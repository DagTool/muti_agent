import asyncio
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hmac import compare_digest
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.core.config import get_settings
from apps.api.app.db.base import (
    ApiToken,
    Approval,
    Artifact,
    AuditLog,
    ModelUsage,
    OutboxEvent,
    Project,
    Requirement,
    Task,
    User,
    WorkflowRun,
    WorkspaceMembership,
    utcnow,
)
from apps.api.app.db.session import get_db, new_session
from apps.api.app.services.workflow import enqueue_task, retry_task
from packages.communication.contracts import TASK_COMMANDS, EventEnvelope
from packages.execution.project_files import safe_relative_path

app = FastAPI(title="AgentForge AI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["X-API-Key", "Idempotency-Key", "Content-Type"],
)
DbSession = Annotated[Session, Depends(get_db)]
IdempotencyKey = Annotated[str, Header(min_length=1, max_length=100)]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    token_budget: int = Field(default=500_000, ge=1_000, le=10_000_000)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str
    status: str
    token_budget: int
    tokens_used: int


class BudgetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token_budget: int = Field(ge=1_000, le=10_000_000)


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    role: str = Field(default="developer", pattern="^developer$")


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    run_id: str | None
    title: str
    role: str
    status: str
    attempt: int
    correlation_id: str
    result: str | None


class RequirementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=10, max_length=50000)


class RequirementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    version: int
    content: str


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: UUID | None = None


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    requirement_id: str
    status: str
    mode: str


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    run_id: str
    action: str
    status: str
    note: str | None
    reviewed_by: str | None


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=10000)


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    run_id: str | None
    task_id: str | None
    kind: str
    content: str


class ActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    action: str
    resource_id: str
    correlation_id: str
    created_at: datetime


class ModelUsageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    run_id: str
    task_id: str
    attempt: int
    model: str
    input_tokens: int
    output_tokens: int
    created_at: datetime


class GeneratedFileRead(BaseModel):
    path: str
    content: str


class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    name: str = Field(min_length=1, max_length=200)
    role: Literal["owner", "member", "viewer"]


class MemberRead(BaseModel):
    id: str
    email: str
    name: str
    role: str


class MemberCreated(MemberRead):
    token_id: str
    api_token: str
    expires_at: datetime


class MemberRoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["owner", "member", "viewer"]


class TokenRead(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


class TokenCreated(TokenRead):
    api_token: str


@dataclass(frozen=True)
class Actor:
    user_id: str | None
    role: str
    workspace_id: str


class ActorRead(BaseModel):
    user_id: str | None
    role: str
    workspace_id: str


def require_api_key(db: DbSession, x_api_key: str | None = Header(default=None)) -> Actor:
    expected = get_settings().api_key
    if not expected:
        raise HTTPException(status_code=503, detail="AGENTFORGE_API_KEY must be configured")
    if not x_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    workspace_id = get_settings().workspace_id
    if compare_digest(x_api_key, expected):
        return Actor(user_id=None, role="owner", workspace_id=workspace_id)
    token_hash = hashlib.sha256(x_api_key.encode("utf-8")).hexdigest()
    row = db.execute(
        select(ApiToken, WorkspaceMembership)
        .join(
            WorkspaceMembership,
            (WorkspaceMembership.user_id == ApiToken.user_id)
            & (WorkspaceMembership.workspace_id == ApiToken.workspace_id),
        )
        .where(
            ApiToken.token_hash == token_hash,
            ApiToken.workspace_id == workspace_id,
            ApiToken.revoked_at.is_(None),
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    token, membership = row
    expires = (
        token.expires_at.replace(tzinfo=UTC)
        if token.expires_at.tzinfo is None
        else token.expires_at
    )
    if expires <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="API token expired")
    return Actor(user_id=token.user_id, role=membership.role, workspace_id=workspace_id)


def require_member(actor: Annotated[Actor, Depends(require_api_key)]) -> Actor:
    if actor.role not in {"owner", "member"}:
        raise HTTPException(status_code=403, detail="Member role required")
    return actor


def require_owner(actor: Annotated[Actor, Depends(require_api_key)]) -> Actor:
    if actor.role != "owner":
        raise HTTPException(status_code=403, detail="Owner role required")
    return actor


@app.get("/api/v1/auth/me", response_model=ActorRead)
def auth_me(actor: Annotated[Actor, Depends(require_api_key)]):
    return ActorRead(user_id=actor.user_id, role=actor.role, workspace_id=actor.workspace_id)


@app.post(
    "/api/v1/members",
    response_model=MemberCreated,
    dependencies=[Depends(require_owner)],
)
def create_member(body: MemberCreate, db: DbSession):
    workspace_id = get_settings().workspace_id
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=body.name)
        db.add(user)
        db.flush()
    existing = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="User is already a workspace member")
    membership = WorkspaceMembership(
        workspace_id=workspace_id,
        user_id=user.id,
        role=body.role,
    )
    token, raw_token = issue_token(workspace_id, user.id)
    expires_at = token.expires_at
    db.add_all([membership, token])
    db.flush()
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            action="member.created",
            resource_id=membership.id,
            correlation_id=str(uuid4()),
        )
    )
    db.commit()
    return MemberCreated(
        id=membership.id,
        email=user.email,
        name=user.name,
        role=membership.role,
        token_id=token.id,
        api_token=raw_token,
        expires_at=expires_at,
    )


def issue_token(workspace_id: str, user_id: str) -> tuple[ApiToken, str]:
    raw_token = secrets.token_urlsafe(32)
    token = ApiToken(
        workspace_id=workspace_id,
        user_id=user_id,
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=utcnow() + timedelta(days=30),
    )
    return token, raw_token


def get_membership_or_404(membership_id: str, db: Session) -> WorkspaceMembership:
    membership = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.id == membership_id,
            WorkspaceMembership.workspace_id == get_settings().workspace_id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return membership


@app.get(
    "/api/v1/members/{membership_id}/tokens",
    response_model=list[TokenRead],
    dependencies=[Depends(require_owner)],
)
def list_member_tokens(membership_id: UUID, db: DbSession):
    membership = get_membership_or_404(str(membership_id), db)
    return db.scalars(
        select(ApiToken)
        .where(
            ApiToken.workspace_id == membership.workspace_id,
            ApiToken.user_id == membership.user_id,
        )
        .order_by(ApiToken.created_at.desc())
    ).all()


@app.post(
    "/api/v1/members/{membership_id}/tokens",
    response_model=TokenCreated,
    dependencies=[Depends(require_owner)],
)
def create_member_token(membership_id: UUID, db: DbSession):
    membership = get_membership_or_404(str(membership_id), db)
    token, raw_token = issue_token(membership.workspace_id, membership.user_id)
    db.add(token)
    db.flush()
    db.add(
        AuditLog(
            workspace_id=membership.workspace_id,
            action="token.created",
            resource_id=token.id,
            correlation_id=str(uuid4()),
        )
    )
    db.commit()
    return TokenCreated(
        id=token.id,
        created_at=token.created_at,
        expires_at=token.expires_at,
        revoked_at=None,
        api_token=raw_token,
    )


@app.get(
    "/api/v1/members",
    response_model=list[MemberRead],
    dependencies=[Depends(require_owner)],
)
def list_members(db: DbSession):
    rows = db.execute(
        select(WorkspaceMembership, User)
        .join(User)
        .where(WorkspaceMembership.workspace_id == get_settings().workspace_id)
        .order_by(User.email)
    ).all()
    return [
        MemberRead(id=membership.id, email=user.email, name=user.name, role=membership.role)
        for membership, user in rows
    ]


@app.post(
    "/api/v1/members/{membership_id}/role",
    response_model=MemberRead,
    dependencies=[Depends(require_owner)],
)
def update_member_role(membership_id: UUID, body: MemberRoleUpdate, db: DbSession):
    membership = db.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.id == str(membership_id),
            WorkspaceMembership.workspace_id == get_settings().workspace_id,
        )
        .with_for_update()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found")
    membership.role = body.role
    user = db.get(User, membership.user_id)
    db.add(
        AuditLog(
            workspace_id=membership.workspace_id,
            action="member.role_updated",
            resource_id=membership.id,
            correlation_id=str(uuid4()),
        )
    )
    db.commit()
    return MemberRead(id=membership.id, email=user.email, name=user.name, role=membership.role)


@app.post(
    "/api/v1/tokens/{token_id}/revoke",
    dependencies=[Depends(require_owner)],
)
def revoke_token(token_id: UUID, db: DbSession):
    token = db.scalar(
        select(ApiToken)
        .where(
            ApiToken.id == str(token_id),
            ApiToken.workspace_id == get_settings().workspace_id,
        )
        .with_for_update()
    )
    if token is None:
        raise HTTPException(status_code=404, detail="Token not found")
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        db.add(
            AuditLog(
                workspace_id=token.workspace_id,
                action="token.revoked",
                resource_id=token.id,
                correlation_id=str(uuid4()),
            )
        )
        db.commit()
    return {"status": "revoked"}


def get_project_or_404(project_id: str, db: Session) -> Project:
    project = db.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.workspace_id == get_settings().workspace_id,
        )
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_run_or_404(run_id: str, db: Session, lock: bool = False) -> WorkflowRun:
    query = (
        select(WorkflowRun)
        .join(Project)
        .where(WorkflowRun.id == run_id, Project.workspace_id == get_settings().workspace_id)
    )
    if lock:
        query = query.with_for_update(of=WorkflowRun)
    run = db.scalar(query)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def ready(db: DbSession):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok"}


@app.post("/api/v1/projects", response_model=ProjectRead, dependencies=[Depends(require_member)])
def create_project(
    body: ProjectCreate,
    idempotency_key: IdempotencyKey,
    db: DbSession,
):
    workspace_id = get_settings().workspace_id
    existing = db.scalar(
        select(Project).where(
            Project.workspace_id == workspace_id, Project.request_key == idempotency_key
        )
    )
    if existing:
        if (
            existing.name != body.name
            or existing.description != body.description
            or existing.token_budget != body.token_budget
        ):
            raise HTTPException(
                status_code=409, detail="Idempotency key reused with different body"
            )
        return existing
    project = Project(
        workspace_id=workspace_id,
        name=body.name,
        description=body.description,
        token_budget=body.token_budget,
        request_key=idempotency_key,
    )
    db.add(project)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(Project).where(
                Project.workspace_id == workspace_id, Project.request_key == idempotency_key
            )
        )
        if existing:
            if (
                existing.name != body.name
                or existing.description != body.description
                or existing.token_budget != body.token_budget
            ):
                raise HTTPException(
                    status_code=409, detail="Idempotency key reused with different body"
                )
            return existing
        raise
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            project_id=project.id,
            action="project.created",
            resource_id=project.id,
            correlation_id=str(uuid4()),
        )
    )
    db.commit()
    return project


@app.get(
    "/api/v1/projects", response_model=list[ProjectRead], dependencies=[Depends(require_api_key)]
)
def list_projects(db: DbSession):
    return db.scalars(
        select(Project)
        .where(Project.workspace_id == get_settings().workspace_id)
        .order_by(Project.created_at.desc())
        .limit(100)
    ).all()


@app.get(
    "/api/v1/projects/{project_id}",
    response_model=ProjectRead,
    dependencies=[Depends(require_api_key)],
)
def get_project(project_id: UUID, db: DbSession):
    return get_project_or_404(str(project_id), db)


@app.post(
    "/api/v1/projects/{project_id}/budget",
    response_model=ProjectRead,
    dependencies=[Depends(require_owner)],
)
def update_project_budget(project_id: UUID, body: BudgetUpdate, db: DbSession):
    project = db.scalar(
        select(Project)
        .where(
            Project.id == str(project_id),
            Project.workspace_id == get_settings().workspace_id,
        )
        .with_for_update()
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if body.token_budget < project.tokens_used:
        raise HTTPException(status_code=409, detail="Budget cannot be below tokens already used")
    project.token_budget = body.token_budget
    db.add(
        AuditLog(
            workspace_id=project.workspace_id,
            project_id=project.id,
            action="project.budget_updated",
            resource_id=project.id,
            correlation_id=str(uuid4()),
        )
    )
    db.commit()
    return project


@app.post(
    "/api/v1/projects/{project_id}/tasks",
    response_model=TaskRead,
    dependencies=[Depends(require_member)],
)
def create_task(
    project_id: UUID,
    body: TaskCreate,
    idempotency_key: IdempotencyKey,
    db: DbSession,
):
    project = get_project_or_404(str(project_id), db)
    existing = db.scalar(
        select(Task).where(Task.project_id == project.id, Task.request_key == idempotency_key)
    )
    if existing:
        if existing.title != body.title or existing.role != body.role:
            raise HTTPException(
                status_code=409, detail="Idempotency key reused with different body"
            )
        return existing
    correlation_id = uuid4()
    execution_id = uuid4()
    task = Task(
        project_id=project.id,
        title=body.title,
        role=body.role,
        correlation_id=str(correlation_id),
        request_key=idempotency_key,
    )
    db.add(task)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(Task).where(Task.project_id == project.id, Task.request_key == idempotency_key)
        )
        if existing:
            if existing.title != body.title or existing.role != body.role:
                raise HTTPException(
                    status_code=409, detail="Idempotency key reused with different body"
                )
            return existing
        raise
    event = EventEnvelope(
        event_type="task.execute.requested",
        correlation_id=correlation_id,
        workspace_id=project.workspace_id,
        project_id=UUID(project.id),
        task_id=UUID(task.id),
        execution_id=execution_id,
        idempotency_key=f"{task.id}:attempt-1",
        sender="api",
        recipient_role=task.role,
        attempt=1,
        payload={"instructions": task.title, "acceptance_criteria": []},
    )
    db.add(
        OutboxEvent(topic=TASK_COMMANDS, event_key=task.id, payload=event.model_dump(mode="json"))
    )
    db.add(
        AuditLog(
            workspace_id=project.workspace_id,
            project_id=project.id,
            action="task.created",
            resource_id=task.id,
            correlation_id=task.correlation_id,
        )
    )
    db.commit()
    return task


@app.get(
    "/api/v1/projects/{project_id}/tasks",
    response_model=list[TaskRead],
    dependencies=[Depends(require_api_key)],
)
def list_tasks(project_id: UUID, db: DbSession):
    project = get_project_or_404(str(project_id), db)
    return db.scalars(
        select(Task)
        .where(Task.project_id == project.id)
        .order_by(Task.created_at.desc())
        .limit(100)
    ).all()


@app.get(
    "/api/v1/tasks/{task_id}", response_model=TaskRead, dependencies=[Depends(require_api_key)]
)
def get_task(task_id: UUID, db: DbSession):
    task = db.scalar(
        select(Task)
        .join(Project)
        .where(Task.id == str(task_id), Project.workspace_id == get_settings().workspace_id)
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post(
    "/api/v1/projects/{project_id}/requirements",
    response_model=RequirementRead,
    dependencies=[Depends(require_member)],
)
def create_requirement(project_id: UUID, body: RequirementCreate, db: DbSession):
    project = get_project_or_404(str(project_id), db)
    db.scalar(select(Project).where(Project.id == project.id).with_for_update())
    version = (
        db.scalar(select(func.max(Requirement.version)).where(Requirement.project_id == project.id))
        or 0
    ) + 1
    requirement = Requirement(project_id=project.id, version=version, content=body.content)
    db.add(requirement)
    db.flush()
    db.add(
        AuditLog(
            workspace_id=project.workspace_id,
            project_id=project.id,
            action="requirement.created",
            resource_id=requirement.id,
            correlation_id=str(uuid4()),
        )
    )
    db.commit()
    return requirement


@app.get(
    "/api/v1/projects/{project_id}/requirements",
    response_model=list[RequirementRead],
    dependencies=[Depends(require_api_key)],
)
def list_requirements(project_id: UUID, db: DbSession):
    project = get_project_or_404(str(project_id), db)
    return db.scalars(
        select(Requirement)
        .where(Requirement.project_id == project.id)
        .order_by(Requirement.version.desc())
        .limit(100)
    ).all()


@app.post(
    "/api/v1/projects/{project_id}/runs",
    response_model=RunRead,
    dependencies=[Depends(require_member)],
)
def create_run(project_id: UUID, body: RunCreate, idempotency_key: IdempotencyKey, db: DbSession):
    project = get_project_or_404(str(project_id), db)
    existing = db.scalar(
        select(WorkflowRun).where(
            WorkflowRun.project_id == project.id, WorkflowRun.request_key == idempotency_key
        )
    )
    if existing:
        if body.requirement_id and existing.requirement_id != str(body.requirement_id):
            raise HTTPException(
                status_code=409, detail="Idempotency key reused with different body"
            )
        return existing
    requirement = (
        db.scalar(
            select(Requirement).where(
                Requirement.project_id == project.id, Requirement.id == str(body.requirement_id)
            )
        )
        if body.requirement_id
        else db.scalar(
            select(Requirement)
            .where(Requirement.project_id == project.id)
            .order_by(Requirement.version.desc())
            .limit(1)
        )
    )
    if requirement is None:
        raise HTTPException(status_code=409, detail="Create a project requirement first")
    mode = get_settings().agent_mode
    if mode not in {"mock", "openai"}:
        raise HTTPException(status_code=503, detail="Unsupported agent mode")
    run = WorkflowRun(
        project_id=project.id,
        requirement_id=requirement.id,
        request_key=idempotency_key,
        mode=mode,
        status="running" if mode == "openai" else "awaiting_scope_approval",
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(WorkflowRun).where(
                WorkflowRun.project_id == project.id, WorkflowRun.request_key == idempotency_key
            )
        )
        if existing:
            if body.requirement_id and existing.requirement_id != str(body.requirement_id):
                raise HTTPException(
                    status_code=409, detail="Idempotency key reused with different body"
                )
            return existing
        raise
    if mode == "openai":
        enqueue_task(
            db,
            project,
            f"Prepare PRD for requirement v{requirement.version}",
            "pm",
            request_key=f"{run.id}:pm",
            run=run,
        )
    else:
        db.add(Approval(run_id=run.id, action="scope"))
        db.add(
            Artifact(
                project_id=project.id,
                run_id=run.id,
                kind="mock_prd_draft",
                content=f"# Draft scope (mock)\n\n{requirement.content}\n\nReview this scope before work starts.",
            )
        )
    db.add(
        AuditLog(
            workspace_id=project.workspace_id,
            project_id=project.id,
            action="run.created",
            resource_id=run.id,
            correlation_id=str(uuid4()),
        )
    )
    db.commit()
    return run


@app.get(
    "/api/v1/projects/{project_id}/runs",
    response_model=list[RunRead],
    dependencies=[Depends(require_api_key)],
)
def list_runs(project_id: UUID, db: DbSession):
    project = get_project_or_404(str(project_id), db)
    return db.scalars(
        select(WorkflowRun)
        .where(WorkflowRun.project_id == project.id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(100)
    ).all()


@app.get("/api/v1/runs/{run_id}", response_model=RunRead, dependencies=[Depends(require_api_key)])
def get_run(run_id: UUID, db: DbSession):
    return get_run_or_404(str(run_id), db)


def generated_root(run: WorkflowRun) -> Path:
    base = Path(get_settings().artifact_root).resolve()
    root = base / run.project_id / run.id
    if run.mode != "openai" or not root.is_dir() or root.is_symlink():
        raise HTTPException(status_code=404, detail="Generated files not found")
    resolved = root.resolve(strict=True)
    if not resolved.is_relative_to(base):
        raise HTTPException(status_code=404, detail="Generated files not found")
    return resolved


@app.get(
    "/api/v1/runs/{run_id}/files",
    response_model=list[str],
    dependencies=[Depends(require_api_key)],
)
def list_generated_files(run_id: UUID, db: DbSession):
    root = generated_root(get_run_or_404(str(run_id), db))
    files = []
    for file in root.rglob("*"):
        if not file.is_file() or file.is_symlink():
            continue
        relative = file.relative_to(root).as_posix()
        try:
            safe_relative_path(relative)
        except ValueError:
            continue
        files.append(relative)
        if len(files) > 100:
            raise HTTPException(status_code=413, detail="Too many generated files")
    return sorted(files)


@app.get(
    "/api/v1/runs/{run_id}/file",
    response_model=GeneratedFileRead,
    dependencies=[Depends(require_api_key)],
)
def read_generated_file(run_id: UUID, path: str, db: DbSession):
    root = generated_root(get_run_or_404(str(run_id), db))
    try:
        relative = safe_relative_path(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file path") from exc
    target = root.joinpath(*relative.parts)
    if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(root):
        raise HTTPException(status_code=404, detail="Generated file not found")
    if target.stat().st_size > 100_000:
        raise HTTPException(status_code=413, detail="Generated file too large")
    return GeneratedFileRead(path=str(relative), content=target.read_text(encoding="utf-8"))


@app.post(
    "/api/v1/runs/{run_id}/cancel", response_model=RunRead, dependencies=[Depends(require_member)]
)
def cancel_run(run_id: UUID, db: DbSession):
    run = get_run_or_404(str(run_id), db, lock=True)
    if run.status in {"completed", "cancelled"}:
        return run
    run.status = "cancelled"
    for approval in db.scalars(
        select(Approval).where(Approval.run_id == run.id, Approval.status == "pending")
    ):
        approval.status = "cancelled"
    for task in db.scalars(
        select(Task).where(Task.run_id == run.id, Task.status.in_(("ready", "running")))
    ):
        task.status = "cancelled"
    project = get_project_or_404(run.project_id, db)
    db.add(
        AuditLog(
            workspace_id=project.workspace_id,
            project_id=project.id,
            action="run.cancelled",
            resource_id=run.id,
            correlation_id=str(uuid4()),
        )
    )
    db.commit()
    return run


@app.post(
    "/api/v1/runs/{run_id}/resume",
    response_model=RunRead,
    dependencies=[Depends(require_member)],
)
def resume_run(run_id: UUID, db: DbSession):
    run = get_run_or_404(str(run_id), db, lock=True)
    if run.status != "blocked" or run.mode != "openai":
        raise HTTPException(status_code=409, detail="Only blocked OpenAI runs can be resumed")
    task = db.scalar(
        select(Task)
        .where(Task.run_id == run.id, Task.status == "failed")
        .order_by(Task.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if task is None or task.attempt >= 3:
        raise HTTPException(status_code=409, detail="No retryable failed task")
    project = get_project_or_404(run.project_id, db)
    retry_task(db, project, task)
    run.status = "running"
    db.commit()
    return run


@app.get(
    "/api/v1/approvals",
    response_model=list[ApprovalRead],
    dependencies=[Depends(require_api_key)],
)
def list_approvals(db: DbSession, status: str = "pending"):
    if status not in {"pending", "approved", "rejected", "cancelled"}:
        raise HTTPException(status_code=422, detail="Invalid approval status")
    return db.scalars(
        select(Approval)
        .join(WorkflowRun)
        .join(Project)
        .where(Project.workspace_id == get_settings().workspace_id, Approval.status == status)
        .order_by(Approval.created_at.desc())
        .limit(100)
    ).all()


@app.post(
    "/api/v1/approvals/{approval_id}/decision",
    response_model=ApprovalRead,
)
def decide_approval(
    approval_id: UUID,
    body: ApprovalDecision,
    db: DbSession,
    actor: Annotated[Actor, Depends(require_owner)],
):
    approval = db.get(Approval, str(approval_id))
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    run = get_run_or_404(approval.run_id, db, lock=True)
    approval = db.scalar(
        select(Approval)
        .where(Approval.id == str(approval_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    target_status = "approved" if body.decision == "approve" else "rejected"
    if approval.status != "pending":
        if approval.status == target_status:
            return approval
        raise HTTPException(status_code=409, detail="Approval already decided")
    expected_run_status = (
        "awaiting_scope_approval" if approval.action == "scope" else "awaiting_handover_approval"
    )
    if run.status != expected_run_status:
        raise HTTPException(status_code=409, detail="Run is not awaiting this approval")
    approval.status = target_status
    approval.note = body.note
    approval.reviewed_by = actor.user_id or "local-owner"
    approval.reviewed_at = utcnow()
    project = get_project_or_404(run.project_id, db)
    if body.decision == "reject":
        run.status = "blocked"
    elif approval.action == "scope":
        requirement = db.get(Requirement, run.requirement_id)
        enqueue_task(
            db,
            project,
            f"{'Design' if run.mode == 'openai' else 'Implement'} requirement v{requirement.version}",
            "architect" if run.mode == "openai" else "developer",
            request_key=f"{run.id}:{'architect' if run.mode == 'openai' else 'developer'}",
            run=run,
        )
        run.status = "running"
    else:
        run.status = "completed"
    db.add(
        AuditLog(
            workspace_id=project.workspace_id,
            project_id=project.id,
            action=f"approval.{target_status}",
            resource_id=approval.id,
            correlation_id=str(uuid4()),
        )
    )
    db.commit()
    return approval


@app.get(
    "/api/v1/projects/{project_id}/artifacts",
    response_model=list[ArtifactRead],
    dependencies=[Depends(require_api_key)],
)
def list_artifacts(project_id: UUID, db: DbSession):
    project = get_project_or_404(str(project_id), db)
    return db.scalars(
        select(Artifact)
        .where(Artifact.project_id == project.id)
        .order_by(Artifact.created_at.desc())
        .limit(100)
    ).all()


@app.get(
    "/api/v1/projects/{project_id}/activity",
    response_model=list[ActivityRead],
    dependencies=[Depends(require_api_key)],
)
def list_activity(project_id: UUID, db: DbSession):
    project = get_project_or_404(str(project_id), db)
    return db.scalars(
        select(AuditLog)
        .where(AuditLog.project_id == project.id)
        .order_by(AuditLog.created_at.desc())
        .limit(100)
    ).all()


def activity_revision(project_id: str, workspace_id: str) -> int:
    with new_session() as db:
        return (
            db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.project_id == project_id,
                    AuditLog.workspace_id == workspace_id,
                )
            )
            or 0
        )


@app.get("/api/v1/projects/{project_id}/events")
async def stream_project_events(
    project_id: UUID,
    x_api_key: str | None = Header(default=None),
):
    with new_session() as db:
        actor = require_api_key(db, x_api_key)
        project_id_value = get_project_or_404(str(project_id), db).id
        workspace_id = actor.workspace_id

    async def events():
        revision = await asyncio.to_thread(activity_revision, project_id_value, workspace_id)
        yield f"event: ready\ndata: {json.dumps({'revision': revision})}\n\n"
        for _ in range(30):
            await asyncio.sleep(2)
            current = await asyncio.to_thread(activity_revision, project_id_value, workspace_id)
            if current != revision:
                revision = current
                yield f"event: change\ndata: {json.dumps({'revision': revision})}\n\n"
            else:
                yield ": keepalive\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.get(
    "/api/v1/projects/{project_id}/model-usage",
    response_model=list[ModelUsageRead],
    dependencies=[Depends(require_api_key)],
)
def list_model_usage(project_id: UUID, db: DbSession):
    project = get_project_or_404(str(project_id), db)
    return db.scalars(
        select(ModelUsage)
        .where(ModelUsage.project_id == project.id)
        .order_by(ModelUsage.created_at.desc())
        .limit(100)
    ).all()

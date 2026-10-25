from hmac import compare_digest
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.app.core.config import get_settings
from apps.api.app.db.base import AuditLog, OutboxEvent, Project, Task
from apps.api.app.db.session import get_db
from packages.communication.contracts import TASK_COMMANDS, EventEnvelope

app = FastAPI(title="AgentForge AI", version="0.1.0")
DbSession = Annotated[Session, Depends(get_db)]
IdempotencyKey = Annotated[str, Header(min_length=1, max_length=100)]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str
    status: str


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=300)
    role: str = Field(default="developer", pattern="^developer$")


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    title: str
    role: str
    status: str
    attempt: int
    correlation_id: str
    result: str | None


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if not expected:
        raise HTTPException(status_code=503, detail="AGENTFORGE_API_KEY must be configured")
    if not x_api_key or not compare_digest(x_api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


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


@app.post("/api/v1/projects", response_model=ProjectRead, dependencies=[Depends(require_api_key)])
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
        if existing.name != body.name or existing.description != body.description:
            raise HTTPException(
                status_code=409, detail="Idempotency key reused with different body"
            )
        return existing
    project = Project(
        workspace_id=workspace_id,
        name=body.name,
        description=body.description,
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
            if existing.name != body.name or existing.description != body.description:
                raise HTTPException(
                    status_code=409, detail="Idempotency key reused with different body"
                )
            return existing
        raise
    db.add(
        AuditLog(
            workspace_id=workspace_id,
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
    "/api/v1/projects/{project_id}/tasks",
    response_model=TaskRead,
    dependencies=[Depends(require_api_key)],
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

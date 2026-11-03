"""OpenAI backed workflow worker. Generated code is tested only in the sandbox."""

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread

from sqlalchemy import select

from apps.api.app.core.config import get_settings
from apps.api.app.db.base import (
    Approval,
    Artifact,
    AuditLog,
    ModelUsage,
    OutboxEvent,
    ProcessedEvent,
    Project,
    Requirement,
    Task,
    WorkflowRun,
    utcnow,
)
from apps.api.app.db.session import new_session
from apps.api.app.services.workflow import enqueue_task
from packages.agent_runtime.openai_adapter import generate_project, generate_text
from packages.communication.contracts import TASK_RESULTS, EventEnvelope
from packages.execution.git_workspace import commit_project
from packages.execution.project_files import write_project_files
from packages.execution.sandbox_manager import run_in_sandbox

log = logging.getLogger(__name__)
ROLES = {"pm", "architect", "developer", "qa"}
HEARTBEAT_INTERVAL_SECONDS = 30


@dataclass(frozen=True)
class WorkOutput:
    kind: str
    content: str
    summary: str
    input_tokens: int = 0
    output_tokens: int = 0
    passed: bool = True


def _workspace(project_id: str, run_id: str) -> Path:
    return Path(get_settings().artifact_root).resolve() / project_id / run_id


def heartbeat_task(task_id: str, run_id: str, attempt: int) -> bool:
    """Refresh only the claim still owned by this running attempt."""
    with new_session() as db:
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update())
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if (
            run is None
            or task is None
            or run.status != "running"
            or task.status != "running"
            or task.run_id != run_id
            or task.attempt != attempt
        ):
            return False
        task.updated_at = utcnow()
        db.commit()
        return True


@contextmanager
def keep_task_alive(task_id: str, run_id: str, attempt: int):
    """Keep a slow model or sandbox call from being mistaken for a dead worker."""
    stopped = Event()

    def pulse():
        while not stopped.wait(HEARTBEAT_INTERVAL_SECONDS):
            try:
                if not heartbeat_task(task_id, run_id, attempt):
                    return
            except Exception:
                log.exception("AI task heartbeat failed")

    thread = Thread(target=pulse, name=f"ai-heartbeat-{task_id}", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join()


def _perform(
    role: str, project_id: str, run_id: str, requirement: str, prd: str, design: str
) -> WorkOutput:
    model = get_settings().openai_model
    if role == "pm":
        response = generate_text(
            "You are a software PM. Write a concise Markdown PRD with user stories, "
            "acceptance criteria, scope and explicit assumptions. Do not claim code was built.",
            requirement,
            model,
        )
        return WorkOutput(
            "prd", response.text, "PRD prepared", response.input_tokens, response.output_tokens
        )
    if role == "architect":
        response = generate_text(
            "You are a software architect. Write a concise Markdown technical design "
            "for a small Python 3.13 standard-library project. Include modules, data model, "
            "interfaces, tests, and tradeoffs. No shell commands or secrets.",
            f"Requirement:\n{requirement}\n\nApproved PRD:\n{prd}",
            model,
        )
        return WorkOutput(
            "architecture",
            response.text,
            "Architecture prepared",
            response.input_tokens,
            response.output_tokens,
        )
    if role == "developer":
        root = _workspace(project_id, run_id)
        if root.exists():
            paths = [
                path
                for path in root.rglob("*")
                if path.is_file() and ".git" not in path.relative_to(root).parts
            ]
            if not paths or not (root / "README.md").is_file():
                raise RuntimeError("Existing generated workspace is incomplete")
            return WorkOutput(
                "generated_project",
                "# Recovered generated project\n\nFiles:\n"
                + "\n".join(f"- {path.relative_to(root).as_posix()}" for path in paths),
                "Recovered generated project after worker interruption",
            )
        project, usage = generate_project(
            f"Requirement:\n{requirement}\n\nPRD:\n{prd}\n\nDesign:\n{design}", model
        )
        paths = write_project_files(root, project)
        commit = commit_project(root, "AgentForge generated project")
        content = (
            "# Generated project\n\n"
            + project.summary
            + "\n\nFiles:\n"
            + "\n".join(f"- {path.relative_to(root).as_posix()}" for path in paths)
            + f"\n\nGit commit: `{commit}`"
        )
        return WorkOutput(
            "generated_project",
            content,
            project.summary,
            usage.input_tokens,
            usage.output_tokens,
        )
    if role == "qa":
        root = _workspace(project_id, run_id)
        compile_result = run_in_sandbox(root, ["python", "-m", "compileall", "."])
        tests = run_in_sandbox(root, ["python", "-m", "unittest", "discover", "-s", "tests", "-v"])
        count = re.search(r"Ran (\d+) tests?", tests.stderr + tests.stdout)
        passed = (
            compile_result.exit_code == 0
            and tests.exit_code == 0
            and count is not None
            and int(count.group(1)) > 0
        )
        report = (
            f"# QA report\n\nCompile exit: {compile_result.exit_code}\n"
            f"Test exit: {tests.exit_code}\n\n"
            f"```text\n{tests.stdout[-12000:]}\n{tests.stderr[-12000:]}\n```"
        )
        if passed:
            report += f"\nGit commit: `{commit_project(root, 'AgentForge QA verified project')}`"
        return WorkOutput(
            "qa_report", report, "QA passed" if passed else "QA failed", passed=passed
        )
    raise ValueError("Unsupported AI worker role")


def process_ai_event(event: EventEnvelope, role: str) -> bool:
    """Claim, execute and finalize one AI task. An interrupted claim needs recovery."""
    if (
        role not in ROLES
        or event.event_type != "task.execute.requested"
        or event.recipient_role != role
    ):
        raise ValueError("Unsupported event for AI worker")
    consumer_name = f"openai-{role}-v1"
    with new_session() as db:
        task = db.get(Task, str(event.task_id))
        if task is None or task.role != role or task.run_id is None:
            raise ValueError("Task/role mismatch")
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == task.run_id).with_for_update())
        task = db.scalar(
            select(Task)
            .where(Task.id == str(event.task_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        project = db.get(Project, task.project_id)
        if (
            run is None
            or run.mode != "openai"
            or project is None
            or project.id != str(event.project_id)
            or project.workspace_id != event.workspace_id
            or task.attempt != event.attempt
        ):
            raise ValueError("AI task/run/event mismatch")
        if db.scalar(
            select(ProcessedEvent).where(
                ProcessedEvent.consumer_name == consumer_name,
                ProcessedEvent.event_id == str(event.event_id),
            )
        ):
            return False
        if run.status == "cancelled":
            task.status = "cancelled"
            db.add(ProcessedEvent(consumer_name=consumer_name, event_id=str(event.event_id)))
            db.commit()
            return False
        if task.status != "ready" or run.status != "running":
            return False
        budget_exhausted = project.tokens_used >= project.token_budget
        task.status = "running"
        requirement = db.get(Requirement, run.requirement_id).content
        artifacts = db.scalars(select(Artifact).where(Artifact.run_id == run.id)).all()
        prd = next((item.content for item in artifacts if item.kind == "prd"), "")
        design = next((item.content for item in artifacts if item.kind == "architecture"), "")
        project_id, run_id = project.id, run.id
        db.commit()

    try:
        with keep_task_alive(str(event.task_id), run_id, event.attempt):
            if budget_exhausted:
                raise RuntimeError("TokenBudgetExceeded")
            output = _perform(role, project_id, run_id, requirement, prd, design)
    except Exception as exc:
        log.exception("AI task failed: %s", type(exc).__name__)
        with new_session() as db:
            run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update())
            task = db.scalar(select(Task).where(Task.id == str(event.task_id)).with_for_update())
            if (
                run.status != "cancelled"
                and task.status == "running"
                and task.attempt == event.attempt
            ):
                task.status = "failed"
                task.result = f"Agent failed: {type(exc).__name__}"
                run.status = "blocked"
                db.add(
                    AuditLog(
                        workspace_id=event.workspace_id,
                        project_id=project_id,
                        action="task.failed",
                        resource_id=task.id,
                        correlation_id=task.correlation_id,
                    )
                )
            db.add(ProcessedEvent(consumer_name=consumer_name, event_id=str(event.event_id)))
            db.commit()
        return True

    with new_session() as db:
        run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update())
        task = db.scalar(select(Task).where(Task.id == str(event.task_id)).with_for_update())
        project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        if task.attempt != event.attempt:
            raise ValueError("AI task attempt changed during execution")
        if output.input_tokens or output.output_tokens:
            db.add(
                ModelUsage(
                    project_id=project_id,
                    run_id=run_id,
                    task_id=task.id,
                    attempt=event.attempt,
                    model=get_settings().openai_model,
                    input_tokens=output.input_tokens,
                    output_tokens=output.output_tokens,
                )
            )
            project.tokens_used += output.input_tokens + output.output_tokens
        if run.status == "cancelled":
            task.status = "cancelled"
        elif run.status != "running" or task.status != "running":
            raise ValueError("AI task changed during execution")
        else:
            task.status = "completed" if output.passed else "failed"
            task.result = output.summary[:2000]
            db.add(
                Artifact(
                    project_id=project_id,
                    run_id=run_id,
                    task_id=task.id,
                    kind=output.kind,
                    content=output.content[:100_000],
                )
            )
            if not output.passed or project.tokens_used >= project.token_budget:
                run.status = "blocked"
            elif role == "pm":
                db.add(Approval(run_id=run_id, action="scope"))
                run.status = "awaiting_scope_approval"
            elif role == "architect":
                enqueue_task(
                    db,
                    project,
                    "Implement approved requirement",
                    "developer",
                    request_key=f"{run_id}:developer",
                    run=run,
                )
            elif role == "developer":
                enqueue_task(
                    db,
                    project,
                    "Test generated project",
                    "qa",
                    request_key=f"{run_id}:qa",
                    run=run,
                )
            elif role == "qa":
                db.add(Approval(run_id=run_id, action="handover"))
                run.status = "awaiting_handover_approval"
            result = EventEnvelope(
                event_type="task.execute.completed",
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                workspace_id=event.workspace_id,
                project_id=event.project_id,
                task_id=event.task_id,
                execution_id=event.execution_id,
                idempotency_key=event.idempotency_key,
                sender=f"openai-{role}",
                recipient_role="orchestrator",
                attempt=event.attempt,
                payload={"result": task.result, "passed": output.passed},
            )
            db.add(
                OutboxEvent(
                    topic=TASK_RESULTS, event_key=task.id, payload=result.model_dump(mode="json")
                )
            )
            db.add(
                AuditLog(
                    workspace_id=project.workspace_id,
                    project_id=project.id,
                    action="task.completed" if output.passed else "task.failed",
                    resource_id=task.id,
                    correlation_id=task.correlation_id,
                )
            )
        db.add(ProcessedEvent(consumer_name=consumer_name, event_id=str(event.event_id)))
        db.commit()
    return True

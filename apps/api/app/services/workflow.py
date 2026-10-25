from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from apps.api.app.db.base import AuditLog, OutboxEvent, Project, Task, WorkflowRun
from packages.communication.contracts import TASK_COMMANDS, EventEnvelope


def enqueue_task(
    db: Session,
    project: Project,
    title: str,
    role: str,
    request_key: str,
    run: WorkflowRun | None = None,
) -> Task:
    correlation_id = uuid4()
    task = Task(
        project_id=project.id,
        run_id=run.id if run else None,
        title=title,
        role=role,
        correlation_id=str(correlation_id),
        request_key=request_key,
    )
    db.add(task)
    db.flush()
    event = EventEnvelope(
        event_type="task.execute.requested",
        correlation_id=correlation_id,
        workspace_id=project.workspace_id,
        project_id=UUID(project.id),
        task_id=UUID(task.id),
        execution_id=uuid4(),
        idempotency_key=f"{task.id}:attempt-1",
        sender="orchestrator" if run else "api",
        recipient_role=role,
        attempt=1,
        payload={
            "instructions": title,
            "acceptance_criteria": [],
            "mode": run.mode if run else "mock",
        },
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
    return task


def retry_task(db: Session, project: Project, task: Task) -> None:
    """Create a new execution command for the next bounded attempt."""
    if task.attempt >= 3:
        raise ValueError("Task reached retry limit")
    task.attempt += 1
    task.status = "ready"
    task.result = None
    event = EventEnvelope(
        event_type="task.execute.requested",
        correlation_id=UUID(task.correlation_id),
        workspace_id=project.workspace_id,
        project_id=UUID(project.id),
        task_id=UUID(task.id),
        execution_id=uuid4(),
        idempotency_key=f"{task.id}:attempt-{task.attempt}",
        sender="orchestrator",
        recipient_role=task.role,
        attempt=task.attempt,
        payload={
            "instructions": task.title,
            "acceptance_criteria": [],
            "mode": "openai" if task.run_id else "mock",
        },
    )
    db.add(
        OutboxEvent(topic=TASK_COMMANDS, event_key=task.id, payload=event.model_dump(mode="json"))
    )
    db.add(
        AuditLog(
            workspace_id=project.workspace_id,
            project_id=project.id,
            action="task.retried",
            resource_id=task.id,
            correlation_id=task.correlation_id,
        )
    )

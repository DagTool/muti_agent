import argparse
import logging
import time

from pydantic import ValidationError
from sqlalchemy import select

from apps.api.app.core.config import get_settings
from apps.api.app.db.base import (
    Approval,
    Artifact,
    AuditLog,
    OutboxEvent,
    ProcessedEvent,
    Project,
    Task,
    WorkflowRun,
)
from apps.api.app.db.session import new_session
from apps.api.app.services.workflow import enqueue_task
from packages.communication.contracts import (
    TASK_DLQ,
    TASK_RESULTS,
    TASKS_ARCHITECT,
    TASKS_DEVELOPER,
    TASKS_PM,
    TASKS_QA,
    EventEnvelope,
)
from packages.communication.kafka import consumer, producer, publish_sync

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
CONSUMER_NAMES = {"developer": "mock-developer-v1", "qa": "mock-qa-v1"}


def process_event(event: EventEnvelope, role: str = "developer") -> bool:
    """Return True when work was applied, False for an already processed delivery."""
    if event.event_type != "task.execute.requested" or event.recipient_role != role:
        raise ValueError("Unsupported event for worker")
    consumer_name = CONSUMER_NAMES[role]

    with new_session() as db:
        already = db.scalar(
            select(ProcessedEvent).where(
                ProcessedEvent.consumer_name == consumer_name,
                ProcessedEvent.event_id == str(event.event_id),
            )
        )
        if already:
            return False
        task = db.get(Task, str(event.task_id))
        if task is None:
            raise ValueError("Task not found")
        run = (
            db.scalar(select(WorkflowRun).where(WorkflowRun.id == task.run_id).with_for_update())
            if task.run_id
            else None
        )
        if run and run.mode != "mock":
            raise ValueError("This run requires the OpenAI worker")
        task = db.scalar(select(Task).where(Task.id == str(event.task_id)).with_for_update())
        # A second read after acquiring the task lock closes the concurrent duplicate race.
        already = db.scalar(
            select(ProcessedEvent).where(
                ProcessedEvent.consumer_name == consumer_name,
                ProcessedEvent.event_id == str(event.event_id),
            )
        )
        if already:
            return False
        project = db.get(Project, str(event.project_id))
        if task is None or project is None or task.project_id != project.id:
            raise ValueError("Task/project mismatch")
        if project.workspace_id != event.workspace_id:
            raise ValueError("Workspace mismatch")
        if task.status == "completed":
            db.add(ProcessedEvent(consumer_name=consumer_name, event_id=str(event.event_id)))
            db.commit()
            return False
        if run and run.status == "cancelled":
            task.status = "cancelled"
            db.add(ProcessedEvent(consumer_name=consumer_name, event_id=str(event.event_id)))
            db.commit()
            return False
        if task.status != "ready" or task.attempt != event.attempt:
            raise ValueError(f"Unexpected task status/attempt: {task.status}/{task.attempt}")
        if run and run.status != "running":
            raise ValueError(f"Run is not running: {run.status}")

        # Deliberately a deterministic mock. Real code execution requires an isolated sandbox.
        task.status = "completed"
        task.result = f"Mock {role} completed: {task.title}"
        if run and role == "developer":
            db.add(
                Artifact(
                    project_id=project.id,
                    run_id=run.id,
                    task_id=task.id,
                    kind="mock_implementation_note",
                    content=task.result,
                )
            )
            enqueue_task(
                db,
                project,
                f"Review run {run.id}",
                "qa",
                request_key=f"{run.id}:qa",
                run=run,
            )
        elif run and role == "qa":
            db.add(
                Artifact(
                    project_id=project.id,
                    run_id=run.id,
                    task_id=task.id,
                    kind="mock_qa_report",
                    content="Mock QA passed; no code was executed.",
                )
            )
            db.add(Approval(run_id=run.id, action="handover"))
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
            sender=f"mock-{role}",
            recipient_role="orchestrator",
            attempt=event.attempt,
            payload={"result": task.result},
        )
        db.add(
            OutboxEvent(
                topic=TASK_RESULTS, event_key=task.id, payload=result.model_dump(mode="json")
            )
        )
        db.add(ProcessedEvent(consumer_name=consumer_name, event_id=str(event.event_id)))
        db.add(
            AuditLog(
                workspace_id=project.workspace_id,
                project_id=project.id,
                action="task.completed",
                resource_id=task.id,
                correlation_id=task.correlation_id,
            )
        )
        db.commit()
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--role", choices=("pm", "architect", "developer", "qa"), default="developer"
    )
    args = parser.parse_args()
    mode = get_settings().agent_mode
    if mode == "mock" and args.role not in CONSUMER_NAMES:
        parser.error("PM and Architect workers require AGENTFORGE_AGENT_MODE=openai")
    if mode not in {"mock", "openai"}:
        parser.error("Unsupported AGENTFORGE_AGENT_MODE")
    if mode == "openai":
        from workers.ai_worker import process_ai_event

        processor = process_ai_event
        consumer_name = f"openai-{args.role}-v1"
    else:
        processor = process_event
        consumer_name = CONSUMER_NAMES[args.role]
    source = consumer(consumer_name)
    dlq = producer()
    topics = {
        "pm": TASKS_PM,
        "architect": TASKS_ARCHITECT,
        "developer": TASKS_DEVELOPER,
        "qa": TASKS_QA,
    }
    source.subscribe([topics[args.role]])
    try:
        while True:
            msg = source.poll(1)
            if msg is None:
                continue
            if msg.error():
                log.error("Kafka poll: %s", msg.error())
                time.sleep(1)
                continue
            try:
                try:
                    event = EventEnvelope.model_validate_json(msg.value())
                    processor(event, role=args.role)
                except ValidationError:
                    publish_sync(
                        dlq,
                        TASK_DLQ,
                        msg.key().decode() if msg.key() else "invalid",
                        {"error": "Invalid event schema"},
                    )
                except ValueError as exc:
                    publish_sync(
                        dlq,
                        TASK_DLQ,
                        msg.key().decode() if msg.key() else "invalid",
                        {"error": str(exc)[:1000]},
                    )
                source.commit(message=msg, asynchronous=False)
            except Exception:
                log.exception("Worker failed; message remains uncommitted")
                time.sleep(3)
    except KeyboardInterrupt:
        pass
    finally:
        source.close()


if __name__ == "__main__":
    main()

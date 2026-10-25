import logging
import time

from pydantic import ValidationError
from sqlalchemy import select

from apps.api.app.db.base import AuditLog, OutboxEvent, ProcessedEvent, Project, Task
from apps.api.app.db.session import new_session
from packages.communication.contracts import TASK_DLQ, TASK_RESULTS, TASKS_DEVELOPER, EventEnvelope
from packages.communication.kafka import consumer, producer, publish_sync

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
CONSUMER_NAME = "mock-developer-v1"


def process_event(event: EventEnvelope) -> bool:
    """Return True when work was applied, False for an already processed delivery."""
    if event.event_type != "task.execute.requested" or event.recipient_role != "developer":
        raise ValueError("Unsupported event for developer worker")

    with new_session() as db:
        already = db.scalar(
            select(ProcessedEvent).where(
                ProcessedEvent.consumer_name == CONSUMER_NAME,
                ProcessedEvent.event_id == str(event.event_id),
            )
        )
        if already:
            return False
        task = db.scalar(select(Task).where(Task.id == str(event.task_id)).with_for_update())
        # A second read after acquiring the task lock closes the concurrent duplicate race.
        already = db.scalar(
            select(ProcessedEvent).where(
                ProcessedEvent.consumer_name == CONSUMER_NAME,
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
            db.add(ProcessedEvent(consumer_name=CONSUMER_NAME, event_id=str(event.event_id)))
            db.commit()
            return False
        if task.status != "ready" or task.attempt != event.attempt:
            raise ValueError(f"Unexpected task status/attempt: {task.status}/{task.attempt}")

        # Deliberately a deterministic mock. Real code execution requires an isolated sandbox.
        task.status = "completed"
        task.result = f"Mock developer completed: {task.title}"
        result = EventEnvelope(
            event_type="task.execute.completed",
            correlation_id=event.correlation_id,
            causation_id=event.event_id,
            workspace_id=event.workspace_id,
            project_id=event.project_id,
            task_id=event.task_id,
            execution_id=event.execution_id,
            idempotency_key=event.idempotency_key,
            sender="mock-developer",
            recipient_role="orchestrator",
            attempt=event.attempt,
            payload={"result": task.result},
        )
        db.add(
            OutboxEvent(
                topic=TASK_RESULTS, event_key=task.id, payload=result.model_dump(mode="json")
            )
        )
        db.add(ProcessedEvent(consumer_name=CONSUMER_NAME, event_id=str(event.event_id)))
        db.add(
            AuditLog(
                workspace_id=project.workspace_id,
                action="task.completed",
                resource_id=task.id,
                correlation_id=task.correlation_id,
            )
        )
        db.commit()
        return True


def main():
    source = consumer(CONSUMER_NAME)
    dlq = producer()
    source.subscribe([TASKS_DEVELOPER])
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
                    process_event(event)
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

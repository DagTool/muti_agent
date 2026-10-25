import logging
import time

from pydantic import ValidationError

from packages.communication.contracts import (
    TASK_COMMANDS,
    TASK_DLQ,
    TASKS_ARCHITECT,
    TASKS_DEVELOPER,
    TASKS_PM,
    TASKS_QA,
    EventEnvelope,
)
from packages.communication.kafka import consumer, producer, publish_sync

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def dispatch_payload(payload: bytes, client) -> None:
    try:
        event = EventEnvelope.model_validate_json(payload)
    except ValidationError:
        publish_sync(client, TASK_DLQ, "invalid-schema", {"error": "Invalid event schema"})
        return
    routes = {
        "pm": TASKS_PM,
        "architect": TASKS_ARCHITECT,
        "developer": TASKS_DEVELOPER,
        "qa": TASKS_QA,
    }
    if event.event_type != "task.execute.requested" or event.recipient_role not in routes:
        publish_sync(
            client,
            TASK_DLQ,
            str(event.task_id),
            {"event_id": str(event.event_id), "error": "Unsupported role or event type"},
        )
        return
    publish_sync(
        client, routes[event.recipient_role], str(event.task_id), event.model_dump(mode="json")
    )


def main():
    source = consumer("agentforge-dispatcher-v1")
    target = producer()
    source.subscribe([TASK_COMMANDS])
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
                dispatch_payload(msg.value(), target)
                source.commit(message=msg, asynchronous=False)
            except Exception:
                log.exception("Dispatch failed; message remains uncommitted")
                time.sleep(3)
    except KeyboardInterrupt:
        pass
    finally:
        source.close()


if __name__ == "__main__":
    main()

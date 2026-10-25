import logging
import time

from sqlalchemy import select

from apps.api.app.db.base import OutboxEvent, utcnow
from apps.api.app.db.session import new_session
from packages.communication.kafka import producer, publish_sync

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def publish_batch(client, limit: int = 20) -> int:
    count = 0
    for _ in range(limit):
        with new_session() as db:
            event = db.scalar(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if event is None:
                break
            publish_sync(client, event.topic, event.event_key, event.payload)
            event.published_at = utcnow()
            db.commit()
            count += 1
    return count


def main():
    client = producer()
    while True:
        try:
            if not publish_batch(client):
                time.sleep(1)
        except KeyboardInterrupt:
            break
        except Exception:
            log.exception("Outbox publish failed; will retry")
            time.sleep(3)


if __name__ == "__main__":
    main()

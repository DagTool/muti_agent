import json
import logging

from confluent_kafka import Consumer, Producer

from apps.api.app.core.config import get_settings

log = logging.getLogger(__name__)


def producer() -> Producer:
    return Producer(
        {
            "bootstrap.servers": get_settings().kafka_bootstrap_servers,
            "enable.idempotence": True,
            "acks": "all",
        }
    )


def consumer(group_id: str) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": get_settings().kafka_bootstrap_servers,
            "group.id": group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )


def publish_sync(client: Producer, topic: str, key: str, payload: dict) -> None:
    errors = []

    def delivered(error, _message):
        if error:
            errors.append(error)

    client.produce(topic, key=key.encode(), value=json.dumps(payload).encode(), callback=delivered)
    if client.flush(15) != 0 or errors:
        raise RuntimeError(f"Kafka delivery failed: {errors}")

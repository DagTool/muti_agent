from confluent_kafka.admin import AdminClient, NewTopic

from apps.api.app.core.config import get_settings
from packages.communication.contracts import TASK_COMMANDS, TASK_DLQ, TASK_RESULTS, TASKS_DEVELOPER


def main():
    admin = AdminClient({"bootstrap.servers": get_settings().kafka_bootstrap_servers})
    topics = [
        NewTopic(name, num_partitions=1, replication_factor=1)
        for name in (TASK_COMMANDS, TASKS_DEVELOPER, TASK_RESULTS, TASK_DLQ)
    ]
    for name, future in admin.create_topics(topics).items():
        try:
            future.result()
            print(f"created {name}")
        except Exception as exc:
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                raise
            print(f"exists {name}")


if __name__ == "__main__":
    main()

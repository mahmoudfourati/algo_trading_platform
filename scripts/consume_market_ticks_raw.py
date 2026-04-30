"""Debug consumer for raw ticks.

Reads Kafka topic `market.ticks.raw` and prints each message as JSON.
"""

import json
import os
import time

from kafka import KafkaAdminClient, KafkaConsumer
from kafka.admin import NewTopic


BOOTSTRAP_SERVER = os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092")
TOPIC = os.getenv("KAFKA_RAW_TOPIC", "market.ticks.raw")
GROUP_ID = os.getenv("KAFKA_GROUP_ID", f"debug-raw-{int(time.time())}")
AUTO_OFFSET_RESET = os.getenv("KAFKA_AUTO_OFFSET_RESET", "latest")  # latest|earliest
CONSUMER_TIMEOUT_MS = int(float(os.getenv("KAFKA_CONSUMER_TIMEOUT_S", "0")) * 1000)  # <=0 => block (omit)
ENSURE_TOPIC = os.getenv("KAFKA_ENSURE_TOPICS", "1").strip().lower() in {"1", "true", "yes", "y", "on"}
PARTITIONS = int(os.getenv("KAFKA_RAW_TOPIC_PARTITIONS", "6"))
REPLICATION_FACTOR = int(os.getenv("KAFKA_RAW_TOPIC_REPLICATION_FACTOR", "1"))


def ensure_topic() -> None:
    if not ENSURE_TOPIC:
        return

    admin = KafkaAdminClient(bootstrap_servers=BOOTSTRAP_SERVER, client_id="debug-consumer-admin")
    try:
        existing = set(admin.list_topics())
        if TOPIC in existing:
            return
        admin.create_topics(
            new_topics=[
                NewTopic(
                    name=TOPIC,
                    num_partitions=PARTITIONS,
                    replication_factor=REPLICATION_FACTOR,
                )
            ],
            validate_only=False,
        )
    finally:
        admin.close()


def main() -> None:
    print(f"Bootstrap: {BOOTSTRAP_SERVER}")
    print(f"Topic: {TOPIC}")
    print(f"Group: {GROUP_ID}")
    print(f"Offset reset: {AUTO_OFFSET_RESET}")

    ensure_topic()

    consumer_kwargs = {}
    if CONSUMER_TIMEOUT_MS > 0:
        consumer_kwargs["consumer_timeout_ms"] = CONSUMER_TIMEOUT_MS

    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVER,
        group_id=GROUP_ID,
        enable_auto_commit=True,
        auto_offset_reset=AUTO_OFFSET_RESET,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        **consumer_kwargs,
    )

    try:
        for msg in consumer:
            key = msg.key.decode("utf-8") if msg.key else None
            print(json.dumps({"partition": msg.partition, "offset": msg.offset, "key": key, "value": msg.value}))
    finally:
        consumer.close()


if __name__ == "__main__":
    main()

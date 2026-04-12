import json
import os
import threading
import time
from dataclasses import dataclass
from typing import List

from kafka import KafkaAdminClient, KafkaConsumer, KafkaProducer
from kafka.admin import NewTopic


BOOTSTRAP_SERVER = os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092")
TOPIC = os.getenv("KAFKA_SMOKE_TOPIC", "smoke.test")
PARTITIONS = int(os.getenv("KAFKA_SMOKE_PARTITIONS", "2"))
REPLICATION_FACTOR = int(os.getenv("KAFKA_SMOKE_REPLICATION_FACTOR", "1"))


def ensure_topic() -> None:
    admin = KafkaAdminClient(bootstrap_servers=BOOTSTRAP_SERVER, client_id="smoke-admin")
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


def produce_messages(count: int = 10) -> List[dict]:
    producer = KafkaProducer(
        bootstrap_servers=BOOTSTRAP_SERVER,
        value_serializer=lambda v: json.dumps(v, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        acks="all",
        retries=3,
        linger_ms=0,
    )
    try:
        payloads: List[dict] = []
        for i in range(count):
            payload = {"i": i, "ts": int(time.time() * 1000)}
            payloads.append(payload)
            producer.send(TOPIC, value=payload)
        producer.flush(timeout=10)
        return payloads
    finally:
        producer.close()


@dataclass
class ConsumerResult:
    name: str
    messages: List[dict]


def _consume(name: str, group_id: str, expected: int, timeout_s: float, out: ConsumerResult) -> None:
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=BOOTSTRAP_SERVER,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset="earliest",
        consumer_timeout_ms=int(timeout_s * 1000),
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
    )
    try:
        deadline = time.time() + timeout_s
        while time.time() < deadline and len(out.messages) < expected:
            for msg in consumer:
                out.messages.append(msg.value)
                if len(out.messages) >= expected:
                    break
    finally:
        consumer.close()


def main() -> None:
    print(f"Bootstrap: {BOOTSTRAP_SERVER}")
    print(f"Topic: {TOPIC} (partitions={PARTITIONS})")

    ensure_topic()
    produced = produce_messages(count=10)
    print(f"Produced {len(produced)} messages")

    # Group semantics: same group shares partitions -> messages split across consumers (with 2 partitions).
    group1 = f"smoke-group-1-{int(time.time())}"
    c1 = ConsumerResult(name="consumer-1", messages=[])
    c2 = ConsumerResult(name="consumer-2", messages=[])

    t1 = threading.Thread(target=_consume, args=(c1.name, group1, 1, 10.0, c1), daemon=True)
    t2 = threading.Thread(target=_consume, args=(c2.name, group1, 1, 10.0, c2), daemon=True)
    t1.start()
    t2.start()
    t1.join(timeout=12)
    t2.join(timeout=12)

    print(f"{c1.name} received: {len(c1.messages)}")
    print(f"{c2.name} received: {len(c2.messages)}")
    if len(c1.messages) == 0 or len(c2.messages) == 0:
        raise SystemExit(
            "Expected both consumers in same group to receive at least one message. "
            "If this fails, confirm the topic has >=2 partitions (KAFKA_SMOKE_PARTITIONS=2)."
        )

    # Two different groups each see all messages independently.
    group2 = f"smoke-group-2-{int(time.time())}"
    c3 = ConsumerResult(name="consumer-group2", messages=[])
    _consume(c3.name, group2, expected=len(produced), timeout_s=10.0, out=c3)
    print(f"{c3.name} received (different group): {len(c3.messages)}")
    if len(c3.messages) < len(produced):
        raise SystemExit("Expected different consumer group to read all produced messages from earliest")

    print("Smoke test OK")


if __name__ == "__main__":
    main()

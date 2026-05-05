"""Raw tick Kafka publisher.

Publishes NormalizedTick messages with a bounded outage buffer and topic auto-create.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

from kafka import KafkaAdminClient, KafkaProducer
from kafka.admin import NewTopic

from shared.audit import emit_audit_event
from shared.schemas import NormalizedTick, RawTick


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class KafkaPublisherConfig:
    bootstrap_server: str
    topic: str
    buffer_max_messages: int
    partitions: int
    replication_factor: int

    @staticmethod
    def from_env() -> "KafkaPublisherConfig":
        return KafkaPublisherConfig(
            bootstrap_server=os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092"),
            topic=os.getenv("KAFKA_RAW_TOPIC", "market.ticks.raw"),
            buffer_max_messages=int(os.getenv("KAFKA_OUTAGE_BUFFER_MAX", "1000")),
            partitions=int(os.getenv("KAFKA_RAW_TOPIC_PARTITIONS", "6")),
            replication_factor=int(os.getenv("KAFKA_RAW_TOPIC_REPLICATION_FACTOR", "1")),
        )


class RawTickKafkaPublisher:
    """Publishes Layer 1 RawTick events to Kafka.

    Phase 2.3 goal: make `market.ticks.raw` visible for a debug consumer.

    Blueprint 2.4: maintain a bounded in-memory buffer (default 1000) during
    Kafka outages; drop oldest when full and emit a critical audit event.
    """

    def __init__(self, config: KafkaPublisherConfig) -> None:
        self._config = config
        self._queue: "queue.Queue[bytes]" = queue.Queue(maxsize=config.buffer_max_messages)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._producer: Optional[KafkaProducer] = None
        self._retry_backoff_s = 1.0
        self._max_backoff_s = 30.0

        self._dropped_total = 0

    @property
    def topic(self) -> str:
        return self._config.topic

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="rawtick-kafka-publisher", daemon=True)
        self._thread.start()

    def stop(self, *, flush_timeout_s: float = 5.0) -> None:
        self._stop.set()
        t = self._thread
        if t:
            t.join(timeout=flush_timeout_s)

        self._close_producer()

    def publish(self, tick: NormalizedTick) -> None:
        payload = self._serialize_tick(RawTick.model_validate(tick.model_dump()))
        try:
            self._queue.put_nowait(payload)
            return
        except queue.Full:
            pass

        # Buffer full: drop oldest and emit a critical alert, then retry.
        try:
            _ = self._queue.get_nowait()
        except queue.Empty:
            pass

        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            # If we still can't enqueue, drop the new message.
            self._dropped_total += 1
            emit_audit_event(
                "kafka.outage_buffer.drop",
                source="layer1_ingestion.kafka_publisher",
                payload={
                    "topic": self._config.topic,
                    "dropped_total": self._dropped_total,
                    "reason": "buffer_full_drop_new",
                },
            )
            return

        self._dropped_total += 1
        emit_audit_event(
            "kafka.outage_buffer.drop",
            source="layer1_ingestion.kafka_publisher",
            payload={
                "topic": self._config.topic,
                "dropped_total": self._dropped_total,
                "reason": "buffer_full_drop_oldest",
            },
        )

    @staticmethod
    def _serialize_tick(tick: RawTick) -> bytes:
        # Canonical JSON: stable encoding for downstream hashing/audit.
        return json.dumps(tick.model_dump(), separators=(",", ":"), sort_keys=True).encode("utf-8")

    def _ensure_topic(self) -> None:
        if not _env_bool("KAFKA_ENSURE_TOPICS", True):
            return

        admin = KafkaAdminClient(bootstrap_servers=self._config.bootstrap_server, client_id="layer1-admin")
        try:
            existing = set(admin.list_topics())
            if self._config.topic in existing:
                return

            admin.create_topics(
                new_topics=[
                    NewTopic(
                        name=self._config.topic,
                        num_partitions=self._config.partitions,
                        replication_factor=self._config.replication_factor,
                    )
                ],
                validate_only=False,
            )
            emit_audit_event(
                "kafka.topic.created",
                source="layer1_ingestion.kafka_publisher",
                payload={
                    "topic": self._config.topic,
                    "partitions": self._config.partitions,
                    "replication_factor": self._config.replication_factor,
                },
            )
        finally:
            admin.close()

    def _build_producer(self) -> KafkaProducer:
        return KafkaProducer(
            bootstrap_servers=self._config.bootstrap_server,
            acks="all",
            retries=3,
            linger_ms=0,
            client_id="layer1-ingestion",
        )

    def _close_producer(self) -> None:
        if self._producer is None:
            return
        try:
            self._producer.flush(timeout=5)
        except Exception:
            pass
        try:
            self._producer.close()
        except Exception:
            pass
        self._producer = None

    def _run(self) -> None:
        # Best-effort: create the topic early so debug consumers can attach.
        try:
            self._ensure_topic()
        except Exception as e:
            emit_audit_event(
                "kafka.topic.ensure_failed",
                source="layer1_ingestion.kafka_publisher",
                payload={"topic": self._config.topic, "error": repr(e)},
            )

        retry_payload: Optional[bytes] = None

        while not self._stop.is_set():
            if retry_payload is None:
                try:
                    payload = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
            else:
                payload = retry_payload

            try:
                if self._producer is None:
                    self._producer = self._build_producer()
                    self._retry_backoff_s = 1.0

                # Send synchronously in this background thread so we can detect outages.
                fut = self._producer.send(self._config.topic, value=payload)
                fut.get(timeout=10)
                retry_payload = None

            except Exception as e:
                # Treat as outage: keep the payload for retry, close producer, and back off.
                retry_payload = payload
                self._close_producer()

                emit_audit_event(
                    "kafka.publish.error",
                    source="layer1_ingestion.kafka_publisher",
                    payload={
                        "topic": self._config.topic,
                        "bootstrap": self._config.bootstrap_server,
                        "error": repr(e),
                        "backoff_s": self._retry_backoff_s,
                    },
                )

                time.sleep(self._retry_backoff_s)
                self._retry_backoff_s = min(self._retry_backoff_s * 2.0, self._max_backoff_s)


def publisher_from_env() -> Optional[RawTickKafkaPublisher]:
    if not _env_bool("PUBLISH_RAW_TO_KAFKA", False):
        return None
    return RawTickKafkaPublisher(KafkaPublisherConfig.from_env())

"""Buffered Kafka JSON publisher.

Used by services to publish JSON payloads with bounded outage buffering.
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
from prometheus_client import Counter, Gauge

from shared.audit import emit_audit_event


_json_pub_enqueued_total = Counter(
    "kafka_json_publisher_enqueued_total",
    "Messages enqueued to a buffered Kafka JSON publisher.",
    ["client_id", "topic"],
)

_json_pub_sent_total = Counter(
    "kafka_json_publisher_sent_total",
    "Messages successfully sent by buffered Kafka JSON publisher.",
    ["client_id", "topic"],
)

_json_pub_dropped_total = Counter(
    "kafka_json_publisher_dropped_total",
    "Messages dropped by buffered Kafka JSON publisher due to full queue.",
    ["client_id", "topic", "reason"],
)

_json_pub_errors_total = Counter(
    "kafka_json_publisher_errors_total",
    "Kafka publish errors from buffered Kafka JSON publisher.",
    ["client_id", "topic"],
)

_json_pub_queue_depth = Gauge(
    "kafka_json_publisher_queue_depth",
    "Current queue depth of buffered Kafka JSON publisher.",
    ["client_id", "topic"],
)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class KafkaJsonPublisherConfig:
    bootstrap_server: str
    topic: str
    buffer_max_messages: int
    partitions: int
    replication_factor: int

    @staticmethod
    def from_env(*, topic_env: str, default_topic: str) -> "KafkaJsonPublisherConfig":
        return KafkaJsonPublisherConfig(
            bootstrap_server=os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092"),
            topic=os.getenv(topic_env, default_topic),
            buffer_max_messages=int(os.getenv("KAFKA_OUTAGE_BUFFER_MAX", "1000")),
            partitions=int(os.getenv("KAFKA_TOPIC_PARTITIONS", "3")),
            replication_factor=int(os.getenv("KAFKA_TOPIC_REPLICATION_FACTOR", "1")),
        )


class KafkaJsonPublisher:
    """Buffered Kafka JSON publisher with bounded outage queue."""

    def __init__(self, config: KafkaJsonPublisherConfig, *, client_id: str) -> None:
        self._config = config
        self._client_id = client_id

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
        self._thread = threading.Thread(target=self._run, name=f"kafka-publisher-{self._client_id}", daemon=True)
        self._thread.start()

    def stop(self, *, timeout_s: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout_s)
        self._close_producer()

    def publish(self, obj: dict) -> None:
        payload = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
        labels = dict(client_id=self._client_id, topic=self._config.topic)

        try:
            self._queue.put_nowait(payload)
            _json_pub_enqueued_total.labels(**labels).inc()
            _json_pub_queue_depth.labels(**labels).set(self._queue.qsize())
            return
        except queue.Full:
            pass

        # Drop oldest then retry.
        try:
            _ = self._queue.get_nowait()
        except queue.Empty:
            pass

        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            self._dropped_total += 1
            _json_pub_dropped_total.labels(**labels, reason="drop_new").inc()
            _json_pub_queue_depth.labels(**labels).set(self._queue.qsize())
            emit_audit_event(
                "kafka.outage_buffer.drop",
                source=self._client_id,
                payload={
                    "topic": self._config.topic,
                    "dropped_total": self._dropped_total,
                    "reason": "buffer_full_drop_new",
                },
            )
            return

        self._dropped_total += 1
        _json_pub_dropped_total.labels(**labels, reason="drop_oldest").inc()
        _json_pub_queue_depth.labels(**labels).set(self._queue.qsize())
        emit_audit_event(
            "kafka.outage_buffer.drop",
            source=self._client_id,
            payload={
                "topic": self._config.topic,
                "dropped_total": self._dropped_total,
                "reason": "buffer_full_drop_oldest",
            },
        )

    def _ensure_topic(self) -> None:
        if not _env_bool("KAFKA_ENSURE_TOPICS", True):
            return

        admin = KafkaAdminClient(bootstrap_servers=self._config.bootstrap_server, client_id=f"{self._client_id}-admin")
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
        finally:
            admin.close()

    def _build_producer(self) -> KafkaProducer:
        return KafkaProducer(
            bootstrap_servers=self._config.bootstrap_server,
            acks="all",
            retries=3,
            linger_ms=0,
            client_id=self._client_id,
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
        try:
            self._ensure_topic()
        except Exception as e:
            emit_audit_event(
                "kafka.topic.ensure_failed",
                source=self._client_id,
                payload={"topic": self._config.topic, "error": repr(e)},
            )

        retry_payload: Optional[bytes] = None

        while not self._stop.is_set():
            if retry_payload is None:
                try:
                    payload = self._queue.get(timeout=0.2)
                    _json_pub_queue_depth.labels(client_id=self._client_id, topic=self._config.topic).set(self._queue.qsize())
                except queue.Empty:
                    continue
            else:
                payload = retry_payload

            try:
                if self._producer is None:
                    self._producer = self._build_producer()
                    self._retry_backoff_s = 1.0

                fut = self._producer.send(self._config.topic, value=payload)
                fut.get(timeout=10)
                retry_payload = None
                _json_pub_sent_total.labels(client_id=self._client_id, topic=self._config.topic).inc()

            except Exception as e:
                retry_payload = payload
                self._close_producer()
                _json_pub_errors_total.labels(client_id=self._client_id, topic=self._config.topic).inc()

                emit_audit_event(
                    "kafka.publish.error",
                    source=self._client_id,
                    payload={
                        "topic": self._config.topic,
                        "bootstrap": self._config.bootstrap_server,
                        "error": repr(e),
                        "backoff_s": self._retry_backoff_s,
                    },
                )

                time.sleep(self._retry_backoff_s)
                self._retry_backoff_s = min(self._retry_backoff_s * 2.0, self._max_backoff_s)

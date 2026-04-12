from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Optional

from kafka import KafkaConsumer
from prometheus_client import Counter, Gauge

from services.layer1_validated.kafka_json_publisher import KafkaJsonPublisher, KafkaJsonPublisherConfig
from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
from shared.schemas import ScoredTick, ValidatedTick

from .engine import DecisionGate, Layer2ScoringEngine


_raw_in_total = Counter("layer2_raw_in_total", "ValidatedTick messages consumed (including bad).")
_bad_in_total = Counter("layer2_bad_in_total", "ValidatedTick messages that failed decoding/validation.")
_scored_out_total = Counter("layer2_scored_out_total", "ScoredTick messages published.")
_last_anomaly = Gauge("layer2_last_anomaly_score", "Last anomaly score emitted.", ["symbol"])
_last_state = Gauge(
    "layer2_system_state",
    "System state encoded as 0=NORMAL,1=CONSERVATIVE,2=DEGRADED,3=HALT.",
)


_STATE_NUM = {"NORMAL": 0.0, "CONSERVATIVE": 1.0, "DEGRADED": 2.0, "HALT": 3.0}


@dataclass
class Layer2Service:
    consumer: KafkaConsumer
    publisher: KafkaJsonPublisher
    engine_by_symbol: dict[str, Layer2ScoringEngine]
    gate: DecisionGate

    def run_forever(self) -> None:
        emit_audit_event(
            "layer2.start",
            source="layer2_anomaly",
            payload={
                "validated_topic": os.getenv("KAFKA_VALIDATED_TOPIC", "market.ticks.validated"),
                "scored_topic": self.publisher.topic,
            },
        )

        try:
            for msg in self.consumer:
                _raw_in_total.inc()
                try:
                    raw = json.loads(msg.value.decode("utf-8"))
                    tick = ValidatedTick.model_validate(raw)
                except Exception as e:
                    _bad_in_total.inc()
                    emit_audit_event(
                        "layer2.bad_validated_tick",
                        source="layer2_anomaly",
                        payload={"error": repr(e)},
                    )
                    continue

                scorer = self.engine_by_symbol.get(tick.symbol)
                if scorer is None:
                    scorer = Layer2ScoringEngine(
                        hmm_model_path=os.getenv("HMM_MODEL_PATH", os.path.join("artifacts", "hmm", "model.pkl")),
                        if_weight=float(os.getenv("L2_IF_WEIGHT", "0.45")),
                        hst_weight=float(os.getenv("L2_HST_WEIGHT", "0.55")),
                        mad_floor=float(os.getenv("L2_MAD_FLOOR", "0.65")),
                    )
                    self.engine_by_symbol[tick.symbol] = scorer

                scores = scorer.score_tick(
                    symbol=tick.symbol,
                    ts_ms=int(tick.timestamp_utc),
                    mid_price=float(tick.mid_price),
                    trust_score=float(tick.trust_score),
                    volume_24h=tick.volume_24h,
                    spread=tick.spread,
                )

                system_state = self.gate.update(trust=float(tick.trust_score), anomaly=float(scores.anomaly_score))
                _last_state.set(_STATE_NUM.get(system_state, 0.0))
                _last_anomaly.labels(symbol=tick.symbol).set(float(scores.anomaly_score))

                out = ScoredTick(
                    symbol=tick.symbol,
                    asset_class=tick.asset_class,
                    mid_price=tick.mid_price,
                    volume_24h=tick.volume_24h,
                    spread=tick.spread,
                    trust_score=tick.trust_score,
                    sub_scores=tick.sub_scores,
                    divergent_sources=tick.divergent_sources,
                    timestamp_utc=tick.timestamp_utc,
                    tick_hash=tick.tick_hash,
                    anomaly_score=float(scores.anomaly_score),
                    if_score=float(scores.if_score),
                    hst_score=float(scores.hst_score),
                    regime=int(scores.regime),
                    regime_posterior=list(scores.regime_posterior),
                    system_state=system_state,  # type: ignore[arg-type]
                    mad_guard_triggered=bool(scores.mad_guard_triggered),
                )

                self.publisher.publish(out.model_dump())
                _scored_out_total.inc()
        finally:
            self.publisher.stop()
            self.consumer.close()


def build_service() -> Layer2Service:
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9103")))

    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092")
    validated_topic = os.getenv("KAFKA_VALIDATED_TOPIC", "market.ticks.validated")

    group_id = os.getenv("KAFKA_GROUP_ID", f"layer2-anomaly-{int(time.time())}")

    consumer = KafkaConsumer(
        validated_topic,
        bootstrap_servers=bootstrap,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset=os.getenv("KAFKA_AUTO_OFFSET_RESET", "latest"),
    )

    pub_cfg = KafkaJsonPublisherConfig.from_env(topic_env="KAFKA_SCORED_TOPIC", default_topic="market.ticks.scored")
    publisher = KafkaJsonPublisher(pub_cfg, client_id="layer2_anomaly")
    publisher.start()

    gate = DecisionGate(
        trust_threshold=float(os.getenv("L2_TRUST_THRESHOLD", "0.60")),
        anomaly_threshold=float(os.getenv("L2_ANOMALY_THRESHOLD", "0.55")),
        upgrade_streak_required=int(os.getenv("L2_UPGRADE_STREAK", "10")),
    )

    return Layer2Service(
        consumer=consumer,
        publisher=publisher,
        engine_by_symbol={},
        gate=gate,
    )


def main() -> None:
    svc = build_service()
    svc.run_forever()


if __name__ == "__main__":
    main()

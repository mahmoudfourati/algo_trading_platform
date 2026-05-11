"""Layer 4 Kafka consumer service wrapper.

Consumes `trading.signals`, runs `Layer4RiskEngine.evaluate_signal`, and
publishes `trading.orders.approved` when appropriate. Supports a dual-mode
where the service can also be invoked in-process for deterministic backtests.
"""

from __future__ import annotations

import json
import os
import time
from kafka import KafkaConsumer
from prometheus_client import Counter, Gauge, Histogram

from services.layer1_validated.kafka_json_publisher import KafkaJsonPublisher, KafkaJsonPublisherConfig
from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
from shared.service_health import mark_service_healthy
from services.layer4_risk.engine import Layer4RiskEngine
from services.layer3_strategy.signals import TradeSignal


# === PROMETHEUS METRICS ===

# Throughput
_signals_in_total = Counter("layer4_signals_in_total", "TradeSignal messages consumed.")
_bad_in_total = Counter("layer4_bad_in_total", "TradeSignal messages that failed validation.")
_approvals_out_total = Counter("layer4_approvals_out_total", "Approved trades published.", ["symbol", "direction"])
_rejections_total = Counter("layer4_rejections_total", "Trade rejections by reason.", ["symbol", "reason"])

# Risk State
_circuit_breaker_active = Gauge("risk_circuit_breaker_active", "Circuit breaker state (1=active, 0=inactive).")
_current_exposure_pct = Gauge("risk_current_exposure_percent", "Current portfolio exposure percentage.", ["symbol"])
_current_drawdown_pct = Gauge("risk_current_drawdown_percent", "Current drawdown from peak.")
_consecutive_losses = Gauge("risk_consecutive_loss_count", "Current consecutive loss counter.")
_daily_loss_pct = Gauge("risk_daily_loss_percent", "Daily loss percentage from start-of-day equity.")

# Limit Violations
_exposure_limit_violations = Counter("risk_exposure_limit_violations_total", "Exposure limit violations.", ["symbol"])
_drawdown_limit_violations = Counter("risk_drawdown_limit_violations_total", "Drawdown limit violations.")
_trust_floor_violations = Counter("risk_trust_floor_violations_total", "Trust floor violations.", ["symbol"])

# Processing Latency
_risk_check_latency_ms = Histogram(
    "risk_check_duration_ms",
    "Risk check processing latency in milliseconds.",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 50, 100]
)


class Layer4Service:
    def __init__(self) -> None:
        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092")
        signals_topic = os.getenv("KAFKA_SIGNALS_TOPIC", "trading.signals")
        approved_topic = os.getenv("KAFKA_APPROVED_TOPIC", "trading.orders.approved")
        group_id = os.getenv("KAFKA_GROUP_ID", f"layer4-risk-v1-{int(time.time())}")

        self.consumer = KafkaConsumer(signals_topic, bootstrap_servers=bootstrap, group_id=group_id, enable_auto_commit=True, auto_offset_reset=os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest"))
        pub_cfg = KafkaJsonPublisherConfig.from_env(topic_env="KAFKA_APPROVED_TOPIC", default_topic=approved_topic)
        self.publisher = KafkaJsonPublisher(pub_cfg, client_id="layer4_risk")
        self.publisher.start()

        # engine state
        self.engine = Layer4RiskEngine()

    def run_forever(self) -> None:
        emit_audit_event("layer4.start", source="layer4_risk", payload={"signals_topic": os.getenv("KAFKA_SIGNALS_TOPIC", "trading.signals"), "approved_topic": self.publisher.topic})
        try:
            for msg in self.consumer:
                _signals_in_total.inc()
                
                try:
                    raw = json.loads(msg.value.decode("utf-8"))
                except Exception as exc:
                    _bad_in_total.inc()
                    emit_audit_event("layer4.bad_signal", source="layer4_risk", payload={"error": repr(exc)})
                    continue

                try:
                    signal = TradeSignal(**raw)
                except Exception as exc:
                    _bad_in_total.inc()
                    emit_audit_event("layer4.invalid_signal", source="layer4_risk", payload={"error": repr(exc), "raw": raw})
                    continue

                # determine reference price (best-effort)
                primary = signal.indicator_snapshots.get("primary", {}) if hasattr(signal, "indicator_snapshots") else {}
                reference_price = primary.get("close") if isinstance(primary, dict) else None
                if reference_price is None:
                    reference_price = raw.get("entry_price") or raw.get("entry_price")

                # portfolio exposure currently unknown in this service wrapper; default to 0.0
                start_time = time.perf_counter()
                decision = self.engine.evaluate_signal(signal, reference_price=reference_price or 0.0, current_portfolio_exposure_pct=0.0)
                risk_check_ms = (time.perf_counter() - start_time) * 1000
                _risk_check_latency_ms.observe(risk_check_ms)
                
                # Update risk state metrics
                _circuit_breaker_active.set(1.0 if self.engine.state.circuit_breaker_state in {"REDUCED", "HALTED"} else 0.0)
                _consecutive_losses.set(self.engine.state.consecutive_losing_trades)
                _current_drawdown_pct.set(self.engine.state.latest_drawdown_pct * 100)
                daily_loss = ((self.engine.state.session_start_equity - self.engine.state.current_equity) / self.engine.state.session_start_equity) * 100
                _daily_loss_pct.set(daily_loss)
                
                if decision.approved and decision.approved_order is not None:
                    payload = decision.approved_order.model_dump() if hasattr(decision.approved_order, "model_dump") else decision.approved_order.__dict__
                    self.publisher.publish(payload)
                    _approvals_out_total.labels(symbol=decision.approved_order.symbol, direction=decision.approved_order.direction).inc()
                    emit_audit_event("layer4.order_approved", source="layer4_risk", payload={"symbol": decision.approved_order.symbol, "client_time": int(time.time() * 1000)})
                else:
                    symbol = signal.symbol if hasattr(signal, "symbol") else "UNKNOWN"
                    _rejections_total.labels(symbol=symbol, reason=decision.reason.replace(" ", "_")).inc()
                    
                    # Track specific violation types
                    if "trust floor" in decision.reason:
                        _trust_floor_violations.labels(symbol=symbol).inc()
                    elif "exposure cap" in decision.reason:
                        _exposure_limit_violations.labels(symbol=symbol).inc()
                    elif "drawdown" in decision.reason:
                        _drawdown_limit_violations.inc()
                    
                    emit_audit_event("layer4.order_rejected", source="layer4_risk", payload={"reason": decision.reason})
        finally:
            self.publisher.stop()
            self.consumer.close()


def build_service() -> Layer4Service:
    return Layer4Service()


def main() -> None:
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9105")))
    mark_service_healthy("layer4_risk", "layer4")
    svc = build_service()
    svc.run_forever()


if __name__ == "__main__":
    main()

"""Layer 5 Kafka consumer service wrapper.

Consumes `trading.orders.approved`, runs `ExecutionEngine.submit_order`, and
publishes `trading.orders.executed`. Preserves WAL semantics via
`services.layer5_execution.persistence.OrderStore` when a persistence DB is
configured via `EXECUTION_PERSISTENCE_DB` environment variable.

Adapter selection via EXECUTION_ADAPTER_TYPE environment variable:
- "simulated" (default): deterministic in-process adapter for backtests
- "binance": live Binance Futures API (testnet or live)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from kafka import KafkaConsumer
from prometheus_client import Counter, Gauge, Histogram

from services.layer1_validated.kafka_json_publisher import KafkaJsonPublisher, KafkaJsonPublisherConfig
from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
from shared.service_health import mark_service_healthy
from services.layer5_execution.engine import ExecutionEngine
from prometheus_client import Counter, Histogram

# Prometheus metrics for execution divergence tracking
DIVERGENCE_REJECTIONS = Counter(
    "execution_divergence_rejections_total",
    "Total number of orders rejected due to execution venue price divergence",
    ["symbol", "execution_venue"]
)
DIVERGENCE_BPS = Histogram(
    "execution_divergence_bps",
    "Execution venue price divergence from consensus in basis points",
    ["symbol", "execution_venue"],
    buckets=[0, 5, 10, 20, 30, 50, 75, 100, 150, 200, 500, 1000]
)


# === PROMETHEUS METRICS ===

# Throughput
_orders_in_total = Counter("layer5_orders_in_total", "Approved orders consumed.")
_bad_in_total = Counter("layer5_bad_in_total", "Orders that failed validation.")
_orders_placed_total = Counter("layer5_orders_placed_total", "Orders placed to exchange.", ["exchange_id", "symbol", "direction"])
_orders_filled_total = Counter("layer5_orders_filled_total", "Orders fully filled.", ["exchange_id", "symbol", "direction"])
_orders_partial_filled_total = Counter("layer5_orders_partial_filled_total", "Orders partially filled.", ["exchange_id", "symbol"])
_orders_failed_total = Counter("layer5_orders_failed_total", "Orders failed.", ["exchange_id", "symbol", "reason"])

# Execution Quality
_fill_rate_pct = Gauge("execution_fill_rate_percent", "Fill rate percentage (filled/placed).", ["symbol"])
_slippage_abs_bps = Histogram(
    "execution_slippage_abs_bps",
    "Absolute execution slippage magnitude in basis points.",
    ["symbol", "direction"],
    buckets=[1, 2, 5, 10, 20, 50, 100, 200]
)
_slippage_signed_bps = Gauge(
    "execution_slippage_signed_bps",
    "Signed execution slippage in basis points (negative=favorable fill).",
    ["symbol", "direction"]
)
_execution_latency_ms = Histogram(
    "execution_order_placement_latency_ms",
    "Order placement latency to exchange.",
    ["exchange_id"],
    buckets=[1, 5, 10, 20, 50, 100, 200, 500, 1000]
)

# Retries & Failures
_order_retries_total = Counter("execution_order_retries_total", "Order retry attempts.", ["exchange_id", "reason"])
_idempotency_dedup_hits = Counter("execution_idempotency_dedup_hits_total", "Idempotency deduplication hits.", ["exchange_id"])
_reconciliation_failures = Counter("execution_reconciliation_failures_total", "Reconciliation failures.", ["exchange_id"])

# State
_pending_orders = Gauge("execution_pending_orders_count", "Current pending orders count.", ["symbol"])
_wal_depth = Gauge("execution_wal_depth", "Write-ahead log depth (unacknowledged orders).")


class Layer5Service:
    def __init__(self) -> None:
        bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092")
        approved_topic = os.getenv("KAFKA_APPROVED_TOPIC", "trading.orders.approved")
        executed_topic = os.getenv("KAFKA_EXECUTED_TOPIC", "trading.orders.executed")
        group_id = os.getenv("KAFKA_GROUP_ID", f"layer5-exec-v1-{int(time.time())}")

        self.consumer = KafkaConsumer(approved_topic, bootstrap_servers=bootstrap, group_id=group_id, enable_auto_commit=True, auto_offset_reset=os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest"))
        pub_cfg = KafkaJsonPublisherConfig.from_env(topic_env="KAFKA_EXECUTED_TOPIC", default_topic=executed_topic)
        self.publisher = KafkaJsonPublisher(pub_cfg, client_id="layer5_execution")
        self.publisher.start()

        persistence_path = os.getenv("EXECUTION_PERSISTENCE_DB")
        persistence_db = Path(persistence_path) if persistence_path else None
        
        # Select adapter based on environment variable
        adapter_type = os.getenv("EXECUTION_ADAPTER_TYPE", "simulated").lower()
        adapter = None
        
        if adapter_type == "binance":
            from services.layer5_execution.adapters import BinanceExecutionAdapter
            api_key = os.getenv("BINANCE_API_KEY", "")
            api_secret = os.getenv("BINANCE_API_SECRET", "")
            testnet = os.getenv("BINANCE_TESTNET", "true").lower() == "true"
            if not api_key or not api_secret:
                raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET must be set for binance adapter")
            adapter = BinanceExecutionAdapter(api_key=api_key, api_secret=api_secret, testnet=testnet)
            emit_audit_event("layer5.adapter_selected", source="layer5_execution", payload={"adapter": "binance", "testnet": testnet})
        elif adapter_type == "simulated":
            adapter = None  # Defaults to SimulatedExecutionAdapter in ExecutionEngine
            emit_audit_event("layer5.adapter_selected", source="layer5_execution", payload={"adapter": "simulated"})
        else:
            raise ValueError(f"Unknown adapter type: {adapter_type}")
        
        self.engine = ExecutionEngine(adapter=adapter, portfolio_value=float(os.getenv("PORTFOLIO_VALUE", "1.0")), persistence_db=persistence_db, publisher=self.publisher)

    def run_forever(self) -> None:
        emit_audit_event("layer5.start", source="layer5_execution", payload={"approved_topic": os.getenv("KAFKA_APPROVED_TOPIC", "trading.orders.approved"), "executed_topic": self.publisher.topic})
        
        # Determine exchange_id for metrics
        adapter_type = os.getenv("EXECUTION_ADAPTER_TYPE", "simulated").lower()
        exchange_id = "binance" if adapter_type == "binance" else "simulated"
        
        try:
            for msg in self.consumer:
                _orders_in_total.inc()
                
                try:
                    raw = json.loads(msg.value.decode("utf-8"))
                except Exception as exc:
                    _bad_in_total.inc()
                    emit_audit_event("layer5.bad_approved", source="layer5_execution", payload={"error": repr(exc)})
                    continue

                symbol = raw.get("symbol", "UNKNOWN")
                direction = raw.get("direction", "UNKNOWN")
                
                try:
                    # Feature flag: Enable/disable divergence checking
                    enable_divergence_check = os.getenv("ENABLE_DIVERGENCE_CHECK", "false").lower() == "true"
                    
                    # Extract divergence checking parameters
                    consensus_price = raw.get("consensus_price") or raw.get("entry_price")
                    execution_venue_prices = raw.get("execution_venue_prices", {})
                    execution_venue = os.getenv("EXECUTION_VENUE", "binance")
                    reference_price = raw.get("entry_price")
                    
                    # Calculate and record divergence metrics if we have the data
                    if consensus_price and execution_venue_prices and execution_venue in execution_venue_prices:
                        venue_price = execution_venue_prices[execution_venue]
                        if consensus_price > 0:
                            divergence_bps = abs(venue_price - consensus_price) / consensus_price * 10000
                            DIVERGENCE_BPS.labels(symbol=symbol, execution_venue=execution_venue).observe(divergence_bps)
                    
                    # Track execution latency
                    start_time = time.perf_counter()
                    
                    # Submit order with or without divergence check based on feature flag
                    if enable_divergence_check:
                        # Protected mode: Check execution venue divergence
                        executed = self.engine.submit_order(
                            raw,
                            reference_price=reference_price,
                            consensus_price=consensus_price,
                            execution_venue_prices=execution_venue_prices,
                            execution_venue=execution_venue
                        )
                    else:
                        # Simple mode: No divergence check (default for demo stability)
                        executed = self.engine.submit_order(
                            raw,
                            reference_price=reference_price
                        )
                    
                    execution_ms = (time.perf_counter() - start_time) * 1000
                    _execution_latency_ms.labels(exchange_id=exchange_id).observe(execution_ms)
                    
                    # Track rejections
                    if executed.note and "REJECTED" in executed.note:
                        DIVERGENCE_REJECTIONS.labels(symbol=symbol, execution_venue=execution_venue).inc()
                        
                except Exception as exc:
                    _orders_failed_total.labels(exchange_id=exchange_id, symbol=symbol, reason="exception").inc()
                    emit_audit_event("layer5.execution_failed", source="layer5_execution", payload={"error": repr(exc), "order": raw})
                    # if engine/store marked it failed and moved to DLQ, we simply continue here
                    continue

                # Track order placement
                _orders_placed_total.labels(exchange_id=exchange_id, symbol=symbol, direction=direction).inc()
                
                # Determine order status from execution result
                if executed.note and "REJECTED" in executed.note:
                    status = "REJECTED"
                    _orders_failed_total.labels(exchange_id=exchange_id, symbol=symbol, reason="rejected").inc()
                elif executed.note and "CANCELLED" in executed.note:
                    status = "CANCELLED"
                    _orders_failed_total.labels(exchange_id=exchange_id, symbol=symbol, reason="cancelled").inc()
                elif executed.filled_pct >= 1.0:
                    status = "FILLED"
                    _orders_filled_total.labels(exchange_id=exchange_id, symbol=symbol, direction=direction).inc()
                elif executed.filled_pct > 0.0:
                    status = "PARTIALLY_FILLED"
                    _orders_partial_filled_total.labels(exchange_id=exchange_id, symbol=symbol).inc()
                else:
                    status = "PENDING"
                
                # Track slippage (in basis points)
                if executed.avg_fill_price > 0.0 and raw.get("entry_price"):
                    entry_price = float(raw.get("entry_price"))
                    slippage_bps = ((executed.avg_fill_price - entry_price) / entry_price) * 10000
                    
                    # Track absolute magnitude for histogram
                    _slippage_abs_bps.labels(symbol=symbol, direction=direction).observe(abs(slippage_bps))
                    
                    # Track signed value for gauge (negative = favorable fill)
                    _slippage_signed_bps.labels(symbol=symbol, direction=direction).set(slippage_bps)
                
                # Calculate filled_size as absolute quantity
                # filled_size = filled_pct * size_pct * portfolio_value / filled_price
                portfolio_value = self.engine.portfolio_value
                size_pct = raw.get("size_pct", 0.0)
                filled_size = 0.0
                if executed.avg_fill_price > 0.0:
                    filled_size = (executed.filled_pct * size_pct * portfolio_value) / executed.avg_fill_price
                
                out = {
                    "order_id": executed.order_id,
                    "symbol": raw.get("symbol", ""),
                    "direction": raw.get("direction", ""),
                    "filled_price": executed.avg_fill_price,
                    "filled_size": filled_size,
                    "status": status,
                    "timestamp_utc": int(time.time() * 1000),
                }
                self.publisher.publish(out)
                emit_audit_event("layer5.order_executed", source="layer5_execution", payload={"order_id": executed.order_id})
                
                # Update WAL depth if persistence is enabled
                if self.engine.store is not None:
                    pending_count = len(self.engine.store.fetch_pending())
                    _wal_depth.set(pending_count)
                
        finally:
            self.publisher.stop()
            self.consumer.close()


def build_service() -> Layer5Service:
    return Layer5Service()


def main() -> None:
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9106")))
    mark_service_healthy("layer5_execution", "layer5")
    svc = build_service()
    svc.run_forever()


if __name__ == "__main__":
    main()

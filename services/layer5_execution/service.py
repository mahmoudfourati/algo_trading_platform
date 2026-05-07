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

from services.layer1_validated.kafka_json_publisher import KafkaJsonPublisher, KafkaJsonPublisherConfig
from shared.audit import emit_audit_event
from services.layer5_execution.engine import ExecutionEngine


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
        
        self.engine = ExecutionEngine(adapter=adapter, portfolio_value=float(os.getenv("PORTFOLIO_VALUE", "1.0")), persistence_db=persistence_db)

    def run_forever(self) -> None:
        emit_audit_event("layer5.start", source="layer5_execution", payload={"approved_topic": os.getenv("KAFKA_APPROVED_TOPIC", "trading.orders.approved"), "executed_topic": self.publisher.topic})
        try:
            for msg in self.consumer:
                try:
                    raw = json.loads(msg.value.decode("utf-8"))
                except Exception as exc:
                    emit_audit_event("layer5.bad_approved", source="layer5_execution", payload={"error": repr(exc)})
                    continue

                try:
                    executed = self.engine.submit_order(raw, reference_price=raw.get("entry_price"))
                except Exception as exc:
                    emit_audit_event("layer5.execution_failed", source="layer5_execution", payload={"error": repr(exc), "order": raw})
                    # if engine/store marked it failed and moved to DLQ, we simply continue here
                    continue

                out = {
                    "order_id": executed.order_id,
                    "filled_pct": executed.filled_pct,
                    "avg_fill_price": executed.avg_fill_price,
                    "fee_paid": executed.fee_paid,
                    "slippage_pct": executed.slippage_pct,
                    "note": executed.note,
                }
                self.publisher.publish(out)
                emit_audit_event("layer5.order_executed", source="layer5_execution", payload={"order_id": executed.order_id})
        finally:
            self.publisher.stop()
            self.consumer.close()


def build_service() -> Layer5Service:
    return Layer5Service()


def main() -> None:
    svc = build_service()
    svc.run_forever()


if __name__ == "__main__":
    main()

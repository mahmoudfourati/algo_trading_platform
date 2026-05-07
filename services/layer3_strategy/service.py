"""Layer 3 Kafka service for trading signal generation.

The service consumes `ScoredTick` messages from `market.ticks.scored`, builds
5m and 1h candles, maintains indicator and OFI state, and publishes sized
trade signals to `trading.signals`.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional

from kafka import KafkaConsumer
from prometheus_client import Counter, Gauge

from services.layer1_validated.kafka_json_publisher import KafkaJsonPublisher, KafkaJsonPublisherConfig
from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
from shared.schemas import ScoredTick, SystemState

from .candles import CandleAggregationManager, CandleAggregationEvent
from .indicators import IndicatorSnapshot, IndicatorManager
from .ofi import OrderFlowImbalanceSnapshot, OrderFlowImbalanceState
from .signals import TradeSignal, evaluate_dual_timeframe_signal
from .sizing import size_trade_signal


_ticks_in_total = Counter("layer3_ticks_in_total", "ScoredTick messages consumed (including bad).")
_bad_in_total = Counter("layer3_bad_in_total", "ScoredTick messages that failed decoding/validation.")
_signals_out_total = Counter("layer3_signals_out_total", "TradeSignal messages published.")
_last_signal_size = Gauge("layer3_last_signal_size_pct", "Last signal size percentage emitted.", ["symbol"])
_last_ofi = Gauge("layer3_last_ofi", "Last order flow imbalance emitted.", ["symbol"])


@dataclass
class Layer3SymbolState:
    """In-memory state for one symbol's Layer 3 processing pipeline."""

    symbol: str
    candle_manager: CandleAggregationManager = field(init=False)
    indicator_manager: IndicatorManager = field(init=False)
    ofi_state: OrderFlowImbalanceState = field(init=False)
    primary_history: Deque[IndicatorSnapshot] = field(init=False)
    higher_history: Deque[IndicatorSnapshot] = field(init=False)
    latest_ofi: Optional[OrderFlowImbalanceSnapshot] = None

    def __post_init__(self) -> None:
        self.candle_manager = CandleAggregationManager(symbol=self.symbol)
        self.indicator_manager = IndicatorManager(symbol=self.symbol)
        self.ofi_state = OrderFlowImbalanceState(symbol=self.symbol)
        self.primary_history = deque(maxlen=3)
        self.higher_history = deque(maxlen=2)

    def ingest_tick(self, tick: ScoredTick) -> list[TradeSignal]:
        self.latest_ofi = self.ofi_state.process(tick)
        _last_ofi.labels(symbol=self.symbol).set(float(self.latest_ofi.ofi))

        produced_signals: list[TradeSignal] = []
        effective_state: SystemState = tick.system_state
        for event in self.candle_manager.process(tick):
            candle = event.candle
            if candle.system_state_override is not None:
                effective_state = candle.system_state_override
            snapshot = self.indicator_manager.process(candle)
            if snapshot is None:
                continue

            if event.timeframe == "5m":
                self.primary_history.append(snapshot)
                produced_signals.extend(self._maybe_emit_signal(system_state=effective_state))
            elif event.timeframe == "1h":
                self.higher_history.append(snapshot)

        return produced_signals

    def flush(self, *, tick: ScoredTick) -> list[TradeSignal]:
        produced_signals: list[TradeSignal] = []
        effective_state: SystemState = tick.system_state
        for event in self.candle_manager.flush():
            candle = event.candle
            if candle.system_state_override is not None:
                effective_state = candle.system_state_override
            snapshot = self.indicator_manager.process(candle)
            if snapshot is None:
                continue
            if event.timeframe == "5m":
                self.primary_history.append(snapshot)
                produced_signals.extend(self._maybe_emit_signal(system_state=effective_state))
            elif event.timeframe == "1h":
                self.higher_history.append(snapshot)
        return produced_signals

    def _maybe_emit_signal(self, *, system_state: SystemState | None = None, tick: ScoredTick | None = None) -> list[TradeSignal]:
        if self.latest_ofi is None:
            return []
        if len(self.primary_history) < 3 or len(self.higher_history) < 2:
            return []

        resolved_state = system_state if system_state is not None else (tick.system_state if tick is not None else None)
        if resolved_state is None:
            raise ValueError("system_state or tick must be provided")

        signal = evaluate_dual_timeframe_signal(
            symbol=self.symbol,
            primary_snapshots=list(self.primary_history),
            higher_snapshots=list(self.higher_history),
            ofi_snapshot=self.latest_ofi,
            trust_score=tick.trust_score if tick is not None else 1.0,
            system_state=resolved_state,
        )
        sized = size_trade_signal(signal).signal
        if sized.direction == "HOLD":
            return []
        _last_signal_size.labels(symbol=self.symbol).set(float(sized.size_pct))
        return [sized]


@dataclass
class Layer3Service:
    consumer: KafkaConsumer
    publisher: KafkaJsonPublisher
    engine_by_symbol: dict[str, Layer3SymbolState]

    def run_forever(self) -> None:
        emit_audit_event(
            "layer3.start",
            source="layer3_strategy",
            payload={
                "scored_topic": os.getenv("KAFKA_SCORED_TOPIC", "market.ticks.scored"),
                "signals_topic": self.publisher.topic,
            },
        )

        try:
            for msg in self.consumer:
                _ticks_in_total.inc()
                try:
                    raw = json.loads(msg.value.decode("utf-8"))
                    tick = ScoredTick.model_validate(raw)
                except Exception as exc:
                    _bad_in_total.inc()
                    emit_audit_event(
                        "layer3.bad_scored_tick",
                        source="layer3_strategy",
                        payload={"error": repr(exc)},
                    )
                    continue

                state = self.engine_by_symbol.get(tick.symbol)
                if state is None:
                    state = Layer3SymbolState(symbol=tick.symbol)
                    self.engine_by_symbol[tick.symbol] = state

                produced_signals = state.ingest_tick(tick)
                for signal in produced_signals:
                    self.publisher.publish(signal.model_dump())
                    _signals_out_total.inc()
        finally:
            self.publisher.stop()
            self.consumer.close()


def build_service() -> Layer3Service:
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9104")))

    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVER", "localhost:29092")
    scored_topic = os.getenv("KAFKA_SCORED_TOPIC", "market.ticks.scored")
    group_id = os.getenv("KAFKA_GROUP_ID", f"layer3-strategy-{int(time.time())}")

    consumer = KafkaConsumer(
        scored_topic,
        bootstrap_servers=bootstrap,
        group_id=group_id,
        enable_auto_commit=True,
        auto_offset_reset=os.getenv("KAFKA_AUTO_OFFSET_RESET", "earliest"),
    )

    pub_cfg = KafkaJsonPublisherConfig.from_env(topic_env="KAFKA_SIGNALS_TOPIC", default_topic="trading.signals")
    publisher = KafkaJsonPublisher(pub_cfg, client_id="layer3_strategy")
    publisher.start()

    return Layer3Service(consumer=consumer, publisher=publisher, engine_by_symbol={})


def main() -> None:
    svc = build_service()
    svc.run_forever()


if __name__ == "__main__":
    main()

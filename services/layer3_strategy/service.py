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
from prometheus_client import Counter, Gauge, Histogram

from services.layer1_validated.kafka_json_publisher import KafkaJsonPublisher, KafkaJsonPublisherConfig
from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
from shared.service_health import mark_service_healthy
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

# Technical Indicator Metrics
_indicator_rsi = Gauge(
    "strategy_indicator_rsi",
    "RSI indicator value",
    ["symbol", "timeframe"]
)

_indicator_macd_histogram = Gauge(
    "strategy_indicator_macd_histogram",
    "MACD histogram value",
    ["symbol", "timeframe"]
)

_indicator_bb_width = Gauge(
    "strategy_indicator_bollinger_width",
    "Bollinger Band width (normalized)",
    ["symbol", "timeframe"]
)

# Signal Generation Metrics
_signal_direction_count = Counter(
    "strategy_signal_direction_total",
    "Signal generation count by direction",
    ["symbol", "direction"]
)

_signal_strength_histogram = Histogram(
    "strategy_signal_strength_distribution",
    "Signal strength distribution",
    ["symbol"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)

_ema_crossover_events = Counter(
    "strategy_ema_crossover_events_total",
    "EMA crossover events",
    ["symbol", "timeframe", "direction"]
)


@dataclass
class Layer3Telemetry:
    """Counters describing Layer 3 signal generation behavior."""

    ticks_seen: int = 0
    candles_5m_finalized: int = 0
    candles_1h_finalized: int = 0
    signal_checks: int = 0
    signals_emitted: int = 0
    long_signals: int = 0
    short_signals: int = 0
    hold_signals: int = 0
    hold_missing_ofi: int = 0
    hold_missing_primary_history: int = 0
    hold_missing_higher_history: int = 0
    hold_primary_candle_unreliable: int = 0
    hold_system_state_halt: int = 0
    hold_system_state_degraded: int = 0
    hold_primary_gate_failed: int = 0
    hold_primary_rsi_failed: int = 0
    hold_primary_macd_failed: int = 0
    hold_primary_bollinger_failed: int = 0
    hold_primary_ema_failed: int = 0
    hold_ofi_gate_failed: int = 0
    hold_higher_timeframe_disagreement: int = 0
    hold_unknown: int = 0


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
    telemetry: Layer3Telemetry = field(init=False)

    def __post_init__(self) -> None:
        self.candle_manager = CandleAggregationManager(symbol=self.symbol)
        self.indicator_manager = IndicatorManager(symbol=self.symbol)
        self.ofi_state = OrderFlowImbalanceState(symbol=self.symbol)
        self.primary_history = deque(maxlen=3)
        self.higher_history = deque(maxlen=2)
        self.telemetry = Layer3Telemetry()

    def ingest_tick(self, tick: ScoredTick) -> list[TradeSignal]:
        self.telemetry.ticks_seen += 1
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

            # Export technical indicator metrics
            if snapshot.rsi is not None:
                _indicator_rsi.labels(symbol=self.symbol, timeframe=event.timeframe).set(snapshot.rsi)
            
            if snapshot.macd_histogram is not None:
                _indicator_macd_histogram.labels(symbol=self.symbol, timeframe=event.timeframe).set(snapshot.macd_histogram)
            
            # Calculate Bollinger Band width (normalized)
            if (snapshot.bollinger_upper is not None and 
                snapshot.bollinger_lower is not None and 
                snapshot.bollinger_middle is not None and 
                snapshot.bollinger_middle > 0):
                bb_width = (snapshot.bollinger_upper - snapshot.bollinger_lower) / snapshot.bollinger_middle
                _indicator_bb_width.labels(symbol=self.symbol, timeframe=event.timeframe).set(bb_width)
            
            # Export EMA crossover events
            if snapshot.ema_cross is not None:
                _ema_crossover_events.labels(symbol=self.symbol, timeframe=event.timeframe, direction=snapshot.ema_cross).inc()

            if event.timeframe == "5m":
                self.telemetry.candles_5m_finalized += 1
                self.primary_history.append(snapshot)
                produced_signals.extend(self._maybe_emit_signal(system_state=effective_state))
            elif event.timeframe == "1h":
                self.telemetry.candles_1h_finalized += 1
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
            
            # Export technical indicator metrics
            if snapshot.rsi is not None:
                _indicator_rsi.labels(symbol=self.symbol, timeframe=event.timeframe).set(snapshot.rsi)
            
            if snapshot.macd_histogram is not None:
                _indicator_macd_histogram.labels(symbol=self.symbol, timeframe=event.timeframe).set(snapshot.macd_histogram)
            
            # Calculate Bollinger Band width (normalized)
            if (snapshot.bollinger_upper is not None and 
                snapshot.bollinger_lower is not None and 
                snapshot.bollinger_middle is not None and 
                snapshot.bollinger_middle > 0):
                bb_width = (snapshot.bollinger_upper - snapshot.bollinger_lower) / snapshot.bollinger_middle
                _indicator_bb_width.labels(symbol=self.symbol, timeframe=event.timeframe).set(bb_width)
            
            # Export EMA crossover events
            if snapshot.ema_cross is not None:
                _ema_crossover_events.labels(symbol=self.symbol, timeframe=event.timeframe, direction=snapshot.ema_cross).inc()
            
            if event.timeframe == "5m":
                self.telemetry.candles_5m_finalized += 1
                self.primary_history.append(snapshot)
                produced_signals.extend(self._maybe_emit_signal(system_state=effective_state))
            elif event.timeframe == "1h":
                self.telemetry.candles_1h_finalized += 1
                self.higher_history.append(snapshot)
        return produced_signals

    def _maybe_emit_signal(self, *, system_state: SystemState | None = None, tick: ScoredTick | None = None) -> list[TradeSignal]:
        self.telemetry.signal_checks += 1
        if self.latest_ofi is None:
            self.telemetry.hold_signals += 1
            self.telemetry.hold_missing_ofi += 1
            return []
        if len(self.primary_history) < 3 or len(self.higher_history) < 2:
            self.telemetry.hold_signals += 1
            if len(self.primary_history) < 3:
                self.telemetry.hold_missing_primary_history += 1
            if len(self.higher_history) < 2:
                self.telemetry.hold_missing_higher_history += 1
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
        
        # Export signal direction metric for all signals (including HOLD)
        _signal_direction_count.labels(symbol=self.symbol, direction=sized.direction).inc()
        
        # Export signal strength metric only for non-HOLD signals
        if sized.direction != "HOLD":
            _signal_strength_histogram.labels(symbol=self.symbol).observe(sized.signal_strength)
        
        if sized.direction == "HOLD":
            self.telemetry.hold_signals += 1
            reason = signal.reason or "unknown"
            if reason == "primary candle not reliable":
                self.telemetry.hold_primary_candle_unreliable += 1
            elif reason.startswith("primary gate failed"):
                self.telemetry.hold_primary_gate_failed += 1
                # Parse breakdown from reason string: "primary gate failed|rsi_ok,macd_ok,..."
                if "|" in reason:
                    breakdown_str = reason.split("|", 1)[1]
                    if "rsi_ok" in breakdown_str:
                        self.telemetry.hold_primary_rsi_failed += 1
                    if "macd_ok" in breakdown_str:
                        self.telemetry.hold_primary_macd_failed += 1
                    if "bollinger_ok" in breakdown_str:
                        self.telemetry.hold_primary_bollinger_failed += 1
                    if "ema_ok" in breakdown_str:
                        self.telemetry.hold_primary_ema_failed += 1
            elif reason in {"OFI long gate failed", "OFI short gate failed"}:
                self.telemetry.hold_ofi_gate_failed += 1
            elif reason == "higher timeframe disagreement":
                self.telemetry.hold_higher_timeframe_disagreement += 1
            elif reason == "system_state=HALT":
                self.telemetry.hold_system_state_halt += 1
            elif reason == "system_state=DEGRADED":
                self.telemetry.hold_system_state_degraded += 1
            else:
                self.telemetry.hold_unknown += 1
            return []
        self.telemetry.signals_emitted += 1
        if sized.direction == "LONG":
            self.telemetry.long_signals += 1
        elif sized.direction == "SHORT":
            self.telemetry.short_signals += 1
        _last_signal_size.labels(symbol=self.symbol).set(float(sized.size_pct))
        return [sized]

    def get_telemetry(self) -> dict[str, object]:
        """Return a flat snapshot for reporting."""

        return {
            "ticks_seen": self.telemetry.ticks_seen,
            "candles_5m_finalized": self.telemetry.candles_5m_finalized,
            "candles_1h_finalized": self.telemetry.candles_1h_finalized,
            "signal_checks": self.telemetry.signal_checks,
            "signals_emitted": self.telemetry.signals_emitted,
            "long_signals": self.telemetry.long_signals,
            "short_signals": self.telemetry.short_signals,
            "hold_signals": self.telemetry.hold_signals,
            "hold_missing_ofi": self.telemetry.hold_missing_ofi,
            "hold_missing_primary_history": self.telemetry.hold_missing_primary_history,
            "hold_missing_higher_history": self.telemetry.hold_missing_higher_history,
            "hold_primary_candle_unreliable": self.telemetry.hold_primary_candle_unreliable,
            "hold_system_state_halt": self.telemetry.hold_system_state_halt,
            "hold_system_state_degraded": self.telemetry.hold_system_state_degraded,
            "hold_primary_gate_failed": self.telemetry.hold_primary_gate_failed,
            "hold_primary_rsi_failed": self.telemetry.hold_primary_rsi_failed,
            "hold_primary_macd_failed": self.telemetry.hold_primary_macd_failed,
            "hold_primary_bollinger_failed": self.telemetry.hold_primary_bollinger_failed,
            "hold_primary_ema_failed": self.telemetry.hold_primary_ema_failed,
            "hold_ofi_gate_failed": self.telemetry.hold_ofi_gate_failed,
            "hold_higher_timeframe_disagreement": self.telemetry.hold_higher_timeframe_disagreement,
            "hold_unknown": self.telemetry.hold_unknown,
        }

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
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9104")))
    mark_service_healthy("layer3_strategy", "layer3")
    svc = build_service()
    svc.run_forever()


if __name__ == "__main__":
    main()

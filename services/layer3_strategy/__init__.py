"""Layer 3 strategy package with candle, bootstrap, and indicator helpers."""

from .candles import Candle, CandleAggregationEvent, CandleAggregationManager, CandleAggregator
from .indicators import (
    IndicatorManager,
    IndicatorSnapshot,
    TimeframeIndicatorState,
)
from .ofi import OrderFlowImbalanceSnapshot, OrderFlowImbalanceState
from .signals import (
    ConfluenceLevel,
    SignalThresholds,
    TradeSignal,
    evaluate_dual_timeframe_signal,
)
from .sizing import PositionSizingConfig, PositionSizingResult, size_trade_signal

__all__ = [
    "Candle",
    "CandleAggregationEvent",
    "CandleAggregationManager",
    "CandleAggregator",
    "IndicatorManager",
    "IndicatorSnapshot",
    "TimeframeIndicatorState",
    "OrderFlowImbalanceSnapshot",
    "OrderFlowImbalanceState",
    "ConfluenceLevel",
    "SignalThresholds",
    "TradeSignal",
    "evaluate_dual_timeframe_signal",
    "PositionSizingConfig",
    "PositionSizingResult",
    "size_trade_signal",
]
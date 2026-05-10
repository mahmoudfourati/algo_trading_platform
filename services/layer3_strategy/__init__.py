"""Layer 3 strategy package with candle, bootstrap, and indicator helpers."""

from .candles import Candle, CandleAggregationEvent, CandleAggregationManager, CandleAggregator
from .feature_flags import Layer3FeatureFlags, load_layer3_feature_flags
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
from .service import Layer3Service, Layer3SymbolState, build_service

__all__ = [
    "Candle",
    "CandleAggregationEvent",
    "CandleAggregationManager",
    "CandleAggregator",
    "Layer3FeatureFlags",
    "load_layer3_feature_flags",
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
    "Layer3Service",
    "Layer3SymbolState",
    "build_service",
]
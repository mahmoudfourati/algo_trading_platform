"""Shared Pydantic schemas.

Defines canonical message contracts exchanged between services (Kafka payloads).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


ExchangeId = Literal["binance", "coinbase", "kraken", "okx", "bybit"]


class RawTick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exchange_id: ExchangeId
    symbol: str = Field(description="Normalized symbol, e.g. 'BTC-USDT'")
    bid: float
    ask: float
    last_price: float
    volume_24h: float
    exchange_timestamp_ms: int
    received_timestamp_ms: int
    timestamp_source: Literal["exchange", "receive"] = "exchange"
    sequence_id: Optional[int] = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


class NormalizedTick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exchange_id: ExchangeId
    symbol: str = Field(description="Normalized symbol, e.g. 'BTC-USDT'")
    bid: float
    ask: float
    last_price: float
    volume_24h: float
    exchange_timestamp_ms: int
    received_timestamp_ms: int
    timestamp_source: Literal["exchange", "receive"] = "exchange"
    sequence_id: Optional[int] = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


class ValidatedTick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    asset_class: Literal["crypto"] = "crypto"
    primary_exchange: ExchangeId = Field(description="Configured primary exchange for downstream operation.")
    mid_price: float = Field(description="Primary exchange mid price used by downstream layers.")
    consensus_mid: float = Field(description="Consensus mid computed from the validated source set.")
    # Optional for backward compatibility with previously emitted ticks.
    # Layer 2 uses these fields if present for feature construction.
    volume_24h: Optional[float] = Field(default=None, description="Primary exchange 24h volume.")
    spread: Optional[float] = Field(
        default=None,
        description="Primary exchange relative spread computed as (ask-bid)/mid_price.",
    )
    trust_score: float
    sub_scores: dict[str, float]
    used_sources: list[ExchangeId]
    divergent_sources: list[ExchangeId]
    # Optional map of overdue exchanges -> silence_ms.
    liveness: Optional[dict[str, float]] = None
    timestamp_utc: int
    tick_hash: str


SystemState = Literal["NORMAL", "CONSERVATIVE", "DEGRADED", "HALT"]


class ScoredTick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ValidatedTick fields
    symbol: str
    asset_class: Literal["crypto"] = "crypto"
    primary_exchange: ExchangeId
    mid_price: float
    consensus_mid: float
    volume_24h: Optional[float] = None
    spread: Optional[float] = None
    trust_score: float
    sub_scores: dict[str, float]
    used_sources: list[ExchangeId]
    divergent_sources: list[ExchangeId]
    timestamp_utc: int
    tick_hash: str

    # Layer 2 fields
    anomaly_score: float
    if_score: float
    hst_score: float
    regime: int
    regime_posterior: list[float]
    system_state: SystemState
    mad_guard_triggered: bool


class ApprovedOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    direction: Literal["LONG", "SHORT", "CLOSE_ALL"]
    size_pct: float
    signal_strength: float
    confluence: Literal["FULL", "PARTIAL", "NONE"]
    ofi: float
    trust_score: float
    timestamp_utc: int
    entry_price: float
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    atr: Optional[float] = None
    system_state: SystemState
    circuit_breaker_state: Literal["NORMAL", "REDUCED", "HALTED"] = "NORMAL"
    portfolio_exposure_pct: float = 0.0
    primary_timeframe_snapshot: dict[str, object] = Field(default_factory=dict)
    higher_timeframe_snapshot: dict[str, object] = Field(default_factory=dict)
    candle_reliability: dict[str, bool] = Field(default_factory=dict)
    risk_adjustments: list[str] = Field(default_factory=list)
    reason: str = ""


class ExecutedOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    client_order_id: Optional[str] = None
    symbol: str
    filled_pct: float
    avg_fill_price: float
    fee_paid: float
    slippage_pct: float
    note: Optional[str] = None


# Schema versioning constants
SCHEMA_VERSIONS = {
    "ApprovedOrder": "v1",
    "ExecutedOrder": "v1",
}

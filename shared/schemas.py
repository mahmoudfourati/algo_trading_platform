"""Shared Pydantic schemas.

Defines canonical message contracts exchanged between services (Kafka payloads).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


ExchangeId = Literal["binance", "coinbase", "kraken", "okx", "bybit"]


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
    sequence_id: Optional[int] = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


class ValidatedTick(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    asset_class: Literal["crypto"] = "crypto"
    mid_price: float
    # Optional for backward compatibility with previously emitted ticks.
    # Layer 2 uses these fields if present for feature construction.
    volume_24h: Optional[float] = None
    spread: Optional[float] = Field(
        default=None,
        description="Relative spread computed as (ask-bid)/mid_price, aggregated across used sources.",
    )
    trust_score: float
    sub_scores: dict[str, float]
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
    mid_price: float
    volume_24h: Optional[float] = None
    spread: Optional[float] = None
    trust_score: float
    sub_scores: dict[str, float]
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

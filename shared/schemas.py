"""Shared Pydantic schemas.

Defines canonical message contracts exchanged between services (Kafka payloads).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


ExchangeId = Literal["binance", "coinbase", "kraken", "okx", "bybit"]


class RawTick(BaseModel):
    """Raw tick from exchange adapter before validation.
    
    This is the first message in the pipeline, emitted by Layer 1 ingestion adapters.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="v1", description="Schema version for compatibility checking")
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
    # SAFETY: Pessimistic default - assume TLS unhealthy until adapter explicitly validates.
    # Adapters must set tls_ok=True after successful TLS pin verification.
    # This ensures trust score T1 subscore is 0.0 for unvalidated ticks.
    tls_ok: bool = False

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0
    
    @field_validator('timestamp_source')
    @classmethod
    def validate_timestamp_source(cls, v: str, info) -> str:
        """Validate timestamp_source matches exchange requirements.
        
        Kraken must use 'receive' (no reliable exchange timestamps).
        All other exchanges should use 'exchange' (more accurate).
        
        This is a warning-level validation - we log but don't reject.
        """
        if 'exchange_id' in info.data:
            exchange_id = info.data['exchange_id']
            
            # Kraken should use 'receive' due to unreliable exchange timestamps
            if exchange_id == 'kraken' and v != 'receive':
                # Note: We don't raise an error, just document the expectation
                # Adapters should handle this, but we allow flexibility
                pass
            
            # Other exchanges should use 'exchange' for better accuracy
            elif exchange_id != 'kraken' and v == 'receive':
                # Again, we document but don't enforce
                pass
        
        return v
    
    def to_dict_canonical(self) -> dict:
        """Convert to canonical dict representation for hash chain computation.
        
        Returns:
            Dict with sorted keys suitable for hash computation
        """
        data = self.model_dump(exclude_none=True)
        return dict(sorted(data.items()))


class NormalizedTick(BaseModel):
    """Normalized tick after adapter-specific transformations.
    
    Intermediate format used within Layer 1 pipeline.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="v1", description="Schema version for compatibility checking")
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
    # SAFETY: Pessimistic default - assume TLS unhealthy until adapter explicitly validates.
    # Mirrors RawTick.tls_ok — carried through the adapter pipeline so the
    # validated service can read the real pin-check result from the tick itself.
    tls_ok: bool = False

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0
    
    @field_validator('timestamp_source')
    @classmethod
    def validate_timestamp_source(cls, v: str, info) -> str:
        """Validate timestamp_source matches exchange requirements.
        
        Kraken must use 'receive' (no reliable exchange timestamps).
        All other exchanges should use 'exchange' (more accurate).
        """
        if 'exchange_id' in info.data:
            exchange_id = info.data['exchange_id']
            
            # Kraken should use 'receive' due to unreliable exchange timestamps
            if exchange_id == 'kraken' and v != 'receive':
                pass  # Document expectation but don't enforce
            
            # Other exchanges should use 'exchange' for better accuracy
            elif exchange_id != 'kraken' and v == 'receive':
                pass  # Document expectation but don't enforce
        
        return v
    
    def to_dict_canonical(self) -> dict:
        """Convert to canonical dict representation for hash chain computation.
        
        Returns:
            Dict with sorted keys suitable for hash computation
        """
        data = self.model_dump(exclude_none=True)
        return dict(sorted(data.items()))


class ValidatedTick(BaseModel):
    """Validated tick with consensus pricing and trust scoring.
    
    This model represents the output of Layer 1 after multi-source consensus,
    trust scoring, and hash chain validation.
    
    Fields:
        execution_venue_prices: Dict of exchange_id -> mid_price for execution-time
            divergence checking. Populated by Layer 1 with all exchanges that
            participated in consensus.
            
            Behavior:
            - Empty dict: Backward compatibility (old Layer 1 versions) or no consensus
            - Missing venue: Execution venue not in consensus (Layer 5 should reject)
            - Present: Use for divergence check in Layer 5
            
            Example:
                {"binance": 75500.0, "coinbase": 75498.0, "kraken": 75502.0}
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="v2", description="Schema version (v2 adds execution_venue_prices)")
    symbol: str
    asset_class: Literal["crypto"] = "crypto"
    # DEPRECATED: primary_exchange kept for backward compatibility but no longer used for pricing
    primary_exchange: ExchangeId = Field(description="Deprecated: Kept for backward compatibility. Use execution_venue instead.")
    mid_price: float = Field(description="Consensus mid price from multi-source validation (used by all downstream layers).")
    consensus_mid: float = Field(description="Consensus mid computed from the validated source set (same as mid_price).")
    # NEW: Execution venue prices for divergence checking at execution time
    execution_venue_prices: dict[ExchangeId, float] = Field(
        default_factory=dict,
        description="Mid prices from each exchange for execution-time divergence checking."
    )
    # Optional for backward compatibility with previously emitted ticks.
    # Layer 2 uses these fields if present for feature construction.
    volume_24h: Optional[float] = Field(default=None, description="Median 24h volume across consensus sources.")
    spread: Optional[float] = Field(
        default=None,
        description="Median relative spread across consensus sources computed as (ask-bid)/mid_price.",
    )
    trust_score: float
    sub_scores: dict[str, float]
    used_sources: list[ExchangeId]
    divergent_sources: list[ExchangeId]
    # Optional map of overdue exchanges -> silence_ms.
    liveness: Optional[dict[str, float]] = None
    timestamp_utc: int
    tick_hash: str
    
    def check_execution_venue(self, venue: ExchangeId) -> tuple[bool, str]:
        """Check if execution venue price is available for divergence checking.
        
        Args:
            venue: Exchange ID where order will be executed (e.g., "binance")
            
        Returns:
            (is_available, reason) tuple:
            - (True, "ok"): Venue price available
            - (False, "execution_venue_prices_empty"): No venue prices (backward compat)
            - (False, "execution_venue_{venue}_not_in_prices"): Venue not in consensus
            
        Example:
            >>> tick = ValidatedTick(...)
            >>> is_ok, reason = tick.check_execution_venue("binance")
            >>> if not is_ok:
            ...     print(f"Cannot execute: {reason}")
        """
        if not self.execution_venue_prices:
            return (False, "execution_venue_prices_empty")
        
        if venue not in self.execution_venue_prices:
            return (False, f"execution_venue_{venue}_not_in_prices")
        
        return (True, "ok")
    
    def validate_execution_venue_prices(self) -> tuple[bool, str]:
        """Validate execution_venue_prices dict is properly populated.
        
        Returns:
            (is_valid, message) tuple:
            - (True, "ok"): Dict is properly populated
            - (False, "execution_venue_prices_empty"): Dict is empty (backward compat warning)
            - (False, "execution_venue_prices_invalid_price"): Contains invalid prices
            
        Example:
            >>> tick = ValidatedTick(...)
            >>> is_valid, msg = tick.validate_execution_venue_prices()
            >>> if not is_valid:
            ...     logger.warning(f"Venue prices validation: {msg}")
        """
        if not self.execution_venue_prices:
            return (False, "execution_venue_prices_empty")
        
        # Check all prices are positive
        for venue, price in self.execution_venue_prices.items():
            if price <= 0:
                return (False, f"execution_venue_prices_invalid_price_{venue}_{price}")
        
        return (True, "ok")
    
    def to_dict_canonical(self) -> dict:
        """Convert to canonical dict representation for hash chain computation.
        
        This method ensures consistent serialization for cryptographic hashing.
        Fields are sorted alphabetically and optional fields with None are excluded.
        
        Returns:
            Dict with sorted keys suitable for hash computation
            
        Example:
            >>> tick = ValidatedTick(...)
            >>> canonical = tick.to_dict_canonical()
            >>> hash_input = json.dumps(canonical, sort_keys=True)
        """
        data = self.model_dump(exclude_none=True, exclude={"tick_hash"})
        # Sort keys for deterministic serialization
        return dict(sorted(data.items()))


SystemState = Literal["NORMAL", "CONSERVATIVE", "DEGRADED", "HALT"]


class ScoredTick(BaseModel):
    """Scored tick with anomaly detection and regime classification.
    
    Output of Layer 2 after HMM regime detection and anomaly scoring.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="v1", description="Schema version for compatibility checking")
    # ValidatedTick fields
    symbol: str
    asset_class: Literal["crypto"] = "crypto"
    primary_exchange: ExchangeId  # Deprecated but kept for compatibility
    mid_price: float  # Consensus price
    consensus_mid: float  # Same as mid_price
    execution_venue_prices: dict[ExchangeId, float] = Field(default_factory=dict)
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
    anomaly_reason: str = ""  # NEW: Primary reason for anomaly score
    anomaly_reasons: list[str] = Field(default_factory=list)  # Multiple reasons (for future use)
    if_score: float = 0.0  # Deprecated
    hst_score: float = 0.0  # Deprecated
    regime: int
    regime_posterior: list[float]
    system_state: SystemState
    mad_guard_triggered: bool


class ApprovedOrder(BaseModel):
    """Risk-approved trading order ready for execution.
    
    Output of Layer 4 after risk checks and position sizing.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="v1", description="Schema version for compatibility checking")
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
    """Executed order with fill details and slippage.
    
    Output of Layer 5 after order execution.
    """
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="v1", description="Schema version for compatibility checking")
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
    "RawTick": "v1",
    "NormalizedTick": "v1",
    "ValidatedTick": "v2",  # v2 adds execution_venue_prices
    "ScoredTick": "v1",
    "ApprovedOrder": "v1",
    "ExecutedOrder": "v1",
}


def validate_schema_version(model_name: str, actual_version: str) -> tuple[bool, str]:
    """Validate schema version matches expected version.
    
    Args:
        model_name: Name of the model class (e.g., "RawTick", "ValidatedTick")
        actual_version: Version string from the message (e.g., "v1", "v2")
        
    Returns:
        (is_valid, message) tuple:
        - (True, "ok"): Version matches expected
        - (False, "version_mismatch_..."): Version doesn't match
        - (False, "unknown_model"): Model name not in SCHEMA_VERSIONS
        
    Example:
        >>> is_valid, msg = validate_schema_version("RawTick", "v1")
        >>> if not is_valid:
        ...     logger.warning(f"Schema version issue: {msg}")
        ...     # Emit audit event for version skew detection
    """
    if model_name not in SCHEMA_VERSIONS:
        return (False, f"unknown_model_{model_name}")
    
    expected_version = SCHEMA_VERSIONS[model_name]
    
    if actual_version != expected_version:
        return (False, f"version_mismatch_{model_name}_expected_{expected_version}_got_{actual_version}")
    
    return (True, "ok")

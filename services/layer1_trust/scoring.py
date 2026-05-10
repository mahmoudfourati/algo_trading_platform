"""Layer 1 trust scoring.

Computes subscores (T1..T5 + T_availability) and aggregates them into a weighted
trust score in [0,1].
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, Optional, Set

from shared.schemas import ExchangeId, NormalizedTick


HALF_LIFE_MS = 25.0
LAMBDA = math.log(2.0) / HALF_LIFE_MS

T2_HALF_LIFE_MS = 7_500.0


@dataclass(frozen=True)
class TrustWeights:
    w1_tls: float
    w2_consensus: float
    w3_freshness: float
    w4_sequence: float
    w5_hash_chain: float
    w_availability: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "T1": self.w1_tls,
            "T2": self.w2_consensus,
            "T3": self.w3_freshness,
            "T4": self.w4_sequence,
            "T5": self.w5_hash_chain,
            "T_availability": self.w_availability,
        }


def load_trust_weights(path: Optional[str] = None) -> TrustWeights:
    """Load weights from a JSON file.

    Path defaults to env TRUST_WEIGHTS_PATH, then config/trust_weights.json.
    """

    weights_path = path or os.getenv("TRUST_WEIGHTS_PATH", os.path.join("config", "trust_weights.json"))
    with open(weights_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return TrustWeights(
        w1_tls=float(raw["w1_tls"]),
        w2_consensus=float(raw["w2_consensus"]),
        w3_freshness=float(raw["w3_freshness"]),
        w4_sequence=float(raw["w4_sequence"]),
        w5_hash_chain=float(raw["w5_hash_chain"]),
        w_availability=float(raw.get("w_availability", 0.1)),  # Default 0.1 for backward compat
    )


def t1_tls_validity(*, tls_ok: bool) -> float:
    return 1.0 if tls_ok else 0.0


def t2_consensus_agreement(*, agreeing_sources: int, total_sources: int) -> float:
    if total_sources <= 0:
        return 0.0
    agreeing = max(0, min(int(agreeing_sources), int(total_sources)))
    return float(agreeing) / float(total_sources)


def compute_t2(
    *,
    ticks_with_age: list[tuple[NormalizedTick, float]],
    consensus_price: float,
    tolerance: float,
    active_sources: set[ExchangeId],
) -> float:
    """Freshness-weighted source agreement score.

    Each source contributes a weight = exp(-age_ms / T2_HALF_LIFE_MS * ln2).
    Only sources in `active_sources` are included.
    """

    weighted_agreement = 0.0
    total_weight = 0.0

    for tick, age_ms in ticks_with_age:
        if tick.exchange_id not in active_sources:
            continue
        weight = math.exp(-float(age_ms) / float(T2_HALF_LIFE_MS) * math.log(2.0))
        agrees = 1.0 if abs(tick.mid - float(consensus_price)) <= float(tolerance) else 0.0
        weighted_agreement += weight * agrees
        total_weight += weight

    return weighted_agreement / total_weight if total_weight > 0 else 0.0


def t3_latency_freshness(*, latency_ms: float) -> float:
    ms = max(0.0, float(latency_ms))
    return math.exp(-LAMBDA * ms)


def t4_sequence_integrity(*, gap: Optional[int]) -> float:
    """Sequence integrity score per blueprint.

    - gap==1 => 1.0
    - gap>1 => 1/gap
    - gap>=10 => 0.0

    If gap is None (sequence not available), returns 1.0 (no penalty applied).
    """

    if gap is None:
        return 1.0

    g = int(gap)
    if g <= 0:
        return 0.0
    if g == 1:
        return 1.0
    if g >= 10:
        return 0.0
    return 1.0 / float(g)


def t5_hash_chain_continuity(*, chain_ok: bool) -> float:
    return 1.0 if chain_ok else 0.0


def t_availability(*, active_exchanges: Set[ExchangeId], configured_exchanges: Set[ExchangeId]) -> float:
    """Exchange availability score.
    
    Penalizes missing exchanges to incentivize multi-source resilience.
    
    T_availability = active_exchanges / configured_exchanges
    
    Args:
        active_exchanges: Set of exchanges that contributed to this window
        configured_exchanges: Set of all exchanges that should be active
        
    Returns:
        Score in [0, 1] where 1.0 = all configured exchanges active
    """
    if not configured_exchanges:
        return 1.0
    
    active_count = len(active_exchanges & configured_exchanges)
    configured_count = len(configured_exchanges)
    
    return float(active_count) / float(configured_count)


def compute_trust_score(*, weights: TrustWeights, subscores: Dict[str, float]) -> float:
    """Weighted linear trust score: T = sum(w_i * T_i)."""

    score = (
        weights.w1_tls * float(subscores["T1"])
        + weights.w2_consensus * float(subscores["T2"])
        + weights.w3_freshness * float(subscores["T3"])
        + weights.w4_sequence * float(subscores["T4"])
        + weights.w5_hash_chain * float(subscores["T5"])
        + weights.w_availability * float(subscores.get("T_availability", 1.0))
    )

    # Trust score is defined on [0,1].
    return max(0.0, min(1.0, score))


def compute_subscores(
    *,
    tls_ok: bool,
    t2: float,
    latency_ms: float,
    sequence_gap: Optional[int],
    chain_ok: bool,
    active_exchanges: Optional[Set[ExchangeId]] = None,
    configured_exchanges: Optional[Set[ExchangeId]] = None,
) -> Dict[str, float]:
    """Compute all trust subscores.
    
    Args:
        tls_ok: TLS pin verification passed
        t2: Consensus agreement score (pre-computed)
        latency_ms: Median latency in milliseconds
        sequence_gap: Sequence ID gap (None if not available)
        chain_ok: Hash chain continuity check passed
        active_exchanges: Set of exchanges active in this window (optional)
        configured_exchanges: Set of all configured exchanges (optional)
        
    Returns:
        Dict of subscore name -> value in [0, 1]
    """
    subscores = {
        "T1": t1_tls_validity(tls_ok=tls_ok),
        "T2": max(0.0, min(1.0, float(t2))),
        "T3": t3_latency_freshness(latency_ms=latency_ms),
        "T4": t4_sequence_integrity(gap=sequence_gap),
        "T5": t5_hash_chain_continuity(chain_ok=chain_ok),
    }
    
    # Add availability score if exchange sets provided
    if active_exchanges is not None and configured_exchanges is not None:
        subscores["T_availability"] = t_availability(
            active_exchanges=active_exchanges,
            configured_exchanges=configured_exchanges
        )
    
    return subscores

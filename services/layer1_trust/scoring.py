from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Dict, Optional


HALF_LIFE_MS = 25.0
LAMBDA = math.log(2.0) / HALF_LIFE_MS


@dataclass(frozen=True)
class TrustWeights:
    w1_tls: float
    w2_consensus: float
    w3_freshness: float
    w4_sequence: float
    w5_hash_chain: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "T1": self.w1_tls,
            "T2": self.w2_consensus,
            "T3": self.w3_freshness,
            "T4": self.w4_sequence,
            "T5": self.w5_hash_chain,
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
    )


def t1_tls_validity(*, tls_ok: bool) -> float:
    return 1.0 if tls_ok else 0.0


def t2_consensus_agreement(*, agreeing_sources: int, total_sources: int) -> float:
    if total_sources <= 0:
        return 0.0
    agreeing = max(0, min(int(agreeing_sources), int(total_sources)))
    return float(agreeing) / float(total_sources)


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


def compute_trust_score(*, weights: TrustWeights, subscores: Dict[str, float]) -> float:
    """Weighted linear trust score: T = sum(w_i * T_i)."""

    score = (
        weights.w1_tls * float(subscores["T1"])
        + weights.w2_consensus * float(subscores["T2"])
        + weights.w3_freshness * float(subscores["T3"])
        + weights.w4_sequence * float(subscores["T4"])
        + weights.w5_hash_chain * float(subscores["T5"])
    )

    # Trust score is defined on [0,1].
    return max(0.0, min(1.0, score))


def compute_subscores(
    *,
    tls_ok: bool,
    agreeing_sources: int,
    total_sources: int,
    latency_ms: float,
    sequence_gap: Optional[int],
    chain_ok: bool,
) -> Dict[str, float]:
    return {
        "T1": t1_tls_validity(tls_ok=tls_ok),
        "T2": t2_consensus_agreement(agreeing_sources=agreeing_sources, total_sources=total_sources),
        "T3": t3_latency_freshness(latency_ms=latency_ms),
        "T4": t4_sequence_integrity(gap=sequence_gap),
        "T5": t5_hash_chain_continuity(chain_ok=chain_ok),
    }

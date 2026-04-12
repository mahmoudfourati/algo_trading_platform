from __future__ import annotations

import math

import pytest

from services.layer1_trust.scoring import (
    HALF_LIFE_MS,
    TrustWeights,
    compute_subscores,
    compute_trust_score,
    t2_consensus_agreement,
    t3_latency_freshness,
    t4_sequence_integrity,
)


def test_t2_consensus_agreement() -> None:
    assert t2_consensus_agreement(agreeing_sources=3, total_sources=3) == 1.0
    assert t2_consensus_agreement(agreeing_sources=2, total_sources=3) == 2.0 / 3.0
    assert t2_consensus_agreement(agreeing_sources=1, total_sources=3) == 1.0 / 3.0
    assert t2_consensus_agreement(agreeing_sources=0, total_sources=3) == 0.0


def test_t3_latency_freshness_half_life() -> None:
    # At 0ms latency, freshness is 1.0
    assert t3_latency_freshness(latency_ms=0.0) == pytest.approx(1.0)

    # At half-life (25ms), freshness is 0.5
    assert t3_latency_freshness(latency_ms=HALF_LIFE_MS) == pytest.approx(0.5, abs=1e-9)

    # At 50ms, it should be 0.25
    assert t3_latency_freshness(latency_ms=2 * HALF_LIFE_MS) == pytest.approx(0.25, abs=1e-9)


def test_t4_sequence_integrity_gap_penalty() -> None:
    assert t4_sequence_integrity(gap=None) == 1.0
    assert t4_sequence_integrity(gap=1) == 1.0
    assert t4_sequence_integrity(gap=2) == 0.5
    assert t4_sequence_integrity(gap=3) == pytest.approx(1.0 / 3.0)
    assert t4_sequence_integrity(gap=9) == pytest.approx(1.0 / 9.0)
    assert t4_sequence_integrity(gap=10) == 0.0
    assert t4_sequence_integrity(gap=100) == 0.0


def test_combined_trust_score_matches_hand_computed_example() -> None:
    weights = TrustWeights(w1_tls=0.25, w2_consensus=0.30, w3_freshness=0.20, w4_sequence=0.15, w5_hash_chain=0.10)

    subscores = compute_subscores(
        tls_ok=True,           # T1=1
        agreeing_sources=2,    # T2=2/3
        total_sources=3,
        latency_ms=25.0,       # T3=0.5
        sequence_gap=2,        # T4=0.5
        chain_ok=False,        # T5=0
    )

    # Hand compute:
    # T = 0.25*1 + 0.30*(2/3) + 0.20*0.5 + 0.15*0.5 + 0.10*0
    expected = 0.25 * 1.0 + 0.30 * (2.0 / 3.0) + 0.20 * 0.5 + 0.15 * 0.5 + 0.10 * 0.0

    assert compute_trust_score(weights=weights, subscores=subscores) == pytest.approx(expected)

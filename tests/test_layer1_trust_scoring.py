"""Tests for Layer 1 trust scoring.

Validates subscores (T1..T5) and weighted aggregation behavior.
"""

from __future__ import annotations

import math

import pytest

from services.layer1_trust.scoring import (
    HALF_LIFE_MS,
    T2_HALF_LIFE_MS,
    TrustWeights,
    compute_t2,
    compute_subscores,
    compute_trust_score,
    t3_latency_freshness,
    t4_sequence_integrity,
)

from shared.schemas import NormalizedTick


def _tick(*, exchange_id: str, mid: float) -> NormalizedTick:
    return NormalizedTick(
        exchange_id=exchange_id,  # type: ignore[arg-type]
        symbol="BTC-USDT",
        bid=mid - 0.01,
        ask=mid + 0.01,
        last_price=mid,
        volume_24h=1.0,
        exchange_timestamp_ms=0,
        received_timestamp_ms=0,
        sequence_id=None,
    )


def test_compute_t2_all_agree_is_one() -> None:
    ticks_with_age = [(_tick(exchange_id="binance", mid=100.0), 0.0), (_tick(exchange_id="coinbase", mid=100.0), 0.0)]
    t2 = compute_t2(
        ticks_with_age=ticks_with_age,
        consensus_price=100.0,
        tolerance=0.5,
        active_sources={"binance", "coinbase"},  # type: ignore[arg-type]
    )
    assert t2 == pytest.approx(1.0)


def test_compute_t2_half_life_weighting() -> None:
    # One agreeing source now (w=1.0) and one disagreeing source at half-life ago (w=0.5).
    ticks_with_age = [
        (_tick(exchange_id="binance", mid=100.0), 0.0),
        (_tick(exchange_id="coinbase", mid=110.0), T2_HALF_LIFE_MS),
    ]
    t2 = compute_t2(
        ticks_with_age=ticks_with_age,
        consensus_price=100.0,
        tolerance=0.1,
        active_sources={"binance", "coinbase"},  # type: ignore[arg-type]
    )
    # Expected = (1.0*1 + 0.5*0) / (1.0 + 0.5) = 2/3
    assert t2 == pytest.approx(2.0 / 3.0)


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
        t2=2.0 / 3.0,
        latency_ms=25.0,       # T3=0.5
        sequence_gap=2,        # T4=0.5
        chain_ok=False,        # T5=0
    )

    # Hand compute:
    # T = 0.25*1 + 0.30*(2/3) + 0.20*0.5 + 0.15*0.5 + 0.10*0
    expected = 0.25 * 1.0 + 0.30 * (2.0 / 3.0) + 0.20 * 0.5 + 0.15 * 0.5 + 0.10 * 0.0

    assert compute_trust_score(weights=weights, subscores=subscores) == pytest.approx(expected)

"""Tests for LKV aligner + weighted T2.

Covers LKV carry-forward with staleness gating, active-source tracking,
and the expected weighting behavior of the continuous T2 score.
"""

from __future__ import annotations

import pytest

from services.layer1_consensus.engine import LIVENESS_THRESHOLD_MS, LKV_STALENESS_MS, TickAligner
from services.layer1_trust.scoring import T2_HALF_LIFE_MS, compute_t2
from shared.schemas import NormalizedTick


def _tick(*, ex: str, symbol: str, mid: float, recv_ms: int) -> NormalizedTick:
    return NormalizedTick(
        exchange_id=ex,  # type: ignore[arg-type]
        symbol=symbol,
        bid=mid - 0.01,
        ask=mid + 0.01,
        last_price=mid,
        volume_24h=1.0,
        exchange_timestamp_ms=recv_ms,
        received_timestamp_ms=recv_ms,
        sequence_id=None,
    )


def test_lkv_fills_missing_sources_when_fresh() -> None:
    aligner = TickAligner(window_ms=50)
    sym = "BTC-USDT"

    # Window 1: both sources present; establishes LKV for coinbase.
    aligner.add(_tick(ex="coinbase", symbol=sym, mid=100.0, recv_ms=0))
    aligner.add(_tick(ex="binance", symbol=sym, mid=100.0, recv_ms=10))
    windows = aligner.flush_due(now_ms=60)
    assert len(windows) == 1

    # Window 2: only binance ticks arrive, but coinbase LKV is still fresh -> fill.
    aligner.add(_tick(ex="binance", symbol=sym, mid=100.1, recv_ms=100))
    windows2 = aligner.flush_due(now_ms=160)
    assert len(windows2) == 1
    w = windows2[0]

    assert set(w.by_ex.keys()) == {"binance", "coinbase"}  # type: ignore[comparison-overlap]

    ages = {t.exchange_id: age for (t, age) in w.ticks_with_age}
    assert ages["binance"] == pytest.approx(0.0)
    assert 0.0 < ages["coinbase"] <= LKV_STALENESS_MS


def test_lkv_does_not_fill_when_stale() -> None:
    aligner = TickAligner(window_ms=50)
    sym = "BTC-USDT"

    aligner.add(_tick(ex="coinbase", symbol=sym, mid=100.0, recv_ms=0))
    windows = aligner.flush_due(now_ms=60)
    assert len(windows) == 1

    aligner.add(_tick(ex="binance", symbol=sym, mid=100.1, recv_ms=20_000))
    windows2 = aligner.flush_due(now_ms=20_060)
    assert len(windows2) == 1
    w = windows2[0]

    assert set(w.by_ex.keys()) == {"binance"}  # type: ignore[comparison-overlap]


def test_active_sources_excludes_inactive() -> None:
    aligner = TickAligner(window_ms=50)
    sym = "BTC-USDT"

    aligner.add(_tick(ex="coinbase", symbol=sym, mid=100.0, recv_ms=0))
    windows = aligner.flush_due(now_ms=60)
    assert len(windows) == 1

    aligner.add(_tick(ex="binance", symbol=sym, mid=100.1, recv_ms=LIVENESS_THRESHOLD_MS + 10))
    windows2 = aligner.flush_due(now_ms=LIVENESS_THRESHOLD_MS + 70)
    assert len(windows2) == 1
    w = windows2[0]

    assert "coinbase" not in w.active_sources  # type: ignore[operator]


def test_compute_t2_respects_active_sources() -> None:
    ticks_with_age = [
        (_tick(ex="binance", symbol="BTC-USDT", mid=100.0, recv_ms=0), 0.0),
        (_tick(ex="coinbase", symbol="BTC-USDT", mid=100.0, recv_ms=0), T2_HALF_LIFE_MS),
    ]

    t2 = compute_t2(
        ticks_with_age=ticks_with_age,
        consensus_price=100.0,
        tolerance=0.1,
        active_sources={"binance"},  # type: ignore[arg-type]
    )
    assert t2 == pytest.approx(1.0)

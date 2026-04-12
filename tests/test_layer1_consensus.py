from __future__ import annotations

import time

import pytest

from services.layer1_consensus.engine import ConsensusConfig, ConsensusEngine
from shared.schemas import NormalizedTick


def _tick(
    *,
    exchange_id: str,
    symbol: str,
    mid: float,
    volume_24h: float = 100.0,
    ts_ms: int | None = None,
) -> NormalizedTick:
    ts = int(time.time() * 1000) if ts_ms is None else ts_ms
    return NormalizedTick(
        exchange_id=exchange_id,  # type: ignore[arg-type]
        symbol=symbol,
        bid=mid - 0.01,
        ask=mid + 0.01,
        last_price=mid,
        volume_24h=volume_24h,
        exchange_timestamp_ms=ts,
        received_timestamp_ms=ts,
        sequence_id=None,
    )


def test_outlier_quarantined_consensus_between_good_sources() -> None:
    eng = ConsensusEngine(ConsensusConfig(divergence_tolerance=0.003, min_sources_for_consensus=2))

    symbol = "BTC-USDT"
    ticks = {
        "binance": _tick(exchange_id="binance", symbol=symbol, mid=100.00),
        "coinbase": _tick(exchange_id="coinbase", symbol=symbol, mid=100.05),
        "kraken": _tick(exchange_id="kraken", symbol=symbol, mid=101.00),  # 0.95% high => divergent
    }

    out = eng.process_aligned(symbol, ticks)  # type: ignore[arg-type]

    assert "kraken" in out.divergent_sources
    assert "kraken" in out.quarantined_sources
    assert out.consensus_mid is not None

    good_mids = [ticks["binance"].mid, ticks["coinbase"].mid]
    assert min(good_mids) <= out.consensus_mid <= max(good_mids)


def test_quarantine_release_when_back_in_tolerance() -> None:
    eng = ConsensusEngine(ConsensusConfig(divergence_tolerance=0.003, min_sources_for_consensus=2))

    symbol = "ETH-USDT"

    # Window 1: Kraken is divergent -> quarantined.
    ticks1 = {
        "binance": _tick(exchange_id="binance", symbol=symbol, mid=200.00),
        "coinbase": _tick(exchange_id="coinbase", symbol=symbol, mid=200.01),
        "kraken": _tick(exchange_id="kraken", symbol=symbol, mid=202.00),
    }
    out1 = eng.process_aligned(symbol, ticks1)  # type: ignore[arg-type]
    assert "kraken" in out1.quarantined_sources

    # Window 2: Kraken comes back close to others -> should be released.
    ticks2 = {
        "binance": _tick(exchange_id="binance", symbol=symbol, mid=200.02),
        "coinbase": _tick(exchange_id="coinbase", symbol=symbol, mid=200.03),
        "kraken": _tick(exchange_id="kraken", symbol=symbol, mid=200.04),
    }
    out2 = eng.process_aligned(symbol, ticks2)  # type: ignore[arg-type]
    assert "kraken" not in out2.quarantined_sources
    assert out2.consensus_mid is not None


def test_consecutive_divergence_escalates_on_third_strike() -> None:
    eng = ConsensusEngine(
        ConsensusConfig(divergence_tolerance=0.003, min_sources_for_consensus=2, escalate_after=3)
    )

    symbol = "BTC-USDT"

    for i in range(2):
        out = eng.process_aligned(
            symbol,
            {
                "binance": _tick(exchange_id="binance", symbol=symbol, mid=100.00 + i * 0.01),
                "coinbase": _tick(exchange_id="coinbase", symbol=symbol, mid=100.02 + i * 0.01),
                "kraken": _tick(exchange_id="kraken", symbol=symbol, mid=101.50),
            },
        )  # type: ignore[arg-type]
        assert "kraken" in out.quarantined_sources
        assert out.escalated_sources == []

    out3 = eng.process_aligned(
        symbol,
        {
            "binance": _tick(exchange_id="binance", symbol=symbol, mid=100.03),
            "coinbase": _tick(exchange_id="coinbase", symbol=symbol, mid=100.05),
            "kraken": _tick(exchange_id="kraken", symbol=symbol, mid=101.50),
        },
    )  # type: ignore[arg-type]
    assert "kraken" in out3.escalated_sources

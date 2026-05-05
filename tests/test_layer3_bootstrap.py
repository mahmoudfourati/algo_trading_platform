"""Tests for Layer 3 candle bootstrap helpers."""

from __future__ import annotations

from services.layer3_strategy.bootstrap import BinanceCandleBootstrapper, BootstrapCandle


def test_builds_binance_rest_url() -> None:
    bootstrapper = BinanceCandleBootstrapper(fetcher=lambda url: [])

    url = bootstrapper.build_url(symbol="BTC-USDT", timeframe="5m", limit=500)

    assert url.startswith("https://api.binance.com/api/v3/klines?")
    assert "symbol=BTCUSDT" in url
    assert "interval=5m" in url
    assert "limit=500" in url


def test_fetch_last_candles_truncates_to_limit() -> None:
    rows = [
        [0, "100", "101", "99", "100.5", "10", 0, "1000", 1],
        [300_000, "101", "102", "100", "101.5", "11", 0, "1100", 2],
        [600_000, "102", "103", "101", "102.5", "12", 0, "1200", 3],
    ]

    bootstrapper = BinanceCandleBootstrapper(fetcher=lambda url: rows)
    candles = bootstrapper.fetch_last_candles(symbol="BTCUSDT", timeframe="5m", limit=2)

    assert len(candles) == 2
    assert candles[0].start_time_utc == 300_000
    assert candles[1].start_time_utc == 600_000
    assert candles[1].close == 102.5


def test_validate_continuity_accepts_exact_handoff() -> None:
    bootstrapper = BinanceCandleBootstrapper(fetcher=lambda url: [])
    last_bootstrap = BootstrapCandle(
        symbol="BTCUSDT",
        timeframe="5m",
        start_time_utc=0,
        end_time_utc=300_000,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
        quote_volume=1000.0,
        trade_count=1,
    )

    result = bootstrapper.validate_continuity(
        bootstrapped_last_candle=last_bootstrap,
        first_live_candle_start_time_utc=300_000,
    )

    assert result.valid is True
    assert "verified" in result.message


def test_validate_continuity_rejects_gap_and_overlap() -> None:
    bootstrapper = BinanceCandleBootstrapper(fetcher=lambda url: [])
    last_bootstrap = BootstrapCandle(
        symbol="BTCUSDT",
        timeframe="5m",
        start_time_utc=0,
        end_time_utc=300_000,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=10.0,
        quote_volume=1000.0,
        trade_count=1,
    )

    gap = bootstrapper.validate_continuity(
        bootstrapped_last_candle=last_bootstrap,
        first_live_candle_start_time_utc=360_000,
    )
    overlap = bootstrapper.validate_continuity(
        bootstrapped_last_candle=last_bootstrap,
        first_live_candle_start_time_utc=240_000,
    )

    assert gap.valid is False
    assert "gap" in gap.message
    assert overlap.valid is False
    assert "overlap" in overlap.message
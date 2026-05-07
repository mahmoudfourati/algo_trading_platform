"""Binance candle bootstrap helpers for Layer 3.

This module fetches the initial candle history needed to warm up the 5m and 1h
strategy streams, and it validates that the last bootstrapped candle connects
cleanly to the first live candle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Iterable, Optional
from urllib.parse import urlencode
from urllib.request import urlopen


BINANCE_REST_BASE_URL = "https://api.binance.com/api/v3/klines"

TIMEFRAME_TO_BINANCE_INTERVAL: dict[str, str] = {
    "5m": "5m",
    "1h": "1h",
}

TIMEFRAME_TO_MS: dict[str, int] = {
    "5m": 5 * 60 * 1000,
    "1h": 60 * 60 * 1000,
}


@dataclass(frozen=True)
class BootstrapCandle:
    """Normalized Binance kline used to seed the strategy layer."""

    symbol: str
    timeframe: str
    start_time_utc: int
    end_time_utc: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trade_count: int


@dataclass(frozen=True)
class BootstrapValidationResult:
    """Result of validating a bootstrap/live candle handoff."""

    valid: bool
    message: str


def _normalize_symbol(symbol: str) -> str:
    return symbol.replace("-", "").upper()


def _binance_interval(timeframe: str) -> str:
    try:
        return TIMEFRAME_TO_BINANCE_INTERVAL[timeframe]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe: {timeframe}") from exc


def _timeframe_ms(timeframe: str) -> int:
    try:
        return TIMEFRAME_TO_MS[timeframe]
    except KeyError as exc:
        raise ValueError(f"Unsupported timeframe: {timeframe}") from exc


def _default_fetcher(url: str) -> list[list[object]]:
    with urlopen(url) as response:  # nosec - controlled Binance REST endpoint
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError("Binance response was not a kline list")
    return data


class BinanceCandleBootstrapper:
    """Fetch and validate warmup candles from Binance REST."""

    def __init__(self, *, fetcher: Callable[[str], list[list[object]]] | None = None) -> None:
        self._fetcher = fetcher or _default_fetcher

    def build_url(self, *, symbol: str, timeframe: str, limit: int = 500) -> str:
        params = urlencode({"symbol": _normalize_symbol(symbol), "interval": _binance_interval(timeframe), "limit": int(limit)})
        return f"{BINANCE_REST_BASE_URL}?{params}"

    def fetch_last_candles(self, *, symbol: str, timeframe: str, limit: int = 500) -> list[BootstrapCandle]:
        """Fetch the most recent candles for a symbol and timeframe."""

        if limit <= 0:
            raise ValueError("limit must be positive")

        url = self.build_url(symbol=symbol, timeframe=timeframe, limit=limit)
        rows = self._fetcher(url)
        return [self._row_to_candle(symbol=symbol, timeframe=timeframe, row=row) for row in rows[-limit:]]

    def validate_continuity(
        self,
        *,
        bootstrapped_last_candle: BootstrapCandle,
        first_live_candle_start_time_utc: int,
    ) -> BootstrapValidationResult:
        """Verify that bootstrap ends exactly where live ingestion begins."""

        expected_start = bootstrapped_last_candle.end_time_utc
        actual_start = int(first_live_candle_start_time_utc)

        if actual_start == expected_start:
            return BootstrapValidationResult(valid=True, message="bootstrap/live candle continuity verified")

        if actual_start < expected_start:
            return BootstrapValidationResult(
                valid=False,
                message=(
                    "bootstrap/live candle overlap detected: "
                    f"last_bootstrap_end={expected_start}, first_live_start={actual_start}"
                ),
            )

        return BootstrapValidationResult(
            valid=False,
            message=(
                "bootstrap/live candle gap detected: "
                f"last_bootstrap_end={expected_start}, first_live_start={actual_start}"
            ),
        )

    def _row_to_candle(self, *, symbol: str, timeframe: str, row: Iterable[object]) -> BootstrapCandle:
        values = list(row)
        if len(values) < 8:
            raise ValueError("Binance kline row has fewer than 8 fields")

        start_time_utc = int(values[0])
        end_time_utc = start_time_utc + _timeframe_ms(timeframe)
        return BootstrapCandle(
            symbol=symbol,
            timeframe=timeframe,
            start_time_utc=start_time_utc,
            end_time_utc=end_time_utc,
            open=float(values[1]),
            high=float(values[2]),
            low=float(values[3]),
            close=float(values[4]),
            volume=float(values[5]),
            quote_volume=float(values[7]),
            trade_count=int(values[8]) if len(values) > 8 else 0,
        )

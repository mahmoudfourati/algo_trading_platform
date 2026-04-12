from __future__ import annotations

import csv
import io
import os
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Iterator, List, Tuple

import httpx


@dataclass(frozen=True)
class KlineRow:
    open_time_ms: int
    close_price: float


def _normalize_epoch_ms(ts: int) -> int:
    # Binance kline timestamps are typically milliseconds since epoch (~1.7e12 today),
    # but some datasets appear to use microseconds (~1.7e15) or nanoseconds (~1.7e18).
    if ts >= 10**17:
        return ts // 1_000_000
    if ts >= 10**14:
        return ts // 1_000
    return ts


def _ymd(d: date) -> str:
    return d.isoformat()


def build_daily_kline_zip_url(*, symbol: str, interval: str, day: date) -> str:
    # Example:
    # https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2026-04-10.zip
    base = "https://data.binance.vision/data/spot/daily/klines"
    return f"{base}/{symbol}/{interval}/{symbol}-{interval}-{_ymd(day)}.zip"


def download_daily_klines(
    *,
    symbol: str,
    interval: str,
    day: date,
    cache_dir: str | Path,
    timeout_s: float = 60.0,
) -> Path:
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    url = build_daily_kline_zip_url(symbol=symbol, interval=interval, day=day)
    out = cache / f"{symbol}-{interval}-{_ymd(day)}.zip"
    if out.exists() and out.stat().st_size > 0:
        return out

    with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
        r = client.get(url)
        if r.status_code == 404:
            raise FileNotFoundError(f"Binance Vision daily kline not found: {url}")
        r.raise_for_status()
        out.write_bytes(r.content)
    return out


def iter_daily_close_prices(zip_path: str | Path) -> Iterator[KlineRow]:
    """Yield (open_time_ms, close_price) from a Binance Vision daily zip."""

    p = Path(zip_path)
    with zipfile.ZipFile(p, "r") as z:
        names = z.namelist()
        if not names:
            return
        # Binance daily zips contain a single CSV.
        with z.open(names[0], "r") as f:
            text = io.TextIOWrapper(f, encoding="utf-8")
            reader = csv.reader(text)
            for row in reader:
                # Binance kline format:
                # 0 open_time, 1 open, 2 high, 3 low, 4 close, 5 volume, ...
                if len(row) < 5:
                    continue
                yield KlineRow(open_time_ms=_normalize_epoch_ms(int(row[0])), close_price=float(row[4]))


def date_range(*, end_inclusive: date, days: int) -> List[date]:
    if days <= 0:
        raise ValueError("days must be positive")
    start = end_inclusive - timedelta(days=days - 1)
    out = []
    d = start
    while d <= end_inclusive:
        out.append(d)
        d += timedelta(days=1)
    return out

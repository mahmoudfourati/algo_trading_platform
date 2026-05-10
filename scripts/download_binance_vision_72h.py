"""Purpose: Download 72h of Binance Vision 1m klines and convert to ticks_raw.csv."""

from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import httpx


def build_kline_url(symbol: str, interval: str, day: date) -> str:
    ymd = day.isoformat()
    base = "https://data.binance.vision/data/spot/daily/klines"
    return f"{base}/{symbol}/{interval}/{symbol}-{interval}-{ymd}.zip"


def download_klines(symbol: str, interval: str, start_day: date, end_day: date, cache_dir: Path) -> Iterator[list]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    d = start_day
    while d <= end_day:
        url = build_kline_url(symbol, interval, d)
        zip_path = cache_dir / f"{symbol}-{interval}-{d.isoformat()}.zip"
        
        # Download if not cached
        if not zip_path.exists() or zip_path.stat().st_size == 0:
            print(f"Downloading {url}")
            with httpx.Client(timeout=60.0) as client:
                try:
                    r = client.get(url)
                    if r.status_code == 404:
                        print(f"Not found: {url}")
                        d += timedelta(days=1)
                        continue
                    r.raise_for_status()
                    zip_path.write_bytes(r.content)
                except Exception as e:
                    print(f"Failed to download: {e}")
                    d += timedelta(days=1)
                    continue
        
        # Extract and yield rows
        try:
            with zipfile.ZipFile(zip_path, 'r') as z:
                names = z.namelist()
                if names:
                    with z.open(names[0], 'r') as f:
                        text = io.TextIOWrapper(f, encoding='utf-8')
                        reader = csv.reader(text)
                        for row in reader:
                            if len(row) >= 5:
                                yield row
        except Exception as e:
            print(f"Error reading {zip_path}: {e}")
        
        d += timedelta(days=1)


def normalize_epoch_ms(ts: int) -> int:
    if ts >= 10**17:
        return ts // 1_000_000
    if ts >= 10**14:
        return ts // 1_000
    return ts


def kline_to_ticks(rows: Iterator[list], output_path: Path) -> None:
    """Convert Binance klines (OHLCV) to tick format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    ticks = []
    for row in rows:
        try:
            open_time_ms = normalize_epoch_ms(int(row[0]))
            open_price = float(row[1])
            high_price = float(row[2])
            low_price = float(row[3])
            close_price = float(row[4])
            volume = float(row[5])
            
            ts_utc = datetime.fromtimestamp(open_time_ms / 1000.0, tz=timezone.utc).isoformat()
            mid = (high_price + low_price) / 2.0
            spread = high_price - low_price
            bid = mid - spread / 2.0
            ask = mid + spread / 2.0
            
            ticks.append({
                'timestamp_utc': ts_utc,
                'exchange': 'binance',
                'symbol': 'BTCUSDT',
                'bid': round(bid, 2),
                'ask': round(ask, 2),
                'last_price': round(close_price, 2),
                'volume': volume,
            })
        except Exception as e:
            print(f"Error parsing row: {e}")
            continue
    
    with open(output_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['timestamp_utc', 'exchange', 'symbol', 'bid', 'ask', 'last_price', 'volume'])
        writer.writeheader()
        for t in ticks:
            writer.writerow(t)
    
    print(f"Wrote {len(ticks)} ticks to {output_path}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--days', type=int, default=3, help='Days of klines to fetch')
    p.add_argument('--symbol', type=str, default='BTCUSDT')
    p.add_argument('--interval', type=str, default='1m')
    p.add_argument('--cache-dir', type=str, default='artifacts/klines_cache')
    p.add_argument('--output', type=str, default='artifacts/backtest_data/ticks_raw.csv')
    args = p.parse_args()
    
    end_day = date.today()
    start_day = end_day - timedelta(days=args.days - 1)
    
    print(f"Downloading {args.days} days of {args.symbol} {args.interval} klines")
    rows = download_klines(args.symbol, args.interval, start_day, end_day, Path(args.cache_dir))
    kline_to_ticks(rows, Path(args.output))


if __name__ == '__main__':
    main()

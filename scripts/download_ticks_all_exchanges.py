"""Purpose: Download historical trades (ticks) from multiple exchanges using ccxt and
normalize them into artifacts/backtest_data/<exchange>_ticks.csv for backtesting.

Usage:
    . .venv\Scripts\Activate.ps1
    python scripts/download_ticks_all_exchanges.py --hours 72
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List

import ccxt


def ensure_output_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def iso_utc(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc).isoformat()


def fetch_trades_exchange(exchange: ccxt.Exchange, market_symbol: str, since_ms: int, until_ms: int) -> Iterable[dict]:
    # ccxt fetch_trades uses milliseconds since epoch
    all_trades: List[dict] = []
    limit = 1000
    since = since_ms
    while True:
        try:
            trades = exchange.fetch_trades(market_symbol, since=since, limit=limit)
        except Exception as e:
            print(f"fetch_trades error for {exchange.id} {market_symbol}: {e}")
            break

        if not trades:
            break

        all_trades.extend(trades)

        # advance since to last trade + 1 ms
        last_ts = trades[-1]['timestamp'] if trades[-1].get('timestamp') else None
        if last_ts is None:
            break
        if last_ts >= until_ms:
            break
        since = last_ts + 1

        # respect rate limit
        time.sleep(exchange.rateLimit / 1000.0 if getattr(exchange, 'rateLimit', None) else 0.2)

    # filter by until_ms
    for t in all_trades:
        ts = int(t.get('timestamp', 0))
        if ts < since_ms or ts > until_ms:
            continue
        yield t


def pick_market_symbol(exchange: ccxt.Exchange, desired: List[str]) -> str | None:
    markets = exchange.load_markets()
    for s in desired:
        if s in markets:
            return s
    return None


def download_for_exchange(exchange_id: str, symbol_candidates: List[str], start_ms: int, end_ms: int, out_path: Path) -> None:
    print(f"Starting {exchange_id} -> {out_path} ({(end_ms-start_ms)/1000/3600:.1f}h)")
    exchange_cls = getattr(ccxt, exchange_id)
    ex = exchange_cls({'enableRateLimit': True})
    try:
        market = pick_market_symbol(ex, symbol_candidates)
        if market is None:
            print(f"No market found on {exchange_id} for candidates {symbol_candidates}")
            return

        rows = []
        for trade in fetch_trades_exchange(ex, market, start_ms, end_ms):
            price = float(trade.get('price') or 0.0)
            amount = float(trade.get('amount') or 0.0)
            ts = int(trade.get('timestamp') or 0)
            rows.append({'timestamp_utc': iso_utc(ts), 'exchange': exchange_id, 'symbol': market.replace('/','').upper(), 'bid': price, 'ask': price, 'last_price': price, 'volume': amount})

        ensure_output_dir(out_path)
        with open(out_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['timestamp_utc','exchange','symbol','bid','ask','last_price','volume'])
            writer.writeheader()
            for r in rows:
                writer.writerow(r)

        print(f"Wrote {len(rows)} ticks to {out_path}")
    finally:
        try:
            ex.close()
        except Exception:
            pass


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--hours', type=int, default=72, help='Hours of history to fetch per exchange')
    p.add_argument('--out-dir', type=str, default='artifacts/backtest_data')
    args = p.parse_args()

    end = datetime.now(tz=timezone.utc)
    start = end - timedelta(hours=args.hours)
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    out_dir = Path(args.out_dir)
    exchanges = {
        'binance': ['BTC/USDT', 'BTC/USDT:USDT'],
        'bybit': ['BTC/USDT', 'BTC/USDT:USDT'],
        'coinbasepro': ['BTC/USD', 'BTC/USDT', 'BTC-USD'],
        'kraken': ['BTC/USDT', 'BTC/USD', 'XBT/USD'],
        'okx': ['BTC/USDT', 'BTC/USDT:USDT'],
    }

    for ex_id, candidates in exchanges.items():
        out = out_dir / f"{ex_id}_ticks.csv"
        download_for_exchange(ex_id, candidates, start_ms, end_ms, out)


if __name__ == '__main__':
    main()

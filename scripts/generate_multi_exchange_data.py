"""Purpose: Generate multi-exchange CSV files from Binance data with realistic per-exchange variations."""

import csv
from pathlib import Path
import random


def generate_multi_exchange_csvs(source_csv: Path, output_dir: Path) -> None:
    """
    Load Binance data and generate separate CSV files for 5 exchanges with realistic variations.
    Each exchange gets: different bid-ask spreads, small price drifts, latency patterns.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Read Binance anchor data
    records = []
    with open(source_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(row)
    
    print(f"Loaded {len(records)} anchor records from {source_csv}")
    
    # Per-exchange config: (spread_bps, price_drift_pct)
    exchanges = {
        'binance': {'spread_bps': 1.0, 'drift_pct': 0.0},      # baseline
        'bybit': {'spread_bps': 1.5, 'drift_pct': 0.02},       # slightly wider, slight drift
        'coinbase': {'spread_bps': 2.0, 'drift_pct': 0.03},    # wider spread, more drift
        'kraken': {'spread_bps': 2.5, 'drift_pct': 0.04},      # widest, most drift
        'okx': {'spread_bps': 1.2, 'drift_pct': 0.01},         # tight spreads
    }
    
    for exchange_name, config in exchanges.items():
        output_path = output_dir / f"{exchange_name}_ticks.csv"
        
        with open(output_path, 'w', encoding='utf-8', newline='') as f:
            fieldnames = ['timestamp_utc', 'exchange', 'symbol', 'bid', 'ask', 'last_price', 'volume']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for i, row in enumerate(records):
                ts = row.get('timestamp_utc', row.get('timestamp', ''))
                symbol = row.get('symbol', 'BTCUSDT')
                bid = float(row.get('bid', row.get('last_price', 0)))
                ask = float(row.get('ask', row.get('last_price', 0)))
                last = float(row.get('last_price', bid))
                vol = float(row.get('volume', 1000))
                
                # Apply per-exchange variations
                spread_bps = config['spread_bps']
                drift_pct = config['drift_pct']
                
                # Add drift
                drift_factor = 1.0 + (drift_pct / 100.0 * random.gauss(0, 1))
                last = last * drift_factor
                
                # Apply spread
                spread = last * (spread_bps / 10000)
                bid = last - spread/2
                ask = last + spread/2
                
                writer.writerow({
                    'timestamp_utc': ts,
                    'exchange': exchange_name,
                    'symbol': symbol,
                    'bid': round(bid, 2),
                    'ask': round(ask, 2),
                    'last_price': round(last, 2),
                    'volume': vol,
                })
        
        print(f"✓ Generated {exchange_name}_ticks.csv ({len(records)} records)")


if __name__ == '__main__':
    source = Path('artifacts/backtest_data/ticks_raw.csv')
    output = Path('artifacts/backtest_data')
    generate_multi_exchange_csvs(source, output)
    print("\nMulti-exchange CSVs ready. Backtest will now load all 5 exchanges.")

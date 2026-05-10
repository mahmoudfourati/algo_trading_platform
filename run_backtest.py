#!/usr/bin/env python
"""Run backtest with window_size=500"""
import sys
import statistics
from datetime import datetime, timezone
sys.path.insert(0, 'c:\\Users\\LENOVO\\algo_trading')

from services.backtesting.engine import BacktestEngine, BacktestConfig
from pathlib import Path

if __name__ == "__main__":
    config = BacktestConfig(
        symbol="BTCUSDT",
        scenario="baseline",
        start_time=datetime(2026, 5, 5, 0, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 5, 7, 0, 0, 0, tzinfo=timezone.utc),
        output_dir=Path("artifacts/test_runs"),
    )
    engine = BacktestEngine(config)
    result = engine.run()
    
    # Extract HST/IF means from events
    if_scores = [e.if_score for e in result.metrics.events if hasattr(e, 'if_score')]
    hst_scores = [e.hst_score for e in result.metrics.events if hasattr(e, 'hst_score')]
    
    if_mean = sum(if_scores) / len(if_scores) if if_scores else 0.0
    hst_mean = sum(hst_scores) / len(hst_scores) if hst_scores else 0.0
    
    print(f"\n{'='*60}")
    print(f"✓ Backtest completed: {result.metrics.run_id}")
    print(f"{'='*60}")
    print(f"HST Score Mean:       {hst_mean:.6f}")
    print(f"IF Score Mean:        {if_mean:.6f}")
    print(f"Combined Anomaly Mean: {0.45*if_mean + 0.55*hst_mean:.6f}")
    print(f"False Positive Rate:  {result.metrics.get_false_positive_rate():.4%}")
    print(f"Total Events:         {len(result.metrics.events)}")
    print(f"{'='*60}")

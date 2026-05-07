"""Quick backtest runner for testing fixes."""
import sys
from pathlib import Path
from datetime import datetime
from services.backtesting.engine import BacktestConfig, BacktestEngine

config = BacktestConfig(
    symbol='BTCUSDT',
    scenario='baseline',
    start_time=datetime.fromisoformat('2025-10-01'),
    end_time=datetime.fromisoformat('2025-10-02'),
    output_dir=Path('artifacts/test_runs'),
    hmm_model_path=Path('artifacts/hmm/model.pkl'),
    anomaly_threshold=0.80,  # Further increased from 0.70 to filter out borderline anomalies
)

print("Running backtest with fixes:")
print(f"  - anomaly_threshold = 0.70 (was 0.55)")
print(f"  - MultiSourceGenerator latencies fixed for consensus")
print("")

try:
    engine = BacktestEngine(config)
    result = engine.run()
    print(f"✓ Backtest completed: {result.report_path}")
    print(f"  Equity curve: {result.equity_curve_path}")
except Exception as e:
    print(f"✗ Backtest failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

"""Quick test of backtest engine."""
from pathlib import Path
from datetime import datetime
from services.backtesting.engine import BacktestConfig, BacktestEngine
import json

config = BacktestConfig(
    symbol='BTCUSDT',
    scenario='baseline',
    start_time=datetime.fromisoformat('2025-10-01'),
    end_time=datetime.fromisoformat('2025-10-02'),
    output_dir=Path('artifacts/test_runs/DIRECT_RUN'),
    hmm_model_path=Path('artifacts/hmm/model.pkl'),
)
try:
    print("Starting backtest...")
    result = BacktestEngine(config).run()
    print('Backtest succeeded')
    print('Report path:', result.report_path)
    print('Equity curve path:', result.equity_curve_path)
    print(f'Net PnL: {result.metrics.net_pnl}')
    print(f'Sharpe: {result.metrics.sharpe}')
    print(f'Max drawdown: {result.metrics.max_drawdown}')
except Exception as e:
    print(f'Error: {type(e).__name__}: {e}')
    import traceback
    traceback.print_exc()

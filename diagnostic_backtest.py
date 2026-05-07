"""Diagnostic backtest to trace layer-by-layer behavior."""
from pathlib import Path
from datetime import datetime
from services.backtesting.engine import BacktestConfig, Layer1Simulator, Layer2Simulator, Layer3SymbolState, Layer4RiskEngine
from services.backtesting.data_loader import HistoricalTickLoader
from services.layer5_execution.engine import ExecutionEngine
from services.layer5_execution.adapters import SimulatedExecutionAdapter
import json

config = BacktestConfig(
    symbol='BTCUSDT',
    scenario='baseline',
    start_time=datetime.fromisoformat('2025-10-01'),
    end_time=datetime.fromisoformat('2025-10-02'),
    output_dir=Path('artifacts/test_runs'),
    hmm_model_path=Path('artifacts/hmm/model.pkl'),
)

# load ticks
loader = HistoricalTickLoader(symbols=['BTCUSDT'], start_date=config.start_time, end_date=config.end_time, source_path=None, cache_path=None)
records = loader.load()
print(f"Loaded {len(records)} records")

# init layers
from services.backtesting.engine import MultiSourceGenerator
layer1 = Layer1Simulator(primary_exchange='binance', enabled_exchanges=config.enabled_exchanges, window_ms=config.window_ms)
layer2 = Layer2Simulator(hmm_model_path=config.hmm_model_path, if_weight=0.45, hst_weight=0.55, trust_threshold=0.6, anomaly_threshold=0.70)
layer3 = Layer3SymbolState(symbol='BTCUSDT')
layer4 = Layer4RiskEngine()
gen = MultiSourceGenerator()

# process first 10 records and log
print("\n=== FIRST 10 RECORDS ===\n")
count = 0
for i, rec in enumerate(records[:100]):
    synth_ticks = list(gen.generate([rec]))
    for tick in synth_ticks:
        validated_list = layer1.ingest(tick)
        print(f"Rec {i} Ex {tick.exchange_id}: price={tick.last_price:.2f} -> {len(validated_list)} validated")
        
        for vt in validated_list:
            print(f"  L1: trust={vt.trust_score:.4f}, T2={vt.sub_scores.get('T2'):.4f}, T3={vt.sub_scores.get('T3'):.4f}")
            
            scored = layer2.score(vt)
            print(f"  L2: anomaly={scored.anomaly_score:.4f}, state={scored.system_state}")
            
            signals = layer3.ingest_tick(scored)
            print(f"  L3: {len(signals)} signals")
            for sig in signals:
                print(f"     signal: {sig.direction} {sig.size_pct:.4f}, strength={sig.strength:.4f}")
                decision = layer4.evaluate_signal(sig, reference_price=scored.mid_price, current_portfolio_exposure_pct=0.0, timestamp_utc=sig.timestamp_utc)
                print(f"     L4: approved={decision.approved}, reason={decision.rejection_reason}")
        count += 1
        if count >= 10:
            break
    if count >= 10:
        break

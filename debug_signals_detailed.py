"""Detailed signal generation tracing."""
from pathlib import Path
from datetime import datetime
from services.backtesting.engine import MultiSourceGenerator, Layer1Simulator, Layer2Simulator, Layer3SymbolState, BacktestConfig
from services.backtesting.data_loader import HistoricalTickLoader
from services.layer3_strategy.signals import evaluate_dual_timeframe_signal

config = BacktestConfig(
    symbol='BTCUSDT',
    scenario='baseline',
    start_time=datetime.fromisoformat('2025-10-01'),
    end_time=datetime.fromisoformat('2025-10-02'),
    output_dir=Path('artifacts/test_runs'),
    hmm_model_path=Path('artifacts/hmm/model.pkl'),
    anomaly_threshold=0.80,
)

loader = HistoricalTickLoader(
    symbols=[config.symbol],
    start_date=config.start_time,
    end_date=config.end_time,
    source_path=config.source_path,
    cache_path=config.cache_path,
)
records = loader.load()

layer1 = Layer1Simulator(primary_exchange=config.primary_exchange, enabled_exchanges=config.enabled_exchanges, window_ms=config.window_ms)
layer2 = Layer2Simulator(hmm_model_path=config.hmm_model_path, if_weight=config.if_weight, hst_weight=config.hst_weight, trust_threshold=config.trust_threshold, anomaly_threshold=config.anomaly_threshold)
layer3 = Layer3SymbolState(symbol=config.symbol)

generator = MultiSourceGenerator()

tick_count = 0
for rec_idx, rec in enumerate(records):
    for tick in generator.generate([rec]):
        for validated in layer1.ingest(tick):
            scored = layer2.score(validated)
            
            # Manually call _maybe_emit_signal with detailed logging
            if layer3.latest_ofi is not None and len(layer3.primary_history) >= 3 and len(layer3.higher_history) >= 2:
                signal = evaluate_dual_timeframe_signal(
                    symbol=config.symbol,
                    primary_snapshots=list(layer3.primary_history),
                    higher_snapshots=list(layer3.higher_history),
                    ofi_snapshot=layer3.latest_ofi,
                    trust_score=scored.trust_score,
                    system_state=scored.system_state,
                )
                if signal.direction != "HOLD":
                    print(f"Tick {tick_count}: {signal.direction} signal! reason={signal.reason}")
                elif tick_count >= 120 and tick_count <= 125:
                    print(f"Tick {tick_count}: HOLD ({signal.reason}), primary_hist={len(layer3.primary_history)}, higher_hist={len(layer3.higher_history)}, ofi={layer3.latest_ofi.ofi:.4f}, state={scored.system_state}")
            
            # Continue with normal Layer 3 ingest
            layer3.ingest_tick(scored)
            tick_count += 1
            
            if tick_count >= 150:
                break
        if tick_count >= 150:
            break
    if tick_count >= 150:
        break

print(f"\nProcessed {tick_count} ticks without signals")

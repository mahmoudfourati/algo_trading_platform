"""Debug script to trace Layer 3 signal generation."""
from pathlib import Path
from datetime import datetime
from services.backtesting.engine import BacktestConfig, BacktestEngine, MultiSourceGenerator, Layer1Simulator, Layer2Simulator, Layer3SymbolState
from services.backtesting.data_loader import HistoricalTickLoader

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
print(f"Loaded {len(records)} records")

layer1 = Layer1Simulator(
    primary_exchange=config.primary_exchange,
    enabled_exchanges=config.enabled_exchanges,
    window_ms=config.window_ms,
)
layer2 = Layer2Simulator(
    hmm_model_path=config.hmm_model_path,
    if_weight=config.if_weight,
    hst_weight=config.hst_weight,
    trust_threshold=config.trust_threshold,
    anomaly_threshold=config.anomaly_threshold,
)
layer3 = Layer3SymbolState(symbol=config.symbol)

generator = MultiSourceGenerator()

signals_emitted = 0
for hour, rec in enumerate(records):
    if hour % 60 == 0:
        print(f"\n=== Hour {hour//60}, Tick {hour} ===")
    
    for tick in generator.generate([rec]):
        for validated in layer1.ingest(tick):
            scored = layer2.score(validated)
            signals = layer3.ingest_tick(scored)
            if signals:
                signals_emitted += 1
                print(f"  HH:MM={hour//60:02d}:{hour%60:02d} Signal: {signals[0].direction} {signals[0].size_pct:.2%}")
            
            if hour >= 120 and hour <= 130:  # Show state around 2h mark
                print(f"  Tick {hour}: primary_hist={len(layer3.primary_history)}, higher_hist={len(layer3.higher_history)}, signals={len(signals)}")

print(f"\nTotal signals emitted: {signals_emitted}")
print(f"Primary candle count: {len(layer3.primary_history)}")
print(f"Higher candle count: {len(layer3.higher_history)}")

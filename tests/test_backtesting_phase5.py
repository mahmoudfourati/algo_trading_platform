"""Phase 5 backtesting core tests."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import joblib

from services.backtesting.attack_scenarios import apply_attack_scenario
from services.backtesting.data_loader import HistoricalTickLoader
import services.backtesting.engine as backtest_engine
from services.backtesting.engine import BacktestConfig, BacktestEngine
from services.backtesting.results_db import ResultsDB
from services.backtesting.time_control import TimeController
from services.layer3_strategy.signals import TradeSignal
from shared.schemas import NormalizedTick


def _write_historical_csv(path: Path) -> None:
    rows = [
        {"timestamp_utc": "2026-01-01T00:00:00Z", "exchange": "binance", "symbol": "BTCUSDT", "bid": 50000.0, "ask": 50001.0, "last_price": 50000.5, "volume": 1000.0},
        {"timestamp_utc": "2026-01-01T00:01:00Z", "exchange": "binance", "symbol": "BTCUSDT", "bid": 50010.0, "ask": 50011.0, "last_price": 50010.5, "volume": 1100.0},
        {"timestamp_utc": "2026-01-01T00:02:00Z", "exchange": "binance", "symbol": "BTCUSDT", "bid": 50020.0, "ask": 50021.0, "last_price": 50020.5, "volume": 1200.0},
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_dummy_hmm_model(path: Path) -> None:
    import numpy as np
    from hmmlearn.hmm import GaussianHMM

    X = np.array([[0.001], [0.002], [0.003], [0.01], [0.011], [0.012]], dtype=float)
    model = GaussianHMM(n_components=2, covariance_type="diag", n_iter=20, random_state=42)
    model.fit(X)
    joblib.dump(model, path)


def _write_trust_weights(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "w1_tls": 0.2,
                "w2_consensus": 0.3,
                "w3_freshness": 0.2,
                "w4_sequence": 0.1,
                "w5_hash_chain": 0.2,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _risk_signal(*, trust_score: float, timestamp_utc: int, size_pct: float = 0.5) -> TradeSignal:
    return TradeSignal(
        symbol="BTCUSDT",
        direction="LONG",
        size_pct=size_pct,
        signal_strength=0.8,
        confluence="FULL",
        ofi=0.25,
        trust_score=trust_score,
        system_state="NORMAL",
        timestamp_utc=timestamp_utc,
        indicator_snapshots={"primary": {"atr": 1.0}, "higher": {"atr": 1.0}},
        candle_reliability={"primary": True, "higher": True},
        reason="integration-fixture",
    )


def test_time_controller_patches_wall_clock() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    controller = TimeController(current_time=start, end_time=start + timedelta(hours=1))

    with controller.patched():
        import time

        assert abs(time.time() - start.timestamp()) < 1e-6
        controller.advance(10)
        assert abs(time.time() - (start + timedelta(seconds=10)).timestamp()) < 1e-6


def test_historical_loader_reads_csv_and_writes_cache(tmp_path: Path) -> None:
    source = tmp_path / "ticks.csv"
    cache = tmp_path / "cache.sqlite"
    _write_historical_csv(source)

    loader = HistoricalTickLoader(
        symbols=["BTCUSDT"],
        start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
        source_path=source,
        cache_path=cache,
    )

    records = loader.load()
    assert len(records) == 3
    assert records[0].symbol == "BTCUSDT"
    assert cache.exists()

    source.unlink()
    cached_records = loader.load()
    assert len(cached_records) == 3
    assert cached_records[1].last_price == 50010.5


def test_backtest_engine_runs_on_synthetic_data(tmp_path: Path) -> None:
    source = tmp_path / "ticks.csv"
    cache = tmp_path / "cache.sqlite"
    hmm_model = tmp_path / "model.pkl"
    trust_weights = tmp_path / "trust_weights.json"
    output_dir = tmp_path / "reports"

    _write_historical_csv(source)
    _write_dummy_hmm_model(hmm_model)
    _write_trust_weights(trust_weights)

    config = BacktestConfig(
        symbol="BTCUSDT",
        scenario="baseline",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        output_dir=output_dir,
        source_path=source,
        cache_path=cache,
        hmm_model_path=hmm_model,
        trust_weights_path=trust_weights,
        time_speed=1.0,
    )

    result = BacktestEngine(config).run()

    assert result.report_path.exists()
    assert result.report_path.name == "report.html"
    assert result.equity_curve_path.exists()
    assert result.metrics.total_ticks > 0
    assert result.metrics.equity_curve_path == str(result.equity_curve_path)
    assert result.metrics.symbol == "BTCUSDT"

    report_text = result.report_path.read_text(encoding="utf-8")
    assert "Phase 5 Backtest Report" in report_text
    assert "Config Snapshot" in report_text

    config_snapshot = result.report_path.parent / "config_snapshot.json"
    assert config_snapshot.exists()

    db_path = output_dir / "results.db"
    assert db_path.exists()
    assert result.metrics.run_id in ResultsDB(db_path).list_run_ids()


def test_attack_injection_flash_crash_changes_price() -> None:
    tick = NormalizedTick(
        exchange_id="binance",
        symbol="BTCUSDT",
        bid=50000.0,
        ask=50001.0,
        last_price=50000.5,
        volume_24h=1000.0,
        exchange_timestamp_ms=1_000,
        received_timestamp_ms=5_000,
        timestamp_source="exchange",
    )

    injected = apply_attack_scenario(
        tick,
        scenario="flash_crash",
        start_ms=0,
        end_ms=10_000,
    )

    assert injected.injected
    assert injected.tick.last_price < tick.last_price


@pytest.mark.parametrize(
    "scenario,exchange_id,assert_fn",
    [
        ("feed_corruption", "binance", lambda injected, original: injected.tick.last_price > original.last_price),
        ("replay_attack", "binance", lambda injected, original: injected.tick.received_timestamp_ms == original.received_timestamp_ms - 200),
        ("gradual_drift", "binance", lambda injected, original: injected.tick.last_price > original.last_price),
        ("coordinated_spoofing", "binance", lambda injected, original: injected.tick.last_price > original.last_price),
        ("coordinated_spoofing", "kraken", lambda injected, original: injected.injected is False),
    ],
)
def test_additional_attack_scenarios_apply_expected_mutations(scenario: str, exchange_id: str, assert_fn) -> None:
    tick = NormalizedTick(
        exchange_id=exchange_id,
        symbol="BTCUSDT",
        bid=50000.0,
        ask=50001.0,
        last_price=50000.5,
        volume_24h=1000.0,
        exchange_timestamp_ms=1_000,
        received_timestamp_ms=5_000,
        timestamp_source="exchange",
    )

    injected = apply_attack_scenario(
        tick,
        scenario=scenario,
        start_ms=0,
        end_ms=10_000,
    )

    assert_fn(injected, tick)


def test_backtest_engine_records_injected_anomalies_for_flash_crash(tmp_path: Path) -> None:
    source = tmp_path / "ticks.csv"
    cache = tmp_path / "cache.sqlite"
    hmm_model = tmp_path / "model.pkl"
    trust_weights = tmp_path / "trust_weights.json"
    output_dir = tmp_path / "reports"

    _write_historical_csv(source)
    _write_dummy_hmm_model(hmm_model)
    _write_trust_weights(trust_weights)

    config = BacktestConfig(
        symbol="BTCUSDT",
        scenario="flash_crash",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        output_dir=output_dir,
        source_path=source,
        cache_path=cache,
        hmm_model_path=hmm_model,
        trust_weights_path=trust_weights,
        time_speed=1.0,
    )

    result = BacktestEngine(config).run()
    assert result.metrics.injected_anomalies > 0
    # detection timing summaries should be present
    assert hasattr(result.metrics, "attack_episode_count")
    assert result.metrics.attack_episode_count >= 1
    assert 0 <= result.metrics.attack_episode_detected_count <= result.metrics.attack_episode_count
    # latency fields should be numeric (floats)
    assert isinstance(result.metrics.attack_detection_latency_ms_first, float)
    assert isinstance(result.metrics.attack_detection_latency_ms_mean, float)
    assert isinstance(result.metrics.attack_detection_latency_ms_max, float)


def test_backtest_engine_computes_permutation_p_value(tmp_path: Path) -> None:
    """Verify that BacktestEngine.run() populates permutation_p_value in metrics."""
    source = tmp_path / "ticks.csv"
    cache = tmp_path / "cache.sqlite"
    hmm_model = tmp_path / "model.pkl"
    trust_weights = tmp_path / "trust_weights.json"
    output_dir = tmp_path / "reports"

    _write_historical_csv(source)
    _write_dummy_hmm_model(hmm_model)
    _write_trust_weights(trust_weights)

    config = BacktestConfig(
        symbol="BTCUSDT",
        scenario="baseline",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        output_dir=output_dir,
        source_path=source,
        cache_path=cache,
        hmm_model_path=hmm_model,
        trust_weights_path=trust_weights,
        time_speed=1.0,
    )

    result = BacktestEngine(config).run()

    # Verify permutation_p_value is set and is a valid probability
    assert result.metrics.permutation_p_value >= 0.0 and result.metrics.permutation_p_value <= 1.0
    # With short equity history, p-value should be 1.0 (not significant)
    # since there are only 3 ticks, so equity_net_history will have ~3 values
    # which is less than 10, so the fallback p-value=1.0 is used
    assert result.metrics.permutation_p_value == 1.0


def test_backtest_routes_signals_through_layer4_risk(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "ticks.csv"
    cache = tmp_path / "cache.sqlite"
    hmm_model = tmp_path / "model.pkl"
    trust_weights = tmp_path / "trust_weights.json"
    output_dir = tmp_path / "reports"

    _write_historical_csv(source)
    _write_dummy_hmm_model(hmm_model)
    _write_trust_weights(trust_weights)

    class FakeLayer3SymbolState:
        def __init__(self, symbol: str) -> None:
            self.symbol = symbol
            self.call_count = 0

        def ingest_tick(self, tick):
            self.call_count += 1
            if self.call_count == 1:
                return [_risk_signal(trust_score=0.95, timestamp_utc=tick.timestamp_utc, size_pct=0.5)]
            if self.call_count == 2:
                return [_risk_signal(trust_score=0.20, timestamp_utc=tick.timestamp_utc, size_pct=0.5)]
            return [_risk_signal(trust_score=0.95, timestamp_utc=tick.timestamp_utc, size_pct=0.5)]

        def flush(self, *, tick):
            return []

    monkeypatch.setattr(backtest_engine, "Layer3SymbolState", FakeLayer3SymbolState)

    config = BacktestConfig(
        symbol="BTCUSDT",
        scenario="baseline",
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 2, tzinfo=timezone.utc),
        output_dir=output_dir,
        source_path=source,
        cache_path=cache,
        hmm_model_path=hmm_model,
        trust_weights_path=trust_weights,
        time_speed=1.0,
    )

    result = BacktestEngine(config).run()

    assert result.metrics.risk_approved_orders >= 1
    assert result.metrics.risk_rejected_orders >= 1
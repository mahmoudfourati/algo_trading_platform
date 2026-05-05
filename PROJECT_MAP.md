<!-- Purpose: Detailed repository map with the real implementation surfaces, phase boundaries, and validation artifacts. -->
# Project Map — Secure Algo Trading Platform

This repository implements a phased, trust-first crypto trading platform. The important thing is not just what exists, but where the actual control points live, how the data moves, and which phase each module belongs to. This map is intentionally more detailed than a folder listing so it can be used as a working reference while the project grows.

## Top-level documents

- [trading_blueprint_final.docx.md](trading_blueprint_final.docx.md)
  - Source blueprint and acceptance criteria.
  - Defines the intended layer contracts, phase order, thresholds, validation rules, and demo constraints.
- [plan.md](plan.md)
  - Live implementation plan and phase checklist.
  - Should match the actual codebase state and phase order.
- [implementation_so_far.md](implementation_so_far.md)
  - Authoritative implementation narrative.
  - Tracks what is complete, what is partial, and what still needs to be built.
- [progress.md](progress.md)
  - Short status ledger of phase completion and evidence.
- [README.md](README.md)
  - Primary run instructions and operator-facing quickstart.
- [docker-compose.yml](docker-compose.yml)
  - Local runtime stack.
- [requirements-dev.txt](requirements-dev.txt)
  - Developer/test dependencies.
- [requirements-ml.txt](requirements-ml.txt)
  - Offline ML dependencies.
- [pytest.ini](pytest.ini)
  - Pytest configuration.

## System overview

The implemented runtime currently looks like this:

- Exchange adapters normalize live ticks and publish `market.ticks.raw`.
- Layer 1 validated service aligns, consensus-checks, trust-scores, and hash-chains ticks, then publishes `market.ticks.validated`.
- Layer 2 consumes validated ticks, scores anomaly/regime/state, and publishes `market.ticks.scored`.
- Layer 3 consumes scored ticks, builds candles, computes indicators, evaluates signals, and sizes positions.
- Backtesting replays historical data through live Layer 1 and Layer 2 code paths and emits reports/artifacts.

## Shared contracts and utilities

Folder: [shared/](shared/)

### [shared/schemas.py](shared/schemas.py)

Canonical Pydantic models exchanged across Kafka topics.

Key contracts:

- `RawTick`
  - Raw ingestion schema for adapter output.
  - Keeps `timestamp_source` and optional `sequence_id` so downstream freshness and replay detection can reason about provenance.
- `NormalizedTick`
  - Canonical Layer 1 ingestion contract.
- `ValidatedTick`
  - Layer 1 output contract.
  - Includes `primary_exchange`, `mid_price`, `consensus_mid`, trust score, divergence metadata, optional `volume_24h` and `spread`, liveness info, and `tick_hash`.
- `ScoredTick`
  - Layer 2 output contract.
  - Extends `ValidatedTick` with anomaly/regime/state fields.
- `SystemState`
  - `NORMAL`, `CONSERVATIVE`, `DEGRADED`, `HALT`.

### [shared/audit.py](shared/audit.py)

Structured audit-event emission helper.

Current role:

- Emits significant lifecycle and security events.
- Used by ingestion, consensus, validated service, Layer 2, and other utilities.

### [shared/tls_pinning.py](shared/tls_pinning.py)

TLS leaf-certificate fingerprint verification helper.

Current role:

- Compares the presented leaf SHA-256 fingerprint against the configured allowlist.
- Supports strict refusal on mismatch.

### [shared/metrics_http.py](shared/metrics_http.py)

Lightweight `/metrics` server helper used by Python services.

### [shared/jsonc.py](shared/jsonc.py)

JSON-with-comments helper for config-like files that carry a header comment block.

## Configuration

Folder: [config/](config/)

- [config/tls_pins.json](config/tls_pins.json)
  - TLS pin allowlist per exchange.
- [config/trust_weights.json](config/trust_weights.json)
  - Layer 1 trust weights.

## Monitoring and operations

Folder: [ops/](ops/)

- [ops/prometheus/prometheus.yml](ops/prometheus/prometheus.yml)
  - Prometheus scrape targets for the service metrics endpoints.
- [ops/grafana/provisioning/datasources/datasource.yml](ops/grafana/provisioning/datasources/datasource.yml)
  - Grafana datasource provisioning.

## Phase 1 and runtime foundation

### Docker Compose

[docker-compose.yml](docker-compose.yml) defines the local stack:

- ZooKeeper
- Kafka
- Prometheus
- Grafana
- Layer 1 and Layer 2 services
- metrics-service

This is the infrastructure base that makes the layered architecture runnable and observable locally.

### Metrics service

Folder: [services/metrics/](services/metrics/)

- [services/metrics/app/main.py](services/metrics/app/main.py)
  - Simple FastAPI service that exposes `/metrics` and a root endpoint.
  - Serves as the reference for the Prometheus pattern used elsewhere.

### Smoke tests and host tooling

Folder: [scripts/](scripts/)

Important host-side scripts:

- [scripts/kafka_smoke_test.py](scripts/kafka_smoke_test.py)
  - Produce/consume and consumer-group semantics test.
- [scripts/consume_market_ticks_raw.py](scripts/consume_market_ticks_raw.py)
  - Debug consumer for raw ticks.
- [scripts/consume_market_ticks_validated.py](scripts/consume_market_ticks_validated.py)
  - Debug consumer for validated ticks.
- [scripts/consume_market_ticks_scored.py](scripts/consume_market_ticks_scored.py)
  - Debug consumer for scored ticks.
- [scripts/print_tls_fingerprint.py](scripts/print_tls_fingerprint.py)
  - Helper to inspect server fingerprints for pinning.
- [scripts/trace_layer1_e2e.py](scripts/trace_layer1_e2e.py)
  - Layer 1 trace harness.
- [scripts/layer1_e2e_test.py](scripts/layer1_e2e_test.py)
  - Layer 1 soak/report generator.

## Phase 2 — Layer 1 trusted ingestion

Folder: [services/layer1_ingestion/](services/layer1_ingestion/)

### Entry points

- [services/layer1_ingestion/run_console.py](services/layer1_ingestion/run_console.py)
  - Runs adapters in console mode and/or publishes to Kafka.
- [services/layer1_ingestion/soak_runner.py](services/layer1_ingestion/soak_runner.py)
  - Long-running soak runner for live feed stability checks.
- [services/layer1_ingestion/kafka_publisher.py](services/layer1_ingestion/kafka_publisher.py)
  - Buffered publisher for `market.ticks.raw`.

### Adapters

Folder: [services/layer1_ingestion/adapters/](services/layer1_ingestion/adapters/)

- [services/layer1_ingestion/adapters/base.py](services/layer1_ingestion/adapters/base.py)
  - Shared reconnect, heartbeat, TLS pinning, and snapshot-on-reconnect logic.
- [services/layer1_ingestion/adapters/binance.py](services/layer1_ingestion/adapters/binance.py)
- [services/layer1_ingestion/adapters/coinbase.py](services/layer1_ingestion/adapters/coinbase.py)
- [services/layer1_ingestion/adapters/kraken.py](services/layer1_ingestion/adapters/kraken.py)
- [services/layer1_ingestion/adapters/okx.py](services/layer1_ingestion/adapters/okx.py)
- [services/layer1_ingestion/adapters/bybit.py](services/layer1_ingestion/adapters/bybit.py)

### What this layer actually does

- Verifies exchange identity through TLS pinning.
- Normalizes exchange-specific payloads to `NormalizedTick`.
- Tracks sequence IDs where available.
- Handles reconnects and short outages.
- Publishes raw ticks into Kafka.

### Tests

- [tests/test_layer1_adapters.py](tests/test_layer1_adapters.py)
- [tests/test_bybit_adapter_parsing.py](tests/test_bybit_adapter_parsing.py)
- [tests/test_tls_pinning.py](tests/test_tls_pinning.py)

## Phase 2 — Layer 1 consensus, trust, and hash log

### Consensus

Folder: [services/layer1_consensus/](services/layer1_consensus/)

- [services/layer1_consensus/engine.py](services/layer1_consensus/engine.py)
  - `TickAligner`
  - `ConsensusEngine`
  - `ConsensusConfig`
  - `ConsensusOutput`

What to look for here:

- 50 ms alignment window.
- LKV fill with staleness gating.
- Divergence quarantine.
- Re-evaluation of quarantined sources.
- Escalation after repeated divergence.
- Volume-weighted median on usable sources.

### Trust scoring

Folder: [services/layer1_trust/](services/layer1_trust/)

- [services/layer1_trust/scoring.py](services/layer1_trust/scoring.py)
  - T1–T5 definitions.
  - `TrustWeights` loader and aggregator.
  - T3 freshness half-life at 25 ms.

### Hash chain

Folder: [services/layer1_hashlog/](services/layer1_hashlog/)

- [services/layer1_hashlog/hash_chain.py](services/layer1_hashlog/hash_chain.py)
  - Append-only validated-window hash chain.
  - Integrity checking and continuity verification.

### Validated service

Folder: [services/layer1_validated/](services/layer1_validated/)

- [services/layer1_validated/service.py](services/layer1_validated/service.py)
  - Kafka consumer for `market.ticks.raw`.
  - Alignment, consensus, trust scoring, liveness, hash-chain append, and `ValidatedTick` publishing.
- [services/layer1_validated/kafka_json_publisher.py](services/layer1_validated/kafka_json_publisher.py)
  - Buffered JSON Kafka publisher helper.
- [services/layer1_validated/liveness.py](services/layer1_validated/liveness.py)
  - Exchange silence / recovery tracking.

### Tests

- [tests/test_layer1_consensus.py](tests/test_layer1_consensus.py)
- [tests/test_layer1_trust_scoring.py](tests/test_layer1_trust_scoring.py)
- [tests/test_layer1_t2_lkv_fix.py](tests/test_layer1_t2_lkv_fix.py)
- [tests/test_layer1_hash_chain.py](tests/test_layer1_hash_chain.py)
- [tests/test_layer1_sequence_gap.py](tests/test_layer1_sequence_gap.py)

## Phase 3 — Offline HMM training

Folder: [services/hmm_training/](services/hmm_training/)

- [services/hmm_training/binance_vision.py](services/hmm_training/binance_vision.py)
  - Historical Binance Vision downloader/parser.
- [services/hmm_training/features.py](services/hmm_training/features.py)
  - Realized-volatility feature construction.
- [services/hmm_training/train.py](services/hmm_training/train.py)
  - HMM training and artifact serialization.

Artifacts:

- [artifacts/hmm/](artifacts/hmm/)
  - `model.pkl`
  - `metadata.json`

Current state:

- The working artifact is a 2-state HMM chosen empirically for the current dataset.
- The code is wired so Layer 2 can load the artifact at startup.

## Phase 4 — Layer 2 anomaly scoring and decision gate

Folder: [services/layer2_anomaly/](services/layer2_anomaly/)

- [services/layer2_anomaly/engine.py](services/layer2_anomaly/engine.py)
  - Rolling features, HMM wrapper, Isolation Forest, Half-Space Trees, MAD guard, and decision gate.
- [services/layer2_anomaly/service.py](services/layer2_anomaly/service.py)
  - Kafka consumer/producer bridge.

Important engine subcomponents:

- `RollingFeatureWindow`
- `RollingRV30m`
- `HMMRegimeClassifier`
- `IsolationForestScorer`
- `HalfSpaceTreeScorer`
- `Layer2ScoringEngine`
- `DecisionGate`

Tests:

- [tests/test_layer2_anomaly.py](tests/test_layer2_anomaly.py)

Important runtime notes:

- Layer 2 consumes `market.ticks.validated` and produces `market.ticks.scored`.
- The decision gate uses trust and anomaly thresholds with hysteresis.
- The service exposes metrics on `:9103/metrics`.

## Phase 5 — Backtesting and validation

Folder: [services/backtesting/](services/backtesting/)

### Core modules

- [services/backtesting/engine.py](services/backtesting/engine.py)
  - Deterministic replay orchestrator.
  - Historical load, synthetic multi-source generation, attack injection, Layer 1 and Layer 2 simulation, metric collection, report output.
- [services/backtesting/data_loader.py](services/backtesting/data_loader.py)
  - Historical tick loading and cache support.
- [services/backtesting/time_control.py](services/backtesting/time_control.py)
  - Deterministic clock control.
- [services/backtesting/metrics.py](services/backtesting/metrics.py)
  - Metrics and scoring-event data models.
- [services/backtesting/report_generator.py](services/backtesting/report_generator.py)
  - HTML report rendering.
- [services/backtesting/results_db.py](services/backtesting/results_db.py)
  - SQLite persistence.
- [services/backtesting/walk_forward.py](services/backtesting/walk_forward.py)
  - Walk-forward validation runner.
- [services/backtesting/permutation_test.py](services/backtesting/permutation_test.py)
  - Sharpe significance helper.
- [services/backtesting/scenario_comparison.py](services/backtesting/scenario_comparison.py)
  - Scenario comparison support.
- [services/backtesting/attack_scenarios.py](services/backtesting/attack_scenarios.py)
  - Synthetic attack injection.

### What this layer currently outputs

- `metrics.json`
- `equity_curve.csv`
- `config_snapshot.json`
- `report.html`
- SQLite run records

### Important current limitation

The backtest still uses Layer 2 system-state transitions as the trade trigger proxy. It does not yet consume actual `TradeSignal` objects from Layer 3. That is the main reason Phase 5/6 validation should still be treated as incomplete from a blueprint-purity perspective.

### Tests

- [tests/test_backtesting_phase5.py](tests/test_backtesting_phase5.py)
- [tests/test_walk_forward.py](tests/test_walk_forward.py)
- [tests/test_permutation_test.py](tests/test_permutation_test.py)
- [tests/test_scenario_comparison.py](tests/test_scenario_comparison.py)
- [tests/test_scenario_comparison_integration.py](tests/test_scenario_comparison_integration.py)

## Phase 6 — Layer 3 strategy engine

Folder: [services/layer3_strategy/](services/layer3_strategy/)

### Core modules

- [services/layer3_strategy/candles.py](services/layer3_strategy/candles.py)
  - 5m/1h candle aggregation.
- [services/layer3_strategy/indicators.py](services/layer3_strategy/indicators.py)
  - RSI, MACD, Bollinger, EMA, ATR.
- [services/layer3_strategy/ofi.py](services/layer3_strategy/ofi.py)
  - Rolling OFI.
- [services/layer3_strategy/signals.py](services/layer3_strategy/signals.py)
  - Pure dual-timeframe signal evaluation.
- [services/layer3_strategy/sizing.py](services/layer3_strategy/sizing.py)
  - Position sizing.
- [services/layer3_strategy/service.py](services/layer3_strategy/service.py)
  - Kafka service wiring for signal generation.
- [services/layer3_strategy/tuning.py](services/layer3_strategy/tuning.py)
  - Grid-search tuning wrapper.

### Tests

- [tests/test_layer3_candles.py](tests/test_layer3_candles.py)
- [tests/test_layer3_bootstrap.py](tests/test_layer3_bootstrap.py)
- [tests/test_layer3_indicators.py](tests/test_layer3_indicators.py)
- [tests/test_layer3_ofi.py](tests/test_layer3_ofi.py)
- [tests/test_layer3_signals.py](tests/test_layer3_signals.py)
- [tests/test_layer3_sizing.py](tests/test_layer3_sizing.py)
- [tests/test_layer3_service.py](tests/test_layer3_service.py)

### Important caveat

The candle model carries an over-threshold `system_state_override`, but the service is still using the upstream scored tick’s state for signal evaluation. That means the override is represented structurally but not yet fully enforced at the decision boundary.

## Phase 6.8 — Tuning artifacts

Relevant files:

- [artifacts/scripts/run_tuning.py](artifacts/scripts/run_tuning.py)
- [artifacts/scripts/walk_forward.py](artifacts/scripts/walk_forward.py)
- [artifacts/scripts/save_tuned_config.py](artifacts/scripts/save_tuned_config.py)
- [artifacts/tuning/](artifacts/tuning/)

Current status:

- Tuning grid search exists.
- Walk-forward runner exists.
- Tuned-threshold snapshot exists.
- The tuning loop is still more of a calibration framework than a final blueprint-grade signal-threshold optimizer.

## Validation and generated artifacts

Important artifact directories:

- [artifacts/reports/](artifacts/reports/)
  - Live integration reports, stress summaries, backtest reports.
- [artifacts/tuning/](artifacts/tuning/)
  - Walk-forward summaries and tuned-threshold snapshots.
- [artifacts/hmm/](artifacts/hmm/)
  - Model and metadata artifacts.
- [artifacts/backtest_data/](artifacts/backtest_data/)
  - Historical tick data used for replay and tuning.

## Test coverage map

The main test surfaces are:

- ingestion and adapters,
- TLS pinning,
- consensus,
- trust scoring,
- hash chain,
- Layer 2 anomaly logic,
- Layer 3 candles, indicators, signals, sizing, and service wiring,
- backtesting,
- walk-forward,
- permutation testing,
- scenario comparison.

## Current implementation boundaries

Still not implemented:

- Layer 4 risk manager.
- Layer 5 execution engine.
- Layer 6 audit-log persistence/rotation verifier.
- Web backend and browser frontend.

Still intentionally simplified:

- The backtest harness is not yet driven by Layer 3 trade signals.
- The permutation test is a practical approximation rather than the exact timestamp-shuffle procedure.
- The HMM is 2-state in the current runtime artifact.

## Hot spots when debugging the current system

If a future issue appears, the most likely files to inspect first are:

- [services/layer1_consensus/engine.py](services/layer1_consensus/engine.py)
- [services/layer1_trust/scoring.py](services/layer1_trust/scoring.py)
- [services/layer1_validated/service.py](services/layer1_validated/service.py)
- [services/layer2_anomaly/engine.py](services/layer2_anomaly/engine.py)
- [services/layer3_strategy/service.py](services/layer3_strategy/service.py)
- [services/backtesting/engine.py](services/backtesting/engine.py)

## Maintenance rule

This map should be updated whenever a new phase lands or an existing phase changes behavior. It should never describe a file as implemented if the code path is still only partially wired.

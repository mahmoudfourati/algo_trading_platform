<!-- Purpose: Single source of truth for what is implemented, how it fits together, and what still remains. -->
# Secure Algorithmic Trading Platform — Implementation Ledger

_Last updated: 2026-05-03_

This file is the authoritative implementation narrative for the repository. It is intentionally detailed and tracks the actual codebase state from Phase 0 onward, including what is implemented, what is validated, what is intentionally simplified, and what remains incomplete.

The project follows a strict layered pipeline: raw market data is normalized, aligned, consensus-checked, trust-scored, chained into a hash log, scored for anomaly/regime state, converted into strategy signals, risk-checked, and then eventually executed. The blueprint is phase-ordered, so this document follows that order and records the real checkpoint state rather than an aspirational one.

## Current checkpoint

What is fully implemented and validated today:

- Phase 0 scaffolding and repository structure.
- Phase 1 foundation stack: Kafka, ZooKeeper, Prometheus, Grafana, smoke tests.
- Phase 2 Layer 1 ingestion, TLS pinning, consensus, trust scoring, hash chaining, and validated-topic wiring.
- Phase 3 offline HMM training with joblib artifacts.
- Phase 4 Layer 2 anomaly scoring, regime inference, decision gate, and live Kafka wiring.
- Phase 5 backtesting scaffold plus deterministic replay, scenario injection, metrics, reporting, walk-forward execution, and permutation testing utilities.
- Phase 6 Layer 3 candle aggregation, indicators, OFI, dual-timeframe signal logic, sizing, service wiring, and tuning helpers.
- Phase 7 Layer 4 risk management with pre-execution checks, ATR stops/targets, circuit breaking, and backtest integration.

Implementation details worth keeping visible:

- Layer 1 now has five exchange adapters, but the primary-exchange path is still treated as the canonical source whenever a single exchange reference is needed downstream.
- Layer 2 is intentionally aligned to the current 2-state HMM artifact, not the older 3-state wording that still appears in parts of the blueprint.
- The backtest harness is deterministic and reproducible, but it still uses synthetic multi-source assumptions when replaying historical data.
- Layer 3 produces signals and sizing decisions, but the replay engine still does not consume live-style Layer 3 output end-to-end in the same way the final execution layer eventually will.
- Layer 4 is live in backtests and unit tests, but production-grade execution, durable risk/audit persistence, and order routing are still future work.

What is not yet implemented:

- Phase 8 execution engine.
- Phase 9 audit log persistence layer.
- Phase 10 blueprint-grade statistical validation closure.
- Phase 11 web interface.
- Phase 12 full integration/demo polish.

This document also captures known mismatches between the plan and the current code so they stay visible instead of being buried in comments.

## Repo map

The current implementation is spread across these main surfaces:

- `shared/`
  - `schemas.py`: Pydantic Kafka contracts (`RawTick`, `NormalizedTick`, `ValidatedTick`, `ScoredTick`, `ApprovedOrder`).
  - `audit.py`: structured audit-event emission helper.
  - `tls_pinning.py`: leaf-certificate fingerprint verification.
  - `metrics_http.py`: lightweight `/metrics` server.
- `config/`
  - `tls_pins.json`: exchange pin allowlist.
  - `trust_weights.json`: Layer 1 trust weights.
- `services/layer1_ingestion/`
  - exchange adapters, reconnect/backoff logic, Kafka publisher, soak runner.
- `services/layer1_consensus/`
  - window alignment and consensus/quarantine logic.
- `services/layer1_trust/`
  - T1–T5 trust math and weighted aggregation.
- `services/layer1_hashlog/`
  - append-only hash chain for validated windows.
- `services/layer1_validated/`
  - raw-topic consumer, primary-exchange routing, trust/hash output, validated-topic publisher, exchange liveness monitor.
- `services/hmm_training/`
  - historical download, realized-volatility features, HMM artifact training.
- `services/layer2_anomaly/`
  - rolling features, HMM regime inference, IF/HST fusion, MAD guard, decision gate, scored-topic publisher.
- `services/layer3_strategy/`
  - candle aggregation, indicator suite, OFI, signal logic, sizing, service wiring, bootstrap helpers, tuning helpers.
- `services/layer4_risk/`
  - pre-execution checks, ATR stop/target computation, circuit breaker, approved-order creation.
- `services/backtesting/`
  - deterministic replay harness, scenario injection, metrics, reports, walk-forward, permutation test, SQLite results.
- `services/metrics/`
  - sample FastAPI metrics service.
- `scripts/` and `artifacts/scripts/`
  - smoke tests, consumers, report helpers, tuning runners, validation runners, data fetchers.
- `tests/`
  - focused unit and integration tests for all implemented layers.

## Architecture summary

The pipeline is Kafka-first and strictly layered.

1. Live exchange adapters produce normalized raw ticks.
2. Layer 1 aligns them, detects divergence, computes trust, and emits validated ticks.
3. Layer 2 computes anomaly/regime/state and emits scored ticks.
4. Layer 3 aggregates candles, computes indicators, evaluates signals, and sizes positions.
5. Layer 4 evaluates pre-execution risk, assigns stops/targets, and approves or rejects orders.
6. Backtesting replays historical ticks through the live Layer 1 and Layer 2 code paths and records metrics and reports.

Design notes:

- The codebase prefers small, pure helpers for math-heavy logic and keeps service classes focused on wiring, IO, and state transitions.
- Most cross-layer contracts are Pydantic models in `shared/schemas.py`, so schema changes are visible quickly in both tests and runtime code.
- The system keeps canonical JSON hashing and stable serialization rules because the trust/hash chain depends on byte-for-byte reproducibility.
- Layer 2 and Layer 3 both expose internal state snapshots in their models so the tests can assert behavior without depending on Kafka consumers.
- The backtesting package mirrors the live layer boundaries so replay can reuse the same implementation surfaces rather than maintaining a parallel simulation stack.

The current limitation is that the backtest engine still does not consume real Layer 3 trade signals end-to-end in the same way a live trading session eventually should. It does, however, exercise the risk layer directly through the backtest harness and records the resulting metrics.

## Phase 0 — Project framing and scaffolding

Phase 0 is complete.

The repo has a coherent structure and a single source of truth for the blueprint. The active plan is in `plan.md`, the source blueprint is `trading_blueprint_final.docx.md`, and the implementation narrative is centered in this file.

The scaffold covers:

- shared schemas and utilities,
- service packages per layer,
- a testing layout,
- configuration files,
- monitoring config,
- and the Docker compose foundation.

## Phase 1 — Foundation stack

Phase 1 is complete and stable.

Implemented and working:

- ZooKeeper and Kafka in `docker-compose.yml`.
- Host and container Kafka listener paths.
- Prometheus scrape config in `ops/prometheus/prometheus.yml`.
- Grafana datasource provisioning in `ops/grafana/provisioning/datasources/datasource.yml`.
- `services/metrics/app/main.py` as a minimal FastAPI metrics sample.
- `scripts/kafka_smoke_test.py` for produce/consume and consumer-group validation.

The current stack reflects the blueprint’s basic operational goals, but the later phases still need the remaining container services and web frontend/backend.

Additional operational detail:

- The compose stack is already good enough for local integration work and smoke testing.
- Monitoring is present from the start, which keeps later service additions observable without retrofitting metrics plumbing.
- Kafka listener configuration distinguishes host access from container-to-container access, which matters on Windows and other local-dev setups.

## Phase 2 — Layer 1 data pipeline

Phase 2 is implemented and validated.

### 2.1 Exchange adapters

Implemented adapters live under `services/layer1_ingestion/adapters/`:

- Binance
- Coinbase
- Kraken
- OKX
- Bybit

Shared adapter behavior in `services/layer1_ingestion/adapters/base.py` includes:

- TLS pin verification before connect.
- Heartbeat / timeout detection.
- Exponential backoff reconnect logic.
- REST snapshot fetch on reconnect.
- Normalization into `NormalizedTick`.

Implementation note:

- Kraken deliberately marks `timestamp_source="receive"` because the feed does not provide a trustworthy exchange-side timestamp in the same way the others do.
- The raw publisher now serializes `RawTick` rather than the broader normalized type so downstream hashing and contract checking stay explicit.

### 2.2 TLS pinning

Implemented in `shared/tls_pinning.py` with config in `config/tls_pins.json`.

Behavior that is present:

- Fingerprint comparison against pinned SHA-256 values.
- Refusal on mismatch.
- Expiry warning when the cert is near expiration.
- Helper script for extracting fingerprints.

### 2.3 Raw Kafka topic

`market.ticks.raw` is implemented as the Layer 1 ingress topic.

The raw publisher uses a bounded queue and degrades by dropping oldest messages during Kafka outage pressure, which matches the plan’s general buffer requirement closely enough for the current checkpoint.

### 2.4 Consensus engine

Implemented in `services/layer1_consensus/engine.py`.

Current behavior:

- 50 ms alignment windows.
- Divergence tolerance around 0.3%.
- Quarantine of divergent sources.
- Re-evaluation of quarantined sources on subsequent windows.
- Escalation after repeated divergence.
- Volume-weighted median consensus on usable sources.

The aligner also carries last-known-value fill and staleness gating, which makes the active-source denominator more realistic when exchanges are temporarily silent.

Behavioral note:

- Used sources are sorted and de-duplicated before being carried forward, which makes the hash chain and validated output stable across equivalent input ordering.

### 2.5 Trust scorer

Implemented in `services/layer1_trust/scoring.py`.

The trust score is the weighted sum of:

- T1 TLS validity,
- T2 consensus agreement,
- T3 freshness decay,
- T4 sequence integrity,
- T5 hash-chain continuity.

The current implementation includes:

- config-driven weights from `config/trust_weights.json`,
- freshness half-life at 25 ms for T3,
- a time-decayed T2 helper over aligned ticks,
- sequence-gap handling,
- binary hash-chain continuity scoring.

Important nuance: the current code also preserves compatibility for missing sequence IDs by not penalizing the score when sequence information is unavailable.

This matters because some feeds do not expose sequence numbers consistently, and the pipeline is designed to degrade gracefully instead of treating missing metadata as a hard failure.

### 2.6 Hash chain

Implemented in `services/layer1_hashlog/hash_chain.py`.

The chain is append-only, asynchronously written, and verifiable. The chain hash uses canonical JSON over the required tick fields plus `previous_hash`.

The hash payload currently includes the primary exchange, the primary exchange mid, the consensus mid, the used/divergent source sets, and the trust score so the hash log carries enough context for integrity checks and audit reconstruction.

### 2.7 Validated-topic wiring

Implemented in `services/layer1_validated/service.py`.

What the service does:

- consumes raw ticks,
- records exchange liveness,
- aligns windows,
- runs consensus,
- requires the primary exchange to participate in the consensus set,
- computes trust subscores,
- appends the validated chain entry,
- publishes `ValidatedTick` to `market.ticks.validated`.

The validated schema carries the fields needed by later layers, including optional `volume_24h`, `spread`, and liveness metadata.

The service also keeps a per-exchange sequence-gap tracker for the primary exchange and treats missing primary participation as a skip condition rather than fabricating a consensus record.

## Phase 3 — Offline HMM training

Phase 3 is implemented and operational.

The training code lives under `services/hmm_training/` and currently uses a 2-state Gaussian HMM chosen from empirical separation on the available data. That is a deliberate implementation choice even though the blueprint’s prose discusses a 3-state regime model in places.

Implemented pieces:

- Binance Vision historical download and normalization.
- Realized-volatility feature construction.
- HMM training and model serialization with joblib.
- Metadata output with training parameters and regime summary.

Current artifact locations:

- `artifacts/hmm/model.pkl`
- `artifacts/hmm/metadata.json`

Training detail:

- The code records the chosen state count in metadata so the runtime classifier can validate that the loaded artifact matches the expected posterior shape.
- The 2-state choice is reflected in both the trainer defaults and the Layer 2 classifier, which avoids silent shape mismatches when the model loads.

## Phase 4 — Layer 2 anomaly detection

Phase 4 is implemented and live-validated.

Implemented in `services/layer2_anomaly/engine.py` and `services/layer2_anomaly/service.py`.

### Rolling features

The engine maintains rolling buffers for:

- log return,
- log volume,
- spread,
- realized volatility history.

### Regime inference

The HMM wrapper loads the offline model artifact and emits:

- regime label,
- posterior probability vector.

### Anomaly detection

The anomaly stack combines:

- Isolation Forest with background retraining and atomic model swap,
- Half-Space Trees with the correct score-before-learn order,
- weighted score fusion,
- regime-sensitive MAD guard,
- and a four-state decision gate with hysteresis.

Implementation detail:

- The service keeps polling Kafka rather than blocking forever on the consumer iterator so the watchdog can enforce a missing-data halt when no validated ticks arrive.
- The watchdog path is idempotent; once the service has forced HALT for silence, it does not emit repeated timeout events every poll cycle.

### Current implementation detail worth preserving

The Layer 2 code currently uses a 2-state HMM and regime-specific MAD multipliers `{4.0, 8.0}`. That is consistent with the current training artifact, but it should be remembered as an empirical implementation choice rather than a literal match to every line of the blueprint text.

### Kafka wiring

Layer 2 consumes `market.ticks.validated` and publishes `market.ticks.scored`.

### Validation status

Layer 2 has already been live-validated in Kafka integration, and the repo contains tests covering the rolling window, HMM bounds, IF retraining, HST ordering, MAD, and decision-gate behavior.

## Phase 5 — Backtesting engine

Phase 5 is materially implemented.

Implemented under `services/backtesting/`:

- deterministic time control,
- historical tick loader,
- synthetic multi-source generation,
- attack scenario injection hooks,
- live Layer 1 / Layer 2 simulation wrappers,
- metrics collection,
- SQLite results persistence,
- HTML report generation,
- walk-forward execution,
- permutation testing.

### What the backtest currently measures

The engine already records:

- gross P&L,
- net P&L,
- Sharpe ratio,
- max drawdown,
- win rate,
- latency proxy,
- NORMAL-state percentage,
- anomaly detection metrics,
- false positives,
- attack detection timing,
- permutation p-value.

The result bundle also persists equity curves, config snapshots, scoring events, and SQLite run records so runs can be inspected after the fact instead of only being printed to stdout.

### Current limitation

The backtest still uses Layer 2 system-state transitions as the trade trigger proxy in the core replay path. It does not yet consume actual Layer 3 `TradeSignal` objects end-to-end. That is the main reason Phase 5/6 validation should still be treated as incomplete from a blueprint-purity perspective.

Practical consequence:

- The backtest is good enough for verifying deterministic replay, anomaly response, and risk gating, but it is not yet the final proof that the live signal-to-execution chain is complete.

### Walk-forward and permutation testing

Implemented helper modules:

- `services/backtesting/walk_forward.py`
- `services/backtesting/permutation_test.py`

The walk-forward helper runs rolling windows over a historical slice and writes a summary artifact.

The permutation helper currently approximates blueprint significance testing by shuffling returns / equity deltas. That is useful and reproducible, but it is not yet the exact trade-entry-timestamp shuffle described in the blueprint.

The walk-forward helper writes a summary artifact for each run, which makes it easy to compare folds without rerunning the whole replay.

### Validation outputs already produced

The repo now contains real run artifacts under `artifacts/` for:

- historical data fetches,
- backtest reports,
- walk-forward summaries,
- tuning results,
- tuned threshold snapshots.

## Phase 6 — Layer 3 strategy engine

Phase 6 is implemented through the current checkpoint.

Implemented in `services/layer3_strategy/`:

- candle aggregation,
- indicator computation,
- order flow imbalance,
- dual-timeframe signal logic,
- position sizing,
- Kafka service wiring,
- bootstrap helpers,
- tuning helpers.

### Candle aggregation

`services/layer3_strategy/candles.py` builds 5m and 1h candles from `ScoredTick`.

Key behavior:

- OHLCV plus metadata.
- `avg_trust_score` and `max_anomaly_score` tracking.
- reliability rule based on trust/anomaly thresholds.
- discarding candles with fewer than 3 ticks.
- consecutive unreliable candle counting.
- `system_state_override="DEGRADED"` once the streak threshold is reached.

That override is carried in the candle model and used by strategy tests, but the service still has one remaining integration gap where it should more explicitly force the downstream decision path to respect the degraded candle state.

### Indicators

`services/layer3_strategy/indicators.py` computes from scratch:

- RSI,
- MACD,
- Bollinger Bands,
- EMA crossover,
- ATR.

### Order Flow Imbalance

`services/layer3_strategy/ofi.py` computes a rolling 50-tick OFI over signed volume, bounded to `[-1, 1]`.

### Signal logic

`services/layer3_strategy/signals.py` implements the pure dual-timeframe decision gate:

- system-state gate,
- primary 5m gate,
- mandatory OFI confirmation,
- higher-timeframe confluence check,
- signal-strength scoring.

### Position sizing

`services/layer3_strategy/sizing.py` applies the blueprint formula:

- base size,
- state multiplier,
- confluence multiplier,
- signal-strength multiplier.

### Service wiring

`services/layer3_strategy/service.py` consumes `market.ticks.scored`, maintains symbol state, feeds candles into indicators, evaluates signals, sizes them, and publishes trade signals.

The service intentionally keeps symbol-local state in memory, which makes the tests fast and deterministic, but it also means that a future production deployment will need explicit restart/recovery handling for warm state reconstruction.

### Bootstrap and tuning

Additional support files are present for:

- initial candle bootstrap via Binance REST,
- strategy tuning and backtest-driven parameter sweeps.

### Important remaining Layer 3 caveat

The candle-level `system_state_override` is carried by the candle model, but the service still evaluates signals using the upstream tick state rather than fully replacing it with the candle override at the decision point. That means the 50-unreliable-candle degradation rule is represented in the data model but not yet fully enforced in the strategy decision flow.

This is a real behavioral gap rather than a documentation gap, and it should stay visible until the execution path is tightened.

## Phase 6.8 — Tuning and validation artifacts

The tuning workflow now exists as a real artifact chain:

- tuning grid search,
- walk-forward runner,
- tuned-threshold snapshot save script,
- saved JSON artifacts under `artifacts/tuning/`.

The current checkpoint is enough to say Phase 6.8 is functionally present, but the tuning methodology is still not the final blueprint-grade strategy calibration pass because Layer 3 thresholds are not yet tuned through a direct signal-level harness.

## Phase 7 — Layer 4 risk management

Phase 7 is implemented and integrated into the backtest harness. The implementation follows the blueprint's acceptance criteria: the eight pre-execution checks, ATR-derived stops/targets, and a circuit-breaker state machine, plus backtest-level metrics and reporting so behavior is observable and testable.

Implemented artifacts and locations:

- Risk engine implementation: `services/layer4_risk/engine.py` — `Layer4RiskEngine` implements the configured pre-execution checks, circuit-breaker state machine, ATR-derived stop/take logic, and an in-memory risk state tracker used by the backtest harness.
- Package export: `services/layer4_risk/__init__.py` — convenience exports for the engine and types.
- ApprovedOrder contract: `shared/schemas.py` — added `ApprovedOrder` Pydantic model and fields (symbol, direction, size_pct, stop_loss_price, take_profit_price, atr, trust_score, circuit_breaker_state, portfolio_exposure_pct, snapshots, risk_adjustments, reason).
- Backtest wiring: `services/backtesting/engine.py` — instantiates `Layer4RiskEngine`, routes emitted `TradeSignal` objects through `evaluate_signal(...)`, and simulates fills for returned `ApprovedOrder` objects.
- Backtest metrics: `services/backtesting/metrics.py` — added `risk_approved_orders`, `risk_rejected_orders`, `risk_reduced_ticks`, `risk_halted_ticks` and included them in serialized metrics output.
- Tests: `tests/test_layer4_risk.py` (unit coverage for checks and circuit-breaker) and `tests/test_backtesting_phase5.py` (integration: backtest routes signals through Layer 4 and asserts risk metrics).

Features implemented:

- Eight pre-execution checks are applied in-order inside `Layer4RiskEngine.evaluate_signal`.
- ATR-based stops and targets are computed from the primary-timeframe ATR exposed inside the signal snapshot.
- Circuit breaker states are `NORMAL`, `REDUCED`, and `HALTED`.
- Backtest integration records approved versus rejected outcomes, updates risk metrics, and appends risk state and position size to equity rows for reporting.


## Phase 8 — Layer 5 execution (newly added)

Status: partially implemented and integrated into the backtest harness (May 2026).

What was added:
- `services/layer5_execution/engine.py` — `ExecutionEngine`, `OrderRecord`, `ExecutedOrder`. The engine accepts an approved-order mapping, delegates to an adapter, and records order/execution facts.
- `services/layer5_execution/adapters.py` — `SimulatedExecutionAdapter` including configurable `slippage_pct`, `fee_pct`, and `partial_fill_threshold` semantics; returns a deterministic `SimulatedFillResult` used in tests and backtests.
- `services/layer5_execution/__init__.py` — package export.
- `tests/test_layer5_execution.py` — unit tests for full fill and partial-fill behaviors, fees, and slippage.

Backtest integration:
- `services/backtesting/engine.py` now instantiates an `ExecutionEngine` (with the `SimulatedExecutionAdapter`) and submits `ApprovedOrder` objects returned by the risk engine to `ExecutionEngine.submit_order()`.
- The backtest uses executed fill price for position entry and close and applies `fee_paid` returned by the adapter to `net_cash` to track net P&L.

Notes and limitations:
- The execution layer in this checkpoint implements deterministic paper-trading simulation and basic fee handling. It intentionally does not yet implement the full blueprint order lifecycle (retry/backoff/dead-letter, durable idempotency, startup reconciliation). Those are planned next and remain critical for production-grade reconciliation and crash resilience.
- Tests for adapter behavior pass locally (`tests/test_layer5_execution.py`). The end-to-end backtest now records execution-level fields in the equity curve and metrics; this improves realism for Phase 10 validation work.

Next steps recommended (Phase 8 continuation):
- Implemented: idempotency store (`services/layer5_execution/persistence.py`) with WAL SQLite, deterministic `client_order_id` generation, persist-before-send behavior, retry/backoff with jitter, and dead-letter queueing.
- Implemented: startup reconciliation now queries adapter order status for pending WAL entries and resolves confirmed/filled orders without blind resubmission.
- Implemented: duplicate-order responses are treated as success when the adapter query reports a terminal order.
- Implemented: `SimulatedExecutionAdapter` now carries deterministic latency, per-exchange fee schedules, and configurable partial-fill behavior.
- Added unit and integration tests under `tests/test_layer5_execution_persistence.py` that verify retry-to-confirm, retry-to-dead-letter, duplicate-order handling, and crash-recover startup reconciliation.


How the engine behaves in practice:

- It rejects hold signals early and treats upstream HALT/DEGRADED states as hard gates, with CLOSE_ALL as the exception.
- It caps raw signal size, applies reduced-state throttling, and then rechecks per-trade loss against the ATR-derived stop distance.
- It only approves orders when the resulting exposure fits inside the portfolio cap and the ATR is present and usable.
- It keeps a short in-memory alert list so the backtest can surface why the circuit breaker changed state.

Validation and status:

- Targeted tests for the risk layer and the backtest integration passed in the most recent run.
- The combined targeted run reported 29 passing tests across the touched suites.
- CSV/equity and metrics outputs were updated and validated to include the new risk fields.

Caveats and scope notes:

- Execution Engine (Phase 8) is still pending. `ApprovedOrder` objects are produced by Layer 4, but no runtime execution consumer is implemented yet. The backtest harness simulates fills based on `ApprovedOrder` outputs.
- Risk alerts are currently captured in memory (`RiskState.alert_events`) and emitted to the backtest metrics; persistent alerting/audit-topic publication is a Phase 8/9 follow-up.
- The risk engine was implemented to be deterministic and testable inside the backtest; production wiring (Kafka topics, durable alerting, Prometheus metrics) can be added without changing the core logic.

## Observability

Prometheus metrics endpoints are present for the running Python services:

- `metrics-service` on `:9100/metrics`
- `layer1-ingestion` on `:9101/metrics`
- `layer1-validated` on `:9102/metrics`
- `layer2-anomaly` on `:9103/metrics`
- `layer3-strategy` on `:9104/metrics`

The services use the shared lightweight HTTP helper in `shared/metrics_http.py`.

This setup is intentionally simple: the goal at this stage is to prove each service exports something scrapeable, not to build the final dashboard taxonomy yet.

## Testing and verification

The repository has focused tests for the main failure-prone paths:

- exchange adapters,
- TLS pinning,
- consensus/quarantine,
- trust scoring,
- hash-chain integrity,
- Layer 2 anomaly scoring and decision gate,
- Layer 3 candles, indicators, OFI, signals, sizing, service wiring, and bootstrap,
- Layer 4 risk checks and backtest routing,
- backtest walk-forward and permutation helpers,
- scenario comparison and report rendering.

Current validation status from recent work:

- Layer 1 and Layer 2 core suites are green.
- Layer 3 test suite is present and covers the major strategy components.
- Layer 4 tests and the backtest integration test passed in the most recent targeted run.
- The workspace currently reports no syntax/type diagnostics for the touched areas from the latest targeted check.

The strongest recent signal is the targeted pytest run that covered Layer 4 plus the adjacent backtest and Layer 3 contract tests in one pass.

Most recent targeted verification command:

- `python -m pytest tests/test_layer4_risk.py tests/test_backtesting_phase5.py tests/test_layer3_signals.py tests/test_layer3_sizing.py tests/test_layer3_service.py -q`

## Known mismatches and caveats

These are the things that still need to be kept explicit so the implementation narrative stays honest.

1. The backtest engine does not yet trade on actual Layer 3 `TradeSignal` objects end-to-end in the same way a live deployment eventually should.
2. The permutation test is still an approximation of the blueprint’s exact timestamp-shuffle procedure.
3. The Layer 3 candle degradation override is modeled, but the service does not yet apply it at signal-evaluation time.
4. The HMM is implemented as 2-state in code, so any 3-state blueprint language should be treated as a design discussion point, not as the current runtime state.
5. Phases 8-12 are not implemented yet.

Additional known simplifications:

- The current report and tuning helpers are useful operational artifacts, but they still reflect the backtest-centric implementation phase rather than a fully productionized control plane.
- Some of the longer-form markdown files in `services/backtesting/` and `services/layer2_anomaly/` are specs and implementation notes rather than runtime code, which is intentional.

## How this file should be maintained

Treat this document as the live implementation ledger.

- Update it when a phase becomes runnable, validated, or structurally changed.
- Record both what exists and what remains missing.
- Keep the mismatch section current.
- Do not silently upgrade a phase description to “done” unless the code and tests actually support that claim.

## Next implementation priority

The next work should stay in strict blueprint order:

1. Phase 8 execution engine.
2. Phase 9 audit persistence and alert plumbing.
3. Phase 10 statistical validation closure.
4. Phase 11 web interface.
5. Phase 12 demo polish and integration hardening.

If the next turn stays in implementation mode, Phase 8 is the correct mechanical next step because it consumes the `ApprovedOrder` contract introduced by Phase 7.

That is the current truthful state of the project.

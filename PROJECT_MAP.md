<!-- Purpose: High-level map of the repository, what each folder does, and where key logic lives. -->
# Project Map — Secure Algo Trading Platform

This repo implements a blueprint-style, multi-layer pipeline for **trust-first market data** and downstream anomaly scoring.

At a high level:

- **Layer 1**: live exchange ticks → normalize → Kafka raw topic → align+consensus+trust → Kafka validated topic + hash-chain audit log
- **Layer 2**: validated ticks → rolling features + regime inference + anomaly models → scored ticks
- **Ops**: Docker Compose stack (Kafka + services + Prometheus + Grafana) + basic host scripts/tests

## Top level

- [trading_blueprint_final.docx.md](trading_blueprint_final.docx.md)
  - The source blueprint document this repo follows.
- [docker-compose.yml](docker-compose.yml)
  - Local stack: Kafka/ZooKeeper + Layer1/Layer2 services + Prometheus + Grafana.
- [README.md](README.md)
  - How to run the stack and basic consumers.
- [implementation_so_far.md](implementation_so_far.md)
  - Article-style description of what’s implemented (phases 1–4) and the dataflow.
- [plan.md](plan.md)
  - Step-by-step blueprint-aligned plan and acceptance criteria.
- [progress.md](progress.md)
  - Running log of what was completed and how it was verified.
- [requirements-dev.txt](requirements-dev.txt)
  - Host-side tooling deps (pytest, kafka-python, etc.).
- [requirements-ml.txt](requirements-ml.txt)
  - Offline ML deps (HMM training + later ML phases).
- [pytest.ini](pytest.ini)
  - Pytest configuration.

## Shared library (schemas + utilities)

Folder: [shared/](shared/)

- [shared/schemas.py](shared/schemas.py)
  - Canonical Pydantic message contracts used between services:
    - `NormalizedTick` (Layer 1 ingestion output)
    - `ValidatedTick` (Layer 1 validated output)
    - `ScoredTick` (Layer 2 anomaly output)
- [shared/audit.py](shared/audit.py)
  - Structured audit events (JSON lines) for important security/ops events.
- [shared/tls_pinning.py](shared/tls_pinning.py)
  - TLS leaf-certificate fingerprint verification (pins live in config).
- [shared/metrics_http.py](shared/metrics_http.py)
  - Lightweight `/metrics` HTTP server helper.
- [shared/jsonc.py](shared/jsonc.py)
  - JSON-with-comments helper (strips a header comment block before JSON parsing).

## Configuration

Folder: [config/](config/)

- [config/tls_pins.json](config/tls_pins.json)
  - Per-exchange TLS certificate pins (SHA-256 fingerprint allowlist).
- [config/trust_weights.json](config/trust_weights.json)
  - Weights for trust subscores T1..T5.

## Services

Folder: [services/](services/)

### Layer 1 — ingestion (exchange adapters → NormalizedTick → Kafka)

Folder: [services/layer1_ingestion/](services/layer1_ingestion/)

- [services/layer1_ingestion/run_console.py](services/layer1_ingestion/run_console.py)
  - Main entrypoint for running live adapters. Can print ticks and/or publish to Kafka.
- [services/layer1_ingestion/soak_runner.py](services/layer1_ingestion/soak_runner.py)
  - Long-running soak runner with periodic status (used to compare tick rates by exchange).
- [services/layer1_ingestion/kafka_publisher.py](services/layer1_ingestion/kafka_publisher.py)
  - Kafka publisher for `market.ticks.raw` with bounded outage buffering.
- [services/layer1_ingestion/adapters/](services/layer1_ingestion/adapters/)
  - WebSocket adapters:
  - [services/layer1_ingestion/adapters/base.py](services/layer1_ingestion/adapters/base.py) — shared reconnect/backoff/heartbeat + TLS pin checks
  - [services/layer1_ingestion/adapters/binance.py](services/layer1_ingestion/adapters/binance.py)
  - [services/layer1_ingestion/adapters/coinbase.py](services/layer1_ingestion/adapters/coinbase.py)
  - [services/layer1_ingestion/adapters/kraken.py](services/layer1_ingestion/adapters/kraken.py)

Outputs:
- Kafka topic: `market.ticks.raw`
- Message type: `NormalizedTick`

### Layer 1 — consensus (alignment + divergence/quarantine + consensus price)

Folder: [services/layer1_consensus/](services/layer1_consensus/)

- [services/layer1_consensus/engine.py](services/layer1_consensus/engine.py)
  - `TickAligner`: aligns ticks into short per-symbol windows (default 50ms)
  - `ConsensusEngine`: divergence detection (tolerance default 0.3%), quarantine + escalation, and consensus mid price (volume-weighted median)

This module is where the “tick-rate mismatch vs 50ms window” issue manifests, because slow exchanges often don’t produce a fresh tick inside a given 50ms window.

### Layer 1 — trust scoring (T1..T5)

Folder: [services/layer1_trust/](services/layer1_trust/)

- [services/layer1_trust/scoring.py](services/layer1_trust/scoring.py)
  - Defines subscores `T1..T5` and aggregates them into `trust_score` using weights from config.
  - Key constants:
    - T3 half-life is `25ms` (exponential decay).
    - T2 is `agreeing_sources / total_sources` (as provided).

### Layer 1 — hash log (hash-chain audit)

Folder: [services/layer1_hashlog/](services/layer1_hashlog/)

- [services/layer1_hashlog/hash_chain.py](services/layer1_hashlog/hash_chain.py)
  - Append-only hash chain for validated windows (tamper evidence / continuity checks).

### Layer 1 — validated service (raw → align → consensus → trust → hashlog → validated)

Folder: [services/layer1_validated/](services/layer1_validated/)

- [services/layer1_validated/service.py](services/layer1_validated/service.py)
  - Kafka consumer for `market.ticks.raw`
  - Uses `TickAligner` and `ConsensusEngine`
  - Computes trust via [services/layer1_trust/scoring.py](services/layer1_trust/scoring.py)
  - Appends hash-chain via [services/layer1_hashlog/hash_chain.py](services/layer1_hashlog/hash_chain.py)
  - Publishes `ValidatedTick` to `market.ticks.validated`
- [services/layer1_validated/kafka_json_publisher.py](services/layer1_validated/kafka_json_publisher.py)
  - Buffered JSON Kafka publisher helper.

### Layer 2 — anomaly service (validated → rolling features → anomaly + state)

Folder: [services/layer2_anomaly/](services/layer2_anomaly/)

- [services/layer2_anomaly/service.py](services/layer2_anomaly/service.py)
  - Kafka consumer for `market.ticks.validated` and producer for `market.ticks.scored`.
- [services/layer2_anomaly/engine.py](services/layer2_anomaly/engine.py)
  - Rolling feature window, regime inference, anomaly scoring, and the decision-gate / state-machine outputs.

### Offline HMM training (not a long-running service)

Folder: [services/hmm_training/](services/hmm_training/)

- [services/hmm_training/train.py](services/hmm_training/train.py)
  - Entrypoint: downloads historical data, builds features, trains a `GaussianHMM`, writes artifacts.
- [services/hmm_training/binance_vision.py](services/hmm_training/binance_vision.py)
  - Downloader/parser for Binance Vision historical klines.
- [services/hmm_training/features.py](services/hmm_training/features.py)
  - Feature engineering for offline training.

Artifacts output to:
- [artifacts/hmm/](artifacts/hmm/) (e.g., `model.pkl`, `metadata.json`)

### Metrics service (example FastAPI + Prometheus)

Folder: [services/metrics/](services/metrics/)

- [services/metrics/app/main.py](services/metrics/app/main.py)
  - Simple FastAPI app exposing `/metrics` and a root endpoint.

## Scripts (host-side tools)

Folder: [scripts/](scripts/)

- [scripts/kafka_smoke_test.py](scripts/kafka_smoke_test.py)
  - Produce/consume sanity test for Kafka connectivity + consumer-group semantics.
- [scripts/consume_market_ticks_raw.py](scripts/consume_market_ticks_raw.py)
  - Debug consumer for `market.ticks.raw`.
- [scripts/consume_market_ticks_validated.py](scripts/consume_market_ticks_validated.py)
  - Debug consumer for `market.ticks.validated`.
- [scripts/consume_market_ticks_scored.py](scripts/consume_market_ticks_scored.py)
  - Debug consumer for `market.ticks.scored`.
- [scripts/print_tls_fingerprint.py](scripts/print_tls_fingerprint.py)
  - Helper to fetch and print TLS leaf certificate SHA-256 fingerprints (for pinning).
- [scripts/trace_layer1_e2e.py](scripts/trace_layer1_e2e.py)
  - Correlation/trace harness: consumes raw ticks, replays alignment/consensus/trust, and tries to match against validated ticks.

## Tests

Folder: [tests/](tests/)

- [tests/test_layer1_adapters.py](tests/test_layer1_adapters.py)
  - Exchange message parsing and normalization.
- [tests/test_tls_pinning.py](tests/test_tls_pinning.py)
  - Pinning mismatch refusal / config parsing.
- [tests/test_layer1_consensus.py](tests/test_layer1_consensus.py)
  - Divergence tolerance, quarantine, escalation.
- [tests/test_layer1_trust_scoring.py](tests/test_layer1_trust_scoring.py)
  - T1..T5 and trust aggregation.
- [tests/test_layer1_hash_chain.py](tests/test_layer1_hash_chain.py)
  - Hash-chain continuity and corruption detection.
- [tests/test_layer1_t2_lkv_fix.py](tests/test_layer1_t2_lkv_fix.py)
  - A proposed/future test suite for an LKV (last-known-value) alignment + T2 denominator change.

## Ops (monitoring)

Folder: [ops/](ops/)

- [ops/prometheus/prometheus.yml](ops/prometheus/prometheus.yml)
  - Prometheus scrape configuration.
- [ops/grafana/provisioning/datasources/datasource.yml](ops/grafana/provisioning/datasources/datasource.yml)
  - Grafana provisioning for Prometheus datasource.

## Artifacts (generated outputs)

Folder: [artifacts/](artifacts/)

- [artifacts/reports/](artifacts/reports/)
  - Saved Layer 1 verification reports (Markdown snapshots).
- [artifacts/traces/](artifacts/traces/)
  - Trace outputs captured by the Layer 1 trace harness.
- [artifacts/hmm/](artifacts/hmm/)
  - Trained HMM model + metadata.

## Where the “Layer 1 trust ~0.6” issue lives

If you’re explaining the problem to other models, the relevant hot spots are:

- Alignment/windowing: [services/layer1_consensus/engine.py](services/layer1_consensus/engine.py)
- T2/T3 trust math: [services/layer1_trust/scoring.py](services/layer1_trust/scoring.py)
- End-to-end wiring: [services/layer1_validated/service.py](services/layer1_validated/service.py)
- Evidence snapshots: [artifacts/reports/](artifacts/reports/)

In practice, Binance produces ticks much faster than Coinbase/Kraken. With strict 50ms windows, many windows contain only Binance, so `agreeing_sources=1` while `total_sources=3` → `T2=1/3`, pulling the overall trust score down even when the system is otherwise healthy.

<!-- Purpose: Running progress log compared against plan.md and the blueprint. -->
# Progress Report

This file is the running implementation log, written so it can be compared directly against the execution plan in `plan.md` (Copilot memory artifact) and the blueprint in `trading_blueprint_final.docx.md`.

Conventions:

- Each entry maps to a **Phase/DoD block** in the plan (treated as one “set of todos”).
- Each entry includes: what was completed, evidence/verification, and what’s next.

---

## 2026-04-10 — Phase 1 complete: Docker + Kafka + Monitoring foundation

**Plan mapping**

- `plan.md` → “Phase 1 — Foundation: Docker + docker-compose + Kafka”

**Completed**

- Added docker-compose stack with:
  - ZooKeeper + Kafka (dual listeners for intra-compose + host access)
  - Prometheus + Grafana
  - `metrics-service` exposing `/metrics` using `prometheus-client`
- Added Prometheus scrape config targeting `metrics-service:9100/metrics`.
- Added Grafana provisioning for a Prometheus datasource.
- Added host-side Kafka smoke test script verifying:
  - Produce/consume round-trip
  - Consumer-group semantics (same group splits, different groups each see all)

**Verification / Evidence**

- `docker compose ps` shows all services **Up** and Kafka **healthy**.
- Kafka smoke test output: `Smoke test OK`.
- Prometheus targets query shows scrape health `up` for `http://metrics-service:9100/metrics`.

**Notes / Decisions**

- ZooKeeper host port is mapped to `22181` (container still uses `2181`) to avoid local port conflicts.
- Kafka host bootstrap is `localhost:29092` (container-to-container uses `kafka:9092`).

**Next set (Phase 2, per plan order — NOT started yet)**

- Implement Layer 1 exchange adapters console-only first (Binance → Coinbase → Kraken), with reconnection + heartbeat behavior, before introducing Kafka publishing.

---

## 2026-04-10 — Phase 2.1 in progress: Layer 1 adapters (console-only)

**Plan mapping**

- `plan.md` → “Phase 2 — Data Pipeline (Layer 1) → 2.1 Exchange adapters (console-only first; no Kafka)”

**Completed in this increment**

- Added shared `NormalizedTick` schema and a temporary console audit emitter.
- Implemented WebSocket adapters with:
  - Exponential backoff reconnect (1s → 30s max)
  - 5-second heartbeat timeout (no messages → reconnect)
  - REST snapshot fetch on reconnect (best-effort; failures emit audit event)
- Added console runner to print normalized ticks (`python -m services.layer1_ingestion.run_console`).
- Added unit tests for parsing sample messages (Binance combined stream wrapper, Coinbase ticker, Kraken ticker).

**Verification / Evidence**

- `pytest` parsing tests: 3 passed.
- Short live run (Binance only) printed continuous normalized ticks to console.
- Automated soak runner exists: `python -m services.layer1_ingestion.soak_runner`.
- Full DoD soak (30 minutes) started with:
  - `DURATION_S=1800`, `SYMBOLS=BTC-USDT,ETH-USDT`, `STATUS_INTERVAL_S=60`, `STALE_THRESHOLD_S=120`

**Remaining for Phase 2.1 DoD (not yet complete)**

- Run all 3 feeds (Binance + Coinbase + Kraken) for 30 minutes with stable reconnect behavior and clean normalized output.

**DoD verification (completed)**

- 30-minute soak completed successfully.
- Log: `logs/layer1_soak_20260410_144554.log`
- Final counts:
  - binance: 3594 ticks
  - coinbase: 362 ticks
  - kraken: 237 ticks
- Result: `SOAK_RESULT OK`

---

## 2026-04-10 — Phase 2.2 complete: TLS certificate pinning

**Plan mapping**

- `plan.md` → “Phase 2 — Data Pipeline (Layer 1) → 2.2 TLS certificate pinning (for each exchange)”

**Completed**

- Implemented TLS leaf-certificate SHA-256 fingerprint pinning utilities.
- Added version-controlled pins file and a script to print current fingerprints.
- Wired pin verification into adapters before any WebSocket connection is established.
- Added non-fatal expiry warning audit event when a cert is within 30 days of expiry.

**Verification / Evidence**

- Unit test confirms mismatched fingerprint is refused.
- Live run after populating pins successfully streamed ticks (pinning check passed).

**Files**

- Pins: `config/tls_pins.json`
- Implementation: `shared/tls_pinning.py`
- Fingerprint helper: `python -m scripts.print_tls_fingerprint <host> <port>`
- Test: `tests/test_tls_pinning.py`

**Notes / Risk**

- Exchange certificates rotate; when they do, pinning will fail hard by design until `config/tls_pins.json` is updated via a controlled process.

---

## 2026-04-10 — Phase 2.3 complete: Kafka integration for raw ticks

**Plan mapping**

- `plan.md` → “Phase 2 — Data Pipeline (Layer 1) → 2.3 Kafka integration for raw ticks”

**Completed**

- Implemented a Layer 1 Kafka publisher that writes RawTick events to `market.ticks.raw`.
- Wired publishing into the existing console runner behind an env flag so default behavior stays console-only.
- Implemented Kafka unavailability handling per blueprint (bounded in-memory buffer, drop-oldest, critical audit event).
- Added a simple debug consumer script to verify the topic is readable from the host.

**Verification / Evidence**

- `pytest`: 4 passed.
- Kafka consume-back check succeeded: `market.ticks.raw` produced and then consumed 1 RawTick message (synthetic publish).

**How to run**

- Consumer: `python scripts/consume_market_ticks_raw.py`
- Producer: set `PUBLISH_RAW_TO_KAFKA=1` and run `python -m services.layer1_ingestion.run_console`

**Files**

- Publisher: `services/layer1_ingestion/kafka_publisher.py`
- Consumer: `scripts/consume_market_ticks_raw.py`

**Next set (per plan order)**

- Phase 2.4+ (consensus engine / trust scorer / hash chain) after RawTick publishing is stable against live feeds.

---

## 2026-04-10 — Phase 2.4 complete: Consensus engine

**Plan mapping**

- `plan.md` → “Phase 2 — Data Pipeline (Layer 1) → 2.4 Consensus engine”

**Completed**

- Implemented volume-weighted median consensus on `NormalizedTick.mid` (weights = `volume_24h`).
- Implemented divergence tolerance quarantine (0.3%) with:
  - Quarantine buffer (divergent sources excluded from consensus until they re-enter tolerance)
  - Re-evaluation on each subsequent aligned window
  - Escalation after 3 consecutive divergences from the same exchange
- Implemented a 50ms tick alignment helper (per-symbol window) to build near-simultaneous per-exchange observations.

**Verification / Evidence**

- `pytest`: 7 passed
- Unit tests cover:
  - Single outlier quarantined; consensus stays between the non-divergent sources
  - Quarantined source is released once it comes back within tolerance
  - 3-strike divergence escalation triggers as specified

**Files**

- Engine: `services/layer1_consensus/engine.py`
- Tests: `tests/test_layer1_consensus.py`

**Next set (per plan order)**

- Phase 2.5 Trust scorer (T1–T5 subscores + configurable weights + unit tests)

---

## 2026-04-10 — Phase 2.5 complete: Trust scorer (math + configurable weights)

**Plan mapping**

- `plan.md` → “Phase 2 — Data Pipeline (Layer 1) → 2.5 Trust scorer”

**Completed**

- Implemented T1–T5 subscores per blueprint:
  - T1 TLS validity (binary)
  - T2 consensus agreement = agreeing_sources / total_sources
  - T3 freshness = exp(-lambda * latency_ms), with half-life 25ms
  - T4 sequence integrity (gap penalty; 0 if gap>=10)
  - T5 hash-chain continuity (binary)
- Implemented weighted linear trust score with weights loaded from a version-controlled JSON config (no hardcoding).

**Verification / Evidence**

- `pytest`: 11 passed
- Unit tests validate:
  - T3 half-life behavior (25ms => 0.5, 50ms => 0.25)
  - T4 gap penalty mapping
  - Combined trust score matches a hand-computed example

**Files**

- Implementation: `services/layer1_trust/scoring.py`
- Weights config: `config/trust_weights.json`
- Tests: `tests/test_layer1_trust_scoring.py`

**Next set (per plan order)**

- Phase 2.6 internal tick hash log (canonical JSON hashing + integrity checker)

---

## 2026-04-10 — Phase 2.6 complete: Internal tick hash log (hash chain)

**Plan mapping**

- `plan.md` → “Phase 2 — Data Pipeline (Layer 1) → 2.6 Internal tick hash log (Layer 1)”

**Completed**

- Implemented canonical JSON hashing + SHA-256 tick hash computation per blueprint inputs:
  - Hash input fields: `{symbol, consensus_mid, trust_score, received_timestamp_ms, previous_hash}`
  - Canonical JSON: UTF-8, sorted keys, no whitespace
- Implemented an async JSONL writer with an in-memory queue.
- Implemented an integrity checker that validates:
  - `previous_hash` continuity
  - recomputed hash matches stored `tick_hash`

**Verification / Evidence**

- `pytest`: 12 passed
- Unit test deliberately corrupts an entry and the checker detects a `tick_hash mismatch`.

**Files**

- Implementation: `services/layer1_hashlog/hash_chain.py`
- Tests: `tests/test_layer1_hash_chain.py`

**Next set (per plan order)**

- Phase 2.7 wiring + validated topic (`market.ticks.validated` populated with ValidatedTick incl. `tick_hash`)

---

## 2026-04-10 — Phase 2.7 complete: Wiring + validated topic

**Plan mapping**

- `plan.md` → “Phase 2 — Data Pipeline (Layer 1) → 2.7 Wiring + validated topic”

**Completed**

- Implemented Layer 1 validated pipeline that:
  - Consumes `market.ticks.raw`
  - Aligns ticks (50ms window)
  - Runs consensus + divergence quarantine
  - Computes trust score (config-driven weights)
  - Appends to the internal hash chain and emits `tick_hash`
  - Publishes `ValidatedTick` to `market.ticks.validated`
- Added a debug consumer script for `market.ticks.validated`.

**Verification / Evidence**

- `pytest`: 12 passed
- End-to-end sanity check: produced synthetic raw ticks and consumed a `ValidatedTick` from `market.ticks.validated` with fields:
  - `symbol`, `mid_price`, `trust_score`, `sub_scores`, `divergent_sources`, `timestamp_utc`, `tick_hash`

**Files**

- Service: `services/layer1_validated/service.py`
- Publisher helper: `services/layer1_validated/kafka_json_publisher.py`
- Schema: `shared/schemas.py` (`ValidatedTick`)
- Debug consumer: `scripts/consume_market_ticks_validated.py`

**How to run**

- See `README.md` → Phase 2.7 section

**Next set (per plan order)**

- Phase 3 HMM training (offline) or Phase 4 Layer 2 anomaly detection (after confirming Layer 1 trust distribution on a 30-minute live run)

---

## 2026-04-10 — Phase 3 complete: HMM training (offline)

**Plan mapping**

- `plan.md` → “Phase 3 — HMM training (offline, parallel with Phase 2)”

**Completed in this increment**

- Added an offline training module that:
  - Downloads Binance Vision daily 1m klines (cached under `data/binance_vision/`)
  - Computes 30-minute realized volatility
  - Trains a 3-state `GaussianHMM` (via `hmmlearn`) and saves artifacts
- Added ML requirements file.

**Environment**

- Installed ML deps into `.venv` from `requirements-ml.txt` (numpy + hmmlearn).

**Files**

- Downloader: `services/hmm_training/binance_vision.py`
- Features: `services/hmm_training/features.py`
- Trainer: `services/hmm_training/train.py`
- Deps: `requirements-ml.txt`

**Verification / Evidence (DoD)**

- Training run (90 days, BTCUSDT+ETHUSDT) completed successfully.
- Artifacts written:
  - `artifacts/hmm/model.pkl`
  - `artifacts/hmm/metadata.json`
- Metadata sanity check:
  - `points`: 8640 (= 90 days × 48 buckets/day × 2 symbols)

**Notes**

- Binance Vision daily files can lag for “today”; training defaults `--end-date` to yesterday and skips missing (404) days.
- Binance Vision timestamps were normalized to milliseconds to ensure 30-minute bucketing works correctly.

---

## 2026-04-10 — Observability compliance: per-service `/metrics` + containerized Layer 1 services

**Plan / blueprint mapping**

- Blueprint requirement: each Python service exposes a `/metrics` endpoint.
- (Operational improvement) Runs long-lived Layer 1 services in `docker-compose` so Prometheus can scrape them via Docker DNS.

**Completed**

- Added a minimal shared metrics HTTP server (`/metrics`) based on `prometheus-client`.
- Exposed `/metrics` from:
  - `layer1-ingestion` (tick counters, publish counters)
  - `layer1-validated` (raw/bad tick counters, window/publish counters, last trust gauge)
- Containerized both services and added them to `docker-compose.yml`:
  - `layer1-ingestion` publishes to Kafka inside Compose (`kafka:9092`)
  - `layer1-validated` consumes raw + publishes validated inside Compose
- Updated Prometheus scrape config to scrape all three jobs:
  - `metrics-service`, `layer1-ingestion`, `layer1-validated`

**Verification / Evidence**

- `docker compose ps` shows `layer1-ingestion` and `layer1-validated` containers **Up**.
- Host curl checks confirm endpoints respond:
  - `http://localhost:9101/metrics` includes `layer1_ingestion_ticks_total`
  - `http://localhost:9102/metrics` includes `layer1_validated_raw_ticks_total`
- Prometheus targets API shows all three scrape jobs `health: up`.

**Notes**

- Prometheus required a container restart to pick up the updated `ops/prometheus/prometheus.yml`.

---

## 2026-04-10 — Phase 4 complete: Layer 2 anomaly detection (scoring + decision gate)

**Plan / blueprint mapping**

- `trading_blueprint_final.docx.md` → “4. Layer 2 — Market Anomaly Detection”

**Completed**

- Implemented `layer2-anomaly` service that consumes `market.ticks.validated`, computes:
  - HMM regime + posterior from `artifacts/hmm/model.pkl` (joblib)
  - MAD guard on raw log-return with regime-dependent k (3/5/8)
  - Isolation Forest score (periodic retrain with atomic swap)
  - Half-Space Trees score (score-then-learn ordering)
  - Weighted fusion into `anomaly_score` in [0,1]
- Implemented the Layer 2 decision gate with hysteresis and the 2D trust/anomaly state matrix.
- Added `ScoredTick` output schema and wired publication to Kafka topic `market.ticks.scored`.
- Added per-service `/metrics` for Layer 2 and added Prometheus scrape job `layer2-anomaly`.
- Rebuilt and restarted `layer1-validated` so `ValidatedTick` can populate optional `spread` and `volume_24h` fields used for Layer 2 feature construction.

**Verification / Evidence**

- `docker compose ps` shows `layer2-anomaly` container **Up** with `9103:9103` exposed.
- Host check: `http://localhost:9103/metrics` returns 200 and includes:
  - `layer2_raw_in_total`
  - `layer2_scored_out_total`
- Prometheus targets API shows job `layer2-anomaly` with `health: up`.
- Kafka CLI consume check returns valid JSON `ScoredTick` messages from `market.ticks.scored`.

**Notes**

- Prometheus requires a container restart to pick up scrape config changes.




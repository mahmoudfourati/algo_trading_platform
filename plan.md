<!-- Purpose: Blueprint-aligned implementation plan and acceptance criteria. -->
## Plan: Secure Algo Trading Platform (Blueprint-Compliant)

Build the platform strictly in Claude’s phase order, using the blueprint’s layer contracts, Kafka topic boundaries, and required validation methodology as acceptance criteria. The core principle is depth-before-breadth: each phase must be runnable and testable end-to-end before starting the next.

**Cross-cutting blueprint requirements (apply to every phase/service)**
- Kafka unavailability handling: each service buffers up to 1000 outgoing messages; on recovery flush in order; if overflow drop oldest and emit a critical alert/audit event.
- Metrics: every Python service exposes a Prometheus /metrics endpoint; Prometheus + Grafana run in docker-compose (dashboards can be added later, but endpoints must exist).
- Audit events: all significant events (connect/reconnect, divergence quarantine, state changes, model swaps, order retries, verifier failures) also publish to the audit.events topic.
- Config + reproducibility: every backtest/validation run saves an immutable config snapshot (weights/thresholds/model params) alongside results.
- Deployment isolation: only the execution service needs outbound internet access; other services should run on the internal Docker network only.


**Steps**
1. Phase 0 — Project framing + repo scaffolding (1 day, blocks Phase 1)
   - Align on: paper-trading only; symbols BTC-USDT + ETH-USDT; timeframes 5m + 1h; single Kafka broker (academic scope).
   - Create a monorepo layout with: shared Python package for schemas/utils; one service package per layer; a web package; backtest package; tests.
   - Define canonical message serialization conventions now (JSON, UTF-8, stable key ordering) because hash-chaining depends on it.
   - Define a uniform config approach (env vars + validated config objects) so weights/thresholds are never hardcoded.
   - Create a traceability checklist that maps every blueprint subsection and numbered procedure item to a concrete task + test (so we can prove nothing was missed).

   - Definition of Done (DoD): repo installs in a fresh venv; a trivial “hello service” container builds; basic lint/test command runs.

2. Phase 1 — Foundation: Docker + docker-compose + Kafka (blocks all runtime layers)
   - Bring up Zookeeper + Kafka via docker-compose with correct advertised listeners for: (a) intra-compose communication and (b) host-to-broker access.
   - Add Prometheus + Grafana containers to docker-compose now (even with minimal dashboards initially).
   - Add a basic Prometheus scrape config that targets each service’s /metrics endpoint (services can be added incrementally as they exist).

   - Create a repeatable smoke test:
     - Create topic, produce one message, consume it back.
     - Verify consumer-group semantics (two consumers in same group split messages; two groups each see all messages).
   - Decide topic retention and partitions early (single partition per topic is OK for the project; document limitation).
   - Add a “local dev runbook” section: how to start/stop stack, reset volumes, and inspect broker logs.
   - DoD: Kafka stack stays healthy for 30 minutes; test producer/consumer works from both host and containers.


3. Phase 2 — Data Pipeline (Layer 1), internal order exactly as specified (blocks Phase 4)
   - 2.1 Exchange adapters (console-only first; no Kafka)
     - Implement Binance WebSocket adapter first:
       - Connect/reconnect with exponential backoff.
       - 5-second heartbeat timeout triggers reconnect.
       - On reconnect, fetch a REST order book snapshot before resuming ticks (prevents stale mid-prices).
       - Emit audit events on connect/reconnect/heartbeat timeouts.
       - Parse raw messages and normalize to NormalizedTick.
       - Print normalized ticks to console.
     - Add Coinbase adapter next, then Kraken.
     - Add schema validation + normalization tests per exchange using captured sample messages.
     - Add sequence ID tracking per exchange per symbol; unit test gaps and non-monotonic IDs.
     - DoD: all 3 feeds run for 30 minutes with stable reconnection and clean normalized output.
 
   - 2.2 TLS certificate pinning (for each exchange)
     - Implement fingerprint extraction workflow and store expected SHA-256 fingerprints as config.
     - Unit test: wrong fingerprint causes hard refusal.
     - Add expiry warning logic (<=30 days).
     - DoD: connections succeed only when fingerprint matches; refusal path is tested.

   - 2.2b Certificate rotation resilience (pin-set + signed updates) — optional hardening that preserves pinning security
     - Goal: prevent planned certificate rotations from causing adapter downtime or cascading trust/state degradation, while staying blueprint-compliant (“controlled deployment process only”).
     - Pin-set (dual-pin) support:
       - Extend the pin config format to allow an allowlist of SHA-256 fingerprints per exchange (e.g., current + next).
       - Verification rule stays strict: connection is allowed only if the presented leaf fingerprint matches any pinned value; otherwise hard refusal + critical audit event.
       - Explicit non-goal: never “learn” or auto-accept a new fingerprint from the live network path (no TOFU), to avoid MITM-induced re-pinning.
     - Operator workflow (controlled deployment):
       - When expiry warning triggers, obtain the upcoming fingerprint via a trusted process, stage it as the “next” fingerprint, and deploy before the exchange cutover; remove the old fingerprint after a safe overlap window.
     - Signed pin bundle (controlled “fast update” without code change):
       - Support loading pins from a versioned bundle file plus detached signature; verify signature against a pinned public key committed with the code.
       - Optional hot-reload on interval: apply only if signature valid and bundle version is monotonic (reject rollback/replay).
       - Keep the runtime update source restricted (local bind-mount / internal artifact), not fetched from arbitrary external URLs.
     - Auditing + metrics:
       - Emit audit events for: expiry warning, pin mismatch refusal, bundle load success/failure, and bundle update applied.
       - Add counters for mismatch events and bundle-update events.
     - Tests:
       - Multi-pin acceptance: any fingerprint in the allowlist passes.
       - Strict refusal: fingerprints outside the allowlist still fail.
       - Signed bundle verification: invalid signature is rejected; rollback/replay is rejected.
     - DoD: a simulated cert rotation (current→next) does not interrupt ingestion; pinning remains strict (no auto-trust of network-provided certs).


   - 2.3 Kafka integration for raw ticks
     - Only after console adapters are stable: add Kafka producer and publish one RawTick stream per exchange to market.ticks.raw.
     - DoD: raw ticks are visible on market.ticks.raw and can be consumed by a simple debug consumer.

   - 2.4 Consensus engine
     - Implement volume-weighted median consensus.
     - Implement divergence tolerance (0.3%) quarantine + consecutive divergence escalation.
     - Align cross-exchange ticks using a small aggregation window (target 50ms) so consensus uses near-simultaneous observations per symbol.
     - Quarantine behavior: divergent sources are buffered and re-evaluated on the next tick; escalate after 3 consecutive divergences from the same source.
     - Unit tests: single outlier gets quarantined; consensus follows other two; consecutive divergence escalates.
     - DoD: given synthetic multi-source ticks, consensus + quarantine behaves as specified.

   - 2.5 Trust scorer
     - Implement T1–T5 subscores exactly (T3 decay with half-life 25ms; T4 gap penalty; T2 agreeing_sources/total_sources; T5 chain continuity).
     - Ensure weights are config parameters and can be swapped without code change.
     - Unit test each subscore in isolation, then combined score against hand-computed examples.
     - DoD: combined trust_score matches expected results on a fixed fixture set.

   - 2.6 Internal tick hash log (Layer 1)
     - Implement canonical JSON hashing for the tick chain.
     - Match blueprint hashing inputs: SHA-256 over canonical JSON of {symbol, consensus_mid, trust_score, received_timestamp_ms, previous_hash} with sorted keys and no whitespace.
     - Implement async write path and integrity checker for deliberate corruption.
     - DoD: corruption is detected; chain tip continuity yields correct T5 inputs.

   - 2.7 Wiring + validated topic
     - Wire adapters → raw topic → consensus → trust scorer → validated topic.
     - Run live for 30 minutes; inspect trust distribution (expected: most ticks >0.8).
     - DoD: market.ticks.validated is populated with ValidatedTick (trust + subscores + tick_hash).

4. Phase 3 — HMM training (offline, parallel with Phase 2)
   - Download 90 days of BTC-USDT and ETH-USDT historical data (from data.binance.vision or equivalent published source).
   - Compute 30-minute realized volatility series.
   - Train GaussianHMM (3 states), validate interpretability (state means are ordered and separated).
   - Serialize the model artifact and a small metadata file (training date range, symbols, feature definition).
   - DoD: running the training script produces a loadable model and a plot/table showing 3 interpretable regimes.

5. Phase 4 — Anomaly Detection (Layer 2), internal order exactly as specified (blocks Phase 5 runtime)
   - 4.1 Rolling statistics engine
     - Implement Welford mean/std for log returns.
     - Implement rolling MAD (median absolute deviation) over the 500-tick buffer.
     - Implement realized volatility over the last 30-minute slice.
     - Unit tests using synthetic sequences (constant price, jump, drift).
     - DoD: stats outputs match hand calculations.

   - 4.2 Live regime inference with HMM
     - Load serialized HMM model at startup.
     - On each tick, infer regime label + posterior probabilities.
     - DoD: regime output is stable on normal data and responds to volatility changes.

   - 4.3 Feature vector construction
     - Compute features f1–f6 as specified, including time-of-day sin/cos.
     - Ensure z-scoring uses rolling stats, and that IF and HST use identical feature construction.
     - Unit tests: each feature matches expected values on fixtures.
     - DoD: feature builder is deterministic and versioned.

   - 4.4 Isolation Forest (batch, periodic retrain)
     - Train at startup on historical data; retrain every 15 minutes.
     - Match blueprint defaults: n_estimators=100, contamination=0.01, max_samples=256 (all configurable).
     - Implement IF score normalization exactly: IF_score = clip(1.0 - (decision_function_output + 0.5), 0.0, 1.0).
     - Implement atomic model swap so scoring never sees a partially-trained model.
     - Add synthetic corrupted tick tests for detection behavior.
     - DoD: retrain loop runs without blocking scoring; model swap verified.

   - 4.5 Half-Space Trees (streaming)
     - Match blueprint defaults: n_trees=25, height=15, window_size=250, seed=42 (configurable).
     - Implement scoring order correctly: score first, then learn.
     - Unit test ensures order is not accidentally reversed.
     - DoD: HST scores respond to injected anomalies.

   - 4.6 Score fusion + MAD guard
     - Implement weighted fusion (configurable weights).
     - Match blueprint defaults: A_combined = 0.45*IF_score + 0.55*HST_score (weights configurable).
     - Implement regime-dependent MAD thresholding and guard floor at 0.65.
     - DoD: MAD guard triggers on extreme returns as specified.

   - 4.7 Decision gate state machine with hysteresis
     - Match blueprint thresholds/state matrix: trust>=0.60 and anomaly<0.55 => NORMAL; trust>=0.60 and anomaly>=0.55 => CONSERVATIVE; trust<0.60 and anomaly<0.55 => DEGRADED; trust<0.60 and anomaly>=0.55 => HALT.
     - Implement 2D trust/anomaly matrix → system_state.
     - Implement dwell counter: upgrades require 10 consecutive qualifying ticks; downgrades to HALT are instantaneous.
     - Add missing-data watchdog: if no valid consensus tick received for a configurable timeout (default 30s), force HALT and emit a critical alert/audit event; require dwell condition to recover.
     - Unit test all transitions and hysteresis edge cases.
     - DoD: state machine passes transition test suite.

   - 4.8 Kafka wiring
     - Consume market.ticks.validated; publish market.ticks.scored.
     - DoD: live Layer 2 produces ScoredTick end-to-end.

6. Phase 5 — Backtesting engine (build now; blocks parameter tuning for Phase 6/7)
   - Build a replay harness that feeds historical ticks through the exact same code paths as live for Layers 1 and 2.
   - Implement deterministic time control (no wall-clock dependencies) so results are reproducible.
   - Implement synthetic multi-source simulation for T2 during backtest (document optimism explicitly).
   - Add hooks for synthetic attack injection scenarios.
   - Implement transaction cost accounting using Binance fee assumption 0.1% per trade; output both gross and net P&L.
   - Ensure backtest outputs the blueprint’s required metrics set (Sharpe, max drawdown, win rate, anomaly detection rate, false positive rate, end-to-end latency proxy, NORMAL-state %, permutation p-value when available).
   - DoD: one command runs a backtest slice and outputs a metrics JSON + equity curve.

7. Phase 6 — Strategy engine (Layer 3), internal order exactly as specified
   - 6.1 Candle aggregation (5m and 1h) from ScoredTick
     - Implement OHLCV + metadata schema and reliability rule (avg_trust <0.5 or max_anomaly >0.7).
     - Discard candles with <3 ticks; track consecutive unreliable candles.
     - Match blueprint escalation rule: if 50+ consecutive candles are unreliable, escalate system state to DEGRADED regardless of trust/anomaly thresholds.
     - Unit tests at boundary timestamps (exact 5m/1h rollovers).
     - DoD: candle outputs match expected OHLCV on synthetic streams.

   - 6.2 Bootstrap procedure
     - Fetch last 500 candles per symbol per timeframe via Binance REST.
     - Verify no timestamp overlap/gap between bootstrapped last candle and first live candle.
     - DoD: indicators are valid immediately after startup.

   - 6.3 Indicators per timeframe (RSI, MACD, Bollinger, EMA cross, ATR)
     - Implement from scratch.
     - Validate against TA-Lib on a known dataset as an oracle.
     - DoD: indicator values match TA-Lib within tolerance.

   - 6.4 Order Flow Imbalance (tick-level)
     - Implement rolling 50-tick OFI in [-1, 1].
     - Unit tests: monotone rising prices yields positive OFI; monotone falling yields negative.
     - DoD: OFI behaves as expected on fixtures.

   - 6.5 Dual-timeframe signal logic
     - Implement as a pure function (no side effects) following steps 1–6.
     - Unit tests cover LONG/SHORT gating, OFI gate, confluence counting, and disagreement blocking.
     - DoD: signal logic passes combinatorial test suite.

   - 6.6 Position sizing
     - Implement base_size × state_multiplier × confluence_multiplier × signal_strength.
     - DoD: sizing matches formula on fixtures.

   - 6.7 Kafka wiring
     - Consume market.ticks.scored; publish trading.signals.
     - DoD: live system emits signals; backtest harness produces realistic signal frequency.

   - 6.8 Tuning loop (using backtest)
     - Tune thresholds to hit target signal frequency (5–10/day/symbol) and acceptable drawdown.
     - Document tuned thresholds and rationale.

8. Phase 7 — Risk management (Layer 4)
   - Implement pre-execution checks in exact order and with numeric thresholds specified.
   - Implement ATR-based stop-loss/take-profit (1.5×ATR, 2.5×ATR).
   - Implement circuit breaker state machine (NORMAL/REDUCED/HALTED).
   - Integrate with backtest to validate risk metrics, drawdown behavior, and loss limits.
   - DoD: end-to-end backtest through Layer 4 produces Approved/Rejected orders consistent with rules.

9. Phase 8 — Execution engine (Layer 5)
   - Paper trading mode first (simulate fills with configurable slippage).
   - Match blueprint defaults: slippage factor default 0.05%; require at least 1 week paper-trading before any live-exchange attempt (even if live trading remains out of scope for the project).
   - Implement order lifecycle + retry with jitter; implement dead-letter queue.
   - Match blueprint retry policy: backoff with jitter (0.5s+U(0,0.5), 1s+U(0,1), 2s+U(0,2)); after 3 retries mark failed, emit critical alert, and send to a dead-letter queue; poll order status at 1s intervals until terminal state.
   - Only after stable paper mode: implement idempotency via SQLite (WAL), deterministic client_order_id, startup reconciliation.
   - Explicit tests: crash between write and confirmation; duplicate order error path.
   - DoD: 48-hour paper run without duplicate fills or unreconciled pending orders.

10. Phase 9 — Audit log (Layer 6) (can be parallel with Phase 8)
   - Implement AuditEntry schema and canonical hash computation.
   - Match blueprint conventions: genesis previous_hash is 64 zeros; canonical JSON uses UTF-8, sorted keys, no whitespace, and includes nulls; compute current_hash last over all fields except current_hash.
   - Rotation rule: when rotating at 100MB, the new file’s genesis entry uses the final hash of the previous file as its previous_hash (cross-file continuity).
   - Implement incremental O(1) chain verification per write.
   - Implement 60-second full replay verifier (halts on chain break).
   - Wire to audit.events topic.
   - DoD: deliberate corruption is detected; rotation preserves continuity.

11. Phase 10 — Statistical validation (required; do not cut)
   - Run walk-forward validation (>=3 OOS windows) and compute required metrics net of fees.
   - Match blueprint walk-forward procedure: split 90 days into 6×15-day windows; train on days 1–60, test 61–75; roll forward (train 16–75, test 76–90); repeat for at least 3 OOS test windows.
   - Run bootstrap permutation test (1000 shuffles) exactly: record actual Sharpe; shuffle trade entry timestamps 1000 times; compute Sharpe for each shuffle; compute p-value as fraction(shuffled Sharpe >= actual); require p<0.05 for 5% significance claim.
   - Run synthetic attack injection suite (5 scenarios) and record detection/false-positive rates.
   - Ensure the 5 synthetic attacks match blueprint: feed corruption (+5% tick), replay (200ms old tick), gradual drift (+0.1%/tick ×20), flash crash (7% down then recover), coordinated spoofing (2 of 3 sources +3%).
   - Run trust-weight grid search calibration on historical data; freeze chosen weights and document methodology.
   - DoD: a reproducible validation report artifact (tables + plots + config snapshot) exists.

12. Phase 11 — Web interface
   - Backend: FastAPI service consumes Kafka topics and exposes endpoints: status, signals, audit, backtest summary, and WebSocket live stream.
   - Match blueprint endpoints exactly: GET / (serve SPA), GET /api/status, GET /api/signals (last 100), GET /api/audit (last 200 + integrity status), GET /api/backtest (summary metrics), WS /ws/live (stream ScoredTick).
   - WebSocket implementation: Kafka consumer pushes into an internal asyncio queue; broadcaster fans out to all connected clients.
   - Match blueprint UI layout (4 panels):
     - Panel 1: 5m candlestick chart + anomaly overlay line with colors (green <0.55, amber 0.55–0.70, red >0.70) + signal markers (up/down arrows, confluence color).
     - Panel 2: system-state badge + trust score (subscores on hover) + anomaly score split (IF/HST on hover) + regime label + posterior mini bar chart.
     - Panel 3: last 20 signals table with required columns and direction color coding.
     - Panel 4: collapsible audit trail with chain integrity indicator.

   - Frontend: single page with TradingView Lightweight Charts; status panel; signal log; audit panel.
   - Styling last (dark theme, monospaced numeric font, state-consistent colors).
   - DoD: browser shows live chart + overlays + signal markers + audit tail with integrity indicator.

13. Phase 12 — Integration, polish, demo prep
   - Presentation/report requirement: explicitly state “tamper-evident, not tamper-proof” and avoid the word “blockchain” when describing the audit log.
   - Run all services end-to-end in docker-compose; rehearse demo 3 times.
   - Monitoring is part of the blueprint: run Prometheus + Grafana in docker-compose; verify scraping of every service’s /metrics; add the core dashboards (trust distribution, anomaly timeline, regime transitions, system-state history, signal frequency, live P&L) as time allows but do not omit the stack.
   - Update report with any deviations and the known limitations section.
   - Prepare jury defense answers and rehearse.
   - DoD: full system run the day before presentation with recorded screenshots/metrics.

**Relevant files**
- Existing: trading_blueprint_final.docx.md — authoritative contracts, thresholds, and validation requirements.
- New (to create): docker-compose stack definition; shared schema/config package; one service per layer; backtest harness; web backend + static frontend; pytest suites; data download/training scripts; documentation/runbooks.

**Verification**
1. Phase 1: broker smoke tests (produce/consume; consumer groups) and 30-minute stability.
2. Phase 2: unit tests for adapters, sequence tracker, consensus, trust scorer, tick hash chain; 30-minute live validated tick run.
3. Phase 3: model training script produces artifact + interpretability check outputs.
4. Phase 4: unit tests for rolling stats, feature builder, IF retrain atomic swap, HST score-before-learn, hysteresis transitions; live scored tick run.
5. Phase 5: deterministic backtest run produces metrics + equity curve.
6. Phase 6–7: backtest-driven tuning yields sane signal frequency and bounded drawdowns.
7. Phase 8–9: 48-hour paper run + audit chain integrity checks + rotation test.
8. Phase 10: walk-forward + permutation p-value + attack injection metrics + trust weight calibration report.
9. Phase 11: live dashboard renders and streams without flicker; endpoints return expected payload sizes.

**Decisions**
- Full blueprint scope by default: BTC-USDT + ETH-USDT; dual timeframe; Kafka-first architecture.
- Paper trading only for the project; live exchange trading is out of scope unless explicitly required later.
- Scope-cut policy (only if behind schedule): cut UI polish, then second symbol, then 1h confirmation; never cut backtesting rigor, trust calibration, or validation suite.

**Further Considerations**
1. Certificate pinning implementation detail varies by WebSocket client/library; choose a library/approach that can expose peer cert fingerprint reliably under WSL2.
2. Historical data format differences (agg trades vs ticks) must be normalized to the same internal tick schema for backtesting realism.
3. Ensure a single source of truth for thresholds/weights (config snapshot saved with every backtest/validation run) to keep results defensible.

**Traceability Matrix (Blueprint → This Plan)**

A) **Numbered implementation procedures (1–35)**
- 1 → Phase 2 (2.1): WebSocket connections for all 3 exchanges with reconnection loop; do not proceed until stable console ticks.
- 2 → Phase 2 (2.2): TLS certificate pinning + unit test wrong fingerprint refuses connection.
- 3 → Phase 2 (2.1): NormalizedTick schema + 3 adapters + unit tests using sample raw messages.
- 4 → Phase 2 (2.1): Sequence ID tracker + unit test deliberate gaps.
- 5 → Phase 2 (2.4): Consensus engine + unit test with 0.5% outlier quarantined.
- 6 → Phase 2 (2.5): Trust score formula + unit tests for each subscore + combined hand-check.
- 7 → Phase 2 (2.6): Internal hash log + corruption test catches integrity break.
- 8 → Phase 2 (2.7): Wire all Layer 1 modules + 30-minute live run + inspect trust distribution (>0.8 typical).
- 9 → Phase 3: Download 90 days BTC-USDT + ETH-USDT historical data.
- 10 → Phase 3: Compute 30-minute realized volatility series.
- 11 → Phase 3: Fit GaussianHMM(n_components=3, covariance_type=full).
- 12 → Phase 3: Validate interpretability; re-init seed/add data until states separate.
- 13 → Phase 3: Serialize trained HMM with joblib; load at Layer 2 startup.
- 14 → Phase 7: Risk check 1 (system state): HALT rejects; DEGRADED rejects except CLOSE_ALL.
- 15 → Phase 7: Risk check 2: trust_score < 0.40 rejects.
- 16 → Phase 7: Risk check 3: position size cap at 20%.
- 17 → Phase 7: Risk check 4: cap per-trade loss to <=2% of capital (resize if needed).
- 18 → Phase 7: Risk check 5: portfolio exposure cap at 60%.
- 19 → Phase 7: Risk check 6: 5+ consecutive losing trades pauses trading for 30 minutes + alert.
- 20 → Phase 7: Risk check 7: daily loss limit 8% halts for remainder of session.
- 21 → Phase 7: Risk check 8: drawdown >5% reduces all sizes 50% until drawdown <3%.
- 22 → Phase 8: Generate deterministic client_order_id = SHA-256(symbol+direction+size+timestamp_utc+session_id).
- 23 → Phase 8: Persist client_order_id to SQLite (WAL) before sending API request.
- 24 → Phase 8: On network error, check exchange history for client_order_id before retry.
- 25 → Phase 8: Treat duplicate order error as success; log dedup event.
- 26 → Phase 8: Startup reconciliation: verify pending SQLite orders against exchange before resuming.
- 27 → Phase 10: Split 90 days into 6 windows of 15 days.
- 28 → Phase 10: Train tunables (trust weights, IF contamination, signal thresholds) on days 1–60.
- 29 → Phase 10: Test on days 61–75 without changing parameters; record all metrics.
- 30 → Phase 10: Roll forward (train days 16–75, test 76–90).
- 31 → Phase 10: Repeat for at least 3 test windows; report per-window + aggregate.
- 32 → Phase 10: Record actual Sharpe from walk-forward backtest.
- 33 → Phase 10: Shuffle trade entry timestamps 1000 times; compute Sharpe for each shuffle.
- 34 → Phase 10: Compute fraction(shuffled Sharpe >= actual Sharpe).
- 35 → Phase 10: Require fraction < 0.05 to claim p<0.05 significance.

B) **Blueprint “must/critical” items not expressed as 1–35**
- Kafka topic boundary discipline (no direct service-to-service calls) → enforced by Phase 0 schema package + Phase 1 topic setup + per-layer wiring tasks.
- Consumer group semantics → Phase 1 smoke tests + Phase 11 web backend uses its own consumer group.
- Kafka unavailability buffer (max 1000 messages; flush; drop oldest; emit critical) → Cross-cutting requirements.
- Exchange adapter lifecycle (reconnect backoff, 5s heartbeat timeout, REST snapshot on reconnect) → Phase 2 (2.1).
- Cert pinning + 30-day expiry warning + controlled fingerprint updates → Phase 2 (2.2) + Phase 12 report notes.
- Consensus: volume-weighted median + divergence tolerance 0.3% + quarantine re-eval + 3-consecutive escalation + 50ms alignment window → Phase 2 (2.4).
- Trust score: linear combination T1–T5, T3 half-life 25ms, weights configurable + grid-search calibration requirement → Phase 2 (2.5) + Phase 10 calibration deliverable.
- Layer 2: HST score-before-learn (critical) → Phase 4 (4.5) test.
- Layer 2: regime-dependent MAD multipliers (3/5/8) + guard floor 0.65 → Phase 4 (4.6).
- Layer 2: hysteresis upgrades require 10 consecutive qualifying ticks; HALT downgrade immediate → Phase 4 (4.7).
- System behavior: HALT if no valid consensus tick for 30s (default) → Phase 4 watchdog addition.
- Candle aggregation: max anomaly score (not average), discard <3 ticks, reliability rule + 50 unreliable candle escalation → Phase 6 (6.1).
- Bootstrap: last bootstrapped candle must connect cleanly to first live candle (explicit test) → Phase 6 (6.2).
- Indicators: implement from scratch and validate against TA-Lib oracle → Phase 6 (6.3).
- OFI: computed at tick-level; must be explainable in defense → Phase 6 (6.4) + Phase 12 jury prep.
- Fees: backtest net-of-fees (0.1%) with gross vs net reporting → Phase 5 + Phase 10.
- Paper trading duration: minimum 1 week before any live attempt → Phase 8 policy.
- Audit log: incremental verification O(1), full replay every 60s halts on break, rotation 100MB cross-file continuity, tamper-evident disclaimer; avoid “blockchain” → Phase 9 + Phase 12.
- Web UI requirements (not minimalistic; dark theme; monospaced numerics; 4-panel layout; endpoint list) → Phase 11.
- Monitoring (Prometheus/Grafana stack) → Phase 1 (compose) + Phase 12 verification.

C) **Proof of completeness gate (before any implementation starts)**
- Create and maintain a checklist that is checked off only when the corresponding unit/integration test and the phase DoD are satisfied; no phase transition without checklist completion.

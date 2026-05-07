<!-- Purpose: Faithful pipeline step-by-step flow (topic-aware) generated from project scan -->

As implemented, the project runs as a complete Kafka pipeline for Layers 1 to 5. Backtesting replays the same layer logic in-process (without Kafka) for determinism and speed. Here is the faithful step-by-step flow.

1. **Layer 1 ingestion receives exchange data**
- The exchange adapters connect to live exchange feeds.
- They verify TLS pinning before accepting the connection.
- They reconnect on heartbeat loss.
- They fetch a fresh REST snapshot after reconnect.
- They normalize exchange payloads into `NormalizedTick`.
- The console runner can print those ticks locally for debugging.
- The Kafka publisher then publishes them to `market.ticks.raw`.
- This is implemented in the Layer 1 ingestion code under layer1_ingestion.

2. **Layer 1 validated subscribes to `market.ticks.raw`**
- The validated service uses a `KafkaConsumer` on `market.ticks.raw`.
- It decodes each raw message as JSON.
- It validates the message as `NormalizedTick`.
- It records exchange liveness.
- It aligns ticks into 50 ms windows using TickAligner (custom aggregation, deviates from blueprint for robustness).
- TickAligner maintains a Last Known Value (LKV) registry per exchange.
- When a window closes, missing sources are filled from LKV if the tick is ≤15 seconds old (LKV_STALENESS_MS).
- This allows consensus to proceed even when some exchanges have temporary feed gaps.
- Active sources (seen within 30 seconds: LIVENESS_THRESHOLD_MS) are tracked per symbol.
- Each tick carries its age (ms) for weighted trust scoring (fresher ticks weighted higher via T2 exponential decay).
- It computes consensus with the Layer 1 consensus engine.
- It requires the configured primary exchange to be present in the consensus set.
- If the primary exchange is missing, it skips the window and emits an audit event.
- It computes latency, spread, and volume summaries from the primary tick.
- It computes trust subscores, including T2 continuous score that decays based on tick age (T2_HALF_LIFE_MS).
- It computes the trust score.
- It computes the validated-tick hash and advances the hash chain tip.
- The validated-tick hash uses canonical JSON with sorted keys and no whitespace, over `{symbol, consensus_mid, trust_score, received_timestamp_ms, previous_hash}`.
- It publishes the resulting `ValidatedTick` to `market.ticks.validated`.
- Downstream layers use the primary-exchange `mid_price` and primary-timeframe snapshots as the canonical inputs for feature construction, indicators, risk checks, sizing and execution; `consensus_mid` is retained only for cross-checks, monitoring and audit.
- The primary exchange is selected from `PRIMARY_EXCHANGE` (default `binance`), and the Layer 1 timing constants are the 50 ms alignment window, `LKV_STALENESS_MS = 15_000`, and `LIVENESS_THRESHOLD_MS = 30_000`.
- Layer 1 also exposes Prometheus `/metrics` and emits audit events for reconnects, divergence, gaps, and other integrity checks.
- This is implemented in service.py, TickAligner and ConsensusEngine in layer1_consensus/engine.py, TrustWeights and compute_t2() in layer1_trust/scoring.py, and the topic publisher in kafka_json_publisher.py.

3. **Layer 1 also handles sequence and integrity tracking**
- It tracks per-exchange sequence IDs per symbol.
- It emits audit events for gaps and non-monotonic sequence IDs.
- It keeps the latest hash-chain tip in memory.
- It persists hash-chain entries asynchronously.
- The validated output includes trust, subscores, used sources, divergent sources, and liveness metadata.
- The audit helper is still best-effort stdout/file logging, not the full Layer 6 audit chain yet.
- That helper is in audit.py.
 

  
4. **Layer 2 anomaly service subscribes to `market.ticks.validated`**
- The anomaly service consumes `ValidatedTick` messages from `market.ticks.validated`.
- It decodes each message from JSON.
- It validates the message as `ValidatedTick`.
- It updates rolling statistics for returns, log volume, and spread.
- It computes 30-minute realized volatility.
- It loads the HMM model artifact.
- It infers the current regime and posterior probabilities.
- It scores anomaly using Isolation Forest.
- It builds the Layer 2 feature vector from `mid_price`, `trust_score`, `volume_24h`, `spread`, and time-of-day features before scoring.
- It creates one scorer per symbol lazily, so each market pair has its own anomaly state.
- It retrains Isolation Forest asynchronously when the training buffer is ready.
- The Isolation Forest retrain is gated by a minimum warmup size, a retrain interval, and a bounded rolling buffer.
- It scores anomaly using Half-Space Trees.
- It scores first, then learns in HST.
- It fuses IF and HST scores.
- It applies the MAD guard.
- It updates the trust/anomaly state machine.
- It publishes `ScoredTick` to `market.ticks.scored`.
- Layer 2 also emits audit events for bad validated ticks, watchdog timeout, and watchdog recovery, and exposes `/metrics`.
- This is implemented in service.py and engine.py.

5. **Layer 2 also has a watchdog and HALT path**
- If no valid validated tick arrives for the configured timeout, the watchdog forces HALT.
- It emits an audit event for timeout and recovery.
- The service polls Kafka with a timeout rather than blocking forever so it can enforce the watchdog.
- This is part of service.py.

 

6. **Layer 3 strategy service subscribes to `market.ticks.scored`**
- The strategy service consumes `ScoredTick` messages from `market.ticks.scored`.
- It decodes and validates each message.
- It maintains per-symbol state in memory.
- It creates each symbol's state lazily the first time that symbol appears.
- It builds 5m candles.
- It builds 1h candles.
- It discards candles with too few ticks.
- It tracks unreliable candle streaks.
- It applies candle-level system-state overrides when a candle has one.
- It computes indicators from the candle stream.
- It computes OFI from the tick stream.
- It computes OFI before evaluating the signal, so the current tick is used as confirmation data.
- It evaluates the dual-timeframe signal logic.
- That signal evaluation requires the primary and higher timeframe snapshots, OFI, trust score, and current system state.
- It sizes the signal.
- Sizing is a separate formula that turns a valid LONG/SHORT into a final position percentage.
- It publishes trade signals to `trading.signals`.
- It only publishes non-HOLD signals.
- This is implemented in service.py.

7. **Layer 3 keeps symbol state locally**
- Each symbol has its own `Layer3SymbolState`.
- That state holds candle aggregation, indicator history, OFI state, and recent snapshots.
- The service emits an audit event on start and on bad tick decoding.
- The service exposes `/metrics`.
- The code is in service.py.



8. **Layer 4 risk management runs as a Kafka consumer service**
- Layer 4 now subscribes to `trading.signals` and publishes `trading.orders.approved`.
- The new `services/layer4_risk/service.py` wraps `Layer4RiskEngine.evaluate_signal(...)` and maps `TradeSignal` -> `ApprovedOrder`.
- It checks the system state gate.
- It checks the trust floor (skipped for CLOSE_ALL signals to allow emergency liquidation).
- It has a special CLOSE_ALL path that bypasses degraded-state rejection and creates an order with size = current portfolio exposure and no stops.
- It checks the position-size cap.
- It checks per-trade loss limits.
- It checks portfolio exposure.
- It checks losing-trade pause logic.
- It checks the daily loss limit.
- It checks drawdown reduction and release thresholds.
- It computes ATR-based stop-loss and take-profit (ATR 1.5× for stop-loss, 2.5× for take-profit).
- It applies the circuit breaker state (NORMAL/REDUCED/HALTED with recovery gates).
- It publishes `trading.orders.approved` when an order is approved and emits audit events on rejection.
- The implementation is in `services/layer4_risk`.


9. **Layer 4 produces `ApprovedOrder` messages on Kafka**
- The approved order is a typed schema object and is published to `trading.orders.approved`.
- It carries symbol, direction, size, ATR, stops, trust score, circuit-breaker state, and snapshots.
- The schema is in `shared/schemas.py` (now includes `ExecutedOrder` schema as well).

 

10. **Layer 5 execution runs as a Kafka consumer service**
- Layer 5 now subscribes to `trading.orders.approved` and publishes `trading.orders.executed`.
- The new `services/layer5_execution/service.py` wraps `ExecutionEngine.submit_order()` and preserves WAL idempotency semantics.
- It assigns a deterministic `client_order_id`.
- It persists the order in SQLite WAL before sending (when `EXECUTION_PERSISTENCE_DB` is configured).
- It submits the order to the adapter.
- It receives fill information.
- It records fill price, fee, slippage, and fill fraction.
- It updates its local execution state.
- It retries transient failures with jitter.
- It handles duplicate-order responses as success when the adapter reports terminal state.
- It reconciles pending orders on restart by querying adapter status and publishing reconciled executions.
- The implementation is in `services/layer5_execution`.

11. **Layer 5 supports two execution adapters: simulated and live Binance**
- The adapter is selected via the `EXECUTION_ADAPTER_TYPE` environment variable (default: "simulated").
- **Simulated adapter** (for unit tests and backtests):
  - Deterministic, in-process, no network calls.
  - Models paper trading with configurable slippage (0.05% default) and fees (0.075% default).
  - Applies partial fills for large orders (size > 50% threshold).
  - Models deterministic latency based on order size.
  - Exposes order-status queries for reconciliation.
- **Binance adapter** (for live paper trading and live trading):
  - Connects to Binance Futures API (testnet or live).
  - Requires `BINANCE_API_KEY` and `BINANCE_API_SECRET` environment variables.
  - Set `BINANCE_TESTNET=true` for Binance Testnet (sandbox), `false` for live trading.
  - Uses HMAC SHA256 signing for request authentication.
  - Submits market orders and receives real fills from the exchange.
  - Computes slippage and fees from actual execution.
  - Stores order status for reconciliation via `get_order_status()`.
- Both adapters implement the same interface, so no changes needed in `ExecutionEngine`.
- Both support the WAL idempotency and retry logic in Layer 5.
- The adapter is instantiated in `services/layer5_execution/service.py`.

<!-- stopped here  -->

12. **Backtesting replays historical data without Kafka in the replay loop**
- The backtest engine loads historical ticks.
- It generates synthetic multi-exchange ticks from the historical anchor stream.
- It applies attack scenarios.
- It runs the Layer 1 consensus and trust logic directly.
- It runs the Layer 2 anomaly logic directly.
- It runs the Layer 3 strategy logic directly.
- It runs the Layer 4 risk logic directly.
- It runs the Layer 5 execution logic directly.
- It does not pass those replay events through Kafka topics.
- It records gross PnL, net PnL, drawdown, Sharpe, win rate, and other metrics.
- The implementation is in engine.py.

13. **Backtesting also writes artifacts**
- It writes the equity curve.
- It writes metrics JSON.
- It writes a config snapshot.
- It writes the HTML report.
- It optionally saves results to SQLite.
- It runs permutation testing on the equity history.
- This is also in engine.py and permutation_test.py.

14. **Kafka topic wiring that is actually present**
- `market.ticks.raw` is the Layer 1 ingestion output and Layer 1 validated input.
- `market.ticks.validated` is the Layer 1 validated output and Layer 2 input.
- `market.ticks.scored` is the Layer 2 output and Layer 3 input.
- `trading.signals` is the Layer 3 output and Layer 4 input.
- `trading.orders.approved` is the Layer 4 output and Layer 5 input.
- `trading.orders.executed` is the Layer 5 output (consumed by Layer 6 and web backend).
- All services now use Kafka for inter-layer communication (Layers 1–5 Kafka-driven).
- Backtesting optionally routes signal publication through Kafka via test-mode publisher.

15. **Metrics and audit are cross-cutting but incomplete at the persistence layer**
- Each live Python service exposes a Prometheus `/metrics` endpoint.
- Audit events are emitted through the shared helper.
- Audit events are not yet persisted as the full Layer 6 hash-chained audit log.
- The audit helper is still best-effort, not the final blueprint audit subsystem.
- The helper is in audit.py.

If you want, I can do one more pass and rewrite this as a strict “topic-by-topic message flow” with each topic showing exactly which service consumes it and which service publishes the next one.

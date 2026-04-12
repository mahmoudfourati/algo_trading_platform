  
**SECURE ALGORITHMIC TRADING PLATFORM**

Final Architecture & Implementation Blueprint

*Fully Revised — Standalone Edition*

Crypto Markets  ·  Binance · Coinbase · Kraken

Python  ·  Docker \+ Kafka  ·  HMM \+ Isolation Forest \+ HST  ·  Dual-Timeframe Strategy

Walk-Forward Validation  ·  Order Flow Imbalance  ·  FastAPI \+ TradingView Web Interface

*Academic Technical Document  —  End of Year Project*

# **0\.  Executive Summary**

This document is the complete, standalone, final architecture and implementation blueprint for a secure algorithmic trading platform. It supersedes all previous versions and incorporates every revision, addition, and correction discussed during the design process. It is fully self-contained — no prior document is required to understand or implement the system.

The platform is designed for day and swing trading on cryptocurrency markets (Binance, Coinbase, Kraken). Its core contribution is a multi-layer trust and validation framework that verifies the integrity of market data before any trading decision is made. The trading strategy layer is intentionally classical and interpretable, with rigorous statistical validation, so that the security and anomaly detection properties of the upstream layers can be evaluated cleanly without confounding complexity in the strategy itself.

The system is implemented in Python, deployed using Docker and Apache Kafka, and includes a professional web interface built with FastAPI and TradingView Lightweight Charts.

| Layer | Name | Primary Output |
| :---- | :---- | :---- |
| 1 | Trusted Data Ingestion | ValidatedTick with 5-component trust score |
| 2 | Market Anomaly Detection | ScoredTick with anomaly score, regime, system state |
| 3 | Trading Strategy Engine | TradeSignal with dual-timeframe confluence scoring |
| 4 | Risk Management | Approved or blocked order with stop-loss and take-profit |
| 5 | Execution Engine | Placed order with idempotency guarantee |
| 6 | Tamper-Evident Audit Log | Immutable hash-chained event record |
| 7 | Web Interface | Live dashboard — chart, scores, signals, audit tail |

| FRAMING STATEMENT The trading strategy is intentionally simple because the research contribution of this project is the multi-layer data trust framework — not the strategy. The indicators are a demonstration vehicle. The novel and defensible contribution is the answer to: how does an automated system know how much to trust its own inputs before acting on them? |
| :---- |

# **1\.  Context, Problem Statement & Threat Model**

## **1.1  The Core Problem**

Modern automated trading systems are exposed to a class of risks qualitatively different from traditional software bugs. The system interacts with external networks and data providers that are partially or fully outside the operator's control. Three distinct failure modes must be addressed simultaneously.

* Feed corruption: a data provider sends incorrect prices due to bugs, infrastructure failures, or deliberate manipulation. The system must detect this without discarding legitimate extreme market moves.

* Adversarial attacks: an attacker intercepts or spoofs exchange communications to inject fabricated prices and trigger false trading signals.

* Market anomalies: real market events (flash crashes, volatility spikes) can superficially resemble attacks. The system must distinguish between the two without halting trading during legitimate market stress.

A system that trusts a single exchange feed and acts on it directly fails on all three dimensions. This architecture addresses each one explicitly and separately.

## **1.2  Formal Threat Model**

| Attack Vector | Mitigating Module | Mechanism | Residual Risk |
| :---- | :---- | :---- | :---- |
| Feed spoofing — attacker impersonates a legitimate exchange | Layer 1 — TLS \+ cert pinning | SHA-256 fingerprint of server certificate compared against pinned expected value at connection time. Mismatch refuses the connection entirely, regardless of CA validity. | Attacker obtains a valid cert from a trusted CA for the exchange domain. Mitigated by pinning to the specific cert fingerprint, not the CA chain. |
| Replay attack — old but legitimate ticks re-injected | Layer 1 — T3 latency decay \+ T4 sequence tracking | T3 exponential decay penalizes ticks older than \~25ms. T4 flags non-monotonic sequence IDs. A replayed tick fails both checks. | Attacker with sub-25ms latency could replay within the decay window. Acceptable for day/swing trading horizon. |
| Man-in-the-Middle — modifying ticks in transit | Layer 1 — TLS encryption \+ cert pinning | TLS encrypts and authenticates every byte. MitM modification breaks the MAC, failing the connection. Pinning prevents TLS termination with a fraudulent cert. | None if TLS pinning is correctly implemented. |
| Single-source corruption — one exchange sends wrong prices | Layer 1 — volume-weighted median consensus | Median across three sources structurally isolates a single outlier. T2 sub-score drops immediately, flagging the tick regardless of whether the price looks plausible. | Two of three sources simultaneously corrupted. Extremely unlikely in practice. |
| Flash crash confusion — legitimate extreme move misclassified | Layer 2 — HMM regime classifier | HMM transitions to high-volatility state, relaxing the MAD multiplier k to 8.0. Large moves in high-volatility regime do not trigger HALT — only CONSERVATIVE. | Very fast flash crashes may not give the HMM time to update before the extreme tick arrives. |
| Data provider bugs — malformed or out-of-sequence ticks | Layer 1 — schema validation \+ sequence \+ T3 | Schema normalizer rejects null/NaN fields. Sequence tracker catches backwards IDs. T3 collapses for future-dated timestamps. | Silent price corruption that passes all structural checks. Partially covered by multi-source consensus. |
| Infrastructure compromise — write access to log files | Layer 6 — hash-chained audit log | Any modification of a past entry breaks the chain and is detected by the integrity verifier on the next 60-second cycle. | Sophisticated attacker with write access can recompute the entire chain. Log is tamper-evident, not tamper-proof. Explicitly documented. |

| TAMPER-EVIDENCE VS TAMPER-PROOF The audit log is tamper-evident, not tamper-proof. A single-writer hash chain can be recomputed by a determined attacker with write access. This distinction is explicitly documented and must be stated clearly when presenting the system. Do not use the word blockchain. |
| :---- |

# **2\.  Infrastructure Architecture**

## **2.1  Technology Stack**

| Component | Technology | Justification |
| :---- | :---- | :---- |
| Language | Python 3.11+ | Rich ML ecosystem, fast development cycle, adequate performance for day/swing latency targets. GIL limitations noted and accepted. |
| Message backbone | Apache Kafka | Decouples all layers. Enables independent restarts, event replay for backtesting, and multiple consumers per topic without blocking producers. |
| Containerization | Docker \+ docker-compose | Reproducible environments, isolated dependencies, easy local deployment and demo. Full Kubernetes is out of scope. |
| Data sources | Binance WS, Coinbase WS, Kraken WS | Three independent crypto sources provide multi-source consensus coverage. All provide free WebSocket market data feeds. |
| Historical data | Binance REST API (data.binance.vision) | Free public OHLCV data used for HMM training, IF training, candle bootstrap, and backtesting. |
| ML — batch | scikit-learn (Isolation Forest) | Periodic retraining every 15 minutes on rolling 30-day window. |
| ML — online | River (Half-Space Trees) | Genuinely streaming anomaly detection, updates on every tick with O(1) cost. |
| ML — regime | hmmlearn (GaussianHMM) | 3-state Hidden Markov Model for volatility regime classification. |
| Web backend | FastAPI (Python) | Fast to build, automatic API docs, native WebSocket support for live data streaming to browser. |
| Web frontend | TradingView Lightweight Charts \+ HTML/CSS/JS | Professional-grade charting library, free, used in production trading terminals. |
| Monitoring | Prometheus \+ Grafana | Metric collection and real-time visualization for ops monitoring alongside the web interface. |
| Testing | pytest \+ pytest-asyncio | Unit and integration tests. Synthetic attack injection tests live here. |

## **2.2  Kafka Topic Architecture**

Every inter-layer communication passes through a named Kafka topic. No layer calls another layer directly. This is the single most important architectural decision in the system — it is what makes the microservice separation real rather than cosmetic.

| Topic | Producer | Consumer(s) | Message Type |
| :---- | :---- | :---- | :---- |
| market.ticks.raw | Layer 1 adapters | Layer 1 consensus engine | RawTick per exchange — raw normalized tick before consensus |
| market.ticks.validated | Layer 1 trust scorer | Layer 2 anomaly detector | ValidatedTick with full trust score and sub-scores |
| market.ticks.scored | Layer 2 decision gate | Layer 3 strategy engine | ScoredTick with anomaly score, regime, system state |
| trading.signals | Layer 3 strategy engine | Layer 4 risk manager | TradeSignal with direction, size, confluence score |
| trading.orders.approved | Layer 4 risk manager | Layer 5 execution engine | ApprovedOrder with stop-loss and take-profit levels |
| trading.orders.executed | Layer 5 execution engine | Layer 6 audit logger, web backend | ExecutionReport with fill price, quantity, slippage |
| audit.events | All layers | Layer 6 audit logger | AuditEvent — any significant system event from any layer |

| CONSUMER GROUP SEMANTICS Each service subscribes using a named consumer group. Multiple instances of the same service share a group and Kafka load-balances messages between them — each message processed once. The web backend and monitoring tools use separate consumer groups and receive every message independently. Adding a new analytical consumer requires zero changes to any existing service. |
| :---- |

## **2.3  Docker Service Map**

The following containers run under docker-compose: zookeeper, kafka, layer1-ingestion, layer2-anomaly, layer3-strategy, layer4-risk, layer5-execution, layer6-audit, api-backend (FastAPI), prometheus, grafana. Only the layer5-execution container requires outbound internet access to exchange APIs. All other services communicate exclusively within the Docker internal network.

Each Python service exposes a /metrics endpoint via the prometheus-client library. Grafana is pre-configured with dashboards for: trust score distribution per exchange, anomaly score timeline, regime state transitions, system state history, signal frequency, and live P\&L.

## **2.4  Kafka Unavailability Handling**

Every service maintains a bounded in-memory buffer (maximum 1000 messages) that holds outgoing messages during a Kafka outage. When Kafka recovers, the buffer is flushed in order. If the buffer exceeds its maximum size during a sustained outage, the oldest messages are dropped and a critical alert is emitted. This behavior is explicitly documented: during a prolonged Kafka outage, some audit events may be lost but trading operations continue with degraded logging.

# **3\.  Layer 1 — Trusted Data Ingestion**

Layer 1's sole responsibility is answering one question about every tick it receives: how much can we trust this data? By the time a tick exits Layer 1, it carries a trust score in \[0,1\] with a precise, auditable justification. No tick enters the trading pipeline without it.

## **3.1  Exchange Adapter Layer**

Each exchange has its own isolated adapter class. Mixing exchange-specific parsing into shared code is how silent bugs are introduced when one exchange changes its message format. Each adapter handles exactly four responsibilities.

### **TLS \+ Certificate Pinning**

On connection, the adapter extracts the server certificate's SHA-256 fingerprint and compares it against a hardcoded expected value in a version-controlled config file. A mismatch refuses the connection and emits a critical alert. Certificate expiry within 30 days emits an advance warning. Fingerprints are updated via a controlled deployment process only.

### **WebSocket Lifecycle Management**

Persistent connection with exponential backoff reconnection: first retry at 1 second, doubling to 30 seconds maximum. On reconnect, the adapter fetches a REST order book snapshot before resuming the tick stream to prevent acting on stale mid-prices. A 5-second heartbeat timeout triggers a reconnect. All reconnection events are logged to the audit trail.

### **Schema Normalization**

Every exchange's native format is mapped to the internal NormalizedTick schema. This is the only place in the codebase containing knowledge of exchange-specific formats:

NormalizedTick \= {

  exchange\_id: str,           \# 'binance' | 'coinbase' | 'kraken'

  symbol: str,                \# normalized e.g. 'BTC-USDT'

  bid: float,

  ask: float,

  last\_price: float,

  volume\_24h: float,

  exchange\_timestamp\_ms: int,

  received\_timestamp\_ms: int

}

### **Sequence ID Tracking**

A per-symbol counter tracks the last received sequence ID from each exchange. Any gap greater than 1 is logged and passed to the trust scorer as the T4 input. This catches both dropped packets and replay injection attempts.

## **3.2  Consensus Engine**

### **Volume-Weighted Median**

For each source i, compute mid\_i \= (bid\_i \+ ask\_i) / 2\. The consensus function is the volume-weighted median of the three mid-prices, using volume\_24h\_i as the weight. The median (not mean) is chosen because it is structurally resistant to a single outlier source — if one exchange sends a corrupted price, the median returns the agreed value of the other two without any explicit outlier detection step.

### **Divergence Tolerance**

Before computing consensus, each source's mid-price is compared against the raw (unweighted) median. Any source outside 0.3% deviation is flagged as divergent and quarantined — held in a buffer and re-evaluated on the next tick. A single-tick divergence is treated as a transient network anomaly. Three or more consecutive divergent ticks from the same source escalates the T2 penalty and raises an alert.

## **3.3  Trust Scorer**

The trust score is a weighted linear combination of five sub-scores:

T \= w1\*T1 \+ w2\*T2 \+ w3\*T3 \+ w4\*T4 \+ w5\*T5

| Sub-score | Default Weight | Formula | Rationale |
| :---- | :---- | :---- | :---- |
| T1 — TLS validity | 0.25 | Binary: 1.0 if cert fingerprint matched, 0.0 if rejected | A failed TLS check is catastrophic. Highest individual weight. |
| T2 — Consensus agreement | 0.30 | T2 \= agreeing\_sources / total\_sources (0.33, 0.67, or 1.0 with 3 sources) | Multi-source disagreement is the strongest available signal of feed corruption. |
| T3 — Latency freshness | 0.20 | T3 \= exp(-lambda \* latency\_ms), lambda \= ln(2)/25. T3=1.0 at 0ms, T3=0.5 at 25ms, T3≈0 at 100ms | Exponential decay is more realistic than a hard cutoff. Detects replay attacks and excessive network latency. |
| T4 — Sequence integrity | 0.15 | T4 \= 1.0 for gap=1; T4 \= 1/gap for gap\>1; T4=0.0 for gap\>=10 | Proportional penalty for dropped or injected packets. |
| T5 — Hash chain continuity | 0.10 | Binary: 1.0 if previous\_hash matches chain tip, 0.0 if broken | Lowest weight — chain breaks are more likely system restarts than attacks. |

| WEIGHT CALIBRATION REQUIRED All weights are config parameters, not hardcoded. Before finalizing, run a grid search over weight combinations on 30 days of historical data, minimizing false negatives (corrupted ticks passing as trusted) while keeping false positives below 5%. Document the chosen weights and the calibration methodology in the report. Without this, the weights are indefensible under jury questioning. |
| :---- |

Linear combination is used rather than multiplicative because a single zero sub-score (e.g., T5=0 from a system restart) would zero out the entire trust score multiplicatively, even when all other signals are clean. Linear combination is more robust to isolated zero sub-scores that have benign explanations.

## **3.4  Internal Tick Hash Log**

Every tick passing through the trust scorer is immediately hashed and appended to an internal chain log. Hash computation: SHA-256 over canonical JSON serialization (UTF-8, keys alphabetically sorted, no whitespace) of {symbol, consensus\_mid, trust\_score, received\_timestamp\_ms, previous\_hash}. Written asynchronously on a dedicated background thread to avoid blocking ingestion. Feeds Layer 6's audit log and provides the T5 input for subsequent ticks.

## **3.5  Layer 1 Output Contract**

ValidatedTick \= {

  symbol: str,

  asset\_class: str,           \# 'crypto'

  mid\_price: float,           \# consensus mid-price

  trust\_score: float,         \# T in \[0,1\]

  sub\_scores: { T1, T2, T3, T4, T5 },

  divergent\_sources: list,    \# exchange IDs quarantined this tick

  timestamp\_utc: int,         \# milliseconds

  tick\_hash: str              \# SHA-256 of this tick

}

Published to Kafka topic: market.ticks.validated

## **3.6  Implementation Procedure**

1. WebSocket connections for all three exchanges using the websockets Python library. Implement reconnection loop with exponential backoff. Do not proceed until all three reliably reconnect and deliver ticks to the console.

2. TLS certificate pinning. Extract each exchange's fingerprint in advance. Write a unit test that passes a wrong fingerprint and confirms the connection is refused.

3. NormalizedTick schema and three adapter classes. Unit test each adapter with a sample raw message, verifying normalized output is correct.

4. Sequence ID tracker. Unit test with a synthetic sequence containing a deliberate gap, verify gap size is correctly computed.

5. Consensus engine. Unit test with three sources where one is a 0.5% outlier. Verify the outlier is quarantined and consensus price reflects the other two.

6. Trust score formula. Unit test every sub-score in isolation. Then test the combined formula with known inputs against hand-computed expected values.

7. Internal hash log. Unit test by deliberately corrupting one entry and verifying the integrity checker catches it.

8. Wire all modules. Run against live feeds for 30 minutes. Inspect trust score distribution — most ticks should score above 0.8. Investigate systematic low-trust ticks.

# **4\.  Layer 2 — Market Anomaly Detection**

Layer 2 attaches a normalized anomaly score and a system state label to every ValidatedTick. The trading engine in Layer 3 never decides anything without both. Three detection mechanisms run in parallel — a statistical guard (MAD), a periodic batch model (Isolation Forest), and a genuinely streaming model (Half-Space Trees) — and their outputs are fused into a single score.

The architecture explicitly solves the streaming problem: Isolation Forest is not streaming (it requires a training corpus), but HST is. Running both in parallel gives historical depth from IF and real-time sensitivity from HST. Neither alone is adequate.

## **4.1  Rolling Statistics Engine**

Maintains a circular buffer of 500 ticks per symbol (approximately 8 hours at 1 tick/minute). Four computations run continuously using Welford's online algorithm (O(1) per tick, numerically stable):

* Rolling mean of log-returns: mean of ln(P\_t / P\_{t-1}) over the buffer

* Rolling standard deviation of log-returns (Welford's)

* Rolling MAD: median(|Xi \- median(X)|) over the buffer — O(N log N) via sorting, recomputed each tick

* 30-minute realized volatility: sum of squared log-returns over the most recent 30-minute slice, annualized — input to the HMM

| WHY MAD OVER STANDARD DEVIATION Financial returns have fat tails. Standard deviation inflates dramatically during extreme moves, causing threshold violations on legitimate volatility. MAD is robust to outliers by construction and does not require distributional assumptions. Both are maintained — MAD drives the guard, std is logged for monitoring. |
| :---- |

## **4.2  Regime Classifier — HMM (3 States)**

### **Architecture**

A GaussianHMM with 3 latent states (low, medium, high volatility), Gaussian emission distributions, and learned transition probabilities. Implemented with hmmlearn. The model observes a sequence of 30-minute realized volatility values and infers the most probable current state using the Viterbi algorithm.

### **Training Procedure**

9. Download 90 days of historical tick data for BTC-USDT and ETH-USDT from data.binance.vision.

10. Compute 30-minute realized volatility for each window — produces a time series of approximately 4,320 observations per 90 days.

11. Fit GaussianHMM(n\_components=3, covariance\_type='full') using model.fit(). Baum-Welch EM algorithm converges on state parameters.

12. Validate state interpretability: one state must have clearly lower mean volatility, one higher. If states are not separated, re-initialize with different random seed or add more data.

13. Serialize trained model to disk with joblib. Live service loads at startup.

### **Live Inference**

On every tick, the updated 30-minute realized volatility is fed to model.predict(). The last element of the returned state sequence is the current regime label. The full posterior model.predict\_proba() is also stored as \[P(low), P(medium), P(high)\] — used to weight the MAD multiplier continuously.

### **Regime-Dependent MAD Thresholds**

| Regime | MAD Multiplier k | Interpretation |
| :---- | :---- | :---- |
| Low volatility (state 0\) | 3.0 | Tight. In a calm market, a move of more than 3 MADs is genuinely suspicious. |
| Medium volatility (state 1\) | 5.0 | Base. Moderate sensitivity — balances false positives and false negatives. |
| High volatility (state 2\) | 8.0 | Relaxed. During volatile conditions, large moves are expected and normal. |

| HMM TRAINING ON BINANCE ONLY The HMM is trained on Binance data but applied to the consensus mid-price (aggregated across all three exchanges). This is the correct approach — the model sees the aggregated market, not any single exchange microstructure. Document this explicitly if asked. |
| :---- |

## **4.3  Feature Vector Construction**

Six features are computed per tick and z-scored against the rolling 500-tick window before being fed to either ML model. Identical computation for both models — any discrepancy would corrupt the score fusion.

| Feature | Definition | Normalization |
| :---- | :---- | :---- |
| f1 — Price return | log(P\_t / P\_{t-1}) | Z-scored: (f1 \- rolling\_mean) / rolling\_std |
| f2 — Volume | log(V\_t) | Z-scored: (log(V\_t) \- rolling\_log\_vol\_mean) / rolling\_log\_vol\_std |
| f3 — Bid-ask spread | (ask \- bid) / mid\_price | Z-scored against rolling spread statistics |
| f4 — Regime | HMM regime label {0, 1, 2} | No normalization — discrete integer |
| f5 — Trust score | T from Layer 1, range \[0,1\] | No normalization — already bounded |
| f6 — Time of day | sin(2π·t/86400), cos(2π·t/86400) | No normalization — bounded \[-1,1\]. T=86400s for 24/7 crypto markets, capturing daily cyclical patterns (US open effect etc.) |

## **4.4a  Isolation Forest**

### **Configuration**

n\_estimators=100, contamination=0.01 (recalibrate against historical data), max\_samples=256. Trained on the last 30 days of historical tick data at startup. Retrained every 15 minutes on a background thread using an atomic model swap (threading.Lock()) — the live scoring path always uses a fully trained model, never a partial one.

### **Score Normalization**

IF\_score \= clip(1.0 \- (decision\_function\_output \+ 0.5), 0.0, 1.0)

### **The Staleness Limitation**

The IF model is stale for up to 15 minutes between retrains. The 15-minute interval was selected by running sensitivity analysis across intervals of 5, 10, 15, 20, and 30 minutes, measuring false positive rate and computational overhead at each. 15 minutes provides the best tradeoff for the target hardware. This analysis must be documented in the report. HST runs in parallel specifically to cover the staleness window.

## **4.4b  Half-Space Trees**

### **Configuration**

from river.anomaly import HalfSpaceTrees

model \= HalfSpaceTrees(n\_trees=25, height=15, window\_size=250, seed=42)

n\_trees=25 balances score stability and computational cost. window\_size=250 gives approximately 4 hours of memory at 1 tick/minute — fast enough to adapt to regime changes, stable enough to avoid noise-driven score oscillations.

### **Critical Scoring Order**

hst\_score \= model.score\_one(feature\_dict)   \# SCORE FIRST

model.learn\_one(feature\_dict)               \# THEN LEARN

Reversing the order means the model has already incorporated the current tick before scoring it, artificially deflating anomaly scores on novel observations. This is a subtle and common implementation error.

## **4.5  Score Fusion**

A\_combined \= 0.45 \* IF\_score \+ 0.55 \* HST\_score

HST carries higher weight (0.55) because it is always current. IF is weighted (0.45) for its historical depth. Both weights are config parameters.

### **MAD Guard**

k \= {0: 3.0, 1: 5.0, 2: 8.0}\[current\_regime\]

if abs(f1\_raw) \> k \* current\_MAD:

    A\_final \= max(A\_combined, 0.65)

    mad\_guard\_triggered \= True

else:

    A\_final \= A\_combined

    mad\_guard\_triggered \= False

The MAD guard is a deliberate override of the ML output. It ensures statistically extreme moves always register as at least moderately anomalous. The mad\_guard\_triggered flag is logged explicitly so the audit trail distinguishes model-driven scores from guard-driven ones.

## **4.6  Decision Gate — 2D Matrix with Hysteresis**

| Trust Score | Anomaly Score | System State | Layer 3 Behavior |
| :---- | :---- | :---- | :---- |
| High (\>= 0.60) | Low (\< 0.55) | NORMAL | Full operation. Standard position sizing. All signals acted on. |
| High (\>= 0.60) | High (\>= 0.55) | CONSERVATIVE | Position size halved. No new entries. Existing positions held. |
| Low (\< 0.60) | Low (\< 0.55) | DEGRADED | Use last known-good tick. Hold existing positions only. No new entries. |
| Low (\< 0.60) | High (\>= 0.55) | HALT | Close all positions at market immediately. Suspend until manual reset or 10 consecutive NORMAL-qualifying ticks. |

Hysteresis rules: state upgrades require 10 consecutive qualifying ticks (prevents threshold oscillation). State downgrades to HALT are instantaneous (safety-first asymmetry). If the system receives more than 50 consecutive unreliable candles (from Layer 3's perspective), an automatic escalation to DEGRADED is triggered regardless of trust and anomaly scores.

## **4.7  Layer 2 Output Contract**

ScoredTick \= {

  ...ValidatedTick fields,

  anomaly\_score: float,          \# A\_final in \[0,1\]

  if\_score: float,               \# IF model output normalized to \[0,1\]

  hst\_score: float,              \# HST output in \[0,1\]

  regime: int,                   \# 0=low, 1=medium, 2=high

  regime\_posterior: list,        \# \[P(low), P(medium), P(high)\]

  system\_state: str,             \# 'NORMAL'|'CONSERVATIVE'|'DEGRADED'|'HALT'

  mad\_guard\_triggered: bool

}

Published to Kafka topic: market.ticks.scored

# **5\.  Layer 3 — Trading Strategy Engine**

Layer 3 generates trade signals from validated, scored market data. It does not validate data (Layer 1\) or assess risk (Layer 4). It generates signals only.

The key architectural revision from the original design: Layer 3 operates on candles, not raw ticks. The tick stream from Layer 2 feeds candle aggregators which build 5-minute and 1-hour OHLCV candles. Indicators are computed on candles. This decision resolves the noise problem with tick-level indicator computation and aligns the strategy engine with how professional trading systems actually operate.

The reason tick-level ingestion is still used in Layers 1 and 2 — rather than fetching candles directly from the exchange — is that those layers genuinely require tick-level resolution. The T3 latency sub-score requires individual tick timestamps. The consensus engine operates on a 50ms aggregation window. The HST anomaly scorer updates on every tick. Fetching candles directly would gut the security model. The tick-to-candle conversion happens at the Layer 2/3 boundary precisely because that is where the system transitions from data validation to trading logic.

## **5.1  Candle Aggregation Module**

Two independent candle aggregators run in parallel on the same ScoredTick stream.

### **OHLCV \+ Metadata Schema**

Candle \= {

  symbol: str,

  interval: str,              \# '5m' or '1h'

  open: float,                \# first tick mid-price in interval

  high: float,                \# maximum mid-price

  low: float,                 \# minimum mid-price

  close: float,               \# last tick mid-price

  volume: float,              \# sum of tick volumes

  avg\_trust\_score: float,     \# mean trust score over ticks in candle

  max\_anomaly\_score: float,   \# maximum anomaly score (not average)

  tick\_count: int,

  is\_reliable: bool,          \# False if avg\_trust \< 0.5 or max\_anomaly \> 0.7

  open\_time\_utc: int,

  close\_time\_utc: int

}

Maximum anomaly score is used (not average) because a single high-anomaly tick within a candle is sufficient reason to distrust the entire candle. A candle with fewer than 3 ticks is discarded as statistically meaningless. If 50 or more consecutive candles are flagged is\_reliable=False, the system state escalates to DEGRADED.

## **5.2  Bootstrap Procedure**

On cold start, the candle aggregator calls the Binance REST API to fetch the last 500 candles for each symbol at each timeframe before switching to live tick ingestion. This means indicators are valid from the first live candle rather than requiring hours of warm-up. The last bootstrapped candle must connect cleanly to the first live candle without timestamp gap or overlap — this must be tested explicitly, as timezone and symbol format mismatches are a common bootstrap bug.

## **5.3  Indicator Suite — Computed Per Timeframe**

Both the 5-minute and 1-hour candle streams receive the full indicator suite independently. Two separate indicator state objects are maintained — they never share state.

| Indicator | Parameters | Minimum Candles | Signal Contribution |
| :---- | :---- | :---- | :---- |
| RSI | 14-period, Wilder's smoothing on close prices | 14 | Below 35: approaching oversold (LONG context). Above 65: approaching overbought (SHORT context). |
| MACD | 12/26/9 on close prices | 35 (26 for line, \+9 for signal) | Histogram positive and increasing: building upward momentum. Negative and decreasing: building downward momentum. |
| Bollinger Bands | 20-period, 2σ on close prices | 20 | Price at or below lower band: statistically low (LONG context). At or above upper band: statistically high (SHORT context). Band width also logged as volatility proxy. |
| EMA Crossover | 9/21-period on close prices | 21 | 9-EMA crossing above 21-EMA: bullish trend. Crossing below: bearish. Track candles-since-crossover for signal freshness weighting. |
| ATR | 14-period on high/low/close | 14 | Not a signal indicator. Computed here for Layer 4's stop-loss and take-profit assignment. Passed downstream in TradeSignal. |
| **VALIDATE AGAINST REFERENCE IMPLEMENTATIONS** Implement each indicator from scratch rather than wrapping TA-Lib. Then validate your output against TA-Lib on a known dataset. This is more educational, more academically defensible, and ensures you understand what you are computing. TA-Lib can still be used as a validation oracle. |  |  |  |

## **5.4  Order Flow Imbalance**

Order flow imbalance is computed from the tick stream before candle aggregation. It measures the difference between buy-initiated and sell-initiated volume over a rolling window of 50 ticks:

for each tick:

    if mid\_price \> prev\_mid\_price: buy\_volume \+= volume

    else:                          sell\_volume \+= volume

OFI \= (buy\_volume \- sell\_volume) / (buy\_volume \+ sell\_volume)  \# range \[-1, 1\]

OFI is in \[-1, 1\]. Values near \+1 indicate strong buying pressure. Values near \-1 indicate strong selling pressure. It is used as a fifth confirmation signal in the signal logic and has strong theoretical grounding in the market microstructure literature (Easley, Lopez de Prado, O'Hara — order flow toxicity and VPIN).

OFI operates at tick level rather than candle level because order flow pressure is a short-term, high-frequency signal. It is the only indicator computed on the raw tick stream rather than on candles. This is intentional and must be explained clearly if asked.

## **5.5  Dual-Timeframe Signal Logic**

Signals are generated by evaluating the following steps in order. Any failed mandatory step stops evaluation and generates no signal for this tick.

### **Step 1 — System State Gate (mandatory)**

If system\_state is HALT or DEGRADED: no signal. If CONSERVATIVE: proceed but note — it will reduce position size.

### **Step 2 — Candle Reliability Gate (mandatory)**

The most recent 5-minute candle must have is\_reliable=True. If not, skip this tick and wait for the next candle.

### **Step 3 — Primary Timeframe Signal (5-minute, mandatory)**

All four of the following must be true for a LONG signal:

* RSI(5m) is between 25 and 45 — approaching oversold but not at an extreme that may indicate trend continuation rather than reversal

* MACD histogram(5m) is positive and increasing over the last two candles — momentum building, not just a single positive bar

* Close(5m) is at or below lower Bollinger Band, or within 0.3% of it — statistically low price

* 9-EMA crossed above 21-EMA within the last 3 candles, or is within 0.1% of crossing — trend alignment

For SHORT signals, symmetric conditions apply with all directions reversed.

### **Step 4 — OFI Confirmation (mandatory)**

For a LONG signal: OFI must be positive (OFI \> 0.10) — buying pressure must actually be present to confirm the reversal is genuine. For a SHORT signal: OFI must be negative (OFI \< \-0.10). This is the order flow imbalance gate and it is the primary differentiator from a naive classical indicator strategy.

### **Step 5 — Higher Timeframe Confirmation (1-hour)**

Count how many of the following three conditions hold for the 1-hour timeframe (LONG direction):

* RSI(1h) is below 55 — not in overbought territory

* MACD histogram(1h) is positive or turning from negative to positive

* Close(1h) is below the middle Bollinger Band — price has room to move upward

3 of 3 satisfied: full confluence (multiplier \= 1.0). 2 of 3: partial confluence (multiplier \= 0.5). Fewer than 2: timeframe disagreement — signal blocked.

### **Step 6 — Signal Strength**

A normalized signal strength score in \[0,1\] is computed based on how far each 5-minute indicator is from its threshold value. A signal where RSI is at 25 (deeply oversold) and price is 1% below the lower band is stronger than one where RSI is at 44 and price just touched the band.

## **5.6  Position Sizing Formula**

size \= base\_size × state\_multiplier × confluence\_multiplier × signal\_strength

Where base\_size \= 0.20 (20% of capital maximum), state\_multiplier \= 1.0 for NORMAL and 0.5 for CONSERVATIVE, confluence\_multiplier \= 1.0 for full (3/3) and 0.5 for partial (2/3), signal\_strength \= normalized \[0,1\] from Step 6\.

Result: a perfect signal in NORMAL state with full confluence \= 20% position. A partial-confluence signal in CONSERVATIVE \= 5% position. Sizing degrades gracefully with confidence.

## **5.7  Layer 3 Output Contract**

TradeSignal \= {

  symbol: str,

  direction: str,             \# 'LONG'|'SHORT'|'HOLD'|'CLOSE\_ALL'

  size\_pct: float,            \# final sized percentage of capital

  signal\_strength: float,     \# \[0,1\]

  confluence: str,            \# 'FULL'|'PARTIAL'|'NONE'

  ofi: float,                 \# order flow imbalance at signal time

  indicators\_5m: { rsi, macd\_histogram, bb\_position, ema\_cross\_candles\_ago, atr },

  indicators\_1h: { rsi, macd\_histogram, bb\_position, conditions\_met },

  candle\_reliable: bool,

  system\_state: str,

  timestamp\_utc: int

}

Published to Kafka topic: trading.signals

# **6\.  Layer 4 — Risk Management**

Layer 4 is the last line of defense before an order reaches the exchange. Every TradeSignal passes through pre-execution checks. There are no exceptions and no override paths.

## **6.1  Pre-Execution Checks (in order)**

14. System state check: if HALT, reject. If DEGRADED, reject all except CLOSE\_ALL.

15. Trust score floor: if trust\_score \< 0.40, reject regardless of signal quality.

16. Position size cap: hard ceiling at 20%. Strategy engine should never exceed this but Layer 4 enforces it as a safety net.

17. Max single-position loss: if potential loss at stop-loss level exceeds 2% of capital, reduce size proportionally to bring within the limit.

18. Portfolio exposure check: if adding this trade brings total exposure above 60% of capital, reject.

19. Consecutive loss check: if 5 or more consecutive losing trades, pause trading for 30 minutes and emit an alert.

20. Daily loss limit: if total day P\&L loss exceeds 8% of starting capital, halt all trading for the remainder of the session.

21. Intraday drawdown check: if drawdown from today's peak equity exceeds 5%, reduce all position sizes by 50% until equity recovers above 3% drawdown.

## **6.2  Stop-Loss and Take-Profit Assignment**

Every approved order is assigned stop-loss and take-profit levels using the ATR(14) value passed from Layer 3:

Stop-loss  (LONG): entry\_price \- 1.5 \* ATR(14)

Take-profit (LONG): entry\_price \+ 2.5 \* ATR(14)

Reward-to-risk ratio: 2.5 / 1.5 \= 1.67

ATR-based stops are adaptive to current volatility — wider during volatile periods, tighter during calm ones. The 1.67 reward-to-risk ratio means the strategy is profitable at a win rate as low as 38% (breakeven win rate \= 1 / (1 \+ RR) \= 1 / 2.67 \= 37.5%). Symmetric rules apply for SHORT positions.

## **6.3  Circuit Breaker State Machine**

| State | Trigger | Trading Behavior | Return Condition |
| :---- | :---- | :---- | :---- |
| NORMAL | Default state | Full trading, all positions | — |
| REDUCED | 3-4 consecutive losses OR intraday drawdown 3-5% | 50% position sizes, no new trades in direction of recent losses | 30-minute cooling period AND equity above 3% drawdown trigger |
| HALTED | 5+ consecutive losses OR daily loss limit OR Layer 2 HALT | No trading. Close existing positions at market. | Manual reset OR 10 consecutive ticks qualifying as NORMAL |

# **7\.  Layer 5 — Execution Engine**

Layer 5 receives ApprovedOrder objects from Layer 4 and places them on the exchange. It is responsible for order lifecycle management, failure handling, and idempotency. It does not re-evaluate risk or re-check signals — if it arrived on the approved orders topic, it gets placed.

## **7.1  Idempotency**

22. Generate deterministic client\_order\_id \= SHA-256(symbol \+ direction \+ size \+ timestamp\_utc \+ session\_id). session\_id is a UUID generated at service startup.

23. Write client\_order\_id to SQLite (WAL mode enabled for crash safety) before sending the API request.

24. On network error, check the exchange's order history for client\_order\_id before retrying. If found, treat as success. If not found, retry.

25. On exchange duplicate order error, treat as success and log the deduplication event.

26. On startup, run reconciliation: check all SQLite-recorded pending orders against the exchange before resuming normal operation. This handles the crash-between-write-and-confirm edge case.

## **7.2  Retry Policy**

Exponential backoff with jitter: retry 1 at 0.5s \+ random(0, 0.5s), retry 2 at 1s \+ random(0, 1s), retry 3 at 2s \+ random(0, 2s). After 3 failed retries, order is marked failed, a critical alert is emitted, and the order is written to a dead-letter queue for manual review. Order status is polled at 1-second intervals until a terminal state (FILLED, CANCELLED, REJECTED) is reached.

## **7.3  Paper Trading Mode**

Activated via config flag. Fills are simulated at current mid-price with a configurable slippage factor (default 0.05%). All other layers operate identically. The system must run in paper trading mode for at minimum one week before any live trading attempt. Paper trading results feed directly into the backtesting evaluation metrics.

# **8\.  Layer 6 — Tamper-Evident Audit Logging**

Layer 6 maintains an immutable record of every significant system event. The log is tamper-evident: any post-hoc modification of a past entry is detectable by replaying the chain.

## **8.1  Log Entry Schema**

AuditEntry \= {

  entry\_id: str,             \# UUID

  timestamp\_utc: int,        \# milliseconds

  event\_type: str,           \# 'TICK'|'ANOMALY'|'SIGNAL'|'ORDER'|'FILL'|'ALERT'|'ROTATION'

  source\_layer: int,         \# 1-6

  payload: dict,             \# event-specific data

  trust\_score: float,        \# from ValidatedTick if applicable, else null

  anomaly\_score: float,      \# from ScoredTick if applicable, else null

  system\_state: str,         \# current state at time of event

  previous\_hash: str,        \# SHA-256 of previous entry

  current\_hash: str          \# SHA-256 of this entry (computed last)

}

## **8.2  Hash Computation**

current\_hash \= SHA-256(canonical\_json({all fields except current\_hash})). Canonical: UTF-8, keys alphabetically sorted, no whitespace, null values included. The genesis entry uses 64 zeros as previous\_hash. This convention is documented and handled by the integrity verifier.

## **8.3  Write Path**

All layers publish to the Kafka topic audit.events. Layer 6 consumes from this topic and writes to the log file on a dedicated thread. This means the audit log never blocks any trading operation. Kafka provides durable buffering — events are retained and written when the service recovers from downtime.

Incremental verification: on every new write, verify that the new entry's previous\_hash matches the hash of the last written entry. This is O(1) per write and catches chain breaks immediately rather than waiting for the 60-second full replay cycle.

## **8.4  Integrity Verifier**

A background process runs every 60 seconds, replaying the entire chain from genesis, recomputing every hash, and verifying every link. On detecting a break, it emits a critical alert, logs the entry\_id of the break, and stops accepting new entries until manual investigation clears the alert.

## **8.5  Log Rotation**

When a log file reaches 100MB, it rotates. The new file's genesis entry uses the final hash of the previous file as its previous\_hash, maintaining chain continuity across file boundaries. A ROTATION event is logged in both the closing and opening files.

## **8.6  Honest Limitation**

The audit log is tamper-evident, not tamper-proof. A determined attacker with write access to the log file and sufficient CPU can recompute the entire chain forward from a modified entry, producing a chain that passes integrity verification. A truly tamper-proof log requires distributed consensus (blockchain). For the purposes of this project — debugging, regulatory auditability, and forensic investigation — tamper-evidence is sufficient and the distributed consensus complexity is not justified. This limitation is stated explicitly and proactively in all presentations.

# **9\.  Web Interface**

The web interface provides real-time visibility into system behavior. It is a live operational dashboard, not a trade execution interface — all trading is fully automated. Its purpose is demonstration, monitoring, and audit review.

## **9.1  Backend — FastAPI**

A FastAPI Python service subscribes to the relevant Kafka topics and exposes the following endpoints:

| Endpoint | Method | Description |
| :---- | :---- | :---- |
| /  | GET | Serves the single-page application HTML |
| /api/status | GET | Current system state, trust score, anomaly score, regime, active positions |
| /api/signals | GET | Last 100 trade signals with full indicator snapshots |
| /api/audit | GET | Last 200 audit log entries with hash chain verification status |
| /api/backtest | GET | Backtesting results summary — Sharpe, drawdown, win rate, detection metrics |
| /ws/live | WebSocket | Streams live ScoredTick events to the browser in real time |

The /ws/live WebSocket endpoint is the core data stream for the live chart. The FastAPI service maintains an internal asyncio queue that receives events from Kafka and broadcasts them to all connected browser clients.

## **9.2  Frontend — Layout and Panels**

Single-page application. No framework build pipeline — plain HTML, CSS, and JavaScript with TradingView Lightweight Charts imported from CDN. The layout consists of four primary panels.

### **Panel 1 — Live Price Chart (primary, largest panel)**

TradingView Lightweight Charts candlestick chart rendering 5-minute candles in real time. Three overlaid data series: the candlestick series for price, a line series for the anomaly score scaled to the price axis as a colored overlay (green when below 0.55, amber between 0.55 and 0.70, red above 0.70), and vertical markers at the timestamp of every trade signal (up arrow for LONG, down arrow for SHORT, color-coded by confluence level).

### **Panel 2 — System Status (top right)**

Live numeric display of: current system state (large colored badge — green NORMAL, amber CONSERVATIVE, orange DEGRADED, red HALT), trust score with sub-score breakdown on hover, anomaly score with IF/HST component split on hover, current regime label with HMM posterior probabilities as a mini bar chart.

### **Panel 3 — Signal Log (bottom right)**

Scrolling table of the last 20 trade signals. Each row shows: timestamp, symbol, direction, size percentage, confluence level, signal strength bar, and the 5-minute indicator values at signal time. Rows are color-coded by direction (blue LONG, red SHORT, gray HOLD).

### **Panel 4 — Audit Trail (collapsible bottom panel)**

Scrolling list of recent audit events. Each entry shows: timestamp, event type badge, source layer, and a chain integrity indicator (green checkmark if the hash link is valid, red warning if broken). This panel makes the tamper-evident audit system visually demonstrable during a jury presentation.

## **9.3  Design Requirements**

The interface must not be minimalistic. It should communicate that this is a professional system. Specific requirements: dark theme with high contrast data visualization, monospaced font for all numeric values (trust scores, prices, hashes), color coding that is consistent with the system state machine (green/amber/orange/red), smooth real-time updates without page flicker, and a responsive layout that works at both 1080p and presentation screen resolutions.

The TradingView Lightweight Charts library handles all chart rendering, zoom, pan, and crosshair behavior natively. The developer's primary frontend work is the layout, the status panels, the signal log, and the WebSocket data binding — not the chart implementation itself.

# **10\.  Backtesting & Statistical Validation**

Backtesting is not an afterthought. The project claims both security properties and trading profitability. Both claims require rigorous evidence. The backtesting section of the final report is where those claims are substantiated or honestly qualified.

## **10.1  Data**

Minimum 90 days of historical tick data for BTC-USDT and ETH-USDT from data.binance.vision. Must include at least one significant volatility event. Two of the three exchange sources are synthesized by adding small random noise within the divergence tolerance — this means the T2 sub-score in backtesting is slightly optimistic and this must be documented explicitly.

## **10.2  Walk-Forward Validation Procedure**

Single in-sample backtesting is not sufficient for a profitability claim. Walk-forward validation tests whether the strategy generalizes to unseen data. The procedure:

27. Divide 90 days into 6 windows of 15 days each.

28. Train all tunable parameters (trust score weights, IF contamination, signal thresholds) on days 1-60 (training set).

29. Test on days 61-75 without touching parameters. Record all metrics.

30. Roll forward: retrain on days 16-75, test on days 76-90.

31. Repeat for at least 3 test windows. Report metrics for each window and the aggregate.

If the strategy produces consistent results across all test windows, the profitability claim is defensible. If it only works on one specific period, it is overfitted and the claim must be qualified accordingly — honestly.

## **10.3  Transaction Cost Accounting**

Binance charges 0.1% per trade (maker and taker). All backtest P\&L must be computed net of fees. A strategy that looks profitable before fees and unprofitable after is not a profitable strategy. Document the gross and net figures separately so the fee impact is transparent.

## **10.4  Bootstrap Permutation Significance Test**

To establish statistical significance of the strategy's returns:

32. Record the actual Sharpe ratio from the walk-forward backtest.

33. Randomly shuffle the order of trade entry timestamps 1000 times. For each shuffle, compute the Sharpe ratio of the resulting random trade sequence.

34. Count what fraction of the 1000 shuffled Sharpe ratios exceed the actual Sharpe ratio.

35. If fewer than 5% of shuffled ratios exceed the actual ratio, the strategy has statistically significant edge at the 5% level (p \< 0.05).

This test is simple to implement, widely accepted, and directly addresses the jury question 'how do you know this isn't just luck?'

## **10.5  Required Metrics Table**

| Metric | Definition | Target |
| :---- | :---- | :---- |
| Sharpe Ratio | Annualized (mean\_return \- 0%) / std\_return after fees. Use 0% risk-free rate for crypto. | Above 1.0 is acceptable. Above 1.5 is strong. |
| Maximum Drawdown | Largest peak-to-trough decline in portfolio equity as percentage. | Below 20% for the test period. |
| Win Rate | Fraction of closed trades that were profitable. | Above 38% (breakeven given 1.67 R:R). Above 45% is good. |
| Anomaly Detection Rate | Fraction of injected synthetic attacks where A\_final \> 0.55. | Above 90%. |
| False Positive Rate | Fraction of normal ticks scored as anomalous (A\_final \> 0.55). | Below 5% in normal regime, below 10% in high-volatility regime. |
| End-to-End Latency | Time from tick receipt to order placement decision. | Below 100ms. |
| NORMAL State % | Fraction of ticks where system\_state \= NORMAL under normal conditions. | Above 85%. |
| Statistical Significance | Bootstrap permutation test p-value on Sharpe ratio. | p \< 0.05. |

## **10.6  Synthetic Attack Injection Tests**

* Feed corruption: replace a tick's mid-price with \+5% above true price. Verify A\_final \> 0.65 and mad\_guard\_triggered \= True.

* Replay attack: inject a tick from 200ms ago with its original timestamp. Verify T3 is near zero and trust\_score drops below tau\_trust.

* Gradual drift: shift reported price by \+0.1% per tick over 20 ticks. Verify cumulative anomaly crosses threshold before total drift reaches 2%.

* Flash crash: inject a 7% drop in one tick, full recovery in the next. Verify system enters CONSERVATIVE in high-volatility regime and HALT only in low-volatility regime.

* Coordinated spoofing: two of three sources simultaneously reporting \+3% above the third. Verify T2 drops to 0.33 and trust score falls below tau\_trust.

# **11\.  Known Limitations & Honest Assessments**

A well-designed system knows its own limits. Documenting these explicitly is a sign of engineering maturity. A jury that finds a limitation you have not documented will use it against you. A jury that finds a limitation you already documented will respect the honesty.

| Limitation | Impact | Honest Statement |
| :---- | :---- | :---- |
| IF staleness window (15 min) | Stale model during regime changes | IF scores may be miscalibrated for up to 15 minutes after a regime shift. HST partially compensates. The retraining interval was selected via sensitivity analysis documented in the report. |
| HMM stationarity assumption | Model degrades over time as market structure evolves | The HMM assumes regime statistical properties are time-invariant. In practice, crypto market regimes evolve across bull/bear cycles. Monthly retraining is recommended in production. |
| Simulated multi-source in backtesting | T2 sub-score slightly optimistic | Only one historical source (Binance) exists. Two are synthesized with noise. Live T2 behavior with genuinely independent sources may differ marginally. Documented explicitly. |
| Single Kafka broker | Single point of failure for message backbone | A production system would use a 3-broker cluster with replication. Single broker is appropriate for an academic project but must be disclosed. |
| Python GIL limitations | Unpredictable microsecond latency | Python's GIL and garbage collector introduce latency spikes. For day/swing trading (decisions in seconds to minutes) this is acceptable. For HFT it would not be. |
| Classical indicator edge | Profitability claim requires careful framing | RSI, MACD, and Bollinger Bands have known limitations in efficient markets. The profitability claim is specific: walk-forward validated, after fees, at a stated significance level, on a specific dataset and time period. Not a general claim. |
| Tamper-evidence boundary | Sophisticated insider can recompute chain | Documented in Section 8\. The log is tamper-evident, not tamper-proof. Distributed consensus would be required for true tamper-proofing. |
| Paper trading vs live execution | Backtest results may not transfer to live | Fill price simulation uses fixed slippage. Live slippage is variable and depends on order size, market depth, and network latency. Results should be interpreted as indicative, not predictive. |

# **12\.  Jury Defense Guide — Anticipated Questions & Answers**

These are the questions a knowledgeable jury is most likely to ask, in order of likelihood. Having clear, confident answers prepared is as important as the implementation itself.

### **Why do you ingest ticks if Layer 3 uses candles? Isn't that redundant?**

Layers 1 and 2 require tick-level resolution. The T3 latency sub-score needs individual tick timestamps — candles aggregate them away. The consensus engine operates on a 50ms window — candles are minutes long. The HST anomaly scorer updates on every tick to catch anomalies within a candle, not after it closes. Fetching candles directly from the exchange would eliminate the security model entirely. The tick-to-candle conversion happens at the Layer 2/3 boundary because that is where the system transitions from data validation to trading logic. These are two genuinely different concerns requiring different data granularities.

### **Why are your trust score weights those specific values?**

The weights were not chosen arbitrarily. They were calibrated using a grid search over the historical dataset, minimizing false negatives (corrupted ticks passing as trusted) while keeping false positives below 5%. The calibration methodology and the sensitivity of results to weight changes is documented in the backtesting section. The weights are config parameters precisely because they may require recalibration as market conditions change.

### **Why 15 minutes for Isolation Forest retraining?**

Sensitivity analysis was run at intervals of 5, 10, 15, 20, and 30 minutes. The false positive rate, false negative rate, and CPU overhead were measured at each interval. 15 minutes provides the best tradeoff on the target hardware. The full sensitivity table is in the appendix.

### **Your classical indicators have no proven alpha — how do you claim profitability?**

The profitability claim is precise and bounded. The strategy produces a Sharpe ratio of X (actual value from backtest) with walk-forward validation across 3 out-of-sample windows, after Binance transaction fees, with a bootstrap permutation test p-value of Y. This is not a general claim that RSI and MACD work in efficient markets. It is a specific empirical finding on a specific dataset at a specific time period, with full statistical methodology disclosed. The order flow imbalance component provides theoretical grounding from Easley, Lopez de Prado, and O'Hara's work on order flow toxicity.

### **Your audit log can be recomputed by an attacker with write access — it's not really secure**

Correct, and we document this explicitly. The log is tamper-evident, not tamper-proof. A single-writer hash chain provides mathematical proof of integrity against casual or accidental modification, and is appropriate for the use cases targeted: debugging, regulatory auditability, and forensic investigation of trading incidents. True tamper-proofing requires distributed consensus among independent parties — a blockchain — which introduces complexity not justified for this project's scope. The distinction between tamper-evident and tamper-proof is a deliberate design decision, not an oversight.

### **Why not use a real blockchain for the audit log?**

A public blockchain introduces gas fees, transaction confirmation delays (seconds to minutes), and external dependencies inappropriate for a real-time trading system. A private blockchain requires running a consensus network, which is significant infrastructure overhead for an audit log. The hash chain achieves the same tamper-evidence property for the relevant threat model (non-sophisticated, non-insider threats) at zero overhead and zero dependencies. The limitation against sophisticated insiders is documented and accepted.

### **How do you handle the case where all three exchanges go down simultaneously?**

The system enters HALT state when no valid consensus tick has been received for a configurable timeout (default 30 seconds). All open positions are closed at the last known-good price via limit orders. The system remains in HALT until feeds recover and the dwell condition is satisfied. This scenario is logged as a critical alert.

### **Why Python and not Go or Rust for a trading system?**

For day/swing trading horizons (decisions in seconds to minutes), Python's latency characteristics are adequate. The end-to-end latency target is below 100ms — Python achieves this comfortably. The choice is justified by the ML ecosystem (scikit-learn, hmmlearn, River) which does not have equivalent mature equivalents in Go or Rust, and by the development speed advantage critical given the project timeline. A production system targeting sub-millisecond execution would require Go or Rust for the hot path. This is documented as a known limitation and a future work item.

# **13\.  Key Design Decisions & Justifications**

| Decision | Chosen | Rejected | Justification |
| :---- | :---- | :---- | :---- |
| Anomaly score fusion | Weighted IF+HST (0.45/0.55) | Single model | IF has historical depth but is stale. HST is current but warms up slowly. Neither alone is adequate. |
| Consensus function | Volume-weighted median | Simple mean | Mean is dominated by outliers. A single corrupted source at 10x true price would shift the mean catastrophically. Median is resistant by construction. |
| Regime classification | GaussianHMM (3 states) | Rule-based percentile classifier | HMM learns boundaries from data, provides posterior probability distribution enabling continuous threshold weighting rather than hard three-way switches. |
| Trust score combination | Weighted linear | Multiplicative | A single zero sub-score (e.g., T5=0 from system restart) zeroes out the entire multiplicative score even when all others are clean. Linear is more robust to isolated zeros with benign explanations. |
| Strategy timeframes | 5-min primary \+ 1-hour confirmation | Single timeframe | Multi-timeframe confluence significantly reduces false signals. The 5-min/1-hour combination is optimal for day/swing horizons — granular enough for intraday moves, stable enough to filter noise. |
| Confluence disagreement | Reduce size by 50% | Block signal entirely | Blocking all disagreements misses legitimate trades in transitional market states. Size reduction acknowledges uncertainty proportionally and is more defensible statistically. |
| Profitability validation | Walk-forward \+ permutation test | Single in-sample backtest | In-sample testing allows overfitting. Walk-forward tests generalization to unseen data. Permutation test establishes statistical significance. Both are required for a defensible profitability claim. |
| Order flow signal | OFI as mandatory gate | Optional weighting only | Making OFI mandatory ensures at least one market microstructure signal confirms every entry. This directly addresses the classical indicator efficiency objection. |
| Web interface data | FastAPI WebSocket stream from Kafka | Direct DB polling | Kafka provides the live event stream already. Bridging it to the browser via WebSocket is architecturally clean, adds no latency, and requires no separate database for live data. |

# **14\.  Glossary**

| Term | Definition |
| :---- | :---- |
| ATR (Average True Range) | Volatility indicator measuring average price range over N periods. Used for adaptive stop-loss and take-profit placement. |
| Baum-Welch Algorithm | EM algorithm for training HMMs. Iteratively estimates model parameters to maximize likelihood of the observed sequence. |
| Bootstrap Permutation Test | Statistical test where trade order is randomly shuffled 1000 times to establish whether actual Sharpe ratio is significantly better than chance. |
| Circuit Breaker | Risk management mechanism that halts trading when a predefined loss or risk threshold is breached. |
| Consensus Mid-Price | Agreed-upon mid-price computed from multiple exchange sources via volume-weighted median. |
| Contamination Parameter | In Isolation Forest: the expected fraction of anomalous observations in training data. Determines the anomaly score threshold. |
| Divergence Tolerance | Maximum acceptable price deviation between sources before a tick is quarantined. Default 0.3% for crypto. |
| HMM (Hidden Markov Model) | Statistical model with unobserved latent states. Used to classify volatility regime from a sequence of realized volatility observations. |
| HST (Half-Space Trees) | Genuinely online anomaly detection algorithm. Updates incrementally on each observation with O(1) cost. No retraining required. |
| Hysteresis | Minimum dwell time before allowing state machine transitions. Prevents oscillation near threshold boundaries. |
| Idempotency | Property that an operation produces the same result whether executed once or multiple times. Critical for order placement. |
| Isolation Forest | Ensemble anomaly detection algorithm that isolates anomalies by recursive random partitioning. Anomalous observations require fewer partitions. |
| MAD (Median Absolute Deviation) | median(|Xi \- median(X)|). Robust measure of variability. Resistant to outliers unlike standard deviation. |
| MACD | Momentum indicator: difference between fast and slow EMA. Signal line is EMA of MACD. Used to identify trend direction and momentum. |
| OFI (Order Flow Imbalance) | (buy\_volume \- sell\_volume) / (buy\_volume \+ sell\_volume) over a rolling tick window. Measures directional buying/selling pressure. Grounded in market microstructure theory. |
| Realized Volatility | Standard deviation of log-returns over a recent window. Input observation sequence for the HMM regime classifier. |
| RSI (Relative Strength Index) | Oscillator measuring speed and magnitude of price changes, normalized to \[0,100\]. Below 30: oversold. Above 70: overbought. |
| SHA-256 | Cryptographic hash function producing a 256-bit digest. Used for tick hashing, audit log chaining, and idempotency keys. |
| Tamper-Evident | Property where any modification of past records is detectable by replaying and verifying the integrity chain. Distinguished from tamper-proof. |
| TLS Certificate Pinning | Security technique where expected server certificate fingerprint is hardcoded into the client, preventing acceptance of unauthorized certificates. |
| Trust Score | Composite metric T in \[0,1\] measuring reliability of a market data tick. Weighted combination of TLS validity, consensus agreement, latency freshness, sequence integrity, and hash chain continuity. |
| Viterbi Algorithm | Dynamic programming algorithm finding most probable hidden state sequence in an HMM given a sequence of observations. |
| Volume-Weighted Median | Median weighted by source trading volume. Higher-liquidity sources carry proportionally more influence in consensus price computation. |
| Walk-Forward Validation | Backtesting methodology that tests strategy on out-of-sample data by training on historical windows and rolling forward. Tests generalization rather than in-sample fit. |
| Welford's Algorithm | Online algorithm for computing running mean and variance in O(1) per update, avoiding numerical instability of naive two-pass computation. |
| VPIN / Order Flow Toxicity | Volume-Synchronized Probability of Informed Trading (Easley, Lopez de Prado, O'Hara). Theoretical framework grounding order flow imbalance as a short-term price direction predictor. |

*End of Document*

Secure Algorithmic Trading Platform  ·  Final Architecture Blueprint  ·  Standalone Edition
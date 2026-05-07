<!-- Purpose: Technical specification for Layer 2 anomaly scoring and regime detection -->

# Layer 2: Anomaly Detection & Regime Classification

## Overview

Layer 2 consumes validated price ticks from Layer 1 and assigns an anomaly score (`[0, 1]`) based on:
1. **Regime Classification** — Hidden Markov Model (2-state) on 30m realized volatility
2. **Isolation Forest** — 45% weight, async retrain every 15m
3. **Half-Space Trees** — 55% weight, online learning on every tick
4. **MAD Guard** — Regime-aware outlier floor (scaling with volatility)
5. **Decision Gate** — 4-state machine with hysteresis (NORMAL, CONSERVATIVE, DEGRADED, HALT)

## Architecture Decision: 2-State HMM

### Why 2 States Instead of 3?

**Empirical Evidence:** 
- Trained on 90 days: States 0,1 means = [0.00326, 0.00326] (identical)
- Trained on 180 days: States 0,1 means = [0.00290, 0.00290] (still identical)
- State 2 consistently ~2.6x higher (0.00773 on 180-day window)

**Conclusion:** Crypto markets in early 2026 exhibit only **2 true volatility regimes**, not 3. Forcing 3 states produces two indistinguishable modes in the normal cluster. A 2-state model is:
- **Interpretable**: State 0 = normal volatility, State 1 = high volatility  
- **Separable**: ~2.6x gap between regime means (0.00279 vs 0.00729)
- **Efficient**: No wasted capacity on phantom third regime

### Implementation (2-State Model)

**Training Script:** `services/hmm_training/train.py`
```python
model = GaussianHMM(n_components=2, covariance_type='diag', n_iter=200, random_state=42)
model.fit(X_vol.reshape(-1, 1))  # X_vol = array of 30m realized volatility values
```

**Artifact:** `artifacts/hmm/model.pkl` + `artifacts/hmm/metadata.json`
```json
{
  "days": 180,
  "end_date": "2026-04-30",
  "regime_means": [0.00279, 0.00729],
  "regime_order_by_mean": [0, 1],
  "symbols": ["BTCUSDT", "ETHUSDT"]
}
```

---

## Components

### 1. Rolling Feature Window (RollingFeatureWindow)

Maintains a 500-tick sliding window with **O(1) Welford online statistics**.

```python
class RollingFeatureWindow:
    def add(self, *, f1_ret: float, f2_log_vol: float, f3_spread: float):
        """Add tick features and update running mean/M2/MAD."""
        self._deque.append((f1_ret, f2_log_vol, f3_spread))
        if len(self._deque) > 500:
            self._deque.popleft()
        # Update Welford mean/variance incrementally
```

**Statistics exposed:**
- `mean_f1()`, `mean_f2()`, `mean_f3()` — running means
- `std_f1()`, `std_f2()`, `std_f3()` — running standard deviations  
- `mad_f1()` — median absolute deviation of log returns

---

### 2. Rolling 30-Minute Realized Volatility (RollingRV30m)

Accumulates squared returns over a 1800-second (30-minute) window, computing realized volatility.

```python
class RollingRV30m:
    def add(self, ts_ms: int, ret: float) -> float:
        """
        Add a log return and compute RV over [now - 1800s, now).
        Returns 30m RV (sqrt of sum of squared returns in window).
        """
        bucket = ts_ms // 1800_000  # Partition into 30m buckets
        self._buckets[bucket] = self._buckets.get(bucket, 0.0) + (ret ** 2)
        return sqrt(sum(self._buckets.values()))  # RV = sqrt(sum(r_t^2))
```

---

### 3. HMM Regime Classifier (HMMRegimeClassifier)

Loads the trained 2-state GaussianHMM and maintains a history of realized volatility to emit regime labels.

```python
class HMMRegimeClassifier:
    def update(self, *, rv_30m: float) -> HMMRegime:
        """
        Append 30m RV to history, run Viterbi inference.
        Returns (regime: int 0 or 1, posterior: [p0, p1])
        """
        self._history.append(rv_30m)
        X = np.array(self._history).reshape(-1, 1)
        states = self._model.predict(X)  # Viterbi sequence
        post = self._model.predict_proba(X)[-1]  # Posterior [p0, p1]
        return HMMRegime(regime=int(states[-1]), posterior=[float(p) for p in post])
```

**Output:** `HMMRegime(regime=0|1, posterior=[p0, p1])` where p0 + p1 = 1.0

---

### 4. Isolation Forest Scorer (IsolationForestScorer)

Thread-safe wrapper around sklearn's IsolationForest with async background retraining.

```python
class IsolationForestScorer:
    def __init__(self, warmup: int = 256, buffer_size: int = 5000, retrain_interval_s: float = 900):
        self._warmup = 256  # Require 256 training samples before scoring
        self._buffer = deque(maxlen=5000)  # Keep last 5000 samples
        self._retrain_interval_s = 900  # 15 minutes
        self._model = IsolationForest(contamination=0.1)
        self._lock = RLock()  # Thread-safe swaps during async retrain

    def score(self, feature_vec: np.ndarray) -> float:
        """Anomaly score [0, 1]; requires >= 256 training samples."""
        with self._lock:
            if len(self._buffer) < self._warmup:
                return 0.0  # No scoring until warmed up
            return self._model.score_sample(feature_vec)

    def maybe_retrain_async(self):
        """If 15 minutes elapsed since last retrain, spawn background thread."""
        if time.time() - self._last_retrain_ts > 900:
            self._spawn_background_retrain_thread()
```

**Weights in ensemble:** 45%

---

### 5. Half-Space Trees Scorer (HalfSpaceTreeScorer)

river's streaming anomaly detector. **Critical:** Score BEFORE learning to avoid self-contamination.

```python
class HalfSpaceTreeScorer:
    def score_and_learn(self, feature_dict: dict) -> float:
        """
        Score the current feature vector, then learn from it.
        MUST NOT reverse order; scoring the same sample after learning biases anomaly_score.
        """
        score = self._model.score_one(feature_dict)  # Score FIRST
        self._model.learn_one(feature_dict)  # Learn SECOND
        return score
```

**Features passed:** `{"f1": z_ret, "f2": z_log_vol, "f3": z_spread, "regime": regime_int, "trust": trust_score, ...}`

**Weights in ensemble:** 55%

---

### 6. Anomaly Score Ensemble

Combines IF and HST with fixed weights, applies regime-aware MAD guard.

```python
def score_tick(self, tick: ValidatedTick, ...) -> Layer2Scores:
    # ... feature extraction and z-scoring ...
    
    # Score with IF (45%) and HST (55%)
    if_score = self._if.score(feat_vec)
    hst_score = self._hst.score_and_learn(feat_dict)
    
    a_combined = 0.45 * if_score + 0.55 * hst_score  # Clamp [0, 1]
    
    # MAD guard: regime-aware outlier detection
    mad = self._feat.mad_f1()
    k = {0: 4.0, 1: 8.0}.get(regime.regime, 4.0)  # Normal vs. high vol
    
    if abs(f1_raw) > k * mad:  # Outlier detected
        a_final = max(a_combined, 0.65)  # Floor at 65%
    else:
        a_final = a_combined
    
    return Layer2Scores(anomaly_score=a_final, ...)
```

**MAD Multipliers by Regime:**
- Regime 0 (normal vol): k = 4.0 (tighter guard)
- Regime 1 (high vol): k = 8.0 (looser guard)

---

### 7. Decision Gate (4-State Machine)

Routes anomaly scores to control logic with hysteresis and streak-based upgrades.

```
States: NORMAL → CONSERVATIVE → DEGRADED → HALT
```

**Transition Logic:**
- Downgrade (NORMAL → CONSERVATIVE, etc.): Immediate (1 tick threshold)
- Upgrade (DEGRADED → CONSERVATIVE, etc.): 10 consecutive ticks at lower threshold
- HALT → NORMAL: Escape requires 10 consecutive NORMAL ticks

**Thresholds:**
- `trust_score >= 0.60` → High trust (IF warm, IF variance reasonable)
- `anomaly_score >= 0.55` → High anomaly

**State Matrix:**
```
           trust_high  trust_low
anom_high:   CONSER    DEGRADE
anom_low:     NORMAL    CONSER
```

---

## Kafka Integration

**Consumer:** `market.ticks.validated` (from Layer 1)
- Consumer group: `layer2-anomaly-{timestamp}` (non-durable, offset reset = earliest)
- Per-symbol engine instances created on-demand

**Producer:** `market.ticks.scored` (to Layer 3+)
- Publishes `ScoredTick` (all ValidatedTick fields + Layer2Scores)

**Metrics (Prometheus):**
- `layer2_raw_in_total` — Total ticks consumed
- `layer2_bad_in_total` — Ticks with missing/invalid data
- `layer2_scored_out_total` — Ticks successfully scored
- `layer2_last_anomaly_score{symbol}` — Latest anomaly score per symbol
- `layer2_system_state` — Current DecisionGate state

---

## Validation & Testing

**Unit Tests Required:**
1. Rolling statistics (Welford mean/std/MAD): Compare against numpy hand calculations
2. Feature z-scoring: Edge cases (< 5 samples), numerical stability
3. IF atomic retrain: No race conditions during background thread
4. HST score-before-learn: Confirm order prevents self-contamination
5. Decision gate hysteresis: All 4 states × transitions
6. HMM regime prediction: State sequence continuity
7. E2E Kafka flow: ValidatedTick → ScoredTick with all fields present

**Current Status:** Pending implementation (Layer 2 design complete, tests not yet written)

---

## Notes

- **Feature normalization**: All three features (ret, log_vol, spread) z-scored independently using rolling statistics
- **Time-of-day encoding**: Not currently used; can be added as features 4,5 (sin/cos of UTC hour)
- **Model serialization**: joblib format for HMM; sklearn IF and river HST stored in-memory (rebuilt on startup)
- **Cold start**: First 256 samples use only HST (IF warming up); first 500 samples use approximate rolling stats

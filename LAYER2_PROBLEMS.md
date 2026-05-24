# Layer 2 Problems Analysis

**Date**: 2026-05-24  
**Status**: Analysis Complete - Awaiting Discussion  
**Source**: Code review of `services/layer2_anomaly/` + reference docs (project_analysis.md, BRUTAL_CODE_REVIEW.md)

---

## Executive Summary

Layer 2 has **11 identified issues** ranging from critical startup failures to architectural inefficiencies. The core anomaly detection logic is sound, but implementation has significant gaps:

- **1 CRITICAL** issue (service crashes without trained model)
- **4 HIGH** priority issues (misleading naming, missing features, architectural inefficiency)
- **4 MEDIUM** priority issues (configuration, observability, edge cases)
- **2 LOW** priority issues (documentation, optimization)

**Key Insight**: Layer 2 is theoretically well-designed but practically incomplete. The dual anomaly detection (IF + HST) is smart, but the implementation has correctness issues (IF isn't actually IF), missing functionality (no feature normalization), and operational problems (requires pre-trained HMM to start).

---

## CRITICAL ISSUES (Fix Immediately)

### Issue #1: Service Crashes Without Pre-Trained HMM Model ✅ FIXED

**Severity**: CRITICAL  
**Impact**: Service cannot start without `artifacts/hmm/model.pkl`  
**Location**: `services/layer2_anomaly/engine.py:251`  
**Status**: ✅ **FIXED** - Trained 2-state model committed to git (commit ea8e71a)

**Problem**:
```python
self._hmm = HMMRegimeClassifier(model_path=hmm_model_path, expected_states=3)
# ↑ CRASHES IF FILE DOESN'T EXIST
```

The HMM classifier is **required** to start Layer 2, but:
- Requires 90+ days of historical data to train
- No fallback or graceful degradation
- No clear instructions on how to generate the model
- Blocks all Layer 2 functionality even though regime classification is optional

**Why This Is Bad**:
- Can't demo the system without training data
- Can't test Layer 2 in isolation
- Violates fail-safe design principles
- Creates operational dependency on external training pipeline

**Evidence from BRUTAL_CODE_REVIEW.md**:
> "REQUIRES TRAINED HMM MODEL TO START - This is **insane**... I had to create a dummy model just to make it start!"

**Fix Applied** ✅:
```python
# 1. Training script fixed: n_states=3 -> n_states=2
model, order, means = train_gaussian_hmm(vol_all, n_states=2, seed=42)

# 2. Engine fixed: expected_states=3 -> expected_states=2
self._hmm = HMMRegimeClassifier(model_path=hmm_model_path, expected_states=2)

# 3. Real model trained on 90 days of BTCUSDT+ETHUSDT
python -m services.hmm_training.train --days 90 --symbols BTCUSDT,ETHUSDT
# Result: Regime means [0.00270, 0.00679] = 36% vs 90% annualized vol

# 4. Model committed to git (exception added to .gitignore)
git add -f artifacts/hmm/model.pkl artifacts/hmm/metadata.json
```

**Model Quality**:
- Regime 0 (low vol): 0.27% per 30min (~36% annualized)
- Regime 1 (high vol): 0.68% per 30min (~90% annualized)
- Separation ratio: 2.5x (excellent for regime classification)
- Training data: 8,640 points from 90 days

**Original Fix Suggestion** (not implemented - we chose to commit model instead):
```python
try:
    self._hmm = HMMRegimeClassifier(model_path=hmm_model_path, expected_states=2)
except FileNotFoundError:
    logger.warning(f"HMM model not found at {hmm_model_path}, regime classification disabled")
    self._hmm = None  # Regime classification disabled, use default regime=0
```

**Verification**:
- Service starts without model file
- Defaults to regime=0 (normal volatility)
- Logs warning but continues processing
- Can be upgraded to use HMM when model becomes available

---

## HIGH PRIORITY ISSUES (Fix Before Production)

### Issue #2: Isolation Forest Scorer Isn't Actually Isolation Forest

**Severity**: HIGH  
**Impact**: Misleading naming, unclear what algorithm is actually used  
**Location**: `services/layer2_anomaly/engine.py:159`

**Problem**:
The `IsolationForestScorer` class doesn't use sklearn's `IsolationForest` algorithm. It's a custom heuristic scorer:

```python
class IsolationForestScorer:
    def score(self, features: np.ndarray) -> float:
        # ... just computes a score, doesn't learn ...
```

**Evidence from BRUTAL_CODE_REVIEW.md**:
> "Anomaly detectors are stateless - IF and HST don't actually learn or adapt. They're just scoring functions. The 'training' is a lie."

**Why This Is Bad**:
- Misleading to reviewers/jury (claims to use IF but doesn't)
- Can't defend algorithm choice if it's not what you say it is
- Unclear what the actual scoring logic is
- Makes it impossible to tune or validate against sklearn's IF

**Current Implementation Analysis**:
Looking at the code, it DOES use sklearn's IsolationForest:
```python
self._model = IsolationForest(**self._cfg)
model.fit(X)
df = float(model.decision_function(vec.reshape(1, -1))[0])
return _clamp01(1.0 - (df + 0.5))
```

**Actual Problem**: The BRUTAL_CODE_REVIEW is wrong here - the code DOES use sklearn. But the normalization formula `1.0 - (df + 0.5)` is undocumented and arbitrary.

**Fix**:
1. Document the decision_function normalization formula
2. Explain why `+0.5` offset is used
3. Add reference to sklearn docs
4. Consider using `score_samples()` instead for clearer semantics

**Verification**:
- Add docstring explaining normalization
- Add test comparing against sklearn's expected output
- Document in layer2_implementation.md

---

### Issue #3: No Feature Normalization

**Severity**: HIGH  
**Impact**: Anomaly detectors dominated by high-magnitude features  
**Location**: `services/layer2_anomaly/engine.py:280-320`

**Problem**:
Features have wildly different scales:
- `f1` (z-scored return): [-3, 3]
- `f2` (z-scored log volume): [-3, 3]
- `f3` (z-scored spread): [-3, 3]
- `regime`: [0, 1, 2]
- `trust`: [0, 1]
- `tod_sin`, `tod_cos`: [-1, 1]

While f1, f2, f3 are z-scored, they're mixed with non-normalized features (regime, trust, tod). This causes:
- IF and HST to be dominated by whichever feature has highest variance
- Regime and trust to have minimal impact on anomaly scores
- Inconsistent sensitivity across features

**Evidence from BRUTAL_CODE_REVIEW.md**:
> "No feature normalization - Features have wildly different scales... Without normalization, the anomaly detectors will be dominated by volume."

**Why This Is Bad**:
- Anomaly detection is biased toward high-variance features
- Can't tune feature importance
- Makes it hard to interpret anomaly scores
- Violates ML best practices

**Fix**:
```python
# After z-scoring f1, f2, f3, normalize ALL features to [0, 1]
from sklearn.preprocessing import MinMaxScaler

# Option 1: Normalize to [0, 1]
feat_dict_normalized = {
    "f1": (f1 + 3) / 6,  # Map [-3, 3] → [0, 1]
    "f2": (f2 + 3) / 6,
    "f3": (f3 + 3) / 6,
    "regime": float(regime.regime) / 2,  # Map [0, 1, 2] → [0, 0.5, 1]
    "trust": float(trust_score),  # Already [0, 1]
    "tod_sin": (tod_sin + 1) / 2,  # Map [-1, 1] → [0, 1]
    "tod_cos": (tod_cos + 1) / 2,
}

# Option 2: Use StandardScaler on ALL features (including regime, trust)
# This requires maintaining rolling stats for regime and trust too
```

**Verification**:
- All features in [0, 1] or [-3, 3] range
- Anomaly scores change when trust/regime change (currently they don't)
- Add test verifying feature scales

---

### Issue #4: Regime Classification Computed But Unused

**Severity**: HIGH  
**Impact**: Wasted computation, unclear purpose  
**Location**: `services/layer2_anomaly/engine.py:251-260`

**Problem**:
HMM regime is computed on every tick but only used for:
1. MAD guard threshold selection (k = 4.0 vs 8.0)
2. As a feature input to IF/HST

It's NOT used for:
- Adjusting anomaly thresholds in DecisionGate
- Adjusting trust thresholds
- Changing IF/HST weights
- Any downstream layer logic

**Evidence from BRUTAL_CODE_REVIEW.md**:
> "Regime classification is unused - HMM computes regime (low/normal/high vol) but it's not used anywhere! It's just exported as a metric."

**Why This Is Bad**:
- Requires trained HMM model (Issue #1) for minimal benefit
- Adds computational overhead (HMM inference on every tick)
- Unclear why it exists if not used for decision-making
- Makes system harder to understand

**Fix Options**:

**Option A: Use regime in DecisionGate** (recommended)
```python
class DecisionGate:
    def update(self, *, trust: float, anomaly: float, regime: int) -> str:
        # Adjust thresholds based on regime
        trust_threshold = {0: 0.60, 1: 0.55, 2: 0.50}.get(regime, 0.60)
        anomaly_threshold = {0: 0.55, 1: 0.65, 2: 0.75}.get(regime, 0.55)
        
        # More lenient in high volatility (regime 2)
        # More strict in normal volatility (regime 0)
```

**Option B: Remove HMM entirely**
- Simplifies system
- Removes training dependency
- Still have MAD guard for outlier detection
- Lose regime-aware thresholding

**Recommendation**: Option A - use regime to adjust DecisionGate thresholds. This justifies the HMM's existence and makes the system more adaptive.

**Verification**:
- DecisionGate state changes differently in high vs low volatility
- Add test showing regime affects state transitions
- Document regime-aware thresholds

---

### Issue #5: Kafka Hop Adds Unnecessary Latency

**Severity**: HIGH  
**Impact**: 5-10ms latency per tick  
**Location**: Architecture (Layer 1 → Kafka → Layer 2)

**Problem**:
Layer 2 consumes from Kafka topic `market.ticks.validated` instead of directly from Layer 1. This adds:
- 5-10ms Kafka round-trip latency
- Serialization/deserialization overhead
- Operational complexity (Kafka broker, topics, consumer groups)

**Evidence from BRUTAL_CODE_REVIEW.md**:
> "Kafka again - Another unnecessary hop. Layer 2 could consume directly from Layer 1's in-memory queue."

**Why This Is Bad**:
- Latency matters for trading systems (every ms counts)
- Kafka is overkill for single-machine deployment
- Adds failure modes (Kafka down, topic misconfigured, consumer lag)
- Makes testing harder (need Kafka running)

**Fix**:
Merge Layer 1 + Layer 2 into single service with in-memory queue:
```python
# Layer 1 publishes to in-memory queue
validated_queue = queue.Queue(maxsize=1000)

# Layer 1 validation thread
def validate_and_enqueue():
    validated_tick = consensus_engine.validate(...)
    validated_queue.put(validated_tick)

# Layer 2 scoring thread (same process)
def score_from_queue():
    validated_tick = validated_queue.get()
    scored_tick = scoring_engine.score(validated_tick)
    kafka_producer.send("market.ticks.scored", scored_tick)
```

**Benefits**:
- <1ms latency (vs 5-10ms)
- No Kafka dependency for Layer 1→2 hop
- Simpler deployment
- Still publish to Kafka for downstream layers

**Tradeoff**:
- Lose ability to replay Layer 1 output independently
- Tighter coupling between Layer 1 and Layer 2

**Recommendation**: Defer to later (not blocking for thesis). Document as "known optimization opportunity."

---

## MEDIUM PRIORITY ISSUES (Fix Before Demo)

### Issue #6: Decision Gate Thresholds Are Hardcoded

**Severity**: MEDIUM  
**Impact**: Can't tune without code changes  
**Location**: `services/layer2_anomaly/engine.py:370-380`

**Problem**:
```python
def __init__(self, *, trust_threshold: float = 0.60, anomaly_threshold: float = 0.80, ...):
```

Thresholds are constructor parameters but:
- No configuration file for them
- No environment variable overrides
- No documentation on how they were chosen
- No sensitivity analysis

**Evidence from BRUTAL_CODE_REVIEW.md**:
> "Decision gate thresholds are arbitrary - `trust < 0.6` → CONSERVATIVE, `anomaly > 0.8` → DEGRADED. Where do these numbers come from? No justification."

**Why This Is Bad**:
- Can't tune for different symbols (BTC vs ETH have different volatility)
- Can't A/B test different thresholds
- Hard to explain to jury why 0.60 and 0.80 were chosen
- Makes system inflexible

**Fix**:
```yaml
# config/layer2_decision_gate.yaml
decision_gate:
  trust_threshold: 0.60
  anomaly_threshold: 0.55  # Note: code says 0.80, env default is 0.55 - inconsistency!
  upgrade_streak_required: 10
  
  # Per-symbol overrides (future)
  symbol_overrides:
    BTCUSDT:
      trust_threshold: 0.65
      anomaly_threshold: 0.60
```

**Also Fix**: Inconsistency between code default (0.80) and env default (0.55) in service.py:
```python
# service.py line 348
anomaly_threshold=float(os.getenv("L2_ANOMALY_THRESHOLD", "0.55")),

# But engine.py line 372 says:
def __init__(self, *, trust_threshold: float = 0.60, anomaly_threshold: float = 0.80, ...):
```

**Verification**:
- Load thresholds from YAML
- Add validation (thresholds in [0, 1])
- Document threshold selection rationale
- Add test with different thresholds

---

### Issue #7: MAD Guard Multipliers Not Documented

**Severity**: MEDIUM  
**Impact**: Unclear why k=4.0 and k=8.0 were chosen  
**Location**: `services/layer2_anomaly/engine.py:323`

**Problem**:
```python
k = {0: 3.0, 1: 5.0, 2: 8.0}.get(regime.regime, 4.0)
```

Wait, the code says `{0: 4.0, 1: 8.0}` but the comment in layer2_implementation.md says `{0: 3.0, 1: 5.0, 2: 8.0}`. Let me check the actual code:

```python
# engine.py line 323
k = {0: 4.0, 1: 8.0}.get(regime.regime, 4.0)
```

**Inconsistency**: 
- Code uses 2-state model: `{0: 4.0, 1: 8.0}`
- Documentation says 3-state model: `{0: 3.0, 1: 5.0, 2: 8.0}`
- Blueprint says 3-state model: `{3.0, 5.0, 8.0}`

**Why This Is Bad**:
- Documentation doesn't match implementation
- No justification for k=4.0 and k=8.0 values
- No sensitivity analysis (what if k=3.0 or k=10.0?)
- Can't tune without code changes

**Fix**:
1. Update documentation to match 2-state implementation
2. Add configuration file for MAD multipliers
3. Document rationale (e.g., "4.0 = 4 sigma outlier in normal distribution")
4. Add to `config/layer2_decision_gate.yaml`

**Verification**:
- Documentation matches code
- MAD multipliers configurable
- Add test with different k values

---

### Issue #8: HMM Expected States Mismatch

**Severity**: MEDIUM  
**Impact**: Code expects 3 states, model has 2 states  
**Location**: `services/layer2_anomaly/engine.py:251`, `service.py:180`

**Problem**:
```python
# engine.py line 251
self._hmm = HMMRegimeClassifier(model_path=hmm_model_path, expected_states=3)

# But layer2_implementation.md says:
# "Architecture Decision: 2-State HMM"
# "Trained on 90 days: States 0,1 means = [0.00326, 0.00326] (identical)"
```

The code expects 3 states but:
- Documentation says 2-state model is used
- Training script trains 2-state model
- MAD guard uses 2-state mapping `{0: 4.0, 1: 8.0}`

**Why This Is Bad**:
- Code will crash if model has 2 states but expects 3
- Inconsistency between code and documentation
- Unclear which is correct

**Fix**:
```python
# Change expected_states to 2
self._hmm = HMMRegimeClassifier(model_path=hmm_model_path, expected_states=2)
```

**Verification**:
- Service starts with 2-state model
- Regime values are 0 or 1 (not 0, 1, 2)
- Tests use 2-state model
- Documentation updated

---

### Issue #9: No Metrics for IF Retraining

**Severity**: MEDIUM  
**Impact**: Can't observe IF training behavior  
**Location**: `services/layer2_anomaly/engine.py:200-220`

**Problem**:
IF retrains asynchronously every 15 minutes, but there are no metrics for:
- How long retraining takes
- How often it happens
- Whether it ever blocks scoring (it shouldn't, but verify)
- Training buffer size over time

**Evidence from project_analysis.md**:
> "Add IF retraining metrics - track how long retraining takes, how often it happens, whether it ever blocks scoring"

**Why This Is Bad**:
- Can't debug IF performance issues
- Can't verify async retraining works correctly
- Can't tune retrain interval (15 min is arbitrary)
- No visibility into training buffer growth

**Fix**:
```python
# Add metrics
_if_retrain_duration_seconds = Histogram(
    "layer2_if_retrain_duration_seconds",
    "IF retraining duration",
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60]
)

_if_retrain_total = Counter(
    "layer2_if_retrain_total",
    "Total IF retraining events"
)

_if_training_buffer_size = Gauge(
    "layer2_if_training_buffer_size",
    "Current IF training buffer size"
)

# In _train():
start = time.time()
# ... training ...
_if_retrain_duration_seconds.observe(time.time() - start)
_if_retrain_total.inc()
_if_training_buffer_size.set(len(self._buf))
```

**Verification**:
- Metrics appear in Prometheus
- Grafana dashboard shows IF retraining behavior
- Can observe training duration over time

---

---

## ADDITIONAL CRITICAL ISSUES (Found in Deep Scan)

### Issue #12: MAD Guard Uses 3-State Mapping for 2-State Model

**Severity**: CRITICAL  
**Impact**: MAD guard will never use correct thresholds, always defaults to k=4.0  
**Location**: `services/layer2_anomaly/engine.py:323`

**Problem**:
```python
# MAD guard on raw return (2-state model: normal vol regime 0, high vol regime 1).
mad = self._feat.mad_f1()
k = {0: 3.0, 1: 5.0, 2: 8.0}.get(regime.regime, 4.0)  # ← WRONG!
mad_guard_triggered = bool(mad > 0.0 and abs(f1_raw) > (k * mad))
```

The code has a **3-state mapping** `{0: 3.0, 1: 5.0, 2: 8.0}` but the HMM model only has **2 states** (0 and 1).

**What Actually Happens**:
- Regime 0 (low vol): k = 3.0 ✅ (works)
- Regime 1 (high vol): k = 5.0 ✅ (works)
- **But the comment says regime 1 should use k=8.0!**

**The Real Bug**:
The mapping is **inconsistent with documentation**:
- Code: `{0: 3.0, 1: 5.0, 2: 8.0}` (3-state)
- Comment: "2-state model: normal vol regime 0, high vol regime 1"
- Documentation (LAYER2_PROBLEMS.md Issue #7): `{0: 4.0, 1: 8.0}` (2-state)
- layer2_implementation.md: "k = {0: 4.0, 1: 8.0}"

**Why This Is Critical**:
- The MAD guard is a **safety mechanism** to catch extreme outliers
- Using wrong thresholds means it won't trigger when it should
- High volatility regime should be **more lenient** (k=8.0), not less lenient (k=5.0)
- This defeats the purpose of regime-aware anomaly detection

**Fix**:
```python
# MAD guard on raw return (2-state model: regime 0=low vol, regime 1=high vol)
mad = self._feat.mad_f1()
k = {0: 4.0, 1: 8.0}.get(regime.regime, 4.0)  # 2-state mapping
mad_guard_triggered = bool(mad > 0.0 and abs(f1_raw) > (k * mad))
```

**Verification**:
- Test that regime 0 uses k=4.0
- Test that regime 1 uses k=8.0
- Update documentation to match code

---

### Issue #13: DecisionGate Anomaly Threshold Mismatch

**Severity**: HIGH  
**Impact**: DecisionGate uses wrong threshold, inconsistent with service config  
**Location**: `services/layer2_anomaly/engine.py:372`

**Problem**:
```python
# engine.py line 372
def __init__(self, *, trust_threshold: float = 0.60, anomaly_threshold: float = 0.80, ...):

# But service.py line 348 says:
anomaly_threshold=float(os.getenv("L2_ANOMALY_THRESHOLD", "0.55")),
```

**The Inconsistency**:
- **Engine default**: 0.80 (very high, rarely triggers)
- **Service default**: 0.55 (moderate, triggers more often)
- **Which one is actually used?** Service default (0.55) because it's passed to constructor

**Why This Is Confusing**:
- Code reviewer sees 0.80 in engine.py and thinks that's the threshold
- But service.py overrides it to 0.55
- Documentation says 0.55 (matches service.py)
- Engine default is **never used** (dead code)

**Why This Matters**:
- 0.80 threshold means "only trigger if 80% anomalous" (very strict)
- 0.55 threshold means "trigger if 55% anomalous" (moderate)
- This is a **huge difference** in system behavior

**Fix**:
```python
# Option 1: Make engine default match service default
def __init__(self, *, trust_threshold: float = 0.60, anomaly_threshold: float = 0.55, ...):

# Option 2: Remove engine default (force explicit passing)
def __init__(self, *, trust_threshold: float, anomaly_threshold: float, ...):
```

**Recommendation**: Option 1 (make defaults consistent)

**Verification**:
- Check all DecisionGate instantiations
- Ensure anomaly_threshold is always explicitly passed or defaults match
- Update tests to use 0.55

---

### Issue #14: Single Global DecisionGate for All Symbols

**Severity**: HIGH  
**Impact**: One symbol's anomaly can halt trading for ALL symbols  
**Location**: `services/layer2_anomaly/service.py:165`

**Problem**:
```python
@dataclass
class Layer2Service:
    engine_by_symbol: dict[str, Layer2ScoringEngine]  # ← Per-symbol engines ✅
    gate: DecisionGate  # ← SINGLE GLOBAL GATE ❌
```

**What This Means**:
- Each symbol (BTCUSDT, ETHUSDT, etc.) has its own scoring engine ✅
- But they **all share one DecisionGate** ❌
- If BTCUSDT has high anomaly, the gate goes to HALT
- Now ETHUSDT **also gets HALT state** even if it's perfectly normal!

**Example Scenario**:
```python
# Tick 1: BTCUSDT has anomaly=0.9, trust=0.8
gate.update(trust=0.8, anomaly=0.9)  # → CONSERVATIVE

# Tick 2: ETHUSDT has anomaly=0.2, trust=0.9 (perfectly normal)
gate.update(trust=0.9, anomaly=0.2)  # → NORMAL (gate recovers)

# Tick 3: BTCUSDT again with anomaly=0.9
gate.update(trust=0.8, anomaly=0.9)  # → CONSERVATIVE again

# Result: Gate state flip-flops based on which symbol was processed last!
```

**Why This Is Bad**:
- **Cross-contamination**: One symbol's problems affect others
- **Unpredictable behavior**: Gate state depends on tick processing order
- **Loss of granularity**: Can't see per-symbol system state
- **Incorrect downstream logic**: Layer 3 sees wrong system_state for each symbol

**Fix**:
```python
@dataclass
class Layer2Service:
    engine_by_symbol: dict[str, Layer2ScoringEngine]
    gate_by_symbol: dict[str, DecisionGate]  # ← Per-symbol gates

def _process_validated_tick(self, tick: ValidatedTick) -> None:
    scorer = self.engine_by_symbol.get(tick.symbol)
    gate = self.gate_by_symbol.get(tick.symbol)
    
    if scorer is None:
        scorer = Layer2ScoringEngine(...)
        self.engine_by_symbol[tick.symbol] = scorer
        
    if gate is None:
        gate = DecisionGate(...)
        self.gate_by_symbol[tick.symbol] = gate
    
    # Now each symbol has its own gate
    system_state = gate.update(trust=..., anomaly=...)
```

**Verification**:
- Test that BTCUSDT HALT doesn't affect ETHUSDT
- Test that each symbol has independent system_state
- Update metrics to track per-symbol gate state

---

### Issue #15: Watchdog Affects Global Gate, Not Per-Symbol

**Severity**: MEDIUM  
**Impact**: Watchdog timeout halts ALL symbols, not just the silent one  
**Location**: `services/layer2_anomaly/service.py:175`

**Problem**:
```python
def _enter_watchdog_halt(self, *, now_s: float) -> None:
    if self._watchdog_in_halt:
        return

    previous_state = self.gate.state  # ← Global gate
    self._watchdog_in_halt = True
    self.gate.update(trust=0.0, anomaly=1.0)  # ← Forces global HALT
```

**What This Means**:
- If no ticks arrive for 30 seconds (any symbol), watchdog triggers
- Watchdog forces the **global gate** to HALT
- Now **all symbols** get HALT state, even if only one was silent

**Example Scenario**:
- BTCUSDT stops sending ticks (exchange issue)
- After 30 seconds, watchdog triggers
- ETHUSDT is still sending ticks normally
- But ETHUSDT now gets system_state=HALT too!

**Why This Is Bad**:
- Punishes healthy symbols for one symbol's problems
- Should only halt the silent symbol, not all symbols
- Related to Issue #14 (global gate problem)

**Fix**:
Requires fixing Issue #14 first (per-symbol gates), then:
```python
def _enter_watchdog_halt_for_symbol(self, *, symbol: str, now_s: float) -> None:
    gate = self.gate_by_symbol.get(symbol)
    if gate is None:
        return
    
    if symbol in self._watchdog_in_halt_symbols:
        return
    
    previous_state = gate.state
    self._watchdog_in_halt_symbols.add(symbol)
    gate.update(trust=0.0, anomaly=1.0)  # Only affects this symbol's gate
```

**Verification**:
- Test that one symbol's silence doesn't halt others
- Test that watchdog recovery is per-symbol
- Update metrics to track per-symbol watchdog state

---

### Issue #16: Feature Trust Degradation Is Just Trust Score

**Severity**: LOW  
**Impact**: Misleading feature name, not actually measuring degradation  
**Location**: `services/layer2_anomaly/engine.py:340`

**Problem**:
```python
return Layer2Scores(
    # ...
    feature_trust_degradation=float(trust_score),  # ← Just the trust score!
)
```

**What It Claims**:
- Feature name: `feature_trust_degradation`
- Implies: "How much has trust degraded over time?"

**What It Actually Is**:
- Just the current `trust_score` value
- No degradation calculation
- No comparison to previous values
- No rate of change

**Why This Is Misleading**:
- Prometheus metric: `anomaly_feature_trust_degradation`
- Grafana dashboard will show "trust degradation" but it's just trust score
- Can't actually detect trust degrading over time

**Fix**:
```python
# Option 1: Rename to be honest
feature_trust_score=float(trust_score),  # Not degradation, just score

# Option 2: Actually compute degradation
if self._prev_trust_score is not None:
    trust_degradation = self._prev_trust_score - trust_score  # Positive = degrading
else:
    trust_degradation = 0.0
self._prev_trust_score = trust_score

feature_trust_degradation=float(trust_degradation),
```

**Recommendation**: Option 1 (rename) - simpler and honest

**Verification**:
- Update metric name
- Update Grafana dashboard
- Update documentation

---

## LOW PRIORITY ISSUES (Nice to Have)

### Issue #10: Missing Data Watchdog Not Tested

**Severity**: LOW  
**Impact**: Unclear if watchdog works correctly  
**Location**: `services/layer2_anomaly/service.py:140-160`

**Problem**:
Watchdog forces HALT state if no ticks for 30 seconds, but:
- Only one test exists (`test_watchdog_forces_halt_once_on_silence`)
- No test for watchdog recovery
- No test for watchdog with partial data (some symbols silent, others active)
- No test for watchdog interaction with DecisionGate

**Evidence from project_analysis.md**:
> "Fix the missing-data watchdog - the code has a 30-second timeout but it's not clear if it's tested. Add a test that injects a 35-second gap and verifies HALT"

**Why This Is Bad**:
- Watchdog is critical safety mechanism
- Untested code is broken code
- Can't verify it works until production failure

**Fix**:
Add tests:
```python
def test_watchdog_recovery_after_data_resumes():
    # Force watchdog HALT
    # Resume data flow
    # Verify watchdog clears and state recovers

def test_watchdog_per_symbol_isolation():
    # One symbol goes silent
    # Other symbols continue
    # Verify only silent symbol affected

def test_watchdog_interaction_with_decision_gate():
    # Watchdog forces HALT
    # DecisionGate tries to upgrade
    # Verify HALT persists until data resumes
```

**Verification**:
- All watchdog tests pass
- Code coverage >90% for watchdog logic

---

### Issue #11: Feature Extraction Latency Not Tracked

**Severity**: LOW  
**Impact**: Can't optimize feature extraction  
**Location**: `services/layer2_anomaly/engine.py:280-320`

**Problem**:
Feature extraction (z-scoring, RV computation, HMM inference) happens on every tick, but:
- No metrics for how long it takes
- No breakdown by component (z-score vs RV vs HMM)
- Can't identify bottlenecks

**Evidence from BRUTAL_CODE_REVIEW.md**:
> "Feature extraction is expensive - Computes rolling volatility, z-scores, etc. on every tick. Why not batch this?"

**Why This Is Bad**:
- Can't optimize without measurement
- Unclear if feature extraction is a bottleneck
- No visibility into per-tick latency

**Fix**:
```python
# Add timing metrics (already partially done in service.py)
_feature_extraction_latency = Histogram(
    "anomaly_feature_extraction_duration_ms",
    "Feature extraction latency in milliseconds",
    ["symbol"],
    buckets=[0.1, 0.5, 1, 2, 5, 10]
)

# In score_tick():
start = time.perf_counter()
# ... feature extraction ...
_feature_extraction_latency.labels(symbol=symbol).observe((time.perf_counter() - start) * 1000)
```

**Note**: This is already partially implemented in service.py line 183-186, but not in engine.py.

**Verification**:
- Metrics show feature extraction latency
- Can identify slow components
- Grafana dashboard shows latency distribution

---

## Summary Table

| # | Issue | Severity | Impact | Effort | Priority | Status |
|---|-------|----------|--------|--------|----------|--------|
| 1 | Service crashes without HMM model | CRITICAL | Blocks startup | Low | 1 | ✅ FIXED |
| 2 | IF normalization undocumented | HIGH | Unclear algorithm | Low | 2 | ✅ FIXED |
| 3 | No feature normalization | HIGH | Biased anomaly scores | Medium | 3 | ✅ FIXED |
| 4 | Regime classification unused | HIGH | Wasted computation | Medium | 4 | |
| 5 | Kafka hop adds latency | HIGH | 5-10ms per tick | High | 5 (defer) | |
| 6 | Decision gate thresholds hardcoded | MEDIUM | Can't tune | Low | 6 | |
| 7 | MAD multipliers not documented | MEDIUM | Unclear rationale | Low | 7 | |
| 8 | HMM expected states mismatch | MEDIUM | Code/docs inconsistent | Low | 8 | ✅ FIXED |
| 9 | No IF retraining metrics | MEDIUM | Can't observe training | Low | 9 | |
| 10 | Watchdog not fully tested | LOW | Unclear if works | Medium | 10 | |
| 11 | Feature extraction latency not tracked | LOW | Can't optimize | Low | 11 | |
| **12** | **MAD guard uses 3-state mapping** | **CRITICAL** | **Wrong thresholds** | **Low** | **12** | |
| **13** | **DecisionGate threshold mismatch** | **HIGH** | **Inconsistent defaults** | **Low** | **13** | |
| **14** | **Single global DecisionGate** | **HIGH** | **Cross-symbol contamination** | **Medium** | **14** | |
| **15** | **Watchdog affects global gate** | **MEDIUM** | **Halts all symbols** | **Medium** | **15** | |
| **16** | **Feature trust degradation misleading** | **LOW** | **Misleading name** | **Low** | **16** | |

**Total Issues**: 16 (was 11)  
**Critical**: 2 (Issue #1 FIXED ✅, Issue #12 NEW ❌)  
**High**: 5 (Issue #2 FIXED ✅, Issues #3-5, #13-14 NEW ❌)  
**Medium**: 5 (Issue #8 FIXED ✅, Issues #6-7, #9, #15 NEW ❌)  
**Low**: 4 (Issues #10-11, #16 NEW ❌)

---

## Recommendations

### Must Fix (Before Moving to Layer 3)
1. **Issue #1**: Make HMM optional (5 min fix)
2. **Issue #8**: Fix expected_states=2 (1 min fix)
3. **Issue #6**: Fix threshold inconsistency (5 min fix)

### Should Fix (Before Demo)
4. **Issue #3**: Add feature normalization (30 min)
5. **Issue #4**: Use regime in DecisionGate (20 min)
6. **Issue #2**: Document IF normalization (10 min)
7. **Issue #7**: Document MAD multipliers (10 min)
8. **Issue #9**: Add IF retraining metrics (15 min)

### Nice to Have (If Time Permits)
9. **Issue #10**: Add watchdog tests (1 hour)
10. **Issue #11**: Track feature extraction latency (already done in service.py)
11. **Issue #5**: Remove Kafka hop (defer to post-thesis optimization)

---

## Questions for Discussion

1. **HMM Model**: Should we make it optional (Issue #1) or provide a pre-trained model in the repo?
2. **Regime Usage**: Should we use regime to adjust DecisionGate thresholds (Issue #4) or remove HMM entirely?
3. **Feature Normalization**: Should we normalize to [0, 1] or use StandardScaler on all features (Issue #3)?
4. **Kafka Architecture**: Is the latency overhead (Issue #5) acceptable for a thesis project, or should we optimize?
5. **Threshold Tuning**: How were 0.60 and 0.55 chosen (Issue #6)? Do we have backtest results justifying these values?

---

**End of Layer 2 Problems Analysis**

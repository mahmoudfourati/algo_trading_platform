# Layer 2 Anomaly Detection Dashboard Guide

## Overview
The Layer 2 dashboard monitors the anomaly detection system that processes validated market ticks and produces scored ticks with anomaly assessments, HMM regime classification, and system state decisions.

**Dashboard URL:** http://localhost:3000/d/layer2-anomaly/layer2-anomaly-detection

---

## Section 1: Critical Status (Top Row)

### System State
**Metric:** `layer2_system_state`

**States:**
- **0 = NORMAL** (Green) - System operating normally
- **1 = CONSERVATIVE** (Yellow) - Reduced confidence, conservative mode
- **2 = DEGRADED** (Orange) - Significant issues detected
- **3 = HALT** (Red) - System halted, no trading signals

**What to Watch:**
- Should be NORMAL (0) during healthy operation
- HALT (3) indicates critical issues (trust too low, anomaly too high, or data timeout)

### Service Health
**Metric:** `service_health{layer="layer2"}`

**Values:**
- **1** = Service is up and healthy
- **0** = Service is down

### Tick Processing Rate
**Metric:** `rate(layer2_raw_in_total[1m])`

**What it Shows:**
- Real-time tick consumption rate (ticks/second)
- Should match Layer 1 output rate

**Expected Values:**
- Depends on market activity
- Should be continuous during market hours

### Cumulative Counters
**Metrics:**
- `layer2_raw_in_total` - Total ticks received
- `layer2_scored_out_total` - Total scored ticks published
- `layer2_bad_in_total` - Total malformed/invalid ticks

**What to Watch:**
- `scored_out` should approximately equal `raw_in - bad_in`
- `bad_in` should be very low (< 0.1% of raw_in)

---

## Section 2: Core Anomaly Metrics

### Anomaly Score (Current)
**Metric:** `layer2_last_anomaly_score`

**Range:** 0.0 to 1.0
- **0.0 - 0.55** (Green) - Normal market behavior
- **0.55 - 0.8** (Yellow) - Elevated anomaly, conservative mode
- **0.8 - 1.0** (Red) - High anomaly, potential halt

**What it Means:**
- Fused score from Isolation Forest and Half-Space Trees
- Higher = more anomalous market behavior

### Trust Score (Current)
**Metric:** `layer2_last_input_trust_score`

**Range:** 0.0 to 1.0
- **0.0 - 0.6** (Red) - Low trust, system may halt
- **0.6 - 0.8** (Yellow) - Moderate trust
- **0.8 - 1.0** (Green) - High trust

**What it Means:**
- Trust score from Layer 1 consensus
- Reflects data source reliability

### HMM Regime State
**Metric:** `hmm_regime_state`

**States:**
- **0 = LOW_VOL** (Blue) - Low volatility regime
- **1 = NORMAL** (Green) - Normal volatility regime
- **2 = HIGH_VOL** (Orange) - High volatility regime

**What it Means:**
- Hidden Markov Model classification of market regime
- Used to contextualize anomaly detection

---

## Section 3: Time Series Analysis

### Anomaly Score History
**Metric:** `layer2_last_anomaly_score`

**What to Watch:**
- Sudden spikes indicate anomalous events
- Sustained high values may trigger system state changes
- Should be relatively stable during normal markets

### Trust Score History
**Metric:** `layer2_last_input_trust_score`

**What to Watch:**
- Should remain high (> 0.8) during normal operation
- Drops indicate data source issues upstream
- Correlates with system state changes

---

## Section 4: Anomaly Decomposition

### Anomaly Subscores (IF vs HST)
**Metrics:**
- `anomaly_subscore_if` - Isolation Forest score
- `anomaly_subscore_hst` - Half-Space Trees score

**What it Shows:**
- Individual model contributions to final anomaly score
- IF and HST may disagree, showing different anomaly perspectives

**Typical Behavior:**
- Both should be low (< 0.5) during normal markets
- Divergence between models is normal and expected

### MAD Guard Status
**Metric:** `anomaly_mad_guard_active`

**Values:**
- **0 = INACTIVE** (Green) - Normal operation
- **1 = ACTIVE** (Red) - MAD guard triggered

**What it Means:**
- Median Absolute Deviation guard prevents false positives
- When active, anomaly score is clamped to floor value (0.65)
- Indicates extreme outlier that may be legitimate market move

### Input Lag
**Metric:** `layer2_last_input_lag_ms`

**What it Shows:**
- Time between tick timestamp and Layer 2 processing
- Indicates processing latency

**Expected Values:**
- **< 100ms** (Green) - Excellent
- **100-500ms** (Yellow) - Acceptable
- **> 500ms** (Red) - Concerning latency

---

## Section 5: HMM Regime Analysis

### HMM Regime Posterior Probabilities
**Metric:** `hmm_regime_posterior_prob{regime="0|1|2"}`

**What it Shows:**
- Probability distribution across three regimes
- Stacked area chart shows confidence in regime classification

**Interpretation:**
- High confidence = one regime dominates (> 0.8)
- Low confidence = regime uncertainty, transition period

### HMM Regime Transitions
**Metric:** `rate(hmm_regime_transitions_total[1m])`

**What it Shows:**
- Frequency of regime changes
- Transition patterns (e.g., NORMAL → HIGH_VOL)

**What to Watch:**
- Frequent transitions may indicate market instability
- Should be relatively rare (< 1 per minute)

---

## Section 6: Feature Vector Observability

These panels show the raw features fed into the anomaly detection models:

### Feature: Raw Return
**Metric:** `anomaly_feature_raw_return`
- Log return of mid price
- Should be small (< 0.01) during normal markets

### Feature: Rolling Volatility
**Metric:** `anomaly_feature_rolling_volatility`
- 30-minute realized volatility
- Higher during volatile markets

### Feature: Spread Divergence Z-Score
**Metric:** `anomaly_feature_spread_divergence`
- Z-score of bid-ask spread
- High values indicate unusual spread widening

### Feature: Latency Anomaly Z-Score
**Metric:** `anomaly_feature_latency_anomaly`
- Z-score of tick arrival latency
- High values indicate timing irregularities

### Feature: Volume Anomaly Z-Score
**Metric:** `anomaly_feature_volume_anomaly`
- Z-score of 24h volume
- High values indicate unusual volume

### Feature: Trust Degradation
**Metric:** `anomaly_feature_trust_degradation`
- Rate of trust score decline
- Positive values indicate trust is falling

---

## Section 7: Performance Metrics

### Model Inference Latency (P50, P95, P99)
**Metric:** `histogram_quantile(0.XX, rate(anomaly_model_inference_duration_ms_bucket[1m]))`

**What it Shows:**
- Latency distribution for anomaly scoring
- P50 = median, P95 = 95th percentile, P99 = 99th percentile

**Expected Values:**
- **P50 < 5ms** - Excellent
- **P95 < 20ms** - Good
- **P99 < 50ms** - Acceptable

**What to Watch:**
- Sudden increases indicate performance degradation
- P99 spikes may indicate GC pauses or resource contention

---

## Section 8: Decision Gate Analysis

### Decision Gate State Transitions
**Metric:** `rate(decision_gate_state_transitions_total[1m])`

**What it Shows:**
- Frequency of system state changes
- Transition patterns (e.g., NORMAL → CONSERVATIVE)

**What to Watch:**
- Should be rare during stable markets
- Frequent transitions indicate instability

### Decision Gate Trigger Reasons
**Metric:** `decision_gate_trigger_total`

**Trigger Types:**
- **trust_low** - Trust score below threshold (< 0.6)
- **anomaly_high** - Anomaly score above threshold (> 0.8)
- **mad_triggered** - MAD guard activated

**What it Shows:**
- Pie chart of trigger reason distribution
- Helps diagnose why system state changes occur

---

## Section 9: Anomaly Score Distribution

### Anomaly Score Distribution Heatmap
**Metric:** `rate(anomaly_score_distribution_bucket[1m])`

**What it Shows:**
- Heatmap of anomaly score distribution over time
- Darker colors = more observations in that score range

**Interpretation:**
- Should be concentrated in low scores (< 0.5) during normal markets
- Spread distribution indicates volatile/uncertain conditions

---

## Alert Conditions

### Critical Alerts
1. **System HALT**
   - `layer2_system_state == 3`
   - Immediate investigation required

2. **Service Down**
   - `service_health{layer="layer2"} == 0`
   - Service restart needed

3. **No Data Flow**
   - `rate(layer2_raw_in_total[5m]) == 0`
   - Check upstream Layer 1 services

### Warning Alerts
1. **High Anomaly Score**
   - `layer2_last_anomaly_score > 0.8`
   - Monitor for system state change

2. **Low Trust Score**
   - `layer2_last_input_trust_score < 0.6`
   - Check Layer 1 data sources

3. **High Latency**
   - `histogram_quantile(0.99, rate(anomaly_model_inference_duration_ms_bucket[1m])) > 100`
   - Performance degradation

4. **Frequent State Transitions**
   - `rate(decision_gate_state_transitions_total[5m]) > 0.1`
   - Market instability or configuration issue

---

## Troubleshooting

### System in HALT State
**Possible Causes:**
1. Trust score too low (< 0.6)
2. Anomaly score too high (> 0.8)
3. Data timeout (no ticks for 30+ seconds)

**Actions:**
1. Check Layer 1 services and data sources
2. Review anomaly score and feature vectors
3. Check for market events or data feed issues
4. Review audit logs for watchdog timeout events

### High Anomaly Scores
**Possible Causes:**
1. Legitimate market volatility
2. Data quality issues
3. Model drift

**Actions:**
1. Check HMM regime state (HIGH_VOL is expected during volatile markets)
2. Review feature vectors for unusual patterns
3. Check MAD guard status (may be legitimate outlier)
4. Compare with external market data

### MAD Guard Frequently Active
**Possible Causes:**
1. Extreme market moves
2. Model miscalibration
3. Data spikes

**Actions:**
1. Review raw feature values
2. Check if legitimate market events occurred
3. Consider adjusting MAD floor threshold (default 0.65)

### High Inference Latency
**Possible Causes:**
1. CPU contention
2. Memory pressure
3. Model complexity

**Actions:**
1. Check system resource usage
2. Review container logs for GC activity
3. Consider scaling Layer 2 service

---

## Configuration

### Environment Variables
- `L2_TRUST_THRESHOLD` - Trust threshold for state transitions (default: 0.60)
- `L2_ANOMALY_THRESHOLD` - Anomaly threshold for state transitions (default: 0.55)
- `L2_IF_WEIGHT` - Isolation Forest weight (default: 0.45)
- `L2_HST_WEIGHT` - Half-Space Trees weight (default: 0.55)
- `L2_MAD_FLOOR` - MAD guard floor value (default: 0.65)
- `L2_UPGRADE_STREAK` - Consecutive good ticks required to upgrade state (default: 10)

### Tuning Recommendations
- **More Conservative:** Increase `L2_TRUST_THRESHOLD`, decrease `L2_ANOMALY_THRESHOLD`
- **More Aggressive:** Decrease `L2_TRUST_THRESHOLD`, increase `L2_ANOMALY_THRESHOLD`
- **Reduce False Positives:** Increase `L2_MAD_FLOOR`
- **Faster Recovery:** Decrease `L2_UPGRADE_STREAK`

---

## Related Dashboards
- **Layer 1 - Consensus:** Upstream trust score generation
- **Layer 3 - Strategy:** Downstream signal generation
- **Operations Dashboard:** System-wide health and performance

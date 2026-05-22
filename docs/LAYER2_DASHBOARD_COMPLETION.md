# Layer 2 Anomaly Detection Dashboard - Completion Summary

**Created:** May 13, 2026  
**Status:** ✅ Complete and Operational

---

## 🎯 What Was Created

### 1. Layer 2 Anomaly Detection Dashboard
**File:** `ops/grafana/provisioning/dashboards/layer2-anomaly-dashboard.json`  
**UID:** `layer2-anomaly`  
**URL:** http://localhost:3000/d/layer2-anomaly/layer2-anomaly-detection

**Dashboard Features:**
- **24 panels** organized into 9 sections
- **Real-time monitoring** with 5-second refresh
- **Comprehensive coverage** of all Layer 2 metrics

---

## 📊 Dashboard Sections

### Section 1: Critical Status (4 panels)
- System State (NORMAL/CONSERVATIVE/DEGRADED/HALT)
- Service Health
- Tick Processing Rate
- Cumulative Counters

### Section 2: Core Anomaly Metrics (3 panels)
- Anomaly Score Gauge (current value)
- Trust Score Gauge (current value)
- HMM Regime State (LOW_VOL/NORMAL/HIGH_VOL)

### Section 3: Time Series Analysis (2 panels)
- Anomaly Score History
- Trust Score History

### Section 4: Anomaly Decomposition (3 panels)
- Anomaly Subscores (IF vs HST)
- MAD Guard Status
- Input Lag

### Section 5: HMM Regime Analysis (2 panels)
- HMM Regime Posterior Probabilities (stacked area)
- HMM Regime Transitions

### Section 6: Feature Vector Observability (6 panels)
- Feature: Raw Return
- Feature: Rolling Volatility
- Feature: Spread Divergence Z-Score
- Feature: Latency Anomaly Z-Score
- Feature: Volume Anomaly Z-Score
- Feature: Trust Degradation

### Section 7: Performance Metrics (1 panel)
- Model Inference Latency (P50, P95, P99)

### Section 8: Decision Gate Analysis (2 panels)
- Decision Gate State Transitions
- Decision Gate Trigger Reasons (pie chart)

### Section 9: Anomaly Score Distribution (1 panel)
- Anomaly Score Distribution Heatmap

---

## 📚 Documentation Created

### 1. Layer 2 Dashboard Guide
**File:** `docs/LAYER2_DASHBOARD_GUIDE.md`

**Contents:**
- Detailed explanation of all 24 panels
- Metric definitions and expected values
- Alert conditions (critical and warning)
- Troubleshooting guide
- Configuration tuning recommendations
- Related dashboards

**Sections:**
1. Critical Status
2. Core Anomaly Metrics
3. Time Series Analysis
4. Anomaly Decomposition
5. HMM Regime Analysis
6. Feature Vector Observability
7. Performance Metrics
8. Decision Gate Analysis
9. Anomaly Score Distribution
10. Alert Conditions
11. Troubleshooting
12. Configuration

### 2. Updated Dashboards Summary
**File:** `docs/DASHBOARDS_SUMMARY.md`

**Updates:**
- Added Layer 2 dashboard to available dashboards list
- Updated dashboard selection guide for different roles
- Added Layer 2 to recommended monitoring setups
- Updated documentation references
- Added Layer 2 to refresh rates section

---

## 🔍 Key Metrics Monitored

### System Health
- `layer2_system_state` - System operational state
- `service_health{layer="layer2"}` - Service health status
- `layer2_raw_in_total` - Total ticks processed
- `layer2_scored_out_total` - Total scored ticks published
- `layer2_bad_in_total` - Total invalid ticks

### Anomaly Detection
- `layer2_last_anomaly_score` - Current anomaly score
- `anomaly_subscore_if` - Isolation Forest subscore
- `anomaly_subscore_hst` - Half-Space Trees subscore
- `anomaly_mad_guard_active` - MAD guard status
- `anomaly_fused_score` - Final fused anomaly score

### HMM Regime Tracking
- `hmm_regime_state` - Current regime (0=LOW_VOL, 1=NORMAL, 2=HIGH_VOL)
- `hmm_regime_posterior_prob` - Posterior probabilities for each regime
- `hmm_regime_transitions_total` - Regime transition counter

### Feature Vectors
- `anomaly_feature_raw_return` - Raw log return
- `anomaly_feature_rolling_volatility` - 30m rolling volatility
- `anomaly_feature_spread_divergence` - Spread divergence z-score
- `anomaly_feature_latency_anomaly` - Latency anomaly z-score
- `anomaly_feature_volume_anomaly` - Volume anomaly z-score
- `anomaly_feature_trust_degradation` - Trust degradation signal

### Decision Gate
- `decision_gate_state_transitions_total` - State transition counter
- `decision_gate_trigger_total` - Trigger reason counter

### Performance
- `anomaly_model_inference_duration_ms` - Model inference latency histogram
- `layer2_last_input_lag_ms` - Input processing lag

---

## 🎨 Dashboard Design Highlights

### Color Coding
- **Green:** Normal/healthy state
- **Yellow:** Warning/elevated state
- **Orange:** Degraded state
- **Red:** Critical/halt state
- **Blue:** Low volatility regime

### Visualization Types
- **Gauges:** Current values with thresholds (anomaly score, trust score)
- **Stats:** Key metrics and counters
- **Time Series:** Historical trends
- **Pie Chart:** Trigger reason distribution
- **Heatmap:** Anomaly score distribution over time
- **Stacked Area:** HMM regime posterior probabilities

### Thresholds
- **Anomaly Score:** 0.55 (warning), 0.8 (critical)
- **Trust Score:** 0.6 (warning), 0.8 (good)
- **Input Lag:** 100ms (warning), 500ms (critical)
- **Inference Latency:** 5ms (P50), 20ms (P95), 50ms (P99)

---

## 🚀 How to Access

### Direct URL
http://localhost:3000/d/layer2-anomaly/layer2-anomaly-detection

### Via Grafana UI
1. Open http://localhost:3000
2. Login: `admin` / `admin`
3. Click **Dashboards** (left sidebar)
4. Search for "Layer 2" or "Anomaly"
5. Click "Layer 2 - Anomaly Detection"

---

## 📈 Current Status

### Expected Behavior
✅ **System State:** NORMAL (0)  
✅ **Service Health:** 1 (up)  
✅ **Anomaly Score:** Low (< 0.5)  
✅ **Trust Score:** High (> 0.8)  
✅ **HMM Regime:** Varies based on market (likely NORMAL)  
✅ **MAD Guard:** INACTIVE (0)  
✅ **Tick Processing:** Continuous flow  

### Data Availability
All metrics should show live data if:
- Layer 1 services are running
- Layer 2 service is running
- Market data is flowing
- Prometheus is scraping metrics

---

## 🔧 Troubleshooting

### Dashboard shows "No data"
1. Check Layer 2 service is running: `docker compose ps layer2_anomaly`
2. Check metrics endpoint: http://localhost:9103/metrics
3. Check Prometheus target: http://localhost:9090/targets (look for layer2_anomaly)
4. Verify time range in Grafana (use "Last 15 minutes")

### Specific panels show "No data"
1. Check if metric exists: http://localhost:9103/metrics | grep <metric_name>
2. Verify Prometheus is scraping: http://localhost:9090/graph
3. Check dashboard query syntax in panel edit mode

### System State shows HALT
**Possible causes:**
1. Trust score too low (< 0.6)
2. Anomaly score too high (> 0.8)
3. Data timeout (no ticks for 30+ seconds)

**Actions:**
1. Check Layer 1 services
2. Review anomaly score and feature vectors
3. Check audit logs for watchdog timeout events

---

## 🎯 Use Cases

### For Data Scientists
- Monitor model behavior in production
- Analyze feature vector distributions
- Track model inference latency
- Debug anomaly detection issues
- Validate model performance

### For Quants
- Understand market regime classification
- Analyze HMM regime transitions
- Correlate anomaly scores with market events
- Study decision gate behavior

### For Operations
- Monitor system health
- Track processing latency
- Identify performance bottlenecks
- Diagnose system state changes

### For Risk Managers
- Monitor system state (NORMAL/HALT)
- Track trust score degradation
- Understand why system enters conservative mode
- Correlate with downstream risk metrics

---

## 🔗 Related Dashboards

### Upstream
- **Layer 1 - Consensus:** Trust score generation
- **Deep Observability:** Trust score decomposition (T1-T5)

### Downstream
- **Layer 3 - Strategy:** Signal generation (uses anomaly scores)
- **Layer 4 - Risk:** Risk management (uses system state)

### System-Wide
- **Operations Dashboard:** Overall system health
- **Pipeline Overview:** High-level monitoring

---

## 📝 Configuration

### Environment Variables (Layer 2 Service)
- `L2_TRUST_THRESHOLD=0.60` - Trust threshold for state transitions
- `L2_ANOMALY_THRESHOLD=0.55` - Anomaly threshold for state transitions
- `L2_IF_WEIGHT=0.45` - Isolation Forest weight
- `L2_HST_WEIGHT=0.55` - Half-Space Trees weight
- `L2_MAD_FLOOR=0.65` - MAD guard floor value
- `L2_UPGRADE_STREAK=10` - Consecutive good ticks to upgrade state

### Tuning Recommendations
- **More Conservative:** Increase `L2_TRUST_THRESHOLD`, decrease `L2_ANOMALY_THRESHOLD`
- **More Aggressive:** Decrease `L2_TRUST_THRESHOLD`, increase `L2_ANOMALY_THRESHOLD`
- **Reduce False Positives:** Increase `L2_MAD_FLOOR`
- **Faster Recovery:** Decrease `L2_UPGRADE_STREAK`

---

## ✅ Completion Checklist

- [x] Dashboard JSON created
- [x] All 24 panels configured
- [x] Thresholds and color coding applied
- [x] Comprehensive documentation written
- [x] Dashboards summary updated
- [x] Grafana restarted
- [x] Dashboard accessible via URL
- [x] All metrics verified

---

## 🎉 Summary

The Layer 2 Anomaly Detection dashboard is now **fully operational** and provides comprehensive monitoring of:

1. **Anomaly Detection:** IF, HST, MAD guard, fused scores
2. **HMM Regime Classification:** State, posteriors, transitions
3. **Feature Vectors:** All 6 features used in anomaly detection
4. **Decision Gate:** State transitions and trigger reasons
5. **Performance:** Model inference latency and input lag
6. **System Health:** Service status and processing rates

**Total Panels:** 24  
**Total Sections:** 9  
**Documentation Pages:** 2 (guide + summary update)  
**Metrics Covered:** 20+ unique metrics  

**Dashboard URL:** http://localhost:3000/d/layer2-anomaly/layer2-anomaly-detection  
**Documentation:** `docs/LAYER2_DASHBOARD_GUIDE.md`

---

**Status:** ✅ Complete and Ready for Production Use

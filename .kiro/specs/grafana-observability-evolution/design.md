# Design Document

## Overview

This design specifies the evolution of the existing Grafana dashboard from basic monitoring (8 panels) to HFT/SIEM-grade observability with forensic visibility, root-cause analysis, and deep layer-specific telemetry. The evolution preserves the existing dark theme and clean layout while adding 5 new rows with ~20 new panels for trust score decomposition, anomaly score decomposition, layer-by-layer telemetry, Kafka monitoring, and pipeline bottleneck detection.

**Design Philosophy:**
- **Evolutionary, not revolutionary**: Preserve existing 8 panels, add new rows
- **Forensic-first**: Enable root-cause analysis for trust degradation and anomaly spikes
- **Layer-specific depth**: Dedicated telemetry for each pipeline layer (1-6)
- **Production-grade**: SRE-friendly with playbooks, alerts, and correlation support
- **Dark theme consistency**: Maintain existing visual style and color conventions

**Key Design Decisions:**
1. Add new rows (3-7) without modifying existing panels (rows 1-2, 8-9)
2. Use time series for decomposition views (trust, anomaly) with multi-line graphs
3. Use state timeline for HMM regime visualization
4. Use heatmaps for trust degradation events and feature vector analysis
5. Use stat panels for binary health indicators (exchange health, circuit breaker)
6. Use histogram buckets optimized for HFT latency ranges (sub-millisecond to seconds)

## Architecture

### Dashboard Row Structure

```
┌─────────────────────────────────────────────────────────────────┐
│ Row 1: Pipeline Health Overview (EXISTING - PRESERVE)          │
│   - Panel 1: Layer 1 Ingestion Rates (time series)             │
│   - Panel 2: Validated/Scored Throughput (time series)         │
├─────────────────────────────────────────────────────────────────┤
│ Row 2: Trust & Anomaly Overview (EXISTING - PRESERVE)          │
│   - Panel 3: Trust Score By Symbol (time series)               │
│   - Panel 4: Anomaly Components By Symbol (time series)        │
│   - Panel 5: System State (stat)                               │
├─────────────────────────────────────────────────────────────────┤
│ Row 3: Trust Score Decomposition (NEW - FORENSIC)              │
│   - Panel 10: Trust Subcomponents Timeline (16 cols)           │
│   - Panel 11: Trust Degradation Heatmap (8 cols)               │
│   - Panel 12: Trust Component Stats (8 cols)                   │
├─────────────────────────────────────────────────────────────────┤
│ Row 4: Anomaly Score Decomposition (NEW - FORENSIC)            │
│   - Panel 13: Anomaly Subcomponents Timeline (16 cols)         │
│   - Panel 14: HMM Regime State Timeline (8 cols)               │
│   - Panel 15: Feature Vector Heatmap (8 cols)                  │
├─────────────────────────────────────────────────────────────────┤
│ Row 5: Layer 1 Deep Telemetry (NEW)                            │
│   - Panel 16: Exchange Connection Health (8 cols)              │
│   - Panel 17: TLS Failures & Reconnects (8 cols)               │
│   - Panel 18: Consensus Divergence Details (8 cols)            │
├─────────────────────────────────────────────────────────────────┤
│ Row 6: Layer 2 Deep Telemetry (NEW)                            │
│   - Panel 19: Model Inference Latency (12 cols)                │
│   - Panel 20: Regime Transitions (6 cols)                      │
│   - Panel 21: Feature Extraction Performance (6 cols)          │
├─────────────────────────────────────────────────────────────────┤
│ Row 7: Layer 3-6 Telemetry (NEW)                               │
│   - Panel 22: Strategy Indicators (8 cols)                     │
│   - Panel 23: Risk Metrics (8 cols)                            │
│   - Panel 24: Execution Performance (8 cols)                   │
├─────────────────────────────────────────────────────────────────┤
│ Row 8: Pipeline Performance (EXISTING - ENHANCE)               │
│   - Panel 6: Pipeline Latency (keep)                           │
│   - Panel 7: Kafka Buffer Depths (keep)                        │
│   - Panel 25: Kafka Consumer Lag (NEW)                         │
│   - Panel 26: Pipeline Bottleneck Heatmap (NEW)                │
├─────────────────────────────────────────────────────────────────┤
│ Row 9: Error Rates (EXISTING - PRESERVE)                       │
│   - Panel 8: Error Rates (time series)                         │
└─────────────────────────────────────────────────────────────────┘
```

**Grid Layout:**
- Grafana uses 24-column grid system
- Standard panel heights: 5-10 units
- Full-width panels: 24 columns
- Half-width panels: 12 columns
- Third-width panels: 8 columns

### Metric Taxonomy

All metrics follow the naming convention defined in `docs/OBSERVABILITY_METRICS_SPEC.md`:

```
<layer>_<component>_<metric_type>_<unit>

Examples:
- trust_subscore_t1_tls              # Trust subscore (gauge)
- anomaly_subscore_if                # Anomaly subscore (gauge)
- hmm_regime_state                   # HMM regime (gauge)
- anomaly_feature_raw_return         # Feature vector (gauge)
- exchange_websocket_reconnects_total # Reconnects (counter)
- pipeline_stage_latency_ms          # Latency (histogram)
```

**Label Conventions:**
- `symbol`: Trading pair (e.g., "BTC-USDT")
- `exchange_id`: Exchange identifier (e.g., "binance", "okx")
- `direction`: Trade direction ("LONG", "SHORT", "HOLD")
- `reason`: Failure/rejection reason (enum values)
- `stage`: Pipeline stage ("ingestion", "validation", "scoring", etc.)
- `regime`: HMM regime ("0", "1", "2")

## Components and Interfaces

### Component 1: Trust Score Decomposition Panels

**Purpose:** Provide forensic visibility into trust score components (T1-T5) to enable root-cause analysis of trust degradation events.

**Panel 10: Trust Subcomponents Timeline**
- **Type:** Time series (multi-line)
- **Dimensions:** 16 columns × 10 rows
- **Queries:**
  - `layer1_validated_last_trust_score{symbol="BTC-USDT"}` → Final trust score (blue, bold)
  - `trust_subscore_t1_tls{symbol="BTC-USDT"}` → T1 TLS (purple)
  - `trust_subscore_t2_consensus{symbol="BTC-USDT"}` → T2 Consensus (green)
  - `trust_subscore_t3_freshness{symbol="BTC-USDT"}` → T3 Freshness (yellow)
  - `trust_subscore_t4_sequence{symbol="BTC-USDT"}` → T4 Sequence (orange)
  - `trust_subscore_t5_hashchain{symbol="BTC-USDT"}` → T5 HashChain (red)
  - `trust_subscore_t_availability{symbol="BTC-USDT"}` → T_Availability (cyan)
- **Legend:** Table mode with last, min, max, mean calculations
- **Y-axis:** Range [0, 1], label "Score [0,1]"
- **Thresholds:** Red (0-0.5), Orange (0.5-0.7), Yellow (0.7-0.85), Green (0.85-1.0)
- **Line styles:** Final trust = 3px width, subscores = 2px width, 10% fill opacity

**Panel 11: Trust Degradation Heatmap**
- **Type:** Heatmap
- **Dimensions:** 8 columns × 10 rows
- **Query:** `sum by (primary_cause) (increase(trust_degradation_events_total{symbol="BTC-USDT"}[5m]))`
- **Color scheme:** RdYlGn (red-yellow-green) reversed, exponential scale
- **Cell gap:** 2px
- **Purpose:** Show which trust component (T1-T5) caused degradation events over time

**Panel 12: Trust Component Stats**
- **Type:** Stat (multi-value)
- **Dimensions:** 8 columns × 5 rows
- **Queries:** Same as Panel 10 (T1-T5 subscores)
- **Display mode:** Value and name, background color mode
- **Graph mode:** Area sparkline
- **Reduce function:** Last not null
- **Purpose:** Show current instant values of all trust components with color-coded health

### Component 2: Anomaly Score Decomposition Panels

**Purpose:** Provide forensic visibility into anomaly detection models (IF, HST, MAD) and feature vector for attack attribution.

**Panel 13: Anomaly Subcomponents Timeline**
- **Type:** Time series (multi-line)
- **Dimensions:** 16 columns × 10 rows
- **Queries:**
  - `anomaly_fused_score{symbol="BTC-USDT"}` → Fused score (red, bold, 3px)
  - `anomaly_subscore_if{symbol="BTC-USDT"}` → Isolation Forest (orange-red)
  - `anomaly_subscore_hst{symbol="BTC-USDT"}` → Half-Space Trees (gold)
  - `anomaly_mad_guard_active{symbol="BTC-USDT"}` → MAD guard (purple, dashed, no fill)
- **Legend:** Table mode with last, max, mean calculations
- **Y-axis:** Range [0, 1], label "Anomaly Score [0,1]"
- **Line styles:** Fused = 3px solid, IF/HST = 2px solid, MAD = 2px dashed

**Panel 14: HMM Regime State Timeline**
- **Type:** State timeline
- **Dimensions:** 8 columns × 5 rows
- **Query:** `hmm_regime_state{symbol="BTC-USDT"}`
- **Value mappings:**
  - 0 → "Low Vol" (green)
  - 1 → "Normal" (yellow)
  - 2 → "High Vol" (red)
- **Options:** Merge adjacent values = true, show value = always, align center
- **Purpose:** Visualize market regime transitions as color-coded timeline

**Panel 15: Feature Vector Heatmap**
- **Type:** Heatmap
- **Dimensions:** 8 columns × 5 rows
- **Queries:**
  - `anomaly_feature_raw_return{symbol="BTC-USDT"}`
  - `anomaly_feature_rolling_volatility{symbol="BTC-USDT"}`
  - `anomaly_feature_spread_divergence{symbol="BTC-USDT"}`
  - `anomaly_feature_latency_anomaly{symbol="BTC-USDT"}`
  - `anomaly_feature_trust_degradation{symbol="BTC-USDT"}`
- **Color scheme:** Spectral (blue-green-yellow-red), 64 steps
- **Purpose:** Show which features are outliers during anomaly events

### Component 3: Layer 1 Deep Telemetry Panels

**Purpose:** Provide visibility into exchange connection health, TLS failures, reconnects, and consensus divergence.

**Panel 16: Exchange Connection Health**
- **Type:** Stat (multi-value)
- **Dimensions:** 8 columns × 6 rows
- **Query:** `exchange_connection_health`
- **Value mappings:**
  - 0 → "DOWN" (dark-red background)
  - 1 → "UP" (dark-green background)
- **Display mode:** Value and name, background color mode
- **Purpose:** Binary health indicator for all exchanges

**Panel 17: TLS Failures & Reconnects**
- **Type:** Time series (stacked bars)
- **Dimensions:** 8 columns × 6 rows
- **Queries:**
  - `sum by (exchange_id) (rate(tls_pin_mismatch_total[1m]))` → TLS failures
  - `sum by (exchange_id) (rate(exchange_websocket_reconnects_total[1m]))` → Reconnects
- **Draw style:** Bars, stacking mode = normal
- **Unit:** ops (operations per second)
- **Purpose:** Show TLS failure and reconnect rates by exchange

**Panel 18: Consensus Divergence Details**
- **Type:** Time series (dual-axis)
- **Dimensions:** 8 columns × 6 rows
- **Queries:**
  - `consensus_divergent_source_count` → Divergent sources (left axis, count)
  - `consensus_divergence_max_bps` → Max divergence (right axis, basis points)
- **Axis overrides:** Query B uses right axis with unit "bps"
- **Purpose:** Show consensus divergence magnitude and affected exchange count

### Component 4: Layer 2 Deep Telemetry Panels

**Purpose:** Provide visibility into model inference performance and regime transitions.

**Panel 19: Model Inference Latency**
- **Type:** Time series (multi-line)
- **Dimensions:** 12 columns × 6 rows
- **Queries:**
  - `histogram_quantile(0.50, rate(anomaly_model_inference_duration_ms_bucket[5m])) by (model)` → p50
  - `histogram_quantile(0.95, rate(anomaly_model_inference_duration_ms_bucket[5m])) by (model)` → p95
  - `histogram_quantile(0.99, rate(anomaly_model_inference_duration_ms_bucket[5m])) by (model)` → p99
- **Unit:** milliseconds
- **Legend:** Table mode with last, max calculations
- **Purpose:** Show inference latency percentiles for IF, HST, HMM models

**Panel 20: Regime Transitions**
- **Type:** Time series (bars)
- **Dimensions:** 6 columns × 6 rows
- **Query:** `rate(hmm_regime_transitions_total[5m]) * 60` → Transitions per minute
- **Draw style:** Bars
- **Purpose:** Show regime transition frequency

**Panel 21: Feature Extraction Performance**
- **Type:** Time series (multi-line)
- **Dimensions:** 6 columns × 6 rows
- **Queries:**
  - `histogram_quantile(0.50, rate(anomaly_feature_extraction_duration_ms_bucket[5m]))` → p50
  - `histogram_quantile(0.95, rate(anomaly_feature_extraction_duration_ms_bucket[5m]))` → p95
  - `histogram_quantile(0.99, rate(anomaly_feature_extraction_duration_ms_bucket[5m]))` → p99
- **Unit:** milliseconds
- **Purpose:** Show feature extraction latency percentiles

### Component 5: Layer 3-6 Telemetry Panels

**Purpose:** Provide visibility into strategy indicators, risk metrics, and execution performance.

**Panel 22: Strategy Indicators**
- **Type:** Time series (multi-line)
- **Dimensions:** 8 columns × 6 rows
- **Queries:**
  - `strategy_indicator_rsi{symbol="BTC-USDT", timeframe="5m"}` → RSI
  - `strategy_indicator_macd_histogram{symbol="BTC-USDT", timeframe="5m"}` → MACD
  - `strategy_indicator_bollinger_width{symbol="BTC-USDT", timeframe="5m"}` → BB Width
- **Purpose:** Show technical indicator values over time

**Panel 23: Risk Metrics**
- **Type:** Stat (multi-value)
- **Dimensions:** 8 columns × 6 rows
- **Queries:**
  - `risk_current_exposure_percent` → Exposure %
  - `risk_current_drawdown_percent` → Drawdown %
  - `risk_circuit_breaker_active` → Circuit breaker (binary)
  - `risk_consecutive_loss_count` → Consecutive losses
- **Display mode:** Value and name, background color mode
- **Thresholds:** Exposure (green <50%, yellow 50-80%, red >80%)
- **Purpose:** Show current risk state

**Panel 24: Execution Performance**
- **Type:** Time series (multi-line)
- **Dimensions:** 8 columns × 6 rows
- **Queries:**
  - `histogram_quantile(0.99, rate(execution_order_placement_latency_ms_bucket[5m])) by (exchange_id)` → p99 latency
  - `rate(execution_order_retries_total[5m]) * 60` → Retries per minute
  - `rate(execution_order_failures_total[5m]) * 60` → Failures per minute
- **Unit:** milliseconds (latency), ops (retries/failures)
- **Purpose:** Show execution performance metrics

### Component 6: Kafka & Pipeline Monitoring Panels

**Purpose:** Provide visibility into Kafka consumer lag and pipeline bottlenecks.

**Panel 25: Kafka Consumer Lag**
- **Type:** Time series (multi-line)
- **Dimensions:** 12 columns × 6 rows
- **Queries:**
  - `kafka_consumer_lag_seconds` → Lag in seconds by consumer group and topic
- **Unit:** seconds
- **Thresholds:** Green (<10s), Yellow (10-30s), Red (>30s)
- **Purpose:** Show consumer lag for all pipeline stages

**Panel 26: Pipeline Bottleneck Heatmap**
- **Type:** Heatmap
- **Dimensions:** 12 columns × 6 rows
- **Query:** `histogram_quantile(0.99, rate(pipeline_stage_latency_ms_bucket[5m])) by (stage)`
- **Color scheme:** Reds (white-yellow-orange-red), exponential scale
- **Purpose:** Identify which pipeline stage has highest p99 latency

## Data Models

### Grafana Panel JSON Structure

```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus"
  },
  "fieldConfig": {
    "defaults": {
      "color": {"mode": "palette-classic"},
      "custom": {
        "lineWidth": 2,
        "fillOpacity": 10,
        "gradientMode": "opacity",
        "axisPlacement": "auto"
      },
      "decimals": 3,
      "max": 1.0,
      "min": 0.0,
      "unit": "none",
      "thresholds": {
        "mode": "absolute",
        "steps": [
          {"color": "red", "value": 0.0},
          {"color": "orange", "value": 0.5},
          {"color": "yellow", "value": 0.7},
          {"color": "green", "value": 0.85}
        ]
      }
    },
    "overrides": [
      {
        "matcher": {"id": "byName", "options": "Trust Final"},
        "properties": [
          {"id": "custom.lineWidth", "value": 3},
          {"id": "color", "value": {"mode": "fixed", "fixedColor": "blue"}}
        ]
      }
    ]
  },
  "gridPos": {"h": 10, "w": 16, "x": 0, "y": 16},
  "id": 10,
  "options": {
    "legend": {
      "calcs": ["last", "min", "max", "mean"],
      "displayMode": "table",
      "placement": "right",
      "showLegend": true
    },
    "tooltip": {"mode": "multi", "sort": "desc"}
  },
  "targets": [
    {
      "expr": "layer1_validated_last_trust_score{symbol=\"BTC-USDT\"}",
      "legendFormat": "Trust Final",
      "refId": "A"
    }
  ],
  "title": "Trust Score Decomposition - BTC-USDT",
  "type": "timeseries"
}
```

### PromQL Query Patterns

**Trust Score Forensics:**
```promql
# Identify which component caused trust drop
topk(1, 
  (trust_subscore_t1_tls < bool 0.5) * 1 +
  (trust_subscore_t2_consensus < bool 0.5) * 2 +
  (trust_subscore_t3_freshness < bool 0.3) * 3 +
  (trust_subscore_t4_sequence < bool 0.5) * 4 +
  (trust_subscore_t5_hashchain < bool 0.5) * 5
)

# Trust score moving average (5min)
avg_over_time(layer1_validated_last_trust_score[5m])

# Correlation: trust drop with anomaly spike
(deriv(layer1_validated_last_trust_score[1m]) < -0.1) 
and 
(anomaly_fused_score > 0.8)
```

**Anomaly Attribution:**
```promql
# Which model triggered the anomaly?
max by (symbol) (
  (anomaly_subscore_if > 0.9) * 1 +
  (anomaly_subscore_hst > 0.9) * 2 +
  (anomaly_mad_guard_active == 1) * 3
)

# Feature vector outlier detection
abs(anomaly_feature_raw_return) > 3 * stddev_over_time(anomaly_feature_raw_return[1h])
```

**Pipeline Bottleneck Detection:**
```promql
# Identify slowest pipeline stage
topk(1, 
  histogram_quantile(0.99, rate(pipeline_stage_latency_ms_bucket[5m])) by (stage)
)

# Backpressure detection
pipeline_backpressure_ratio > 0.8
```

### Color Scheme (Dark Theme)

**Trust Score Components:**
- T1 (TLS): `#9933FF` (Purple) - Security-critical
- T2 (Consensus): `#00FF00` (Green) - Agreement
- T3 (Freshness): `#FFFF00` (Yellow) - Timeliness
- T4 (Sequence): `#FF9900` (Orange) - Integrity
- T5 (HashChain): `#FF0000` (Red) - Audit trail
- Final Trust: `#0099FF` (Blue) - Bold, primary

**Anomaly Components:**
- Fused Score: `#FF0000` (Red) - Alert
- Isolation Forest: `#FF6600` (Orange-Red)
- Half-Space Trees: `#FFCC00` (Gold)
- MAD Guard: `#9933FF` (Purple) - Dashed line

**State Colors:**
- NORMAL: `#00FF00` (Green)
- CONSERVATIVE: `#FFFF00` (Yellow)
- DEGRADED: `#FF9900` (Orange)
- HALT: `#FF0000` (Red)

**HMM Regime:**
- Low Vol: `#00FF00` (Green)
- Normal: `#FFFF00` (Yellow)
- High Vol: `#FF0000` (Red)

## Error Handling

### Missing Metrics Handling

**Problem:** Metrics may not exist if corresponding service is not running or metric export is not implemented.

**Solution:**
- Use Grafana's "No data" handling: Display "No data" message instead of empty panel
- Configure panel options: `"noValue": "No data available"`
- Use PromQL `or vector(0)` fallback for critical metrics:
  ```promql
  trust_subscore_t1_tls{symbol="BTC-USDT"} or vector(0)
  ```

### High Cardinality Label Handling

**Problem:** Labels like `correlation_id` or `timestamp` can cause high cardinality and Prometheus performance issues.

**Solution:**
- Avoid high-cardinality labels in aggregations
- Use recording rules for expensive queries
- Limit label values to enums (e.g., `reason` has fixed set of values)
- Use `topk()` or `bottomk()` to limit result set size

### Query Timeout Handling

**Problem:** Complex PromQL queries may timeout on large time ranges.

**Solution:**
- Use recording rules for expensive aggregations (trust score moving averages, percentiles)
- Limit time range to reasonable window (default: 15 minutes, max: 6 hours)
- Use `rate()` with appropriate time windows ([1m] for counters, [5m] for histograms)
- Configure Grafana query timeout: 30 seconds

### Panel Rendering Performance

**Problem:** Too many panels or high refresh rate can cause browser performance issues.

**Solution:**
- Use 5-second refresh rate (existing dashboard standard)
- Limit panels per row to 3-4 maximum
- Use heatmaps instead of high-cardinality time series
- Enable panel caching in Grafana

## Testing Strategy

### Dashboard Validation Testing

**Objective:** Ensure all panels render correctly with valid PromQL queries and proper data visualization.

**Approach:**
1. **PromQL Query Validation:**
   - Test each PromQL query against production Prometheus instance
   - Verify query returns expected metric names and labels
   - Check query execution time (<1 second for all queries)
   - Validate histogram bucket ranges match metric definitions

2. **Panel Rendering Validation:**
   - Import dashboard JSON into Grafana staging environment
   - Verify all panels render without errors
   - Check color schemes match dark theme specification
   - Validate legend displays correct calculations (last, min, max, mean)
   - Verify thresholds trigger at correct values

3. **Layout Validation:**
   - Verify grid positions (x, y, w, h) do not overlap
   - Check panel heights are consistent within rows
   - Validate 24-column grid alignment
   - Verify existing panels (1-8) are not modified

4. **Data Accuracy Validation:**
   - Compare panel values with raw Prometheus queries
   - Verify aggregations (sum, avg, rate) produce correct results
   - Check histogram percentiles (p50, p95, p99) are accurate
   - Validate time range filters work correctly

### Integration Testing

**Objective:** Ensure dashboard integrates correctly with Prometheus, alert rules, and existing infrastructure.

**Approach:**
1. **Prometheus Integration:**
   - Verify datasource UID "prometheus" resolves correctly
   - Test dashboard with Prometheus recording rules enabled
   - Validate alert annotations appear on timeline panels
   - Check dashboard works with Prometheus federation (if applicable)

2. **Alert Rule Integration:**
   - Trigger test alerts (trust score drop, anomaly spike)
   - Verify alert annotations appear on correct panels
   - Check annotation colors match severity (red=critical, orange=warning)
   - Validate annotation tooltips display alert details

3. **Backward Compatibility:**
   - Verify existing alert rules still work with new dashboard
   - Check existing recording rules are not broken
   - Validate existing Grafana variables (if any) still function
   - Test dashboard rollback procedure

### User Acceptance Testing

**Objective:** Ensure dashboard meets SRE operational requirements and usability standards.

**Approach:**
1. **SRE Playbook Validation:**
   - Follow "Trust Score Sudden Drop" playbook using dashboard
   - Follow "Anomaly Score Spike" playbook using dashboard
   - Follow "Pipeline Bottleneck" playbook using dashboard
   - Verify all required metrics are visible and actionable

2. **Forensic Analysis Validation:**
   - Inject synthetic trust degradation event
   - Use dashboard to identify root cause (which T-score dropped)
   - Inject synthetic anomaly spike
   - Use dashboard to identify which model triggered and which features were outliers

3. **Performance Validation:**
   - Load dashboard with 15-minute time range (default)
   - Verify page load time <3 seconds
   - Test dashboard with 6-hour time range (max)
   - Verify all panels render within 5 seconds

### Snapshot Testing

**Objective:** Ensure dashboard JSON structure remains consistent across updates.

**Approach:**
1. Export dashboard JSON from Grafana
2. Compare with reference JSON in version control
3. Validate only intended changes are present
4. Check for unintended modifications to existing panels

**Test Cases:**
- Existing panels (1-8) JSON unchanged
- New panels (10-26) JSON matches specification
- Datasource UID references are correct
- Grid positions do not overlap
- Color overrides match specification

### Production Deployment Testing

**Objective:** Ensure safe deployment with rollback capability.

**Approach:**
1. **Pre-Deployment:**
   - Backup existing dashboard JSON
   - Test new dashboard in staging environment
   - Validate all metrics are being scraped in production
   - Check Prometheus recording rules are deployed

2. **Deployment:**
   - Import new dashboard JSON via Grafana API or provisioning
   - Verify dashboard appears in Grafana UI
   - Check all panels render without errors
   - Validate refresh rate is 5 seconds

3. **Post-Deployment:**
   - Monitor Grafana logs for errors
   - Check Prometheus query load (should not spike)
   - Verify alert annotations appear correctly
   - Test rollback procedure (restore backup JSON)

4. **Rollback Procedure:**
   - Keep backup of original 8-panel dashboard JSON
   - If issues occur, restore backup via Grafana API:
     ```bash
     curl -X POST -H "Content-Type: application/json" \
       -d @backup-dashboard.json \
       http://grafana:3000/api/dashboards/db
     ```
   - Verify original dashboard is restored
   - Document rollback reason for post-mortem

## Summary

This design provides a comprehensive evolution of the Grafana dashboard from basic monitoring to HFT/SIEM-grade observability while preserving the existing dark theme and layout. The design adds 5 new rows with ~20 new panels for trust score decomposition, anomaly score decomposition, layer-specific telemetry, Kafka monitoring, and pipeline bottleneck detection.

**Key Features:**
- **Forensic visibility:** Trust and anomaly decomposition panels enable root-cause analysis
- **Layer-specific depth:** Dedicated telemetry for each pipeline layer (1-6)
- **Production-grade:** SRE playbooks, alert integration, correlation support
- **Evolutionary approach:** Preserves existing 8 panels, adds new rows
- **Dark theme consistency:** Maintains existing visual style and color conventions

**Testing Strategy:**
- Dashboard validation (PromQL queries, panel rendering, layout)
- Integration testing (Prometheus, alerts, backward compatibility)
- User acceptance testing (SRE playbooks, forensic analysis)
- Snapshot testing (JSON structure consistency)
- Production deployment testing (pre/post-deployment validation, rollback)

**Implementation Approach:**
- Create panel JSON configurations for all new panels (Rows 3-7)
- Update existing dashboard JSON to add new rows
- Deploy via Grafana provisioning or API
- Validate with SRE team using operational playbooks
- Document baseline metric values for production monitoring

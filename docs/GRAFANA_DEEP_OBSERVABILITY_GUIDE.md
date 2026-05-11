# Grafana Deep Observability Dashboard - User Guide

**Dashboard**: `Algo Trading Deep Observability`  
**UID**: `algo-deep-observability`  
**Style**: Dark theme, production-grade HFT/SIEM observability  
**Auto-refresh**: 5 seconds

---

## Overview

This dashboard provides forensic-level visibility into your algorithmic trading platform with deep telemetry across all layers. It preserves the existing dark theme and layout philosophy while adding comprehensive observability for root-cause analysis, anomaly attribution, and operational resilience.

---

## Dashboard Structure

### ROW 1: Pipeline Health Overview
**Purpose**: High-level throughput monitoring  
**Panels**:
- **Layer 1 Ingestion Rates**: Ticks received and published to Kafka by exchange
- **Validated And Scored Throughput**: Validated and scored tick rates

**Use Case**: Quick health check - are ticks flowing through the pipeline?

---

### ROW 2: Trust & Anomaly Overview
**Purpose**: System state and score monitoring  
**Panels**:
- **Trust Score By Symbol**: Final trust score timeline
- **Anomaly Components By Symbol**: Anomaly, IF, and HST scores
- **System State**: Current decision gate state (NORMAL/CONSERVATIVE/DEGRADED/HALT)

**Use Case**: Monitor system health and state transitions

---

### ROW 3: Trust Score Decomposition (FORENSIC)
**Purpose**: Deep trust score forensics for root-cause analysis  
**Panels**:
- **Trust Score Decomposition**: All T1-T5 components + final score on same graph
  - **T1 (Purple)**: TLS validity
  - **T2 (Green)**: Consensus agreement
  - **T3 (Yellow)**: Freshness/latency
  - **T4 (Orange)**: Sequence integrity
  - **T5 (Red)**: Hash chain continuity
  - **Final (Blue, bold)**: Weighted trust score
- **Current Trust Components**: Instant values with color-coded thresholds
- **Trust Degradation Events**: Bar chart showing degradation events by cause

**Use Case**: When trust drops, identify which component caused it

**Forensic Workflow**:
1. Trust score drops → Check decomposition panel
2. Identify lowest component (e.g., T2 drops to 0.3)
3. Check degradation events bar chart → confirms T2 as primary cause
4. Navigate to Row 5 → Check consensus divergence details
5. Root cause: One exchange diverged >100 bps

---

### ROW 4: Anomaly Score Decomposition (FORENSIC)
**Purpose**: Deep anomaly detection forensics  
**Panels**:
- **Anomaly Score Decomposition**: IF, HST, MAD guard, and fused score
  - **Fused Score (Red, bold)**: Final anomaly score
  - **Isolation Forest (Orange-Red)**: Global outlier detection
  - **Half-Space Trees (Gold)**: Local anomaly detection
  - **MAD Guard (Purple, dashed)**: Extreme outlier guard
- **HMM Regime State**: State timeline (Low Vol/Normal/High Vol)
- **Anomaly Feature Vector**: Raw return, rolling vol, spread div, volume anom, trust deg

**Use Case**: When anomaly spikes, identify which model triggered and why

**Forensic Workflow**:
1. Anomaly score spikes to 0.95 → Check decomposition panel
2. IF score = 0.98, HST score = 0.45 → IF triggered (global outlier)
3. Check feature vector → Raw return = 5.2 (extreme)
4. Check regime state → Transitioned from Normal → High Vol
5. Root cause: Large price movement during regime transition

---

### ROW 5: Layer 1 Deep Telemetry
**Purpose**: Ingestion and validation health monitoring  
**Panels**:
- **Exchange Connection Health**: UP/DOWN status for all exchanges
- **TLS Failures & WebSocket Reconnects**: Connection stability
- **Consensus Divergence Details**: Divergent source count + max divergence (bps)

**Use Case**: Diagnose exchange connectivity and consensus issues

**Operational Scenarios**:
- **High reconnect rate**: Exchange or network instability
- **TLS failures**: Certificate rotation needed (run `refresh_spki_pins.py`)
- **High divergence**: Price manipulation or exchange outage

---

### ROW 6: Layer 2 Deep Telemetry
**Purpose**: Anomaly detection performance monitoring  
**Panels**:
- **Model Inference Latency**: P95/P99 inference time
- **HMM Regime Transitions**: Regime change frequency

**Use Case**: Monitor model performance and regime behavior

**Performance Thresholds**:
- **P95 < 10ms**: Excellent
- **P95 10-50ms**: Good
- **P95 50-100ms**: Warning
- **P95 > 100ms**: Critical (model degradation or resource contention)

---

### ROW 7: Pipeline Performance & Kafka
**Purpose**: End-to-end latency and backpressure monitoring  
**Panels**:
- **Pipeline Latency**: Layer 1 and Layer 2 processing latency
- **Kafka Buffer Depths**: Queue depths for backpressure detection

**Use Case**: Identify pipeline bottlenecks

**Bottleneck Detection**:
- **L1 latency > 100ms**: Consensus or trust scoring slow
- **L2 lag > 500ms**: Anomaly detection slow (check model inference latency)
- **Buffer depth > 500**: Backpressure building (downstream consumer slow)

---

### ROW 8: Error Rates & Rejections
**Purpose**: Error and rejection monitoring  
**Panels**:
- **Error Rates & Tick Rejections**: All error types on one graph

**Use Case**: Monitor data quality and pipeline health

**Error Types**:
- **Raw publish errors**: Kafka connectivity issues
- **JSON publisher errors**: Serialization or Kafka issues
- **Bad raw ticks**: Malformed exchange data
- **Bad validated ticks**: Schema validation failures
- **Tick rejections**: Rejected by reason (malformed, stale, duplicate, etc.)

---

## Annotations

The dashboard includes automatic annotations for critical events:

1. **Trust Degradation Events** (Red markers)
   - Triggered when `trust_degradation_events_total > 0`
   - Shows which component caused the drop (T1-T5)

2. **Anomaly Spike Events** (Dark red markers)
   - Triggered when `anomaly_fused_score > 0.9`
   - Shows anomaly score value

**Use Case**: Correlate events across panels visually

---

## Variables

**Symbol Selector**: Choose between BTC-USDT and ETH-USDT  
**Location**: Top of dashboard  
**Note**: Some panels are hardcoded to BTC-USDT for forensic depth. Update queries manually if needed.

---

## SRE Operational Playbooks

### Playbook 1: Trust Score Sudden Drop

**Symptom**: Trust score drops from 0.85 to 0.55

**Investigation**:
1. Navigate to **Row 3: Trust Score Decomposition**
2. Identify which component dropped (e.g., T2 = 0.3)
3. Check **Trust Degradation Events** bar chart → Confirms T2 as primary cause
4. Navigate to **Row 5: Consensus Divergence Details**
5. Check divergent source count and max divergence (bps)

**Root Causes by Component**:
- **T1 (TLS)**: Certificate mismatch → Run `refresh_spki_pins.py`
- **T2 (Consensus)**: Price divergence → Check exchange health
- **T3 (Freshness)**: High latency → Check network or exchange performance
- **T4 (Sequence)**: Sequence gaps → Exchange feed quality issue
- **T5 (HashChain)**: Chain break → CRITICAL integrity issue

---

### Playbook 2: Anomaly Score Spike

**Symptom**: Anomaly score spikes from 0.2 to 0.95

**Investigation**:
1. Navigate to **Row 4: Anomaly Score Decomposition**
2. Identify which model triggered (IF vs HST)
3. Check **Anomaly Feature Vector** → Identify outlier feature
4. Check **HMM Regime State** → Verify regime transition
5. Correlate with **Trust Score** → Check if trust dropped simultaneously

**Root Causes by Feature**:
- **Raw Return**: Large price movement (check if legitimate market event)
- **Rolling Volatility**: Volatility regime change (check HMM state)
- **Spread Divergence**: Bid-ask spread anomaly (liquidity issue or manipulation)
- **Volume Anomaly**: Unusual volume (check exchange for news/events)
- **Trust Degradation**: Trust dropped (follow Playbook 1)

---

### Playbook 3: Pipeline Bottleneck

**Symptom**: Kafka consumer lag increasing, latency spiking

**Investigation**:
1. Navigate to **Row 7: Pipeline Performance**
2. Check **Pipeline Latency** → Identify which layer is slow
3. Check **Kafka Buffer Depths** → Identify backpressure location
4. Navigate to **Row 6: Model Inference Latency** → Check if Layer 2 is slow
5. Navigate to **Row 8: Error Rates** → Check for errors causing retries

**Root Causes by Stage**:
- **L1 slow**: Consensus or trust scoring bottleneck
- **L2 slow**: Model inference degradation (check P95/P99 latency)
- **Buffer depth high**: Downstream consumer slow or stopped
- **High error rate**: Retries causing throughput degradation

---

### Playbook 4: Exchange Connection Issues

**Symptom**: High reconnect rate or TLS failures

**Investigation**:
1. Navigate to **Row 5: Exchange Connection Health**
2. Check **Exchange Connection Health** → Identify unhealthy exchanges
3. Check **TLS Failures & WebSocket Reconnects** → Identify failure reasons
4. Check **Consensus Divergence** → Verify if divergence increased

**Actions by Failure Type**:
- **TLS failures**: Run `python scripts/refresh_spki_pins.py` and restart ingestion
- **High reconnects (heartbeat)**: Exchange or network instability (wait or switch exchange)
- **High reconnects (timeout)**: Network congestion (check firewall/DNS)
- **High reconnects (error)**: Exchange API issue (check exchange status page)

---

## Alert Rules (Recommended)

### Critical Alerts (PagerDuty)

```yaml
# Trust score critically low
- alert: TrustScoreCriticallyLow
  expr: layer1_validated_last_trust_score < 0.5
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Trust score critically low for {{ $labels.symbol }}"
    description: "Current: {{ $value }}"

# Anomaly spike
- alert: AnomalyScoreSpike
  expr: anomaly_fused_score > 0.9
  for: 30s
  labels:
    severity: critical
  annotations:
    summary: "Anomaly spike detected for {{ $labels.symbol }}"
    description: "Score: {{ $value }}"

# System state HALT
- alert: SystemStateHalt
  expr: layer2_system_state == 3
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "System in HALT state"
    description: "Trading halted due to trust/anomaly conditions"

# TLS verification failure
- alert: TLSVerificationFailure
  expr: rate(tls_verification_failures_total[5m]) > 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "TLS verification failed for {{ $labels.exchange_id }}"
    description: "Reason: {{ $labels.reason }}"
```

### Warning Alerts (Slack)

```yaml
# High WebSocket reconnect rate
- alert: HighWebSocketReconnectRate
  expr: rate(exchange_websocket_reconnects_total[5m]) * 60 > 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "High reconnect rate for {{ $labels.exchange_id }}"
    description: "{{ $value }} reconnects/min"

# High consensus divergence
- alert: HighConsensusDivergence
  expr: consensus_divergence_max_bps > 100
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "High price divergence for {{ $labels.symbol }}"
    description: "{{ $value }} basis points"

# Model inference latency high
- alert: ModelInferenceLatencyHigh
  expr: histogram_quantile(0.95, rate(anomaly_model_inference_duration_ms_bucket[5m])) > 100
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Model inference latency degraded"
    description: "P95 latency: {{ $value }}ms"
```

---

## Performance Impact

**Metrics Exported**: ~56 metrics across all layers  
**Dashboard Panels**: 23 panels  
**Refresh Rate**: 5 seconds  
**Query Load**: ~50 PromQL queries per refresh  
**Prometheus Scrape Interval**: 15 seconds (default)

**Resource Usage**:
- **Prometheus**: ~100MB additional memory for metric storage
- **Grafana**: Negligible (queries are efficient)
- **Services**: <1% CPU overhead for metric export

---

## Accessing the Dashboard

1. Open Grafana: `http://localhost:3000`
2. Login: `admin` / `admin` (default)
3. Navigate to **Dashboards** → **Algo Trading** folder
4. Select **Algo Trading Deep Observability**

---

## Customization

### Adding More Symbols

Edit the dashboard variable:
1. Click gear icon (⚙️) → **Variables**
2. Edit `symbol` variable
3. Add symbols to the comma-separated list
4. Save dashboard

### Changing Refresh Rate

1. Click time picker (top right)
2. Select refresh interval (5s, 10s, 30s, 1m, etc.)
3. Dashboard will auto-refresh at selected interval

### Exporting Dashboard

1. Click share icon → **Export**
2. Select **Export for sharing externally**
3. Save JSON file
4. Import on another Grafana instance

---

## Troubleshooting

### Panels Show "No Data"

**Cause**: Metrics not being exported or Prometheus not scraping

**Fix**:
1. Check service is running: `docker compose ps`
2. Check metrics endpoint: `curl http://localhost:9102/metrics | grep trust_subscore`
3. Check Prometheus targets: `http://localhost:9090/targets`
4. Verify scrape config in `ops/prometheus/prometheus.yml`

### Panels Show Old Data

**Cause**: Services restarted and metrics reset

**Fix**: Metrics are gauges/counters that reset on restart. Wait for new data to accumulate.

### Dashboard Not Auto-Provisioned

**Cause**: Grafana provisioning not configured correctly

**Fix**:
1. Check `ops/grafana/provisioning/dashboards/dashboards.yml` exists
2. Verify dashboard JSON is in `ops/grafana/provisioning/dashboards/`
3. Restart Grafana: `docker compose restart grafana`
4. Check Grafana logs: `docker compose logs grafana`

---

## References

- **Metrics Spec**: `docs/OBSERVABILITY_METRICS_SPEC.md`
- **Implementation Guide**: `docs/OBSERVABILITY_IMPLEMENTATION_GUIDE.md`
- **Phase 2 Summary**: `docs/PHASE2_COMPLETION_SUMMARY.md`
- **Phase 3 Layer 1 Summary**: `docs/PHASE3_LAYER1_COMPLETION.md`
- **Dashboard Panels Spec**: `docs/GRAFANA_DASHBOARD_PANELS.md`

---

**Dashboard Version**: 1.0  
**Last Updated**: May 10, 2026  
**Status**: Production-ready

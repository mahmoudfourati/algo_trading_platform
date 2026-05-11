# Grafana Deep Observability - Quick Start Guide

**Status**: ✅ Running  
**Date**: May 10, 2026

---

## 🚀 Access Your Dashboards

### Grafana Web Interface
**URL**: http://localhost:3000  
**Username**: `admin`  
**Password**: `admin`

### Available Dashboards

1. **Algo Trading Pipeline Overview** (Original)
   - UID: `algo-pipeline-overview`
   - High-level pipeline monitoring
   - 8 panels covering basic metrics

2. **Algo Trading Deep Observability** (NEW) ⭐
   - UID: `algo-deep-observability`
   - Production-grade forensic observability
   - 23 panels across 8 rows
   - HFT/SIEM-level telemetry

---

## 📊 Dashboard Navigation

### Quick Access Path
1. Open http://localhost:3000
2. Login with `admin` / `admin`
3. Click **Dashboards** (left sidebar)
4. Navigate to **Algo Trading** folder
5. Select **Algo Trading Deep Observability**

### Dashboard Rows

**ROW 1: Pipeline Health Overview**
- Layer 1 Ingestion Rates
- Validated And Scored Throughput

**ROW 2: Trust & Anomaly Overview**
- Trust Score By Symbol
- Anomaly Components By Symbol
- System State

**ROW 3: Trust Score Decomposition (FORENSIC)** ⭐
- All T1-T5 components + final score
- Current trust components (stat panel)
- Trust degradation events (bar chart)

**ROW 4: Anomaly Score Decomposition (FORENSIC)** ⭐
- IF, HST, MAD guard, fused score
- HMM regime state timeline
- Anomaly feature vector

**ROW 5: Layer 1 Deep Telemetry** ⭐
- Exchange connection health
- TLS failures & WebSocket reconnects
- Consensus divergence details

**ROW 6: Layer 2 Deep Telemetry** ⭐
- Model inference latency (P95/P99)
- HMM regime transitions

**ROW 7: Pipeline Performance & Kafka**
- Pipeline latency
- Kafka buffer depths

**ROW 8: Error Rates & Rejections**
- All error types and tick rejections

---

## 🔍 Key Features

### Forensic Visibility
- **Trust Score Decomposition**: See which T1-T5 component caused trust drops
- **Anomaly Attribution**: Identify which model (IF/HST/MAD) triggered alerts
- **Feature Vector Analysis**: Root-cause anomaly spikes by feature

### Color Coding
- **Trust Components**:
  - T1 (TLS): Purple
  - T2 (Consensus): Green
  - T3 (Freshness): Yellow
  - T4 (Sequence): Orange
  - T5 (HashChain): Red
  - Final Trust: Blue (bold)

- **System States**:
  - NORMAL: Green
  - CONSERVATIVE: Yellow
  - DEGRADED: Orange
  - HALT: Red

- **HMM Regimes**:
  - Low Vol: Green
  - Normal: Yellow
  - High Vol: Red

### Annotations
- **Trust Degradation Events**: Red markers showing which component dropped
- **Anomaly Spikes**: Dark red markers when anomaly > 0.9

---

## 📈 Current System Status

### Services Running
```
✓ Grafana          - http://localhost:3000
✓ Prometheus       - http://localhost:9090
✓ Kafka            - localhost:29092
✓ Layer 1 Ingestion - :9101/metrics
✓ Layer 1 Validated - :9102/metrics
✓ Layer 2 Anomaly   - :9103/metrics
✓ Layer 4 Risk      - :9104/metrics
✓ Layer 5 Execution - :9105/metrics
```

### Metrics Exported
- **Layer 1**: Trust subscores (T1-T5), consensus divergence, TLS health
- **Layer 2**: Anomaly subscores (IF, HST, MAD), HMM regime, feature vector
- **Pipeline**: Latency, buffer depths, error rates

### Current Observations
- **System State**: HALT (3.0) - No validated ticks yet (primary exchange not in consensus)
- **Trust Subscores**: Not yet populated (waiting for valid consensus)
- **Anomaly Metrics**: Initialized but no data yet

---

## 🛠️ Troubleshooting

### No Data in Panels

**Cause**: Services just started, waiting for data flow

**Solution**: Wait 30-60 seconds for:
1. Layer 1 ingestion to connect to exchanges
2. Consensus windows to form
3. Validated ticks to be published
4. Layer 2 to process and score ticks

**Check Progress**:
```powershell
# Check Layer 1 ingestion logs
docker compose logs layer1-ingestion --tail 20

# Check Layer 1 validated logs
docker compose logs layer1-validated --tail 20

# Check metrics directly
Invoke-WebRequest http://localhost:9102/metrics | Select-String "trust_subscore"
```

### Primary Exchange Not in Consensus

**Symptom**: `layer1_validated_primary_source_skipped_total` increasing

**Cause**: Primary exchange (binance) not participating in consensus

**Solution**: 
1. Check exchange connection health in Row 5
2. Verify TLS pins are valid
3. Check ingestion logs for connection issues

### Dashboard Not Loading

**Solution**:
```powershell
# Restart Grafana
docker compose restart grafana

# Check Grafana logs
docker compose logs grafana --tail 50
```

---

## 📚 Documentation

- **Full Dashboard Guide**: `docs/GRAFANA_DEEP_OBSERVABILITY_GUIDE.md`
- **Metrics Specification**: `docs/OBSERVABILITY_METRICS_SPEC.md`
- **Implementation Guide**: `docs/OBSERVABILITY_IMPLEMENTATION_GUIDE.md`
- **SRE Playbooks**: See dashboard guide for operational scenarios

---

## 🎯 Next Steps

1. **Wait for Data**: Let the system run for 1-2 minutes to accumulate data
2. **Explore Dashboards**: Navigate through all 8 rows
3. **Test Forensics**: Watch for trust drops or anomaly spikes
4. **Review Playbooks**: Familiarize yourself with operational scenarios

---

## 🔧 Useful Commands

### View Logs
```powershell
# All services
docker compose logs -f

# Specific service
docker compose logs -f layer1-validated
docker compose logs -f layer2-anomaly
docker compose logs -f grafana
```

### Check Metrics
```powershell
# Layer 1 Validated (Trust scores)
Invoke-WebRequest http://localhost:9102/metrics

# Layer 2 Anomaly (Anomaly scores)
Invoke-WebRequest http://localhost:9103/metrics

# Prometheus targets
Start-Process http://localhost:9090/targets
```

### Restart Services
```powershell
# Restart all
docker compose restart

# Restart specific service
docker compose restart grafana
docker compose restart layer1-validated
```

### Stop Everything
```powershell
docker compose down
```

---

**Dashboard Status**: ✅ Provisioned and Ready  
**Metrics Status**: ✅ Exporting  
**System Status**: 🟡 Waiting for data flow

**Enjoy your production-grade observability! 🚀**

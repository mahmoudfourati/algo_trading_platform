# Grafana Dashboards Summary

**Last Updated**: May 13, 2026

---

## 📊 Available Dashboards

### 1. **Algo Trading Deep Observability** ⭐
**UID**: `algo-deep-observability`  
**URL**: http://localhost:3000/d/algo-deep-observability

**Purpose**: Production-grade forensic observability for the entire trading pipeline

**Key Features**:
- 23 panels across 8 rows
- Trust score decomposition (T1-T5)
- Anomaly score breakdown (IF, HST, MAD)
- HMM regime tracking
- Exchange health matrix
- Pipeline latency and performance

**Best For**:
- System-wide monitoring
- Debugging trust/anomaly issues
- Performance analysis
- SRE operations

---

### 2. **Algo Trading Pipeline Overview**
**UID**: `algo-pipeline-overview`  
**URL**: http://localhost:3000/d/algo-pipeline-overview

**Purpose**: High-level pipeline monitoring

**Key Features**:
- 8 basic panels
- Layer 1 ingestion rates
- Validated and scored throughput
- Trust and anomaly scores
- System state
- Pipeline latency
- Error rates

**Best For**:
- Quick health checks
- Executive overview
- Simple monitoring

---

### 3. **Algorithmic Trading Platform — Operations**
**UID**: `algo-trading-ops`  
**URL**: http://localhost:3000/d/algo-trading-ops

**Purpose**: Operational dashboard for trading platform

**Key Features**:
- System operational state
- Pipeline health score
- Active exchanges
- Kafka health
- Total throughput
- Exchange health matrix
- Trust engine metrics

**Best For**:
- Operations team
- Platform health monitoring
- Exchange connectivity

**Note**: Some metrics may show "No data" if using outdated metric names. Use Deep Observability dashboard for most reliable data.

---

### 4. **Layer 1 - Trust Engine** ✨ NEW
**UID**: `layer1-trust`  
**URL**: http://localhost:3000/d/layer1-trust

**Purpose**: Dedicated monitoring for Layer 1 trust scoring and consensus validation

**Key Features**:
- Trust score gauge and history
- Trust subscores (T1-T5 + T_Availability) breakdown
- Consensus metrics (sources used, divergent, quarantined)
- Exchange health and latency
- Trust degradation events
- TLS validation and hash chain monitoring

**Best For**:
- Understanding trust score composition
- Debugging trust degradation
- Monitoring consensus quality
- Exchange connectivity issues

**Documentation**: `docs/LAYER1_DASHBOARD_GUIDE.md`

---

### 5. **Layer 2 - Anomaly Detection** ✨ NEW
**UID**: `layer2-anomaly`  
**URL**: http://localhost:3000/d/layer2-anomaly

**Purpose**: Dedicated monitoring for Layer 2 anomaly detection and HMM regime classification

**Key Features**:
- System state and decision gate
- Anomaly score decomposition (IF, HST, MAD guard)
- HMM regime tracking and transitions
- Feature vector observability (6 features)
- Model inference latency
- Trust score monitoring
- Decision gate trigger analysis

**Best For**:
- Data scientists monitoring model behavior
- Quants analyzing market regime detection
- Understanding system state changes
- Debugging anomaly detection issues

**Documentation**: `docs/LAYER2_DASHBOARD_GUIDE.md`

---

### 6. **Layer 3 - Trading Strategy** ✨ NEW
**UID**: `layer3-strategy`  
**URL**: http://localhost:3000/d/layer3-strategy

**Purpose**: Dedicated monitoring for Layer 3 strategy and signal generation

**Key Features**:
- Service health and tick consumption
- Technical indicators (RSI, MACD, Bollinger Bands)
- Order Flow Imbalance (OFI)
- Signal generation breakdown
- EMA crossover events
- Current indicator gauges

**Best For**:
- Strategy development
- Signal analysis
- Understanding why no trades are generated
- Technical indicator monitoring

**Documentation**: `docs/LAYER3_DASHBOARD_GUIDE.md`

---

### 7. **Layer 4 - Risk Management** ✨ NEW
**UID**: `layer4-risk`  
**URL**: http://localhost:3000/d/layer4-risk

**Purpose**: Dedicated monitoring for Layer 4 risk management and circuit breaker

**Key Features**:
- **Circuit breaker status** (CRITICAL)
- Portfolio risk metrics (drawdown, daily loss, consecutive losses)
- Signal approvals and rejections
- Risk limit violations
- Risk check latency
- Rejection reasons breakdown

**Best For**:
- Risk monitoring
- Circuit breaker alerts
- Understanding trade rejections
- Portfolio protection

**Documentation**: `docs/LAYER4_DASHBOARD_GUIDE.md`

---

### 8. **Layer 5 - Order Execution** ✨ NEW
**UID**: `layer5-execution`  
**URL**: http://localhost:3000/d/layer5-execution

**Purpose**: Dedicated monitoring for Layer 5 order execution and fills

**Key Features**:
- Order flow (placed, filled, failed)
- Execution quality (fill rate, slippage)
- Order placement latency (P50, P95, P99)
- Failures and retries breakdown
- Pending orders and WAL depth
- Orders by direction and symbol

**Best For**:
- Execution quality monitoring
- Slippage analysis
- Order failure debugging
- Performance optimization

**Documentation**: `docs/LAYER5_DASHBOARD_GUIDE.md`

---

### 9. **Layer 6 - Audit & Compliance** ✨ NEW
**UID**: `layer6-audit`  
**URL**: http://localhost:3000/d/layer6-audit

**Purpose**: Dedicated monitoring for Layer 6 audit logging and hash chain integrity

**Key Features**:
- Hash chain integrity monitoring
- Chain continuity breaks (CRITICAL)
- Audit event throughput
- Log write latency (P50, P95, P99)
- Log rotation and file size
- Compliance summary

**Best For**:
- Compliance monitoring
- Audit trail verification
- Hash chain integrity checks
- Tamper detection

**Documentation**: `docs/LAYER6_DASHBOARD_GUIDE.md`

---

## 🎯 Dashboard Selection Guide

### For Different Roles:

**Traders / Strategy Developers**:
1. Layer 3 - Trading Strategy (primary)
2. Layer 2 - Anomaly Detection (for market regime)
3. Layer 4 - Risk Management (secondary)
4. Deep Observability (for debugging)

**Data Scientists / Quants**:
1. Layer 2 - Anomaly Detection (primary)
2. Layer 3 - Trading Strategy (secondary)
3. Deep Observability (for feature analysis)

**Risk Managers**:
1. Layer 4 - Risk Management (primary)
2. Layer 2 - Anomaly Detection (for system state)
3. Deep Observability (for trust scores)
4. Pipeline Overview (for system health)

**SRE / Operations**:
1. Deep Observability (primary)
2. Operations Dashboard (secondary)
3. Pipeline Overview (for quick checks)

**Executives / Management**:
1. Pipeline Overview (primary)
2. Operations Dashboard (secondary)

---

## 🚀 Quick Start

### First Time Setup:
1. Open http://localhost:3000
2. Login: `admin` / `admin`
3. Navigate to **Dashboards** (left sidebar)
4. Browse available dashboards

### Recommended Monitoring Setup:

**Single Monitor**:
- Use Deep Observability dashboard

**Dual Monitor**:
- Monitor 1: Deep Observability
- Monitor 2: Layer 2 Anomaly or Layer 3 Strategy

**Triple Monitor**:
- Monitor 1: Deep Observability
- Monitor 2: Layer 2 Anomaly Detection
- Monitor 3: Layer 3 Strategy

**Quad Monitor** (Full Stack):
- Monitor 1: Deep Observability
- Monitor 2: Layer 2 Anomaly Detection
- Monitor 3: Layer 3 Strategy
- Monitor 4: Layer 4 Risk

---

## 📈 Current System Status

### Data Availability:

**Layers 1 & 2**: ✅ Full data available
- Trust scores
- Anomaly scores
- Tick processing
- Exchange health

**Layer 3**: ✅ Full data available
- Technical indicators
- Signal generation (all HOLD)
- OFI tracking
- EMA crossovers

**Layer 4**: ✅ Full data available
- Risk metrics (all at 0, no signals yet)
- Circuit breaker (NORMAL)
- Service health

**Layers 5, 6, 7**: ⚠️ Limited data
- Services running but no orders yet
- Waiting for Layer 3 to generate signals

---

## 🔍 Why Some Panels Show "No Data"

### Expected "No Data" Scenarios:

1. **Layer 3 Signals Published = 0**
   - **Reason**: Strategy only publishes LONG/SHORT signals, not HOLD
   - **Current**: All signals are HOLD (neutral market)
   - **Normal**: Yes, this is expected

2. **Layer 4 Approvals/Rejections = 0**
   - **Reason**: No signals from Layer 3 to process
   - **Normal**: Yes, waiting for Layer 3 signals

3. **Layer 5 Execution Metrics = 0**
   - **Reason**: No approved orders from Layer 4
   - **Normal**: Yes, waiting for Layer 4 approvals

4. **Operations Dashboard - Some Panels**
   - **Reason**: Using outdated metric names
   - **Solution**: Use Deep Observability or Layer-specific dashboards

---

## 🛠️ Troubleshooting

### Dashboard shows "No data" everywhere:
1. Check time range (use "Last 15 minutes" or "Last 5 minutes")
2. Verify services are running: `docker compose ps`
3. Check Prometheus targets: http://localhost:9090/targets
4. Restart Grafana: `docker compose restart grafana`

### Specific panel shows "No data":
1. Check if metric exists: http://localhost:9090/graph
2. Verify service is exporting metric: http://localhost:910X/metrics
3. Check Prometheus is scraping: http://localhost:9090/targets
4. Review dashboard query syntax

### Dashboard not loading:
1. Check Grafana logs: `docker compose logs grafana --tail 50`
2. Verify dashboard JSON is valid
3. Restart Grafana: `docker compose restart grafana`

---

## 📚 Documentation

### Dashboard Guides:
- `docs/GRAFANA_DEEP_OBSERVABILITY_GUIDE.md` - Deep Observability dashboard
- `docs/GRAFANA_DASHBOARD_PANELS.md` - Panel descriptions
- `docs/LAYER2_DASHBOARD_GUIDE.md` - Layer 2 Anomaly Detection dashboard
- `docs/LAYER3_DASHBOARD_GUIDE.md` - Layer 3 Strategy dashboard
- `docs/LAYER4_DASHBOARD_GUIDE.md` - Layer 4 Risk dashboard

### Implementation Guides:
- `docs/OBSERVABILITY_IMPLEMENTATION_GUIDE.md` - How observability is implemented
- `docs/OBSERVABILITY_METRICS_SPEC.md` - Metrics specification
- `GRAFANA_QUICK_START.md` - Quick start guide

---

## 🎨 Customization

### Adding New Dashboards:
1. Create JSON file in `ops/grafana/provisioning/dashboards/`
2. Restart Grafana: `docker compose restart grafana`
3. Dashboard will auto-load

### Modifying Existing Dashboards:
1. Edit in Grafana UI (will be lost on restart)
2. Export JSON and save to `ops/grafana/provisioning/dashboards/`
3. Restart Grafana to persist changes

### Creating Alerts:
1. Open dashboard panel
2. Click "Alert" tab
3. Configure alert rules
4. Set notification channels

---

## 🔄 Refresh Rates

**Default Refresh Rates**:
- Deep Observability: 5s
- Pipeline Overview: 5s
- Operations: 10s
- Layer 2 Anomaly: 5s
- Layer 3 Strategy: 5s
- Layer 4 Risk: 5s

**Recommended for Production**:
- Real-time monitoring: 5s
- Historical analysis: Manual refresh
- Resource-constrained: 30s

---

## 📊 Metrics Coverage

### Layer 1 (Ingestion & Validation):
- ✅ Tick rates
- ✅ Trust scores (T1-T5)
- ✅ Exchange health
- ✅ Consensus metrics
- ✅ TLS validation

### Layer 2 (Anomaly Detection):
- ✅ Anomaly scores (IF, HST, MAD)
- ✅ HMM regime tracking
- ✅ Feature vectors
- ✅ System state
- ✅ Model inference latency

### Layer 3 (Strategy):
- ✅ Technical indicators (RSI, MACD, BB)
- ✅ Signal generation
- ✅ OFI tracking
- ✅ EMA crossovers

### Layer 4 (Risk):
- ✅ Circuit breaker state
- ✅ Portfolio risk metrics
- ✅ Approvals/rejections
- ✅ Risk violations
- ✅ Check latency

### Layer 5 (Execution):
- ⚠️ Order metrics (waiting for orders)
- ⚠️ Fill rates (waiting for orders)
- ⚠️ Slippage (waiting for orders)

---

**Dashboard Status**: ✅ All dashboards operational  
**Prometheus**: ✅ Scraping all targets  
**Grafana**: ✅ Running on port 3000

**Happy Monitoring! 📊🚀**

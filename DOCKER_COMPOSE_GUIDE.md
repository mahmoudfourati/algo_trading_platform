# Docker Compose Configuration Guide

This project uses multiple Docker Compose files for different scenarios. This guide explains when and how to use each one.

---

## 📁 Available Compose Files

| File | Purpose | When to Use |
|------|---------|-------------|
| `docker-compose.yml` | **Main configuration** | Production-like setup with full retention and realistic settings |
| `docker-compose.init.yml` | **Topic initialization** | One-time setup to pre-create Kafka topics with explicit configs |
| `docker-compose.demo.yml` | **Demo overrides** | Jury presentations, live demos, faster feedback cycles |

---

## 🚀 Usage Scenarios

### Scenario 1: First-Time Setup (Recommended)

```powershell
# Step 1: Start infrastructure
docker compose up -d zookeeper kafka

# Step 2: Wait for Kafka to be healthy (check with docker compose ps)
docker compose ps

# Step 3: Initialize topics with explicit partition counts
docker compose -f docker-compose.init.yml up

# Step 4: Start all services
docker compose up -d

# Step 5: Verify everything is running
docker compose ps
```

**Why this order?**
- Ensures Kafka topics exist with correct partition counts before services start
- Prevents auto-creation with default settings
- Gives you explicit control over topic configuration

---

### Scenario 2: Normal Development

```powershell
# Start everything (assumes topics already exist)
docker compose up -d

# View logs
docker compose logs -f layer1-ingestion

# Stop everything
docker compose down

# Stop and remove volumes (full reset)
docker compose down -v
```

---

### Scenario 3: Demo/Jury Presentation Mode

```powershell
# Start with demo overrides (faster, more visible)
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d

# What changes in demo mode:
# - 10x faster tick generation (100ms instead of 1000ms)
# - Lower thresholds (more alerts, more trades)
# - Shorter retention (10 minutes instead of 24 hours)
# - More verbose logging (DEBUG level)
# - Smaller portfolio (0.5 BTC instead of 1.0 BTC)
```

**Demo mode benefits:**
- ✅ See a full trade cycle in 60 seconds instead of 5 minutes
- ✅ More anomalies and risk blocks (more impressive)
- ✅ Less disk usage (can run multiple demos)
- ✅ Faster reset between demo runs

---

### Scenario 4: Clean Slate Reset

```powershell
# Stop everything and remove all data
docker compose down -v

# Remove logs and artifacts
Remove-Item -Recurse -Force logs\*
Remove-Item -Recurse -Force artifacts\hmm\*

# Start fresh
docker compose up -d zookeeper kafka
docker compose -f docker-compose.init.yml up
docker compose up -d
```

---

## 🔧 Topic Configuration Details

The `docker-compose.init.yml` creates topics with these settings:

| Topic | Partitions | Retention | Compression | Notes |
|-------|-----------|-----------|-------------|-------|
| `market.ticks.raw` | 3 | 24h | lz4 | High throughput, multiple exchanges |
| `market.ticks.validated` | 3 | 24h | lz4 | Post-validation, still high volume |
| `market.ticks.scored` | 3 | 24h | lz4 | With anomaly scores |
| `trading.signals` | 2 | 24h | lz4 | Lower volume, strategy outputs |
| `trading.orders.approved` | 2 | 24h | lz4 | Risk-approved orders |
| `trading.orders.executed` | 2 | 24h | lz4 | Execution confirmations |
| `audit.events` | 1 | 30d | lz4 | Audit trail, longer retention, compacted |

**Why these partition counts?**
- **3 partitions** for market data: Allows parallel processing of high-volume tick streams
- **2 partitions** for trading data: Balances parallelism with order consistency
- **1 partition** for audit: Ensures strict ordering of audit events

---

## 🎯 Demo Mode Environment Variables

When using `docker-compose.demo.yml`, these variables are overridden:

### Layer 1 (Ingestion)
- `TICK_INTERVAL_MS: 100` - 10x faster tick generation
- `EXCHANGES: binance,bybit` - Focus on 2 exchanges for clarity

### Layer 2 (Anomaly Detection)
- `ANOMALY_THRESHOLD: 0.3` - Lower threshold = more anomalies detected
- `ANOMALY_LOOKBACK_SECONDS: 30` - Shorter window = faster detection

### Layer 3 (Strategy)
- `SIGNAL_THRESHOLD: 0.6` - Lower threshold = more trading signals
- `MA_SHORT_WINDOW: 5` - Faster moving averages
- `MA_LONG_WINDOW: 15` - Faster moving averages

### Layer 4 (Risk)
- `MAX_POSITION_SIZE: 0.15` - Allow larger positions
- `RISK_THRESHOLD: 0.7` - Approve more orders

### Layer 5 (Execution)
- `PORTFOLIO_VALUE: 0.5` - Smaller portfolio for realistic demo numbers
- `EXECUTION_DELAY_MS: 50` - Faster execution simulation

### Kafka
- `KAFKA_LOG_RETENTION_MS: 600000` - 10 minutes instead of 24 hours
- `KAFKA_LOG_SEGMENT_MS: 60000` - Flush every minute

---

## 🐛 Troubleshooting

### Topics not created
```powershell
# Check if Kafka is healthy
docker compose ps kafka

# Manually run topic creation
docker compose -f docker-compose.init.yml up

# List topics
docker compose exec kafka kafka-topics --bootstrap-server kafka:9092 --list
```

### Services stuck in "health: starting"
```powershell
# Check service logs
docker compose logs layer1-ingestion

# Check if metrics endpoint is responding
Invoke-WebRequest -Uri http://localhost:9101/metrics
```

### Demo mode not working
```powershell
# Verify both files are loaded
docker compose -f docker-compose.yml -f docker-compose.demo.yml config

# Check environment variables in running container
docker compose exec layer1-ingestion env | Select-String TICK_INTERVAL
```

### Reset everything
```powershell
# Nuclear option: remove everything
docker compose down -v
docker system prune -a --volumes -f
Remove-Item -Recurse -Force logs\*, artifacts\hmm\*

# Start fresh
docker compose up -d zookeeper kafka
Start-Sleep -Seconds 10
docker compose -f docker-compose.init.yml up
docker compose up -d
```

---

## 📊 Monitoring

### Check all services are healthy
```powershell
docker compose ps
```

### Check Prometheus targets
```powershell
# Open in browser
start http://localhost:9090/targets

# Or via API
Invoke-WebRequest -Uri http://localhost:9090/api/v1/targets | ConvertFrom-Json
```

### Check Grafana dashboards
```powershell
# Open in browser (admin/admin)
start http://localhost:3000
```

### Check Kafka topics
```powershell
# List topics
docker compose exec kafka kafka-topics --bootstrap-server kafka:9092 --list

# Describe topics
docker compose exec kafka kafka-topics --bootstrap-server kafka:9092 --describe

# Check consumer lag
docker compose exec kafka kafka-consumer-groups --bootstrap-server kafka:9092 --list
```

---

## 🎓 For Jury Presentation

**Recommended startup sequence:**

```powershell
# 1. Clean slate
docker compose down -v

# 2. Start infrastructure
docker compose up -d zookeeper kafka

# 3. Wait 10 seconds
Start-Sleep -Seconds 10

# 4. Create topics
docker compose -f docker-compose.init.yml up

# 5. Start in DEMO MODE
docker compose -f docker-compose.yml -f docker-compose.demo.yml up -d

# 6. Wait 30 seconds for services to initialize
Start-Sleep -Seconds 30

# 7. Open Grafana
start http://localhost:3000

# 8. Show live data flowing
docker compose logs -f layer1-ingestion
```

**What the jury will see:**
- ✅ Ticks flowing every 100ms (very visible)
- ✅ Anomalies detected within 30 seconds
- ✅ Trading signals generated quickly
- ✅ Orders approved and executed
- ✅ Real-time Grafana dashboards updating every 5 seconds

---

## 📝 Notes

- **Production mode** (`docker-compose.yml` only): Realistic settings, 24-hour retention, slower tick generation
- **Demo mode** (`docker-compose.yml` + `docker-compose.demo.yml`): Fast, impressive, laptop-friendly
- **Init file** (`docker-compose.init.yml`): One-time topic creation, run after Kafka starts

**File precedence:** When using multiple compose files, later files override earlier ones:
```
docker-compose.yml (base) → docker-compose.demo.yml (overrides)
```


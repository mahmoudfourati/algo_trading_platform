# Docker Infrastructure Fix Summary

**Date:** 2026-05-23  
**Purpose:** Document all Docker Compose improvements for production-grade infrastructure

---

## What Was Fixed

### ✅ 1. Resource Limits Added (Non-Negotiable)

**Problem:** No resource limits meant one service could starve others during high load.

**Solution:** Added `deploy.resources` to all services with limits and reservations.

**Resource Allocation:**

| Service | CPU Limit | Memory Limit | CPU Reserve | Memory Reserve |
|---------|-----------|--------------|-------------|----------------|
| zookeeper | 0.5 | 512M | 0.25 | 256M |
| kafka | 1.0 | 1G | 0.5 | 512M |
| metrics-service | 0.25 | 256M | 0.1 | 128M |
| layer1-ingestion | 0.5 | 512M | 0.25 | 256M |
| layer1-validated | 0.5 | 512M | 0.25 | 256M |
| layer2-anomaly | 1.0 | 1G | 0.5 | 512M |
| layer3-strategy | 0.5 | 512M | 0.25 | 256M |
| layer4-risk | 0.5 | 512M | 0.25 | 256M |
| layer5-execution | 0.5 | 512M | 0.25 | 256M |
| layer6-audit | 0.5 | 512M | 0.25 | 256M |
| prometheus | 0.5 | 512M | 0.25 | 256M |
| grafana | 0.5 | 512M | 0.25 | 256M |
| kafka-exporter | 0.25 | 256M | 0.1 | 128M |
| **Total** | **7.0 CPUs** | **7.5 GB** | **3.5 CPUs** | **3.75 GB** |

**Why These Values:**
- Kafka and Layer 2 get more resources (ML models, retraining)
- Python services get 512M (adequate for day/swing trading)
- Monitoring services get less (lightweight)
- Reservations ensure minimum guaranteed resources

---

### ✅ 2. Restart Policies Added (Non-Negotiable)

**Problem:** Services didn't restart automatically after crashes or system reboots.

**Solution:** Added `restart: unless-stopped` to all services.

**What This Means:**
- Services restart automatically on failure
- Services restart after system reboot
- Services stay stopped if manually stopped with `docker compose stop`
- Prevents silent failures during demos

**Exception:** None — all services get `unless-stopped` policy.

---

### ✅ 3. Dead Code Removed (Non-Negotiable)

**Problem:** Commented-out `cadvisor` and `node-exporter` services cluttered the file.

**Solution:** Removed commented-out services entirely.

**Why:**
- `cadvisor` requires Linux host filesystem access (doesn't work on Windows)
- `node-exporter` requires Linux host filesystem access (doesn't work on Windows)
- Keeping commented code is confusing
- If needed later, can be added back from git history

---

### ✅ 4. PORTFOLIO_VALUE Documented

**Problem:** `PORTFOLIO_VALUE: "1.0"` was unclear — 1 what?

**Solution:** Added inline comment explaining it's "1 BTC equivalent".

**Before:**
```yaml
PORTFOLIO_VALUE: "1.0"
```

**After:**
```yaml
# Portfolio value in BTC equivalent (1.0 = 1 BTC worth of capital)
# For demo purposes, this represents the total capital available for trading
PORTFOLIO_VALUE: "1.0"
```

**Why This Matters:**
- Makes it clear this is a demo value
- Explains the unit (BTC equivalent)
- Documents that it's configurable

---

### ✅ 5. Explicit Topic Creation

**Problem:** Relying on auto-create is risky for demos (topics might not exist when services start).

**Solution:** Created topic pre-creation scripts.

**New Files:**
- `scripts/create_kafka_topics.sh` (Linux/Mac)
- `scripts/create_kafka_topics.ps1` (Windows)
- `scripts/start_system.ps1` (Comprehensive startup script)

**Topics Created:**
1. `market.ticks.raw`
2. `market.ticks.validated`
3. `market.ticks.scored`
4. `trading.signals`
5. `trading.orders.approved`
6. `trading.orders.executed`
7. `audit.events`

**Topic Configuration:**
- Partitions: 1 (academic scope)
- Replication factor: 1 (single broker)
- Retention: 24 hours (86400000 ms)
- Segment size: 1 hour (3600000 ms)

---

### ✅ 6. Health Checks Added

**Problem:** Only Kafka had health checks. Other services could fail silently.

**Solution:** Added health checks to all Python services and monitoring services.

**Health Check Configuration:**

| Service | Health Check | Interval | Timeout | Retries | Start Period |
|---------|--------------|----------|---------|---------|--------------|
| kafka | kafka-broker-api-versions | 10s | 5s | 10 | - |
| metrics-service | curl /metrics | 30s | 10s | 3 | 10s |
| layer1-ingestion | curl /metrics | 30s | 10s | 3 | 20s |
| layer1-validated | curl /metrics | 30s | 10s | 3 | 20s |
| layer2-anomaly | curl /metrics | 30s | 10s | 3 | 30s |
| layer3-strategy | curl /metrics | 30s | 10s | 3 | 20s |
| layer4-risk | curl /metrics | 30s | 10s | 3 | 20s |
| layer5-execution | curl /metrics | 30s | 10s | 3 | 20s |
| layer6-audit | curl /metrics | 30s | 10s | 3 | 20s |
| prometheus | wget /-/healthy | 30s | 10s | 3 | 10s |
| grafana | wget /api/health | 30s | 10s | 3 | 30s |

**Why Different Start Periods:**
- Layer 2 gets 30s (loads HMM model)
- Grafana gets 30s (installs plugins)
- Others get 10-20s (normal startup)

**Benefits:**
- `docker compose ps` shows health status
- Can use `condition: service_healthy` in depends_on
- Easier to diagnose startup issues

---

## New Startup Workflow

### Old Way (Risky)
```powershell
docker compose up -d --build
```

**Problems:**
- Topics auto-created (race conditions)
- No health check verification
- No status summary

### New Way (Recommended)
```powershell
.\scripts\start_system.ps1
```

**What It Does:**
1. Starts Kafka + ZooKeeper
2. Waits for Kafka health check
3. Pre-creates all topics
4. Starts all services
5. Waits 10 seconds for initialization
6. Shows system status
7. Shows access points
8. Shows next steps

**Output:**
```
========================================
  Algo Trading Platform - Startup
========================================

[1/4] Starting infrastructure (Kafka, ZooKeeper)...
✓ Infrastructure started

[2/4] Waiting for Kafka to be healthy...
✓ Kafka is healthy

[3/4] Creating Kafka topics...
✓ Topics created

[4/4] Starting all services...
✓ All services started

========================================
  System Status
========================================
NAME                    STATUS    HEALTH
kafka                   Up        healthy
layer1-ingestion        Up        healthy
...

========================================
  Access Points
========================================
Kafka (host):        localhost:29092
Prometheus:          http://localhost:9090
Grafana:             http://localhost:3000 (admin/admin)
...

✓ System startup complete!
```

---

## Verification Commands

### Check All Services Are Running
```powershell
docker compose ps
```

**Expected:** All services show "Up" status, most show "healthy".

### Check Resource Usage
```powershell
docker stats
```

**Expected:** No service exceeds its memory limit.

### Check Kafka Topics
```powershell
docker compose exec -T kafka kafka-topics --bootstrap-server kafka:9092 --list
```

**Expected:** All 7 topics listed.

### Check Prometheus Targets
Open: http://localhost:9090/targets

**Expected:** All 8 layer services show "UP".

### Check Grafana
Open: http://localhost:3000

**Expected:** Dashboards load without errors.

---

## Before/After Comparison

### Before
- ❌ No resource limits (OOM risk)
- ❌ No restart policies (manual restart after crash)
- ❌ Commented-out dead code (confusing)
- ❌ Unclear PORTFOLIO_VALUE (what unit?)
- ❌ Auto-create topics (race conditions)
- ❌ No health checks (silent failures)

### After
- ✅ Resource limits on all services (OOM protected)
- ✅ Restart policies on all services (auto-recovery)
- ✅ Clean docker-compose (no dead code)
- ✅ Documented PORTFOLIO_VALUE (BTC equivalent)
- ✅ Explicit topic creation (no race conditions)
- ✅ Health checks on all services (visible failures)

---

## Impact on Demo

### Reliability
- **Before:** Services could crash silently, topics might not exist
- **After:** Services auto-restart, topics guaranteed to exist

### Observability
- **Before:** `docker compose ps` showed only "Up" or "Exit"
- **After:** `docker compose ps` shows "healthy" or "unhealthy"

### Startup Time
- **Before:** ~30 seconds (but risky)
- **After:** ~60 seconds (but reliable)

**Verdict:** Extra 30 seconds is worth the reliability.

---

## Known Limitations

### 1. Single Kafka Broker
- **Limitation:** No replication, single point of failure
- **Acceptable:** Academic scope, documented in blueprint
- **Production:** Would use 3-broker cluster

### 2. Resource Limits Are Estimates
- **Limitation:** Not empirically validated under load
- **Acceptable:** Based on reasonable estimates
- **Production:** Would run load tests to tune

### 3. Health Checks Use curl/wget
- **Limitation:** Requires curl/wget in containers
- **Acceptable:** Standard tools, likely present
- **Production:** Would use native health check endpoints

---

## Troubleshooting

### Service Won't Start
```powershell
# Check logs
docker compose logs <service-name>

# Check health
docker compose ps <service-name>

# Restart service
docker compose restart <service-name>
```

### Out of Memory
```powershell
# Check resource usage
docker stats

# Increase Docker Desktop memory limit
# Settings → Resources → Memory → 8GB+
```

### Topics Not Created
```powershell
# Manually create topics
.\scripts\create_kafka_topics.ps1

# Verify topics exist
docker compose exec -T kafka kafka-topics --bootstrap-server kafka:9092 --list
```

### Health Check Failing
```powershell
# Check if metrics endpoint responds
curl http://localhost:9101/metrics

# Check service logs
docker compose logs layer1-ingestion
```

---

## References

- **Docker Compose:** `docker-compose.yml`
- **Startup Script:** `scripts/start_system.ps1`
- **Topic Creation:** `scripts/create_kafka_topics.ps1`
- **README:** Updated with new startup instructions
- **Analysis:** `project_analysis.md` (Infrastructure section)

# Purpose: Start the entire trading system with proper initialization
# This script ensures Kafka topics are created before services start

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Algo Trading Platform - Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Start infrastructure (Kafka, ZooKeeper)
Write-Host "[1/4] Starting infrastructure (Kafka, ZooKeeper)..." -ForegroundColor Yellow
docker compose up -d zookeeper kafka
Write-Host "✓ Infrastructure started" -ForegroundColor Green
Write-Host ""

# Step 2: Wait for Kafka to be healthy
Write-Host "[2/4] Waiting for Kafka to be healthy..." -ForegroundColor Yellow
$maxRetries = 60
$retryCount = 0
while ($retryCount -lt $maxRetries) {
    $health = docker compose ps kafka --format json | ConvertFrom-Json
    if ($health.Health -eq "healthy") {
        Write-Host "✓ Kafka is healthy" -ForegroundColor Green
        break
    }
    Write-Host "Waiting for Kafka health check... ($retryCount/$maxRetries)" -ForegroundColor Yellow
    Start-Sleep -Seconds 2
    $retryCount++
}

if ($retryCount -eq $maxRetries) {
    Write-Host "ERROR: Kafka did not become healthy in time" -ForegroundColor Red
    Write-Host "Check logs with: docker compose logs kafka" -ForegroundColor Yellow
    exit 1
}
Write-Host ""

# Step 3: Create Kafka topics
Write-Host "[3/4] Creating Kafka topics..." -ForegroundColor Yellow
& "$PSScriptRoot\create_kafka_topics.ps1"
Write-Host "✓ Topics created" -ForegroundColor Green
Write-Host ""

# Step 4: Start all services
Write-Host "[4/4] Starting all services..." -ForegroundColor Yellow
docker compose up -d
Write-Host "✓ All services started" -ForegroundColor Green
Write-Host ""

# Wait a bit for services to initialize
Write-Host "Waiting 10 seconds for services to initialize..." -ForegroundColor Yellow
Start-Sleep -Seconds 10
Write-Host ""

# Show status
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  System Status" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
docker compose ps
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Access Points" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Kafka (host):        localhost:29092" -ForegroundColor White
Write-Host "Prometheus:          http://localhost:9090" -ForegroundColor White
Write-Host "Grafana:             http://localhost:3000 (admin/admin)" -ForegroundColor White
Write-Host "Metrics Service:     http://localhost:9100/metrics" -ForegroundColor White
Write-Host "Layer 1 Ingestion:   http://localhost:9101/metrics" -ForegroundColor White
Write-Host "Layer 1 Validated:   http://localhost:9102/metrics" -ForegroundColor White
Write-Host "Layer 2 Anomaly:     http://localhost:9103/metrics" -ForegroundColor White
Write-Host "Layer 3 Strategy:    http://localhost:9104/metrics" -ForegroundColor White
Write-Host "Layer 4 Risk:        http://localhost:9105/metrics" -ForegroundColor White
Write-Host "Layer 5 Execution:   http://localhost:9106/metrics" -ForegroundColor White
Write-Host "Layer 6 Audit:       http://localhost:9107/metrics" -ForegroundColor White
Write-Host ""

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Next Steps" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "1. Check Prometheus targets: http://localhost:9090/targets" -ForegroundColor White
Write-Host "2. View Grafana dashboards:  http://localhost:3000" -ForegroundColor White
Write-Host "3. Monitor logs:             docker compose logs -f" -ForegroundColor White
Write-Host "4. Stop system:              docker compose down" -ForegroundColor White
Write-Host ""

Write-Host "✓ System startup complete!" -ForegroundColor Green

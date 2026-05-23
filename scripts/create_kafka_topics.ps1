# Purpose: Pre-create all Kafka topics with explicit partition counts
# This ensures topics exist before services start, preventing auto-create race conditions

$ErrorActionPreference = "Stop"

$KAFKA_BROKER = if ($env:KAFKA_BROKER) { $env:KAFKA_BROKER } else { "localhost:29092" }
$PARTITIONS = if ($env:PARTITIONS) { $env:PARTITIONS } else { "1" }
$REPLICATION_FACTOR = if ($env:REPLICATION_FACTOR) { $env:REPLICATION_FACTOR } else { "1" }

Write-Host "Creating Kafka topics on broker: $KAFKA_BROKER" -ForegroundColor Cyan
Write-Host "Partitions: $PARTITIONS, Replication Factor: $REPLICATION_FACTOR" -ForegroundColor Cyan
Write-Host ""

# Wait for Kafka to be ready
Write-Host "Waiting for Kafka to be ready..." -ForegroundColor Yellow
$maxRetries = 30
$retryCount = 0
while ($retryCount -lt $maxRetries) {
    try {
        docker compose exec -T kafka kafka-broker-api-versions --bootstrap-server kafka:9092 2>&1 | Out-Null
        Write-Host "Kafka is ready!" -ForegroundColor Green
        break
    }
    catch {
        Write-Host "Kafka not ready yet, waiting... ($retryCount/$maxRetries)" -ForegroundColor Yellow
        Start-Sleep -Seconds 2
        $retryCount++
    }
}

if ($retryCount -eq $maxRetries) {
    Write-Host "ERROR: Kafka did not become ready in time" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Define topics
$TOPICS = @(
    "market.ticks.raw",
    "market.ticks.validated",
    "market.ticks.scored",
    "trading.signals",
    "trading.orders.approved",
    "trading.orders.executed",
    "audit.events"
)

# Create topics
foreach ($TOPIC in $TOPICS) {
    Write-Host "Creating topic: $TOPIC" -ForegroundColor Cyan
    
    $createCmd = "docker compose exec -T kafka kafka-topics --bootstrap-server kafka:9092 --create --if-not-exists --topic $TOPIC --partitions $PARTITIONS --replication-factor $REPLICATION_FACTOR --config retention.ms=86400000 --config segment.ms=3600000"
    
    Invoke-Expression $createCmd
    
    Write-Host "✓ Topic $TOPIC created" -ForegroundColor Green
    Write-Host ""
}

Write-Host "All topics created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "Listing all topics:" -ForegroundColor Cyan
docker compose exec -T kafka kafka-topics --bootstrap-server kafka:9092 --list

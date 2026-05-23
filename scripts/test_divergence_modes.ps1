# Purpose: Test both execution modes (simple and protected)
# Usage: .\scripts\test_divergence_modes.ps1

Write-Host "Testing Execution Divergence Modes" -ForegroundColor Cyan
Write-Host ""

# Test 1: Simple Mode (default)
Write-Host "=== Test 1: Simple Mode (ENABLE_DIVERGENCE_CHECK=false) ===" -ForegroundColor Yellow
Write-Host "Expected: All orders execute normally" -ForegroundColor Gray
Write-Host ""

# Check current config
Write-Host "Checking docker-compose.yml configuration..." -ForegroundColor Cyan
$config = docker compose config | Select-String -Pattern "ENABLE_DIVERGENCE_CHECK"
Write-Host $config
Write-Host ""

# Check if Layer 5 is running
$layer5Status = docker compose ps layer5-execution --format json | ConvertFrom-Json
if ($layer5Status) {
    Write-Host "Layer 5 Status: $($layer5Status.State)" -ForegroundColor Green
    
    # Check environment variable
    Write-Host ""
    Write-Host "Checking ENABLE_DIVERGENCE_CHECK environment variable..." -ForegroundColor Cyan
    docker compose exec -T layer5-execution sh -c 'echo "ENABLE_DIVERGENCE_CHECK=$ENABLE_DIVERGENCE_CHECK"'
    
    # Check recent logs for divergence mentions
    Write-Host ""
    Write-Host "Recent logs (last 10 lines):" -ForegroundColor Cyan
    docker compose logs --tail=10 layer5-execution
} else {
    Write-Host "Layer 5 is not running. Start with: docker compose up -d" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Test 2: Protected Mode (ENABLE_DIVERGENCE_CHECK=true) ===" -ForegroundColor Yellow
Write-Host "To enable protected mode:" -ForegroundColor Gray
Write-Host "1. Edit docker-compose.yml and set ENABLE_DIVERGENCE_CHECK: 'true'" -ForegroundColor Gray
Write-Host "2. Run: docker compose restart layer5-execution" -ForegroundColor Gray
Write-Host "3. Check logs: docker compose logs -f layer5-execution" -ForegroundColor Gray
Write-Host "4. Look for 'REJECTED: divergence_' messages" -ForegroundColor Gray
Write-Host ""

Write-Host "=== Metrics to Check ===" -ForegroundColor Yellow
Write-Host "Prometheus metrics available at: http://localhost:9106/metrics" -ForegroundColor Gray
Write-Host ""
Write-Host "Key metrics:" -ForegroundColor Cyan
Write-Host "  - execution_divergence_bps (histogram of divergence magnitudes)" -ForegroundColor Gray
Write-Host "  - execution_divergence_rejections_total (count of rejections)" -ForegroundColor Gray
Write-Host "  - layer5_orders_in_total (total orders received)" -ForegroundColor Gray
Write-Host ""

# Try to fetch metrics if Layer 5 is running
if ($layer5Status -and $layer5Status.State -eq "running") {
    Write-Host "Fetching current metrics..." -ForegroundColor Cyan
    try {
        $metrics = Invoke-WebRequest -Uri http://localhost:9106/metrics -UseBasicParsing -TimeoutSec 2
        
        # Extract divergence metrics
        $divergenceMetrics = $metrics.Content -split "`n" | Select-String -Pattern "execution_divergence|layer5_orders"
        
        if ($divergenceMetrics) {
            Write-Host ""
            Write-Host "Current Divergence Metrics:" -ForegroundColor Green
            $divergenceMetrics | ForEach-Object { Write-Host $_ -ForegroundColor Gray }
        } else {
            Write-Host "No divergence metrics found yet (no orders processed)" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "Could not fetch metrics (Layer 5 may still be starting)" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host "✓ Simple mode (default): ENABLE_DIVERGENCE_CHECK=false" -ForegroundColor Green
Write-Host "✓ Protected mode (optional): ENABLE_DIVERGENCE_CHECK=true" -ForegroundColor Green
Write-Host "✓ Configuration: docker-compose.yml layer5-execution environment" -ForegroundColor Green
Write-Host "✓ Metrics: http://localhost:9106/metrics" -ForegroundColor Green
Write-Host ""

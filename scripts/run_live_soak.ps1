# Purpose: Start stack for a live testnet soak, capture metrics/logs, and archive artifacts.
param(
    [string]$OutputBase = "artifacts/test_runs",
    [string]$EnvFile = ".env.testnet",
    [int]$DurationS = 3600
)

$RunTag = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$OutDir = Join-Path $OutputBase "LIVE_$RunTag"
New-Item -Path $OutDir -ItemType Directory -Force | Out-Null

if (-not (Test-Path $EnvFile)) { Write-Host "Env file $EnvFile not found"; exit 2 }

docker-compose --env-file $EnvFile up --build -d
Start-Sleep -Seconds 10

# endpoints to scrape - edit as needed
$endpoints = @('http://localhost:9100/metrics','http://localhost:9200/metrics','http://localhost:9300/metrics')
python tools/capture_prometheus.py (Join-Path $OutDir 'metrics') $endpoints

# capture logs
docker-compose logs --no-color --since 1m > (Join-Path $OutDir 'combined_logs.txt')

Write-Host "Running live soak for $DurationS seconds"
Start-Sleep -Seconds $DurationS

python tools/capture_prometheus.py (Join-Path $OutDir 'metrics_post') $endpoints

docker-compose logs --no-color > (Join-Path $OutDir 'combined_logs_full.txt')

# archive
$zip = Join-Path $OutDir "artifacts_bundle_$RunTag.tar.gz"
Compress-Archive -Path (Join-Path $OutDir '*') -DestinationPath $zip -Force

docker-compose --env-file $EnvFile down
Write-Host "Live soak completed. Artifacts: $OutDir"

# Purpose: Wrapper to run deterministic backtest, capture metadata, and run verification
param(
    [string]$Symbol = "BTCUSDT",
    [string]$Start = "2026-04-01",
    [string]$End = "2026-04-02",
    [string]$OutputBase = "artifacts/test_runs",
    [string]$HMMPath = "artifacts/hmm/model.pkl",
    [int]$Seed = 42
)

$RunTag = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$OutDir = Join-Path $OutputBase "BACKTEST_$RunTag"
New-Item -Path $OutDir -ItemType Directory -Force | Out-Null

# capture git and environment
git rev-parse --verify HEAD | Out-File -FilePath (Join-Path $OutDir git_commit.txt) -Encoding utf8
python -c "import sys,platform; print(platform.python_version())" | Out-File -FilePath (Join-Path $OutDir python_version.txt) -Encoding utf8
$env:RUN_TAG = $RunTag
$run_metadata = @{ git_commit = (Get-Content (Join-Path $OutDir git_commit.txt)).Trim(); run_tag = $RunTag; start_utc = (Get-Date).ToUniversalTime().ToString("o"); seed = $Seed }
$run_metadata | ConvertTo-Json | Out-File (Join-Path $OutDir run_metadata.json) -Encoding utf8

# run backtest
$cmd = "python -m services.backtesting.engine --symbol $Symbol --scenario baseline --start $Start --end $End --output-dir $OutDir --hmm-model-path $HMMPath --time-speed 1.0"
Write-Host "Running: $cmd"
Invoke-Expression $cmd

# run verification
python tools/verify_run.py $OutDir
if ($LASTEXITCODE -ne 0) { Write-Host "Verification failed with exit $LASTEXITCODE"; exit $LASTEXITCODE }

# generate human-readable summary
$NestedDir = Get-ChildItem $OutDir -Directory | Where-Object {$_.Name -match "^[A-Z]+_baseline_"} | Select-Object -First 1
if ($NestedDir) {
    python tools/generate_summary.py $NestedDir.FullName
    Write-Host ""
    Write-Host "Human-readable summary: $(Join-Path $NestedDir.FullName 'SUMMARY.txt')"
}

Write-Host "Backtest completed. Artifacts in $OutDir"

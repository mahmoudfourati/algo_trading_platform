#!/usr/bin/env bash
# Purpose: Wrapper to run deterministic backtest, capture metadata, and run verification
set -euo pipefail
SYMBOL=${1:-BTCUSDT}
START=${2:-2026-04-01}
END=${3:-2026-04-02}
OUTPUT_BASE=${4:-artifacts/test_runs}
HMM_PATH=${5:-artifacts/hmm/model.pkl}
SEED=${6:-42}

RUN_TAG=$(date -u +%Y%m%dT%H%M%SZ)
OUT_DIR="$OUTPUT_BASE/BACKTEST_$RUN_TAG"
mkdir -p "$OUT_DIR"

git rev-parse --verify HEAD > "$OUT_DIR/git_commit.txt" || true
python -c "import platform,sys; print(platform.python_version())" > "$OUT_DIR/python_version.txt" || true
python - <<PY > "$OUT_DIR/run_metadata.json"
import json,os
print(json.dumps({
    "git_commit": open("$OUT_DIR/git_commit.txt").read().strip() if os.path.exists("$OUT_DIR/git_commit.txt") else None,
    "run_tag": "$RUN_TAG",
    "start_utc": "$RUN_TAG",
    "seed": $SEED
}, indent=2))
PY

python -m services.backtesting.engine --symbol "$SYMBOL" --scenario baseline --start "$START" --end "$END" --output-dir "$OUT_DIR" --hmm-model-path "$HMM_PATH" --time-speed 1.0

python tools/verify_run.py "$OUT_DIR"

# generate human-readable summary
NESTED_DIR=$(find "$OUT_DIR" -type d -name "*_baseline_*" | head -1)
if [ -n "$NESTED_DIR" ]; then
  python tools/generate_summary.py "$NESTED_DIR"
  echo ""
  echo "Human-readable summary: $NESTED_DIR/SUMMARY.txt"
fi

echo "Backtest completed. Artifacts in $OUT_DIR"

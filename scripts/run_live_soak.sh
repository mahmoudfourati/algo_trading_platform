#!/usr/bin/env bash
# Purpose: Start stack for a live testnet soak, capture metrics/logs, and archive artifacts.
set -euo pipefail
OUTPUT_BASE=${1:-artifacts/test_runs}
ENV_FILE=${2:-.env.testnet}
DURATION_S=${3:-3600}

RUN_TAG=$(date -u +%Y%m%dT%H%M%SZ)
OUT_DIR="$OUTPUT_BASE/LIVE_$RUN_TAG"
mkdir -p "$OUT_DIR"

if [ ! -f "$ENV_FILE" ]; then
  echo "Env file $ENV_FILE not found" >&2
  exit 2
fi

# start stack
docker-compose --env-file "$ENV_FILE" up --build -d

# wait for services to come up (best-effort)
sleep 10

# capture prometheus scrapes (list can be edited)
ENDPOINTS=("http://localhost:9100/metrics" "http://localhost:9200/metrics" "http://localhost:9300/metrics")
python tools/capture_prometheus.py "$OUT_DIR/metrics" "${ENDPOINTS[@]}" || true

# stream logs in background and capture to file
docker-compose logs --no-color --since 1m > "$OUT_DIR/combined_logs.txt" || true

# run soak duration
echo "Running live soak for $DURATION_S seconds"
sleep "$DURATION_S"

# post-run: capture latest metrics and docker-compose logs
python tools/capture_prometheus.py "$OUT_DIR/metrics_post" "${ENDPOINTS[@]}" || true

docker-compose logs --no-color > "$OUT_DIR/combined_logs_full.txt" || true

# archive artifacts
tar -czf "$OUT_DIR/artifacts_bundle_$RUN_TAG.tar.gz" -C "$OUT_DIR" . || true

# stop stack
docker-compose --env-file "$ENV_FILE" down

echo "Live soak completed. Artifacts: $OUT_DIR"

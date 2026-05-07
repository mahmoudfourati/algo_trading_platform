<!-- Purpose: Project overview and how to run/verify the stack locally. -->
# Secure Algorithmic Trading Platform (Blueprint Implementation)

This repo implements the system described in `trading_blueprint_final.docx.md`.

## Phase 1 (current): Local foundation stack

### Prereqs

- Docker Desktop
- `docker compose` (Compose v2)
- Optional for smoke test from host: Python 3.11+

### Start the stack

```powershell
docker compose up -d --build
```

Services:

- Kafka broker (host access): `localhost:29092`
- ZooKeeper (host access): `localhost:22181`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000` (default login `admin` / `admin`)
- Metrics service `/metrics`: `http://localhost:9100/metrics`
- Layer 1 ingestion `/metrics`: `http://localhost:9101/metrics`
- Layer 1 validated `/metrics`: `http://localhost:9102/metrics`
- Layer 2 anomaly `/metrics`: `http://localhost:9103/metrics`

### Grafana dashboards (auto-provisioned)

Grafana now auto-loads a dashboard folder and pipeline dashboard from provisioning files.

- Folder: `Algo Trading`
- Dashboard: `Algo Trading Pipeline Overview`

Open Grafana and navigate:

1. `Dashboards`
2. `Algo Trading`
3. `Algo Trading Pipeline Overview`

The dashboard visualizes:

- Layer 1 ingestion rates by exchange
- Raw -> validated -> scored throughput
- Trust score and anomaly components (IF/HST)
- Pipeline latency and Layer 2 input lag
- Kafka publisher buffer depth and publish errors

### Stop / reset

```powershell
docker compose down
docker compose down -v
```

### Useful commands

```powershell
docker compose ps
docker compose logs -f kafka
docker compose logs -f prometheus
docker compose logs -f grafana
```

### Kafka smoke test (host)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python scripts\kafka_smoke_test.py
```

This verifies:

- Produce/consume round-trip
- Consumer-group semantics with a 2-partition topic

### Prometheus scrape check

Open Prometheus targets:

- `http://localhost:9090/targets`

You should see `metrics-service` as **UP**.

You should also see `layer1-ingestion` and `layer1-validated` as **UP**.

You should also see `layer2-anomaly` as **UP**.

### Flow metrics added

Additional metrics are exported to improve observability of message flow and backpressure:

- Layer 1 raw publisher:
	- `layer1_ingestion_kafka_enqueued_total`
	- `layer1_ingestion_kafka_sent_total`
	- `layer1_ingestion_kafka_dropped_total`
	- `layer1_ingestion_kafka_publish_errors_total`
	- `layer1_ingestion_kafka_buffer_depth`
- Layer 1 validated:
	- `layer1_validated_last_window_sources`
	- `layer1_validated_last_window_used_sources`
	- `layer1_validated_last_window_latency_ms`
- Layer 2 anomaly:
	- `layer2_last_if_score`
	- `layer2_last_hst_score`
	- `layer2_last_input_trust_score`
	- `layer2_last_input_lag_ms`
- Shared JSON Kafka publisher (used by validated/scored publishers):
	- `kafka_json_publisher_enqueued_total`
	- `kafka_json_publisher_sent_total`
	- `kafka_json_publisher_dropped_total`
	- `kafka_json_publisher_errors_total`
	- `kafka_json_publisher_queue_depth`

## Phase 2 (in progress): Layer 1 adapters

Layer 1 is the trust boundary. It ingests exchange data via secure WebSocket adapters, applies consensus and trust scoring, and outputs a validated tick stream.

See [layer1_implementation.md](layer1_implementation.md) for a detailed architectural walkthrough.

### Layer 1 End-to-End Soak Test

For a complete Layer 1 verification run (adapters, alignment, consensus, trust, hash-chain, and report):

```powershell
.\venv\Scripts\python scripts\layer1_e2e_test.py --symbols BTC-USDT --duration 900 --output artifacts\reports\
```

This runs all 5 exchange adapters for 15 minutes and generates a Markdown report in `artifacts/reports/layer1_e2e_*.md` with:

- Ingestion metrics (tick counts, arrival gaps, out-of-order events)
- Alignment statistics (real vs LKV-filled sources, staleness)
- Consensus outcomes (true/degraded/no-consensus windows)
- Trust scores (T1–T5 subscores with percentiles)
- Liveness events (exchange silence/recovery)
- Hash-chain verification status

This is the fastest way to validate that Layer 1 is wired correctly end to end.

### Console adapters (no Kafka)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt

$env:SYMBOLS = "BTC-USDT,ETH-USDT"
$env:EXCHANGES = "binance,coinbase,kraken,okx,bybit"
.\venv\Scripts\python -m services.layer1_ingestion.run_console
```

### Publish raw ticks to Kafka (`market.ticks.raw`)

The raw Kafka topic carries `RawTick` messages—the direct output of the adapter layer after exchange-specific parsing. Each raw tick includes an explicit `timestamp_source` field indicating whether the timestamp is exchange-sourced or receive-sourced only (e.g., Kraken).

Terminal A (consume raw ticks):

```powershell
$env:KAFKA_BOOTSTRAP_SERVER = "localhost:29092"
.\.venv\Scripts\python scripts\consume_market_ticks_raw.py
```

Terminal B (producer via Layer 1 runner):

```powershell
$env:PUBLISH_RAW_TO_KAFKA = "1"
$env:KAFKA_BOOTSTRAP_SERVER = "localhost:29092"
$env:SYMBOLS = "BTC-USDT"
$env:EXCHANGES = "binance,coinbase,kraken,okx,bybit"
.\venv\Scripts\python -m services.layer1_ingestion.run_console
```

### Validated topic (`market.ticks.validated`)

The validated topic carries `ValidatedTick` messages, which are the Layer 1 output after alignment, consensus, and trust scoring. Each validated tick carries:

- **Primary exchange data**: `primary_exchange` (e.g., "binance") and `mid_price` (the price to operate on)
- **Consensus validation**: `consensus_mid` (multi-source agreement) and `used_sources` (which exchanges participated)
- **Trust metadata**: Trust score, T1–T5 subscores, divergent sources, and hash-chain link

**Primary Exchange Routing**: The validated service is configured with a primary exchange (default: Binance via `PRIMARY_EXCHANGE` env var). Only windows where the primary exchange successfully participated in consensus produce validated ticks. This ensures downstream layers always operate on a single exchange's data while continuously validating it against multi-source consensus.

Terminal A (start validated service):

```powershell
$env:KAFKA_BOOTSTRAP_SERVER = "localhost:29092"
$env:PRIMARY_EXCHANGE = "binance"  # Optional; defaults to binance
.\.venv\Scripts\python -m services.layer1_validated.service
```
The validated service:
- Consumes raw ticks from `market.ticks.raw`
- Aligns them into 50 ms windows
- Applies consensus (0.3% divergence tolerance)
- **Checks if primary exchange is in the consensus set; skips the window if not**
- Computes trust scores (TLS, agreement, freshness, sequence, hash-chain)
- Appends entries to the hash-chain log (including both primary and consensus prices)
- Publishes validated ticks to `market.ticks.validated`

It uses a stable Kafka consumer group and earliest offset reset by default, so restarts do not skip data.
Terminal B (consume validated ticks):

```powershell
$env:KAFKA_BOOTSTRAP_SERVER = "localhost:29092"
.\.venv\Scripts\python scripts\consume_market_ticks_validated.py
```

Terminal C (produce raw ticks via adapters):

```powershell
$env:PUBLISH_RAW_TO_KAFKA = "1"
$env:KAFKA_BOOTSTRAP_SERVER = "localhost:29092"
$env:SYMBOLS = "BTC-USDT"
$env:EXCHANGES = "binance,coinbase,kraken,okx,bybit"
.\venv\Scripts\python -m services.layer1_ingestion.run_console
```

### Tracing Layer 1 (debug mode)

To replay alignment and consensus manually while correlating with validated output:

```powershell
$env:KAFKA_BOOTSTRAP_SERVER = "localhost:29092"
$env:PRIMARY_EXCHANGE = "binance"  # Optional; must match the validated service's config
$env:TRACE_MAX_WINDOWS = "12"
$env:TRACE_MAX_SECONDS = "15"
.\venv\Scripts\python scripts\trace_layer1_e2e.py
```

This debug script replays raw ticks through the consensus engine locally and compares the output with what the validated service published to Kafka. It filters windows the same way: only reporting traced windows where the primary exchange is present in the consensus set.

## Phase 3: HMM training (offline)

Installs ML deps (may take a bit on Windows):

```powershell
.\.venv\Scripts\python -m pip install -r requirements-ml.txt
```

Train the 2-state GaussianHMM on 30-minute realized volatility (default 90 days):

```powershell
.\.venv\Scripts\python -m services.hmm_training.train --days 90 --symbols BTCUSDT,ETHUSDT
```

Outputs:

- `artifacts/hmm/model.pkl`
- `artifacts/hmm/metadata.json`

## Phase 4: Layer 2 anomaly detection

Layer 2 consumes `market.ticks.validated` and publishes `ScoredTick` messages to `market.ticks.scored`.

### Consume scored ticks (from inside the Kafka container)

```powershell
docker compose exec -T kafka kafka-console-consumer --bootstrap-server kafka:9092 --topic market.ticks.scored --consumer-property auto.offset.reset=earliest --max-messages 5
```

### Or consume scored ticks (host Python)

```powershell
$env:KAFKA_BOOTSTRAP_SERVER = "localhost:29092"
.\.venv\Scripts\python scripts\consume_market_ticks_scored.py
```

## Phase 5: Backtesting engine

Phase 5 replays historical market data through the live Layer 1 and Layer 2 code paths so the system can be validated deterministically on known scenarios.

See [phase5_implementation.md](phase5_implementation.md) for the detailed architecture, outputs, assumptions, and remaining work.

Current outputs for a slice run:

- `metrics.json`
- `equity_curve.csv`
- `config_snapshot.json`
- `report.html`

The Phase 5 runner writes all artifacts into a timestamped directory under `artifacts/reports/` and persists run records in SQLite.

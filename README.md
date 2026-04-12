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

## Phase 2 (in progress): Layer 1 adapters

### Console adapters (no Kafka)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt

$env:SYMBOLS = "BTC-USDT,ETH-USDT"
$env:EXCHANGES = "binance,coinbase,kraken"
.\.venv\Scripts\python -m services.layer1_ingestion.run_console
```

### Phase 2.3: Publish raw ticks to Kafka (`market.ticks.raw`)

Terminal A (consumer):

```powershell
$env:KAFKA_BOOTSTRAP_SERVER = "localhost:29092"
.\.venv\Scripts\python scripts\consume_market_ticks_raw.py
```

Terminal B (producer via Layer 1 runner):

```powershell
$env:PUBLISH_RAW_TO_KAFKA = "1"
$env:KAFKA_BOOTSTRAP_SERVER = "localhost:29092"
$env:SYMBOLS = "BTC-USDT"
$env:EXCHANGES = "binance"
.\.venv\Scripts\python -m services.layer1_ingestion.run_console
```

### Phase 2.7: Wiring + validated topic (`market.ticks.validated`)

Terminal A (start validated service):

```powershell
$env:KAFKA_BOOTSTRAP_SERVER = "localhost:29092"
.\.venv\Scripts\python -m services.layer1_validated.service
```

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
$env:EXCHANGES = "binance,coinbase,kraken"
.\.venv\Scripts\python -m services.layer1_ingestion.run_console
```

## Phase 3: HMM training (offline)

Installs ML deps (may take a bit on Windows):

```powershell
.\.venv\Scripts\python -m pip install -r requirements-ml.txt
```

Train the 3-state GaussianHMM on 30-minute realized volatility (default 90 days):

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
docker compose exec -T kafka kafka-console-consumer --bootstrap-server kafka:9092 --topic market.ticks.scored --consumer-property auto.offset.reset=latest --max-messages 5
```

### Or consume scored ticks (host Python)

```powershell
$env:KAFKA_BOOTSTRAP_SERVER = "localhost:29092"
.\.venv\Scripts\python scripts\consume_market_ticks_scored.py
```

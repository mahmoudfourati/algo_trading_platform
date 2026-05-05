<!-- Purpose: Phase 5 Backtesting Engine - Complete technical specification and implementation roadmap -->

# Phase 5: Backtesting Engine Specification

**Status:** Ready to Implement (Phase 4 Complete)  
**Dependencies:** Layer 1 (ingestion), Layer 2 (anomaly detection), trained HMM model artifact from Phase 3  
**Target Deliverable:** Historical replay harness with deterministic time control and benchmark metrics

---

## 1. Overview

The backtesting engine replays historical market data through the live Layer 1 and Layer 2 pipelines to validate anomaly detection performance on known price movements and injected attack scenarios.

**Core Requirements:**
- Replay historical tick data from CSV/database with deterministic time progression
- Use a minimum 90-day historical validation window; retain 180-day cache support when available for faster repeated runs
- Simulate multi-source tick generation (synthetic Bybit, OKX, etc.) and document any optimistic assumptions in the report
- Feed data through Layer 1 consensus engine and Layer 2 anomaly detection
- Inject synthetic attack scenarios (flash crashes, extreme spreads, multi-source disagreement)
- Output benchmark metrics (Sharpe ratio, max drawdown, win rate, anomaly detection rate, false positive rate, end-to-end latency proxy, NORMAL-state percentage, permutation p-value when available)
- Emit both gross and net P&L with explicit Binance fee accounting at 0.1% per trade

---

## 2. Architecture

### 2.1 Data Flow

```
Historical Tick CSV
    ↓
Backtest Replay Engine
├─ Time Control (deterministic, no wall clock)
├─ Multi-source Tick Generator (simulate all 5 exchanges)
└─ Attack Scenario Injector
    ↓
Layer 1 Consensus (in-memory, no Kafka)
    ↓
Layer 2 Anomaly Detection (using live code)
    ↓
Backtest Results Collector
├─ Anomaly Detection Rate
├─ False Positive Rate
├─ State Transition Timeline
├─ Sharpe Ratio
└─ Max Drawdown
    ↓
Results Database + Report Generator
```

### 2.2 Key Components

| Component | Purpose | Implementation |
|-----------|---------|-----------------|
| **TimeController** | Deterministic time progression | Mocks datetime, controls tick timestamp ordering |
| **HistoricalTickLoader** | Load/cache historical data | CSV/Parquet from Binance Vision or local database |
| **MultiSourceGenerator** | Simulate all 5 exchanges | Add configurable jitter/delay per exchange |
| **AttackInjector** | Insert synthetic scenarios | Context managers for flash crash, spread spike, etc. |
| **Layer1Simulator** | Run consensus in-memory | Reuse live Layer 1 validation logic |
| **Layer2Simulator** | Run anomaly detection | Use live Layer 2 engine, feed synthetic ValidatedTicks |
| **MetricsCollector** | Track detection events | Log anomalies, states, decisions, timestamps |
| **ResultsDB** | Persist results | SQLite for queryability across runs |

---

## 3. Component Details

### 3.1 TimeController

**Purpose:** Replace wall-clock time with test-controlled progression

**Interface:**
```python
class TimeController:
    def __init__(self, start_dt: datetime, end_dt: datetime):
        self.current_time = start_dt
        self.end_time = end_dt
        self.speed = 1.0  # 1.0 = real-time, 2.0 = 2x speed, etc.
    
    def advance(self, seconds: float) -> None:
        """Move time forward by N seconds (test speed)"""
        self.current_time += timedelta(seconds=seconds * self.speed)
    
    def now(self) -> datetime:
        """Current test time"""
        return self.current_time
    
    def fast_forward(self, hours: float) -> None:
        """Skip to N hours later"""
        self.current_time += timedelta(hours=hours)
```

**Usage:** Inject via monkeypatch in backtest scope; Layer 1/2 code reads `datetime.utcnow()` which returns controller's time.

---

### 3.2 HistoricalTickLoader

**Purpose:** Load real market data at scale

**Data Sources:**
- **Binance Vision:** BTCUSDT + ETHUSDT minimum 90 days for walk-forward validation; 180 days optional for cache/reuse and model training artifacts
- **Local CSV:** `artifacts/backtest_data/ticks_raw.csv` (schema: timestamp, exchange, symbol, bid, ask, last, volume)
- **Synthetic Cache:** For fast repeated runs

**Backtest realism note:** the live system only has one authoritative historical source, so multi-source backtests may synthesize additional exchange streams with small bounded noise inside the divergence tolerance. This makes the Layer 1 T2 sub-score slightly optimistic and must be stated explicitly in every report.

**Interface:**
```python
class HistoricalTickLoader:
    def __init__(self, symbols: List[str], start_date: datetime, end_date: datetime):
        self.symbols = symbols
        self.start_date = start_date
        self.end_date = end_date
        self._cache = {}
    
    def load(self) -> DataFrame:
        """Returns all ticks in date range, indexed by (timestamp, exchange, symbol)"""
    
    def get_slice(self, dt_start: datetime, dt_end: datetime) -> DataFrame:
        """Get ticks for specific time window"""
    
    def iterator(self) -> Iterator[RawTick]:
        """Stream ticks in chronological order"""
```

**Performance Optimization:**
- Cache 180 days in memory on first load (~2-3 GB estimated)
- Index by timestamp for fast lookups
- Allow downsampling (e.g., every 10th tick) for fast validation runs

---

### 3.3 MultiSourceGenerator

**Purpose:** Simulate all 5 exchanges producing ticks in realistic patterns

**Configuration per Exchange:**
```python
@dataclass
class ExchangeConfig:
    name: str  # "binance", "bybit", "coinbase", "kraken", "okx"
    base_frequency_hz: float  # Ticks per second (e.g., 5, 2, 1)
    latency_ms: float  # Simulated network delay
    tick_jitter_pips: float  # Random noise added to bid/ask
    outage_probability: float  # Probability of temporary offline (0.0-0.05)
```

**Logic:**
1. Start with Binance as source of truth (highest frequency)
2. Resample each exchange to its base frequency
3. Add latency offset (e.g., Bybit +50ms, OKX +100ms)
4. Add jitter to mid-price (uniform ±jitter_pips)
5. Randomly simulate outages (skip ticks for 30-300s windows)

**Output:** Produces RawTick messages as if from live API

---

### 3.4 AttackInjector

**Purpose:** Inject synthetic market stress scenarios

**Scenario Definitions:**

#### 4.1 Flash Crash
```python
class FlashCrash:
    def __init__(self, symbol: str, severity: float = 0.10, duration_ms: int = 500):
        self.symbol = symbol  # "BTCUSDT", "ETHUSDT"
        self.severity = severity  # 10% crash
        self.duration_ms = duration_ms  # 500ms event
    
    def inject(self, ticks: Iterator[RawTick]) -> Iterator[RawTick]:
        """Modify tick stream: midpoint drops by severity%, then recovers"""
```

**Expected Output:**
- Mid-price drops 10% in <1s
- Layer 2 should detect as ANOMALY
- Decision gate should downgrade to CONSERVATIVE or DEGRADED

#### 4.2 Extreme Spread Widening
```python
class SpreadSpike:
    def __init__(self, symbol: str, max_spread_bps: int = 200):
        self.symbol = symbol
        self.max_spread_bps = max_spread_bps  # 200 bps = 2% spread
    
    def inject(self, ticks: Iterator[RawTick]) -> Iterator[RawTick]:
        """Widen bid-ask spread to extreme levels"""
```

**Expected Output:**
- Bid-ask spread 2-3x normal
- Layer 2 should detect as ANOMALY (via feature: max_spread relative to regime)
- Decision gate may not fully degrade unless combined with other factors

#### 4.3 Multi-Source Disagreement
```python
class MultiSourceDisagreement:
    def __init__(self, symbol: str, disagreement_pct: float = 0.5):
        self.symbol = symbol
        self.disagreement_pct = disagreement_pct  # 0.5% mid-price divergence
    
    def inject(self, exchanges: Dict[str, Iterator[RawTick]]) -> Dict[str, Iterator[RawTick]]:
        """Make some exchanges report different prices"""
```

**Expected Output:**
- Bybit/OKX report mid-prices 0.5% above Binance
- Layer 1 consensus detects trust < threshold
- Layer 2 receives reduced trust score
- Decision gate may degrade if combined with anomaly score

#### 4.4 Volume Spike
```python
class VolumeSpike:
    def __init__(self, symbol: str, multiplier: float = 10.0, duration_s: int = 60):
        self.symbol = symbol
        self.multiplier = multiplier  # 10x normal volume
        self.duration_s = duration_s
    
    def inject(self, ticks: Iterator[RawTick]) -> Iterator[RawTick]:
        """Increase reported volumes"""
```

**Expected Output:**
- Volume feature spikes dramatically
- Layer 2 may detect as regime shift or anomaly
- Decision gate behavior depends on correlation with price moves

---

### 3.5 Layer1Simulator

**Purpose:** Run Layer 1 consensus logic in-memory (no Kafka)

**Input:** Raw ticks from multi-source generator  
**Output:** ValidatedTick messages (as if published to Kafka topic)

**Reuse:** Import live code:
```python
from services.layer1_validated.service import Layer1ConsensusEngine

engine = Layer1ConsensusEngine(
    trust_threshold=0.60,
    min_source_agreement=2  # At least 2 exchanges agree on price
)

for raw_tick in raw_tick_stream:
    if engine.should_process(raw_tick):
        validated_tick = engine.validate(raw_tick)
        yield validated_tick
```

---

### 3.6 Layer2Simulator

**Purpose:** Run Layer 2 anomaly detection on validated ticks

**Input:** ValidatedTick stream  
**Output:** ScoredTick messages + internal state log

**Reuse:** Import live code:
```python
from services.layer2_anomaly.engine import Layer2ScoringEngine

engine = Layer2ScoringEngine(
    hmm_model_path="artifacts/hmm/model.pkl",
    if_contamination=0.01,
    hst_n_trees=25,
)

for validated_tick in validated_stream:
    scored_tick = engine.score(validated_tick)
    yield scored_tick
```

**Logging:** Capture internal state transitions:
```python
@dataclass
class ScoringEvent:
    timestamp: datetime
    symbol: str
    anomaly_score: float
    hm_regime: int
    if_score: float
    hst_score: float
    mad_triggered: bool
    decision_state: str
    trust_score: float
```

---

### 3.7 MetricsCollector

**Purpose:** Track detection performance metrics

**Collected Metrics:**

| Metric | Type | Definition |
|--------|------|-----------|
| `gross_pnl` | float | Backtest profit/loss before fees |
| `net_pnl` | float | Backtest profit/loss after 0.1% Binance fee accounting |
| `sharpe_ratio` | float | Annualized Sharpe ratio of net returns after fees |
| `max_drawdown` | float | Largest peak-to-trough equity decline |
| `win_rate` | float (0-1) | Fraction of closed trades that were profitable |
| `anomaly_detection_rate` | float (0-1) | % of injected anomalies detected by Layer 2 |
| `false_positive_rate` | float (0-1) | % of normal ticks incorrectly marked as anomalies |
| `end_to_end_latency_ms` | float | Time from tick receipt to order-placement decision |
| `normal_state_pct` | float (0-1) | Fraction of normal-condition ticks in NORMAL state |
| `state_transitions` | int | Number of decision gate state changes |
| `time_to_detect` | float (ms) | Milliseconds from anomaly injection to Layer 2 detection |
| `time_to_recover` | float (ms) | Milliseconds from anomaly end to return to NORMAL |
| `anomaly_duration` | float (s) | Seconds Layer 2 stayed in degraded/alert state |
| `trust_score_min` | float | Minimum trust score during run |
| `permutation_p_value` | float | Bootstrap permutation p-value on Sharpe ratio |
| `equity_curve_path` | str | Path to saved equity curve artifact |

**Implementation:**
```python
@dataclass
class BacktestMetrics:
    run_id: str
    start_time: datetime
    end_time: datetime
    symbol: str
    scenario: str  # "flash_crash", "spread_spike", etc.
    gross_pnl: float
    net_pnl: float
    win_rate: float
    end_to_end_latency_ms: float
    normal_state_pct: float
    permutation_p_value: float
    equity_curve_path: str
    
    # Detection performance
    injected_anomalies: int
    detected_anomalies: int
    false_positives: int
    
    # State tracking
    events: List[ScoringEvent]
    
    def get_detection_rate(self) -> float:
        return self.detected_anomalies / self.injected_anomalies if self.injected_anomalies > 0 else 0.0
    
    def get_false_positive_rate(self) -> float:
        total_normal = self.total_ticks - self.injected_anomalies
        return self.false_positives / total_normal if total_normal > 0 else 0.0

    def get_net_return(self) -> float:
        return self.net_pnl
```

---

### 3.8 ResultsDB

**Purpose:** Persist and query backtest results

**Schema:**
```sql
CREATE TABLE backtest_runs (
    run_id VARCHAR PRIMARY KEY,
    scenario VARCHAR,  -- "flash_crash", "spread_spike", etc.
    start_time DATETIME,
    end_time DATETIME,
    duration_minutes FLOAT,
    symbol VARCHAR,
    
    gross_pnl FLOAT,
    net_pnl FLOAT,
    win_rate FLOAT,
    injected_anomalies INT,
    detected_anomalies INT,
    detection_rate FLOAT,
    false_positives INT,
    fp_rate FLOAT,
    end_to_end_latency_ms FLOAT,
    normal_state_pct FLOAT,
    
    state_transitions INT,
    mean_time_to_detect_ms FLOAT,
    mean_time_to_recover_ms FLOAT,
    
    min_trust_score FLOAT,
    sharpe_ratio FLOAT,
    max_drawdown FLOAT,
    permutation_p_value FLOAT,
    equity_curve_path TEXT,
    
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Queries:**
```sql
-- Compare detection rates across scenarios
SELECT scenario, AVG(detection_rate) as avg_detection 
FROM backtest_runs 
GROUP BY scenario;

-- Find fastest detection times
SELECT scenario, MIN(mean_time_to_detect_ms) as fastest_ms 
FROM backtest_runs 
ORDER BY fastest_ms ASC;

-- Track regression: all runs by date
SELECT DATE(created_at), AVG(detection_rate) 
FROM backtest_runs 
GROUP BY DATE(created_at);
```

---

## 4. Implementation Phases

### Phase 5.1: Core Engine (Week 1)
- [ ] TimeController implementation + testing
- [ ] HistoricalTickLoader (CSV + Binance Vision)
- [ ] MultiSourceGenerator with 5 exchange configs
- [ ] Basic Layer 1/2 simulators (reuse live code)

**Output:** Can replay 1 day of historical data through Layers 1+2

### Phase 5.2: Attack Scenarios (Week 2)
- [ ] FlashCrash injector
- [ ] SpreadSpike injector
- [ ] MultiSourceDisagreement injector
- [ ] VolumeSpike injector

**Output:** Can inject individual scenarios and observe Layer 2 responses

### Phase 5.3: Metrics & Results (Week 2)
- [ ] MetricsCollector + event logging
- [ ] ResultsDB (SQLite) + schema
- [ ] Anomaly detection rate calculation
- [ ] False positive rate calculation
- [ ] Sharpe ratio + max drawdown computation

**Output:** Full metrics capture for each backtest run

### Phase 5.4: Reporting (Week 3)
- [ ] HTML report generator (similar to stress test report)
- [ ] Time-series visualization (state transitions, anomaly scores over time)
- [ ] Scenario comparison dashboard
- [ ] Regression detection (new runs vs. historical baseline)

**Output:** Automated reports with visual insights

### Phase 5.5: Validation & Tuning (Week 3)
- [ ] Run backtests on known events (historical crashes, flash crashes)
- [ ] Tune hyperparameters based on backtest results
- [ ] Compare live performance vs. backtest metrics
- [ ] Document parameter changes and rationale

**Output:** Validated, tuned anomaly detection engine ready for Phase 6

---

## 5. Data Requirements

### 5.1 Historical Ticks

**Source:** Binance Vision (free, reliable, 1-minute klines available)

**Download Command:**
```bash
# Get 180 days of 1-minute klines
python -c "
from binance_historical_data_downloader import BinanceDownloader
dl = BinanceDownloader('SPOT', 'klines', '1m', 'BTCUSDT', '2025-11-15', '2026-05-01')
df = dl.get_data()
df.to_csv('artifacts/backtest_data/btc_180d.csv')
"
```

**Schema:**
```
timestamp (UTC), open, high, low, close, volume
2025-11-15 00:00:00, 42500.00, 42600.00, 42400.00, 42550.00, 1234.56
```

### 5.2 Attack Scenario Catalog

**Maintain a library of historical attacks for reference:**
- **2020-03-12 (COVID Crash):** ~30% drop in 2 hours
- **2021-06-23 (Luna Collapse):** Extreme volatility spike
- **2023-03-10 (SVB Contagion):** Multi-exchange disagreement
- **May 2010 (Flash Crash):** Sub-second 10% drop + recovery

**Synthetic Versions:** Scale and timestamp to known dates for reproducibility

---

## 6. Expected Deliverables

### 6.1 Code Structure
```
services/backtesting/
├── engine.py                 # Main BacktestEngine orchestrator
├── time_control.py           # TimeController class
├── data_loader.py            # HistoricalTickLoader
├── multi_source.py           # MultiSourceGenerator
├── attack_injector.py        # AttackInjector + scenario classes
├── layer1_sim.py             # Layer1Simulator wrapper
├── layer2_sim.py             # Layer2Simulator wrapper
├── metrics.py                # MetricsCollector + ScoringEvent
├── results_db.py             # ResultsDB (SQLite)
├── report_generator.py       # HTML report + visualization
├── __main__.py               # CLI entry point
└── tests/
    ├── test_time_control.py
    ├── test_data_loader.py
    ├── test_attacks.py
    └── test_end_to_end.py
```

### 6.2 CLI Interface
```bash
# Run single scenario
python -m services.backtesting \
  --scenario flash_crash \
  --symbol BTCUSDT \
  --severity 0.10 \
  --date 2026-01-15 \
  --output artifacts/reports/backtest_flash_crash_20260115.html

# Run all scenarios (for regression testing)
python -m services.backtesting --run-all --output artifacts/reports/

# Query results database
python -m services.backtesting --query "SELECT AVG(detection_rate) FROM backtest_runs WHERE scenario='flash_crash'"
```

### 6.3 Benchmark Report Structure
```
Backtest Report: Flash Crash on BTCUSDT (2026-01-15)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Scenario Summary
  Severity: 10% price drop over 500ms
  Injected: 1 anomaly event
  Duration: 5 minutes

Detection Performance
  ✅ Detected: YES (at 234ms)
  Detection Confidence: 0.87 (high)
  Time to Detect: 234ms
  Time to Recover: 1250ms
  
Layer 2 State Timeline
  00:00 NORMAL [trust=0.80, anomaly=0.02]
  00:00.234 CONSERVATIVE [trust=0.80, anomaly=0.76]
  00:00.450 DEGRADED [trust=0.60, anomaly=0.92]
  00:01.700 CONSERVATIVE [trust=0.65, anomaly=0.45]
  00:05.000 NORMAL [trust=0.80, anomaly=0.02]

False Positive Analysis
  False Positives: 0/4760 normal ticks (0.00% FP rate)
  
Metrics Summary
  Sharpe Ratio: 2.34 (good signal quality)
  Max Drawdown: 0.15 (brief confidence loss, recovered)
```

---

## 7. Success Criteria

The backtesting engine is **complete and validated** when:

1. ✅ **Deterministic Replay:** Same data + config produces identical results
2. ✅ **Attack Detection:** 90%+ detection rate on injected flash crashes
3. ✅ **False Positive Rate:** <1% on normal market conditions
4. ✅ **Time to Detect:** Anomalies detected within 500-1000ms of injection
5. ✅ **Recovery Time:** System returns to NORMAL within 2-5 seconds
6. ✅ **Database Persistence:** 1000+ backtest runs queryable and comparable
7. ✅ **Regression Testing:** Automated comparison against baseline metrics
8. ✅ **Full Documentation:** README with example usage and interpretation guide

---

## 8. Timeline

| Week | Task | Completion |
|------|------|-----------|
| Week 1 | Core engine (TimeController, DataLoader, Generator) | 40% |
| Week 2 | Attack scenarios + Layer 1/2 simulators | 70% |
| Week 2 | Metrics + ResultsDB | 85% |
| Week 3 | Reporting + visualization | 100% |
| Week 3 | Validation + tuning on historical data | 100% |

**Total Effort:** 3 weeks (15 working days)  
**Blocking:** Phase 6 (Strategy Engine)  
**Parallel:** Can run alongside extended stress tests

---

## 9. Next Steps

1. **Immediately:** Create `services/backtesting/` directory structure
2. **Week 1:** Implement TimeController + HistoricalTickLoader
3. **Week 1:** Verify data loading (180 days × 2 symbols)
4. **Week 2:** Build attack injectors
5. **Week 2-3:** Metrics collection and reporting
6. **Week 3:** Run regression tests on 180-day dataset
7. **Post-Phase-5:** Begin Phase 6 Strategy Engine (leverages backtest infrastructure)


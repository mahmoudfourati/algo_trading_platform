# Design Document

## Introduction

This document provides the technical design for implementing Phase 3 Layers 3-6 observability metrics. The design follows established patterns from Phases 1-2 and Phase 3 Layer 1, ensuring consistency across the observability evolution.

## Architecture Overview

### System Context

The algorithmic trading platform processes market data through a 6-layer pipeline:
- **Layer 1**: Ingestion & Validation (✅ Phase 3 Layer 1 complete)
- **Layer 2**: Anomaly Detection (✅ Phase 2 complete)
- **Layer 3**: Strategy Generation (⏳ This phase)
- **Layer 4**: Risk Management (⏳ This phase)
- **Layer 5**: Execution (⏳ This phase)
- **Layer 6**: Audit Logging (⏳ This phase)

Each layer exports Prometheus metrics on dedicated HTTP servers for scraping.

### Design Principles

1. **Pattern Consistency**: Follow Layer 2 anomaly service as the reference implementation
2. **Separation of Concerns**: Metrics export in service.py, business logic in engine.py
3. **Low Cardinality**: Use enums for labels, avoid high-cardinality values
4. **Non-Breaking**: Add metrics without modifying existing APIs
5. **Real-Time**: Metrics update immediately as data flows through the system

## Component Design

### Layer 3 Strategy Metrics

**File**: `services/layer3_strategy/service.py` (modify existing)

**Metrics to Add**:

```python
from prometheus_client import Counter, Gauge, Histogram

# Technical Indicators
_indicator_rsi = Gauge(
    "strategy_indicator_rsi",
    "RSI indicator value",
    ["symbol", "timeframe"]  # timeframe = 5m|1h
)

_indicator_macd_histogram = Gauge(
    "strategy_indicator_macd_histogram",
    "MACD histogram value",
    ["symbol", "timeframe"]
)

_indicator_bb_width = Gauge(
    "strategy_indicator_bollinger_width",
    "Bollinger Band width (normalized)",
    ["symbol", "timeframe"]
)

# Signal Generation
_signal_direction_count = Counter(
    "strategy_signal_direction_total",
    "Signal generation count by direction",
    ["symbol", "direction"]  # direction = LONG|SHORT|HOLD
)

_signal_strength_histogram = Histogram(
    "strategy_signal_strength_distribution",
    "Signal strength distribution",
    ["symbol"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)

_ema_crossover_events = Counter(
    "strategy_ema_crossover_events_total",
    "EMA crossover events",
    ["symbol", "direction"]  # direction = bullish|bearish
)
```

**Integration Points**:

1. **Indicator Export**: In `Layer3SymbolState.ingest_tick()`, after `self.indicator_manager.process(candle)` returns a snapshot:
   ```python
   if snapshot is not None:
       _indicator_rsi.labels(symbol=self.symbol, timeframe=event.timeframe).set(snapshot.rsi)
       _indicator_macd_histogram.labels(symbol=self.symbol, timeframe=event.timeframe).set(snapshot.macd_histogram)
       _indicator_bb_width.labels(symbol=self.symbol, timeframe=event.timeframe).set(snapshot.bb_width)
   ```

2. **Signal Direction Tracking**: In `Layer3SymbolState._maybe_emit_signal()`, after signal evaluation:
   ```python
   _signal_direction_count.labels(symbol=self.symbol, direction=sized.direction).inc()
   if sized.direction != "HOLD":
       _signal_strength_histogram.labels(symbol=self.symbol).observe(sized.signal_strength)
   ```

3. **EMA Crossover Detection**: In `IndicatorManager.process()`, detect crossovers by comparing current and previous EMA states:
   ```python
   if self._previous_ema_fast is not None:
       if self._previous_ema_fast < self._previous_ema_slow and ema_fast > ema_slow:
           _ema_crossover_events.labels(symbol=self.symbol, direction="bullish").inc()
       elif self._previous_ema_fast > self._previous_ema_slow and ema_fast < ema_slow:
           _ema_crossover_events.labels(symbol=self.symbol, direction="bearish").inc()
   ```

**No service.py creation needed** - Layer 3 already has a service.py file with metrics server running on port 9104.

---

### Layer 4 Risk Metrics

**Files**: 
- `services/layer4_risk/service.py` (create new)
- `services/layer4_risk/engine.py` (modify to expose state)

**Metrics to Add**:

```python
from prometheus_client import Counter, Gauge

# Trade Rejections
_trade_rejections = Counter(
    "risk_trade_rejections_total",
    "Trade rejections by reason",
    ["reason"]  # Dynamic: exposure_limit|drawdown_limit|circuit_breaker|consecutive_losses|etc.
)

# Portfolio State
_current_exposure_pct = Gauge(
    "risk_current_exposure_percent",
    "Current portfolio exposure percentage",
    ["symbol"]
)

_current_drawdown_pct = Gauge(
    "risk_current_drawdown_percent",
    "Current drawdown from peak",
    []
)

# Circuit Breaker
_circuit_breaker_state = Gauge(
    "risk_circuit_breaker_state",
    "Circuit breaker state (0=NORMAL, 1=REDUCED, 2=HALTED)",
    []
)

_consecutive_losses = Gauge(
    "risk_consecutive_loss_count",
    "Current consecutive loss counter",
    []
)
```

**New Service Architecture**:

```python
# services/layer4_risk/service.py

from dataclasses import dataclass
from kafka import KafkaConsumer
from prometheus_client import start_http_server
from .engine import Layer4RiskEngine

@dataclass
class Layer4Service:
    consumer: KafkaConsumer
    publisher: KafkaJsonPublisher
    engine: Layer4RiskEngine
    
    def run_forever(self) -> None:
        for msg in self.consumer:
            signal = TradeSignal.model_validate(json.loads(msg.value))
            
            # Evaluate signal
            decision = self.engine.evaluate_signal(
                signal,
                reference_price=signal.entry_price,
                current_portfolio_exposure_pct=self._calculate_exposure()
            )
            
            # Export metrics
            if not decision.approved:
                _trade_rejections.labels(reason=decision.reason).inc()
            
            _circuit_breaker_state.set(
                {"NORMAL": 0, "REDUCED": 1, "HALTED": 2}[decision.circuit_breaker_state]
            )
            _consecutive_losses.set(self.engine.state.consecutive_losing_trades)
            _current_drawdown_pct.set(self.engine.state.latest_drawdown_pct * 100)
            
            # Publish approved orders
            if decision.approved:
                self.publisher.publish(decision.approved_order.model_dump())

def main():
    start_http_server(9105)  # Metrics on port 9105
    svc = build_service()
    svc.run_forever()
```

**Engine Modifications**:
- No breaking changes to `engine.py`
- Service wraps engine and reads state for metrics export
- Engine continues to return `RiskDecision` objects

---

### Layer 5 Execution Metrics

**Files**:
- `services/layer5_execution/service.py` (create new)
- `services/layer5_execution/engine.py` (modify to add timing)

**Metrics to Add**:

```python
from prometheus_client import Counter, Histogram

# Order Placement
_order_placement_latency = Histogram(
    "execution_order_placement_latency_ms",
    "Order placement latency to exchange",
    ["exchange_id"],
    buckets=[1, 5, 10, 20, 50, 100, 200, 500, 1000]
)

# Retries and Failures
_order_retry_count = Counter(
    "execution_order_retries_total",
    "Order retry attempts",
    ["exchange_id", "reason"]  # reason = timeout|rate_limit|rejected|duplicate
)

_idempotency_dedup_hits = Counter(
    "execution_idempotency_dedup_hits_total",
    "Idempotency deduplication hits (prevented duplicate orders)",
    ["exchange_id"]
)

_order_failures = Counter(
    "execution_order_failures_total",
    "Failed orders by reason",
    ["exchange_id", "reason"]  # reason = insufficient_balance|invalid_price|rejected|max_retries
)

# Slippage
_slippage_bps = Histogram(
    "execution_slippage_bps",
    "Execution slippage in basis points",
    ["symbol", "direction"],
    buckets=[-100, -50, -20, -10, -5, 0, 5, 10, 20, 50, 100]
)
```

**New Service Architecture**:

```python
# services/layer5_execution/service.py

from dataclasses import dataclass
import time
from kafka import KafkaConsumer
from prometheus_client import start_http_server
from .engine import ExecutionEngine

@dataclass
class Layer5Service:
    consumer: KafkaConsumer
    publisher: KafkaJsonPublisher
    engine: ExecutionEngine
    
    def run_forever(self) -> None:
        for msg in self.consumer:
            order = ApprovedOrder.model_validate(json.loads(msg.value))
            
            # Time order placement
            start_time = time.perf_counter()
            try:
                executed = self.engine.submit_order(order, reference_price=order.entry_price)
                latency_ms = (time.perf_counter() - start_time) * 1000
                
                # Export metrics
                exchange_id = self._extract_exchange_id(order)
                _order_placement_latency.labels(exchange_id=exchange_id).observe(latency_ms)
                
                # Calculate slippage
                slippage_bps = ((executed.avg_fill_price - order.entry_price) / order.entry_price) * 10000
                _slippage_bps.labels(symbol=order.symbol, direction=order.direction).observe(slippage_bps)
                
                # Track retries and dedups from engine telemetry
                if self.engine.telemetry.duplicate_orders > self._last_dedup_count:
                    _idempotency_dedup_hits.labels(exchange_id=exchange_id).inc()
                    self._last_dedup_count = self.engine.telemetry.duplicate_orders
                
                # Publish execution result
                self.publisher.publish(executed.model_dump())
                
            except Exception as exc:
                _order_failures.labels(
                    exchange_id=exchange_id,
                    reason=self._classify_failure(exc)
                ).inc()

def main():
    start_http_server(9106)  # Metrics on port 9106
    svc = build_service()
    svc.run_forever()
```

**Engine Modifications**:
- Add timing instrumentation in `submit_order()` method
- Track retry attempts in existing retry loop
- Expose telemetry counters for service to read

---

### Layer 6 Audit Metrics

**File**: `shared/audit.py` (modify existing)

**Metrics to Add**:

```python
from prometheus_client import Counter, Histogram
import time

# Audit Log Performance
_audit_log_write_latency = Histogram(
    "audit_log_write_latency_ms",
    "Audit log write latency",
    [],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 50]
)

# Hash Chain Integrity
_hash_verification_failures = Counter(
    "audit_hash_verification_failures_total",
    "Hash chain verification failures",
    ["reason"]  # reason = mismatch|missing|corrupted
)

_chain_continuity_breaks = Counter(
    "audit_chain_continuity_breaks_total",
    "Hash chain continuity breaks detected",
    []
)
```

**Integration**:

```python
def emit_audit_event(event_type: str, *, source: str, payload: Optional[Dict[str, Any]] = None) -> None:
    event = {
        "event_type": event_type,
        "source": source,
        "timestamp_ms": int(time.time() * 1000),
        "payload": payload or {},
    }
    line = json.dumps(event, separators=(",", ":"), sort_keys=True)
    print(line)

    log_path = os.getenv("AUDIT_LOG_PATH")
    if log_path:
        start_time = time.perf_counter()
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            latency_ms = (time.perf_counter() - start_time) * 1000
            _audit_log_write_latency.observe(latency_ms)
        except OSError:
            pass  # Best-effort logging
```

**Hash Chain Verification** (if hash chain logger exists):
- Add metrics to hash chain verification logic
- Track mismatches and continuity breaks
- Export on Layer 1 validated service metrics server (port 9102)

---

## Data Models

### Metric Label Schemas

**Layer 3 Labels**:
- `symbol`: Trading pair (e.g., "BTC-USDT")
- `timeframe`: Candle timeframe ("5m" | "1h")
- `direction`: Signal or crossover direction ("LONG" | "SHORT" | "HOLD" | "bullish" | "bearish")

**Layer 4 Labels**:
- `reason`: Rejection reason (dynamic string)
- `symbol`: Trading pair

**Layer 5 Labels**:
- `exchange_id`: Exchange identifier ("binance" | "okx" | "bybit" | etc.)
- `symbol`: Trading pair
- `direction`: Order direction ("LONG" | "SHORT")
- `reason`: Retry or failure reason (dynamic string)

**Layer 6 Labels**:
- `reason`: Hash verification failure reason ("mismatch" | "missing" | "corrupted")

### Metric Value Ranges

- **RSI**: 0-100 (typical range 30-70)
- **MACD Histogram**: -∞ to +∞ (typically -5 to +5)
- **Bollinger Band Width**: 0-1 (normalized)
- **Signal Strength**: 0-1
- **Exposure Percentage**: 0-100
- **Drawdown Percentage**: 0-100
- **Circuit Breaker State**: 0 (NORMAL), 1 (REDUCED), 2 (HALTED)
- **Latency**: milliseconds (0-1000+)
- **Slippage**: basis points (-100 to +100)

---

## Interface Specifications

### Metrics HTTP Endpoints

**Layer 3 Strategy**:
- Endpoint: `http://localhost:9104/metrics`
- Already exists, add new metrics to existing server

**Layer 4 Risk**:
- Endpoint: `http://localhost:9105/metrics`
- New HTTP server in new service.py

**Layer 5 Execution**:
- Endpoint: `http://localhost:9106/metrics`
- New HTTP server in new service.py

**Layer 6 Audit**:
- Endpoint: `http://localhost:9102/metrics` (Layer 1 validated service)
- Add metrics to existing server

### Prometheus Scrape Configuration

Add to `ops/prometheus/prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'layer4-risk'
    static_configs:
      - targets: ['layer4-risk:9105']
  
  - job_name: 'layer5-execution'
    static_configs:
      - targets: ['layer5-execution:9106']
```

---

## Error Handling

### Metric Export Failures

**Strategy**: Best-effort metric export
- Metric export failures do NOT crash services
- Use try-except blocks around metric updates
- Log errors but continue processing

**Example**:
```python
try:
    _indicator_rsi.labels(symbol=symbol, timeframe=timeframe).set(rsi_value)
except Exception as exc:
    logger.warning(f"Failed to export RSI metric: {exc}")
```

### Missing Data Handling

**Indicators**: Export only when values are available
```python
if snapshot is not None and snapshot.rsi is not None:
    _indicator_rsi.labels(symbol=symbol, timeframe=timeframe).set(snapshot.rsi)
```

**Slippage**: Only calculate when execution succeeds
```python
if executed.avg_fill_price > 0:
    slippage_bps = ((executed.avg_fill_price - order.entry_price) / order.entry_price) * 10000
    _slippage_bps.labels(symbol=order.symbol, direction=order.direction).observe(slippage_bps)
```

---

## Performance Considerations

### Metric Cardinality

**Low Cardinality** (✅ Good):
- `symbol`: ~10 trading pairs
- `timeframe`: 2 values (5m, 1h)
- `direction`: 3-5 values (LONG, SHORT, HOLD, bullish, bearish)
- `exchange_id`: ~5 exchanges

**Total Cardinality**: ~1000 unique time series (acceptable)

### Metric Update Frequency

- **Layer 3 Indicators**: Updated every 5m/1h (low frequency)
- **Layer 4 State**: Updated every signal evaluation (~1-10/min)
- **Layer 5 Latency**: Updated every order submission (~1-100/min)
- **Layer 6 Audit**: Updated every audit event (~10-1000/min)

**Performance Impact**: Negligible (<1ms per metric update)

### Memory Overhead

- Prometheus client library: ~10KB per metric
- Total new metrics: ~25 metrics
- Memory overhead: ~250KB (negligible)

---

## Security Considerations

### Metric Exposure

**Risk**: Metrics endpoints expose system internals
**Mitigation**: 
- Metrics servers bind to localhost by default
- Production deployment uses internal network only
- No sensitive data (API keys, passwords) in metrics

### Label Injection

**Risk**: Dynamic labels could be exploited for cardinality explosion
**Mitigation**:
- Validate label values before export
- Use enums for known categorical values
- Sanitize dynamic strings (rejection reasons)

**Example**:
```python
def sanitize_reason(reason: str) -> str:
    """Sanitize rejection reason to prevent cardinality explosion."""
    # Replace spaces with underscores, limit length
    return reason.replace(" ", "_")[:50]

_trade_rejections.labels(reason=sanitize_reason(decision.reason)).inc()
```

---

## Testing Strategy

### Unit Tests

**Not required for this phase** - metrics are observability instrumentation, not business logic.

### Integration Tests

**Manual verification**:
1. Start services with metrics enabled
2. Curl each /metrics endpoint
3. Verify metrics appear in Prometheus format
4. Process test data through pipeline
5. Verify metric values update in real-time

**Example**:
```bash
# Layer 3 Strategy
curl -s http://localhost:9104/metrics | grep strategy_indicator_rsi

# Layer 4 Risk
curl -s http://localhost:9105/metrics | grep risk_circuit_breaker_state

# Layer 5 Execution
curl -s http://localhost:9106/metrics | grep execution_order_placement_latency_ms

# Layer 6 Audit
curl -s http://localhost:9102/metrics | grep audit_log_write_latency_ms
```

### Verification Checklist

- [ ] All metrics defined in OBSERVABILITY_METRICS_SPEC.md are exported
- [ ] Metrics follow naming conventions
- [ ] Label cardinality is low (<1000 unique series)
- [ ] Services rebuild without errors
- [ ] Metrics update in real-time during operation
- [ ] No performance degradation (<1% overhead)

---

## Deployment Strategy

### Rollout Plan

**Phase 1**: Layer 3 Strategy (30 minutes)
- Add metrics to existing service.py
- Rebuild and test
- Verify metrics in Grafana

**Phase 2**: Layer 4 Risk (45 minutes)
- Create new service.py
- Add metrics export
- Rebuild and test
- Update docker-compose.yml

**Phase 3**: Layer 5 Execution (45 minutes)
- Create new service.py
- Add timing instrumentation
- Rebuild and test
- Update docker-compose.yml

**Phase 4**: Layer 6 Audit (20 minutes)
- Add metrics to shared/audit.py
- Rebuild all services
- Verify metrics on Layer 1 endpoint

**Total Estimated Time**: 2.5 hours

### Rollback Plan

**If metrics cause issues**:
1. Revert code changes
2. Rebuild services
3. Restart containers

**Risk**: Low - metrics are non-blocking and best-effort

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Metric Export Completeness

For any layer service that processes data, all metrics defined in the OBSERVABILITY_METRICS_SPEC.md for that layer SHALL be exported on the /metrics endpoint.

**Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2**

### Property 2: Metric Naming Consistency

For any exported metric, the metric name SHALL follow the pattern `<layer>_<component>_<metric_type>_<unit>` where layer is one of {strategy, risk, execution, audit}.

**Validates: Requirements 5.2**

### Property 3: Label Cardinality Bounds

For any metric with labels, the total number of unique label combinations SHALL be less than 1000 to prevent cardinality explosion.

**Validates: Requirements 5.4**

### Property 4: Non-Breaking Integration

For any existing service or engine class, adding metrics SHALL NOT modify the public API or break existing functionality.

**Validates: Requirements 5.6, 6.5**

### Property 5: Real-Time Metric Updates

For any metric that tracks system state, when the underlying state changes, the metric value SHALL update within 1 second.

**Validates: Requirements 7.3**

### Property 6: Service Architecture Consistency

For any layer that exports metrics, if the layer has an engine.py file, it SHALL also have a service.py file that wraps the engine and exports metrics.

**Validates: Requirements 6.1, 6.2, 6.3**

### Property 7: HTTP Endpoint Availability

For any layer service that exports metrics, the /metrics HTTP endpoint SHALL return a 200 OK response with Prometheus text format when queried.

**Validates: Requirements 7.1, 7.2**

---

## References

- **OBSERVABILITY_METRICS_SPEC.md**: Complete metrics specification
- **OBSERVABILITY_IMPLEMENTATION_GUIDE.md**: Implementation patterns and SRE playbooks
- **Layer 2 Anomaly Service**: Reference implementation for service architecture
- **Layer 1 Ingestion Adapters**: Reference implementation for metrics patterns
- **Prometheus Client Library**: https://github.com/prometheus/client_python

---

## Appendix: Metric Definitions Summary

### Layer 3 Strategy (6 metrics)
- `strategy_indicator_rsi` (Gauge)
- `strategy_indicator_macd_histogram` (Gauge)
- `strategy_indicator_bollinger_width` (Gauge)
- `strategy_signal_direction_total` (Counter)
- `strategy_signal_strength_distribution` (Histogram)
- `strategy_ema_crossover_events_total` (Counter)

### Layer 4 Risk (5 metrics)
- `risk_trade_rejections_total` (Counter)
- `risk_current_exposure_percent` (Gauge)
- `risk_current_drawdown_percent` (Gauge)
- `risk_circuit_breaker_state` (Gauge)
- `risk_consecutive_loss_count` (Gauge)

### Layer 5 Execution (5 metrics)
- `execution_order_placement_latency_ms` (Histogram)
- `execution_order_retries_total` (Counter)
- `execution_idempotency_dedup_hits_total` (Counter)
- `execution_order_failures_total` (Counter)
- `execution_slippage_bps` (Histogram)

### Layer 6 Audit (3 metrics)
- `audit_log_write_latency_ms` (Histogram)
- `audit_hash_verification_failures_total` (Counter)
- `audit_chain_continuity_breaks_total` (Counter)

**Total: 19 new metrics**


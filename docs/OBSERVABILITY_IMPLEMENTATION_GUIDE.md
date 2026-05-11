# Observability Implementation Guide - SRE Operations

**Target**: Production-grade algorithmic trading platform  
**Philosophy**: Forensic visibility, root-cause analysis, operational resilience

---

## IMPLEMENTATION ROADMAP

### Phase 1: Trust Score Decomposition (Week 1)

**Priority**: CRITICAL - Trust degradation is a security event

1. **Add trust subscore metrics** to `services/layer1_validated/service.py`
   - Export T1-T5 independently
   - Add trust degradation event counter
   - Implement histogram for distribution analysis

2. **Update Grafana dashboard**
   - Add Row 3: Trust Score Decomposition
   - Create trust subcomponents timeline panel
   - Add trust degradation heatmap
   - Add current component stat panel

3. **Configure alerts**
   - Critical: Any T-score < 0.5 for >1min
   - Warning: Trust drop >0.1 in single window
   - Info: Trust degradation event (for forensics)

**Validation**:
```bash
# Check metrics are exported
curl -s http://localhost:9102/metrics | grep trust_subscore

# Verify in Grafana
# Navigate to Trust Score Decomposition row
# Confirm all T1-T5 lines visible
# Trigger test: empty tls_pins.json → T1 should drop to 0.0
```

---

### Phase 2: Anomaly Score Decomposition (Week 2)

**Priority**: HIGH - Anomaly attribution for attack forensics

1. **Add anomaly subscore metrics** to `services/layer2_anomaly/service.py`
   - Export IF, HST, MAD, fused scores
   - Add HMM regime state and posterior probabilities
   - Export feature vector components
   - Add model inference latency histograms

2. **Update Grafana dashboard**
   - Add Row 4: Anomaly Score Decomposition
   - Create anomaly subcomponents timeline
   - Add HMM regime state timeline
   - Add feature vector heatmap

3. **Configure alerts**
   - Critical: Fused anomaly > 0.9 for >30s
   - Warning: MAD guard triggered
   - Info: Regime transition (for pattern analysis)

**Validation**:
```bash
# Check anomaly metrics
curl -s http://localhost:9103/metrics | grep anomaly_subscore

# Verify HMM regime tracking
curl -s http://localhost:9103/metrics | grep hmm_regime

# Test: Inject synthetic anomaly → all components should spike
```

---

### Phase 3: Layer-Specific Telemetry (Week 3-4)

**Priority**: MEDIUM - Deep layer visibility

1. **Layer 1 Ingestion**
   - Add exchange connection health gauge
   - Track WebSocket reconnects by reason
   - Count TLS failures by type
   - Track tick rejection reasons

2. **Layer 2 Anomaly**
   - Add model inference latency histograms
   - Track feature extraction performance
   - Count regime transitions

3. **Layer 3 Strategy**
   - Export RSI, MACD, Bollinger Band values
   - Track signal generation frequency
   - Count LONG/SHORT/HOLD ratio

4. **Layer 4 Risk**
   - Export current exposure percentage
   - Track drawdown from peak
   - Monitor circuit breaker state
   - Count trade rejections by reason

5. **Layer 5 Execution**
   - Track order placement latency
   - Count retries and failures
   - Measure slippage distribution
   - Monitor idempotency dedup hits

6. **Layer 6 Audit**
   - Track audit log write latency
   - Count hash verification failures
   - Monitor chain continuity

**Validation**: Each layer should have dedicated Grafana row with 3-4 panels

---

### Phase 4: Kafka & Pipeline Observability (Week 5)

**Priority**: HIGH - Pipeline bottleneck identification

1. **Kafka Consumer Lag Monitoring**
   ```python
   # shared/kafka_monitoring.py
   
   from kafka import KafkaConsumer
   from kafka.structs import TopicPartition
   
   def export_consumer_lag(consumer: KafkaConsumer, group_id: str):
       """Export Kafka consumer lag metrics."""
       for topic, partitions in consumer.assignment().items():
           for partition in partitions:
               tp = TopicPartition(topic, partition)
               committed = consumer.committed(tp)
               position = consumer.position(tp)
               if committed is not None:
                   lag = position - committed
                   _kafka_consumer_lag.labels(
                       consumer_group=group_id,
                       topic=topic,
                       partition=str(partition)
                   ).set(lag)
   ```

2. **Pipeline Stage Latency Tracking**
   - Add correlation IDs to all messages
   - Track end-to-end latency per stage
   - Identify bottlenecks with percentile analysis

3. **Backpressure Detection**
   - Monitor queue depth / capacity ratio
   - Alert when backpressure > 0.8

**Validation**:
```bash
# Check consumer lag
curl -s http://localhost:9102/metrics | grep kafka_consumer_lag

# Verify pipeline latency tracking
curl -s http://localhost:9102/metrics | grep pipeline_stage_latency
```

---

## SRE OPERATIONAL PLAYBOOKS

### Playbook 1: Trust Score Sudden Drop

**Symptom**: Trust score drops from 0.85 to 0.55 in <1 minute

**Investigation Steps**:

1. **Check Trust Decomposition Panel**
   ```
   Navigate to: Row 3 - Trust Score Decomposition
   Look for: Which T-score dropped?
   ```

2. **Root Cause by Component**:

   **If T1 (TLS) dropped**:
   ```bash
   # Check TLS health
   curl -s http://localhost:9102/metrics | grep tls_exchange_health
   
   # Check TLS failures
   curl -s http://localhost:9102/metrics | grep tls_pin_mismatch_total
   
   # Action: Refresh SPKI pins
   python scripts/refresh_spki_pins.py
   docker compose restart layer1-ingestion
   ```

   **If T2 (Consensus) dropped**:
   ```bash
   # Check divergent sources
   curl -s http://localhost:9102/metrics | grep consensus_divergent_source_count
   
   # Check divergence magnitude
   curl -s http://localhost:9102/metrics | grep consensus_divergence_max_bps
   
   # Action: Investigate exchange price feeds
   # Check if one exchange is stale or manipulated
   docker compose logs layer1-ingestion | grep divergent
   ```

   **If T3 (Freshness) dropped**:
   ```bash
   # Check latency
   curl -s http://localhost:9102/metrics | grep layer1_validated_last_window_latency_ms
   
   # Action: Check network latency to exchanges
   # Verify no network congestion
   # Check if exchange is slow to respond
   ```

   **If T4 (Sequence) dropped**:
   ```bash
   # Check sequence gaps
   curl -s http://localhost:9102/metrics | grep sequence_gap_distribution
   
   # Action: Investigate exchange feed quality
   # Check for message loss or reordering
   docker compose logs layer1-ingestion | grep sequence
   ```

   **If T5 (HashChain) dropped**:
   ```bash
   # Check hash chain continuity
   docker compose logs layer1-validated | grep hash_chain
   
   # Action: CRITICAL - potential data integrity issue
   # Verify audit logs
   # Check for tampering or corruption
   ```

3. **Correlate with Anomaly Score**
   ```
   Navigate to: Row 4 - Anomaly Score Decomposition
   Check if: Anomaly spike coincides with trust drop
   If yes: Potential attack or manipulation
   ```

4. **Check Decision Gate State**
   ```
   Navigate to: System State panel
   Verify: System transitioned to CONSERVATIVE or DEGRADED
   Expected: Automatic risk reduction activated
   ```

---

### Playbook 2: Anomaly Score Spike

**Symptom**: Anomaly score spikes from 0.2 to 0.95

**Investigation Steps**:

1. **Check Anomaly Decomposition Panel**
   ```
   Navigate to: Row 4 - Anomaly Score Decomposition
   Identify: Which model triggered? (IF, HST, or MAD)
   ```

2. **Analyze Feature Vector**
   ```
   Navigate to: Feature Vector Heatmap
   Look for: Which feature(s) are outliers?
   ```

3. **Root Cause by Feature**:

   **If raw_return is outlier**:
   ```
   Interpretation: Sudden large price movement
   Action: Verify if legitimate market event or manipulation
   Check: News, exchange announcements, order book depth
   ```

   **If rolling_volatility is outlier**:
   ```
   Interpretation: Volatility regime change
   Action: Check HMM regime state
   Expected: Regime transition from Normal → High Vol
   ```

   **If spread_divergence is outlier**:
   ```
   Interpretation: Bid-ask spread anomaly
   Action: Check exchange liquidity
   Possible: Market manipulation, flash crash, or exchange issue
   ```

   **If latency_anomaly is outlier**:
   ```
   Interpretation: Unusual latency spike
   Action: Check network performance
   Verify: No DDoS or network congestion
   ```

   **If trust_degradation is outlier**:
   ```
   Interpretation: Trust score dropped suddenly
   Action: Follow "Trust Score Sudden Drop" playbook
   ```

4. **Check HMM Regime State**
   ```
   Navigate to: HMM Regime State Timeline
   Verify: Did regime transition occur?
   Expected: Regime change should precede anomaly spike
   ```

5. **Check MAD Guard**
   ```
   Navigate to: Anomaly Subcomponents Timeline
   Look for: MAD Guard activation (dashed purple line)
   If active: Extreme outlier detected, system in defensive mode
   ```

6. **Correlate with Trust Score**
   ```
   Navigate to: Trust Score Decomposition
   Check if: Trust dropped simultaneously
   If yes: Coordinated attack or systemic issue
   ```

7. **Decision Gate Response**
   ```
   Navigate to: System State panel
   Verify: System transitioned to DEGRADED or HALT
   Expected: Trading halted or severely restricted
   ```

---

### Playbook 3: Pipeline Bottleneck

**Symptom**: Kafka consumer lag increasing, latency spiking

**Investigation Steps**:

1. **Check Kafka Consumer Lag**
   ```bash
   # Check lag by topic
   curl -s http://localhost:9102/metrics | grep kafka_consumer_lag_seconds
   
   # Identify bottleneck stage
   # If lag on market.ticks.raw → Layer 1 validated is slow
   # If lag on market.ticks.validated → Layer 2 anomaly is slow
   # If lag on market.ticks.scored → Layer 3 strategy is slow
   ```

2. **Check Pipeline Stage Latency**
   ```
   Navigate to: Pipeline Performance row
   Look for: Which stage has highest p99 latency?
   ```

3. **Root Cause by Stage**:

   **If Layer 1 Validated is slow**:
   ```bash
   # Check processing rate
   curl -s http://localhost:9102/metrics | grep layer1_validated_windows_total
   
   # Check if consensus is slow
   curl -s http://localhost:9102/metrics | grep consensus_divergent_source_count
   
   # Action: Optimize consensus algorithm or scale horizontally
   ```

   **If Layer 2 Anomaly is slow**:
   ```bash
   # Check model inference latency
   curl -s http://localhost:9103/metrics | grep anomaly_model_inference_duration_ms
   
   # Check feature extraction latency
   curl -s http://localhost:9103/metrics | grep anomaly_feature_extraction_duration_ms
   
   # Action: Optimize model inference or use faster models
   # Consider: Model quantization, batch inference, or GPU acceleration
   ```

   **If Layer 3 Strategy is slow**:
   ```bash
   # Check indicator calculation latency
   docker compose logs layer3-strategy | grep "slow"
   
   # Action: Optimize indicator calculations
   # Consider: Incremental updates instead of full recalculation
   ```

4. **Check Backpressure**
   ```bash
   # Check queue depth ratio
   curl -s http://localhost:9102/metrics | grep pipeline_backpressure_ratio
   
   # If > 0.8: Backpressure detected
   # Action: Scale bottleneck stage or optimize processing
   ```

5. **Check Resource Utilization**
   ```bash
   # Check CPU/memory usage
   docker stats
   
   # If high: Resource exhaustion
   # Action: Scale vertically (more CPU/RAM) or horizontally (more instances)
   ```

---

## ADVANCED OBSERVABILITY PATTERNS

### Pattern 1: Distributed Tracing with Correlation IDs

**Implementation**:

```python
# shared/correlation.py

import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str] = ContextVar('correlation_id', default='')

def generate_correlation_id() -> str:
    """Generate a new correlation ID."""
    return str(uuid.uuid4())

def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID for the current context."""
    _correlation_id.set(correlation_id)

def get_correlation_id() -> str:
    """Get the correlation ID for the current context."""
    return _correlation_id.get()

# Usage in Layer 1 Ingestion
from shared.correlation import generate_correlation_id, set_correlation_id

async def _print_and_publish_ticks(name: str, tick_iter, stop, publisher):
    async for tick in tick_iter:
        correlation_id = generate_correlation_id()
        set_correlation_id(correlation_id)
        
        # Add correlation_id to tick metadata
        tick_with_id = tick.model_copy(update={
            "correlation_id": correlation_id,
            "ingestion_timestamp_ms": int(time.time() * 1000)
        })
        
        publisher.publish(tick_with_id)
        
        # Log with correlation ID
        logger.info(f"[{correlation_id}] Published tick: {tick.symbol}")
```

**Grafana Query**:
```promql
# Trace a specific correlation ID through the pipeline
{correlation_id="abc-123-def"} |= "Published" or "Validated" or "Scored"
```

---

### Pattern 2: Attack Replay Visualization

**Implementation**:

```python
# services/layer2_anomaly/attack_replay.py

from dataclasses import dataclass
from typing import List
import json

@dataclass
class AttackEvent:
    timestamp_ms: int
    correlation_id: str
    anomaly_score: float
    trust_score: float
    feature_vector: dict
    decision_gate_state: str
    
def record_attack_event(tick: ValidatedTick, anomaly_score: float, features: dict):
    """Record attack event for replay."""
    if anomaly_score > 0.9:  # High anomaly threshold
        event = AttackEvent(
            timestamp_ms=tick.timestamp_utc,
            correlation_id=tick.correlation_id,
            anomaly_score=anomaly_score,
            trust_score=tick.trust_score,
            feature_vector=features,
            decision_gate_state=get_current_state()
        )
        
        # Write to attack replay log
        with open("logs/attack_replay.jsonl", "a") as f:
            f.write(json.dumps(event.__dict__) + "\n")
        
        # Export metric for Grafana annotation
        _attack_event_marker.labels(
            symbol=tick.symbol,
            severity="high" if anomaly_score > 0.95 else "medium"
        ).set(1)
```

**Grafana Annotation**:
```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "prometheus"
  },
  "enable": true,
  "expr": "attack_event_marker == 1",
  "iconColor": "red",
  "name": "Attack Events",
  "tagKeys": "severity,symbol",
  "textFormat": "Attack detected: {{symbol}}",
  "titleFormat": "Anomaly Spike"
}
```

---

### Pattern 3: Synthetic Attack Injection (Testing)

**Implementation**:

```python
# scripts/inject_synthetic_attack.py

import asyncio
import random
from shared.schemas import NormalizedTick

async def inject_price_manipulation_attack(publisher, symbol: str, duration_s: int):
    """Inject synthetic price manipulation attack for testing."""
    print(f"[ATTACK] Injecting price manipulation for {symbol} ({duration_s}s)")
    
    start_time = time.time()
    while time.time() - start_time < duration_s:
        # Create manipulated tick with extreme price
        manipulated_tick = NormalizedTick(
            symbol=symbol,
            exchange_id="binance",
            mid=100000.0,  # Extreme price
            bid=99999.0,
            ask=100001.0,
            volume_24h=1000000.0,
            spread=0.0001,
            exchange_timestamp_ms=int(time.time() * 1000),
            received_timestamp_ms=int(time.time() * 1000),
            sequence_id=None,
            tls_ok=True,
            timestamp_source="exchange"
        )
        
        publisher.publish(manipulated_tick)
        await asyncio.sleep(0.1)  # 10 ticks/second
    
    print(f"[ATTACK] Attack injection complete")

# Usage
# python scripts/inject_synthetic_attack.py --symbol BTC-USDT --duration 60
```

**Expected Observability**:
1. Trust score T2 (consensus) should drop (price divergence)
2. Anomaly score should spike (IF and HST detect outlier)
3. Feature vector: `raw_return` and `spread_divergence` should be outliers
4. Decision gate should transition to DEGRADED or HALT
5. Attack event annotation should appear in Grafana

---

## PRODUCTION DEPLOYMENT CHECKLIST

### Pre-Deployment

- [ ] All metrics exported and validated in dev environment
- [ ] Grafana dashboard tested with synthetic data
- [ ] Alert rules configured and tested
- [ ] Playbooks documented and team trained
- [ ] Correlation IDs implemented across all layers
- [ ] Attack replay logging enabled

### Deployment

- [ ] Deploy metrics changes to production
- [ ] Import Grafana dashboard
- [ ] Configure alert routing (PagerDuty, Slack)
- [ ] Enable Prometheus recording rules for performance
- [ ] Set up Grafana snapshots for incident reports

### Post-Deployment

- [ ] Verify all metrics are being scraped
- [ ] Test alert firing with synthetic anomaly
- [ ] Run attack injection test in staging
- [ ] Document baseline metric values
- [ ] Train SRE team on new observability features

---

## PERFORMANCE OPTIMIZATION

### Prometheus Recording Rules

```yaml
# /etc/prometheus/rules/algo_trading.yml

groups:
  - name: trust_score_aggregations
    interval: 10s
    rules:
      # Pre-compute trust score moving average
      - record: trust_score:5m_avg
        expr: avg_over_time(layer1_validated_last_trust_score[5m])
      
      # Pre-compute trust score volatility
      - record: trust_score:5m_stddev
        expr: stddev_over_time(layer1_validated_last_trust_score[5m])
      
      # Pre-compute anomaly score percentiles
      - record: anomaly_score:p99
        expr: histogram_quantile(0.99, rate(anomaly_score_distribution_bucket[5m]))

  - name: pipeline_performance
    interval: 30s
    rules:
      # Pre-compute pipeline stage p99 latency
      - record: pipeline_latency:p99:by_stage
        expr: histogram_quantile(0.99, rate(pipeline_stage_latency_ms_bucket[5m])) by (stage)
      
      # Pre-compute Kafka consumer lag aggregate
      - record: kafka_lag:max:by_topic
        expr: max by (topic) (kafka_consumer_lag_seconds)
```

### Grafana Query Optimization

```promql
# BAD: Expensive aggregation on every dashboard load
avg_over_time(layer1_validated_last_trust_score[5m])

# GOOD: Use pre-computed recording rule
trust_score:5m_avg

# BAD: High-cardinality label in aggregation
sum by (correlation_id) (rate(layer1_ingestion_ticks_total[1m]))

# GOOD: Aggregate by low-cardinality label
sum by (exchange_id) (rate(layer1_ingestion_ticks_total[1m]))
```

---

## SUMMARY

### What You Get

1. **Forensic Visibility**
   - Trust score decomposition (T1-T5)
   - Anomaly score decomposition (IF, HST, MAD, fused)
   - Feature vector observability
   - HMM regime tracking

2. **Root-Cause Analysis**
   - Trust degradation event tracking
   - Anomaly attribution by model and feature
   - Pipeline bottleneck identification
   - Attack replay capability

3. **Operational Resilience**
   - Layer-by-layer health monitoring
   - Kafka consumer lag tracking
   - Backpressure detection
   - Circuit breaker observability

4. **SRE Playbooks**
   - Trust score sudden drop
   - Anomaly score spike
   - Pipeline bottleneck
   - Attack investigation

### Metrics Added

- **Trust**: 15 new metrics (T1-T5 subscores, degradation events, histograms)
- **Anomaly**: 20 new metrics (IF, HST, MAD, HMM, features, inference latency)
- **Layer 1**: 10 new metrics (connection health, TLS, reconnects, rejections)
- **Layer 2**: 8 new metrics (model latency, regime transitions)
- **Layer 3**: 6 new metrics (indicators, signals)
- **Layer 4**: 5 new metrics (rejections, exposure, drawdown)
- **Layer 5**: 6 new metrics (latency, retries, slippage)
- **Layer 6**: 4 new metrics (audit log, hash verification)
- **Kafka**: 5 new metrics (consumer lag, rebalances)

**Total**: ~80 new metrics for production-grade observability

### Dashboard Panels Added

- **Row 3**: Trust Score Decomposition (3 panels)
- **Row 4**: Anomaly Score Decomposition (3 panels)
- **Row 5**: Layer 1 Deep Telemetry (3 panels)
- **Row 6**: Layer 2 Deep Telemetry (3 panels)
- **Row 7**: Layer 3-5 Telemetry (6 panels)
- **Row 8**: Kafka & Pipeline (2 panels enhanced)

**Total**: ~20 new panels, preserving existing 8 panels

---

**Status**: Ready for implementation  
**Estimated Effort**: 4-5 weeks (phased rollout)  
**Impact**: Production-grade observability for HFT/SIEM-level forensics

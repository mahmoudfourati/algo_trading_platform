# Production-Grade Observability Metrics Specification

**Target**: Algorithmic Trading Platform  
**Approach**: Evolutionary enhancement (preserve existing dashboard style)  
**Focus**: Forensic visibility, root-cause analysis, anomaly attribution

---

## PART 1: TRUST SCORE DECOMPOSITION METRICS

### Required New Metrics (Layer 1 Validated Service)

```python
# services/layer1_validated/service.py

from prometheus_client import Gauge, Histogram

# === TRUST SCORE SUBCOMPONENTS ===
# Export each T1-T5 component independently for forensic analysis

_trust_t1_tls = Gauge(
    "trust_subscore_t1_tls",
    "T1: TLS validity subscore [0,1]",
    ["symbol", "exchange_id"]
)

_trust_t2_consensus = Gauge(
    "trust_subscore_t2_consensus", 
    "T2: Consensus agreement subscore [0,1]",
    ["symbol"]
)

_trust_t3_freshness = Gauge(
    "trust_subscore_t3_freshness",
    "T3: Latency freshness subscore [0,1]", 
    ["symbol"]
)

_trust_t4_sequence = Gauge(
    "trust_subscore_t4_sequence",
    "T4: Sequence integrity subscore [0,1]",
    ["symbol", "exchange_id"]
)

_trust_t5_hashchain = Gauge(
    "trust_subscore_t5_hashchain",
    "T5: Hash chain continuity subscore [0,1]",
    ["symbol"]
)

_trust_t_availability = Gauge(
    "trust_subscore_t_availability",
    "T_availability: Exchange availability subscore [0,1]",
    ["symbol"]
)

# === TRUST SCORE DISTRIBUTION ===
# Histogram for anomaly detection on trust score itself

_trust_score_histogram = Histogram(
    "trust_score_distribution",
    "Trust score distribution for anomaly detection",
    ["symbol"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]
)

# === TRUST DEGRADATION EVENTS ===
# Counter for sudden trust drops (forensic trigger)

_trust_degradation_events = Counter(
    "trust_degradation_events_total",
    "Count of sudden trust score drops >0.1 in single window",
    ["symbol", "primary_cause"]  # primary_cause = t1|t2|t3|t4|t5|availability
)

# === CONSENSUS DIVERGENCE DETAILS ===

_consensus_divergent_sources = Gauge(
    "consensus_divergent_source_count",
    "Number of sources excluded from consensus due to price divergence",
    ["symbol"]
)

_consensus_divergence_magnitude = Gauge(
    "consensus_divergence_max_bps",
    "Maximum price divergence in basis points",
    ["symbol"]
)

# === SEQUENCE GAP TRACKING ===

_sequence_gap_histogram = Histogram(
    "sequence_gap_distribution",
    "Distribution of sequence gaps for gap analysis",
    ["symbol", "exchange_id"],
    buckets=[1, 2, 3, 5, 10, 20, 50, 100, 500, 1000]
)

# === TLS HEALTH DETAILS ===

_tls_pin_mismatch_total = Counter(
    "tls_pin_mismatch_total",
    "Total TLS pin mismatches by exchange",
    ["exchange_id", "reason"]  # reason = spki_mismatch|timeout|no_pin|cert_expired
)

_tls_reconnect_total = Counter(
    "tls_reconnect_total",
    "Total TLS-triggered reconnections",
    ["exchange_id"]
)
```

### Implementation in `_process_window()`:

```python
def _process_window(self, window: AlignedWindow) -> None:
    # ... existing code ...
    
    subscores = compute_subscores(
        tls_ok=tls_ok,
        t2=t2,
        latency_ms=latency_ms,
        sequence_gap=sequence_gap,
        chain_ok=chain_ok,
        active_exchanges=active_exchanges_set,
        configured_exchanges=configured_exchanges_set,
    )
    
    # === EXPORT TRUST SUBCOMPONENTS ===
    _trust_t1_tls.labels(symbol=symbol, exchange_id=self.primary_exchange).set(subscores["T1"])
    _trust_t2_consensus.labels(symbol=symbol).set(subscores["T2"])
    _trust_t3_freshness.labels(symbol=symbol).set(subscores["T3"])
    _trust_t4_sequence.labels(symbol=symbol, exchange_id=self.primary_exchange).set(subscores["T4"])
    _trust_t5_hashchain.labels(symbol=symbol).set(subscores["T5"])
    _trust_t_availability.labels(symbol=symbol).set(subscores.get("T_availability", 1.0))
    
    trust_score = compute_trust_score(weights=self.weights, subscores=subscores)
    
    # === TRUST SCORE HISTOGRAM ===
    _trust_score_histogram.labels(symbol=symbol).observe(trust_score)
    
    # === DETECT TRUST DEGRADATION ===
    previous_trust = self._last_trust_scores.get(symbol, trust_score)
    if previous_trust - trust_score > 0.1:  # >10% drop
        # Identify primary cause
        primary_cause = min(subscores.items(), key=lambda x: x[1])[0]
        _trust_degradation_events.labels(symbol=symbol, primary_cause=primary_cause).inc()
    self._last_trust_scores[symbol] = trust_score
    
    # === CONSENSUS DIVERGENCE DETAILS ===
    _consensus_divergent_sources.labels(symbol=symbol).set(len(out.divergent_sources))
    if out.divergent_sources:
        max_divergence_bps = max([
            abs(by_ex[ex].mid - out.consensus_mid) / out.consensus_mid * 10000
            for ex in out.divergent_sources
        ])
        _consensus_divergence_magnitude.labels(symbol=symbol).set(max_divergence_bps)
    
    # === SEQUENCE GAP HISTOGRAM ===
    if sequence_gap:
        _sequence_gap_histogram.labels(symbol=symbol, exchange_id=self.primary_exchange).observe(sequence_gap)
```

---

## PART 2: ANOMALY SCORE DECOMPOSITION METRICS

### Required New Metrics (Layer 2 Anomaly Service)

```python
# services/layer2_anomaly/service.py

# === ANOMALY SUBCOMPONENTS ===

_anomaly_if_score = Gauge(
    "anomaly_subscore_if",
    "Isolation Forest anomaly subscore [0,1]",
    ["symbol"]
)

_anomaly_hst_score = Gauge(
    "anomaly_subscore_hst",
    "Half-Space Trees anomaly subscore [0,1]",
    ["symbol"]
)

_anomaly_mad_triggered = Gauge(
    "anomaly_mad_guard_active",
    "MAD guard activation state (1=active, 0=inactive)",
    ["symbol"]
)

_anomaly_fused_score = Gauge(
    "anomaly_fused_score",
    "Final fused anomaly score [0,1]",
    ["symbol"]
)

# === HMM REGIME CLASSIFIER ===

_hmm_regime_state = Gauge(
    "hmm_regime_state",
    "Current HMM regime state (0=low_vol, 1=normal, 2=high_vol)",
    ["symbol"]
)

_hmm_regime_posterior = Gauge(
    "hmm_regime_posterior_prob",
    "HMM posterior probability for each regime",
    ["symbol", "regime"]  # regime = 0|1|2
)

_hmm_regime_transitions = Counter(
    "hmm_regime_transitions_total",
    "Total regime transitions",
    ["symbol", "from_regime", "to_regime"]
)

# === FEATURE VECTOR OBSERVABILITY ===

_feature_raw_return = Gauge(
    "anomaly_feature_raw_return",
    "Feature: raw log return",
    ["symbol"]
)

_feature_rolling_vol = Gauge(
    "anomaly_feature_rolling_volatility",
    "Feature: rolling volatility (30m RV)",
    ["symbol"]
)

_feature_spread_divergence = Gauge(
    "anomaly_feature_spread_divergence",
    "Feature: spread divergence z-score",
    ["symbol"]
)

_feature_latency_anomaly = Gauge(
    "anomaly_feature_latency_anomaly",
    "Feature: latency anomaly z-score",
    ["symbol"]
)

_feature_volume_anomaly = Gauge(
    "anomaly_feature_volume_anomaly",
    "Feature: volume anomaly z-score",
    ["symbol"]
)

_feature_trust_degradation = Gauge(
    "anomaly_feature_trust_degradation",
    "Feature: trust degradation signal",
    ["symbol"]
)

# === MODEL INFERENCE PERFORMANCE ===

_model_inference_latency = Histogram(
    "anomaly_model_inference_duration_ms",
    "Model inference latency in milliseconds",
    ["model"],  # model = isolation_forest|half_space_trees|hmm
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 50, 100]
)

_feature_extraction_latency = Histogram(
    "anomaly_feature_extraction_duration_ms",
    "Feature extraction latency in milliseconds",
    ["symbol"],
    buckets=[0.1, 0.5, 1, 2, 5, 10]
)

# === ANOMALY DISTRIBUTION ===

_anomaly_score_histogram = Histogram(
    "anomaly_score_distribution",
    "Anomaly score distribution",
    ["symbol"],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0]
)

# === DECISION GATE STATE TRANSITIONS ===

_decision_gate_transitions = Counter(
    "decision_gate_state_transitions_total",
    "Decision gate state transitions",
    ["from_state", "to_state"]  # NORMAL|CONSERVATIVE|DEGRADED|HALT
)

_decision_gate_trigger_reason = Counter(
    "decision_gate_trigger_total",
    "Decision gate trigger events by reason",
    ["trigger"]  # trust_low|anomaly_high|mad_triggered|manual
)
```

### Implementation in Layer 2 Service:

```python
def _process_tick(self, tick: ValidatedTick) -> None:
    # ... existing code ...
    
    # === FEATURE EXTRACTION TIMING ===
    start_time = time.perf_counter()
    features = self.engine.extract_features(tick)
    feature_latency_ms = (time.perf_counter() - start_time) * 1000
    _feature_extraction_latency.labels(symbol=tick.symbol).observe(feature_latency_ms)
    
    # === EXPORT FEATURE VECTOR ===
    _feature_raw_return.labels(symbol=tick.symbol).set(features.raw_return)
    _feature_rolling_vol.labels(symbol=tick.symbol).set(features.rolling_vol)
    _feature_spread_divergence.labels(symbol=tick.symbol).set(features.spread_z)
    _feature_latency_anomaly.labels(symbol=tick.symbol).set(features.latency_z)
    _feature_volume_anomaly.labels(symbol=tick.symbol).set(features.volume_z)
    _feature_trust_degradation.labels(symbol=tick.symbol).set(features.trust_delta)
    
    # === MODEL INFERENCE TIMING ===
    start_if = time.perf_counter()
    if_score = self.engine.isolation_forest_score(features)
    _model_inference_latency.labels(model="isolation_forest").observe((time.perf_counter() - start_if) * 1000)
    
    start_hst = time.perf_counter()
    hst_score = self.engine.half_space_trees_score(features)
    _model_inference_latency.labels(model="half_space_trees").observe((time.perf_counter() - start_hst) * 1000)
    
    start_hmm = time.perf_counter()
    regime = self.engine.hmm_regime(features)
    _model_inference_latency.labels(model="hmm").observe((time.perf_counter() - start_hmm) * 1000)
    
    # === EXPORT ANOMALY SUBCOMPONENTS ===
    _anomaly_if_score.labels(symbol=tick.symbol).set(if_score)
    _anomaly_hst_score.labels(symbol=tick.symbol).set(hst_score)
    _anomaly_mad_triggered.labels(symbol=tick.symbol).set(1.0 if mad_active else 0.0)
    
    fused_score = self.engine.fuse_anomaly_scores(if_score, hst_score, mad_active)
    _anomaly_fused_score.labels(symbol=tick.symbol).set(fused_score)
    _anomaly_score_histogram.labels(symbol=tick.symbol).observe(fused_score)
    
    # === HMM REGIME TRACKING ===
    previous_regime = self._last_regime.get(tick.symbol)
    if previous_regime is not None and regime.regime != previous_regime:
        _hmm_regime_transitions.labels(
            symbol=tick.symbol,
            from_regime=str(previous_regime),
            to_regime=str(regime.regime)
        ).inc()
    self._last_regime[tick.symbol] = regime.regime
    
    _hmm_regime_state.labels(symbol=tick.symbol).set(regime.regime)
    for i, prob in enumerate(regime.posterior):
        _hmm_regime_posterior.labels(symbol=tick.symbol, regime=str(i)).set(prob)
    
    # === DECISION GATE STATE TRANSITIONS ===
    new_state = self.gate.evaluate(trust_score, fused_score, mad_active)
    previous_state = self._last_gate_state.get(tick.symbol)
    if previous_state and new_state != previous_state:
        _decision_gate_transitions.labels(from_state=previous_state, to_state=new_state).inc()
    self._last_gate_state[tick.symbol] = new_state
```

---

## PART 3: LAYER-SPECIFIC TELEMETRY

### Layer 1 Ingestion Metrics

```python
# services/layer1_ingestion/adapters/base.py

_websocket_reconnects = Counter(
    "exchange_websocket_reconnects_total",
    "WebSocket reconnection count",
    ["exchange_id", "reason"]  # reason = timeout|tls_fail|heartbeat|error
)

_websocket_connection_duration = Histogram(
    "exchange_websocket_connection_duration_seconds",
    "WebSocket connection duration before disconnect",
    ["exchange_id"],
    buckets=[1, 5, 10, 30, 60, 300, 600, 1800, 3600]
)

_tick_rejection_reasons = Counter(
    "tick_rejection_total",
    "Tick rejections by reason",
    ["exchange_id", "reason"]  # reason = malformed|stale|duplicate|invalid_price
)

_exchange_health_status = Gauge(
    "exchange_connection_health",
    "Exchange connection health (1=healthy, 0=unhealthy)",
    ["exchange_id"]
)
```

### Layer 3 Strategy Metrics

```python
# services/layer3_strategy/service.py

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
```

### Layer 4 Risk Metrics

```python
# services/layer4_risk/engine.py

_trade_rejections = Counter(
    "risk_trade_rejections_total",
    "Trade rejections by reason",
    ["reason"]  # reason = exposure_limit|drawdown_limit|circuit_breaker|consecutive_losses
)

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

_circuit_breaker_state = Gauge(
    "risk_circuit_breaker_active",
    "Circuit breaker state (1=active, 0=inactive)",
    []
)

_consecutive_losses = Gauge(
    "risk_consecutive_loss_count",
    "Current consecutive loss counter",
    []
)
```

### Layer 5 Execution Metrics

```python
# services/layer5_execution/engine.py

_order_placement_latency = Histogram(
    "execution_order_placement_latency_ms",
    "Order placement latency to exchange",
    ["exchange_id"],
    buckets=[1, 5, 10, 20, 50, 100, 200, 500, 1000]
)

_order_retry_count = Counter(
    "execution_order_retries_total",
    "Order retry attempts",
    ["exchange_id", "reason"]  # reason = timeout|rate_limit|rejected
)

_idempotency_dedup_hits = Counter(
    "execution_idempotency_dedup_hits_total",
    "Idempotency deduplication hits (prevented duplicate orders)",
    ["exchange_id"]
)

_order_failures = Counter(
    "execution_order_failures_total",
    "Failed orders by reason",
    ["exchange_id", "reason"]  # reason = insufficient_balance|invalid_price|rejected
)

_slippage_bps = Histogram(
    "execution_slippage_bps",
    "Execution slippage in basis points",
    ["symbol", "direction"],
    buckets=[-100, -50, -20, -10, -5, 0, 5, 10, 20, 50, 100]
)
```

### Layer 6 Audit Metrics

```python
# services/layer6_audit/logger.py

_audit_log_write_latency = Histogram(
    "audit_log_write_latency_ms",
    "Audit log write latency",
    [],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 50]
)

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

---

## PART 4: KAFKA & PIPELINE OBSERVABILITY

### Kafka Consumer Lag Metrics

```python
# shared/kafka_monitoring.py

_kafka_consumer_lag = Gauge(
    "kafka_consumer_lag_messages",
    "Consumer lag in messages",
    ["consumer_group", "topic", "partition"]
)

_kafka_consumer_lag_seconds = Gauge(
    "kafka_consumer_lag_seconds",
    "Consumer lag in seconds (time-based)",
    ["consumer_group", "topic"]
)

_kafka_rebalance_total = Counter(
    "kafka_consumer_rebalances_total",
    "Consumer group rebalance events",
    ["consumer_group"]
)
```

### Pipeline Bottleneck Detection

```python
_pipeline_stage_latency = Histogram(
    "pipeline_stage_latency_ms",
    "End-to-end latency per pipeline stage",
    ["stage"],  # stage = ingestion|validation|scoring|strategy|risk|execution
    buckets=[1, 5, 10, 20, 50, 100, 200, 500, 1000, 2000]
)

_pipeline_backpressure = Gauge(
    "pipeline_backpressure_ratio",
    "Backpressure ratio (queue_depth / queue_capacity)",
    ["stage"]
)
```

---

## METRIC NAMING CONVENTIONS

### Taxonomy Structure

```
<layer>_<component>_<metric_type>_<unit>

Examples:
- trust_subscore_t1_tls              # Layer 1 trust subscore
- anomaly_subscore_if                # Layer 2 anomaly subscore  
- strategy_indicator_rsi             # Layer 3 indicator
- risk_trade_rejections_total        # Layer 4 counter
- execution_order_placement_latency_ms  # Layer 5 histogram
- audit_log_write_latency_ms         # Layer 6 histogram
```

### Metric Type Suffixes

- `_total` - Counter (monotonically increasing)
- `_duration_ms` / `_latency_ms` - Histogram (timing)
- `_percent` / `_pct` - Gauge (percentage 0-100)
- `_ratio` - Gauge (ratio 0-1)
- `_count` - Gauge (current count)
- `_distribution` - Histogram (value distribution)

### Label Guidelines

- **Keep cardinality low** (<100 unique values per label)
- **Use consistent label names**: `symbol`, `exchange_id`, `direction`, `reason`
- **Avoid high-cardinality labels**: No UUIDs, timestamps, or user IDs
- **Use enums for categorical data**: `direction=LONG|SHORT|HOLD`

---

## ALERT RULES

### Critical Alerts (PagerDuty)

```yaml
# Trust score sudden drop
- alert: TrustScoreSuddenDrop
  expr: |
    (trust_subscore_t1_tls < 0.5) or
    (trust_subscore_t2_consensus < 0.5) or
    (trust_subscore_t3_freshness < 0.3)
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Trust score component critically low"
    description: "{{ $labels.symbol }}: T1={{ $value }}"

# Anomaly spike
- alert: AnomalyScoreSpike
  expr: anomaly_fused_score > 0.9
  for: 30s
  labels:
    severity: critical
  annotations:
    summary: "Anomaly score spike detected"

# Decision gate degraded
- alert: DecisionGateDegraded
  expr: layer2_system_state >= 2
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "System in DEGRADED or HALT state"
```

### Warning Alerts (Slack)

```yaml
- alert: HighConsumerLag
  expr: kafka_consumer_lag_seconds > 30
  for: 5m
  labels:
    severity: warning

- alert: ExchangeReconnecting
  expr: rate(exchange_websocket_reconnects_total[5m]) > 0.1
  for: 2m
  labels:
    severity: warning

- alert: HighOrderRejectionRate
  expr: rate(risk_trade_rejections_total[5m]) > 0.5
  for: 5m
  labels:
    severity: warning
```

---

**Next**: I'll create the Grafana dashboard JSON panels in the next document.

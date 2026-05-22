# Production-Grade Observability Architecture

## Overview

This document describes the complete observability stack for the distributed secure algorithmic trading platform. The system provides real-time monitoring, anomaly investigation, security monitoring, and operational command center capabilities.

## Architecture Layers

### Data Collection Layer
- **Prometheus**: Time-series metrics database with 5s scrape interval
- **cAdvisor**: Container resource metrics (CPU, memory, network, disk)
- **Kafka Exporter**: Kafka broker, topic, and consumer group metrics
- **Node Exporter**: Host-level system metrics
- **Application Metrics**: Custom Python instrumentation using prometheus_client

### Visualization Layer
- **Grafana**: Primary visualization and alerting platform
- **5 Core Dashboards**: Executive, Layer 1, Layer 2, Strategy+Risk, Infrastructure+Audit
- **Advanced Panels**: Event flow tracing, node graphs, state timelines

### Alert Layer
- **Prometheus Alertmanager**: Alert routing and deduplication
- **Grafana Alerts**: Dashboard-based alerting with notification channels

## System Components

### Layer 1 — Trusted Data Ingestion
**Services**: layer1-ingestion (9101), layer1-validated (9102)

**Key Metrics**:
- `trust_score`: Overall trust score [0,1]
- `trust_t1_tls`: TLS pinning subscore
- `trust_t2_consensus`: Multi-exchange consensus subscore
- `trust_t3_latency`: Latency anomaly subscore
- `trust_t4_sequence`: Sequence integrity subscore
- `trust_t5_hash`: Hash chain continuity subscore
- `websocket_latency_ms`: Exchange websocket latency
- `consensus_divergence`: Price divergence across exchanges
- `sequence_gaps_total`: Sequence integrity violations
- `replay_suspicion_total`: Replay attack detection counter
- `tls_pinning_failures_total`: TLS certificate validation failures
- `quarantined_ticks_total`: Ticks rejected by trust engine

### Layer 2 — Market Anomaly Detection
**Service**: layer2-anomaly (9103)

**Key Metrics**:
- `anomaly_subscore_if`: Isolation Forest score [0,1]
- `anomaly_subscore_hst`: Half-Space Trees score [0,1]
- `anomaly_fused_score`: Final fused anomaly score [0,1]
- `anomaly_mad_guard_active`: MAD guard activation (0/1)
- `hmm_regime_state`: Current regime (0=low, 1=normal, 2=high)
- `hmm_regime_posterior_prob`: Posterior probabilities per regime
- `hmm_regime_transitions_total`: Regime transition counter
- `anomaly_feature_*`: Feature vector components (6 features)
- `decision_gate_state_transitions_total`: State transition counter
- `layer2_system_state`: System state (0=NORMAL, 1=CONSERVATIVE, 2=DEGRADED, 3=HALT)

### Layer 3 — Trading Strategy Engine
**Service**: layer3-strategy (9104)

**Key Metrics**:
- `strategy_signal_direction_total`: Signal counts by direction (LONG/SHORT/HOLD)
- `strategy_signal_strength_distribution`: Signal strength histogram
- `strategy_indicator_rsi`: RSI indicator values
- `strategy_indicator_macd_histogram`: MACD histogram values
- `strategy_indicator_bollinger_width`: Bollinger Band width (normalized)
- `strategy_ema_crossover_events_total`: EMA crossover events
- `layer3_last_ofi`: Order Flow Imbalance
- `layer3_signals_out_total`: Total signals emitted

### Layer 4 — Risk Management
**Service**: layer4-risk (9105)

**Key Metrics**:
- `risk_rejections_total`: Risk rejection counter by reason
- `risk_circuit_breaker_state`: Circuit breaker state (0=CLOSED, 1=OPEN)
- `risk_position_size_pct`: Current position sizing
- `risk_exposure_usd`: Total exposure in USD
- `risk_drawdown_pct`: Current drawdown percentage
- `risk_pnl_usd`: Profit and Loss in USD
- `risk_open_positions`: Number of open positions

### Layer 5 — Execution Engine
**Service**: layer5-execution (9106)

**Key Metrics**:
- `execution_orders_placed_total`: Orders placed by exchange
- `execution_retries_total`: Retry counter by reason
- `execution_idempotency_hits_total`: Duplicate prevention hits
- `execution_latency_ms`: Order execution latency
- `execution_fill_rate`: Order fill rate percentage

### Layer 6 — Tamper-Evident Audit Logging
**Service**: layer6-audit (9107)

**Key Metrics**:
- `audit_chain_valid`: Audit chain integrity (0/1)
- `audit_verification_errors_total`: Hash verification failures
- `audit_events_total`: Total audit events by type
- `audit_chain_length`: Current chain length

### Infrastructure Metrics

**Kafka**:
- `kafka_consumer_lag`: Consumer lag by topic/partition
- `kafka_topic_partition_current_offset`: Current offset
- `kafka_topic_partition_replicas`: Replica count
- `kafka_brokers`: Active broker count

**Containers (cAdvisor)**:
- `container_cpu_usage_seconds_total`: CPU usage
- `container_memory_usage_bytes`: Memory usage
- `container_network_receive_bytes_total`: Network RX
- `container_network_transmit_bytes_total`: Network TX
- `container_fs_usage_bytes`: Filesystem usage

**System (Node Exporter)**:
- `node_cpu_seconds_total`: CPU time
- `node_memory_MemAvailable_bytes`: Available memory
- `node_disk_io_time_seconds_total`: Disk I/O time
- `node_network_receive_bytes_total`: Network RX

## Dashboard Architecture

### Dashboard 1: Executive Overview
**Purpose**: Global real-time system overview and operational command center

**Panels**:
1. **Global System State** - Current state with color coding
2. **Layer Status Grid** - Health status for all 6 layers
3. **Kafka Broker Health** - Broker availability
4. **Exchange Connectivity** - Websocket connection status
5. **System Node Graph** - End-to-end pipeline visualization with latency/throughput
6. **Trust Score Timeline** - Historical trust score trends
7. **Anomaly Score Timeline** - Historical anomaly trends
8. **Regime State Timeline** - HMM regime transitions
9. **Current Positions** - Open positions table
10. **PnL Gauge** - Real-time profit/loss
11. **Drawdown Gauge** - Current drawdown
12. **Exposure Gauge** - Total exposure
13. **Risk State Indicator** - Current risk management state

### Dashboard 2: Layer 1 Trust Engine
**Purpose**: Deep dive into trust scoring and data validation

**Panels**:
1. **Exchange Websocket Latency Heatmap** - Latency by exchange over time
2. **Consensus Divergence Chart** - Price divergence across exchanges
3. **Trust Score Decomposition** - T1-T5 subscores stacked area
4. **Sequence Gap Violations** - Sequence integrity timeline
5. **Replay Attack Suspicion** - Replay detection counter
6. **TLS Pinning Alerts** - Certificate validation failures
7. **Quarantined Tick Table** - Recent rejected ticks
8. **Consensus Mid-Price** - Multi-exchange price consensus
9. **Trust Score Distribution** - Histogram of trust scores
10. **Hash Chain Integrity** - T5 hash continuity monitoring

### Dashboard 3: Layer 2 Anomaly Detection
**Purpose**: Anomaly detection model observability and regime tracking

**Panels**:
1. **Isolation Forest Score** - IF subscore timeline
2. **HST Score** - Half-Space Trees subscore timeline
3. **Final Anomaly Fusion Score** - Fused anomaly score
4. **MAD Guard Activation** - MAD guard trigger events
5. **Regime Posterior Probabilities** - P(low), P(medium), P(high) stacked area
6. **Feature Vector Monitoring** - 6 feature components (f1-f6)
7. **State Transition Timeline** - NORMAL/CONSERVATIVE/DEGRADED/HALT
8. **Model Inference Latency** - Scoring performance histogram
9. **Anomaly Score Distribution** - Score histogram by symbol
10. **Decision Gate Triggers** - Trigger reason breakdown

### Dashboard 4: Strategy + Risk
**Purpose**: Trading signal generation and risk management monitoring

**Panels**:
1. **Signal Direction Breakdown** - LONG/SHORT/HOLD/CLOSE_ALL counts
2. **RSI Chart** - RSI indicator by timeframe
3. **MACD Chart** - MACD histogram visualization
4. **Bollinger Bands** - BB width and price position
5. **EMA Crossover Visualization** - EMA cross events
6. **Position Sizing Gauge** - Current position size percentage
7. **Risk Rejection Table** - Recent risk rejections with reasons
8. **Circuit Breaker State Timeline** - Circuit breaker activations
9. **Open Positions Table** - Current positions with SL/TP
10. **Signal Strength Distribution** - Signal strength histogram
11. **Order Flow Imbalance** - OFI timeline

### Dashboard 5: Infrastructure + Audit
**Purpose**: Infrastructure health and audit integrity monitoring

**Panels**:
1. **Kafka Consumer Lag** - Lag by topic/consumer group
2. **Kafka Topic Throughput** - Messages/sec by topic
3. **Service CPU Usage** - CPU by container
4. **Service Memory Usage** - Memory by container
5. **Container Restart Counts** - Restart events
6. **API Retry Metrics** - Retry counts by reason
7. **Idempotency Duplicate Prevention** - Duplicate detection hits
8. **Audit Chain Integrity Status** - Chain validation state
9. **Hash Verification Failure Counter** - Verification errors
10. **Event Throughput Per Layer** - Messages/sec by layer

### Critical Panel: Full Event Flow Tracer
**Purpose**: Trace a single event through the entire pipeline

**Implementation**: Logs panel with correlated trace IDs showing:
```
RAW TICK (t0) → 
TRUST SCORE (t1, Δ=5ms) → 
ANOMALY SCORE (t2, Δ=3ms) → 
SYSTEM STATE (t2, state=NORMAL) → 
SIGNAL (t3, Δ=8ms, direction=LONG) → 
RISK CHECK (t4, Δ=2ms, approved=true) → 
ORDER (t5, Δ=15ms, status=FILLED) → 
AUDIT ENTRY (t6, Δ=1ms, hash=abc123)
```

## Alert Rules

### Critical Alerts (P1)
- **HALT State Activation**: System enters HALT state
- **Audit Chain Break**: Hash verification failure detected
- **Kafka Broker Down**: Kafka broker unavailable
- **Layer Service Down**: Any layer service unhealthy
- **Replay Attack Suspicion**: Replay attack counter incremented

### High Priority Alerts (P2)
- **Trust Score Below Threshold**: Trust score < 0.6 for 1 minute
- **Anomaly Score Spike**: Anomaly score > 0.8 for 30 seconds
- **Consensus Divergence Spike**: Price divergence > 1% across exchanges
- **High Kafka Lag**: Consumer lag > 1000 messages
- **Websocket Disconnect**: Exchange websocket disconnected

### Medium Priority Alerts (P3)
- **High Retry Count**: Execution retries > 10 in 5 minutes
- **Circuit Breaker Open**: Risk circuit breaker activated
- **Container High CPU**: Container CPU > 80% for 5 minutes
- **Container High Memory**: Container memory > 80% for 5 minutes

## Metrics Naming Convention

### Prefix Standards
- `trust_*`: Layer 1 trust scoring metrics
- `anomaly_*`: Layer 2 anomaly detection metrics
- `strategy_*`: Layer 3 trading strategy metrics
- `risk_*`: Layer 4 risk management metrics
- `execution_*`: Layer 5 execution metrics
- `audit_*`: Layer 6 audit logging metrics
- `kafka_*`: Kafka infrastructure metrics
- `container_*`: Container resource metrics
- `node_*`: System-level metrics

### Metric Types
- **Counter**: Monotonically increasing values (e.g., `*_total`)
- **Gauge**: Point-in-time values (e.g., `*_score`, `*_state`)
- **Histogram**: Distribution of values (e.g., `*_duration_ms`, `*_distribution`)

### Label Standards
- `symbol`: Trading symbol (e.g., BTC-USDT)
- `exchange`: Exchange name (e.g., binance, coinbase)
- `layer`: Layer identifier (e.g., layer1, layer2)
- `direction`: Signal direction (e.g., LONG, SHORT, HOLD)
- `reason`: Rejection/failure reason
- `state`: State identifier (e.g., NORMAL, HALT)

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Grafana (Port 3000)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │Executive │ │ Layer 1  │ │ Layer 2  │ │Strategy+ │       │
│  │ Overview │ │  Trust   │ │ Anomaly  │ │   Risk   │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ┌──────────────────────────────────────────────────┐       │
│  │      Infrastructure + Audit Dashboard            │       │
│  └──────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ HTTP :9090
┌─────────────────────────────────────────────────────────────┐
│                   Prometheus (Port 9090)                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Scrape Targets (5s interval):                       │   │
│  │  • Layer 1-6 Services (9101-9107)                    │   │
│  │  • Kafka Exporter (9308)                             │   │
│  │  • cAdvisor (8080)                                   │   │
│  │  • Node Exporter (9100)                              │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ /metrics endpoints
┌─────────────────────────────────────────────────────────────┐
│                  Application Services                        │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐    │
│  │Layer1│ │Layer2│ │Layer3│ │Layer4│ │Layer5│ │Layer6│    │
│  │ 9101 │ │ 9103 │ │ 9104 │ │ 9105 │ │ 9106 │ │ 9107 │    │
│  │ 9102 │ │      │ │      │ │      │ │      │ │      │    │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘    │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ Kafka Topics
┌─────────────────────────────────────────────────────────────┐
│                    Kafka + Zookeeper                         │
│  Topics: raw → validated → scored → signals → approved      │
│          → executed → audit                                  │
└─────────────────────────────────────────────────────────────┘
```

## Best Practices

### Metrics Instrumentation
1. **Use Prometheus client library**: Consistent instrumentation across all services
2. **Expose /metrics endpoint**: Standard HTTP endpoint on each service port
3. **Use appropriate metric types**: Counter for cumulative, Gauge for snapshots, Histogram for distributions
4. **Add meaningful labels**: Enable filtering and aggregation
5. **Avoid high cardinality**: Limit unique label combinations

### Dashboard Design
1. **Top-down approach**: Start with executive overview, drill down to details
2. **Color coding**: Use consistent colors for states (green=good, yellow=warning, red=critical)
3. **Time synchronization**: Link time ranges across panels
4. **Template variables**: Use variables for symbol, exchange, layer selection
5. **Panel descriptions**: Add context and PromQL explanations

### Alert Configuration
1. **Severity levels**: P1 (critical), P2 (high), P3 (medium)
2. **Avoid alert fatigue**: Set appropriate thresholds and durations
3. **Actionable alerts**: Include context and remediation steps
4. **Alert routing**: Route by severity and team
5. **Silence during maintenance**: Use Grafana silence feature

### Performance Optimization
1. **Scrape interval**: 5s for real-time, 15s for infrastructure
2. **Retention**: 15 days for Prometheus, longer for long-term storage
3. **Query optimization**: Use recording rules for expensive queries
4. **Dashboard refresh**: 5s for operational, 30s for analytical
5. **Panel query limits**: Limit time range for heavy queries

## Security Considerations

1. **Grafana Authentication**: Enable authentication, disable anonymous access
2. **Prometheus Security**: Restrict access to Prometheus UI
3. **Metrics Sanitization**: Avoid exposing sensitive data in metrics
4. **Network Isolation**: Use Docker network for internal communication
5. **TLS Encryption**: Enable TLS for production deployments

## Maintenance and Operations

### Daily Operations
- Monitor executive dashboard for system health
- Review alert notifications
- Check Kafka consumer lag
- Verify audit chain integrity

### Weekly Operations
- Review anomaly detection patterns
- Analyze trading signal performance
- Check infrastructure resource usage
- Review and tune alert thresholds

### Monthly Operations
- Analyze long-term trends
- Optimize dashboard queries
- Review and update documentation
- Capacity planning based on metrics

## Troubleshooting Guide

### High Anomaly Scores
1. Check Layer 2 feature vector metrics
2. Review HMM regime state transitions
3. Verify trust score is healthy
4. Check for market volatility events

### System State HALT
1. Check decision gate trigger reasons
2. Review trust score decomposition
3. Verify exchange connectivity
4. Check for Kafka lag or service failures

### High Kafka Lag
1. Check consumer group status
2. Verify service health and CPU/memory
3. Review message throughput
4. Check for processing bottlenecks

### Missing Metrics
1. Verify service /metrics endpoint is accessible
2. Check Prometheus scrape targets
3. Review Prometheus logs for errors
4. Verify service is running and healthy

## Future Enhancements

1. **Distributed Tracing**: Add OpenTelemetry for request tracing
2. **Log Aggregation**: Integrate with ELK or Loki for log analysis
3. **Machine Learning**: Anomaly detection on metrics themselves
4. **Capacity Forecasting**: Predictive scaling based on trends
5. **Custom Exporters**: Additional infrastructure metrics
6. **Multi-Region**: Cross-region monitoring and failover
7. **SLA Tracking**: Service level objective monitoring
8. **Cost Tracking**: Resource cost attribution by layer

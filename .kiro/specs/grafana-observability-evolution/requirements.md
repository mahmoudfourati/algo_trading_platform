# Requirements Document

## Introduction

This document specifies the requirements for evolving the existing Grafana dashboard into a production-grade HFT/SIEM-level observability interface for the algorithmic trading platform. The evolution preserves the existing dark theme and clean layout while adding deep forensic visibility into trust score decomposition, anomaly score decomposition, layer-specific telemetry, and advanced observability features.

The platform operates a 6-layer algorithmic trading pipeline (Ingestion → Validation → Anomaly → Strategy → Risk → Execution → Audit) with Prometheus metrics backend. Many metrics already exist from Phase 1-2 (trust/anomaly decomposition) and Phase 3 Layer 1 (ingestion telemetry), with Phase 3 Layers 3-6 metrics planned but not yet implemented.

This specification focuses on creating concrete Grafana panel JSON configurations, PromQL query patterns, alert rules, and SRE debugging workflows to enable forensic-level observability for production operations.

## Glossary

- **Trust_Score**: A composite score [0,1] representing data feed trustworthiness, computed from 5 subcomponents (T1-T5) plus availability
- **T1_TLS**: Trust subscore for TLS certificate validity and SPKI pinning verification
- **T2_Consensus**: Trust subscore for multi-exchange price consensus agreement
- **T3_Freshness**: Trust subscore for data latency and freshness
- **T4_Sequence**: Trust subscore for sequence number integrity and gap detection
- **T5_HashChain**: Trust subscore for hash chain continuity verification
- **T_Availability**: Trust subscore for exchange availability and connectivity
- **Anomaly_Score**: A composite score [0,1] representing market anomaly severity, fused from Isolation Forest and Half-Space Trees
- **IF_Score**: Isolation Forest anomaly detection subscore
- **HST_Score**: Half-Space Trees anomaly detection subscore
- **MAD_Guard**: Median Absolute Deviation guard that triggers on extreme statistical outliers
- **HMM_Regime**: Hidden Markov Model regime classifier output (0=low_vol, 1=normal, 2=high_vol)
- **Feature_Vector**: 6-dimensional input to anomaly models (raw return, rolling volatility, spread divergence, latency anomaly, volume anomaly, trust degradation)
- **Decision_Gate**: State machine with states NORMAL, CONSERVATIVE, DEGRADED, HALT based on trust and anomaly scores
- **Grafana_Panel**: A visualization component in Grafana dashboard with specific panel type, queries, and configuration
- **PromQL**: Prometheus Query Language for querying time-series metrics
- **Panel_Type**: Grafana visualization type (timeseries, stat, state-timeline, heatmap, barchart, gauge)
- **Alert_Rule**: Prometheus alerting rule with expression, duration, severity, and annotations
- **Forensic_Visibility**: Ability to trace root cause of system behavior through detailed metric decomposition
- **Layer_Telemetry**: Metrics specific to one of the 6 pipeline layers
- **Kafka_Consumer_Lag**: Delay between message production and consumption in Kafka topics
- **Correlation_ID**: Unique identifier propagated through pipeline stages for distributed tracing
- **Slippage**: Difference between expected and actual execution price in basis points
- **Circuit_Breaker**: Risk management state machine (NORMAL, REDUCED, HALTED)
- **Consensus_Divergence**: Price difference between exchanges measured in basis points
- **Sequence_Gap**: Missing sequence numbers indicating dropped messages
- **Regime_Transition**: Change in HMM regime state indicating market condition shift

## Requirements

### Requirement 1: Trust Score Decomposition Panel

**User Story:** As an SRE operator, I want a Grafana panel showing all trust score subcomponents (T1-T5, T_availability) and the final trust score on the same graph, so that I can immediately identify which component caused a trust degradation event.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display all 6 trust subcomponents (T1_TLS, T2_Consensus, T3_Freshness, T4_Sequence, T5_HashChain, T_Availability) as separate time series
2. THE Grafana_Panel SHALL display the final trust score as a distinct time series with visual emphasis (thicker line or different color)
3. THE Grafana_Panel SHALL use panel type "timeseries" with Y-axis range [0, 1]
4. THE Grafana_Panel SHALL include PromQL queries for each subscore metric: trust_subscore_t1_tls, trust_subscore_t2_consensus, trust_subscore_t3_freshness, trust_subscore_t4_sequence, trust_subscore_t5_hashchain, trust_subscore_t_availability
5. THE Grafana_Panel SHALL include PromQL query for final trust score: layer1_validated_last_trust_score
6. THE Grafana_Panel SHALL use legend format showing component names clearly (e.g., "T1 TLS", "T2 Consensus", "Final Trust")
7. THE Grafana_Panel SHALL include threshold lines at 0.5 (warning) and 0.3 (critical) for visual reference
8. THE Grafana_Panel SHALL display min, max, and current values for each series in the legend
9. THE Grafana_Panel SHALL support symbol filtering via dashboard variable
10. THE Grafana_Panel SHALL use color palette that highlights the final trust score distinctly from subcomponents

### Requirement 2: Trust Degradation Events Panel

**User Story:** As an SRE operator, I want a Grafana panel showing trust degradation events grouped by root cause, so that I can quickly identify patterns in trust failures.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display trust degradation event counts using panel type "barchart"
2. THE Grafana_Panel SHALL use PromQL query: increase(trust_degradation_events_total[1h]) to show events in the last hour
3. THE Grafana_Panel SHALL group events by symbol and primary_cause labels
4. THE Grafana_Panel SHALL use legend format showing both symbol and cause (e.g., "BTC-USDT - t1", "ETH-USDT - t2")
5. THE Grafana_Panel SHALL sort bars by count descending to highlight most frequent causes
6. THE Grafana_Panel SHALL use color coding to distinguish different primary causes (t1=red, t2=orange, t3=yellow, t4=blue, t5=purple, availability=gray)
7. THE Grafana_Panel SHALL display zero values when no degradation events occurred

### Requirement 3: Consensus Divergence Panel

**User Story:** As an SRE operator, I want a Grafana panel showing consensus divergence magnitude and divergent source count, so that I can detect price manipulation attempts or exchange data quality issues.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display consensus divergence using panel type "timeseries" with dual Y-axes
2. THE Grafana_Panel SHALL use PromQL query: consensus_divergent_source_count for left Y-axis showing count of divergent exchanges
3. THE Grafana_Panel SHALL use PromQL query: consensus_divergence_max_bps for right Y-axis showing maximum divergence in basis points
4. THE Grafana_Panel SHALL label left Y-axis as "Divergent Sources (count)" and right Y-axis as "Max Divergence (bps)"
5. THE Grafana_Panel SHALL use different line styles (solid vs dashed) to distinguish the two metrics
6. THE Grafana_Panel SHALL include threshold line at 100 bps for visual reference
7. THE Grafana_Panel SHALL support symbol filtering via dashboard variable

### Requirement 4: Anomaly Score Decomposition Panel

**User Story:** As an SRE operator, I want a Grafana panel showing all anomaly score subcomponents (IF, HST, MAD guard, fused score), so that I can understand which detection model triggered an anomaly alert.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display anomaly subcomponents using panel type "timeseries"
2. THE Grafana_Panel SHALL use PromQL queries: anomaly_subscore_if, anomaly_subscore_hst, anomaly_fused_score, anomaly_mad_guard_active
3. THE Grafana_Panel SHALL use Y-axis range [0, 1] for scores and [0, 1] for MAD guard state
4. THE Grafana_Panel SHALL use legend format: "Isolation Forest", "Half-Space Trees", "Fused Score", "MAD Guard"
5. THE Grafana_Panel SHALL visually emphasize the fused score (thicker line)
6. THE Grafana_Panel SHALL display MAD guard as a step function (0 or 1)
7. THE Grafana_Panel SHALL include threshold lines at 0.7 (warning) and 0.9 (critical)
8. THE Grafana_Panel SHALL support symbol filtering via dashboard variable

### Requirement 5: HMM Regime State Timeline Panel

**User Story:** As an SRE operator, I want a Grafana panel showing HMM regime transitions over time, so that I can correlate market regime changes with anomaly spikes and trading decisions.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display HMM regime state using panel type "state-timeline"
2. THE Grafana_Panel SHALL use PromQL query: hmm_regime_state
3. THE Grafana_Panel SHALL map regime values to labels: 0="Low Vol", 1="Normal", 2="High Vol"
4. THE Grafana_Panel SHALL use color coding: Low Vol=green, Normal=blue, High Vol=red
5. THE Grafana_Panel SHALL display regime transitions as distinct state changes
6. THE Grafana_Panel SHALL support symbol filtering via dashboard variable
7. THE Grafana_Panel SHALL show regime duration in tooltip on hover

### Requirement 6: Anomaly Feature Vector Panel

**User Story:** As an SRE operator, I want a Grafana panel showing all 6 feature vector components used by anomaly models, so that I can understand what input signals drove an anomaly detection.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display feature vector components using panel type "timeseries"
2. THE Grafana_Panel SHALL use PromQL queries: anomaly_feature_raw_return, anomaly_feature_rolling_volatility, anomaly_feature_spread_divergence, anomaly_feature_latency_anomaly, anomaly_feature_volume_anomaly, anomaly_feature_trust_degradation
3. THE Grafana_Panel SHALL use legend format showing feature names: "Raw Return", "Rolling Vol", "Spread Div", "Latency Anom", "Volume Anom", "Trust Deg"
4. THE Grafana_Panel SHALL normalize Y-axis to show all features on comparable scale
5. THE Grafana_Panel SHALL support symbol filtering via dashboard variable
6. THE Grafana_Panel SHALL use color palette that distinguishes all 6 features clearly

### Requirement 7: Model Inference Latency Panel

**User Story:** As an SRE operator, I want a Grafana panel showing model inference latency for IF, HST, and HMM models, so that I can detect performance degradation in anomaly detection.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display model inference latency using panel type "timeseries"
2. THE Grafana_Panel SHALL use PromQL query: histogram_quantile(0.95, rate(anomaly_model_inference_duration_ms_bucket[5m])) for p95 latency
3. THE Grafana_Panel SHALL display separate series for each model: isolation_forest, half_space_trees, hmm
4. THE Grafana_Panel SHALL use Y-axis unit "ms" (milliseconds)
5. THE Grafana_Panel SHALL include threshold line at 10ms for visual reference
6. THE Grafana_Panel SHALL display current, min, max, and p95 values in legend

### Requirement 8: Layer 1 Exchange Health Status Panel

**User Story:** As an SRE operator, I want a Grafana panel showing connection health status for all exchanges, so that I can quickly identify connectivity issues.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display exchange health using panel type "stat"
2. THE Grafana_Panel SHALL use PromQL query: exchange_connection_health
3. THE Grafana_Panel SHALL display one stat per exchange with exchange_id label
4. THE Grafana_Panel SHALL map values to text: 1="Healthy", 0="Unhealthy"
5. THE Grafana_Panel SHALL use color coding: Healthy=green, Unhealthy=red
6. THE Grafana_Panel SHALL use "instant" query mode to show current state only
7. THE Grafana_Panel SHALL arrange stats horizontally for compact display

### Requirement 9: Layer 1 WebSocket Reconnect Rate Panel

**User Story:** As an SRE operator, I want a Grafana panel showing WebSocket reconnection rate by exchange and reason, so that I can diagnose connection stability issues.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display reconnect rate using panel type "timeseries"
2. THE Grafana_Panel SHALL use PromQL query: rate(exchange_websocket_reconnects_total[5m]) * 60 to show reconnects per minute
3. THE Grafana_Panel SHALL group by exchange_id and reason labels
4. THE Grafana_Panel SHALL use legend format: "{{exchange_id}} - {{reason}}"
5. THE Grafana_Panel SHALL use Y-axis unit "reconnects/min"
6. THE Grafana_Panel SHALL include threshold line at 1 reconnect/min for visual reference

### Requirement 10: Layer 1 Tick Rejection Rate Panel

**User Story:** As an SRE operator, I want a Grafana panel showing tick rejection rate by exchange and reason, so that I can identify data quality issues.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display tick rejection rate using panel type "timeseries"
2. THE Grafana_Panel SHALL use PromQL query: rate(tick_rejection_total[5m]) * 60 to show rejections per minute
3. THE Grafana_Panel SHALL group by exchange_id and reason labels
4. THE Grafana_Panel SHALL use legend format: "{{exchange_id}} - {{reason}}"
5. THE Grafana_Panel SHALL use Y-axis unit "rejections/min"
6. THE Grafana_Panel SHALL display zero values when no rejections occur

### Requirement 11: Layer 3 Technical Indicators Panel

**User Story:** As an SRE operator, I want a Grafana panel showing RSI, MACD histogram, and Bollinger Band width for both 5m and 1h timeframes, so that I can monitor strategy signal generation inputs.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display technical indicators using panel type "timeseries"
2. THE Grafana_Panel SHALL use PromQL queries: strategy_indicator_rsi, strategy_indicator_macd_histogram, strategy_indicator_bollinger_width
3. THE Grafana_Panel SHALL filter by timeframe label (5m and 1h)
4. THE Grafana_Panel SHALL use legend format: "{{indicator}} {{timeframe}}"
5. THE Grafana_Panel SHALL normalize Y-axis to show all indicators on comparable scale
6. THE Grafana_Panel SHALL support symbol filtering via dashboard variable

### Requirement 12: Layer 3 Signal Direction Distribution Panel

**User Story:** As an SRE operator, I want a Grafana panel showing the distribution of LONG, SHORT, and HOLD signals over time, so that I can detect strategy bias or signal generation failures.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display signal direction distribution using panel type "barchart"
2. THE Grafana_Panel SHALL use PromQL query: increase(strategy_signal_direction_total[1h])
3. THE Grafana_Panel SHALL group by direction label (LONG, SHORT, HOLD)
4. THE Grafana_Panel SHALL use color coding: LONG=green, SHORT=red, HOLD=gray
5. THE Grafana_Panel SHALL display percentage of total signals for each direction
6. THE Grafana_Panel SHALL support symbol filtering via dashboard variable

### Requirement 13: Layer 4 Risk Rejection Reasons Panel

**User Story:** As an SRE operator, I want a Grafana panel showing trade rejection counts by reason, so that I can understand why the risk engine is blocking trades.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display rejection reasons using panel type "barchart"
2. THE Grafana_Panel SHALL use PromQL query: increase(risk_trade_rejections_total[1h])
3. THE Grafana_Panel SHALL group by reason label dynamically (no hardcoded reasons)
4. THE Grafana_Panel SHALL sort bars by count descending
5. THE Grafana_Panel SHALL use legend format showing rejection reason clearly
6. THE Grafana_Panel SHALL display zero values when no rejections occur

### Requirement 14: Layer 4 Circuit Breaker State Panel

**User Story:** As an SRE operator, I want a Grafana panel showing circuit breaker state over time, so that I can monitor risk management state transitions.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display circuit breaker state using panel type "state-timeline"
2. THE Grafana_Panel SHALL use PromQL query: risk_circuit_breaker_active
3. THE Grafana_Panel SHALL map values to labels: 0="NORMAL", 1="REDUCED", 2="HALTED"
4. THE Grafana_Panel SHALL use color coding: NORMAL=green, REDUCED=yellow, HALTED=red
5. THE Grafana_Panel SHALL display state transitions as distinct changes
6. THE Grafana_Panel SHALL show state duration in tooltip on hover

### Requirement 15: Layer 4 Exposure and Drawdown Panel

**User Story:** As an SRE operator, I want a Grafana panel showing current portfolio exposure and drawdown percentages, so that I can monitor risk limits in real-time.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display exposure and drawdown using panel type "timeseries" with dual Y-axes
2. THE Grafana_Panel SHALL use PromQL queries: risk_current_exposure_percent, risk_current_drawdown_percent
3. THE Grafana_Panel SHALL label left Y-axis as "Exposure (%)" and right Y-axis as "Drawdown (%)"
4. THE Grafana_Panel SHALL include threshold lines at exposure limits (e.g., 80%) and drawdown limits (e.g., 10%)
5. THE Grafana_Panel SHALL use color coding: exposure=blue, drawdown=red
6. THE Grafana_Panel SHALL support symbol filtering for exposure metric

### Requirement 16: Layer 5 Order Placement Latency Panel

**User Story:** As an SRE operator, I want a Grafana panel showing order placement latency distribution by exchange, so that I can detect exchange API performance issues.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display order placement latency using panel type "timeseries"
2. THE Grafana_Panel SHALL use PromQL query: histogram_quantile(0.95, rate(execution_order_placement_latency_ms_bucket[5m])) for p95 latency
3. THE Grafana_Panel SHALL group by exchange_id label
4. THE Grafana_Panel SHALL use Y-axis unit "ms" (milliseconds)
5. THE Grafana_Panel SHALL include threshold line at 100ms for visual reference
6. THE Grafana_Panel SHALL display p50, p95, p99 latencies in legend

### Requirement 17: Layer 5 Order Retry and Failure Panel

**User Story:** As an SRE operator, I want a Grafana panel showing order retry counts and failure counts by reason, so that I can diagnose execution reliability issues.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display retry and failure counts using panel type "timeseries"
2. THE Grafana_Panel SHALL use PromQL queries: rate(execution_order_retries_total[5m]), rate(execution_order_failures_total[5m])
3. THE Grafana_Panel SHALL group by exchange_id and reason labels
4. THE Grafana_Panel SHALL use legend format: "{{exchange_id}} - {{reason}} (retry/failure)"
5. THE Grafana_Panel SHALL use Y-axis unit "ops/sec"
6. THE Grafana_Panel SHALL use color coding to distinguish retries (yellow) from failures (red)

### Requirement 18: Layer 5 Slippage Distribution Panel

**User Story:** As an SRE operator, I want a Grafana panel showing execution slippage distribution by symbol and direction, so that I can monitor execution quality.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display slippage distribution using panel type "heatmap"
2. THE Grafana_Panel SHALL use PromQL query: rate(execution_slippage_bps_bucket[5m])
3. THE Grafana_Panel SHALL group by symbol and direction labels
4. THE Grafana_Panel SHALL use X-axis for time, Y-axis for slippage buckets (bps)
5. THE Grafana_Panel SHALL use color gradient: green (negative slippage/favorable) to red (positive slippage/unfavorable)
6. THE Grafana_Panel SHALL display slippage range from -100 bps to +100 bps

### Requirement 19: Layer 6 Audit Log Write Latency Panel

**User Story:** As an SRE operator, I want a Grafana panel showing audit log write latency, so that I can detect audit system performance degradation.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display audit log write latency using panel type "timeseries"
2. THE Grafana_Panel SHALL use PromQL query: histogram_quantile(0.95, rate(audit_log_write_latency_ms_bucket[5m])) for p95 latency
3. THE Grafana_Panel SHALL use Y-axis unit "ms" (milliseconds)
4. THE Grafana_Panel SHALL include threshold line at 10ms for visual reference
5. THE Grafana_Panel SHALL display p50, p95, p99 latencies in legend

### Requirement 20: Layer 6 Hash Chain Integrity Panel

**User Story:** As an SRE operator, I want a Grafana panel showing hash verification failures and chain continuity breaks, so that I can detect audit log tampering or corruption.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display hash integrity metrics using panel type "stat"
2. THE Grafana_Panel SHALL use PromQL queries: increase(audit_hash_verification_failures_total[24h]), increase(audit_chain_continuity_breaks_total[24h])
3. THE Grafana_Panel SHALL display two stats: "Hash Failures (24h)" and "Chain Breaks (24h)"
4. THE Grafana_Panel SHALL use color coding: 0=green, >0=red
5. THE Grafana_Panel SHALL use "instant" query mode to show current count

### Requirement 21: Kafka Consumer Lag Panel

**User Story:** As an SRE operator, I want a Grafana panel showing Kafka consumer lag in seconds by topic and consumer group, so that I can detect pipeline bottlenecks.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display consumer lag using panel type "timeseries"
2. THE Grafana_Panel SHALL use PromQL query: kafka_consumer_lag_seconds
3. THE Grafana_Panel SHALL group by consumer_group and topic labels
4. THE Grafana_Panel SHALL use legend format: "{{consumer_group}} - {{topic}}"
5. THE Grafana_Panel SHALL use Y-axis unit "seconds"
6. THE Grafana_Panel SHALL include threshold lines at 10s (warning) and 30s (critical)

### Requirement 22: Pipeline Stage Latency Panel

**User Story:** As an SRE operator, I want a Grafana panel showing end-to-end latency for each pipeline stage, so that I can identify bottlenecks in the processing pipeline.

#### Acceptance Criteria

1. THE Grafana_Panel SHALL display pipeline stage latency using panel type "timeseries"
2. THE Grafana_Panel SHALL use PromQL query: histogram_quantile(0.95, rate(pipeline_stage_latency_ms_bucket[5m]))
3. THE Grafana_Panel SHALL group by stage label (ingestion, validation, scoring, strategy, risk, execution)
4. THE Grafana_Panel SHALL use Y-axis unit "ms" (milliseconds)
5. THE Grafana_Panel SHALL display p95 latency for each stage
6. THE Grafana_Panel SHALL use stacked area chart to show cumulative latency

### Requirement 23: Critical Alert Rules

**User Story:** As an SRE operator, I want Prometheus alert rules for critical conditions (TLS failures, trust score drops, anomaly spikes, system halt), so that I receive immediate notifications for production incidents.

#### Acceptance Criteria

1. THE Alert_Rule SHALL trigger when rate(tls_verification_failures_total[5m]) > 0 for 1 minute with severity "critical"
2. THE Alert_Rule SHALL trigger when layer1_validated_last_trust_score < 0.5 for 2 minutes with severity "critical"
3. THE Alert_Rule SHALL trigger when anomaly_fused_score > 0.9 for 30 seconds with severity "critical"
4. THE Alert_Rule SHALL trigger when layer2_system_state == 3 (HALT) for 1 minute with severity "critical"
5. THE Alert_Rule SHALL trigger when exchange_connection_health == 0 for 2 minutes with severity "critical"
6. THE Alert_Rule SHALL include annotations with summary and description fields
7. THE Alert_Rule SHALL include labels for routing to PagerDuty

### Requirement 24: Warning Alert Rules

**User Story:** As an SRE operator, I want Prometheus alert rules for warning conditions (high reconnect rate, consumer lag, rejection rate), so that I can proactively address issues before they become critical.

#### Acceptance Criteria

1. THE Alert_Rule SHALL trigger when rate(exchange_websocket_reconnects_total[5m]) * 60 > 1 for 5 minutes with severity "warning"
2. THE Alert_Rule SHALL trigger when kafka_consumer_lag_seconds > 30 for 5 minutes with severity "warning"
3. THE Alert_Rule SHALL trigger when rate(risk_trade_rejections_total[5m]) > 0.5 for 5 minutes with severity "warning"
4. THE Alert_Rule SHALL trigger when consensus_divergence_max_bps > 100 for 2 minutes with severity "warning"
5. THE Alert_Rule SHALL trigger when increase(trust_degradation_events_total[5m]) > 0 with severity "info"
6. THE Alert_Rule SHALL include annotations with summary and description fields
7. THE Alert_Rule SHALL include labels for routing to Slack

### Requirement 25: Dashboard Layout and Organization

**User Story:** As an SRE operator, I want the Grafana dashboard organized into logical rows with clear section headers, so that I can quickly navigate to relevant observability data.

#### Acceptance Criteria

1. THE Grafana_Dashboard SHALL organize panels into rows: Overview, Trust Decomposition, Anomaly Decomposition, Layer 1 Telemetry, Layer 3 Strategy, Layer 4 Risk, Layer 5 Execution, Layer 6 Audit, Kafka & Pipeline
2. THE Grafana_Dashboard SHALL use row titles as section headers
3. THE Grafana_Dashboard SHALL use consistent panel sizing within each row
4. THE Grafana_Dashboard SHALL preserve the existing dark theme
5. THE Grafana_Dashboard SHALL use 5-second refresh interval
6. THE Grafana_Dashboard SHALL include dashboard variables for symbol filtering
7. THE Grafana_Dashboard SHALL maintain backward compatibility with existing 8 panels

### Requirement 26: PromQL Query Patterns Documentation

**User Story:** As a developer, I want documentation of common PromQL query patterns used in the dashboard, so that I can create new panels or modify existing ones consistently.

#### Acceptance Criteria

1. THE Documentation SHALL provide PromQL patterns for rate calculations: rate(metric_total[5m])
2. THE Documentation SHALL provide PromQL patterns for histogram quantiles: histogram_quantile(0.95, rate(metric_bucket[5m]))
3. THE Documentation SHALL provide PromQL patterns for increase over time: increase(metric_total[1h])
4. THE Documentation SHALL provide PromQL patterns for aggregation: sum by (label) (metric)
5. THE Documentation SHALL provide PromQL patterns for threshold filtering: metric > threshold
6. THE Documentation SHALL provide examples for each pattern with actual metric names from the platform

### Requirement 27: SRE Debugging Workflows

**User Story:** As an SRE operator, I want documented debugging workflows for common production scenarios, so that I can efficiently diagnose and resolve issues using the observability dashboard.

#### Acceptance Criteria

1. THE Documentation SHALL provide workflow for debugging trust score drops: check trust decomposition panel → identify failing component → check layer 1 telemetry for root cause
2. THE Documentation SHALL provide workflow for debugging anomaly spikes: check anomaly decomposition panel → check feature vector panel → check HMM regime state → correlate with trust degradation
3. THE Documentation SHALL provide workflow for debugging execution failures: check layer 5 retry/failure panel → check order placement latency → check exchange health status
4. THE Documentation SHALL provide workflow for debugging pipeline bottlenecks: check Kafka consumer lag → check pipeline stage latency → identify slowest stage
5. THE Documentation SHALL provide workflow for debugging risk rejections: check layer 4 rejection reasons → check exposure/drawdown panel → check circuit breaker state
6. THE Documentation SHALL include screenshots or panel references for each workflow step

### Requirement 28: Concrete Grafana Panel JSON Specifications

**User Story:** As a developer, I want complete Grafana panel JSON specifications for all new panels, so that I can import them directly into Grafana without manual configuration.

#### Acceptance Criteria

1. THE Specification SHALL provide complete JSON for trust score decomposition panel including all queries, field configs, and overrides
2. THE Specification SHALL provide complete JSON for anomaly score decomposition panel including all queries, field configs, and overrides
3. THE Specification SHALL provide complete JSON for HMM regime state timeline panel including mappings and colors
4. THE Specification SHALL provide complete JSON for all layer-specific telemetry panels
5. THE Specification SHALL provide complete JSON for Kafka consumer lag panel
6. THE Specification SHALL provide complete JSON for pipeline stage latency panel
7. THE Specification SHALL use Grafana schema version 39 (current version)
8. THE Specification SHALL include gridPos coordinates for panel placement
9. THE Specification SHALL include datasource configuration referencing Prometheus UID
10. THE Specification SHALL be directly importable into Grafana without modification

### Requirement 29: Alert Rule YAML Specifications

**User Story:** As a developer, I want complete Prometheus alert rule YAML specifications, so that I can deploy alert rules to Prometheus without manual configuration.

#### Acceptance Criteria

1. THE Specification SHALL provide complete YAML for all critical alert rules in a single file
2. THE Specification SHALL provide complete YAML for all warning alert rules in a single file
3. THE Specification SHALL use Prometheus alert rule syntax with groups, rules, expr, for, labels, and annotations
4. THE Specification SHALL include routing labels for PagerDuty (critical) and Slack (warning)
5. THE Specification SHALL include descriptive annotations with summary and description templates
6. THE Specification SHALL be directly deployable to Prometheus without modification

### Requirement 30: Metric Naming Convention Compliance

**User Story:** As a developer, I want all panel queries to use metrics that comply with the established naming conventions, so that the observability system remains consistent and maintainable.

#### Acceptance Criteria

1. THE Panel_Queries SHALL use metric names following pattern: <layer>_<component>_<metric_type>_<unit>
2. THE Panel_Queries SHALL use appropriate metric type suffixes: _total for counters, _duration_ms or _latency_ms for histograms, _percent or _pct for percentages
3. THE Panel_Queries SHALL use consistent label names: symbol, exchange_id, direction, reason, timeframe, stage
4. THE Panel_Queries SHALL avoid high-cardinality labels (no UUIDs, timestamps, or unbounded strings)
5. THE Panel_Queries SHALL reference only metrics defined in OBSERVABILITY_METRICS_SPEC.md or planned in phase3-layers-3-6-observability spec

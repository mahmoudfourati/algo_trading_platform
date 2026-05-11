# Requirements Document

## Introduction

This document specifies the requirements for implementing Phase 3 Layers 3-6 observability metrics for the algorithmic trading platform. This phase completes the production-grade observability evolution by adding deep forensic visibility into strategy generation (Layer 3), risk management (Layer 4), execution (Layer 5), and audit logging (Layer 6).

The implementation follows established patterns from completed Phases 1-2 (trust and anomaly score decomposition) and Phase 3 Layer 1 (ingestion telemetry), using Prometheus metrics exported on dedicated HTTP servers.

## Glossary

- **Layer_3_Strategy**: The trading signal generation service that consumes ScoredTick messages and produces TradeSignal messages using dual-timeframe technical indicators
- **Layer_4_Risk**: The risk management engine that evaluates trade signals against pre-execution checks and circuit breaker rules
- **Layer_5_Execution**: The order execution engine that submits approved orders to exchanges with retry logic and idempotency guarantees
- **Layer_6_Audit**: The audit logging system that records all system events with hash chain integrity
- **Prometheus_Metric**: A time-series metric exported via HTTP endpoint for scraping by Prometheus monitoring system
- **Gauge**: A Prometheus metric type representing a value that can go up or down
- **Counter**: A Prometheus metric type representing a monotonically increasing value
- **Histogram**: A Prometheus metric type representing a distribution of values across buckets
- **Metrics_HTTP_Server**: An HTTP server exposing /metrics endpoint for Prometheus scraping
- **Technical_Indicator**: A calculated value from price/volume data (RSI, MACD, Bollinger Bands, EMA)
- **Circuit_Breaker**: A risk management state machine with states NORMAL, REDUCED, HALTED
- **Rejection_Reason**: A classification of why a trade signal was rejected by risk management
- **Slippage**: The difference between expected and actual execution price
- **Idempotency_Dedup**: Prevention of duplicate order submissions using deterministic client order IDs
- **Hash_Chain**: A cryptographic chain linking audit log entries for tamper detection

## Requirements

### Requirement 1

**User Story:** As an SRE operator, I want Layer 3 Strategy to export technical indicator values as Prometheus metrics, so that I can monitor signal generation behavior and diagnose strategy failures.

#### Acceptance Criteria

1. WHEN Layer 3 processes a finalized candle, THE Layer_3_Strategy SHALL export RSI indicator value as a Gauge metric labeled by symbol and timeframe
2. WHEN Layer 3 processes a finalized candle, THE Layer_3_Strategy SHALL export MACD histogram value as a Gauge metric labeled by symbol and timeframe
3. WHEN Layer 3 processes a finalized candle, THE Layer_3_Strategy SHALL export Bollinger Band width as a Gauge metric labeled by symbol and timeframe
4. WHEN Layer 3 generates a trade signal, THE Layer_3_Strategy SHALL increment a Counter metric labeled by symbol and signal direction (LONG, SHORT, HOLD)
5. WHEN Layer 3 generates a trade signal, THE Layer_3_Strategy SHALL record signal strength in a Histogram metric labeled by symbol
6. WHEN Layer 3 detects an EMA crossover event, THE Layer_3_Strategy SHALL increment a Counter metric labeled by symbol and crossover direction (bullish, bearish)
7. THE Layer_3_Strategy SHALL export all indicator metrics for both 5m and 1h timeframes

### Requirement 2

**User Story:** As an SRE operator, I want Layer 4 Risk to export rejection reasons and circuit breaker state as Prometheus metrics, so that I can understand why trades are being blocked and monitor risk management behavior.

#### Acceptance Criteria

1. WHEN Layer 4 rejects a trade signal, THE Layer_4_Risk SHALL increment a Counter metric labeled by rejection reason
2. THE Layer_4_Risk SHALL export all rejection reasons dynamically without hardcoding specific reason values
3. WHEN Layer 4 observes market state, THE Layer_4_Risk SHALL export current portfolio exposure percentage as a Gauge metric labeled by symbol
4. WHEN Layer 4 observes market state, THE Layer_4_Risk SHALL export current drawdown percentage as a Gauge metric
5. WHEN Layer 4 observes market state, THE Layer_4_Risk SHALL export circuit breaker state as a Gauge metric with values (NORMAL=0, REDUCED=1, HALTED=2)
6. WHEN Layer 4 observes market state, THE Layer_4_Risk SHALL export consecutive loss counter as a Gauge metric
7. THE Layer_4_Risk SHALL expose metrics on a dedicated HTTP server following the established pattern

### Requirement 3

**User Story:** As an SRE operator, I want Layer 5 Execution to export order placement latency and retry metrics, so that I can monitor exchange connectivity and diagnose execution failures.

#### Acceptance Criteria

1. WHEN Layer 5 submits an order to an exchange, THE Layer_5_Execution SHALL record order placement latency in a Histogram metric labeled by exchange_id
2. WHEN Layer 5 retries an order submission, THE Layer_5_Execution SHALL increment a Counter metric labeled by exchange_id and retry reason
3. WHEN Layer 5 detects a duplicate order via idempotency check, THE Layer_5_Execution SHALL increment a Counter metric labeled by exchange_id
4. WHEN Layer 5 fails to submit an order after all retries, THE Layer_5_Execution SHALL increment a Counter metric labeled by exchange_id and failure reason
5. WHEN Layer 5 executes an order, THE Layer_5_Execution SHALL record slippage in a Histogram metric labeled by symbol and direction
6. THE Layer_5_Execution SHALL expose metrics on a dedicated HTTP server following the established pattern

### Requirement 4

**User Story:** As an SRE operator, I want Layer 6 Audit to export log write latency and hash verification metrics, so that I can monitor audit system health and detect integrity issues.

#### Acceptance Criteria

1. WHEN Layer 6 writes an audit log entry, THE Layer_6_Audit SHALL record write latency in a Histogram metric
2. WHEN Layer 6 detects a hash verification failure, THE Layer_6_Audit SHALL increment a Counter metric labeled by failure reason
3. WHEN Layer 6 detects a hash chain continuity break, THE Layer_6_Audit SHALL increment a Counter metric
4. THE Layer_6_Audit SHALL add instrumentation directly to the shared/audit.py module

### Requirement 5

**User Story:** As an SRE operator, I want all new metrics to follow the established naming conventions and patterns, so that the observability system remains consistent and maintainable.

#### Acceptance Criteria

1. THE System SHALL use the prometheus_client library for all metric definitions
2. THE System SHALL follow the naming convention: <layer>_<component>_<metric_type>_<unit>
3. THE System SHALL use appropriate metric types: Gauge for current values, Counter for monotonic counts, Histogram for distributions
4. THE System SHALL keep label cardinality low by using enums for categorical data
5. THE System SHALL export metrics on dedicated HTTP servers with ports following the established pattern (9104 for Layer 3, 9105 for Layer 4, 9106 for Layer 5)
6. THE System SHALL maintain backward compatibility with existing metrics and APIs

### Requirement 6

**User Story:** As a developer, I want Layers 4 and 5 to have service.py files that wrap their engines, so that the architecture remains consistent across all layers.

#### Acceptance Criteria

1. WHEN implementing Layer 4 metrics, THE System SHALL create a new services/layer4_risk/service.py file
2. WHEN implementing Layer 5 metrics, THE System SHALL create a new services/layer5_execution/service.py file
3. THE service.py files SHALL follow the pattern established in Layer 2 and Layer 3 services
4. THE service.py files SHALL start dedicated metrics HTTP servers
5. THE service.py files SHALL wrap the existing engine classes without breaking changes
6. THE engine.py files SHALL remain focused on business logic without metrics export concerns

### Requirement 7

**User Story:** As an SRE operator, I want the implementation to be verifiable through manual testing, so that I can confirm all metrics are working before production deployment.

#### Acceptance Criteria

1. WHEN the services are running, THE System SHALL expose all new metrics on their respective /metrics endpoints
2. WHEN querying the /metrics endpoints, THE System SHALL return metrics in Prometheus text format
3. WHEN the system is processing data, THE System SHALL update metric values in real-time
4. THE System SHALL allow verification by curling http://localhost:<port>/metrics for each layer
5. THE System SHALL rebuild and run without errors after implementation


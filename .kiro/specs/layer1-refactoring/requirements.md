# Requirements Document: Layer 1 Refactoring

## Introduction

This document specifies requirements for refactoring the Layer 1 market data ingestion and validation pipeline. The refactoring addresses two critical architectural issues identified in the code review:

1. **Primary Exchange Dependency**: The current implementation only publishes validated ticks when the "primary exchange" (Binance) is present in the consensus set, creating a single point of failure. If Binance goes down, the system stops publishing even when 4 other exchanges agree on price.

2. **Unnecessary Kafka Hop**: The ingestion and validation services communicate via Kafka, adding 5-10ms latency for no architectural benefit. These services can be merged into a single process with an in-memory queue.

The refactoring will eliminate these issues while maintaining all existing functionality: multi-source consensus, trust scoring, TLS health tracking, hash chain logging, and comprehensive observability.

## Glossary

- **Layer1_Service**: The merged ingestion and validation service that replaces Layer1_Ingestion and Layer1_Validated
- **Consensus_Price**: The median mid price computed from all exchanges that pass divergence tolerance checks
- **Primary_Exchange**: Legacy concept - the designated "primary" exchange (Binance) used for routing decisions (to be removed)
- **Execution_Venue**: Any exchange where orders can be executed
- **Divergence_Check**: Validation that an execution venue's price is within tolerance of the consensus price
- **In_Memory_Queue**: Async queue that replaces Kafka for communication between ingestion and validation logic
- **ValidatedTick**: Schema representing a validated, consensus-based market data tick
- **NormalizedTick**: Schema representing a raw tick from a single exchange after normalization
- **Trust_Score**: Composite score (0-1) measuring data quality across 6 dimensions
- **Hash_Chain**: Cryptographic audit trail linking consecutive validated ticks
- **TLS_Health**: Boolean indicating whether an exchange's TLS certificate passed SPKI pinning validation

## Requirements

### Requirement 1: Use Consensus Price for All Downstream Layers

**User Story:** As a trading system operator, I want all downstream layers to use the consensus price computed from multiple exchanges, so that the system remains operational even when a single exchange (including Binance) goes down.

#### Acceptance Criteria

1. WHEN the consensus engine computes a consensus price from N exchanges (N >= 2), THE Layer1_Service SHALL set ValidatedTick.mid_price equal to the consensus price
2. WHEN the consensus engine computes a consensus price, THE Layer1_Service SHALL set ValidatedTick.consensus_mid equal to the consensus price
3. THE Layer1_Service SHALL NOT skip publishing a ValidatedTick when the primary exchange is absent from the consensus set
4. THE Layer1_Service SHALL NOT filter ticks based on primary exchange presence before computing consensus
5. FOR ALL ValidatedTick messages published, ValidatedTick.mid_price SHALL equal ValidatedTick.consensus_mid

### Requirement 2: Provide Execution Venue Prices for Divergence Checking

**User Story:** As a risk manager, I want execution-time divergence checks to ensure the execution venue's price hasn't diverged from consensus, so that orders are not executed at stale or manipulated prices.

#### Acceptance Criteria

1. WHEN the Layer1_Service publishes a ValidatedTick, THE Layer1_Service SHALL include a map of execution venue prices (exchange_id -> mid_price) in ValidatedTick.execution_venue_prices
2. FOR ALL exchanges present in the aligned window, THE Layer1_Service SHALL include that exchange's mid price in execution_venue_prices
3. THE execution_venue_prices map SHALL include both consensus sources and divergent sources
4. WHEN an exchange is absent from the aligned window, THE Layer1_Service SHALL NOT include that exchange in execution_venue_prices
5. FOR ALL exchanges in execution_venue_prices, the mid price SHALL be computed as (bid + ask) / 2.0

### Requirement 3: Validate Execution Venue Divergence at Execution Time

**User Story:** As a trading system operator, I want the execution layer to validate that the chosen execution venue's price is within tolerance of the consensus price, so that orders are rejected if the venue price has diverged significantly.

#### Acceptance Criteria

1. WHEN Layer5_Execution receives an approved order, THE Layer5_Execution SHALL retrieve the most recent ValidatedTick for the order's symbol
2. WHEN Layer5_Execution selects an execution venue, THE Layer5_Execution SHALL check if the venue's price exists in ValidatedTick.execution_venue_prices
3. IF the execution venue's price is absent from execution_venue_prices, THEN THE Layer5_Execution SHALL reject the order with reason "execution_venue_price_unavailable"
4. WHEN the execution venue's price is present, THE Layer5_Execution SHALL compute the divergence as abs(venue_price - consensus_mid) / consensus_mid
5. IF the divergence exceeds the configured tolerance (default 0.003), THEN THE Layer5_Execution SHALL reject the order with reason "execution_venue_diverged"
6. IF the divergence is within tolerance, THEN THE Layer5_Execution SHALL proceed with order execution
7. THE Layer5_Execution SHALL emit a metric "execution_venue_divergence_bps" with labels [symbol, exchange_id] for all divergence checks

### Requirement 4: Deprecate Primary Exchange Routing Logic

**User Story:** As a system maintainer, I want the primary exchange concept to be deprecated but not removed, so that backward compatibility is maintained while the system transitions to consensus-based routing.

#### Acceptance Criteria

1. THE ValidatedTick.primary_exchange field SHALL remain in the schema with a deprecation notice
2. THE Layer1_Service SHALL continue to populate ValidatedTick.primary_exchange with the configured primary exchange value
3. THE Layer1_Service SHALL NOT use ValidatedTick.primary_exchange for any routing or filtering decisions
4. THE Layer1_Service SHALL remove the "primary_source_skipped_total" metric increment when primary exchange is absent
5. THE Layer1_Service SHALL emit an audit event "layer1.primary_exchange.deprecated" on startup indicating the field is deprecated

### Requirement 5: Merge Ingestion and Validation Services

**User Story:** As a system operator, I want ingestion and validation to run in a single process, so that end-to-end latency is reduced by 5-10ms and operational complexity is reduced.

#### Acceptance Criteria

1. THE Layer1_Service SHALL instantiate WebSocket adapters for all configured exchanges
2. WHEN a WebSocket adapter receives a tick, THE Layer1_Service SHALL publish the NormalizedTick to an in-memory async queue
3. THE Layer1_Service SHALL consume NormalizedTick messages from the in-memory queue
4. THE Layer1_Service SHALL process consumed ticks through the tick aligner, consensus engine, and trust scorer
5. WHEN validation completes, THE Layer1_Service SHALL publish ValidatedTick to Kafka topic "market.ticks.validated"
6. THE Layer1_Service SHALL NOT publish NormalizedTick messages to Kafka topic "market.ticks.raw"
7. THE in-memory queue SHALL have a maximum size of 10,000 messages to prevent memory exhaustion

### Requirement 6: Implement In-Memory Queue for Raw Ticks

**User Story:** As a developer, I want an in-memory async queue to replace the Kafka hop between ingestion and validation, so that latency is minimized and the codebase is simpler.

#### Acceptance Criteria

1. THE In_Memory_Queue SHALL be implemented using Python's asyncio.Queue
2. THE In_Memory_Queue SHALL support async put() and get() operations
3. WHEN the queue is full (10,000 messages), THE In_Memory_Queue SHALL block the producer until space is available
4. WHEN the queue is empty, THE In_Memory_Queue SHALL block the consumer until a message is available
5. THE In_Memory_Queue SHALL emit a metric "layer1_queue_size" indicating the current number of messages in the queue
6. THE In_Memory_Queue SHALL emit a metric "layer1_queue_full_total" counting the number of times the queue reached capacity

### Requirement 7: Preserve All Existing Metrics and Observability

**User Story:** As a system operator, I want all existing Prometheus metrics and audit events to be preserved, so that monitoring dashboards and alerts continue to work without modification.

#### Acceptance Criteria

1. THE Layer1_Service SHALL emit all metrics currently emitted by Layer1_Validated (30+ metrics)
2. THE Layer1_Service SHALL emit all audit events currently emitted by Layer1_Validated
3. THE Layer1_Service SHALL emit all metrics currently emitted by Layer1_Ingestion (connection status, reconnection attempts, TLS health)
4. THE Layer1_Service SHALL emit a new metric "layer1_ingestion_to_validation_latency_ms" measuring the time from tick receipt to validation completion
5. THE Layer1_Service SHALL emit a new metric "layer1_merged_service_active" with value 1.0 to indicate the merged service is running
6. THE Layer1_Service SHALL NOT emit metrics related to Kafka consumption of raw ticks (since raw ticks are no longer published to Kafka)

### Requirement 8: Maintain Backward Compatibility for Downstream Consumers

**User Story:** As a downstream service developer, I want the ValidatedTick schema to remain compatible, so that Layer 2, Layer 3, Layer 4, and Layer 5 services continue to work without modification.

#### Acceptance Criteria

1. THE ValidatedTick schema SHALL retain all existing fields (symbol, primary_exchange, mid_price, consensus_mid, volume_24h, spread, trust_score, sub_scores, used_sources, divergent_sources, timestamp_utc, tick_hash, liveness)
2. THE ValidatedTick schema SHALL add the new field execution_venue_prices with a default value of empty dict
3. WHEN a downstream service reads a ValidatedTick without the execution_venue_prices field (old message), THE schema validation SHALL succeed with execution_venue_prices defaulting to empty dict
4. WHEN a downstream service reads a ValidatedTick with execution_venue_prices (new message), THE schema validation SHALL succeed
5. THE ValidatedTick.mid_price field SHALL continue to represent the price used by all downstream layers

### Requirement 9: Preserve Hash Chain Integrity

**User Story:** As an auditor, I want the hash chain to remain unbroken across the refactoring, so that the cryptographic audit trail is maintained.

#### Acceptance Criteria

1. THE Layer1_Service SHALL continue to use the Hash_Chain_Logger to append validated ticks to the hash chain
2. WHEN the Layer1_Service starts, THE Hash_Chain_Logger SHALL load the previous hash from the existing hash chain log file
3. WHEN the Layer1_Service appends a tick to the hash chain, THE hash SHALL be computed from (symbol, primary_exchange, consensus_mid, used_sources, divergent_sources, trust_score, timestamp, previous_hash)
4. THE hash chain log file format SHALL remain unchanged (JSONL with fields: timestamp, symbol, primary_exchange, primary_mid_price, consensus_mid, used_sources, divergent_sources, trust_score, received_timestamp_ms, previous_hash, current_hash)
5. THE Layer1_Service SHALL emit the metric "trust_subscore_t5_hashchain" indicating hash chain continuity

### Requirement 10: Support Graceful Shutdown and Restart

**User Story:** As a system operator, I want the merged service to shut down gracefully, so that no ticks are lost and the hash chain remains consistent.

#### Acceptance Criteria

1. WHEN the Layer1_Service receives a SIGTERM or SIGINT signal, THE Layer1_Service SHALL stop accepting new ticks from WebSocket adapters
2. WHEN shutdown is initiated, THE Layer1_Service SHALL drain the in-memory queue (process all remaining ticks)
3. WHEN the queue is drained, THE Layer1_Service SHALL flush the Hash_Chain_Logger to disk
4. WHEN the hash chain is flushed, THE Layer1_Service SHALL close the Kafka producer
5. WHEN the Kafka producer is closed, THE Layer1_Service SHALL close all WebSocket connections
6. THE Layer1_Service SHALL complete shutdown within 30 seconds or log a warning
7. WHEN the Layer1_Service restarts, THE Hash_Chain_Logger SHALL resume from the last hash in the log file

### Requirement 11: Maintain TLS Health Tracking

**User Story:** As a security operator, I want TLS health tracking to continue working, so that I can detect certificate pinning failures and potential MITM attacks.

#### Acceptance Criteria

1. THE Layer1_Service SHALL continue to use the TLS_Health_Registry to track TLS health per exchange
2. WHEN a WebSocket adapter performs TLS pinning validation, THE adapter SHALL update the TLS_Health_Registry with the result
3. WHEN a NormalizedTick is created, THE adapter SHALL set NormalizedTick.tls_ok based on the TLS pinning result
4. WHEN computing trust scores, THE Layer1_Service SHALL use the TLS health from NormalizedTick.tls_ok
5. THE Layer1_Service SHALL emit the metric "tls_exchange_health" with labels [symbol, exchange_id] indicating TLS health (1.0 = healthy, 0.0 = unhealthy)
6. THE Layer1_Service SHALL emit the metric "tls_validation_failures_total" with labels [symbol, exchange_id] counting TLS failures

### Requirement 12: Support Rollback to Old Architecture

**User Story:** As a system operator, I want the ability to rollback to the old two-service architecture, so that I can quickly recover if the merged service has critical bugs.

#### Acceptance Criteria

1. THE old Layer1_Ingestion and Layer1_Validated services SHALL be moved to services/layer1_ingestion_old/ and services/layer1_validated_old/
2. THE docker-compose.yml file SHALL include commented-out service definitions for layer1-ingestion-old and layer1-validated-old
3. THE rollback procedure SHALL be documented in .kiro/specs/layer1-refactoring/ROLLBACK.md
4. WHEN rolling back, THE operator SHALL stop the layer1 service, uncomment the old service definitions, and restart docker-compose
5. THE rollback procedure SHALL take less than 5 minutes to execute

### Requirement 13: Validate Configuration on Startup

**User Story:** As a system operator, I want the service to validate its configuration on startup, so that misconfigurations are caught early rather than causing runtime failures.

#### Acceptance Criteria

1. WHEN the Layer1_Service starts, THE Layer1_Service SHALL validate that at least one exchange is configured in the EXCHANGES environment variable
2. WHEN the Layer1_Service starts, THE Layer1_Service SHALL validate that the PRIMARY_EXCHANGE (if configured) is in the list of enabled exchanges
3. WHEN the Layer1_Service starts, THE Layer1_Service SHALL validate that trust weights sum to 1.0 (within 0.001 tolerance)
4. WHEN the Layer1_Service starts, THE Layer1_Service SHALL validate that all trust weights are non-negative
5. IF any validation fails, THEN THE Layer1_Service SHALL log an error and exit with status code 1
6. IF all validations pass, THEN THE Layer1_Service SHALL emit an audit event "layer1.startup.config_validated" with the validated configuration

### Requirement 14: Emit End-to-End Latency Metrics

**User Story:** As a performance engineer, I want to measure end-to-end latency from tick receipt to ValidatedTick publication, so that I can verify the latency reduction from removing the Kafka hop.

#### Acceptance Criteria

1. WHEN a WebSocket adapter receives a tick, THE adapter SHALL record the receipt timestamp
2. WHEN the Layer1_Service publishes a ValidatedTick, THE Layer1_Service SHALL compute the end-to-end latency as (publish_time - receipt_time)
3. THE Layer1_Service SHALL emit a histogram metric "layer1_e2e_latency_ms" with labels [symbol] and buckets [1, 2, 5, 10, 20, 50, 100, 200, 500]
4. THE Layer1_Service SHALL emit a histogram metric "layer1_queue_latency_ms" measuring time from queue put to queue get
5. THE Layer1_Service SHALL emit a histogram metric "layer1_validation_latency_ms" measuring time from queue get to ValidatedTick publication
6. THE Layer1_Service SHALL emit a gauge metric "layer1_e2e_latency_p99_ms" tracking the 99th percentile end-to-end latency over a 60-second window

### Requirement 15: Support Multiple Symbols

**User Story:** As a trading system operator, I want the merged service to handle multiple symbols concurrently, so that the system can trade multiple assets simultaneously.

#### Acceptance Criteria

1. THE Layer1_Service SHALL maintain separate tick aligners for each symbol
2. THE Layer1_Service SHALL maintain separate consensus state for each symbol
3. THE Layer1_Service SHALL maintain separate hash chains for each symbol
4. WHEN ticks for different symbols arrive concurrently, THE Layer1_Service SHALL process them independently without blocking
5. THE Layer1_Service SHALL emit per-symbol metrics for all observability metrics (trust_score, latency, consensus, etc.)
6. THE Layer1_Service SHALL support at least 10 concurrent symbols without performance degradation


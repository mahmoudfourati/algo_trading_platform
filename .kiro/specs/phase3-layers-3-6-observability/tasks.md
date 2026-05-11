# Implementation Plan: Phase 3 Layers 3-6 Observability Metrics

## Overview

This plan implements production-grade observability metrics for Layers 3-6 of the algorithmic trading platform, completing the observability evolution started in Phases 1-2. The implementation adds 19 new Prometheus metrics across 4 layers, following established patterns from completed phases.

## Tasks

- [ ] 1. Implement Layer 3 Strategy Metrics
  - [x] 1.1 Add technical indicator metrics to Layer 3 service
    - Add Gauge metrics for RSI, MACD histogram, and Bollinger Band width
    - Label metrics by symbol and timeframe (5m, 1h)
    - Export metrics in `Layer3SymbolState.ingest_tick()` after indicator processing
    - _Requirements: 1.1, 1.2, 1.3, 1.7_
  
  - [x] 1.2 Add signal generation metrics to Layer 3 service
    - Add Counter for signal direction (LONG, SHORT, HOLD)
    - Add Histogram for signal strength distribution
    - Export metrics in `Layer3SymbolState._maybe_emit_signal()`
    - _Requirements: 1.4, 1.5_
  
  - [x] 1.3 Add EMA crossover detection and metrics
    - Detect bullish/bearish EMA crossovers in `IndicatorManager.process()`
    - Add Counter for crossover events labeled by direction
    - Store previous EMA values for crossover detection
    - _Requirements: 1.6_
  
  - [~] 1.4 Verify Layer 3 metrics export
    - Rebuild Layer 3 service
    - Start service and verify metrics on http://localhost:9104/metrics
    - Process test data and verify metric values update
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [~] 2. Checkpoint - Ensure Layer 3 metrics are working
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Implement Layer 4 Risk Service and Metrics
  - [~] 3.1 Create Layer 4 service.py file
    - Create `services/layer4_risk/service.py` following Layer 2/3 pattern
    - Implement `Layer4Service` dataclass with Kafka consumer and publisher
    - Wrap `Layer4RiskEngine` for signal evaluation
    - Start metrics HTTP server on port 9105
    - _Requirements: 6.1, 6.3, 6.4, 2.7_
  
  - [~] 3.2 Add risk management metrics to Layer 4 service
    - Add Counter for trade rejections with dynamic reason labels
    - Add Gauge for current exposure percentage by symbol
    - Add Gauge for current drawdown percentage
    - Add Gauge for circuit breaker state (0=NORMAL, 1=REDUCED, 2=HALTED)
    - Add Gauge for consecutive loss counter
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6_
  
  - [~] 3.3 Integrate metrics export in Layer 4 service run loop
    - Export rejection reason counter when decision.approved is False
    - Export circuit breaker state from decision.circuit_breaker_state
    - Export consecutive losses from engine.state.consecutive_losing_trades
    - Export drawdown from engine.state.latest_drawdown_pct
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 2.6_
  
  - [~] 3.4 Verify Layer 4 metrics export
    - Rebuild Layer 4 service
    - Start service and verify metrics on http://localhost:9105/metrics
    - Process test signals and verify rejection metrics increment
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [~] 4. Checkpoint - Ensure Layer 4 metrics are working
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 5. Implement Layer 5 Execution Service and Metrics
  - [~] 5.1 Create Layer 5 service.py file
    - Create `services/layer5_execution/service.py` following Layer 2/3 pattern
    - Implement `Layer5Service` dataclass with Kafka consumer and publisher
    - Wrap `ExecutionEngine` for order submission
    - Start metrics HTTP server on port 9106
    - _Requirements: 6.2, 6.3, 6.4, 3.6_
  
  - [~] 5.2 Add order placement latency instrumentation
    - Add Histogram for order placement latency by exchange_id
    - Time order submission in service run loop using time.perf_counter()
    - Export latency metric after successful submission
    - _Requirements: 3.1_
  
  - [~] 5.3 Add retry and failure metrics to Layer 5 service
    - Add Counter for order retries by exchange_id and reason
    - Add Counter for idempotency dedup hits by exchange_id
    - Add Counter for order failures by exchange_id and reason
    - Track metrics from engine telemetry counters
    - _Requirements: 3.2, 3.3, 3.4_
  
  - [~] 5.4 Add slippage calculation and metrics
    - Add Histogram for slippage in basis points by symbol and direction
    - Calculate slippage: ((avg_fill_price - entry_price) / entry_price) * 10000
    - Export slippage metric after successful execution
    - _Requirements: 3.5_
  
  - [~] 5.5 Verify Layer 5 metrics export
    - Rebuild Layer 5 service
    - Start service and verify metrics on http://localhost:9106/metrics
    - Submit test orders and verify latency and slippage metrics
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [~] 6. Checkpoint - Ensure Layer 5 metrics are working
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement Layer 6 Audit Metrics
  - [~] 7.1 Add audit log write latency instrumentation
    - Add Histogram for audit log write latency in shared/audit.py
    - Time file write operations using time.perf_counter()
    - Export latency metric after successful write
    - _Requirements: 4.1, 4.4_
  
  - [~] 7.2 Add hash verification failure metrics
    - Add Counter for hash verification failures by reason
    - Add Counter for hash chain continuity breaks
    - Integrate metrics in hash chain verification logic (if exists)
    - _Requirements: 4.2, 4.3_
  
  - [~] 7.3 Verify Layer 6 metrics export
    - Rebuild all services that use shared/audit.py
    - Verify metrics on http://localhost:9102/metrics (Layer 1 validated service)
    - Trigger audit events and verify latency metrics update
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [ ] 8. Integration and Verification
  - [~] 8.1 Update Prometheus scrape configuration
    - Add Layer 4 Risk scrape target (port 9105) to ops/prometheus/prometheus.yml
    - Add Layer 5 Execution scrape target (port 9106) to ops/prometheus/prometheus.yml
    - Verify Prometheus can scrape all new endpoints
    - _Requirements: 5.5_
  
  - [~] 8.2 Update docker-compose.yml for new services
    - Add Layer 4 Risk service container with metrics port 9105 exposed
    - Add Layer 5 Execution service container with metrics port 9106 exposed
    - Verify all services start without errors
    - _Requirements: 6.3, 6.4_
  
  - [~] 8.3 End-to-end verification
    - Start all services with docker-compose up
    - Verify all /metrics endpoints return 200 OK
    - Run backtest or live soak test to generate data
    - Verify all 19 new metrics appear in Prometheus
    - Verify metric values update in real-time
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  
  - [~] 8.4 Verify metric naming conventions
    - Check all metrics follow <layer>_<component>_<metric_type>_<unit> pattern
    - Verify label cardinality is low (<1000 unique series)
    - Verify no breaking changes to existing APIs
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6_

- [~] 9. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Follow Layer 2 anomaly service as the reference implementation pattern
- All metrics are best-effort and should not crash services on failure
- Use try-except blocks around metric updates for robustness
- Verify metrics in Prometheus format using curl before moving to next layer
- Layer 3 already has service.py, only modify it (no new file creation)
- Layers 4 and 5 need new service.py files created
- Layer 6 metrics are added to shared/audit.py (no new service)
- Total implementation time: ~2.5 hours


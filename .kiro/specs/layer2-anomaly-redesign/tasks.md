# Tasks: Layer 2 Anomaly Detection System Redesign

## Overview

This document breaks down the Layer 2 redesign into concrete implementation tasks organized by 4 phases. Each task includes acceptance criteria, estimated effort, and dependencies.

**Total Estimated Effort**: 4 weeks (160 hours)

---

## Phase 1: Foundation (Week 1)

**Goal**: Immediate flash crash detection with zero warmup  
**Estimated Effort**: 40 hours

### Task 1.1: Create Detector Base Class

**Priority**: P0 (Blocker)  
**Effort**: 2 hours  
**Dependencies**: None

**Description**: Implement the abstract base class that all detectors will inherit from.

**Acceptance Criteria**:
- [x] Create `detectors/base.py` with `AnomalyDetector` abstract class
- [x] Define `DetectorScore` dataclass with `score`, `reason`, `warmup_progress`
- [x] Define abstract methods: `update()`, `get_warmup_ticks_required()`, `get_name()`
- [x] Add type hints for all methods
- [x] Add docstrings with examples

**Files to Create**:
- `services/layer2_anomaly/detectors/__init__.py`
- `services/layer2_anomaly/detectors/base.py`

---

### Task 1.2: Implement AbsoluteThresholdDetector

**Priority**: P0 (Blocker)  
**Effort**: 4 hours  
**Dependencies**: Task 1.1

**Description**: Implement detector for flash events (price jump, spread, volume).

**Acceptance Criteria**:
- [x] Create `detectors/absolute_threshold.py`
- [x] Implement price jump detection (>100bps → score 1.0)
- [x] Implement spread detection (>50bps → score 0.9)
- [x] Implement volume spike detection (>10x avg → score 0.8)
- [x] Return max score when multiple thresholds exceeded
- [x] Maintain 5-min rolling average for volume (300 ticks)
- [~] Latency <0.5ms per tick
- [~] Add unit tests with known input/output pairs

**Files to Create**:
- `services/layer2_anomaly/detectors/absolute_threshold.py`
- `services/layer2_anomaly/tests/test_absolute_threshold.py`

---

### Task 1.3: Implement TrustPassthroughDetector

**Priority**: P0 (Blocker)  
**Effort**: 2 hours  
**Dependencies**: Task 1.1

**Description**: Convert Layer 1 trust score to anomaly score.

**Acceptance Criteria**:
- [ ] Create `detectors/trust_passthrough.py`
- [~] Implement formula: `anomaly_score = 1.0 - trust_score`
- [~] Latency <0.1ms per tick
- [~] Add unit tests verifying score inversion

**Files to Create**:
- `services/layer2_anomaly/detectors/trust_passthrough.py`
- `services/layer2_anomaly/tests/test_trust_passthrough.py`

---

### Task 1.4: Implement Basic Fusion Engine

**Priority**: P0 (Blocker)  
**Effort**: 4 hours  
**Dependencies**: Task 1.1

**Description**: Implement fusion engine with weighted average (Phase 1: no coincidence logic yet).

**Acceptance Criteria**:
- [~] Create `fusion.py` with `FusionEngine` class
- [~] Define `FusionResult` dataclass
- [~] Implement weighted average fusion
- [~] Support configurable detector weights
- [~] Validate weights sum to 1.0
- [~] Return top detector as reason
- [ ] Latency <0.5ms per tick
- [~] Add unit tests for weighted average properties

**Files to Create**:
- `services/layer2_anomaly/fusion.py`
- `services/layer2_anomaly/tests/test_fusion.py`

---

### Task 1.5: Update Kafka Consumer/Publisher

**Priority**: P0 (Blocker)  
**Effort**: 4 hours  
**Dependencies**: None

**Description**: Update service.py to consume ValidatedTick and publish ScoredTick.

**Acceptance Criteria**:
- [~] Update `service.py` to consume from `market.ticks.validated`
- [~] Update `service.py` to publish to `market.ticks.scored`
- [~] Add `anomaly_score` field to output message
- [~] Add `anomaly_reasons` field (List[str]) to output message
- [~] Add `system_state` field to output message
- [~] Add `regime` field to output message
- [~] Preserve all ValidatedTick fields in output
- [~] Add error handling for Kafka failures
- [~] Add exponential backoff for reconnection

**Files to Modify**:
- `services/layer2_anomaly/service.py`

---

### Task 1.6: Add Prometheus Metrics (Phase 1)

**Priority**: P1 (High)  
**Effort**: 4 hours  
**Dependencies**: Task 1.4

**Description**: Add Prometheus metrics for Phase 1 detectors.

**Acceptance Criteria**:
- [~] Create `metrics.py` with Prometheus client setup
- [~] Add gauge `layer2_detector_score{symbol, detector}`
- [~] Add gauge `layer2_final_anomaly_score{symbol}`
- [~] Add gauge `layer2_system_state{symbol}`
- [~] Add histogram `layer2_processing_latency_ms{symbol}`
- [~] Expose metrics endpoint on port 9103
- [~] Add unit tests for metrics registration

**Files to Create**:
- `services/layer2_anomaly/metrics.py`
- `services/layer2_anomaly/tests/test_metrics.py`

---

### Task 1.7: Update Engine Integration

**Priority**: P0 (Blocker)  
**Effort**: 6 hours  
**Dependencies**: Tasks 1.2, 1.3, 1.4, 1.6

**Description**: Integrate Phase 1 detectors into main engine.

**Acceptance Criteria**:
- [~] Update `engine.py` to use new detector architecture
- [~] Initialize AbsoluteThreshold and TrustPassthrough detectors
- [~] Call detectors in `score_tick()` method
- [~] Pass detector results to FusionEngine
- [~] Update metrics after each tick
- [~] Remove old IF/HST code (comment out for now)
- [~] Maintain HMM and Decision Gate (no changes yet)
- [~] Add integration tests with mock Kafka

**Files to Modify**:
- `services/layer2_anomaly/engine.py`

**Files to Create**:
- `services/layer2_anomaly/tests/test_engine_integration.py`

---

### Task 1.8: Create Basic Grafana Dashboard

**Priority**: P1 (High)  
**Effort**: 4 hours  
**Dependencies**: Task 1.6

**Description**: Create Grafana dashboard for Phase 1 metrics.

**Acceptance Criteria**:
- [~] Create `layer2-anomaly-dashboard-v2.json`
- [~] Add time series panel for detector scores (2 detectors)
- [~] Add time series panel for final anomaly score
- [~] Add state timeline panel for system state
- [~] Add histogram panel for processing latency
- [~] Add symbol dropdown variable
- [~] Test dashboard with live metrics

**Files to Create**:
- `ops/grafana/provisioning/dashboards/layer2-anomaly-dashboard-v2.json`

---

### Task 1.9: Update Docker Configuration

**Priority**: P1 (High)  
**Effort**: 3 hours  
**Dependencies**: None

**Description**: Update Dockerfile and requirements.txt to remove heavy dependencies.

**Acceptance Criteria**:
- [~] Remove `scikit-learn` from requirements.txt (keep for HMM loading only)
- [~] Remove `river` from requirements.txt
- [~] Keep `numpy`, `scipy`, `joblib`
- [~] Update Dockerfile to expose port 9103
- [~] Verify Docker image builds successfully
- [~] Verify image size <500MB

**Files to Modify**:
- `services/layer2_anomaly/requirements.txt`
- `services/layer2_anomaly/Dockerfile`

---

### Task 1.10: Phase 1 Testing and Validation

**Priority**: P0 (Blocker)  
**Effort**: 6 hours  
**Dependencies**: All Phase 1 tasks

**Description**: End-to-end testing of Phase 1 implementation.

**Acceptance Criteria**:
- [~] Run unit tests (>90% coverage)
- [~] Run integration tests with mock Kafka
- [~] Test flash crash detection on tick 1
- [~] Verify latency <2ms per tick
- [~] Test with historical data (1 day)
- [~] Verify all metrics publishing correctly
- [~] Verify Grafana dashboard displays data
- [~] Document any issues found

**Files to Create**:
- `services/layer2_anomaly/tests/test_phase1_integration.py`

---

### Task 1.11: Phase 1 Documentation

**Priority**: P2 (Medium)  
**Effort**: 3 hours  
**Dependencies**: Task 1.10

**Description**: Document Phase 1 implementation.

**Acceptance Criteria**:
- [~] Update README.md with Phase 1 status
- [~] Document detector configurations
- [~] Document metrics and their meanings
- [~] Add troubleshooting guide
- [~] Document known limitations

**Files to Modify**:
- `services/layer2_anomaly/README.md`

---

## Phase 2: Core Detection (Week 2)

**Goal**: Replace IF/HST with MAD detector and full fusion logic  
**Estimated Effort**: 40 hours

### Task 2.1: Implement MADDetector

**Priority**: P0 (Blocker)  
**Effort**: 6 hours  
**Dependencies**: Phase 1 complete

**Description**: Implement Median Absolute Deviation detector with regime awareness.

**Acceptance Criteria**:
- [~] Create `detectors/mad.py`
- [~] Maintain rolling window of 50 prices
- [~] Compute median and MAD efficiently
- [~] Implement regime-aware thresholds (k=4 for regime 0, k=8 for regime 1)
- [~] Linear interpolation between k*MAD and 2*k*MAD
- [~] Return warmup progress (0-50 ticks)
- [~] Latency <1.0ms per tick
- [~] Add unit tests with known distributions

**Files to Create**:
- `services/layer2_anomaly/detectors/mad.py`
- `services/layer2_anomaly/tests/test_mad.py`

---

### Task 2.2: Update HMM Classifier for Regime Passing

**Priority**: P0 (Blocker)  
**Effort**: 3 hours  
**Dependencies**: Task 2.1

**Description**: Update HMM to pass regime to detectors.

**Acceptance Criteria**:
- [~] Refactor `HMMRegimeClassifier` to return `RegimeClassification` dataclass
- [~] Add method to notify detectors of regime changes
- [~] Optimize HMM to only process last 30 samples (already done, verify)
- [~] Add unit tests for regime notification

**Files to Modify**:
- `services/layer2_anomaly/engine.py`

**Files to Create**:
- `services/layer2_anomaly/tests/test_hmm_regime.py`

---

### Task 2.3: Implement Full Fusion Logic with Coincidence

**Priority**: P0 (Blocker)  
**Effort**: 5 hours  
**Dependencies**: Task 2.1

**Description**: Add coincidence checking to fusion engine.

**Acceptance Criteria**:
- [~] Implement extreme event logic (any detector >0.90 → use max)
- [~] Implement coincidence logic (2+ detectors >0.60 → weighted avg + flag)
- [~] Implement normal operation (weighted avg)
- [~] Return list of contributing detectors in reasons
- [~] Add configurable thresholds (0.90, 0.60)
- [~] Add unit tests for all 3 branches
- [~] Add property-based tests for score ranges

**Files to Modify**:
- `services/layer2_anomaly/fusion.py`

**Files to Create**:
- `services/layer2_anomaly/tests/test_fusion_coincidence.py`

---

### Task 2.4: Add Coincidence Metrics

**Priority**: P1 (High)  
**Effort**: 2 hours  
**Dependencies**: Task 2.3

**Description**: Add Prometheus metrics for coincidence events.

**Acceptance Criteria**:
- [~] Add counter `layer2_coincidence_triggers_total{symbol}`
- [~] Add counter `layer2_detector_reasons_total{symbol, reason}`
- [~] Increment counters in fusion engine
- [~] Add unit tests for metric increments

**Files to Modify**:
- `services/layer2_anomaly/metrics.py`
- `services/layer2_anomaly/fusion.py`

---

### Task 2.5: Integrate MAD into Engine

**Priority**: P0 (Blocker)  
**Effort**: 4 hours  
**Dependencies**: Tasks 2.1, 2.2, 2.3

**Description**: Add MAD detector to engine and wire regime updates.

**Acceptance Criteria**:
- [~] Initialize MAD detector in engine
- [~] Pass regime to MAD detector after HMM update
- [~] Add MAD to detector list for fusion
- [~] Update detector weights (add MAD with weight 0.30)
- [~] Add integration tests with regime changes

**Files to Modify**:
- `services/layer2_anomaly/engine.py`

---

### Task 2.6: Remove IF/HST Code

**Priority**: P1 (High)  
**Effort**: 3 hours  
**Dependencies**: Task 2.5

**Description**: Remove Isolation Forest and Half-Space Trees code.

**Acceptance Criteria**:
- [~] Delete `IsolationForestScorer` class
- [~] Delete `HalfSpaceTreeScorer` class
- [~] Remove IF/HST initialization from engine
- [~] Remove IF/HST scoring from `score_tick()`
- [~] Remove IF/HST metrics
- [~] Clean up unused imports
- [~] Verify tests still pass

**Files to Modify**:
- `services/layer2_anomaly/engine.py`

---

### Task 2.7: Update Grafana Dashboard (Phase 2)

**Priority**: P1 (High)  
**Effort**: 3 hours  
**Dependencies**: Task 2.4

**Description**: Add Phase 2 metrics to dashboard.

**Acceptance Criteria**:
- [~] Add MAD detector to time series panel
- [~] Add coincidence events stat panel
- [~] Add anomaly reasons bar chart panel
- [~] Add regime indicator panel
- [~] Test dashboard with live data

**Files to Modify**:
- `ops/grafana/provisioning/dashboards/layer2-anomaly-dashboard-v2.json`

---

### Task 2.8: Performance Testing (Phase 2)

**Priority**: P0 (Blocker)  
**Effort**: 4 hours  
**Dependencies**: Task 2.5

**Description**: Verify performance targets with 3 detectors.

**Acceptance Criteria**:
- [~] Run performance tests with 10,000 ticks
- [~] Verify p50 latency <2ms
- [~] Verify p99 latency <3ms
- [~] Verify memory usage <10MB per symbol
- [~] Test with 10 concurrent symbols
- [~] Profile and optimize bottlenecks if needed

**Files to Create**:
- `services/layer2_anomaly/tests/test_performance_phase2.py`

---

### Task 2.9: Historical Data Validation

**Priority**: P1 (High)  
**Effort**: 5 hours  
**Dependencies**: Task 2.5

**Description**: Validate Phase 2 against historical data.

**Acceptance Criteria**:
- [~] Load 7 days of historical data
- [~] Run Phase 2 system on historical data
- [~] Compare anomaly scores with known events
- [~] Verify flash crash detection (if any in data)
- [~] Measure false positive rate (manual labeling)
- [~] Document findings

**Files to Create**:
- `services/layer2_anomaly/tests/test_historical_validation.py`

---

### Task 2.10: Phase 2 Documentation

**Priority**: P2 (Medium)  
**Effort**: 3 hours  
**Dependencies**: Task 2.9

**Description**: Document Phase 2 implementation.

**Acceptance Criteria**:
- [~] Update README.md with Phase 2 status
- [~] Document MAD detector configuration
- [~] Document coincidence logic
- [~] Document regime integration
- [~] Add performance benchmarks

**Files to Modify**:
- `services/layer2_anomaly/README.md`

---

## Phase 3: Advanced Detection (Week 3)

**Goal**: Add liquidity crisis detection  
**Estimated Effort**: 40 hours

### Task 3.1: Implement VolatilityRatioDetector

**Priority**: P0 (Blocker)  
**Effort**: 5 hours  
**Dependencies**: Phase 2 complete

**Description**: Detect regime shifts by comparing short-term vs long-term volatility.

**Acceptance Criteria**:
- [~] Create `detectors/volatility_ratio.py`
- [~] Maintain 30-tick and 300-tick return windows
- [~] Compute realized volatility for both windows
- [~] Compute ratio = rv_30 / rv_300
- [~] Score: 0.0 if ratio <2.0, 1.0 if ratio ≥3.0, linear between
- [~] Return warmup progress (0-300 ticks)
- [ ] Latency <0.5ms per tick
- [~] Add unit tests with synthetic volatility spikes

**Files to Create**:
- `services/layer2_anomaly/detectors/volatility_ratio.py`
- `services/layer2_anomaly/tests/test_volatility_ratio.py`

---

### Task 3.2: Implement CUSUMDetector with Composite Signal

**Priority**: P0 (Blocker)  
**Effort**: 6 hours  
**Dependencies**: Phase 2 complete

**Description**: Detect sustained drift across price, spread, and volume.

**Acceptance Criteria**:
- [~] Create `detectors/cusum.py`
- [~] Maintain history for price, spread, volume (1000 samples each)
- [~] Compute z-scores for each signal
- [~] Compute composite: 0.5*z_price + 0.3*z_spread + 0.2*z_volume
- [~] Update CUSUM statistics (positive and negative)
- [~] Score based on threshold (5σ)
- [~] Return warmup progress (0-30 ticks)
- [ ] Latency <0.5ms per tick
- [~] Add unit tests with sustained drift scenarios

**Files to Create**:
- `services/layer2_anomaly/detectors/cusum.py`
- `services/layer2_anomaly/tests/test_cusum.py`

---

### Task 3.3: Integrate VolatilityRatio and CUSUM

**Priority**: P0 (Blocker)  
**Effort**: 3 hours  
**Dependencies**: Tasks 3.1, 3.2

**Description**: Add new detectors to engine.

**Acceptance Criteria**:
- [~] Initialize VolatilityRatio and CUSUM detectors
- [~] Add to detector list for fusion
- [~] Update detector weights (add VolatilityRatio=0.15, CUSUM=0.10)
- [~] Rebalance existing weights if needed
- [~] Add integration tests

**Files to Modify**:
- `services/layer2_anomaly/engine.py`

---

### Task 3.4: Add Regime Shift Metrics

**Priority**: P1 (High)  
**Effort**: 2 hours  
**Dependencies**: Task 3.3

**Description**: Add metrics for regime shift detection.

**Acceptance Criteria**:
- [~] Add gauge `layer2_hmm_regime{symbol}`
- [~] Add gauge `layer2_regime_threshold_adjustment{symbol}`
- [~] Update metrics after HMM classification
- [~] Add unit tests

**Files to Modify**:
- `services/layer2_anomaly/metrics.py`
- `services/layer2_anomaly/engine.py`

---

### Task 3.5: Update Decision Gate with Regime Adjustment

**Priority**: P1 (High)  
**Effort**: 4 hours  
**Dependencies**: Task 3.4

**Description**: Implement regime-based threshold adjustment in Decision Gate.

**Acceptance Criteria**:
- [~] Add regime parameter to `DecisionGate.update()`
- [~] Compute regime_adjustment = -0.10 if regime==0 else 0.0
- [~] Apply adjustment to all anomaly thresholds
- [~] Add unit tests for regime-adjusted transitions
- [~] Verify hysteresis still works correctly

**Files to Modify**:
- `services/layer2_anomaly/engine.py` (DecisionGate class)

**Files to Create**:
- `services/layer2_anomaly/tests/test_decision_gate_regime.py`

---

### Task 3.6: Update Grafana Dashboard (Phase 3)

**Priority**: P1 (High)  
**Effort**: 3 hours  
**Dependencies**: Task 3.4

**Description**: Add Phase 3 metrics to dashboard.

**Acceptance Criteria**:
- [~] Add VolatilityRatio and CUSUM to detector scores panel
- [~] Add regime shift indicator panel
- [~] Add regime threshold adjustment panel
- [~] Update state timeline to show regime-adjusted thresholds
- [~] Test dashboard with regime changes

**Files to Modify**:
- `ops/grafana/provisioning/dashboards/layer2-anomaly-dashboard-v2.json`

---

### Task 3.7: Liquidity Crisis Simulation

**Priority**: P1 (High)  
**Effort**: 4 hours  
**Dependencies**: Task 3.3

**Description**: Test system with simulated liquidity crisis.

**Acceptance Criteria**:
- [~] Create synthetic data with gradual spread widening
- [~] Create synthetic data with volume decline
- [~] Run Phase 3 system on synthetic data
- [~] Verify CUSUM detects composite signal
- [~] Verify coincidence logic triggers (CUSUM + others)
- [~] Document detection latency

**Files to Create**:
- `services/layer2_anomaly/tests/test_liquidity_crisis.py`

---

### Task 3.8: Performance Testing (Phase 3)

**Priority**: P0 (Blocker)  
**Effort**: 4 hours  
**Dependencies**: Task 3.3

**Description**: Verify performance targets with 5 detectors.

**Acceptance Criteria**:
- [ ] Run performance tests with 10,000 ticks
- [~] Verify p50 latency <3ms
- [~] Verify p99 latency <4ms
- [ ] Verify memory usage <10MB per symbol
- [~] Profile and optimize if needed

**Files to Create**:
- `services/layer2_anomaly/tests/test_performance_phase3.py`

---

### Task 3.9: Configuration Management

**Priority**: P1 (High)  
**Effort**: 4 hours  
**Dependencies**: Task 3.3

**Description**: Externalize detector configurations to environment variables.

**Acceptance Criteria**:
- [~] Create `config.py` with Config class
- [~] Add environment variables for all detector thresholds
- [~] Add validation for all config values
- [~] Add fail-fast on invalid config
- [~] Update docker-compose.yml with env vars
- [~] Add unit tests for config validation

**Files to Create**:
- `services/layer2_anomaly/config.py`
- `services/layer2_anomaly/tests/test_config.py`

**Files to Modify**:
- `docker-compose.yml`

---

### Task 3.10: Phase 3 Documentation

**Priority**: P2 (Medium)  
**Effort**: 3 hours  
**Dependencies**: Task 3.9

**Description**: Document Phase 3 implementation.

**Acceptance Criteria**:
- [~] Update README.md with Phase 3 status
- [~] Document VolatilityRatio and CUSUM detectors
- [~] Document configuration options
- [~] Document regime adjustment logic
- [~] Add liquidity crisis detection guide

**Files to Modify**:
- `services/layer2_anomaly/README.md`

---

## Phase 4: Production Hardening (Week 4)

**Goal**: Complete detector stack and production tuning  
**Estimated Effort**: 40 hours

### Task 4.1: Implement EWMADetector (Price)

**Priority**: P0 (Blocker)  
**Effort**: 5 hours  
**Dependencies**: Phase 3 complete

**Description**: Detect small sustained shifts in price.

**Acceptance Criteria**:
- [~] Create `detectors/ewma.py`
- [~] Maintain history of price changes (1000 samples)
- [~] Compute running mean and std
- [~] Update EWMA statistic with λ=0.2
- [~] Compute control limits with L=3.0
- [~] Score based on distance from control limits
- [ ] Return warmup progress (0-30 ticks)
- [ ] Latency <0.5ms per tick
- [~] Add unit tests with sustained shifts

**Files to Create**:
- `services/layer2_anomaly/detectors/ewma.py`
- `services/layer2_anomaly/tests/test_ewma.py`

---

### Task 4.2: Implement EWMADetector (Spread)

**Priority**: P0 (Blocker)  
**Effort**: 3 hours  
**Dependencies**: Task 4.1

**Description**: Detect small sustained shifts in spread (reuse EWMA implementation).

**Acceptance Criteria**:
- [~] Instantiate second EWMA detector for spread
- [~] Configure to track spread_bps instead of price changes
- [~] Same parameters (λ=0.2, L=3.0)
- [~] Add unit tests for spread widening

**Files to Modify**:
- `services/layer2_anomaly/detectors/ewma.py` (make signal_name configurable)

**Files to Create**:
- `services/layer2_anomaly/tests/test_ewma_spread.py`

---

### Task 4.3: Integrate EWMA Detectors

**Priority**: P0 (Blocker)  
**Effort**: 3 hours  
**Dependencies**: Tasks 4.1, 4.2

**Description**: Add EWMA detectors to engine.

**Acceptance Criteria**:
- [~] Initialize EWMA_Price and EWMA_Spread detectors
- [ ] Add to detector list for fusion
- [~] Update detector weights (add EWMA_Price=0.05, EWMA_Spread=0.05)
- [~] Verify all weights sum to 1.0
- [ ] Add integration tests

**Files to Modify**:
- `services/layer2_anomaly/engine.py`

---

### Task 4.4: Add Warmup Progress Metrics

**Priority**: P1 (High)  
**Effort**: 3 hours  
**Dependencies**: Task 4.3

**Description**: Add metrics to track detector warmup status.

**Acceptance Criteria**:
- [~] Add gauge `layer2_detector_warmup_progress{symbol, detector}`
- [~] Update metric after each detector update
- [~] Add audit event `layer2.detector_ready` when warmup completes
- [ ] Add unit tests

**Files to Modify**:
- `services/layer2_anomaly/metrics.py`
- `services/layer2_anomaly/engine.py`

---

### Task 4.5: Add Regime Threshold Metrics

**Priority**: P1 (High)  
**Effort**: 2 hours  
**Dependencies**: Task 4.4

**Description**: Add metrics showing detector thresholds per regime.

**Acceptance Criteria**:
- [~] Add gauge `layer2_detector_threshold{symbol, detector, regime}`
- [~] Publish MAD thresholds for both regimes
- [~] Publish Decision Gate thresholds for both regimes
- [ ] Add unit tests

**Files to Modify**:
- `services/layer2_anomaly/metrics.py`

---

### Task 4.6: Complete Grafana Dashboard

**Priority**: P1 (High)  
**Effort**: 4 hours  
**Dependencies**: Tasks 4.4, 4.5

**Description**: Finalize dashboard with all panels.

**Acceptance Criteria**:
- [~] Add EWMA_Price and EWMA_Spread to detector scores panel
- [~] Add warmup progress gauge panel
- [~] Add regime threshold table panel
- [~] Add threshold lines to detector score time series
- [~] Polish layout and colors
- [~] Add panel descriptions
- [~] Test with all 7 detectors

**Files to Modify**:
- `ops/grafana/provisioning/dashboards/layer2-anomaly-dashboard-v2.json`

---

### Task 4.7: Implement Audit Logger

**Priority**: P1 (High)  
**Effort**: 4 hours  
**Dependencies**: Phase 3 complete

**Description**: Add audit trail for compliance.

**Acceptance Criteria**:
- [~] Create `audit.py` with AuditLogger class
- [~] Implement `log_state_transition()`
- [~] Implement `log_coincidence_trigger()`
- [~] Implement `log_flash_event()`
- [~] Implement `log_regime_change()`
- [~] Publish to Kafka topic `system.audit`
- [~] Add unit tests for all event types

**Files to Create**:
- `services/layer2_anomaly/audit.py`
- `services/layer2_anomaly/tests/test_audit.py`

---

### Task 4.8: Integrate Audit Logger

**Priority**: P1 (High)  
**Effort**: 3 hours  
**Dependencies**: Task 4.7

**Description**: Wire audit logger into engine.

**Acceptance Criteria**:
- [~] Initialize AuditLogger in engine
- [~] Log state transitions in Decision Gate
- [~] Log coincidence events in Fusion Engine
- [~] Log flash events in AbsoluteThreshold detector
- [~] Log regime changes in HMM classifier
- [ ] Add integration tests

**Files to Modify**:
- `services/layer2_anomaly/engine.py`
- `services/layer2_anomaly/fusion.py`
- `services/layer2_anomaly/detectors/absolute_threshold.py`

---

### Task 4.9: Implement Health Check Endpoint

**Priority**: P1 (High)  
**Effort**: 3 hours  
**Dependencies**: Phase 3 complete

**Description**: Add HTTP health check endpoint for monitoring.

**Acceptance Criteria**:
- [~] Create `health.py` with HTTP server
- [~] Implement `/health` endpoint
- [~] Return 200 OK when operational
- [~] Return 503 when unhealthy
- [~] Include detector readiness in response
- [~] Include Kafka connection status in response
- [~] Start server on port 8080
- [ ] Add unit tests

**Files to Create**:
- `services/layer2_anomaly/health.py`
- `services/layer2_anomaly/tests/test_health.py`

---

### Task 4.10: Performance Optimization

**Priority**: P0 (Blocker)  
**Effort**: 5 hours  
**Dependencies**: Task 4.3

**Description**: Optimize to meet <5ms p99 latency target.

**Acceptance Criteria**:
- [~] Profile with 10,000 ticks
- [~] Identify bottlenecks
- [~] Optimize median calculation in MAD (use approximate if needed)
- [~] Optimize rolling statistics (use O(1) updates)
- [~] Reuse numpy arrays where possible
- [~] Verify p50 <2ms, p99 <5ms
- [~] Document optimizations

**Files to Modify**:
- `services/layer2_anomaly/detectors/mad.py`
- `services/layer2_anomaly/detectors/cusum.py`
- `services/layer2_anomaly/detectors/ewma.py`

**Files to Create**:
- `services/layer2_anomaly/utils/rolling_stats.py` (optimized implementations)

---

### Task 4.11: Load Testing

**Priority**: P0 (Blocker)  
**Effort**: 4 hours  
**Dependencies**: Task 4.10

**Description**: Test system under production load.

**Acceptance Criteria**:
- [~] Test with 100 ticks/second for 10 minutes
- [ ] Test with 10 concurrent symbols
- [~] Verify no memory leaks
- [~] Verify no Kafka backlog
- [ ] Verify all metrics publishing correctly
- [~] Document results

**Files to Create**:
- `services/layer2_anomaly/tests/test_load.py`

---

### Task 4.12: Historical Data Validation (Full System)

**Priority**: P0 (Blocker)  
**Effort**: 5 hours  
**Dependencies**: Task 4.3

**Description**: Validate complete system against historical data.

**Acceptance Criteria**:
- [~] Load 30 days of historical data
- [~] Run complete system on historical data
- [~] Identify all known flash crashes (if any)
- [~] Measure false positive rate (manual labeling of 1000 samples)
- [~] Compare with Phase 2 results
- [~] Document improvements

**Files to Create**:
- `services/layer2_anomaly/tests/test_historical_full.py`

---

### Task 4.13: Create Migration Comparison Tool

**Priority**: P1 (High)  
**Effort**: 4 hours  
**Dependencies**: Task 4.12

**Description**: Build tool to compare old vs new system outputs.

**Acceptance Criteria**:
- [~] Create `tools/compare_systems.py`
- [~] Consume from both old and new Layer 2 topics
- [~] Compute score correlation
- [~] Compute latency comparison
- [~] Generate comparison report
- [~] Publish comparison metrics to Prometheus

**Files to Create**:
- `tools/compare_systems.py`
- `tools/README.md`

---

### Task 4.14: Complete Documentation

**Priority**: P1 (High)  
**Effort**: 6 hours  
**Dependencies**: All Phase 4 tasks

**Description**: Finalize all documentation.

**Acceptance Criteria**:
- [~] Update main README.md with complete system overview
- [~] Document all 7 detectors with formulas
- [~] Document all configuration options
- [~] Create operational runbook
- [~] Create troubleshooting guide
- [~] Create performance tuning guide
- [~] Create migration guide
- [~] Add architecture diagrams

**Files to Modify**:
- `services/layer2_anomaly/README.md`

**Files to Create**:
- `services/layer2_anomaly/docs/OPERATIONS.md`
- `services/layer2_anomaly/docs/TROUBLESHOOTING.md`
- `services/layer2_anomaly/docs/TUNING.md`
- `services/layer2_anomaly/docs/MIGRATION.md`

---

### Task 4.15: Final Integration Testing

**Priority**: P0 (Blocker)  
**Effort**: 4 hours  
**Dependencies**: All Phase 4 tasks

**Description**: End-to-end testing of complete system.

**Acceptance Criteria**:
- [~] Run all unit tests (>90% coverage)
- [~] Run all integration tests
- [~] Run all performance tests
- [~] Test with Docker Compose
- [~] Test Kafka integration
- [~] Test Prometheus metrics
- [~] Test Grafana dashboard
- [~] Test health check endpoint
- [~] Test audit events
- [~] Document any issues

**Files to Create**:
- `services/layer2_anomaly/tests/test_final_integration.py`

---

## Post-Implementation Tasks

### Task 5.1: Parallel Deployment Setup

**Priority**: P0 (Blocker)  
**Effort**: 4 hours  
**Dependencies**: Phase 4 complete

**Description**: Deploy new system alongside old system for validation.

**Acceptance Criteria**:
- [~] Update docker-compose.yml with both services
- [~] Configure new service to publish to `market.ticks.scored.v2`
- [~] Configure comparison tool to consume from both topics
- [~] Deploy to staging environment
- [~] Verify both systems running
- [~] Monitor for 24 hours

**Files to Modify**:
- `docker-compose.yml`

---

### Task 5.2: Validation Period (7 Days)

**Priority**: P0 (Blocker)  
**Effort**: Ongoing monitoring  
**Dependencies**: Task 5.1

**Description**: Monitor parallel deployment for 7 days.

**Acceptance Criteria**:
- [~] Monitor comparison metrics daily
- [~] Verify p99 latency <5ms consistently
- [~] Verify no crashes or errors
- [~] Verify score correlation >0.80
- [~] Verify false positive rate <5%
- [~] Verify flash crash detection on tick 1
- [~] Document any anomalies

---

### Task 5.3: Cutover to New System

**Priority**: P0 (Blocker)  
**Effort**: 2 hours  
**Dependencies**: Task 5.2 (success criteria met)

**Description**: Switch Layer 3 to consume from new Layer 2.

**Acceptance Criteria**:
- [~] Update Layer 3 to consume from `market.ticks.scored.v2`
- [~] Stop old Layer 2 service
- [~] Rename new topic to `market.ticks.scored`
- [~] Monitor for 1 hour
- [~] Verify Layer 3-6 functioning correctly
- [~] Document cutover

**Files to Modify**:
- `docker-compose.yml`
- Layer 3 service configuration

---

### Task 5.4: Rollback Procedure Documentation

**Priority**: P1 (High)  
**Effort**: 2 hours  
**Dependencies**: Task 5.3

**Description**: Document rollback procedure in case of issues.

**Acceptance Criteria**:
- [~] Document step-by-step rollback procedure
- [~] Document rollback triggers (when to rollback)
- [~] Document verification steps after rollback
- [~] Test rollback procedure in staging
- [~] Verify rollback time <5 minutes

**Files to Create**:
- `services/layer2_anomaly/docs/ROLLBACK.md`

---

### Task 5.5: Post-Deployment Monitoring

**Priority**: P1 (High)  
**Effort**: Ongoing  
**Dependencies**: Task 5.3

**Description**: Monitor production system for 30 days.

**Acceptance Criteria**:
- [~] Monitor all metrics daily
- [~] Review audit events weekly
- [~] Tune detector thresholds if needed
- [ ] Document any issues
- [~] Collect feedback from users

---

## Summary

### Effort Breakdown by Phase

| Phase | Tasks | Estimated Hours |
|-------|-------|-----------------|
| Phase 1: Foundation | 11 | 40 |
| Phase 2: Core Detection | 10 | 40 |
| Phase 3: Advanced Detection | 10 | 40 |
| Phase 4: Production Hardening | 15 | 40 |
| Post-Implementation | 5 | 8 |
| **TOTAL** | **51** | **168** |

### Critical Path

```
Phase 1 (Week 1)
├─ Task 1.1: Base Class (2h) [BLOCKER]
├─ Task 1.2: AbsoluteThreshold (4h) [BLOCKER]
├─ Task 1.3: TrustPassthrough (2h) [BLOCKER]
├─ Task 1.4: Fusion Engine (4h) [BLOCKER]
├─ Task 1.5: Kafka Integration (4h) [BLOCKER]
├─ Task 1.6: Metrics (4h)
├─ Task 1.7: Engine Integration (6h) [BLOCKER]
├─ Task 1.8: Grafana Dashboard (4h)
├─ Task 1.9: Docker (3h)
├─ Task 1.10: Testing (6h) [BLOCKER]
└─ Task 1.11: Documentation (3h)

Phase 2 (Week 2)
├─ Task 2.1: MAD Detector (6h) [BLOCKER]
├─ Task 2.2: HMM Regime (3h) [BLOCKER]
├─ Task 2.3: Fusion Coincidence (5h) [BLOCKER]
├─ Task 2.4: Coincidence Metrics (2h)
├─ Task 2.5: MAD Integration (4h) [BLOCKER]
├─ Task 2.6: Remove IF/HST (3h)
├─ Task 2.7: Grafana Update (3h)
├─ Task 2.8: Performance Testing (4h) [BLOCKER]
├─ Task 2.9: Historical Validation (5h)
└─ Task 2.10: Documentation (3h)

Phase 3 (Week 3)
├─ Task 3.1: VolatilityRatio (5h) [BLOCKER]
├─ Task 3.2: CUSUM (6h) [BLOCKER]
├─ Task 3.3: Integration (3h) [BLOCKER]
├─ Task 3.4: Regime Metrics (2h)
├─ Task 3.5: Decision Gate Regime (4h)
├─ Task 3.6: Grafana Update (3h)
├─ Task 3.7: Liquidity Crisis Test (4h)
├─ Task 3.8: Performance Testing (4h) [BLOCKER]
├─ Task 3.9: Configuration (4h)
└─ Task 3.10: Documentation (3h)

Phase 4 (Week 4)
├─ Task 4.1: EWMA Price (5h) [BLOCKER]
├─ Task 4.2: EWMA Spread (3h) [BLOCKER]
├─ Task 4.3: EWMA Integration (3h) [BLOCKER]
├─ Task 4.4: Warmup Metrics (3h)
├─ Task 4.5: Threshold Metrics (2h)
├─ Task 4.6: Complete Dashboard (4h)
├─ Task 4.7: Audit Logger (4h)
├─ Task 4.8: Audit Integration (3h)
├─ Task 4.9: Health Check (3h)
├─ Task 4.10: Optimization (5h) [BLOCKER]
├─ Task 4.11: Load Testing (4h) [BLOCKER]
├─ Task 4.12: Historical Validation (5h) [BLOCKER]
├─ Task 4.13: Comparison Tool (4h)
├─ Task 4.14: Documentation (6h)
└─ Task 4.15: Final Testing (4h) [BLOCKER]
```

### Success Criteria

**Phase 1 Success**:
- ✅ Flash crash detection on tick 1
- ✅ Latency <2ms per tick
- ✅ All metrics publishing

**Phase 2 Success**:
- ✅ MAD detector operational
- ✅ Coincidence logic working
- ✅ Latency <3ms per tick
- ✅ IF/HST removed

**Phase 3 Success**:
- ✅ Liquidity crisis detection
- ✅ Regime shift detection
- ✅ Latency <4ms per tick
- ✅ Configuration externalized

**Phase 4 Success**:
- ✅ All 7 detectors operational
- ✅ Latency <5ms per tick (p99)
- ✅ Complete observability
- ✅ Production-ready documentation
- ✅ Audit trail functional

**Production Cutover Criteria**:
- ✅ 7 days parallel deployment without issues
- ✅ Score correlation >0.80 with old system
- ✅ False positive rate <5%
- ✅ p99 latency <5ms consistently
- ✅ Flash crash detection verified

---

**Document Version**: 1.0  
**Last Updated**: 2026-05-26  
**Status**: Ready for Implementation

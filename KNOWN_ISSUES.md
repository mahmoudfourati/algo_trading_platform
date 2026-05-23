# Known Issues

**Last Updated:** 2026-05-23  
**Purpose:** Track known bugs, limitations, and technical debt separate from implementation status

---

## 🔴 Critical Issues (Fix Before Demo)

### 1. Primary Exchange Refactor Incomplete
**Status:** 🟡 In Progress  
**Severity:** High  
**Impact:** Code confusion, deprecated fields in schemas

**Description:**
The system is mid-refactor from primary-exchange-centric to consensus-centric pricing. Schemas have deprecated `primary_exchange` field but it's still used in some places.

**Evidence:**
- `shared/schemas.py`: `primary_exchange` marked deprecated
- `REFACTORING_STATUS.md`: Phase 1 incomplete
- Layer 5 execution divergence checking not implemented

**Fix Required:**
1. Complete Layer 5 execution divergence checking
2. Remove or document why `primary_exchange` must stay
3. Update all services to use consensus price consistently
4. Add tests for divergence checking

**Workaround:**
None — must be fixed

**Related Files:**
- `shared/schemas.py`
- `services/layer1_validated/service.py`
- `services/layer5_execution/engine.py`
- `REFACTORING_STATUS.md`

---

### 2. Layer 3 Signals Not Wired End-to-End in Backtest
**Status:** ❌ Not Fixed  
**Severity:** Critical  
**Impact:** Can't validate strategy logic in backtest

**Description:**
The backtest uses Layer 2 system state transitions as trade triggers instead of consuming actual `TradeSignal` objects from Layer 3. This means the dual-timeframe confluence, OFI gate, and signal strength logic are not exercised in backtest.

**Evidence:**
- `services/backtesting/engine.py`: Uses `system_state` transitions
- `IMPLEMENTATION_STATUS.md`: Listed as known limitation
- `project_analysis.md`: Identified as critical issue

**Fix Required:**
1. Update backtest to consume `TradeSignal` objects
2. Route signals through Layer 4 risk engine
3. Use approved orders for position entry/exit
4. Validate signal frequency matches expectations

**Workaround:**
Layer 3 service runs live and produces signals, but backtest doesn't use them

**Related Files:**
- `services/backtesting/engine.py`
- `services/layer3_strategy/service.py`
- `shared/schemas.py` (TradeSignal)

---

### 3. TLS Default Inconsistency
**Status:** ❌ Not Fixed  
**Severity:** Medium  
**Impact:** Security model inconsistency

**Description:**
`tls_ok` field in schemas defaults to `True` (optimistic), but `TlsHealthRegistry` uses pessimistic default (`False`). This contradicts the "pessimistic default" fix documented in `TRUST_SCORE_FIX_SUMMARY.md`.

**Evidence:**
- `shared/schemas.py`: `tls_ok: bool = True`
- `shared/tls_health_registry.py`: `return self._health.get(exchange_id, False)`
- `TRUST_SCORE_FIX_SUMMARY.md`: Documents pessimistic fix

**Fix Required:**
1. Change schema default to `tls_ok: bool = False`
2. Update adapters to explicitly set `tls_ok=True` after verification
3. Update tests to expect pessimistic default
4. Document why optimistic default was wrong

**Workaround:**
Adapters explicitly set `tls_ok` after verification, so runtime behavior is correct

**Related Files:**
- `shared/schemas.py`
- `shared/tls_health_registry.py`
- `services/layer1_ingestion/adapters/base.py`

---

### 4. No Resource Limits in Docker Compose
**Status:** ❌ Not Fixed  
**Severity:** Medium  
**Impact:** Risk of OOM kills during demo

**Description:**
Docker Compose services have no `mem_limit` or `cpus` constraints. One service could starve others during high load.

**Evidence:**
- `docker-compose.yml`: No resource limits defined
- `project_analysis.md`: Identified as critical issue

**Fix Required:**
1. Add `mem_limit` to all services (e.g., 512MB for Python services)
2. Add `cpus` limits (e.g., 1.0 for most services)
3. Test under load to verify limits are appropriate
4. Document resource requirements

**Workaround:**
Monitor `docker stats` during demo

**Related Files:**
- `docker-compose.yml`

---

### 5. Phase 10 Validation Incomplete
**Status:** ❌ Not Started  
**Severity:** High  
**Impact:** Can't claim statistical significance

**Description:**
Blueprint requires full 90-day walk-forward validation with 3+ OOS windows, 1000 permutations, and 5 attack scenarios. None of this has been run end-to-end.

**Evidence:**
- `IMPLEMENTATION_STATUS.md`: Phase 10 not complete
- No artifacts in `artifacts/reports/` for full validation

**Fix Required:**
1. Run full 90-day backtest with walk-forward
2. Implement exact timestamp-shuffle permutation test
3. Run all 5 attack scenarios with detection metrics
4. Run trust weight grid search calibration
5. Generate reproducible validation report

**Workaround:**
None — required for jury defense

**Related Files:**
- `services/backtesting/walk_forward.py`
- `services/backtesting/permutation_test.py`
- `services/backtesting/attack_scenarios.py`

---

## 🟡 Important Issues (Fix Soon)

### 6. Candle State Override Not Enforced
**Status:** ❌ Not Fixed  
**Severity:** Medium  
**Impact:** 50-unreliable-candle rule not working

**Description:**
`Candle` model has `system_state_override="DEGRADED"` field, but Layer 3 service doesn't enforce it at signal evaluation time. The 50-consecutive-unreliable-candle escalation rule is modeled but not integrated.

**Evidence:**
- `services/layer3_strategy/candles.py`: Sets override
- `services/layer3_strategy/service.py`: Doesn't check override
- `project_analysis.md`: Identified as behavioral gap

**Fix Required:**
1. Update signal evaluation to check candle override
2. Force DEGRADED state if override is set
3. Add test for 50-unreliable-candle escalation
4. Document override precedence rules

**Workaround:**
System still uses upstream tick state, which is usually correct

**Related Files:**
- `services/layer3_strategy/candles.py`
- `services/layer3_strategy/service.py`
- `services/layer3_strategy/signals.py`

---

### 7. Indicators Not Validated Against TA-Lib
**Status:** ❌ Not Done  
**Severity:** Medium  
**Impact:** Can't prove indicator correctness

**Description:**
Blueprint requires validating custom indicators against TA-Lib on a known dataset. This hasn't been done.

**Evidence:**
- `plan.md`: "Validate against TA-Lib on a known dataset as an oracle"
- No test files comparing against TA-Lib
- `project_analysis.md`: Identified as missing

**Fix Required:**
1. Install TA-Lib in test environment
2. Create test dataset (e.g., 1000 candles)
3. Compute RSI, MACD, Bollinger, EMA, ATR with both implementations
4. Assert values match within tolerance (e.g., 0.01%)
5. Document any intentional differences

**Workaround:**
Indicators are implemented from first principles and tested with synthetic data

**Related Files:**
- `services/layer3_strategy/indicators.py`
- `tests/test_layer3_indicators.py`

---

### 8. Risk State Not Persisted
**Status:** ❌ Not Fixed  
**Severity:** Medium  
**Impact:** Risk state lost on restart

**Description:**
Layer 4 risk engine keeps state in memory only (consecutive losses, daily P&L, peak equity). If service restarts, it forgets this state.

**Evidence:**
- `services/layer4_risk/engine.py`: In-memory `RiskState`
- `project_analysis.md`: Identified as issue

**Fix Required:**
1. Add SQLite persistence like Layer 5 execution
2. Save risk state on every update
3. Load risk state on startup
4. Add tests for persistence

**Workaround:**
Don't restart Layer 4 during trading session

**Related Files:**
- `services/layer4_risk/engine.py`
- `services/layer5_execution/persistence.py` (reference)

---

### 9. Execution Divergence Checking Not Implemented
**Status:** ❌ Not Fixed  
**Severity:** Medium  
**Impact:** Can't detect execution venue price manipulation

**Description:**
`ValidatedTick` has `execution_venue_prices` dict for divergence checking, but Layer 5 execution engine doesn't use it before placing orders.

**Evidence:**
- `shared/schemas.py`: `execution_venue_prices` field exists
- `services/layer5_execution/engine.py`: Doesn't check divergence
- `REFACTORING_STATUS.md`: Phase 1 incomplete

**Fix Required:**
1. Extract `execution_venue_prices` from approved order
2. Check if execution venue price diverges >0.5% from consensus
3. Reject order if divergence detected
4. Add Prometheus metric for divergence rejections
5. Add test for divergence rejection

**Workaround:**
System uses consensus price, which is already validated

**Related Files:**
- `services/layer5_execution/engine.py`
- `services/layer5_execution/service.py`
- `shared/schemas.py`

---

### 10. Audit Log Not Tested End-to-End
**Status:** ❌ Not Tested  
**Severity:** Medium  
**Impact:** Can't prove tamper-evidence

**Description:**
Layer 6 audit service is deployed but has no end-to-end tests. Chain integrity, rotation, and corruption detection are not validated.

**Evidence:**
- `services/layer6_audit/service.py` exists
- No `tests/test_layer6_audit.py`
- `IMPLEMENTATION_STATUS.md`: "deployed but not validated"

**Fix Required:**
1. Create `tests/test_layer6_audit.py`
2. Test chain integrity verification
3. Test rotation and cross-file continuity
4. Test corruption detection
5. Test 60-second verifier

**Workaround:**
Service is running and logging, but integrity not proven

**Related Files:**
- `services/layer6_audit/service.py`
- `tests/` (missing test file)

---

## 🟢 Nice to Have (If Time Permits)

### 11. Layer 1 Services Not Merged
**Status:** ❌ Not Done  
**Severity:** Low  
**Impact:** 5-10ms extra latency

**Description:**
Layer 1 is split into `layer1-ingestion` and `layer1-validated` with a Kafka hop between them. Could be merged into one service with in-memory queue.

**Evidence:**
- `docker-compose.yml`: Two separate services
- `services/layer1/in_memory_queue.py`: Started but not wired
- `project_analysis.md`: Suggested improvement

**Fix Required:**
1. Complete `services/layer1/service.py` (merged service)
2. Wire in-memory queue between adapters and consensus
3. Update docker-compose to single service
4. Test latency improvement

**Workaround:**
5-10ms latency is acceptable for day/swing trading

**Related Files:**
- `services/layer1/in_memory_queue.py`
- `docker-compose.yml`

---

### 12. No Grafana Alerting Rules
**Status:** ❌ Not Done  
**Severity:** Low  
**Impact:** No automated alerts

**Description:**
Prometheus scrapes metrics but has no alerting rules. Grafana has no alerts configured.

**Evidence:**
- `ops/prometheus/prometheus.yml`: No alert rules
- `ops/grafana/`: No alert provisioning

**Fix Required:**
1. Add Prometheus alert rules (HALT state, high anomaly, circuit breaker)
2. Add Grafana alert provisioning
3. Configure alert channels (email, Slack, etc.)
4. Test alerts trigger correctly

**Workaround:**
Monitor dashboards manually

**Related Files:**
- `ops/prometheus/prometheus.yml`
- `ops/prometheus/alerts/` (could create)

---

### 13. No Audit Log Query API
**Status:** ❌ Not Done  
**Severity:** Low  
**Impact:** Audit log is write-only

**Description:**
Audit log can only be written, not queried. No API to search by timestamp, event type, or layer.

**Evidence:**
- `services/layer6_audit/service.py`: Write-only
- No query endpoints

**Fix Required:**
1. Add FastAPI endpoints to Layer 6 service
2. Implement query by timestamp range
3. Implement query by event type
4. Implement query by source layer
5. Add pagination

**Workaround:**
Read log files directly with `grep` or text editor

**Related Files:**
- `services/layer6_audit/service.py`

---

### 14. No Backtest Comparison Tool
**Status:** ❌ Not Done  
**Severity:** Low  
**Impact:** Hard to compare runs

**Description:**
No tool to compare two backtest runs side-by-side (metrics, equity curves, parameters).

**Evidence:**
- No comparison script in `scripts/` or `tools/`

**Fix Required:**
1. Create `scripts/compare_backtests.py`
2. Load two run directories
3. Compare metrics (Sharpe, drawdown, win rate)
4. Plot equity curves side-by-side
5. Highlight parameter differences

**Workaround:**
Manually compare metrics.json files

**Related Files:**
- `scripts/` (missing tool)
- `services/backtesting/results_db.py` (could query)

---

### 15. No Monte Carlo Simulation
**Status:** ❌ Not Done  
**Severity:** Low  
**Impact:** No confidence intervals on results

**Description:**
Backtest produces point estimates (Sharpe, drawdown) but no confidence intervals. Monte Carlo simulation could bootstrap equity curve to estimate uncertainty.

**Evidence:**
- No Monte Carlo code in `services/backtesting/`

**Fix Required:**
1. Create `services/backtesting/monte_carlo.py`
2. Bootstrap equity curve (resample with replacement)
3. Compute 1000 bootstrap samples
4. Calculate 95% confidence intervals
5. Add to HTML report

**Workaround:**
Use permutation test p-value as significance measure

**Related Files:**
- `services/backtesting/` (missing module)

---

## Issue Summary by Severity

| Severity | Count | Status |
|----------|-------|--------|
| 🔴 Critical | 5 | 0 fixed, 5 open |
| 🟡 Important | 5 | 0 fixed, 5 open |
| 🟢 Nice to Have | 5 | 0 fixed, 5 open |
| **Total** | **15** | **0 fixed, 15 open** |

---

## Issue Summary by Category

| Category | Count |
|----------|-------|
| Architecture | 3 |
| Integration | 3 |
| Testing | 3 |
| Configuration | 2 |
| Validation | 2 |
| Observability | 2 |

---

## Priority Fix Order

### This Week (Before Demo)
1. ✅ Create documentation (this file, IMPLEMENTATION_STATUS, BLUEPRINT_DEVIATIONS, DEMO_SCRIPT, JURY_DEFENSE_PREP)
2. Fix TLS default inconsistency (#3)
3. Add resource limits to docker-compose (#4)
4. Complete primary exchange refactor (#1) OR revert it
5. Wire Layer 3 signals into backtest (#2)

### Next Week
6. Add execution divergence checking (#9)
7. Add risk state persistence (#8)
8. Validate indicators against TA-Lib (#7)
9. Fix candle state override enforcement (#6)
10. Add audit log tests (#10)

### If Time Permits
11. Run full Phase 10 validation (#5)
12. Merge Layer 1 services (#11)
13. Add Grafana alerting (#12)
14. Add audit query API (#13)
15. Add backtest comparison tool (#14)

---

## References

- **Implementation Status:** `IMPLEMENTATION_STATUS.md`
- **Blueprint Deviations:** `BLUEPRINT_DEVIATIONS.md`
- **Analysis:** `project_analysis.md`
- **Refactoring Status:** `REFACTORING_STATUS.md`

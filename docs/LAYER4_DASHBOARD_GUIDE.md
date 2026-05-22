# Layer 4 Risk Management Dashboard Guide

**Dashboard**: Layer 4 - Risk Management  
**UID**: `layer4-risk`  
**Created**: May 13, 2026

---

## 🚀 Quick Access

**URL**: http://localhost:3000/d/layer4-risk/layer4-risk-management

**Path in Grafana**:
1. Open http://localhost:3000
2. Login with `admin` / `admin`
3. Click **Dashboards** (left sidebar)
4. Search for "Layer 4" or "Risk Management"

---

## 🎯 Purpose

Layer 4 is the **Risk Management** layer that acts as the final gatekeeper before orders are sent to execution. It:
- Evaluates every trading signal from Layer 3
- Checks portfolio risk limits
- Monitors drawdown and exposure
- Activates circuit breakers when risk thresholds are exceeded
- Approves or rejects trades based on risk rules

**Key Principle**: Layer 4 can only **reject** trades, never create them. It's a pure risk filter.

---

## 📊 Dashboard Sections

### Section 1: Critical Status

#### F1: CIRCUIT BREAKER STATE (CRITICAL ALERT)
**Most Important Panel on Dashboard**

**States:**
- **NORMAL** (Green) - Trading allowed, all risk checks active
- **⚠️ CIRCUIT BREAKER ACTIVE** (Red) - **TRADING HALTED**

**When Circuit Breaker Activates:**
- All incoming signals are automatically rejected
- No new positions can be opened
- Existing positions may be closed (depending on configuration)
- Manual intervention required to reset

**Triggers:**
- Drawdown exceeds maximum threshold (e.g., -15%)
- Daily loss exceeds limit (e.g., -10%)
- Consecutive losses exceed threshold (e.g., 10 losses)
- Trust score drops below minimum (e.g., < 0.5)
- Manual activation by operator

#### Service Health
Shows if Layer 4 service is running:
- **1** = Healthy and processing
- **0** = Service down or crashed

#### Signal Consumption Rate
Real-time rate of trading signals being received from Layer 3.
- **Expected**: 0 ops/sec (Layer 3 is only generating HOLD signals currently)
- **When active**: Will show rate when Layer 3 publishes LONG/SHORT signals

---

### Section 2: Portfolio Risk Metrics

#### F2: Current Drawdown
**Definition**: Percentage decline from peak portfolio value

**Thresholds:**
- **Green (0%)**: At peak, no drawdown
- **Yellow (-5%)**: Minor drawdown, normal trading
- **Orange (-10%)**: Moderate drawdown, increased caution
- **Red (-15%)**: Severe drawdown, approaching circuit breaker

**Risk Limits** (typical):
- Warning: -10%
- Circuit Breaker: -15%

#### F3: Daily Loss
**Definition**: Percentage loss from start-of-day equity

**Thresholds:**
- **Green (0%)**: No daily loss
- **Yellow (-2%)**: Minor daily loss
- **Orange (-5%)**: Moderate daily loss
- **Red (-8%)**: Severe daily loss, approaching limit

**Risk Limits** (typical):
- Warning: -5%
- Circuit Breaker: -10%

#### F4: Consecutive Losses
**Definition**: Number of losing trades in a row

**Thresholds:**
- **Green (0-2)**: Normal variance
- **Yellow (3-4)**: Elevated risk
- **Orange (5-6)**: High risk, strategy may be failing
- **Red (7+)**: Critical, approaching circuit breaker

**Risk Limits** (typical):
- Warning: 5 consecutive losses
- Circuit Breaker: 10 consecutive losses

#### Drawdown History
Time series showing drawdown over time. Helps identify:
- Drawdown trends
- Recovery patterns
- Maximum drawdown periods

#### F5: Exposure Percentage
**Definition**: Percentage of portfolio currently at risk in open positions

**Thresholds:**
- **Green (0-50%)**: Conservative exposure
- **Yellow (50-70%)**: Moderate exposure
- **Orange (70-90%)**: High exposure
- **Red (90-100%)**: Maximum exposure

**Risk Limits** (typical):
- Maximum exposure: 80%
- Per-trade limit: 10%

---

### Section 3: Signal Processing & Approvals

#### Total Signals Received
Cumulative count of trading signals received from Layer 3.
- **Expected**: 0 (Layer 3 not publishing signals yet)
- **When active**: Will increment with each LONG/SHORT signal

#### Total Approvals
Cumulative count of signals that passed all risk checks.
- Shows how many trades were approved for execution
- **Approval Rate** = Approvals / Signals Received

#### Total Rejections
Cumulative count of signals that failed risk checks.
- **Rejection Rate** = Rejections / Signals Received
- High rejection rate indicates:
  - Risk limits are being hit
  - Strategy is too aggressive
  - Market conditions are unfavorable

#### Signal Processing Rate
Real-time rate of:
- **Signals In/sec**: Incoming from Layer 3
- **Approvals/sec**: Passing risk checks

#### Rejections by Reason
Breakdown of why trades were rejected:
- **drawdown_limit**: Drawdown too high
- **daily_loss_limit**: Daily loss exceeded
- **exposure_limit**: Portfolio exposure too high
- **consecutive_losses**: Too many losses in a row
- **trust_floor**: Trust score too low
- **circuit_breaker**: Circuit breaker active

**Use this to identify**:
- Which risk limit is most restrictive
- Whether limits need adjustment
- If strategy needs modification

---

### Section 4: Risk Limit Violations

#### Exposure Limit Violations
Count of times portfolio exposure exceeded limits.
- **Green (0)**: No violations
- **Yellow (1-4)**: Occasional violations
- **Red (5+)**: Frequent violations, limits may be too tight

#### Drawdown Limit Violations
Count of times drawdown exceeded warning threshold.
- Indicates how often portfolio is under stress
- Frequent violations suggest strategy needs adjustment

#### Trust Floor Violations
Count of times trust score dropped below minimum.
- Indicates data quality issues
- May trigger conservative trading mode or rejections

---

### Section 5: Performance Metrics

#### Risk Check Latency
Time taken to evaluate each signal:
- **P50 (Median)**: Typical processing time
- **P95**: 95% of checks complete within this time
- **P99**: 99% of checks complete within this time

**Thresholds:**
- **Green (< 5ms)**: Excellent performance
- **Yellow (5-10ms)**: Good performance
- **Orange (10-20ms)**: Acceptable performance
- **Red (> 20ms)**: Slow, may cause delays

**Target**: < 10ms P95 for real-time trading

#### Current Risk Check Latency (P95)
Gauge showing current P95 latency.
- Real-time indicator of system performance
- Spikes may indicate:
  - High CPU load
  - Database contention
  - Network issues

---

## 🚨 Alert Conditions

### Critical Alerts (Immediate Action Required)

1. **Circuit Breaker Active**
   - **Severity**: CRITICAL
   - **Action**: Investigate cause, review positions, manual reset required
   - **Annotation**: Red marker on timeline

2. **Service Health = 0**
   - **Severity**: CRITICAL
   - **Action**: Check logs, restart service if needed

3. **Drawdown > -15%**
   - **Severity**: CRITICAL
   - **Action**: Review strategy, consider reducing exposure

### Warning Alerts (Monitor Closely)

1. **Drawdown > -10%**
   - **Severity**: WARNING
   - **Action**: Increase monitoring, prepare for circuit breaker

2. **Daily Loss > -5%**
   - **Severity**: WARNING
   - **Action**: Review today's trades, check for anomalies

3. **Consecutive Losses > 5**
   - **Severity**: WARNING
   - **Action**: Strategy may be failing, consider manual intervention

4. **High Rejection Rate (> 50%)**
   - **Severity**: WARNING
   - **Action**: Risk limits may be too tight, or strategy too aggressive

---

## 📈 Normal Operating Conditions

### Healthy System Indicators:
- ✅ Circuit Breaker = NORMAL (green)
- ✅ Service Health = 1
- ✅ Drawdown = 0% or small negative
- ✅ Daily Loss = 0% or small negative
- ✅ Consecutive Losses = 0-2
- ✅ Risk Check Latency < 10ms P95
- ✅ No limit violations

### Expected When No Trading:
- ⚠️ Signals Received = 0 (Layer 3 not publishing)
- ⚠️ Approvals = 0 (no signals to approve)
- ⚠️ Rejections = 0 (no signals to reject)
- ⚠️ Signal rate = 0 ops/sec

**This is normal!** Layer 4 is waiting for Layer 3 to generate actionable signals.

---

## 🔍 Troubleshooting

### Dashboard shows "No data"
1. Check time range (use "Last 15 minutes")
2. Verify Layer 4 is running: `docker compose ps layer4-risk`
3. Check Prometheus: http://localhost:9090/targets
4. Verify metrics: http://localhost:9105/metrics

### Circuit Breaker won't reset
1. Check logs: `docker compose logs layer4-risk --tail 100`
2. Verify risk conditions have improved
3. May require service restart or manual reset

### High rejection rate
**Possible causes:**
- Risk limits too conservative
- Strategy generating too many signals
- Market conditions unfavorable
- Trust scores too low

**Actions:**
- Review rejection reasons
- Adjust risk limits if appropriate
- Evaluate strategy performance

### Latency spikes
**Possible causes:**
- High CPU load
- Database slow queries
- Network issues
- Too many concurrent checks

**Actions:**
- Check system resources
- Review database performance
- Scale horizontally if needed

---

## 🎛️ Risk Configuration

### Default Risk Limits (Typical):

**Drawdown Limits:**
- Warning: -10%
- Circuit Breaker: -15%

**Daily Loss Limits:**
- Warning: -5%
- Circuit Breaker: -10%

**Exposure Limits:**
- Maximum portfolio exposure: 80%
- Maximum per-trade: 10%

**Consecutive Loss Limits:**
- Warning: 5 losses
- Circuit Breaker: 10 losses

**Trust Floor:**
- Minimum trust score: 0.5
- Conservative mode: 0.7

**Note**: Actual limits are configured in the Layer 4 service code and may differ.

---

## 📚 Related Documentation

- **Service Implementation**: `services/layer4_risk/service.py`
- **Risk Rules**: Check service code for current limits
- **Layer 3 Dashboard**: For signal generation metrics
- **Layer 5 Dashboard**: For execution metrics
- **Deep Observability**: For system-wide view

---

## 🎨 Dashboard Customization

### Adding Custom Alerts
Use Grafana alerting to notify on:
- Circuit breaker activation
- Drawdown thresholds
- High rejection rates
- Latency spikes

### Adjusting Thresholds
Modify gauge thresholds to match your risk tolerance:
- Edit panel → Field → Thresholds
- Adjust values and colors

### Time Range
- Default: Last 15 minutes
- For risk analysis: Last 1 hour or 1 day
- For real-time monitoring: Last 5 minutes

---

## 🔐 Risk Management Best Practices

1. **Monitor Circuit Breaker**: Most critical indicator
2. **Set Conservative Limits**: Better to miss trades than blow up account
3. **Review Rejections**: Understand why trades are being blocked
4. **Track Drawdown**: Know your maximum acceptable loss
5. **Test Limits**: Backtest with historical data before going live
6. **Have Manual Override**: Ability to halt trading immediately
7. **Log Everything**: Audit trail for all risk decisions
8. **Regular Review**: Adjust limits based on strategy performance

---

**Dashboard Status**: ✅ Active and monitoring  
**Data Flow**: Layer 3 → Layer 4 → Prometheus → Grafana  
**Update Frequency**: Real-time (5s refresh)

**Trade Safely! 🛡️📊**

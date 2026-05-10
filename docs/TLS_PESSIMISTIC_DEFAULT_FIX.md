# TLS Pessimistic Default Fix

**Date:** 2026-05-09  
**Issue:** Trust score not degrading with empty TLS pins  
**Root Cause:** Optimistic default in TLS health registry  
**Fix:** Changed to pessimistic default (security-first)

---

## Problem

When `config/tls_pins.json` is empty or missing, the trust score should degrade because TLS verification cannot be performed. However, the trust score was remaining high (~0.76-0.78) instead of dropping.

### Root Cause

The `TlsHealthRegistry.is_healthy()` method had an **optimistic default**:

```python
def is_healthy(self, exchange_id: str) -> bool:
    with self._lock:
        return self._health.get(exchange_id, True)  # ← Optimistic: defaults to True
```

This meant:
- Empty registry → all exchanges default to **healthy**
- Empty pins file → adapters can't verify TLS → but registry still shows healthy
- Result: T1 = 1.0 → trust score remains high

---

## Solution

Changed to **pessimistic default** (security-first):

```python
def is_healthy(self, exchange_id: str) -> bool:
    with self._lock:
        return self._health.get(exchange_id, False)  # ← Pessimistic: defaults to False
```

Now:
- Empty registry → all exchanges default to **unhealthy**
- Empty pins file → TLS verification fails → T1 = 0.0
- Result: Trust score drops by ~0.20 (T1 weight)

---

## Behavior Comparison

### Before Fix (Optimistic Default)

| Condition | Registry State | `is_healthy()` | T1 | Trust Score |
|-----------|----------------|----------------|-----|-------------|
| Empty pins, no checks | `{}` | `True` | 1.0 | ~0.76 |
| Empty pins, after check | `{"binance": False}` | `False` | 0.0 | ~0.56 |

**Problem:** Trust score high until adapters reconnect and perform checks.

### After Fix (Pessimistic Default)

| Condition | Registry State | `is_healthy()` | T1 | Trust Score |
|-----------|----------------|----------------|-----|-------------|
| Empty pins, no checks | `{}` | `False` | 0.0 | ~0.56 |
| Valid pins, after check | `{"binance": True}` | `True` | 1.0 | ~0.76 |

**Benefit:** Trust score immediately reflects missing/invalid pins.

---

## Test Results

Run `python test_tls_trust_degradation.py` to verify:

```
TLS Pin Verification:
  Binance: success=False, reason=no_pins_file_or_empty

TLS Health Registry State:
  Binance healthy: False
  Coinbase healthy: False
  Kraken healthy: False
  OKX healthy: False
  Bybit healthy: False

Scenario 1: TLS Healthy (valid pins)
  T1 (TLS): 1.000
  → Trust Score: 0.710

Scenario 2: TLS Unhealthy (empty/missing pins)
  T1 (TLS): 0.000
  → Trust Score: 0.510

Trust Score Degradation: 0.200 (28.2%)
```

---

## Impact

### Security

✅ **Improved:** Empty/missing pins immediately degrade trust (fail-secure)  
✅ **Improved:** No silent bypass of TLS verification  
✅ **Improved:** Explicit verification required before marking healthy

### Operations

✅ **No breaking changes:** Adapters already mark exchanges healthy on successful verification  
✅ **No performance impact:** Registry operations remain O(1)  
✅ **Better observability:** Trust score accurately reflects TLS state from startup

### Backtest

✅ **No impact:** Backtests explicitly set `tls_ok=True` in scoring calls

---

## Migration

**No action required.** The fix is backward-compatible:

1. Existing deployments with valid pins: Adapters mark exchanges healthy on connect → no change
2. Deployments with empty/invalid pins: Trust score now correctly degrades → expected behavior
3. Backtests: Explicitly pass `tls_ok=True` → no change

---

## Verification

### Check Registry Default

```powershell
python -c "from shared.tls_health_registry import get_tls_health_registry; reg = get_tls_health_registry(); print('Binance healthy:', reg.is_healthy('binance'))"
```

**Expected output:** `Binance healthy: False` (before any checks)

### Check TLS Verification

```powershell
python -c "from shared.tls_pinning import verify_spki_pin; from pathlib import Path; success, reason = verify_spki_pin(exchange_id='binance', pins_path=Path('config/tls_pins.json')); print(f'success={success}, reason={reason}')"
```

**Expected output (empty pins):** `success=False, reason=no_pins_file_or_empty`

### Check Trust Score

```powershell
python test_tls_trust_degradation.py
```

**Expected:** Trust score drops by ~0.20 when `tls_ok=False`

---

## Files Changed

1. `shared/tls_health_registry.py` — Changed default from `True` to `False`
2. `docs/TLS_REFACTOR_SUMMARY.md` — Updated documentation
3. `docs/TLS_QUICK_REFERENCE.md` — Clarified empty pins behavior
4. `test_tls_trust_degradation.py` — **NEW** test script

---

## Rationale

### Why Pessimistic?

**Security-first design:**
- TLS verification is a security control
- Missing/invalid pins should be treated as a failure, not a pass
- Explicit verification required before trusting an exchange

**Operational clarity:**
- Trust score immediately reflects configuration state
- No silent bypass of security checks
- Easier to diagnose issues (low trust score → check TLS pins)

### Why Not Optimistic?

**Optimistic default creates security gaps:**
- Empty pins → silent pass → false sense of security
- Delayed detection (only after adapter reconnect)
- Violates principle of least privilege

---

## Related Documentation

- `docs/TLS_REFACTOR_SUMMARY.md` — Complete technical summary
- `docs/TLS_REFACTOR_MIGRATION.md` — Migration guide
- `docs/TLS_QUICK_REFERENCE.md` — Operator reference
- `test_tls_trust_degradation.py` — Test script

---

**Fix Status:** ✅ Complete  
**Testing:** ✅ Verified  
**Documentation:** ✅ Updated  
**Deployment:** Ready for production


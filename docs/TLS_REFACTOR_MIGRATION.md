# TLS Trust Architecture Refactor — Migration Guide

**Date:** 2026-05-09  
**Status:** Production-Ready  
**Breaking Changes:** Config format, trust weights

---

## Executive Summary

The Layer 1 TLS trust architecture has been redesigned for production resilience:

- **SPKI pinning** replaces leaf certificate fingerprints (survives cert renewals)
- **Non-fatal TLS failures** — mismatches degrade trust instead of crashing services
- **Exchange availability scoring** — missing exchanges now penalize trust
- **Thread-safe health registry** — cached TLS state, no blocking on hot path
- **Full Kafka pipeline continuity** — services never stop during TLS failures

---

## What Changed

### 1. SPKI Pinning (Public Key Pinning)

**Before:**
```json
{
  "binance": {
    "host": "stream.binance.com",
    "port": 9443,
    "sha256_fingerprint": "abc123..."  // Full leaf cert hash
  }
}
```

**After:**
```json
{
  "binance": {
    "host": "stream.binance.com",
    "port": 9443,
    "spki_sha256": "def456..."  // Public key hash only
  }
}
```

**Why:** SPKI pins hash the SubjectPublicKeyInfo (public key) instead of the full certificate. When an exchange renews its certificate with the same key pair, the SPKI hash remains valid. This eliminates operational fragility from certificate rotations.

---

### 2. Non-Fatal TLS Failures

**Before:**
- TLS mismatch → `TlsPinningError` raised → adapter crashes → Kafka stops → pipeline halts

**After:**
- TLS mismatch → audit event emitted → trust score degraded → **pipeline continues**

**Implementation:**
```python
# Old (fatal)
verify_pin_or_raise(exchange_id=exchange_id, pins_path=pins_path)

# New (non-fatal)
tls_success, tls_reason = verify_spki_pin(
    exchange_id=exchange_id,
    pins_path=pins_path,
    timeout=5.0
)
if tls_success:
    registry.mark_healthy(exchange_id)
else:
    registry.mark_unhealthy(exchange_id, reason=tls_reason)
    # Continue operating with degraded trust
```

---

### 3. TLS Health Registry

**New Component:** `shared/tls_health_registry.py`

Thread-safe, non-blocking, async-safe registry for tracking TLS health per exchange.

**API:**
```python
from shared.tls_health_registry import get_tls_health_registry

registry = get_tls_health_registry()

# Adapter marks health after pin check
registry.mark_healthy("binance")
registry.mark_unhealthy("coinbase", reason="spki_mismatch")

# Validated service reads cached state (no blocking)
tls_ok = registry.is_healthy("binance")  # True/False
```

**Design:**
- Global singleton with `threading.Lock`
- All operations O(1)
- Defaults to healthy (optimistic) for unknown exchanges
- No I/O in any method

---

### 4. Exchange Availability Scoring

**New Subscore:** `T_availability`

```
T_availability = active_exchanges / configured_exchanges
```

**Example:**
- Configured: `{binance, coinbase, kraken, okx, bybit}` (5 exchanges)
- Active in window: `{binance, coinbase, kraken}` (3 exchanges)
- `T_availability = 3/5 = 0.6`

**Impact:**
- Missing exchanges now reduce trust score
- Incentivizes multi-source resilience
- Penalizes single-exchange degradation

---

### 5. Updated Trust Weights

**Before:**
```json
{
  "w1_tls": 0.25,
  "w2_consensus": 0.30,
  "w3_freshness": 0.20,
  "w4_sequence": 0.15,
  "w5_hash_chain": 0.10
}
```

**After:**
```json
{
  "w1_tls": 0.20,
  "w2_consensus": 0.25,
  "w3_freshness": 0.20,
  "w4_sequence": 0.15,
  "w5_hash_chain": 0.10,
  "w_availability": 0.10
}
```

**Rationale:**
- Reduced T1 weight (0.25 → 0.20) to make TLS failures less catastrophic
- Reduced T2 weight (0.30 → 0.25) to balance with availability
- Added T_availability (0.10) to penalize missing exchanges
- Total still sums to 1.0

---

## Migration Steps

### Step 1: Install Dependencies

```powershell
.\.venv\Scripts\python -m pip install cryptography
```

SPKI pinning requires the `cryptography` library for parsing X.509 certificates.

---

### Step 2: Fetch SPKI Pins

```powershell
.\.venv\Scripts\python scripts\refresh_spki_pins.py
```

This connects to each exchange, extracts the public key, and writes SPKI hashes to `config/tls_pins.json`.

**Dry-run first (recommended):**
```powershell
.\.venv\Scripts\python scripts\refresh_spki_pins.py --dry-run
```

---

### Step 3: Update Trust Weights

The new `config/trust_weights.json` is already updated. If you have custom weights, add:

```json
{
  "w_availability": 0.10
}
```

And rebalance other weights to sum to 1.0.

---

### Step 4: Restart Services

```powershell
docker compose down
docker compose up -d --build
```

Or restart manually:
```powershell
# Ingestion
.\.venv\Scripts\python -m services.layer1_ingestion.run_console

# Validated
.\.venv\Scripts\python -m services.layer1_validated.service
```

---

### Step 5: Verify

Check Prometheus metrics:
- `tls_exchange_health{exchange_id="binance"}` should be `1.0`
- `unhealthy_exchange_count` should be `0`
- `availability_score` should be `1.0` (all exchanges active)
- `layer1_validated_last_trust_score` should be `~0.85-0.95`

Check audit events:
```powershell
docker compose logs layer1-ingestion | grep "adapter_tls_pin"
```

Expected:
```
adapter_tls_pin_verified: {"status": "ok"}
```

---

## Trust Score Behavior

### Before Refactor

| Scenario | T1 | T2 | T3 | T4 | T5 | Trust |
|----------|----|----|----|----|----|----|
| All healthy | 1.0 | 0.9 | 0.8 | 1.0 | 1.0 | **0.92** |
| TLS mismatch | **CRASH** | — | — | — | — | **N/A** |
| 1 exchange missing | 1.0 | 0.9 | 0.8 | 1.0 | 1.0 | **0.92** (no penalty) |

### After Refactor

| Scenario | T1 | T2 | T3 | T4 | T5 | T_avail | Trust |
|----------|----|----|----|----|----|---------|----|
| All healthy | 1.0 | 0.9 | 0.8 | 1.0 | 1.0 | 1.0 | **0.92** |
| TLS mismatch | 0.0 | 0.9 | 0.8 | 1.0 | 1.0 | 1.0 | **0.72** (degraded, not crashed) |
| 1 exchange missing | 1.0 | 0.9 | 0.8 | 1.0 | 1.0 | 0.8 | **0.90** (penalized) |
| 2 exchanges missing | 1.0 | 0.9 | 0.8 | 1.0 | 1.0 | 0.6 | **0.88** (more penalty) |

**Key Improvement:** TLS failures no longer crash the system — they degrade trust gracefully.

---

## Operational Benefits

### 1. Certificate Renewal Resilience

**Before:** Exchange renews certificate → SPKI changes → pin mismatch → **service crashes**

**After:** Exchange renews certificate with same key → SPKI unchanged → **no impact**

**When SPKI changes:** Exchange rotates key → SPKI mismatch → trust degrades to ~0.72 → **pipeline continues** → operator updates pin at leisure

---

### 2. Partial Exchange Failures

**Before:** Binance TLS fails → adapter crashes → **no ticks from any exchange**

**After:** Binance TLS fails → Binance trust = 0.0 → other 4 exchanges continue → trust score = ~0.88 → **pipeline fully operational**

---

### 3. Monitoring & Alerting

**New Prometheus Metrics:**
- `tls_exchange_health{exchange_id}` — per-exchange TLS health (1=healthy, 0=unhealthy)
- `unhealthy_exchange_count` — total unhealthy exchanges
- `availability_score{symbol}` — exchange availability ratio
- `tls_validation_failures_total{exchange_id}` — cumulative TLS failures

**Alert Rules (example):**
```yaml
- alert: ExchangeTLSUnhealthy
  expr: tls_exchange_health == 0
  for: 5m
  annotations:
    summary: "Exchange {{ $labels.exchange_id }} TLS unhealthy"

- alert: LowAvailability
  expr: availability_score < 0.8
  for: 10m
  annotations:
    summary: "Exchange availability below 80%"
```

---

## Backtest Compatibility

**No changes required.** Backtests bypass live TLS verification by default:

```python
# Backtest engine
subscores = compute_subscores(
    tls_ok=True,  # Optimistic default for replay
    t2=t2,
    latency_ms=latency_ms,
    sequence_gap=sequence_gap,
    chain_ok=chain_ok,
    active_exchanges=None,  # Availability scoring disabled in backtest
    configured_exchanges=None,
)
```

To test TLS failure scenarios in backtest, mock the registry:

```python
from shared.tls_health_registry import get_tls_health_registry

registry = get_tls_health_registry()
registry.mark_unhealthy("binance")  # Simulate TLS failure
```

---

## Files Modified

### Core Implementation
1. `shared/tls_pinning.py` — SPKI pinning, non-fatal verification
2. `shared/tls_health_registry.py` — **NEW** thread-safe health registry
3. `services/layer1_trust/scoring.py` — added `T_availability`, updated weights
4. `services/layer1_ingestion/adapters/base.py` — non-fatal TLS checks, registry integration
5. `services/layer1_validated/service.py` — registry reads, availability scoring, new metrics

### Configuration
6. `config/tls_pins.json` — `sha256_fingerprint` → `spki_sha256`
7. `config/trust_weights.json` — added `w_availability`

### Tooling
8. `scripts/refresh_spki_pins.py` — **NEW** SPKI pin fetcher
9. `scripts/refresh_tls_pins.py` — **DEPRECATED** (leaf cert pinning)

### Documentation
10. `docs/TLS_REFACTOR_MIGRATION.md` — **THIS FILE**

---

## Rollback Plan

If issues arise, rollback is straightforward:

1. Revert `config/tls_pins.json` to old format (`sha256_fingerprint`)
2. Revert `config/trust_weights.json` to old weights (remove `w_availability`)
3. Revert code changes via git:
   ```powershell
   git revert <commit-hash>
   ```
4. Restart services

**Note:** Old and new formats are **incompatible**. Do not mix.

---

## Testing Checklist

- [ ] SPKI pins fetched successfully for all 5 exchanges
- [ ] Services start without errors
- [ ] `tls_exchange_health` metrics show `1.0` for all exchanges
- [ ] Trust scores in range `0.85-0.95` under normal conditions
- [ ] Simulate TLS failure (wrong pin) → trust degrades to ~0.72, pipeline continues
- [ ] Simulate missing exchange → `availability_score` drops, trust penalized
- [ ] Audit events logged for TLS failures
- [ ] Backtests run without modification
- [ ] Prometheus alerts fire correctly

---

## FAQ

**Q: What if an exchange rotates its public key?**  
A: SPKI mismatch → trust degrades → audit event emitted → operator runs `refresh_spki_pins.py` → services auto-recover on next reconnect.

**Q: Can I disable TLS pinning entirely?**  
A: Not recommended. To bypass for testing, set empty `config/tls_pins.json`:
```json
{}
```
All exchanges will default to `tls_ok=True`.

**Q: How often should I refresh SPKI pins?**  
A: Only when:
1. Adding a new exchange
2. An exchange rotates its key (rare, ~1-2 years)
3. Audit event `adapter_tls_pin_failed` appears

**Q: What's the performance impact?**  
A: Negligible. TLS checks run once per reconnect (not per tick). Registry reads are O(1) with no I/O.

**Q: Does this work with custom exchanges?**  
A: Yes. Add to `config/tls_pins.json` and `scripts/refresh_spki_pins.py`.

---

## Support

For issues or questions:
1. Check Prometheus metrics: `tls_exchange_health`, `unhealthy_exchange_count`
2. Check audit logs: `docker compose logs | grep tls_pin`
3. Verify SPKI pins: `.\.venv\Scripts\python scripts\refresh_spki_pins.py --dry-run`
4. Review this migration guide

---

**End of Migration Guide**

# TLS Trust — Quick Reference Card

## Installation

```powershell
# Install cryptography library
.\.venv\Scripts\python -m pip install cryptography

# Fetch SPKI pins
.\.venv\Scripts\python scripts\refresh_spki_pins.py

# Restart services
docker compose down
docker compose up -d --build
```

---

## Key Metrics

```
# TLS health (1=healthy, 0=unhealthy)
tls_exchange_health{exchange_id="binance"}

# Total unhealthy exchanges
unhealthy_exchange_count

# Exchange availability (active/configured)
availability_score{symbol="BTC-USDT"}

# Trust score (includes all subscores)
layer1_validated_last_trust_score{symbol="BTC-USDT"}
```

---

## Expected Values

| Metric | Normal | Degraded | Action |
|--------|--------|----------|--------|
| `tls_exchange_health` | 1.0 | 0.0 | Check audit logs, refresh pins |
| `unhealthy_exchange_count` | 0 | >0 | Investigate unhealthy exchanges |
| `availability_score` | 1.0 | <0.8 | Check missing exchanges |
| `trust_score` | 0.85-0.95 | <0.75 | Review all subscores |

---

## Troubleshooting

### TLS Mismatch

**Symptom:** `tls_exchange_health{exchange_id="X"} = 0`

**Check:**
```powershell
docker compose logs layer1-ingestion | grep "adapter_tls_pin_failed"
```

**Fix:**
```powershell
.\.venv\Scripts\python scripts\refresh_spki_pins.py
docker compose restart layer1-ingestion
```

---

### Low Trust Score

**Symptom:** `trust_score < 0.75`

**Check subscores:**
```
layer1_validated_last_trust_score{symbol="BTC-USDT"}
```

**Investigate:**
- T1 = 0.0 → TLS failure (see above)
- T2 < 0.7 → Consensus issues (check divergent sources)
- T3 < 0.5 → High latency (check network)
- T4 < 0.8 → Sequence gaps (check exchange feed)
- T5 = 0.0 → Hash chain break (check logs)
- T_availability < 0.8 → Missing exchanges (check adapters)

---

### Missing Exchanges

**Symptom:** `availability_score < 1.0`

**Check:**
```powershell
docker compose logs layer1-ingestion | grep "adapter_disconnect"
```

**Common causes:**
- Network issues
- Exchange downtime
- TLS mismatch (see above)
- Configuration error

---

## Config Files

### `config/tls_pins.json`

```json
{
  "binance": {
    "host": "stream.binance.com",
    "port": 9443,
    "spki_sha256": "abc123..."
  }
}
```

**When to update:** Exchange rotates public key (rare, ~1-2 years)

---

### `config/trust_weights.json`

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

**When to update:** Custom trust policy requirements

---

## Audit Events

### Healthy

```json
{
  "event_type": "adapter_tls_pin_verified",
  "source": "binance",
  "payload": {"status": "ok"}
}
```

### Unhealthy

```json
{
  "event_type": "adapter_tls_pin_failed",
  "source": "coinbase",
  "payload": {
    "reason": "spki_mismatch",
    "action": "continuing_with_degraded_trust"
  }
}
```

---

## Emergency Procedures

### Empty TLS Pins (Testing Only)

```json
// config/tls_pins.json
{}
```

**Behavior:** All exchanges will be marked **unhealthy** (pessimistic default). Trust score will drop by ~0.20 (T1 weight). Pipeline continues operating with degraded trust.

**Use case:** Testing trust degradation behavior without network access.

**Production:** Always maintain valid SPKI pins.

---

### Force Refresh All Pins

```powershell
.\.venv\Scripts\python scripts\refresh_spki_pins.py
docker compose restart layer1-ingestion layer1-validated
```

---

### Check Pin Validity (Dry-Run)

```powershell
.\.venv\Scripts\python scripts\refresh_spki_pins.py --dry-run
```

---

## Contact

For issues:
1. Check metrics (Prometheus)
2. Check audit logs (`docker compose logs`)
3. Review migration guide (`docs/TLS_REFACTOR_MIGRATION.md`)
4. Review technical summary (`docs/TLS_REFACTOR_SUMMARY.md`)

---

**Quick Reference v1.0 — 2026-05-09**

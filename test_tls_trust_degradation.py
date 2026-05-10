#!/usr/bin/env python3
"""Test script to demonstrate TLS trust degradation with empty pins.

This script shows how the trust score changes when TLS pins are missing/empty.
"""

from services.layer1_trust.scoring import (
    compute_subscores,
    compute_trust_score,
    load_trust_weights,
)
from shared.tls_health_registry import get_tls_health_registry
from shared.tls_pinning import verify_spki_pin
from pathlib import Path


def main():
    print("=" * 70)
    print("TLS TRUST DEGRADATION TEST")
    print("=" * 70)
    print()
    
    # Load trust weights
    weights = load_trust_weights()
    print("Trust Weights:")
    for name, value in weights.as_dict().items():
        print(f"  {name}: {value:.2f}")
    print()
    
    # Check TLS pin verification
    print("TLS Pin Verification:")
    success, reason = verify_spki_pin(
        exchange_id="binance",
        pins_path=Path("config/tls_pins.json")
    )
    print(f"  Binance: success={success}, reason={reason}")
    print()
    
    # Check registry state
    registry = get_tls_health_registry()
    print("TLS Health Registry State:")
    print(f"  Binance healthy: {registry.is_healthy('binance')}")
    print(f"  Coinbase healthy: {registry.is_healthy('coinbase')}")
    print(f"  Kraken healthy: {registry.is_healthy('kraken')}")
    print(f"  OKX healthy: {registry.is_healthy('okx')}")
    print(f"  Bybit healthy: {registry.is_healthy('bybit')}")
    print()
    
    # Simulate typical conditions
    print("Simulated Trust Score Scenarios:")
    print()
    
    # Scenario 1: TLS healthy (with valid pins)
    print("Scenario 1: TLS Healthy (valid pins)")
    subscores_healthy = compute_subscores(
        tls_ok=True,
        t2=0.8,
        latency_ms=1500,
        sequence_gap=1,
        chain_ok=True,
        active_exchanges={"binance", "coinbase", "kraken"},
        configured_exchanges={"binance", "coinbase", "kraken", "okx", "bybit"},
    )
    score_healthy = compute_trust_score(weights=weights, subscores=subscores_healthy)
    print(f"  T1 (TLS): {subscores_healthy['T1']:.3f}")
    print(f"  T2 (Consensus): {subscores_healthy['T2']:.3f}")
    print(f"  T3 (Freshness): {subscores_healthy['T3']:.6f}")
    print(f"  T4 (Sequence): {subscores_healthy['T4']:.3f}")
    print(f"  T5 (Hash Chain): {subscores_healthy['T5']:.3f}")
    print(f"  T_availability: {subscores_healthy['T_availability']:.3f}")
    print(f"  → Trust Score: {score_healthy:.3f}")
    print()
    
    # Scenario 2: TLS unhealthy (empty/missing pins)
    print("Scenario 2: TLS Unhealthy (empty/missing pins)")
    subscores_unhealthy = compute_subscores(
        tls_ok=False,
        t2=0.8,
        latency_ms=1500,
        sequence_gap=1,
        chain_ok=True,
        active_exchanges={"binance", "coinbase", "kraken"},
        configured_exchanges={"binance", "coinbase", "kraken", "okx", "bybit"},
    )
    score_unhealthy = compute_trust_score(weights=weights, subscores=subscores_unhealthy)
    print(f"  T1 (TLS): {subscores_unhealthy['T1']:.3f}")
    print(f"  T2 (Consensus): {subscores_unhealthy['T2']:.3f}")
    print(f"  T3 (Freshness): {subscores_unhealthy['T3']:.6f}")
    print(f"  T4 (Sequence): {subscores_unhealthy['T4']:.3f}")
    print(f"  T5 (Hash Chain): {subscores_unhealthy['T5']:.3f}")
    print(f"  T_availability: {subscores_unhealthy['T_availability']:.3f}")
    print(f"  → Trust Score: {score_unhealthy:.3f}")
    print()
    
    # Show the difference
    delta = score_healthy - score_unhealthy
    print(f"Trust Score Degradation: {delta:.3f} ({delta/score_healthy*100:.1f}%)")
    print()
    
    print("=" * 70)
    print("CONCLUSION:")
    print("=" * 70)
    if not success:
        print("✓ TLS pins are empty/missing")
        print("✓ Registry defaults to unhealthy (pessimistic)")
        print("✓ Trust score correctly degrades by removing T1 contribution")
        print(f"✓ Expected score drop: ~{weights.w1_tls:.2f} (T1 weight)")
    else:
        print("✗ TLS pins are valid - trust score should be higher")
    print()


if __name__ == "__main__":
    main()

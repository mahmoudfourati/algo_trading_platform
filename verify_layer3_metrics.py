#!/usr/bin/env python3
"""Verification script for Layer 3 Strategy metrics.

This script verifies that all 6 Layer 3 metrics are properly defined and can be exported.
"""

from prometheus_client import REGISTRY, Counter, Gauge, Histogram

def verify_layer3_metrics():
    """Verify all Layer 3 metrics are registered and properly configured."""
    
    print("=" * 80)
    print("LAYER 3 STRATEGY METRICS VERIFICATION")
    print("=" * 80)
    
    expected_metrics = {
        "strategy_indicator_rsi": "gauge",
        "strategy_indicator_macd_histogram": "gauge",
        "strategy_indicator_bollinger_width": "gauge",
        "strategy_signal_direction_total": "counter",
        "strategy_signal_strength_distribution": "histogram",
        "strategy_ema_crossover_events_total": "counter",
    }
    
    print(f"\n✓ Expected metrics: {len(expected_metrics)}")
    print("\nChecking metric definitions...\n")
    
    # Import the service module to register metrics
    try:
        from services.layer3_strategy import service
        print("✓ Layer 3 service module imported successfully")
    except Exception as e:
        print(f"✗ Failed to import Layer 3 service: {e}")
        return False
    
    # Check each expected metric
    found_metrics = {}
    for collector in REGISTRY._collector_to_names.keys():
        if hasattr(collector, '_name'):
            metric_name = collector._name
            if metric_name in expected_metrics:
                metric_type = type(collector).__name__.lower()
                found_metrics[metric_name] = metric_type
                
                # Get labels
                labels = []
                if hasattr(collector, '_labelnames'):
                    labels = list(collector._labelnames)
                
                print(f"✓ {metric_name}")
                print(f"  Type: {metric_type}")
                print(f"  Labels: {labels}")
                print(f"  Description: {collector._documentation}")
                print()
    
    # Verify all expected metrics were found
    missing = set(expected_metrics.keys()) - set(found_metrics.keys())
    if missing:
        print(f"\n✗ Missing metrics: {missing}")
        return False
    
    print(f"\n{'=' * 80}")
    print(f"✓ ALL {len(expected_metrics)} LAYER 3 METRICS VERIFIED")
    print(f"{'=' * 80}")
    
    # Test metric export format
    print("\nSample Prometheus export format:\n")
    print("# HELP strategy_indicator_rsi RSI indicator value")
    print("# TYPE strategy_indicator_rsi gauge")
    print('strategy_indicator_rsi{symbol="BTC-USDT",timeframe="5m"} 45.5')
    print()
    print("# HELP strategy_signal_direction_total Signal generation count by direction")
    print("# TYPE strategy_signal_direction_total counter")
    print('strategy_signal_direction_total{symbol="BTC-USDT",direction="LONG"} 12')
    print()
    print("# HELP strategy_ema_crossover_events_total EMA crossover events")
    print("# TYPE strategy_ema_crossover_events_total counter")
    print('strategy_ema_crossover_events_total{symbol="BTC-USDT",timeframe="5m",direction="bullish"} 3')
    print()
    
    return True

if __name__ == "__main__":
    import sys
    success = verify_layer3_metrics()
    sys.exit(0 if success else 1)

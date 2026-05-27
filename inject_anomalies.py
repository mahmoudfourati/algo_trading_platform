#!/usr/bin/env python3
"""Inject synthetic anomalies into the trading platform for testing Layer 2 detection.

This script publishes crafted ValidatedTick messages to Kafka to simulate:
1. Flash crash (5% price drop in 1 second)
2. Liquidity crisis (spread widens 10×)
3. Volume explosion (50× normal volume)
4. Sustained drift (gradual 0.5% drift over 30 ticks)
5. Volatility regime shift (vol doubles suddenly)
"""

import json
import time
from datetime import datetime
from typing import Dict, Any

from kafka import KafkaProducer


class AnomalyInjector:
    """Inject synthetic anomalies into the validated tick stream."""

    def __init__(self, bootstrap_server: str = "localhost:29092"):
        self.producer = KafkaProducer(
            bootstrap_servers=bootstrap_server,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        self.topic = "market.ticks.validated"  # Layer 2 consumes from validated topic
        
        # Baseline values (normal market)
        self.baseline = {
            "BTC-USDT": {"price": 95000.0, "spread": 0.50, "volume": 1000000.0},
            "ETH-USDT": {"price": 3500.0, "spread": 0.20, "volume": 500000.0},
        }

    def _create_tick(
        self,
        symbol: str,
        mid_price: float,
        spread: float,
        volume_24h: float,
        trust_score: float = 1.0,
    ) -> Dict[str, Any]:
        """Create a ValidatedTick message."""
        return {
            "symbol": symbol,
            "asset_class": "crypto",
            "primary_exchange": "binance",
            "mid_price": mid_price,
            "consensus_mid": mid_price,
            "volume_24h": volume_24h,
            "spread": spread,
            "trust_score": trust_score,
            "sub_scores": {
                "T_availability": 1.0,
                "T_consensus": 1.0,
                "T_sequence": 1.0,
                "T_hashchain": 1.0,
                "T_tls": 1.0,
            },
            "used_sources": ["binance", "bybit", "okx"],
            "divergent_sources": [],
            "timestamp_utc": int(time.time() * 1000),
            "tick_hash": "synthetic_anomaly_test",
        }

    def inject_flash_crash(self, symbol: str = "BTC-USDT", severity: float = 0.50):
        """Simulate a flash crash: sudden 50% price drop."""
        print(f"\n🔴 INJECTING FLASH CRASH: {symbol} -{severity*100:.1f}%")
        
        baseline = self.baseline[symbol]
        crash_price = baseline["price"] * (1 - severity)
        
        # Send MANY crash ticks rapidly to overwhelm real market data
        print(f"   Price: ${baseline['price']:,.0f} → ${crash_price:,.0f} (-50%)")
        print(f"   Spread: ${baseline['spread']:.2f} → ${baseline['spread']*20:.2f} (×20)")
        print(f"   Volume: ${baseline['volume']:,.0f} → ${baseline['volume']*500:,.0f} (×500)")
        print(f"   Trust: 1.0 → 0.20 (extreme exchange divergence)")
        print(f"   Sending 20 rapid ticks to overwhelm real data...")
        
        # Send 20 crash ticks rapidly (one every 0.1s)
        for i in range(20):
            tick = self._create_tick(
                symbol=symbol,
                mid_price=crash_price * (1 + 0.005 * i),  # Slight recovery over time
                spread=baseline["spread"] * (20 - i * 0.5),  # Spread narrowing
                volume_24h=baseline["volume"] * (500 - i * 20),  # Volume decreasing
                trust_score=0.20 + (i * 0.02),  # Trust slowly recovering
            )
            self.producer.send(self.topic, tick)
            self.producer.flush()  # Force immediate send
            time.sleep(0.1)
            if i % 5 == 0:
                print(f"   Tick {i+1}/20: price ${crash_price * (1 + 0.005 * i):,.0f}, trust {0.20 + (i * 0.02):.2f}")
        
        print(f"   ✅ Sent 20 crash ticks - memory window should sustain high score for 30s")

    def inject_liquidity_crisis(self, symbol: str = "BTC-USDT", spread_multiplier: float = 50.0):
        """Simulate liquidity crisis: spread widens 50×."""
        print(f"\n🟠 INJECTING LIQUIDITY CRISIS: {symbol} spread ×{spread_multiplier:.0f}")
        
        baseline = self.baseline[symbol]
        wide_spread = baseline["spread"] * spread_multiplier
        
        # Sustained liquidity crisis for 3 seconds
        for i in range(3):
            tick = self._create_tick(
                symbol=symbol,
                mid_price=baseline["price"] * (1 - 0.01 * i),  # Price drifting down
                spread=wide_spread * (1 - 0.1 * i),  # Spread slowly narrowing
                volume_24h=baseline["volume"] * 0.05,  # Very low volume during crisis
                trust_score=0.40,  # Low trust
            )
            self.producer.send(self.topic, tick)
            time.sleep(1)
            if i == 0:
                print(f"   Spread: ${baseline['spread']:.2f} → ${wide_spread:.2f} (×{spread_multiplier:.0f})")
                print(f"   Volume: ${baseline['volume']:,.0f} → ${baseline['volume']*0.05:,.0f} (×0.05)")
                print(f"   Trust: 1.0 → 0.40")
                print(f"   Expected: AbsoluteThreshold + CUSUM trigger, HALT state")

    def inject_volume_explosion(self, symbol: str = "BTC-USDT", volume_multiplier: float = 50.0):
        """Simulate volume explosion: 50× normal volume."""
        print(f"\n🟡 INJECTING VOLUME EXPLOSION: {symbol} volume ×{volume_multiplier:.0f}")
        
        baseline = self.baseline[symbol]
        huge_volume = baseline["volume"] * volume_multiplier
        
        tick = self._create_tick(
            symbol=symbol,
            mid_price=baseline["price"] * 1.01,  # Slight price move
            spread=baseline["spread"],
            volume_24h=huge_volume,
        )
        self.producer.send(self.topic, tick)
        print(f"   Volume: ${baseline['volume']:,.0f} → ${huge_volume:,.0f}")
        print(f"   Expected: AbsoluteThreshold trigger, score ~0.5-0.7")

    def inject_sustained_drift(self, symbol: str = "BTC-USDT", drift_pct: float = 0.005, ticks: int = 30):
        """Simulate sustained drift: gradual 0.5% drift over 30 ticks."""
        print(f"\n🔵 INJECTING SUSTAINED DRIFT: {symbol} +{drift_pct*100:.2f}% over {ticks} ticks")
        
        baseline = self.baseline[symbol]
        start_price = baseline["price"]
        end_price = start_price * (1 + drift_pct)
        price_step = (end_price - start_price) / ticks
        
        for i in range(ticks):
            current_price = start_price + (price_step * i)
            tick = self._create_tick(
                symbol=symbol,
                mid_price=current_price,
                spread=baseline["spread"],
                volume_24h=baseline["volume"],
            )
            self.producer.send(self.topic, tick)
            time.sleep(0.1)  # 10 ticks/sec
            
            if i % 10 == 0:
                print(f"   Tick {i}: ${current_price:,.2f}")
        
        print(f"   Final: ${start_price:,.0f} → ${end_price:,.0f}")
        print(f"   Expected: CUSUM trigger after ~15-20 ticks, score ~0.6-0.8")

    def inject_volatility_spike(self, symbol: str = "BTC-USDT", vol_multiplier: float = 3.0):
        """Simulate volatility regime shift: vol triples suddenly."""
        print(f"\n🟣 INJECTING VOLATILITY SPIKE: {symbol} vol ×{vol_multiplier:.1f}")
        
        baseline = self.baseline[symbol]
        
        # Send 10 ticks with 3× normal volatility
        for i in range(10):
            # Random walk with 3× volatility
            price_change_pct = (0.002 * vol_multiplier) * (1 if i % 2 == 0 else -1)
            new_price = baseline["price"] * (1 + price_change_pct)
            
            tick = self._create_tick(
                symbol=symbol,
                mid_price=new_price,
                spread=baseline["spread"],
                volume_24h=baseline["volume"],
            )
            self.producer.send(self.topic, tick)
            time.sleep(0.1)
            
            if i % 3 == 0:
                print(f"   Tick {i}: ${new_price:,.2f} ({price_change_pct*100:+.2f}%)")
        
        print(f"   Expected: VolatilityRatio trigger, score ~0.5-0.7")

    def inject_combined_crisis(self, symbol: str = "BTC-USDT"):
        """Simulate combined crisis: flash crash + liquidity crisis + volume spike."""
        print(f"\n🔴🟠🟡 INJECTING COMBINED CRISIS: {symbol}")
        
        baseline = self.baseline[symbol]
        
        print(f"   Price: ${baseline['price']:,.0f} → ${baseline['price']*0.70:,.0f} (-30%)")
        print(f"   Spread: ${baseline['spread']:.2f} → ${baseline['spread']*50:.2f} (×50)")
        print(f"   Volume: ${baseline['volume']:,.0f} → ${baseline['volume']*1000:,.0f} (×1000)")
        print(f"   Trust: 1.0 → 0.15 (catastrophic exchange divergence)")
        print(f"   Sending 30 rapid crisis ticks...")
        
        # Extreme crisis - 30 ticks over 3 seconds
        for i in range(30):
            tick = self._create_tick(
                symbol=symbol,
                mid_price=baseline["price"] * (0.70 - 0.005 * i),  # 30% crash, continuing to drop
                spread=baseline["spread"] * (50 - i * 0.5),  # Massive spread, slowly narrowing
                volume_24h=baseline["volume"] * (1000 - i * 20),  # Huge volume, decreasing
                trust_score=0.15 + (i * 0.01),  # Very low trust, slowly recovering
            )
            self.producer.send(self.topic, tick)
            self.producer.flush()
            time.sleep(0.1)
            
            if i % 10 == 0:
                print(f"   Tick {i+1}/30: price ${baseline['price'] * (0.70 - 0.005 * i):,.0f}, trust {0.15 + (i * 0.01):.2f}")
        
        print(f"   ✅ Sent 30 crisis ticks - should trigger HALT and sustain for 30+ seconds")

    def run_test_suite(self):
        """Run all anomaly tests in sequence."""
        print("=" * 70)
        print("LAYER 2 ANOMALY DETECTION TEST SUITE")
        print("=" * 70)
        print("\nWatch Grafana dashboard: http://localhost:3000/d/layer2-anomaly")
        print("\nStarting tests in 5 seconds...")
        time.sleep(5)
        
        # Test 1: Flash Crash (50% drop, 20 rapid ticks)
        self.inject_flash_crash("BTC-USDT", severity=0.50)
        print("\n⏳ Waiting 40 seconds to observe memory window decay...")
        time.sleep(40)
        
        # Test 2: Combined Crisis (30% drop, 30 rapid ticks)
        self.inject_combined_crisis("BTC-USDT")
        print("\n⏳ Waiting 40 seconds to observe memory window decay...")
        time.sleep(40)
        
        print("\n" + "=" * 70)
        print("TEST SUITE COMPLETE")
        print("=" * 70)
        print("\nCheck Grafana for anomaly score behavior!")
        print("Expected behavior:")
        print("  - Flash crash: score jumps to 0.85+, sustains for ~30s, then decays")
        print("  - Combined crisis: score jumps to 0.85+, sustains for ~30s, then decays")
        print("  - Decision Gate: should reach HALT state during both events")
        print("  - Memory window: scores should stay elevated even after anomaly ends")

    def close(self):
        """Close Kafka producer."""
        self.producer.flush()
        self.producer.close()


if __name__ == "__main__":
    injector = AnomalyInjector()
    try:
        injector.run_test_suite()
    finally:
        injector.close()

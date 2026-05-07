"""Attack scenario injectors for backtesting replay."""

from __future__ import annotations

from dataclasses import dataclass

from shared.schemas import NormalizedTick


@dataclass(frozen=True)
class ScenarioInjection:
    tick: NormalizedTick
    injected: bool


def _progress(ts_ms: int, *, start_ms: int, end_ms: int) -> float:
    if end_ms <= start_ms:
        return 0.0
    p = (float(ts_ms) - float(start_ms)) / float(end_ms - start_ms)
    return max(0.0, min(1.0, p))


def _in_window(p: float, *, lo: float = 0.35, hi: float = 0.65) -> bool:
    return lo <= p <= hi


def apply_attack_scenario(
    tick: NormalizedTick,
    *,
    scenario: str,
    start_ms: int,
    end_ms: int,
) -> ScenarioInjection:
    """Apply a synthetic attack scenario to a single tick."""

    scenario = scenario.strip().lower()
    if scenario in {"", "baseline", "none"}:
        return ScenarioInjection(tick=tick, injected=False)

    p = _progress(tick.received_timestamp_ms, start_ms=start_ms, end_ms=end_ms)

    if scenario == "flash_crash":
        if not _in_window(p):
            return ScenarioInjection(tick=tick, injected=False)

        # Triangular shock: max impact at middle of active window.
        local = (p - 0.35) / 0.30
        intensity = max(0.2, 1.0 - abs((local * 2.0) - 1.0))
        severity = 0.10 * intensity

        new_mid = max(1e-8, tick.last_price * (1.0 - severity))
        half_spread = max(1e-8, (tick.ask - tick.bid) / 2.0)
        mutated = tick.model_copy(
            update={
                "last_price": new_mid,
                "bid": max(1e-8, new_mid - half_spread),
                "ask": new_mid + half_spread,
            }
        )
        return ScenarioInjection(tick=mutated, injected=True)

    if scenario == "feed_corruption":
        if not _in_window(p):
            return ScenarioInjection(tick=tick, injected=False)

        new_mid = max(1e-8, tick.last_price * 1.05)
        half_spread = max(1e-8, (tick.ask - tick.bid) / 2.0)
        mutated = tick.model_copy(
            update={
                "last_price": new_mid,
                "bid": max(1e-8, new_mid - half_spread),
                "ask": new_mid + half_spread,
            }
        )
        return ScenarioInjection(tick=mutated, injected=True)

    if scenario == "replay_attack":
        if not _in_window(p):
            return ScenarioInjection(tick=tick, injected=False)

        replay_ms = max(0, tick.received_timestamp_ms - 200)
        mutated = tick.model_copy(
            update={
                "received_timestamp_ms": replay_ms,
                "exchange_timestamp_ms": max(0, tick.exchange_timestamp_ms - 200),
            }
        )
        return ScenarioInjection(tick=mutated, injected=True)

    if scenario == "gradual_drift":
        if not _in_window(p):
            return ScenarioInjection(tick=tick, injected=False)

        drift_steps = 20
        step = int(round(((p - 0.35) / 0.30) * (drift_steps - 1)))
        drift_factor = 1.0 + (0.001 * max(0, step))
        new_mid = max(1e-8, tick.last_price * drift_factor)
        half_spread = max(1e-8, (tick.ask - tick.bid) / 2.0)
        mutated = tick.model_copy(
            update={
                "last_price": new_mid,
                "bid": max(1e-8, new_mid - half_spread),
                "ask": new_mid + half_spread,
            }
        )
        return ScenarioInjection(tick=mutated, injected=True)

    if scenario == "coordinated_spoofing":
        if not _in_window(p):
            return ScenarioInjection(tick=tick, injected=False)
        if tick.exchange_id not in {"binance", "coinbase"}:
            return ScenarioInjection(tick=tick, injected=False)

        new_mid = max(1e-8, tick.last_price * 1.03)
        half_spread = max(1e-8, (tick.ask - tick.bid) / 2.0)
        mutated = tick.model_copy(
            update={
                "last_price": new_mid,
                "bid": max(1e-8, new_mid - half_spread),
                "ask": new_mid + half_spread,
            }
        )
        return ScenarioInjection(tick=mutated, injected=True)

    if scenario == "spread_spike":
        if not _in_window(p):
            return ScenarioInjection(tick=tick, injected=False)

        mid = max(1e-8, tick.last_price)
        widened = max(1e-8, mid * 0.02)  # 200 bps
        mutated = tick.model_copy(
            update={
                "bid": max(1e-8, mid - widened / 2.0),
                "ask": mid + widened / 2.0,
            }
        )
        return ScenarioInjection(tick=mutated, injected=True)

    if scenario == "multi_source_disagreement":
        if not _in_window(p):
            return ScenarioInjection(tick=tick, injected=False)
        if tick.exchange_id == "binance":
            return ScenarioInjection(tick=tick, injected=False)

        new_mid = max(1e-8, tick.last_price * 1.005)  # +0.5%
        half_spread = max(1e-8, (tick.ask - tick.bid) / 2.0)
        mutated = tick.model_copy(
            update={
                "last_price": new_mid,
                "bid": max(1e-8, new_mid - half_spread),
                "ask": new_mid + half_spread,
            }
        )
        return ScenarioInjection(tick=mutated, injected=True)

    if scenario == "volume_spike":
        if not _in_window(p):
            return ScenarioInjection(tick=tick, injected=False)
        mutated = tick.model_copy(update={"volume_24h": float(tick.volume_24h) * 10.0})
        return ScenarioInjection(tick=mutated, injected=True)

    return ScenarioInjection(tick=tick, injected=False)
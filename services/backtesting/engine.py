"""Backtest engine for Phase 5 historical replay."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional, Sequence

from services.layer1_consensus.engine import AlignedWindow, ConsensusConfig, ConsensusEngine, TickAligner
from services.layer1_hashlog.hash_chain import GENESIS_HASH, compute_tick_hash
from services.layer1_trust.scoring import compute_subscores, compute_t2, compute_trust_score, load_trust_weights
from services.layer2_anomaly.engine import DecisionGate, Layer2ScoringEngine
from services.layer3_strategy.service import Layer3SymbolState
from services.layer3_strategy.signals import TradeSignal
from services.layer4_risk import Layer4RiskEngine
from shared.schemas import ExchangeId, NormalizedTick, ScoredTick, ValidatedTick

from .attack_scenarios import apply_attack_scenario
from .data_loader import HistoricalTickLoader, HistoricalTickRecord
from .metrics import BacktestMetrics, ScoringEvent
from .permutation_test import run_permutation_test
from .report_generator import BacktestReportGenerator
from .results_db import ResultsDB
from .time_control import TimeController


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _median_latency_ms(ticks: Iterable[NormalizedTick], *, now_ms: int) -> float:
    latencies = [max(0, now_ms - int(t.exchange_timestamp_ms)) for t in ticks]
    if not latencies:
        return float("inf")
    return float(statistics.median(latencies))


def _median_spread(ticks: Iterable[NormalizedTick]) -> float:
    spreads: list[float] = []
    for tick in ticks:
        mid = tick.mid
        if mid > 0:
            spreads.append(max(0.0, (tick.ask - tick.bid) / mid))
    return float(statistics.median(spreads)) if spreads else 0.0


def _median_volume_24h(ticks: Iterable[NormalizedTick]) -> float:
    volumes = [max(0.0, float(tick.volume_24h)) for tick in ticks]
    return float(statistics.median(volumes)) if volumes else 0.0


@dataclass(frozen=True)
class ExchangeConfig:
    name: ExchangeId
    base_frequency_hz: float = 1.0
    latency_ms: float = 0.0
    tick_jitter_pips: float = 0.0
    outage_probability: float = 0.0


@dataclass
class BacktestConfig:
    """Configuration for a single backtest run."""

    symbol: str
    scenario: str
    start_time: datetime
    end_time: datetime
    output_dir: Path = Path("artifacts/reports")
    source_path: Optional[Path] = None
    cache_path: Optional[Path] = None
    results_db_path: Optional[Path] = None
    hmm_model_path: Path = Path("artifacts/hmm/model.pkl")
    trust_weights_path: Optional[Path] = None
    primary_exchange: ExchangeId = "binance"
    enabled_exchanges: Sequence[ExchangeId] = ("binance", "bybit", "coinbase", "kraken", "okx")
    window_ms: int = 50
    time_speed: float = 1.0
    if_weight: float = 0.45
    hst_weight: float = 0.55
    trust_threshold: float = 0.60
    anomaly_threshold: float = 0.80


@dataclass(frozen=True)
class BacktestResult:
    """Output bundle for a completed backtest run."""

    config: BacktestConfig
    metrics: BacktestMetrics
    report_path: Path
    equity_curve_path: Path


@dataclass
class OpenPosition:
    """Active position tracked during backtest replay."""

    direction: str
    size_pct: float
    entry_price: float
    entry_timestamp_utc: int
    stop_loss_price: Optional[float]
    take_profit_price: Optional[float]


class MultiSourceGenerator:
    """Synthetic 5-exchange tick generator built from a historical anchor stream."""

    def __init__(self, *, exchange_configs: Optional[Sequence[ExchangeConfig]] = None, seed: int = 42) -> None:
        import random

        self._random = random.Random(seed)
        # Keep latencies tight (all within 50ms window) to ensure consensus participation
        # Binance is PRIMARY_EXCHANGE and must always be in every aligned window
        self._configs = list(
            exchange_configs
            or [
                ExchangeConfig("binance", base_frequency_hz=5.0, latency_ms=5.0, tick_jitter_pips=0.2, outage_probability=0.0),
                ExchangeConfig("bybit", base_frequency_hz=2.5, latency_ms=12.0, tick_jitter_pips=0.3, outage_probability=0.01),
                ExchangeConfig("coinbase", base_frequency_hz=1.5, latency_ms=20.0, tick_jitter_pips=0.35, outage_probability=0.01),
                ExchangeConfig("kraken", base_frequency_hz=1.0, latency_ms=28.0, tick_jitter_pips=0.4, outage_probability=0.02),
                ExchangeConfig("okx", base_frequency_hz=1.0, latency_ms=38.0, tick_jitter_pips=0.45, outage_probability=0.02),
            ]
        )

    def generate(self, records: Iterable[HistoricalTickRecord]) -> Iterator[NormalizedTick]:
        for record in records:
            mid = float(record.last_price)
            spread = max(1e-8, float(record.ask) - float(record.bid))
            for cfg in self._configs:
                if self._random.random() < cfg.outage_probability:
                    continue

                jitter_bps = self._random.uniform(-cfg.tick_jitter_pips, cfg.tick_jitter_pips)
                jitter_scale = 1.0 + (jitter_bps / 10_000.0)
                synth_mid = max(1e-8, mid * jitter_scale)
                synth_spread = max(1e-8, spread * (1.0 + self._random.uniform(-0.1, 0.1)))
                bid = synth_mid - synth_spread / 2.0
                ask = synth_mid + synth_spread / 2.0
                ts_ms = record.timestamp_ms + int(cfg.latency_ms)

                yield NormalizedTick(
                    exchange_id=cfg.name,
                    symbol=record.symbol,
                    bid=bid,
                    ask=ask,
                    last_price=synth_mid,
                    volume_24h=max(0.0, float(record.volume) * (1.0 + self._random.uniform(-0.05, 0.05))),
                    exchange_timestamp_ms=record.timestamp_ms,
                    received_timestamp_ms=ts_ms,
                    timestamp_source="exchange",
                    sequence_id=None,
                )


class Layer1Simulator:
    """In-memory Layer 1 consensus and trust replay."""

    def __init__(
        self,
        *,
        primary_exchange: ExchangeId,
        enabled_exchanges: Sequence[ExchangeId],
        window_ms: int,
        trust_weights_path: Optional[Path] = None,
    ) -> None:
        self.primary_exchange = primary_exchange
        self.enabled_exchanges = list(enabled_exchanges)
        self.consensus = ConsensusEngine(
            ConsensusConfig(
                divergence_tolerance=0.003,
                aggregation_window_ms=window_ms,
                escalate_after=3,
                min_sources_for_consensus=2,
            )
        )
        self.aligner = TickAligner(window_ms=window_ms)
        self.weights = load_trust_weights(str(trust_weights_path) if trust_weights_path else None)
        self._previous_hash = GENESIS_HASH

    def ingest(self, tick: NormalizedTick) -> list[ValidatedTick]:
        validated: list[ValidatedTick] = []
        for window in self.aligner.add(tick):
            validated.extend(self._process_window(window))
        return validated

    def flush(self, *, now_ms: int) -> list[ValidatedTick]:
        validated: list[ValidatedTick] = []
        for window in self.aligner.flush_due(now_ms=now_ms):
            validated.extend(self._process_window(window))
        return validated

    def _process_window(self, window: AlignedWindow) -> list[ValidatedTick]:
        symbol = window.symbol
        out = self.consensus.process_aligned(symbol, window.by_ex)
        if out.consensus_mid is None:
            return []

        primary_tick = window.by_ex.get(self.primary_exchange)
        if primary_tick is None or self.primary_exchange not in out.used_sources:
            return []

        tolerance = abs(out.consensus_mid) * float(self.consensus.config.divergence_tolerance)
        t2 = compute_t2(
            ticks_with_age=window.ticks_with_age,
            consensus_price=out.consensus_mid,
            tolerance=tolerance,
            active_sources=window.active_sources,
        )
        latency_ms = _median_latency_ms((primary_tick,), now_ms=window.window_end_ms)
        spread = _median_spread((primary_tick,))
        volume_24h = _median_volume_24h((primary_tick,))

        subscores = compute_subscores(
            tls_ok=True,
            t2=t2,
            latency_ms=latency_ms,
            sequence_gap=None,
            chain_ok=True,
        )
        trust_score = compute_trust_score(weights=self.weights, subscores=subscores)

        tick_hash = compute_tick_hash(
            symbol=symbol,
            primary_exchange=self.primary_exchange,
            primary_mid_price=primary_tick.mid,
            consensus_mid=out.consensus_mid,
            used_sources=out.used_sources,
            divergent_sources=out.divergent_sources,
            trust_score=trust_score,
            received_timestamp_ms=window.window_end_ms,
            previous_hash=self._previous_hash,
        )
        self._previous_hash = tick_hash

        return [
            ValidatedTick(
                symbol=symbol,
                primary_exchange=self.primary_exchange,
                mid_price=primary_tick.mid,
                consensus_mid=out.consensus_mid,
                volume_24h=volume_24h,
                spread=spread,
                trust_score=trust_score,
                sub_scores=subscores,
                used_sources=out.used_sources,
                divergent_sources=out.divergent_sources,
                timestamp_utc=window.window_end_ms,
                tick_hash=tick_hash,
            )
        ]


class Layer2Simulator:
    """In-memory Layer 2 scoring and decision-gate replay."""

    def __init__(
        self,
        *,
        hmm_model_path: Path,
        if_weight: float,
        hst_weight: float,
        trust_threshold: float,
        anomaly_threshold: float,
    ) -> None:
        self.scorer = Layer2ScoringEngine(
            hmm_model_path=str(hmm_model_path),
            if_weight=if_weight,
            hst_weight=hst_weight,
        )
        self.gate = DecisionGate(trust_threshold=trust_threshold, anomaly_threshold=anomaly_threshold)

    def score(self, validated: ValidatedTick) -> ScoredTick:
        scores = self.scorer.score_tick(
            symbol=validated.symbol,
            ts_ms=validated.timestamp_utc,
            mid_price=validated.mid_price,
            trust_score=validated.trust_score,
            volume_24h=validated.volume_24h,
            spread=validated.spread,
        )
        system_state = self.gate.update(trust=validated.trust_score, anomaly=scores.anomaly_score)
        return ScoredTick(
            symbol=validated.symbol,
            asset_class=validated.asset_class,
            primary_exchange=validated.primary_exchange,
            mid_price=validated.mid_price,
            consensus_mid=validated.consensus_mid,
            volume_24h=validated.volume_24h,
            spread=validated.spread,
            trust_score=validated.trust_score,
            sub_scores=validated.sub_scores,
            used_sources=validated.used_sources,
            divergent_sources=validated.divergent_sources,
            timestamp_utc=validated.timestamp_utc,
            tick_hash=validated.tick_hash,
            anomaly_score=scores.anomaly_score,
            if_score=scores.if_score,
            hst_score=scores.hst_score,
            regime=scores.regime,
            regime_posterior=scores.regime_posterior,
            system_state=system_state,
            mad_guard_triggered=scores.mad_guard_triggered,
        )


class BacktestEngine:
    """Orchestrate deterministic replay and metric collection."""

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.loader = HistoricalTickLoader(
            symbols=[config.symbol],
            start_date=config.start_time,
            end_date=config.end_time,
            source_path=config.source_path,
            cache_path=config.cache_path,
        )
        self.generator = MultiSourceGenerator()

    def _write_equity_curve(self, rows: list[dict[str, object]], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp_utc",
                    "symbol",
                    "state",
                    "risk_state",
                    "signal_direction",
                    "signal_size_pct",
                    "position",
                    "position_size_pct",
                    "anomaly_score",
                    "gross_pnl",
                    "net_pnl",
                    "equity_gross",
                    "equity_net",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)

    def run(self) -> BacktestResult:
        records = self.loader.load()
        if not records:
            raise RuntimeError("No historical ticks were loaded for the requested range")

        output_dir = self.config.output_dir / f"{self.config.symbol}_{self.config.scenario}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        output_dir.mkdir(parents=True, exist_ok=True)

        time_controller = TimeController(
            current_time=_utc(self.config.start_time),
            end_time=_utc(self.config.end_time),
            speed=self.config.time_speed,
        )
        layer1 = Layer1Simulator(
            primary_exchange=self.config.primary_exchange,
            enabled_exchanges=self.config.enabled_exchanges,
            window_ms=self.config.window_ms,
            trust_weights_path=self.config.trust_weights_path,
        )
        layer2 = Layer2Simulator(
            hmm_model_path=self.config.hmm_model_path,
            if_weight=self.config.if_weight,
            hst_weight=self.config.hst_weight,
            trust_threshold=self.config.trust_threshold,
            anomaly_threshold=self.config.anomaly_threshold,
        )
        layer3 = Layer3SymbolState(symbol=self.config.symbol)
        layer4 = Layer4RiskEngine()
        # Phase 8: execution engine (simulated adapter by default)
        from services.layer5_execution.engine import ExecutionEngine
        from services.layer5_execution.adapters import SimulatedExecutionAdapter

        exec_adapter = SimulatedExecutionAdapter()
        capital_base = 1.0
        execution_engine = ExecutionEngine(adapter=exec_adapter, portfolio_value=capital_base)
        per_trade_rows: list[dict[str, object]] = []
        _trade_id_counter = 1
        validated_total = 0
        scored_total = 0
        normal_count = 0
        detected_anomalies = 0
        false_positives = 0
        gross_cash = 0.0
        net_cash = 0.0
        open_position: Optional[OpenPosition] = None
        last_price: Optional[float] = None
        approved_orders = 0
        rejected_orders = 0
        reduced_state_ticks = 0
        halted_state_ticks = 0
        trade_pnls: list[float] = []
        equity_rows: list[dict[str, object]] = []
        events: list[ScoringEvent] = []
        equity_net_history: list[float] = []
        total_latency_ms = 0.0
        peak_equity = 0.0
        max_drawdown = 0.0
        injected_anomalies = 0
        attack_activity_budget = 0
        attack_episode_count = 0
        attack_episode_detected_count = 0
        attack_detection_latencies_ms: list[float] = []
        current_attack_episode_start_ms: Optional[int] = None
        current_attack_episode_detected = False
        last_scored_tick: Optional[ScoredTick] = None

        def current_unrealized_pct(*, trade_price: float) -> float:
            if open_position is None:
                return 0.0
            price_return = (trade_price - open_position.entry_price) / open_position.entry_price
            if open_position.direction == "SHORT":
                price_return = -price_return
            return open_position.size_pct * price_return

        def current_equity(*, trade_price: float) -> tuple[float, float]:
            unrealized = current_unrealized_pct(trade_price=trade_price)
            gross_equity = capital_base + gross_cash + unrealized
            net_equity = capital_base + net_cash + unrealized
            return gross_equity, net_equity

        def open_order(*, order, trade_price: float) -> None:
            nonlocal open_position, net_cash

            open_position = OpenPosition(
                direction=order.direction,
                size_pct=order.size_pct,
                entry_price=trade_price,
                entry_timestamp_utc=order.timestamp_utc,
                stop_loss_price=order.stop_loss_price,
                take_profit_price=order.take_profit_price,
            )
            net_cash -= order.size_pct * 0.001

        def close_order(*, trade_price: float, timestamp_utc: int) -> None:
            nonlocal open_position, gross_cash, net_cash, trade_pnls

            if open_position is None:
                return

            price_return = (trade_price - open_position.entry_price) / open_position.entry_price
            if open_position.direction == "SHORT":
                price_return = -price_return
            realized_gross = open_position.size_pct * price_return
            realized_net = realized_gross - (open_position.size_pct * 0.001)
            gross_cash += realized_gross
            net_cash += realized_net
            trade_pnls.append(realized_net)
            layer4.register_closed_trade(realized_pnl_pct=realized_net, direction=open_position.direction, timestamp_utc=timestamp_utc)
            open_position = None

        start_ms = min(rec.timestamp_ms for rec in records)
        end_ms = max(rec.timestamp_ms for rec in records)

        with time_controller.patched():
            for tick in self.generator.generate(records):
                injected = apply_attack_scenario(
                    tick,
                    scenario=self.config.scenario,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
                tick_for_replay = injected.tick
                if injected.injected:
                    injected_anomalies += 1
                    if attack_activity_budget <= 0:
                        attack_episode_count += 1
                        current_attack_episode_start_ms = tick_for_replay.received_timestamp_ms
                        current_attack_episode_detected = False
                    attack_activity_budget = max(attack_activity_budget, 5)

                time_controller.sync_to(datetime.fromtimestamp(tick_for_replay.received_timestamp_ms / 1000.0, tz=timezone.utc))
                for validated in layer1.ingest(tick_for_replay):
                    validated_total += 1
                    scored = layer2.score(validated)
                    scored_total += 1
                    last_price = scored.mid_price
                    last_scored_tick = scored

                    equity_gross, equity_net = current_equity(trade_price=scored.mid_price)
                    layer4.observe_market(timestamp_utc=scored.timestamp_utc, equity=equity_net, upstream_state=scored.system_state)
                    if layer4.state.circuit_breaker_state == "NORMAL":
                        normal_count += 1
                    elif layer4.state.circuit_breaker_state == "REDUCED":
                        reduced_state_ticks += 1
                    elif layer4.state.circuit_breaker_state == "HALTED":
                        halted_state_ticks += 1

                    if attack_activity_budget > 0:
                        if scored.anomaly_score >= self.config.anomaly_threshold:
                            detected_anomalies += 1
                            if current_attack_episode_start_ms is not None and not current_attack_episode_detected:
                                attack_episode_detected_count += 1
                                attack_detection_latencies_ms.append(
                                    max(0.0, float(scored.timestamp_utc - current_attack_episode_start_ms))
                                )
                                current_attack_episode_detected = True
                    elif scored.anomaly_score >= self.config.anomaly_threshold and scored.trust_score >= self.config.trust_threshold:
                        false_positives += 1

                    emitted_signals = layer3.ingest_tick(scored)
                    last_signal_direction = "HOLD"
                    last_signal_size_pct = 0.0
                    current_exposure_pct = open_position.size_pct if open_position is not None else 0.0
                    for signal in emitted_signals:
                        decision = layer4.evaluate_signal(
                            signal,
                            reference_price=scored.mid_price,
                            current_portfolio_exposure_pct=current_exposure_pct,
                            timestamp_utc=signal.timestamp_utc,
                        )
                        if not decision.approved or decision.approved_order is None:
                            rejected_orders += 1
                            continue

                        approved_orders += 1

                        order = decision.approved_order
                        # Submit to execution engine and obtain fill details
                        submit_ts = int(time.time() * 1000)
                        executed = execution_engine.submit_order(order, reference_price=scored.mid_price)
                        ack_ts = int(time.time() * 1000)
                        # record per-trade ledger row
                        per_trade_rows.append(
                            {
                                "trade_id": _trade_id_counter,
                                "client_order_id": executed.order_id,
                                "signal_ts": int(signal.timestamp_utc),
                                "submit_ts": submit_ts,
                                "ack_ts": ack_ts,
                                "first_fill_ts": ack_ts,
                                "last_fill_ts": ack_ts,
                                "fill_price": executed.avg_fill_price,
                                "fill_fraction": executed.filled_pct,
                                "side": order.direction,
                                "size_pct": order.size_pct if hasattr(order, "size_pct") else order.get("size_pct", 0.0),
                                "fee": executed.fee_paid,
                                "slippage_pct": executed.slippage_pct,
                                "final_state": executed.note or "",
                                "exit_reason": "",
                                "net_pnl": 0.0,
                            }
                        )
                        _trade_id_counter += 1
                        # Update net/gross cash based on execution
                        # executed.filled_pct is fraction of portfolio filled (size_pct or capped partial)
                        filled_size = executed.filled_pct
                        filled_notional = filled_size * capital_base
                        # fees are denominated in quote, subtract from net
                        net_cash -= executed.fee_paid
                        gross_cash -= 0.0  # gross_cash remains PnL-only here

                        last_signal_direction = order.direction
                        last_signal_size_pct = order.size_pct

                        if order.direction == "CLOSE_ALL":
                            # close fully using the execution engine semantics
                            submit_ts = int(time.time() * 1000)
                            executed_close = execution_engine.submit_order(order, reference_price=scored.mid_price)
                            ack_ts = int(time.time() * 1000)
                            per_trade_rows.append(
                                {
                                    "trade_id": _trade_id_counter,
                                    "client_order_id": executed_close.order_id,
                                    "signal_ts": int(order.timestamp_utc),
                                    "submit_ts": submit_ts,
                                    "ack_ts": ack_ts,
                                    "first_fill_ts": ack_ts,
                                    "last_fill_ts": ack_ts,
                                    "fill_price": executed_close.avg_fill_price,
                                    "fill_fraction": executed_close.filled_pct,
                                    "side": order.direction,
                                    "size_pct": order.size_pct if hasattr(order, "size_pct") else order.get("size_pct", 0.0),
                                    "fee": executed_close.fee_paid,
                                    "slippage_pct": executed_close.slippage_pct,
                                    "final_state": executed_close.note or "",
                                    "exit_reason": "CLOSE_ALL",
                                    "net_pnl": 0.0,
                                }
                            )
                            _trade_id_counter += 1
                            # apply close to PnL
                            close_order(trade_price=executed_close.avg_fill_price, timestamp_utc=order.timestamp_utc)
                            continue

                        if open_position is not None and open_position.direction != order.direction:
                            close_order(trade_price=scored.mid_price, timestamp_utc=order.timestamp_utc)

                        if open_position is None:
                            # Use executed fill price for entry
                            open_order(order=order, trade_price=executed.avg_fill_price)

                    equity_gross, equity_net = current_equity(trade_price=scored.mid_price)
                    peak_equity = max(peak_equity, equity_net)
                    max_drawdown = max(max_drawdown, peak_equity - equity_net)

                    equity_net_history.append(equity_net)
                    total_latency_ms += max(0.0, float(scored.timestamp_utc - validated.timestamp_utc))

                    events.append(
                        ScoringEvent(
                            timestamp=datetime.fromtimestamp(scored.timestamp_utc / 1000.0, tz=timezone.utc),
                            symbol=scored.symbol,
                            anomaly_score=scored.anomaly_score,
                            regime=scored.regime,
                            if_score=scored.if_score,
                            hst_score=scored.hst_score,
                            mad_triggered=scored.mad_guard_triggered,
                            decision_state=scored.system_state,
                            trust_score=scored.trust_score,
                        )
                    )

                    if attack_activity_budget > 0:
                        attack_activity_budget -= 1
                        if attack_activity_budget == 0:
                            current_attack_episode_start_ms = None
                            current_attack_episode_detected = False

                    equity_rows.append(
                        {
                            "timestamp_utc": datetime.fromtimestamp(scored.timestamp_utc / 1000.0, tz=timezone.utc).isoformat(),
                            "symbol": scored.symbol,
                            "state": scored.system_state,
                            "risk_state": layer4.state.circuit_breaker_state,
                            "signal_direction": last_signal_direction,
                            "signal_size_pct": last_signal_size_pct,
                            "position": 1 if open_position and open_position.direction == "LONG" else (-1 if open_position and open_position.direction == "SHORT" else 0),
                            "position_size_pct": open_position.size_pct if open_position is not None else 0.0,
                            "anomaly_score": scored.anomaly_score,
                            "gross_pnl": gross_cash,
                            "net_pnl": net_cash,
                            "equity_gross": equity_gross,
                            "equity_net": equity_net,
                        }
                    )

        if last_scored_tick is not None:
            flushed_signals = layer3.flush(tick=last_scored_tick)
            for signal in flushed_signals:
                decision = layer4.evaluate_signal(
                    signal,
                    reference_price=last_scored_tick.mid_price,
                    current_portfolio_exposure_pct=open_position.size_pct if open_position is not None else 0.0,
                    timestamp_utc=signal.timestamp_utc,
                )
                if decision.approved and decision.approved_order is not None:
                    approved_orders = locals().get("approved_orders", 0)
                    approved_orders += 1
                    if decision.approved_order.direction == "CLOSE_ALL" and open_position is not None:
                        close_order(trade_price=last_scored_tick.mid_price, timestamp_utc=decision.approved_order.timestamp_utc)

        if open_position is not None and last_price is not None:
            close_order(trade_price=last_price, timestamp_utc=int(last_scored_tick.timestamp_utc if last_scored_tick is not None else _utc(self.config.end_time).timestamp() * 1000))
            equity_gross, equity_net = current_equity(trade_price=last_price)
            peak_equity = max(peak_equity, equity_net)
            max_drawdown = max(max_drawdown, peak_equity - equity_net)
            equity_net_history.append(equity_net)

        gross_pnl = gross_cash
        net_pnl = net_cash
        win_rate = (sum(1 for pnl in trade_pnls if pnl > 0) / len(trade_pnls)) if trade_pnls else 0.0
        returns = [equity_net_history[i] - equity_net_history[i - 1] for i in range(1, len(equity_net_history))]
        if len(returns) >= 2:
            mean_r = statistics.mean(returns)
            stdev_r = statistics.pstdev(returns)
            sharpe = (mean_r / stdev_r) * math.sqrt(len(returns)) if stdev_r > 1e-12 else 0.0
        else:
            sharpe = 0.0

        if attack_detection_latencies_ms:
            attack_detection_latency_ms_first = attack_detection_latencies_ms[0]
            attack_detection_latency_ms_mean = statistics.mean(attack_detection_latencies_ms)
            attack_detection_latency_ms_max = max(attack_detection_latencies_ms)
        else:
            attack_detection_latency_ms_first = 0.0
            attack_detection_latency_ms_mean = 0.0
            attack_detection_latency_ms_max = 0.0

        # Compute permutation test for Sharpe significance
        permutation_p_value = 1.0
        if len(equity_net_history) >= 10:
            perm_result = run_permutation_test(equity_net_history, num_shuffles=1000)
            permutation_p_value = perm_result.p_value

        metrics = BacktestMetrics(
            run_id=datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
            start_time=_utc(self.config.start_time),
            end_time=_utc(self.config.end_time),
            symbol=self.config.symbol,
            scenario=self.config.scenario,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            sharpe_ratio=sharpe,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            end_to_end_latency_ms=(total_latency_ms / scored_total) if scored_total else 0.0,
            normal_state_pct=(normal_count / scored_total) if scored_total else 0.0,
            permutation_p_value=permutation_p_value,
            equity_curve_path=str(output_dir / "equity_curve.csv"),
            injected_anomalies=injected_anomalies,
            detected_anomalies=detected_anomalies,
            false_positives=false_positives,
            attack_episode_count=attack_episode_count,
            attack_episode_detected_count=attack_episode_detected_count,
            attack_detection_latency_ms_first=attack_detection_latency_ms_first,
            attack_detection_latency_ms_mean=attack_detection_latency_ms_mean,
            attack_detection_latency_ms_max=attack_detection_latency_ms_max,
            risk_approved_orders=locals().get("approved_orders", 0),
            risk_rejected_orders=locals().get("rejected_orders", 0),
            risk_reduced_ticks=locals().get("reduced_state_ticks", 0),
            risk_halted_ticks=locals().get("halted_state_ticks", 0),
            total_ticks=scored_total,
            events=events,
        )

        equity_path = output_dir / "equity_curve.csv"
        metrics_path = output_dir / "metrics.json"
        config_path = output_dir / "config_snapshot.json"
        report_path = output_dir / "report.html"

        # write per-trade ledger if any trades occurred
        ledger_path = output_dir / "per_trade_ledger.csv"
        if per_trade_rows:
            with open(ledger_path, "w", encoding="utf-8", newline="") as lf:
                fieldnames = [
                    "trade_id",
                    "client_order_id",
                    "signal_ts",
                    "submit_ts",
                    "ack_ts",
                    "first_fill_ts",
                    "last_fill_ts",
                    "fill_price",
                    "fill_fraction",
                    "side",
                    "size_pct",
                    "fee",
                    "slippage_pct",
                    "final_state",
                    "exit_reason",
                    "net_pnl",
                ]
                writer = csv.DictWriter(lf, fieldnames=fieldnames)
                writer.writeheader()
                for r in per_trade_rows:
                    writer.writerow(r)

        # write a simple reconciliation report built from persisted store if present,
        # otherwise reflect observed executions
        reconciliation_path = output_dir / "reconciliation_report.json"
        reconciliation: list[dict[str, object]] = []
        try:
            if execution_engine.store is not None:
                # compare persisted orders to in-memory executions
                pending = execution_engine.store.fetch_pending()
                for p in pending:
                    reconciliation.append({
                        "wal_id": p.client_order_id,
                        "client_order_id": p.client_order_id,
                        "wal_state": p.status,
                        "adapter_state": execution_engine.get_execution(p.client_order_id).note if execution_engine.get_execution(p.client_order_id) is not None else None,
                        "wal_ts": p.timestamp_utc,
                        "adapter_ts": None,
                        "delta_ms": None,
                        "resolved": False,
                        "notes": "pending in store",
                    })
            else:
                # derive from per_trade_rows and engine executions
                for r in per_trade_rows:
                    exec_obj = execution_engine.get_execution(r.get("client_order_id"))
                    reconciliation.append({
                        "wal_id": r.get("client_order_id"),
                        "client_order_id": r.get("client_order_id"),
                        "wal_state": "NONE",
                        "adapter_state": exec_obj.note if exec_obj is not None else None,
                        "wal_ts": r.get("submit_ts"),
                        "adapter_ts": r.get("ack_ts"),
                        "delta_ms": (r.get("ack_ts") - r.get("submit_ts")) if r.get("ack_ts") and r.get("submit_ts") else None,
                        "resolved": True,
                        "notes": "backtest execution observed",
                    })
        except Exception:
            reconciliation.append({"error": "failed to generate reconciliation report"})

        reconciliation_path.write_text(json.dumps(reconciliation, indent=2, sort_keys=True), encoding="utf-8")

        self._write_equity_curve(equity_rows, equity_path)
        metrics_path.write_text(json.dumps(metrics.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        config_path.write_text(json.dumps(self._config_snapshot(), indent=2, sort_keys=True), encoding="utf-8")
        report_path = BacktestReportGenerator(output_dir).write_report(config=self.config, metrics=metrics)

        db_path = self.config.results_db_path or (self.config.output_dir / "results.db")
        ResultsDB(db_path).save_run(metrics)

        return BacktestResult(
            config=self.config,
            metrics=metrics,
            report_path=report_path,
            equity_curve_path=equity_path,
        )

    def _config_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "symbol": self.config.symbol,
            "scenario": self.config.scenario,
            "start_time": _utc(self.config.start_time).isoformat(),
            "end_time": _utc(self.config.end_time).isoformat(),
            "output_dir": str(self.config.output_dir),
            "source_path": str(self.config.source_path) if self.config.source_path else None,
            "cache_path": str(self.config.cache_path) if self.config.cache_path else None,
            "results_db_path": str(self.config.results_db_path) if self.config.results_db_path else None,
            "hmm_model_path": str(self.config.hmm_model_path),
            "trust_weights_path": str(self.config.trust_weights_path) if self.config.trust_weights_path else None,
            "primary_exchange": self.config.primary_exchange,
            "enabled_exchanges": list(self.config.enabled_exchanges),
            "window_ms": self.config.window_ms,
            "time_speed": self.config.time_speed,
            "if_weight": self.config.if_weight,
            "hst_weight": self.config.hst_weight,
            "trust_threshold": self.config.trust_threshold,
            "anomaly_threshold": self.config.anomaly_threshold,
        }
        return snapshot


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point for the backtest package."""

    parser = argparse.ArgumentParser(description="Phase 5 backtesting engine")
    parser.add_argument("--symbol", default="BTCUSDT", help="Symbol to replay")
    parser.add_argument("--scenario", default="baseline", help="Scenario label for the run")
    parser.add_argument("--start", required=True, help="Replay start timestamp (YYYY-MM-DD or ISO-8601)")
    parser.add_argument("--end", required=True, help="Replay end timestamp (YYYY-MM-DD or ISO-8601)")
    parser.add_argument("--source-path", default=None, help="CSV/JSONL/SQLite historical input")
    parser.add_argument("--cache-path", default=None, help="Optional SQLite cache path")
    parser.add_argument("--results-db", default=None, help="Optional SQLite results database path")
    parser.add_argument("--output-dir", default=os.path.join("artifacts", "reports"), help="Output directory")
    parser.add_argument("--hmm-model-path", default=os.path.join("artifacts", "hmm", "model.pkl"), help="Trained HMM model")
    parser.add_argument("--time-speed", type=float, default=1.0, help="Deterministic replay speed factor")
    args = parser.parse_args(argv)

    config = BacktestConfig(
        symbol=args.symbol,
        scenario=args.scenario,
        start_time=datetime.fromisoformat(args.start),
        end_time=datetime.fromisoformat(args.end),
        output_dir=Path(args.output_dir),
        source_path=Path(args.source_path) if args.source_path else None,
        cache_path=Path(args.cache_path) if args.cache_path else None,
        results_db_path=Path(args.results_db) if args.results_db else None,
        hmm_model_path=Path(args.hmm_model_path),
        time_speed=args.time_speed,
    )
    result = BacktestEngine(config).run()

    print(json.dumps(result.metrics.to_dict(), indent=2, sort_keys=True))
    print(f"metrics: {result.report_path}")
    print(f"equity curve: {result.equity_curve_path}")
    return 0
"""Layer 1 merged service - Ingestion + Validation in one process.

Eliminates the Kafka hop between ingestion and validation, reducing latency from 5-10ms to <1ms.
Uses an in-memory async queue for tick passing.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, cast

from prometheus_client import Counter, Gauge, Histogram

from services.layer1_consensus.engine import AlignedWindow, ConsensusConfig, ConsensusEngine, TickAligner
from services.layer1_consensus.window_config import load_window_config
from services.layer1_hashlog.hash_chain import HashChainLogger
from services.layer1_trust.scoring import TrustWeights, compute_subscores, compute_t2, compute_trust_score, load_trust_weights
from services.layer1_validated.liveness import ExchangeLivenessMonitor
from services.layer1_validated.kafka_json_publisher import KafkaJsonPublisher, KafkaJsonPublisherConfig
from shared.audit import emit_audit_event
from shared.metrics_http import start_metrics_http_server
from shared.service_health import mark_service_healthy
from shared.schemas import ExchangeId, NormalizedTick, ValidatedTick
from shared.tls_health_registry import get_tls_health_registry

# Import adapters
from services.layer1_ingestion.adapters.binance import BinanceAdapter
from services.layer1_ingestion.adapters.bybit import BybitAdapter
from services.layer1_ingestion.adapters.coinbase import CoinbaseAdapter
from services.layer1_ingestion.adapters.kraken import KrakenAdapter
from services.layer1_ingestion.adapters.okx import OkxAdapter


# === INGESTION METRICS ===
_ingestion_ticks_total = Counter(
    "layer1_merged_ingestion_ticks_total",
    "Total normalized ticks from adapters",
    ["exchange"],
)

_ingestion_queue_depth = Gauge(
    "layer1_merged_queue_depth",
    "Current depth of in-memory tick queue",
)

# === VALIDATION METRICS ===
_validation_ticks_total = Counter(
    "layer1_merged_validation_ticks_total",
    "Total ticks processed by validation",
)

_windows_total = Counter(
    "layer1_merged_windows_total",
    "Total aligned windows processed",
    ["symbol"],
)

_published_total = Counter(
    "layer1_merged_published_total",
    "Total validated ticks published",
    ["symbol"],
)

_last_trust_score = Gauge(
    "layer1_merged_last_trust_score",
    "Most recent trust score",
    ["symbol"],
)

_last_window_sources = Gauge(
    "layer1_merged_last_window_sources",
    "Number of sources in last window",
    ["symbol"],
)

_last_window_used_sources = Gauge(
    "layer1_merged_last_window_used_sources",
    "Number of sources used in consensus",
    ["symbol"],
)

_last_window_latency_ms = Gauge(
    "layer1_merged_last_window_latency_ms",
    "Median latency from exchange to publish",
    ["symbol"],
)

_trust_t1_tls = Gauge(
    "trust_subscore_t1_tls",
    "T1: TLS validity subscore",
    ["symbol", "exchange_id"]
)

_trust_t2_consensus = Gauge(
    "trust_subscore_t2_consensus",
    "T2: Consensus agreement subscore",
    ["symbol"]
)

_trust_t3_freshness = Gauge(
    "trust_subscore_t3_freshness",
    "T3: Latency freshness subscore",
    ["symbol"]
)

_trust_t4_sequence = Gauge(
    "trust_subscore_t4_sequence",
    "T4: Sequence integrity subscore",
    ["symbol", "exchange_id"]
)

_trust_t5_hashchain = Gauge(
    "trust_subscore_t5_hashchain",
    "T5: Hash chain continuity subscore",
    ["symbol"]
)

_trust_t_availability = Gauge(
    "trust_subscore_t_availability",
    "T_availability: Exchange availability subscore",
    ["symbol"]
)

_consensus_divergent_sources = Gauge(
    "consensus_divergent_source_count",
    "Number of divergent sources",
    ["symbol"]
)

_active_exchange_count = Gauge(
    "active_exchange_count",
    "Number of active exchanges",
    ["symbol"],
)

_silent_exchange_count = Gauge(
    "silent_exchange_count",
    "Number of exchanges excluded due to silence (liveness monitor)",
    ["symbol"],
)

_availability_score = Gauge(
    "availability_score",
    "Exchange availability score",
    ["symbol"],
)

_sequence_gap_per_exchange = Gauge(
    "sequence_gap_per_exchange",
    "Sequence ID gap per exchange (1=no gap, >1=gap detected)",
    ["symbol", "exchange_id"],
)

_sequence_gap_max = Gauge(
    "sequence_gap_max",
    "Maximum sequence gap across all exchanges (used for T4)",
    ["symbol"],
)

_circuit_breaker_state = Gauge(
    "consensus_circuit_breaker_state",
    "Circuit breaker state (0=closed/normal, 1=open/halted)",
    ["symbol"],
)

_consecutive_consensus_failures = Gauge(
    "consecutive_consensus_failures",
    "Number of consecutive consensus failures",
    ["symbol"],
)

_tls_healthy_count = Gauge(
    "tls_healthy_exchange_count",
    "Number of exchanges with healthy TLS",
    ["symbol"],
)

_tls_unhealthy_count = Gauge(
    "tls_unhealthy_exchange_count",
    "Number of exchanges with unhealthy TLS",
    ["symbol"],
)

_latency_per_exchange = Gauge(
    "latency_per_exchange_ms",
    "Latency per exchange in milliseconds",
    ["symbol", "exchange_id", "timestamp_source"],
)

# Circuit breaker configuration
CIRCUIT_BREAKER_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "10"))
CIRCUIT_BREAKER_RESET_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_RESET_THRESHOLD", "5"))

def _parse_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _enabled_exchanges() -> list[ExchangeId]:
    raw = os.getenv("EXCHANGES", "binance,bybit,coinbase,kraken,okx")
    xs = _parse_csv(raw)
    return [x for x in xs if x in {"binance", "coinbase", "kraken", "okx", "bybit"}]  # type: ignore[return-value]


def _primary_exchange(enabled_exchanges: list[ExchangeId]) -> ExchangeId:
    configured = os.getenv("PRIMARY_EXCHANGE", "binance")
    if configured in enabled_exchanges:
        return cast(ExchangeId, configured)

    if not enabled_exchanges:
        raise RuntimeError("No enabled exchanges configured")

    emit_audit_event(
        "layer1.merged.primary_exchange.fallback",
        source="layer1_merged",
        payload={
            "configured": configured,
            "fallback": enabled_exchanges[0],
            "enabled_exchanges": enabled_exchanges,
        },
    )
    return enabled_exchanges[0]


def _median_latency_ms(ticks: List[NormalizedTick], *, now_ms: int) -> float:
    """Compute median latency across all ticks.
    
    For exchanges with exchange_timestamp (Binance, Coinbase, OKX, Bybit):
        latency = now - exchange_timestamp
    
    For exchanges with receive_timestamp only (Kraken):
        latency = now - received_timestamp
    
    This ensures all exchanges contribute to the latency metric.
    """
    tick_list = list(ticks)
    latencies = []
    
    for t in tick_list:
        timestamp_source = getattr(t, "timestamp_source", "exchange")
        
        if timestamp_source == "exchange" and t.exchange_timestamp_ms is not None:
            # Use exchange timestamp (more accurate)
            latency = max(0, int(now_ms) - int(t.exchange_timestamp_ms))
            latencies.append(latency)
        elif t.received_timestamp_ms is not None:
            # Use receive timestamp (fallback for Kraken)
            latency = max(0, int(now_ms) - int(t.received_timestamp_ms))
            latencies.append(latency)
    
    if latencies:
        return float(statistics.median(latencies))
    
    return float("inf")

def _median_spread(ticks: List[NormalizedTick]) -> float:
    spreads: List[float] = []
    for t in ticks:
        mid = t.mid
        if mid <= 0:
            continue
        spreads.append(max(0.0, (t.ask - t.bid) / mid))
    if not spreads:
        return 0.0
    return float(statistics.median(spreads))


def _median_volume_24h(ticks: List[NormalizedTick]) -> float:
    vols = [max(0.0, float(t.volume_24h)) for t in ticks]
    if not vols:
        return 0.0
    return float(statistics.median(vols))


@dataclass
class Layer1MergedService:
    """Merged ingestion + validation service."""
    
    # Validation components
    publisher: KafkaJsonPublisher
    consensus: ConsensusEngine
    aligner: TickAligner
    weights: TrustWeights
    hashlog: HashChainLogger
    enabled_exchanges: List[ExchangeId]
    primary_exchange: ExchangeId
    liveness: ExchangeLivenessMonitor
    tls_registry: any
    
    # Ingestion components
    symbols: List[str]
    adapters: List[any]
    
    # State
    _last_sequence_ids: Dict[Tuple[str, ExchangeId], int]
    _last_liveness_overdue: Dict[str, float]
    _last_liveness_check_s: float
    _last_trust_scores: Dict[str, float]
    _consecutive_consensus_failures: Dict[str, int]  # Track failures per symbol
    _circuit_breaker_open: Dict[str, bool]  # Circuit breaker state per symbol
    _stop: asyncio.Event
    
    # In-memory queue
    _tick_queue: asyncio.Queue[NormalizedTick]

    def _compute_sequence_gap(
        self,
        *,
        symbol: str,
        exchange: ExchangeId,
        sequence_id: Optional[int],
    ) -> Optional[int]:
        if sequence_id is None:
            return None

        key = (symbol, exchange)
        current = int(sequence_id)
        previous = self._last_sequence_ids.get(key)
        if previous is None:
            self._last_sequence_ids[key] = current
            return 1

        gap = current - previous
        if gap <= 0:
            emit_audit_event(
                "layer1.merged.sequence.non_monotonic",
                source="layer1_merged",
                payload={
                    "symbol": symbol,
                    "exchange_id": exchange,
                    "previous_sequence_id": previous,
                    "current_sequence_id": current,
                    "computed_gap": gap,
                },
            )
            self._last_sequence_ids[key] = max(previous, current)
            return 10

        self._last_sequence_ids[key] = current
        if gap > 1:
            emit_audit_event(
                "layer1.merged.sequence.gap",
                source="layer1_merged",
                payload={
                    "symbol": symbol,
                    "exchange_id": exchange,
                    "previous_sequence_id": previous,
                    "current_sequence_id": current,
                    "computed_gap": gap,
                },
            )
        return gap

    async def _adapter_task(self, adapter: any) -> None:
        """Run adapter and feed ticks into queue."""
        async for tick in adapter.run_forever():
            if self._stop.is_set():
                break
            
            _ingestion_ticks_total.labels(exchange=adapter.exchange_id).inc()
            
            try:
                self._tick_queue.put_nowait(tick)
                _ingestion_queue_depth.set(self._tick_queue.qsize())
            except asyncio.QueueFull:
                # Queue full - drop oldest tick
                try:
                    _ = self._tick_queue.get_nowait()
                    self._tick_queue.put_nowait(tick)
                    _ingestion_queue_depth.set(self._tick_queue.qsize())
                    emit_audit_event(
                        "layer1.merged.queue.overflow",
                        source="layer1_merged",
                        payload={"exchange": adapter.exchange_id, "action": "dropped_oldest"},
                    )
                except:
                    pass

    async def _validation_task(self) -> None:
        """Process ticks from queue through validation pipeline."""
        while not self._stop.is_set():
            try:
                tick = await asyncio.wait_for(self._tick_queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            
            _validation_ticks_total.inc()
            _ingestion_queue_depth.set(self._tick_queue.qsize())
            
            self.liveness.record_tick(tick.exchange_id)
            now_s = time.time()
            if now_s - self._last_liveness_check_s >= 1.0:
                self._last_liveness_overdue = self.liveness.check_all()
                self._last_liveness_check_s = now_s

            for window in self.aligner.add(tick):
                self._process_window(window)

    def _process_window(self, window: AlignedWindow) -> None:
        """Process aligned window through consensus and trust scoring."""
        symbol = window.symbol
        by_ex = window.by_ex

        _windows_total.labels(symbol=symbol).inc()
        _last_window_sources.labels(symbol=symbol).set(float(len(by_ex)))
        
        out = self.consensus.process_aligned(symbol, by_ex)
        
        # Circuit breaker: Track consecutive consensus failures
        if out.consensus_mid is None:
            # Increment failure counter
            self._consecutive_consensus_failures[symbol] = self._consecutive_consensus_failures.get(symbol, 0) + 1
            failures = self._consecutive_consensus_failures[symbol]
            
            _consecutive_consensus_failures.labels(symbol=symbol).set(failures)
            
            # Check if circuit breaker should open
            if failures >= CIRCUIT_BREAKER_THRESHOLD and not self._circuit_breaker_open.get(symbol, False):
                self._circuit_breaker_open[symbol] = True
                _circuit_breaker_state.labels(symbol=symbol).set(1)
                
                emit_audit_event(
                    "consensus.circuit_breaker.open",
                    source="layer1_merged",
                    payload={
                        "symbol": symbol,
                        "consecutive_failures": failures,
                        "threshold": CIRCUIT_BREAKER_THRESHOLD,
                        "message": f"Circuit breaker OPEN: {failures} consecutive consensus failures",
                    },
                )
            
            # If circuit breaker is open, log and skip
            if self._circuit_breaker_open.get(symbol, False):
                emit_audit_event(
                    "consensus.circuit_breaker.skip",
                    source="layer1_merged",
                    payload={
                        "symbol": symbol,
                        "consecutive_failures": failures,
                        "message": "Skipping tick due to open circuit breaker",
                    },
                )
            
            return
        
        # Consensus succeeded - reset failure counter
        previous_failures = self._consecutive_consensus_failures.get(symbol, 0)
        self._consecutive_consensus_failures[symbol] = 0
        _consecutive_consensus_failures.labels(symbol=symbol).set(0)
        
        # Check if circuit breaker should close (after N successful consensuses)
        if self._circuit_breaker_open.get(symbol, False):
            # Circuit breaker is open, but we got a successful consensus
            # Close it after CIRCUIT_BREAKER_RESET_THRESHOLD consecutive successes
            # For simplicity, close immediately on first success
            self._circuit_breaker_open[symbol] = False
            _circuit_breaker_state.labels(symbol=symbol).set(0)
            
            emit_audit_event(
                "consensus.circuit_breaker.close",
                source="layer1_merged",
                payload={
                    "symbol": symbol,
                    "previous_failures": previous_failures,
                    "message": "Circuit breaker CLOSED: consensus recovered",
                },
            )

        usable_ticks = [tick for ex, tick in by_ex.items() if ex in out.used_sources]
        
        if not usable_ticks:
            return

        tolerance = abs(out.consensus_mid) * float(self.consensus.config.divergence_tolerance)
        t2 = compute_t2(
            ticks_with_age=window.ticks_with_age,
            consensus_price=out.consensus_mid,
            tolerance=tolerance,
            active_sources=window.active_sources,
        )

        # Compute median latency and emit per-exchange latency metrics
        latency_ms = _median_latency_ms(usable_ticks, now_ms=window.window_end_ms)
        _last_window_latency_ms.labels(symbol=symbol).set(latency_ms)
        
        # Emit per-exchange latency metrics for observability
        for exchange, tick in by_ex.items():
            if exchange in out.used_sources:
                timestamp_source = getattr(tick, "timestamp_source", "exchange")
                
                if timestamp_source == "exchange" and tick.exchange_timestamp_ms is not None:
                    latency = max(0, int(window.window_end_ms) - int(tick.exchange_timestamp_ms))
                    _latency_per_exchange.labels(
                        symbol=symbol,
                        exchange_id=exchange,
                        timestamp_source="exchange"
                    ).set(latency)
                elif tick.received_timestamp_ms is not None:
                    latency = max(0, int(window.window_end_ms) - int(tick.received_timestamp_ms))
                    _latency_per_exchange.labels(
                        symbol=symbol,
                        exchange_id=exchange,
                        timestamp_source="receive"
                    ).set(latency)
        
        _last_window_used_sources.labels(symbol=symbol).set(float(len(out.used_sources)))

        spread = _median_spread(usable_ticks)
        volume_24h = _median_volume_24h(usable_ticks)

        # TLS health: pessimistic approach (all must be healthy)
        # Security-focused: if ANY exchange has bad TLS, trust should degrade
        # Majority vote is too optimistic (3/5 bad = still "healthy")
        tls_states = [getattr(tick, 'tls_ok', False) for tick in usable_ticks]
        tls_ok = all(tls_states) if tls_states else False
        
        # Track TLS health per exchange for observability
        tls_healthy_count = sum(tls_states)
        tls_total_count = len(tls_states)
        tls_unhealthy_count = tls_total_count - tls_healthy_count
        
        _tls_healthy_count.labels(symbol=symbol).set(tls_healthy_count)
        _tls_unhealthy_count.labels(symbol=symbol).set(tls_unhealthy_count)
        
        # Emit audit event if any exchange has bad TLS
        if tls_unhealthy_count > 0:
            unhealthy_exchanges = [
                ex for ex, tick in zip(out.used_sources, usable_ticks)
                if not getattr(tick, 'tls_ok', False)
            ]
            emit_audit_event(
                "layer1.merged.tls.unhealthy",
                source="layer1_merged",
                payload={
                    "symbol": symbol,
                    "unhealthy_exchanges": unhealthy_exchanges,
                    "healthy_count": tls_healthy_count,
                    "unhealthy_count": tls_unhealthy_count,
                },
            )
        
        _active_exchange_count.labels(symbol=symbol).set(float(len(out.used_sources)))

        # Sequence gap tracking for ALL exchanges
        # Compute T4 for each exchange that has sequence IDs, then aggregate
        sequence_gaps = {}
        for exchange, tick in by_ex.items():
            if tick.sequence_id is not None:
                gap = self._compute_sequence_gap(
                    symbol=symbol,
                    exchange=exchange,
                    sequence_id=tick.sequence_id,
                )
                sequence_gaps[exchange] = gap
                # Emit per-exchange metric
                _sequence_gap_per_exchange.labels(symbol=symbol, exchange_id=exchange).set(gap)
        
        # Aggregate sequence gap for trust scoring
        # Use the WORST (maximum) gap among all exchanges
        # This is conservative: if ANY exchange has gaps, trust degrades
        if sequence_gaps:
            sequence_gap = max(sequence_gaps.values())
            _sequence_gap_max.labels(symbol=symbol).set(sequence_gap)
        else:
            sequence_gap = None

        previous_hash = self.hashlog.tip
        chain_ok = True

        # Compute subscores
        active_exchanges_set = set(out.used_sources)
        
        # Exclude exchanges that are silent (detected by liveness monitor)
        # If an exchange hasn't sent a tick in >30s, it's using stale LKV data
        # and should not be counted as "active" for T_availability
        silent_count = 0
        for silent_exchange in self._last_liveness_overdue.keys():
            if silent_exchange in active_exchanges_set:
                active_exchanges_set.discard(silent_exchange)
                silent_count += 1
        
        # Emit metric for silent exchanges
        _silent_exchange_count.labels(symbol=symbol).set(silent_count)
        
        configured_exchanges_set = set(self.enabled_exchanges)
        
        subscores = compute_subscores(
            tls_ok=tls_ok,
            t2=t2,
            latency_ms=latency_ms,
            sequence_gap=sequence_gap,
            chain_ok=chain_ok,
            active_exchanges=active_exchanges_set,
            configured_exchanges=configured_exchanges_set,
        )
        
        availability = subscores.get("T_availability", 1.0)
        _availability_score.labels(symbol=symbol).set(availability)
        
        trust_score = compute_trust_score(weights=self.weights, subscores=subscores)
        _last_trust_score.labels(symbol=symbol).set(trust_score)
        
        # Export trust subcomponents (T1 and T4 are per-exchange, others are per-symbol)
        # For aggregated metrics, use primary exchange as representative
        _trust_t1_tls.labels(symbol=symbol, exchange_id=self.primary_exchange).set(subscores["T1"])
        _trust_t2_consensus.labels(symbol=symbol).set(subscores["T2"])
        _trust_t3_freshness.labels(symbol=symbol).set(subscores["T3"])
        _trust_t4_sequence.labels(symbol=symbol, exchange_id=self.primary_exchange).set(subscores["T4"])
        _trust_t5_hashchain.labels(symbol=symbol).set(subscores["T5"])
        _trust_t_availability.labels(symbol=symbol).set(subscores.get("T_availability", 1.0))
        
        _consensus_divergent_sources.labels(symbol=symbol).set(len(out.divergent_sources))
        
        self._last_trust_scores[symbol] = trust_score

        # Build execution venue prices
        execution_venue_prices = {ex: tick.mid for ex, tick in by_ex.items()}

        tick_hash, _ = self.hashlog.append(
            symbol=symbol,
            primary_exchange=self.primary_exchange,
            primary_mid_price=out.consensus_mid,
            consensus_mid=out.consensus_mid,
            used_sources=out.used_sources,
            divergent_sources=out.divergent_sources,
            trust_score=trust_score,
            received_timestamp_ms=window.window_end_ms,
            previous_hash=previous_hash,
        )

        validated = ValidatedTick(
            symbol=symbol,
            primary_exchange=self.primary_exchange,
            mid_price=out.consensus_mid,
            consensus_mid=out.consensus_mid,
            execution_venue_prices=execution_venue_prices,
            volume_24h=volume_24h,
            spread=spread,
            trust_score=trust_score,
            sub_scores=subscores,
            used_sources=out.used_sources,
            divergent_sources=out.divergent_sources,
            timestamp_utc=window.window_end_ms,
            tick_hash=tick_hash,
            liveness=self._last_liveness_overdue or None,
        )

        self.publisher.publish(validated.model_dump())
        _published_total.labels(symbol=symbol).inc()

    async def run_forever(self) -> None:
        """Run merged service with adapters and validation."""
        emit_audit_event(
            "layer1.merged.start",
            source="layer1_merged",
            payload={
                "symbols": self.symbols,
                "exchanges": [str(e) for e in self.enabled_exchanges],
                "validated_topic": self.publisher.topic,
            },
        )

        # Start adapter tasks
        adapter_tasks = [
            asyncio.create_task(self._adapter_task(adapter), name=f"adapter-{adapter.exchange_id}")
            for adapter in self.adapters
        ]
        
        # Start validation task
        validation_task = asyncio.create_task(self._validation_task(), name="validation")
        
        try:
            await self._stop.wait()
        finally:
            # Cancel all tasks
            for task in adapter_tasks + [validation_task]:
                task.cancel()
            
            await asyncio.gather(*adapter_tasks, validation_task, return_exceptions=True)
            
            # Close adapters
            for adapter in self.adapters:
                await adapter.close()
            
            # Stop services
            self.hashlog.stop()
            self.publisher.stop()


def build_service() -> Layer1MergedService:
    """Build merged Layer 1 service."""
    enabled_exchanges = _enabled_exchanges()
    primary_exchange = _primary_exchange(enabled_exchanges)
    symbols = _parse_csv(os.getenv("SYMBOLS", "BTC-USDT,ETH-USDT"))

    # Build adapters
    adapters = []
    if "binance" in enabled_exchanges:
        adapters.append(BinanceAdapter(symbols))
    if "coinbase" in enabled_exchanges:
        adapters.append(CoinbaseAdapter(symbols))
    if "kraken" in enabled_exchanges:
        adapters.append(KrakenAdapter(symbols))
    if "okx" in enabled_exchanges:
        adapters.append(OkxAdapter(symbols))
    if "bybit" in enabled_exchanges:
        adapters.append(BybitAdapter(symbols))

    # Build validation components
    pub_cfg = KafkaJsonPublisherConfig.from_env(
        topic_env="KAFKA_VALIDATED_TOPIC",
        default_topic="market.ticks.validated"
    )
    publisher = KafkaJsonPublisher(pub_cfg, client_id="layer1_merged")
    publisher.start()

    weights = load_trust_weights()

    consensus_cfg = ConsensusConfig(
        divergence_tolerance=float(os.getenv("CONSENSUS_DIVERGENCE_TOL", "0.003")),
        aggregation_window_ms=int(os.getenv("CONSENSUS_WINDOW_MS", "50")),
        escalate_after=int(os.getenv("CONSENSUS_ESCALATE_AFTER", "3")),
        min_sources_for_consensus=int(os.getenv("CONSENSUS_MIN_SOURCES", "2")),
    )

    consensus = ConsensusEngine(consensus_cfg)
    
    # Load per-symbol window configuration
    try:
        window_config = load_window_config()
        emit_audit_event(
            "layer1.merged.window_config.loaded",
            source="layer1_merged",
            payload={
                "default_window_ms": window_config.default_window_ms,
                "symbol_overrides": window_config.symbol_overrides,
            },
        )
    except Exception as e:
        emit_audit_event(
            "layer1.merged.window_config.load_failed",
            source="layer1_merged",
            payload={"error": repr(e), "using_default": consensus_cfg.aggregation_window_ms},
        )
        window_config = None
    
    aligner = TickAligner(
        window_ms=consensus_cfg.aggregation_window_ms,
        window_config=window_config,
    )

    log_path = os.getenv("HASH_CHAIN_LOG_PATH", os.path.join("logs", "layer1_hash_chain.jsonl"))
    hashlog = HashChainLogger(path=log_path)
    hashlog.start()

    def _audit(event_type: str, payload: Dict) -> None:
        emit_audit_event(event_type, source="layer1_merged", payload=payload)

    liveness = ExchangeLivenessMonitor(
        sources=[str(x) for x in enabled_exchanges],
        audit_fn=_audit,
    )
    
    tls_registry = get_tls_health_registry()
    
    # Create in-memory queue
    queue_size = int(os.getenv("TICK_QUEUE_SIZE", "10000"))
    tick_queue: asyncio.Queue[NormalizedTick] = asyncio.Queue(maxsize=queue_size)

    return Layer1MergedService(
        publisher=publisher,
        consensus=consensus,
        aligner=aligner,
        weights=weights,
        hashlog=hashlog,
        enabled_exchanges=enabled_exchanges,
        primary_exchange=primary_exchange,
        liveness=liveness,
        tls_registry=tls_registry,
        symbols=symbols,
        adapters=adapters,
        _last_sequence_ids={},
        _last_liveness_overdue={},
        _last_liveness_check_s=0.0,
        _last_trust_scores={},
        _consecutive_consensus_failures={},
        _circuit_breaker_open={},
        _stop=asyncio.Event(),
        _tick_queue=tick_queue,
    )


async def main() -> None:
    """Main entry point."""
    start_metrics_http_server(port=int(os.getenv("METRICS_PORT", "9101")))
    mark_service_healthy("layer1_merged", "layer1")

    svc = build_service()
    
    # Setup signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, svc._stop.set)
        except NotImplementedError:
            pass  # Windows doesn't support SIGTERM handler
    
    await svc.run_forever()


if __name__ == "__main__":
    asyncio.run(main())

"""Prometheus metrics for Layer 2 Anomaly Detection.

This module defines and manages all Prometheus metrics for observability.
Metrics are exposed on port 9103 for scraping by Prometheus.
"""

from prometheus_client import Counter, Gauge, Histogram, start_http_server
from typing import Dict


class Layer2Metrics:
    """Prometheus metrics manager for Layer 2.
    
    Metrics Categories:
        1. Detector Scores: Individual detector outputs
        2. Final Score: Fused anomaly score
        3. System State: Decision Gate state
        4. Performance: Processing latency
        5. Coincidence: Multi-detector events (Phase 2)
        6. Regime: HMM regime classification (Phase 2)
    
    Example:
        >>> metrics = Layer2Metrics()
        >>> metrics.start_server(port=9103)
        >>> metrics.update_detector_score("BTCUSDT", "mad", 0.65)
        >>> metrics.update_final_score("BTCUSDT", 0.45)
    """
    
    def __init__(self):
        """Initialize all Prometheus metrics."""
        
        # Detector scores (one gauge per detector)
        self.detector_score = Gauge(
            'layer2_detector_score',
            'Individual detector anomaly score',
            ['symbol', 'detector']
        )
        
        # Final fused anomaly score
        self.final_anomaly_score = Gauge(
            'layer2_final_anomaly_score',
            'Final fused anomaly score after fusion',
            ['symbol']
        )
        
        # System state (0=NORMAL, 1=CONSERVATIVE, 2=DEGRADED, 3=HALT)
        self.system_state = Gauge(
            'layer2_system_state',
            'Decision Gate system state (0=NORMAL, 1=CONSERVATIVE, 2=DEGRADED, 3=HALT)',
            ['symbol']
        )
        
        # Processing latency histogram
        self.processing_latency = Histogram(
            'layer2_processing_latency_ms',
            'Per-tick processing latency in milliseconds',
            ['symbol'],
            buckets=[0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 10.0, 20.0, 50.0]
        )
        
        # Phase 2 metrics (not used in Phase 1)
        self.coincidence_triggers = Counter(
            'layer2_coincidence_triggers_total',
            'Number of times coincidence logic triggered',
            ['symbol']
        )
        
        self.detector_reasons = Counter(
            'layer2_detector_reasons_total',
            'Count of each detector appearing in anomaly reasons',
            ['symbol', 'reason']
        )
        
        self.hmm_regime = Gauge(
            'layer2_hmm_regime',
            'Current HMM regime (0=low volatility, 1=high volatility)',
            ['symbol']
        )
        
        self.regime_threshold_adjustment = Gauge(
            'layer2_regime_threshold_adjustment',
            'Current regime-based threshold adjustment',
            ['symbol']
        )
        
        # Phase 3 metrics
        self.detector_warmup_progress = Gauge(
            'layer2_detector_warmup_progress',
            'Detector warmup progress (0.0 to 1.0)',
            ['symbol', 'detector']
        )
        
        self.detector_threshold = Gauge(
            'layer2_detector_threshold',
            'Current detector threshold value',
            ['symbol', 'detector', 'regime']
        )
        
        self._server_started = False
    
    def start_server(self, port: int = 9103) -> None:
        """Start Prometheus metrics HTTP server.
        
        Args:
            port: Port to expose metrics on (default: 9103)
        
        Note:
            This should be called once at service startup.
        """
        if not self._server_started:
            start_http_server(port)
            self._server_started = True
    
    def update_detector_score(self, symbol: str, detector: str, score: float) -> None:
        """Update individual detector score.
        
        Args:
            symbol: Trading symbol (e.g., "BTCUSDT")
            detector: Detector name (e.g., "mad", "absolute_threshold")
            score: Anomaly score [0.0, 1.0]
        """
        self.detector_score.labels(symbol=symbol, detector=detector).set(score)
    
    def update_final_score(self, symbol: str, score: float) -> None:
        """Update final fused anomaly score.
        
        Args:
            symbol: Trading symbol
            score: Final anomaly score [0.0, 1.0]
        """
        self.final_anomaly_score.labels(symbol=symbol).set(score)
    
    def update_system_state(self, symbol: str, state: int) -> None:
        """Update Decision Gate system state.
        
        Args:
            symbol: Trading symbol
            state: State value (0=NORMAL, 1=CONSERVATIVE, 2=DEGRADED, 3=HALT)
        """
        self.system_state.labels(symbol=symbol).set(state)
    
    def observe_latency(self, symbol: str, latency_ms: float) -> None:
        """Record processing latency.
        
        Args:
            symbol: Trading symbol
            latency_ms: Processing time in milliseconds
        """
        self.processing_latency.labels(symbol=symbol).observe(latency_ms)
    
    def increment_coincidence(self, symbol: str) -> None:
        """Increment coincidence trigger counter (Phase 2).
        
        Args:
            symbol: Trading symbol
        """
        self.coincidence_triggers.labels(symbol=symbol).inc()
    
    def increment_detector_reason(self, symbol: str, reason: str) -> None:
        """Increment detector reason counter (Phase 2).
        
        Args:
            symbol: Trading symbol
            reason: Detector name that contributed to anomaly
        """
        self.detector_reasons.labels(symbol=symbol, reason=reason).inc()
    
    def update_hmm_regime(self, symbol: str, regime: int) -> None:
        """Update HMM regime classification (Phase 2).
        
        Args:
            symbol: Trading symbol
            regime: Regime value (0=low volatility, 1=high volatility)
        """
        self.hmm_regime.labels(symbol=symbol).set(regime)
    
    def update_regime_adjustment(self, symbol: str, adjustment: float) -> None:
        """Update regime threshold adjustment (Phase 2).
        
        Args:
            symbol: Trading symbol
            adjustment: Threshold adjustment value (e.g., -0.10 for regime 0)
        """
        self.regime_threshold_adjustment.labels(symbol=symbol).set(adjustment)
    
    def update_warmup_progress(self, symbol: str, detector: str, progress: float) -> None:
        """Update detector warmup progress (Phase 3).
        
        Args:
            symbol: Trading symbol
            detector: Detector name
            progress: Warmup progress [0.0, 1.0]
        """
        self.detector_warmup_progress.labels(symbol=symbol, detector=detector).set(progress)
    
    def update_detector_threshold(self, symbol: str, detector: str, regime: int, threshold: float) -> None:
        """Update detector threshold value (Phase 3).
        
        Args:
            symbol: Trading symbol
            detector: Detector name
            regime: Regime value (0 or 1)
            threshold: Current threshold value
        """
        self.detector_threshold.labels(
            symbol=symbol,
            detector=detector,
            regime=str(regime)
        ).set(threshold)


# Global metrics instance
_metrics_instance = None


def get_metrics() -> Layer2Metrics:
    """Get global metrics instance (singleton pattern).
    
    Returns:
        Layer2Metrics instance
    """
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = Layer2Metrics()
    return _metrics_instance

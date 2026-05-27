# Design Document: Layer 2 Anomaly Detection System Redesign

## 1. Executive Summary

This document specifies the detailed design for the Layer 2 Anomaly Detection System redesign. The new architecture replaces slow batch-oriented models (Isolation Forest, Half-Space Trees) with a tiered detector stack optimized for real-time streaming data. The system provides:

- **Immediate flash crash detection** (tick 1, no warmup)
- **Multi-detector coincidence checking** (reduces false positives)
- **Full explainability** (every score includes reasons)
- **Sub-5ms latency** (vs current 8+ seconds)
- **Regime-adaptive thresholds** (HMM modifies detector sensitivity)

### Key Design Principles

1. **Tiered Architecture**: Detectors organized by warmup requirements (Tier 1: 0 ticks, Tier 2: 30-50 ticks, Tier 3: cumulative)
2. **Coincidence Logic**: 2+ detectors firing simultaneously = high confidence
3. **Explainability First**: Every anomaly score includes list of contributing detectors
4. **Performance by Design**: All detectors O(1) per tick, no batch operations
5. **Regime Integration**: HMM adjusts thresholds, not used as feature

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Layer 2 Anomaly Detection                     │
└─────────────────────────────────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   Kafka Consumer        │
                    │ market.ticks.validated  │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  ValidatedTick Parser   │
                    └────────────┬────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ HMM Regime    │    │ Detector      │    │ Decision Gate │
│ Classifier    │    │ Stack         │    │ State Machine │
└───────┬───────┘    └───────┬───────┘    └───────┬───────┘
        │                    │                    │
        │  regime={0,1}      │  detector_scores   │  state
        │  posterior=[...]   │  [0.0-1.0]         │  {NORMAL,CONSERVATIVE,
        │                    │                    │   DEGRADED,HALT}
        └────────────────────┼────────────────────┘
                             │
                ┌────────────▼────────────┐
                │   Fusion Engine         │
                │ - Coincidence Check     │
                │ - Weighted Average      │
                │ - Reason Aggregation    │
                └────────────┬────────────┘
                             │
                ┌────────────▼────────────┐
                │  ScoredTick Builder     │
                │ + anomaly_score         │
                │ + anomaly_reasons       │
                │ + system_state          │
                │ + regime                │
                └────────────┬────────────┘
                             │
                ┌────────────▼────────────┐
                │   Kafka Publisher       │
                │ market.ticks.scored     │
                └─────────────────────────┘
```

### 2.2 Detector Stack Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Detector Stack                            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ TIER 1: Zero Warmup (fires on tick 1)                           │
├─────────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────┐  ┌─────────────────────────┐       │
│ │ AbsoluteThreshold       │  │ TrustPassthrough        │       │
│ │ - Price jump >100bps→1.0│  │ - score = 1.0 - trust   │       │
│ │ - Spread >50bps → 0.9   │  │ - Instant conversion    │       │
│ │ - Volume >10x → 0.8     │  │ - <0.1ms latency        │       │
│ │ - <0.5ms latency        │  │                         │       │
│ └─────────────────────────┘  └─────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ TIER 2: Short Warmup (30-50 ticks)                              │
├─────────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────┐  ┌─────────────────────────┐       │
│ │ MADDetector             │  │ VolatilityRatio         │       │
│ │ - Window: 50 ticks      │  │ - rv_30 / rv_300        │       │
│ │ - Regime-aware k        │  │ - Ratio >2.0 → 0.8      │       │
│ │   k=4 (regime 0)        │  │ - Ratio >3.0 → 1.0      │       │
│ │   k=8 (regime 1)        │  │ - <0.5ms latency        │       │
│ │ - <1.0ms latency        │  │                         │       │
│ └─────────────────────────┘  └─────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ TIER 3: Cumulative Drift Detection                              │
├─────────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────┐  ┌─────────────────────────┐       │
│ │ CUSUMDetector           │  │ EWMADetector (2x)       │       │
│ │ - Composite input:      │  │ - EWMA_Price            │       │
│ │   0.5*z_price +         │  │   λ=0.2, L=3.0          │       │
│ │   0.3*z_spread +        │  │ - EWMA_Spread           │       │
│ │   0.2*z_volume          │  │   λ=0.2, L=3.0          │       │
│ │ - Threshold: 5σ         │  │ - <0.5ms each           │       │
│ │ - <0.5ms latency        │  │                         │       │
│ └─────────────────────────┘  └─────────────────────────┘       │
└─────────────────────────────────────────────────────────────────┘

## 3. Component Design

### 3.1 Detector Base Class

All detectors implement a common interface for consistency and testability.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class DetectorScore:
    """Result from a detector."""
    score: float  # [0.0, 1.0] where 0=normal, 1=anomaly
    reason: str   # Human-readable detector name
    warmup_progress: float  # [0.0, 1.0] where 1.0=fully warmed up

class AnomalyDetector(ABC):
    """Base class for all anomaly detectors."""
    
    @abstractmethod
    def update(self, tick_data: dict) -> DetectorScore:
        """Process new tick and return anomaly score.
        
        Args:
            tick_data: Dictionary containing:
                - mid_price: float
                - spread: float
                - volume: float
                - trust_score: float
                - timestamp_ms: int
        
        Returns:
            DetectorScore with score, reason, and warmup_progress
        """
        pass
    
    @abstractmethod
    def get_warmup_ticks_required(self) -> int:
        """Return number of ticks required for warmup."""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Return detector name for logging and explainability."""
        pass
```

### 3.2 Tier 1 Detectors

#### 3.2.1 AbsoluteThresholdDetector

**Purpose**: Catch extreme flash events on first tick without warmup.

**Algorithm**:

```python
class AbsoluteThresholdDetector(AnomalyDetector):
    def __init__(self):
        self._prev_price: Optional[float] = None
        self._volume_history: deque = deque(maxlen=300)  # 5 min at 1 tick/sec
    
    def update(self, tick_data: dict) -> DetectorScore:
        price = tick_data['mid_price']
        spread = tick_data['spread']
        volume = tick_data['volume']
        
        scores = []
        
        # Check 1: Price jump >100bps
        if self._prev_price is not None:
            price_jump_bps = abs(price - self._prev_price) / self._prev_price * 10000
            if price_jump_bps > 100:
                scores.append(1.0)
        
        # Check 2: Spread >50bps
        spread_bps = spread / price * 10000
        if spread_bps > 50:
            scores.append(0.9)
        
        # Check 3: Volume >10x average
        if len(self._volume_history) > 0:
            avg_volume = sum(self._volume_history) / len(self._volume_history)
            if volume > 10 * avg_volume:
                scores.append(0.8)
        
        self._prev_price = price
        self._volume_history.append(volume)
        
        # Return max score if any threshold exceeded
        final_score = max(scores) if scores else 0.0
        return DetectorScore(
            score=final_score,
            reason="absolute_threshold",
            warmup_progress=1.0  # Always ready
        )
```

**Performance**: O(1) per tick, <0.5ms latency

#### 3.2.2 TrustPassthroughDetector

**Purpose**: Convert Layer 1 trust score to anomaly score.

**Algorithm**:

```python
class TrustPassthroughDetector(AnomalyDetector):
    def update(self, tick_data: dict) -> DetectorScore:
        trust_score = tick_data['trust_score']
        anomaly_score = 1.0 - trust_score
        
        return DetectorScore(
            score=anomaly_score,
            reason="trust_passthrough",
            warmup_progress=1.0  # Always ready
        )
```

**Performance**: O(1) per tick, <0.1ms latency

### 3.3 Tier 2 Detectors

#### 3.3.1 MADDetector (Median Absolute Deviation)

**Purpose**: Robust outlier detection for fat-tailed crypto distributions.

**Algorithm**:
```python
class MADDetector(AnomalyDetector):
    def __init__(self, window_size: int = 50):
        self._window_size = window_size
        self._prices: deque = deque(maxlen=window_size)
        self._regime: int = 0  # Updated by HMM
    
    def set_regime(self, regime: int):
        """Called by engine when HMM updates regime."""
        self._regime = regime
    
    def update(self, tick_data: dict) -> DetectorScore:
        price = tick_data['mid_price']
        self._prices.append(price)
        
        if len(self._prices) < self._window_size:
            # Still warming up
            progress = len(self._prices) / self._window_size
            return DetectorScore(score=0.0, reason="mad", warmup_progress=progress)
        
        # Compute MAD
        median = statistics.median(self._prices)
        deviations = [abs(p - median) for p in self._prices]
        mad = statistics.median(deviations)
        
        if mad < 1e-9:
            mad = 1e-9  # Avoid division by zero
        
        # Regime-aware threshold
        k = 4.0 if self._regime == 0 else 8.0
        
        # Current deviation
        current_dev = abs(price - median)
        
        # Score calculation
        if current_dev < k * mad:
            score = 0.0
        elif current_dev >= 2 * k * mad:
            score = 1.0
        else:
            # Linear interpolation between k*MAD and 2*k*MAD
            score = (current_dev - k * mad) / (k * mad)
        
        return DetectorScore(
            score=min(1.0, max(0.0, score)),
            reason="mad",
            warmup_progress=1.0
        )
```

**Performance**: O(n log n) for median calculation where n=50, <1.0ms latency

#### 3.3.2 VolatilityRatioDetector

**Purpose**: Detect regime shifts in real-time by comparing short-term vs long-term volatility.

**Algorithm**:
```python
class VolatilityRatioDetector(AnomalyDetector):
    def __init__(self):
        self._returns_30: deque = deque(maxlen=30)
        self._returns_300: deque = deque(maxlen=300)
        self._prev_price: Optional[float] = None
    
    def update(self, tick_data: dict) -> DetectorScore:
        price = tick_data['mid_price']
        
        if self._prev_price is not None:
            ret = math.log(price / self._prev_price)
            self._returns_30.append(ret)
            self._returns_300.append(ret)
        
        self._prev_price = price
        
        if len(self._returns_300) < 300:
            progress = len(self._returns_300) / 300
            return DetectorScore(score=0.0, reason="volatility_ratio", warmup_progress=progress)
        
        # Compute realized volatility
        rv_30 = math.sqrt(sum(r**2 for r in self._returns_30))
        rv_300 = math.sqrt(sum(r**2 for r in self._returns_300))
        
        if rv_300 < 1e-9:
            rv_300 = 1e-9
        
        ratio = rv_30 / rv_300
        
        # Score calculation
        if ratio < 2.0:
            score = 0.0
        elif ratio >= 3.0:
            score = 1.0
        else:
            # Linear interpolation between 2.0 and 3.0
            score = (ratio - 2.0) / 1.0
        
        return DetectorScore(
            score=min(1.0, max(0.0, score)),
            reason="volatility_ratio",
            warmup_progress=1.0
        )
```

**Performance**: O(n) where n=30 for short window, <0.5ms latency

### 3.4 Tier 3 Detectors

#### 3.4.1 CUSUMDetector (Cumulative Sum)

**Purpose**: Detect sustained drift across multiple signals (price, spread, volume).

**Algorithm**:

```python
class CUSUMDetector(AnomalyDetector):
    def __init__(self, threshold_sigma: float = 5.0, drift: float = 0.5):
        self._threshold = threshold_sigma
        self._drift = drift
        self._cusum_pos = 0.0
        self._cusum_neg = 0.0
        
        # Running statistics for each signal
        self._price_history: deque = deque(maxlen=1000)
        self._spread_history: deque = deque(maxlen=1000)
        self._volume_history: deque = deque(maxlen=1000)
        
        self._prev_price: Optional[float] = None
    
    def update(self, tick_data: dict) -> DetectorScore:
        price = tick_data['mid_price']
        spread = tick_data['spread']
        volume = tick_data['volume']
        
        # Compute price change
        if self._prev_price is not None:
            price_change_bps = (price - self._prev_price) / self._prev_price * 10000
            self._price_history.append(price_change_bps)
        self._prev_price = price
        
        # Store spread and volume
        spread_bps = spread / price * 10000
        self._spread_history.append(spread_bps)
        self._volume_history.append(volume)
        
        if len(self._price_history) < 30:
            progress = len(self._price_history) / 30
            return DetectorScore(score=0.0, reason="cusum", warmup_progress=progress)
        
        # Compute z-scores for each signal
        z_price = self._compute_zscore(price_change_bps, self._price_history)
        z_spread = self._compute_zscore(spread_bps, self._spread_history)
        z_volume = self._compute_zscore(volume, self._volume_history)
        
        # Composite signal: 0.5*z_price + 0.3*z_spread + 0.2*z_volume
        composite = 0.5 * z_price + 0.3 * z_spread + 0.2 * z_volume
        
        # Update CUSUM
        self._cusum_pos = max(0.0, self._cusum_pos + composite - self._drift)
        self._cusum_neg = max(0.0, self._cusum_neg - composite - self._drift)
        
        # Score based on threshold
        max_cusum = max(self._cusum_pos, self._cusum_neg)
        score = min(1.0, max_cusum / self._threshold)
        
        return DetectorScore(
            score=score,
            reason="cusum",
            warmup_progress=1.0
        )
    
    def _compute_zscore(self, value: float, history: deque) -> float:
        if len(history) < 2:
            return 0.0
        mean = statistics.mean(history)
        std = statistics.stdev(history)
        if std < 1e-9:
            return 0.0
        return (value - mean) / std
```

**Performance**: O(n) where n=1000 for statistics, <0.5ms latency

#### 3.4.2 EWMADetector (Exponentially Weighted Moving Average)

**Purpose**: Detect small sustained shifts in price or spread.

**Algorithm**:
```python
class EWMADetector(AnomalyDetector):
    def __init__(self, signal_name: str, lambda_: float = 0.2, L: float = 3.0):
        self._signal_name = signal_name  # "price" or "spread"
        self._lambda = lambda_
        self._L = L
        self._ewma = 0.0
        self._initialized = False
        
        self._history: deque = deque(maxlen=1000)
        self._prev_price: Optional[float] = None
    
    def update(self, tick_data: dict) -> DetectorScore:
        price = tick_data['mid_price']
        spread = tick_data['spread']
        
        # Extract signal value
        if self._signal_name == "price":
            if self._prev_price is not None:
                value = (price - self._prev_price) / self._prev_price * 10000
            else:
                self._prev_price = price
                return DetectorScore(score=0.0, reason=f"ewma_{self._signal_name}", warmup_progress=0.0)
            self._prev_price = price
        else:  # spread
            value = spread / price * 10000
        
        self._history.append(value)
        
        if len(self._history) < 30:
            progress = len(self._history) / 30
            return DetectorScore(score=0.0, reason=f"ewma_{self._signal_name}", warmup_progress=progress)
        
        # Compute z-score
        mean = statistics.mean(self._history)
        std = statistics.stdev(self._history)
        if std < 1e-9:
            std = 1e-9
        z = (value - mean) / std
        
        # Update EWMA
        if not self._initialized:
            self._ewma = z
            self._initialized = True
        else:
            self._ewma = self._lambda * z + (1 - self._lambda) * self._ewma
        
        # Compute control limits
        control_limit = self._L * math.sqrt(self._lambda / (2 - self._lambda))
        
        # Score calculation
        if abs(self._ewma) > control_limit:
            excess = abs(self._ewma) - control_limit
            score = min(1.0, excess / control_limit)
        else:
            score = abs(self._ewma) / control_limit
        
        return DetectorScore(
            score=score,
            reason=f"ewma_{self._signal_name}",
            warmup_progress=1.0
        )
```

**Performance**: O(n) where n=1000 for statistics, <0.5ms latency

### 3.5 HMM Regime Classifier

**Purpose**: Classify market regime (low/high volatility) to adjust detector thresholds.

**Design**:

```python
@dataclass
class RegimeClassification:
    regime: int  # 0=low volatility, 1=high volatility
    posterior: List[float]  # Posterior probabilities for each regime

class HMMRegimeClassifier:
    def __init__(self, model_path: str):
        import joblib
        self._model = joblib.load(model_path)
        self._rv_history: deque = deque(maxlen=30)  # 30-min window
        self._returns: deque = deque(maxlen=1800)  # 30 min at 1 tick/sec
        self._prev_price: Optional[float] = None
    
    def update(self, tick_data: dict) -> RegimeClassification:
        price = tick_data['mid_price']
        
        # Compute return
        if self._prev_price is not None:
            ret = math.log(price / self._prev_price)
            self._returns.append(ret)
        self._prev_price = price
        
        # Compute 30-min realized volatility
        if len(self._returns) >= 30:
            rv_30m = math.sqrt(sum(r**2 for r in self._returns))
            self._rv_history.append(rv_30m)
        
        if len(self._rv_history) < 30:
            # Default to high volatility (conservative) during warmup
            return RegimeClassification(regime=1, posterior=[0.0, 1.0])
        
        # Predict regime using HMM
        X = np.array(list(self._rv_history)).reshape(-1, 1)
        states = self._model.predict(X)
        posteriors = self._model.predict_proba(X)
        
        regime = int(states[-1])
        posterior = [float(p) for p in posteriors[-1]]
        
        return RegimeClassification(regime=regime, posterior=posterior)
```

**Performance**: O(n) where n=30 for HMM prediction, <1.0ms latency

**Regime Integration**: HMM output is passed to detectors that support regime-aware thresholds (MAD, Decision Gate).

### 3.6 Fusion Engine

**Purpose**: Combine detector scores using coincidence logic and weighted averaging.

**Algorithm**:

```python
@dataclass
class FusionResult:
    final_score: float
    reasons: List[str]
    coincidence_triggered: bool
    detector_scores: Dict[str, float]

class FusionEngine:
    def __init__(self):
        # Detector weights (must sum to 1.0)
        self._weights = {
            "absolute_threshold": 0.25,
            "trust_passthrough": 0.10,
            "mad": 0.30,
            "volatility_ratio": 0.15,
            "cusum": 0.10,
            "ewma_price": 0.05,
            "ewma_spread": 0.05,
        }
        
        # Coincidence thresholds
        self._extreme_threshold = 0.90
        self._coincidence_threshold = 0.60
    
    def fuse(self, detector_results: List[DetectorScore]) -> FusionResult:
        """Fuse detector scores using coincidence logic.
        
        Logic:
        1. If any detector > 0.90: use max score (extreme event)
        2. Elif 2+ detectors > 0.60: weighted avg (coincidence = confidence)
        3. Else: weighted avg (normal operation)
        """
        # Build score dict
        scores = {r.reason: r.score for r in detector_results}
        
        # Check for extreme events
        max_score = max(scores.values())
        if max_score > self._extreme_threshold:
            max_detector = max(scores.items(), key=lambda x: x[1])[0]
            return FusionResult(
                final_score=max_score,
                reasons=[max_detector],
                coincidence_triggered=False,
                detector_scores=scores
            )
        
        # Check for coincidence (2+ detectors > 0.60)
        high_detectors = [name for name, score in scores.items() 
                         if score > self._coincidence_threshold]
        
        if len(high_detectors) >= 2:
            # Coincidence detected - compute weighted average
            weighted_sum = sum(scores[name] * self._weights[name] 
                             for name in scores.keys())
            return FusionResult(
                final_score=weighted_sum,
                reasons=high_detectors,
                coincidence_triggered=True,
                detector_scores=scores
            )
        
        # Normal operation - weighted average
        weighted_sum = sum(scores[name] * self._weights[name] 
                         for name in scores.keys())
        top_detector = max(scores.items(), key=lambda x: x[1])[0]
        
        return FusionResult(
            final_score=weighted_sum,
            reasons=[top_detector],
            coincidence_triggered=False,
            detector_scores=scores
        )
```

**Performance**: O(n) where n=7 detectors, <0.5ms latency

**Key Innovation**: Coincidence check reduces false positives by requiring multiple detectors to agree.

### 3.7 Decision Gate State Machine

**Purpose**: Manage system state with hysteresis to prevent oscillation.

**State Diagram**:
```
                    ┌─────────┐
                    │ NORMAL  │
                    └────┬────┘
                         │
         trust<0.60 OR   │   trust≥0.60 AND
         anomaly>0.55+δ  │   anomaly≤0.55+δ
                         │   (10 consecutive ticks)
                    ┌────▼────────┐
                    │CONSERVATIVE │
                    └────┬────────┘
                         │
         trust<0.40 OR   │   trust≥0.40 AND
         anomaly>0.75+δ  │   anomaly≤0.75+δ
                         │   (10 consecutive ticks)
                    ┌────▼────────┐
                    │  DEGRADED   │
                    └────┬────────┘
                         │
         trust<0.20 OR   │   trust≥0.20 AND
         anomaly>0.90+δ  │   anomaly≤0.90+δ
                         │   (10 consecutive ticks)
                    ┌────▼────────┐
                    │    HALT     │
                    └─────────────┘

δ = regime_adjustment = -0.10 if regime==0 else 0.0
```

**Algorithm**:
```python
from enum import IntEnum

class SystemState(IntEnum):
    NORMAL = 0
    CONSERVATIVE = 1
    DEGRADED = 2
    HALT = 3

class DecisionGate:
    def __init__(self):
        self._state = SystemState.NORMAL
        self._upgrade_counter = 0
        self._upgrade_threshold = 10
    
    def update(self, anomaly_score: float, trust_score: float, regime: int) -> SystemState:
        """Update state machine with new scores.
        
        Args:
            anomaly_score: Fused anomaly score [0, 1]
            trust_score: Layer 1 trust score [0, 1]
            regime: HMM regime (0=low vol, 1=high vol)
        
        Returns:
            Current system state
        """
        # Regime adjustment: tighten thresholds in low volatility
        regime_adj = -0.10 if regime == 0 else 0.0
        
        # Check for immediate downgrade conditions
        if self._should_downgrade(anomaly_score, trust_score, regime_adj):
            self._state = self._compute_target_state(anomaly_score, trust_score, regime_adj)
            self._upgrade_counter = 0
            return self._state
        
        # Check for upgrade conditions (requires 10 consecutive good ticks)
        if self._should_upgrade(anomaly_score, trust_score, regime_adj):
            self._upgrade_counter += 1
            if self._upgrade_counter >= self._upgrade_threshold:
                self._state = SystemState(max(0, self._state - 1))
                self._upgrade_counter = 0
        else:
            self._upgrade_counter = 0
        
        return self._state
    
    def _should_downgrade(self, anomaly: float, trust: float, adj: float) -> bool:
        if trust < 0.20 or anomaly > (0.90 + adj):
            return self._state != SystemState.HALT
        if trust < 0.40 or anomaly > (0.75 + adj):
            return self._state < SystemState.DEGRADED
        if trust < 0.60 or anomaly > (0.55 + adj):
            return self._state < SystemState.CONSERVATIVE
        return False
    
    def _compute_target_state(self, anomaly: float, trust: float, adj: float) -> SystemState:
        if trust < 0.20 or anomaly > (0.90 + adj):
            return SystemState.HALT
        if trust < 0.40 or anomaly > (0.75 + adj):
            return SystemState.DEGRADED
        if trust < 0.60 or anomaly > (0.55 + adj):
            return SystemState.CONSERVATIVE
        return SystemState.NORMAL
    
    def _should_upgrade(self, anomaly: float, trust: float, adj: float) -> bool:
        if self._state == SystemState.HALT:
            return trust >= 0.20 and anomaly <= (0.90 + adj)
        if self._state == SystemState.DEGRADED:
            return trust >= 0.40 and anomaly <= (0.75 + adj)
        if self._state == SystemState.CONSERVATIVE:
            return trust >= 0.60 and anomaly <= (0.55 + adj)
        return False
```

**Performance**: O(1) per tick, <0.1ms latency

## 4. Data Flow

### 4.1 Per-Tick Processing Pipeline

```
1. Kafka Consumer receives ValidatedTick
   ↓
2. Parse message → extract fields
   ↓
3. HMM Classifier updates regime
   ↓
4. Update all detectors in parallel:
   - AbsoluteThreshold
   - TrustPassthrough
   - MAD (with regime)
   - VolatilityRatio
   - CUSUM
   - EWMA_Price
   - EWMA_Spread
   ↓
5. Fusion Engine combines scores
   - Check extreme events (>0.90)
   - Check coincidence (2+ >0.60)
   - Compute weighted average
   - Aggregate reasons
   ↓
6. Decision Gate updates state
   - Apply regime adjustment
   - Check downgrade conditions
   - Check upgrade conditions
   ↓
7. Build ScoredTick message
   - Copy all ValidatedTick fields
   - Add anomaly_score
   - Add anomaly_reasons
   - Add system_state
   - Add regime
   ↓
8. Publish to Kafka
   ↓
9. Update Prometheus metrics
```

**Total Latency Budget**: <5ms (p99)
- Kafka receive: <0.5ms
- HMM update: <1.0ms
- Detector updates: <3.0ms (7 detectors × ~0.4ms each)
- Fusion: <0.5ms
- Decision Gate: <0.1ms
- Kafka publish: <0.5ms
- Metrics: <0.5ms

### 4.2 Message Schemas

#### ValidatedTick (Input)
```json
{
  "symbol": "BTCUSDT",
  "timestamp_ms": 1716768000000,
  "mid_price": 95234.50,
  "spread": 0.50,
  "volume_24h": 1234567.89,
  "trust_score": 0.95,
  "exchange": "binance",
  "latency_ms": 12
}
```

#### ScoredTick (Output)
```json
{
  "symbol": "BTCUSDT",
  "timestamp_ms": 1716768000000,
  "mid_price": 95234.50,
  "spread": 0.50,
  "volume_24h": 1234567.89,
  "trust_score": 0.95,
  "exchange": "binance",
  "latency_ms": 12,
  "anomaly_score": 0.23,
  "anomaly_reasons": ["mad", "volatility_ratio"],
  "system_state": "NORMAL",
  "regime": 0
}
```

## 5. Observability Design

### 5.1 Prometheus Metrics

#### Detector Scores
```python
# Gauge: Individual detector scores
layer2_detector_score{symbol="BTCUSDT", detector="absolute_threshold"} 0.0
layer2_detector_score{symbol="BTCUSDT", detector="trust_passthrough"} 0.05
layer2_detector_score{symbol="BTCUSDT", detector="mad"} 0.23
layer2_detector_score{symbol="BTCUSDT", detector="volatility_ratio"} 0.15
layer2_detector_score{symbol="BTCUSDT", detector="cusum"} 0.10
layer2_detector_score{symbol="BTCUSDT", detector="ewma_price"} 0.08
layer2_detector_score{symbol="BTCUSDT", detector="ewma_spread"} 0.12

# Gauge: Final fused score
layer2_final_anomaly_score{symbol="BTCUSDT"} 0.23

# Counter: Coincidence events
layer2_coincidence_triggers_total{symbol="BTCUSDT"} 42

# Gauge: HMM regime
layer2_hmm_regime{symbol="BTCUSDT"} 0

# Gauge: System state (0=NORMAL, 1=CONSERVATIVE, 2=DEGRADED, 3=HALT)
layer2_system_state{symbol="BTCUSDT"} 0

# Histogram: Processing latency
layer2_processing_latency_ms{symbol="BTCUSDT"} 2.3

# Counter: Anomaly reasons
layer2_detector_reasons_total{symbol="BTCUSDT", reason="mad"} 156
layer2_detector_reasons_total{symbol="BTCUSDT", reason="volatility_ratio"} 89

# Gauge: Regime threshold adjustment
layer2_regime_threshold_adjustment{symbol="BTCUSDT"} -0.10

# Gauge: Detector warmup progress
layer2_detector_warmup_progress{symbol="BTCUSDT", detector="mad"} 1.0
layer2_detector_warmup_progress{symbol="BTCUSDT", detector="volatility_ratio"} 0.85

# Gauge: Detector thresholds (regime-aware)
layer2_detector_threshold{symbol="BTCUSDT", detector="mad", regime="0"} 4.0
layer2_detector_threshold{symbol="BTCUSDT", detector="mad", regime="1"} 8.0
```

### 5.2 Grafana Dashboard Layout

#### Panel 1: Detector Scores Time Series
- **Type**: Time series
- **Metrics**: All 7 detector scores + final score
- **Y-axis**: [0, 1]
- **Legend**: Show detector names
- **Purpose**: Visualize which detectors are firing

#### Panel 2: System State Timeline
- **Type**: State timeline
- **Metric**: layer2_system_state
- **Colors**: NORMAL=green, CONSERVATIVE=yellow, DEGRADED=orange, HALT=red
- **Purpose**: Track state transitions

#### Panel 3: Anomaly Reasons Bar Chart
- **Type**: Bar chart
- **Metric**: rate(layer2_detector_reasons_total[5m])
- **Purpose**: Show which detectors trigger most frequently

#### Panel 4: HMM Regime Time Series
- **Type**: Time series
- **Metric**: layer2_hmm_regime
- **Y-axis**: [0, 1]
- **Purpose**: Visualize regime changes

#### Panel 5: Coincidence Events
- **Type**: Stat
- **Metric**: rate(layer2_coincidence_triggers_total[5m])
- **Purpose**: Show coincidence event frequency

#### Panel 6: Processing Latency Histogram
- **Type**: Histogram
- **Metric**: layer2_processing_latency_ms
- **Buckets**: [0.5, 1, 2, 5, 10, 20]
- **Purpose**: Monitor performance

#### Panel 7: Warmup Progress
- **Type**: Gauge
- **Metrics**: layer2_detector_warmup_progress for all detectors
- **Purpose**: Show which detectors are ready

#### Panel 8: Regime Thresholds
- **Type**: Table
- **Metrics**: layer2_detector_threshold
- **Purpose**: Show current threshold values per regime

## 6. Infrastructure Design

### 6.1 Docker Configuration

#### Dockerfile Changes
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install only required dependencies (remove scikit-learn, river)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose Prometheus metrics port
EXPOSE 9103

CMD ["python", "service.py"]
```

#### requirements.txt
```
# Core dependencies
kafka-python==2.0.2
prometheus-client==0.19.0

# Numerical computing
numpy==1.26.3
scipy==1.11.4

# HMM model loading
scikit-learn==1.4.0  # Only for joblib.load() of pre-trained HMM
joblib==1.3.2

# Logging
structlog==24.1.0
```

**Size Reduction**: From ~800MB (with river) to ~400MB

### 6.2 Docker Compose Integration

```yaml
services:
  layer2-anomaly:
    build: ./services/layer2_anomaly
    container_name: layer2-anomaly
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=kafka:9092
      - KAFKA_INPUT_TOPIC=market.ticks.validated
      - KAFKA_OUTPUT_TOPIC=market.ticks.scored
      - KAFKA_CONSUMER_GROUP=layer2-anomaly
      - HMM_MODEL_PATH=/app/artifacts/hmm/model.pkl
      - PROMETHEUS_PORT=9103
      # Detector configuration
      - L2_MAD_MULTIPLIER_LOW_VOL=4.0
      - L2_MAD_MULTIPLIER_HIGH_VOL=8.0
      - L2_CUSUM_THRESHOLD=5.0
      - L2_EWMA_LAMBDA=0.2
      - L2_FUSION_WEIGHTS={"absolute_threshold":0.25,"trust_passthrough":0.10,"mad":0.30,"volatility_ratio":0.15,"cusum":0.10,"ewma_price":0.05,"ewma_spread":0.05}
    volumes:
      - ./artifacts/hmm:/app/artifacts/hmm:ro
    depends_on:
      - kafka
      - layer1-consensus
    networks:
      - trading-network
    restart: unless-stopped
```

### 6.3 Kafka Topic Configuration

```bash
# Input topic (from Layer 1)
kafka-topics.sh --create \
  --topic market.ticks.validated \
  --partitions 4 \
  --replication-factor 2 \
  --config retention.ms=3600000

# Output topic (to Layer 3)
kafka-topics.sh --create \
  --topic market.ticks.scored \
  --partitions 4 \
  --replication-factor 2 \
  --config retention.ms=3600000
```

## 7. Implementation Strategy

### 7.1 Phase 1: Foundation (Week 1)

**Goal**: Immediate flash crash detection with zero warmup

**Tasks**:
1. Implement `AnomalyDetector` base class
2. Implement `AbsoluteThresholdDetector`
3. Implement `TrustPassthroughDetector`
4. Implement basic `FusionEngine` (weighted average only)
5. Update Kafka consumer/publisher
6. Add Prometheus metrics for Phase 1 detectors
7. Create basic Grafana dashboard

**Success Criteria**:
- Flash crash detection on tick 1
- Latency <2ms per tick
- All metrics publishing correctly

### 7.2 Phase 2: Core Detection (Week 2)

**Goal**: Replace IF/HST with MAD detector and full fusion logic

**Tasks**:
1. Implement `MADDetector` with regime awareness
2. Implement full `FusionEngine` with coincidence logic
3. Update HMM classifier to pass regime to detectors
4. Add coincidence metrics
5. Update Grafana dashboard with coincidence panel

**Success Criteria**:
- MAD detector produces reliable scores after 50 ticks
- Coincidence logic reduces false positives
- Latency <3ms per tick

### 7.3 Phase 3: Advanced Detection (Week 3)

**Goal**: Add liquidity crisis detection

**Tasks**:
1. Implement `VolatilityRatioDetector`
2. Implement `CUSUMDetector` with composite signal
3. Add regime shift detection metrics
4. Update Grafana dashboard with new detectors

**Success Criteria**:
- Volatility ratio detects regime shifts
- CUSUM catches sustained drift
- Latency <4ms per tick

### 7.4 Phase 4: Production Hardening (Week 4)

**Goal**: Complete detector stack and production tuning

**Tasks**:
1. Implement `EWMADetector` for price and spread
2. Add warmup progress metrics
3. Add regime threshold adjustment metrics
4. Complete Grafana dashboard with all panels
5. Performance tuning and optimization
6. Load testing with historical data
7. Documentation

**Success Criteria**:
- All 7 detectors operational
- Latency <5ms per tick (p99)
- Complete observability
- Production-ready documentation

### 7.5 Migration Strategy

#### Parallel Deployment
```
┌─────────────────┐
│   Layer 1       │
└────────┬────────┘
         │
         ├──────────────┬──────────────┐
         │              │              │
    ┌────▼────┐    ┌────▼────┐   ┌────▼────┐
    │Layer 2  │    │Layer 2  │   │ Compare │
    │  OLD    │    │  NEW    │   │  Tool   │
    └────┬────┘    └────┬────┘   └────┬────┘
         │              │              │
         │              │              │
    ┌────▼────┐    ┌────▼────┐   ┌────▼────┐
    │Layer 3  │    │ Metrics │   │ Report  │
    │(current)│    │  Only   │   │         │
    └─────────┘    └─────────┘   └─────────┘
```

#### Comparison Metrics
```python
# Correlation between old and new scores
layer2_migration_score_correlation{symbol="BTCUSDT"} 0.87

# Latency comparison
layer2_migration_latency_old_ms{symbol="BTCUSDT"} 8234.5
layer2_migration_latency_new_ms{symbol="BTCUSDT"} 2.3

# False positive rate (manual labeling required)
layer2_migration_false_positive_rate_old 0.15
layer2_migration_false_positive_rate_new 0.04
```

#### Cutover Criteria
1. **Performance**: p99 latency <5ms for 7 consecutive days
2. **Accuracy**: False positive rate <5% on labeled test set
3. **Reliability**: No crashes or data loss for 7 consecutive days
4. **Flash Crash Detection**: 100% detection rate on historical flash crashes

#### Rollback Procedure
1. Stop new Layer 2 service
2. Update Layer 3 to consume from old Layer 2 topic
3. Restart old Layer 2 service
4. Verify data flow
5. Total time: <5 minutes

## 8. Testing Strategy

### 8.1 Unit Tests

#### Detector Tests
```python
def test_absolute_threshold_price_jump():
    detector = AbsoluteThresholdDetector()
    
    # Normal price movement
    result1 = detector.update({'mid_price': 100.0, 'spread': 0.1, 'volume': 1000})
    assert result1.score == 0.0
    
    # Flash crash: 2% price jump (200 bps)
    result2 = detector.update({'mid_price': 102.0, 'spread': 0.1, 'volume': 1000})
    assert result2.score == 1.0
    assert result2.reason == "absolute_threshold"

def test_mad_detector_regime_awareness():
    detector = MADDetector(window_size=50)
    
    # Fill window with normal prices
    for i in range(50):
        detector.update({'mid_price': 100.0 + random.gauss(0, 0.1)})
    
    # Test low volatility regime (k=4)
    detector.set_regime(0)
    result_low = detector.update({'mid_price': 105.0})  # 5% outlier
    
    # Test high volatility regime (k=8)
    detector.set_regime(1)
    result_high = detector.update({'mid_price': 105.0})  # Same outlier
    
    # Score should be higher in low volatility regime
    assert result_low.score > result_high.score

def test_fusion_coincidence_logic():
    fusion = FusionEngine()
    
    # Test extreme event (single detector >0.90)
    results = [
        DetectorScore(score=0.95, reason="absolute_threshold", warmup_progress=1.0),
        DetectorScore(score=0.10, reason="mad", warmup_progress=1.0),
        # ... other detectors
    ]
    fused = fusion.fuse(results)
    assert fused.final_score == 0.95
    assert fused.reasons == ["absolute_threshold"]
    
    # Test coincidence (2+ detectors >0.60)
    results = [
        DetectorScore(score=0.70, reason="mad", warmup_progress=1.0),
        DetectorScore(score=0.65, reason="volatility_ratio", warmup_progress=1.0),
        # ... other detectors
    ]
    fused = fusion.fuse(results)
    assert fused.coincidence_triggered == True
    assert "mad" in fused.reasons
    assert "volatility_ratio" in fused.reasons
```

### 8.2 Property-Based Tests

```python
from hypothesis import given, strategies as st

@given(st.floats(min_value=0.0, max_value=1.0))
def test_detector_score_range(trust_score):
    """All detectors must produce scores in [0, 1]."""
    detector = TrustPassthroughDetector()
    result = detector.update({'trust_score': trust_score})
    assert 0.0 <= result.score <= 1.0

@given(st.lists(st.floats(min_value=0.0, max_value=1.0), min_size=7, max_size=7))
def test_fusion_weighted_average_property(scores):
    """Fused score must be within range of input scores."""
    fusion = FusionEngine()
    results = [
        DetectorScore(score=s, reason=f"detector_{i}", warmup_progress=1.0)
        for i, s in enumerate(scores)
    ]
    fused = fusion.fuse(results)
    assert min(scores) <= fused.final_score <= max(scores)
```

### 8.3 Integration Tests

```python
def test_end_to_end_flash_crash():
    """Test complete pipeline with flash crash scenario."""
    engine = Layer2ScoringEngine(symbol="BTCUSDT", hmm_model_path="artifacts/hmm/model.pkl")
    
    # Normal ticks
    for i in range(100):
        result = engine.score_tick(
            symbol="BTCUSDT",
            ts_ms=1000 * i,
            mid_price=100.0 + random.gauss(0, 0.1),
            trust_score=0.95,
            volume_24h=1000000,
            spread=0.05
        )
        assert result.system_state == SystemState.NORMAL
    
    # Flash crash: 5% price drop
    result = engine.score_tick(
        symbol="BTCUSDT",
        ts_ms=100000,
        mid_price=95.0,  # 5% drop
        trust_score=0.95,
        volume_24h=1000000,
        spread=0.05
    )
    
    # Should detect immediately
    assert result.anomaly_score > 0.90
    assert "absolute_threshold" in result.anomaly_reasons
    assert result.system_state == SystemState.HALT

def test_historical_data_replay():
    """Test with real historical data."""
    engine = Layer2ScoringEngine(symbol="BTCUSDT", hmm_model_path="artifacts/hmm/model.pkl")
    
    # Load historical data
    data = load_historical_ticks("data/binance_vision/BTCUSDT-1m-2026-03-01.zip")
    
    latencies = []
    for tick in data:
        start = time.perf_counter()
        result = engine.score_tick(**tick)
        latency_ms = (time.perf_counter() - start) * 1000
        latencies.append(latency_ms)
    
    # Verify performance
    p99_latency = np.percentile(latencies, 99)
    assert p99_latency < 5.0, f"p99 latency {p99_latency:.2f}ms exceeds 5ms target"
```

### 8.4 Performance Tests

```python
def test_latency_under_load():
    """Test latency with 100 ticks/second."""
    engine = Layer2ScoringEngine(symbol="BTCUSDT", hmm_model_path="artifacts/hmm/model.pkl")
    
    latencies = []
    for i in range(10000):  # 100 seconds at 100 ticks/sec
        tick = generate_random_tick()
        start = time.perf_counter()
        result = engine.score_tick(**tick)
        latency_ms = (time.perf_counter() - start) * 1000
        latencies.append(latency_ms)
    
    p50 = np.percentile(latencies, 50)
    p99 = np.percentile(latencies, 99)
    
    assert p50 < 2.0, f"p50 latency {p50:.2f}ms exceeds 2ms target"
    assert p99 < 5.0, f"p99 latency {p99:.2f}ms exceeds 5ms target"

def test_memory_usage():
    """Test memory usage per symbol."""
    import tracemalloc
    
    tracemalloc.start()
    engine = Layer2ScoringEngine(symbol="BTCUSDT", hmm_model_path="artifacts/hmm/model.pkl")
    
    # Process 10000 ticks
    for i in range(10000):
        tick = generate_random_tick()
        engine.score_tick(**tick)
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    peak_mb = peak / 1024 / 1024
    assert peak_mb < 10.0, f"Peak memory {peak_mb:.2f}MB exceeds 10MB target"
```

## 9. Configuration Management

### 9.1 Environment Variables

```bash
# Kafka configuration
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
KAFKA_INPUT_TOPIC=market.ticks.validated
KAFKA_OUTPUT_TOPIC=market.ticks.scored
KAFKA_CONSUMER_GROUP=layer2-anomaly

# HMM configuration
HMM_MODEL_PATH=/app/artifacts/hmm/model.pkl

# Prometheus configuration
PROMETHEUS_PORT=9103

# Detector thresholds
L2_MAD_MULTIPLIER_LOW_VOL=4.0
L2_MAD_MULTIPLIER_HIGH_VOL=8.0
L2_MAD_WINDOW_SIZE=50

L2_VOLATILITY_RATIO_SHORT_WINDOW=30
L2_VOLATILITY_RATIO_LONG_WINDOW=300
L2_VOLATILITY_RATIO_THRESHOLD_LOW=2.0
L2_VOLATILITY_RATIO_THRESHOLD_HIGH=3.0

L2_CUSUM_THRESHOLD=5.0
L2_CUSUM_DRIFT=0.5
L2_CUSUM_PRICE_WEIGHT=0.5
L2_CUSUM_SPREAD_WEIGHT=0.3
L2_CUSUM_VOLUME_WEIGHT=0.2

L2_EWMA_LAMBDA=0.2
L2_EWMA_L=3.0

L2_ABSOLUTE_THRESHOLD_PRICE_BPS=100
L2_ABSOLUTE_THRESHOLD_SPREAD_BPS=50
L2_ABSOLUTE_THRESHOLD_VOLUME_MULTIPLIER=10

# Fusion weights (JSON string)
L2_FUSION_WEIGHTS={"absolute_threshold":0.25,"trust_passthrough":0.10,"mad":0.30,"volatility_ratio":0.15,"cusum":0.10,"ewma_price":0.05,"ewma_spread":0.05}

# Fusion thresholds
L2_FUSION_EXTREME_THRESHOLD=0.90
L2_FUSION_COINCIDENCE_THRESHOLD=0.60

# Decision Gate thresholds
L2_GATE_NORMAL_TO_CONSERVATIVE_TRUST=0.60
L2_GATE_NORMAL_TO_CONSERVATIVE_ANOMALY=0.55
L2_GATE_CONSERVATIVE_TO_DEGRADED_TRUST=0.40
L2_GATE_CONSERVATIVE_TO_DEGRADED_ANOMALY=0.75
L2_GATE_DEGRADED_TO_HALT_TRUST=0.20
L2_GATE_DEGRADED_TO_HALT_ANOMALY=0.90
L2_GATE_UPGRADE_THRESHOLD=10
L2_GATE_REGIME_ADJUSTMENT_LOW_VOL=-0.10
```

### 9.2 Configuration Validation

```python
class Config:
    """Configuration with validation."""
    
    def __init__(self):
        self.kafka_bootstrap_servers = self._get_env("KAFKA_BOOTSTRAP_SERVERS")
        self.kafka_input_topic = self._get_env("KAFKA_INPUT_TOPIC")
        self.kafka_output_topic = self._get_env("KAFKA_OUTPUT_TOPIC")
        
        self.mad_multiplier_low_vol = self._get_float("L2_MAD_MULTIPLIER_LOW_VOL", 4.0)
        self.mad_multiplier_high_vol = self._get_float("L2_MAD_MULTIPLIER_HIGH_VOL", 8.0)
        
        self.fusion_weights = self._get_json("L2_FUSION_WEIGHTS")
        self._validate_fusion_weights()
    
    def _get_env(self, key: str) -> str:
        value = os.getenv(key)
        if value is None:
            raise ValueError(f"Required environment variable {key} not set")
        return value
    
    def _get_float(self, key: str, default: float) -> float:
        value = os.getenv(key)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError:
            raise ValueError(f"Environment variable {key}={value} is not a valid float")
    
    def _get_json(self, key: str) -> dict:
        value = os.getenv(key)
        if value is None:
            raise ValueError(f"Required environment variable {key} not set")
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            raise ValueError(f"Environment variable {key} is not valid JSON: {e}")
    
    def _validate_fusion_weights(self):
        """Validate fusion weights sum to 1.0."""
        total = sum(self.fusion_weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Fusion weights sum to {total}, expected 1.0")
        
        required_detectors = [
            "absolute_threshold", "trust_passthrough", "mad",
            "volatility_ratio", "cusum", "ewma_price", "ewma_spread"
        ]
        for detector in required_detectors:
            if detector not in self.fusion_weights:
                raise ValueError(f"Missing fusion weight for detector: {detector}")
```

## 10. Error Handling and Reliability

### 10.1 Graceful Degradation

```python
class Layer2ScoringEngine:
    def score_tick(self, **tick_data) -> Layer2Scores:
        """Score tick with graceful degradation."""
        try:
            # Update HMM regime
            try:
                regime = self._hmm.update(tick_data)
            except Exception as e:
                logger.error(f"HMM update failed: {e}", exc_info=True)
                regime = RegimeClassification(regime=1, posterior=[0.0, 1.0])  # Default to high vol
            
            # Update all detectors
            detector_results = []
            for detector in self._detectors:
                try:
                    result = detector.update(tick_data)
                    detector_results.append(result)
                except Exception as e:
                    logger.error(f"Detector {detector.get_name()} failed: {e}", exc_info=True)
                    # Skip failed detector (don't add to results)
            
            # Check if we have any valid detector results
            if not detector_results:
                logger.error("All detectors failed, returning neutral score")
                return Layer2Scores(
                    anomaly_score=0.5,
                    anomaly_reasons=["all_detectors_failed"],
                    system_state=SystemState.DEGRADED,
                    regime=regime.regime
                )
            
            # Fuse scores
            try:
                fusion_result = self._fusion.fuse(detector_results)
            except Exception as e:
                logger.error(f"Fusion failed: {e}", exc_info=True)
                # Fallback: use max detector score
                max_result = max(detector_results, key=lambda r: r.score)
                fusion_result = FusionResult(
                    final_score=max_result.score,
                    reasons=[max_result.reason],
                    coincidence_triggered=False,
                    detector_scores={r.reason: r.score for r in detector_results}
                )
            
            # Update decision gate
            try:
                state = self._decision_gate.update(
                    fusion_result.final_score,
                    tick_data['trust_score'],
                    regime.regime
                )
            except Exception as e:
                logger.error(f"Decision gate failed: {e}", exc_info=True)
                state = SystemState.DEGRADED
            
            return Layer2Scores(
                anomaly_score=fusion_result.final_score,
                anomaly_reasons=fusion_result.reasons,
                system_state=state,
                regime=regime.regime,
                detector_scores=fusion_result.detector_scores
            )
            
        except Exception as e:
            logger.error(f"Catastrophic failure in score_tick: {e}", exc_info=True)
            # Last resort: return neutral score
            return Layer2Scores(
                anomaly_score=0.5,
                anomaly_reasons=["catastrophic_failure"],
                system_state=SystemState.DEGRADED,
                regime=1
            )
```

### 10.2 Kafka Error Handling

```python
class Layer2Service:
    def __init__(self, config: Config):
        self._config = config
        self._consumer = None
        self._producer = None
        self._reconnect_backoff = ExponentialBackoff(initial=1.0, max=60.0)
        self._message_buffer = deque(maxlen=1000)
    
    def run(self):
        """Main service loop with reconnection logic."""
        while True:
            try:
                self._ensure_connected()
                self._process_messages()
            except KafkaException as e:
                logger.error(f"Kafka error: {e}", exc_info=True)
                self._reconnect()
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                time.sleep(5)
    
    def _ensure_connected(self):
        """Ensure Kafka consumer and producer are connected."""
        if self._consumer is None:
            self._consumer = KafkaConsumer(
                self._config.kafka_input_topic,
                bootstrap_servers=self._config.kafka_bootstrap_servers,
                group_id=self._config.kafka_consumer_group,
                auto_offset_reset='latest',
                enable_auto_commit=True
            )
            logger.info("Kafka consumer connected")
        
        if self._producer is None:
            self._producer = KafkaProducer(
                bootstrap_servers=self._config.kafka_bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode('utf-8')
            )
            logger.info("Kafka producer connected")
    
    def _reconnect(self):
        """Reconnect to Kafka with exponential backoff."""
        backoff_time = self._reconnect_backoff.next()
        logger.info(f"Reconnecting in {backoff_time:.1f} seconds...")
        time.sleep(backoff_time)
        
        # Close existing connections
        if self._consumer:
            self._consumer.close()
            self._consumer = None
        if self._producer:
            self._producer.close()
            self._producer = None
    
    def _process_messages(self):
        """Process messages with buffering for producer failures."""
        for message in self._consumer:
            try:
                # Parse and score tick
                tick = json.loads(message.value)
                scored_tick = self._engine.score_tick(**tick)
                
                # Try to publish
                self._publish_with_retry(scored_tick)
                
            except Exception as e:
                logger.error(f"Failed to process message: {e}", exc_info=True)
    
    def _publish_with_retry(self, scored_tick: dict):
        """Publish with buffering and retry."""
        try:
            self._producer.send(self._config.kafka_output_topic, value=scored_tick)
            self._reconnect_backoff.reset()  # Reset backoff on success
        except Exception as e:
            logger.error(f"Failed to publish message: {e}", exc_info=True)
            # Buffer message for retry
            self._message_buffer.append(scored_tick)
            if len(self._message_buffer) >= 1000:
                logger.error("Message buffer full, dropping oldest message")
```

### 10.3 Health Check Endpoint

```python
from http.server import HTTPServer, BaseHTTPRequestHandler

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            # Check if service is operational
            if self.server.service.is_healthy():
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': 'healthy',
                    'detectors_ready': self.server.service.get_detectors_ready(),
                    'kafka_connected': self.server.service.is_kafka_connected()
                }).encode())
            else:
                self.send_response(503)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'status': 'unhealthy',
                    'reason': self.server.service.get_health_reason()
                }).encode())

def start_health_check_server(service: Layer2Service, port: int = 8080):
    """Start health check HTTP server."""
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.service = service
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info(f"Health check server started on port {port}")
```

## 11. Audit Trail

### 11.1 Audit Event Schema

```python
@dataclass
class AuditEvent:
    event_type: str
    timestamp_ms: int
    symbol: str
    old_value: Any
    new_value: Any
    reason: str
    metadata: Dict[str, Any]

class AuditLogger:
    def __init__(self, kafka_producer: KafkaProducer, topic: str = "system.audit"):
        self._producer = kafka_producer
        self._topic = topic
    
    def log_state_transition(self, symbol: str, old_state: SystemState, new_state: SystemState, reason: str):
        """Log Decision Gate state transition."""
        event = AuditEvent(
            event_type="layer2.state_transition",
            timestamp_ms=int(time.time() * 1000),
            symbol=symbol,
            old_value=old_state.name,
            new_value=new_state.name,
            reason=reason,
            metadata={}
        )
        self._publish(event)
    
    def log_coincidence_trigger(self, symbol: str, detectors: List[str], scores: Dict[str, float]):
        """Log coincidence event."""
        event = AuditEvent(
            event_type="layer2.coincidence_trigger",
            timestamp_ms=int(time.time() * 1000),
            symbol=symbol,
            old_value=None,
            new_value=detectors,
            reason=f"{len(detectors)} detectors exceeded threshold",
            metadata={"scores": scores}
        )
        self._publish(event)
    
    def log_flash_event(self, symbol: str, detector: str, score: float, tick_data: dict):
        """Log flash event."""
        event = AuditEvent(
            event_type="layer2.flash_event",
            timestamp_ms=int(time.time() * 1000),
            symbol=symbol,
            old_value=None,
            new_value=score,
            reason=f"{detector} detected flash event",
            metadata={"tick_data": tick_data}
        )
        self._publish(event)
    
    def log_regime_change(self, symbol: str, old_regime: int, new_regime: int, posterior: List[float]):
        """Log HMM regime change."""
        event = AuditEvent(
            event_type="layer2.regime_change",
            timestamp_ms=int(time.time() * 1000),
            symbol=symbol,
            old_value=old_regime,
            new_value=new_regime,
            reason="HMM regime classification changed",
            metadata={"posterior": posterior}
        )
        self._publish(event)
    
    def _publish(self, event: AuditEvent):
        """Publish audit event to Kafka."""
        try:
            self._producer.send(
                self._topic,
                value=asdict(event)
            )
        except Exception as e:
            logger.error(f"Failed to publish audit event: {e}", exc_info=True)
```

### 11.2 Audit Event Examples

```json
{
  "event_type": "layer2.state_transition",
  "timestamp_ms": 1716768000000,
  "symbol": "BTCUSDT",
  "old_value": "NORMAL",
  "new_value": "CONSERVATIVE",
  "reason": "anomaly_score exceeded threshold",
  "metadata": {}
}

{
  "event_type": "layer2.coincidence_trigger",
  "timestamp_ms": 1716768001000,
  "symbol": "BTCUSDT",
  "old_value": null,
  "new_value": ["mad", "volatility_ratio"],
  "reason": "2 detectors exceeded threshold",
  "metadata": {
    "scores": {
      "mad": 0.72,
      "volatility_ratio": 0.68
    }
  }
}

{
  "event_type": "layer2.flash_event",
  "timestamp_ms": 1716768002000,
  "symbol": "BTCUSDT",
  "old_value": null,
  "new_value": 1.0,
  "reason": "absolute_threshold detected flash event",
  "metadata": {
    "tick_data": {
      "mid_price": 95234.50,
      "spread": 0.50,
      "volume_24h": 1234567.89
    }
  }
}

{
  "event_type": "layer2.regime_change",
  "timestamp_ms": 1716768003000,
  "symbol": "BTCUSDT",
  "old_value": 0,
  "new_value": 1,
  "reason": "HMM regime classification changed",
  "metadata": {
    "posterior": [0.15, 0.85]
  }
}
```

## 12. Performance Optimization

### 12.1 Algorithmic Optimizations

#### Rolling Statistics with O(1) Updates
```python
class RollingStatistics:
    """Efficient rolling mean and variance with O(1) updates."""
    
    def __init__(self, window_size: int):
        self._window_size = window_size
        self._values: deque = deque(maxlen=window_size)
        self._sum = 0.0
        self._sum_sq = 0.0
    
    def add(self, value: float):
        """Add value with O(1) complexity."""
        # Remove old value from sums if at capacity
        if len(self._values) == self._window_size:
            old_value = self._values[0]
            self._sum -= old_value
            self._sum_sq -= old_value * old_value
        
        # Add new value
        self._values.append(value)
        self._sum += value
        self._sum_sq += value * value
    
    def mean(self) -> float:
        """Get mean with O(1) complexity."""
        if not self._values:
            return 0.0
        return self._sum / len(self._values)
    
    def variance(self) -> float:
        """Get variance with O(1) complexity."""
        if len(self._values) < 2:
            return 0.0
        n = len(self._values)
        mean = self._sum / n
        return (self._sum_sq / n) - (mean * mean)
    
    def std(self) -> float:
        """Get standard deviation with O(1) complexity."""
        return math.sqrt(max(0.0, self.variance()))
```

#### Median Approximation for MAD
For very large windows, exact median calculation (O(n log n)) can be replaced with approximate median using P² algorithm (O(1)):

```python
class ApproximateMedian:
    """P² algorithm for approximate median with O(1) updates."""
    
    def __init__(self):
        self._markers = [0.0] * 5  # 5 markers for min, p25, p50, p75, max
        self._positions = [1, 2, 3, 4, 5]
        self._desired_positions = [1, 1.5, 2, 2.5, 3]
        self._count = 0
    
    def add(self, value: float):
        """Add value and update median estimate."""
        # Implementation of P² algorithm
        # See: Jain & Chlamtac (1985)
        pass
    
    def median(self) -> float:
        """Get approximate median."""
        return self._markers[2]  # Middle marker
```

### 12.2 Memory Optimizations

#### Fixed-Size Buffers
All detectors use `deque(maxlen=N)` to prevent unbounded memory growth:
- MAD: 50 values
- VolatilityRatio: 300 values
- CUSUM: 1000 values
- EWMA: 1000 values

**Total memory per symbol**: ~50KB

#### Numpy Array Reuse
```python
class Layer2ScoringEngine:
    def __init__(self):
        # Pre-allocate arrays to avoid repeated allocation
        self._feature_buffer = np.zeros(8, dtype=np.float32)
    
    def _build_features(self, tick_data: dict) -> np.ndarray:
        """Build feature vector by reusing pre-allocated buffer."""
        self._feature_buffer[0] = tick_data['price_jump_bps']
        self._feature_buffer[1] = tick_data['volume_ratio']
        # ... fill remaining features
        return self._feature_buffer
```

### 12.3 Profiling Results

#### Baseline Performance (Current System)
```
Component                  Latency (ms)    % of Total
─────────────────────────────────────────────────────
Isolation Forest           256.3           3.1%
Half-Space Trees (3x)      8234.5          99.8%
CUSUM                      0.2             0.0%
EWMA                       0.2             0.0%
HMM                        1.5             0.0%
Decision Gate              0.1             0.0%
─────────────────────────────────────────────────────
TOTAL                      8492.8          100%
```

#### Target Performance (New System)
```
Component                  Latency (ms)    % of Total
─────────────────────────────────────────────────────
AbsoluteThreshold          0.3             6.0%
TrustPassthrough           0.05            1.0%
MAD                        0.8             16.0%
VolatilityRatio            0.4             8.0%
CUSUM                      0.4             8.0%
EWMA_Price                 0.4             8.0%
EWMA_Spread                0.4             8.0%
HMM                        1.0             20.0%
Fusion                     0.3             6.0%
Decision Gate              0.05            1.0%
Kafka/Metrics              1.0             20.0%
─────────────────────────────────────────────────────
TOTAL                      5.0             100%
```

**Speedup**: 1698x faster (8492.8ms → 5.0ms)

## 13. Comparison with Current System

### 13.1 Architecture Comparison

| Aspect | Current System | New System |
|--------|---------------|------------|
| **Primary Detectors** | Isolation Forest, Half-Space Trees | 7 specialized detectors (tiered) |
| **Warmup Time** | 256 ticks (IF), 250-3000 ticks (HST) | 0 ticks (Tier 1), 50 ticks (Tier 2) |
| **Latency (p99)** | 8492ms | <5ms |
| **Flash Crash Detection** | After 256 ticks | Tick 1 (immediate) |
| **Explainability** | None (black box) | Full (anomaly_reasons list) |
| **Coincidence Check** | No | Yes (2+ detectors) |
| **Regime Adaptation** | Used as feature | Adjusts thresholds |
| **Dependencies** | scikit-learn, river | numpy, scipy only |
| **Docker Image Size** | ~800MB | ~400MB |
| **Memory per Symbol** | ~50MB | ~10MB |

### 13.2 Detection Capability Comparison

| Anomaly Type | Current System | New System |
|--------------|---------------|------------|
| **Flash Crash** | ❌ Missed (warmup gap) | ✅ Detected on tick 1 |
| **Gradual Drift** | ⚠️ Slow (IF batch) | ✅ CUSUM + EWMA |
| **Regime Shift** | ❌ Not detected | ✅ VolatilityRatio |
| **Spread Widening** | ⚠️ Indirect (IF feature) | ✅ EWMA_Spread |
| **Volume Spike** | ⚠️ Indirect (IF feature) | ✅ AbsoluteThreshold |
| **Trust Degradation** | ❌ Not used | ✅ TrustPassthrough |
| **Liquidity Crisis** | ❌ Not detected | ✅ Composite CUSUM |

### 13.3 False Positive Comparison

**Current System**:
- IF: ~10% false positive rate (too sensitive with contamination=0.05)
- HST: ~20% false positive rate (hypersensitive, scores 0.7-1.0)
- No coincidence check → single detector misfires trigger alerts

**New System**:
- Individual detectors: ~5-10% false positive rate
- Coincidence check: Requires 2+ detectors → ~2% false positive rate
- Explainability allows manual filtering of known false positives

**Expected Improvement**: 5-10x reduction in false positives

### 13.4 Migration Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **New system misses anomalies** | Medium | High | Parallel deployment with comparison tool |
| **Performance regression** | Low | High | Load testing with historical data |
| **Configuration errors** | Medium | Medium | Validation at startup, fail-fast |
| **Kafka compatibility issues** | Low | High | Schema backward compatibility |
| **Detector bugs** | Medium | Medium | Comprehensive unit tests, property tests |
| **HMM model incompatibility** | Low | Medium | Model validation at startup |

**Overall Risk**: Medium (acceptable with parallel deployment)

## 14. Future Enhancements

### 14.1 Adaptive Thresholds

**Current**: Fixed thresholds per regime (k=4 for regime 0, k=8 for regime 1)

**Enhancement**: Online learning of optimal thresholds based on false positive/negative rates

```python
class AdaptiveThresholdMAD(MADDetector):
    def __init__(self):
        super().__init__()
        self._false_positives = deque(maxlen=1000)
        self._false_negatives = deque(maxlen=1000)
    
    def update_with_feedback(self, tick_data: dict, is_anomaly: bool):
        """Update detector with ground truth feedback."""
        result = self.update(tick_data)
        
        # Track false positives/negatives
        if result.score > 0.6 and not is_anomaly:
            self._false_positives.append(1)
        elif result.score < 0.4 and is_anomaly:
            self._false_negatives.append(1)
        
        # Adjust threshold to minimize total error
        if len(self._false_positives) > 100:
            fp_rate = sum(self._false_positives) / len(self._false_positives)
            fn_rate = sum(self._false_negatives) / len(self._false_negatives)
            
            if fp_rate > 0.05:  # Too many false positives
                self._k_multiplier *= 1.1  # Increase threshold
            elif fn_rate > 0.05:  # Too many false negatives
                self._k_multiplier *= 0.9  # Decrease threshold
```

### 14.2 Multi-Symbol Correlation

**Current**: Each symbol processed independently

**Enhancement**: Detect market-wide anomalies by correlating signals across symbols

```python
class CrossSymbolDetector:
    def __init__(self, symbols: List[str]):
        self._symbols = symbols
        self._scores: Dict[str, deque] = {s: deque(maxlen=10) for s in symbols}
    
    def update(self, symbol: str, anomaly_score: float) -> float:
        """Detect market-wide anomalies."""
        self._scores[symbol].append(anomaly_score)
        
        # Check if multiple symbols have high scores simultaneously
        recent_scores = [list(scores)[-1] for scores in self._scores.values() if len(scores) > 0]
        
        if len(recent_scores) >= 3:
            high_score_count = sum(1 for s in recent_scores if s > 0.6)
            if high_score_count >= 3:
                # Market-wide event detected
                return 1.0
        
        return 0.0
```

### 14.3 Anomaly Clustering

**Current**: Each tick scored independently

**Enhancement**: Cluster anomalies to identify event types (flash crash, liquidity crisis, etc.)

```python
class AnomalyClusterer:
    def __init__(self):
        self._recent_anomalies: deque = deque(maxlen=100)
    
    def add_anomaly(self, tick_data: dict, detector_scores: Dict[str, float]):
        """Add anomaly to clustering."""
        self._recent_anomalies.append({
            'timestamp': tick_data['timestamp_ms'],
            'scores': detector_scores
        })
    
    def classify_event_type(self) -> str:
        """Classify recent anomalies into event types."""
        if not self._recent_anomalies:
            return "none"
        
        # Flash crash: AbsoluteThreshold + MAD high
        if self._pattern_match(['absolute_threshold', 'mad'], threshold=0.8):
            return "flash_crash"
        
        # Liquidity crisis: CUSUM + EWMA_Spread high
        if self._pattern_match(['cusum', 'ewma_spread'], threshold=0.7):
            return "liquidity_crisis"
        
        # Regime shift: VolatilityRatio high
        if self._pattern_match(['volatility_ratio'], threshold=0.8):
            return "regime_shift"
        
        return "unknown"
```

### 14.4 Detector Ensemble Optimization

**Current**: Fixed detector weights

**Enhancement**: Learn optimal weights using historical data and gradient descent

```python
class LearnedFusionEngine(FusionEngine):
    def __init__(self):
        super().__init__()
        self._weight_history: deque = deque(maxlen=10000)
    
    def optimize_weights(self, labeled_data: List[Tuple[Dict[str, float], bool]]):
        """Optimize fusion weights using labeled data."""
        # labeled_data: [(detector_scores, is_anomaly), ...]
        
        # Define loss function (binary cross-entropy)
        def loss(weights: np.ndarray) -> float:
            total_loss = 0.0
            for scores, is_anomaly in labeled_data:
                fused_score = sum(scores[d] * w for d, w in zip(scores.keys(), weights))
                target = 1.0 if is_anomaly else 0.0
                total_loss += (fused_score - target) ** 2
            return total_loss / len(labeled_data)
        
        # Optimize using scipy
        from scipy.optimize import minimize
        initial_weights = np.array(list(self._weights.values()))
        result = minimize(
            loss,
            initial_weights,
            method='L-BFGS-B',
            bounds=[(0.0, 1.0)] * len(initial_weights),
            constraints={'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}
        )
        
        # Update weights
        optimized_weights = result.x
        for i, detector in enumerate(self._weights.keys()):
            self._weights[detector] = optimized_weights[i]
```

### 14.5 Real-Time Model Retraining

**Current**: HMM model pre-trained offline, loaded at startup

**Enhancement**: Continuously retrain HMM on recent data to adapt to market evolution

```python
class OnlineHMMClassifier(HMMRegimeClassifier):
    def __init__(self, model_path: str):
        super().__init__(model_path=model_path)
        self._retrain_interval_s = 3600  # Retrain every hour
        self._last_retrain_s = time.time()
    
    def maybe_retrain(self):
        """Retrain HMM if enough time has passed."""
        now = time.time()
        if (now - self._last_retrain_s) < self._retrain_interval_s:
            return
        
        if len(self._history) < 1000:
            return
        
        # Retrain on recent data
        X = np.array(list(self._history)).reshape(-1, 1)
        self._model.fit(X)
        self._last_retrain_s = now
        
        logger.info(f"HMM retrained on {len(X)} samples")
```

## 15. Appendix

### 15.1 Mathematical Formulas

#### MAD (Median Absolute Deviation)
```
MAD = median(|x_i - median(x)|)

Anomaly Score:
  if |x - median| < k * MAD:
    score = 0.0
  elif |x - median| >= 2 * k * MAD:
    score = 1.0
  else:
    score = (|x - median| - k * MAD) / (k * MAD)

where k = 4 (regime 0) or k = 8 (regime 1)
```

#### CUSUM (Cumulative Sum)
```
S_pos(t) = max(0, S_pos(t-1) + z(t) - drift)
S_neg(t) = max(0, S_neg(t-1) - z(t) - drift)

Anomaly Score = min(1.0, max(S_pos, S_neg) / threshold)

where:
  z(t) = (x(t) - μ) / σ
  drift = 0.5
  threshold = 5.0
```

#### EWMA (Exponentially Weighted Moving Average)
```
EWMA(t) = λ * z(t) + (1 - λ) * EWMA(t-1)

Control Limit = L * sqrt(λ / (2 - λ))

Anomaly Score:
  if |EWMA| > Control Limit:
    score = min(1.0, (|EWMA| - Control Limit) / Control Limit)
  else:
    score = |EWMA| / Control Limit

where:
  λ = 0.2 (smoothing parameter)
  L = 3.0 (control limit multiplier)
```

#### Realized Volatility
```
RV_30m = sqrt(Σ r_i^2)

where r_i are log returns over 30-minute window
```

#### Volatility Ratio
```
Ratio = RV_30tick / RV_300tick

Anomaly Score:
  if Ratio < 2.0:
    score = 0.0
  elif Ratio >= 3.0:
    score = 1.0
  else:
    score = (Ratio - 2.0) / 1.0
```

### 15.2 Detector Decision Trees

#### AbsoluteThreshold Decision Tree
```
if price_jump_bps > 100:
  return 1.0
elif spread_bps > 50:
  return 0.9
elif volume > 10 * avg_volume:
  return 0.8
else:
  return 0.0
```

#### Fusion Engine Decision Tree
```
if any(detector_score > 0.90):
  return max(detector_scores)
elif count(detector_score > 0.60) >= 2:
  return weighted_average(detector_scores)
  # Coincidence triggered
else:
  return weighted_average(detector_scores)
  # Normal operation
```

#### Decision Gate State Transitions
```
Current State: NORMAL
  if trust < 0.60 OR anomaly > (0.55 + regime_adj):
    → CONSERVATIVE (immediate)
  
Current State: CONSERVATIVE
  if trust < 0.40 OR anomaly > (0.75 + regime_adj):
    → DEGRADED (immediate)
  elif trust >= 0.60 AND anomaly <= (0.55 + regime_adj) for 10 ticks:
    → NORMAL (delayed)

Current State: DEGRADED
  if trust < 0.20 OR anomaly > (0.90 + regime_adj):
    → HALT (immediate)
  elif trust >= 0.40 AND anomaly <= (0.75 + regime_adj) for 10 ticks:
    → CONSERVATIVE (delayed)

Current State: HALT
  if trust >= 0.20 AND anomaly <= (0.90 + regime_adj) for 10 ticks:
    → DEGRADED (delayed)

where regime_adj = -0.10 if regime == 0 else 0.0
```

### 15.3 Glossary of Terms

- **Anomaly**: Unusual market behavior that deviates from normal patterns
- **Basis Point (bps)**: 1/100th of 1% (0.01%)
- **Coincidence Check**: Logic requiring multiple detectors to agree before triggering alert
- **Contamination**: Expected proportion of anomalies in training data (IF parameter)
- **CUSUM**: Cumulative Sum control chart for detecting sustained drift
- **Decision Gate**: State machine managing system operational state
- **Drift**: Allowable deviation before CUSUM triggers (typically 0.5σ)
- **EWMA**: Exponentially Weighted Moving Average control chart
- **Flash Crash**: Sudden extreme price movement (>100bps)
- **Fusion**: Combining multiple detector scores into single score
- **HMM**: Hidden Markov Model for regime classification
- **Hysteresis**: Delayed state transitions to prevent oscillation
- **Isolation Forest**: Batch anomaly detection algorithm (being removed)
- **Latency**: Time from input to output (target: <5ms)
- **MAD**: Median Absolute Deviation, robust outlier detection
- **Regime**: Market volatility state (0=low, 1=high)
- **Realized Volatility**: Square root of sum of squared returns
- **Spread**: Difference between bid and ask prices
- **Tier**: Detector grouping by warmup requirements
- **Trust Score**: Layer 1 data quality score [0, 1]
- **Warmup**: Initial period before detector produces reliable scores
- **Z-score**: Standardized score (value - mean) / std

### 15.4 References

1. **MAD**: Leys et al. (2013). "Detecting outliers: Do not use standard deviation around the mean, use absolute deviation around the median"
2. **CUSUM**: Page, E.S. (1954). "Continuous Inspection Schemes"
3. **EWMA**: Roberts, S.W. (1959). "Control Chart Tests Based on Geometric Moving Averages"
4. **HMM**: Rabiner, L.R. (1989). "A Tutorial on Hidden Markov Models"
5. **Isolation Forest**: Liu et al. (2008). "Isolation Forest"
6. **Half-Space Trees**: Tan et al. (2011). "Fast Anomaly Detection for Streaming Data"

---

**Document Version**: 1.0  
**Last Updated**: 2026-05-26  
**Authors**: System Architecture Team  
**Status**: Ready for Implementation

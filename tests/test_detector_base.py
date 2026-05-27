"""Tests for the AnomalyDetector base class and DetectorScore dataclass.

Verifies the abstract interface and basic functionality of the detector base class.
"""

from __future__ import annotations

import pytest

from services.layer2_anomaly.detectors.base import AnomalyDetector, DetectorScore


class TestDetectorScore:
    """Test DetectorScore dataclass."""

    def test_detector_score_creation(self) -> None:
        """Verify DetectorScore can be created with valid fields."""
        score = DetectorScore(score=0.85, reason="test_detector", warmup_progress=1.0)
        
        assert score.score == 0.85
        assert score.reason == "test_detector"
        assert score.warmup_progress == 1.0

    def test_detector_score_fields_are_typed(self) -> None:
        """Verify DetectorScore fields have correct types."""
        score = DetectorScore(score=0.5, reason="mad", warmup_progress=0.75)
        
        assert isinstance(score.score, float)
        assert isinstance(score.reason, str)
        assert isinstance(score.warmup_progress, float)

    def test_detector_score_boundary_values(self) -> None:
        """Verify DetectorScore accepts boundary values."""
        # Minimum values
        score_min = DetectorScore(score=0.0, reason="", warmup_progress=0.0)
        assert score_min.score == 0.0
        assert score_min.warmup_progress == 0.0
        
        # Maximum values
        score_max = DetectorScore(score=1.0, reason="detector", warmup_progress=1.0)
        assert score_max.score == 1.0
        assert score_max.warmup_progress == 1.0


class TestAnomalyDetectorInterface:
    """Test AnomalyDetector abstract base class."""

    def test_cannot_instantiate_abstract_class(self) -> None:
        """Verify AnomalyDetector cannot be instantiated directly."""
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            AnomalyDetector()  # type: ignore[abstract]

    def test_concrete_detector_must_implement_all_methods(self) -> None:
        """Verify concrete detector must implement all abstract methods."""
        
        # Missing update() method
        class IncompleteDetector1(AnomalyDetector):
            def get_warmup_ticks_required(self) -> int:
                return 0
            
            def get_name(self) -> str:
                return "incomplete1"
        
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteDetector1()  # type: ignore[abstract]
        
        # Missing get_warmup_ticks_required() method
        class IncompleteDetector2(AnomalyDetector):
            def update(self, tick_data: dict) -> DetectorScore:
                return DetectorScore(score=0.0, reason="incomplete2", warmup_progress=1.0)
            
            def get_name(self) -> str:
                return "incomplete2"
        
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteDetector2()  # type: ignore[abstract]
        
        # Missing get_name() method
        class IncompleteDetector3(AnomalyDetector):
            def update(self, tick_data: dict) -> DetectorScore:
                return DetectorScore(score=0.0, reason="incomplete3", warmup_progress=1.0)
            
            def get_warmup_ticks_required(self) -> int:
                return 0
        
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteDetector3()  # type: ignore[abstract]

    def test_complete_detector_can_be_instantiated(self) -> None:
        """Verify complete detector implementation can be instantiated."""
        
        class CompleteDetector(AnomalyDetector):
            def update(self, tick_data: dict) -> DetectorScore:
                return DetectorScore(
                    score=0.0,
                    reason="complete_detector",
                    warmup_progress=1.0
                )
            
            def get_warmup_ticks_required(self) -> int:
                return 0
            
            def get_name(self) -> str:
                return "complete_detector"
        
        detector = CompleteDetector()
        assert isinstance(detector, AnomalyDetector)

    def test_detector_update_method_signature(self) -> None:
        """Verify update() method accepts correct tick_data format."""
        
        class TestDetector(AnomalyDetector):
            def update(self, tick_data: dict) -> DetectorScore:
                # Verify expected fields are present
                assert "mid_price" in tick_data
                assert "spread" in tick_data
                assert "volume" in tick_data
                assert "trust_score" in tick_data
                assert "timestamp_ms" in tick_data
                
                return DetectorScore(
                    score=0.5,
                    reason="test_detector",
                    warmup_progress=1.0
                )
            
            def get_warmup_ticks_required(self) -> int:
                return 0
            
            def get_name(self) -> str:
                return "test_detector"
        
        detector = TestDetector()
        tick_data = {
            "mid_price": 50000.0,
            "spread": 1.0,
            "volume": 1000000.0,
            "trust_score": 0.85,
            "timestamp_ms": 1716768000000,
        }
        
        result = detector.update(tick_data)
        assert isinstance(result, DetectorScore)
        assert result.score == 0.5
        assert result.reason == "test_detector"
        assert result.warmup_progress == 1.0

    def test_detector_warmup_ticks_required(self) -> None:
        """Verify get_warmup_ticks_required() returns correct values for different tiers."""
        
        # Tier 1: Zero warmup
        class Tier1Detector(AnomalyDetector):
            def update(self, tick_data: dict) -> DetectorScore:
                return DetectorScore(score=0.0, reason="tier1", warmup_progress=1.0)
            
            def get_warmup_ticks_required(self) -> int:
                return 0
            
            def get_name(self) -> str:
                return "tier1"
        
        tier1 = Tier1Detector()
        assert tier1.get_warmup_ticks_required() == 0
        
        # Tier 2: Short warmup
        class Tier2Detector(AnomalyDetector):
            def update(self, tick_data: dict) -> DetectorScore:
                return DetectorScore(score=0.0, reason="tier2", warmup_progress=0.5)
            
            def get_warmup_ticks_required(self) -> int:
                return 50
            
            def get_name(self) -> str:
                return "tier2"
        
        tier2 = Tier2Detector()
        assert tier2.get_warmup_ticks_required() == 50
        
        # Tier 3: Cumulative
        class Tier3Detector(AnomalyDetector):
            def update(self, tick_data: dict) -> DetectorScore:
                return DetectorScore(score=0.0, reason="tier3", warmup_progress=0.3)
            
            def get_warmup_ticks_required(self) -> int:
                return 300
            
            def get_name(self) -> str:
                return "tier3"
        
        tier3 = Tier3Detector()
        assert tier3.get_warmup_ticks_required() == 300

    def test_detector_name_consistency(self) -> None:
        """Verify get_name() returns consistent detector name."""
        
        class NamedDetector(AnomalyDetector):
            def update(self, tick_data: dict) -> DetectorScore:
                return DetectorScore(
                    score=0.0,
                    reason=self.get_name(),
                    warmup_progress=1.0
                )
            
            def get_warmup_ticks_required(self) -> int:
                return 0
            
            def get_name(self) -> str:
                return "named_detector"
        
        detector = NamedDetector()
        assert detector.get_name() == "named_detector"
        
        # Verify name is used in DetectorScore
        result = detector.update({
            "mid_price": 50000.0,
            "spread": 1.0,
            "volume": 1000000.0,
            "trust_score": 0.85,
            "timestamp_ms": 1716768000000,
        })
        assert result.reason == "named_detector"


class TestDetectorWarmupProgress:
    """Test warmup progress tracking."""

    def test_warmup_progress_increases_with_ticks(self) -> None:
        """Verify warmup_progress increases as detector processes ticks."""
        
        class WarmupDetector(AnomalyDetector):
            def __init__(self) -> None:
                self._tick_count = 0
                self._warmup_required = 10
            
            def update(self, tick_data: dict) -> DetectorScore:
                self._tick_count += 1
                progress = min(1.0, self._tick_count / self._warmup_required)
                
                return DetectorScore(
                    score=0.0,
                    reason="warmup_detector",
                    warmup_progress=progress
                )
            
            def get_warmup_ticks_required(self) -> int:
                return self._warmup_required
            
            def get_name(self) -> str:
                return "warmup_detector"
        
        detector = WarmupDetector()
        tick_data = {
            "mid_price": 50000.0,
            "spread": 1.0,
            "volume": 1000000.0,
            "trust_score": 0.85,
            "timestamp_ms": 1716768000000,
        }
        
        # Process ticks and verify progress
        for i in range(1, 11):
            result = detector.update(tick_data)
            expected_progress = i / 10.0
            assert abs(result.warmup_progress - expected_progress) < 1e-6
        
        # After warmup, progress should stay at 1.0
        result = detector.update(tick_data)
        assert result.warmup_progress == 1.0

    def test_zero_warmup_detector_always_ready(self) -> None:
        """Verify Tier 1 detectors report warmup_progress=1.0 immediately."""
        
        class InstantDetector(AnomalyDetector):
            def update(self, tick_data: dict) -> DetectorScore:
                return DetectorScore(
                    score=0.0,
                    reason="instant_detector",
                    warmup_progress=1.0
                )
            
            def get_warmup_ticks_required(self) -> int:
                return 0
            
            def get_name(self) -> str:
                return "instant_detector"
        
        detector = InstantDetector()
        tick_data = {
            "mid_price": 50000.0,
            "spread": 1.0,
            "volume": 1000000.0,
            "trust_score": 0.85,
            "timestamp_ms": 1716768000000,
        }
        
        # First tick should already be fully warmed up
        result = detector.update(tick_data)
        assert result.warmup_progress == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

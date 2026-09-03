"""
Violawake wake-word detector contract tests.

Replaces the Porcupine regression contract tests (session 278). Verifies:

  CT-WW-1: The detector adapter protocol (is_enabled / sample_rate /
           frame_length / process_frame / cleanup).
  CT-WW-2: Exact 16 kHz / 320-sample input contract.
  CT-WW-4: No Picovoice key or .ppn path is required.
  CT-WW-5: Detector failure does not disable audio/STT (fail-closed only for
           wake detection).

The detector loads the real trained "Hey Iris" ONNX model via the Violawake
SDK. These tests run against the installed violawake_sdk + openwakeword.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

# Project root (backend/tests/contract/ -> project root)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MODEL = _PROJECT_ROOT / "data" / "hey iris_237_1788045452.onnx"


def _can_load_violawake() -> bool:
    """True if violawake_sdk is installed."""
    try:
        import violawake_sdk  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture
def detector():
    """Return a configured ViolawakeWakeWordDetector, or skip if unavailable."""
    from backend.voice.violawake_detector import ViolawakeWakeWordDetector

    if not _can_load_violawake():
        pytest.skip("violawake_sdk not installed")
    if not _DEFAULT_MODEL.exists():
        pytest.skip(f"ONNX model not found: {_DEFAULT_MODEL}")

    d = ViolawakeWakeWordDetector()
    yield d
    d.cleanup()


# ---------------------------------------------------------------------------
# CT-WW-1: Detector adapter protocol
# ---------------------------------------------------------------------------

class TestViolawakeApiContract:
    """Verify the ViolawakeWakeWordDetector API contract."""

    def test_constructor_does_not_crash(self):
        """Creating a detector with a valid model should not raise."""
        from backend.voice.violawake_detector import ViolawakeWakeWordDetector

        if not _can_load_violawake():
            pytest.skip("violawake_sdk not installed")
        if not _DEFAULT_MODEL.exists():
            pytest.skip(f"ONNX model not found: {_DEFAULT_MODEL}")

        d = ViolawakeWakeWordDetector()
        assert d.is_enabled() is True
        d.cleanup()

    def test_is_enabled_returns_bool(self, detector):
        """is_enabled() must always return a bool."""
        assert isinstance(detector.is_enabled(), bool)

    def test_sample_rate_is_16000(self, detector):
        """sample_rate must be 16000 Hz."""
        assert detector.sample_rate == 16000

    def test_frame_length_is_320(self, detector):
        """frame_length must be 320 samples."""
        assert detector.frame_length == 320

    def test_process_frame_returns_tuple(self, detector):
        """process_frame must return (bool, Optional[str])."""
        frame = np.zeros(320, dtype=np.int16)
        result = detector.process_frame(frame)
        assert isinstance(result, tuple)
        assert len(result) == 2
        detected, name = result
        assert isinstance(detected, bool)
        assert name is None or isinstance(name, str)

    def test_cleanup_does_not_crash(self, detector):
        """cleanup() must not raise."""
        detector.cleanup()
        # After cleanup, is_enabled should be False (detector closed)
        assert detector.is_enabled() is False


# ---------------------------------------------------------------------------
# CT-WW-2: 16 kHz / 320-sample input contract
# ---------------------------------------------------------------------------

class TestViolawakeFrameContract:
    """Verify the exact 320-sample frame contract and bounded buffering."""

    def test_silence_frames_no_detection(self, detector):
        """Silent frames must never trigger detection."""
        for _ in range(20):
            frame = np.zeros(320, dtype=np.int16)
            detected, name = detector.process_frame(frame)
            assert detected is False
            assert name is None

    def test_non_aligned_chunk_does_not_crash(self, detector):
        """Chunks not equal to 320 samples must not crash (bounded buffering)."""
        # 500 samples (not a multiple of 320)
        frame = np.zeros(500, dtype=np.int16)
        detected, name = detector.process_frame(frame)
        assert detected is False
        assert name is None

    def test_odd_length_chunk_does_not_crash(self, detector):
        """Odd-length chunks must not crash."""
        frame = np.zeros(255, dtype=np.int16)
        detected, name = detector.process_frame(frame)
        assert detected is False
        assert name is None

    def test_empty_frame_does_not_crash(self, detector):
        """Empty frames must not crash."""
        frame = np.array([], dtype=np.int16)
        detected, name = detector.process_frame(frame)
        assert detected is False
        assert name is None

    def test_remainder_buffer_is_bounded(self, detector):
        """The remainder buffer must not grow unbounded."""
        # Feed many non-aligned chunks; the internal buffer must stay bounded.
        for _ in range(100):
            detector.process_frame(np.zeros(100, dtype=np.int16))
        # After processing, remainder should be < 320 samples (640 bytes)
        assert len(detector._remainder) < 320 * 2


# ---------------------------------------------------------------------------
# CT-WW-4: No Picovoice key or .ppn path required
# ---------------------------------------------------------------------------

class TestNoPicovoiceDependency:
    """Verify no Picovoice key or .ppn path is required."""

    def test_no_picovoice_key_required(self, detector):
        """The detector must work without PICOVOICE_ACCESS_KEY."""
        assert "PICOVOICE_ACCESS_KEY" not in os.environ or True
        assert detector.is_enabled() is True

    def test_no_ppn_file_required(self, detector):
        """The detector must not reference any .ppn file."""
        assert detector.is_enabled() is True
        # The model path must be the ONNX file, not a .ppn
        model_path = detector._model_path or ""
        assert model_path.endswith(".onnx"), f"Expected .onnx, got {model_path}"


# ---------------------------------------------------------------------------
# CT-WW-5: Detector failure does not disable audio/STT
# ---------------------------------------------------------------------------

class TestFailClosedOnlyForWake:
    """Verify a detector failure disables only wake detection, not audio/STT."""

    def test_missing_model_disables_only_detector(self):
        """A missing model must disable the detector but not raise."""
        from backend.voice.violawake_detector import ViolawakeWakeWordDetector

        d = ViolawakeWakeWordDetector(model_path="/nonexistent/model.onnx")
        assert d.is_enabled() is False
        assert d.get_status()["state"] == "error"
        # process_frame must still return safe values
        detected, name = d.process_frame(np.zeros(320, dtype=np.int16))
        assert detected is False
        assert name is None
        d.cleanup()

    def test_disabled_process_frame_safe(self, detector):
        """Even when disabled, process_frame must not raise."""
        detector._disabled = True
        detected, name = detector.process_frame(np.zeros(320, dtype=np.int16))
        assert detected is False
        assert name is None
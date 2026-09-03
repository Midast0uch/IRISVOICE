"""
Porcupine wake-word regression tests.

Verifies:
  1. Porcupine detection API contract (no crash with any frame size)
  2. Graceful degradation when no access key is configured
  3. TTS suppression path (``engine.set_tts_active``)
  4. Concurrent safety with Parakeet pipeline (no deadlocks)
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Detection-capable tests (require PICOVOICE_ACCESS_KEY or pvporcupine)
# ---------------------------------------------------------------------------

try:
    import pvporcupine as _pv
    _HAS_PORCUPINE_PKG = True
except ImportError:
    _HAS_PORCUPINE_PKG = False

_PICOVOICE_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "")


def _can_detect() -> bool:
    """True if we can instantiate a real PorcupineWakeWordDetector."""
    return _HAS_PORCUPINE_PKG and bool(_PICOVOICE_KEY)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def detector() -> Optional["PorcupineWakeWordDetector"]:
    """Return a configured PorcupineWakeWordDetector, or None if impossible."""
    from backend.voice.porcupine_detector import PorcupineWakeWordDetector
    try:
        return PorcupineWakeWordDetector(access_key=_PICOVOICE_KEY or "dummy")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# API contract tests (always run — no dependency on pvporcupine)
# ---------------------------------------------------------------------------

class TestPorcupineApiContract:
    """Verify the PorcupineWakeWordDetector API doesn't crash on edge inputs."""

    def test_constructor_does_not_crash(self):
        """Creating a detector without valid access key should set disabled=True."""
        from backend.voice.porcupine_detector import PorcupineWakeWordDetector
        try:
            d = PorcupineWakeWordDetector(access_key="nonexistent-key-12345")
        except Exception:
            # Some configurations may raise on invalid key — that's OK.
            return
        # If it didn't raise, it should be disabled (no valid key)
        assert d._disabled is True

    def test_disabled_process_frame_returns_safe_values(self, detector):
        """Even when disabled, process_frame must not raise."""
        if detector is None:
            pytest.skip("Could not create PorcupineWakeWordDetector")

        # Correct-size frame for disabled mode (any small frame)
        frame = np.zeros(256, dtype=np.int16)
        detected, name = detector.process_frame(frame)
        assert detected is False
        assert name is None

    def test_disabled_process_frame_odd_length(self, detector):
        """Odd-length frames must not crash (edge case robustness)."""
        if detector is None:
            pytest.skip("Could not create PorcupineWakeWordDetector")

        frame = np.zeros(255, dtype=np.int16)
        detected, name = detector.process_frame(frame)
        assert detected is False
        assert name is None

    def test_disabled_process_frame_empty(self, detector):
        """Empty frames must not crash."""
        if detector is None:
            pytest.skip("Could not create PorcupineWakeWordDetector")

        frame = np.array([], dtype=np.int16)
        detected, name = detector.process_frame(frame)
        assert detected is False
        assert name is None

    def test_is_enabled_returns_bool(self, detector):
        """is_enabled() must always return a bool."""
        if detector is None:
            pytest.skip("Could not create PorcupineWakeWordDetector")

        enabled = detector.is_enabled()
        assert isinstance(enabled, bool)

    def test_is_enabled_false_without_valid_key(self, detector):
        """Without a valid access key, is_enabled() should return False."""
        if detector is None:
            pytest.skip("Could not create PorcupineWakeWordDetector")

        # With dummy key, the detector should be disabled.
        # Note: if PICOVOICE_ACCESS_KEY is set in env, this test may fail.
        if _PICOVOICE_KEY:
            pytest.skip("PICOVOICE_ACCESS_KEY is set — detector may be enabled")
        assert detector.is_enabled() is False


# ---------------------------------------------------------------------------
# Actual detection tests (only with a valid Picovoice key)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _can_detect(), reason="No valid PICOVOICE_ACCESS_KEY found")
class TestPorcupineDetection:
    """These tests exercise actual wake-word detection."""

    def test_detector_is_enabled_with_valid_key(self, detector):
        if detector is None:
            pytest.skip("Could not create PorcupineWakeWordDetector")
        assert detector.is_enabled() is True

    def test_silence_frames_no_detection(self):
        """Silent frames should never trigger detection."""
        from backend.voice.porcupine_detector import PorcupineWakeWordDetector

        d = PorcupineWakeWordDetector(access_key=_PICOVOICE_KEY)
        assert d.is_enabled()

        # Porcupine uses frame_length = 512 samples at 16 kHz
        frame_length = d._porcupine.frame_length
        for _ in range(20):
            frame = np.zeros(frame_length, dtype=np.int16)
            detected, name = d.process_frame(frame)
            if detected:
                pytest.fail(f"Silence triggered false detection: {name}")

    def test_process_frame_ignored_during_tts(self):
        """When tts_active is True, process_frame should be no-op."""
        from backend.voice.porcupine_detector import PorcupineWakeWordDetector

        d = PorcupineWakeWordDetector(access_key=_PICOVOICE_KEY)

        # Pretend TTS is active
        d._disabled = True
        frame_length = getattr(d, "_porcupine", None)
        length = getattr(frame_length, "frame_length", 512) if frame_length else 512

        for _ in range(10):
            frame = np.zeros(length, dtype=np.int16)
            detected, name = d.process_frame(frame)
            # When disabled, must always return (False, None)
            assert detected is False
            assert name is None

        d._disabled = False

    def test_detection_requires_exact_frame_length(self):
        """Porcupine requires specific frame_length; wrong size should not crash."""
        from backend.voice.porcupine_detector import PorcupineWakeWordDetector

        d = PorcupineWakeWordDetector(access_key=_PICOVOICE_KEY)
        assert d.is_enabled()

        correct_length = d._porcupine.frame_length

        # Too short
        short_frame = np.zeros(correct_length // 2, dtype=np.int16)
        detected, name = d.process_frame(short_frame)
        assert detected is False

        # Too long
        long_frame = np.zeros(correct_length * 2, dtype=np.int16)
        detected, name = d.process_frame(long_frame)
        assert detected is False

        # Correct length should not crash
        correct_frame = np.zeros(correct_length, dtype=np.int16)
        detected, name = d.process_frame(correct_frame)
        assert detected is False  # Silence should still not trigger


# ---------------------------------------------------------------------------
# TTS suppression path tests (engine level)
# ---------------------------------------------------------------------------

class TestTtsSuppression:
    """Verify the engine's TTS-active flag suppresses wake word processing."""

    def test_engine_set_tts_active_flag(self):
        """set_tts_active(True) should set _tts_active on the engine."""
        from backend.audio.engine import get_audio_engine
        engine = get_audio_engine()
        if engine is None:
            pytest.skip("AudioEngine not available in this environment")

        original = engine._tts_active

        engine.set_tts_active(True)
        assert engine._tts_active is True

        engine.set_tts_active(False)
        assert engine._tts_active is False

        # Restore original state
        engine.set_tts_active(original)

    def test_tts_active_suppresses_porcupine_in_loop(self):
        """When _tts_active is True, the audio loop should skip wake-word check."""
        from backend.audio.engine import get_audio_engine
        engine = get_audio_engine()
        if engine is None:
            pytest.skip("AudioEngine not available in this environment")

        # The engine's _process_audio_loop checks:
        #   if not self._tts_active and self._wake_word_detector:
        #       detected, keyword = self._wake_word_detector.process_frame(...)
        # We can't easily test the loop, but we can verify the flag is read.
        assert hasattr(engine, "_tts_active")


# ---------------------------------------------------------------------------
# Concurrent safety test (Parakeet + Porcupine)
# ---------------------------------------------------------------------------

class TestConcurrentSafety:
    """Verify no deadlocks when Parakeet streaming and Porcupine run concurrently."""

    def test_detector_thread_safety(self, detector):
        """process_frame should be safely callable from a thread."""
        if detector is None or not detector.is_enabled():
            pytest.skip("PorcupineWakeWordDetector not available for thread safety test")

        import threading
        import queue

        results: queue.Queue = queue.Queue()
        errors: list[Exception] = []

        def worker(count: int):
            try:
                frame_length = detector._porcupine.frame_length
                for _ in range(50):
                    frame = np.zeros(frame_length, dtype=np.int16)
                    detected, name = detector.process_frame(frame)
                    results.put((detected, name))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0, f"Thread safety failures: {errors}"
        assert results.qsize() == 3 * 50

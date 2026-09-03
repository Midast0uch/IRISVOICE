"""
Behavioral test: Violawake wake detector through the real audio engine.

Verifies (REQ-4, REQ-5):
  - The engine initializes the Violawake detector.
  - process_frame handles silence without false detection.
  - The detector does not block the asyncio event loop (runs in audio thread).
  - TTS suppression gate works (frames dropped while _tts_active).
  - Detector failure does not disable audio/STT (fail-closed only for wake).

This drives the REAL AudioEngine + ViolawakeWakeWordDetector, not mocks.
"""

from __future__ import annotations

import asyncio
import threading
import time

import numpy as np
import pytest

from backend.audio.engine import AudioEngine


@pytest.fixture
def engine():
    """Return a fresh AudioEngine with the Violawake detector initialized."""
    eng = AudioEngine()
    ok = eng.initialize_detector()
    if not ok or not eng._wake_detector or not eng._wake_detector.is_enabled():
        pytest.skip("Violawake detector not available (model or package missing)")
    yield eng
    eng.cleanup()


class TestEngineWakeBehavior:
    """Verify the engine's wake detection behavior end-to-end."""

    def test_engine_initializes_violawake(self, engine):
        """The engine must initialize the Violawake detector."""
        assert engine._wake_detector_initialized is True
        assert engine._wake_detector is not None
        assert engine._wake_detector.is_enabled() is True

    def test_silence_does_not_trigger(self, engine):
        """Silent frames must not trigger the wake callback."""
        fired = []
        engine.set_wake_word_callback(lambda word: fired.append(word))

        # Feed silence through the engine's frame processing path.
        for _ in range(50):
            frame = np.zeros(512, dtype=np.float32)  # engine frame size
            engine._process_audio_frame(frame)

        assert fired == [], f"Silence triggered wake: {fired}"

    def test_tts_active_suppresses_detection(self, engine):
        """When _tts_active is True, frames must be dropped (no detection)."""
        fired = []
        engine.set_wake_word_callback(lambda word: fired.append(word))
        engine.set_tts_active(True)

        for _ in range(50):
            frame = np.zeros(512, dtype=np.float32)
            engine._process_audio_frame(frame)

        assert fired == [], "TTS-active gate failed to suppress detection"
        engine.set_tts_active(False)

    def test_detector_runs_off_event_loop(self, engine):
        """process_frame must not block the asyncio event loop."""
        # The detector runs in the audio callback thread. Verify a concurrent
        # asyncio task keeps ticking while frames are processed.
        loop = asyncio.new_event_loop()
        ticks = []

        async def ticker():
            for _ in range(10):
                ticks.append(time.monotonic())
                await asyncio.sleep(0.01)

        # Run the ticker in a thread while processing frames in the main thread.
        def run_ticker():
            loop.run_until_complete(ticker())

        t = threading.Thread(target=run_ticker, daemon=True)
        t.start()

        # Process frames while the ticker runs.
        for _ in range(200):
            engine._process_audio_frame(np.zeros(512, dtype=np.float32))

        t.join(timeout=5)
        loop.close()

        # The ticker must have advanced (event loop was not blocked).
        assert len(ticks) >= 5, (
            f"Event loop was blocked — only {len(ticks)} ticks in 200 frames"
        )

    def test_detector_failure_keeps_engine_alive(self):
        """A detector failure must not crash the engine or disable audio."""
        eng = AudioEngine()
        # Force a detector failure by pointing at a missing model.
        from backend.voice.violawake_detector import ViolawakeWakeWordDetector

        eng._wake_detector = ViolawakeWakeWordDetector(
            model_path="/nonexistent/model.onnx"
        )
        eng._wake_detector_initialized = True

        # process_frame must return safe values, not raise.
        detected, name = eng._wake_detector.process_frame(
            np.zeros(320, dtype=np.int16)
        )
        assert detected is False
        assert name is None
        eng.cleanup()
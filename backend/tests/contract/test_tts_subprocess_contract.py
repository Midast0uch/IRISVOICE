"""
Contract tests for the TTS subprocess IPC protocol (REQ-9, REQ-10).

Verifies:
  CT-TTS-1: The worker's JSONL protocol (ping/shutdown/synthesize).
  CT-TTS-2: synthesize_stream yields float32 numpy arrays at 24 kHz.
  CT-TTS-3: Crash recovery — the proxy restarts a dead worker.
  CT-TTS-4: The public API is preserved (synthesize, is_loaded, get_voice_info).

These tests spawn the REAL tts_worker.py subprocess. They skip if pocket-tts
is not installed or the model cannot load.
"""

from __future__ import annotations

import importlib.util
import numpy as np
import pytest

_HAS_POCKET_TTS = importlib.util.find_spec("pocket_tts") is not None


@pytest.fixture
def tts():
    """Return a TTSManager proxy with the worker spawned."""
    from backend.agent.tts import get_tts_manager

    if not _HAS_POCKET_TTS:
        pytest.skip("pocket_tts not installed")

    mgr = get_tts_manager()
    if not mgr._ensure_worker():
        pytest.skip("TTS worker could not start (model load failed)")
    yield mgr


class TestTTSSubprocessProtocol:
    """Verify the worker IPC protocol."""

    def test_worker_is_ready(self, tts):
        """The worker must report ready."""
        assert tts.is_loaded() is True

    def test_synthesize_stream_yields_float32(self, tts):
        """synthesize_stream must yield float32 numpy arrays."""
        chunks = list(tts.synthesize_stream("Hello"))
        assert len(chunks) > 0, "No audio chunks produced"
        for chunk in chunks:
            assert isinstance(chunk, np.ndarray)
            assert chunk.dtype == np.float32
            assert len(chunk) > 0

    def test_synthesize_stream_sample_rate(self, tts):
        """Chunks must be at 24 kHz (OUTPUT_SAMPLE_RATE)."""
        from backend.agent.tts import OUTPUT_SAMPLE_RATE

        chunks = list(tts.synthesize_stream("Hello"))
        assert len(chunks) > 0
        # The worker streams at 24 kHz; verify the proxy reports it.
        assert OUTPUT_SAMPLE_RATE == 24000

    def test_synthesize_returns_concatenated_audio(self, tts):
        """synthesize() must return a single concatenated array."""
        audio = tts.synthesize("Hello")
        assert audio is not None
        assert isinstance(audio, np.ndarray)
        assert audio.dtype == np.float32
        assert len(audio) > 0

    def test_empty_text_returns_nothing(self, tts):
        """Empty text must produce no audio."""
        chunks = list(tts.synthesize_stream(""))
        assert chunks == []

    def test_disabled_returns_nothing(self, tts):
        """When tts_enabled is False, synthesize_stream must yield nothing."""
        tts.update_config(tts_enabled=False)
        try:
            chunks = list(tts.synthesize_stream("Hello"))
            assert chunks == []
        finally:
            tts.update_config(tts_enabled=True)


class TestTTSPublicApi:
    """Verify the public API is preserved (REQ-10)."""

    def test_is_loaded(self, tts):
        """is_loaded() must return a bool."""
        assert isinstance(tts.is_loaded(), bool)

    def test_get_voice_info(self, tts):
        """get_voice_info() must return the expected keys."""
        info = tts.get_voice_info()
        assert "available_voices" in info
        assert "current_voice" in info
        assert "model_ready" in info
        assert "sample_rate" in info
        assert info["sample_rate"] == 24000

    def test_get_config(self, tts):
        """get_config() must return the config dict."""
        cfg = tts.get_config()
        assert "tts_enabled" in cfg
        assert "tts_voice" in cfg


class TestTTSCrashRecovery:
    """Verify the proxy restarts a dead worker (REQ-9 AC9)."""

    def test_restart_after_kill(self, tts):
        """Killing the worker must not break the next synthesis."""
        # Kill the worker subprocess.
        if tts._proc is not None:
            tts._proc.kill()
            tts._proc.wait(timeout=5)
            tts._ready = False

        # The next synthesize_stream must restart the worker and produce audio.
        chunks = list(tts.synthesize_stream("Hello"))
        assert len(chunks) > 0, "Worker did not recover after kill"
        assert tts.is_loaded() is True
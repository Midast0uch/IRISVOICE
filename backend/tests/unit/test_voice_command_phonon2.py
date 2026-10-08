"""Unit tests: Phonon-2 streaming STT seam (Wave 1, specs/phonon2-d1-model-swap).

Replaces test_voice_command_parakeet.py (both copies), which pinned the
retired ParakeetTranscriber seam. Same INTENT, new engine: timing fields,
fallback semantics, retirement guard, stream-client fail-soft behavior.

Run: python -m pytest backend/tests/unit/test_voice_command_phonon2.py -q
"""
from __future__ import annotations

import os
import wave
import io
import numpy as np
import pytest
from unittest.mock import MagicMock

from backend.audio.voice_command import VoiceCommandHandler, PARAKEET_RETIRED
from backend.audio import phonon2_stream


# ── Helpers ──────────────────────────────────────────────────────────────────
class _FakePhonon2:
    """Minimal Phonon2StreamClient double: finish() -> text or ''.

    Fidelity note: on the real client `active` and `last_error` are
    @property, `last_timing` and `finish` are methods — mirror that exactly
    or the code under test reads a bound method as truthy.
    """

    def __init__(self, text: str = "", error: str | None = None,
                 first_partial_s: float | None = 0.69):
        self._text = text
        self.last_error = error  # property on the real client
        self._timing = {"first_partial_s": first_partial_s, "final_s": 1.2}

    @property
    def active(self) -> bool:
        return True

    def last_timing(self):
        return self._timing

    def finish(self, timeout: float = 12.0) -> str:
        return self._text

    def feed_frame(self, audio_np) -> None:
        pass

    def abort(self) -> None:
        pass


def _make_handler() -> VoiceCommandHandler:
    handler = VoiceCommandHandler.__new__(VoiceCommandHandler)
    handler.sample_rate = 16000
    return handler


# ── _finalize_via_phonon2: timing + backend strings ─────────────────────────
class TestFinalizeViaPhonon2:

    def test_success_records_stt_timing(self):
        """A stream final populates _last_stt_timing with all fields (AC1.6)."""
        handler = _make_handler()
        handler._phonon2 = _FakePhonon2(text="hello world")

        audio = np.zeros(16000, dtype=np.float32)
        result = handler._finalize_via_phonon2(audio)

        assert result == "hello world"
        timing = handler._last_stt_timing
        assert timing["stt_backend"] == "phonon-2"
        assert "stt_latency_ms" in timing and timing["stt_latency_ms"] >= 0
        assert timing["stt_audio_seconds"] == pytest.approx(1.0, abs=0.01)
        # REQ-1 AC1.6: the streaming headline number is measurable.
        assert timing["stt_first_partial_s"] == 0.69

    def test_failure_records_failed_backend(self):
        """A dead stream records phonon-2_failed and returns '' (whisper next)."""
        handler = _make_handler()
        handler._phonon2 = _FakePhonon2(text="", error="stream closed: boom")

        result = handler._finalize_via_phonon2(np.zeros(16000, dtype=np.float32))
        assert result == ""
        assert handler._last_stt_timing["stt_backend"] == "phonon-2_failed"

    def test_empty_result_records_empty_backend(self):
        """A live stream that heard nothing records phonon-2_empty."""
        handler = _make_handler()
        handler._phonon2 = _FakePhonon2(text="", error=None)

        result = handler._finalize_via_phonon2(np.zeros(16000, dtype=np.float32))
        assert result == ""
        assert handler._last_stt_timing["stt_backend"] == "phonon-2_empty"

    def test_never_parakeet_backend_string(self):
        """Wave 1 live-gate precondition: the backend string is greppable
        evidence — it must never read 'parakeet*' (AC13.2)."""
        handler = _make_handler()
        handler._phonon2 = _FakePhonon2(text="x")
        handler._finalize_via_phonon2(np.zeros(16000, dtype=np.float32))
        assert not handler._last_stt_timing["stt_backend"].startswith("parakeet")


# ── Retirement guard (C1/AC2.3/AC11.3) ───────────────────────────────────────
class TestRetirementGuard:

    def test_parakeet_retired_flag_is_greppable(self):
        assert PARAKEET_RETIRED is True

    def test_stale_parakeet_env_fails_loudly(self, monkeypatch):
        """A boot that asks for the retired engine raises, naming the flag.

        Calls the guard DIRECTLY (no importlib.reload): a reload that raises
        mid-module leaves a half-initialized module in sys.modules and
        poisons every later import in the session (found via cross-file
        test pollution 2026-10-08)."""
        monkeypatch.setenv("IRIS_PARAKEET_PROVIDER", "cuda")
        from backend.audio.voice_command import _assert_single_stt_engine
        with pytest.raises(RuntimeError, match="PARAKEET_RETIRED"):
            _assert_single_stt_engine()

    def test_clean_env_boots(self, monkeypatch):
        monkeypatch.delenv("IRIS_PARAKEET_PROVIDER", raising=False)
        monkeypatch.delenv("IRIS_PARAKEET_SHERPA_DIR", raising=False)
        from backend.audio.voice_command import _assert_single_stt_engine
        _assert_single_stt_engine()  # must not raise


# ── Phonon2StreamClient fail-soft behavior ──────────────────────────────────
class TestStreamClientFailSoft:

    def test_begin_utterance_false_when_server_cold(self, monkeypatch):
        """No server on the port: begin returns False (never blocks, never
        raises); the utterance falls back to whisper (AC1.2/AC1.5)."""
        client = phonon2_stream.Phonon2StreamClient()
        mgr = MagicMock()
        mgr.server_ready.return_value = False
        monkeypatch.setattr(phonon2_stream, "get_server_manager", lambda: mgr)
        assert client.begin_utterance() is False
        # A background spawn was kicked, not a blocking one.
        mgr.spawn_in_background.assert_called_once()

    def test_feed_frame_never_raises_on_dead_stream(self):
        """feed_frame on a stream that never opened is a silent no-op."""
        client = phonon2_stream.Phonon2StreamClient()
        client.feed_frame(np.zeros(512, dtype=np.float32))  # must not raise
        assert client.active is False

    def test_finish_empty_when_never_begun(self):
        client = phonon2_stream.Phonon2StreamClient()
        assert client.finish() == ""


# ── media_tools WAV wrapper (REQ-3 AC3.2) ────────────────────────────────────
class TestMediaToolsRewire:

    def test_pcm_wrapped_as_valid_wav(self):
        """The fermion endpoint takes the Whisper API shape: chunks are
        headerless PCM and must ship inside a WAV container."""
        from backend.tools.media_tools import _wrap_pcm_as_wav

        pcm = (np.linspace(-1, 1, 1600) * 32767).astype("<i2").tobytes()
        wav_bytes = _wrap_pcm_as_wav(pcm)
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            assert wf.getframerate() == 16000
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.readframes(1600) == pcm

    def test_transcribe_url_is_phonon2(self):
        """The media consumer rides the Phonon-2 server, not the retired
        :8765 Parakeet service (V3 finding, REQ-3 AC3.2)."""
        from backend.tools import media_tools
        assert "8766" in media_tools.PHONON2_TRANSCRIBE_URL
        assert "8765" not in media_tools.PHONON2_TRANSCRIBE_URL

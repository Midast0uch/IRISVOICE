"""Behavioral test: whisper serves utterance 1, the Phonon-2 stream takes over.

Replaces test_voice_whisper_to_parakeet_flow.py (Wave 1,
specs/phonon2-d1-model-swap). Same INTENT on the new seam (REQ-1 AC1.2/AC1.5):

  1. Utterance 1 (server cold / stream never opened): ``_finalize_via_phonon2``
     returns "" so the ``_run_transcription`` fallback routes the utterance to
     faster-whisper — no hang, no VoiceState.ERROR.
  2. Once the stream is live, subsequent utterances finalize from the stream.
  3. A stream that dies mid-utterance stays on whisper (fail-soft, sticky).
"""

from __future__ import annotations

import numpy as np
from unittest.mock import MagicMock

from backend.audio.engine import AudioEngine
from backend.audio.voice_command import VoiceCommandHandler


class _FakePhonon2:
    """Minimal Phonon2StreamClient double: finish() -> text or ''.

    Fidelity: `active` and `last_error` are @property on the real client;
    `last_timing` and `finish` are methods.
    """

    def __init__(self, live: bool, text: str = "", error: str | None = None):
        self._live = live
        self._text = text
        self.last_error = error  # property on the real client

    @property
    def active(self) -> bool:
        return self._live

    def last_timing(self):
        return {"first_partial_s": 0.69 if self._live else None,
                "final_s": 1.2 if self._live else None}

    def finish(self, timeout: float = 12.0) -> str:
        return self._text if self._live else ""

    def feed_frame(self, audio_np) -> None:
        pass

    def abort(self) -> None:
        pass


class _FakeWhisper:
    """faster-whisper double returning a fixed transcript."""

    def __init__(self, text: str):
        self._text = text

    def transcribe(self, audio_np, language="en", beam_size=1, best_of=1,
                   condition_on_previous_text=False, vad_filter=False):
        class _Seg:
            def __init__(self, t):
                self.text = t

        return [_Seg(self._text)], None


def _make_handler() -> VoiceCommandHandler:
    handler = VoiceCommandHandler(MagicMock(spec=AudioEngine))
    handler.sample_rate = 16000
    return handler


def test_utterance1_whisper_then_phonon2_takes_over():
    handler = _make_handler()
    # Server cold: the stream never opened for this utterance.
    handler._phonon2 = _FakePhonon2(live=False, error="server cold (spawning)")
    handler._get_whisper = lambda: _FakeWhisper("what is the weather")

    audio = np.zeros(16000, dtype=np.float32)

    # ── Utterance 1: stream cold -> whisper serves it ────────────────────
    text1 = handler._finalize_via_phonon2(audio)
    assert text1 == "", "a cold stream must not produce a transcript"
    assert handler._last_stt_timing["stt_backend"] == "phonon-2_failed"

    # The _run_transcription fallback then uses faster-whisper (AC1.2).
    segments, _ = handler._get_whisper().transcribe(audio)
    assert " ".join(s.text for s in segments) == "what is the weather"

    # ── Utterance 2: stream live -> finalizes from the stream ────────────
    handler._phonon2 = _FakePhonon2(live=True, text="second question")
    text2 = handler._finalize_via_phonon2(audio)
    assert text2 == "second question"
    assert handler._last_stt_timing["stt_backend"] == "phonon-2"
    assert handler._last_stt_timing["stt_first_partial_s"] == 0.69


def test_stream_death_falls_back_to_whisper():
    """REQ-1 edge: a stream that died mid-utterance yields '' and the
    captured buffer goes to whisper (AC1.2: finals only)."""
    handler = _make_handler()
    handler._phonon2 = _FakePhonon2(live=False, error="feed failed: closed")
    handler._get_whisper = lambda: _FakeWhisper("fallback text")

    audio = np.zeros(16000, dtype=np.float32)
    text = handler._finalize_via_phonon2(audio)
    assert text == ""
    assert handler._last_stt_timing["stt_backend"] == "phonon-2_failed"
    # Whisper remains the live fallback.
    segments, _ = handler._get_whisper().transcribe(audio)
    assert " ".join(s.text for s in segments) == "fallback text"

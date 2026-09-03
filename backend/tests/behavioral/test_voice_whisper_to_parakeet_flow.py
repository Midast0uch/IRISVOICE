"""Behavioral test: whisper serves utterance 1, Parakeet takes over (REQ-2).

Drives the real routing decision in ``VoiceCommandHandler``:

  1. Utterance 1 (Parakeet not loaded): ``_transcribe_via_parakeet`` returns ""
     (the worker spawns in a background thread), so the ``_run_transcription``
     fallback routes the utterance to faster-whisper — no hang, no VoiceState.ERROR.
  2. Once Parakeet reports ready, subsequent utterances route to Parakeet GPU ASR.

This pins REQ-1 AC1.3/AC1.4 and REQ-2 AC2.5: the seamless whisper-to-Parakeet
bridge that eliminates the boot-time 4.2 GB Parakeet footprint.
"""

from __future__ import annotations

import numpy as np
from unittest.mock import MagicMock

from backend.audio.engine import AudioEngine
from backend.audio.voice_command import VoiceCommandHandler


class _FakeParakeet:
    """Minimal ParakeetTranscriber double: loaded -> returns text, else ''."""

    def __init__(self, loaded: bool, text: str = ""):
        self._loaded = loaded
        self._text = text
        self._loading = not loaded
        self._load_error = None

    def transcribe(self, audio_np, sample_rate):
        return self._text if self._loaded else ""


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


def test_utterance1_whisper_then_parakeet_takes_over():
    handler = _make_handler()
    # Parakeet NOT loaded yet: transcribe returns "" (worker spawns in bg).
    handler._parakeet = _FakeParakeet(loaded=False)
    handler._get_whisper = lambda: _FakeWhisper("what is the weather")

    audio = np.zeros(16000, dtype=np.float32)

    # ── Utterance 1: Parakeet not ready -> whisper serves it ──────────────
    text1 = handler._transcribe_via_parakeet(audio)
    assert text1 == "", "Parakeet must not transcribe before it is loaded"
    assert handler._last_stt_timing["stt_backend"] == "parakeet_loading"

    # The _run_transcription fallback then uses faster-whisper (REQ-2 AC2.5).
    segments, _ = handler._get_whisper().transcribe(audio)
    assert " ".join(s.text for s in segments) == "what is the weather"

    # ── Utterance 2: Parakeet now loaded -> routes to Parakeet GPU ASR ────
    handler._parakeet = _FakeParakeet(loaded=True, text="second question")
    text2 = handler._transcribe_via_parakeet(audio)
    assert text2 == "second question"
    assert handler._last_stt_timing["stt_backend"] == "parakeet"


def test_parakeet_failure_falls_back_to_whisper_permanently():
    """REQ-1 edge: a worker load failure marks _load_error and stays on whisper."""
    handler = _make_handler()
    handler._parakeet = _FakeParakeet(loaded=False)
    # A load failure means the worker FINISHED loading (unsuccessfully), so
    # _loading is False and _load_error is sticky — matching _spawn_worker's
    # finally block which clears _loading on every exit path.
    handler._parakeet._loading = False
    handler._parakeet._load_error = RuntimeError("CUDA OOM")
    handler._get_whisper = lambda: _FakeWhisper("fallback text")

    audio = np.zeros(16000, dtype=np.float32)
    text = handler._transcribe_via_parakeet(audio)
    assert text == ""
    # The failure is sticky: backend recorded as parakeet_failed, not loading.
    assert handler._last_stt_timing["stt_backend"] == "parakeet_failed"
    # Whisper remains the live fallback.
    segments, _ = handler._get_whisper().transcribe(audio)
    assert " ".join(s.text for s in segments) == "fallback text"
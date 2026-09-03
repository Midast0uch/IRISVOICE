"""
Unit tests for voice_command.py's in-process Parakeet ASR path.

Tests ``ParakeetTranscriber`` and ``_transcribe_via_parakeet()`` with mocked
model loading to verify the transcription chain:
  - Parakeet loaded + success → return text
  - Parakeet loaded + failure → return "" (caller tries faster-whisper)
  - Parakeet failed to load → return "" (caller tries faster-whisper)
"""

from __future__ import annotations

import time
import threading
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def parakeet():
    """A fresh ParakeetTranscriber (not yet loaded)."""
    from backend.audio.voice_command import ParakeetTranscriber
    return ParakeetTranscriber()


@pytest.fixture
def handler():
    """A minimal VoiceCommandHandler for testing _transcribe_via_parakeet."""
    from backend.audio.voice_command import VoiceCommandHandler
    h = VoiceCommandHandler.__new__(VoiceCommandHandler)
    h._logger = MagicMock()
    h._set_state = MagicMock()
    h._get_whisper = MagicMock()
    h._whisper = None
    h._whisper_lock = threading.Lock()
    h.sample_rate = 16000
    h._parakeet = MagicMock()
    return h


# ---------------------------------------------------------------------------
# Tests: ParakeetTranscriber._ensure_loaded
# ---------------------------------------------------------------------------

class TestParakeetTranscriberLoading:
    """Verify lazy-loading behavior of ParakeetTranscriber."""

    def test_initial_state_not_loaded(self, parakeet):
        assert parakeet._loaded is False
        assert parakeet._load_error is None

    @patch("backend.audio.voice_command.ParakeetTranscriber._ensure_loaded")
    def test_transcribe_skips_when_not_loaded(self, mock_ensure, parakeet):
        """transcribe() returns '' if model not loaded."""
        mock_ensure.return_value = False
        result = parakeet.transcribe(np.zeros(16000, dtype=np.float32))
        assert result == ""

    @patch("backend.audio.voice_command.ParakeetTranscriber._ensure_loaded")
    def test_transcribe_delegates_when_loaded(self, mock_ensure, parakeet):
        """transcribe() calls model.generate() and decodes via tokenizer."""
        mock_ensure.return_value = True
        parakeet._model = MagicMock()
        parakeet._model.parameters.return_value = iter([SimpleNamespace(dtype="float16")])
        parakeet._processor = MagicMock()

        # Keep this unit test independent of the 2-minute torch import. The
        # production method only needs no_grad() at this seam; GPU tensor
        # movement and model generation are already mocked below.
        fake_torch = SimpleNamespace(no_grad=lambda: nullcontext())

        # Mock processor return — Parakeet processor outputs input_features
        mock_inputs = MagicMock()
        mock_inputs.input_features = MagicMock()
        mock_inputs.input_features.cuda.return_value = MagicMock()
        mock_inputs.attention_mask = MagicMock()
        mock_inputs.attention_mask.cuda.return_value = MagicMock()
        parakeet._processor.return_value = mock_inputs

        # Mock model.generate() return (TDT models use generate(), not forward())
        # generate() returns ParakeetRNNTGenerateOutput with .sequences
        mock_output = MagicMock()
        mock_output.sequences = MagicMock()
        mock_output.sequences.__getitem__ = lambda self, i: MagicMock()
        parakeet._model.generate.return_value = mock_output

        # Mock processor.tokenizer.decode() (new path uses tokenizer, not batch_decode)
        parakeet._processor.tokenizer.decode.return_value = "hello world"

        audio = np.zeros(16000, dtype=np.float32)
        with patch.dict(sys.modules, {"torch": fake_torch}):
            result = parakeet.transcribe(audio)

        assert result == "hello world"


# ---------------------------------------------------------------------------
# Tests: _transcribe_via_parakeet (VoiceCommandHandler method)
# ---------------------------------------------------------------------------

class TestEnsureLoadedIsNonBlocking:
    """Parakeet loading must never block a voice caller behind a multi-minute
    checkpoint load. The tests replace the worker so they verify scheduling
    semantics without importing torch or touching the real model.
    """

    def test_first_call_starts_worker_and_returns_immediately(self, parakeet, monkeypatch):
        started = threading.Event()
        release = threading.Event()

        def worker():
            started.set()
            release.wait(timeout=2)
            with parakeet._lock:
                parakeet._loading = False

        monkeypatch.setattr(parakeet, "_load_model_worker", worker)
        start = time.monotonic()
        assert parakeet._ensure_loaded() is False
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
        assert started.wait(timeout=1)
        assert parakeet._loading is True
        release.set()

    def test_second_call_during_load_returns_immediately(self, parakeet, monkeypatch):
        parakeet._loading = True
        start = time.monotonic()
        result = parakeet._ensure_loaded()
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed < 1.0

    def test_loaded_fast_path_does_not_start_worker(self, parakeet, monkeypatch):
        worker = MagicMock()
        monkeypatch.setattr(parakeet, "_load_model_worker", worker)
        parakeet._loaded = True
        assert parakeet._ensure_loaded() is True
        worker.assert_not_called()

    def test_permanent_failure_always_returns_false(self, parakeet, monkeypatch):
        """A failed Parakeet load leaves whisper as the stable fallback."""
        worker = MagicMock()
        monkeypatch.setattr(parakeet, "_load_model_worker", worker)
        parakeet._load_error = RuntimeError("boom")
        assert parakeet._ensure_loaded() is False
        assert parakeet._ensure_loaded() is False
        worker.assert_not_called()


class TestTranscribeViaParakeet:
    """Verify the in-process Parakeet path in VoiceCommandHandler."""

    def test_success_returns_text(self, handler):
        """Successful Parakeet transcription returns the text."""
        handler._parakeet.transcribe.return_value = "hello world"
        audio = np.zeros(16000, dtype=np.float32)
        result = handler._transcribe_via_parakeet(audio)
        assert result == "hello world"

    def test_empty_text_returns_empty(self, handler):
        """Empty transcription → empty string."""
        handler._parakeet.transcribe.return_value = ""
        result = handler._transcribe_via_parakeet(np.zeros(16000, dtype=np.float32))
        assert result == ""

    def test_delegates_to_parakeet_transcriber(self, handler):
        """_transcribe_via_parakeet calls ParakeetTranscriber.transcribe."""
        handler._parakeet.transcribe.return_value = "test"
        audio = np.zeros(16000, dtype=np.float32)
        handler._transcribe_via_parakeet(audio)
        handler._parakeet.transcribe.assert_called_once_with(audio, handler.sample_rate)


class TestFasterWhisperFallback:
    """The backup must remain reachable when Parakeet is loading or fails."""

    def test_faster_whisper_is_used_for_fallback(self, handler):
        whisper = MagicMock()
        whisper.transcribe.return_value = (
            iter([SimpleNamespace(text=" hello from whisper ")]),
            None,
        )
        handler._get_whisper.return_value = whisper
        audio = np.zeros(16000, dtype=np.float32)
        fake_memory = SimpleNamespace(available=8 * 1024**3)

        with patch("psutil.virtual_memory", return_value=fake_memory):
            result = handler._transcribe_with_fallback(audio)

        assert result == "hello from whisper"
        handler._get_whisper.assert_called_once_with()
        whisper.transcribe.assert_called_once()

    def test_parakeet_loading_routes_to_fallback(self, handler):
        """The async warm-up state is not treated as a permanent failure."""
        handler._parakeet.transcribe.return_value = ""
        handler._parakeet._loading = True
        handler._parakeet._load_error = None
        result = handler._transcribe_via_parakeet(np.zeros(16000, dtype=np.float32))
        assert result == ""
        assert handler._last_stt_timing["stt_backend"] == "parakeet_loading"

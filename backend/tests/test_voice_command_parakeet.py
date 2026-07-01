"""
Unit tests for voice_command.py's in-process Parakeet ASR path.

Tests ``ParakeetTranscriber`` and ``_transcribe_via_parakeet()`` with mocked
model loading to verify the transcription chain:
  - Parakeet loaded + success → return text
  - Parakeet loaded + failure → return "" (caller tries faster-whisper)
  - Parakeet failed to load → return "" (caller tries faster-whisper)
"""

from __future__ import annotations

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
        """transcribe() calls model when loaded."""
        mock_ensure.return_value = True
        parakeet._model = MagicMock()
        parakeet._processor = MagicMock()

        # Mock processor return
        mock_inputs = MagicMock()
        mock_inputs.input_values = MagicMock()
        mock_inputs.input_values.cuda.return_value = MagicMock()
        mock_inputs.attention_mask = MagicMock()
        mock_inputs.attention_mask.cuda.return_value = MagicMock()
        parakeet._processor.return_value = mock_inputs

        # Mock model return
        mock_outputs = MagicMock()
        parakeet._model.return_value = mock_outputs

        # Mock batch_decode
        parakeet._processor.batch_decode.return_value = ["hello world"]

        audio = np.zeros(16000, dtype=np.float32)
        result = parakeet.transcribe(audio)

        assert result == "hello world"


# ---------------------------------------------------------------------------
# Tests: _transcribe_via_parakeet (VoiceCommandHandler method)
# ---------------------------------------------------------------------------

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

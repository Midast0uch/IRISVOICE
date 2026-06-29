"""
Unit tests for voice_command.py's Parakeet ASR fallback path.

Tests ``_transcribe_via_parakeet_service()`` with mocked HTTP calls to
verify the fallback chain: Parakeet success → return text, Parakeet
failure → return "" (caller tries faster-whisper).
"""

from __future__ import annotations

from unittest.mock import ANY, MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Fixture: a minimal VoiceCommandHandler with the new method
# ---------------------------------------------------------------------------

@pytest.fixture
def handler():
    """A VoiceCommandHandler with mocked audio engine and default config."""
    from backend.audio.voice_command import VoiceCommandHandler

    h = VoiceCommandHandler.__new__(VoiceCommandHandler)
    h._logger = MagicMock()
    h._set_state = MagicMock()
    h._get_whisper = MagicMock()
    h.sample_rate = 16000
    h.parakeet_service_url = "http://localhost:8765"
    return h


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTranscribeViaParakeetService:
    """Verify the Parakeet HTTP fallback path in VoiceCommandHandler."""

    # ── Happy path ─────────────────────────────────────────────────────

    @patch("backend.audio.voice_command.requests.post")
    def test_success_returns_text(self, mock_post, handler):
        """Successful Parakeet transcription returns the text."""
        mock_post.return_value = MagicMock(
            ok=True,
            status_code=200,
            json=lambda: {"text": "hello world", "confidence": 0.95},
            raise_for_status=lambda: None,
        )

        audio = np.zeros(16000, dtype=np.float32)  # 1 second of silence
        result = handler._transcribe_via_parakeet_service(audio)

        assert result == "hello world"
        mock_post.assert_called_once_with(
            "http://localhost:8765/transcribe",
            json=ANY,
            timeout=30.0,
        )

    @patch("backend.audio.voice_command.requests.post")
    def test_success_strips_whitespace(self, mock_post, handler):
        """Trailing/leading whitespace is stripped from the returned text."""
        mock_post.return_value = MagicMock(
            ok=True, status_code=200,
            json=lambda: {"text": "  hello  ", "confidence": 0.90},
            raise_for_status=lambda: None,
        )

        result = handler._transcribe_via_parakeet_service(np.zeros(16000, dtype=np.float32))
        assert result == "hello"

    # ── Connection errors ──────────────────────────────────────────────

    @patch("backend.audio.voice_command.requests.post")
    def test_connection_error_returns_empty(self, mock_post, handler):
        """Service not reachable → empty string (caller falls through)."""
        from requests.exceptions import ConnectionError
        mock_post.side_effect = ConnectionError("Connection refused")

        result = handler._transcribe_via_parakeet_service(np.zeros(16000, dtype=np.float32))
        assert result == ""

    @patch("backend.audio.voice_command.requests.post")
    def test_timeout_returns_empty(self, mock_post, handler):
        """Request timeout → empty string, not an exception."""
        from requests.exceptions import Timeout
        mock_post.side_effect = Timeout("timeout")

        result = handler._transcribe_via_parakeet_service(np.zeros(16000, dtype=np.float32))
        assert result == ""

    @patch("backend.audio.voice_command.requests.post")
    def test_http_error_returns_empty(self, mock_post, handler):
        """HTTP 5xx → empty string."""
        mock_post.return_value = MagicMock(
            ok=False, status_code=503,
            raise_for_status=MagicMock(side_effect=Exception("503")),
        )

        result = handler._transcribe_via_parakeet_service(np.zeros(16000, dtype=np.float32))
        assert result == ""

    # ── Empty / missing text ───────────────────────────────────────────

    @patch("backend.audio.voice_command.requests.post")
    def test_empty_text_from_service_returns_empty(self, mock_post, handler):
        """Service returns text='' → empty string (don't return empty text)."""
        mock_post.return_value = MagicMock(
            ok=True, status_code=200,
            json=lambda: {"text": "", "confidence": 0.0},
            raise_for_status=lambda: None,
        )

        result = handler._transcribe_via_parakeet_service(np.zeros(16000, dtype=np.float32))
        assert result == ""

    @patch("backend.audio.voice_command.requests.post")
    def test_missing_text_key_returns_empty(self, mock_post, handler):
        """Response missing 'text' key → handled gracefully."""
        mock_post.return_value = MagicMock(
            ok=True, status_code=200,
            json=lambda: {"confidence": 1.0},
            raise_for_status=lambda: None,
        )

        result = handler._transcribe_via_parakeet_service(np.zeros(16000, dtype=np.float32))
        assert result == ""

    # ── URL is None ────────────────────────────────────────────────────

    def test_no_url_returns_empty_immediately(self, handler):
        """parakeet_service_url = None → skip immediately, no HTTP call."""
        handler.parakeet_service_url = None

        result = handler._transcribe_via_parakeet_service(np.zeros(16000, dtype=np.float32))
        assert result == ""

    # ── Audio conversion correctness ───────────────────────────────────

    @patch("backend.audio.voice_command.requests.post")
    def test_sends_wav_in_request_body(self, mock_post, handler):
        """The request body should be a WAV with correct base64 encoding."""
        import base64
        import io
        import wave

        mock_post.return_value = MagicMock(
            ok=True, status_code=200,
            json=lambda: {"text": "ok", "confidence": 0.9},
            raise_for_status=lambda: None,
        )

        audio = np.zeros(16000, dtype=np.float32)
        handler._transcribe_via_parakeet_service(audio)

        call_kwargs = mock_post.call_args.kwargs
        body = call_kwargs["json"]

        assert "audio_base64" in body
        assert body["encoding"] == "pcm_s16le"
        assert body["sample_rate"] == 16000

        # Verify the base64 decodes to a valid WAV
        raw = base64.b64decode(body["audio_base64"])
        with wave.open(io.BytesIO(raw), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2  # 16-bit
            assert wf.getframerate() == 16000

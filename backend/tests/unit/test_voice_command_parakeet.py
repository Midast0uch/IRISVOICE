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


# ---------------------------------------------------------------------------
# Tests: wait_ready (ParakeetTranscriber)
# ---------------------------------------------------------------------------

class TestWaitReady:
    """wait_ready() must block until Parakeet loads, fails, or times out."""

    def test_returns_true_when_already_loaded(self, parakeet):
        parakeet._loaded = True
        assert parakeet.wait_ready(timeout=0.5) is True

    def test_returns_false_on_load_error(self, parakeet):
        parakeet._load_error = RuntimeError("boom")
        assert parakeet.wait_ready(timeout=0.5) is False

    def test_waits_for_load_to_complete(self, parakeet):
        """wait_ready polls until _loaded flips True."""
        def _flip_loaded():
            time.sleep(0.2)
            with parakeet._lock:
                parakeet._loaded = True
        threading.Thread(target=_flip_loaded, daemon=True).start()
        assert parakeet.wait_ready(timeout=2.0) is True

    def test_times_out_when_never_loads(self, parakeet):
        """wait_ready returns False after timeout if Parakeet never loads."""
        parakeet._loading = True  # stuck loading
        start = time.monotonic()
        result = parakeet.wait_ready(timeout=0.3)
        elapsed = time.monotonic() - start
        assert result is False
        assert elapsed >= 0.25  # actually waited, didn't return instantly


# ---------------------------------------------------------------------------
# Tests: _parakeet_warm_up (no thread churn when already warm)
# ---------------------------------------------------------------------------

class TestParakeetWarmUp:
    """_parakeet_warm_up must be a cheap no-op when Parakeet is already loaded."""

    def test_noop_when_already_loaded(self, handler, monkeypatch):
        """Already-loaded Parakeet must NOT spawn a warm-up thread."""
        handler._parakeet._loaded = True
        spawned = []
        monkeypatch.setattr(
            "backend.audio.voice_command.threading.Thread",
            lambda *a, **k: spawned.append(a) or MagicMock(),
        )
        handler._parakeet_warm_up()
        assert spawned == [], "No thread should be spawned when already loaded"

    def test_spawns_thread_when_cold(self, handler, monkeypatch):
        """Cold Parakeet spawns a warm-up thread."""
        handler._parakeet._loaded = False
        handler._parakeet._loading = False
        handler._parakeet._load_error = None
        handler._parakeet._ensure_loaded = MagicMock(return_value=False)
        spawned = []
        monkeypatch.setattr(
            "backend.audio.voice_command.threading.Thread",
            lambda *a, **k: spawned.append(a) or MagicMock(),
        )
        handler._parakeet_warm_up()
        assert len(spawned) == 1, "Cold Parakeet should spawn exactly one thread"


# ---------------------------------------------------------------------------
# Tests: _get_whisper bounded lock (no hang behind warm-up)
# ---------------------------------------------------------------------------

class TestGetWhisperBoundedLock:
    """_get_whisper must not block forever behind the warm-up thread's load."""

    @pytest.fixture
    def whisper_handler(self):
        """A handler with the REAL _get_whisper (not mocked)."""
        from backend.audio.voice_command import VoiceCommandHandler
        h = VoiceCommandHandler.__new__(VoiceCommandHandler)
        h._logger = MagicMock()
        h._whisper = None
        h._whisper_lock = threading.Lock()
        h._whisper_loading = False
        return h

    def test_returns_none_when_load_in_progress(self, whisper_handler):
        """If another thread is loading, _get_whisper returns None after timeout."""
        whisper_handler._whisper_loading = True  # warm-up in progress
        start = time.monotonic()
        result = whisper_handler._get_whisper(timeout=0.2)
        elapsed = time.monotonic() - start
        assert result is None, "Should return None when load is in progress"
        assert elapsed >= 0.15  # actually waited, didn't return instantly

    def test_returns_model_when_load_finishes(self, whisper_handler):
        """If the in-progress load finishes, _get_whisper returns the model."""
        fake_model = MagicMock()
        def _finish_load():
            time.sleep(0.2)
            whisper_handler._whisper = fake_model
        threading.Thread(target=_finish_load, daemon=True).start()
        whisper_handler._whisper_loading = True
        result = whisper_handler._get_whisper(timeout=2.0)
        assert result is fake_model

    def test_returns_model_when_lock_free(self, whisper_handler):
        """When nothing is loading, _get_whisper loads and returns the model."""
        fake_model = MagicMock()
        fake_fw = SimpleNamespace(WhisperModel=lambda *a, **k: fake_model)
        with patch.dict(sys.modules, {"faster_whisper": fake_fw}):
            result = whisper_handler._get_whisper(timeout=1.0)
        assert result is fake_model
        assert whisper_handler._whisper is fake_model
        assert whisper_handler._whisper_loading is False


# ---------------------------------------------------------------------------
# Tests: _start_recording_locked triggers Parakeet warm-up
# ---------------------------------------------------------------------------

class TestStartRecordingWarmsParakeet:
    """start_recording must trigger Parakeet warm-up (lazy load on wake word)."""

    def test_start_recording_calls_parakeet_warm_up(self, handler, monkeypatch):
        """The wake-word path (start_recording) must kick off Parakeet warm-up."""
        handler._parakeet._loaded = False
        handler._parakeet._loading = False
        handler._parakeet._load_error = None
        handler._parakeet._ensure_loaded = MagicMock(return_value=False)
        warm_calls = []
        monkeypatch.setattr(
            handler, "_parakeet_warm_up",
            lambda: warm_calls.append(True),
        )
        # Minimal state so _start_recording_locked doesn't crash.
        handler.is_recording = False
        handler._cancel_idle_timer = MagicMock()
        handler._cancel_event = threading.Event()
        handler._stop_event = threading.Event()
        handler._start_lock = threading.Lock()
        handler._register_frame_listener = MagicMock()
        handler._run_transcription = MagicMock()
        handler._on_audio_envelope = None
        handler._post_start_flush_frames = 0
        handler.sample_rate = 16000
        handler._recording_started_at = 0.0
        handler._auto_stop_mode = False
        handler._pre_speech_timeout_sec = 0.0
        handler._voice_timing = {}
        handler._set_state = MagicMock()

        handler.start_recording(auto_stop=True)
        assert warm_calls, "start_recording must trigger Parakeet warm-up"

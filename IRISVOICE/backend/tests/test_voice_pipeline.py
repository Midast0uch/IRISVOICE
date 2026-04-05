"""
test_voice_pipeline.py — IRIS Voice Pipeline Integration Tests

Tests the full voice pipeline without requiring real audio hardware or
downloaded models (mocked where needed).  Covers:

  1. TTSManager preflight path detection (F5-TTS + reference audio)
  2. TTSManager pyttsx3 fallback path
  3. TTSManager singleton behaviour
  4. VoiceCommandHandler state machine (start/stop/cancel)
  5. VoiceCommandHandler thread-safe cancel (Event not bool)
  6. AudioEngine ModelManager-free (dead code removed)
  7. audio/__init__.py exports only live symbols
  8. requirements.txt — RealtimeSTT absent, faster-whisper present
  9. Dead files removed (vad.py, tokenizer.py, model_manager.py)
 10. download_models.py script is present and importable
 11. WS event integration — audio_level callback fires during recording
 12. WS event integration — set_voice_handler wires all callbacks
 13. WS event integration — listening_state transitions match backend states
 14. WS event integration — text_response payload structure for voice flow
"""

import sys
import os
import threading
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path so backend.* imports work
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# 1. TTSManager — F5-TTS path constants
# ---------------------------------------------------------------------------

class TestTTSManagerPaths:
    def test_reference_audio_path_is_in_data_dir(self):
        """Reference audio must be under IRISVOICE/data/."""
        from backend.agent.tts import REFERENCE_AUDIO
        assert "data" in str(REFERENCE_AUDIO).replace("\\", "/"), (
            f"REFERENCE_AUDIO not in data/: {REFERENCE_AUDIO}"
        )
        assert REFERENCE_AUDIO.name == "TOMV2.wav"

    def test_reference_audio_exists(self):
        """TOMV2.wav must be present — without it voice cloning is disabled."""
        from backend.agent.tts import REFERENCE_AUDIO
        assert REFERENCE_AUDIO.exists(), (
            f"TOMV2.wav not found at {REFERENCE_AUDIO}. "
            "Place the reference audio file at IRISVOICE/data/TOMV2.wav."
        )

    def test_output_sample_rate_is_24khz(self):
        """Output sample rate must be 24 kHz (F5-TTS native rate)."""
        from backend.agent.tts import F5TTS_NATIVE_RATE, OUTPUT_SAMPLE_RATE
        assert F5TTS_NATIVE_RATE == 24_000
        assert OUTPUT_SAMPLE_RATE == 24_000

    def test_available_voices_list(self):
        """AVAILABLE_VOICES must include both Cloned Voice and Built-in."""
        from backend.agent.tts import AVAILABLE_VOICES
        assert "Cloned Voice" in AVAILABLE_VOICES
        assert "Built-in" in AVAILABLE_VOICES


# ---------------------------------------------------------------------------
# 2. TTSManager — singleton behaviour
# ---------------------------------------------------------------------------

class TestTTSManagerSingleton:
    def test_singleton_returns_same_instance(self):
        """TTSManager() must always return the same object."""
        from backend.agent.tts import TTSManager
        a = TTSManager()
        b = TTSManager()
        assert a is b

    def test_get_tts_manager_factory(self):
        """get_tts_manager() must return the singleton TTSManager."""
        from backend.agent.tts import TTSManager, get_tts_manager
        mgr = get_tts_manager()
        assert isinstance(mgr, TTSManager)
        assert mgr is TTSManager()

    def test_config_has_required_keys(self):
        """TTSManager config must have the three expected keys."""
        from backend.agent.tts import get_tts_manager
        cfg = get_tts_manager().get_config()
        assert "tts_enabled" in cfg
        assert "tts_voice" in cfg
        assert "speaking_rate" in cfg

    def test_get_voice_info_includes_model_and_reference(self):
        """get_voice_info() must expose model path and reference audio status."""
        from backend.agent.tts import get_tts_manager
        info = get_tts_manager().get_voice_info()
        assert "model_path_exists" in info
        assert "reference_audio_exists" in info
        assert info.get("reference_audio_exists") is True   # TOMV2.wav confirmed present


# ---------------------------------------------------------------------------
# 3. TTSManager — resample helper
# ---------------------------------------------------------------------------

class TestTTSResample:
    def test_noop_when_same_rate(self):
        """_resample must return unchanged array when src == dst rate."""
        from backend.agent.tts import _resample, OUTPUT_SAMPLE_RATE
        arr = np.random.randn(1000).astype(np.float32)
        out = _resample(arr, OUTPUT_SAMPLE_RATE)
        np.testing.assert_array_equal(out, arr.astype(np.float32))

    def test_resamples_to_correct_length(self):
        """_resample must produce array of correct length."""
        from backend.agent.tts import _resample, OUTPUT_SAMPLE_RATE
        orig_sr = 22_050
        arr = np.random.randn(22_050).astype(np.float32)  # 1 second at 22050 Hz
        out = _resample(arr, orig_sr)
        expected_len = int(len(arr) * OUTPUT_SAMPLE_RATE / orig_sr)
        # Allow ±1 sample for rounding
        assert abs(len(out) - expected_len) <= 1, (
            f"Expected ~{expected_len} samples, got {len(out)}"
        )

    def test_output_is_float32(self):
        """_resample must always return float32."""
        from backend.agent.tts import _resample
        arr = np.random.randn(500).astype(np.float64)
        out = _resample(arr, 16_000)
        assert out.dtype == np.float32


# ---------------------------------------------------------------------------
# 4. TTSManager — pyttsx3 fallback (synthesize returns None when disabled)
# ---------------------------------------------------------------------------

class TestTTSSynthesizeDisabled:
    def test_synthesize_returns_none_when_disabled(self):
        """synthesize() must return None when tts_enabled=False."""
        from backend.agent.tts import TTSManager
        mgr = TTSManager()
        mgr.update_config(tts_enabled=False)
        result = mgr.synthesize("hello world")
        assert result is None
        mgr.update_config(tts_enabled=True)  # restore

    def test_synthesize_returns_none_for_empty_text(self):
        """synthesize() must return None for blank/whitespace text."""
        from backend.agent.tts import TTSManager
        mgr = TTSManager()
        assert mgr.synthesize("") is None
        assert mgr.synthesize("   ") is None
        assert mgr.synthesize(None) is None  # type: ignore

    def test_synthesize_stream_empty_for_disabled(self):
        """synthesize_stream() must yield nothing when tts_enabled=False."""
        from backend.agent.tts import TTSManager
        mgr = TTSManager()
        mgr.update_config(tts_enabled=False)
        chunks = list(mgr.synthesize_stream("test"))
        assert chunks == []
        mgr.update_config(tts_enabled=True)  # restore


# ---------------------------------------------------------------------------
# 5. VoiceCommandHandler — state machine
# ---------------------------------------------------------------------------

class TestVoiceCommandHandlerStates:
    """Test VoiceCommandHandler without real audio hardware."""

    def _make_handler(self):
        """Build a VoiceCommandHandler with a fully mocked AudioEngine."""
        from backend.audio.voice_command import VoiceCommandHandler, VoiceState

        engine = MagicMock()
        engine.pipeline = MagicMock()  # pipeline exists → frame listener can register

        # Prevent warm_up() background thread from actually loading Whisper
        with patch.object(VoiceCommandHandler, "warm_up", return_value=None):
            handler = VoiceCommandHandler(engine)

        return handler, VoiceState

    def test_initial_state_is_idle(self):
        handler, VoiceState = self._make_handler()
        assert handler.state == VoiceState.IDLE
        assert not handler.is_recording

    def test_cancel_event_is_threading_event(self):
        """_cancel_event must be a threading.Event (not a plain bool)."""
        handler, _ = self._make_handler()
        assert isinstance(handler._cancel_event, threading.Event), (
            "_cancel_event must be threading.Event for thread-safe cancellation"
        )

    def test_stop_event_is_threading_event(self):
        handler, _ = self._make_handler()
        assert isinstance(handler._stop_event, threading.Event)

    def test_cancel_sets_event_and_stop(self):
        """cancel_recording() must set both _cancel_event and _stop_event."""
        handler, _ = self._make_handler()
        handler.is_recording = True  # fake an in-progress recording
        handler.cancel_recording()
        assert handler._cancel_event.is_set()
        assert handler._stop_event.is_set()

    def test_cancel_noop_when_not_recording(self):
        """cancel_recording() must do nothing if not currently recording."""
        handler, _ = self._make_handler()
        handler.cancel_recording()   # should not raise
        assert not handler._cancel_event.is_set()
        assert not handler._stop_event.is_set()

    def test_stop_sets_stop_event(self):
        """stop_recording() must set _stop_event without setting cancel."""
        handler, _ = self._make_handler()
        handler.is_recording = True
        handler.stop_recording()
        assert handler._stop_event.is_set()
        assert not handler._cancel_event.is_set()

    def test_get_status_returns_dict(self):
        handler, _ = self._make_handler()
        status = handler.get_status()
        assert isinstance(status, dict)
        assert "state" in status
        assert "is_recording" in status

    def test_set_active_session(self):
        handler, _ = self._make_handler()
        handler.set_active_session("session_xyz")
        assert handler._active_session_id == "session_xyz"

    def test_vad_poll_uses_event_wait(self):
        """VAD loop must use _stop_event.wait(timeout=...) not time.sleep."""
        import inspect
        from backend.audio.voice_command import VoiceCommandHandler
        src = inspect.getsource(VoiceCommandHandler._vad_wait_for_speech_then_silence)
        assert "_stop_event.wait(timeout=" in src, (
            "VAD loop must use _stop_event.wait(timeout=VAD_POLL_INTERVAL_SEC) "
            "instead of time.sleep() for CPU-efficient blocking"
        )

    def test_run_transcription_uses_cancel_event(self):
        """_run_transcription must check _cancel_event.is_set() not _cancelled."""
        import inspect
        from backend.audio.voice_command import VoiceCommandHandler
        src = inspect.getsource(VoiceCommandHandler._run_transcription)
        assert "_cancel_event.is_set()" in src, (
            "_run_transcription must use _cancel_event.is_set() (threading.Event) "
            "not the old _cancelled bool"
        )
        assert "_cancelled" not in src.replace("_cancel_event", ""), (
            "Old _cancelled bool still referenced in _run_transcription"
        )


# ---------------------------------------------------------------------------
# 6. AudioEngine — ModelManager removed
# ---------------------------------------------------------------------------

class TestAudioEngineClean:
    def test_model_manager_not_imported_in_engine(self):
        """engine.py must not import ModelManager after dead code removal."""
        engine_path = Path(__file__).parent.parent / "audio" / "engine.py"
        content = engine_path.read_text(encoding="utf-8")
        assert "from .model_manager import" not in content, (
            "engine.py still imports ModelManager — dead code not removed"
        )
        assert "model_manager import ModelManager" not in content

    def test_get_status_no_model_loaded_key(self):
        """AudioEngine.get_status() must not expose 'model_loaded' after cleanup."""
        from backend.audio.engine import AudioEngine
        # Reset singleton for test isolation
        AudioEngine._initialized = False
        AudioEngine._instance = None
        engine = AudioEngine()
        status = engine.get_status()
        assert "model_loaded" not in status, (
            "get_status() still returns 'model_loaded' from removed ModelManager"
        )

    def test_audio_engine_has_no_model_manager_attr(self):
        """AudioEngine instance must not have a model_manager attribute."""
        from backend.audio.engine import AudioEngine
        engine = AudioEngine()
        assert not hasattr(engine, "model_manager"), (
            "AudioEngine still has model_manager attribute — dead code not cleaned up"
        )


# ---------------------------------------------------------------------------
# 7. audio/__init__.py exports only live symbols
# ---------------------------------------------------------------------------

class TestAudioInitExports:
    def test_no_dead_symbols_exported(self):
        """audio/__init__.py must not export ModelManager, VADProcessor, etc."""
        import backend.audio as audio_module
        dead_names = ["ModelManager", "VADProcessor", "AudioTokenizer", "LFM2_5AudioProcessor"]
        for name in dead_names:
            assert not hasattr(audio_module, name), (
                f"backend.audio still exports dead symbol: {name}"
            )

    def test_live_symbols_exported(self):
        """audio/__init__.py must export AudioEngine, VoiceState, etc."""
        import backend.audio as audio_module
        for name in ["AudioEngine", "VoiceState", "get_audio_engine", "AudioPipeline"]:
            assert hasattr(audio_module, name), (
                f"backend.audio is missing expected export: {name}"
            )


# ---------------------------------------------------------------------------
# 8. requirements.txt — RealtimeSTT removed, faster-whisper present
# ---------------------------------------------------------------------------

class TestRequirements:
    @pytest.fixture
    def req_lines(self):
        req_path = Path(__file__).parent.parent.parent / "requirements.txt"
        return req_path.read_text(encoding="utf-8").splitlines()

    def test_realtimestt_removed(self, req_lines):
        """RealtimeSTT must be removed — it is an unused 100 MB dependency."""
        for line in req_lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert not stripped.lower().startswith("realtimestt"), (
                f"RealtimeSTT still in requirements.txt: {line}"
            )

    def test_faster_whisper_present(self, req_lines):
        """faster-whisper must be listed as a direct dependency."""
        found = any(
            line.strip().startswith("faster-whisper")
            for line in req_lines
            if not line.strip().startswith("#")
        )
        assert found, "faster-whisper not found in requirements.txt"

    def test_f5tts_referenced_in_requirements(self, req_lines):
        """requirements.txt must list f5-tts as a dependency."""
        found = any(
            line.strip().startswith("f5-tts")
            for line in req_lines
            if not line.strip().startswith("#")
        )
        assert found, "f5-tts not found in requirements.txt"


# ---------------------------------------------------------------------------
# 9. Dead files removed
# ---------------------------------------------------------------------------

class TestDeadFilesRemoved:
    def _audio_dir(self):
        return Path(__file__).parent.parent / "audio"

    def test_vad_py_removed(self):
        """backend/audio/vad.py must be deleted — Silero VAD stub never used."""
        assert not (self._audio_dir() / "vad.py").exists(), (
            "backend/audio/vad.py still exists — delete it (Silero VAD stub, never wired)"
        )

    def test_tokenizer_py_removed(self):
        """backend/audio/tokenizer.py must be deleted — random-noise placeholder."""
        assert not (self._audio_dir() / "tokenizer.py").exists(), (
            "backend/audio/tokenizer.py still exists — delete it (placeholder with random noise)"
        )

    def test_model_manager_py_removed(self):
        """backend/audio/model_manager.py must be deleted — LFM2 stub never completed."""
        assert not (self._audio_dir() / "model_manager.py").exists(), (
            "backend/audio/model_manager.py still exists — delete it (LFM2 stub, unimplemented)"
        )


# ---------------------------------------------------------------------------
# 10. download_models.py present and importable
# ---------------------------------------------------------------------------

class TestDownloadScript:
    def test_script_exists(self):
        """scripts/download_models.py must exist."""
        script = Path(__file__).parent.parent.parent / "scripts" / "download_models.py"
        assert script.exists(), "scripts/download_models.py not found"

    def test_script_importable(self):
        """download_models.py must import without errors."""
        import importlib.util
        script = Path(__file__).parent.parent.parent / "scripts" / "download_models.py"
        spec = importlib.util.spec_from_file_location("download_models", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "check_model_dir")
        assert hasattr(mod, "check_reference_audio")
        assert hasattr(mod, "run_verification")

    def test_check_functions_return_bool(self):
        """Verification helpers must return booleans."""
        import importlib.util
        script = Path(__file__).parent.parent.parent / "scripts" / "download_models.py"
        spec = importlib.util.spec_from_file_location("download_models", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert isinstance(mod.check_git(), bool)
        assert isinstance(mod.check_huggingface_hub(), bool)
        assert isinstance(mod.check_reference_audio(), bool)
        assert isinstance(mod.check_model_dir(), bool)

    def test_reference_audio_check_correct(self):
        """check_reference_audio() must return True since TOMV2.wav exists."""
        import importlib.util
        script = Path(__file__).parent.parent.parent / "scripts" / "download_models.py"
        spec = importlib.util.spec_from_file_location("download_models", script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # TOMV2.wav confirmed present from TTSManager path test above
        assert mod.check_reference_audio() is True, (
            "check_reference_audio() returned False even though TOMV2.wav exists"
        )


# ---------------------------------------------------------------------------
# 11. WS event integration — audio_level callback
# ---------------------------------------------------------------------------

class TestAudioLevelCallback:
    """VoiceCommandHandler must fire an audio_level callback during VAD loop."""

    def _make_handler(self):
        """Build a VoiceCommandHandler with all heavy deps mocked out."""
        with patch("backend.audio.engine.AudioEngine.__init__", lambda self: None):
            engine = object.__new__(__import__("backend.audio.engine", fromlist=["AudioEngine"]).AudioEngine)
            engine.pipeline = None
        from backend.audio.voice_command import VoiceCommandHandler
        with patch.object(VoiceCommandHandler, "warm_up"):
            handler = VoiceCommandHandler.__new__(VoiceCommandHandler)
            # Manually init without calling warm_up
            import threading
            handler.audio_engine = engine
            handler._whisper = None
            handler._whisper_lock = threading.Lock()
            handler.state = __import__("backend.audio.voice_command", fromlist=["VoiceState"]).VoiceState.IDLE
            handler.is_recording = False
            handler.audio_buffer = []
            handler._raw_frames = []
            handler.sample_rate = 16000
            handler._active_session_id = "test-session"
            handler._auto_stop_mode = False
            handler._pre_speech_timeout_sec = 0.0
            handler._stop_event = threading.Event()
            handler._cancel_event = threading.Event()
            handler._on_state_change = None
            handler._on_command_result = None
            handler._on_audio_level = None
            handler._frame_listener_registered = False
            handler._transcription_thread = None
            handler._start_lock = threading.Lock()
        return handler

    def test_set_audio_level_callback_stores_callable(self):
        """set_audio_level_callback must store the callable."""
        handler = self._make_handler()
        cb = MagicMock()
        handler.set_audio_level_callback(cb)
        assert handler._on_audio_level is cb

    def test_audio_level_callback_fires_during_vad(self):
        """
        _vad_wait_for_speech_then_silence must call _on_audio_level
        at least once when audio frames are present.

        Strategy: feed speech frames to trigger VAD_MIN_SPEECH_SEC onset,
        then feed silence frames to trigger VAD_SILENCE_SEC end-of-speech.
        The loop exits naturally; stop_event is NOT pre-set.
        """
        from backend.audio.voice_command import VoiceCommandHandler
        handler = self._make_handler()
        fired_levels = []
        handler.set_audio_level_callback(fired_levels.append)
        handler.is_recording = True

        # Compute how many frames are needed for speech + silence detection.
        # frame_sec = 512 / 16000 = 0.032 s
        frame_sec = 512 / handler.sample_rate
        speech_needed = int(VoiceCommandHandler.VAD_MIN_SPEECH_SEC / frame_sec)  # ~8
        silence_needed = int(VoiceCommandHandler.VAD_SILENCE_SEC / frame_sec)    # ~16

        # Speech frames: RMS = 0.05, well above VAD_ENERGY_THRESHOLD (0.008)
        speech_frame = np.full(512, 0.05, dtype=np.float32)
        # Silence frames: RMS ~= 0, below threshold
        silence_frame = np.zeros(512, dtype=np.float32)

        # Enough speech to pass speech_needed, then enough silence to exit
        for _ in range(speech_needed + 2):
            handler._raw_frames.append(speech_frame)
        for _ in range(silence_needed + 2):
            handler._raw_frames.append(silence_frame)

        # _stop_event NOT set — let end-of-speech detection exit the loop
        handler._auto_stop_mode = True
        handler._pre_speech_timeout_sec = 0.0
        handler._vad_wait_for_speech_then_silence()

        assert len(fired_levels) >= 1, (
            "audio_level callback was never fired during VAD loop — "
            "orb pulse animation will not work during voice recording"
        )
        # All emitted levels must be normalised 0.0–1.0
        for lvl in fired_levels:
            assert 0.0 <= lvl <= 1.0, f"audio_level {lvl} is outside [0.0, 1.0]"

    def test_audio_level_zero_frames_does_not_crash(self):
        """VAD loop with no frames must not raise even with callback set."""
        handler = self._make_handler()
        handler.set_audio_level_callback(lambda _: None)
        handler._stop_event.set()   # exit immediately
        # Should return without error
        handler._vad_wait_for_speech_then_silence()


# ---------------------------------------------------------------------------
# 12. WS event integration — set_voice_handler wires all callbacks
# ---------------------------------------------------------------------------

class TestSetVoiceHandlerWiring:
    """IRISGateway.set_voice_handler must wire command_result AND audio_level callbacks."""

    def _make_gateway_and_handler(self):
        from backend.audio.voice_command import VoiceCommandHandler
        from backend.audio.engine import AudioEngine

        mock_ws = MagicMock()
        mock_state = MagicMock()

        with patch("backend.iris_gateway.get_websocket_manager", return_value=mock_ws), \
             patch("backend.iris_gateway.get_state_manager", return_value=mock_state), \
             patch("backend.iris_gateway.WakeWordDiscovery"), \
             patch("backend.iris_gateway.CleanupAnalyzer"), \
             patch("backend.iris_gateway.LFMVLProvider"), \
             patch("threading.Thread"):
            from backend.iris_gateway import IRISGateway
            gw = IRISGateway.__new__(IRISGateway)
            # Minimal init
            gw._ws_manager = mock_ws
            gw._state_manager = mock_state
            gw._logger = __import__("logging").getLogger("test")
            gw._voice_handler = None
            gw._main_loop = None
            gw._conversation_sessions = set()
            gw._active_voice_client = {}
            gw._relisten_pre_speech_timeout = 8.0
            gw._tts_prewarmed = True
            gw._speech_interrupted = False

        # Minimal VoiceCommandHandler mock (no real audio engine needed)
        handler = MagicMock(spec=VoiceCommandHandler)
        handler._active_session_id = "default"
        return gw, handler

    def test_command_result_callback_wired(self):
        """set_voice_handler must call set_command_result_callback."""
        gw, handler = self._make_gateway_and_handler()
        gw.set_voice_handler(handler)
        handler.set_command_result_callback.assert_called_once_with(gw._on_voice_result)

    def test_audio_level_callback_wired(self):
        """set_voice_handler must call set_audio_level_callback."""
        gw, handler = self._make_gateway_and_handler()
        gw.set_voice_handler(handler)
        handler.set_audio_level_callback.assert_called_once()
        # The callback arg must be callable
        cb = handler.set_audio_level_callback.call_args[0][0]
        assert callable(cb), "audio_level callback must be a callable"


# ---------------------------------------------------------------------------
# 13. WS event integration — listening_state payload structure
# ---------------------------------------------------------------------------

class TestListeningStatePayloads:
    """
    All listening_state messages sent by the gateway must use the string
    states that the frontend VoiceState type accepts.
    Frontend type: "idle" | "listening" | "processing_conversation" |
                   "processing_tool" | "speaking" | "error"
    """

    VALID_STATES = frozenset({
        "idle", "listening", "processing_conversation",
        "processing_tool", "speaking", "error",
    })

    def _extract_listening_states(self):
        """Parse all listening_state payloads from iris_gateway.py source."""
        import re
        gateway_path = (
            Path(__file__).parent.parent / "iris_gateway.py"
        )
        source = gateway_path.read_text(encoding="utf-8")
        # Match: "type": "listening_state", ... "state": "<value>"
        # (state value appears on the next line in the actual source)
        states = re.findall(
            r'"type"\s*:\s*"listening_state".*?"state"\s*:\s*"([^"]+)"',
            source,
            re.DOTALL,
        )
        return states

    def test_all_listening_states_are_valid_frontend_values(self):
        """Every listening_state payload must use a value the frontend handles."""
        states = self._extract_listening_states()
        assert len(states) >= 5, (
            f"Expected at least 5 listening_state broadcasts, found {len(states)}"
        )
        invalid = [s for s in states if s not in self.VALID_STATES]
        assert not invalid, (
            f"listening_state payloads with values not handled by frontend: {invalid}\n"
            f"Frontend VoiceState type accepts: {sorted(self.VALID_STATES)}"
        )


# ---------------------------------------------------------------------------
# 14. WS event integration — text_response payload for voice flow
# ---------------------------------------------------------------------------

class TestTextResponsePayload:
    """
    Voice pipeline must send text_response with 'text' and 'sender' keys.
    Frontend hook handles: payload.text (str) + payload.sender ("user"|"assistant").
    """

    def test_text_response_sent_for_user_transcript(self):
        """
        _process_voice_transcription source must contain a text_response
        message with sender='user' (the transcript bubble).
        """
        import re
        gateway_path = Path(__file__).parent.parent / "iris_gateway.py"
        source = gateway_path.read_text(encoding="utf-8")
        # Find text_response blocks and verify sender=user appears
        matches = re.findall(
            r'"type"\s*:\s*"text_response".*?"sender"\s*:\s*"user"',
            source,
            re.DOTALL,
        )
        assert matches, (
            "iris_gateway.py must send a text_response with sender='user' "
            "so the user transcript bubble appears in ChatView after voice input"
        )

    def test_text_response_sent_for_assistant_reply(self):
        """
        _process_voice_transcription source must contain a text_response
        message with sender='assistant' (the AI reply bubble).
        """
        import re
        gateway_path = Path(__file__).parent.parent / "iris_gateway.py"
        source = gateway_path.read_text(encoding="utf-8")
        matches = re.findall(
            r'"type"\s*:\s*"text_response".*?"sender"\s*:\s*"assistant"',
            source,
            re.DOTALL,
        )
        assert matches, (
            "iris_gateway.py must send a text_response with sender='assistant' "
            "so the AI response bubble appears in ChatView after voice input"
        )

    def test_audio_level_event_type_matches_frontend_handler(self):
        """
        Backend must emit type='audio_level' with a 'level' key.
        Frontend hook case: 'audio_level' → payload.level (number).
        """
        import re
        gateway_path = Path(__file__).parent.parent / "iris_gateway.py"
        source = gateway_path.read_text(encoding="utf-8")
        # The set_voice_handler callback closure must contain both the type
        # and the level key
        assert '"audio_level"' in source, (
            "iris_gateway.py must broadcast type='audio_level' events "
            "for the IrisOrb to animate during voice recording"
        )
        assert '"level"' in source, (
            "audio_level broadcast must include a 'level' key in its payload"
        )

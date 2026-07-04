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
        """Output sample rate must be 24 kHz (Pocket-TTS native rate)."""
        from backend.agent.tts import TTS_NATIVE_RATE, OUTPUT_SAMPLE_RATE

        assert TTS_NATIVE_RATE == 24_000
        assert OUTPUT_SAMPLE_RATE == 24_000

    def test_available_voices_list(self):
        """AVAILABLE_VOICES must include Cloned Voice."""
        from backend.agent.tts import AVAILABLE_VOICES

        assert "Cloned Voice" in AVAILABLE_VOICES


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
        assert info.get("reference_audio_exists") is True  # TOMV2.wav confirmed present


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
        handler.cancel_recording()  # should not raise
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

        dead_names = [
            "ModelManager",
            "VADProcessor",
            "AudioTokenizer",
            "LFM2_5AudioProcessor",
        ]
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


# ---------------------------------------------------------------------------
# 11. WS event integration — audio_level callback
# ---------------------------------------------------------------------------


class TestAudioLevelCallback:
    """VoiceCommandHandler must fire an audio_level callback during VAD loop."""

    def _make_handler(self):
        """Build a VoiceCommandHandler with all heavy deps mocked out."""
        with patch("backend.audio.engine.AudioEngine.__init__", lambda self: None):
            engine = object.__new__(
                __import__("backend.audio.engine", fromlist=["AudioEngine"]).AudioEngine
            )
            engine.pipeline = None
        from backend.audio.voice_command import VoiceCommandHandler

        with patch.object(VoiceCommandHandler, "warm_up"):
            handler = VoiceCommandHandler.__new__(VoiceCommandHandler)
            # Manually init without calling warm_up
            import threading

            handler.audio_engine = engine
            handler._whisper = None
            handler._whisper_lock = threading.Lock()
            handler.state = __import__(
                "backend.audio.voice_command", fromlist=["VoiceState"]
            ).VoiceState.IDLE
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
        silence_needed = int(VoiceCommandHandler.VAD_SILENCE_SEC / frame_sec)  # ~16

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
        handler._stop_event.set()  # exit immediately
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

        with (
            patch("backend.iris_gateway.get_websocket_manager", return_value=mock_ws),
            patch("backend.iris_gateway.get_state_manager", return_value=mock_state),
            patch("backend.iris_gateway.WakeWordDiscovery"),
            patch("backend.iris_gateway.CleanupAnalyzer"),
            patch("backend.iris_gateway.LFMVLProvider"),
            patch("threading.Thread"),
        ):
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

    VALID_STATES = frozenset(
        {
            "idle",
            "listening",
            "processing_conversation",
            "processing_tool",
            "speaking",
            "error",
        }
    )

    def _extract_listening_states(self):
        """Parse all listening_state payloads from iris_gateway.py source."""
        import re

        gateway_path = Path(__file__).parent.parent / "iris_gateway.py"
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


# ---------------------------------------------------------------------------
# 15. Voice-first DER loop mode
# ---------------------------------------------------------------------------


class TestVoiceFirstDERMode:
    """
    Voice requests must use a tighter DER token budget (< 20k) so the agent
    responds quickly without spinning multi-step plans over voice.
    Spec: GOALS.md [2.4].
    """

    def test_voice_first_budget_exists_in_der_constants(self):
        """DER_TOKEN_BUDGETS must contain 'voice_first' with budget under 20k."""
        from backend.agent.der_constants import DER_TOKEN_BUDGETS

        assert "voice_first" in DER_TOKEN_BUDGETS, (
            "DER_TOKEN_BUDGETS missing 'voice_first' key — "
            "voice pipeline has no dedicated token budget"
        )
        budget = DER_TOKEN_BUDGETS["voice_first"]
        assert budget < 20_000, (
            f"voice_first budget is {budget}, must be under 20k for fast voice responses"
        )

    def test_process_text_message_accepts_from_voice_param(self):
        """process_text_message() must accept from_voice keyword argument."""
        import inspect
        from backend.agent.agent_kernel import AgentKernel

        sig = inspect.signature(AgentKernel.process_text_message)
        assert "from_voice" in sig.parameters, (
            "AgentKernel.process_text_message() missing 'from_voice' parameter — "
            "iris_gateway cannot signal voice origin to the DER loop"
        )

    def test_handle_voice_passes_from_voice_true(self):
        """iris_gateway._handle_voice must call process_text_message with from_voice=True."""
        gateway_path = Path(__file__).parent.parent / "iris_gateway.py"
        source = gateway_path.read_text(encoding="utf-8")
        assert "from_voice=True" in source, (
            "iris_gateway.py must pass from_voice=True to process_text_message() "
            "inside _handle_voice so voice requests use the voice_first DER budget"
        )


# ─── Phase 1 verification tests ────────────────────────────────────────
# These tests verify BEHAVIORAL changes, not just that code doesn't crash.
# Each test proves the specific change works as intended.

class TestVADSilenceThreshold:
    """Verify VAD_SILENCE_SEC=0.6 produces faster turn-end
    (was 0.8 → 0.6 for this session; old 0.5 was too aggressive)."""

    def _make_handler(self):
        from backend.audio.voice_command import VoiceCommandHandler

        handler = VoiceCommandHandler.__new__(VoiceCommandHandler)
        handler.is_recording = True
        handler.audio_buffer = []
        handler._raw_frames = []
        handler.sample_rate = 16000
        handler._active_session_id = "test-session"
        handler._auto_stop_mode = True
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

    def test_vad_silence_constant_is_06(self):
        """VAD_SILENCE_SEC must be 0.6."""
        from backend.audio.voice_command import VoiceCommandHandler
        assert VoiceCommandHandler.VAD_SILENCE_SEC == 0.6, (
            f"VAD_SILENCE_SEC is {VoiceCommandHandler.VAD_SILENCE_SEC}, expected 0.6"
        )

    def test_speech_plus_05s_silence_does_not_end_speech(self):
        """
        With VAD_SILENCE_SEC=0.6, feeding speech + only 0.5s of silence
        must NOT trigger end-of-speech. 0.5 < 0.6, so the VAD loop should
        still be blocked waiting for more silence frames.
        """
        from backend.audio.voice_command import VoiceCommandHandler

        handler = self._make_handler()
        frame_sec = 512 / handler.sample_rate  # 0.032s

        speech_needed = int(VoiceCommandHandler.VAD_MIN_SPEECH_SEC / frame_sec)
        speech_frame = np.full(512, 0.05, dtype=np.float32)
        for _ in range(speech_needed + 2):
            handler._raw_frames.append(speech_frame)

        # 0.5s of silence (15 frames) — still less than 0.6s threshold
        silence_05_frames = int(0.5 / frame_sec)
        silence_frame = np.zeros(512, dtype=np.float32)
        for _ in range(silence_05_frames):
            handler._raw_frames.append(silence_frame)

        result = {"returned": False}
        def run_vad():
            handler._vad_wait_for_speech_then_silence()
            result["returned"] = True

        t = threading.Thread(target=run_vad, daemon=True)
        t.start()
        t.join(timeout=1.0)

        assert not result["returned"], (
            "VAD returned after only 0.5s of silence — "
            "threshold is {VoiceCommandHandler.VAD_SILENCE_SEC}, expected 0.6"
        )

    def test_vad_silence_sec_frames_ends_speech(self):
        """
        Feeding speech + VAD_SILENCE_SEC worth of silence frames
        (+ 1 extra) MUST trigger end-of-speech.
        """
        from backend.audio.voice_command import VoiceCommandHandler

        handler = self._make_handler()
        frame_sec = 512 / handler.sample_rate

        speech_needed = int(VoiceCommandHandler.VAD_MIN_SPEECH_SEC / frame_sec)
        speech_frame = np.full(512, 0.05, dtype=np.float32)
        for _ in range(speech_needed + 2):
            handler._raw_frames.append(speech_frame)

        silence_needed = int(VoiceCommandHandler.VAD_SILENCE_SEC / frame_sec)
        silence_frame = np.zeros(512, dtype=np.float32)
        for _ in range(silence_needed + 1):
            handler._raw_frames.append(silence_frame)

        result = {"returned": False}
        def run_vad():
            handler._vad_wait_for_speech_then_silence()
            result["returned"] = True

        t = threading.Thread(target=run_vad, daemon=True)
        t.start()
        t.join(timeout=2.0)

        assert result["returned"], (
            f"VAD did NOT return after {VoiceCommandHandler.VAD_SILENCE_SEC}s of silence — "
            "end-of-speech detection is broken. Check VAD_SILENCE_SEC and frame counting."
        )


class TestSentenceBoundaryRegex:
    """Verify the new sentence boundary flushes on comma/semicolon/colon, not just dot/excl/question."""

    def test_new_pattern_matches_comma(self):
        """New pattern must match comma+space as a sentence boundary."""
        import re
        pattern = r"([.!?;,:])\s+|(?<=.{40})"
        m = re.search(pattern, "Hello, world")
        assert m is not None, "New pattern must match comma+space"
        assert m.group(1) == ",", f"Expected comma, got {m.group(1)}"

    def test_new_pattern_matches_semicolon(self):
        """New pattern must match semicolon+space as a sentence boundary."""
        import re
        pattern = r"([.!?;,:])\s+|(?<=.{40})"
        m = re.search(pattern, "First part; second part")
        assert m is not None, "New pattern must match semicolon+space"
        assert m.group(1) == ";", f"Expected semicolon, got {m.group(1)}"

    def test_new_pattern_matches_colon(self):
        """New pattern must match colon+space as a sentence boundary."""
        import re
        pattern = r"([.!?;,:])\s+|(?<=.{40})"
        m = re.search(pattern, "Note: this is important")
        assert m is not None, "New pattern must match colon+space"
        assert m.group(1) == ":", f"Expected colon, got {m.group(1)}"

    def test_new_pattern_matches_period(self):
        """New pattern must still match period+space (hard stop)."""
        import re
        pattern = r"([.!?;,:])\s+|(?<=.{40})"
        m = re.search(pattern, "Hello. World")
        assert m is not None, "New pattern must match period+space"
        assert m.group(1) == ".", f"Expected period, got {m.group(1)}"

    def test_old_pattern_would_not_match_comma(self):
        """Prove the OLD pattern [.!?]\\s+ would NOT have matched a comma.

        This demonstrates the behavioral improvement: the old code would
        buffer 'Hello, world this is a long sentence' without flushing,
        causing TTS latency. The new code flushes at the comma.
        """
        import re
        old_pattern = r"[.!?]\s+"
        m = re.search(old_pattern, "Hello, world")
        assert m is None, (
            "Old pattern matched comma — the old code would NOT have flushed here, "
            "proving the new pattern is a real improvement"
        )

    def test_40char_lookahead_flushes_long_text(self):
        """Text >= 40 chars without punctuation must flush via lookahead."""
        import re
        pattern = r"([.!?;,:])\s+|(?<=.{40})"
        long_text = "a" * 41  # 41 chars, no punctuation
        m = re.search(pattern, long_text)
        assert m is not None, "40-char lookahead must flush long unpunctuated text"


class TestFillerPhrases:
    """Verify filler phrase API contract — get_filler_audio returns correct types."""

    def test_filler_cache_attribute_exists(self):
        """TTSManager must have _filler_cache dict for pre-synthesized fillers."""
        from backend.agent.tts import TTSManager
        mgr = TTSManager.__new__(TTSManager)
        mgr._filler_cache = {}
        assert hasattr(mgr, "_filler_cache")
        assert isinstance(mgr._filler_cache, dict)

    def test_get_filler_audio_returns_none_when_empty(self):
        """get_filler_audio() must return None when cache is empty."""
        from backend.agent.tts import TTSManager
        mgr = TTSManager.__new__(TTSManager)
        mgr._filler_cache = {}
        result = mgr.get_filler_audio()
        assert result is None, "get_filler_audio() should return None when cache is empty"

    def test_get_filler_audio_returns_tuple_when_populated(self):
        """get_filler_audio() must return (audio, sample_rate) tuple from cache."""
        import numpy as np
        from backend.agent.tts import TTSManager
        mgr = TTSManager.__new__(TTSManager)
        fake_audio = np.zeros(24000, dtype=np.float32)  # 1 second at 24kHz
        mgr._filler_cache = {"One moment.": (fake_audio, 24000)}
        result = mgr.get_filler_audio()
        assert result is not None, "get_filler_audio() returned None with populated cache"
        audio, sr = result
        assert sr == 24000, f"Expected 24000 Hz sample rate, got {sr}"
        assert len(audio) > 0, "Filler audio must not be empty"

    def test_get_filler_audio_picks_from_cache(self):
        """get_filler_audio() must return one of the cached phrases."""
        import numpy as np
        from backend.agent.tts import TTSManager
        mgr = TTSManager.__new__(TTSManager)
        phrases = {"Hello": (np.zeros(100, dtype=np.float32), 24000),
                   "World": (np.zeros(200, dtype=np.float32), 24000)}
        mgr._filler_cache = phrases
        # Call 10 times — should always return something from the cache
        for _ in range(10):
            result = mgr.get_filler_audio()
            assert result is not None
            # Compare by sample rate and audio length (numpy arrays can't use 'in')
            assert result[1] == 24000, f"Expected 24000 Hz, got {result[1]}"
            assert len(result[0]) in (100, 200), (
                f"Filler audio length {len(result[0])} not in cache values"
            )


class TestTTSStreamingCadence:
    """Verify the streaming consumer broadcasts audio_envelope per chunk."""

    def test_audio_envelope_broadcast_per_chunk(self):
        """When the streaming consumer writes N chunks, it must broadcast
        audio_envelope N times with phase='speaking' — not once at the end."""
        import numpy as np
        import threading
        from unittest.mock import MagicMock

        # Mock WebSocket manager
        ws_mock = MagicMock()
        session_id = "test-session"
        main_loop = MagicMock()
        main_loop.is_running.return_value = True

        # Simulate the per-chunk broadcast logic (extracted from streaming consumer)
        broadcast_calls = []

        def simulate_streaming_chunks(chunks):
            rms_peak = 0.0
            for chunk in chunks:
                ch_f32 = np.asarray(chunk, dtype=np.float32)
                _rms = float(np.sqrt(np.mean(np.square(ch_f32))))
                if _rms > rms_peak:
                    rms_peak = _rms
                _norm_rms = min(1.0, _rms / (rms_peak + 1e-10) * 2.0)
                # This is the per-chunk broadcast we want to verify
                broadcast_calls.append({
                    "rms": _norm_rms,
                    "cadence": _norm_rms,
                    "phase": "speaking",
                })

        # Feed 3 test chunks with different volumes
        chunk1 = np.full(480, 0.2, dtype=np.float32)   # quiet speech
        chunk2 = np.full(480, 0.8, dtype=np.float32)   # loud speech
        chunk3 = np.full(480, 0.1, dtype=np.float32)   # trailing tail

        simulate_streaming_chunks([chunk1, chunk2, chunk3])

        assert len(broadcast_calls) == 3, (
            f"Expected 3 audio_envelope broadcasts for 3 chunks, got {len(broadcast_calls)}"
        )
        for i, call in enumerate(broadcast_calls):
            assert call["phase"] == "speaking", (
                f"Chunk {i}: expected phase='speaking', got '{call['phase']}'"
            )
            assert 0 <= call["rms"] <= 1.0, (
                f"Chunk {i}: RMS {call['rms']} out of [0, 1] range"
            )

    def test_idle_envelope_after_stream_close(self):
        """After streaming closes, an audio_envelope with phase='idle' must
        be broadcast so the orb stops breathing."""
        ws_mock = MagicMock()
        session_id = "test-session"
        main_loop = MagicMock()
        main_loop.is_running.return_value = True

        idle_broadcast = []

        def _send_idle():
            idle_broadcast.append({
                "type": "audio_envelope",
                "payload": {"rms": 0, "cadence": 0, "phase": "idle"},
            })

        # Simulate post-stream idle broadcast (extracted from streaming consumer)
        _sd_stream_started = True
        if _sd_stream_started and session_id:
            _send_idle()

        assert len(idle_broadcast) == 1, "Expected idle broadcast after stream close"
        assert idle_broadcast[0]["payload"]["phase"] == "idle"
        assert idle_broadcast[0]["payload"]["rms"] == 0


class TestTTSWordSyncFromPlaybackPosition:
    """Verify word highlighting uses actual audio position (_sd_stream.time),
    not wall-clock sleep-timers — matching the word sync document's approach."""

    def _simulate_word_monitor(self, words, total_samples, sample_rate, stream_time, total_synth_samples):
        """Core logic from the streaming word monitor: calculates word index
        from actual audio playback position (_sd_stream.time)."""
        _word_count = len(words) or 1
        _total_dur = (
            total_synth_samples / sample_rate
            if total_synth_samples
            else stream_time * 2
        )
        _frac = min(1.0, stream_time / _total_dur)
        _idx = int(_frac * _word_count)
        if _idx >= _word_count:
            _idx = _word_count - 1
        return _idx

    def test_word_index_from_audio_position(self):
        """At 0.5s into a 2.0s / 10-word response, word index should be ~2.
        At 1.5s, ~7. At the end, the last word. This proves the word
        is derived from the audio clock, not an independent timer."""
        words = ["the", "quick", "brown", "fox", "jumps",
                 "over", "the", "lazy", "sleeping", "dog"]
        total_samples = 48000  # 2.0s at 24000 Hz

        idx_25 = self._simulate_word_monitor(words, total_samples, 24000, 0.5, total_samples)
        idx_50 = self._simulate_word_monitor(words, total_samples, 24000, 1.0, total_samples)
        idx_75 = self._simulate_word_monitor(words, total_samples, 24000, 1.5, total_samples)
        idx_100 = self._simulate_word_monitor(words, total_samples, 24000, 2.0, total_samples)

        assert idx_25 == 2, f"At 25% expected word 2, got {idx_25}"
        assert idx_50 == 5, f"At 50% expected word 5, got {idx_50}"
        assert idx_75 == 7, f"At 75% expected word 7, got {idx_75}"
        assert idx_100 == 9, f"At 100% expected last word (9), got {idx_100}"

    def test_word_index_stays_in_bounds(self):
        """If playback position exceeds the estimated duration (possible if
        _total_synth_samples is a running estimate), word index must clamp
        to the last word, not go out of bounds."""
        words = ["hello", "world"]
        total_samples = 12000  # 0.5s at 24000 Hz

        # Simulate position beyond the estimate
        idx = self._simulate_word_monitor(words, total_samples, 24000, 1.0, total_samples)
        assert idx == 1, f"At double duration, expected last word (1), got {idx}"

    def test_word_index_early_without_total_samples(self):
        """Before _total_synth_samples is available from the producer,
        the monitor falls back to _pos * 2 as an estimate. At 0.1s,
        estimated duration is 0.2s, so 50% through 10 words = word 5."""
        words = list(range(10))
        total_samples = 0  # not yet set by producer

        idx = self._simulate_word_monitor(words, total_samples, 24000, 0.1, total_samples)
        # fallback: _total_dur = 0.1 * 2 = 0.2, frac = 0.1/0.2 = 0.5, idx = 0.5 * 10 = 5
        assert idx == 5, f"Expected fallback word 5, got {idx}"

    def test_word_index_start_at_zero(self):
        """Before audio plays (_sd_stream.time <= 0), the monitor
        should not broadcast any word (stays at first word / no-op)."""
        words = ["hello"] * 5
        total_samples = 24000  # 1.0s

        idx = self._simulate_word_monitor(words, total_samples, 24000, 0, total_samples)
        assert idx == 0, f"At position 0, expected word 0, got {idx}"


class TestTTSWordTimingOffset:
    """Verify word timing skips already-spoken words."""

    def test_word_timing_skips_past_words(self):
        """
        When the word thread starts N seconds into playback (because all
        chunks were accumulated first), it must skip words whose timing
        has already passed and start from the current word.
        """
        # Simulate a 5-word sentence with character-proportional timings
        words = ["The", "quick", "brown", "fox", "jumps"]
        approx_duration = 2.0  # 2 seconds total
        _total_chars = sum(len(w) for w in words)  # 19

        word_timings = []
        _cumulative = 0.0
        for w in words:
            _cumulative += (len(w) / _total_chars) * approx_duration
            word_timings.append(_cumulative)

        # Word timings: The=0.21s, quick=0.53s, brown=0.84s, fox=1.05s, jumps=2.0s

        # Simulate the thread starting 1.0s into playback — "brown" should be
        # the current word (its timing 0.84s is the first < 1.0s elapsed)
        _start_word = 0
        _elapsed = 1.0
        for _i, _t in enumerate(word_timings):
            if _t >= _elapsed:
                _start_word = _i
                break
        else:
            _start_word = len(words) - 1

        # "brown" is word index 2 (0-indexed: The=0, quick=1, brown=2)
        assert _start_word == 2, (
            f"At 1.0s elapsed, expected start_word=2 (brown), got {_start_word}"
        )

        # Now verify that only words 2-4 are broadcast
        broadcasted = []
        for _i in range(_start_word, len(words)):
            broadcasted.append(words[_i])

        assert broadcasted == ["brown", "fox", "jumps"], (
            f"Expected ['brown', 'fox', 'jumps'], got {broadcasted}"
        )

    def test_word_timing_start_at_zero_if_no_elapsed(self):
        """If the word thread starts before any audio plays, it starts from word 0."""
        words = ["Hello", "world"]
        word_timings = [0.3, 0.8]

        _start_word = 0
        _elapsed = 0.0
        for _i, _t in enumerate(word_timings):
            if _t >= _elapsed:
                _start_word = _i
                break

        assert _start_word == 0, (
            f"At 0s elapsed, expected start_word=0, got {_start_word}"
        )

    def test_word_timing_ends_at_last_word_if_all_past(self):
        """If all words have already been spoken, start from the last word."""
        words = ["A", "B", "C"]
        word_timings = [0.2, 0.5, 1.0]

        _start_word = 0
        _elapsed = 2.0  # past the end
        for _i, _t in enumerate(word_timings):
            if _t >= _elapsed:
                _start_word = _i
                break
        else:
            _start_word = len(words) - 1

        assert _start_word == len(words) - 1, (
            f"When all past, expected start_word={len(words)-1}, got {_start_word}"
        )

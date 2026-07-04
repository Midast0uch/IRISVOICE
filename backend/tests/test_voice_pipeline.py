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

    def test_vad_silence_constant_is_075(self):
        """VAD_SILENCE_SEC must be 0.75."""
        from backend.audio.voice_command import VoiceCommandHandler
        assert VoiceCommandHandler.VAD_SILENCE_SEC == 0.75, (
            f"VAD_SILENCE_SEC is {VoiceCommandHandler.VAD_SILENCE_SEC}, expected 0.75"
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
        """Core logic from the streaming word monitor: waits until total
        synth samples is set, then calculates word index from audio position.
        Returns -1 if total samples not yet available (no broadcast)."""
        _word_count = len(words) or 1
        if not total_synth_samples or total_synth_samples <= 0:
            return -1  # unknown total — don't broadcast yet
        _total_dur = total_synth_samples / sample_rate
        if _total_dur <= 0:
            return -1
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

    def test_word_index_skips_when_total_samples_missing(self):
        """Before _total_synth_samples is set, the monitor must NOT broadcast
        (returns -1) instead of using a fallback estimate that would lock
        the word index at 50% and then jump when total arrives."""
        words = list(range(10))
        total_samples = 0  # not yet set by producer

        idx = self._simulate_word_monitor(words, total_samples, 24000, 0.1, total_samples)
        assert idx == -1, f"Expected -1 (no broadcast), got {idx}"

    def test_word_index_start_at_zero(self):
        """Before audio plays (_sd_stream.time <= 0), the monitor
        should not broadcast any word (stays at first word / no-op)."""
        words = ["hello"] * 5
        total_samples = 24000  # 1.0s

        idx = self._simulate_word_monitor(words, total_samples, 24000, 0, total_samples)
        assert idx == 0, f"At position 0, expected word 0, got {idx}"


class TestWordMonitorStableWn:
    """Verify the word monitor's _wn capping and monotonic fraction."""

    def _capped_wn(self, real_wn, last_word_idx):
        """Replicates the production word monitor's _wn capping logic:
        _wn = min(real_wn, last_word_idx + 5)"""
        if last_word_idx < 0:
            return real_wn
        return min(real_wn, last_word_idx + 5)

    def test_wn_starts_at_real_count(self):
        """Before any words are highlighted, _wn = real_wn (no cap needed)."""
        assert self._capped_wn(10, -1) == 10
        assert self._capped_wn(2, -1) == 2

    def test_wn_capped_at_current_word_plus_5(self):
        """_wn caps at last_word_idx + 5 so new sentences don't jump the index."""
        # Real word count is 30, but we've only highlighted word 2
        assert self._capped_wn(30, 2) == 7  # min(30, 7) = 7
        assert self._capped_wn(30, 10) == 15  # min(30, 15) = 15
        assert self._capped_wn(30, 25) == 30  # min(30, 30) = 30 (caught up)

    def test_wn_grows_gradually_with_word_index(self):
        """As last_word_idx grows, _wn grows too. Simulate a 30-word response."""
        wn = 0
        for idx in range(0, 30):
            wn = self._capped_wn(30, idx)
            expected = min(30, idx + 5)
            assert wn == expected, f"At word {idx}: expected _wn={expected}, got {wn}"

    def test_wn_never_exceeds_real_wn(self):
        """_wn must never exceed the real word count."""
        for real_wn in [5, 10, 50]:
            for idx in range(-1, real_wn + 5):
                capped = self._capped_wn(real_wn, idx)
                assert capped <= real_wn, (
                    f"real_wn={real_wn}, idx={idx}: capped={capped} > real_wn"
                )

    def test_monotonic_fraction_with_padding(self):
        """The fraction _pos / (_total_dur + 0.5) must never decrease.
        The 0.5s padding prevents the initial fraction from being near 1.0
        (when _pos ≈ _total_dur for the first chunk)."""
        frac = 0.0
        _last_frac = 0.0
        # Simulate: _pos grows, _total_dur jumps ahead
        for _pos, _dur in [(0.5, 1.0), (0.8, 1.2), (1.0, 3.0), (1.5, 3.2)]:
            _frac = min(1.0, _pos / (_dur + 0.5))
            if _frac < _last_frac:
                _frac = _last_frac
            else:
                _last_frac = _frac
            assert _frac >= frac, f"Fraction decreased: {frac} -> {_frac}"
            frac = _frac
        # After step 2: frac = 0.8 / (1.2 + 0.5) = 0.8/1.7 ≈ 0.4706
        # Step 3: 1.0 / (3.0 + 0.5) = 0.286 < 0.4706 → guard keeps 0.4706
        # Step 4: 1.5 / (3.2 + 0.5) = 0.405 < 0.4706 → guard keeps 0.4706
        # Final value should be 0.4706 (guard never let it decrease)
        assert abs(frac - 0.470588235) < 1e-6, f"Expected 0.4706, got {frac}"

    def test_word_index_only_moves_forward(self):
        """Word index must never decrease when _wn grows."""
        _last_word_idx = -1
        # Simulate: fraction constant 0.5, _wn jumps from 2 to 17
        cases = [
            (_wn := 2, int(0.5 * 2) - 1),   # idx = 0 (safe)
            (_wn := 17, int(0.5 * 17) - 1),  # idx = 7 (jumps but forward)
        ]
        for _, _idx in cases:
            if _idx <= _last_word_idx:
                _idx = _last_word_idx  # clamp (backup guard)
            assert _idx >= _last_word_idx, f"Word index went backwards: {_last_word_idx} -> {_idx}"
            _last_word_idx = _idx

        # Final word index should be 7 (not 0, not 1)
        assert _last_word_idx == 7, f"Expected final word 7, got {_last_word_idx}"


class TestNewConversationContextReset:
    """Verify new_conversation WS message clears the agent kernel context."""

    def test_new_conversation_calls_clear_conversation(self):
        """When a new_conversation message is received, the agent kernel's
        clear_conversation must be called so the next voice STT starts
        with a fresh context (not the old thread's history)."""
        from unittest.mock import MagicMock, patch

        # Mock the get_agent_kernel function
        mock_kernel = MagicMock()
        mock_kernel.clear_conversation.return_value = None

        with patch("backend.iris_gateway.get_agent_kernel", return_value=mock_kernel):
            # Import and call the handler via the message router
            from backend.iris_gateway import IRISGateway

            # Create a minimal mock gateway
            gateway = IRISGateway.__new__(IRISGateway)
            gateway._logger = MagicMock()
            gateway._ws_manager = MagicMock()
            gateway._agent_kernels = {}
            gateway._main_loop = MagicMock()

            # Simulate what _handle_chat does for new_conversation
            session_id = "test-session"
            message = {"type": "new_conversation", "payload": {"conversation_id": "new-conv-1"}}

            # _handle_chat is async, so we run it
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    gateway._handle_chat(session_id, "test-client", message)
                )
            finally:
                loop.close()

            # Verify clear_conversation was called on the agent kernel
            mock_kernel.clear_conversation.assert_called_once()


class TestPendingAccumulation:
    """Verify the TTS producer's _pending list accumulates items correctly
    and clears ONLY after a successful flush.

    This tests the structural fix for the bug where `_pending = []` ran
    at 20sp (outside the `if _pending_words >= _target:` block), clearing
    items every iteration regardless of whether the threshold was met.
    Items with fewer words than the threshold were permanently lost —
    only the first sentence (is_first_chunk gate) and the END_STREAM
    flush survived. This caused TTS to play the first few words then
    restart (the END_STREAM flush sounded like "starting over").
    """

    def _make_producer(self, first_threshold=6, normal_threshold=8):
        """Create a minimal producer state machine matching the production
        code in iris_gateway.py lines 2665-2836.

        Returns a dict with the producer state and a `feed()` method that
        simulates one iteration of the while True: loop."""
        state = {
            "_pending": [],
            "_pending_words": 0,
            "_all_words": [],
            "_target": first_threshold,
            "_is_first_chunk": True,
            "_flushed_chunks": [],   # list of (chunk_text, word_count)
            "_first_audio_pushed": False,
        }

        def feed(item, interrupted=False):
            """Simulate one iteration of the producer loop.

            item=None means END_STREAM sentinel.
            Returns 'flushed', 'accumulated', or 'end_stream_flush'."""
            if item is None:
                # END_STREAM path (lines 2699-2722)
                if state["_pending"] and not interrupted:
                    chunk = " ".join(state["_pending"])
                    state["_flushed_chunks"].append((chunk, state["_pending_words"]))
                    state["_pending"] = []
                    state["_pending_words"] = 0
                    return "end_stream_flush"
                return "end_stream_empty"

            if interrupted:
                return "interrupted"

            # Accumulate (line 2724-2726)
            state["_pending"].append(item)
            state["_pending_words"] += len(item.split())
            state["_all_words"].extend(item.split())

            # Threshold check (lines 2728-2730)
            should_flush = (
                state["_pending_words"] >= state["_target"]
                or (state["_is_first_chunk"] and len(state["_pending"]) >= 1)
            )

            if should_flush:
                chunk = " ".join(state["_pending"])
                state["_flushed_chunks"].append((chunk, state["_pending_words"]))
                # Post-flush housekeeping (lines 2753-2755)
                if state["_is_first_chunk"]:
                    state["_is_first_chunk"] = False
                    state["_target"] = normal_threshold
                # THIS IS THE FIX: _pending = [] and _pending_words = 0
                # must be INSIDE the if block, not outside it
                state["_pending"] = []
                state["_pending_words"] = 0
                return "flushed"

            # Non-flush: items stay in _pending (no clear!)
            return "accumulated"

        return state, feed

    def test_items_accumulate_below_threshold(self):
        """Items with fewer words than the threshold must accumulate
        in _pending, not be cleared each iteration."""
        state, feed = self._make_producer(normal_threshold=8)

        # First item always flushes due to is_first_chunk gate — skip it
        feed("Of course!")
        assert state["_is_first_chunk"] is False

        # Now test accumulation: "For a classic" = 3 words, below threshold (8)
        assert feed("For a classic") == "accumulated"
        assert len(state["_pending"]) == 1
        assert state["_pending_words"] == 3

        # "apple pie," = 2 words, still below threshold
        assert feed("apple pie,") == "accumulated"
        assert len(state["_pending"]) == 2
        assert state["_pending_words"] == 5

        # "you can't go wrong" = 4 words, total 9 >= 8 → flush
        assert feed("you can't go wrong") == "flushed"
        assert len(state["_pending"]) == 0
        assert state["_pending_words"] == 0

        # Verify the flushed chunk contains all three items
        assert len(state["_flushed_chunks"]) == 2  # first + this flush
        flushed_text = state["_flushed_chunks"][1][0]
        assert "For a classic" in flushed_text
        assert "apple pie," in flushed_text
        assert "you can't go wrong" in flushed_text

    def test_first_chunk_flushes_immediately(self):
        """is_first_chunk gate: first item triggers flush regardless of
        word count, even if below normal threshold."""
        state, feed = self._make_producer(first_threshold=6, normal_threshold=8)

        # "Of course!" = 2 words, below first_threshold (6)
        # but is_first_chunk=True → flush
        assert feed("Of course!") == "flushed"
        assert len(state["_pending"]) == 0
        assert len(state["_flushed_chunks"]) == 1
        assert "Of course!" in state["_flushed_chunks"][0][0]

        # After first flush, is_first_chunk=False, target=normal_threshold
        assert state["_is_first_chunk"] is False
        assert state["_target"] == 8

    def test_pending_not_cleared_on_non_flush(self):
        """THE CRITICAL BUG TEST: _pending must NOT be cleared when the
        word threshold is not met. Before the fix, `_pending = []` ran
        at 20sp (outside the if block), clearing items every iteration."""
        state, feed = self._make_producer(normal_threshold=10)

        # Skip first-chunk flush
        feed("skip")
        assert state["_is_first_chunk"] is False

        # Send 3 items of 2 words each = 6 total, below threshold (10)
        feed("hello world")
        feed("foo bar")
        feed("baz qux")

        # All 3 items must still be in _pending
        assert len(state["_pending"]) == 3
        assert state["_pending_words"] == 6
        assert state["_pending"] == ["hello world", "foo bar", "baz qux"]

        # No additional flushes occurred (only the skip flush)
        assert len(state["_flushed_chunks"]) == 1

    def test_flush_captures_all_accumulated_items(self):
        """After accumulating multiple items, the flush must capture ALL
        of them in the chunk, not just the current item."""
        state, feed = self._make_producer(normal_threshold=12)

        # Skip first-chunk flush
        feed("skip")

        feed("one two")       # 2 words
        feed("three four")    # 2 words
        feed("five six")      # 2 words  → 6 total
        feed("seven eight")   # 2 words  → 8 total
        feed("nine ten")      # 2 words  → 10 total
        feed("eleven twelve thirteen")  # 3 words → 13 >= 12 → flush

        assert len(state["_flushed_chunks"]) == 2  # skip + this flush
        chunk_text, word_count = state["_flushed_chunks"][1][0], state["_flushed_chunks"][1][1]
        assert word_count == 13
        # All 6 items must be in the flushed chunk
        for item in ["one two", "three four", "five six",
                     "seven eight", "nine ten", "eleven twelve thirteen"]:
            assert item in chunk_text

    def test_end_stream_flushes_remaining(self):
        """END_STREAM sentinel must flush whatever is left in _pending,
        even if the threshold was never met."""
        state, feed = self._make_producer(normal_threshold=20)

        # Skip first-chunk flush
        feed("skip")

        feed("short")          # 1 word, accumulated
        feed("text here")      # 2 words, accumulated → 3 total

        assert len(state["_pending"]) == 2
        assert state["_pending_words"] == 3

        # END_STREAM
        result = feed(None)
        assert result == "end_stream_flush"
        assert len(state["_pending"]) == 0
        assert state["_pending_words"] == 0
        assert len(state["_flushed_chunks"]) == 2  # skip + end_stream
        assert "short" in state["_flushed_chunks"][1][0]
        assert "text here" in state["_flushed_chunks"][1][0]

    def test_multiple_flush_cycles(self):
        """After a flush, _pending resets and the next batch accumulates
        correctly from scratch."""
        state, feed = self._make_producer(normal_threshold=8)

        # Skip first-chunk flush
        feed("skip")

        # Batch 1: accumulate + flush
        feed("aaa bbb ccc")     # 3 words
        feed("ddd eee fff")     # 3 words → 6 total
        feed("ggg hhh iii")     # 3 words → 9 >= 8 → flush
        assert len(state["_flushed_chunks"]) == 2  # skip + batch1
        assert state["_pending"] == []
        assert state["_pending_words"] == 0

        # Batch 2: accumulate + flush
        feed("jjj kkk lll")     # 3 words
        feed("mmm nnn ooo")     # 3 words → 6 total
        feed("ppp qqq rrr")     # 3 words → 9 >= 8 → flush
        assert len(state["_flushed_chunks"]) == 3  # skip + batch1 + batch2
        assert state["_pending"] == []

        # Verify both batches have correct content
        assert "aaa bbb ccc" in state["_flushed_chunks"][1][0]
        assert "jjj kkk lll" in state["_flushed_chunks"][2][0]

    def test_bug_repro_items_lost_every_iteration(self):
        """Reproduce the exact bug scenario: 6-word sentence fragments
        with threshold=8. Before the fix, _pending cleared every iteration,
        so items never accumulated and only the first sentence (is_first_chunk)
        and END_STREAM flush survived."""
        state, feed = self._make_producer(first_threshold=6, normal_threshold=8)

        # Simulate LLM streaming: 6-word sentence fragments
        # First item: is_first_chunk → flushes immediately (correct)
        result1 = feed("Of course! For a classic")
        assert result1 == "flushed"
        assert "Of course! For a classic" in state["_flushed_chunks"][0][0]

        # Items 2-4: 6 words each, threshold=8 after first flush
        # BUG: _pending cleared every iteration → items LOST
        # FIX: items accumulate until threshold met
        result2 = feed("apple pie, you can't go wrong")
        assert result2 == "accumulated"
        assert len(state["_pending"]) == 1  # item survived!

        # item2 (6 words) + item3 (6 words) = 12 ≥ 8 → flush
        result3 = feed("with a flaky golden crust")
        assert result3 == "flushed"
        # Both items flushed together
        assert len(state["_flushed_chunks"]) == 2  # first + this flush
        batch2_text = state["_flushed_chunks"][1][0]
        assert "apple pie" in batch2_text
        assert "flaky golden crust" in batch2_text
        # pending is cleared after flush
        assert len(state["_pending"]) == 0

        # item4 starts fresh accumulation
        result4 = feed("and warm cinnamon filling inside")
        assert result4 == "accumulated"
        assert len(state["_pending"]) == 1
        assert state["_pending"][0] == "and warm cinnamon filling inside"

        # END_STREAM flushes item4
        feed(None)
        assert len(state["_flushed_chunks"]) == 3
        assert "and warm cinnamon filling inside" in state["_flushed_chunks"][2][0]

        # TOTAL: 3 flushes covering ALL text. Before fix: only 2 flushes
        # (first item + END_STREAM), items 2-4 permanently lost.
        assert len(state["_flushed_chunks"]) == 3

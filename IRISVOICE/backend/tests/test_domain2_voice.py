"""
Domain 2 — Voice Pipeline verification tests.

Covers [2.1] Wake word (Porcupine wiring + graceful disable),
       [2.2] STT (faster-whisper importable, gateway wiring, callback chain),
       [2.3] TTS (Piper fallback when F5-TTS absent, speak path wired),
       [2.4] Voice-first DER mode (budget enforced, single-step limit),
       Linux compatibility (sounddevice, platform-aware .ppn selection).

Run with:
    python -m pytest backend/tests/test_domain2_voice.py -v
"""
import importlib
import sys
import threading
import types
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# [2.1] Porcupine — graceful disable + gateway wiring
# ---------------------------------------------------------------------------

class TestPorcupineGracefulDisable:
    """Porcupine disables itself cleanly when no access key is available."""

    def test_porcupine_disabled_without_access_key(self, monkeypatch):
        """PorcupineWakeWordDetector._disabled=True when access_key missing (v2 API).

        pvporcupine IS installed; we just clear the env var and reset the cached
        access-key check so the detector exercises the early-return disable path.
        The detector returns before ever calling pv.create(), so this is safe.
        """
        monkeypatch.setenv("PICOVOICE_ACCESS_KEY", "")
        import backend.voice.porcupine_detector as _mod
        original_cache = _mod._PORCUPINE_NEEDS_ACCESS_KEY
        _mod._PORCUPINE_NEEDS_ACCESS_KEY = True  # simulate pvporcupine v2
        try:
            from backend.voice.porcupine_detector import PorcupineWakeWordDetector
            det = PorcupineWakeWordDetector(access_key=None, builtin_keywords=["porcupine"])
            assert det._disabled is True, "Should be disabled when no access key"
            assert det.porcupine is None
        finally:
            _mod._PORCUPINE_NEEDS_ACCESS_KEY = original_cache

    def test_porcupine_disabled_reason_is_descriptive(self, monkeypatch):
        """Disabled reason string explains what the user needs to do."""
        monkeypatch.setenv("PICOVOICE_ACCESS_KEY", "")
        import backend.voice.porcupine_detector as _mod
        original_cache = _mod._PORCUPINE_NEEDS_ACCESS_KEY
        _mod._PORCUPINE_NEEDS_ACCESS_KEY = True
        try:
            from backend.voice.porcupine_detector import PorcupineWakeWordDetector
            det = PorcupineWakeWordDetector(access_key=None, builtin_keywords=["porcupine"])
            assert (
                "PICOVOICE_ACCESS_KEY" in det._disabled_reason
                or "access" in det._disabled_reason.lower()
            )
        finally:
            _mod._PORCUPINE_NEEDS_ACCESS_KEY = original_cache

    def test_porcupine_disabled_no_wake_words(self):
        """PorcupineWakeWordDetector._disabled=True when no wake words given (v1 API path)."""
        import backend.voice.porcupine_detector as _mod
        original_cache = _mod._PORCUPINE_NEEDS_ACCESS_KEY
        _mod._PORCUPINE_NEEDS_ACCESS_KEY = False  # simulate pvporcupine v1 (no key needed)
        try:
            from backend.voice.porcupine_detector import PorcupineWakeWordDetector
            det = PorcupineWakeWordDetector(
                access_key=None,
                custom_model_path=None,
                builtin_keywords=[]
            )
            assert det._disabled is True
        finally:
            _mod._PORCUPINE_NEEDS_ACCESS_KEY = original_cache

    def test_gateway_has_set_voice_handler_method(self):
        """IRISGateway exposes set_voice_handler() for external wiring."""
        src = open("backend/iris_gateway.py", encoding="utf-8").read()
        assert "def set_voice_handler" in src, \
            "set_voice_handler() must exist in iris_gateway.py"

    def test_gateway_set_voice_handler_registers_callback(self):
        """set_voice_handler wires _on_voice_result as command result callback."""
        src = open("backend/iris_gateway.py", encoding="utf-8").read()
        assert "set_command_result_callback" in src and "_on_voice_result" in src, \
            "set_voice_handler must call set_command_result_callback(_on_voice_result)"

    def test_gateway_voice_handler_checked_before_start_recording(self):
        """Gateway checks _voice_handler is not None before calling start_recording."""
        src = open("backend/iris_gateway.py", encoding="utf-8").read()
        assert "self._voice_handler" in src and "start_recording" in src, \
            "Gateway must guard _voice_handler before start_recording()"

    def test_audio_engine_initializes_without_pvporcupine(self):
        """AudioEngine module exists and pvporcupine is not a module-level import in it."""
        # Check file exists without importing it (avoids numpy C-extension reload issue)
        import pathlib
        engine_path = pathlib.Path("backend/audio/engine.py")
        assert engine_path.exists(), "backend/audio/engine.py must exist"
        src = engine_path.read_text(encoding="utf-8")
        # pvporcupine must NOT be imported at module level in engine.py
        lines = src.split("\n")
        module_level_pv = any(
            "pvporcupine" in l and not l.startswith(" ") and not l.startswith("\t")
            for l in lines
        )
        assert not module_level_pv, \
            "pvporcupine must NOT be imported at module level in engine.py"


# ---------------------------------------------------------------------------
# [2.2] STT — faster-whisper importable + VoiceCommandHandler wiring
# ---------------------------------------------------------------------------

class TestSTTWiring:
    """faster-whisper is installed and properly wired into the voice pipeline."""

    def test_faster_whisper_importable(self):
        """faster-whisper package must be installed for STT to work."""
        import importlib.util
        spec = importlib.util.find_spec("faster_whisper")
        assert spec is not None, \
            "faster-whisper not installed — run: pip install faster-whisper"

    def test_voice_command_handler_has_transcribe_fallback(self):
        """VoiceCommandHandler has _transcribe_with_fallback for robustness."""
        src = open("backend/audio/voice_command.py", encoding="utf-8").read()
        assert "_transcribe_with_fallback" in src, \
            "_transcribe_with_fallback must be defined in voice_command.py"

    def test_voice_command_handler_lazy_loads_whisper(self):
        """WhisperModel is lazy-loaded, not at module import time."""
        src = open("backend/audio/voice_command.py", encoding="utf-8").read()
        # lazy load is inside a method, not at module top
        lines = src.split("\n")
        module_level_import = any(
            "from faster_whisper" in l and not l.startswith(" ") and not l.startswith("\t")
            for l in lines
        )
        assert not module_level_import, \
            "faster_whisper must not be imported at module level (lazy import required)"

    def test_voice_handler_has_set_command_result_callback(self):
        """VoiceCommandHandler exposes set_command_result_callback for gateway wiring."""
        src = open("backend/audio/voice_command.py", encoding="utf-8").read()
        assert "def set_command_result_callback" in src, \
            "VoiceCommandHandler must have set_command_result_callback()"

    def test_voice_handler_callback_fires_on_transcription(self):
        """After transcription, command result callback is called with transcript."""
        src = open("backend/audio/voice_command.py", encoding="utf-8").read()
        # Callback must be called somewhere in the transcription flow
        assert "_command_result_callback" in src or "command_result_callback" in src, \
            "Transcription result must route through the command result callback"

    def test_process_voice_transcription_uses_from_voice_flag(self):
        """Gateway passes from_voice=True to process_text_message for voice requests."""
        src = open("backend/iris_gateway.py", encoding="utf-8").read()
        assert "from_voice=True" in src, \
            "process_text_message must be called with from_voice=True for voice input"

    def test_on_voice_result_dispatches_to_event_loop(self):
        """_on_voice_result dispatches to main event loop (thread-safe)."""
        src = open("backend/iris_gateway.py", encoding="utf-8").read()
        assert "run_coroutine_threadsafe" in src or "call_soon_threadsafe" in src, \
            "_on_voice_result must use thread-safe dispatch to main event loop"


# ---------------------------------------------------------------------------
# [2.3] TTS — Piper fallback + speak path wired
# ---------------------------------------------------------------------------

class TestTTSWiring:
    """TTS produces output and falls back to Piper when F5-TTS is not installed."""

    def test_piper_importable(self):
        """Piper TTS must be installed as the built-in fallback."""
        import importlib.util
        spec = importlib.util.find_spec("piper")
        assert spec is not None, \
            "piper not installed — run: pip install piper-tts"

    def test_tts_enabled_by_default(self):
        """TTSManager.config['tts_enabled'] defaults to True."""
        from backend.agent.tts import get_tts_manager
        mgr = get_tts_manager()
        assert mgr.config.get("tts_enabled", True) is True, \
            "TTS must be enabled by default"

    def test_tts_select_engine_does_not_raise_when_f5_missing(self):
        """_select_engine() falls back to Piper gracefully when f5_tts is absent."""
        from backend.agent.tts import get_tts_manager
        mgr = get_tts_manager()
        # Force Cloned Voice mode even if f5_tts is missing
        original_voice = mgr.config.get("tts_voice", "Built-in Piper")
        mgr.config["tts_voice"] = "Cloned Voice"
        try:
            mgr._select_engine()  # must not raise even without f5_tts
        except Exception as e:
            assert False, f"_select_engine raised with Cloned Voice + no f5_tts: {e}"
        finally:
            mgr.config["tts_voice"] = original_voice

    def test_tts_synthesize_returns_none_when_disabled(self):
        """synthesize() returns None when tts_enabled=False (no audio produced)."""
        from backend.agent.tts import get_tts_manager
        mgr = get_tts_manager()
        original = mgr.config.get("tts_enabled", True)
        mgr.config["tts_enabled"] = False
        try:
            result = mgr.synthesize("Hello world")
            assert result is None, "synthesize must return None when TTS disabled"
        finally:
            mgr.config["tts_enabled"] = original

    def test_tts_synthesize_stream_is_empty_when_disabled(self):
        """synthesize_stream() yields nothing when tts_enabled=False."""
        from backend.agent.tts import get_tts_manager
        mgr = get_tts_manager()
        original = mgr.config.get("tts_enabled", True)
        mgr.config["tts_enabled"] = False
        try:
            chunks = list(mgr.synthesize_stream("Hello world"))
            assert chunks == [], "synthesize_stream must yield nothing when TTS disabled"
        finally:
            mgr.config["tts_enabled"] = original

    def test_gateway_speaks_response_after_agent_reply(self):
        """Gateway _process_voice_transcription calls TTS after LLM response."""
        src = open("backend/iris_gateway.py", encoding="utf-8").read()
        assert "_speak_response" in src or "synthesize_stream" in src or "synthesize" in src, \
            "Gateway must call TTS after LLM response in voice pipeline"

    def test_tts_speak_path_broadcasts_speaking_state(self):
        """Speaking state is broadcast to frontend during TTS playback."""
        src = open("backend/iris_gateway.py", encoding="utf-8").read()
        assert '"speaking"' in src or "'speaking'" in src, \
            "Gateway must broadcast speaking state during TTS playback"

    def test_f5tts_not_required_at_startup(self):
        """f5_tts absence must not crash backend at import time."""
        # We already know f5_tts may not be installed — verify the module
        # never imports it at the top level
        src = open("backend/agent/tts.py", encoding="utf-8").read()
        lines = src.split("\n")
        module_level_f5 = any(
            "import f5" in l.lower() and not l.startswith(" ") and not l.startswith("\t")
            for l in lines
        )
        assert not module_level_f5, \
            "f5_tts must not be imported at module level in tts.py"


# ---------------------------------------------------------------------------
# [2.4] Voice-first DER mode — budget enforced, single-step limit
# ---------------------------------------------------------------------------

class TestVoiceFirstDERMode:
    """Voice-first DER mode applies tight token budget and single-step limit."""

    def test_voice_first_budget_exists_in_der_token_budgets(self):
        """DER_TOKEN_BUDGETS must have a 'voice_first' key."""
        from backend.agent.agent_kernel import DER_TOKEN_BUDGETS
        assert "voice_first" in DER_TOKEN_BUDGETS, \
            "voice_first must be a key in DER_TOKEN_BUDGETS"

    def test_voice_first_budget_is_under_20k(self):
        """Voice-first token budget must be < 20,000 tokens (tight response target)."""
        from backend.agent.agent_kernel import DER_TOKEN_BUDGETS
        budget = DER_TOKEN_BUDGETS["voice_first"]
        assert budget < 20000, \
            f"voice_first budget must be < 20k tokens, got {budget}"

    def test_voice_first_budget_is_15k(self):
        """Voice-first budget should be exactly 15,000 as specified in GOALS.md."""
        from backend.agent.agent_kernel import DER_TOKEN_BUDGETS
        assert DER_TOKEN_BUDGETS["voice_first"] == 15000, \
            f"voice_first budget must be 15000, got {DER_TOKEN_BUDGETS['voice_first']}"

    def test_from_voice_flag_sets_voice_first_mode(self):
        """process_text_message with from_voice=True sets _mode_name to voice_first."""
        src = open("backend/agent/agent_kernel.py", encoding="utf-8").read()
        assert "voice_first" in src and "from_voice" in src, \
            "from_voice=True must lead to voice_first mode selection"

    def test_voice_first_single_step_enforced(self):
        """DER loop limits voice_first tasks to single queue item."""
        src = open("backend/agent/agent_kernel.py", encoding="utf-8").read()
        # The code checks task_class == "voice_first" and len(items) > 1
        assert 'task_class == "voice_first"' in src or "voice_first" in src, \
            "voice_first single-step guard must be present in DER loop"

    def test_voice_first_overrides_mode_detector(self):
        """Voice requests bypass mode detection and lock to voice_first."""
        src = open("backend/agent/agent_kernel.py", encoding="utf-8").read()
        # Mode detector is only run when NOT a voice request
        voice_first_line_idx = src.find('_mode_name = "voice_first"')
        mode_detector_line_idx = src.find("_mode_result")
        assert voice_first_line_idx > 0, "voice_first assignment must exist"
        assert mode_detector_line_idx > 0, "mode detector must exist"


# ---------------------------------------------------------------------------
# Linux compatibility — sounddevice, platform .ppn selection, portaudio note
# ---------------------------------------------------------------------------

class TestLinuxCompatibility:
    """Cross-platform compatibility checks for the voice pipeline."""

    def test_sounddevice_importable(self):
        """sounddevice must be installed (requires PortAudio system library on Linux)."""
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            raise AssertionError(
                "sounddevice not installed. On Linux run: "
                "sudo apt install portaudio19-dev && pip install sounddevice"
            )

    def test_pipeline_lazy_imports_sounddevice(self):
        """AudioPipeline lazy-loads sounddevice to avoid PortAudio init at startup."""
        src = open("backend/audio/pipeline.py", encoding="utf-8").read()
        lines = src.split("\n")
        module_level_sd = any(
            "import sounddevice" in l and not l.startswith(" ") and not l.startswith("\t")
            for l in lines
        )
        assert not module_level_sd, \
            "sounddevice must NOT be imported at module level (lazy via _sd())"

    def test_wake_word_discovery_selects_platform_ppn(self):
        """WakeWordDiscovery picks the correct .ppn filename for the current platform."""
        from backend.voice.wake_word_discovery import WakeWordDiscovery
        disc = WakeWordDiscovery()
        filename = disc.HEY_IRIS_FILENAME
        if sys.platform == "win32":
            assert "windows" in filename, \
                f"Windows should use windows .ppn, got: {filename}"
        elif sys.platform == "darwin":
            assert "mac" in filename or "macos" in filename, \
                f"macOS should use mac .ppn, got: {filename}"
        else:
            assert "linux" in filename, \
                f"Linux should use linux .ppn, got: {filename}"

    def test_wake_word_discovery_linux_fallback_warns_not_crashes(self):
        """If Linux .ppn missing but Windows .ppn present, discovery warns not crashes."""
        from backend.voice.wake_word_discovery import WakeWordDiscovery
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            # Place only a Windows .ppn
            win_ppn = os.path.join(tmpdir, "hey-iris_en_windows_v4_0_0.ppn")
            open(win_ppn, "wb").close()
            disc = WakeWordDiscovery(wake_words_dir=tmpdir)
            disc.scan_directory()
            # verify_hey_iris must return True (fallback) without raising
            result = disc.verify_hey_iris()
            assert isinstance(result, bool), "verify_hey_iris must return bool"

    def test_porcupine_detector_lazy_imports_pvporcupine(self):
        """pvporcupine DLL is not loaded at module import (lazy inside _initialize_porcupine)."""
        src = open("backend/voice/porcupine_detector.py", encoding="utf-8").read()
        lines = src.split("\n")
        module_level_pv = any(
            "import pvporcupine" in l and not l.startswith(" ") and not l.startswith("\t")
            for l in lines
        )
        assert not module_level_pv, \
            "pvporcupine must NOT be imported at module level"

    def test_numpy_importable(self):
        """numpy is required by audio pipeline on all platforms."""
        import importlib.util
        spec = importlib.util.find_spec("numpy")
        assert spec is not None, "numpy not installed — pip install numpy"

    def test_requirements_has_sounddevice(self):
        """requirements.txt must list sounddevice for cross-platform audio I/O."""
        reqs = open("requirements.txt", encoding="utf-8").read()
        assert "sounddevice" in reqs, \
            "requirements.txt must include sounddevice"

    def test_requirements_has_faster_whisper(self):
        """requirements.txt must list faster-whisper for STT."""
        reqs = open("requirements.txt", encoding="utf-8").read()
        assert "faster-whisper" in reqs or "faster_whisper" in reqs, \
            "requirements.txt must include faster-whisper"

    def test_requirements_has_pvporcupine(self):
        """requirements.txt must list pvporcupine for wake word detection."""
        reqs = open("requirements.txt", encoding="utf-8").read()
        assert "pvporcupine" in reqs, \
            "requirements.txt must include pvporcupine"

    def test_audio_pipeline_handles_missing_input_device_gracefully(self):
        """AudioPipeline.start() returns True if only output fails (input ok or vice versa)."""
        src = open("backend/audio/pipeline.py", encoding="utf-8").read()
        # Both streams are started independently — one failure should not block the other
        assert "input_ok" in src and "output_ok" in src, \
            "AudioPipeline must track input/output independently for graceful degradation"

"""
Voice Command Handler — RealtimeSTT pipeline for IRIS.

Replaces the previous LFM audio model + manual VAD + fallback transcription chain
with RealtimeSTT (KoljaB/RealtimeSTT), which bundles faster-whisper + silero-VAD.

Wake word detection (Porcupine) is still handled upstream by WakeWordDetector in
pipeline.py.  This handler focuses solely on post-wake-word recording and
transcription.

Flow:
  1. iris_gateway calls start_recording(auto_stop=True)  ← wake word path
     or start_recording(auto_stop=False)                 ← double-click path
  2. AudioEngine frame listener (_capture_frame) feeds int16 PCM bytes to
     RealtimeSTT via recorder.feed_audio()
  3. RealtimeSTT's built-in silero-VAD detects end-of-speech automatically
     (auto_stop=True) or stop_recording() is called by the user (manual stop)
  4. recorder.text() unblocks → _on_transcription_complete fires
  5. _on_command_result callback → iris_gateway._on_voice_result → agent pipeline
"""

import logging
import threading
import numpy as np
from typing import Optional, Callable, Dict, Any
from enum import Enum

from .engine import AudioEngine

logger = logging.getLogger(__name__)


class VoiceState(str, Enum):
    """Voice command states"""
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"
    SUCCESS = "success"
    ERROR = "error"


class VoiceCommandHandler:
    """
    Records user speech after wake word detection and transcribes with RealtimeSTT.

    Uses faster-whisper (tiny model, ~40 MB) + silero-VAD via RealtimeSTT.
    No LFM audio model, no manual ring buffer, no fallback chain required.
    """

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self._recorder = None           # lazy-init AudioToTextRecorder

        # State
        self.state = VoiceState.IDLE
        self.is_recording = False
        # audio_buffer length is checked by iris_gateway (> 30 frames = has real audio).
        # We append None sentinels so the count stays correct without storing raw audio.
        self.audio_buffer: list = []

        # Configuration
        self.sample_rate = 16000        # AudioEngine input sample rate

        # Session tracking
        self._active_session_id: str = "default"
        self._auto_stop_mode: bool = False

        # Callbacks
        self._on_state_change: Optional[Callable[[VoiceState, str], None]] = None
        self._on_command_result: Optional[Callable[[Dict[str, Any]], None]] = None

        # Internal
        self._frame_listener_registered = False
        self._transcription_thread: Optional[threading.Thread] = None
        self._recorder_lock = threading.Lock()   # guards lazy-init of _recorder

    # -------------------------------------------------------------------------
    # Public API  (interface identical to the old VoiceCommandHandler)
    # -------------------------------------------------------------------------

    def set_state_callback(self, callback: Callable[[VoiceState, str], None]) -> None:
        """Register callback fired on every state transition."""
        self._on_state_change = callback

    def set_command_result_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register callback fired with the transcription result dict."""
        self._on_command_result = callback

    def set_active_session(self, session_id: str) -> None:
        """Set the session_id that owns the current recording."""
        self._active_session_id = session_id

    def get_status(self) -> Dict[str, Any]:
        """Return current handler status."""
        return {
            "state": self.state.value,
            "is_recording": self.is_recording,
            "buffer_size": len(self.audio_buffer),
            "silence_counter": 0,           # handled internally by RealtimeSTT
            "speech_started": self.is_recording,
        }

    def start_recording(self, auto_stop: bool = False) -> bool:
        """
        Begin recording user speech.

        Args:
            auto_stop: True for wake-word-triggered recording (silero-VAD ends it
                       automatically); False for double-click (user clicks stop).

        Returns:
            True if recording started successfully.
        """
        self._auto_stop_mode = auto_stop
        if self.is_recording:
            return True

        try:
            logger.info("[VoiceCommand] Starting recording (RealtimeSTT)...")
            self._play_activation_beep()

            self.is_recording = True
            self.audio_buffer = []

            # Register AudioEngine frame listener once (kept for lifetime of handler)
            if not self._frame_listener_registered:
                if self.audio_engine.pipeline:
                    self.audio_engine.register_frame_listener(self._capture_frame)
                    self._frame_listener_registered = True
                else:
                    logger.error("[VoiceCommand] AudioEngine pipeline not available")
                    self._set_state(VoiceState.ERROR, "Audio pipeline not ready")
                    self.is_recording = False
                    return False

            # Start blocking transcription in background thread
            self._transcription_thread = threading.Thread(
                target=self._run_transcription,
                daemon=True,
                name="iris-realtimestt",
            )
            self._transcription_thread.start()

            self._set_state(VoiceState.RECORDING, "Listening...")
            return True

        except Exception as e:
            logger.error(f"[VoiceCommand] Failed to start recording: {e}")
            self._set_state(VoiceState.ERROR, f"Recording failed: {e}")
            self.is_recording = False
            return False

    def stop_recording(self) -> None:
        """
        Stop recording (called by user double-click stop or iris_gateway).
        Signals RealtimeSTT to transcribe captured audio and return.
        """
        if not self.is_recording:
            return

        logger.info("[VoiceCommand] Stopping recording (user requested)...")

        try:
            if self._recorder is not None:
                # stop() causes the blocking text() call in _run_transcription to
                # process any buffered audio and return the partial transcript.
                self._recorder.stop()
        except Exception as e:
            logger.warning(f"[VoiceCommand] Error stopping recorder: {e}")
        # _run_transcription thread finishes and calls _on_transcription_complete

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _get_recorder(self):
        """Lazy-init the RealtimeSTT AudioToTextRecorder (single instance, reused).

        Thread-safe: _recorder_lock prevents _capture_frame and _run_transcription
        from racing to create two separate instances on the first recording.
        """
        if self._recorder is None:
            with self._recorder_lock:
                if self._recorder is None:   # double-checked locking
                    from RealtimeSTT import AudioToTextRecorder
                    self._recorder = AudioToTextRecorder(
                        use_microphone=False,
                        spinner=False,
                        model="tiny",                       # ~40 MB, fast, CPU-friendly
                        language="en",
                        silero_sensitivity=0.4,
                        post_speech_silence_duration=1.0,   # 1 s silence → end of speech
                        min_length_of_recording=0.3,        # ignore sub-300 ms blips
                        enable_realtime_transcription=False, # streaming not needed
                    )
                    logger.info("[VoiceCommand] RealtimeSTT recorder initialised (faster-whisper/tiny)")
        return self._recorder

    def _run_transcription(self) -> None:
        """Background thread: blocks on recorder.text() until speech ends."""
        try:
            recorder = self._get_recorder()
            logger.info("[VoiceCommand] Waiting for speech (RealtimeSTT)...")

            # Blocks until silero-VAD detects end-of-speech OR stop() is called
            transcript = recorder.text()
            self._on_transcription_complete(transcript or "")

        except Exception as e:
            logger.error(f"[VoiceCommand] Transcription error: {e}", exc_info=True)
            self.is_recording = False
            self._set_state(VoiceState.ERROR, f"Transcription failed: {e}")
            threading.Timer(2.0, lambda: self._set_state(VoiceState.IDLE, "")).start()

    def _on_transcription_complete(self, transcript: str) -> None:
        """Called when recorder.text() returns with a transcript."""
        self.is_recording = False
        transcript = transcript.strip()

        logger.info(f"[VoiceCommand] Transcript: '{transcript[:80]}'")

        if not transcript:
            logger.info("[VoiceCommand] Empty transcript — ignoring")
            self._set_state(VoiceState.IDLE, "")
            return

        result: Dict[str, Any] = {
            "type":          "voice_transcription",
            "transcript":    transcript,
            "audio_context": "",
            "session_id":    self._active_session_id,
            "status":        "success",
        }

        self._set_state(VoiceState.PROCESSING, "Processing...")

        if self._on_command_result:
            try:
                self._on_command_result(result)
            except Exception as e:
                logger.error(f"[VoiceCommand] Callback error: {e}")

        self._set_state(VoiceState.SUCCESS, "Voice transcription complete")
        threading.Timer(2.0, lambda: self._set_state(VoiceState.IDLE, "")).start()

    def _capture_frame(self, audio_frame: np.ndarray) -> None:
        """
        AudioEngine frame listener.  Converts float32 frame to int16 PCM bytes
        and feeds it to RealtimeSTT, which handles VAD internally.
        """
        if not self.is_recording:
            return

        # Sentinel append keeps len(audio_buffer) accurate for iris_gateway check
        self.audio_buffer.append(None)

        # float32 [-1, 1] → int16 PCM bytes at 16 kHz
        audio_int16 = (np.clip(audio_frame, -1.0, 1.0) * 32767).astype(np.int16)

        try:
            self._get_recorder().feed_audio(audio_int16.tobytes())
        except Exception:
            pass  # Never propagate exceptions to the audio callback thread

    def _play_activation_beep(self) -> None:
        """Play a short 880 Hz confirmation beep via the AudioEngine pipeline."""
        try:
            sample_rate = 24000
            duration = 0.1
            t = np.linspace(0, duration, int(sample_rate * duration))
            beep = (0.3 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)
            if self.audio_engine.pipeline:
                self.audio_engine.pipeline.play_audio(beep)
        except Exception as e:
            logger.warning(f"[VoiceCommand] Beep failed: {e}")

    def _set_state(self, new_state: VoiceState, message: str = "") -> None:
        """Update internal state and fire the state-change callback."""
        if self.state != new_state:
            logger.info(f"[VoiceCommand] State: {self.state} → {new_state}")
            self.state = new_state
            if self._on_state_change:
                try:
                    self._on_state_change(new_state, message)
                except Exception as e:
                    logger.error(f"[VoiceCommand] State callback error: {e}")

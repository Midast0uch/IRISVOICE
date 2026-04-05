"""
AudioEngine - Singleton audio processing engine for IRIS
Manages voice pipeline, wake word detection (Porcupine), and audio I/O
"""
import asyncio
import logging
import threading
import time
from enum import Enum
from typing import Optional, Callable, Dict, Any
import numpy as np

logger = logging.getLogger(__name__)

from .pipeline import AudioPipeline
from backend.ws_manager import get_websocket_manager
from backend.voice.porcupine_detector import PorcupineWakeWordDetector


class VoiceState(str, Enum):
    """Voice processing states for native audio flow"""
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING_NATIVE_AUDIO = "processing_native_audio"
    PLAYING_NATIVE_AUDIO = "playing_native_audio"
    ERROR = "error"


class AudioEngine:
    """
    Singleton audio engine managing the audio pipeline:
    1. Wake word detection (Porcupine)
    2. Audio frame distribution to registered listeners
    3. TTS suppression (Porcupine paused while IRIS is speaking)
    4. Speech interrupt signalling for in-progress TTS cancellation
    """

    _instance: Optional['AudioEngine'] = None
    _initialized: bool = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if AudioEngine._initialized:
            return

        # Core components
        self.pipeline: Optional[AudioPipeline] = None

        # Porcupine wake word detector (initialized lazily via initialize_porcupine())
        self._porcupine: Optional[PorcupineWakeWordDetector] = None
        self._porcupine_initialized: bool = False
        self._on_wake_word_detected = None   # callback: (wake_word_name: str) -> None

        # State
        self._state = VoiceState.IDLE
        self._state_callbacks: list[Callable[[VoiceState], None]] = []
        self._is_running = False
        self._lock = threading.Lock()
        self._main_loop: Optional[asyncio.AbstractEventLoop] = None

        # TTS interrupt: set True to stop in-progress speech at the next sentence boundary
        self._speech_interrupted: bool = False

        # TTS active: Porcupine skips wake-word detection while IRIS is speaking to
        # (a) avoid false triggers from speaker audio bleeding into the mic, and
        # (b) reduce CPU load so TTS synthesis threads aren't starved.
        self._tts_active: bool = False

        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass  # No running loop

        self.config: Dict[str, Any] = {
            "input_device": None,
            "output_device": None,
            "input_sensitivity": 1.0,
            "noise_reduction": True,
            "echo_cancellation": True,
            "sample_rate": 16000,
            "frame_length": 512,
            "activation_sound": True,
            "native_audio_enabled": True,
            "native_audio_model": "./models",
        }

        AudioEngine._initialized = True

    @property
    def state(self) -> VoiceState:
        return self._state

    def on_state_change(self, callback: Callable[[VoiceState], None]):
        self._state_callbacks.append(callback)

    def register_frame_listener(self, callback: Callable[[np.ndarray], None]):
        if self.pipeline:
            self.pipeline.add_frame_listener(callback)

    def _set_state(self, new_state: VoiceState):
        if self.state != new_state:
            old_state = self.state
            self._state = new_state
            logger.info(f"[AudioEngine] State: {old_state} -> {new_state}")

            for callback in self._state_callbacks:
                try:
                    callback(new_state)
                except Exception as e:
                    logger.error(f"State callback error: {e}")

    def initialize_porcupine(self, wake_phrase: Optional[str] = None, sensitivity: Optional[float] = None) -> bool:
        """
        Initialize Porcupine wake word detector using the user's chosen wake phrase.
        Supports both built-in pvporcupine keywords and custom .ppn model files.
        wake_phrase/sensitivity default to WakeConfig settings (set via Voice > Wake Word in UI).
        Called lazily — NOT at startup (avoids delay on low-spec PCs).
        """
        try:
            from backend.agent.wake_config import get_wake_config
            wake_config = get_wake_config()

            # Read from user settings if not overridden
            if wake_phrase is None:
                wake_phrase = wake_config.get_wake_phrase()
            if sensitivity is None:
                sensitivity = wake_config.get_sensitivity()

            # Check if a custom .ppn model file has been selected
            custom_model_path = wake_config.get_custom_model_path()

            # Known pvporcupine built-in keyword names (lowercase)
            _BUILTIN_KEYWORDS = {"jarvis", "computer", "bumblebee", "porcupine"}

            if custom_model_path:
                # Custom .ppn file (user-trained wake word, e.g. hey-iris_en_windows_v4_0_0.ppn)
                self._porcupine = PorcupineWakeWordDetector(
                    custom_model_path=custom_model_path,
                    sensitivities=[sensitivity]
                )
                logger.info(
                    f"[AudioEngine] Porcupine initialized — custom model '{wake_phrase}' "
                    f"({custom_model_path}) sensitivity={sensitivity:.2f}"
                )
            elif wake_phrase.lower().replace(" ", "_") in _BUILTIN_KEYWORDS or wake_phrase.lower() in _BUILTIN_KEYWORDS:
                # Built-in pvporcupine keyword (jarvis, computer, bumblebee, porcupine)
                keyword = wake_phrase.lower().replace(" ", "_")
                self._porcupine = PorcupineWakeWordDetector(
                    builtin_keywords=[keyword],
                    sensitivities=[sensitivity]
                )
                logger.info(
                    f"[AudioEngine] Porcupine initialized — builtin '{keyword}' sensitivity={sensitivity:.2f}"
                )
            else:
                # wake_phrase is not a built-in and custom_model_path is not set.
                # Try to auto-discover a matching .ppn file via WakeWordDiscovery.
                try:
                    from backend.voice.wake_word_discovery import WakeWordDiscovery
                    discovery = WakeWordDiscovery()
                    discovered = discovery.scan_directory()
                    match = next(
                        (f for f in discovered if f.display_name.lower() == wake_phrase.lower()),
                        None
                    )
                except Exception as disc_err:
                    logger.warning(f"[AudioEngine] WakeWordDiscovery lookup failed: {disc_err}")
                    match = None

                if match:
                    # Found the .ppn file — use it and update WakeConfig so future inits are fast
                    wake_config.update_config(custom_model_path=match.path)
                    self._porcupine = PorcupineWakeWordDetector(
                        custom_model_path=match.path,
                        sensitivities=[sensitivity]
                    )
                    logger.info(
                        f"[AudioEngine] Porcupine initialized — auto-discovered custom model '{wake_phrase}' "
                        f"({match.path}) sensitivity={sensitivity:.2f}"
                    )
                else:
                    # Phrase not found as builtin or custom model — fall back to default to avoid a crash
                    fallback = wake_config.DEFAULT_WAKE_PHRASE  # "jarvis"
                    logger.warning(
                        f"[AudioEngine] Wake phrase '{wake_phrase}' is not a built-in keyword and no "
                        f"matching .ppn file was found. Falling back to '{fallback}'. "
                        f"Select a valid wake word in Voice settings and press Confirm."
                    )
                    wake_config.update_config(wake_phrase=fallback, custom_model_path=None)
                    self._porcupine = PorcupineWakeWordDetector(
                        builtin_keywords=[fallback],
                        sensitivities=[sensitivity]
                    )
                    logger.info(
                        f"[AudioEngine] Porcupine initialized — fallback builtin '{fallback}' sensitivity={sensitivity:.2f}"
                    )

            self._porcupine_initialized = True
            return True
        except Exception as e:
            logger.error(f"[AudioEngine] Porcupine init failed: {e}")
            self._porcupine_initialized = False
            return False

    def reinitialize_porcupine(self) -> bool:
        """
        Reinitialize Porcupine after user changes wake phrase in settings.
        Called by WakeConfig.on_change_callback — registered in main.py.
        """
        if self._porcupine:
            try:
                self._porcupine.cleanup()
            except Exception:
                pass
            self._porcupine = None
            self._porcupine_initialized = False
        return self.initialize_porcupine()   # reads fresh values from WakeConfig

    def set_wake_word_callback(self, callback) -> None:
        """Set callback fired when wake word is detected. callback(wake_word_name: str) -> None"""
        self._on_wake_word_detected = callback

    def set_tts_active(self, active: bool) -> None:
        """Mark TTS playback as active/inactive.

        While active, Porcupine wake-word processing is suppressed:
        - Prevents speaker output from bleeding into the mic and triggering false detections.
        - Reduces CPU load so the CosyVoice synthesis thread is not starved of frames.
        Call set_tts_active(True) before the first sentence plays and
        set_tts_active(False) once playback finishes.
        """
        self._tts_active = active

    def interrupt_speech(self) -> None:
        """Signal any in-progress TTS playback to stop at the next sentence boundary.

        Thread-safe — can be called from the wake-word callback thread or the
        WebSocket handler.  The flag is consumed (reset to False) by
        is_speech_interrupted(), so callers don't need to clear it manually.
        """
        self._speech_interrupted = True

    def is_speech_interrupted(self) -> bool:
        """Return True (and reset the flag) if interrupt_speech() was called since
        the last check.  Designed to be polled inside the TTS sentence loop."""
        if self._speech_interrupted:
            self._speech_interrupted = False
            return True
        return False

    def get_main_loop(self) -> Optional[asyncio.AbstractEventLoop]:
        """Return the main event loop stored during initialization."""
        return self._main_loop

    def initialize(self) -> bool:
        try:
            logger.info("[AudioEngine] Initializing...")

            # Auto-select input device if not explicitly configured.
            # Output device intentionally stays None (system default) unless the
            # user has explicitly chosen one — this ensures TTS goes to whatever
            # Windows has set as the default playback device (speakers/headphones).
            if self.config.get("input_device") is None:
                try:
                    devices = AudioPipeline.list_devices()
                    first_input = next((d for d in devices if d.get("input")), None)
                    if first_input:
                        self.config["input_device"] = first_input.get("index")
                        logger.info(f"[AudioEngine] Auto-selected input: {first_input['name']} (index {first_input['index']})")
                except Exception as device_err:
                    logger.error(f"[AudioEngine] Failed to auto-select input device: {device_err}")

            output_device = self.config.get("output_device")
            logger.info(f"[AudioEngine] Output device: {'system default' if output_device is None else output_device}")

            self.pipeline = AudioPipeline(
                input_device=self.config["input_device"],
                output_device=output_device,
                sample_rate=self.config["sample_rate"],
                frame_length=self.config["frame_length"]
            )

            logger.info("[AudioEngine] Initialization complete")
            return True

        except Exception as e:
            logger.error(f"[AudioEngine] Initialization failed: {e}")
            self._set_state(VoiceState.ERROR)
            return False

    def start(self) -> bool:
        """Start the audio pipeline"""
        if self._is_running:
            return True

        if not self.pipeline:
            if not self.initialize():
                return False

        try:
            logger.info("[AudioEngine] Starting audio pipeline...")
            self.pipeline.start(
                on_audio_frame=self._process_audio_frame
            )
            self._is_running = True
            self._set_state(VoiceState.IDLE)
            logger.info("[AudioEngine] Audio pipeline started")
            return True

        except Exception as e:
            logger.error(f"[AudioEngine] Failed to start: {e}")
            self._set_state(VoiceState.ERROR)
            return False

    def stop(self):
        """Stop the audio pipeline"""
        if self.pipeline:
            self.pipeline.stop()
        self._is_running = False
        self._set_state(VoiceState.IDLE)
        logger.info("[AudioEngine] Audio pipeline stopped")

    def _process_audio_frame(self, audio_frame: np.ndarray):
        """
        Process incoming audio frame.
        - Porcupine wake word detection (lightweight, <1ms per frame)
        - Notifies registered frame listeners (used by VoiceCommandHandler for buffering)
        No longer streams every frame to lfm_audio_manager.
        """
        try:
            # Wake word detection (only when Porcupine is initialized and TTS is not playing)
            if self._porcupine_initialized and self._porcupine and not self._tts_active:
                # Convert float32 [-1,1] → int16 PCM for Porcupine.
                # PERF: keep as numpy array — avoid .tolist() which allocates a Python
                # int object per sample (512 objects × 31 frames/sec = ~16k allocs/sec).
                # pvporcupine.process() accepts any sequence supporting the buffer protocol,
                # including numpy int16 arrays.
                pcm_int16 = (np.clip(audio_frame, -1.0, 1.0) * 32767).astype(np.int16)
                frame_len = self._porcupine.frame_length
                # Process in Porcupine-sized chunks (numpy slicing is O(1), zero-copy)
                for i in range(0, len(pcm_int16) - frame_len + 1, frame_len):
                    chunk = pcm_int16[i:i + frame_len]
                    detected, word = self._porcupine.process_frame(chunk)
                    if detected:
                        logger.info(f"[AudioEngine] Wake word detected: '{word}'")
                        if self._on_wake_word_detected:
                            self._on_wake_word_detected(word)

        except Exception as e:
            logger.error(f"[AudioEngine] Frame processing error: {e}")

    def _broadcast_threadsafe(self, message: dict):
        """
        Broadcast a WebSocket message from any thread safely.
        Uses the stored main event loop with call_soon_threadsafe.
        """
        ws_manager = get_websocket_manager()

        if self._main_loop and self._main_loop.is_running():
            self._main_loop.call_soon_threadsafe(
                self._main_loop.create_task,
                ws_manager.broadcast(message)
            )
        else:
            # _main_loop was not captured at startup (AudioEngine initialised
            # before the asyncio event loop started).  Skip the broadcast rather
            # than calling asyncio.get_event_loop() from a background thread,
            # which raises "There is no current event loop in thread '...'" on
            # Python 3.10+.
            logger.debug(f"[AudioEngine] (WS skip: no main loop ref) {message.get('type', 'unknown')}")

    def update_config(self, **kwargs):
        """Update engine configuration"""
        self.config.update(kwargs)

        # Reinitialize if running
        if self._is_running:
            self.stop()
            self.initialize()
            self.start()

    def cleanup(self):
        """Clean up resources"""
        try:
            print("[AudioEngine] Cleaning up...")
            self.stop()

            # Clean up Porcupine wake word detector
            if self._porcupine:
                try:
                    self._porcupine.cleanup()
                except Exception:
                    pass

            print("[AudioEngine] Cleanup complete")

        except Exception as e:
            print(f"[AudioEngine] Error during cleanup: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get current engine status"""
        return {
            "state":                 self._state.value,
            "is_running":            self._is_running,
            "config":                self.config,
            "porcupine_initialized": self._porcupine_initialized,
        }


def get_audio_engine() -> AudioEngine:
    """Get the singleton AudioEngine instance"""
    return AudioEngine()

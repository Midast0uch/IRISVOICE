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

    _instance: Optional["AudioEngine"] = None
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
        self._on_wake_word_detected = None  # callback: (wake_word_name: str) -> None

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

        # Energy-based barge-in state (used when _tts_active is True).
        # Counter of consecutive frames above BARGE_IN_ENERGY_THRESHOLD; reset
        # to 0 on any frame below threshold.  At ~31 Hz frame rate, 25 frames
        # ≈ 800 ms of sustained loud speech before barge-in fires.
        self._barge_in_frame_count: int = 0
        self._on_barge_in_detected: Optional[Callable[[], None]] = None
        # Arming delay — barge-in detection is suppressed for the first
        # BARGE_IN_ARM_DELAY seconds after TTS starts, preventing the mic
        # from picking up the start of IRIS's own speech and self-triggering.
        self._barge_in_arm_time: float = 0.0

        # Mirrors WakeConfig.wake_word_enabled — updated by reinitialize_porcupine().
        # Checked in the 31 Hz audio callback; kept as a plain bool to avoid a
        # dict lookup on every frame.
        self._wake_word_enabled: bool = True

        # Audio device hot-plug polling — daemon thread checks list_devices()
        # every 2s and broadcasts audio_devices_changed when indices change.
        self._device_poll_stop: Optional[threading.Event] = None
        self._device_poll_thread: Optional[threading.Thread] = None

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
            # Sound played when voice command activates.
            #   - "default" : built-in 880 Hz sine tone
            #   - "beep"    : alias for default
            #   - "off"     : no sound
            #   - "<path>"  : path to a WAV file (absolute or relative to repo root)
            "activation_sound": "liquid-bubble-3000.wav",
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

    def initialize_porcupine(
        self, wake_phrase: Optional[str] = None, sensitivity: Optional[float] = None
    ) -> bool:
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
                    custom_model_path=custom_model_path, sensitivities=[sensitivity]
                )
                logger.info(
                    f"[AudioEngine] Porcupine initialized — custom model '{wake_phrase}' "
                    f"({custom_model_path}) sensitivity={sensitivity:.2f}"
                )
            elif (
                wake_phrase.lower().replace(" ", "_") in _BUILTIN_KEYWORDS
                or wake_phrase.lower() in _BUILTIN_KEYWORDS
            ):
                # Built-in pvporcupine keyword (jarvis, computer, bumblebee, porcupine)
                keyword = wake_phrase.lower().replace(" ", "_")
                self._porcupine = PorcupineWakeWordDetector(
                    builtin_keywords=[keyword], sensitivities=[sensitivity]
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
                        (
                            f
                            for f in discovered
                            if f.display_name.lower() == wake_phrase.lower()
                        ),
                        None,
                    )
                except Exception as disc_err:
                    logger.warning(
                        f"[AudioEngine] WakeWordDiscovery lookup failed: {disc_err}"
                    )
                    match = None

                if match:
                    # Found the .ppn file — use it and update WakeConfig so future inits are fast
                    wake_config.update_config(custom_model_path=match.path)
                    self._porcupine = PorcupineWakeWordDetector(
                        custom_model_path=match.path, sensitivities=[sensitivity]
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
                    wake_config.update_config(
                        wake_phrase=fallback, custom_model_path=None
                    )
                    self._porcupine = PorcupineWakeWordDetector(
                        builtin_keywords=[fallback], sensitivities=[sensitivity]
                    )
                    logger.info(
                        f"[AudioEngine] Porcupine initialized — fallback builtin '{fallback}' sensitivity={sensitivity:.2f}"
                    )

            self._porcupine_initialized = True
            return True
        except ImportError as e:
            logger.error(
                f"[AudioEngine] Porcupine init failed — pvporcupine import error: {e}\n"
                f"Native DLLs may not be on PATH. Check:\n"
                f"  1. venv\\Lib\\site-packages\\pvporcupine\\lib\\windows\\amd64\\*.dll exists\n"
                f"  2. Visual C++ Redistributable is installed\n"
                f"  3. PYTHONPATH / working directory is correct",
                exc_info=True,
            )
            self._porcupine_initialized = False
            return False
        except Exception as e:
            logger.error(f"[AudioEngine] Porcupine init failed: {e}", exc_info=True)
            self._porcupine_initialized = False
            return False

    def reinitialize_porcupine(self) -> bool:
        """
        Reinitialize Porcupine after user changes wake phrase or enabled state.
        Called by WakeConfig.on_change_callback — registered in main.py.
        Reads wake_word_enabled from WakeConfig so toggling the widget switch
        actually stops/starts detection rather than just persisting the field.
        """
        try:
            from backend.agent.wake_config import get_wake_config

            enabled = get_wake_config().config.get("wake_word_enabled", True)
        except Exception:
            enabled = True
        self._wake_word_enabled = enabled

        if self._porcupine:
            try:
                self._porcupine.cleanup()
            except Exception:
                pass
            self._porcupine = None
            self._porcupine_initialized = False

        if not enabled:
            logger.info("[AudioEngine] Wake word disabled — Porcupine stopped")
            return True

        return (
            self.initialize_porcupine()
        )  # reads fresh phrase/sensitivity from WakeConfig

    def set_wake_word_callback(self, callback) -> None:
        """Set callback fired when wake word is detected. callback(wake_word_name: str) -> None"""
        self._on_wake_word_detected = callback

    def set_main_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Store a reference to the main asyncio event loop for cross-thread broadcasts."""
        self._main_loop = loop

    def set_tts_active(self, active: bool) -> None:
        """Mark TTS playback as active/inactive.

        While active, Porcupine wake-word processing is suppressed:
        - Prevents speaker output from bleeding into the mic and triggering false detections.
        - Reduces CPU load so the TTS synthesis thread is not starved of frames.
        Call set_tts_active(True) before the first sentence plays and
        set_tts_active(False) once playback finishes.

        Also propagates to the pipeline so STT buffering and frame-listener
        forwarding are blocked while TTS plays (half-duplex echo avoidance).
        Without this, headphone users hear static feedback because the mic
        captures IRIS's own TTS and feeds it back into STT.
        """
        self._tts_active = active
        if active:
            import time as _time
            self._barge_in_arm_time = _time.monotonic()
            self._barge_in_frame_count = 0
        if self.pipeline is not None:
            try:
                self.pipeline.set_tts_active(active)
            except Exception as exc:
                logger.warning(f"[AudioEngine] pipeline.set_tts_active failed: {exc}")

    def interrupt_speech(self) -> None:
        """Signal any in-progress TTS playback to stop immediately.

        Thread-safe — can be called from the wake-word callback thread or the
        WebSocket handler.  The flag is consumed (reset to False) by
        is_speech_interrupted(), so callers don't need to clear it manually.

        Also triggers pipeline.interrupt() for sub-5ms native audio cancellation.
        """
        self._speech_interrupted = True
        if self.pipeline:
            self.pipeline.interrupt()

    def is_speech_interrupted(self) -> bool:
        """Return True (and reset the flag) if interrupt_speech() was called since
        the last check.  Designed to be polled inside the TTS sentence loop."""
        if self._speech_interrupted:
            self._speech_interrupted = False
            return True
        return False

    # ── Energy-based barge-in ──────────────────────────────────────────────
    # Constants tuned for 512-frame chunks at 16 kHz (~31 Hz callback rate).
    BARGE_IN_ENERGY_THRESHOLD: float = 0.025    # RMS level to trigger barge-in (was 0.04 — lowered so normal speech over TTS triggers without screaming)
    BARGE_IN_CONSECUTIVE_FRAMES: int = 10       # ~320 ms sustained speech (was 15 for 480 ms)
    BARGE_IN_ARM_DELAY: float = 0.3             # seconds after TTS starts before barge-in is armed

    def _on_barge_in_energy(self, rms: float) -> None:
        """Called from PortAudio input thread ~31 Hz with frame RMS during TTS.

        Counts consecutive frames above BARGE_IN_ENERGY_THRESHOLD.  When the
        counter reaches BARGE_IN_CONSECUTIVE_FRAMES, fires the barge-in callback
        registered by the gateway to stop TTS and start a new recording.

        Barge-in is suppressed for BARGE_IN_ARM_DELAY seconds after TTS starts
        to prevent the mic from picking up IRIS's own speech and self-triggering.
        """
        # Suppress barge-in during the arm delay window
        import time as _time
        if _time.monotonic() - self._barge_in_arm_time < self.BARGE_IN_ARM_DELAY:
            return

        if rms >= self.BARGE_IN_ENERGY_THRESHOLD:
            self._barge_in_frame_count += 1
            if (
                self._barge_in_frame_count >= self.BARGE_IN_CONSECUTIVE_FRAMES
                and self._on_barge_in_detected is not None
            ):
                self._barge_in_frame_count = 0
                try:
                    self._on_barge_in_detected()
                except Exception as _b_exc:
                    logger.error(f"[AudioEngine] Barge-in callback error: {_b_exc}")
        else:
            self._barge_in_frame_count = 0

    def set_barge_in_detected_callback(
        self, callback: Optional[Callable[[], None]]
    ) -> None:
        """Register the barge-in callback (fires from PortAudio input thread).

        The gateway registers a callback that stops TTS, reopens the half-duplex
        gate, and starts a new recording.  Pass None to unregister.
        """
        self._on_barge_in_detected = callback

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
                    inputs = [d for d in devices if d.get("input")]
                    # Skip virtual/loopback devices that route system audio back to a mic
                    # — these cause audio feedback (TTS → loopback → wake word fires).
                    _LOOPBACK_KEYWORDS = (
                        "stereo mix",
                        "what u hear",
                        "cable output",
                        "voicemeeter output",
                        "voicemeeter aux",
                        "vb-audio",
                    )

                    def is_real_mic(d):
                        name = (d.get("name") or "").lower()
                        return not any(kw in name for kw in _LOOPBACK_KEYWORDS)

                    real_inputs = [d for d in inputs if is_real_mic(d)]
                    # Prefer real mics over virtual loopback
                    selected = real_inputs[0] if real_inputs else (inputs[0] if inputs else None)
                    if selected:
                        self.config["input_device"] = selected.get("index")
                        logger.info(
                            f"[AudioEngine] Auto-selected input: {selected['name']} (index {selected['index']})"
                            + (" [real mic]" if is_real_mic(selected) else " [WARNING: virtual/loopback device]")
                        )
                except Exception as device_err:
                    logger.error(
                        f"[AudioEngine] Failed to auto-select input device: {device_err}"
                    )

            output_device = self.config.get("output_device")
            # The UI config stores "Default" as a string, but sounddevice
            # expects None (system default) or an integer device ID.
            # The string "Default" makes PortAudio look for a device literally
            # named "Default" which doesn't exist — causing silent failures
            # on activation beep and STTPROC playback.
            if isinstance(output_device, str) and output_device.lower() in ("default", ""):
                output_device = None
            logger.info(
                f"[AudioEngine] Output device: {'system default' if output_device is None else output_device}"
            )

            self.pipeline = AudioPipeline(
                input_device=self.config["input_device"],
                output_device=output_device,
                sample_rate=self.config["sample_rate"],
                frame_length=self.config["frame_length"],
                echo_cancellation=self.config.get("echo_cancellation", True),
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
            self.pipeline.start(on_audio_frame=self._process_audio_frame)
            # Register barge-in energy callback — fires ~31Hz from PortAudio
            # input thread with RMS of frames captured during TTS playback.
            self.pipeline.set_barge_in_energy_callback(self._on_barge_in_energy)
            self._is_running = True
            self._set_state(VoiceState.IDLE)

            # Start device hot-plug polling — daemon thread checks list_devices()
            # every 2s and broadcasts when devices are plugged/unplugged.
            if self._device_poll_stop is not None:
                self._device_poll_stop.set()  # stop any previous poll thread
            self._device_poll_stop = threading.Event()
            self._device_poll_thread = threading.Thread(
                target=self._poll_device_changes, daemon=True, name="iris-device-poll"
            )
            self._device_poll_thread.start()

            logger.info("[AudioEngine] Audio pipeline started")
            return True

        except Exception as e:
            logger.error(f"[AudioEngine] Failed to start: {e}")
            self._set_state(VoiceState.ERROR)
            return False

    def stop(self):
        """Stop the audio pipeline"""
        if self._device_poll_stop is not None:
            self._device_poll_stop.set()
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
        """
        # One-time diagnostic: log every gate condition so we know WHY wake word
        # isn't triggering.  Fires once per 300 frames (~10s) per condition.
        if not hasattr(self, "_gate_diag_count"):
            self._gate_diag_count = 0
        self._gate_diag_count += 1
        _diag = self._gate_diag_count % 300 == 1

        try:
            if not self._wake_word_enabled:
                if _diag:
                    logger.info("[AudioEngine] ww-gate: wake_word_enabled=False")
                return
            if not self._porcupine_initialized:
                if _diag:
                    logger.warning(
                        "[AudioEngine] ww-gate: porcupine_initialized=False. "
                        "Wake word detection never started. Check PICOVOICE_ACCESS_KEY in .env.local."
                    )
                return
            if not self._porcupine:
                if _diag:
                    logger.warning(
                        "[AudioEngine] ww-gate: _porcupine is None. "
                        "initialize_porcupine() succeeded but detector object is missing."
                    )
                return
            if self._tts_active:
                return  # normal — TTS gate (too noisy to log even periodically)

            # Convert float32 [-1,1] → int16 PCM for Porcupine.
            # PERF: keep as numpy array — avoid .tolist() which allocates a Python
            # int object per sample (512 objects × 31 frames/sec = ~16k allocs/sec).
            # pvporcupine.process() accepts any sequence supporting the buffer protocol,
            # including numpy int16 arrays.
            pcm_int16 = (np.clip(audio_frame, -1.0, 1.0) * 32767).astype(np.int16)
            frame_len = self._porcupine.frame_length
            # Process in Porcupine-sized chunks (numpy slicing is O(1), zero-copy)
            for i in range(0, len(pcm_int16) - frame_len + 1, frame_len):
                chunk = pcm_int16[i : i + frame_len]
                detected, word = self._porcupine.process_frame(chunk)
                if detected:
                    logger.info(f"[AudioEngine] Wake word detected: '{word}'")
                    if self._on_wake_word_detected:
                        self._on_wake_word_detected(word)

        except Exception as e:
            logger.error(f"[AudioEngine] Frame processing error: {e}", exc_info=True)

    def _broadcast_threadsafe(self, message: dict):
        """
        Broadcast a WebSocket message from any thread safely.
        Uses the stored main event loop with call_soon_threadsafe.
        """
        ws_manager = get_websocket_manager()
        msg_type = message.get("type", "unknown")

        if self._main_loop and self._main_loop.is_running():
            self._main_loop.call_soon_threadsafe(
                self._main_loop.create_task, ws_manager.broadcast(message)
            )
            logger.info(
                f"[AudioEngine] Broadcast queued ({msg_type}) " +
                f"from bg thread to main loop"
            )
        else:
            logger.warning(
                f"[AudioEngine] Broadcast SKIPPED ({msg_type}) — " +
                f"_main_loop is {'None' if not self._main_loop else 'not running'}"
            )

    def _poll_device_changes(self) -> None:
        """Daemon thread — polls AudioPipeline.list_devices() every 2s.

        When the set of device indices changes (USB/BT plug/unplug),
        broadcasts audio_devices_changed to all connected clients.
        The frontend responds by re-fetching the full device list.
        """
        last_inputs: set = set()
        last_outputs: set = set()
        while not self._device_poll_stop.wait(2.0):
            try:
                devices = AudioPipeline.list_devices()
                inputs = {d["index"] for d in devices if d.get("input")}
                outputs = {d["index"] for d in devices if d.get("output")}
                if inputs != last_inputs or outputs != last_outputs:
                    last_inputs, last_outputs = inputs, outputs
                    logger.info(
                        f"[AudioEngine] Audio device change detected — "
                        f"inputs={len(inputs)} output={len(outputs)}"
                    )
                    self._broadcast_threadsafe({
                        "type": "audio_devices_changed",
                        "payload": {
                            "input_count": len(inputs),
                            "output_count": len(outputs),
                        },
                    })
            except Exception:
                pass  # PortAudio may be locked during stream restart — skip this poll

    def update_config(self, **kwargs):
        """Update engine configuration"""
        self.config.update(kwargs)

        # Reinitialize if running
        if self._is_running:
            self.stop()
            self.initialize()
            self.start()

    def remove_state_callback(self, callback: Callable) -> None:
        """Remove a previously registered state change callback."""
        try:
            self._state_callbacks.remove(callback)
        except ValueError:
            pass

    def cleanup(self):
        """Clean up resources"""
        try:
            print("[AudioEngine] Cleaning up...")
            self.stop()
            self._state_callbacks.clear()

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
            "state": self._state.value,
            "is_running": self._is_running,
            "config": self.config,
            "porcupine_initialized": self._porcupine_initialized,
        }


def get_audio_engine() -> AudioEngine:
    """Get the singleton AudioEngine instance.

    This MUST return the same instance every time. Previously this returned
    a new AudioEngine() on every call, which caused frame listeners to be
    registered on one engine while a different engine's input stream was
    actually running. Result: recordings captured 0-1 frames and VAD never
    detected speech.
    """
    global _audio_engine_singleton
    if _audio_engine_singleton is None:
        _audio_engine_singleton = AudioEngine()
    return _audio_engine_singleton


# Module-level singleton holder. Using a global avoids the pitfall where
# a function-local default would be re-evaluated on each call.
_audio_engine_singleton: Optional[AudioEngine] = None

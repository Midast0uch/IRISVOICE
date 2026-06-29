"""
Voice Command Handler — faster-whisper direct STT pipeline for IRIS.

Uses faster-whisper (tiny/int8, ~40 MB) directly instead of RealtimeSTT.
RealtimeSTT.AudioToTextRecorder.__init__ hangs indefinitely on this system
(blocks on audio device enumeration even with use_microphone=False).

Flow:
  1. iris_gateway calls start_recording(auto_stop=True)   ← wake word path
     or start_recording(auto_stop=False)                  ← double-click path
  2. AudioEngine frame listener (_capture_frame) accumulates float32 PCM frames
  3a. auto_stop=True:  energy-based VAD loop detects end-of-speech silently
  3b. auto_stop=False: stop_recording() is called by user or gateway
  4. Accumulated audio is passed to faster-whisper.transcribe()
  5. _on_command_result callback → iris_gateway._on_voice_result → agent pipeline
"""

import base64
import io
import logging
import threading
import time
import wave
import os

import numpy as np
import requests
from typing import Optional, Callable, Dict, Any, List
from enum import Enum

from .engine import AudioEngine
from .cadence_detector import CadenceDetector

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
    Records user speech after wake word detection and transcribes with faster-whisper.

    Uses WhisperModel('tiny', compute_type='int8') — ~40 MB, loads in ~1s on CPU,
    transcribes a 3s utterance in < 1s.  Simple energy-based VAD handles
    auto-stop (wake-word path) without external VAD dependencies.
    """

    # VAD tuning — adjustable per environment
    VAD_ENERGY_THRESHOLD: float = 0.004  # RMS level that counts as speech (was 0.008)
    VAD_MIN_SPEECH_SEC: float = 0.15  # ignore blips shorter than this (was 0.25)
    VAD_SILENCE_SEC: float = 1.0  # silence after speech → end of utterance (was 2.0)
    VAD_MAX_DURATION_SEC: float = 30.0  # hard cap on recording length
    VAD_POLL_INTERVAL_SEC: float = 0.015  # how often VAD loop checks for new frames

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self._whisper = None  # lazy-loaded WhisperModel
        self._whisper_lock = threading.Lock()

        # State
        self.state = VoiceState.IDLE
        self.is_recording = False
        self._recording_started_at = (
            0.0  # monotonic clock; used for duplicate-fire detection
        )
        # audio_buffer length checked by iris_gateway (> 30 frames = has real audio).
        # Sentinel Nones keep the count accurate without storing duplicates.
        self.audio_buffer: List = []
        self._raw_frames: List[np.ndarray] = []  # actual float32 PCM frames

        # Configuration
        self.sample_rate = 16000

        # Parakeet ASR service URL (None = use faster-whisper directly)
        self.parakeet_service_url: Optional[str] = "http://localhost:8765"

        # Session tracking
        self._active_session_id: str = "default"
        self._auto_stop_mode: bool = False
        self._pre_speech_timeout_sec: float = 0.0  # 0 = disabled

        # Stop signal (set by stop_recording / cancel_recording / VAD)
        self._stop_event = threading.Event()
        # Cancel event: set() by cancel_recording() so _run_transcription skips
        # Whisper entirely and returns IDLE immediately.  Using threading.Event
        # instead of a plain bool guarantees visibility across threads without
        # a lock (Event.set/is_set use an internal condition + lock internally).
        self._cancel_event = threading.Event()

        # Callbacks
        self._on_state_change: Optional[Callable[[VoiceState, str], None]] = None
        self._on_command_result: Optional[Callable[[Dict[str, Any]], None]] = None
        # Called with smoothed RMS level (0.0–1.0) every ~100 ms during recording.
        # Used by the gateway to broadcast audio_level WS events for orb animation.
        self._on_audio_level: Optional[Callable[[float], None]] = None
        # Called with (rms, cadence, phase) every ~100 ms during recording.
        # Used by the gateway to broadcast audio_envelope WS events for XurOrb.
        # phase is "listening" during STT, "speaking" during TTS, "idle" otherwise.
        self._on_audio_envelope: Optional[Callable[[float, float, str], None]] = None

        # Cadence detector — spectral flux for speech rhythm tracking
        self.cadence_detector = CadenceDetector(sample_rate=self.sample_rate)

        # Internal
        self._frame_listener_registered = False
        self._transcription_thread: Optional[threading.Thread] = None
        self._start_lock = (
            threading.Lock()
        )  # prevents concurrent start_recording() calls

        # Warm up the STT model immediately (background thread)
        self.warm_up()

    # -------------------------------------------------------------------------
    # Public API  (interface identical to the previous VoiceCommandHandler)
    # -------------------------------------------------------------------------

    def set_state_callback(self, callback: Callable[[VoiceState, str], None]) -> None:
        """Register callback fired on every state transition."""
        self._on_state_change = callback

    def set_command_result_callback(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Register callback fired with the transcription result dict."""
        self._on_command_result = callback

    def set_audio_level_callback(self, callback: Callable[[float], None]) -> None:
        """Register callback fired with smoothed RMS (0.0–1.0) every ~100 ms during recording."""
        self._on_audio_level = callback

    def set_audio_envelope_callback(
        self, callback: Callable[[float, float, str], None]
    ) -> None:
        """Register callback fired with (rms, cadence, phase) every ~100 ms during recording.

        phase is "listening" during STT recording. The gateway uses this to
        broadcast audio_envelope WS events for XurOrb's cadence breathing.
        """
        self._on_audio_envelope = callback

    def set_active_session(self, session_id: str) -> None:
        """Set the session_id that owns the current recording."""
        self._active_session_id = session_id

    def get_status(self) -> Dict[str, Any]:
        """Return current handler status."""
        return {
            "state": self.state.value,
            "is_recording": self.is_recording,
            "buffer_size": len(self.audio_buffer),
            "silence_counter": 0,
            "speech_started": self.is_recording,
        }

    def start_recording(
        self, auto_stop: bool = False, pre_speech_timeout_sec: float = 0.0
    ) -> bool:
        """
        Begin recording user speech.

        Args:
            auto_stop: True → energy-based VAD ends recording automatically (wake word path).
                       False → recording continues until stop_recording() is called (double-click).
            pre_speech_timeout_sec: In auto_stop mode, give up if speech doesn't start within
                                    this many seconds (0 = use VAD_MAX_DURATION_SEC).
                                    Used for conversation mode relisten passes.

        Returns:
            True if recording started successfully.
        """
        if not self._start_lock.acquire(blocking=False):
            logger.warning(
                "[VoiceCommand] start_recording() already in progress — ignoring duplicate call"
            )
            return False

        try:
            return self._start_recording_locked(auto_stop, pre_speech_timeout_sec)
        finally:
            self._start_lock.release()

    def _start_recording_locked(
        self, auto_stop: bool, pre_speech_timeout_sec: float
    ) -> bool:
        """Inner implementation of start_recording — called only when _start_lock is held."""
        self._auto_stop_mode = auto_stop
        self._pre_speech_timeout_sec = pre_speech_timeout_sec
        if self.is_recording:
            elapsed = time.monotonic() - self._recording_started_at
            if elapsed < 2.0:
                # Duplicate within 2s — return True so the caller doesn't
                # reset the orb to idle (the existing recording is still valid).
                logger.debug(
                    f"[VoiceCommand] Duplicate start ignored "
                    f"({elapsed:.1f}s since current recording started)"
                )
                return (
                    True  # recording IS in progress — this is a success, not a failure
                )
            # A new wake-word arrived well after the previous one started.
            # Cancel the existing take so the new one can start fresh.
            # Without this, the second "hey iris" is silently swallowed and the
            # orb stays frozen until the first recording times out.
            logger.info(
                "[VoiceCommand] New recording requested while already recording — cancelling previous take"
            )
            self.cancel_recording()
            # The transcription thread checks _stop_event every frame (32 ms).
            # Give it up to 500 ms to read its current frame, notice the event,
            # and set is_recording = False.  The old 60 ms value was too tight
            # and caused all subsequent voice commands to fail permanently
            # with "didn't stop in time".
            import time as _t

            for _ in range(50):  # up to 50 × 10 ms = 500 ms
                if not self.is_recording:
                    break
                _t.sleep(0.01)
            if self.is_recording:
                logger.warning(
                    "[VoiceCommand] Previous recording thread didn't stop in time after 500 ms — skipping new start"
                )
                return False

        try:
            logger.info("[VoiceCommand] Starting recording (faster-whisper)...")

            self.is_recording = True
            self._recording_started_at = time.monotonic()
            self.audio_buffer = []
            self._raw_frames = []
            self._cancel_event.clear()  # clear any stale cancel from the previous take
            self._stop_event.clear()

            # Register AudioEngine frame listener once (kept for lifetime of handler).
            # IMPORTANT: do NOT return early here.  The previous code returned True
            # immediately after first-time registration, which meant the FIRST voice
            # trigger registered the listener but never started the _run_transcription
            # thread — so no VAD/Whisper ever ran on the first activation, the orb
            # hung in RECORDING, and the next trigger raced against the dangling
            # recording ("opens and closes right after").  Now we register (if
            # needed) and fall through to start the transcription thread unconditionally.
            if not self._frame_listener_registered:
                if self.audio_engine.pipeline:
                    self.audio_engine.register_frame_listener(self._capture_frame)
                    self._frame_listener_registered = True
                else:
                    logger.error("[VoiceCommand] AudioEngine pipeline not available")
                    self._set_state(VoiceState.ERROR, "Audio pipeline not ready")
                    self.is_recording = False
                    return False

            # Play beep AFTER registering the listener but route it through
            # set_tts_active so the half-duplex gate in AudioPipeline._input_callback
            # drops the frames captured while the beep plays.  Otherwise the
            # just-opened mic captures the 880 Hz confirmation tone and you hear
            # static feedback at every voice trigger.
            threading.Thread(
                target=self._play_activation_beep, daemon=True, name="iris-beep"
            ).start()

            # Start transcription thread (handles VAD + whisper in background)
            self._transcription_thread = threading.Thread(
                target=self._run_transcription,
                daemon=True,
                name="iris-stt",
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
        Stop recording (called by user double-click stop or gateway timeout).
        Signals the transcription thread to process buffered audio and return.
        """
        if not self.is_recording:
            return
        logger.info("[VoiceCommand] Stopping recording (user requested)...")
        self._stop_event.set()

    def cancel_recording(self) -> None:
        """
        Cancel recording WITHOUT transcribing — used when the user explicitly
        clicks the orb to abort a wake-word recording or to restart.

        Sets _cancelled so _run_transcription skips Whisper entirely and
        immediately returns the handler to IDLE.  Safe to call even if no
        recording is in progress (no-op).
        """
        if not self.is_recording:
            return
        logger.info(
            "[VoiceCommand] Recording cancelled by user — skipping transcription"
        )
        self._cancel_event.set()
        self._stop_event.set()

    # -------------------------------------------------------------------------
    # Internal — whisper
    # -------------------------------------------------------------------------

    def _transcribe_with_fallback(self, audio_np) -> str:
        """
        Transcribe audio using a fallback STT chain when the native LFM audio
        model fails to load or is unavailable.

        Fallback chain (in order):
          1. faster_whisper — WhisperModel tiny/int8, ~40 MB, GPU optional
          2. speech_recognition — Google Web Speech API (requires internet)

        RAM guard: requires >= 4.0 GB available RAM before attempting LFM audio.
        Uses psutil to check available system memory before model load.

        Args:
            audio_np: float32 numpy array at self.sample_rate

        Returns:
            Transcript string (empty string on failure).
        """
        import psutil

        # RAM guard — require at least 4.0 GB free before attempting model load
        _avail_gb = psutil.virtual_memory().available / (1024**3)
        if _avail_gb < 4.0:
            logger.warning(
                f"[VoiceCommand] Fallback STT: only {_avail_gb:.1f} GB RAM available "
                "(need >= 4.0 GB) — skipping to speech_recognition fallback"
            )
        else:
            # Attempt 1: faster_whisper (reuse cached model, do not create a new one)
            try:
                _fw_model = self._get_whisper()
                segments, _ = _fw_model.transcribe(
                    audio_np, language="en", beam_size=1, vad_filter=True
                )
                transcript = " ".join(s.text.strip() for s in segments).strip()
                if transcript:
                    logger.info(
                        f"[VoiceCommand] Fallback (faster_whisper): '{transcript[:80]}'"
                    )
                    return transcript
            except Exception as _fw_exc:
                logger.warning(
                    f"[VoiceCommand] faster_whisper fallback failed: {_fw_exc}"
                )

        # Attempt 2: speech_recognition (Google Web Speech API — last resort)
        try:
            import speech_recognition as sr
            import io
            import wave

            recognizer = sr.Recognizer()
            # Convert float32 to PCM int16 bytes for speech_recognition
            # (np is imported at module level; do not re-import locally —
            #  doing so would shadow np at function scope and trigger
            #  UnboundLocalError for the earlier use at line ~390.)
            pcm_int16 = (audio_np * 32767).clip(-32768, 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(pcm_int16.tobytes())
            buf.seek(0)
            with sr.AudioFile(buf) as source:
                audio_data = recognizer.record(source)
            transcript = recognizer.recognize_google(audio_data)
            logger.info(
                f"[VoiceCommand] Fallback (speech_recognition): '{transcript[:80]}'"
            )
            return transcript
        except Exception as _sr_exc:
            logger.warning(
                f"[VoiceCommand] speech_recognition fallback failed: {_sr_exc}"
            )

        return ""

    def _get_whisper(self):
        """Lazy-load and cache the WhisperModel (thread-safe)."""
        if self._whisper is None:
            with self._whisper_lock:
                if self._whisper is None:
                    from faster_whisper import WhisperModel

                    logger.info(
                        "[VoiceCommand] Loading faster-whisper tiny/int8 on CPU..."
                    )
                    # Always use CPU for STT.  tiny/int8 transcribes a 3 s clip
                    # in ~80 ms on any modern CPU — no reason to occupy CUDA.
                    self._whisper = WhisperModel(
                        "tiny",
                        device="cpu",
                        compute_type="int8",
                        num_workers=1,  # single-threaded is fine for our latency target
                        cpu_threads=4,  # cap so we don't starve the F5-TTS thread
                    )
                    logger.info("[VoiceCommand] faster-whisper ready")
        return self._whisper

    def warm_up(self) -> None:
        """
        Pre-load the Whisper model and run one silent inference in a daemon
        thread so the FIRST real transcription has zero model-load latency.

        Call this once during backend startup (after AudioEngine initialises).
        Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._whisper is not None:
            return  # already loaded

        def _do_warm_up():
            try:
                model = self._get_whisper()
                # Run a silent 0.5 s array through the pipeline to trigger
                # any lazy ONNX/CTranslate2 kernel compilation.
                silence = np.zeros(int(self.sample_rate * 0.5), dtype=np.float32)
                list(model.transcribe(silence, language="en", beam_size=1)[0])
                logger.info(
                    "[VoiceCommand] Whisper warm-up complete — first transcription will be instant"
                )
            except Exception as exc:
                logger.warning(
                    f"[VoiceCommand] Whisper warm-up failed (non-fatal): {exc}"
                )

        threading.Thread(
            target=_do_warm_up, daemon=True, name="iris-stt-warmup"
        ).start()

    # ------------------------------------------------------------------ #
    # Parakeet ASR path (primary, fall back to faster-whisper on failure)
    # ------------------------------------------------------------------ #

    def _transcribe_via_parakeet_service(self, audio_np: np.ndarray) -> str:
        """
        Send ``audio_np`` (float32 PCM, self.sample_rate Hz, mono) to the
        Parakeet ASR service via HTTP POST ``/transcribe``.

        Returns the transcribed text on success, or empty string on any
        failure (connection error, timeout, bad response).  The caller
        falls through to faster-whisper when the return is empty.
        """
        if not self.parakeet_service_url:
            return ""

        url = f"{self.parakeet_service_url.rstrip('/')}/transcribe"

        try:
            # Convert float32 → 16-bit WAV bytes for the service
            pcm_int16 = (audio_np * 32767.0).clip(-32768, 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(self.sample_rate)
                wf.writeframes(pcm_int16.tobytes())
            wav_bytes = buf.getvalue()

            audio_b64 = base64.b64encode(wav_bytes).decode("ascii")

            resp = requests.post(
                url,
                json={
                    "audio_base64": audio_b64,
                    "encoding": "pcm_s16le",
                    "sample_rate": self.sample_rate,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data.get("text", "").strip()
            confidence = data.get("confidence", 0.0)

            if text:
                logger.info(
                    "[VoiceCommand] Parakeet ASR: '%s' (confidence=%.3f)",
                    text[:80], confidence,
                )
                return text

            logger.warning("[VoiceCommand] Parakeet ASR returned empty text")
        except requests.exceptions.ConnectionError:
            logger.info(
                "[VoiceCommand] Parakeet service not reachable at %s — "
                "falling back to faster-whisper",
                self.parakeet_service_url,
            )
        except requests.exceptions.Timeout:
            logger.warning("[VoiceCommand] Parakeet ASR timed out after 30 s")
        except requests.exceptions.HTTPError as exc:
            logger.warning("[VoiceCommand] Parakeet ASR HTTP error: %s", exc)
        except Exception as exc:
            logger.warning("[VoiceCommand] Parakeet ASR unexpected error: %s", exc)

        return ""

    def _run_transcription(self) -> None:
        """
        Background thread: waits for end-of-speech (VAD or manual stop),
        then transcribes with faster-whisper and fires the result callback.
        """
        try:
            logger.info("[VoiceCommand] Waiting for speech...")

            if self._auto_stop_mode:
                # Energy-based VAD: wait for speech onset, then wait for silence
                self._vad_wait_for_speech_then_silence()
            else:
                # Manual mode: wait until stop_recording() sets the event
                self._stop_event.wait()

            self.is_recording = False

            # Check for explicit user cancellation BEFORE running Whisper.
            # cancel_recording() sets _cancel_event when the user clicks the orb
            # to abort a wake-word recording (nothing said, or wants to redo).
            if self._cancel_event.is_set():
                self._cancel_event.clear()
                logger.info(
                    "[VoiceCommand] Recording cancelled — skipping transcription"
                )
                self._raw_frames = []
                self.audio_buffer = []
                self._on_transcription_complete("")
                return

            if not self._raw_frames:
                logger.info("[VoiceCommand] No audio captured — ignoring")
                self._on_transcription_complete("")
                return

            # Concatenate all captured frames into one float32 array
            audio_np = np.concatenate(self._raw_frames, axis=0).astype(np.float32)
            duration = len(audio_np) / self.sample_rate
            rms = float(np.sqrt(np.mean(audio_np ** 2)))
            peak = float(np.max(np.abs(audio_np)))
            logger.info(
                f"[VoiceCommand] Transcribing {duration:.1f}s of audio "
                f"(RMS={rms:.4f}, peak={peak:.4f})..."
            )
            if rms < 1e-4:
                logger.warning(
                    "[VoiceCommand] Audio RMS near zero — likely silence. "
                    "Check input device selection (TTS feedback loop?)"
                )

            self._set_state(VoiceState.PROCESSING, "Transcribing...")

            # ── Primary path: Parakeet ASR service (GPU, RTX 3070) ─────────
            transcript = self._transcribe_via_parakeet_service(audio_np)

            # ── Fallback path: faster-whisper (CPU, tiny int8) ─────────────
            if not transcript:
                whisper = self._get_whisper()
                segments, _ = whisper.transcribe(
                    audio_np,
                    language="en",
                    beam_size=1,  # 3× faster; negligible quality loss for conversational STT
                    best_of=1,  # deterministic, fastest path
                    condition_on_previous_text=False,  # prevents hallucination drift
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 300},
                )
                transcript = " ".join(s.text.strip() for s in segments).strip()
                logger.info(f"[VoiceCommand] Transcript: '{transcript[:100]}'")

            self._on_transcription_complete(transcript)

            # Explicit buffer release — free memory immediately after transcription
            self._raw_frames = []
            if hasattr(self, "audio_buffer"):
                self.audio_buffer = []

        except Exception as e:
            logger.error(f"[VoiceCommand] Transcription error: {e}", exc_info=True)
            self.is_recording = False
            logger.warning(f"[VoiceCommand] Failed to load native audio model: {e}")
            try:
                if self._raw_frames:
                    # np is imported at module level; do NOT re-import here
                    # (a local `import numpy as np` makes the name local
                    #  throughout the function, breaking the earlier read at
                    #  line 390 with UnboundLocalError).
                    audio_np = np.concatenate(self._raw_frames, axis=0).astype(
                        np.float32
                    )
                    transcript = self._transcribe_with_fallback(audio_np)
                    if transcript:
                        self._on_transcription_complete(transcript)
                        self._raw_frames = []
                        if hasattr(self, "audio_buffer"):
                            self.audio_buffer = []
                        return
            except Exception as _fb_exc:
                logger.error(
                    f"[VoiceCommand] _transcribe_with_fallback also failed: {_fb_exc}"
                )
            self._set_state(VoiceState.ERROR, f"Transcription failed: {e}")
            threading.Timer(2.0, lambda: self._set_state(VoiceState.IDLE, "")).start()

    def _vad_wait_for_speech_then_silence(self) -> None:
        """
        Simple energy-based VAD for auto_stop mode.

        State machine:
          PRE_SPEECH  → wait for audio above VAD_ENERGY_THRESHOLD
          IN_SPEECH   → wait for sustained silence (VAD_SILENCE_SEC) after speech
          DONE        → return (triggers transcription)

        If _pre_speech_timeout_sec > 0, gives up if speech onset doesn't
        arrive within that window — used by conversation-mode relisten passes.
        """
        frame_sec = 512 / self.sample_rate  # ≈ 0.032 s per frame at 16 kHz
        silence_needed = int(self.VAD_SILENCE_SEC / frame_sec)
        speech_needed = int(self.VAD_MIN_SPEECH_SEC / frame_sec)
        max_frames = int(self.VAD_MAX_DURATION_SEC / frame_sec)
        pre_speech_max_frames = (
            int(self._pre_speech_timeout_sec / frame_sec)
            if self._pre_speech_timeout_sec > 0
            else max_frames
        )

        silence_count = 0
        speech_count = 0
        speech_started = False
        last_processed = 0
        total_frames = 0
        pre_speech_frames = 0  # frames elapsed before first speech onset
        # Audio level: emit smoothed RMS every ~3 frames (~100 ms at 32 ms/frame)
        _level_accum = 0.0
        _level_frame_count = 0
        _LEVEL_EMIT_EVERY = 3
        # Cadence: reset spectral flux detector at recording start
        self.cadence_detector.reset()

        while total_frames < max_frames and not self._stop_event.is_set():
            current_len = len(self._raw_frames)
            if current_len == last_processed:
                # Block until the stop event fires OR the poll interval expires.
                # More CPU-efficient than time.sleep() — wakes immediately on cancel.
                self._stop_event.wait(timeout=self.VAD_POLL_INTERVAL_SEC)
                continue

            new_frames = self._raw_frames[last_processed:current_len]
            last_processed = current_len

            for frame in new_frames:
                total_frames += 1
                rms = float(np.sqrt(np.mean(np.square(frame))))

                # Accumulate for audio_level broadcast (~100 ms cadence)
                _level_accum += rms
                _level_frame_count += 1
                if _level_frame_count >= _LEVEL_EMIT_EVERY:
                    # Normalise: divide by 2× threshold so speech ≈ 0.5, loud ≈ 1.0
                    level = min(
                        1.0,
                        _level_accum
                        / _level_frame_count
                        / (self.VAD_ENERGY_THRESHOLD * 2),
                    )
                    # Legacy callback (old IrisOrb.tsx still listens for audio_level)
                    if self._on_audio_level:
                        try:
                            self._on_audio_level(level)
                        except Exception:
                            pass
                    # New consolidated callback (XurOrb listens for audio_envelope)
                    if self._on_audio_envelope:
                        try:
                            cadence = self.cadence_detector.process(frame)
                            self._on_audio_envelope(level, cadence, "listening")
                        except Exception:
                            pass
                    _level_accum = 0.0
                    _level_frame_count = 0

                if rms >= self.VAD_ENERGY_THRESHOLD:
                    speech_count += 1
                    silence_count = 0
                    if speech_count >= speech_needed:
                        speech_started = True
                else:
                    if speech_started:
                        silence_count += 1
                        if silence_count >= silence_needed:
                            logger.debug("[VoiceCommand] VAD: end-of-speech detected")
                            return  # silence after real speech → done
                    else:
                        # Background noise before speech — decay counter slowly
                        speech_count = max(0, speech_count - 1)
                        pre_speech_frames += 1
                        if pre_speech_frames >= pre_speech_max_frames:
                            logger.debug(
                                f"[VoiceCommand] VAD: pre-speech timeout "
                                f"({self._pre_speech_timeout_sec}s) — returning to idle"
                            )
                            return  # no speech onset in time → done (empty frames)

        logger.debug(
            f"[VoiceCommand] VAD: loop ended (frames={total_frames}, speech_started={speech_started})"
        )

    # -------------------------------------------------------------------------
    # Internal — audio capture
    # -------------------------------------------------------------------------

    def _capture_frame(self, audio_frame: np.ndarray) -> None:
        """
        AudioEngine frame listener — accumulates float32 PCM while recording.
        Called from the sounddevice callback thread; must never raise.
        """
        if not self.is_recording:
            return

        # Sentinel keeps audio_buffer length accurate for iris_gateway check (> 30 frames)
        self.audio_buffer.append(None)
        self._raw_frames.append(audio_frame.copy())

    # -------------------------------------------------------------------------
    # Internal — helpers
    # -------------------------------------------------------------------------

    def _on_transcription_complete(self, transcript: str) -> None:
        """Called when whisper returns a transcript."""
        transcript = transcript.strip()

        if not transcript:
            logger.info(
                "[VoiceCommand] Empty transcript — returning empty result to gateway"
            )
            self._set_state(VoiceState.IDLE, "")
            if self._on_command_result:
                self._on_command_result(
                    {
                        "type": "voice_transcription",
                        "transcript": "",
                        "audio_context": "",
                        "session_id": self._active_session_id,
                        "status": "success",
                    }
                )
            return

        result: Dict[str, Any] = {
            "type": "voice_transcription",
            "transcript": transcript,
            "audio_context": "",
            "session_id": self._active_session_id,
            "status": "success",
        }

        if self._on_command_result:
            try:
                self._on_command_result(result)
            except Exception as e:
                logger.error(f"[VoiceCommand] Callback error: {e}")

        self._set_state(VoiceState.SUCCESS, "Voice transcription complete")
        threading.Timer(2.0, lambda: self._set_state(VoiceState.IDLE, "")).start()

    def _play_activation_beep(self) -> None:
        """Play a short confirmation sound when voice command starts.

        Three modes (resolved once at call time):

          1. ``activation_sound`` set to a WAV file path  → play that file
          2. ``activation_sound`` set to "off" / "none"    → skip playback
          3. default                                         → 880 Hz sine tone

        Wraps playback in ``set_tts_active(True/False)`` so the half-duplex
        gate in ``AudioPipeline._input_callback`` drops the frames captured
        while the sound is audible.  Without this gate, the just-opened mic
        captures the activation sound and the user hears static feedback at
        every voice trigger.
        """
        sound = None
        sr = 24000
        try:
            cfg = getattr(self.audio_engine, "config", {}) or {}
            mode = (cfg.get("activation_sound") or "default").lower()

            if mode in ("off", "none", "false", "disable", "disabled"):
                # No activation sound at all — user explicitly disabled
                return

            if mode not in ("default", "beep"):
                # Treat as a file path
                path = mode
                if not os.path.isabs(path):
                    path = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        path,
                    )
                if os.path.isfile(path):
                    import soundfile as sf
                    sound, sr = sf.read(path, dtype="float32")
                    if sound.ndim > 1:
                        sound = sound.mean(axis=1)  # stereo → mono
                    logger.info(f"[VoiceCommand] Playing activation sound: {path}")
                else:
                    logger.warning(
                        f"[VoiceCommand] activation_sound={path!r} not found, "
                        "falling back to 880 Hz tone"
                    )

            if sound is None:
                # Default: 880 Hz sine tone for 80 ms
                sr = 24000
                duration = 0.08
                t = np.linspace(0, duration, int(sr * duration))
                sound = (0.25 * np.sin(2 * np.pi * 880 * t)).astype(np.float32)

            if self.audio_engine.pipeline:
                # Engage the half-duplex gate for the sound + a small tail so
                # the mic doesn't capture the trailing resonance.
                self.audio_engine.set_tts_active(True)
                try:
                    self.audio_engine.pipeline.play_audio(sound, sample_rate=sr)
                finally:
                    # 150 ms tail covers the 80 ms beep + output buffer drain.
                    # Custom sounds may be longer, so add a small buffer.
                    tail = max(0.15, len(sound) / sr + 0.1)
                    time.sleep(tail)
                    self.audio_engine.set_tts_active(False)
        except Exception as e:
            # Always release the gate even if playback raised — otherwise the
            # pipeline stays muted and the real recording captures nothing.
            try:
                self.audio_engine.set_tts_active(False)
            except Exception:
                pass
            logger.warning(f"[VoiceCommand] Activation sound failed: {e}")

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

"""
Voice Command Handler â€” faster-whisper direct STT pipeline for IRIS.

Uses faster-whisper (tiny/int8, ~40 MB) directly instead of RealtimeSTT.
RealtimeSTT.AudioToTextRecorder.__init__ hangs indefinitely on this system
(blocks on audio device enumeration even with use_microphone=False).

Flow:
  1. iris_gateway calls start_recording(auto_stop=True)   â† wake word path
     or start_recording(auto_stop=False)                  â† double-click path
  2. AudioEngine frame listener (_capture_frame) accumulates float32 PCM frames
  3a. auto_stop=True:  energy-based VAD loop detects end-of-speech silently
  3b. auto_stop=False: stop_recording() is called by user or gateway
  4. Accumulated audio is passed to faster-whisper.transcribe()
  5. _on_command_result callback â†’ iris_gateway._on_voice_result â†’ agent pipeline
"""

import io
import logging
import threading
import time
import wave
import os

import numpy as np
from typing import Optional, Callable, Dict, Any, List
from enum import Enum

from .engine import AudioEngine
from .cadence_detector import CadenceDetector

logger = logging.getLogger(__name__)


class ParakeetTranscriber:
    """In-process Parakeet GPU ASR transcriber.

    Lazy-loads ParakeetForTDT + AutoProcessor on first call.
    Model stays in GPU memory after first load (~1.2 GB VRAM on RTX 3070).
    Torch/transformers imports happen ONLY on first load â€” zero cost at
    module import time.  Thread-safe via _lock.

    Memory budget:
      - VRAM: ~1.2 GB (fp16 model on GPU)
      - RAM:  ~200 MB (torch + transformers runtime)
      - Per-request: ~0 extra (reuses loaded model + processor)
    """

    def __init__(self):
        self._model = None
        self._processor = None
        self._lock = threading.Lock()
        self._loaded = False
        self._load_error = None

    def _ensure_loaded(self) -> bool:
        """Lazy-load model on first call.  Returns True if ready."""
        if self._loaded:
            return True
        if self._load_error is not None:
            return False

        with self._lock:
            if self._loaded:
                return True
            try:
                logger.info("[Parakeet] Loading Parakeet TDT model (GPU fp16, device_map=cuda)...")
                import torch
                from transformers import AutoProcessor, ParakeetForTDT

                model_name = "nvidia/parakeet-tdt-0.6b-v3"
                # Offline-first: the model is large (~2.5GB) and is already in
                # the local HuggingFace cache (C:\Users\<user>\.cache\huggingface).
                # Loading with local_files_only=True skips the per-startup network
                # resolve-check against the Hub, so startup is instant and works
                # with no internet.  Fall back to a normal (network) load only if
                # the cache is missing (first-ever install / fresh machine).
                try:
                    self._processor = AutoProcessor.from_pretrained(
                        model_name, local_files_only=True
                    )
                    self._model = ParakeetForTDT.from_pretrained(
                        model_name,
                        torch_dtype=torch.float16,
                        device_map="cuda",
                        local_files_only=True,
                    )
                except (OSError, ValueError):
                    logger.warning(
                        "[Parakeet] Local cache miss — fetching %s from HuggingFace Hub",
                        model_name,
                    )
                    self._processor = AutoProcessor.from_pretrained(model_name)
                    self._model = ParakeetForTDT.from_pretrained(
                        model_name,
                        torch_dtype=torch.float16,
                        device_map="cuda",
                    )
                self._model.eval()

                # Free any residual CPU memory from processor init
                import gc as _gc
                _gc.collect()
                torch.cuda.empty_cache()
                self._loaded = True
                logger.info("[Parakeet] Model loaded successfully (GPU fp16, device_map=cuda)")
                return True
            except Exception as exc:
                self._load_error = exc
                logger.error(
                    "[Parakeet] Failed to load model: %s â€” "
                    "will fall back to faster-whisper",
                    exc,
                )
                return False

    def transcribe(self, audio_np: np.ndarray, sample_rate: int = 16000) -> str:
        """Transcribe float32 PCM audio via Parakeet GPU.

        Args:
            audio_np: float32 PCM audio, mono, at *sample_rate* Hz.
            sample_rate: Sample rate (default 16000).

        Returns:
            Transcribed text, or empty string on failure.
        """
        if not self._ensure_loaded():
            return ""

        try:
            import torch

            # Convert float32 â†’ int16 PCM for the processor
            pcm_int16 = (audio_np * 32767.0).clip(-32768, 32767).astype(np.int16)

            # Process audio
            inputs = self._processor(
                audio=pcm_int16,
                sampling_rate=sample_rate,
                return_tensors="pt",
            )

            # Move to GPU in model's dtype â€” device_map="cuda" loads the model in
            # fp16, so inputs must match.  The processor returns float32 tensors.
            _dtype = next(self._model.parameters()).dtype
            input_features = inputs.input_features.to(dtype=_dtype, device="cuda")
            attention_mask = (
                inputs.attention_mask.to(dtype=_dtype, device="cuda")
                if hasattr(inputs, "attention_mask")
                else None
            )

            # Inference â€” Parakeet TDT uses generate() not direct forward()
            with torch.no_grad():
                # TDT model expects generate() to handle the decoding properly
                # generate() returns ParakeetRNNTGenerateOutput with .sequences
                output = self._model.generate(
                    input_features=input_features,
                    attention_mask=attention_mask,
                    max_new_tokens=256,
                )
                generated_ids = output.sequences if hasattr(output, "sequences") else output

            # Decode using the processor's tokenizer
            if hasattr(self._processor, "tokenizer"):
                text = self._processor.tokenizer.decode(
                    generated_ids[0], skip_special_tokens=True
                ).strip()
            else:
                # Fallback to batch_decode if tokenizer not directly available
                text = self._processor.batch_decode(generated_ids)[0].strip()

            if text:
                logger.info("[Parakeet] GPU ASR: '%s'", text[:80])
                return text
            else:
                logger.warning("[Parakeet] GPU ASR returned empty text")
                return ""

        except Exception as exc:
            import traceback
            logger.error(
                "[Parakeet] GPU transcription failed: %s\n%s",
                exc,
                traceback.format_exc(),
            )
            return ""


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

    Uses WhisperModel('tiny', compute_type='int8') â€” ~40 MB, loads in ~1s on CPU,
    transcribes a 3s utterance in < 1s.  Simple energy-based VAD handles
    auto-stop (wake-word path) without external VAD dependencies.
    """

    # VAD tuning â€” adjustable per environment
    VAD_ENERGY_THRESHOLD: float = 0.006  # RMS level that counts as speech
    VAD_MIN_SPEECH_SEC: float = 0.3  # ignore blips shorter than this (plan Â§1.3.4)
    VAD_SILENCE_SEC: float = 0.7  # silence after speech â†’ end of utterance
    VAD_MAX_DURATION_SEC: float = 30.0  # hard cap on recording length
    VAD_POLL_INTERVAL_SEC: float = 0.015  # how often VAD loop checks for new frames

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self._whisper = None  # lazy-loaded WhisperModel
        self._whisper_lock = threading.Lock()
        self._parakeet = ParakeetTranscriber()  # in-process GPU ASR (lazy-loaded)

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

        # STT timing: populated by _transcribe_via_parakeet() / whisper fallback,
        # forwarded via the result dict to iris_gateway for real-time metric broadcast.
        self._last_stt_timing: Dict[str, float] = {}

        # Configuration
        self.sample_rate = 16000

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

        # Post-start flush: drops the first N frames captured after start_recording.
        # Used after barge-in to flush residual TTS echo from the mic pipeline.
        self._post_start_flush_frames: int = 0

        # Idle timer: fires 2s after SUCCESS to transition to IDLE.
        # Stored so it can be cancelled if a new recording (barge-in) starts first.
        self._idle_timer: Optional[threading.Timer] = None

        # Callbacks
        self._on_state_change: Optional[Callable[[VoiceState, str], None]] = None
        self._on_command_result: Optional[Callable[[Dict[str, Any]], None]] = None
        # Called with smoothed RMS level (0.0â€“1.0) every ~100 ms during recording.
        # Used by the gateway to broadcast audio_level WS events for orb animation.
        self._on_audio_level: Optional[Callable[[float], None]] = None
        # Called with (rms, cadence, phase) every ~100 ms during recording.
        # Used by the gateway to broadcast audio_envelope WS events for XurOrb.
        # phase is "listening" during STT, "speaking" during TTS, "idle" otherwise.
        self._on_audio_envelope: Optional[Callable[[float, float, str], None]] = None

        # Cadence detector â€” spectral flux for speech rhythm tracking
        self.cadence_detector = CadenceDetector(sample_rate=self.sample_rate)

        # Internal
        self._frame_listener_registered = False
        self._transcription_thread: Optional[threading.Thread] = None
        self._start_lock = (
            threading.Lock()
        )  # prevents concurrent start_recording() calls

        # Warm up the STT model immediately (background thread)
        self.warm_up()

        # Pre-warm Parakeet GPU model in background so first transcription is instant
        self._parakeet_warm_up()

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
        """Register callback fired with smoothed RMS (0.0â€“1.0) every ~100 ms during recording."""
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
        self, auto_stop: bool = False, pre_speech_timeout_sec: float = 0.0,
        play_beep: bool = True, flush_ms: int = 0,
    ) -> bool:
        """
        Begin recording user speech.

        Args:
            auto_stop: True â†’ energy-based VAD ends recording automatically (wake word path).
                       False â†’ recording continues until stop_recording() is called (double-click).
            pre_speech_timeout_sec: In auto_stop mode, give up if speech doesn't start within
                                    this many seconds (0 = use VAD_MAX_DURATION_SEC).
                                    Used for conversation mode relisten passes.
            play_beep: True â†’ play activation beep (default for fresh wake-word activations).
                       False â†’ skip beep (barge-in re-recordings, auto-relisten).

        Returns:
            True if recording started successfully.
        """
        if not self._start_lock.acquire(blocking=False):
            logger.warning(
                "[VoiceCommand] start_recording() already in progress â€” ignoring duplicate call"
            )
            return False

        try:
            return self._start_recording_locked(auto_stop, pre_speech_timeout_sec, play_beep, flush_ms)
        finally:
            self._start_lock.release()

    def _start_recording_locked(
        self, auto_stop: bool, pre_speech_timeout_sec: float, play_beep: bool = True, flush_ms: int = 0,
    ) -> bool:
        """Inner implementation of start_recording â€” called only when _start_lock is held."""
        self._auto_stop_mode = auto_stop
        self._pre_speech_timeout_sec = pre_speech_timeout_sec
        if self.is_recording:
            elapsed = time.monotonic() - self._recording_started_at
            # Duplicate within 2s â€” the previous start just landed, ignore.
            if elapsed < 2.0:
                logger.debug(
                    f"[VoiceCommand] Duplicate start within 2s â€” ignoring "
                    f"({elapsed:.1f}s into current recording)"
                )
                return True
            # Stale recording beyond 30s â€” force-reset and start fresh.
            # Don't cancel (loses audio) â€” just reset the flag and let the
            # old thread finish naturally while a new one starts.
            if elapsed > 30.0:
                logger.warning(
                    f"[VoiceCommand] Stale recording detected ({elapsed:.1f}s) â€” "
                    f"force-resetting is_recording"
                )
                self.is_recording = False
            else:
                # Recording between 2-30s â€” it's active and valid.
                # Return True so the caller doesn't reset the orb to idle,
                # but a new thread won't start (the existing VAD handles it).
                logger.debug(
                    f"[VoiceCommand] Active recording in progress "
                    f"({elapsed:.1f}s) â€” ignoring duplicate"
                )
                return True

        try:
            logger.info("[VoiceCommand] Starting recording (Parakeet primary, faster-whisper fallback)...")

            # Cancel any pending idle timer from a prior SUCCESS so it can't
            # force IDLE while this new recording is active.
            self._cancel_idle_timer()

            self.is_recording = True
            self._recording_started_at = time.monotonic()
            self.audio_buffer = []
            self._raw_frames = []
            # Post-start flush: drop first N frames captured after start.
            # This lets residual TTS echo from barge-in decay before VAD
            # starts speech detection.  Caller sets flush_ms > 0 for barge-in.
            _frame_chunk = 512  # capture frame size
            self._post_start_flush_frames = int(flush_ms * self.sample_rate / (_frame_chunk * 1000)) if flush_ms > 0 else 0
            self._cancel_event.clear()  # clear any stale cancel from the previous take
            self._stop_event.clear()

            # Register AudioEngine frame listener once (kept for lifetime of handler).
            # IMPORTANT: do NOT return early here.  The previous code returned True
            # immediately after first-time registration, which meant the FIRST voice
            # trigger registered the listener but never started the _run_transcription
            # thread â€” so no VAD/Whisper ever ran on the first activation, the orb
            # hung in RECORDING, and the next trigger raced against the dangling
            # recording ("opens and closes right after").  Now we register (if
            # needed) and fall through to start the transcription thread unconditionally.
            # Always re-register the frame listener â€” not guarded by the flag.
            # If the AudioEngine stream was cleaned up (e.g. after TTS playback),
            # _frame_listeners was cleared and our old reference is gone.
            # add_frame_listener is idempotent, so this is safe to call every time.
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
            #
            # Skip the beep during barge-in re-recordings (play_beep=False)
            # to avoid briefly blocking the audio output device while the
            # previous TTS is still winding down â€” this prevents the VAD from
            # stalling at 15/23 silence frames.
            if play_beep:
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
        Cancel recording WITHOUT transcribing â€” used when the user explicitly
        clicks the orb to abort a wake-word recording or to restart.

        Sets _cancelled so _run_transcription skips Whisper entirely and
        immediately returns the handler to IDLE.  Safe to call even if no
        recording is in progress (no-op).
        """
        if not self.is_recording:
            return
        logger.info(
            "[VoiceCommand] Recording cancelled by user â€” skipping transcription"
        )
        self._cancel_event.set()
        self._stop_event.set()

    # -------------------------------------------------------------------------
    # Internal â€” whisper
    # -------------------------------------------------------------------------

    def _transcribe_with_fallback(self, audio_np) -> str:
        """
        Transcribe audio using a fallback STT chain when the native LFM audio
        model fails to load or is unavailable.

        Fallback chain (in order):
          1. faster_whisper â€” WhisperModel tiny/int8, ~40 MB, GPU optional
          2. speech_recognition â€” Google Web Speech API (requires internet)

        RAM guard: requires >= 4.0 GB available RAM before attempting LFM audio.
        Uses psutil to check available system memory before model load.

        Args:
            audio_np: float32 numpy array at self.sample_rate

        Returns:
            Transcript string (empty string on failure).
        """
        import psutil

        # RAM guard â€” require at least 4.0 GB free before attempting model load
        _avail_gb = psutil.virtual_memory().available / (1024**3)
        if _avail_gb < 4.0:
            logger.warning(
                f"[VoiceCommand] Fallback STT: only {_avail_gb:.1f} GB RAM available "
                "(need >= 4.0 GB) â€” skipping to speech_recognition fallback"
            )
        else:
            # Attempt 1: faster_whisper (reuse cached model, do not create a new one)
            try:
                _fw_model = self._get_whisper()
                segments, _ = _fw_model.transcribe(
                    audio_np, language="en", beam_size=1, vad_filter=False
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

        # Attempt 2: speech_recognition (Google Web Speech API â€” last resort)
        try:
            import speech_recognition as sr
            import io
            import wave

            recognizer = sr.Recognizer()
            # Convert float32 to PCM int16 bytes for speech_recognition
            # (np is imported at module level; do not re-import locally â€”
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
                    # in ~80 ms on any modern CPU â€” no reason to occupy CUDA.
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
        Safe to call multiple times â€” subsequent calls are no-ops.
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
                    "[VoiceCommand] Whisper warm-up complete â€” first transcription will be instant"
                )
            except Exception as exc:
                logger.warning(
                    f"[VoiceCommand] Whisper warm-up failed (non-fatal): {exc}"
                )

        threading.Thread(
            target=_do_warm_up, daemon=True, name="iris-stt-warmup"
        ).start()

    def _parakeet_warm_up(self) -> None:
        """
        Pre-load the Parakeet GPU model in a background daemon thread so
        the FIRST transcription has zero model-load latency (~10-30s cold
        start avoided). During model load, the orb shows zero cadence
        feedback because _capture_frame returns early when is_recording=False.
        Pre-warming eliminates this dead window entirely.

        Safe to call multiple times â€” subsequent calls are no-ops because
        _ensure_loaded() returns True immediately if already loaded.
        """
        def _do_parakeet_warm():
            try:
                if self._parakeet._ensure_loaded():
                    logger.info(
                        "[VoiceCommand] Parakeet GPU pre-loaded â€” "
                        "first transcription will be instant"
                    )
                else:
                    logger.warning(
                        "[VoiceCommand] Parakeet pre-load failed â€” "
                        "will use whisper CPU fallback"
                    )
            except Exception as exc:
                logger.warning(
                    f"[VoiceCommand] Parakeet warm-up failed (non-fatal): {exc}"
                )

        threading.Thread(
            target=_do_parakeet_warm, daemon=True, name="iris-parakeet-warmup"
        ).start()

    # ------------------------------------------------------------------ #
    # Parakeet ASR path (primary, fall back to faster-whisper on failure)
    # ------------------------------------------------------------------ #

    def _transcribe_via_parakeet(self, audio_np: np.ndarray) -> str:
        """Transcribe audio using in-process Parakeet GPU ASR.

        Returns transcribed text on success, or empty string on failure.
        Logs explicitly which STT backend was used.

        Also records STT latency in self._last_stt_timing for the result
        callback to forward to iris_gateway for real-time metric broadcast.
        """
        import time as _stt_time
        _stt_start = _stt_time.monotonic()
        text = self._parakeet.transcribe(audio_np, self.sample_rate)
        _stt_end = _stt_time.monotonic()
        # Record timing for the result callback to pick up
        self._last_stt_timing = {
            "stt_start_monotonic": _stt_start,
            "stt_end_monotonic": _stt_end,
            "stt_latency_ms": (_stt_end - _stt_start) * 1000.0,
            "stt_backend": "parakeet",
            "stt_audio_seconds": len(audio_np) / self.sample_rate,
        }
        if text:
            logger.info(
                f"[STT] parakeet GPU â€” '{text[:80]}' "
                f"(latency: {self._last_stt_timing['stt_latency_ms']:.0f}ms)"
            )
        else:
            logger.warning("[STT] parakeet FAILED or unavailable â€” falling back to whisper")
            self._last_stt_timing["stt_backend"] = "parakeet_failed"
        return text

    def _run_transcription(self) -> None:
        """
        Background thread: waits for end-of-speech (VAD or manual stop),
        then transcribes with faster-whisper and fires the result callback.
        """
        # Watchdog: if this thread hangs for >60s, force-reset is_recording
        # so subsequent wake words aren't permanently blocked.
        _watchdog_fired = threading.Event()

        def _watchdog_reset():
            if not _watchdog_fired.is_set():
                _watchdog_fired.set()
                logger.error(
                    "[VoiceCommand] WATCHDOG: transcription thread hung for 60s â€” "
                    "force-resetting is_recording"
                )
                self.is_recording = False
                self._set_state(VoiceState.ERROR, "Transcription timed out")
                threading.Timer(2.0, lambda: self._set_state(VoiceState.IDLE, "")).start()

        _watchdog_timer = threading.Timer(60.0, _watchdog_reset)
        _watchdog_timer.daemon = True
        _watchdog_timer.start()

        try:
            logger.info("[VoiceCommand] Waiting for speech...")

            if self._auto_stop_mode:
                # Energy-based VAD: wait for speech onset, then wait for silence.
                # Returns True if real speech was detected, False if only silence.
                _speech_detected = self._vad_wait_for_speech_then_silence()
            else:
                # Manual mode: wait until stop_recording() sets the event
                self._stop_event.wait()
                _speech_detected = True  # manual mode always transcribes

            self.is_recording = False

            # Check for explicit user cancellation BEFORE running Whisper.
            # cancel_recording() sets _cancel_event when the user clicks the orb
            # to abort a wake-word recording (nothing said, or wants to redo).
            if self._cancel_event.is_set():
                self._cancel_event.clear()
                logger.info(
                    "[VoiceCommand] Recording cancelled â€” skipping transcription"
                )
                self._raw_frames = []
                self.audio_buffer = []
                self._on_transcription_complete("")
                return

            # â”€â”€ Guard: skip transcription when VAD found no speech â”€â”€â”€â”€â”€â”€
            # After barge-in or auto-relisten, the VAD may timeout without
            # ever detecting speech onset.  The buffer still contains
            # near-silence frames.  Sending this to Parakeet causes it to
            # hallucinate short filler words ("yeah", "okay", "hello") which
            # the agent treats as real user input â€” creating phantom
            # conversational turns.  Skip transcription entirely when no
            # speech was detected.
            if not _speech_detected:
                logger.info(
                    "[VoiceCommand] VAD detected no speech â€” "
                    "discarding buffer (avoid Parakeet hallucination)"
                )
                self._raw_frames = []
                self.audio_buffer = []
                self._on_transcription_complete("")
                return

            if not self._raw_frames:
                logger.info("[VoiceCommand] No audio captured â€” ignoring")
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
                    "[VoiceCommand] Audio RMS near zero â€” likely silence. "
                    "Skipping transcription to avoid Parakeet hallucination."
                )
                self._raw_frames = []
                self.audio_buffer = []
                self._on_transcription_complete("")
                return

            self._set_state(VoiceState.PROCESSING, "Transcribing...")

            # â”€â”€ Processing-phase orb breathing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # During transcription, is_recording=False so _capture_frame returns
            # early and the orb gets zero audio_envelope messages. Without this,
            # the orb appears dead during the 0.5-30s processing window (latency
            # varies: whisper ~80ms, Parakeet cold start ~10-30s). Emit a subtle
            # periodic pulse so the orb shows it's alive and working.
            _proc_pulse_stop = threading.Event()
            def _emit_proc_pulse():
                while not _proc_pulse_stop.is_set():
                    if hasattr(self, "_on_audio_envelope") and self._on_audio_envelope:
                        try:
                            self._on_audio_envelope(0.12, 0.06, "processing")
                        except Exception:
                            pass
                    _proc_pulse_stop.wait(0.12)
            _proc_pulse_thread = threading.Thread(
                target=_emit_proc_pulse, daemon=True, name="iris-proc-pulse"
            )
            _proc_pulse_thread.start()

            # â”€â”€ Primary path: Parakeet GPU ASR (in-process) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            transcript = self._transcribe_via_parakeet(audio_np)

            _proc_pulse_stop.set()  # stop the processing pulse

            # â”€â”€ Fallback path: faster-whisper (CPU, tiny int8) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if not transcript:
                logger.info("[STT] Attempting faster-whisper CPU fallback...")
                import time as _stt_time_w
                _w_start = _stt_time_w.monotonic()
                whisper = self._get_whisper()
                segments, _ = whisper.transcribe(
                    audio_np,
                    language="en",
                    beam_size=1,  # 3x faster; negligible quality loss for conversational STT
                    best_of=1,  # deterministic, fastest path
                    condition_on_previous_text=False,  # prevents hallucination drift
                    vad_filter=False,  # energy VAD already handled end-of-speech â€” whisper VAD strips too aggressively
                )
                transcript = " ".join(s.text.strip() for s in segments).strip()
                # Whisper VAD (if enabled) can strip already-trimmed audio to zero
                # segments for short utterances. Retry once with VAD explicitly off.
                if not transcript:
                    logger.warning("[STT] whisper returned empty â€” retrying without VAD filter")
                    segments, _ = whisper.transcribe(
                        audio_np,
                        language="en",
                        beam_size=1,
                        best_of=1,
                        condition_on_previous_text=False,
                        vad_filter=False,
                    )
                    transcript = " ".join(s.text.strip() for s in segments).strip()
                _w_end = _stt_time_w.monotonic()
                # Overwrite the parakeet timing with whisper timing
                self._last_stt_timing = {
                    "stt_start_monotonic": _w_start,
                    "stt_end_monotonic": _w_end,
                    "stt_latency_ms": (_w_end - _w_start) * 1000.0,
                    "stt_backend": "whisper",
                    "stt_audio_seconds": len(audio_np) / self.sample_rate,
                }
                if transcript:
                    logger.info(
                        f"[STT] whisper CPU â€” '{transcript[:80]}' "
                        f"(latency: {self._last_stt_timing['stt_latency_ms']:.0f}ms)"
                    )
                if transcript:
                    logger.info("[STT] whisper CPU â€” '%s'", transcript[:80])
                else:
                    logger.warning(
                        "[STT] whisper CPU returned empty text. "
                        "Check: (1) mic input level, (2) VAD_ENERGY_THRESHOLD "
                        f"(currently {self.VAD_ENERGY_THRESHOLD}), "
                        "(3) audio buffer has actual speech (not just silence)"
                    )

            self._on_transcription_complete(transcript)

            # Explicit buffer release â€” free memory immediately after transcription
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
        finally:
            # Cancel watchdog if thread completed normally
            _watchdog_timer.cancel()
            # Belt-and-suspenders: ensure is_recording is always reset
            # even if the thread is killed or a non-Exception is raised
            if self.is_recording:
                logger.warning(
                    "[VoiceCommand] finally: is_recording was still True â€” "
                    "resetting (thread may have been killed)"
                )
                self.is_recording = False

    def _vad_wait_for_speech_then_silence(self) -> bool:
        """
        Energy-based VAD with adaptive noise-floor calibration (plan Â§1.3).

        State machine:
          CALIBRATE  â†’ sample ~0.5s ambient audio, compute noise floor, set thresholds
          PRE_SPEECH  â†’ wait for audio above speech_threshold (noise_floor * 3.0)
          IN_SPEECH   â†’ wait for sustained silence (adaptive frames) below silence_threshold
          DONE        â†’ return True (triggers transcription)

        The fixed threshold (VAD_ENERGY_THRESHOLD) was the root cause of the
        intermittent "STT never starts" bug: too high in a quiet room (speech
        never detected) or too low in a noisy room (background noise triggers
        false speech). Calibrating from the actual ambient level makes detection
        robust to the environment. Hysteresis (speech_threshold > silence_threshold)
        prevents flicker at the boundary.

        If _pre_speech_timeout_sec > 0, gives up if speech onset doesn't arrive
        within that window â€” used by conversation-mode relisten passes.

        Returns:
            True if speech was actually detected and ended naturally.
            False if only silence was captured (timeout or max duration).
            Callers should skip transcription when False to avoid
            Parakeet hallucinating text from silence.
        """
        frame_sec = 512 / self.sample_rate  # â‰ˆ 0.032 s per frame at 16 kHz
        silence_needed = int(self.VAD_SILENCE_SEC / frame_sec)
        speech_needed = int(self.VAD_MIN_SPEECH_SEC / frame_sec)
        max_frames = int(self.VAD_MAX_DURATION_SEC / frame_sec)
        pre_speech_max_frames = (
            int(self._pre_speech_timeout_sec / frame_sec)
            if self._pre_speech_timeout_sec > 0
            else max_frames
        )

        # â”€â”€ Adaptive noise-floor calibration (plan Â§1.3.1) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Sample ~0.5s of ambient audio to set thresholds relative to the
        # actual room noise. Recalibrate once if speech hasn't started by 10s.
        calibration_frames = max(1, int(0.5 / frame_sec))
        noise_floor = self.VAD_ENERGY_THRESHOLD  # fallback if no frames yet
        _calibration_rms: list = []
        _recalibrated = False

        def _calibrate() -> tuple:
            """Return (speech_threshold, silence_threshold) from current noise floor."""
            floor = noise_floor if noise_floor > 0 else self.VAD_ENERGY_THRESHOLD
            # Hysteresis: speech onset needs 3Ã— floor, offset needs only 1.5Ã— floor.
            speech_th = max(floor * 3.0, self.VAD_ENERGY_THRESHOLD * 0.5)
            silence_th = max(floor * 1.5, self.VAD_ENERGY_THRESHOLD * 0.25)
            return speech_th, silence_th

        speech_threshold, silence_threshold = _calibrate()

        silence_count = 0
        speech_count = 0
        speech_started = False
        speech_frames_total = 0  # total speech frames â†’ drives adaptive silence
        last_processed = 0
        total_frames = 0
        pre_speech_frames = 0  # frames elapsed before first speech onset
        # Audio level: emit smoothed RMS every ~3 frames (~100 ms at 32 ms/frame)
        _level_accum = 0.0
        _level_frame_count = 0
        _LEVEL_EMIT_EVERY = 3
        # Cadence: reset spectral flux detector at recording start
        if hasattr(self, "cadence_detector"):
            self.cadence_detector.reset()

        logger.debug(
            f"[VAD] start: calibration_frames={calibration_frames}, "
            f"silence_needed={silence_needed}, speech_needed={speech_needed}, "
            f"max_frames={max_frames}, fallback_th={self.VAD_ENERGY_THRESHOLD}"
        )

        while total_frames < max_frames and not self._stop_event.is_set():
            current_len = len(self._raw_frames)
            if current_len == last_processed:
                # Block until the stop event fires OR the poll interval expires.
                # More CPU-efficient than time.sleep() â€” wakes immediately on cancel.
                self._stop_event.wait(timeout=self.VAD_POLL_INTERVAL_SEC)
                continue

            new_frames = self._raw_frames[last_processed:current_len]
            last_processed = current_len

            for frame in new_frames:
                total_frames += 1
                rms = float(np.sqrt(np.mean(np.square(frame))))

                # â”€â”€ Calibration phase: collect ambient RMS, no VAD yet â”€â”€
                if not speech_started and total_frames <= calibration_frames:
                    # Exclude beep/echo energy from the noise floor. The 880 Hz
                    # activation beep (and its room echo) can leak into the mic
                    # on the first wake after backend start; its RMS (~0.2+) is
                    # far above normal speech (<0.05), so a hard ceiling keeps it
                    # out of the calibration median. The half-duplex gate (set in
                    # _play_activation_beep) is the primary defence; this is the
                    # backstop so a single leaked frame can't poison calibration.
                    if rms < 0.1:
                        _calibration_rms.append(rms)
                    continue
                # Finalize calibration on the first frame after the window
                if not speech_started and total_frames == calibration_frames + 1:
                    if _calibration_rms:
                        # Median is robust to early speech blips during calibration
                        _sorted = sorted(_calibration_rms)
                        noise_floor = _sorted[len(_sorted) // 2]
                    speech_threshold, silence_threshold = _calibrate()
                    logger.info(
                        f"[VAD] calibrated noise_floor={noise_floor:.5f} "
                        f"speech_th={speech_threshold:.5f} silence_th={silence_threshold:.5f}"
                    )

                # Accumulate for audio_level broadcast (~100 ms cadence)
                _level_accum += rms
                _level_frame_count += 1
                if _level_frame_count >= _LEVEL_EMIT_EVERY:
                    # Normalise: divide by 2Ã— speech threshold so speech â‰ˆ 0.5
                    level = min(
                        1.0,
                        _level_accum / _level_frame_count / (speech_threshold * 2),
                    )
                    # Legacy callback (old IrisOrb.tsx still listens for audio_level)
                    if self._on_audio_level:
                        try:
                            self._on_audio_level(level)
                        except Exception:
                            pass
                    # New consolidated callback (XurOrb listens for audio_envelope)
                    if hasattr(self, "_on_audio_envelope") and self._on_audio_envelope and hasattr(self, "cadence_detector"):
                        try:
                            cadence = self.cadence_detector.process(frame)
                            # Blend spectral flux with a scaled RMS so even quiet
                            # speech produces visible orb movement. Pure spectral flux
                            # is near-zero at low input levels (RMS < 0.001), making
                            # the orb appear frozen. RMS gives a floor that keeps the
                            # orb breathing in sync with the user's voice level.
                            rms_scaled = min(1.0, rms / (speech_threshold * 0.5))
                            blended = max(cadence, rms_scaled * 0.6)
                            self._on_audio_envelope(level, blended, "listening")
                        except Exception:
                            pass
                    _level_accum = 0.0
                    _level_frame_count = 0

                # â”€â”€ Recalibrate once if speech hasn't started after 10s â”€â”€
                if (
                    not speech_started
                    and not _recalibrated
                    and total_frames >= int(10.0 / frame_sec)
                ):
                    recent = _calibration_rms[-calibration_frames:] if _calibration_rms else []
                    if recent:
                        _sorted = sorted(recent)
                        noise_floor = _sorted[len(_sorted) // 2]
                        speech_threshold, silence_threshold = _calibrate()
                        logger.info(
                            f"[VAD] recalibrated @10s: noise_floor={noise_floor:.5f} "
                            f"speech_th={speech_threshold:.5f}"
                        )
                    _recalibrated = True

                # â”€â”€ VAD state machine â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                if rms >= speech_threshold:
                    speech_count += 1
                    silence_count = 0
                    speech_frames_total += 1
                    if speech_count >= speech_needed and not speech_started:
                        speech_started = True
                        logger.info(
                            f"[VAD] speech started (RMS={rms:.4f}, "
                            f"speech_th={speech_threshold:.4f})"
                        )
                else:
                    if speech_started:
                        silence_count += 1
                        # Adaptive silence frames (plan Â§1.3.2): shorter for short
                        # utterances (snappier), longer for long ones (natural pauses).
                        adaptive_silence = silence_needed
                        speech_sec = speech_frames_total * frame_sec
                        if speech_sec < 2.0:
                            adaptive_silence = max(8, int(silence_needed * 0.5))
                        elif speech_sec > 5.0:
                            adaptive_silence = int(silence_needed * 1.5)
                        if silence_count % 5 == 0:
                            logger.info(
                                f"[VAD] silence {silence_count}/{adaptive_silence} "
                                f"(RMS={rms:.4f}, silence_th={silence_threshold:.4f})"
                            )
                        if silence_count >= adaptive_silence:
                            logger.info(
                                f"[VAD] end-of-speech detected "
                                f"(RMS={rms:.4f}, silence_frames={silence_count})"
                            )
                            return True  # silence after real speech â†’ done
                    else:
                        # Background noise before speech â€” decay counter slowly
                        speech_count = max(0, speech_count - 1)
                        pre_speech_frames += 1
                        if pre_speech_frames >= pre_speech_max_frames:
                            logger.info(
                                f"[VAD] pre-speech timeout "
                                f"({self._pre_speech_timeout_sec}s) â€” no speech detected, "
                                f"skipping transcription to avoid hallucination"
                            )
                            return False  # no speech onset â†’ skip transcription

        logger.debug(
            f"[VAD] loop ended (frames={total_frames}, speech_started={speech_started})"
        )
        return speech_started

    # -------------------------------------------------------------------------
    # Internal â€” audio capture
    # -------------------------------------------------------------------------

    def _capture_frame(self, audio_frame: np.ndarray) -> None:
        """
        AudioEngine frame listener â€” accumulates float32 PCM while recording.
        Called from the sounddevice callback thread; must never raise.
        """
        # DIAGNOSTIC: Throttled RMS log so we can verify the mic is actually
        # receiving audio. Logs every 30 frames (~1 s at 32 ms/frame) regardless
        # of recording state â€” if we never see this, the input stream is dead.
        if not hasattr(self, "_diag_frame_count"):
            self._diag_frame_count = 0
        self._diag_frame_count += 1
        if self._diag_frame_count % 30 == 1:
            try:
                _rms = float(np.sqrt(np.mean(np.square(audio_frame))))
                _peak = float(np.max(np.abs(audio_frame)))
                logger.info(
                    f"[DIAG][capture_frame] frame#{self._diag_frame_count} "
                    f"shape={audio_frame.shape} rms={_rms:.5f} peak={_peak:.5f} "
                    f"is_recording={self.is_recording} device_frames={len(self._raw_frames)}"
                )
            except Exception as _diag_exc:
                logger.warning(f"[DIAG][capture_frame] log error: {_diag_exc}")

        if not self.is_recording:
            return

        # Post-start flush: drop frames captured immediately after recording
        # starts.  Used after barge-in to flush residual TTS echo from the
        # mic pipeline before VAD begins speech detection.
        if self._post_start_flush_frames > 0:
            self._post_start_flush_frames -= 1
            return

        # Sentinel keeps audio_buffer length accurate for iris_gateway check (> 30 frames)
        self.audio_buffer.append(None)
        self._raw_frames.append(audio_frame.copy())

        # â”€â”€ Broadcast audio_envelope for orb breathing during STT â”€â”€â”€â”€â”€â”€
        # The VAD loop in _run_transcription also sends audio_envelope (every
        # 3 frames, ~96ms), but it's gated on the VAD loop iteration speed.
        # If the VAD loop is delayed (backend-specific processing overhead),
        # the orb stops breathing.  Broadcasting directly from _capture_frame
        # ensures the envelope fires as long as audio frames are being captured,
        # regardless of backend (Whisper or Parakeet).
        if not hasattr(self, "_capture_envelope_count"):
            self._capture_envelope_count = 0
        self._capture_envelope_count += 1
        if self._capture_envelope_count % 3 == 0:
            try:
                _rms = float(np.sqrt(np.mean(np.square(audio_frame))))
                _level = min(1.0, _rms / (self.VAD_ENERGY_THRESHOLD * 2))
                if hasattr(self, "_on_audio_envelope") and self._on_audio_envelope and hasattr(self, "cadence_detector"):
                    _cadence = self.cadence_detector.process(audio_frame)
                    self._on_audio_envelope(_level, _cadence, "listening")
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Internal â€” helpers
    # -------------------------------------------------------------------------

    def _on_transcription_complete(self, transcript: str) -> None:
        """Called when whisper returns a transcript."""
        transcript = transcript.strip()

        if not transcript:
            logger.warning(
                "[VoiceCommand] Empty transcript dispatched to gateway â€” "
                "agent will NOT be called (gateway skips empty transcripts). "
                f"Buffer had {len(self._raw_frames)} frames. "
                f"Check: (1) mic input level (VAD_ENERGY_THRESHOLD={self.VAD_ENERGY_THRESHOLD}), "
                "(2) whisper vad_filter stripped speech, (3) audio buffer contains actual speech."
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
            "stt_timing": dict(self._last_stt_timing),  # STT latency for metric broadcast
        }

        if self._on_command_result:
            try:
                self._on_command_result(result)
            except Exception as e:
                logger.error(f"[VoiceCommand] Callback error: {e}")

        self._set_state(VoiceState.SUCCESS, "Voice transcription complete")
        # Cancel any previous idle timer (from an earlier transcription) so a
        # stale timer doesn't force IDLE while a new recording is active.
        self._cancel_idle_timer()
        self._idle_timer = threading.Timer(2.0, self._fire_idle_if_not_recording)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _play_activation_beep(self) -> None:
        """Play a short confirmation sound when voice command starts.

        Three modes (resolved once at call time):

          1. ``activation_sound`` set to a WAV file path  â†’ play that file
          2. ``activation_sound`` set to "off" / "none"    â†’ skip playback
          3. default                                         â†’ 880 Hz sine tone

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
                # No activation sound at all â€” user explicitly disabled
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
                        sound = sound.mean(axis=1)  # stereo â†’ mono
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
                # Play activation sound DIRECTLY via sounddevice, bypassing
                # the native C++ audio pipeline entirely.
                #
                # The native player has two problems:
                #   1) It normalizes audio to 0.85 peak, making quiet files
                #      sound harsh and staticky
                #   2) The PortAudio buffer/stream setup for Headphones (WG1)
                #      causes wait_done() to block for 30-40 seconds for a
                #      1-second WAV, which delays the entire voice pipeline
                #
                # Using sd.play() directly preserves the original file's
                # dynamics and completes in real-time.
                import sounddevice as _sd
                # Resolve output device: the config may store "Default" as a
                # string, but sounddevice needs None (system default) or int.
                _dev = self.audio_engine.pipeline.output_device
                if isinstance(_dev, str) and _dev.lower() in ("default", ""):
                    _dev = None
                try:
                    _sd.play(sound, sr, device=_dev, blocking=True)
                except Exception as _beep_err:
                    # Fallback: play through pipeline's fallback path
                    logger.warning(f"[VoiceCommand] Direct sd.play failed ({_beep_err}), using pipeline")
                    self.audio_engine.pipeline.play_audio(sound, sample_rate=sr)
                finally:
                    # ALWAYS release the half-duplex gate after playback,
                    # whether it succeeded or fell back.  If skipped on the
                    # happy path, _tts_active stays True and _input_callback
                    # drops every frame forever — STT captures nothing until
                    # the pipeline is closed/restarted (VAD never sees speech).
                    try:
                        self.audio_engine.set_tts_active(False)
                    except Exception:
                        pass
        except Exception as e:
            # Always release the gate even if playback raised â€” otherwise the
            # pipeline stays muted and the real recording captures nothing.
            try:
                self.audio_engine.set_tts_active(False)
            except Exception:
                pass
            logger.warning(f"[VoiceCommand] Activation sound failed: {e}")

    def _set_state(self, new_state: VoiceState, message: str = "") -> None:
        """Update internal state and fire the state-change callback."""
        if self.state != new_state:
            logger.info(f"[VoiceCommand] State: {self.state} â†’ {new_state}")
            self.state = new_state
            if self._on_state_change:
                try:
                    self._on_state_change(new_state, message)
                except Exception as e:
                    logger.error(f"[VoiceCommand] State callback error: {e}")

    def _fire_idle_if_not_recording(self) -> None:
        """Timer callback: transition to IDLE only if no recording is active.

        Prevents an orphaned timer from a previous SUCCESS from forcing
        RECORDING â†’ IDLE when the user has already barge-in-started a new
        recording.
        """
        if not self.is_recording:
            self._set_state(VoiceState.IDLE, "")

    def _cancel_idle_timer(self) -> None:
        """Cancel any pending idle-transition timer from a prior transcription."""
        timer = getattr(self, "_idle_timer", None)
        if timer is not None:
            timer.cancel()
            self._idle_timer = None

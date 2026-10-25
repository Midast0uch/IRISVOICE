"""
Voice Command Handler — faster-whisper direct STT pipeline for IRIS.

Uses faster-whisper (tiny/int8, ~40 MB) directly instead of RealtimeSTT.
RealtimeSTT.AudioToTextRecorder.__init__ hangs indefinitely on this system
(blocks on audio device enumeration even with use_microphone=False).

Flow:
  1. iris_gateway calls start_recording(auto_stop=True)   ← wake word path
     or start_recording(auto_stop=False)                  ← double-click path
  2. AudioEngine frame listener (_capture_frame) accumulates float32 PCM frames
     AND feeds them live to the Phonon-2 stream (interim hypotheses, REQ-1)
  3a. auto_stop=True:  energy-based VAD loop detects end-of-speech silently
  3b. auto_stop=False: stop_recording() is called by user or gateway
  4. At end-of-speech the Phonon-2 stream final becomes the transcript;
     faster-whisper (tiny/int8 CPU) transcribes the captured buffer only as
     the FINAL-segment fallback (stream cold/dead/empty — REQ-1 AC1.2)
  5. _on_command_result callback → iris_gateway._on_voice_result → agent pipeline
"""

import io
import json
import logging
import queue
import sys
import threading
import time
import types
import wave
import os

import numpy as np
from typing import Optional, Callable, Dict, Any, List
from enum import Enum

from .engine import AudioEngine
from .cadence_detector import CadenceDetector

logger = logging.getLogger(__name__)

# ctranslate2 submodules used only for model CONVERSION (they import torch and
# transformers); never needed to run Whisper. See VoiceCommandHandler._get_whisper.
_CT2_CONVERSION_MODULES = ("ctranslate2.converters", "ctranslate2.specs")

# ── VAD pause-tolerance ramp (2026-10-07) ──────────────────────────────────
# MODULE level, not class level, on purpose. The VAD wait loop is a nested
# function, and the contract tests exercise it through a stand-in handler that
# binds only some of VoiceCommandHandler's methods and attributes. A constant
# read from `self` here raised AttributeError on the stand-in while passing on
# the real class — the exact stand-in trap in AGENTS.md. At module scope the
# stand-in resolves it through the module it already imports.
#
# Short commands stay snappy at the 0.8 s base; the tolerance grows with how
# long the speaker has been talking, because a mid-sentence thinking pause gets
# more likely the longer you go on. MAX_SCALE 2.25 is what makes the 1.8 s
# ceiling reachable from a 0.8 s base.
_VAD_RAMP_START_SEC: float = 1.5
_VAD_RAMP_SPAN_SEC: float = 2.5
_VAD_RAMP_MAX_SCALE: float = 2.25

# ── Wake confirm gate (2026-10-24) ─────────────────────────────────────────
# The wake head cannot tell "Hey Iris" from other speech (violawake_detector:
# a click, the owner's voice and near-silence all score ~0.59). Live
# 2026-10-24 it fired on TV speech 3 s after boot (peak 0.614 vs bar 0.555)
# and the recording it opened sent "Now, Miss, Miss, Miss, Miss, I'll just get
# Tommy not settled in..." to the agent as a task, with real tool runs, into
# memory.db. Nothing downstream asked whether the phrase was said.
#
# So a wake-opened recording now transcribes the clip that made the detector
# fire (AudioEngine.take_wake_clip, ~3 s before the fire) in parallel with the
# user's speech, and its transcript only reaches the agent when that clip
# holds the wake name. Fail-closed: no clip, no STT, or no verdict in time =
# reject. A missed wake costs a retry; a false wake costs a task and a memory.
#
# MEASURED 2026-10-24, whisper tiny/int8 + wake_phrase_heard on every clip in
# logs/wake_triggers/ (316 real fires): 12 accepted, all the owner saying the
# name ("Hey, Iris." / "Hey, Aris."); 0 of the ~304 TV/room fires accepted.
# 36 synthetic "Hey Iris" clips (2 SAPI voices x 3 rates x 6 phrasings): 34
# accepted; the 2 misses ran the name into the next word ("Hey, I resopened").
# Clip STT cost: median 517 ms, p90 1982 ms on a loaded CPU, in parallel with
# the user's speech.
_WAKE_CONFIRM_TIMEOUT_SEC: float = 20.0
_WAKE_NAME: str = "iris"
# Whisper spellings of the name. One edit from "iris" also passes ("aris").
_WAKE_NAME_FORMS = frozenset({"iris", "irish", "irises"})


def _edit_distance_le1(a: str, b: str) -> bool:
    """True when a and b differ by at most one insert, delete or substitute."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = j = 0
    edited = False
    while i < len(a) and j < len(b):
        if a[i] != b[j]:
            if edited:
                return False
            edited = True
            if len(a) == len(b):
                i += 1
            j += 1
            continue
        i += 1
        j += 1
    return True


def wake_phrase_heard(text: str) -> bool:
    """Does an STT transcript of the wake clip contain the wake name?"""
    words = "".join(c if c.isalpha() else " " for c in (text or "").lower()).split()
    return any(w in _WAKE_NAME_FORMS or _edit_distance_le1(w, _WAKE_NAME) for w in words)


_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


# ── STT engine retirement record (C2, specs/phonon2-d1-model-swap REQ-11) ──
# Parakeet (sherpa-onnx GPU ASR) was RETIRED 2026-10-08 and replaced by
# Phonon-2 live streaming on CPU (backend/audio/phonon2_stream.py). The
# ParakeetTranscriber class that lived here is deleted; the standalone
# :8765 service (backend/audio/parakeet_service.py) is retired with it.
# Nothing may fall back to Parakeet: a boot that finds IRIS_PARAKEET_*
# set must fail loudly (see _assert_single_stt_engine below), never
# silently resurrect the retired engine.
PARAKEET_RETIRED = True

# The Phonon-2 streaming client: lazy server spawn, interim hypotheses,
# final at VAD end-of-speech, whisper fallback for finals (REQ-1 AC1.1/1.2).
from .phonon2_stream import Phonon2StreamClient


def _assert_single_stt_engine() -> None:
    """C1/AC2.3: refuse a boot that asks for the retired Parakeet engine.

    Two ASR engines live at once is both a correctness and a VRAM hazard;
    an explicit IRIS_PARAKEET_* request means a stale config is trying to
    resurrect the retired engine. Fail loudly with the retirement flag
    named (AC11.3), never silently run both.
    """
    stale = [k for k in os.environ if k.startswith("IRIS_PARAKEET")]
    if stale:
        raise RuntimeError(
            f"Parakeet is RETIRED (PARAKEET_RETIRED=True, phonon2-d1-model-swap "
            f"Wave 1) but the environment still sets {stale}. Remove them; "
            f"Phonon-2 (IRIS_PHONON2_PORT) is the STT engine."
        )


_assert_single_stt_engine()

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
    VAD_ENERGY_THRESHOLD: float = 0.006  # RMS level that counts as speech
    VAD_MIN_SPEECH_SEC: float = 0.3  # ignore blips shorter than this (plan §1.3.4)
    VAD_SILENCE_SEC: float = 0.8  # 0.5 cut mid-sentence pauses (live 2026-09-04); 0.8 covers breaths
    # 2026-10-07: was 1.2, and the cap BINNED against `silence_needed * 1.5`
    # (25 frames x 1.5 = 37 frames = 1.18 s ≈ the 1.2 s cap), so every long
    # utterance topped out at 1.2 s and raising it could never take effect.
    # 1.8 is the ceiling the pause ramp below actually reaches.
    VAD_SILENCE_SEC_MAX: float = 1.8  # hard cap on adaptive silence (long utterances)
    VAD_MAX_DURATION_SEC: float = 30.0  # hard cap on recording length
    VAD_POLL_INTERVAL_SEC: float = 0.015  # how often VAD loop checks for new frames

    def __init__(self, audio_engine: AudioEngine):
        self.audio_engine = audio_engine
        self._whisper = None  # lazy-loaded WhisperModel
        self._whisper_lock = threading.Lock()
        self._whisper_loading = False  # True while a thread is importing faster_whisper
        # Phonon-2 live streaming STT (CPU, fermion server subprocess).
        # Replaces the retired ParakeetTranscriber (PARAKEET_RETIRED above).
        self._phonon2 = Phonon2StreamClient()

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

        # STT timing: populated by _finalize_via_phonon2() / whisper fallback,
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
        # Called with smoothed RMS level (0.0–1.0) every ~100 ms during recording.
        # Used by the gateway to broadcast audio_level WS events for orb animation.
        self._on_audio_level: Optional[Callable[[float], None]] = None
        # Called with (rms, cadence, phase) every ~100 ms during recording.
        # Used by the gateway to broadcast audio_envelope WS events for XurOrb.
        # phase is "listening" during STT, "speaking" during TTS, "idle" otherwise.
        self._on_audio_envelope: Optional[Callable[[float, float, str], None]] = None
        # Called with the CURRENT interim hypothesis every ~0.5 s while the
        # user speaks (Phonon-2 partials, REQ-1 AC1.1). The gateway broadcasts
        # it as a voice_interim WS event; the UI shows provisional text.
        self._on_stt_interim: Optional[Callable[[str], None]] = None

        # Cadence detector — spectral flux for speech rhythm tracking
        self.cadence_detector = CadenceDetector(sample_rate=self.sample_rate)

        # Internal
        self._frame_listener_registered = False
        self._transcription_thread: Optional[threading.Thread] = None
        self._start_lock = (
            threading.Lock()
        )  # prevents concurrent start_recording() calls

        # REQ-1 AC1.2 / REQ-6 AC6.1: NO eager warm-up at construction.
        # Previously this called self.warm_up() (pre-loading faster-whisper)
        # and the Parakeet warm-up (spawning the GPU subprocess), which
        # together added ~4.2 GB to the boot-time idle footprint. Both
        # engines now start lazily: faster-whisper via _get_whisper() on the
        # first utterance, and Phonon-2 via _phonon2_warm_up() which spawns
        # the fermion server in a background thread and lets faster-whisper
        # serve utterance 1 (REQ-1 AC1.2/AC1.5).

    # -------------------------------------------------------------------------
    # Public API  (interface identical to the previous VoiceCommandHandler)
    # -------------------------------------------------------------------------

    def set_state_callback(self, callback: Callable[[VoiceState, str], None]) -> None:
        """Register callback fired on every state transition."""
        self._on_state_change = callback

    def set_command_result_callback(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        """Register callback fired when a voice command's transcript is ready."""
        self._on_command_result = callback

    def set_interim_callback(self, callback: Callable[[str], None]) -> None:
        """Register callback fired on every Phonon-2 interim hypothesis
        while the user speaks (REQ-1 AC1.1). The gateway wires this to the
        voice_interim WS broadcast."""
        self._on_stt_interim = callback

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
        self, auto_stop: bool = False, pre_speech_timeout_sec: float = 0.0,
        play_beep: bool = True, flush_ms: int = 0, wake_confirm: bool = False,
    ) -> bool:
        """
        Begin recording user speech.

        wake_confirm: True for a recording a wake-word fire opened. The
            transcript is dropped unless the wake clip holds the wake name
            (see _WAKE_CONFIRM_TIMEOUT_SEC above).

        Args:
            auto_stop: True → energy-based VAD ends recording automatically (wake word path).
                       False → recording continues until stop_recording() is called (double-click).
            pre_speech_timeout_sec: In auto_stop mode, give up if speech doesn't start within
                                    this many seconds (0 = use VAD_MAX_DURATION_SEC).
                                    Used for conversation mode relisten passes.
            play_beep: True → play activation beep (default for fresh wake-word activations).
                       False → skip beep (barge-in re-recordings, auto-relisten).

        Returns:
            True if recording started successfully.
        """
        if not self._start_lock.acquire(blocking=False):
            logger.warning(
                "[VoiceCommand] start_recording() already in progress — ignoring duplicate call"
            )
            return False

        try:
            return self._start_recording_locked(
                auto_stop, pre_speech_timeout_sec, play_beep, flush_ms, wake_confirm
            )
        finally:
            self._start_lock.release()

    def _start_recording_locked(
        self, auto_stop: bool, pre_speech_timeout_sec: float, play_beep: bool = True, flush_ms: int = 0,
        wake_confirm: bool = False,
    ) -> bool:
        """Inner implementation of start_recording — called only when _start_lock is held."""
        self._auto_stop_mode = auto_stop
        self._pre_speech_timeout_sec = pre_speech_timeout_sec
        if self.is_recording:
            elapsed = time.monotonic() - self._recording_started_at
            # Duplicate within 2s — the previous start just landed, ignore.
            if elapsed < 2.0:
                logger.debug(
                    f"[VoiceCommand] Duplicate start within 2s — ignoring "
                    f"({elapsed:.1f}s into current recording)"
                )
                return True
            # Stale recording beyond 30s — force-reset and start fresh.
            # Don't cancel (loses audio) — just reset the flag and let the
            # old thread finish naturally while a new one starts.
            if elapsed > 30.0:
                logger.warning(
                    f"[VoiceCommand] Stale recording detected ({elapsed:.1f}s) — "
                    f"force-resetting is_recording"
                )
                self.is_recording = False
            else:
                # Recording between 2-30s — it's active and valid.
                # Return True so the caller doesn't reset the orb to idle,
                # but a new thread won't start (the existing VAD handles it).
                logger.debug(
                    f"[VoiceCommand] Active recording in progress "
                    f"({elapsed:.1f}s) — ignoring duplicate"
                )
                return True

        try:
            logger.info("[VoiceCommand] Starting recording (Phonon-2 streaming primary, faster-whisper final fallback)...")

            # Cancel any pending idle timer from a prior SUCCESS so it can't
            # force IDLE while this new recording is active.
            self._cancel_idle_timer()

            self.is_recording = True
            self._recording_started_at = time.monotonic()
            self.audio_buffer = []
            self._raw_frames = []
            # Set on EVERY start: a relisten or double-click take carries no
            # verdict from an earlier wake.
            self._wake_verdict = self._begin_wake_confirm() if wake_confirm else None
            # Warm the Phonon-2 server on the FIRST wake word trigger (not at
            # end-of-speech): the fermion server cold boot (~64 s first run,
            # ~6 s warm) overlaps with VAD recording, so by the time VAD
            # detects end-of-speech the stream is usually live. No-op if the
            # server is already up or spawning.
            self._phonon2_warm_up()
            # Open the live stream for THIS utterance. False (server cold)
            # is fine: frames still accumulate in _raw_frames and the final
            # falls back to faster-whisper (REQ-1 AC1.2/AC1.5).
            self._phonon2.begin_utterance(self._on_stt_interim_text)
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
            # thread — so no VAD/Whisper ever ran on the first activation, the orb
            # hung in RECORDING, and the next trigger raced against the dangling
            # recording ("opens and closes right after").  Now we register (if
            # needed) and fall through to start the transcription thread unconditionally.
            # Always re-register the frame listener — not guarded by the flag.
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
            # previous TTS is still winding down — this prevents the VAD from
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
    # Internal — wake confirm gate
    # -------------------------------------------------------------------------

    def _begin_wake_confirm(self) -> Dict[str, Any]:
        """Start transcribing the wake clip on a daemon thread; return the verdict slot.

        Runs while the user speaks, so a warm whisper (~80 ms for 3 s) adds
        no latency. On a cold boot the final STT needs the same whisper load.
        """
        verdict: Dict[str, Any] = {"done": threading.Event(), "ok": False, "heard": ""}
        clip = None
        try:
            clip = self.audio_engine.take_wake_clip()
        except Exception as e:
            logger.warning(f"[WakeConfirm] take_wake_clip failed: {e}")

        def _confirm() -> None:
            try:
                if clip is None or len(clip) == 0:
                    verdict["heard"] = "<no wake clip>"
                    return
                whisper = self._get_whisper(timeout=_WAKE_CONFIRM_TIMEOUT_SEC)
                if whisper is None:
                    verdict["heard"] = "<whisper unavailable>"
                    return
                segments, _ = whisper.transcribe(
                    clip,
                    language="en",
                    beam_size=1,
                    best_of=1,
                    condition_on_previous_text=False,
                    vad_filter=False,
                )
                heard = " ".join(s.text.strip() for s in segments).strip()
                verdict["heard"] = heard
                verdict["ok"] = wake_phrase_heard(heard)
            except Exception as e:
                verdict["heard"] = f"<error: {e}>"
            finally:
                verdict["done"].set()

        threading.Thread(target=_confirm, daemon=True, name="iris-wake-confirm").start()
        return verdict

    def _wake_confirmed(self) -> bool:
        """True unless this take was wake-opened and the clip did not hold the name."""
        verdict = getattr(self, "_wake_verdict", None)
        if verdict is None:
            return True
        self._wake_verdict = None
        if not verdict["done"].wait(_WAKE_CONFIRM_TIMEOUT_SEC):
            logger.warning(
                f"[WakeConfirm] session={self._active_session_id} no verdict in "
                f"{_WAKE_CONFIRM_TIMEOUT_SEC:.0f}s — rejecting"
            )
            return False
        logger.info(
            f"[WakeConfirm] session={self._active_session_id} "
            f"{'CONFIRMED' if verdict['ok'] else 'REJECTED'} — clip heard {verdict['heard']!r}"
        )
        return bool(verdict["ok"])

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

        REQ-2 AC2.2: NO RAM gate. The old 4.0 GB free-RAM barrier aborted the
        faster-whisper CPU fallback during resource contention, forcing a
        network-dependent last resort and false VoiceState.ERROR. faster-whisper
        tiny/int8 is ~40 MB and runs on CPU; it is always attempted.

        Args:
            audio_np: float32 numpy array at self.sample_rate

        Returns:
            Transcript string (empty string on failure).
        """
        # Attempt 1: faster_whisper (reuse cached model, do not create a new one)
        try:
            _fw_model = self._get_whisper()
            if _fw_model is None:
                # Lock held by warm-up — skip whisper this turn rather than
                # block for minutes (see _get_whisper docstring).
                logger.warning(
                    "[VoiceCommand] faster_whisper unavailable (warm-up in "
                    "progress) — skipping to next fallback"
                )
                raise RuntimeError("whisper unavailable (warm-up)")
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

    def _get_whisper(self, timeout: float = 5.0):
        """Lazy-load and cache the WhisperModel (thread-safe).

        Uses a ``_whisper_loading`` flag rather than holding the lock across
        the slow import. The background warm-up thread sets the flag, then
        imports faster_whisper (~126s cold) WITHOUT holding the lock, so a
        live transcription thread is never blocked behind it. If a load is
        already in progress, this waits up to ``timeout`` for it to finish
        and returns the model, or None on timeout (caller skips whisper).
        """
        if self._whisper is not None:
            return self._whisper
        # Fast path: another thread is already loading — wait briefly.
        if self._whisper_loading:
            _deadline = time.monotonic() + timeout
            while time.monotonic() < _deadline:
                if self._whisper is not None:
                    return self._whisper
                time.sleep(0.1)
            logger.warning(
                "[VoiceCommand] _get_whisper: load in progress for >%.1fs — "
                "skipping whisper fallback this turn",
                timeout,
            )
            return None
        # Claim the loading flag (guarded by the lock so only one thread loads).
        with self._whisper_lock:
            if self._whisper is not None:
                return self._whisper
            if self._whisper_loading:
                # Lost the race — another thread just claimed it. Wait briefly.
                _deadline = time.monotonic() + timeout
                while time.monotonic() < _deadline:
                    if self._whisper is not None:
                        return self._whisper
                    time.sleep(0.1)
                return None
            self._whisper_loading = True
        # Load WITHOUT holding the lock — the import can take ~126s cold and
        # must not block a live transcription thread.
        try:
            # ctranslate2/__init__ imports its converters and specs, which try
            # `import torch` and `import transformers` - for model CONVERSION,
            # never used to run a converted model. Cold on this HDD that chain
            # ran ~19 min inside the backend (stack dumps 2026-10-03 11:04 ->
            # 11:23) and overlapped two live turns. Inference uses only the
            # compiled ctranslate2._ext, so empty submodules are registered
            # first (nothing else in IRIS imports ctranslate2). Measured in a
            # fresh process: torch False, transformers False, transcribe ok.
            if "ctranslate2" not in sys.modules:
                for _stub in _CT2_CONVERSION_MODULES:
                    sys.modules.setdefault(_stub, types.ModuleType(_stub))
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
        finally:
            self._whisper_loading = False
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

    def _phonon2_warm_up(self) -> None:
        """Pre-spawn the Phonon-2 fermion server so the FIRST utterance
        streams instead of falling back to whisper.

        The engine is a separate process (fermion serve phonon-2), so GIL
        contention during model loading can never starve the main asyncio
        event loop. Safe to call on EVERY wake word trigger: if the server
        is already up or spawning this is a no-op.
        """
        from .phonon2_stream import get_server_manager

        mgr = get_server_manager()
        if mgr.server_ready():
            return  # already warm — no-op, no thread churn

        def _do_phonon2_warm():
            try:
                if mgr.ensure():
                    logger.info(
                        "[VoiceCommand] Phonon-2 server warm — first "
                        "utterance will stream"
                    )
                else:
                    logger.warning(
                        "[VoiceCommand] Phonon-2 server unavailable — "
                        "faster-whisper serves the finals"
                    )
            except Exception as exc:
                logger.warning(
                    f"[VoiceCommand] Phonon-2 warm-up failed (non-fatal): {exc}"
                )

        threading.Thread(
            target=_do_phonon2_warm, daemon=True, name="iris-phonon2-warmup"
        ).start()

    # ------------------------------------------------------------------ #
    # Phonon-2 streaming ASR path (primary; whisper is the FINAL fallback)
    # ------------------------------------------------------------------ #

    def _on_stt_interim_text(self, text: str) -> None:
        """Relay one Phonon-2 interim hypothesis to the gateway callback
        (voice_interim WS broadcast). Guarded: a callback fault must never
        touch the stream reader thread."""
        cb = self._on_stt_interim
        if cb is not None:
            try:
                cb(text)
            except Exception:
                pass

    def _finalize_via_phonon2(self, audio_np: np.ndarray) -> str:
        """Close the live stream and return its final transcript.

        The frames were already fed while recording (see _capture_frame);
        this runs at VAD end-of-speech. Returns "" on ANY failure (stream
        never opened, died mid-utterance, finish timeout, empty result) —
        the caller then transcribes the captured buffer with
        faster-whisper (REQ-1 AC1.2). Never raises.

        Records STT latency in self._last_stt_timing for the result
        callback to forward to iris_gateway (stt_backend is greppable
        evidence for the Wave 1 live gate: never 'parakeet*').
        """
        import time as _stt_time
        _stt_start = _stt_time.monotonic()
        audio_s = len(audio_np) / self.sample_rate
        timing = self._phonon2.last_timing()
        text = self._phonon2.finish()
        _stt_end = _stt_time.monotonic()
        if text:
            self._last_stt_timing = {
                "stt_start_monotonic": _stt_start,
                "stt_end_monotonic": _stt_end,
                "stt_latency_ms": (_stt_end - _stt_start) * 1000.0,
                "stt_backend": "phonon-2",
                "stt_audio_seconds": audio_s,
                # REQ-1 AC1.6: first-hypothesis latency is the streaming
                # headline number (measured 0.69 s in the Wave 0 smoke).
                "stt_first_partial_s": timing.get("first_partial_s"),
            }
            logger.info(
                f"[STT] phonon-2 stream — '{text[:80]}' "
                f"(final latency: {self._last_stt_timing['stt_latency_ms']:.0f}ms, "
                f"first partial: {timing.get('first_partial_s')})"
            )
        else:
            reason = self._phonon2.last_error or "empty result"
            backend = "phonon-2_empty" if reason == "empty result" else "phonon-2_failed"
            self._last_stt_timing = {
                "stt_start_monotonic": _stt_start,
                "stt_end_monotonic": _stt_end,
                "stt_latency_ms": 0.0,
                "stt_backend": backend,
                "stt_audio_seconds": audio_s,
            }
            logger.warning(
                "[STT] phonon-2 stream unavailable (%s) — falling back to whisper",
                reason,
            )
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
                    "[VoiceCommand] WATCHDOG: transcription thread hung for 60s — "
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
                    "[VoiceCommand] Recording cancelled — skipping transcription"
                )
                self._phonon2.abort()  # drop the live stream without waiting
                self._raw_frames = []
                self.audio_buffer = []
                self._on_transcription_complete("")
                return

            # ── Guard: skip transcription when VAD found no speech ──────
            # After barge-in or auto-relisten, the VAD may timeout without
            # ever detecting speech onset.  The buffer still contains
            # near-silence frames.  Sending this to the STT engine causes it
            # to hallucinate short filler words ("yeah", "okay", "hello") which
            # the agent treats as real user input — creating phantom
            # conversational turns.  Skip transcription entirely when no
            # speech was detected.
            if not _speech_detected:
                logger.info(
                    "[VoiceCommand] VAD detected no speech — "
                    "discarding buffer (avoid STT hallucination)"
                )
                self._phonon2.abort()  # drop the live stream without waiting
                self._raw_frames = []
                self.audio_buffer = []
                self._on_transcription_complete("")
                return

            if not self._raw_frames:
                logger.info("[VoiceCommand] No audio captured — ignoring")
                self._on_transcription_complete("")
                return

            # ── Guard: a wake-opened take needs the wake name in its clip ──
            # Before any STT of the request, so ambient speech after a false
            # fire never becomes a transcript, a task, or a memory.
            if not self._wake_confirmed():
                self._phonon2.abort()
                self._raw_frames = []
                self.audio_buffer = []
                self._on_transcription_complete("")
                return

            # Concatenate all captured frames into one float32 array
            audio_np = np.concatenate(self._raw_frames, axis=0).astype(np.float32)
            duration = len(audio_np) / self.sample_rate

            # REQ-2 AC2.3: calibrate the transcription watchdog to the captured
            # audio length. The base 60s watchdog above guards the VAD-wait
            # phase; once we know how long the utterance is, re-arm it with
            # T = max(25.0, audio_seconds * 3.0) so high-load CPU conditions
            # (memory-starved faster-whisper) do not prematurely abort a valid
            # transcription into VoiceState.ERROR.
            _watchdog_timer.cancel()
            _watchdog_timeout = max(25.0, duration * 3.0)
            _watchdog_timer = threading.Timer(_watchdog_timeout, _watchdog_reset)
            _watchdog_timer.daemon = True
            _watchdog_timer.start()

            rms = float(np.sqrt(np.mean(audio_np ** 2)))
            peak = float(np.max(np.abs(audio_np)))
            logger.info(
                f"[VoiceCommand] Transcribing {duration:.1f}s of audio "
                f"(RMS={rms:.4f}, peak={peak:.4f})..."
            )
            if rms < 1e-4:
                logger.warning(
                    "[VoiceCommand] Audio RMS near zero — likely silence. "
                    "Skipping transcription to avoid STT hallucination."
                )
                self._raw_frames = []
                self.audio_buffer = []
                self._on_transcription_complete("")
                return

            self._set_state(VoiceState.PROCESSING, "Transcribing...")

            # ── Processing-phase orb breathing ─────────────────────────
            # During transcription, is_recording=False so _capture_frame returns
            # early and the orb gets zero audio_envelope messages. Without this,
            # the orb appears dead during the 0.5-30s processing window (latency
            # varies: whisper ~80ms, phonon-2 stream final ~0.1-1s). Emit a subtle
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

            # ── Primary path: Phonon-2 live stream final ────────────────
            transcript = self._finalize_via_phonon2(audio_np)

            _proc_pulse_stop.set()  # stop the processing pulse

            # ── Fallback path: faster-whisper (CPU, tiny int8) ─────────────
            if not transcript:
                logger.info("[STT] Attempting faster-whisper CPU fallback...")
                import time as _stt_time_w
                _w_start = _stt_time_w.monotonic()
                whisper = self._get_whisper()
                if whisper is None:
                    # Both engines cold (phonon-2 server spawning + whisper loading).
                    # Complete gracefully with "" (IDLE, not ERROR) so the
                    # next wake word still works. Mirrors the no-speech path.
                    logger.warning("[STT] whisper unavailable (loading) — skipping this turn")
                    self._on_transcription_complete("")
                    self._raw_frames = []
                    if hasattr(self, "audio_buffer"):
                        self.audio_buffer = []
                    return
                segments, _ = whisper.transcribe(
                    audio_np,
                    language="en",
                    beam_size=1,  # 3x faster; negligible quality loss for conversational STT
                    best_of=1,  # deterministic, fastest path
                    condition_on_previous_text=False,  # prevents hallucination drift
                    vad_filter=False,  # energy VAD already handled end-of-speech — whisper VAD strips too aggressively
                )
                transcript = " ".join(s.text.strip() for s in segments).strip()
                # Whisper VAD (if enabled) can strip already-trimmed audio to zero
                # segments for short utterances. Retry once with VAD explicitly off.
                if not transcript:
                    logger.warning("[STT] whisper returned empty — retrying without VAD filter")
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
                        f"[STT] whisper CPU — '{transcript[:80]}' "
                        f"(latency: {self._last_stt_timing['stt_latency_ms']:.0f}ms)"
                    )
                if transcript:
                    logger.info("[STT] whisper CPU — '%s'", transcript[:80])
                else:
                    logger.warning(
                        "[STT] whisper CPU returned empty text. "
                        "Check: (1) mic input level, (2) VAD_ENERGY_THRESHOLD "
                        f"(currently {self.VAD_ENERGY_THRESHOLD}), "
                        "(3) audio buffer has actual speech (not just silence)"
                    )

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
        finally:
            # Cancel watchdog if thread completed normally
            _watchdog_timer.cancel()
            # Belt-and-suspenders: ensure is_recording is always reset
            # even if the thread is killed or a non-Exception is raised
            if self.is_recording:
                logger.warning(
                    "[VoiceCommand] finally: is_recording was still True — "
                    "resetting (thread may have been killed)"
                )
                self.is_recording = False

    def _vad_wait_for_speech_then_silence(self) -> bool:
        """
        Energy-based VAD with adaptive noise-floor calibration (plan §1.3).

        State machine:
          CALIBRATE  → sample ~0.5s ambient audio, compute noise floor, set thresholds
          PRE_SPEECH  → wait for audio above speech_threshold (noise_floor * 3.0)
          IN_SPEECH   → wait for sustained silence (adaptive frames) below silence_threshold
          DONE        → return True (triggers transcription)

        The fixed threshold (VAD_ENERGY_THRESHOLD) was the root cause of the
        intermittent "STT never starts" bug: too high in a quiet room (speech
        never detected) or too low in a noisy room (background noise triggers
        false speech). Calibrating from the actual ambient level makes detection
        robust to the environment. Hysteresis (speech_threshold > silence_threshold)
        prevents flicker at the boundary.

        If _pre_speech_timeout_sec > 0, gives up if speech onset doesn't arrive
        within that window — used by conversation-mode relisten passes.

        Returns:
            True if speech was actually detected and ended naturally.
            False if only silence was captured (timeout or max duration).
            Callers should skip transcription when False to avoid
            Parakeet hallucinating text from silence.
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

        # ── Adaptive noise-floor calibration (plan §1.3.1) ──────────────
        # Sample ~0.5s of ambient audio to set thresholds relative to the
        # actual room noise. Recalibrate once if speech hasn't started by 10s.
        calibration_frames = max(1, int(0.5 / frame_sec))
        noise_floor = self.VAD_ENERGY_THRESHOLD  # fallback if no frames yet
        _calibration_rms: list = []
        _recalibrated = False

        def _calibrate() -> tuple:
            """Return (speech_threshold, silence_threshold) from current noise floor."""
            floor = noise_floor if noise_floor > 0 else self.VAD_ENERGY_THRESHOLD
            # Hysteresis: speech onset needs 3× floor, offset needs only 1.5× floor.
            speech_th = max(floor * 3.0, self.VAD_ENERGY_THRESHOLD * 0.5)
            silence_th = max(floor * 1.5, self.VAD_ENERGY_THRESHOLD * 0.25)
            return speech_th, silence_th

        speech_threshold, silence_threshold = _calibrate()

        silence_count = 0
        speech_count = 0
        speech_started = False
        speech_frames_total = 0  # total speech frames → drives adaptive silence
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
                # More CPU-efficient than time.sleep() — wakes immediately on cancel.
                self._stop_event.wait(timeout=self.VAD_POLL_INTERVAL_SEC)
                continue

            new_frames = self._raw_frames[last_processed:current_len]
            last_processed = current_len

            for frame in new_frames:
                total_frames += 1
                rms = float(np.sqrt(np.mean(np.square(frame))))

                # ── Calibration phase: collect ambient RMS, no VAD yet ──
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
                    # Normalise: divide by 2× speech threshold so speech ≈ 0.5
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

                # ── Recalibrate once if speech hasn't started after 10s ──
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

                # ── VAD state machine ───────────────────────────────────
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
                        # Pause tolerance ramps with utterance length (plan §1.3.2): short
                        # utterances stay snappy, longer ones earn room for a
                        # natural pause.
                        #
                        # 2026-10-07: this was an if/elif —
                        # `if speech_sec < 2.0: base / elif speech_sec > 5.0: cap`
                        # — which left a HOLE between 2 s and 5 s. An utterance
                        # in that band matched neither branch and silently kept
                        # the BASE 0.8 s cutoff, so it got no pause tolerance at
                        # all. Measured live: a ~3 s request ("search up the
                        # recent repo of the math") followed by a ~1 s thinking
                        # pause was cut off, so IRIS heard only the first half
                        # and never learned the request also meant to
                        # cross-reference the project. The missing feature was
                        # not the cause — the hole was. Now a continuous ramp.
                        adaptive_silence = silence_needed
                        speech_sec = speech_frames_total * frame_sec
                        if speech_sec >= _VAD_RAMP_START_SEC:
                            _frac = min(
                                1.0,
                                (speech_sec - _VAD_RAMP_START_SEC)
                                / _VAD_RAMP_SPAN_SEC,
                            )
                            _scale = 1.0 + (_VAD_RAMP_MAX_SCALE - 1.0) * _frac
                            adaptive_silence = min(
                                int(silence_needed * _scale),
                                int(self.VAD_SILENCE_SEC_MAX / frame_sec),
                            )
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
                            return True  # silence after real speech → done
                    else:
                        # Background noise before speech — decay counter slowly
                        speech_count = max(0, speech_count - 1)
                        pre_speech_frames += 1
                        if pre_speech_frames >= pre_speech_max_frames:
                            logger.info(
                                f"[VAD] pre-speech timeout "
                                f"({self._pre_speech_timeout_sec}s) — no speech detected, "
                                f"skipping transcription to avoid hallucination"
                            )
                            return False  # no speech onset → skip transcription

        logger.debug(
            f"[VAD] loop ended (frames={total_frames}, speech_started={speech_started})"
        )
        return speech_started

    # -------------------------------------------------------------------------
    # Internal — audio capture
    # -------------------------------------------------------------------------

    def _capture_frame(self, audio_frame: np.ndarray) -> None:
        """
        AudioEngine frame listener — accumulates float32 PCM while recording.
        Called from the sounddevice callback thread; must never raise.
        """
        # NOTE: a throttled [DIAG][capture_frame] RMS log used to live here.
        # It was session-279 temporary instrumentation; the equivalent logs in
        # audio/engine.py and voice/violawake_detector.py were removed in
        # session 280 and this copy was missed. It fired every 30 frames
        # (~1-3 lines/sec) FOREVER, including while idle, so the capture
        # callback wrote to a rotating log on every single audio frame window
        # for the life of the process. That is sustained disk I/O in the audio
        # callback path — exactly the contention that makes a multi-GB GGUF
        # model load (HDD-bound) stall the rest of the app. Removed; mic
        # liveness is observable via the existing capture/device diagnostics.

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

        # ── Feed the Phonon-2 live stream (REQ-1 AC1.1) ─────────────────
        # Same frame, second consumer: the stream turns it into interim
        # hypotheses while the user speaks. Best-effort and never raises
        # (this runs on the sounddevice callback thread); a dropped frame
        # only delays the next partial. The _raw_frames copy above stays
        # the whisper-fallback safety net.
        if self._phonon2.active:
            self._phonon2.feed_frame(audio_frame)

        # ── Broadcast audio_envelope for orb breathing during STT ──────
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
    # Internal — helpers
    # -------------------------------------------------------------------------

    def _on_transcription_complete(self, transcript: str) -> None:
        """Called when whisper returns a transcript."""
        transcript = transcript.strip()

        if not transcript:
            logger.warning(
                "[VoiceCommand] Empty transcript dispatched to gateway — "
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
            "stt_timing": dict(getattr(self, "_last_stt_timing", {})),  # STT latency for metric broadcast
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
                    # T7 (REQ-7 AC7.2): route the beep through the lane
                    # scheduler so the half-duplex mic gate derives from
                    # scheduler state. The scheduler's worker plays it via the
                    # registered beep callback (gate already closed).
                    from backend.agent.conversation_kernel import get_conversation_kernel
                    _ck = get_conversation_kernel()
                    if _ck is not None and getattr(_ck, "scheduler", None) is not None:
                        _ck.set_beep_play_callback(self._play_beep_node)
                        from backend.agent.speech_lanes import NARRATION, Situation, build_node, route
                        _situation = Situation(
                            trigger_label=NARRATION,
                            source="voice",
                            content_shape="conversation",
                        )
                        _node = build_node(
                            _situation,
                            route(_situation),
                            turn_id="unknown",
                            session_id="default",
                            content={
                                "kind": "beep",
                                "sound": sound,
                                "sample_rate": sr,
                                "device": _dev,
                            },
                        )
                        _ck.scheduler.admit(_node)
                    else:
                        # No scheduler wired — fall back to direct playback.
                        self._play_beep_direct(sound, sr, _dev)
                except Exception as _beep_err:
                    logger.warning(f"[VoiceCommand] Activation sound failed: {_beep_err}")
        except Exception as e:
            logger.warning(f"[VoiceCommand] Activation sound failed: {e}")

    def _play_beep_node(self, node) -> None:
        """Play a beep node (called by the lane scheduler's worker thread).

        The half-duplex mic gate is already closed by the scheduler while this
        node plays (REQ-7 AC7.2).
        """
        content = node.content or {}
        sound = content.get("sound")
        sr = content.get("sample_rate") or 24000
        _dev = content.get("device")
        if sound is None:
            return
        import sounddevice as _sd
        try:
            _sd.play(sound, sr, device=_dev, blocking=True)
        except Exception as _beep_err:
            logger.warning(
                f"[VoiceCommand] Direct sd.play failed ({_beep_err}), using pipeline"
            )
            try:
                self.audio_engine.pipeline.play_audio(sound, sample_rate=sr)
            except Exception:
                pass

    def _play_beep_direct(self, sound, sr, _dev) -> None:
        """Fallback direct beep playback when no lane scheduler is wired.

        Engages the half-duplex gate around playback so the just-opened mic
        doesn't capture the activation sound (the pre-scheduler behavior).
        """
        import sounddevice as _sd
        try:
            self.audio_engine.set_tts_active(True)
        except Exception:
            pass
        try:
            self.audio_engine.note_tts_audio()
        except Exception:
            pass
        try:
            _sd.play(sound, sr, device=_dev, blocking=True)
        except Exception as _beep_err:
            logger.warning(
                f"[VoiceCommand] Direct sd.play failed ({_beep_err}), using pipeline"
            )
            try:
                self.audio_engine.pipeline.play_audio(sound, sample_rate=sr)
            except Exception:
                pass
        finally:
            try:
                self.audio_engine.set_tts_active(False)
            except Exception:
                pass

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

    def _fire_idle_if_not_recording(self) -> None:
        """Timer callback: transition to IDLE only if no recording is active.

        Prevents an orphaned timer from a previous SUCCESS from forcing
        RECORDING → IDLE when the user has already barge-in-started a new
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

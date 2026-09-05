#!/usr/bin/env python3
"""
Violawake Wake Word Detector

Drop-in replacement for PorcupineWakeWordDetector using the Violawake SDK
(custom ONNX head + OpenWakeWord backbone). Matches the same interface that
AudioEngine expects:

    - is_enabled() -> bool
    - sample_rate (property) -> int
    - frame_length (property) -> int
    - process_frame(audio_frame) -> (bool, Optional[str])
    - cleanup()

Engine-neutral since the Violawake migration (session 278). The detector loads
a custom ONNX wake head (the trained "Hey Iris" model) via
``violawake_sdk.WakeDetector(model=<path>)``.

Audit result (pin_4cbe8eb4afab): ``WakeDetector`` does NOT expose
``frame_length`` / ``sample_rate`` attributes, so this adapter hardcodes
320 samples / 16000 Hz per the spec.
"""

import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Violawake / OpenWakeWord contract (verified in T0 audit):
# 16 kHz mono int16, 20 ms / 320-sample frames.
SAMPLE_RATE: int = 16000
FRAME_LENGTH: int = 320

# Default wake phrase label returned on detection.
WAKE_PHRASE: str = "Hey Iris"

# Detection threshold — measured on this model, NOT the SDK's tuned default.
#
# The SDK default is 0.80, but 0.80 sits ABOVE the wake phrase's own peak
# score, so the detector could never fire (session-280 root cause). Measured
# end-to-end through this adapter using 512-sample engine frames:
#
#   "Hey Iris" @16 kHz (TTS probe, 5 injections) ... 0.773 - 0.786
#   quiet room tone (worst negative) ................ 0.572 - 0.599
#   loud broadband noise ............................ 0.420
#   syllabic / speech-like .......................... 0.376
#   tonal / music ................................... 0.303
#
# 0.70 clears the worst measured negative by 0.10 and the weakest measured
# positive by 0.07. The "silence scores up to 0.598" figure that originally
# drove the 0.80 choice was the mel-buffer startup transient (the backbone
# seeds its mel buffer with np.ones), not steady state — steady-state digital
# silence settles at 0.401.
#
# NOTE: 0.70 is a FLOOR, not a final value. WakeConfig detection_sensitivity
# (0.0-1.0, default 0.65) is combined as max(DEFAULT_THRESHOLD, sensitivity),
# so lowering sensitivity below 0.70 has no effect; raise it to be stricter.
DEFAULT_THRESHOLD: float = 0.70

# ── Anti-retrigger / anti-false-positive guards ───────────────────────────
# The head's receptive window is ~720 ms, so one spoken "Hey Iris" holds the
# score above threshold across MANY consecutive 320-sample chunks. A plain
# "score > threshold" test therefore fires once per chunk: measured on
# 2026-09-01, a single utterance produced 18 detections in 290 ms (scores
# 0.702-0.721), each one re-entering AudioEngine's wake callback and
# restarting the VAD.
#
# These two guards collapse that burst to one trigger and reject loud
# transients, WITHOUT raising the threshold. The threshold cannot go up: the
# wake phrase's own live peak is only 0.748, so 0.70 is already a thin margin
# over the 0.599 worst-case background.
#
#   CONSECUTIVE_CHUNKS — the score must stay above threshold for this many
#     consecutive 320-sample chunks (~40 ms). A door slam, keyboard clack or
#     a speaker thump spikes one chunk and is gone; the wake phrase sustains.
#     The wake phrase produces 18+ consecutive hits, so 2 was too permissive:
#     transient room noises can sustain for 2-3 chunks.  8 (= ~256ms) filters
#     all non-speech transients while still catching the wake phrase with room
#     to spare: one utterance sustains 18+ consecutive hits, and the threshold
#     itself cannot rise (live peak 0.748 vs 0.70 floor), so chunk-count is the
#     only false-trigger lever. Raised 5 -> 8 live 2026-09-04 (loud-room falses).
#   COOLDOWN_SEC — after a detection, further detections are ignored for this
#     long. One utterance collapses to one trigger, and the activation chime
#     (which the mic hears) cannot re-fire the detector.
CONSECUTIVE_CHUNKS: int = 8
COOLDOWN_SEC: float = 2.0
#   RELEASE_FLOOR — the release chunk must score BELOW this, not merely below
#     the (possibly adapted) threshold. A plateau dithering across the line
#     (0.705, 0.699, 0.704, ...) released the old gate on every wobble.
#     Measured 2026-09-05 through the real detector: a true "hey iris"
#     collapses to 0.576-0.589 on its first below-threshold chunk (full and
#     x0.3 gain alike), so 0.65 keeps true releases with ~0.06 margin while
#     rejecting shallow dithers. A shallow release disarms as a reject.
RELEASE_FLOOR: float = 0.65
#   REARM_QUIET_CHUNKS — after any fire or sustained-reject, this many
#     consecutive below-threshold 320-sample chunks (~0.5 s) must pass before
#     a new streak may arm. Bursty background (TV dialogue with pauses)
#     re-armed the old gate every 8 hot chunks and fired on every pause;
#     a genuine second phrase always has real silence before it (and the 2 s
#     cooldown covers the immediate repeat window anyway).
REARM_QUIET_CHUNKS: int = 25
#   PROFILER_MAX_THRESHOLD — ceiling for the SDK adaptive threshold (K4).
#     The profiler raises the bar only for frames near the noise floor
#     (quiet-room sustained mush, the 2026-09-04 false signature) and lowers
#     it toward the floor for clear speech. Floor stays DEFAULT_THRESHOLD
#     (0.70): in quiet conditions behavior is exactly today's, so no new
#     misses are possible there; x0.3-gain phrase still arms+fires (measured
#     2026-09-05), so 0.78 cannot clip real utterances either.
PROFILER_MAX_THRESHOLD: float = 0.78
#   RELEASE_WINDOW_SEC — after the streak gate passes, the score must drop
#     back below threshold within this long. A spoken phrase always ends;
#     sustained noise (TV dialogue, hums) never releases and therefore never
#     fires, no matter how long it holds above threshold. Window measured
#     from the arming instant (~8 chunks into the phrase); a "hey iris" is
#     ~300-700ms end to end, so 0.8s clears it with margin while an endless
#     sound ages out and disarms. When in doubt the detector stays silent:
#     a missed wake retries by speaking again, a false wake interrupts work.
RELEASE_WINDOW_SEC: float = 0.8


def _patch_onnx_single_thread() -> None:
    """Force Violawake's ONNX Runtime sessions to a single thread.

    ``violawake_sdk.backends.onnx_backend.OnnxBackend.load`` creates each
    session with the DEFAULT ``intra_op_num_threads`` (= number of physical
    cores, 8 on this machine). The wake detector runs at 31 Hz; between the
    tiny ~1ms 320-sample inferences the thread pool busy-waits, pinning
    ~325-400% CPU at idle (session 279 root cause). The frames are tiny, so
    1 thread is more than enough — measured 1.7% CPU vs 325% at 31 Hz.

    Idempotent: patches the class once. Only affects the wake detector's own
    sessions (the backend creates no other onnxruntime sessions).
    """
    try:
        from violawake_sdk.backends.onnx_backend import OnnxBackend, OnnxSession
    except Exception:
        return  # SDK not installed / backend module moved — leave as-is

    if getattr(OnnxBackend, "_iris_single_thread_patched", False):
        return

    def _load(self, model_path, **kwargs):
        import onnxruntime as ort
        from pathlib import Path

        providers = kwargs.get("providers", self._providers)
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        try:
            session = ort.InferenceSession(
                str(Path(model_path)), sess_options=so, providers=providers
            )
        except Exception as exc:
            from violawake_sdk._exceptions import ModelLoadError

            raise ModelLoadError(
                f"ONNX Runtime failed to load {model_path}: {exc}"
            ) from exc
        return OnnxSession(session)

    OnnxBackend.load = _load
    OnnxBackend._iris_single_thread_patched = True
    logger.info(
        "[ViolawakeDetector] ONNX sessions forced to single thread "
        "(intra_op_num_threads=1) — eliminates wake-detector thread-pool spin"
    )


class ViolawakeWakeWordDetector:
    """
    Wake word detector using the Violawake SDK with a custom ONNX head.

    Supports:
    - Custom ONNX wake head (the trained "Hey Iris" model)
    - CPU-first ONNX Runtime provider
    - Bounded 320-sample frame buffering (handles chunks not equal to 320)
    - Lifecycle status (disabled / loading / ready / error)
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        sensitivity: float = 0.65,
        providers: Optional[list] = None,
    ):
        """
        Initialize the Violawake wake word detector.

        Args:
            model_path: Path to the custom ONNX wake head. If None, resolved
                from WakeConfig (project-root default).
            sensitivity: Detection sensitivity (0.0-1.0). Mapped to a detector
                threshold with a floor of DEFAULT_THRESHOLD (0.70), which
                clears the measured worst-case background score (0.599).
            providers: ONNX Runtime providers. Defaults to CPU-first.
        """
        self._disabled = False
        self._disabled_reason: str = ""
        self._detector = None
        self._model_path = model_path
        self._sensitivity = sensitivity
        self._providers = providers or ["CPUExecutionProvider"]

        # 0.70 is a measured floor, not the SDK default (0.80 sits above the
        # wake phrase's own peak — see DEFAULT_THRESHOLD). A higher sensitivity
        # value raises the threshold above the floor.
        self._threshold = max(DEFAULT_THRESHOLD, float(sensitivity))

        # Bounded remainder buffer for frames not aligned to 320 samples.
        # Max 319 samples after each call — never accumulates unbounded.
        self._remainder = bytearray()

        # Anti-retrigger state (see CONSECUTIVE_CHUNKS / RELEASE_WINDOW_SEC /
        # COOLDOWN_SEC / RELEASE_FLOOR / REARM_QUIET_CHUNKS).
        self._consecutive_hits = 0
        # Peak score of the current streak (for the detection log: the fire
        # happens on the below-threshold RELEASE chunk, whose own score is
        # meaningless — report what the phrase itself scored).
        self._streak_peak = 0.0
        # Monotonic timestamp when the streak gate passed (armed, awaiting
        # the release); None while idle or disarmed.
        self._streak_armed_at: float | None = None
        self._last_detection_at = 0.0
        # Re-arm inhibit latch + consecutive-quiet counter. Set on every fire
        # or sustained-reject; cleared only after REARM_QUIET_CHUNKS of real
        # below-threshold audio, so bursty noise cannot re-arm on every pause.
        self._inhibit_arm = False
        self._quiet_chunks = 0
        # SDK adaptive-threshold profiler (K4). None when the installed SDK
        # predates it — the gate then runs on the fixed threshold exactly as
        # before, plus hysteresis and the re-arm gap.
        self._profiler = None

        # Lifecycle status for diagnostics.
        self._status = "loading"
        self._last_error: Optional[str] = None
        self._detection_count = 0

        self._initialize()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def _resolve_model_path(self) -> Optional[str]:
        """Resolve the ONNX model path from explicit arg or WakeConfig."""
        if self._model_path:
            return self._model_path
        try:
            from backend.agent.wake_config import get_wake_config

            return get_wake_config().get_model_path()
        except Exception as exc:
            logger.warning(
                f"[ViolawakeDetector] Could not resolve model path from WakeConfig: {exc}"
            )
            return None

    def _initialize(self) -> None:
        """Load the Violawake detector with the custom ONNX head."""
        model_path = self._resolve_model_path()
        self._model_path = model_path  # store resolved path for diagnostics
        if not model_path or not os.path.exists(model_path):
            self._disabled = True
            self._status = "error"
            self._last_error = f"ONNX model not found: {model_path}"
            self._disabled_reason = self._last_error
            logger.error(f"[ViolawakeDetector] {self._last_error}")
            return

        try:
            from violawake_sdk import WakeDetector

            # Force the Violawake ONNX sessions to a single thread BEFORE the
            # WakeDetector builds them. OnnxBackend.load() creates sessions with
            # the DEFAULT intra_op_num_threads (= physical cores, 8 here). The
            # wake detector runs at 31 Hz; between the tiny ~1ms 320-sample
            # inferences the thread pool busy-waits, pinning ~325-400% CPU at
            # idle (session 279). 1 thread is more than enough for these frames.
            _patch_onnx_single_thread()

            logger.info(
                f"[ViolawakeDetector] Loading custom ONNX head: {os.path.basename(model_path)} "
                f"(threshold={self._threshold}, providers={self._providers})"
            )
            self._detector = WakeDetector(
                model=model_path,
                threshold=self._threshold,
                providers=self._providers,
            )
            self._status = "ready"
            logger.info(
                f"[ViolawakeDetector] Ready — {os.path.basename(model_path)} "
                f"({SAMPLE_RATE} Hz, {FRAME_LENGTH} samples/frame)"
            )

            # SDK adaptive threshold (K4): per-frame dynamic bar driven by a
            # rolling noise-floor estimate. Raises only for near-floor frames
            # (quiet-room sustained mush); never below DEFAULT_THRESHOLD, so
            # quiet-condition behavior is unchanged. Absent on older SDKs —
            # the gate degrades to the fixed threshold, never to an error.
            try:
                from violawake_sdk import NoiseProfiler

                self._profiler = NoiseProfiler(
                    base_threshold=self._threshold,
                    min_threshold=DEFAULT_THRESHOLD,
                    max_threshold=PROFILER_MAX_THRESHOLD,
                    frames_per_second=50.0,  # 320 samples @16 kHz = 20 ms
                )
                logger.info(
                    "[ViolawakeDetector] Adaptive threshold on "
                    f"(floor={DEFAULT_THRESHOLD}, ceiling={PROFILER_MAX_THRESHOLD})"
                )
            except Exception as exc:
                self._profiler = None
                logger.debug(
                    f"[ViolawakeDetector] NoiseProfiler unavailable ({exc}) — "
                    "fixed threshold"
                )
        except ImportError:
            self._disabled = True
            self._status = "error"
            self._last_error = (
                "violawake_sdk not installed. Run: pip install 'violawake[oww]'"
            )
            self._disabled_reason = self._last_error
            logger.error(f"[ViolawakeDetector] {self._last_error}")
        except Exception as exc:
            self._disabled = True
            self._status = "error"
            self._last_error = str(exc)
            self._disabled_reason = self._last_error
            logger.error(
                f"[ViolawakeDetector] Failed to initialize: {exc}", exc_info=True
            )

    # ------------------------------------------------------------------
    # Public API (matches PorcupineWakeWordDetector interface)
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """Return True if the detector is ready to process frames."""
        return not self._disabled and self._detector is not None

    @property
    def sample_rate(self) -> int:
        """Required sample rate for audio input (16 kHz)."""
        return SAMPLE_RATE

    @property
    def frame_length(self) -> int:
        """Required frame length for audio input (320 samples)."""
        return FRAME_LENGTH

    def process_frame(self, audio_frame) -> Tuple[bool, Optional[str]]:
        """
        Process a single audio frame for wake word detection.

        Accepts any sequence of int16 samples (numpy array or list). Handles
        chunks not equal to 320 samples via a bounded remainder buffer.

        Returns:
            Tuple of (wake_word_detected, wake_word_name)
        """
        if self._disabled or self._detector is None:
            return False, None

        try:
            # Convert to int16 bytes and buffer.
            import numpy as np
            import time

            now = time.monotonic()

            frame = np.asarray(audio_frame, dtype=np.int16)
            self._remainder.extend(frame.tobytes())

            # Process complete 320-sample (640-byte) frames.
            detected = False
            while len(self._remainder) >= FRAME_LENGTH * 2:
                chunk = np.frombuffer(
                    self._remainder[: FRAME_LENGTH * 2], dtype=np.int16
                )
                del self._remainder[: FRAME_LENGTH * 2]

                score = self._detector.process(chunk)
                # Normalize once: a None score (SDK gap) is silence, never hot.
                s = 0.0 if score is None else float(score)
                # Dynamic bar: SDK noise-profiler threshold when available,
                # else the fixed floor. In quiet conditions the profiler sits
                # at the floor, so behavior there is exactly the old gate.
                thr = (
                    float(self._profiler.update(chunk.astype(np.float32)))
                    if self._profiler is not None
                    else self._threshold
                )
                if s <= thr:
                    # Below threshold — either idle (restart the streak) or the
                    # RELEASE of an armed streak: the sound ENDED the way a
                    # spoken phrase does, so this is the moment to fire.
                    # Sustained noise never releases and therefore never fires
                    # (peak-and-release, live 2026-09-04: TV dialogue held
                    # 0.70+ indefinitely and defeated the chunk-count gate at
                    # any count).
                    self._quiet_chunks += 1
                    if self._quiet_chunks >= REARM_QUIET_CHUNKS:
                        self._inhibit_arm = False
                    if (
                        self._streak_armed_at is not None
                        and now - self._streak_armed_at <= RELEASE_WINDOW_SEC
                    ):
                        self._streak_armed_at = None
                        self._consecutive_hits = 0
                        # Hysteresis: a plateau dithering across the line also
                        # "releases" within the window. Only a collapse below
                        # RELEASE_FLOOR counts (true phrase: 0.576-0.589).
                        if s >= RELEASE_FLOOR:
                            logger.debug(
                                "[ViolawakeDetector] shallow release rejected "
                                f"(score={s:.3f}, floor={RELEASE_FLOOR})"
                            )
                            self._streak_peak = 0.0
                            self._inhibit_arm = True
                            self._quiet_chunks = 0
                            continue
                        # Refractory period (unchanged semantics).
                        if now - self._last_detection_at < COOLDOWN_SEC:
                            logger.debug(
                                f"[ViolawakeDetector] suppressed within cooldown "
                                f"(score={s:.3f}, "
                                f"{now - self._last_detection_at:.2f}s since last)"
                            )
                            self._inhibit_arm = True
                            self._quiet_chunks = 0
                            continue
                        self._last_detection_at = now
                        detected = True
                        self._detection_count += 1
                        logger.info(
                            f"[ViolawakeDetector] Wake word detected: '{WAKE_PHRASE}' "
                            f"(peak={self._streak_peak:.3f})"
                        )
                        self._streak_peak = 0.0
                        self._inhibit_arm = True
                        self._quiet_chunks = 0
                        continue
                    # Idle blip, or an armed streak that outlived its window
                    # without releasing (sustained noise — reject quietly).
                    if self._streak_armed_at is not None:
                        logger.debug(
                            "[ViolawakeDetector] sustained score rejected "
                            "(no release within window)"
                        )
                        self._streak_armed_at = None
                        self._inhibit_arm = True
                        self._quiet_chunks = 0
                    self._consecutive_hits = 0
                    self._streak_peak = 0.0
                    continue

                self._quiet_chunks = 0
                self._consecutive_hits += 1
                if s > self._streak_peak:
                    self._streak_peak = s
                if self._consecutive_hits < CONSECUTIVE_CHUNKS:
                    continue

                # Streak gate passed — ARM and wait for the release instead of
                # firing immediately. If the score never drops (constant hum,
                # TV dialogue), the deadline below disarms without firing, and
                # the streak restarts from zero so an endless sound can never
                # accumulate its way to a trigger.
                if self._streak_armed_at is None:
                    # Re-arm gap: after a fire or reject, bursty noise must
                    # show real silence before it may arm again.
                    if self._inhibit_arm:
                        self._consecutive_hits = 0
                        continue
                    self._streak_armed_at = now
                    continue
                if now - self._streak_armed_at > RELEASE_WINDOW_SEC:
                    logger.debug(
                        "[ViolawakeDetector] sustained score rejected "
                        "(hot past release window)"
                    )
                    self._streak_armed_at = None
                    self._consecutive_hits = 0
                    self._streak_peak = 0.0
                    self._inhibit_arm = True
                    self._quiet_chunks = 0
                    continue

            # Bound the remainder buffer (should never exceed 319 samples).
            if len(self._remainder) >= FRAME_LENGTH * 2:
                self._remainder = self._remainder[-FRAME_LENGTH * 2 + 2 :]

            return detected, WAKE_PHRASE if detected else None

        except Exception as exc:
            logger.error(f"[ViolawakeDetector] Error processing frame: {exc}")
            return False, None

    def update_sensitivity(self, wake_word_index: int, sensitivity: float):
        """Update detection sensitivity (requires re-initialization)."""
        if not 0.0 <= sensitivity <= 1.0:
            logger.warning(
                f"[ViolawakeDetector] Invalid sensitivity {sensitivity}, must be 0.0-1.0"
            )
            return
        self._sensitivity = sensitivity
        logger.info(
            f"[ViolawakeDetector] Updated sensitivity to {sensitivity} — re-initializing"
        )
        self.cleanup()
        self._initialize()

    def update_sensitivity_by_name(self, wake_word_name: str, sensitivity: float):
        """Update sensitivity by wake word name (single model — just updates)."""
        self.update_sensitivity(0, sensitivity)

    def get_status(self) -> dict:
        """Return lifecycle status for diagnostics."""
        return {
            "state": self._status,
            "phrase": WAKE_PHRASE,
            "model_name": os.path.basename(self._model_path or ""),
            "backend": "onnx-cpu",
            "last_error": self._last_error,
            "detection_count": self._detection_count,
            "enabled": self.is_enabled(),
        }

    def cleanup(self):
        """Clean up detector resources."""
        detector = getattr(self, "_detector", None)
        if detector is not None:
            try:
                detector.close()
            except Exception as exc:
                logger.debug(f"[ViolawakeDetector] close failed: {exc}")
            self._detector = None
        self._remainder = bytearray()

    def __del__(self):
        """Destructor to ensure cleanup."""
        self.cleanup()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()
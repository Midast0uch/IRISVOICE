"""
conversation_kernel.py — Caducean v2 phase-driven voice wrapper.

v2: THIN WRAPPER on the existing voice pipeline. NO new VAD, NO new TTS,
NO new state machine, NO new event loop.

This module adds Caducean phase-awareness to decisions that the
existing classes already make. It is registered as an additional
observer on existing callbacks; it exposes only two read-only
methods to the existing pipeline:

  - get_tts_chunk_size() -> int (read from Caducean, scaled by force_magnitude)
  - should_halt_on_violation() -> bool (calls existing audio_pipeline.interrupt())

Architecture (per plan §Component 5, "Why this consolidation matters"):
  - VoiceCommandHandler (existing): energy-based VAD, audio_level callback,
    state transitions (IDLE -> RECORDING -> PROCESSING -> SUCCESS).
  - TTSManager (existing): synthesize_stream() with chunking + interrupt.
  - AudioPipeline (existing): interrupt() for barge-in.
  - ConversationKernel (v2): observes callbacks, exposes read-only methods,
    NEVER replaces the existing pipeline.

Why this matters:
  - N parallel VAD implementations fighting each other
  - N parallel TTS paths that can desync
  - N parallel state machines with no single source of truth
  - Wiring changes touching every audio/ file

Verified by 6 consolidation tests in test_conversation_kernel.py:
  - test_voice_handler_state_callbacks_wired
  - test_no_duplicate_vad
  - test_no_duplicate_tts
  - test_existing_voice_tests_still_pass
  - test_speak_response_uses_kernel_chunk_size
  - test_halt_on_violation_breaks_tts_loop
"""

import logging
import threading
from typing import Any, Callable, Optional

from backend.gateway.iris_ffi import (
    ffi_caducean_recommend,
    ffi_caducean_get_direction_signal,
)

logger = logging.getLogger(__name__)

# TTS chunk size bounds (in tokens)
TTS_CHUNK_MIN = 20
TTS_CHUNK_MAX = 200
TTS_CHUNK_SCALE = 300  # chunk = clamp(force_magnitude * SCALE, MIN, MAX)


class ConversationKernel:
    """v2: thin wrapper that adds Caducean phase-awareness to voice.

    The kernel:
      1. Observes existing VoiceCommandHandler callbacks
      2. Exposes 2 read-only methods to the existing pipeline
      3. Never blocks the audio thread (all operations are sync ctypes
         calls which are thread-safe per session_id — see plan §Fix #13)

    Session-id is the unit of identity. One kernel per active session.
    The kernel is owned by iris_gateway and created in set_voice_handler().
    """

    def __init__(
        self,
        voice_handler: Any,  # VoiceCommandHandler (existing)
        tts_manager: Any,  # TTSManager (existing, used via callback only)
        audio_pipeline: Any,  # AudioPipeline (existing, for interrupt)
        session_id_getter: Callable[[], Optional[str]],
    ):
        """Constructor takes references to existing singletons.

        Args:
            voice_handler: The existing VoiceCommandHandler instance.
            tts_manager: The existing TTSManager instance (kept for future
                use; currently the kernel doesn't call TTS directly —
                _speak_response in iris_gateway does).
            audio_pipeline: The existing AudioPipeline instance. Used by
                should_halt_on_violation() to call interrupt() — the
                existing interrupt path.
            session_id_getter: Callable that returns the active session_id.
                Used to look up the Caducean state for this voice session.
                The getter is used (not a stored session_id) because the
                active session can change without a kernel re-instantiation.
        """
        self._voice_handler = voice_handler
        self._tts_manager = tts_manager
        self._audio_pipeline = audio_pipeline
        self._session_id_getter = session_id_getter
        self._was_speaking = False
        self._current_audio_level = 0.0
        # Speech-gating phase driven by the voice pipeline state machine
        # (see on_voice_state). Defaults to EXPAND so speech is allowed
        # until the first RECORDING transition. Previously this attribute
        # was never set, so filter_speech() was a no-op. See plan Issue E.
        self._current_caducean_phase = "EXPAND"
        # Lock for state updates from audio thread (state callbacks may
        # fire from a worker thread; should_halt_on_violation may fire
        # from the TTS loop). The lock is fine-grained: only around the
        # _was_speaking and _current_audio_level flags.
        self._lock = threading.Lock()

    # ── v2: Caducean-driven voice logic ──────────────────────────────

    def _get_current_balance(self) -> float:
        """Fetch current balance from C++ for ffi_caducean_update calls.

        Falls back to 1.0 (safe default) if engine is unavailable or
        balance is out of range. Clamped to [0.1, 3.0] per Caducean
        contract.
        """
        try:
            from backend.gateway.iris_ffi import ffi_calculate_eml

            session_id = self._session_id_getter()
            if session_id is None:
                return 1.0
            score, _, _ = ffi_calculate_eml(session_id)
            return max(0.1, min(3.0, score))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ConversationKernel] _get_current_balance failed: %s", exc)
            return 1.0

    def get_tts_chunk_size(self) -> int:
        """v2: returns the TTS chunk size scaled by force_magnitude.

        Used by _speak_response in iris_gateway to replace the
        hardcoded FIRST_CHUNK_THRESHOLD = 1 and NORMAL_CHUNK_THRESHOLD = 8
        constants. Same physics signal that gates every other
        phase-driven decision in v2.
        """
        try:
            session_id = self._session_id_getter()
            if session_id is None:
                return TTS_CHUNK_MAX // 2  # 100 — reasonable default
            sig = ffi_caducean_get_direction_signal(session_id, balance=1.0)
            raw = int(sig.force_magnitude * TTS_CHUNK_SCALE)
            return max(TTS_CHUNK_MIN, min(TTS_CHUNK_MAX, raw))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ConversationKernel] get_tts_chunk_size failed: %s", exc)
            return TTS_CHUNK_MAX // 2  # 100 — same as default

    def should_halt_on_violation(self) -> bool:
        """v2: returns True iff Caducean has fired TOPO_VIOLATION (rec=3).

        Called from _speak_response at each chunk boundary. If True,
        calls the existing audio_pipeline.interrupt() to halt TTS using
        the same path as user-barge-in.

        The interrupt is a NO-OP if the engine is unavailable — the
        existing pipeline is the source of truth for TTS lifecycle.
        """
        try:
            session_id = self._session_id_getter()
            if session_id is None:
                return False
            rec = ffi_caducean_recommend(session_id)
            if rec == 3:
                # Use the existing interrupt path — same as user barge-in.
                try:
                    self._audio_pipeline.interrupt()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "[ConversationKernel] audio_pipeline.interrupt failed: %s", exc
                    )
                return True
            return False
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "[ConversationKernel] should_halt_on_violation failed: %s", exc
            )
            return False

    # ── Observer callbacks (registered on existing voice_handler) ──

    def on_voice_state(self, state: Any, message: str = "") -> None:
        """Observer: fires on every VoiceCommandHandler state transition.

        Updates Caducean with EXPAND when transitioning to IDLE (user
        turn complete) and COMPRESS when entering RECORDING (user turn
        started). This is the bidirectional coupling between the voice
        pipeline's state machine and the physics state.

        Sequence:
          IDLE -> RECORDING:  user started speaking -> COMPRESS (0,1)
          RECORDING -> PROCESSING -> IDLE:  user finished -> EXPAND (0,0)
          IDLE -> SUCCESS:    TTS finished -> EXPAND (0,0)

        Args:
            state: VoiceState enum value (IDLE, RECORDING, PROCESSING, etc.)
            message: optional human-readable message (for logging only)
        """
        # Lazy import to avoid circular import
        from backend.audio.voice_command import VoiceState

        try:
            session_id = self._session_id_getter()
            if session_id is None:
                return
            state_value = getattr(state, "value", state)
            was_speaking = False

            # ── 1. Set the speech-gating phase FIRST (local state) ──
            # This is the production wiring that was missing: the kernel's
            # own _current_caducean_phase now tracks the real voice state so
            # filter_speech() actually gates. RECORDING = user speaking ->
            # COMPRESS (never talk over the user); every other state ->
            # EXPAND (agent may give feedback while thinking/working).
            if state_value == VoiceState.RECORDING.value:
                with self._lock:
                    self._was_speaking = False
                    self._current_caducean_phase = "COMPRESS"
            elif state_value == VoiceState.IDLE.value:
                with self._lock:
                    was_speaking = self._was_speaking
                    self._was_speaking = False
                    self._current_caducean_phase = "EXPAND"
            elif state_value in (VoiceState.PROCESSING.value, VoiceState.SUCCESS.value):
                with self._lock:
                    self._current_caducean_phase = "EXPAND"

            # ── 2. Drive the Caducean engine (best-effort, never blocks) ──
            # FFI import is lazy + nested so a missing C++ extension can
            # never prevent the speech-gating phase from being set.
            try:
                from backend.gateway.iris_ffi import ffi_caducean_update

                balance = self._get_current_balance()
                if state_value == VoiceState.RECORDING.value:
                    # User started speaking — bias toward compress
                    ffi_caducean_update(session_id, 1, balance)
                elif state_value == VoiceState.IDLE.value and was_speaking:
                    # Turn completed after TTS — bias toward expand
                    ffi_caducean_update(session_id, 0, balance)
                # PROCESSING / SUCCESS don't change Caducean engine phase
            except Exception as _ffi_exc:  # noqa: BLE001
                logger.debug(
                    "[ConversationKernel] caducean engine update skipped: %s", _ffi_exc
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ConversationKernel] on_voice_state failed: %s", exc)

    def on_audio_level(self, level: float) -> None:
        """Observer: fires on every audio-level callback from VAD.

        Tracks the current audio level and triggers a barge-in
        if user speaks while agent is speaking.

        Args:
            level: RMS audio level in [0, 1] (or similar; depends on
                VoiceCommandHandler's normalization)
        """
        with self._lock:
            self._current_audio_level = level
            was_speaking = self._was_speaking
        # Barge-in: if user speaks loudly while agent is speaking,
        # force the engine's parameters so the next update pushes u negative.
        if was_speaking and level > 0.5:
            try:
                session_id = self._session_id_getter()
                if session_id is not None:
                    # Bump walk speed down slightly to slow agent's momentum
                    # and push u into the compress basin. This is a tiny
                    # nudge — the main interrupt path is audio_pipeline.interrupt().
                    from backend.gateway.iris_ffi import (
                        ffi_caducean_get_state,
                        ffi_caducean_set_params,
                    )

                    state = ffi_caducean_get_state(session_id)
                    new_s = max(0.1, min(0.8, state.get("s", 0.35) - 0.05))
                    ffi_caducean_set_params(
                        session_id, state.get("a", 2.0), state.get("b", 2.0), new_s
                    )
            except Exception as exc:  # noqa: BLE001
                logger.debug("[ConversationKernel] barge-in nudge failed: %s", exc)

    def mark_speaking(self, is_speaking: bool) -> None:
        """Called by _speak_response when TTS starts/stops.

        This is a public method that iris_gateway calls explicitly.
        It updates _was_speaking so on_audio_level can detect barge-in.
        """
        with self._lock:
            self._was_speaking = is_speaking

    # ── EventBus integration ─────────────────────────────────────────

    def filter_speech(self, phase: str) -> bool:
        """Determine if speech should be emitted based on Caducean phase.

        Only emit speech during EXPAND phase.  During COMPRESS phase,
        the agent is working on tools — speaking would be distracting.
        """
        return phase in ("EXPAND", "IDLE")

    def subscribe_to_event_bus(self) -> None:
        """Subscribe to EventBus for utterance events.

        This kernel receives utterance events and forwards them
        to the TTS pipeline.  Speech is gated by Caducean phase:
        only EXPAND phase utterances are spoken aloud.
        """
        if getattr(self, "_event_bus_subscribed", False):
            return
        try:
            from backend.agent.event_bus import get_event_bus, IRISStreamEvent

            bus = get_event_bus()
            bus.subscribe(IRISStreamEvent.UTTERANCE_START, self._on_utterance_start)
            bus.subscribe(IRISStreamEvent.UTTERANCE_CHUNK, self._on_utterance_chunk)
            bus.subscribe(IRISStreamEvent.UTTERANCE_DONE, self._on_utterance_done)
            self._event_bus_subscribed = True
            logger.info("[ConversationKernel] Subscribed to EventBus utterance events")
        except Exception as exc:
            logger.warning(
                "[ConversationKernel] EventBus subscription failed: %s", exc
            )

    def _resolve_audio_pipeline(self):
        """Return the audio playback sink.

        Prefers an explicitly-injected pipeline; otherwise derives it from
        the voice handler's audio engine (VoiceCommandHandler.audio_engine.pipeline),
        which is the same AudioPipeline the main response path uses.
        """
        p = getattr(self, "_audio_pipeline", None)
        if p is not None:
            return p
        vh = getattr(self, "_voice_handler", None)
        if vh is not None:
            engine = getattr(vh, "audio_engine", None)
            if engine is not None:
                return getattr(engine, "pipeline", None)
        return None

    def _on_utterance_start(self, payload) -> None:
        """Handle an utterance:start event.

        Synthesizes the text via TTSManager and plays it through the audio
        pipeline. Speech is gated by Caducean phase: only EXPAND-phase
        utterances are spoken aloud (never while the user is recording).
        """
        phase = getattr(self, "_current_caducean_phase", "EXPAND")
        if not self.filter_speech(phase):
            logger.debug(
                "[ConversationKernel] Suppressed utterance (phase=%s)", phase
            )
            return
        text = (payload.data or {}).get("text", "")
        logger.debug(
            "[ConversationKernel] utterance start -> TTS (phase=%s): %s",
            phase,
            text[:60],
        )
        if not text:
            return
        tts = getattr(self, "_tts_manager", None)
        pipeline = self._resolve_audio_pipeline()
        if tts is None or pipeline is None:
            logger.warning(
                "[ConversationKernel] Dropped utterance (tts=%s, pipeline=%s)",
                tts is not None,
                pipeline is not None,
            )
            return
        # Run synthesis + playback off the EventBus dispatch thread so a
        # multi-second utterance doesn't block other subscribers.
        threading.Thread(
            target=self._speak_utterance,
            args=(text, bool((payload.data or {}).get("interrupt"))),
            daemon=True,
            name="ck-utterance",
        ).start()

    def _speak_utterance(self, text: str, interrupt: bool) -> None:
        """Synthesize + play a single utterance (runs in a worker thread)."""
        tts = getattr(self, "_tts_manager", None)
        pipeline = self._resolve_audio_pipeline()
        if tts is None or pipeline is None:
            return
        try:
            if interrupt and hasattr(tts, "stop"):
                try:
                    tts.stop()
                except Exception as exc:
                    logger.warning("[ConversationKernel] TTS stop failed: %s", exc)
            from backend.agent.tts import OUTPUT_SAMPLE_RATE

            pipeline.play_stream(
                tts.synthesize_stream(text), sample_rate=OUTPUT_SAMPLE_RATE
            )
        except Exception as exc:
            logger.warning(
                "[ConversationKernel] TTS failed for utterance: %s", exc
            )

    def _on_utterance_chunk(self, payload) -> None:
        """Handle an utterance:chunk event.

        The speak tool emits START + DONE only (no incremental chunks), so
        this is a no-op. Kept for forward-compatibility with any future
        streaming emitter.
        """
        return

    def _on_utterance_done(self, payload) -> None:
        """Handle an utterance:done event.

        Playback is driven by the audio pipeline's play_stream, which owns
        its own queue/flush — nothing to do here.
        """
        return

    # ── Registration helpers (no new state machine) ────────────────

    def register_callbacks(self) -> None:
        """Register this kernel as an additional observer on the
        existing VoiceCommandHandler.

        The voice_handler accepts a single callable per callback.
        Per plan §Fix #15, we use the "wrap existing callback" approach
        IF a callback is already registered. If no callback is
        registered yet, we just register ourselves directly.
        """
        try:
            # The VoiceCommandHandler stores callbacks as
            # self._on_state_change and self._on_audio_level. If they
            # are already set (by iris_gateway), we wrap them. If not,
            # we set ourselves as the primary callback.
            existing_state_cb = getattr(self._voice_handler, "_on_state_change", None)
            if (
                existing_state_cb is not None
                and existing_state_cb != self.on_voice_state
            ):
                # Wrap: call existing first, then our kernel observer
                wrapped = _CallbackChain(existing_state_cb, self.on_voice_state)
                self._voice_handler.set_state_callback(wrapped)
            else:
                self._voice_handler.set_state_callback(self.on_voice_state)

            existing_level_cb = getattr(self._voice_handler, "_on_audio_level", None)
            if (
                existing_level_cb is not None
                and existing_level_cb != self.on_audio_level
            ):
                wrapped = _CallbackChain(existing_level_cb, self.on_audio_level)
                self._voice_handler.set_audio_level_callback(wrapped)
            else:
                self._voice_handler.set_audio_level_callback(self.on_audio_level)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ConversationKernel] register_callbacks failed: %s", exc)


class _CallbackChain:
    """Wraps multiple observers into a single callable.

    VoiceCommandHandler.set_state_callback accepts ONE callable. If
    iris_gateway already registered a callback, we wrap both:
    existing first, then the kernel's observer. This is the
    "Option (b)" approach from plan §Fix #15 — zero changes to
    audio/voice_command.py.
    """

    def __init__(self, *callbacks):
        self._callbacks = list(callbacks)

    def __call__(self, *args, **kwargs):
        for cb in self._callbacks:
            try:
                cb(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                logger.debug("[CallbackChain] callback %r failed: %s", cb, exc)


# ── Singleton accessor (managed by iris_gateway) ─────────────────

_kernel_singleton: Optional[ConversationKernel] = None
_kernel_lock = threading.Lock()


def get_conversation_kernel() -> Optional[ConversationKernel]:
    """Return the active kernel, or None if not yet set."""
    return _kernel_singleton


def set_conversation_kernel(kernel: Optional[ConversationKernel]) -> None:
    """Set or clear the active kernel (called by iris_gateway)."""
    global _kernel_singleton
    with _kernel_lock:
        _kernel_singleton = kernel

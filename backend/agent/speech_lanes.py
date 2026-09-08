"""Speech lane engine — deterministic lane router + scheduler + observability.

Replaces flag/lock coordination of speech with a deterministic lane engine:
every utterance enters exactly one lane (NARRATION / REPLY / ALERT_CRITICAL /
ALERT_AWAITING) via a pure function of (trigger label, turn phase, content
shape, lane occupancy). No model call in the routing path (REQ-1 AC1.1).

Wave 1 (foundation, NO behavior change):
  * UtteranceNode model (design.md Data Models)
  * deterministic router + hierarchy table as data (REQ-1, REQ-3)
  * per-turn observability + tuning counters (REQ-9)
  * shadow-mode observer (REQ-9 AC9.3) — logs would-order, changes nothing

Wave 2 (cutover, strangler order):
  * SpeechScheduler — serialize/preempt/subsume via lane priority (REQ-2,
    REQ-4, REQ-5, REQ-7). One mouth: a single worker drains the priority
    queue; gates derive from running play-nodes.

This module imports nothing from phase_manager (vocabulary only) and nothing
heavy — pure stdlib, off the audio path.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("iris.agent.speech_lanes")

# ── Lanes (design.md D1/D9) ────────────────────────────────────────────────
NARRATION = "narration"
REPLY = "reply"
ALERT_CRITICAL = "alert_critical"
ALERT_AWAITING = "alert_awaiting"

LANES = (NARRATION, REPLY, ALERT_CRITICAL, ALERT_AWAITING)

# Lane priority for serialization (REQ-2 AC2.2): lower number = higher priority.
# ALERT_CRITICAL preempts all; ALERT_AWAITING survives boundaries; REPLY
# preempts narration; narration is lowest (subsumable, ephemeral).
LANE_PRIORITY: Dict[str, int] = {
    ALERT_CRITICAL: 0,
    ALERT_AWAITING: 1,
    REPLY: 2,
    NARRATION: 3,
}

# Default lane for unclassifiable triggers (design.md D4): fail-safe toward
# ephemerality — heard, never persisted as phantom history.
DEFAULT_LANE = NARRATION

# Node lifecycle states (design.md Data Models).
STATE_QUEUED = "queued"
STATE_READY = "ready"
STATE_PLAYING = "playing"
STATE_DONE = "done"
STATE_CANCELLED = "cancelled"
STATE_FAILED = "failed"
NODE_STATES = (STATE_QUEUED, STATE_READY, STATE_PLAYING, STATE_DONE,
               STATE_CANCELLED, STATE_FAILED)

# ── Watchdog + failure semantics (REQ-8, REQ-7 AC7.3) ──────────────────────
# Per-node play budget. Rationale (physical, not tuned-to-green): the longest
# legitimate per-node synthesis measured ~62 s (2500 chars on the real worker,
# pre-split-guard); the 2000-char sequential-split guard bounds nodes further.
# 120 s is ~2x headroom — a play call exceeding it is wedged, not slow.
NODE_WATCHDOG_TIMEOUT_S = 120.0
# A node whose queue wait already consumed its deadline still gets this floor,
# so queue wait alone can never wedge-fail a healthy node on the spot (it
# retries with a fresh deadline if it trips).
WATCHDOG_STALE_FLOOR_S = 0.2
# Watchdog poll granularity: how fast barge-in / preemption / stop preempts a
# play wait, and how soon past-deadline is noticed.
WATCHDOG_POLL_S = 0.05
# Cascading-failure trip: distinct dead nodes in one turn that drains the turn.
# Counts DISTINCT nodes, not attempts — one flaky node retrying once must not
# trip the drain by itself; three independently dead nodes means the lane is
# broken for this turn.
TURN_FAILURE_TRIP_COUNT = 3
# Failure-notice content kind — notices never retry and never raise notices.
FAILURE_NOTICE_KIND = "failure_notice"
FAILURE_NOTICE_TEXT = "Sorry — that reply didn't play. Continuing."

# ── Beat store (REQ-10, T13; design.md D10/D12) ────────────────────────────
# The scheduler queue IS the beat store: beats are immutable UtteranceNodes
# (kind planned|reactive); the agent amends via atomic ADD / REPLACE /
# CANCEL, each landing fully or rejected with a logged reason. Pending
# narration coalesces (burst merge); playing narration always finishes its
# sentence (AC10.10) — spacing is emergent, never timer-driven.
BEAT_MERGE_DEBOUNCE_S = 2.0  # burst window (UNVERIFIED — tune live via REQ-9)
BEAT_RECENT_OPENINGS = 8     # spoken-opening ring for the bounce check
BEAT_OPENING_WORDS = 5       # normalized opening = first N alnum words
NODE_REGISTRY_MAX = 128      # settled-node registry cap (replace reasons)
BOUNCED_OPENINGS_MAX = 64    # bounced-opening set cap
# Fixed companion vocabulary for wait narration (direction-level, no tool
# names, no mechanics — same class as the AC8.2 failure notice).
WAIT_ENTRY_TEXT = "This step takes a while — still working."
WAIT_MISS_TEXT = "Still on it — taking longer than expected."

# Narration-beat kinds (session-305): immutable nodes.
KIND_PLANNED = "planned"
KIND_REACTIVE = "reactive"


def _node_text(node: "UtteranceNode") -> str:
    """Spoken text carried by a node ("" for streaming queues)."""
    content = node.content or {}
    text = content.get("text", "")
    return text if isinstance(text, str) else ""


def _normalized_opening(text: str) -> str:
    """First BEAT_OPENING_WORDS alnum words, lowercased (AC10.12 matching)."""
    import re as _re

    return " ".join(_re.findall(r"[a-z0-9]+", text.lower())[:BEAT_OPENING_WORDS])


# ── Situation (router input) ───────────────────────────────────────────────
@dataclass(frozen=True)
class Situation:
    """Pure, serializable description of a speech trigger.

    The router is a pure function of these fields (REQ-1 AC1.1). `trigger_label`
    is the L1 explicit caller label when present; `turn_phase` and
    `content_shape` feed the L2/L3 rules; `lane_occupancy` is the set of lanes
    currently holding utterances (used for FIFO/priority tie-breaks and future
    rules). No field is derived from a model call.
    """

    trigger_label: Optional[str] = None   # L1 explicit caller label
    source: str = "unknown"               # ws | voice | tool | dashboard
    turn_phase: Optional[str] = None      # active | idle | awaiting | turn_end
    content_shape: Optional[str] = None   # prose|table|diagram|code|conversation|artifact|unknown
    lane_occupancy: Tuple[str, ...] = ()  # lanes currently holding utterances

    def as_dict(self) -> Dict[str, Any]:
        return {
            "trigger_label": self.trigger_label,
            "source": self.source,
            "turn_phase": self.turn_phase,
            "content_shape": self.content_shape,
            "lane_occupancy": list(self.lane_occupancy),
        }


@dataclass(frozen=True)
class RoutingDecision:
    """Result of routing a Situation to a lane (REQ-1 AC1.3: recorded)."""

    lane: str
    rule_fired: str          # e.g. "L1:explicit:reply" | "L4:default"
    inputs: Dict[str, Any]   # snapshot of the situation for observability


# ── Hierarchy table as data (REQ-3) ────────────────────────────────────────
# The table is DATA, not code branches: the router iterates it in order and
# returns the first matching rule's lane. New rules land by appending a row —
# the router never changes. Precedence: L1 explicit label > L2 turn-phase rule
# > L3 content-shape rule > L4 default lane (narration).
@dataclass(frozen=True)
class HierarchyRule:
    level: int                       # 1..4
    name: str                        # stable rule id (observability key)
    predicate: Callable[[Situation], bool]
    lane: str


def _label_is(lane: str) -> Callable[[Situation], bool]:
    return lambda s: s.trigger_label == lane


def _phase_is(phase: str) -> Callable[[Situation], bool]:
    return lambda s: s.turn_phase == phase


def _shape_in(shapes: Tuple[str, ...]) -> Callable[[Situation], bool]:
    return lambda s: s.content_shape in shapes


# L1 — explicit caller label wins (REQ-3 AC3.1). Conflicting labels are
# resolved by the originating caller's label; the conflict is logged as a
# warning by the router (see route()).
_L1_RULES = [
    HierarchyRule(1, "L1:explicit:reply", _label_is(REPLY), REPLY),
    HierarchyRule(1, "L1:explicit:alert_critical", _label_is(ALERT_CRITICAL), ALERT_CRITICAL),
    HierarchyRule(1, "L1:explicit:alert_awaiting", _label_is(ALERT_AWAITING), ALERT_AWAITING),
    HierarchyRule(1, "L1:explicit:narration", _label_is(NARRATION), NARRATION),
]

# L2 — turn-phase rules (REQ-3 AC3.1). An utterance arriving while the system
# awaits a user decision is an awaiting alert; an utterance at turn end is
# progress chatter that dies with the turn (narration).
_L2_RULES = [
    HierarchyRule(2, "L2:phase:awaiting", _phase_is("awaiting"), ALERT_AWAITING),
    HierarchyRule(2, "L2:phase:turn_end", _phase_is("turn_end"), NARRATION),
]

# L3 — content-shape rules (REQ-3 AC3.1). Artifacts (table/diagram/code) are
# described, never recited → ephemeral narration. A conversational line is a
# reply.
_L3_RULES = [
    HierarchyRule(3, "L3:shape:artifact", _shape_in(("table", "diagram", "code")), NARRATION),
    HierarchyRule(3, "L3:shape:conversation", _shape_in(("conversation", "prose")), REPLY),
]

# L4 — default lane (REQ-3 AC3.3): no usable label/phase/shape → narration.
_L4_DEFAULT = HierarchyRule(4, "L4:default", lambda s: True, DEFAULT_LANE)

HIERARCHY_TABLE: Tuple[HierarchyRule, ...] = (
    *_L1_RULES,
    *_L2_RULES,
    *_L3_RULES,
    _L4_DEFAULT,
)


def route(situation: Situation) -> RoutingDecision:
    """Assign a Situation to exactly one lane (REQ-1 AC1.1, REQ-3 AC3.1).

    Pure function: no model call, no I/O, O(len(HIERARCHY_TABLE)) — never
    blocks synthesis start (REQ-7 AC7.4). Returns the first matching rule's
    lane. If the router itself throws, the caller falls back to the default
    lane (narration) rather than dropping speech (REQ-1 edge case).
    """
    inputs = situation.as_dict()
    for rule in HIERARCHY_TABLE:
        try:
            if rule.predicate(situation):
                return RoutingDecision(lane=rule.lane, rule_fired=rule.name, inputs=inputs)
        except Exception as exc:  # noqa: BLE001 — a bad rule never drops speech
            logger.warning(
                "[speech_lanes] rule %s predicate failed: %s", rule.name, exc
            )
            continue
    # Unreachable (L4 default always matches), but keep the contract explicit.
    return RoutingDecision(lane=DEFAULT_LANE, rule_fired=_L4_DEFAULT.name, inputs=inputs)


# ── UtteranceNode (design.md Data Models) ──────────────────────────────────
@dataclass
class UtteranceNode:
    """One utterance in a lane. Immutable content; engine transitions state.

    `priority` is lane-derived (LANE_PRIORITY), never caller-supplied (REQ-1
    AC1.2). `persist` is lane-derived: replies/alerts persist, narration does
    not (design.md D7). Narration beats carry `kind` (planned|reactive) and an
    optional `audio_ref` for the Wave-4 synthesize-and-hold buffer.
    """

    id: str
    lane: str
    trigger: Dict[str, Any]      # {source, label, rule_fired} — L1..L4 provenance
    turn_id: str
    session_id: str
    content: Dict[str, Any]      # {kind, text/show-ref} — shaped spoken line + shown anchor
    persist: bool = False        # lane-derived (set in __post_init__)
    state: str = STATE_QUEUED
    priority: int = 0            # lane-derived
    enqueued_at: float = 0.0
    deadline: float = 0.0        # node watchdog (stuck detection, Wave 3)
    attempts: int = 0            # play tries so far (AC8.3: at most one retry)
    kind: Optional[str] = None   # "planned" | "reactive" (narration only)
    audio_ref: Optional[str] = None  # synthesize-and-hold buffer ref (Wave 4)

    def __post_init__(self) -> None:
        if self.lane not in LANES:
            raise ValueError(f"unknown lane: {self.lane!r}")
        if self.state not in NODE_STATES:
            raise ValueError(f"unknown state: {self.state!r}")
        if self.kind is not None and self.kind not in (KIND_PLANNED, KIND_REACTIVE):
            raise ValueError(f"unknown narration kind: {self.kind!r}")
        self.priority = LANE_PRIORITY[self.lane]
        self.persist = self.lane in (REPLY, ALERT_CRITICAL, ALERT_AWAITING)
        if not self.enqueued_at:
            self.enqueued_at = time.time()


def build_node(
    situation: Situation,
    decision: RoutingDecision,
    *,
    turn_id: str,
    session_id: str,
    content: Optional[Dict[str, Any]] = None,
    kind: Optional[str] = None,
) -> UtteranceNode:
    """Construct an UtteranceNode from a routed Situation (REQ-1 AC1.3).

    Records the routing decision (inputs + chosen lane) on the node's trigger
    provenance for observability.
    """
    node = UtteranceNode(
        id=f"utt_{uuid.uuid4().hex[:8]}",
        lane=decision.lane,
        trigger={
            "source": situation.source,
            "label": situation.trigger_label,
            "rule_fired": decision.rule_fired,
            "inputs": decision.inputs,
        },
        turn_id=turn_id or "unknown",
        session_id=session_id or "unknown",
        content=content or {"kind": "text", "text": ""},
        kind=kind,
    )
    # Wire the node watchdog (REQ-8, REQ-7 AC7.3): the play phase must finish
    # before enqueued_at + budget, or the scheduler fails the node and frees
    # the derived gates.
    node.deadline = node.enqueued_at + NODE_WATCHDOG_TIMEOUT_S
    return node


# ── Observability (REQ-9) ──────────────────────────────────────────────────
class SpeechCounters:
    """Named tuning counters (REQ-9 AC9.2): L2–L4 hierarchy hits and unlisted
    content types. Thread-safe (speech arrives from multiple threads)."""

    def __init__(self) -> None:
        self._counts: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def incr(self, name: str, n: int = 1) -> None:
        with self._lock:
            self._counts[name] += n

    def get(self, name: str) -> int:
        with self._lock:
            return self._counts.get(name, 0)

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counts)


class SpeechObservability:
    """Per-turn structured observability (REQ-9 AC9.1/AC9.2).

    Logs lane assignment, preemptions, subsumptions, shaping decisions, and
    node outcomes, each stamped with turn_id and session scope. Named counters
    feed the tuning loop (L2–L4 hits, unlisted content types). All writes are
    off the audio path (log after admission, never inline with synthesis).
    """

    def __init__(self, counters: Optional[SpeechCounters] = None) -> None:
        self._counters = counters or SpeechCounters()

    @property
    def counters(self) -> SpeechCounters:
        return self._counters

    def record_routing(
        self,
        decision: RoutingDecision,
        *,
        turn_id: str,
        session_id: str,
        source: str = "unknown",
    ) -> None:
        """Log a lane assignment + increment the L2–L4 counter (REQ-9 AC9.1/AC9.2)."""
        rule = decision.rule_fired
        if rule.startswith("L1"):
            pass  # explicit labels are not a tuning signal
        else:
            self._counters.incr(f"hierarchy:{rule}")
        logger.info(
            "SpeechLane route",
            extra={
                "context": "speech_lanes",
                "lane": decision.lane,
                "rule_fired": rule,
                "turn_id": turn_id or "unknown",
                "session_id": session_id or "unknown",
                "source": source,
                "inputs": decision.inputs,
            },
        )

    def record_unlisted_type(
        self, content_type: str, *, turn_id: str, session_id: str
    ) -> None:
        """Count an unlisted content type (REQ-6 AC6.4 extension feed, REQ-9 AC9.2)."""
        self._counters.incr(f"unlisted_type:{content_type}")
        logger.info(
            "SpeechLane unlisted_type",
            extra={
                "context": "speech_lanes",
                "content_type": content_type,
                "turn_id": turn_id or "unknown",
                "session_id": session_id or "unknown",
            },
        )

    def record_preemption(
        self, *, lane: str, turn_id: str, session_id: str, detail: str = ""
    ) -> None:
        self._counters.incr("preemption")
        logger.info(
            "SpeechLane preempt",
            extra={
                "context": "speech_lanes",
                "lane": lane,
                "turn_id": turn_id or "unknown",
                "session_id": session_id or "unknown",
                "detail": detail,
            },
        )

    def record_subsumption(
        self, *, lane: str, turn_id: str, session_id: str, detail: str = ""
    ) -> None:
        self._counters.incr("subsumption")
        logger.info(
            "SpeechLane subsume",
            extra={
                "context": "speech_lanes",
                "lane": lane,
                "turn_id": turn_id or "unknown",
                "session_id": session_id or "unknown",
                "detail": detail,
            },
        )

    def record_node_outcome(
        self, node: UtteranceNode, *, detail: str = ""
    ) -> None:
        self._counters.incr(f"node:{node.state}")
        logger.info(
            "SpeechLane node",
            extra={
                "context": "speech_lanes",
                "node_id": node.id,
                "lane": node.lane,
                "state": node.state,
                "turn_id": node.turn_id,
                "session_id": node.session_id,
                "detail": detail,
            },
        )

    def record_beat_event(
        self, kind: str, *, turn_id: str, session_id: str, detail: str = ""
    ) -> None:
        """Count a beat-store / wait event (REQ-10 tuning feed, T13).

        Kinds: beat_revision, beat_replace_rejected, beat_merged,
        beat_bounced, wait_entry, wait_miss, wait_exit.
        """
        self._counters.incr(f"beat:{kind}")
        logger.info(
            "SpeechLane beat",
            extra={
                "context": "speech_lanes",
                "event": kind,
                "turn_id": turn_id or "unknown",
                "session_id": session_id or "unknown",
                "detail": detail,
            },
        )


# ── Shadow-mode observer (REQ-9 AC9.3) ─────────────────────────────────────
class ShadowObserver:
    """Shadow-mode observer: logs would-order, changes nothing (design.md D3).

    Every speech intent registers here during shadow mode. The observer routes
    the Situation through the SAME pure router and logs the would-be lane, so
    divergences against actual behavior are measurable before cutover. It never
    alters playback, never enqueues, never blocks.
    """

    def __init__(
        self,
        observability: Optional[SpeechObservability] = None,
        enabled: bool = True,
    ) -> None:
        self._obs = observability or SpeechObservability()
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def observe(
        self,
        situation: Situation,
        *,
        turn_id: str,
        session_id: str,
        actual_lane: Optional[str] = None,
    ) -> RoutingDecision:
        """Route a Situation and log the would-be lane (shadow, no behavior change).

        If `actual_lane` is provided (the lane the caller actually used), a
        divergence is logged when it differs from the would-be lane.
        """
        if not self._enabled:
            # Still return the decision so callers can use it; just don't log.
            return route(situation)
        decision = route(situation)
        self._obs.record_routing(
            decision, turn_id=turn_id, session_id=session_id, source=situation.source
        )
        if actual_lane is not None and actual_lane != decision.lane:
            logger.info(
                "SpeechLane shadow_divergence",
                extra={
                    "context": "speech_lanes",
                    "would_lane": decision.lane,
                    "actual_lane": actual_lane,
                    "rule_fired": decision.rule_fired,
                    "turn_id": turn_id or "unknown",
                    "session_id": session_id or "unknown",
                    "inputs": decision.inputs,
                },
            )
        return decision


# ── Singleton accessors ────────────────────────────────────────────────────
_observability: Optional[SpeechObservability] = None
_observability_lock = threading.Lock()

_shadow_observer: Optional[ShadowObserver] = None
_shadow_observer_lock = threading.Lock()


def get_observability() -> SpeechObservability:
    """Process-wide observability singleton (thread-safe)."""
    global _observability
    if _observability is None:
        with _observability_lock:
            if _observability is None:
                _observability = SpeechObservability()
    return _observability


def get_shadow_observer() -> ShadowObserver:
    """Process-wide shadow observer singleton (thread-safe)."""
    global _shadow_observer
    if _shadow_observer is None:
        with _shadow_observer_lock:
            if _shadow_observer is None:
                _shadow_observer = ShadowObserver(observability=get_observability())
    return _shadow_observer


def reset_speech_lanes_for_testing() -> None:
    """Reset singletons — used by tests to get a fresh instance."""
    global _observability, _shadow_observer
    _observability = None
    _shadow_observer = None


def emit_speech_intent(
    *,
    source: str,
    turn_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trigger_label: Optional[str] = None,
    content_shape: Optional[str] = None,
    actual_lane: Optional[str] = None,
) -> RoutingDecision:
    """Additive shadow hook for a speech intent (REQ-9 AC9.3, design.md D3).

    Called at every speech-intent site (the 4 `_speak_response` entries +
    SpeakTool). Routes the Situation through the shadow observer, which logs
    the would-be lane and any divergence from `actual_lane` — and changes
    NOTHING about playback. Returns the would-be RoutingDecision for callers
    that want it. Removable in one task: delete the call sites and this helper.
    """
    situation = Situation(
        trigger_label=trigger_label,
        source=source,
        content_shape=content_shape,
    )
    return get_shadow_observer().observe(
        situation,
        turn_id=turn_id or "unknown",
        session_id=session_id or "unknown",
        actual_lane=actual_lane,
    )


# ── Scheduler (REQ-2, REQ-4, REQ-5, REQ-7) ────────────────────────────────
class SpeechScheduler:
    """Serialize / preempt / subsume speech through lane priority (one mouth).

    A single worker thread drains a priority queue of UtteranceNodes ordered
    by lane priority (LANE_PRIORITY) then FIFO within equal priority (REQ-2
    AC2.2). Admission applies the lane contracts:

      * REPLY / ALERT_AWAITING admitted  -> cancel pending NARRATION unspoken
        (subsumption, REQ-4 AC4.2).
      * ALERT_CRITICAL admitted          -> preempt the running utterance
        immediately (REQ-4 AC4.3).
      * barge_in()                       -> cancel running + all pending, fresh
        turn (REQ-4 AC4.1).
      * cancel_turn(turn_id)             -> cancel NARRATION nodes for a turn
        (REQ-5 AC5.1); REPLY/ALERT_AWAITING survive (AC5.2/AC5.3).

    Gates derive from scheduler state (REQ-7 AC7.2): `is_playing()` is True
    while any play-node runs. The scheduler adds zero latency to first-audio
    (REQ-7 AC7.4): admission is O(1) queue ops off the synthesis path; the
    worker only pops when a node is ready.

    The scheduler is deliberately decoupled from TTS internals: it calls a
    `play` callable (synthesize+play) supplied by the caller, so tests inject
    a fake and the real path stays the existing tts_play machinery.
    """

    def __init__(
        self,
        play: Callable[[UtteranceNode], None],
        observability: Optional[SpeechObservability] = None,
        *,
        auto_start: bool = True,
        gate: Optional[Callable[[bool], None]] = None,
    ) -> None:
        self._play_fn = play
        self._obs = observability or get_observability()
        self._gate = gate
        self._queue: list[UtteranceNode] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._running: Optional[UtteranceNode] = None
        # Failure semantics (REQ-8): per-turn distinct dead-node ids (cascade
        # trip), turns that already got their one-breath notice (AC8.2 cap),
        # turns drained by the cascade trip. Scoped by turn and cleaned on
        # turn end / barge-in, so the footprint stays bounded.
        self._turn_failed_nodes: Dict[str, set] = defaultdict(set)
        self._failure_notice_turns: set = set()
        self._drained_turns: set = set()
        # Beat store (REQ-10, T13 — the queue IS the store, design.md D10):
        # node registry for replace/cancel reasons (bounded), recent spoken
        # openings for the anti-repetition bounce (bounded ring), bounced
        # openings (one bounce each, bounded), live waits for miss detection.
        self._nodes: Dict[str, UtteranceNode] = {}
        self._recent_openings: deque = deque(maxlen=BEAT_RECENT_OPENINGS)
        self._bounced_openings: Dict[str, None] = {}
        self._waits: Dict[str, dict] = {}
        # Held-audio free callback (REQ-10 AC10.7, T14): wired by the kernel
        # to TTSManager.free_held. Every non-play exit of a node carrying an
        # audio_ref frees its held buffer through here (None in tests).
        self._audio_free = None
        if auto_start:
            self.start()

    def set_audio_free_callback(self, cb) -> None:
        """Register the held-buffer free callback (T14, AC10.7)."""
        self._audio_free = cb

    def _free_node_audio(self, node: UtteranceNode) -> None:
        """Free a node's held buffer, if any (all non-play exits)."""
        ref = getattr(node, "audio_ref", None)
        if ref and self._audio_free is not None:
            try:
                self._audio_free(ref)
            except Exception as exc:  # noqa: BLE001 — freeing never blocks lanes
                logger.debug("[speech_lanes] audio free skipped: %s", exc)

    # ── lifecycle ────────────────────────────────────────────────────
    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="speech-lane-scheduler"
        )
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)

    # ── admission (REQ-4) ────────────────────────────────────────────
    def admit(self, node: UtteranceNode) -> None:
        """Admit a node, applying subsumption/preemption, then enqueue."""
        with self._lock:
            # Subsumption: REPLY / ALERT_AWAITING cancel pending NARRATION.
            if node.lane in (REPLY, ALERT_AWAITING):
                self._cancel_pending_narration(node.turn_id)
            # Preemption: ALERT_CRITICAL stops the running utterance.
            if node.lane == ALERT_CRITICAL and self._running is not None:
                self._obs.record_preemption(
                    lane=node.lane,
                    turn_id=node.turn_id,
                    session_id=node.session_id,
                    detail=f"critical preempts running {self._running.id}",
                )
                self._running.state = STATE_CANCELLED
                self._free_node_audio(self._running)
                self._obs.record_node_outcome(self._running, detail="preempted")
                self._running = None
            node.state = STATE_QUEUED
            self._queue.append(node)
            self._queue.sort(key=lambda n: (LANE_PRIORITY[n.lane], n.enqueued_at))
            self._register_node(node)
        self._wake.set()

    def barge_in(self, *, turn_id: str, session_id: str) -> None:
        """Kill running + all pending; fresh turn (REQ-4 AC4.1)."""
        with self._lock:
            if self._running is not None:
                self._running.state = STATE_CANCELLED
                self._free_node_audio(self._running)
                self._obs.record_node_outcome(self._running, detail="barge-in")
                self._running = None
            for n in self._queue:
                n.state = STATE_CANCELLED
                self._free_node_audio(n)
                self._obs.record_node_outcome(n, detail="barge-in")
            self._queue.clear()
            self._obs.record_preemption(
                lane="*", turn_id=turn_id, session_id=session_id, detail="barge-in"
            )
            # Old turns are dead — drop their failure bookkeeping (REQ-8).
            self._turn_failed_nodes.clear()
            self._failure_notice_turns.clear()
            self._drained_turns.clear()
            # ...and their waits (REQ-10): a fresh turn re-announces its own.
            self._waits.clear()
            self._bounced_openings.clear()
        # Reopen the half-duplex mic gate immediately (REQ-7 AC7.2) so the new
        # turn's recording starts capturing without waiting for the worker to
        # observe the cancellation. The worker's finally block re-closes it
        # idempotently.
        self._set_gate(False)
        self._wake.set()

    def cancel_turn(self, turn_id: str) -> None:
        """Cancel NARRATION nodes for a turn (REQ-5 AC5.1). Replies/alerts survive."""
        with self._lock:
            kept: list[UtteranceNode] = []
            for n in self._queue:
                if n.lane == NARRATION and n.turn_id == turn_id:
                    n.state = STATE_CANCELLED
                    self._free_node_audio(n)
                    self._obs.record_node_outcome(n, detail="turn-end")
                else:
                    kept.append(n)
            self._queue = kept
            # The turn is over — drop its failure bookkeeping (REQ-8).
            self._turn_failed_nodes.pop(turn_id, None)
            self._failure_notice_turns.discard(turn_id)
            self._drained_turns.discard(turn_id)
            # ...and its waits (REQ-10, T13).
            self._waits = {
                wid: w for wid, w in self._waits.items()
                if w.get("turn_id") != turn_id
            }
        self._wake.set()

    def subsume_narration(self, *, turn_id: str, session_id: str) -> None:
        """Cancel pending NARRATION (REQ-4 AC4.2) — the subsumption side-effect
        of admitting a REPLY/ALERT_AWAITING, without enqueuing a node.

        Used by the reply paths (voice turn, agent DAG, dashboard) which keep
        their own contract-locked playback in `_speak_response` but must still
        silence pending narration the moment a reply is admitted. The running
        narration finishes its current sentence (AC4.4); only queued narration
        dies unspoken.
        """
        with self._lock:
            kept: list[UtteranceNode] = []
            for n in self._queue:
                if n.lane == NARRATION:
                    n.state = STATE_CANCELLED
                    self._free_node_audio(n)
                    self._obs.record_subsumption(
                        lane=n.lane,
                        turn_id=n.turn_id,
                        session_id=n.session_id,
                        detail=f"subsumed by reply (turn {turn_id})",
                    )
                    self._obs.record_node_outcome(n, detail="subsumed")
                else:
                    kept.append(n)
            self._queue = kept
        self._wake.set()

    # ── beat store: ADD / REPLACE / CANCEL (REQ-10, T13, design.md D10) ──
    def _register_node(self, node: UtteranceNode) -> None:
        """Track a node for replace/cancel reasons (bounded registry)."""
        self._nodes[node.id] = node
        while len(self._nodes) > NODE_REGISTRY_MAX:
            self._nodes.pop(next(iter(self._nodes)))

    def _check_bounce(self, text: str, *, turn_id: str, session_id: str) -> None:
        """Anti-repetition bounce (REQ-10 AC10.12): a newly authored beat whose
        normalized opening exactly matches a recently spoken beat is bounced
        back exactly once — then it speaks regardless (admission below always
        proceeds; the bounce is the logged signal, never a block)."""
        opening = _normalized_opening(text)
        if not opening or opening in self._bounced_openings:
            return
        with self._lock:
            recent = opening in self._recent_openings
        if not recent:
            return
        self._bounced_openings[opening] = None
        while len(self._bounced_openings) > BOUNCED_OPENINGS_MAX:
            self._bounced_openings.pop(next(iter(self._bounced_openings)))
        self._obs.record_beat_event(
            "beat_bounced", turn_id=turn_id, session_id=session_id,
            detail=f"opening {opening!r} repeats recent speech; admitted once",
        )

    def add_beat(
        self, text: str, *, turn_id: str, session_id: str, kind: str = KIND_PLANNED,
        audio_ref: Optional[str] = None,
    ) -> str:
        """ADD a narration beat (atomic: lands fully or not at all)."""
        text = (text or "").strip()
        if not text:
            raise ValueError("beat text must not be empty")
        self._check_bounce(text, turn_id=turn_id, session_id=session_id)
        situation = Situation(
            trigger_label=NARRATION, source="beat", content_shape="prose"
        )
        node = build_node(
            situation, route(situation), turn_id=turn_id or "unknown",
            session_id=session_id or "unknown",
            content={"kind": "text", "text": text}, kind=kind,
        )
        node.audio_ref = audio_ref  # pre-synthesized hold key, if any (T14)
        self.admit(node)
        return node.id

    def admit_reactive(
        self, text: str, *, turn_id: str, session_id: str, pivot: bool = False,
        audio_ref: Optional[str] = None,
    ) -> str:
        """Admit a live reactive line with burst merge (REQ-10 AC10.9).

        Findings arriving while the turn's youngest queued reactive is still
        inside the debounce window fold into ONE merged line (never N
        back-to-back utterances). Pivot-grade findings bypass the merge and
        admit immediately — still behind any playing node (AC10.10/D12).
        """
        text = (text or "").strip()
        if not text:
            raise ValueError("reactive text must not be empty")
        self._check_bounce(text, turn_id=turn_id, session_id=session_id)
        if not pivot:
            # Helper locks internally; a race (target played/cancelled
            # between lookup and replace) falls through to a fresh admit.
            target = self._youngest_pending_reactive(turn_id)
            if target is not None:
                merged = f"{_node_text(target)}; {text}"
                target_id = target.id
            if target is not None:
                new_id = self.replace_beat(
                    target_id, merged, turn_id=turn_id, session_id=session_id,
                )
                if new_id is not None:
                    self._obs.record_beat_event(
                        "beat_merged", turn_id=turn_id, session_id=session_id,
                        detail=f"folded into {target_id}",
                    )
                    return new_id
                # Target raced away (played/cancelled) — fall through to admit.
        situation = Situation(
            trigger_label=NARRATION, source="reactive", content_shape="prose"
        )
        node = build_node(
            situation, route(situation), turn_id=turn_id or "unknown",
            session_id=session_id or "unknown",
            content={"kind": "text", "text": text}, kind=KIND_REACTIVE,
        )
        node.audio_ref = audio_ref  # pre-synthesized hold key, if any (T14)
        self.admit(node)
        return node.id

    def _youngest_pending_reactive(self, turn_id: str) -> Optional[UtteranceNode]:
        """Youngest QUEUED reactive narration node of the turn inside the
        debounce window, or None. Caller must hold no lock (takes it)."""
        now = time.time()
        with self._lock:
            best: Optional[UtteranceNode] = None
            for n in self._queue:
                if (
                    n.lane != NARRATION
                    or n.turn_id != turn_id
                    or n.state != STATE_QUEUED
                    or n.kind != KIND_REACTIVE
                ):
                    continue
                if now - n.enqueued_at > BEAT_MERGE_DEBOUNCE_S:
                    continue
                if best is None or n.enqueued_at > best.enqueued_at:
                    best = n
            return best

    def replace_beat(
        self, beat_id: str, new_text: str, *, turn_id: str, session_id: str
    ) -> Optional[str]:
        """REPLACE = atomic cancel + add (design.md D10).

        Returns the new node id, or None with a logged reason when the target
        is already playing/spoken/dead (stale beats die; they are never
        resurrected or rewritten — engine transitions state, agent writes
        content).
        """
        new_text = (new_text or "").strip()
        if not new_text:
            raise ValueError("replacement text must not be empty")
        with self._lock:
            node = self._nodes.get(beat_id)
            queued = (
                node is not None
                and node.state == STATE_QUEUED
                and any(n is node for n in self._queue)
            )
            if node is not None and not queued:
                reason = (
                    "already playing" if node.state == STATE_PLAYING
                    else "already spoken" if node.state in (STATE_DONE, STATE_FAILED)
                    else "turn dead"
                )
                self._obs.record_beat_event(
                    "beat_replace_rejected", turn_id=turn_id,
                    session_id=session_id, detail=f"{beat_id}: {reason}",
                )
                return None
            if node is None:
                self._obs.record_beat_event(
                    "beat_replace_rejected", turn_id=turn_id,
                    session_id=session_id, detail=f"{beat_id}: unknown beat",
                )
                return None
            kind = node.kind or KIND_REACTIVE
            node.state = STATE_CANCELLED
            self._free_node_audio(node)
            self._obs.record_node_outcome(node, detail="replaced")
            self._queue = [n for n in self._queue if n is not node]
        self._obs.record_beat_event(
            "beat_revision", turn_id=turn_id, session_id=session_id,
            detail=f"{beat_id} replaced",
        )
        return self.add_beat(new_text, turn_id=turn_id, session_id=session_id, kind=kind)

    def cancel_beat(self, beat_id: str, *, turn_id: str, session_id: str) -> bool:
        """CANCEL a pending beat. False + logged reason when already gone."""
        with self._lock:
            node = self._nodes.get(beat_id)
            if (
                node is None
                or node.state != STATE_QUEUED
                or not any(n is node for n in self._queue)
            ):
                reason = "unknown beat" if node is None else (
                    "already playing" if node and node.state == STATE_PLAYING
                    else "already settled"
                )
                self._obs.record_beat_event(
                    "beat_replace_rejected", turn_id=turn_id,
                    session_id=session_id, detail=f"{beat_id}: {reason}",
                )
                return False
            node.state = STATE_CANCELLED
            self._free_node_audio(node)
            self._obs.record_node_outcome(node, detail="beat-cancelled")
            self._queue = [n for n in self._queue if n is not node]
            return True

    # ── wait-state triggers (REQ-10 AC10.11, T13) ─────────────────────
    def note_wait(
        self, wait_id: str, *, turn_id: str, session_id: str,
        budget_s: float, long_wait: bool,
    ) -> None:
        """Record a tool wait; known-long waits speak one entry line.

        Expectation-miss fires from the worker loop when the wait crosses its
        stated budget with no result (no timers — the existing 0.5s wake
        drives the check). Exit is silent (results voice via the reply path).
        """
        with self._lock:
            self._waits[wait_id] = {
                "deadline": time.time() + max(budget_s, 0.1),
                "turn_id": turn_id,
                "session_id": session_id,
                "missed": False,
            }
        self._obs.record_beat_event(
            "wait_entry", turn_id=turn_id, session_id=session_id,
            detail=f"{wait_id} budget={budget_s:g}s",
        )
        if long_wait:
            try:
                self.admit_reactive(
                    WAIT_ENTRY_TEXT, turn_id=turn_id, session_id=session_id,
                )
            except Exception as exc:  # noqa: BLE001 — narration never blocks waits
                logger.debug("[speech_lanes] wait entry line skipped: %s", exc)

    def end_wait(self, wait_id: str) -> None:
        """Close a wait (result arrived — results voice via the reply path)."""
        with self._lock:
            wait = self._waits.pop(wait_id, None)
        if wait is not None:
            self._obs.record_beat_event(
                "wait_exit", turn_id=wait.get("turn_id", ""),
                session_id=wait.get("session_id", ""),
                detail=wait_id,
            )

    def _check_waits(self) -> None:
        """Fire expectation-miss lines for waits past budget (worker loop)."""
        now = time.time()
        due: list = []
        with self._lock:
            for wait_id, wait in self._waits.items():
                if not wait.get("missed") and now >= wait.get("deadline", now):
                    wait["missed"] = True
                    due.append((wait_id, wait))
        for wait_id, wait in due:
            self._obs.record_beat_event(
                "wait_miss", turn_id=wait.get("turn_id", ""),
                session_id=wait.get("session_id", ""),
                detail=f"{wait_id} crossed stated budget",
            )
            try:
                self.admit_reactive(
                    WAIT_MISS_TEXT, turn_id=wait.get("turn_id", ""),
                    session_id=wait.get("session_id", ""),
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("[speech_lanes] wait miss line skipped: %s", exc)

    # ── derived gates (REQ-7 AC7.2) ──────────────────────────────────
    def _set_gate(self, active: bool) -> None:
        """Drive the half-duplex mic gate from scheduler state (REQ-7 AC7.2).

        The gate is DERIVED from the scheduler's running state: it is closed
        (active=True) while any play-node runs and reopened (active=False) when
        playback stops or barge-in kills the turn. The `gate` callable is wired
        by the kernel to `AudioEngine.set_tts_active`; a failure never blocks
        the scheduler worker (the pipeline's stall backstop still self-releases
        a wedged gate after _TTS_GATE_STALL_GRACE).
        """
        if self._gate is None:
            return
        try:
            self._gate(active)
        except Exception as exc:  # noqa: BLE001 — a gate failure never wedges speech
            logger.debug("[speech_lanes] gate(%s) failed: %s", active, exc)

    def is_playing(self) -> bool:
        with self._lock:
            return self._running is not None

    def running_lane(self) -> Optional[str]:
        with self._lock:
            return self._running.lane if self._running is not None else None

    def pending_count(self) -> int:
        with self._lock:
            return len(self._queue)

    # ── internals ────────────────────────────────────────────────────
    def _cancel_pending_narration(self, turn_id: str) -> None:
        """Cancel all queued NARRATION nodes (subsumption, REQ-4 AC4.2)."""
        kept: list[UtteranceNode] = []
        for n in self._queue:
            if n.lane == NARRATION:
                n.state = STATE_CANCELLED
                self._free_node_audio(n)
                self._obs.record_subsumption(
                    lane=n.lane,
                    turn_id=n.turn_id,
                    session_id=n.session_id,
                    detail=f"subsumed by reply (turn {turn_id})",
                )
                self._obs.record_node_outcome(n, detail="subsumed")
            else:
                kept.append(n)
        self._queue = kept

    def _pop_next(self) -> Optional[UtteranceNode]:
        with self._lock:
            if not self._queue:
                return None
            return self._queue.pop(0)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=0.5)
            self._wake.clear()
            if self._stop.is_set():
                break
            # Wait expectation-miss check rides the existing wake (REQ-10
            # AC10.11, T13) — no timers, no extra threads.
            self._check_waits()
            node = self._pop_next()
            if node is None:
                continue
            with self._lock:
                self._running = node
                node.state = STATE_PLAYING
                node.attempts += 1
            # Close the half-duplex mic gate while any play-node runs (REQ-7
            # AC7.2). The gate is derived from scheduler state, not manual
            # open/close calls at call sites.
            self._set_gate(True)
            outcome = self._play_with_watchdog(node)
            if outcome == "ok":
                node.state = STATE_DONE
                self._finish_node(node)
            elif outcome == "abandoned":
                # Barge-in / preemption / stop claimed the node mid-play and
                # already recorded its outcome — just clear the slot. The
                # orphaned play thread is a daemon: it dies with the process
                # and never touches node state again.
                with self._lock:
                    if self._running is node:
                        self._running = None
                self._set_gate(False)
            else:  # "failed" (raised) or "wedged" (past deadline)
                self._handle_node_failure(node, detail=outcome)

    def _play_with_watchdog(self, node: UtteranceNode) -> str:
        """Run the play callable with stuck detection (REQ-7 AC7.3, REQ-8).

        The play call runs in a daemon thread so a wedged call cannot pin the
        scheduler worker. Returns "ok" (played), "failed" (raised), "wedged"
        (past deadline), or "abandoned" (barge-in / preemption / stop claimed
        the node first — the claimer already recorded the outcome).
        """
        errors: list = []

        def _target() -> None:
            try:
                self._play_fn(node)
            except BaseException as exc:  # noqa: BLE001 — captured, handled below
                errors.append(exc)

        play_thread = threading.Thread(
            target=_target, daemon=True, name=f"speech-lane-play-{node.id}"
        )
        start = time.time()
        if node.deadline > 0:
            budget = node.deadline - start
        else:
            # Hand-built nodes predate the watchdog: full budget, not zero.
            budget = NODE_WATCHDOG_TIMEOUT_S
        budget = max(budget, WATCHDOG_STALE_FLOOR_S)
        play_thread.start()
        deadline = start + budget
        while play_thread.is_alive():
            if self._stop.is_set():
                return "abandoned"
            with self._lock:
                claimed = node.state != STATE_PLAYING
            if claimed:
                return "abandoned"
            if time.time() >= deadline:
                logger.warning(
                    "[speech_lanes] node %s wedged past watchdog (%.1fs); "
                    "failing node, freeing gates",
                    node.id,
                    budget,
                    extra={
                        "context": "speech_lanes",
                        "node_id": node.id,
                        "turn_id": node.turn_id,
                        "session_id": node.session_id,
                    },
                )
                return "wedged"
            play_thread.join(timeout=WATCHDOG_POLL_S)
        if errors:
            logger.warning(
                "[speech_lanes] node %s failed: %s",
                node.id,
                errors[0],
                extra={
                    "context": "speech_lanes",
                    "node_id": node.id,
                    "turn_id": node.turn_id,
                    "session_id": node.session_id,
                },
            )
            return "failed"
        return "ok"

    def _finish_node(self, node: UtteranceNode) -> None:
        """Clear a done node: free the derived gate, record the outcome."""
        self._set_gate(False)
        with self._lock:
            if self._running is node:
                self._running = None
            if node.state == STATE_DONE and node.lane == NARRATION:
                # Feed the anti-repetition ring (AC10.12) with spoken beats.
                self._recent_openings.append(_normalized_opening(_node_text(node)))
        self._obs.record_node_outcome(node)

    def _handle_node_failure(self, node: UtteranceNode, *, detail: str) -> None:
        """Fail a node, free gates, keep the turn going (REQ-8 AC8.1).

        Marks the node failed, frees the derived gates, then applies the
        failure semantics in order: cascade trip → retry-once → one-breath
        notice. The worker loop continues with the next node either way, so
        the turn proceeds visibly without the dead utterance.
        """
        node.state = STATE_FAILED
        self._set_gate(False)
        self._free_node_audio(node)
        with self._lock:
            if self._running is node:
                self._running = None
        self._obs.record_node_outcome(node, detail=detail)
        turn_id = node.turn_id
        with self._lock:
            self._turn_failed_nodes[turn_id].add(node.id)
            distinct_failures = len(self._turn_failed_nodes[turn_id])
        # Cascading failures (REQ-8 edge): 3+ DISTINCT dead nodes in one turn
        # drains the turn — it completes silently-visible, error logged once.
        if distinct_failures >= TURN_FAILURE_TRIP_COUNT:
            if turn_id not in self._drained_turns:
                self._drained_turns.add(turn_id)
                logger.warning(
                    "[speech_lanes] turn %s drained after %d distinct node failures",
                    turn_id,
                    distinct_failures,
                    extra={"context": "speech_lanes", "turn_id": turn_id},
                )
            self._drain_turn(turn_id)
            return
        # Retry-once (REQ-8 AC8.3): requeue on the next scheduler pass with a
        # fresh deadline, then drop. A wedged node costs at most one more
        # budget head-of-line before it drops. Failure notices never retry.
        if node.attempts <= 1 and node.content.get("kind") != FAILURE_NOTICE_KIND:
            node.state = STATE_QUEUED
            node.deadline = time.time() + NODE_WATCHDOG_TIMEOUT_S
            with self._lock:
                self._queue.append(node)
                self._queue.sort(key=lambda n: (LANE_PRIORITY[n.lane], n.enqueued_at))
            self._obs.record_node_outcome(node, detail="retrying")
            self._wake.set()
        # One-breath Critical cap (REQ-8 AC8.2): a REPLY/ALERT death speaks a
        # single short notice per turn — never a loop of failure announcements.
        if (
            node.lane in (REPLY, ALERT_CRITICAL, ALERT_AWAITING)
            and node.content.get("kind") != FAILURE_NOTICE_KIND
            and turn_id not in self._failure_notice_turns
        ):
            self._failure_notice_turns.add(turn_id)
            self.admit(self._build_failure_notice(node))

    def _drain_turn(self, turn_id: str) -> None:
        """Cancel all queued nodes for a turn (cascading-failure trip)."""
        with self._lock:
            kept: list[UtteranceNode] = []
            for n in self._queue:
                if n.turn_id == turn_id:
                    n.state = STATE_CANCELLED
                    self._free_node_audio(n)
                    self._obs.record_node_outcome(n, detail="turn-drained")
                else:
                    kept.append(n)
            self._queue = kept
        self._wake.set()

    def _build_failure_notice(self, node: UtteranceNode) -> UtteranceNode:
        """One-breath Critical notice for a dead REPLY/ALERT (REQ-8 AC8.2)."""
        return UtteranceNode(
            id=f"utt_failnotice_{uuid.uuid4().hex[:8]}",
            lane=ALERT_CRITICAL,
            trigger={
                "source": "scheduler",
                "label": ALERT_CRITICAL,
                "rule_fired": "watchdog:failure-notice",
            },
            turn_id=node.turn_id,
            session_id=node.session_id,
            content={"kind": FAILURE_NOTICE_KIND, "text": FAILURE_NOTICE_TEXT},
        )


# ── Content-aware spoken shaping (REQ-6) ──────────────────────────────────
# One resolver with fixed precedence (design.md D5): agent `speak` line >
# type-aware shaping > first-sentence fallback. Guarantees spoken ⊆ visible
# (AC6.3): every spoken utterance is derived from shown content — nothing
# invented, no raw full-text marathons, no mid-sentence clips.
#
# The type table is DATA (AC6.4): unlisted types fall back to describe-don't-
# recite and are logged for table extension.

# Content types the resolver understands (REQ-6 AC6.1).
TYPE_PROSE = "prose"
TYPE_TABLE = "table"
TYPE_DIAGRAM = "diagram"
TYPE_CODE = "code"
TYPE_HTML = "html"
TYPE_MARKDOWN = "markdown"
TYPE_TEXT = "text"

# Type-aware shaping: how each content type is spoken (AC6.1). Tables,
# diagrams, and code are described, never recited cell-by-cell / line-by-line.
_TYPE_SHAPING: Dict[str, str] = {
    TYPE_PROSE: "speak_generously",
    TYPE_TABLE: "describe",
    TYPE_DIAGRAM: "describe",
    TYPE_CODE: "describe",
    TYPE_HTML: "describe",
    TYPE_MARKDOWN: "speak_generously",
    TYPE_TEXT: "speak_generously",
}

# Sentence-boundary regex for the first-sentence fallback (AC6.3: no
# mid-sentence clips).
_SENTENCE_BOUNDARY = ".!?"


def _classify_content_type(show_format: Optional[str]) -> str:
    """Map a `show.format` value to a resolver content type (AC6.1).

    `show.format` carries markdown/table/diagram/html/text (REQ-6 Verified).
    Returns the canonical type; unknown formats fall through to the unlisted
    path (AC6.4).
    """
    f = (show_format or "").strip().lower()
    if f in ("table",):
        return TYPE_TABLE
    if f in ("diagram", "mermaid", "graph"):
        return TYPE_DIAGRAM
    if f in ("code", "python", "javascript", "json", "yaml", "bash", "sql"):
        return TYPE_CODE
    if f in ("html",):
        return TYPE_HTML
    if f in ("markdown", "md"):
        return TYPE_MARKDOWN
    if f in ("text", "plain", "prose"):
        return TYPE_PROSE
    return f or TYPE_TEXT


def _first_sentence(text: str, max_words: int = 60) -> str:
    """First sentence(s) up to max_words, respecting sentence boundaries."""
    import re as _re

    cleaned = _re.sub(r"```[\s\S]*?```", "", text)
    cleaned = _re.sub(r"`[^`]+`", "", cleaned)
    cleaned = _re.sub(r"^#{1,6}\s+", "", cleaned, flags=_re.MULTILINE)
    cleaned = _re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", cleaned)
    cleaned = _re.sub(r"^\s*[-*•]\s+", "", cleaned, flags=_re.MULTILINE)
    cleaned = " ".join(cleaned.split())
    words = cleaned.split()
    if not words:
        return ""
    if len(words) <= max_words:
        return cleaned
    truncated = " ".join(words[:max_words])
    last_boundary = max(
        truncated.rfind(". "),
        truncated.rfind("! "),
        truncated.rfind("? "),
    )
    if last_boundary > 25:
        truncated = truncated[: last_boundary + 1]
    return truncated


def _describe_artifact(text: str) -> str:
    """Describe a table/diagram/code artifact without reciting it (AC6.1).

    Strips table pipes, code fences, and markdown, then takes the first
    sentence (≤ 40 words). The result is a SHORT summary derived from the
    shown content — never the full body, never raw cells/lines.
    """
    import re as _re

    cleaned = _re.sub(r"```[\s\S]*?```", "", text)
    cleaned = _re.sub(r"`[^`]+`", "", cleaned)
    # Strip table pipes and separators so cells aren't recited.
    cleaned = _re.sub(r"\|", " ", cleaned)
    cleaned = _re.sub(r"^[\s\-:]+$", "", cleaned, flags=_re.MULTILINE)
    cleaned = _re.sub(r"^#{1,6}\s+", "", cleaned, flags=_re.MULTILINE)
    cleaned = _re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", cleaned)
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return ""
    return _first_sentence(cleaned, max_words=40)


def resolve_spoken_text(
    *,
    shown_text: str,
    agent_speak: Optional[str] = None,
    show_format: Optional[str] = None,
    override_recite: bool = False,
    observability: Optional[SpeechObservability] = None,
) -> str:
    """Resolve the spoken line for shown content (REQ-6 AC6.2).

    Precedence (design.md D5):
      1. agent `speak` line — the agent's own TTS line wins (AC6.2).
      2. type-aware shaping — prose speaks generously; table/diagram/code are
         described, never recited (AC6.1).
      3. first-sentence fallback — short prose spoken verbatim; long content
         reduced to the first sentence(s) (AC6.3).

    `override_recite` (the "read it to me" override) beats the type table and
    recites the full shown text (AC6.4 edge case).

    Guarantees spoken ⊆ visible: the returned line is always derived from
    `shown_text` (or the agent's own line, which is itself shown content).
    """
    obs = observability or get_observability()
    if override_recite:
        return shown_text or ""
    if agent_speak and agent_speak.strip():
        return agent_speak.strip()
    content_type = _classify_content_type(show_format)
    if content_type not in _TYPE_SHAPING:
        # Unlisted type (AC6.4): describe-don't-recite + log for extension.
        obs.record_unlisted_type(content_type, turn_id="unknown", session_id="unknown")
        return _describe_artifact(shown_text)
    mode = _TYPE_SHAPING[content_type]
    if mode == "describe":
        return _describe_artifact(shown_text)
    # speak_generously: prose/markdown/text — first-sentence fallback.
    return _first_sentence(shown_text)
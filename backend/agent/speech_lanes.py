"""Speech lane engine — deterministic lane router + observability (Wave 1).

Replaces flag/lock coordination of speech with a deterministic lane router:
every utterance enters exactly one lane (NARRATION / REPLY / ALERT_CRITICAL /
ALERT_AWAITING) via a pure function of (trigger label, turn phase, content
shape, lane occupancy). No model call in the routing path (REQ-1 AC1.1).

Wave 1 scope (foundation, NO behavior change):
  * UtteranceNode model (design.md Data Models)
  * deterministic router + hierarchy table as data (REQ-1, REQ-3)
  * per-turn observability + tuning counters (REQ-9)
  * shadow-mode observer (REQ-9 AC9.3) — logs would-order, changes nothing

The scheduler (serialize/preempt/subsume), derived gates, and cutover live in
later waves. This module imports nothing from phase_manager (vocabulary only)
and nothing heavy — pure stdlib, off the audio path.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import defaultdict
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

# Narration-beat kinds (session-305): immutable nodes.
KIND_PLANNED = "planned"
KIND_REACTIVE = "reactive"


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
    return UtteranceNode(
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
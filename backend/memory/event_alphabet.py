"""The event alphabet of IRIS memory (docs/Design/EVENT_TAXONOMY.md, owner-approved 2026-09-30).

Layer 1 - ALPHABET: closed lattices. NEVER widen them: node chains hash sequences
written in this alphabet (specs/wormhole-aperture REQ-46 AC7), so a widened value
set silently invalidates every stored chain. Their sizes are pinned by
backend/tests/unit/test_event_alphabet.py. Three lattices are REUSED from code
that already owns them, never re-modelled here:
  cause   - FAULTLINE   backend/agent/tool_errors.FailureDimensions (27)
  outcome - envelope    backend/agent/tool_envelope.ExpectationDimensions (27)
  trigger - node reason backend/agent/nodes/outcome.Reason (closed enum)
Layer 2 - WORDS: an open label registry (register_event_label = a data edit).
Layer 3 - UNCLASSIFIED: unknown labels are kept, counted, and promotable.
"""
from __future__ import annotations

import hashlib
import logging
import math
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
# 2 (2026-10-18, owner-approved): x and y enter as the charge Q and the work volume, not
# raw step counts; the sector ROOT and the mode. Rows written under 1 keep their scheme
# (no bulk re-hash - Wormhole REQ-10 AC4).
HASH_SCHEME = 2

# ── Layer 1: the new closed lattices ────────────────────────────────────────
FAMILIES = frozenset({
    "intent", "control", "problem", "knowledge", "feedback",
    "delivery", "memory", "safety", "environment",
})
VALENCES = frozenset({"advances", "sets_back", "neutral"})
ACTORS = frozenset({"user", "agent", "tool", "world", "subagent"})
EVIDENCE = frozenset({
    "none", "claim", "verifier", "test", "completion", "user", "recurrence", "corroboration",
})
# Only these are OUTSIDE evidence: they gate chain genesis, landmark promotion
# and RL reward. claim (the model's own) and verifier (the system's own check)
# are inside evidence.
OUTSIDE_EVIDENCE = frozenset({"test", "completion", "user", "recurrence", "corroboration"})
# Who produced the LABEL. Only rule and user labels are facts; oracle and brain
# labels are guesses about the event (e.g. "this message was a confirmation").
LABEL_SOURCES = frozenset({"rule", "user", "oracle", "brain"})
TRUSTED_LABEL_SOURCES = frozenset({"rule", "user"})


def counts_as_outside_evidence(evidence: str, label_source: str) -> bool:
    """THE gate every decision that consumes evidence uses (chain genesis,
    landmark promotion, RL reward). An event is outside evidence only when its
    evidence kind is outside AND its label is a fact, not a model's guess - an
    Oracle-typed CONFIRMATION must never promote anything until the Oracle has
    earned enforcement (CLAUDE.md "the Oracle earns its jobs")."""
    return evidence in OUTSIDE_EVIDENCE and label_source in TRUSTED_LABEL_SOURCES


@dataclass(frozen=True)
class EventLabel:
    label: str
    family: str
    valence: str
    actor: str
    description: str


_LABELS: Dict[str, EventLabel] = {}
_UNKNOWN: Dict[str, int] = {}
_LOCK = threading.Lock()


def register_event_label(label: str, family: str, valence: str, actor: str,
                         description: str) -> EventLabel:
    """Layer 2 growth API. Refuses values outside the alphabet and duplicates."""
    if family not in FAMILIES:
        raise ValueError(f"family {family!r} is not in the alphabet")
    if valence not in VALENCES:
        raise ValueError(f"valence {valence!r} is not in the alphabet")
    if actor not in ACTORS:
        raise ValueError(f"actor {actor!r} is not in the alphabet")
    with _LOCK:
        if label in _LABELS:
            raise ValueError(f"event label {label!r} is already registered")
        spec = EventLabel(label, family, valence, actor, description)
        _LABELS[label] = spec
        _UNKNOWN.pop(label, None)
        return spec


def resolve_event_label(label: str) -> Optional[EventLabel]:
    """Layer 2 lookup; an unregistered label is counted (Layer 3) and returns None."""
    with _LOCK:
        spec = _LABELS.get(label)
        if spec is None:
            _UNKNOWN[label] = _UNKNOWN.get(label, 0) + 1
        return spec


def unknown_event_counts() -> Dict[str, int]:
    with _LOCK:
        return dict(_UNKNOWN)


def promote_unknown_event(label: str, family: str, valence: str, actor: str,
                          description: str) -> EventLabel:
    """Layer 3 -> Layer 2 after review: adds a NAME, never a new dimension value."""
    return register_event_label(label, family, valence, actor, description)


def registered_labels() -> Dict[str, EventLabel]:
    with _LOCK:
        return dict(_LABELS)


_SEED = [
    # intent
    ("GOAL_SET", "intent", "neutral", "user", "the user states a goal"),
    ("GOAL_REFINED", "intent", "neutral", "user", "the user changes or narrows the goal"),
    ("CLARIFY_ASKED", "intent", "neutral", "agent", "the agent asks what the user means"),
    ("CLARIFY_ANSWERED", "intent", "advances", "user", "the user answers a clarification"),
    ("PREFERENCE_STATED", "intent", "neutral", "user", "a standing preference (always/never)"),
    ("GOAL_ABANDONED", "intent", "sets_back", "user", "the user drops the goal"),
    # control
    ("PLAN_MADE", "control", "neutral", "agent", "a plan for the goal"),
    ("REPLAN", "control", "neutral", "agent", "the plan changes after a result"),
    ("PIVOT", "control", "neutral", "agent", "deviation from a chain or plan (NodeChains REQ-21)"),
    ("SPLIT", "control", "neutral", "agent", "a step fans out into children"),
    ("DELEGATED", "control", "neutral", "agent", "work handed to a subagent"),
    ("ESCALATED", "control", "neutral", "agent", "the agent asks the user to decide"),
    ("HALTED", "control", "sets_back", "agent", "the loop stops (e.g. TOPO_VIOLATION)"),
    ("BUDGET_HIT", "control", "sets_back", "world", "a time, token or step budget ran out"),
    # problem (BUG/FIX are the coding words of OBSTACLE/RESOLUTION)
    ("OBSTACLE", "problem", "sets_back", "world", "something blocks progress"),
    ("BUG", "problem", "sets_back", "tool", "a code or test failure (coding OBSTACLE)"),
    ("ATTEMPT", "problem", "neutral", "agent", "an unverified try at an open problem"),
    ("DEAD_END", "problem", "sets_back", "agent", "a try that failed (negative marker)"),
    ("RESOLUTION", "problem", "advances", "agent", "a verified step resolves the problem"),
    ("FIX", "problem", "advances", "agent", "a verified code fix (coding RESOLUTION)"),
    ("VERIFIED_RESOLUTION", "problem", "advances", "world", "outside evidence confirms a resolution"),
    ("VERIFIED_FIX", "problem", "advances", "world", "outside evidence confirms a fix"),
    # knowledge
    ("OBSERVED", "knowledge", "neutral", "tool", "a page, screen, file or result was observed"),
    ("CLAIM_CORROBORATED", "knowledge", "advances", "world", "a prior claim is supported again"),
    ("CLAIM_UPDATED", "knowledge", "neutral", "world", "a claim's value changed"),
    ("CLAIM_CONTRADICTED", "knowledge", "sets_back", "world", "evidence contradicts a claim"),
    ("SOURCE_UNRELIABLE", "knowledge", "sets_back", "world", "a source is walled or wrong"),
    ("BELIEF_STALE", "knowledge", "neutral", "world", "a belief needs a re-check"),
    # feedback
    ("CONFIRMATION", "feedback", "advances", "user", "the user confirms a result"),
    ("CORRECTION", "feedback", "sets_back", "user", "the user corrects the agent"),
    ("CORRECTION_UNDONE", "feedback", "neutral", "user", "the user undid one of their memory corrections"),
    ("APPROVAL", "feedback", "advances", "user", "the user approves an action"),
    ("DENIAL", "feedback", "sets_back", "user", "the user refuses an action"),
    ("NO_RESPONSE", "feedback", "neutral", "user", "a question timed out"),
    # delivery
    ("ANSWER_GIVEN", "delivery", "advances", "agent", "a reply reached the user"),
    ("ARTIFACT_PRODUCED", "delivery", "advances", "agent", "a document/card/file was produced"),
    ("NARRATED", "delivery", "neutral", "agent", "speech was produced"),
    ("CARD_SHOWN", "delivery", "neutral", "agent", "a UI card was shown"),
    # memory
    ("RECALL_DELIVERED", "memory", "neutral", "agent", "memory entered the context"),
    ("RECALL_USED", "memory", "neutral", "agent", "a delivered recall was used (outcome pending)"),
    ("RECALL_HELPED", "memory", "advances", "agent", "a used recall led to a resolved outcome"),
    ("RECALL_MISLED", "memory", "sets_back", "agent", "a used recall led to a failure"),
    ("RECALL_MISSED", "memory", "sets_back", "agent", "memory existed but was not delivered"),
    ("APERTURE_DROPPED", "memory", "neutral", "agent", "a candidate expired or was dropped"),
    ("OFFLOADED", "memory", "neutral", "agent", "a block left the live view (placeholder kept)"),
    ("RESTRETCHED", "memory", "neutral", "agent", "an offloaded block was re-expanded"),
    ("PREMATURE_EVICTION", "memory", "sets_back", "agent", "an offloaded block was needed"),
    ("LESSON", "memory", "neutral", "agent", "a model-authored candidate lesson"),
    ("LANDMARK_PROMOTED", "memory", "advances", "world", "outside evidence promoted a landmark"),
    ("LANDMARK_STALE", "memory", "neutral", "world", "a landmark dependency changed"),
    ("LANDMARK_DEMOTED", "memory", "sets_back", "world", "a landmark was contradicted"),
    # Kyudo integrity pass (integrity.py): the memory cleans itself; evidence stays "none"
    ("LANDMARK_DISSOLVED", "memory", "sets_back", "agent", "a landmark lost its credibility or its coordinates and was absorbed (row kept)"),
    ("LANDMARK_MERGED", "memory", "neutral", "agent", "duplicate landmarks were absorbed into a survivor"),
    # the user's own forget (POST /api/memory/correct): absorbed with the reason "forgotten by you", row kept
    ("CLAIM_FORGOTTEN", "memory", "sets_back", "user", "the user told IRIS to forget a claim; it is absorbed, the row is kept"),
    # the user's own pin / strand corrections (corrections.py): each event holds the prior state, so an undo needs no table
    ("PIN_CORRECTED", "memory", "neutral", "user", "the user pinned, unpinned, held or released a pin"),
    ("STRAND_LEARNING_FORGOTTEN", "memory", "sets_back", "user", "the user told IRIS to forget what it learned in a strand; recall leaves the strand out"),
    ("STRAND_PURGED", "memory", "sets_back", "user", "the user removed the text of a strand's memory rows; ids and links stay"),
    ("MEMORY_PRUNED", "memory", "sets_back", "agent", "orphan or dangling memory rows were removed or re-pointed"),
    ("CHAIN_CREATED", "memory", "advances", "agent", "a node chain crystallized"),
    ("CHAIN_VARIANT", "memory", "advances", "agent", "a proven pivot became a variant"),
    # sectors (MEMORY-INTERFACE Part II 5.1, SHADOW): computed and logged, read by nothing
    ("SECTOR_BORN", "memory", "neutral", "agent", "a candidate sector was born from a recurring term"),
    ("SECTOR_PROVEN", "memory", "advances", "world", "outside evidence closed a candidate sector"),
    ("SECTOR_SPLIT", "memory", "neutral", "agent", "a sector whose outcomes disagree grew a child"),
    ("SECTOR_MERGED", "memory", "neutral", "agent", "two sectors merged; the absorbed key is an alias"),
    ("SECTOR_DISSOLVED", "memory", "sets_back", "agent", "a candidate sector expired and folded into its parent"),
    # strand tombstones (MEMORY-SURFACE-BUILD section 4, cases 1/2/8). Family "memory", not
    # "environment": a tombstone is the memory keeping what chat is about to lose (the
    # strand's title lives only in conversations.db), like OFFLOADED keeps its placeholder.
    # Actor "user": the user deleted or renamed it in chat. Written by
    # memory_events.record_strand_tombstone.
    ("STRAND_DELETED", "memory", "neutral", "user", "a conversation was deleted in chat; the tombstone keeps its title"),
    ("STRAND_RENAMED", "memory", "neutral", "user", "a conversation was renamed in chat; the tombstone keeps the old title"),
    # safety
    ("UNSAFE_REFUSED", "safety", "neutral", "agent", "an unsafe action was refused"),
    ("ESCALATED_UNSURE", "safety", "neutral", "agent", "an unsure action was put to the user"),
    ("INJECTION_SUSPECTED", "safety", "sets_back", "world", "untrusted text carried instructions"),
    ("PERMISSION_DENIED", "safety", "sets_back", "world", "policy refused an action"),
    # environment
    ("DEPENDENCY_CHANGED", "environment", "neutral", "world", "something knowledge depends on changed"),
    ("RESOURCE_LIMIT", "environment", "sets_back", "world", "a rate limit or resource ran out"),
    ("WORLD_CHANGED", "environment", "neutral", "world", "the observed world changed"),
]
for _row in _SEED:
    register_event_label(*_row)


# ── Wormhole REQ-1: the exact state address, computed at write time ─────────

_Q_EDGES = (-0.6, -0.2, 0.2, 0.6)   # 5 charge bins: lone antikink .. balanced .. lone kink
_V_MAX = 5                         # work volume bins: floor(log2(1 + x + y)), capped
_UNHASHABLE = {"count": 0}         # NaN / inf coordinates seen (a poisoned address is worse than none)


def quantize_state(sigma: Optional[str]) -> Optional[Tuple[int, int, int, int]]:
    """Quantize a ``format_coords`` text "x,y,xi,u" into (q_bin, v_bin, xi_bin, u_bin).

    x and y are step COUNTS, so they never enter raw (a raw count makes every step a new
    address). They enter as the STATE they imply: the topological charge
    Q = (x - y) / (x + y + 1) (docs/CADUCEAN_TECHNICAL_OVERVIEW.md section 5), binned
    in 5, and the work volume x + y on a log2 scale, capped. xi is binned to eighths of a
    turn, u to quarters on [-1, 1]. None when the coordinate is unknown or not finite
    (Wormhole REQ-1 edge case: written unhashed, logged, counted)."""
    if not sigma:
        return None
    try:
        x, y, xi, u = (float(v) for v in str(sigma).split(","))
    except Exception:  # noqa: BLE001 - not a coordinate (e.g. "rest:input:1")
        return None
    if not all(math.isfinite(v) for v in (x, y, xi, u)):
        _UNHASHABLE["count"] += 1
        logger.warning("[event_alphabet] non-finite sigma %r: written unhashed (seen %d)",
                       sigma, _UNHASHABLE["count"])
        return None
    x, y = max(x, 0.0), max(y, 0.0)
    q = (x - y) / (x + y + 1.0)
    q_bin = sum(q >= e for e in _Q_EDGES)
    v_bin = min(_V_MAX, int(math.log2(1.0 + x + y)))
    xi_bin = int((xi % (2 * math.pi)) // (math.pi / 4))
    u_bin = int(min(max(u, -1.0), 0.999) // 0.25)
    return q_bin, v_bin, xi_bin, u_bin


def sector_root(topic_domain: Optional[str]) -> str:
    """The top-level sector of a (possibly layered) sector key: "systems/memory" ->
    "systems". Addresses use the root so refining a sector never moves an address."""
    return (topic_domain or "-").split("/", 1)[0] or "-"


def hash_signature(sigma: Optional[str], exec_domain: Optional[str],
                   topic_domain: Optional[str]) -> Optional[str]:
    """Deterministic exact-match address of the quantized state + mode + sector root
    (scheme HASH_SCHEME; Wormhole REQ-1). None when the state is unknown or not finite -
    an unknown state has no address (never a stand-in)."""
    qs = quantize_state(sigma)
    if qs is None:
        return None
    key = f"s{HASH_SCHEME}|q{qs[0]}|v{qs[1]}|x{qs[2]}|u{qs[3]}|{exec_domain or '-'}|{sector_root(topic_domain)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


HEX_SCHEME = 1


def hex_bin_id(sigma: Optional[str], exec_domain: Optional[str],
               topic_domain: Optional[str]) -> Optional[str]:
    """The hex cell of the same quantized state (Wormhole REQ-2 AC1), minted at write
    time; Tier-1b neighbour lookups stay deferred (REQ-2 AC6). The (xi, u) plane is laid
    on a pointy-top hex grid of 8 columns x 8 rows; the charge, volume, mode and sector
    root are the layer the grid sits in. Readable, not hashed, so a later Tier-1b query
    can compute the six neighbours from the id."""
    qs = quantize_state(sigma)
    if qs is None:
        return None
    xi, u = (float(v) for v in str(sigma).split(",")[2:4])   # finite: quantize_state checked
    px =(xi % (2 * math.pi)) / (2 * math.pi) * 8 * math.sqrt(3)
    py = (min(max(u, -1.0), 1.0) + 1.0) / 2.0 * 8 * 1.5
    aq = (math.sqrt(3) / 3 * px - py / 3)
    ar = 2.0 / 3.0 * py
    # cube rounding: deterministic tie-break (Wormhole REQ-2 boundary rule)
    cx, cz = aq, ar
    cy = -cx - cz
    rx, ry, rz = round(cx), round(cy), round(cz)
    dx, dy, dz = abs(rx - cx), abs(ry - cy), abs(rz - cz)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry
    return f"h{HEX_SCHEME}|q{qs[0]}|v{qs[1]}|{int(rx)},{int(rz)}|{exec_domain or '-'}|{sector_root(topic_domain)}"

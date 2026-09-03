"""
Semantic Logic Gate — DAG-routed, ontology-grounded intent classification.

Replaces the legacy rule router in ``backend/agent/agent_kernel.py``
(``_classify_intent`` :1885-1927, ``_needs_planning`` :1928-1955) with a
multi-dimensional semantic routing engine:

* **Tier 0** — deterministic command fast-path (migrated rule sets, <1ms)
* **Tier 2** — ontology neighborhood + context filter (coordinate-graph recall)

The gate compiles every turn into a :class:`DAGPlanGraph` of capability lanes
(16 lanes across 5 ``IntentDomain`` values). The only boolean output is the
derived efficiency flag ``requires_der_kernel``. Routing is rules (Tier 0) +
coordinates (Tier 2) + the continuation lens (REQ-4) — the neural embedding
tier (Tier 1) was REMOVED: the gate routes on the app's coordinate-graph
memory, not vector search.

Import/provenance discipline (REQ-6 AC1): all ontology constants are IMPORTED
from their CI-pinned source modules — ``DOMAIN_IDS`` (spaces.py:89),
``LINK_VOCABULARY`` (pin_store.py:61), ``BACKEND_LFM`` provenance id
(embedding.py:47). ``embedding.py`` imports no heavy ML libraries at module
level (its neural backends load lazily inside ``_load_active_backend``), so
importing here is lazy-safe. Node-type values have no exported constant
upstream (they are pinned by ``scripts/validate_ontology_schema.py`` against
``NodeRecord.node_type`` in der_loop.py); ``NODE_TYPES`` is the pinned set and
the provenance test (T13) asserts it matches the CI pin.

``FOLLOWUP_SIM_THRESHOLD`` (REQ-4 continuation alignment) is an INITIAL value
per the Decisions Locked in specs/semantic-logic-gate/; it changes only against
the measured T13 benchmark numbers, with the reason written in a comment next
to the number.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Sequence

# Registry-backed constants — imported, never hardcoded (REQ-6 AC1).
# All three source modules are lazy-safe at import time (no ML init).
from backend.memory.embedding import BACKEND_LFM
from backend.memory.mycelium.spaces import DOMAIN_IDS
from backend.memory.pin_store import LINK_VOCABULARY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# REQ-6 AC2 (T9) — bounded, latched, background LFM warm-up
# ---------------------------------------------------------------------------

_warm_start_lock = threading.Lock()
_warm_start_done = False


def warm_up_lfm() -> threading.Thread:
    """REQ-6 AC2 (T9): pre-warm the LFM backend in a background daemon thread
    so the first user turn runs at warm latency.

    Bounded: the probe encode rides ``EmbeddingService._load_active_backend``,
    which is itself bounded by ``IRIS_EMBEDDING_LOAD_TIMEOUT_S``
    (embedding.py:74-82) and falls back to hash on timeout.
    Latched: the service's model load is latched — a later encode reuses it.
    Never blocks startup: returns immediately after spawning the daemon.
    A failed warm-up is NOT an error — the gate's normal degraded (cold) path
    takes over, exactly as if no warm-up had run.
    """
    def _task() -> None:
        try:
            from backend.memory.embedding import get_embedding_service

            svc = get_embedding_service()
            svc.encode("IRIS semantic logic gate warm-up probe")
            logger.info("[SemanticGate] LFM backend warm (first turn runs warm)")
        except Exception as exc:
            logger.debug("[SemanticGate] LFM warm-up failed (cold path remains): %s", exc)

    t = threading.Thread(target=_task, daemon=True, name="iris-lfm-warmup")
    t.start()
    return t


def ensure_warm_start() -> None:
    """Fire the LFM warm-up at most once per process (latched, REQ-6 AC2).

    Called from kernel/startup initialization; returns immediately. The latch
    is claimed synchronously so concurrent kernel inits spawn a single thread.
    """
    global _warm_start_done
    if _warm_start_done:
        return
    with _warm_start_lock:
        if _warm_start_done:
            return
        _warm_start_done = True
        warm_up_lfm()

# ---------------------------------------------------------------------------
# TIER 0 — deterministic command fast-path (REQ-1, design.md "Tier 0
# short-circuit"). Migrated VERBATIM from AgentKernel (agent_kernel.py
# 1786-1883, 4540-4560) — _is_chitchat / _ACTION_VERBS / _FOLLOWUP_MARKERS /
# _ANAPHORA_PRONOUNS / _is_followup_to_task / _is_web_search_request. Logic is
# identical; names are adapted to module scope. Most traffic resolves here at
# <1ms with zero model work. Do not "improve" these rules — they are pinned by
# test_universal_planning.py (W0.2) and equivalence-proven at T13.
# ---------------------------------------------------------------------------

CHITCHAT_PATTERNS = (
    "hi", "hello", "hey", "yo", "sup", "howdy", "hiya", "greetings",
    "good morning", "good afternoon", "good evening", "good night",
    "how are you", "how's it going", "how is it going", "how are things",
    "how have you been", "how's your day", "what's up", "whats up",
    "wassup", "what is up", "thanks", "thank you", "thx", "ty",
    "appreciate it", "appreciate that", "nice", "cool", "great", "awesome",
    "sweet", "lol", "haha", "hahaha", "lmao", "bye", "goodbye", "see you",
    "see ya", "cya", "talk later", "take care", "who are you", "what are you",
)

# Short acknowledgements / confirmations that are not task continuations.
CHITCHAT_ACKS = (
    "yes", "yeah", "yep", "yup", "no", "nope", "nah", "ok", "okay", "k",
    "sure", "maybe", "perhaps", "right", "correct", "of course", "got it",
    "gotcha", "alright", "fine", "agreed", "sounds good", "sure thing",
)

# Action/tool intent markers — prompts containing these need the DER
# planning/tool loop. Everything else (simple questions, factual lookups,
# conversation) takes the fast direct-response path.
#
# REQ-1 AC2 coverage: "test" and "look up" were added for compound-task
# prompts ("look up X from last session and test it in Y") — verified safe
# against the pinned test_universal_planning contract (W0.2): none of the 17
# chitchat / 5 question / 4 followup pinned inputs contain them.
ACTION_VERBS = (
    "search", "google", "lookup", "look up", "find", "open", "launch", "start",
    "create", "make", "build", "generate", "write", "send", "email",
    "message", "text", "call", "schedule", "remind", "set", "add",
    "delete", "remove", "update", "edit", "change", "list", "play", "show me",
    "book", "order", "buy", "download", "upload", "post", "tweet",
    "run", "execute", "deploy", "install", "configure", "toggle",
    "turn on", "turn off", "switch", "navigate", "go to", "browse",
    "scrape", "fetch", "pull", "sync", "backup", "translate", "summarize",
    "analyze", "compare", "calculate", "convert", "test",
)

# Follow-up / anaphora markers — signal the user is continuing a PRIOR task
# ("now do it for the sales team", "yes, schedule that", "what about the
# other one"). They carry no action verb of their own but are clearly NOT
# standalone questions, so they route to DER (the safe fallback) rather than
# the dumb direct path.
FOLLOWUP_MARKERS = (
    "now", "then", "also", "too", "as well", "instead", "again",
    "what about", "how about", "and the", "for the", "with the",
    "yes", "yeah", "yep", "sure", "ok", "okay", "do it", "go ahead",
    "proceed", "confirm", "that one", "the other one", "the same",
)
ANAPHORA_PRONOUNS = ("it", "that", "this", "them", "they", "those", "these", "him", "her")

# Explicit tool-request prefixes (REQ-1 AC5 / ask_first policy).
TOOL_PREFIXES = ("tool:", "run:", "execute:", "plan:")

# Web-search trigger phrases (migrated from _is_web_search_request, 4540-4560).
WEB_SEARCH_TRIGGERS = [
    "web search",
    "websearch ",
    "search the web",
    "search on the internet",
    "search online",
    "look up online",
    "look up on the",
    "find on the web",
    "find on the internet",
    "browse the web",
    "do a web search",
    "research ",
    "do research",
    "do some research",
    "find information about",
    "look up information",
]


def is_chitchat(text: str) -> bool:
    """True for pure social/casual messages that need no planning or tools.

    Migrated verbatim from AgentKernel._is_chitchat. Empty/whitespace input is
    chit-chat (REQ-1 AC4 — matches legacy empty-string behavior).
    """
    t = (text or "").lower().strip()
    if not t:
        return True
    if t in CHITCHAT_PATTERNS:
        return True
    # Starts with a greeting token (e.g. "hey there")
    _first = t.split()[0] if t.split() else ""
    if _first in ("hi", "hello", "hey", "yo", "sup", "howdy", "hiya", "greetings"):
        return True
    # "how are you" family — social, not a task
    if t.startswith("how are") or t.startswith("how's") or t.startswith("how is"):
        return True
    # Short casual acknowledgement (no tool intent)
    if t in CHITCHAT_ACKS:
        return True
    return False


def is_followup_to_task(text: str, context) -> bool:
    """Does this message continue a prior task rather than start a fresh one?

    Migrated verbatim from AgentKernel._is_followup_to_task. Returns True when
    the message is short, anaphoric (references "it/that/them"), or a
    confirmation/continuation marker AND the recent context shows an active
    task. Free (0 model calls).
    """
    t = (text or "").lower().strip()
    if not t or len(t.split()) > 25:
        return False
    # Anaphora: a pronoun with no noun is almost always a continuation.
    words = set(t.split())
    if words & set(ANAPHORA_PRONOUNS) and not any(
        v in t for v in ACTION_VERBS
    ):
        # "do it", "change that", "what about them" — continuation.
        if any(m in t for m in ("do", "change", "update", "edit", "what about",
                                "how about", "send", "for", "with", "the")):
            return True
    # Explicit continuation/confirmation markers.
    if any(t.startswith(m) or f" {m} " in f" {t} " for m in FOLLOWUP_MARKERS):
        return True
    # Prior task context: if the last assistant turn was a plan/tool result,
    # a short user reply is overwhelmingly a follow-up, not a new question.
    if context:
        try:
            last = context[-1] if isinstance(context, (list, tuple)) else None
            if isinstance(last, dict) and last.get("role") == "assistant":
                c = (last.get("content") or "")
                if any(k in c.lower() for k in ("plan", "tool", "step", "task", "i'll", "i will")):
                    if len(t.split()) <= 12:
                        return True
        except Exception:
            pass
    return False


def is_web_search_request(text: str) -> bool:
    """Does the user message explicitly request a web search?

    Migrated verbatim from AgentKernel._is_web_search_request. Precise phrase
    triggers rather than broad keywords, to avoid blocking legitimate
    non-search queries.
    """
    if not text:
        return False
    _lower = text.lower().strip()
    return any(t in _lower for t in WEB_SEARCH_TRIGGERS)


class Tier0Intent(str, Enum):
    """The four legacy intents + the web variant resolved by Tier 0.

    ``requires_der_kernel`` mapping is applied at the policy layer (REQ-8 AC3:
    _tool_mode is a registered policy, not a branch here).
    """

    CHAT = "chat"
    ACTION = "action"
    FOLLOWUP = "followup"
    QUESTION = "question"
    WEB = "web"  # action + web_crawler_query lane (web-mode gated at compile)


@dataclass
class Tier0Verdict:
    """Deterministic Tier 0 result — pure, no I/O, no model calls."""

    intent: Tier0Intent
    is_chitchat: bool = False
    is_web_search: bool = False


def tier0_classify(text: str, context=None) -> Tier0Verdict:
    """The Tier 0 fast-path — migrated from AgentKernel._classify_intent.

    Resolves by the CHEAPEST matching layer; the neural/ontology tiers are the
    fallback, not the first responder (negative routing). Most traffic resolves
    here at <1ms with 0 model work. Tool-mode is NOT applied here — it is a
    registered policy applied at DAG-compile time (REQ-8 AC3).
    """
    t = (text or "").lower().strip()
    if not t:
        # Empty/whitespace -> CONVERSATIONAL_SURFACE(chitchat_banter) (REQ-1 AC4).
        return Tier0Verdict(intent=Tier0Intent.CHAT, is_chitchat=True)

    # Layer 1 — deterministic rules.
    if t.startswith(TOOL_PREFIXES):
        return Tier0Verdict(intent=Tier0Intent.ACTION)
    if is_chitchat(text):
        return Tier0Verdict(intent=Tier0Intent.CHAT, is_chitchat=True)

    # Layer 2 — cheap keyword/intent match.
    if is_web_search_request(text):
        return Tier0Verdict(intent=Tier0Intent.WEB, is_web_search=True)
    if any(verb in t for verb in ACTION_VERBS):
        return Tier0Verdict(intent=Tier0Intent.ACTION)

    # Layer 3 — ambiguous middle: follow-up to a prior task -> DER (safe).
    if is_followup_to_task(text, context):
        return Tier0Verdict(intent=Tier0Intent.FOLLOWUP)

    # Layer 4 — default: standalone question -> direct path.
    return Tier0Verdict(intent=Tier0Intent.QUESTION)


def _compound_task_lanes(text: str) -> List[CapabilityLane]:
    """Deterministic compound-task splitter (REQ-1 AC2).

    Splits a prompt on task-joining conjunctions and classifies each clause:
    memory-seeking phrases ("look up ... from last session") ->
    skill_landmark_query; "test"/"verify" clauses -> test_validation; other
    task verbs -> code_inspection. Returns >= 2 distinct lanes when the prompt
    is a compound task, else []. Zero model calls — the deterministic multi-lane
    path (Tier 1 was removed).
    """
    import re

    t = (text or "").lower().strip()
    clauses = [c.strip() for c in re.split(r"\s+(?:and|then|also)\s+|,\s*", t) if c.strip()]
    if len(clauses) < 2:
        return []
    lanes: List[CapabilityLane] = []
    for c in clauses:
        if "test" in c or "verify" in c or "run the tests" in c:
            lanes.append(CapabilityLane.TEST_VALIDATION)
        elif any(p in c for p in (
            "look up", "from last session", "remember", "last time",
            "find the pattern", "reconnect pattern", "previous session",
        )):
            lanes.append(CapabilityLane.SKILL_LANDMARK_QUERY)
        elif any(v in c for v in ACTION_VERBS):
            lanes.append(CapabilityLane.CODE_INSPECTION)
    seen: set = set()
    out: List[CapabilityLane] = []
    for ln in lanes:
        if ln not in seen:
            seen.add(ln)
            out.append(ln)
    return out if len(out) >= 2 else []


# ---------------------------------------------------------------------------

# Node types for RecallFilters / memory_chain write-back. CI-pinned by
# scripts/validate_ontology_schema.py against NodeRecord.node_type vocabulary
# (der_loop.py). No exported constant exists upstream, so the pinned set lives
# here; the T13 provenance test asserts it matches the CI pin.
NODE_TYPES = frozenset({"task", "step", "sub_loop"})

# execution_domain registry (ontology.md §2b) — 3 values, never free text.
EXECUTION_DOMAINS = frozenset({"voice", "der", "research"})

# ---------------------------------------------------------------------------
# Routing thresholds — INITIAL values, tuned in T13 (Decisions Locked).
# ---------------------------------------------------------------------------
# Follow-up extension: a short follow-up aligns with the active task when its
# embedding similarity >= this (REQ-4 AC2). Initial; tuned in T13.
FOLLOWUP_SIM_THRESHOLD = 0.65


class IntentDomain(str, Enum):
    """The five intent domains. 16 capability lanes hang off these."""

    CONVERSATIONAL_SURFACE = "conversational_surface"
    ONTOLOGY_MEMORY_QA = "ontology_memory_qa"
    VOICE_DESKTOP_ACTION = "voice_desktop_action"
    TASK_EXECUTION_DAG = "task_execution_dag"
    RESEARCH_SWARM_DAG = "research_swarm_dag"


class CapabilityLane(str, Enum):
    """The 16 DAG-composable capability lanes — counted exactly (3+4+2+4+3).

    ``skill_landmark`` is a landmark concept, NOT a node_type value — it never
    appears in ``NODE_TYPES`` (REQ-2 AC4).
    """

    # Conversational Surface (3)
    CHITCHAT_BANTER = "lane:chitchat_banter"
    CLARIFICATION_PROBE = "lane:clarification_probe"
    EXPLANATION_SYNTHESIS = "lane:explanation_synthesis"
    # Ontology Memory QA (4)
    PREFERENCE_LOOKUP = "lane:preference_lookup"
    SKILL_LANDMARK_QUERY = "lane:skill_landmark_query"
    EPISODIC_TRAJECTORY_WALK = "lane:episodic_trajectory_walk"
    DOMAIN_CONCEPT_RETRIEVAL = "lane:domain_concept_retrieval"
    # Voice Desktop Action (2)
    IMMEDIATE_OS_CONTROL = "lane:immediate_os_control"
    SYSTEM_STATE_QUERY = "lane:system_state_query"
    # Task Execution DAG (4)
    CODE_INSPECTION = "lane:code_inspection"
    MUTATION_PATCH = "lane:mutation_patch"
    TEST_VALIDATION = "lane:test_validation"
    SHELL_COMMAND = "lane:shell_command"
    # Research Swarm DAG (3)
    WEB_CRAWLER_QUERY = "lane:web_crawler_query"
    SOURCE_TRIANGULATION = "lane:source_triangulation"
    DEEP_SYNTHESIS = "lane:deep_synthesis"
    # == 16 lanes total ==

    @property
    def domain(self) -> IntentDomain:
        """The IntentDomain this lane belongs to (single source of truth)."""
        return _LANE_DOMAIN[self]


# lane -> domain mapping (asserted by T11 unit tests).
_LANE_DOMAIN: Dict[CapabilityLane, IntentDomain] = {
    CapabilityLane.CHITCHAT_BANTER: IntentDomain.CONVERSATIONAL_SURFACE,
    CapabilityLane.CLARIFICATION_PROBE: IntentDomain.CONVERSATIONAL_SURFACE,
    CapabilityLane.EXPLANATION_SYNTHESIS: IntentDomain.CONVERSATIONAL_SURFACE,
    CapabilityLane.PREFERENCE_LOOKUP: IntentDomain.ONTOLOGY_MEMORY_QA,
    CapabilityLane.SKILL_LANDMARK_QUERY: IntentDomain.ONTOLOGY_MEMORY_QA,
    CapabilityLane.EPISODIC_TRAJECTORY_WALK: IntentDomain.ONTOLOGY_MEMORY_QA,
    CapabilityLane.DOMAIN_CONCEPT_RETRIEVAL: IntentDomain.ONTOLOGY_MEMORY_QA,
    CapabilityLane.IMMEDIATE_OS_CONTROL: IntentDomain.VOICE_DESKTOP_ACTION,
    CapabilityLane.SYSTEM_STATE_QUERY: IntentDomain.VOICE_DESKTOP_ACTION,
    CapabilityLane.CODE_INSPECTION: IntentDomain.TASK_EXECUTION_DAG,
    CapabilityLane.MUTATION_PATCH: IntentDomain.TASK_EXECUTION_DAG,
    CapabilityLane.TEST_VALIDATION: IntentDomain.TASK_EXECUTION_DAG,
    CapabilityLane.SHELL_COMMAND: IntentDomain.TASK_EXECUTION_DAG,
    CapabilityLane.WEB_CRAWLER_QUERY: IntentDomain.RESEARCH_SWARM_DAG,
    CapabilityLane.SOURCE_TRIANGULATION: IntentDomain.RESEARCH_SWARM_DAG,
    CapabilityLane.DEEP_SYNTHESIS: IntentDomain.RESEARCH_SWARM_DAG,
}


class EdgeRelationship(str, Enum):
    """Typed dependency edges of the compiled execution DAG (REQ-1 AC2)."""

    DEPENDS_ON = "depends_on"
    DERIVES_FROM = "derives_from"
    RELEVANT_TO = "relevant_to"
    SUPPLEMENTS = "supplements"
    HANDOFF_TO = "handoff_to"


@dataclass
class DAGPlanNode:
    """A single capability-lane node of the compiled execution DAG.

    ``topic_domain`` / ``execution_domain`` are registry-backed axes from
    ``DOMAIN_IDS`` / ``EXECUTION_DOMAINS`` — never free text (REQ-2 AC1).
    """

    node_id: str
    domain: IntentDomain
    lane: CapabilityLane
    description: str
    # Registry-backed axes (from DOMAIN_IDS / {voice, der, research}).
    topic_domain: Optional[str] = None
    execution_domain: Optional[str] = None
    ontology_scope_resolved: Optional[str] = None  # SCOPE_* winning label
    confidence: float = 0.0


@dataclass
class DAGPlanGraph:
    """The gate's compiled routing result handed to planning.

    ``DAGPlanGraph`` is the gate's OUTPUT, not a persisted object. The durable
    execution graph lives in ``ExecutionLedger``/``TaskLifecycle``,
    ``DirectorQueue``, ``NodeRecord`` and the link store — the gate reads those
    (REQ-4 AC1), it does not duplicate them.
    """

    nodes: List[DAGPlanNode] = field(default_factory=list)
    edges: List[Dict[str, str]] = field(default_factory=list)  # {source, target, relationship}
    is_pure_conversation: bool = False
    requires_der_kernel: bool = True
    latency_ms: float = 0.0
    # REQ-5 AC1 (T8): winning ontology widen scope from Tier 2 ("" when no
    # recall ran or no scope was recorded).
    widen_scope: str = ""
    # Human-readable reason for the routing decision (REQ-8 AC1) — feeds the
    # planning-policy hook's contributors and the [LAYERS] telemetry line.
    why: str = ""

    @property
    def lane_distribution(self) -> List[CapabilityLane]:
        """Ranked lanes by confidence, descending (REQ-1 AC7 fluid routing)."""
        return sorted(
            (n.lane for n in self.nodes),
            key=lambda ln: next(n.confidence for n in self.nodes if n.lane is ln),
            reverse=True,
        )


# ===========================================================================
# TIER 2 — ontology neighborhood + context filter (REQ-2).
#
# Runs the SHARED recall helper (``run_filtered_recall``, ontology_recall.py)
# — the same code path as AgentKernel._der_recall_neighborhood (REQ-6 AC3), so
# the widen-order and telemetry cannot drift between the gate and DER. Axes
# are registry-backed: topic_domain from DOMAIN_IDS via resolve_topic_domain
# (miss -> 'general' + logged, REQ-2 AC1), execution_domain from
# {voice, der, research}. Lane-specific store routing (preference_lookup ->
# semantic.py, REQ-2 AC4) is applied at DAG-compile time (T7), not here.
# ---------------------------------------------------------------------------


@dataclass
class Tier2Result:
    """Ontology recall outcome for a prompt (REQ-2)."""

    rows: List[dict] = field(default_factory=list)
    topic_domain: Optional[str] = None
    execution_domain: Optional[str] = None
    # REQ-5 AC1 (T8): winning widen scope from run_filtered_recall ("" when
    # no recall ran or no scope was recorded).
    widen_scope: str = ""


def tier2_ontology(
    text: str,
    memory_interface=None,
    execution_domain: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 5,
) -> Tier2Result:
    """Ontology neighborhood recall for a prompt (REQ-2 AC1-AC3).

    Extracts the two registry-backed axes from the prompt and runs the shared
    recall helper. Returns rows or empty — never raises; a missing connection
    or a recall failure yields an empty result and the caller proceeds on live
    state (AC5: surviving nodes returned without raising).
    """
    from backend.agent.ontology_recall import (
        RecallFilters,
        resolve_mycelium_conn,
        run_filtered_recall,
    )
    from backend.memory.mycelium.extractor import resolve_topic_domain

    topic = resolve_topic_domain(text or "")  # registry-backed; miss -> general + logged
    exec_domain = execution_domain if execution_domain in EXECUTION_DOMAINS else "der"
    filters = RecallFilters(
        topic_domain=topic,
        execution_domain=exec_domain,
        thread_id=session_id or None,  # ranking input only, never a hard filter
        limit=limit,
    )
    conn = resolve_mycelium_conn(memory_interface)
    if conn is None:
        return Tier2Result(rows=[], topic_domain=topic, execution_domain=exec_domain)
    scope_out: List[str] = []
    rows = run_filtered_recall(conn, filters, scope_out=scope_out)
    return Tier2Result(
        rows=rows,
        topic_domain=topic,
        execution_domain=exec_domain,
        widen_scope=scope_out[0] if scope_out else "",
    )
    return Tier2Result(rows=rows, topic_domain=topic, execution_domain=exec_domain)


def lookup_preference(memory_interface, key: str) -> Optional[str]:
    """Route ``lane:preference_lookup`` to the store that owns the data (REQ-2 AC4).

    Preferences live in ``semantic.py`` (``user_preferences`` category), NOT in
    the DER ``memory_chain``. Uses ``MemoryInterface.get_preference`` (added as
    the divergence-resolution for the spec citation interface.py:439-482).
    """
    if memory_interface is None:
        return None
    try:
        return memory_interface.get_preference(key)
    except Exception as exc:
        logger.debug("[SemanticGate] preference lookup failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# CONTEXTUAL CONTINUATION — a READ-ONLY LENS over the existing execution graph
# (REQ-4). The "active DAG" already exists: a non-terminal TaskLifecycle with
# non-empty pending_step_ids (der_execution_ledger.py:177,209) + the live
# DirectorQueue (der_loop.py:243). This evaluator READS those; it adds NO
# second persistence layer (AC1). The directives it emits are executed by the
# kernel wiring (T7) via the EXISTING graft path (agent_kernel.py:7810),
# _split_step + fold-back, and lifecycle terminal transitions.
# ---------------------------------------------------------------------------

# Explicit abort / topic-switch markers (REQ-4 AC4). Deliberately stronger
# than the follow-up markers: "instead" alone is a continuation, not an abort.
ABORT_MARKERS = (
    "cancel", "cancel that", "cancel the task", "stop", "stop that",
    "stop the task", "never mind", "forget it", "forget that", "abort",
    "quit", "start over", "restart", "scrap it", "drop it", "do something else",
    "switch topic", "change the subject", "new task", "different task",
)


class ContinuationDirective(str, Enum):
    """What the kernel should do with the active task (REQ-4 AC2-AC4)."""

    NONE = "none"      # no active task / not a continuation
    EXTEND = "extend"  # append new QueueItem steps to the pending set (graft path)
    MORPH = "morph"    # edge changes on existing nodes / split + fold-back
    CLOSE = "close"    # transition lifecycle to terminal, open a new task_id


@dataclass
class ContinuationVerdict:
    """Read-only evaluation of a follow-up turn against the active task."""

    directive: ContinuationDirective = ContinuationDirective.NONE
    task_id: Optional[str] = None
    sim: float = 0.0
    reason: str = ""
    avoid_rows: List[dict] = field(default_factory=list)  # recall_failed_like (AC5)


def _alignment_sim(text: str, objective: str, embedding_service=None, is_anaphoric: bool = False) -> float:
    """Alignment similarity between a follow-up and the active task objective.

    Neural cosine when a neural backend is available (the 0.65 threshold in
    REQ-4 AC2 is calibrated on the LFM embedding); otherwise a lexical Jaccard
    over significant tokens, documented as a degraded fallback. Never raises.

    Degraded-fallback convention: a short anaphoric follow-up ("yes do it",
    "ok proceed", "what about the other one") carries no content tokens of its
    own — its only possible referent IS the active task, so alignment is
    maximal (1.0) when ``is_anaphoric`` and the follow-up has <= 2 significant
    tokens. The neural path never needs this convention.
    """
    if not objective:
        return 0.0
    try:
        if embedding_service is not None and getattr(embedding_service, "backend", None) == BACKEND_LFM:
            a = embedding_service.encode_with_backend(text, BACKEND_LFM)
            b = embedding_service.encode_with_backend(objective, BACKEND_LFM)
            if a and b and len(a) == len(b) == 1024:
                na = math.sqrt(sum(x * x for x in a)) or 1.0
                nb = math.sqrt(sum(x * x for x in b)) or 1.0
                return sum(x / na * y / nb for x, y in zip(a, b))
    except Exception as exc:
        logger.debug("[SemanticGate] neural alignment sim failed, lexical fallback: %s", exc)
    # Lexical fallback: Jaccard over significant tokens (>= 4 chars, non-stop).
    _stop = {"with", "that", "this", "from", "what", "about", "there", "have", "your", "the", "and", "for", "you", "are", "not", "but", "can", "its", "it's"}
    ta = {w for w in (text or "").lower().split() if len(w) >= 4 and w not in _stop}
    tb = {w for w in (objective or "").lower().split() if len(w) >= 4 and w not in _stop}
    if not ta:
        # Purely anaphoric follow-up — binds to the active task by construction.
        return 1.0 if is_anaphoric else 0.0
    if is_anaphoric and len(ta) <= 2:
        return 1.0
    if not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _shares_topic(text: str, objective: str) -> bool:
    """Registry-backed topical relatedness for MORPH (REQ-4 AC3).

    True when both strings resolve to the SAME non-general topic_domain
    (DOMAIN_IDS registry), OR they share at least one significant token. The
    lexical complement is needed because the registry's keyword patterns are
    coarse (most task phrasing resolves to ``general``); the neural path's
    cosine is the primary signal and this is the degraded-path complement.
    """
    if not objective:
        return False
    try:
        from backend.memory.mycelium.extractor import resolve_topic_domain

        td_text = resolve_topic_domain(text or "")
        td_obj = resolve_topic_domain(objective)
        if td_text != "general" and td_text == td_obj:
            return True
    except Exception:
        pass
    _stop = {"with", "that", "this", "from", "what", "about", "there", "have", "your", "the", "and", "for", "you", "are", "not", "but", "can", "its", "it's"}
    ta = {w for w in (text or "").lower().split() if len(w) >= 4 and w not in _stop}
    tb = {w for w in (objective or "").lower().split() if len(w) >= 4 and w not in _stop}
    return bool(ta & tb)


def evaluate_continuation(
    text: str,
    task_lifecycle=None,
    director_queue=None,
    memory_interface=None,
    embedding_service=None,
    failed_step_ids: Optional[List[str]] = None,
) -> ContinuationVerdict:
    """Evaluate a follow-up turn against the active task (REQ-4 AC1-AC5).

    Read-only: inspects the existing TaskLifecycle + DirectorQueue, never
    mutates them. Returns a directive the kernel executes through the existing
    graft / split / lifecycle mechanisms. Never raises.
    """
    # Lazy embedding resolution (REQ-4): the continuation lens uses the neural
    # alignment path when a backend is active, else the lexical Jaccard
    # fallback. Resolved here so the gate no longer owns a Tier-1 projector.
    if embedding_service is None:
        try:
            from backend.memory.embedding import get_embedding_service

            embedding_service = get_embedding_service()
        except Exception:
            embedding_service = None

    # AC1 — is there an active DAG at all?
    active = (
        task_lifecycle is not None
        and not task_lifecycle.is_terminal()
        and bool(getattr(task_lifecycle, "pending_step_ids", None))
    )
    if not active:
        return ContinuationVerdict(reason="no active task")

    task_id = getattr(task_lifecycle, "task_id", None)
    t = (text or "").lower().strip()
    if not t:
        return ContinuationVerdict(directive=ContinuationDirective.NONE, task_id=task_id, reason="empty follow-up")

    # AC4 — explicit abort / topic switch -> CLOSE.
    if any(m in t for m in ABORT_MARKERS):
        return ContinuationVerdict(
            directive=ContinuationDirective.CLOSE,
            task_id=task_id,
            reason="explicit abort/topic-switch marker",
        )

    # AC2 — short follow-up (<= 12 words, _is_followup_to_task rules) aligned
    # with the active task (sim >= 0.65) -> EXTEND.
    objective = getattr(director_queue, "objective", "") if director_queue is not None else ""
    if not objective:
        objective = getattr(task_lifecycle, "next_action", "") or ""
    is_short_followup = len(t.split()) <= 12 and is_followup_to_task(text, None)
    sim = _alignment_sim(text, objective, embedding_service, is_anaphoric=is_short_followup)
    if is_short_followup and sim >= FOLLOWUP_SIM_THRESHOLD:
        verdict = ContinuationVerdict(
            directive=ContinuationDirective.EXTEND,
            task_id=task_id,
            sim=sim,
            reason="short follow-up aligned with active task",
        )
        # AC5 — AVOID integration: extending from a failed step consults
        # recall_failed_like so a known-failure class is not re-attempted.
        failed = failed_step_ids or []
        if director_queue is not None:
            failed = failed + list(getattr(director_queue, "failed_ids", []) or [])
        if failed:
            from backend.agent.ontology_recall import recall_failed_like, resolve_mycelium_conn

            conn = resolve_mycelium_conn(memory_interface)
            if conn is not None:
                for step_id in failed[:3]:
                    verdict.avoid_rows.extend(recall_failed_like(conn, step_id, limit=3))
        return verdict

    # AC3 — re-target / reorder -> MORPH (edge changes; deeper rework is
    # expressed as _split_step + fold-back by the kernel, never a new graph).
    task_like = any(v in t for v in ACTION_VERBS) or is_followup_to_task(text, None)
    if task_like and (sim >= FOLLOWUP_SIM_THRESHOLD or _shares_topic(text, objective)):
        return ContinuationVerdict(
            directive=ContinuationDirective.MORPH,
            task_id=task_id,
            sim=sim,
            reason="re-target/reorder of active task",
        )

    return ContinuationVerdict(directive=ContinuationDirective.NONE, task_id=task_id, sim=sim, reason="not aligned with active task")


# ---------------------------------------------------------------------------
# BIDIRECTIONAL CADUCEAN MEMORY (REQ-7).
#
# Read side:  ffi_caducean_get_state coordinates -> ffi_immortus_chain_query_by_coordinate
# Write side: ffi_immortus_chain_append with ontology axes + coords (Python
#             engine first — the C++ 8-arg struct cannot carry the ontology
#             columns, iris_ffi.py:1585).
# Both are OFF the hot path (the caller schedules the write-back) and no-op
# cleanly when the engine is not loaded (ffi returns {} / -1 / []).
# ---------------------------------------------------------------------------


def _state_coords(state: Dict[str, float]) -> List[float]:
    """Extract the 4D reasoning-state coordinate (x, y, xi, u) from a state dict."""
    if not state:
        return []
    try:
        return [float(state[k]) for k in ("x", "y", "xi", "u")]
    except (KeyError, TypeError, ValueError):
        return []


def _coords_str(coords: Sequence[float]) -> str:
    """Serialize numeric coords the same way the C++ core does (",".join floats)."""
    return ",".join(str(float(c)) for c in coords)


def caducean_recall(
    session_id: str = "",
    thread_id: Optional[str] = None,
    coords: Optional[Sequence[float]] = None,
    limit: int = 5,
) -> List[dict]:
    """Coordinate recall from the Caducean reasoning state (REQ-7 read side).

    Uses ``ffi_caducean_get_state`` coordinates (falling back to an explicit
    ``coords`` override) -> ``ffi_immortus_chain_query_by_coordinate``. Engine
    not loaded -> empty state -> [] (no-op). Never raises.
    """
    from backend.gateway import iris_ffi

    if coords is None:
        state = iris_ffi.ffi_caducean_get_state(session_id or "")
        coords = _state_coords(state)
    if not coords:
        return []
    try:
        rows = iris_ffi.ffi_immortus_chain_query_by_coordinate(
            coords, threshold=1.0, limit=limit, thread_id=thread_id
        )
        return rows or []
    except Exception as exc:
        logger.debug("[SemanticGate] caducean coordinate recall failed: %s", exc)
        return []


def caducean_write_routing(
    session_id: str,
    thread_id: str,
    result: str,
    node_type: str,
    topic_domain: str,
    execution_domain: str,
    coords_from: Optional[Sequence[float]] = None,
    coords_to: Optional[Sequence[float]] = None,
    nbl_outcome: str = "",
    insight: str = "",
    file_path: str = "",
    landmark_id: str = "",
    mediator: str = "",
    mediator_source: str = "",
) -> int:
    """Write the routing decision back to the Caducean memory chain (REQ-7 write side).

    Uses ``ffi_immortus_chain_append`` with ontology axes + coords. The coords
    are serialized as the C++ core does (",".join floats) so the row is
    queryable by the same coordinate. Engine not loaded -> -1 (no-op). Never
    raises. Caller schedules this OFF the hot path.
    """
    from backend.gateway import iris_ffi

    try:
        if coords_from is None or coords_to is None:
            state = iris_ffi.ffi_caducean_get_state(session_id or "")
            c = _state_coords(state)
            if not c:
                return -1  # engine not loaded / no state — no-op
            coords_from = coords_from or c
            coords_to = coords_to or c
        return iris_ffi.ffi_immortus_chain_append(
            thread_id=thread_id,
            result=result,
            coords_from=_coords_str(coords_from),
            coords_to=_coords_str(coords_to),
            nbl_outcome=nbl_outcome or None,
            insight=insight or None,
            file_path=file_path or None,
            landmark_id=landmark_id or None,
            mediator=mediator or None,
            mediator_source=mediator_source or None,
            node_type=node_type,
            topic_domain=topic_domain,
            execution_domain=execution_domain,
        )
    except Exception as exc:
        logger.debug("[SemanticGate] caducean routing write-back failed: %s", exc)
        return -1


# ---------------------------------------------------------------------------
# THE GATE — compile_dag() (REQ-1, REQ-8). Wired into AgentKernel at T7.
#
# compile_dag() runs Tier 0 (deterministic rules) -> Tier 2 (coordinate-graph
# ontology) -> the continuation lens, then composes a DAGPlanGraph: 16-lane
# nodes, typed edges, is_pure_conversation, requires_der_kernel (the ONLY
# boolean — a derived efficiency flag, REQ-1 AC7), and a human-readable
# `why` (REQ-8 AC1). The planning-policy hook (REQ-8 AC3) lets skills/plugins/
# MCPs register contributors/overrides that adjust the draft graph per task;
# _tool_mode is itself a registered policy (auto|ask_first|disabled).
# ---------------------------------------------------------------------------


class SemanticLogicGate:
    """The DAG-compiling semantic router. No model load at construction."""

    def __init__(
        self,
        tool_mode: str = "auto",
        memory_interface=None,
    ) -> None:
        self.tool_mode = tool_mode if tool_mode in ("auto", "ask_first", "disabled") else "auto"
        self._memory_interface = memory_interface
        self._policies: Dict[str, Callable] = {}
        self._register_default_policies()

    # -- planning-policy hook (REQ-8) ---------------------------------------

    def _register_default_policies(self) -> None:
        """_tool_mode is a REGISTERED policy (REQ-8 AC3), default = gate."""
        self._policies["tool_mode:auto"] = (
            lambda graph, text, context: graph.requires_der_kernel
        )
        self._policies["tool_mode:ask_first"] = (
            lambda graph, text, context: (text or "").lower().strip().startswith(TOOL_PREFIXES)
        )
        self._policies["tool_mode:disabled"] = (
            lambda graph, text, context: False
        )

    def register_policy(self, name: str, fn) -> None:
        """Planning-policy hook (REQ-8): skills/plugins/MCPs register a
        contributor/override ``fn(graph, text, context) -> DAGPlanGraph`` that
        adjusts the draft graph per task. Applied after the tool_mode policy,
        in registration order."""
        if not callable(fn):
            raise TypeError("planning policy must be callable")
        self._policies[name] = fn

    # -- compilation ---------------------------------------------------------

    def compile_dag(
        self,
        text: str,
        context=None,
        task_lifecycle=None,
        director_queue=None,
        web_mode: bool = False,
        session_id: Optional[str] = None,
    ) -> DAGPlanGraph:
        """Compile a turn into a DAGPlanGraph (REQ-1, REQ-8).

        Never raises. Routing is Tier 0 (deterministic rules) + Tier 2
        (coordinate-graph ontology) + the continuation lens. The neural
        embedding tier (Tier 1) was removed — the gate routes on rules +
        coordinates, matching the app's coordinate-graph memory.
        """
        _t0 = time.perf_counter()
        verdict = tier0_classify(text, context)

        # Tier 2 — ontology axes + shared recall (only when memory is wired).
        t2 = Tier2Result()
        if self._memory_interface is not None:
            t2 = tier2_ontology(text, self._memory_interface, session_id=session_id)

        # Continuation lens (REQ-4) — only when an active task is supplied.
        cont = ContinuationVerdict()
        if task_lifecycle is not None:
            cont = evaluate_continuation(
                text,
                task_lifecycle,
                director_queue,
                self._memory_interface,
            )

        graph = self._compose(text, verdict, t2, cont, web_mode, continuation_consulted=(task_lifecycle is not None))
        graph.widen_scope = t2.widen_scope

        # Policy layer: tool_mode first, then registered contributor hooks.
        policy = self._policies.get(f"tool_mode:{self.tool_mode}", self._policies["tool_mode:auto"])
        graph.requires_der_kernel = bool(policy(graph, text, context))
        for name, fn in self._policies.items():
            if name.startswith("tool_mode:"):
                continue
            try:
                graph = fn(graph, text, context) or graph
            except Exception as exc:
                logger.debug("[SemanticGate] planning policy %s failed: %s", name, exc)

        graph.latency_ms = (time.perf_counter() - _t0) * 1000.0
        return graph

    # -- composition ---------------------------------------------------------

    def _compose(
        self,
        text: str,
        verdict: Tier0Verdict,
        t2: Tier2Result,
        cont: ContinuationVerdict,
        web_mode: bool,
        continuation_consulted: bool = False,
    ) -> DAGPlanGraph:
        """Build the draft DAGPlanGraph from the tier outputs (REQ-1 AC1-AC7)."""
        nodes: List[DAGPlanNode] = []
        edges: List[Dict[str, str]] = []
        requires_der = False
        pure_conversation = False
        why_parts: List[str] = []

        def _add(domain: IntentDomain, lane: CapabilityLane, desc: str, conf: float = 0.0,
                 topic: Optional[str] = None, exec_domain: Optional[str] = None) -> str:
            node_id = f"{lane.value}:{len(nodes)}"
            nodes.append(DAGPlanNode(
                node_id=node_id, domain=domain, lane=lane, description=desc,
                topic_domain=topic, execution_domain=exec_domain,
                ontology_scope_resolved=None, confidence=conf,
            ))
            return node_id

        if verdict.intent == Tier0Intent.CHAT:
            _add(IntentDomain.CONVERSATIONAL_SURFACE, CapabilityLane.CHITCHAT_BANTER,
                 "pure conversation — direct response, no task card")
            pure_conversation = True
            requires_der = False
            why_parts.append("tier0:chitchat")
        else:
            if verdict.intent == Tier0Intent.WEB:
                # REQ-1 AC6: web_crawler_query only when web mode is ON. The
                # requires_der flag stays True either way so the kernel's
                # existing web-advice path (agent_kernel.py:4901, checks
                # _is_web_search_request directly) still fires when web is OFF.
                if web_mode:
                    _add(IntentDomain.RESEARCH_SWARM_DAG, CapabilityLane.WEB_CRAWLER_QUERY,
                         "explicit web search request", conf=1.0,
                         topic=t2.topic_domain, exec_domain="research")
                    why_parts.append("tier0:web+web_mode")
                else:
                    _add(IntentDomain.CONVERSATIONAL_SURFACE, CapabilityLane.EXPLANATION_SYNTHESIS,
                         "web intent with web mode OFF — advise toggle (AC6)")
                    why_parts.append("tier0:web+web_mode_off")
                requires_der = True
            elif verdict.intent == Tier0Intent.ACTION:
                # REQ-1 AC2: compound task ("look up X and test it in Y") ->
                # multi-lane DAG with typed edges. Deterministic splitter
                # (no neural tier).
                compound = _compound_task_lanes(text)
                if compound:
                    node_ids: Dict[CapabilityLane, str] = {}
                    for ln in compound:
                        node_ids[ln] = _add(
                            IntentDomain.ONTOLOGY_MEMORY_QA if ln == CapabilityLane.SKILL_LANDMARK_QUERY
                            else IntentDomain.TASK_EXECUTION_DAG,
                            ln, f"compound-task clause ({ln.value})",
                            topic=t2.topic_domain,
                            exec_domain="der",
                        )
                    # AC2 edge shape: skill_landmark_query --derives_from-->
                    # code_inspection --depends_on--> test_validation. When the
                    # clauses only yield memory+test lanes, the inspection node
                    # is implied (the target-file work between lookup and test).
                    if (CapabilityLane.SKILL_LANDMARK_QUERY in node_ids
                            and CapabilityLane.TEST_VALIDATION in node_ids
                            and CapabilityLane.CODE_INSPECTION not in node_ids):
                        node_ids[CapabilityLane.CODE_INSPECTION] = _add(
                            IntentDomain.TASK_EXECUTION_DAG, CapabilityLane.CODE_INSPECTION,
                            "compound-task implied inspection (target file)",
                            topic=t2.topic_domain, exec_domain="der")
                    if CapabilityLane.SKILL_LANDMARK_QUERY in node_ids and CapabilityLane.CODE_INSPECTION in node_ids:
                        edges.append({"source": node_ids[CapabilityLane.SKILL_LANDMARK_QUERY],
                                      "target": node_ids[CapabilityLane.CODE_INSPECTION],
                                      "relationship": "derives_from"})
                    if CapabilityLane.CODE_INSPECTION in node_ids and CapabilityLane.TEST_VALIDATION in node_ids:
                        edges.append({"source": node_ids[CapabilityLane.CODE_INSPECTION],
                                      "target": node_ids[CapabilityLane.TEST_VALIDATION],
                                      "relationship": "depends_on"})
                    requires_der = True
                    why_parts.append("tier0:compound-task " + "+".join(ln.value for ln in compound))
                else:
                    # Default task lane: code_inspection (most common). No neural
                    # lane ranking — Tier 1 removed; routing is rules + coordinates.
                    _add(IntentDomain.TASK_EXECUTION_DAG, CapabilityLane.CODE_INSPECTION,
                         "action request (verb match)",
                         topic=t2.topic_domain, exec_domain="der")
                    requires_der = True
                    why_parts.append("tier0:action lane=code_inspection")
                    # Memory-seeking action: ontology lanes derive from the task.
                    if t2.rows:
                        ont_id = _add(IntentDomain.ONTOLOGY_MEMORY_QA, CapabilityLane.SKILL_LANDMARK_QUERY,
                                      "ontology neighborhood for action context",
                                      topic=t2.topic_domain, exec_domain="der")
                        edges.append({"source": ont_id, "target": nodes[0].node_id, "relationship": "derives_from"})
            elif verdict.intent == Tier0Intent.FOLLOWUP:
                # Continuation lens (REQ-4): EXTEND/MORPH -> DER; CLOSE -> new task.
                if cont.directive in (ContinuationDirective.EXTEND, ContinuationDirective.MORPH):
                    _add(IntentDomain.TASK_EXECUTION_DAG, CapabilityLane.CODE_INSPECTION,
                         f"continuation ({cont.directive.value}) of active task {cont.task_id}",
                         conf=cont.sim, topic=t2.topic_domain, exec_domain="der")
                    requires_der = True
                    why_parts.append(f"tier0:followup {cont.directive.value} sim={cont.sim:.2f}")
                elif cont.directive == ContinuationDirective.CLOSE:
                    _add(IntentDomain.TASK_EXECUTION_DAG, CapabilityLane.CODE_INSPECTION,
                         "explicit abort — close active task, open fresh plan",
                         topic=t2.topic_domain, exec_domain="der")
                    requires_der = True
                    why_parts.append("tier0:followup close")
                elif not continuation_consulted:
                    # Legacy followup semantics (pinned by test_universal_planning
                    # W0.2): a follow-up with prior-task context routes to DER
                    # even when no lifecycle handle is supplied — the ambiguous
                    # middle defaults to the safe path, never the dumb direct.
                    _add(IntentDomain.TASK_EXECUTION_DAG, CapabilityLane.CODE_INSPECTION,
                         "follow-up with prior-task context (legacy safe default)",
                         topic=t2.topic_domain, exec_domain="der")
                    requires_der = True
                    why_parts.append("tier0:followup legacy-default")
                else:
                    _add(IntentDomain.CONVERSATIONAL_SURFACE, CapabilityLane.EXPLANATION_SYNTHESIS,
                         "follow-up without active task — direct response")
                    requires_der = False
                    why_parts.append("tier0:followup no-active-task")
            else:  # QUESTION
                # Ontology memory lanes come from the coordinate graph (Tier 2),
                # never a neural projector. Tier 1 removed.
                if t2.rows:
                    _add(IntentDomain.ONTOLOGY_MEMORY_QA, CapabilityLane.DOMAIN_CONCEPT_RETRIEVAL,
                         "question with ontology neighborhood", topic=t2.topic_domain, exec_domain="der")
                    why_parts.append("tier2:ontology rows")
                else:
                    _add(IntentDomain.CONVERSATIONAL_SURFACE, CapabilityLane.EXPLANATION_SYNTHESIS,
                         "standalone question — direct response")
                    why_parts.append("tier0:question")
                requires_der = False

        return DAGPlanGraph(
            nodes=nodes,
            edges=edges,
            is_pure_conversation=pure_conversation,
            requires_der_kernel=requires_der,
            why="; ".join(why_parts),
        )

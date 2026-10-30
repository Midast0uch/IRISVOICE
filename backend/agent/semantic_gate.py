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
import re
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
    # "text" REMOVED 2026-10-30: it is usually a NOUN ("remembered text",
    # "the text on the page"). "send a text" is caught by "send"; the noun
    # match sent a memory seed to DER.
    "message", "call", "schedule", "remind", "set", "add",
    "delete", "remove", "update", "edit", "change", "list", "play", "show me",
    "book", "order", "buy", "download", "upload", "post", "tweet",
    "run", "execute", "deploy", "install", "configure", "toggle",
    "turn on", "turn off", "switch", "navigate", "go to", "browse",
    "scrape", "fetch", "pull", "sync", "backup", "translate", "summarize",
    # REQ-24 (2026-09-24 live, conv-green-tea / conv-compare-oled): analyze/
    # compare/calculate/convert are CONTENT-level verbs — "compare OLED vs
    # LCD" needs reasoning, not a crawl — but the pinned suite (W0.2) owns
    # them as same-frame anchors for compound prompts ("compare X then write
    # it to Y"), so they cannot be unloaded from the verb list without
    # breaking the gate proof. The REQ-24 fix therefore lives at the lane
    # composition, not here: a content ask that carries no fresh-data marker
    # must never acquire the research lane.
    "append", "prepend", "merge into", "insert into",
    "analyze", "compare", "calculate", "convert", "test",
)

# A verb is a WORD, not a substring. The old `any(verb in t ...)` match sent
# "staging deployment" to DER on "deploy", "context" on "text", and "prefix" on
# "fix" (the last is why WORK_VERBS already uses boundaries). One compiled
# alternation, longest first, so multi-word verbs ("look up", "show me") win.
#
# Inflected forms are generated explicitly: a word boundary alone would MISS
# "deploying" / "creating" / "running" and send a real action request to the
# direct path (the old substring match caught them). Nouns are NOT generated
# ("deployment" stays a noun).
def _action_verb_forms() -> set[str]:
    forms: set[str] = set()
    for verb in ACTION_VERBS:
        forms.add(verb)
        if " " in verb:            # phrase: no single-word inflection
            continue
        forms.update({verb + "s", verb + "ed", verb + "ing"})
        if verb.endswith("e"):     # make -> making, create -> creating
            stem = verb[:-1]
            forms.update({stem + "ing", stem + "ed"})
        elif len(verb) <= 4 and verb[-1] not in "aeiou":
            # CVC doubling: run -> running, set -> setting, add -> adding.
            forms.add(verb + verb[-1] + "ing")
            forms.add(verb + verb[-1] + "ed")
    return forms


_ACTION_VERB_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(v) for v in sorted(_action_verb_forms(), key=len, reverse=True))
    + r")\b"
)


def has_action_verb(text: str) -> bool:
    """True when an ACTION_VERB (or an inflected form) appears as a whole word.

    Word boundaries in both directions: ``"deployment"`` does NOT match
    ``"deploy"``, and ``"context"`` does NOT match ``"text"``. Inflections are
    generated, so ``"deploying"``, ``"creating"`` and ``"running"`` do match.
    Free and pure.
    """
    return bool(_ACTION_VERB_RE.search((text or "").lower()))


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

# A continuation marker is EVIDENCE only when it can mean "continue the task".
# Strong phrases are unambiguous on their own; weak words ("with the",
# "for the", "now", "also") appear inside ordinary questions ("Answer with the
# number only") and must not divert a fresh question to DER without a task in
# the recent context. This is the seam that misrouted two T48 memory asks.
# "what about" / "how about" are WEAK on purpose: "what about the weather?"
# is a fresh question when no task precedes it. A phrase that only makes sense
# as a continuation ("do it", "go ahead", "the same") stands on its own.
_STRONG_FOLLOWUP_MARKERS = (
    "do it", "go ahead", "proceed", "confirm", "that one", "the other one",
    "the same", "instead", "again",
)
_WEAK_FOLLOWUP_MARKERS = tuple(
    m for m in FOLLOWUP_MARKERS if m not in _STRONG_FOLLOWUP_MARKERS
)

# Word boundaries, not substrings: "planet" is not a plan, "toolbar" is not a
# tool, "stepper" is not a step, "multitask" is not a task.
_PRIOR_TASK_RE = re.compile(
    r"\b(?:plan|tool|step|task|i'll|i will|i've|working on)\b"
)


def _prior_task_context(context) -> bool:
    """Does the recent context show an assistant plan/tool/task turn?

    Scans the last four messages (not only the tail) so a one-message coda
    ("anything else?") does not erase the task that preceded it. Never raises.
    """
    try:
        for msg in list(context or [])[-4:]:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            c = (msg.get("content") or "").lower()
            if _PRIOR_TASK_RE.search(c):
                return True
    except Exception:
        return False
    return False


# Explicit tool-request prefixes (REQ-1 AC5 / ask_first policy).
TOOL_PREFIXES = ("tool:", "run:", "execute:", "plan:")

# ── REQ-24 (specs/reply-surface-contract) — bounded-ask markers ────────────
# A fresh-data / time marker means the user WANTS current facts: the ask stays
# a research ask and keeps the crawl lane (REQ-24 AC3).
FRESH_DATA_MARKERS = (
    "latest", "newest", "today", "tonight", "tomorrow", "yesterday",
    "current", "currently", "recent", "recently", "news", "right now",
    "this week", "this month", "this year", "so far", "up to date",
    "up-to-date", "breaking", "score", "scores", "price", "prices",
    "stock", "weather", "forecast", "who won",
)

# A named evidence OBJECT means the ask is ABOUT that object — it needs the
# object (file, URL, log, screen), not a fact search for it. Word forms match on
# WORD BOUNDARIES: "log" must not fire on "ontology", nor "site" on "opposite".
_EVIDENCE_OBJECT_WORDS = (
    "file", "files", "folder", "directory", "path", "url", "link",
    "website", "web page", "site", "database", "db", "log", "repo",
    "repository", "codebase", "script", "email", "inbox", "screen",
    "screenshot", "image", "attachment", "spreadsheet",
)
# A filename suffix or a URL is unambiguous wherever it appears.
_EVIDENCE_OBJECT_RAW = (
    ".txt", ".json", ".py", ".md", ".ts", ".rs", ".csv", ".pdf", "http",
)
_EVIDENCE_OBJECT_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _EVIDENCE_OBJECT_WORDS) + r")\b"
)

# Answer verbs: they produce meaning (or a document), never a fact search.
# They stay in ACTION_VERBS — the pinned gate proof (W0.2) requires it — but a
# sentence whose action verb comes from this set only is answered by reasoning
# (REQ-24 AC1). "list" is deliberately absent: "list files" names an object and
# "list" the noun is a pinned ambiguity (test_behavioral_intent_routing).
CONTENT_ASK_VERBS = (
    "analyze", "analyse", "compare", "calculate", "compute", "convert",
    "explain", "describe", "summarize", "summarise", "outline", "draft",
    "review", "translate", "discuss", "write",
)

# Work verbs the shared intent layer was missing (owner, 2026-10-07).
#
# These could not simply be appended to ACTION_VERBS: that list is matched by
# SUBSTRING (`any(verb in t for verb in ACTION_VERBS)`), so "fix" also matches
# "prefix"/"suffix"/"fixture", "port" matches "report"/"important"/"support",
# and "patch" matches "dispatch" — the same class of defect the audit already
# recorded for "spec"/"specific" and "doc"/"docker". They are therefore matched
# on WORD BOUNDARIES below, which is what a verb actually is.
#
# Why they exist: execution audit B8 added a DEVELOPER-MODE override that
# rewrote every question into an action, because these verbs were absent and
# "fix the bug in foo.py" was answered conversationally. The override was the
# wrong layer — it made INTENT differ by mode. With the verbs present in the
# shared layer, a work request routes to the work loop in BOTH modes and the
# override can be deleted, so intent is mode-independent (owner: "there should
# be no difference between personal mode and developer mode besides how things
# are displayed and the agent being able to edit/read/write its own code").
WORK_VERBS = (
    "fix", "implement", "refactor", "migrate", "rename", "optimize",
    "optimise", "patch", "port", "upgrade", "rewrite", "rework", "harden",
    "investigate", "diagnose", "troubleshoot", "reproduce",
)
_WORK_VERB_RE = re.compile(
    r"\b(?:" + "|".join(WORK_VERBS) + r")(?:s|es|ed|d|ing)?\b"
)


def has_work_verb(text: str) -> bool:
    """True when the text asks for WORK to be done (word-boundary matched).

    Mode-independent by construction: this is the shared intent layer, so
    "fix the bug in foo.py" routes to the work loop in personal AND developer
    mode. Only DISPLAY (matrix vs compact card) and CAPABILITY (edit / read /
    write its own code) may differ by mode - never the routing decision.
    """
    return bool(_WORK_VERB_RE.search((text or "").lower()))


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
    # Anaphora is EVIDENCE only when a task actually precedes it. Without this
    # guard, "Remember this ... Just acknowledge it briefly." matched "it"+"for"
    # and ran DER (141 s), and "what does this error mean?" was a false
    # follow-up. A pronoun with no prior task is a fresh question.
    if (_prior_task_context(context) and words & set(ANAPHORA_PRONOUNS)
            and not has_action_verb(text)):
        # "do it", "change that", "what about them" — continuation.
        if any(m in t for m in ("do", "change", "update", "edit", "what about",
                                "how about", "send", "for", "with", "the")):
            return True
    # Unambiguous continuation phrases stand on their own.
    if any(t.startswith(m) or f" {m} " in f" {t} " for m in _STRONG_FOLLOWUP_MARKERS):
        return True
    # Weak markers ("with the", "for the", "now", "also") are continuation
    # evidence only when a task actually precedes them.
    if _prior_task_context(context) and any(
        t.startswith(m) or f" {m} " in f" {t} " for m in _WEAK_FOLLOWUP_MARKERS
    ):
        return True
    # Prior task context: a short reply after a plan/tool result is a follow-up.
    if _prior_task_context(context) and len(t.split()) <= 12:
        return True
    return False


# ── Memory-recall questions (T48) ─────────────────────────────────────────
# The app's memory store holds the USER's own statements (the turn pair is
# written with `tool_name="user_turn"`). A question about those statements is a
# recall, not an action, and it must reach the DIRECT path - that is the path
# that assembles every memory leg (session + cross-session + file + prior).
# These are pure Tier 0 rules: no store read, no model call.
_WH_OPENERS = ("what", "which", "who", "when", "where", "why", "how")
_MEMORY_STRONG_OPENERS = (
    "do you remember", "do you recall", "do you know my",
    "did i tell you", "did i mention", "did i say",
    "have i told you", "have i mentioned", "what did i",
    "what was my", "what were my", "what is my", "what's my",
    "where is my", "where's my", "who is my", "who's my",
    "when is my", "when's my",
)
_REQUEST_OPENERS = ("can you", "could you", "would you", "will you", "please")
_PREFERENCE_VERBS = (
    "prefer", "like", "want", "use", "choose", "chose", "favorite", "favourite",
)
_MEMORY_WORDS = ("remember", "recall", "said", "told", "mentioned", "stored")


def is_memory_question(text: str) -> bool:
    """Is this a question about something the user already stated/stored?

    The memory system's recall unit is the user's own turn pair. A recall
    question therefore belongs on the direct path, whose assembly includes the
    cross-session leg; the DER step only carries a thin 8-row memory block.

    This rule runs BEFORE the action-verb and follow-up layers so two measured
    misroutes cannot happen again:
      * a noun that contains a verb ("staging deployment" -> "deploy"), and
      * a generic marker inside an instruction ("Answer with the number only"
        -> "with the" -> follow-up).

    Conservative on purpose: it needs a question shape AND a first-person /
    memory signal, and a request to DO something ("can you search my email")
    stays an action. Never raises; free and pure.
    """
    t = (text or "").lower().strip()
    if not t or t.startswith(TOOL_PREFIXES):
        return False
    first = t.split()[0] if t.split() else ""
    strong = any(t.startswith(o) for o in _MEMORY_STRONG_OPENERS)
    is_question = "?" in t or first in _WH_OPENERS or strong
    if not is_question:
        return False
    # A request to act is an action even when it mentions "my" data.
    if any(t.startswith(o) for o in _REQUEST_OPENERS) and has_action_verb(t):
        return False
    if strong:
        return True
    # An action verb means the user wants work done, not a fact recalled.
    if has_action_verb(t):
        return False
    if re.search(r"\b(?:my|our)\b", t):
        return True
    if any(re.search(rf"\b{re.escape(w)}\b", t) for w in _MEMORY_WORDS):
        return True
    has_first_person = re.search(r"\b(?:i|me|we|us)\b", t) is not None
    return has_first_person and any(
        re.search(rf"\b{re.escape(p)}\b", t) for p in _PREFERENCE_VERBS
    )


# A memory WRITE is the user telling IRIS to keep a fact. The write itself
# already happens at turn entry + completion; the router only needs to keep it
# OFF the planning loop. The seed turns ("Remember this for later: ... Just
# acknowledge it briefly.") were running DER for ~141 s because "it" + "for"
# matched the anaphora follow-up branch. A write is not a follow-up task.
_MEMORY_WRITE_OPENERS = (
    "remember this", "remember that", "remember for", "note that",
    "keep in mind", "save this", "store this", "don't forget",
    "do not forget", "make a note",
)


def is_memory_write(text: str) -> bool:
    """Is this an instruction to REMEMBER a fact (not a question)?"""
    t = (text or "").lower().strip()
    if not t or "?" in t or t.startswith(TOOL_PREFIXES):
        return False
    return any(t.startswith(o) for o in _MEMORY_WRITE_OPENERS)


# A broad self-query is not similarity-matched to one fact ("what do you know
# about me" has no lexical overlap with "my card number is ..."). It needs a
# RECENT-FACTS leg, not a narrower similarity threshold. Pure Tier 0.
_BROAD_MEMORY_PHRASES = (
    "what do you know about me", "what have you learned about me",
    "tell me about myself", "what do you remember about me",
    "what have i told you",
)


def is_broad_memory_question(text: str) -> bool:
    """Is this a broad 'what do you know about me' recall question?"""
    t = (text or "").lower().strip()
    # Phrase-based: "Tell me about myself." is a request, not a "?" question.
    return any(p in t for p in _BROAD_MEMORY_PHRASES)


_WH_START = (
    "what", "what's", "whats", "which", "who", "who's", "whose",
    "when", "when's", "where", "where's", "why", "how", "how's",
)


def is_wh_question(text: str) -> bool:
    """Does the message start with a wh-word? A question, even with a verb in
    the tail ("What is the exact name ... Reproduce it exactly."). The direct
    path still owns a ReAct tool loop, so a question that needs a tool can use
    one; it just must not be routed to DER by a tail work verb."""
    t = (text or "").lower().strip()
    return bool(t) and t.split()[0] in _WH_START


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


def is_bounded_content_ask(text: str) -> bool:
    """REQ-24: is this ask answerable by reasoning, with no fact search?

    The user asked for meaning, not for fresh facts — "compare OLED versus
    LCD displays for me", "explain how recursion works", "write a short note
    about sleep". A bounded ask must NOT silently enter the research loop:
    the model answers from its own trained knowledge, or from a light recall
    read (specs/reply-surface-contract REQ-24 AC1).

    Returns True ONLY when every one of these holds:
      * not empty / whitespace,
      * no explicit tool prefix ("Tool:", "RUN:", ...),
      * no explicit web phrasing (``is_web_search_request``),
      * no fresh-data / time marker (latest, news, today, price, weather, ...),
      * no named evidence OBJECT (a file, folder, URL, log, screen, ...).

    A named object means the ask needs that object, and a fresh-data marker
    means the user WANTS the crawl — both stay research asks (REQ-24 AC3).

    Pure and free: no I/O, no model call, no state. Callers may consult it on
    the reply path.
    """
    t = (text or "").lower().strip()
    if not t:
        return False
    if t.startswith(TOOL_PREFIXES):
        return False
    if is_web_search_request(text):
        return False
    if any(m in t for m in FRESH_DATA_MARKERS):
        return False
    if _EVIDENCE_OBJECT_RE.search(t) or any(m in t for m in _EVIDENCE_OBJECT_RAW):
        return False
    return any(v in t for v in CONTENT_ASK_VERBS)


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
    is_memory: bool = False         # recall of the user's own stored statements
    is_memory_write: bool = False   # instruction to remember a fact


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
    # The memory heuristics are SHADOW features now; they do not route.
    # Follow-up FIRST: a wh-word can still be a continuation ("what about the
    # other one"), and anaphora only counts with a prior task.
    if is_followup_to_task(text, context):
        return Tier0Verdict(intent=Tier0Intent.FOLLOWUP)
    # A wh-question is a QUESTION even when a work verb is in the tail
    # ("... Reproduce it exactly"). The direct path still has a ReAct loop.
    if is_wh_question(text):
        return Tier0Verdict(intent=Tier0Intent.QUESTION)
    if has_action_verb(text) or has_work_verb(t):
        return Tier0Verdict(intent=Tier0Intent.ACTION)

    # Default: standalone question -> direct path.
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
        developer: bool = False,
    ) -> DAGPlanGraph:
        """Compile a turn into a DAGPlanGraph (REQ-1, REQ-8).

        Never raises. Routing is Tier 0 (deterministic rules) + Tier 2
        (coordinate-graph ontology) + the continuation lens. The neural
        embedding tier (Tier 1) was removed — the gate routes on rules +
        coordinates, matching the app's coordinate-graph memory.

        ``developer`` is DISPLAY + CAPABILITY, never INTENT (owner, 2026-10-07).
        It used to rewrite every question into an action, so a knowledge
        question in developer mode ran the whole work loop (and "fix the bug"
        only worked there, because the shared verb list had no "fix"). The
        missing verbs now live in the shared layer as WORK_VERBS, so a work
        request routes to the loop in BOTH modes and a question does not, in
        either. Personal mode is the standard and the foundation: the two modes
        may differ in how a turn is DRAWN (matrix rows vs compact cards) and in
        what the agent is ALLOWED to do (edit / read / write its own code) —
        never in what kind of turn it is. ``developer`` is still accepted and
        recorded so those layers can read it; the routing decision ignores it.
        """
        _t0 = time.perf_counter()
        verdict = tier0_classify(text, context)
        graph_developer = bool(developer)

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
                # A recall of the user's own statements is a MEMORY question:
                # the direct path assembles the cross-session legs, so the DAG
                # records the lane and keeps requires_der False. A preference
                # question ("which colour do I prefer") is the canonical case.
                # No memory route here: a recall/write turn is a QUESTION by
                # the general rules. The memory behaviour is the automatic
                # turn pair + pins + recall, not a routing label.
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

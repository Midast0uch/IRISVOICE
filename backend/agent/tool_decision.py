"""
ToolDecisionBox — encapsulated tool resolution + dispatch for DER.

Single interface the DER loop calls for step execution.  Router-agnostic:
all provider selection flows through InferenceRouter role bindings
(reasoning / tool_execution).  Never reads model/swarm snapshots directly.

Spec: specs/der-tool-resolution-blackbox/
  REQ-3 (encapsulated box), REQ-4 (TOOL/REASON/FAIL decisions),
  REQ-5 (structured logging), REQ-6 (failure → DER recovery),
  REQ-7 (per-step failure detection).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Idempotency (REQ-11) ───────────────────────────────────────────────────

_IDEMPOTENCY_TTL = 86400  # seconds (24 hours)

# REQ-27 AC27.2: the engine cache's documented bound. A long-lived backend
# accumulates one entry per distinct question; past this the oldest entry is
# evicted (LRU) rather than growing without limit.
_ENGINE_CACHE_MAX = 256

# REQ-22 AC22.1 / REQ-25 AC25.8: the threshold used with NO engine at all —
# the legacy engine-free path. It is NOT a default for the engine path: an
# engine whose active backend has no measured curve resolves to
# `_NEVER_ENFORCE_THRESHOLD` instead (fail-closed).
_LEGACY_THRESHOLD = 0.85

# Above every possible probability, so a below-threshold comparison can never
# pass: the honest encoding of "refuse enforcement" for a backend with no
# measured entry. Read as "no curve → no confident pick → escalate".
_NEVER_ENFORCE_THRESHOLD = 1.01


def _evidence_cache_component(evidence: Optional[dict]) -> str:
    """REQ-27 AC27.1/AC27.3: the evidence payload rides the cache key.

    Empty sentinel when absent (the always-empty case until REQ-28 supplies a
    payload); a stable content hash when present, so two different payloads
    never collide on the same goal.
    """
    if not evidence:
        return ""
    try:
        return hashlib.sha256(
            json.dumps(evidence, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
    except Exception:
        return ""


def _evidence_prior_component(evidence: Optional[dict]) -> Dict[str, Any]:
    """REQ-28 AC28.1/AC28.2/AC28.8 (T43): the per-candidate prior evidence block.

    Ships UNPOPULATED. No caller supplies `evidence["prior"]` within this
    spec's scope (`specs/wormhole-aperture/` is not implemented), so the block
    is `{}` and behaviour is byte-identical to today (AC28.1 edge).

    Shape — per candidate, SCOPED, never a bare global score (AC28.2/AC28.8)::

        {name: {"lower_bound": float, "observations": int,
                "region": str, "mediator": str, "freshness_s": float}}

    The value is the posterior LOWER BOUND, not a point estimate: a prior is
    allowed to be cautious, never optimistic. An entry that cannot be shaped is
    DROPPED rather than guessed, and a candidate absent from the menu is
    ignored by the applier (REQ-28 edge). Never raises.
    """
    if not evidence or not isinstance(evidence, dict):
        return {}
    prior = evidence.get("prior")
    if not isinstance(prior, dict):
        return {}
    out: Dict[str, Any] = {}
    try:
        for name, raw in prior.items():
            if not isinstance(raw, dict):
                continue
            lb = raw.get("lower_bound")
            if not isinstance(lb, (int, float)) or isinstance(lb, bool):
                continue
            try:
                obs = int(raw.get("observations") or 0)
            except Exception:  # noqa: BLE001
                obs = 0
            try:
                fresh = float(raw.get("freshness_s") or 0.0)
            except Exception:  # noqa: BLE001
                fresh = 0.0
            out[str(name)] = {
                "lower_bound": float(lb),
                "observations": obs,
                "region": str(raw.get("region") or ""),
                "mediator": str(raw.get("mediator") or ""),
                "freshness_s": fresh,
            }
    except Exception:  # noqa: BLE001 — a prior is never worth a crash
        return {}
    return out


# REQ-28 AC28.3 (T45): the prior's maximum share of the blended score. A
# WEIGHTED PRIOR, never a filter and never a decider — a large weight would let
# the graph outvote the model, which is exactly what the AC forbids.
_EVIDENCE_PRIOR_WEIGHT = 0.25


def apply_evidence_prior(
    ds: Optional["DecisionScore"],
    prior: Optional[Dict[str, Any]],
    threshold: float,
) -> Tuple[Optional["DecisionScore"], bool]:
    """REQ-28 AC28.3/AC28.6/AC28.7 (T45): blend the prior into the distribution.

    Returns ``(score, used)``. ``used`` is True only when the prior actually
    CHANGED the outcome, so "retrieved" and "used" stay distinguishable and an
    unused retrieval is never scored as a success (AC28.7).

    Two safety properties, both required:
      * the model's own evidence can OUTVOTE the prior — the blend is weighted,
        so a candidate the model scores far lower is not rescued by a high
        lower bound; and
      * the prior CANNOT raise the winner above `threshold` on its own — when
        the model's confidence was below the threshold, the blended confidence
        is capped below it. A prior may reorder plausible candidates; it may
        never manufacture confidence (AC28.3).

    Absent/empty prior, or no menu candidate carrying evidence → the score is
    returned UNCHANGED with ``used=False`` (AC28.1 edge: byte-identical).
    Never raises.
    """
    if ds is None or not prior:
        return ds, False
    try:
        from backend.agent.decision_engine import CandidateScore, DecisionScore

        dist = tuple(ds.distribution or ())
        if not dist:
            return ds, False
        hits = {c.name: prior[c.name] for c in dist if c.name in prior}
        if not hits:
            return ds, False   # evidence for absent candidates: ignored

        w = _EVIDENCE_PRIOR_WEIGHT
        # A candidate WITHOUT evidence gets a prior of 0.0 — it is not
        # penalised, it simply carries no prior. (Using `hits[name]` directly
        # raised KeyError for every un-evidenced candidate, which the fail-safe
        # below then swallowed: the prior silently never applied.)
        blended = {
            c.name: (1.0 - w) * float(c.prob)
            + w * (
                float(hits[c.name]["lower_bound"]) if c.name in hits else 0.0
            )
            for c in dist
        }
        total = sum(blended.values())
        if total <= 0:
            return ds, False
        probs = {n: v / total for n, v in blended.items()}
        # AC28.7: the prior is a REORDERER. If the ranking is intact it changed
        # nothing, so it must not touch the verdict — a renormalisation nudge
        # is not "used", and an unused retrieval must not be scored a success.
        model_order = [c.name for c in sorted(dist, key=lambda c: -float(c.prob))]
        blended_order = sorted(probs, key=lambda n: -probs[n])
        if model_order == blended_order:
            return ds, False
        best = blended_order[0]
        conf = probs[best]
        if ds.confidence < threshold and conf >= threshold:
            # AC28.3: the prior may not cross the threshold by itself. Cap it
            # just below and let the model's own score decide the ranking.
            conf = max(0.0, threshold - 1e-6)
        new_dist = tuple(
            CandidateScore(
                name=c.name,
                logprob=c.logprob,
                prob=round(float(probs[c.name]), 6),
            )
            for c in dist
        )
        return (
            DecisionScore(
                consumer_id=ds.consumer_id, chosen=best, confidence=conf,
                distribution=new_dist,
                engine_latency_ms=ds.engine_latency_ms,
                retried=ds.retried,
                stage_detail=ds.stage_detail,
            ),
            True,
        )
    except Exception as _e:  # noqa: BLE001 — a prior never breaks a decision
        logger.debug("[TOOL_DECISION] evidence prior failed: %r", _e)
        return ds, False


def apply_ruled_out(
    ds: Optional["DecisionScore"], ruled_out
) -> Optional["DecisionScore"]:
    """REQ-11 AC11.2 (T14): zero a ruled-out tool's probability, then re-pick.

    A graft step resolving after a tool just failed must never be able to
    choose that tool again. The veto is applied at the SCORE (not only as a
    post-hoc refusal) so the recorded distribution is honest: the failed tool
    carries probability 0.0, and the winner is the best SURVIVING candidate.

    Returns None when every candidate is ruled out — the caller escalates to
    the Brain with the veto set attached rather than force-picking a vetoed
    tool (REQ-11 edge case). Pure; never raises.
    """
    if ds is None or not ruled_out:
        return ds
    try:
        from backend.agent.decision_engine import (  # lazy — no import cycle
            CandidateScore,
            DecisionScore,
        )

        blocked = {str(n) for n in ruled_out if n}
        if not blocked:
            return ds
        dist = tuple(
            CandidateScore(name=c.name, logprob=-1e9 if c.name in blocked else c.logprob,
                           prob=0.0 if c.name in blocked else c.prob)
            for c in (ds.distribution or ())
        )
        survivors = [c for c in dist if c.name not in blocked]
        if not survivors:
            return None  # all candidates vetoed → escalate with the veto set
        best = max(survivors, key=lambda c: c.prob)
        return DecisionScore(
            consumer_id=ds.consumer_id,
            chosen=best.name,
            confidence=best.prob,
            distribution=dist,
            engine_latency_ms=ds.engine_latency_ms,
            retried=ds.retried,
            stage_detail=ds.stage_detail,
        )
    except Exception:
        return ds  # a veto rewrite must never lose the decision


def _emit_truncation(field: str, original_len: int, kept_len: int) -> None:
    """REQ-6 AC6.6: a structured truncation event for the silent cuts —
    field + original length, so a truncated input is never decided silently.
    Best-effort; never raises."""
    try:
        logger.info(
            "[TOOL_DECISION] truncation field=%s original_len=%d kept_len=%d",
            field, original_len, kept_len,
        )
    except Exception:
        pass


def _make_idempotency_key(turn_id: str, tool_name: str, params: dict) -> str:
    """Deterministic key for retry-safe deduplication."""
    payload = f"{turn_id}:{tool_name}:{json.dumps(params, sort_keys=True, default=str)}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _is_write_tool(tool_name: str) -> bool:
    """Heuristic: tools with write-side-effect prefixes are WRITE."""
    write_prefixes = (
        "create_", "update_", "delete_", "remove_",
        "send_", "write_", "charge_", "cancel_",
    )
    return any(tool_name.startswith(p) for p in write_prefixes)


# Tools whose success changes the files a later call reads (same set as
# memory_events._EDIT_TOOLS; importing that module costs ~5 s of
# backend.memory init). A successful one bumps ToolDecisionBox._change_epoch,
# so an identical call AFTER it is new work, not a repeat: c04 (2026-10-02,
# conv-622) re-ran its tests after each edit and the dispatcher blocked 22
# test runs and 36 writes as "loop detected".
_FILE_CHANGE_TOOLS = frozenset(
    {"write_file", "edit_file", "create_directory", "delete_file", "move_file"}
)


# specs/tool-decision-engine REQ-16: exact-token triggers for vision relevance.
# Keeps 'view' OUT and 'screenshot' IN — a sighted decision must be earned.
# REQ-3 (T3): the isolated token "what's" is REMOVED — it falsely fired on
# factual search queries ("what's the capital of France" routed to a vision
# menu instead of web search). A "what's" style prompt now triggers vision
# only through a multi-word contextual phrase (below) or a real vision token.
_VISION_TOKENS = frozenset({
    "screenshot", "screen", "screenshot,", "screens", "image", "photo",
    "picture", "pixels", "vision", "diagram", "banner", "logo",
})

# REQ-3 (T3): multi-word contextual phrases. An isolated "what's" fired on
# any question; the phrase must match as a whole, so "what's on screen"
# triggers vision while "what's the weather" does not.
_VISION_PHRASES = (
    "what's on screen", "whats on screen", "what is on screen",
    "what's on my screen", "whats on my screen", "what is on my screen",
    "look at screen", "look at the screen", "look at my screen",
)


# Developer-mode menu priority: the tools a coding step actually uses, with
# ripgrep search right after reading. Only the first (cap - 2) reach the scorer.
_DEV_MENU_ORDER = (
    "read_file", "edit_file", "grep_files", "run_command",
    "write_file", "glob_files", "list_directory", "git_diff", "git_status",
)


def _developer_mode() -> bool:
    try:
        from backend.capabilities import CapabilitySet

        return CapabilitySet.is_developer()
    except Exception:
        return False


def _vision_relevant(goal: str) -> bool:
    """Deterministic vision-relevance feature (REQ-16, amended by REQ-3).

    Token-level match, never substring: 'screenshotting' and 'view' don't
    fire; 'screenshot' / 'image' / 'diagram' do. A "what's" style prompt
    fires only through a multi-word contextual phrase — the isolated token
    is gone (REQ-3: factual search queries must not trigger vision menus).
    """
    toks = {t.strip(",.?!\"'").lower() for t in (goal or "").split()}
    if toks & _VISION_TOKENS:
        return True
    g = (goal or "").lower()
    return any(p in g for p in _VISION_PHRASES)


# Gather signals for OQ-2: these mean "go and fetch something". A step that
# carries one always climbs the ladder, whatever else the goal text says.
_GATHER_SIGNALS = (
    "search", "crawl", "look up", "find", "google", "browse", "download",
    "upload", "fetch", "research",
)
# Remaining action signals. Substring matching is deliberate: a token match would
# miss "searching", "searches", "downloads". A false positive costs nothing but
# the old behaviour (escalate), so the lists lean inclusive.
_ACTION_SIGNALS = _GATHER_SIGNALS + (
    # mutate
    "write", "save", "create", "delete", "move", "rename", "copy",
    "install", "execute", "run ", "send", "email",
    # machine control
    "screenshot", "click", "type ", "capture", "record", "deploy",
    # file-system objects
    "file", "folder", "directory", "dir ", "path",
)
_PATH_SIGNALS = (
    ":\\", ":/", "http",
    ".txt", ".json", ".py", ".md", ".csv", ".pdf", ".ts", ".rs", ".log",
    ".yaml", ".yml", ".toml", ".html", ".xml",
)
# Outcomes no tool can change. Kept narrow on purpose: each phrase states that
# the file system already answered.
_TERMINAL_FAILURE_SIGNALS = (
    "no such file", "does not exist", "not found", "no such directory",
    "permission denied", "access denied", "cannot find",
)


def _goal_needs_action(goal: str) -> bool:
    """Does this step goal give any reason to touch a tool? (OQ-2, 2026-09-24)

    A confident NONE may stop the step ONLY when the goal carries no gather and
    no action signal. The signal is lexical and deterministic on purpose: it is
    cheap, it is auditable, and its false-positive direction is the SAFE one —
    when in doubt it returns True, which keeps the old escalate path exactly as
    it was. Session-345's live regression (conv-128) was a websearch goal where
    a confident NONE was wrong, and "search" is one of these signals, so that
    case still climbs the ladder.
    """
    g = (goal or "").lower()
    if not g:
        return False
    _lexical = any(s in g for s in _ACTION_SIGNALS) or any(
        s in g for s in _PATH_SIGNALS)
    # REQ-29 AC29.4 (T49): shadow-score `needs_action` and record the row.
    # The SAFE direction is STRUCTURAL, not calibrated: the engine may ADD a
    # True ("when in doubt, act") but may never REMOVE one, so a model false
    # negative can never stop a step that needs a tool. The lexical heuristic
    # decides until a TG-13 measured bar says otherwise.
    try:
        from backend.agent import surface_shadow as _ss

        _value, _row = _ss.surface_bool(
            "needs_action", goal,
            brain_bool_fn=lambda: _lexical,
            engine=_ss.AUTO_ENGINE,
        )
        _ss.emit_row(_row)
        if _lexical:
            return True          # the safe direction is never narrowed
        return bool(_value)
    except Exception:  # noqa: BLE001 — the heuristic is the fallback
        return _lexical


def _goal_needs_gather(goal: str) -> bool:
    """True when the goal asks for something to be fetched or researched."""
    g = (goal or "").lower()
    return bool(g) and any(s in g for s in _GATHER_SIGNALS)


def _goal_records_terminal_failure(goal: str) -> bool:
    """True when the goal RECORDS an outcome that no tool can change.

    A recovery step whose text says the file does not exist cannot be fixed by
    asking for a tool again — the filesystem already answered. Live case (turn
    b0da0d28-8ba, engine NONE@0.936): the goal was "RESOLVE: result was not
    verified against the expected output: [Errno 2] No such file or directory:
    'C:/dev/IRISVOICE/does_not_exist_42.txt'", and the escalation still produced
    a full workspace browse.
    """
    g = (goal or "").lower()
    return bool(g) and any(s in g for s in _TERMINAL_FAILURE_SIGNALS)


# ── Propose prompt ──────────────────────────────────────────────────────────

_PROPOSE_PROMPT = """You are the tool-selection policy for one agent step.
GOAL: {goal}

EVIDENCE (memory-conditioned):
{evidence}

AVAILABLE TOOLS (pick the best fit):
{tool_list}

Respond with STRICT JSON only:
{{"kind": "tool"|"reasoning"|"done", "tool": "<tool_name or null>", "params": {{}}, "rationale": "<one line>"}}

Rules:
- If the goal needs an external action, set kind="tool" and pick a tool from AVAILABLE TOOLS.
- If the goal is pure reasoning/text, set kind="reasoning" and tool=null.
- If the goal is fully satisfied, set kind="done".
- params must match the tool's schema. Do not invent tools not in AVAILABLE TOOLS.
"""


# ── Helpers ─────────────────────────────────────────────────────────────────


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Find the first JSON object in *text* and return it.

    Session 248 (live conv-52): command-a sometimes appends a SECOND object
    after the tool decision — ``{"kind":"tool",...},\\n{"kind":"reasoning",...}``.
    The old greedy regex ``\\{[\\s\\S]+\\}`` matched across BOTH objects,
    ``json.loads`` failed on the concatenation, and a perfectly valid tool
    decision was discarded as "unparseable" — the crawl never dispatched and
    the turn died at box resolution. Now: try whole-text first, then scan
    for the first BALANCED object (brace counting that respects strings)."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except Exception:
                        break  # first balanced blob wasn't JSON; try next {
        start = text.find("{", start + 1)
    return None


# ── Decision types ──────────────────────────────────────────────────────────


class DecisionKind(Enum):
    """Outcome of a single tool-resolution attempt."""

    TOOL = "tool"  # a tool was chosen (params validated)
    REASON = "reason"  # model decided no tool needed (valid reasoning step)
    FAIL = "fail"  # resolution could not complete (model dead / unparseable / invalid tool)


@dataclass
class Decision:
    """Result of ToolDecisionBox.resolve()."""

    kind: DecisionKind
    tool: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    source: str = ""  # "llm" | "memory" | "engine" | "fail"
    error: Optional[str] = None  # populated when kind == FAIL

    # specs/tool-decision-engine REQ-9 AC9.1: decision-engine provenance rides
    # every decision the engine participated in (route: engine / memory-fallback
    # / escalated); None on pure-legacy decisions. **Property, not a dataclass
    # field**: test_tool_decision_contract.py::TestDecisionShape pins the field
    # set at exactly {kind, tool, params, rationale, source, error}, and both
    # contracts hold — the kernel-facing shape is unchanged, the channel exists.
    # Shape of the dict itself is pinned by CT-DE-1.
    @property
    def meta(self) -> Optional[Dict[str, Any]]:
        return self.__dict__.get("_meta_value")

    @meta.setter
    def meta(self, value: Optional[Dict[str, Any]]) -> None:
        self.__dict__["_meta_value"] = value


@dataclass
class ToolCallNode:
    """A single tool call in the DER execution tree (REQ-13)."""
    step_id: str = ""
    tool: Optional[str] = None
    args_hash: str = ""
    result_summary: str = ""
    error_type: Optional[str] = None
    source: str = ""  # "llm" | "memory" | "fail"
    split_depth: int = 0
    parent_step_id: Optional[str] = None


@dataclass
class ToolCallTree:
    """Tree of all tool calls across a DER run (REQ-13)."""
    conversation_id: str = ""
    nodes: list[ToolCallNode] = field(default_factory=list)


@dataclass
class DispatchResult:
    """Result of ToolDecisionBox.dispatch().

    ``error_type`` follows REQ-10's structured error envelope:
    - ``transient``      — network blip, 5xx, timeout  → retry with backoff
    - ``rate_limit``     — 429 / explicit rate-limit   → retry with backoff, honour Retry-After
    - ``validation``     — bad params, 400, 422        → re-plan, do NOT retry verbatim
    - ``not_found``      — 404                         → re-plan
    - ``permission``     — 401, 403                    → escalate, do NOT retry
    - ``partial_success`` — some sub-calls failed      → inspect succeeded/failed arrays
    - ``permanent``      — fallback for unknown errors → re-plan
    """

    success: bool
    result: Any = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    duration_ms: int = 0


def _classify_error(error: Optional[str], result: Any = None) -> str:
    """Classify a tool failure into an ``error_type`` (REQ-10).

    Uses heuristic matching on the error message / result structure.
    """
    if not error:
        return "permanent"
    err_lower = error.lower()
    # Transient / rate-limit. A 5xx status is matched as a whole 3-digit code:
    # the old bare "5" keyword matched ANY digit 5 (a line number, a port, a
    # path), so "SyntaxError at line 15" was classified transient and retried.
    if any(kw in err_lower for kw in ("timeout", "timed out", "connection reset")) \
            or re.search(r"\b5\d\d\b", err_lower):
        return "transient"
    if any(kw in err_lower for kw in ("rate limit", "429", "too many requests")):
        return "rate_limit"
    # Re-plan (not worth retrying)
    if any(kw in err_lower for kw in ("not found", "404")):
        return "not_found"
    if any(kw in err_lower for kw in ("permission", "unauthorized", "401", "403", "forbidden")):
        return "permission"
    if any(kw in err_lower for kw in ("validation", "bad request", "400", "422", "invalid")):
        return "validation"
    # Partial success marker
    if isinstance(result, dict) and "succeeded" in result and "failed" in result:
        return "partial_success"
    return "permanent"


# ── ToolDecisionBox ─────────────────────────────────────────────────────────


class ToolDecisionBox:
    """Encapsulated tool decision + dispatch for DER steps.

    Constructor injects all dependencies (never reads global snapshots), so the
    box is fully testable and swarm-refactor-friendly.
    """

    def __init__(
        self,
        router: Any,
        tool_bridge: Any,
        get_available_tools: Callable[[], list[dict]],
        validate_tool_call: Callable[[str, dict], tuple[bool, Optional[str]]],
        infer_fn: Optional[Callable[..., str]] = None,
        memory_lookup_fn: Optional[Callable[[str], Optional[dict]]] = None,
        decision_engine: Any = None,
        decision_threshold: Optional[float] = None,
        use_decision_engine: bool = True,
    ):
        """
        Args:
            router:     InferenceRouter instance (or anything with ``generate(role, …)``).
            tool_bridge: AgentToolBridge instance (or anything with
                         ``execute_tool(name, params) -> dict``).
            get_available_tools: Zero-arg callable returning the current tool
                                 registry as ``[{name, description, params}, …]``.
            validate_tool_call:  ``(tool_name, params) -> (is_valid, error_msg)``.
            infer_fn:            Optional callable for REASON dispatch
                                 ``(prompt, role, …) -> str``.
            memory_lookup_fn:    Optional callable ``(goal_description) -> {tool, rationale} |
                                 None`` for memory-based resolution (pheromone / mycelium /
                                 SourceRegistry).
        """
        self._router = router
        self._tool_bridge = tool_bridge
        self._get_available_tools = get_available_tools
        self._validate_tool_call = validate_tool_call
        self._infer = infer_fn
        self._memory_lookup = memory_lookup_fn or (lambda _goal: None)
        self._idem_cache: Dict[str, tuple[Any, float]] = {}  # key -> (result, expiry_ts) REQ-11
        self._tool_fails: Dict[str, int] = {}  # tool_name -> consecutive failures REQ-12
        self._last_call: Dict[str, tuple[str, bool, int]] = {}  # tool -> (args_hash, success, repeat_count) REQ-12
        # Count of successful file changes (_FILE_CHANGE_TOOLS). Part of every
        # repeat/cache/replay key: the same call on changed files is not a repeat.
        self._change_epoch = 0
        self._tool_call_nodes: list[ToolCallNode] = []  # REQ-13
        # (tool, args_hash) -> how many times that exact call came back with a
        # PERMANENT error. Deliberately NOT cleared by reset_failure_counters():
        # the DER calls that on every _split_step, which is exactly how a
        # permanently-failing call kept escaping its failure budget. Cleared
        # for a given call as soon as that call succeeds.
        self._permanent_failed_args: Dict[tuple, int] = {}
        # REQ-11 AC11.2 (T14): objective -> the tools that have already FAILED
        # for it. This is the SEED veto list the engine must respect when it
        # resolves a graft step. Like _permanent_failed_args above it is
        # deliberately NOT cleared by reset_failure_counters(): the DER calls
        # that on every _split_step, and a veto that a split erases is exactly
        # how recovery re-picks the tool that just failed.
        self._ruled_out_seed: Dict[str, set] = {}
        # REQ-11 AC11.3/AC11.5 (T15): the last `recovery_strategy` consumer
        # verdict for this box ("" until the gate runs). Recorded in meta so
        # calibration can join the strategy against the outcome.
        self._recovery_strategy: str = ""
        # REQ-17 AC17.1 (T21): the LAST failure-triage shadow row — the engine's
        # verdict (with `retry_same` offered) PAIRED with what the counters
        # actually decided. None when no triage row was produced (no engine, or
        # the deterministic double-failure escalate, which pays no model call).
        # Shadow only: the counters remain the deciders (AC17.2).
        self.last_triage_shadow: Optional[Dict[str, Any]] = None
        # REQ-11 AC11.4 (T15): objective -> the tools that failed for it, in
        # order. Two consecutive identical entries means a third identical
        # attempt must escalate instead of being grafted.
        self._recovery_failures: Dict[str, list] = {}
        # specs/tool-decision-engine: resident decision engine (Jev-pattern
        # calibrated Choice). Injected or lazily resolved from the module
        # singleton; disabled entirely by use_decision_engine=False.
        self._decision_engine: Any = decision_engine
        # REQ-22 AC22.1 / REQ-25 AC25.8: the confidence threshold is keyed by
        # the ACTIVE BACKEND. Resolved here, not defaulted: an explicit caller
        # value wins; otherwise the active backend's measured entry; otherwise
        # NO enforcement (fail-closed). The old hardcoded 0.85 was the RETIRED
        # LFM curve and no caller ever passed a value, so every decision was
        # judged against a curve the deployed model never produced. Measured
        # live 2026-09-26: the ledger recorded threshold=0.85 against backend
        # gliner25-decide-onnx-int8, whose measured entry is 0.40.
        self._decision_threshold: float = self._resolve_decision_threshold(
            decision_threshold
        )
        self._use_decision_engine: bool = bool(use_decision_engine)
        self._engine_meta: Optional[Dict[str, Any]] = None  # set by _engine_try
        self._engine_retried: bool = False  # REQ-4 escalated-call retry marker
        # RE site: turn-scoped engine cache — same question (goal + options +
        # class + evidence) inside one box lifetime does not re-evaluate the
        # model. A change to any of those properties invalidates, so decisions
        # stay honest; we pay the model once per distinct question per session,
        # not once per step. REQ-27 (D16): the evidence payload rides the key
        # FROM DAY ONE (empty sentinel until REQ-28 supplies a payload) — a
        # cache hit must never return a verdict computed without it. Bounded
        # with LRU eviction (_ENGINE_CACHE_MAX): the dict was unbounded
        # against the project's own quality bar.
        self._engine_cache: Dict[tuple, Any] = {}
        # REQ-15 continuity: (chosen, kind.value) of the LAST engine-resolved
        # decision this conversation made — read-only frame input, never
        # engine-written (AC15.3: the engine keeps no state of its own).
        self._engine_prev: Optional[Dict[str, Optional[str]]] = None
        # Resolve-scoped step index (REQ-15 AC15.2): node records land at
        # dispatch time, so a second resolve of a pending step must still see
        # it — this counter is resolve-scoped, not dispatch-scoped.
        self._engine_step_index: int = 0

    @staticmethod
    def _run_async(coro, timeout_s: Optional[float] = None):
        """
        Run an async tool coroutine to completion from (possibly) sync context.

        Tool implementations are async (execute_tool is a coroutine).  When this
        dispatch method is called from a thread with NO running event loop,
        asyncio.run() is correct.  When called from inside the DER async loop
        (a loop is already running on this thread), asyncio.run() would raise
        "cannot be called from a running event loop" — so we schedule the
        coroutine on a fresh loop in a worker thread via run_coroutine_threadsafe.

        Session-318 T18 (REQ-11 AC11.1/AC11.3): `timeout_s` bounds the wait.
        Thread path: future.result(timeout) (pre-existing 120s default kept
        when unset). Loop path: wait_for around the coroutine so expiry
        CANCELS it instead of orphaning it. TimeoutError propagates — the
        caller settles the honest timeout envelope.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = asyncio.run_coroutine_threadsafe(coro, asyncio.new_event_loop())
                    return future.result(timeout=timeout_s or 120)
        except RuntimeError:
            pass
        if timeout_s is not None:
            async def _bounded():
                return await asyncio.wait_for(coro, timeout_s)
            return asyncio.run(_bounded())
        return asyncio.run(coro)

    # ── Public API ──────────────────────────────────────────────────────────

    def _bindings_differ(self) -> bool:
        """True when the Brain and the Tool are different models.

        Same model on both roles means there is nobody to coordinate with, so
        every split-only behaviour below is skipped and the path stays exactly
        as it was — no extra call, no extra latency.
        """
        try:
            _r = self._router.resolve("reasoning")
            _t = self._router.resolve("tool_execution")
        except Exception:
            return False
        return (getattr(_r, "id", None), getattr(_r, "model", None)) != (
            getattr(_t, "id", None), getattr(_t, "model", None)
        )

    def _selection_role(self) -> str:
        """Role that converts a step description into a tool call."""
        return "tool_execution" if self._bindings_differ() else "reasoning"

    # ── Decision engine (specs/tool-decision-engine REQ-1..3, REQ-13) ────────

    _DE_DELEGATE = "DELEGATE"  # engine says: below its pay grade
    _DE_NONE = "NONE"          # engine says: no tool applies

    @staticmethod
    def _compose_engine_menu(
        names: list, delegate: str, none: str, cap: int,
    ) -> list:
        """AC21.8: registry names + the two control labels, total width = cap.

        The engine applies its own ``candidate_cap`` truncation internally, so
        the control labels must be RESERVED a slot before the cap, not appended
        after it — appending after made the menu cap+2 wide and the engine's
        internal truncation silently cut DELEGATE/NONE off entirely (neither
        control label ever reached the scorer at the shipped width of 6).
        Registry tools literally named NONE/DELEGATE are dropped first — no
        duplicate labels. Vision-fronted names stay at the front, so they
        survive whenever they fit inside the reserved width.
        """
        controls = [delegate, none]
        reserved = max(cap - len(controls), 0)
        clean = [n for n in names if n and n not in controls]
        return clean[:reserved] + controls

    @staticmethod
    def _vision_tool_names(tools: list) -> list:
        return [
            t.get("name") for t in tools
            if (t.get("category") or "").lower() == "vision" and t.get("name")
        ]

    @staticmethod
    def _order_engine_names(names: list, vision_names: list, goal: str) -> list:
        """THE menu order, before the cap cuts it - one rule for the engine
        route and the shadow scorer, so the shadow measures the menu the
        engine would really score.

        Vision-relevant step: the vision tools go first (REQ-16; the cap must
        never silently delete a sighted option). Developer mode otherwise: the
        coding tools go first - the registry lists vision tools FIRST, so in a
        coding task the cap left the Oracle scoring vision tools while
        read/grep/run never made the menu (execution audit, 2026-09-29; the
        shadow path kept that defect until 2026-10-01: 278 tool_choice rows
        where the Brain's tool was never on the menu).
        """
        if _vision_relevant(goal):
            return list(vision_names) + [n for n in names if n not in vision_names]
        if _developer_mode():
            front = [n for n in _DEV_MENU_ORDER if n in names]
            return front + [n for n in names if n not in front]
        return list(names)

    def _resolve_decision_threshold(self, explicit: Optional[float]) -> float:
        """The confidence threshold for THIS backend (AC22.1 / AC25.8).

        Order:
          1. an explicit caller value (tests and callers that know their curve);
          2. the ACTIVE backend's entry via ``EngineConfig.threshold_for``;
          3. ``_NEVER_ENFORCE_THRESHOLD`` when the active backend has NO entry.

        Step 3 is the fail-closed rule, not a fallback: a probability threshold
        is only meaningful for the distribution it was measured on, so an
        unknown backend must never be judged against some other model's curve.
        A stale calibrated width resolves to None inside ``threshold_for`` too
        (AC25.5) and lands here as "do not enforce".

        With NO engine at all the legacy 0.85 stands, so engine-free unit
        suites keep the behaviour they were written against.
        """
        if explicit is not None:
            return float(explicit)
        cfg = getattr(self._decision_engine, "_cfg", None)
        if cfg is None:
            return _LEGACY_THRESHOLD
        try:
            resolved = cfg.threshold_for("tool_choice")
        except Exception:  # noqa: BLE001 — an unusable config is no curve
            resolved = None
        if resolved is None:
            logger.warning(
                "[TOOL_DECISION] no threshold for the active backend (%s) — "
                "refusing enforcement for tool_choice (AC25.8 fail-closed)",
                getattr(cfg, "backend_id", None) or "unknown",
            )
            return _NEVER_ENFORCE_THRESHOLD
        return float(resolved)

    def _engine(self):
        """The injected decision engine when enabled; None disables cleanly.

        Injection is required (the kernel wires it): the box must NOT lazily
        adopt the module singleton on its own — that would flip behavior in
        unit tests the moment a 350M file lands on disk. Degrade = legacy path
        (AC1.3).
        """
        if not self._use_decision_engine:
            return None
        return self._decision_engine

    def _memory_decision(
        self, all_tools: list[dict], goal: str, conversation_id: str,
        vetoed: Optional[set] = None,
    ) -> Optional[Decision]:
        """Shared memory-fallback step (used by the engine ladder and legacy).

        Returns a TOOL Decision when memory names a valid, registered tool;
        None otherwise. Identical semantics to the inline memory fallback the
        legacy path has always run.

        ``vetoed`` (session 366, track B): the same execution-policy veto the
        engine pick already obeys (memory hint + local-workspace web tools).
        MEMORY MUST OBEY IT TOO - a measured turn chose `crawler_query` for a
        LOCAL goal via `source=memory` and bypassed the veto entirely, because
        this method never saw the set. A vetoed tool is refused here and the
        ladder continues (NONE-commit or escalate), so no route re-introduces it.
        """
        memory_result = (
            self._memory_lookup(goal) if callable(self._memory_lookup) else None
        )
        if memory_result and isinstance(memory_result, dict):
            mtool = memory_result.get("tool")
            mparams = memory_result.get("params", {})
            if mtool and mtool in (vetoed or ()):
                logger.info(
                    "[TOOL_DECISION] memory pick %s VETOED by execution policy "
                    "conv=%s", mtool, conversation_id,
                )
                return None
            if mtool and mtool in {t.get("name") for t in all_tools}:
                is_valid, _verr = self._validate_tool_call(mtool, mparams)
                if is_valid:
                    logger.info(
                        "[TOOL_DECISION] kind=TOOL source=memory tool=%s conv=%s",
                        mtool, conversation_id,
                    )
                    return Decision(
                        kind=DecisionKind.TOOL, tool=mtool, params=mparams,
                        source="memory",
                        rationale=memory_result.get("rationale", ""),
                    )
        return None

    def _engine_try(
        self,
        *,
        engine,
        step: dict,
        goal: str,
        evidence: Optional[dict],
        start: float,
        session_id: str,
        conversation_id: str,
        ruled_out: Optional[set] = None,
        failed_tool: str = "",
    ) -> Optional[Decision]:
        """Calibrated Choice over the pre-filtered candidate set (REQ-2).

        Returns a Decision when the engine fully resolved the step. Returns
        None when the engine declined, degraded, or scored below threshold —
        the caller then runs the legacy ladder, which IS the escalation path
        (AC3.2). Never raises.

        ``ruled_out`` (REQ-11 AC11.1/AC11.2, T14) is the graft failure veto:
        the failed tool carries probability 0.0 and cannot win; when EVERY
        candidate is ruled out the engine declines and the caller escalates to
        the Brain with the veto set attached (never a force-picked vetoed tool).
        """
        try:
            all_tools: list[dict] = self._get_available_tools() or []
            memory_hint = (
                self._memory_lookup(goal) if callable(self._memory_lookup) else None
            )
            pre_filtered = self._apply_pre_filter(all_tools, memory_hint, goal)
            vetoed: set = set((memory_hint or {}).get("veto") or [])
            names = [t.get("name") for t in pre_filtered if t.get("name")]
            if not names:
                return None

            # REQ-16: vision-relevant steps keep the vision tools on the menu
            # even when the memory pre-filter dropped them — the candidate cap
            # must never silently delete a sighted option. Vision tools are
            # kept ahead of the cap truncation for vision-relevant steps.
            # Vision tools are kept ahead of the cap truncation for
            # vision-relevant steps; developer steps rank the coding tools
            # first. The menu WIDTH is unchanged, so the calibrated threshold
            # still applies. One rule, shared with the shadow scorer.
            needs_vision = _vision_relevant(goal)
            names = self._order_engine_names(
                names, self._vision_tool_names(all_tools), goal)
            _cap = getattr(getattr(engine, "_cfg", None), "candidate_cap", 8)
            # AC21.8: compose the menu ONCE — registry names + DELEGATE/NONE,
            # total width = cap. The engine truncates internally to the same
            # cap, so a menu composed wider than cap would lose the control
            # labels at the scorer (the defect this composition fixes).
            # Session 366, track B (2nd half): REMOVE the vetoed names from the
            # MENU, not just guard the pick. Guarding the pick alone turned a
            # low-confidence web pick into an immediate REASON, and for a LOCAL
            # goal that means the step never tries the tool that WOULD work -
            # measured: "engine pick crawler_query VETOED ... -> REASON", then the
            # reply "unable to retrieve the list of files". With the web tools off
            # the menu the engine can land on list_directory/read_file instead.
            # The pick guard above stays as the backstop for any route that still
            # proposes one, and the composed menu keeps its width (controls are
            # reserved and names backfilled), so the calibrated threshold holds.
            names = [n for n in names if n not in vetoed]
            names = self._compose_engine_menu(
                names, self._DE_DELEGATE, self._DE_NONE, _cap)

            # REQ-15: cross-step continuity — the engine sees (only) its own
            # last verdict inside this conversation's run. Read-only: the
            # engine never writes chain state (AC15.3).
            _prev = self._engine_prev or {}
            step_index = self._engine_step_index
            # REQ-16/new-fix: frame carries option descriptions so the 350M can
            # ground its choice in MEANING of the name (cuddled-token read-out
            # alone collapsed to literal name matching — session 344 finding).
            # REQ-6 AC6.6: a truncation that actually cuts content emits a
            # structured event — never decided silently.
            desc_map = {
                t.get("name"): (t.get("description") or "")[:90]
                for t in all_tools if t.get("name")
            }
            for t in all_tools:
                _d = t.get("description") or ""
                if len(_d) > 90:
                    _emit_truncation("option_description", len(_d), 90)
            _goal_raw = goal or ""
            if len(_goal_raw) > 200:
                _emit_truncation("goal", len(_goal_raw), 200)
            # Enumerated feature frame (D9): no prose, deterministic fields.
            frame = {
                "goal": (goal or "")[:200],
                "task_class": (step or {}).get("task_class"),
                "n_candidates": len(names),
                "previous_chosen": _prev.get("chosen"),
                "previous_outcome": _prev.get("outcome"),
                "step_index": step_index,
                "needs_vision": needs_vision,
                "vision_candidates": sum(
                    1
                    for t in all_tools
                    if (t.get("category") or "").lower() == "vision"
                ),
                "option_descriptions": desc_map,
                # REQ-11 AC11.1 (T14): the failure evidence the engine frame
                # carries — the tools this objective has already ruled out.
                "ruled_out": sorted(ruled_out or ()),
                # REQ-28 AC28.1 (T43): the per-candidate prior evidence block.
                # Ships UNPOPULATED — `{}` until a provider supplies
                # `evidence["prior"]`, so the frame is byte-identical to today
                # (AC28.1 edge). Shaped (AC28.2/AC28.8), never a bare score.
                "evidence": _evidence_prior_component(evidence),
            }
            # Turn-scoped cache: a repeat of the identical engine question
            # inside this conversation reuses the measured distribution. The
            # ledger still gets the row (meta carries cache=True), because the
            # second answer is the same decision, not a new one. REQ-27: the
            # evidence payload rides the key (empty sentinel when absent).
            cache_key = (
                (goal or "")[:200],
                tuple(names),
                (step or {}).get("task_class"),
                needs_vision,
                _evidence_cache_component(evidence),
                # T14: the veto set changes the ANSWER, so it must change the
                # key — otherwise a verdict computed without the veto is
                # replayed for a vetoed resolution (same swallow as T37).
                tuple(sorted(ruled_out or ())),
            )
            cached_hit = False
            if cache_key in self._engine_cache:
                # LRU: move the hit to the end so a repeat question stays hot
                ds = self._engine_cache.pop(cache_key)
                self._engine_cache[cache_key] = ds
                cached_hit = True  # carried into meta as cached=True below
            else:
                ds = None
            if ds is None:
                # REQ-22 AC22.3: flat single-pass scoring over the candidate
                # set is the ONLY path — the hierarchical two-stage tree is
                # retired (measured: 26.7 accuracy points and 4.6x latency
                # worse than flat; its lane construction existed solely to
                # feed decide_tree and is deleted with it, which is what
                # cancelled REQ-4/T4). The menu arrives already composed at
                # the cap with both control labels reserved (AC21.8).
                ds = engine.decide("tool_choice", names, frame)
                if ds is not None:
                    self._engine_cache[cache_key] = ds
                    # REQ-27 AC27.2: bounded with LRU eviction — the dict was
                    # unbounded (no eviction) against the project's quality bar.
                    while len(self._engine_cache) > _ENGINE_CACHE_MAX:
                        self._engine_cache.pop(next(iter(self._engine_cache)))
            if ds is None:
                return None  # engine unavailable/timeout — plain degrade
            # REQ-11 AC11.2 (T14): the failed tool scores ZERO — applied to the
            # verdict itself, not just as a post-hoc refusal, so the recorded
            # distribution is honest. All candidates vetoed → decline and let
            # the caller escalate with the veto set attached.
            if ruled_out:
                _vetoed_pick = ds.chosen in ruled_out
                ds = apply_ruled_out(ds, ruled_out)
                if ds is None:
                    logger.info(
                        "[TOOL_DECISION] every candidate ruled out %s -> "
                        "escalate conv=%s", sorted(ruled_out), conversation_id,
                    )
                    self._engine_meta = {
                        "ruled_out": sorted(ruled_out),
                        "failed_tool": failed_tool,
                    }
                    return None
                if _vetoed_pick:
                    logger.info(
                        "[TOOL_DECISION] engine pick vetoed by failure evidence "
                        "-> %s conv=%s", ds.chosen, conversation_id,
                    )
            # REQ-28 AC28.3/AC28.6/AC28.7 (T45): blend the graph prior into the
            # distribution. The veto (AC11.2) is applied FIRST so a ruled-out
            # candidate can never be resurrected by evidence, and the prior is
            # bounded so it cannot cross the threshold on its own. Absent
            # evidence leaves `ds` untouched (AC28.1 edge: byte-identical).
            _ev_prior = frame.get("evidence") or {}
            _ev_present = bool(_ev_prior)
            _ev_used = False
            if _ev_present:
                ds, _ev_used = apply_evidence_prior(
                    ds, _ev_prior, self._decision_threshold)
                if ds is None:
                    return None
            chosen, conf = ds.chosen, ds.confidence
            base_meta: Dict[str, Any] = {
                "engine": getattr(engine, "model_id", None) or "decision-engine",
                "consumer_id": "tool_choice",
                "chosen": chosen,
                "confidence": round(conf, 4),
                "candidates": len(names),
                # Session-345: the candidate count alone cannot explain a wrong
                # answer. Record the menu itself (bounded: <= cap names) so a
                # live miss is auditable — today's NONE@0.935 was inexplicable
                # until the menu could be reconstructed. The composed menu
                # already carries both control labels (AC21.8).
                "candidate_names": list(names),
                "threshold": self._decision_threshold,
                "engine_latency_ms": ds.engine_latency_ms,
                "previous_chosen": _prev.get("chosen"),
                "previous_outcome": _prev.get("outcome"),
                "step_index": step_index,
                "needs_vision": needs_vision,
                "vision_candidates": frame["vision_candidates"],
                "stage_detail": getattr(ds, "stage_detail", None),
                "cached": cached_hit,
                # REQ-6 AC6.4: the full distribution rides the row, so the
                # reliability curve reads the whole menu, not just the winner.
                "distribution": [
                    {"name": c.name, "prob": round(c.prob, 4)}
                    for c in (ds.distribution or ())
                ],
                # REQ-21 AC21.7/AC22.5: the deployed backend identity + model
                # file hash — a variant swap is detectable, historical LFM
                # rows stay distinguishable.
                "model_hash": (
                    engine.model_hash()
                    if callable(getattr(engine, "model_hash", None))
                    else getattr(engine, "model_hash", None)
                ),
                # REQ-11 AC11.5 (T14/T15): the recovery join keys. `failed_tool`
                # is what just failed for this objective; `ruled_out` is the
                # full veto set; `recovery_strategy` is the engine consumer's
                # verdict (REQ-11 AC11.3) — "" until T15's gate runs.
                "failed_tool": failed_tool or None,
                "ruled_out": sorted(ruled_out or ()),
                "recovery_strategy": self._recovery_strategy or None,
                # REQ-28 AC28.6/AC28.7 (T45): PRESENT and USED are recorded
                # separately, so an unused retrieval is never scored as a
                # success and calibration can measure whether the prior helped.
                "evidence_present": _ev_present,
                "evidence_used": _ev_used,
            }

            def _m(route: str, **kw) -> Dict[str, Any]:
                meta = dict(base_meta)
                meta.update(route=route, escalated=route == "escalated")
                meta.update(kw)
                return meta

            # Session-345 (live finding, conv-128): NONE must NOT commit here.
            # REQ-3 AC3.2: chosen ∈ {DELEGATE, NONE} SHALL try the memory
            # fallback, then the legacy ladder — the old code returned REASON
            # immediately for NONE at ANY confidence, so a confident-wrong
            # "no tool applies" (live: NONE@0.869 on a websearch goal) killed
            # the step with no search ever running. NONE now takes the same
            # ladder as DELEGATE; the ledger still distinguishes it (822-824
            # records engine_correct=False when the ladder runs a real tool).
            # Memory vetoes outrank engine confidence (pin_517dfcbda150 stands).
            if chosen in vetoed:
                logger.info(
                    "[TOOL_DECISION] engine pick %s VETOED by memory sanction "
                    "-> REASON conv=%s", chosen, conversation_id,
                )
                _d = Decision(
                    kind=DecisionKind.REASON, source="memory",
                    rationale=(memory_hint or {}).get("rationale")
                    or "vetoed by execution policy",
                )
                _d.meta = _m("memory-fallback", args_valid=None, retried=False)
                return _d
            # Below threshold, DELEGATE, or NONE → memory fallback, then escalate (AC3.2).
            if chosen in (self._DE_DELEGATE, self._DE_NONE) or conf < self._decision_threshold:
                md = self._memory_decision(
                    all_tools, goal, conversation_id, vetoed=vetoed)
                if md is not None:
                    md.meta = _m("memory-fallback", args_valid=None, retried=False)
                    _c = getattr(engine, "counters", None)
                    if _c is not None:
                        _c.memory_fallbacks += 1
                    return md
                # ── OQ-2 RESOLVED 2026-09-24 ────────────────────────────────
                # A NONE at or above threshold now COMMITS as REASON when the
                # goal carries no gather/action signal. Live finding (turn
                # b0da0d28-8ba, recovery step after a failed read_file): the
                # engine answered NONE@0.936 and NONE@0.918, both escalations
                # asked the model again with the tool schemas bound, and the
                # model named `list_directory` anyway — a browse of the whole
                # workspace for a file that does not exist. A correct "no tool
                # needed" could not stop the step. It can now. DELEGATE still
                # escalates, memory still outranks the engine, and a goal with
                # any action/gather signal still climbs the ladder (session-345,
                # conv-128: a confident-wrong NONE on a websearch goal).
                if (
                    chosen == self._DE_NONE
                    and conf >= self._decision_threshold
                    and not _goal_needs_gather(goal)
                    and (
                        not _goal_needs_action(goal)
                        or _goal_records_terminal_failure(goal)
                    )
                ):
                    logger.info(
                        "[TOOL_DECISION] engine NONE@%.3f committed as REASON "
                        "(goal needs no action) conv=%s goal=%r",
                        conf, conversation_id, (goal or "")[:60],
                    )
                    _d = Decision(
                        kind=DecisionKind.REASON, source="engine-none",
                        rationale=(
                            f"engine NONE@{conf:.3f}; the goal needs no tool"
                        ),
                    )
                    _d.meta = _m("engine-none", args_valid=None, retried=False)
                    return _d
                self._engine_meta = _m(
                    "escalated", args_valid=None, retried=False)
                return None
            # Confident real tool → schema-constrained args from the engine.
            from .tool_registry import resolve_tool

            rspec = resolve_tool(chosen)
            if rspec is None:
                return None
            params_schema = {
                "properties": {
                    k: {
                        "type": (v or {}).get("type", "string"),
                        "description": (v or {}).get("description", "")[:120],
                    }
                    for k, v in (rspec.parameters or {}).items()
                },
                "required": [
                    k
                    for k, v in (rspec.parameters or {}).items()
                    if not (v or {}).get("optional", False)
                ],
            }
            # REQ-2 + REQ-10: the fast path first — the goal text maps directly
            # to the 'query' parameter in 0ms for single-param query tools, and
            # a click/tap/press goal maps to the vision element target (T13);
            # complex schemas fall back to generate_args (AC2.4/AC10.2), which
            # degrades to the legacy ladder in production (the ONNX backend
            # scores labels, it does not generate arguments).
            ar = None
            is_fast_path = False
            fast_path_pattern = ""
            _fast = getattr(engine, "fast_path_args", None)
            if callable(_fast):
                ar = _fast(chosen, params_schema, frame)
                is_fast_path = ar is not None
                if is_fast_path:
                    # AC10.3: the pattern id is the calibration join key.
                    fast_path_pattern = getattr(ar, "fast_path", "") or ""
                    logger.info(
                        "[TOOL_DECISION] is_fast_path=true pattern=%s tool=%s "
                        "conv=%s",
                        fast_path_pattern or "unspecified", chosen,
                        conversation_id,
                    )
            if ar is None:
                ar = engine.generate_args("tool_choice", chosen, params_schema, frame)
            if ar.args is None:
                # AC2.5: invalid structure/args escalates the whole decision.
                self._engine_meta = _m(
                    "escalated", args_valid=False, retried=ar.retried)
                return None
            decision = self._validate_as_tool(
                chosen, ar.args, "engine", conversation_id, start, {},
                goal=goal,
            )
            if decision.kind != DecisionKind.TOOL:
                self._engine_meta = _m(
                    "escalated", args_valid=False, retried=ar.retried)
                return None
            decision.meta = _m(
                "engine", args_valid=True, retried=ar.retried,
                is_fast_path=is_fast_path,
                fast_path_pattern=fast_path_pattern,
            )
            ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "[TOOL_DECISION] kind=TOOL source=engine tool=%s conf=%.3f "
                "resolve_ms=%d conv=%s",
                chosen, conf, ms, conversation_id,
            )
            return decision
        except Exception as _e:
            logger.warning(
                "[TOOL_DECISION] engine path failed (%r) — legacy ladder", _e,
            )
            return None


    def _missing_required(self, tool_name: str, params: Optional[dict]) -> list:
        """Required parameters the proposed call did not supply."""
        from .tool_registry import resolve_tool

        spec = resolve_tool(tool_name)
        if spec is None:
            return []
        _p = params or {}
        # authored_by="brain" fields (file bodies) are written after resolution
        # by backend/agent/brain_author.py with the file in view; asking for them
        # here (200 tokens, no file) produced bodies that could not be right.
        return [
            name
            for name, pspec in (spec.parameters or {}).items()
            if isinstance(pspec, dict)
            and not pspec.get("optional", False)
            and pspec.get("authored_by") != "brain"
            and not str(_p.get(name, "")).strip()
        ]

    def _ask_brain_for_params(
        self, goal: str, tool_name: str, missing: list, params: Optional[dict]
    ) -> Optional[dict]:
        """Tool model could not fill required arguments — ask the Brain.

        This is the Brain<->Tool handshake, and it exists because the execution
        model is usually the SMALLER one: it knows which tool to reach for but
        may not infer, say, the exact path or the question text the Brain had in
        mind. Rather than dispatch a call that is certain to fail (observed
        2026-08-16: ask_user_question dispatched with no text, permanent
        failure, which aborted the step that composes the user's answer), it
        asks the Brain for exactly the missing values and retries once.

        Only ever runs when Brain and Tool are different models, and only for a
        call that would otherwise be dispatched incomplete — so the common path
        pays nothing. One round trip, no loop.
        """
        try:
            _prompt = (
                f"GOAL: {goal}\n"
                f"TOOL TO CALL: {tool_name}\n"
                f"ALREADY SUPPLIED: {json.dumps(params or {})}\n"
                f"MISSING REQUIRED ARGUMENTS: {', '.join(missing)}\n\n"
                "Supply ONLY the missing arguments, as strict JSON, using the "
                'goal to determine their values. Respond with: {"args": {...}}'
            )
            text, _t, _tc = self._router.generate(
                "reasoning",
                [{"role": "user", "content": _prompt}],
                temperature=0.0,
                max_tokens=200,
            )
            _m = re.search(r"\{[\s\S]+\}", text or "")
            if not _m:
                return None
            _obj = json.loads(_m.group(0))
            _args = _obj.get("args") if isinstance(_obj, dict) else None
            if not isinstance(_args, dict):
                return None
            merged = dict(params or {})
            for k, v in _args.items():
                if str(v).strip():
                    merged[k] = v
            return merged
        except Exception as _e:
            logger.debug("[TOOL_DECISION] brain clarification failed: %s", _e)
            return None

    def _complete_params_via_brain(self, decision, goal: str):
        """Fill a split-model tool call's missing required args from the Brain.

        No-op when Brain and Tool are the same model, when nothing is missing,
        or when the Brain cannot supply the values.
        """
        if decision.kind != DecisionKind.TOOL or not decision.tool:
            return decision
        if not self._bindings_differ():
            return decision
        missing = self._missing_required(decision.tool, decision.params)
        if not missing:
            return decision
        logger.info(
            "[TOOL_DECISION] split models — tool model proposed %s without %s; "
            "asking the brain",
            decision.tool, ",".join(missing),
        )
        merged = self._ask_brain_for_params(
            goal, decision.tool, missing, decision.params
        )
        if merged is None:
            logger.info(
                "[TOOL_DECISION] brain could not complete %s -> REASON "
                "(dispatching an incomplete call would fail permanently)",
                decision.tool,
            )
            return Decision(kind=DecisionKind.REASON, source="handshake")
        still = self._missing_required(decision.tool, merged)
        if still:
            logger.info(
                "[TOOL_DECISION] %s still missing %s after brain -> REASON",
                decision.tool, ",".join(still),
            )
            return Decision(kind=DecisionKind.REASON, source="handshake")
        decision.params = merged
        logger.info(
            "[TOOL_DECISION] brain completed %s args: %s",
            decision.tool, ",".join(missing),
        )
        return decision

    def resolve(
        self,
        step: dict,
        evidence: Optional[dict] = None,
        session_id: str = "",
        conversation_id: str = "",
        failure: Optional[dict] = None,
    ) -> Decision:
        """Engine-first resolution (specs/tool-decision-engine REQ-2/3/4).

        Order: engine Choice over the pre-filtered candidates → memory fallback
        → legacy single-shot generation ladder (which is the escalation path).
        The kernel-facing DecisionKind set is unchanged: {TOOL, REASON, FAIL}
        (AC3.4); DELEGATE never escapes this method. Provenance rides
        ``Decision.meta``; route-only rows (REASON/FAIL with meta) are recorded
        through the SAME tool-event writer as executions — one row, one writer
        (AC5.1, AC5.4).

        ``failure`` (REQ-11 AC11.1, T14): optional graft failure evidence —
        ``{"failed_tool": str, "error_snippet": str}``. The failed tool is
        recorded against the objective and ruled out of this resolution, so
        recovery cannot re-pick the tool that just failed. Absent = behaviour
        byte-identical to today (the veto list is empty).
        """
        _start = time.perf_counter()
        goal = step.get("description", "") or ""
        # AC11.1/AC11.2: seed the veto from the reported failure AND from any
        # earlier failure for this objective (survives reset_failure_counters).
        _objective = (
            step.get("objective_anchor") or step.get("objective") or goal
        ) or ""
        _failed_tool = ""
        if failure:
            _failed_tool = str(failure.get("failed_tool") or "").strip()
            if _failed_tool:
                self._ruled_out_seed.setdefault(_objective, set()).add(_failed_tool)
        _ruled_out = set(self._ruled_out_seed.get(_objective) or ())
        self._engine_meta = None
        eng = self._engine()
        if eng is not None:
            early = self._engine_try(
                engine=eng, step=step, goal=goal, evidence=evidence,
                start=_start, session_id=session_id,
                conversation_id=conversation_id,
                ruled_out=_ruled_out, failed_tool=_failed_tool,
            )
            if early is not None:
                engine_counts = getattr(eng, "counters", None)
                if engine_counts is not None and getattr(
                    early.meta or {}, "escalated", False
                ):
                    engine_counts.escalations += 1
                self._engine_prev = {
                    "chosen": early.tool or (early.meta or {}).get("chosen"),
                    "outcome": early.kind.value,
                }
                self._engine_step_index += 1
                self._record_decision_row(early, session_id)
                return early
        else:
            eng = None
        decision = self._resolve_legacy(
            step, evidence=evidence, session_id=session_id,
            conversation_id=conversation_id,
        )
        if self._engine_meta is not None and decision.meta is None:
            meta = dict(self._engine_meta)
            meta["retried"] = bool(self._engine_retried)
            meta["decision_latency_ms"] = int((time.perf_counter() - _start) * 1000)
            # Calibration join key: the engine's pick vs what the escalation
            # ACTUALLY ran. Without this the ladder was 'engine said X' with no
            # 'reality ran Y' and the reliability curve was fiction.
            chosen = meta.get("chosen")
            if chosen == self._DE_DELEGATE:
                # engine asked for the brain; the escalation path IS the brain
                meta["final_choice"] = decision.tool or decision.kind.value
                meta["engine_correct"] = True
            elif chosen == self._DE_NONE:
                meta["final_choice"] = decision.tool or decision.kind.value
                meta["engine_correct"] = decision.kind != DecisionKind.TOOL
            else:
                meta["final_choice"] = (
                    decision.tool if decision.kind == DecisionKind.TOOL
                    else decision.kind.value
                )
                meta["engine_correct"] = (
                    decision.kind == DecisionKind.TOOL
                    and decision.tool == chosen
                )
            decision.meta = meta
            counters = getattr(eng, "counters", None) if eng is not None else None
            if counters is not None:
                counters.escalations += 1
        # REQ-15: roll the continuity record forward for the NEXT step.
        self._engine_prev = {
            "chosen": decision.tool or (decision.meta or {}).get("chosen"),
            "outcome": decision.kind.value,
        }
        self._engine_step_index += 1
        self._record_decision_row(decision, session_id)
        return decision

    def _record_decision_row(self, decision: Decision, session_id: str) -> None:
        """Write the route-only ledger row for non-TOOL engine decisions.

        TOOL decisions carry their meta into execute_tool, where the tool event
        row already records the outcome — recording here would double-count
        (D4). Best-effort; the bridge absorbs failures (AC5.3).
        """
        meta = decision.meta
        if not meta or decision.kind == DecisionKind.TOOL:
            return
        bridge = self._tool_bridge
        recorder = getattr(bridge, "record_decision", None)
        if recorder is None:
            return
        try:
            recorder(
                meta,
                kind=decision.kind.value,
                error=decision.error,
                session_id=session_id,
            )
        except Exception as _e:
            logger.debug("[TOOL_DECISION] decision row write failed: %r", _e)

    def record_shadow_tool_choice(
        self,
        *,
        goal: str,
        observed_tool: str,
        observed_params: Optional[dict] = None,
        candidates: Optional[list] = None,
        session_id: str = "",
        conversation_id: str = "",
        threshold: Optional[float] = None,
        async_: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """REQ-16 AC16.2 (T20): shadow-score a tool choice made OUTSIDE the box.

        The RespondDirect ReAct loop picks tools with native function calling
        (`agent_kernel.py:3132-3176`), bypassing ``resolve()`` — so that traffic
        never reached the ledger and the reliability curve was built on a biased
        subset. This records the engine's OWN Choice over the same candidate
        menu, PAIRED with the tool the Brain actually called (``brain_choice``),
        so calibration sees 100% of tool-choice traffic (CT-DEI-7).

        Shadow only: nothing here changes what runs. ``async_=True`` (the
        kernel's mode) runs the scoring on a daemon thread, so the fast chat
        path pays ZERO added latency (REQ-16 edge case). Returns the row in sync
        mode; None when async, when there is no engine, or when no candidates
        are known — a missing engine must never fabricate a row (T17/T18
        convention). Never raises.

        The frame deliberately does NOT carry ``observed_tool``: telling the
        engine what the Brain picked would make the row a self-fulfilling
        measurement instead of an independent one.
        """
        if async_:
            try:
                threading.Thread(
                    target=self.record_shadow_tool_choice,
                    kwargs={
                        "goal": goal, "observed_tool": observed_tool,
                        "observed_params": observed_params,
                        "candidates": candidates, "session_id": session_id,
                        "conversation_id": conversation_id,
                        "threshold": threshold, "async_": False,
                    },
                    daemon=True, name="shadow-tool-choice",
                ).start()
            except Exception as _e:  # noqa: BLE001 — an observer never blocks
                logger.debug("[TOOL_DECISION] shadow thread failed: %r", _e)
            return None
        try:
            eng = self._engine()
            if eng is None:
                return None
            registry = self._get_available_tools() or []
            names = [
                n for n in (
                    candidates if candidates is not None
                    else [t.get("name") for t in registry]
                ) if n
            ]
            if not names:
                return None
            # The engine route's order rule, over the tools the Brain was
            # OFFERED (callers pass them): a vision tool the Brain never had
            # is not put on the menu.
            names = self._order_engine_names(
                names,
                [n for n in self._vision_tool_names(registry) if n in names],
                goal or "",
            )
            _cap = getattr(getattr(eng, "_cfg", None), "candidate_cap", 6)
            menu = self._compose_engine_menu(
                names, self._DE_DELEGATE, self._DE_NONE, _cap)
            frame = {
                "goal": (goal or "")[:200],
                "n_candidates": len(menu),
                "source": "respond_direct",
            }
            ds = eng.decide("tool_choice", menu, frame)
            if ds is None:
                return None
            row: Dict[str, Any] = {
                "consumer_id": "tool_choice",
                "engine": getattr(eng, "model_id", None) or "decision-engine",
                "chosen": ds.chosen,
                "confidence": round(float(ds.confidence), 4),
                "candidates": [
                    {"name": c.name, "prob": round(c.prob, 4)}
                    for c in (ds.distribution or ())
                ],
                "threshold": (
                    self._decision_threshold if threshold is None
                    else float(threshold)
                ),
                "engine_latency_ms": ds.engine_latency_ms,
                # The shadow PAIR: the engine's pick vs the Brain's actual call.
                "brain_choice": observed_tool,
                "brain_params": observed_params or {},
                "conversation_id": conversation_id or None,
                "source": "respond_direct",
                "shadow": True,
            }
            self._record_shadow_row(row, session_id=session_id)
            return row
        except Exception as _e:  # noqa: BLE001 — a shadow never raises
            logger.debug("[TOOL_DECISION] shadow tool-choice failed: %r", _e)
            return None

    def _resolve_legacy(
        self,
        step: dict,
        evidence: Optional[dict] = None,
        session_id: str = "",
        conversation_id: str = "",
    ) -> Decision:
        """Pre-engine single-shot resolution (now also the escalation path)."""
        """Resolve a DER step to a tool (or reason / fail).

        Two-phase *retrieve-then-decide* (REQ-4 AC6):
          1. Narrow candidate toolset via memory (pheromone / mycelium).
          2. Let the model (via ``router.generate("reasoning", …)``) decide.
          3. If the model is dead / unparseable, consult memory again.
          4. Only if memory also yields nothing → ``FAIL``.

        Never silently substitutes "reason" when resolution fails
        (REQ-4 AC5).
        """
        _start = time.perf_counter()
        goal = step.get("description", "") or ""
        _ev = evidence or {}
        _ev_str = json.dumps(_ev, ensure_ascii=False)
        log_extra: dict[str, Any] = {"session_id": session_id, "conversation_id": conversation_id}

        # ── 1. Get available tools ─────────────────────────────────────
        all_tools: list[dict] = self._get_available_tools() or []

        # ── 2. Memory pre-filter (REQ-4 AC6) ───────────────────────────
        memory_hint = self._memory_lookup(goal) if callable(self._memory_lookup) else None
        pre_filtered = self._apply_pre_filter(all_tools, memory_hint, goal)
        # pin_517dfcbda150: the memory layer may explicitly veto heavy gather
        # tools (crawler_query/web_search) when the physics sanction says the
        # agent is converged / budget-exhausted / provider-loaded. The veto is
        # enforced below even if the model proposes a vetoed tool anyway.
        _vetoed: set[str] = set((memory_hint or {}).get("veto") or [])

        def _memory_allowed(_mres):
            """Session 366, track B: refuse a memory-suggested tool the execution
            policy vetoed, so the memory fallbacks obey the SAME veto as the
            engine path. Returns the result unchanged, or None when vetoed."""
            if isinstance(_mres, dict) and _mres.get("tool") in _vetoed:
                logger.info(
                    "[TOOL_DECISION] memory pick %s VETOED by execution policy "
                    "conv=%s", _mres.get("tool"), conversation_id,
                )
                return None
            return _mres

        # (Session 366: the LOCAL-workspace phrase-list veto was REMOVED as debt.
        # The arbiter is the Oracle's `web_intent` consumer through _mem_lookup,
        # which only pre-commits crawler_query for a CONFIDENT web-intent goal.
        # `_vetoed` now carries the memory/physics sanction only. See the removal
        # note above _DEPTH_ROUTES.)

        # ── 3. Build propose prompt and call router ────────────────────
        tool_list = "\n".join(
            f"- {t.get('name', '?')}: {t.get('description', '')[:200]}"
            for t in pre_filtered
        ) or "(none available)"

        propose_prompt = _PROPOSE_PROMPT.format(
            goal=goal,
            evidence=_ev_str,
            tool_list=tool_list,
        )
        messages = [
            {"role": "system", "content": "You are a precise tool-selection assistant."},
            {"role": "user", "content": propose_prompt},
        ]

        # Convert to provider function-calling schema before sending. The
        # internal descriptors use a bare property map, which is not valid JSON
        # Schema — a tool with a property named "description" (e.g.
        # vision_detect_element) makes Cohere reject the whole request with a
        # 422. See tool_registry.to_function_schema for the full rationale.
        from .tool_registry import to_function_schema

        _fn_tools = to_function_schema(pre_filtered) if pre_filtered else None

        # Which model turns this step into a tool call. When Brain and Tool are
        # the SAME model there is nothing to coordinate, so we stay on the
        # reasoning binding and behave exactly as before — no extra hop, no
        # extra latency. When they are DIFFERENT models the tool binding owns
        # this: picking a tool and shaping its arguments is the Tool model's
        # actual job (2026-08-16).
        _sel_role = self._selection_role()

        # No call-site output cap (execution audit B2, 2026-09-29). This call
        # writes the tool ARGUMENTS, and for write_file those are the whole
        # file body: the old max_tokens=500 made any file over ~1,500 chars
        # impossible to write. The router's own default still bounds a
        # runaway generation, and its window cap already reserves room for it.
        try:
            text, _thinking, tool_calls = self._router.generate(
                _sel_role,
                messages,
                tools=_fn_tools,
                temperature=0.2,
            )
            # REQ-4 (specs/tool-decision-engine, session-342 E5): the planner
            # died cleanly on an EMPTY completion ("[TOOL_DECISION_FAIL]
            # Empty response from Ollama") because this path had no retry while
            # the synthesis path had one. One bounded retry, no loop; the retry
            # flag lands in the escalation meta row.
            self._engine_retried = False
            if not (text and text.strip()) and not tool_calls:
                self._engine_retried = True
                logger.info(
                    "[TOOL_DECISION] empty completion — one bounded retry "
                    "conv=%s",
                    conversation_id,
                )
                text, _thinking, tool_calls = self._router.generate(
                    _sel_role,
                    messages,
                    tools=_fn_tools,
                    temperature=0.2,
                )

            # ── 4. Parse response ──────────────────────────────────────
            # Prefer provider-native tool_calls when available
            if tool_calls and isinstance(tool_calls, list) and len(tool_calls) > 0:
                tc = tool_calls[0]
                if isinstance(tc, dict):
                    tc_tool = tc.get("function", {}).get("name") or tc.get("name")
                    tc_args = (
                        tc.get("function", {}).get("arguments", {})
                        or tc.get("input", {})
                    )
                    if isinstance(tc_args, str):
                        try:
                            tc_args = json.loads(tc_args)
                        except Exception:
                            tc_args = {}
                    if tc_tool and tc_tool in {t.get("name") for t in all_tools}:
                        if tc_tool in _vetoed:
                            logger.info(
                                "[TOOL_DECISION] tool_call %s VETOED by memory "
                                "sanction -> REASON conv=%s",
                                tc_tool, conversation_id,
                            )
                            return Decision(
                                kind=DecisionKind.REASON, source="memory",
                                rationale=(memory_hint or {}).get("rationale")
                                or "vetoed by execution policy",
                            )
                        return self._validate_as_tool(tc_tool, tc_args, "llm",
                                                       conversation_id, _start, log_extra,
                                                       goal=goal)

            # Parse text output as JSON
            data = _extract_json(text) if text else None
            if data:
                kind = str(data.get("kind", "")).lower()
                tool_name = data.get("tool")
                params = data.get("params", {})
                rationale = data.get("rationale", "")

                if kind in ("reasoning", "done") and not tool_name:
                    ms = int((time.perf_counter() - _start) * 1000)
                    logger.info(
                        "[TOOL_DECISION] kind=REASON source=llm tool=null "
                        "rationale=%s resolve_ms=%d conv=%s",
                        rationale[:120], ms, conversation_id,
                    )
                    return Decision(kind=DecisionKind.REASON, source="llm",
                                    rationale=rationale)

                if kind == "tool" and tool_name:
                    if tool_name in _vetoed:
                        logger.info(
                            "[TOOL_DECISION] kind=tool %s VETOED by memory "
                            "sanction -> REASON conv=%s",
                            tool_name, conversation_id,
                        )
                        return Decision(
                            kind=DecisionKind.REASON, source="memory",
                            rationale=(memory_hint or {}).get("rationale")
                            or "vetoed by execution policy",
                        )
                    if tool_name not in {t.get("name") for t in all_tools}:
                        ms = int((time.perf_counter() - _start) * 1000)
                        logger.warning(
                            "[TOOL_DECISION] kind=FAIL source=llm "
                            "tool=%s — not in registry resolve_ms=%d conv=%s",
                            tool_name, ms, conversation_id,
                        )
                        return Decision(
                            kind=DecisionKind.FAIL, source="llm",
                            error=f"Tool '{tool_name}' not in available tool registry",
                        )
                    return self._validate_as_tool(tool_name, params, "llm",
                                                   conversation_id, _start, log_extra,
                                                   goal=goal)

            # ── 5. Model failure → consult memory (REQ-4 AC3) ──────────
            # Session 247: log the raw response when parsing produced nothing
            # — "Model unavailable" was misleading (the model DID answer; its
            # output just didn't parse into a tool decision). Bounded excerpt
            # keeps this debug-only and safe.
            if text:
                logger.debug(
                    "[TOOL_DECISION] unparseable resolver response conv=%s "
                    "raw[:600]=%r",
                    conversation_id, text[:600],
                )
            memory_result = _memory_allowed(
                self._memory_lookup(goal) if callable(self._memory_lookup) else None
            )
            if memory_result and isinstance(memory_result, dict):
                mtool = memory_result.get("tool")
                mparams = memory_result.get("params", {})
                mrationale = memory_result.get("rationale", "")
                if mtool and mtool in {t.get("name") for t in all_tools}:
                    is_valid, verr = self._validate_tool_call(mtool, mparams)
                    if is_valid:
                        ms = int((time.perf_counter() - _start) * 1000)
                        logger.info(
                            "[TOOL_DECISION] kind=TOOL source=memory tool=%s "
                            "resolve_ms=%d conv=%s",
                            mtool, ms, conversation_id,
                        )
                        return Decision(
                            kind=DecisionKind.TOOL, tool=mtool, params=mparams,
                            source="memory", rationale=mrationale,
                        )

            # ── 6. Memory also empty → FAIL (REQ-4 AC4) ────────────────
            # HONEST ERROR (session 260). This said "Model unavailable" for
            # every arrival here, including the common case where the model
            # answered perfectly well and simply did not emit a tool decision.
            # Session 247 already noticed and added the raw-response debug log
            # above, but left the message itself lying -- so the log said the
            # model replied while the error said it was unavailable, and the
            # step failure reported to the user named the wrong cause.
            # Measured live 2026-08-26 (conv-64): usage recorded
            # prompt=6465 completion=500, 429s=0, and the raw reply began
            # "1. Step 1 already listed all files in the backend directory".
            # The model was there. It just answered instead of deciding.
            # REQ-35 AC1/AC3: the model REPLIED and simply did not name a
            # tool. That is a terminal answer for this step -- "no tool
            # needed" -- and DecisionKind.REASON is the shape this codebase
            # already has for it: "model decided no tool needed (valid
            # reasoning step)". The kernel routes REASON to _run_step_direct
            # (agent_kernel: "REASON: item.tool stays None -> falls to
            # _run_step_direct below"), which runs the step as a direct
            # inference and returns a result through the NORMAL outcome path.
            #
            # AC2/AC4 hold BY CONSTRUCTION: nothing here marks the step
            # successful. The reply changes what happens next -- direct
            # execution instead of a hard failure -- and the loop still
            # decides whether the objective was met. Reached only AFTER the
            # memory lookup above has had its chance to name a real tool.
            #
            # A genuinely dead model still FAILS below: no text, no reply, no
            # terminal answer to honour.
            if text and text.strip():
                ms = int((time.perf_counter() - _start) * 1000)
                logger.info(
                    "[TOOL_DECISION] kind=REASON source=llm-noparse "
                    "resolve_ms=%d conv=%s (model replied without naming a "
                    "tool; running the step directly)",
                    ms, conversation_id,
                )
                return Decision(
                    kind=DecisionKind.REASON, source="llm-noparse",
                    rationale=text.strip()[:500],
                )

            err_msg = (
                "No response from the model, and memory had no suggestion for "
                "this step."
            )
            ms = int((time.perf_counter() - _start) * 1000)
            logger.warning(
                "[TOOL_DECISION_FAIL] kind=FAIL source=fail "
                "error=%s resolve_ms=%d conv=%s",
                err_msg, ms, conversation_id,
            )
            return Decision(kind=DecisionKind.FAIL, source="fail", error=err_msg)

        except Exception as exc:
            # Exception during LLM call → consult memory before FAIL
            memory_result = _memory_allowed(
                self._memory_lookup(goal) if callable(self._memory_lookup) else None
            )
            if memory_result and isinstance(memory_result, dict):
                mtool = memory_result.get("tool")
                mparams = memory_result.get("params", {})
                mrationale = memory_result.get("rationale", "")
                if mtool and mtool in {t.get("name") for t in all_tools}:
                    is_valid, verr = self._validate_tool_call(mtool, mparams)
                    if is_valid:
                        ms = int((time.perf_counter() - _start) * 1000)
                        logger.info(
                            "[TOOL_DECISION] kind=TOOL source=memory tool=%s "
                            "resolve_ms=%d conv=%s (after exception)",
                            mtool, ms, conversation_id,
                        )
                        return Decision(
                            kind=DecisionKind.TOOL, tool=mtool, params=mparams,
                            source="memory", rationale=mrationale,
                        )
            ms = int((time.perf_counter() - _start) * 1000)
            logger.warning(
                "[TOOL_DECISION_FAIL] kind=FAIL source=fail "
                "error='%s' resolve_ms=%d conv=%s",
                str(exc)[:200], ms, conversation_id,
                exc_info=True,  # a bare message here made a TypeError in this
                                # path undiagnosable from the logs (2026-08-16)
            )
            return Decision(kind=DecisionKind.FAIL, source="fail", error=str(exc)[:500])

    def dispatch(
        self,
        decision: Decision,
        session_id: str = "",
        conversation_id: str = "",
        reasoning_prompt: str = "",
        turn_id: str = "",  # for idempotency (REQ-11)
        timeout_s: Optional[float] = None,  # Session-318 T18 (REQ-11 AC11.1)
    ) -> DispatchResult:
        """Execute a resolved decision.

        - ``TOOL``:   calls ``tool_bridge.execute_tool`` (REQ-6 AC3).
        - ``REASON``: calls ``infer_fn`` for direct reasoning.
        - ``FAIL``:   **never dispatched** — callers route to DER recovery
                      (REQ-6 AC2).  Raises ``ValueError`` as a safety net.

        ``turn_id`` enables idempotency-key generation (REQ-11): if provided
        and the tool is a ``write`` tool, the result is cached so a retry
        with the same key returns the cached result (no duplicate side-effect).
        """
        if decision.kind == DecisionKind.FAIL:
            raise ValueError(
                "dispatch() called with FAIL decision — callers must route "
                "FAIL to DER recovery (_der_handle_step_failure), not dispatch."
            )

        start = time.perf_counter()
        log_extra: dict[str, Any] = {
            "session_id": session_id,
            "conversation_id": conversation_id,
        }

        try:
            if decision.kind == DecisionKind.TOOL:
                if not self._tool_bridge:
                    raise RuntimeError("ToolDecisionBox has no tool_bridge injected")

                # ── Duplicate-call detection (REQ-12 AC2) — before execute ──
                # "@epoch": the same args on changed files are a new call.
                _raw_hash = hashlib.md5(
                    json.dumps(decision.params, sort_keys=True, default=str).encode()
                ).hexdigest()[:12]
                _args_hash = f"{_raw_hash}@{self._change_epoch}"
                _prev = self._last_call.get(decision.tool)  # (args_hash, success)
                # Duplicate: same args, last was success, AND we've already
                # allowed one silent repeat (idempotency-safe retry).
                # Third+ identical call → loop signal.
                _repeat = 0
                _prev = self._last_call.get(decision.tool)  # (args_hash, success, repeat_count)
                # pin_42ddd255162d: crawler_query is exempt from the dispatcher's
                # repeat guard — the crawl JobRegistry dedupe is the authoritative
                # anti-loop for crawls (a same-query dispatch legitimately returns
                # the cached pages). Applying BOTH guards double-punishes a cached
                # re-dispatch into a "failure", which the DER then splits on.
                # Read-only, idempotent tools (get_rendered_documents etc.) are
                # ALSO exempt: they have no side effects, so looping on them is
                # harmless, and blocking them starves the DER's ability to re-read
                # gathered docs (the observed 15:45+ loop: LLM kept resolving
                # get_rendered_documents → DUPLICATE CALL → step never committed
                # → agent gave up and asked the user).
                # read_command_output: polling a running command with the same
                # handle is how the agent watches it; its output changes, and
                # the node's own "unchanged result" detector catches a real loop.
                _IDEMPOTENT_READ_TOOLS = frozenset(
                    {"get_rendered_documents", "recall_memory", "read_file", "read_command_output"}
                )
                if (
                    decision.tool
                    and decision.tool != "crawler_query"
                    and decision.tool not in _IDEMPOTENT_READ_TOOLS
                    and _prev
                    and _prev[0] == _args_hash
                    and _prev[1]
                ):
                    _repeat = _prev[2]
                    if _repeat >= 1:  # second+ consecutive repeat → loop
                        logger.warning(
                            "[TOOL_DISPATCH] DUPLICATE CALL tool=%s args=%s repeat=%d conv=%s",
                            decision.tool, _args_hash, _repeat, conversation_id,
                        )
                        dr = DispatchResult(
                            success=False,
                            error=f"Duplicate call to '{decision.tool}' with identical args ({_repeat+1}x) — loop detected",
                            error_type="permanent", duration_ms=0,
                        )
                        dr.duration_ms = int((time.perf_counter() - start) * 1000)
                        return dr

                # ── Update _last_call repeat counter BEFORE idempotency ──
                # (so cache hits still increment the repeat counter)
                if decision.tool:
                    _prev = self._last_call.get(decision.tool)
                    if _prev and _prev[0] == _args_hash and _prev[1]:
                        # Same args, previous was successful → increment repeat
                        self._last_call[decision.tool] = (_args_hash, False, _prev[2] + 1)
                    elif _prev and _prev[0] == _args_hash:
                        # Same args but previous failed → repeat without success
                        self._last_call[decision.tool] = (_args_hash, False, _prev[2])
                    else:
                        # Different args or new tool → start fresh
                        self._last_call[decision.tool] = (_args_hash, False, 0)

                # ── Idempotency check (REQ-11) ──────────────────────────
                _ik = ""
                if turn_id and decision.tool:
                    _ik = _make_idempotency_key(
                        f"{turn_id}@{self._change_epoch}", decision.tool, decision.params
                    )
                    _now = time.time()
                    if _ik in self._idem_cache and self._idem_cache[_ik][1] < _now:
                        del self._idem_cache[_ik]
                    if _ik in self._idem_cache:
                        _cached_result, _cached_expiry = self._idem_cache[_ik]
                        logger.info(
                            "[TOOL_DISPATCH] idempotency cache HIT key=%s tool=%s conv=%s",
                            _ik, decision.tool, conversation_id,
                        )
                        dr = DispatchResult(
                            success=True,
                            result=_cached_result,
                            duration_ms=0,
                            error_type=None,
                        )
                        dr.duration_ms = int((time.perf_counter() - start) * 1000)
                        # Update _last_call success (cache hit = previous succeeded)
                        if decision.tool and _args_hash:
                            _prev = self._last_call.get(decision.tool)
                            if _prev and _prev[0] == _args_hash:
                                self._last_call[decision.tool] = (_args_hash, True, _prev[2])
                        return dr

                # ── Per-tool failure budget (REQ-12 AC1) — before execute ──
                _budget = 3
                if decision.tool and self._tool_fails.get(decision.tool, 0) >= _budget:
                    logger.warning(
                        "[TOOL_DISPATCH] BUDGET EXCEEDED tool=%s fails=%d conv=%s",
                        decision.tool, _budget, conversation_id,
                    )
                    dr = DispatchResult(
                        success=False,
                        error=f"Tool '{decision.tool}' exceeded consecutive failure budget ({_budget}). Do not call again.",
                        error_type="permanent", duration_ms=0,
                    )
                    dr.duration_ms = int((time.perf_counter() - start) * 1000)
                    return dr

                # ── Permanent-failure replay guard — after the budget ───────
                # Deliberately placed AFTER the budget check above so it never
                # preempts it: within one box the budget is the authority and
                # its "exceeded" message must win. This guard covers the gap
                # the budget cannot: reset_failure_counters() wipes the budget
                # on every DER _split_step, so a call that fails permanently
                # can be re-dispatched forever across splits. Observed
                # 2026-09-03 (pid 25120) as ask_user_question dispatched four
                # times with an empty `text` — each rejected by the bridge with
                # "Question text is required", each feeding a DER split that
                # reset the very budget meant to stop it.
                #
                # Same threshold as the budget, so a failing call gets exactly
                # the same number of attempts as before; the only change is
                # that the count now survives a reset. A permanent error is
                # non-retryable by definition, so an identical retry can only
                # be a loop. Transient failures are untouched — retrying those
                # is legitimate recovery.
                _replay_limit = 3
                if (
                    decision.tool
                    and self._permanent_failed_args.get(
                        (decision.tool, _args_hash), 0
                    ) >= _replay_limit
                ):
                    logger.warning(
                        "[TOOL_DISPATCH] REPLAY OF PERMANENT FAILURE tool=%s "
                        "args=%s attempts=%d conv=%s",
                        decision.tool, _args_hash,
                        self._permanent_failed_args[(decision.tool, _args_hash)],
                        conversation_id,
                    )
                    dr = DispatchResult(
                        success=False,
                        error=(
                            f"'{decision.tool}' already failed permanently with "
                            "these exact arguments — re-issuing it cannot "
                            "succeed. Change the arguments or use a different "
                            "tool."
                        ),
                        error_type="permanent", duration_ms=0,
                    )
                    dr.duration_ms = int((time.perf_counter() - start) * 1000)
                    return dr

                # execute_tool is a coroutine — it MUST be awaited, not called
                # bare (a bare call returns a coroutine object, which previously
                # surfaced as "Unexpected tool result type: <class 'coroutine'>"
                # and failed every tool dispatch instantly).  Run it
                # loop-aware: asyncio.run() when no loop is active in this
                # thread, otherwise run it in a worker thread via
                # run_coroutine_threadsafe so we don't clash with the DER loop
                # already driving this call.
                # session_id MUST be threaded through. Without it execute_tool
                # falls back to its default "unknown" (tool_bridge.py:1010), and
                # every session-addressed side effect silently goes nowhere:
                # crawl UI events (open_tab / crawler_started /
                # crawler_page_fetched / crawler_complete) are broadcast to
                # get_clients_for_session("unknown"), which matches no client.
                # That is why an agent-driven web search answered in chat while
                # the browser panel never moved, while the user-initiated
                # gateway crawl — which passes a real session — animated fine.
                # Diagnosed from a live log line:
                #   [crawl-ui] first event CRAWLER_STARTED for session='unknown' clients=0
                result = self._run_async(
                    self._tool_bridge.execute_tool(
                        decision.tool, decision.params, session_id=session_id,
                        decision_meta=getattr(decision, "meta", None),
                    ),
                    timeout_s=timeout_s,
                )

                if not isinstance(result, dict):
                    result = {"success": False, "error": f"Unexpected tool result type: {type(result)}"}
                success = result.get("success", False)
                error = result.get("error")

                # ── Track consecutive failures (REQ-12 AC1) ────────────────
                if decision.tool:
                    _et = result.get("error_type") if isinstance(result, dict) else None
                    if success:
                        self._tool_fails.pop(decision.tool, None)
                        # This exact call demonstrably CAN succeed — drop any
                        # permanent-failure tally against it.
                        if _args_hash:
                            self._permanent_failed_args.pop(
                                (decision.tool, _args_hash), None
                            )
                    elif _et == "aborted":
                        # REQ-19 AC4: a user abort is not tool unreliability —
                        # it never counts against the failure budget. (The
                        # tool-decision veto memory is written only from
                        # web-gather budget policy, so an abort cannot enter
                        # it through this path either.)
                        pass
                    else:
                        self._tool_fails[decision.tool] = self._tool_fails.get(decision.tool, 0) + 1

                # REQ-10 AC1: prefer an explicit error_type from the tool's
                # structured envelope; fall back to heuristic classification only
                # when the tool didn't supply one.
                _explicit_et = result.get("error_type") if isinstance(result, dict) else None
                _result_val = result.get("result")
                if _result_val is None and "result" not in result:
                    # No dedicated "result" key — the tool envelope itself IS the
                    # result (e.g. crawler_query returns
                    # {success, content, sources, url, trust, ...}). Pass the
                    # WHOLE envelope so _format_tool_result extracts the content
                    # text for the step result AND _capture_tool_result persists
                    # sources/har_path for the DOCUMENT_RENDER prism card.
                    # pin: dropping it here (old `result.get("result")` → None)
                    # starved every crawl step: empty step_result → verify FAILED
                    # → split → children → physics veto → agent looped and the
                    # card stayed empty despite real gathered content.
                    _result_val = result
                dr = DispatchResult(success=success, result=_result_val,
                                    error=error, duration_ms=0,
                                    error_type=_explicit_et or _classify_error(error, result))

                # REQ-15 AC2: a tool result is NEVER both successful and
                # permanently errored. `_classify_error` returns "permanent"
                # for any None error — including a HEALTHY crawl that simply
                # has no error string — which produced the traced
                # `[TOOL_DISPATCH] tool=crawler_query success=True
                # error_type=permanent` line on a run that retrieved zero
                # usable content. A success carries no permanent error.
                if success and dr.error_type == "permanent":
                    dr.error_type = None

                # Remember permanently-failed calls so an identical retry is
                # rejected as a loop instead of re-executed. Recorded only
                # after the REQ-15 AC2 fixup above, so a healthy result that
                # merely lacked an error string is never marked permanent.
                if (
                    not success
                    and dr.error_type == "permanent"
                    and decision.tool
                    and _args_hash
                ):
                    _pf_key = (decision.tool, _args_hash)
                    self._permanent_failed_args[_pf_key] = (
                        self._permanent_failed_args.get(_pf_key, 0) + 1
                    )

                # A successful file change starts a new epoch. Re-stamp THIS
                # call with it, so an identical retry right after it (nothing
                # changed in between) still matches as a repeat / cache hit.
                if success and decision.tool in _FILE_CHANGE_TOOLS:
                    self._change_epoch += 1
                    _new_hash = f"{_raw_hash}@{self._change_epoch}"
                    _prev = self._last_call.get(decision.tool)
                    if _prev and _prev[0] == _args_hash:
                        self._last_call[decision.tool] = (_new_hash, _prev[1], _prev[2])
                    _args_hash = _new_hash
                    if _ik:
                        _ik = _make_idempotency_key(
                            f"{turn_id}@{self._change_epoch}", decision.tool, decision.params
                        )

                # ── Idempotency store (REQ-11) ──────────────────────────
                # Successes only: a hit is replayed as success=True, so a
                # cached failure would report a write that never happened.
                if _ik and success and _is_write_tool(decision.tool):
                    self._idem_cache[_ik] = (result, time.time() + _IDEMPOTENCY_TTL)
                    logger.info(
                        "[TOOL_DISPATCH] idempotency cache STORE key=%s tool=%s ttl=%ds conv=%s",
                        _ik, decision.tool, _IDEMPOTENCY_TTL, conversation_id,
                    )

                # Update _last_call success flag from actual result
                if decision.tool and _args_hash:
                    _prev = self._last_call.get(decision.tool)
                    if _prev and _prev[0] == _args_hash:
                        self._last_call[decision.tool] = (_args_hash, success, _prev[2])

            elif decision.kind == DecisionKind.REASON:
                prompt = reasoning_prompt or decision.rationale or ""
                if not prompt:
                    raise ValueError("REASON dispatch requires a reasoning_prompt or decision.rationale")
                text = self._run_reason_step(prompt)
                dr = DispatchResult(success=True, result=text, duration_ms=0, error_type=None)

            else:
                dr = DispatchResult(success=False, error=f"Unknown decision kind: {decision.kind}",
                                    error_type="permanent")

            dr.duration_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "[TOOL_DISPATCH] kind=%s tool=%s success=%s error_type=%s duration_ms=%d conv=%s",
                decision.kind.value,
                decision.tool or "null",
                dr.success,
                dr.error_type or "none",
                dr.duration_ms,
                conversation_id,
            )
            if not dr.success and dr.error:
                logger.warning(
                    "[TOOL_DISPATCH] failure tool=%s error_type=%s error='%s' duration_ms=%d conv=%s",
                    decision.tool or "null",
                    dr.error_type or "?",
                    dr.error[:200],
                    dr.duration_ms,
                    conversation_id,
                )
            return dr

        except Exception as exc:
            ms = int((time.perf_counter() - start) * 1000)
            # Session-326 (owner: name the killer): a timeout/cancel death
            # carries a blank message (CancelledError str is ''), which is
            # how the 162s D7 stall reported error=''. Fall back to the
            # exception type so the line always names the death.
            _exc_text = (str(exc) or "").strip()[:200] or (
                "%s (no message)" % type(exc).__name__
            )
            logger.error(
                "[TOOL_DISPATCH] kind=%s tool=%s CRASHED error='%s' duration_ms=%d conv=%s",
                decision.kind.value,
                decision.tool or "null",
                _exc_text,
                ms,
                conversation_id,
            )
            _err = _exc_text[:500]
            return DispatchResult(success=False, error=_err, duration_ms=ms,
                                  error_type=_classify_error(_err))

    # ── Internal helpers ──────────────────────────────────────────────────

    def reset_failure_counters(self) -> None:
        """Reset per-tool failure counters and dedup state (REQ-12 AC3).

        Called by the DER loop when a ``_split_step`` Sub-Loop is created,
        so the graft is not penalized as a continuation of the parent step.

        NOTE: this deliberately does NOT clear ``_ruled_out_seed`` (REQ-11
        AC11.2) — the failure veto must outlive the split, exactly as
        ``_permanent_failed_args`` does.
        """
        self._tool_fails.clear()
        self._last_call.clear()
        self._tool_call_nodes.clear()

    # ── REQ-11 AC11.3/AC11.4 (T15) + REQ-17 AC17.1/AC17.2 (T21) ────────────
    # The triage menu. T21 (AC17.1) EXTENDS it with `retry_same`, so the engine
    # can express the retry|graft|escalate distinction the heuristic counters
    # used to own implicitly.
    _RECOVERY_STRATEGIES = (
        "retry_same", "retry_different_tool", "decompose", "escalate",
    )

    # ── Session 365: the CONTINUATION route vocabulary (`depth_route`) ──────
    # The routes `AgentKernel._der_plan_next_step` can take once the Brain says
    # it is done. These are the INCUMBENT's own branch names, DELIBERATELY:
    # oracle.md 14.2 requires the engine and the live path to speak the same
    # vocabulary, or "the comparison never matches and the report shows
    # precision 0 as though it were a measurement".
    #
    # `next_step` was ADDED session 366 (handoff 3.4 / oracle.md 17.3.2). The
    # first cut had only the four `done`-branch routes, and that branch needs the
    # monitor consult to return done=True - which is rare - so the site could not
    # fire often enough to collect one row. The not-done path is a real
    # continuation decision too (the Brain named a next step), so it belongs in
    # the menu. WITH IT, every consult that reaches a branch records exactly one
    # row, and `brain_choice` still varies with state.
    #
    # The richer "how to deepen" sub-routes (deepen_with_tool / reread_evidence
    # / verify_with_evidence / accept_partial) are NOT here yet: the incumbent
    # cannot pick them, so they could never agree with it, and adding them now
    # would deflate precision for no information. They become scoreable only
    # once `deepen` is enforced and the engine's pick actually RUNS.
    _DEPTH_ROUTES = (
        "cover_open_fact", "bonus_ceiling", "deepen", "next_step", "finalize",
    )

    # ── REMOVED (session 366): the LOCAL-workspace web veto ────────────────
    # `_WEB_GATHER_TOOLS`, `_LOCAL_WORKSPACE_MARKERS`, `_is_local_workspace_goal`
    # and `_local_web_veto` were a phrase-list band-aid, now deleted as debt
    # (owner decision 2026-09-29). The arbiter is the Oracle's `web_intent`
    # consumer: `_mem_lookup` only pre-commits `crawler_query` when
    # `_is_web_intent(goal)` is true, and since session 366 that verdict requires
    # `noul.confident(0.8)` - an UNSURE engine falls back to the deterministic
    # trigger list instead of flipping a coin into a crawl. The veto MACHINERY
    # (the memory-hint `veto` set, the menu filter, `_memory_allowed`) STAYS: it
    # is the physics sanction, not the local list.

    def _record_shadow_row(
        self, row: Optional[Dict[str, Any]], session_id: str = "",
    ) -> None:
        """Write a shadow row through the box's single writer.

        One row, one writer (D4): the same bridge method route-only decisions
        already use. Best-effort — a ledger write never breaks a recovery or a
        reply. Shared by the failure-triage row (REQ-17) and the RespondDirect
        tool-choice row (REQ-16 AC16.2).
        """
        if not row:
            return
        recorder = getattr(self._tool_bridge, "record_decision", None)
        if recorder is None:
            return
        try:
            recorder(row, kind="shadow", session_id=session_id)
        except Exception as _e:  # noqa: BLE001 — the row is an observer
            logger.debug("[TOOL_DECISION] triage shadow row write failed: %r", _e)

    def note_failure(self, *, objective: str = "", failed_tool: str = "") -> None:
        """REQ-11 AC11.1/AC11.2 (T14 remainder): seed the graft failure veto.

        ``resolve(failure=...)`` already seeds this, but the DER detects a step
        failure in ``_der_handle_step_failure`` — a path that never calls
        ``resolve()``. This is the seeding-ONLY half: no engine call, no
        decision, no side effect beyond the veto set. Idempotent, never raises.

        KEY CHOICE: the caller must pass the same ``objective`` string the next
        ``resolve()`` will compute. ``resolve()`` derives it as
        ``step["objective_anchor"] or step["objective"] or description``, so the
        kernel passes ``item.objective_anchor`` (the overall task goal, which
        graft children inherit — ``der_loop.py:230``) AND includes it in the
        step dict at the resolve call site. Keying on the per-step description
        would make the veto unreachable for the graft it exists to protect.

        Like ``_permanent_failed_args``, the set is deliberately NOT cleared by
        ``reset_failure_counters``: a veto a split erases is exactly how
        recovery re-picks the tool that just failed.
        """
        try:
            _tool = str(failed_tool or "").strip()
            _key = str(objective or "")
            if _tool and _key:
                self._ruled_out_seed.setdefault(_key, set()).add(_tool)
        except Exception as _e:  # noqa: BLE001 — a veto seed never raises
            logger.debug("[TOOL_DECISION] note_failure failed: %r", _e)

    def recovery_strategy(
        self,
        *,
        failed_tool: str = "",
        error_snippet: str = "",
        objective: str = "",
        threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Triage a graft failure BEFORE the Brain is asked to plan recovery.

        Returns ``{"strategy", "confidence", "delegate"}``. ``delegate=True``
        means "this gate declined — run the Brain planning path"; the Brain is
        consulted ONLY on DELEGATE or below threshold (AC11.3).

        AC11.4 is decided DETERMINISTICALLY, ahead of the model: when the same
        tool has failed twice consecutively for one objective, the strategy is
        ``escalate`` — a third identical attempt is never grafted, and no model
        call is spent to see a repeat. Never raises.

        REQ-17 AC17.1/AC17.2 (T21): the menu now offers ``retry_same`` and a
        shadow row is recorded on every MODEL-CONSULTED triage — the engine's
        verdict PAIRED with the counters' decision (``counter_choice``). The
        engine only records: the counters keep deciding, so a confident
        ``retry_same`` is never returned (AC17.2). The deterministic
        double-failure escalate stays model-free per AC11.4, so it records no
        row rather than a fabricated one.
        """
        _key = objective or ""
        try:
            recent = self._recovery_failures.setdefault(_key, [])
            if failed_tool:
                recent.append(failed_tool)
                if len(recent) >= 2 and recent[-1] == recent[-2]:
                    logger.info(
                        "[TOOL_DECISION] recovery: %s failed twice consecutively "
                        "for one objective -> escalate", failed_tool,
                    )
                    self._recovery_strategy = "escalate"
                    # AC11.4 forbids a model call here, so there is no engine
                    # verdict to pair — the counters decided (AC17.2).
                    self.last_triage_shadow = None
                    return {"strategy": "escalate", "confidence": 1.0,
                            "delegate": False}
        except Exception:  # noqa: BLE001 — triage must never raise
            pass

        _thr = self._decision_threshold if threshold is None else float(threshold)
        eng = self._engine()
        _row: Optional[Dict[str, Any]] = None
        if eng is not None:
            try:
                frame = {
                    "goal": objective or f"recover from {failed_tool or 'a failure'}",
                    # AC11.2: the failed tool is ruled out of the triage too.
                    "ruled_out": [failed_tool] if failed_tool else [],
                    "error_snippet": (error_snippet or "")[:200],
                }
                # Criteria registration (2026-09-27). Without it the engine
                # REFUSES to score this consumer - measured live:
                #   decision_backend_onnx: no criteria for consumer=
                #   recovery_strategy - refusing to score (legacy path)
                # A refusal returns no Noul, so no row is written and the
                # consumer can never reach the Wave 7 bar however often the
                # triage runs. Registered on first use, mirroring the reviewer.
                try:
                    from backend.agent.decision_backend_onnx import (
                        ConsumerSpec,
                        get_consumer_spec,
                        register_consumer_spec,
                    )

                    if get_consumer_spec("recovery_strategy") is None:
                        register_consumer_spec(ConsumerSpec(
                            consumer_id="recovery_strategy",
                            task_name="recovery_strategy",
                            instruction=(
                                "A tool step failed. What should happen next: "
                                "retry the same tool, try a different one, or "
                                "escalate to a new plan?"
                            ),
                            labels=tuple(
                                list(self._RECOVERY_STRATEGIES)
                                + [self._DE_DELEGATE]
                            ),
                        ))
                except Exception:  # noqa: BLE001 — criteria are best-effort
                    pass
                ds = eng.decide(
                    "recovery_strategy",
                    list(self._RECOVERY_STRATEGIES) + [self._DE_DELEGATE],
                    frame,
                )
                if ds is not None:
                    # The shadow PAIR: what the engine said vs what ran.
                    _row = {
                        "consumer_id": "recovery_strategy",
                        "engine": getattr(eng, "model_id", None) or "decision-engine",
                        "chosen": ds.chosen,
                        "confidence": round(float(ds.confidence), 4),
                        "candidates": [
                            {"name": c.name, "prob": round(c.prob, 4)}
                            for c in (ds.distribution or ())
                        ],
                        "threshold": _thr,
                        "engine_latency_ms": ds.engine_latency_ms,
                        "retry_same_offered": "retry_same" in self._RECOVERY_STRATEGIES,
                        "failed_tool": failed_tool or None,
                        "shadow": True,
                    }
                # AC17.2: `retry_same` is SHADOW-ONLY. A confident retry_same
                # is recorded and then discarded — the counters own the
                # retry-vs-graft call, so the engine can never route a repeat
                # that the counters would have escalated.
                if (ds is not None and ds.chosen != self._DE_DELEGATE
                        and ds.chosen != "retry_same"
                        and ds.confidence >= _thr):
                    self._recovery_strategy = ds.chosen
                    if _row is not None:
                        # The engine and the counters agree on the outcome.
                        _row["counter_choice"] = ds.chosen
                        # The parity reference under the name the ledger passes
                        # through and the report reads (2026-09-27). The Brain's
                        # ACTUAL decision here is the counters' one, so that is
                        # what the engine's pick must be judged against.
                        _row["brain_choice"] = ds.chosen
                        self.last_triage_shadow = _row
                        self._record_shadow_row(_row)
                    return {"strategy": ds.chosen,
                            "confidence": round(ds.confidence, 4),
                            "delegate": False}
            except Exception as _e:  # noqa: BLE001 — degrade to Brain
                logger.warning(
                    "[TOOL_DECISION] recovery_strategy gate failed (%r) — "
                    "delegating to Brain", _e,
                )

        self._recovery_strategy = ""
        if _row is not None:
            # AC17.2: the counters' decision stands (delegate = the Brain
            # plans), whatever the engine picked.
            _row["counter_choice"] = "delegate"
            # ...and the same fact as the parity reference (2026-09-27).
            _row["brain_choice"] = "delegate"
            self.last_triage_shadow = _row
            self._record_shadow_row(_row)
        return {"strategy": "delegate", "confidence": 0.0, "delegate": True}

    def depth_route(
        self,
        *,
        incumbent_route: str,
        coverage: float = 0.0,
        open_facts: Optional[list] = None,
        criteria: str = "",
        grade: str = "",
        depth_met: Optional[bool] = None,
        pushes_used: int = 0,
        session_id: str = "",
        threshold: Optional[float] = None,
        async_: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """SHADOW: which continuation should the loop take now that the Brain
        says it is done? Records the row and returns it; the caller's behaviour
        is UNCHANGED (the incumbent's route stands).

        WHY THIS SITE, AND WHY THIS IS THE ANSWER (session 365). The depth push
        on its own is NOT a decision point — it is one of four returns inside
        the continuation decision, and scoring the push alone would have given a
        CONSTANT reference (oracle.md 14.1's "manufacture agreement" trap: the
        precision would measure nothing). The continuation decision genuinely
        chooses among four named routes, so `brain_choice` varies with state and
        the parity is meaningful.

        THE REFERENCE IS A NAME, COMPARED AS A NAME. `brain_choice` is the route
        the live path ACTUALLY took, and it speaks the same vocabulary as the
        menu — no translation, which is the safest case 14.2 describes. Both
        keys (`brain_choice`, `chosen`) are on `tool_bridge._DECISION_META_KEYS`,
        or the ledger would drop the reference in transit.

        WHAT IT CANNOT MEASURE YET, stated plainly: this is parity with a
        state-determined policy, not an outcome measurement. In shadow the
        engine's pick does not RUN, so the event's outcome describes the
        incumbent's route, not the engine's. Outcome labelling only becomes
        possible after a flip — which is why shadow-first parity is the correct
        first step rather than a compromise.

        Never raises: a shadow consumer must never block a reply.

        ``async_=True`` (the kernel's mode): the score and its row run on
        lane("oracle_shadow") and this returns None at once - 69 inline scores,
        33 s per coding eval run, sat on the continuation path (2026-10-01).
        """
        if async_:
            try:
                from backend.utils.durability_queue import lane

                _kw = dict(
                    incumbent_route=incumbent_route, coverage=coverage,
                    open_facts=list(open_facts or []), criteria=criteria,
                    grade=grade, depth_met=depth_met, pushes_used=pushes_used,
                    session_id=session_id, threshold=threshold,
                )
                if not lane("oracle_shadow").submit(
                        "depth_route", lambda: self.depth_route(**_kw)):
                    logger.warning("[TOOL_DECISION] depth_route row dropped (lane full)")
            except Exception as _e:  # noqa: BLE001 — an observer never blocks
                logger.warning("[TOOL_DECISION] depth_route submit failed: %r", _e)
            return None
        _thr = self._decision_threshold if threshold is None else float(threshold)
        eng = self._engine()
        if eng is None:
            return None
        try:
            # Criteria registration, mirroring recovery_strategy: without it the
            # engine REFUSES to score the consumer, so no Noul is returned, no
            # row is written, and the consumer can never reach the bar however
            # often the continuation decision runs.
            try:
                from backend.agent.decision_backend_onnx import (
                    ConsumerSpec,
                    get_consumer_spec,
                    register_consumer_spec,
                )

                if get_consumer_spec("depth_route") is None:
                    register_consumer_spec(ConsumerSpec(
                        consumer_id="depth_route",
                        task_name="depth_route",
                        instruction=(
                            "The loop is deciding how to continue. What should "
                            "it do next: cover a required fact that is still "
                            "open, run the bounded bonus pass over the ceiling "
                            "facts, push for more depth because the work is only "
                            "superficially complete, pursue the next step the "
                            "Brain named, or finalize and answer?"
                        ),
                        labels=tuple(
                            list(self._DEPTH_ROUTES) + [self._DE_DELEGATE]
                        ),
                    ))
            except Exception:  # noqa: BLE001 — criteria are best-effort
                pass
            frame = {
                "goal": (criteria or "")[:200],
                "coverage": round(float(coverage or 0.0), 3),
                "open_facts": [str(_f) for _f in (open_facts or [])][:5],
                "grade": grade or "",
                "depth_met": depth_met,
                "pushes_used": int(pushes_used or 0),
                "incumbent_route": incumbent_route,
            }
            ds = eng.decide(
                "depth_route",
                list(self._DEPTH_ROUTES) + [self._DE_DELEGATE],
                frame,
            )
            if ds is None:
                return None
            row = {
                "consumer_id": "depth_route",
                "engine": getattr(eng, "model_id", None) or "decision-engine",
                "chosen": ds.chosen,
                "confidence": round(float(ds.confidence), 4),
                "candidates": [
                    {"name": c.name, "prob": round(c.prob, 4)}
                    for c in (ds.distribution or ())
                ],
                "threshold": _thr,
                "engine_latency_ms": ds.engine_latency_ms,
                # The live path's route, kept as its own field so a report can
                # see BOTH the reference and what the incumbent did even if the
                # two ever diverge in naming.
                "incumbent_route": incumbent_route,
                # oracle.md 14.2: the parity reference, under the key the ledger
                # passes through and the report reads.
                "brain_choice": incumbent_route,
                # v2 (2026-10-01): the Oracle job input now renders coverage,
                # open facts, depth_met and grade - before, only `goal` was read.
                "criteria_version": "depth_route/v2",
                "shadow": True,
            }
            self._record_shadow_row(row, session_id=session_id)
            return row
        except Exception as _e:  # noqa: BLE001 — an observer never blocks
            logger.warning("[TOOL_DECISION] depth_route gate failed: %r", _e)
            return None

    def record_tool_call(
        self,
        step_id: str,
        tool: Optional[str],
        args_hash: str,
        result_summary: str,
        error_type: Optional[str],
        source: str,
        split_depth: int = 0,
        parent_step_id: Optional[str] = None,
    ) -> None:
        """Record a single tool call for the ToolCallTree (REQ-13)."""
        self._tool_call_nodes.append(ToolCallNode(
            step_id=step_id,
            tool=tool,
            args_hash=args_hash,
            result_summary=result_summary[:200],
            error_type=error_type,
            source=source,
            split_depth=split_depth,
            parent_step_id=parent_step_id,
        ))

    def get_tool_call_tree(self, conversation_id: str = "") -> ToolCallTree:
        """Return the accumulated ToolCallTree and reset."""
        tree = ToolCallTree(
            conversation_id=conversation_id,
            nodes=list(self._tool_call_nodes),
        )
        self._tool_call_nodes.clear()
        return tree

    def _validate_as_tool(
        self,
        tool_name: str,
        params: dict,
        source: str,
        conversation_id: str,
        start: float,
        log_extra: dict,
        goal: str = "",
    ) -> Decision:
        """Validate *tool_name* + *params* via RC1 and return TOOL or FAIL."""
        is_valid, err = self._validate_tool_call(tool_name, params)
        ms = int((time.perf_counter() - start) * 1000)
        if is_valid:
            logger.info(
                "[TOOL_DECISION] kind=TOOL source=%s tool=%s "
                "resolve_ms=%d conv=%s",
                source, tool_name, ms, conversation_id,
            )
            _d = Decision(
                kind=DecisionKind.TOOL, tool=tool_name, params=params,
                source=source,
            )
            # Brain<->Tool handshake. Only engages when the two roles are on
            # DIFFERENT models and the proposed call is missing required
            # arguments — i.e. the smaller execution model knew WHICH tool but
            # not WHAT to pass it. Same model on both roles returns untouched.
            return self._complete_params_via_brain(_d, goal)
        logger.warning(
            "[TOOL_DECISION_FAIL] kind=FAIL source=%s tool=%s "
            "error='RC1: %s' resolve_ms=%d conv=%s",
            source, tool_name, err, ms, conversation_id,
        )
        return Decision(
            kind=DecisionKind.FAIL, source=source,
            error=f"RC1 validation failed for '{tool_name}': {err}",
        )

    def _apply_pre_filter(
        self,
        all_tools: list[dict],
        memory_hint: Optional[dict],
        goal: str,
    ) -> list[dict]:
        """Narrow candidate tools via memory hint (REQ-4 AC6).

        Keeps the memory-suggested tool (if any) plus generic utility tools
        so the model still has a choice.  Returns the full list unchanged
        when there is no memory hint.

        pin_517dfcbda150: a hint may carry an explicit ``veto`` list — tools
        the memory layer forbids this step (e.g. crawler_query when the
        physics sanction says the agent is converged / budget-exhausted /
        provider-loaded). Vetoed tools are REMOVED from the candidate set so
        the LLM cannot pick them; a vetoed-only candidate set collapses to
        the generic utilities, and an empty result falls back to the full
        list only if even the utilities are absent.
        """
        if not memory_hint:
            return all_tools  # no pre-filter
        vetoed = memory_hint.get("veto") or []
        if vetoed:
            generic = {"speak", "tts", "ask_user", "respond"}
            keep = [t for t in all_tools if t.get("name", "") not in vetoed]
            if keep:
                return keep
            gen_only = [t for t in all_tools if t.get("name", "") in generic]
            return gen_only if gen_only else all_tools
        suggested = memory_hint.get("tool")
        if not suggested:
            return all_tools
        # Session-332 (live T3): a memory *suggestion* is a RANKING BIAS, not a
        # whitelist. This branch used to return ONLY {suggested} ∪ generic, which
        # deleted every other real tool from the candidate set. Measured: a goal
        # "create t3_redrive.txt" with memory hint {tool: list_directory} left
        # candidates = [list_directory, speak, ask_user] — write_file was gone,
        # so the LLM could not select it no matter how clearly the goal asked to
        # write. The docstring already promised "so the model still has a
        # choice"; the code did not deliver it. Keep the full set and float the
        # suggested tool to the front (plus generics) so memory still biases the
        # model without amputating its options. The `veto` branch above is a
        # genuine hard constraint and remains exclusive — only *suggestions*
        # are demoted to a hint.
        generic = {"speak", "tts", "ask_user", "respond"}
        preferred, rest = [], []
        for t in all_tools:
            name = t.get("name", "")
            if name == suggested or name in generic:
                preferred.append(t)
            else:
                rest.append(t)
        return preferred + rest if preferred else all_tools


    def _run_reason_step(self, prompt: str, role: str = "REASONING") -> str:
        """Direct reasoning: used when the model decided no tool is needed."""
        if self._infer is None:
            raise RuntimeError(
                "ToolDecisionBox cannot dispatch REASON: no infer_fn was injected"
            )
        return self._infer(prompt, role=role)

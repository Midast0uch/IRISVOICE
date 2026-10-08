"""
ToolResultEnvelope — write-time wrapper for every DER tool result.
File: IRISVOICE/backend/agent/tool_envelope.py

Source: specs/tool-result-envelope/ (REQ-1, REQ-3, REQ-5, REQ-8, REQ-9, REQ-11;
KD-3, KD-7, KD-8, KD-9, KD-11, KD-14, KD-15)

THE DEAL (design.md Context): every tool result arrives in the loop already
shaped — bounded digest, durable raw pointer, and decision-useful wrapper
labels IN WORDS. The Director reasons over sentences ("repeat of Step 1 —
read it instead of re-fetching"), never over vector norms. Raw payloads never
re-enter the context window; consumers resolve `raw_ref` on demand.

REPORTER-ONLY CONTRACT (KD-10 / session-316 lock): the envelope NEVER mints
hashes, NEVER walks the graph, NEVER scores recall. It stamps joinable
identity (doc_id + card_id + step_id + session/turn + verbatim coords) so
wormhole/aperture land later with zero rework. No fingerprint, no vectors, no
encodes (KD-7) — the wrapper is derived from already-recorded signals only,
deterministic, zero LLM calls, zero I/O (AC3.5).
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.agent.tool_errors import (
    classify_exception_from_message,
    resolve_label,
)

# ── Vocabulary (enums as plain strings — words, not physics) ────────────────

STATUS_VALUES = ("success", "error", "partial", "timeout")
MATCH_VALUES = ("matched", "mismatched", "unclear")
NOVELTY_VALUES = ("new", "empty")  # plus "repeat_of_<step_id>"
SUGGESTION_VALUES = ("proceed", "retry_same", "try_different", "stop")
STUCK_SHAPES = (
    "none", "circling", "dry_well", "wrong_package", "flat_tire", "idling",
)
CRITICALITY_VALUES = ("load-bearing", "supporting", "cosmetic")
CRITICALITY_SOURCES = ("declared", "confirmed")

SUMMARY_MAX_CHARS = 300
SUMMARY_MAX_LINES = 2

# Tool-family → expectation bar (KD-9: one bar cannot judge a crawl and a
# file read). Families: gather (asked-terms + sources), read (ref resolved),
# synthesis (covers prior summaries, no raw dump), action (side effect
# confirmed), direct (tool-less reasoning step).
_GATHER_TOOLS = frozenset({
    "web_search", "crawler_query", "search_discovery", "websearch",
    "get_rendered_documents", "fetch_url", "crawl",
    # ── KD-9 gap closed (2026-10-08) ────────────────────────────────────────
    # The open-url and browser tools GO AND RETRIEVE from outside the project,
    # so their expectation IS `gather`. Leaving them as `direct` was not
    # cosmetic: agent_kernel.py:6991 gates the VLM recovery path on
    # `tool_family(...) == "gather"`, so a browser_open / open_url step that
    # came back with NOTHING was never offered recovery - the one case that
    # needs it most. `browser_act` is deliberately NOT here; see _ACTION_TOOLS.
    "open_url", "browser_open", "browser_observe", "browser_explore",
})
_SYNTHESIS_TOOLS = frozenset({"synthesis", "respond", "compose"})
_ACTION_TOOLS = frozenset({
    "write_file", "edit_file", "delete_file", "run_command", "create_file",
    "move_file", "speak",
    # KD-9 gap closed (2026-10-08): browser_act CHANGES the page (click / type)
    # rather than retrieving from it, so its expectation is `action`, not
    # `direct`. It stays out of `gather` so it never inherits gather's recovery
    # semantics, which are about a fetch that returned nothing.
    "browser_act",
})
_READ_TOOLS = frozenset({
    "read_file", "get_document", "read_document", "get_rendered_document",
})

_STOPWORDS = frozenset(
    "a an the and or of for to in on with by from as at is are was were be "
    "been this that these those it its their there here what which how why "
    "any all each into about over under after before between during support "
    "supports does do did covering cover compare compares using use".split()
)

_SOURCE_MARKER_RE = re.compile(r"---\s*Source:", re.IGNORECASE)
_SOURCE_URL_RE = re.compile(r"---\s*Source:\s*(https?://[^\s]+)", re.IGNORECASE)


def normalize_url(u: str) -> str:
    """Canonical address key for turn-memory repeat detection (AC10.2).

    Same page with a trailing slash, a fragment, or host-case drift is the
    same address. Normalizes: strip whitespace, lowercase scheme+host, drop
    fragment, strip one trailing slash (root '/' kept). Pure, stdlib-only,
    never raises — unparseable input returns stripped input.
    """
    try:
        from urllib.parse import urlsplit, urlunsplit
        _s = (u or "").strip()
        if not _s:
            return ""
        _p = urlsplit(_s)
        _scheme = (_p.scheme or "").lower()
        _host = (_p.netloc or "").lower()
        _path = _p.path or ""
        if len(_path) > 1 and _path.endswith("/"):
            _path = _path[:-1]
        return urlunsplit((_scheme, _host, _path, _p.query, ""))
    except Exception:
        try:
            return (u or "").strip()
        except Exception:
            return ""
# Hard bound on the marker scan: totals are exact below it (absurd inputs
# still terminate). The returned slice honors `limit` (default mirrors
# der_constants.SOURCES_MAX — kept literal here so this module stays
# stdlib-only with zero config reads).
_SOURCES_SCAN_MAX = 256


def extract_sources(result_text: str, limit: int = 8) -> Tuple[List[str], int]:
    """REQ-8 AC8.1: URLs actually fetched for the step, derived at wrap
    time from in-scope result text. Returns (sources, total): order-
    preserving, de-duplicated slice plus the FULL pre-cap distinct count —
    total > len(sources) IS the truncation mark. Same marker shape the
    kernel's `_der_crawled_urls` update regexes, factored here so wrap-time
    and ledger agree. Pure, zero I/O."""
    _all: List[str] = []
    try:
        for _m in _SOURCE_URL_RE.finditer(str(result_text or "")):
            if len(_all) >= _SOURCES_SCAN_MAX:
                break
            _u = _m.group(1).strip().rstrip(".,;)]")
            if _u and _u not in _all:
                _all.append(_u)
    except Exception:
        pass
    return _all[:limit], len(_all)
_SUCCESS_MARKER_RE = re.compile(
    r"\b(success|succeeded|created|deleted|saved|written|confirmed|completed|"
    r"done|applied)\b",
    re.IGNORECASE,
)


def tool_family(tool: Optional[str]) -> str:
    """Classify a tool name into its expectation family (KD-9)."""
    t = (tool or "").lower()
    if t in _GATHER_TOOLS or "crawl" in t or "search" in t:
        return "gather"
    if t in _READ_TOOLS or t.startswith("read") or t.startswith("get_doc"):
        return "read"
    if t in _SYNTHESIS_TOOLS or "synth" in t:
        return "synthesis"
    if t in _ACTION_TOOLS or t.startswith("write") or t.startswith("edit"):
        return "action"
    return "direct"


def _extract_terms(text: str, limit: int = 6) -> List[str]:
    """Distinctive terms from an expectation/goal string, minus stopwords."""
    terms: List[str] = []
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", text or ""):
        w = raw.strip(".-").lower()
        if len(w) < 3 or w in _STOPWORDS:
            continue
        if w not in terms:
            terms.append(w)
        if len(terms) >= limit:
            break
    return terms


def _one_line(text: str) -> str:
    """Collapse whitespace/newlines — a summary is ≤2 lines by construction."""
    return re.sub(r"\s+", " ", (text or "")).strip()


def _bound_summary(text: str) -> str:
    """AC1.1: summary ≤300 chars, ≤2 lines. Head+TAIL excerpt with an
    explicit truncation marker (page chrome lives at heads — a tail slice
    keeps the digest honest about what got cut, never a silent amputation)."""
    s = _one_line(text)
    if len(s) <= SUMMARY_MAX_CHARS:
        return s
    _head = s[: int(SUMMARY_MAX_CHARS * 0.7)].rstrip()
    _tail = s[-60:].lstrip()
    return f"{_head} […] {_tail}"[:SUMMARY_MAX_CHARS + 5]


# ── The envelope ─────────────────────────────────────────────────────────────


@dataclass
class ToolResultEnvelope:
    """Write-time wrapper around one executed tool result (AC1.1).

    Words, not numbers: the Director reads status/match/novelty/suggestion.
    Coords pass through VERBATIM for future wormhole hashing and are never
    arithmetized here (AC1.5 / KD-3). raw_ref is doc-store ONLY — Pacman
    filing is async, chunk ids are never available at wrap time and never
    waited on (AC1.3 / KD-7).
    """

    status: str                  # success | error | partial
    summary: str                 # ≤300 chars, ≤2 lines
    raw_ref: Dict[str, Any] = field(default_factory=dict)   # {"doc_id": str}
    match: str = "unclear"       # matched | mismatched | unclear
    novelty: str = "new"         # new | empty | repeat_of_<step_id>
    suggestion: str = "proceed"  # proceed | retry_same | try_different | stop
    stuck_shape: str = "none"    # none | circling | dry_well | wrong_package | flat_tire | idling
    coords_from: str = ""        # VERBATIM passthrough — never subtracted here
    coords_to: str = ""          # VERBATIM passthrough
    coords_basis: str = "none"   # "format_coords" when real signal, "none" when absent (AC1.5)
    criticality: str = "supporting"     # load-bearing | supporting | cosmetic
    criticality_source: str = "declared"  # declared | confirmed (AC1.6)
    card_id: str = ""            # join keys for aperture/chains later (KD-10)
    step_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    error_type: str = ""         # populated when status != success (tool_errors.py shape)
    recovery_hint: str = ""
    sources: List[str] = field(default_factory=list)  # URLs actually fetched (REQ-8,
                                # AC8.1: capped, truncation marked via sources_total)
    sources_total: int = 0        # pre-cap distinct count; total > len(sources) ⇒ truncated
    recovery_of: str = ""        # parent step_id when this is a VLM recovery envelope (REQ-9)
    elapsed_s: float = 0.0        # wall time vs the step deadline (REQ-11/REQ-12)
    created_at: float = field(default_factory=time.time)

    def line(self) -> str:
        """The single bounded sentence that may enter working memory /
        prompts / fallback cards (AC2.1). Words, not numbers. e.g.
        'success, mismatched, repeat of step_1 — try_different, doc ab12ef34'.
        Failures render too — a slip-through repeat must be undeniable."""
        parts: List[str] = [self.status]
        if self.match and self.match != "matched":
            parts.append(self.match)
        if self.novelty and self.novelty != "new":
            parts.append(self.novelty)
        if self.stuck_shape and self.stuck_shape != "none":
            parts.append(f"[{self.stuck_shape}]")
        head = ", ".join(parts)
        tail = f" — {self.suggestion}"
        doc_id = str(self.raw_ref.get("doc_id") or "")
        if doc_id:
            tail += f", doc {doc_id[:12]}"
        if self.error_type:
            tail += f" (error: {self.error_type}; {self.recovery_hint})" if self.recovery_hint else f" (error: {self.error_type})"
        out = f"{head}{tail} | {self.summary}"
        return out[:SUMMARY_MAX_CHARS + 200]

    def wrapper_dict(self) -> Dict[str, Any]:
        """The dict shape consumed by evaluate_streak / counters (REQ-7)."""
        return {
            "step_id": self.step_id,
            "status": self.status,
            "match": self.match,
            "novelty": self.novelty,
            "suggestion": self.suggestion,
            "stuck_shape": self.stuck_shape,
            "criticality": self.criticality,
            "criticality_source": self.criticality_source,
        }


# ── Wrapper derivation (AC3.1/AC3.2 — pure, deterministic, O(1) scope) ──────


# ── Expectation registry (session-319) ───────────────────────────────────────
#
# FAULTLINE's three-layer shape (docs/architecture/FAULTLINE.md) applied to
# EXPECTATION instead of failure. The problem it solves: the per-family bars
# below used to be `if family == ...` branches, so every new tool meant editing
# this file — and a tool nobody had classified fell through to a default that
# silently judged it.
#
#   LAYER 1 — DIMENSIONS: the closed, invariant questions every judgement
#             answers. Hardcoded and CLOSED for the same reason FAULTLINE's
#             triple is: specs/wormhole-aperture requires the dimension set to
#             be a closed categorical address that it may HASH but never
#             re-derive or re-model (aperture REQ-32 AC2, which already keys
#             retrieval on FAULTLINE's `(retryable × blame × info_state)`).
#             So this triple is deliberately small, closed and hashable.
#   LAYER 2 — REGISTRY: which bar a tool is judged by, as DATA. Mapping a new
#             tool onto an existing bar is a register_expectation_label(...)
#             call, never an edit to derive_match.
#   LAYER 3 — UNCLASSIFIED: a tool with no registered bar is COUNTED, not
#             silently judged. The vocabulary grows from evidence, mirroring
#             tool_errors.unknown_label_counts() / promote_unknown().
#
# The envelope stays REPORTER-ONLY (locked decision): this registry changes how
# `alignment` is COMPUTED, never what is STAMPED. The stamp shape is unchanged,
# so the aperture's zero-rework contract holds.

# Layer 1 — closed value sets. Adding a member here is a DELIBERATE act, exactly
# as adding a `Reason` is in FAULTLINE: consumers understand values through the
# axis they sit on, so the sets must stay small and closed.
ALIGNMENT_VALUES = frozenset({"matched", "mismatched", "unclear"})
IDENTITY_VALUES = frozenset({"new", "repeat", "unknown"})
YIELD_VALUES = frozenset({"full", "partial", "empty"})


@dataclass(frozen=True)
class ExpectationDimensions:
    """Layer 1 — the closed, invariant outcome triple (3×3×3 = 27 addresses).

    Mirrors tool_errors.FailureDimensions deliberately: the aperture indexes
    failures by cause and findings by outcome the same way, so both lattices
    must have the same shape (small, closed, hashable).
    """

    alignment: str = "unclear"   # matched | mismatched | unclear
    identity: str = "unknown"    # new | repeat | unknown
    yield_state: str = "empty"   # full | partial | empty

    def as_dict(self) -> Dict[str, str]:
        return {
            "alignment": self.alignment,
            "identity": self.identity,
            "yield_state": self.yield_state,
        }

    def as_key(self) -> str:
        """The closed categorical ADDRESS the aperture may hash (REQ-32 AC2).

        Stable, ordered, and cheap — a primary-key-shaped string, never a
        vector. The aperture must never need to re-derive this.
        """
        return f"{self.alignment}|{self.identity}|{self.yield_state}"


UNKNOWN_DIMENSIONS = ExpectationDimensions()


# Layer 2 — the closed set of BARS (pure evaluators).
#
# Closed on purpose: a bar is the unit of judgement, and the aperture needs the
# judgement space to be enumerable. Mapping a new tool onto an existing bar is a
# data edit; adding a genuinely new KIND of work adds one bar here, which is a
# deliberate act like adding a Reason to FAULTLINE's Layer 1.
#
# Each bar has the same signature so the registry can dispatch on data alone:
#   (result_text, expected_output, raw_doc_id, prior_summaries) -> alignment


def _bar_gather(result_text, expected_output, raw_doc_id, prior_summaries) -> str:
    """gather: asked-terms present + sources cited."""
    text = _one_line(result_text)
    terms = _extract_terms(expected_output)
    if not terms:
        return "unclear"
    lower = text.lower()
    hits = sum(1 for t in terms if t in lower)
    sources_cited = bool(_SOURCE_MARKER_RE.search(result_text or "")) or "sources" in lower
    if hits == 0:
        return "mismatched"
    if hits >= max(1, len(terms) // 2):
        return "matched" if sources_cited or hits == len(terms) else "unclear"
    return "unclear"


def _bar_read(result_text, expected_output, raw_doc_id, prior_summaries) -> str:
    """read: the reference resolved (doc present or substantial text back)."""
    text = _one_line(result_text)
    if raw_doc_id or len(text) > 80:
        return "matched"
    if text:
        return "unclear"
    return "mismatched"


def _bar_synthesis(result_text, expected_output, raw_doc_id, prior_summaries) -> str:
    """synthesis: covers prior envelope summaries, no raw dump."""
    text = _one_line(result_text)
    priors = [p for p in (prior_summaries or []) if p]
    if not priors:
        return "unclear"
    lower = text.lower()
    covered = sum(1 for p in priors if any(
        t in lower for t in _extract_terms(p, limit=4)
    ))
    if covered == 0:
        return "mismatched"
    return "matched" if covered >= max(1, len(priors) // 2) else "unclear"


def _bar_action(result_text, expected_output, raw_doc_id, prior_summaries) -> str:
    """action: side effect confirmed."""
    text = _one_line(result_text)
    if not text:
        return "unclear"
    return "matched" if _SUCCESS_MARKER_RE.search(text) else "unclear"


def _bar_direct(result_text, expected_output, raw_doc_id, prior_summaries) -> str:
    """direct / unclassified: judged against expected_output terms."""
    text = _one_line(result_text)
    terms = _extract_terms(expected_output)
    if not terms:
        return "unclear"
    lower = text.lower()
    hits = sum(1 for t in terms if t in lower)
    if hits == 0:
        return "mismatched" if text else "unclear"
    return "matched" if hits >= max(1, len(terms) // 2) else "unclear"


BARS: Dict[str, Any] = {
    "gather": _bar_gather,
    "read": _bar_read,
    "synthesis": _bar_synthesis,
    "action": _bar_action,
    "direct": _bar_direct,
}


@dataclass(frozen=True)
class ExpectationSpec:
    """One registered expectation label = the bar a tool is judged by + meaning."""

    label: str
    bar: str
    description: str = ""


EXPECTATION_LABELS: Dict[str, ExpectationSpec] = {}
_EXPECTATION_LOCK = threading.Lock()


def register_expectation_label(label: str, bar: str, description: str = "") -> bool:
    """Layer 2 growth API. Map a tool/label onto an existing bar.

    Returns True when registered, False when the spec is invalid (unknown bar)
    or the label already exists. Invalid registrations are REFUSED, not coerced
    — mirroring tool_errors.register_error_label — so the registry only ever
    contains well-formed entries and a typo cannot silently create a new
    judgement.
    """
    if bar not in BARS:
        return False
    with _EXPECTATION_LOCK:
        if label in EXPECTATION_LABELS:
            # Same rule as FAULTLINE: the first spec to name a label owns it.
            return False
        EXPECTATION_LABELS[label] = ExpectationSpec(
            label=label, bar=bar, description=description
        )
    return True


# Layer 3 — unclassified bucket (how the vocabulary evolves).
_UNKNOWN_EXPECTATIONS: Dict[str, int] = {}
_UNKNOWN_LOCK = threading.Lock()


def _count_unknown(label: str) -> None:
    with _UNKNOWN_LOCK:
        _UNKNOWN_EXPECTATIONS[label] = _UNKNOWN_EXPECTATIONS.get(label, 0) + 1


def unknown_expectation_counts() -> Dict[str, int]:
    """Layer 3 read API: which labels are being judged without a registered bar.

    Repeated unknowns are promotion candidates — the same evidence-driven growth
    path as FAULTLINE's promote_unknown().
    """
    with _UNKNOWN_LOCK:
        return dict(_UNKNOWN_EXPECTATIONS)


def promote_unknown_expectation(label: str, bar: str, description: str = "") -> bool:
    """Layer 3 -> Layer 2 promotion, from measured need rather than a guess."""
    with _UNKNOWN_LOCK:
        _UNKNOWN_EXPECTATIONS.pop(label, None)
    return register_expectation_label(label, bar, description)


def reset_expectation_registry_for_testing() -> None:
    """Test hook: drop non-seeded labels + unknown counts (mirrors
    tool_errors.reset_wall_ledger_for_testing)."""
    with _EXPECTATION_LOCK:
        for _k in list(EXPECTATION_LABELS):
            if _k not in ("gather", "read", "synthesis", "action", "direct"):
                del EXPECTATION_LABELS[_k]
    with _UNKNOWN_LOCK:
        _UNKNOWN_EXPECTATIONS.clear()


# Seed vocabulary — the four families the system already judges, plus the
# unclassified fallback. Each maps to the bar that reproduces today's exact
# behaviour, so this refactor is behaviour-preserving by construction.
register_expectation_label(
    "gather", "gather", "Gather/crawl/search: asked-terms present + sources cited."
)
register_expectation_label(
    "read", "read", "Read/fetch: the reference resolved (doc id or substantial text)."
)
register_expectation_label(
    "synthesis", "synthesis", "Synthesis: covers prior envelope summaries, no raw dump."
)
register_expectation_label(
    "action", "action", "Action: side effect confirmed."
)
register_expectation_label(
    "direct", "direct", "Unclassified/tool-less: judged against expected_output terms."
)


def judge_alignment(
    label: str,
    result_text: str,
    expected_output: str,
    raw_doc_id: str,
    prior_summaries: Optional[List[str]] = None,
) -> str:
    """Resolve *label* to a bar and judge the result. Zero LLM, pure, O(1).

    A label with no registered bar is COUNTED (Layer 3) and judged `unclear` —
    never silently defaulted to matched/mismatched. That is what makes an
    unclassified tool visible instead of invisible.
    """
    spec = EXPECTATION_LABELS.get(label)
    if spec is None:
        _count_unknown(label)
        return "unclear"
    bar = BARS.get(spec.bar)
    if bar is None:
        _count_unknown(label)
        return "unclear"
    try:
        return bar(result_text, expected_output, raw_doc_id, prior_summaries)
    except Exception:
        return "unclear"


def derive_match(
    family: str,
    result_text: str,
    expected_output: str,
    raw_doc_id: str,
    prior_summaries: Optional[List[str]] = None,
) -> str:
    """Judge the result against the tool's registered bar (AC3.1 / KD-9).

    Registry-driven (session-319): the caller's `family` is a LABEL, and the bar
    is looked up as data. `tool_family()` remains the heuristic that PRODUCES
    that label when a tool has no explicit registration — so a brand-new tool is
    still judged sensibly on day one, and its label is visible in
    `unknown_expectation_counts()` as a promotion candidate.

    Zero LLM: term presence + structural markers only.
    """
    return judge_alignment(
        family, result_text, expected_output, raw_doc_id, prior_summaries
    )


def body_hashes_of(result_text: str) -> List[str]:
    """Session-318 T17 (REQ-10 AC10.1): exact identity of extracted bodies.
    Splits result text on `--- Source:` markers (chunk[0] preamble skipped),
    hashes each EXTRACTED BODY only — machine lines the pipeline appends
    (`--- Attempted:`, `--- Outlinks`, `--- Dead:`) are cut before hashing,
    otherwise two identical fetches with different attempt histories would
    hash differently and identity would be unobservable (caught by BT-4).
    Normalizes (whitespace-collapsed, lowercased); skips trivial bodies
    (>=200 chars — chrome-only stubs never match). stdlib only;
    exact-match, never similarity (KD-13). Pure."""
    import hashlib as _hl
    _out: List[str] = []
    try:
        _chunks = re.split(
            r"---\s*Source:[^\n]*\n", str(result_text or "")
        )
        for _ch in _chunks[1:]:
            _body = re.split(
                r"\n---\s*(?:Attempted|Outlinks|Dead)\b", _ch, maxsplit=1
            )[0]
            _norm = re.sub(r"\s+", " ", _body).strip().lower()
            if len(_norm) < 200:
                continue
            _h = _hl.sha256(_norm.encode("utf-8", "replace")).hexdigest()
            if _h not in _out:
                _out.append(_h)
    except Exception:
        pass
    return _out


def derive_novelty(
    result_text: str,
    tool: Optional[str],
    params_digest: str,
    turn_memory: Dict[str, Any],
) -> str:
    """Novelty vs turn memory (AC3.1): new | empty | repeat_of_<step_id>.
    turn_memory carries: crawled_urls (this turn), tool_params ({digest:
    step_id}), step_outputs ([(step_id, excerpt)]), body_hashes ({sha: step})."""
    if not (result_text or "").strip():
        return "empty"
    seen_params = turn_memory.get("tool_params") or {}
    prior_step_id = seen_params.get(params_digest or "")
    if prior_step_id:
        return f"repeat_of_{prior_step_id}"
    # All fetched URLs already known this turn → the crawl is a repeat.
    # Session-322: compare NORMALIZED addresses — raw text keeps trailing
    # slashes/fragments that turn memory already normalized away.
    crawled = turn_memory.get("crawled_urls") or set()
    result_urls = set(re.findall(r"https?://[^\s\"')\]]+", result_text or ""))
    try:
        _crawled_n = {normalize_url(str(u)) for u in crawled}
        _result_n = {normalize_url(str(u).rstrip(".,;)]")) for u in result_urls}
        _result_n.discard("")
        _crawled_n.discard("")
    except Exception:
        _crawled_n = set(crawled)
        _result_n = set(result_urls)
    if _crawled_n and _result_n and _result_n <= _crawled_n:
        return "repeat_of_" + str(turn_memory.get("last_gather_step_id") or "gather")
    # Session-318 T17 (REQ-10 AC10.1): identical extracted bodies under
    # different URLs are the same groceries — exact hash hit repeats the
    # step that first held the body (fingerprint CUT stands: no vectors).
    _hashes = turn_memory.get("body_hashes") or {}
    if _hashes:
        for _h in body_hashes_of(result_text or ""):
            _prior = _hashes.get(_h)
            if _prior:
                return f"repeat_of_{_prior}"
    return "new"


def classify_stuck_shape(
    status: str,
    match: str,
    novelty: str,
    result_text: str,
    error_type: str,
    verified_fraction: Optional[float],
    prev_verified_fraction: Optional[float],
    capture_skipped: bool = False,
    vetoed: bool = False,
) -> str:
    """The 5-shape stuck taxonomy (AC3.2). Single-step visible for the first
    four; idling is streak-counted by evaluate_streak (it still labels here
    when the fraction genuinely did not move, and the gate counts runs)."""
    if status == "error" or status == "timeout" or capture_skipped or vetoed:
        # Session-318 T18: a timeout is an execution failure (the van broke
        # down) — flat tire, streak-counted like an empty (AC11.4).
        return "flat_tire"
    if novelty == "empty" or not (result_text or "").strip():
        return "dry_well"
    if novelty.startswith("repeat_of_"):
        return "circling"
    if match == "mismatched":
        return "wrong_package"
    # dry well, chrome-only variant: success-shaped but no substance.
    if status == "success" and len(_one_line(result_text)) < 40 and not (
        result_text or ""
    ).strip():
        return "dry_well"
    if (
        status == "success"
        and novelty == "new"
        and match == "matched"
        and verified_fraction is not None
        and prev_verified_fraction is not None
        and abs(verified_fraction - prev_verified_fraction) < 1e-9
    ):
        return "idling"
    return "none"


def derive_suggestion(
    stuck_shape: str,
    status: str,
    error_type: str,
) -> str:
    """Hierarchy C (AC3.3 / KD-8): WALLED and CIRCLING are HARD — the
    pre-dispatch guard enforces them; the suggestion word still steers.
    Everything else is a strong suggestion the Director may override with a
    logged reason."""
    if error_type == "walled":
        return "stop"  # HARD: a walled tool is never retried in-run
    if stuck_shape == "circling":
        return "try_different"  # HARD: never re-execute; read the original doc
    if stuck_shape == "dry_well":
        return "try_different"  # rephrase, don't repeat (tool_errors: empty)
    if stuck_shape == "wrong_package":
        return "try_different"
    if stuck_shape == "flat_tire":
        # transient failures may retry; anything else: different approach
        if error_type in ("transient", "rate_limited", "cap_reached"):
            return "retry_same"
        return "try_different"
    if stuck_shape == "idling":
        return "try_different"
    if status == "timeout":
        return "try_different"  # AC11.3: never a bare repeat after a hang
    if status == "error":
        return "try_different"
    return "proceed"


# ── Envelope construction (AC1.1–AC1.6) ─────────────────────────────────────


def build_envelope(
    result_text: str,
    step_success: bool,
    outcome: str,
    expected_output: str,
    tool: Optional[str],
    params_digest: str,
    verified_fraction: Optional[float],
    prev_verified_fraction: Optional[float],
    raw_doc_id: str,
    coords_from: Optional[str],
    coords_to: Optional[str],
    turn_memory: Dict[str, Any],
    error: Optional[Dict[str, Any]] = None,
    declared_criticality: str = "supporting",
    capture_skipped: bool = False,
    vetoed: bool = False,
    topo_violation: bool = False,
    card_id: str = "",
    step_id: str = "",
    session_id: str = "",
    turn_id: str = "",
    recovery_of: str = "",
    elapsed_s: float = 0.0,
    timeout: bool = False,
) -> ToolResultEnvelope:
    """Build the envelope ONCE at the finalize site (AC1.2). Pure — no I/O,
    no encodes, no DB writes (AC1.3 / CT-9); zero LLM calls (AC3.5).

    `outcome` is the verifier label (VERIFIED/UNVERIFIED/FAILED);
    `turn_memory` carries crawled_urls / tool_params / step_summaries /
    last_gather_step_id from the kernel's turn state.
    """
    family = tool_family(tool)
    text = str(result_text or "")

    # status: step outcome + tool error shape (AC1.1). A deadline expiry is
    # authoritative (AC11.3) — honest timeout, never folded into error.
    if timeout:
        status = "timeout"
    elif error or not step_success or outcome == "FAILED":
        status = "error"
    elif outcome == "UNVERIFIED":
        status = "partial"
    else:
        status = "success"

    match = derive_match(family, text, expected_output or "", raw_doc_id,
                         turn_memory.get("step_summaries"))
    novelty = derive_novelty(text, tool, params_digest, turn_memory)
    err = error if isinstance(error, dict) else None
    error_type = str((err or {}).get("error_type") or "")
    recovery_hint = str((err or {}).get("recovery_hint")
                        or (err or {}).get("details", {}).get("recovery_hint") or "")
    if status == "error" and not error_type:
        # AC1.1 edge: no structured error dict — classify from the message
        # via the existing tool_errors taxonomy (CT-4 lock), never empty.
        error_type = classify_exception_from_message(text)
        _lbl = resolve_label(error_type)
        if _lbl is not None and not recovery_hint:
            recovery_hint = _lbl.description[:120]
    if status == "timeout":
        # AC11.3: the timeout carries its own cause (deadline named at the
        # dispatch site); never a bare label.
        error_type = error_type or "timeout"
        if not recovery_hint:
            recovery_hint = (
                f"Exceeded the step deadline ({elapsed_s:g}s elapsed); "
                "use a different approach, not a bare repeat."
            )
    stuck_shape = classify_stuck_shape(
        status, match, novelty, text, error_type,
        verified_fraction, prev_verified_fraction,
        capture_skipped=capture_skipped, vetoed=vetoed,
    )
    suggestion = derive_suggestion(stuck_shape, status, error_type)
    if topo_violation:
        # AC3.4: a Caducean TOPO_VIOLATION recommendation is an
        # AUTHORITATIVE override — physics first (KD-4), suggestion=stop.
        suggestion = "stop"

    # Coords: VERBATIM passthrough; explicit empty + basis "none" when no
    # signal exists — never a fabricated zero coordinate (AC1.5).
    if coords_from is None and coords_to is None:
        coords_from_s, coords_to_s, basis = "", "", "none"
    else:
        coords_from_s = str(coords_from or "")
        coords_to_s = str(coords_to or "")
        basis = "format_coords" if (coords_from_s or coords_to_s) else "none"

    criticality, crit_source = confirm_criticality(
        declared_criticality,
        consumed=bool(raw_doc_id) and family in ("gather", "read"),
    )
    # REQ-8 AC8.1: stamp what was actually fetched, capped with an explicit
    # truncation mark (sources_total). Derived here — never a fetch, never
    # a store read; the kernel reuses extract_sources for its step map.
    _sources, _sources_total = extract_sources(text)

    return ToolResultEnvelope(
        status=status,
        summary=_bound_summary(text) or "(no output)",
        raw_ref={"doc_id": raw_doc_id} if raw_doc_id else {},
        match=match,
        novelty=novelty,
        suggestion=suggestion,
        stuck_shape=stuck_shape,
        coords_from=coords_from_s,
        coords_to=coords_to_s,
        coords_basis=basis,
        criticality=criticality,
        criticality_source=crit_source,
        sources=_sources,
        sources_total=_sources_total,
        recovery_of=recovery_of,
        elapsed_s=float(elapsed_s or 0.0),
        card_id=card_id,
        step_id=step_id,
        session_id=session_id,
        turn_id=turn_id,
        error_type=error_type if status != "success" else "",
        recovery_hint=recovery_hint if status != "success" else "",
    )


def minimal_envelope(
    outcome: str,
    content_summary: str,
    raw_doc_id: str,
    coords_from: Optional[str] = None,
    coords_to: Optional[str] = None,
    step_id: str = "",
    session_id: str = "",
    turn_id: str = "",
) -> ToolResultEnvelope:
    """AC1.4 degrade path: when envelope construction fails, build the
    minimal envelope (status from outcome, summary = existing content
    summary, wrapper = match:unclear / novelty:new / suggestion:proceed,
    coords as available) — never break the DER loop."""
    status = {"VERIFIED": "success", "UNVERIFIED": "partial"}.get(outcome, "error")
    if coords_from is None and coords_to is None:
        cf, ct, basis = "", "", "none"
    else:
        cf, ct = str(coords_from or ""), str(coords_to or "")
        basis = "format_coords" if (cf or ct) else "none"
    return ToolResultEnvelope(
        status=status,
        summary=_bound_summary(content_summary) or "(no output)",
        raw_ref={"doc_id": raw_doc_id} if raw_doc_id else {},
        match="unclear",
        novelty="new",
        suggestion="proceed",
        stuck_shape="none",
        coords_from=cf,
        coords_to=ct,
        coords_basis=basis,
        criticality="supporting",
        criticality_source="declared",
        step_id=step_id,
        session_id=session_id,
        turn_id=turn_id,
    )


def params_digest(tool: Optional[str], params: Any) -> str:
    """Stable digest of tool+params for turn-memory repeat detection (AC3.1).

    Session-322: gather repeat key is the SEARCH INTENT, not the visit list.
    `excluded_urls` grows after every gather, so including it makes the same
    query hash differently each time and the digest repeat NEVER fires. Drop
    it (plus volatile siblings) before hashing. Pure, bounded; `default=str`
    tolerates non-JSON param values."""
    import json as _json

    try:
        _p = dict(params or {}) if isinstance(params, dict) else (params or {})
        if isinstance(_p, dict):
            _p = {
                k: v for k, v in _p.items()
                if k not in ("excluded_urls", "known_urls", "seed_urls")
            }
        return _json.dumps(
            {"tool": (tool or ""), "params": _p},
            sort_keys=True, ensure_ascii=False, default=str,
        )
    except Exception:
        return f"{tool or ''}:{sorted((params or {}).keys())}"


def mark_consumed(envelope: "ToolResultEnvelope") -> Tuple[str, str]:
    """AC1.6 retroactive half: when a later step actually consumes this
    envelope's doc (Executor raw_ref read / pre-dispatch reroute), the
    envelope is re-stamped confirmed load-bearing. Returns the
    (before, after) criticality tuple so the caller can log the
    declared-vs-confirmed divergence as a tuning signal (AC7.1/AC7.2)."""
    before = (envelope.criticality, envelope.criticality_source)
    if envelope.criticality != "load-bearing" or envelope.criticality_source != "confirmed":
        envelope.criticality = "load-bearing"
        envelope.criticality_source = "confirmed"
    return before, (envelope.criticality, envelope.criticality_source)


def confirm_criticality(declared: str, consumed: bool) -> Tuple[str, str]:
    """AC1.6 option C (KD-9): the planner DECLARES intent, consumption
    PROVES it. A step declared supporting/cosmetic whose doc later steps
    actually consume is re-stamped confirmed load-bearing; the caller logs
    the declared-vs-confirmed divergence as a tuning signal. Zero LLM, O(1)."""
    d = declared if declared in CRITICALITY_VALUES else "supporting"
    if consumed and d != "load-bearing":
        return "load-bearing", "confirmed"
    return d, "declared"


# ── Streak gate (REQ-5 — O(envelope count) arithmetic, zero LLM, AC5.5) ─────


def evaluate_streak(
    wrappers: List[Dict[str, Any]],
    stuck_n: int,
    idle_n: int,
    topo_violation: bool = False,
    coverage: Optional[float] = None,
    coverage_unmoved_n: int = 0,
    coverage_rho: Optional[float] = None,
    stall_rate: float = 0.0,
) -> Tuple[bool, str]:
    """REQ-5 AC5.1/AC5.2/AC5.3: fire the replan gate only on a stuck streak.

    Fire conditions (trailing consecutive run):
      * N consecutive wrappers with novelty repeat/empty OR match mismatched
      * N consecutive idling wrappers (success + new + matched, fraction unmoved)
      * timeouts count exactly like empties (AC11.4 — a hang is a dry run)
      * goal-contract stall (specs/goal-contract-coverage REQ-3 AC3.4/CT-GC5):
        task coverage C below 1.0 and EITHER unmoved across N settled nodes
        OR the dimensionless progress ratio rho = dC/(g*ds) below the stall
        rate. Patience shrinks as the gap grows — fail on no-progress, never
        on slowness. ``coverage=None`` (no contract) preserves the exact
        legacy behavior — the coverage arms are purely additive.
    TOPO_VIOLATION (Caducean rec, der_loop.py:536) forces fire REGARDLESS of
    streak arithmetic (AC5.3 / KD-4 — reuse the existing physics detection).
    Below threshold → (False, "") — the plan continues, no inference paid.
    """
    if topo_violation:
        return True, "topo_violation"
    if coverage is not None and float(coverage) < 1.0:
        if idle_n > 0 and int(coverage_unmoved_n) >= idle_n:
            return True, (
                f"coverage_stall:C={float(coverage):.3f}"
                f":unmoved={int(coverage_unmoved_n)}"
            )
        if (
            coverage_rho is not None
            and float(stall_rate) > 0.0
            and int(coverage_unmoved_n) >= 1
            and float(coverage_rho) < float(stall_rate)
        ):
            return True, (
                f"coverage_rate:rho={float(coverage_rho):.4f}"
                f"<{float(stall_rate)}:C={float(coverage):.3f}"
            )
    if not wrappers:
        return False, ""

    def _is_stuck(w: Dict[str, Any]) -> bool:
        nov = str(w.get("novelty") or "new")
        return (
            nov == "empty"
            or nov.startswith("repeat_of_")
            or w.get("match") == "mismatched"
            or w.get("status") == "timeout"
        )

    stuck_run = 0
    for w in reversed(wrappers):
        if _is_stuck(w):
            stuck_run += 1
        else:
            break
    if stuck_n > 0 and stuck_run >= stuck_n:
        return True, f"stuck_streak:{stuck_run}"

    def _is_idling(w: Dict[str, Any]) -> bool:
        return (
            w.get("stuck_shape") == "idling"
            and w.get("status") == "success"
            and w.get("novelty") == "new"
            and w.get("match") == "matched"
        )

    idle_run = 0
    for w in reversed(wrappers):
        if _is_idling(w):
            idle_run += 1
        else:
            break
    if idle_n > 0 and idle_run >= idle_n:
        return True, f"idle_streak:{idle_run}"

    return False, ""


def evaluate_run_grade(
    envelopes: List[Any],
    load_bearing_veto: bool = True,
    coverage: Optional[float] = None,
    open_unblocked: Optional[List[str]] = None,
    blocked: Optional[List[str]] = None,
) -> Tuple[str, List[str]]:
    """AC5.6 done + grade: any load-bearing step with match != matched caps
    the run below full pass; supporting/cosmetic misses alone never sink it.
    Goal contract T10 (REQ-8 AC8.1-AC8.3): when coverage inputs are supplied,
    the grade is computed from coverage — C = 1.0 with no blocked fact is a
    pass; an open unblocked fact caps the run below pass (an open unblocked
    fact NEVER reports pass, AC8.3); all-open-facts-blocked-and-named is a
    partial (capped with the blocked list as the reason). A ``coverage=None``
    (no contract) preserves the exact legacy envelope behavior. A run that is
    capped on EITHER signal reports both reason families.
    Returns (grade, reasons) — grade is 'pass' or 'capped' (live over-exceed
    markers — faster-than-baseline etc. — are judged by the live probe, not
    here). Zero LLM, O(n) over envelopes."""
    reasons: List[str] = []
    for env in envelopes:
        crit = getattr(env, "criticality", "supporting")
        if getattr(env, "match", "unclear") != "matched" and crit == "load-bearing":
            reasons.append(
                f"step {getattr(env, 'step_id', '?')} load-bearing "
                f"match={getattr(env, 'match', 'unclear')}"
            )
    if coverage is not None:
        try:
            _c = float(coverage)
        except Exception:
            # AC8 edge: coverage computation failed — grade unavailable,
            # logged, never silently pass.
            return "unavailable", ["coverage computation failed"]
        _open = [str(_f) for _f in (open_unblocked or []) if str(_f).strip()]
        _blocked = [str(_f) for _f in (blocked or []) if str(_f).strip()]
        if _open:
            reasons.append(
                f"goal coverage C={_c:.3f}: "
                f"{len(_open)} required fact(s) open and unblocked"
            )
            for _f in _open[:5]:
                reasons.append(f"open fact: {_f[:160]}")
        elif _blocked:
            reasons.append(
                f"goal coverage C={_c:.3f}: every open fact blocked and "
                f"named ({len(_blocked)})"
            )
            for _f in _blocked[:5]:
                reasons.append(f"blocked fact: {_f[:160]}")
        if _open or _c < 1.0:
            if load_bearing_veto and reasons:
                return "capped", reasons
            if _c < 1.0:
                return "capped", reasons or [f"C={_c:.3f} below 1.0"]
    if load_bearing_veto and reasons:
        return "capped", reasons
    return "pass", []

"""Goal contract — pure deterministic core (specs/goal-contract-coverage, T1).

The contract is the TASK NODE's record, not a new store (KD-1). Coverage C is
the task node's verified_fraction (KD-2). The gap g = 1 - C is the forcing
term on the existing cognitive u (KD-3). This module is pure: deterministic,
zero LLM calls, zero I/O. Logging only.

Layer rule (REQ-10): this module imports NO oscillator/phase module. The gap
feeds the cognitive u path at the call site; the scheduler path is untouched.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_FALLBACK_REQUIRED_CAP = 12
_FALLBACK_CEILING_CAP = 8

_STOPWORDS = frozenset({
    "the", "and", "for", "with", "find", "search", "research",
    "compare", "whether", "how", "its", "any", "github",
    "documentation", "authoritative", "information", "please",
    "show", "give", "what", "when", "that", "this", "from",
    "into", "your", "about", "which", "their", "there",
})

_ENUM_PREFIX_RE = re.compile(r"^\s*(?:\d+[.)]\s+|\(\d+\)\s*|[-*•]\s+)")
_SPLIT_RE = re.compile(r"\s*(?:\n+|;+|\s+\d+[.)]\s+|\s*\(\d+\)\s*)\s*")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{3,}")
_AND_RE = re.compile(r"\s+and\s+", re.IGNORECASE)
# The lead-in is one clause: no sentence end before the colon ("...main.py.
# Example: f('a, b')" is not a list).
_LIST_LEAD_RE = re.compile(r"^((?:(?![.!?]\s)[^:]){3,}):\s+(.+)$", re.DOTALL)
_LIST_JOIN_RE = re.compile(r"^(?:and|or)\s+", re.IGNORECASE)
# A list comma, not one inside a call or a quote: "add(name, qty)".
_LIST_COMMA_RE = re.compile(r",(?![^()]*\))(?=(?:[^'\"]*['\"][^'\"]*['\"])*[^'\"]*$)")
# A prohibition ("do not change app.py") is kept by NOT acting, so no step can
# cover it; as a required fact it drew a push per boundary (eval c06,
# 2026-10-01: 36 pushes, reply 366 s). Nodes still see it - every node gets
# the user's request word for word (S5).
_PROHIBITION_RE = re.compile(
    r"^(?:and\s+|but\s+)?(?:do\s+not|don'?t|never|must\s+not|should\s+not|"
    r"shouldn'?t|without)\b",
    re.IGNORECASE,
)
# Page scaffolding a web tool result wraps around content: "--- Source: URL ---" headers,
# the "--- Attempted:" / "--- Dead:" / "--- Outlinks ..." machine lines, bare-URL outlink
# bullets, and the truncation marker. None of it is a deliverable, yet each line used to
# become a "discovered fact" (and a needless bonus pass) - spec A6 / RC6.
_SCAFFOLD_LINE_RE = re.compile(
    r"^\s*(?:-{3,}\s*(?:source|attempted|dead|outlinks)\b.*"
    r"|[-*•]\s+https?://\S+"
    r"|\(\+\d+\s+already-visited.*\)"
    r"|\[\.\.\.truncated\.\.\.\])\s*$",
    re.IGNORECASE,
)


def _goal_cap(name: str, fallback: int) -> int:
    """Read a GOAL_* cap lazily so this module never creates an import cycle."""
    try:
        from backend.agent import der_constants as _dc

        _val = getattr(_dc, name, fallback)
        return int(_val) if int(_val) > 0 else fallback
    except Exception:
        return fallback


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _clean_fact(text: str) -> str:
    _t = _ENUM_PREFIX_RE.sub("", (text or "").strip())
    _t = re.sub(r"\s+", " ", _t).strip().rstrip(".")
    return _t


def _distinctive_terms(text: str) -> List[str]:
    _seen: Dict[str, None] = {}
    for _w in _WORD_RE.findall(text or ""):
        _lw = _w.lower()
        if _lw in _STOPWORDS:
            continue
        if _lw not in _seen:
            _seen[_lw] = None
    return list(_seen.keys())


_NAME_RUN_RE = re.compile(r"\b[A-Z][a-z]+\b(?: [A-Z][a-z]+\b)*")
_QUOTED_RE = re.compile(
    r"(?<![A-Za-z])'[^']*'|\"[^\"]*\"|`[^`]*`"
    r"|\S*[\\/]\S*?(?=[.,;:!?]?(?:\s|$))"  # a path; its sentence end stays
)


def _names_in(text: str) -> List[str]:
    """The names a fact holds, lowercased: runs of capitalized words
    ("Golden Gate Bridge", "Harry Potter"). Not names: a capital that only
    opens a sentence ("The", "Fix"), a code identifier ("ImportError",
    "DEFAULTS" - a reply about the fix need not repeat it), quoted text
    ("slugify('Hello, World!')" is an example, not a subject) and paths (the
    eval work folder "C:\\Users\\...\\Local\\Temp" gave c02 the names "users",
    "local", "temp": 2 pushes, reply 84 s)."""
    _out: List[str] = []
    text = _QUOTED_RE.sub(lambda _q: " " * len(_q.group(0)), text or "")
    for _m in _NAME_RUN_RE.finditer(text):
        _words = _m.group(0).split(" ")
        _before = text[:_m.start()].rstrip()
        if not _before or _before[-1] in ".!?:;":
            _words = _words[1:]
        _name = " ".join(_words).lower()
        if len(_name) >= 3 and _name not in _out:
            _out.append(_name)
    return _out


# One "Actions:" line of a node result (node_executor.NodeResult.as_step_result):
# "- run_command python -m pytest -q -> ok".
_ACTION_RE = re.compile(r"^- (\S+) ?(.*?) -> (ok|FAILED)\s*$", re.MULTILINE)
# A command that runs the code or its tests (not "ls", not "git status").
_CHECK_CMD_RE = re.compile(
    r"\b(?:pytest|unittest|python3?|py|node|npm|npx|jest|vitest|go|cargo|dotnet|mvn|gradle|make)\b",
    re.IGNORECASE,
)
_LAST_CMD_FAILED = "last command in this step exited non-zero"


def _checked_after_change(result: str) -> bool:
    """True when the step RAN the code or its tests after its last file change
    and that run passed. A passing run is outside evidence for a spec fact a
    coding node's result does not repeat word for word ("raises ValueError if
    there is not enough" vs "- run_command python -m pytest -q -> ok"; live
    c10 2026-10-05: an own-word rule left that fact open, 2 pushes, reply
    15 -> 47 s)."""
    if not result or _LAST_CMD_FAILED in result:
        return False
    from backend.agent.node_executor import _CHANGE_TOOLS

    acts = _ACTION_RE.findall(result)
    last_change = max((i for i, a in enumerate(acts) if a[0] in _CHANGE_TOOLS), default=-1)
    return any(
        tool == "run_command" and ok == "ok" and _CHECK_CMD_RE.search(target)
        for tool, target, ok in acts[last_change + 1:]
    )


@dataclass(frozen=True)
class Contract:
    """The goal contract: floor (required) + ceiling (discovered) + version."""

    required: Tuple[str, ...]
    ceiling: Tuple[str, ...] = ()
    version: int = 1


@dataclass(frozen=True)
class Coverage:
    """Terminal coverage verdict for one contract state."""

    covered: Tuple[str, ...]
    blocked: Tuple[Tuple[str, str], ...]
    required_n: int
    ceiling_n: int
    C: float
    g: float
    rho: float = 0.0
    ds: float = 0.0


def extract_required(request: str) -> Tuple[str, ...]:
    """Derive the required-fact set deterministically (REQ-1 AC1.1, AC1.6).

    Zero LLM calls. Splits enumerated asks, numeric counts, and delimited
    deliverables; dedupes by normalized text; caps at GOAL_REQUIRED_FACTS_CAP.
    Falls back to a single fact equal to the request summary when nothing is
    extractable.
    """
    _raw = request or ""
    _stripped = _raw.strip()
    if not _stripped:
        logger.info("[goal-contract] extract fallback: empty request")
        return ("",)
    # Spec A6: drop web-page scaffolding lines first. A text that is ONLY scaffolding
    # has no deliverable at all (the empty fallback), not itself as a fact.
    _kept = [_ln for _ln in _stripped.splitlines() if not _SCAFFOLD_LINE_RE.match(_ln)]
    if len(_kept) != len(_stripped.splitlines()):
        _stripped = "\n".join(_kept).strip()
        if not _stripped:
            logger.info("[goal-contract] extract fallback: scaffolding only")
            return ("",)
    _parts: List[str] = []
    for _chunk in _SPLIT_RE.split(_stripped):
        _chunk = (_chunk or "").strip()
        if not _chunk:
            continue
        # "Do X and give each one: A, B, and C" - the list after the colon is
        # what is asked for; the lead-in only says how. As a fact of its own it
        # can never be covered, and before the list was split it hid B inside
        # A's fact (eval r09, 2026-10-04: "the year the Golden Gate Bridge
        # opened" rode in the Eiffel Tower fact and was never searched).
        _lead = _LIST_LEAD_RE.match(_chunk)
        if _lead and ("," in _lead.group(2) or _AND_RE.search(_lead.group(2))):
            _chunk = _lead.group(2).strip()
        # A comma list first ("A, B, and C"), then "A and B" inside each item.
        _items = [_chunk]
        if len(_LIST_COMMA_RE.findall(_chunk)) >= 2:
            _subs = [_LIST_JOIN_RE.sub("", _s.strip()) for _s in _LIST_COMMA_RE.split(_chunk)]
            _subs = [_s for _s in _subs if _s]
            if len(_subs) > 1 and all(len(_s) >= 8 for _s in _subs):
                _items = _subs
        for _item in _items:
            # Split "A and B" only when both sides carry substance, so a single
            # "research X and summarize" ask is not torn into fragments.
            if _AND_RE.search(_item):
                _sides = [_s.strip() for _s in _AND_RE.split(_item) if _s.strip()]
                if len(_sides) > 1 and all(len(_s) >= 12 for _s in _sides):
                    _parts.extend(_sides)
                    continue
            _parts.append(_item)
    _facts: List[str] = []
    _seen: Dict[str, None] = {}
    for _p in _parts:
        _f = _clean_fact(_p)
        if not _f:
            continue
        if _PROHIBITION_RE.match(_f):
            logger.info("[goal-contract] prohibition, not a deliverable: %r", _f[:120])
            continue
        _k = _norm(_f)
        if _k in _seen:
            continue
        _seen[_k] = None
        _facts.append(_f)
    if not _facts:
        logger.info("[goal-contract] extract fallback: no deliverable found")
        return (_stripped,)
    _cap = _goal_cap("GOAL_REQUIRED_FACTS_CAP", _FALLBACK_REQUIRED_CAP)
    if len(_facts) > _cap:
        logger.info(
            "[goal-contract] extract truncated: %d facts capped at %d",
            len(_facts), _cap,
        )
        _facts = _facts[:_cap]
    return tuple(_facts)


def _step_text(step: object) -> str:
    if step is None:
        return ""
    if isinstance(step, str):
        return step
    # "description" last: the planner emits goals only (no expected_output),
    # so without it no fact ever mapped to a step (r09: "3 omitted" every run).
    if isinstance(step, dict):
        for _k in ("expected_output", "expected", "text", "summary", "description"):
            _v = step.get(_k)
            if _v:
                return str(_v)
        return ""
    for _k in ("expected_output", "expected", "text", "summary", "description"):
        _v = getattr(step, _k, None)
        if _v:
            return str(_v)
    return ""


def map_to_steps(
    facts: Iterable[str],
    steps: Iterable[object],
) -> Tuple[str, ...]:
    """Return the facts NO step's expected_output covers (REQ-1 AC1.2/AC1.3).

    A fact is mapped when its normalized text appears in a step, or when all
    of its distinctive terms appear in a single step's expected_output.
    """
    _facts = [str(_f) for _f in (facts or ())]
    _texts = [_step_text(_s).lower() for _s in (steps or ())]
    _omitted: List[str] = []
    for _f in _facts:
        _fl = _f.lower()
        _terms = _distinctive_terms(_f)
        _mapped = False
        for _t in _texts:
            if not _t:
                continue
            if _fl and _fl in _t:
                _mapped = True
                break
            if _terms and all(_term in _t for _term in _terms):
                _mapped = True
                break
        if not _mapped:
            _omitted.append(_f)
    return tuple(_omitted)


def _outcome_verified(outcome: object) -> bool:
    if outcome is None:
        return False
    if isinstance(outcome, str):
        return outcome.strip().upper() in ("VERIFIED", "OK", "PARTIAL")
    if isinstance(outcome, (tuple, list)) and outcome:
        return _outcome_verified(outcome[0])
    _status = getattr(outcome, "status", outcome)
    _val = getattr(_status, "value", _status)
    try:
        return str(_val).strip().upper() in ("VERIFIED", "OK", "PARTIAL", "SUCCESS")
    except Exception:
        return False


def mark_coverage(
    contract: Contract,
    node_outcomes: Iterable[object],
    results: Iterable[str],
) -> Coverage:
    """Compute set-union coverage (REQ-2 AC2.1-AC2.5).

    A required fact is covered only if a VERIFIED child's result carries:
      - one of the fact's OWN names as whole words ("Golden Gate Bridge",
        "Harry Potter") - a name no other required fact holds; else
      - one of its OWN terms (a term no other required fact holds; all its
        terms when it has fewer than two own), or a passing run of the code
        or its tests after the step's last file change.
    In eval r09 (2026-10-04) a result about the Eiffel Tower covered "the
    year the first Harry Potter book was published" through "year", C read
    1.0 and the turn ended with 2 of 3 facts never searched. A fact's OWN
    words were not enough either: that search result carries a "PRIOR
    RESEARCH" block with "first", "published", "Gate" and "Bridge" (run
    conv-789), but not "Golden Gate Bridge" or "Harry Potter" - over 186
    stored single-topic searches the old rule covered more than one fact in
    every one, the name rule in none. A coding node's result says "8
    passed", not the words of the spec ("raises ValueError if there is not
    enough"): own terms alone left such a fact open in live c10 (2 pushes,
    blocked, reply 15 -> 47 s), hence the passing-run evidence.
    Facts with no distinctive terms are covered by VERIFIED status alone
    (weak check, logged).
    """
    _required = list(contract.required) if contract else []
    _outcomes = list(node_outcomes or [])
    _results = [str(_r or "") for _r in (results or [])]
    while len(_results) < len(_outcomes):
        _results.append("")
    _covered: List[str] = []
    _seen: Dict[str, None] = {}
    _lows = [_norm(_f) for _f in _required]
    _all_terms = [_distinctive_terms(_f) for _f in _required]
    for _i, _fact in enumerate(_required):
        _terms = _all_terms[_i]
        # A term another fact also holds ("year") cannot tell them apart.
        _shared = {_t for _j, _ts in enumerate(_all_terms) if _j != _i for _t in _ts}
        _own = [_t for _t in _terms if _t not in _shared]
        _match_terms = _own if len(_own) >= 2 else _terms
        _names = [
            _n for _n in _names_in(_fact)
            if not any(_n in _lows[_j] for _j in range(len(_required)) if _j != _i)
        ]
        if _names:
            # whole words: "bun" is not in "bundle"
            _name_re = re.compile(
                r"\b(?:" + "|".join(re.escape(_n) for _n in _names) + r")\b"
            )
        _hit = False
        for _oc, _res in zip(_outcomes, _results):
            if not _outcome_verified(_oc):
                continue
            _low = _norm(_res)
            if not _terms:
                if _res.strip():
                    logger.info(
                        "[goal-contract] weak cover (no distinctive terms): %r",
                        _fact[:80],
                    )
                    _hit = True
                    break
                continue
            if _names:
                _found = _name_re.search(_low) is not None
            else:
                _found = (any(_t in _low for _t in _match_terms)
                          or _checked_after_change(_res))
            if _found:
                _hit = True
                break
        if _hit:
            _k = _norm(_fact)
            if _k not in _seen:
                _seen[_k] = None
                _covered.append(_fact)
    _n = len(_required)
    _c = (len(_covered) / _n) if _n else 1.0
    _c = max(0.0, min(1.0, float(_c)))
    _g = 1.0 - _c
    if not _n:
        logger.info("[goal-contract] degenerate contract: empty required set, C=1.0")
    return Coverage(
        covered=tuple(_covered),
        blocked=(),
        required_n=_n,
        ceiling_n=len(contract.ceiling) if contract else 0,
        C=_c,
        g=_g,
    )


def progress_ratio(prev_c: float, new_c: float, g: float, ds: float) -> float:
    """Dimensionless progress ratio rho = dC / (g * ds) (REQ-3 AC3.4).

    Never raises: degenerate inputs yield 0.0 (treated as not-stalled this
    cycle by the caller, per the design error table).
    """
    try:
        _g = float(g)
        _ds = float(ds)
        if _g <= 0.0 or _ds <= 0.0:
            return 0.0
        return max(0.0, (float(new_c) - float(prev_c)) / (_g * _ds))
    except Exception:
        return 0.0


def amend(
    contract: Contract,
    *,
    add: Iterable[str] = (),
    remove: Iterable[str] = (),
    source: str = "user",
    reason: str = "",
) -> Contract:
    """Amend the floor in place, preserving task identity (REQ-4).

    Floor protection: an agent-sourced amendment NEVER changes the floor —
    removals and floor adds from the agent are refused (agent discoveries go
    through add_ceiling). Only the user may add, remove, or repromote.
    """
    if contract is None:
        return Contract(required=tuple())
    _src = (source or "user").strip().lower()
    if _src not in ("user", "agent"):
        _src = "user"
    _adds = [str(_a) for _a in (add or ()) if str(_a or "").strip()]
    _rems = [str(_r) for _r in (remove or ()) if str(_r or "").strip()]
    if _src == "agent" and (_adds or _rems):
        logger.warning(
            "[goal-contract] amend refused: agent may not mutate the floor (%s)",
            reason[:120] if reason else "no reason",
        )
        return contract
    _req = list(contract.required)
    _keys = {_norm(_f) for _f in _req}
    _changed = False
    if _rems:
        _rem_keys = {_norm(_r) for _r in _rems}
        _new = [_f for _f in _req if _norm(_f) not in _rem_keys]
        if len(_new) != len(_req):
            _req = _new
            _keys = {_norm(_f) for _f in _req}
            _changed = True
    if _adds:
        _cap = _goal_cap("GOAL_REQUIRED_FACTS_CAP", _FALLBACK_REQUIRED_CAP)
        for _a in _adds:
            _f = _clean_fact(_a)
            if not _f or _norm(_f) in _keys:
                continue
            if len(_req) >= _cap:
                logger.info("[goal-contract] amend truncated at cap %d", _cap)
                break
            _req.append(_f)
            _keys.add(_norm(_f))
            _changed = True
    if not _changed:
        return contract
    return Contract(
        required=tuple(_req), ceiling=contract.ceiling,
        version=int(contract.version) + 1,
    )


def add_ceiling(contract: Contract, facts: Iterable[str]) -> Contract:
    """Add agent-discovered ceiling facts, capped, never blocking (REQ-4 AC4.2)."""
    if contract is None:
        return Contract(required=tuple())
    _cap = _goal_cap("GOAL_CEILING_CAP", _FALLBACK_CEILING_CAP)
    _floor = {_norm(_f) for _f in contract.required}
    _ceil = list(contract.ceiling)
    _keys = {_norm(_f) for _f in _ceil} | _floor
    _changed = False
    for _raw in facts or ():
        _f = _clean_fact(str(_raw or ""))
        if not _f or _norm(_f) in _keys:
            continue
        if len(_ceil) >= _cap:
            logger.info("[goal-contract] ceiling truncated at cap %d", _cap)
            break
        _ceil.append(_f)
        _keys.add(_norm(_f))
        _changed = True
    if not _changed:
        return contract
    return Contract(
        required=contract.required, ceiling=tuple(_ceil),
        version=int(contract.version) + 1,
    )


def is_blocked(reason: object) -> bool:
    """True when a reason blocks a fact (terminal + APPROVAL_UNAVAILABLE)."""
    if reason is None:
        return False
    _val = getattr(reason, "value", reason)
    _name = str(_val or "").strip().lower()
    if _name in ("approval_unavailable", "approval-unavailable"):
        return True
    try:
        from backend.agent.nodes.outcome import (
            Reason as _Reason,
            is_terminal_reason as _is_terminal,
        )

        if isinstance(reason, _Reason):
            return bool(_is_terminal(reason))
        try:
            return bool(_is_terminal(_Reason(_name)))
        except Exception:
            return False
    except Exception:
        return _name in ("robots_refused", "permission_denied")


_REMOVAL_MARKERS = (
    "drop", "remove", "delete", "forget", "skip", "ignore", "without",
    "exclude", "cut", "no longer need", "don't need", "dont need",
    "do not need", "not needed",
)
_ADD_CUES = ("also", "add ", "include", "plus", "as well", "additionally")


def _match_facts(needle: str, facts: Iterable[str]) -> List[str]:
    """Return the facts a free-text needle refers to (REQ-4 T7).

    Deterministic: normalized substring either direction, else distinctive-
    term overlap (>=2 shared terms, or >=50% of the fact's terms).
    """
    _n = _norm(needle)
    if not _n:
        return []
    _needle_terms = set(_distinctive_terms(needle))
    _hits: List[str] = []
    for _f in facts or ():
        _f = str(_f)
        _fl = _norm(_f)
        if not _fl:
            continue
        if _fl in _n or _n in _fl:
            _hits.append(_f)
            continue
        _fterms = _distinctive_terms(_f)
        if not _fterms or not _needle_terms:
            continue
        _shared = len(set(_fterms) & _needle_terms)
        if _shared >= 2 or _shared / max(1, len(_fterms)) >= 0.5:
            _hits.append(_f)
    return _hits


def step_fact_hits(uncovered: Iterable[str], step_text: str) -> Tuple[str, ...]:
    """Facts a step's text was working on (REQ-5 T9 mapping).

    Used both ways: which uncovered facts a failed step maps to (blocking),
    and which blocked facts an answer text already names (T9 naming check).
    """
    return tuple(_match_facts(step_text or "", uncovered))


def parse_steering_amendment(
    text: str,
    required: Iterable[str],
    blocked: Iterable[str] = (),
) -> Dict[str, Tuple[str, ...]]:
    """Parse user steering into a floor amendment (REQ-4 AC4.1, T7).

    Deterministic, zero LLM. Removal only on explicit removal markers;
    addition of genuinely new facts only on additive cues; a blocked fact
    mentioned without a removal cue is repromoted (unblocked). Anything
    else yields empty lists — steering is noted, the contract unchanged.
    """
    _req = [str(_f) for _f in (required or ())]
    _blocked = [str(_f) for _f in (blocked or ())]
    _adds: List[str] = []
    _removes: List[str] = []
    _repromotes: List[str] = []
    _text = (text or "").strip()
    if not _text:
        return {"add": (), "remove": (), "repromote": ()}
    _low = _text.lower()
    _clauses = [
        _c.strip() for _c in re.split(r"[\n;]+|\.\s+", _text) if _c.strip()
    ]
    for _cl in _clauses:
        _cl_low = _cl.lower()
        _marker_at = -1
        for _m in _REMOVAL_MARKERS:
            _pos = _cl_low.find(_m)
            if _pos >= 0:
                _marker_at = _pos + len(_m)
                break
        if _marker_at >= 0:
            _hits = _match_facts(_cl[_marker_at:], _req)
            for _h in _hits:
                if _h not in _removes:
                    _removes.append(_h)
            continue
        for _b in _match_facts(_cl, _blocked):
            if _b not in _repromotes:
                _repromotes.append(_b)
    if any(_cue in _low for _cue in _ADD_CUES):
        _existing = {_norm(_f) for _f in _req}
        for _cand in extract_required(_text):
            _stripped = _cand
            try:
                _stripped = re.sub(
                    r"^(?:also\s+add|also|additionally|add|include|including|"
                    r"plus|as\s+well\s+as)\s+",
                    "", str(_cand or "").strip(), flags=re.IGNORECASE,
                ).strip() or str(_cand)
            except Exception:
                _stripped = _cand
            if _norm(_stripped) in _existing:
                continue
            if _match_facts(_stripped, _removes):
                continue
            _adds.append(_stripped)
            _existing.add(_norm(_stripped))
    return {"add": tuple(_adds), "remove": tuple(_removes),
            "repromote": tuple(_repromotes)}

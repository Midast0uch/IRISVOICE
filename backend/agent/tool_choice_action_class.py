"""The tool_choice label that matches the Oracle's actual job.

The outcome label ("did the step complete") grades the assistant's execution:
its arguments, its verification, its final answer. The Oracle only chooses the
TOOL. Measured 2026-11-07: all 5 failed rows picked read_file for a read /
inspect / verify step - the correct tool - and failed on a stale target path or
a verification; the pre-call features had no signal (AUROC 0.50, p=0.47).

This label asks the Oracle's question instead: did it pick a tool of the right
ACTION CLASS for the step's goal?

Classes: READ, WRITE, RUN, CONTROL (stop/delegate/none), UNKNOWN.

The required class comes from the FIRST action verb of the step's goal, plus how
far the step has got (``calls_this_step``):
  * read/inspect/identify/verify ...      -> READ
  * create/write/add ...                  -> WRITE (act now)
  * fix/update/change/refactor ...        -> READ if nothing read yet (gather),
                                             WRITE once reads exist (act)
  * run/execute/test ...                  -> RUN
  * anything else                         -> UNKNOWN (no label; never guessed)

This is a stated rule, not a model. It is deliberately narrow: it labels the
class, not the exact tool, and it returns None when the goal is ambiguous.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, List, Optional, Tuple

READ = "READ"
WRITE = "WRITE"
RUN = "RUN"
CONTROL = "CONTROL"
UNKNOWN = "UNKNOWN"

TOOL_CLASS = {
    "read_file": READ,
    "grep_files": READ,
    "glob_files": READ,
    "list_directory": READ,
    "git_status": READ,
    "git_diff": READ,
    "read_command_output": READ,
    "recall_memory": READ,
    "write_file": WRITE,
    "edit_file": WRITE,
    "append_file": WRITE,
    "create_directory": WRITE,
    "create_artifact": WRITE,
    "run_command": RUN,
    "stop_command": CONTROL,
    "DELEGATE": CONTROL,
    "NONE": CONTROL,
}

_READ_FIRST = frozenset({
    "read", "inspect", "identify", "match", "cross-check", "examine",
    "review", "explain", "report", "count", "extract", "locate",
    "determine", "compare", "summarize", "summarise", "find", "search",
    "list", "show", "check", "verify", "assess", "analyze", "analyse",
    "scan", "look", "open", "traverse", "gather", "collect",
})
_DIRECT_WRITE_FIRST = frozenset({
    "create", "write", "add", "append", "insert", "make", "build",
    "generate", "replace",
})
_FIX_WRITE_FIRST = frozenset({
    "fix", "update", "change", "modify", "refactor", "rename", "remove",
    "delete", "edit", "implement",
})
_RUN_FIRST = frozenset({"run", "execute", "test"})

_READ_CALLS = ("read_file", "grep_files", "glob_files")
_WRITE_CALLS = ("edit_file", "write_file", "append_file", "create_artifact")


def classify_tool(tool: Optional[str]) -> str:
    return TOOL_CLASS.get(str(tool or ""), UNKNOWN)


def _first_word(goal: str) -> str:
    for tok in re.split(r"\s+", str(goal or "").strip()):
        word = tok.strip("`'\"*:.,;()[]").lower()
        if word:
            return word
    return ""


def required_class(goal: str, calls_this_step: str = "") -> Optional[str]:
    """The single first-verb class (no plan phase). Kept for simple callers."""
    first = _first_word(goal)
    calls = str(calls_this_step or "").lower()
    has_read = any(k in calls for k in _READ_CALLS)
    if first in _RUN_FIRST:
        return RUN
    if first in _DIRECT_WRITE_FIRST:
        return WRITE
    if first in _FIX_WRITE_FIRST:
        return WRITE if has_read else READ
    if first in _READ_FIRST:
        return READ
    return None


def required_classes(goal: str, calls_this_step: str = "",
                     step_id: str = "") -> Optional[frozenset]:
    """The classes this step can correctly use, by FIRST VERB and PLAN PHASE.

    The eval plans are phase-shaped: s1 gathers, s2 acts, s3 verifies. Reading a
    "Rename ..." step in s2 as a READ step marked a correct edit_file pick wrong
    (measured 2026-11-07, 80.5% raw accuracy). The phase fixes that.
    A verify step may read or run; that is a set, not one class.
    """
    sid = str(step_id or "").strip()
    first = _first_word(goal)
    calls = str(calls_this_step or "").lower()
    has_read = any(k in calls for k in _READ_CALLS)
    n = 0
    if sid.startswith("s") and sid[1:].isdigit():
        n = int(sid[1:])
    # The GOAL'S FIRST VERB is the primary signal. Read is ALWAYS allowed: it
    # is the safe gather action, and forbidding it in a RUN step made the model
    # explore with shell commands (c14: list_directory failed, 28 commands,
    # 301 s vs 23.6 s). The guard exists to stop a WRONG SIDE EFFECT, never a
    # read.
    if first in _RUN_FIRST:
        return frozenset({READ, RUN})
    if first in _DIRECT_WRITE_FIRST:
        return frozenset({READ, WRITE})
    if first in _FIX_WRITE_FIRST:
        if n == 1:
            return frozenset({READ})
        if n >= 3:
            return frozenset({READ, WRITE, RUN})
        return frozenset({READ, WRITE})
    if first in _READ_FIRST:
        if n >= 3:
            return frozenset({READ, RUN})
        return frozenset({READ})
    if first in _RUN_FIRST:
        return frozenset({RUN})
    if first in _DIRECT_WRITE_FIRST:
        return frozenset({WRITE})
    if first in _FIX_WRITE_FIRST:
        return frozenset({WRITE}) if has_read else frozenset({READ, WRITE})
    if first in _READ_FIRST:
        return frozenset({READ})
    return None


def action_class_ok(tool: Optional[str], goal: str,
                    calls_this_step: str = "",
                    step_id: str = "") -> Optional[bool]:
    """True/False for a labelable step, None when the goal is ambiguous."""
    need = required_classes(goal, calls_this_step, step_id)
    if need is None:
        return None
    got = classify_tool(tool)
    if got == UNKNOWN:
        return None
    return got in need


# ── THE GUARD + THE OWNER'S ALWAYS-ENFORCE FLAG (2026-11-07) ────────────────
# The Oracle's confidence does not rank its class errors (measured AUROC 0.61
# over three label designs). The sure path is not a threshold: it is a
# deterministic class GUARD plus the owner's always-enforce policy.
#   * allowed_tools() narrows the menu to the required class, so the Oracle
#     cannot pick the wrong class. It still picks the specific tool.
#   * always_enabled() is the owner's switch. When on, the Oracle is consulted
#     on EVERY decision and its pick is used without a calibrated threshold.
# An UNKNOWN class abstains (returns None) so enforcement never runs unguarded.
ENV_ALWAYS = "IRIS_ORACLE_TOOL_CHOICE_ALWAYS"
ENV_SHORTLIST_K = "IRIS_ORACLE_TOOL_CHOICE_SHORTLIST_K"
ENV_CLASS_DECISION = "IRIS_ORACLE_TOOL_CHOICE_CLASS_DECISION"
# The class margin below which the class decision is NOT taken. Measured on
# 398 stored rows (2026-11-08): top-1 class 93.7% overall; margin <0.1 64.7%,
# 0.1-0.3 88.5%, 0.3-0.7 92.4%, >=0.7 97.7%. The low-margin rows fall back to
# the shortlist instead of forcing a class.
CLASS_MARGIN_MIN = 0.30


def class_decision_enabled() -> bool:
    """The d1-2b decides the CLASS; the model picks the specific tool."""
    return os.environ.get(ENV_CLASS_DECISION, "").strip().lower() in (
        "1", "true", "yes", "on")


def class_masses(distribution, top_class: Optional[str] = None):
    """``(masses, margin)`` over READ/WRITE/RUN from a tool distribution.

    With ``top_class`` the margin is THAT class's mass minus its strongest
    competitor: the other two classes AND the summed mass of the offered tools
    outside the class map (browser, web search, desktop - UNKNOWN). Without it,
    the top class minus the runner-up (the measurement form).

    Why (2026-11-09): the class taken is the top-1 tool's class, so the margin
    must be about that class - 26 of 1581 stored rows had a top-1 class that
    was not the mass argmax. And the class map covers only the coding tools:
    of those 1581 rows, ONE offered the web/browser tools, so a READ margin
    counted against coding classes alone could strip ``search`` from a
    research step. Measured on the 1361 labelled rows: the same 1342 rows clear
    0.30 under both forms (coding menus carry ~no UNKNOWN mass).
    """
    masses = {READ: 0.0, WRITE: 0.0, RUN: 0.0}
    other = 0.0
    for c in distribution or ():
        name = str(getattr(c, "name", "") or "")
        cl = classify_tool(name)
        try:
            prob = float(getattr(c, "prob", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if cl in masses:
            masses[cl] += prob
        elif cl == UNKNOWN:
            other += prob
    if top_class in masses:
        rival = max([v for k, v in masses.items() if k != top_class] + [other])
        return masses, round(masses[top_class] - rival, 6)
    order = sorted(masses.items(), key=lambda t: t[1], reverse=True)
    return masses, round(order[0][1] - order[1][1], 6)


def always_enabled() -> bool:
    """The owner's always-enforce policy. Read per call; default OFF."""
    return os.environ.get(ENV_ALWAYS, "").strip().lower() in (
        "1", "true", "yes", "on")


def shortlist_k() -> int:
    """Candidate-compression depth. 0 = off (the full menu goes to the model).

    The Oracle RANKS; the model PICKS from the top-k. This is the standard
    tool-retrieval pattern (Toollery/Tool RAG): a smaller candidate set is both
    more accurate and faster, and the model keeps the final choice.
    """
    try:
        return max(0, int(os.environ.get(ENV_SHORTLIST_K, "0") or 0))
    except ValueError:
        return 0


def allowed_tools(
    tools: Iterable[str], goal: str,
    calls_this_step: str = "", step_id: str = "",
) -> Tuple[List[str], Optional[frozenset]]:
    """``(tools of the required class, required class set or None)``.

    ``None`` means the goal is ambiguous: the caller must NOT enforce (there is
    no guard). An empty list means the class is known but no offered tool fits:
    the caller must abstain.
    """
    ordered = [str(t) for t in tools if t]
    need = required_classes(goal, calls_this_step, step_id)
    if need is None:
        return ordered, None
    return [t for t in ordered if classify_tool(t) in need], need


_CONTROLS = frozenset({"DELEGATE", "NONE"})
# Tools that are safe but rarely the best next step for a coding node. They
# stay AVAILABLE; they are demoted in the shortlist so a core tool takes the
# slot (measured: the top-5 carried list_directory/recall_memory and the model
# explored them before read_file). Curation, not removal.
_LOW_VALUE = frozenset({
    "list_directory", "recall_memory", "read_command_output", "stop_command",
})


def shortlist_from_distribution(
    distribution, k: int, demote: float = 0.20,
) -> List[str]:
    """The Oracle's top-k tool names, with low-value tools demoted.

    Controls (DELEGATE/NONE) are never in the model's tool list. The menu was
    already narrowed by the class guard, so this list is safe by construction.
    ``demote`` subtracts from a low-value tool's score so a core tool wins the
    slot; it never removes a tool the model may still need.
    """
    if k <= 0:
        return []
    ranked = []
    for c in distribution or ():
        name = str(getattr(c, "name", "") or "")
        if not name or name in _CONTROLS:
            continue
        try:
            prob = float(getattr(c, "prob", 0.0) or 0.0)
        except (TypeError, ValueError):
            prob = 0.0
        score = prob - (demote if name in _LOW_VALUE else 0.0)
        ranked.append((name, score))
    ranked.sort(key=lambda t: t[1], reverse=True)
    out: List[str] = []
    for name, _ in ranked:
        if name not in out:
            out.append(name)
        if len(out) >= k:
            break
    return out

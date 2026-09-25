"""Artifact + task-card policy (owner bound change, 2026-09-25).

Two lines decide the reply surface, and the owner moved BOTH on 2026-09-25:

  * A TASK CARD is for genuinely long, multi-tool work — **three or more steps
    that call tools**. Below that bound the work still runs through DER, the
    tools still fire and a real artifact still renders; only the card is
    skipped. "there shouldnt be a task card for the agent to create three bullet
    points ... only appear for 3 more steps with tools".

  * An ARTIFACT (prism card) is for a markdown document or a report. Notes and
    lists are conversation and belong in the reply bubble. "artifacts are really
    only for mds and reports, notes and lists dont need to be an artifact thats
    not a lot of content".

Everything here is pure and dependency-free, so the kernel, the WS bridge and
the tests share ONE definition of each rule (REQ-22 / REQ-23). The only state is
the bounded, turn-scoped card gate at the bottom.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Iterable, Optional

# Owner bound: three or more TOOL steps earn a card.
MIN_TOOL_STEPS_FOR_CARD = 3

# Steps that are not "work" for this rule. A plan is allowed to carry speak
# steps (they voice the answer) without turning the turn into a project.
_NON_WORK_TOOLS = frozenset({"", "speak", "speak_tool", "tts", "no_tool", "none"})

# An artifact ask asks for a KEEPABLE DOCUMENT. The nouns that make one.
_DOC_NOUNS = (
    "report", "document", "docs", "doc", "markdown", "readme", "guide",
    "spec", "specification", "whitepaper", "write-up", "writeup", "briefing",
    "manual", "handbook", "article", "essay",
)
# ...and the nouns that make the ask NOT one, even next to a doc noun
# ("write a markdown note" is a note, not a document).
_SHORT_NOUNS = (
    "note", "notes", "list", "bullets", "bullet", "checklist", "summary",
    "recap", "memo", "reminder", "snippet", "one-liner",
)
_BUILD_VERBS = (
    "write", "create", "make", "draft", "generate", "produce", "compose",
    "prepare", "build", "author", "put together", "whip up",
)


def is_artifact_ask(text: str) -> bool:
    """True when the ask is for a markdown document or a report.

    Narrow on purpose (owner bound): "create a file with three bullets about
    sleep" is not an artifact ask, so it earns no card even when the agent uses
    write_file + read_file to do it.
    """
    t = (text or "").lower()
    if not t:
        return False
    if not any(v in t for v in _BUILD_VERBS):
        return False
    if any(n in t for n in _SHORT_NOUNS):
        return False
    return any(n in t for n in _DOC_NOUNS)


def _step_tool(step: Any) -> str:
    """The tool name of a plan step (objects and dicts both occur)."""
    if isinstance(step, dict):
        tool = step.get("tool") or step.get("tool_name") or ""
    else:
        tool = getattr(step, "tool", None) or ""
    return str(tool).strip().lower()


def tool_step_count(steps: Iterable[Any]) -> int:
    """How many of the plan's steps call a real tool."""
    return sum(1 for s in steps or [] if _step_tool(s) not in _NON_WORK_TOOLS)


def card_warranted(steps: Iterable[Any], task_text: str = "") -> bool:
    """THE decision: does this turn earn a task card?

    Long, multi-tool work does. An artifact ask never does, however many steps
    it takes, because the artifact IS the visible result (owner bound).
    """
    if is_artifact_ask(task_text):
        return False
    return tool_step_count(steps) >= MIN_TOOL_STEPS_FOR_CARD


def is_artifact_document(content: str) -> bool:
    """True when a body reads as a document worth keeping (markdown/report).

    A structural test, not a length heuristic: a single-'#' heading, a markdown
    table with at least two columns, or a fenced block. A plain note or a bullet
    list returns False — that is exactly the owner's line, and it is the same
    test the calibration log uses (REQ-14 AC3), so the signal and the behaviour
    cannot drift apart.
    """
    text = content or ""
    if not text.strip():
        return False
    if "```" in text:
        return True
    for line in text.splitlines():
        s = line.strip()
        # One '#' + whitespace = an H1, the markdown heading of a document.
        if s.startswith("#") and not s.startswith("##"):
            rest = s[1:]
            if rest[:1].isspace() and rest.strip():
                return True
        # A table row with two or more cells = tabular content.
        if s.startswith("|") and s.count("|") >= 3:
            return True
    return False


# ── turn-scoped card gate ───────────────────────────────────────────────────
# Bounded LRU of turn ids that must not produce a card. The kernel records the
# decision when it knows the plan; the WS bridge consults it while forwarding
# card-lifecycle events, so a short turn reaches the UI as a plain exchange even
# though DER ran the same way it always does.
_CARD_SUPPRESSED: "OrderedDict[str, None]" = OrderedDict()
_MAX_SUPPRESSED_TURNS = 64
_GATE_LOCK = threading.Lock()


def suppress_card_for_turn(turn_id: Optional[str]) -> None:
    """Record that this turn runs without a task card (bounded, thread-safe)."""
    if not turn_id:
        return
    with _GATE_LOCK:
        _CARD_SUPPRESSED[turn_id] = None
        _CARD_SUPPRESSED.move_to_end(turn_id)
        while len(_CARD_SUPPRESSED) > _MAX_SUPPRESSED_TURNS:
            _CARD_SUPPRESSED.popitem(last=False)


def card_suppressed(turn_id: Optional[str]) -> bool:
    """True when this turn must not surface card-lifecycle events."""
    if not turn_id:
        return False
    with _GATE_LOCK:
        return turn_id in _CARD_SUPPRESSED


def clear_card_gate_for_testing() -> None:
    with _GATE_LOCK:
        _CARD_SUPPRESSED.clear()

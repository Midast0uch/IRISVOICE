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

import json
import threading
from collections import OrderedDict
from typing import Any, Iterable, Optional

# Owner bound: a card needs MORE THAN three tool steps. The owner's words,
# verbatim, on 2026-09-25: "task cards should only appear for 3 more steps with
# tools ... its genuinely long multi tool work" and then, tightening it,
# "not have task cards pop up for things that are not more than 3 steps".
# Four or more tool steps, therefore — three or fewer is a conversation.
MIN_TOOL_STEPS_FOR_CARD = 4

# Card ids are minted as "card_<turn_id>", which is what lets a frame carrying
# only a card_id still be traced back to its turn (see card_event_turn_id).
_CARD_ID_PREFIX = "card_"

# Steps that are EXPLICITLY not work. A plan is allowed to carry speak steps
# (they voice the answer) without turning the turn into a project.
#
# An EMPTY/unknown tool field is NOT in this set, on purpose. Live 2026-09-25:
# a write+read plan reached the card decision with every tool field empty
# ("tool_steps=0") and then dispatched write_file and read_file seconds later —
# the planner resolves tools at execution time. Counting unknown as non-work
# would have removed the card from every long turn.
_NON_WORK_TOOLS = frozenset({"speak", "speak_tool", "tts", "no_tool", "none"})

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


def card_title_from_content(content: Optional[str]) -> str:
    """The prism card's title label (REQ-22), derived from a body preview.

    Mirrors the LIVE rule exactly (chat-view.tsx: first markdown heading, else
    ``Document``) so a card reads the same before and after a reload. Owner
    report 2026-09-25: "prism cards are still missing title labels on
    rehydrate" — the live path derived the title from the body, the hydration
    payload carries no body (CT-DOC-1), so the label simply vanished.
    """
    for line in (content or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        rest = stripped[1:]
        # One '#' + whitespace, matching the live regex ^\s*#\s+(.+)$.
        if not rest[:1].isspace():
            continue
        title = rest.strip()
        if title:
            return title
    return "Document"


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


def is_tool_result_envelope(content: str) -> bool:
    """True when ``content`` is a bare tool-RESULT envelope, not an artifact.

    The shape every tool returns: a single JSON object with a ``success`` key
    ({'success': true, 'message': 'Written to X'}). Such a body is a receipt,
    never an artifact, so it must not become a prism card — live 2026-09-25 the
    model passed tool results to render_document once per step, so every write
    and read minted a card whose body was the receipt ("prism cards are
    rendering with just json output").
    """
    if not isinstance(content, str):
        return False
    text = content.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return False
    try:
        parsed = json.loads(text)
    except Exception:
        return False
    return isinstance(parsed, dict) and "success" in parsed


def card_event_turn_id(payload: Any) -> Optional[str]:
    """The turn a card-lifecycle frame belongs to, however the emit site named it.

    LIVE 2026-09-25: only ``task:start``/``task:done`` carry ``turn_id``, so a
    ``task:progress`` frame for a card-free turn slipped past the gate and the
    frontend rebuilt the card from its ``card_id``. Every way an emit site
    identifies the turn is accepted here: the envelope's turn_id, the payload's
    turn_id, the task_id (the turn id under which the card was minted), and the
    card_id (``card_<turn_id>``).
    """
    if payload is None:
        return None
    data = getattr(payload, "data", None)
    if not isinstance(data, dict):
        data = {}
    candidates = (
        getattr(payload, "turn_id", None),
        data.get("turn_id"),
        data.get("task_id"),
        data.get("card_id"),
    )
    for cand in candidates:
        if not cand:
            continue
        text = str(cand)
        if text.startswith(_CARD_ID_PREFIX):
            text = text[len(_CARD_ID_PREFIX):]
        if text:
            return text
    return None


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
        _CONVERSATION_CARD_FREE.clear()


# Turns are the precise scope, but a few card frames name only their
# conversation: live 2026-09-25 the "Editing tts_check5.md" progress frames carry
# just {"conversation_id": "conv-151"}. Those set the frontend's phase/status
# ("SYNTHESIZING ANSWER") while the matching clear signal (task:done) is withheld
# for a card-free turn — so the status stayed lit after the answer arrived. The
# conversation is therefore gated too, and cleared the moment a turn in that
# conversation EARNS a card.
_CONVERSATION_CARD_FREE: "OrderedDict[str, None]" = OrderedDict()
_MAX_CARD_FREE_CONVERSATIONS = 32


def suppress_card_for_conversation(
    conversation_id: Optional[str], turn_id: Optional[str] = None
) -> None:
    """Mark a conversation as currently running a card-free turn (bounded)."""
    suppress_card_for_turn(turn_id)
    if not conversation_id:
        return
    with _GATE_LOCK:
        _CONVERSATION_CARD_FREE[conversation_id] = None
        _CONVERSATION_CARD_FREE.move_to_end(conversation_id)
        while len(_CONVERSATION_CARD_FREE) > _MAX_CARD_FREE_CONVERSATIONS:
            _CONVERSATION_CARD_FREE.popitem(last=False)


def clear_card_free_conversation(conversation_id: Optional[str]) -> None:
    """A turn in this conversation earned a card — stop gating the conversation."""
    if not conversation_id:
        return
    with _GATE_LOCK:
        _CONVERSATION_CARD_FREE.pop(conversation_id, None)


def card_suppressed_for_conversation(conversation_id: Optional[str]) -> bool:
    """True when this conversation is currently running a card-free turn."""
    if not conversation_id:
        return False
    with _GATE_LOCK:
        return conversation_id in _CONVERSATION_CARD_FREE

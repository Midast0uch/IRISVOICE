"""Artifact + task-card policy (owner bound change, 2026-09-25).

Two lines decide the reply surface, and the owner moved BOTH on 2026-09-25:

  * A TASK CARD is for genuinely long, multi-tool work — **three or more steps
    that call tools**. Below that bound the work still runs through DER, the
    tools still fire and a real artifact still renders; only the card is
    skipped. "there shouldnt be a task card for the agent to create three bullet
    points ... only appear for 3 more steps with tools".

  * An ARTIFACT (prism card) appears for ONE reason: the model called
    ``create_artifact`` (reply-surface audit, Phase A). The earlier rules that
    inferred a card from the body - a heading test, a "substantial markdown"
    test, a keyword ask that minted a card after the fact - are gone: a reply
    in plain text is shown in full and never becomes a card. What stays here is
    the vocabulary of the one trigger (kinds, formats, titles).

Everything here is pure and dependency-free, so the kernel, the WS bridge and
the tests share ONE definition of each rule (REQ-22 / REQ-23). The only state is
the bounded, turn-scoped card gate at the bottom.
"""
from __future__ import annotations

import json
import re
import threading
from collections import OrderedDict
from typing import Any, Iterable, Optional

# Owner bound, final reading (2026-09-25). Earlier the same day: "task cards only
# appear for 3 more steps with tools" and "not have task cards pop up for things
# that are not more than 3 steps". Asked to choose between counting plan steps and
# counting tool calls, the owner answered: "keep it >4 steps" — so the unit stays
# PLAN STEPS and the threshold is MORE THAN FOUR: five or more tool steps.
# A coarse plan (2 steps holding 6 tool calls) therefore gets no card, by choice.
MIN_TOOL_STEPS_FOR_CARD = 5

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
    write_file + read_file to do it. Only the TASK-card gate reads this now
    (``card_warranted``): the artifact is the visible result, so no task card
    is drawn beside it. It no longer mints an artifact.
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


_NARRATION_MARKERS = (
    "need to call", "needs to call", "let's run", "lets run", "let's call",
    "i'll call", "i will call", "i will now", "next step",
    "the tool only returned", "we haven't", "i haven't", "i need to ",
    "we need to ", "let me ", "i should ", "let's use", "lets use", "let us ",
)


def looks_like_internal_narration(text: str) -> bool:
    """True when the text is the agent thinking out loud about its own next move.

    Live 2026-09-25, twice:
      * a failed three-file turn showed the user
        "We haven't performed the read yet. Need to call read_file for the three
        files.Let's run read_file." — that is a plan, not an answer;
      * a report card carried "The tool only returned a partial draft; it omitted
        full sections ..." — meta-commentary about its own tools.
    Neither is a user-facing message. The failure/success synthesis paths already
    reject tool-args JSON and stubs; this is the third shape.
    """
    t = (text or "").lower()
    if not t.strip():
        return False
    return any(marker in t for marker in _NARRATION_MARKERS)


def strip_leading_narration(text: str, *, max_lead_chars: int = 320) -> str:
    """Drop a leading narration paragraph when a real answer follows it.

    Conservative on purpose: the first paragraph must be short AND read as
    narration, and at least 40 characters must remain, so a genuine answer that
    merely mentions "let me explain" is left alone. Only the lead goes; the
    answer the user asked for is untouched.
    """
    t = (text or "").strip()
    if not t:
        return t
    parts = t.split("\n\n", 1)
    if len(parts) != 2:
        return t
    head, rest = parts[0].strip(), parts[1].strip()
    if (
        head
        and len(head) <= max_lead_chars
        and looks_like_internal_narration(head)
        and len(rest) >= 40
    ):
        return rest
    return t


# The [RESPONSE FORMAT] prompt block teaches the reply format with a literal
# "ANSWER:" label (agent_kernel.py). Models sometimes copy the label into the
# reply — recorded live 2026-10-06 (recorded_personal_ok.json): the streamed
# delta, the final text AND the spoken line all started with it.
_ANSWER_MARKER_RE = re.compile(
    r"^\s*[*_]{0,3}\s*answer\s*[*_]{0,3}\s*[:：][*_]{0,3}[ \t]*",
    re.IGNORECASE,
)


def strip_leading_answer_marker(text: str) -> str:
    """Drop ONE leading "ANSWER:" label the model copied from the prompt.

    Variants a markdown-rendering model produces: leading whitespace (the
    recorded reply started with a blank line), optional emphasis (*, **, _,
    __) around the word, any case, ASCII or full-width colon. Only the very
    start of the text, once; a marker mid-text is prose and stays.
    """
    return _ANSWER_MARKER_RE.sub("", text or "", count=1)


def card_title_from_content(content: Optional[str]) -> str:
    """The prism card's title label (REQ-22), derived from a body preview.

    Order: the first markdown heading (H1..H6), else the first substantive line,
    else ``Document``. Mirrors the LIVE rule (chat-view.tsx) so a card reads the
    same before and after a reload. Owner report 2026-09-25: "prism cards are
    still missing title labels on rehydrate" — the live path derived the title
    from the body, the hydration payload carries no body (CT-DOC-1), so the
    label vanished.

    Owner, later the same day: "All titles and labels should be unique to the
    artifact created". That is why the first substantive line is used when there
    is no heading: a card labelled "Document" says nothing about which artifact
    it is.
    """
    text = (content or "").strip()
    heading = _first_heading(text)
    if heading:
        return heading
    # No heading: the first substantive line names the artifact.
    for line in text.splitlines():
        stripped = line.strip().strip("*_`#> -").strip()
        if len(stripped) >= 3:
            return stripped[:60]
    return "Document"


def _first_heading(content: Optional[str]) -> str:
    """The first markdown heading (any level), or "" when there is none."""
    for line in (content or "").splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        rest = stripped.lstrip("#")
        if not rest[:1].isspace():
            continue
        title = rest.strip().strip("*_`")
        if title:
            return title[:60]
    return ""


# ── The one trigger: create_artifact (reply-surface audit, Phase A) ──────────
# Kinds the model may name. The wire format (RichDocument format) is derived
# from the kind, so the model never picks a render format by hand again.
ARTIFACT_KINDS = ("document", "code", "data", "diagram", "page", "image")

# The card title is a label, not a sentence. Longer titles are cut (and logged
# by the caller) instead of refused: a long title is a style slip, not a reason
# to lose the artifact.
ARTIFACT_TITLE_MAX = 60

# The old `show` payload names a render FORMAT; create_artifact names a KIND.
_KIND_FOR_FORMAT = {
    "markdown": "document", "text": "document", "": "document",
    "html": "page",
    "diagram": "diagram", "mermaid": "diagram", "svg": "diagram",
    "json": "data", "table": "data", "csv": "data",
    "image": "image",
}


def kind_for_show_format(fmt: Optional[str]) -> str:
    """The artifact kind for a `show` payload's format (unknown -> document)."""
    return _KIND_FOR_FORMAT.get(str(fmt or "").strip().lower(), "document")


def artifact_format_and_body(
    kind: str, content: str, language: Optional[str] = None
) -> "tuple[str, str]":
    """``(render format, stored body)`` for a create_artifact call.

    document -> markdown as given; code -> markdown holding ONE fenced block
    tagged with the language (a body that is already a single fence is kept, so
    it is not wrapped twice); data -> json when the language is json, else the
    text as given (CSV, a markdown table); diagram -> diagram; page -> html;
    image -> image. The fence is made longer than any backtick run inside the
    code, so code that itself contains a fence cannot close the block early.
    """
    lang = (language or "").strip().lower()
    if kind == "code":
        body = content.strip("\n")
        if body.lstrip().startswith("```") and body.rstrip().endswith("```"):
            return "markdown", body
        fence = "```"
        while fence in body:
            fence += "`"
        return "markdown", f"{fence}{lang}\n{body}\n{fence}"
    if kind == "data":
        return ("json" if lang == "json" else "markdown"), content
    if kind == "diagram":
        return "diagram", content
    if kind == "page":
        return "html", content
    if kind == "image":
        return "image", content
    return "markdown", content


def first_sentence(text: Optional[str], limit: int = 140) -> str:
    """The first sentence of ``text`` on one line, at most ``limit`` chars."""
    flat = " ".join((text or "").split())
    if not flat:
        return ""
    for i, ch in enumerate(flat):
        if ch in ".!?" and (i + 1 == len(flat) or flat[i + 1] == " "):
            flat = flat[: i + 1]
            break
    return flat[:limit].rstrip()


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

"""The live view (CLM-1, specs/clm-memory) - Wave 1: parity only.

Plain picture: the desk. Every paper that reaches the desk is a Block with a
filing number (Ref). ``render()`` lays the papers out in the order they were
admitted and hands the provider the same message list the old builder made.
Nothing leaves the desk in this wave: no zones, no policy, no placeholders.

The view is derived and in memory: built from the record per turn or run,
never persisted. It never mutates what it is given (the lists, and so
``ConversationMemory.messages``, design Q4): it stores a copy of each list and
renders fresh dict copies.

Pure module: no I/O, no kernel import. A view is single-threaded by design (one view
per turn or run, never shared between conversations), so it holds no lock; the
module-level fallback counter is shared and has one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.agent.context_gauge import estimate_tokens

# Block kinds on the direct path. These are the names the Wave 0 instrument
# already uses (``clm_baseline.record_direct`` parts), so the baseline and the
# view speak the same words. The node path adds its kinds in T1.3.
SYSTEM_PROMPT = "system_prompt"
RECALL_EPISODIC = "recall_episodic"
RECALL_PROFILE = "recall_profile"
RECALL_CHUNKS = "recall_chunks"
HISTORY = "history"
CURRENT_USER = "current_user"

# Block kinds on the DER node path (T1.3), one per message the node loop
# (node_executor.run_node) creates. The step-goal message carries the earlier
# step results and the memory facts INSIDE its text, so they are not blocks of
# their own while the message stays byte-equal.
SYSTEM = "system"                              # the node's _SYSTEM
STEP_GOAL = "step_goal"                        # task, step, done-when, prior results, memory
ASSISTANT_TOOL_CALLS = "assistant_tool_calls"  # a model answer that calls tools
ASSISTANT_ANSWER = "assistant_answer"          # a model answer kept before a harness note
TOOL_RESULT = "tool_result"                    # a tool message (result, repeat or unchanged stub)
SCREENSHOT = "screenshot"                      # the marked page picture (user turn)
HARNESS_NOTE = "harness_note"                  # hint, hand-over, picture hint, closing stop
# Synthesis (kernel/der/report.py _synthesize_response) sends one user message.
SYNTHESIS_REQUEST = "synthesis_request"


@dataclass(frozen=True)
class Ref:
    """Address of a block in the record. ``ephemeral`` has no row (id is "")."""

    kind: str           # "chunk" | "chain" | "episode" | "thread" | "pin" | "landmark" | "ephemeral"
    id: str = ""
    thread_id: str = ""  # incidence key (recall REQ-10)


EPHEMERAL = Ref(kind="ephemeral")


@dataclass
class Block:
    block_id: str       # short, stable within the view: "b1" (what the model names)
    ref: Ref
    kind: str
    messages: List[Dict[str, Any]]  # provider-shaped; a tool call stays with its result
    tokens: int         # raw gauge count at admit (``estimate_tokens``, uncalibrated)
    ts: float = 0.0
    zone: str = ""      # unused until Wave 4; carried so the data model is final
    domain: str = ""
    open_items: Tuple[Any, ...] = ()
    protected: bool = False
    # Ordered refs of the rows a MERGED block was built from (e.g. the recalled
    # chunk ids inside one <context_memory> message). ``ref`` is the first of
    # them, or ephemeral. Refs live on blocks only, never in message dicts.
    refs: Tuple[Ref, ...] = ()
    # Why part or all of the block has no row address (empty when fully addressed).
    ref_reason: str = ""
    # Wave 2: the placeholder line while the block is set aside ("" = in view).
    # ``render()`` substitutes it for the content; ``messages`` never changes.
    aside: str = ""


class ContextView:
    """Blocks in admission order; ``render()`` returns the provider messages."""

    def __init__(self) -> None:
        self._blocks: List[Block] = []

    @property
    def blocks(self) -> Tuple[Block, ...]:
        return tuple(self._blocks)

    def admit(
        self,
        kind: str,
        messages: Sequence[Dict[str, Any]],
        *,
        ref: Optional[Ref] = None,
        ts: float = 0.0,
        zone: str = "",
        domain: str = "",
        open_items: Tuple[Any, ...] = (),
        protected: bool = False,
        refs: Tuple[Ref, ...] = (),
        ref_reason: str = "",
    ) -> Block:
        """Append one block, in the order the old builder appended its messages.

        An empty ``messages`` admits an empty block (it renders nothing), so a
        call site can admit every part unconditionally, in order.
        """
        held = [dict(m) for m in messages]
        block = Block(
            block_id=f"b{len(self._blocks) + 1}",
            ref=ref if ref is not None else (refs[0] if refs else EPHEMERAL),
            kind=kind,
            messages=held,
            tokens=estimate_tokens(held),
            ts=ts,
            zone=zone,
            domain=domain,
            open_items=open_items,
            protected=protected,
            refs=tuple(refs),
            ref_reason=ref_reason,
        )
        self._blocks.append(block)
        return block

    def render(self) -> List[Dict[str, Any]]:
        """The provider message list: blocks in order, fresh dict copies.

        The dicts are shallow copies: a caller that edits a rendered message
        does not touch the view or the record. Nested values (``tool_calls``)
        are shared, as they are in the old builder's list. A set-aside block
        renders its messages with the placeholder as the content; every other
        key (role, tool_call_id, name) stays, so the conversation keeps its
        shape and the list keeps its length.
        """
        return [
            dict(m) if not block.aside else {**m, "content": block.aside}
            for block in self._blocks
            for m in block.messages
        ]

    def admit_live(
        self, kind: str, message: Dict[str, Any], *, protected: bool = False
    ) -> Block:
        """Append one block that HOLDS the caller's message dict (no copy).

        For a loop that owns its list and edits a message in place after it
        was sent: the DER node turns an old screenshot into a one-line note
        (``node_executor._drop_old_screenshots``). A copy would keep the old
        picture and drift from the loop's list; holding the same dict keeps
        the two equal. ``render()`` still hands out fresh shallow copies.
        ``tokens`` is the count at admit; an in-place edit does not recount
        it (nothing in Wave 1 reads it).
        """
        block = Block(
            block_id=f"b{len(self._blocks) + 1}",
            ref=EPHEMERAL,
            kind=kind,
            messages=[message],
            tokens=estimate_tokens([message]),
            protected=protected,
        )
        self._blocks.append(block)
        return block

    # -- Wave 2 core (T2.2): units, set aside, restore -------------------------

    def units(self) -> List["Unit"]:
        """The tool-call units in view order: an assistant message with
        ``tool_calls`` plus the tool messages that answer its call ids.

        A unit is ONE thing for offload (Carried into Wave 2): its call and its
        results leave together or not at all. ``complete`` is True only when
        every call id has its tool message.
        """
        out: List[Unit] = []
        blocks = self._blocks
        i = 0
        while i < len(blocks):
            call = blocks[i]
            calls = _tool_calls_of(call)
            if not calls:
                i += 1
                continue
            ids = {str(tc.get("id") or (tc.get("function") or {}).get("name") or "")
                   for tc in calls if isinstance(tc, dict)}
            results: List[Block] = []
            j = i + 1
            while j < len(blocks) and _is_tool_block(blocks[j]):
                results.append(blocks[j])
                j += 1
            answered = {str(m.get("tool_call_id") or "") for b in results for m in b.messages}
            ref = call.ref if call.ref.kind != EPHEMERAL.kind else Ref(kind=HELD, id=call.block_id)
            out.append(Unit(call=call, results=tuple(results), ref=ref,
                            complete=bool(results) and ids <= answered))
            i = j
        return out

    def set_aside(self, unit: "Unit", placeholder: str) -> None:
        """Set one unit aside (see ``set_aside_batch``)."""
        self.set_aside_batch([(unit, placeholder)])

    def set_aside_batch(self, items: Sequence[Tuple["Unit", str]]) -> None:
        """Set several units aside as ONE edit (one batch per boundary).

        All or nothing: every item is checked first (the unit is this view's,
        complete, not already aside, and the placeholder parses back to the
        unit's ref); only then are the result blocks marked. The call message
        stays (an assistant ``tool_calls`` message without its tool messages
        is a 400 on OpenAI-shaped APIs); each result message keeps its role,
        ``tool_call_id`` and name and carries the placeholder as its content.
        Nothing the loop holds is mutated: ``render()`` substitutes.
        """
        held = {id(b) for b in self._blocks}
        for unit, placeholder in items:
            if id(unit.call) not in held or any(id(b) not in held for b in unit.results):
                raise ValueError(f"unit {unit.ref} is not in this view")
            if not unit.complete:
                raise ValueError(f"unit {unit.ref} is incomplete")
            if any(b.aside for b in unit.results):
                raise ValueError(f"unit {unit.ref} is already set aside")
            named = parse_placeholder(placeholder)
            if named is None or _addr(named) != _addr(unit.ref):
                raise ValueError(f"placeholder does not name {unit.ref}: {placeholder!r}")
        for unit, placeholder in items:
            for b in unit.results:
                b.aside = _result_placeholder(b, placeholder)

    def restore(self, ref: Ref, blocks: Optional[Sequence["Block"]] = None) -> bool:
        """Bring a set-aside unit back, byte-for-byte (CLM-2 AC3).

        The view still holds the unit's original messages, so a ``held`` ref
        needs nothing else. ``blocks`` - the unit as read back from the record
        - is optional; when given, every message must equal the held one, or
        the restore is refused (False): a record that differs never replaces
        what the view held. Returns True when the unit is back in view.
        """
        for unit in self.units():
            if _addr(unit.ref) != _addr(ref) or not any(b.aside for b in unit.results):
                continue
            if blocks is not None:
                got = [m for b in blocks for m in b.messages]
                want = [m for b in (unit.call, *unit.results) for m in b.messages]
                if _canon(got) != _canon(want):
                    return False
            for b in unit.results:
                b.aside = ""
            return True
        return False


# -- view_fallback (design "Error Handling") -----------------------------------
# A call site that cannot build or render the view falls back to the old list
# and counts it here. Its expected value is 0; the CLM baseline row carries it
# so the live gate can assert that.
_fallback_lock = threading.Lock()
_fallback = {"view_fallback": 0}


def count_view_fallback() -> int:
    with _fallback_lock:
        _fallback["view_fallback"] += 1
        return _fallback["view_fallback"]


def view_fallback_count() -> int:
    with _fallback_lock:
        return _fallback["view_fallback"]


# == Wave 2 core: placeholder (T2.1), break-even (T2.1), offload gate (T2.2) ==
# Pure: no I/O. Nothing here is wired yet; the node boundary calls it in T2.3.

# A unit whose bytes the view itself still holds (the DER node: the loop's own
# message dicts, admit_live). Its id is the call block's id. A node view never
# outlives its node, so a held unit is readable for the whole life of every
# placeholder that names it.
HELD = "held"


@dataclass(frozen=True)
class Unit:
    """One offloadable thing: a tool call and the results that answer it."""

    call: Block
    results: Tuple[Block, ...]
    ref: Ref
    complete: bool

    @property
    def blocks(self) -> Tuple[Block, ...]:
        return (self.call, *self.results)

    @property
    def protected(self) -> bool:
        return any(b.protected for b in self.blocks)

    @property
    def open_items(self) -> Tuple[Any, ...]:
        return tuple(i for b in self.blocks for i in b.open_items)

    def tool_names(self) -> List[str]:
        return [str((tc.get("function") or {}).get("name") or "")
                for tc in _tool_calls_of(self.call) if isinstance(tc, dict)]


def _tool_calls_of(block: Block) -> list:
    if len(block.messages) != 1:
        return []
    m = block.messages[0]
    calls = m.get("tool_calls") if m.get("role") == "assistant" else None
    return calls if isinstance(calls, list) and calls else []


def _is_tool_block(block: Block) -> bool:
    return bool(block.messages) and all(m.get("role") == "tool" for m in block.messages)


def _addr(ref: Ref) -> Tuple[str, str]:
    """The placeholder address of a ref: kind and id (``thread_id`` is an
    incidence key, not part of the address - design "Placeholder syntax")."""
    return (ref.kind, ref.id)


def _canon(messages: Sequence[Dict[str, Any]]) -> str:
    import json

    return json.dumps(list(messages), sort_keys=True, ensure_ascii=False, default=str)


def recount(block: Block) -> int:
    """The block's tokens NOW. ``Block.tokens`` is the count at admit and goes
    stale after an in-place edit (a replaced screenshot keeps the image
    count); every offload decision reads this instead."""
    return estimate_tokens(block.messages)


# -- the placeholder (CLM-2 AC1, AC5) ------------------------------------------
# `[[SET ASIDE {ref.kind}:{ref.id} | {time_frame} | {domain} | {reason}]]`
# (design "Placeholder syntax"). One line. The reason and the domain are cut so
# the whole line stays within PLACEHOLDER_MAX_CHARS (~70 tokens by
# estimate_tokens); a placeholder is therefore never larger than a unit
# that passes break-even.
PLACEHOLDER_MAX_CHARS = 240
_DOMAIN_MAX = 40
_PH_RE = None


def _field(text: Any, limit: int) -> str:
    s = " ".join(str(text or "").split())
    s = s.replace("|", "/").replace("[[", "[ [").replace("]]", "] ]")
    return s[:limit]


def _time_frame(ts: float) -> str:
    if not ts or ts <= 0:
        return "this run"
    import time

    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts))


def render_placeholder(block: Block, reason: str, *, ref: Optional[Ref] = None,
                       domain: str = "") -> str:
    """The placeholder line for ``block`` (or for ``ref`` when given - a unit's
    ref is its call block's, see ``ContextView.units``)."""
    ref = ref if ref is not None else block.ref
    if not ref.kind or ref.kind == EPHEMERAL.kind:
        raise ValueError("an ephemeral block has no address; it cannot be set aside")
    if not ref.kind or any(c not in "abcdefghijklmnopqrstuvwxyz_" for c in ref.kind):
        raise ValueError(f"ref kind {ref.kind!r} is not a placeholder token")
    if not ref.id or any(c.isspace() or c in "|]" for c in ref.id):
        raise ValueError(f"ref id {ref.id!r} cannot be written in a placeholder")
    head = f"[[SET ASIDE {ref.kind}:{ref.id} | {_time_frame(block.ts)} | "
    dom = _field(domain or block.domain or block.kind, _DOMAIN_MAX)
    room = PLACEHOLDER_MAX_CHARS - len(head) - len(dom) - len(" | ]]")
    if room < 1:
        raise ValueError(f"ref {ref} leaves no room for a reason")
    return f"{head}{dom} | {_field(reason, room) or 'set aside'}]]"


def _result_placeholder(block: Block, unit_placeholder: str) -> str:
    """The line a set-aside RESULT block shows. A result with its own durable
    address (a node tool result in the chat record: ``tool_result:<id>``)
    names THAT address, so the model can expand exactly this result after the
    node is gone; any other result shows the unit's placeholder (``held``)."""
    if block.ref.kind in ("", EPHEMERAL.kind, HELD):
        return unit_placeholder
    parts = unit_placeholder[2:-2].split(" | ")
    domain = parts[2] if len(parts) == 4 else ""
    reason = parts[3] if len(parts) == 4 else "set aside"
    return render_placeholder(block, reason, ref=block.ref, domain=domain)


def parse_placeholder(text: str) -> Optional[Ref]:
    """The Ref a placeholder names, or None when ``text`` is not one."""
    global _PH_RE
    if _PH_RE is None:
        import re

        _PH_RE = re.compile(r"^\[\[SET ASIDE ([a-z_]+):([^\s|\]]+) \| [^|]* \| [^|]* \| [^|]*\]\]$")
    m = _PH_RE.match(text or "")
    return Ref(kind=m.group(1), id=m.group(2)) if m else None


# -- break-even (T2.1, CLM-2 AC5, edge case "below break-even") -----------------
# MIN_SAVING = 256 gauge tokens, from the Wave 0 window data (logs/clm_baseline
# .jsonl, 885 rows of 2026-11-12, the rows behind evals/results/clm-baseline-
# 2026-11-12.json; tokens = the router rule, the unit the gauge uses):
#   tool messages in windows: n = 730; p10 32, p25 35, p50 42, p75 73, p90 2126,
#   p95 2298, max 2647 - two modes: hints/short outputs, and real results.
#   threshold  share of tool messages >= it  share of tool-result tokens in them
#      64            27.8 %                        90.8 %
#     128            16.4 %                        87.7 %
#     256            14.8 %                        86.7 %
#     512            11.9 %                        83.7 %
# 256 is the knee: below it each step adds edits (every edit re-processes the
# prompt after it, CLM-10) for about 1 % more tokens; above it real results
# start to be missed. A placeholder's content costs at most 69 tokens
# (estimate_tokens: 74 for a 240-char message, 5 for an empty one), so a unit
# that passes saves at least 3.7x (256 / 69) what
# its placeholder costs - AC5 ("a placeholder larger than the block") cannot pass.
MIN_SAVING = 256


def unit_saving(unit: Unit, placeholder: str, extra_tokens: int = 0) -> int:
    """Tokens the unit gives back if set aside: its result messages NOW minus the
    same messages carrying the placeholder, minus what the caller adds for it
    (digest, carried open items)."""
    now = sum(recount(b) for b in unit.results)
    after = sum(estimate_tokens([{**m, "content": placeholder} for m in b.messages])
                for b in unit.results)
    return now - after - int(extra_tokens)


# -- the offload gate (T2.2, CLM-2 AC2, CT-2) ----------------------------------
REFUSE_NO_REF = "no_ref"
REFUSE_UNREADABLE = "unreadable"
REFUSE_INCOMPLETE = "incomplete_unit"
REFUSE_PROTECTED = "protected"
REFUSE_NEWEST = "newest_unit"
REFUSE_OPEN_ITEMS = "open_items_not_carried"
REFUSE_BREAK_EVEN = "below_break_even"
REFUSE_ALREADY_ASIDE = "already_aside"
REFUSE_NOT_IN_VIEW = "not_in_view"

_refusal_lock = threading.Lock()
_refusals: Dict[str, int] = {}


def _refuse(reason: str) -> None:
    with _refusal_lock:
        _refusals[reason] = _refusals.get(reason, 0) + 1


def offload_refusal_counts() -> Dict[str, int]:
    """Refusals by reason since process start (HIDDEN FAILURES rule 4)."""
    with _refusal_lock:
        return dict(_refusals)


@dataclass(frozen=True)
class OffloadDecision:
    allowed: bool
    reason: str          # "" when allowed, else one REFUSE_* value
    saving: int = 0
    placeholder: str = ""


def offload_decision(
    view: ContextView,
    unit: Unit,
    resolver: Any,
    *,
    reason: str,
    carried: Sequence[Any] = (),
    extra_tokens: int = 0,
    domain: str = "",
) -> OffloadDecision:
    """May ``unit`` leave the view now? Pure: the record is reached only through
    ``resolver(ref) -> bool`` (True = readable by its ref NOW; the call site's
    resolver owns any bounded wait on a queued write - on the bound it answers
    False and the unit stays). Checks, in order: in view, not already aside,
    complete, not protected, not the newest unit, has an address, readable,
    every open item carried, break-even. Each refusal is counted.
    """
    def no(why: str, saving: int = 0, ph: str = "") -> OffloadDecision:
        _refuse(why)
        return OffloadDecision(False, why, saving, ph)

    units = view.units()
    mine = next((u for u in units if u.call is unit.call), None)
    if mine is None:
        return no(REFUSE_NOT_IN_VIEW)
    unit = mine
    if any(b.aside for b in unit.results):
        return no(REFUSE_ALREADY_ASIDE)
    if not unit.complete:
        return no(REFUSE_INCOMPLETE)
    if unit.protected:
        return no(REFUSE_PROTECTED)
    if unit.call is units[-1].call:
        return no(REFUSE_NEWEST)
    if not unit.ref.kind or unit.ref.kind == EPHEMERAL.kind:
        return no(REFUSE_NO_REF)
    try:
        readable = bool(resolver(unit.ref))
    except Exception:  # noqa: BLE001 - an unanswered read is an unreadable ref
        readable = False
    if not readable:
        return no(REFUSE_UNREADABLE)
    have = list(carried)
    if any(item not in have for item in unit.open_items):
        return no(REFUSE_OPEN_ITEMS)
    ph = render_placeholder(unit.call, reason, ref=unit.ref,
                            domain=domain or " ".join(unit.tool_names()))
    saving = unit_saving(unit, ph, extra_tokens)
    if saving < MIN_SAVING:
        return no(REFUSE_BREAK_EVEN, saving, ph)
    return OffloadDecision(True, "", saving, ph)


def held_resolver(view: ContextView) -> Any:
    """The resolver for ``held`` refs: readable while this view holds the unit."""
    def _readable(ref: Ref) -> bool:
        return ref.kind == HELD and any(_addr(u.ref) == _addr(ref) for u in view.units())
    return _readable

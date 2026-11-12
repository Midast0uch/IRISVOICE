"""CT-2 (specs/clm-memory design, Testing Strategy; CLM-2 AC1-AC3, AC5) - the
offload core, pure and unwired (Wave 2, T2.1 + T2.2).

- The gate refuses: an unreadable ref, an incomplete unit, a protected unit,
  the newest unit, an uncarried open item, a unit below break-even - each with a
  named reason, each counted. It allows the rest.
- A tool call and its results are ONE unit; a set-aside never separates them.
- The list rendered after a set-aside is a valid conversation for the
  OpenAI-shaped wire and the Ollama converter (no orphan tool_calls, no orphan
  tool messages, same roles in the same order), and has the same length.
- The placeholder round-trips to its ref; restore brings the exact bytes back.
- Decisions read the tokens NOW (``recount``), not the stale admit count.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from backend.agent import context_view as cv
from backend.agent.context_view import (
    ASSISTANT_TOOL_CALLS,
    HARNESS_NOTE,
    HELD,
    MIN_SAVING,
    PLACEHOLDER_MAX_CHARS,
    SCREENSHOT,
    STEP_GOAL,
    SYSTEM,
    TOOL_RESULT,
    Block,
    ContextView,
    Ref,
    held_resolver,
    offload_decision,
    offload_refusal_counts,
    parse_placeholder,
    recount,
    render_placeholder,
)
from backend.agent.context_gauge import estimate_tokens
from backend.agent.inference.transport import _to_ollama_messages

BIG = "line of a tool result\n" * 400      # ~2.5k gauge tokens: over break-even
SMALL = "ok"                                # far below break-even


def _call(i: int, *names: str) -> Dict[str, Any]:
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"c{i}_{k}", "type": "function",
         "function": {"name": n, "arguments": json.dumps({"path": f"f{i}.py"})}}
        for k, n in enumerate(names)]}


def _result(i: int, k: int, name: str, content: str) -> Dict[str, Any]:
    return {"role": "tool", "tool_call_id": f"c{i}_{k}", "name": name, "content": content}


def _node_view(*units) -> tuple:
    """A node-shaped view built the way run_node builds it (admit_live over the
    loop's own dicts). ``units`` = [(names, [contents])...]."""
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": "You are doing ONE step."},
        {"role": "user", "content": "STEP: fix calc.py"},
    ]
    view = ContextView()
    view.admit_live(SYSTEM, messages[0], protected=True)
    view.admit_live(STEP_GOAL, messages[1], protected=True)
    for i, (names, contents) in enumerate(units, 1):
        call = _call(i, *names)
        messages.append(call)
        view.admit_live(ASSISTANT_TOOL_CALLS, call)
        for k, (name, content) in enumerate(zip(names, contents)):
            res = _result(i, k, name, content)
            messages.append(res)
            view.admit_live(TOOL_RESULT, res)
    return view, messages


def _valid_openai_shape(messages: List[Dict[str, Any]]) -> None:
    """The wire rule the OpenAI-shaped providers enforce (a 400 otherwise): every
    assistant tool_calls message is followed by tool messages answering ALL its
    ids, and a tool message answers an id of the nearest preceding call."""
    open_ids: set = set()
    for m in messages:
        role = m.get("role")
        if role == "tool":
            assert m.get("tool_call_id") in open_ids, f"orphan tool message {m.get('tool_call_id')}"
            open_ids.discard(m["tool_call_id"])
            continue
        assert not open_ids, f"tool_calls left unanswered: {sorted(open_ids)}"
        if role == "assistant" and m.get("tool_calls"):
            open_ids = {tc["id"] for tc in m["tool_calls"]}
    assert not open_ids, f"tool_calls left unanswered at the end: {sorted(open_ids)}"


# -- the placeholder ----------------------------------------------------------

def test_placeholder_round_trips_to_its_ref_and_stays_bounded():
    block = Block(block_id="b3", ref=Ref(kind="chunk", id="9f1c2a7e-0000-4000-8000-1234567890ab"),
                  kind=TOOL_RESULT, messages=[{"role": "tool", "content": "x"}], tokens=1,
                  ts=1_794_464_722.0, domain="web | search ]] [[x")
    text = render_placeholder(block, "the release date\nwas found here | " + "r" * 500)
    assert text.startswith("[[SET ASIDE chunk:9f1c2a7e-0000-4000-8000-1234567890ab | 2026-11-12 ")
    assert text.endswith("]]") and "\n" not in text
    assert len(text) <= PLACEHOLDER_MAX_CHARS
    assert parse_placeholder(text) == Ref(kind="chunk", id="9f1c2a7e-0000-4000-8000-1234567890ab")
    held = render_placeholder(block, "short", ref=Ref(kind=HELD, id="b7"))
    assert parse_placeholder(held) == Ref(kind=HELD, id="b7")


def test_placeholder_refuses_an_address_it_cannot_write():
    block = Block(block_id="b1", ref=cv.EPHEMERAL, kind=SYSTEM, messages=[], tokens=0)
    with pytest.raises(ValueError):
        render_placeholder(block, "no address")
    with pytest.raises(ValueError):
        render_placeholder(block, "bad id", ref=Ref(kind="chunk", id="a b"))
    assert parse_placeholder("plain tool text") is None
    assert parse_placeholder("[[SET ASIDE chunk:x | t | d ]]") is None


# -- units --------------------------------------------------------------------

def test_a_call_and_its_results_are_one_unit():
    view, _ = _node_view((("read_file", "grep_files"), [BIG, BIG]), (("run_command",), [SMALL]))
    units = view.units()
    assert [len(u.results) for u in units] == [2, 1]
    assert all(u.complete for u in units)
    assert units[0].ref == Ref(kind=HELD, id=units[0].call.block_id)


def test_a_unit_missing_a_result_is_incomplete_and_refused():
    view, _ = _node_view((("read_file",), [BIG]), (("run_command",), [SMALL]))
    call = _call(9, "read_file", "edit_file")        # two calls, one answer
    view.admit_live(ASSISTANT_TOOL_CALLS, call)
    view.admit_live(TOOL_RESULT, _result(9, 0, "read_file", BIG))
    view.admit_live(HARNESS_NOTE, {"role": "user", "content": "note"})
    view.admit_live(ASSISTANT_TOOL_CALLS, _call(10, "read_file"))
    view.admit_live(TOOL_RESULT, _result(10, 0, "read_file", SMALL))
    unit = [u for u in view.units() if u.call.messages[0] is call][0]
    assert not unit.complete
    d = offload_decision(view, unit, held_resolver(view), reason="r")
    assert (d.allowed, d.reason) == (False, cv.REFUSE_INCOMPLETE)


# -- the gate (CT-2) ----------------------------------------------------------

def _counted(reason: str, fn) -> cv.OffloadDecision:
    before = offload_refusal_counts().get(reason, 0)
    d = fn()
    assert d.allowed is False and d.reason == reason
    assert offload_refusal_counts().get(reason, 0) == before + 1, "every refusal is counted"
    return d


def test_gate_allows_a_complete_old_readable_unit_over_break_even():
    view, _ = _node_view((("read_file",), [BIG]), (("run_command",), [SMALL]))
    d = offload_decision(view, view.units()[0], held_resolver(view), reason="read calc.py")
    assert d.allowed and d.reason == "" and d.saving >= MIN_SAVING
    assert parse_placeholder(d.placeholder) == view.units()[0].ref


def test_gate_refuses_an_unreadable_ref():
    view, _ = _node_view((("read_file",), [BIG]), (("run_command",), [SMALL]))
    _counted(cv.REFUSE_UNREADABLE,
             lambda: offload_decision(view, view.units()[0], lambda ref: False, reason="r"))
    # a resolver that raises is an unanswered read: the unit stays
    def _boom(ref):
        raise TimeoutError("queued write not landed within the bound")
    _counted(cv.REFUSE_UNREADABLE,
             lambda: offload_decision(view, view.units()[0], _boom, reason="r"))


def test_gate_refuses_the_newest_unit():
    view, _ = _node_view((("read_file",), [BIG]), (("read_file",), [BIG]))
    _counted(cv.REFUSE_NEWEST,
             lambda: offload_decision(view, view.units()[-1], held_resolver(view), reason="r"))


def test_gate_refuses_a_protected_unit():
    view, _ = _node_view((("read_file",), [BIG]), (("run_command",), [SMALL]))
    view.units()[0].call.protected = True
    _counted(cv.REFUSE_PROTECTED,
             lambda: offload_decision(view, view.units()[0], held_resolver(view), reason="r"))


def test_gate_refuses_an_uncarried_open_item_and_allows_it_carried():
    view, _ = _node_view((("run_command",), [BIG]), (("read_file",), [SMALL]))
    unit = view.units()[0]
    unit.results[0].open_items = ("pytest: 2 failed in test_calc.py",)
    _counted(cv.REFUSE_OPEN_ITEMS,
             lambda: offload_decision(view, unit, held_resolver(view), reason="r"))
    d = offload_decision(view, view.units()[0], held_resolver(view), reason="r",
                         carried=["pytest: 2 failed in test_calc.py"])
    assert d.allowed


def test_gate_refuses_below_break_even():
    view, _ = _node_view((("read_file",), [SMALL]), (("run_command",), [SMALL]))
    d = _counted(cv.REFUSE_BREAK_EVEN,
                 lambda: offload_decision(view, view.units()[0], held_resolver(view), reason="r"))
    assert d.saving < MIN_SAVING
    # the caller's own additions (digest, carried items) count against the saving
    view2, _ = _node_view((("read_file",), [BIG]), (("run_command",), [SMALL]))
    big_saving = offload_decision(view2, view2.units()[0], held_resolver(view2), reason="r").saving
    _counted(cv.REFUSE_BREAK_EVEN, lambda: offload_decision(
        view2, view2.units()[0], held_resolver(view2), reason="r",
        extra_tokens=big_saving - MIN_SAVING + 1))


def test_gate_refuses_an_ephemeral_ref_and_a_unit_from_another_view():
    view, _ = _node_view((("read_file",), [BIG]), (("run_command",), [SMALL]))
    other, _ = _node_view((("read_file",), [BIG]), (("run_command",), [SMALL]))
    _counted(cv.REFUSE_NOT_IN_VIEW,
             lambda: offload_decision(view, other.units()[0], held_resolver(view), reason="r"))


# -- set aside: valid conversation, same length, loop dicts untouched ----------

def test_set_aside_leaves_a_valid_conversation_of_the_same_length():
    view, messages = _node_view((("read_file", "grep_files"), [BIG, BIG]),
                                (("run_command",), [SMALL]))
    view.admit_live(SCREENSHOT, {"role": "user", "content": [
        {"type": "text", "text": "shot"}, {"type": "image_url", "image_url": {"url": "data:x"}}]})
    messages.append(view.blocks[-1].messages[0])
    snapshot = json.dumps(messages, sort_keys=True)
    before = view.render()
    unit = view.units()[0]
    d = offload_decision(view, unit, held_resolver(view), reason="read and grep calc.py")
    assert d.allowed
    view.set_aside(unit, d.placeholder)
    after = view.render()
    assert len(after) == len(before) == len(messages), "the _outgoing() length guard still holds"
    assert [(m.get("role"), m.get("tool_call_id")) for m in after] == [
        (m.get("role"), m.get("tool_call_id")) for m in before]
    _valid_openai_shape(after)
    ollama = _to_ollama_messages(after)
    assert [m["role"] for m in ollama] == [m["role"] for m in after]
    assert [m["content"] for m in after if m.get("role") == "tool"][:2] == [d.placeholder] * 2
    assert json.dumps(messages, sort_keys=True) == snapshot, "the loop's dicts are never edited"
    assert estimate_tokens(after) <= estimate_tokens(before) - MIN_SAVING


def test_set_aside_batch_is_all_or_nothing():
    view, _ = _node_view((("read_file",), [BIG]), (("grep_files",), [BIG]),
                         (("run_command",), [SMALL]))
    u1, u2 = view.units()[0], view.units()[1]
    ok = offload_decision(view, u1, held_resolver(view), reason="r").placeholder
    with pytest.raises(ValueError):
        view.set_aside_batch([(u1, ok), (u2, ok)])   # u2's placeholder names u1
    assert not any(b.aside for b in view.blocks), "a refused batch changes nothing"


def test_restore_returns_the_exact_original_bytes():
    view, _ = _node_view((("read_file", "grep_files"), [BIG, "é — ünïcode " + BIG]),
                         (("run_command",), [SMALL]))
    before = json.dumps(view.render(), sort_keys=True, ensure_ascii=False)
    unit = view.units()[0]
    view.set_aside(unit, offload_decision(view, unit, held_resolver(view), reason="r").placeholder)
    assert json.dumps(view.render(), sort_keys=True, ensure_ascii=False) != before
    assert view.restore(unit.ref) is True
    assert json.dumps(view.render(), sort_keys=True, ensure_ascii=False) == before
    assert view.restore(unit.ref) is False, "nothing left to restore"


def test_restore_refuses_a_record_copy_that_differs():
    view, _ = _node_view((("read_file",), [BIG]), (("run_command",), [SMALL]))
    unit = view.units()[0]
    view.set_aside(unit, offload_decision(view, unit, held_resolver(view), reason="r").placeholder)
    wrong = [Block(block_id="x", ref=unit.ref, kind=b.kind,
                   messages=[{**m, "content": "changed"} if m.get("role") == "tool" else dict(m)
                             for m in b.messages], tokens=0) for b in unit.blocks]
    assert view.restore(unit.ref, wrong) is False
    assert any(b.aside for b in unit.results), "the unit stays aside"
    exact = [Block(block_id="y", ref=unit.ref, kind=b.kind,
                   messages=[dict(m) for m in b.messages], tokens=0) for b in unit.blocks]
    assert view.restore(unit.ref, exact) is True


# -- tokens are recounted ------------------------------------------------------

def test_decisions_recount_a_block_after_an_in_place_edit():
    shot = {"role": "user", "content": [{"type": "text", "text": "shot"},
                                        {"type": "image_url", "image_url": {"url": "data:x"}}]}
    view = ContextView()
    block = view.admit_live(SCREENSHOT, shot)
    stale = block.tokens
    shot["content"] = "[an earlier page screenshot was here; only the newest is kept]"
    assert block.tokens == stale, "the admit count is stale by design"
    assert recount(block) == estimate_tokens([shot]) < stale
    # the gate's saving reads the content NOW: a result shrunk in place after
    # admit no longer passes break-even
    view2, messages = _node_view((("read_file",), [BIG]), (("run_command",), [SMALL]))
    messages[3]["content"] = SMALL
    d = offload_decision(view2, view2.units()[0], held_resolver(view2), reason="r")
    assert (d.allowed, d.reason) == (False, cv.REFUSE_BREAK_EVEN)

"""BT-2 (specs/clm-memory Wave 2, T2.3 + T2.4): a DER node on a SMALL window.

The harness guarantees, with a model that never edits its own context: ten reads
of 7,000 characters on an 8,000-token window. Without the CLM hooks the input
grows past the router's budget (the router would cut blind); with them, at
every model call:
  - the input fits the router's budget (window - reserve) - no blind drop;
  - the conversation stays valid (every tool_calls message is answered by its
    tool messages, no orphan tool message);
  - every set-aside result names a reference that resolves to its whole text;
  - one OFFLOADED event per set-aside unit.
And the cut between steps names where the rest lives (T2.4).
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List

from backend.agent import node_executor as ne
from backend.agent.context_gauge import estimate_tokens
from backend.agent.context_view import parse_placeholder

WINDOW = 8000
READS = 10
READ_CHARS = 7000


def _tool(name: str) -> Dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": name,
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}}


TOOLS = [_tool("read_file"), _tool("run_command")]


def _call(i: int, path: str) -> Dict[str, Any]:
    return {"id": f"c{i}", "type": "function",
            "function": {"name": "read_file", "arguments": json.dumps({"path": path})}}


def _budget(max_tokens: int = 8192) -> int:
    # router.py _cap_messages_to_window: the same arithmetic
    reserve = min(max(256, max_tokens), WINDOW // 2) + 256
    return max(256, WINDOW - reserve)


def _valid(messages: List[Dict[str, Any]]) -> bool:
    open_ids: set = set()
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            if open_ids:
                return False
            open_ids = {tc["id"] for tc in m["tool_calls"]}
        elif m.get("role") == "tool":
            if m.get("tool_call_id") not in open_ids:
                return False
            open_ids.discard(m["tool_call_id"])
        elif open_ids:
            return False
    return True


def _run(with_clm: bool):
    script = [("", [_call(i, f"part{i}.txt")]) for i in range(1, READS + 1)]
    script.append(("Read them all.\nSTATUS: done", []))
    seen: List[List[Dict[str, Any]]] = []
    store: Dict[str, str] = {}
    events: List[tuple] = []

    def generate(role, messages, tools=None, **kw):
        seen.append(copy.deepcopy(messages))
        text, calls = script.pop(0)
        return text, "", copy.deepcopy(calls)

    def record_result(name, params, text, call_ord):
        rid = f"r{len(store) + 1:04d}"
        store[rid] = text
        return rid

    hooks = dict(record_result=record_result, ref_readable=lambda rid: rid in store,
                 on_clm_event=lambda label, payload: events.append((label, payload)),
                 window=WINDOW) if with_clm else {}
    ctx = ne.NodeContext(
        generate=generate,
        execute=lambda name, params: {"success": True, "content": params.get("path", "")},
        format_result=lambda name, raw: (raw["content"] + ":" + "x" * READ_CHARS)[:READ_CHARS],
        tools=TOOLS, task="Read every part", conv_id="bt2", max_calls=READS + 2, **hooks)
    result = ne.run_node("Read the parts", ctx)
    return seen, store, events, result


def test_without_the_hooks_the_input_outgrows_the_router_budget():
    seen, _store, _events, _r = _run(with_clm=False)
    assert max(estimate_tokens(m, TOOLS) for m in seen) > _budget()


def test_with_the_hooks_every_call_fits_the_budget_and_stays_valid():
    seen, store, events, result = _run(with_clm=True)
    assert len(seen) == READS + 1
    for i, msgs in enumerate(seen):
        assert estimate_tokens(msgs, TOOLS) <= _budget(), f"call {i + 1} over budget"
        assert _valid(msgs), f"call {i + 1} is not a valid conversation"
    # something really left, and each set-aside result names a whole record
    asides = [m["content"] for m in seen[-1] if m.get("role") == "tool"
              and str(m.get("content", "")).startswith("[[SET ASIDE")]
    assert asides
    for line in asides:
        ref = parse_placeholder(line)
        assert ref is not None and ref.kind == "tool_result" and ref.id in store
        assert len(store[ref.id]) == READ_CHARS  # the whole text, not the clip
    offloaded = [p for label, p in events if label == "OFFLOADED"]
    assert sum(len(p["refs"]) for p in offloaded) == len(asides)


def test_the_step_result_names_where_each_long_result_lives():
    _seen, store, _events, result = _run(with_clm=True)
    text = result.as_step_result()
    assert "recall_memory with expand=<ref>" in text
    for rid in store:
        assert f"tool_result:{rid}" in text


def test_a_failing_record_never_blocks_the_step():
    script = [("", [_call(1, "a.txt")]), ("ok\nSTATUS: done", [])]

    def boom(*a):
        raise RuntimeError("store down")

    ctx = ne.NodeContext(
        generate=lambda role, messages, tools=None, **kw: (lambda t: (t[0], "", t[1]))(script.pop(0)),
        execute=lambda name, params: {"success": True, "content": "a"},
        format_result=lambda name, raw: "y" * READ_CHARS,
        tools=TOOLS, conv_id="bt2-fail", record_result=boom,
        ref_readable=lambda rid: False, window=WINDOW)
    before = ne.clm_node_stats()["record_failures"]
    result = ne.run_node("Read a", ctx)
    assert result.success
    assert ne.clm_node_stats()["record_failures"] == before + 1
    assert "tool_result:" not in result.as_step_result()


def test_asking_back_for_a_set_aside_result_counts_a_premature_eviction():
    script = [("", [_call(i, f"part{i}.txt")]) for i in range(1, 5)]
    store: Dict[str, str] = {}
    events: List[tuple] = []
    state = {"asked": False}

    def generate(role, messages, tools=None, **kw):
        if script:
            text, calls = script.pop(0)
            return text, "", copy.deepcopy(calls)
        asides = [m["content"] for m in messages if m.get("role") == "tool"
                  and str(m.get("content", "")).startswith("[[SET ASIDE")]
        if asides and not state["asked"]:
            state["asked"] = True
            ref = parse_placeholder(asides[0])
            call = {"id": "back", "type": "function", "function": {
                "name": "recall_memory",
                "arguments": json.dumps({"expand": f"{ref.kind}:{ref.id}"})}}
            return "", "", [call]
        return "Done.\nSTATUS: done", "", []

    def record_result(name, params, text, call_ord):
        rid = f"r{len(store) + 1:04d}"
        store[rid] = text
        return rid

    ctx = ne.NodeContext(
        generate=generate,
        execute=lambda name, params: {"success": True, "content": "x"},
        format_result=lambda name, raw: "z" * READ_CHARS,
        tools=TOOLS + [_tool("recall_memory")], conv_id="bt2-back", max_calls=8,
        record_result=record_result, ref_readable=lambda rid: rid in store,
        on_clm_event=lambda label, payload: events.append((label, payload)), window=WINDOW)
    ne.run_node("Read parts", ctx)
    assert state["asked"]
    assert [p for label, p in events if label == "PREMATURE_EVICTION"]


def test_the_gauge_line_shows_only_with_the_hooks():
    seen_on, _s, _e, _r = _run(with_clm=True)
    seen_off, _s2, _e2, _r2 = _run(with_clm=False)
    tool_text_on = [m["content"] for m in seen_on[-1] if m.get("role") == "tool"]
    assert any("tokens |" in t and "set aside]" in t for t in tool_text_on)
    assert all("set aside]" not in str(m.get("content", "")) and "[ref tool_result:" not in str(m.get("content", ""))
               for msgs in seen_off for m in msgs)


def test_the_model_can_set_aside_a_result_by_its_ref_through_the_same_gate():
    store: Dict[str, str] = {}
    events: List[tuple] = []
    script = [("", [_call(1, "a.txt")]), ("", [_call(2, "b.txt")])]
    state = {"asked": False, "reply": None}

    def generate(role, messages, tools=None, **kw):
        if script:
            text, calls = script.pop(0)
            return text, "", copy.deepcopy(calls)
        if not state["asked"]:
            state["asked"] = True
            first = next(m["content"] for m in messages if m.get("role") == "tool")
            ref = first.split("\n", 1)[0][len("[ref "):-1]       # "[ref tool_result:<id>]"
            call = {"id": "aside", "type": "function", "function": {
                "name": "recall_memory",
                "arguments": json.dumps({"set_aside": ref + " tool_result:nope", "reason": "done with a"})}}
            return "", "", [call]
        state["reply"] = next(m["content"] for m in reversed(messages) if m.get("role") == "tool")
        state["final"] = copy.deepcopy(messages)
        return "Done.\nSTATUS: done", "", []

    def record_result(name, params, text, call_ord):
        rid = f"{len(store) + 1:032x}"
        store[rid] = text
        return rid

    ctx = ne.NodeContext(
        generate=generate,
        execute=lambda name, params: {"success": True, "content": "x"},
        format_result=lambda name, raw: json.dumps(raw) if name == "recall_memory" else "w" * READ_CHARS,
        tools=TOOLS + [_tool("recall_memory")], conv_id="bt2-model", max_calls=8,
        record_result=record_result, ref_readable=lambda rid: rid in store,
        on_clm_event=lambda label, payload: events.append((label, payload)), window=128000)
    ne.run_node("Read a and b", ctx)
    body = state["reply"]
    if body.startswith("[ref "):                     # the result's own ref head
        body = body.split("\n", 1)[1]
    reply = json.loads(body.split("\n[view")[0]) if body.startswith("{") else None
    assert reply is not None and reply["success"] is True
    assert reply["refused"] == {"tool_result:nope": "not_in_view"}
    assert [p.get("by") for label, p in events if label == "OFFLOADED"] == ["model"]
    first_tool = next(m for m in state["final"] if m.get("role") == "tool")
    assert first_tool["content"].startswith("[[SET ASIDE tool_result:")

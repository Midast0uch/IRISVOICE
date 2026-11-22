"""BT-1 + BT-3 (specs/clm-memory design.md "Testing Strategy"), through the real loop.

BT-1: a node at 8x context pressure (24 reads of 9,600 chars on an 8,000-token
window, ~8.2x) with the REAL kernel CLM hooks (_clm_node_hooks: the chat-record
writer, the readability check, the event sink) and the REAL router cap counting
blind drops at every call:
  - blind drops = 0 (the router never has to cut);
  - every set-aside unit has its OFFLOADED event;
  - the final answer uses a value that only the FIRST result held, brought back
    with recall_memory(expand=<ref>) through the real expand handler.
BT-3: forget a strand through the real correction endpoint, then expand a result
of that strand: case `forgotten`, never the content; undo brings it back. And a
row the record's budget evicted expands to `pruned` (CLM-2 AC4).
"""
from __future__ import annotations

import copy
import importlib
import json
import re
import time
from types import SimpleNamespace

import pytest

from backend.tests.contract.test_memory_corrections_contract import (  # noqa: F401 - fixtures
    _post, _undo, env, rich)

WINDOW = 8000
READS = 24
READ_CHARS = 9600
NEEDLE = "OMEGA-4471"


@pytest.fixture()
def cs(tmp_path, monkeypatch):
    monkeypatch.setenv("IRIS_CONVERSATIONS_DB", str(tmp_path / "conversations.db"))
    import backend.conversation_store as store

    importlib.reload(store)
    yield store
    lane = store._tr_lane()
    deadline = time.monotonic() + 10.0
    while lane.pending() and time.monotonic() < deadline:
        time.sleep(0.01)
    lane.flush(10.0)
    try:
        store._conn.close()
    except Exception:  # noqa: BLE001
        pass


class _Kernel:
    conversation_id = "conv-bt"
    _DER_READ_TOOLS: set = set()

    def resolve_context_window_with_source(self, role="reasoning"):
        return SimpleNamespace(tokens=WINDOW, source="test")


def _tool(name):
    return {"type": "function", "function": {
        "name": name, "description": name,
        "parameters": {"type": "object", "properties": {"path": {"type": "string"},
                                                        "expand": {"type": "string"}}}}}


def _call(i, name, **args):
    return {"id": f"c{i}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _report(i):
    head = f"REPORT {i:02d}\n" + (f"the access token is {NEEDLE}\n" if i == 0 else "no token here\n")
    return (head + f"line of report {i:02d} " * 600)[:READ_CHARS]


def test_bt1_eight_x_pressure_no_blind_drop_every_offload_evented_value_comes_back(cs, monkeypatch):
    from backend.agent import node_executor as ne
    from backend.agent import tool_bridge as tb
    from backend.agent.inference.router import InferenceRouter
    from backend.agent.kernel import base
    from backend.agent.kernel.der import node

    assert READS * READ_CHARS / 3.5 / WINDOW >= 8.0              # the pressure this test claims
    events = []
    monkeypatch.setattr(base, "_emit_event",
                        lambda owner, label, **kw: events.append((label, kw.get("payload"))))
    monkeypatch.setattr("backend.agent.event_emit.emit", lambda *a, **k: None)
    hooks = node._clm_node_hooks(_Kernel(), SimpleNamespace(step_id="s1"), "turn-1")
    hooks.pop("landmarks", None)
    tools = [_tool("read_file"), _tool("recall_memory")]
    dropped, finals = [], []
    state = {"turn": 0}

    def generate(role, messages, tools=None, **kw):
        cut = InferenceRouter._cap_messages_to_window(copy.deepcopy(messages), tools, WINDOW,
                                                      int(kw.get("max_tokens") or 1024))
        dropped.append(len(messages) - len(cut))
        t = state["turn"]
        state["turn"] += 1
        if t < READS:
            return f"Reading report {t}.", "", [_call(t, "read_file", path=f"report_{t:02d}.txt")]
        if t == READS:
            # the model reads the FIRST result's slip and asks for it back by its ref
            first = next(m for m in messages if m.get("role") == "tool")
            ref = re.search(r"tool_result:[0-9a-f]{32}", str(first["content"])).group(0)
            assert "SET ASIDE" in str(first["content"])               # it really had left the view
            return "Bringing back report 0.", "", [_call(t, "recall_memory", expand=ref)]
        last = str(messages[-1].get("content") or "")
        found = NEEDLE if NEEDLE in last else "unknown"
        finals.append(found)
        return f"The access token is {found}.\nSTATUS: done", "", []

    def execute(name, params):
        if name == "recall_memory":
            return tb._expand_tool_result(SimpleNamespace(
                _active_conversation_id={}, _memory_interface=SimpleNamespace(episodic=None)),
                "s", params)
        i = int(params["path"][7:9])
        return {"success": True, "content": _report(i)}

    before = ne.clm_node_stats()
    res = ne.run_node("Find the access token in the reports", ne.NodeContext(
        generate=generate, execute=execute,
        format_result=lambda name, raw: (raw.get("content") if isinstance(raw, dict) and raw.get("content")
                                         else json.dumps(raw)),
        tools=tools, conv_id="conv-bt", max_calls=READS + 4, max_tokens=1024, **hooks))
    after = ne.clm_node_stats()
    set_aside = after["set_aside_units"] - before["set_aside_units"]

    assert sum(dropped) == 0, f"router cut blind: {dropped}"
    assert set_aside > 0
    assert sum(1 for label, _p in events if label == "OFFLOADED") == set_aside
    assert finals == [NEEDLE] and NEEDLE in (res.summary or "")


def _record(cs, conv, text, rid=None):
    rid = rid or cs.new_tool_result_id()
    assert cs.add_tool_result(rid, conv, "t1", "s1", 0, "read_file", "a.txt", text)
    assert cs.get_tool_result(rid, wait_s=5.0)
    return rid


def test_bt3_a_forgotten_strand_expands_to_forgotten_and_undo_brings_it_back(cs, rich):
    from backend.agent import tool_bridge as tb

    rid = _record(cs, "conv-a", "the deploy key lives in vault path ops/deploy " * 80)
    bridge = SimpleNamespace(_active_conversation_id={},
                             _memory_interface=SimpleNamespace(episodic=SimpleNamespace(db=rich.conn)))
    assert tb._expand_tool_result(bridge, "s", {"expand": f"tool_result:{rid}"})["success"]
    d = _post(rich, "forget_learned", "strand:conv-a").json()
    out = tb._expand_tool_result(bridge, "s", {"expand": f"tool_result:{rid}"})
    assert out["success"] is False and out["case"] == "forgotten" and "content" not in out
    assert "vault path" not in json.dumps(out)
    _undo(rich, d)
    assert tb._expand_tool_result(bridge, "s", {"expand": f"tool_result:{rid}"})["success"]


def test_bt3_an_evicted_result_expands_to_pruned(cs, monkeypatch):
    from backend.agent import tool_bridge as tb

    monkeypatch.setattr(cs, "TOOL_RESULTS_PER_CONVERSATION", 2)   # drive the budget, not 200 writes
    first = _record(cs, "conv-p", "first result " * 300)
    for _ in range(3):
        _record(cs, "conv-p", "later result " * 300)
    out = tb._expand_tool_result(SimpleNamespace(
        _active_conversation_id={}, _memory_interface=SimpleNamespace(episodic=None)),
        "s", {"expand": f"tool_result:{first}"})
    assert out["success"] is False and out["case"] == "pruned" and out["error"]

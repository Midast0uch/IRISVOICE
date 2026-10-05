"""Natural split inside a node (owner 2026-10-04): the calls ONE model answer
asks for are siblings of the DAG and run side by side - no planner wording
needed.

Live A/B r09 (three separate facts): the planner made ONE step in 6 of 8 runs;
that node's model asked for the three searches in one answer and they ran in a
row (2.5 + 3.6 + 3.3 s). The owner: speed must come from the DAG, not from the
prompt.

Contract (run_node with ctx.parallel_ok):
  1. every call of the answer may run side by side -> they overlap, and the
     model still reads the results in its own order;
  2. a batch with any call that may not (a side effect) runs in order;
  3. no ctx.parallel_ok -> in order (the old behavior).
"""
from __future__ import annotations

import json
import threading
import time

from backend.agent.node_executor import NodeContext, run_node

TOOLS = [{"type": "function", "function": {"name": n, "parameters": {}}}
         for n in ("search", "edit_file")]
_WORK_S = 0.4


def _call(name, args, i):
    return {"id": f"c{i}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _node(batch, parallel_ok):
    replies = [("", batch), ("All three found.", [])]
    seen = []
    live = {"n": 0, "max": 0}
    lock = threading.Lock()

    _pending = list(replies)

    def gen2(role, messages, **k):
        seen.append([dict(m) for m in messages])
        text, calls = _pending.pop(0)
        return text, "", calls

    def execute(name, params):
        with lock:
            live["n"] += 1
            live["max"] = max(live["max"], live["n"])
        time.sleep(_WORK_S)
        with lock:
            live["n"] -= 1
        return {"success": True, "content": f"{name}:{params.get('query') or params.get('path')}"}

    ctx = NodeContext(generate=gen2, execute=execute, format_result=lambda n, r: json.dumps(r),
                      tools=TOOLS, workdir="C:/proj", parallel_ok=parallel_ok)
    t0 = time.monotonic()
    result = run_node("find three facts", ctx)
    return result, time.monotonic() - t0, live["max"], seen


def _read_only(name, params):
    return name == "search"


def test_sibling_calls_of_one_answer_run_side_by_side_in_the_models_order():
    batch = [_call("search", {"query": q}, i) for i, q in enumerate(("eiffel", "golden gate", "potter"))]
    result, took, peak, seen = _node(batch, _read_only)
    assert result.success
    assert peak == 3, f"the three searches did not overlap (peak {peak})"
    assert took < 3 * _WORK_S, f"{took:.2f}s - they ran in a row"
    tool_msgs = [m for m in seen[-1] if m.get("role") == "tool"]
    assert [json.loads(m["content"])["content"] for m in tool_msgs] == [
        "search:eiffel", "search:golden gate", "search:potter"], "results out of the model's order"
    assert [c["target"] for c in result.calls] == ["eiffel", "golden gate", "potter"]


def test_a_batch_with_a_side_effect_runs_in_order():
    batch = [_call("search", {"query": "a"}, 0), _call("edit_file", {"path": "m.py"}, 1),
             _call("search", {"query": "b"}, 2)]
    _result, took, peak, _seen = _node(batch, _read_only)
    assert peak == 1, "a side-effect batch ran in parallel"
    assert took >= 3 * _WORK_S


def test_without_the_predicate_a_node_runs_in_order():
    batch = [_call("search", {"query": q}, i) for i, q in enumerate(("a", "b"))]
    _result, _took, peak, _seen = _node(batch, None)
    assert peak == 1

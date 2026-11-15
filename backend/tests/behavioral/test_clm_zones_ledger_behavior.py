"""BT-4 + CLM-5 (specs/clm-memory Wave 4) on the node path, small window.

- AC3: the task's dead ends (memory_cases.dead_ends, written by record_step on
  a repeated failure) reach the step as a bounded DEAD ENDS section - absent,
  not padded, when there are none.
- AC2: an unresolved tool error is an open item of its unit; the unit may
  leave the view only with its slip carrying that item; a later success on the
  same action resolves it.
- AC4: a set-aside failure comes back (RESTRETCHED) when the model's next
  action matches it (dead_end_match) or the same error happens again
  (error_match); a re-stretch that would not fit is refused and counted.
"""
from __future__ import annotations

import copy
import json
import sqlite3
from typing import Any, Dict, List

from backend.agent import node_executor as ne
from backend.agent.context_view import parse_placeholder

WINDOW = 8000
# A window where ONE restored result fits beside the newest one: reserve =
# min(8192, 7000) + 256 = 7256, limit = (14000 - 7256) x 0.8 = 5395 tokens,
# one 7,000-char result ~2,000 tokens. On 8,000 the limit is 2,995 and a
# restore never fits next to the newest unit - that case is the refusal test.
ROOMY = 14000
BIG = 7000


def _tool(name: str) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": name,
                                             "parameters": {"type": "object"}}}


TOOLS = [_tool("read_file"), _tool("run_command")]


def _call(i, name, **args):
    return {"id": f"c{i}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def _node(script, execute, dead_ends=(), window=WINDOW):
    seen: List[List[Dict[str, Any]]] = []
    store: Dict[str, str] = {}
    events: List[tuple] = []
    script = list(script)

    def generate(role, messages, tools=None, **kw):
        seen.append(copy.deepcopy(messages))
        if script:
            text, calls = script.pop(0)
            return text, "", copy.deepcopy(calls)
        return "Done.\nSTATUS: done", "", []

    def record_result(name, params, text, call_ord):
        rid = f"{len(store) + 1:032x}"
        store[rid] = text
        return rid

    ctx = ne.NodeContext(
        generate=generate, execute=execute,
        format_result=lambda name, raw: (json.dumps(raw) + " " + "p" * BIG)[:BIG],
        tools=TOOLS, conv_id="bt4", max_calls=14, record_result=record_result,
        ref_readable=lambda rid: rid in store,
        on_clm_event=lambda label, payload: events.append((label, payload)),
        window=window, dead_ends=list(dead_ends))
    result = ne.run_node("Fix the build", ctx)
    return seen, events, result


def _ok(name, params):
    return {"success": True, "content": params.get("path") or params.get("command")}


def test_ac3_the_dead_end_ledger_reaches_the_step_bounded_and_only_when_present():
    seen, _e, _r = _node([], _ok, dead_ends=[f"run_command:make t{i}" for i in range(12)])
    step = seen[0][1]["content"]
    assert "DEAD ENDS (actions that already failed in this task" in step
    assert step.count("\n- run_command:make t") == ne._LEDGER_MAX          # bounded: the newest 8
    assert "run_command:make t11" in step and "run_command:make t0\n" not in step
    seen2, _e2, _r2 = _node([], _ok)
    assert "DEAD ENDS" not in seen2[0][1]["content"]                       # never padded


def test_ac2_ac4_a_set_aside_failure_carries_its_error_and_comes_back_on_the_same_action():
    def execute(name, params):
        if params.get("command") == "make build":
            return {"success": False, "error": "linker error: undefined symbol foo"}
        return _ok(name, params)

    script = [("", [_call(1, "run_command", command="make build")])]
    script += [("", [_call(i, "read_file", path=f"f{i}.c")]) for i in range(2, 6)]
    script += [("", [_call(9, "run_command", command="make build")])]      # the same failed action again
    seen, events, _r = _node(script, execute, window=ROOMY)
    # while it was aside, its slip named the unresolved error (AC2)
    slips = [m["content"] for msgs in seen for m in msgs
             if m.get("role") == "tool" and str(m.get("content", "")).startswith("[[SET ASIDE")]
    failed_slips = [s for s in slips if "FAILED run_command:make build" in s]
    assert failed_slips and parse_placeholder(failed_slips[0]) is not None
    labels = [(label, p.get("trigger")) for label, p in events]
    assert ("RESTRETCHED", "dead_end_match") in labels                     # AC4
    # after the re-stretch the earlier failure is back in full view
    last = seen[-1]
    first_result = next(m for m in last if m.get("role") == "tool" and m.get("tool_call_id") == "c1")
    assert "linker error" in first_result["content"] and not first_result["content"].startswith("[[SET")


def test_ac4_the_same_error_again_brings_back_the_earlier_failure():
    calls = {"n": 0}

    def execute(name, params):
        if params.get("command", "").startswith("make"):
            return {"success": False, "error": "disk full"}
        return _ok(name, params)

    script = [("", [_call(1, "run_command", command="make a")])]
    script += [("", [_call(i, "read_file", path=f"g{i}.c")]) for i in range(2, 6)]
    script += [("", [_call(9, "run_command", command="make b")])]          # different action, same error
    _seen, events, _r = _node(script, execute, window=ROOMY)
    assert ("RESTRETCHED", "error_match") in [(l, p.get("trigger")) for l, p in events]


def test_ac2_a_later_success_resolves_the_open_item():
    state = {"n": 0}

    def execute(name, params):
        if params.get("command") == "make":
            state["n"] += 1
            return {"success": state["n"] > 1, "error": "flaky"} if state["n"] == 1 else _ok(name, params)
        return _ok(name, params)

    script = [("", [_call(1, "run_command", command="make")]),
              ("", [_call(2, "run_command", command="make")])]
    script += [("", [_call(i, "read_file", path=f"h{i}.c")]) for i in range(3, 8)]
    seen, _events, _r = _node(script, execute)
    slips = [m["content"] for msgs in seen for m in msgs
             if m.get("role") == "tool" and str(m.get("content", "")).startswith("[[SET ASIDE")]
    assert slips and not any("FAILED run_command:make" in s for s in slips)


def test_ac3_dead_ends_for_reads_the_existing_bounded_list(tmp_path):
    from backend.memory import memory_events as me

    conn = sqlite3.connect(str(tmp_path / "m.db"), check_same_thread=False)
    me.ensure_schema(conn)
    for step in ("s1", "s2", "s3"):
        me.record_step(conn, thread_id="sess", task_id="sess:t1", step_id=step,
                       tool="run_command", params={"command": "make"}, success=False,
                       verified="FAILED", error_text="boom", description="build")
    assert me.dead_ends_for(conn, "sess:t1") == ["run_command:make"]
    assert me.dead_ends_for(conn, "sess:other") == []
    assert me.dead_ends_for(None, "x") == []                                # never raises


def test_edge_a_restretch_that_cannot_fit_is_refused_counted_and_the_view_stays_in_budget():
    def execute(name, params):
        if params.get("command") == "make build":
            return {"success": False, "error": "linker error"}
        return _ok(name, params)

    script = [("", [_call(1, "run_command", command="make build")])]
    script += [("", [_call(i, "read_file", path=f"k{i}.c")]) for i in range(2, 6)]
    script += [("", [_call(9, "run_command", command="make build")])]
    before = ne.clm_node_stats()["restretch_refused"]
    seen, events, _r = _node(script, execute, window=WINDOW)
    assert ne.clm_node_stats()["restretch_refused"] > before
    assert "RESTRETCHED" not in [label for label, _p in events]
    from backend.agent.context_gauge import estimate_tokens

    reserve = min(max(256, 8192), WINDOW // 2) + 256
    assert all(estimate_tokens(m, TOOLS) <= WINDOW - reserve for m in seen)   # never over the router budget

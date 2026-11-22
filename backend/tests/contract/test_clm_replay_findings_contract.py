"""CLM TG-2 replay findings (scripts/validate_view_replay.py, 2026-11-22), guarded.

Replaying 101 recorded nodes at an 8,192-token window found 6 calls over the
router budget WITH the CLM hooks on - blind drops the hooks exist to prevent:
  1. the CLOSING call ("step call limit reached") went out without the shrink;
  2. one model turn that read five 8,000-char reports in parallel returned more
     than the whole budget, and that turn is the newest unit, which never leaves.
Fixes: the closing call shrinks first; on a known window the results of one
turn share a fixed part of it, each cut naming its record ref.
Flag off (window 0): the 8,000-char clip is unchanged (byte-equal node).
"""
from __future__ import annotations

import copy
import json

from backend.agent import node_executor as ne
from backend.agent.context_gauge import estimate_tokens

WINDOW = 8192
BUDGET = WINDOW - (min(max(256, 1024), WINDOW // 2) + 256)   # the router's: 6,912


def _tool(name):
    return {"type": "function", "function": {"name": name, "description": name,
                                             "parameters": {"type": "object"}}}


def _call(i, path):
    return {"id": f"c{i}", "type": "function",
            "function": {"name": "read_file", "arguments": json.dumps({"path": path})}}


def _run(script, window, max_calls=14):
    seen, store = [], {}
    script = list(script)

    def generate(role, messages, tools=None, **kw):
        seen.append((copy.deepcopy(messages), tools))
        if script:
            text, calls = script.pop(0)
            return text, "", copy.deepcopy(calls)
        return "Done.\nSTATUS: done", "", []

    def record_result(name, params, text, call_ord):
        rid = f"{len(store) + 1:032x}"
        store[rid] = text
        return rid

    hooks = {}
    if window:
        hooks = dict(record_result=record_result, ref_readable=lambda rid: rid in store,
                     on_clm_event=lambda *a: None, window=window)
    ne.run_node("Total the vendor reports", ne.NodeContext(
        generate=generate,
        execute=lambda name, params: {"success": True, "content": params["path"] + " " + "x" * 9000},
        format_result=lambda name, raw: raw["content"], tools=[_tool("read_file")],
        conv_id="replay-guard", max_calls=max_calls, max_tokens=1024, **hooks))
    return seen


FIVE = [("Reading all five reports.", [_call(i, f"vendor_{i}.txt") for i in range(5)])]


def test_one_wide_turn_fits_the_budget_and_each_cut_names_its_ref():
    seen = _run(FIVE, WINDOW)
    assert all(estimate_tokens(m, t) <= BUDGET for m, t in seen)      # was 10,300 > 6,912
    tool_msgs = [m for m in seen[1][0] if m.get("role") == "tool"]
    assert len(tool_msgs) == 5
    assert all("tool_result:" in str(m["content"]) for m in tool_msgs)   # the way back


def test_the_closing_call_is_shrunk_like_every_other_call():
    # three turns of wide reads, then the call cap: the closing call must fit too
    script = [(f"Batch {b}.", [_call(10 * b + i, f"r{b}_{i}.txt") for i in range(3)])
              for b in range(3)]
    seen = _run(script, WINDOW, max_calls=9)
    closing = [(m, t) for m, t in seen if "Stop here" in str(m[-1].get("content"))]
    assert closing, "the call cap was not reached"
    assert all(estimate_tokens(m, t) <= BUDGET for m, t in seen)


def test_flag_off_keeps_the_8000_char_clip():
    seen = _run(FIVE, 0)
    tool_msgs = [m for m in seen[1][0] if m.get("role") == "tool"]
    assert all(len(str(m["content"])) > 7000 for m in tool_msgs)        # today's node, unchanged

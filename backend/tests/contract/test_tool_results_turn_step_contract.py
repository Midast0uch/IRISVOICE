"""W0 (memory cortex plan, 2026-11-22): every tool_results row names its turn and step.

Measured on the live chat record: `tool_results.turn_id` was NULL on 3,987 of 4,000 rows.
The two writers that wrote them - the Workbench spill (`workbench/manager.py` StoreSink.write)
and the run_python code row (`tool_bridge._record_code_row`) - passed None, so a strand
could not show which turn a script or a spilled value belonged to (the plan's strand steps
and tool-output-on-click need it). A spill can happen turns later (fresh / close / idle
end), so it must carry the turn that MADE the value, not the turn that ends the workbench.

Each test FAILS on the code before this change.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.agent import node_executor as ne


def _capture(monkeypatch) -> List[tuple]:
    from backend import conversation_store as cs

    rows: List[tuple] = []
    monkeypatch.setattr(cs, "add_tool_result",
                        lambda rid, conv, turn, step, ord_, tool, target, text, **k: rows.append(
                            (conv, turn, step, tool)) or True)
    return rows


def test_run_python_code_row_carries_its_turn_and_step(monkeypatch):
    from backend.agent import tool_bridge

    rows = _capture(monkeypatch)
    tool_bridge._record_code_row("conv-1", "x = 1", "set x", {"ok": True, "wall_ms": 3}, 3,
                                 "turn-7", "s3")
    assert rows == [("conv-1", "turn-7", "s3", "run_python")]


def test_a_spill_names_the_turn_that_made_the_value(monkeypatch):
    from backend.agent.workbench import digest
    from backend.agent.workbench.manager import StoreSink

    rows = _capture(monkeypatch)
    inc = "inc-w0-test"
    digest.remember_origin({"incarnation": inc, "vars": [{"name": "totals"}]}, "sum it",
                           "turn-2", "s1")
    # the spill runs later (another turn is live by then): the row keeps turn-2 / s1
    StoreSink().write("conv-1", inc, "totals", "{'a': 1}")
    assert rows == [("conv-1", "turn-2", "s1", "wb_spill")]
    assert digest.step_of(inc, "unknown") == ("", "")


def test_the_node_injects_turn_and_step_and_strips_model_values():
    """A real run_node: the harness puts the node's turn and step into run_python params;
    a value the model writes itself is replaced."""
    seen: List[Dict[str, Any]] = []
    script = [("", [{"id": "c1", "type": "function", "function": {
        "name": "run_python", "arguments": json.dumps(
            {"code": "x = 1", "purpose": "set x", "_wb_turn": "forged", "_wb_step": "forged"})}}]),
        ("Done.\nSTATUS: done", [])]
    tools = [{"type": "function", "function": {
        "name": "run_python", "description": "run python",
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}}}}}]
    ctx = ne.NodeContext(
        generate=lambda role, messages, tools=None, **kw: (lambda t: (t[0], "", t[1]))(script.pop(0)),
        execute=lambda name, params: seen.append(dict(params)) or {"success": True, "content": "ok"},
        format_result=lambda name, raw: raw["content"],
        tools=tools, task="set x", conv_id="w0", max_calls=3,
        wb_node="node-1", wb_turn="turn-7", wb_step="s3")
    ne.run_node("Set x", ctx)
    assert seen and seen[0]["_wb_turn"] == "turn-7" and seen[0]["_wb_step"] == "s3"

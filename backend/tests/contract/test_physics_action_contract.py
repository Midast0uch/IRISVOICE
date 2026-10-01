"""A step's Caducean action follows what the step DID - node steps included (REQ-8 redo).

Measured history (backend/agent/physics_action.py docstring): the live rule fed
action 0 on every step and a balance stuck at its 3.0 clamp, so Sigma was a step
counter; K4 (adbf69f8) read every NODE step (no single tool) as COMPRESS and the
continuation brake never fired live (reverted). Guards:
  1. the rule classifies a node step by its calls, both directions;
  2. the kernel actually hands the node's calls to the physics (a rule with no
     input would be the K4 failure again).
"""
from __future__ import annotations

import ast
from pathlib import Path

from backend.agent.physics_action import COMPRESS, EXPAND, balance_from_eml, step_action

_KERNEL = Path(__file__).resolve().parents[2] / "agent" / "agent_kernel.py"


def test_node_step_that_only_read_expands():
    assert step_action(None, True, [("read_file", True), ("grep_files", True)]) == EXPAND


def test_node_step_that_wrote_compresses():
    assert step_action(None, True, [("read_file", True), ("edit_file", True)]) == COMPRESS


def test_a_failed_write_did_not_consolidate():
    assert step_action(None, True, [("edit_file", False)]) == EXPAND


def test_failed_step_expands_and_plain_steps_keep_their_tool_rule():
    assert step_action(None, False, [("edit_file", True)]) == EXPAND
    assert step_action("crawler_query", True) == EXPAND
    assert step_action(None, True) == COMPRESS          # synthesis, no calls


def test_balance_leaves_the_clamp():
    assert balance_from_eml(12.51) == 3.0
    assert 0.1 < balance_from_eml(2.0) < 1.0


def test_kernel_feeds_node_calls_to_the_physics():
    src = _KERNEL.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    run_node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "_der_run_node")
    assert any(isinstance(t, ast.Attribute) and t.attr == "node_calls"
               for n in ast.walk(run_node) if isinstance(n, ast.Assign)
               for t in n.targets), "_der_run_node no longer records the node's calls"
    assert '"node_calls"' in src and "step_action(" in src, (
        "the physics no longer reads the node's calls")

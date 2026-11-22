"""tool_choice class decision: a WRITE step keeps the RUN tools.

Found 2026-11-22 (coding gate wb_gate-20261122-145643, c10 conv-10781). The
planner rule (planning.py, the 2026-10-02 c12 rule) puts "change one file AND
check it" in the SAME step. The d1-2b class decision took WRITE for that step
and narrowed the menu to the WRITE tools only, so the node closed with "no
command-execution tool available" and the run paid a repair step.

The fix widens the WRITE class list with the RUN tools. The class label and its
calibration rows are unchanged (class_decided stays WRITE). READ and RUN keep
their own class only.

The guard drives the real `choose_node_tool` with a stub engine. On the old
code a WRITE step loses `run_command`.
"""
from __future__ import annotations

from backend.agent.tool_choice_action_class import READ, RUN, WRITE
from backend.tests.contract.test_tool_choice_class_unmapped_contract import (
    _box, _class_env)

_CODE_MENU = ["read_file", "grep_files", "edit_file", "write_file",
              "run_command", "list_directory"]


def test_a_write_class_keeps_the_run_tools(monkeypatch):
    """A clear WRITE class keeps run_command: the change is checked in-step."""
    _class_env(monkeypatch)
    pairs = [("edit_file", 0.70), ("write_file", 0.10), ("run_command", 0.08),
             ("list_directory", 0.04), ("read_file", 0.05), ("grep_files", 0.03)]
    got = _box(pairs).choose_node_tool(
        goal="Fix the off-by-one in utils.py and run its test",
        candidates=_CODE_MENU, scope_key="s")
    assert got is not None
    tools, row = got
    assert row["route"] == "class" and row["class_decided"] == WRITE, row
    for name in ("edit_file", "write_file", "run_command"):
        assert name in tools, f"{name} was stripped from a WRITE step"
    assert not {"read_file", "grep_files", "list_directory"} & set(tools)


def test_read_and_run_classes_stay_narrow(monkeypatch):
    """The widening is WRITE only: a READ or RUN class gains nothing."""
    _class_env(monkeypatch)
    read_pairs = [("read_file", 0.75), ("grep_files", 0.10), ("edit_file", 0.05),
                  ("write_file", 0.03), ("run_command", 0.04), ("list_directory", 0.03)]
    tools, row = _box(read_pairs).choose_node_tool(
        goal="Read utils.py", candidates=_CODE_MENU, scope_key="s")
    assert row["class_decided"] == READ
    assert not {"edit_file", "write_file", "run_command"} & set(tools)

    run_pairs = [("run_command", 0.75), ("list_directory", 0.10), ("edit_file", 0.05),
                 ("write_file", 0.03), ("read_file", 0.04), ("grep_files", 0.03)]
    tools, row = _box(run_pairs).choose_node_tool(
        goal="Run the test suite", candidates=_CODE_MENU, scope_key="s")
    assert row["class_decided"] == RUN
    assert not {"edit_file", "write_file", "read_file", "grep_files", "list_directory"} & set(tools)

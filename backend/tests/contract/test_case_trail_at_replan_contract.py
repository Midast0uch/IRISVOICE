"""Wave E3 (spec research-memory-chain-browser D9; brief 7.11): a known case's
trail reaches the replan after a failure - only when the live failure matches
it, bounded, and never at a physics split. Drives the REAL _split_step on a
REAL temp store (case written through memory_events, rows through the chain)."""
from __future__ import annotations

import sqlite3

from backend.memory import memory_events as me
from backend.tests.contract.test_replan_chain_context_contract import (  # noqa: F401
    _CAD,
    _item,
    _kernel,
    chain_store,
)

ERR = 'File "C:\\x\\a.py", line 12\nAssertionError: expected 3 got 2'


def _known_case(conn: sqlite3.Connection) -> None:
    t = "sess-old:turn1"
    me.record_step(conn, thread_id="sess-old", task_id=t, step_id="1", tool="run_command",
                   params={"command": "pytest"}, success=False, verified="FAILED", error_text=ERR)
    me.record_step(conn, thread_id="sess-old", task_id=t, step_id="2", tool="edit_file",
                   params={"path": "a.py", "old": "x"}, success=False, verified="FAILED",
                   error_text="no match")
    me.record_step(conn, thread_id="sess-old", task_id=t, step_id="3", tool="edit_file",
                   params={"path": "a.py"}, success=True, verified="VERIFIED",
                   description="fix the off-by-one in a.py")
    me.record_task_end(conn, thread_id="sess-old", task_id=t, success=True)


def _item_with(tool, result):
    it = _item()
    it.tool = tool
    it.result = result
    return it


def test_matching_failure_gets_the_case_trail(chain_store):
    _known_case(chain_store)
    children = _kernel(chain_store)._split_step(
        _item_with("run_command", ERR.replace("12", "77")), "verify_failed", _CAD,
        work_units=10, step_result=ERR.replace("12", "77"),
    )
    assert children
    for c in children:
        ps = c.node_record.prior_summary
        assert "KNOWN CASE (verified" in ps and "off-by-one" in ps
        assert "dead ends:" in ps and "edit_file:a.py" in ps


def test_unrelated_failure_and_physics_split_get_no_trail(chain_store):
    _known_case(chain_store)
    k = _kernel(chain_store)
    for c in k._split_step(_item_with("run_command", "ModuleNotFoundError: zz"),
                           "verify_failed", _CAD, work_units=10,
                           step_result="ModuleNotFoundError: zz"):
        assert "KNOWN CASE" not in c.node_record.prior_summary
    for c in k._split_step(_item_with("run_command", ERR), "unresolved_u", _CAD, work_units=10):
        assert "KNOWN CASE" not in c.node_record.prior_summary

"""Recall attribution v1 (EVENT_TAXONOMY section 4 memory family; Wormhole REQ-17 spirit).

A recall DELIVERED to a step is followed to that step's outcome: the same
``recall_trace_id`` appears on RECALL_DELIVERED and then on RECALL_HELPED (the step
did not fail) or RECALL_MISLED (it failed). Only recalls actually delivered to a step
count - never a recall some other step received. Drives the REAL kernel delivery
helpers and the REAL replan (``_split_step``) on a REAL temp store, with the events
written through the REAL ``memory_events`` lane."""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.gateway.iris_ffi as _ffi
from backend.agent import agent_kernel as ak
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import QueueItem
from backend.memory import memory_events as me
from backend.utils.durability_queue import lane

SESSION = "sess-attr"
TASK = f"{SESSION}:turn-1"
ERR = 'File "C:\\x\\a.py", line 12\nAssertionError: expected 3 got 2'
_CAD = {"x": 0.0, "y": 0.0, "xi": 0.0, "u": 0.1}   # |u| < U_SPLIT -> a wide split


@pytest.fixture()
def world():
    tmp = Path(tempfile.mkdtemp(prefix="attr-"))
    path = tmp / "memory.db"
    eng = _ffi._PythonFallbackEngine(db_path=str(path), key_hex="00" * 32)
    prev = _ffi._engine
    _ffi._engine = eng
    conn = sqlite3.connect(str(path), check_same_thread=False)  # the lane thread writes on it
    me.ensure_schema(conn)
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = SimpleNamespace(_mycelium=SimpleNamespace(conn=conn))
    k._tool_bridge = None
    k._der_task_class = "full"
    k._der_completed_tools = []
    k._der_work_units = 0
    k.conversation_id = "conv-attr"
    k.session_id = SESSION
    k._der_session = SESSION
    k._der_turn_id = "turn-1"
    yield k, conn
    lane("memory_events").flush()
    _ffi._engine = prev
    conn.close()
    try:
        eng._conn.close()
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)


def _item(step_id="2"):
    return QueueItem(step_id=step_id, step_number=2, description="do the thing",
                     objective_anchor="objective", depth_layer=0,
                     expected_output="thing done", critical=True)


def _events(conn, label):
    lane("memory_events").flush()
    rows = conn.execute(
        "SELECT step_index, links, payload, ts FROM memory_events WHERE label = ? ORDER BY ts, rowid",
        (label,)).fetchall()
    return [(s, json.loads(lk), json.loads(p), ts) for s, lk, p, ts in rows]


def _finish(kernel, item, ok):
    """Mirrors the finalize site: the step's outcome goes to the lane WITH the traces it carries."""
    ak._memory_events_submit(
        kernel, "record_step", thread_id=SESSION, task_id=TASK, step_id=item.step_id,
        tool="browser_act", params={"target": "m1"}, success=ok,
        verified="VERIFIED" if ok else "FAILED", error_text="" if ok else "boom: failed",
        description="", recall_trace_ids=list(getattr(item, "recall_trace_ids", None) or []),
    )


def test_a_recall_delivered_to_a_step_that_succeeds_is_helped_with_the_same_trace(world):
    kernel, conn = world
    item = _item()
    ak._der_recall_delivered(kernel, item, "neighbors", ["chain-1", "chain-2"], SESSION)
    (trace,) = item.recall_trace_ids
    _finish(kernel, item, ok=True)
    (d_step, d_links, d_payload, d_ts), = _events(conn, "RECALL_DELIVERED")
    (h_step, h_links, _p, h_ts), = _events(conn, "RECALL_HELPED")
    assert d_links["recall_trace_id"] == h_links["recall_trace_id"] == trace
    assert (d_step, h_step) == ("2", "2") and d_ts <= h_ts            # delivered, THEN helped
    assert d_payload == {"source": "neighbors", "refs": ["chain-1", "chain-2"]}
    assert _events(conn, "RECALL_MISLED") == []
    ep = {r[0] for r in conn.execute(
        "SELECT episode_id FROM memory_events WHERE label LIKE 'RECALL_%'")}
    assert ep == {TASK}                                                # one episode for both


def test_a_recall_delivered_to_a_step_that_fails_is_misled_with_the_same_trace(world):
    kernel, conn = world
    item = _item()
    ak._der_recall_delivered(kernel, item, "neighbors", ["chain-9"], SESSION)
    (trace,) = item.recall_trace_ids
    _finish(kernel, item, ok=False)
    (_s, d_links, _p, _t), = _events(conn, "RECALL_DELIVERED")
    (_s, m_links, _p, _t), = _events(conn, "RECALL_MISLED")
    assert d_links["recall_trace_id"] == m_links["recall_trace_id"] == trace
    assert _events(conn, "RECALL_HELPED") == []


def test_a_recall_is_never_credited_to_a_step_it_was_not_delivered_to(world):
    kernel, conn = world
    a, b = _item("2"), _item("3")
    ak._der_recall_delivered(kernel, a, "neighbors", [], SESSION)
    _finish(kernel, b, ok=True)               # b received nothing
    assert _events(conn, "RECALL_HELPED") == [] and _events(conn, "RECALL_MISLED") == []
    _finish(kernel, a, ok=True)
    assert len(_events(conn, "RECALL_HELPED")) == 1


def test_the_replan_recalls_reach_every_child_and_each_child_is_judged_on_its_own(world):
    kernel, conn = world
    for n in range(1, 4):                                      # this task's own chain timeline
        _ffi.ffi_immortus_chain_append(
            thread_id=SESSION, result="success", coords_from="1.00,0.00,1.00,0.00",
            coords_to="1.00,0.00,1.00,0.00", nbl_outcome=f"step_{n}", insight=f"edit module {n}",
            file_path="", landmark_id="")
    parent = _item("1")
    parent.tool, parent.result = "run_command", ERR
    children = kernel._split_step(parent, "verify_failed", _CAD, work_units=10, step_result=ERR)
    assert len(children) >= 2
    assert all(len(c.recall_trace_ids) == 1 for c in children)          # the chain timeline
    assert len({t for c in children for t in c.recall_trace_ids}) == len(children)   # one trace each
    first, last = children[0], children[-1]
    _finish(kernel, first, ok=True)
    _finish(kernel, last, ok=False)
    delivered = {lk["recall_trace_id"]: (s, p["source"]) for s, lk, p, _t in _events(conn, "RECALL_DELIVERED")}
    assert delivered[first.recall_trace_ids[0]] == (first.step_id, "chain_timeline")
    (h_step, h_links, _p, _t), = _events(conn, "RECALL_HELPED")
    (m_step, m_links, _p, _t), = _events(conn, "RECALL_MISLED")
    assert (h_step, h_links["recall_trace_id"]) == (first.step_id, first.recall_trace_ids[0])
    assert (m_step, m_links["recall_trace_id"]) == (last.step_id, last.recall_trace_ids[0])


def test_a_physics_split_delivers_no_recall(world):
    kernel, conn = world
    parent = _item("1")
    for c in kernel._split_step(parent, "unresolved_u", _CAD, work_units=10):
        assert not getattr(c, "recall_trace_ids", None)
    assert _events(conn, "RECALL_DELIVERED") == []


def test_a_prior_research_head_in_a_tool_result_is_delivered_to_the_step_that_ran_it(world):
    kernel, conn = world
    item = _item()
    ak._der_prior_research_delivered(kernel, item, "no prior here, just results", SESSION)
    assert not getattr(item, "recall_trace_ids", None)
    ak._der_prior_research_delivered(
        kernel, item, "PRIOR RESEARCH (earlier searches close to this one):\n- 2026-09-01 ...", SESSION)
    (trace,) = item.recall_trace_ids
    (_s, links, payload, _t), = _events(conn, "RECALL_DELIVERED")
    assert links["recall_trace_id"] == trace and payload["source"] == "prior_research"
    _finish(kernel, item, ok=True)
    assert len(_events(conn, "RECALL_HELPED")) == 1

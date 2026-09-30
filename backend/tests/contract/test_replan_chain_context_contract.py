"""Contract CT-K3 (REQ-4 AC4.3/AC4.4): the chain is consulted at the replan-after-failure
decision point - and nowhere else.

The replan after a failed step is ``_split_step(trigger="verify_failed")``: its
children carry the failure context in their NodeRecord ``prior_summary``
(Understanding). This drives the REAL ``_split_step`` against a REAL temp chain
store (rows written through ``ffi_immortus_chain_append``):

  - the replan context contains the timeline of THIS thread, oldest first,
    bounded to the last 8 rows, with no row of another thread;
  - mediators tried on this thread ride with it (``immortus_chain_query_mediators``);
  - a physics split ("unresolved_u") and a normal step's neighbors carry none of it;
  - a thread with no chain rows adds nothing;
  - the timeline query orders by the index (S2: no temp sort), and one
    ``[chain_recall] replan rows=<n> mediators=<m> ms=<t>`` line is logged.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.gateway.iris_ffi as _ffi
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import QueueItem
from backend.agent.ontology_recall import _TIMELINE_SQL, TIMELINE_ROWS

SESSION = "sess-k3"


@pytest.fixture()
def chain_store():
    """A temp store whose engine is the global one, plus a read connection on it."""
    tmp = Path(tempfile.mkdtemp(prefix="k3-chain-"))
    path = tmp / "memory.db"
    eng = _ffi._PythonFallbackEngine(db_path=str(path), key_hex="00" * 32)
    prev = _ffi._engine
    _ffi._engine = eng
    conn = sqlite3.connect(str(path))
    yield conn
    _ffi._engine = prev
    conn.close()
    try:
        eng._conn.close()
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)


def _append(thread, n, insight, result="success", mediator=None, coords="1.00,0.00,1.00,0.00"):
    _ffi.ffi_immortus_chain_append(
        thread_id=thread, result=result, coords_from=coords, coords_to=coords,
        nbl_outcome=f"step_{n}", insight=insight, file_path="", landmark_id="",
        mediator=mediator, mediator_source="explicit" if mediator else None,
    )


def _kernel(conn):
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = SimpleNamespace(_mycelium=SimpleNamespace(conn=conn))
    k._tool_bridge = None
    k._der_task_class = "full"
    k._der_completed_tools = []
    k._der_work_units = 0
    k.conversation_id = "conv-k3"
    k.session_id = SESSION
    return k


def _item():
    return QueueItem(step_id="s1", step_number=1, description="do the thing",
                     objective_anchor="objective", depth_layer=0,
                     expected_output="thing done", critical=True)


_CAD = {"x": 0.0, "y": 0.0, "xi": 0.0, "u": 0.1}  # |u| < U_SPLIT -> wide split


def _seed_task(conn):
    for n in range(1, 11):  # 10 rows on THIS thread
        _append(SESSION, n, f"task step {n} edit module",
                result="failure" if n == 10 else "success",
                mediator=f"tool_{n % 3}:hash" if n > 6 else None)
    for n in range(1, 4):   # another thread, interleaved in time
        _append("other-thread", n, f"OTHERTHREAD step {n}")


def test_replan_context_has_this_threads_bounded_timeline(chain_store):
    _seed_task(chain_store)
    children = _kernel(chain_store)._split_step(
        _item(), "verify_failed", _CAD, work_units=10, step_result="Error: boom"
    )
    assert children
    for c in children:
        ps = c.node_record.prior_summary
        assert "CHAIN TIMELINE (this task, oldest first):" in ps, ps
        # Bounded: the LAST 8 of this thread's 10 rows, in time order.
        assert TIMELINE_ROWS == 8
        for n in range(3, 11):
            assert f"task step {n} edit module" in ps, (n, ps)
        assert "task step 2 edit module" not in ps and "task step 1 edit module" not in ps
        assert ps.index("task step 3 ") < ps.index("task step 10 ")
        assert "OTHERTHREAD" not in ps
        # The outcome of the failed row is visible to the replanner.
        assert "step_10 failure" in ps
        # Mediators tried on this thread, near here.
        assert "MEDIATORS TRIED NEAR NOW:" in ps and "tool_" in ps
        assert len(ps) <= 1200, len(ps)


def test_context_size_is_bounded_whatever_the_rows_say(chain_store):
    for n in range(1, 12):
        _append(SESSION, n, "x" * 500, mediator=f"m{n}:" + "y" * 100)
    ps = _kernel(chain_store)._split_step(
        _item(), "verify_failed", _CAD, work_units=10
    )[0].node_record.prior_summary
    assert len(ps) <= 1200, len(ps)


def test_physics_split_and_normal_step_carry_no_chain_data(chain_store):
    _seed_task(chain_store)
    k = _kernel(chain_store)
    for c in k._split_step(_item(), "unresolved_u", _CAD, work_units=10):
        assert "CHAIN TIMELINE" not in c.node_record.prior_summary
        assert "MEDIATORS" not in c.node_record.prior_summary
    # A normal step's chain input is only the relevance-gated neighbors, never the timeline.
    item = SimpleNamespace(
        description="unrelated quantum gardening", session_id=SESSION,
        node_record=SimpleNamespace(node_type="step", topic_domain="general",
                                    execution_domain="der"),
    )
    assert k._der_recall_neighborhood(item, SESSION) == []


def test_thread_without_chain_rows_adds_nothing(chain_store):
    ps = _kernel(chain_store)._split_step(
        _item(), "verify_failed", _CAD, work_units=10
    )[0].node_record.prior_summary
    assert "CHAIN TIMELINE" not in ps and "MEDIATORS" not in ps


def test_no_store_never_raises():
    k = _kernel(None)
    k._memory_interface = None
    assert k._split_step(_item(), "verify_failed", _CAD, work_units=10)


def test_timeline_query_uses_the_index_not_a_sort(chain_store):
    plan = [r[-1] for r in chain_store.execute(
        "EXPLAIN QUERY PLAN " + _TIMELINE_SQL, (SESSION, 8))]
    assert not any("TEMP B-TREE FOR ORDER BY" in p for p in plan), plan


def test_replan_log_line_reports_rows_and_ms(chain_store, caplog):
    _seed_task(chain_store)
    with caplog.at_level(logging.INFO, logger="backend.agent.ontology_recall"):
        _kernel(chain_store)._split_step(_item(), "verify_failed", _CAD, work_units=10)
    lines = [r.getMessage() for r in caplog.records if "[chain_recall] replan" in r.getMessage()]
    assert len(lines) == 1, lines
    assert lines[0].startswith("[chain_recall] replan rows=8 mediators=3 ms="), lines[0]

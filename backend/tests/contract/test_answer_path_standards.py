"""Standards the answer path must not regress from (execution audit, 2026-09-29).

Each test pins the STRUCTURAL cause of a stall measured with in-process stack
dumps on the live store (docs/audits/2026-09-29/PROGRESS.md, "Standards").
None of them measures wall-clock on the live store — they fail on the cause,
so a regression is caught before it costs a turn.

  S1  per-session event counts (calculate_eml's input) use an index.
      Measured: SCAN of system_events on the cold 6.3 GB store took 16-84 s
      per DER step; with idx_system_events_session, ~1 ms.
  S2  the recall recency order uses an index, with no temp sort.
      Measured: the unindexed ORDER BY created_at read every row — 119 s
      cold for the widest scope, a 40 s turn-start stall; with
      idx_memory_chain_created, 0.000 s. (Corrected 2026-09-30 by a full page
      attribution: memory_chain held 4.89 GB in 37 huge rows, so the sort
      walked their overflow pages — see S11.)
  S3  a step's answer path never waits for its physics update, and a shape
      decision still folds back on it. Measured: the inline update held the
      reply 16-106 s; on the physics lane the reply no longer waits.
  S11 a document-store READ is never captured as a new document. Measured:
      get_rendered_documents results were captured, nested and re-escaped
      each round; 37 memory_chain rows grew to 4.84 GB (rows up to 841 MB)
      of the 6.6 GB store.
  S12 one memory_chain row is bounded and stored once. Measured: 28 rows
      over 1 MB held 4.83 GB, every byte twice (content == result); the
      writer now caps result at _CHAIN_RESULT_CAP and leaves content empty.
"""
from __future__ import annotations

import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest

import backend.agent.caducean_trajectory as _ct_module
import backend.agent.event_bus as _eb_module
import backend.gateway.iris_ffi as _ffi


@pytest.fixture()
def migrated_store():
    """A fresh store migrated by the same code the backend runs at startup."""
    tmp = Path(tempfile.mkdtemp(prefix="answer-path-std-"))
    store = tmp / "memory.db"
    eng = _ffi._PythonFallbackEngine(db_path=str(store), key_hex="00" * 32)
    conn = sqlite3.connect(str(store))
    yield conn
    conn.close()
    try:
        eng._conn.close()
    except Exception:
        pass


def _plan(conn, sql: str, params=()) -> list:
    return [row[-1] for row in conn.execute("EXPLAIN QUERY PLAN " + sql, params)]


# The four per-session counts calculate_eml runs (iris_core.cpp:181-256).
_EML_COUNTS = (
    "SELECT COUNT(DISTINCT interaction_payload) FROM (SELECT interaction_payload "
    "FROM system_events WHERE session_id = ? AND event_domain = 'CODE' AND "
    "event_type = 'file_edit' ORDER BY created_at DESC LIMIT 3)",
    "SELECT COUNT(*) FROM (SELECT 1 FROM system_events WHERE session_id = ? AND "
    "event_domain = 'CODE' AND event_type = 'test_run' AND outcome = 'success' "
    "ORDER BY created_at DESC LIMIT 3)",
    "SELECT COUNT(*) FROM system_events WHERE session_id = ?",
)


@pytest.mark.parametrize("sql", _EML_COUNTS)
def test_s1_session_event_counts_use_an_index(migrated_store, sql):
    plan = _plan(migrated_store, sql, ("sess",))
    scans = [p for p in plan if p.startswith("SCAN system_events")]
    assert not scans, (
        f"system_events is scanned again ({plan}) — on the cold 6 GB store "
        "this cost 16-84 s per DER step"
    )
    assert any("idx_system_events_session" in p for p in plan), plan


# ontology_recall.filtered_chain_recall: widest scope and a filtered scope.
_RECALL_ORDER = (
    "SELECT chain_id FROM memory_chain ORDER BY created_at DESC, rowid DESC LIMIT 5",
    "SELECT chain_id FROM memory_chain WHERE topic_domain = ? "
    "ORDER BY created_at DESC, rowid DESC LIMIT 5",
)


@pytest.mark.parametrize("sql", _RECALL_ORDER)
def test_s2_recall_recency_order_uses_an_index(migrated_store, sql):
    params = ("general",) if "?" in sql else ()
    plan = _plan(migrated_store, sql, params)
    assert not any("TEMP B-TREE FOR ORDER BY" in p for p in plan), (
        f"recall sorts memory_chain by reading every row again ({plan}) — "
        "119 s cold for the widest scope on the live 6.6 GB store"
    )
    assert any("idx_memory_chain_created" in p for p in plan), plan


# ── S3: the answer path never waits for the physics ─────────────────────────

class _Recorder:
    def __init__(self, *a, **kw):
        pass

    def record_commit(self, **kw):
        pass

    def record(self, **kw):
        pass

    def record_fan_trace(self, **kw):
        pass

    def get_latest_coordinate(self, _session):
        return None


class _Bus:
    def emit(self, *a, **kw):
        pass


def _stub_kernel(conversation_id: str):
    from backend.agent.agent_kernel import AgentKernel

    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = conversation_id
    k._memory_interface = None
    k._mcm_orch = None
    k._der_last_u_mag = None
    k._der_work_units = 10
    k._der_live_cad_state = lambda session: {"u": 0.5, "xi": 0.1}
    k._split_step = lambda item, reason, cad, wu, step_result="": []
    k._verify_step_result = (
        lambda goal, expected, result, tool=None, success=False: "VERIFIED"
    )
    return k


def test_s3_finalize_does_not_wait_for_physics_and_decisions_fold_back(monkeypatch):
    from backend.agent import agent_kernel as ak
    from backend.agent.der_loop import DirectorQueue, ExecutionMode, QueueItem

    # The physics update blocks until the test releases it (the measured
    # stall, made indefinite). Wall-clock is not asserted: finalize has other
    # first-call costs; what is asserted is that it returns while the physics
    # is still blocked, i.e. it never waited for it.
    release = threading.Event()
    eml_ran = threading.Event()

    def _slow_eml(_session):
        release.wait(30)
        eml_ran.set()
        return 1.0, 0.0, 0.0

    # The physics step reads the v2 state EML since REQ-8 (spec
    # research-memory-chain-browser); the block moves with the call.
    monkeypatch.setattr(_ffi, "ffi_caducean_calculate_eml", _slow_eml)
    monkeypatch.setattr(_ct_module, "get_trajectory_recorder", lambda mi: _Recorder())
    monkeypatch.setattr(_eb_module, "get_event_bus", lambda: _Bus())

    kernel = _stub_kernel("conv-answer-path-std")
    item = QueueItem(
        step_id="s1", step_number=1, description="write the module",
        tool="write_file", params={}, critical=False,
        objective_anchor="do it", expected_output="done",
    )
    queue = DirectorQueue(objective="do it", items=[item])
    queue.mode = ExecutionMode.QUICK

    try:
        kernel._der_finalize_step(
            item=item, step_result="wrote inventory.py", step_success=True,
            step_outputs=[], completed_items=[], _tokens_used=0, _token_budget=10_000,
            _session="sess-std", _turn_id="t1", _phase=2, is_mature=False,
            _live_ctx=None, plan=type("P", (), {"original_task": "do it"})(),
            context_package=None, queue=queue, verdict=None,
        )
        assert not eml_ran.is_set(), (
            "finalize returned only after the physics update finished — the "
            "physics is back on the answer path (it held replies 16-106 s)"
        )
        fold = kernel._der_physics_pending["sess-std"]
        assert not fold.ready.is_set()

        # A shape decision folds back: it returns only once the integrator moved.
        threading.Timer(0.3, release.set).start()
        ak._der_physics_settle(kernel, "sess-std")
        assert eml_ran.is_set() and fold.ready.is_set(), (
            "a shape decision read the physics before the update landed"
        )
    finally:
        release.set()
        _fold = getattr(kernel, "_der_physics_pending", {}).get("sess-std")
        if _fold is not None:
            _fold.done.wait(10)     # never leave the lane running into the next test


def test_s11_store_read_results_are_never_captured():
    """S11: a store read returns documents that are already stored; capturing
    it nests every earlier document into a new one (size doubles per round)."""
    from backend.agent.agent_kernel import AgentKernel

    kernel = AgentKernel.__new__(AgentKernel)
    listing = {"success": True, "conversation_id": "c", "documents": [
        {"document_id": "d1", "format": "json", "content": "x" * 500}
    ]}
    for tool in AgentKernel._DER_READ_TOOLS:
        assert AgentKernel._is_capture_worthy(kernel, tool, listing) is False, (
            f"S11: {tool} result would be captured as a new document"
        )
    # A fresh gather is still captured (the gate is not simply closed).
    assert AgentKernel._is_capture_worthy(kernel, "crawler_query", listing) is True


def test_s12_chain_row_is_bounded_and_stored_once():
    """S12: an oversized chain result is stored truncated with a marker, and
    the legacy content column (the live store's shape) never duplicates it."""
    tmp = Path(tempfile.mkdtemp(prefix="answer-path-s12-"))
    store = str(tmp / "memory.db")
    legacy = sqlite3.connect(store)
    # The live data/memory.db shape before the coordinate ALTER.
    legacy.execute(
        "CREATE TABLE memory_chain (entry_id TEXT DEFAULT NULL, "
        "thread_id TEXT NOT NULL, session_id TEXT DEFAULT NULL, "
        "sequence INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, "
        "metadata TEXT DEFAULT '{}', session_ts REAL DEFAULT NULL, "
        "result TEXT DEFAULT NULL, distilled INTEGER DEFAULT 0, "
        "created_at REAL NOT NULL, PRIMARY KEY (thread_id, sequence))"
    )
    legacy.commit()
    legacy.close()
    eng = _ffi._PythonFallbackEngine(db_path=store, key_hex="00" * 32)
    try:
        big = "y" * (_ffi._CHAIN_RESULT_CAP * 4)
        assert eng.immortus_chain_append("s12-thread", big) == 0
    finally:
        eng._conn.close()
    conn = sqlite3.connect(store)
    try:
        result, content = conn.execute(
            "SELECT result, content FROM memory_chain WHERE thread_id = ?",
            ("s12-thread",),
        ).fetchone()
    finally:
        conn.close()
    assert len(result) < _ffi._CHAIN_RESULT_CAP + 200, "S12: chain row not capped"
    assert "truncated" in result, "S12: a capped row must say it was truncated"
    assert not content, "S12: content duplicates result (every row stored twice)"

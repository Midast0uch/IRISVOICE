"""Behavioral (REQ-26 AC6 / T41b) — THE discriminating region-scoped test.

Drive the REAL ``AgentKernel._der_finalize_step`` (same harness as
test_der_step_edge_scoring.py) with five FAILED steps whose tool is
"run_command" while TWO coordinate regions are active in the session:

  region A  — the failures happen here
  region B  — the same mediator, NOT touched

Assert the EMERGENT property that separates a real region-scoped posterior
from a decay curve or a global per-tool score: repeated failure of the
mediator in region A demonstrably lowers its RANK in A while leaving its
rank AND score in region B materially unchanged (exactly 0.5 — no decay, no
global fan-out). Then assert the next DECISION reads the posterior: the
BehavioralPredictor (REQ-26 AC3 prior reader) picks a different tool first
for region A, and still picks run_command first for region B.

This test is the reason REQ-26 exists: a single global score cannot express
"a tool that works in one region and fails in another".

Spec: specs/der-dag-inversion/requirements.md REQ-26 AC6, T41b.
"""

from __future__ import annotations

import sqlite3
import struct
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import backend.agent.caducean_trajectory as _ct_module
import backend.agent.event_bus as _eb_module
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_loop import DirectorQueue, ExecutionMode, QueueItem
from backend.memory.mycelium.interpreter import BehavioralPredictor
from backend.memory.mycelium.navigator import SessionRegistry
from backend.memory.mycelium.store import CoordinateStore


def _make_mem_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE mycelium_nodes (
            node_id TEXT PRIMARY KEY, space_id TEXT, coordinates BLOB,
            label TEXT, confidence REAL, access_count INTEGER DEFAULT 0,
            created_at REAL, updated_at REAL, last_accessed REAL
        );
        CREATE TABLE mycelium_edges (
            edge_id TEXT PRIMARY KEY, from_node_id TEXT, to_node_id TEXT,
            score REAL DEFAULT 0.5, edge_type TEXT DEFAULT 'traversal',
            traversal_count INTEGER DEFAULT 0, hit_count INTEGER DEFAULT 0,
            miss_count INTEGER DEFAULT 0, decay_rate REAL DEFAULT 0.01,
            created_at REAL, last_traversed REAL,
            observation_count INTEGER DEFAULT 0
        );
        """
    )
    conn.commit()
    return conn


def _insert_node(
    conn: sqlite3.Connection,
    space_id: str,
    label: str,
    coords: list,
) -> str:
    nid = str(uuid.uuid4())
    blob = struct.pack(f">{len(coords)}f", *coords)
    now = time.time()
    conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,1,?,?,?)",
        (nid, space_id, blob, label, 0.7, now, now, now),
    )
    conn.commit()
    return nid


def _insert_edge(
    conn: sqlite3.Connection,
    from_id: str,
    to_id: str,
    score: float,
) -> str:
    edge_id = str(uuid.uuid4())
    now = time.time()
    conn.execute(
        "INSERT INTO mycelium_edges "
        "(edge_id, from_node_id, to_node_id, score, edge_type, decay_rate, "
        " created_at, last_traversed) "
        "VALUES (?,?,?,?,'tool_choice',0.01,?,?)",
        (edge_id, from_id, to_id, score, now, now),
    )
    conn.commit()
    return edge_id


def _edge_score(conn: sqlite3.Connection, edge_id: str) -> float:
    row = conn.execute(
        "SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)
    ).fetchone()
    assert row is not None, f"edge {edge_id} missing"
    return row[0]


def _rank_of(conn: sqlite3.Connection, region: str, mediator_label: str) -> int:
    """1-based rank of the (region -> mediator) edge among the region's
    outbound edges, ordered by score DESC — the ordering the ranking reads."""
    rows = conn.execute(
        """SELECT m.label, e.score FROM mycelium_edges e
           JOIN mycelium_nodes m ON m.node_id = e.to_node_id
           WHERE e.from_node_id = ? AND m.space_id = 'toolpath'
           ORDER BY e.score DESC""",
        (region,),
    ).fetchall()
    labels = [r[0] for r in rows]
    assert mediator_label in labels, f"{mediator_label} not among {labels}"
    return labels.index(mediator_label) + 1


class _FakeMyc:
    def __init__(self, conn):
        self._store = CoordinateStore(conn)
        self._registry = SessionRegistry()


class _NoOpRecorder:
    def __init__(self, *a, **kw):
        pass

    def record_commit(self, **kwargs):
        pass


class _NoOpBus:
    def emit(self, *a, **kw):
        pass


def _make_kernel(conn: sqlite3.Connection, verified_label: str) -> tuple:
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-region"
    k._der_work_units = 10
    k._der_live_cad_state = lambda s: {"x": 0.1, "y": 0.2, "xi": 0.3, "u": 0.4}
    k._der_trace_task_id = lambda: "trace-region"
    myc = _FakeMyc(conn)
    k._memory_interface = SimpleNamespace(
        _mycelium=myc,
        episodic=None,
        append_to_session=lambda *a, **kw: None,
        query=lambda *a, **kw: None,
    )
    k._trailing_director = SimpleNamespace(register_observation=lambda *a, **kw: None)
    k._verify_step_result = lambda *a, **kw: verified_label
    k._emit_der_step_event = lambda *a, **kw: None
    k._der_ledger = None
    k._der_trace = lambda *a, **kw: SimpleNamespace(record=lambda *aa, **kk: None)
    return k, myc


def _finalize(kernel: AgentKernel, item: QueueItem, result: str = "nope") -> None:
    queue = DirectorQueue(objective="do the thing", items=[item])
    queue.mode = ExecutionMode.QUICK
    return kernel._der_finalize_step(
        item=item,
        step_result=result,
        step_success=False,
        step_outputs=[],
        completed_items=[],
        _tokens_used=0,
        _token_budget=10_000,
        _session="sess-region",
        _turn_id="t1",
        _phase=2,
        is_mature=False,
        _live_ctx=None,
        plan=type("P", (), {"original_task": "do the thing"})(),
        context_package=None,
        queue=queue,
        verdict=None,
    )


@pytest.fixture(autouse=True)
def _patch_ledger(monkeypatch):
    # The commit-ledger write (REQ-1 AC1) is orthogonal to this file's concern
    # (the region-scoped posterior) — stub the recorder exactly like
    # test_der_step_edge_scoring.py does so no real sqlite3 backing is needed
    # for der_commits here.
    monkeypatch.setattr(_ct_module, "CaduceanTrajectoryRecorder", _NoOpRecorder)
    monkeypatch.setattr(_eb_module, "get_event_bus", lambda: _NoOpBus())


class TestRegionScopedPosterior:
    """T41b — repeated failure in region A lowers rank in A, leaves B alone."""

    def _build_scene(self):
        conn = _make_mem_conn()
        # Two distinct coordinate regions.
        region_a = _insert_node(conn, "context", "A", [0.1, 0.2, 0.3, 0.4])
        region_b = _insert_node(conn, "context", "B", [0.8, 0.7, 0.6, 0.5])
        # The mediator under test, plus a competing mediator in each region so
        # a rank change is actually observable.
        m = _insert_node(conn, "toolpath", "run_command", [0.5, 0.5, 0.5, 0.5])
        x = _insert_node(conn, "toolpath", "other_tool", [0.5, 0.5, 0.5, 0.5])
        # Region A: M leads (0.5 > 0.45) — baseline rank 1.
        edge_a_m = _insert_edge(conn, region_a, m, score=0.5)
        edge_a_x = _insert_edge(conn, region_a, x, score=0.45)
        # Region B: M leads (0.5 > 0.45) — baseline rank 1.
        edge_b_m = _insert_edge(conn, region_b, m, score=0.5)
        edge_b_x = _insert_edge(conn, region_b, x, score=0.45)
        return conn, region_a, region_b, edge_a_m, edge_b_m

    def test_repeated_failure_lowers_rank_in_a_leaves_b_unchanged(self):
        conn, region_a, region_b, edge_a_m, edge_b_m = self._build_scene()
        kernel, myc = _make_kernel(conn, "FAILED")
        # Both regions are active in this session (a multi-region task).
        myc._registry.register("sess-region", [region_a, region_b])

        assert _rank_of(conn, region_a, "run_command") == 1
        assert _rank_of(conn, region_b, "run_command") == 1

        # FIVE consecutive FAILED steps, all using the run_command mediator.
        # Each is a distinct node (distinct step_id) so no per-step cap
        # interferes — the failures are five SEPARATE observations of the
        # same (region A, run_command) pair.
        for i in range(5):
            _finalize(
                kernel,
                QueueItem(
                    step_id=f"step-f{i}", step_number=i + 1,
                    description=f"fail {i}", tool="run_command", params={},
                    critical=False, objective_anchor="do the thing",
                    expected_output="done",
                ),
                result="it failed",
            )

        # --- Region A: rank dropped materially. ---
        rank_a = _rank_of(conn, region_a, "run_command")
        assert rank_a == 2, (
            f"repeated failure in region A must lower run_command's rank in A "
            f"(expected 2 — other_tool now leads), got {rank_a}"
        )
        score_a = _edge_score(conn, edge_a_m)
        assert score_a < 0.4, (
            f"the (A, run_command) edge must be materially weakened by 5 "
            f"misses, got {score_a}"
        )
        obs_a = conn.execute(
            "SELECT observation_count FROM mycelium_edges WHERE edge_id = ?",
            (edge_a_m,),
        ).fetchone()[0]
        assert obs_a == 5, f"(A, run_command) must carry 5 observations, got {obs_a}"

        # --- Region B: materially unchanged — exactly 0.5, rank 1. ---
        score_b = _edge_score(conn, edge_b_m)
        assert score_b == pytest.approx(0.5, abs=1e-6), (
            f"region B's edge for the SAME mediator must be untouched "
            f"(exactly the prior 0.5 — no global fan-out, no decay), got {score_b}"
        )
        rank_b = _rank_of(conn, region_b, "run_command")
        assert rank_b == 1, (
            f"the same mediator's rank in region B must be unchanged, got {rank_b}"
        )
        obs_b = conn.execute(
            "SELECT observation_count FROM mycelium_edges WHERE edge_id = ?",
            (edge_b_m,),
        ).fetchone()[0]
        assert obs_b == 0

        # --- The DECISION reads the posterior (REQ-26 AC3). ---
        # The same session, next step: the predictor must NOT pick
        # run_command first for region A (it failed 5x there) but MUST still
        # pick it first for region B (it never failed there).
        preds_a = BehavioralPredictor().predict(
            session_id="sess-region", current_node_ids=[region_a],
            task_class="code", completed_tools=[], conn=conn,
        )
        assert preds_a and preds_a[0] == "other_tool", (
            f"next decision in region A must avoid the failed mediator: "
            f"got {preds_a}"
        )
        preds_b = BehavioralPredictor().predict(
            session_id="sess-region", current_node_ids=[region_b],
            task_class="code", completed_tools=[], conn=conn,
        )
        assert preds_b and preds_b[0] == "run_command", (
            f"next decision in region B must still prefer the mediator that "
            f"never failed there: got {preds_b}"
        )

    def test_failure_in_a_does_not_score_region_b_edge(self):
        """The update site selects the (A, M) edge — region B's edge for the
        same mediator carries ZERO observations (region-scoping at the write)."""
        conn, region_a, region_b, edge_a_m, edge_b_m = self._build_scene()
        kernel, myc = _make_kernel(conn, "FAILED")
        myc._registry.register("sess-region", [region_a, region_b])

        for i in range(3):
            _finalize(
                kernel,
                QueueItem(
                    step_id=f"step-g{i}", step_number=i + 1,
                    description=f"fail {i}", tool="run_command", params={},
                    critical=False, objective_anchor="do the thing",
                    expected_output="done",
                ),
                result="nope",
            )

        row_b = conn.execute(
            "SELECT score, observation_count FROM mycelium_edges WHERE edge_id = ?",
            (edge_b_m,),
        ).fetchone()
        assert row_b[0] == pytest.approx(0.5, abs=1e-6)
        assert row_b[1] == 0

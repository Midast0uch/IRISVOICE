"""Behavioral: REQ-1 AC2/AC3/AC4 — the per-step edge-score consequence of a
step's ``verified_label``, driven through the REAL
``AgentKernel._der_finalize_step`` (same harness pattern as
test_failed_step_writes_commit_row.py).

Spec: specs/phase-6-der-integrity/requirements.md REQ-1 AC2, AC3, AC4.

The gap this file closes: the commit ledger (REQ-1 AC1) already wrote a row
for every VERIFIED/UNVERIFIED/FAILED step, but nothing fed that label into
the pre-existing, generic scoring mechanisms — ``EdgeScorer`` (scorer.py,
the hit/partial/miss delta table) and the episodes-table AVOID section
(evidence.py's ``_avoid_list`` / ``assemble_evidence``). Both of those
mechanisms are exercised here UNCHANGED — only the missing per-step call
(``AgentKernel._der_score_step_outcome``) is new.

Every assertion is on the EFFECT (a real edge score in a real
CoordinateStore, a real line in a real ``assemble_evidence`` block) —
never on whether a function was called.
"""

from __future__ import annotations

import json
import sqlite3
import struct
import time
import uuid

import pytest

import backend.agent.caducean_trajectory as _ct_module
import backend.agent.event_bus as _eb_module
from backend.agent.agent_kernel import AgentKernel
from backend.agent.der_constants import DER_MAX_UNVERIFIED_REPROPOSE
from backend.agent.der_loop import DirectorQueue, ExecutionMode, QueueItem
from backend.agent.evidence import assemble_evidence
from backend.memory.mycelium.navigator import SessionRegistry
from backend.memory.mycelium.store import CoordinateStore


# ---------------------------------------------------------------------------
# Minimal in-memory Mycelium schema (mirrors backend/memory/tests/
# test_mycelium_scorer.py's helpers) — only the two tables
# CoordinateStore/SessionRegistry actually touch.
# ---------------------------------------------------------------------------


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
            created_at REAL, last_traversed REAL
        );
        """
    )
    conn.commit()
    return conn


def _insert_node(conn: sqlite3.Connection, space_id: str = "toolpath", label: str = "n") -> str:
    nid = str(uuid.uuid4())
    coords = [0.5, 0.5, 0.5]
    blob = struct.pack(f">{len(coords)}f", *coords)
    now = time.time()
    conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,1,?,?,?)",
        (nid, space_id, blob, label, 0.7, now, now, now),
    )
    conn.commit()
    return nid


def _insert_edge(conn: sqlite3.Connection, from_id: str, to_id: str, score: float = 0.5) -> str:
    edge_id = str(uuid.uuid4())
    now = time.time()
    conn.execute(
        "INSERT INTO mycelium_edges "
        "(edge_id, from_node_id, to_node_id, score, edge_type, decay_rate, created_at, last_traversed) "
        "VALUES (?,?,?,?,'traversal',0.01,?,?)",
        (edge_id, from_id, to_id, score, now, now),
    )
    conn.commit()
    return edge_id


def _edge_score(conn: sqlite3.Connection, edge_id: str) -> float:
    row = conn.execute(
        "SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)
    ).fetchone()
    return row[0]


# ---------------------------------------------------------------------------
# Duck-typed stand-ins — only the surface _der_score_step_outcome and
# evidence.py's AVOID/prediction helpers actually touch (._store, ._registry,
# plus the episode write path AC4 depends on). Real CoordinateStore /
# SessionRegistry underneath, so score deltas and AVOID rows are real.
# ---------------------------------------------------------------------------


class _FakeMyc:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._store = CoordinateStore(conn)
        self._registry = SessionRegistry()


class _FakeMemoryInterface:
    """Enough of MemoryInterface's surface for _der_finalize_step to run
    without raising, plus the episode-store write AC4's AVOID path depends
    on. ``store_episode`` writes directly into an `episodes` table on the
    SAME connection real evidence.py._avoid_list reads, mirroring the shape
    EpisodicStore.store() persists (id/session/task/tool_sequence/type) —
    without pulling the encrypted, embedding-backed store into this test.
    """

    def __init__(self, myc: _FakeMyc) -> None:
        self._mycelium = myc
        self.session_id = "kernel-default-session"

    def mycelium_ingest_tool_call(self, **kw):
        pass

    def append_to_session(self, *a, **kw):
        pass

    def store_episode(self, episode) -> str:
        conn = self._mycelium._store._conn
        conn.execute(
            "CREATE TABLE IF NOT EXISTS episodes ("
            "id TEXT PRIMARY KEY, session_id TEXT, task_summary TEXT, "
            "full_content TEXT, tool_sequence TEXT, outcome_score REAL DEFAULT 0.0, "
            "outcome_type TEXT)"
        )
        eid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO episodes "
            "(id, session_id, task_summary, full_content, tool_sequence, outcome_type) "
            "VALUES (?,?,?,?,?,?)",
            (
                eid,
                episode.session_id,
                episode.task_summary,
                episode.full_content,
                json.dumps(episode.tool_sequence),
                episode.outcome_type,
            ),
        )
        conn.commit()
        return eid


class _NoOpRecorder:
    """Stub CaduceanTrajectoryRecorder — the commit ledger itself is
    REQ-1 AC1, already covered elsewhere; not re-tested here."""

    def __init__(self, *a, **kw):
        pass

    def record_commit(self, **kwargs):
        pass


class _NoOpBus:
    def emit(self, *a, **kw):
        pass


def _make_kernel(conn: sqlite3.Connection, verdict_label: str):
    myc = _FakeMyc(conn)
    k = AgentKernel.__new__(AgentKernel)
    k.conversation_id = "conv-scoring"
    k.session_id = "sess-scoring"
    k._memory_interface = _FakeMemoryInterface(myc)
    k._trailing_director = None
    k._mcm_orch = None
    k._der_last_u_mag = None
    k._der_work_units = 10
    k._der_live_cad_state = lambda session: {"u": 0.5, "xi": 0.1}
    k._split_step = lambda item, reason, cad, wu: []
    k._verify_step_result = lambda goal, expected, result: verdict_label
    return k, myc


def _finalize(kernel, item, result: str = "step output text long enough", success: bool = True):
    queue = DirectorQueue(objective="do the thing", items=[item])
    queue.mode = ExecutionMode.QUICK
    return kernel._der_finalize_step(
        item=item,
        step_result=result,
        step_success=success,
        step_outputs=[],
        completed_items=[],
        _tokens_used=0,
        _token_budget=10_000,
        _session="sess-scoring",
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
    # The commit-ledger write (REQ-1 AC1) is orthogonal to this file's
    # concern (the per-step scoring consequence) — stub it out exactly like
    # test_failed_step_writes_commit_row.py does, so a real sqlite3 backing
    # isn't needed for der_commits here.
    monkeypatch.setattr(_ct_module, "CaduceanTrajectoryRecorder", _NoOpRecorder)
    monkeypatch.setattr(_eb_module, "get_event_bus", lambda: _NoOpBus())


def _make_step_item(step_id: str, tool: str = "run_command", description: str = "do it") -> QueueItem:
    return QueueItem(
        step_id=step_id, step_number=1, description=description,
        tool=tool, params={}, critical=False,
        objective_anchor="do the thing", expected_output="done",
    )


class TestVerifiedStepHitScores:
    """REQ-1 AC2: VERIFIED steps remain hit-scored — no regression from
    adding UNVERIFIED/FAILED wiring."""

    def test_verified_step_applies_hit_delta(self):
        conn = _make_mem_conn()
        kernel, myc = _make_kernel(conn, "VERIFIED")
        n_from = _insert_node(conn)
        n_to = _insert_node(conn)
        edge_id = _insert_edge(conn, n_from, n_to, score=0.5)
        myc._registry.register("sess-scoring", [n_from])

        _finalize(kernel, _make_step_item("step-v1"))

        assert _edge_score(conn, edge_id) == pytest.approx(0.55, abs=1e-6), (
            "VERIFIED must still hit-score (EdgeScorer +0.05) — no regression"
        )


class TestUnverifiedPartialCreditAndCap:
    """REQ-1 AC3: +0.02 partial credit, capped at
    DER_MAX_UNVERIFIED_REPROPOSE + 1 scored attempts per step_id."""

    def test_unverified_step_applies_partial_credit(self):
        conn = _make_mem_conn()
        kernel, myc = _make_kernel(conn, "UNVERIFIED")
        n_from = _insert_node(conn)
        n_to = _insert_node(conn)
        edge_id = _insert_edge(conn, n_from, n_to, score=0.5)
        myc._registry.register("sess-scoring", [n_from])

        _finalize(kernel, _make_step_item("step-u1"))

        assert _edge_score(conn, edge_id) == pytest.approx(0.52, abs=1e-6), (
            "UNVERIFIED must apply the +0.02 partial-credit delta (REQ-1 AC3)"
        )

    def test_repropose_cap_blocks_further_credit(self):
        """Drive the SAME step_id past the cap and assert no further credit
        accrues — the load-bearing part of AC3. Without this cap an
        UNVERIFIED step could be re-proposed indefinitely to farm +0.02
        edge score forever."""
        conn = _make_mem_conn()
        kernel, myc = _make_kernel(conn, "UNVERIFIED")
        n_from = _insert_node(conn)
        n_to = _insert_node(conn)
        edge_id = _insert_edge(conn, n_from, n_to, score=0.5)
        myc._registry.register("sess-scoring", [n_from])

        item = _make_step_item("step-u-cap")

        # Attempt 1 (the original commit) — scores.
        _finalize(kernel, item)
        after_1 = _edge_score(conn, edge_id)
        assert after_1 == pytest.approx(0.52, abs=1e-6)

        # Attempt 2 (the one permitted re-propose, DER_MAX_UNVERIFIED_REPROPOSE=1)
        # — scores again.
        _finalize(kernel, item)
        after_2 = _edge_score(conn, edge_id)
        assert after_2 == pytest.approx(0.54, abs=1e-6)

        # Attempt 3 — past the cap. Must NOT accrue further credit.
        _finalize(kernel, item)
        after_3 = _edge_score(conn, edge_id)
        assert after_3 == after_2, (
            f"re-propose cap (DER_MAX_UNVERIFIED_REPROPOSE={DER_MAX_UNVERIFIED_REPROPOSE}) "
            "must block scoring past the cap, else an UNVERIFIED step could farm "
            "partial credit forever — the exact reward-hack this phase closes"
        )

        # Attempt 4 — still capped (monotonic, not a one-off off-by-one).
        _finalize(kernel, item)
        assert _edge_score(conn, edge_id) == after_2


class TestFailedStepMissScoresAndAvoids:
    """REQ-1 AC4: -0.08 miss delta, and the outcome reaches the tier-3 AVOID
    header (evidence.py's real, unmodified assemble_evidence)."""

    def test_failed_step_applies_miss_delta(self):
        conn = _make_mem_conn()
        kernel, myc = _make_kernel(conn, "FAILED")
        n_from = _insert_node(conn)
        n_to = _insert_node(conn)
        edge_id = _insert_edge(conn, n_from, n_to, score=0.5)
        myc._registry.register("sess-scoring", [n_from])

        _finalize(kernel, _make_step_item("step-f1"), result="it did not work")

        assert _edge_score(conn, edge_id) == pytest.approx(0.42, abs=1e-6), (
            "FAILED must apply the -0.08 miss delta (REQ-1 AC4)"
        )

    def test_failed_step_appears_in_avoid_header(self):
        conn = _make_mem_conn()
        kernel, myc = _make_kernel(conn, "FAILED")
        n_from = _insert_node(conn)
        n_to = _insert_node(conn)
        _insert_edge(conn, n_from, n_to, score=0.5)
        myc._registry.register("sess-scoring", [n_from])

        _finalize(
            kernel,
            _make_step_item("step-f2", tool="fetch_widgets", description="fetch the widget report"),
            result="fetch_widgets: connection refused",
        )

        block = assemble_evidence(
            goal="fetch the widget report",
            session_id="sess-scoring",
            myc=myc,
            memory_interface=None,
        )
        avoid_lines = [ln for ln in block.splitlines() if ln.startswith("AVOID")]
        assert avoid_lines, "assemble_evidence must always render an AVOID line"
        assert "fetch_widgets" in avoid_lines[0], (
            "a FAILED step must surface its tool in the AVOID/tier-3 header so "
            f"it is actually avoided next time, got: {avoid_lines[0]!r}"
        )

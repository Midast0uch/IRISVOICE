"""CT: REQ-20 trajectory-recorder binding — application store, not build memory.

Spec: specs/long-horizon-der-execution/requirements.md REQ-20.
Task: T38 — application-store write assertion test.

What this pins:
  AC3: a DER commit recorded through the application's normal call path
       (`get_trajectory_recorder(memory_interface).record_commit(...)` — the
       exact call agent_kernel.py:8244 now makes) lands in the APPLICATION
       store's commit table, NOT in `.mcm/coordinates.db` (the BUILD-memory DB
       that previously received every bare-constructed recorder's writes).
  AC2: bare `CaduceanTrajectoryRecorder()` construction now FAILS LOUDLY
       (ValueError) instead of silently binding to MCM_DB_PATH/.mcm.
  Edge: when `episodic.db` is unopenable, `get_trajectory_recorder` returns the
       no-op recorder (pin_42ddd255162d) — writes are no-ops, never a fallback
       to the build DB, and never a crash.

Run: python -m pytest backend/tests/contract/test_trajectory_recorder_binding.py -v
"""
from __future__ import annotations

import os
import sqlite3
import uuid

import pytest

from backend.agent.caducean_trajectory import (
    CaduceanTrajectoryRecorder,
    _NoopTrajectoryRecorder,
    get_trajectory_recorder,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
_BUILD_DB = os.path.join(_REPO_ROOT, ".mcm", "coordinates.db")


class _FakeEpisodic:
    """Stand-in for MemoryInterface.episodic whose .db is a real sqlite conn."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)

    @property
    def db(self):
        return self._conn


class _FakeMemoryInterface:
    """Shape-matches the real MemoryInterface surface the recorder reads."""

    def __init__(self, db_path: str):
        self.episodic = _FakeEpisodic(db_path)


class _BrokenEpisodic:
    """episodic whose .db raises — the unopenable-store edge case."""

    @property
    def db(self):
        raise RuntimeError("episodic store unopenable")


class _BrokenMemoryInterface:
    episodic = _BrokenEpisodic()


@pytest.fixture
def app_store(tmp_path):
    """A temp sqlite file standing in for backend/data/memory.db."""
    return str(tmp_path / "memory.db")


def _build_db_session_ids() -> set:
    if not os.path.exists(_BUILD_DB):
        return set()
    conn = sqlite3.connect(_BUILD_DB)
    try:
        rows = conn.execute("SELECT session_id FROM der_commits").fetchall()
        return {r[0] for r in rows}
    except sqlite3.OperationalError:
        return set()
    finally:
        conn.close()


class TestRecorderAppStoreBinding:
    def test_commit_writes_to_application_store_not_build_db(self, app_store):
        """AC3: the normal application call path writes the commit row to the
        application store and never to .mcm/coordinates.db."""
        mi = _FakeMemoryInterface(app_store)
        session_id = f"sess-req20-{uuid.uuid4().hex[:8]}"
        before = _build_db_session_ids()

        recorder = get_trajectory_recorder(mi)
        recorder.record_commit(
            session_id=session_id,
            step_id="step-1",
            commit_hash="abc123",
            message="REQ-20 binding test commit",
            u=0.5,
            xi=0.2,
            verified_label="VERIFIED",
        )

        # The commit row is in the APPLICATION store (the memory_interface conn).
        app_rows = mi.episodic.db.execute(
            "SELECT session_id, step_id, verified_label FROM der_commits "
            "WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        assert len(app_rows) == 1
        assert app_rows[0][0] == session_id
        assert app_rows[0][1] == "step-1"
        assert app_rows[0][2] == "VERIFIED"

        # And NOT in the BUILD-memory database.
        after = _build_db_session_ids()
        assert session_id not in after
        assert after == before

    def test_recorder_uses_the_memory_interface_conn(self, app_store):
        """The recorder binds to the SAME conn the MemoryInterface exposes — it
        does not open its own separate database."""
        mi = _FakeMemoryInterface(app_store)
        recorder = get_trajectory_recorder(mi)
        assert recorder._conn is mi.episodic.db

    def test_bare_construction_fails_loudly(self):
        """AC2: constructing without a connection raises instead of silently
        writing to the BUILD-memory .mcm/coordinates.db."""
        with pytest.raises(ValueError, match="get_trajectory_recorder"):
            CaduceanTrajectoryRecorder()

    def test_unopenable_store_degrades_to_noop(self, app_store):
        """Edge (pin_42ddd255162d): an unopenable episodic store yields the
        no-op recorder; writes are no-ops, no crash, no build-DB write."""
        before = _build_db_session_ids()
        mi = _BrokenMemoryInterface()
        recorder = get_trajectory_recorder(mi)
        assert isinstance(recorder, _NoopTrajectoryRecorder)

        session_id = f"sess-req20-noop-{uuid.uuid4().hex[:8]}"
        recorder.record_commit(
            session_id=session_id,
            step_id="step-1",
            commit_hash="x",
            message="noop",
            verified_label="FAILED",
        )
        recorder.record_session_exit(
            session_id=session_id,
            domain="general",
            natural_exit=True,
        )
        assert recorder.get_session_exits() == []
        assert recorder.get_latest_coordinate(session_id) is None

        after = _build_db_session_ids()
        assert session_id not in after
        assert after == before

    def test_application_call_sites_pass_explicit_binding(self):
        """The no-op path never selects the build DB as a silent fallback."""
        mi = _BrokenMemoryInterface()
        recorder = get_trajectory_recorder(mi)
        # No silent .mcm/coordinates.db conn anywhere on this recorder.
        assert not hasattr(recorder, "_conn") or recorder._conn is None

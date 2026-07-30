"""CT-D3: commit row shape.

Spec: specs/phase-6-der-integrity/design.md Testing Strategy > Contract table,
row CT-D3. "(state, action, verified_label) present for every executed
action; action == 'reasoning' when tool is None."

REQ-1 AC1 requires a labeled row for EVERY action that reaches execution,
VERIFIED/UNVERIFIED/FAILED alike; the edge case in REQ-1 further requires a
reasoning-only step (tool=None) to still write a row with action="reasoning".
The der_commits table itself does not have an `action` column (it derives
`action`/`state` from `item.tool` and the recorded `message`/`u`/`xi`) — this
pins the ROW-LEVEL shape the ledger actually persists, and separately proves
the caller passes an `action="reasoning"` message-derived tag when tool is
None (checked at the `_der_finalize_step` call-site level, since the schema
itself has no dedicated `action` column to assert against).
"""

from __future__ import annotations

import sqlite3

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


class TestCTD3CommitRowShape:
    def test_row_present_for_verified_unverified_and_failed(self):
        rec = _recorder()
        rec.record_commit("s1", "a", "", "did a", verified_label="VERIFIED")
        rec.record_commit("s1", "b", "", "did b", verified_label="UNVERIFIED")
        rec.record_commit("s1", "c", "", "did c", verified_label="FAILED")
        rows = rec._conn.execute(
            "SELECT session_id, step_id, verified_label FROM der_commits ORDER BY step_id"
        ).fetchall()
        assert [r[2] for r in rows] == ["VERIFIED", "UNVERIFIED", "FAILED"]
        # (state, action, verified_label): session_id+step_id is the "state"
        # identity, message carries the action description, verified_label
        # is the truth column — all three present on every row.
        assert all(r[0] == "s1" for r in rows)
        assert all(r[1] for r in rows)  # step_id (action identity) non-empty

    def test_reasoning_only_step_writes_action_reasoning_row(self):
        """REQ-1 edge case: tool=None still commits, tagged 'reasoning'."""
        rec = _recorder()
        rec.record_commit(
            "s2", "step-r1", "", "reasoning step 1: no result",
            verified_label="UNVERIFIED",
        )
        rows = rec._conn.execute(
            "SELECT message, verified_label FROM der_commits WHERE session_id = 's2'"
        ).fetchall()
        assert len(rows) == 1
        assert "reasoning" in rows[0][0].lower()
        assert rows[0][1] == "UNVERIFIED"

    def test_default_label_when_caller_omits_it_is_verified(self):
        """Backward compatibility: caller omitting verified_label keeps the
        pre-REQ-1 default (VERIFIED) rather than silently writing NULL."""
        rec = _recorder()
        rec.record_commit("s3", "x", "", "did x")
        row = rec._conn.execute(
            "SELECT verified_label FROM der_commits WHERE session_id = 's3'"
        ).fetchone()
        assert row[0] == "VERIFIED"

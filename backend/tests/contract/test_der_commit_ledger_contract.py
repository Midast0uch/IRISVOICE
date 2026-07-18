"""Contract tests: honest DER commit ledger (REQ-1 / audit B fix).

Verifies the G5 ledger writes a (state, action, verified_label) triple for
EVERY executed action — VERIFIED, UNVERIFIED, and FAILED alike. The old
contract gated the write on VERIFIED, which starved the failure-learning
channel (edge miss-scoring, AVOID headers). The contract now pins the
label column so a FAILED step is recorded, not silently dropped.

Spec: specs/der-loop-integrity-display/requirements.md REQ-1.
"""

from __future__ import annotations

import sqlite3

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


class TestCommitLedgerRecordsAllLabels:
    def test_verified_commit_has_label(self):
        rec = _recorder()
        rec.record_commit("s1", "step-1", "", "did thing", verified_label="VERIFIED")
        rows = rec._conn.execute(
            "SELECT verified_label, message FROM der_commits"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "VERIFIED"
        # The label column carries the truth; message is caller-supplied.
        assert rows[0][1] == "did thing"

    def test_failed_commit_is_recorded_not_dropped(self):
        """Audit B: a FAILED step must write a ledger entry (was silently dropped)."""
        rec = _recorder()
        rec.record_commit("s1", "step-9", "", "risky thing", verified_label="FAILED")
        rows = rec._conn.execute(
            "SELECT verified_label FROM der_commits"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "FAILED"

    def test_unverified_commit_is_recorded(self):
        rec = _recorder()
        rec.record_commit(
            "s1", "step-3", "", "partial thing", verified_label="UNVERIFIED"
        )
        rows = rec._conn.execute(
            "SELECT verified_label FROM der_commits"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "UNVERIFIED"

    def test_default_label_is_verified(self):
        """Backward-compatible default keeps VERIFIED when caller omits the label."""
        rec = _recorder()
        rec.record_commit("s1", "step-1", "", "did thing")
        rows = rec._conn.execute(
            "SELECT verified_label FROM der_commits"
        ).fetchall()
        assert rows[0][0] == "VERIFIED"

    def test_session_exit_carries_verified_count(self):
        """REQ-2: verified_count is derived from the commit ledger for the gate."""
        rec = _recorder()
        rec.record_commit("sX", "a", "", "a", verified_label="VERIFIED")
        rec.record_commit("sX", "b", "", "b", verified_label="FAILED")
        rec.record_session_exit("sX", "general", natural_exit=True)
        rows = rec._conn.execute(
            "SELECT verified_count, tokens_total FROM caducean_session_exits"
        ).fetchall()
        assert len(rows) == 1
        # 1 VERIFIED of 2 total steps.
        assert rows[0][0] == 1

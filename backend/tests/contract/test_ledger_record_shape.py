"""Contract test CT-I7: ledger record — verified_label present for all
outcomes; the outer loop's input unchanged.

design.md: pins two things Phase 2 must not regress while it reshapes the
card/narration layer sitting on top of the DER commit ledger:
  1. `record_commit()` writes a `verified_label` for EVERY outcome
     (VERIFIED / UNVERIFIED / FAILED alike) — the honest audit trail the
     outer loop and the AVOID/edge-miss path consume.
  2. `record_session_exit()`'s parameter shape — the outer loop's *input* —
     is unchanged, and `verified_count` / `executed_steps` are still derived
     from that SAME honest ledger (not a separately-tracked counter that
     could drift from it).

Asserts the EFFECT (rows actually written to the ledger tables), not the
computation.
"""

from __future__ import annotations

import inspect
import sqlite3

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder

EXPECTED_EXIT_PARAMS = {
    "session_id", "domain", "natural_exit", "route_score", "drift",
    "tokens_total", "verified_count", "executed_steps",
}


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


class TestLedgerRecordShape:
    def test_every_outcome_label_is_recorded(self):
        rec = _recorder()
        for label in ("VERIFIED", "UNVERIFIED", "FAILED"):
            rec.record_commit("sX", f"step-{label}", "", "did thing", verified_label=label)
        rows = rec._conn.execute(
            "SELECT verified_label FROM der_commits ORDER BY rowid"
        ).fetchall()
        assert {r[0] for r in rows} == {"VERIFIED", "UNVERIFIED", "FAILED"}, (
            f"not every outcome label reached the ledger: {rows}"
        )

    def test_record_session_exit_input_shape_unchanged(self):
        """The outer loop's input: if a param is renamed or dropped, the outer
        loop silently stops receiving what it was tuned against."""
        sig = inspect.signature(CaduceanTrajectoryRecorder.record_session_exit)
        assert EXPECTED_EXIT_PARAMS.issubset(set(sig.parameters.keys())), (
            f"record_session_exit signature changed: {set(sig.parameters.keys())}"
        )

    def test_verified_count_derives_from_the_same_ledger_it_reports_on(self):
        rec = _recorder()
        rec.record_commit("sX", "a", "", "a", verified_label="VERIFIED")
        rec.record_commit("sX", "b", "", "b", verified_label="FAILED")
        rec.record_commit("sX", "c", "", "c", verified_label="VERIFIED")
        rec.record_session_exit("sX", "general", natural_exit=True)
        rows = rec._conn.execute(
            "SELECT verified_count, tokens_total FROM caducean_session_exits"
        ).fetchall()
        assert len(rows) == 1
        # 2 VERIFIED of 3 total steps recorded above.
        assert rows[0][0] == 2, (
            f"verified_count ({rows[0][0]}) does not match the honest der_commits "
            f"ledger (2 VERIFIED of 3) — outer-loop input has drifted from its "
            f"source of truth."
        )

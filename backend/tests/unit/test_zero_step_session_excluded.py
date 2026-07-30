"""Unit test: a zero-step held-out session is NEUTRAL, not 1.0 (REQ-2 AC6, D-1).

Spec: specs/phase-6-der-integrity/requirements.md REQ-2 AC6.

D-1: counting a fresh (zero-executed-step) session as 1.0 is exactly the
dead-branch behaviour this phase repairs (`vf_sum += 1.0 if vc == 0 else 1.0`
in outer_loop.py:136), and it is wrong in the direction that HIDES
degradation — several fresh sessions in a held-out batch would drag the
mean toward 1.0 and mask a real drop elsewhere in the batch. This test
asserts the zero-step session changes the mean NOT AT ALL: adding it to a
batch must leave `verified_fraction` identical to the batch without it.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.outer_loop import OuterTuner


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


def _seed_session(rec: CaduceanTrajectoryRecorder, session_id: str, labels: list) -> None:
    for i, label in enumerate(labels):
        rec.record_commit(session_id, f"{session_id}-step{i}", "", "step done",
                           verified_label=label)
    rec.record_session_exit(session_id, "general", natural_exit=True)


def _seed_zero_step_session(rec: CaduceanTrajectoryRecorder, session_id: str) -> None:
    """A session that exited with NO executed steps at all — no der_commits row."""
    rec.record_session_exit(session_id, "general", natural_exit=True)


class TestZeroStepSessionExcluded:
    def test_zero_step_session_does_not_move_the_mean(self):
        rec_without = _recorder()
        _seed_session(rec_without, "s0", ["VERIFIED"])
        _seed_session(rec_without, "s1", ["VERIFIED", "FAILED"])
        tuner_without = OuterTuner(recorder=rec_without, held_out_count=2)
        held_out_without = tuner_without._heldout_batch(tuner_without._ledger()["exits"])
        baseline = tuner_without._score(held_out_without)["verified_fraction"]

        rec_with = _recorder()
        _seed_session(rec_with, "s0", ["VERIFIED"])
        _seed_session(rec_with, "s1", ["VERIFIED", "FAILED"])
        _seed_zero_step_session(rec_with, "s2")  # the fresh, zero-step session
        tuner_with = OuterTuner(recorder=rec_with, held_out_count=3)
        held_out_with = tuner_with._heldout_batch(tuner_with._ledger()["exits"])
        with_zero = tuner_with._score(held_out_with)["verified_fraction"]

        assert with_zero == pytest.approx(baseline), (
            f"adding a zero-step session moved verified_fraction from "
            f"{baseline} to {with_zero} — it must be excluded (neutral), not "
            f"counted as a 1.0 vote that drags the mean up"
        )

    def test_zero_step_session_is_not_counted_as_zero_either(self):
        """D-1: neutral means EXCLUDED, not 0.0 either — a batch of ONLY
        zero-step sessions must not read as a verified_fraction of 0.0 (that
        would falsely look like total failure when nothing was even tried)."""
        rec = _recorder()
        _seed_zero_step_session(rec, "s0")
        _seed_zero_step_session(rec, "s1")
        _seed_zero_step_session(rec, "s2")
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        metrics, live = tuner._score_with_liveness(held_out)
        # No session had an executed step -> the guard has no input at all;
        # it must report as UNAVAILABLE (REQ-6 AC5), not as "0.0 measured".
        assert live["verified_fraction"] is False

    def test_all_natural_exit_but_mixed_depth_takes_neutral_value(self):
        """A batch mixing a real session with a zero-step session still
        reports the REAL session's ratio — proves exclusion, not averaging
        the zero-step session in as a 0.5 vote or similar."""
        rec = _recorder()
        _seed_session(rec, "s0", ["VERIFIED", "VERIFIED"])  # ratio 1.0
        _seed_zero_step_session(rec, "s1")
        tuner = OuterTuner(recorder=rec, held_out_count=2)
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        score = tuner._score(held_out)
        assert score["verified_fraction"] == pytest.approx(1.0)

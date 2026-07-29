"""Unit test: `verified_fraction` is a REAL ratio, not a constant (REQ-2 AC5).

This is the DIRECT regression test for the defect at outer_loop.py:136 —
`vf_sum += 1.0 if vc == 0 else 1.0` — where BOTH ternary branches were `1.0`,
so the value was always exactly 1.0 regardless of input. A single-batch test
would pass against that bug (1.0 == 1.0 looks fine in isolation); this test is
parametrized over SEVERAL DISTINCT held-out batches and asserts the computed
value takes more than one value AND matches the real ratio for each batch.

Spec: specs/phase-6-der-integrity/requirements.md REQ-2 AC5.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.outer_loop import OuterTuner


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


def _seed_session(rec: CaduceanTrajectoryRecorder, session_id: str, labels: list) -> None:
    """Write one der_commits row per label, then close the session. Both
    verified_count and executed_steps are derived from these rows (the honest
    ledger), never passed as a literal."""
    for i, label in enumerate(labels):
        rec.record_commit(session_id, f"{session_id}-step{i}", "", "step done",
                           verified_label=label)
    rec.record_session_exit(session_id, "general", natural_exit=True)


class TestVerifiedFractionIsNotConstant:
    @pytest.mark.parametrize(
        "batch_labels, expected_ratio",
        [
            ([["VERIFIED"], ["VERIFIED"], ["VERIFIED"]], 1.0),
            ([["VERIFIED", "FAILED"], ["VERIFIED", "FAILED"], ["VERIFIED", "FAILED"]], 0.5),
            ([["FAILED", "FAILED"], ["UNVERIFIED", "FAILED"], ["FAILED"]], 0.0),
        ],
    )
    def test_each_batch_matches_its_real_ratio(self, batch_labels, expected_ratio):
        rec = _recorder()
        for i, labels in enumerate(batch_labels):
            _seed_session(rec, f"s{i}", labels)
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        score = tuner._score(held_out)
        assert score["verified_fraction"] == pytest.approx(expected_ratio)

    def test_verified_fraction_takes_more_than_one_value_across_batches(self):
        """The direct regression test: a batch-to-batch comparison. If BOTH
        ternary branches were 1.0 (the historical bug), every batch below
        would compute to the SAME 1.0 — this asserts they do not."""
        results = []
        for batch_labels in (
            [["VERIFIED"], ["VERIFIED"], ["VERIFIED"]],
            [["VERIFIED", "FAILED"], ["VERIFIED", "FAILED"], ["VERIFIED", "FAILED"]],
            [["FAILED", "FAILED"], ["UNVERIFIED", "FAILED"], ["FAILED"]],
        ):
            rec = _recorder()
            for i, labels in enumerate(batch_labels):
                _seed_session(rec, f"s{i}", labels)
            tuner = OuterTuner(recorder=rec, held_out_count=3)
            held_out = tuner._heldout_batch(tuner._ledger()["exits"])
            results.append(tuner._score(held_out)["verified_fraction"])
        assert len(set(results)) > 1, (
            f"verified_fraction took only {set(results)} across distinct "
            "batches — both ternary branches were 1.0 (the historical bug) "
            "would produce exactly this failure"
        )
        assert results == [pytest.approx(1.0), pytest.approx(0.5), pytest.approx(0.0)]

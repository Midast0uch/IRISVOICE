"""Unit test: `tokens_per_verified` is non-zero and varies with the batch
(REQ-2 AC4).

Spec: specs/phase-6-der-integrity/requirements.md REQ-2 AC4.

This is the direct regression test for the SECOND dead branch:
`tpv_sum += (tt / vc) if vc > 0 else 0.0` in outer_loop.py:137 was always
0.0 because the only production caller of `record_session_exit`
(memory.py:329-336) omitted `tokens_total`, so it defaulted to 0.0 — the
FORMULA was fine, the CALLER never supplied a non-zero input (tasks.md T1.3
RIPPLE). This test seeds `tokens_total` directly through the recorder (the
formula's contract), proving the metric is live once the input is populated,
and that it VARIES across distinct batches rather than being pinned to one
value.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.outer_loop import OuterTuner


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


class TestTokensPerVerifiedNonzero:
    def test_nonzero_with_populated_tokens_total(self):
        rec = _recorder()
        rec.record_session_exit(
            "s0", "general", natural_exit=True, verified_count=5, tokens_total=5000.0,
        )
        rec.record_session_exit(
            "s1", "general", natural_exit=True, verified_count=5, tokens_total=5000.0,
        )
        rec.record_session_exit(
            "s2", "general", natural_exit=True, verified_count=5, tokens_total=5000.0,
        )
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        score = tuner._score(held_out)
        assert score["tokens_per_verified"] == pytest.approx(1000.0)
        assert score["tokens_per_verified"] > 0.0

    def test_varies_across_distinct_batches(self):
        """The direct regression test: if the caller still omitted
        tokens_total (the historical bug), every batch below would compute
        to the SAME 0.0 — this asserts they do not."""
        results = []
        for tokens_total, verified_count in ((5000.0, 5), (20000.0, 5), (1000.0, 2)):
            rec = _recorder()
            rec.record_session_exit(
                "s0", "general", natural_exit=True,
                verified_count=verified_count, tokens_total=tokens_total,
            )
            rec.record_session_exit(
                "s1", "general", natural_exit=True,
                verified_count=verified_count, tokens_total=tokens_total,
            )
            rec.record_session_exit(
                "s2", "general", natural_exit=True,
                verified_count=verified_count, tokens_total=tokens_total,
            )
            tuner = OuterTuner(recorder=rec, held_out_count=3)
            held_out = tuner._heldout_batch(tuner._ledger()["exits"])
            results.append(tuner._score(held_out)["tokens_per_verified"])
        assert len(set(results)) > 1, (
            f"tokens_per_verified took only {set(results)} across distinct "
            "batches — the historical bug (tokens_total defaulting to 0.0 "
            "because the caller omitted it) would produce exactly this "
            "failure: every batch reading 0.0"
        )
        assert all(r > 0.0 for r in results)

    def test_session_with_zero_verified_steps_excluded_from_mean(self):
        """A session with tokens spent but zero VERIFIED steps has an
        undefined tokens_per_verified for THAT session — it must not
        silently contribute 0.0 and pull the batch mean toward zero."""
        rec = _recorder()
        rec.record_session_exit(
            "s0", "general", natural_exit=True, verified_count=5, tokens_total=5000.0,
        )
        rec.record_session_exit(
            "s1", "general", natural_exit=False, verified_count=0, tokens_total=9000.0,
        )
        tuner = OuterTuner(recorder=rec, held_out_count=2)
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        score = tuner._score(held_out)
        # Only s0 contributes: 5000/5 = 1000, NOT averaged with a phantom 0.0
        # for s1 (which would give 500).
        assert score["tokens_per_verified"] == pytest.approx(1000.0)

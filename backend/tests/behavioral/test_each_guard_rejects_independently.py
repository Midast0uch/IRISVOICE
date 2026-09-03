"""Behavioral: each of the three compound-gate guards can reject INDEPENDENTLY
(REQ-2 AC7). THE ACCEPTANCE TEST FOR PHASE 6.

Spec: specs/phase-6-der-integrity/requirements.md REQ-2 AC7.

Parametrized over all THREE guards. For each one: construct a proposal that
IMPROVES the other two and DEGRADES exactly the one under test, then assert
the compound gate rejects it. Dropping a guard from this parametrize list is
itself a test modification — and it is EXACTLY how two dead guards survived
for months: a compound gate tested only end-to-end passes with two dead
branches, because the one live guard (`natural_exit_rate`) alone was enough
to make `_compound_accepts` return True or False in every historical test.
Testing each guard in isolation is the only way to prove a specific guard,
not just the gate as a whole, can veto.

This drives the REAL `OuterTuner` through `_score_with_liveness` +
`_compound_accepts` on a seeded ledger — not a hand-built metrics dict — so
the assertion exercises the same path production code does.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.outer_loop import OuterTuner


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


def _seed_healthy_batch(rec: CaduceanTrajectoryRecorder) -> None:
    """A healthy baseline: not all-natural (so natural_exit_rate has room to
    improve), decent verified_fraction, moderate tokens_per_verified.
    `executed_steps` is passed explicitly (>0) so verified_fraction has a
    real denominator instead of falling back to the empty der_commits table.
    """
    rec.record_session_exit(
        "s0", "general", natural_exit=True, verified_count=8,
        tokens_total=8000.0, executed_steps=10,
    )
    rec.record_session_exit(
        "s1", "general", natural_exit=True, verified_count=8,
        tokens_total=8000.0, executed_steps=10,
    )
    rec.record_session_exit(
        "s2", "general", natural_exit=False, verified_count=8,
        tokens_total=8000.0, executed_steps=10,
    )


class TestEachGuardRejectsIndependently:
    @pytest.mark.parametrize(
        "degraded_guard",
        ["natural_exit_rate", "verified_fraction", "tokens_per_verified"],
    )
    def test_degrading_exactly_one_guard_rejects_the_proposal(self, degraded_guard):
        rec = _recorder()
        _seed_healthy_batch(rec)
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        baseline, live = tuner._score_with_liveness(held_out)
        assert all(live.values()), "fixture must make all three guards live"

        proposed = dict(baseline)
        # Improve the OTHER two, degrade exactly the guard under test.
        if degraded_guard != "natural_exit_rate":
            proposed["natural_exit_rate"] = min(1.0, baseline["natural_exit_rate"] + 0.2)
        if degraded_guard != "verified_fraction":
            proposed["verified_fraction"] = min(1.0, baseline["verified_fraction"] + 0.2)
        if degraded_guard != "tokens_per_verified":
            proposed["tokens_per_verified"] = max(0.0, baseline["tokens_per_verified"] - 500.0)

        if degraded_guard == "natural_exit_rate":
            proposed["natural_exit_rate"] = max(0.0, baseline["natural_exit_rate"] - 0.2)
        elif degraded_guard == "verified_fraction":
            proposed["verified_fraction"] = max(0.0, baseline["verified_fraction"] - 0.3)
        elif degraded_guard == "tokens_per_verified":
            proposed["tokens_per_verified"] = baseline["tokens_per_verified"] + 3000.0

        guards = OuterTuner._evaluate_guards(proposed, baseline, live)
        deciding = next(g for g in guards if g.name == degraded_guard)
        assert deciding.passed is False, (
            f"{degraded_guard} must independently reject when it alone is "
            f"degraded (baseline={baseline[degraded_guard]!r}, "
            f"proposed={proposed[degraded_guard]!r})"
        )
        others_pass = [g for g in guards if g.name != degraded_guard]
        assert all(g.passed for g in others_pass), (
            "the other two guards must PASS in this scenario, proving the "
            f"rejection traces to {degraded_guard} alone, not a coincidental "
            "failure elsewhere"
        )
        assert OuterTuner._compound_accepts(proposed, baseline, live) is False

    def test_improving_all_three_is_accepted(self):
        """Control case: when none is degraded, the gate accepts — proves the
        rejections above are not a gate that rejects everything."""
        rec = _recorder()
        _seed_healthy_batch(rec)
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        baseline, live = tuner._score_with_liveness(held_out)
        proposed = dict(baseline)
        proposed["natural_exit_rate"] = min(1.0, baseline["natural_exit_rate"] + 0.1)
        assert OuterTuner._compound_accepts(proposed, baseline, live) is True

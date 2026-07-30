"""Behavioral: the "never split" hack is REJECTED BY THE GATE, not merely
absent from the candidate list (REQ-4).

Spec: specs/phase-6-der-integrity/requirements.md REQ-4.

Before this phase, `_PROPOSALS["U_SPLIT"]` was `[0.4, 0.5, 0.6, 0.7]` —
`U_SPLIT <= 0.0` (the value that makes `abs(u) < U_SPLIT` false for every
real `u`, so the DER loop NEVER splits again) could not even be proposed.
The acceptance criterion the compound gate is named for ("reject the never-
split hack") had therefore never been exercised: the guard was ASSUMED, not
PROVEN (design.md's framing). REQ-4 AC1 puts the value in the candidate
list; this test proves AC2/AC3 — the gate rejects it because it wins
`natural_exit_rate` (never doing the hard part raises the exit rate) and
loses `verified_fraction` (skipping splits starves the recovery path that
turns FAILED/UNVERIFIED steps into VERIFIED ones).
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.outer_loop import _PROPOSALS, OuterTuner


class TestNeverSplitRejected:
    def test_never_split_value_is_in_the_candidate_list(self):
        """REQ-4 AC1: the hack must be PRESENT, not merely impossible to
        reach — this is a standing regression guard against re-removing it
        to make some other test green (tasks.md T2.3 RIPPLE)."""
        assert 0.0 in _PROPOSALS["U_SPLIT"], (
            "the 'never split' candidate must be present in _PROPOSALS so "
            "the gate is exercised against it, not merely assumed to reject "
            "it if it ever showed up"
        )

    def test_zero_is_provably_past_the_split_point(self):
        """OQ-2: U_SPLIT <= 0.0 must be provably past the point where a
        split can occur, given the `abs(u) < U_SPLIT` comparison. abs(u) is
        never negative, so `abs(u) < 0.0` is false for EVERY real u — not
        just usually false."""
        import random

        for _ in range(2000):
            u = random.uniform(-10.0, 10.0)
            assert not (abs(u) < 0.0), (
                f"abs({u}) < 0.0 was True — U_SPLIT=0.0 is not actually "
                "past the point where a split can occur"
            )

    def test_never_split_wins_natural_exit_loses_verified_fraction_and_is_rejected(self):
        """REQ-4 AC2/AC3: construct the exact hack shape — natural_exit_rate
        UP, verified_fraction DOWN — and assert the compound gate rejects
        it. This mirrors design.md's sequence diagram."""
        rec = CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))
        # Healthy-but-imperfect baseline (natural_exit_rate has headroom).
        rec.record_session_exit(
            "s0", "general", natural_exit=True, verified_count=8,
            tokens_total=5000.0, executed_steps=10,
        )
        rec.record_session_exit(
            "s1", "general", natural_exit=True, verified_count=8,
            tokens_total=5000.0, executed_steps=10,
        )
        rec.record_session_exit(
            "s2", "general", natural_exit=False, verified_count=8,
            tokens_total=5000.0, executed_steps=10,
        )
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        held_out = tuner._heldout_batch(tuner._ledger()["exits"])
        baseline, live = tuner._score_with_liveness(held_out)

        # The hack's SHAPE: never splitting means the loop exits "naturally"
        # more often (it never enters the hard recovery path), but the steps
        # that would have been fixed by a split now stay UNVERIFIED/FAILED,
        # dropping verified_fraction.
        hacked = dict(baseline)
        hacked["natural_exit_rate"] = min(1.0, baseline["natural_exit_rate"] + 0.2)
        hacked["verified_fraction"] = max(0.0, baseline["verified_fraction"] - 0.4)

        guards = OuterTuner._evaluate_guards(hacked, baseline, live)
        vf_guard = next(g for g in guards if g.name == "verified_fraction")
        assert vf_guard.passed is False
        assert OuterTuner._compound_accepts(hacked, baseline, live) is False

    def test_never_split_is_the_first_proposed_candidate_from_default_params(self):
        """With DEFAULT_PARAMS (U_SPLIT=0.5) as the current value, 0.0 is the
        first candidate that differs — so `_propose_one` actually surfaces
        it as a live proposal, not a value the tuner would skip past."""
        rec = CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))
        for i in range(4):
            rec.record_session_exit(
                f"s{i}", "general", natural_exit=True, verified_count=5,
                tokens_total=5000.0, executed_steps=10,
            )
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        proposal = tuner._propose_one()
        assert proposal == ("U_SPLIT", 0.0)

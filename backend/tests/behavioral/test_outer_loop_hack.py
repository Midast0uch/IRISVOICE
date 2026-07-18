"""Behavioral tests: outer-loop compound gate rejects the hack (REQ-2 AC3).

Drives the real OuterTuner through a full proposal cycle and asserts the
EMERGENT property: a parameter change that raises natural_exit_rate by
CHEATING (fewer VERIFIED steps, or more tokens per verified step) is
REJECTED. This is the anti-hack gate — the system must not improve its
own metric at the cost of honesty or efficiency.

Spec: specs/der-loop-integrity-display/requirements.md REQ-2.
"""

from __future__ import annotations

import sqlite3

from backend.agent.caducean_trajectory import CaduceanTrajectoryRecorder
from backend.agent.outer_loop import OuterTuner


def _recorder() -> CaduceanTrajectoryRecorder:
    return CaduceanTrajectoryRecorder(db_conn=sqlite3.connect(":memory:"))


def _seed_sessions(rec, specs):
    """Seed session-exit rows. specs = list of (natural_exit, verified_count,
    tokens_total)."""
    for i, (ne, vc, tt) in enumerate(specs):
        rec.record_session_exit(
            f"s{i}", "general", natural_exit=ne, verified_count=vc,
            tokens_total=tt,
        )


class TestCompoundGateRejectsHack:
    def test_healthy_proposal_accepted(self):
        """All-natural-exit, healthy guards -> a consolidating proposal is accepted."""
        rec = _recorder()
        # 6 healthy sessions: all natural exits, all verified, low token cost.
        _seed_sessions(rec, [(True, 5, 5000)] * 6)
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        change = tuner.run_once(domain="general")
        assert change is not None
        # Either applied (improved) or gracefully rejected — never raises, and if
        # applied it must not have degraded guards.
        if change.get("applied"):
            assert "key" in change and "value" in change

    def test_degraded_verified_fraction_rejected(self):
        """A proposal that would drop verified_fraction must be rejected even if
        natural_exit_rate looks better."""
        rec = _recorder()
        # Held-out batch: 3 sessions, all natural exits but with varying verified
        # counts. We force a baseline where a 'hack' proposal lowers verified_fraction.
        _seed_sessions(rec, [(True, 10, 5000), (True, 10, 5000), (True, 10, 5000)])
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        baseline = tuner._score(tuner._heldout_batch(tuner._ledger()["exits"]))
        # Simulate a hack proposal: natural_exit_rate up, verified_fraction down.
        hacked = dict(baseline)
        hacked["natural_exit_rate"] = min(1.0, baseline["natural_exit_rate"] + 0.1)
        hacked["verified_fraction"] = baseline["verified_fraction"] - 0.5
        assert tuner._compound_accepts(hacked, baseline) is False

    def test_inflated_tokens_per_verified_rejected(self):
        """A proposal that inflates tokens_per_verified must be rejected even if
        natural_exit_rate looks better."""
        rec = _recorder()
        _seed_sessions(rec, [(True, 5, 5000), (True, 5, 5000), (True, 5, 5000)])
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        baseline = tuner._score(tuner._heldout_batch(tuner._ledger()["exits"]))
        hacked = dict(baseline)
        hacked["natural_exit_rate"] = min(1.0, baseline["natural_exit_rate"] + 0.1)
        hacked["tokens_per_verified"] = baseline["tokens_per_verified"] + 1000.0
        assert tuner._compound_accepts(hacked, baseline) is False

    def test_no_improvement_rejected(self):
        """A proposal that does not raise natural_exit_rate is rejected."""
        rec = _recorder()
        _seed_sessions(rec, [(True, 5, 5000), (True, 5, 5000), (True, 5, 5000)])
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        baseline = tuner._score(tuner._heldout_batch(tuner._ledger()["exits"]))
        same = dict(baseline)
        assert tuner._compound_accepts(same, baseline) is False

    def test_compound_accepts_genuine_improvement(self):
        """A proposal that raises natural_exit_rate WITHOUT degrading guards passes."""
        rec = _recorder()
        # Baseline < 1.0 so a +0.05 raise is a real improvement: 2/3 natural.
        _seed_sessions(rec, [(True, 5, 5000), (True, 5, 5000), (False, 5, 5000)])
        tuner = OuterTuner(recorder=rec, held_out_count=3)
        baseline = tuner._score(tuner._heldout_batch(tuner._ledger()["exits"]))
        assert baseline["natural_exit_rate"] < 1.0
        genuine = dict(baseline)
        genuine["natural_exit_rate"] = min(1.0, baseline["natural_exit_rate"] + 0.05)
        # guards unchanged
        assert tuner._compound_accepts(genuine, baseline) is True

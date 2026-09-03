"""Unit test: a guard with a missing input reports `live=False`, and the
proposal is NOT accepted on it (REQ-6 AC5, D-3).

Spec: specs/phase-6-der-integrity/requirements.md REQ-6 AC5.

This is the exact conflation that hid the original bug for months:
`tokens_per_verified` had no input and reported PASS; `verified_fraction`
had a constant and reported PASS. Both SHOULD have reported "I cannot
evaluate this." `GuardResult.live` and `GuardResult.passed` are DISTINCT
fields on purpose (design.md D-3 / CT-D5) — asserting only the compound
`_compound_accepts()` boolean would not catch a guard that is dead-but-
reports-pass, because a dead guard defaulting to True is indistinguishable
from a live guard that genuinely passed, from the compound result alone.
This test asserts the GuardResult objects directly.
"""

from __future__ import annotations

from backend.agent.outer_loop import GuardResult, OuterTuner


class TestGuardUnavailableIsNotPass:
    def test_live_false_reports_not_passed_even_if_proposed_looks_better(self):
        """CT-D5: live=False can never imply passed=True — even when the
        proposed value, taken at face value, would have looked like an
        improvement."""
        baseline = {
            "natural_exit_rate": 0.5,
            "verified_fraction": 0.5,
            "tokens_per_verified": 2000.0,
        }
        proposed = {
            "natural_exit_rate": 0.9,       # genuinely better
            "verified_fraction": 0.9,       # looks better too...
            "tokens_per_verified": 1000.0,  # ...and this too
        }
        live = {
            "natural_exit_rate": True,
            "verified_fraction": False,     # ...but this guard has NO INPUT
            "tokens_per_verified": True,
        }
        guards = OuterTuner._evaluate_guards(proposed, baseline, live)
        vf = next(g for g in guards if g.name == "verified_fraction")
        assert vf.live is False
        assert vf.passed is False, (
            "a guard with live=False must report passed=False regardless of "
            "how favorable its numbers look — live=False can never imply "
            "passed=True (CT-D5)"
        )

    def test_dead_guard_cannot_carry_the_compound_gate_to_acceptance(self):
        """A proposal cannot be accepted on the strength of a dead guard —
        `_compound_accepts` must reject when ANY guard is dead, mirroring
        REQ-2 AC3 ('all three hold')."""
        baseline = {
            "natural_exit_rate": 0.5,
            "verified_fraction": 0.5,
            "tokens_per_verified": 2000.0,
        }
        proposed = dict(baseline)
        proposed["natural_exit_rate"] = 0.9  # only the live, real guard improves
        live = {
            "natural_exit_rate": True,
            "verified_fraction": False,   # dead — no input this batch
            "tokens_per_verified": True,
        }
        assert OuterTuner._compound_accepts(proposed, baseline, live) is False

    def test_guard_result_shape_keeps_live_and_passed_distinct(self):
        """CT-D5 as a direct dataclass-shape assertion."""
        g = GuardResult(name="x", baseline=1.0, proposed=1.0, live=False, passed=False)
        assert g.live is False
        assert g.passed is False
        g2 = GuardResult(name="y", baseline=1.0, proposed=2.0, live=True, passed=True)
        assert g2.live is True
        assert g2.passed is True
        # The fields are independently settable — the dataclass does not
        # derive one from the other.
        g3 = GuardResult(name="z", baseline=1.0, proposed=2.0, live=True, passed=False)
        assert g3.live is True and g3.passed is False

    def test_all_three_dead_means_gate_never_accepts(self):
        baseline = {"natural_exit_rate": 0.5, "verified_fraction": 0.5, "tokens_per_verified": 2000.0}
        proposed = {"natural_exit_rate": 0.9, "verified_fraction": 0.9, "tokens_per_verified": 100.0}
        live = {"natural_exit_rate": False, "verified_fraction": False, "tokens_per_verified": False}
        assert OuterTuner._compound_accepts(proposed, baseline, live) is False
        guards = OuterTuner._evaluate_guards(proposed, baseline, live)
        assert all(g.live is False for g in guards)
        assert all(g.passed is False for g in guards)

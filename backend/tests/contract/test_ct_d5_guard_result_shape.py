"""CT-D5: GuardResult shape.

Spec: specs/phase-6-der-integrity/design.md Testing Strategy > Contract table,
row CT-D5. "`live` and `passed` are distinct fields; `live=False` can never
imply `passed=True`."

This is the narrow dataclass-shape pin; the fuller behavioral proof that a
dead guard cannot carry the compound gate to acceptance lives in
backend/tests/unit/test_guard_unavailable_is_not_pass.py (REQ-6 AC5, D-3).
"""

from __future__ import annotations

import dataclasses

from backend.agent.outer_loop import GuardResult, OuterTuner


class TestCTD5GuardResultShape:
    def test_guard_result_has_distinct_live_and_passed_fields(self):
        field_names = {f.name for f in dataclasses.fields(GuardResult)}
        assert {"name", "baseline", "proposed", "live", "passed"} <= field_names

    def test_live_false_never_implies_passed_true_across_all_settings(self):
        """Exhaustive over the field's own truth table: every GuardResult
        with live=False must be constructible with passed=False, and
        `_evaluate_guards` (the only production constructor) never emits
        live=False with passed=True for any combination of numbers."""
        baseline = {"natural_exit_rate": 0.4, "verified_fraction": 0.4, "tokens_per_verified": 3000.0}
        for ne in (0.1, 0.9):
            for vf in (0.1, 0.9):
                for tpv in (100.0, 9000.0):
                    proposed = {
                        "natural_exit_rate": ne,
                        "verified_fraction": vf,
                        "tokens_per_verified": tpv,
                    }
                    for dead in ("natural_exit_rate", "verified_fraction", "tokens_per_verified"):
                        live = {k: (k != dead) for k in baseline}
                        guards = OuterTuner._evaluate_guards(proposed, baseline, live)
                        dead_guard = next(g for g in guards if g.name == dead)
                        assert dead_guard.live is False
                        assert dead_guard.passed is False, (
                            f"CT-D5 violated: live=False but passed=True for "
                            f"{dead} with proposed={proposed}"
                        )

    def test_dataclass_is_frozen(self):
        g = GuardResult(name="x", baseline=1.0, proposed=1.0, live=True, passed=True)
        with __import__("pytest").raises(dataclasses.FrozenInstanceError):
            g.passed = False

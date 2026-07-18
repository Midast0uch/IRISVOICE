"""Unit tests: measured-token work-unit debit (REQ-3).

REQ-3 replaces the flat `work_units -= len(children)` debit with a debit
proportional to the step's MEASURED token cost: `max(1, tokens // AVG_STEP_COST)`.
A step always costs >=1 unit; the budget never goes negative.

Spec: specs/der-loop-integrity-display/requirements.md REQ-3.
"""

from __future__ import annotations

from backend.agent.der_constants import AVG_STEP_COST, debit_work_units


class TestDebitWorkUnits:
    def test_small_step_costs_one_unit(self):
        # A short step (~200 tok) is < one AVG_STEP_COST -> floor to 1 unit.
        assert debit_work_units(10, 200) == 9
        assert debit_work_units(10, AVG_STEP_COST - 1) == 9

    def test_large_step_costs_multiple_units(self):
        # A 4500-token step = 3 units at AVG_STEP_COST=1500.
        assert debit_work_units(10, 4500) == 7
        assert debit_work_units(10, 3 * AVG_STEP_COST) == 7

    def test_zero_tokens_still_costs_one(self):
        # A step that spent nothing still consumed a cycle -> >=1 unit.
        assert debit_work_units(5, 0) == 4

    def test_never_negative(self):
        assert debit_work_units(0, 100000) == 0
        assert debit_work_units(2, 100000) == 0

    def test_exact_boundary(self):
        # Exactly one AVG_STEP_COST -> exactly 1 unit debited.
        assert debit_work_units(5, AVG_STEP_COST) == 4

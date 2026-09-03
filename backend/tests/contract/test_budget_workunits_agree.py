"""Contract CT-F2: budget and work units derive from the SAME window.

REQ-1 AC4: ``_token_budget`` and ``derive_work_units_0()`` must derive from the
same ``context_window`` value. Both are pure functions of that window; the
contract is that they agree on the window they were given and neither exceeds it.
A drift between them is exactly how the budget and the work units separated 5x
apart in the first place.
"""
from __future__ import annotations

import pytest

from backend.agent.der_constants import (
    AVG_STEP_COST,
    derive_work_units_0,
    resolve_der_token_budget,
)

WINDOWS = [2_000, 8_192, 32_000, 128_000, 256_000]


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("task_class", ["quick", "implement", "full"])
def test_same_window_bounds(window, task_class):
    budget = resolve_der_token_budget(window, task_class)
    units = derive_work_units_0(window)
    # Both bounded by the window they were derived from.
    assert budget <= window, f"budget {budget} > window {window}"
    # Work units approximate the window in AVG_STEP_COST units (within one step).
    assert units * AVG_STEP_COST >= window - AVG_STEP_COST, (
        f"work units {units} do not cover window {window}"
    )


@pytest.mark.parametrize("window", WINDOWS)
def test_monotonic_with_window(window):
    # Larger window -> larger or equal budget AND units (they track the same
    # resource, so they cannot disagree on which window they were given).
    bigger = window * 2
    for tc in ["quick", "implement", "full"]:
        assert resolve_der_token_budget(bigger, tc) >= resolve_der_token_budget(
            window, tc
        )
    assert derive_work_units_0(bigger) >= derive_work_units_0(window)

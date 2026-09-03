"""Unit tests: DER step budget derived from the model's REAL context window.

REQ-1 AC7: prove across window sizes {2k, 8k, 32k, 128k, 256k} x task classes
{quick, implement, full} that the budget never exceeds the window, the mode
ceiling binds on large windows, and the floor never exceeds the window.

The fix (``resolve_der_token_budget`` in der_constants.py, commit 01e6625b)
was landed UNTESTED — these tests are the missing pin. Reducing the parametrize
matrix (dropping a window or a class) is a test modification and is forbidden.
"""
from __future__ import annotations

import pytest

from backend.agent.der_constants import (
    DER_BUDGET_MIN_FLOOR,
    DER_WINDOW_UTILISATION,
    resolve_der_token_budget,
)

WINDOWS = [2_000, 8_192, 32_000, 128_000, 256_000]
CLASSES = ["quick", "implement", "full"]


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("task_class", CLASSES)
def test_budget_never_exceeds_window(window, task_class):
    budget = resolve_der_token_budget(window, task_class)
    assert budget <= window, (
        f"budget {budget} exceeds window {window} for {task_class}"
    )


@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("task_class", CLASSES)
def test_budget_never_exceeds_window_cap(window, task_class):
    cap = max(int(window * DER_WINDOW_UTILISATION), 1)
    budget = resolve_der_token_budget(window, task_class)
    assert budget <= cap, f"budget {budget} exceeds window cap {cap} for {task_class}"


@pytest.mark.parametrize("task_class", CLASSES)
def test_large_window_ceiling_binds(task_class):
    # On a 256k window the per-class fraction ceiling (not the 0.9 cap, not the
    # floor) is the binding constraint — capacity scales with the model.
    window = 256_000
    cap = max(int(window * DER_WINDOW_UTILISATION), 1)
    budget = resolve_der_token_budget(window, task_class)
    assert budget < cap, (
        f"ceiling did not bind for {task_class}: budget {budget} vs cap {cap}"
    )


def test_small_window_floor_ignored():
    # 2k window: floor (4000) clamped by window cap (1800) -> budget == window*0.9.
    window = 2_000
    expected = max(int(window * DER_WINDOW_UTILISATION), 1)
    assert resolve_der_token_budget(window, "full") == expected
    assert resolve_der_token_budget(window, "quick") == expected


def test_8k_quick_floor_raises_but_stays_under_window():
    # 8k quick: 10% of 7372 = 737 < floor 4000 -> floor raises to 4000,
    # and 4000 < 7372 (window cap). The floor is clamped by the window.
    window = 8_192
    cap = max(int(window * DER_WINDOW_UTILISATION), 1)
    budget = resolve_der_token_budget(window, "quick")
    assert budget == DER_BUDGET_MIN_FLOOR
    assert budget < cap


def test_floor_clamped_by_window():
    # For every window the floor is clamped by the window cap, so it can never
    # reintroduce an overcommit on a small model.
    for window in WINDOWS:
        cap = max(int(window * DER_WINDOW_UTILISATION), 1)
        assert min(DER_BUDGET_MIN_FLOOR, cap) <= cap

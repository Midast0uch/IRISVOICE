"""
Unit tests for param_homeostasis.py — relaxation arithmetic, deadband, clamping,
default baseline, re-anchor, eviction, and no overshoot.

All FFI interactions are mocked so these are pure logic tests.
"""
import time
import threading
from unittest.mock import patch, MagicMock

import pytest

from backend.agent.param_homeostasis import (
    ParamHomeostasis,
    ParamBaseline,
    get_param_homeostasis,
    reset_param_homeostasis,
    SAFE_A,
    SAFE_B,
    SAFE_S,
    RELAX_STEP,
    RELAX_DEADBAND,
    MAX_BASELINES,
    RELAX_EVERY_N_UPDATES,
)


@pytest.fixture(autouse=True)
def _reset():
    """Reset the singleton before each test."""
    reset_param_homeostasis()
    yield
    reset_param_homeostasis()


# ── Default baseline ─────────────────────────────────────────────────────


def test_default_baseline():
    """A session with no set_baseline gets (2.0, 2.0, 0.35)."""
    h = get_param_homeostasis()
    rec = h.get_baseline("session_1")
    assert rec.a == pytest.approx(2.0)
    assert rec.b == pytest.approx(2.0)
    assert rec.s == pytest.approx(0.35)


# ── Re-anchor via set_baseline ───────────────────────────────────────────


def test_set_baseline_reanchors():
    """set_baseline records a new baseline, clamped to safe ranges."""
    h = get_param_homeostasis()
    h.set_baseline("session_1", 3.0, 1.5, 0.5)
    rec = h.get_baseline("session_1")
    assert rec.a == pytest.approx(3.0)
    assert rec.b == pytest.approx(1.5)
    assert rec.s == pytest.approx(0.5)


def test_set_baseline_clamps_out_of_range():
    """set_baseline clamps values to safe ranges."""
    h = get_param_homeostasis()
    h.set_baseline("session_1", 99.0, -99.0, 0.99)
    rec = h.get_baseline("session_1")
    assert rec.a == pytest.approx(SAFE_A[1])  # 4.0
    assert rec.b == pytest.approx(SAFE_B[0])  # 1.0
    assert rec.s == pytest.approx(SAFE_S[1])  # 0.8


# ── Proportional step ────────────────────────────────────────────────────


def test_proportional_step_toward_baseline():
    """relax_params moves 10% of the distance toward baseline.

    We patch the FFI functions at the USAGE site in param_homeostasis
    because the module imports them by value at module load time.
    """
    h = get_param_homeostasis()
    h.set_baseline("session_1", 2.0, 2.0, 0.35)

    # Mock FFI at the usage site (param_homeostasis module namespace)
    with patch(
        "backend.agent.param_homeostasis._ffi_get_state",
        return_value={"a": 4.0, "b": 4.0, "s": 0.1},
    ) as mock_get, patch(
        "backend.agent.param_homeostasis._ffi_set_params",
        return_value=True,
    ) as mock_set:
        h.relax_params("session_1")

    mock_get.assert_called_once_with("session_1")
    mock_set.assert_called_once()

    _args = mock_set.call_args[0]
    sid, new_a, new_b, new_s = _args

    # 4.0 + 0.25 * (2.0 - 4.0) = 4.0 - 0.50 = 3.5  (RELAX_STEP = 0.25)
    assert new_a == pytest.approx(3.5)
    # 4.0 + 0.25 * (2.0 - 4.0) = 3.5
    assert new_b == pytest.approx(3.5)
    # 0.1 + 0.25 * (0.35 - 0.1) = 0.1 + 0.0625 = 0.1625
    assert new_s == pytest.approx(0.1625)


# ── No overshoot ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cur_a,cur_b,cur_s,base_a,base_b,base_s",
    [
        (4.0, 4.0, 0.1, 2.0, 2.0, 0.35),
        (1.0, 1.0, 0.8, 2.0, 2.0, 0.35),
        (3.5, 2.5, 0.3, 3.5, 2.5, 0.3),  # already at baseline
        (1.0, 4.0, 0.5, 2.0, 2.0, 0.35),
    ],
)
def test_no_overshoot(cur_a, cur_b, cur_s, base_a, base_b, base_s):
    """Relaxation from any safe value never crosses baseline (proportional step < 1.0 guarantees this)."""
    h = get_param_homeostasis()
    h.set_baseline("session_1", base_a, base_b, base_s)

    with patch(
        "backend.agent.param_homeostasis._ffi_get_state",
        return_value={"a": cur_a, "b": cur_b, "s": cur_s},
    ), patch(
        "backend.agent.param_homeostasis._ffi_set_params",
        return_value=True,
    ) as mock_set:
        h.relax_params("session_1")

    _args = mock_set.call_args[0]
    _, new_a, new_b, new_s = _args

    # The new value must be between current and baseline (never overshoot).
    for cur, new, base in [
        (cur_a, new_a, base_a),
        (cur_b, new_b, base_b),
        (cur_s, new_s, base_s),
    ]:
        if cur <= base:
            assert cur <= new <= base + 1e-9, (
                f"overshoot: cur={cur} new={new} base={base}"
            )
        else:
            assert cur >= new >= base - 1e-9, (
                f"overshoot: cur={cur} new={new} base={base}"
            )
        # Also check the RELAX_STEP fraction bound.
        if abs(cur - base) > 1e-9:
            fraction_moved = abs(new - cur) / abs(base - cur)
            assert fraction_moved <= RELAX_STEP + 1e-9, (
                f"moved {fraction_moved:.3f} > {RELAX_STEP}"
            )


# ── Deadband ──────────────────────────────────────────────────────────────


def test_deadband_skips_near_baseline():
    """A parameter within RELAX_DEADBAND of baseline is left unchanged."""
    h = get_param_homeostasis()
    h.set_baseline("session_1", 2.0, 2.0, 0.35)

    # Current values very close to baseline
    with patch(
        "backend.agent.param_homeostasis._ffi_get_state",
        return_value={"a": 2.01, "b": 1.99, "s": 0.355},
    ), patch(
        "backend.agent.param_homeostasis._ffi_set_params",
        return_value=True,
    ) as mock_set:
        h.relax_params("session_1")

    _args = mock_set.call_args[0]
    _, new_a, new_b, new_s = _args

    # Should snap to baseline since within deadband
    assert new_a == pytest.approx(2.0)
    assert new_b == pytest.approx(2.0)
    assert new_s == pytest.approx(0.35)


# ── Safe-range clamping ──────────────────────────────────────────────────


def test_relax_clamps_to_safe_ranges():
    """Even if relaxation step would go out of bounds, clamp to safe ranges."""
    h = get_param_homeostasis()
    h.set_baseline("session_1", SAFE_A[0], SAFE_B[0], SAFE_S[0])

    # Current values at far end — moving 10% toward baseline stays in range
    with patch(
        "backend.agent.param_homeostasis._ffi_get_state",
        return_value={"a": SAFE_A[1], "b": SAFE_B[1], "s": SAFE_S[1]},
    ), patch(
        "backend.agent.param_homeostasis._ffi_set_params",
        return_value=True,
    ) as mock_set:
        h.relax_params("session_1")

    _args = mock_set.call_args[0]
    _, new_a, new_b, new_s = _args

    assert SAFE_A[0] <= new_a <= SAFE_A[1], f"a={new_a} out of safe range"
    assert SAFE_B[0] <= new_b <= SAFE_B[1], f"b={new_b} out of safe range"
    assert SAFE_S[0] <= new_s <= SAFE_S[1], f"s={new_s} out of safe range"


# ── Perturbation tracking ────────────────────────────────────────────────


def test_register_perturbation():
    """register_perturbation increments the writer's counter."""
    h = get_param_homeostasis()
    h.register_perturbation("session_1", "barge_in")
    h.register_perturbation("session_1", "barge_in")
    h.register_perturbation("session_1", "violation_tune")
    rec = h.get_baseline("session_1")
    assert rec.perturbations == {"barge_in": 2, "violation_tune": 1}


# ── Eviction ──────────────────────────────────────────────────────────────


def test_eviction_at_capacity():
    """Evict oldest sessions when over MAX_BASELINES."""
    h = get_param_homeostasis()
    # Fill up to MAX_BASELINES
    for i in range(MAX_BASELINES):
        h.set_baseline(f"s{i:04d}", 2.0, 2.0, 0.35)
    assert len(h._baselines) == MAX_BASELINES
    # One more triggers eviction
    h.set_baseline("new_sessions", 3.0, 2.0, 0.4)
    assert len(h._baselines) == MAX_BASELINES
    # The oldest (s0000) should be gone
    assert "s0000" not in h._baselines
    assert "new_sessions" in h._baselines


# ── Metrics ───────────────────────────────────────────────────────────────


def test_metrics_snapshot():
    """metrics() returns current, baseline, perturbations, relaxations."""
    h = get_param_homeostasis()
    h.set_baseline("session_1", 3.0, 2.5, 0.45)
    h.register_perturbation("session_1", "barge_in")
    h.register_perturbation("session_1", "violation_tune")

    m = h.metrics("session_1")
    assert "current_a" in m
    assert "baseline_a" in m
    assert "perturbations" in m
    assert "relaxations" in m
    assert m["perturbations"]["barge_in"] == 1
    assert m["perturbations"]["violation_tune"] == 1


# ── Relaxation counter ────────────────────────────────────────────────────


def test_relaxation_count_increments():
    """Each relax_params call increments the relaxation counter."""
    h = get_param_homeostasis()
    h.set_baseline("session_1", 2.0, 2.0, 0.35)

    with patch(
        "backend.agent.param_homeostasis._ffi_get_state",
        return_value={"a": 4.0, "b": 4.0, "s": 0.1},
    ), patch(
        "backend.agent.param_homeostasis._ffi_set_params",
        return_value=True,
    ):
        h.relax_params("session_1")

    rec = h.get_baseline("session_1")
    assert rec.relaxations == 1

    with patch(
        "backend.agent.param_homeostasis._ffi_get_state",
        return_value={"a": 3.8, "b": 3.8, "s": 0.125},
    ), patch(
        "backend.agent.param_homeostasis._ffi_set_params",
        return_value=True,
    ):
        h.relax_params("session_1")

    rec = h.get_baseline("session_1")
    assert rec.relaxations == 2


# ── FFI unavailable ───────────────────────────────────────────────────────


def test_ffi_unavailable_does_not_raise():
    """When FFI returns empty (engine unavailable), relax_params logs debug and returns."""
    h = get_param_homeostasis()
    h.set_baseline("session_1", 2.0, 2.0, 0.35)

    # Empty dict simulates FFI unavailability
    with patch(
        "backend.agent.param_homeostasis._ffi_get_state",
        return_value={},
    ):
        # Should not raise
        h.relax_params("session_1")


# ── maybe_relax cadence ────────────────────────────────────────────────────


def test_maybe_relax_fires_at_cadence():
    """maybe_relax fires when update_count - last >= RELAX_EVERY_N_UPDATES."""
    h = get_param_homeostasis()
    h.set_baseline("session_1", 2.0, 2.0, 0.35)

    relax_count = [0]

    def _tracking_relax(sid):
        relax_count[0] += 1

    # Replace relax_params temporarily for counting
    original = h.relax_params
    h.relax_params = _tracking_relax
    try:
        # Call with update_count below cadence
        h.maybe_relax("session_1", 5)
        assert relax_count[0] == 0, "should not fire below cadence"

        # Call with update_count hitting cadence
        h.maybe_relax("session_1", 10)
        assert relax_count[0] == 1, "should fire at cadence"

        # Call again at same update_count — should not fire again
        h.maybe_relax("session_1", 10)
        assert relax_count[0] == 1, "should not fire again at same count"

        # Next cadence
        h.maybe_relax("session_1", 20)
        assert relax_count[0] == 2, "should fire at next cadence"
    finally:
        h.relax_params = original




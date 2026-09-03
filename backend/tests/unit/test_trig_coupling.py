"""
test_trig_coupling.py — Unit tests for trig_coupling primitives (T3.2 / REQ-7/REQ-18).

Pins the sign convention: splay_force repels (opposite signs for leading/trailing),
align_force attracts (negation of splay_force), circular_delta is wrap-aware,
and _per_oscillator_forces returns a List[float] of signed values.
"""

import math
from typing import List

import pytest

from backend.agent.trig_coupling import (
    align_force,
    circular_delta,
    splay_force,
    _per_oscillator_forces,
)


class TestSplayAlignForce:
    """REQ-18 AC4: splay_force and align_force have OPPOSITE signs."""

    def test_splay_and_align_opposite_signs(self):
        """For the same inputs, splay_force and align_force are negations."""
        _f_splay = splay_force(0.0, [0.0, math.pi / 2], k=1.0)
        _f_align = align_force(0.0, [0.0, math.pi / 2], k=1.0)
        assert _f_splay == pytest.approx(-_f_align, abs=1e-10)

    def test_splay_leading_positive_trailing_negative(self):
        """Leading oscillator (higher theta) gets positive force; trailing gets negative."""
        _f_lead = splay_force(math.pi / 2, [0.0, math.pi / 2], k=1.0)
        _f_trail = splay_force(0.0, [0.0, math.pi / 2], k=1.0)
        assert _f_lead > 0, "leading oscillator should have positive splay force"
        assert _f_trail < 0, "trailing oscillator should have negative splay force"

    def test_align_leading_negative_trailing_positive(self):
        """align_force reverses the sign: leading gets negative, trailing positive."""
        _f_lead = align_force(math.pi / 2, [0.0, math.pi / 2], k=1.0)
        _f_trail = align_force(0.0, [0.0, math.pi / 2], k=1.0)
        assert _f_lead < 0, "leading oscillator should have negative align force"
        assert _f_trail > 0, "trailing oscillator should have positive align force"


class TestCircularDelta:
    """circular_delta is wrap-aware and commutative."""

    def test_delta_near_zero(self):
        """Angles close together have a small delta."""
        _d = circular_delta(0.1, 0.15)
        assert _d == pytest.approx(0.05, abs=1e-10)

    def test_delta_near_2pi(self):
        """Angles near 0 and 2pi give the short arc across the wrap."""
        _d = circular_delta(0.05, 2 * math.pi - 0.05)
        # Short arc: 0.05 to 2pi-0.05 = 6.233, but the other way is 0.1
        assert _d == pytest.approx(0.10, abs=1e-10)

    def test_delta_zero(self):
        """Same angle gives delta 0."""
        _d = circular_delta(1.0, 1.0)
        assert _d == pytest.approx(0.0, abs=1e-10)

    def test_delta_commutative(self):
        """circular_delta is commutative."""
        _d1 = circular_delta(0.3, 1.7)
        _d2 = circular_delta(1.7, 0.3)
        assert _d1 == pytest.approx(_d2, abs=1e-10)

    def test_delta_pi(self):
        """Opposite angles have delta pi."""
        _d = circular_delta(0.0, math.pi)
        assert _d == pytest.approx(math.pi, abs=1e-10)


class TestPerOscillatorForces:
    """_per_oscillator_forces returns List[float] of signed values."""

    def test_returns_list_of_float(self):
        """Result is a List[float]."""
        _forces = _per_oscillator_forces([0.0, math.pi / 2], k=1.0)
        assert isinstance(_forces, list)
        assert all(isinstance(f, float) for f in _forces)
        assert len(_forces) == 2

    def test_signed_values(self):
        """Forces are signed — not all the same sign."""
        _forces = _per_oscillator_forces([0.0, math.pi / 2], k=1.0)
        # One positive, one negative
        assert (_forces[0] > 0 and _forces[1] < 0) or (
            _forces[0] < 0 and _forces[1] > 0
        )

    def test_empty_inputs_safe_zeros(self):
        """Empty or single-element input returns safe zeros."""
        assert _per_oscillator_forces([], 1.0) == []
        assert _per_oscillator_forces([1.0], 1.0) == [0.0]

    def test_zero_k_safe_zeros(self):
        """k=0 returns all zeros."""
        _forces = _per_oscillator_forces([0.0, math.pi / 2], k=0.0)
        assert all(f == 0.0 for f in _forces)


class TestZeroInputSafety:
    """Edge cases for splay_force and align_force."""

    def test_splay_force_empty_others(self):
        """Empty others returns 0.0."""
        assert splay_force(0.0, [], k=1.0) == 0.0

    def test_splay_force_single_self(self):
        """Single element with self returns 0.0."""
        assert splay_force(0.0, [0.0], k=1.0) == 0.0

    def test_splay_force_zero_k(self):
        """k=0 returns 0.0."""
        assert splay_force(0.0, [0.0, math.pi], k=0.0) == 0.0

    def test_align_force_zero_k(self):
        """align_force with k=0 returns 0.0."""
        assert align_force(0.0, [0.0, math.pi], k=0.0) == 0.0

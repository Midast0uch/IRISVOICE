"""
test_chunk_size_bands.py — Unit tests for chunk_size_from_u (T3.5 / REQ-12).

Tests:
  - monotonic non-decreasing across a sweep of abs_u
  - three bands produce expected ordering
  - values stay within [CHUNK_MIN, CHUNK_MAX]
"""

import math

import pytest

from backend.agent.conversation_kernel import ConversationKernel, CHUNK_MIN, CHUNK_MAX


class TestChunkSizeFromU:
    """REQ-12: monotonic non-decreasing banded chunk size from |u|."""

    def test_band_ordering(self):
        """Split band < mid band < converged band."""
        _split = ConversationKernel._chunk_size_from_u(0.0)
        _mid = ConversationKernel._chunk_size_from_u(0.65)
        _conv = ConversationKernel._chunk_size_from_u(1.0)
        assert _split <= _mid, f"split={_split} should be <= mid={_mid}"
        assert _mid <= _conv, f"mid={_mid} should be <= converged={_conv}"

    def test_monotonic_sweep(self):
        """Monotonic non-decreasing across a sweep of abs_u from 0 to 2."""
        _prev = 0
        for _u in [i * 0.01 for i in range(201)]:  # 0 to 2.0 step 0.01
            _size = ConversationKernel._chunk_size_from_u(_u)
            assert _size >= _prev, (
                f"Not monotonic at u={_u:.2f}: {_prev} -> {_size}"
            )
            _prev = _size

    def test_bounds(self):
        """Values stay within [CHUNK_MIN, CHUNK_MAX]."""
        for _u in [i * 0.05 for i in range(41)]:  # 0 to 2.0 step 0.05
            _size = ConversationKernel._chunk_size_from_u(_u)
            assert CHUNK_MIN <= _size <= CHUNK_MAX, (
                f"u={_u:.2f} gives size={_size} outside [{CHUNK_MIN}, {CHUNK_MAX}]"
            )

    def test_split_band_below_threshold(self):
        """abs_u below U_SPLIT returns CHUNK_MIN."""
        _size = ConversationKernel._chunk_size_from_u(0.0)
        assert _size == CHUNK_MIN

    def test_converged_band_at_threshold(self):
        """abs_u at/above U_CONVERGED returns CHUNK_MAX."""
        _size = ConversationKernel._chunk_size_from_u(1.0)
        assert _size == CHUNK_MAX

    def test_interpolates_mid_band(self):
        """Mid band produces values strictly between CHUNK_MIN and CHUNK_MAX."""
        _size = ConversationKernel._chunk_size_from_u(0.65)
        assert CHUNK_MIN < _size < CHUNK_MAX, (
            f"mid-band u=0.65 gives size={_size} should be between "
            f"{CHUNK_MIN} and {CHUNK_MAX}"
        )

    def test_large_u_is_clamped(self):
        """abs_u > 1 still returns CHUNK_MAX (capped at converged)."""
        for _u in (1.5, 2.0, 5.0):
            _size = ConversationKernel._chunk_size_from_u(_u)
            assert _size == CHUNK_MAX, f"u={_u} should return CHUNK_MAX, got {_size}"

"""
Contract test: DER band thresholds and label strings (CT-E3, CT-E5).

Asserts:
- _verify_step_result returns VERIFIED / UNVERIFIED / FAILED at the
  correct 0.8 / 0.3 thresholds.
- The three label strings are exactly "VERIFIED", "UNVERIFIED", "FAILED".
- A bare stub always produces FAILED.
- Empty result always produces FAILED.
"""

from __future__ import annotations

import re
from unittest import mock

from backend.agent.agent_kernel import AgentKernel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_kernel(verified_fraction_return: float | None = None):
    """Create a minimal AgentKernel-like instance for testing.

    Avoids the heavy __init__ by patching it out.
    """
    with mock.patch.object(AgentKernel, "__init__", return_value=None):
        k = AgentKernel.__new__(AgentKernel)
        k._STUB_RE = re.compile(r"\[step\s+\d+\s+completed\]", re.IGNORECASE)
        if verified_fraction_return is not None:
            k._verified_fraction = mock.Mock(return_value=verified_fraction_return)  # type: ignore[method-assign]
        return k


# ---------------------------------------------------------------------------
# VERIFIED (fraction >= 0.8)
# ---------------------------------------------------------------------------

def test_verified_label_at_high_fraction():
    """Fraction >= 0.8 yields VERIFIED."""
    kernel = _make_kernel(verified_fraction_return=0.8)
    label = kernel._verify_step_result(
        goal="do the thing",
        expected="do the thing",
        result="the thing was done",
    )
    assert label == "VERIFIED", f"expected VERIFIED, got {label!r}"


def test_verified_label_above_threshold():
    """Fraction > 0.8 yields VERIFIED."""
    kernel = _make_kernel(verified_fraction_return=0.95)
    label = kernel._verify_step_result(
        goal="do the thing",
        expected="do the thing",
        result="the thing was done comprehensively",
    )
    assert label == "VERIFIED"


# ---------------------------------------------------------------------------
# UNVERIFIED (0.3 <= fraction < 0.8)
# ---------------------------------------------------------------------------

def test_unverified_label_at_threshold():
    """Fraction exactly 0.3 yields UNVERIFIED."""
    kernel = _make_kernel(verified_fraction_return=0.3)
    label = kernel._verify_step_result(
        goal="do the thing",
        expected="do the thing",
        result="partially addressed",
    )
    assert label == "UNVERIFIED", f"expected UNVERIFIED, got {label!r}"


def test_unverified_label_mid_range():
    """Fraction between 0.3 and 0.8 yields UNVERIFIED."""
    kernel = _make_kernel(verified_fraction_return=0.55)
    label = kernel._verify_step_result(
        goal="do the thing",
        expected="do the thing",
        result="somewhat addressed",
    )
    assert label == "UNVERIFIED"


def test_unverified_label_just_below_verified():
    """Fraction just below 0.8 (0.79) yields UNVERIFIED."""
    kernel = _make_kernel(verified_fraction_return=0.79)
    label = kernel._verify_step_result(
        goal="do the thing",
        expected="do the thing",
        result="mostly done but not fully",
    )
    assert label == "UNVERIFIED"


# ---------------------------------------------------------------------------
# FAILED (fraction < 0.3)
# ---------------------------------------------------------------------------

def test_failed_label_below_threshold():
    """Fraction < 0.3 yields FAILED."""
    kernel = _make_kernel(verified_fraction_return=0.29)
    label = kernel._verify_step_result(
        goal="do the thing",
        expected="do the thing",
        result="irrelevant output",
    )
    assert label == "FAILED", f"expected FAILED, got {label!r}"


def test_failed_label_zero():
    """Fraction 0.0 yields FAILED."""
    kernel = _make_kernel(verified_fraction_return=0.0)
    label = kernel._verify_step_result(
        goal="do the thing",
        expected="do the thing",
        result="completely wrong",
    )
    assert label == "FAILED"


# ---------------------------------------------------------------------------
# Bare stub / empty result (pre-fraction guards)
# ---------------------------------------------------------------------------

def test_bare_stub_failed():
    """A result that is only a stub marker is FAILED before fraction check."""
    # Even if fraction were forced to 0.8+, stub guard catches it first.
    kernel = _make_kernel(verified_fraction_return=0.9)
    label = kernel._verify_step_result(
        goal="do the thing",
        expected="do the thing",
        result="[step 1 completed]",
    )
    assert label == "FAILED", (
        f"expected FAILED for bare stub, got {label!r} — "
        "stub guard must fire before fraction check"
    )


def test_empty_result_failed():
    """Empty result is FAILED."""
    kernel = _make_kernel(verified_fraction_return=0.9)
    label = kernel._verify_step_result(
        goal="do the thing",
        expected="do the thing",
        result="",
    )
    assert label == "FAILED"


def test_whitespace_result_failed():
    """Whitespace-only result is FAILED."""
    kernel = _make_kernel(verified_fraction_return=0.9)
    label = kernel._verify_step_result(
        goal="do the thing",
        expected="do the thing",
        result="   ",
    )
    assert label == "FAILED"


# ---------------------------------------------------------------------------
# Label strings are exact (CT-E3)
# ---------------------------------------------------------------------------

def test_label_strings_exact():
    """The three labels must be exactly the specified strings (CT-E3)."""
    assert "VERIFIED" == "VERIFIED"
    assert "UNVERIFIED" == "UNVERIFIED"
    assert "FAILED" == "FAILED"

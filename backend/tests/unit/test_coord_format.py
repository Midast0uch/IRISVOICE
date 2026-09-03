"""
Unit tests for format_coords / parse_coords (REQ-5).

Verifies:
  - Round-trip: format_coords → parse_coords is exact for representative values
  - Fixed 2-decimal precision (no more, no less)
  - parse_coords raises ValueError on malformed input
"""

import pytest

from backend.agent.caducean_trajectory import format_coords, parse_coords


# ── Happy path: round-trip ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "x, y, xi, u",
    [
        (0.0, 0.0, 0.0, 0.0),         # origin
        (1.0, 2.0, 3.0, 4.0),         # positive integers
        (-1.0, -2.0, -3.0, -4.0),     # negative values
        (0.5, 0.25, 0.125, 0.0625),   # fractional
        (-0.5, -0.25, -0.125, -0.0625),  # negative fractional
        (123.45, 67.89, 0.01, 999.99),  # moderate magnitudes
        (1.234, 5.678, 9.012, 3.456),  # >2 decimal digits → truncated
        (0.001, 0.009, 0.099, 0.999),  # small values
        (-0.001, -0.009, -0.099, -0.999),  # negative small
    ],
)
def test_round_trip(x, y, xi, u):
    """format_coords → parse_coords returns exact values (2-dec precision)."""
    s = format_coords(x, y, xi, u)
    rx, ry, rxi, ru = parse_coords(s)

    # Each field should match round(x, 2)
    assert rx == pytest.approx(round(x, 2))
    assert ry == pytest.approx(round(y, 2))
    assert rxi == pytest.approx(round(xi, 2))
    assert ru == pytest.approx(round(u, 2))


# ── Precision: exactly 2 decimal places ───────────────────────────────────


def test_exactly_two_decimals():
    """format_coords always produces exactly 2 digits after the decimal."""
    s = format_coords(1.0, 2.0, 3.0, 4.0)
    # Pattern: number.number,number.number,number.number,number.number
    parts = s.split(",")
    assert len(parts) == 4
    for p in parts:
        assert "." in p, f"Missing decimal point in {p!r}"
        integer_part, fractional_part = p.split(".")
        assert len(fractional_part) == 2, (
            f"Expected 2 fractional digits, got {len(fractional_part)} in {p!r}"
        )
        # Integer part may have leading minus sign
        assert integer_part.lstrip("-").isdigit(), f"Non-numeric integer part in {p!r}"


def test_large_magnitudes():
    """Large values still produce valid 2-decimal format."""
    s = format_coords(10000.0, -5000.0, 0.0, 3.14159)
    rx, ry, rxi, ru = parse_coords(s)
    assert rx == pytest.approx(10000.00)
    assert ry == pytest.approx(-5000.00)
    assert rxi == pytest.approx(0.00)
    assert ru == pytest.approx(3.14)


# ── Malformed input ───────────────────────────────────────────────────────


def test_parse_wrong_field_count_empty():
    with pytest.raises(ValueError, match="Expected 4"):
        parse_coords("")


def test_parse_wrong_field_count_too_few():
    with pytest.raises(ValueError, match="Expected 4"):
        parse_coords("1.0,2.0,3.0")


def test_parse_wrong_field_count_too_many():
    with pytest.raises(ValueError, match="Expected 4"):
        parse_coords("1.0,2.0,3.0,4.0,5.0")


def test_parse_non_numeric():
    with pytest.raises(ValueError, match="Non-numeric"):
        parse_coords("1.0,abc,3.0,4.0")


def test_parse_extra_whitespace():
    """Whitespace in values causes parse failure (strict format)."""
    with pytest.raises(ValueError, match="whitespace"):
        parse_coords(" 1.0,2.0,3.0,4.0")


def test_parse_none():
    with pytest.raises(TypeError):
        parse_coords(None)  # type: ignore


# ── Idempotence: double-format is a no-op ─────────────────────────────────


def test_format_twice_same():
    """Calling format_coords twice with same inputs gives same result."""
    a = format_coords(1.23, 4.56, 7.89, 0.12)
    b = format_coords(1.23, 4.56, 7.89, 0.12)
    assert a == b

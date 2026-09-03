"""
Contract test CU-7: coordinate string format stability (REQ-5).

Pins the on-disk/over-the-wire coordinate format as a stable contract.
Changing this format breaks all trajectory-proximity queries and
Immortus chain recall — must be a deliberate, coordinated change.

Format: ``^-?\\d+\\.\\d{2},-?\\d+\\.\\d{2},-?\\d+\\.\\d{2},-?\\d+\\.\\d{2}$``

Example: ``"1.23,-4.56,0.78,0.90"``
"""

import re

import pytest

from backend.agent.caducean_trajectory import format_coords, parse_coords

# ── CU-7: format regex — stable contract ──────────────────────────────────

_COORD_FORMAT_REGEX = re.compile(
    r"^-?\d+\.\d{2},-?\d+\.\d{2},-?\d+\.\d{2},-?\d+\.\d{2}$"
)


def test_format_matches_regex():
    """CU-7: format_coords output matches the contract regex."""
    s = format_coords(1.23, -4.56, 0.78, 0.90)
    assert _COORD_FORMAT_REGEX.match(s), (
        f"format_coords({s!r}) does not match contract regex"
    )


def test_format_matches_for_representative_values():
    """CU-7: regex contract holds for diverse coordinate values."""
    cases = [
        (0.0, 0.0, 0.0, 0.0),
        (-1.0, -2.0, -3.0, -4.0),
        (123.45, 67.89, 0.01, 999.99),
        (10000.0, -5000.0, 0.001, 3.14159),
    ]
    for x, y, xi, u in cases:
        s = format_coords(x, y, xi, u)
        assert _COORD_FORMAT_REGEX.match(s), (
            f"format_coords({x}, {y}, {xi}, {u}) = {s!r} fails contract"
        )


def test_format_stable_across_calls():
    """CU-7: identical inputs produce identical output (format drift guard)."""
    a = format_coords(7.77, 3.33, 1.11, 9.99)
    b = format_coords(7.77, 3.33, 1.11, 9.99)
    assert a == b
    assert a == "7.77,3.33,1.11,9.99"


def test_round_trip_via_parse():
    """CU-7: format → parse recovers original 2-decimal values."""
    s = format_coords(5.0, -3.0, 0.5, 0.25)
    x, y, xi, u = parse_coords(s)
    assert x == pytest.approx(5.00)
    assert y == pytest.approx(-3.00)
    assert xi == pytest.approx(0.50)
    assert u == pytest.approx(0.25)


def test_parse_rejects_extra_whitespace():
    """CU-7: leading/trailing whitespace is NOT part of the contract."""
    with pytest.raises(ValueError):
        parse_coords(" 1.00,2.00,3.00,4.00")


# ── Hard-coded example (immutable contract anchor) ────────────────────────


def test_known_example_immutable():
    """CU-7: known example must not change — proves format stability."""
    result = format_coords(1.23, -4.56, 0.78, 0.90)
    assert result == "1.23,-4.56,0.78,0.90", (
        f"FORMAT DRIFT: expected '1.23,-4.56,0.78,0.90', got {result!r}\n"
        "This change breaks all trajectory-proximity queries and Immortus "
        "chain recall. Update callers first, then change this contract."
    )

"""A tiny Python project the calibration traffic works on.

The calibration tasks share ONE fixture repo: the Oracle bar needs DISTINCT
decision rows, and a distinct row comes from a distinct INPUT (the prompt),
not from a distinct workdir. The runner copies this repo for every task that
has no fixture of its own.
"""


def add(a: int, b: int) -> int:
    """Return the sum of two integers."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Return the product of two integers."""
    return a * b


def is_odd(n: int) -> bool:
    """Return True when ``n`` is odd, False otherwise."""
    return n % 2 != 0


def average(values: list[float]) -> float:
    """Return the arithmetic mean of ``values`` (0.0 for an empty list)."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def clamp(value: float, low: float, high: float) -> float:
    """Return ``value`` limited to the inclusive range [low, high]."""
    return max(low, min(high, value))

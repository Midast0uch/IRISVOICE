"""Human-readable billing output."""

from .core import calc_total


def report(items):
    """Format the total of the given items for display."""
    return f"Total: {calc_total(items):.2f}"

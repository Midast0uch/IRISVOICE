"""Core billing arithmetic."""


def calc_total(items):
    """Return the total of (unit_price, quantity) pairs."""
    return sum(price * qty for price, qty in items)

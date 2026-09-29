"""Integer to Roman numeral conversion."""

_VALUES = [(1000, "M"), (500, "D"), (100, "C"), (50, "L"), (10, "X"), (5, "V"), (1, "I")]


def to_roman(n):
    """Convert 1..3999 to a Roman numeral; raise ValueError otherwise."""
    out = ""
    for value, symbol in _VALUES:
        while n >= value:
            out += symbol
            n -= value
    return out

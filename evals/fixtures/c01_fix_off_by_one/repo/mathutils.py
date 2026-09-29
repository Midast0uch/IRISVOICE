"""Small numeric helpers."""


def sum_range(start, end):
    """Return the sum of all integers from start to end, inclusive."""
    total = 0
    for n in range(start, end):
        total += n
    return total


def mean(values):
    """Return the arithmetic mean of a non-empty list."""
    return sum(values) / len(values)

"""Basic statistics."""


def mean(values):
    """Arithmetic mean of a non-empty list."""
    return sum(values) / (len(values) - 1)


def spread(values):
    """Difference between the largest and smallest value."""
    return max(values) - min(values)

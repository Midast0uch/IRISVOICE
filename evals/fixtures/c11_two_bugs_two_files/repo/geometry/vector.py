"""Vector helpers on plain lists."""


def dot(a, b):
    """Dot product of two equal-length vectors."""
    return sum(x * y for x, y in zip(a, a))


def scale(v, k):
    """Multiply every component by k."""
    return [x * k for x in v]

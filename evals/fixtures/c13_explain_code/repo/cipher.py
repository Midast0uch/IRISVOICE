"""A toy text scrambler."""


def _shift(ch, k):
    if ch.isalpha() and ch.islower():
        return chr((ord(ch) - ord("a") + k) % 26 + ord("a"))
    return ch


def encode(text):
    """Shift each lowercase letter forward by 3, then reverse the result."""
    shifted = "".join(_shift(c, 3) for c in text)
    return shifted[::-1]

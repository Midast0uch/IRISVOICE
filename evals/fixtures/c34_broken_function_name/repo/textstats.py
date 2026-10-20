"""Small text statistics helpers."""


def word_count(text):
    """Return the number of words in text."""
    return len(text.split())


def longest_word(text):
    """Return the longest word in text, or '' when text is empty."""
    words = text.split()
    return min(words, key=len) if words else ""

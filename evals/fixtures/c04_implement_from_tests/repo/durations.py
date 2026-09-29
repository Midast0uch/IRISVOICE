"""Parse short duration strings such as "1h30m" into seconds."""


def parse_duration(text):
    """Return the number of seconds in a duration like "1h2m3s".

    Units are h, m and s, each used at most once, in that order.
    Raise ValueError for anything else, including an empty string.
    """
    raise NotImplementedError

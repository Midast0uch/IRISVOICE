from calculator import to_lower


def test_to_lower():
    assert to_lower("ABC") == "abc"
    assert to_lower("AbC") == "abc"


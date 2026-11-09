from calculator import to_upper


def test_to_upper():
    assert to_upper("abc") == "ABC"
    assert to_upper("aBc") == "ABC"


from calculator import reverse_string


def test_reverse():
    assert reverse_string("abc") == "cba"
    assert reverse_string("") == ""


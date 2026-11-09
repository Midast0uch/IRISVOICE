from calculator import is_odd


def test_is_odd():
    assert is_odd(3) is True
    assert is_odd(2) is False
    assert is_odd(7) is True

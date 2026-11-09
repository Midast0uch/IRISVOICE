from calculator import is_odd


def test_is_odd():
    assert is_odd(3) is True
    assert is_odd(0) is False
    assert is_odd(8) is False

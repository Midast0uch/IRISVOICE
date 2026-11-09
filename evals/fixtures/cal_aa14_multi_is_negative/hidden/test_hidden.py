from calculator import is_negative


def test_is_negative():
    assert is_negative(-1) is True
    assert is_negative(0) is False
    assert is_negative(1) is False

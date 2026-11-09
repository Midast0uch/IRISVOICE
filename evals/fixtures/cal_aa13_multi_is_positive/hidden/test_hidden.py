from calculator import is_positive


def test_is_positive():
    assert is_positive(1) is True
    assert is_positive(0) is False
    assert is_positive(-1) is False

from calculator import is_odd


def test_odd_and_even():
    assert is_odd(3) is True
    assert is_odd(4) is False
    assert is_odd(0) is False
    assert is_odd(-5) is True


from calculator import is_divisible_by


def test_divisible():
    assert is_divisible_by(10, 5) is True
    assert is_divisible_by(10, 3) is False
    assert is_divisible_by(0, 5) is True


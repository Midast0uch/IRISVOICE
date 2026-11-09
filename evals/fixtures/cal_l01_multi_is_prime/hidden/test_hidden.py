from calculator import is_prime


def test_even_and_odd():
    assert is_prime(2) is True
    assert is_prime(3) is True
    assert is_prime(4) is False
    assert is_prime(9) is False


def test_small_numbers():
    assert is_prime(0) is False
    assert is_prime(1) is False


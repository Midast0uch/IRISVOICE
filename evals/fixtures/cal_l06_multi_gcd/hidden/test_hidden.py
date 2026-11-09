from calculator import gcd


def test_gcd():
    assert gcd(12, 8) == 4
    assert gcd(7, 13) == 1
    assert gcd(0, 5) == 5


from calculator import negate


def test_negate():
    assert negate(5) == -5
    assert negate(0) == 0
    assert negate(-2) == 2

from calc import add, div, mul, power, sub


def test_add():
    assert add(2, 3) == 5


def test_add_negative():
    assert add(-2, -3) == -5


def test_sub():
    assert sub(5, 3) == 2


def test_mul():
    assert mul(4, 3) == 12


def test_div():
    assert div(7, 2) == 3.5


def test_power():
    assert power(2, 3) == 8


def test_mul_zero():
    assert mul(9, 0) == 0

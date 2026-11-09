from calculator import power


def test_power():
    assert power(2, 3) == 8
    assert power(5, 0) == 1
    assert power(3, 2) == 9

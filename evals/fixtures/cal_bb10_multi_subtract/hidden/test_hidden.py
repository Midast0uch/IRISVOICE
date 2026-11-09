from calculator import subtract


def test_subtract():
    assert subtract(5, 2) == 3
    assert subtract(2, 5) == -3
    assert subtract(4, 4) == 0

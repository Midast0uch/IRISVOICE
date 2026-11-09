from calculator import subtract_one


def test_subtract_one():
    assert subtract_one(2) == 1
    assert subtract_one(0) == -1
    assert subtract_one(-1) == -2

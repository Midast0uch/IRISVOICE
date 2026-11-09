from calculator import largest


def test_largest():
    assert largest(3, 7) == 7
    assert largest(7, 3) == 7
    assert largest(5, 5) == 5

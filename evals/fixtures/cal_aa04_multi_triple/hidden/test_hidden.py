from calculator import triple


def test_triple():
    assert triple(3) == 9
    assert triple(0) == 0
    assert triple(-1) == -3

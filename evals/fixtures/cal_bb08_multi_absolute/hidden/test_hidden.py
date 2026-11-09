from calculator import absolute


def test_absolute():
    assert absolute(-5) == 5
    assert absolute(5) == 5
    assert absolute(0) == 0

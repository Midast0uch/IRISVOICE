from calculator import cube


def test_cube():
    assert cube(2) == 8
    assert cube(0) == 0
    assert cube(-2) == -8

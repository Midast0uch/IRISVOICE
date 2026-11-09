from calculator import smallest


def test_smallest():
    assert smallest(3, 7) == 3
    assert smallest(7, 3) == 3
    assert smallest(5, 5) == 5

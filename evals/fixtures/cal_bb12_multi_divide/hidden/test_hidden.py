from calculator import divide


def test_divide():
    assert divide(6, 3) == 2
    assert divide(1, 2) == 0.5
    assert divide(0, 5) == 0

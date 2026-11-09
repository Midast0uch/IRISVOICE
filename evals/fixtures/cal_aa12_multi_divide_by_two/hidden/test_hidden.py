from calculator import divide_by_two


def test_divide_by_two():
    assert divide_by_two(4) == 2
    assert divide_by_two(0) == 0
    assert divide_by_two(3) == 1.5

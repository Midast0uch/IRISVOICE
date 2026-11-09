from calculator import min_of_two


def test_min_of_two():
    assert min_of_two(3, 5) == 3
    assert min_of_two(5, 3) == 3
    assert min_of_two(2, 2) == 2

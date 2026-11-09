from calculator import max_of_two


def test_max_of_two():
    assert max_of_two(3, 5) == 5
    assert max_of_two(5, 3) == 5
    assert max_of_two(2, 2) == 2

from calculator import multiply_by_ten


def test_multiply_by_ten():
    assert multiply_by_ten(3) == 30
    assert multiply_by_ten(0) == 0
    assert multiply_by_ten(-1) == -10

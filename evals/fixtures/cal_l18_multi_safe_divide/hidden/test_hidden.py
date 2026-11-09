from calculator import safe_divide


def test_safe_divide():
    assert safe_divide(6, 3) == 2.0
    assert safe_divide(1, 0) is None


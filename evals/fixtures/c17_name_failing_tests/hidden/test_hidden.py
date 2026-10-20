import conftest as h


def test_nothing_fixed_or_edited():
    assert h.unchanged("calc.py")
    assert h.unchanged("test_calc.py")

import conftest as h
from mathutils import mean, sum_range


def test_inclusive_end():
    assert sum_range(1, 5) == 15
    assert sum_range(3, 3) == 3
    assert sum_range(-2, 2) == 0


def test_other_function_untouched():
    assert mean([1, 2, 3, 4]) == 2.5


def test_visible_test_not_edited():
    assert h.unchanged("test_mathutils.py")

from mathutils import mean, sum_range


def test_sum_range():
    assert sum_range(1, 5) == 15


def test_mean():
    assert mean([2, 4, 6]) == 4

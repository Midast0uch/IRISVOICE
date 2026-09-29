from geometry.stats import mean, spread
from geometry.vector import dot, scale


def test_dot():
    assert dot([1, 2, 3], [4, 5, 6]) == 32


def test_scale():
    assert scale([1, 2], 3) == [3, 6]


def test_mean():
    assert mean([2, 4, 6]) == 4


def test_spread():
    assert spread([3, 9, 1]) == 8

import pytest

from calculator import add, average, clamp, multiply


def test_add():
    assert add(2, 3) == 5


def test_multiply():
    assert multiply(4, 5) == 20


def test_average():
    assert average([1.0, 2.0, 3.0]) == 2.0


def test_average_empty():
    assert average([]) == 0.0


def test_clamp():
    assert clamp(5, 0, 3) == 3
    assert clamp(-1, 0, 3) == 0
    assert clamp(2, 0, 3) == 2

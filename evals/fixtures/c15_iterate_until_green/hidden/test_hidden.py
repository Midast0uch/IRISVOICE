import conftest as h
import pytest
from roman import to_roman


@pytest.mark.parametrize("n,expected", [
    (4, "IV"), (49, "XLIX"), (944, "CMXLIV"), (2026, "MMXXVI"), (3999, "MMMCMXCIX"), (8, "VIII"),
])
def test_values(n, expected):
    assert to_roman(n) == expected


@pytest.mark.parametrize("n", [0, -1, 4000])
def test_range(n):
    with pytest.raises(ValueError):
        to_roman(n)


def test_visible_tests_not_edited():
    assert h.unchanged("test_roman.py")

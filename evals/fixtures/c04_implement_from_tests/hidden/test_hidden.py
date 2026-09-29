import conftest as h
import pytest
from durations import parse_duration


@pytest.mark.parametrize("text,seconds", [
    ("1h30m", 5400), ("45s", 45), ("2h", 7200), ("1h2m3s", 3723),
    ("10m", 600), ("0s", 0), ("3m7s", 187),
])
def test_valid(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["abc", "", "5x", "h", "1h1h"])
def test_invalid(text):
    with pytest.raises(ValueError):
        parse_duration(text)


def test_visible_tests_not_edited():
    assert h.unchanged("test_durations.py")

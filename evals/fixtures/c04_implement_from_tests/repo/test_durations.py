import pytest
from durations import parse_duration


def test_hours_and_minutes():
    assert parse_duration("1h30m") == 5400


def test_seconds_only():
    assert parse_duration("45s") == 45


def test_hours_only():
    assert parse_duration("2h") == 7200


def test_all_units():
    assert parse_duration("1h2m3s") == 3723


def test_invalid():
    with pytest.raises(ValueError):
        parse_duration("abc")

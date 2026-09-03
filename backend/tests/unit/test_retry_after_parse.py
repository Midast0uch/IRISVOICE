"""
Unit tests for ``parse_retry_after`` (REQ-2).

Pure-function tests — no HTTP, no I/O. Covers:
  * delta-seconds form (int / float)
  * HTTP-date form (converted to delta)
  * absent / empty / unparseable → None
  * negative delta → None (or 0 when clamped)
  * clamping to RETRY_AFTER_MAX_S
"""
import time

from backend.agent.inference.transport import parse_retry_after


def test_delta_seconds_integer():
    assert parse_retry_after("2") == 2.0


def test_delta_seconds_float():
    assert parse_retry_after("2.5") == 2.5


def test_http_date_form():
    # A date 3 seconds in the future → ~3.0s delta (allow clock skew)
    _future = time.strftime(
        "%a, %d %b %Y %H:%M:%S GMT", time.gmtime(time.time() + 3)
    )
    _val = parse_retry_after(_future)
    assert _val is not None
    assert 1.5 <= _val <= 3.5


def test_absent_header_returns_none():
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("   ") is None


def test_unparseable_returns_none():
    assert parse_retry_after("not-a-number") is None
    assert parse_retry_after("Wed, 21 Oct 2026") is None  # incomplete date


def test_negative_delta_clamped_to_zero():
    _past = time.strftime(
        "%a, %d %b %Y %H:%M:%S GMT", time.gmtime(time.time() - 10)
    )
    assert parse_retry_after(_past) == 0.0


def test_clamps_to_max():
    # 9999s exceeds the default 30s cap → clamped to 30.0
    assert parse_retry_after("9999") == 30.0

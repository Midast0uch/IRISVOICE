"""
Behavioral: a 429 retry ACTUALLY sleeps in the STREAMING path (REQ-1, T6.9/AC11).

Permanent guard for the original Wave 1 defect: in
``ApiHttpxTransport._stream`` the 429 branch called ``continue``, which jumped to
the next ``for attempt`` iteration and **skipped the backoff sleep** further down
the loop body. Three 429s were hammered with zero delay — the system amplified
the very condition that produced them.

The assertion is deliberately about the *streaming* path, because the
non-streaming paths always slept correctly and would mask the bug.
"""
from unittest.mock import patch

import pytest

from backend.agent.inference import transport as _tp
from backend.agent.inference.errors import RateLimitedError


class _FakeStreamResponse:
    """Minimal httpx stream-response stand-in that always 429s."""

    status_code = 429
    headers = {"Retry-After": "2"}
    text = "rate limited"

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def read(self):
        return b""

    def iter_lines(self):
        return iter(())

    def iter_bytes(self):
        return iter((b"",))


class _FakeClient:
    def __init__(self, *_a, **_kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def stream(self, *_a, **_kw):
        return _FakeStreamResponse()

    def post(self, *_a, **_kw):
        return _FakeStreamResponse()


def _run_stream_and_capture_sleeps():
    """Drive the streaming path against a always-429 server; record sleeps."""
    _sleeps = []
    _t = _tp.ApiHttpxTransport(
        api_base_url="https://api.example.test/v1",
        api_key="k",
        quota_id="https://api.example.test/v1|testfp",
    )
    with patch.object(_tp, "_perf_t") as _mock_time:
        _mock_time.sleep = lambda d: _sleeps.append(d)
        _mock_time.perf_counter = lambda: 0.0
        with patch("httpx.Client", _FakeClient):
            with pytest.raises(RateLimitedError):
                _t.generate(
                    "m",
                    [{"role": "user", "content": "hi"}],
                    None,
                    chunk_callback=lambda _c: None,  # forces the STREAM path
                )
    return _sleeps


def test_streaming_429_sleeps_before_each_retry():
    """REQ-1 AC1/AC2: every 429 retry with attempts remaining must sleep."""
    _sleeps = _run_stream_and_capture_sleeps()
    assert _sleeps, (
        "the streaming 429 path slept ZERO times — this is the exact defect "
        "(transport `continue` skipping the backoff sleep)"
    )
    # 3 attempts total => at most 2 inter-attempt sleeps (AC4: no terminal sleep).
    assert 1 <= len(_sleeps) <= 2, "expected 1-2 inter-attempt sleeps, got %s" % _sleeps
    assert all(d > 0 for d in _sleeps), "every sleep must be a real delay: %s" % _sleeps


def test_streaming_429_honors_retry_after_header():
    """REQ-2 AC1: the server-supplied Retry-After (2s) is preferred over backoff."""
    _sleeps = _run_stream_and_capture_sleeps()
    assert any(d == pytest.approx(2.0, abs=0.01) for d in _sleeps), (
        "Retry-After: 2 must be honored; slept %s" % _sleeps
    )


def test_streaming_429_raises_and_never_fabricates():
    """REQ-3 AC2/AC3: exhausted 429 retries raise — never return '(I see.)'."""
    _t = _tp.ApiHttpxTransport(
        api_base_url="https://api.example.test/v1",
        api_key="k",
        quota_id="https://api.example.test/v1|testfp",
    )
    with patch.object(_tp, "_perf_t") as _mock_time:
        _mock_time.sleep = lambda _d: None
        _mock_time.perf_counter = lambda: 0.0
        with patch("httpx.Client", _FakeClient):
            with pytest.raises(RateLimitedError) as _ei:
                _t.generate(
                    "m",
                    [{"role": "user", "content": "hi"}],
                    None,
                    chunk_callback=lambda _c: None,
                )
    assert "(I see.)" not in str(_ei.value)

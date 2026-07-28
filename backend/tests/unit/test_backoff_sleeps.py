"""
Unit tests for 429 retry backoff (REQ-1).

Verifies that when a transport receives HTTP 429 with attempts remaining, it
SLEEPS before the next attempt (the historical bug skipped the sleep, hammering
the provider with zero delay). Uses a fake clock + fake sleep so the test is
fast and deterministic.

Covers both streaming (ApiHttpxTransport._stream) and non-streaming
(ApiHttpxTransport._nonstream) paths.
"""
import time
from unittest.mock import MagicMock, patch

from backend.agent.inference.transport import ApiHttpxTransport


class _FakePerfClock:
    """Records sleep calls and advances a virtual clock."""

    def __init__(self):
        self.sleeps = []
        self._t = 1000.0

    def perf_counter(self):
        return self._t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self._t += seconds

    def time(self):
        return self._t

    def monotonic(self):
        return self._t


class _FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._lines = ["data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}", ""]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        for _l in self._lines:
            yield _l

    def read(self):
        return b""

    def json(self):
        return {"choices": [{"message": {"content": "hi"}}]}


class _FakeClient:
    """Returns 429 for the first N attempts, then 200."""

    def __init__(self, fail_count, headers=None):
        self._fail = fail_count
        self._calls = 0
        self._headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, *a, **k):
        self._calls += 1
        if self._calls <= self._fail:
            return _FakeResponse(429, self._headers)
        return _FakeResponse(200)

    def post(self, *a, **k):
        self._calls += 1
        if self._calls <= self._fail:
            return _FakeResponse(429, self._headers)
        return _FakeResponse(200)


def _make_transport():
    return ApiHttpxTransport(
        api_base_url="http://test", api_key="x"
    )


def test_stream_429_sleeps_before_retry():
    _clock = _FakePerfClock()
    _client = _FakeClient(fail_count=2)  # 2x 429, then 200
    with patch(
        "httpx.Client", return_value=_client
    ), patch(
        "backend.agent.inference.transport._perf_t", _clock
    ):
        _t = _make_transport()
        _out, _think, _tools = _t.generate(
            "m", [{"role": "user", "content": "hi"}], [], max_tokens=10,
            temperature=0.7, chunk_callback=lambda _: None,
            reasoning_callback=lambda _: None,
        )
    # Two 429s → two sleeps before the successful 3rd attempt.
    assert len(_clock.sleeps) == 2
    # Exponential backoff base=1.0, cap=8.0, with jitter → first sleep ~1.0-1.3
    assert 0.9 <= _clock.sleeps[0] <= 1.4
    assert _out == "hi"


def test_stream_429_no_sleep_on_final_attempt():
    _clock = _FakePerfClock()
    _client = _FakeClient(fail_count=3)  # all 3 attempts 429
    with patch(
        "httpx.Client", return_value=_client
    ), patch(
        "backend.agent.inference.transport._perf_t", _clock
    ):
        _t = _make_transport()
        try:
            _t.generate(
                "m", [{"role": "user", "content": "hi"}], [], max_tokens=10,
                temperature=0.7, chunk_callback=lambda _: None,
                reasoning_callback=lambda _: None,
            )
            assert False, "expected RateLimitedError"
        except Exception as _e:
            assert type(_e).__name__ == "RateLimitedError"
    # 3 attempts, 429 on all → sleeps only before attempts 1 and 2 (not final)
    assert len(_clock.sleeps) == 2


def test_nonstream_429_sleeps_before_retry():
    _clock = _FakePerfClock()
    _client = _FakeClient(fail_count=1)  # 1x 429, then 200
    with patch(
        "httpx.Client", return_value=_client
    ), patch(
        "backend.agent.inference.transport._perf_t", _clock
    ):
        _t = _make_transport()
        _out, _think, _tools = _t.generate(
            "m", [{"role": "user", "content": "hi"}], [], max_tokens=10,
            temperature=0.7, chunk_callback=lambda _: None,
            reasoning_callback=lambda _: None,
        )
    # One 429 → one sleep before the successful 2nd attempt.
    assert len(_clock.sleeps) == 1
    assert _out == "hi"


def test_retry_after_header_used_when_present():
    _clock = _FakePerfClock()
    _client = _FakeClient(fail_count=1, headers={"Retry-After": "5"})
    with patch(
        "httpx.Client", return_value=_client
    ), patch(
        "backend.agent.inference.transport._perf_t", _clock
    ):
        _t = _make_transport()
        _t.generate(
            "m", [{"role": "user", "content": "hi"}], [], max_tokens=10,
            temperature=0.7, chunk_callback=lambda _: None,
            reasoning_callback=lambda _: None,
        )
    # Retry-After: 5 → sleep should be ~5.0 (not exponential ~1.0)
    assert len(_clock.sleeps) == 1
    assert 4.5 <= _clock.sleeps[0] <= 5.5

"""CT-7 (REQ-6 AC6.3/AC6.4): transport Empty-retry contract.

The Empty disease — a provider 200 whose message has no content AND no
tool_calls — hit 4 downstream call sites across conv-96/97/98/99 with ZERO
retry, because the empty check sat AFTER the 3-attempt HTTP loop. The fix
moves the extraction + empty check INSIDE the loop so the SAME payload is
retried before the error is raised.

Contract pinned here:
  * empty response with attempts remaining  -> same payload retried (same URL,
    same body), not raised
  * empty on every attempt                  -> raises "Empty response from API"
    (the existing error, unchanged — downstream sub-loop handling depends on it)
  * RateLimitedError path (429 exhaustion)  -> UNCHANGED
  * non-200 path                            -> UNCHANGED (immediate RuntimeError)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agent.inference.transport import ApiHttpxTransport


class _FakePerfClock:
    """Fake clock so 429 backoff sleeps never stall the test run."""

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
    """httpx.Response stand-in for the non-streaming path."""

    def __init__(self, status_code, body=None, headers=None, text=""):
        self.status_code = status_code
        self._body = body or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._body


def _resp_content(content="ok"):
    return _FakeResponse(
        200, {"choices": [{"message": {"content": content}}]}
    )


def _resp_empty():
    # An OpenAI-compatible empty: 200, content=null (or absent), no tool_calls.
    return _FakeResponse(200, {"choices": [{"message": {"content": None}}]})


def _resp_429(headers=None):
    return _FakeResponse(429, {}, headers=headers or {}, text="rate limited")


def _resp_500():
    return _FakeResponse(500, {}, text="server error")


class _FakeClient:
    """Serves a scripted list of responses; records every post payload."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.bodies = []
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        self.calls += 1
        self.bodies.append({"url": url, "json": json})
        return self._responses[min(self.calls - 1, len(self._responses) - 1)]


def _make_transport():
    return ApiHttpxTransport(api_base_url="http://test", api_key="x")


def _run(client):
    with patch("httpx.Client", return_value=client), patch(
        "backend.agent.inference.transport._perf_t", _FakePerfClock()
    ):
        t = _make_transport()
        return t.generate(
            "m", [{"role": "user", "content": "hi"}], None,
            max_tokens=10, temperature=0.7,
        )


def test_empty_response_retries_same_payload_then_succeeds():
    """AC6.3: empty with attempts remaining -> SAME payload retried."""
    client = _FakeClient([_resp_empty(), _resp_content("recovered")])
    out, _think, _tools = _run(client)
    assert out == "recovered"
    assert client.calls == 2, "empty response must retry, not raise"
    # Same payload: identical url and body on both attempts.
    assert client.bodies[0]["url"] == client.bodies[1]["url"]
    assert client.bodies[0]["json"] == client.bodies[1]["json"]


def test_empty_response_exhaustion_raises_existing_error():
    """AC6.3: empty on all attempts -> the existing error text, unchanged."""
    client = _FakeClient([_resp_empty()])
    with pytest.raises(RuntimeError, match="Empty response from API"):
        _run(client)
    assert client.calls == 3, "all 3 attempts must be spent before raising"


def test_empty_with_tool_calls_only_is_not_empty():
    """A tool-call-only response (content=null) is the NORMAL tool-call shape
    — it must never be treated as Empty (the 2026-08-16 regression)."""
    client = _FakeClient([
        _FakeResponse(200, {"choices": [{"message": {
            "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "t", "arguments": "{}"}}],
        }}]}),
    ])
    _out, _think, tools = _run(client)
    assert len(tools) == 1
    assert client.calls == 1


def test_rate_limited_path_unchanged():
    """AC6.4: 429 exhaustion still raises RateLimitedError."""
    client = _FakeClient([_resp_429()])
    with pytest.raises(Exception) as exc_info:
        _run(client)
    assert type(exc_info.value).__name__ == "RateLimitedError"


def test_non_200_path_unchanged():
    """AC6.4: a non-200, non-429 response still fails immediately."""
    client = _FakeClient([_resp_500()])
    with pytest.raises(RuntimeError, match="API returned 500"):
        _run(client)
    assert client.calls == 1, "non-200 must not consume retries"


def test_empty_retry_does_not_mask_rate_limit():
    """A 429 followed by real 200 responses (even empty ones) terminates with
    the Empty error — the provider DID answer after the throttle, so the
    honest terminal state is the empty response, not the earlier 429. This is
    the EXISTING behavior (RateLimitedError fires only when result is None,
    i.e. every attempt was 429) and it must stay unchanged (AC6.4)."""
    client = _FakeClient([_resp_429(), _resp_empty(), _resp_empty()])
    with pytest.raises(RuntimeError, match="Empty response from API"):
        _run(client)
    assert client.calls == 3

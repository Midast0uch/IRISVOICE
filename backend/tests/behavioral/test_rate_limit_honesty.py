"""
Behavioral tests for rate-limit honesty (REQ-3).

Drives a transport that always returns 429 through the real generate() path and
asserts:
  * RateLimitedError is raised (NOT a "(I see.)" filler string)
  * The error carries provider_id and attempts
  * A genuine empty-content 200 still returns "(I see.)" (the only allowed case)

This is a behavioral test (not pure unit) because the bug was in the SEAM
between the 429 branch and the return statement — a unit test on either side
alone would not catch it.
"""
from unittest.mock import patch

from backend.agent.inference.errors import RateLimitedError
from backend.agent.inference.transport import ApiHttpxTransport


class _Always429:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, *a, **k):
        return _Resp429()

    def post(self, *a, **k):
        return _Resp429()


class _Resp429:
    status_code = 429
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        return iter([])

    def read(self):
        return b""

    def json(self):
        return {}


class _Empty200:
    status_code = 200
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, *a, **k):
        return self

    def iter_lines(self):
        return iter([])  # empty content

    def read(self):
        return b""

    def json(self):
        return {"choices": [{"message": {"content": ""}}]}


def _transport():
    return ApiHttpxTransport(
        api_base_url="http://test", api_key="x"
    )


def test_429_raises_rate_limited_not_filler():
    with patch(
        "httpx.Client", return_value=_Always429()
    ):
        _t = _transport()
        try:
            _t.generate(
                "m", [{"role": "user", "content": "hi"}], [], max_tokens=10,
                temperature=0.7, chunk_callback=lambda _: None,
                reasoning_callback=lambda _: None,
            )
            assert False, "expected RateLimitedError, got a return value"
        except RateLimitedError as _e:
            assert _e.attempts == 3
            assert _e.provider_id == "unknown"  # wired in T2.5
        except Exception as _e:
            assert False, f"wrong exception type: {type(_e).__name__}"


def test_genuine_empty_200_still_returns_filler():
    """REQ-3 AC3: the "(I see.)" fallback is preserved for a genuine
    empty-content 200 response (not a 429)."""
    with patch(
        "httpx.Client", return_value=_Empty200()
    ):
        _t = _transport()
        _out, _think, _tools = _t.generate(
            "m", [{"role": "user", "content": "hi"}], [], max_tokens=10,
            temperature=0.7, chunk_callback=lambda _: None,
            reasoning_callback=lambda _: None,
        )
    assert _out == "(I see.)"

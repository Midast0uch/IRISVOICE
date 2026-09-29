"""Regression (execution audit B16, 2026-09-29): a stream retry must never
duplicate text.

The reply buffer and tool-call accumulator were created once, outside the
3-attempt loop. A stream that failed after sending some text retried and
appended the new text after the partial copy, and the chat already showed
the partial copy. Both tests fail on that code.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from backend.agent.inference import transport as tr


def _sse(text):
    return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]})


class _FakeStream:
    """Yields its lines; with drop=True the connection then fails mid-stream."""

    def __init__(self, lines, drop=False):
        self.status_code = 200
        self.headers = {}
        self._lines = lines
        self._drop = drop

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        yield from self._lines
        if self._drop:
            raise ConnectionError("stream dropped")


class _FakeClient:
    """Serves one scripted stream per attempt (one Client per attempt)."""

    script: list = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def stream(self, *a, **kw):
        return _FakeClient.script.pop(0)


def _run(script):
    _FakeClient.script = list(script)
    chunks = []
    t = tr.OpenAICompatTransport("http://127.0.0.1:1")
    with patch("httpx.Client", _FakeClient), patch.object(tr._perf_t, "sleep", lambda s: None):
        result = t._stream("u", "u2", {}, chunks.append)
    return result, chunks


def test_failure_after_text_is_not_retried():
    partial = _FakeStream([_sse("Hello "), _sse("wor")], drop=True)
    retry = _FakeStream([_sse("Hello world"), "data: [DONE]"])
    with pytest.raises(ConnectionError):
        _run([partial, retry])


def test_failure_before_any_text_retries_cleanly():
    tool_frag = "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "c1", "function": {"name": "write_file", "arguments": "{\"pa"}}]}}]})
    broken = _FakeStream([tool_frag], drop=True)
    good = _FakeStream([_sse("Hello world"), "data: [DONE]"])
    (text, _thinking, tool_calls), chunks = _run([broken, good])
    assert text == "Hello world"
    assert "".join(chunks) == "Hello world"
    assert tool_calls == []  # the failed attempt's fragment is gone

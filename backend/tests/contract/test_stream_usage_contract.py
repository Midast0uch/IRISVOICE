"""A streamed API call asks for its real token counts (2026-10-26).

Before: a streamed reply carried no usage (Inception sends it only when asked), so every streamed call fell to a
char/4 estimate of the REPLY - a direct reply over a long conversation counted ~40 tokens and the context pill could
not show how full the window was. A provider that refuses the option streams without it from then on.
"""
from __future__ import annotations

import json
from contextlib import contextmanager

import httpx
import pytest

from backend.agent.inference import transport as tr

_URL = "https://api.example.test/v1/chat/completions"


class _Resp:
    def __init__(self, status, lines):
        self.status_code, self._lines, self.headers = status, lines, {}

    def iter_lines(self):
        return iter(self._lines)

    def iter_bytes(self):
        return iter([b'{"error": "unknown field stream_options"}'])

    def read(self):
        return b""


def _ok_lines():
    return ["data: " + json.dumps({"choices": [{"delta": {"content": "ok"}}]}),
            "data: " + json.dumps({"choices": [], "usage": {"prompt_tokens": 9000, "completion_tokens": 12,
                                                            "total_tokens": 9012}}),
            "data: [DONE]"]


def _fake_client(bodies, refuse):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @contextmanager
        def stream(self, method, url, headers=None, json=None):
            bodies.append(json)
            if refuse and "stream_options" in json:
                yield _Resp(400, [])
            else:
                yield _Resp(200, _ok_lines())
    return _Client


@pytest.fixture(autouse=True)
def _clean():
    tr._STREAM_USAGE_REFUSED.discard(_URL)
    yield
    tr._STREAM_USAGE_REFUSED.discard(_URL)


def _run(monkeypatch, refuse):
    bodies = []
    monkeypatch.setattr(httpx, "Client", _fake_client(bodies, refuse))
    t = tr.ApiHttpxTransport("https://api.example.test/v1", "k")
    text, _think, _tools = t._stream(_URL, {}, {"model": "m", "messages": []}, "m", [], lambda _c: None)
    return t, text, bodies


def test_a_stream_asks_for_usage_and_the_real_count_reaches_last_usage(monkeypatch):
    t, text, bodies = _run(monkeypatch, refuse=False)
    assert text == "ok"
    assert bodies[0]["stream"] is True and bodies[0]["stream_options"] == {"include_usage": True}
    assert t.last_usage and t.last_usage["prompt_tokens"] == 9000 and t.last_usage["total_tokens"] == 9012


def test_a_provider_that_refuses_the_option_streams_without_it_from_then_on(monkeypatch):
    t, text, bodies = _run(monkeypatch, refuse=True)
    assert text == "ok"
    assert "stream_options" in bodies[0] and "stream_options" not in bodies[1]
    assert _URL in tr._STREAM_USAGE_REFUSED
    _t2, _text2, bodies2 = _run(monkeypatch, refuse=True)
    assert all("stream_options" not in b for b in bodies2)        # remembered: no second refusal

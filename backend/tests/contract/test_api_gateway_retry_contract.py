"""Contract: a provider gateway 5xx is retried once inside the transport.

Eval c03 (2026-10-02, tool model mercury-2): Inception answered 504 after a
120 s stall. The transport raised at once, the node failed and lost its
history, and the step ran again from the start. A 502/503/504 is the
provider's transient fault: one retry keeps the node's work. A second 5xx, or
any other error status, still raises.
"""
from __future__ import annotations

import httpx
import pytest

from backend.agent.inference import transport as tmod
from backend.agent.inference.transport import ApiHttpxTransport

_OK = {"choices": [{"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}],
       "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}


@pytest.fixture()
def wire(monkeypatch):
    replies = []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            status, body = replies.pop(0)
            return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(tmod, "_record_attempt", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(tmod._perf_t, "sleep", lambda s: None)
    return replies


def _gen():
    return ApiHttpxTransport("https://api.example.test/v1", "k").generate(
        "m", [{"role": "user", "content": "x"}], max_tokens=64)


@pytest.mark.parametrize("status", [502, 503, 504])
def test_one_gateway_fault_is_retried(wire, status):
    wire += [(status, {"error": "gateway"}), (200, _OK)]
    assert _gen()[0] == "done"


def test_two_gateway_faults_raise(wire):
    wire += [(504, {"error": "gateway"}), (504, {"error": "gateway"})]
    with pytest.raises(RuntimeError, match="504"):
        _gen()


def test_a_client_error_is_not_retried(wire):
    wire += [(400, {"error": "bad request"}), (200, _OK)]
    with pytest.raises(RuntimeError, match="400"):
        _gen()

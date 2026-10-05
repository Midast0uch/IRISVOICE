"""Hedged request (2026-10-04) - a stalled provider request does not hold a turn.

Live 2026-10-04: mercury-2.5 calls p50 3.2 s, p90 4.6 s; 12 of 148 took >= 30 s
because the provider gave no answer for 30 s (the stall bound) and the SAME
request then answered in ~3 s. r06 lost 60 s of an 88 s turn this way.

Contract: with no answer after max(_HEDGE_MIN_S, 2 x p90) the transport sends
the same request again and returns the FIRST answer; with no profile there is
no hedge; the stall bound and its retry still stand behind it (see
test_api_stall_bound_contract.py).
"""
from __future__ import annotations

import threading
import time

import httpx
import pytest

from backend.agent.inference import transport as tmod
from backend.agent.inference.transport import ApiHttpxTransport, hedge_delay

BASE = "https://api.hedge.test/v1"
_OK = {"choices": [{"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}],
       "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(tmod, "_CALL_TIMES", {})
    monkeypatch.setattr(tmod, "_PROFILE_PATH", tmp_path / "model_call_times.json")
    monkeypatch.setattr(tmod, "_profile_state", {"loaded": False, "saved_at": 1e18})
    monkeypatch.setattr(tmod, "_record_attempt", lambda *a, **kw: None, raising=False)


def test_the_hedge_delay_comes_from_the_models_own_times():
    assert hedge_delay(BASE, "m", 30.0) is None  # never guess before 5 samples
    for s in (1.0, 2.0, 1.5, 2.5, 4.0, 1.2):
        tmod._record_call_time(BASE, "m", s)
    assert hedge_delay(BASE, "m", 30.0) == pytest.approx(8.0)  # 2 x p90 4.0
    assert hedge_delay(BASE, "m", 5.0) is None  # never past the read limit
    for _ in range(10):
        tmod._record_call_time(BASE, "fast", 0.5)
    assert hedge_delay(BASE, "fast", 30.0) == pytest.approx(tmod._HEDGE_MIN_S)


def test_a_stalled_request_is_hedged_and_the_first_answer_wins(monkeypatch):
    for s in (0.1, 0.1, 0.1, 0.1, 0.1):
        tmod._record_call_time(BASE, "m", s)
    # The delay is a parameter of the rule (max(min, 2 x p90)); a short floor
    # keeps the test fast without changing what it measures.
    monkeypatch.setattr(tmod, "_HEDGE_MIN_S", 0.3)
    release = threading.Event()
    posts = []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            release.set()  # closing the client ends the losing request
            return False

        def post(self, url, headers=None, json=None):
            posts.append(time.perf_counter())
            if len(posts) == 1:
                release.wait(20)  # the provider stalls this one
                raise httpx.ReadTimeout("stall", request=httpx.Request("POST", url))
            return httpx.Response(200, json=_OK, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "Client", _Client)
    t0 = time.perf_counter()
    text = ApiHttpxTransport(BASE, "k").generate(
        "m", [{"role": "user", "content": "x"}], max_tokens=64, timeout_s=300)[0]
    took = time.perf_counter() - t0
    assert text == "done"
    assert len(posts) == 2, "the same request was sent a second time"
    assert took < 3.0, f"the stalled request held the call {took:.1f} s"

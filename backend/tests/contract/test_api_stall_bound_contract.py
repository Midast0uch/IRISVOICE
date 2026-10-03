"""C6 guard (2026-10-02): a hosted model call far past its normal time is a
provider stall - the first attempt is bounded by the model's own profile and
retried once with the full timeout.

Live run A3: mercury-2 node calls took 1-3 s; one call took 121 s, because the
read timeout was the node's whole budget (up to 300 s). The task waited 2 min
for nothing.
"""
from __future__ import annotations

import httpx
import pytest

from backend.agent.inference import transport as tmod
from backend.agent.inference.transport import ApiHttpxTransport, stall_bound

BASE = "https://api.stall.test/v1"
_OK = {"choices": [{"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}],
       "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(tmod, "_CALL_TIMES", {})
    # Hermetic: the profile file is per test, never the app's data/ file.
    monkeypatch.setattr(tmod, "_PROFILE_PATH", tmp_path / "model_call_times.json")
    monkeypatch.setattr(tmod, "_profile_state", {"loaded": False, "saved_at": 1e18})
    monkeypatch.setattr(tmod, "_record_attempt", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(tmod._perf_t, "sleep", lambda s: None)


def test_no_profile_no_bound_then_a_bound_from_the_models_own_times():
    assert stall_bound(BASE, "m", 300) is None  # never guess before 5 samples
    for s in (1.0, 2.0, 1.5, 2.5, 3.0, 1.2):
        tmod._record_call_time(BASE, "m", s)
    assert stall_bound(BASE, "m", 300) == pytest.approx(30.0)  # floor: max(30, 4 x p90 3.0)
    assert stall_bound(BASE, "m", 20) is None  # never longer than the caller's own timeout
    for _ in range(30):
        tmod._record_call_time(BASE, "slow", 20.0)
    assert stall_bound(BASE, "slow", 300) == pytest.approx(80.0)  # a slow model keeps room


def test_a_stalled_first_attempt_is_cut_at_the_bound_and_retried(monkeypatch):
    for s in (1.0, 2.0, 1.5, 2.5, 3.0):
        tmod._record_call_time(BASE, "m", s)
    reads = []

    class _Client:
        def __init__(self, *a, timeout=None, **kw):
            self.read = timeout.read if timeout is not None else None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            reads.append(self.read)
            if len(reads) == 1:
                raise httpx.ReadTimeout("provider stall", request=httpx.Request("POST", url))
            return httpx.Response(200, json=_OK, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "Client", _Client)
    text = ApiHttpxTransport(BASE, "k").generate(
        "m", [{"role": "user", "content": "x"}], max_tokens=64, timeout_s=300)[0]
    assert text == "done"
    assert reads == [pytest.approx(30.0), pytest.approx(300.0)]


def test_the_profile_survives_a_restart(monkeypatch, tmp_path):
    """Run A6: a fresh backend had no profile, so Inception's 120 s hold before a
    504 was not bounded. The profile is saved (one lane writer) and reloaded."""
    for s_ in (1.0, 2.0, 1.5, 2.5, 3.0):
        tmod._record_call_time(BASE, "m", s_)
    tmod._save_profile({f"{b}|{m}": t for (b, m), t in tmod._CALL_TIMES.items()})
    monkeypatch.setattr(tmod, "_CALL_TIMES", {})  # a new process
    monkeypatch.setattr(tmod, "_profile_state", {"loaded": False, "saved_at": 1e18})
    assert stall_bound(BASE, "m", 300) == pytest.approx(30.0)

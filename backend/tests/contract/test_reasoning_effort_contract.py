"""Contract: the planner asks for a LOW hidden-reasoning budget, and only a
provider that takes the parameter ever sees it.

Measured 2026-10-05 (mercury-2.5, the planner prompt, 3 runs per cell): the
default effort spent ~1,300-1,650 hidden reasoning tokens and ~4 s on a 1-3
step plan; "low" spent ~250 tokens and 2.5-3.2 s with 6/6 valid plans. The
planner was 24% of reply time over 20 live turns.
"""
from __future__ import annotations

import inspect

import httpx
import pytest

from backend.agent.inference import transport as tmod
from backend.agent.inference.transport import ApiHttpxTransport

_OK = {"choices": [{"message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
       "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}


@pytest.fixture()
def bodies(monkeypatch):
    sent = []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            sent.append(json)
            return httpx.Response(200, json=_OK, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(tmod, "_record_attempt", lambda *a, **kw: None, raising=False)
    return sent


def _gen(provider_id, **kw):
    t = ApiHttpxTransport("https://api.example.test/v1", "k", quota_id=None)
    t._provider_id = provider_id
    return t.generate("m", [{"role": "user", "content": "plan"}], max_tokens=64, **kw)


def test_a_provider_that_takes_it_gets_the_effort(bodies):
    _gen("inceptionlabs", reasoning_effort="low")
    assert bodies[0]["reasoning_effort"] == "low"


def test_any_other_provider_is_sent_the_call_unchanged(bodies):
    _gen("openai", reasoning_effort="low")
    _gen("inceptionlabs")
    assert "reasoning_effort" not in bodies[0] and "reasoning_effort" not in bodies[1]


def test_the_planner_asks_for_low_effort():
    from backend.agent.agent_kernel import AgentKernel

    src = inspect.getsource(AgentKernel._plan_task)
    i = src.index('self._router.generate(\n                    "reasoning"')
    assert 'reasoning_effort="low"' in src[i:i + 900]

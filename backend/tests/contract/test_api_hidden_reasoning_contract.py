"""Contract: hidden reasoning never eats the caller's answer budget.

Measured 2026-10-02, Inception mercury-2.5 at max_tokens=1024 (a Brain call):
usage.completion_tokens_details.reasoning_tokens 818-979, finish_reason=length,
content 0-345 chars. The transport retried the SAME payload ("empty response
-- retrying same payload"), which is cut the same way, and a cut-off plan with
some text passed as a normal answer.

Pins: a reasoning-cut answer is resent ONCE with room for the reasoning; the
model's reasoning is learned, so the next call asks for answer + reasoning
from the start; a model that reports no reasoning is sent exactly as before.
"""
from __future__ import annotations

import httpx
import pytest

from backend.agent.inference import transport as tmod
from backend.agent.inference.transport import ApiHttpxTransport


def _reply(content, finish, reasoning=0):
    return {"choices": [{"message": {"role": "assistant", "content": content},
                         "finish_reason": finish}],
            "usage": {"prompt_tokens": 60, "completion_tokens": reasoning + 50, "total_tokens": 110 + reasoning,
                      "completion_tokens_details": {"reasoning_tokens": reasoning}}}


@pytest.fixture()
def wire(monkeypatch):
    sent, replies = [], []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            sent.append(json["max_tokens"])
            return httpx.Response(200, json=replies.pop(0), request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(tmod, "_record_attempt", lambda *a, **kw: None, raising=False)
    return sent, replies


def _t():
    return ApiHttpxTransport("https://api.example.test/v1", "k", quota_id=None)


def test_a_reasoning_cut_answer_is_resent_with_room(wire):
    sent, replies = wire
    replies += [_reply("", "length", reasoning=979), _reply("PLAN: step 1", "stop", reasoning=900)]
    text, _think, _tools = _t().generate("mercury-2.5", [{"role": "user", "content": "plan"}], max_tokens=1024)
    assert text == "PLAN: step 1"
    assert len(sent) == 2 and sent[0] == 1024 and sent[1] >= 1024 + 979


def test_a_cut_answer_with_some_text_is_not_accepted_as_done(wire):
    sent, replies = wire
    replies += [_reply("PLAN: st", "length", reasoning=818), _reply("PLAN: step 1, step 2", "stop", reasoning=800)]
    text, _think, _tools = _t().generate("mercury-2.5", [{"role": "user", "content": "plan"}], max_tokens=1024)
    assert text == "PLAN: step 1, step 2"


def test_the_next_call_asks_for_answer_plus_reasoning(wire):
    sent, replies = wire
    t = _t()
    replies += [_reply("ok", "stop", reasoning=700)]
    t.generate("mercury-2.5", [{"role": "user", "content": "a"}], max_tokens=1024)
    replies += [_reply("ok", "stop", reasoning=600)]
    t.generate("mercury-2.5", [{"role": "user", "content": "b"}], max_tokens=1024)
    assert sent == [1024, 1024 + 700]


def test_a_model_without_reasoning_is_sent_as_before(wire):
    sent, replies = wire
    t = _t()
    replies += [_reply("ok", "stop"), _reply("ok", "stop")]
    t.generate("plain-model", [{"role": "user", "content": "a"}], max_tokens=1024)
    t.generate("plain-model", [{"role": "user", "content": "b"}], max_tokens=1024)
    assert sent == [1024, 1024]

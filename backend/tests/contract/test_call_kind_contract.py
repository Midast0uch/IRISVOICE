"""Round 4 W0: what each model call is FOR, and how many HTTP requests it cost, on the
IRIS_CLM_BASELINE row (analysis: evals/wb_ab_analysis.py).

* ONE optional keyword on InferenceRouter.generate: call_kind (default "other"). It rides
  into the baseline row as "call_kind" and goes no further: no transport sees it.
* "sends" (int >= 1) on the row = HTTP requests the call made: the first send, a resend after
  "answer cut by ... hidden reasoning tokens", a hedge duplicate. Counted where every request
  is recorded (transport._record_attempt), per calling thread; behavior unchanged.
* The call sites: label (event_oracle brain_for), plan (_plan_task), synth (_synthesize_response,
  all three calls). node / code_node / wb_repair are pinned in test_workbench_round4_node_contract.
* Flag off (IRIS_CLM_BASELINE unset) nothing is written and the transport gets the same call.
"""
from __future__ import annotations

import ast
import threading

import httpx
import pytest

import backend.agent.inference.registry as _reg_mod
import backend.agent.inference.roles as _roles_mod
from backend.agent.inference import clm_baseline as cb
from backend.agent.inference import transport as tmod
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.transport import ApiHttpxTransport, sends_count, sends_reset
from backend.iris_config import InferenceConfig, ProviderEntry
from backend.tests._kernel_source import kernel_function_source


@pytest.fixture()
def router(monkeypatch):
    _reg_mod._REGISTRY = None
    _roles_mod._ROLES = None
    cfg = InferenceConfig()
    cfg.providers = {
        "p1": ProviderEntry(id="p1", label="p", kind="API", model="m1",
                            endpoint="https://api.example.test/v1", cred_ref="p1"),
    }
    r = InferenceRouter(cfg)
    r.bind_role("reasoning", "p1")
    rows = []

    class _Transport:
        """A FIXED signature: a stray call_kind keyword would raise TypeError."""
        last_usage = {"prompt_tokens": 40, "completion_tokens": 5, "total_tokens": 45}
        n_requests = 1

        def generate(self, model, messages, tools, max_tokens=None, temperature=None,
                     chunk_callback=None, reasoning_callback=None, timeout_s=None,
                     budget_check=None, num_ctx=None):
            for _ in range(self.n_requests):
                tmod._record_attempt(self)          # what a real transport does per request
            return ("ok", None, [])

    t = _Transport()
    monkeypatch.setattr(r, "_build_transport", lambda inst: t)
    monkeypatch.setenv(cb.ENV, "1")
    monkeypatch.setattr(cb, "_submit", lambda label, fn, *a: fn(*a))      # no lane: inline
    monkeypatch.setattr(cb, "_append", lambda row: rows.append(row))
    yield r, t, rows
    _reg_mod._REGISTRY = None
    _roles_mod._ROLES = None


_MSGS = [{"role": "user", "content": "hello"}]


def test_an_untagged_call_reads_other_and_a_tagged_call_reads_its_kind(router):
    r, _t, rows = router
    r.generate("reasoning", _MSGS)
    r.generate("reasoning", _MSGS, call_kind="plan")
    assert [x["call_kind"] for x in rows] == ["other", "plan"]


def test_the_kind_never_reaches_the_transport(router):
    r, _t, _rows = router
    assert r.generate("reasoning", _MSGS, call_kind="wb_repair") == ("ok", None, [])   # no TypeError


def test_sends_counts_every_request_of_one_call_and_never_below_one(router):
    r, t, rows = router
    t.n_requests = 0                                # a transport that records nothing: still >= 1
    r.generate("reasoning", _MSGS)
    t.n_requests = 2                                # a resend or a hedge
    r.generate("reasoning", _MSGS)
    t.n_requests = 1
    r.generate("reasoning", _MSGS)
    assert [x["sends"] for x in rows] == [1, 2, 1]


def test_a_failed_call_still_carries_its_kind_sends_and_seconds(router):
    r, t, rows = router

    def _boom(*a, **kw):
        tmod._record_attempt(t)
        tmod._record_attempt(t)
        raise RuntimeError("down")
    t.generate = _boom
    with pytest.raises(RuntimeError):
        r.generate("reasoning", _MSGS, call_kind="synth")
    (row,) = rows
    assert row["ok"] is False and row["call_kind"] == "synth" and row["sends"] == 2
    assert isinstance(row["seconds"], float) and row["seconds"] >= 0


def test_flag_off_writes_nothing(router, monkeypatch):
    r, _t, rows = router
    monkeypatch.delenv(cb.ENV)
    assert r.generate("reasoning", _MSGS, call_kind="plan") == ("ok", None, [])
    assert rows == []


# --- sends on the real transport -------------------------------------------------------
def _reply(content, finish, reasoning=0):
    return {"choices": [{"message": {"role": "assistant", "content": content},
                         "finish_reason": finish}],
            "usage": {"prompt_tokens": 60, "completion_tokens": reasoning + 50, "total_tokens": 110 + reasoning,
                      "completion_tokens_details": {"reasoning_tokens": reasoning}}}


def _t():
    return ApiHttpxTransport("https://api.example.test/v1", "k", quota_id=None)


def test_a_resend_after_a_reasoning_cut_counts_two_sends(monkeypatch):
    replies = [_reply("", "length", reasoning=979), _reply("PLAN", "stop", reasoning=900)]

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            return httpx.Response(200, json=replies.pop(0), request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "Client", _Client)
    sends_reset()
    _t().generate("mercury-2.5", [{"role": "user", "content": "plan"}], max_tokens=1024)
    assert sends_count() == 2


def test_a_plain_call_counts_one_send(monkeypatch):
    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            return httpx.Response(200, json=_reply("ok", "stop"), request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "Client", _Client)
    sends_reset()
    _t().generate("plain-model", [{"role": "user", "content": "a"}], max_tokens=1024)
    assert sends_count() == 1


def test_a_hedge_duplicate_counts_as_a_send(monkeypatch, tmp_path):
    base = "https://api.hedge.test/v1"
    monkeypatch.setattr(tmod, "_CALL_TIMES", {})
    monkeypatch.setattr(tmod, "_PROFILE_PATH", tmp_path / "model_call_times.json")
    monkeypatch.setattr(tmod, "_profile_state", {"loaded": False, "saved_at": 1e18})
    for s in (0.1, 0.1, 0.1, 0.1, 0.1):
        tmod._record_call_time(base, "m", s)
    monkeypatch.setattr(tmod, "_HEDGE_MIN_S", 0.3)
    release, posts = threading.Event(), []

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            release.set()
            return False

        def post(self, url, headers=None, json=None):
            posts.append(1)
            if len(posts) == 1:
                release.wait(20)
                raise httpx.ReadTimeout("stall", request=httpx.Request("POST", url))
            return httpx.Response(200, json=_reply("done", "stop"), request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "Client", _Client)
    sends_reset()
    ApiHttpxTransport(base, "k").generate("m", [{"role": "user", "content": "x"}],
                                          max_tokens=64, timeout_s=300)
    assert sends_count() == 2


def test_the_counter_is_per_calling_thread():
    sends_reset()
    tmod._record_attempt(object())
    seen = []
    th = threading.Thread(target=lambda: (sends_reset(), tmod._record_attempt(object()),
                                          tmod._record_attempt(object()), seen.append(sends_count())))
    th.start()
    th.join()
    assert seen == [2] and sends_count() == 1


# --- call sites -------------------------------------------------------------------------
def _router_generate_calls(fn_name):
    tree = ast.parse("class _C:\n" + "\n".join("    " + ln for ln in
                                               kernel_function_source(fn_name).splitlines()))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "generate":
            f = node.func.value
            if isinstance(f, ast.Attribute) and f.attr == "_router":
                out.append({k.arg: (k.value.value if isinstance(k.value, ast.Constant) else None)
                            for k in node.keywords})
    return out


def test_the_planner_call_is_tagged_plan():
    calls = _router_generate_calls("_plan_task")
    assert len(calls) == 1 and calls[0].get("call_kind") == "plan"
    assert calls[0].get("reasoning_effort") == "low"           # the tag did not move the effort


def test_every_synthesis_call_is_tagged_synth():
    calls = _router_generate_calls("_synthesize_response")
    assert len(calls) == 3 and all(c.get("call_kind") == "synth" for c in calls)


def test_the_user_feedback_label_call_is_tagged_label():
    from types import SimpleNamespace

    from backend.agent import event_oracle as eo

    seen = []

    def infer(prompt, role="x", max_tokens=1, temperature=0.0, **kw):
        seen.append((max_tokens, kw))
        return SimpleNamespace(raw_text="confirmation")
    assert eo.brain_for(SimpleNamespace(infer=infer))("p") == "confirmation"
    assert seen == [(16, {"call_kind": "label"})]


def test_an_infer_with_a_fixed_signature_is_called_as_before():
    from types import SimpleNamespace

    from backend.agent import event_oracle as eo

    seen = []

    def infer(prompt, role, max_tokens, temperature):
        seen.append(max_tokens)
        return SimpleNamespace(raw_text="none")
    assert eo.brain_for(SimpleNamespace(infer=infer))("p") == "none" and seen == [16]


def test_infer_passes_a_kind_to_the_router_only_when_given():
    from types import SimpleNamespace

    from backend.agent.kernel.models import ModelsMixin

    seen = []
    k = SimpleNamespace(_router=SimpleNamespace(
        generate=lambda role, messages, **kw: (seen.append(kw), ("t", None, []))[1],
        last_usage=None), _accrue_tokens=lambda *a, **kw: None)
    ModelsMixin.infer(k, "p", role="reasoning", max_tokens=16, call_kind="label")
    ModelsMixin.infer(k, "p", role="reasoning", max_tokens=16)
    assert "call_kind" in seen[0] and seen[0]["call_kind"] == "label"
    assert "call_kind" not in seen[1]

"""Context-window negotiation, across provider classes (2026-09-27).

WHY THIS FILE EXISTS

DER budgets every turn from the SMALLER context window of the two bound roles
(pinned in test_ctx_budget_source_contract.py:
test_ctb4_turn_budget_is_capped_by_the_smaller_window). That rule is right, so
the only way to stop a small tool model from throttling the whole agent is to
give the tool model a bigger REAL window. Two things were missing:

  1. Nothing in the backend ever asked for a window. `num_ctx` appeared nowhere,
     so an Ollama model was served whatever the server defaulted to, and the
     resolver could not see it.
  2. Nothing capped the prompt. A provider whose window the client cannot set
     (hosted API, OpenAI-compatible, in-process GGUF) would still be sent
     whatever we had, however large.

The contract, by provider class:

  | provider class                     | client owns the window?    | we do   |
  |------------------------------------|----------------------------|---------|
  | Ollama, local model                | YES                        | ask     |
  | Ollama, `-cloud` model             | NO (runs on ollama.com)    | no ask  |
  | hosted API (Cohere, Cerebras, ...)  | NO                        | cap     |
  | OpenAI-compatible endpoint          | NO (set at server start)  | cap     |
  | in-process local GGUF               | NO (set at load time)     | cap     |

Every provider ends up covered: one we can set, we set; one we cannot, we
resolve it and never exceed it.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agent.inference import router as router_mod
from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter
from backend.agent.inference.transport import ApiHttpxTransport, OllamaTransport


# ── Transport fakes (same pattern as test_transport_empty_retry_contract) ───

class _FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None, text=""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._body


class _FakeClient:
    """Records every POST payload it is asked to send."""

    def __init__(self, response):
        self._response = response
        self.bodies = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        self.bodies.append({"url": url, "json": json})
        return self._response


def _ollama_call(model, *, num_ctx):
    """Drive OllamaTransport once and return the captured request body."""
    client = _FakeClient(_FakeResponse(200, {"message": {"content": "hi"}}))
    with patch("httpx.Client", return_value=client):
        OllamaTransport(endpoint="http://test").generate(
            model,
            [{"role": "user", "content": "hi"}],
            None,
            max_tokens=8,
            num_ctx=num_ctx,
        )
    assert len(client.bodies) == 1
    return client.bodies[0]["json"]


# ── Part 1: the provider whose window we own ────────────────────────────────

def test_local_ollama_model_is_asked_for_the_window():
    """A local Ollama model gets options.num_ctx, so the window becomes OUR choice."""
    body = _ollama_call("granite3.3:8b", num_ctx=32_768)
    assert body.get("options", {}).get("num_ctx") == 32_768


def test_cloud_ollama_model_is_never_asked_for_a_window():
    """A -cloud model runs on ollama.com: no request field can raise its window,
    so the field must not be sent at all (a rejected field costs a turn)."""
    body = _ollama_call("gpt-oss:120b-cloud", num_ctx=32_768)
    assert "options" not in body


def test_no_window_requested_keeps_the_payload_as_it_was():
    """Without a resolved window nothing changes - the old payload shape stays."""
    body = _ollama_call("granite3.3:8b", num_ctx=None)
    assert "options" not in body


def test_api_transport_accepts_num_ctx_and_does_not_leak_it():
    """A hosted API cannot honour a window, so the parameter is accepted and
    dropped: it must never reach the wire as an unknown field."""
    client = _FakeClient(
        _FakeResponse(200, {"choices": [{"message": {"content": "ok"}}]})
    )
    with patch("httpx.Client", return_value=client):
        ApiHttpxTransport(api_base_url="http://test", api_key="k").generate(
            "command-r", [{"role": "user", "content": "hi"}], None,
            max_tokens=8, num_ctx=32_768,
        )
    assert client.bodies, "no request was sent"
    assert "num_ctx" not in client.bodies[0]["json"]
    assert "options" not in client.bodies[0]["json"]


# ── Part 2: the router offers the window and caps the prompt ────────────────

class _RecordingTransport:
    """Stands in for any transport; records what the router handed it."""

    def __init__(self):
        self.calls = []
        self.last_usage = None

    def generate(
        self,
        model,
        messages,
        tools=None,
        *,
        max_tokens=4096,
        temperature=0.6,
        chunk_callback=None,
        reasoning_callback=None,
        timeout_s=None,
        num_ctx=None,
    ):
        self.calls.append(
            {"model": model, "messages": messages, "num_ctx": num_ctx}
        )
        return ("ok", "", [])


@pytest.fixture(autouse=True)
def _no_phase_gate(monkeypatch):
    """The router's phase gate can WAIT. This file only cares about the payload,
    so the gate is a no-op here (it is fail-open in production)."""
    monkeypatch.setattr(router_mod, "acquire", lambda **kw: 0.0, raising=False)


def _router(resolver, recorder, *, model="granite3.3:8b"):
    reg = ProviderRegistry()
    reg.add(
        ProviderInstance(
            id="ollama", label="Ollama", kind=ProviderKind.OLLAMA,
            model=model, api_base_url="http://localhost:11434",
        )
    )
    r = InferenceRouter.__new__(InferenceRouter)
    for name, value in [
        ("_registry", reg),
        ("_roles", RoleBindingTable(reg)),
        ("_default_role", "reasoning"),
        ("_transports", {}),
        ("_inprocess_mgr", None),
    ]:
        object.__setattr__(r, name, value)
    r.bind_role("reasoning", "ollama")
    r.bind_role("tool_execution", "ollama")
    r.set_window_resolver(resolver)
    # Shadow the real transport builder: this file is about the payload.
    object.__setattr__(r, "_build_transport", lambda inst: recorder)
    return r


def test_router_passes_the_resolved_window_to_the_transport():
    """The window is OFFERED to the transport, and reported for callers."""
    rec = _RecordingTransport()
    r = _router(lambda role: 32_768, rec)
    r.generate("tool_execution", [{"role": "user", "content": "hi"}], None)
    assert rec.calls[0]["num_ctx"] == 32_768
    assert r.last_num_ctx == 32_768


def test_router_caps_a_prompt_that_cannot_fit_the_window():
    """The other half: a prompt larger than the window is trimmed to it. The old
    behaviour sent it anyway, to a model that cannot read it."""
    rec = _RecordingTransport()
    r = _router(lambda role: 4_096, rec)
    filler = "x" * 20_000  # ~5.7k tokens by the conservative estimate
    messages = [{"role": "system", "content": "sys"}] + [
        {"role": "user", "content": filler} for _ in range(6)
    ] + [{"role": "user", "content": "the request"}]

    r.generate("tool_execution", messages, None, max_tokens=256)

    sent = rec.calls[0]["messages"]
    assert len(sent) < len(messages), "an over-window prompt must be trimmed"
    assert sent[0]["role"] == "system", "the instructions survive the trim"
    assert sent[-1]["content"] == "the request", "the request itself survives"


def test_router_leaves_a_prompt_that_fits_completely_alone():
    """Trimming is a safety net, not a behaviour change: a normal prompt is
    handed over untouched."""
    rec = _RecordingTransport()
    r = _router(lambda role: 32_768, rec)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]
    r.generate("tool_execution", messages, None)
    assert rec.calls[0]["messages"] == messages


def test_router_without_a_resolver_behaves_exactly_as_before():
    """No resolver -> num_ctx None and messages untouched (backward compatible)."""
    rec = _RecordingTransport()
    r = _router(None, rec)
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]
    r.generate("tool_execution", messages, None)
    assert rec.calls[0]["num_ctx"] is None
    assert rec.calls[0]["messages"] == messages


def test_a_failing_resolver_never_breaks_a_turn():
    """Resolution is an optimisation. If it raises, the call still goes out."""

    def _boom(role):
        raise RuntimeError("no window for you")

    rec = _RecordingTransport()
    r = _router(_boom, rec)
    out, _thinking, _tools = r.generate(
        "tool_execution", [{"role": "user", "content": "hi"}], None
    )
    assert out == "ok"
    assert rec.calls[0]["num_ctx"] is None

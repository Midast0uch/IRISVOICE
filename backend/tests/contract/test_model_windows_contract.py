"""Every model shows its own real window, in the pill and in the switcher (owner 2026-11-23).

Measured before: every opencodego model read 128,000 (one provider-wide row; its Brain deepseek-v4.1-flash has 1,000,000),
clinepass and nvidia models read the 8,192 stand-in, Ollama's new cloud models too, and a model switch moved the pill only
at the next turn. Each test FAILS on the code before this change.
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from backend.agent.inference import provider_catalog as pc
from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.snapshot import build_inference_snapshot
from backend.agent.kernel.context import window_for

TABLE = [("opencodego", "deepseek", 128_000), ("openai", "gpt-4", 8_192), ("cerebras", "qwen-3.8-27b", 64_000)]


@pytest.fixture(autouse=True)
def caches(monkeypatch):
    monkeypatch.setattr(pc, "_API_WINDOWS", {})
    monkeypatch.setattr(pc, "_CATALOG_WINDOWS", {
        "opencode-go": {"deepseek-v4.1-flash": 1_000_000, "kimi-k2.7-code": 262_144},
        "opencode": {"kimi-k2.6": 262_144}, "cline-pass": {"cline-pass/kimi-k3": 1_048_576},
        "openai": {"gpt-4.1": 1_047_576}, "cerebras": {"qwen-3.8-27b": 131_072}})


@pytest.mark.parametrize("provider,model,tokens,source", [
    ("opencodego", "deepseek-v4.1-flash", 1_000_000, "catalog"),
    ("opencodego", "kimi-k2.7-code", 262_144, "catalog"),          # each model its own, not one per provider
    ("opencodego", "kimi-k2.6", 262_144, "catalog"),               # an older id: the wider list of the same provider
    ("clinepass", "cline-pass/kimi-k3", 1_048_576, "catalog"),
    ("openai", "gpt-4.1", 1_047_576, "catalog"),                   # an exact id beats the "gpt-4" substring (8,192)
    ("cerebras", "qwen-3.8-27b", 64_000, "catalog"),               # what this account is served, not the model's maximum
    ("openai", "gpt-4-0613", 8_192, "table"),
    ("opencodego", "no-such-model", 8_192, "default"),             # nobody states it: never a guess upward
])
def test_a_models_window_is_the_one_stated_for_it(provider, model, tokens, source):
    w = window_for(provider, model, "https://x.test/v1", TABLE, warn=False)
    assert (w.tokens, w.source) == (tokens, source)


def test_the_providers_own_list_outranks_the_catalog():
    pc._API_WINDOWS["https://x.test/v1"] = {"deepseek-v4.1-flash": 500_000}
    assert window_for("opencodego", "deepseek-v4.1-flash", "https://x.test/v1/", TABLE).tokens == 500_000


def test_no_window_lookup_touches_the_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network in a window lookup")
    monkeypatch.setattr("httpx.get", boom)
    window_for("opencodego", "deepseek-v4.1-flash", "https://x.test/v1", TABLE)


def test_an_ollama_cloud_model_publishes_and_a_local_one_does_not(monkeypatch):
    body = {"models": [{"name": "deepseek:cloud", "remote_host": "https://ollama.com", "details": {"context_length": 1_048_576}},
                       {"name": "llama3.2:latest", "details": {"context_length": 131_072}}]}   # memory on this machine, not a limit
    monkeypatch.setattr("httpx.get", lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: body))
    pc._fetch_ollama_windows("http://o.test")
    assert pc._API_WINDOWS["http://o.test"] == {"deepseek:cloud": 1_048_576}


def test_the_catalog_keeps_a_copy_and_never_holds_a_local_servers_window(monkeypatch, tmp_path):
    raw = {"opencode-go": {"models": {"m": {"limit": {"context": 7}}, "bad": {"limit": {}}}},
           "lmstudio": {"models": {"x": {"limit": {"context": 9}}}}, "unused": {"models": {"y": {"limit": {"context": 9}}}}}
    monkeypatch.setattr(pc, "_CATALOG_WINDOWS", {})
    monkeypatch.setattr(pc, "_catalog_path", lambda: tmp_path / "w.json")
    monkeypatch.setattr("httpx.get", lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: raw))
    pc._fetch_catalog()
    assert pc._CATALOG_WINDOWS == {"opencode-go": {"m": 7}} == json.loads((tmp_path / "w.json").read_text())

    def down(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr("httpx.get", down)
    pc._fetch_catalog()                                            # a failed refresh keeps the last copy
    assert pc.catalog_window("opencodego", "m") == 7 and pc._CATALOG_STATE["fetching"] is False


def _router(*insts, bindings=()):
    return SimpleNamespace(snapshot=lambda: {"providers": [], "role_bindings": [], "default_role": None},
                           registry=SimpleNamespace(list=lambda: list(insts)), roles=SimpleNamespace(list=lambda: list(bindings)))


def test_the_switcher_is_told_each_models_window_by_the_same_resolver():
    api = ProviderInstance(id="opencodego", label="o", kind=ProviderKind.API, model="deepseek-v4.1-flash")
    local = ProviderInstance(id="lm", label="l", kind=ProviderKind.LOCAL_OPENAI, model="q4")       # not loaded: nothing serves it
    unknown = ProviderInstance(id="openrouter", label="r", kind=ProviderKind.API, model="delisted/model")
    b = SimpleNamespace(instance_id="opencodego", model_override="kimi-k2.7-code", role="tool_execution")
    w = build_inference_snapshot(_router(api, local, unknown, bindings=[b]))["model_windows"]
    assert w["opencodego"]["deepseek-v4.1-flash"] == 1_000_000 and w["opencodego"]["kimi-k2.7-code"] == 262_144
    assert "lm" not in w and "delisted/model" not in w.get("openrouter", {})   # unknown is absent, never the 8,192 stand-in
    assert build_inference_snapshot(None)["model_windows"] == {}


def test_a_model_switch_moves_the_pill_at_once(monkeypatch):
    from backend import iris_gateway as gw

    said = []
    thread_kernel = SimpleNamespace(_emit_context_usage=lambda: said.append("thread"))
    inst = ProviderInstance(id="p", label="p", kind=ProviderKind.API, model="m")
    router = SimpleNamespace(registry=SimpleNamespace(get=lambda i: inst), bind_role=lambda *a, **k: None, snapshot=lambda: {},
                             _roles=SimpleNamespace(list=lambda: []))
    kernel = SimpleNamespace(_router=router, _emit_context_usage=lambda: said.append("default"))
    g = gw.IRISGateway.__new__(gw.IRISGateway)
    g._logger = logging.getLogger("t")
    g._active_conversation_id = {"s": "conv-1"}

    async def send(*a, **k):
        return None
    g._ws_manager = SimpleNamespace(send_to_client=send)

    async def persist(*a, **k):
        return None
    g._persist_and_broadcast_role_bindings = persist
    monkeypatch.setattr("backend.agent.get_agent_kernel", lambda conv=None, s=None, *a, **k: thread_kernel if conv == "conv-1" else kernel)
    monkeypatch.setattr(pc, "prefetch_api_windows", lambda insts: None)
    asyncio.run(g._handle_set_role_binding("s", "c", {"payload": {"role": "reasoning", "instance_id": "p"}}))
    assert said == ["thread"]

"""Contract: an API model's budget window is the window its provider publishes.

Eval runs 2026-10-02: Brain mercury-2.5 (Inception's /models says 260000) and
OpenRouter nemotron-3-super (262144) both resolved to the 8192 default, while a
local model resolves to its real loaded n_ctx. With 8192 the Brain answered
"read_file returned no content" for a file the node had read.

Pins: (1) a published window wins for BOTH roles (Brain and tool), tagged
"authoritative"; (2) an unpublished model still degrades loudly to 8192;
(3) the window lookup only reads the cache - it never fetches.
"""
from __future__ import annotations

import pytest

from backend.agent import agent_kernel as _ak
from backend.agent.inference import provider_catalog as pc
from backend.agent.inference.router import InferenceRouter
from backend.iris_config import InferenceConfig, ProviderEntry

import backend.agent.inference.registry as _reg_mod
import backend.agent.inference.roles as _roles_mod

_BASE = "https://api.example-provider.test/v1"


@pytest.fixture()
def kernel(monkeypatch):
    _reg_mod._REGISTRY = None
    _roles_mod._ROLES = None
    monkeypatch.setattr(pc, "_API_WINDOWS", {})
    cfg = InferenceConfig()
    cfg.providers = {
        "brainprov": ProviderEntry(id="brainprov", label="b", kind="API", model="big-model",
                                   endpoint=_BASE, cred_ref="brainprov"),
        "toolprov": ProviderEntry(id="toolprov", label="t", kind="API", model="fast-model",
                                  endpoint=_BASE + "/", cred_ref="toolprov"),
    }
    router = InferenceRouter(cfg)
    router.bind_role("reasoning", "brainprov")
    router.bind_role("tool_execution", "toolprov")
    k = _ak.AgentKernel.__new__(_ak.AgentKernel)
    k._context_window_overrides = {}
    k._router = router
    yield k
    _reg_mod._REGISTRY = None
    _roles_mod._ROLES = None


def test_published_windows_fund_both_roles(kernel):
    pc._API_WINDOWS[_BASE] = {"big-model": 260_000, "fast-model": 128_000}
    brain = kernel.resolve_context_window_with_source("reasoning")
    tool = kernel.resolve_context_window_with_source("tool_execution")
    assert (brain.tokens, brain.source) == (260_000, "authoritative")
    assert (tool.tokens, tool.source) == (128_000, "authoritative")


def test_an_unpublished_model_still_degrades_loudly(kernel, caplog):
    pc._API_WINDOWS[_BASE] = {"other-model": 64_000}
    res = kernel.resolve_context_window_with_source("reasoning")
    assert (res.tokens, res.source) == (8_192, "default")
    assert "no context window known" in caplog.text


def test_the_lookup_never_fetches(kernel, monkeypatch):
    def _no_network(*a, **kw):
        raise AssertionError("window lookup made a network call")
    monkeypatch.setattr("httpx.get", _no_network)
    monkeypatch.setattr(pc, "_fetch_api_windows", _no_network)
    kernel.resolve_context_window_with_source("reasoning")
    kernel.resolve_context_window_with_source("tool_execution")

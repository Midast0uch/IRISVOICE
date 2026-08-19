"""T16 (REQ-2, REQ-3 AC4) — WIRING guards.

Before T16, `grep -rn "resolve_vision_provider" backend/ --include=*.py`
outside tests returned ONLY its own definition and log lines: zero
production callers. All three vision consumers (`automation/vision.py`,
`vision_guided_operator.py`, `iris_gateway.py`) constructed the tier-3
`LFMVLProvider` directly, so production routed every vision task to the
dedicated VL server regardless of what the bound brain/tool could already
do — success criterion #1 ("a multimodal API brain answers a vision task
with ZERO local model loads") did not hold in the running system.

This file guards the three things that gap hid:
  (a) at least one REAL production consumer reaches
      `InferenceRouter.resolve_vision_provider()` — driven through
      `VisionGuidedOperator.find_element`, one of the three named call
      sites, not through `resolve_vision_client()` in isolation (that would
      only prove the new helper works, not that a consumer uses it).
  (b) a tier-1 multimodal brain serves a vision request with NO
      llama-server spawn (the whole point of the feature).
  (c) `VisionModelUnavailable` now PROPAGATES out of
      `resolve_vision_provider()` instead of being swallowed into a clean
      null resolution (the fix note in T16).

No GPU, no network, no real model loads, no real screenshots.
"""
from __future__ import annotations

import subprocess

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter, resolve_vision_client
from backend.agent.local_model_manager import LocalModelManager
from backend.agent.vision_guided_operator import VisionGuidedOperator
from backend.tools import lfm_vl_provider as vl


def _router_with(*instances: ProviderInstance) -> InferenceRouter:
    """Build a router bypassing __init__ (no config load, no side effects) —
    mirrors test_vision_capability_resolution.py / test_vision_routing_tier_
    permutations.py's own house style."""
    reg = ProviderRegistry()
    for inst in instances:
        reg.add(inst)
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", None)
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


class _FakeKernel:
    """Stand-in for AgentKernel — only the `_router` attribute matters to
    `resolve_vision_client()`'s `get_active_kernel("session_iris")` lookup."""

    def __init__(self, router: InferenceRouter) -> None:
        self._router = router


class _FakeHttpResponse:
    def __init__(self, content: str) -> None:
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


@pytest.fixture(autouse=True)
def _no_real_nvidia_smi(monkeypatch):
    """Block the real nvidia-smi subprocess so free-VRAM faking below is the
    only source of truth (this dev box has a real GPU)."""
    monkeypatch.setattr("shutil.which", lambda _name: None)


# ---------------------------------------------------------------------------
# (a) — a REAL production consumer reaches resolve_vision_provider().
# ---------------------------------------------------------------------------


def test_vision_guided_operator_reaches_resolve_vision_provider(monkeypatch):
    """VisionGuidedOperator.find_element (one of T16's three named call
    sites) must reach InferenceRouter.resolve_vision_provider() through
    resolve_vision_client() — the exact gap that hid the whole feature.
    Spies on the REAL method (not a stand-in), so a future revert to a bare
    `LFMVLProvider()` construction makes this call-count assertion fail.
    """
    monkeypatch.setattr(
        LocalModelManager, "get_hardware_info",
        lambda self, force_refresh=False: {"cuda_available": True, "vram_free_gb": 6.0},
    )

    brain = ProviderInstance(
        id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o",
        api_base_url="https://api.openai.com/v1",
    )
    router = _router_with(brain)
    router.roles.bind("reasoning", "openai")

    monkeypatch.setattr(
        "backend.agent.agent_kernel.get_active_kernel",
        lambda session_id: _FakeKernel(router),
    )
    monkeypatch.setattr(vl, "screenshot_to_bytes", lambda region=None: b"\x89PNG-fake")

    calls: list = []
    real_resolve = InferenceRouter.resolve_vision_provider

    def _spy(self):
        calls.append(True)
        return real_resolve(self)

    monkeypatch.setattr(InferenceRouter, "resolve_vision_provider", _spy)
    monkeypatch.setattr(
        "httpx.post", lambda *a, **kw: _FakeHttpResponse("x=42 y=99")
    )

    operator = VisionGuidedOperator(vision_server=object(), native_operator=None)

    import asyncio

    coords = asyncio.run(operator.find_element("the submit button"))

    assert calls, "resolve_vision_provider() was never reached from a production consumer"
    assert coords == (42, 99)


# ---------------------------------------------------------------------------
# (b) — tier-1 multimodal brain serves vision with NO llama-server spawn.
# ---------------------------------------------------------------------------


def test_tier1_brain_serves_via_consumer_with_no_spawn(monkeypatch):
    """Driven through the same production consumer as (a): a multimodal API
    brain answers, and NOTHING in the tier-3 spawn/discovery machinery is
    ever reached — the whole point of the feature, now proven reachable
    from real calling code, not only from resolve_vision_provider() in
    isolation (test_vision_routing_tier_permutations.py already covers
    that)."""
    monkeypatch.setattr(
        LocalModelManager, "get_hardware_info",
        lambda self, force_refresh=False: {"cuda_available": True, "vram_free_gb": 6.0},
    )

    brain = ProviderInstance(
        id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4o",
        api_base_url="https://api.openai.com/v1",
    )
    router = _router_with(brain)
    router.roles.bind("reasoning", "openai")

    monkeypatch.setattr(
        "backend.agent.agent_kernel.get_active_kernel",
        lambda session_id: _FakeKernel(router),
    )
    monkeypatch.setattr(vl, "screenshot_to_bytes", lambda region=None: b"\x89PNG-fake")

    def _spawn_spy(*_a, **_kw):
        raise AssertionError("llama-server spawn attempted despite a vision-capable brain")

    monkeypatch.setattr(subprocess, "Popen", _spawn_spy)

    def _find_spy():
        raise AssertionError("_find_vision_model called despite the brain answering directly")

    monkeypatch.setattr(vl, "_find_vision_model", _find_spy)

    lfm_call_spy: list = []
    monkeypatch.setattr(
        vl.LFMVLProvider, "_call",
        lambda self, *a, **kw: lfm_call_spy.append(True) or "unused",
    )

    posted: list = []

    def _fake_post(url, *, json, headers=None, timeout=None):
        posted.append((url, json, headers))
        return _FakeHttpResponse("x=10 y=20")

    monkeypatch.setattr("httpx.post", _fake_post)

    operator = VisionGuidedOperator(vision_server=object(), native_operator=None)

    import asyncio

    coords = asyncio.run(operator.find_element("the OK button"))

    assert coords == (10, 20)
    assert lfm_call_spy == [], "the tier-3 LFMVLProvider._call path must never run"
    assert len(posted) == 1
    url, payload, headers = posted[0]
    assert url == "https://api.openai.com/v1/chat/completions"
    assert payload["model"] == "gpt-4o"
    # No credential configured in this test -> no Authorization header sent,
    # proving the header is conditional, not hardcoded.
    assert "Authorization" not in (headers or {})


# ---------------------------------------------------------------------------
# (c) — VisionModelUnavailable propagates out of resolve_vision_provider().
# ---------------------------------------------------------------------------


def test_resolve_vision_provider_propagates_vision_model_unavailable(monkeypatch):
    """REQ-3 AC4 ("fail loudly") must reach resolve_vision_provider()'s own
    caller. Before the T16 fix, the tier-3 try/except caught
    VisionModelUnavailable like any other lookup failure and returned a
    clean VisionResolution(model_path=None) instead — silently defeating
    the user's decision at the hierarchy's own entry point."""
    monkeypatch.setattr(
        LocalModelManager, "get_hardware_info",
        lambda self, force_refresh=False: {"cuda_available": True, "vram_free_gb": 4.0},
    )
    brain = ProviderInstance(
        id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
    )
    router = _router_with(brain)
    router.roles.bind("reasoning", "cohere")

    def _raise_unavailable():
        raise vl.VisionModelUnavailable(
            "No vision-language model found on disk.",
            free_gb=4.0, smallest_requirement_gb=2.5, ladder=[],
        )

    monkeypatch.setattr(vl, "_find_vision_model", _raise_unavailable)

    with pytest.raises(vl.VisionModelUnavailable):
        router.resolve_vision_provider()


def test_resolve_vision_client_also_propagates_the_raise(monkeypatch):
    """The new production entry point (resolve_vision_client) must not
    swallow the raise either — a consumer catching VisionModelUnavailable
    (as vision_guided_operator.py and automation/vision.py now do) is the
    only thing standing between REQ-3 AC4 and an unhandled exception."""
    monkeypatch.setattr(
        LocalModelManager, "get_hardware_info",
        lambda self, force_refresh=False: {"cuda_available": True, "vram_free_gb": 4.0},
    )
    brain = ProviderInstance(
        id="cohere", label="Cohere", kind=ProviderKind.API, model="command-r-plus"
    )
    router = _router_with(brain)
    router.roles.bind("reasoning", "cohere")

    def _raise_unavailable():
        raise vl.VisionModelUnavailable(
            "No vision-language model found on disk.",
            free_gb=4.0, smallest_requirement_gb=2.5, ladder=[],
        )

    monkeypatch.setattr(vl, "_find_vision_model", _raise_unavailable)

    with pytest.raises(vl.VisionModelUnavailable):
        resolve_vision_client(router)

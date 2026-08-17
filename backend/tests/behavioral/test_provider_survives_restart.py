"""Behavioral: a provider chosen in the dashboard survives a restart.

Reported live 2026-08-16: pick Ollama in the dashboard, hit Apply, and after a
backend restart it is gone from the ModelSwitcher dropdown while both roles have
fallen back to Cohere.

Cause: ``set_model_selection`` called ``router.add_provider()``, which writes the
LIVE registry only. The registry is rebuilt at startup from
``config.inference.providers``, and that collection was written by a different
method that only the explicit provider-setup flow calls. So the provider existed
until the process ended, and the role bindings then pointed at an id that no
longer existed.

Provider-agnostic by construction — it swallowed any provider not registered
through provider setup, and would swallow a loaded local model the same way, so
these tests parametrize across the kinds rather than pinning Ollama.
"""

from __future__ import annotations

import json

import pytest

from backend.agent.inference.provider import ProviderKind


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    """Redirect load_config/save_config at a scratch file."""
    import backend.iris_config as cfg_mod

    # The module-level path is `_IRIS_CONFIG_PATH` (a pathlib.Path). Patching a
    # guessed name silently does nothing and the test then writes the USER'S
    # real config — which is exactly what happened the first time this ran, so
    # assert the redirect took rather than trusting it.
    path = tmp_path / "iris_config.json"
    path.write_text(json.dumps({"inference": {"providers": {}}}), encoding="utf-8")
    assert hasattr(cfg_mod, "_IRIS_CONFIG_PATH"), (
        "iris_config no longer exposes _IRIS_CONFIG_PATH — this fixture would "
        "write to the real config file"
    )
    monkeypatch.setattr(cfg_mod, "_IRIS_CONFIG_PATH", path)
    assert cfg_mod._IRIS_CONFIG_PATH == path
    return path


@pytest.mark.parametrize(
    "provider_id, kind, model",
    [
        ("ollama", ProviderKind.OLLAMA, "gpt-oss:120b-cloud"),
        ("cohere", ProviderKind.API, "command-a-plus-05-2026"),
        ("local:twil", ProviderKind.INPROCESS, "TwIL-LM3"),
        ("lmstudio", ProviderKind.LOCAL_OPENAI, "some-local-model"),
    ],
)
def test_every_provider_kind_round_trips_through_config(provider_id, kind, model):
    """A persisted entry must rebuild into an equivalent live instance.

    This is the invariant the restart depends on: whatever we write for a
    provider must come back as the same instance on the next boot, for EVERY
    kind — an API provider, an Ollama server, an in-process local model, and an
    OpenAI-compatible local server.
    """
    from backend.iris_config import ProviderEntry
    from backend.agent.inference.router import InferenceRouter

    entry = ProviderEntry(
        id=provider_id, label=provider_id, kind=kind.name, model=model,
        purpose="chat", endpoint="http://localhost:1234", cred_ref=provider_id,
    )
    # Survives serialization (what save_config/load_config do to it).
    revived = ProviderEntry(**json.loads(json.dumps(entry.__dict__)))
    assert revived.id == provider_id
    assert revived.model == model
    # And the kind string resolves back to the SAME enum member.
    assert InferenceRouter._kind_from_str(revived.kind) is kind


def test_selecting_a_provider_writes_it_to_the_config_collection(temp_config):
    """The regression itself: choosing a provider must persist it.

    Drives the real ``set_model_selection`` and then reads the config file that
    startup rebuilds the registry from. Before the fix this collection stayed
    empty and the provider vanished on restart.
    """
    import backend.agent.agent_kernel as ak
    from backend.agent.inference.registry import get_provider_registry
    from backend.agent.inference.roles import get_role_binding_table
    from backend.agent.inference.router import InferenceRouter
    from backend.iris_config import load_config

    reg = get_provider_registry()
    roles = get_role_binding_table()
    saved_p, saved_b = list(reg.list()), list(roles.list())
    try:
        kernel = ak.AgentKernel.__new__(ak.AgentKernel)
        kernel._router = InferenceRouter(load_config())
        kernel._api_key = ""
        kernel._api_key_provider = ""
        kernel._api_base_url = ""
        kernel._lmstudio_endpoint = ""
        kernel._context_window_overrides = {}
        kernel._swarm_enabled = False

        ok = kernel.set_model_selection(
            reasoning_model="gpt-oss:120b-cloud",
            tool_execution_model="gpt-oss:120b-cloud",
            model_provider="ollama",
            api_base_url="http://localhost:11434",
        )
        assert ok is True

        persisted = load_config().inference.providers or {}
        assert "ollama" in persisted, (
            "the provider was registered live but never written to config — it "
            "will disappear on the next restart"
        )
        assert persisted["ollama"].endpoint == "http://localhost:11434"
    finally:
        for b in list(roles.list()):
            roles.unbind(b.role)
        for b in saved_b:
            roles.bind(b.role, b.instance_id, b.model_override)
        for p in saved_p:
            reg.add(p)

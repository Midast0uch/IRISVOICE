"""Phase 1 Wave 5 — behavioral tests for the foundation.

These drive fuller scenarios through the real router + config stack and assert
emergent properties: bindings survive a config reload, an upgrade preserves an
existing provider, and resolution never silently falls back to a different
provider.
"""
from __future__ import annotations

import pytest

from backend.agent.inference.router import InferenceRouter
from backend.iris_config import InferenceConfig, ProviderEntry


@pytest.fixture(autouse=True)
def _fresh_registry():
    import backend.agent.inference.registry as _reg
    import backend.agent.inference.roles as _roles

    _reg._REGISTRY = None
    _roles._ROLES = None
    yield
    _reg._REGISTRY = None
    _roles._ROLES = None


def _cfg_with(entries, extra_flat=None):
    cfg = InferenceConfig()
    cfg.providers = {e.id: e for e in entries}
    cfg.config_version = 2
    # Bind each provider to a distinct role so bindings don't overwrite.
    _roles = ["reasoning", "tool_execution", "embedding", "rerank"]
    cfg.role_bindings = [
        {"role": _roles[i % len(_roles)], "instance_id": e.id}
        for i, e in enumerate(entries)
    ]
    if extra_flat:
        for k, v in extra_flat.items():
            setattr(cfg, k, v)
    return cfg


def test_binding_survives_restart():
    e = ProviderEntry(id="cerebras", label="Cerebras", kind="API",
                      model="gemma", endpoint="https://cb", cred_ref="cerebras")
    cfg = _cfg_with([e])
    r1 = InferenceRouter(cfg)
    assert r1.resolve("reasoning").id == "cerebras"
    # Simulate a restart: rebuild the router from the same (persisted) config.
    r2 = InferenceRouter(cfg)
    assert r2.resolve("reasoning").id == "cerebras"


def test_upgrade_preserves_existing_provider():
    # Legacy flat config (no collection) -> migration populates the collection
    # and preserves the provider. The key is moved into the keyring.
    cfg = InferenceConfig.from_dict({
        "provider": "cerebras",
        "api_key": "topsecret",
        "reasoning_model": "gemma-4-31b",
        "api_base_url": "https://cb",
    })
    assert "cerebras" in cfg.providers
    assert cfg.providers["cerebras"].cred_ref == "cerebras"
    # Keyring holds the migrated credential (not the flat config).
    from backend.agent.inference.keyring import get_secret

    assert get_secret("cerebras") == "topsecret"
    # config_version bumped so migration does not re-run.
    assert cfg.config_version == 2


def test_collection_wins_over_flat_on_upgrade():
    # If BOTH a collection and flat fields exist, the collection wins and the
    # flat fields are NEVER merged in (no silent duplicate provider).
    cfg = InferenceConfig.from_dict({
        "provider": "cerebras",  # flat
        "api_key": "x",
        "providers": {
            "openai": {
                "id": "openai", "label": "OpenAI", "kind": "API",
                "model": "gpt-4o", "endpoint": "https://oa", "cred_ref": "openai",
            }
        },
        "config_version": 1,
    })
    # Collection ("openai") is preserved; flat "cerebras" is NOT merged in.
    assert set(cfg.providers.keys()) == {"openai"}


def test_no_silent_provider_fallback():
    e = ProviderEntry(id="cerebras", label="Cerebras", kind="API",
                      model="gemma", endpoint="https://cb", cred_ref="cerebras")
    e2 = ProviderEntry(id="openai", label="OpenAI", kind="API",
                       model="gpt", endpoint="https://oa", cred_ref="openai")
    cfg = _cfg_with([e, e2])
    r = InferenceRouter(cfg)
    # A bound role resolves to the bound provider, never a silent swap to the
    # other registered provider.
    assert r.resolve("reasoning").id == "cerebras"
    # The default role is used for unbound roles (predictable, not a silent
    # swap to a different provider). It must resolve to one of the configured
    # providers, not invent an unconfigured one.
    default = r.resolve("some_unbound_role")
    assert default.id in ("cerebras", "openai")

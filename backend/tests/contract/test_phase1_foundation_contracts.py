"""Phase 1 Wave 5 — contract tests CT-F1..CT-F9.

These pin the Phase 1 foundation contracts: one provider collection, one
process-wide registry, namespaced local ids, atomic endpoint+credential writes,
additive snapshot payload, binding-before-load allowed, and routing mode frozen.

The process-wide registry/roles singletons are reset per test so assertions about
"both present" / "exactly N" are isolated.
"""
from __future__ import annotations

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import get_provider_registry
from backend.agent.inference.roles import get_role_binding_table
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


def _router(entries=(), bindings=(), local_model_id="", provider="api"):
    cfg = InferenceConfig()
    cfg.provider = provider
    cfg.local_model_id = local_model_id
    cfg.providers = {e.id: e for e in entries}
    cfg.config_version = 2
    cfg.role_bindings = list(bindings)
    return InferenceRouter(cfg)


# CT-F1: two providers survive the config serialization (restart) path.
def test_two_providers_survive_restart():
    e1 = ProviderEntry(id="cerebras", label="Cerebras", kind="API",
                       model="gemma-4-31b", endpoint="https://cb", cred_ref="cerebras")
    e2 = ProviderEntry(id="openai", label="OpenAI", kind="API",
                       model="gpt-4o", endpoint="https://oa", cred_ref="openai")
    cfg = InferenceConfig()
    cfg.providers = {e1.id: e1, e2.id: e2}
    cfg.config_version = 2
    # Serialize + deserialize (the restart mechanism).
    cfg2 = InferenceConfig.from_dict(cfg.to_dict())
    assert set(cfg2.providers.keys()) == {"cerebras", "openai"}


# CT-F2: adding a second provider does not erase the first.
def test_second_provider_does_not_erase_first():
    e1 = ProviderEntry(id="cerebras", label="Cerebras", kind="API",
                       model="gemma", endpoint="https://cb", cred_ref="cerebras")
    e2 = ProviderEntry(id="openai", label="OpenAI", kind="API",
                       model="gpt", endpoint="https://oa", cred_ref="openai")
    r = _router(entries=[e1, e2])
    ids = {i.id for i in r.registry.list()}
    assert ids == {"cerebras", "openai"}


# CT-F3: the phase-scheduler gate call inside generate() survives the refactor.
def test_phase_gate_called_in_generate(monkeypatch):
    e = ProviderEntry(id="cerebras", label="Cerebras", kind="API",
                      model="gemma", endpoint="https://cb", cred_ref="cerebras")
    r = _router(entries=[e], bindings=[{"role": "reasoning", "instance_id": "cerebras"}])
    called = {}

    def _fake_acquire(*a, **k):
        called["acquire"] = True
        return True

    class _FakeTransport:
        def generate(self, *a, **k):
            yield "ok"

    def _fake_build_transport(*a, **k):
        return _FakeTransport()

    import backend.agent.inference.router as _router_mod

    monkeypatch.setattr(_router_mod, "acquire", _fake_acquire)
    monkeypatch.setattr(r, "_build_transport", _fake_build_transport)
    list(r.generate(messages=[{"role": "user", "content": "hi"}], role="reasoning", model="gemma"))
    assert called.get("acquire") is True, "phase gate (acquire) not invoked in generate()"


# CT-F4: atomic write rejects an endpoint-without-credential (or vice versa) for
# a NEW provider; both together succeed.
def test_atomic_write_rejects_mismatch():
    r = _router()
    # New provider, endpoint but no credential -> rejected.
    with pytest.raises(ValueError):
        r.write_provider(
            ProviderEntry(id="newp", label="New", kind="API", endpoint="https://x")
        )
    # New provider, credential but no endpoint -> rejected.
    with pytest.raises(ValueError):
        r.write_provider(
            ProviderEntry(id="newp2", label="New2", kind="API"), credential="secret"
        )
    # Both together -> accepted.
    r.write_provider(
        ProviderEntry(id="newp3", label="New3", kind="API", endpoint="https://y"),
        credential="secret",
    )
    assert r.registry.get("newp3") is not None


# CT-F5: local provider ids are namespaced, never the bare literal "local".
def test_local_id_namespaced():
    # Local providers are registered from config via the migration path.
    cfg = InferenceConfig.from_dict(
        {"provider": "local", "local_model_id": "qwen3-9b-q4_k_m.gguf"}
    )
    r = InferenceRouter(cfg)
    ids = {i.id for i in r.registry.list()}
    assert "local" not in ids
    assert any(i.startswith("local:") for i in ids)
    assert "local:qwen3-9b-q4_k_m" in ids


# CT-F6: snapshot payload retains id/label/kind/model/api_base_url/has_key and
# adds loaded/loading/purpose; NO credential or credential fragment.
def test_snapshot_payload_shape():
    e = ProviderEntry(id="cerebras", label="Cerebras", kind="API",
                      model="gemma", endpoint="https://cb", cred_ref="cerebras")
    r = _router(entries=[e], bindings=[{"role": "reasoning", "instance_id": "cerebras"}])
    snap = r.snapshot()
    prov = next(p for p in snap["providers"] if p["id"] == "cerebras")
    for field in ("id", "label", "kind", "model", "api_base_url", "has_key",
                 "loaded", "loading", "purpose"):
        assert field in prov, f"snapshot missing {field}"
    # No credential may leak into the payload.
    assert "api_key" not in prov
    assert "cred_ref" not in prov
    assert "secret" not in str(prov)


# CT-F7: binding to a local provider before its model is loaded is ALLOWED
# (status flag, not a veto).
def test_bind_before_load_allowed():
    # Local provider registered from config via migration (not yet loaded).
    cfg = InferenceConfig.from_dict(
        {"provider": "local", "local_model_id": "qwen3-9b-q4_k_m.gguf"}
    )
    r = InferenceRouter(cfg)
    local_id = next(i.id for i in r.registry.list() if i.id.startswith("local:"))
    # Not loaded yet.
    assert r.registry.get(local_id).loaded is False
    # Binding must succeed (no veto — it becomes live once the model loads).
    r.bind_role("reasoning", local_id)
    assert r.resolve("reasoning").id == local_id


# CT-F8: two local models both register (no collision / no shadowing).
def test_two_local_models():
    e1 = ProviderEntry(id="local:qwen3-9b", label="Qwen", kind="LOCAL_OPENAI",
                       model="qwen3-9b", endpoint="http://127.0.0.1:8081")
    e2 = ProviderEntry(id="local:llama3-8b", label="Llama", kind="LOCAL_OPENAI",
                       model="llama3-8b", endpoint="http://127.0.0.1:8082")
    r = _router(entries=[e1, e2])
    ids = {i.id for i in r.registry.list()}
    assert ids == {"local:qwen3-9b", "local:llama3-8b"}


# CT-F9: the routing selector (provider) is frozen — survives a config
# round-trip for every value. Phase 1 must not alter which backend serves.
@pytest.mark.parametrize("prov", ["api", "lm_studio", "ollama", "iris_local"])
def test_routing_selector_frozen(prov):
    cfg = InferenceConfig()
    cfg.provider = prov
    cfg2 = InferenceConfig.from_dict(cfg.to_dict())
    assert cfg2.provider == prov

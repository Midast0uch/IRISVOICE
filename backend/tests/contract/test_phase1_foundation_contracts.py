"""Phase 1 Wave 5 — contract tests CT-F1..CT-F9.

These pin the Phase 1 foundation contracts: one provider collection, one
process-wide registry, namespaced local ids, atomic endpoint+credential writes,
additive snapshot payload, binding-before-load allowed, and routing mode frozen.

The process-wide registry/roles singletons are reset per test so assertions about
"both present" / "exactly N" are isolated.

NOTE (2026-07-29): CT-F2 (`test_second_provider_does_not_erase_first`) and CT-F8
(`test_two_local_models`) assert exact registry-id sets scoped to purpose="chat".
Phase 4's register_builtin_encoder_providers() (backend/agent/inference/provider.py
:115-151) runs from InferenceRouter.__init__ (backend/agent/inference/router.py:93-94),
so every router built here also registers "embedding:lfm25-emb-350m" — a real,
intended provider outside what CT-F2/CT-F8 were ever meant to pin. See
test_encoder_provider_registered_embedding_not_chat_bound below for the coverage
this scoping would otherwise have dropped.
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


# CT-F2: adding a second (chat) provider does not erase the first.
#
# Scoped to purpose="chat" (2026-07-29): Phase 4's
# register_builtin_encoder_providers() (backend/agent/inference/provider.py:115-151)
# is invoked from InferenceRouter.__init__ (backend/agent/inference/router.py:93-94),
# so constructing ANY router — including the one this test builds — also
# registers "embedding:lfm25-emb-350m" into the process-wide registry. A
# registry-reset fixture does not change that; the encoder is added by this
# test's own router construction, not leaked from a prior test. Phase 1's
# REQ-6 only requires that a provider collection keyed by id does not erase
# entries within the SAME purpose; it never required "no other provider of
# any purpose exists" — that guarantee is now false by Phase 4 design, so the
# assertion is narrowed to the chat scope it actually covers. Exact-set
# equality is preserved WITHIN that scope.
def test_second_provider_does_not_erase_first():
    e1 = ProviderEntry(id="cerebras", label="Cerebras", kind="API",
                       model="gemma", endpoint="https://cb", cred_ref="cerebras")
    e2 = ProviderEntry(id="openai", label="OpenAI", kind="API",
                       model="gpt", endpoint="https://oa", cred_ref="openai")
    r = _router(entries=[e1, e2])
    chat_ids = {i.id for i in r.registry.list() if (i.purpose or "chat") == "chat"}
    assert chat_ids == {"cerebras", "openai"}


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


# CT-F8: two local (chat) models both register (no collision / no shadowing).
#
# Scoped to purpose="chat" for the same reason as test_second_provider_does_not_
# erase_first above: constructing the router also registers Phase 4's
# "embedding:lfm25-emb-350m" (purpose="embedding"). Exact-set equality is
# preserved within the chat scope this test actually exercises.
def test_two_local_models():
    e1 = ProviderEntry(id="local:qwen3-9b", label="Qwen", kind="LOCAL_OPENAI",
                       model="qwen3-9b", endpoint="http://127.0.0.1:8081")
    e2 = ProviderEntry(id="local:llama3-8b", label="Llama", kind="LOCAL_OPENAI",
                       model="llama3-8b", endpoint="http://127.0.0.1:8082")
    r = _router(entries=[e1, e2])
    chat_ids = {i.id for i in r.registry.list() if (i.purpose or "chat") == "chat"}
    assert chat_ids == {"local:qwen3-9b", "local:llama3-8b"}


# CT-F8b (new coverage, 2026-07-29): the encoder provider Phase 4 registers as
# a side effect of every router construction is visible with purpose=
# "embedding" and is never bound to a chat-serving role (reasoning /
# tool_execution). This is the coverage that narrowing CT-F2/CT-F8 to the
# chat scope would otherwise have dropped.
def test_encoder_provider_registered_embedding_not_chat_bound():
    r = _router()
    inst = r.registry.get("embedding:lfm25-emb-350m")
    assert inst is not None, "Phase 4 encoder provider not registered"
    assert inst.purpose == "embedding"
    bound_ids = {b.instance_id for b in r.roles.list()
                 if b.role in ("reasoning", "tool_execution")}
    assert inst.id not in bound_ids


# T1.5 guard (specs/phase-1-foundation/tasks.md): no bare ("<provider>", "", N)
# provider-wide fallback above the conservative default may ever be added to
# _KNOWN_CONTEXT_WINDOWS. A bare substring ("") matches EVERY model from that
# provider, so a high value here is a guess applied to models that may not
# have that window. The budget is window*0.9, so a raised provider-wide entry
# silently re-creates the overcommit this table's default exists to prevent.
# This is the guard test named in tasks.md T1.5 ("test_no_raised_provider_default").
#
# NO EXCEPTIONS (2026-07-29): this guard previously grandfathered
# ("openrouter", "", 32_000) into an allow-list on the theory that it predated
# AC6. That was wrong — AC6 does not carve out pre-existing entries, and the
# allow-list let a real over-provisioning bug (OpenRouter fronts 4k-2M window
# models under one 32k guess) hide behind a "grandfathered" label instead of
# being fixed. The entry has been REMOVED from _KNOWN_CONTEXT_WINDOWS (see
# agent_kernel.py:927-943) and this guard is provider-agnostic with no
# allow-list, full stop.
# The conservative default an unknown window falls back to (REQ-2 AC4).
_CONSERVATIVE_DEFAULT = 8_192


def test_no_raised_provider_default():
    """REQ-2 AC6 / T1.5: no provider-wide default above the conservative one.

    A bare substring ("") matches EVERY model from that provider, so a high
    value here is a guess applied to models that may not have that window. The
    DER budget is derived from this number (REQ-1 AC4), so guessing high means
    steps keep issuing while every call silently truncates — the first entry in
    the silent-failure table in specs/PHASES.md.

    Guards every provider, with NO exceptions: a cerebras-only check passes
    while ("groq", "", 128_000) walks straight in, and an allow-list just
    moves the hole to whichever provider is listed in it.
    """
    from backend.agent.agent_kernel import AgentKernel

    offenders = [
        (provider, tokens)
        for provider, substring, tokens in AgentKernel._KNOWN_CONTEXT_WINDOWS
        if substring == ""
        and tokens > _CONSERVATIVE_DEFAULT
    ]
    assert not offenders, (
        f"provider-wide fallback(s) above the conservative "
        f"{_CONSERVATIVE_DEFAULT} default: {offenders}. A bare-substring entry "
        f"applies to every model from that provider; sizing the budget from a "
        f"guessed-high window truncates every call while steps keep issuing "
        f"(REQ-2 AC6, see agent_kernel.py:927-943)."
    )


# CT-F9: the routing selector (provider) is frozen — survives a config
# round-trip for every value. Phase 1 must not alter which backend serves.
@pytest.mark.parametrize("prov", ["api", "lm_studio", "ollama", "iris_local"])
def test_routing_selector_frozen(prov):
    cfg = InferenceConfig()
    cfg.provider = prov
    cfg2 = InferenceConfig.from_dict(cfg.to_dict())
    assert cfg2.provider == prov


# ---------------------------------------------------------------------------
# BUG 1 regression: migrate_flat_to_collection() must not leave the legacy
# credential on the dataclass once it has been moved into the keyring —
# to_dict()/asdict() (and therefore save_config()) would otherwise still
# serialize the raw key into iris_config.json in plaintext (REQ-6 AC4 /
# REQ-7's core promise). Asserts the EFFECT (no credential in the serialized
# bytes / on the dataclass), never that set_secret() was merely called.
# ---------------------------------------------------------------------------
import json  # noqa: E402


def test_migration_clears_flat_credential_after_keyring_success():
    _cred = "FAKETESTCRED-should-never-survive-migration"
    cfg = InferenceConfig.from_dict({
        "provider": "cerebras",
        "api_base_url": "https://api.cerebras.ai/v1",
        "api_key": _cred,
        "reasoning_model": "gemma-4-31b",
    })
    # The keyring write succeeded (real store or its JSON-file fallback —
    # either way set_secret() did not raise), so the flat field must be gone.
    assert cfg.api_key == "", (
        "InferenceConfig.api_key still holds the legacy credential after a "
        "successful keyring migration — asdict()/to_dict() will serialize it "
        "into iris_config.json in plaintext."
    )
    serialized = json.dumps(cfg.to_dict())
    assert _cred not in serialized, (
        "the legacy credential leaked into the serialized config bytes even "
        "though migrate_flat_to_collection() ran"
    )


def test_migration_keeps_flat_credential_when_keyring_write_fails(monkeypatch):
    _cred = "FAKETESTCRED-must-not-be-lost-on-keyring-failure"

    def _boom(provider_id, key):
        raise RuntimeError("simulated keyring backend failure")

    monkeypatch.setattr(
        "backend.agent.inference.keyring.set_secret", _boom
    )
    cfg = InferenceConfig.from_dict({
        "provider": "cerebras",
        "api_base_url": "https://api.cerebras.ai/v1",
        "api_key": _cred,
        "reasoning_model": "gemma-4-31b",
    })
    # The keyring write failed -> the ONLY copy of the credential must survive
    # on the dataclass rather than being silently dropped (losing it is worse
    # than the pre-existing plaintext-config risk).
    assert cfg.api_key == _cred, (
        "the flat api_key was cleared even though the keyring write raised — "
        "the user's only copy of the credential would be lost"
    )


# ---------------------------------------------------------------------------
# BUG 4 regression: a pure legacy config (no `providers` collection) must
# still get its reasoning/tool_execution roles bound, even though Phase 4's
# register_builtin_encoder_providers() (provider.py:115-151) always populates
# the registry with a non-chat "embedding:lfm25-emb-350m" entry BEFORE
# _apply_config() runs. Asserts the EFFECT (roles actually bound / resolve()
# works), never that a particular method was invoked.
# ---------------------------------------------------------------------------


def test_legacy_config_gets_role_bindings_despite_encoder_provider():
    cfg = InferenceConfig()
    cfg.provider = "cerebras"
    cfg.api_base_url = "https://api.cerebras.ai/v1"
    cfg.api_key = "sk-test-legacy"
    cfg.reasoning_model = "gemma-4-31b"
    # config_version left at 1 / providers left empty: this is exactly the
    # "pure legacy config" shape migrate_flat_to_collection() would later
    # upgrade, but InferenceRouter must synthesize bindings from the flat
    # fields directly regardless.
    r = InferenceRouter(cfg)

    assert r.roles.list(), (
        "legacy flat config produced NO role bindings at all (roles: []) — "
        "the encoder provider's presence in the registry suppressed the "
        "legacy synthesis path"
    )
    assert r.default_role is not None, (
        "legacy flat config left default_role unset — DER's unbound-role "
        "fallback (e.g. EXECUTION) has nothing to resolve to"
    )
    assert r.resolve("reasoning").id == "cerebras"
    assert r.resolve("tool_execution").id == "cerebras"
    # The encoder provider must still be present (Phase 4 requirement) but
    # never bound to a chat-serving role.
    bound_ids = {b.instance_id for b in r.roles.list()
                 if b.role in ("reasoning", "tool_execution")}
    assert "embedding:lfm25-emb-350m" not in bound_ids

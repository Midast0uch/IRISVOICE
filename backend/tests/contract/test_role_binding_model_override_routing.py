"""
Contract test: RoleBindingTable.resolve() must apply the binding's
model_override to the resolved instance.

Regression guard (2026-08-16): the override was stored and displayed but
NEVER applied at routing time — resolve() returned the provider's registered
default model, so a user who picked nemotron-3-super-cloud for ollama got
gpt-oss:120b-cloud (the provider default) in actual inference. The dashboard
and ModelSwitcher showed the override; the router used the default.

Contract:
  1. resolve() returns the binding's model_override when present.
  2. The registry entry itself is untouched (resolve returns a copy).
  3. Without an override, resolve() returns the registered model.
"""

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable


def _make_table():
    reg = ProviderRegistry()
    reg.add(
        ProviderInstance(
            id="ollama",
            label="Ollama",
            kind=ProviderKind.OLLAMA,
            model="gpt-oss:120b-cloud",
            api_base_url="http://localhost:11434",
        )
    )
    return RoleBindingTable(reg), reg


def test_resolve_applies_model_override():
    """The fix: the user's per-role model choice wins over the provider default."""
    table, reg = _make_table()
    table.bind("reasoning", "ollama", model_override="nemotron-3-super-cloud")

    inst = table.resolve("reasoning")
    assert inst.id == "ollama"
    assert inst.model == "nemotron-3-super-cloud", (
        f"expected override nemotron-3-super-cloud, got {inst.model!r}"
    )


def test_resolve_does_not_mutate_registry_entry():
    """resolve() returns a copy — the registry keeps the provider default."""
    table, reg = _make_table()
    table.bind("reasoning", "ollama", model_override="nemotron-3-super-cloud")

    table.resolve("reasoning")
    assert reg.get("ollama").model == "gpt-oss:120b-cloud", (
        "registry entry must keep its registered model"
    )


def test_resolve_without_override_returns_registered_model():
    """No override -> the provider's registered model is used."""
    table, _ = _make_table()
    table.bind("reasoning", "ollama")

    inst = table.resolve("reasoning")
    assert inst.model == "gpt-oss:120b-cloud"


def test_provider_only_rebind_preserves_model_override():
    """A provider-only rebind (no model) to the SAME instance must keep the
    existing model_override — otherwise the chat ModelSwitcher / dashboard
    provider pick wipes the user's model choice and the router falls back to
    the provider's registered default (2026-08-16: nano pick overwritten by a
    provider-only rebind, router used stale nemotron-3-super-cloud)."""
    table, _reg = _make_table()
    table.bind("reasoning", "ollama", model_override="nemotron-3-nano:30b-cloud")

    # Provider-only rebind, same instance — must NOT wipe the override.
    table.bind("reasoning", "ollama")

    inst = table.resolve("reasoning")
    assert inst.model == "nemotron-3-nano:30b-cloud", (
        f"provider-only rebind wiped the override, got {inst.model!r}"
    )


def test_rebind_to_different_instance_resets_model():
    """Rebinding to a DIFFERENT instance resets the model (new provider, no
    choice yet) — the preserve rule must not leak the old provider's model."""
    reg = ProviderRegistry()
    reg.add(
        ProviderInstance(
            id="ollama",
            label="Ollama",
            kind=ProviderKind.OLLAMA,
            model="gpt-oss:120b-cloud",
            api_base_url="http://localhost:11434",
        )
    )
    reg.add(
        ProviderInstance(
            id="cohere",
            label="Cohere",
            kind=ProviderKind.API,
            model="command-a-plus-05-2026",
        )
    )
    table = RoleBindingTable(reg)
    table.bind("reasoning", "ollama", model_override="nemotron-3-nano:30b-cloud")

    table.bind("reasoning", "cohere")

    inst = table.resolve("reasoning")
    assert inst.id == "cohere"
    assert inst.model == "command-a-plus-05-2026", (
        f"cross-provider rebind leaked the old override, got {inst.model!r}"
    )
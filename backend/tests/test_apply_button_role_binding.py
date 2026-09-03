"""
Regression test for the APPLY-button per-role binding bug
(pin_22911c374522 / pin_dfc1fd4c4189).

Root cause: the model_selection confirm_card handler bound roles to the
MODEL DISPLAY NAME (e.g. "gemma-4-31b") instead of the PROVIDER INSTANCE ID
(e.g. "cerebras" / "local"). Binding to a bare model name creates a dangling
role binding that router.resolve() cannot find, collapsing both roles onto the
default and silently overriding the user's per-role Brain/Tool picks.

This test exercises the InferenceRouter directly (the same object the gateway
handler binds against) to prove:
  1. Binding a role to a provider INSTANCE ID resolves correctly.
  2. Binding a role to a bare MODEL NAME does NOT resolve (the bug class).
  3. A distinct per-role selection (reasoning->local, tool_execution->cerebras)
     is preserved and both resolve to their own instances.
"""

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter


def _make_router():
    reg = ProviderRegistry()
    reg.add(ProviderInstance(id="cerebras", label="Cerebras", kind=ProviderKind.API, model="gemma-4-31b", api_base_url="https://api.cerebras.ai/v1"))
    reg.add(ProviderInstance(id="local", label="Local", kind=ProviderKind.INPROCESS, model="lfm2-8b"))
    router = InferenceRouter.__new__(InferenceRouter)
    # Minimal wiring: router needs a registry + roles table + default role.
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


def test_bind_role_to_provider_instance_id_resolves():
    """The fix: bind roles to the provider INSTANCE ID, not the model name."""
    router = _make_router()
    # This is what the corrected gateway handler now does:
    router.bind_role("reasoning", "cerebras", model_override="gemma-4-31b")
    router.bind_role("tool_execution", "cerebras", model_override="gemma-4-31b")

    inst = router.resolve("reasoning")
    assert inst.id == "cerebras", f"expected cerebras, got {inst.id!r}"
    assert inst.model == "gemma-4-31b"
    # tool_execution must resolve to the same provider instance (Use Same Model)
    tool_inst = router.resolve("tool_execution")
    assert tool_inst.id == "cerebras"


def test_bind_role_to_model_name_does_not_resolve():
    """Reproduces the OLD bug class: binding to a bare model name is dangling."""
    router = _make_router()
    # OLD (buggy) behaviour: bind_role("reasoning", "gemma-4-31b")
    router.bind_role("reasoning", "gemma-4-31b")

    with pytest.raises(RuntimeError):
        # The model name is not a registered provider instance id -> cannot resolve
        router.resolve("reasoning")


def test_distinct_per_role_bindings_preserved():
    """Brain=local, Tool=cerebras must both resolve to their own instances."""
    router = _make_router()
    router.bind_role("reasoning", "local", model_override="lfm2-8b")
    router.bind_role("tool_execution", "cerebras", model_override="gemma-4-31b")

    brain = router.resolve("reasoning")
    tool = router.resolve("tool_execution")
    assert brain.id == "local", f"brain should be local, got {brain.id!r}"
    assert tool.id == "cerebras", f"tool should be cerebras, got {tool.id!r}"
    assert brain.id != tool.id


def test_existing_distinct_bindings_detected():
    """The gateway handler checks for distinct existing bindings before clobbering.

    Mirrors the `_per_role_distinct` guard added to iris_gateway.py: it must
    detect that reasoning and tool_execution already point at DIFFERENT instances.
    """
    router = _make_router()
    router.bind_role("reasoning", "local")
    router.bind_role("tool_execution", "cerebras")

    existing = {b.role: b.instance_id for b in router._roles.list()}
    per_role_distinct = (
        existing.get("reasoning")
        and existing.get("tool_execution")
        and existing["reasoning"] != existing["tool_execution"]
    )
    assert per_role_distinct is True
    assert existing["reasoning"] == "local"
    assert existing["tool_execution"] == "cerebras"

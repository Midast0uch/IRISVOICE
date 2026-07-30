"""Contract test CT-E7 (backend enforcement): chat-only roles refuse non-chat providers.

Phase 4 REQ-6 states an embedding/rerank provider can "never serve as the user's
brain or tool runner". That was true only through two FRONTEND candidate-list
filters (``components/ModelSwitcher.tsx``, ``components/ModelInferenceSection.tsx``).
A frontend filter is not an enforcement boundary: a ``role_bindings`` entry loaded
from ``iris_config.json``, or any direct ``bind_role()`` call, bypassed it and would
bind the embedding provider to ``reasoning`` — failing later at generate time, far
from the misconfiguration.

These assert the EFFECT (the binding does not exist afterwards), not that a guard
function was called.

The narrowness is load-bearing and is asserted here too: binding an id that is not
yet in the registry must still succeed, because Phase 1 REQ-3 AC6 / CT-F7 require
binding a local provider BEFORE its model loads, and ``_apply_config`` can apply
role bindings before the provider collection is populated. A guard that rejected
unknown ids would break startup ordering.
"""

from __future__ import annotations

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable


def _table() -> RoleBindingTable:
    reg = ProviderRegistry()
    reg.add(
        ProviderInstance(
            id="embedding:lfm25-emb-350m",
            label="LFM2.5 Embedding 350M",
            kind=ProviderKind.INPROCESS,
            purpose="embedding",
        )
    )
    reg.add(
        ProviderInstance(
            id="rerank:lfm25-colbert-350m",
            label="LFM2.5 ColBERT 350M",
            kind=ProviderKind.INPROCESS,
            purpose="rerank",
        )
    )
    reg.add(
        ProviderInstance(
            id="cerebras",
            label="Cerebras",
            kind=ProviderKind.API,
            model="gemma-4-31b",
            purpose="chat",
        )
    )
    return RoleBindingTable(reg)


@pytest.mark.parametrize("role", ["reasoning", "tool_execution"])
@pytest.mark.parametrize(
    "bad_id", ["embedding:lfm25-emb-350m", "rerank:lfm25-colbert-350m"]
)
def test_non_chat_provider_is_refused_for_chat_only_roles(role, bad_id):
    """Both chat-only roles x both non-chat purposes — all four must refuse.

    Parametrized over both roles AND both purposes on purpose: a guard that
    checked only `reasoning`, or only `embedding`, would pass a single-case test
    while leaving the other door open.
    """
    t = _table()
    t.bind(role, bad_id)
    with pytest.raises(RuntimeError):
        t.resolve(role)


@pytest.mark.parametrize("role", ["reasoning", "tool_execution"])
def test_chat_provider_still_binds(role):
    """The guard must not block the normal case."""
    t = _table()
    t.bind(role, "cerebras")
    assert t.resolve(role).id == "cerebras"


@pytest.mark.parametrize("role", ["reasoning", "tool_execution"])
def test_unregistered_id_still_binds(role):
    """Phase 1 REQ-3 AC6 / CT-F7: bind-before-load must keep working.

    The provider is not in the registry yet, so its purpose is unknowable. The
    guard must allow this rather than guess — rejecting unknown ids would break
    `_apply_config` whenever role bindings are applied before providers.
    """
    t = _table()
    t.bind(role, "local:qwen3-9b")
    # resolve() raises because the instance is absent from the registry, which is
    # the pre-existing bind-before-load behaviour — but the BINDING was recorded,
    # which is what this test pins.
    assert t.snapshot() if hasattr(t, "snapshot") else True
    assert any(
        b.instance_id == "local:qwen3-9b" for b in t._bindings.values()
    ), "bind-before-load was refused; Phase 1 CT-F7 requires it to be allowed"


def test_refusal_leaves_a_previous_good_binding_intact():
    """A refused rebind must not clear a working role.

    Refusing by early-return means the dict is never touched; a naive
    delete-then-validate would strand the role unbound and take the brain offline
    on one bad config line.
    """
    t = _table()
    t.bind("reasoning", "cerebras")
    t.bind("reasoning", "embedding:lfm25-emb-350m")
    assert t.resolve("reasoning").id == "cerebras"

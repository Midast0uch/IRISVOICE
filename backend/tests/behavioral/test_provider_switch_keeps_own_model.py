"""Behavioral regression: a model name never crosses provider boundaries,
and the card's explicit provider is the user's choice.

Two incidents, one invariant:

2026-08-13 (``.iris-logs/backend-20260813-074742.log``): a confirm_card
carrying the PREVIOUS provider's model re-registered ``cohere`` with
``model="gemma-4-31b"`` — a Cerebras model — so the chat-row ModelSwitcher,
the dashboard Model & Inference card, and the actual outbound request all
reported ``cohere · gemma-4-31b``.

2026-08-15 (``backend-20260815-134032.log`` 13:40:32): the guard built for
the first incident treated the ROLE BINDING as authoritative over the card's
EXPLICIT model_provider. The user selected Ollama while a cerebras binding
was live; the handler resolved the effective provider back to cerebras,
discarded the card, and the UI reverted to Cerebras.

The reconciled spec (card-wins precedence):

  1. The card's explicit ``model_provider`` is the user's dropdown choice
     and WINS. The binding is the fallback only when the card names no
     provider.
  2. A ROLE BINDING contributes its model only when it serves the effective
     provider — the card named no provider, or it named the SAME provider
     the binding already serves. A binding left on the previous provider
     must not stamp its model onto the newly selected one.
  3. When the card names a provider the reasoning binding does not serve,
     BOTH roles REBIND to it: ``generate()`` resolves each role THROUGH its
     binding, so a binding left on the old provider keeps serving it (that
     is what made the ollama selection revert).
  4. A card that merely ECHOES the reasoning binding (the global APPLY
     re-sending the synced provider) rebinds nothing, so a Brain/Tool split
     across two providers survives an unrelated APPLY.

The invariant, stated once: **a model name is only meaningful next to the
provider it was chosen for.** A model belonging to provider X may never end
up registered on provider Y — enforced at the gateway (binding guard, rule
2) and again in ``AgentKernel.set_model_selection`` (catalog check for
hosted API providers, pinned below).

Drives the REAL ``confirm_card`` handler — the same message the dashboard's
Model & Inference card sends — and asserts on what the gateway hands the
kernel, because that call is where the provider instance gets (re-)registered.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.iris_gateway import IRISGateway
from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.provider_catalog import (
    get_default_model_for_provider,
    model_belongs_to_provider,
)
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter


class _FakeWSManager:
    def __init__(self):
        self.sent = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg):
        pass

    async def broadcast(self, msg):
        pass


class _RecordingKernel:
    """Records what the gateway asks it to register.

    Deliberately does NOT re-implement the kernel's own sanitization — the
    assertion is on what the GATEWAY hands down, which is the seam under test.
    Unknown attributes resolve to no-ops so the rest of the confirm_card body
    (configure_api, configure_vps, …) runs to completion instead of bailing into
    the handler's outer except.
    """

    def __init__(self, router):
        self._router = router
        self.selections = []
        self.bindings = []

    def set_model_selection(self, reasoning_model=None, tool_execution_model=None,
                            model_provider=None, **kwargs):
        self.selections.append(
            {
                "reasoning_model": reasoning_model,
                "tool_execution_model": tool_execution_model,
                "model_provider": model_provider,
                **kwargs,
            }
        )
        return True

    def set_role_binding(self, role, instance_id, model_override=None):
        self.bindings.append((role, instance_id, model_override))
        return True

    def __getattr__(self, _name):
        return lambda *a, **k: None


def _router_with(*instances) -> InferenceRouter:
    reg = ProviderRegistry()
    for inst in instances:
        reg.add(inst)
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


def _confirm_model_card(gw, values, session_id="session_iris"):
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            gw.handle_message(
                "iris",
                {
                    "type": "confirm_card",
                    "payload": {"section_id": "model_selection", "values": values},
                },
                session_id=session_id,
            )
        )
    finally:
        loop.close()


def _gateway_with(kernel):
    gw = IRISGateway(ws_manager=_FakeWSManager())
    gw._main_loop = asyncio.new_event_loop()
    return gw


# A card that names cerebras and cerebras's own model. Under card-wins
# precedence this is honoured as a switch TO cerebras whatever is bound —
# what must never happen is its model landing on a DIFFERENT provider.
CEREBRAS_CARD = {
    "model_provider": "cerebras",
    "reasoning_model": "gemma-4-31b",
    "tool_model": "gemma-4-31b",
}

# The card from the 2026-08-15 incident: the user picked Ollama in the
# Provider dropdown while a cerebras binding was live.
OLLAMA_SWITCH_CARD = {
    "model_provider": "ollama",
    "reasoning_model": "gpt-oss:120b-cloud",
    "tool_model": "gpt-oss:120b-cloud",
}


class TestCardProviderIsTheUsersChoice:
    """2026-08-15: the card's explicit provider wins over the binding."""

    def test_ollama_card_switches_off_a_stale_cerebras_binding(self, monkeypatch):
        """The exact 13:40:32 replay: bindings say cerebras, card says ollama."""
        router = _router_with(
            ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model="gemma-4-31b"),
            ProviderInstance(id="ollama", label="Ollama",
                             kind=ProviderKind.OLLAMA, model=None),
        )
        router.bind_role("reasoning", "cerebras", model_override="gemma-4-31b")
        router.bind_role("tool_execution", "cerebras", model_override="gemma-4-31b")

        kernel = _RecordingKernel(router)
        gw = _gateway_with(kernel)
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(gw, OLLAMA_SWITCH_CARD)

        assert kernel.selections, "the confirm_card handler never reached the kernel"
        sel = kernel.selections[-1]
        assert sel["model_provider"] == "ollama", (
            "the card's explicit provider is the user's dropdown choice — a "
            f"stale binding must not revert it (got {sel['model_provider']!r})"
        )
        assert sel["reasoning_model"] == "gpt-oss:120b-cloud", (
            "the card names ollama, so the card's model applies; the cerebras "
            "binding's model must not cross the switch (got "
            f"{sel['reasoning_model']!r})"
        )
        assert model_belongs_to_provider("ollama", sel["reasoning_model"])
        assert sel["tool_execution_model"] != "gemma-4-31b"
        assert model_belongs_to_provider("ollama", sel["tool_execution_model"])
        # generate() resolves each role THROUGH its binding — without the
        # rebind the switch silently reverts to the previous provider.
        assert ("reasoning", "ollama", sel["reasoning_model"]) in kernel.bindings, (
            "reasoning must rebind to the card's provider on a switch"
        )
        assert ("tool_execution", "ollama", sel["tool_execution_model"]) in (
            kernel.bindings
        ), "tool_execution must rebind to the card's provider on a switch"
        # The endpoint must resolve — the old inline chain yielded "" for
        # ollama (and every provider it forgot).
        assert sel.get("api_base_url"), (
            "the ollama provider was registered with no endpoint"
        )

    def test_card_without_provider_defers_to_the_binding(self, monkeypatch):
        """No provider on the card → the binding is canonical, and nothing
        rebinds (an APPLY from a card that carries only model names must not
        move the user's provider)."""
        router = _router_with(
            ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model="gemma-4-31b"),
        )
        router.bind_role("reasoning", "cerebras", model_override="qwen-3-235b-instruct")
        router.bind_role("tool_execution", "cerebras", model_override="qwen-3-32b")

        kernel = _RecordingKernel(router)
        gw = _gateway_with(kernel)
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(
            gw, {"reasoning_model": "gemma-4-31b", "tool_model": "gemma-4-31b"}
        )

        sel = kernel.selections[-1]
        assert sel["model_provider"] == "cerebras", (
            "card names no provider — the binding's provider is the answer "
            f"(got {sel['model_provider']!r})"
        )
        assert sel["reasoning_model"] == "qwen-3-235b-instruct", (
            "the binding's model_override is canonical when the card names "
            "no provider"
        )
        assert sel["tool_execution_model"] == "qwen-3-32b"
        assert kernel.bindings == [], "nothing should rebind when no provider is named"

    def test_echo_card_preserves_a_split_brain_tool_binding(self, monkeypatch):
        """The global APPLY re-sends the provider SYNCED from the reasoning
        binding. That echo must not clobber a Tool binding the user placed on
        a different provider."""
        router = _router_with(
            ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model="gemma-4-31b"),
            ProviderInstance(id="ollama", label="Ollama",
                             kind=ProviderKind.OLLAMA, model="gpt-oss:120b-cloud"),
        )
        router.bind_role("reasoning", "cerebras")
        router.bind_role("tool_execution", "ollama", model_override="gpt-oss:120b-cloud")

        kernel = _RecordingKernel(router)
        gw = _gateway_with(kernel)
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(gw, CEREBRAS_CARD)

        sel = kernel.selections[-1]
        assert sel["model_provider"] == "cerebras"
        rebound_roles = {role for role, _inst, _m in kernel.bindings}
        assert rebound_roles == set(), (
            "a card echoing the reasoning binding must not rebind — the "
            f"Brain/Tool split would be clobbered (rebound: {rebound_roles})"
        )

    def test_the_switch_takes_effect_in_the_real_router(self, monkeypatch):
        """Full loop: REAL confirm_card handler + REAL kernel + REAL router.

        The reported 2026-08-15 bug was emergent — every seam looked right but
        the router still served cerebras afterwards. Assert the END state:
        both roles resolve to the card's provider with the card's model, and
        the ollama instance carries its endpoint.
        """
        from backend.agent.agent_kernel import AgentKernel

        kernel = AgentKernel(session_id="test_switch_takes_effect")
        kernel._router.add_provider(
            ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model="gemma-4-31b")
        )
        kernel._router.bind_role("reasoning", "cerebras", model_override="gemma-4-31b")
        kernel._router.bind_role("tool_execution", "cerebras", model_override="gemma-4-31b")

        gw = _gateway_with(kernel)
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(gw, OLLAMA_SWITCH_CARD, session_id="test_switch_takes_effect")

        bindings = {b.role: b for b in kernel._router._roles.list()}
        assert bindings["reasoning"].instance_id == "ollama", (
            "reasoning still serves the previous provider — the switch "
            "silently reverted (the reported bug)"
        )
        assert bindings["tool_execution"].instance_id == "ollama"
        assert bindings["reasoning"].model_override == "gpt-oss:120b-cloud"
        inst = kernel._router.resolve("reasoning")
        assert inst.id == "ollama"
        assert inst.api_base_url, "the ollama instance was registered with no endpoint"


class TestProviderSwitchKeepsItsOwnModel:
    """2026-08-13 invariant under card-wins precedence: the model that lands
    belongs to the provider that ends up selected — never a foreign one."""

    def test_switch_lands_a_model_that_belongs_to_the_selected_provider(
        self, monkeypatch
    ):
        """Card names cerebras + gemma-4-31b while cohere is bound: the switch
        to cerebras is honoured, and gemma-4-31b lands on cerebras — its
        owner. What is forbidden is the model crossing to a DIFFERENT
        provider (the original 08:19:07 leak)."""
        router = _router_with(
            ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model="gemma-4-31b"),
            # Cohere as "Apply Provider" left it: registered, bound, no model.
            ProviderInstance(id="cohere", label="Cohere",
                             kind=ProviderKind.API, model=None),
        )
        router.bind_role("reasoning", "cohere")
        router.bind_role("tool_execution", "cohere")

        kernel = _RecordingKernel(router)
        gw = _gateway_with(kernel)
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(gw, CEREBRAS_CARD)

        assert kernel.selections, "the confirm_card handler never reached the kernel"
        sel = kernel.selections[-1]
        assert sel["model_provider"] == "cerebras", (
            "the card's explicit provider is the user's choice — it must win "
            f"over the binding (got {sel['model_provider']!r})"
        )
        assert model_belongs_to_provider(
            sel["model_provider"], sel["reasoning_model"]
        ), (
            f"{sel['reasoning_model']!r} does not belong to "
            f"{sel['model_provider']!r} — the model crossed providers"
        )
        assert model_belongs_to_provider(
            sel["model_provider"], sel["tool_execution_model"]
        )
        # The switch must actually take: roles rebind to the card's provider.
        assert ("reasoning", "cerebras", sel["reasoning_model"]) in kernel.bindings
        assert ("tool_execution", "cerebras", sel["tool_execution_model"]) in (
            kernel.bindings
        )

    def test_previous_providers_model_is_discarded_on_a_switch(self, monkeypatch):
        """The abandoned binding's registered model must NOT follow the user
        to the newly selected provider — that is the exact shape of the
        2026-08-13 desync viewed from the other side."""
        router = _router_with(
            ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model=None),
            ProviderInstance(id="cohere", label="Cohere",
                             kind=ProviderKind.API, model="command-a-03-2025"),
        )
        router.bind_role("reasoning", "cohere")
        router.bind_role("tool_execution", "cohere")

        kernel = _RecordingKernel(router)
        gw = _gateway_with(kernel)
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(gw, CEREBRAS_CARD)

        sel = kernel.selections[-1]
        assert sel["model_provider"] == "cerebras"
        assert sel["reasoning_model"] == "gemma-4-31b", (
            "the card names cerebras, so its own model applies — cohere's "
            "'command-a-03-2025' must not be stamped onto cerebras (got "
            f"{sel['reasoning_model']!r})"
        )

    def test_role_binding_override_wins_when_card_names_the_same_provider(
        self, monkeypatch
    ):
        """A per-role model_override is the most specific answer and wins —
        but only while the binding serves the provider being applied.

        It lives on ``RoleBinding``, not on ``ProviderInstance`` — reading it
        off the resolved instance (as the handler used to) always yielded
        None and silently fell through to the card.
        """
        router = _router_with(
            ProviderInstance(id="cohere", label="Cohere",
                             kind=ProviderKind.API, model="command-a-03-2025"),
        )
        router.bind_role("reasoning", "cohere", model_override="command-r-plus-08-2024")
        router.bind_role("tool_execution", "cohere", model_override="command-r-08-2024")

        kernel = _RecordingKernel(router)
        gw = _gateway_with(kernel)
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(
            gw,
            {
                "model_provider": "cohere",
                "reasoning_model": "command-a-03-2025",
                "tool_model": "command-a-03-2025",
            },
        )

        sel = kernel.selections[-1]
        assert sel["reasoning_model"] == "command-r-plus-08-2024"
        assert sel["tool_execution_model"] == "command-r-08-2024"

    def test_card_that_names_the_same_provider_is_still_honoured(self, monkeypatch):
        """The guard must not throw away a card that is actually current.

        Discarding every card value would be the easy over-correction: a user
        picking a different Cerebras model while Cerebras is bound has to keep
        working.
        """
        router = _router_with(
            ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model=None),
        )
        router.bind_role("reasoning", "cerebras")
        router.bind_role("tool_execution", "cerebras")

        kernel = _RecordingKernel(router)
        gw = _gateway_with(kernel)
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(gw, CEREBRAS_CARD)

        sel = kernel.selections[-1]
        assert sel["model_provider"] == "cerebras"
        assert sel["reasoning_model"] == "gemma-4-31b", (
            "the card names the SAME provider that is bound, so its model is "
            "current, not stale — it must be applied"
        )


class TestKernelCatalogSanitizer:
    """The second line of defence (rule 2's backstop): the KERNEL drops a
    foreign model before registering an API provider, because on a provider
    switch the gateway hands the card's raw model down by design.

    Exercised against the REAL AgentKernel.set_model_selection — the same
    call the gateway makes — since that is where the instance is registered.
    """

    @pytest.fixture(scope="class")
    def kernel(self):
        from backend.agent.agent_kernel import AgentKernel

        return AgentKernel(session_id="test_kernel_catalog_sanitizer")

    def test_kernel_drops_a_foreign_model_for_an_api_provider(self, kernel):
        kernel.set_model_selection(
            reasoning_model="gemma-4-31b",  # a Cerebras model
            tool_execution_model="gemma-4-31b",
            model_provider="cohere",
            api_base_url="https://api.cohere.ai/compatibility/v1",
        )
        inst = kernel._router.registry.get("cohere")
        assert inst is not None, "provider was never registered"
        assert inst.model != "gemma-4-31b", (
            "the previous provider's model was stamped onto the new provider"
        )
        assert model_belongs_to_provider("cohere", inst.model)

    def test_kernel_keeps_a_native_model_for_the_same_provider(self, kernel):
        kernel.set_model_selection(
            reasoning_model="command-r-08-2024",
            tool_execution_model="command-r-08-2024",
            model_provider="cohere",
            api_base_url="https://api.cohere.ai/compatibility/v1",
        )
        inst = kernel._router.registry.get("cohere")
        assert inst.model == "command-r-08-2024"


class TestCatalogOwnership:
    """The primitive the fix leans on: does this model belong to this provider?"""

    def test_a_cerebras_model_does_not_belong_to_cohere(self):
        assert model_belongs_to_provider("cerebras", "gemma-4-31b") is True
        assert model_belongs_to_provider("cohere", "gemma-4-31b") is False

    def test_a_provider_without_a_catalog_accepts_anything(self):
        """Absence of a catalog is not evidence a model is wrong.

        A loaded GGUF ("local:<stem>") and a runtime-configured endpoint have no
        catalog; rejecting their models would make them unusable.
        """
        assert model_belongs_to_provider("local:twil-lm3-q4_k_m", "TwIL-LM3-Q4_K_M") is True

    def test_no_model_belongs_to_nothing(self):
        assert model_belongs_to_provider("cohere", "") is False
        assert model_belongs_to_provider("cohere", None) is False

    @pytest.mark.parametrize("provider", ["cohere", "cerebras", "openai", "anthropic"])
    def test_every_api_preset_can_name_a_default_model(self, provider):
        """A provider with no resolvable model falls back to its OWN default.

        If this returns None the fallback chain has nothing provider-scoped to
        offer and the old cross-provider leak becomes reachable again.
        """
        default = get_default_model_for_provider(provider)
        assert default, f"{provider} has no catalog default"
        assert model_belongs_to_provider(provider, default)

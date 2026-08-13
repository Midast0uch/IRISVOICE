"""Behavioral regression: switching providers must not carry the old model over.

Root-caused 2026-08-13 from ``.iris-logs/backend-20260813-074742.log``:

    08:18:35  set_model_selection  reasoning=,             provider=cohere
    08:19:07  set_model_selection  reasoning=gemma-4-31b,  provider=cohere
    08:19:36  [InferenceRouter] role=reasoning instance=cohere model=gemma-4-31b

``gemma-4-31b`` is a CEREBRAS model. The user switched Cerebras -> Cohere and
the Cohere provider instance came up wearing Cerebras's model, so the chat-row
ModelSwitcher, the dashboard Model & Inference card, and the actual outbound
request all reported ``cohere · gemma-4-31b``.

Two things combined to produce it, and this file pins both:

  1. Applying a not-yet-registered provider sent ``reasoning_model=""``, so the
     new instance was registered with NO model.
  2. The ``confirm_card`` canonical-resolution block then could not find a model
     on the binding (it read ``model_override`` off the resolved
     ``ProviderInstance``, which has no such attribute — the override lives on
     the ``RoleBinding``), and fell back to the model name carried by a STALE
     card that named the PREVIOUS provider.

The invariant, stated once: **a model name is only meaningful next to the
provider it was chosen for.** A payload that names provider X may never
contribute a model to provider Y.

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


# The stale card the frontend re-sends after a provider switch: it still names
# the OLD provider and the OLD provider's model.
STALE_CEREBRAS_CARD = {
    "model_provider": "cerebras",
    "reasoning_model": "gemma-4-31b",
    "tool_model": "gemma-4-31b",
}


class TestProviderSwitchKeepsItsOwnModel:
    def test_stale_card_model_never_reaches_the_newly_bound_provider(self, monkeypatch):
        """The exact 08:19:07 replay: bindings say cohere, card says cerebras."""
        router = _router_with(
            ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model="gemma-4-31b"),
            # Cohere as "Apply Provider" left it before the fix: registered,
            # bound, but carrying no model of its own.
            ProviderInstance(id="cohere", label="Cohere",
                             kind=ProviderKind.API, model=None),
        )
        router.bind_role("reasoning", "cohere")
        router.bind_role("tool_execution", "cohere")

        kernel = _RecordingKernel(router)
        gw = IRISGateway(ws_manager=_FakeWSManager())
        gw._main_loop = asyncio.new_event_loop()
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(gw, STALE_CEREBRAS_CARD)

        assert kernel.selections, "the confirm_card handler never reached the kernel"
        sel = kernel.selections[-1]
        assert sel["model_provider"] == "cohere", (
            "role_bindings are canonical — the stale card must not move the "
            f"provider back to cerebras (got {sel['model_provider']!r})"
        )
        assert sel["reasoning_model"] != "gemma-4-31b", (
            "the previous provider's model crossed the switch: cohere would be "
            "re-registered as 'cohere · gemma-4-31b'"
        )
        assert model_belongs_to_provider("cohere", sel["reasoning_model"]), (
            f"{sel['reasoning_model']!r} is not a Cohere model"
        )
        assert sel["tool_execution_model"] != "gemma-4-31b"
        assert model_belongs_to_provider("cohere", sel["tool_execution_model"])

    def test_providers_own_registered_model_wins_over_the_card(self, monkeypatch):
        """When the bound provider HAS a model, that model is what survives."""
        router = _router_with(
            ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model="gemma-4-31b"),
            ProviderInstance(id="cohere", label="Cohere",
                             kind=ProviderKind.API, model="command-a-03-2025"),
        )
        router.bind_role("reasoning", "cohere")
        router.bind_role("tool_execution", "cohere")

        kernel = _RecordingKernel(router)
        gw = IRISGateway(ws_manager=_FakeWSManager())
        gw._main_loop = asyncio.new_event_loop()
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(gw, STALE_CEREBRAS_CARD)

        sel = kernel.selections[-1]
        assert sel["model_provider"] == "cohere"
        assert sel["reasoning_model"] == "command-a-03-2025", (
            "the instance's own registered model must win over a stale card "
            f"value (got {sel['reasoning_model']!r})"
        )

    def test_role_binding_override_is_read_from_the_binding_not_the_instance(
        self, monkeypatch
    ):
        """A per-role model_override is the most specific answer and must win.

        It lives on ``RoleBinding``, not on ``ProviderInstance`` — reading it off
        the resolved instance (as the handler used to) always yielded None and
        silently fell through to the card.
        """
        router = _router_with(
            ProviderInstance(id="cohere", label="Cohere",
                             kind=ProviderKind.API, model="command-a-03-2025"),
        )
        router.bind_role("reasoning", "cohere", model_override="command-r-plus-08-2024")
        router.bind_role("tool_execution", "cohere", model_override="command-r-08-2024")

        kernel = _RecordingKernel(router)
        gw = IRISGateway(ws_manager=_FakeWSManager())
        gw._main_loop = asyncio.new_event_loop()
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(gw, STALE_CEREBRAS_CARD)

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
        gw = IRISGateway(ws_manager=_FakeWSManager())
        gw._main_loop = asyncio.new_event_loop()
        monkeypatch.setattr(
            "backend.agent.agent_kernel.get_agent_kernel",
            lambda session_id=None: kernel,
        )

        _confirm_model_card(gw, STALE_CEREBRAS_CARD)

        sel = kernel.selections[-1]
        assert sel["model_provider"] == "cerebras"
        assert sel["reasoning_model"] == "gemma-4-31b", (
            "the card names the SAME provider that is bound, so its model is "
            "current, not stale — it must be applied"
        )


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

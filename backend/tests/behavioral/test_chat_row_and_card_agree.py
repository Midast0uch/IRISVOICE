"""Behavioral: the chat-row switcher and the dashboard card cannot disagree.

Three UI surfaces write model state, over two backend paths:

  ChatView ModelSwitcher   -> sendRoleBinding(role, instance)          \\  same
  Dashboard Brain/Tool     -> sendRoleBinding(role, instance, model)   /  handler
  Dashboard provider APPLY -> confirm_card -> set_model_selection(preserve_bindings=True)
                                              + conditional set_role_binding

The chat row sends the instance id ONLY — no model override. That is the detail
this file exists for: a provider-only rebind must keep the model the user chose
in the dashboard, and a subsequent card APPLY that merely echoes the synced
provider must not overwrite either of them.

test_provider_switch_keeps_own_model.py pins card-vs-binding precedence. This
pins the SEQUENCES a user actually performs across both surfaces, and asserts
that what the kernel REPORTS (the values every status broadcast and the
ContextPill read) matches what the router RESOLVES. Those two disagreeing is the
bug class: until 2026-08-16 confirm_card ended with an unconditional
`kernel._model_provider = _effective_provider`, which stamped the card's
provider onto the kernel even in the branch that had just deliberately preserved
a different binding — so the card could report cohere while routing to cerebras.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import get_provider_registry
from backend.agent.inference.roles import get_role_binding_table
from backend.iris_gateway import IRISGateway


class _FakeWSManager:
    def __init__(self):
        self.sent = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg):
        pass

    async def broadcast(self, msg):
        pass


@pytest.fixture
def surfaces():
    """Real process-wide registry/roles + real kernel + real gateway."""
    import backend.agent.agent_kernel as ak

    reg = get_provider_registry()
    roles = get_role_binding_table()
    saved_p, saved_b = list(reg.list()), list(roles.list())
    saved_k = dict(ak._agent_kernel_instances)
    for b in saved_b:
        roles.unbind(b.role)
    ak._agent_kernel_instances.clear()

    reg.add(ProviderInstance(id="cerebras", label="Cerebras",
                             kind=ProviderKind.API, model="gemma-4-31b"))
    reg.add(ProviderInstance(id="cohere", label="Cohere", kind=ProviderKind.API,
                             model="command-r-plus-08-2024"))

    gw = IRISGateway(ws_manager=_FakeWSManager())
    gw._main_loop = asyncio.new_event_loop()
    kernel = ak.get_agent_kernel("session_iris")

    yield gw, kernel, reg, roles, ak

    for b in list(roles.list()):
        roles.unbind(b.role)
    for b in saved_b:
        roles.bind(b.role, b.instance_id, b.model_override)
    for p in saved_p:
        reg.add(p)
    ak._agent_kernel_instances.clear()
    ak._agent_kernel_instances.update(saved_k)


def _send(gw, msg, session_id="session_iris"):
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(gw.handle_message("iris", msg, session_id=session_id))
    finally:
        loop.close()


def _bind_from_chat_row(gw, role, instance_id):
    """The chat-row switcher: role + instance, NO model override."""
    _send(gw, {"type": "set_role_binding",
               "payload": {"role": role, "instance_id": instance_id}})


def _bind_from_dashboard(gw, role, instance_id, model):
    """The dashboard Brain/Tool dropdown: carries the model override."""
    _send(gw, {"type": "set_role_binding",
               "payload": {"role": role, "instance_id": instance_id,
                           "model_override": model}})


class TestChatRowAndCardAgree:
    def test_kernel_report_matches_router_resolution_after_a_chat_row_pick(
        self, surfaces
    ):
        """What the kernel reports is what the router resolves — one read."""
        gw, kernel, reg, roles, ak = surfaces
        _bind_from_chat_row(gw, "reasoning", "cohere")
        _bind_from_chat_row(gw, "tool_execution", "cohere")

        assert roles.resolve("reasoning").id == "cohere"
        assert kernel._model_provider == "cohere"
        assert kernel._selected_reasoning_model == roles.resolve("reasoning").model
        assert (
            kernel._selected_tool_execution_model
            == roles.resolve("tool_execution").model
        )

    def test_chat_row_provider_only_pick_keeps_the_dashboards_model_choice(
        self, surfaces
    ):
        """Dashboard picks a specific model; the chat row later re-picks the SAME
        provider with no model. The user's model must survive."""
        gw, kernel, reg, roles, ak = surfaces
        _bind_from_dashboard(gw, "reasoning", "cohere", "command-r-08-2024")
        assert kernel._selected_reasoning_model == "command-r-08-2024"

        _bind_from_chat_row(gw, "reasoning", "cohere")  # provider only

        assert kernel._selected_reasoning_model == "command-r-08-2024", (
            "a provider-only chat-row rebind wiped the model the dashboard chose"
        )

    def test_a_card_echoing_the_synced_provider_does_not_disturb_a_split(
        self, surfaces
    ):
        """Brain and Tool on different providers; the dashboard APPLY re-sends
        the card it already synced. Nothing may move, and the kernel's reported
        provider must still follow the REASONING binding — not the card."""
        gw, kernel, reg, roles, ak = surfaces
        _bind_from_dashboard(gw, "reasoning", "cohere", "command-r-plus-08-2024")
        _bind_from_dashboard(gw, "tool_execution", "cerebras", "gemma-4-31b")

        _send(gw, {"type": "confirm_card", "payload": {
            "section_id": "model_selection",
            "values": {"model_provider": "cohere",
                       "reasoning_model": "command-r-plus-08-2024",
                       "tool_model": "command-r-plus-08-2024"}}})

        assert roles.resolve("reasoning").id == "cohere"
        assert roles.resolve("tool_execution").id == "cerebras", (
            "the card collapsed the Tool onto the Brain's provider"
        )
        assert kernel._model_provider == "cohere"
        assert kernel._selected_tool_execution_model == "gemma-4-31b"

    def test_the_pair_survives_a_new_conversation(self, surfaces):
        """The full sequence, then a message on a conversation never seen before
        — the case that produced the original report."""
        gw, kernel, reg, roles, ak = surfaces
        _bind_from_dashboard(gw, "reasoning", "cohere", "command-r-plus-08-2024")
        _bind_from_chat_row(gw, "tool_execution", "cerebras")

        ak.get_agent_kernel("conv-fresh")

        assert roles.resolve("reasoning").id == "cohere"
        assert roles.resolve("tool_execution").id == "cerebras"
        new_kernel = ak.get_agent_kernel("conv-fresh")
        assert new_kernel._model_provider == "cohere"
        assert new_kernel._selected_reasoning_model == "command-r-plus-08-2024"

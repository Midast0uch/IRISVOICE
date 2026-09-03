"""Behavioral test: the user's LIVE model choice survives a new conversation.

This is the test that the 30 green contract/behavioral tests around role
binding could not fail, because every one of them drives ``bind_role`` /
``roles.bind`` / ``kernel.set_role_binding`` against a router built inside the
test. The revert the user actually hits lives somewhere none of them look: in
``get_agent_kernel``'s lazy-construction path, which runs when a message
arrives on a conversation this process has not seen before.

The sequence, exactly as a user drives it:

  1. The process starts with a persisted config (cerebras/gemma-4-31b) — the
     startup seed. Peer kernels carry it in their legacy fields.
  2. The user picks Cohere in the ModelSwitcher. That sends ONE message,
     ``set_role_binding``, to ``IRISGateway._handle_set_role_binding``, which
     binds the process-wide RoleBindingTable. This is the live choice, and it
     is the ONLY place the user's intent is recorded.
  3. The user sends a message on a NEW conversation. ``get_agent_kernel``
     constructs a kernel for it.

After (3) the reasoning role must still resolve to Cohere. The role table is a
process-wide singleton (``roles.get_role_binding_table``) shared by every
kernel's router, so constructing a kernel is a READ of the user's choice, never
a write. Any write during (3) is a stale copy overwriting the live value.

Asserted against the process-wide table itself rather than any kernel's view,
because that table is what ``resolve()`` consults at inference time and what
``router.snapshot()`` broadcasts back to the frontend.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import get_provider_registry
from backend.agent.inference.roles import get_role_binding_table


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
def clean_process_state():
    """Give each test a clean process-wide registry, role table, and kernel map.

    These are module-level singletons by design (REQ-5: role bindings live in
    ONE place). The test drives the real ones, so it must restore them.
    """
    import backend.agent.agent_kernel as ak

    reg = get_provider_registry()
    roles = get_role_binding_table()

    saved_providers = list(reg.list())
    saved_bindings = list(roles.list())
    saved_kernels = dict(ak._agent_kernel_instances)

    for b in saved_bindings:
        roles.unbind(b.role)

    reg.add(
        ProviderInstance(
            id="cerebras", label="Cerebras", kind=ProviderKind.API,
            model="gemma-4-31b",
        )
    )
    reg.add(
        ProviderInstance(
            id="cohere", label="Cohere", kind=ProviderKind.API,
            model="command-r-plus-08-2024",
        )
    )

    yield reg, roles

    for b in list(roles.list()):
        roles.unbind(b.role)
    for b in saved_bindings:
        roles.bind(b.role, b.instance_id, b.model_override)
    for p in saved_providers:
        reg.add(p)
    ak._agent_kernel_instances.clear()
    ak._agent_kernel_instances.update(saved_kernels)


class TestLiveBindingSurvivesNewConversation:
    def test_new_conversation_does_not_revert_the_users_pick(
        self, clean_process_state, monkeypatch
    ):
        from backend.iris_gateway import IRISGateway
        import backend.agent.agent_kernel as ak

        reg, roles = clean_process_state

        # ── (1) Startup state: config seeded cerebras, and the peer kernel
        # that already exists carries it in its legacy fields — which is the
        # ONLY thing the startup path writes there.
        roles.bind("reasoning", "cerebras", model_override="gemma-4-31b")
        roles.bind("tool_execution", "cerebras", model_override="gemma-4-31b")

        ak._agent_kernel_instances.clear()
        peer = ak.get_agent_kernel("session_iris")
        assert peer._model_provider == "cerebras", (
            "precondition: the existing peer kernel reports the seeded provider"
        )

        # ── (2) The user picks Cohere in the ModelSwitcher. One message.
        ws = _FakeWSManager()
        gw = IRISGateway(ws_manager=ws)
        gw._main_loop = asyncio.new_event_loop()

        loop = asyncio.new_event_loop()
        for role in ("reasoning", "tool_execution"):
            loop.run_until_complete(
                gw.handle_message(
                    "iris",
                    {
                        "type": "set_role_binding",
                        "payload": {"role": role, "instance_id": "cohere"},
                    },
                    session_id="session_iris",
                )
            )
        loop.close()

        assert roles.resolve("reasoning").id == "cohere", (
            "the bind itself failed — this test is about what happens AFTER "
            "a successful bind"
        )

        # ── (3) A message arrives on a conversation this process has never
        # seen. The kernel is constructed lazily.
        ak.get_agent_kernel("conv-brand-new")

        # ── The user's live choice must still be the live choice.
        assert roles.resolve("reasoning").id == "cohere", (
            "constructing a kernel for a new conversation REBOUND the "
            "process-wide reasoning role away from the user's live pick "
            "(cohere) — a stale copy (config replay in InferenceRouter."
            "_apply_config, or peer-inheritance in get_agent_kernel) "
            "overwrote it. Kernel construction must READ the role table, "
            "never write it."
        )
        assert roles.resolve("tool_execution").id == "cohere", (
            "the tool_execution role reverted on new-conversation construction"
        )

    def test_brain_and_tool_stay_independent_across_a_new_conversation(
        self, clean_process_state
    ):
        """Split brain/tool selection must also survive.

        The scaling case: subagents and the swarm bind DIFFERENT providers to
        different roles. If new-conversation construction collapses both roles
        onto one provider, per-role routing is not a foundation anything can be
        built on.
        """
        import backend.agent.agent_kernel as ak

        reg, roles = clean_process_state

        roles.bind("reasoning", "cohere", model_override="command-r-plus-08-2024")
        roles.bind("tool_execution", "cerebras", model_override="gemma-4-31b")

        ak._agent_kernel_instances.clear()
        peer = ak.get_agent_kernel("session_iris")
        # The kernel's provider reflects the REASONING binding, and its two
        # model fields reflect their own roles — split, not collapsed.
        assert peer._model_provider == "cohere"
        assert peer._selected_reasoning_model == "command-r-plus-08-2024"
        assert peer._selected_tool_execution_model == "gemma-4-31b"

        ak.get_agent_kernel("conv-brand-new")

        assert roles.resolve("reasoning").id == "cohere", (
            "the reasoning role collapsed onto the tool provider when a new "
            "conversation kernel was constructed"
        )
        assert roles.resolve("tool_execution").id == "cerebras", (
            "the tool_execution role collapsed onto the reasoning provider "
            "when a new conversation kernel was constructed"
        )
        assert roles.resolve("reasoning").model == "command-r-plus-08-2024"
        assert roles.resolve("tool_execution").model == "gemma-4-31b"

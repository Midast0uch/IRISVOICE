"""Behavioral test (specs/phase-5-switcher, REQ-2 AC7).

"Bind Brain and Tool to DIFFERENT providers from the switcher; both hold."

Decision Locked #4: "Brain and Tool stay independently bindable. The switcher
must not collapse mix-and-match into a single selection." Drives the REAL
`IRISGateway._handle_set_role_binding` handler twice (once per role, exactly
as ModelSwitcher's two role sections each call `sendRoleBinding` independently
— see `components/ModelSwitcher.tsx`'s per-role `CustomDropdown`), then
resolves BOTH roles through the real `InferenceRouter.resolve()` — not just
reading the bindings table, but proving each role's resolution actually
reaches its OWN provider instance.
"""

from __future__ import annotations

import asyncio

from backend.iris_gateway import IRISGateway
from backend.agent.inference.provider import ProviderInstance, ProviderKind
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


class _FakeKernel:
    def __init__(self, router):
        self._router = router


def _make_router() -> InferenceRouter:
    reg = ProviderRegistry()
    reg.add(ProviderInstance(id="cerebras", label="Cerebras", kind=ProviderKind.API, model="gemma-4-31b"))
    reg.add(ProviderInstance(id="local:qwen3-9b", label="Local", kind=ProviderKind.INPROCESS,
                              model="qwen3-9b", loaded=True))
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


class TestBrainAndToolIndependent:
    def test_brain_and_tool_bound_to_different_providers_both_resolve_independently(self, monkeypatch):
        router = _make_router()
        ws = _FakeWSManager()
        gw = IRISGateway(ws_manager=ws)
        gw._main_loop = asyncio.new_event_loop()
        monkeypatch.setattr(
            "backend.agent.get_agent_kernel", lambda session_id=None: _FakeKernel(router)
        )

        loop = asyncio.new_event_loop()
        # Brain -> Cerebras (API), from the switcher's "reasoning" dropdown.
        loop.run_until_complete(
            gw.handle_message(
                "iris",
                {"type": "set_role_binding", "payload": {"role": "reasoning", "instance_id": "cerebras"}},
                session_id="session_iris",
            )
        )
        # Tool -> a DIFFERENT provider (local), from the switcher's
        # "tool_execution" dropdown — a SEPARATE message, not a
        # single-selection collapse (Decision Locked #4).
        loop.run_until_complete(
            gw.handle_message(
                "iris",
                {"type": "set_role_binding", "payload": {"role": "tool_execution", "instance_id": "local:qwen3-9b"}},
                session_id="session_iris",
            )
        )
        loop.close()

        # Both acks succeeded independently.
        updates = [m for (_, m) in ws.sent if m.get("type") == "role_binding_updated"]
        assert len(updates) == 2, f"expected 2 successful binds, got: {ws.sent}"

        # Each role resolves to ITS OWN instance — binding Tool did not
        # clobber Brain, and vice versa.
        brain = router.resolve("reasoning")
        tool = router.resolve("tool_execution")
        assert brain.id == "cerebras"
        assert tool.id == "local:qwen3-9b"
        assert brain.id != tool.id, "Brain and Tool collapsed onto the same instance"

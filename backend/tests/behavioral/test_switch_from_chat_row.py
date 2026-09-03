"""Behavioral test (specs/phase-5-switcher, REQ-2 AC5, REQ-4 AC4).

"Select a model in the switcher; the binding takes effect and the settings
panel shows the same active model."

There is no separate "chat row" backend path — that is the whole point of
D-3 (no new backend surface). This test drives the REAL
`IRISGateway._handle_set_role_binding` handler (the one message
`ModelSwitcher.sendRoleBinding` and `ModelInferenceSection`'s Brain/Tool
selectors both send) and then reads the state back through
`InferenceRouter.snapshot()` — the exact payload shape
`useInferenceState`'s `iris:role_bindings_updated` merge consumes — to prove
the two UIs cannot disagree, because there is only one handler and one
registry underneath both of them.
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
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


class TestSwitchFromChatRow:
    def test_binding_from_the_chat_row_is_visible_to_the_settings_panel(self, monkeypatch):
        router = _make_router()
        ws = _FakeWSManager()
        gw = IRISGateway(ws_manager=ws)
        gw._main_loop = asyncio.new_event_loop()
        monkeypatch.setattr(
            "backend.agent.get_agent_kernel", lambda session_id=None: _FakeKernel(router)
        )

        # "The chat row" (ModelSwitcher) selects Cerebras for Brain.
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            gw.handle_message(
                "iris",
                {"type": "set_role_binding", "payload": {"role": "reasoning", "instance_id": "cerebras"}},
                session_id="session_iris",
            )
        )
        loop.close()

        updates = [m for (_, m) in ws.sent if m.get("type") == "role_binding_updated"]
        assert updates, "expected a role_binding_updated ack"
        ack_snapshot = updates[0]["payload"]["snapshot"]

        # "The settings panel" reads useInferenceState's merged snapshot
        # shape (providers + role_bindings) — same fields the ack carried.
        settings_binding = next(
            b for b in ack_snapshot["role_bindings"] if b["role"] == "reasoning"
        )
        assert settings_binding["instance_id"] == "cerebras"

        # And a THIRD, independent read straight off the router (as if the
        # settings panel had instead re-fetched /api/inference/state fresh)
        # agrees too — one source of truth, not two paths that happen to
        # match right now.
        fresh_snapshot = router.snapshot()
        fresh_binding = next(
            b for b in fresh_snapshot["role_bindings"] if b["role"] == "reasoning"
        )
        assert fresh_binding["instance_id"] == "cerebras"
        assert fresh_binding == settings_binding, (
            "the ack's snapshot and a fresh router.snapshot() disagree — "
            "there must be exactly one source of truth (D-3, REQ-4 AC4)"
        )

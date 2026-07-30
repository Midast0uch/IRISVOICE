"""Behavioral test (specs/phase-5-switcher, REQ-4 AC3) — a bind failure
surfaces the error and leaves the PREVIOUS selection active; the switcher
must never show the failed selection as active before it succeeds.

Drives the REAL `IRISGateway._handle_set_role_binding` handler twice against
one real `InferenceRouter`:
  1. A SUCCESSFUL bind (reasoning -> cerebras) — this is "the previous
     selection".
  2. A bind attempt that FAILS for a reason the handler already detects
     ("router unavailable" — `kernel._router is None`, exercised the same
     way a not-yet-initialized kernel would trigger it) — this must NOT
     touch the router's role-binding state at all.

Then asserts the router (the actual state ModelSwitcher and the settings
panel both read from) still shows the ORIGINAL binding — never the failed
attempt's target, and never an unbound/cleared role.
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
    reg.add(ProviderInstance(id="openai", label="OpenAI", kind=ProviderKind.API, model="gpt-4"))
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


def _make_gateway():
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws)
    gw._main_loop = asyncio.new_event_loop()
    return gw, ws


def _bound_instance(router: InferenceRouter, role: str) -> str | None:
    binding = next((b for b in router._roles.list() if b.role == role), None)
    return binding.instance_id if binding else None


class TestSwitchFailureKeepsPreviousSelectionActive:
    def test_failed_bind_leaves_the_previous_binding_untouched(self, monkeypatch):
        router = _make_router()
        gw, ws = _make_gateway()

        # Step 1: a SUCCESSFUL switch — reasoning -> cerebras. This is "the
        # previous selection" the rest of the test protects.
        monkeypatch.setattr(
            "backend.agent.get_agent_kernel", lambda session_id=None: _FakeKernel(router)
        )
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            gw.handle_message(
                "iris",
                {"type": "set_role_binding", "payload": {"role": "reasoning", "instance_id": "cerebras"}},
                session_id="session_iris",
            )
        )
        assert _bound_instance(router, "reasoning") == "cerebras"

        # Step 2: a FAILING switch attempt — router unavailable (the same
        # condition the real handler already detects and rejects).
        monkeypatch.setattr(
            "backend.agent.get_agent_kernel", lambda session_id=None: _FakeKernel(None)
        )
        ws.sent.clear()
        loop.run_until_complete(
            gw.handle_message(
                "iris",
                {"type": "set_role_binding", "payload": {"role": "reasoning", "instance_id": "openai"}},
                session_id="session_iris",
            )
        )
        loop.close()

        errors = [m for (_, m) in ws.sent if m.get("type") == "role_binding_error"]
        assert errors, f"expected a role_binding_error, got: {ws.sent}"
        updates = [m for (_, m) in ws.sent if m.get("type") == "role_binding_updated"]
        assert not updates, "a failed bind must never also send a success ack"

        # The REAL protection: the router — what both ModelSwitcher and the
        # settings panel actually read — still shows the PREVIOUS binding.
        # It must NOT show openai (the failed target) and must NOT be
        # unbound either.
        assert _bound_instance(router, "reasoning") == "cerebras", (
            "a failed bind attempt changed the active binding — REQ-4 AC3 violated"
        )

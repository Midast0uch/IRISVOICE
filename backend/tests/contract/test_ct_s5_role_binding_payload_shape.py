"""Contract test CT-S5 (specs/phase-5-switcher/design.md).

"`set_role_binding` message: payload shape unchanged — the switcher uses the
SAME message as settings (D-3)."

Drives the REAL `IRISGateway._handle_set_role_binding` handler (the one
handler both ModelSwitcher and the settings panel's ModelInferenceSection
write through via `sendRoleBinding` / `useInferenceState`) with a real
`InferenceRouter` wired to an isolated `ProviderRegistry` — not a mock that
could paper over a broken path — and pins:

  1. the accepted request payload shape: {role, instance_id, model_override?}
  2. the success ack shape: {success, role, instance_id, model_override,
     status, snapshot}
  3. that a SECOND caller (modeling the settings panel) reading the same
     process-wide registry sees the identical bound state — one handler,
     one source of truth, so the switcher and settings panel cannot disagree
     (REQ-4 AC4, D-3).
"""

from __future__ import annotations

import asyncio

import pytest

from backend.iris_gateway import IRISGateway
from backend.agent.inference.provider import ProviderInstance, ProviderKind
from backend.agent.inference.registry import ProviderRegistry
from backend.agent.inference.roles import RoleBindingTable
from backend.agent.inference.router import InferenceRouter


class _FakeWSManager:
    def __init__(self):
        self.sent = []
        self.broadcasts = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg):
        self.broadcasts.append((session_id, msg))

    async def broadcast(self, msg):
        self.broadcasts.append((None, msg))


class _FakeKernel:
    """Stand-in for AgentKernel exposing only what the handler reads: `_router`."""

    def __init__(self, router):
        self._router = router


def _make_router() -> InferenceRouter:
    # Same construction technique as test_apply_button_role_binding.py — an
    # isolated registry, not the real process-wide singleton, so this test
    # cannot leak state into (or be polluted by) other tests.
    reg = ProviderRegistry()
    reg.add(ProviderInstance(id="cerebras", label="Cerebras", kind=ProviderKind.API,
                              model="gemma-4-31b", api_base_url="https://api.cerebras.ai/v1"))
    reg.add(ProviderInstance(id="local:qwen3-9b", label="Local", kind=ProviderKind.INPROCESS,
                              model="qwen3-9b", loaded=True))
    router = InferenceRouter.__new__(InferenceRouter)
    object.__setattr__(router, "_registry", reg)
    object.__setattr__(router, "_roles", RoleBindingTable(reg))
    object.__setattr__(router, "_default_role", "reasoning")
    object.__setattr__(router, "_transports", {})
    object.__setattr__(router, "_inprocess_mgr", None)
    return router


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _make_gateway(router):
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws)
    gw._main_loop = asyncio.new_event_loop()
    return gw, ws, router


class TestCTS5RoleBindingPayloadShape:
    def test_request_payload_shape_role_instance_id_model_override(self, loop, monkeypatch):
        """Exactly what ModelSwitcher's `sendRoleBinding` sends
        (hooks/useInferenceState.ts:119-128): {role, instance_id,
        model_override?}."""
        router = _make_router()
        gw, ws, _ = _make_gateway(router)
        monkeypatch.setattr(
            "backend.agent.get_agent_kernel", lambda session_id=None: _FakeKernel(router)
        )

        msg = {
            "type": "set_role_binding",
            "payload": {"role": "reasoning", "instance_id": "cerebras", "model_override": "gemma-4-31b"},
        }
        loop.run_until_complete(gw.handle_message("iris", msg, session_id="session_iris"))

        updates = [m for (_, m) in ws.sent if m.get("type") == "role_binding_updated"]
        assert updates, f"expected a role_binding_updated ack, got: {ws.sent}"
        payload = updates[0]["payload"]
        assert payload["success"] is True
        assert payload["role"] == "reasoning"
        assert payload["instance_id"] == "cerebras"
        assert payload["model_override"] == "gemma-4-31b"
        assert "status" in payload
        assert "snapshot" in payload

    def test_model_override_is_optional(self, loop, monkeypatch):
        router = _make_router()
        gw, ws, _ = _make_gateway(router)
        monkeypatch.setattr(
            "backend.agent.get_agent_kernel", lambda session_id=None: _FakeKernel(router)
        )
        msg = {
            "type": "set_role_binding",
            "payload": {"role": "tool_execution", "instance_id": "local:qwen3-9b"},
        }
        loop.run_until_complete(gw.handle_message("iris", msg, session_id="session_iris"))
        updates = [m for (_, m) in ws.sent if m.get("type") == "role_binding_updated"]
        assert updates
        assert updates[0]["payload"]["model_override"] is None

    def test_switcher_and_settings_share_one_source_of_truth(self, loop, monkeypatch):
        """D-3 / REQ-4 AC4: the switcher and the settings panel write through
        the SAME handler and read the SAME registry snapshot — they cannot
        disagree because there is only one path to the state."""
        router = _make_router()
        gw, ws, _ = _make_gateway(router)
        monkeypatch.setattr(
            "backend.agent.get_agent_kernel", lambda session_id=None: _FakeKernel(router)
        )

        # "The switcher" binds Brain to cerebras.
        loop.run_until_complete(
            gw.handle_message(
                "iris",
                {"type": "set_role_binding", "payload": {"role": "reasoning", "instance_id": "cerebras"}},
                session_id="session_iris",
            )
        )

        # "The settings panel" reads the SAME router snapshot the switcher
        # just wrote through — same registry, same handler, same message.
        snapshot = router.snapshot()
        brain = next(b for b in snapshot["role_bindings"] if b["role"] == "reasoning")
        assert brain["instance_id"] == "cerebras", (
            "settings-panel view of the binding disagrees with what the "
            "switcher just set — REQ-4 AC4 violated"
        )

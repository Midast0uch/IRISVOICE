"""Session 268, handoff item 3.6 — pin the `field_update` alias routing.

The frontend (`hooks/useIRISWebSocket.ts`) sends every card-field edit as
`sendMessage("field_update", ...)`. The backend historically routed only
`update_field` -> `_handle_settings`, so every keystroke died at the
dispatcher with "Unknown message type: field_update". The fix added the
alias to the routing table (`backend/iris_gateway.py:765`) and to the
in-handler branch (`:1179`).

This drives the REAL dispatcher (`IRISGateway.handle_message`) — not the
handler directly — so it fails if either the routing entry or the
in-handler alias branch is deleted.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Tuple

import pytest

try:
    from backend.iris_gateway import IRISGateway
except ImportError:
    import sys

    sys.path.insert(0, "..")
    from backend.iris_gateway import IRISGateway


class _FakeWSManager:
    def __init__(self):
        self.sent: List[Tuple[str, Dict[str, Any]]] = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))

    async def broadcast_to_session(self, session_id, msg, exclude_clients=None):
        pass

    def get_session_id_for_client(self, client_id):
        return "sess-alias"

    async def flush_pending(self, session_id, client_id):
        pass


class _FakeState:
    current_category = None
    field_values: Dict[str, Any] = {}


class _FakeStateManager:
    async def get_state(self, session_id):
        return _FakeState()


def _make_gateway():
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws, state_manager=_FakeStateManager())
    gw._main_loop = asyncio.new_event_loop()
    gw._logger = logging.getLogger("test_field_update_alias")
    return gw, ws


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _routed_messages(monkeypatch, msg_type: str):
    """Send `msg_type` through the REAL dispatcher; return the kwargs the
    settings handler received plus everything the dispatcher sent back."""
    gw, ws = _make_gateway()
    received: List[Dict[str, Any]] = []

    async def _record_settings(session_id, client_id, message):
        received.append({"session_id": session_id, "client_id": client_id, "message": message})

    monkeypatch.setattr(gw, "_handle_settings", _record_settings)
    _run(gw.handle_message(
        "client-alias",
        {"type": msg_type, "payload": {"section_id": "s", "field_id": "f", "value": 1}},
        session_id="sess-alias",
    ))
    return received, ws.sent


class TestFieldUpdateAliasRouting:
    def test_field_update_routes_to_handle_settings(self, monkeypatch):
        """The frontend's verb reaches the settings handler through the real
        dispatcher — no alias entry, no settings persistence."""
        received, sent = _routed_messages(monkeypatch, "field_update")
        assert len(received) == 1, (
            f"field_update must dispatch to _handle_settings exactly once — "
            f"got {len(received)} deliveries"
        )
        assert received[0]["session_id"] == "sess-alias"
        assert received[0]["client_id"] == "client-alias"
        assert received[0]["message"]["type"] == "field_update"

    def test_field_update_is_not_rejected_as_unknown(self, monkeypatch):
        """The original bug: the dispatcher logged and sent
        "Unknown message type: field_update". No error reply may mention it."""
        _, sent = _routed_messages(monkeypatch, "field_update")
        for _client, msg in sent:
            text = str(msg)
            assert "Unknown message type" not in text, (
                f"field_update was rejected at the dispatcher: {text}"
            )

    def test_legacy_update_field_still_routes(self, monkeypatch):
        """The backend's historical verb keeps working — the alias was ADDED,
        not a rename."""
        received, _ = _routed_messages(monkeypatch, "update_field")
        assert len(received) == 1
        assert received[0]["message"]["type"] == "update_field"

    def test_genuinely_unknown_type_is_still_rejected(self, monkeypatch):
        """The alias must not degrade dispatch: an unknown verb still gets the
        error reply (guards against a catch-all swallowing typos)."""
        gw, ws = _make_gateway()

        async def _boom(*a, **k):
            raise AssertionError("no handler should be reached")

        monkeypatch.setattr(gw, "_handle_settings", _boom)
        _run(gw.handle_message(
            "client-alias",
            {"type": "definitely_not_a_real_type", "payload": {}},
            session_id="sess-alias",
        ))
        assert any("Unknown message type" in str(msg) for _c, msg in ws.sent), (
            "an unknown message type must still produce the Unknown message "
            "type error reply"
        )

"""T7a (REQ-4 AC2/AC4/AC5) — specs/task-card-v2-liquid-ink: the read half of
the T4/T4a write path.

T4/T4a persist cards into ``conversation_cards`` (write path: complete,
wired, tested — test_card_persistence_wiring.py). T6/T7 render a keyed card
collection per conversation (render path: complete, tested — 75 hook
tests). NOTHING CONNECTED THEM: there was no ``get_cards`` handler in
``iris_gateway.py`` and no endpoint exposing ``get_cards_for_conversation``.
A fresh page load therefore still showed no cards — the ORIGINAL
user-reported bug REQ-4 exists to fix.

This drives the REAL, unstubbed seam: cards written through the REAL
``ConversationContextStore.save_card`` (same store T4/T4a's writers use),
read back through the REAL ``IRISGateway._handle_get_cards``, onto the REAL
WS wire shape. Must FAIL if ``_handle_get_cards`` — or its dispatch
registration in ``handle_message`` — is deleted.
"""
from __future__ import annotations

import asyncio
import sys
import time

import pytest

try:
    from backend.iris_gateway import IRISGateway
except ImportError:
    sys.path.insert(0, "..")
    from backend.iris_gateway import IRISGateway

import backend.agent.conversation_context_store as ccs_module
from backend.agent.conversation_context_store import CardState, CardStepSnapshot


class _FakeWSManager:
    def __init__(self):
        self.sent = []

    async def send_to_client(self, client_id, msg):
        self.sent.append((client_id, msg))


def _make_gateway():
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws)
    gw._main_loop = asyncio.new_event_loop()
    import logging

    gw._logger = logging.getLogger("test_get_cards")
    return gw, ws


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Same isolation recipe as test_card_persistence_wiring.py — point the
    singleton at a tmp_path DB so this test never touches
    data/databases/conversation_contexts.db."""
    ccs_module.reset_context_store_for_testing()
    store = ccs_module.ConversationContextStore(db_path=tmp_path / "test_contexts.db")
    monkeypatch.setattr(ccs_module, "_store_instance", store)
    yield store
    store.close()
    ccs_module.reset_context_store_for_testing()


def test_get_cards_handler_returns_persisted_cards_across_the_seam(isolated_store):
    """CT-CARD-1 (REQ-4 AC2/AC4): a card written through the REAL store
    arrives back through the REAL handler on the wire shape the frontend
    consumes ({type:"cards", payload:{cards:[...]}})."""
    card = CardState(
        card_id="card-seam-1",
        conversation_id="conv-1",
        card_relation="new",
        plan_title="Research something",
        mode="agentic",
        steps=[
            CardStepSnapshot(id="s1", description="search the web", status="done", tool_name="web_search"),
            CardStepSnapshot(id="s2", description="write it up", status="working", tool_name="draft"),
        ],
        current_step=2,
        total_steps=2,
        terminal_state="done",
    )
    assert isolated_store.save_card(card) is True

    gw, ws = _make_gateway()
    msg = {"type": "get_cards", "payload": {"conversation_id": "conv-1"}}
    _run(gw._handle_get_cards("sess1", "client1", msg))

    assert ws.sent, "expected a cards response — handler never sent anything"
    client_id, response = ws.sent[-1]
    assert client_id == "client1"
    assert response["type"] == "cards"
    assert "payload" in response and "cards" in response["payload"]
    cards = response["payload"]["cards"]
    assert len(cards) == 1
    wire_card = cards[0]
    assert wire_card["card_id"] == "card-seam-1"
    assert wire_card["conversation_id"] == "conv-1"
    assert wire_card["plan_title"] == "Research something"
    assert wire_card["total_steps"] == 2
    assert [s["id"] for s in wire_card["steps"]] == ["s1", "s2"]
    assert [s["status"] for s in wire_card["steps"]] == ["done", "working"]
    assert wire_card["terminal_state"] == "done"


def test_get_cards_handler_isolates_threads(isolated_store):
    """REQ-4 AC3: a card from another conversation is never returned."""
    isolated_store.save_card(
        CardState(card_id="card-a", conversation_id="conv-a", plan_title="A")
    )
    isolated_store.save_card(
        CardState(card_id="card-b", conversation_id="conv-b", plan_title="B")
    )

    gw, ws = _make_gateway()
    msg = {"type": "get_cards", "payload": {"conversation_id": "conv-a"}}
    _run(gw._handle_get_cards("sess1", "client1", msg))

    _, response = ws.sent[-1]
    ids = {c["card_id"] for c in response["payload"]["cards"]}
    assert ids == {"card-a"}
    assert "card-b" not in ids


def test_get_cards_handler_transports_terminated_unknown_faithfully(isolated_store):
    """REQ-4 AC5: a card orphaned mid-run (still "running" in the row) is
    resolved to "terminated_unknown" by the STORE on read, and the handler
    must carry that value through UNCHANGED — never re-decide it, never
    silently pass "running" to the wire."""
    isolated_store.save_card(
        CardState(
            card_id="card-orphan",
            conversation_id="conv-1",
            steps=[CardStepSnapshot(id="s1", description="mid-flight", status="working")],
            terminal_state="running",
        )
    )

    gw, ws = _make_gateway()
    msg = {"type": "get_cards", "payload": {"conversation_id": "conv-1"}}
    _run(gw._handle_get_cards("sess1", "client1", msg))

    _, response = ws.sent[-1]
    wire_card = response["payload"]["cards"][0]
    assert wire_card["terminal_state"] == "terminated_unknown"


def test_get_cards_handler_empty_on_unknown_conversation(isolated_store):
    """Unknown/empty conversation -> empty list, never raises."""
    gw, ws = _make_gateway()
    msg = {"type": "get_cards", "payload": {"conversation_id": "nope"}}
    _run(gw._handle_get_cards("sess1", "client1", msg))

    _, response = ws.sent[-1]
    assert response["type"] == "cards"
    assert response["payload"]["cards"] == []

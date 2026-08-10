"""
Tests for Phase 4 (chat-card-redesign) — document editing / revision.

Verifies the backend can revise an already-rendered document by document_id
(bump revision + emit DOCUMENT_RENDER with updated=True) and that the agent's
structured `show` response can carry a document_id to revise in place.

Run: python -m pytest backend/tests/test_document_update.py -v
"""

import json
import sqlite3
from unittest.mock import patch, MagicMock

from backend.agent.document_store import DocumentDataStore
from backend.agent.agent_kernel import AgentKernel


def _store():
    return DocumentDataStore(sqlite3.connect(":memory:"))


def _make_kernel():
    with patch.object(AgentKernel, "__init__", lambda self, *a, **kw: None):
        k = AgentKernel.__new__(AgentKernel)
    k._memory = MagicMock()
    k.conversation_id = "conv-test"
    return k


def test_document_store_update_bumps_revision():
    store = _store()
    store.store(
        document_id="d1", conversation_id="c1", fmt="markdown",
        content="v1", variants={"markdown": "v1"}, alternatives=[], trust="trusted",
    )
    assert store.get("d1")["revision"] == 0
    assert store.get("d1")["content"] == "v1"
    ok = store.update("d1", "v2", "markdown", {"markdown": "v2"}, "trusted")
    assert ok is True
    rec = store.get("d1")
    assert rec["content"] == "v2"
    assert rec["revision"] == 1
    # unknown id -> no-op
    assert store.update("nope", "x", "markdown", {}, "trusted") is False


def test_update_document_emits_updated():
    store = _store()
    store.store(
        document_id="d1", conversation_id="c1", fmt="markdown",
        content="v1", variants={"markdown": "v1"}, alternatives=[], trust="trusted",
    )
    bus = MagicMock()
    k = _make_kernel()
    with patch("backend.agent.document_store.DocumentDataStore.get_for", return_value=store), \
         patch("backend.agent.event_bus.get_event_bus", return_value=bus):
        result = k.update_document("d1", "v2 revised", fmt="markdown", trust="trusted", turn_id="t1")
    assert result == "d1"
    assert store.get("d1")["content"] == "v2 revised"
    assert store.get("d1")["revision"] == 1
    assert bus.emit.called
    data = bus.emit.call_args.kwargs.get("data")
    assert data["updated"] is True
    assert data["revision"] == 1
    assert data["content"] == "v2 revised"
    assert data["document_id"] == "d1"


def test_update_document_unknown_id_returns_none():
    store = _store()
    bus = MagicMock()
    k = _make_kernel()
    with patch("backend.agent.document_store.DocumentDataStore.get_for", return_value=store), \
         patch("backend.agent.event_bus.get_event_bus", return_value=bus):
        result = k.update_document("missing", "x")
    assert result is None
    assert not bus.emit.called


def test_deliver_structured_response_revises_existing():
    store = _store()
    store.store(
        document_id="d1", conversation_id="c1", fmt="markdown",
        content="v1", variants={"markdown": "v1"}, alternatives=[], trust="trusted",
    )
    bus = MagicMock()
    k = _make_kernel()
    with patch("backend.agent.document_store.DocumentDataStore.get_for", return_value=store), \
         patch("backend.agent.event_bus.get_event_bus", return_value=bus):
        out = k._process_structured_response(
            json.dumps({"type": "show", "show": {"format": "markdown", "content": "v2", "document_id": "d1"}}),
            turn_id="t1", conversation_id="c1",
        )
    # Revised in place — no fresh render returned.
    assert out == ""
    assert store.get("d1")["content"] == "v2"
    data = bus.emit.call_args.kwargs.get("data")
    assert data["updated"] is True
    assert data["document_id"] == "d1"

"""Contract (specs/reply-surface-contract REQ-17, task T29 — CT-13): the
single-document body read.

The hydration list stays metadata-only (AC4, CT-DOC-1 untouched); this handler
is the lazy read. Scoped to the requesting conversation; a store miss is a
status, never an exception; blob-backed cards resolve through get_blob.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3

from unittest.mock import patch

from backend.agent.document_store import DocumentDataStore
from backend.iris_gateway import IRISGateway


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_to_client(self, client_id, msg):
        self.sent.append(msg)


def _gateway_and_store():
    gw = IRISGateway.__new__(IRISGateway)
    gw._logger = logging.getLogger("test_get_document_body")
    ws = _FakeWS()
    gw._ws_manager = ws
    store = DocumentDataStore(sqlite3.connect(":memory:"))
    return gw, ws, store


class _Kernel:
    def __init__(self, store):
        self._store = store

    def _get_document_store(self):
        return self._store


def _drive(gw, payload):
    async def run():
        await gw._handle_get_document_body("sess", "client-1", {"payload": payload})

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run())
    finally:
        loop.close()


class TestGetDocumentBody:
    def test_ok_returns_content_and_variants(self):
        gw, ws, store = _gateway_and_store()
        store.store(
            "d1", "conv-1", "markdown", "# Body", {"html": "<h1>Body</h1>"},
            [], "trusted", sources=[{"url": "http://x", "title": "X"}],
            har_path="data/har/x.har",
        )
        with patch(
            "backend.agent.agent_kernel.get_agent_kernel",
            return_value=_Kernel(store),
        ):
            _drive(gw, {"document_id": "d1", "conversation_id": "conv-1"})
        assert len(ws.sent) == 1
        msg = ws.sent[0]
        assert msg["type"] == "document_body"
        body = msg["payload"]
        assert body["status"] == "ok"
        assert body["content"] == "# Body"
        assert body["variants"] == {"html": "<h1>Body</h1>"}
        assert body["sources"] == [{"url": "http://x", "title": "X"}]
        assert body["har_path"] == "data/har/x.har"

    def test_unknown_document_returns_missing_not_error(self):
        gw, ws, store = _gateway_and_store()
        with patch(
            "backend.agent.agent_kernel.get_agent_kernel",
            return_value=_Kernel(store),
        ):
            _drive(gw, {"document_id": "nope", "conversation_id": "conv-1"})
        assert ws.sent[0]["payload"]["status"] == "missing"

    def test_document_from_another_conversation_is_out_of_scope(self):
        gw, ws, store = _gateway_and_store()
        store.store("d1", "conv-A", "markdown", "secret", {}, [], "trusted")
        with patch(
            "backend.agent.agent_kernel.get_agent_kernel",
            return_value=_Kernel(store),
        ):
            _drive(gw, {"document_id": "d1", "conversation_id": "conv-B"})
        assert ws.sent[0]["payload"]["status"] == "missing", (
            "a document must never cross conversation scope"
        )

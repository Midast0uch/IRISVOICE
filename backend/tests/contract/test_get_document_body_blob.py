"""Contract (reply-surface-contract REQ-17 edge "blob-backed card"; audit
2026-09-22, F2): a blob-only document body resolves as its serve URL.

get_blob returns {mime, data(bytes), byte_len}. Putting that dict in
`content` would fail WS serialization and, if it ever arrived, crash the
frontend merge (doc.content.trim on an object). The handler must hand back
the image's serve URL with format="image" — the same shape live screenshot
cards use — and never the raw blob dict.
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
    gw._logger = logging.getLogger("test_get_document_body_blob")
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


class TestBlobBackedCardFetchesAsImageUrl:
    def test_blob_doc_returns_serve_url_not_raw_dict(self):
        gw, ws, store = _gateway_and_store()
        store.store(
            "shot-1", "conv-1", "image", "", {}, [], "trusted",
            turn_id="turn-1",
        )
        assert store.store_blob("shot-1", b"\x89PNG-fake-bytes", "image/png")
        with patch(
            "backend.agent.agent_kernel.get_agent_kernel",
            return_value=_Kernel(store),
        ):
            _drive(gw, {"document_id": "shot-1", "conversation_id": "conv-1"})
        assert len(ws.sent) == 1
        body = ws.sent[0]["payload"]
        assert body["status"] == "ok"
        assert isinstance(body["content"], str), (
            "the raw blob dict must never reach the wire"
        )
        assert body["content"] == "/api/documents/shot-1/image"
        assert body["format"] == "image"

    def test_no_content_and_no_blob_still_missing(self):
        gw, ws, store = _gateway_and_store()
        store.store(
            "empty-1", "conv-1", "markdown", "", {}, [], "trusted",
        )
        with patch(
            "backend.agent.agent_kernel.get_agent_kernel",
            return_value=_Kernel(store),
        ):
            _drive(gw, {"document_id": "empty-1", "conversation_id": "conv-1"})
        assert ws.sent[0]["payload"]["status"] == "missing"

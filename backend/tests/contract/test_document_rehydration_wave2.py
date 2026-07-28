"""
Contract tests for document-rehydration Wave 2 (T3/T4/T5).

CT-DOC-1 (T3, REQ-4/REQ-12): get_documents WS handler returns the EXISTING
  wrapped {type:"documents", payload:{documents:[...]}} shape and isolates
  threads via the WHERE conversation_id= clause (other conv never returned).
CT-DOC-2 (T4, REQ-6): document:render payload carries sources when provenance
  exists, absent for plain docs.
CT-DOC-3 (T5, REQ-7/REQ-8): get_rendered_documents tool returns conv-scoped
  full document DATA (incl. har_path), excluding other threads.
"""
import asyncio
import sqlite3
import sys

from unittest.mock import AsyncMock, patch

import pytest

try:
    from backend.iris_gateway import IRISGateway
except ImportError:
    sys.path.insert(0, "..")
    from backend.iris_gateway import IRISGateway

from backend.agent.document_store import DocumentDataStore
from backend.agent.agent_kernel import AgentKernel
from backend.agent.tool_bridge import AgentToolBridge


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
    def __init__(self, store):
        self._store = store

    def _get_document_store(self):
        return self._store


def _make_gateway():
    ws = _FakeWSManager()
    gw = IRISGateway(ws_manager=ws)
    gw._main_loop = asyncio.new_event_loop()
    import logging
    gw._logger = logging.getLogger("test_doc_rehyd")
    return gw, ws


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _seeded_store():
    conn = sqlite3.connect(":memory:")
    store = DocumentDataStore(conn)
    store.store("c1a", "c1", "markdown", "CONTENT A", {}, [], "trusted",
                sources=[{"url": "http://x.com/a", "title": "A"}], har_path="data/har/j1.har")
    store.store("c1b", "c1", "table", "CONTENT B", {}, [], "trusted")
    store.store("c2a", "c2", "markdown", "OTHER CONV", {}, [], "trusted")
    return store


def test_ct_doc_1_get_documents_shape_and_thread_isolation():
    """T3: wrapped response shape + REQ-12 thread isolation via handler."""
    gw, ws = _make_gateway()
    store = _seeded_store()
    msg = {"type": "get_documents", "payload": {"conversation_id": "c1"}}

    async def run():
        with patch("backend.agent.agent_kernel.get_agent_kernel",
                   return_value=_FakeKernel(store)):
            await gw._handle_get_documents("sess1", "client1", msg)

    _run(run())

    assert ws.sent, "expected a documents response"
    client_id, response = ws.sent[-1]
    assert client_id == "client1"
    assert response["type"] == "documents"
    assert "payload" in response
    assert "documents" in response["payload"]
    docs = response["payload"]["documents"]
    # Thread isolation: only c1 docs returned, c2 excluded.
    ids = {d["document_id"] for d in docs}
    assert ids == {"c1a", "c1b"}
    assert "c2a" not in ids
    # Light metadata only (no content blob) on the UI path.
    for d in docs:
        assert "content" not in d
        assert d["conversation_id"] == "c1"
    # Provenance surfaced on the row that has it.
    a = next(d for d in docs if d["document_id"] == "c1a")
    assert a["sources"] == [{"url": "http://x.com/a", "title": "A"}]
    assert a["har_path"] == "data/har/j1.har"


def test_ct_doc_1_get_documents_empty_on_unknown_conv():
    """T3: unknown/empty conversation -> empty list, never raises."""
    gw, ws = _make_gateway()
    store = _seeded_store()
    msg = {"type": "get_documents", "payload": {"conversation_id": "nope"}}

    async def run():
        with patch("backend.agent.agent_kernel.get_agent_kernel",
                   return_value=_FakeKernel(store)):
            await gw._handle_get_documents("sess1", "client1", msg)

    _run(run())
    client_id, response = ws.sent[-1]
    assert response["type"] == "documents"
    assert response["payload"]["documents"] == []


import json


class _FakeEventBus:
    def __init__(self):
        self.emits = []

    def emit(self, event, data=None, turn_id=None, conversation_id=None):
        self.emits.append((event, data))


class _FakeEpisodic:
    def __init__(self, c):
        self.db = c

    def fragment_and_store(self, *a, **k):
        pass


class _FakeMI:
    def __init__(self, c):
        self.episodic = _FakeEpisodic(c)


def _make_kernel_with_store():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    mi = _FakeMI(conn)
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = mi
    k._pacman_zone_for_turn = lambda: "trusted"
    return k, DocumentDataStore.get_for(mi)


def _patch_emit(kernel_fn):
    bus = _FakeEventBus()
    with patch("backend.agent.event_bus.get_event_bus", return_value=bus), \
         patch("backend.agent.caducean_trajectory.get_trajectory_recorder") as gtr, \
         patch("backend.gateway.iris_ffi.ffi_immortus_chain_append"):
        gtr.return_value.get_latest_coordinate.return_value = None
        kernel_fn()
        return bus


def test_ct_doc_2_render_carries_sources_when_provenance():
    """T4/REQ-6: document:render payload carries sources + har_path."""
    k, _ = _make_kernel_with_store()
    resp = json.dumps(
        {
            "speak": "here is the summary",
            "show": {
                "format": "markdown",
                "content": "# The Doc",
                "sources": [{"url": "http://x.com/a", "title": "A"}],
                "har_path": "data/har/job1.har",
            },
        }
    )

    def run():
        k._process_structured_response(resp, turn_id="t1", conversation_id="c1")

    bus = _patch_emit(run)
    renders = [d for (ev, d) in bus.emits if ev.value == "document:render"]
    assert renders, "expected a document:render emit"
    data = renders[0]
    assert data["sources"] == [{"url": "http://x.com/a", "title": "A"}]
    assert data["har_path"] == "data/har/job1.har"
    assert data["document_id"]
    assert data["format"] == "markdown"


def test_ct_doc_2_render_absent_sources_for_plain():
    """T4/REQ-6: plain doc render has empty sources, no har_path."""
    k, _ = _make_kernel_with_store()
    resp = json.dumps(
        {
            "speak": "just talking",
            "show": {"format": "markdown", "content": "plain doc"},
        }
    )

    def run():
        k._process_structured_response(resp, turn_id="t1", conversation_id="c1")

    bus = _patch_emit(run)
    renders = [d for (ev, d) in bus.emits if ev.value == "document:render"]
    assert renders
    data = renders[0]
    assert data["sources"] == []
    assert data["har_path"] is None


def _make_bridge_with_store():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    store = DocumentDataStore(conn)
    store.store("c1a", "c1", "markdown", "FULL CONTENT A", {}, [], "trusted",
                sources=[{"url": "http://x.com/a", "title": "A"}], har_path="data/har/j1.har")
    store.store("c1b", "c1", "table", "FULL CONTENT B", {}, [], "trusted")
    store.store("c2a", "c2", "markdown", "OTHER CONV", {}, [], "trusted")
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._active_conversation_id = {}
    import logging
    bridge._logger = logging.getLogger("test_bridge")
    return bridge, store


def test_ct_doc_3_get_rendered_documents_conv_scoped():
    """T5/REQ-7/REQ-8: tool returns conv-scoped FULL data, excludes other threads."""
    bridge, store = _make_bridge_with_store()
    fake_kernel = _FakeKernel(store)

    async def run():
        with patch("backend.agent.agent_kernel.get_agent_kernel",
                   return_value=fake_kernel):
            return await bridge._execute_get_rendered_documents(
                {"conversation_id": "c1"}, "sess1"
            )

    result = _run(run())
    assert result["success"] is True
    assert result["conversation_id"] == "c1"
    docs = result["documents"]
    ids = {d["document_id"] for d in docs}
    assert ids == {"c1a", "c1b"}
    assert "c2a" not in ids
    # Full data path (metadata_only=False): content present + har_path surfaced.
    a = next(d for d in docs if d["document_id"] == "c1a")
    assert a["content"] == "FULL CONTENT A"
    assert a["har_path"] == "data/har/j1.har"
    assert a["sources"] == [{"url": "http://x.com/a", "title": "A"}]


def test_ct_doc_3_get_rendered_documents_falls_back_to_active_conv():
    """T5: when no conversation_id given, uses the active conversation for session."""
    bridge, store = _make_bridge_with_store()
    bridge._active_conversation_id = {"sess9": "c1"}
    fake_kernel = _FakeKernel(store)

    async def run():
        with patch("backend.agent.agent_kernel.get_agent_kernel",
                   return_value=fake_kernel):
            return await bridge._execute_get_rendered_documents({}, "sess9")

    result = _run(run())
    assert result["success"] is True
    assert result["conversation_id"] == "c1"
    assert {d["document_id"] for d in result["documents"]} == {"c1a", "c1b"}

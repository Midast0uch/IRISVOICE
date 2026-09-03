"""
Unit tests for cross-conversation document retrieval (Issue B).

The agent must be able to DISCOVER prior threads that rendered documents
(list_conversations) and PULL their existing data (get_rendered_documents with
a conversation_id) instead of falling back to a failing websearch. This is the
missing half that made "continue the previous task" websearch and never
synthesize.
"""
import asyncio
import logging
import sqlite3
from unittest.mock import patch

from backend.agent.document_store import DocumentDataStore
from backend.agent.tool_bridge import AgentToolBridge


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_store():
    conn = sqlite3.connect(":memory:")
    store = DocumentDataStore(conn)
    store.store(
        "c1a", "c1", "markdown", "FULL CONTENT A", {}, [], "trusted",
        sources=[{"url": "http://x.com/a", "title": "A"}], har_path="data/har/j1.har",
    )
    store.store("c1b", "c1", "table", "FULL CONTENT B", {}, [], "trusted")
    store.store("c2a", "c2", "markdown", "OTHER CONV DOC", {}, [], "trusted")
    return store


class _FakeKernel:
    def __init__(self, store):
        self._store = store

    def _get_document_store(self):
        return self._store


def _make_bridge(store):
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._active_conversation_id = {}
    bridge._logger = logging.getLogger("test_xconv")
    return bridge, store


def test_list_conversations_returns_distinct_threads():
    store = _make_store()
    convs = store.list_conversations()
    ids = [c["conversation_id"] for c in convs]
    assert set(ids) == {"c1", "c2"}
    by_id = {c["conversation_id"]: c for c in convs}
    assert by_id["c1"]["doc_count"] == 2
    assert by_id["c2"]["doc_count"] == 1


def test_execute_list_conversations_handler():
    bridge, store = _make_bridge(_make_store())
    fake_kernel = _FakeKernel(store)

    async def run():
        with patch("backend.agent.agent_kernel.get_agent_kernel", return_value=fake_kernel):
            return await bridge._execute_list_conversations({}, "sess1")

    result = _run(run())
    assert result["success"] is True
    ids = [c["conversation_id"] for c in result["conversations"]]
    assert set(ids) == {"c1", "c2"}


def test_get_rendered_documents_cross_thread_pulls_existing_data():
    """B scenario: agent in c2 pulls c1's already-rendered doc instead of websearching."""
    bridge, store = _make_bridge(_make_store())
    fake_kernel = _FakeKernel(store)

    async def run():
        with patch("backend.agent.agent_kernel.get_agent_kernel", return_value=fake_kernel):
            return await bridge._execute_get_rendered_documents({"conversation_id": "c1"}, "sess2")

    result = _run(run())
    assert result["success"] is True
    assert result["conversation_id"] == "c1"
    ids = {d["document_id"] for d in result["documents"]}
    assert ids == {"c1a", "c1b"}   # c1's existing docs, NOT c2's
    assert "c2a" not in ids

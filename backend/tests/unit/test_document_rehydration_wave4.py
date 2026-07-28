"""
Unit + contract tests for document-rehydration Wave 4 (T8).

CT-DOC-4 (T8/REQ-9): combine_documents merges A+B into one render, unions
  sources, preserves provenance.
CT-DOC-5 (T8/REQ-10/11): urls_needing_recrawl re-crawls ONLY when HAR evidence
  is missing/stale — never blindly.
CT-DOC-6 (T8): combine_documents tool is conv-scoped.
"""
import os
import sqlite3
import sys
import tempfile

from unittest.mock import patch

import pytest

sys.path.insert(0, "..")

from backend.agent.document_store import DocumentDataStore
from backend.agent.recombination import combine_documents, urls_needing_recrawl
from backend.agent.tool_bridge import AgentToolBridge


def _seeded_store():
    conn = sqlite3.connect(":memory:")
    store = DocumentDataStore(conn)
    store.store("a", "c1", "markdown", "CONTENT A", {}, [], "trusted",
                sources=[{"url": "http://x.com/a", "title": "A"}], har_path="data/har/ja.har")
    store.store("b", "c1", "markdown", "CONTENT B", {}, [], "trusted",
                sources=[{"url": "http://x.com/b", "title": "B"}], har_path="data/har/jb.har")
    store.store("other", "c2", "markdown", "OTHER", {}, [], "trusted")
    return store


def test_ct_doc_4_combine_unions_sources_and_content():
    store = _seeded_store()
    out = combine_documents(store, ["a", "b"], "c1")
    assert out is not None
    assert "CONTENT A" in out["content"]
    assert "CONTENT B" in out["content"]
    # Union of sources preserved on the combined doc.
    urls = {s["url"] for s in out["sources"]}
    assert urls == {"http://x.com/a", "http://x.com/b"}
    # New document is stored and resolvable.
    combined = store.get(out["document_id"])
    assert combined["content"] == out["content"]
    assert combined["conversation_id"] == "c1"


def test_ct_doc_4_combine_skips_missing_ids():
    store = _seeded_store()
    out = combine_documents(store, ["a", "missing"], "c1")
    assert out is not None
    assert "CONTENT A" in out["content"]
    assert {s["url"] for s in out["sources"]} == {"http://x.com/a"}


def test_ct_doc_5_recrawl_only_when_har_missing_or_stale():
    with tempfile.NamedTemporaryFile(suffix=".har", delete=False) as f:
        fresh_har = f.name
    try:
        sources = [
            {"url": "http://fresh.com", "har_path": fresh_har},   # fresh -> reuse
            {"url": "http://nohar.com"},                            # no HAR -> recrawl
        ]
        needed = urls_needing_recrawl(sources, max_age_s=3600)
        assert "http://fresh.com" not in needed
        assert "http://nohar.com" in needed
    finally:
        os.unlink(fresh_har)


def test_ct_doc_5_stale_har_triggers_recrawl():
    with tempfile.NamedTemporaryFile(suffix=".har", delete=False) as f:
        stale_har = f.name
    try:
        old = 0.0  # epoch -> far older than max_age
        os.utime(stale_har, (old, old))
        sources = [{"url": "http://stale.com", "har_path": stale_har}]
        needed = urls_needing_recrawl(sources, max_age_s=3600, now=1_000_000_000.0)
        assert "http://stale.com" in needed
    finally:
        os.unlink(stale_har)


def test_ct_doc_6_combine_tool_conv_scoped():
    store = _seeded_store()
    bridge = AgentToolBridge.__new__(AgentToolBridge)
    bridge._active_conversation_id = {}
    import logging
    bridge._logger = logging.getLogger("test_combine")

    class _FakeKernel:
        def __init__(self, s):
            self._store = s

        def _get_document_store(self):
            return self._store

    async def run():
        with patch("backend.agent.agent_kernel.get_agent_kernel",
                   return_value=_FakeKernel(store)):
            return await bridge._execute_combine_documents(
                {"document_ids": ["a", "b"], "conversation_id": "c1"}, "sess1"
            )

    import asyncio
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(run())
    finally:
        loop.close()
    assert result["success"] is True
    assert "CONTENT A" in result["content"]
    assert "CONTENT B" in result["content"]
    # Combined doc lives in c1, not c2.
    combined = store.get(result["document_id"])
    assert combined["conversation_id"] == "c1"

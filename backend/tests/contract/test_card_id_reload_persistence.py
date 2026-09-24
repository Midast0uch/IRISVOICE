"""Contract (reply-surface-contract REQ-10, edge "history reload"; audit
2026-09-22, F7): the prism card_id is PERSISTED and rehydrated.

A card's lifecycle id used to live only in AgentKernel._prism_card_by_doc —
a reload minted a fresh id while the document survived, so lifecycle events
(settle, dismiss, update) could not address a rehydrated card by the id any
client had already seen. The store now carries card_id and the kernel reads
it back before minting.
"""

from __future__ import annotations

import logging
import sqlite3

from unittest.mock import patch

from backend.agent.agent_kernel import AgentKernel
from backend.agent.document_store import DocumentDataStore


def _kernel(store: DocumentDataStore):
    k = AgentKernel.__new__(AgentKernel)
    k._prism_card_by_doc = {}  # cold — simulates a process restart
    return k


class TestCardIdPersistence:
    def test_store_roundtrip_keeps_card_id(self):
        store = DocumentDataStore(sqlite3.connect(":memory:"))
        store.store(
            "doc-1", "conv-1", "markdown", "# Hi", {}, [], "trusted",
            turn_id="turn-1", card_id="card_doc_keepme",
        )
        row = store.get("doc-1")
        assert row is not None
        assert row["card_id"] == "card_doc_keepme"

    def test_a_later_store_call_cannot_overwrite_the_card_id(self):
        store = DocumentDataStore(sqlite3.connect(":memory:"))
        store.store(
            "doc-1", "conv-1", "markdown", "# Hi", {}, [], "trusted",
            turn_id="turn-1", card_id="card_doc_keepme",
        )
        # Reformat-style rewrite without identity knowledge must not erase it.
        store.store(
            "doc-1", "conv-1", "html", "<h1>Hi</h1>", {}, [], "trusted",
            turn_id="turn-1",
        )
        assert store.get("doc-1")["card_id"] == "card_doc_keepme"

    def test_kernel_reuses_the_stored_card_id_after_restart(self):
        store = DocumentDataStore(sqlite3.connect(":memory:"))
        store.store(
            "doc-9", "conv-1", "markdown", "# D", {}, [], "trusted",
            card_id="card_doc_survived",
        )
        k = _kernel(store)
        with patch.object(
            AgentKernel, "_get_document_store", lambda self: store
        ), patch.object(
            AgentKernel, "__init__", lambda self: None
        ):
            card_id = AgentKernel._prism_card_id_for(k, "doc-9")
        assert card_id == "card_doc_survived", (
            "a rehydrated document must keep its original lifecycle id"
        )
        # ...and the reuse must warm the in-memory cache for the next lookup.
        assert k._prism_card_by_doc["doc-9"] == "card_doc_survived"

    def test_new_document_mints_then_persists_via_store(self):
        """A fresh mint is random — but once stored it is stable forever."""
        store = DocumentDataStore(sqlite3.connect(":memory:"))
        k = _kernel(store)
        with patch.object(AgentKernel, "_get_document_store", lambda self: store):
            minted = AgentKernel._prism_card_id_for(k, "doc-new")
            store.store(
                "doc-new", "conv-1", "markdown", "# X", {}, [], "trusted",
                card_id=minted,
            )
        k2 = _kernel(store)  # "restarted" kernel: empty in-memory map
        with patch.object(AgentKernel, "_get_document_store", lambda self: store):
            again = AgentKernel._prism_card_id_for(k2, "doc-new")
        assert again == minted

    def test_card_id_rehydrates_in_metadata_only_hydration(self):
        """REQ-17 AC4 + REQ-10: hydration stays metadata-only but the
        lifecycle id now rides it."""
        store = DocumentDataStore(sqlite3.connect(":memory:"))
        store.store(
            "doc-5", "conv-1", "markdown", "# M", {}, [], "trusted",
            turn_id="turn-5", card_id="card_doc_meta",
        )
        rows = store.list_for_conversation("conv-1", metadata_only=True)
        assert rows and rows[0]["card_id"] == "card_doc_meta"
        assert "content" not in rows[0], "hydration must stay metadata-only"

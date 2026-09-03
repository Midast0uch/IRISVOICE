#!/usr/bin/env python3
"""Wave 1 unit tests — T1 (document_store.list_for_conversation).

Run:  pytest backend/tests/unit/test_document_rehydration_wave1.py -q
"""
import sqlite3
import sys

REPO_ROOT = r"C:\dev\IRISVOICE"
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.agent.document_store import DocumentDataStore


def test_t1_list_scoped_by_conversation():
    conn = sqlite3.connect(":memory:")
    store = DocumentDataStore(conn)
    store.store("d_c1a", "c1", "markdown", "BIG CONTENT 1", {}, [], "trusted",
                sources=[{"url": "http://x.com/a", "title": "A"}], har_path="data/har/j1.har")
    store.store("d_c1b", "c1", "markdown", "BIG CONTENT 2", {}, [], "trusted")
    store.store("d_c2a", "c2", "markdown", "OTHER CONV", {}, [], "trusted")
    c1 = store.list_for_conversation("c1")
    ids = {d["document_id"] for d in c1}
    assert ids == {"d_c1a", "d_c1b"}
    assert all(d["conversation_id"] == "c1" for d in c1)
    # Other conversation excluded (REQ-12 thread isolation).
    assert "d_c2a" not in ids


def test_t1_metadata_only_omits_content():
    conn = sqlite3.connect(":memory:")
    store = DocumentDataStore(conn)
    store.store("d1", "c1", "markdown", "BIG CONTENT BLOB", {}, [], "trusted",
                sources=[{"url": "u", "title": "t"}], har_path="data/har/j.har")
    light = store.list_for_conversation("c1", metadata_only=True)
    assert len(light) == 1
    assert "content" not in light[0]
    assert light[0]["document_id"] == "d1"
    assert light[0]["sources"] == [{"url": "u", "title": "t"}]
    assert light[0]["har_path"] == "data/har/j.har"
    # Full path includes content.
    full = store.list_for_conversation("c1", metadata_only=False)
    assert full[0]["content"] == "BIG CONTENT BLOB"


def test_t1_alter_idempotent_double_run():
    conn = sqlite3.connect(":memory:")
    store = DocumentDataStore(conn)
    store._ensure_table()
    store._ensure_table()  # second run must be a safe no-op
    cols = {r[1] for r in conn.execute("PRAGMA table_info(document_data)").fetchall()}
    for col in ("source_document_id", "sources", "har_path"):
        assert col in cols

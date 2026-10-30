"""Contract: the native `remember` tool writes the app pin store, and `recall`
reads it back.

`remember` is a thin `PinStore` wrapper. It must:
  * use `app_write` (PinStore), never a second connection (FFI single-writer),
  * update the existing pin for the same attribute (newest wins),
  * reject empty attribute/value and cap the lengths,
  * round-trip through `_recall_memory_payload` (`pins`).
"""
from __future__ import annotations

import sqlite3

from backend.agent.tool_bridge import (
    _recall_memory_payload,
    _remember_memory_payload,
)
from backend.memory.pin_store import PinStore


def _make_app_pin_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE mycelium_pins (
            pin_id TEXT PRIMARY KEY, title TEXT NOT NULL,
            pin_type TEXT DEFAULT 'note', content TEXT,
            tags TEXT DEFAULT '[]', file_refs TEXT DEFAULT '[]',
            image_refs TEXT DEFAULT '[]', url_refs TEXT DEFAULT '[]',
            project_id TEXT, origin_id TEXT,
            created_at REAL NOT NULL, updated_at REAL NOT NULL,
            is_permanent INTEGER DEFAULT 0
        );
        CREATE TABLE mycelium_pin_links (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL, source_id TEXT NOT NULL,
            target_type TEXT NOT NULL, target_id TEXT NOT NULL,
            relationship TEXT NOT NULL, weight REAL DEFAULT 1.0,
            created_at REAL NOT NULL
        );
    """)
    return conn


class _EpisodicStub:
    def __init__(self, conn):
        self.db = conn

    def retrieve_context_chunks(self, *a, **k):
        return []

    def retrieve_similar(self, *a, **k):
        return []


def test_remember_adds_then_updates_one_pin():
    conn = _make_app_pin_db()
    first = _remember_memory_payload(conn, "library card number", "880417")
    assert first["success"] is True
    assert first["updated"] is False
    assert len(PinStore(conn).list()) == 1

    second = _remember_memory_payload(conn, "library card number", "990001")
    assert second["success"] is True
    assert second["updated"] is True
    pins = PinStore(conn).list()
    assert len(pins) == 1, "re-teaching an attribute must update, not duplicate"
    assert pins[0].content == "990001"
    assert pins[0].title == "fact:library card number"


def test_remember_rejects_empty_and_caps_length():
    conn = _make_app_pin_db()
    assert _remember_memory_payload(conn, "", "x")["success"] is False
    assert _remember_memory_payload(conn, "x", "")["success"] is False
    long_value = "a" * 5000
    out = _remember_memory_payload(conn, "long", long_value)
    assert out["success"] is True
    assert len(out["value"]) == 2000
    assert PinStore(conn).list()[0].content == "a" * 2000


def test_remember_then_recall_returns_the_pin():
    conn = _make_app_pin_db()
    _remember_memory_payload(conn, "library card number", "880417")
    payload = _recall_memory_payload(_EpisodicStub(conn), "library card number")
    assert payload["pins"]
    assert payload["pins"][0]["pin"]["content"] == "880417"

"""Contract: `recall_memory` must reach the app's structured pin store.

The app memory already has `mycelium_pins` + `mycelium_pin_links`, written
through `PinStore.add` -> `app_write` (the ONE writer, same queue as the FFI).
`recall_memory` read chunks/chain/episodes only, so a pinned fact was invisible
to the native tool. This pins the missing leg and its failure-soft behavior.

`pins` (18 columns) is the MCM build store's table; `mycelium_pins` is the app
table (pin_store.py:140-159). This test uses the app schema.
"""
from __future__ import annotations

import sqlite3

from backend.agent.tool_bridge import _recall_memory_payload
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


def test_recall_memory_returns_a_pinned_fact():
    conn = _make_app_pin_db()
    PinStore(conn=conn).add(
        title="Library card number",
        content="880417",
        tags=["fact", "user"],
        pin_type="note",
    )
    payload = _recall_memory_payload(_EpisodicStub(conn), "library card number")
    assert payload["success"] is True
    assert payload["pins"], "recall_memory must return the pin leg"
    pin = payload["pins"][0]["pin"]
    assert pin["title"] == "Library card number"
    assert pin["content"] == "880417"
    assert payload["pins"][0]["score"] > 0


def test_recall_memory_pins_leg_fails_soft_without_the_table():
    conn = sqlite3.connect(":memory:")  # no mycelium_pins
    payload = _recall_memory_payload(_EpisodicStub(conn), "anything")
    assert payload["success"] is True
    assert payload["pins"] == []
    assert payload["chunks"] == []
    assert payload["chain"] == []
    assert payload["episodes"] == []

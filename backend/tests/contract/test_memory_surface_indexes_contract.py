"""The two indexes the Memory surface API needs exist on the app store (owner approved 2026-10-21).

  idx_memory_events_thread_ts  memory_events(thread_id, ts)  - one strand's events by thread
  idx_memory_chain_chain_id    memory_chain(chain_id)        - resolving the chain ids recall refs name

Without them surface_queries falls back to a capped ts-window scan ("partial" strand events) and does not
resolve chain refs at all (a 42k-row scan, 11 s warm / 98 s cold). surface_queries gates on has_index_on,
so it picks the indexes up by itself. Checked by NAME: the fresh-store chain_id is a PRIMARY KEY with an
autoindex, the live table (made by the native core) has none.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from backend.gateway import iris_ffi as _ffi
from backend.memory import memory_events as me
from backend.memory.surface_queries import has_index_on

WANT = {"idx_memory_events_thread_ts", "idx_memory_chain_chain_id"}


def _names(conn) -> set:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}


def test_app_store_has_the_memory_surface_indexes():
    tmp = Path(tempfile.mkdtemp(prefix="memidx-"))

    # A fresh app store, built the way startup builds it.
    eng = _ffi._PythonFallbackEngine(db_path=str(tmp / "fresh.db"), key_hex="00" * 32)
    fresh = sqlite3.connect(str(tmp / "fresh.db"))
    try:
        me.ensure_schema(fresh)
        assert WANT <= _names(fresh), WANT - _names(fresh)
    finally:
        fresh.close()
        eng._conn.close()

    # A store as it is live: both tables exist from before, chain_id is a plain column, no new indexes.
    old = sqlite3.connect(str(tmp / "old.db"))
    try:
        old.execute("CREATE TABLE memory_events (event_id TEXT PRIMARY KEY, ts REAL NOT NULL, schema_version INTEGER "
                    "NOT NULL, thread_id TEXT, label TEXT NOT NULL, evidence TEXT NOT NULL, label_source TEXT NOT NULL)")
        old.execute("CREATE TABLE memory_cases (case_id TEXT PRIMARY KEY)")
        old.execute("CREATE TABLE memory_chain (thread_id TEXT NOT NULL, created_at REAL NOT NULL)")
        old.commit()
        me._COLUMNS_OK.clear()
        me.ensure_schema(old)
        _ffi.migrate_memory_chain_schema(old, str(tmp / "old.db"))
        assert WANT <= _names(old), WANT - _names(old)
        assert has_index_on(old, "memory_events", "thread_id")
        assert has_index_on(old, "memory_chain", "chain_id")
        plan = " ".join(r[3] for r in old.execute(
            "EXPLAIN QUERY PLAN SELECT event_id FROM memory_events WHERE thread_id = ? ORDER BY ts DESC LIMIT 5", ("t",)))
        assert "idx_memory_events_thread_ts" in plan, plan
    finally:
        old.close()

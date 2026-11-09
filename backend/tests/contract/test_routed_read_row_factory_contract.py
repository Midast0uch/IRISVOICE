"""A read routed to this thread's own connection keeps the caller's row_factory.

Live 2026-11-09, every boot: "[memory_api] snapshot warm-up failed (the first
request computes instead): TypeError: tuple indices must be integers or
slices, not str". surface_queries set sqlite3.Row on its connection, the
store connection sent the SELECT to the per-thread lane connection (opened
bare), and the rows came back as plain tuples. Drives the real routing with a
real store file; only "the native writer owns this file" is stood in.
"""
from __future__ import annotations

import sqlite3

from backend.memory import db as memdb


def test_a_routed_read_returns_the_callers_row_type(tmp_path, monkeypatch):
    path = tmp_path / "memory.db"
    seed = sqlite3.connect(path)
    seed.execute("PRAGMA journal_mode=WAL")
    seed.execute("CREATE TABLE t (name TEXT, n INTEGER)")
    seed.execute("INSERT INTO t VALUES ('a', 1)")
    seed.commit()
    seed.close()
    conn = memdb.open_encrypted_memory(str(path), b"")
    monkeypatch.setattr(memdb, "owns_store", lambda c: True)
    assert memdb.lane_connection(conn) is not conn, "the read must be routed"

    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT name, n FROM t").fetchone()
    assert row["name"] == "a" and row["n"] == 1

    # another caller on the same thread with plain tuples is not affected
    other = memdb.open_encrypted_memory(str(path), b"")
    assert other.execute("SELECT name FROM t").fetchone() == ("a",)

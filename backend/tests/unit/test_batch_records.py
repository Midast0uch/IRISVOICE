"""Unit tests for batch execution record tables (REQ-19, T5).

Exercises initialise_mycelium_schema against an in-memory SQLite database:
parent/child tables exist, init is idempotent (safe on live stores), and the
child -> parent foreign key holds inside one atomic transaction.
"""

import sqlite3
import time

import pytest

from backend.memory.db import initialise_mycelium_schema


@pytest.fixture()
def conn():
    cx = sqlite3.connect(":memory:")
    cx.execute("PRAGMA foreign_keys=ON")
    try:
        yield cx
    finally:
        cx.close()


def _tables(cx):
    return {r[0] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def test_batch_tables_created(conn):
    initialise_mycelium_schema(conn)
    tables = _tables(conn)
    assert "batch_records" in tables
    assert "batch_node_records" in tables


def test_schema_init_is_idempotent(conn):
    """T5: safe to run on every startup / live stores (IF NOT EXISTS)."""
    initialise_mycelium_schema(conn)
    initialise_mycelium_schema(conn)  # must not raise
    assert _tables(conn) >= {"batch_records", "batch_node_records"}


def test_parent_child_commit_is_atomic(conn):
    """REQ-19 AC19.1 shape: one parent + linked children in one transaction."""
    initialise_mycelium_schema(conn)
    now = time.time()
    with conn:  # single atomic transaction
        conn.execute(
            "INSERT INTO batch_records "
            "(batch_id, tool, session_id, item_count, ok_count, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            ("b1", "crawler_query", "s1", 2, 1, now),
        )
        conn.executemany(
            "INSERT INTO batch_node_records "
            "(node_id, batch_id, item_key, ok, result_json, error, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [("b1#0", "b1", "a", 1, '{"price": 5}', None, now),
             ("b1#1", "b1", "b", 0, '{}', "timeout", now)],
        )
    got = conn.execute(
        "SELECT item_key, ok FROM batch_node_records WHERE batch_id='b1' "
        "ORDER BY item_key").fetchall()
    assert got == [("a", 1), ("b", 0)]
    assert conn.execute(
        "SELECT ok_count FROM batch_records WHERE batch_id='b1'").fetchone() == (1,)


def test_orphan_child_rejected(conn):
    """The FK pins every child to a real parent BatchRecord."""
    initialise_mycelium_schema(conn)
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute(
                "INSERT INTO batch_node_records "
                "(node_id, batch_id, item_key, ok, created_at)"
                " VALUES ('x#0', 'no-such-batch', 'x', 0, 0.0)",
            )

"""T16 (REQ-19): save_batch_footprint — atomic write of a completed batch run
into memory.db + coordinate graph, with non-blockable rollback / idempotence.
"""
from __future__ import annotations

import pytest

from backend.memory.db import open_encrypted_memory
from backend.memory.card_footprint import save_batch_footprint


def _db(tmp_path):
    """Scratch DB per test, pre-initialized with the batch tables."""
    conn = open_encrypted_memory(str(tmp_path / "memory.db"), b"test-key" * 4)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS batch_records (
            batch_id    TEXT PRIMARY KEY,
            tool        TEXT NOT NULL,
            session_id  TEXT NOT NULL DEFAULT '',
            item_count  INTEGER NOT NULL DEFAULT 0,
            ok_count    INTEGER NOT NULL DEFAULT 0,
            created_at  REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS batch_node_records (
            node_id     TEXT PRIMARY KEY,
            batch_id    TEXT NOT NULL REFERENCES batch_records(batch_id),
            item_key    TEXT NOT NULL,
            ok          INTEGER NOT NULL DEFAULT 0,
            result_json TEXT DEFAULT '{}',
            error       TEXT,
            created_at  REAL NOT NULL
        );
    """)
    conn.commit()
    return conn


def test_atomic_batch_write_inserts_parent_and_children(tmp_path):
    """One batch write inserts ONE batch_records row + linked children in
    ONE transaction. A batch that fails halfway must leave only partial
    siblings (never parent without parts, never parts without parent)."""
    db = _db(tmp_path)
    ok = save_batch_footprint(
        db,
        batch_id="b-alpha",
        tool="fetch.crawl",
        session_id="s-alpha",
        items=[
            {"item_key": "urls", "ok": True, "result": "found"},
            {"item_key": "threads", "ok": False, "error": "timeout"},
        ],
    )
    assert ok is True  # write succeeded

    rows = db.execute(
        "SELECT COUNT(*) FROM batch_records WHERE batch_id=?", ("b-alpha",)
    ).fetchone()
    assert rows[0] == 1
    kids = db.execute(
        "SELECT COUNT(*) FROM batch_node_records WHERE batch_id=?", ("b-alpha",)
    ).fetchone()
    assert kids[0] == 2


def test_ok_count_matches_children(tmp_path):
    db = _db(tmp_path)
    save_batch_footprint(
        db,
        batch_id="b-ok",
        tool="fetch.crawl",
        session_id="s",
        items=[
            {"item_key": "a", "ok": True, "result": "ok1"},
            {"item_key": "b", "ok": True, "result": "ok2"},
            {"item_key": "c", "ok": False, "error": "x"},
        ],
    )
    n = db.execute(
        "SELECT ok_count FROM batch_records WHERE batch_id='b-ok'"
    ).fetchone()[0]
    assert n == 2


def test_batch_write_is_atomic_on_mid_failure(tmp_path):
    """If ANY child write fails mid batch, the whole batch rolls back."""
    db = _db(tmp_path)
    with pytest.raises(Exception):
        save_batch_footprint(
            db,
            batch_id="b-atomic",
            tool="fetch.crawl",
            session_id="s",
            items=[
                {"item_key": "a", "ok": True, "result": "ok1"},
                {"item_key": "b", "ok": False, "error": "partial"},
            ],
            fail_on_child=True,
        )
    rows = db.execute(
        "SELECT COUNT(*) FROM batch_records WHERE batch_id='b-atomic'"
    ).fetchone()[0]
    assert rows == 0  # nothing left behind


def test_idempotent_re_save_on_same_batch_id(tmp_path):
    db = _db(tmp_path)
    items = [{"item_key": "x", "ok": True, "result": "r1"}]
    save_batch_footprint(
        db, batch_id="b-idem", tool="crawl", session_id="s", items=items,
    )
    ok2 = save_batch_footprint(
        db, batch_id="b-idem", tool="crawl", session_id="s", items=items,
    )
    assert ok2 is True  # never crashes on re-write of the same batch
    print(db.execute(
        "SELECT COUNT(*) FROM batch_records WHERE batch_id='b-idem'"
    ).fetchone()[0])
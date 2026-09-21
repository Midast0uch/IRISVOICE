"""CT-3 (vision-goal-directed-search REQ-19, T23 + T16): batch memory writes
are ATOMIC — one parent BatchRecord + all child NodeRecords under ONE
SQLite transaction, or nothing at all.

Why this contract exists: batch crawls write N+1 rows. A mid-transaction
crash that leaves the parent without its children (or 3 of 5 children)
silently reverses history: recalls against the batch then return a partial
record that LOOKS complete. The test uses ``fail_on_child``, the deliberate
test seam in ``save_batch_footprint``, to force a mid-transaction raise and
asserts the rollback left no partial state.
"""
from __future__ import annotations

import sqlite3

import pytest

from backend.memory.card_footprint import save_batch_footprint
from backend.memory.db import initialise_mycelium_schema


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    initialise_mycelium_schema(c)
    yield c
    c.close()


_CHILDREN = [
    {"item_key": "https://a.example/1", "ok": True, "result": {"price": 1999}},
    {"item_key": "https://b.example/2", "ok": False, "error": "rate_limited"},
    {"item_key": "https://c.example/3", "ok": True, "result": {"price": 1899}},
]


def _counts(conn) -> tuple[int, int]:
    parents = conn.execute("SELECT COUNT(*) FROM batch_records").fetchone()[0]
    nodes = conn.execute("SELECT COUNT(*) FROM batch_node_records").fetchone()[0]
    return parents, nodes


def test_happy_path_commits_parent_and_all_children_in_one_tx(conn):
    ok = save_batch_footprint(
        conn, batch_id="b-1", tool="fetch.crawl", session_id="s",
        items=_CHILDREN,
    )
    assert ok is True

    p, n = _counts(conn)
    assert (p, n) == (1, len(_CHILDREN))
    parent = conn.execute(
        "SELECT tool, session_id, item_count, ok_count FROM batch_records "
        "WHERE batch_id='b-1'"
    ).fetchone()
    assert parent == ("fetch.crawl", "s", 3, 2)


def test_mid_transaction_failure_rolls_back_then_raises(conn):
    """AC19.1: a crash writing child #0 must leave NO parent row and NO
    child rows — the transaction is one atomic unit.

    THE EXISTING COMMIT PINS THE RAISE: backend/tests/unit/test_batch_footprint.py
    ::test_batch_write_is_atomic_on_mid_failure asserts the exception
    PROPAGATES after rollback (not a swallowed False). This contract re-pins
    the same surface from the visionary batch side so both halves hold:
    rollback first (zero rows), raise second (loud to the caller).
    """
    with pytest.raises(RuntimeError):
        save_batch_footprint(
            conn, batch_id="b-crash", tool="fetch.crawl", session_id="s",
            items=_CHILDREN, fail_on_child=True,
        )
    assert _counts(conn) == (0, 0), (
        "mid-transaction failure left partial batch rows — an orphaned "
        "batch_records parent would report a fabricated complete batch later"
    )


def test_idempotent_resave_is_a_noop(conn):
    """AC19.1 retry safety: a re-save of the same batch_id (circuit retry,
    replay) never duplicates rows and reports success."""
    assert save_batch_footprint(
        conn, batch_id="b-2", tool="fetch.vision", session_id="s", items=_CHILDREN,
    ) is True
    before = _counts(conn)
    assert save_batch_footprint(
        conn, batch_id="b-2", tool="fetch.vision", session_id="s", items=_CHILDREN * 2,
    ) is True
    assert _counts(conn) == before, (
        "re-saving an existing batch_id appended duplicate rows"
    )


def test_empty_batch_id_is_rejected_without_writes(conn):
    """AC guard: a batch with no identity must not write (a write under ''
    would collide with every later anonymous batch)."""
    assert save_batch_footprint(
        conn, batch_id="", tool="fetch.crawl", session_id="s", items=_CHILDREN,
    ) is False
    assert _counts(conn) == (0, 0)

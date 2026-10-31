"""Contract: the recent-facts leg reads the Immortus chain, not chunk rows.

2026-10-30: the leg read ``context_chunks.tool_name='user_turn'``. That writer
landed for a few turns only and chunk pruning removed the rest — after a 33-turn
probe run the store held 158 chain user_turn rows and 1 chunk row. The chain
records every turn, so it is the source that can keep the newest 8 facts.
"""
import sqlite3

from backend.agent.agent_kernel import _recent_user_turn_texts


def _db():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE memory_chain (entry_id INTEGER PRIMARY KEY, "
        "insight TEXT, content TEXT, node_type TEXT, stale INTEGER DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE context_chunks (content TEXT, tool_name TEXT, "
        "folded_into TEXT, timestamp TEXT)"
    )
    return conn


def _chain(db, insight, node_type="user_turn", content=""):
    db.execute(
        "INSERT INTO memory_chain (insight, content, node_type) VALUES (?, ?, ?)",
        (insight, content, node_type),
    )


def test_newest_first_and_the_current_turn_is_skipped():
    db = _db()
    _chain(db, "my card is alpha")
    _chain(db, "my card is bravo")
    _chain(db, "the answer was 42", node_type="response")
    _chain(db, "What is my card?")
    out = _recent_user_turn_texts(db, "What is my card?", limit=8)
    assert out == ["my card is bravo", "my card is alpha"]


def test_limit_is_bounded_and_chunk_rows_are_not_a_source():
    db = _db()
    for i in range(12):
        _chain(db, f"fact {i}")
    db.execute(
        "INSERT INTO context_chunks (content, tool_name, folded_into) VALUES (?, ?, ?)",
        ("chunk only fact", "user_turn", None),
    )
    out = _recent_user_turn_texts(db, "", limit=8)
    assert len(out) == 8
    assert out[0] == "fact 11"
    assert "chunk only fact" not in out


def test_falls_back_to_content_and_strips_the_user_prefix():
    db = _db()
    _chain(db, None, content="User: my spot is A1\nAssistant: noted")
    assert _recent_user_turn_texts(db, "", limit=8) == ["my spot is A1"]


def test_a_missing_table_returns_no_facts_instead_of_raising():
    assert _recent_user_turn_texts(sqlite3.connect(":memory:")) == []


def test_a_forgotten_fact_is_not_offered_to_recall():
    """`forget` marks the chain rows that quote the value stale. They stay as
    history but must leave this leg, or the fact comes straight back."""
    db = _db()
    _chain(db, "my locker code is locker-live-77")
    _chain(db, "my parking spot is spot-1")
    db.execute(
        "UPDATE memory_chain SET stale = 1 WHERE insight LIKE '%locker-live-77%'"
    )
    out = _recent_user_turn_texts(db, "", limit=8)
    assert out == ["my parking spot is spot-1"]

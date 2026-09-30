"""Behavioral K2 (REQ-4 AC4.2/AC4.4): the per-step chain neighbors are relevance-gated.

Drives the REAL ``AgentKernel._der_recall_neighborhood`` (+ the block text the
step receives) against a temp SQLite chain store. Owner rule 2026-09-30: chain
data enters the context ONLY when relevant to the current task.

  - a same-topic row whose text matches the step goal IS injected;
  - a same-topic row with unrelated text is NOT;
  - a matching row of ANOTHER topic is NOT;
  - a step with no passing row gets NO neighbors block (empty string);
  - survivors rank by state proximity, then recency;
  - one ``[chain_recall] cand=<n> kept=<k> ms=<t>`` line per recall;
  - rows injected per step: before (recency + topic only, limit 3) vs after.
"""
from __future__ import annotations

import logging
import sqlite3
from types import SimpleNamespace
from unittest import mock

import pytest

from backend.agent.agent_kernel import AgentKernel, _der_neighbors_block
from backend.agent.ontology_recall import RecallFilters, run_filtered_recall

GOAL = "fix the failing pytest in the billing module tax rounding"
MATCH = "edit billing module tax rounding so the pytest passes"
UNRELATED = "summarize the weather forecast for tuesday afternoon"


def _store() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE memory_chain ("
        " chain_id TEXT PRIMARY KEY, thread_id TEXT, result TEXT, coords_from TEXT,"
        " coords_to TEXT, nbl_outcome TEXT, insight TEXT, created_at REAL,"
        " node_type TEXT, topic_domain TEXT, execution_domain TEXT)"
    )
    conn.execute("CREATE INDEX idx_memory_chain_created ON memory_chain(created_at)")
    return conn


def _row(conn, chain_id, insight, created_at, topic="coding", coords="", result="success"):
    conn.execute(
        "INSERT INTO memory_chain (chain_id, thread_id, result, coords_from, coords_to,"
        " insight, created_at, node_type, topic_domain, execution_domain)"
        " VALUES (?, 't', ?, ?, ?, ?, ?, 'step', ?, 'der')",
        (chain_id, result, coords or None, coords or None, insight, created_at, topic),
    )


def _kernel(conn):
    k = AgentKernel.__new__(AgentKernel)
    k._memory_interface = SimpleNamespace(_mycelium=SimpleNamespace(conn=conn))
    return k


def _item(goal=GOAL, topic="coding"):
    return SimpleNamespace(
        description=goal,
        node_record=SimpleNamespace(node_type="step", topic_domain=topic,
                                    execution_domain="der"),
    )


def _ids(rows):
    return [r["chain_id"] for r in rows]


def test_matching_row_injected_unrelated_and_other_topic_not():
    conn = _store()
    _row(conn, "match", MATCH, 100.0)
    _row(conn, "unrelated", UNRELATED, 101.0)          # newer, same topic, no overlap
    _row(conn, "other_topic", MATCH, 102.0, topic="web")  # newest, matching text, other topic
    rows = _kernel(conn)._der_recall_neighborhood(_item(), "sess")
    assert _ids(rows) == ["match"]
    block = _der_neighbors_block(rows)
    assert "match" in block and "billing" in block
    assert "unrelated" not in block and "weather" not in block


def test_step_with_no_passing_row_gets_no_block():
    conn = _store()
    for i in range(6):
        _row(conn, f"u{i}", UNRELATED + f" {i}", 100.0 + i)
    k = _kernel(conn)
    rows = k._der_recall_neighborhood(_item(), "sess")
    assert rows == []
    assert _der_neighbors_block(rows) == ""
    # An empty store and an empty goal are also "nothing", never an error.
    assert _kernel(_store())._der_recall_neighborhood(_item(), "sess") == []
    assert k._der_recall_neighborhood(_item(goal=""), "sess") == []


def test_one_shared_word_is_not_relevance():
    conn = _store()
    _row(conn, "weak", "read the billing invoice template", 100.0)  # shares only "billing"
    assert _kernel(conn)._der_recall_neighborhood(_item(), "sess") == []


def test_gate_finds_an_older_match_beyond_the_recent_three():
    """The candidate pool is wider than 3; what the step CARRIES is still <= 3."""
    conn = _store()
    _row(conn, "old_match", MATCH, 1.0)
    for i in range(10):
        _row(conn, f"noise{i}", UNRELATED + f" {i}", 100.0 + i)
    rows = _kernel(conn)._der_recall_neighborhood(_item(), "sess")
    assert _ids(rows) == ["old_match"]


def test_survivors_rank_by_state_proximity_then_recency():
    conn = _store()
    _row(conn, "far_new", MATCH, 300.0, coords="9.00,9.00,9.00,9.00")
    _row(conn, "near_old", MATCH, 100.0, coords="1.00,0.00,1.00,0.00")
    _row(conn, "near_new", MATCH, 200.0, coords="1.00,0.00,1.00,0.00")
    _row(conn, "nocoord_newest", MATCH, 400.0)
    with mock.patch("backend.agent.caducean_trajectory.latest_coords_str",
                    return_value="1.00,0.00,1.00,0.00"):
        rows = _kernel(conn)._der_recall_neighborhood(_item(), "sess")
    # keep is 3: proximity first (equal distance -> newer first), unknown position last.
    assert _ids(rows) == ["near_new", "near_old", "far_new"]


def test_keeps_at_most_three_rows():
    conn = _store()
    for i in range(8):
        _row(conn, f"m{i}", MATCH, 100.0 + i)
    assert len(_kernel(conn)._der_recall_neighborhood(_item(), "sess")) == 3


def test_chain_recall_log_line(caplog):
    conn = _store()
    _row(conn, "match", MATCH, 100.0)
    _row(conn, "unrelated", UNRELATED, 101.0)
    with caplog.at_level(logging.INFO, logger="backend.agent.ontology_recall"):
        _kernel(conn)._der_recall_neighborhood(_item(), "sess")
    lines = [r.getMessage() for r in caplog.records if "[chain_recall]" in r.getMessage()]
    assert len(lines) == 1, lines
    assert lines[0].startswith("[chain_recall] cand=2 kept=1 ms="), lines[0]


def test_rows_injected_per_step_before_and_after(capsys):
    """Measured: a store full of recent same-topic rows about OTHER work.

    Before (recency + topic only, limit 3) every step carried 3 rows whatever
    they said; after, a step with nothing relevant carries 0 and a step with one
    relevant row carries exactly that one.
    """
    conn = _store()
    for i in range(12):
        _row(conn, f"other{i}", UNRELATED + f" {i}", 100.0 + i)
    _row(conn, "match", MATCH, 50.0)  # oldest: recency alone never reaches it
    k = _kernel(conn)

    def before(goal):
        f = RecallFilters(node_type="step", topic_domain="coding",
                          execution_domain="der", limit=3)
        return run_filtered_recall(conn, f)

    goals = [GOAL, "rename the settings panel header", "write release notes draft"]
    b = [len(before(g)) for g in goals]
    a = [len(k._der_recall_neighborhood(_item(goal=g), "sess")) for g in goals]
    with capsys.disabled():
        print(f"\n[K2 measured] rows injected per step before={b} after={a}")
    assert b == [3, 3, 3]
    assert a == [1, 0, 0]

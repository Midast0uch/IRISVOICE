"""CT-ON3 — REQ-20 (T21): ontology-aware recall with widen-order.

Drives the REAL ``backend.agent.ontology_recall`` against an in-memory
SQLite store carrying the typed memory_chain schema (node_type,
topic_domain, execution_domain) plus a mycelium_pin_links table for the
relationship filters.

Pinned contracts:
  - AC1  : filters (node_type + both domain axes + relationship) applied to
           chain recall.
  - AC1b : cross-conversation by default — thread_id RANKS, never filters.
           Rows from other sessions/threads are candidates.
  - AC2  : zero-hit -> widen ONE level at a time (relationship -> type ->
           domain); the winning scope is returned and logged, never silent.
  - AC2b : age is a ranking input, not a cutoff — an old surviving row is
           reachable; recency never hides it.
  - AC3  : the filtered neighborhood is surfaced as RELEVANT NEIGHBORS in
           the step context (verified at the kernel wiring level).
  - Edge : unknown relationship value -> treated as no relationship (widen).
"""

import sqlite3

import pytest

from backend.agent.ontology_recall import (
    RecallFilters,
    SCOPE_ALL,
    SCOPE_ALL_FILTERS,
    SCOPE_NO_RELATIONSHIP,
    SCOPE_NO_TYPE,
    filtered_chain_recall,
    recall_failed_like,
)


# ── shared store helper: typed memory_chain + link store ────────────────


def _make_store() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE memory_chain ("
        " chain_id TEXT PRIMARY KEY, thread_id TEXT, result TEXT, "
        " node_type TEXT, topic_domain TEXT, execution_domain TEXT, "
        " insight TEXT, created_at REAL, rowid INTEGER)"
    )
    conn.execute(
        "CREATE TABLE mycelium_pin_links ("
        " source_id TEXT, target_id TEXT, relationship TEXT, created_at REAL)"
    )
    return conn


def _seed(conn, chain_id, thread="t1", result="r", node_type="step",
          topic_domain="web", execution_domain="der", created_at=1000.0):
    conn.execute(
        "INSERT INTO memory_chain (chain_id, thread_id, result, node_type, "
        " topic_domain, execution_domain, insight, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, '', ?)",
        (chain_id, thread, result, node_type, topic_domain, execution_domain,
         created_at),
    )


def _seed_link(conn, source, target, relationship, created_at=2000.0):
    conn.execute(
        "INSERT INTO mycelium_pin_links (source_id, target_id, relationship, "
        " created_at) VALUES (?, ?, ?, ?)",
        (source, target, relationship, created_at),
    )


# ── AC1: filters apply to chain recall ──────────────────────────────────


def test_typed_domain_filter_narrows_to_neighborhood():
    conn = _make_store()
    _seed(conn, "n1", node_type="step", topic_domain="web", execution_domain="der")
    _seed(conn, "n2", node_type="task", topic_domain="ai", execution_domain="research")
    _seed(conn, "n3", node_type="step", topic_domain="web", execution_domain="der")

    rows, scope = filtered_chain_recall(
        conn, RecallFilters(node_type="step", topic_domain="web",
                            execution_domain="der", limit=10)
    )
    ids = {r["chain_id"] for r in rows}
    assert ids == {"n1", "n3"}  # only the web/der steps — not the ai task
    assert scope == SCOPE_ALL_FILTERS


def test_type_filter_excludes_other_types():
    conn = _make_store()
    _seed(conn, "task1", node_type="task")
    _seed(conn, "step1", node_type="step")
    rows, _ = filtered_chain_recall(
        conn, RecallFilters(node_type="task", limit=10)
    )
    assert {r["chain_id"] for r in rows} == {"task1"}


# ── AC2: zero-hit widens relationship -> type -> domain, logged ─────────


def test_zero_hit_drops_relationship_then_type_then_domain(caplog):
    conn = _make_store()
    # only a task node in ai/research exists — nothing matches a web/der step
    _seed(conn, "only", node_type="task", topic_domain="ai",
          execution_domain="research")
    _seed_link(conn, "node:x", "node:only", "failed_like")

    with caplog.at_level("INFO", logger="backend.agent.ontology_recall"):
        rows, scope = filtered_chain_recall(
            conn, RecallFilters(node_type="step", topic_domain="web",
                                execution_domain="der", limit=10)
        )
    # winning scope is the widest that answered: unfiltered-all
    assert scope == SCOPE_ALL
    assert {r["chain_id"] for r in rows} == {"only"}
    # the widen was LOGGED, not silent (AC2)
    logs = " ".join(r.message for r in caplog.records)
    assert "widened" in logs


def test_relationship_zero_hit_widens_to_type_domains(caplog):
    conn = _make_store()
    # a web/der step exists, but NO failed_like links exist for it
    _seed(conn, "stepA", node_type="step", topic_domain="web",
          execution_domain="der")

    with caplog.at_level("INFO", logger="backend.agent.ontology_recall"):
        rows, scope = filtered_chain_recall(
            conn, RecallFilters(relationship="failed_like", node_type="step",
                                topic_domain="web", execution_domain="der",
                                limit=10)
        )
    # relationship dropped -> the web/der step itself answers
    assert scope == SCOPE_NO_RELATIONSHIP
    assert {r["chain_id"] for r in rows} == {"stepA"}


def test_type_zero_hit_widens_to_domain(caplog):
    conn = _make_store()
    _seed(conn, "taskA", node_type="task", topic_domain="web",
          execution_domain="der")

    with caplog.at_level("INFO", logger="backend.agent.ontology_recall"):
        rows, scope = filtered_chain_recall(
            conn, RecallFilters(node_type="step", topic_domain="web",
                                execution_domain="der", limit=10)
        )
    # type dropped -> the web/der task answers under domain scope
    assert scope == SCOPE_NO_TYPE
    assert {r["chain_id"] for r in rows} == {"taskA"}


def test_relationship_filter_via_link_store_walk():
    conn = _make_store()
    _seed(conn, "fail1", node_type="step")
    _seed(conn, "fail2", node_type="step")
    _seed(conn, "ok", node_type="step")
    _seed_link(conn, "node:new", "node:fail1", "failed_like")
    _seed_link(conn, "node:new", "node:fail2", "failed_like")

    # relationship filter = nodes linked failed_like to a node (AVOID walk)
    rows, scope = filtered_chain_recall(
        conn, RecallFilters(relationship="failed_like", limit=10)
    )
    assert scope == SCOPE_ALL_FILTERS
    ids = {r["chain_id"] for r in rows}
    # fail1/fail2 are targets of failed_like links; 'ok' has no link
    assert ids == {"fail1", "fail2"}


# ── AC2 edge: unknown relationship -> widen, never error ────────────────


def test_unknown_relationship_treated_as_no_relationship(caplog):
    conn = _make_store()
    _seed(conn, "n1", node_type="step", topic_domain="web")
    with caplog.at_level("INFO", logger="backend.agent.ontology_recall"):
        rows, scope = filtered_chain_recall(
            conn, RecallFilters(relationship="totally_bogus",
                                node_type="step", topic_domain="web",
                                limit=10)
        )
    # widened to type+domains; n1 answers; scope reports the winner
    assert scope in (SCOPE_ALL_FILTERS, SCOPE_NO_RELATIONSHIP, SCOPE_NO_TYPE,
                     SCOPE_ALL)
    assert {r["chain_id"] for r in rows} == {"n1"}


# ── AC1b: cross-conversation by default ─────────────────────────────────


def test_thread_id_ranks_never_filters():
    conn = _make_store()
    # same topic/type, DIFFERENT thread — must still be a candidate (AC1b)
    _seed(conn, "other-session", thread="session-42", node_type="step",
          topic_domain="web", execution_domain="der", created_at=500.0)
    _seed(conn, "this-session", thread="session-7", node_type="step",
          topic_domain="web", execution_domain="der", created_at=900.0)

    rows, _ = filtered_chain_recall(
        conn, RecallFilters(node_type="step", topic_domain="web",
                            execution_domain="der",
                            thread_id="session-7", limit=10)
    )
    ids = {r["chain_id"] for r in rows}
    assert "other-session" in ids  # older session is NOT hidden
    assert "this-session" in ids
    # recency ranks: this-session (created 900) sorts before other-session (500)
    assert rows[0]["chain_id"] == "this-session"


# ── AC2b: age ranks, never a cutoff ─────────────────────────────────────


def test_old_surviving_row_reachable():
    conn = _make_store()
    _seed(conn, "ancient", node_type="step", topic_domain="web",
          execution_domain="der", created_at=1.0)   # very old
    _seed(conn, "fresh", node_type="step", topic_domain="web",
          execution_domain="der", created_at=9999.0)

    rows, _ = filtered_chain_recall(
        conn, RecallFilters(node_type="step", topic_domain="web",
                            execution_domain="der", limit=10)
    )
    ids = {r["chain_id"] for r in rows}
    assert "ancient" in ids  # old but surviving decay -> reachable
    assert rows[0]["chain_id"] == "fresh"  # recency ranks, doesn't cut


# ── failed_like graph walk (REQ-19 AC3 / REQ-20 AVOID) ──────────────────


def test_recall_failed_like_walk():
    conn = _make_store()
    _seed_link(conn, "node:current", "node:prior1", "failed_like", created_at=100.0)
    _seed_link(conn, "node:current", "node:prior2", "failed_like", created_at=200.0)
    _seed_link(conn, "node:current", "node:ok", "depends_on", created_at=300.0)

    prior = recall_failed_like(conn, "current")
    ids = {p["node_id"] for p in prior}
    assert ids == {"node:prior1", "node:prior2"}
    assert "node:ok" not in ids  # depends_on is not failed_like


def test_recall_failed_like_empty_store_no_error():
    conn = _make_store()
    assert recall_failed_like(conn, "missing") == []


# ── edge: empty store / no filters preserves all-scope behavior ─────────


def test_no_filters_returns_all_scope():
    conn = _make_store()
    _seed(conn, "a", node_type="task")
    _seed(conn, "b", node_type="step")
    rows, scope = filtered_chain_recall(conn, RecallFilters(limit=10))
    assert {r["chain_id"] for r in rows} == {"a", "b"}
    assert scope == SCOPE_ALL


def test_filter_over_empty_memory_widens_to_empty_all(caplog):
    conn = _make_store()
    with caplog.at_level("INFO", logger="backend.agent.ontology_recall"):
        rows, scope = filtered_chain_recall(
            conn, RecallFilters(node_type="step", topic_domain="web", limit=10)
        )
    assert rows == []
    assert scope == SCOPE_ALL

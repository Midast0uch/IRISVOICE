"""DER links in the shared link store are session-scoped, written once, and bounded.

Measured 2026-11-22 on the live app store: `mycelium_pin_links` held 56,325 rows,
none from a pin, on 48 targets, with only 301 distinct (source, target, relationship)
links - one DER link 9,029 times. Two causes:

  1. `der_links._node_id(step)` was `node:<step>` with PLAN-LOCAL step ids (s1, s2):
     every plan's s1 was one node, so AVOID recall (`recall_failed_like`) and the
     lineage walk mixed unrelated tasks.
  2. `PinStore.link` inserted every call, so the same link was written again on
     every run, with no budget (1,352-3,285 rows a day).

Each test FAILS on the code before this change.
"""
from __future__ import annotations

from backend.agent import der_links
from backend.agent.der_links import DerLinkWriter
from backend.agent.ontology_recall import recall_failed_like
from backend.memory.pin_store import PinStore
from backend.tests.contract.test_der_t20_link_store_contract import _FakeItem, _fresh_writer
from backend.agent.der_loop import NodeRecord


def _rows(conn, where=""):
    return conn.execute("SELECT source_id, target_id, relationship FROM mycelium_pin_links "
                        + where).fetchall()


def test_the_same_step_in_two_sessions_is_two_nodes():
    conn, w = _fresh_writer()
    for sess in ("conv-a", "conv-b"):
        w.write_node_links(_FakeItem("s2", depends_on=["s1"]), NodeRecord(step_id="s2", parent_step_id=""),
                           step_success=True, session_id=sess)
    assert set(_rows(conn)) == {("node:conv-a:s2", "node:conv-a:s1", "depends_on"),
                                ("node:conv-b:s2", "node:conv-b:s1", "depends_on")}


def test_avoid_recall_stays_in_its_own_node():
    conn, w = _fresh_writer()
    w.record_failure_class("conv-a", "s1", "permanent")
    w.link_failed_like("conv-b", "s1", "permanent")     # conv-b's s1 failed like conv-a's s1
    w.record_failure_class("conv-c", "s9", "transient")
    assert recall_failed_like(conn, "s1", session_id="conv-b") == [{"node_id": "node:conv-a:s1"}]
    assert recall_failed_like(conn, "s1", session_id="conv-x") == []   # another plan's s1


def test_a_link_that_exists_is_not_written_again():
    conn, _ = _fresh_writer()
    ps = PinStore(conn=conn)
    for _ in range(5):
        ps.link("node:conv-a:s2", "node:conv-a:s1", relationship="depends_on",
                source_type="node", target_type="node")
    assert len(_rows(conn)) == 1


def test_der_links_have_a_budget_and_pins_are_never_pruned(monkeypatch):
    monkeypatch.setattr(der_links, "DER_LINKS_MAX_ROWS", 10)
    monkeypatch.setattr(der_links, "DER_LINKS_PRUNE_EVERY", 5)
    conn, w = _fresh_writer()
    PinStore(conn=conn).link("pin_1", "node:x", relationship="relevant_to",
                             source_type="pin", target_type="node")
    for i in range(40):   # 40 runs, one depends_on link each
        w.write_node_links(_FakeItem("s2", depends_on=["s1"]), NodeRecord(step_id="s2", parent_step_id=""),
                           step_success=True, session_id=f"conv-{i}")
    node_rows = _rows(conn, "WHERE source_type = 'node'")
    assert len(node_rows) <= 10, len(node_rows)
    assert ("node:conv-39:s2", "node:conv-39:s1", "depends_on") in node_rows   # the newest stay
    assert _rows(conn, "WHERE source_type = 'pin'") == [("pin_1", "node:x", "relevant_to")]


def _schema_store():
    import sqlite3
    from backend.memory.db import initialise_mycelium_schema

    conn = sqlite3.connect(":memory:")
    initialise_mycelium_schema(conn)
    return conn


_RAW = ("INSERT INTO mycelium_pin_links (source_type, source_id, target_type, target_id, "
        "relationship, weight, created_at) VALUES ('node', 'node:c:s2', 'node', 'node:c:s1', "
        "'depends_on', 1.0, 1.0)")


def test_the_store_refuses_a_copy_from_any_writer():
    """The schema's unique index: a raw INSERT of an existing link fails, whoever writes it."""
    import sqlite3

    import pytest

    conn = _schema_store()
    conn.execute(_RAW)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(_RAW)


def test_the_cleanup_removes_copies_and_builds_the_index():
    import sqlite3

    import pytest

    conn = _schema_store()
    conn.execute("DROP INDEX idx_pin_links_unique")    # an old store, before the index
    for _ in range(4):
        conn.execute(_RAW)
    conn.commit()
    out = PinStore(conn=conn).remove_duplicate_links(dry_run=False)
    assert out == {"rows": 4, "distinct": 1, "removed": 3, "unique_index": True}
    assert len(_rows(conn)) == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(_RAW)
    assert PinStore(conn=conn).remove_duplicate_links(dry_run=True)["removed"] == 0

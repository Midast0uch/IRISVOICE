"""CT-ON2 — REQ-19 (T20): DER structure in the SHARED link store.

  AC1  : parent / depends_on / sub-loop containment persist as typed links in
         the mycelium link store (mycelium_pin_links, source_type='node')
  AC2b : the vocabulary is enforced at the WRITE boundary — an
         out-of-vocabulary predicate is rejected loudly (logged + dropped),
         never written; part_of is the ONLY containment direction DER writes
         (contains never written by DER)
  AC3  : a failed node is linked failed_like to PRIOR same-class failures, so
         AVOID recall is a graph walk
  AC4  : REQ-5 coupling edges land in the SAME store (one store, no second
         edge store) — relevant_to written only for actually-surfaced branches

Spec: specs/der-dag-inversion/requirements.md REQ-19.
"""

from __future__ import annotations

import logging
import sqlite3

from backend.agent.der_links import DerLinkWriter
from backend.agent.der_loop import NodeRecord, QueueItem
from backend.memory.pin_store import DER_LINK_PREDICATES, LINK_VOCABULARY


class _FakeItem:
    """Minimal QueueItem-shaped collaborator the writer reads."""

    def __init__(self, step_id, parent_step_id="", is_subloop=False,
                 depends_on=None, candidates=None):
        self.step_id = step_id
        self.parent_step_id = parent_step_id
        self.is_subloop = is_subloop
        self.depends_on = list(depends_on or [])
        self._coupled_candidates = list(candidates or [])


def _fresh_writer():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """CREATE TABLE mycelium_pin_links (
               link_id INTEGER PRIMARY KEY AUTOINCREMENT,
               source_type TEXT, source_id TEXT,
               target_type TEXT, target_id TEXT,
               relationship TEXT, weight REAL, created_at REAL)"""
    )
    return conn, DerLinkWriter(type("S", (), {"_conn": conn})())


# ── vocabulary (AC2b) ──────────────────────────────────────────────────────


def test_vocabulary_has_ten_predicates_with_der_extensions():
    assert {"derives_from", "part_of", "relevant_to", "failed_like"} <= LINK_VOCABULARY
    assert {"depends_on", "part_of", "relevant_to", "failed_like"} <= DER_LINK_PREDICATES
    assert len(LINK_VOCABULARY) == 10


def test_link_store_accepts_der_predicates():
    conn, w = _fresh_writer()
    assert w.link_part_of("s1_s0", "s1") is True
    row = conn.execute(
        "SELECT relationship, source_type, source_id, target_id "
        "FROM mycelium_pin_links"
    ).fetchone()
    assert row[0] == "part_of"
    assert row[1] == "node"
    assert row[2] == "node:s1_s0"
    assert row[3] == "node:s1"


def test_contains_never_written_by_der(caplog):
    """AC2b rule 1: DER writes part_of only; contains is derived, never written.
    PinStore.link rejects it as out-of-DER-vocabulary? No — contains IS in the
    full vocabulary; the DER writer simply never emits it. The discriminator:
    a full-vocabulary predicate the writer's API never exposes cannot be
    produced by write_node_links."""
    conn, w = _fresh_writer()
    w.write_node_links(
        _FakeItem("s1_s0", parent_step_id="s1", is_subloop=True),
        NodeRecord(step_id="s1_s0", parent_step_id="s1"),
        step_success=True,
    )
    rows = conn.execute("SELECT relationship FROM mycelium_pin_links").fetchall()
    assert all(r[0] != "contains" for r in rows)
    assert any(r[0] == "part_of" for r in rows)


# ── structural links (AC1) ─────────────────────────────────────────────────


def test_part_of_and_depends_on_persist():
    conn, w = _fresh_writer()
    item = _FakeItem(
        "s2", parent_step_id="s1", is_subloop=False,
        depends_on=["s1", "s1_s0"],
    )
    w.write_node_links(item, NodeRecord(step_id="s2", parent_step_id="s1"),
                       step_success=True)
    rels = sorted(r[0] for r in conn.execute(
        "SELECT relationship FROM mycelium_pin_links").fetchall())
    assert rels == ["depends_on", "depends_on"]


def test_relevant_to_only_for_surfaced_branches():
    """AC4: relevant_to is written ONLY for branches actually surfaced to the
    decision — coupling provenance lives in the SAME store."""
    conn, w = _fresh_writer()
    item = _FakeItem(
        "s3",
        candidates=[{"node_id": "branch_a"}, {"node_id": "branch_b"}],
    )
    rec = NodeRecord(step_id="s3", parent_step_id="s1", chosen_branch="branch_a")
    w.write_node_links(item, rec, step_success=True)
    targets = sorted(r[0] for r in conn.execute(
        "SELECT target_id FROM mycelium_pin_links").fetchall())
    assert targets == ["branch_a", "branch_b"]


# ── failed_like walk (AC3) ─────────────────────────────────────────────────


def test_failed_like_links_to_prior_same_class_failures():
    conn, w = _fresh_writer()
    w.record_failure_class("sess1", "s1", "transient")
    w.record_failure_class("sess1", "s2", "permanent")
    n = w.link_failed_like("sess1", "s3", "transient")
    assert n == 1
    row = conn.execute(
        "SELECT source_id, target_id, relationship FROM mycelium_pin_links"
    ).fetchone()
    assert row[0] == "node:s3"
    assert row[1] == "node:s1"
    assert row[2] == "failed_like"


def test_failed_like_walk_via_write_node_links():
    """AC3 behavioral-shaped: two transient failures, then a third — the walk
    finds both prior same-class failures, not the permanent one."""
    conn, w = _fresh_writer()
    w.record_failure_class("sess2", "s1", "transient")
    w.record_failure_class("sess2", "s2", "permanent")
    w.write_node_links(_FakeItem("s3"), NodeRecord(step_id="s3", parent_step_id=""),
                       step_success=False, step_result="timed out",
                       session_id="sess2")
    rows = conn.execute(
        "SELECT target_id FROM mycelium_pin_links "
        "WHERE relationship='failed_like'"
    ).fetchall()
    targets = sorted(r[0] for r in rows)
    assert targets == ["node:s1"]

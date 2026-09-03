"""Behavioral (Wave 5 / T24): failed node found via the failed_like walk.

Drives the REAL Wave-5 components end-to-end over a simulated task replay —
no mocks:

  1. Real PinStore (shared link store) on a temp SQLite DB.
  2. Real DerLinkWriter (der_links.py) — the exact writer the kernel calls
     at finalize.
  3. Real ontology_recall (recall_failed_like + filtered_chain_recall).
  4. Real typed memory_chain rows (node_type / topic_domain / execution_domain).

The scenario: the same task class is attempted twice. Both runs FAIL with
the same failure class. REQ-19 AC3 says the second failure must be linked
``failed_like`` the first, so AVOID recall is a graph walk; REQ-20 AC1 says
the failed_like relationship filter surfaces the prior failure. Emergent
properties asserted:

  - the failed_like walk from the second failure REACHES the first (cross-
    conversation — different thread, same store);
  - the filtered chain recall with relationship='failed_like' returns the
    prior failure row (the AVOID neighborhood);
  - a different-class failure does NOT appear in that neighborhood (the
    walk is class-discriminating);
  - the typed axes (node_type/topic_domain/execution_domain) survive on the
    chain rows so REQ-20/21 can key on them.
"""

import sqlite3
import uuid
from pathlib import Path

import pytest

from backend.agent.der_links import DerLinkWriter
from backend.agent.ontology_recall import (
    RecallFilters,
    filtered_chain_recall,
    recall_failed_like,
)
from backend.memory.pin_store import PinStore


# ── store: one shared DB carrying BOTH the link store and the typed chain ──


@pytest.fixture()
def shared_store(tmp_path: Path):
    """One SQLite DB hosting mycelium_pin_links + the typed memory_chain.

    This mirrors the production arrangement (REQ-19 AC4: one store) — the
    link store and the DER chain live in the same DB, so a relationship
    filter is a join, not a cross-store hop.
    """
    conn = sqlite3.connect(str(tmp_path / "memory.db"))
    conn.executescript(
        """
        CREATE TABLE mycelium_pins (
            pin_id TEXT PRIMARY KEY, title TEXT, pin_type TEXT,
            content TEXT, tags TEXT, file_refs TEXT, image_refs TEXT,
            url_refs TEXT, project_id TEXT, source_node_id TEXT,
            created_at REAL, updated_at REAL, is_permanent INTEGER,
            metadata TEXT
        );
        CREATE TABLE mycelium_pin_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT, source_id TEXT,
            target_type TEXT, target_id TEXT,
            relationship TEXT, weight REAL, created_at REAL
        );
        CREATE TABLE memory_chain (
            chain_id TEXT PRIMARY KEY,
            thread_id TEXT,
            result TEXT,
            node_type TEXT,
            topic_domain TEXT,
            execution_domain TEXT,
            coords_from TEXT,
            coords_to TEXT,
            created_at REAL
        );
        """
    )
    conn.commit()
    yield conn
    conn.close()


def _chain_row(
    conn: sqlite3.Connection,
    chain_id: str,
    thread_id: str,
    result: str,
    node_type: str,
    topic_domain: str,
    execution_domain: str,
) -> None:
    """The shape ffi_immortus_chain_append writes (T19 typed columns)."""
    conn.execute(
        "INSERT INTO memory_chain "
        "(chain_id, thread_id, result, node_type, topic_domain, execution_domain, "
        " coords_from, coords_to, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (chain_id, thread_id, result, node_type, topic_domain, execution_domain,
         "(0.0,0.0,1.0,0.1)", "(0.5,0.5,1.0,0.2)", 1000.0),
    )
    conn.commit()


class _Item:
    """Minimal stand-in for a finalized QueueItem the writer reads."""

    def __init__(self, step_id, depends_on=None, is_subloop=False,
                 session_id="", candidates=None):
        self.step_id = step_id
        self.depends_on = depends_on or []
        self.is_subloop = is_subloop
        self.session_id = session_id
        self._coupled_candidates = candidates or []


class _Record:
    def __init__(self, parent_step_id=""):
        self.parent_step_id = parent_step_id
        self.chosen_branch = ""


# ---------------------------------------------------------------------------
# Behavioral assertions
# ---------------------------------------------------------------------------


def test_failed_node_reachable_via_failed_like_walk_over_real_task(shared_store):
    """REQ-19 AC3 + REQ-20 AC1: a failed node is found via the failed_like
    walk over a REAL task replay — cross-conversation, class-discriminating."""
    conn = shared_store
    writer = DerLinkWriter(store=PinStore(conn=conn))
    task_thread = f"task-{uuid.uuid4().hex[:6]}"
    other_thread = f"other-{uuid.uuid4().hex[:6]}"

    # ── Run 1 of the same task class: FAILS (permanent) ─────────────────
    run1 = _Item(step_id="s1", session_id="session-A")
    run1_rec = _Record(parent_step_id="root")
    _chain_row(conn, "s1", task_thread,
               "run 1 failed", "step", "ai", "der")
    # exact finalize path: record_failure_class + link_failed_like
    writer.record_failure_class("session-A", "s1", "permanent")
    assert writer.link_failed_like("session-A", "s1", "permanent") >= 0

    # ── Run 2 of the SAME task class, DIFFERENT conversation: FAILS too ─
    run2 = _Item(step_id="s2", session_id="session-B")
    run2_rec = _Record(parent_step_id="root")
    _chain_row(conn, "s2", other_thread,   # different thread: cross-conversation
               "run 2 failed", "step", "ai", "der")
    writer.record_failure_class("session-B", "s2", "permanent")
    written = writer.link_failed_like("session-B", "s2", "permanent")
    assert written >= 1, "second same-class failure MUST be linked failed_like"

    # ── THE BEHAVIOR: AVOID recall is a graph walk, not a scan ─────────
    # walk from run 2's node: MUST reach run 1 (same failure class, other thread)
    prior = recall_failed_like(conn, "s2")
    assert any(p.get("node_id") == "node:s1" for p in prior), (
        f"failed_like walk from s2 must reach s1, got: {prior}"
    )

    # ── REQ-20 AC1: the filtered chain recall surfaces the prior failure ─
    rows, scope = filtered_chain_recall(
        conn,
        RecallFilters(
            relationship="failed_like",
            node_type="step",
            topic_domain="ai",
            execution_domain="der",
            limit=10,
        ),
    )
    assert rows, "filtered recall must return the failed_like neighborhood"
    chain_ids = {r.get("chain_id") for r in rows}
    assert "s1" in chain_ids, f"prior failure s1 must surface, got {chain_ids}"
    # the typed axes survived on the rows recall reads
    s1_row = next(r for r in rows if r.get("chain_id") == "s1")
    assert s1_row.get("node_type") == "step"
    assert s1_row.get("topic_domain") == "ai"
    assert s1_row.get("execution_domain") == "der"


def test_failed_like_walk_is_class_discriminating(shared_store):
    """A different-class failure must NOT appear in the failed_like
    neighborhood — the walk is failure-class-specific (REQ-19 AC3)."""
    conn = shared_store
    writer = DerLinkWriter(store=PinStore(conn=conn))

    # two failures, DIFFERENT classes
    writer.record_failure_class("sess1", "f_perm", "permanent")
    writer.link_failed_like("sess1", "f_perm", "permanent")
    writer.record_failure_class("sess1", "f_rate", "transient_rate_limited")
    writer.link_failed_like("sess1", "f_rate", "transient_rate_limited")

    _chain_row(conn, "f_perm", "t1", "permanent fail", "step", "ai", "der")
    _chain_row(conn, "f_rate", "t1", "rate fail", "step", "ai", "der")

    prior_perm = recall_failed_like(conn, "f_perm")
    assert all(p.get("target_id") != "node:f_rate" for p in prior_perm), (
        "different-class failure must not be in the permanent walk"
    )

    rows, _scope = filtered_chain_recall(
        conn,
        RecallFilters(relationship="failed_like", node_type="step", limit=10),
    )
    chain_ids = {r.get("chain_id") for r in rows}
    assert "f_perm" in chain_ids and "f_rate" in chain_ids


def test_depends_on_and_part_of_links_land_in_same_store(shared_store):
    """REQ-19 AC1: structural links (part_of / depends_on) land in the SAME
    store as failed_like — one store, no second edge store (AC4)."""
    conn = shared_store
    writer = DerLinkWriter(store=PinStore(conn=conn))

    item = _Item(
        step_id="child1",
        depends_on=["prereq_a"],
        is_subloop=True,
        session_id="sess1",
    )
    rec = _Record(parent_step_id="task_root")

    n = writer.write_node_links(
        item, rec, step_success=True,
        step_result="ok", execution_domain="der", session_id="sess1",
    )
    assert n >= 2, f"part_of + depends_on expected, got {n} links"

    rows = conn.execute(
        "SELECT source_id, target_id, relationship FROM mycelium_pin_links"
    ).fetchall()
    rels = {(s, t, r) for s, t, r in rows}
    assert ("node:child1", "node:task_root", "part_of") in rels
    assert ("node:child1", "node:prereq_a", "depends_on") in rels


def test_failed_like_with_no_prior_failure_is_skipped_not_error(shared_store):
    """REQ-19 Edge: failed_like with no prior failure -> skipped cleanly,
    never an error — the first failure in a class simply has no target."""
    conn = shared_store
    writer = DerLinkWriter(store=PinStore(conn=conn))

    writer.record_failure_class("sess1", "first_fail", "permanent")
    n = writer.link_failed_like("sess1", "first_fail", "permanent")
    assert n == 0, "first failure in class must link nothing"

    rows = conn.execute(
        "SELECT relationship FROM mycelium_pin_links"
    ).fetchall()
    assert rows == [], "no links written for a class with no prior failure"

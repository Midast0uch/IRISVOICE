"""Side-lane reads never hold the answer path (2026-10-04).

Live c03: the answer path's recall read (resonance._load_session_nodes_by_space)
sat 4+ s on the SHARED mycelium connection while the memory lane ran
_attribute_recalls on it - a LIKE over the whole memory_events table (the query
named only `label`, so the (family, label) index was unusable). A connection
runs one statement at a time; on cold pages that scan took seconds.

Contract:
  1. the recall-trace query uses the (family, label) index - no table SCAN;
  2. a side lane reads on its OWN connection to the store file (one per
     thread, reused), never the shared one; a connection without a store path
     (tests, other files) is used as is.
"""
from __future__ import annotations

import sqlite3
import threading

from backend.memory import db as memdb
from backend.memory import memory_events as me


def test_the_recall_trace_query_uses_the_label_index():
    conn = sqlite3.connect(":memory:")
    for stmt in me._SCHEMA.split(";"):
        if stmt.strip():
            conn.execute(stmt)
    plan = " | ".join(r[3] for r in conn.execute(
        "EXPLAIN QUERY PLAN " + me._RECALL_DONE_SQL, ("%rt-x%",)))
    assert "SCAN memory_events" not in plan, plan
    assert "idx_memory_events_label" in plan, plan


def test_a_side_lane_reads_on_its_own_connection(tmp_path):
    path = tmp_path / "memory.db"
    seed = sqlite3.connect(path)
    seed.execute("PRAGMA journal_mode=WAL")
    seed.execute("CREATE TABLE t (x INTEGER)")
    seed.commit()
    seed.close()
    shared = memdb.open_encrypted_memory(str(path), b"")
    assert getattr(shared, "store_path", "")
    seen = {}

    def lane():
        a = memdb.lane_connection(shared)
        seen["a"], seen["b"] = a, memdb.lane_connection(shared)
        seen["rows"] = a.execute("SELECT count(*) FROM t").fetchone()[0]

    t = threading.Thread(target=lane)
    t.start()
    t.join(10)
    assert seen["a"] is not shared, "the lane read on the shared connection"
    assert seen["a"] is seen["b"], "one connection per thread, reused"
    assert seen["rows"] == 0
    plain = sqlite3.connect(":memory:")
    assert memdb.lane_connection(plain) is plain

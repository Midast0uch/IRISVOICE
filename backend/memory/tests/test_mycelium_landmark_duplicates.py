"""Guard (2026-10-19, W9 task A): duplicate landmarks.

What was wrong (live store, read-only): 91 non-absorbed landmarks held only 7
distinct clusters over 15 nodes; two hardware nodes sat in 83 of them, one
6-node cluster in 45 and one 2-node cluster in 24. Identical clusters have
Jaccard 1.0, yet they were never merged. Two causes, traced in the live rows:

  1. LandmarkMerger.try_merge absorbed ONE candidate per crystallization. A
     group of k identical landmarks (a backlog from before merges worked) lost
     one member to each new arrival and gained the arrival, so it stayed at k for
     ever (the 7 eval landmarks of 2026-10-18 each carry one merge and still
     share one cluster).
  2. LandmarkCondenser.condense drew the cluster from ALL nodes of the graph,
     top 6 by access_count - not from the session's nodes - so every session got
     the same few always-present nodes (every live traversal_sequence equals its
     cluster and equals its neighbours').

Plus: landmarks_in_region broke ties by landmark_id, and the merge log key was
``mrg_<seconds>`` so a second merge in the same second hit the primary key.
Each guard below FAILS on the code before this change.
"""
import json
import time
import types
import uuid

import pytest

from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium import profile as profile_mod
from backend.memory.mycelium.interface import MyceliumInterface
from backend.memory.mycelium.landmark import Landmark, LandmarkIndex
from backend.memory.mycelium.profile import LandmarkMerger


def _cluster(node_ids, access=3):
    return [{"node_id": n, "space_id": "domain", "coordinates": [0.1, 0.5, 1.0],
             "confidence": 0.5, "access_count": access} for n in node_ids]


def _raw_landmark(conn, node_ids, *, score=0.8, created=None, lid=None):
    lid = lid or "lm_" + uuid.uuid4().hex[:8]
    conn.execute(
        "INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster,"
        " traversal_sequence, cumulative_score, activation_count, is_permanent, created_at)"
        " VALUES (?, 'lm', 'code_task', ?, '[]', ?, 0, 0, ?)",
        (lid, json.dumps(_cluster(node_ids)), score, created or time.time()),
    )
    conn.commit()
    return lid


def _new_landmark(node_ids, score=0.8):
    return Landmark(
        landmark_id="lm_" + uuid.uuid4().hex[:8], label="a new task", task_class="code_task",
        coordinate_cluster=_cluster(node_ids), traversal_sequence=list(node_ids),
        cumulative_score=score, micro_abstract=None, micro_abstract_text=None,
        activation_count=0, is_permanent=False, conversation_ref="sess_new",
        created_at=time.time(), last_activated=None,
    )


def _live(conn):
    return conn.execute("SELECT COUNT(*) FROM mycelium_landmarks WHERE absorbed IS NULL").fetchone()[0]


NODES = [f"n{i}" for i in range(6)]


def test_one_crystallization_collapses_the_whole_group_of_identical_landmarks(mem_conn):
    for _ in range(4):                      # the backlog: four identical, never merged
        _raw_landmark(mem_conn, NODES)
    idx = LandmarkIndex(mem_conn)
    new = _new_landmark(NODES)
    idx.save(new)
    assert LandmarkMerger(idx).try_merge(new) is not None
    # Old code: one merge per call -> 5 identical landmarks became 4. Never fewer.
    assert _live(mem_conn) == 1


def test_a_group_never_survives_by_the_size_it_started_with(mem_conn):
    """The invariant behind the live numbers: arrivals must not keep a backlog alive."""
    for _ in range(3):
        _raw_landmark(mem_conn, NODES)
    idx = LandmarkIndex(mem_conn)
    merger = LandmarkMerger(idx)
    for _ in range(3):
        n = _new_landmark(NODES)
        idx.save(n)
        merger.try_merge(n)
    assert _live(mem_conn) == 1


def test_collapse_duplicates_absorbs_the_backlog_keeps_every_row_and_is_idempotent(mem_conn):
    for _ in range(6):
        _raw_landmark(mem_conn, NODES)                       # group of 6
    for _ in range(2):
        _raw_landmark(mem_conn, ["x1", "x2"])                # group of 2
    _raw_landmark(mem_conn, ["y1", "y2", "y3"])              # unrelated
    total = mem_conn.execute("SELECT COUNT(*) FROM mycelium_landmarks").fetchone()[0]
    merger = LandmarkMerger(LandmarkIndex(mem_conn))

    assert merger.collapse_duplicates() == 6                 # 5 + 1 absorbed
    assert _live(mem_conn) == 3
    # ABSORBS, never deletes: every row is still there, flagged absorbed.
    assert mem_conn.execute("SELECT COUNT(*) FROM mycelium_landmarks").fetchone()[0] == total
    assert mem_conn.execute(
        "SELECT COUNT(*) FROM mycelium_landmarks WHERE absorbed = 1").fetchone()[0] == 6
    assert merger.collapse_duplicates() == 0                 # idempotent
    assert _live(mem_conn) == 3


def test_collapse_moves_the_absorbed_landmarks_outside_evidence_to_the_survivor(mem_conn):
    """A promoted landmark must not be lost to a candidate by the cleanup."""
    from backend.memory.mycelium.landmark import ensure_landmark_policy_columns

    ensure_landmark_policy_columns(mem_conn)
    old = _raw_landmark(mem_conn, NODES, created=1.0)          # the oldest: absorbed first
    _raw_landmark(mem_conn, NODES, created=2.0)
    ev = [{"kind": "task_complete", "session": "s1"}, {"kind": "test_pass", "session": "s2"}]
    mem_conn.execute("UPDATE mycelium_landmarks SET evidence = ?, tier = 'landmark' WHERE landmark_id = ?",
                     (json.dumps(ev), old))
    mem_conn.commit()
    assert LandmarkMerger(LandmarkIndex(mem_conn)).collapse_duplicates() == 1
    tier, evidence = mem_conn.execute(
        "SELECT tier, evidence FROM mycelium_landmarks WHERE absorbed IS NULL").fetchone()
    assert tier == "landmark" and len(json.loads(evidence)) == 2


def test_two_merges_in_one_second_are_both_logged(mem_conn, monkeypatch):
    """merge_id was ``mrg_<seconds>``: the second merge in a second hit the PK."""
    monkeypatch.setattr(profile_mod, "time", types.SimpleNamespace(time=lambda: 1_800_000_000.0))
    for _ in range(2):
        _raw_landmark(mem_conn, NODES)
    idx = LandmarkIndex(mem_conn)
    merger = LandmarkMerger(idx)
    for _ in range(2):
        n = _new_landmark(NODES)
        idx.save(n)
        merger.try_merge(n)
    ids = [r[0] for r in mem_conn.execute("SELECT merge_id FROM mycelium_landmark_merges")]
    assert len(ids) >= 2 and len(set(ids)) == len(ids)


def _hub_graph(mi):
    """Six always-present nodes (high access_count) and four session-specific ones."""
    store = mi._store
    hubs = [store.upsert_node("domain", [0.10 + 0.12 * i, 0.5, 1.0], f"hub{i}", 0.9) for i in range(6)]
    mine = [store.upsert_node("conduct", [0.10 + 0.2 * i, 0.5, 0.5, 0.5, 0.5], f"mine{i}", 0.5)
            for i in range(4)]
    for n in hubs:
        mi._conn.execute("UPDATE mycelium_nodes SET access_count = 50 WHERE node_id = ?", (n.node_id,))
    for n in mine:
        mi._conn.execute("UPDATE mycelium_nodes SET access_count = 1 WHERE node_id = ?", (n.node_id,))
    mi._conn.commit()
    return {n.node_id for n in hubs}, [n.node_id for n in mine]


def test_the_cluster_is_the_sessions_nodes_not_the_graphs_top_nodes(mem_conn):
    mi = MyceliumInterface(mem_conn)
    hubs, mine = _hub_graph(mi)
    mi._registry.register("sess_a", mine[:2])
    mi._registry.register("sess_b", mine[2:])
    for sid in ("sess_a", "sess_b"):
        mi.crystallize_landmark(sid, 0.8, "hit", task_entry_label=f"task of {sid}")
    clusters = sorted(
        ({d["node_id"] for d in json.loads(c)}
         for (c,) in mem_conn.execute(
             "SELECT coordinate_cluster FROM mycelium_landmarks WHERE absorbed IS NULL")),
        key=lambda s: sorted(s))
    # Old code: both landmarks took the six hubs, were identical, and became ONE.
    assert clusters == sorted([set(mine[:2]), set(mine[2:])], key=lambda s: sorted(s))
    assert all(not (c & hubs) for c in clusters)


def test_a_session_that_walked_nothing_crystallizes_nothing(mem_conn):
    """Coordinator decision before merge (2026-10-19): with no region the condenser's
    fallback is the graph's global top nodes - the cluster bug - and the merge rule
    would absorb every legacy look-alike at once. No region, no landmark (counted)."""
    from backend.agent import write_counters

    mi = MyceliumInterface(mem_conn)
    _hub_graph(mi)
    n0 = write_counters.get("landmark.crystallize.skipped_no_region")
    assert mi.crystallize_landmark("sess_none", 0.8, "hit", task_entry_label="no region") is None
    assert write_counters.get("landmark.crystallize.skipped_no_region") == n0 + 1


def _tie_landmark(conn, lid, node_ids, score):
    return _raw_landmark(conn, node_ids, score=score, lid=lid)


def test_landmarks_in_region_ties_go_to_the_more_specific_landmark(mem_conn):
    # Same overlap (1 node), ids chosen so the OLD tie-break (landmark_id) picks the wide one.
    _tie_landmark(mem_conn, "aaa_wide", ["hit", "w1", "w2", "w3", "w4", "w5"], 0.9)
    _tie_landmark(mem_conn, "zzz_narrow", ["hit", "k1"], 0.1)
    assert LandmarkIndex(mem_conn).landmarks_in_region({"hit"}) == ["zzz_narrow", "aaa_wide"]


def test_landmarks_in_region_then_the_higher_score_then_the_id(mem_conn):
    _tie_landmark(mem_conn, "m1", ["hit", "a"], 0.3)
    _tie_landmark(mem_conn, "m2", ["hit", "b"], 0.9)
    _tie_landmark(mem_conn, "m3", ["hit", "c"], 0.9)
    assert LandmarkIndex(mem_conn).landmarks_in_region({"hit"}) == ["m2", "m3", "m1"]


def test_a_larger_overlap_still_beats_a_more_specific_one(mem_conn):
    _tie_landmark(mem_conn, "big", ["a", "b", "c", "d", "e", "f"], 0.5)   # overlap 3 of 6
    _tie_landmark(mem_conn, "tiny", ["a", "z"], 0.5)                       # overlap 1 of 2
    assert LandmarkIndex(mem_conn).landmarks_in_region({"a", "b", "c"})[0] == "big"

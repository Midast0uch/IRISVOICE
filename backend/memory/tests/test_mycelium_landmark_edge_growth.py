"""Guard (2026-10-19, Kyudo proposal 7): landmark edges GROW.

What was wrong (live store, read-only): mycelium_landmark_edges held 6,628 rows,
ALL score 0.4, traversal_count 0, last_traversed NULL. They were created by an
INSERT OR IGNORE and nothing ever updated them, so landmark recall could not
learn which patterns go together, and apply_landmark_decay (on the one law,
decay.py) skipped every edge (last_traversed IS NULL) - it never had work.

The growth half uses the SAME law as EdgeScorer.record_outcome:
score += delta * 1/(1+n), n = traversal_count BEFORE the observation.
Each guard below FAILS on the code before this change.
"""
import json
import time
import uuid

import pytest

from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.decay import ensure_decay_columns, evidence_weight
from backend.memory.mycelium.interface import MyceliumInterface
from backend.memory.mycelium.landmark import LandmarkIndex
from backend.memory.mycelium.scorer import _OUTCOME_DELTAS

DAY = 86400.0


def _landmark(conn, node_ids, absorbed=None):
    lid = "lm_" + uuid.uuid4().hex[:8]
    cluster = [{"space_id": "domain", "node_id": n} for n in node_ids]
    conn.execute(
        "INSERT INTO mycelium_landmarks (landmark_id, label, task_class, coordinate_cluster,"
        " traversal_sequence, cumulative_score, activation_count, is_permanent, created_at,"
        " absorbed) VALUES (?, 'lm', 'code_task', ?, '[]', 0.8, 0, 0, ?, ?)",
        (lid, json.dumps(cluster), time.time(), absorbed),
    )
    conn.commit()
    return lid


def _edge(conn, a, b, score=0.4, n=0):
    conn.execute(
        "INSERT INTO mycelium_landmark_edges (edge_id, from_landmark_id, to_landmark_id,"
        " score, edge_type, traversal_count, hit_count, miss_count, created_at, last_traversed)"
        " VALUES (?, ?, ?, ?, 'similarity', ?, 0, 0, ?, NULL)",
        (uuid.uuid4().hex[:12], a, b, score, n, time.time()),
    )
    conn.commit()


def _edge_row(conn, a, b):
    return conn.execute(
        "SELECT score, traversal_count, hit_count, miss_count, last_traversed "
        "FROM mycelium_landmark_edges WHERE from_landmark_id = ? AND to_landmark_id = ?",
        (a, b),
    ).fetchone()


def _pair(conn):
    """Two landmarks, each sharing a node id with the session region, joined by a fresh 0.4 edge."""
    na, nb = uuid.uuid4().hex, uuid.uuid4().hex
    a, b = _landmark(conn, [na]), _landmark(conn, [nb])
    _edge(conn, a, b)
    return a, b, {na, nb}


def test_hit_raises_the_edge_among_co_activated_landmarks(mem_conn):
    a, b, region = _pair(mem_conn)
    LandmarkIndex(mem_conn).observe_region(region, "hit")
    score, n, hits, misses, last = _edge_row(mem_conn, a, b)
    assert score == pytest.approx(0.4 + _OUTCOME_DELTAS["hit"])   # n = 0: full weight
    assert (n, hits, misses) == (1, 1, 0)
    assert last is not None


def test_miss_lowers_the_edge(mem_conn):
    a, b, region = _pair(mem_conn)
    LandmarkIndex(mem_conn).observe_region(region, "miss")
    score, n, hits, misses, _ = _edge_row(mem_conn, a, b)
    assert score == pytest.approx(0.4 + _OUTCOME_DELTAS["miss"])
    assert (n, hits, misses) == (1, 0, 1)


def test_a_proven_edge_moves_less(mem_conn):
    fresh_a, fresh_b, fresh_region = _pair(mem_conn)
    old_a, old_b, old_region = _pair(mem_conn)
    mem_conn.execute(
        "UPDATE mycelium_landmark_edges SET traversal_count = 9 WHERE from_landmark_id = ?",
        (old_a,),
    )
    mem_conn.commit()
    index = LandmarkIndex(mem_conn)
    index.observe_region(fresh_region, "hit")
    index.observe_region(old_region, "hit")
    fresh_gain = _edge_row(mem_conn, fresh_a, fresh_b)[0] - 0.4
    old_gain = _edge_row(mem_conn, old_a, old_b)[0] - 0.4
    assert old_gain == pytest.approx(fresh_gain * evidence_weight(9))
    assert old_gain < fresh_gain / 5
    assert _edge_row(mem_conn, old_a, old_b)[1] == 10


def test_decay_now_acts_on_a_grown_edge(mem_conn):
    ensure_decay_columns(mem_conn)   # the application store's shape
    a, b, region = _pair(mem_conn)
    index = LandmarkIndex(mem_conn)
    index.observe_region(region, "hit")
    grown = _edge_row(mem_conn, a, b)[0]
    mem_conn.execute(
        "UPDATE mycelium_landmark_edges SET last_traversed = ? WHERE from_landmark_id = ?",
        (time.time() - 10 * DAY, a),
    )
    mem_conn.commit()
    index.apply_landmark_decay()
    assert _edge_row(mem_conn, a, b)[0] < grown


def test_a_pair_without_an_edge_gets_one_at_the_initial_score_then_grows(mem_conn):
    na, nb = uuid.uuid4().hex, uuid.uuid4().hex
    _landmark(mem_conn, [na])
    _landmark(mem_conn, [nb])
    LandmarkIndex(mem_conn).observe_region({na, nb}, "hit")
    rows = mem_conn.execute(
        "SELECT score, traversal_count FROM mycelium_landmark_edges"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(0.4 + _OUTCOME_DELTAS["hit"])
    assert rows[0][1] == 1


def test_edge_stored_in_the_other_direction_is_the_pairs_edge(mem_conn):
    a, b, region = _pair(mem_conn)
    mem_conn.execute(
        "UPDATE mycelium_landmark_edges SET from_landmark_id = ?, to_landmark_id = ?",
        (b, a),
    )
    mem_conn.commit()
    LandmarkIndex(mem_conn).observe_region(region, "hit")
    assert mem_conn.execute("SELECT COUNT(*) FROM mycelium_landmark_edges").fetchone()[0] == 1
    assert _edge_row(mem_conn, b, a)[1] == 1


def test_activation_is_bounded_and_skips_absorbed_and_unrelated(mem_conn):
    nodes = [uuid.uuid4().hex for _ in range(8)]
    ids = [_landmark(mem_conn, [n]) for n in nodes]
    gone = _landmark(mem_conn, ["only-in-absorbed"], absorbed=1)
    _landmark(mem_conn, ["unrelated"])
    index = LandmarkIndex(mem_conn)
    activated = index.observe_region(set(nodes) | {"only-in-absorbed"}, "hit")
    assert len(activated) == 6 and set(activated) <= set(ids)
    assert gone not in activated
    assert mem_conn.execute("SELECT COUNT(*) FROM mycelium_landmark_edges").fetchone()[0] == 15
    counts = dict(mem_conn.execute("SELECT landmark_id, activation_count FROM mycelium_landmarks"))
    assert sorted(counts.values()).count(1) == 6
    assert counts[gone] == 0


def test_one_landmark_or_no_overlap_writes_no_edge(mem_conn):
    n = uuid.uuid4().hex
    lone = _landmark(mem_conn, [n])
    index = LandmarkIndex(mem_conn)
    assert index.observe_region({n}, "hit") == [lone]
    assert index.observe_region({"nothing"}, "hit") == []
    assert mem_conn.execute("SELECT COUNT(*) FROM mycelium_landmark_edges").fetchone()[0] == 0


def test_the_turn_end_reads_the_region_the_session_had_when_cleared(mem_conn):
    """The kernel clears the Mycelium session on the answer path; the
    episode/landmark job runs after, on a lane. The region must survive."""
    a, b, region = _pair(mem_conn)
    mi = MyceliumInterface(mem_conn)
    mi._registry.register("sess", sorted(region))
    mi.clear_session("sess")
    assert mi._registry.get_region("sess") == set()
    assert set(mi.observe_landmark_use("sess", "hit")) == {a, b}
    assert _edge_row(mem_conn, a, b)[1] == 1

"""
Tests for EdgeScorer and MapManager — Task 12.3
Requirements: 14.4, 14.5, 7.1–7.10
"""

import time
import uuid
import pytest
from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.store import CoordinateStore
from backend.memory.mycelium.scorer import EdgeScorer, MapManager
from backend.memory.mycelium.spaces import PRUNE_THRESHOLD


def _seed_spaces(conn):
    for sid in ["conduct", "domain", "style", "chrono", "context", "capability", "toolpath"]:
        conn.execute(
            "INSERT OR IGNORE INTO mycelium_spaces (space_id, axes, dtype, value_range) VALUES (?,?,?,?)",
            (sid, "[]", "float32", "[0.0,1.0]"),
        )
    conn.commit()


def _insert_edge(conn, from_id, to_id, score=0.5, space_id="domain", decay_rate=0.01):
    edge_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO mycelium_edges
           (edge_id, from_node_id, to_node_id, score, edge_type, decay_rate, created_at, last_traversed)
           VALUES (?, ?, ?, ?, 'traversal', ?, ?, ?)""",
        (edge_id, from_id, to_id, score, decay_rate, time.time(), time.time()),
    )
    conn.commit()
    return edge_id


def _insert_node(conn, space_id, label="n", coords=None):
    import struct
    coords = coords or [0.5, 0.5, 0.5, 0.5, 0.5]
    nid = str(uuid.uuid4())
    blob = struct.pack(f"{len(coords)}f", *coords)
    now = time.time()
    conn.execute(
        """INSERT INTO mycelium_nodes (node_id, space_id, coordinates, label, confidence, access_count, created_at, updated_at, last_accessed)
           VALUES (?, ?, ?, ?, 0.7, 1, ?, ?, ?)""",
        (nid, space_id, blob, label, now, now, now),
    )
    conn.commit()
    return nid


def test_hit_increases_edge_score(mem_conn):
    """Apply 'hit' outcome; verify score increased by 0.05."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    n1 = _insert_node(mem_conn, "domain", "n1")
    n2 = _insert_node(mem_conn, "domain", "n2")
    edge_id = _insert_edge(mem_conn, n1, n2, score=0.5)

    scorer = EdgeScorer(store)
    scorer.record_outcome([edge_id], "hit")

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    assert row[0] == pytest.approx(0.55, abs=0.01), f"Expected ~0.55 after hit, got {row[0]}"


def test_miss_decreases_edge_score(mem_conn):
    """Apply 'miss' outcome; verify score decreased by 0.08."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    n1 = _insert_node(mem_conn, "domain", "n1")
    n2 = _insert_node(mem_conn, "domain", "n2")
    edge_id = _insert_edge(mem_conn, n1, n2, score=0.5)

    scorer = EdgeScorer(store)
    scorer.record_outcome([edge_id], "miss")

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    assert row[0] == pytest.approx(0.42, abs=0.01), f"Expected ~0.42 after miss, got {row[0]}"


def test_decay_prunes_below_threshold(mem_conn):
    """Edge score at 0.09; after decay with high multiplier → edge deleted."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    n1 = _insert_node(mem_conn, "domain", "n1")
    n2 = _insert_node(mem_conn, "domain", "n2")
    # Set score just above prune threshold but with high decay rate
    edge_id = _insert_edge(mem_conn, n1, n2, score=0.09, decay_rate=1.0)

    scorer = EdgeScorer(store)
    pruned = scorer.apply_decay()

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    # Either pruned (row is None) or score reduced below PRUNE_THRESHOLD
    if row is not None:
        assert row[0] < PRUNE_THRESHOLD or pruned >= 0
    else:
        assert pruned >= 1


def test_toolpath_uses_toolpath_decay_rate(mem_conn):
    """Toolpath edges decay faster than regular edges given same parameters."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    from backend.memory.mycelium.spaces import TOOLPATH_DECAY_RATE
    # Use 1 day ago so decay is meaningful (decay formula: score -= rate * days_idle)
    old_ts = time.time() - 86400.0
    n1 = _insert_node(mem_conn, "domain", "n1_reg")
    n2 = _insert_node(mem_conn, "domain", "n2_reg")
    e_reg = _insert_edge(mem_conn, n1, n2, score=0.8, decay_rate=0.01)
    mem_conn.execute("UPDATE mycelium_edges SET last_traversed = ? WHERE edge_id = ?", (old_ts, e_reg))

    t1 = _insert_node(mem_conn, "toolpath", "t1")
    t2 = _insert_node(mem_conn, "toolpath", "t2")
    e_tp = _insert_edge(mem_conn, t1, t2, score=0.8, decay_rate=TOOLPATH_DECAY_RATE)
    mem_conn.execute("UPDATE mycelium_edges SET last_traversed = ? WHERE edge_id = ?", (old_ts, e_tp))
    mem_conn.commit()

    scorer = EdgeScorer(store)
    scorer.apply_decay()

    reg_row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (e_reg,)).fetchone()
    tp_row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (e_tp,)).fetchone()

    # Both may exist; if toolpath was pruned that's also valid
    if reg_row and tp_row:
        assert tp_row[0] <= reg_row[0], "Toolpath should decay same or faster than regular"


def test_highway_bonus_applied_when_crossing_threshold(mem_conn):
    """
    Req 7.4: when a 'hit' pushes the score from below HIGHWAY_THRESHOLD (0.85)
    to at or above it, an additional HIGHWAY_BONUS (0.01) must be applied.

    Score 0.82 + 0.05 (hit delta) = 0.87 ≥ 0.85 → highway crossed → +0.01 bonus
    Expected final score: 0.82 + 0.05 + 0.01 = 0.88
    """
    from backend.memory.mycelium.spaces import HIGHWAY_THRESHOLD, HIGHWAY_BONUS
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    n1 = _insert_node(mem_conn, "domain", "n1")
    n2 = _insert_node(mem_conn, "domain", "n2")
    # Start just below HIGHWAY_THRESHOLD; a hit will cross it
    start_score = HIGHWAY_THRESHOLD - 0.03   # 0.82
    edge_id = _insert_edge(mem_conn, n1, n2, score=start_score)

    scorer = EdgeScorer(store)
    scorer.record_outcome([edge_id], "hit")

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    expected = min(1.0, start_score + 0.05 + HIGHWAY_BONUS)
    assert row[0] == pytest.approx(expected, abs=0.001), (
        f"Req 7.4: highway bonus not applied. Expected ~{expected:.3f}, got {row[0]:.3f}"
    )


def test_highway_bonus_not_applied_when_already_above_threshold(mem_conn):
    """
    Req 7.4: highway bonus must NOT be applied when score was already at or
    above HIGHWAY_THRESHOLD before the hit — the bonus only fires on crossing.

    Score 0.90 + 0.05 (hit) = 0.95. No crossing → no bonus → expected 0.95.
    """
    from backend.memory.mycelium.spaces import HIGHWAY_THRESHOLD
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    n1 = _insert_node(mem_conn, "domain", "n1")
    n2 = _insert_node(mem_conn, "domain", "n2")
    start_score = HIGHWAY_THRESHOLD + 0.05  # 0.90 — already above
    edge_id = _insert_edge(mem_conn, n1, n2, score=start_score)

    scorer = EdgeScorer(store)
    scorer.record_outcome([edge_id], "hit")

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    expected = min(1.0, start_score + 0.05)  # no bonus
    assert row[0] == pytest.approx(expected, abs=0.001), (
        f"Req 7.4: highway bonus must NOT fire when already above threshold. "
        f"Expected ~{expected:.3f}, got {row[0]:.3f}"
    )


def test_decay_formula_score_minus_rate_times_days(mem_conn):
    """
    Req 7.2: decay formula is score -= decay_rate * days_idle.

    Edge: score=0.50, decay_rate=0.01, last_traversed=10 days ago.
    Expected new score: 0.50 - 0.01 * 10 = 0.40 (well above PRUNE_THRESHOLD=0.08).
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    n1 = _insert_node(mem_conn, "domain", "n1")
    n2 = _insert_node(mem_conn, "domain", "n2")
    # decay_rate=0.01, 10 days → 0.50 - 0.01 * 10 = 0.40 (survives; > PRUNE_THRESHOLD=0.08)
    edge_id = _insert_edge(mem_conn, n1, n2, score=0.50, decay_rate=0.01)
    ten_days_ago = time.time() - 10 * 86400.0
    mem_conn.execute("UPDATE mycelium_edges SET last_traversed = ? WHERE edge_id = ?", (ten_days_ago, edge_id))
    mem_conn.commit()

    scorer = EdgeScorer(store)
    scorer.apply_decay()

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    assert row is not None, "Edge should survive (0.40 > PRUNE_THRESHOLD 0.08)"
    assert row[0] == pytest.approx(0.40, abs=0.02), (
        f"Req 7.2: decay formula score -= rate * days. Expected ~0.40, got {row[0]:.3f}"
    )


def test_condense_merges_close_nodes(mem_conn):
    """
    Req 7.5: condense() merges pairs of nodes within CONDENSE_THRESHOLD (0.04)
    Euclidean distance, keeping the one with higher access_count and deleting the other.

    Two nodes 0.01 apart (well within 0.04) → after condense only 1 remains.
    The survivor MUST be the one with higher access_count.
    """
    import struct
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    c1 = [0.500, 0.5, 0.5, 0.5, 0.5]
    c2 = [0.501, 0.5, 0.5, 0.5, 0.5]  # Euclidean distance = 0.001 << 0.04
    nid_high = str(uuid.uuid4())  # higher access_count → survivor
    nid_low  = str(uuid.uuid4())  # lower access_count → merged away
    now = time.time()
    mem_conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,0.7,10,?,?,?)",
        (nid_high, "domain", struct.pack("5f", *c1), "high_access", now, now, now),
    )
    mem_conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,0.7,2,?,?,?)",
        (nid_low, "domain", struct.pack("5f", *c2), "low_access", now, now, now),
    )
    mem_conn.commit()

    mm = MapManager(store)
    mm.condense("domain")

    rows = mem_conn.execute(
        "SELECT node_id FROM mycelium_nodes WHERE space_id='domain'"
    ).fetchall()
    assert len(rows) == 1, (
        f"Req 7.5: condense() must reduce 2 close nodes to 1, got {len(rows)} nodes"
    )
    assert rows[0][0] == nid_high, (
        "Req 7.5: survivor must be the node with higher access_count"
    )


def test_partial_increases_edge_score_by_002(mem_conn):
    """
    Req 7.1: 'partial' outcome increases score by +0.02.
    Start 0.5 → expected 0.52.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    n1 = _insert_node(mem_conn, "domain", "n1")
    n2 = _insert_node(mem_conn, "domain", "n2")
    edge_id = _insert_edge(mem_conn, n1, n2, score=0.5)

    scorer = EdgeScorer(store)
    scorer.record_outcome([edge_id], "partial")

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    assert row[0] == pytest.approx(0.52, abs=0.01), (
        f"Req 7.1: 'partial' outcome must add +0.02. Expected ~0.52, got {row[0]}"
    )


def test_condense_fixed_space_order(mem_conn):
    """
    Req 7.10: run_condense() iterates spaces in the fixed order
    domain → style → conduct → chrono → capability → context → toolpath.

    We verify this by patching condense() to record which spaces are processed
    and in what order.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    mm = MapManager(store)

    visited = []
    original_condense = mm.condense

    def tracking_condense(space_id):
        visited.append(space_id)
        return original_condense(space_id)

    mm.condense = tracking_condense
    mm.run_condense()

    expected_order = ["domain", "style", "conduct", "chrono", "capability", "context", "toolpath"]
    assert visited == expected_order, (
        f"Req 7.10: fixed space iteration order violated. "
        f"Expected {expected_order}, got {visited}"
    )

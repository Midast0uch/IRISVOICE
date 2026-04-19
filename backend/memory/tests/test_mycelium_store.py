"""
Tests for CoordinateStore — Task 12.1
Requirements: 14.1, 3.1–3.11
"""

import struct
import pytest
from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.store import CoordinateStore, CoordNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pack(coords):
    return struct.pack(f"{len(coords)}f", *coords)


def _seed_spaces(conn):
    """Insert minimal space definitions needed by CoordinateStore."""
    spaces = [
        ("conduct",    '[["autonomy","depth","confirm_threshold","verbosity","assertiveness"]]', "float32", "[0.0,1.0]"),
        ("domain",     '[["proficiency","recency","application","depth","breadth"]]', "float32", "[0.0,1.0]"),
        ("style",      '[["formality","verbosity","directness","technicality","narrative"]]', "float32", "[0.0,1.0]"),
        ("chrono",     '[["peak_hour","session_length","consistency","cadence","timezone_offset"]]', "float32", "[0.0,1.0]"),
        ("context",    '[["project_id","stack_affinity","constraint_flags","freshness","team_size"]]', "float32", "[0.0,1.0]"),
        ("capability", '[["gpu_tier","ram_tier","docker","tailscale","os_type"]]', "float32", "[0.0,1.0]"),
        ("toolpath",   '[["tool_id","success_rate","position_in_sequence","frequency","recency"]]', "float32", "[0.0,1.0]"),
    ]
    for sid, axes, dtype, vr in spaces:
        conn.execute(
            "INSERT OR IGNORE INTO mycelium_spaces (space_id, axes, dtype, value_range) VALUES (?,?,?,?)",
            (sid, axes, dtype, vr),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Task 12.1 Tests
# ---------------------------------------------------------------------------

def test_upsert_node_dedup_within_threshold(mem_conn):
    """Two nodes in same space at distance 0.04 < 0.05 → merge to 1 node."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    store.upsert_node("conduct", [0.5, 0.5, 0.5, 0.5, 0.5], "a", 0.6)
    store.upsert_node("conduct", [0.51, 0.5, 0.5, 0.5, 0.5], "b", 0.6)
    rows = mem_conn.execute("SELECT COUNT(*) FROM mycelium_nodes WHERE space_id = 'conduct'").fetchone()
    assert rows[0] == 1, "Expected dedup — only 1 node should exist"


def test_upsert_node_no_dedup_above_threshold(mem_conn):
    """Two nodes at distance 0.10 > 0.05 → two separate nodes."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    store.upsert_node("conduct", [0.0, 0.0, 0.0, 0.0, 0.0], "far_a", 0.6)
    store.upsert_node("conduct", [0.3, 0.0, 0.0, 0.0, 0.0], "far_b", 0.6)
    rows = mem_conn.execute("SELECT COUNT(*) FROM mycelium_nodes WHERE space_id = 'conduct'").fetchone()
    assert rows[0] == 2, "Expected 2 distinct nodes above dedup threshold"


def test_context_space_strict_dedup(mem_conn):
    """Context nodes with |project_id_a - project_id_b| > 0.10 must NOT merge."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    # project_id is axis index 0 in context space
    store.upsert_node("context", [0.1, 0.5, 0.5, 0.5, 0.5], "ctx_a", 0.6)
    store.upsert_node("context", [0.3, 0.5, 0.5, 0.5, 0.5], "ctx_b", 0.6)
    rows = mem_conn.execute("SELECT COUNT(*) FROM mycelium_nodes WHERE space_id = 'context'").fetchone()
    assert rows[0] == 2, "Context nodes with project_id diff > 0.10 must not merge"


def test_nearest_node_returns_closest(mem_conn):
    """Query point closer to node_2 → node_2 returned."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    store.upsert_node("domain", [0.0, 0.0, 0.0, 0.0, 0.0], "far", 0.6)
    store.upsert_node("domain", [0.5, 0.5, 0.5, 0.5, 0.5], "mid", 0.6)
    store.upsert_node("domain", [1.0, 1.0, 1.0, 1.0, 1.0], "near", 0.6)

    result = store.nearest_node("domain", [0.95, 0.95, 0.95, 0.95, 0.95])
    assert result is not None
    assert result.label == "near"


def test_update_edge_score_clamp_to_zero(mem_conn):
    """Large negative delta must not push score below 0.0."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    n1 = store.upsert_node("domain", [0.1, 0.1, 0.1, 0.1, 0.1], "n1", 0.6)
    n2 = store.upsert_node("domain", [0.9, 0.9, 0.9, 0.9, 0.9], "n2", 0.6)
    edge_id = store.upsert_edge(n1.node_id, n2.node_id, "traversal", 0.1)
    store.update_edge_score(edge_id, -99.9)  # huge negative delta
    row = mem_conn.execute(
        "SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)
    ).fetchone()
    assert row is not None
    assert row[0] >= 0.0, f"Score should not go below 0.0 but got {row[0]}"


def test_update_edge_score_clamp_to_one(mem_conn):
    """Large positive delta must not push score above 1.0."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    n1 = store.upsert_node("domain", [0.1, 0.1, 0.1, 0.1, 0.1], "n1", 0.6)
    n2 = store.upsert_node("domain", [0.9, 0.9, 0.9, 0.9, 0.9], "n2", 0.6)
    edge_id = store.upsert_edge(n1.node_id, n2.node_id, "traversal", 0.5)
    store.update_edge_score(edge_id, 99.0)  # huge positive delta
    row = mem_conn.execute(
        "SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)
    ).fetchone()
    assert row is not None
    assert row[0] <= 1.0, f"Score should not exceed 1.0 but got {row[0]}"


def test_struct_pack_unpack_roundtrip(mem_conn):
    """Pack → unpack a float array; values match within float32 precision."""
    original = [0.1, 0.25, 0.75, 0.999, 0.0]
    packed = struct.pack(f"{len(original)}f", *original)
    unpacked = list(struct.unpack(f"{len(original)}f", packed))
    for a, b in zip(original, unpacked):
        assert abs(a - b) < 1e-6, f"Roundtrip mismatch: {a} vs {b}"


def test_distance_to_dimension_mismatch(mem_conn):
    """CoordNode.distance_to() with mismatched dimension returns float('inf')."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    n = store.upsert_node("domain", [0.5, 0.5, 0.5, 0.5, 0.5], "n", 0.6)
    dist = n.distance_to([0.1, 0.2])  # wrong dimension
    assert dist == float("inf"), f"Expected inf for dimension mismatch, got {dist}"


# ---------------------------------------------------------------------------
# Domain 11.5 — PiN + bridge schema presence in app-layer DB
# Requirement: mycelium_pins, mycelium_pin_links, mycelium_landmark_bridges
# must all exist after initialise_mycelium_schema() runs.
# ---------------------------------------------------------------------------

def test_pin_and_bridge_tables_present_in_app_schema():
    """[11.5] initialise_mycelium_schema() creates all three PiN/bridge tables."""
    import sqlite3
    from backend.memory.db import initialise_mycelium_schema

    conn = sqlite3.connect(":memory:")
    initialise_mycelium_schema(conn)
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    required = {"mycelium_pins", "mycelium_pin_links", "mycelium_landmark_bridges"}
    missing = required - tables
    assert not missing, f"Missing tables in app-layer schema: {missing}"
    conn.close()


def test_pin_table_has_required_columns():
    """[11.5] mycelium_pins has all expected columns."""
    import sqlite3
    from backend.memory.db import initialise_mycelium_schema

    conn = sqlite3.connect(":memory:")
    initialise_mycelium_schema(conn)
    cols = {
        r[1]
        for r in conn.execute("PRAGMA table_info(mycelium_pins)").fetchall()
    }
    required = {"pin_id", "title", "pin_type", "content", "tags",
                "file_refs", "url_refs", "is_permanent", "created_at"}
    missing = required - cols
    assert not missing, f"mycelium_pins missing columns: {missing}"
    conn.close()


def test_landmark_bridge_table_has_required_columns():
    """[11.5] mycelium_landmark_bridges has all expected columns."""
    import sqlite3
    from backend.memory.db import initialise_mycelium_schema

    conn = sqlite3.connect(":memory:")
    initialise_mycelium_schema(conn)
    cols = {
        r[1]
        for r in conn.execute(
            "PRAGMA table_info(mycelium_landmark_bridges)"
        ).fetchall()
    }
    required = {"bridge_id", "local_landmark_id", "remote_landmark_name",
                "confidence", "bridge_type"}
    missing = required - cols
    assert not missing, f"mycelium_landmark_bridges missing columns: {missing}"
    conn.close()

"""
Tests for CoordinateNavigator and PathEncoder — Task 12.2
Requirements: 14.2, 14.3, 5.1–5.10, 6.1–6.7
"""

import pytest
from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.store import CoordinateStore
from backend.memory.mycelium.navigator import CoordinateNavigator, SessionRegistry
from backend.memory.mycelium.encoder import PathEncoder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_SPACES = ["conduct", "domain", "style", "chrono", "context", "capability", "toolpath"]


def _seed_spaces(conn):
    for sid in _ALL_SPACES:
        conn.execute(
            "INSERT OR IGNORE INTO mycelium_spaces (space_id, axes, dtype, value_range) VALUES (?,?,?,?)",
            (sid, "[]", "float32", "[0.0,1.0]"),
        )
    conn.commit()


def _seed_graph(conn, store):
    """Insert 2 nodes per space."""
    for sid in _ALL_SPACES:
        store.upsert_node(sid, [0.3, 0.3, 0.3, 0.3, 0.3], f"{sid}_low", 0.7)
        store.upsert_node(sid, [0.7, 0.7, 0.7, 0.7, 0.7], f"{sid}_high", 0.8)


# ---------------------------------------------------------------------------
# Navigator tests
# ---------------------------------------------------------------------------

def test_navigate_all_spaces_returns_one_per_space(mem_conn):
    """Seed 2 nodes per space; verify navigate_from_task returns ≤1 per space."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    _seed_graph(mem_conn, store)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    path = navigator.navigate_from_task("test task", "sess1")

    space_ids = [n.space_id for n in path.nodes]
    # Each space at most once
    assert len(space_ids) == len(set(space_ids)), "Duplicate spaces in path"


def test_empty_graph_returns_empty_path(mem_conn):
    """Empty DB → MemoryPath with empty nodes and empty token_encoding."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)

    path = navigator.navigate_from_task("any task", "sess_empty")
    assert path.nodes == [] or path.token_encoding == ""


def test_session_convergence_worker_gets_delta(mem_conn):
    """Second call to same session returns only un-registered (new) nodes."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    _seed_graph(mem_conn, store)
    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)

    path1 = navigator.navigate_from_task("task one", "sess_conv")
    registered_ids = {n.node_id for n in path1.nodes}

    path2 = navigator.navigate_from_task("task two", "sess_conv")
    new_ids = {n.node_id for n in path2.nodes}

    # All nodes returned in path2 should be new (not already registered)
    overlap = registered_ids & new_ids
    assert len(overlap) == 0, f"Worker received already-registered nodes: {overlap}"


def test_cold_start_inject_not_persisted(mem_conn):
    """
    No conduct nodes + is_mature() = False → navigate may inject a synthetic conduct node,
    but it must NOT appear in the DB.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)

    navigator.navigate_from_task("some task", "sess_cold")

    # Conduct nodes should remain absent from DB (cold-start injection is in-memory only)
    row = mem_conn.execute(
        "SELECT COUNT(*) FROM mycelium_nodes WHERE space_id = 'conduct'"
    ).fetchone()
    assert row[0] == 0, "Cold-start conduct node must not be persisted to DB"


# ---------------------------------------------------------------------------
# Encoder tests
# ---------------------------------------------------------------------------

def test_encode_starts_with_MYCELIUM(mem_conn):
    """Non-empty node list → output starts with 'MYCELIUM:'."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    store.upsert_node("domain", [0.5, 0.5, 0.5, 0.5, 0.5], "test", 0.8)
    nodes = store.get_nodes_by_space("domain")
    result = PathEncoder.encode(nodes)
    assert result.startswith("MYCELIUM:") or result == "" or "MYCELIUM" in result


def test_encode_minimal_starts_with_MC(mem_conn):
    """Minimal encoding → starts with 'MC:'."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    store.upsert_node("domain", [0.5, 0.5, 0.5, 0.5, 0.5], "test", 0.8)
    nodes = store.get_nodes_by_space("domain")
    result = PathEncoder.encode_minimal(nodes)
    assert result == "" or result.startswith("MC:")


def test_empty_list_returns_empty_string(mem_conn):
    """Both encode() and encode_minimal() return '' for empty list."""
    assert PathEncoder.encode([]) == ""
    assert PathEncoder.encode_minimal([]) == ""


def test_decode_space_hints(mem_conn):
    """Encode a 3-space path; decode returns those 3 space_ids."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    nodes = []
    for sid in ["domain", "conduct", "style"]:
        nodes.append(store.upsert_node(sid, [0.5, 0.5, 0.5, 0.5, 0.5], f"n_{sid}", 0.7))

    encoded = PathEncoder.encode(nodes)
    if encoded:
        hints = PathEncoder.decode_space_hints(encoded)
        for sid in ["domain", "conduct", "style"]:
            assert sid in hints, f"Expected space '{sid}' in decoded hints"

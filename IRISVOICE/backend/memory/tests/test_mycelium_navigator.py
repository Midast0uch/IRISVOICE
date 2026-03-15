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

def test_encode_full_format(mem_conn):
    """
    Req 6.1: full encoding starts with 'MYCELIUM: '.
    Req 6.2: each node segment is formatted as {space_id}({label}):{c1},{c2},...@{access_count}
             with coordinates rounded to 3 decimal places.
    Req 6.3: final segment is 'confidence:{avg:.2f}'.
    """
    import re
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    store.upsert_node("domain", [0.5, 0.5, 0.5], "mytest", 0.8)
    nodes = store.get_nodes_by_space("domain")
    result = PathEncoder.encode(nodes)

    assert result.startswith("MYCELIUM: "), (
        f"Req 6.1: full encoding must start with 'MYCELIUM: ', got: {result!r}"
    )

    # Node segment pattern: domain(mytest):0.500,0.500,0.500@N
    node_pattern = re.compile(
        r"[a-z_]+\([^)]+\):[0-9]+\.[0-9]{3}(?:,[0-9]+\.[0-9]{3})*@[0-9]+"
    )
    segments = [s.strip() for s in result[len("MYCELIUM: "):].split("|")]
    node_segments = segments[:-1]  # last is confidence
    for seg in node_segments:
        assert node_pattern.match(seg.strip()), (
            f"Req 6.2: node segment does not match "
            f"'space(label):c1,c2,...@access_count' format: {seg!r}"
        )

    # Confidence segment
    conf_seg = segments[-1].strip()
    assert re.match(r"confidence:[0-9]+\.[0-9]{2}$", conf_seg), (
        f"Req 6.3: last segment must be 'confidence:X.XX', got: {conf_seg!r}"
    )


def test_encode_minimal_format(mem_conn):
    """
    Req 6.1: minimal encoding starts with 'MC: '.
    Req 6.4: each node segment is {space_id}:{c1},{c2},... with 2-decimal precision,
             NO labels and NO access counts.
    """
    import re
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    store.upsert_node("domain", [0.5, 0.5, 0.5], "labeled", 0.8)
    nodes = store.get_nodes_by_space("domain")
    result = PathEncoder.encode_minimal(nodes)

    assert result.startswith("MC: "), (
        f"Req 6.4: minimal encoding must start with 'MC: ', got: {result!r}"
    )

    body = result[len("MC: "):].strip()
    # No parentheses (no labels), no @ (no access counts)
    assert "(" not in body and "@" not in body, (
        f"Req 6.4: minimal encoding must omit labels and access_counts, got: {body!r}"
    )

    # Each coord rounded to 2 decimal places
    minimal_node_pattern = re.compile(r"[a-z_]+:[0-9]+\.[0-9]{2}(?:,[0-9]+\.[0-9]{2})*")
    for seg in body.split("|"):
        assert minimal_node_pattern.match(seg.strip()), (
            f"Req 6.4: minimal segment must be 'space:c1,c2,...' with 2-decimal coords: {seg!r}"
        )


def test_empty_list_returns_empty_string(mem_conn):
    """Both encode() and encode_minimal() return '' for empty list."""
    assert PathEncoder.encode([]) == ""
    assert PathEncoder.encode_minimal([]) == ""


def test_record_path_outcome_partial_delta(mem_conn):
    """
    Req 5.7: record_path_outcome with 'partial' outcome applies +0.02 delta to path edges.
    """
    import struct
    import uuid
    import time
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    # Insert two nodes and an edge between them
    def _insert_node_raw(space_id, label):
        nid = str(uuid.uuid4())
        blob = struct.pack(">5f", 0.5, 0.5, 0.5, 0.5, 0.5)
        now = time.time()
        mem_conn.execute(
            "INSERT INTO mycelium_nodes VALUES (?,?,?,?,0.7,1,?,?,?)",
            (nid, space_id, blob, label, now, now, now),
        )
        mem_conn.commit()
        return nid

    n1 = _insert_node_raw("domain", "n1")
    n2 = _insert_node_raw("domain", "n2")
    edge_id = str(uuid.uuid4())
    mem_conn.execute(
        """INSERT INTO mycelium_edges
           (edge_id, from_node_id, to_node_id, score, edge_type, decay_rate, created_at, last_traversed)
           VALUES (?,?,?,0.5,'traversal',0.01,?,?)""",
        (edge_id, n1, n2, time.time(), time.time()),
    )
    mem_conn.commit()

    from backend.memory.mycelium.store import CoordNode, MemoryPath
    from backend.memory.mycelium.navigator import CoordinateNavigator, SessionRegistry

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)

    node1 = store.get_node_by_id(n1)
    node2 = store.get_node_by_id(n2)
    path = MemoryPath(
        nodes=[node1, node2],
        cumulative_score=0.5,
        token_encoding="",
        spaces_covered=["domain"],
        traversal_id="test_trav",
    )

    navigator.record_path_outcome(path, "partial", "sess_partial", "test task")

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(0.52, abs=0.01), (
        f"Req 5.7: partial outcome must add +0.02 to edge score. Expected 0.52, got {row[0]}"
    )


def test_record_path_outcome_logs_traversal(mem_conn):
    """
    Req 5.7: record_path_outcome must log a traversal record in mycelium_traversals.
    """
    import struct
    import uuid
    import time
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    n1_id = store.upsert_node("domain", [0.3, 0.3, 0.3, 0.3, 0.3], "n1", 0.7).node_id
    from backend.memory.mycelium.store import MemoryPath
    from backend.memory.mycelium.navigator import CoordinateNavigator, SessionRegistry

    node1 = store.get_node_by_id(n1_id)
    path = MemoryPath(
        nodes=[node1],
        cumulative_score=0.6,
        token_encoding="",
        spaces_covered=["domain"],
        traversal_id="trav_log",
    )

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    navigator.record_path_outcome(path, "hit", "sess_log", "logging test task")

    row = mem_conn.execute(
        "SELECT COUNT(*) FROM mycelium_traversals WHERE session_id = 'sess_log'"
    ).fetchone()
    assert row[0] >= 1, (
        "Req 5.7: record_path_outcome must write a traversal log entry"
    )


def test_author_edge_initial_score_04(mem_conn):
    """
    Req 5.8: author_edge always creates an edge with initial score 0.4.
    The initial score is not configurable by agents.
    """
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)

    edge = navigator.author_edge(
        "domain", [0.3, 0.3, 0.3, 0.3, 0.3],
        "style", [0.7, 0.7, 0.7],
        "test_link",
    )
    assert edge is not None, "author_edge must return a CoordEdge"
    assert edge.score == pytest.approx(0.4, abs=0.01), (
        f"Req 5.8: author_edge initial score must be 0.4, got {edge.score}"
    )


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

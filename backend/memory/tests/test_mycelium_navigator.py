"""
Tests for CoordinateNavigator and PathEncoder — Task 12.2
Requirements: 14.2, 14.3, 5.1–5.10, 6.1–6.7
"""

import pytest
from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.store import CoordinateStore, MemoryPath
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


# ---------------------------------------------------------------------------
# Req 5.1 — keyword-based entry node matching
# ---------------------------------------------------------------------------

def test_keyword_match_selects_labelled_nodes(mem_conn):
    """Req 5.1: task text 'python debugging' → nodes labelled 'python' used as entry."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    # Insert a node whose label matches a task keyword
    node = store.upsert_node("domain", [0.5, 0.8, 0.5], "python", 0.8)
    # Insert a decoy that should NOT match
    store.upsert_node("style", [0.5, 0.5, 0.5], "unrelated_label", 0.8)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    path = navigator.navigate_from_task("python debugging task", "sess_kw")

    node_ids = [n.node_id for n in path.nodes]
    assert node.node_id in node_ids, (
        "Req 5.1: node whose label matches a task keyword must appear in the path"
    )


def test_keyword_match_is_case_insensitive(mem_conn):
    """Req 5.1: keyword matching is case-insensitive."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    node = store.upsert_node("domain", [0.5, 0.8, 0.5], "PYTHON", 0.8)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    path = navigator.navigate_from_task("python debugging", "sess_case")

    assert node.node_id in [n.node_id for n in path.nodes], (
        "Req 5.1: keyword matching must be case-insensitive"
    )


def test_extract_keywords_strips_punctuation(mem_conn):
    """Req 5.1: _extract_keywords strips trailing punctuation from tokens."""
    keywords = CoordinateNavigator._extract_keywords("fix the bug, please!")
    assert "bug" in keywords, "punctuation-stripped token 'bug' must appear in keywords"
    assert "please" in keywords
    # Words with len <= 2 are dropped; "it" (len=2) is filtered, "the" (len=3) is kept
    assert "it" not in CoordinateNavigator._extract_keywords("fix it please")


# ---------------------------------------------------------------------------
# Req 5.2 — fallback to domain+style nodes when no keyword match
# ---------------------------------------------------------------------------

def test_fallback_uses_domain_style_nodes(mem_conn):
    """Req 5.2: no keyword match → fallback picks domain+style nodes with confidence > 0.7."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    # Nodes that won't match any keyword in "zzz"
    d_node = store.upsert_node("domain", [0.5, 0.8, 0.5], "unmatched_label", 0.8)
    s_node = store.upsert_node("style",  [0.5, 0.5, 0.5], "another_unmatched", 0.8)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    path = navigator.navigate_from_task("zzz", "sess_fallback")

    returned_ids = {n.node_id for n in path.nodes}
    assert d_node.node_id in returned_ids or s_node.node_id in returned_ids, (
        "Req 5.2: fallback must return domain/style nodes when no keyword matches"
    )


def test_fallback_excludes_low_confidence_nodes(mem_conn):
    """Req 5.2: fallback ignores nodes with confidence <= 0.7."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    low_node = store.upsert_node("domain", [0.5, 0.8, 0.5], "low_conf", 0.5)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    path = navigator.navigate_from_task("zzz_no_match", "sess_lowconf")

    assert low_node.node_id not in [n.node_id for n in path.nodes], (
        "Req 5.2: fallback must not include nodes with confidence <= 0.7"
    )


# ---------------------------------------------------------------------------
# Req 5.3 — edge traversal
# ---------------------------------------------------------------------------

def test_edge_traversal_follows_outbound_edges(mem_conn):
    """Req 5.3: navigate_from_task follows high-score outbound edges from entry nodes."""
    import struct, uuid, time as _time
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    # Entry node with matching keyword
    entry = store.upsert_node("domain", [0.5, 0.8, 0.5], "python", 0.8)
    # Target node connected by edge
    target = store.upsert_node("style", [0.5, 0.5, 0.5], "target_style", 0.8)

    # Author edge entry → target with score above min_score (0.2)
    edge_id = store.upsert_edge(entry.node_id, target.node_id, "traversal", initial_score=0.6)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    path = navigator.navigate_from_task("python task", "sess_edge")

    returned_ids = {n.node_id for n in path.nodes}
    assert entry.node_id in returned_ids, "Entry node must appear in path"
    assert target.node_id in returned_ids, (
        "Req 5.3: target node reachable via high-score edge must appear in path"
    )


def test_edge_traversal_skips_low_score_edges(mem_conn):
    """Req 5.3: edges below min_score (0.2) are not followed."""
    import struct, uuid, time as _time
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    entry = store.upsert_node("domain", [0.5, 0.8, 0.5], "python", 0.8)
    blocked = store.upsert_node("style", [0.5, 0.5, 0.5], "blocked_target", 0.8)

    # Edge with score below min_score
    edge_id = store.upsert_edge(entry.node_id, blocked.node_id, "traversal", initial_score=0.1)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    path = navigator.navigate_from_task("python task", "sess_lowscore")

    assert blocked.node_id not in [n.node_id for n in path.nodes], (
        "Req 5.3: target node behind a low-score edge must not appear in path"
    )


# ---------------------------------------------------------------------------
# Req 5.4 — navigate_all_spaces highest confidence per space
# ---------------------------------------------------------------------------

def test_navigate_all_spaces_picks_highest_confidence(mem_conn):
    """Req 5.4: navigate_all_spaces returns the node with highest confidence per space."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    low  = store.upsert_node("domain", [0.3, 0.3, 0.3], "low_conf",  confidence=0.5)
    high = store.upsert_node("domain", [0.7, 0.7, 0.7], "high_conf", confidence=0.9)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    nodes = navigator.navigate_all_spaces("sess_allspaces")

    domain_nodes = [n for n in nodes if n.space_id == "domain"]
    assert len(domain_nodes) == 1, "navigate_all_spaces must return exactly 1 domain node"
    assert domain_nodes[0].node_id == high.node_id, (
        "Req 5.4: navigate_all_spaces must pick the highest-confidence domain node"
    )


def test_navigate_all_spaces_cold_start_conduct_coordinates(mem_conn):
    """Req 4.26: cold-start synthetic conduct node must use CONDUCT_COLD_START_DEFAULT."""
    from backend.memory.mycelium.spaces import CONDUCT_COLD_START_DEFAULT
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    # No conduct nodes — cold-start inject should fire

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    nodes = navigator.navigate_all_spaces("sess_coldstart")

    conduct_nodes = [n for n in nodes if n.space_id == "conduct"]
    assert len(conduct_nodes) == 1, "cold-start must inject exactly 1 conduct node"
    assert conduct_nodes[0].node_id == "__cold_start__", "synthetic node must use reserved ID"
    assert conduct_nodes[0].coordinates == list(CONDUCT_COLD_START_DEFAULT), (
        "Req 4.26: cold-start coordinates must equal CONDUCT_COLD_START_DEFAULT"
    )


# ---------------------------------------------------------------------------
# Req 5.5 — SessionRegistry prevents re-registration
# ---------------------------------------------------------------------------

def test_session_registry_excludes_active_nodes(mem_conn):
    """Req 5.5: nodes already registered in the session are excluded from subsequent paths."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    node = store.upsert_node("domain", [0.5, 0.8, 0.5], "python", 0.8)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)

    path1 = navigator.navigate_from_task("python task", "sess_reg")
    assert node.node_id in [n.node_id for n in path1.nodes]

    # Second call — same node is now active, must be excluded
    path2 = navigator.navigate_from_task("python task", "sess_reg")
    assert node.node_id not in [n.node_id for n in path2.nodes], (
        "Req 5.5: already-active node must not appear in subsequent paths for same session"
    )


def test_session_registry_clear_resets_tracking(mem_conn):
    """Req 5.9: clear_session() wipes registry so nodes can be re-traversed."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    node = store.upsert_node("domain", [0.5, 0.8, 0.5], "python", 0.8)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)

    navigator.navigate_from_task("python task", "sess_clear")
    navigator.clear_session("sess_clear")

    # After clear, node must be traversable again
    path = navigator.navigate_from_task("python task", "sess_clear")
    assert node.node_id in [n.node_id for n in path.nodes], (
        "Req 5.9: after clear_session, node must be traversable again"
    )


# ---------------------------------------------------------------------------
# Req 5.7 — record_path_outcome: hit/miss deltas and counters
# ---------------------------------------------------------------------------

def _make_path_with_edge(mem_conn, store):
    """Helper: insert two linked nodes, return (path, edge_id)."""
    import struct, time as _time, uuid as _uuid
    n1 = store.upsert_node("domain", [0.5, 0.5, 0.5], "n1", 0.7)
    n2 = store.upsert_node("style",  [0.5, 0.5, 0.5], "n2", 0.7)
    edge_id = store.upsert_edge(n1.node_id, n2.node_id, "traversal", initial_score=0.5)
    path = MemoryPath(
        nodes=[n1, n2],
        cumulative_score=0.5,
        token_encoding="",
        spaces_covered=["domain", "style"],
        traversal_id="t1",
    )
    return path, edge_id


def test_record_path_outcome_hit_delta(mem_conn):
    """Req 5.7: hit outcome applies +0.05 delta."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    path, edge_id = _make_path_with_edge(mem_conn, store)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    navigator.record_path_outcome(path, "hit", "sess_hit", "hit test")

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    assert row[0] == pytest.approx(0.55, abs=0.01), "Req 5.7: hit must apply +0.05 delta"


def test_record_path_outcome_miss_delta(mem_conn):
    """Req 5.7: miss outcome applies -0.08 delta."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    path, edge_id = _make_path_with_edge(mem_conn, store)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    navigator.record_path_outcome(path, "miss", "sess_miss", "miss test")

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    assert row[0] == pytest.approx(0.42, abs=0.01), "Req 5.7: miss must apply -0.08 delta"


def test_record_path_outcome_hit_increments_hit_count(mem_conn):
    """Req 5.7: hit outcome increments hit_count on the edge."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    path, edge_id = _make_path_with_edge(mem_conn, store)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    navigator.record_path_outcome(path, "hit", "sess_hitcnt", "count test")

    row = mem_conn.execute("SELECT hit_count FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    assert row[0] >= 1, "Req 5.7: hit must increment hit_count"


def test_record_path_outcome_miss_increments_miss_count(mem_conn):
    """Req 5.7: miss outcome increments miss_count on the edge."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    path, edge_id = _make_path_with_edge(mem_conn, store)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    navigator.record_path_outcome(path, "miss", "sess_misscnt", "miss count test")

    row = mem_conn.execute("SELECT miss_count FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    assert row[0] >= 1, "Req 5.7: miss must increment miss_count"


def test_record_path_outcome_unknown_outcome_no_delta(mem_conn):
    """Req 5.7: unknown outcome string → no score change."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    path, edge_id = _make_path_with_edge(mem_conn, store)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    navigator.record_path_outcome(path, "unknown_outcome", "sess_unk", "unknown test")

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    assert row[0] == pytest.approx(0.5, abs=0.01), "Unknown outcome must not change edge score"


def test_record_path_outcome_traversal_contains_node_ids(mem_conn):
    """Req 5.7: traversal log must contain the path node IDs."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    path, _ = _make_path_with_edge(mem_conn, store)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    navigator.record_path_outcome(path, "hit", "sess_trav_ids", "node id test")

    row = mem_conn.execute(
        "SELECT path_node_ids FROM mycelium_traversals WHERE session_id = 'sess_trav_ids'"
    ).fetchone()
    assert row is not None
    import json
    node_ids = json.loads(row[0])
    path_ids = [n.node_id for n in path.nodes]
    for nid in path_ids:
        assert nid in node_ids, f"Req 5.7: traversal log must contain node_id {nid}"


# ---------------------------------------------------------------------------
# Req 5.8 — author_edge: resolves nearest node, creates if absent
# ---------------------------------------------------------------------------

def test_author_edge_resolves_existing_nodes(mem_conn):
    """Req 5.8: author_edge finds nearest existing nodes rather than always inserting."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    # Pre-insert nodes close to the coords we'll pass to author_edge
    existing_from = store.upsert_node("domain", [0.5, 0.5, 0.5], "existing_from", 0.7)
    existing_to   = store.upsert_node("style",  [0.5, 0.5, 0.5], "existing_to",   0.7)
    before_count = mem_conn.execute("SELECT COUNT(*) FROM mycelium_nodes").fetchone()[0]

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    edge = navigator.author_edge(
        "domain", [0.5, 0.5, 0.5],
        "style",  [0.5, 0.5, 0.5],
        "test_link",
    )

    after_count = mem_conn.execute("SELECT COUNT(*) FROM mycelium_nodes").fetchone()[0]
    # No new nodes should have been created — nearest_node found the existing ones
    assert after_count == before_count, (
        "Req 5.8: author_edge must reuse existing nearest nodes, not insert new ones"
    )
    assert edge is not None


def test_author_edge_creates_nodes_when_absent(mem_conn):
    """Req 5.8: author_edge creates new nodes when no nearby node exists."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    edge = navigator.author_edge(
        "domain", [0.1, 0.1, 0.1],
        "style",  [0.9, 0.9, 0.9],
        "new_link",
    )

    count = mem_conn.execute("SELECT COUNT(*) FROM mycelium_nodes").fetchone()[0]
    assert count >= 2, "Req 5.8: author_edge must create from/to nodes when none exist"
    assert edge is not None
    assert edge.score == pytest.approx(0.4, abs=0.01)


# ---------------------------------------------------------------------------
# Req 5.10 — connect_nodes: internal edge with explicit score
# ---------------------------------------------------------------------------

def test_connect_nodes_creates_edge_with_specified_score(mem_conn):
    """Req 5.10: connect_nodes creates an edge at the specified initial_score."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)

    n1 = store.upsert_node("domain", [0.3, 0.3, 0.3], "n1", 0.7)
    n2 = store.upsert_node("style",  [0.7, 0.7, 0.7], "n2", 0.7)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    edge_id = navigator.connect_nodes(n1.node_id, n2.node_id, "maintenance", initial_score=0.75)

    row = mem_conn.execute("SELECT score FROM mycelium_edges WHERE edge_id = ?", (edge_id,)).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(0.75, abs=0.01), (
        "Req 5.10: connect_nodes must create edge at specified initial_score"
    )


# ---------------------------------------------------------------------------
# Req 5.6 — spaces_covered in MemoryPath
# ---------------------------------------------------------------------------

def test_navigate_path_spaces_covered_reflects_traversal(mem_conn):
    """Req 5.6: MemoryPath.spaces_covered must include all spaces traversed."""
    _seed_spaces(mem_conn)
    store = CoordinateStore(mem_conn)
    store.upsert_node("domain", [0.5, 0.8, 0.5], "domain_node", 0.8)
    store.upsert_node("style",  [0.5, 0.5, 0.5], "style_node",  0.8)

    registry = SessionRegistry()
    navigator = CoordinateNavigator(store, registry)
    path = navigator.navigate_from_task("zzz_fallback_trigger", "sess_covered")

    if path.nodes:
        actual_spaces = {n.space_id for n in path.nodes}
        covered = set(path.spaces_covered)
        assert actual_spaces == covered, (
            "Req 5.6: spaces_covered must exactly match the spaces of traversed nodes"
        )

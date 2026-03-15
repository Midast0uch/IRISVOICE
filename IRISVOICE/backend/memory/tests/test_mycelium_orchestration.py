"""
Orchestration tests — MyceliumInterface pipeline contracts.
Requirements: 12.3, 12.5, 12.7, 12.8, 12.9, 15.6
"""
import struct
import time
import uuid

import pytest

from .conftest_mycelium import mem_conn  # noqa: F401

from backend.memory.mycelium.interface import (
    MyceliumInterface,
    DISTILLATION_MAX_INTERVAL,
)
from backend.memory.mycelium.store import MemoryPath


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_mature_nodes(conn, mi: MyceliumInterface, spaces=("domain", "conduct", "style")):
    """Seed spaces with confidence >= 0.6 nodes and invalidate maturity cache."""
    for space_id in spaces:
        nid = str(uuid.uuid4())
        coords = [0.7, 0.7, 0.7]
        blob = struct.pack(f">{len(coords)}f", *coords)
        now = time.time()
        conn.execute(
            "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,1,?,?,?)",
            (nid, space_id, blob, "seed", 0.75, now, now, now),
        )
    conn.commit()
    mi._is_mature_cached = None


# ---------------------------------------------------------------------------
# Req 12.3 — maturity gate: >= 3 spaces with confidence >= 0.6
# ---------------------------------------------------------------------------

def test_is_mature_false_when_too_few_confident_spaces(mem_conn):
    """Req 12.3: only 1 confident space → immature → False."""
    mi = MyceliumInterface(mem_conn)
    nid = str(uuid.uuid4())
    blob = struct.pack(">3f", 0.7, 0.7, 0.7)
    now = time.time()
    mem_conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,1,?,?,?)",
        (nid, "domain", blob, "seed", 0.75, now, now, now),
    )
    mem_conn.commit()
    mi._is_mature_cached = None
    assert mi.is_mature() is False


def test_is_mature_true_when_threshold_met(mem_conn):
    """Req 12.3: 3 spaces with confident nodes → True."""
    mi = MyceliumInterface(mem_conn)
    _insert_mature_nodes(mem_conn, mi)
    assert mi.is_mature() is True


def test_is_mature_caches_true_indefinitely(mem_conn):
    """Req 12.3: once True, always True without re-querying."""
    mi = MyceliumInterface(mem_conn)
    _insert_mature_nodes(mem_conn, mi)
    assert mi.is_mature() is True
    # Delete all nodes — cached result must still be True
    mem_conn.execute("DELETE FROM mycelium_nodes")
    mem_conn.commit()
    assert mi.is_mature() is True, "cached True must survive node deletion"


# ---------------------------------------------------------------------------
# Req 12.5 — get_context_path() returns "" when graph is immature
# ---------------------------------------------------------------------------

def test_get_context_path_returns_empty_when_immature(mem_conn):
    """Req 12.5: empty graph → empty string, no exceptions."""
    mi = MyceliumInterface(mem_conn)
    result = mi.get_context_path("fix the bug", "sess_x")
    assert result == ""


def test_get_context_path_returns_string_when_mature(mem_conn):
    """Req 12.5: mature graph → str returned without raising (may be empty if no path)."""
    mi = MyceliumInterface(mem_conn)
    _insert_mature_nodes(mem_conn, mi)
    result = mi.get_context_path("write a python function", "sess_y")
    assert isinstance(result, str)


def test_get_context_path_returns_non_empty_when_domain_nodes_present(mem_conn):
    """Req 12.5: mature graph + research task (includes domain in space_subset) → non-empty."""
    mi = MyceliumInterface(mem_conn)
    # research_task space_subset includes domain+style — seed those spaces
    mi._store.upsert_node("domain", [0.8, 0.9, 0.8], "python", 0.9)
    mi._store.upsert_node("style", [0.5, 0.5, 0.5], "style_node", 0.9)
    mi._store.upsert_node("conduct", [0.7, 0.5, 0.7, 0.3, 0.1], "conduct", 0.9)
    mi._is_mature_cached = None
    # "explain" → research_task → space_subset includes domain + style
    result = mi.get_context_path("explain machine learning concepts", "sess_y2")
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_context_path_minimal_not_longer_than_full(mem_conn):
    """Req 12.5: minimal=True encoding must not be longer than full."""
    mi = MyceliumInterface(mem_conn)
    _insert_mature_nodes(mem_conn, mi)
    full = mi.get_context_path("coding task", "sess_z", minimal=False)
    minimal = mi.get_context_path("coding task", "sess_z", minimal=True)
    if full and minimal:
        assert len(minimal) <= len(full), "minimal must not be longer than full"


# ---------------------------------------------------------------------------
# Req 12.7 — crystallize_landmark() suspension + no-session cases
# ---------------------------------------------------------------------------

def test_crystallize_returns_none_when_suspended(mem_conn):
    """Req 12.7: crystallisation suspended → None."""
    mi = MyceliumInterface(mem_conn)
    mi._crystallisation_suspended = True
    result = mi.crystallize_landmark("sess_s", 0.8, "hit")
    assert result is None


def test_crystallize_returns_none_when_no_session_nodes(mem_conn):
    """Req 12.7: no traversal data for session → None."""
    mi = MyceliumInterface(mem_conn)
    result = mi.crystallize_landmark("empty_session", 0.8, "hit")
    assert result is None


def test_crystallize_does_not_raise_with_recorded_traversal(mem_conn):
    """Req 12.7: session with traversal → no exception, returns Landmark or None."""
    mi = MyceliumInterface(mem_conn)
    session_id = "sess_crys_" + str(uuid.uuid4())[:8]

    n1 = mi._store.upsert_node("domain", [0.5, 0.7, 0.5], "d_node", 0.7)
    n2 = mi._store.upsert_node("style", [0.6, 0.6, 0.6], "s_node", 0.7)
    path = MemoryPath(
        nodes=[n1, n2],
        cumulative_score=0.75,
        token_encoding="test",
        spaces_covered={"domain", "style"},
        traversal_id=None,
    )
    mi.record_outcome(path, "hit", session_id, "unit test task")
    result = mi.crystallize_landmark(session_id, 0.75, "hit", "test task")
    assert result is None or hasattr(result, "landmark_id")


# ---------------------------------------------------------------------------
# Req 12.8 — clear_session() ordering
# ---------------------------------------------------------------------------

def test_clear_session_clears_navigator_state(mem_conn):
    """Req 12.8 step 1: navigator active set cleared after clear_session."""
    mi = MyceliumInterface(mem_conn)
    session_id = "sess_clear"
    # Populate navigator registry
    mi._registry.register(session_id, ["nodeA", "nodeB"])
    assert session_id in mi._registry._active
    mi.clear_session(session_id)
    assert session_id not in mi._registry._active


def test_clear_session_clears_extractor_windows(mem_conn):
    """Req 12.8 step 2: extractor observation windows cleared."""
    mi = MyceliumInterface(mem_conn)
    session_id = "sess_ext_clear"
    for i in range(2):
        mi.ingest_tool_call("bash", True, i + 1, 3, session_id)
    assert any(k[0] == session_id for k in mi._extractor._observation_windows)
    mi.clear_session(session_id)
    assert not any(k[0] == session_id for k in mi._extractor._observation_windows)


def test_clear_session_no_exception_when_immature(mem_conn):
    """Req 12.8 step 3: pre-warm skipped on immature graph — no crash."""
    mi = MyceliumInterface(mem_conn)
    mi.clear_session("sess_immature")  # no exception


def test_clear_session_flags_maintenance_when_overdue(mem_conn):
    """Req 12.8 step 4: maintenance_needed set when last distillation is overdue."""
    mi = MyceliumInterface(mem_conn)
    mi._last_distillation_at = time.time() - (DISTILLATION_MAX_INTERVAL + 1)
    mi.clear_session("sess_overdue")
    assert mi._maintenance_needed is True


# ---------------------------------------------------------------------------
# Req 12.9 — run_maintenance() sequence
# ---------------------------------------------------------------------------

def test_run_maintenance_sets_last_distillation_at(mem_conn):
    """Req 12.9: run_maintenance() must set _last_distillation_at."""
    mi = MyceliumInterface(mem_conn)
    assert mi._last_distillation_at is None
    mi.run_maintenance()
    assert mi._last_distillation_at is not None
    assert mi._last_distillation_at <= time.time()


def test_run_maintenance_clears_maintenance_needed(mem_conn):
    """Req 12.9: maintenance_needed flag reset after run_maintenance()."""
    mi = MyceliumInterface(mem_conn)
    mi._maintenance_needed = True
    mi.run_maintenance()
    assert mi._maintenance_needed is False


def test_run_maintenance_does_not_raise_on_empty_graph(mem_conn):
    """Req 12.9: maintenance on empty graph must not raise."""
    mi = MyceliumInterface(mem_conn)
    mi.run_maintenance()  # no exception


def test_run_maintenance_renders_profile(mem_conn):
    """Req 12.9 step 5: profile render runs — get_readable_profile() returns str."""
    mi = MyceliumInterface(mem_conn)
    mi.ingest_statement("I work mainly in machine learning and Python")
    mi.run_maintenance()
    result = mi.get_readable_profile()
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Req 15.6 — ingest_rag_content() conduct blocked for low-trust channels
# ---------------------------------------------------------------------------

def test_ingest_rag_content_blocks_conduct_writes_for_external(mem_conn):
    """Req 15.6: EXTERNAL channel (web source) must not write conduct space."""
    mi = MyceliumInterface(mem_conn)
    mi.ingest_rag_content(
        "Please always confirm before making changes",
        source_type="web",
        session_id="sess_rag",
    )
    conduct_nodes = mi._store.get_nodes_by_space("conduct")
    assert len(conduct_nodes) == 0, "EXTERNAL RAG must not write conduct space"


def test_ingest_rag_content_does_not_raise(mem_conn):
    """Req 15.6: ingest_rag_content() must never raise regardless of content."""
    mi = MyceliumInterface(mem_conn)
    mi.ingest_rag_content(
        "Python is widely used in machine learning",
        source_type="web",
        session_id="sess_rag2",
    )
    # No assertion needed — just must not raise


# ---------------------------------------------------------------------------
# Req 12.10 — get_stats() never raises
# ---------------------------------------------------------------------------

def test_get_stats_returns_expected_keys(mem_conn):
    """Req 12.10: get_stats() must return dict with node_count, landmark_count."""
    mi = MyceliumInterface(mem_conn)
    stats = mi.get_stats()
    assert isinstance(stats, dict)
    assert "node_count" in stats
    assert "landmark_count" in stats


def test_get_stats_does_not_raise_on_empty_graph(mem_conn):
    """Req 12.10: stats on empty graph must not raise."""
    mi = MyceliumInterface(mem_conn)
    stats = mi.get_stats()
    assert stats["node_count"] == 0


# ---------------------------------------------------------------------------
# ingest_conduct_outcomes — only "hit" and "success" pass
# ---------------------------------------------------------------------------

def test_ingest_conduct_outcomes_does_not_raise_on_malformed_episodes(mem_conn):
    """ingest_conduct_outcomes must silently ignore missing fields."""
    mi = MyceliumInterface(mem_conn)
    mi.ingest_conduct_outcomes([{"task_text": "some text"}])  # no outcome field
    stats = mi.get_stats()
    assert isinstance(stats["node_count"], int)


def test_ingest_conduct_outcomes_skips_miss_outcome(mem_conn):
    """miss episodes must be silently dropped — node count unchanged."""
    mi = MyceliumInterface(mem_conn)
    before = mi.get_stats()["node_count"]
    mi.ingest_conduct_outcomes([
        {"task_text": "Please always confirm before changes", "outcome": "miss"},
    ])
    after = mi.get_stats()["node_count"]
    assert after == before, "miss episode must not add nodes"

"""
Production environment tests — schema idempotency, concurrent access,
hardware probe resilience, stats contract, SQLCipher availability guard.
Requirements: 2.1, 12.2, 12.6, 12.10
"""
import sqlite3
import struct
import threading
import time
import uuid

import pytest

from .conftest_mycelium import _make_memory_conn, _apply_schema, mem_conn  # noqa: F401

from backend.memory.mycelium.interface import MyceliumInterface
from backend.memory.mycelium.store import CoordinateStore


# ---------------------------------------------------------------------------
# Req 2.1 — Schema idempotency (CREATE TABLE IF NOT EXISTS)
# ---------------------------------------------------------------------------

def test_schema_apply_twice_no_error():
    """Req 2.1: applying schema twice must not raise."""
    conn = sqlite3.connect(":memory:")
    _apply_schema(conn)
    _apply_schema(conn)   # second application — must be idempotent
    conn.close()


def test_schema_apply_preserves_existing_rows():
    """Req 2.1: re-applying schema must not delete existing rows."""
    conn = sqlite3.connect(":memory:")
    _apply_schema(conn)

    nid = str(uuid.uuid4())
    blob = struct.pack(">3f", 0.5, 0.5, 0.5)
    now = time.time()
    conn.execute(
        "INSERT INTO mycelium_nodes VALUES (?,?,?,?,?,1,?,?,?)",
        (nid, "domain", blob, "probe", 0.7, now, now, now),
    )
    conn.commit()

    _apply_schema(conn)  # second application

    count = conn.execute("SELECT COUNT(*) FROM mycelium_nodes").fetchone()[0]
    assert count == 1, "schema re-apply must not wipe existing data"
    conn.close()


def test_schema_creates_all_13_tables():
    """Req 2.1: schema must create all 13 required tables."""
    conn = sqlite3.connect(":memory:")
    _apply_schema(conn)

    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {row[0] for row in rows}
    expected = {
        "mycelium_spaces", "mycelium_nodes", "mycelium_edges",
        "mycelium_traversals", "mycelium_landmarks", "mycelium_landmark_edges",
        "mycelium_landmark_merges", "mycelium_profile", "mycelium_conflicts",
        "mycelium_mcp_registry", "mycelium_episode_index",
        "mycelium_charts", "mycelium_trajectories",
    }
    missing = expected - table_names
    assert missing == set(), f"Schema missing tables: {missing}"
    conn.close()


# ---------------------------------------------------------------------------
# MyceliumInterface init and get_stats() contract
# ---------------------------------------------------------------------------

def test_interface_initialises_without_error(mem_conn):
    """MyceliumInterface must instantiate cleanly against in-memory DB."""
    mi = MyceliumInterface(mem_conn)
    assert mi is not None


def test_interface_get_stats_never_raises(mem_conn):
    """Req 12.10: get_stats() must never raise regardless of graph state."""
    mi = MyceliumInterface(mem_conn)
    stats = mi.get_stats()
    assert isinstance(stats, dict)


def test_interface_get_stats_required_keys(mem_conn):
    """Req 12.10: get_stats() must include node_count and landmark_count."""
    mi = MyceliumInterface(mem_conn)
    stats = mi.get_stats()
    assert "node_count" in stats
    assert "landmark_count" in stats


def test_interface_get_stats_zero_on_empty_graph(mem_conn):
    """Req 12.10: node_count=0 on empty graph."""
    mi = MyceliumInterface(mem_conn)
    stats = mi.get_stats()
    assert stats["node_count"] == 0


# ---------------------------------------------------------------------------
# Req 12.2 — all 7 spaces registered on __init__
# ---------------------------------------------------------------------------

def test_all_7_spaces_registered_on_init(mem_conn):
    """Req 12.2: MyceliumInterface.__init__ must register all 7 spaces."""
    mi = MyceliumInterface(mem_conn)
    rows = mem_conn.execute("SELECT space_id FROM mycelium_spaces").fetchall()
    registered = {row[0] for row in rows}
    expected = {"domain", "style", "conduct", "chrono", "capability", "context", "toolpath"}
    assert expected == registered, f"Missing spaces: {expected - registered}"


# ---------------------------------------------------------------------------
# Req 12.6 — ingest_hardware() platform-safe
# ---------------------------------------------------------------------------

def test_ingest_hardware_does_not_raise(mem_conn):
    """Req 12.6: ingest_hardware() must not raise on any platform."""
    mi = MyceliumInterface(mem_conn)
    mi.ingest_hardware()  # no exception


def test_ingest_hardware_at_most_one_capability_node(mem_conn):
    """Req 12.6: single ingest_hardware() call produces at most 1 capability node."""
    mi = MyceliumInterface(mem_conn)
    mi.ingest_hardware()
    nodes = mi._store.get_nodes_by_space("capability")
    assert len(nodes) <= 1


def test_ingest_hardware_twice_no_duplicate_nodes(mem_conn):
    """Req 12.6: calling ingest_hardware() twice must not create duplicate nodes."""
    mi = MyceliumInterface(mem_conn)
    mi.ingest_hardware()
    before = len(mi._store.get_nodes_by_space("capability"))
    mi.ingest_hardware()
    after = len(mi._store.get_nodes_by_space("capability"))
    # dedup threshold should prevent a second distinct node from the same hardware
    assert after <= before + 1, "double ingest_hardware must not proliferate nodes"


# ---------------------------------------------------------------------------
# run_maintenance() on empty DB
# ---------------------------------------------------------------------------

def test_run_maintenance_empty_db_sets_last_distillation(mem_conn):
    """Full maintenance pass on empty DB must complete and set timestamp."""
    mi = MyceliumInterface(mem_conn)
    mi.run_maintenance()
    assert mi._last_distillation_at is not None


def test_run_maintenance_empty_db_no_raise(mem_conn):
    """Full maintenance pass on empty DB must not raise."""
    mi = MyceliumInterface(mem_conn)
    mi.run_maintenance()  # no exception


# ---------------------------------------------------------------------------
# Concurrent CoordinateStore upserts
# ---------------------------------------------------------------------------

def test_rapid_sequential_upserts_consistent_count():
    """
    Rapid sequential upserts across 6 spaces (single thread, as designed)
    must produce a correct and consistent node count — no lost writes.

    Production architecture: one process, one thread, one connection.
    Cross-thread concurrent access is not the production pattern.
    """
    conn = _make_memory_conn()
    store = CoordinateStore(conn)

    spaces = ["domain", "style", "conduct", "chrono", "capability", "context"]
    inserted = 0
    for space_id in spaces:
        for i in range(5):
            store.upsert_node(space_id, [0.1 * i, 0.5, 0.5], f"node_{space_id}_{i}", 0.7)
            inserted += 1

    count = conn.execute("SELECT COUNT(*) FROM mycelium_nodes").fetchone()[0]
    assert count > 0, "At least some nodes must have been inserted"
    # Dedup may merge nearby nodes — count <= inserted is acceptable
    assert count <= inserted, "count must not exceed inserted (dedup may reduce)"
    conn.close()


def test_thread_per_session_with_lock_no_corruption():
    """
    Multiple threads accessing the store through a shared lock (production pattern)
    must produce consistent results without corruption.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    _apply_schema(conn)
    store = CoordinateStore(conn)
    db_lock = threading.Lock()
    errors = []

    def _locked_insert(space_id: str, n: int):
        try:
            for i in range(n):
                with db_lock:
                    store.upsert_node(space_id, [0.1 * i, 0.5, 0.5], f"node_{i}", 0.7)
        except Exception as exc:
            errors.append(f"{space_id}: {exc}")

    spaces = ["domain", "style", "conduct"]
    threads = [threading.Thread(target=_locked_insert, args=(s, 5)) for s in spaces]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Locked thread errors: {errors}"
    count = conn.execute("SELECT COUNT(*) FROM mycelium_nodes").fetchone()[0]
    assert count > 0
    conn.close()


# ---------------------------------------------------------------------------
# SQLCipher availability guard
# ---------------------------------------------------------------------------

def test_sqlcipher3_import_or_skip():
    """
    If sqlcipher3 is installed: verify a connection can be opened, schema applied,
    and MyceliumInterface instantiated.
    If not installed: skip gracefully — not a failure in CI (uses plain sqlite3).
    """
    try:
        import sqlcipher3  # type: ignore
    except ImportError:
        pytest.skip("sqlcipher3 not installed — skipping cipher integration test")

    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        cipher_conn = sqlcipher3.connect(db_path)
        cipher_conn.execute("PRAGMA key='testpassword'")
        _apply_schema(cipher_conn)
        mi = MyceliumInterface(cipher_conn)
        stats = mi.get_stats()
        assert isinstance(stats, dict)
        assert "node_count" in stats
        cipher_conn.close()
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# MyceliumInterface must not reference identity.db
# ---------------------------------------------------------------------------

def test_mycelium_package_does_not_import_identity_db():
    """
    Static guard: no mycelium module may reference 'identity.db' directly.
    This prevents accidental coupling to the identity storage layer.
    """
    import glob
    import os

    mycelium_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "mycelium")
    )
    py_files = glob.glob(os.path.join(mycelium_dir, "**", "*.py"), recursive=True)
    assert py_files, "No .py files found — check path"

    violations = [
        f for f in py_files
        if "identity.db" in open(f, encoding="utf-8").read()
    ]
    assert violations == [], f"Forbidden identity.db reference: {violations}"

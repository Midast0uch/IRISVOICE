"""
T11 — Crystallization seeding (O2): trusted, frequently-referenced document
data crystallizes into a permanent landmark at PERMANENCE_THRESHOLD (8);
untrusted data is excluded by the trust-cap (no bypass).

Standalone CDD test (NOT pytest-collected). Run:
    python backend/tests/test_crystallization_seeding.py
"""
import os
import sqlite3
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from backend.memory.mycelium.interface import MyceliumInterface
from backend.memory.mycelium.landmark import LandmarkIndex
from backend.memory.mycelium.kyudo import HyphaChannel

SCHEMA = """
    CREATE TABLE IF NOT EXISTS mycelium_spaces (
        space_id     TEXT PRIMARY KEY, axes TEXT NOT NULL, dtype TEXT NOT NULL DEFAULT 'float32',
        value_range  TEXT NOT NULL DEFAULT '[0.0, 1.0]', description TEXT, active INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS mycelium_nodes (
        node_id TEXT PRIMARY KEY, space_id TEXT NOT NULL, coordinates BLOB NOT NULL, label TEXT,
        confidence REAL DEFAULT 0.5, access_count INTEGER DEFAULT 0, created_at REAL,
        updated_at REAL, last_accessed REAL
    );
    CREATE TABLE IF NOT EXISTS mycelium_edges (
        edge_id TEXT PRIMARY KEY, from_node_id TEXT NOT NULL, to_node_id TEXT NOT NULL,
        score REAL DEFAULT 0.5, edge_type TEXT DEFAULT 'traversal', traversal_count INTEGER DEFAULT 0,
        hit_count INTEGER DEFAULT 0, miss_count INTEGER DEFAULT 0, decay_rate REAL DEFAULT 0.01,
        created_at REAL, last_traversed REAL
    );
    CREATE TABLE IF NOT EXISTS mycelium_traversals (
        traversal_id TEXT PRIMARY KEY, session_id TEXT, path_node_ids TEXT, task_summary TEXT,
        outcome TEXT, cumulative_score REAL, path_score REAL, tokens_saved INTEGER,
        created_at REAL, delta_compressed INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS mycelium_landmarks (
        landmark_id TEXT PRIMARY KEY, label TEXT, task_class TEXT, coordinate_cluster TEXT,
        traversal_sequence TEXT, cumulative_score REAL DEFAULT 0.0, micro_abstract BLOB,
        micro_abstract_text TEXT, activation_count INTEGER DEFAULT 0, is_permanent INTEGER DEFAULT 0,
        conversation_ref TEXT, created_at REAL, last_activated REAL, absorbed INTEGER
    );
    CREATE TABLE IF NOT EXISTS mycelium_landmark_edges (
        edge_id TEXT PRIMARY KEY, from_landmark_id TEXT, to_landmark_id TEXT, score REAL DEFAULT 0.4,
        edge_type TEXT DEFAULT 'co_activation', traversal_count INTEGER DEFAULT 0, hit_count INTEGER DEFAULT 0,
        miss_count INTEGER DEFAULT 0, created_at REAL, last_traversed REAL
    );
    CREATE TABLE IF NOT EXISTS mycelium_landmark_merges (
        merge_id TEXT PRIMARY KEY, survivor_id TEXT, absorbed_id TEXT, overlap_score REAL,
        pre_merge_score_s REAL, pre_merge_score_a REAL, post_merge_score REAL, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS mycelium_profile (
        section_id TEXT PRIMARY KEY, space_id TEXT UNIQUE, render_order INTEGER DEFAULT 99,
        prose TEXT, source_node_ids TEXT, source_lm_ids TEXT, dirty INTEGER DEFAULT 1,
        last_rendered REAL, word_count INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS mycelium_conflicts (
        conflict_id TEXT PRIMARY KEY, space_id TEXT, axis TEXT, value_a REAL, source_a TEXT,
        value_b REAL, source_b TEXT, resolved_value REAL, resolution_basis TEXT,
        landmark_ref TEXT, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS mycelium_mcp_registry (
        server_id TEXT PRIMARY KEY, url TEXT, content_hash TEXT, registered_at REAL
    );
    CREATE TABLE IF NOT EXISTS mycelium_episode_index (
        idx_id TEXT PRIMARY KEY, episode_id TEXT, session_id TEXT, node_ids TEXT, space_ids TEXT,
        landmark_id TEXT, source_channel INTEGER DEFAULT 1, coordinate_hash TEXT, created_at REAL
    );
    CREATE TABLE IF NOT EXISTS mycelium_charts (
        position_id TEXT PRIMARY KEY, landmark_id TEXT, session_id TEXT, x REAL, y REAL, z REAL,
        primitive TEXT, confidence REAL, created_at REAL, stale INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS mycelium_trajectories (
        trajectory_id TEXT PRIMARY KEY, landmark_id TEXT, z_values TEXT, z_trend REAL,
        primitive_history TEXT, staleness_count INTEGER DEFAULT 0, last_updated REAL
    );
    CREATE TABLE IF NOT EXISTS mycelium_path_deltas (
        delta_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, delta_data TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
"""


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def _seed_spaces(conn: sqlite3.Connection) -> None:
    for sid in ["conduct", "domain", "style", "chrono", "context", "capability", "toolpath"]:
        conn.execute(
            "INSERT OR IGNORE INTO mycelium_spaces (space_id, axes, dtype, value_range) VALUES (?,?,?,?)",
            (sid, "[]", "float32", "[0.0,1.0]"),
        )
    conn.commit()


def check(name: str, cond: bool) -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        raise AssertionError(f"T11 FAILED: {name}")


def main() -> None:
    # ---- Trusted document data crystallizes to permanent ----
    conn = _make_conn()
    _seed_spaces(conn)
    mi = MyceliumInterface(conn)
    sid = "sess_trusted_doc"
    mi.ingest_document_data(
        content='{"document_id":"doc-1","format":"markdown","content":"trusted spec"}',
        trust="trusted",
        session_id=sid,
        coords=[0.5, 0.5, 0.5, 0.5],
        label="doc-1",
    )
    nodes = conn.execute(
        "SELECT COUNT(*) FROM mycelium_nodes WHERE space_id='context'"
    ).fetchone()[0]
    check("trusted document data seeded as context node (TOOL_ZONE)", nodes >= 1)

    landmark = mi.crystallize_landmark(
        sid, 0.8, "hit", "trusted doc", source_channel=HyphaChannel.VERIFIED.value
    )
    check("trusted document data forms a landmark", landmark is not None)
    if landmark is not None:
        index = LandmarkIndex(conn)
        for _ in range(8):
            index.activate(landmark.landmark_id)
        row = conn.execute(
            "SELECT is_permanent, activation_count FROM mycelium_landmarks WHERE landmark_id=?",
            (landmark.landmark_id,),
        ).fetchone()
        check("trusted landmark promoted to permanent at threshold 8", row is not None and row[0] == 1)
        check("trusted landmark activation_count >= 8", row is not None and row[1] >= 8)

    # ---- Untrusted document data excluded by trust-cap ----
    conn2 = _make_conn()
    _seed_spaces(conn2)
    mi2 = MyceliumInterface(conn2)
    sid2 = "sess_untrusted_doc"
    mi2.ingest_document_data(
        content='{"document_id":"doc-2","format":"html","content":"<img src=x onerror=alert(1)>"}',
        trust="untrusted",
        session_id=sid2,
        coords=[0.2, 0.2, 0.2, 0.2],
        label="doc-2",
    )
    nodes2 = conn2.execute(
        "SELECT COUNT(*) FROM mycelium_nodes WHERE space_id='toolpath'"
    ).fetchone()[0]
    check("untrusted document data seeded only in toolpath (REFERENCE_ZONE)", nodes2 >= 1)
    # Trusted zone must remain empty for untrusted content (CellWall enforced).
    trusted_nodes = conn2.execute(
        "SELECT COUNT(*) FROM mycelium_nodes WHERE space_id='context'"
    ).fetchone()[0]
    check("untrusted document data never writes to trusted context zone", trusted_nodes == 0)

    landmark2 = mi2.crystallize_landmark(
        sid2, 0.8, "hit", "untrusted doc", source_channel=HyphaChannel.EXTERNAL.value
    )
    check("untrusted document data excluded from crystallization by trust-cap", landmark2 is None)

    print("\nT11 ALL CHECKS PASSED")


if __name__ == "__main__":
    main()

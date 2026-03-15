"""
Shared fixtures for Mycelium unit tests.

Uses plain sqlite3 (unencrypted :memory:) so tests never require sqlcipher3.
The full schema is applied via initialise_mycelium_schema() against a patched
connection that accepts plain sqlite3.
"""

import sqlite3
import pytest

# ---------------------------------------------------------------------------
# Minimal shim so schema SQL that targets sqlite3 works without sqlcipher3
# ---------------------------------------------------------------------------


def _make_memory_conn() -> sqlite3.Connection:
    """Return an in-memory sqlite3 connection with the Mycelium schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    _apply_schema(conn)
    return conn


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Apply the full Mycelium schema (copied from db.initialise_mycelium_schema)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mycelium_spaces (
            space_id     TEXT PRIMARY KEY,
            axes         TEXT NOT NULL,
            dtype        TEXT NOT NULL DEFAULT 'float32',
            value_range  TEXT NOT NULL DEFAULT '[0.0, 1.0]',
            description  TEXT,
            active       INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS mycelium_nodes (
            node_id      TEXT PRIMARY KEY,
            space_id     TEXT NOT NULL,
            coordinates  BLOB NOT NULL,
            label        TEXT,
            confidence   REAL DEFAULT 0.5,
            access_count INTEGER DEFAULT 0,
            created_at   REAL,
            updated_at   REAL,
            last_accessed REAL
        );

        CREATE TABLE IF NOT EXISTS mycelium_edges (
            edge_id       TEXT PRIMARY KEY,
            from_node_id  TEXT NOT NULL,
            to_node_id    TEXT NOT NULL,
            score         REAL DEFAULT 0.5,
            edge_type     TEXT DEFAULT 'traversal',
            traversal_count INTEGER DEFAULT 0,
            hit_count     INTEGER DEFAULT 0,
            miss_count    INTEGER DEFAULT 0,
            decay_rate    REAL DEFAULT 0.01,
            created_at    REAL,
            last_traversed REAL
        );

        CREATE TABLE IF NOT EXISTS mycelium_traversals (
            traversal_id  TEXT PRIMARY KEY,
            session_id    TEXT,
            path_node_ids TEXT,
            task_summary  TEXT,
            outcome       TEXT,
            cumulative_score REAL,
            created_at    REAL
        );

        CREATE TABLE IF NOT EXISTS mycelium_landmarks (
            landmark_id        TEXT PRIMARY KEY,
            label              TEXT,
            task_class         TEXT,
            coordinate_cluster TEXT,
            traversal_sequence TEXT,
            cumulative_score   REAL DEFAULT 0.0,
            micro_abstract     BLOB,
            micro_abstract_text TEXT,
            activation_count   INTEGER DEFAULT 0,
            is_permanent       INTEGER DEFAULT 0,
            conversation_ref   TEXT,
            created_at         REAL,
            last_activated     REAL,
            absorbed           INTEGER
        );

        CREATE TABLE IF NOT EXISTS mycelium_landmark_edges (
            edge_id           TEXT PRIMARY KEY,
            from_landmark_id  TEXT,
            to_landmark_id    TEXT,
            score             REAL DEFAULT 0.4,
            created_at        REAL,
            last_traversed    REAL
        );

        CREATE TABLE IF NOT EXISTS mycelium_landmark_merges (
            merge_id          TEXT PRIMARY KEY,
            survivor_id       TEXT,
            absorbed_id       TEXT,
            overlap_score     REAL,
            pre_merge_score_s REAL,
            pre_merge_score_a REAL,
            post_merge_score  REAL,
            created_at        REAL
        );

        CREATE TABLE IF NOT EXISTS mycelium_profile (
            section_id      TEXT PRIMARY KEY,
            space_id        TEXT UNIQUE,
            render_order    INTEGER DEFAULT 99,
            prose           TEXT,
            source_node_ids TEXT,
            source_lm_ids   TEXT,
            dirty           INTEGER DEFAULT 1,
            last_rendered   REAL,
            word_count      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS mycelium_conflicts (
            conflict_id      TEXT PRIMARY KEY,
            space_id         TEXT,
            axis             TEXT,
            value_a          REAL,
            source_a         TEXT,
            value_b          REAL,
            source_b         TEXT,
            resolved_value   REAL,
            resolution_basis TEXT,
            landmark_ref     TEXT,
            created_at       REAL
        );

        CREATE TABLE IF NOT EXISTS mycelium_mcp_registry (
            server_id     TEXT PRIMARY KEY,
            url           TEXT,
            content_hash  TEXT,
            registered_at REAL
        );

        CREATE TABLE IF NOT EXISTS mycelium_episode_index (
            idx_id          TEXT PRIMARY KEY,
            episode_id      TEXT,
            session_id      TEXT,
            node_ids        TEXT,
            space_ids       TEXT,
            landmark_id     TEXT,
            source_channel  INTEGER DEFAULT 1,
            coordinate_hash TEXT,
            created_at      REAL
        );

        CREATE TABLE IF NOT EXISTS mycelium_charts (
            position_id  TEXT PRIMARY KEY,
            landmark_id  TEXT,
            session_id   TEXT,
            x            REAL,
            y            REAL,
            z            REAL,
            primitive    TEXT,
            confidence   REAL,
            created_at   REAL,
            stale        INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS mycelium_trajectories (
            trajectory_id     TEXT PRIMARY KEY,
            landmark_id       TEXT,
            z_values          TEXT,
            z_trend           REAL,
            primitive_history TEXT,
            staleness_count   INTEGER DEFAULT 0,
            last_updated      REAL
        );

        CREATE TABLE IF NOT EXISTS mycelium_path_deltas (
            delta_id   TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            delta_data TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()


@pytest.fixture
def mem_conn() -> sqlite3.Connection:
    """In-memory sqlite3 connection with full Mycelium schema."""
    conn = _make_memory_conn()
    yield conn
    conn.close()

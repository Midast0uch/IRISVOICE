"""
Database utilities for IRIS Memory Foundation.

Provides encrypted SQLite connections via SQLCipher.
All memory access goes through this module — never raw sqlite3.connect().

Dev-mode fallback: when sqlcipher3 is not available (e.g. Windows + Python 3.13
where no pre-built wheel exists), the module falls back to plain sqlite3 with a
WARNING. The connection interface is identical — only the at-rest encryption is
absent. Set IRIS_MEMORY_ENCRYPTION=1 to force an error instead of falling back.
"""

import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Suppress repeated sqlcipher3 fallback warnings — only warn once per process.
_sqlcipher_warned: bool = False

# Default configuration values
DEFAULT_CIPHER_PAGE_SIZE = 4096
DEFAULT_KDF_ITERATIONS = 64000

# Set IRIS_MEMORY_ENCRYPTION=1 to disable fallback and require sqlcipher3.
_REQUIRE_ENCRYPTION = os.environ.get("IRIS_MEMORY_ENCRYPTION", "0") == "1"


def open_encrypted_memory(db_path: str, biometric_key: bytes):
    """
    Opens the memory database, preferring SQLCipher AES-256 encryption.

    Falls back to plain sqlite3 when sqlcipher3 is not installed and
    IRIS_MEMORY_ENCRYPTION is not set to '1'. The connection interface is
    identical in both cases.

    Args:
        db_path: Path to the database file (e.g., "data/memory.db")
        biometric_key: 32-byte key derived from platform biometric API at app startup.
                      Unused in fallback mode (no encryption key applied).

    Returns:
        Connection: Configured sqlite connection (sqlcipher3 or sqlite3)

    Raises:
        ImportError: If sqlcipher3 is not installed and IRIS_MEMORY_ENCRYPTION=1
        RuntimeError: If database cannot be opened or configured
    """
    # Ensure parent directory exists
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    # Try sqlcipher3 first
    try:
        import sqlcipher3 as _sqlcipher3
        conn = _sqlcipher3.connect(str(db_path))
        try:
            key_hex = biometric_key.hex()
            conn.execute(f"PRAGMA key='{key_hex}'")
            conn.execute(f"PRAGMA cipher_page_size={DEFAULT_CIPHER_PAGE_SIZE}")
            conn.execute(f"PRAGMA kdf_iter={DEFAULT_KDF_ITERATIONS}")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("SELECT count(*) FROM sqlite_master")
            logger.info(f"[db] Opened encrypted memory database: {db_path}")
            return conn
        except Exception as e:
            conn.close()
            logger.error(f"[db] Failed to configure encrypted database: {e}")
            raise RuntimeError(f"Failed to open encrypted memory database: {e}") from e

    except ImportError:
        if _REQUIRE_ENCRYPTION:
            raise ImportError(
                "sqlcipher3 not installed and IRIS_MEMORY_ENCRYPTION=1. "
                "See docs/MEMORY_SETUP.md for platform-specific instructions."
            )
        global _sqlcipher_warned
        if not _sqlcipher_warned:
            _sqlcipher_warned = True
            logger.warning(
                "[db] sqlcipher3 not available — falling back to unencrypted sqlite3. "
                "Memory data is NOT encrypted at rest. "
                "To suppress: install sqlcipher3. "
                "To require encryption: set IRIS_MEMORY_ENCRYPTION=1."
            )
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("SELECT count(*) FROM sqlite_master")
        logger.info(f"[db] Opened unencrypted (dev) memory database: {db_path}")
        return conn


def verify_encryption(conn: "sqlcipher3.Connection") -> bool:
    """
    Verify that the database connection is properly encrypted.
    
    This is a test function that attempts to verify encryption is active.
    It should be called once after opening the database.
    
    Args:
        conn: SQLCipher connection to verify
    
    Returns:
        True if encryption is verified, False otherwise
    """
    try:
        # Attempt to read the cipher settings
        cursor = conn.execute("PRAGMA cipher_page_size")
        page_size = cursor.fetchone()[0]
        
        cursor = conn.execute("PRAGMA kdf_iter")
        kdf_iter = cursor.fetchone()[0]
        
        logger.debug(f"[db] Encryption verified: page_size={page_size}, kdf_iter={kdf_iter}")
        return True
        
    except Exception as e:
        logger.warning(f"[db] Could not verify encryption settings: {e}")
        return False


def is_sqlcipher_available() -> bool:
    """
    Check if sqlcipher3 is available without importing it.
    
    Returns:
        True if sqlcipher3 can be imported, False otherwise
    """
    try:
        import sqlcipher3
        return True
    except ImportError:
        return False


# Type alias — accepts either sqlcipher3.Connection or sqlite3.Connection
from typing import Union
Connection = Union["sqlcipher3.Connection", "sqlite3.Connection"]


def initialise_mycelium_schema(conn) -> None:
    """
    Create all Mycelium coordinate-graph tables and indexes in the encrypted database.

    Safe to call on every startup — all statements use IF NOT EXISTS.
    Must be called AFTER the existing v1.5 schema is initialised (episodic, semantic tables).
    Topology tables (mycelium_charts, mycelium_trajectories) are added here as Block 2
    so that FK references to mycelium_landmarks resolve correctly.

    Args:
        conn: Open, authenticated SQLCipher connection to data/memory.db.
              MUST be the shared connection — never open a second connection.
    """
    logger.info("[db] Initialising Mycelium schema (v1.5 + Topology v2.0)")

    # -------------------------------------------------------------------------
    # Block 1 — Foundation tables (FK order: nodes before edges, landmarks before
    # landmark_edges, etc.)
    # -------------------------------------------------------------------------
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mycelium_nodes (
            node_id       TEXT PRIMARY KEY,
            space_id      TEXT NOT NULL,
            coordinates   BLOB NOT NULL,
            label         TEXT,
            confidence    REAL DEFAULT 0.5,
            created_at    REAL NOT NULL,
            updated_at    REAL NOT NULL,
            access_count  INTEGER DEFAULT 0,
            last_accessed REAL
        );

        CREATE TABLE IF NOT EXISTS mycelium_edges (
            edge_id          TEXT PRIMARY KEY,
            from_node_id     TEXT NOT NULL REFERENCES mycelium_nodes(node_id),
            to_node_id       TEXT NOT NULL REFERENCES mycelium_nodes(node_id),
            score            REAL NOT NULL DEFAULT 0.5,
            edge_type        TEXT NOT NULL,
            traversal_count  INTEGER DEFAULT 0,
            hit_count        INTEGER DEFAULT 0,
            miss_count       INTEGER DEFAULT 0,
            decay_rate       REAL DEFAULT 0.005,
            created_at       REAL NOT NULL,
            last_traversed   REAL,
            UNIQUE(from_node_id, to_node_id)
        );

        CREATE TABLE IF NOT EXISTS mycelium_traversals (
            traversal_id     TEXT PRIMARY KEY,
            session_id       TEXT NOT NULL,
            task_summary     TEXT,
            path_node_ids    TEXT NOT NULL,
            path_score       REAL,
            outcome          TEXT,
            tokens_saved     INTEGER,
            delta_compressed INTEGER DEFAULT 0,
            created_at       REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mycelium_spaces (
            space_id    TEXT PRIMARY KEY,
            axes        TEXT NOT NULL,
            dtype       TEXT NOT NULL,
            value_range TEXT NOT NULL,
            description TEXT,
            active      INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS mycelium_landmarks (
            landmark_id         TEXT PRIMARY KEY,
            label               TEXT,
            task_class          TEXT NOT NULL,
            coordinate_cluster  TEXT NOT NULL,
            traversal_sequence  TEXT NOT NULL,
            cumulative_score    REAL NOT NULL,
            micro_abstract      BLOB,
            micro_abstract_text TEXT,
            activation_count    INTEGER DEFAULT 0,
            is_permanent        INTEGER DEFAULT 0,
            conversation_ref    TEXT,
            absorbed            INTEGER,
            created_at          REAL NOT NULL,
            last_activated      REAL
        );

        CREATE TABLE IF NOT EXISTS mycelium_landmark_edges (
            edge_id            TEXT PRIMARY KEY,
            from_landmark_id   TEXT NOT NULL REFERENCES mycelium_landmarks(landmark_id),
            to_landmark_id     TEXT NOT NULL REFERENCES mycelium_landmarks(landmark_id),
            score              REAL NOT NULL DEFAULT 0.5,
            edge_type          TEXT NOT NULL,
            traversal_count    INTEGER DEFAULT 0,
            hit_count          INTEGER DEFAULT 0,
            miss_count         INTEGER DEFAULT 0,
            created_at         REAL NOT NULL,
            last_traversed     REAL,
            UNIQUE(from_landmark_id, to_landmark_id)
        );

        CREATE TABLE IF NOT EXISTS mycelium_conflicts (
            conflict_id      TEXT PRIMARY KEY,
            space_id         TEXT NOT NULL,
            axis             TEXT NOT NULL,
            value_a          REAL NOT NULL,
            source_a         TEXT NOT NULL,
            value_b          REAL NOT NULL,
            source_b         TEXT NOT NULL,
            resolved_value   REAL NOT NULL,
            resolution_basis TEXT NOT NULL,
            landmark_ref     TEXT,
            created_at       REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mycelium_profile (
            section_id      TEXT PRIMARY KEY,
            space_id        TEXT NOT NULL,
            render_order    INTEGER NOT NULL,
            prose           TEXT NOT NULL,
            source_node_ids TEXT NOT NULL,
            source_lm_ids   TEXT,
            dirty           INTEGER DEFAULT 0,
            last_rendered   REAL NOT NULL,
            word_count      INTEGER
        );

        CREATE TABLE IF NOT EXISTS mycelium_landmark_merges (
            merge_id         TEXT PRIMARY KEY,
            survivor_id      TEXT NOT NULL,
            absorbed_id      TEXT NOT NULL,
            overlap_score    REAL NOT NULL,
            pre_merge_score_s REAL NOT NULL,
            pre_merge_score_a REAL NOT NULL,
            post_merge_score  REAL NOT NULL,
            created_at        REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mycelium_episode_index (
            idx_id           TEXT PRIMARY KEY,
            episode_id       TEXT NOT NULL,
            session_id       TEXT NOT NULL,
            node_ids         TEXT NOT NULL,
            space_ids        TEXT NOT NULL,
            landmark_id      TEXT,
            coordinate_hash  TEXT NOT NULL,
            source_channel   INTEGER,
            created_at       REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mycelium_mcp_registry (
            server_id     TEXT PRIMARY KEY,
            url           TEXT NOT NULL,
            content_hash  TEXT NOT NULL,
            registered_at REAL NOT NULL
        );
    """)

    # -------------------------------------------------------------------------
    # Block 2 — PiN layer + Cross-project landmark bridges
    # PiN = Primordial Information Node: any knowledge artifact anchored to
    # IRIS memory — files, folders, docs, images, decisions, URLs, fragments.
    # -------------------------------------------------------------------------
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mycelium_pins (
            pin_id       TEXT PRIMARY KEY,
            title        TEXT NOT NULL,
            pin_type     TEXT DEFAULT 'note',   -- 'note'|'file'|'folder'|'image'|'doc'|'url'|'decision'|'fragment'
            content      TEXT,                  -- markdown body or description
            tags         TEXT DEFAULT '[]',     -- JSON array
            file_refs    TEXT DEFAULT '[]',     -- JSON array of file/folder paths
            image_refs   TEXT DEFAULT '[]',     -- JSON array of image paths/URLs
            url_refs     TEXT DEFAULT '[]',     -- JSON array of external URLs
            project_id   TEXT,                  -- optional project scope
            origin_id    TEXT,                  -- instance UUID that created this PiN
            created_at   REAL NOT NULL,
            updated_at   REAL NOT NULL,
            is_permanent INTEGER DEFAULT 0      -- 1 = never decays
        );

        CREATE TABLE IF NOT EXISTS mycelium_pin_links (
            link_id      INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type  TEXT NOT NULL,         -- 'pin' | 'landmark' | 'episode' | 'node'
            source_id    TEXT NOT NULL,
            target_type  TEXT NOT NULL,
            target_id    TEXT NOT NULL,
            relationship TEXT NOT NULL,         -- 'documents'|'references'|'implements'|'depends_on'|'contains'|'related_to'
            weight       REAL DEFAULT 1.0,
            created_at   REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mycelium_landmark_bridges (
            bridge_id              TEXT PRIMARY KEY,
            local_landmark_id      TEXT NOT NULL REFERENCES mycelium_landmarks(landmark_id),
            remote_project_id      TEXT,        -- project scope (nullable = global)
            remote_instance_id     TEXT,        -- origin instance UUID
            remote_landmark_name   TEXT NOT NULL,
            remote_landmark_id     TEXT,        -- optional direct landmark ID
            confidence             REAL DEFAULT 1.0,
            bridge_type            TEXT DEFAULT 'equivalent',  -- 'equivalent'|'similar'|'inverse'
            notes                  TEXT,
            created_at             REAL NOT NULL
        );
    """)

    # -------------------------------------------------------------------------
    # Block 3 — Topology v2.0 tables (FK references mycelium_landmarks above)
    # -------------------------------------------------------------------------
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS mycelium_charts (
            position_id  TEXT PRIMARY KEY,
            landmark_id  TEXT NOT NULL REFERENCES mycelium_landmarks(landmark_id),
            session_id   TEXT NOT NULL,
            x            REAL NOT NULL,
            y            REAL NOT NULL,
            z            REAL NOT NULL,
            primitive    TEXT NOT NULL,
            confidence   REAL NOT NULL,
            created_at   REAL NOT NULL,
            stale        INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS mycelium_trajectories (
            trajectory_id     TEXT PRIMARY KEY,
            landmark_id       TEXT NOT NULL UNIQUE REFERENCES mycelium_landmarks(landmark_id),
            z_values          TEXT NOT NULL,
            z_trend           REAL NOT NULL,
            primitive_history TEXT NOT NULL,
            staleness_count   INTEGER DEFAULT 0,
            last_updated      REAL NOT NULL
        );
    """)

    # -------------------------------------------------------------------------
    # All indexes — Foundation + Topology
    # -------------------------------------------------------------------------
    conn.executescript("""
        -- Foundation indexes
        CREATE INDEX IF NOT EXISTS idx_nodes_space
            ON mycelium_nodes(space_id);
        CREATE INDEX IF NOT EXISTS idx_edges_from
            ON mycelium_edges(from_node_id);
        CREATE INDEX IF NOT EXISTS idx_edges_score
            ON mycelium_edges(score DESC);
        CREATE INDEX IF NOT EXISTS idx_traversals_session
            ON mycelium_traversals(session_id);
        CREATE INDEX IF NOT EXISTS idx_landmarks_task_class
            ON mycelium_landmarks(task_class);
        CREATE INDEX IF NOT EXISTS idx_landmarks_score
            ON mycelium_landmarks(cumulative_score DESC);
        CREATE INDEX IF NOT EXISTS idx_landmark_edges_from
            ON mycelium_landmark_edges(from_landmark_id);
        CREATE INDEX IF NOT EXISTS idx_conflicts_space
            ON mycelium_conflicts(space_id);
        CREATE INDEX IF NOT EXISTS idx_profile_space
            ON mycelium_profile(space_id);
        CREATE INDEX IF NOT EXISTS idx_profile_dirty
            ON mycelium_profile(dirty);
        CREATE INDEX IF NOT EXISTS idx_merges_survivor
            ON mycelium_landmark_merges(survivor_id);
        CREATE INDEX IF NOT EXISTS idx_epindex_episode
            ON mycelium_episode_index(episode_id);
        CREATE INDEX IF NOT EXISTS idx_epindex_session
            ON mycelium_episode_index(session_id);
        CREATE INDEX IF NOT EXISTS idx_epindex_landmark
            ON mycelium_episode_index(landmark_id);
        CREATE INDEX IF NOT EXISTS idx_epindex_hash
            ON mycelium_episode_index(coordinate_hash);
        CREATE INDEX IF NOT EXISTS idx_epindex_channel
            ON mycelium_episode_index(source_channel);
        CREATE INDEX IF NOT EXISTS idx_mcp_registry_server
            ON mycelium_mcp_registry(server_id);

        -- Topology v2.0 indexes
        CREATE INDEX IF NOT EXISTS idx_charts_landmark
            ON mycelium_charts(landmark_id);
        CREATE INDEX IF NOT EXISTS idx_charts_session
            ON mycelium_charts(session_id);
        CREATE INDEX IF NOT EXISTS idx_charts_primitive
            ON mycelium_charts(primitive);
        CREATE INDEX IF NOT EXISTS idx_charts_stale
            ON mycelium_charts(stale);
        CREATE INDEX IF NOT EXISTS idx_trajectories_landmark
            ON mycelium_trajectories(landmark_id);

        -- PiN + bridge indexes
        CREATE INDEX IF NOT EXISTS idx_pins_type
            ON mycelium_pins(pin_type);
        CREATE INDEX IF NOT EXISTS idx_pins_origin
            ON mycelium_pins(origin_id);
        CREATE INDEX IF NOT EXISTS idx_pins_project
            ON mycelium_pins(project_id);
        CREATE INDEX IF NOT EXISTS idx_pin_links_source
            ON mycelium_pin_links(source_type, source_id);
        CREATE INDEX IF NOT EXISTS idx_pin_links_target
            ON mycelium_pin_links(target_type, target_id);
        CREATE INDEX IF NOT EXISTS idx_bridges_local
            ON mycelium_landmark_bridges(local_landmark_id);
        CREATE INDEX IF NOT EXISTS idx_bridges_remote
            ON mycelium_landmark_bridges(remote_instance_id);
    """)

    # ── Swarm collaboration tables ────────────────────────────────────────
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS task_collaboration (
            collab_id      TEXT PRIMARY KEY,
            task_id        TEXT NOT NULL,
            session_id     TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'working',
            primary_agent  TEXT NOT NULL,
            helper_agents  TEXT DEFAULT '[]',
            max_helpers    INTEGER DEFAULT 2,
            required_skills TEXT DEFAULT '[]',
            task_summary   TEXT DEFAULT '',
            context_pin_id TEXT,
            created_at     REAL NOT NULL,
            opened_at      REAL,
            completed_at   REAL
        );

        CREATE TABLE IF NOT EXISTS swarm_join_signals (
            signal_id     TEXT PRIMARY KEY,
            collab_id     TEXT NOT NULL REFERENCES task_collaboration(collab_id),
            agent_id      TEXT NOT NULL,
            signal_type   TEXT NOT NULL,
            payload       TEXT DEFAULT '{}',
            created_at    REAL NOT NULL,
            read_by       TEXT DEFAULT '[]'
        );

        CREATE INDEX IF NOT EXISTS idx_collab_task    ON task_collaboration(task_id);
        CREATE INDEX IF NOT EXISTS idx_collab_status  ON task_collaboration(status);
        CREATE INDEX IF NOT EXISTS idx_collab_session ON task_collaboration(session_id);
        CREATE INDEX IF NOT EXISTS idx_signals_collab ON swarm_join_signals(collab_id);
        CREATE INDEX IF NOT EXISTS idx_signals_type   ON swarm_join_signals(signal_type);
    """)

    conn.commit()
    logger.info("[db] Mycelium schema initialised: 18 tables, 36 indexes")

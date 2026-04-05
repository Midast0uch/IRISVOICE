"""
IRIS Bootstrap Coordinate Store
File: IRISVOICE/bootstrap/coordinates.py

Lightweight Mycelium implementation for the bootstrap phase.
Runs without the full IRIS backend. SQLite only. No encryption yet.
The agent calls this directly from terminal via update_coordinates.py.

When Tauri build works and the app is autonomous, coordinates.db
transfers to data/memory.db and the full Mycelium system takes over.
The schema is compatible — no migration needed.
"""

import sqlite3
import json
import time
import uuid
import os
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


# ── Constants ──────────────────────────────────────────────────────────────

COORDINATES_DB = os.path.join(
    os.path.dirname(__file__), "coordinates.db"
)

# Signals directory — sub-agents write completion events here; orchestrator polls
SIGNALS_DIR = os.path.join(os.path.dirname(__file__), "signals")

# Landmark crystallization threshold — how many passing tests before permanent
LANDMARK_THRESHOLD = 3

# Gradient warning decay — sessions before a warning fades if not reinforced
GRADIENT_DECAY_SESSIONS = 10

# Contract formation — how many correction events before a contract forms
CONTRACT_MIN_EVIDENCE = 2

# Node activation threshold — when a file_node reaches this count it is
# crystallization-ready (matches CHART_ACTIVATION_THRESHOLD in the Mycelium spec)
CHART_ACTIVATION_THRESHOLD = 12

# Edge weight bounds for pheromone-trail compounding
EDGE_WEIGHT_MAX = 5.0
EDGE_WEIGHT_MIN = 0.1
EDGE_SUCCESS_FACTOR = 1.10   # weight multiplier on successful traversal
EDGE_FAILURE_FACTOR = 0.85   # weight multiplier on failed traversal

# Minimum score for a failure to be treated as a future-success signal
HIGH_POTENTIAL_FAILURE_THRESHOLD = 0.50

# Decay rates per coordinate space (fraction lost per day without reinforcement)
# Matches the Mycelium spec v1.6 — schema is transfer-compatible with data/memory.db
NODE_DECAY_RATES = {
    "domain":     0.005,   # stable — expertise grows over months
    "conduct":    0.008,   # working habits evolve
    "style":      0.005,   # communication preferences are stable
    "chrono":     0.005,   # active hours are stable lifestyle patterns
    "context":    0.025,   # fastest — stale project context misleads
    "capability": 0.002,   # nearly static — hardware doesn't change
    "toolpath":   0.020,   # 4× faster than profile — habits shift quickly
}

# All 7 coordinate spaces (matches Mycelium spec v1.6)
# Schema is intentionally transfer-compatible: when the Tauri build is complete,
# bootstrap/coordinates.db moves to data/memory.db — no migration needed.
BOOTSTRAP_SPACES = [
    "domain",      # Space 1: intellectual expertise in IRIS architecture
    "conduct",     # Space 2: how the agent works (autonomy, style, depth)
    "style",       # Space 3: communication preference (verbosity, directness)
    "chrono",      # Space 4: temporal activity patterns (session timing)
    "context",     # Space 5: active project and environment
    "capability",  # Space 6: hardware reality (GPU, RAM, OS, tools)
    "toolpath",    # Space 7: behavioral tool habits (freq, success_rate)
]


# ── Schema ─────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS landmarks (
    landmark_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    feature_path    TEXT NOT NULL,     -- file or module that was built
    test_command    TEXT NOT NULL,     -- command that verifies it works
    pass_count      INTEGER DEFAULT 0, -- times this test has passed
    is_permanent    INTEGER DEFAULT 0, -- 1 when pass_count >= LANDMARK_THRESHOLD
    session_number  INTEGER NOT NULL,
    created_at      REAL NOT NULL,
    last_verified   REAL
);

CREATE TABLE IF NOT EXISTS gradient_warnings (
    warning_id      TEXT PRIMARY KEY,
    space           TEXT NOT NULL,     -- which coordinate space this affects
    description     TEXT NOT NULL,     -- what the failure was
    approach        TEXT NOT NULL,     -- what approach was tried
    correction      TEXT,              -- what worked instead (if known)
    session_number  INTEGER NOT NULL,
    reinforced_at   REAL,              -- last time this warning fired
    decay_session   INTEGER,           -- session when this expires
    created_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS contracts (
    contract_id     TEXT PRIMARY KEY,
    rule            TEXT NOT NULL,     -- "when X do Y"
    evidence_count  INTEGER DEFAULT 0,
    confidence      REAL DEFAULT 0.0,
    is_active       INTEGER DEFAULT 1,
    created_at      REAL NOT NULL,
    last_fired      REAL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    session_number  INTEGER NOT NULL,
    objective       TEXT NOT NULL,
    tasks_completed TEXT NOT NULL,     -- JSON array
    landmarks_added TEXT NOT NULL,     -- JSON array of landmark_ids
    warnings_added  TEXT NOT NULL,     -- JSON array of warning_ids
    graph_maturity  TEXT NOT NULL,     -- "immature" | "developing" | "mature"
    domain_confidence REAL DEFAULT 0.0,
    toolpath_confidence REAL DEFAULT 0.0,
    started_at      REAL NOT NULL,
    ended_at        REAL
);

CREATE TABLE IF NOT EXISTS coordinate_path (
    space           TEXT PRIMARY KEY,
    coordinates     TEXT NOT NULL,     -- JSON array of floats
    confidence      REAL DEFAULT 0.0,
    last_updated    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS work_items (
    item_id         TEXT PRIMARY KEY,
    gate            INTEGER NOT NULL,  -- 1, 2, 3, 4
    step            TEXT NOT NULL,     -- "1.1", "1.2" etc.
    description     TEXT NOT NULL,
    spec_file       TEXT NOT NULL,
    test_command    TEXT NOT NULL,
    status          TEXT DEFAULT 'available', -- available | claimed | complete
    claimed_by      TEXT,
    claimed_at      REAL,
    heartbeat_at    REAL,
    completed_at    REAL,
    result          TEXT,              -- success | failure
    landmark_name   TEXT,
    warning_description TEXT
);

CREATE INDEX IF NOT EXISTS idx_landmarks_permanent
    ON landmarks(is_permanent);
CREATE INDEX IF NOT EXISTS idx_warnings_space
    ON gradient_warnings(space);
CREATE INDEX IF NOT EXISTS idx_sessions_number
    ON sessions(session_number);
CREATE INDEX IF NOT EXISTS idx_work_items_status
    ON work_items(status, gate);

-- Every file change, test run, note made by any agent
-- score: signal quality 0.0–1.0; a failure scoring >=0.5 is a future-success candidate
CREATE TABLE IF NOT EXISTS code_events (
    event_id        TEXT PRIMARY KEY,
    session_number  INTEGER NOT NULL,
    agent_id        TEXT NOT NULL,
    event_type      TEXT NOT NULL,  -- 'file_edit' | 'file_create' | 'test_run' | 'git_commit' | 'note'
    file_path       TEXT,
    description     TEXT NOT NULL,
    outcome         TEXT,           -- 'pass' | 'fail' | 'partial' | null
    score           REAL DEFAULT NULL, -- signal quality 0.0-1.0 (NULL = unscored)
    detail          TEXT,           -- JSON blob: test output summary, diff stats, etc.
    landmark_id     TEXT,
    gate            INTEGER,
    created_at      REAL NOT NULL
);

-- Per-file knowledge node
-- activation_count: how many times meaningfully touched (toward CHART_ACTIVATION_THRESHOLD=12)
-- confidence: grows with successful events, decays without reinforcement
-- z_trajectory: slope of confidence over recent events (+ = ACQUIRING, - = EVOLVING, ~0 = CORE/ORBIT)
--   This is the Z-axis from the Topology spec — direction of travel, not just position.
--   Combined with confidence (X-axis proxy) and edge weight to neighbors (Y-axis proxy),
--   this gives a 3D position in the codebase topology space.
CREATE TABLE IF NOT EXISTS file_nodes (
    file_id          TEXT PRIMARY KEY,
    file_path        TEXT UNIQUE NOT NULL,
    purpose          TEXT,
    language         TEXT,
    edit_count       INTEGER DEFAULT 0,
    activation_count INTEGER DEFAULT 0,   -- toward CHART_ACTIVATION_THRESHOLD
    confidence       REAL DEFAULT 0.10,   -- 0.0-1.0, decays without reinforcement
    z_trajectory     REAL DEFAULT 0.0,    -- trajectory: +converging / -diverging / ~0 stable
    decay_rate       REAL DEFAULT 0.005,  -- fraction lost per day (matches spec)
    last_agent       TEXT,
    last_edited      REAL,
    owning_landmark  TEXT,
    test_files       TEXT DEFAULT '[]',
    created_at       REAL NOT NULL
);

-- Per-test knowledge node
CREATE TABLE IF NOT EXISTS test_nodes (
    test_id         TEXT PRIMARY KEY,
    test_file       TEXT NOT NULL,
    test_name       TEXT,
    total_runs      INTEGER DEFAULT 0,
    pass_count      INTEGER DEFAULT 0,
    fail_count      INTEGER DEFAULT 0,
    last_run        REAL,
    last_outcome    TEXT,
    covers_files    TEXT DEFAULT '[]',
    landmark_id     TEXT,
    created_at      REAL NOT NULL
);

-- Graph edges between any node types
-- weight compounds on successful traversal (pheromone trail), decays on failure
-- compound_count: total times this edge has been scored (strength of the trail)
CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id         TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    relationship    TEXT NOT NULL,  -- 'tests'|'implements'|'caused_by'|'fixed_by'|'requires'
    weight          REAL DEFAULT 1.0,
    compound_count  INTEGER DEFAULT 0,  -- traversal count for pheromone strength
    decay_rate      REAL DEFAULT 0.020, -- fraction lost per day without reinforcement
    last_scored     REAL,               -- timestamp of last weight change
    created_at      REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_code_events_file ON code_events(file_path);
CREATE INDEX IF NOT EXISTS idx_code_events_agent ON code_events(agent_id);
CREATE INDEX IF NOT EXISTS idx_code_events_type ON code_events(event_type);
CREATE INDEX IF NOT EXISTS idx_file_nodes_path ON file_nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_test_nodes_file ON test_nodes(test_file);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target_type, target_id);

-- ── Federation & Wiki layer ──────────────────────────────────────────────────
-- Unique identity per IRIS installation (one row, auto-created on first init)
CREATE TABLE IF NOT EXISTS instance_registry (
    instance_id  TEXT PRIMARY KEY,   -- UUID v4
    name         TEXT,               -- e.g. "midas-desktop"
    owner        TEXT,
    created_at   REAL NOT NULL,
    last_seen    REAL NOT NULL,
    version      TEXT DEFAULT '1.0'
);

-- Multi-project tracking in one DB (each project gets a UUID)
CREATE TABLE IF NOT EXISTS project_registry (
    project_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    path         TEXT,
    description  TEXT,
    tags         TEXT DEFAULT '[]',  -- JSON array
    created_at   REAL NOT NULL,
    last_active  REAL NOT NULL
);

-- Wiki knowledge nodes: docs, images, design notes linked into the graph
CREATE TABLE IF NOT EXISTS wiki_entries (
    entry_id     TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    content      TEXT,               -- markdown body
    tags         TEXT DEFAULT '[]',  -- JSON array
    file_refs    TEXT DEFAULT '[]',  -- JSON array of file paths
    image_refs   TEXT DEFAULT '[]',  -- JSON array of image paths/URLs
    project_id   TEXT,               -- FK → project_registry (nullable)
    origin_id    TEXT,               -- instance_id that created this
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    is_permanent INTEGER DEFAULT 0   -- 1 = never decays, survives federation merges
);

-- Typed edges between wiki entries, file nodes, and landmarks
CREATE TABLE IF NOT EXISTS wiki_links (
    link_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type  TEXT NOT NULL,      -- 'wiki' | 'file' | 'landmark'
    source_id    TEXT NOT NULL,
    target_type  TEXT NOT NULL,
    target_id    TEXT NOT NULL,
    relationship TEXT NOT NULL,      -- 'documents'|'references'|'implements'|'depends_on'
    weight       REAL DEFAULT 1.0,
    created_at   REAL NOT NULL
);

-- Federation merge audit log
CREATE TABLE IF NOT EXISTS merge_log (
    merge_id                TEXT PRIMARY KEY,
    source_instance_id      TEXT NOT NULL,
    source_path             TEXT NOT NULL,
    merged_at               REAL NOT NULL,
    landmarks_imported      INTEGER DEFAULT 0,
    wiki_entries_imported   INTEGER DEFAULT 0,
    conflicts_resolved      INTEGER DEFAULT 0,
    strategy                TEXT DEFAULT 'landmark_wins'  -- 'landmark_wins'|'newer_wins'|'manual'
);

CREATE INDEX IF NOT EXISTS idx_wiki_entries_project ON wiki_entries(project_id);
CREATE INDEX IF NOT EXISTS idx_wiki_entries_origin  ON wiki_entries(origin_id);
CREATE INDEX IF NOT EXISTS idx_wiki_links_source    ON wiki_links(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_wiki_links_target    ON wiki_links(target_type, target_id);
"""


# ── Stable ID helpers ──────────────────────────────────────────────────────

def _file_id(file_path: str) -> str:
    """
    Deterministic file node ID from path.
    Uses SHA256 so the same path always produces the same ID across processes.
    Python's hash() is randomized per-process — never use it for stored IDs.
    """
    digest = hashlib.sha256(file_path.encode()).hexdigest()[:16]
    return f"fn_{digest}"


def _test_id(test_file: str, test_name: Optional[str] = None) -> str:
    """Deterministic test node ID."""
    key = test_file + (test_name or "")
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"tn_{digest}"


def _edge_id(source_id: str, target_id: str) -> str:
    """Deterministic edge ID from source+target pair."""
    key = source_id + "|" + target_id
    digest = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"ge_{digest}"


# ── Core Store ─────────────────────────────────────────────────────────────

class CoordinateStore:
    """
    Bootstrap coordinate store. All the agent needs to track its
    own progress and crystallize knowledge across sessions.

    Usage:
        store = CoordinateStore()
        store.add_landmark("coordinate_store", "Built the coordinate store",
                          "bootstrap/coordinates.py",
                          "python bootstrap/coordinates.py --test")
        store.record_session(session_number=1, tasks=["build coordinate store"],
                            landmarks=["coordinate_store"])
        store.generate_system_prompt_state()
    """

    def __init__(self, db_path: str = COORDINATES_DB):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # Migrate existing databases — add new columns if they don't exist yet.
            # SQLite does not support IF NOT EXISTS for ALTER TABLE, so we use try/except.
            migrations = [
                "ALTER TABLE code_events ADD COLUMN score REAL DEFAULT NULL",
                "ALTER TABLE file_nodes ADD COLUMN activation_count INTEGER DEFAULT 0",
                "ALTER TABLE file_nodes ADD COLUMN confidence REAL DEFAULT 0.10",
                "ALTER TABLE file_nodes ADD COLUMN z_trajectory REAL DEFAULT 0.0",
                "ALTER TABLE file_nodes ADD COLUMN decay_rate REAL DEFAULT 0.005",
                "ALTER TABLE graph_edges ADD COLUMN compound_count INTEGER DEFAULT 0",
                "ALTER TABLE graph_edges ADD COLUMN decay_rate REAL DEFAULT 0.020",
                "ALTER TABLE graph_edges ADD COLUMN last_scored REAL",
                # Federation provenance columns — track which instance/project owns a node
                "ALTER TABLE file_nodes ADD COLUMN origin_id TEXT DEFAULT NULL",
                "ALTER TABLE file_nodes ADD COLUMN project_id TEXT DEFAULT NULL",
                "ALTER TABLE landmarks ADD COLUMN origin_id TEXT DEFAULT NULL",
                "ALTER TABLE landmarks ADD COLUMN project_id TEXT DEFAULT NULL",
            ]
            for stmt in migrations:
                try:
                    conn.execute(stmt)
                except Exception:
                    pass  # column already exists
            # Auto-create instance identity on first init
            self._ensure_instance_identity(conn)
            # Seed all 7 coordinate spaces if not present
            for space in BOOTSTRAP_SPACES:
                conn.execute(
                    "INSERT OR IGNORE INTO coordinate_path "
                    "(space, coordinates, confidence, last_updated) "
                    "VALUES (?, ?, ?, ?)",
                    (space, json.dumps([0.1, 0.1, 0.1]), 0.1, time.time())
                )

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_instance_identity(self, conn: sqlite3.Connection):
        """Create the local instance identity row if it doesn't exist yet."""
        row = conn.execute("SELECT instance_id FROM instance_registry LIMIT 1").fetchone()
        if not row:
            instance_id = str(uuid.uuid4())
            import socket
            hostname = socket.gethostname()
            conn.execute(
                "INSERT INTO instance_registry "
                "(instance_id, name, owner, created_at, last_seen, version) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (instance_id, hostname, None, time.time(), time.time(), "1.0")
            )
        else:
            # Update last_seen on every init
            conn.execute(
                "UPDATE instance_registry SET last_seen = ?",
                (time.time(),)
            )

    def get_instance_id(self) -> str:
        """Return the local instance UUID (created on first init)."""
        with self._conn() as conn:
            row = conn.execute("SELECT instance_id FROM instance_registry LIMIT 1").fetchone()
            return row["instance_id"] if row else ""

    # ── Project Registry ─────────────────────────────────────────────────

    def ensure_project(self, name: str, path: str = "", description: str = "",
                       tags: list = None) -> str:
        """
        Return project_id for a named project, creating it if absent.
        Idempotent — safe to call on every session start.
        """
        with self._conn() as conn:
            row = conn.execute(
                "SELECT project_id FROM project_registry WHERE name = ?", (name,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE project_registry SET last_active = ? WHERE name = ?",
                    (time.time(), name)
                )
                return row["project_id"]
            project_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO project_registry "
                "(project_id, name, path, description, tags, created_at, last_active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, name, path, description,
                 json.dumps(tags or []), time.time(), time.time())
            )
            return project_id

    def get_projects(self) -> list:
        """Return all registered projects."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM project_registry ORDER BY last_active DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Wiki Entries ─────────────────────────────────────────────────────

    def add_wiki_entry(
        self,
        title: str,
        content: str = "",
        tags: list = None,
        file_refs: list = None,
        image_refs: list = None,
        project_id: str = None,
        is_permanent: bool = False,
    ) -> str:
        """
        Add a wiki knowledge node and return its entry_id.
        Automatically stamps origin_id from the local instance registry.
        """
        entry_id = f"wiki_{uuid.uuid4().hex[:12]}"
        origin_id = self.get_instance_id()
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO wiki_entries "
                "(entry_id, title, content, tags, file_refs, image_refs, "
                " project_id, origin_id, created_at, updated_at, is_permanent) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry_id, title, content,
                    json.dumps(tags or []),
                    json.dumps(file_refs or []),
                    json.dumps(image_refs or []),
                    project_id, origin_id, now, now,
                    1 if is_permanent else 0,
                )
            )
        return entry_id

    def get_wiki_entries(
        self,
        project_id: str = None,
        permanent_only: bool = False,
        limit: int = 50,
    ) -> list:
        """Return wiki entries, optionally filtered by project or permanence."""
        with self._conn() as conn:
            clauses, params = [], []
            if project_id:
                clauses.append("project_id = ?")
                params.append(project_id)
            if permanent_only:
                clauses.append("is_permanent = 1")
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM wiki_entries {where} "
                f"ORDER BY updated_at DESC LIMIT ?",
                params + [limit]
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                for field in ("tags", "file_refs", "image_refs"):
                    try:
                        d[field] = json.loads(d[field] or "[]")
                    except Exception:
                        d[field] = []
                result.append(d)
            return result

    def search_wiki(self, query: str, limit: int = 20) -> list:
        """Full-text search across wiki entry titles, content, and tags."""
        q = f"%{query}%"
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM wiki_entries "
                "WHERE title LIKE ? OR content LIKE ? OR tags LIKE ? "
                "ORDER BY updated_at DESC LIMIT ?",
                (q, q, q, limit)
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                for field in ("tags", "file_refs", "image_refs"):
                    try:
                        d[field] = json.loads(d[field] or "[]")
                    except Exception:
                        d[field] = []
                result.append(d)
            return result

    def add_wiki_link(
        self,
        source_type: str, source_id: str,
        target_type: str, target_id: str,
        relationship: str = "references",
        weight: float = 1.0,
    ) -> int:
        """Create a typed graph edge between any two node types."""
        with self._conn() as conn:
            cursor = conn.execute(
                "INSERT INTO wiki_links "
                "(source_type, source_id, target_type, target_id, "
                " relationship, weight, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source_type, source_id, target_type, target_id,
                 relationship, weight, time.time())
            )
            return cursor.lastrowid

    def update_wiki_entry(
        self,
        entry_id: str,
        content: str = None,
        tags: list = None,
        file_refs: list = None,
        image_refs: list = None,
        is_permanent: bool = None,
    ):
        """Update mutable fields of an existing wiki entry."""
        with self._conn() as conn:
            sets, params = [], []
            if content is not None:
                sets.append("content = ?"); params.append(content)
            if tags is not None:
                sets.append("tags = ?"); params.append(json.dumps(tags))
            if file_refs is not None:
                sets.append("file_refs = ?"); params.append(json.dumps(file_refs))
            if image_refs is not None:
                sets.append("image_refs = ?"); params.append(json.dumps(image_refs))
            if is_permanent is not None:
                sets.append("is_permanent = ?"); params.append(1 if is_permanent else 0)
            if not sets:
                return
            sets.append("updated_at = ?"); params.append(time.time())
            params.append(entry_id)
            conn.execute(
                f"UPDATE wiki_entries SET {', '.join(sets)} WHERE entry_id = ?",
                params
            )

    # ── Federation / Merge ───────────────────────────────────────────────

    def get_merge_log(self) -> list:
        """Return the full merge audit log."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM merge_log ORDER BY merged_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def record_merge(
        self,
        source_instance_id: str,
        source_path: str,
        landmarks_imported: int = 0,
        wiki_entries_imported: int = 0,
        conflicts_resolved: int = 0,
        strategy: str = "landmark_wins",
    ) -> str:
        """Record a completed federation merge in the audit log."""
        merge_id = f"merge_{uuid.uuid4().hex[:12]}"
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO merge_log "
                "(merge_id, source_instance_id, source_path, merged_at, "
                " landmarks_imported, wiki_entries_imported, "
                " conflicts_resolved, strategy) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (merge_id, source_instance_id, source_path, time.time(),
                 landmarks_imported, wiki_entries_imported,
                 conflicts_resolved, strategy)
            )
        return merge_id

    # ── Landmarks ────────────────────────────────────────────────────────

    def add_landmark(
        self,
        name: str,
        description: str,
        feature_path: str,
        test_command: str,
        session_number: int
    ) -> str:
        """
        Add a new landmark. Starts with pass_count=0.
        Call verify_landmark() each time the test passes.
        Becomes permanent when pass_count reaches LANDMARK_THRESHOLD.
        """
        landmark_id = f"lm_{name.lower().replace(' ', '_')[:20]}"
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO landmarks
                   (landmark_id, name, description, feature_path,
                    test_command, pass_count, is_permanent,
                    session_number, created_at)
                   VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?)""",
                (landmark_id, name, description, feature_path,
                 test_command, session_number, time.time())
            )
        return landmark_id

    def verify_landmark(self, landmark_id: str) -> bool:
        """
        Record a passing test for this landmark.
        Returns True if landmark just became permanent.
        """
        with self._conn() as conn:
            conn.execute(
                "UPDATE landmarks SET pass_count = pass_count + 1, "
                "last_verified = ? WHERE landmark_id = ?",
                (time.time(), landmark_id)
            )
            row = conn.execute(
                "SELECT pass_count FROM landmarks WHERE landmark_id = ?",
                (landmark_id,)
            ).fetchone()
            if row and row["pass_count"] >= LANDMARK_THRESHOLD:
                conn.execute(
                    "UPDATE landmarks SET is_permanent = 1 WHERE landmark_id = ?",
                    (landmark_id,)
                )
                return True
        return False

    def get_landmarks(self, permanent_only: bool = False) -> List[Dict]:
        with self._conn() as conn:
            if permanent_only:
                rows = conn.execute(
                    "SELECT * FROM landmarks WHERE is_permanent = 1 "
                    "ORDER BY created_at"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM landmarks ORDER BY created_at"
                ).fetchall()
        return [dict(r) for r in rows]

    # ── Gradient Warnings ────────────────────────────────────────────────

    def add_gradient_warning(
        self,
        space: str,
        description: str,
        approach: str,
        session_number: int,
        correction: Optional[str] = None
    ) -> str:
        """
        Record a failure. This becomes a gradient warning — future sessions
        read this before working in this coordinate space.
        """
        warning_id = f"gw_{str(uuid.uuid4())[:8]}"
        decay_session = session_number + GRADIENT_DECAY_SESSIONS
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO gradient_warnings
                   (warning_id, space, description, approach, correction,
                    session_number, decay_session, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (warning_id, space, description, approach, correction,
                 session_number, decay_session, time.time())
            )
        return warning_id

    def resolve_gradient_warning(
        self, warning_id: str, correction: str
    ) -> None:
        """Record what approach worked after a failure."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE gradient_warnings SET correction = ?, "
                "reinforced_at = ? WHERE warning_id = ?",
                (correction, time.time(), warning_id)
            )

    def get_active_warnings(self, session_number: int) -> List[Dict]:
        """Get warnings that haven't decayed yet."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM gradient_warnings "
                "WHERE decay_session > ? OR decay_session IS NULL "
                "ORDER BY created_at DESC",
                (session_number,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Contracts ────────────────────────────────────────────────────────

    def add_contract_evidence(self, rule: str) -> str:
        """
        Record a correction event that supports a behavioral contract.
        When evidence_count reaches CONTRACT_MIN_EVIDENCE, contract activates.
        """
        with self._conn() as conn:
            # Check if contract for this rule already exists
            row = conn.execute(
                "SELECT contract_id, evidence_count FROM contracts WHERE rule = ?",
                (rule,)
            ).fetchone()

            if row:
                new_count = row["evidence_count"] + 1
                confidence = min(new_count / 5.0, 1.0)
                conn.execute(
                    "UPDATE contracts SET evidence_count = ?, "
                    "confidence = ?, last_fired = ? WHERE contract_id = ?",
                    (new_count, confidence, time.time(), row["contract_id"])
                )
                return row["contract_id"]
            else:
                contract_id = f"ct_{str(uuid.uuid4())[:8]}"
                conn.execute(
                    """INSERT INTO contracts
                       (contract_id, rule, evidence_count, confidence, created_at)
                       VALUES (?, ?, 1, 0.2, ?)""",
                    (contract_id, rule, time.time())
                )
                return contract_id

    def get_active_contracts(self) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM contracts WHERE is_active = 1 "
                "AND evidence_count >= ? ORDER BY confidence DESC",
                (CONTRACT_MIN_EVIDENCE,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Sessions ─────────────────────────────────────────────────────────

    def record_session(
        self,
        session_number: int,
        objective: str,
        tasks_completed: List[str],
        landmarks_added: List[str],
        warnings_added: List[str]
    ) -> str:
        """Record what happened in this session."""
        # Calculate confidence from landmark count
        permanent = len([l for l in self.get_landmarks(permanent_only=True)])
        domain_conf = min(0.1 + (permanent * 0.05), 1.0)
        toolpath_conf = min(0.1 + (len(landmarks_added) * 0.03), 1.0)

        # Determine maturity
        if permanent == 0:
            maturity = "immature"
        elif permanent < 5:
            maturity = "developing"
        else:
            maturity = "mature"

        session_id = f"s_{str(uuid.uuid4())[:8]}"
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO sessions
                   (session_id, session_number, objective, tasks_completed,
                    landmarks_added, warnings_added, graph_maturity,
                    domain_confidence, toolpath_confidence, started_at, ended_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, session_number, objective,
                    json.dumps(tasks_completed),
                    json.dumps(landmarks_added),
                    json.dumps(warnings_added),
                    maturity, domain_conf, toolpath_conf,
                    time.time() - 3600,   # approximate session start
                    time.time()
                )
            )
            # Update coordinate path confidence
            conn.execute(
                "UPDATE coordinate_path SET confidence = ?, last_updated = ? "
                "WHERE space = 'domain'",
                (domain_conf, time.time())
            )
            conn.execute(
                "UPDATE coordinate_path SET confidence = ?, last_updated = ? "
                "WHERE space = 'toolpath'",
                (toolpath_conf, time.time())
            )
        return session_id

    def get_session_count(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) as c FROM sessions").fetchone()
        return row["c"] if row else 0

    # ── System Prompt Generation ─────────────────────────────────────────

    def generate_system_prompt_state(self) -> str:
        """
        Generate the COORDINATE STATE block for the LM Studio system prompt.
        Call this at the end of every session and paste into the system prompt.
        update_coordinates.py does this automatically.
        """
        session_count = self.get_session_count()
        landmarks = self.get_landmarks()
        permanent = [l for l in landmarks if l["is_permanent"]]
        warnings = self.get_active_warnings(session_count)
        contracts = self.get_active_contracts()

        # Maturity
        if len(permanent) == 0:
            maturity = "immature"
            confidence = 0.20
        elif len(permanent) < 5:
            maturity = "developing"
            confidence = 0.20 + (len(permanent) * 0.08)
        else:
            maturity = "mature"
            confidence = min(0.60 + (len(permanent) * 0.03), 0.95)

        # Compact semantic header — the mathematical representation (15 tokens)
        # This is what agents read in their native language, not prose
        try:
            semantic_header = self.get_semantic_header()
        except Exception:
            semantic_header = f"MYCELIUM: confidence:{confidence:.2f}"

        lines = [
            "## COORDINATE STATE",
            semantic_header,
            "",
            f"SESSIONS_COMPLETED: {session_count}",
            f"GRAPH_MATURITY: {maturity}",
            f"CONFIDENCE: {confidence:.2f}",
            "",
            "LANDMARKS:",
        ]

        if permanent:
            for lm in permanent:
                lines.append(f"  [+] {lm['name']}: {lm['description'][:60]}")
        else:
            lines.append("  none yet — first session crystallizes coordinate store")

        if len(landmarks) > len(permanent):
            developing = [l for l in landmarks if not l["is_permanent"]]
            lines.append("DEVELOPING (not yet permanent):")
            for lm in developing:
                lines.append(
                    f"  [~] {lm['name']} "
                    f"({lm['pass_count']}/{LANDMARK_THRESHOLD} passes)"
                )

        lines.append("")
        lines.append("GRADIENT_WARNINGS:")
        if warnings:
            for w in warnings[-5:]:  # last 5 warnings
                lines.append(f"  [{w['space']}] {w['description'][:80]}")
                if w["correction"]:
                    lines.append(f"    → resolved by: {w['correction'][:60]}")
        else:
            lines.append("  none yet")

        lines.append("")
        lines.append("ACTIVE_CONTRACTS:")
        if contracts:
            for c in contracts:
                lines.append(
                    f"  [{c['confidence']:.2f}] {c['rule'][:80]}"
                )
        else:
            lines.append("  none yet")

        # Topology
        lines.extend([
            "",
            "TOPOLOGY:",
            f"  primitive: {'acquisition' if len(permanent) < 5 else 'core'}",
            f"  permanent_landmarks: {len(permanent)}",
            f"  total_sessions: {session_count}",
        ])

        return "\n".join(lines)

    # ── Work Items ───────────────────────────────────────────────────────

    def seed_work_items(self, items: List[Dict]) -> int:
        """
        Seed the work_items table (INSERT OR IGNORE so re-runs are safe).
        Returns number of rows actually inserted.
        """
        inserted = 0
        with self._conn() as conn:
            for item in items:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO work_items
                       (item_id, gate, step, description, spec_file, test_command)
                       VALUES (:item_id, :gate, :step, :description,
                               :spec_file, :test_command)""",
                    item
                )
                inserted += cur.rowcount
        return inserted

    def get_available_work(self) -> List[Dict]:
        """Return unclaimed items for the current lowest incomplete gate."""
        with self._conn() as conn:
            # Find lowest gate that still has incomplete items
            row = conn.execute(
                "SELECT MIN(gate) as g FROM work_items "
                "WHERE status != 'complete'"
            ).fetchone()
            if not row or row["g"] is None:
                return []
            current_gate = row["g"]
            rows = conn.execute(
                "SELECT * FROM work_items "
                "WHERE gate = ? AND status = 'available' "
                "ORDER BY step",
                (current_gate,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_claimed_work(self) -> List[Dict]:
        """Return all currently claimed (in-progress) work items."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM work_items WHERE status = 'claimed' "
                "ORDER BY claimed_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def claim_next_work_item(self, agent_id: str) -> Optional[Dict]:
        """
        Atomically claim the next available work item for agent_id.
        Returns the claimed item dict, or None if nothing available.
        """
        with self._conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Find lowest gate with available items
            row = conn.execute(
                "SELECT MIN(gate) as g FROM work_items "
                "WHERE status = 'available'"
            ).fetchone()
            if not row or row["g"] is None:
                return None
            current_gate = row["g"]
            item_row = conn.execute(
                "SELECT * FROM work_items "
                "WHERE gate = ? AND status = 'available' "
                "ORDER BY step LIMIT 1",
                (current_gate,)
            ).fetchone()
            if not item_row:
                return None
            item = dict(item_row)
            now = time.time()
            conn.execute(
                "UPDATE work_items SET status='claimed', claimed_by=?, "
                "claimed_at=?, heartbeat_at=? WHERE item_id=?",
                (agent_id, now, now, item["item_id"])
            )
            item["claimed_by"] = agent_id
            item["claimed_at"] = now
        return item

    def complete_work_item(
        self,
        item_id: str,
        agent_id: str,
        result: str,
        landmark_name: str = "",
        warning_description: str = ""
    ) -> bool:
        """Mark a work item complete and write a signal file."""
        now = time.time()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE work_items SET status='complete', completed_at=?, "
                "result=?, landmark_name=?, warning_description=? "
                "WHERE item_id=? AND claimed_by=?",
                (now, result, landmark_name, warning_description,
                 item_id, agent_id)
            )
            if cur.rowcount == 0:
                return False
        # Write signal file so orchestrator can poll
        os.makedirs(SIGNALS_DIR, exist_ok=True)
        signal_path = os.path.join(
            SIGNALS_DIR, f"complete_{item_id}_{int(now)}.json"
        )
        import json as _json
        with open(signal_path, "w") as f:
            _json.dump({
                "item_id": item_id,
                "agent_id": agent_id,
                "result": result,
                "landmark_name": landmark_name,
                "warning": warning_description,
                "completed_at": now,
            }, f)
        return True

    def heartbeat(self, agent_id: str) -> None:
        """Update heartbeat timestamp for all items claimed by agent_id."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE work_items SET heartbeat_at=? "
                "WHERE claimed_by=? AND status='claimed'",
                (time.time(), agent_id)
            )

    def release_stale_claims(self, timeout_minutes: int = 10) -> int:
        """
        Release claimed items whose heartbeat is older than timeout.
        Call this from orchestrator so stale claims don't block progress.
        """
        cutoff = time.time() - (timeout_minutes * 60)
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE work_items SET status='available', claimed_by=NULL, "
                "claimed_at=NULL WHERE status='claimed' AND heartbeat_at < ?",
                (cutoff,)
            )
        return cur.rowcount

    # ── Code Events (Mycelium Trail) ─────────────────────────────────────────

    def record_code_event(
        self,
        agent_id: str,
        event_type: str,
        description: str,
        file_path: Optional[str] = None,
        outcome: Optional[str] = None,
        score: Optional[float] = None,
        detail: Optional[Dict] = None,
        landmark_id: Optional[str] = None,
        gate: Optional[int] = None,
    ) -> str:
        """
        Record any code action: file edit, test run, git commit, note.
        This is the core mycelium trail — grows every session.

        score: override the computed signal quality (0.0–1.0).
               A failure with score >= HIGH_POTENTIAL_FAILURE_THRESHOLD is treated
               as a future-success candidate by the graph (not discarded as noise).
        """
        event_id = f"ev_{str(uuid.uuid4())[:12]}"
        session_number = self.get_session_count()
        computed_score = score if score is not None else self._compute_event_score(
            event_type, outcome, description
        )
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO code_events
                   (event_id, session_number, agent_id, event_type, file_path,
                    description, outcome, score, detail, landmark_id, gate, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id, session_number, agent_id, event_type, file_path,
                    description, outcome, computed_score,
                    json.dumps(detail) if detail else None,
                    landmark_id, gate, time.time()
                )
            )
            # Auto-upsert file node if file_path provided
            if file_path:
                self._upsert_file_node_inner(
                    conn, file_path, agent_id, event_score=computed_score
                )
        return event_id

    def _compute_event_score(
        self,
        event_type: str,
        outcome: Optional[str],
        description: str,
    ) -> float:
        """
        Heuristic signal score (0.0–1.0) for a code event.

        Scoring philosophy (Mycelium spec):
        - A failure with high score signals future success potential.
        - Success episodes with low scores get suppressed when coordinates cover them.
        - Failure warnings are NEVER suppressed — they carry the exception, the surprise.
        - Informative failures (import error, missing attribute, approach decision) score
          higher than blind crashes because they teach the next agent something specific.
        """
        desc_lower = (description or "").lower()

        if event_type == "test_run":
            if outcome == "pass":
                return 0.85
            elif outcome == "partial":
                return 0.55
            else:  # fail — score by informativeness
                score = 0.20
                informative_signals = [
                    "import", "attribute", "missing", "expected", "assert",
                    "raises", "circular", "timeout", "connection", "permission",
                    "approach", "resolved", "fixed", "tried", "instead",
                    "keyerror", "typeerror", "nameerror", "valueerror",
                ]
                boost = sum(0.05 for kw in informative_signals if kw in desc_lower)
                return min(0.20 + boost, 0.65)

        if event_type == "file_create":
            return 0.75

        if event_type == "file_edit":
            fix_signals = ["fix", "resolve", "correct", "patch", "remove", "bug", "error", "broken"]
            if any(kw in desc_lower for kw in fix_signals):
                return 0.80
            return 0.70

        if event_type == "note":
            # Architectural decisions are high-signal — they encode why, not just what
            return 0.80

        if event_type == "git_commit":
            return 0.85

        return 0.60

    def upsert_file_node(
        self,
        file_path: str,
        purpose: Optional[str] = None,
        language: Optional[str] = None,
        agent_id: Optional[str] = None,
        owning_landmark: Optional[str] = None,
    ) -> str:
        """Register or update a file in the knowledge graph."""
        with self._conn() as conn:
            return self._upsert_file_node_inner(
                conn, file_path, agent_id, purpose, language, owning_landmark
            )

    def _upsert_file_node_inner(
        self, conn, file_path: str,
        agent_id: Optional[str] = None,
        purpose: Optional[str] = None,
        language: Optional[str] = None,
        owning_landmark: Optional[str] = None,
        event_score: Optional[float] = None,
    ) -> str:
        file_id = _file_id(file_path)
        # Infer language from extension
        if not language:
            ext = file_path.rsplit(".", 1)[-1] if "." in file_path else ""
            language = {
                "py": "python", "ts": "typescript", "tsx": "typescript",
                "js": "javascript", "rs": "rust", "md": "markdown",
                "sql": "sql", "yaml": "yaml", "json": "json",
            }.get(ext, ext)
        now = time.time()
        existing = conn.execute(
            "SELECT file_id, edit_count, activation_count, confidence, z_trajectory "
            "FROM file_nodes WHERE file_path = ?",
            (file_path,)
        ).fetchone()
        if existing:
            existing = dict(existing)
            # activation_count grows every meaningful touch — toward CHART_ACTIVATION_THRESHOLD
            # confidence nudges toward the event score (running average, capped at 0.95)
            current_confidence = existing.get("confidence") or 0.10
            if event_score is not None:
                new_confidence = min(current_confidence * 0.80 + event_score * 0.20, 0.95)
            else:
                new_confidence = current_confidence
            # Z-trajectory: slope of confidence change
            # Positive = converging (confidence rising) → ACQUIRING
            # Negative = diverging (confidence falling) → EVOLVING
            # Near zero = stable → CORE or ORBIT
            z_delta = new_confidence - current_confidence
            current_z = existing.get("z_trajectory") or 0.0
            # Blend: Z is a running slope, decays toward zero when stable
            new_z = current_z * 0.70 + z_delta * 0.30
            new_z = max(-1.0, min(1.0, new_z))
            updates = [
                "edit_count = edit_count + 1",
                "activation_count = activation_count + 1",
                "confidence = ?",
                "z_trajectory = ?",
                "last_edited = ?",
                "last_agent = ?",
            ]
            params: list = [new_confidence, new_z, now, agent_id or "unknown"]
            if purpose:
                updates.append("purpose = ?")
                params.append(purpose)
            if owning_landmark:
                updates.append("owning_landmark = ?")
                params.append(owning_landmark)
            params.append(file_path)
            conn.execute(
                f"UPDATE file_nodes SET {', '.join(updates)} WHERE file_path = ?",
                params
            )
            return existing["file_id"]
        else:
            initial_confidence = event_score * 0.20 + 0.10 if event_score is not None else 0.10
            conn.execute(
                """INSERT OR IGNORE INTO file_nodes
                   (file_id, file_path, purpose, language, edit_count,
                    activation_count, confidence, decay_rate,
                    last_agent, last_edited, owning_landmark, created_at)
                   VALUES (?, ?, ?, ?, 1, 1, ?, 0.005, ?, ?, ?, ?)""",
                (file_id, file_path, purpose, language,
                 initial_confidence,
                 agent_id or "unknown", now, owning_landmark, now)
            )
            return file_id

    def record_test_run(
        self,
        agent_id: str,
        test_file: str,
        outcome: str,
        test_name: Optional[str] = None,
        covers_files: Optional[List[str]] = None,
        landmark_id: Optional[str] = None,
        output_summary: Optional[str] = None,
    ) -> str:
        """Record a test run result and update the test node's history."""
        test_id = _test_id(test_file, test_name)
        now = time.time()
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT test_id, total_runs, pass_count, fail_count "
                "FROM test_nodes WHERE test_file = ? AND (test_name = ? OR (test_name IS NULL AND ? IS NULL))",
                (test_file, test_name, test_name)
            ).fetchone()
            if existing:
                pass_inc = 1 if outcome == "pass" else 0
                fail_inc = 1 if outcome == "fail" else 0
                covers_json = json.dumps(covers_files or [])
                conn.execute(
                    """UPDATE test_nodes SET
                       total_runs = total_runs + 1,
                       pass_count = pass_count + ?,
                       fail_count = fail_count + ?,
                       last_run = ?, last_outcome = ?,
                       covers_files = ?, landmark_id = COALESCE(?, landmark_id)
                       WHERE test_id = ?""",
                    (pass_inc, fail_inc, now, outcome,
                     covers_json, landmark_id, existing["test_id"])
                )
                test_id = existing["test_id"]
            else:
                covers_json = json.dumps(covers_files or [])
                conn.execute(
                    """INSERT INTO test_nodes
                       (test_id, test_file, test_name, total_runs, pass_count,
                        fail_count, last_run, last_outcome, covers_files,
                        landmark_id, created_at)
                       VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        test_id, test_file, test_name,
                        1 if outcome == "pass" else 0,
                        1 if outcome == "fail" else 0,
                        now, outcome, covers_json, landmark_id, now
                    )
                )
            # Compute score and record as a code_event (inline to avoid nested connection)
            event_score = self._compute_event_score("test_run", outcome, output_summary or "")
            event_id = f"ev_{str(uuid.uuid4())[:12]}"
            session_number = self.get_session_count()
            ev_desc = f"Test run: {test_file}" + (f"::{test_name}" if test_name else "")
            ev_detail = json.dumps({"summary": output_summary or "", "covers": covers_files or []})
            conn.execute(
                """INSERT INTO code_events
                   (event_id, session_number, agent_id, event_type, file_path,
                    description, outcome, score, detail, landmark_id, gate, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_id, session_number, agent_id, "test_run", test_file,
                 ev_desc, outcome, event_score, ev_detail, landmark_id, None, now)
            )
            # Auto-upsert file node for test file
            self._upsert_file_node_inner(conn, test_file, agent_id, event_score=event_score)
            # Link test -> covers files in graph, compound edge weights based on outcome
            if covers_files:
                for cf in covers_files:
                    # Upsert the covered file's node first — returns the ACTUAL stored file_id
                    # (which may be an old hash-based ID on existing DBs; we use what's there)
                    actual_fn_id = self._upsert_file_node_inner(
                        conn, cf, agent_id, event_score=event_score
                    )
                    ge_id = _edge_id(test_id, actual_fn_id)
                    # Insert edge if it doesn't exist
                    conn.execute(
                        """INSERT OR IGNORE INTO graph_edges
                           (edge_id, source_type, source_id, target_type,
                            target_id, relationship, weight, compound_count,
                            decay_rate, last_scored, created_at)
                           VALUES (?, 'test', ?, 'file', ?, 'tests', 1.0, 0, 0.020, ?, ?)""",
                        (ge_id, test_id, actual_fn_id, now, now)
                    )
                    # Compound the edge weight based on outcome (pheromone trail)
                    if outcome == "pass":
                        conn.execute(
                            """UPDATE graph_edges SET
                               weight = MIN(weight * ?, ?),
                               compound_count = compound_count + 1,
                               last_scored = ?
                               WHERE edge_id = ?""",
                            (EDGE_SUCCESS_FACTOR, EDGE_WEIGHT_MAX, now, ge_id)
                        )
                    else:
                        conn.execute(
                            """UPDATE graph_edges SET
                               weight = MAX(weight * ?, ?),
                               compound_count = compound_count + 1,
                               last_scored = ?
                               WHERE edge_id = ?""",
                            (EDGE_FAILURE_FACTOR, EDGE_WEIGHT_MIN, now, ge_id)
                        )
        return test_id

    def link_events_to_landmark(
        self, agent_id: str, landmark_id: str, since_ts: Optional[float] = None
    ) -> int:
        """Link all recent code_events by agent_id to a landmark. Returns count linked."""
        with self._conn() as conn:
            if since_ts:
                cur = conn.execute(
                    "UPDATE code_events SET landmark_id = ? "
                    "WHERE agent_id = ? AND landmark_id IS NULL AND created_at >= ?",
                    (landmark_id, agent_id, since_ts)
                )
            else:
                cur = conn.execute(
                    "UPDATE code_events SET landmark_id = ? "
                    "WHERE agent_id = ? AND landmark_id IS NULL",
                    (landmark_id, agent_id)
                )
            # Also update test nodes
            conn.execute(
                "UPDATE test_nodes SET landmark_id = ? "
                "WHERE landmark_id IS NULL AND test_file IN ("
                "  SELECT DISTINCT file_path FROM code_events "
                "  WHERE agent_id = ? AND event_type = 'test_run'"
                ")",
                (landmark_id, agent_id)
            )
            return cur.rowcount

    def add_graph_edge(
        self,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
        relationship: str,
        weight: float = 1.0,
    ) -> str:
        """Add a directed edge to the knowledge graph."""
        edge_id = f"ge_{str(uuid.uuid4())[:12]}"
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO graph_edges
                   (edge_id, source_type, source_id, target_type,
                    target_id, relationship, weight, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (edge_id, source_type, source_id, target_type,
                 target_id, relationship, weight, time.time())
            )
        return edge_id

    # ── Graph Query Methods ───────────────────────────────────────────────────

    def get_file_history(self, file_path: str, limit: int = 10) -> List[Dict]:
        """All recent code events for a specific file."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM code_events WHERE file_path = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (file_path, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_file_node(self, file_path: str) -> Optional[Dict]:
        """Get the knowledge node for a file."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM file_nodes WHERE file_path = ?",
                (file_path,)
            ).fetchone()
        return dict(row) if row else None

    def get_related_tests(self, file_path: str) -> List[Dict]:
        """Get test nodes that cover a given implementation file."""
        fn_id = _file_id(file_path)
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT t.* FROM test_nodes t
                   JOIN graph_edges e ON e.source_id = t.test_id
                   WHERE e.target_id = ? AND e.relationship = 'tests'
                   ORDER BY t.last_run DESC""",
                (str(fn_id),)
            ).fetchall()
            if not rows:
                # Fallback: search by covers_files JSON
                all_tests = conn.execute(
                    "SELECT * FROM test_nodes ORDER BY last_run DESC"
                ).fetchall()
                rows = [r for r in all_tests if file_path in (r["covers_files"] or "")]
        return [dict(r) for r in rows]

    def get_agent_trail(self, agent_id: str, limit: int = 20) -> List[Dict]:
        """Everything an agent has done, most recent first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM code_events WHERE agent_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (agent_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_events(self, limit: int = 10, event_type: Optional[str] = None) -> List[Dict]:
        """Most recent code events across all agents."""
        with self._conn() as conn:
            if event_type:
                rows = conn.execute(
                    "SELECT * FROM code_events WHERE event_type = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (event_type, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM code_events ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    def get_graph_summary(self) -> Dict:
        """Summary statistics about the knowledge graph."""
        with self._conn() as conn:
            events = conn.execute("SELECT COUNT(*) as c FROM code_events").fetchone()["c"]
            files = conn.execute("SELECT COUNT(*) as c FROM file_nodes").fetchone()["c"]
            tests = conn.execute("SELECT COUNT(*) as c FROM test_nodes").fetchone()["c"]
            edges = conn.execute("SELECT COUNT(*) as c FROM graph_edges").fetchone()["c"]
            hot_files = conn.execute(
                "SELECT file_path, edit_count, activation_count, confidence "
                "FROM file_nodes ORDER BY edit_count DESC LIMIT 5"
            ).fetchall()
            near_crystallization = conn.execute(
                "SELECT COUNT(*) as c FROM file_nodes "
                "WHERE activation_count >= ?",
                (CHART_ACTIVATION_THRESHOLD,)
            ).fetchone()["c"]
            high_potential = conn.execute(
                "SELECT COUNT(*) as c FROM code_events "
                "WHERE outcome IN ('fail', 'partial') AND score >= ?",
                (HIGH_POTENTIAL_FAILURE_THRESHOLD,)
            ).fetchone()["c"]
        return {
            "total_events": events,
            "file_nodes": files,
            "test_nodes": tests,
            "graph_edges": edges,
            "near_crystallization": near_crystallization,
            "high_potential_failures": high_potential,
            "hottest_files": [dict(r) for r in hot_files],
        }

    # ── Score / Compound / Decay ──────────────────────────────────────────────

    def score_event(self, event_id: str, score: float) -> bool:
        """
        Explicitly set the signal score on an existing event.

        Use this when you can judge quality after the fact — e.g., a 'fail' test
        that revealed a fundamental architecture issue scores 0.70, not 0.20.
        A failure that teaches the next agent something specific should not
        be discarded as noise — give it a score that reflects its real value.

        score: 0.0 (pure noise) to 1.0 (maximum signal)
        Returns True if the event was found and updated.
        """
        score = max(0.0, min(1.0, score))
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE code_events SET score = ? WHERE event_id = ?",
                (score, event_id)
            )
        return cur.rowcount > 0

    def score_edge_success(self, edge_id: str) -> float:
        """
        Compound an edge's weight upward on successful traversal.
        This is the pheromone trail mechanic — paths that work grow stronger.
        Returns the new weight.
        """
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """UPDATE graph_edges SET
                   weight = MIN(weight * ?, ?),
                   compound_count = compound_count + 1,
                   last_scored = ?
                   WHERE edge_id = ?""",
                (EDGE_SUCCESS_FACTOR, EDGE_WEIGHT_MAX, now, edge_id)
            )
            row = conn.execute(
                "SELECT weight FROM graph_edges WHERE edge_id = ?", (edge_id,)
            ).fetchone()
        return row["weight"] if row else 0.0

    def score_edge_failure(self, edge_id: str) -> float:
        """
        Decay an edge's weight downward on failed traversal.
        Paths that don't work weaken. They don't disappear — they become less likely.
        Returns the new weight.
        """
        now = time.time()
        with self._conn() as conn:
            conn.execute(
                """UPDATE graph_edges SET
                   weight = MAX(weight * ?, ?),
                   compound_count = compound_count + 1,
                   last_scored = ?
                   WHERE edge_id = ?""",
                (EDGE_FAILURE_FACTOR, EDGE_WEIGHT_MIN, now, edge_id)
            )
            row = conn.execute(
                "SELECT weight FROM graph_edges WHERE edge_id = ?", (edge_id,)
            ).fetchone()
        return row["weight"] if row else 0.0

    def run_decay_pass(self, days_elapsed: float = 1.0) -> Dict:
        """
        Apply time-based decay to non-landmark file_node confidence and edge weights.

        Decay mechanics (from Mycelium spec v1.6):
        - Nodes not reinforced by recent sessions gradually fade.
        - The map self-corrects without intervention.
        - Landmarks NEVER decay — they are permanent memory.
        - context space decays fastest (0.025/day) — stale project context misleads.
        - toolpath decays at 0.020/day — habits shift.
        - domain/style/chrono/capability decay slowly (0.005/day) — identity is stable.

        days_elapsed: how many days since last decay pass (typically 1.0)
        Returns counts of nodes updated.
        """
        now = time.time()
        cutoff = now - (days_elapsed * 86400)

        with self._conn() as conn:
            # Decay file_node confidence for nodes not touched since cutoff
            # Nodes with owning_landmark (permanent) decay more slowly
            file_cur = conn.execute(
                """UPDATE file_nodes SET
                   confidence = MAX(confidence * (1.0 - decay_rate * ?), 0.01)
                   WHERE last_edited < ? AND owning_landmark IS NULL""",
                (days_elapsed, cutoff)
            )
            # Landmark-owned files decay at half rate
            lm_cur = conn.execute(
                """UPDATE file_nodes SET
                   confidence = MAX(confidence * (1.0 - (decay_rate * 0.5) * ?), 0.05)
                   WHERE last_edited < ? AND owning_landmark IS NOT NULL""",
                (days_elapsed, cutoff)
            )
            # Decay edge weights for edges not scored recently
            edge_cur = conn.execute(
                """UPDATE graph_edges SET
                   weight = MAX(weight * (1.0 - decay_rate * ?), ?)
                   WHERE (last_scored IS NULL OR last_scored < ?)""",
                (days_elapsed, EDGE_WEIGHT_MIN, cutoff)
            )
            # Update coordinate space confidence using spec decay rates
            for space, rate in NODE_DECAY_RATES.items():
                conn.execute(
                    """UPDATE coordinate_path SET
                       confidence = MAX(confidence * (1.0 - ? * ?), 0.05),
                       last_updated = ?
                       WHERE space = ?""",
                    (rate, days_elapsed, now, space)
                )

        return {
            "file_nodes_decayed": file_cur.rowcount + lm_cur.rowcount,
            "edges_decayed": edge_cur.rowcount,
            "days_elapsed": days_elapsed,
        }

    def get_high_potential_failures(self, limit: int = 20) -> List[Dict]:
        """
        Return failed/partial events with score >= HIGH_POTENTIAL_FAILURE_THRESHOLD.

        These are failures that carry informative signal — the map does not
        discard them. They represent approaches that were tried, what they revealed,
        and why future attempts in the same space might succeed.

        Failure warnings are always injected (spec Part 8) — they carry the
        exception, the surprise, the thing coordinates cannot say.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM code_events
                   WHERE outcome IN ('fail', 'partial')
                   AND score >= ?
                   ORDER BY score DESC, created_at DESC
                   LIMIT ?""",
                (HIGH_POTENTIAL_FAILURE_THRESHOLD, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_crystallization_candidates(self) -> List[Dict]:
        """
        Return file_nodes with activation_count >= CHART_ACTIVATION_THRESHOLD.
        These nodes have been activated enough times to be considered
        crystallization-ready — the biological equivalent of a pheromone trail
        that has been reinforced enough to become a permanent path.
        """
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM file_nodes
                   WHERE activation_count >= ?
                   ORDER BY confidence DESC, activation_count DESC""",
                (CHART_ACTIVATION_THRESHOLD,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Topology Primitives ───────────────────────────────────────────────────

    def classify_topology_primitive(self, file_path: str) -> str:
        """
        Classify a file_node into one of the five topology primitives from
        the Mycelium spec v2.0 — adapted for codebase topology rather than
        user identity topology.

        In the codebase context:
          X-axis (confidence) = how well-established this file is (0=experimental, 1=battle-tested)
          Y-axis (edge weight) = how connected to other key files (0=isolated, 1=central)
          Z-axis (z_trajectory) = direction of travel (+=ACQUIRING mastery, -=EVOLVING away)

        Primitives:
          CORE        — high confidence, stable, well-connected. The settled foundation.
          ACQUISITION — actively being built up. Confidence rising. Z positive.
          EXPLORATION — active edits but mixed confidence. Being experimented on.
          EVOLUTION   — was important, confidence falling. Being refactored/replaced.
          ORBIT       — moderate everything, Z near zero. Supporting/adjacent role.

        This is the semantic layer — it tells you what a file IS right now,
        not just what happened to it.
        """
        node = self.get_file_node(file_path)
        if not node:
            return "UNKNOWN"

        confidence = node.get("confidence") or 0.10
        z = node.get("z_trajectory") or 0.0
        activation = node.get("activation_count") or 0

        # Get average outgoing edge weight (Y-axis: connectivity)
        with self._conn() as conn:
            fn_id = _file_id(file_path)
            row = conn.execute(
                "SELECT AVG(weight) as avg_w FROM graph_edges "
                "WHERE source_id = ? OR target_id = ?",
                (str(fn_id), str(fn_id))
            ).fetchone()
        avg_edge_weight = row["avg_w"] if row and row["avg_w"] else 1.0
        # Normalize to 0-1 (max reasonable weight is EDGE_WEIGHT_MAX=5.0)
        y = min(avg_edge_weight / EDGE_WEIGHT_MAX, 1.0)

        # ACQUISITION: actively converging — Z is the determining signal
        if z >= 0.08:
            return "ACQUISITION"

        # EVOLUTION: actively diverging — was important, now moving away
        if z <= -0.06 and confidence > 0.40:
            return "EVOLUTION"

        # CORE: high confidence, well-connected, stable
        if confidence >= 0.65 and y >= 0.30 and abs(z) < 0.06:
            return "CORE"

        # EXPLORATION: active (high activation) but low/mid confidence — being tried out
        if activation >= 3 and confidence < 0.60 and abs(z) < 0.10:
            return "EXPLORATION"

        # ORBIT: near everything but not landing — moderate all axes, near-zero Z
        return "ORBIT"

    def get_pheromone_routes(
        self, from_file: Optional[str] = None, limit: int = 6
    ) -> List[Dict]:
        """
        Return the strongest paths through the knowledge graph.

        This is the routing signal — the spider's pheromone trails.
        An agent reading this does not need to reason about where to start;
        the graph tells it where the highest-confidence paths are.

        If from_file is given, returns edges from/to that file's node.
        Otherwise returns the globally strongest edges.

        The weight of each edge represents the compound reinforcement from
        all test runs and traversals — edges that repeatedly produce passing
        tests grow stronger (up to EDGE_WEIGHT_MAX=5.0).
        """
        # Edges connect test_nodes (source_type='test', source_id=tn_XXX)
        # to file_nodes (target_type='file', target_id=fn_XXX).
        # We JOIN both tables to resolve human-readable paths.
        route_sql = """
            SELECT e.*,
                COALESCE(tn_src.test_file, fn_src.file_path, e.source_id) AS source_path,
                COALESCE(fn_tgt.file_path, tn_tgt.test_file, e.target_id) AS target_path
            FROM graph_edges e
            LEFT JOIN test_nodes  tn_src ON tn_src.test_id  = e.source_id
            LEFT JOIN file_nodes  fn_src ON fn_src.file_id  = e.source_id
            LEFT JOIN file_nodes  fn_tgt ON fn_tgt.file_id  = e.target_id
            LEFT JOIN test_nodes  tn_tgt ON tn_tgt.test_id  = e.target_id
        """
        with self._conn() as conn:
            if from_file:
                fn_id = _file_id(from_file)
                rows = conn.execute(
                    route_sql +
                    "WHERE e.source_id = ? OR e.target_id = ? "
                    "ORDER BY e.weight DESC LIMIT ?",
                    (fn_id, fn_id, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    route_sql + "ORDER BY e.weight DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    def get_semantic_header(self) -> str:
        """
        Generate the compact MYCELIUM: coordinate line — the mathematical
        representation agents read in their native language.

        This is the 15-token representation that replaces 60 tokens of prose.
        The coordinate path encodes the current state of the codebase build:
        - context: gate progress + confidence
        - toolpath: strongest edge weight + total events
        - topology: primitive distribution across file nodes
        - warnings: active gradient warnings count

        Format mirrors the Mycelium spec's semantic header so this bootstrap
        DB is structurally compatible with data/memory.db when transferred.
        """
        session_count = self.get_session_count()
        permanent = self.get_landmarks(permanent_only=True)
        warnings = self.get_active_warnings(session_count)

        # Context coordinates: [gate_progress, landmark_density, session_depth]
        gate_progress = min(len(permanent) / 16.0, 1.0)  # 16 total landmarks across 3 gates
        landmark_density = min(len(permanent) / 20.0, 1.0)
        session_depth = min(session_count / 50.0, 1.0)
        context_coords = f"[{gate_progress:.2f},{landmark_density:.2f},{session_depth:.2f}]"

        # Toolpath: strongest compound edge + total events
        try:
            summary = self.get_graph_summary()
            total_ev = summary["total_events"]
            routes = self.get_pheromone_routes(limit=1)
            max_weight = routes[0]["weight"] if routes else 1.0
        except Exception:
            total_ev, max_weight = 0, 1.0
        toolpath_coords = f"[w:{max_weight:.1f},ev:{total_ev}]"

        # Topology: count primitives across all file nodes
        try:
            with self._conn() as conn:
                file_nodes = conn.execute(
                    "SELECT file_path FROM file_nodes ORDER BY activation_count DESC LIMIT 30"
                ).fetchall()
            primitives: Dict[str, int] = {}
            for fn in file_nodes:
                p = self.classify_topology_primitive(fn["file_path"])
                primitives[p] = primitives.get(p, 0) + 1
        except Exception:
            primitives = {}

        topo_str = " | ".join(
            f"{p.lower()}:{n}"
            for p, n in sorted(primitives.items(), key=lambda x: -x[1])
            if n > 0
        ) or "immature"

        conf = min(0.20 + len(permanent) * 0.05, 0.95)
        w_count = len(warnings)

        lines = [
            f"MYCELIUM: context:{context_coords}@gate{min(len(permanent)//4+1,4)} "
            f"| toolpath:{toolpath_coords} | confidence:{conf:.2f}",
            f"TOPOLOGY: {topo_str}",
        ]
        if w_count:
            lines.append(f"GRADIENT: {w_count} active warning{'s' if w_count != 1 else ''}")

        return "\n".join(lines)

    def run_self_test(self) -> bool:
        """
        Self-test for the coordinate store.
        Returns True if all operations work correctly.
        Used as the first landmark verification.
        """
        try:
            # Test landmark operations
            lm_id = self.add_landmark(
                name="self_test",
                description="Coordinate store self-test passed",
                feature_path="bootstrap/coordinates.py",
                test_command="python bootstrap/coordinates.py --test",
                session_number=1
            )
            self.verify_landmark(lm_id)

            # Test gradient warning
            w_id = self.add_gradient_warning(
                space="toolpath",
                description="Test warning",
                approach="test approach",
                session_number=1,
                correction="test correction"
            )

            # Test contract
            self.add_contract_evidence("Always test before marking landmark done")

            # Test state generation
            state = self.generate_system_prompt_state()
            assert "COORDINATE STATE" in state
            assert "SESSIONS_COMPLETED" in state

            # Clean up test data
            with self._conn() as conn:
                conn.execute(
                    "DELETE FROM landmarks WHERE landmark_id = ?", (lm_id,)
                )
                conn.execute(
                    "DELETE FROM gradient_warnings WHERE warning_id = ?", (w_id,)
                )

            return True
        except Exception as e:
            print(f"Self-test failed: {e}")
            return False


# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    store = CoordinateStore()

    if "--test" in sys.argv:
        print("Running coordinate store self-test...")
        if store.run_self_test():
            print("PASS: Coordinate store working correctly")
            sys.exit(0)
        else:
            print("FAIL: Coordinate store self-test failed")
            sys.exit(1)

    if "--state" in sys.argv:
        print(store.generate_system_prompt_state())
        sys.exit(0)

    if "--landmarks" in sys.argv:
        for lm in store.get_landmarks():
            status = "[PERMANENT]" if lm["is_permanent"] else f"[{lm['pass_count']}/{LANDMARK_THRESHOLD}]"
            print(f"{status} {lm['name']}: {lm['description']}")
        sys.exit(0)

    if "--warnings" in sys.argv:
        session = store.get_session_count()
        for w in store.get_active_warnings(session):
            print(f"[{w['space']}] {w['description']}")
            if w["correction"]:
                print(f"  → {w['correction']}")
        sys.exit(0)

    print("IRIS Bootstrap Coordinate Store")
    print(f"Database: {COORDINATES_DB}")
    print(f"Sessions: {store.get_session_count()}")
    print(f"Landmarks: {len(store.get_landmarks())}")
    print(f"Warnings: {len(store.get_active_warnings(store.get_session_count()))}")
    print("")
    print("Commands:")
    print("  --test       Run self-test (use as first landmark verification)")
    print("  --state      Print coordinate state for system prompt")
    print("  --landmarks  List all landmarks")
    print("  --warnings   List active gradient warnings")

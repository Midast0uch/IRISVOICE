# IRIS Memory Foundation — Implementation Spec
**Version:** 1.0 | **Status:** Pre-Implementation | **Target Phase:** Torus-Ready  
**Audience:** Implementing agent / developer  
**Cross-references:** IRIS_Swarm_PRD_v6_1.md (§12, §13), Torus_Whitepaper_v0.7

---

## Purpose of This Document

This spec defines the memory foundation that must exist before swarm implementation begins. It is written for an implementing agent. Every section answers: *what exists, what needs to change, how to change it, and why.* No new files are created unless a file for that responsibility genuinely does not exist. No existing logic is replaced unless it conflicts with the target architecture.

The memory system built here will:
1. Power single-user IRIS today (Phase 0–3)
2. Operate across a user's own devices via Tailscale mesh (Phase 4–5)
3. Participate as a sovereign personal memory layer in the Torus network (Phase 6+)

The Torus constraint is a day-one design rule, not a future migration. Every schema field, every API boundary, every encryption choice made here must be valid at Torus scale without refactoring.

---

## Pre-Work: Audit Existing Memory Code

**Before writing a single line of new code**, the implementing agent must:

1. Locate all files currently handling memory, context, or conversation history in the existing IRIS codebase
2. Map each file to one of the five memory responsibilities defined in Section 3
3. Identify conflicts, gaps, and redundancies
4. Report findings before proceeding

Audit checklist:
- [ ] Search for any existing `ConversationBufferMemory`, `chat_history`, `context`, or `memory` implementations
- [ ] Identify where conversation turns are currently stored and retrieved
- [ ] Identify any existing SQLite, JSON, or file-based persistence
- [ ] Identify where the system prompt is currently assembled
- [ ] Identify any existing embedding or vector search code
- [ ] Document every file touched by memory-adjacent logic

**Rule:** If a file already handles a responsibility, extend it. Do not create a parallel implementation.

---

## 1. Architecture Overview

### 1.1 The Three Tiers (Unchanged from PRD §12)

| Tier | Storage | Scope | Purpose |
|------|---------|-------|---------|
| Working Memory | In-process dict, zone-managed | Session | Active context window; auto-compresses at 80% fill |
| Episodic Memory | SQLite + sqlite-vec, AES-256 | Permanent, local | Vector similarity retrieval of past tasks and outcomes |
| Semantic Memory | SQLite key-value, AES-256 | Permanent, local | Distilled user model; user preferences; named skills |

### 1.2 The Single Access Boundary

All memory reads and writes flow through one class: `MemoryInterface`. Nothing else in the codebase touches memory storage directly. This boundary is what makes the system upgradeable and Torus-compatible — at Phase 6, storage backends can change without touching callers.

```
┌──────────────────────────────────────────────────────┐
│                   IRIS / Swarm Core                   │
│  AgentKernel / PrimaryNode / WorkerExecutor           │
│  IntentGate / DistillationProcess / SkillCrystalliser │
└────────────────────┬─────────────────────────────────┘
                     │ only entry point
                     ▼
        ┌────────────────────────┐
        │     MemoryInterface    │  ← single boundary class
        └────┬──────────┬────────┘
             │          │
    ┌─────────▼──┐  ┌────▼─────────────────┐
    │ContextMgr  │  │  memory.db (SQLCipher) │
    │(in-process)│  │  ├── episodes table    │
    └────────────┘  │  ├── semantic table    │
                    │  └── user_display table│
                    └──────────────────────┘
```

### 1.3 Torus-Ready Constraints (Apply From Day One)

These are non-negotiable design rules, not future improvements:

- Every episode record carries a `node_id` field (set to `"local"` now; set to Dilithium3 pubkey at Phase 6)
- Every semantic entry carries a `version` integer (enables delta-sync across devices)
- Memory API must have a distinct `get_task_context_for_remote()` method that returns only task-scoped context — no personal data ever crosses to a Torus peer
- The embedding model (`all-MiniLM-L6-v2`) is loaded as a singleton service, never instantiated per-call
- All database access goes through `open_encrypted_memory()` — no unencrypted SQLite connections

---

## 2. File Structure

The implementing agent must map this structure onto the existing codebase. If a file already exists for a responsibility, use it. Only create new files for responsibilities that have no existing home.

```
backend/
└── memory/                        ← create if not exists, or map to existing memory dir
    ├── __init__.py
    ├── interface.py               ← MemoryInterface (THE single access boundary)
    ├── working.py                 ← ContextManager (zone-based, in-process)
    ├── episodic.py                ← EpisodicStore (SQLite + sqlite-vec)
    ├── semantic.py                ← SemanticStore (distilled user model)
    ├── embedding.py               ← EmbeddingService (singleton)
    ├── distillation.py            ← DistillationProcess (4h background daemon)
    └── skills.py                  ← SkillCrystalliser

data/
└── memory.db                     ← SQLCipher AES-256 encrypted database
```

**Audit note:** If any of these responsibilities already exist in files with different names (e.g., `context_manager.py`, `agent_memory.py`, `history.py`), extend those files rather than creating the names above. Name consistency matters less than avoiding duplication.

---

## 3. The Five Responsibilities

### 3.1 Responsibility 1 — MemoryInterface (interface.py)

This is the only class the rest of the application calls. It delegates to the stores below.

```python
# backend/memory/interface.py

from dataclasses import dataclass, field
from typing import Optional
from .working import ContextManager
from .episodic import EpisodicStore
from .semantic import SemanticStore
from .embedding import EmbeddingService

@dataclass
class Episode:
    session_id: str
    task_summary: str
    full_content: str
    tool_sequence: list          # [{tool, action, params, result}]
    outcome_type: str            # success|failure|partial|abandoned|clarification
    failure_reason: Optional[str] = None
    user_corrected: bool = False
    user_confirmed: bool = False
    duration_ms: int = 0
    tokens_used: int = 0
    model_id: str = ""
    source_channel: str = "websocket"
    node_id: str = "local"       # TORUS: Dilithium3 pubkey at Phase 6
    origin: str = "local"        # TORUS: 'local' | 'torus_task'


class MemoryInterface:
    """
    Single access boundary for all memory operations.
    Nothing outside this class touches memory.db or ContextManager directly.
    """

    def __init__(self, adapter, db_path: str, biometric_key: bytes):
        self.episodic = EpisodicStore(db_path, biometric_key)
        self.semantic = SemanticStore(db_path, biometric_key)
        self.context  = ContextManager(adapter)
        self.embed    = EmbeddingService()

    # ── Called before every task ──────────────────────────────────────────────

    def get_task_context(self, task: str, session_id: str) -> str:
        """
        Assembles the full context for a task.
        Returns a string ready to inject into the model prompt.
        Used by: AgentKernel, PrimaryNode, WorkerExecutor (local tasks only)
        """
        header   = self.semantic.get_startup_header()
        episodic = self.episodic.assemble_episodic_context(task)
        return self.context.assemble_for_task(session_id, task, header, episodic)

    def get_task_context_for_remote(self, task_summary: str, tool_sequence: list) -> str:
        """
        Context for a Torus peer worker. Contains ONLY task-relevant data.
        No personal profile data. No user preferences. No episodic memory.
        TORUS: This is the only context method callable with a remote TaskMessage.
        """
        # Only includes: task description + relevant tool sequences from past
        # No semantic_header — personal data stays local
        similar = self.episodic.retrieve_similar(task_summary, limit=2, min_score=0.6)
        tool_hints = "\n".join(
            f"- Approach: {ep['tool_sequence']}" for ep in similar if ep.get('tool_sequence')
        )
        return f"TASK: {task_summary}\n\nRELEVANT TOOL PATTERNS:\n{tool_hints}"

    # ── Called during task execution ──────────────────────────────────────────

    def append_to_session(self, session_id: str, content: str, zone: str = "working_history"):
        """Appends content to working memory. Triggers compression if needed."""
        self.context.append(session_id, content, zone)

    def update_tool_state(self, session_id: str, tool_output: str):
        """Updates the live tool output zone. Does not compress."""
        self.context.append(session_id, tool_output, zone="active_tool_state")

    def get_assembled_context(self, session_id: str) -> str:
        """Returns current rendered context for the session."""
        return self.context.render(session_id)

    def clear_session(self, session_id: str):
        """Clears working memory for a session after completion."""
        self.context.clear_session(session_id)

    # ── Called after task completion ──────────────────────────────────────────

    def store_episode(self, episode: Episode):
        """
        Persists a completed task episode with embedding.
        Called by: SwarmBridge / AgentKernel after every task completion.
        """
        score = self._score_outcome(episode)
        self.episodic.store(episode, score)

    # ── Called by semantic update triggers ────────────────────────────────────

    def update_preference(self, key: str, value: str, source: str = "user_set"):
        """
        Directly updates a user preference in semantic memory.
        source = 'user_set' for UI-driven changes, 'auto_learned' for distillation.
        """
        self.semantic.update("user_preferences", key, value)
        self.semantic.update_user_display(key, value, source)

    def get_user_profile_display(self) -> list[dict]:
        """
        Returns the user-facing memory entries (for UI panel: 'IRIS remembers').
        Non-technical users see and can edit these.
        """
        return self.semantic.get_display_entries()

    def forget_preference(self, key: str):
        """Removes a user-facing memory entry. Called from UI 'forget' action."""
        self.semantic.delete_display_entry(key)
        self.semantic.delete("user_preferences", key)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _score_outcome(self, ep: Episode) -> float:
        score  = 0.50 if ep.outcome_type == "success" else 0.0
        score += 0.30 if ep.user_confirmed            else 0.0
        score += 0.10 if not ep.user_corrected        else 0.0
        score += 0.10 if ep.duration_ms < 5000        else 0.0
        return min(round(score, 2), 1.0)
```

---

### 3.2 Responsibility 2 — Working Memory (working.py)

Zone-based in-process context window. Manages what goes into each model prompt.

**Zones (in injection order — order is critical for model attention):**

| Zone | Compressed? | Content |
|------|-------------|---------|
| `semantic_header` | Never | Distilled user model from SemanticStore |
| `episodic_injection` | Never | Top similar past episodes |
| `task_anchor` | Never | Current task description |
| `active_tool_state` | Never | Live tool output from current step |
| `working_history` | YES at 80% | Rolling conversation history |

```python
# backend/memory/working.py

class ContextManager:
    ZONES_ORDER = [
        "semantic_header",
        "episodic_injection",
        "task_anchor",
        "active_tool_state",
        "working_history"
    ]
    ANCHOR_ZONES = {"semantic_header", "task_anchor", "active_tool_state"}

    def __init__(self, adapter, compression_threshold: float = 0.80):
        self.adapter   = adapter
        self.threshold = compression_threshold
        self._sessions: dict = {}   # session_id -> {zone: content}

    def assemble_for_task(self, session_id: str, task: str,
                          semantic_header: str, episodic_context: str) -> str:
        self._sessions[session_id] = {
            "semantic_header":    semantic_header,
            "episodic_injection": episodic_context,
            "task_anchor":        f"CURRENT TASK: {task}",
            "active_tool_state":  "",
            "working_history":    ""
        }
        return self.render(session_id)

    def append(self, session_id: str, content: str, zone: str = "working_history"):
        zones = self._sessions.setdefault(session_id, {})
        zones[zone] = zones.get(zone, "") + "\n" + content
        if zone not in self.ANCHOR_ZONES:
            if self._usage_pct(session_id) > self.threshold:
                self._compress(session_id)

    def render(self, session_id: str) -> str:
        zones = self._sessions.get(session_id, {})
        return "\n\n".join(
            zones.get(z, "") for z in self.ZONES_ORDER if zones.get(z)
        )

    def clear_session(self, session_id: str):
        self._sessions.pop(session_id, None)

    def _compress(self, session_id: str):
        """
        Compresses working_history using the COMPRESSION model role.
        Keeps the newest 60% of history lines verbatim.
        Summarizes the oldest 40% into a compact summary block.
        """
        from src.model.adapter_base import ModelRole
        zones   = self._sessions.get(session_id, {})
        history = zones.get("working_history", "")
        if not history:
            return
        lines = [l for l in history.split("\n") if l.strip()]
        if len(lines) < 10:
            return  # Not enough history to meaningfully compress
        split      = int(len(lines) * 0.4)
        old, keep  = lines[:split], lines[split:]
        prompt     = f"Summarise concisely, preserving all key facts and decisions:\n{chr(10).join(old)}"
        summary    = self.adapter.infer(
            prompt, role=ModelRole.COMPRESSION, max_tokens=300
        ).raw_text
        zones["working_history"] = f"[HISTORY SUMMARY: {summary}]\n" + "\n".join(keep)

    def _usage_pct(self, session_id: str) -> float:
        from src.model.adapter_base import ModelRole
        rendered = self.render(session_id)
        ctx_size = self.adapter.get_context_size(ModelRole.EXECUTION)
        if ctx_size == 0:
            return 0.0
        return self.adapter.count_tokens(rendered) / ctx_size
```

---

### 3.3 Responsibility 3 — Episodic Memory (episodic.py)

Permanent vector-searchable store of every completed task.

#### 3.3.1 Schema

```sql
-- data/memory.db (AES-256 via SQLCipher)

CREATE TABLE IF NOT EXISTS episodes (
    id             TEXT PRIMARY KEY,          -- UUID v4
    session_id     TEXT NOT NULL,
    task_summary   TEXT NOT NULL,
    full_content   TEXT,
    tool_sequence  TEXT,                       -- JSON: [{tool, action, params, result}]
    outcome_score  REAL DEFAULT 0.0,           -- 0.0–1.0 via scoring formula
    outcome_type   TEXT NOT NULL,              -- success|failure|partial|abandoned|clarification
    failure_reason TEXT,
    user_corrected INTEGER DEFAULT 0,
    user_confirmed INTEGER DEFAULT 0,
    duration_ms    INTEGER DEFAULT 0,
    tokens_used    INTEGER DEFAULT 0,
    model_id       TEXT DEFAULT '',
    source_channel TEXT DEFAULT 'websocket',
    node_id        TEXT DEFAULT 'local',       -- TORUS: Dilithium3 pubkey hex at Phase 6
    origin         TEXT DEFAULT 'local',       -- TORUS: 'local' | 'torus_task'
    embedding      FLOAT[384],                 -- all-MiniLM-L6-v2
    timestamp      TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ep_vec    ON episodes USING vec(embedding);
CREATE INDEX IF NOT EXISTS idx_ep_fail   ON episodes(outcome_type)
    WHERE outcome_type = 'failure';
CREATE INDEX IF NOT EXISTS idx_ep_score  ON episodes(outcome_score);
CREATE INDEX IF NOT EXISTS idx_ep_node   ON episodes(node_id);     -- TORUS: query by node
CREATE INDEX IF NOT EXISTS idx_ep_origin ON episodes(origin);      -- TORUS: filter local vs remote
```

#### 3.3.2 EpisodicStore Class

```python
# backend/memory/episodic.py

import uuid, json
from .embedding import EmbeddingService
from .db import open_encrypted_memory

class EpisodicStore:

    def __init__(self, db_path: str, biometric_key: bytes):
        self.db    = open_encrypted_memory(db_path, biometric_key)
        self.embed = EmbeddingService()
        self._init_schema()

    def store(self, episode, score: float):
        """Persist an episode with its embedding."""
        vec = self.embed.encode(episode.task_summary)
        self.db.execute("""
            INSERT OR REPLACE INTO episodes
            (id, session_id, task_summary, full_content, tool_sequence,
             outcome_score, outcome_type, failure_reason, user_corrected,
             user_confirmed, duration_ms, tokens_used, model_id,
             source_channel, node_id, origin, embedding)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            str(uuid.uuid4()), episode.session_id, episode.task_summary,
            episode.full_content, json.dumps(episode.tool_sequence),
            score, episode.outcome_type, episode.failure_reason,
            int(episode.user_corrected), int(episode.user_confirmed),
            episode.duration_ms, episode.tokens_used, episode.model_id,
            episode.source_channel, episode.node_id, episode.origin,
            vec
        ))
        self.db.commit()

    def retrieve_similar(self, task: str, limit: int = 3,
                         min_score: float = 0.6) -> list[dict]:
        """Top-N semantically similar successful episodes."""
        vec = self.embed.encode(task)
        rows = self.db.execute("""
            SELECT task_summary, tool_sequence, outcome_score
            FROM episodes
            WHERE outcome_score >= ?
            ORDER BY vec_distance_cosine(embedding, ?) ASC
            LIMIT ?
        """, (min_score, vec, limit)).fetchall()
        return [{"task_summary": r[0], "tool_sequence": json.loads(r[1] or "[]"),
                 "outcome_score": r[2]} for r in rows]

    def retrieve_failures(self, task: str, limit: int = 2) -> list[dict]:
        """Top-N semantically similar failure episodes — injected as warnings."""
        vec = self.embed.encode(task)
        rows = self.db.execute("""
            SELECT task_summary, failure_reason
            FROM episodes
            WHERE outcome_type = 'failure'
            ORDER BY vec_distance_cosine(embedding, ?) ASC
            LIMIT ?
        """, (vec, limit)).fetchall()
        return [{"task_summary": r[0], "failure_reason": r[1]} for r in rows]

    def assemble_episodic_context(self, task: str) -> str:
        """
        Formats episodic context for injection into the semantic_header zone.
        Returns empty string if no relevant episodes exist.
        """
        successes = self.retrieve_similar(task, limit=3, min_score=0.6)
        failures  = self.retrieve_failures(task, limit=2)
        parts = []
        if successes:
            parts.append("RELEVANT PAST SUCCESSES:")
            for ep in successes:
                parts.append(f"  - {ep['task_summary']} (score: {ep['outcome_score']})")
        if failures:
            parts.append("WARNINGS FROM PAST FAILURES:")
            for ep in failures:
                parts.append(f"  - {ep['task_summary']}: {ep['failure_reason']}")
        return "\n".join(parts)

    def get_stats(self) -> dict:
        """Returns memory health stats for monitoring/UI display."""
        row = self.db.execute("""
            SELECT COUNT(*), AVG(outcome_score),
                   SUM(CASE WHEN outcome_type='success' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN outcome_type='failure' THEN 1 ELSE 0 END)
            FROM episodes
        """).fetchone()
        return {
            "total_episodes": row[0],
            "avg_score": round(row[1] or 0, 3),
            "successes": row[2],
            "failures": row[3]
        }

    def _init_schema(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                id             TEXT PRIMARY KEY,
                session_id     TEXT NOT NULL,
                task_summary   TEXT NOT NULL,
                full_content   TEXT,
                tool_sequence  TEXT,
                outcome_score  REAL DEFAULT 0.0,
                outcome_type   TEXT NOT NULL,
                failure_reason TEXT,
                user_corrected INTEGER DEFAULT 0,
                user_confirmed INTEGER DEFAULT 0,
                duration_ms    INTEGER DEFAULT 0,
                tokens_used    INTEGER DEFAULT 0,
                model_id       TEXT DEFAULT '',
                source_channel TEXT DEFAULT 'websocket',
                node_id        TEXT DEFAULT 'local',
                origin         TEXT DEFAULT 'local',
                embedding      FLOAT[384],
                timestamp      TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_ep_fail   ON episodes(outcome_type)
                WHERE outcome_type = 'failure';
            CREATE INDEX IF NOT EXISTS idx_ep_score  ON episodes(outcome_score);
            CREATE INDEX IF NOT EXISTS idx_ep_node   ON episodes(node_id);
            CREATE INDEX IF NOT EXISTS idx_ep_origin ON episodes(origin);
        """)
```

---

### 3.4 Responsibility 4 — Semantic Memory (semantic.py)

The distilled user model. Everything IRIS knows about who this person is and how they work. This is what becomes the `semantic_header` injected into every prompt.

#### 3.4.1 Schema

```sql
-- Semantic knowledge store (in memory.db)

CREATE TABLE IF NOT EXISTS semantic_entries (
    category TEXT NOT NULL,       -- see categories below
    key      TEXT NOT NULL,
    value    TEXT NOT NULL,
    version  INTEGER DEFAULT 1,   -- TORUS: incremented on every update for delta-sync
    confidence REAL DEFAULT 1.0,  -- auto-learned entries have confidence < 1.0
    source   TEXT DEFAULT 'distillation', -- 'distillation' | 'crystallisation' | 'direct'
    updated  TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (category, key)
);

CREATE INDEX IF NOT EXISTS idx_sem_version  ON semantic_entries(version);  -- TORUS: delta-sync
CREATE INDEX IF NOT EXISTS idx_sem_category ON semantic_entries(category);

-- User-facing display entries (non-technical users see and edit these)
CREATE TABLE IF NOT EXISTS user_display_memory (
    display_key   TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,   -- "Prefers concise answers"
    internal_ref  TEXT,            -- "user_preferences.response_length"
    source        TEXT DEFAULT 'auto_learned',  -- 'auto_learned' | 'user_set'
    confidence    REAL DEFAULT 1.0,
    editable      INTEGER DEFAULT 1,
    created       TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### 3.4.2 Semantic Categories

| Category | Content | Updated By |
|----------|---------|------------|
| `user_preferences` | Explicit preferences stated by the user | Direct user statements; UI edits |
| `cognitive_model` | Linguistic style, autonomy preference, correction patterns | Distillation daemon |
| `tool_proficiency` | Per-tool success rates, optimal parameters | Episode outcome analysis |
| `domain_knowledge` | Reusable facts about the user's environment and work | Successful task completions |
| `named_skills` | Crystallised high-score tool sequences | SkillCrystalliser |
| `failure_patterns` | Common error types and avoidance strategies | Failed task analysis |

#### 3.4.3 SemanticStore Class

```python
# backend/memory/semantic.py

from .db import open_encrypted_memory

class SemanticStore:

    HEADER_CATEGORIES = [
        "user_preferences",
        "cognitive_model",
        "domain_knowledge",
        "named_skills",
        "failure_patterns"
    ]

    def __init__(self, db_path: str, biometric_key: bytes):
        self.db = open_encrypted_memory(db_path, biometric_key)
        self._init_schema()

    def update(self, category: str, key: str, value: str,
               confidence: float = 1.0, source: str = "direct"):
        """
        Upserts a semantic entry. Increments version on every update.
        Version increment is critical for TORUS device delta-sync.
        """
        self.db.execute("""
            INSERT INTO semantic_entries (category, key, value, confidence, source, version)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(category, key) DO UPDATE SET
                value      = excluded.value,
                confidence = excluded.confidence,
                source     = excluded.source,
                version    = semantic_entries.version + 1,
                updated    = CURRENT_TIMESTAMP
        """, (category, key, value, confidence, source))
        self.db.commit()

    def get(self, category: str, key: str) -> str | None:
        row = self.db.execute(
            "SELECT value FROM semantic_entries WHERE category=? AND key=?",
            (category, key)
        ).fetchone()
        return row[0] if row else None

    def delete(self, category: str, key: str):
        self.db.execute(
            "DELETE FROM semantic_entries WHERE category=? AND key=?",
            (category, key)
        )
        self.db.commit()

    def get_startup_header(self) -> str:
        """
        Assembles the semantic_header string injected at the top of every prompt.
        This is the core of IRIS's persistent identity for this user.
        Never compressed. Always present.
        """
        parts = ["=== USER CONTEXT ==="]
        for cat in self.HEADER_CATEGORIES:
            rows = self.db.execute(
                "SELECT key, value FROM semantic_entries WHERE category=? ORDER BY updated DESC",
                (cat,)
            ).fetchall()
            if rows:
                parts.append(f"\n[{cat.upper().replace('_', ' ')}]")
                for key, value in rows:
                    parts.append(f"  {key}: {value}")
        parts.append("=== END USER CONTEXT ===")
        return "\n".join(parts)

    def get_delta_since_version(self, since_version: int) -> list[dict]:
        """
        TORUS / DEVICE SYNC: Returns all entries updated since a given version.
        Used to sync semantic memory across a user's own Tailscale-connected devices.
        Does NOT expose personal data to remote Torus peers — only to devices owned
        by the same user (identified by shared Dilithium3 seed).
        """
        rows = self.db.execute("""
            SELECT category, key, value, version, source, updated
            FROM semantic_entries
            WHERE version > ?
            ORDER BY version ASC
        """, (since_version,)).fetchall()
        return [{"category": r[0], "key": r[1], "value": r[2],
                 "version": r[3], "source": r[4], "updated": r[5]}
                for r in rows]

    def get_max_version(self) -> int:
        row = self.db.execute(
            "SELECT MAX(version) FROM semantic_entries"
        ).fetchone()
        return row[0] or 0

    # ── User-facing display methods ──────────────────────────────────────────

    def update_user_display(self, key: str, value: str, source: str,
                             display_name: str = None, confidence: float = 1.0):
        name = display_name or self._auto_display_name(key, value)
        self.db.execute("""
            INSERT INTO user_display_memory (display_key, display_name, internal_ref, source, confidence)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(display_key) DO UPDATE SET
                display_name = excluded.display_name,
                source       = excluded.source,
                confidence   = excluded.confidence
        """, (key, name, f"user_preferences.{key}", source, confidence))
        self.db.commit()

    def get_display_entries(self) -> list[dict]:
        rows = self.db.execute("""
            SELECT display_key, display_name, source, confidence, editable, created
            FROM user_display_memory
            ORDER BY created DESC
        """).fetchall()
        return [{"key": r[0], "display_name": r[1], "source": r[2],
                 "confidence": r[3], "editable": bool(r[4])} for r in rows]

    def delete_display_entry(self, key: str):
        self.db.execute("DELETE FROM user_display_memory WHERE display_key=?", (key,))
        self.db.commit()

    def _auto_display_name(self, key: str, value: str) -> str:
        return f"{key.replace('_', ' ').title()}: {value}"

    def _init_schema(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS semantic_entries (
                category   TEXT NOT NULL,
                key        TEXT NOT NULL,
                value      TEXT NOT NULL,
                version    INTEGER DEFAULT 1,
                confidence REAL DEFAULT 1.0,
                source     TEXT DEFAULT 'distillation',
                updated    TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (category, key)
            );
            CREATE INDEX IF NOT EXISTS idx_sem_version  ON semantic_entries(version);
            CREATE INDEX IF NOT EXISTS idx_sem_category ON semantic_entries(category);
            CREATE TABLE IF NOT EXISTS user_display_memory (
                display_key  TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                internal_ref TEXT,
                source       TEXT DEFAULT 'auto_learned',
                confidence   REAL DEFAULT 1.0,
                editable     INTEGER DEFAULT 1,
                created      TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
```

---

### 3.5 Responsibility 5 — EmbeddingService (embedding.py)

Singleton. Loaded once at startup. All embedding calls go through here.

```python
# backend/memory/embedding.py

from threading import Lock

class EmbeddingService:
    """
    Singleton sentence-transformer embedding service.
    Model: all-MiniLM-L6-v2 (384-dim, ~80MB, CPU-capable)
    
    All memory components share this single instance.
    Never instantiate SentenceTransformer directly anywhere else.
    """
    _instance = None
    _model    = None
    _lock     = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer
                    self._model = SentenceTransformer("all-MiniLM-L6-v2")

    def encode(self, text: str) -> list[float]:
        """Returns 384-dim float vector for a text string."""
        self._load()
        return self._model.encode(text, convert_to_numpy=True).tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Batch encoding — use this when embedding multiple texts at once."""
        self._load()
        return self._model.encode(texts, convert_to_numpy=True).tolist()
```

---

### 3.6 Database Utilities (db.py)

```python
# backend/memory/db.py

def open_encrypted_memory(db_path: str, biometric_key: bytes):
    """
    Opens the SQLCipher AES-256 encrypted memory database.
    All memory access goes through this function — never raw sqlite3.connect().
    
    biometric_key: derived from platform biometric API at app startup.
    At Phase 6 (Torus), this key derives from the same seed phrase as
    the Dilithium3 identity — one backup recovers everything.
    """
    import sqlcipher3
    conn = sqlcipher3.connect(db_path)
    conn.execute(f"PRAGMA key='{biometric_key.hex()}'")
    conn.execute("PRAGMA cipher_page_size = 4096")
    conn.execute("PRAGMA kdf_iter = 64000")
    conn.execute("PRAGMA journal_mode = WAL")    # Better concurrent write performance
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

---

## 4. Learning System

### 4.1 DistillationProcess (distillation.py)

Background daemon. Runs every 4 hours when the system has been idle for at least 10 minutes. Clusters recent episodes into semantic entries. Does not require user action.

```python
# backend/memory/distillation.py

import asyncio, time
from datetime import datetime, timedelta

DISTILLATION_INTERVAL_HOURS = 4
IDLE_THRESHOLD_MINUTES       = 10
MIN_EPISODES_FOR_DISTILL     = 5    # Don't run if fewer than 5 new episodes

class DistillationProcess:

    def __init__(self, memory_interface, adapter):
        self.memory  = memory_interface
        self.adapter = adapter
        self._last_activity = time.time()
        self._last_distill  = 0.0
        self._running       = False

    def record_activity(self):
        """Call this on every user interaction to reset idle timer."""
        self._last_activity = time.time()

    async def start(self):
        """Launch background daemon. Call once at app startup."""
        self._running = True
        while self._running:
            await asyncio.sleep(300)   # Check every 5 minutes
            if self._should_distill():
                await self._run_distillation()

    def stop(self):
        self._running = False

    def _should_distill(self) -> bool:
        now          = time.time()
        idle_minutes = (now - self._last_activity) / 60
        hours_since  = (now - self._last_distill) / 3600
        return idle_minutes >= IDLE_THRESHOLD_MINUTES and hours_since >= DISTILLATION_INTERVAL_HOURS

    async def _run_distillation(self):
        """
        Clusters recent episodes into semantic categories.
        Runs as background inference — does not block user interactions.
        """
        from src.model.adapter_base import ModelRole

        # Fetch recent episodes not yet distilled
        recent = self.memory.episodic.get_recent_for_distillation(
            hours=self.DISTILLATION_INTERVAL_HOURS * 2,
            min_episodes=MIN_EPISODES_FOR_DISTILL
        )
        if not recent:
            return

        episode_text = "\n".join(
            f"- [{ep['outcome_type']}] {ep['task_summary']}"
            for ep in recent
        )

        # Ask model to extract patterns across categories
        prompt = f"""Analyze these recent interactions and extract key user patterns.
Return JSON only with this structure:
{{
  "user_preferences": {{"key": "value"}},
  "cognitive_model":  {{"key": "value"}},
  "domain_knowledge": {{"key": "value"}},
  "failure_patterns": {{"key": "value"}}
}}
Only include entries you are confident about.

INTERACTIONS:
{episode_text}"""

        try:
            result = self.adapter.infer(
                prompt, role=ModelRole.EXECUTION,
                max_tokens=500, temperature=0.1
            )
            import json
            patterns = json.loads(result.raw_text)
            for category, entries in patterns.items():
                if isinstance(entries, dict):
                    for key, value in entries.items():
                        if key and value:
                            confidence = 0.7   # Auto-learned entries start at 0.7 confidence
                            self.memory.semantic.update(
                                category, key, str(value),
                                confidence=confidence, source="distillation"
                            )
            self._last_distill = time.time()
        except Exception:
            pass  # Distillation failure is silent — never blocks user interaction

    DISTILLATION_INTERVAL_HOURS = DISTILLATION_INTERVAL_HOURS
```

### 4.2 SkillCrystalliser (skills.py)

Identifies tool sequences used 5+ times with average score ≥ 0.7 and crystallises them as named reusable skills in semantic memory.

```python
# backend/memory/skills.py

CRYSTALLISATION_MIN_USES  = 5
CRYSTALLISATION_MIN_SCORE = 0.7

class SkillCrystalliser:

    def __init__(self, memory_interface, adapter):
        self.memory  = memory_interface
        self.adapter = adapter

    def scan_and_crystallise(self):
        """
        Scans episodic memory for crystallisation candidates.
        Call this from the DistillationProcess after each distillation run.
        """
        from src.model.adapter_base import ModelRole
        candidates = self.memory.episodic.get_crystallisation_candidates(
            min_uses=CRYSTALLISATION_MIN_USES,
            min_avg_score=CRYSTALLISATION_MIN_SCORE
        )
        for candidate in candidates:
            # Ask model to name the skill
            prompt = (
                f"This tool sequence is used repeatedly with high success:\n"
                f"{candidate['tool_sequence']}\n\n"
                f"Give it a short, descriptive skill name (3-5 words max). Output the name only."
            )
            name = self.adapter.infer(
                prompt, role=ModelRole.EXECUTION, max_tokens=20
            ).raw_text.strip()

            self.memory.semantic.update(
                "named_skills", name,
                str(candidate['tool_sequence']),
                confidence=0.9, source="crystallisation"
            )
```

---

## 5. IntentGate Integration

The `IntentGate` (PRD §13.1) uses memory to avoid repeating clarification questions.

```python
# backend/core/intent_gate.py (existing file — extend, do not replace)

CONFIDENCE_THRESHOLD = 0.75

class IntentGate:

    def __init__(self, adapter, memory_interface):
        self.adapter = adapter
        self.memory  = memory_interface

    def evaluate(self, task: str, session_id: str) -> tuple[bool, str]:
        """
        Returns (proceed: bool, clarification_question: str).
        Checks episodic memory before generating a new clarification question.
        """
        from src.model.adapter_base import ModelRole
        context = self.memory.get_assembled_context(session_id)
        result  = self.adapter.infer(
            f"{context}\n\nUSER: {task}\n\n"
            'Parse intent. JSON only: {"intent":"...","confidence":0.0,"ambiguity":"..."}',
            role=ModelRole.EXECUTION, max_tokens=80, temperature=0.1
        )
        try:
            import json
            parsed = json.loads(result.raw_text)
            confidence = float(parsed.get("confidence", 0.0))
        except Exception:
            confidence = 0.5  # Parsing failed — treat as ambiguous

        if confidence >= CONFIDENCE_THRESHOLD:
            return True, ""

        # Check if this ambiguity has been clarified before
        past = self.memory.episodic.retrieve_similar(task, limit=3, min_score=0.5)
        for ep in past:
            if ep.get("outcome_type") == "clarification":
                return False, ep.get("task_summary", "")

        # Generate new clarification question
        q = self.adapter.infer(
            f'User said: "{task}". Generate ONE short clarifying question. Output question only.',
            role=ModelRole.EXECUTION, max_tokens=60
        )
        return False, q.raw_text.strip()
```

---

## 6. Startup Integration

Memory must initialise before the first task is processed. This section specifies where to insert the initialisation into the existing app startup sequence.

```python
# backend/core/app_startup.py (or equivalent existing startup file)
# Find the existing startup sequence and add memory initialisation here.

async def initialise_memory(adapter, config: dict) -> "MemoryInterface":
    """
    Called once at application startup, before AgentKernel/PrimaryNode starts.
    
    Returns a MemoryInterface instance that must be passed to:
    - AgentKernel (or SwarmBridge when the swarm is built)
    - IntentGate
    - DistillationProcess
    """
    from backend.memory.interface import MemoryInterface
    from backend.memory.distillation import DistillationProcess
    from backend.memory.skills import SkillCrystalliser
    from backend.core.biometric import derive_biometric_key  # existing or new

    db_path       = config.get("memory_db_path", "data/memory.db")
    biometric_key = derive_biometric_key()  # Platform biometric or fallback passphrase

    memory = MemoryInterface(adapter, db_path, biometric_key)

    # Start background distillation daemon
    distillation = DistillationProcess(memory, adapter)
    asyncio.create_task(distillation.start())

    return memory


# In the existing task handler (AgentKernel.handle_message or equivalent):
# BEFORE calling the model, add:

async def handle_task(task: str, session_id: str, memory: MemoryInterface):
    # 1. Record activity (resets idle timer for distillation)
    distillation.record_activity()
    
    # 2. Check intent confidence
    proceed, clarification = intent_gate.evaluate(task, session_id)
    if not proceed:
        return clarification
    
    # 3. Assemble context (injects semantic_header + episodic context)
    context = memory.get_task_context(task, session_id)
    
    # 4. ... run inference with context ...
    
    # AFTER task completion, add:
    # 5. Store episode
    from backend.memory.interface import Episode
    episode = Episode(
        session_id   = session_id,
        task_summary = task[:200],
        full_content = full_conversation,
        tool_sequence= tools_used,
        outcome_type = outcome,
        duration_ms  = elapsed_ms,
        tokens_used  = token_count,
        model_id     = model_name
    )
    memory.store_episode(episode)
    
    # 6. Clear working memory for this session
    memory.clear_session(session_id)
```

---

## 7. Dependencies

These must be present. Add to `requirements.txt` if not already there.

```
sqlcipher3>=0.5.0        # AES-256 encrypted SQLite
sqlite-vec>=0.1.0        # Vector similarity search in SQLite
sentence-transformers>=2.7.0  # all-MiniLM-L6-v2 embedding model
```

**Installation note:** `sqlcipher3` requires the system SQLCipher library:
- Ubuntu/Debian: `apt-get install libsqlcipher-dev`
- macOS: `brew install sqlcipher`
- Windows: Use the pre-built wheel from sqlcipher3's GitHub releases

---

## 8. Torus Phase Upgrade Path

These are the specific changes required at each future phase. Nothing here requires architecture changes — only configuration and activation of already-present fields.

### Phase 4–5 (Device Sync over Tailscale)

When the user's phone or secondary device connects via Tailscale:

1. Device requests `semantic_store.get_max_version()` from the primary node
2. If device version < primary version, device calls `semantic_store.get_delta_since_version(device_version)`
3. Device applies delta updates to its local semantic store
4. Episodic memory is NOT synced — it stays on the device that recorded it
5. No server involved — direct Tailscale P2P connection

**Code changes:** Zero. The `get_delta_since_version()` and `version` field are already built.

### Phase 6 (Torus Network)

When the Torus network activates:

1. Replace `node_id = "local"` with the node's Dilithium3 public key hex at startup
2. Replace `biometric_key` derivation with the key derived from the Torus seed phrase
3. Checkpoint data (separate from memory — see PRD §11) goes to Torus distributed cloud
4. `get_task_context_for_remote()` is the ONLY context method Torus peer workers ever call
5. Personal memory (`memory.db`) never leaves the local machine — Torus peers only get TaskMessage-scoped context

**Code changes:** Two field assignments at startup. All API boundaries are already defined.

### Phase 6 — Swarm Agent Memory Sharing

When agents in the swarm need to share context for collaborative tasks:

- The `TaskMessage` (PRD §4) carries a `context_snapshot` field
- `MemoryInterface.get_task_context_for_remote()` populates that field
- Remote workers execute against the snapshot — they never query the originating node's memory
- Results are returned and stored as episodes on the originating node with `origin = "torus_task"`

This means the Torus network's "agents speaking to share compute" pattern works through the TaskMessage, not through shared memory access. Each node's memory stays sovereign.

---

## 9. Success Criteria

The memory foundation is complete when all of the following are true:

**Functional:**
- [ ] `MemoryInterface` is the only path through which any part of the app reads or writes memory
- [ ] A `semantic_header` is injected into every model prompt
- [ ] After 10 interactions, relevant past episodes appear in task context
- [ ] After 20 interactions, failure warnings appear before tasks similar to past failures
- [ ] Distillation runs after 4h idle and produces semantic entries
- [ ] After 5+ uses of a tool sequence with ≥0.7 avg score, a named skill appears in semantic memory

**Schema:**
- [ ] Every episode has a `node_id` field (value: "local")
- [ ] Every semantic entry has a `version` integer that increments on update
- [ ] `memory.db` is AES-256 encrypted and cannot be read without the biometric key

**API boundary:**
- [ ] No file outside `backend/memory/` calls `sqlcipher3.connect()` directly
- [ ] `get_task_context_for_remote()` returns no personal profile data
- [ ] `EmbeddingService` is instantiated exactly once (verify via singleton test)

**Non-regression:**
- [ ] All existing WebSocket message types continue to work after memory integration
- [ ] Agent response latency increases by no more than 200ms (embedding + retrieval overhead)
- [ ] App startup time increases by no more than 3 seconds (model load is lazy)

**User-facing:**
- [ ] `get_user_profile_display()` returns a non-empty list after 5+ interactions
- [ ] A user can call `forget_preference(key)` and that entry disappears from display and from the startup header on the next session

---

## 10. Things to NOT Do

These are failure modes the implementing agent must actively avoid:

**Do not create a second SQLite database.** One encrypted `memory.db` with multiple tables. Not `episodic.db` and `semantic.db` separately.

**Do not load `SentenceTransformer` more than once.** If you find yourself calling `SentenceTransformer("all-MiniLM-L6-v2")` in more than one place, you have a bug. Use `EmbeddingService`.

**Do not store personal user data in the `get_task_context_for_remote()` return value.** This method is the privacy boundary. It must never include the semantic header, user preferences, cognitive model, or domain knowledge. Only task-scoped tool patterns.

**Do not replace existing working memory/context code without first mapping it.** If IRIS already has a conversation history mechanism, understand it fully before replacing it. The goal is to upgrade the existing system into this architecture, not to delete and rebuild from scratch.

**Do not block user interactions with distillation.** The `DistillationProcess` runs in an `asyncio` background task. If distillation inference fails, it fails silently. It never raises to the user.

**Do not skip the audit step.** Section "Pre-Work: Audit Existing Memory Code" is mandatory. Building without the audit will create the exact file conflicts and redundancies this spec is designed to prevent.

---

*IRIS Memory Foundation Spec v1.0 | Confidential*  
*Build correct. Build once. Torus-ready from day one.*

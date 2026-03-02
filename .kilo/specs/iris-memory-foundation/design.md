# Design: IRIS Memory Foundation

## Overview

This design implements a three-tier memory architecture for IRIS that enables personalized, contextual AI assistance while remaining Torus-ready from day one. The core principle is a **single access boundary** — all memory operations flow through `MemoryInterface`, making storage backends interchangeable without touching callers.

Key architectural decisions:
1. **Extend, don't replace** — The existing `ConversationMemory` in `backend/agent/memory.py` continues to handle session-scoped conversation; the new system adds persistent episodic/semantic layers beneath it
2. **Lazy loading** — The embedding model loads on first use to minimize startup impact
3. **Silent failures** — Background distillation never blocks user interactions
4. **Privacy boundary** — `get_task_context_for_remote()` is the only method that may be called with Torus TaskMessages; it returns zero personal data

---

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         IRIS Application                             │
│                                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ AgentKernel  │  │ IntentGate   │  │  DistillationProcess     │  │
│  │ (orchestrates)│  │ (pre-filter) │  │  (background daemon)     │  │
│  └──────┬───────┘  └──────┬───────┘  └────────────┬─────────────┘  │
│         │                 │                       │                │
│         └─────────────────┼───────────────────────┘                │
│                           │                                        │
│                           ▼                                        │
│         ┌──────────────────────────────────┐                       │
│         │      MemoryInterface             │ ← SINGLE ACCESS BOUNDARY
│         │  (interface.py)                  │   Nothing else touches     │
│         └──────────────┬───────────────────┘   memory.db directly    │
│                        │                                           │
│        ┌───────────────┼───────────────┐                          │
│        │               │               │                          │
│        ▼               ▼               ▼                          │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐                     │
│   │ Working  │   │ Episodic │   │ Semantic │                     │
│   │ Memory   │   │ Store    │   │ Store    │                     │
│   │(working) │   │(episodic)│   │(semantic)│                     │
│   └────┬─────┘   └────┬─────┘   └────┬─────┘                     │
│        │              │              │                            │
│        │              └──────┬───────┘                            │
│        │                     │                                    │
│        │              ┌──────▼──────┐                            │
│        │              │  Embedding  │                            │
│        │              │  Service    │ ← Singleton                │
│        │              │ (embedding) │   all-MiniLM-L6-v2         │
│        │              └──────┬──────┘                            │
│        │                     │                                    │
│        └─────────────────────┼────────────────────────────────────┘
│                              │                                     │
└──────────────────────────────┼─────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    data/memory.db (SQLCipher)                       │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────┐   │
│  │ episodes table │  │semantic_entries│  │ user_display_memory│   │
│  │ - Vector index │  │ - versioned    │  │ - UI-facing prefs  │   │
│  │ - node_id      │  │ - confidence   │  │ - editable         │   │
│  │ - origin       │  │ - source       │  │                    │   │
│  └────────────────┘  └────────────────┘  └────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | File | Responsibility | New/Existing |
|-----------|------|----------------|--------------|
| MemoryInterface | `backend/memory/interface.py` | Single access boundary; delegates to stores; privacy boundary for remote context | **New** |
| ContextManager | `backend/memory/working.py` | Zone-based in-process context; auto-compression; session isolation | **New** |
| EpisodicStore | `backend/memory/episodic.py` | Vector similarity retrieval; episode persistence; outcome scoring | **New** |
| SemanticStore | `backend/memory/semantic.py` | Distilled user model; versioned entries; user display | **New** |
| EmbeddingService | `backend/memory/embedding.py` | Singleton sentence-transformer; lazy model loading | **New** |
| open_encrypted_memory | `backend/memory/db.py` | SQLCipher connection factory; AES-256 encryption | **New** |
| DistillationProcess | `backend/memory/distillation.py` | Background daemon; 4h idle cycle; pattern extraction | **New** |
| SkillCrystalliser | `backend/memory/skills.py` | High-score tool sequence detection; skill naming | **New** |
| ConversationMemory | `backend/agent/memory.py` | **Existing** — session-scoped conversation; integrate with ContextManager | **Existing** |
| AgentKernel | `backend/agent/agent_kernel.py` | **Existing** — add MemoryInterface calls in task lifecycle | **Existing** |

---

## Data Models

### Episode (Dataclass)

```python
@dataclass
class Episode:
    session_id: str              # UUID of session that created this episode
    task_summary: str            # Short description for embedding/retrieval
    full_content: str            # Complete conversation/task content
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
```

### Database Schema

#### episodes table
```sql
CREATE TABLE IF NOT EXISTS episodes (
    id             TEXT PRIMARY KEY,          -- UUID v4
    session_id     TEXT NOT NULL,
    task_summary   TEXT NOT NULL,
    full_content   TEXT,
    tool_sequence  TEXT,                       -- JSON
    outcome_score  REAL DEFAULT 0.0,           -- 0.0-1.0 computed
    outcome_type   TEXT NOT NULL,
    failure_reason TEXT,
    user_corrected INTEGER DEFAULT 0,
    user_confirmed INTEGER DEFAULT 0,
    duration_ms    INTEGER DEFAULT 0,
    tokens_used    INTEGER DEFAULT 0,
    model_id       TEXT DEFAULT '',
    source_channel TEXT DEFAULT 'websocket',
    node_id        TEXT DEFAULT 'local',       -- TORUS field
    origin         TEXT DEFAULT 'local',       -- TORUS field
    embedding      FLOAT[384],                 -- sqlite-vec
    timestamp      TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_ep_vec    ON episodes USING vec(embedding);
CREATE INDEX IF NOT EXISTS idx_ep_fail   ON episodes(outcome_type) WHERE outcome_type = 'failure';
CREATE INDEX IF NOT EXISTS idx_ep_score  ON episodes(outcome_score);
CREATE INDEX IF NOT EXISTS idx_ep_node   ON episodes(node_id);
CREATE INDEX IF NOT EXISTS idx_ep_origin ON episodes(origin);
```

#### semantic_entries table
```sql
CREATE TABLE IF NOT EXISTS semantic_entries (
    category   TEXT NOT NULL,       -- user_preferences | cognitive_model | tool_proficiency | domain_knowledge | named_skills | failure_patterns
    key        TEXT NOT NULL,
    value      TEXT NOT NULL,
    version    INTEGER DEFAULT 1,   -- TORUS: incremented on every update
    confidence REAL DEFAULT 1.0,    -- < 1.0 for auto-learned
    source     TEXT DEFAULT 'distillation', -- distillation | crystallisation | direct
    updated    TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (category, key)
);

CREATE INDEX IF NOT EXISTS idx_sem_version  ON semantic_entries(version);
CREATE INDEX IF NOT EXISTS idx_sem_category ON semantic_entries(category);
```

#### user_display_memory table
```sql
CREATE TABLE IF NOT EXISTS user_display_memory (
    display_key   TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,    -- Human-readable: "Prefers concise answers"
    internal_ref  TEXT,             -- "user_preferences.response_length"
    source        TEXT DEFAULT 'auto_learned', -- auto_learned | user_set
    confidence    REAL DEFAULT 1.0,
    editable      INTEGER DEFAULT 1,
    created       TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

## API / Interface Changes

### MemoryInterface Public API

```python
class MemoryInterface:
    def __init__(self, adapter, db_path: str, biometric_key: bytes)
    
    # ── Task lifecycle ─────────────────────────────────────────────
    def get_task_context(self, task: str, session_id: str) -> str
    def get_task_context_for_remote(self, task_summary: str, tool_sequence: list) -> str
    def append_to_session(self, session_id: str, content: str, zone: str = "working_history")
    def update_tool_state(self, session_id: str, tool_output: str)
    def get_assembled_context(self, session_id: str) -> str
    def clear_session(self, session_id: str)
    
    # ── Episode storage ────────────────────────────────────────────
    def store_episode(self, episode: Episode)
    
    # ── Semantic updates ───────────────────────────────────────────
    def update_preference(self, key: str, value: str, source: str = "user_set")
    def get_user_profile_display(self) -> list[dict]
    def forget_preference(self, key: str)
```

### Context Zones (Injection Order)

Zones are injected into prompts in this specific order (critical for model attention):

| Zone | Compressed? | Content |
|------|-------------|---------|
| `semantic_header` | Never | Distilled user model from SemanticStore |
| `episodic_injection` | Never | Top similar past episodes |
| `task_anchor` | Never | Current task description |
| `active_tool_state` | Never | Live tool output from current step |
| `working_history` | YES at 80% | Rolling conversation history |

---

## Sequence Diagram

### Task Execution Flow

```
User          AgentKernel      MemoryInterface    ContextMgr    EpisodicStore    SemanticStore    Model
 |                |                   |                |               |               |         |
 |── message ────>|                  |                |               |               |         |
 |                |── record_activity()──────────────>|               |               |         |
 |                |                   |                |               |               |         |
 |                |── evaluate() ──────────────────────────────────────────────────────>|         |
 |                |<─ (proceed?, clarification?) ───────────────────────────────────────|         |
 |                |                                                                  |         |
 |                |── get_task_context(task, session_id) ──>|                       |         |
 |                |                   |── semantic.get_startup_header() ─────────────>|         |
 |                |                   |── episodic.assemble_episodic_context(task) ───>|         |
 |                |                   |── context.assemble_for_task(...) ──>|         |         |
 |                |<────────────────── context_string ─────────────────────────────────|         |
 |                |                                                                  |         |
 |                |── infer(context_string + user_message) ───────────────────────────────────>|
 |                |<──────────────────────────────────────────────────────────────── response |
 |                |                                                                  |         |
 |                |── store_episode(episode) ─────────>|               |               |         |
 |                |                   |── embed.encode(task_summary) ──>|               |         |
 |                |                   |── episodic.store(episode, score) ──────────────>|         |
 |                |                   |                |               |               |         |
 |                |── clear_session(session_id) ──────>|               |               |         |
 |<─ response ────|                  |                |               |               |         |
```

### Distillation Background Process

```
DistillationProcess              MemoryInterface          EpisodicStore          SemanticStore
        |                              |                        |                       |
        |◄──── every 5 min check ──────|                        |                       |
        |                              |                        |                       |
        │ should_distill()? (4h idle, 10min threshold)          │                       │
        │                              │                        │                       │
        ├── get_recent_for_distillation() ─────────────────────>│                       │
        │<──────────────────────────── recent episodes ─────────│                       │
        │                              │                        │                       │
        │── model.infer(extract patterns) ──────────────────────────────────────────────>│
        │<────────────────────────────── JSON patterns ──────────────────────────────────│
        │                              │                        │                       │
        │── semantic.update(category, key, value, confidence=0.7) ─────────────────────>│
```

---

## Key Design Decisions

### Decision 1: Working Memory Integration Strategy

**Choice:** Create new `ContextManager` in `backend/memory/working.py` while keeping existing `ConversationMemory` in `backend/agent/memory.py`

**Rationale:**
- `ConversationMemory` handles session-scoped conversation with Message/TaskRecord dataclasses and persistence to session storage
- `ContextManager` handles the zone-based context window assembly and compression for LLM prompts
- They are complementary: `ConversationMemory` is the source of truth for conversation history; `ContextManager` assembles what goes into the prompt
- Integration point: `MemoryInterface.get_task_context()` can pull from `ConversationMemory` to populate `working_history` zone

**Alternative considered:** Replace `ConversationMemory` entirely — rejected because it would require refactoring all existing agent code that depends on it.

---

### Decision 2: Embedding Model Selection

**Choice:** `all-MiniLM-L6-v2` (384-dim, ~80MB, CPU-capable)

**Rationale:**
- Sufficient quality for task similarity matching
- Small enough to load on modest hardware
- Well-supported by sentence-transformers
- Fast inference for real-time context assembly
- 384 dimensions balances accuracy vs storage

**Alternative considered:** Larger models like `all-mpnet-base-v2` — rejected because 80MB vs 420MB is significant for users with limited RAM.

---

### Decision 3: Encryption Strategy

**Choice:** SQLCipher with AES-256, biometric key derivation

**Rationale:**
- SQLCipher is mature, well-tested encryption for SQLite
- AES-256 is industry standard for data at rest
- Biometric key ties to user identity (or fallback passphrase)
- At Phase 6 Torus, same key derivation from seed phrase provides unified backup
- WAL mode enables concurrent reads during writes

**Alternative considered:** Application-level encryption — rejected because it would require decrypting entire datasets into memory.

---

### Decision 4: Distillation Trigger Strategy

**Choice:** 4-hour interval + 10-minute idle threshold

**Rationale:**
- 4 hours balances freshness vs computational cost
- 10-minute idle ensures we don't interrupt active use
- Minimum 5 episodes threshold prevents running on sparse data
- Silent failures prevent user disruption

**Alternative considered:** Episode-count triggers — rejected because time-based allows for natural clustering of related interactions.

---

### Decision 5: Context Compression Approach

**Choice:** Keep newest 60% verbatim, summarize oldest 40% with compression model

**Rationale:**
- Recent context is more relevant for current task
- Oldest context still contributes but in compressed form
- `ModelRole.COMPRESSION` role uses faster/cheaper model
- Only compresses `working_history` zone — anchor zones preserved

**Alternative considered:** Full summarization — rejected because losing exact recent turns harms coherence.

---

### Decision 6: Configuration Management

**Choice:** Centralized `MemoryConfig` dataclass with IRIS config system integration

**Rationale:**
- All tunable parameters in one location with sensible defaults
- Validation at startup catches configuration errors early
- Hot-reload support for non-critical settings (retention, thresholds)
- Integration with existing IRIS config.yaml and environment variables
- Clear documentation of all available options

**Configuration Parameters:**
```python
@dataclass
class MemoryConfig:
    # Working Memory
    compression_threshold: float = 0.80
    max_context_tokens: int = 8192
    
    # Episodic Memory
    retention_days: int = 90
    min_episode_score_to_retain: float = 0.3
    high_value_episode_threshold: float = 0.8
    
    # Distillation
    distillation_interval_hours: int = 4
    idle_threshold_minutes: int = 10
    min_episodes_for_distillation: int = 5
    
    # Skill Crystallization
    skill_min_uses: int = 5
    skill_min_score: float = 0.7
    
    # Database
    wal_mode: bool = True
    cipher_page_size: int = 4096
    kdf_iterations: int = 64000
    
    # Privacy
    audit_log_retention_days: int = 30
    audit_log_max_size_mb: int = 100
```

---

### Decision 7: Concurrency & Threading Model

**Choice:** Async MemoryInterface methods with SQLCipher connection per thread

**Rationale:**
- SQLite (and SQLCipher) requires each thread to have its own connection
- WAL mode enables concurrent reads during writes
- Async methods prevent blocking the event loop during DB operations
- Connection pooling managed at thread level, not coroutine level
- Thread-local storage for database connections in EpisodicStore/SemanticStore

**Implementation Pattern:**
```python
async def get_task_context(self, task: str, session_id: str) -> str:
    # Run blocking DB operations in thread pool
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, self._get_task_context_sync, task, session_id
    )
```

---

### Decision 8: Vector Search Fallback

**Choice:** Graceful degradation to keyword search if sqlite-vec unavailable

**Rationale:**
- sqlite-vec requires extension loading which may fail on some platforms
- System should remain functional even without vector search
- Keyword matching on task_summary provides baseline retrieval
- Clear warning logs guide users to install sqlite-vec for better performance
- Feature flag enables runtime detection and fallback

**Fallback Chain:**
1. Try sqlite-vec cosine similarity search
2. If unavailable, try full-text search (FTS5 if enabled)
3. If unavailable, fall back to substring matching on task_summary
4. Log appropriate warnings at each fallback level

---

### Decision 9: Data Migration Strategy

**Choice:** On-first-run migration from existing conversation.json to episodic memory

**Rationale:**
- Existing IRIS users have conversation history in session storage
- Migration preserves valuable interaction history
- Version tag prevents re-migration on subsequent runs
- Batch processing prevents startup delay (migrate in background)
- Original files preserved until migration verified

**Migration Process:**
1. Check `memory.db` for migration_version marker
2. If not present, scan `backend/sessions/*/conversation.json` files
3. Extract TaskRecord entries and convert to Episode format
4. Store in episodic memory with origin="migrated"
5. Set migration_version and log completion

---

## Error Handling & Edge Cases

| Scenario | Handling |
|----------|----------|
| Embedding model fails to load | Fallback to keyword matching; log warning; system continues |
| SQLCipher not available | Raise at startup with clear installation instructions |
| Database corruption | Attempt WAL recovery; if fails, backup and recreate with warning |
| Distillation inference fails | Silent failure; retry next cycle; never raise to user |
| Context compression fails | Return uncompressed context; log error; continue |
| Vector search returns no results | Return empty episodic context; system continues normally |
| Biometric key unavailable | Prompt for fallback passphrase at startup |
| get_task_context_for_remote() called without filtering | Code review enforcement; returns only tool patterns by design |
| sqlite-vec extension fails to load | Degrade to keyword matching; log warning; continue |
| Episode duplicate detected (similarity >0.95) | Update existing with occurrence_count + 1; recalculate score |
| Retention cleanup fails | Log error; retry next cycle; never block user |
| Audit log rotation fails | Archive current log; start new; alert user if persistent |
| Configuration validation fails | Raise at startup with specific error message; halt |
| Hot-reload config invalid | Keep previous config; log warning; notify user |


---

## Testing Strategy

### Unit Tests (per component)
- `test_context_manager.py` — zone assembly, compression logic, usage threshold
- `test_episodic_store.py` — store/retrieve, similarity search, outcome scoring
- `test_semantic_store.py` — CRUD, versioning, user display
- `test_embedding_service.py` — singleton behavior, lazy loading, encoding
- `test_memory_interface.py` — boundary enforcement, privacy isolation

### Integration Tests
- `test_memory_integration.py` — full task lifecycle with episode storage
- `test_distillation.py` — background daemon with mocked time
- `test_skill_crystallization.py` — candidate detection and naming

### Performance Tests
- `test_latency.py` — verify <200ms overhead for context assembly
- `test_startup.py` — verify <3s additional startup time
- `test_compression.py` — verify 80% threshold triggers correctly

### Security Tests
- `test_encryption.py` — verify database unreadable without key
- `test_privacy_boundary.py` — verify get_task_context_for_remote excludes personal data

### Additional Test Categories
- `test_retention.py` — verify old episodes pruned, high-value retained
- `test_duplicates.py` — verify similarity detection and occurrence counting
- `test_privacy_audit.py` — verify audit logging and rotation
- `test_config.py` — verify validation, defaults, hot-reload
- `test_migration.py` — verify conversation.json migration
- `test_fallback.py` — verify sqlite-vec unavailable degrades gracefully

---

## Security & Performance Considerations

### Security

1. **Encryption at rest:** All episodic and semantic data encrypted with AES-256
2. **Privacy boundary:** `get_task_context_for_remote()` is the only Torus-exposed method; audited to return no personal data
3. **Key derivation:** Biometric key or fallback passphrase; Torus Phase 6 uses seed phrase
4. **No plaintext storage:** SQLCipher encrypts entire database including indexes

### Performance

1. **Lazy embedding loading:** Model loads on first encode() call, not at startup
2. **WAL mode:** Concurrent reads during writes; better performance under load
3. **Singleton embedding:** One model instance shared across all components
4. **Context compression:** Prevents unbounded context growth; keeps token count predictable
5. **Vector indexing:** sqlite-vec provides efficient cosine similarity search

### Observability

Structured logging integration using existing IRIS logging infrastructure:

**Memory Operations (DEBUG level):**
- `memory.episode.stored` — episode stored with id, score, duration_ms
- `memory.episode.retrieved` — similar episodes retrieved with count, query_time_ms
- `memory.context.assembled` — context assembled with zones, total_tokens
- `memory.compression.triggered` — compression at threshold with before/after tokens
- `memory.compression.completed` — summary length, compression ratio

**Background Processes (INFO level):**
- `memory.distillation.started` — episodes to process, estimated time
- `memory.distillation.completed` — patterns extracted, entries updated
- `memory.distillation.failed` — error (silent, logged only)
- `memory.skill.crystallized` — skill name, uses, avg_score
- `memory.retention.cleaned` — episodes removed, episodes retained

**Privacy & Security (SECURITY level):**
- `memory.privacy.remote_context` — timestamp, requester_hash, content_hash, size_bytes
- `memory.encryption.rotation` — key rotation events
- `memory.audit.export` — audit log export events

**Health Metrics (exposed via get_stats()):**
- Total episodes, avg score, success/failure ratio
- Semantic entry count by category
- Database size, WAL file size
- Embedding cache hit rate
- Distillation last run timestamp

### Scalability (Torus Phase 6)

1. **node_id field:** Ready for Dilithium3 pubkey identification
2. **version field:** Enables delta-sync across user devices
3. **origin field:** Distinguishes local vs torus_task episodes
4. **get_delta_since_version():** API for device synchronization
5. **Sovereign memory:** Personal data never leaves local machine; only task snapshots shared

---

## File Structure

```
backend/
├── memory/
│   ├── __init__.py           # Exports MemoryInterface, Episode
│   ├── interface.py          # MemoryInterface (single boundary)
│   ├── working.py            # ContextManager (zone-based working memory)
│   ├── episodic.py           # EpisodicStore (vector similarity)
│   ├── semantic.py           # SemanticStore (user model)
│   ├── embedding.py          # EmbeddingService (singleton)
│   ├── db.py                 # open_encrypted_memory()
│   ├── distillation.py       # DistillationProcess (background)
│   └── skills.py             # SkillCrystalliser
│
├── agent/
│   ├── memory.py             # EXISTING — ConversationMemory (session-scoped)
│   └── agent_kernel.py       # EXISTING — integrate MemoryInterface
│
├── main.py                   # EXISTING — add memory initialization
│
└── data/
    └── memory.db             # SQLCipher encrypted database
```

---

## Dependencies

Add to `requirements.txt`:

```
sqlcipher3>=0.5.0        # AES-256 encrypted SQLite (requires libsqlcipher-dev)
sqlite-vec>=0.1.0        # Vector similarity search in SQLite
sentence-transformers>=2.7.0  # all-MiniLM-L6-v2 embeddings
```

Platform-specific installation notes:
- Ubuntu/Debian: `apt-get install libsqlcipher-dev`
- macOS: `brew install sqlcipher`
- Windows: Pre-built wheel from sqlcipher3 GitHub releases

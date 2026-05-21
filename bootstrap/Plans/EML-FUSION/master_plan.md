# Implementation Plan — IRISVOICE EML-FUSION (Pristine Production Blueprint)

> **Revision 2 — Forensic Gap Corrections Applied**
> Addresses all 8 gaps, 4 phantom assumptions, and 3 uncovered failure modes.
> Cross-referenced against `iris_mcp_memory_evaluation.md` as the architectural north star.

This implementation plan outlines the step-by-step engineering sequence to execute **Option A: Fused In-Process Gateway, SQLCipher Migration, and Organic Lifecycle Redesign**. It represents a pristine, highly detailed blueprint to migrate, sanitize, and unify the memory core of IRISVOICE, ensuring the agent is fully equipped to graduate to its own workspace terminal for self-development.

> [!IMPORTANT]
> **GOAL: above 98% Runtime Success Rate**
> We have designed this plan to eliminate brittle external processes, prevent synchronization deadlocks, and preserve the organic biological metaphors of the system (Mycelium, Kyudo, Immortus, Pacman). Every layer is mapped out in this blueprint, including explicit mitigations for critical engineering failure modes.

---

## 0. Source Material Reference Map

All code being ported into IRISVOICE originates from two external repositories. This table maps every source artifact to its destination so no experimental work is reimplemented from scratch.

| Source Artifact | Source Path | Destination in IRISVOICE | Phase |
|:---|:---|:---|:---:|
| `compute_expansion_v2()` | `C:\Users\midas\AGENT\data\eml_reasoning\harness\calibrate_dynamic_eml.py` | `backend/agent/eml_engine.py` | 1.5 |
| `compute_compression_v2()` | Same as above | `backend/agent/eml_engine.py` | 1.5 |
| `compute_reasoning_v2()` | Same as above | `backend/agent/eml_engine.py` | 1.5 |
| `eml_op(x, y) = exp(x) - ln(y)` | `C:\Users\midas\AGENT\data\eml_reasoning\harness\scoring.py` | `backend/agent/eml_engine.py` | 1.5 |
| `AutoRecorder` class | `C:\Users\midas\AGENT\data\eml_reasoning\harness\auto_record.py` | `backend/gateway/auto_recorder.py` | 1.5 |
| `detect_test_result()` parsers | Same as above | `backend/gateway/auto_recorder.py` | 1.5 |
| `is_test_command()` patterns | Same as above | `backend/gateway/auto_recorder.py` | 1.5 |
| `memory_chain` + `memory_chain_v2` schema | `C:\Users\midas\MCM-EML-SDK\mcm\schema.py` (lines 239-269) | `backend/memory/db.py` schema init | 1 |
| `MCMProxy._int()` interception pattern | `C:\Users\midas\MCM-EML-SDK\mcm\proxy_core.py` | `backend/iris_gateway.py` interceptor | 2 |
| `MCMProxy._ctx()` context enrichment | Same as above | `backend/agent/eml_engine.py` | 2 |
| Calibration ground truth | `C:\Users\midas\AGENT\data\eml_reasoning\output\calibration_results.json` | `backend/tests/fixtures/eml_calibration.json` | 1.5 |

---

## 1. High-Level Architecture & Layered System Checklist

The upgraded FUSION memory core operates entirely in-process inside the Tauri application backend. The following checklist defines the precise operational bounds and responsibilities of each architectural layer:

### [ ] Layer 1: Storage Core (`backend/memory`)
- **SQLCipher AES-256 Engine:** Integrates hardware-accelerated encryption on the unified memory database using biometric runtime keys supplied by the Tauri host. **Single database file** opened via `open_encrypted_memory(db_path, biometric_key)` — there is NO separate `coordinates.db` / `mycelium.db` split.
- **Universal `system_events` Schema:** Houses all system interactions across four domains (`CODE`, `TASK`, `SYSTEM`, `USER`) in a unified, scrubbed table with a **dynamic `interaction_payload`** JSON field (see §4.5 Dynamic Parameter Mapping).
- **Immortus `memory_chain` Table:** Creates the `memory_chain` table (schema ported from `MCM-EML-SDK/mcm/schema.py` lines 239-269) to persist Immortus thread lineage. Immortus is the **4D temporal layer over the 3D Mycelium coordinate system** — it allocates for time across sessions. Without this persistence, Immortus is stateless across compressions.
- **`chain_append()` / `chain_distill()` Implementation:** Implements these two methods on the MCM store so that `mcm.py:L126-L139` no longer silently fails at the except block.
- **Automatic Reference Cleaning:** Implements `validate_memory_chain_references()` inside DB maintenance routines, marking orphaned references as `stale = 1` rather than rewriting historical logs.
- **No Performance Regressions:** Retains standard transactional safety, keeping index querying SLAs below $50\text{ ms}$.

### [ ] Layer 2: In-Process Gateway & IrisFileObserver (`backend/gateway`)
- **Tauri IPC / WS Interceptor:** Modifies `backend/ws_manager.py` (at repo root — NOT `backend/gateway/ws_manager.py` which does not exist) and `backend/iris_gateway.py` to transparently capture file edits, command execution outputs (pytest, npm test, cargo test, etc.), and agent state updates.
- **Zero-Trust Sanitization Gate:** Extends the **existing** `backend/gateway/security_filter.py` (465 lines — `SecurityFilter` + `MCPSecurityManager` + `SecurityAuditLogger`) with a new `sanitize_payload()` method for dual-pass credential scrubbing. **No new parallel `security_sanitizer.py` file is created.**
- **IrisFileObserver (Custom Lightweight Watcher):** Replaces the external `watchdog` library dependency with a custom `IrisFileObserver` class using Win32 `ReadDirectoryChangesW` via `ctypes` — zero external dependencies. Includes built-in debouncing ($250\text{ ms}$ quiet window), hard ignorelist, and extension filtering. Design is modeled on the interception pattern from `MCM-EML-SDK/mcm/proxy_core.py` (which intercepts tool calls at the JSON-RPC level). The existing `backend/dev/file_watcher.py` continues to serve developer mode only.
- **Degraded Fallback Queue:** Automatically buffers logs in a memory-only deque during client disconnects, draining them asynchronously once connection recovers.

### [ ] Layer 3: Pacman Loop (Context Recycling)
- **Transparent Digestion:** The gateway interceptor automatically streams intercepted conversation turns and tool executions to `episodic.fragment_and_store(...)` in a background executor thread, removing manual recording tasks.
- **Automated Metabolism:** The metabolic decay (`cleanup_stale_chunks()`) is triggered by the `QuorumSensor` during the pre-flight check gate, checking for chunks older than $72\text{ hours}$ with low usage metrics.
- **Dynamic Crystallization:** Automatically promotes highly retrieved chunks (retrieval count $\ge 5$) to stable landmarks via Mycelium indexing, safeguarding them from decay.

### [ ] Layer 4: DER Loop (Director-Explorer-Reviewer)
- **Dual Data Source Boundary:** The `Reviewer` class continues to read from `context_package` (Mycelium graph: `gradient_warnings`, `active_contracts`). Only the Director's outcome classification switches to `system_events`. These sources are NOT merged.
- **Immortus Chain Feed:** When Immortus is active (depth ≥ 3), auto-recorded `system_events` are also fed into `chain_append()` so the thread lineage captures automated edit/test signals alongside manual MCM compressions.
- **Reviewer Immune Check:** The `QuorumSensor` (classes: `CellWall`, `QuorumReorganization`, `TaskClassifier`, `PredictiveLoader`) runs in the pre-call flow to vet steps.
- **No Agent Interruption:** Eliminates agent-visible bookkeeping instructions (`record_edit`, `record_test`, `mcm_compress`), saving up to $\sim 300$ tokens per ReAct cycle.
- **EML Governor:** EML's expansion/compression signal modulates Immortus's `DRIFT_CRITICAL` constant dynamically, acting as the governor that prevents speculative branches from exploding or stalling.

### [ ] Layer 5: EML-Immortus Synergy (Decision Router)
- **Calibrated v2 Formula:** Ports the validated `compute_expansion_v2()` / `compute_compression_v2()` from the AGENT harness — NOT the legacy R1/R2 functions. Includes three critical bug fixes (timestamp fallback, edit-weighting inversion, zero-dominance).
- **Table Remapping:** `file_nodes` → `mycelium_nodes`, `code_events` → `system_events`, `landmarks` → `mycelium_landmarks`. The `activation_count`, `confidence`, `topology_primitive` fields exist on `mycelium_nodes` (ported via Phase 6 migrations in the SDK).
- **EML Dynamic Synergy:** Maps $\text{EML}(x, y) = e^x - \ln(y)$:
  - *High Exploration ($x \ge 0.60$):* $d_{\text{limit}} = 0.50$, Depth $D \ge 5$, Synthetic Trail weight $+0.25$.
  - *High Compression ($y \ge 0.70$):* $d_{\text{limit}} = 0.30$, Momentum $m \leftarrow \min(1.0, m + 0.10)$.
  - *Neutral/Balanced:* $d_{\text{limit}} = 0.40$, Depth $D = 3$, Momentum decays $-0.05$/turn.
- **Cold-Start Tree → Calibrated Handoff:** Turns 1-3 use `MathEMLTree` (tagged `[preliminary]`). At turn ≥ 4 with ≥ 3 DB events, switches to calibrated v2.
- **Divergence Detection:** Tree recommends expand but calibrated demands compress → inject: `eml: 1.10 (compress) | tree: expand (divergent) | N edits, M tests | NEXT -> [file]`
- **Route Pivot Fallback:** Triggers speculative branch rollback to the nearest stable landmark if Drift exceeds $d_{\text{limit}}$.

### [ ] Layer 6: Opt-In Swarm Coordinator (`backend/agent/swarm`)
- **Decoupled Synchronization:** Spawns sync hooks only when `swarm_mode = True`, leaving single-agent execution lightweight.
- **Existing Schema Preserved:** Uses the existing `task_collaboration` and `swarm_join_signals` tables in `backend/memory/db.py` (lines 474-506). **No parallel `swarm_collaborations` table is created.** If additional columns are needed (e.g., `coordinate_code`), they are added via `ALTER TABLE` on existing tables.
- **Task-ID Serialization:** Each agent receives a `task_id` tied to the execution plan, which naturally serializes writes in the common single-agent case. The `BEGIN IMMEDIATE TRANSACTION` wrapper handles rare multi-agent contention without requiring `busy_timeout` overhead in the default path.

---

## 2. Redesign Blueprint: Pacman & DER Loops

To adapt to the transparent auto-recording paradigm, the Pacman and DER loops must undergo structural modifications to operate without manual intervention.

### 2.1 The Pacman Context Recycling Loop

```
  [Tauri Gateway Interceptor] ──► [Background Executor Thread]
               │                                │
               ▼ (Conversations / Tool Outputs)  ▼
  [Pacman Digestion: episodic.fragment_and_store(content, session_id)]
               │
               ▼ (Stored in context_chunks)
  [QuorumSensor: Pre-Call / Pre-Flight Gate]
               │
               ├─► [Crystallization: retrieval_count >= 5] ──► Promote to Landmark
               │
               └─► [Metabolism: age > 72h AND retrievals <= 0] ──► Prune from DB
```

#### Pacman Redesign Checklist:
1.  **Eliminate Manual Prompts:** Remove explicit instructions for the agent to compress context manually. The agent focuses exclusively on the user goal.
2.  **In-Process Gateway Digestion:**
    - Capture conversation segments and tool outputs in `backend/ws_manager.py` and route through `backend/iris_gateway.py`.
    - Offload digestion to `episodic.fragment_and_store(content, session_id)` in a fire-and-forget background execution pool (`concurrent.futures.ThreadPoolExecutor`).
    - **Commit Fence:** The executor callback calls `db.commit()` BEFORE returning, so the DER Director never reads stale `system_events` data.
3.  **Automated Pre-Call Metabolism:**
    - Wire `episodic.cleanup_stale_chunks()` to run during the Kyudo `pre_call_flow` checking routine.
    - Set the standard metabolic parameters: decay chunks older than $72\text{ hours}$ if they have $0$ retrievals. Chunks that are adjacent to crystallization candidates (retrieval count $\ge 5$) are preserved forever.
4.  **Organic Crystallization Pathway:**
    - When `retrieve_context_chunks()` returns semantically matching fragments for the query, automatically increment their `retrieval_count` in a unified database transaction.
    - If a fragment's retrieval count hits the crystallization threshold ($\ge 5$), trigger an asynchronous index call to `self._mycelium.episode_indexer.index_episode()` to elevate the fragment to a permanent landmark node in the Mycelium space.

---

### 2.2 The DER Loop (Director-Explorer-Reviewer)

```
  [ExecutionPlan] ──► [Director Queue]
                             │
                             ▼
  [QuorumSensor Pre-Flight Checks (G1-G13)] ──► Fail? ──► [Halt / Self-Heal]
                             │ Pass
                             ▼
  [Reviewer Gating (Heuristic + Live Context)] ──► VETO? ──► [Queue Alternative]
                             │ Pass
                             ▼
  [Explorer Execution (Transparent Auto-Recording Proxy)]
                             │
                             ▼ (Captures command outcome and exit code)
  [System Events Database: record_test / record_edit]
                             │
                             ▼ (Reads real-time EML metrics)
  [EML Synergy Governor] ──► Modulates Immortus Drift & Momentum (Exploration vs. Verification)
```

#### DER Loop Redesign Checklist:
1.  **Bookkeeping Simplification:** Remove manual `record_edit` and `record_test` tools. All edits and test runs are captured automatically by the gateway `AutoRecorder`.
2.  **Dual Data Source Boundary (Gap 6 Fix):**
    - The **Reviewer** continues to read from `context_package` (Mycelium graph). It uses `gradient_warnings` and `active_contracts` for mature graph reviews, and `_heuristic_review` fast path for immature graphs with destructive operation detection. These sources remain unchanged.
    - The **Director** reads outcomes from `system_events` to classify step success/failure. It checks the table for records matching the current `session_id` and the step's file paths.
    - **Rule:** Do NOT merge these data sources. The Reviewer reads live graph state. The Director reads recorded outcomes.
3.  **Immortus Chain Integration (Gap 6 Fix):**
    - When Immortus is active (depth ≥ 3), auto-recorded `system_events` are also fed into `chain_append()` so the thread lineage captures automated edit/test signals alongside manual MCM compressions.
    - EML's expansion/compression signal modulates Immortus's `DRIFT_CRITICAL` constant dynamically.
4.  **EML Signal Governance:**
    - At the start of each ReAct iteration, the Director queries `system_events` to compute EML parameters via `eml_engine.compute_reasoning_v2()`.
    - The `compute_expansion_v2()` function reads from `mycelium_nodes` (activation_count, topology_primitive) and recent exploration events in `system_events`.
    - The `compute_compression_v2()` function reads from `mycelium_landmarks` (pass_count, is_permanent) and recent edit/test events.
    - If $x \ge 0.60$ (High Expansion): Relax $d_{\text{limit}}$ to $0.50$, increase search depth.
    - If $y \ge 0.70$ (High Compression): Tighten $d_{\text{limit}}$ to $0.30$, boost momentum.
5.  **Automatic Disconnect Recovery:**
    - The loop checks the client heartbeat via `_session_has_client()`. If WebSocket clients disconnect during execution, the loop gracefully stops, records a partial success log to `system_events`, and buffers pending workspace updates in the degraded queue.

---

## 3. Engineering Risks, Bottlenecks, and Mitigations

To guarantee an above 98% runtime success rate, we have identified five major engineering failure modes and built explicit mitigations directly into our in-process architecture:

### 3.1 SQLite Multi-Agent Write Conflicts
- **Problem:** When multiple swarm agents or background tracking tasks write to the encrypted database simultaneously, SQLite throws a `database is locked` error.
- **Mitigation:**
  1. Each agent receives a `task_id` tied to the plan, providing natural write serialization in single-agent mode (the common case).
  2. Implement a unified serialization wrapper using `BEGIN IMMEDIATE TRANSACTION;` for all write operations, forcing SQLite to acquire write-locks instantly instead of deferring them.
  3. If a write fails due to lock contention, catch the exception, write the event payload to an in-memory cache, raise an `MCM:99X_LOCK_DEGRADED` warning to the UI, and automatically merge the cached logs once the lock is released.
  4. **Note:** `PRAGMA busy_timeout` is intentionally NOT added to the default path to avoid masking contention issues. The task-ID serialization makes it unnecessary for normal operation. If future swarm testing reveals sustained multi-agent contention, this PRAGMA can be re-evaluated as a targeted addition to swarm-mode-only connections.

### 3.2 IrisFileObserver I/O Thrashing during Mass Edits
- **Problem:** Running massive operations (like `npm install` or checking out a new git branch) triggers thousands of rapid file-system write events, flooding the gateway, spiking CPU, and locking the database.
- **Mitigation (Custom IrisFileObserver — replaces watchdog dependency):**
  1. **Win32 Native Implementation:** Uses `ReadDirectoryChangesW` via `ctypes` — zero external package dependencies. This avoids the known issue where `watchdog` can fail silently inside PyInstaller-frozen binaries due to working directory and file handle differences.
  2. **Debounced Event Processor:** Queues raw events and only fires the database logger after a **$250\text{ ms}$ quiet window** of file inactivity.
  3. **Hard Ignorelist:** `"node_modules", ".git", ".gemini", ".pytest_cache", "logs", "__pycache__", "*.db", "*.db-wal", "*.db-shm"`
  4. **Extension Allowlist:** Only tracks code-relevant extensions: `*.py, *.js, *.ts, *.tsx, *.html, *.css, *.json, *.rs, *.sql, *.toml, *.yaml`.
  5. **Fallback:** If `ReadDirectoryChangesW` is unavailable (non-Windows), falls back to a lightweight polling loop ($1\text{s}$ interval, stat-based change detection).

### 3.3 Nested Credential Escapes in JSON Payloads
- **Problem:** Sensitive environment variables or secret keys hidden inside deeply nested JSON payloads or raw CLI stdout buffers bypass standard top-level string regex sanitizers, getting written to disk.
- **Mitigation:**
  - Extend the existing `backend/gateway/security_filter.py` with a **Dual-Pass In-Memory Sanitization** method (`sanitize_payload()`):
    - **Pass 1 (Flat Regex Scrub):** Pre-compiled regex expressions scan the entire flat payload string to intercept plain matches (Google, Anthropic, OpenAI, Private Keys, DB URIs).
    - **Pass 2 (Recursive JSON Tree Traversal):** If the payload is parsed as JSON, the sanitizer recursively traverses the dictionary/list hierarchy. It checks all keys against a strict blocklist (`"api_key", "secret", "password", "token", "auth"`) and replaces their values with `[REDACTED_SECURITY_BOUNDARY]`, ensuring nested JSON objects are fully scrubbed.
  - This integrates with the existing `SecurityAuditLogger` for audit trail continuity.

### 3.4 Memory Leakage during Massive Codebase Walks
- **Problem:** Compiling massive file graphs or traversing deeply nested Mycelium relationships over long-running sessions causes memory usage to climb due to lingering node caches, leading to process crashes.
- **Mitigation:**
  - Establish a maximum cache boundary for `MyceliumStore` in-memory structures.
  - Implement a simple **LRU Cache Eviction Policy** for node relationships (capping the in-memory graph at $10,000$ active edges).
  - Explicitly invoke the Python garbage collector (`import gc; gc.collect()`) inside the gateway `post_turn_flow` whenever memory compaction or database optimization runs.

### 3.5 Sudden WebSocket Client Disconnects
- **Problem:** If the Tauri UI window is refreshed or a network hiccup occurs, the WebSocket connection drops, interrupting active tool execution and causing subsequent log writes to crash the gateway process.
- **Mitigation:**
  - Decouple the execution engine from the active WS channel.
  - The gateway WebSocket manager buffers all stdout and telemetry outputs in a local **Degraded Pending Queue** (`degraded_pending_queue`) when no client is connected.
  - When the client re-establishes a WebSocket connection with the active `session_id`, the manager automatically drains and streams the buffered execution logs to the UI, ensuring seamless persistence and visibility.

### 3.6 Async/Sync Boundary Mismatch (Uncovered Failure Mode)
- **Problem:** `ImmortusBrain.evaluate()` is `async`. The `MCMOrchestrator` workflows are synchronous. If `episodic.fragment_and_store()` is called from a `ThreadPoolExecutor` but the DER Director queries `system_events` synchronously, there's a race condition: the Director may read stale data because the background thread hasn't committed yet.
- **Mitigation:**
  1. Add a `db.commit()` fence in the ThreadPoolExecutor callback BEFORE returning.
  2. Add a brief `await asyncio.sleep(0)` yield point in the DER loop after checking `system_events` to allow the event loop to flush pending writes.

### 3.7 SQLCipher Thread Safety (Uncovered Failure Mode)
- **Problem:** The `EpisodicStore` takes a `db` connection at init. If the gateway's background executor calls `fragment_and_store()` on a separate thread, SQLite throws `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`. The sqlite3 fallback in `db.py:L94` sets `check_same_thread=False`, but the SQLCipher path does NOT.
- **Mitigation:**
  - Add `check_same_thread=False` equivalent to the sqlcipher3 connection path in `open_encrypted_memory()`.
  - Alternative: ensure the ThreadPoolExecutor creates its own connection via a connection-per-thread pool.

---

## 4. Layer-by-Layer Database Schemas & Code Modifications

### 4.1 Schema Migration

#### [NEW] `backend/memory/migrations/001_fusion_migration.sql`

```sql
-- Migration 001: FUSION Schema — memory_chain + system_events
-- NOTE: No swarm_collaborations table. Existing task_collaboration table is extended.

-- ═══════════════════════════════════════════════════════════════════════════
-- Immortus Memory Chain (ported from MCM-EML-SDK/mcm/schema.py lines 239-269)
-- This is the 4D temporal layer over the 3D Mycelium coordinate system.
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS memory_chain (
    entry_id        TEXT DEFAULT NULL,
    thread_id       TEXT NOT NULL,
    session_id      TEXT DEFAULT NULL,
    sequence        INTEGER NOT NULL,
    role            TEXT NOT NULL,        -- 'action' | 'observation' | 'compress' | 'system'
    content         TEXT NOT NULL,
    metadata        TEXT DEFAULT '{}',    -- JSON: coords_from, coords_to, nbl_outcome, insight
    session_ts      REAL DEFAULT NULL,
    result          TEXT DEFAULT NULL,    -- 'landmark' | 'warning' | 'pivot' | 'success' | 'failure'
    stale           INTEGER DEFAULT 0,   -- 1 = orphaned reference (G13 validation)
    distilled       INTEGER DEFAULT 0,   -- 1 = compressed by chain_distill()
    created_at      REAL NOT NULL,
    PRIMARY KEY (thread_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_memory_chain_thread ON memory_chain(thread_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_chain_session ON memory_chain(session_id);
CREATE INDEX IF NOT EXISTS idx_memory_chain_stale ON memory_chain(stale);

-- ═══════════════════════════════════════════════════════════════════════════
-- Universal System Events — dynamic payload schema per domain
-- ═══════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS system_events (
    event_id TEXT PRIMARY KEY,              -- Secure UUIDv4
    session_id TEXT NOT NULL,               -- Links to thread/conversation
    event_domain TEXT NOT NULL,             -- 'CODE' | 'TASK' | 'SYSTEM' | 'USER'
    event_type TEXT NOT NULL,               -- Domain-specific (see §4.5)
    actor TEXT NOT NULL,                    -- 'user' | 'agent_kernel' | 'gateway' | 'system'
    outcome TEXT DEFAULT 'pending',         -- 'success' | 'failure' | 'pending'
    sanitization_state TEXT NOT NULL,       -- 'clean' | 'scrubbed'
    summary TEXT NOT NULL,                  -- Human-readable summary
    interaction_payload TEXT,               -- Dynamic JSON (see §4.5)
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sysevents_session ON system_events(session_id);
CREATE INDEX IF NOT EXISTS idx_sysevents_domain ON system_events(event_domain, event_type);
CREATE INDEX IF NOT EXISTS idx_sysevents_created ON system_events(created_at DESC);

-- ═══════════════════════════════════════════════════════════════════════════
-- Extend existing swarm tables (NOT a new table)
-- ═══════════════════════════════════════════════════════════════════════════
ALTER TABLE task_collaboration ADD COLUMN coordinate_code TEXT DEFAULT NULL;
```

### 4.2 Security Sanitization (Extend Existing Module)

#### [MODIFY] `backend/gateway/security_filter.py`

Add a new `sanitize_payload()` method to the existing `SecurityFilter` class. This preserves the existing audit trail (`SecurityAuditLogger`) and rate limiting infrastructure while adding deep JSON scrubbing:

```python
# Added to existing SecurityFilter class in security_filter.py

def sanitize_payload(self, payload: Union[str, Dict, List]) -> Tuple[str, str]:
    """Dual-pass scrub: flat regex + recursive JSON tree traversal.
    Returns (sanitized_string, state) where state = 'clean' | 'scrubbed'.
    Integrates with existing SecurityAuditLogger for audit trail.
    """
    # Pass 1: Flat regex scrub against SECRET_PATTERNS
    # Pass 2: Recursive JSON tree traversal against KEY_BLOCKLIST
    # (Implementation identical to evaluation §3.5.1 spec)
    ...
```

**No new `security_sanitizer.py` file is created.** The dual-pass logic lives as a method on the existing filter.

### 4.3 Immortus Chain Persistence (Gap 2 + Gap 8 Fix)

#### [MODIFY] `backend/memory/mycelium_store.py`

Implement the two methods that `mcm.py:L126-L139` already calls but which have no implementation:

```python
def chain_append(self, thread_id: str, result: str, coords_from: list,
                 coords_to: list, nbl_outcome: str, insight: str) -> None:
    """Persist a memory chain entry for Immortus thread lineage."""
    import json, time
    from uuid import uuid4
    seq = self.db.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM memory_chain WHERE thread_id = ?",
        (thread_id,)
    ).fetchone()[0]
    self.db.execute(
        """INSERT INTO memory_chain
           (entry_id, thread_id, sequence, role, content, metadata, result, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (uuid4().hex, thread_id, seq, "compress", insight,
         json.dumps({"coords_from": coords_from, "coords_to": coords_to,
                     "nbl_outcome": nbl_outcome}),
         result, time.time())
    )
    self.db.commit()

def chain_distill(self, thread_id: str, threshold: int = 50) -> None:
    """Compress old chain entries when count exceeds threshold.
    Marks oldest entries as distilled=1 rather than deleting history."""
    count = self.db.execute(
        "SELECT COUNT(*) FROM memory_chain WHERE thread_id = ? AND distilled = 0",
        (thread_id,)
    ).fetchone()[0]
    if count > threshold:
        self.db.execute(
            """UPDATE memory_chain SET distilled = 1
               WHERE thread_id = ? AND distilled = 0
               AND sequence NOT IN (
                   SELECT sequence FROM memory_chain
                   WHERE thread_id = ? AND distilled = 0
                   ORDER BY created_at DESC LIMIT ?
               )""",
            (thread_id, thread_id, threshold)
        )
        self.db.commit()
```

Also add:
```python
def validate_memory_chain_references(self) -> int:
    """G13: Mark orphaned landmark/file references as stale."""
    cursor = self.db.execute("""
        UPDATE memory_chain SET stale = 1
        WHERE stale = 0 AND metadata LIKE '%landmark_id%'
        AND json_extract(metadata, '$.landmark_id') NOT IN
            (SELECT landmark_id FROM mycelium_landmarks)
    """)
    self.db.commit()
    return cursor.rowcount
```

### 4.4 Unified Event Logger

#### [MODIFY] `backend/memory/mycelium_store.py`

```python
def log_system_event(self, session_id: str, domain: str, event_type: str,
                     actor: str, summary: str, payload: Any,
                     outcome: str = "pending") -> str:
    """Sanitize payload in-memory and persist to system_events.
    Uses the existing SecurityFilter.sanitize_payload() for scrubbing."""
    from backend.gateway.security_filter import get_security_filter
    import uuid, time

    event_id = str(uuid.uuid4())
    sf = get_security_filter()
    scrubbed_payload_str, state = sf.sanitize_payload(payload)

    try:
        self.db.execute(
            """INSERT INTO system_events
               (event_id, session_id, event_domain, event_type, actor,
                outcome, sanitization_state, summary, interaction_payload, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (event_id, session_id, domain, event_type, actor,
             outcome, state, summary, scrubbed_payload_str, time.time())
        )
        self.db.commit()
        return event_id
    except Exception as e:
        logger.error(f"[MyceliumStore] System event log failed: {e}")
        return ""
```

### 4.5 Dynamic Parameter Mapping Schema (Gap 7 — CRITICAL)

The `interaction_payload` JSON field in `system_events` must be **dynamic** — adapting its structure to whatever task the agent is working on (code, web, search, project management, etc.). The schema gives enough detail to the event being recorded for the EML engine to derive its `x` and `y` parameters downstream.

#### Domain-Specific Payload Schemas:

**CODE domain — `file_edit`:**
```json
{
  "file_path": "/path/to/file.py",
  "file_hash": "sha256:abc123...",
  "edit_type": "edit_file|write_file|create_file",
  "tool": "edit_file",
  "coordinates": {"x": 0.45, "y": 0.20, "z": 0.67},
  "lines_changed": 15,
  "language": "python"
}
```

**CODE domain — `test_run`:**
```json
{
  "command": "python -m pytest tests/ -v",
  "exit_code": 0,
  "test_result": {"passed": 12, "failed": 0, "total": 12},
  "covers_files": ["src/main.py", "src/utils.py"],
  "duration_ms": 2340,
  "framework": "pytest"
}
```

**TASK domain — `task_start` / `milestone_reached`:**
```json
{
  "task_id": "uuid",
  "plan_depth": 3,
  "step_index": 2,
  "description": "Implement auth middleware",
  "dependencies": ["step_1_db_schema"],
  "estimated_complexity": "medium"
}
```

**SYSTEM domain — `compaction_run` / `maintenance`:**
```json
{
  "operation": "cleanup_stale_chunks",
  "chunks_removed": 14,
  "chunks_crystallized": 3,
  "duration_ms": 120,
  "db_size_bytes": 4521984
}
```

**USER domain — `voice_command` / `search_query`:**
```json
{
  "input_type": "voice|text|search",
  "query": "find authentication handler",
  "results_count": 5,
  "context": "web_browsing|code_search|project_management"
}
```

#### Key Design Principle:
The payload schema is NOT fixed. Each domain/event_type combination defines its own required and optional fields. The `AutoRecorder` (§4.6) populates the fields it can observe. The EML engine reads whatever fields are present to compute signals — it gracefully handles missing fields with sensible defaults.

### 4.6 AutoRecorder Integration (Gap 1 — CRITICAL)

#### [NEW] `backend/gateway/auto_recorder.py`

Ported from `C:\Users\midas\AGENT\data\eml_reasoning\harness\auto_record.py` with adaptations for IRISVOICE's table schema:

```python
"""
AutoRecorder — Ported from AGENT/data/eml_reasoning/harness/auto_record.py
Automatically records events to system_events based on observed agent behavior.
No explicit record_edit/record_test calls required.
"""
import hashlib, json, re, time
from typing import Optional, Dict, Any, Set

# Test command patterns (from auto_record.py — expanded)
_TEST_PATTERNS = [
    "pytest", "python -m pytest", "python -m unittest", "unittest",
    "npm test", "jest", "mocha", "vitest", "go test", "cargo test",
    "bundle exec rspec", "rspec", "phpunit", "dotnet test",
]

class AutoRecorder:
    """Observes tool calls, auto-records to system_events via MyceliumStore.
    Preserves dedup logic: if agent explicitly calls legacy record tools,
    the auto-recorder yields priority to avoid double-recording."""

    def __init__(self, store=None):
        self._store = store
        self._pending_edits: Dict[str, Dict] = {}
        self._explicit_record_edit: Set[str] = set()  # dedup set
        self._explicit_record_test: Set[str] = set()

    def observe_edit(self, session_id: str, file_path: str, tool_name: str,
                     success: bool = True) -> None:
        """Called by gateway interceptor after successful edit/write."""
        if file_path in self._explicit_record_edit:
            return  # Agent handled it explicitly
        file_hash = self._compute_file_hash(file_path)
        self._store.log_system_event(
            session_id=session_id,
            domain="CODE",
            event_type="file_edit",
            actor="gateway",
            summary=f"Auto-recorded: {tool_name} on {file_path.split('/')[-1]}",
            payload={
                "file_path": file_path,
                "file_hash": file_hash,
                "edit_type": tool_name,
                "tool": tool_name,
            },
            outcome="success" if success else "failure"
        )

    def observe_test(self, session_id: str, command: str, file_path: str,
                     output: str = "", exit_code: int = 0) -> None:
        """Called by gateway interceptor after test command completes."""
        if not self._is_test_command(command):
            return
        if file_path in self._explicit_record_test:
            return
        result = self._detect_test_result(output, exit_code)
        self._store.log_system_event(
            session_id=session_id,
            domain="CODE",
            event_type="test_run",
            actor="gateway",
            summary=f"Auto-recorded test: {command.split()[0]}",
            payload={
                "command": command,
                "exit_code": exit_code,
                "test_result": result,
                "covers_files": self._infer_covered_files(file_path),
            },
            outcome="success" if exit_code == 0 else "failure"
        )

    def on_explicit_record(self, file_path: str, record_type: str) -> None:
        """Agent explicitly called legacy record tool — mark as handled."""
        if record_type == "edit":
            self._explicit_record_edit.add(file_path)
        else:
            self._explicit_record_test.add(file_path)

    # ── Private helpers (ported from auto_record.py) ──
    @staticmethod
    def _is_test_command(command: str) -> bool: ...
    @staticmethod
    def _detect_test_result(output: str, exit_code: int) -> Dict: ...
    @staticmethod
    def _compute_file_hash(file_path: str) -> str: ...
    @staticmethod
    def _infer_covered_files(file_path: str) -> list: ...
```

### 4.7 In-Process Interceptor Integration

#### [MODIFY] `backend/iris_gateway.py`

The interception hooks are added to `iris_gateway.py` (the main message router — 4156 lines). The pattern follows `MCM-EML-SDK/mcm/proxy_core.py` `_int()` method: intercept tool responses AFTER they succeed, then fire-and-forget the recording.

```python
# Inside the message routing logic of IrisGateway:

async def _intercept_tool_response(self, session_id: str, tool_name: str,
                                    args: dict, result: dict) -> None:
    """Post-execution interceptor — fires AutoRecorder on success."""
    if tool_name in ("edit_file", "write_file", "create_file"):
        file_path = args.get("file_path", args.get("path", ""))
        if file_path and result.get("success", True):
            self._executor.submit(
                self._auto_recorder.observe_edit,
                session_id, file_path, tool_name, True
            )
    elif tool_name == "run_command":
        command = args.get("command", "")
        exit_code = result.get("exit_code", -1)
        output = result.get("output", "")
        self._executor.submit(
            self._auto_recorder.observe_test,
            session_id, command, "", output, exit_code
        )
```

---

## 5. Phase 1.5: EML Engine Porting (Gap 1 — CRITICAL)

This is the highest-leverage task in the entire plan. The experimental data is validated (97% calibration accuracy, +40% compliance) but requires a concrete porting strategy from the AGENT harness into IRISVOICE.

### 5.1 Port Scope

#### [NEW] `backend/agent/eml_engine.py`

This file contains the calibrated v2 EML formulas adapted to IRISVOICE's schema:

| Function | Source | Table Remapping |
|:---|:---|:---|
| `eml_op(x, y)` | `scoring.py:L25-L29` | None (pure math) |
| `compute_expansion_v2()` | `calibrate_dynamic_eml.py:L29-L74` | `file_nodes` → `mycelium_nodes`, `code_events` → `system_events` |
| `compute_compression_v2()` | `calibrate_dynamic_eml.py:L77-L121` | `landmarks` → `mycelium_landmarks`, `code_events` → `system_events` |
| `compute_reasoning_v2()` | `calibrate_dynamic_eml.py:L126-L169` | None (operates on computed signals) |

### 5.2 Critical Bug Fixes Preserved

These corrections from Round 2-3 calibration MUST be preserved in the port:

1. **Timestamp Fallback:** When no events have real timestamps (`created_at > 1700000000`), count ALL events as recent rather than returning 0. Without this, cold-start sessions get permanent `expansion = 0`.
2. **Edit Weighting Inversion:** Edits boost **compression** (they're verification activity), NOT expansion. The R1 formula had this inverted. In v2, edits appear in `compute_compression_v2()` tertiary weight, not in expansion.
3. **Zero-Dominance:** When one signal is essentially zero (`< 0.02`) and the other has data (`>= 0.05`), default to the side with data. Without this, the system returns "balanced" when it should clearly be "expand" or "compress".
4. **Landmark Floor:** Permanent landmarks force a minimum compression of `0.60`. This prevents the formula from incorrectly suggesting expansion on fully-verified code.

### 5.3 Cold-Start → Calibrated Handoff

```
Turn 1-3: MathEMLTree deterministic fallback
           ↓ (tagged [preliminary] in context)
Turn 4+:  Switch to calibrated v2 formula
           IF system_events count >= 3 for this session
           ELSE remain on tree
```

### 5.4 Wiring into ImmortusBrain

```python
# In ImmortusBrain.evaluate() — after computing EML signal:
reasoning = eml_engine.compute_reasoning_v2(expansion, compression)

if reasoning["action"] == "expand" and expansion >= 0.60:
    self.DRIFT_CRITICAL = 0.50  # relax leash
    self.search_depth = max(5, self.search_depth)
elif reasoning["action"] == "compress" and compression >= 0.70:
    self.DRIFT_CRITICAL = 0.30  # tighten
    self.temporal_coord.momentum = min(1.0, self.temporal_coord.momentum + 0.10)
else:
    self.DRIFT_CRITICAL = 0.40  # neutral
```

### 5.5 Unit Tests (Using Calibration Ground Truth)

Copy `C:\Users\midas\AGENT\data\eml_reasoning\output\calibration_results.json` to `backend/tests/fixtures/eml_calibration.json`. Write tests that:
- Validate `compute_expansion_v2()` returns expansion-heavy for files with high activation but no landmarks.
- Validate `compute_compression_v2()` returns ≥ 0.60 for files with permanent landmarks.
- Validate `compute_reasoning_v2()` matches the 97% accuracy from calibration (28/29 correct).
- Validate the cold-start handoff at turn boundary.

---

## 6. Verification & Testing Sequence

```
  Phase 1 → Phase 1.5 → Phase 2 → Phase 3 → Phase 4 → Phase 5
  Schema    EML Port    Gateway    Pacman     DER/Immortus  Build
```

### 6.1 Step 1: Schema Migration & Baseline
```powershell
python -m pytest backend/memory/tests/test_mycelium_store.py -v
python -m pytest backend/memory/tests/test_db_encryption.py -v
```
Validates: `memory_chain` table created, `system_events` table created, `task_collaboration.coordinate_code` column added, `chain_append()`/`chain_distill()` work.

### 6.2 Step 2: EML Engine Unit Tests
```powershell
python -m pytest backend/agent/tests/test_eml_engine.py -v
```
Validates: v2 formulas produce correct signals against calibration ground truth. Cold-start handoff works. Divergence detection fires correctly.

### 6.3 Step 3: Security Filter Extension
```powershell
python -m pytest backend/gateway/tests/test_security_filter.py -v
```
Validates: `sanitize_payload()` scrubs API keys, SSH keys, env vars from flat strings and nested JSON.

### 6.4 Step 4: AutoRecorder & Gateway Integration
```powershell
python -m pytest backend/gateway/tests/test_auto_recorder.py -v
```
Validates: edits auto-recorded, tests auto-recorded, dedup works (explicit record prevents double-write), dynamic payload schema populated correctly.

### 6.5 Step 5: IrisFileObserver
```powershell
python -m pytest backend/gateway/tests/test_iris_file_observer.py -v
```
Validates: Win32 `ReadDirectoryChangesW` fires on file changes, debouncing works, ignorelist filters correctly, extension allowlist enforced.

### 6.6 Step 6: DER Loop + Immortus Integration
```powershell
python -m pytest backend/tests/test_agent_loop_upgrade.py -v
```
Validates: Director reads outcomes from `system_events`. Reviewer still reads from `context_package`. EML modulates drift/momentum. Immortus chain_append captures automated signals.

### 6.7 Step 7: Pristine Graduation
```powershell
python build_pyinstaller/compile.py
```
**Additional check:** Verify `IrisFileObserver` fires correctly inside the frozen binary (no watchdog dependency to fail). Test by creating a temp file in the watched directory and asserting the event arrives within 1 second.

---

## 7. Implementation Phase Order

| Phase | Scope | Depends On | Key Deliverables |
|:---:|:---|:---:|:---|
| **1** | Schema migration + `chain_append`/`chain_distill` | — | `memory_chain` table, `system_events` table, extended swarm |
| **1.5** | EML engine port + unit tests | Phase 1 | `eml_engine.py`, calibration validation, cold-start handoff |
| **2** | Gateway interceptor + AutoRecorder + IrisFileObserver | Phase 1 | `auto_recorder.py`, `iris_file_observer.py`, interceptor in `iris_gateway.py` |
| **3** | Pacman wiring (fragment_and_store + crystallization) | Phase 2 | Background executor, commit fence, pre-call metabolism |
| **4** | DER/Immortus integration + security filter extension | Phase 1.5, 2 | Dual data source boundary, EML governor, sanitize_payload() |
| **5** | PyInstaller graduation + IrisFileObserver frozen test | Phase 1-4 | Production binary, file observer verification |

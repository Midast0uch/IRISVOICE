# Forensic Gap Analysis: Implementation Plan vs. Evaluation vs. Live Codebase

> [!IMPORTANT]
> **Verdict: The plan is structurally sound but has 7 real gaps, 4 phantom assumptions, and 3 uncovered failure modes** that would degrade the 98% success target if left unaddressed. None are architectural dealbreakers — all are fixable within the existing plan skeleton.

---

## ✅ What's Well-Covered (No Action Needed)

These areas are correctly mapped between the evaluation, the plan, and the live code:

| Area | Evidence |
|:-----|:---------|
| **Pacman fragment_and_store()** | Already implemented in [episodic.py:L555-L666](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/episodic.py#L555-L666) with dedup, batch insert, and zone classification. Plan correctly targets wiring it to gateway auto-recording. |
| **Pacman cleanup_stale_chunks()** | Already implemented in [episodic.py:L805-L853](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/episodic.py#L805-L853) with crystallization protection. Plan correctly targets wiring it to QuorumSensor pre-flight. |
| **Crystallization pathway** | Already wired in [episodic.py:L778-L795](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/episodic.py#L778-L795). When `retrieval_count >= _CRYSTALLIZE_THRESHOLD`, the chunk is promoted to Mycelium landmark via `episode_indexer.index_episode()`. |
| **SQLCipher encryption layer** | Already implemented in [db.py:L32-L103](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/db.py#L32-L103) with dev-mode sqlite3 fallback. The plan correctly builds on this existing infrastructure. |
| **Swarm coordinator decoupling** | Already properly decoupled in [coordinator.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/agent/swarm/coordinator.py). The plan's "opt-in toggle" design matches the existing implementation. |

---

## 🔴 Gap 1: EML Porting Strategy Is Underspecified — Experimental Data Is Validated but the Plan Lacks a Concrete Migration Path

**Severity: CRITICAL — this is the spine of the entire fusion.**

**Source material:** The EML reasoning signal was experimentally validated across 3 rounds of A/B testing in the `AGENT` folder:
- [scoring.py](file:///c:/Users/midas/AGENT/data/eml_reasoning/harness/scoring.py) — Core `eml_op(x, y) = exp(x) - ln(y)` operator + legacy R1/R2 expansion/compression signals
- [calibrate_dynamic_eml.py](file:///c:/Users/midas/AGENT/data/eml_reasoning/harness/calibrate_dynamic_eml.py) — Calibrated v2 formula with 3 critical bug fixes (timestamp fallback, edit weighting inversion, zero-dominance), validated at **97% accuracy** (28/29) against production DB snapshot
- [auto_record.py](file:///c:/Users/midas/AGENT/data/eml_reasoning/harness/auto_record.py) — Complete `AutoRecorder` class with `observe_edit()`, `observe_test()`, `flush_edits()`, dedup against explicit agent calls, and test output parsing for pytest/jest/unittest/cargo
- [ANALYSIS_ROUND_3.md](file:///c:/Users/midas/AGENT/data/eml_reasoning/output/ANALYSIS_ROUND_3.md) — Final experiment showing **+40% compliance on expand/balanced signals**, dynamic signal adaptation across 3-turn sessions (expand 5.16 → balanced 2.44 → compress 1.56), and 100% formula accuracy

**The Gap:** The evaluation doc (§3.4, §5.1) correctly describes EML as the dynamic cognitive governor. The plan names it as "Layer 5" but **doesn't provide a concrete file-by-file porting strategy** from the experimental harness into IRISVOICE's `backend/agent/` directory. Currently zero EML code exists in IRISVOICE — which is expected (it's experimental), but the plan needs to specify:
- **Which formula version to port:** The calibrated `compute_expansion_v2` / `compute_compression_v2` from `calibrate_dynamic_eml.py` (NOT the legacy R1/R2 functions in `scoring.py`)
- **Where it lives in IRISVOICE:** A new `backend/agent/eml_engine.py` that adapts the v2 functions to read from IRISVOICE's actual tables (`mycelium_landmarks`, `mycelium_nodes`, `context_chunks`, `system_events`) instead of the SDK's `file_nodes`/`code_events`/`landmarks` tables
- **AutoRecorder integration:** The `AutoRecorder` class from `auto_record.py` needs to be ported into the gateway interceptor — the plan describes the *concept* of auto-recording but doesn't reference this existing, tested implementation that already handles dedup, test pattern detection, and explicit-call priority
- **Cold-start tree → calibrated formula handoff:** The evaluation describes the turn 1-3 fallback but the plan doesn't address this transition
- **Divergence detection:** Tree recommends expand but calibrated DB demands compress — the plan mentions it but doesn't specify the warning injection format into the context window

**Impact on 98% target:** Without a concrete porting strategy, an implementer would either (a) rewrite the EML logic from scratch (wasting the 3 rounds of calibration work), or (b) copy the SDK code verbatim and hit table-name mismatches on first run. The v2 calibration corrections (especially the edit-weighting inversion and landmark floor at 0.60) are non-obvious — if reimplemented naively, the formula would produce the same bugs that Rounds 1-2 exposed.

**Recommendation:** The plan needs a dedicated Phase 1.5 task:
1. Port `compute_expansion_v2()` and `compute_compression_v2()` from [calibrate_dynamic_eml.py](file:///c:/Users/midas/AGENT/data/eml_reasoning/harness/calibrate_dynamic_eml.py) into `backend/agent/eml_engine.py`, remapping table references to IRISVOICE schema (`mycelium_landmarks` for `landmarks`, `mycelium_nodes` for `file_nodes`, `system_events` for `code_events`).
2. Port the `AutoRecorder` class from [auto_record.py](file:///c:/Users/midas/AGENT/data/eml_reasoning/harness/auto_record.py) into the gateway interceptor, preserving its dedup logic (`_explicit_record_edit` set) and test pattern matchers.
3. Wire EML output into `ImmortusBrain.evaluate()` to dynamically modulate `IMMORTUS_DRIFT_CRITICAL` (0.30 ↔ 0.50) and search depth (3 ↔ 5).
4. Implement the cold-start tree → calibrated handoff at turn ≥ 4.
5. Add unit tests validating both EML states using the ground truth from [calibration_results.json](file:///c:/Users/midas/AGENT/data/eml_reasoning/output/calibration_results.json).

---

## 🔴 Gap 2: `memory_chain` Table Is Essential to Immortus Thread Lineage — But Doesn't Exist in the Schema

**Severity: HIGH**

The evaluation (§4 G13) and the plan's migration script (§4.1) both assume a `memory_chain` table exists with columns `landmark_id`, `coords_from`, `file_path`, `thread_id`, and `stale`. The migration adds `ALTER TABLE memory_chain ADD COLUMN stale INTEGER DEFAULT 0;`.

**What `memory_chain` actually IS:** Immortus is not just a speculative router — it's a **deep memory chain**. The [ImmortusSession](file:///c:/Users/midas/Desktop/IRISVOICE/backend/agent/immortus/session.py#L18) explicitly documents `thread_id` as the "Unique thread for this lineage in memory_chain." The [MCM compress](file:///c:/Users/midas/Desktop/IRISVOICE/backend/agent/mcm.py#L126-L139) method writes chain entries on every compression checkpoint via `self._store.chain_append()`, linking coordinate traversals (`coords_from`, `coords_to`), NBL outcomes, and insights into a persistent thread lineage. The [NBL builder](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/nbl.py#L97-L107) reads from `memory_chain WHERE thread_id = ?` to display `CHAIN: entries:N landmarks:M` in the agent's context window.

**Reality:** The `memory_chain` table is **not created** in the schema initialization in [db.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/db.py). The `chain_append()` and `chain_distill()` methods called by MCM **don't exist anywhere in the `backend/memory/` directory** — zero implementations. This means the entire Immortus thread lineage is currently broken: every compress call silently fails at `chain_append` (caught by the `except Exception` at line 138), and the NBL CHAIN line never renders.

**Impact:** The `ALTER TABLE` migration will crash with `no such table: memory_chain` on any database. More importantly, without the chain persistence layer, Immortus sessions lose their lineage across compressions — the brain activates and assigns threads, but nothing is ever recorded, so the next session can't reference prior deep-chain work.

**Recommendation:**
1. Add `CREATE TABLE IF NOT EXISTS memory_chain (...)` to the migration script BEFORE the `ALTER TABLE`, with columns: `chain_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, result TEXT, coords_from TEXT, coords_to TEXT, nbl_outcome TEXT, insight TEXT, file_path TEXT, landmark_id TEXT, stale INTEGER DEFAULT 0, created_at REAL NOT NULL`.
2. Implement `chain_append()` and `chain_distill()` on the MCM store (see Gap 8).

---

## 🔴 Gap 3: The Plan's Swarm Schema Conflicts with the Already-Existing One

**Severity: HIGH**

The plan's migration script (§4.1) creates `swarm_collaborations` as:
```sql
CREATE TABLE IF NOT EXISTS swarm_collaborations (
    collaboration_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    coordinate_code TEXT NOT NULL,
    payload TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Reality:** The codebase already has a fully functional swarm schema in [db.py:L474-L506](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/db.py#L474-L506) with `task_collaboration` and `swarm_join_signals` tables. The `SwarmCoordinator` in [coordinator.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/agent/swarm/coordinator.py) actively reads and writes to these tables.

**Impact:** The plan creates a **parallel, disconnected** swarm table. The existing `SwarmCoordinator` will continue using `task_collaboration` while the gateway logs to `swarm_collaborations`. Two swarm systems running blind to each other = silent data loss and coordination failures.

**Recommendation:** Drop the `swarm_collaborations` table from the migration entirely. Instead, extend the existing `task_collaboration` and `swarm_join_signals` tables if additional columns are needed (e.g., `coordinate_code`).

---

## 🔴 Gap 4: The Plan Creates `security_sanitizer.py` — But `security_filter.py` Already Exists

**Severity: MEDIUM**

The plan (§4.2) creates a brand new [security_sanitizer.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/gateway/security_sanitizer.py) for credential scrubbing.

**Reality:** [security_filter.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/gateway/security_filter.py) already exists (465 lines, 18KB) in the exact same directory. It already has:
- `FilterRule` with blocked pattern matching
- Rate limiting per operation type
- Security audit logging integration via `MCPSecurityManager` and `SecurityAuditLogger`

**Impact:** Two security modules in the same directory with overlapping but disconnected logic. The existing `SecurityFilter` won't call the new sanitizer's `sanitize_payload()`, and the new sanitizer won't benefit from the existing rate limits and audit trail.

**Recommendation:** Integrate the dual-pass credential scrubbing logic INTO the existing `security_filter.py` as a new method or a composable filter rule, rather than creating a parallel file. This preserves the existing audit trail integration.

---

## 🔴 Gap 5: No `PRAGMA busy_timeout` Exists Anywhere in the Codebase

**Severity: MEDIUM**

The plan's §3.1 mitigation relies on `PRAGMA busy_timeout = 5000;` to handle SQLite multi-agent write conflicts. The evaluation (§5.5.2) also references it.

**Reality:** A grep for `busy_timeout` across the entire backend returns **zero results**. The current [db.py:L57-L70](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/db.py#L57-L70) connection setup configures `journal_mode=WAL`, `foreign_keys=ON`, `synchronous=NORMAL`, `cache_size`, `temp_store`, and `mmap_size` — but not `busy_timeout`.

**Impact:** This isn't a gap in the plan's *design* — it's a gap in the plan's *execution checklist*. The plan assumes this is a configuration change, but doesn't list modifying [db.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/db.py) as an explicit task. If forgotten during implementation, swarm mode will deadlock on the first concurrent write.

**Recommendation:** Add an explicit Phase 1 task: "Modify `open_encrypted_memory()` in `backend/memory/db.py` to add `conn.execute('PRAGMA busy_timeout=5000;')` immediately after the existing PRAGMA block."

---

## 🔴 Gap 6: DER ↔ Immortus Handoff Needs Clearer Data Source Boundaries

**Severity: MEDIUM**

The plan (§2.2) describes redesigning `der_loop.py` to "parse raw tool outcome metrics and test passes/fails directly from `system_events`." It treats the DER loop as a simple linear executor.

**Reality:** DER and Immortus form a **two-tier memory chain** — DER handles shallow tasks (dependency depth < 3) while Immortus activates as the deeper memory chain for complex multi-step plans (depth ≥ 3). The actual [der_loop.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/agent/der_loop.py) is architecturally richer than assumed:
- It has a `Reviewer` class (96 lines) that runs model inference against gradient warnings and active contracts — not just heuristics.
- The `DirectorQueue` tracks `coordinate_signal`, `depth_layer`, `gap_analysis`, and `veto_count` per item.
- The `Reviewer` uses `context_package.gradient_warnings` and `context_package.active_contracts` for mature graph reviews.
- It has an explicit `_heuristic_review` fast path for immature graphs with destructive operation detection.

When DER encounters a plan with depth ≥ 3, the [ImmortusBrain](file:///c:/Users/midas/Desktop/IRISVOICE/backend/agent/immortus/brain.py#L69) takes over — assigning a thread_id, tracking 4D temporal coordinates (momentum, drift, velocity, depth), and writing to the `memory_chain` via [MCM compress](file:///c:/Users/midas/Desktop/IRISVOICE/backend/agent/mcm.py#L126-L139). The DER loop's Reviewer continues to vet individual steps, but the Immortus chain provides the cross-step routing and pivot logic.

**Impact:** The plan's description of "eliminating bookkeeping" and "reading outcomes from system_events" is correct in intent but doesn't account for this two-tier relationship. If the DER loop reads outcomes from `system_events` but the Reviewer still expects live `gradient_warnings` from the Mycelium graph, there's a data source mismatch. Additionally, the auto-recorded `system_events` need to be available to Immortus's `chain_append()` so the deeper memory chain captures the automated data, not just manually-triggered compressions.

**Recommendation:** The plan should explicitly state:
1. "The Reviewer continues to read from `context_package` (Mycelium graph). Only the Director's outcome classification switches to `system_events`. Do not merge these data sources."
2. "When Immortus is active (depth ≥ 3), auto-recorded `system_events` are also fed into `chain_append()` so the thread lineage captures automated edit/test signals alongside manual MCM compressions."
3. "EML's expansion/compression signal modulates Immortus's `DRIFT_CRITICAL` constant dynamically, acting as the governor that prevents speculative branches from exploding or stalling."

---

## 🔴 Gap 7: Evaluation's §3.2 Parameter Mapping Schema Is Not Reflected in the Plan

**Severity: MEDIUM**

The evaluation (§3.2) describes a rich auto-recording schema that captures:
- `coordinates: {x: primitive_rank, y: eml_balance, z: z_trajectory}`
- `edit_type`, `file_hash` (SHA-256)
- `test_result: {passed: count, failed: count, exit_code: code}`
- `covers_files: infer_covered_files(file_path)`

The implementation plan (§4.4) simplifies this to:
```python
payload={"file_path": file_path, "tool": msg.type.value}
```

**Impact:** The plan loses the coordinate embedding, the file hash (useful for detecting no-op edits), and the test coverage inference. Without coordinate embedding in the payload, the EML engine (Gap 1) has no raw data to compute `x` and `y` parameters from.

**Recommendation:** The plan's interceptor payloads in §4.4 should be expanded to match the evaluation's §3.2 schema, or at minimum include `file_hash` and raw `exit_code`/`stdout` so that EML can derive its parameters downstream.

---

## 🟡 Phantom Assumptions (Things the Plan Gets Wrong About the Codebase)

These are cases where the plan describes something slightly differently from what actually exists. Not necessarily bugs, but they'll cause confusion during implementation.

### Phantom 1: The Plan References `ws_manager.py` in `backend/gateway/`

The plan (§4.4) says to modify `backend/gateway/ws_manager.py`. The actual WebSocket manager lives at [backend/ws_manager.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/ws_manager.py) (root of backend, not inside gateway). There IS a [backend/gateway/iris_gateway.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/gateway/iris_gateway.py) that handles message routing. The plan needs to clarify which file is being modified.

### Phantom 2: The Plan Assumes G1-G13 Gates Are Numbered in Code

The Kyudo module ([kyudo.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/mycelium/kyudo.py)) implements the concepts described as G1-G13 but does NOT use those identifiers in code. The actual classes are `CellWall`, `QuorumSensor`, `QuorumReorganization`, `TaskClassifier`, `PredictiveLoader`, etc. The plan should reference these class names, not abstract gate numbers, to prevent implementer confusion.

### Phantom 3: The Plan Says "15 Required Tables" for G3

The evaluation (§4 G3) says G3 verifies "15 required tables": `landmarks, gradient_warnings, contracts, sessions, coordinate_path, work_items, code_events, file_nodes, test_nodes, graph_edges, instance_registry, project_registry, pins, pin_links, landmark_bridges`. But the actual schema in [db.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/db.py) creates tables like `mycelium_nodes`, `mycelium_edges`, `mycelium_landmarks`, `mycelium_pins`, etc. — ALL prefixed with `mycelium_`. None of the 15 table names listed in the evaluation exist in the current codebase. This is legacy nomenclature that was never updated.

### Phantom 4: The Migration Mentions `coordinates.db` and `mycelium.db` as Separate Files

The evaluation and plan reference both `coordinates.db` and `mycelium.db`. The actual codebase uses a single database opened via `open_encrypted_memory(db_path, biometric_key)` where `db_path` comes from config. There's no evidence of two separate database files in the current code.

---

## 🔶 Uncovered Failure Modes (Not in Plan or Evaluation)

### Uncovered 1: Async/Sync Boundary Mismatch

`ImmortusBrain.evaluate()` is an `async` method ([brain.py:L51](file:///c:/Users/midas/Desktop/IRISVOICE/backend/agent/immortus/brain.py#L51)). The `MCMOrchestrator` workflows are synchronous ([orchestrator.py:L92-L121](file:///c:/Users/midas/Desktop/IRISVOICE/backend/agent/mcm_protocol/orchestrator.py#L92-L121)). The plan doesn't address how the EML-Immortus synergy will bridge this boundary. If `episodic.fragment_and_store()` is called from a `ThreadPoolExecutor` (as the plan describes) but the DER loop's Director queries `system_events` synchronously, there's a race condition: the Director may read stale data because the background thread hasn't committed yet.

**Mitigation:** Add a `db.commit()` fence in the ThreadPoolExecutor callback BEFORE returning, and add a brief `await asyncio.sleep(0)` yield point in the DER loop after checking `system_events` to allow the event loop to flush pending writes.

### Uncovered 2: Episodic Store Connection Isolation

The `EpisodicStore` in [episodic.py](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/episodic.py) takes a `db` connection at init. If the gateway's background executor calls `fragment_and_store()` on a separate thread, but the connection was created on the main thread, SQLite will throw `ProgrammingError: SQLite objects created in a thread can only be used in that same thread` — UNLESS `check_same_thread=False` was set. The fallback in [db.py:L94](file:///c:/Users/midas/Desktop/IRISVOICE/backend/memory/db.py#L94) DOES set this flag for sqlite3, but the SQLCipher path does NOT.

**Mitigation:** Add `check_same_thread=False` equivalent to the sqlcipher3 connection path, or ensure the ThreadPoolExecutor creates its own connection.

### Uncovered 3: Watchdog Library on Windows + PyInstaller

The plan specifies using the `watchdog` library for file system observation. On Windows, `watchdog` uses `ReadDirectoryChangesW` which works fine in development, but can fail silently inside PyInstaller-frozen binaries because the working directory and file handles behave differently. This directly impacts the Step 5 graduation to compiled binary.

**Mitigation:** Add a specific test in Step 5 (PyInstaller graduation) that verifies `watchdog` events fire correctly inside the frozen binary, with a fallback to polling mode if they don't.

---

## 📊 Summary Scorecard

| Category | Count | Impact on 98% Target |
|:---------|:-----:|:---------------------|
| ✅ Well-covered | 5 | Positive — solid foundation |
| 🔴 Real gaps | 8 | **−15% if all missed** (EML porting + Immortus chain = −8%) |
| 🟡 Phantom assumptions | 4 | **−3%** (implementer confusion, wrong file paths) |
| 🟖 Uncovered failures | 3 | **−4%** (race conditions, thread safety, PyInstaller) |

**Estimated success rate if deployed as-is:** ~83%  
**Estimated success rate after addressing all items:** ~97-98%  

The single highest-leverage fix is **Gap 1 (EML porting strategy)** — the experimental data is validated (97% calibration, +40% compliance) but the plan doesn't map a concrete path from the AGENT harness code to IRISVOICE's table schema and module structure. The second highest is **Gap 3 (swarm schema conflict)** — deploying a parallel swarm table would silently fracture coordination.

---

## Recommended Priority Order

1. **Gap 1** — Port calibrated v2 EML formula + AutoRecorder from AGENT harness into `eml_engine.py` (CRITICAL — blocks EML-Immortus synergy)
2. **Gap 3** — Remove duplicate swarm schema (HIGH — prevents coordination fracture)
3. **Gap 2** — Create `memory_chain` table + fix ALTER migration (HIGH — Immortus lineage is broken without it)
4. **Gap 8** — Implement `chain_append()` / `chain_distill()` on MCM store (HIGH — chain persistence is hollow)
5. **Gap 5** — Add `busy_timeout` to `db.py` (MEDIUM — prevents swarm deadlocks)
6. **Gap 4** — Merge sanitizer into existing security_filter (MEDIUM — prevents module sprawl)
7. **Gap 6** — Clarify DER Reviewer data source boundary (MEDIUM — prevents data mismatch)
8. **Gap 7** — Enrich interceptor payload schema (MEDIUM — enables EML computation)
9. **Phantom 1-4** — Fix file paths and table names in plan text (LOW — prevents confusion)
10. **Uncovered 1, 3** — Add async fence and PyInstaller watchdog test (LOW — edge cases)

---

## 🔴 Gap 8 (NEW): Immortus Memory Chain Persistence Layer Is Called But Never Implemented

**Severity: HIGH — blocks the deep memory chain from functioning.**

The MCM module at [mcm.py:L126-L139](file:///c:/Users/midas/Desktop/IRISVOICE/backend/agent/mcm.py#L126-L139) calls `self._store.chain_append()` and `self._store.chain_distill()` on every compression checkpoint. These are the write operations that persist Immortus's thread lineage — connecting coordinate traversals, NBL outcomes, and insights into the `memory_chain` table.

**Reality:** Neither `chain_append()` nor `chain_distill()` exists anywhere in the `backend/memory/` directory. Zero implementations. The `self._store` object (the MCM store) doesn't define these methods. Every call silently fails at the `except Exception` catch on line 138.

**What this means for Immortus:** The [ImmortusBrain](file:///c:/Users/midas/Desktop/IRISVOICE/backend/agent/immortus/brain.py) correctly activates for deep plans (depth ≥ 3), assigns thread_ids, computes 4D temporal coordinates, and routes through the pheromone walk. But when MCM compresses — which is the moment the chain should **persist** the work — nothing is recorded. The next session's NBL builder queries `memory_chain WHERE thread_id = ?` and gets zero rows. The chain is born and dies within a single session.

**Impact:** Without chain persistence, Immortus is stateless across sessions. Deep multi-step plans can't resume thread lineage after a compression or session restart. The entire "deeper memory chain" concept is architecturally present but operationally hollow.

**Recommendation:** Implement these two methods on the MCM store:
```python
def chain_append(self, thread_id, result, coords_from, coords_to, nbl_outcome, insight):
    """Persist a memory chain entry for Immortus thread lineage."""
    self._conn.execute(
        "INSERT INTO memory_chain (chain_id, thread_id, result, coords_from, coords_to, nbl_outcome, insight, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (uuid4().hex, thread_id, result, json.dumps(coords_from), json.dumps(coords_to), nbl_outcome, insight, time.time())
    )
    self._conn.commit()

def chain_distill(self, thread_id, threshold=50):
    """Compress old chain entries when count exceeds threshold."""
    count = self._conn.execute("SELECT COUNT(*) FROM memory_chain WHERE thread_id = ?", (thread_id,)).fetchone()[0]
    if count > threshold:
        # Keep newest threshold entries, delete rest
        self._conn.execute(
            "DELETE FROM memory_chain WHERE thread_id = ? AND chain_id NOT IN "
            "(SELECT chain_id FROM memory_chain WHERE thread_id = ? ORDER BY created_at DESC LIMIT ?)",
            (thread_id, thread_id, threshold)
        )
        self._conn.commit()
```

This must be paired with the `CREATE TABLE memory_chain` fix from Gap 2.

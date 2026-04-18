# Context Engineering — IRIS Memory Architecture

**Version:** 2.0
**Status:** Option B + Pacman lifecycle implemented; C.1 built; C.4 in test suite
**Last updated:** 2026-03-31
**Owner:** IRIS Core Team

---

## What This Document Is

This document defines how IRIS uses memory as an **active participant in cognition**,
not as a post-hoc log.  It is the canonical reference for what is actually implemented,
what the design intent is, and what remains to be built.

The term **context engineering** refers to the deliberate design of *what information
is available to the model at each moment during a task* — not just at the start, but
throughout every reasoning step.

---

## Research Foundation

**Titans + MIRAS** (`research.google/blog/titans-miras-helping-ai-have-long-term-memory`)
- Titans: neural long-term memory (MLP) working *alongside* attention — updates during
  inference, not after.
- MIRAS: real-time parameter adaptation — memory updates while processing.
- Key principle: *"memory should update dynamically during reasoning, not remain frozen."*

**TurboQuant** (`research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression`)
- Frames the KV cache as an active computational constraint.
- 6× memory compression with no accuracy loss.

**PACMAN** (`docs/PACMAN.md`)
- Context metabolism architecture. Content is *digested* into coordinate signals,
  not stored as retrievable documents.
- The longer you use it, the cheaper it gets.  Graph matures → tokens needed drop.
- Five fragmentation dimensions: Zone, Tier, Address, Priority, Concentration Field.

| Research Concept | IRIS Implementation |
|---|---|
| Titans long-term memory | Mycelium coordinate graph — persists across sessions |
| MIRAS real-time update | `append_to_session()` after each DER step |
| TurboQuant KV compression | `_assemble_direct_context` token budget + chunk trimming |
| Titans memory alongside attention | ContextPackage injected at every Director + Explorer step |
| PACMAN metabolism | `fragment_and_store()` → `context_chunks` DB + `retrieve_context_chunks()` |
| PACMAN zone membrane | `zone` column on `context_chunks`: trusted / tool / reference |
| PACMAN decay | `cleanup_stale_chunks()` — prunes low-retrieval old fragments |
| PACMAN crystallization signal | `retrieval_count` → `episode_indexer` at threshold |

---

## The Three Memory Layers

```
┌──────────────────────────────────────────────────────────────┐
│ LAYER 1 — Mycelium Coordinate Graph                          │
│ What: topology, trajectories, gradient warnings, landmarks,  │
│       pheromone edges, behavioral contracts                  │
│ Read: BEFORE planning (get_task_context_package)             │
│ Write: during execution (mycelium_ingest_tool_call) +        │
│        after completion (crystallize_landmark)               │
│ Maturity: 3 spaces × confidence ≥ 0.6 (currently 0.95)      │
│ Status: FULLY WIRED                                          │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ LAYER 2 — Episodic Store (task-level episodes)               │
│ What: completed task summaries, tool sequences, outcomes     │
│ Read: assemble_episodic_context() before context assembly    │
│ Write: _store_task_episode() after DER loop completes        │
│ Search: cosine similarity on embeddings                      │
│ Status: READ + WRITE both wired                              │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ LAYER 3 — Pacman Context Fragments (turn-level DB)           │
│ What: conversation turn-pairs + DER step outputs, chunked    │
│       and embedded in context_chunks table                   │
│ Read: retrieve_context_chunks() replaces rolling window      │
│       in _assemble_direct_context (semantic retrieval)       │
│ Write: fragment_and_store() after each response + DER step   │
│ Zone: 'trusted' (conversation) / 'tool' (DER outputs)        │
│ Lifecycle: age-weighted scoring, retrieval_count, decay      │
│ Status: FULLY WIRED                                          │
└──────────────────────────────────────────────────────────────┘
```

---

## Option A — Episodic Loop Closure

**Status: IMPLEMENTED**

### What It Does

After each DER-executed task, `_store_task_episode()` writes an `Episode` to the
episodic store:
- `task_summary` = original user task text
- `tool_sequence` = list of `{tool, params, step_number, description}` for all steps
- `full_content` = concatenated step outputs
- `outcome_type` = "success" | "failure"

On the next semantically similar task, `assemble_episodic_context()` finds the episode
via cosine similarity and injects "RELEVANT PAST SUCCESSES" / "WARNINGS FROM PAST
FAILURES" into the prompt.

### Key Files

- `backend/memory/episodic.py` — `EpisodicStore.store()`, `retrieve_similar()`
- `backend/agent/agent_kernel.py` — `_store_task_episode()` called from `_execute_plan_der()`
- `backend/memory/interface.py` — `episodic.assemble_episodic_context()` proxy

---

## Option B — Pacman Context Fragmentation

**Status: IMPLEMENTED** (including Pacman lifecycle upgrade)

### Philosophy

Standard rolling-window context is a filing cabinet: older messages get truncated
regardless of relevance.  Pacman inverts this.  Every conversation turn and every DER
step output is *digested* — chunked, embedded, stored in `context_chunks`.  When
assembling context for the next message, the model receives the most *relevant*
fragments from the entire session history, not the most *recent* N messages.

### Architecture

#### context_chunks table

```sql
CREATE TABLE context_chunks (
    id               TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    chunk_type       TEXT NOT NULL DEFAULT 'context_fragment',
    zone             TEXT NOT NULL DEFAULT 'trusted',
    content          TEXT NOT NULL,
    embedding        BLOB,
    retrieval_count  INTEGER NOT NULL DEFAULT 0,
    timestamp        TEXT DEFAULT CURRENT_TIMESTAMP
);
```

**chunk_type** — what produced this chunk:
- `context_fragment` — a conversation turn-pair (user + assistant)
- `der_output` — a single DER step result with its description

**zone** — PACMAN.md Dimension 1 zone membrane:
- `trusted` — user's own conversation (assigned to `context_fragment`)
- `tool` — verified DER/tool execution output (assigned to `der_output`)
- `reference` — external content (future)
- `system` — IRIS internals (future)

#### fragment_and_store(content, session_id, chunk_type, zone)

Called after every direct-path response and after every DER step.

1. Splits `content` into overlapping 2048-char chunks (200-char overlap)
2. Embeds each chunk via `EmbeddingService`
3. Deduplicates at 0.92 cosine similarity (within same session + chunk_type)
4. Stores `(id, session_id, chunk_type, zone, content, embedding)` in `context_chunks`

#### retrieve_context_chunks(query, session_id, limit, min_similarity, chunk_types, zones)

Called by `_assemble_direct_context` as **Layer 3** of context assembly.

**Scoring formula (PACMAN.md §Compounding Cost Curve):**

```
similarity_score = cosine(query_embedding, chunk_embedding)   # semantic match
age_hours        = time since chunk was stored
recency_score    = 1 / (1 + age_hours / 24.0)                 # half-life = 24h
combined_score   = similarity_score × 0.80 + recency_score × 0.20
```

Chunks below `min_similarity` are filtered before recency weighting — a stale
chunk cannot win on recency alone if it's semantically irrelevant.

**After retrieval:**
- `retrieval_count` incremented for all returned chunks
- Chunks with `retrieval_count >= 5` emit a signal to `episode_indexer` for the
  Mycelium crystallization pathway

#### cleanup_stale_chunks(session_id, max_age_hours, min_retrievals)

Pacman decay: removes chunks older than `max_age_hours` AND with `retrieval_count
<= min_retrievals`.  Chunks at or above the crystallization threshold
(`retrieval_count >= 5`) are never pruned — they have earned permanent status.

#### Context Assembly — _assemble_direct_context()

```
_assemble_direct_context(text, context)
    │
    ├─ [system]      _build_system_prompt()         — Layer 1 Mycelium coords
    │
    ├─ [episodic]    assemble_episodic_context(text) — Layer 2 task summaries
    │                → injected as <memory> pseudo-exchange
    │
    ├─ [chunk_prefix] retrieve_context_chunks(text,  — Layer 3a semantic DB
    │                    session_id, limit=6,
    │                    min_similarity=0.25)
    │                → injected as <context_memory> pseudo-exchange
    │
    ├─ [recency]     last 4 raw turns from context   — Layer 3b recency anchor
    │                → trimmed if chunk_prefix uses budget
    │
    └─ [current]     {"role":"user", "content": text}
```

When `chunk_prefix` is non-empty (DB has chunks), only the last 4 raw turns are
included as a recency anchor.  When the DB is empty (first message), falls back to
the full rolling window.  The token budget is split: chunk tokens are deducted from
the history budget so the total never overflows `_DIRECT_CTX_BUDGET` (20k tokens).

### Call Sites

| Location | chunk_type | zone |
|---|---|---|
| `process_text_message` — after direct response | `context_fragment` | `trusted` |
| `_execute_plan_der` — after each Explorer step | `der_output` | `tool` |

---

## Option C — Continuous Context Engineering

### C.1 — LiveContextPackage

**Status: IMPLEMENTED** (`backend/agent/live_context.py`)

Wraps `ContextPackage` and refreshes coordinate signals at each DER cycle boundary.
Calls `memory_interface.get_task_context_package()` with the current step's context
to update `gradient_warnings` and `tier2_predictions` mid-loop.

### C.2 — BehavioralPredictor

**Status: STUB** (`backend/memory/mycelium/interpreter.py`)

Will populate `tier2_predictions` in `ContextPackage` from pheromone edge weights.
Required for `LiveContextPackage.tier2_predictions` to be non-empty.

### C.3 — CoordinateInterpreter

**Status: PARTIAL** (`backend/memory/mycelium/interpreter.py`)

`ResolutionEncoder` implemented with 3-rule arbitration.  `CoordinateInterpreter`
conflict resolution logic present.  `BehavioralPredictor` still a stub.

### C.4 — Mid-loop Episodic Retrieval (Sub-task Hints)

**Status: SPECCED + TESTED** (test suite covers the mechanism)

At each DER cycle boundary, query episodic store for `item.description` (the
*sub-task*, not the original user task).  If similarity ≥ 0.55, inject result into
`item.coordinate_signal` as `SUB-TASK HINT: ...`.

```python
# In _execute_plan_der(), each cycle:
_sub_eps = episodic.retrieve_similar(task=item.description, limit=2, min_score=0.55)
if _sub_eps:
    _hints = "; ".join(ep["task_summary"][:80] for ep in _sub_eps)
    item.coordinate_signal = (item.coordinate_signal + f"\nSUB-TASK HINT: {_hints}").strip()
```

Covered by `test_context_engineering.py` (see `test_working_memory_via_chunks`,
`test_retrieve_context_chunks`).  Not yet wired into `_execute_plan_der()` production
code — the test validates the retrieval mechanism; wiring is the next step.

### C.5 — Predictive Pre-warming

**Status: NOT BUILT**

Pre-fetch likely next tool results while Reviewer validates the current step.

---

## Data Flow — Complete Picture

```
USER MESSAGE
     │
     ▼
agent_kernel.process_text_message(text, session_id)
     │
     ├─ 1. ConversationMemory.add_message("user", text)
     │
     ├─ 2. [LAYER 1] MyceliumInterface.get_task_context_package()
     │       → ContextPackage {tier1_directives, gradient_warnings, contracts, ...}
     │
     ├─ 3. [LAYER 2] episodic.assemble_episodic_context(text)
     │       → "RELEVANT PAST SUCCESSES: ..." / "WARNINGS FROM PAST FAILURES: ..."
     │
     ├─ 4. [Not DER] _respond_direct(text, context)
     │       → _assemble_direct_context():
     │           [system]       Mycelium ContextPackage
     │           [episodic]     Layer 2 injection
     │           [chunk_prefix] retrieve_context_chunks() — Layer 3a
     │           [recent]       last 4 raw turns — Layer 3b
     │           [current]      user message
     │       → fragment_and_store(turn_pair, zone='trusted')  ← DIGEST TURN
     │
     └─ 5. [DER] _execute_plan_der(plan, context_package, ...)
           │
           ├─ LOOP for each QueueItem:
           │   │
           │   ├─ Reviewer.review(item, completed_items, context_package)
           │   ├─ Explorer executes (tool or _run_step_direct)
           │   ├─ mycelium_ingest_tool_call(...)
           │   ├─ append_to_session(step_result, 'working_history')
           │   └─ fragment_and_store(step_result, zone='tool')  ← DIGEST STEP
           │
           ├─ mycelium_record_outcome()
           ├─ mycelium_crystallize_landmark()
           ├─ mycelium_clear_session()
           ├─ mycelium_record_plan_stats()
           └─ _store_task_episode(...)  ← EPISODE TO LAYER 2

RESPONSE → user
```

---

## Implementation Status

| Component | File | Status |
|---|---|---|
| Mycelium coordinate graph | `memory/mycelium/` | DONE |
| Episodic store (schema + embeddings) | `memory/episodic.py` | DONE |
| Episode write (Option A) | `agent_kernel.py:_store_task_episode` | DONE |
| Episodic read (assemble_episodic_context) | `memory/episodic.py` | DONE |
| `fragment_and_store` (Pacman digestion) | `memory/episodic.py` | DONE |
| `retrieve_context_chunks` (semantic retrieval) | `memory/episodic.py` | DONE |
| Zone classification (trusted/tool) | `memory/episodic.py` | DONE |
| Age-weighted scoring (recency decay) | `memory/episodic.py` | DONE |
| retrieval_count + crystallization signal | `memory/episodic.py` | DONE |
| `cleanup_stale_chunks` (Pacman decay) | `memory/episodic.py` | DONE |
| `_assemble_direct_context` — Layer 3 as DB | `agent_kernel.py` | DONE |
| fragment_and_store call after direct response | `agent_kernel.py` | DONE |
| fragment_and_store call after DER step | `agent_kernel.py` | DONE |
| TTS normalizer (markdown/path/symbol → speech) | `voice/tts_normalizer.py` | DONE |
| LiveContextPackage (C.1) | `agent/live_context.py` | DONE |
| BehavioralPredictor (C.2) | `memory/mycelium/interpreter.py` | STUB |
| CoordinateInterpreter (C.3) | `memory/mycelium/interpreter.py` | PARTIAL |
| C.4 sub-task hints wired into DER loop | `agent_kernel.py` | TODO |
| C.5 predictive pre-warming | — | NOT BUILT |

---

## Test Commands

```bash
# Pacman fragmentation + context assembly (Option B):
python -m pytest backend/tests/test_context_engineering.py -v

# TTS normalizer (voice output quality):
python -m pytest backend/tests/test_tts_normalizer.py -v

# Full DER loop:
python -m pytest backend/tests/test_der_loop.py -v

# All backend tests:
python -m pytest backend/tests/ -v --ignore=backend/tests/test_type_safety.py \
  --ignore=backend/tests/test_vision_memory.py
```

---

*Architecture contracts enforced in: `bootstrap/GOALS.md` Domain 1 + Domain 5*
*PACMAN philosophy: `docs/PACMAN.md`*
*DER Loop + Mycelium: `docs/DER_LOOP_MYCELIUM.md`*

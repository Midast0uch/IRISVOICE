# IRIS — DER Loop & Mycelium Memory System
## How the Agent Processes Prompts Into Executing Tasks

**File:** `IRISVOICE/docs/DER_LOOP_MYCELIUM.md`
**Last updated:** v1.7 — all DER gaps resolved, PiN layer + landmark bridges added

---

## 1. Overview

IRIS uses a two-phase agent architecture:

1. **DER Loop** (Director → Explorer → Reviewer) — structured execution brain that breaks tasks into steps, filters each step through a Reviewer, executes via tools or direct model inference, and records everything to Mycelium.
2. **Mycelium Memory** — coordinate graph stored in SQLite (`data/memory.db` at runtime, `bootstrap/coordinates.db` during build). Gives the DER loop spatial context: where the agent is, what has worked before, what failure patterns exist, and what to prioritize next.
3. **PiN Layer** — Primordial Information Nodes anchor explicit human knowledge (files, docs, images, decisions, URLs) as typed graph nodes that participate in context assembly and decay alongside coordinate nodes.
4. **Landmark Bridges** — cross-project equivalence maps that let patterns crystallized in one project activate immediately in another, without re-learning from scratch.

The loop and the memory are inseparable. Without a mature Mycelium graph, the Reviewer has no signal and falls back to PASS on every step. As the graph matures, the Reviewer begins shaping the execution trajectory based on real coordinate history. PiNs provide the explicit knowledge layer that coordinates cannot — human decisions, design intent, and external references — feeding the Reviewer with richer context.

---

## 2. Entry Point — WebSocket to DER

### 2.1 Path from message to execution

```
User types message in frontend  (or speaks → STT → text)
    ↓
WebSocket → IRISGateway.handle_message()          [iris_gateway.py]
    ↓ routes by msg_type
msg_type == "text_message" → _handle_chat()
    ↓
security_filter.py → message sanitization + injection detection
mcp_security.py    → HyphaChannel trust enforcement
    ↓
get_agent_kernel(session_id)                       [AgentKernel instance per session]
    ↓
agent_kernel.process_text_message(text, session_id)   [agent_kernel.py]
```

### 2.2 process_text_message() — the staging area

Before the DER loop runs, these steps happen in fixed order:

```python
# Step 1 — Sanitize (injection protection)
task = _sanitize_task(text)
# Replaces coordinate markers like [CORE], [ORBIT] with [filtered]

# Step 2 — Classify (MUST be before context assembly)
task_class, space_subset = TaskClassifier.classify(task)
# task_class: "full" | "partial" | "quick"
# space_subset: which Mycelium spaces to query

# Step 3 — Get context package (uses space_subset from Step 2)
context_package, is_mature = memory_interface.get_task_context_package(
    task, session_id, space_subset
)
# is_mature=True → ContextPackage with full coordinate data + PiN summaries
# is_mature=False → plain string context (graph not ready yet)

# Step 4 — Plan the task
plan = _plan_task(text, context_package=context_package, is_mature=is_mature)
# Returns ExecutionPlan with strategy + list of PlanSteps
# temperature = 0.1 if is_mature, else 0.25

# Step 5 — Ingest planning reasoning as coordinate statement
memory_interface.mycelium_ingest_statement(reasoning_text, session_id)

# Step 6 — Route by strategy
if plan.strategy == "do_it_myself":
    return _execute_plan_der(plan, context_package, is_mature, task_class, session_id)
else:
    # Falls through to ReAct / agentic loop
```

**Critical ordering rule:** Step 2 (classification) MUST run before Step 3 (context assembly). The `space_subset` from classification is a required argument to `get_task_context_package`. Reversing this order causes a NameError. This is a permanent architectural constraint.

---

## 3. The DER Loop — _execute_plan_der()

### 3.1 What it is

A three-role cycle that runs until all plan steps are complete or the cycle limit is hit:

| Role | Function | Who |
|------|----------|-----|
| **Director** | Picks the next ready step (dependency-aware) | `DirectorQueue.next_ready()` |
| **Reviewer** | Approves, refines, or vetoes the step | `Reviewer.review()` |
| **Explorer** | Executes the step (tool or model) | `_tool_bridge.execute_tool()` or `_run_step_direct()` |

### 3.2 Data structures

**ExecutionPlan** (from `_plan_task()`):
```
plan_id          — unique ID
original_task    — the raw user message
strategy         — "do_it_myself" | "delegate" | ...
reasoning        — why this strategy was chosen
steps            — List[PlanStep]
```

**PlanStep** → converted to **QueueItem** when the DER loop starts:
```
step_id              — "step-1", "step-2", etc.
step_number          — 1, 2, 3...
description          — what to do
expected_output      — what success looks like
tool                 — optional tool name (None = direct model inference)
params               — tool parameters dict
critical             — if False, can be skipped on veto
depends_on           — List[step_id] that must complete first
objective_anchor     — the original task (never changes)
coordinate_signal    — Mycelium region targeted
veto_count           — incremented on VETO verdict
refined_description  — set by Reviewer on REFINE
depth_layer          — for trailing crystallizer
gap_analysis         — set by TrailingDirector
```

**DirectorQueue** — manages the step queue:
```
objective        — task objective (immutable)
items            — List[QueueItem]
completed_ids    — steps that finished
vetoed_ids       — steps that were permanently skipped
cycle_count      — increments each iteration
max_cycles = 40  — hard cap (emergency stop)
```

### 3.3 The main loop

```python
# Token budget set from mode (DER_TOKEN_BUDGETS dict, not just cycle count)
_token_budget = DER_TOKEN_BUDGETS.get(task_class, DER_TOKEN_BUDGETS["DEFAULT"])
_tokens_used = 0

while not queue.is_complete() and not queue.hit_cycle_limit():
    queue.cycle_count += 1

    # ── DIRECTOR ─────────────────────────────────────────────────
    item = queue.next_ready()
    if item is None:
        break  # dependency deadlock

    # ── REVIEWER ─────────────────────────────────────────────────
    verdict, feedback = reviewer.review(
        item, completed_steps, context_package, is_mature
    )

    if verdict == ReviewVerdict.VETO:
        item.veto_count += 1
        if item.veto_count >= DER_MAX_VETO_PER_ITEM:   # 2
            queue.mark_vetoed(item.step_id)
        continue

    if verdict == ReviewVerdict.REFINE:
        item.description = feedback

    # ── MID-LOOP EPISODIC RETRIEVAL (Context Engineering C.4) ────
    similar = episodic_store.retrieve_similar(item.description, threshold=0.55)
    if similar:
        item.coordinate_signal += "\nSUB-TASK HINT: " + similar[0].summary

    # ── EXPLORER ─────────────────────────────────────────────────
    if item.tool:
        step_result = _tool_bridge.execute_tool(item.tool, item.params)
    else:
        step_result = _run_step_direct(item, context_package, session_id)

    # ── MYCELIUM SIGNAL ──────────────────────────────────────────
    memory_interface.mycelium_ingest_tool_call(
        tool_name=item.tool or "direct",
        success=True,
        sequence_position=len(completed_items),
        total_steps=len(queue.items),
        session_id=session_id
    )

    # ── TOKEN BUDGET CHECK ────────────────────────────────────────
    _tokens_used += len(step_result) // 4   # rough: 4 chars ≈ 1 token
    if _tokens_used >= _token_budget:
        break  # budget exceeded — stop cleanly

    # ── TRAILING DIRECTOR ─────────────────────────────────────────
    if len(completed_items) % TRAILING_GAP_MIN == 0:
        gap_items = trailing_director.analyze_gaps(
            item, plan, context_package, is_mature
        )
        for gi in gap_items:
            queue.add_item(gi)   # non-critical, can be vetoed

    queue.mark_complete(item.step_id)
    completed_items.append(item)
    step_outputs.append(step_result)

# ── POST-LOOP: OUTCOME RECORDING (strictly ordered) ──────────────
memory_interface.mycelium_record_outcome(task, outcome, session_id)
memory_interface.mycelium_crystallize_landmark(session_id, score, outcome, task_label)
memory_interface.mycelium_clear_session(session_id)
memory_interface.mycelium_record_plan_stats(stats)

return "\n".join(step_outputs)
```

### 3.4 Reviewer — the membrane

The Reviewer is not a gate. Its job is to filter, not block. It always falls back to PASS on failure.

**Three verdicts:**
- `PASS` — step approved as-is, continue to Explorer
- `REFINE` — Reviewer rewrote the step description, continue to Explorer
- `VETO` — step rejected; after 2 vetoes the step is permanently skipped

**When the Reviewer is active:** Only when Mycelium is mature (`is_mature=True`) AND a context package with real gradient warnings / contracts is available. In early sessions, every Reviewer call is a fast-path PASS.

**What the Reviewer sees (when mature):**
```
- objective
- last 3 completed steps (summaries)
- gradient_warnings from context_package  ← from Mycelium graph
- active_contracts from context_package   ← behavioral rules
- PiN summaries relevant to this step     ← from pin_links graph
```

The Reviewer never raises — any exception returns `(PASS, None)`. Max 200 tokens, temperature 0.0.

---

## 4. Context Package — What the DER Loop Gets

When Mycelium is mature, `get_task_context_package()` returns a `ContextPackage`:

```python
@dataclass
class ContextPackage:
    mycelium_path: str        # Encoded coordinate path for this task
    topology_path: str        # Current topology layer context
    manifest: Dict            # Address registry (URLs, tokens, summaries)
    tier1_directives: str     # Top-level goals / primary direction
    tier2_predictions: str    # Predicted next steps (BehavioralPredictor)
    tier3_failures: str       # Known failure patterns + resolutions
    active_contracts: str     # Behavioral rules currently enforced
    gradient_warnings: str    # Danger zones from prior failures
    causal_context: str       # Why the graph is in its current state
    ambient_signals: str      # Background signals
    topology_position: str    # Current position in topology
    task_class: str           # Classification of this task
```

**What feeds into the context package:**

| Source | What it contributes |
|--------|---------------------|
| Coordinate graph | 7-space position → task routing, reviewer signal |
| Landmark index | Permanent patterns → tier1_directives, tier2_predictions |
| Episodic store | Similar past tasks → episodic injections (C.4) |
| Gradient warnings | Past failures → tier3_failures, Reviewer warnings |
| Contracts | Behavioral rules → active_contracts |
| Topology layer | Spatial position → topology_position, topology_path |
| PiNs (v1.7) | Relevant knowledge nodes → ambient_signals, manifest |

**BehavioralPredictor** (`interpreter.py`) ranks outgoing pheromone edges by `(hit_count/traversal_count) × confidence` → top-3 predicted tool names → `tier2_predictions`. The Planner uses these to front-load likely tools in the plan.

**CoordinateInterpreter** (`interpreter.py`) arbitrates conflicting coordinate values: confidence → recency → pheromone edge strength. Resolution basis stored in `mycelium_conflicts`.

---

## 5. Mode Detection — Before Planning

The `ModeDetector` determines task type and flows into DER token budget selection:

| Mode | DER token budget | When |
|------|-----------------|------|
| `SPEC` | 60,000 | Bypasses DER — routes to SpecEngine |
| `RESEARCH` | 80,000 | Web/file heavy |
| `IMPLEMENT` | 40,000 | Default coding/building |
| `DEBUG` | 30,000 | Targeted fix |
| `TEST` | 40,000 | Test writing/running |
| `REVIEW` | 20,000 | Code review |

**SPEC mode bypasses DER entirely.** Routes to `SpecEngine.produce()` — planning, not execution.

**Clarification suppressed** when `topology_primitive != "unknown"` — Mycelium already knows the answer.

---

## 6. Context Lifecycle — Pacman Model

The context system follows a Pacman lifecycle (defined in `docs/CONTEXT_ENGINEERING.md`):

**Zone membrane (Dimension 1):**
- `context_fragment` → trusted (user's own conversation)
- `der_output` → tool (verified DER/executor output)

**Age-weighted retrieval scoring:**
```
combined = similarity × 0.80 + recency × 0.20
recency  = 1 / (1 + age_hours / 24.0)   # half-life = 24h
```

**Crystallization pathway:**
`retrieval_count >= 5` → triggers `episode_indexer.index_episode()` → Mycelium crystallization candidate. Crystallization candidates are never pruned.

**Pacman decay:**
`cleanup_stale_chunks()` removes chunks older than `max_age_hours` with `retrieval_count <= min_retrievals`.

**Unlimited effective context (Layer architecture):**
- **Layer 1 (direct):** All conversation history that fits the 32k window — oldest trimmed when budget exceeded
- **Layer 2 (episodic):** Summaries of past DER tasks via `assemble_episodic_context()` — carries the gist forward even when raw history is trimmed
- **Layer 3 (Mycelium):** Coordinate context package — the compressed accumulated intelligence of all sessions

The 32k window is the immediate execution buffer. Mycelium + episodic is the permanent long-term store. Together they give unbounded effective recall.

---

## 7. Trailing Director — Gap Filling (WIRED)

The `TrailingDirector` runs behind the main loop, analyzing completed steps for depth gaps and injecting gap-filling items:

```python
class TrailingDirector:
    def analyze_gaps(self, completed_step, plan, context_package, is_mature):
        # Builds GAP_ANALYSIS_PROMPT from:
        #   - objective, completed step + result, graph_state, gradient_warnings
        # Calls adapter.infer() — max_tokens=800, temperature=0.1
        # Parses: {"has_gaps": bool, "confidence": float, "gap_items": [...]}
        # Returns List[QueueItem] with critical=False, depth_layer set
        # Hard cap: 3 gap items per completed step
        # Never raises — returns [] on any failure
```

**Gap items are non-critical.** They can be vetoed without blocking the main loop. Their `step_id` follows `gap-{parent_step_id}-{i}`. Wired in `_execute_plan_der()` at every `TRAILING_GAP_MIN` completed steps.

---

## 8. PiNs in the DER Loop

PiNs (Primordial Information Nodes) are typed knowledge artifacts that sit in the graph alongside coordinate nodes and landmarks. The DER loop interacts with them in two ways:

### 8.1 Context injection

When a PiN is `is_permanent=True` or has high `pin_link` weight to the active landmark cluster, it surfaces in `context_package.ambient_signals` and `context_package.manifest`. The Reviewer reads these when deciding PASS / REFINE / VETO.

A PiN of type `decision` that documents why a particular approach was chosen (e.g. "TTS primary = F5-TTS because voice cloning is core to IRIS identity") prevents the Reviewer from approving a step that would re-select Piper as the TTS engine.

### 8.2 PiN recording after task completion

After the DER loop completes a task that references files, URLs, or design decisions, the agent can anchor a PiN to crystallize that knowledge:

```python
# After a successful DER task that touched a key design file:
pin_id = mycelium_interface.record_pin(
    title="Design decision recorded during task",
    pin_type="decision",
    file_refs=[item.file_path],
    is_permanent=relevant_to_architecture,
)
# Add link from pin to the landmark it supported
mycelium_interface.add_pin_link(
    source_type="pin", source_id=pin_id,
    target_type="landmark", target_id=session_landmark_id,
    relationship="documents",
)
```

### 8.3 PiN + MCP storage

PiNs are the mechanism by which external storage systems become first-class memory nodes:
- A file in Google Drive → PiN of type `doc` with `url_refs` pointing to the Drive link
- A Discord message thread → PiN of type `note` with the channel/message URL
- A Notion page → PiN of type `doc` with the page URL and markdown content snapshot
- A GitHub issue or PR → PiN of type `fragment` with code refs and URL

When the MCP integration for these services is active, IRIS can automatically anchor PiNs as it reads from or writes to external systems, making every external artifact part of the memory graph.

---

## 9. Landmark Bridges — Cross-Project Pattern Transfer

Landmark bridges allow patterns crystallized in one project to activate immediately in another, without re-running the 12-activation crystallization cycle.

### 9.1 How bridges activate

```python
# On entering a new project, context assembly checks for bridges:
existing_bridge = landmark_index.find_bridge(
    remote_landmark_name="g1_api_healthy",   # landmark name in new project
    remote_instance_id=instance_id,
)
if existing_bridge and existing_bridge["confidence"] >= 0.80:
    # Treat as equivalent to local landmark — activate its traversal history
    local_lm = landmark_index.get_by_id(existing_bridge["local_landmark_id"])
    context_package.tier1_directives += f"\nBRIDGE: {local_lm.label} (conf={existing_bridge['confidence']:.2f})"
```

### 9.2 Bridge types and DER effect

| Bridge type | DER effect |
|-------------|------------|
| `equivalent` | Full prior activation — traversal history loaded as if same project |
| `similar` | Partial boost to `tier2_predictions` — suggested tools weighted higher |
| `inverse` | Warning injected into `gradient_warnings` — step involving this pattern triggers Reviewer scrutiny |

### 9.3 Projects don't need to share a domain

A bridge requires only the same seven-space coordinate map. A landmark from a music production workflow (`g1_audio_pipeline_stable`) can bridge to `g1_backend_health` in a software project if both represent the same underlying pattern: "primary output path verified and healthy." The coordinate signature is the same. Domain is irrelevant.

---

## 10. Mycelium Maturation Cycle

Each session:
1. **Tool calls ingested** → strengthen or weaken pheromone edges
2. **Outcomes recorded** → CORE nodes gain confidence, ORBIT nodes lose it
3. **Crystallization attempts** → successful sessions produce permanent landmarks
4. **`run_maintenance()` fires periodically:**
   - `EdgeScorer.apply_decay()` — old edges fade
   - `MapManager.run_condense()` / `run_expand()` — topology shifts
   - `LandmarkIndex.apply_landmark_decay()` — unverified landmarks lose confidence
   - `ProfileRenderer.render_dirty_sections()` — profile cache refreshed
   - `TopologyLayer.run_topology_maintenance()` — topology state updated
5. **PiN decay pass** — non-permanent PiNs without recent `pin_link` traversal lose weight; permanent PiNs are untouched

**Maturity check:**
```python
def is_mature(self) -> bool:
    # True when: >= 3 distinct spaces each have >= 1 node with confidence >= 0.6
    # Caches True indefinitely once reached
    # At maturity: Reviewer activates, context packages become rich
```

---

## 11. Post-Loop Ordering — Strict Sequence

```
1. record_outcome()         ← outcome needed for crystallization scoring
2. crystallize_landmark()   ← session data needed before clear
3. clear_session()          ← clean state before stats
4. record_plan_stats()      ← summary of everything above — always last
```

Reversing this order corrupts the graph. The sequence is fixed.

---

## 12. Proxy Methods — DER Loop ↔ Mycelium Interface

All proxy methods live in `backend/memory/interface.py`. Every call is wrapped in `try/except` — Mycelium failures NEVER block the DER loop. When `_mycelium` is None, all calls are silent no-ops.

| Method | When called | What it does |
|--------|-------------|--------------|
| `mycelium_ingest_tool_call(tool, success, pos, total, session)` | After each DER step | Records tool execution signal |
| `mycelium_record_outcome(task, outcome, session)` | After DER loop | Records "hit"/"partial"/"miss" |
| `mycelium_crystallize_landmark(session, score, outcome, label)` | After outcome | Attempts crystallization |
| `mycelium_clear_session(session)` | After crystallization | Clears session state |
| `mycelium_record_plan_stats(...)` | Last | Inserts execution stats |
| `mycelium_ingest_statement(text, session)` | After _plan_task() | Ingests planning reasoning |
| `get_task_context_package(task, session, space_subset)` | Before _plan_task() | Returns (ContextPackage, is_mature) |

---

## 13. Complete Prompt Flow Diagram

```
Frontend (chat-view.tsx)
    │ WebSocket: {type: "text_message", payload: {text: "..."}}
    ▼
IRISGateway.handle_message()                    [iris_gateway.py]
    │
    ├─ security_filter.py  ← sanitize + injection detect
    ├─ mcp_security.py     ← HyphaChannel trust enforcement
    │
    ▼
AgentKernel.process_text_message(text, session_id)   [agent_kernel.py]
    │
    ├─ [1] _sanitize_task(text)
    ├─ [2] TaskClassifier.classify(text) → (task_class, space_subset)
    ├─ [3] memory_interface.get_task_context_package()
    │       ├─ mature  → ContextPackage (coordinates + PiNs + landmarks)
    │       └─ immature → plain string
    ├─ [4] _plan_task(text, context_package, is_mature)
    ├─ [5] mycelium_ingest_statement(reasoning)
    └─ [6] route by strategy

_execute_plan_der(plan, context_package, is_mature, task_class, session_id)
    │
    ├─ token_budget = DER_TOKEN_BUDGETS[task_class]
    ├─ Build DirectorQueue from plan.steps
    │
    ├─ LOOP:
    │   ├─ DIRECTOR: queue.next_ready() → item
    │   ├─ REVIEWER: review(item, completed, context_package, is_mature)
    │   │   ├─ reads: gradient_warnings, contracts, PiN summaries
    │   │   └─ PASS / REFINE / VETO
    │   ├─ MID-LOOP EPISODIC: inject sub-task hints from episodic store
    │   ├─ EXPLORER: execute_tool() or _run_step_direct()
    │   ├─ SIGNAL: mycelium_ingest_tool_call()
    │   ├─ TOKEN CHECK: break if _tokens_used >= token_budget
    │   ├─ TRAILING DIRECTOR: analyze_gaps() → inject gap items
    │   └─ queue.mark_complete()
    │
    ├─ POST-LOOP (strictly ordered):
    │   ├─ mycelium_record_outcome()
    │   ├─ mycelium_crystallize_landmark()
    │   ├─ mycelium_clear_session()
    │   └─ mycelium_record_plan_stats()
    │
    └─ return response

IRISGateway → WebSocket → Frontend (chat-view.tsx or xterm.js TUI)
```

---

## 14. Key Files Reference

| File | Role |
|------|------|
| `backend/iris_gateway.py` | WebSocket handler, security filter, routes to AgentKernel |
| `backend/agent/agent_kernel.py` | Main agent class — sanitize, classify, plan, DER loop |
| `backend/agent/der_loop.py` | ReviewVerdict, QueueItem, DirectorQueue, Reviewer |
| `backend/agent/mode_detector.py` | AgentMode, ModeDetector, ComplexityLevel |
| `backend/agent/trailing_director.py` | TrailingDirector.analyze_gaps() — gap-filling Director |
| `backend/agent/der_constants.py` | Token budgets, cycle limits, gap range constants |
| `backend/agent/spec_engine.py` | SpecEngine — handles /spec tasks outside DER loop |
| `backend/memory/interface.py` | Proxy methods — DER loop's interface to Mycelium |
| `backend/memory/mycelium/interface.py` | MyceliumInterface, ContextPackage, core graph operations |
| `backend/memory/mycelium/interpreter.py` | CoordinateInterpreter, BehavioralPredictor, ResolutionEncoder |
| `backend/memory/mycelium/landmark.py` | LandmarkIndex — save, activate, bridge, decay |
| `backend/memory/db.py` | Schema: mycelium_pins, mycelium_pin_links, mycelium_landmark_bridges |
| `backend/memory/episodic.py` | Episodic store — Pacman lifecycle, crystallization |
| `bootstrap/coordinates.db` | Build-time coordinate graph (transfers to data/memory.db at graduation) |
| `bootstrap/pin.py` | PiN CLI — anchor, search, link, bridge |

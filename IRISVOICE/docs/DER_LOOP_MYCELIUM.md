# IRIS — DER Loop & Mycelium Memory System
## How the Agent Processes Prompts Into Executing Tasks

**File:** `IRISVOICE/docs/DER_LOOP_MYCELIUM.md`
**Last updated:** Session 6 (Gate 4)

---

## 1. Overview

IRIS uses a two-phase agent architecture:

1. **DER Loop** (Director → Explorer → Reviewer) — structured execution brain that breaks tasks into steps, filters each step through a Reviewer, executes via tools or direct model inference, and records everything to Mycelium.
2. **Mycelium Memory** — coordinate graph stored in SQLite that gives the DER loop spatial context: where the agent is, what has worked before, what failure patterns exist, and what to prioritize next.

The loop and the memory are inseparable. Without a mature Mycelium graph, the Reviewer has no signal and falls back to PASS on every step. As the graph matures, the Reviewer begins shaping the execution trajectory based on real coordinate history.

---

## 2. Entry Point — WebSocket to DER

### 2.1 Path from message to execution

```
User types message in frontend
    ↓
WebSocket → IRISGateway.handle_message()          [iris_gateway.py]
    ↓
msg_type == "text_message" → _handle_chat()
    ↓
get_agent_kernel(session_id)                       [AgentKernel instance per session]
    ↓
agent_kernel.process_text_message(text, session_id)   [agent_kernel.py]
```

### 2.2 process_text_message() — the staging area

Before the DER loop runs, four things happen in fixed order:

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
# is_mature=True → ContextPackage with full coordinate data
# is_mature=False → plain string context (graph not ready yet)

# Step 4 — Plan the task
plan = _plan_task(text, context_package=context_package, is_mature=is_mature)
# Returns ExecutionPlan with strategy + list of PlanSteps

# Step 5 — Route by strategy
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
while not queue.is_complete() and not queue.hit_cycle_limit():
    queue.cycle_count += 1

    # ── DIRECTOR ─────────────────────────────────────────────────
    item = queue.next_ready()
    # next_ready() returns the first item where:
    #   - not in completed_ids
    #   - not in vetoed_ids
    #   - all depends_on IDs are in completed_ids
    if item is None:
        break  # dependency deadlock — no step can proceed

    # ── REVIEWER ─────────────────────────────────────────────────
    verdict, feedback = reviewer.review(
        item, completed_steps, context_package, is_mature
    )

    if verdict == ReviewVerdict.VETO:
        item.veto_count += 1
        if item.veto_count >= DER_MAX_VETO_PER_ITEM:   # 2
            queue.mark_vetoed(item.step_id)
        continue  # try again next cycle (or skip if maxed)

    if verdict == ReviewVerdict.REFINE:
        item.description = feedback   # Reviewer rewrote the step

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

    # ── QUEUE UPDATE ─────────────────────────────────────────────
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

**How it works:**
```python
class Reviewer:
    REVIEWER_MAX_TOKENS = 200
    REVIEWER_TEMPERATURE = 0.0   # deterministic

    def review(self, item, completed_steps, context_package, is_mature):
        # Fast path: no Mycelium data → PASS immediately
        if not context_package or not is_mature:
            return ReviewVerdict.PASS, None

        # Build compact prompt:
        # - objective
        # - last 3 completed steps (summaries)
        # - gradient_warnings from context_package
        # - active_contracts from context_package

        # Call model inference
        response = adapter.infer(prompt, max_tokens=200, temperature=0.0)

        # Parse JSON: {"verdict": "pass|refine|veto", "reason": "...", "refined": "..."}
        # Return (ReviewVerdict.PASS/REFINE/VETO, refined_description or reason)

        # Never raises — any exception returns (PASS, None)
        except Exception:
            return ReviewVerdict.PASS, None
```

**Three verdicts:**
- `PASS` — step approved as-is, continue to Explorer
- `REFINE` — Reviewer rewrote the step description (item.description updated), continue to Explorer
- `VETO` — step rejected; veto_count incremented; after 2 vetoes the step is permanently skipped

**When the Reviewer is active:** Only when Mycelium is mature (`is_mature=True`) AND a context package with real gradient warnings / contracts is available. In the early sessions, every Reviewer call is a fast-path PASS.

---

## 4. Mode Detection — Before Planning

Before `_plan_task()` is called, the `ModeDetector` determines what kind of task this is:

```python
class AgentMode(Enum):
    SPEC       # /spec — route to SpecEngine, bypass DER loop
    RESEARCH   # /research
    IMPLEMENT  # default
    DEBUG      # /debug
    TEST       # /test
    REVIEW     # /review
```

**Detection priority:**
1. **Slash commands** (deterministic, confidence 1.0): `/spec`, `/debug`, `/ask`, etc.
2. **Keyword inference**: multi-word keyword phrases score higher than single words
3. **Default**: IMPLEMENT with confidence 0.3

**Special case — SPEC mode bypasses DER entirely.** When `mode == AgentMode.SPEC`, the task routes directly to `SpecEngine.produce()` and the DER loop never runs. This is intentional — spec production is a planning operation, not an execution one.

**Complexity detection:**
- `SIMPLE`: "small", "quick", "minor", "just", "tweak", "rename"
- `COMPLEX`: "system", "architecture", "full", "complete", "redesign"
- `UNKNOWN`: neither dominates

**Clarification logic:** If the task is SPEC + UNKNOWN complexity OR confidence < 0.5 AND the task is long, `needs_clarification=True` is returned. Suppressed if Mycelium already knows the answer (`topology_primitive != "unknown"`).

---

## 5. DER Constants

```python
# Trailing crystallizer gap range
TRAILING_GAP_MIN = 2    # min completed steps before crystallizer checks
TRAILING_GAP_MAX = 4    # max gap before crystallizer must run

# Token budgets per mode (enforcement: NOT YET IMPLEMENTED — see gaps)
DER_TOKEN_BUDGETS = {
    "SPEC":      60_000,
    "RESEARCH":  80_000,
    "IMPLEMENT": 40_000,
    "DEBUG":     30_000,
    "TEST":      40_000,
    "REVIEW":    20_000,
    "DEFAULT":   40_000,
}

# Safety limits
DER_EMERGENCY_STOP = 200       # cycle count last resort
DER_MAX_VETO_PER_ITEM = 2      # vetoes before permanent skip
DER_MAX_CYCLES = 40            # hard cycle cap
DER_WRITE_LOCK_TIMEOUT = 5.0   # Mycelium write lock timeout (seconds)
```

---

## 6. Trailing Director — Gap Filling (Defined, Not Yet Wired)

The `TrailingDirector` is a second Director brain that runs *behind* the main loop, analyzing completed steps for depth gaps and injecting gap-filling items back into the queue.

```python
class TrailingDirector:
    def analyze_gaps(self, completed_step, plan, context_package, is_mature):
        # Builds a GAP_ANALYSIS_PROMPT:
        # - objective
        # - the completed step + its result
        # - graph_state from context_package
        # - gradient_warnings
        # Calls adapter.infer() with max_tokens=800, temperature=0.1
        # Parses: {"has_gaps": bool, "confidence": float, "gap_items": [...]}
        # Returns List[QueueItem] with critical=False, depth_layer set
        # Hard cap: 3 gap items per completed step
        # Never raises — returns [] on any failure
```

**Gap items are non-critical by design.** They can be vetoed without blocking the main loop. Their `step_id` follows the pattern `gap-{parent_step_id}-{i}`.

**Current status:** `TrailingDirector.analyze_gaps()` is fully implemented. It is **NOT called anywhere in `agent_kernel._execute_plan_der()`**. Wiring it in is a known gap (see Section 8).

---

## 7. Mycelium Memory System

### 7.1 What Mycelium is

Mycelium is a coordinate graph stored in SQLite (`bootstrap/coordinates.db` during build, `data/memory.db` at runtime). It encodes the agent's spatial knowledge:

- **Where files are** in coordinate space (CORE, ACQUIRING, EXPLORING, EVOLVING, ORBIT)
- **Which paths are reinforced** by repeated test passes (pheromone edges)
- **What has failed** (high-signal failures with scores)
- **Behavioral contracts** derived from repeated patterns
- **Landmarks** — permanent verified features (crystallized after 3 passes)

### 7.2 Maturity check

```python
def is_mature(self) -> bool:
    # True when: >= 3 distinct spaces each have >= 1 node with confidence >= 0.6
    # Caches True indefinitely once reached
    # At maturity, the Reviewer activates and context packages become rich
```

### 7.3 ContextPackage — the DER loop's compass

When Mycelium is mature, `get_task_context_package()` returns a `ContextPackage`:

```python
@dataclass
class ContextPackage:
    mycelium_path: str        # Encoded coordinate path for this task
    topology_path: str        # Current topology layer context
    manifest: Dict            # Address registry (URLs, tokens, summaries)
    tier1_directives: str     # Top-level goals / primary direction
    tier2_predictions: str    # Predicted next steps based on graph
    tier3_failures: str       # Known failure patterns + resolutions
    active_contracts: str     # Behavioral rules currently enforced
    gradient_warnings: str    # Danger zones from prior failures
    causal_context: str       # Why the graph is in its current state
    ambient_signals: str      # Background signals
    topology_position: str    # Current position in topology
    task_class: str           # Classification of this task
```

Key accessor:
```python
def get_system_zone_content(self) -> str:
    # Returns: contracts + warnings + context + directives + path + topology + signals
    # Used by _run_step_direct() to prime direct model inference
```

### 7.4 Proxy methods — how the DER loop talks to Mycelium

All proxy methods live in `backend/memory/interface.py`. Every call is wrapped in `try/except` — Mycelium failures NEVER block the DER loop. When `_mycelium` is None, all calls are silent no-ops.

| Method | When called | What it does |
|--------|-------------|--------------|
| `mycelium_ingest_tool_call(tool, success, pos, total, session)` | After each DER step | Records tool execution signal into graph |
| `mycelium_record_outcome(task, outcome, session)` | After DER loop completes | Records "hit" / "partial" / "miss" outcome |
| `mycelium_crystallize_landmark(session, score, outcome, label)` | After outcome recording | Attempts to crystallize a permanent landmark |
| `mycelium_clear_session(session)` | After crystallization | Clears session state, pre-warms cache if mature |
| `mycelium_record_plan_stats(...)` | Last, after clear | Inserts execution stats into mycelium_plan_stats table |
| `mycelium_ingest_statement(text, session)` | After _plan_task() | Ingests planning reasoning as coordinate statement |
| `get_task_context_package(task, session, space_subset)` | Before _plan_task() | Returns (ContextPackage, is_mature) or (string, False) |

### 7.5 Post-loop ordering — why order matters

```
1. record_outcome()       ← must run before crystallize (outcome needed for scoring)
2. crystallize_landmark() ← must run before clear (session data needed)
3. clear_session()        ← must run before record_stats (clean state for stats)
4. record_plan_stats()    ← always last (summary of everything above)
```

Reversing this order corrupts the graph. The sequence is fixed.

### 7.6 How Mycelium matures over sessions

Each session:
1. Tool calls are ingested → strengthen or weaken pheromone edges
2. Outcomes are recorded → CORE nodes gain confidence, ORBIT nodes lose it
3. Crystallization attempts → successful sessions produce permanent landmarks
4. `run_maintenance()` runs periodically:
   - `EdgeScorer.apply_decay()` — old edges fade
   - `MapManager.run_condense()` / `run_expand()` — topology shifts
   - `LandmarkIndex.apply_landmark_decay()` — unverified landmarks lose confidence
   - `ProfileRenderer.render_dirty_sections()` — profile cache refreshed
   - `TopologyLayer.run_topology_maintenance()` — topology state updated

---

## 8. Known Gaps (Not Yet Implemented)

These are architectural features that are defined but incomplete or unwired:

### 8.1 Trailing Director not called from DER loop
- **File:** `agent_kernel.py` → `_execute_plan_der()`
- **Gap:** `TrailingDirector.analyze_gaps()` exists and is correct but is never called
- **Fix needed:** After each `queue.mark_complete()`, check if `len(completed_items)` mod `TRAILING_GAP_MIN` == 0, call `trailing_director.analyze_gaps(item, plan, context_package, is_mature)`, and add returned gap items via `queue.add_item()`

### 8.2 DER token budgets defined but not enforced
- **File:** `agent_kernel.py` → `_execute_plan_der()`
- **Gap:** `DER_TOKEN_BUDGETS` constants exist in `der_constants.py` but `_execute_plan_der()` only uses cycle count (`max_cycles = 40`), not token count
- **Fix needed:** Track `_der_tokens_used` across the loop, check against `DER_TOKEN_BUDGETS[mode]` each iteration, break when exceeded

### 8.3 CoordinateInterpreter and BehavioralPredictor are empty stubs
- **File:** `backend/memory/mycelium/interpreter.py`
- **Gap:** `ResolutionEncoder` is implemented; `CoordinateInterpreter` and `BehavioralPredictor` are `class X: pass`
- **Fix needed:** Implement both classes based on their spec roles

### 8.4 Mode detection not wired to _plan_task temperature
- **File:** `agent_kernel.py`
- **Gap:** `ModeDetector.detect()` result exists but the detected mode doesn't flow into `_plan_task()` to select the correct token budget or temperature
- **Fix needed:** Pass `mode_result.mode` into `_plan_task()` and `_execute_plan_der()`

### 8.5 record_plan_stats signature mismatch
- **File:** `backend/memory/interface.py` vs `backend/memory/mycelium/interface.py`
- **Gap:** The proxy method signature and the underlying MyceliumInterface signature have field mismatches (missing `plan_id`, `task` fields in some call sites)
- **Fix needed:** Audit and align both signatures

---

## 9. Complete Prompt Flow Diagram

```
Frontend (chat-view.tsx)
    │ WebSocket send: {type: "text_message", payload: {text: "..."}}
    ▼
IRISGateway.handle_message()                    [iris_gateway.py]
    │ routes by msg_type
    ▼
_handle_chat(client_id, payload, session_id)
    │
    ▼
AgentKernel.process_text_message(text, session_id)   [agent_kernel.py]
    │
    ├─ [1] _sanitize_task(text)
    │       └─ replaces [CORE], [ORBIT], etc. with [filtered]
    │
    ├─ [2] TaskClassifier.classify(text)
    │       └─ → (task_class, space_subset)
    │
    ├─ [3] memory_interface.get_task_context_package(task, session_id, space_subset)
    │       ├─ mature → ContextPackage, is_mature=True
    │       └─ immature → context_string, is_mature=False
    │
    ├─ [4] _plan_task(text, context_package, is_mature)
    │       ├─ temperature = 0.1 if is_mature, else 0.25
    │       ├─ calls model → parses ExecutionPlan JSON
    │       └─ fallback: single-step plan with strategy="do_it_myself"
    │
    └─ [5] route by strategy
            │
            ├─ "do_it_myself" → _execute_plan_der()
            │
            └─ else → ReAct/agentic loop

_execute_plan_der(plan, context_package, is_mature, task_class, session_id)
    │
    ├─ Build DirectorQueue from plan.steps
    │
    ├─ LOOP (while not complete and not hit_cycle_limit):
    │   │
    │   ├─ DIRECTOR: queue.next_ready() → item (dependency-aware)
    │   │
    │   ├─ REVIEWER: reviewer.review(item, completed_steps, context_package, is_mature)
    │   │   ├─ Fast path (immature): return PASS immediately
    │   │   ├─ PASS  → continue to Explorer
    │   │   ├─ REFINE → update item.description, continue to Explorer
    │   │   └─ VETO  → veto_count++; skip if >= 2; else retry next cycle
    │   │
    │   ├─ EXPLORER:
    │   │   ├─ item.tool set → _tool_bridge.execute_tool(item.tool, item.params)
    │   │   └─ no tool    → _run_step_direct(item, context_package, session_id)
    │   │
    │   ├─ SIGNAL: mycelium_ingest_tool_call(tool, success, pos, total, session)
    │   │
    │   └─ queue.mark_complete(item.step_id)
    │
    ├─ POST-LOOP (strictly ordered):
    │   ├─ mycelium_record_outcome(task, outcome, session_id)
    │   ├─ mycelium_crystallize_landmark(session_id, score, outcome, label)
    │   ├─ mycelium_clear_session(session_id)
    │   └─ mycelium_record_plan_stats(stats)
    │
    └─ return "\n".join(step_outputs)

IRISGateway
    │ send: {type: "chat_message", payload: {role: "assistant", content: response}}
    ▼
Frontend (chat-view.tsx) receives and displays response
```

---

## 10. Key Files Reference

| File | Role |
|------|------|
| `backend/iris_gateway.py` | WebSocket handler, routes to AgentKernel |
| `backend/agent/agent_kernel.py` | Main agent class — sanitize, classify, plan, DER loop |
| `backend/agent/der_loop.py` | ReviewVerdict, QueueItem, DirectorQueue, Reviewer |
| `backend/agent/mode_detector.py` | AgentMode, ModeDetector, ComplexityLevel |
| `backend/agent/trailing_director.py` | TrailingDirector.analyze_gaps() — gap-filling Director |
| `backend/agent/der_constants.py` | Token budgets, cycle limits, gap range constants |
| `backend/agent/spec_engine.py` | SpecEngine — handles /spec tasks outside DER loop |
| `backend/memory/interface.py` | Proxy methods — DER loop's interface to Mycelium |
| `backend/memory/mycelium/interface.py` | MyceliumInterface, ContextPackage, core graph operations |
| `backend/memory/mycelium/interpreter.py` | ResolutionEncoder (implemented), stubs for CoordinateInterpreter/BehavioralPredictor |
| `bootstrap/coordinates.db` | Build-time coordinate graph (transfers to data/memory.db at graduation) |

# Context Engineering — IRIS Memory Architecture

**Version:** 1.0
**Status:** A+B implemented, C specced
**Last updated:** 2026-03-29
**Owner:** IRIS Core Team

---

## What This Document Is

This document defines how IRIS uses memory as an **active participant in cognition**,
not as a post-hoc log. It captures the theoretical model, the current implementation
state, what A+B add, and the full specification for Option C with the requirements
needed to achieve a >95% task success rate.

The term **context engineering** refers to the deliberate design of *what information
is available to the model at each moment during a task* — not just at the start, but
throughout every reasoning step. The distinction from "prompting" is that context
engineering is structural: it defines the shape of the information pipeline, not the
wording of individual instructions.

---

## 1. The Cognitive Model

### Memory as Active Cognition

Human working memory does not work like a lookup table queried once at the start of a
task. It operates continuously: facts are retrieved as they become relevant, intermediate
findings are held "in mind" and shape what gets attended to next, and past failures
produce hesitation before repeating a known-bad action.

The goal for IRIS is the same model:

```
Before acting:   retrieve relevant history (successes + failures)
During acting:   update working memory with intermediate findings
Before each step: check if this exact sub-action failed before
After acting:    write the experience back so it informs the next task
```

This creates a **bilateral memory loop**: reads inform the present, writes build the
future. A system that only reads from memory (but never writes completed experiences)
learns nothing across sessions. A system that only writes (but never reads mid-task)
loses continuity within a session.

### The Three Memory Layers in IRIS

```
┌─────────────────────────────────────────────────────────────┐
│ LAYER 1 — Mycelium Coordinate Graph                         │
│ What it knows: topology, trajectories, gradient warnings,   │
│                landmarks, pheromone edges                   │
│ When it reads: BEFORE planning (via ContextPackage)         │
│ When it writes: during execution (ingest_tool_call) +       │
│                 after completion (crystallize_landmark)     │
│ Maturity threshold: 3 spaces × confidence ≥ 0.6            │
│ Status: FULLY WIRED                                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ LAYER 2 — Episodic Store                                    │
│ What it knows: completed task summaries, tool sequences,    │
│                outcome scores, failure reasons              │
│ When it reads: BEFORE planning (assemble_episodic_context)  │
│ When it writes: [GAP — fixed in Option A]                   │
│ Search method: cosine similarity on embeddings              │
│ Status: READ PATH WIRED, WRITE PATH OPEN (→ fixed by A)     │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ LAYER 3 — Working Memory (ContextManager)                   │
│ What it knows: zones: semantic_header, episodic_injection,  │
│                task_anchor, active_tool_state,              │
│                working_history (compressed at 80%)          │
│ When it reads: [GAP — fixed in Option B, each DER step]     │
│ When it writes: [GAP — fixed in Option B, after each step]  │
│ Status: INITIALIZED BUT IDLE DURING DER LOOP (→ fixed by B) │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Current Foundation (pre-A/B)

### What Works

| Component | Status | Evidence |
|-----------|--------|---------|
| Mycelium coordinate graph | Mature (confidence 0.95) | `bootstrap/session_start.py` |
| ContextPackage injection into Director | Working | `agent_kernel.py:1690` |
| Reviewer reads gradient_warnings | Working | `der_loop.py:137-144` |
| Tool call ingestion (Mycelium) | Working | `agent_kernel.py:2352` |
| Landmark crystallization after task | Working | `agent_kernel.py:2381` |
| Episodic store schema + embeddings | Built | `memory/episodic.py` |
| `assemble_episodic_context()` | Built, called | `memory/interface.py:121` |
| Working memory zones (ContextManager) | Built | `memory/working.py` |
| `append_to_session()` | Built, never called | `memory/interface.py:196` |
| DER loop (Director/Explorer/Reviewer) | Running | `agent_kernel.py:2228` |
| `_store_task_episode()` | Built, never called | `agent_kernel.py:376` |

### The Open Loop (pre-A/B)

```
get_task_context() calls assemble_episodic_context(task)
    │
    └─ retrieve_similar(task)     ← queries episodic DB
    └─ retrieve_failures(task)    ← queries episodic DB
           │
           └─ episodic DB has ZERO ROWS
              because _store_task_episode() is never called
              │
              └─ context assembled with NO past experience
                 even after 100+ sessions
```

```
DER loop runs Explorer step N
    │
    └─ step_result returned
    └─ mycelium_ingest_tool_call(...)   ← Mycelium gets the signal
    └─ append_to_session() NOT CALLED   ← working memory stays empty
           │
           └─ step N+1 starts
              with identical context as step 1
              even if step N discovered key information
```

---

## 3. Option A — Close the Episodic Loop

### What Changes

**File:** `backend/agent/agent_kernel.py`

**Change 1:** Add `session_id` and `duration_ms` parameters to `_store_task_episode()`
so it works correctly when called from `_execute_plan_der()` (which uses a local
`_session` variable rather than `self.session_id`).

**Change 2:** Track `_start_time` at the beginning of `_execute_plan_der()` so
`duration_ms` is accurate.

**Change 3:** After the outcome recording block at the end of `_execute_plan_der()`,
call `_store_task_episode()` with the completed tool sequence and full output.

### What This Unlocks

After Option A, every DER-executed task writes an Episode to the episodic store:
- `task_summary` = the original user task text
- `tool_sequence` = list of {tool, params, step_number, description} for all completed steps
- `full_content` = concatenated step outputs
- `outcome_type` = "success" | "failure"

On the **next** task with a semantically similar prompt:
1. `assemble_episodic_context()` finds it via cosine similarity
2. The episodic context string gets injected into the prompt as "RELEVANT PAST SUCCESSES"
   or "WARNINGS FROM PAST FAILURES"
3. The Director now knows: "last time I did X, I used tools A→B→C and it worked"

### Acceptance Criteria for A

- [ ] After completing a multi-step DER task, `episodic.get_stats()["total_episodes"] > 0`
- [ ] Running the same task a second time produces a non-empty episodic_injection zone
- [ ] Failure episodes appear in `assemble_episodic_context()` output with failure_reason
- [ ] Deduplication prevents identical tasks from creating duplicate episodes
- [ ] No exception is raised if memory_interface is None (graceful no-op)

---

## 4. Option B — Working Memory During Execution

### What Changes

**File 1:** `backend/agent/agent_kernel.py` — `_execute_plan_der()`

After each Explorer step, append the step result to the working memory `working_history`
zone. This builds a session-scoped "what I've found so far" that gets compressed at 80%
context usage.

**File 2:** `backend/agent/agent_kernel.py` — `_run_step_direct()`

Inject the rendered working memory context into the prompt for tool-less steps. This
means each direct-inference step sees the intermediate findings of all preceding steps
in the current DER loop.

**File 3:** `backend/agent/der_loop.py` — `Reviewer`

When `is_mature=False` (immature graph), instead of always returning `PASS`, run
heuristic checks:
- Destructive operation keywords → VETO
- Duplicate of a recently completed step → REFINE
- Unknown territory → PASS (same as before, but explicit)

### What This Unlocks

**Within a session:** When step 3 needs to know what step 1 found, it does — because
the ContextManager's `working_history` zone accumulates findings and is injected into
the prompt for each direct-inference step.

**On new installs:** The Reviewer becomes immediately useful even before the Mycelium
graph matures. Safety checks fire from day one.

**Tool call context:** When Explorer calls a tool and gets a result, that result is
appended to `active_tool_state`. The next `_run_step_direct` call reads the full
ContextManager render which includes all active tool state.

### Acceptance Criteria for B

- [ ] After Explorer step N completes, `memory_interface.context._sessions[session_id]["working_history"]` is non-empty
- [ ] `_run_step_direct()` includes working memory content in its prompt
- [ ] Reviewer returns VETO for a step containing "delete all" even when `is_mature=False`
- [ ] Reviewer returns REFINE for a step that duplicates a recently completed step
- [ ] No regression on existing DER tests

---

## 5. Option C — Continuous Context Engineering (>95% Success Spec)

### Overview

Option C restructures context assembly from a one-shot event at planning time to a
**continuous process** that refreshes at every DER cycle boundary. This is the full
realization of the cognitive model from Section 1.

The target: **>95% task completion rate** on multi-step tasks with 3+ tool calls,
measured as (tasks where all non-vetoed steps complete without [STEP ERROR]) /
(total tasks routed to DER loop).

### Architecture Change

```
CURRENT (A+B):
  T=0: get_task_context_package() → ContextPackage (frozen)
  T=1..N: ContextPackage unchanged throughout DER loop
  T=N: crystallize_landmark() → write to Mycelium

TARGET (C):
  T=0: get_task_context_package() → ContextPackage (initial)
  T=1: Explorer step 1 result → update working memory
  T=2: re-evaluate ContextPackage.gradient_warnings + episodic retrieval
       for the *current* sub-problem, not just the initial task
  T=3..N: same — context refreshes each cycle
  T=N: crystallize + store episode
```

### Components Required for C

#### C.1 — LiveContextPackage

A mutable ContextPackage wrapper that can be refreshed mid-loop.

```python
class LiveContextPackage:
    """Wraps ContextPackage and refreshes coordinate signals each cycle."""

    def refresh(
        self,
        session_id: str,
        current_step: QueueItem,
        completed_items: List[QueueItem],
        memory_interface: MemoryInterface,
    ) -> None:
        """
        Re-query Mycelium for the current coordinate position given
        completed steps so far. Updates gradient_warnings and tier2_predictions.
        Called by Director at the start of each DER cycle.

        MUST complete in < 50ms — uses cached navigator paths.
        MUST fall back gracefully if Mycelium is unavailable.
        """
```

#### C.2 — BehavioralPredictor (Domain 5.2 from GOALS.md)

Currently a stub. Must be implemented to populate `tier2_predictions` in the
ContextPackage with likely next steps based on pheromone edge weights.

```python
class BehavioralPredictor:
    """
    Given current coordinate position + task class, predicts the 3 most
    likely next steps. Feeds into LiveContextPackage.tier2_predictions.

    Requirement: predictions must match actual next step ≥ 60% of the time
    on a held-out test set of 20 multi-step tasks (measured after 50 sessions).
    """

    def predict(
        self,
        session_id: str,
        current_node_ids: List[str],
        task_class: str,
        completed_tools: List[str],
    ) -> List[str]:
        """Returns top-3 predicted next tool/action names."""
```

#### C.3 — CoordinateInterpreter (Domain 5.1 from GOALS.md)

Currently a stub. Must arbitrate coordinate conflicts before they reach the
ContextPackage. Without this, conflicting signals from two recent tasks can
produce contradictory gradient_warnings.

```python
class CoordinateInterpreter:
    """
    Resolves conflicts when two coordinate nodes make opposing claims
    about the same axis. Stores resolution basis in mycelium_conflicts table.

    Resolution strategy:
    1. Prefer the node with higher confidence
    2. If equal confidence, prefer the more recent traversal
    3. If same session, prefer the node on the pheromone-strongest edge
    """

    def resolve(
        self,
        space_id: str,
        axis: str,
        node_a: str,
        node_b: str,
    ) -> float:
        """Returns the resolved coordinate value."""
```

#### C.4 — Mid-loop Episodic Retrieval

At each DER cycle boundary, run a targeted episodic query for the *current step's*
sub-task, not the original user task. This catches cases where a sub-problem (e.g.,
"read file at path X") has been solved many times before, even if the parent task
is new.

```python
# In _execute_plan_der(), each cycle:
_sub_task_episodes = memory_interface.episodic.retrieve_similar(
    task=item.description,   # sub-task, not plan.original_task
    limit=2,
    min_score=0.6,
)
# Inject as a hint into the item's coordinate_signal field
if _sub_task_episodes:
    item.coordinate_signal += "\nSUB-TASK HINT: " + _sub_task_episodes[0]["task_summary"]
```

#### C.5 — Predictive Pre-warming

Before the DER loop starts, use BehavioralPredictor to pre-fetch the likely next 3
tool results from cache. This overlaps network/disk I/O with the Reviewer phase,
reducing perceived latency on multi-step tasks.

```
Reviewer validates step N
     │ (parallel)
     └─ Prefetch: predicted tool N+1 result from cache
           │
           └─ If prediction correct: step N+1 has result ready
              If prediction wrong: fall back to live execution
```

### >95% Success Rate Requirements

The following conditions must ALL be true for the system to achieve >95%:

| Requirement | Metric | How to Measure |
|-------------|--------|----------------|
| Episodic store populated (A) | >0 episodes after 1st session | `episodic.get_stats()` |
| Episodic retrieval improves plan | Matching episodes injected ≥ 70% of tasks | Log episodic_injection zone length |
| Working memory continuity (B) | working_history non-empty after step 1 | ContextManager._sessions |
| Reviewer active on new installs (B) | VETO rate > 0 on destructive steps | Reviewer test |
| BehavioralPredictor accuracy (C.2) | ≥60% next-step prediction accuracy | 50-session eval |
| CoordinateInterpreter (C.3) | Zero unresolved conflicts in mycelium_conflicts | DB query |
| Mid-loop episodic retrieval (C.4) | Sub-task hints fire on ≥30% of steps | Step-level logging |
| LiveContextPackage refresh (C.1) | <50ms per refresh, ≥1 refresh per DER loop | Timing logs |
| Mycelium confidence | ≥0.85 (currently 0.95 — maintain) | session_start.py |
| Episode dedup threshold | DEDUP_THRESHOLD=0.95 prevents >5% duplication | episodic stats |

### Option C Acceptance Test (the graduate condition)

```bash
# Run the multi-step task evaluation suite (minimum 20 tasks):
python -m pytest backend/tests/test_context_engineering.py -v

# Requirements that must pass:
# - test_episodic_roundtrip: store → retrieve → inject into prompt
# - test_working_memory_continuity: step N+1 sees step N result
# - test_reviewer_heuristic: VETO fires on destructive ops without mature graph
# - test_behavioral_predictor_accuracy: ≥60% prediction accuracy
# - test_live_context_package_refresh: refresh < 50ms
# - test_mid_loop_retrieval: sub-task episodes injected during DER
# - test_success_rate: ≥95% of DER tasks complete without STEP ERROR

python bootstrap/query_graph.py --summary
# Must show: BehavioralPredictor returning non-empty tier2_predictions
```

---

## 6. Implementation Timeline

| Phase | Items | Status |
|-------|-------|--------|
| A | Episodic loop closure | Implemented (this session) |
| B | Working memory + Reviewer heuristics | Implemented (this session) |
| C.1 | LiveContextPackage | Spec complete, not built |
| C.2 | BehavioralPredictor | Domain 5.2 in GOALS.md |
| C.3 | CoordinateInterpreter | Domain 5.1 in GOALS.md |
| C.4 | Mid-loop episodic retrieval | Spec complete, not built |
| C.5 | Predictive pre-warming | Future |

---

## 7. Data Flow After A+B (Complete Picture)

```
USER MESSAGE
     │
     ▼
iris_gateway._handle_chat()
     │
     ▼
agent_kernel.process_text_message(text, session_id)
     │
     ├─ 1. ConversationMemory.add_message("user", text)
     │
     ├─ 2. TaskClassifier.classify(text)
     │       → (task_class, space_subset)
     │
     ├─ 3. [LAYER 1] MyceliumInterface.get_task_context_package()
     │       → ContextPackage {
     │           tier1_directives,
     │           tier2_predictions,    ← stub until C.2
     │           tier3_failures,
     │           gradient_warnings,    ← from mature graph
     │           active_contracts,
     │         }
     │
     ├─ 4. [LAYER 2] episodic.assemble_episodic_context(text)  ← NOW HAS DATA (A)
     │       → "RELEVANT PAST SUCCESSES: ..."
     │       → "WARNINGS FROM PAST FAILURES: ..."
     │
     ├─ 5. [LAYER 3] ContextManager.assemble_for_task()        ← NOW POPULATED (B)
     │       → zones: semantic_header + episodic_injection
     │                + task_anchor + active_tool_state (empty)
     │                + working_history (empty)
     │
     ├─ 6. _plan_task() → ExecutionPlan
     │       → mycelium_ingest_statement("task required strategy: ...")
     │
     └─ 7. _execute_plan_der(plan, context_package, ...)
           │
           ├─ LOOP: for each QueueItem:
           │    │
           │    ├─ Reviewer.review(item, completed_items, context_package, is_mature)
           │    │    ├─ if is_mature: use gradient_warnings + active_contracts
           │    │    └─ if not mature: _heuristic_review()   ← NEW (B)
           │    │         ├─ check destructive keywords → VETO
           │    │         └─ check duplicate steps → REFINE
           │    │
           │    ├─ Explorer executes step (tool or direct inference)
           │    │    └─ if _run_step_direct():
           │    │         inject get_assembled_context(session_id)  ← NEW (B)
           │    │
           │    ├─ mycelium_ingest_tool_call(tool, success, session_id)
           │    │
           │    └─ append_to_session(session_id, step_result, "working_history")  ← NEW (B)
           │
           ├─ mycelium_record_outcome()
           ├─ mycelium_crystallize_landmark()
           ├─ mycelium_clear_session()
           ├─ mycelium_record_plan_stats()
           └─ _store_task_episode(task, tools, outcome, session_id)  ← NEW (A)
                → episodic.store(episode, score)
                → episode_indexer.index_episode(episode_id, session_id)
                → Mycelium: record_outcome + crystallize_landmark

RESPONSE → user
```

---

## 8. What "Context Engineering" Means for IRIS

The phrase comes from Google's research practice of treating the context window as
a **first-class engineering artifact** — not a prompt, but a pipeline. Every token
in the context has a cost and a benefit. The goal is to maximize the information
density of what the model sees at each moment.

For IRIS specifically:

1. **The ContextPackage is the semantic layer** — compressed coordinate signals
   that carry architectural knowledge from the Mycelium graph. It tells the Director
   *where* it is in solution space before any LLM call.

2. **The episodic injection is the experiential layer** — "I've done this before
   and it worked / failed this way." Without episodes, this zone is empty and the
   model has no experiential prior.

3. **The working memory is the continuity layer** — what has been found *in this
   session*. Without appending step results, each Explorer step starts cold even
   though the session has accumulated knowledge.

4. **The Reviewer is the safety layer** — checks against known dangers (gradient
   warnings) and contracts before executing. When the graph is immature, heuristic
   checks fill the gap.

All four layers must be populated for the system to behave like a working brain
rather than a stateless query processor.

---

*This document is a living spec. Update it as C components are built.*
*Test commands: `python -m pytest backend/tests/test_context_engineering.py -v`*
*Architecture contracts enforced in: `bootstrap/GOALS.md` Domain 1 + Domain 5*

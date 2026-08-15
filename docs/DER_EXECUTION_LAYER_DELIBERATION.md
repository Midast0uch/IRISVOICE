# DER Execution Layer — Deliberation Document

**Purpose:** Map the terrain before any code. Where DER is *now* (grounded in actual
code), where it is *supposed* to be (foundational docs), where the MorphoHDL/Caducean
handoff points, every issue, and recommendations. This is a deliberation artifact, not
a spec and not an implementation plan. Nothing here is committed to code.

**Read alongside:**
- `docs/DER_LOOP_MYCELIUM.md` — the intended DER + Mycelium design (v1.7)
- `docs/handoffs/morphohdl-irisvoice-handoff.md` — Caducean physics + AIDE² outer-loop research

---

## 1. The core tension (stated plainly)

The foundational doc says DER should be an **enabling execution layer**: the agent
always has the tool bridge, memory (Mycelium/Pacman/PiNs) is the *thinking substrate*,
and the agent *decides*. The built code does the opposite in one critical place — it
**chooses the tool for the agent up front** and the Explorer either runs that
pre-chosen tool or does bare inference with **no capability to act**.

That is the "hand-holding" you identified. It is not a styling problem; it is a control-
flow problem in how steps are planned and executed.

---

## 2. Current state — grounded in code

All line numbers from `backend/agent/agent_kernel.py` (7409 lines) and
`backend/agent/der_loop.py` as read this session.

### 2.1 Planning assigns the tool up front (the hand-holding root)
`_plan_task()` asks the model to return a JSON plan where **each step carries a `tool`
field** (`agent_kernel.py:3658`):
```python
tool=raw_step.get("tool"),          # planner decides the tool here
params=raw_step.get("params", {}),
```
So the **Director/planner** is the one choosing which tool each step uses, before
execution. The agent is told "use tool X for step N."

### 2.2 Execution: tool bridge only reachable if pre-assigned
- **Tool path:** `_der_run_step_execution()` (`agent_kernel.py:5846`) runs
  `self._tool_bridge.execute_tool(item.tool, ...)` — but ONLY `if item.tool and
  self._tool_bridge is not None`. The tool must have been pre-assigned by the planner.
- **Tool-less path:** `_run_step_direct()` (`agent_kernel.py:5789-5826`) does
  **`self.infer(...)` with NO tool bridge in scope at all**. It builds a prompt from
  context + objective + step description and returns `result.raw_text or
  f"[step {item.step_number} completed]"`. There is no code path here that lets the
  model discover or invoke a tool.

**Consequence (the bug class from pin_c36415be4335 / pin_00a08fa83935):** when the
planner returns `tool: null` (weak local model, or the planning prompt omitted the
tools list), the step falls into `_run_step_direct`, which cannot act → stub
`[step N completed]` → Pacman stores 0. The system "completed" the step without doing
anything. This is hand-holding failing: the agent was never *empowered* to act, it was
only *told* what to do, and when the tell was missing it did nothing.

### 2.3 The tool bridge IS available — it is just gated wrong
`self._tool_bridge = get_agent_tool_bridge()` (`agent_kernel.py:2611`) is instantiated
on the kernel. The capability exists. The problem is purely that `_run_step_direct`
does not expose it, and the planner is expected to pre-pick tools instead of the agent
resolving them against the live tool registry at execution time.

### 2.4 Reviewer is correctly a membrane (good — keep this)
`der_loop.py:5-6`: "The Reviewer is a membrane, not a gate. It never blocks on failure
— always falls back to PASS." This is the right design and should be preserved in any
pivot. The Reviewer shapes via `gradient_warnings` / `active_contracts` / PiN summaries
(`DER_LOOP_MYCELIUM.md §3.4`), it does not command tools.

### 2.5 Budget (just changed this session)
- `DER_TOKEN_BUDGETS` was a flat per-mode cap (`der_constants.py:68-77`). Now
  (`agent_kernel.py:4757-4767`) the DER loop budget = `max(context_window × 0.9,
  floor)` — derived from the model's real context window, flat caps kept only as a
  safety floor, no upper cap. This lets each model use its full window.
- `resolve_context_window()` now trusts the live local model manager's actual `n_ctx`
  (`agent_kernel.py:892-940`), so a local Bonsai 27B at 32768 resolves to 32768, not
  the old 8192 default.
- Pacman retrieval (`episodic.py:686`) is now token-aware: `retrieve_context_chunks(
  ..., max_context_tokens=...)` caps returned chunks to fit the model window
  (`agent_kernel.py:1718` passes `int(resolve_context_window() × 0.6)`).

These are necessary but **insufficient** — they fix *capacity*, not the *hand-holding*
control flow.

---

## 3. Intended design (from the docs)

### 3.1 `DER_LOOP_MYCELIUM.md` says
- DER = Director → Explorer → Reviewer. The Reviewer filters, never blocks.
- Mycelium gives the loop *spatial context*: where it is, what worked, failure
  patterns, what to prioritize. PiNs give explicit human knowledge.
- "Without a mature Mycelium graph, the Reviewer has no signal and falls back to PASS."
- Context Package (`§4`) carries `tier2_predictions` (top-3 next-tool predictions from
  pheromone edges via `BehavioralPredictor`) and `tier3_failures` — these are meant to
  *inform* the agent, not *command* it.
- Pacman model (`§6`): Layer 1 (direct window) + Layer 2 (episodic) + Layer 3
  (Mycelium) = unbounded effective recall. The 32k window is the execution buffer;
  Mycelium + episodic is permanent store.

### 3.2 The handoff (`morphohdl-irisvoice-handoff.md`) adds
- **Caducean physics (u/ξ)** should drive *emergent* execution-tree shape: split-or-
  execute decided live by convergence state, not by a QUICK/AGENTIC/FULL mode chosen up
  front (`§5`, `§9.2`).
- **AIDE²-style outer loop** (`§9`): a slower process that nudges governing *constants*
  from recorded `caducean_trajectories`, judged on held-out metrics (natural exit rate,
  emergency-stop rate, token cost) — never on the same pheromone score being tuned.
  Explicitly "Level 1" auto-tuner, not recursive self-improvement.
- **Warning carried forward:** do not flatten the stateful, path-history behavior into
  a stateless "pick the tool for the agent" rule (`§5` Breaks). The hand-holding
  anti-pattern is exactly that flattening.

---

## 4. Issues catalog (every one traced to code or doc)

| # | Issue | Where | Type |
|---|-------|-------|------|
| I1 | Planner pre-assigns `tool` per step; agent never resolves tools itself | `agent_kernel.py:3658` | Hand-holding (root) |
| I2 | `_run_step_direct` has no tool bridge; bare inference only → stub on null tool | `agent_kernel.py:5789-5826` | Hand-holding (root) |
| I3 | Tool bridge gated behind `if item.tool` — capability exists but unreachable | `agent_kernel.py:5846` | Design gap |
| I4 | Weak/local model returns `tool:null` → `[step N completed]` → Pacman stores 0 | pin_c36415be4335, pin_00a08fa83935 | Symptom of I1/I2 |
| I5 | `BehavioralPredictor` top-3 tool predictions exist but are only *hints*, never a live registry the agent queries at execution | `DER_LOOP_MYCELIUM.md §4`, `interpreter.py` | Underused memory signal |
| I6 | Mode (QUICK/AGENTIC/FULL) fixed up front; execution-tree shape should emerge from u/ξ instead | handoff `§5` | Architecture gap |
| I7 | No outer self-tuning loop for governing constants despite trajectory data being recorded | handoff `§9` | Missing capability |
| I8 | Reviewer context (gradient_warnings, PiNs) informs but the *agent* still can't act on its own — it's told the tool | `DER_LOOP_MYCELIUM.md §3.4` vs I1 | Inconsistency |
| I9 | Per-role context windows not resolved (Brain=local 32k, Tool=cerebras 256k share one window) | `resolve_context_window` uses global `_model_provider` | Scaling gap |
| I10 | Pacman retrieval passes no `zones`/`chunk_types` from current DER task → generic top-6, not task-aligned | `agent_kernel.py:1718` | Memory-alignment gap |

---

## 5. Recommendations (layered, in priority order)

### Layer A — Kill the hand-holding (the pivot you asked for)
**A1. Tool bridge is a permanent capability, not an injected argument.**
Make `_run_step_direct` (and the Explorer generally) always hold the live tool
registry. A step is a *goal*, not a pre-bound tool call. At execution, the agent
resolves which tool serves the goal from:
  - the live tool registry (`_tool_bridge.list_tools()` or equivalent),
  - `BehavioralPredictor`'s top-3 pheromone-suggested tools (`tier2_predictions`),
  - Mycelium `gradient_warnings` (avoid known-failure tools).
The model *proposes*; the bridge *executes*. No "we chose the tool for you."

**A2. Stop pre-assigning `tool` in the plan.**
`_plan_task` should emit steps as goals + expected output, not `tool`+`params`. Tool
resolution moves to execution time (A1). This is the single change that converts
hand-holding → empowerment.

**A3. Never stub on null tool.**
If the agent cannot resolve a tool for a step, that is a Reviewer/VETO signal, not a
`[step N completed]` lie. Pacman should not store a fake completion.

### Layer B — Memory as the thinking substrate (already intended, finish it)
**B1.** Feed `tier2_predictions` + `tier3_failures` + PiN summaries into the Explorer's
execution prompt (not just the Reviewer's). The agent *reasons* with memory; it does
not receive commands.
**B2.** Pass `zones`/`chunk_types` from the current DER task into
`retrieve_context_chunks` (I10) so retrieval aligns to the task, not generic top-6.
**B3.** Per-role context windows (I9): resolve the window per role from the router's
bound instance, so Brain and Tool size their context independently.

### Layer C — Emergent shape + self-tuning (from the handoff, later phase)
**C1.** Let `u/ξ` from `caducean_trajectories` decide split-or-execute live (handoff
`§5`) — the execution tree *shape* emerges rather than being fixed by mode.
**C2.** AIDE²-style outer loop (handoff `§9.3`) that nudges named governing constants
from recorded trajectories, judged on held-out metrics, budget-capped, one variable at
a time. Explicitly "Level 1" auto-tuner.

---

## 6. What to preserve (do not break)
- Reviewer as membrane (never blocks, falls back to PASS) — `der_loop.py:5-6`.
- Mycelium maturity gating (Reviewer activates only when mature) — `DER_LOOP_MYCELIUM.md §10`.
- Pacman lifecycle (fragment → crystallize → decay) — `episodic.py`.
- The budget/context-window work done this session (§2.5) — keep, extend per-role (B3).
- Strict post-loop ordering (record_outcome → crystallize → clear → stats) —
  `DER_LOOP_MYCELIUM.md §11`.

---

## 7. Open decisions for you (before any spec)
1. **Scope of first cut:** Layer A only (kill hand-holding), or A+B, or A+B+C?
2. **Execution-time tool resolution:** pure LLM proposal (agent picks from registry
   text), or a small deterministic policy (registry + BehavioralPredictor top-3 +
   gradient_warnings filter) that the LLM ratifies?
3. **Flag-gating:** implement behind a feature flag so current DER still works during
   rollout? (Recommended — matches project "verify before replace" discipline.)
4. **Validation:** WS-driven task that exercises real tool use through the new layer,
   asserting Pacman stores >0 and no `[step N completed]` stub.

---

## 8. File reference (everything this pivot touches)
| File | Role in pivot |
|------|---------------|
| `backend/agent/agent_kernel.py` | `_plan_task` (3658 tool pre-assign), `_run_step_direct` (5789 no bridge), `_der_run_step_execution` (5846 gated bridge), `resolve_context_window` (892), budget (4757) |
| `backend/agent/der_loop.py` | Reviewer membrane (5-6), DirectorQueue, ExecutionMode |
| `backend/agent/der_constants.py` | `DER_TOKEN_BUDGETS` (68-77), mode enums |
| `backend/memory/episodic.py` | `retrieve_context_chunks` token-aware (686), Pacman lifecycle |
| `backend/memory/mycelium/interpreter.py` | `BehavioralPredictor` top-3 tool predictions |
| `backend/agent/caducean_trajectory.py` | `u/ξ` state for emergent split-or-execute (Layer C) |
| `backend/agent/trailing_director.py` | gap-filling Director |
| `docs/DER_LOOP_MYCELIUM.md` | intended design (source of truth) |
| `docs/handoffs/morphohdl-irisvoice-handoff.md` | Caducean + AIDE² research |

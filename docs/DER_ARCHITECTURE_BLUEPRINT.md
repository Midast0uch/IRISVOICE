# DER Coupled Action Cycle — Architecture Blueprint

> Companion to `DER_COUPLED_ACTION_CYCLE_SPEC.md`. This is the *as-built* blueprint
> of the DER (Deep Executive Reasoning) loop after all 5 phases landed. It shows
> every layer, what it does, and exactly which layers it interacts with.
>
> Branch: `feat/agent-multi-step-tool-execution`. Tests: 44 DER tests pass
> (Phase 0–4 + integration smoke + prior budget/role tests).

---

## 1. The one invariant (read this first)

```
        ONE recursive operator  =  fan-out / fold-back
        at FOUR scales, driven by the SAME Caducean physics (u/ξ),
        sharing ONE resource  W0 = resolve_context_window() / avg_step_cost
```

| Scale            | What it is                                  | Same physics |
|------------------|---------------------------------------------|--------------|
| step             | one tool action                             | u/ξ          |
| Sub-Loop         | a growth-width split child (is_subloop)     | u/ξ          |
| context window   | the W0 budget the loop lives inside         | u/ξ          |
| outer loop       | AIDE² tuning of U_SPLIT/width/strictness    | u/ξ          |

There is **no separate recovery-graft path**, **no mode-driven fan-out**, **no
web-regex override**. All of those collapsed into the one operator.

---

## 2. Blueprint diagram (layers + interactions)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         OUTER LOOP  (slow timescale / AIDE²)                     │
│   backend/agent/outer_loop.py :: OuterTuner                                     │
│   trigger: compaction signal (record_session_exit)  — NOT MCM 70% cadence       │
│                                                                                 │
│   reads:  caducean_session_exits ──► learns U_SPLIT / MAX_WIDTH / VERIFY_STRICT  │
│   writes: der_params.json  (applied only if held-out natural_exit_rate improves) │
└───────────▲───────────────────────────────────────────┬───────────────────────┘
            │ session exit signal                         │ learns-from
            │                                             ▼
┌───────────┴───────────────────────────────────────────────────────────────────┐
│                      SESSION-EXIT LEDGER  (D4.0)                                 │
│   caducean_trajectory.py :: record_session_exit / get_session_exits             │
│   hooked from ConversationMemory.archive_on_session_end                         │
└───────────▲───────────────────────────────────────────────────────────────────┘
            │ written on
            ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    EXECUTION LOOP  (fast timescale / the cycle)                 │
│                                                                                 │
│  ┌──────────────┐    goals only    ┌──────────────────────────────────────┐    │
│  │  PLANNER     │ ───────────────► │  STEP (QueueItem, tool=None)          │    │
│  │ _plan_task   │                   └───────────┬──────────────────────────┘    │
│  │ (agent_kernel│                               │ needs a tool                   │
│  │  .py)        │                               ▼                                │
│  └──────────────┘                   ┌──────────────────────────────────────┐    │
│                                     │  EVIDENCE (memory-conditioned block)  │    │
│                                     │  evidence.py :: assemble_evidence     │    │
│                                     │  PREDICTED NEXT / PROVEN PATH /       │    │
│                                     │  AVOID / CONTRACTS / (u,ξ)            │    │
│                                     └───────────┬──────────────────────────┘    │
│                                                 │ conditions prompt              │
│                                                 ▼                                │
│                                     ┌──────────────────────────────────────┐    │
│                                     │  RESOLVER  (single authority / F1,F6) │    │
│                                     │  explorer.py :: propose               │    │
│                                     │  LLM → validate_tool_call → tool      │    │
│                                     │  fallback: pheromone top-1 / crawler  │    │
│                                     └───────────┬──────────────────────────┘    │
│                                                 │ picks tool                     │
│                                                 ▼                                │
│                                     ┌──────────────────────────────────────┐    │
│                                     │  TOOL BRIDGE  (execute)               │    │
│                                     │  tool_bridge.py :: execute_tool (async)│   │
│                                     └───────────┬──────────────────────────┘    │
│                                                 │ result                         │
│                                                 ▼                                │
│                                     ┌──────────────────────────────────────┐    │
│                                     │  VERIFIER  (G1, D2.3)                 │    │
│                                     │  _verify_step_result (deterministic)  │    │
│                                     │  verify_rubric.py (mid-|u| LLM rubric) │   │
│                                     │  → VERIFIED / UNVERIFIED / FAILED     │    │
│                                     └───────────┬──────────────────────────┘    │
│                                                 │                               │
│                          ┌──────────────────────┼───────────────────────┐       │
│                          │ FAILED               │ VERIFIED               │ UNVERIFIED│
│                          ▼                      ▼                        ▼       │
│                  ┌──────────────┐    ┌──────────────────────┐   (policy)        │
│                  │ SPLIT OPER.  │    │ COMMIT LEDGER (G5)    │                  │
│                  │ _split_step  │    │ record_commit         │                  │
│                  │ _growth_width│    │ (only on VERIFIED)    │                  │
│                  │ (u/ξ → width)│    └──────────┬───────────┘                  │
│                  └──────┬───────┘                                              │
│                         │ Sub-Loop children (is_subloop) collapse to parent    │
│                         │ as ONE COMPRESS (Lyapunov Φ strictly decreases)      │
│                         └──────────────► back into STEP queue                  │
└──────────────────────────────────────────────────────────────────────────────┘
            │                                 │                                 │
            ▼                                 ▼                                 ▼
┌────────────────────┐   ┌────────────────────────────┐   ┌─────────────────────────┐
│  MEMORY SUBSTRATE  │   │  CADUCEAN ENGINE (physics)  │   │  MCM COORDINATE GRAPH   │
│  (thinking layer)  │   │  FFI u/ξ signal             │   │  navigation / pruning   │
│  Mycelium          │◄──┤  iris_ffi                   │   │  (separate concern)     │
│  episodic store    │   │  ffi_caducean_get_state     │   │                         │
│  trajectory recorder│  │  ffi_caducean_update        │   │                         │
│  (der_commits,     │   └────────────────────────────┘   └─────────────────────────┘
│   der_fan_traces,  │            ▲ reads u/ξ                   ▲ reads topology
│   caducean_        │            │                             │
│   trajectories,    │            └─────────────────────────────┘
│   session_exits)   │
└────────────────────┘
```

---

## 3. Layer reference (what each does + who it talks to)

| # | Layer | Module :: symbol | Talks to | Phase |
|---|-------|------------------|----------|-------|
| L1 | Planner | `agent_kernel._plan_task` | emits `QueueItem(tool=None)` → Step | 1 (D1.3) |
| L2 | Evidence | `evidence.assemble_evidence` | Mycelium (`_store._conn`, `_registry`), episodic, FFI `u/ξ` → Resolver prompt | 1 (D1.1) |
| L3 | Resolver | `explorer.propose` | `tool_registry.validate_tool_call`, `BehavioralPredictor` (pheromone), `evidence` | 1 (D1.2/F1,F6) |
| L4 | Tool Bridge | `tool_bridge.execute_tool` (async) | external tools / MCP | — |
| L5 | Verifier (det) | `agent_kernel._verify_step_result` | `_verified_fraction` (assertion match) | 0 (D0.1) |
| L6 | Verifier (LLM) | `verify_rubric.call` | `infer` (mid-`\|u\|` band only) | 3 (D3.1) |
| L7 | Split operator | `agent_kernel._split_step` / `_growth_width` | FFI `u/ξ`, `der_constants` (U_SPLIT, MAX_DEPTH, DER_MAX_GRAFTS), `work_units` | 2 (D2.1/F2,F3) |
| L8 | Commit ledger | `caducean_trajectory.record_commit` | called only when VERIFIED (G5) | 3 (D3.3) |
| L9 | Session-exit ledger | `caducean_trajectory.record_session_exit` | `ConversationMemory.archive_on_session_end` | 4 (D4.0) |
| L10 | Outer loop | `outer_loop.OuterTuner` / `run_outer_loop` | reads L9 + L8 + `der_fan_traces`; writes `der_params.json` | 4 (D4.2) |
| M | Memory substrate | Mycelium + episodic + trajectory recorder | L2, L3, L7, L8, L9 | — |
| P | Caducean engine | `iris_ffi` (`u/ξ`) | L2, L7 (read signal) | — |
| G | MCM graph | coordinate DB | navigation/pruning (separate concern) | — |

---

## 4. Interaction matrix (who calls whom)

```
                 L1  L2  L3  L4  L5  L6  L7  L8  L9  L10  M   P   G
L1 Planner        —   ·   ·   ·   ·   ·   ·   ·   ·   ·    ·   ·   ·
L2 Evidence      ·   —   ▲   ·   ·   ·   ·   ·   ·   ·    ▼   ▼   ·
L3 Resolver      ·   ▲   —   ▼   ·   ·   ·   ·   ·   ·    ▼   ·   ·
L4 ToolBridge    ·   ·   ▲   —   ▼   ·   ·   ·   ·   ·    ·   ·   ·
L5 Verif(det)    ·   ·   ·   ▲   —   ·   ·   ·   ·   ·    ·   ·   ·
L6 Verif(LLM)    ·   ·   ·   ·   ▲   —   ·   ·   ·   ·    ·   ·   ·
L7 Split         ·   ·   ·   ·   ▲   ·   —   ·   ·   ·    ·   ▼   ·
L8 Commit        ·   ·   ·   ·   ▲   ·   ·   —   ·   ·    ▼   ·   ·
L9 SessionExit   ·   ·   ·   ·   ·   ·   ·   ·   —   ▲    ▼   ·   ·
L10 OuterLoop    ·   ·   ·   ·   ·   ·   ·   ▲   ▲   —    ▼   ·   ·
M  Memory        ▲   ▲   ▲   ·   ·   ·   ▲   ▲   ▲   ▲    —   ·   ·
P  Caducean      ▲   ▲   ·   ·   ·   ·   ▲   ·   ·   ·    ·   —   ·
G  MCM graph     ·   ·   ·   ·   ·   ·   ·   ·   ·   ·    ·   ·   —
```

Legend: `▲` = reads-from / depends-on, `▼` = writes-to / feeds, `·` = no direct link.

Key takeaways from the matrix:
- **L3 Resolver** is the only layer that picks a tool (F6: single authority). It reads L2 (evidence) and M (memory) and writes L4 (tool bridge).
- **L7 Split** is the only layer that changes *shape*; it reads P (Caducean `u/ξ`) and M, and feeds back into the Step queue.
- **L8/L9 ledgers** are write-only sinks (honest audit) that only L10 (outer loop) reads.
- **P (Caducean)** is read by L2 and L7 — the physics signal is the single source of shape, never mode.
- **G (MCM graph)** is a separate concern (navigation/pruning); it does not participate in the action cycle's control flow.

---

## 5. Enforcement tiers (where they live)

| Tier | Kind | Enforced by | Example |
|------|------|-------------|---------|
| 1 | Binary bookkeeping | `agent_kernel` / `caducean_trajectory` | stub→FAILED (G1), honest veto (G2), commit-only-on-VERIFIED (G5) |
| 2 | Physics-based (hard rule) | `_split_step` / `_growth_width` / `_verify_step_result` | `|u|`-band verify, `work_units` termination, MAX_DEPTH/DER_MAX_GRAFTS caps |
| 3 | Subjective/empowered | `verify_rubric.call` / `explorer.propose` | LLM rubric verdict, tool proposal |

Anti-patterns (explicitly avoided): standing context injection, nudges, fan_traces-in-prompt, treating Tier-2 as binary.

---

## 6. Data flow (one full cycle)

```
objective
  │
  ▼
_plan_task ──► QueueItem(tool=None, expected_output set)        [L1]
  │
  ▼  for each step:
  _der_run_step_execution
     ├─ assemble_evidence(goal, myc, u/ξ)  ───────────────────► [L2] reads M, P
     ├─ propose(evidence, live_tools)      ───────────────────► [L3] validate → tool
     ├─ tool_bridge.execute_tool(tool)     ───────────────────► [L4] result
     └─ _der_finalize_step
           ├─ _verify_step_result(result)  ───────────────────► [L5] VERIFIED/FAILED/UNVERIFIED
           │     (mid-|u| ⇒ verify_rubric) ───────────────────► [L6]
           ├─ FAILED ⇒ _split_step(u/ξ)    ───────────────────► [L7] Sub-Loop children → queue
           └─ VERIFIED ⇒ record_commit     ───────────────────► [L8] ledger row
  │
  ▼  session ends:
archive_on_session_end ──► record_session_exit ──────────────► [L9] ledger row
  │
  ▼  compaction signal:
run_outer_loop ──► OuterTuner.run_once ──────────────────────► [L10] reads L8+L9, learns params
```

---

## 7. Files touched by the rewrite (as-built)

| File | Role |
|------|------|
| `backend/agent/agent_kernel.py` | Planner (L1), verifier (L5), split operator (L7), finalize/commit wiring (L8), resolver call (L3), None-safe myc lookup |
| `backend/agent/evidence.py` | Evidence block assembler (L2) |
| `backend/agent/explorer.py` | Single runtime tool resolver (L3) |
| `backend/agent/verify_rubric.py` | LLM rubric verifier (L6) |
| `backend/agent/outer_loop.py` | AIDE² outer loop (L10) |
| `backend/agent/der_constants.py` | U_SPLIT, U_CONVERGED, MAX_DEPTH, DER_MAX_GRAFTS, AVG_STEP_COST, derive_work_units_0, ExecutionMode (display-only) |
| `backend/agent/caducean_trajectory.py` | record_commit (L8), record_session_exit (L9), domain column, der_commits/der_fan_traces/caducean_session_exits tables |
| `backend/agent/memory.py` | archive_on_session_end → record_session_exit hook (D4.0) |
| `backend/agent/der_loop.py` | QueueItem.is_subloop (Sub-Loop marker) |
| `backend/tests/test_der_*.py` | Phase 0–4 + integration smoke (44 tests) |

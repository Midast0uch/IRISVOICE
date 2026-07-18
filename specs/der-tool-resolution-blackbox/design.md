# Design: DER Tool-Resolution Black Box

## Context

DER executes multi-step plans, but tool decision + dispatch is scattered and fails
*soft*. The investigation (traced against `agent_kernel.py`, `explorer.py`,
`tool_bridge.py`, `inference/router.py`) found:

- `agent_kernel.infer()` is documented **"Never raises — returns empty-text object
  on any backend failure"** (agent_kernel.py:576). This is the silent-failure
  enabler: a dead model yields `""`, `propose` can't parse it, and silently returns
  "reason instead".
- `explorer.propose` has three silent fallbacks (web-intent → `crawler_query`,
  pheromone top-1, final "reason") — debug noise the user wants removed
  (explorer.py:179-214).
- `_plan_task` returns a silent single-step fallback plan on any planner failure
  (agent_kernel.py:3834-3844) — violates the standing "no silent self-do" rule.
- RC1 pre-execution validation only runs `if item.tool` (agent_kernel.py:5296), so a
  resolver crash (which leaves `tool=None`) bypasses it and falls to
  `_run_step_direct` (agent_kernel.py:6379).
- No model-health pre-flight: DER enters the loop with a dead model and burns ~47s
  across planner timeout + per-step resolver timeout + 2 retries + graft split-step
  timeout before any escalation.

The fix consolidates resolution + dispatch into one **`ToolDecisionBox`** that is
router-agnostic, fail-loud, and DER-recovery-friendly. It removes silent fallbacks,
adds a pre-flight, and makes `_plan_task` error instead of self-do.

## Architecture Overview

```
                         ┌─────────────────────────────────────────┐
                         │            DER loop                       │
                         │  (_execute_plan_der, _der_handle_step_*)  │
                         └───────────────┬───────────────┬──────────┘
                                         │               │
                            PRE-FLIGHT   │               │  FAIL
                                         ▼               │
                         ┌───────────────────────┐       │
                         │  InferenceRouter.resolve│       │
                         │  ("reasoning" role)    │       │
                         └───────────┬───────────┘       │
                          usable?     │ no               │
                          ───────     ▼                   │
                         yes │   RETURN DER_UNAVAILABLE  │
                              │   (ERROR, no loop)        │
                              ▼                           │
                   ┌──────────────────────────┐          │
                   │     ToolDecisionBox       │◄─────────┘ (FAIL → _der_handle_step_failure)
                   │  resolve() → Decision     │
                   │  dispatch() → DispatchResult│
                   └──────────┬───────────┬────┘
                              │           │
              resolve         │           │ dispatch
              (role=reasoning)│           │ (tool_bridge.execute_tool)
                              ▼           ▼
                   ┌────────────────┐  ┌──────────────────────────┐
                   │ InferenceRouter│  │ AgentToolBridge           │
                   │ generate(role) │  │ (capability/perm gates)   │
                   └────────────────┘  └──────────────────────────┘
                              │
                    ProviderInstance → Transport
                    (API / LOCAL_OPENAI / OLLAMA / INPROCESS)
```

The box is the ONLY component the DER loop calls for step execution. It depends on
two existing, correct subsystems: `InferenceRouter` (role→provider→transport) and
`AgentToolBridge` (capability/permission gates + actual tool run). It never touches
provider URLs or the swarm/model snapshots directly.

## Sequence / Data Flow

```mermaid
sequenceDiagram
    participant DER as DER loop
    participant Box as ToolDecisionBox
    participant Rtr as InferenceRouter
    participant Mem as Memory (pheromone/mycelium)
    participant TB as AgentToolBridge
    participant Rec as Recovery (_der_handle_step_failure)

    DER->>Rtr: resolve("reasoning")
    alt no usable provider
        Rtr-->>DER: DER_UNAVAILABLE (ERROR, no loop)
    else usable
        DER->>Box: resolve(step, evidence)
        Box->>Rtr: generate("reasoning", propose_prompt)
        alt model returns decision (TOOL | REASON)
            Rtr-->>Box: decision
            Box-->>DER: Decision(kind, source=llm)
        else model dead / unparseable / invalid tool
            Box->>Mem: consult pheromone top-1 / mycelium
            alt memory yields a registered tool
                Mem-->>Box: suggested tool
                Box-->>DER: Decision(TOOL, source=memory)  %% explicit, logged
            else no memory suggestion
                Box-->>DER: Decision(FAIL, error)
                DER->>Rec: handle_step_failure (graft / escalate REQ-10)
            end
        end
        opt Decision.kind == TOOL
            DER->>Box: dispatch(decision)
            Box->>TB: execute_tool(tool, params)
            TB-->>Box: {success, result}
            Box-->>DER: DispatchResult
            opt success == False
                DER->>Rec: handle_step_failure (retry / graft)
            end
        end
        opt Decision.kind == REASON
            DER->>Box: dispatch(REASON)  %% runs _run_step_direct
            Box-->>DER: DispatchResult (reasoning text)
        end
    end
```

## Data Models

```python
# backend/agent/tool_decision.py

class DecisionKind(Enum):
    TOOL = "tool"        # a tool was chosen (params validated)
    REASON = "reason"    # model decided no tool needed (valid)
    FAIL = "fail"        # resolution could not complete (model dead / invalid)

@dataclass
class Decision:
    kind: DecisionKind
    tool: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    source: str = ""          # "llm" | "memory" | "fail"
    error: Optional[str] = None   # populated when kind == FAIL

@dataclass
class DispatchResult:
    success: bool
    result: Any = None
    error: Optional[str] = None
    duration_ms: int = 0

class ToolDecisionBox:
    def __init__(self, router, tool_bridge, get_available_tools, validate_tool_call): ...
    def resolve(self, step, evidence, session_id, conversation_id) -> Decision: ...
    def dispatch(self, decision, session_id, conversation_id) -> DispatchResult: ...
```

`ToolDecisionBox` is constructed once per kernel (or per call) with the router and
bridge injected — never imports snapshots. `resolve` returns a `Decision`; `dispatch`
returns a `DispatchResult`. Both are plain dataclasses, easy to assert in contract
tests.

## Key Decisions

1. **Remove `infer`'s "never raises" only for the resolver path.** Rather than change
   `infer` globally (it is also used by the Reviewer and other DER components that
   legitimately tolerate empty output), the box does a **pre-call health probe** on
   `router.resolve("reasoning")` and treats an `uninitialized`/unreachable provider as
   `FAIL`. This isolates the fail-loud behavior to tool resolution.
   *Alternative rejected:* making `infer` raise everywhere — would break the Reviewer's
   "membrane, not gate" tolerance and ripple through unrelated callers.

2. **`FAIL` is terminal only when memory also has no suggestion; recovery is DER's
   job.** The box does NOT retry resolution or silently substitute "reason". Memory
   (pheromone/mycelium) is a first-class, explicit, logged resolver source
   (`source=memory`) — KEPT as a feature, consolidated into the box, not removed.
   Only when the model is dead AND memory yields no registered tool does the box
   return `FAIL`, which routes to the already-robust `_der_handle_step_failure`
   (graft + REQ-10 escalation). *Alternative rejected:* internal retry/fallback in
   the box — exactly the silent-masking debug noise the user wants gone.

3. **`REASON` vs `FAIL` is the core distinction.** `REASON` = model *decided* no tool
   (valid, runs `_run_step_direct`). `FAIL` = model *could not be asked* (dead /
   unparseable / invalid tool). Only `FAIL` triggers recovery. This removes the
   ambiguity that let resolver crashes masquerade as reasoning steps.

4. **Router-agnostic by construction.** The box calls `router.generate("reasoning",
   ...)` and `tool_bridge.execute_tool(...)`. It never reads `_model_config_snapshot`
   or `_swarm_config_snapshot`. The swarm refactor only needs to rebind roles on the
   router (as it already does at agent_kernel.py:8040-8042); the box is untouched.

5. **Pre-flight at DER entry, not per-step.** Checking provider health once at
   `_execute_plan_der` entry (REQ-1) avoids N probe calls per step and still kills the
   death-spiral. Per-step `FAIL` still handles mid-run provider loss (e.g. swarm node
   drop).

6. **The black box is the "Control Plane as a Tool" pattern.** Exposing one tool
   interface that encapsulates modular routing logic behind it (Kandasamy,
   arXiv:2505.06817) is exactly this design. The memory pre-filter (REQ-4 AC6) is the
   *retrieve-then-decide* pattern from semantic-tool-discovery research
   (RAG-MCP arXiv:2505.03275; Semantic Tool Discovery arXiv:2603.20313): retrieve a
   narrowed tool subset via memory, then let the model decide among it. `SourceRegistry`
   is the web-search instance; the `ToolCallTree` collapse (REQ-13) generalizes it.

## Error Handling

| Fault | Current behavior | New behavior (EARS) |
|---|---|---|
| No usable `reasoning` provider | enters loop, ~47s timeouts | pre-flight → `DER_UNAVAILABLE` ERROR <2s, no card (REQ-1) |
| Planner non-JSON / raises | silent 1-step self-do plan | plan error → ERROR response, no loop (REQ-2) |
| Resolver: model dead | `propose` → "reason" silently | `Decision(FAIL)` → recovery/escalate (REQ-4, REQ-6) |
| Resolver: invalid tool name | fallback to pheromone/reason | `Decision(FAIL)` (REQ-4 AC3) |
| `TOOL` with bad params | RC1 skipped (tool was None) | RC1 runs on every `TOOL` before dispatch (REQ-7 AC3) |
| Dispatch error | loose `error` string, no class | structured envelope `error_type` + `suggested_action` (REQ-10); transient→backoff, permanent→re-plan |
| Write-tool retry after timeout | can double-execute side effect | idempotency key `hash(turn+tool+args)`; retry is a no-op (REQ-11) |
| One tool keeps failing | retries until global cycle limit | per-tool budget → "do not call again"; dedup flags loop (REQ-12) |
| Loop ends | flat commit ledger only | `ToolCallTree` emitted (all calls across splits) → observability + pre-filter (REQ-13) |
| Non-critical step FAIL | recorded to memory (kept) | unchanged (REQ-6 edge) |

The existing `retry_with_backoff_sync` (transport errors only) and `_der_handle_step_
failure` (graft + REQ-10) are **preserved** — the box feeds them, it does not replace
them.

## ToolCallTree collapse & memory pre-filter

The DER loop already records every executed action in a flat commit ledger
(`caducean_trajectory.record_commit`, step_id + u/xi + verified_label) and collapses
Sub-Loops to the parent as one COMPRESS (`agent_kernel.py:7102`). REQ-13 upgrades this
to a **structured `ToolCallTree`** emitted on collapse:

```
ToolCallTree(conversation_id, root_step_id)
  nodes: { step_id, tool, args_hash, result/error_class, source, split_depth }
  edges: parent_step_id -> child_step_id   # from _split_step Sub-Loops
```

This single artifact serves two purposes:
1. **Observability** (REQ-9 AC5): the full tool-call structure of a run is
   reconstructable without raw-log grep.
2. **Memory pre-filter input** (REQ-4 AC6): the tree replenishes the retrieval memory
   that narrows the candidate toolset *before* the next LLM call. `SourceRegistry`
   (`crawler/source_registry.py:36`) is the web-search instance of this memory; the
   collapse tree generalizes it to all tools. This is the two-phase
   *retrieve-then-decide* pattern from semantic-tool-discovery research: memory
   retrieves the relevant subset, the model decides among it.

The black box is the **single interface** the DER loop calls; internally it consults
memory (pre-filter) → router (resolution) → bridge (dispatch) → ledger (tree). This is
an instance of the *"Control Plane as a Tool"* pattern (Kandasamy, arXiv:2505.06817):
one tool interface encapsulating modular routing logic behind it.

## Testing Strategy

Organized per the project CDD standard (`tests/unit`, `tests/contract`,
`tests/behavioral`, `scripts/validate_der_*.py` standing harness).

```
tests/unit/tool_decision_test.py
  - resolve returns TOOL/REASON/FAIL on faked infer outputs (no I/O)
  - FAIL when infer returns "" / raises / invalid tool
  - REASON only when model explicitly decided no tool
  - RC1 validation runs on every TOOL decision

tests/contract/test_tool_decision_contract.py
  - Decision / DispatchResult shapes are pinned (fields, enum values)
  - DER_UNAVAILABLE event shape pinned (thread-scoped, reason field)
  - TOOL_CALL event carries kind (tool|reason) — frontend contract

tests/behavioral/test_tool_decision_behavioral.py
  - Full DER task with a DEAD reasoning provider → asserts:
      * no task card rendered (no phantom card)
      * DER_UNAVAILABLE emitted, ERROR returned <2s
      * zero tool dispatches occurred
  - Full DER task with valid provider + web goal → asserts:
      * TOOL decision → crawler_query dispatched → result shown
      * spoken ⊆ visible (existing behavioral property)
  - Full DER task with invalid tool name → asserts FAIL → graft/escalate,
    not silent reason

scripts/validate_der_tool_resolution.py  (STANDING CDD HARNESS)
  - Replays recorded trajectories (dead-model, web-search, invalid-tool) through the
    FULL stack; asserts contracts + behaviors EVERY run. Gap found → decomposed into
    the contract test that would have caught it.
```

**Physics-aware:** inject Caducean u/ξ states and assert system-level outcome — e.g.
a `FAIL` during an oscillating band still triggers graft (split), not silence.

**Standing harness integration:** extend `backend/tests/_sort_log.py` buckets with
`tool_decision.log`, `tool_dispatch.log`, `tool_decision_fail.log` so live runs are
correlatable (REQ-5 / REQ-9).

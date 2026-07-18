# Requirements: DER Tool-Resolution Black Box

## Decisions Locked

These are user-resolved directives. Future sessions MUST NOT re-litigate them.

1. **No silent failure masking; memory-driven resolution is a kept feature.**
   The memory system's tool suggestions (pheromone top-1, mycelium/web-intent) are
   a FEATURE, not debug noise, and are KEPT as an explicit, logged resolver source
   (`source="memory"`) *inside* the black box (consolidated, not scattered in
   `explorer.propose`). What is REMOVED is only the *silent failure masking*: when
   the model is unavailable, `propose` currently substitutes "reason instead" with
   no signal. That masking is gone. When the resolver cannot reach a decision
   because the model is unavailable, it consults memory; if memory yields a
   registered tool it returns `TOOL(source=memory)`; only if memory also has no
   suggestion does it FAIL LOUDLY and let DER's split-recovery + user escalation
   (REQ-10) handle it. A *legitimate* "this step needs no tool, reason directly"
   decision made BY the model is a valid `REASON` outcome, not a fallback.
2. **Tool decision + dispatch become one encapsulated black box** with DER-grade
   logging and DER-style split failure. Callers (the DER loop) interact only with
   its interface; they never reach into `propose` / `tool_bridge` / `infer`
   directly for step execution.
3. **The black box is router-agnostic.** All provider selection flows through
   `InferenceRouter` role bindings (`reasoning` / `tool_execution`). The black box
   never reads `_model_config_snapshot` or `_swarm_config_snapshot` directly, so the
   upcoming swarm refactor does not touch it.
4. **Multi-provider + local-model mix is preserved.** Resolution uses the
   `reasoning` role; dispatch may use `tool_execution` or no LLM (e.g. web search
   hits the exa API, not the LLM). The black box passes roles, never hardcodes a
   provider or model.
5. **Fail fast on a dead/uninitialized model.** DER must not enter the expensive
   loop when no usable `reasoning` provider exists. This kills the ~47s
   timeout death-spiral observed with `provider=uninitialized`.
6. **Empty/invalid plan → ERROR, never silent self-do.** Matches the standing rule:
   "agent must NOT operate outside DER — empty-step plan → return ERROR, no
   fallback/silent self-do."

## Introduction

DER plans and executes multi-step tasks, but its tool-decision path is scattered
across `agent_kernel._plan_task`, `explorer.propose`, `agent_kernel.infer`, and
`agent_kernel._der_run_step_execution`, and fails *soft*: a dead model produces an
empty plan, a silent "reason" decision, and a stub `[step N completed]` result —
never an error. This spec consolidates tool decision + dispatch into one
encapsulated, well-logged, fail-loud black box, adds a model-health pre-flight, and
removes silent failure masking (keeping memory-driven pheromone/mycelium resolution
as an explicit, logged `source=memory`), while staying router-agnostic for the swarm
refactor.

### Success criteria
- A request with no usable `reasoning` provider returns a structured ERROR in
  <2s, emits no fake task card, and never enters the DER loop.
- A planner failure returns ERROR (not a single-step self-do plan).
- Tool resolution returns exactly one of `TOOL` / `REASON` / `FAIL`; `FAIL` is
  never silently converted to `REASON`.
- Every decision, dispatch, result, and failure is logged thread-scoped with a
  timestamp and a stable event type.
- The swarm refactor can change provider wiring without modifying the black box.

## Requirements

### REQ-1: Model-health pre-flight at DER entry
**User Story:** As the user, I want IRIS to tell me immediately when its model is
unavailable, so that I am not left waiting ~47s for a silent failure.

**Verified:** agent_kernel.py:4942 (`_execute_plan_der` entry), agent_kernel.py:5128
(loop guard), inference/router.py:255-270 (`resolve` + default-role fallback),
agent_kernel.py:7879-7928 (`_model_config_snapshot` / uninitialized sentinel).

**Acceptance Criteria:**
- AC1: WHEN DER is about to execute a plan THEN THE SYSTEM SHALL resolve the
  `reasoning` role via `InferenceRouter.resolve` and confirm the bound provider is
  not the `uninitialized` sentinel and is reachable.
- AC2: IF no usable `reasoning` provider is resolved THEN THE SYSTEM SHALL return a
  structured error (no task card, no loop entry) within 2 seconds.
- AC3: THE SYSTEM SHALL emit a single `DER_UNAVAILABLE` event (thread-scoped)
  carrying the reason, so the frontend can surface it instead of a phantom card.

**Edge Cases:**
- Provider bound but endpoint dead (e.g. LM Studio at localhost:1234) → treat as
  unavailable (AC2), not as a usable provider.
- `resolve` raises (no binding, no default) → unavailable (AC2).
- Non-WS (REST) path → return the error synchronously, no event needed.

### REQ-2: Planner failure returns ERROR, not a silent self-do plan
**User Story:** As the user, I want an empty/invalid plan to be reported as an error,
so that IRIS does not silently "do it itself" with a single text step.

**Verified:** agent_kernel.py:3605 (`_plan_task`), agent_kernel.py:3742
(router planning path), agent_kernel.py:3834-3844 (silent single-step fallback),
agent_kernel.py:3814-3818 (planner `tool` field stripped — decision deferred to
runtime, expected).

**Acceptance Criteria:**
- AC1: IF the planner model returns non-JSON or raises THEN THE SYSTEM SHALL signal
  a plan error (structured) rather than returning a one-step plan whose `description`
  is the raw user text.
- AC2: WHEN a plan error is signalled THEN THE SYSTEM SHALL return an ERROR response
  to the user (no DER loop, no task card) instead of executing the fallback plan.
- AC3: THE SYSTEM SHALL log the planner failure with the raw model response (first
  600 chars) and the parsed keys attempted, thread-scoped.

**Edge Cases:**
- Router path fails AND LM Studio/Ollama fallback also fails → plan error (AC1).
- Planner returns valid JSON but zero steps → plan error (AC1) — empty plan is not
  executable.
- Planner returns valid JSON with steps but all steps are voice-only → existing
  FIX-B behavior (skip card, direct path) remains; this is NOT a plan error.

### REQ-3: Encapsulated tool-decision black box
**User Story:** As the maintainer, I want tool decision + dispatch in one module with
a single interface, so that the DER loop and the swarm refactor both call one thing.

**Verified:** agent_kernel.py:6286-6386 (`_der_run_step_execution` — current inline
resolver + dispatch), explorer.py:122-214 (`propose` — current resolver),
tool_bridge.py:889 (`execute_tool` — current dispatch), inference/router.py:311-339
(`generate` — role→provider→transport).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide a `ToolDecisionBox` module exposing
  `resolve(step, evidence, session_id, conversation_id) -> Decision` and
  `dispatch(decision, session_id, conversation_id) -> DispatchResult`.
- AC2: THE SYSTEM SHALL route resolution through `InferenceRouter` using the
  `reasoning` role and route dispatch through `tool_bridge.execute_tool`, so no
  provider/model is hardcoded in the box.
- AC3: WHILE the DER loop executes a step THEN THE SYSTEM SHALL call only
  `ToolDecisionBox.resolve` then `ToolDecisionBox.dispatch`; it shall not call
  `explorer.propose`, `agent_kernel.infer`, or `tool_bridge.execute_tool` directly
  for that step.

**Edge Cases:**
- `resolve` called with a step that already has a `tool` assigned (planner/registry
  pre-set) → box validates it (REQ-4) instead of re-resolving.
- Box constructed without a router → fail construction with a clear error.

### REQ-4: Decision types — TOOL / REASON / FAIL, with explicit memory-sourced resolution
**User Story:** As the debugger, I want resolution outcomes to be explicit and
source-tagged, so a model outage is never silently masked as "reason", while the
memory system's tool suggestions remain a first-class resolution path.

**Verified:** explorer.py:157-214 (current: invalid→fallback web-intent→fallback
pheromone→fallback reasoning — memory paths KEPT as explicit `source=memory`, silent
masking REMOVED), agent_kernel.py:6322-6326 (resolver exception swallowed,
`item.tool` stays None), agent_kernel.py:6379 (`_run_step_direct` when `tool is
None`), agent_kernel.py:8015-8059 (swarm / mycelium hydration context).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL return exactly one `Decision.kind` ∈ {`TOOL`, `REASON`,
  `FAIL`}, with `Decision.source` ∈ {`llm`, `memory`, `fail`}.
- AC2: WHEN the model returns a valid decision with `kind=reasoning`/`done` or
  `tool=null` THEN THE SYSTEM SHALL return `REASON` (valid, no tool needed,
  `source=llm`).
- AC3: WHEN the model is unavailable or returns unparseable output THEN THE SYSTEM
  SHALL consult memory (pheromone top-1 / mycelium suggestion); IF memory yields a
  registered tool THEN THE SYSTEM SHALL return `TOOL` with `source=memory`
  (explicit, logged — not a silent fallback).
- AC4: IF the model is unavailable AND memory yields no registered tool (or the
  suggested tool fails registry validation) THEN THE SYSTEM SHALL return `FAIL`
  (never `REASON`).
- AC5: THE SYSTEM SHALL NOT silently substitute "reason" when resolution fails; a
  crashed resolver is `FAIL` (AC4), never `REASON`.
- AC6: THE SYSTEM SHALL use memory as a **pre-filter**, not only a fallback: before
  the LLM call it shall retrieve the candidate tool subset via memory (pheromone /
  mycelium / `SourceRegistry` for web) and present only the narrowed set to the model
  (two-phase retrieve-then-decide), improving selection accuracy and cutting context
  bloat. The `ToolCallTree` collapse (REQ-13) replenishes this memory.

**Edge Cases:**
- Model returns a tool name not in the registry → `FAIL` (AC4), not "reason".
- Model returns valid `TOOL` but `params` fail schema validation → `FAIL` (AC4).
- Memory suggests a tool → `TOOL(source=memory)`, explicitly logged (AC3), not a
  hidden fallback.
- `SourceRegistry` (crawler/source_registry.py:36) is the web-search instance of this
  pre-filter; REQ-13 generalizes it to all tools via the collapse tree.
- `REASON` is only emitted when the model explicitly decided no tool is needed
  (AC2); a crashed resolver is `FAIL` (AC4).

### REQ-5: Structured, thread-scoped logging
**User Story:** As the tuner, I want every decision/dispatch/result/failure logged
with a stable event type and thread scope, so that live-test correlation is possible
without grep archaeology.

**Verified:** agent_kernel.py:6318-6321 (current resolver log),
agent_kernel.py:6383-6385 (current explorer error log),
backend/tests/_sort_log.py (existing log sorter → `logs/by_type/*.log`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL emit a `TOOL_DECISION` log line (thread-scoped, timestamped)
  for every `resolve` with `kind`, `tool`, `rationale`, and `source`
  (`llm` | `memory` | `fail`).
- AC2: THE SYSTEM SHALL emit a `TOOL_DISPATCH` log line for every `dispatch` with
  `tool`, `params` (redacted), `success`, `duration_ms`, and `error` when present.
- AC3: THE SYSTEM SHALL emit a `TOOL_DECISION_FAIL` log line (not a generic warning)
  when resolution fails, carrying the underlying error string.

**Edge Cases:**
- Missing `conversation_id` → fall back to `session_id` scope, never drop the line.
- High volume → logs are off the critical path (best-effort, never block dispatch).

### REQ-6: Failure routes to DER split-recovery, no internal retry/fallback
**User Story:** As the user, I want a failed tool decision to trigger DER's recovery
(graft → escalate), not a hidden retry or a fake success.

**Verified:** agent_kernel.py:5626-5753 (`_der_handle_step_failure`: mark failed,
abort descendants, graft via `_split_step`, REQ-10 escalate via `TASK_BLOCKED` +
`ask_user`), agent_kernel.py:5329-5358 (current retry_with_backoff — retained for
transport errors only).

**Acceptance Criteria:**
- AC1: WHEN `resolve` returns `FAIL` THEN THE SYSTEM SHALL treat the step as failed
  and invoke the existing `_der_handle_step_failure` path (graft for critical steps,
  escalate to user when graft budget exhausted).
- AC2: THE SYSTEM SHALL NOT internally retry resolution or substitute an alternate
  tool inside the box; recovery is DER's responsibility (graft/split).
- AC3: IF a dispatched tool returns `{"success": False}` THEN THE SYSTEM SHALL return
  `DispatchResult.success=False` so the existing retry-with-backoff (transport
  errors) and graft path engage.

**Edge Cases:**
- `FAIL` on a non-critical step → recorded to memory + Caducean drift signal
  (existing behavior), no graft.
- `FAIL` on a critical step with graft budget exhausted → `TASK_BLOCKED` +
  `ask_user` (REQ-10), never silent partial completion.

### REQ-7: Per-step failure detection distinguishes crash from "no tool needed"
**User Story:** As the debugger, I want a resolver crash and a legitimate "reason"
step to behave differently, so a dead model is never silently executed as a stub.

**Verified:** agent_kernel.py:5296 (RC1 validation only `if item.tool` — bypassed
when resolver fails), agent_kernel.py:6379 (`_run_step_direct` when `tool is None`),
agent_kernel.py:6457-6470 (`_STUB_RE` / `_verified_fraction` stub detector,
post-hoc), agent_kernel.py:5329-5358 (retry_with_backoff).

**Acceptance Criteria:**
- AC1: WHEN `resolve` returns `FAIL` THEN THE SYSTEM SHALL skip `_run_step_direct`
  and go straight to the failure path (no stub generation).
- AC2: WHEN `resolve` returns `REASON` THEN THE SYSTEM SHALL execute `_run_step_direct`
  (legitimate reasoning step).
- AC3: THE SYSTEM SHALL apply RC1 pre-execution validation (`validate_tool_call`)
  whenever a `TOOL` decision is produced, before dispatch, so invalid tools fail
  before runtime.

**Edge Cases:**
- A `TOOL` decision that passes RC1 but fails at dispatch → retry_with_backoff then
  graft (existing).
- A `REASON` step whose direct output matches the stub pattern → `_verified_fraction`
  still flags it (existing D0.1), but this is now only reachable for genuine
  reasoning steps, not resolver crashes.

### REQ-8: Router-agnostic across providers, local models, and swarm
**User Story:** As the architect, I want the black box to work unchanged whether the
reasoning provider is Cerebras, a local model, or a swarm, so the swarm refactor is
isolated.

**Verified:** inference/router.py:167-172 (role bindings:
`reasoning`/`tool_execution`), inference/router.py:255-270 (`resolve` default-role
fallback), agent_kernel.py:8015-8059 (swarm snapshot hydrates via
`router.bind_role`, not direct box access), inference/router.py:283-304 (transport
kinds: INPROCESS/API/LOCAL_OPENAI/OLLAMA).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL resolve and dispatch exclusively through `InferenceRouter`
  role bindings; it shall not read `_model_config_snapshot`, `_swarm_config_snapshot`,
  or any provider URL directly.
- AC2: WHILE a local model is bound to `tool_execution` and a remote model to
  `reasoning` THEN THE SYSTEM SHALL use the `reasoning` provider for resolution and
  the `tool_execution` provider (or no LLM) for dispatch, per the bindings.
- AC3: WHEN the swarm refactor rebinds roles on the router THEN THE SYSTEM SHALL
  require no changes to the black box.

**Edge Cases:**
- Both roles bound to the same instance → box still works (single provider).
- `tool_execution` unbound but `reasoning` bound → `resolve("tool_execution")` falls
  back to default role (existing router behavior); box does not special-case this.

### REQ-9: Observability / tuning instrumentation
**User Story:** As the tuner, I want measured signals for resolution latency and
failure rate, so that I can tune thresholds and confirm the death-spiral is gone.

**Verified:** NEW (implementation pending). Anchored to backend/tests/_sort_log.py
sorter convention (`logs/by_type/*.log`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log `TOOL_DECISION` latency (`resolve_ms`) and
  `TOOL_DISPATCH` latency (`duration_ms`), thread-scoped, so per-step cost is
  measurable.
- AC2: THE SYSTEM SHALL increment a per-conversation failure counter exposed via the
  existing context-usage / status channel, so a run with repeated `FAIL` is visible
  without raw log grep.
- AC3: THE SYSTEM SHALL track **tool-selection accuracy** (did the resolved tool match
  the task's ground-truth need) and **first-attempt argument validity** (percentage of
  tool calls passing schema validation without a retry), as leading indicators of
  schema/prompt quality.
- AC4: THE SYSTEM SHALL track the **error-class distribution** (transient vs
  validation vs permission vs permanent) per tool, so the dominant failure mode is
  visible and actionable (REQ-10).
- AC5: THE SYSTEM SHALL export the **`ToolCallTree` collapse snapshot** (REQ-13) per
  conversation as an observability artifact, so a run's full tool-call structure is
  reconstructable without raw log grep.
- AC6: THE SYSTEM SHALL surface these metrics through the existing context-usage /
  status channel (thread-scoped), never as raw log lines only.

**Edge Cases:**
- Missing id → fallback scope, never drop the metric.
- High volume → counters are cheap (in-memory per conversation), off the critical
  path.
- Error class unparseable → counted under `permanent` (safe default, REQ-10 AC4).

### REQ-10: Structured tool error envelope + transient/permanent classification
**User Story:** As the debugger and the model, I want every tool failure to carry a
machine-readable class and a next-action hint, so retries are safe and the model can
self-correct instead of looping.

**Verified:** tool_bridge.py:889 (`execute_tool` returns `{"success": False, "error": <str>}`
— a loose string today, no class), agent_kernel.py:5329-5358 (`retry_with_backoff_sync`
retries only `ConnectionError`/`Timeout`, no permanent/transient distinction),
agent_kernel.py:576 (`infer` never raises — failures surface as empty, not classified).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL return tool failures as a structured envelope with
  `error_type` ∈ {`validation`, `transient`, `rate_limit`, `not_found`,
  `permission`, `partial_success`, `permanent`}, a human-readable `message`, a
  `suggested_action`, and an optional `example_valid_call`.
- AC2: WHEN a tool failure is `transient` (408/429/5xx/timeout/connection-reset)
  THEN THE SYSTEM SHALL retry with jittered exponential backoff up to a bounded count.
- AC3: WHEN a tool failure is `permanent` (400/401/403/404/422, schema violation,
  hallucinated tool name) THEN THE SYSTEM SHALL NOT retry verbatim; it shall re-plan
  with the error fed back as an observation or escalate (REQ-6).
- AC4: THE SYSTEM SHALL classify failures from the structured envelope (HTTP code +
  provider/tool error code), never from string-matching the message body.

**Edge Cases:**
- `partial_success` (some sub-results ok, some failed) → inspect succeeded/failed
  arrays; do not assume full completion.
- `rate_limit` → honour `retry_after` hint; do not tight-loop.
- Envelope missing a field → default `error_type=permanent` (safe: forces re-plan,
  not a blind retry).

### REQ-11: Idempotency keys for write / side-effecting tools
**User Story:** As the user, I want a retried tool call to never double-send, double-
charge, or double-create, so a transient timeout during a write does not duplicate a
side effect.

**Verified:** tool_bridge.py:889 (`execute_tool` has no idempotency concept),
agent_kernel.py:6326-6386 (dispatch path, no key), caducean_trajectory.py:304-325
(commit ledger records actions but no idempotency guard).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL classify every tool as `read` or `write` (side-effecting);
  `write` tools require an idempotency key.
- AC2: THE SYSTEM SHALL generate a deterministic idempotency key per logical action
  as `hash(turn_id + tool_name + args)` and pass it through the tool boundary on every
  call (including retries).
- AC3: WHEN a `write` tool is retried with the same idempotency key THEN THE SYSTEM
  SHALL return the original result rather than re-executing the side effect (server-
  native key or a client-side cache keyed by the same hash with a TTL).
- AC4: THE SYSTEM SHALL NOT blind-retry a `write` tool whose backend does not support
  idempotency without first checking status or wrapping it in an idempotency proxy.

**Edge Cases:**
- Tool has no native idempotency support → client-side cache (key→result, TTL) makes
  the retry safe.
- Key collision across distinct logical actions → key includes `args` hash, so
  distinct args yield distinct keys (no false de-dupe).

### REQ-12: Per-tool retry budget + duplicate-call detection, DER-split-aware
**User Story:** As the tuner, I want a stuck tool to stop being retried and a looping
agent to be detected, without penalizing legitimate DER recovery splits.

**Verified:** agent_kernel.py:5128 (`hit_cycle_limit()` global guard only),
agent_kernel.py:5329-5358 (`retry_with_backoff_sync` 2 retries, no per-tool budget),
agent_kernel.py:7102-7107 (`_split_step` Sub-Loops collapse to parent as one COMPRESS),
der_loop.py:92 (`is_subloop` flag).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL maintain a per-tool consecutive-failure budget scoped to a
  **step identity**; after N consecutive failures within one step THEN THE SYSTEM
  SHALL return a terminal "do not call this tool again; proceed without it or report
  inability" message rather than retrying.
- AC2: THE SYSTEM SHALL detect a repeated identical call — same `(tool, args_hash)`
  within the same step — and treat it as a loop signal: tell the model to change
  arguments or approach instead of re-executing.
- AC3: WHEN a step fails verification and DER grafts a recovery Sub-Loop
  (`_split_step`, `is_subloop=True`) THEN THE SYSTEM SHALL assign the Sub-Loop its own
  step identity so its tool calls are NOT counted against the parent step's retry
  budget nor flagged as duplicates of the parent — recovery is legitimate, not a loop.
- AC4: THE SYSTEM SHALL keep the existing global `hit_cycle_limit()` + token budget as
  the last-line guard; per-tool budget (AC1) and dedup (AC2) are finer-grained layers
  in front of it.

**Edge Cases:**
- A Sub-Loop that itself fails and is re-split → each split gets a fresh step identity
  (AC3); the global cycle limit (AC4) still bounds total splits.
- Per-tool budget exhausted on a critical step → route to `_der_handle_step_failure`
  (graft/escalate, REQ-6), not silent skip.

### REQ-13: Loop-collapse ToolCallTree snapshot (observability + memory pre-filter)
**User Story:** As the system, I want the collapse of a DER loop to emit a structured
tree of every tool call across all splits, so it both observes the run and feeds the
memory pre-filter for future tasks.

**Verified:** caducean_trajectory.py:304-325 (`record_commit` writes one ledger row per
executed action with `step_id`, `u`, `xi`, `verified_label` — flat today, not a tree),
agent_kernel.py:5848-5874 (Sub-Loops collapse back to parent), agent_kernel.py:7102-7107
(split/collapse as ONE COMPRESS, `u/xi` carried), crawler/source_registry.py:36
(`SourceRegistry` — the web-search-specific learned topic→URL memory this generalizes).

**Acceptance Criteria:**
- AC1: WHEN a DER loop collapses (Sub-Loops → parent COMPRESS; `DER_DONE`) THEN THE
  SYSTEM SHALL emit a `ToolCallTree`: nodes are tool calls
  `(tool, args_hash, result/error_class, step_id, source, split_depth)`; edges are the
  step hierarchy (parent `step_id` → child `step_id`).
- AC2: THE SYSTEM SHALL persist the `ToolCallTree` per conversation (never injected
  into a prompt) as the honest audit trail and the learning signal for the outer loop.
- AC3: THE SYSTEM SHALL feed the `ToolCallTree` into the memory pre-filter (REQ-4)
  so future tasks with similar goals retrieve the tools that succeeded, generalizing
  `SourceRegistry` (web-only today) to all tools.
- AC4: THE SYSTEM SHALL export the `ToolCallTree` as an observability artifact
  (thread-scoped) so a run's full tool-call structure is reconstructable without raw
  log grep (extends REQ-9).

**Edge Cases:**
- Tree with zero tool calls (pure reasoning run) → valid empty tree, still emitted.
- Very deep split chain → `split_depth` bounded by the global cycle limit (REQ-12 AC4);
  tree truncation must preserve parent links.

## Non-Requirements (Out of Scope)
- Changing the Caducean physics layer or the split operator itself (`_split_step`,
  `_growth_width`) — only how failures reach them.
- Frontend design changes (deferred until tool-calling is verified solid).
- Replacing `tool_bridge.execute_tool`'s capability/permission gates — they are
  correct; the box calls through them.
- Auto-selecting a different model when one is down (that is a fallback — excluded
  per Decisions Locked #1).

## Open Questions
- Should `REASON` steps still emit a `TOOL_CALL` event (currently emitted at
  agent_kernel.py:5278 with `tool_name="direct"`)? Recommend: emit
  `TOOL_CALL` with `kind=reason` for frontend clarity. (Non-blocking; resolve during
  design review.)
- Exact shape of the `DER_UNAVAILABLE` event (REQ-1 AC3) — align with frontend once
  the event bus contract is reviewed. (Non-blocking.)

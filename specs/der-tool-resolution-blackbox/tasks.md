# Tasks: DER Tool-Resolution Black Box

> Each task links to a requirement. Grouped into waves for parallel execution.
> Dependency note: Wave 1 (box + pre-flight) must land before Wave 2 (DER loop
> wiring) because the loop calls the box. Wave 3 (tests) can start as soon as the
> relevant wave's code exists. Frontend event-shape alignment (REQ-1 AC3, REQ-7
> open question) is deferred per the standing "fix tool-calling before frontend
> design" rule and is called out in Wave 4 as a contract-only task.

## Wave 1 — Black box foundation
- [ ] T1 (REQ-3, REQ-4): Create `backend/agent/tool_decision.py` with `ToolDecisionBox`,
  `Decision`/`DispatchResult`/`DecisionKind` dataclasses, constructor injecting
  `router`, `tool_bridge`, `get_available_tools`, `validate_tool_call`. — new file
- [ ] T2 (REQ-4, REQ-7): Implement `resolve()` — call `router.generate("reasoning",
  propose_prompt)`; parse to `TOOL(source=llm)` / `REASON(source=llm)` / consult
  memory; if model dead/unparseable, consult pheromone/mycelium and return
  `TOOL(source=memory)` when a registered tool is suggested; only if memory also
  yields nothing → `FAIL`. No silent "reason" masking. — tool_decision.py
- [ ] T3 (REQ-4, REQ-7 AC3): Implement RC1 `validate_tool_call` invocation inside
  `resolve()` for every `TOOL` decision before returning. — tool_decision.py
- [ ] T4 (REQ-3, REQ-6): Implement `dispatch()` — `tool_bridge.execute_tool` for
  `TOOL`, `_run_step_direct` for `REASON`; return `DispatchResult(success, ...)`;
  `FAIL` is never dispatched (caller routes to recovery). — tool_decision.py
- [ ] T5 (REQ-5, REQ-9): Add `TOOL_DECISION` / `TOOL_DISPATCH` / `TOOL_DECISION_FAIL`
  thread-scoped, timestamped logs with `resolve_ms` / `duration_ms`. — tool_decision.py
- [ ] T6 (REQ-1): Add `InferenceRouter` health probe helper (resolve "reasoning" +
  reachability check; `uninitialized`/dead → unavailable). — inference/router.py

## Wave 2 — DER loop wiring (remove scattered resolution)
- [ ] T7 (REQ-1): Add pre-flight at `_execute_plan_der` entry (agent_kernel.py:4942):
  if no usable `reasoning` provider → return structured error + emit `DER_UNAVAILABLE`,
  no loop, no card. — agent_kernel.py
- [ ] T8 (REQ-2): Change `_plan_task` (agent_kernel.py:3834-3844) silent single-step
  fallback → signal plan error (structured); caller returns ERROR, no self-do. — agent_kernel.py
- [ ] T9 (REQ-3 AC3, REQ-7): Replace inline resolver + dispatch in
  `_der_run_step_execution` (agent_kernel.py:6286-6386) with
  `ToolDecisionBox.resolve` then `.dispatch`; `FAIL` → `_der_handle_step_failure`
  (skip `_run_step_direct`). — agent_kernel.py
- [ ] T10 (REQ-4, REQ-6): Refactor `explorer.propose` (explorer.py:179-214) so the
  memory-driven paths (pheromone top-1, mycelium/web-intent) are explicit, logged
  resolver signals returning `TOOL(source=memory)`; REMOVE only the silent
  "reason instead" masking on model failure (that becomes `FAIL`). The box owns this
  resolution; `propose` becomes the LLM-decision helper it calls. — explorer.py
- [ ] T11 (REQ-8): Confirm box uses only `router`/`tool_bridge`; remove any direct
  snapshot reads from the step-execution path. — agent_kernel.py / tool_decision.py

## Wave 2b — Production-safety hardening (external best-practice gaps)
- [ ] T18 (REQ-10): Add structured error envelope (`error_type`, `suggested_action`,
  `example_valid_call`) to `DispatchResult` / `tool_bridge.execute_tool`; classify
  transient vs permanent from the envelope; route permanent → re-plan, never retry
  verbatim. — tool_decision.py / tool_bridge.py
- [ ] T19 (REQ-11): Classify tools read/write; generate idempotency key
  `hash(turn_id + tool_name + args)`; pass through dispatch; client-side cache for
  tools without native idempotency support. — tool_decision.py / tool_bridge.py
- [ ] T20 (REQ-12): Per-tool consecutive-failure budget scoped to step identity;
  duplicate-call detection `(tool, args_hash)`; ensure `_split_step` Sub-Loops get
  their own step identity so recovery is not penalized as a loop. — tool_decision.py /
  agent_kernel.py
- [ ] T21 (REQ-4 AC6, REQ-13): Wire `SourceRegistry` + `ToolCallTree` collapse as the
  memory pre-filter: retrieve narrowed candidate set before the LLM call; emit
  `ToolCallTree` on `DER_DONE`. — tool_decision.py / caducean_trajectory.py /
  crawler/source_registry.py

## Wave 3 — Verification (contract + behavioral + CDD harness)
- [ ] T12 (REQ-3, REQ-4): `tests/unit/tool_decision_test.py` — resolve TOOL/REASON/
  FAIL on faked infer; FAIL on ""/raise/invalid tool; RC1 runs. — new test
- [ ] T13 (REQ-3): `tests/contract/test_tool_decision_contract.py` — Decision /
  DispatchResult / DER_UNAVAILABLE shapes pinned. — new test
- [ ] T14 (REQ-1, REQ-2, REQ-6): `tests/behavioral/test_tool_decision_behavioral.py`
  — dead-provider → no card + ERROR <2s + zero dispatches; web goal → crawler_query
  dispatched; invalid tool → FAIL → graft/escalate. — new test
- [ ] T15 (REQ-5, REQ-9): Extend `backend/tests/_sort_log.py` with
  `tool_decision.log` / `tool_dispatch.log` / `tool_decision_fail.log` buckets. — backend/tests/_sort_log.py
- [ ] T16 (REQ-1, REQ-4, REQ-6): `scripts/validate_der_tool_resolution.py` standing
  CDD harness — replays dead-model / web-search / invalid-tool trajectories through
  full stack, asserts contracts + behaviors every run. — new script
- [ ] T22 (REQ-10, REQ-11, REQ-12): `tests/unit/tool_safety_test.py` — error-envelope
  classification (transient→backoff, permanent→re-plan), idempotency no-double-execute
  on retry, per-tool budget + dedup, and split-scoped identity (graft not penalized).
- [ ] T23 (REQ-13, REQ-4 AC6): `tests/behavioral/test_toolcall_tree.py` — collapse emits
  `ToolCallTree` across splits; repeated goal retrieves succeeded tools via pre-filter.

## Wave 4 — Frontend contract alignment (deferred until tool-calling verified)
- [ ] T17 (REQ-1 AC3, REQ-7 open Q): Align frontend event bus with `DER_UNAVAILABLE`
  and `TOOL_CALL{kind}` shapes; render error state instead of phantom card. — frontend
  (BLOCKED on "fix tool-calling before frontend design" rule; do after live verify)

## Dependency / parallelization notes
- T1-T6 (Wave 1) are backend-only and can run in parallel within the wave.
- T7-T11 (Wave 2) depend on T1-T4 (box interface must exist). T7/T8 are independent
  of T9/T10 and can parallelize.
- T12-T16 (Wave 3) can begin as soon as the task it covers lands; T16 needs T7+T9.
- T17 (Wave 4) is explicitly deferred per the standing frontend-design rule and must
  not block backend verification.
- The swarm refactor (user-owned) requires NO changes here (REQ-8 AC3) — it only
  rebinds router roles, which the box already consumes.

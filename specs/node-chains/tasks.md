> **SUPERSEDED (2026-08-23).** This spec is merged into
> [`specs/wormhole-aperture/`](../wormhole-aperture/) as **Stage C — Node Chains**.
> Node Chains is no longer a peer feature: it is the CONSUMER that proves a delivered
> recall was worth delivering. Its REQ IDs are preserved via the mapping table in
> `specs/wormhole-aperture/requirements.md` (NC REQ-1..15 -> REQ-18..31).
> Do not implement from this file. Kept for provenance only.

# Tasks: Node Chains — Emergent, Composable Skills

> Each task links to a requirement. Grouped into waves for parallel execution.
> Every task carries a RIPPLE note naming the areas it touches or relies on.

## Wave 0 — Green baseline (MANDATORY, before any implementation)

- [ ] T0 (ALL REQs): Establish the green baseline — run every test suite relevant to
  this spec and record the exact pass/fail state BEFORE any code changes:
  - `backend/agent/tests/test_recall_fixes.py` (C3 skill-genesis test = REQ-3
    requirement; C5 chunk-callback test = the OTHER handoff bug)
  - `backend/tests/test_workflow_capture.py` (existing capture pipeline — REQ-2/3
    ripple)
  - `backend/tests/test_dag_node_contract.py` + `test_dag_node_behavior.py` (the
    node substrate this spec builds on)
  - The full gate+routing suite (semantic-gate / Tier-1 / encoder — must stay green)
  - Standing CDD harness `scripts/validate_der_*.py`
  - RIPPLE: classify each failure as REAL GAP (C3 skill genesis → REQ-3; C5
    conversation_id → separate fix) vs STALE TEST (3 embedding-contract tests);
    pin the baseline (pin_add) so no implementation step can claim a regression that
    pre-existed; the C3 test MUST remain unmodified and red until REQ-3 lands.

## Wave 1 — Foundation (data model + storage)

- [ ] T1 (REQ-1): Define NodeChain / PivotEvent / ChainVariant dataclasses in
  `backend/agent/node_chain.py` — RIPPLE: new module; consumed by extraction,
  runner, projection. Contract test CT-3/CT-4 pins the shapes.
- [ ] T2 (REQ-1): Add `node_chains`, `pivot_events`, `chain_variants` tables to
  `backend/memory/db.py` (follow the `mycelium_traversals` pattern at `:229`) —
  RIPPLE: app memory schema; idempotent CREATE TABLE IF NOT EXISTS; no migration
  needed for existing DBs.
- [ ] T3 (REQ-1): Sequence-hash dedupe helper (stable hash of mediator sequence) —
  RIPPLE: used by both extraction paths (T4, T5); unit test.

## Wave 2 — Extraction (live + recall)

- [ ] T4 (REQ-2): Live-run extraction — `extract_chain_from_run(node_records,
  session_id)` reading `der_fan_traces`; wire into `_maybe_trigger_skill_creation`
  (`agent_kernel.py:1535`) replacing the tool-name heuristic — RIPPLE:
  `agent_kernel.py` call site `:7021`; `workflow_capture.py` superseded;
  `caducean_trajectory.py` read helper.
- [ ] T5 (REQ-3): Recall-episode extraction — query `episodes` WHERE
  `source_channel='recall' AND outcome_type='success'`, group by op pattern,
  count >= 3 → chain. Wire the recall path into `_maybe_trigger_skill_creation`
  (currently returns early on empty tool_sequence at `:1561`) — RIPPLE: the C3
  test `test_recall_fixes.py::TestC3SkillGenesisSql` MUST pass unmodified;
  `recall_phases.py` is NO-CHANGE (verified — `:433` already records the data).
- [ ] T6 (REQ-2, REQ-3): Refactor `workflow_capture.py` — keep `register_verified_skill`
  shape for backward compat (CT-2), replace `should_capture`/`self_test_skill`
  with chain extraction + registered-tool validation (reuse `tool_registry.resolve_tool`
  at `:99`) — RIPPLE: `backend/tests/test_workflow_capture.py` assertions preserved
  where behavior is preserved; `auto_research.py` consumer.

## Wave 3 — Pivot recording + promotion

- [ ] T7 (REQ-4): Pivot recording — `record_pivot(chain_id, node_index, reason,
  alternative, outcome)` reading u/xi from Caducean; write `pivot_events` row with
  topic/execution domain tags — RIPPLE: `der_loop.py` NodeRecord finalize site;
  `caducean_trajectory.py`; contract test CT-4.
- [ ] T8 (REQ-5): Promotion — when same fork point succeeds N times (default 2) AND
  RL confirms improvement, write `chain_variants` row + regenerate chain.md —
  RIPPLE: `node_chain.py`; `mycelium_landmark_merges` pattern for merge/archive;
  physics-aware test (neutral RL → no promotion).
- [ ] T9 (REQ-5): Variant selection at execution — agent may choose main chain or
  variant; bound variants per fork (default 3), archive weakest on overflow —
  RIPPLE: chain runner (T10); REQ-8 archive logic.

## Wave 4 — Chain-guided execution + projection

- [ ] T10 (REQ-6): Chain-seeded DirectorQueue — when a chain matches (trigger +
  topic/execution domain), seed the queue from the chain's nodes; every node still
  runs through NodeOutcome + routing + fold-back — RIPPLE: `der_loop.py`
  `DirectorQueue` (`:243`); `agent_kernel.py` DER entry; disable switch (REQ-6 AC5).
- [ ] T11 (REQ-7, REQ-8): chain.md generation + storage + linking — minimal
  projection (name, trigger, nodes, forks) written to `data/chains/<chain_id>.md`,
  size-bounded, regenerated on chain change (idempotent — same chain_id, new
  content), never hand-written; frontmatter carries `chain_id` (file → chain),
  chain record carries `chain_md_path` + `chain_md_hash` (chain → file + staleness
  detection); register each chain.md as a pin (`pin_type='chain_md'`) linked via
  `pin_links`, with `ref_status` alive/stale tracking on chain change — RIPPLE:
  new `data/chains/` directory; `pins` + `pin_links` tables; contract test CT-5;
  token-discipline requirement REQ-8 AC1-AC5.
- [ ] T12 (REQ-8): Chain lifecycle bounds — max chains (default 200), archive
  weakest on overflow (deferred to maintenance pass), merge near-duplicates
  (prefix + outcome) — RIPPLE: `mycelium_landmark_merges` pattern; REQ-8 AC5
  stats recording.

## Wave 5 — Node grafts + disambiguation + evolution

- [ ] T13 (REQ-10): Chain grafts — promote a verified chain to a composite node
  (`NodeSpec` with `composite_of`, `origin='chain_graft'`); self-test before
  acceptance (reject without touching registry); sync on chain change (re-graft or
  mark stale) — RIPPLE: `tool_registry.py` `register_node`; `node_chain.py`;
  duplicate guard (CT-8 in dag-node-execution-model).
- [ ] T14 (REQ-11): Script grafts — `executor="script"` type on `ToolSpec`
  (`tool_registry.py:58`) + `script_sandbox.py` (subprocess, timeout, no shell
  expansion, bounded args, no network by default); `read_only` default + user
  approval for escalation; structural self-test before first use; disable switch
  (composition-only mode) — RIPPLE: `tool_bridge.py` dispatch (`:825` pattern);
  `permissions.py` tiers; REQ-11 AC1-AC7.
- [ ] T15 (REQ-12): Context signatures — every node gains domain + artifact contract
  + intent keywords; chain nodes record context at capture; fit validation at replay
  (mismatch → pivot, never wrong-tool fire); semantic similarity index for selection
  + graft near-duplicate refusal — RIPPLE: `tool_registry.py`; `node_chain.py`;
  `der_loop.py` replay path; contract test CT-7.
- [ ] T16 (REQ-13): Tool evolution — tool version/signature_hash on chain nodes;
  tool-change detection flags referencing chains stale + re-validates (adapted /
  re-captured / archived); improved tool bumps chain confidence (RL reinforcement) —
  RIPPLE: `tool_registry.py` versioning; `tool_evolution.py` (NEW); `node_chain.py`;
  contract test CT-8.
- [ ] T17 (REQ-10..REQ-13): Contract tests CT-7/CT-8 + behavioral tests BT-6/BT-7
  (similar-tool fit selection; tool-change re-validation) — RIPPLE:
  `backend/tests/contract/`, `backend/tests/behavioral/`.

## Wave 6 — Blocker removal + chain permissions

- [ ] T18 (REQ-14): Remove capture blockers — drop `MIN_DISTINCT_TOOLS`
  (`workflow_capture.py:29`), replace name-Jaccard dedupe with order-sensitive
  sequence hash, extract from BOTH episode channels (`websocket` DER runs +
  `recall`), add artifact CONSUME contract to NodeSpec (validate compatibility at
  composition, REQ-14 AC4) — RIPPLE: `workflow_capture.py`, `node_chain.py`,
  `tool_registry.py` `_produce`/`_consume` maps, `agent_kernel.py:747` episode
  channel, `der_loop.py` composition check.
- [ ] T19 (REQ-15): Chain-level permission resolution — chain tier = MAX of node
  tiers; chain-as-unit user approval when above session tier; approved tier recorded
  on chain; re-check on tool evolution (REQ-13) — RIPPLE: `node_chain.py`,
  `permissions.py`, `der_loop.py` execution gate, contract test CT-9.
- [ ] T20 (REQ-11 + UC-2): Self-created MCP server pattern — script graft that speaks
  JSON-RPC, runtime registration into `mycelium_mcp_registry` with trust level,
  network approval path (sandbox AC2/AC3) — RIPPLE: `tool_registry.py` MCP executor
  path, `mycelium_mcp_registry`, `script_sandbox.py`.

## Wave 7 — Integration + verification

- [ ] T21 (REQ-9): Observability — log chain creation (source, hash, provenance),
  every PivotEvent, every promotion/refusal, every graft (accepted/rejected), scoped
  by session/thread — RIPPLE: `node_chain.py`; structured logging standard.
- [ ] T22 (REQ-6): AutoResearchRunner integration — read chains alongside
  `named_skills` for refinement (`auto_research.py:364`) — RIPPLE: `auto_research.py`;
  CT-2 named_skills compatibility.
- [ ] T23 (REQ-2..REQ-15): Contract tests CT-1..CT-9 + behavioral tests BT-1..BT-7
  + physics-aware promotion test + cross-domain composition test + chain-approval
  test — RIPPLE: `backend/tests/contract/`, `backend/tests/behavioral/`; the C3 test
  is the REQ-3 requirement.
- [ ] T24 (REQ-2..REQ-15): Extend standing CDD harness (`scripts/validate_der_*.py`)
  to replay recorded trajectories and assert chains + pivots + grafts emerge —
  RIPPLE: harness scripts; runs on every validation.

## Dependency / parallelization notes

- **Wave 1 must land first** — T1/T2/T3 are prerequisites for everything else
  (models + tables + dedupe).
- **Wave 2 (T4, T5) can run in parallel** once Wave 1 is in — live-run and
  recall-episode extraction are independent paths; T5 unblocks the C3 test.
- **Wave 3 (T7, T8, T9) depends on Wave 1** (pivot_events table) and partially on
  Wave 2 (pivots are defined relative to chains). T7 can start once T1/T2 land.
- **Wave 4 (T10, T11, T12) depends on Wave 2** — the runner needs chains to exist;
  the projection needs chains to exist.
- **Wave 5 (T13-T17) depends on Wave 1** (registry + models) and partially on Wave 2
  (grafts need chains). T15 (context signatures) and T16 (tool evolution) can start
  once T1/T2 land — they touch the registry, not the extraction paths.
- **Wave 6 (T18-T20) depends on Wave 1 + Wave 2** — blocker removal touches
  extraction; permissions touch the execution gate. T18 can start alongside Wave 2.
- **Wave 7 (T21-T24) is the verification wave** — T23/T24 run against the completed
  feature; T21 (observability) can land early alongside Wave 2.
- **NO-CHANGE-verified areas** (need only contract tests, no code): `recall_phases.py`
  (`:433` already records the data), `mycelium/store.py` (`:546` already records
  paths), `semantic_gate.py` (routes on rules + coordinates), `nodes/outcome.py`
  (CT-1 lock), `semantic.py` named_skills shape (CT-2 lock).
- **CONTRACT LOCK areas** (pin with tests, never modify): `nodes/outcome.py` Reason
  vocabulary (CT-1), `named_skills` category shape (CT-2), the C3 test
  (`test_recall_fixes.py::TestC3SkillGenesisSql` — the REQ-3 requirement).
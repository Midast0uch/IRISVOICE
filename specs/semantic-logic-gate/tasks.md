# Tasks: Semantic Logic Gate Architecture (DAG-Routed & Ontology-Grounded)

> Each task links to a requirement from `requirements.md`. Tasks are grouped into waves for safe, dependency-ordered execution.

## Wave 0 — Green Baseline (run FIRST, before any gate code)
- [ ] W0.1: Run the full backend suite to green. Baseline `pytest` across `backend/tests/` (unit + contract + behavioral) and `backend/agent/tests/`, plus `npx tsc --noEmit` / `npm test` on the frontend. Record any pre-existing failures as a known-baseline list — the gate must not be blamed for them.
- [ ] W0.2 (REQ-1): Snapshot the current routing contract. Pin the existing `_needs_planning` / `_classify_intent` behavioral tests (`test_universal_planning.py` + twin) as the reference outcomes the gate must reproduce, and confirm the 5+ `MagicMock` sites that depend on the `_needs_planning` shim.
  - **RIPPLE**: Establishes the before-state so the after-state can be diffed honestly (kiro-spec-writer step 1). No code changes.

## Wave 1 — Foundation, Provenance & Centroid Engine
- [ ] T1 (REQ-1, REQ-3, REQ-6): Create `backend/agent/semantic_gate.py` defining `IntentDomain`, `CapabilityLane` (**16 lanes, not 15**), `EdgeRelationship`, `DAGPlanNode`, `DAGPlanGraph`.
  - **RIPPLE**: New module. Imports `DOMAIN_IDS` (`spaces.py:89`), `LINK_VOCABULARY` (`pin_store.py:61`), and node-type values from source — never hardcoded (REQ-6 AC1, CI-pinned by `scripts/validate_ontology_schema.py`).
- [ ] T2 (REQ-1, REQ-3): Implement Tier 0 deterministic fast-path by **migrating** the existing rule sets verbatim — `_is_chitchat` (`agent_kernel.py:1792`), `_ACTION_VERBS` (`1820`), `_FOLLOWUP_MARKERS` (`1838`), `_ANAPHORA_PRONOUNS` (`1844`), `_is_followup_to_task` (`1846`), `_is_web_search_request` (`4540`).
  - **RIPPLE**: Independent pure module; zero impact on the live router until wired.
- [ ] T3 (REQ-3): Implement Tier 1 neural centroid projector — lazy centroid load from `semantic_gate_centroids.json`, `encode_with_backend(text, BACKEND_LFM)`, normalized-dot comparison with early-exit top-2 margin ($\Delta_{\text{margin}}=0.15$), co-mingling threshold ($\tau_{\text{co-mingle}} \ge 0.62$), and the **provenance gate** (`EmbeddingService.backend == BACKEND_LFM`). Emit a **ranked lane distribution**, not a single label (REQ-1 AC7).
  - **RIPPLE**: Client of `EmbeddingService`; reuse its LRU cache + lazy/bounded load. No model load at import.
- [ ] T4 (REQ-2, REQ-6): Implement Tier 2 ontology walk by **reusing** the extracted recall helper (shared with `_der_recall_neighborhood`, `agent_kernel.py:4241`) and `filtered_chain_recall` with registry-backed axes + widen-order; route `preference_lookup` → `semantic.py` (REQ-2 AC4).
  - **RIPPLE**: Calls `ontology_recall.py` (read-only, shared connection). Refactor `_der_recall_neighborhood` into the shared helper first.
- [ ] T5 (REQ-4): Implement the Contextual Continuation evaluator as a **read-only lens** over the existing execution graph — read `ExecutionLedger`/`TaskLifecycle` (`der_execution_ledger.py:177,209`) + active `DirectorQueue` (`der_loop.py:243`) for follow-up decisions; emit *extend* (append `QueueItem` steps via the graft path, `agent_kernel.py:7810`) / *morph* (edit `depends_on`, reuse `_split_step` + fold-back) / *close* (transition lifecycle to terminal) directives. Add `recall_failed_like` AVOID integration.
  - **RIPPLE**: No new persistence. Reuses `self._der_ledger` (`agent_kernel.py:6871`), `DirectorQueue`, `NodeRecord`, and the link store. Lifecycle mirrors `useTaskProgress.ts` resets.
- [ ] T6 (REQ-7): Implement bidirectional Caducean memory — coordinate recall via `ffi_immortus_chain_query_by_coordinate` (`iris_ffi.py:1639`) using `ffi_caducean_get_state` (`1555`) coordinates, and routing write-back via `ffi_immortus_chain_append` (`1585`) with ontology axes + coords, off the hot path.
  - **RIPPLE**: Read/write the existing `memory_chain` (same table REQ-2 reads); engine-not-loaded no-ops.

## Wave 2 — Kernel Integration & Telemetry
- [ ] T7 (REQ-1, REQ-2, REQ-4, REQ-8): Wire `SemanticLogicGate.compile_dag()` into `agent_kernel.py`, replacing `_classify_intent` (`1885-1927`) and `_needs_planning` (`1928-1955`) with the structured planning decision. Keep a **temporary** `_needs_planning` shim (`compile_dag().requires_der_kernel`) so the routing-contract tests stay green (W0.2); re-express `_tool_mode` (`275`) as a registered policy (`auto|ask_first|disabled`); expose the planning-policy hook so skills/plugins/MCPs can adjust the draft `DAGPlanGraph` per task (REQ-8).
  - **RIPPLE**: Modifies the routing hot path. Pure conversation → `_respond_direct` with zero `TASK_START`; composite DAG → executable task plan. The shim is temporary and retired in T13 after the equivalence proof.
- [ ] T8 (REQ-5): Add gate fields to `TurnMetrics` (`observability.py:95`) and emit on the existing `[LAYERS]` line (`154`); reuse `record_widening_telemetry`; add the >35 ms warning via `loud_error`/`safe_call`.
  - **RIPPLE**: Extends the existing telemetry line; zero new logging infra.
- [ ] T9 (REQ-6 AC2): Add bounded, latched, background LFM warm-up at startup so the first user turn runs warm.
  - **RIPPLE**: Startup background task; never blocks init.

## Wave 3 — Calibration & Verification
- [ ] T10 (REQ-3 AC1): Produce and version the centroid calibration artifact (`semantic_gate_centroids.json`) — 16 normalized 1024-dim vectors with `backend` provenance, from a labeled prompt seed set.
  - **RIPPLE**: Data artifact; re-calibration without code deploy.
- [ ] T11 (REQ-1, REQ-3): Unit tests in `backend/tests/unit/test_semantic_gate.py` — 16 lanes, centroid math, early-exit margin, provenance gate (hash fallback skips Tier 1), non-binary co-mingling, edge cases.
  - **RIPPLE**: Verifies `semantic_gate.py` in isolation.
- [ ] T12 (REQ-1, REQ-2, REQ-5): Contract test `CT-GATE-1` in `backend/tests/contract/test_contract_semantic_gate.py` — `DAGPlanGraph` schema, zero-`TASK_START` on chitchat, `_tool_mode` honor, `[LAYERS]` gate fields, widen-scope logging, REQ-7 write-back is off the hot path.
  - **RIPPLE**: Contract lock on `IRISStreamEvent` + `TurnMetrics` + `memory_chain` row shape.
- [ ] T13 (REQ-1..REQ-8): Behavioral suite in `backend/tests/behavioral/test_behavioral_intent_routing.py` — 50+ benchmark prompts (multi-concern DAGs, ontology queries, desktop actions, chitchat, co-mingled chit-chat+task) through the live gate → kernel, plus a provenance test asserting ontology constants are imported, not copied. Tune `τ_co-mingle` / follow-up `sim` / margin here (Decisions Locked: initial → tuned).
  - **RIPPLE**: End-to-end regression guard; thresholds converge against real accuracy.
  - **GATE-PROOF gate (retires the shim)**: This task MUST (a) prove the gate's default `requires_der_kernel` is **equivalent** to the legacy `_needs_planning` outcomes for the simple cases W0.2 pinned, and (b) prove the gate is **superior** on co-mingled/multi-lane prompts the legacy classifier could not express. Only after both pass is the `_needs_planning` shim removed and its call sites pointed directly at the gate (Decisions Locked).

---

## Dependency & Parallelization Notes
- **Wave 0** (W0.1–W0.2) is prerequisite for everything — establishes the green baseline and the before-state of the routing contract.
- **Wave 1** (T1–T6) is self-contained in `backend/agent/semantic_gate.py` (+ the T4 shared-helper extraction) and can be built and unit-tested before touching `agent_kernel.py`'s routing path.
- **Wave 2** (T7–T9) modifies the live routing path and depends on Wave 1 passing unit verification.
- **Wave 3** (T10–T13) seals the contract boundaries and establishes the permanent regression guard.

### Corrected from the original task list
- Lane count fixed: **16**, not 15 (T1, T11).
- Tier 0 is a **migration** of existing rule sets, not new rules (T2).
- Ontology walk **reuses** the shared helper rather than a second implementation (T4).
- Telemetry **extends `TurnMetrics`**, not a new `SemanticGateTelemetry` (T8).
- Active-DAG follow-up is a **lens** over `ExecutionLedger`/`DirectorQueue`, not new state (T5).
- Added Wave 0 green baseline (W0.1–W0.2), bidirectional Caducean memory (T6), provenance gate (T3), warm-up (T9), and centroid calibration (T10) — all absent from the original.

---

## Implementation Notes & Pivot Rules (read BEFORE Wave 1)
These keep the implementation systematic and tell the agent when to deviate rather than stall or guess:

1. **Citations are versioned.** All `file:line` references were verified 2026-08-14. If a symbol has moved, re-locate it by name (grep the symbol), never trust a stale number — and update the citation in this spec.
2. **Re-verify before you reuse.** Every "REUSE (verified)" ripple row points at an API that existed at curation time. If the API differs, re-verify against live code first. If a cited API genuinely does not exist, that is a FINDING — surface it (per AGENTS.md "REPORT, DO NOT RECONCILE"); do not silently invent a replacement.
3. **Wave order is dependency-ordered.** Do not start Wave 2 before Wave 1's unit tests pass; do not start Wave 3 before Wave 2 routing works. Wave 0 is non-negotiable and is the entry point.
4. **The test rule is absolute.** Never weaken a test to go green. If a spec and a test conflict, report the conflict, name both sides, and propose a fix (AGENTS.md). Any change to a test's inputs must be called out in the report.
5. **Pivot on measurement, not preference.** Thresholds (`τ_co-mingle`, `sim`, margin) change only against the T13 benchmark numbers, with the measured reason written in a code comment (AGENTS.md: tolerances change for physical reasons, never "it was flaky").
6. **Quality check before every test run** (AGENTS.md): no blocking calls in async hot paths, heavy imports lazy, every exception path has an explicit outcome, resources cleaned up, no shared mutable state across sessions, structured logs with `turn_id`.
7. **Reuse beats novelty.** If a REUSE module already does the thing, use it. The gate adds a new module only for the routing/classification logic that exists nowhere else.
8. **The shim is temporary by design.** `_needs_planning` stays as a thin bridge only until T13's gate-proof (equivalence + superiority) passes; then it is removed and call sites point at the gate. Do not build new features on top of the shim.

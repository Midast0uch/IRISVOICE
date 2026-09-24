# Tasks: Tool Decision Engine Improvements (Sub-450ms Native Latency)

> Each task links to requirements. Waves are dependency-ordered; Wave 1 is engine scoring and parameter generation, Wave 2 integrates routing and vision deduplication, Wave 3 is verification and calibration.

---

## Wave 1 — Decision Engine Core Scoring & Parameter Fast-Path

- [ ] T1 (REQ-1): Implement single-letter candidate option formatting (`A, B, C, D`) and single forward-pass logit extraction in `backend/agent/decision_engine.py:426-453`, eliminating prefix-collision tie-breaker loops and context resets. — RIPPLE: Preserves `score_candidates` output interface while reducing CPU scoring latency to 25–60ms.
- [ ] T2 (REQ-2): Implement deterministic fast-path slot filling in `backend/agent/decision_engine.py:477-520` for single-parameter query tools (`search`, `crawler_query`), bypassing `generate_args` token generation. — RIPPLE: Eliminates 500–1,500ms autoregressive generation for search tasks.
- [ ] TG-1 (Wave 1 Gate): Run unit and contract tests proving AC1.1–1.4 and AC2.1–2.4 green. Verify scoring latency ≤ 180ms on CPU.

---

## Wave 2 — De-biasing, Lane Construction & Vision Deduplication

- [ ] T3 (REQ-3): Remove isolated token `"what's"` from `_VISION_TOKENS` and enforce multi-word contextual phrases (`"what's on screen"`, `"look at screen"`) in `backend/agent/tool_decision.py:51-65`. — RIPPLE: Prevents factual search queries from falsely triggering vision candidate menus.
- [ ] T4 (REQ-4): Refactor hierarchical lane construction in `backend/agent/tool_decision.py:464-534` to construct lanes from the full candidate set before applying candidate cap truncation. — RIPPLE: Ensures `web` lane is never dropped by wide candidate menus.
- [ ] T5 (REQ-5): Deduplicate screenshot capture in `backend/agent/tool_bridge.py:1601` by reusing the image buffer returned from the vision tool instead of executing a second synchronous screen capture. — RIPPLE: Saves 100–250ms of synchronous thread time per vision action.
- [ ] TG-2 (Wave 2 Gate): Run tests proving AC3.1–3.3, AC4.1–4.3, and AC5.1–5.3 green. Verify no search-vision false positives.

---

## Wave 3 — Observability, Benchmarking & Live Calibration

- [ ] T6 (REQ-6): Implement structured latency logging in `backend/agent/decision_engine.py` recording `scoring_latency_ms`, `args_latency_ms`, `decision_latency_ms`, and `is_fast_path`. — RIPPLE: Observability off the critical path.
- [ ] T7 (REQ-6): Update `scripts/bench_decision_engine.py` and `scripts/calibrate_decision_threshold.py` to assert CPU decision scoring ≤ 180ms and verify zero vision false positives across search question batteries. — RIPPLE: Validates sub-450ms target on local hardware.
- [ ] TG-3 (Wave 3 Gate): Run benchmark battery proving AC6.1–6.3 green. Verify total decision resolution p50 ≤ 450ms.

---

## Wave 4 — Dynamic Composite Recipes & Graph Caching

- [ ] T8 (REQ-7): Implement `DynamicCompositeRecipe` models and pre-flight contract & null validation in `backend/agent/dynamic_recipe.py`, verifying that zero required schema arguments are null/unassigned and artifact kinds match across edges. — RIPPLE: Rejects broken DAGs prior to execution.
- [ ] T9 (REQ-7): Implement dynamic composite materialization in `backend/agent/der_loop.py`, mapping dynamic recipes into batch queue items and propagating dependency parameters via `resolve_dependent_params`. — RIPPLE: Executes arbitrary multi-tool recipes without code changes.
- [ ] T10 (REQ-7): Implement episodic graph registration of verified dynamic recipes into `_NODE_SPECS` as reusable composite nodes (`NodeSpec(composite_of=...)`), enabling sub-450ms Decision Engine reuse on repeat queries. — RIPPLE: Enables native resident fast-path execution of learned composite workflows.
- [ ] TG-4 (Wave 4 Gate): Run unit and behavioral tests proving AC7.1–7.5 green. Verify pre-flight validation catches null parameters and verified recipes execute via letter scoring in ≤ 450ms.

---

## Traceability Matrix (MANDATORY — every AC accounted for)

| REQ | AC | Covering Tasks | Covering Tests | Status |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-1** | AC1.1 | T1 | `tests/unit/test_letter_scoring.py::test_prompt_letter_formatting` | covered |
| **REQ-1** | AC1.2 | T1 | `tests/unit/test_letter_scoring.py::test_single_forward_pass_logits` | covered |
| **REQ-1** | AC1.3 | T1 | `tests/behavioral/test_decision_bench.py::test_cpu_scoring_sub_180ms` | covered |
| **REQ-1** | AC1.4 | T1 | `tests/unit/test_letter_scoring.py::test_no_prefix_tie_breaker_loop` | covered |
| **REQ-2** | AC2.1 | T2 | `tests/unit/test_fast_path_args.py::test_single_slot_query_mapping` | covered |
| **REQ-2** | AC2.2 | T2 | `tests/unit/test_fast_path_args.py::test_bypass_autoregressive_gen` | covered |
| **REQ-2** | AC2.3 | T2 | `tests/unit/test_fast_path_args.py::test_zero_token_generation_time` | covered |
| **REQ-2** | AC2.4 | T2 | `tests/unit/test_fast_path_args.py::test_complex_schema_fallback` | covered |
| **REQ-3** | AC3.1 | T3 | `tests/unit/test_vision_tokens.py::test_whats_token_removed` | covered |
| **REQ-3** | AC3.2 | T3 | `tests/unit/test_vision_tokens.py::test_multi_word_vision_phrase_required` | covered |
| **REQ-3** | AC3.3 | T3 | `tests/behavioral/test_search_routing.py::test_whats_query_routes_to_web` | covered |
| **REQ-4** | AC4.1 | T4 | `tests/unit/test_lane_construction.py::test_lanes_built_pre_cap` | covered |
| **REQ-4** | AC4.2 | T4 | `tests/unit/test_lane_construction.py::test_top_candidate_per_lane` | covered |
| **REQ-4** | AC4.3 | T4 | `tests/behavioral/test_search_routing.py::test_web_lane_never_dropped` | covered |
| **REQ-5** | AC5.1 | T5 | `tests/unit/test_vision_capture.py::test_reuse_vision_server_buffer` | covered |
| **REQ-5** | AC5.2 | T5 | `tests/unit/test_vision_capture.py::test_no_duplicate_screen_capture` | covered |
| **REQ-5** | AC5.3 | T5 | `tests/contract/test_ledger_record.py::test_async_ledger_event_record` | covered |
| **REQ-6** | AC6.1 | T6 | `tests/unit/test_decision_telemetry.py::test_decision_latency_breakdown_log` | covered |
| **REQ-6** | AC6.2 | T7 | `tests/behavioral/test_decision_bench.py::test_bench_decision_engine_suite` | covered |
| **REQ-6** | AC6.3 | T7 | `tests/behavioral/test_calibrate_threshold.py::test_calibration_no_vision_fp` | covered |
| **REQ-7** | AC7.1 | T8 | `tests/unit/test_dynamic_recipe.py::test_brain_recipe_synthesis_dag` | covered |
| **REQ-7** | AC7.2 | T8 | `tests/contract/test_dynamic_recipe_contracts.py::test_artifact_consumes_produces` | covered |
| **REQ-7** | AC7.3 | T8 | `tests/unit/test_dynamic_recipe.py::test_reject_null_or_missing_params` | covered |
| **REQ-7** | AC7.4 | T9 | `tests/behavioral/test_dynamic_recipe_execution.py::test_der_queue_materialization` | covered |
| **REQ-7** | AC7.5 | T10 | `tests/behavioral/test_dynamic_recipe_execution.py::test_graph_cache_and_fast_reuse` | covered |

**Matrix Audit:**
- Counted ACs in requirements.md: 25
- Matrix rows: 25
- Covered: 25
- Deferred: 0
- Unmapped: 0

---

## Dependency & Parallelization Notes

- **Wave 1 vs Wave 2:** Wave 1 (in-process decision engine prompt and parameter logic) and Wave 2 (candidate token pre-filters and vision deduplication) can be developed in parallel.
- **Wave 3 dependencies:** Wave 3 requires Wave 1 and Wave 2 to be green to measure and calibrate true sub-450ms resolution latency.

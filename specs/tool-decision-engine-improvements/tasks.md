# Tasks: Tool Decision Engine Improvements (Sub-450ms Native Latency)

> Each task links to requirements. Waves are dependency-ordered; Wave 0 ~~probes the contested scoring method~~ (**cancelled** — see Wave 8), Wave 1 is engine scoring and parameter generation (~~incl. head-snapshot wiring, T23~~ — **T23 cancelled**), Wave 2 integrates routing and vision deduplication, Wave 3 is verification and calibration (incl. calibration quality, T24), Wave 4 covers dynamic composite recipes, Wave 5 wires extended routing (search tier, examples, vision target) and recovery awareness, Wave 6 adds the new consumers in shadow with per-consumer criteria (T25) and batched scoring (T26), Wave 7 flips enforcement on measured bars, **Wave 8 replaces the model itself — GLiNER2.5-Decide via ONNX supersedes LFM2-350M-Extract (T28–T32)**, **Wave 9 repairs the measurement instruments and the two real reds (T33–T37)**, **Wave 10 tunes the swapped backend against a recorded baseline (T38–T42)**, **Wave 11 lays the read-only evidence seam, unpopulated (T43–T45)**, **Wave 12 completes the decision surface in shadow (T46–T49)**, and **Wave 13 CONFIRMS the operating point against the deployed configuration, firing re-validation only if it moves — TG-7 remains the authoritative enforcement gate (T50–T52, Decision C)**.
>
> **Wave 8 is the highest-priority wave.** It supersedes Wave 0/T1/T23 and should land before the
> Wave 6/7 consumer work is tuned, since every consumer's distribution changes with the backend.
>
> **Wave 9 is the integrity wave and gates everything after it.** Three findings make later
> measurement dishonest if left in place: T31 edits a config value nothing reads, all seven
> Wave 6 consumers depend on an observer seam that returns `None`, and the engine emits no
> latency breakdown. Wave 9 fixes the instruments first. Waves 9 and 8 may run in parallel.
>
> **Progressive verification is the point of Waves 9–13.** Each wave's gate asserts its own
> claim with evidence — a config round-trip, a measured delta against a recorded baseline, an
> inert-when-absent regression check, a re-derived curve — rather than accepting a green suite
> as proof. No wave is measured before its predecessor's gate passes, so the engine is
> verified as it is built and each wave's numbers are trustworthy when the next one starts.

---

## Wave 0 — Scoring-Method Probe — **CANCELLED (superseded by Wave 8)**

- [x] ~~T0 (REQ-1): A/B-probe letter-token vs first-token scoring~~ — **CANCELLED 2026-09-25.** The model decision (REQ-21) removes the option-token read entirely; there is no method to probe. Wave 8 replaces this entire wave.
- [x] ~~TG-0 (Wave 0 Gate): Probe results recorded~~ — **RETIRED.** Superseded by TG-8 (ONNX backend parity).

---

## Wave 1 — Decision Engine Core Scoring & Parameter Fast-Path

- [x] ~~T1 (REQ-1): Implement single-letter candidate option formatting~~ — **CANCELLED 2026-09-25.** Superseded by T28 (ONNX schema scoring). The LFM scoring path is deleted, not modified.
- [ ] T2 (REQ-2): Implement deterministic fast-path slot filling in `backend/agent/decision_engine.py:477-520` for single-parameter query tools (`search`, `crawler_query`), bypassing `generate_args` token generation. — RIPPLE: Eliminates 500–1,500ms autoregressive generation for search tasks. **Note (2026-09-25):** `generate_args` is unaffected by the model swap — the ONNX backend scores labels, it does not generate arguments. This task still stands, but its line refs must be re-checked after T29's deletions.
- [x] ~~T23 (REQ-1): Wire the warm-head KV snapshot~~ — **CANCELLED 2026-09-25.** The head cache was an LFM prompt-prefill optimisation; the ONNX encoder has no autoregressive prompt to cache. T29 deletes `_warm_head_state` outright.
- [ ] TG-1 (Wave 1 Gate): Run unit and contract tests proving AC2.1–2.4 green. ~~AC1.1–1.4 and the head-snapshot clause~~ — **superseded by TG-8** (AC1.3 is carried by REQ-21/T28).

---

## Wave 2 — De-biasing, Lane Construction & Vision Deduplication

- [ ] T3 (REQ-3): Remove isolated token `"what's"` from `_VISION_TOKENS` and enforce multi-word contextual phrases (`"what's on screen"`, `"look at screen"`) in `backend/agent/tool_decision.py:51-65`. — RIPPLE: Prevents factual search queries from falsely triggering vision candidate menus.
- [x] ~~T4 (REQ-4): Refactor hierarchical lane construction in `backend/agent/tool_decision.py` to construct lanes from the full candidate set before applying candidate cap truncation.~~ — **CANCELLED 2026-09-25.** REQ-4 is SUPERSEDED by REQ-22 AC22.3. Verified: `lanes` / `lanes_for_engine` are built at `tool_decision.py:603-609` and consumed at **exactly one** place — `_dt("tool_choice", lanes_for_engine, frame)` (`:613`). With `decide_tree` retired the whole block is dead code, so this task would fix a path that no longer exists. **T29 deletes the block instead.**
- [x] T5 (REQ-5): Deduplicate screenshot capture in `backend/agent/tool_bridge.py` by reusing the image buffer returned from the vision tool instead of executing a second synchronous screen capture. Two sites, not one: `:1709` (vision) and `:1719` (GUI). — RIPPLE: Saves 100–250ms of synchronous thread time per vision action; the GUI site (`:1719`) carries the identical defect and needs an explicit scope decision (extend this task or open a follow-up). **STATUS 2026-09-26 (session 358): AC5.1/5.2 landed (buffer reuse tested). AC5.3 landed — `_record_tool_event` runs FFI ingest on a daemon thread (tool_bridge.py:2204-2206), proven by `tests/contract/test_ledger_record.py::test_async_ledger_event_record`.**
- [ ] TG-2 (Wave 2 Gate): Run tests proving AC3.1–3.3, AC4.1–4.3, and AC5.1–5.3 green. Verify no search-vision false positives.

---

## Wave 3 — Observability, Benchmarking & Live Calibration

- [ ] T6 (REQ-6): Implement structured latency logging in `backend/agent/decision_engine.py` recording `scoring_latency_ms`, `args_latency_ms`, `decision_latency_ms`, and `is_fast_path`. — RIPPLE: Observability off the critical path.
- [ ] T7 (REQ-6): Update `scripts/bench_decision_engine.py` and `scripts/calibrate_decision_threshold.py` to assert CPU decision scoring ≤ 180ms and verify zero vision false positives across search question batteries. — RIPPLE: Validates sub-450ms target on local hardware.
- [ ] T24 (REQ-18): Add reliability-bucket / ECE / Brier measurement to `scripts/calibrate_decision_threshold.py` and resolve `softmax_tau` — replace the fixed sharpening (`decision_engine.py:126`) with a fitted monotone calibration map, or document it as a threshold-shift and stop reporting the sharpened value as a calibrated probability. — RIPPLE: **Blocks every Wave 7 enforcement flip** (AC18.4); proven by CT-DEI-8 and BT-DEI-10.
- [ ] T27 (REQ-6): Record `model_id` + file hash on calibration rows and assert identity at load (glob at `decision_engine.py:143`/`:157-160` is unpinned); emit structured truncation events for the silent cuts at `:374`/`:379`/`:386`; persist the full distribution per decision row. — RIPPLE: AC6.4/6.5/6.6; makes a model swap detectable instead of silently invalidating thresholds.
- [ ] TG-3 (Wave 3 Gate): Run benchmark battery proving AC6.1–6.6 and AC18.1–18.5 green. Verify total decision resolution p50 ≤ 450ms and ECE ≤ 0.05 on the labeled battery.

---

## Wave 4 — Dynamic Composite Recipes & Graph Caching

- [ ] T8 (REQ-7): Implement `DynamicCompositeRecipe` models and pre-flight contract & null validation in `backend/agent/dynamic_recipe.py`, verifying that zero required schema arguments are null/unassigned and artifact kinds match across edges. — RIPPLE: Rejects broken DAGs prior to execution.
- [ ] T9 (REQ-7): Implement dynamic composite materialization in `backend/agent/der_loop.py`, mapping dynamic recipes into batch queue items and propagating dependency parameters via `resolve_dependent_params`. — RIPPLE: Executes arbitrary multi-tool recipes without code changes.
- [ ] T10 (REQ-7): Implement episodic graph registration of verified dynamic recipes into `_NODE_SPECS` as reusable composite nodes (`NodeSpec(composite_of=...)`), enabling sub-450ms Decision Engine reuse on repeat queries. — RIPPLE: Enables native resident fast-path execution of learned composite workflows.
- [ ] TG-4 (Wave 4 Gate): Run unit and behavioral tests proving AC7.1–7.5 green. Verify pre-flight validation catches null parameters and verified recipes execute via letter scoring in ≤ 450ms.

---

## Wave 5 — Extended Routing & Recovery Awareness

- [ ] T11 (REQ-8): Reroute the `search` tool path in `backend/agent/tool_bridge.py:3644-3745` to `backend/crawler/search_providers/` (no subprocess, no LLM planning), keep `crawler_query` on the orchestrator, split registry descriptions, preserve REQ-16 progress/card emits. — RIPPLE: Touches the card event contract (locked by CT-DEI-4); no new provider code.
- [ ] T12 (REQ-9): Add search-vs-research contrast pairs to the prompt head in `backend/agent/decision_engine.py:356-373` and extend the calibration battery with both intent classes + per-class reporting. — RIPPLE: Prompt-only; measured by BT-DEI-5 and calibration. **SUPERSEDED 2026-09-26 (session 357) for the prompt half.** The cited prompt head (`_build_prompt_parts`) was DELETED with the LFM path (T29) — `grep -rn "_build_prompt_parts" backend/agent/` returns zero hits. The ONNX backend scores a schema `Task` whose instruction is pinned byte-identical to the measured bench shape (`_TASK_INSTRUCTION`, `decision_backend_onnx.py:46`), so adding worked examples would change the distribution the 0.40 threshold was measured on and force AC25.5/AC31.4 to mark it STALE — satisfying the AC would DISABLE enforcement. The battery half (AC9.2 per-class reporting) is covered by `tests/behavioral/test_calibrate_threshold.py::test_per_class_accuracy_report`; AC9.3 by `tests/behavioral/test_search_routing.py::test_no_heuristic_override_above_threshold`. `tests/unit/test_prompt_examples.py` is deliberately NOT created.
- [ ] T13 (REQ-10): Implement quoted-target regex fast-path for `vision_detect_element` with LLM fallback and `is_fast_path` logging. — RIPPLE: Vision dispatch only; never changes fallback behavior.
- [ ] T14 (REQ-11): Plumb failure evidence (`failed_tool`, `error_snippet`) from the graft failure path into `ToolDecisionBox.resolve()` frame as `ruled_out`; veto survives `reset_failure_counters`. — RIPPLE: Resolve signature gains an optional param (default empty = today's behavior); contract-locked by CT-DEI-5. **STATUS 2026-09-26 (session 357): box-side was landed, CALLER-SIDE WAS MISSING AND IS NOW WIRED.** ⚠️ **The original line citations were FABRICATED (BLUEPRINT-DIVERGENT):** `agent_kernel.py:12986` is `_split_step`'s child `NodeRecord` construction and `:15012-15031` is the `_get_tool_box()` construction site — neither contains graft plumbing, and `grep -n "failed_tool\|error_snippet" backend/agent/agent_kernel.py` returned **ZERO hits**, so the caller side never existed. The real seam is `_der_handle_step_failure` (`agent_kernel.py:11917`) — the ONE failure-triage point (called from both the main step loop and the extra-step loop). Wiring landed: (a) `ToolDecisionBox.note_failure(objective, failed_tool)` — the seeding-only half, no engine call; (b) the `resolve()` call site now passes `"objective_anchor"`, so the veto KEY matches across parent→graft (graft children inherit `objective_anchor` — `der_loop.py:230` — but carry a NEW description, so keying on the description made the veto unreachable for the very graft it protects). Proven by `tests/contract/test_recovery_evidence_contract.py::TestFailureTriageSeamWired`.
- [ ] T15 (REQ-11): Register the `recovery_strategy` engine consumer and consult it in graft paths before Brain planning spend; double-consecutive same-tool failure escalates. — RIPPLE: Needs Wave 1 green (stable scoring); proven by BT-DEI-6.
- [ ] T16 (REQ-12): Move `sr.resolve` off the DER thread (`run_coroutine_threadsafe` + bounded TTL cache, budget fallback) in `agent_kernel.py:14507-14656`. — RIPPLE: Pre-filter only; late-attach path must not mutate the current decision.
- [ ] TG-5 (Wave 5 Gate): Run tests proving AC8.1–8.4, AC9.1–9.3, AC10.1–10.3, AC11.1–11.5, AC12.1–12.3 green (CT-DEI-4/5, BT-DEI-5/6/7). Verify quick-search total ≤ 800ms and zero repeat-tool grafts on the battery.

---

## Wave 6 — New-Consumer Foundation (Shadow-First, Nothing Enforced)

> Foundation rule (D7): every task below wires its consumer in shadow mode — rows flow, legacy code decides. No enforcement flip lives in this wave.

- [ ] T17 (REQ-13): Register the `review_verdict` consumer and shadow-score it in the Reviewer over envelope-view inputs; Brain keeps verdict duty and all `refined`-text duty. — RIPPLE: Reviewer semantics locked; ledger gains rows only. **WIRED 2026-09-26 (session 357):** the machinery and its tests had landed, but NOTHING in production called them — `monitor_shadow` was imported nowhere outside itself, and `Reviewer.set_review_engine` / `ModeDetector.set_mode_engine` were defined and never invoked, so these consumers were INERT and TG-6's parity clause was unreachable. Call sites now wired: `AgentKernel.__init__` (`agent_kernel.py:773`) now calls `self._reviewer.set_review_engine(get_decision_engine())`.
- [ ] T18 (REQ-14): Register `sufficient` / `done` / `on_track` bool consumers and shadow-score them at the three monitor sites; Brain calls unchanged; goal-contract done-override preserved. — RIPPLE: Three call sites, one shared envelope; advisory-fail-closed shape kept. **WIRED 2026-09-26 (session 357):** the machinery and its tests had landed, but NOTHING in production called them — `monitor_shadow` was imported nowhere outside itself, and `Reviewer.set_review_engine` / `ModeDetector.set_mode_engine` were defined and never invoked, so these consumers were INERT and TG-6's parity clause was unreachable. Call sites now wired: `sufficient` at `agent_kernel.py:13525` (`_der_findings_sufficient`, via `monitor_shadow.sufficiency_gate`), `done` at `:18457` (the Explorer done-bit), `on_track` at `:18564` (the FULL-mode drift check). `monitor_shadow` gained `set_row_sink`/`emit_row` so rows reach a ledger rather than being discarded.
- [ ] T19 (REQ-15): Register `mode` + `web_intent` consumers shadowing `ModeDetector` and the three web-trigger copies; slash overrides, IMPLEMENT default, and keyword fallback preserved. — RIPPLE: Deletes duplicated lists only after the fold proves parity. **WIRED 2026-09-26 (session 357):** the machinery and its tests had landed, but NOTHING in production called them — `monitor_shadow` was imported nowhere outside itself, and `Reviewer.set_review_engine` / `ModeDetector.set_mode_engine` were defined and never invoked, so these consumers were INERT and TG-6's parity clause was unreachable. Call sites now wired: `web_intent` was already live via `explorer._is_web_intent`; `AgentKernel.__init__` (`agent_kernel.py:794`) now calls `self._mode_detector.set_mode_engine(get_decision_engine())` so AC15.2's measured confidence is reachable.
- [ ] T20 (REQ-16): Score engine Choice in `propose()` before the Brain single-shot; route or shadow-record RespondDirect tool calls through the box. — RIPPLE: Fast chat path gets shadow-record only, zero added latency.
- [ ] T21 (REQ-17): Extend `recovery_strategy` with `retry_same` and consult it in shadow at each failure triage point; counters keep deciding. — RIPPLE: Needs Wave 1 + Wave 5 green; touches triage only as an observer. **LANDED + WIRED 2026-09-26 (session 357).** `_RECOVERY_STRATEGIES` gained `retry_same` (AC17.1); `recovery_strategy()` now ALWAYS records a shadow triage row (`box.last_triage_shadow`) pairing the engine verdict with `counter_choice`; a confident `retry_same` NEVER steers (AC17.2 — it is recorded then discarded, so the counters keep owning retry-vs-graft). **The "each failure triage point" clause is now REAL:** `_der_handle_step_failure` calls `recovery_strategy()` in shadow before the recovery sub-graph is planned. Without that wiring the consumer was INERT (no production caller) and TG-6's first clause plus Wave 7's ≥100-row flip bar were structurally unreachable. AC11.4 precedence is honoured: the deterministic double-failure escalate pays NO model call and records no row — sanctioned by REQ-17's own Edge Cases ("safety overrides calibration"). Tests: `tests/contract/test_verdict_consumer_shape.py::test_triage_shadow_row`, `tests/unit/test_triage_shadow.py::test_counters_still_decide`, `tests/contract/test_recovery_evidence_contract.py::TestFailureTriageSeamWired`.
- [ ] T25 (REQ-19): Register per-consumer head specs (instructions + worked example + option criteria) and maintain a per-consumer cached KV state (LRU-bounded); refuse to score a consumer with no criteria rather than borrowing another consumer's head. — RIPPLE: **Lands BEFORE T17–T21** — every new consumer would otherwise be scored under the tool-selection head (`decision_engine.py:356-373`, warmed only for `"tool_choice"` at `:304`) with zero criteria, which is the likeliest cause of a BT-DEI-8 parity failure. `tool_choice` behavior regression-guarded (AC19.4); CT-DEI-9.
- [ ] T26 (REQ-20): Add the batched multi-question scoring entry point (N typed questions, one state, one pass) with per-question isolation and graceful degradation to the existing per-consumer path. — RIPPLE: Keeps Wave 6's six new consumers from multiplying loop latency; CT-DEI-10, BT-DEI-11.
- [ ] TG-6 (Wave 6 Gate): All six new consumers emit well-formed rows (CT-DEI-6/7 green) **and are scored against their own head criteria (CT-DEI-9)**; legacy decisions unchanged on the battery (parity check runs, enforcement off); batched path returns envelopes identical to the per-consumer path (CT-DEI-10).

---

## Wave 7 — Enforcement Optimization (Measured Flips Only)

> Optimize rule (D7/D8): a consumer flips to enforced if and only if its gate bar holds — ≥ 50 rows at P(correct | conf ≥ threshold) ≥ 0.90. Positive-path Brain calls are skipped; negative-branch prose stays on the Brain.

- [ ] T22 (REQ-13–17): Flip each Wave 6 consumer that passes its bar to enforced; wire Brain-text-only on negative branches (refine/insufficient/not-done/drifted); measure per-consumer skip rates and Brain-token savings (BT-DEI-8/9/10). A consumer flips only when BOTH precision ≥ 0.90 over ≥ 100 rows AND ECE is within bound — no flip on precision alone. Consumers below bar stay shadow with the gap logged — no forced flips.
- [ ] TG-7 (Wave 7 Gate): BT-DEI-8 parity ≥ 0.90 per flipped consumer; **BT-DEI-10 reports ECE ≤ bound for every flipped consumer**; BT-DEI-9 reports skip rates + savings with zero routing regressions vs the TG-6 baseline. Unflipped consumers list their missing data explicitly.
  - **AUTHORITATIVE (Decision C, 2026-09-25):** this gate remains the authoritative enforcement gate. `candidate_cap` ships at **6** — the width the 0.40 curve was derived at (REQ-25 AC25.7) — so the calibration stays valid and these flips STAND. They are invalidated only if the cap, backend, or deployed variant moves, at which point AC25.5 marks the threshold stale and TG-13 re-validates or reverts to shadow (REQ-31 AC31.6).

---

## Wave 8 — ONNX Backend Migration (REQ-21, REQ-22) — **the model swap**

> Decided 2026-09-25 on measured evidence (`BENCH-2026-09-25-model-comparison.md`). GLiNER2.5-Decide
> via ONNX **replaces** LFM2-350M-Extract with **no fallback model**. Wave 8 supersedes Wave 0,
> T1 and T23 — see the cancellation note below.

- [ ] T28 (REQ-21): Vendor the torch-free ONNX runner and add `backend/agent/decision_backend_onnx.py` — a `GlinerOnnx` wrapper returning the **unchanged `DecisionScore` envelope**, one schema `Task` per consumer, `onnxruntime` `CPUExecutionProvider`, `None` on any failure. — RIPPLE: Ports the reference `gliner_onnx.py` (`encode`/`logits`/`probabilities`); no caller changes (AC21.2); CT-DEI-11. **+ AC21.8 / CT-DEI-18:** prove the PRODUCTION menu (`tool_decision.py:617-621` — registry names + `DELEGATE`/`NONE` after pre-filter and cap) scores correctly at the shipped width of 6, with no duplicate labels and both control labels surviving the cap. The 60-case battery builds its own fixture-driven menu (`bench_decision_models.py:102-103`), so its parity result covers the menu SHAPE, not the production composition code — do not treat BT-DEI-13 as covering this.
- [ ] T29 (REQ-21 AC21.6): Delete the LFM machinery — `_score_options_one_pass` (`decision_engine.py:396-454`), `_letter_token_ids` (`:218`, `:315-319`), `_warm_head_state` (`:293-321`), `softmax_tau` (`:126`), `decide_tree` for tool choice (`:517-605`), `resolve_model_path`'s GGUF glob (`:143`, `:157-184`), the LFM-only config fields (`n_gpu_layers`, `hierarchy_trigger`, `max_answer_tokens`) and the `IRIS_DECISION_GPU_LAYERS` env knob. **Keep** the `DecisionScore`/`ArgsResult` envelope and `gate()`. — RIPPLE: **⚠️ Deletion, not dormancy, and three traps the obvious check misses.** (1) **`decide_tree` has three callers, and none is an `import`** — a grep for imports finds none of them: `tool_decision.py:611` (guarded by `getattr(..., None)` + `callable()`, so it silently falls through to flat `decide` — the DESIRED end state, but the dead branch and the whole lane block `:590-620` must be removed with it), plus **two scripts that will raise `AttributeError`**: `scripts/bench_decision_models.py:166` and `scripts/run_engine_calibration.py:125` — the latter is the project's own calibration-row generator, so it must be migrated to flat `decide` in the same task or the calibration path dies with it. (2) The lane block (`name_to_cat` `:598`, `_pre_cap_count > _cap` `:610`) becomes dead once `decide_tree` goes — delete it (this is what cancelled T4). (3) Verify no other module imports the removed symbols by ATTRIBUTE as well as by name.
- [ ] T30 (REQ-21 AC21.5): Declare `onnxruntime` and `tokenizers` in `requirements.txt` (both installed but undeclared); add the ONNX model directory to `agent_config.yaml` `decision_driver` with a startup availability check that degrades cleanly. — RIPPLE: `llama-cpp-python` stays (8+ other modules). **CORRECTED 2026-09-25:** the fate of `candidate_cap: 32` is no longer an open question here — it is owned by **T35 (REQ-25)**, which makes the whole `decision_driver` block live. T30 adds the model-dir key; T35 makes the block authoritative. Also note the ONNX model currently sits at `C:\temp\gliner-onnx` — **outside the repo**, so T30 must name a shippable install location, not only declare the dependencies.
- [ ] T31 (REQ-22): Set the `tool_choice` threshold to **0.40** via the active backend's `backend_thresholds` entry, remove the deprecated `default_threshold` key, and extend `scripts/calibrate_decision_threshold.py` to report the coverage/accuracy-above-threshold curve so the operating point is re-derivable. — RIPPLE: **⚠️ THREE threshold sources must be reconciled, not one (REQ-22 AC22.1).** (1) `ToolDecisionBox.__init__(decision_threshold=0.85)` (`tool_decision.py:333`, stored `:370`) is what `tool_choice` **actually reads** (`:639`, `:678`, `:700`) and is **never passed** at its single construction site (`agent_kernel.py:14967`) — it is hardcoded 0.85. (2) `EngineConfig.default_threshold` (`decision_engine.py:109`) drives `presentation`/`narration` via `threshold_for()` (`:136-137`). (3) `EngineConfig.thresholds` per-consumer overrides sit on top. **`EngineConfig.default_threshold` is NOT the tool_choice threshold** — editing it (or the YAML) alone would tune the wrong consumers and leave tool_choice at 0.85. Thresholds are distribution-specific; BT-DEI-14.
- [ ] T32 (REQ-21 AC21.7, REQ-22 AC22.5): Record the backend identity and the deployed ONNX variant on the decision envelope/ledger so calibration rows are attributable and a variant swap marks thresholds stale. — RIPPLE: CT-DEI-12; keeps historical LFM rows distinguishable.
- [ ] TG-8 (Wave 8 Gate): **BT-DEI-13** green — ONNX backend ≥70% accuracy, ≥99% above the 0.40 threshold, p50 ≤180ms on the 60-case battery (incumbent: 60.0% / 70.8% / 1172ms, so a regression fails). CT-DEI-11/12 green. `llama_cpp` import removed from `decision_engine.py`; engine returns `None` cleanly with the model dir absent.

### Superseded tasks (cancelled inline in their original waves)

T0 and TG-0 (Wave 0), T1 and T23 (Wave 1) are marked cancelled **in place** above, so their
history stays visible where it was written. In summary: the model decision (REQ-21) removes the
option-token read, so there is no scoring-method probe to run (T0/TG-0), no lettered scoring to
implement (T1), and no LFM prompt head to cache (T23 — T29 deletes `_warm_head_state`). TG-1's
head-snapshot clause is superseded by TG-8.

---

## Wave 9 — Foundation Integrity (the measurement instruments)

> **Why this wave exists and why it is first.** Three findings make every later wave's
> measurement dishonest if left in place: T31 edits a config value nothing reads (REQ-25);
> all seven Wave 6 consumers depend on an observer seam that returns `None` (REQ-23); and the
> engine emits no latency breakdown, so no Wave 10 optimisation could be attributed to a stage
> (REQ-26). Wave 9 fixes the instruments, then gates. **T30's open question about the unwired
> `candidate_cap: 32` is owned by T35 from here on.**

- [ ] T33 (REQ-23): Fix `AgentKernel._engine_gate_surface` — return the engine verdict when the consumer is not enforced, remove the `_last_render_emitted` early return so card turns still yield an observer verdict, make `card_already_rendered` truthful, and delete the `_last_surface_choice` writes. — RIPPLE: `_observe_surface_async` (`agent_kernel.py:14304`) is the likely verdict consumer (OQ-DEI-6); **all seven Wave 6 consumers share this observer pattern**, so this must be green before T17–T21; the two RED tests (`test_decision_engine_gates.py:241,267`) must go green **without being edited** (TEST RULE). CT-DEI-13.
- [ ] T34 (REQ-24): Fix `_get_failure_warnings` — build the failure dict from recorded session state and pass a `Dict` to `encode_with_resolution`; settle the return type as `str`; log a non-recoverable error with its exception type instead of silently returning `"None"`; align the six test stubs. — RIPPLE: restores the upstream for REQ-11's `ruled_out` veto; callers at `agent_kernel.py:6296` and `:9067`; `test_narration_beats_behavior.py:70` currently stubs `[]` while four others stub `"None"`. CT-DEI-14.
- [ ] T35 (REQ-25): Parse the `decision_driver` block into `EngineConfig`; expose the effective configuration; every documented key parsed or removed. Parse `backend_thresholds` and resolve the threshold by **ACTIVE BACKEND IDENTITY**, refusing enforcement (fail-closed) when the active backend has no entry. — RIPPLE: T31 must not land before this or it is a no-op; AC25.5 makes a cap change STALE the calibrated threshold (coupling to T31/T50); `ToolDecisionBox` reads the effective cap via `engine._cfg.candidate_cap` (`tool_decision.py:534`). **AC25.8 REMOVES the ordering hazard** — with backend-keyed thresholds, T35 and T28/T31 may land in EITHER order without a parsed 0.85 reaching a GLiNER backend, because the backend/threshold pairing is validated at runtime rather than by task order. Changing `threshold_for`'s resolution ripples to **four** call sites: `agent_kernel.py:14272`/`:14279`, `narration.py:269`, and `iris_gateway.py:3907`/`:3913`/`:3935`. CT-DEI-16.
- [ ] T36 (REQ-26): Add a bounded acquire to every engine entry point (`generate_args` currently uses a bare `with self._lock`, `decision_engine.py:657`) and emit `scoring_latency_ms` / `args_latency_ms` / `decision_latency_ms` with lock-wait separated from compute. — RIPPLE: **Waves 10 and 13 measure with these fields**; makes REQ-6 AC6.1 implementable for the first time (0 grep hits today).
- [ ] T37 (REQ-27): Include an evidence component in the `_engine_cache` key (empty sentinel until REQ-28 supplies a payload) and bound the cache with a documented maximum and eviction policy. — RIPPLE: **must land before T43**, or the prior is silently swallowed on a cache hit; the dict is unbounded today (`tool_decision.py:379`, 3 grep hits, no eviction). CT-DEI-17.
- [ ] TG-9 (Wave 9 Gate): **BT-DEI-15** green — the recorded baseline matches reality, the two presentation-observer reds are GREEN (fixed, not edited), and the `title` pin is extended. CT-DEI-13/14/16/17 green. A config round-trip proves a non-default value actually takes effect, and the three latency fields emit on a real decision. A green suite alone does NOT satisfy this gate.

---

## Wave 10 — Post-Swap Engine Performance (measured against a recorded baseline)

> Depends on **Wave 8** (the ONNX backend must exist to tune) and **Wave 9** (the breakdown must
> exist to measure). Every task here is measured, not assumed.

- [ ] T38 (REQ-30 AC30.1): Set explicit ORT session options (`intra_op_num_threads`, `inter_op_num_threads`, `graph_optimization_level`, `execution_mode`) sized to the host CPU, and record the effective values. — RIPPLE: the reference runner sets only an optional `intra_op_num_threads` (`gliner_onnx.py:51-55`) and the bench never passes it, so defaults apply today.
- [ ] T39 (REQ-30 AC30.2): Cache label positions per label set instead of re-tokenizing per call. — RIPPLE: the LFM path warmed `_letter_token_ids` and never read them (`decision_engine.py:315-319`); the same idea applies to the ONNX label positions.
- [ ] T40 (REQ-30 AC30.3): Verify that a batched multi-consumer call performs ONE encode and ONE session run — measured, not assumed. — RIPPLE: REQ-20 claims this natively; the reference runner builds structure tokens per `Task`, so the claim needs verification.
- [ ] T41 (REQ-30 AC30.4): Warm up at the effective `candidate_cap` width rather than the current 2-option menu. — RIPPLE: needs T35's parsed config; `main.py:847-870` warms with `["NONE","DELEGATE"]` while real menus are 6+.
- [ ] T42 (REQ-30 AC30.5): Run inference off the shared step threads (dedicated executor) so step scheduling cannot contend with it. — RIPPLE: `resolve` already runs on a daemon worker or executor (`agent_kernel.py:9421`, `:15690`); the engine lock currently serializes against them.
- [ ] TG-10 (Wave 10 Gate): **BT-DEI-19** green — each change measured against the recorded Wave 8 baseline, **BT-DEI-13 re-run green** (no accuracy regression), the per-stage breakdown reported (CT via AC30.6), and any p95 regression recorded AND reverted rather than kept.

---

## Wave 11 — Evidence Seam (foundational; ships UNPOPULATED)

> REQ-28 exists so that `specs/wormhole-aperture/` can plug in later **without engine changes**.
> Wormhole is NOT implemented and nothing here may assume it. No caller supplies a payload in
> this spec's scope, and absent-evidence behaviour must be byte-identical to today.

- [ ] T43 (REQ-28 AC28.1, AC28.2, AC28.8): Add the `evidence` field to the engine frame, shaped to carry the posterior LOWER BOUND, its observation count, its scope (region + mediator), and its freshness. Ships unpopulated. — RIPPLE: `ToolDecisionBox` frame construction; today the hint only arrives as a filter/veto/short-circuit (`tool_decision.py:513-514`, `:664-665`, `:1015-1020`).
- [ ] T44 (REQ-28 AC28.4): Add the read-only contract test asserting ZERO writes to the memory/graph store from any engine decision path. — RIPPLE: pins the owner decision that the engine never feeds the pheromone loop; the `tool_choice` edge writes stay with the execution layer (`record_region_mediator_outcome`, `agent_kernel.py:16143`). CT-DEI-15.
- [ ] T45 (REQ-28 AC28.3, AC28.6, AC28.7): Make evidence a WEIGHTED PRIOR that the engine's own evidence can outvote and that cannot raise a candidate above the threshold alone; record present-vs-used separately so an unused retrieval is never scored as a success. — RIPPLE: needs T37's cache key and T43's field; proven by BT-DEI-18.
- [ ] TG-11 (Wave 11 Gate): **BT-DEI-18** green — absent evidence is byte-identical to today (regression guard), present evidence reorders candidates but cannot cross the threshold on its own, present-vs-used are recorded separately, and **CT-DEI-15** confirms zero graph writes. T37's key test confirms two payloads do not collide.

---

## Wave 12 — Surface Completion (shadow-first, nothing enforced)

> Foundation rule (D7): rows flow, legacy code decides. Four consumers, no enforcement.

- [ ] T46 (REQ-29 AC29.1): Register a `has_gaps` consumer shadowing `trailing_director`, with the Brain still writing gap items only when the engine scores positive. — RIPPLE: `trailing_director.py:100` spends an 800-token Brain call **per completed step** when the common case needs only a negative bool — the highest-value miss on the whole surface.
- [ ] T47 (REQ-29 AC29.2): Register a `use_thinking` bool consumer shadowing the phrase list, retaining the list as the engine-unavailable fallback. — RIPPLE: `agent_kernel.py:2411`.
- [ ] T48 (REQ-29 AC29.3): Register an `escalate_incomplete` bool consumer shadowing the keyword list. Escalation and all budget/veto-cap safety behaviour UNCHANGED — the engine may never permit. — RIPPLE: `der_loop.py:513`; `BUDGET_ABSOLUTE_MIN` (`:480`) and the budget-ratio escalate (`:531`) stay deterministic.
- [ ] T49 (REQ-29 AC29.4, AC29.5): Register a `needs_action` consumer shadowing the `NONE`-gate heuristics, preserving their documented SAFE direction (when in doubt, act); do NOT touch `tier0_classify` (recorded non-fit). — RIPPLE: `tool_decision.py:55/99/124` gate the engine's own `NONE` commit.
- [ ] TG-12 (Wave 12 Gate): all four consumers emit well-formed rows (CT-DEI-6 shape), legacy decisions are unchanged on the battery (parity runs, enforcement off), `tier0_classify` is untouched, and engine-unavailable behaviour is identical to today at all four sites.

---

## Wave 13 — Operating-Point CONFIRMATION (conditional re-validation) — Decision C

> **Decision C (owner, 2026-09-25): TG-7 remains the authoritative enforcement gate.** The
> `decision_driver` block becomes live (REQ-25) but ships `candidate_cap: 6` — the width the
> 0.40 curve was derived at — so the calibration stays valid and **settled flips are NOT
> re-litigated**. Wave 13 therefore CONFIRMS the operating point and fires re-validation only
> if the cap, backend, or deployed variant actually moves. The menu-width study is DEFERRED,
> not dropped: specified and ready, firing only when a width change is proposed.

- [ ] T50 (REQ-31 AC31.1, AC31.2, AC31.4): CONFIRM the recorded operating point against the deployed backend, cap, and variant — reporting ECE + Brier alongside precision — and mark thresholds stale / refuse enforcement only when the deployed configuration differs from the calibrated one. — RIPPLE: needs T35 (live config) and T36 (attribution); `calibrate_decision_threshold.py` is the instrument. A match is a confirmation, not a silent assumption. BT-DEI-20.
- [ ] T51 (REQ-31 AC31.3) — **DEFERRED (Decision C)**: the menu-width study fires only when a width change is actually proposed. Measure accuracy and latency across at least two widths and record the optimum BEFORE the change ships. — RIPPLE: `candidate_cap` ships at 6, so there is no second width to compare against at the shipped configuration; running the study unrequested would be over-build. Mirrors the `Decisions Locked 14` pattern (specified, gated, not early).
- [ ] T52 (REQ-31 AC31.5, AC31.6): Record the measured bar (rows, precision, ECE) per consumer — the evidence trail behind each enforcement decision — and CONFIRM that no flip was measured at a superseded configuration. Re-validation (and revert-to-shadow) fires ONLY if the configuration moved. — RIPPLE: adds REQ-29's four consumers to the bar record; T22 keeps the flip authority for REQ-13–17 unless the configuration changed.
- [ ] TG-13 (Wave 13 Gate): **BT-DEI-20** green — the operating point is CONFIRMED against the deployed configuration with the numbers recorded, ECE is within bound, every consumer's status is recorded (flipped or shadow-with-gap), and **no consumer is enforced on a curve measured at a superseded configuration**. If the configuration is unchanged since Wave 7, this gate CONFIRMS and closes — it does not re-open flips. If it moved, BT-DEI-8/9/10 re-run and any flip that fails re-validation reverts to shadow.

---

## Traceability Matrix (MANDATORY — every AC accounted for)

| REQ | AC | Covering Tasks | Covering Tests | Status |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-1** | AC1.1 | — | — | **superseded** (REQ-21) |
| **REQ-1** | AC1.2 | — | — | **superseded** (REQ-21) |
| **REQ-1** | AC1.3 | T28 | `tests/behavioral/test_decision_bench.py::test_cpu_scoring_sub_180ms` (BT-DEI-13) | carried by REQ-21 |
| **REQ-1** | AC1.4 | — | — | **superseded** (REQ-21) |
| **REQ-2** | AC2.1 | T2 | `tests/unit/test_fast_path_args.py::test_single_slot_query_mapping` | covered |
| **REQ-2** | AC2.2 | T2 | `tests/unit/test_fast_path_args.py::test_bypass_autoregressive_gen` | covered |
| **REQ-2** | AC2.3 | T2 | `tests/unit/test_fast_path_args.py::test_zero_token_generation_time` | covered |
| **REQ-2** | AC2.4 | T2 | `tests/unit/test_fast_path_args.py::test_complex_schema_fallback` | covered |
| **REQ-3** | AC3.1 | T3 | `tests/unit/test_vision_tokens.py::test_whats_token_removed` | covered |
| **REQ-3** | AC3.2 | T3 | `tests/unit/test_vision_tokens.py::test_multi_word_vision_phrase_required` | covered |
| **REQ-3** | AC3.3 | T3 | `tests/behavioral/test_search_routing.py::test_whats_query_routes_to_web` | covered |
| **REQ-4** | AC4.1 | — | — | **superseded** (REQ-22 AC22.3) |
| **REQ-4** | AC4.2 | — | — | **superseded** (REQ-22 AC22.3) |
| **REQ-4** | AC4.3 | — | — | **superseded** (REQ-22 AC22.3) |
| **REQ-5** | AC5.1 | T5 | `tests/unit/test_vision_capture.py::test_reuse_vision_server_buffer` | covered |
| **REQ-5** | AC5.2 | T5 | `tests/unit/test_vision_capture.py::test_no_duplicate_screen_capture` | covered |
| **REQ-5** | AC5.3 | T5 | `tests/contract/test_ledger_record.py::test_async_ledger_event_record` | covered |
| **REQ-6** | AC6.1 | T6 | `tests/unit/test_decision_telemetry.py::test_decision_latency_breakdown_log` | covered |
| **REQ-6** | AC6.2 | T7 | `tests/behavioral/test_decision_bench.py::test_bench_decision_engine_suite` | covered |
| **REQ-6** | AC6.3 | T7 | `tests/behavioral/test_calibrate_threshold.py::test_calibration_no_vision_fp` | covered |
| **REQ-6** | AC6.4 | T27 | `tests/unit/test_decision_telemetry.py::test_distribution_persisted_per_row` | covered |
| **REQ-6** | AC6.5 | T27 | `tests/contract/test_model_pin.py::test_model_identity_matches_calibration_rows` | covered |
| **REQ-6** | AC6.6 | T27 | `tests/unit/test_decision_telemetry.py::test_truncation_event_emitted` | covered |
| **REQ-7** | AC7.1 | T8 | `tests/unit/test_dynamic_recipe.py::test_brain_recipe_synthesis_dag` | covered |
| **REQ-7** | AC7.2 | T8 | `tests/contract/test_dynamic_recipe_contracts.py::test_artifact_consumes_produces` | covered |
| **REQ-7** | AC7.3 | T8 | `tests/unit/test_dynamic_recipe.py::test_reject_null_or_missing_params` | covered |
| **REQ-7** | AC7.4 | T9 | `tests/behavioral/test_dynamic_recipe_execution.py::test_der_queue_materialization` | covered |
| **REQ-7** | AC7.5 | T10 | `tests/behavioral/test_dynamic_recipe_execution.py::test_graph_cache_and_fast_reuse` | covered |

| **REQ-8** | AC8.1 | T11 | `tests/contract/test_search_tier_contract.py::test_provider_path_no_subprocess` | covered |
| **REQ-8** | AC8.2 | T11 | `tests/behavioral/test_quick_search.py::test_provider_latency_and_frames` | covered |
| **REQ-8** | AC8.3 | T11 | `tests/contract/test_search_tier_contract.py::test_crawler_path_unchanged` | covered |
| **REQ-8** | AC8.4 | T11 | `tests/contract/test_search_tier_contract.py::test_registry_descriptions_split` | covered |
| **REQ-9** | AC9.1 | T12 | — | **superseded** (ONNX swap: no prompt head; see the AC) |
| **REQ-9** | AC9.2 | T12 | `tests/behavioral/test_calibrate_threshold.py::test_per_class_accuracy_report` | covered |
| **REQ-9** | AC9.3 | T12 | `tests/behavioral/test_search_routing.py::test_no_heuristic_override_above_threshold` | covered |
| **REQ-10** | AC10.1 | T13 | `tests/unit/test_vision_target.py::test_regex_target_zero_tokens` | covered |
| **REQ-10** | AC10.2 | T13 | `tests/unit/test_vision_target.py::test_fallback_on_no_match` | covered |
| **REQ-10** | AC10.3 | T13 | `tests/unit/test_decision_telemetry.py::test_fast_path_pattern_logged` | covered |
| **REQ-11** | AC11.1 | T14 | `tests/contract/test_recovery_evidence_contract.py::test_ruled_out_in_frame` | covered |
| **REQ-11** | AC11.2 | T14 | `tests/unit/test_recovery_veto.py::test_vetoed_tool_zero_probability` | covered |
| **REQ-11** | AC11.3 | T15 | `tests/behavioral/test_graft_recovery.py::test_strategy_gate_before_brain` | covered |
| **REQ-11** | AC11.4 | T15 | `tests/behavioral/test_graft_recovery.py::test_double_failure_escalates` | covered |
| **REQ-11** | AC11.5 | T14 | `tests/contract/test_recovery_evidence_contract.py::test_meta_carries_recovery_fields` | covered |
| **REQ-12** | AC12.1 | T16 | `tests/unit/test_mem_lookup.py::test_no_asyncio_run_on_der_thread` | covered |
| **REQ-12** | AC12.2 | T16 | `tests/behavioral/test_mem_lookup_budget.py::test_prefilter_latency_budget` | covered |
| **REQ-12** | AC12.3 | T16 | `tests/unit/test_mem_lookup.py::test_over_budget_late_attach` | covered |

| **REQ-13** | AC13.1 | T17 | `tests/contract/test_verdict_consumer_shape.py::test_review_verdict_shadow_row` | covered |
| **REQ-13** | AC13.2 | T17 | `tests/unit/test_reviewer_split.py::test_brain_writes_refined_text` | covered |
| **REQ-13** | AC13.3 | T22 | `tests/behavioral/test_consumer_parity.py::test_verdict_enforcement_bar` | covered |
| **REQ-13** | AC13.4 | T22 | `tests/behavioral/test_brain_spend.py::test_review_token_savings` | covered |
| **REQ-14** | AC14.1 | T18 | `tests/contract/test_verdict_consumer_shape.py::test_monitor_bool_shadow_rows` | covered |
| **REQ-14** | AC14.2 | T18 | `tests/unit/test_monitor_split.py::test_brain_text_on_negative_branch` | covered |
| **REQ-14** | AC14.3 | T22 | `tests/behavioral/test_consumer_parity.py::test_bool_skip_positive_path` | covered |
| **REQ-14** | AC14.4 | T18 | `tests/unit/test_monitor_split.py::test_sufficiency_fail_closed` | covered |
| **REQ-14** | AC14.5 | T22 | `tests/behavioral/test_brain_spend.py::test_monitor_skip_rates` | covered |
| **REQ-14** | AC14.6 | T25 | `tests/unit/test_noul_envelope.py::test_noul_single_calibrated_probability` | covered |
| **REQ-15** | AC15.1 | T19 | `tests/behavioral/test_mode_routing.py::test_slash_overrides_win` | covered |
| **REQ-15** | AC15.2 | T19 | `tests/contract/test_verdict_consumer_shape.py::test_mode_confidence_measured` | covered |
| **REQ-15** | AC15.3 | T19 | `tests/unit/test_web_intent_fold.py::test_single_consumer_no_copies` | covered |
| **REQ-15** | AC15.4 | T22 | `tests/behavioral/test_consumer_parity.py::test_heuristic_enforcement_bar` | covered |
| **REQ-16** | AC16.1 | T20 | `tests/behavioral/test_propose_path.py::test_engine_before_brain` | covered |
| **REQ-16** | AC16.2 | T20 | `tests/contract/test_no_bypass.py::test_all_paths_emit_rows` | covered |
| **REQ-16** | AC16.3 | T22 | `tests/behavioral/test_brain_spend.py::test_propose_no_brain_share` | covered |
| **REQ-17** | AC17.1 | T21 | `tests/contract/test_verdict_consumer_shape.py::test_triage_shadow_row` | covered |
| **REQ-17** | AC17.2 | T21 | `tests/unit/test_triage_shadow.py::test_counters_still_decide` | covered |
| **REQ-17** | AC17.3 | T22 | `tests/behavioral/test_consumer_parity.py::test_triage_enforcement_bar` | covered |

| **REQ-18** | AC18.1 | T24 | `tests/unit/test_calibration_quality.py::test_reliability_ece_brier_computed` | covered |
| **REQ-18** | AC18.2 | T24 | `tests/behavioral/test_calibrate_threshold.py::test_ece_reported_with_precision` | covered |
| **REQ-18** | AC18.3 | T24 | `tests/unit/test_calibration_quality.py::test_tau_replaced_by_fitted_map` | covered |
| **REQ-18** | AC18.4 | T22, T24 | `tests/behavioral/test_consumer_parity.py::test_enforcement_requires_ece_bound` | covered |
| **REQ-18** | AC18.5 | T24 | `tests/unit/test_calibration_quality.py::test_insufficient_data_no_verdict` | covered |
| **REQ-19** | AC19.1 | T25, T28 | `tests/unit/test_consumer_tasks.py::test_task_built_from_consumer_spec` | revised (schema Task) |
| **REQ-19** | AC19.2 | T26, T28 | `tests/unit/test_consumer_tasks.py::test_multi_task_single_call` | revised (multi-Task) |
| **REQ-19** | AC19.3 | T25, T28 | `tests/contract/test_consumer_tasks_contract.py::test_task_matches_registered_spec` | covered |
| **REQ-19** | AC19.4 | T25, T28 | `tests/behavioral/test_consumer_parity.py::test_tool_choice_unchanged_by_task_refactor` | covered |
| **REQ-20** | AC20.1 | T26, T28 | `tests/unit/test_batched_scoring.py::test_multi_task_single_session_run` | revised (native) |
| **REQ-20** | AC20.2 | T26, T28 | `tests/behavioral/test_batched_scoring.py::test_same_state_batched` | revised (native) |
| **REQ-20** | AC20.3 | T26 | `tests/behavioral/test_batched_scoring.py::test_batch_flat_latency` (BT-DEI-11) | covered |
| **REQ-20** | AC20.4 | T26 | `tests/contract/test_batched_scoring_contract.py::test_batch_failure_degrades_per_consumer` | covered |

| **REQ-21** | AC21.1 | T28 | `tests/unit/test_onnx_backend.py::test_labels_scored_as_schema_task` | covered |
| **REQ-21** | AC21.2 | T28 | `tests/contract/test_onnx_backend_contract.py::test_envelope_unchanged` | covered |
| **REQ-21** | AC21.3 | T28 | `tests/contract/test_onnx_backend_contract.py::test_cpu_provider_zero_vram` (CT-DEI-11) | covered |
| **REQ-21** | AC21.4 | T29 | `tests/contract/test_onnx_backend_contract.py::test_no_fallback_model` | covered |
| **REQ-21** | AC21.5 | T30 | `tests/unit/test_onnx_backend.py::test_requirements_and_path_check` | covered |
| **REQ-21** | AC21.6 | T29 | `tests/unit/test_lfm_removal.py::test_no_lfm_symbols_remain` | covered |
| **REQ-21** | AC21.7 | T32 | `tests/contract/test_onnx_backend_contract.py::test_backend_identity_on_row` (CT-DEI-12) | covered |
| **REQ-21** | AC21.8 | T28 | `tests/contract/test_menu_composition_contract.py::test_production_menu_no_dupes_controls_survive_cap` (CT-DEI-18) | covered |
| **REQ-22** | AC22.1 | T31 | `tests/unit/test_threshold_retune.py::test_default_threshold_040` | covered |
| **REQ-22** | AC22.2 | T31 | `tests/behavioral/test_calibrate_threshold.py::test_coverage_accuracy_curve_reported` (BT-DEI-14) | covered |
| **REQ-22** | AC22.3 | T29 | `tests/behavioral/test_decision_bench.py::test_flat_only_no_tree` | covered |
| **REQ-22** | AC22.4 | T31 | `tests/behavioral/test_consumer_parity.py::test_no_enforce_below_bar` | covered |
| **REQ-22** | AC22.5 | T32 | `tests/contract/test_onnx_backend_contract.py::test_variant_recorded_and_stale_check` | covered |

| **REQ-23** | AC23.1 | T33 | `tests/behavioral/test_decision_engine_gates.py::TestSurfaceGateBehavior::test_shadow_verdict_returned_for_calibration_never_steers` (RED → green, not edited) | covered |
| **REQ-23** | AC23.2 | T33 | `tests/behavioral/test_decision_engine_gates.py::TestSurfaceGateBehavior::test_card_turn_still_observed_with_truthful_frame` (RED → green, not edited) | covered |
| **REQ-23** | AC23.3 | T33 | `tests/contract/test_presentation_observer_contract.py::test_no_steering_field_written` (CT-DEI-13) | covered |
| **REQ-23** | AC23.4 | T33 | `tests/behavioral/test_presentation_observer.py::test_engine_unavailable_returns_none` | covered |
| **REQ-23** | AC23.5 | T33 | `tests/contract/test_presentation_observer_contract.py::test_meta_row_shape_both_paths` (CT-DEI-13) | covered |
| **REQ-23** | AC23.6 | T33 | `tests/contract/test_presentation_observer_contract.py::test_gate_layer_only_never_content` | covered |
| **REQ-24** | AC24.1 | T34 | `tests/unit/test_failure_warnings.py::test_passes_failure_dict_to_encoder` | covered |
| **REQ-24** | AC24.2 | T34 | `tests/contract/test_failure_evidence_contract.py::test_single_settled_return_type` (CT-DEI-14) | covered |
| **REQ-24** | AC24.3 | T34 | `tests/unit/test_failure_warnings.py::test_absent_state_returns_empty_no_raise` | covered |
| **REQ-24** | AC24.4 | T34 | `tests/contract/test_recovery_evidence_contract.py::test_warning_reaches_ruled_out` | covered |
| **REQ-24** | AC24.5 | T34 | `tests/unit/test_failure_warnings.py::test_error_logged_with_exception_type` | covered |
| **REQ-24** | AC24.6 | T34 | `tests/contract/test_failure_evidence_contract.py::test_row_records_evidence_supplied` | covered |
| **REQ-25** | AC25.1 | T35 | `tests/contract/test_config_authority.py::test_yaml_parsed_into_engineconfig` (CT-DEI-16) | covered |
| **REQ-25** | AC25.2 | T35 | `tests/contract/test_config_authority.py::test_effective_config_observable` | covered |
| **REQ-25** | AC25.3 | T35 | `tests/unit/test_config_fallback.py::test_missing_key_falls_back_and_logs_once` | covered |
| **REQ-25** | AC25.4 | T35 | `tests/behavioral/test_config_roundtrip.py::test_cap_effective_in_menu_width` (BT-DEI-16) | covered |
| **REQ-25** | AC25.5 | T35 | `tests/behavioral/test_config_roundtrip.py::test_cap_change_marks_threshold_stale` (BT-DEI-16) | covered |
| **REQ-25** | AC25.6 | T35 | `tests/contract/test_config_authority.py::test_no_unread_keys_in_block` | covered |
| **REQ-25** | AC25.7 | T35 | `tests/contract/test_config_authority.py::test_shipped_cap_equals_calibrated_width` (Decision C) | covered |
| **REQ-25** | AC25.8 | T35, T31 | `tests/contract/test_config_authority.py::test_threshold_keyed_by_active_backend_fail_closed` | covered |
| **REQ-26** | AC26.1 | T36 | `tests/behavioral/test_bounded_wait.py::test_all_entry_points_bounded` (BT-DEI-17) | covered |
| **REQ-26** | AC26.2 | T36 | `tests/unit/test_latency_breakdown.py::test_three_latency_fields_emitted` | covered |
| **REQ-26** | AC26.3 | T36 | `tests/unit/test_latency_breakdown.py::test_lock_wait_separated_from_compute` | covered |
| **REQ-26** | AC26.4 | T36 | `tests/behavioral/test_bounded_wait.py::test_overrun_returns_none_legacy_path` (BT-DEI-17) | covered |
| **REQ-26** | AC26.5 | T36 | `tests/unit/test_latency_breakdown.py::test_fast_path_args_near_zero_present` | covered |
| **REQ-27** | AC27.1 | T37 | `tests/contract/test_cache_contract.py::test_key_includes_evidence_component` (CT-DEI-17) | covered |
| **REQ-27** | AC27.2 | T37 | `tests/contract/test_cache_contract.py::test_cache_bounded_with_eviction` (CT-DEI-17) | covered |
| **REQ-27** | AC27.3 | T37 | `tests/unit/test_cache_key.py::test_evidence_differs_no_collision` | covered |
| **REQ-27** | AC27.4 | T37 | `tests/unit/test_cache_key.py::test_hit_not_counted_as_fresh_decision` | covered |
| **REQ-27** | AC27.5 | T37 | `tests/unit/test_cache_key.py::test_no_consult_when_key_incomplete` | covered |
| **REQ-28** | AC28.1 | T43 | `tests/contract/test_evidence_seam.py::test_frame_accepts_unpopulated_evidence` | covered |
| **REQ-28** | AC28.2 | T43 | `tests/unit/test_evidence_shape.py::test_lower_bound_count_and_scope` | covered |
| **REQ-28** | AC28.3 | T45 | `tests/behavioral/test_evidence_semantics.py::test_prior_outvotable_cannot_cross_threshold` (BT-DEI-18) | covered |
| **REQ-28** | AC28.4 | T44 | `tests/contract/test_readonly_engine.py::test_zero_graph_writes_all_paths` (CT-DEI-15) | covered |
| **REQ-28** | AC28.5 | T43 | `tests/behavioral/test_evidence_late.py::test_late_evidence_no_stall_no_redecide` | covered |
| **REQ-28** | AC28.6 | T45 | `tests/contract/test_evidence_seam.py::test_row_records_present_and_used` | covered |
| **REQ-28** | AC28.7 | T45 | `tests/behavioral/test_evidence_semantics.py::test_unused_retrieval_not_scored_success` (BT-DEI-18) | covered |
| **REQ-28** | AC28.8 | T43 | `tests/unit/test_evidence_shape.py::test_freshness_and_scope_attached` | covered |
| **REQ-29** | AC29.1 | T46 | `tests/behavioral/test_trailing_director_consumer.py::test_has_gaps_shadow_row` | covered |
| **REQ-29** | AC29.2 | T47 | `tests/behavioral/test_thinking_consumer.py::test_use_thinking_shadow_and_fallback` | covered |
| **REQ-29** | AC29.3 | T48 | `tests/behavioral/test_escalation_consumer.py::test_escalate_incomplete_safety_unchanged` | covered |
| **REQ-29** | AC29.4 | T49 | `tests/behavioral/test_needs_action_consumer.py::test_safe_direction_preserved` | covered |
| **REQ-29** | AC29.5 | T49 | `tests/contract/test_consumer_registry.py::test_tier0_not_scored` | covered |
| **REQ-29** | AC29.6 | T52 | `tests/behavioral/test_consumer_parity.py::test_flip_only_on_tg13_bar` | covered |
| **REQ-29** | AC29.7 | T46, T47, T48, T49 | `tests/behavioral/test_engine_unavailable_parity.py::test_all_four_sites_unchanged_when_dead` | covered |
| **REQ-30** | AC30.1 | T38 | `tests/unit/test_ort_session_options.py::test_explicit_session_options_recorded` | covered |
| **REQ-30** | AC30.2 | T39 | `tests/unit/test_label_cache.py::test_label_positions_cached_per_set` | covered |
| **REQ-30** | AC30.3 | T40 | `tests/behavioral/test_batch_single_encode.py::test_one_encode_one_session_run` | covered |
| **REQ-30** | AC30.4 | T41 | `tests/behavioral/test_warmup_width.py::test_warmup_at_effective_cap` | covered |
| **REQ-30** | AC30.5 | T42 | `tests/contract/test_executor_isolation.py::test_inference_off_shared_step_threads` | covered |
| **REQ-30** | AC30.6 | T38 | `tests/behavioral/test_bench_breakdown.py::test_per_stage_breakdown_reported` | covered |
| **REQ-30** | AC30.7 | T38, T39, T40, T41, T42 | `tests/behavioral/test_decision_bench.py::test_no_accuracy_regression_vs_wave8` (BT-DEI-19) | covered |
| **REQ-30** | AC30.8 | T38, T39, T40, T41, T42 | `tests/behavioral/test_tuning_revert.py::test_p95_regression_recorded_and_reverted` (BT-DEI-19) | covered |
| **REQ-31** | AC31.1 | T50 | `tests/behavioral/test_calibrate_threshold.py::test_curve_at_deployed_config` (BT-DEI-20) | covered |
| **REQ-31** | AC31.2 | T50 | `tests/behavioral/test_calibrate_threshold.py::test_ece_brier_at_deployed_config` | covered |
| **REQ-31** | AC31.3 | T51 (DEFERRED — Decision C) | `tests/behavioral/test_menu_width_study.py::test_two_widths_measured_optimum_recorded` | covered (deferred) |
| **REQ-31** | AC31.4 | T50 | `tests/behavioral/test_config_roundtrip.py::test_stale_refuses_enforcement` | covered |
| **REQ-31** | AC31.5 | T52 | `tests/contract/test_consumer_bar_record.py::test_bar_recorded_per_consumer` | covered |
| **REQ-31** | AC31.6 | T52 | `tests/behavioral/test_consumer_parity.py::test_tg7_stands_when_config_unchanged` (Decision C) | covered |

**Matrix Audit:**
- Counted ACs in requirements.md: 151
- Matrix rows: 151
- Covered: 145
- Superseded: 6 — REQ-21 model decision (AC1.1, AC1.2, AC1.4) + **REQ-22 AC22.3 `decide_tree` retirement (AC4.1, AC4.2, AC4.3)**
- Carried by another REQ: 1 (AC1.3 → REQ-21/T28, counted within the 145)
- Deferred: 1 (AC31.3 — menu-width study, Decision C; still owned by T51 and still covered by a test)
- Unmapped: 0

**Verified mechanically (2026-09-25):** ACs extracted from `requirements.md` and from this
matrix were compared with `comm -23` / `comm -13` in both directions — **zero ACs in the
requirements missing from the matrix, and zero matrix rows without a requirement**. Counts
agree at 151/151.

**AC delta history:** 62 (baseline) → 79 (+3 REQ-6, +1 REQ-14, +5 REQ-18, +4 REQ-19, +4 REQ-20)
→ 91 (+7 REQ-21 ONNX backend, +5 REQ-22 distribution retune) → **151** (+60 for REQ-23–REQ-31
plus the AC21.8 amendment: +6 REQ-23 observer seam, +6 REQ-24 failure evidence, +8 REQ-25 config
authority (AC25.7 Decision C, AC25.8 backend-keyed thresholds), +5 REQ-26 bounded waits, +5 REQ-27
cache, +8 REQ-28 evidence seam, +7 REQ-29 surface consumers, +8 REQ-30 post-swap performance,
+6 REQ-31 operating point, +1 REQ-21 AC21.8 production menu composition).

**Supersession note (2026-09-25, second pass):** REQ-1 was retired by the model decision
(REQ-21) and **REQ-4 is now retired by REQ-22 AC22.3** — the lane construction it fixes feeds
only `decide_tree`, which is being deleted. T0, T1, T4 and T23 are cancelled; TG-0 is retired.
The `zero prefix tie-breaker` success criterion is N/A (the loop is deleted, not fixed), and the
`web lane never dropped` criterion is N/A for the same reason. REQ-18/19/20 are retained with
revised acceptance criteria — their intent survives, their LFM-specific mechanics do not.

**Task delta history:** T0–T32 (4 cancelled: T0, T1, T23, TG-0) → **T33–T52 added** across Waves
9–13, with gates TG-9 through TG-13. 20 new tasks, 5 new gates.

**Supersession note (2026-09-25):** the model decision (REQ-21) retires REQ-1's letter/first-token
mechanism. T0, T1 and T23 are cancelled; TG-0 is retired; the `zero prefix tie-breaker` success
criterion is marked N/A (the loop is deleted, not fixed). REQ-18/19/20 are retained with revised
acceptance criteria — their intent survives, their LFM-specific mechanics do not.

---

## Dependency & Parallelization Notes

- **Wave 1 vs Wave 2:** Wave 1 (in-process decision engine prompt and parameter logic) and Wave 2 (candidate token pre-filters and vision deduplication) can be developed in parallel.
- **Wave 3 dependencies:** Wave 3 requires Wave 1 and Wave 2 to be green to measure and calibrate true sub-450ms resolution latency. **T24 blocks Wave 7** — no consumer flips to enforced while its ECE is unmeasured or out of bound.
- **Wave 0 gates Wave 1:** T1 MUST NOT start until TG-0 locks the scoring-method winner (letters vs first-token). T23 (head-snapshot wiring) is independent of the method and may start immediately.
- **Wave 5 dependencies:** T15 requires Wave 1 green (stable engine scoring underlies the strategy gate); T11/T12/T13/T14/T16 are independent of each other and may run parallel once Wave 1 is green. Wave 5 needs no Wave 3 calibration data, but BT-DEI-5/6/7 join the standing battery afterwards.
- **Wave 6 dependencies:** **T25 lands before T17–T21** (per-consumer criteria must exist before consumers are scored, or parity fails for reasons unrelated to the consumers themselves). T17–T21 require Wave 1 green (scoring stable) and may then run parallel; T21 additionally needs Wave 5 green (recovery consumer exists). T26 (batched scoring) is independent and may run parallel. Nothing in Wave 6 changes runtime decisions, so it needs no calibration data — it PRODUCES it.
- **Wave 7 dependencies:** T22 requires TG-6 green plus row volume (≥ 100 rows per consumer proposed for flip, per JEV's 100–500 calibration-sample guidance) AND a within-bound ECE from T24. Consumers below bar stay shadow; TG-7 records exactly which flipped and which did not, with the numbers.
- **Wave 8 dependencies (model migration):** T28 (backend) is the root — T29 (LFM deletion) must follow it, never precede it, so the engine is never left with no scorer. T30 (deps/config) and T31 (threshold) can run in parallel with T29 once T28 is green. T32 depends on T28. **Wave 8 does not depend on Waves 0–3** and should land early: it supersedes T0/T1/T23, and every consumer's confidence distribution changes with the backend, so Wave 6/7 thresholds (T24/T31) must be measured *after* Wave 8, not before. Re-run TG-8 after any change to the ONNX variant.
- **Wave 9 dependencies (foundation integrity):** T33–T37 are **independent of each other** and may run in parallel — they touch different files (`agent_kernel.py` gate, `agent_kernel.py` failure warnings, config parsing, `decision_engine.py` locks, `tool_decision.py` cache). **T35 MUST land before T31**, or T31 edits a value nothing reads. **T37 MUST land before T43**, or the evidence payload is silently swallowed on a cache hit. T33 should land before T17–T21 (Wave 6) because all seven new consumers share the observer pattern it fixes. **Wave 9 does not depend on Wave 8** and may run in parallel with it.
- **Wave 10 dependencies (post-swap performance):** requires **Wave 8 green** (nothing to tune without the ONNX backend) and **Wave 9 green** (nothing to measure without the latency breakdown). T38–T42 are independent of each other but each must be measured against the SAME recorded Wave 8 baseline, so they should be applied and measured one at a time rather than batched — a batched change cannot be attributed. T41 needs T35's parsed config.
- **Wave 11 dependencies (evidence seam):** T43 → T45 (the field must exist before its semantics are pinned); T44 is independent and may run any time after T43. **T37 (Wave 9) must be green first.** Wave 11 has **no dependency on `specs/wormhole-aperture/`** — it ships the seam unpopulated precisely so that spec can land later without engine changes. Do not let a wormhole task enter this wave.
- **Wave 12 dependencies (surface completion):** T46–T49 are independent of each other and may run parallel. Each requires a **stable engine** (Wave 8) and the **shadow observer pattern** (T33). Nothing in Wave 12 changes runtime decisions — it PRODUCES calibration data. T48 and T49 touch escalation and the `NONE` commit, so they must not alter any budget, veto-cap, or termination check.
- **Wave 13 dependencies (operating point) — CONFIRMATION gate under Decision C:** requires **TG-9, TG-10, TG-11, TG-12 green**, plus row volume (≥100 rows per consumer, per D7/TG-7). T50 runs **after** T35 (live config) and after any Wave 10 tuning that changed latency, since both move the curve. **TG-7 remains the authoritative enforcement gate**: TG-13 CONFIRMS it while the configuration is unchanged and fires re-validation only if the cap, backend, or deployed variant moves. T51 (menu-width study) is **DEFERRED** and gates T52 only when a width change is proposed. Re-run TG-13 after any change to the backend, the cap, or the deployed ONNX variant.
- **Cross-wave rule (progressive verification):** no wave may be measured before its predecessor's gate passes, and no gate may be satisfied by a green test suite alone — each gate asserts its wave's specific claim with evidence (a config round-trip, a measured delta against a recorded baseline, an inert-when-absent regression check, a confirmed or re-derived curve). This is what keeps the engine verifiably optimal rather than merely passing.

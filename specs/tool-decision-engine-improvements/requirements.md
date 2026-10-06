# Requirements: Tool Decision Engine Improvements (Sub-450ms Native Latency)

## Decisions Locked

- **Model decision — REVISED 2026-09-25 (supersedes "Native LFM2-350M-Extract Retention"):** the resident decision model becomes **`GLiNER2.5-Decide` via its ONNX export, run in-process on `onnxruntime` (CPUExecutionProvider)**. The previous decision locked `LFM2-350M-Extract` (GGUF via `llama_cpp`); it is **retired, with no fallback path**. Rationale: measured head-to-head on the 60-case labeled battery, GLiNER scores **71.7% accuracy at 119 ms p50** versus LFM2's **60.0% at 1172 ms** (flat) and **33.3% at 5399 ms** (the hierarchical production path), and its confidence is natively calibrated (**100% accuracy above 0.40**, all errors ≤ 0.352). Full evidence: `BENCH-2026-09-25-model-comparison.md`; amendment record: `docs/architecture/tool-decision-engine-improvements.md` §10.
  - **Still REJECTED:** hosted/external router dependencies (Laya, or any cloud decision API). GLiNER runs locally in-process; only the *model* changed, not the residency principle.
  - **Still REJECTED:** GPU VRAM for the decision engine — `onnxruntime` CPUExecutionProvider only.
  - **No fallback model:** on engine failure the engine returns `None` and callers take their existing legacy-heuristic path (unchanged behaviour when the engine is unavailable). A second resident model is explicitly out of scope.
  - **The GGUF constraint is withdrawn.** It was a proxy for "no new heavy dependency, CPU-resident, in-process". `onnxruntime` + `tokenizers` + `numpy` are already installed and satisfy the real constraint; both must now be declared in `requirements.txt`.
- **Single-Token Option Scoring (method probe-gated):** *SUPERSEDED 2026-09-25 by the model decision above.* With a schema-scoring backend there is no option-token read, no prefix-collision tie-breaker loop, and no T0 A/B probe to run. Retained here only as history; REQ-1 is superseded (see REQ-1).
- **Fast-Path Parameter Slot Filling:** For single-parameter query tools (`search`, `crawler_query`), eliminate autoregressive token generation (`generate_args`). Map the user goal text directly to the `"query"` parameter in 0ms, saving 500–1,500ms.
- **Token De-biasing:** Strip `"what's"` from `_VISION_TOKENS` in `backend/agent/tool_decision.py`. Require multi-word phrases (e.g. `"what's on screen"`) to prevent factual questions from falsely masquerading as vision tasks.
- **~~Pre-Cap Hierarchical Lane Construction~~ — SUPERSEDED 2026-09-25. THE HIERARCHY IS RETIRED; nothing in this spec builds or preserves one for tool choice.** ~~Construct hierarchical category lanes (`web`, `vision`, `file`) from the full tool candidate set before applying candidate cap truncation, ensuring web tools are never silently dropped.~~ **Replaced by:** flat single-pass scoring over the candidate set is the ONLY path (REQ-22 AC22.3). Measured: the hierarchy cost **26.7 accuracy points and 4.6× latency** (33.3% @5399 ms vs 60.0% @1172 ms on the same model), and its failure mode was 33-of-40 wrong answers collapsing to `DELEGATE` — the lane stage fails, the leaf cannot resolve, and the decision degrades to "no tool". The lane construction it required exists **solely** to feed `decide_tree` (`tool_decision.py:603-609`, consumed only at `:613`) and is deleted by **T29**; **REQ-4 is superseded and T4 is cancelled.** The wide-menu case (`>26` candidates) is handled by `candidate_cap` (REQ-25 AC25.7) plus the backend's native multi-label scoring — **not** by lanes.
- **Vision Capture Deduplication:** In `tool_bridge.py:1601`, reuse the screenshot buffer returned by the vision tool for ledger recording instead of executing a second synchronous screen capture.
- **Dynamic On-The-Fly Composite Recipe Generation & Pre-Flight Contract Validation:** When a multi-step user goal requires interconnecting multiple tools without a pre-existing composite node in the registry, the Brain Agent synthesizes an on-the-fly composite recipe (`DynamicCompositeRecipe`). Before execution, the engine validates artifact compatibility (`NodeSpec.consumes` matches `NodeSpec.produces`) and enforces that zero required parameters are null or missing (`validate_no_null_or_missing_params`). Successfully verified recipes are registered into the node graph as reusable composite nodes (`NodeSpec(composite_of=...)`), enabling the resident Decision Engine to select them directly via sub-450ms letter scoring on future turns.
- **Amendment 2026-09-25 (code-verified audit of the improvements doc):** every finding below was traced against live code before writing. (a) Quick-search tiering is a WIRING task, not a new-provider build — `backend/crawler/search_providers/` (`base.py`, `exa.py`, `llm.py`) already exists but the `search` tool still routes through `CrawlOrchestrator().research()` (`backend/agent/tool_bridge.py:3644-3745`); wire the existing providers and preserve the REQ-16 progress/card event frames the current path emits. (b) REQ-1 letter scoring is CONTESTED by as-built evidence — the engine deliberately scores first-tokens with a tie-break loop (`backend/agent/decision_engine.py:426-453`, rationale at :396-407) after live probes showed content tokens discriminate and bare letters collapse to literal matching (session-344 finding, cited at `backend/agent/tool_decision.py:550-552`); T0 A/B probe gates T1's method, REQ-1's ACs stand either way. (c) Graft recovery tool-pick needs NO new wiring — grafted/split children carry `tool=None` and already resolve engine-first via `ToolDecisionBox.resolve()` (`backend/agent/agent_kernel.py:15012-15031`); the real gap is failure memory (the just-failed tool is not vetoed, counters reset at :12986), covered by REQ-11. (d) The `_mem_lookup` synchronous block is still live (`_asyncio.run` at `backend/agent/agent_kernel.py:14656`), covered by REQ-12.
- **Amendment 2026-09-25 (c) — decisions locked from the full-surface audit.** These are settled; they shape REQ-23–REQ-31 and are not open for re-litigation:
  - **The engine NEVER feeds the pheromone loop (owner decision).** The engine is READ-ONLY with respect to NBL. `tool_choice` edge writes belong to the execution layer (`record_region_mediator_outcome`, `agent_kernel.py:16143`, derived from `_der_mediator_for(item)` — the executed item, not the engine's choice). This is the D8 shape: the engine scores, other layers write. Pinned by REQ-28 AC28.4.
  - **Evidence ships UNPOPULATED.** REQ-28 defines the frame field and its context rules, but no caller supplies it within this spec's scope. `specs/wormhole-aperture/` is NOT implemented; nothing here may assume it. The seam exists so a future provider plugs in without engine changes.
  - **The cache key must include the evidence payload from day one** (REQ-27 AC27.1), even while it is always empty — otherwise the prior is silently swallowed on a cache hit when it does arrive.
  - **Tier-0 deterministic classification is a NON-FIT** (REQ-29 AC29.5). A <1ms reflex must not become a ~119ms model call.
  - **A config value that does not change behaviour is a defect** (REQ-25). `decision_driver` is parsed or trimmed; no documented-but-unread keys.
  - **The baseline record is corrected** to `5 failed / 102 passed`; two of those reds are real (REQ-23), not stale.
  - **DECISION C (2026-09-25) — `candidate_cap` ships at 6, the calibrated width.** The `decision_driver` block becomes live (REQ-25) but ships `candidate_cap: 6` — the menu width the 0.40 accuracy/coverage curve was actually derived at. This fixes the real defect (the key was **DECORATIVE**: `grep "decision_driver"` returned zero hits, so nothing read it) **without invalidating the calibration**. Consequence: **Wave 7 / TG-7 remains the authoritative enforcement gate**, and Wave 13 / TG-13 becomes a **CONFIRMATION plus a conditional re-validation** that fires only when the cap, backend, or deployed variant actually moves. Rejected alternatives: ship `32` and re-derive every consumer's bar (pays for a re-measurement nobody asked for, and re-opens settled flips); or delete the key and freeze the cap permanently (loses a real tuning knob). Recorded in `backend/agent/agent_config.yaml:25-35`; pinned by REQ-25 AC25.7.

---

## Introduction

The IRIS Tool Decision Engine was built to provide calibrated, low-latency small-model tool selection. While the resident `LFM2-350M-Extract` model is computationally capable of sub-250ms inference on CPU, runtime decision latency currently averages 1,500–2,500ms. 

This latency explosion is caused by two structural bottlenecks:
1. Candidate prefix collisions among tools sharing prefixes (e.g., `vision_detect_element`, `vision_analyze_screen`), which trigger context resets and sequential prompt re-evaluations (+800–1,100ms).
2. Autoregressive JSON token generation in `generate_args` (+500–1,500ms).
In addition, heuristic false positives on the token `"what's"` push web queries into vision menus, causing high-latency escalations.

This feature optimizes the decision engine to achieve a total decision and dispatch latency under 450ms (targeting 150–250ms) entirely on CPU.

### Success Criteria

**Revised 2026-09-25 against measured results** (original targets retained for history in the
amendment record; `BENCH-2026-09-25-model-comparison.md` carries the evidence).

- **Decision Scoring Latency:** p50 ≤ 180ms on CPU. **MEASURED: 119.2ms** (GLiNER ONNX int8) — met.
- **Total Resolution Latency:** end-to-end tool decision p50 ≤ 450ms. **MEASURED: 119.2ms** — met (44× under the old 2,200ms baseline).
- **No Prefix Tie-Breaker Loops:** N/A — superseded; the tie-breaker loop is deleted with the LFM path (REQ-21 AC21.6).
- **Zero Vision False Positives on Search:** unchanged (REQ-3), independent of the model.
- **Decision Accuracy:** P(correct tool | confidence ≥ threshold) ≥ 0.92. **MEASURED: 100.0%** at threshold 0.40 — met.
- **Decision Calibration:** the reported confidence tracks empirical correctness. **MEASURED: all errors ≤ 0.352 confidence; 100% accuracy above 0.40** — met (REQ-18/REQ-22).
- **Overall accuracy (new, 2026-09-25):** ≥ 70% on the labeled battery with no threshold. **MEASURED: 71.7%** (incumbent LFM: 60.0% flat / 33.3% production).
- **Post-swap performance (new, REQ-30):** every tuning change measured against the recorded Wave 8 baseline with **no accuracy regression**, and a recorded latency breakdown per stage. A change that regresses p95 is reverted and recorded, not kept.
- **Config authority (new, REQ-25):** every key in the `decision_driver` block is either parsed and effective, or removed. A documented value that does not change behaviour is a defect.
- **Bounded waits (new, REQ-26):** no engine entry point can block indefinitely; every decision carries `scoring_latency_ms` / `args_latency_ms` / `decision_latency_ms` with lock-wait separated from compute.
- **Bounded cache (new, REQ-27):** the decision cache has a documented maximum and cannot return a verdict computed for a different evidence payload.
- **Read-only engine (new, REQ-28):** zero engine writes to the memory/graph store on every decision path, asserted by contract test.
- **Operating point (new, REQ-31, Decision C):** the operating point is CONFIRMED against the deployed configuration. The shipped `candidate_cap` equals the calibrated width (**6**), so the calibration stays valid, **Wave 7 / TG-7 remains the authoritative enforcement gate**, and settled flips are not re-litigated. Re-derivation fires only if the cap, backend, or deployed variant actually moves — and then no flip measured at a superseded configuration stands.

### Test baseline (corrected 2026-09-25)

The earlier record of `2 failed, 70 passed` is **STALE**. Measured this session:

```
5 failed, 102 passed, 3 warnings in 9.63s
```

- **2 known stale reds** (unchanged): `TestCtDe3Ledger::test_reason_engine_decision_records_route_only_row_once` and `TestBtDe4ReasonSingleRow::test_none_choice_one_route_only_row` — both assert route `"escalated"` while the code emits `"engine-none"` (the 2026-09-24 OQ-2 refinement). Not regressions; **do not edit the tests** (TEST RULE); owner decision.
- **2 REAL reds** — the presentation observer seam, owned by REQ-23. Unimplemented requirements red since 2026-09-24 (`528a9435`), not stale tests.
- **1 stale PIN** — `test_document_render_data_keys_pinned`: the `DOCUMENT_RENDER` emit carries a `title` key (`agent_kernel.py:10351`, intentional additive change) that the CT-DE-6 pinned set never absorbed. The pin needs the documented extension (as `card_id` / `partial` each received), not a code fix.

Wave 9's gate re-establishes this baseline before any later wave measures against it.

---

## Requirements

### REQ-1: Single-Forward-Pass Option Scoring (Lettered Choices) — **SUPERSEDED**

> **SUPERSEDED 2026-09-25 by the model decision (REQ-21).** With a schema-scoring backend
> (GLiNER2.5-Decide) there is no option-token read at all: candidate tools are labels in a
> `Task` schema, scored by a classification head in one pass. The prefix-collision tie-breaker
> loop, the `_letter_token_ids` machinery, the first-token scoring path, and the T0 A/B probe
> **all become moot** — T0/T1/T23 are cancelled. The acceptance criteria below are retained
> for history only and are **not** to be implemented. The latency and accuracy intent they
> encoded is carried by REQ-21 (backend) and REQ-22 (threshold/calibration).

**User Story:** As the decision engine I want candidate tools scored via single-letter tokens so that option scoring executes in a single forward pass without prefix-collision context resets.

**Verified:** NEW (currently `decision_engine.py:426-453` evaluates first-token prefixes and executes serial tie-breaker evals).

**Approach contingency (2026-09-25):** as-built evidence contests the letter method — live probes showed the answer position distributes over content tokens, not letters (`decision_engine.py:396-407`), and session 344 found letter read-out collapses to literal name matching (`tool_decision.py:550-552`). T0 runs the deciding A/B probe; T1 implements letters OR tie-break-free first-token scoring per the probe winner. AC1.1–1.4 hold under either method (read "letter token" as "the probe-winning single-token method" if letters lose).

**Acceptance Criteria:**
- AC1.1: THE ENGINE SHALL format candidate options in the decision prompt using single-letter indices (`A: <tool_1>`, `B: <tool_2>`, `C: <tool_3>`).
- AC1.2: THE ENGINE SHALL compute candidate probabilities by extracting output logits for pre-tokenized letter tokens at the completion position in a single forward pass.
- AC1.3: THE ENGINE SHALL complete candidate scoring in ≤ 180ms p50 on CPU without calling `_llm.reset()` or re-evaluating prompt tokens.
- AC1.4: IF multiple candidates share a common tool name prefix (e.g. `vision_*`) THEN THE ENGINE SHALL score them independently via distinct letter tokens without triggering a tie-breaker re-eval loop.

**Edge Cases:**
- Candidate list with > 26 tools → ~~The engine applies hierarchical lane grouping before letter scoring.~~ **N/A — the hierarchy is RETIRED (AC22.3).** The backend scores an arbitrary label set in one pass; the menu is bounded by `candidate_cap`.
- Model returns non-letter token → Fallback to argmax over candidate letter logit subset.
- **All Edge Cases in this REQ are historical** — REQ-1 is superseded and none of them is to be implemented.

---

### REQ-2: Deterministic Fast-Path Parameter Slot Filling
**User Story:** As the runtime I want tools with single-string arguments (`query`) populated directly from the goal text so that the system saves 500–1,500ms of autoregressive JSON text generation.

**Verified:** NEW (currently `decision_engine.py:477-520` always runs autoregressive JSON text completion).

**Acceptance Criteria:**
- AC2.1: WHEN the chosen tool requires only a single parameter `{"query": str}` (such as `search` or `crawler_query`) THEN THE SYSTEM SHALL map the goal text directly to the `"query"` parameter.
- AC2.2: WHEN single-slot parameter extraction applies THEN THE SYSTEM SHALL bypass `generate_args` autoregressive token completion entirely.
- AC2.3: THE SYSTEM SHALL complete parameter assignment in ≤ 1ms with 0 autoregressive tokens generated.
- AC2.4: IF the chosen tool schema requires multiple complex arguments THEN THE SYSTEM SHALL execute schema-constrained JSON generation.

**Edge Cases:**
- Goal text contains surrounding quotes or whitespace → Strip leading/trailing whitespace and quotes before slot assignment.
- Empty goal text → Raise validation error without parameter assignment.

---

### REQ-3: Heuristic & Vision Token De-biasing
**User Story:** As the agent loop I want web queries containing the word "what's" routed to search instead of vision so that factual questions are not intercepted by vision candidate menus.

**Verified:** NEW (currently `tool_decision.py:56` includes `"what's"` in `_VISION_TOKENS`).

**Acceptance Criteria:**
- AC3.1: THE SYSTEM SHALL remove the isolated token `"what's"` from `_VISION_TOKENS` in `backend/agent/tool_decision.py`.
- AC3.2: THE SYSTEM SHALL require multi-word contextual phrases (`"what's on screen"`, `"look at screen"`, `"take a screenshot"`) to trigger vision relevance.
- AC3.3: WHEN a user asks a factual question starting with "what's" (e.g., "what's the stock price of Apple") THEN THE SYSTEM SHALL route the candidate menu to web search tools and SHALL NOT force vision tools to the front.

**Edge Cases:**
- Query says "what's on my screen right now" → Matches multi-word phrase; correctly routes to vision tools.

---

### REQ-4: Hierarchical Lane Construction Fix — **SUPERSEDED**

> **SUPERSEDED 2026-09-25 by REQ-22 AC22.3 (`decide_tree` retired).** The lane construction this
> REQ fixes exists **only** to feed `decide_tree`'s lane stage. Verified: `lanes` /
> `lanes_for_engine` are built at `tool_decision.py:603-609` and consumed at **exactly one**
> place — `_dt("tool_choice", lanes_for_engine, frame)` (`:613`). Nothing else reads them. Once
> `decide_tree` is deleted, the whole block (`:590-620`, including `name_to_cat` at `:598` and
> the `_pre_cap_count > _cap` trigger at `:610`) is **dead code**, so fixing lane construction
> would be fixing a code path that no longer exists. **T4 is cancelled in place**; the dead
> block is deleted by **T29** instead. The acceptance criteria below are retained for history
> only and are **not** to be implemented. The §10.3 "RE-EVALUATE" note for REQ-3/REQ-4 is hereby
> resolved for REQ-4: REQ-3 (vision tokens) still stands — `_vision_relevant` is consumed
> independently at `:513-514`.

**User Story:** As the decision router I want hierarchical category lanes constructed from all available tools rather than a pre-sliced sub-list so that web search tools are not dropped by menu truncation.

**Verified:** SUPERSEDED — see banner above. (Was: `tool_decision.py:534` iterates over `names = names[:_cap]`.)

**Acceptance Criteria:**
- AC4.1 **(SUPERSEDED — DO NOT IMPLEMENT)**: ~~THE SYSTEM SHALL populate category lanes (`web`, `vision`, `file`, `misc`) from all pre-filtered candidates before applying candidate cap truncation.~~
- AC4.2 **(SUPERSEDED — DO NOT IMPLEMENT)**: ~~WHEN candidate count exceeds cap THEN THE SYSTEM SHALL evaluate the top candidate from each category lane.~~
- AC4.3 **(SUPERSEDED — DO NOT IMPLEMENT)**: ~~THE SYSTEM SHALL never discard the `web` lane when web search tools are available in the registry.~~

**Edge Cases:**
- All tools belong to one category → Lane evaluates with top candidates up to candidate cap.

---

### REQ-5: Vision Screenshot Deduplication
**User Story:** As the vision executor I want to reuse the captured screen frame instead of performing a second synchronous desktop capture so that vision executions save 100–250ms.

**Verified:** NEW (currently `tool_bridge.py:1601` invokes `_capture_screenshot_blob()` synchronously). **Amendment 2026-09-25:** there are TWO identical duplicate-capture sites, not one — `tool_bridge.py:1709` (vision tools) and `tool_bridge.py:1719` (GUI tools), both invoking `_capture_screenshot_blob()` immediately after their executor returns. This REQ's user story is vision-scoped; the GUI site carries the same defect and is recorded here as an explicit scope question (extend AC5.1–5.3 to both sites, or open a follow-up) rather than silently widened.

**Acceptance Criteria:**
- AC5.1: WHEN `execute_vision_tool` completes THEN THE SYSTEM SHALL reuse the image buffer returned by `VisionMCPServer`.
- AC5.2: THE SYSTEM SHALL eliminate the second synchronous `_capture_screenshot_blob()` call at `tool_bridge.py:1709` (and at `:1719` when the GUI path is in scope — see scope note above).
- AC5.3: THE SYSTEM SHALL record the shared image buffer to the event ledger asynchronously off the critical thread.

**Edge Cases:**
- `VisionMCPServer` fails to return an image buffer → Fallback to single asynchronous desktop capture.

---

### REQ-6: Observability & Latency Calibration
**User Story:** As the tuner I want structured decision logs and calibration scripts so that I can verify that tool decision engine resolution stays under 450ms.

**Verified:** NEW.

**Acceptance Criteria:**
- AC6.1: THE SYSTEM SHALL log structured JSON metrics for every decision event containing `decision_latency_ms`, `scoring_latency_ms`, `args_latency_ms`, and `is_fast_path`.
- AC6.2: `scripts/bench_decision_engine.py` SHALL assert decision scoring latency ≤ 180ms p50 on CPU across candidate menus.
- AC6.3: `scripts/calibrate_decision_threshold.py` SHALL verify P(correct tool | confidence ≥ 0.85) ≥ 0.92 without vision false positives on search queries.
- AC6.4 (2026-09-25): THE SYSTEM SHALL persist the full probability distribution and chosen confidence for every decision row — not only latency and `is_fast_path`. Rationale: JEV's audit principle records the distribution for every decision; AC6.1 as written cannot support REQ-18's calibration measurement, and CT-DEI-6 already assumes the distribution is carried for the new consumers.
- AC6.5 (2026-09-25): THE SYSTEM SHALL record the resolved decision-model identity (`model_id` + file hash) alongside calibration rows and SHALL assert it matches at load. Rationale: `resolve_model_path` globs `LFM2*350M*.gguf` (`decision_engine.py:143`, `:157-160`); thresholds are calibrated against one model's probability distribution, so an unpinned model swap silently invalidates every threshold (JEV: pin model versions in production to avoid threshold drift).
- AC6.6 (2026-09-25): WHEN the prompt builder truncates any input (goal, state bit, or option description) THEN THE SYSTEM SHALL emit a structured truncation event carrying the field name and original length. Rationale: truncation is currently silent — goal cut to 160 chars (`decision_engine.py:374`), state bits to 80 chars ×10 (`:379`), option descriptions to 80 chars (`:386`) — so a decision flipped by a cut goal is unattributable. Full JEV explicit-budget error semantics are out of scope at `n_ctx=1024`; observability of truncation is not.

**Edge Cases:**
- Ledger contains fewer than 50 events → Calibration script reports INSUFFICIENT_DATA without crashing.
- Input exactly at the truncation boundary → No truncation event (the event fires only on actual loss).

---

### REQ-7: On-The-Fly Dynamic Composite Recipe Generation & Pre-Flight Contract Validation
**User Story:** As an agent executing complex multi-tool goals I want the Brain Agent to synthesize on-the-fly composite recipes with pre-flight parameter and artifact validation so that the system handles novel interconnected workflows without requiring hardcoded recipes or failing on null parameters.

**Verified:** NEW (currently composite tools like `crawler_query` are hardcoded in `capabilities.py:729`).

**Acceptance Criteria:**
- AC7.1: WHEN a multi-step user goal requires interconnecting multiple tools without an existing composite recipe THEN the Brain Agent SHALL synthesize an on-the-fly composite recipe (`DynamicCompositeRecipe`) specifying the sub-node execution sequence, data bindings (`{{step_id.output}}`), and target artifact kinds.
- AC7.2: THE ENGINE SHALL perform pre-flight contract validation across the synthesized recipe DAG: verifying that every node's produced artifact kind satisfies the downstream consumer's `NodeSpec.consumes` declaration.
- AC7.3: THE ENGINE SHALL perform pre-flight parameter validation verifying that zero required tool schema parameters are unassigned, null, or unresolved; IF an unresolvable parameter is detected, THE ENGINE SHALL reject the invalid DAG prior to execution and request a repair.
- AC7.4: THE SYSTEM SHALL materialize the validated dynamic recipe into DER `QueueItem`s with resolved dependencies and execute the DAG through `expand_batch_nodes` and `resolve_dependent_params`.
- AC7.5: WHEN a dynamic composite recipe completes with verified user outcome THEN THE SYSTEM SHALL register the validated DAG into the episodic node graph as a reusable composite `NodeSpec`; subsequent matching requests SHALL be selected directly by the resident Decision Engine via letter-scoring fast path in ≤ 450ms without invoking the Brain LLM.

**Edge Cases:**
- Synthesized DAG contains a circular dependency → Reject during topological sort validation and prompt Brain Agent to re-plan.
- Intermediate step produces an empty or failure outcome → Trigger advertise-driven recovery node or escalate to Brain Agent with failure reason.

---

### REQ-8: Quick-Search Tier Wiring (Existing Providers, No New Build)
**User Story:** As the runtime I want the `search` tool served by the existing lightweight provider layer instead of the full crawl subprocess so that quick factual lookups return in ≤ 500ms.

**Verified:** NEW — `search` routes through `CrawlOrchestrator().research()` (`backend/agent/tool_bridge.py:3644-3745`, same path as `crawler_query`); `backend/crawler/search_providers/` (`base.py`, `exa.py`, `llm.py`) exists but is unwired to the tool.

**Acceptance Criteria:**
- AC8.1: WHEN the chosen tool is `search` THEN THE SYSTEM SHALL serve it via `backend/crawler/search_providers/` with no browser subprocess and no LLM URL planning.
- AC8.2: THE SYSTEM SHALL complete provider quick search in ≤ 500ms p50, preserving the REQ-16 progress/card event frames (`TASK_PROGRESS` + browser-panel vocabulary) the current path emits.
- AC8.3: `crawler_query` SHALL keep the `CrawlOrchestrator` deep path unchanged.
- AC8.4: THE SYSTEM SHALL distinguish the two tools in registry descriptions (`search` = instant lookup, `crawler_query` = deep multi-page research) so the engine menu can offer both without conflation.

**Edge Cases:**
- Provider returns zero results or errors → Fallback to `crawler_query` deep path with the fallback recorded in meta.
- Provider credentials absent → Degrade to current orchestrator path, never fail the step.

---

### REQ-9: Prompt Worked-Example De-biasing (search vs crawler_query)
**User Story:** As the decision engine I want worked examples that separate instant lookup from deep research so that the two web tools score differently by intent.

**Verified:** NEW — head examples in `DecisionEngine._build_prompt_parts` (`backend/agent/decision_engine.py:356-373`) contain no `search`-vs-`crawler_query` contrast pair.

**Acceptance Criteria:**
- AC9.1 — **SUPERSEDED 2026-09-26 (session 357), see below**: THE ENGINE SHALL include at least one instant-lookup example resolving to `search` and one research-class example resolving to `crawler_query` in the prompt head.
  - **WHY IT IS SUPERSEDED (BLUEPRINT-DIVERGENT, verified):** the "prompt head" this AC targets was `DecisionEngine._build_prompt_parts`, which **no longer exists** — T29 deleted it with the LFM path (`grep -rn "_build_prompt_parts" backend/agent/` returns ZERO hits). The ONNX backend has no prompt head: it scores a schema `Task` whose instruction is pinned **byte-identical to the measured bench shape** (`_TASK_INSTRUCTION`, `decision_backend_onnx.py:46`) precisely so the 0.40 curve stays valid (AC22.1/D13, and the module docstring states that frame fields are *deliberately* not rendered). Injecting worked examples into that instruction would change the distribution the threshold was measured on, which AC25.5/AC31.4 then require us to mark STALE — i.e. satisfying AC9.1 as written would **invalidate the operating point and refuse enforcement**. The de-biasing this AC wanted is delivered instead by per-consumer criteria (REQ-19) and measured by AC9.2. `tests/unit/test_prompt_examples.py` is therefore deliberately NOT created; the supersession is recorded here and in the traceability matrix, mirroring AC1.1/1.2/1.4 and AC4.1–4.3.
- AC9.2: THE CALIBRATION battery SHALL contain both intent classes and report per-class accuracy. — **covered** (`tests/behavioral/test_calibrate_threshold.py::test_per_class_accuracy_report`; the bench's `SEARCH_CASES` carry both classes).
- AC9.3: WHEN a goal matches research-class intent THEN `_is_web_intent`-family heuristics SHALL NOT force-downgrade `search` where the engine confidently chose it, and vice versa. — **covered** (`tests/behavioral/test_search_routing.py::test_no_heuristic_override_above_threshold`).

**Edge Cases:**
- Ambiguous intent ("find X") → Engine decides; no heuristic override above confidence threshold.

---

### REQ-10: Vision Target Fast-Path (Regex Slot Fill)
**User Story:** As the vision executor I want quoted click targets extracted deterministically so that `vision_detect_element` skips LLM completion on plain commands.

**Verified:** NEW (no regex target extraction exists; target resolution always costs an LLM call).

**Acceptance Criteria:**
- AC10.1: WHEN a goal matches `click|tap|press ... "X"|the X button` patterns THEN THE SYSTEM SHALL fill the element target directly in 0ms with 0 LLM tokens.
- AC10.2: IF no pattern matches THEN THE SYSTEM SHALL fall back to the current LLM target resolution unchanged.
- AC10.3: THE SYSTEM SHALL log `is_fast_path=true` with the matched pattern id for calibration joins.

**Edge Cases:**
- Quoted string is empty or longer than 120 chars → Fallback, never an empty target dispatch.

---

### REQ-11: Recovery-Aware Engine Resolution (Graft Failure Memory)
**User Story:** As the DER loop I want grafted recovery steps resolved with the just-failed tool vetoed so that recovery never re-picks the tool that just failed.

**Verified:** NEW — grafted/split children carry `tool=None` and resolve engine-first (`backend/agent/agent_kernel.py:15012-15031`), but resolve evidence carries no failure memory (`:15016-15020`) and `_split_step` resets failure counters unconditionally (`:12986`).

**Acceptance Criteria:**
- AC11.1: `ToolDecisionBox.resolve()` SHALL accept optional failure evidence (`failed_tool`, `error_snippet`) and carry it into the engine frame as `ruled_out`.
- AC11.2: THE ENGINE SHALL score a vetoed `failed_tool` at zero probability for the resolving graft step (veto survives `reset_failure_counters`, which resets counts but preserves the seed veto list).
- AC11.3: THE SYSTEM SHALL add a `recovery_strategy` engine consumer (`retry_different_tool` / `decompose` / `escalate`) consulted by graft paths BEFORE Brain planning spend; Brain plans only on DELEGATE or below-threshold.
- AC11.4: WHEN the same tool fails twice consecutively for one objective THEN THE SYSTEM SHALL escalate instead of grafting a third identical attempt.
- AC11.5: THE SYSTEM SHALL record `failed_tool` + `recovery_strategy` in decision meta for calibration joins.

**Edge Cases:**
- No failure evidence passed (normal steps) → Behavior identical to today; veto list empty.
- All candidates vetoed → Escalate to Brain with the veto set attached, never force-pick a vetoed tool.

---

### REQ-12: Off-Thread Source-Registry Lookup (Unblock the Engine Start)
**User Story:** As the DER loop I want memory source resolution off the critical thread so that a synchronous block does not delay every engine decision by 50–200ms.

**Verified:** NEW — `_mem_lookup` runs `_asyncio.run(sr.resolve(goal, quick=True))` synchronously on the DER thread (`backend/agent/agent_kernel.py:14656`, inside `_mem_lookup` at :14507).

**Acceptance Criteria:**
- AC12.1: THE SYSTEM SHALL NOT call `_asyncio.run` on the DER thread; resolution goes via `run_coroutine_threadsafe` or a bounded TTL cache.
- AC12.2: THE SYSTEM SHALL complete the memory pre-filter in ≤ 20ms p50 on cache hit and ≤ 100ms p50 on miss, never blocking engine start beyond that budget.
- AC12.3: IF the lookup exceeds budget THEN THE SYSTEM SHALL proceed with a cache-or-empty hint and attach the late result to the next step, never stalling the current decision.

**Edge Cases:**
- Event loop unavailable (unit tests) → Synchronous direct call permitted behind an explicit allowlist flag, never in production path.

---

### REQ-13: Reviewer Verdict Consumer (pass | refine | veto)
**User Story:** As the DER loop I want the per-step Reviewer verdict scored by the engine so that the hottest Brain verdict in the loop costs ~40ms instead of a full reasoning call.

**Verified:** NEW — verdict comes from a Brain JSON call against the prompt at `backend/agent/der_loop.py:1109-1122`, parsed at `:1125-1141`.

**Acceptance Criteria:**
- AC13.1 (foundation): THE SYSTEM SHALL add a `review_verdict` engine consumer scoring `pass | refine | veto` over the same envelope-view inputs, wired in shadow mode (records rows, Brain verdict still decides).
- AC13.2 (foundation): WHEN the engine scores `refine` THEN THE SYSTEM SHALL still use the Brain to write the `refined` text; the engine never writes step descriptions.
- AC13.3 (optimize): WHEN calibration shows P(verdict | confidence ≥ threshold) ≥ 0.90 over ≥ 50 rows THEN THE SYSTEM SHALL enforce the engine verdict and skip the Brain call on `pass`.
- AC13.4 (optimize): THE SYSTEM SHALL measure Brain-token spend per reviewed step before and after, and report the saving in the Wave 7 gate.

**Edge Cases:**
- Engine unavailable or below threshold → Brain path exactly as today; no behavior change.
- `refine` without usable text from Brain → Fall back to `pass` with the gap logged, never block the step.

---

### REQ-14: Loop-Monitor Bool Consumers (Sufficiency, Done-Bit, Drift)
**User Story:** As the DER loop I want binary monitor questions answered by the engine so that three per-turn Brain calls shrink to one conditional text write.

**Verified:** NEW — three Brain bool+text calls: sufficiency gate (`backend/agent/agent_kernel.py:13361-13411`, prompt at `:13372-13404`), Explorer done/next-goal (`:18261-18306`, prompt at `:18288`), FULL-mode drift check (`:18382-18397`, prompt at `:18382`). **Line refs re-pinned 2026-09-25:** the first edition's `:18102-18121` and `:18202-18214` pointed at unrelated contract-amendment and `done_summary` code — both sites had drifted ~150 lines.

**Acceptance Criteria:**
- AC14.1 (foundation): THE SYSTEM SHALL add engine consumers for the three bools (`sufficient`, `done`, `on_track`) in shadow mode with the Brain calls unchanged.
- AC14.2 (foundation): WHEN a bool scores negative THEN THE SYSTEM SHALL call the Brain for the text part only (`missing` / next-goal `description` / `note`+`suggestion`); the engine never writes assessments.
- AC14.3 (optimize): WHEN a bool scores positive above its measured threshold THEN THE SYSTEM SHALL skip its Brain call entirely.
- AC14.4 (optimize): THE SUFFICIENCY gate SHALL keep its advisory-fail-closed shape (inference/parse failure returns `(False, "")`), with engine failure feeding the same path.
- AC14.5 (optimize): THE SYSTEM SHALL report per-site Brain-call skip rate in the Wave 7 gate.
- AC14.6 (foundation, 2026-09-25): THE ENGINE SHALL expose the three monitor judgments through a `Noul`-shaped envelope — a single calibrated probability of truth, distinct from a two-option Choice. Rationale: JEV's Noul returns P(statement true) with no separate confidence field; a 2-way softmax is not the same object, and REQ-14 AC14.4's fail-closed gate semantics depend on the probability meaning what it claims. `Noul` does not exist in the codebase today (`grep -ri noul backend/` → zero hits) despite `docs/architecture/tool-decision-engine.md:148-149` claiming the primitive is reproduced.

**Edge Cases:**
- Goal-contract open facts exist (`_goal_contract_open_facts` non-empty) → The done-bit honors the contract override exactly as today, regardless of the engine score.

---

### REQ-15: Heuristic Replacement Consumers (Mode + Web Intent)
**User Story:** As the router I want keyword-phrase heuristics replaced by calibrated engine scoring so that routing stops breaking on phrasing variants.

**Verified:** NEW — keyword inference in `ModeDetector.detect` (`backend/agent/mode_detector.py:43-80`, called at `backend/agent/agent_kernel.py:7274-7284`); three copies of the web-trigger list (`agent_kernel.py:6723-6751`, `:6753-6782`, `explorer.py:53-69`).

**Acceptance Criteria:**
- AC15.1 (foundation): THE SYSTEM SHALL add a `mode` engine consumer (6 options) shadowing `ModeDetector`'s keyword branch; slash-command overrides stay deterministic and always win.
- AC15.2 (foundation): THE SYSTEM SHALL replace the hand-set `ModeResult.confidence` float with the engine's measured confidence on the inference branch.
- AC15.3 (foundation): THE SYSTEM SHALL fold the three web-trigger copies into one `web_intent` engine consumer (or the `tool_choice` menu) and delete the duplicated lists.
- AC15.4 (optimize): WHEN per-class accuracy ≥ 0.90 over ≥ 50 rows THEN THE SYSTEM SHALL enforce the engine branch; keyword lists remain only as the engine-unavailable fallback.

**Edge Cases:**
- Empty or garbage input → `IMPLEMENT` default exactly as today (`mode_detector.py` fallback preserved).
- Engine unavailable → Keyword branch runs unchanged; no routing regression possible.

---

### REQ-16: No-Bypass Resolver Consistency (propose + RespondDirect)
**User Story:** As the calibrator I want every tool-choice path scored by the engine so that no traffic escapes the ledger and no path pays Brain cost the engine could carry.

**Verified:** NEW — the RespondDirect ReAct loop chooses tools via native function calling outside the box (`backend/agent/agent_kernel.py:3132-3176`), so that traffic never reached the ledger.

**CORRECTED 2026-09-26 (session 357 — BLUEPRINT-DIVERGENT row, Phase -1.0 grounding gate run retroactively):** this requirement originally cited `explorer.propose()` (`explorer.py:146-214`) as the live defect. That citation is stale: `propose()` has **no production caller** (`grep -rn "propose(" backend/` finds it only in tests). The live resolver is `ToolDecisionBox.resolve()` (`agent_kernel.py:15241`), and it **already runs `_engine_try()` engine-first before `_resolve_legacy()`** (`tool_decision.py:1133`) — so the user story's "no path pays Brain cost the engine could carry" objective is already satisfied on the live path. AC16.1's ladder is nonetheless implemented in `propose()` exactly as this AC specifies, and is verified against BOTH the AC's letter and the live seam. `propose()` is deliberately **kept, not deleted**: it is the only implementation of the deterministic backstop chain (web-intent → pheromone top-1 → reasoning) that `_resolve_legacy` lacks.

**Acceptance Criteria:**
- AC16.1 (foundation): `propose()` SHALL score an engine Choice over `live_tools` before the Brain single-shot; Brain runs only on engine decline/below-threshold. — **SCOPE NOTE (2026-09-26):** `propose()` is not on the live resolver path (see the CORRECTED note above). The LIVE equivalent is `ToolDecisionBox._engine_try()` (`tool_decision.py:1133`), which already runs engine-first. This AC is retained as the contract for the `propose()` entry point and is proven by `tests/behavioral/test_propose_path.py::test_engine_before_brain`. If `propose()` is ever deleted, this AC must be **re-pointed at `_engine_try`**, never silently dropped.
- AC16.2 (foundation): THE SYSTEM SHALL route RespondDirect tool calls through `ToolDecisionBox` or record shadow engine rows for them, so calibration sees 100% of tool-choice traffic.
- AC16.3 (optimize): THE SYSTEM SHALL report the share of `propose()` resolutions settled without Brain spend in the Wave 7 gate.

**Edge Cases:**
- `live_tools` empty → Today's fallback chain unchanged (web-intent → pheromone → reasoning).
- RespondDirect latency budget hot → Shadow-record only, never add latency to the fast chat path.

---

### REQ-17: Triage Growth on the Recovery Consumer (retry | graft | escalate)
**User Story:** As the DER loop I want retry-vs-graft-vs-escalate triage scored by the engine so that heuristic counters stop owning recovery routing.

**Verified:** NEW — counters own triage today; REQ-11's `recovery_strategy` consumer (`retry_different_tool` / `decompose` / `escalate`) is the seam (extends REQ-11, needs Wave 1 + Wave 5 green).

**Acceptance Criteria:**
- AC17.1 (foundation): THE SYSTEM SHALL extend the `recovery_strategy` consumer with a `retry_same` option and consult it at each failure triage point in shadow mode.
- AC17.2 (foundation): HEURISTIC counters SHALL remain the deciders until the consumer passes its calibration bar; the engine only records.
- AC17.3 (optimize): WHEN P(correct triage | confidence ≥ threshold) ≥ 0.90 over ≥ 50 rows THEN THE SYSTEM SHALL enforce engine triage; counters stay as the engine-unavailable fallback.

**Edge Cases:**
- Critical-step failure past graft budget → Escalation path (REQ-10 of the DER model) fires regardless of engine score; safety overrides calibration.

---

### REQ-18: Calibration Quality (Reliability, ECE, Brier) & Tau Resolution
**User Story:** As the calibrator I want the engine's reported confidence to be measurably calibrated so that an enforcement threshold means what it claims.

**Verified:** NEW (2026-09-25) — REQ-6 measures precision-at-threshold only; a reliability curve, ECE, or Brier score appears nowhere in the spec or the code (`grep`: no `ECE`/`Brier`/`reliability` outside D7's prose). `P(correct | conf ≥ 0.85) ≥ 0.92` is satisfiable by a badly miscalibrated model (e.g. reporting 0.99 while correct 60% of the time). Separately, `EngineConfig.softmax_tau = 0.5` (`decision_engine.py:126`) sharpens the softmax specifically to cross the 0.85 gate — the inline comment concedes the raw distribution "spreads across 0.28–0.53 — rarely crossing 0.85 even on clear cases" — and a monotone sharpening inflates confidence without changing accuracy ordering, which is calibration-destroying by construction. This is the single most important JEV property (RLCD exists to guarantee it) and the spec currently asserts it without measuring it.

**Acceptance Criteria:**
- AC18.1: THE SYSTEM SHALL compute a reliability curve, Expected Calibration Error (ECE), and Brier score for engine decisions over the labeled battery, bucketed by reported confidence.
- AC18.2: `scripts/calibrate_decision_threshold.py` SHALL report ECE and Brier alongside the existing precision-at-threshold figure.
- AC18.3 (REVISED 2026-09-25): THE SYSTEM SHALL NOT apply any fixed sharpening transform to the reported distribution. `softmax_tau` (`decision_engine.py:126`) is **deleted** with the LFM path — GLiNER's schema softmax is natively calibrated (measured: all errors ≤ 0.352, 100% accuracy above 0.40), and sharpening would destroy that property. If a future backend's distribution is measured uncalibrated, a **fitted** monotone map (temperature scaling fit to the ledger) is permitted; a hard-coded constant is not.
- AC18.4: THE SYSTEM SHALL gate every enforcement flip (REQ-13–17) on BOTH the existing precision bar AND an ECE bound, so no consumer is enforced on an uncalibrated distribution.
- AC18.5: WHEN the engine is unavailable or the battery is under the row floor THEN THE SYSTEM SHALL report INSUFFICIENT_DATA and SHALL NOT report a calibration verdict.

**Edge Cases:**
- All decisions land in one confidence bucket → ECE is reported with a low-confidence flag, never silently passed.
- `softmax_tau` set to 1.0 (sharpening disabled) → Calibration measured on the raw distribution; AC18.3's honesty clause applies.

---

### REQ-19: Per-Consumer Criteria — **REVISED to schema `Task`s**

> **REVISED 2026-09-25 (model decision, REQ-21).** The original requirement was to give each
> consumer its own *prompt head* with a cached KV state, because the LFM backend shared one
> tool-selection head across all consumers (`decision_engine.py:356-373`, warmed only for
> `"tool_choice"` at `:304`). The GLiNER backend expresses the same intent **natively and more
> cheaply**: each consumer is a `Task(name, labels, instruction, exclusive)` in the schema, and
> the runner builds the structure tokens per call (`gliner_onnx.py:Task.tokens`). No prompt
> heads, no KV-cache management. AC19.1/AC19.2 are restated for the schema shape; AC19.3/AC19.4
> are unchanged in intent.

**User Story:** As the engine I want each consumer scored against its own instructions and
label set so that the probabilities reflect the question actually being asked.

**Verified:** NEW (2026-09-25) — consumer-independence was absent from the LFM backend (constant
head at `decision_engine.py:356-373`); the GLiNER backend supplies it structurally via `Task`.

**Acceptance Criteria:**
- AC19.1 (REVISED): THE ENGINE SHALL express each consumer as a `Task` carrying its own
  `instruction` and label set, rather than reusing one shared head across consumers.
- AC19.2 (REVISED): WHEN multiple consumers are scored in one call THEN THE SYSTEM SHALL pass
  them as separate `Task`s in a single request rather than issuing N sequential calls.
- AC19.3: THE SYSTEM SHALL assert, per consumer, that the `Task` used for scoring matches that
  consumer's registered specification — guarding against silent reuse of another consumer's
  labels or instruction.
- AC19.4: `tool_choice` scoring behavior SHALL be unchanged by the per-consumer refactor,
  regression-guarded by the existing calibration battery.

**Edge Cases:**
- Consumer registered without criteria → The engine refuses to score it and degrades to the legacy path, rather than scoring under another consumer's head.
- Head-cache memory bound exceeded → The least-recently-used head is evicted; correctness is unaffected (cold head = one extra prefill).

---

### REQ-20: Parallel Multi-Question Scoring — **SATISFIED NATIVELY by REQ-21**

> **SATISFIED 2026-09-25 (model decision, REQ-21).** The GLiNER backend accepts **multiple
> `Task`s in a single call** and evaluates them against the same text in one encoder pass — the
> property this requirement was written to build. No batching layer is needed; AC20.1/AC20.2
> become "pass more than one `Task`" and AC20.3 becomes a verification of the vendor property
> on our battery. AC20.4's graceful-degradation clause still applies.

**User Story:** As the runtime I want several judgments about one state answered in a single
forward pass so that adding questions does not multiply latency.

**Verified:** NATIVE (2026-09-25) — `gliner_onnx.GlinerOnnx.probabilities(text, tasks)` takes a
list of `Task`s and returns one distribution per task from a single `session.run`
(`gliner_onnx.py:83-99`). The earlier LFM backend answered exactly one question per forward pass.

**Acceptance Criteria:**
- AC20.1 (REVISED): THE ENGINE SHALL expose a batched scoring entry point that answers N typed
  questions against one state in a single ONNX session run.
- AC20.2 (REVISED): WHEN multiple consumers ask about the same step state THEN THE SYSTEM SHALL
  pass them as multiple `Task`s in one call rather than N sequential calls.
- AC20.3: THE SYSTEM SHALL demonstrate on the labeled battery that batching two questions does
  not exceed 1.5× the single-question p50 latency.
- AC20.4: IF the batched call fails or the engine is unavailable THEN THE SYSTEM SHALL degrade
  to the per-consumer path unchanged, returning the same envelope shapes.

**Edge Cases:**
- Batched questions exceed the context budget → The batch is split into the smallest number of calls that fit; no question is silently dropped.
- One question in a batch is malformed → That question returns a per-question error envelope; the other answers are unaffected (per-question isolation).

---

### REQ-21: ONNX Decision Backend (GLiNER2.5-Decide Replaces LFM2-350M)
**User Story:** As the runtime I want tool choice scored by a calibrated classification model in-process on CPU so that decisions are accurate, honest about their confidence, and fast enough for the loop.

**Verified:** MEASURED (2026-09-25) — `GLiNER2.5-Decide` via `nishparadox/gliner2.5-decide-onnx`
scores **71.7% accuracy at 119 ms p50** on the 60-case labeled battery, versus the incumbent
LFM2-350M-Extract's 60.0% at 1172 ms (flat) and 33.3% at 5399 ms (production `decide_tree`).
Its confidence is natively calibrated (all errors ≤ 0.352; 100% above 0.40). The torch-free
runner needs only `onnxruntime` + `tokenizers` + `numpy`, all already installed. Evidence:
`BENCH-2026-09-25-model-comparison.md`; amendment: `docs/architecture/tool-decision-engine-improvements.md` §10.

**Acceptance Criteria:**
- AC21.1: THE SYSTEM SHALL score candidate options by supplying them as the label set of a schema `Task` to an ONNX-exported `GLiNER2.5-Decide` session, replacing the LFM logit-continuation path.
- AC21.2: THE ENGINE SHALL return the unchanged `DecisionScore` envelope (`consumer_id`, `chosen`, `confidence`, `distribution`, `engine_latency_ms`) so that **no caller changes**.
- AC21.3: THE ENGINE SHALL run wholly on `onnxruntime`'s `CPUExecutionProvider` with zero VRAM allocation (CT-DEI-1 preserved).
- AC21.4: THE ENGINE SHALL NOT load, retain, or fall back to a second resident model. On load failure, session error, or timeout it SHALL return `None` and callers SHALL take their existing legacy-heuristic path.
- AC21.5: `onnxruntime` and `tokenizers` SHALL be declared in `requirements.txt`, and the ONNX model directory SHALL be configurable with a startup availability check that degrades cleanly when absent.
- AC21.6 **(AMENDED 2026-09-25)**: THE SYSTEM SHALL remove the LFM-only machinery: `_score_options_one_pass`, `_letter_token_ids`, `_warm_head_state`, `softmax_tau`, `decide_tree` for tool choice, **and the LFM-only config fields that go dead with it** — `n_gpu_layers` (`decision_engine.py:130`; consumed only at `:264` and `:268`, both passing to `Llama`), `hierarchy_trigger` (`:121`; **defined and read nowhere — already dead**), and `max_answer_tokens` (`:106`; no reader found). Also remove the `IRIS_DECISION_GPU_LAYERS` env knob (`:264`). Leaving these behind re-creates exactly the decorative-config defect REQ-25 exists to fix. **Keep** the `DecisionScore`/`ArgsResult` envelope and `gate()` — callers depend on both.
  - **⚠️ REQ-NUMBER COLLISION (do not be misled):** the `hierarchy_trigger` comment at `decision_engine.py:119-121` cites **"(REQ-17)"**, but that is the **OLD** REQ-17 (hierarchical selection), which no longer exists. In THIS spec **REQ-17 is "Triage Growth on the Recovery Consumer"** — an unrelated requirement. The collision resolves itself when `hierarchy_trigger` is deleted with the rest of the LFM path; until then, do not read that comment as pointing at the current REQ-17.
- AC21.7: THE SYSTEM SHALL report the backend in the decision envelope/ledger (`engine` field) so calibration rows distinguish the new backend from historical LFM rows.
- AC21.8 **(2026-09-25 — menu-composition coverage)**: THE SYSTEM SHALL verify that the **PRODUCTION** menu-composition path (`backend/agent/tool_decision.py:617-621` — registry names plus the `DELEGATE` / `NONE` control labels, AFTER pre-filter and cap) produces a label set the backend scores correctly, with **no duplicate labels** and with the control labels **surviving the cap**. Rationale: the 60-case battery builds its **own** menu (`bench_decision_models.py:102-103` appends the control labels; `build_menu` is fixture-driven), so it replicates the menu **shape** but does **not** execute the production composition code. The measured 71.7% / 100%-above-0.40 result therefore does **not** by itself prove the production path — and the cap now ships at 6 (REQ-25 AC25.7), so whether the control labels can be pushed out of a 6-wide menu is untested. Also guards the collision case: a registry tool literally named `NONE` or `DELEGATE` would duplicate a label.

**Edge Cases:**
- ONNX model or tokenizer missing → engine unavailable; callers use the legacy path; one structured warning, no crash.
- Session init slower than the acquire timeout → return `None`; never block the DER thread.
- Label set larger than the battery tested → allowed; candidate cap is re-evaluated (REQ-22) rather than assumed.
- `int8` quantization drift → thresholds validated against the deployed variant, not the fp32 reference.

---

### REQ-22: Distribution Retune & Calibration for the Schema Softmax
**User Story:** As the calibrator I want the decision threshold derived from the new backend's measured reliability curve so that auto-execution is safe at a known coverage.

**Verified:** MEASURED (2026-09-25) — the LFM-era threshold of 0.85 is wrong for GLiNER's
distribution, which spreads over the candidate menu. Measured curve: 0.30 → 63.3% coverage /
86.8% accuracy; 0.35 → 45.0% / 96.3%; **0.40 → 38.3% / 100.0%**; 0.45+ → 100% accuracy at
declining coverage. All 17 errors carry confidence ≤ 0.352.

**Acceptance Criteria:**
- AC22.1 **(AMENDED 2026-09-25 — Decision C follow-up)**: THE SYSTEM SHALL source the `tool_choice` threshold from the **active backend's** entry in `backend_thresholds` (**0.40** for the schema-softmax backend, replacing 0.85). **There are THREE threshold sources in the code today and all three must be reconciled** — an agent that changes only one will silently tune the WRONG consumers:
  1. `ToolDecisionBox.__init__(decision_threshold=0.85)` (`backend/agent/tool_decision.py:333`, stored at `:370`) — **this is what `tool_choice` actually reads** (`:639`, `:678`, `:700`), and it is never passed at its single construction site (`backend/agent/agent_kernel.py:14967`), so it is hardcoded at 0.85.
  2. `EngineConfig.default_threshold` (`backend/agent/decision_engine.py:109`, default 0.85) — read via `threshold_for()` (`:136-137`) for `presentation` and `narration`.
  3. `EngineConfig.thresholds` (per-consumer overrides, `:113`) — sits on top of the above.
  **⚠️ `EngineConfig.default_threshold` is NOT the `tool_choice` threshold.** Editing it alone (or the YAML alone) would move `presentation`/`narration` while leaving `tool_choice` at 0.85 — the exact opposite of this AC's intent.
- AC22.2: `scripts/calibrate_decision_threshold.py` SHALL report the coverage/accuracy-above-threshold curve for the deployed backend so the operating point is re-derivable, not hard-coded.
- AC22.3: THE SYSTEM SHALL keep `decide_tree` retired for tool choice; flat scoring over the candidate set SHALL be the only path (measured: the hierarchy cost 26.7 accuracy points and 4.6× latency).
- AC22.4: WHEN a consumer's measured accuracy-above-threshold is below 0.90 THEN THE SYSTEM SHALL keep it in shadow and record the gap; enforcement SHALL NOT flip on an unmeasured or sub-bar curve.
- AC22.5: THE SYSTEM SHALL record the deployed model variant (`int8` / `fp16` / `fp32`) on calibration rows, since `int8` is lossy (`max |ΔP| ≤ 0.18`) and thresholds are variant-specific.

**Edge Cases:**
- Battery below the row floor → report INSUFFICIENT_DATA, never a verdict.
- Variant swapped without recalibration → the recorded variant mismatch SHALL mark thresholds stale.

---

> **Amendment 2026-09-25 (c) — Wave 9–13: foundation integrity, post-swap performance, the
> evidence seam, surface completion, and operating-point fine-tuning.** REQ-23–REQ-31 were
> added after a code-verified audit of the whole application surface (all Brain call sites,
> all keyword classifiers, the engine's own gates, and the result cache). Every claim below was
> traced against live code; each `Verified:` line carries the file:line it was traced to. Three
> findings are prerequisites for requirements already written: **T31 edits a config value
> nothing reads (REQ-25)**, **Wave 6's seven consumers all depend on an observer seam that
> returns nothing (REQ-23)**, and **the result cache omits the evidence payload (REQ-27)**, so
> REQ-28's prior would be silently swallowed. Waves 9–13 are ordered so each wave's gate
> verifies the engine before the next wave builds on it. Under **Decision C** the operating
> point is CONFIRMED rather than re-derived: `candidate_cap` ships at the calibrated width (6),
> so **TG-7 remains the authoritative enforcement gate** and TG-13 fires only if the deployed
> configuration actually moves.

### REQ-23: Presentation Observer Seam Integrity
**User Story:** As the calibrator I want the already-wired `presentation` consumer to return its verdict in shadow and to observe card turns with a truthful frame so that the one consumer that steers production produces usable calibration data.

**Verified:** NEW (2026-09-25) — `AgentKernel._engine_gate_surface` (`backend/agent/agent_kernel.py:14233-14302`) returns `None` whenever `not (enforced and confident)` (`:14299-14300`), early-returns on `_last_render_emitted` (`:14250-14252`), and hardcodes `"card_already_rendered": False` (`:14262`). Two tests pin the opposite and are RED: `test_shadow_verdict_returned_for_calibration_never_steers` and `test_card_turn_still_observed_with_truthful_frame` (`backend/tests/behavioral/test_decision_engine_gates.py:241,267`). Both landed 2026-09-24 (`528a9435`); the gate was last touched 2026-09-21 (`fdead349`), so the requirement is documented and simply not implemented. The steering field `_last_surface_choice` is written at `:14269`/`:14301` and read nowhere (grep: 3 hits, all writes). Per the TEST RULE the tests are the requirement — the gate is fixed, the tests are not edited.

**Acceptance Criteria:**
- AC23.1: WHEN the `presentation` consumer is NOT enforced THEN THE GATE SHALL return the engine verdict to its caller for calibration, and SHALL NOT steer the surface.
- AC23.2: WHEN a card was already rendered this turn THEN THE GATE SHALL still produce an observer verdict, and the frame SHALL carry `card_already_rendered: true`.
- AC23.3: THE GATE SHALL NOT write `_last_surface_choice` or any other steering field on any path.
- AC23.4: WHEN the engine is unavailable THEN THE GATE SHALL return `None` and the caller's legacy path SHALL run unchanged.
- AC23.5: THE GATE SHALL emit the same meta row shape on both the enforced and shadow paths, with `route` distinguishing them, so calibration joins uniformly.
- AC23.6: THE GATE SHALL remain gate-layer only — surface choice, never content.

**Edge Cases:**
- Card already rendered AND engine unavailable → `None`, no row, no steering write.
- Enforced + confident on a card turn → verdict still returned; the render sites keep owning one-card-per-turn (AC11.4 moved there, not deleted).

### REQ-24: Failure-Evidence Supply Integrity
**User Story:** As the DER loop I want the graph's high-signal failure warnings to actually reach the engine frame so that REQ-11's veto has a working upstream instead of a function that always reports "nothing wrong".

**Verified:** NEW (2026-09-25) — `_get_failure_warnings` (`backend/agent/agent_kernel.py:5975-5993`) calls `ResolutionEncoder.encode_with_resolution(task, conn)` with a `str`, while the signature is `encode_with_resolution(failure: Dict, conn=None)` (`backend/memory/mycelium/interpreter.py:24`). `.get()` on a `str` raises, `except Exception: pass` swallows it, and the function **always returns `"None"`**. Called at `:6296` and `:9067`. The return contract is additionally ambiguous: six test files stub it, four as `lambda text: "None"` and one as `lambda text: []` (`backend/tests/behavioral/test_narration_beats_behavior.py:70`).

**Acceptance Criteria:**
- AC24.1: THE FUNCTION SHALL construct the failure dict from the session's recorded failure state and pass a `Dict` to `encode_with_resolution`.
- AC24.2: THE FUNCTION SHALL have ONE settled return type (`str`), and every caller and test stub SHALL be consistent with it.
- AC24.3: IF no failure state is available THEN THE FUNCTION SHALL return the documented empty value and SHALL NOT raise.
- AC24.4: WHEN a failure warning exists THEN THE SYSTEM SHALL carry it into the engine frame as veto evidence (REQ-11 `ruled_out`).
- AC24.5: THE FUNCTION SHALL NOT silently swallow a programming error — a non-recoverable failure SHALL be logged with its exception type and the function name.
- AC24.6: THE SYSTEM SHALL record on the decision row whether failure evidence was supplied and applied.

**Edge Cases:**
- Failure state present but the encoder returns empty → documented empty value, no veto.
- Exception type outside the expected class → logged with type, never silently `"None"`.
- Memory interface absent (unit tests) → documented empty value, no raise.

### REQ-25: Decision Config Authority
**User Story:** As the tuner I want the `decision_driver` configuration to be the authority for engine behaviour so that changing a documented value actually changes behaviour.

**Verified:** NEW (2026-09-25) — `grep -rn "decision_driver" backend/ --include=*.py` returns **zero hits**. The block (`backend/agent/agent_config.yaml:22-32`) declares `n_ctx`, `candidate_cap: 32`, `acquire_timeout_s: 2.0`, `default_threshold: 0.85`, `device`, `dtype` — **none of it is parsed**. `EngineConfig` (`backend/agent/decision_engine.py:103-131`) is always built from code defaults (`candidate_cap=6`, `default_threshold=0.85`), and `get_decision_engine()` (`:712`) accepts no config. Consequence: **T31 as written edits a value nothing reads, and `candidate_cap: 32` is decorative.** The effective cap (6) is what `ToolDecisionBox` reads via `engine._cfg.candidate_cap` (`tool_decision.py:534`).

**Acceptance Criteria:**
- AC25.1: THE SYSTEM SHALL parse the `decision_driver` block into `EngineConfig` at engine construction.
- AC25.2: WHEN a documented key is present THEN THE ENGINE SHALL use the parsed value, and the EFFECTIVE configuration SHALL be observable (logged or exposed) for verification.
- AC25.3: IF a key is absent or malformed THEN THE ENGINE SHALL fall back to the code default and log the fallback once.
- AC25.4: THE SYSTEM SHALL treat `candidate_cap` as live — the cap used for menu construction SHALL equal the effective configured value.
- AC25.5: WHEN `candidate_cap`, the backend, or the deployed variant changes THEN THE SYSTEM SHALL mark the calibrated threshold STALE, because the curve was derived at the previous menu width (REQ-22 AC22.4, REQ-31 AC31.4).
- AC25.6: THE SYSTEM SHALL NOT leave a documented-but-unread key in place; every key in the block SHALL either be parsed or removed.
- AC25.7 (DECISION C, 2026-09-25): THE SHIPPED `candidate_cap` SHALL equal the menu width the current threshold curve was derived at (**6**), so that making the block live does NOT itself invalidate the calibration. The value MAY be changed later, but any change SHALL mark the threshold stale (AC25.5) and require re-derivation before enforcement. Rationale: the defect REQ-25 fixes is that the key was DECORATIVE, not that it held a particular number — making it read while shipping the calibrated value fixes the defect without re-opening settled enforcement flips.
- AC25.8 **(2026-09-25 — Decision C follow-up)**: THE SYSTEM SHALL key thresholds by **BACKEND IDENTITY** (`backend_thresholds`), not by a single global number, and SHALL **REFUSE ENFORCEMENT** when the active backend has no entry (fail-closed). Rationale: a probability threshold is only meaningful for the distribution it was measured on — 0.85 suits LFM's sharpened softmax, 0.40 suits GLiNER's menu-wide softmax. This **removes the T35→T31 ordering hazard**: whichever lands first, the backend/threshold pairing is validated at runtime rather than depending on task order. It also makes a future model swap degrade to SHADOW rather than silently enforcing on the previous model's curve. This is the same staleness machinery as AC6.5 (model pin) and AC22.5 (variant recorded), extended from variant identity to backend identity — **not a new mechanism**.

**Edge Cases:**
- YAML absent entirely → code defaults, one warning, engine still works.
- Cap larger than the registry → clamps to available candidates, logged.
- Cap smaller than the number of required menu members (vision tools, `NONE`, `DELEGATE`) → clamp with a logged warning, never a silently truncated menu.
- Cap changed away from the calibrated width → threshold marked stale; enforcement refused until the curve is re-derived (AC25.5, REQ-31 AC31.6).

### REQ-26: Bounded Engine Waits and Latency Attribution
**User Story:** As the runtime I want every engine entry point bounded and every millisecond attributed so that no engine call can block the loop and every optimisation is measurable rather than assumed.

**Verified:** NEW (2026-09-25) — `generate_args` acquires with a bare `with self._lock` (`backend/agent/decision_engine.py:657`) and therefore has NO timeout, while `decide` uses `acquire_timeout_s` (`:476`, default 2.0). A grep for `scoring_latency_ms` / `args_latency_ms` across `backend/` and `scripts/` returns **zero hits**, so REQ-6 AC6.1's breakdown does not exist and `generate_args` cost is invisible; the engine records only `engine_latency_ms` inside the lock (`:495-500`), excluding load and lock wait.

**Acceptance Criteria:**
- AC26.1: EVERY engine entry point (`decide`, `generate_args`, and the batched entry point) SHALL acquire its lock with a bounded timeout and SHALL return a degraded result on overrun — never block indefinitely.
- AC26.2: THE ENGINE SHALL emit `scoring_latency_ms`, `args_latency_ms`, and `decision_latency_ms` per decision.
- AC26.3: THE ENGINE SHALL distinguish lock-WAIT time from compute time in the breakdown.
- AC26.4: IF the lock wait exceeds its budget THEN THE ENGINE SHALL return `None` and the caller SHALL take its legacy path.
- AC26.5: WHEN the deterministic fast-path applies (REQ-2) THEN `args_latency_ms` SHALL be recorded as approximately zero, not omitted.

**Edge Cases:**
- Lock held by a hung call → bounded wait, `None`, one structured warning, no retry storm.
- Engine unavailable before the lock → breakdown records unavailability, not a zero.
- Zero-token args path → `args_latency_ms ≈ 0` present on the row so `is_fast_path` joins cleanly.

### REQ-27: Engine Result Cache Correctness and Bounds
**User Story:** As the runtime I want the decision cache to key on everything that can change the answer and to stay bounded so that it never returns a verdict computed for a different context and never grows without limit.

**Verified:** NEW (2026-09-25) — `ToolDecisionBox._engine_cache` (`backend/agent/tool_decision.py:379`) is keyed on `((goal or "")[:200], tuple(names), (step or {}).get("task_class"), needs_vision)` (get `:584`, set `:624`) and is NEVER evicted — grep returns 3 hits, all init/get/set, no max size and no clear. Two defects: the key omits the memory hint and therefore any evidence payload, so an injected prior is silently ignored on a cache hit; and the dict is unbounded, against the project's own quality bar (`AGENTS.md`: "memory footprint bounded — no unbounded caches").

**Acceptance Criteria:**
- AC27.1: THE CACHE KEY SHALL include EVERY input that can change the verdict, including the evidence/prior payload (REQ-28) — present from day one even while that payload is always empty.
- AC27.2: THE CACHE SHALL be bounded with a documented maximum entry count and an eviction policy.
- AC27.3: WHEN the evidence payload differs for otherwise identical inputs THEN THE CACHE SHALL NOT return the other payload's verdict.
- AC27.4: A cache hit SHALL be recorded in meta as today and SHALL NOT be counted as a fresh engine decision for calibration.
- AC27.5: THE CACHE SHALL NOT be consulted on a path whose inputs are not fully represented in the key.

**Edge Cases:**
- Evidence empty for both entries → key remains stable and the cache still functions.
- Cache at capacity → oldest entry evicted, memory bounded, no behavioural change beyond a recompute.
- Candidate list order differs → the key treats ordering as significant, or normalizes it deliberately and documents which.

### REQ-28: Evidence Seam — Read-Only Graph Consumption
**User Story:** As the decision engine I want the graph's learned evidence handed to me in a defined shape and context so that I can weigh it as a prior without ever becoming a writer of the graph.

**Verified:** NEW (2026-09-25) — the engine currently receives only a PRUNED MENU: `_apply_pre_filter` plus a `veto` set plus a `Decision(source="memory")` short-circuit (`backend/agent/tool_decision.py:513-514`, `:1015-1020`, `:664-665`). The pheromone posterior exists and is read elsewhere (`BehavioralPredictor.predict`, `backend/memory/mycelium/interpreter.py:251-323`), but is never presented to the engine as evidence. **The engine writes nothing**: the `tool_choice` edge writes belong to the EXECUTION layer (`record_region_mediator_outcome`, `backend/agent/agent_kernel.py:16143`), derived from `_der_mediator_for(item)` — the executed item, not the engine's choice. **Owner decision (2026-09-25): the engine must never feed the pheromone loop; this REQ is read-only by construction.**

**Acceptance Criteria:**
- AC28.1: THE ENGINE FRAME SHALL carry an `evidence` field shaped to hold per-candidate prior evidence, and SHALL accept it UNPOPULATED — no caller supplies it within this spec's scope.
- AC28.2: WHEN evidence is supplied THEN THE SYSTEM SHALL attach the posterior LOWER BOUND and its observation count, scoped to the candidate's region and mediator — never a bare global score.
- AC28.3: THE ENGINE SHALL treat evidence as a WEIGHTED PRIOR that its own evidence can outvote; evidence SHALL NOT be able to raise a candidate above the consumer threshold on its own.
- AC28.4: THE ENGINE SHALL NEVER WRITE to the memory/graph store, and a contract test SHALL assert zero writes on every decision path.
- AC28.5: WHEN evidence arrives after the decision budget THEN THE SYSTEM SHALL proceed without it and SHALL NOT stall or re-decide (the REQ-12 AC12.3 late-attach shape).
- AC28.6: THE SYSTEM SHALL record on the decision row whether evidence was PRESENT and whether it was USED, so calibration can measure whether it helped.
- AC28.7: THE SYSTEM SHALL distinguish "evidence retrieved" from "evidence used" — an unused retrieval SHALL NOT be scored as a success.
- AC28.8: WHEN evidence is supplied THEN the system SHALL attach its FRESHNESS and its scope (region + mediator) alongside the value, so a stale or out-of-scope posterior is identifiable rather than silently trusted.

**Edge Cases:**
- Evidence for a candidate absent from the menu → ignored, logged once.
- Evidence stale beyond its freshness bound → treated as absent.
- All candidates carry evidence → the prior reorders, and cannot manufacture confidence.
- No evidence supplied (this spec's scope) → behaviour is byte-identical to today, guarded by a regression test.
- **REQ-28 ships UNEXERCISED — stated plainly.** No caller supplies an evidence payload within this spec's scope, and `specs/wormhole-aperture/` is not implemented. The seam is deliberately **inert, not proven**: its behaviour against a real provider is UNVERIFIED until one exists. The ACs here constrain the shape and the safety properties (read-only, outvotable, cannot manufacture confidence, absent = byte-identical); they do not claim the prior improves decisions. Any future claim that it helps must be measured on the ledger (AC28.6/AC28.7) before enforcement.

### REQ-29: Remaining Decision Surface Consumers (shadow-first)
**User Story:** As the runtime I want the remaining choice-shaped Brain calls scored by the engine in shadow so that the ledger sees all of them before any is enforced.

**Verified:** NEW (2026-09-25) — four sites missed by the §8.4 wiring survey: `trailing_director.py:100` (`self.adapter.infer(prompt, role="REASONING", max_tokens=800, temperature=0.1)` **per completed step**, when the common case needs only a negative bool); `agent_kernel.py:2411` (`_should_use_thinking`, a ~40-phrase list plus a social-short-circuit); `der_loop.py:513` (`incomplete_keywords` phrase list triggering escalation); `tool_decision.py:55/99/124` (`_vision_relevant` / `_goal_needs_action` / `_goal_records_terminal_failure` — the heuristics that gate the engine's OWN `NONE` commit). **Explicit NON-FIT:** `semantic_gate.tier0_classify` (`semantic_gate.py:372`) is documented pure, deterministic, no-I/O, no-model-call, resolving most traffic at <1ms — replacing it with a ~119ms model would be a REGRESSION, and only its neural/ontology fallback tier is a candidate.

**Acceptance Criteria:**
- AC29.1 (foundation): THE SYSTEM SHALL add a `has_gaps` consumer shadowing `trailing_director`, with the Brain writing gap items only when the engine scores positive.
- AC29.2 (foundation): THE SYSTEM SHALL add a `use_thinking` bool consumer shadowing the phrase list, with the list retained as the engine-unavailable fallback.
- AC29.3 (foundation): THE SYSTEM SHALL add an `escalate_incomplete` bool consumer shadowing the keyword list, with escalation and all budget safety behaviour UNCHANGED.
- AC29.4 (foundation): THE SYSTEM SHALL add a `needs_action` consumer shadowing the NONE-gate heuristics, preserving their documented SAFE direction (when in doubt, act).
- AC29.5: THE SYSTEM SHALL NOT score `tier0_classify`'s deterministic branch; the non-fit SHALL be recorded in Non-Requirements so it is not re-proposed.
- AC29.6 (optimize): each consumer flips to enforced only on the TG-13 measured bar, never on precision alone.
- AC29.7: WHEN the engine is unavailable THEN every one of these sites SHALL behave exactly as today.

**Edge Cases:**
- `has_gaps` positive → the Brain still writes the gap items; the engine never writes prose.
- Engine scores positive on `escalate_incomplete` → escalation still passes through the existing budget and veto-cap checks, which the engine may never permit.
- Goal carries a gather/action signal → `needs_action` returns the safe (True) direction regardless of engine score.

### REQ-30: Post-Swap Engine Performance (measured, not assumed)
**User Story:** As the tuner I want the ONNX backend tuned and measured against a recorded baseline so that the engine runs at its optimum on this CPU rather than at library defaults.

**Verified:** NEW (2026-09-25) — the reference runner sets only an optional `intra_op_num_threads` (`C:\temp\gliner-onnx\gliner_onnx.py:51-55`) and the bench never passes it, so ONNX defaults apply: no `inter_op_num_threads`, no `graph_optimization_level`, no `execution_mode`, no arena, no IO binding. Label positions are rebuilt per call. Warm-up exercises a 2-option menu (`main.py:847-870`, `decide("tool_choice", ["NONE","DELEGATE"], …)`) while real menus are 6+. `scripts/bench_decision_engine.py` records only load+warm and end-to-end wall time, with no breakdown.

**Acceptance Criteria:**
- AC30.1: THE ENGINE SHALL set explicit ORT session options (`intra_op_num_threads`, `inter_op_num_threads`, `graph_optimization_level`, `execution_mode`) sized to the host CPU, and SHALL record the effective values.
- AC30.2: THE ENGINE SHALL cache label positions per label set rather than re-tokenizing them on every call.
- AC30.3: WHEN multiple consumers are batched THEN THE SYSTEM SHALL perform ONE encode and ONE session run for the batch, VERIFIED rather than assumed.
- AC30.4: THE WARM-UP SHALL exercise a representative menu width (the effective `candidate_cap`), not a 2-option menu.
- AC30.5: THE ENGINE SHALL run inference off the shared step threads, so step scheduling cannot contend with it.
- AC30.6: `scripts/bench_decision_engine.py` SHALL report the latency breakdown (tokenize / encode / session / post) so any change is attributable to a stage.
- AC30.7: EVERY tuning change SHALL be measured against the recorded Wave 8 baseline with NO accuracy regression (BT-DEI-13 re-run green).
- AC30.8: IF a tuning change regresses p95 THEN THE SYSTEM SHALL record the regression and revert rather than keep it silently.

**Edge Cases:**
- Host has fewer cores than configured → clamp to available, logged.
- Label set changes between calls → cache keyed on the set, miss recomputes, correctness unaffected.
- Batching cannot share one encode for a given shape → recorded as a measured limitation, not silently N encodes.

### REQ-31: Operating-Point Confirmation & Conditional Re-Validation
**User Story:** As the calibrator I want the operating point CONFIRMED against the deployed configuration, and re-derived only when that configuration actually moves, so that settled enforcement flips are not needlessly re-opened and stale ones cannot survive.

**Verified:** NEW (2026-09-25) — the 0.40 threshold was derived at menu width 6. Under **Decision C (2026-09-25)** the config block becomes live (REQ-25) but ships `candidate_cap: 6` — the calibrated width — so the calibration remains valid and **Wave 7 / TG-7 stays the authoritative enforcement gate while the configuration is unchanged**. Re-validation becomes necessary only if the cap, backend, or deployed variant moves, because any of those alters the softmax spread the curve was read from.

**Acceptance Criteria:**
- AC31.1: THE SYSTEM SHALL CONFIRM the recorded operating point against the deployed backend, cap, and variant, and SHALL record the comparison — a match is a confirmation, not a silent assumption.
- AC31.2: THE SYSTEM SHALL report ECE and Brier alongside precision-at-threshold (REQ-18) at the deployed configuration.
- AC31.3 **[DEFERRED — see Decisions Locked]**: WHERE the owner elects to change the menu width THEN THE SYSTEM SHALL measure accuracy and latency across at least two widths and record the optimum BEFORE the change ships. The study is not a standing requirement; it fires only when a width change is actually proposed. Rationale: at the shipped width there is no second width to compare against, and an unrequested experiment would be over-build.
- AC31.4: WHEN the deployed configuration differs from the calibrated one THEN THE SYSTEM SHALL mark thresholds STALE and refuse enforcement.
- AC31.5: THE SYSTEM SHALL record, per consumer, the measured bar (rows, precision, ECE) that justified its enforcement flip or its continued shadow status.
- AC31.6 **(REVISED — Decision C):** WHILE the deployed configuration matches the calibrated one, Wave 7 / TG-7 SHALL remain the authoritative enforcement gate and this REQ SHALL NOT re-open settled flips. WHEN the configuration differs THEN re-validation SHALL fire and no flip measured at a superseded configuration SHALL stand.

**Edge Cases:**
- Battery below the row floor → INSUFFICIENT_DATA, never a verdict.
- Cap changed mid-calibration → the curve is marked stale and the run is repeated.
- A consumer passes precision but fails the ECE bound → stays in shadow, gap recorded.
- Configuration unchanged since Wave 7 → TG-13 confirms and closes; no flip is re-litigated.

---

## Non-Requirements (Out of Scope)

- Replacing the decision engine with **external hosted** cloud models or third-party routers (Laya, or any cloud decision API). **Note (2026-09-25):** the local model *is* changing — `LFM2-350M-Extract` → `GLiNER2.5-Decide` ONNX (REQ-21). The residency principle is unchanged; only the model is. This exclusion is about *hosted* dependencies, not about the local model choice.
- Retaining a second resident model as a fallback for the decision engine. There is exactly one decision model; failure degrades to legacy heuristics, not to another model.
- Allocating GPU VRAM to the Decision Engine (it must remain 100% CPU resident).
- Modifying the external tool execution signature expected by `AgentKernel`.
- Model-selection authority (local vs cloud routing) — owned by `specs/model-selection-authority/`; this spec only notes the engine as its future consumer.
- Engine-written prose of any kind (plans, summaries, refined descriptions, assessments, TTS text) — the engine scores options only.
- Engine-permitted safety, permission, veto-cap, or termination-budget decisions — deterministic code decides; the engine may advise, never permit.
- **`Score` (ordinal) primitive and consumers (2026-09-25):** JEV ships three primitives (Choice, Score, Noul); this spec adds only Choice and Noul shapes. No current consumer needs ordinal scoring, so `Score` is deliberately deferred rather than built speculatively. Its natural first home is the deferred model-selection-authority work (`specs/model-selection-authority/`), where a difficulty/quality score is genuinely needed. `Score` is a closed-set primitive (2–10 ordered levels), so it is not excluded by the no-prose rule — it is excluded by having no consumer yet.
- **Engine WRITES to the memory/graph store (2026-09-25):** the engine is READ-ONLY with respect to NBL. It consumes evidence (REQ-28) and never writes pheromone edges, edge scores, posteriors, or node state. The `tool_choice` edge writes belong to the execution layer (`record_region_mediator_outcome`, `agent_kernel.py:16143`). REQ-28 AC28.4 pins this with a contract test.
- **`semantic_gate.tier0_classify` engine scoring (2026-09-25):** the Tier-0 classifier (`semantic_gate.py:372`) is documented pure, deterministic, no-I/O and no-model-call, and resolves most traffic at <1ms with zero model work. Routing it through the engine would replace a sub-millisecond reflex with a ~119ms model call — a REGRESSION, not an improvement. It is recorded here so it is not re-proposed; only the neural/ontology fallback tier below it is a candidate, and no REQ in this spec claims it.
- **QA-Emb / interpretable question-answer embeddings (2026-09-25):** captured as a discussion document at `specs/wormhole-aperture/QA-EMB-DISCUSSION.md` and explicitly OUT OF SCOPE here. Nothing in this spec depends on it, and REQ-28's evidence seam is designed to accept an unpopulated payload so that a future provider can plug in without engine changes. `specs/wormhole-aperture/` is not implemented; no requirement here may assume it.
- **Changing the menu width within this spec (Decision C, 2026-09-25):** `candidate_cap` becomes LIVE under REQ-25 AC25.4 but SHIPS at **6** — the width the 0.40 curve was derived at (AC25.7). This spec does NOT authorise shipping a different cap. Any change marks the calibrated threshold stale (AC25.5, REQ-31 AC31.4) and requires the AC31.3 menu-width study plus a re-derived curve first. The study is therefore **DEFERRED, not dropped** — fully specified and ready, firing only when a width change is actually proposed. Mirrors the `Decisions Locked 14` pattern in `specs/wormhole-aperture/` (specified, gated, not early).

---

## Open Questions (resolve WITH the owner; non-blocking)

Raised by the 2026-09-25 JEV-fidelity review, then extended by the 2026-09-25 (c) surface audit.

**Resolved by the model decision or by later amendment — do not re-litigate:**

- ~~**OQ-DEI-2 (REQ-1/T23):** wire the warm-head snapshot or delete it?~~ **RESOLVED** — T23 is cancelled and T29 DELETES `_warm_head_state` outright (REQ-21 AC21.6). An encoder-only backend has no autoregressive prompt to cache, so there is nothing to wire.
- ~~**OQ-DEI-3 (REQ-18):** fitted calibration map vs. keep `softmax_tau`?~~ **RESOLVED** — AC18.3 deletes `softmax_tau` with the LFM path; GLiNER's schema softmax is natively calibrated. A fitted map is permitted only if a future backend measures uncalibrated.
- ~~**OQ-DEI-4 (Wave 7 bar):** ≥100 rows, or ≥500 for high-frequency consumers?~~ **RESOLVED** — ≥100 is the floor (Wave 7 / TG-13); TG-13 AC31.5 records the bar per consumer.
- ~~**OQ-DEI-5 (Score primitive):** defer or promote?~~ **RESOLVED** — deferred, recorded in Non-Requirements with its natural first home.
- ~~**OQ-DEI-7 (REQ-25 / REQ-31):** should `candidate_cap` ship at 32, 6, or be set by the menu-width study?~~ **RESOLVED — Decision C (owner, 2026-09-25).** The block becomes live but ships at **6**, the calibrated width, because the defect is that the key was DECORATIVE, not that it held a particular number. Result: the calibration stays valid, **Wave 7 / TG-7 remains the authoritative enforcement gate**, and the menu-width study (AC31.3) is DEFERRED rather than required. Recorded in Decisions Locked, AC25.7, and `agent_config.yaml`.

**Still open:**

- **OQ-DEI-1 (REQ-5 scope):** `_capture_screenshot_blob()` is duplicated at `tool_bridge.py:1709` (vision) **and** `:1719` (GUI). REQ-5 is written vision-scoped. Extend AC5.1–5.3 to the GUI site, or open a separate follow-up? (Recommend: extend — it is the same 100–250ms defect and the same fix.)
- **OQ-DEI-6 (REQ-23):** the shadow verdict must be RETURNED, but is the caller `_observe_surface_async` (`agent_kernel.py:14304`) the intended consumer, or does it need its own change to accept the returned verdict? The test pins the return value; this REQ pins the observer contract. (Recommend: confirm the observer is the consumer and pin its shape with a contract test.)
- **OQ-DEI-8 (REQ-28):** the exact evidence field set. AC28.2/AC28.8 require the posterior lower bound, observation count, scope (region + mediator) and freshness. Confirm whether anything else belongs (e.g. the tier that produced it) — and confirm the empty-payload behaviour is byte-identical to today.
- **OQ-DEI-9 (REQ-24):** the settled return type for `_get_failure_warnings`. Six test stubs disagree (`"None"` ×4, `[]` ×1). AC24.2 requires one type; `str` matches the majority and the callers. (Recommend: `str`, and fix the odd stub.)
- **OQ-DEI-10 (REQ-31):** the row floor for the operating-point gate now that REQ-29 adds four more consumers — keep a flat ≥100, or scale with consumer count? (Recommend: flat ≥100 as the floor, with the highest-frequency consumers held to the higher bar.)


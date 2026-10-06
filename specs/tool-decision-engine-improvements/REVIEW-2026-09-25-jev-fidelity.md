# Review: JEV Fidelity & Gap Analysis
**Subject:** `docs/architecture/tool-decision-engine-improvements.md` + `specs/tool-decision-engine-improvements/` (requirements / design / tasks)
**Date:** 2026-09-25
**Method:** read the doc and all three spec files; researched JEV (TypeSafe AI "System One") against official docs + third-party technical writeups; then traced every load-bearing claim against committed code.

---

## 0. Verdict (read this first)

The spec is **strong on latency mechanics and wiring** — the bottleneck diagnosis (tie-break loops, `generate_args`, `"what's"` token, lane truncation, screenshot dedup) is accurate and the Wave 0 probe / Wave 6-7 shadow-first discipline is genuinely faithful to JEV's "never set a threshold without calibration data" rule.

It is **thin on the four properties that actually make JEV *JEV***:

1. **Calibration honesty** — the spec measures precision-at-threshold and calls it calibration; the code *sharpens* the softmax, which destroys calibration by construction.
2. **Per-question criteria** — all consumers share one frozen tool-selection prompt head.
3. **Parallel multi-question scoring** — JEV's marquee property; the spec issues one question per forward pass.
4. **Primitive typing** — `Score` is absent; `Noul` is not modeled as a calibrated probability-of-truth.

Plus **three code-verified defects** where the doc/spec describe behavior the code does not have, and **two internal contradictions** in the doc itself.

---

## 1. What JEV actually is (research digest)

**JEV** = TypeSafe AI's first **"System One" model** (launched Sept 2026; `jev-1.13`, live on OpenRouter/Vercel/Cloudflare). Named after Kahneman's System 1 — fast, intuitive judgment — as distinct from the LLM "System 2" (slow, deliberate reasoning). It is explicitly **not a chat model and generates no text**.

**Core contract:** send a `state` (string / object / array) + typed `questions` → get typed `answers` with **calibrated probabilities and confidence**.

**The three primitives** (this is the part the spec under-uses):

| Primitive | Question | Returns |
| :--- | :--- | :--- |
| **Choice** | pick one of N labeled options (≤255) | `choice`, `probabilities` (per option), `confidence` |
| **Score** | rate on an ordered rubric (2–10 levels) | `score` (can be fractional), `probabilities`, `legend`, `confidence` |
| **Noul** | is this statement true? | `noul` — a **calibrated 0–1 probability of truth** (no confidence field) |

**Engineering doctrine that matters here:**

- **Parallel, isolated questions.** All questions in one call are evaluated in parallel against the same state. *"Adding questions barely changes the response time"* — and per-question isolation avoids context-rot.
- **Atomic questions, composed in code.** Decompose multi-factor judgments into separate questions; combine the results with your own logic. *"Instead of 'rate this startup pitch', ask separately about market size, technical feasibility, differentiation."*
- **Criteria per question.** Choice options and Score levels carry descriptive criteria; Noul carries instructions. *"The more precise your criteria, the more trustworthy the probabilities."*
- **RLCD** (Reinforcement Learning for **Calibrated Decisions**) — the training method. Unlike RLHF (optimizes human preference), RLCD optimizes *accuracy **and** probability calibration*: the reported confidence must genuinely reflect correctness likelihood. This is what makes thresholds viable.
- **Closed output space** → no text to hallucinate (vendor: "zero hallucinations"; caveat: probability *judgments* can still be wrong).
- **Explicit input budget, error not truncate.** `state` + all questions ≤ 64k tokens; `state` + longest single question ≤ 32k; over budget returns `max_tokens_exceeded` — *"we won't truncate for you."*
- **Pin model versions in production** to avoid threshold drift.
- **Validate calibration on your own data before trusting thresholds** — 100–500 historical samples compared against human conclusions; *"don't set thresholds without calibration data."*
- **Threshold posture:** auto-execute high-confidence, escalate low-confidence, human review as backstop.

---

## 2. Fidelity matrix

| JEV property | Spec coverage | Verdict |
| :--- | :--- | :--- |
| System One decides / System Two thinks | Non-Requirements + D8 (engine scores, Brain writes) | **Faithful** |
| Closed output space (no prose) | Non-Requirements "engine-written prose" ban | **Faithful** (Choice only) |
| Never set a threshold without calibration data | D7 shadow-first foundation → measured flips | **Faithful** (strongest part of the spec) |
| Confidence thresholds → act vs escalate | 0.85 default + per-consumer thresholds | **Faithful** |
| Choice primitive | `decide()` | **Faithful** |
| Calibrated probabilities (RLCD's whole point) | AC6.3 = precision-at-threshold only | **Not faithful** — §3 B1 |
| Per-question criteria | One frozen `tool_choice` head for all consumers | **Not faithful** — §3 B2 |
| Parallel multi-question, ~flat latency | One question per forward pass | **Missing** — §3 B3 |
| Score primitive | absent | **Missing** — §3 B4 |
| Noul as calibrated P(true) | modeled as 2-way Choice | **Partial** — §3 B5 |
| Atomic questions composed in code | one judgment per consumer, no composition | **Partial** |
| Explicit budget, never silent-truncate | silent truncation at 160/80 chars | **Not faithful** — §3 B8 |
| Pin model version | glob-resolves any `LFM2*350M*.gguf` | **Not faithful** — §3 B7 |
| Calibrate on 100–500 samples | enforcement bar = 50 rows | **Partial** — §3 B6 |
| Residual text generation eliminated | `generate_args` retained for complex schemas | **Partial** — §3 B9 |

---

## 3. Findings

### 3.0 Classification (Kiro workflow step 1)

Every finding below was traced against live code before being written. Classified per the Kiro spec-writer taxonomy:

| Finding | Classification | Evidence |
| :--- | :--- | :--- |
| A1 warm-head snapshot unwired | **REAL GAP** | `save_state()` at `decision_engine.py:308`; zero `load_state()` calls in `backend/` |
| A2 letters unimplemented, tie-break loop live | **REAL GAP** | first-token scoring `:426-433` + loop `:437-453`; `_letter_token_ids` unused |
| A3 Noul primitive absent | **REAL GAP** | `grep -ri noul backend/` → 0 hits |
| A4 second capture site (`:1719`) | **REAL GAP** | `tool_bridge.py:1709` and `:1719` both call `_capture_screenshot_blob()` |
| A5 amendment line refs drifted | **REAL GAP** | `_mem_lookup` `:14681`, `_asyncio.run` `:14830` |
| B1 calibration unmeasured + tau | **REAL GAP** | no ECE/Brier anywhere; `softmax_tau=0.5` at `:126` |
| B2 no per-question criteria | **REAL GAP** | head constant at `:356-373`; warmed only for `"tool_choice"` at `:304` |
| B3 no parallel multi-question | **REAL GAP** | one question per `decide()` call |
| B4 Score primitive absent | **REAL GAP** (scope call) | only `decide()` + `generate_args()` exist |
| B7 no model pinning | **REAL GAP** | glob at `:143`, `:157-160` |
| B8 silent truncation | **REAL GAP** | cuts at `:374`, `:379`, `:386`, unlogged |
| Doc §2 / §5 Track 1.1 latency + letter claims | **BLUEPRINT-DIVERGENT** | doc describes target behavior the code does not implement |
| `docs/architecture/tool-decision-engine.md:148-149` "typed Choice/Noul reproduced" | **BLUEPRINT-DIVERGENT** | contradicts code |
| Doc §8.4 "62/62" vs §8 "43/43" | **STALE** (internal contradiction) | same doc, two counts |
| Bottleneck diagnosis (§3–§4 of the doc) | **ALREADY CORRECT** | every cited site verified live |
| D7 shadow-first discipline | **ALREADY CORRECT** | matches JEV's calibration-before-threshold rule |
| JEV vendor benchmark claims (193.6×, 444.6×) | **CANNOT VERIFY** | vendor-sourced; not relevant to local fidelity |
| Whether `LFM2-350M` discriminates ≥6 options reliably | **CANNOT VERIFY** without running T0 | `candidate_cap=6` is a measured-floor assertion from 2026-09-20 |

### 3.1 Code-verified defects (doc/spec describe behavior the code does not have)

**A1 — The warm-head snapshot is dead code, and no REQ owns wiring it. `BLOCKER`**
`_warm_head_state()` computes `self._head_state = self._llm.save_state()` (`decision_engine.py:308`) but **`load_state()` is never called anywhere in the backend** (verified: the only `save_state`/`load_state` hits in `backend/` are unrelated — `crawler/capabilities.py`, `memory/reindex.py`, `sessions/state_isolation.py`). `_n_head_tokens` is set and never read. The scoring path re-tokenizes and re-evaluates the **full** prompt every call (`:410-412`).
*Why it matters:* the doc's §2 latency arithmetic ("static head ~90 tokens pre-computed and snapshotted once… dynamic tail evaluated in 10–60ms… total 150–250ms") and the design's architecture diagram (`design.md:26` "Re-use Snapshotted Head Cache (`_warm_head_state`)") both **assume this works**. It does not. The `REQ-1` AC1.3 (≤180ms p50) is being measured against a path that still pays full-prompt prefill. No AC, task, or ripple row owns wiring the snapshot.
*Action:* add an explicit task under T1 to `load_state()` + eval only the tail, with a test asserting the head is not re-evaluated (e.g. instrument `_llm.eval` call count/token count per decision).

**A2 — "Single-forward-pass letter scoring" is not what runs; the tie-break loop is live. `BLOCKER`**
`_score_options_one_pass` scores the **first token of each candidate name** (`:426-433`), and for prefix-shared candidates runs a **`reset()` + full `eval(tokens + cont)` loop per tied option** (`:437-453`). `_letter_token_ids` is populated at `:315-319` and **never used**. The prompt head says *"Answer with the exact tool name"* (`:357`) with name-valued examples — i.e. the letter prompt of AC1.1 is not built.
*Why it matters:* REQ-1 AC1.1 ("format options using single-letter indices"), AC1.3 ("without calling `_llm.reset()`") and AC1.4 ("without triggering a tie-breaker re-eval loop") are **false as-built**; the Success Criterion "Zero Prefix Tie-Breaker Loops" is not met. The 2026-09-25 amendment correctly flags the method as contested and T0 is the right instrument — but the *doc* still presents letters as the fix (§5 Track 1.1) and the *design* still marks letters "Chosen" (§D1) with a lettered mermaid flow.
*Action:* keep T0 as the decider, but (a) reconcile AC1.1/1.3/1.4 language so they read correctly under either winner (the amendment says this; the ACs themselves were not edited), and (b) make explicit that *whichever* method wins must eliminate the `reset()` loop, not just the letter premise.

**A3 — "Typed Choice/Noul primitives" is claimed reproduced but Noul does not exist in code. `MAJOR`**
`docs/architecture/tool-decision-engine.md:148-149` states *"Reproduced: parallel single-pass option scoring (letter-indexed logits), typed Choice/Noul primitives."* Verified: `grep -ri noul backend/ --include=*.py` → **zero hits**. There is no Noul type, no `Score` type; `CONSUMERS` is `("tool_choice", "presentation", "narration")` (`:37`) and the only primitives are `decide()` and `generate_args()`.
*Action:* correct the architecture doc's fidelity section, and treat "add Noul/Score primitives" as real work (§3 B4/B5) rather than a reproduced property.

**A4 — `REQ-5` covers one of two duplicate-capture sites. `MAJOR`**
REQ-5 AC5.2 says "eliminate the second synchronous `_capture_screenshot_blob()` call in `tool_bridge.py:1601`" (singular). Live: there are **two** identical call sites — `:1709` (vision tools) **and** `:1719` (GUI tools), both immediately after their executor returns, both feeding `_record_tool_event`. The doc §4.2 likewise cites only the vision one.
*Action:* per the repo's own bound rule, **report, don't silently widen.** Either state REQ-5 is vision-only and open a follow-up for the GUI path, or extend AC5.1/5.2 to both sites. Do not leave the second site unmentioned.

**A5 — The amendment's own "current line references" have already drifted. `MINOR`**
The doc §8.3 table (labelled "Live location (2026-09-25)") gives `_mem_lookup` at `:14507` and `_asyncio.run` at `:14656`. Live: `def _mem_lookup` is at **`:14681`**, `_asyncio.run(sr.resolve(...))` at **`:14830`**. REQ-12 and T16 inherit the stale numbers.
*Why it matters:* the section's credibility rests on being "code-verified"; drifting within the same day undermines it and will mislead whoever implements T16.
*Action:* re-pin the numbers, or better, cite the function name + a grep-able anchor instead of raw line numbers (line refs in this file have drifted repeatedly).

---

### 3.2 JEV-doctrine gaps

**B1 — Calibration is asserted, never measured — and `softmax_tau` destroys it by construction. `BLOCKER`**
This is the central JEV property and the spec's weakest point.

- The engine is described as "calibrated" (requirements §Introduction; `decision_engine.py:1` docstring) but the only quality metric is AC6.3 `P(correct tool | confidence ≥ 0.85) ≥ 0.92` — that is **precision at a threshold**, not calibration. A model reporting 0.99 while being right 60% of the time passes AC6.3 with ease.
- There is **no reliability curve, no Expected Calibration Error, no Brier score** anywhere in REQ-6, the design, or the tasks (verified by grep across the spec folder).
- Worse, `EngineConfig.softmax_tau = 0.5` (`:126`) sharpens the softmax purely to cross the 0.85 gate — the inline comment admits the raw distribution "spreads across 0.28–0.53 — rarely crossing 0.85 even on clear cases. tau < 1 sharpens without reordering." A monotone sharpening is *calibration-destroying by definition*: it inflates confidence without changing accuracy ordering. So the engine's stated confidence is **not** a probability of correctness, which is precisely what JEV's RLCD guarantees and what makes thresholds safe.

*Action:* add a REQ that measures calibration directly (reliability curve + ECE/Brier on the labeled battery, bucketed by confidence) and gates enforcement on it — e.g. `ECE ≤ 0.05` **in addition to** the existing precision bar. Then either (a) replace `softmax_tau` with a fitted calibration map (temperature scaling fit to the ledger — itself monotone but *fitted*, so it can be reported honestly), or (b) explicitly document tau as a threshold-shifting transform and stop calling the output "calibrated."

**B2 — No per-question criteria: one frozen `tool_choice` head serves every consumer. `BLOCKER`**
JEV's rule: criteria per question → trustworthy probabilities. Live: the prompt **head is consumer-independent** — `_build_prompt_parts(consumer_id, …)` builds a constant head (`:356-373`) reading *"Choose the best tool for each task. Answer with the exact tool name."* with four tool-selection worked examples; only the **tail** interpolates `consumer_id` (`:390`). `_warm_head_state()` warms exactly one head, built with `"tool_choice"` (`:304`).
*Why it matters:* REQ-13–17 introduce ~7 new consumers (`review_verdict`, `sufficient`, `done`, `on_track`, `mode`, `web_intent`, `recovery_strategy`) that will all be scored under a prompt that says "choose the best tool" and whose worked examples all resolve to tool names. The `mode` consumer (6-way: spec/research/implement/debug/test/review) and `review_verdict` (pass/refine/veto) get no criteria at all. Expect weak discrimination and miscalibrated confidence — and the spec's own parity test (BT-DEI-8, ≥0.90 agreement) is the thing that will fail.
*Action:* the design must decide how criteria are expressed per consumer. Cheapest faithful shape: keep the shared head for `tool_choice`, and give the new consumers **their own heads** (per-consumer cached KV states) carrying their own instructions + one worked example each. Add a ripple row + a task; without it, REQ-13–17 are built on an unstated and probably invalid assumption.

**B3 — No parallel multi-question scoring (JEV's marquee property). `MAJOR`**
JEV: multiple questions against one state are scored in parallel, and *"adding questions barely changes the response time."* The spec issues **one question per forward pass** and adds six consumers as six independent call sites. Where the loop already needs several judgments about the same step (e.g. Reviewer: verdict + on-track + done; or a recovery point: strategy + tool choice), those are 3 separate forward passes on the same state — the exact cost JEV's parallel sampler exists to remove.
*Action:* add a REQ/AC for a batched `decide_many(state, questions)` returning one answer per question from a single pass (multiple answer positions over one shared prompt). This is the natural extension of the (currently unwired, see A1) head-cache design and directly serves the sub-450ms target.

**B4 — `Score` primitive absent. `MAJOR`**
JEV has three primitives; the engine has Choice (+ `generate_args`). No ordinal/continuous scoring consumer exists. The doc's own §8.4 lists risk/compliance judgment as a JEV use case and defers model-selection authority, but there is no Score consumer anywhere — and JEV's `Score` is a *closed-set* primitive (2–10 ordered levels), so it is not excluded by the "engine never writes prose" rule.
*Action:* either add a Score primitive + at least one consumer (e.g. step risk, or the deferred model-selection-authority difficulty score) or state explicitly in Non-Requirements *why* Score is deliberately out of scope. Silence here is the gap.

**B5 — `Noul` is modeled as a 2-way Choice, not a calibrated probability-of-truth. `MODERATE`**
REQ-14's bools (`sufficient`, `done`, `on_track`) are conceptually Noul, but the spec never defines a Noul return shape. JEV's Noul returns a single calibrated 0–1 P(statement true) — which is not the same object as `softmax` over two options, and matters for the fail-closed gate semantics REQ-14 AC14.4 cares about.
*Action:* define the Noul envelope (single probability, no `confidence` field) and have REQ-14's consumers use it.

**B6 — Enforcement bar is 50 rows; JEV's own guidance is 100–500. `MODERATE`**
The Wave 7 bar is "≥ 50 rows at P(correct | conf ≥ threshold) ≥ 0.90" (D7, TG-7, T22). JEV's production guidance is to validate confidence on **100–500** historical samples before trusting thresholds.
*Action:* raise the foundation→enforcement bar to ≥100 rows minimum (500 preferred for the high-frequency, user-visible consumers), or justify 50 with a measured variance argument. At 50 rows the confidence interval on a 0.90 accuracy estimate is roughly ±0.08 — too wide to safely flip a routing consumer.

**B7 — No model pinning tied to calibration. `MAJOR` (cheap fix)**
JEV: pin the model version in production "to avoid threshold drift." Live: `resolve_model_path` globs `LFM2*350M*.gguf` (`:143`, `:157-160`) and takes whatever matches. Thresholds are calibrated against *one* model's probability distribution; swapping the GGUF silently invalidates every threshold with no signal.
*Action:* record the resolved model id (already captured as `self.model_id`, `:274`) + file hash in the calibration ledger, and assert it matches at load. A one-line guard with outsized safety value.

**B8 — Silent input truncation is ungoverned. `MODERATE`**
JEV: explicit budgets (64k/32k) and `max_tokens_exceeded` on overflow — never silent truncation. Live: the goal is cut to the first line, 160 chars (`:374`), state bits to 80 chars × 10 (`:379`), option descriptions to 80 chars (`:386`), with no logging and no budget accounting. `n_ctx=1024` (`:105`).
*Why it matters:* a long goal truncated at 160 chars can flip the decision, and nothing records that it happened — so a bad decision is unattributable.
*Action:* log when truncation occurs (field + original length) and add an AC. Full JEV-style explicit-budget error semantics may be overkill at 1024 ctx; the *observability* of truncation is the non-negotiable part.

**B9 — Residual text generation in `generate_args` keeps a hallucination surface. `MODERATE`**
JEV's "no hallucination" comes from *never generating text*. REQ-2's fast path removes autoregression for single-`query` tools, but AC2.4 deliberately **retains schema-constrained JSON generation** for multi-arg tools. REQ-7's `validate_no_null_or_missing_params` catches null/missing params but **not a wrong-but-non-null value** (e.g. a plausible wrong path or wrong enum).
*Action:* note the residual explicitly and extend validation beyond null-checking where cheap — enum/closed-set membership, path existence for file args, pattern match for IDs. Where the arg space is finite, prefer JEV's "enumerate from a finite set" over generation.

**B10 — Primitive cardinality limits not documented. `MINOR`**
JEV: Choice ≤255 options, Score 2–10 levels. The engine's `candidate_cap = 6` is stricter (and justified by a measured discrimination floor, `:114-118`) — fine — but the doc §3.1 says "candidate_cap is 6 or 8" while the engine default is 6 and `tool_decision.py:534` falls back to 8. Pin the number in one place.

---

### 3.3 Internal inconsistencies in the doc/spec

**C1 — "Decisions Locked" declares letter scoring locked; the same section's amendment contests it. `MODERATE`**
`requirements.md:6` locks "Letter-Indexed Candidate Scoring … enables single forward pass scoring in 25–60ms on CPU." `requirements.md:12` (amendment) says REQ-1's letter method "is CONTESTED by as-built evidence." Both sit under the same "Decisions Locked" heading. A reader implementing T1 sees a locked decision and a contradiction.

**C2 — design.md still presents letters and the head cache as settled. `MODERATE`**
D1 says single-letter tokens "Chosen" (only a trailing contingency note), and the Architecture Overview mermaid shows "Format Lettered Prompt A: tool_1" feeding "Re-use Snapshotted Head Cache". Both are unwired (A1, A2). The design's *diagrams* contradict the amendment.

**C3 — The AC count is stated two different ways in the same doc. `MINOR`**
`tool-decision-engine-improvements.md:253` says "the matrix counts **43/43** ACs covered, 0 unmapped"; `:304` says "Matrix now counts **62/62** ACs, 0 unmapped." `tasks.md:152-154` says 62. The 43/43 line is stale.

**C4 — Success Criterion vs contingency. `MINOR`**
Success Criteria promise "**Zero** Prefix Tie-Breaker Loops: Eliminate 100% of context resets." D1's contingency permits first-token scoring, which as-built *includes* the tie-break loop. State plainly that the tie-break loop must go under either method (see A2).

---

## 3.4 Citation verification sweep + test baseline (2026-09-25)

Every remaining unverified `Verified:` citation in the spec was traced. Result: **most are accurate; one REQ had two badly stale refs.**

| Claim (spec) | Live location | Status |
| :--- | :--- | :--- |
| REQ-2 `generate_args` autoregressive | `decision_engine.py:645-693` | **VERIFIED** |
| REQ-3 `"what's"` in `_VISION_TOKENS` | `tool_decision.py:51-55` (`"what's"` at `:54`; spec said `:56`) | VERIFIED (1-line drift) |
| REQ-4 cap truncation → lanes | slice `:538-543`, lanes `:603-605` (spec said `:534`) | VERIFIED (shifted) |
| REQ-7 `crawler_query` hardcoded composite | `capabilities.py:729` def, `:778` `composite_of=(...)` | **VERIFIED — exact** |
| REQ-8 `search_providers/` exists but unwired | `backend/crawler/search_providers/{__init__,base,exa,llm}.py` present | **VERIFIED — exact** |
| REQ-9 no search-vs-crawler contrast in head | `decision_engine.py:356-373` — no `search` option appears at all | **VERIFIED — exact** |
| REQ-11 `_split_step` resets counters | def `:12803`; reset at `:12992-12995` ("Reset failure counters so Sub-Loops aren't penalized"); `ruled_out=""` at `:12967` | VERIFIED (spec said `:12986`) |
| REQ-12 `_asyncio.run` on DER thread | `:14830` | VERIFIED (re-pinned) |
| REQ-13 Reviewer verdict Brain call | prompt `:1109-1122` (`{"verdict":"pass\|refine\|veto"}`), `_parse_verdict` at `:1125-1141` | **VERIFIED — exact** |
| REQ-14 sufficiency gate | `_der_findings_sufficient` `:13361`, prompt `:13372-13404`, parse `:13411` | VERIFIED |
| REQ-14 done/next-goal | prompt `:18288`, parse `:18306` — spec said `:18102-18121` | **WRONG REF — fixed** |
| REQ-14 drift check | `on_track` prompt `:18382`, parse `:18397` — spec said `:18202-18214` | **WRONG REF — fixed** |
| REQ-15 `_WEB_INTENT_TRIGGERS` (15 phrases) | `explorer.py:53-69` | **VERIFIED — exact** |
| REQ-15 two web-trigger copies | `agent_kernel.py:6723` `_is_web_search_request`, `:6753` `_looks_informational` | **VERIFIED — exact** |
| REQ-15 `ModeDetector` | class `:43`, `def detect` `:103`, `_infer_mode` `:172` (spec said `:43-80`) | VERIFIED (range points at the keyword table, not `detect`) |
| REQ-16 `propose()` 400-token Brain call | `explorer.py:146-150` — `infer(prompt, role="REASONING", max_tokens=400, ...)` | **VERIFIED — exact** |
| REQ-16 RespondDirect ReAct loop | `agent_kernel.py:3111` (`_router.generate` with tools) → `:3125-3129` ReAct loop | **VERIFIED — exact** |

**REQ-14 was the only requirement with materially wrong refs** — both the done-bit and drift citations had drifted ~150–180 lines and pointed at unrelated code (contract-amendment bookkeeping and `done_summary` construction). Corrected in requirements.md and the design ripple row.

### Test baseline (required by Kiro workflow step 1)

```
backend/tests/{unit,contract,behavioral}/ (decision-engine set)
2 failed, 70 passed, 3 warnings in 15.11s
```

**Both failures are STALE TESTS, not production regressions** — classified by reading the code they exercise:

- `test_decision_engine_contract.py::TestCtDe3Ledger::test_reason_engine_decision_records_route_only_row_once`
- `test_decision_engine_behavioral.py::TestBtDe4ReasonSingleRow::test_none_choice_one_route_only_row`

Both assert `row["meta"]["route"] == "escalated"`; the code emits `"engine-none"`. Their own comments say *"Session-345: NONE now takes the AC3.2 ladder … so the single row's route is 'escalated'"*. That was true at session 345, but the **2026-09-24 OQ-2 refinement superseded it**: `tool_decision.py:698-719` now commits a confident `NONE` as REASON with `source="engine-none"` when the goal carries no gather/action signal — and both test fixtures use signal-free descriptions (`"just think"`, `"nothing to do"`), so the new gate fires. The gate is documented at `:99-114` and `:688-697` (including the live finding that motivated it).

**Do not "fix" these by editing the tests** (project TEST RULE — absolute), and do not treat them as green-baseline blockers for TG-1/TG-2. They are owner-decision items, same class as the already-tracked `test_unparseable_json` stale red (`docs/architecture/tool-decision-engine.md:176-178`). Recommended: update the two fixtures to carry an action/gather signal *or* update the expected route to `engine-none` — whichever the owner intends the pinned property to be — and record the decision as a pin.

---

## 4. What's already right (don't change these)

- **The bottleneck diagnosis is accurate.** Tie-break loop at `decision_engine.py:437-453`, always-on autoregressive args, `"what's"` in `_VISION_TOKENS` (`tool_decision.py:51-55`), lanes built from truncated `names` (`tool_decision.py:603-605` after the slice at `:538-543`), duplicate capture (`tool_bridge.py:1709`) — every one verified live.
- **D7 shadow-first foundation → measured enforcement is exactly JEV's "never set thresholds without calibration data."** This is the most faithful part of the spec; the Wave 6/7 split and the "consumers below bar stay shadow with the gap logged" rule should be preserved verbatim.
- **D8 (engine scores, Brain writes) is correct JEV shape** and correctly rejects engine-authored prose.
- **The Wave 0 probe gating T1 is good engineering** — it is the right response to the contested letter method.
- **The Non-Requirements list** (no hosted router, CPU-only, no prose, no safety/budget authority) maps cleanly onto JEV's boundaries.

---

## 5. Recommended spec deltas

| # | Finding | Suggested home |
| :--- | :--- | :--- |
| A1 | Wire `load_state()` + tail-only eval | New task under T1; test asserts head not re-evaluated |
| A2 | Reconcile letter ACs with the probe outcome; kill the `reset()` loop either way | Edit AC1.1/1.3/1.4 + D1 |
| A3 | Correct the architecture doc's fidelity claim | `docs/architecture/tool-decision-engine.md:146-153` |
| A4 | Decide scope of the second capture site (vision-only vs both) | Edit REQ-5 or add follow-up |
| A5 | Re-pin or replace line refs | Doc §8.3 |
| B1 | **Measure calibration (ECE/Brier/reliability) and gate enforcement on it; resolve `softmax_tau`** | **New REQ-18 (Calibration Quality) + amend REQ-6** |
| B2 | **Per-consumer prompt heads with criteria** | **New REQ-19 (Per-Consumer Criteria) + design decision + ripple rows** |
| B3 | Batched multi-question scoring | New REQ-20 (Parallel Multi-Question) |
| B4 | Score primitive (add or explicitly exclude) | New REQ or Non-Requirements |
| B5 | Noul envelope as calibrated P(true) | Fold into REQ-14 |
| B6 | Raise enforcement bar 50 → ≥100 rows | Edit D7 / TG-7 / T22 |
| B7 | Pin model id + hash against the calibration ledger | Fold into REQ-6 |
| B8 | Log truncation events | Fold into REQ-6 (observability) |
| B9 | Extend arg validation beyond null-checking | Fold into REQ-2 / REQ-7 |
| C1-C4 | Fix contradictions in the locked section, design diagrams, AC count, success criterion | Editorial |

**Highest-value three, in order:** B1 (calibration is the point of JEV and is currently unmeasured *and* undermined by tau-sharpening), B2 (all seven new consumers are about to be scored under a prompt that doesn't describe them), A1 (the sub-450ms story rests on a snapshot that is never loaded).

---

## 6. Sources

- TypeSafe AI official docs — Introduction & primitives: https://docs.typesafe.ai/introduction
- Jev API reference (state/questions, Choice/Score/Noul shapes, 64k/32k budgets, `max_tokens_exceeded`, pinning): https://jevtypesafeai.com/zh/docs
- Technical writeup (RLCD, latency/cost benchmarks, calibration validation on 100–500 samples, anti-patterns): https://dev.to/czmilo/what-is-jev-the-2026-complete-guide-to-typesafes-system-one-model-200x-faster-400x-cheaper-ai-451h
- Primitive/RLCD summary: https://fluxbbs.com/typesafe-ai-jev-system-one-model/

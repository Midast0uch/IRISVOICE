# Requirements: Tool Decision Engine (Calibrated Small-Model Tool Selection)

## Decisions Locked

- **Model:** LFM2.5-350M is the decision driver, and it is a **first-class resident backend
  component** (`backend/agent/decision_engine.py`), not a config-only rebinding of the
  existing executor. (Owner, 2026-09-20.)
- **Confidence source:** candidate-continuation logprob scoring — the Jev parallel-Choice
  pattern reproduced on local weights. Self-reported confidence ("append 0.9 to the JSON")
  is REJECTED: small models self-report ~0.9 regardless of correctness. (Owner, 2026-09-20.)
- **Jev hosted API is NOT used.** Jev (TypeSafe AI "System One" model) is hosted; the
  pattern (parallel option scoring + calibrated probability + escalation threshold) is
  reproduced with `llama_cpp` primitives. (Librarian research 2026-09-20,
  pin_1d6703528054.)
- **RLCD** here means TypeSafe's "Reinforcement Learning for Calibrated Decisions"
  (honest-probability training). The Meta paper "RLCD: Reinforcement Learning from
  Contrastive Distillation" (arXiv 2307.12950) is a name collision and is OUT of scope.
- **In-process CPU residency.** The 350M runs via `llama_cpp` inside the backend process
  on CPU. It holds no VRAM and no entry in the VRAM ledger. Rejected alternatives in
  design.md (D1).
- **No double recording.** The engine has NO write access to the memory layer and emits
  NO events of its own. Decision metadata travels as fields on the ONE existing tool
  event row written by `_record_tool_event`. (Owner, 2026-09-20.)
- **Default threshold 0.85** (owner proposal), provisional until the calibration tool
  re-derives it from the ledger (REQ-6).
- **Kernel seam unchanged.** Escalation (LOW-CONFIDENCE / DELEGATE) is absorbed inside
  `ToolDecisionBox.resolve()`; the kernel still receives only TOOL/REASON/FAIL.
- **Multi-consumer service.** The engine is a decision service; the tool box is consumer
  one. Wave 4 adds the presentation gate and the narration gate. (Owner, 2026-09-20 —
  resolves OQ-3.)
- **Engine replaces, heuristics are the degrade path.** The auto-render heuristic
  (`agent_kernel.py:4280`), the first-sentence excerpt, and the narration timer become
  fallback behavior used only when the engine is unavailable. (Owner, 2026-09-20.)
- **Narration gate covers all narration** — final answer and mid-turn progress —
  AND-gated with the user toggle and existing latches. (Owner, 2026-09-20.)
- **Shadow-first cold start.** Presentation and narration gates record their decisions
  while the heuristics still decide; enforcement flips only after the calibration gate.
  Tool Choice enforces at 0.85 from day one. (Owner, 2026-09-20.)
- **Gate-layer only, order-free vs chat-communication-lanes.** Wave 4 gates the
  existing two-surface emit points; chat-communication-lanes still owns content
  (the three-way split). The specs compose in either order. (Owner, 2026-09-20.)
- **Enumerated feature frame only.** Engine consumers receive a deterministic feature
  frame (no free prose). (Owner, 2026-09-20.)
- **350M file source:** discovered in the models directory during T1; if absent,
  downloaded via the existing `hf_hub_download` path. (Owner, 2026-09-20 — resolves
  OQ-1.)

## Introduction

Tool selection today is a single-shot, confidence-free generation by whatever model the
`tool_execution` role resolves to (`tool_decision.py:491`). When that model returns an
empty completion the step fails outright (session-342 E5 live failure,
`[TOOL_DECISION_FAIL] Empty response from Ollama`). There is no measured confidence, no
escalation middle ground, and no way to compare decision speed/efficiency across routing
strategies over time. The Decision Engine puts a resident 350M model in front of the
existing path: it scores all candidate tools in parallel (Jev pattern), returns a real
probability, and only the calibrated tail escalates to the big model. Every decision is
joined to its DAG step and its tool outcome in ONE ledger row, so speed and quality are
measurable going forward.

### Success Criteria

- Zero terminal `FAIL`s whose sole cause is a first-try empty completion (E5 closed).
- P(correct tool | confidence ≥ threshold) ≥ 0.90, measured on harvested ledger data
  (method UNVERIFIED until the REQ-6/REQ-10 live gate).
- Decision latency: engine decision p50 ≤ current tool_execution decision p50 + 1.0s on
  identical hardware, and the big-model escalation rate is measured (target set from the
  baseline, UNVERIFIED until the live gate).
- Zero leaked model contexts/processes across load → decisions → shutdown.
- Exactly one ledger event per tool execution with the decision engine active
  (no double-record regressions).
- Presentation and narration gates measure ≥ 0.90 observed accuracy at their enforced
  threshold before enforcement is enabled (method UNVERIFIED until the same calibration
  gate that proves the tool Choice threshold).

## Requirements

### REQ-1: Resident 350M Decision Engine component
**User Story:** As the agent loop I want a small, always-warm decision model so that tool
selection is fast, deterministic in cost, and independent of which brain is loaded.

**Verified:** NEW (no engine exists today — `tool_decision.py:491` is the only decision
call).

**Acceptance Criteria:**
- AC1.1: THE SYSTEM SHALL load the LFM2.5-350M model lazily on the first decision
  request, never at backend startup.
- AC1.2: THE ENGINE SHALL run in-process on CPU and SHALL make no entry in the VRAM
  ledger (`local_model_manager.py:791` ledger untouched).
- AC1.3: IF the model file is missing, corrupt, or fails to load THEN THE SYSTEM SHALL
  report the engine unavailable and ToolDecisionBox SHALL use the pre-existing
  single-shot path unchanged.
- AC1.4: THE ENGINE SHALL bound its resources: context ≤ 2048 tokens, decision output
  ≤ 512 tokens, and SHALL serialize concurrent decision calls behind one context with a
  bounded wait (timeout → escalation ladder).

**Edge Cases:**
- Two decision requests arriving concurrently → second waits bounded time, then
  escalates.
- Backend shutdown with the engine loaded → context freed (see REQ-7 AC7.4).

### REQ-2: Parallel candidate scoring (Jev Choice reproduction)
**User Story:** As the agent loop I want every candidate tool scored in one pass so that
the choice is a probability distribution, not a hoped-for JSON.

**Verified:** NEW.

**Acceptance Criteria:**
- AC2.1: THE ENGINE SHALL score every candidate tool produced by the existing memory
  pre-filter PLUS the reserved candidates `DELEGATE` and `NONE`, in a single engine
  invocation.
- AC2.2: THE ENGINE SHALL compute each candidate's score as the log-probability of the
  candidate name as a forced continuation of a fixed decision prompt, and SHALL
  softmax-normalize the set into a probability distribution.
- AC2.3: THE ENGINE SHALL return `{chosen, confidence, distribution}` where
  `confidence = P(chosen)` and `chosen = argmax`.
- AC2.4: IF scoring fails for any reason (timeout, model error, invalid distribution)
  THEN THE SYSTEM SHALL degrade to the existing single-shot generation path.
- AC2.5: WHEN the chosen candidate is a real tool with confidence ≥ threshold THEN THE
  ENGINE SHALL generate that tool's arguments constrained to the tool's declared
  parameter schema; IF the generated arguments fail schema validation THEN THE SYSTEM
  SHALL escalate the whole decision to the reasoning model.

**Edge Cases:**
- Empty candidate list after pre-filter → score set is `{DELEGATE, NONE}` only.
- Tool names sharing a long common token prefix — scoring uses full-name continuation
  logprobs, not first-token tricks, so shared prefixes are handled.

### REQ-3: Confidence-threshold routing and escalation ladder
**User Story:** As the operator I want confident cheap decisions to execute immediately
and uncertain ones to cost a big-model call, so that quality is spent where needed.

**Verified:** NEW (today's ladder is memory-fallback → `FAIL`,
`tool_decision.py:575-657`).

**Acceptance Criteria:**
- AC3.1: WHEN `confidence ≥ threshold` and `chosen` is a real tool with valid args THEN
  the box SHALL return the TOOL decision with shape identical to today's TOOL decision.
- AC3.2: WHEN `confidence < threshold` or `chosen ∈ {DELEGATE, NONE}` THEN the box SHALL
  try the existing memory fallback; IF memory also fails THEN it SHALL escalate to the
  reasoning model via the existing generation path (the big model decides tool + args).
- AC3.3: THE DEFAULT threshold SHALL be 0.85, configurable via agent config, and the
  calibration tool (REQ-6) SHALL be able to write a measured override.
- AC3.4: DELEGATE SHALL never leave `resolve()` as a new visible kind: the kernel-facing
  `DecisionKind` set stays exactly {TOOL, REASON, FAIL}.

**Edge Cases:**
- Threshold = 1.0 → every decision escalates (debug mode).
- Reasoning model also fails after escalation → existing FAIL path, unchanged.

### REQ-4: Bounded empty-completion retry
**User Story:** As the operator I want one silent retry on an empty model response so
that the session-342 E5 failure cannot recur.

**Verified:** NEW (retry exists only on synthesis: `agent_kernel.py:17651-17666`;
`tool_decision.py` has none).

**Acceptance Criteria:**
- AC4.1: WHEN any decision-call generation (engine args stage or fallback generation)
  returns empty or whitespace-only output THEN THE SYSTEM SHALL retry exactly once.
- AC4.2: THE RETRY SHALL happen before any escalation or fallback step consumes the
  failure.
- AC4.3: THE SYSTEM SHALL never retry more than once per step.

**Edge Cases:**
- Both attempts empty → proceeds down the normal escalation ladder, never loops.

### REQ-5: Decision ledger — one row per execution, joined to the DAG step
**User Story:** As the tuner I want each decision recorded once, joined to its DAG step
and its tool outcome, so that calibration and speed analysis read ONE source of truth.

**Verified:** NEW on top of `tool_bridge.py:1936` (`_record_tool_event` already writes
one bounded payload row per execution on a daemon thread, never-raises).

**Acceptance Criteria:**
- AC5.1: THE SYSTEM SHALL record per decision: DAG node/step id, candidate count,
  chosen, confidence, route ∈ {engine, memory-fallback, escalated, failed}, args-valid
  boolean, decision latency ms, engine latency ms, and the tool outcome
  (success/failure) — all as fields of the SAME tool event row.
- AC5.2: LEDGER writes SHALL ride the existing `_record_tool_event` path (daemon
  thread, `_summarize` bounding) and SHALL add no synchronous I/O to the decision hot
  path.
- AC5.3: IF the ledger write fails THEN the decision path SHALL be unaffected.
- AC5.4: THE ENGINE SHALL NOT write to the memory layer, the event store, or any ledger
  itself. The ONLY writer remains `_record_tool_event`; decision data arrives inside its
  payload. (Anti-double-record rule.)

**Edge Cases:**
- Decision produced but no tool dispatched (REASON/DELEGATE outcomes) → one route-only
  row with `outcome=None`, still written via the same event path, not a second channel.

### REQ-6: Calibration tooling
**User Story:** As the tuner I want a reliability curve and a recommended threshold from
our own traffic, so the 0.85 default is replaced by a measured value.

**Verified:** NEW.

**Acceptance Criteria:**
- AC6.1: THE SYSTEM SHALL provide a script that reads the decision ledger and outputs a
  reliability table (confidence bucket vs observed accuracy) and a recommended threshold
  maximizing the auto-executed fraction subject to accuracy ≥ 0.90.
- AC6.2: THE SCRIPT SHALL refuse to recommend a threshold from fewer than 50 recorded
  decisions and SHALL state the sample size.
- AC6.3: THE threshold SHALL be reported as UNVERIFIED (provisional 0.85 in effect)
  until the live harvesting gate collects ≥ 50 decisions from LT battery runs.

**Edge Cases:**
- Ledger has decisions from multiple engine model ids → script groups by model id.

### REQ-7: Infra wiring and lifecycle
**User Story:** As the maintainer I want the engine registered like any other local
model so that deployment needs no special procedure.

**Verified:** NEW.

**Acceptance Criteria:**
- AC7.1: THE ENGINE model file SHALL be discoverable under the configured models
  directory (`local_model_manager.py:1403` scan already enumerates it); the engine
  loads it directly via `llama_cpp`, bypassing the single-resident 8082 server.
- AC7.2: `agent_config.yaml` SHALL declare the 350M entry with CPU constraints,
  mirroring the existing executor entry style.
- AC7.3: WHEN the engine is unavailable THEN ToolDecisionBox SHALL log one notice per
  session and run the pre-existing path silently thereafter (no per-call log spam).
- AC7.4: ON gateway shutdown the engine context SHALL be freed; a load → decisions →
  shutdown cycle SHALL leak no llama_cpp context (verified by test).

**Edge Cases:**
- Engine loaded while the brain/vision load path runs concurrently → engine is
  independent of the 8082 single-resident server by construction (AC1.2).

### REQ-8: Decision observability
**User Story:** As the operator I want a structured decision log line so that live runs
show routing behavior without deep debugging.

**Verified:** NEW.

**Acceptance Criteria:**
- AC8.1: THE SYSTEM SHALL emit one structured log line per decision: route, confidence,
  chosen, latency ms, retry flag — off the critical path.
- AC8.2: THE SYSTEM SHALL maintain counters: engine decisions, escalations, memory
  fallbacks, retries, engine-unavailable events.

**Edge Cases:**
- High-frequency decision loops → one line per decision, no per-candidate spam.

### REQ-9: Bidirectional data contract (what the engine reads, what it writes)
**User Story:** As the maintainer I want the engine's read set and write set pinned by
contract so that future edits cannot smuggle a second memory write or an unpinned input.

**Verified:** NEW.

**Acceptance Criteria:**
- AC9.1: THE SYSTEM SHALL define one `DecisionMeta` contract object carried from
  `resolve()` through `dispatch()` into `execute_tool`; its fields SHALL be exactly the
  AC5.1 decision fields, and the shape SHALL be pinned by a contract test.
- AC9.2: THE ENGINE's read set SHALL be exactly: the pre-filtered tool menu, the memory
  hint/veto output, the step goal and evidence, and the chosen tool's parameter schema.
  Any new input source requires a spec amendment.
- AC9.3: THE ENGINE's write set SHALL be exactly: its return value to the box, plus the
  AC8 log/counters. It SHALL hold no reference to, and make no calls into, the memory
  layer, the event store, or `ffi_ingest_event` (enforced by an AST-scan contract test
  in the style of `test_no_direct_lfm_vl_provider_bypass.py`).

**Edge Cases:**
- `DecisionMeta` missing (legacy callers that never went through the engine) →
  `execute_tool` and the ledger behave exactly as today (fields absent, not null-filled).

### REQ-10: Speed and efficiency measurement, going forward
**User Story:** As the operator I want decision speed and routing mix measured
continuously so that the engine's benefit is a number, not a belief.

**Verified:** NEW.

**Acceptance Criteria:**
- AC10.1: THE LEDGER row SHALL carry decision latency and the escalated Boolean so
  per-route latency p50/p95 and the escalation rate are computable from the ledger
  alone (implementation detail lives with REQ-5 fields; this AC pins the guarantee).
- AC10.2: THE CALIBRATION script SHALL also report: per-route latency p50/p95,
  escalation rate, and big-model calls avoided (1 − escalation rate among routable
  decisions).
- AC10.3: BEFORE the engine is enabled for the first time, THE SYSTEM SHALL capture a
  baseline of the current tool_execution decision latency (instrumented run over the
  same LT battery), stored beside the calibration output.
- AC10.4: THE LIVE GATE SHALL compare engine-on vs engine-baseline on the same battery
  and report both speed and success deltas; targets set from the baseline, recorded in
  the live-test doc (`docs/LIVE_TEST_VISION_BROWSER_E2E.md` family).

**Edge Cases:**
- Baseline capture fails partway → gate reports UNVERIFIED rather than fabricating
  numbers.

### REQ-11: Presentation-surface gate (engine consumer 2)
**User Story:** As the user I want the system to decide whether an outcome deserves a
card at all, so the Prism card appears when it adds value and never drowns a one-line
answer.

**Verified:** NEW. Replaces the heuristic at `agent_kernel.py:4280`
(`_pacman_zone_for_turn() == "reference" and len(response) >= 300`) and the
first-sentence excerpt at `:4375` (`_supportive_text`) as the authority over surface
choice. The three-way content split itself belongs to chat-communication-lanes
REQ-2/REQ-3 — this gate decides surface, never writes content.

**Acceptance Criteria:**
- AC11.1: THE ENGINE SHALL score the presentation Choice `{plain_text, prism_card,
  card_plus_summary}` from the enumerated feature frame at every completion that could
  auto-render, and SHALL return the calibrated distribution.
- AC11.2: WHEN the engine is unavailable THEN the system SHALL apply the pre-existing
  heuristic path unchanged (degrade, aligned with AC1.3).
- AC11.3: THE GATE SHALL run in shadow mode at birth: the engine decision is recorded
  to the ledger while the heuristic still decides; enforcement SHALL flip only after
  the calibration gate proves the threshold on ≥ 50 recorded presentation decisions.
- AC11.4: WHEN `_last_render_emitted` is already true for the turn THEN the engine
  SHALL NOT be consulted for a second card (dedupe is a hard precondition, not a
  scored candidate).
- AC11.5: THE GATE SHALL produce no content: no rewriting, no composition, no
  narration text. Its write set is the decision plus its ledger record.

**Edge Cases:**
- Frame construction fails (missing features) → degrade to heuristic, logged.
- Engine says `plain_text` for what would have been a 4000-char card → chat line only;
  card never emitted.
- Mid-turn lane change (lanes spec lands later) → gate ACs unaffected (order-free).

### REQ-12: Narration gate (engine consumer 3, Noul)
**User Story:** As the user I want a calibrated speak/silence decision for both the
final answer and progress narration, so the system neither narrates internal noise nor
falls silent after a rendered card.

**Verified:** NEW. Touches `_speak_response` admission (`iris_gateway.py:3839`, calls
at `:3780/:3811`), the guaranteed-utterance backstop (`:3434-3463`), and progress
narration admission (`narration.py:246 may_narrate`, 18 s gate at `:241`).

**Acceptance Criteria:**
- AC12.1: THE ENGINE SHALL answer one Noul per narration admission point: speak yes/no
  with calibrated probability, from the enumerated feature frame.
- AC12.2: THE ENGINE SHALL be AND-gated with the user's narration toggle
  (`conversation_kernel.py:137`): a disabled toggle silences regardless of engine; the
  engine can never speak when the toggle is off.
- AC12.3: WHEN the engine is unavailable THEN THE SYSTEM SHALL apply the existing
  backstop and timer exactly as today (heuristic degrade path).
- AC12.4: THE ENGINE judgment SHALL replace inference inside the guaranteed-utterance
  backstop: when the engine is available and returns an intentional `silent`, the
  backstop SHALL NOT fire; the backstop fires only when the engine is unavailable or
  errored.
- AC12.5: SYSTEM alerts and error utterances SHALL bypass the engine gate entirely
  (they are not optional narration; existing lane guarantee "Replies and alerts never
  consult it" stays intact).

**Edge Cases:**
- Engine timeout mid-turn → the 18 s timer + backstop behave as today (no double-speak,
  no silence regression).
- u/ξ physics state appears in the feature frame as read-only context; the engine may
  use it to say "silence when converged," but the physics layer never reads the engine.

### REQ-13: Decision service surface (multi-consumer)
**User Story:** As the maintainer I want the engine exposed as one registry with
per-consumer decisions so that adding a gated decision never means touching the
engine's load, locking, or ledger code again.

**Verified:** NEW.

**Acceptance Criteria:**
- AC13.1: THE ENGINE SHALL expose a single consumer API: `decide(consumer_id, options,
  frame) -> DecisionScore` where `consumer_id ∈ {tool_choice, presentation,
  narration}` at v1 completion.
- AC13.2: ALL consumers SHALL share the one serialized context (AC1.4) and the one
  ledger path; a consumer SHALL have no private model, lock, or event channel.
- AC13.3: THE LEDGER row SHALL carry `consumer_id` so calibration (REQ-6) reports per
  consumer: the tool threshold and the surface/narration thresholds SHALL be
  independent numbers.

**Edge Cases:**
- One pathological consumer flooding the queue → per-consumer rate/turn budget; the
  other consumers see bounded wait, not starvation.

## Non-Requirements (Out of Scope)

- No Jev hosted API integration.
- No RLCD-style fine-tuning of the 350M (ledger exists first; a later spec
  may consume the calibration artifact for training).
- No change to `_der_plan_next_step` continuation decisions (`agent_kernel.py:17232`).
- No VRAM/ledger slot for the engine, no new server process, no new port.
- No change to `DecisionKind` visible at the kernel seam.
- No new event channel, no new memory write path, no second ledger.
- Wave 4 gates decide SURFACE and SILENCE only — they do not compose, summarize, or
  rewrite any content. Content belongs to chat-communication-lanes.
- The engine does NOT decide the crawl→vision escalation (that policy lives with the
  orchestrator's failure taxonomy). The engine scores vision tools as candidates and
  measures its own votes — it does not pre-empt the wall/escalate logic.

## Open Questions

- OQ-2: Whether `NONE` (no tool applies) maps to REASON directly or passes the memory
  fallback first — implementer records the choice in this spec on amendment.

### REQ-17: Hierarchical choice — lane then leaf
**User Story:** As the operator I want the engine to choose a lane first (file,
vision, memory, web, system...) and then the tool inside the lane, so that the
discrimination set at each stage is small enough for a 350M to win reliably.

**Verified:** NEW. Live evidence (session-344 calibration lap): cascaded 20-wide
flat selection scored uniform (conf 1/6 = guess); the earlier 4-6-wide probes
showed reliable discrimination (0.94-0.98). Two stages of narrow Choice beat
one stage of wide Choice.

**Acceptance Criteria:**
- AC17.1: THE ENGINE SHALL decide in TWO stages: Stage-1 picks a lane from the
  registry's existing `category` field (plus `DELEGATE_l / NONE_l`); Stage-2 picks
  the leaf among that lane's tools plus `DELEGATE_t + NONE_t`.
- AC17.2: WHEN Stage-1's confidence is below the same consumer threshold THEN
  THE DECISION escalates directly (no leaf evaluation — savings of Stage-2
  latency on a doomed pick).
- AC17.3: WHEN Stage-1 is confident but Stage-2 is not THEN route = escalated
  (leaf ambiguity) and the ledger carries BOTH stage confidences and both choices.
- AC17.4: THE FLAT single-stage path SHALL remain as the explicit fallback path
  when the model has no lane structure to serve (e.g. tiny menu: one lane).
- AC17.5: LATENCY SHALL stay budget-bounded: two stages in series SHALL finish
  within the same decision-call budget as one stage (combined tokens < the
  flat budget of a wide menu).

**Edge Cases:**
- Lane has 1 tool → engine picks lane, leaf = that tool, Stage-2 skipped.
- Lane name same as a leaf name (e.g. "speak") → lane escapes collision via
  `lane:` prefix in Stage-1 prompt text.
- Both stages share the same head prefix; only their tails differ (KV-cache
  friendly).
### REQ-15: Cross-step continuity frame (long-horizon coherence)
**User Story:** As the operator I want the engine to remember its own last pick inside
a plan, so a long DAG does not oscillate (pick → DELEGATE → pick again) without at
least seeing the contradiction.

**Verified:** NEW. Coordination audit 2026-09-20 (pin_a51d46ed8b5d): the engine is
stateless per step; the box's `ToolCallTree` (`tool_decision.py:144-160`,
`_tool_call_nodes`) holds the in-run history.

**Acceptance Criteria:**
- AC15.1: THE FRAME SHALL carry `previous_chosen`, `previous_outcome`, and
  `step_index` populated from the box's own in-run record — the engine NEVER reads the
  node store itself.
- AC15.2: THE META in the ledger row SHALL carry the same three fields so oscillation
  (chosen == previous_chosen after failure, etc.) is computable from the ledger alone.
- AC15.3: THE ENGINE SHALL stay stateless: no carry-over beyond what the frame
  supplies (single source for cross-step context stays the DER/goal-contract layer).
- AC15.4: A FIRST step of a plan SHALL mark `previous_chosen = null`, not a
  fabricated value.

**Edge Cases:**
- Steps executed concurrently (DER parallelism) → continuity follows the DAG order,
  not wall-clock; races are impossible because each step's record is written before
  the next step resolves in the same kernel.

### REQ-16: Engine ↔ vision path coordination
**User Story:** As the owner I want the engine to reason over the vision tool family
as first-class candidates, so steps needing sight never silently lose the vision
options to the candidate cap.

**Verified:** NEW. Registry exposes vision tools with category `vision`
(`tool_bridge.get_available_tools` shape: name/description/parameters/category);
the engine's candidate truncation happens at `decision_engine.py` `[:candidate_cap]`.

**Acceptance Criteria:**
- AC16.1: WHEN a step is vision-relevant (deterministic feature: the goal text
  matches the vision trigger vocabulary) THEN THE ENGINE's option set SHALL include
  the vision tools (up to the candidate cap, in registry order) even when the memory
  pre-filter dropped them.
- AC16.2: THE FRAME SHALL carry `needs_vision: bool` and
  `vision_candidates: int`.
- AC16.3: WHEN the engine picks a vision tool with confidence ≥ threshold THEN the
  normal engine path executes it — the vision tool itself owns server/borrow
  semantics (engine never manages servers).
- AC16.4: IF the VLM stack is unavailable THEN the vision candidates SHALL still be
  scored (they fail at execution with the stack's own honest failure — the engine's
  job is the choice, not the capability check).

**Edge Cases:**
- The whole registry is vision tools only → cap applies normally.
- Step mentions a URL but no visual need (e.g. "fetch the API docs") →
  `needs_vision=False`; vocabulary is exact-match on tokens, not substring
  ("screenshot" yes, "view" no unless in the token list).

# (REQ-17 is additively appended below; section order was corrected 2026-09-20)

## Deferred Interactions (documented non-gaps)

- Long-horizon plan SHAPE (splitting, re-planning) remains with the brain +
  goal-contract; the engine never splits steps (its previous_* read-only chip aside).
- The presentation gate and the narration gate see the same continuity fields so a
  card-heavy plan can learn "third card this plan" (frame: `recent_cards`).

### REQ-14: VLM-driven live verification (gate, not decoration)
**User Story:** As the operator I want the live gate driven by the vision stack acting
like a human user, so the decision engine is measured against what the UI actually
shows and says — not against API-replay artifacts.

**Verified:** NEW. Consumes the vision/browser stack proven in sessions 341-343
(fetch_vision + takeover + capture; docs/LIVE_TEST_VISION_BROWSER_E2E.md).

**Acceptance Criteria:**
- AC14.1: THE LIVE GATE SHALL drive the running application through the vision/browser
  control layer (navigate, click, type, screenshot) rather than REST injection, for
  every battery row.
- AC14.2: PER RUN the gate SHALL assert on screenshots: card presence/absence matching
  the recorded engine decision, chat-line non-duplication of card content; AND on the
  TTS event sequence: speak fired iff the engine answered Noul=yes.
- AC14.3: THE GATE SHALL harvest ≥ 50 engine decisions across the battery split across
  consumers before any threshold flip, and every live behavioral gap found SHALL
  decompose into a CT-DE-* contract test before the run counts as resolved.
- AC14.4: RUN ARTIFACTS (canonical screenshots dir, ledger extract, route-latency
  table) SHALL land as rows in the LT doc with a verdict per battery row.

**Edge Cases:**
- VLM stack unavailable → gate reports UNVERIFIED, never fabricates; the run does not
  count toward the 50.
- Flaky UI timing → screenshot assertions poll-bounded, never single-shot sleeps.

## Open Questions

- OQ-2: Whether `NONE` (no tool applies) maps to REASON directly or passes the memory
  fallback first — implementer records the choice in this spec on amendment.

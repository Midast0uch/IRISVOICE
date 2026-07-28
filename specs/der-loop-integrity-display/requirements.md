# Requirements: DER Loop Integrity + Honest Display

## Introduction
The DER (Deep Executive Reasoning) loop on branch `feat/agent-multi-step-tool-execution`
implements a four-scale recursive operator (fan-out / fold-back) governed by Caducean
`u`/`ξ` physics, sharing one resource `W0 = resolve_context_window() / avg_step_cost`.
A design audit (against the blueprint) plus code-level verification found the
architecture is sound, but three load-bearing behaviors are broken or regressed in the
as-built code, and — separately — the **frontend display layer renders DER-internal
step-resolution text** ("step N completed" narration, phantom tasklist cards) instead of
the real tool output / task description the user actually needs to see.

This spec fixes the three real backend gaps (B: commit-all-labeled-outcomes, C:
compound outer-loop gate, G: measured W0 debit), the minor D/E/F intent items, the 3
stale tests, and makes the display layer honest. Fundamental values from the existing
spec/blueprint (single resolver, no mode-driven fan-out, evidence-conditioned acting,
physics-driven split) are preserved — this spec does NOT rewrite the loop, it repairs
integrity and display.

### Success criteria
- Every executed DER action writes exactly one labeled outcome record
  (VERIFIED / UNVERIFIED / FAILED) — no silent success-only audit.
- The outer-loop tuner accepts a constant change only when natural-exit rate improves
  AND verified-fraction does not degrade AND tokens-per-verified-step does not degrade
  (per held-out domain).
- `work_units` is debited by measured token cost per step, not a flat 1-per-child unit.
- The frontend renders real tool output / task description, never DER-internal
  step-resolution narration or phantom cards.
- Full DER suite green (103 real tests) + 3 stale tests repaired; no regression on
  G1–G5 invariant suite.

## Requirements

### REQ-1: Commit a labeled outcome for every executed action (fixes audit B)
**User Story:** As the learning substrate I want every executed action recorded with its
true label so that I can learn from failures, not just successes.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL write a `(state, action, verified_label)` triple to the commit
  ledger for EVERY action that reaches execution — VERIFIED, UNVERIFIED, and FAILED alike.
- AC2: WHEN `verified_label == "VERIFIED"` THEN THE SYSTEM SHALL mark the step eligible
  for crystallization and hit-scoring (reward-adjacent consequences gated on VERIFIED only).
- AC3: WHEN `verified_label == "UNVERIFIED"` THEN THE SYSTEM SHALL apply partial credit
  (+0.02 edge score), SHALL NOT crystallize, and SHALL permit at most one re-propose
  before accepting.
- AC4: WHEN `verified_label == "FAILED"` THEN THE SYSTEM SHALL apply miss-scoring
  (−0.08 edge delta) and SHALL generate a tier-3 failure header (AVOID source) from the
  outcome.
- AC5: IF the commit ledger write fails THEN THE SYSTEM SHALL log at debug level and
  SHALL NOT crash the step (current behavior preserved).

**Edge Cases:**
- Vetoed action (never executed): no commit row (D0.2 — honest, not a lie).
- Reasoning-only step (tool=None): still writes a commit row with action="reasoning".
- Ledger DB unavailable: step continues, debug log only.

### REQ-2: Compound acceptance gate for the outer self-tuning loop (fixes audit C)
**User Story:** As the coach process I want to accept a tuned constant only when it is
genuinely better, so that I cannot reward-hack myself by tuning the metric I measure.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL evaluate every proposed constant change on a held-out batch that
  is disjoint from the inspiring batch.
- AC2: WHEN scoring a proposal THEN THE SYSTEM SHALL compute three held-out metrics:
  natural_exit_rate, verified_fraction, and tokens_per_verified_step.
- AC3: THE SYSTEM SHALL apply a proposed change ONLY IF all three hold: natural_exit_rate
  improves AND verified_fraction does not degrade AND tokens_per_verified_step does not
  degrade (relative to baseline).
- AC4: WHERE a `domain` is available on the held-out trajectories THEN THE SYSTEM SHALL
  require the compound gate to hold within each domain that has ≥2 sessions (heterogeneity).
- AC5: THE SYSTEM SHALL reject a "never split" proposal (U_SPLIT pushed to 1.0) because it
  wins metric one (natural exit) but loses metric two (verified-fraction).

**Edge Cases:**
- Fewer than `held_out_count` sessions: tuner returns None (no proposal), current behavior.
- All-held-out already natural exits: conservative rule may consolidate but must still pass
  the compound gate.
- Domain column absent/empty: fall back to pooled compound gate (no per-domain split).

### REQ-3: Measured-cost work-unit debit (fixes audit G)
**User Story:** As the termination resource I want each step to consume its real token
cost so that a 50k-char crawler result and a 200-char read_file are not billed equally.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL debit `work_units` by `max(1, measured_tokens / AVG_STEP_COST)`
  per executed step, where `measured_tokens` is the actual token cost of that step's
  result + prompt.
- AC2: THE SYSTEM SHALL retain `AVG_STEP_COST` as a Phase-4-tunable constant (currently
  1500) consumed by the debit formula.
- AC3: WHEN a split occurs THEN THE SYSTEM SHALL still prepay `width` units up front
  (Lyapunov Φ strictly decreases invariant preserved).
- AC4: THE SYSTEM SHALL keep `work_units` and the context window coupled to the same
  `resolve_context_window()` resource (R0.10 preserved).

**Edge Cases:**
- Token count unavailable (no tokenizer): debit 1 unit (safe floor), debug log.
- Split child with zero measured cost: debit floor of 1.
- `AVG_STEP_COST` tuned to 0 or negative: clamp to a minimum (e.g. 200) to avoid div-by-zero.

### REQ-4: Explicit depth check on VERIFIED-but-shallow steps (fixes audit D)
**User Story:** As the reflection layer I want a verified step that was done too shallowly
to be flagged, so that "verified but inadequate" does not pass silently.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL, on a VERIFIED step, run `TrailingDirector.analyze_gaps` when the
  step's measured depth (sub-step count / token investment) is below the expected depth for
  its task class.
- AC2: IF a gap is detected on a VERIFIED step THEN THE SYSTEM SHALL add a gap item to the
  queue (same path as failure-triggered gaps).
- AC3: WHERE depth analysis is intentionally not performed for a task class THEN THE SYSTEM
  SHALL document that exclusion in the code (no silent coverage loss).

**Edge Cases:**
- TrailingDirector unavailable: skip depth check, debug log (current graceful no-op).
- Step already at max depth: no further split attempted.

### REQ-5: Resolver fallback ordering (fixes audit E, minor)
**User Story:** As the resolver I want the safe fallback for a non-web goal to be reasoning,
not a web tool, so that I do not inject a tool preference at the wrong layer.

**Acceptance Criteria:**
- AC1: WHEN the LLM proposal is unparseable/invalid AND the goal's `task_class != "research"`
  THEN THE SYSTEM SHALL fall back to pheromone top-1 or `reasoning` — NEVER `crawler_query`.
- AC2: WHEN the goal's `task_class == "research"` AND capability allows THEN THE SYSTEM
  SHALL prefer `crawler_query` as Fallback-1 (current behavior, preserved).
- AC3: THE SYSTEM SHALL pass the evidence block into the prompt for `kind="reasoning"`
  steps identically to `kind="tool"` steps.

**Edge Cases:**
- No pheromone prediction and not research: return `reasoning` (tool=None).
- Evidence empty: prompt still builds (evidence section blank).

### REQ-6: Repair stale DER tests (harness, not behavior)
**User Story:** As the test suite I want my paths and mocks to match the as-built code so
that green means green.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL fix the two relative-path reads in `test_der_phase0.py`
  (`backend/agent/agent_kernel.py`, `backend/agent/dcp.py`) to resolve from the repo root
  or use an absolute path derived from the test file location.
- AC2: THE SYSTEM SHALL add `expected_output: Optional[str] = None` to the local `_Item`
  mock in `test_der_a1_a2_a3_memory_bridge.py::test_fragment_failed_output_stored` so it
  matches the real `QueueItem`.
- AC3: THE full DER suite SHALL report 0 failures after the repairs (103 real tests + the
  3 repaired).

**Edge Cases:**
- `dcp.py` path: confirm file exists at `backend/agent/dcp.py` and use
  `Path(__file__).parents[2] / "backend/agent/dcp.py"`.

### REQ-7: Agent-driven communication strategy (text + TTS narration)
**User Story:** As the user I want the agent to decide HOW it communicates — when to stay
silent, when to give a brief summary, and when to give incremental updates during a long
task that leaves me waiting — so that what I read in the chat and what I hear spoken aloud
both make sense and match what actually happened.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL treat communication as a first-class agent decision, not a fixed
  timer. The agent (not a heartbeat loop) SHALL decide, per task, whether to emit (a) no
  narration, (b) a single brief summary at completion, or (c) incremental updates during
  execution.
- AC2: WHEN a task is short (single step or sub-second result) THEN THE SYSTEM SHALL emit
  no interim narration and SHALL surface only the final result in chat (silence is correct).
- AC3: THE SYSTEM SHALL trigger incremental updates from a PHYSICS EVENT in the Caducean
  trajectory — a `|u|` band crossing (oscillating → converged), a split firing, or a
  Sub-Loop collapse — NOT a fixed wall-clock interval and NOT a naive step counter. The same
  `u`/`ξ` that governs execution SHALL govern narration timing, so the two never drift. The
  narration SHALL describe the state change itself (e.g. when a split fires, the agent says
  "now moving into sub-task" or similar) — it narrates the transition, not a generic tick.
- AC4: THE SYSTEM SHALL implement the decision as a post-step hook that reads the ALREADY
  WRITTEN commit-ledger record (REQ-1) and applies a local, cheap decision rule (task shape
  + physics-event signal). The hook SHALL perform NO new inference on silent steps and SHALL
  invoke the LLM ONLY to author the `speak` condensation when a narration is actually
  warranted — so per-step latency stays at zero for the common (silent) case.
- AC5: THE SYSTEM SHALL separate, for every communication, the `speak` text (short, spoken
  aloud via TTS) from the `display` text (full, shown in chat / documents). The `speak`
  text SHALL be a condensation the agent authors, never a raw dump of internal step
  strings (e.g. "[step N completed]").
- AC6: WHEN the agent speaks, THE SYSTEM SHALL speak only information that is already
  reflected in the chat view or a document the user can see — the spoken words and the
  visible text SHALL never contradict or describe work the display does not show.
- AC7: THE SYSTEM SHALL cancel or supersede an in-progress spoken narration when the task
  state changes (e.g. a "still working" update is replaced by the completion summary, not
  queued after it).
- AC8: THE SYSTEM SHALL choose narration tone by task class: a research task may narrate
  sources; a file task may narrate the path touched; a reasoning task may narrate the
  conclusion. The agent SHALL NOT narrate tool-internal mechanics the user cannot act on.
- AC9: IF the agent decides silence is appropriate (AC2) THEN THE SYSTEM SHALL still write
  the full result to the chat/document record so the user can review it on their own time.

**Edge Cases:**
- Long task that fails mid-way: agent SHALL speak the failure honestly (not a success
  summary queued before the failure arrived).
- User interrupts / asks a question mid-task: in-progress narration SHALL be cancelled; the
  agent SHALL re-orient to the user.
- TTS unavailable / muted: `speak` text degrades to display-only; no error surfaces to user.
- Two tasks overlap: each task's narration SHALL be scoped to its own task id; no cross-talk.
- Agent cannot decide (model failure): default to brief completion summary, never a timer
  heartbeat.
- Physics signal unavailable: fall back to step-boundary trigger (still event-driven, never
  a timer).

### REQ-8: Honest, coherent, live frontend display of DER execution
**User Story:** As the user I want the chat view, task cards, and documents to show the REAL
tool, parameters, and result of each step as it happens — and to stay coherent with what was
spoken — so that I am never misled by internal narration or phantom cards, and so the
agent's learning-from-failure (Pacman) becomes visible and valued.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL drive the task cards (`TaskListCard`) and chat stream from the
  actual `QueueItem` + commit-ledger records (real steps with real `toolName`,
  `resultPreview`, status), never from DER-internal narration text.
- AC2: THE SYSTEM SHALL update the card to reflect the agent's ONGOING activity — status
  transitions (pending → working → done / fail / vetoed / error) and real `resultPreview`
  as each step resolves — without requiring an explicit child/sub-step rendering. The card
  SHALL tell the truth at every moment, not only at task end.
- AC3: THE SYSTEM SHALL render, for each step, the real tool name, params, and result (or
  the real reasoning output) — never the DER-internal step-resolution string.
- AC4: WHEN a step has no real tool output (reasoning-only or stub) THEN THE SYSTEM SHALL
  render an explicit "reasoning" or "no output" state — never a phantom card implying
  completed work, and never a `resultPreview` fabricated from narration.
- AC5: IF a step is FAILED or UNVERIFIED THEN THE SYSTEM SHALL render its true status and
  the real error / partial result, not a success-styled card (status `fail`/`error` styling
  already exists in `TaskListCard`; it must be driven by real outcome, not assumed done).
- AC6: THE SYSTEM SHALL surface the Pacman / learning signals as visible UI — what was
  AVOIDED (from recorded failures), what was RETRIED, and what CRYSTALLIZED (verified skill)
  — so the value of learning-from-failure is visible to the user, not hidden internals.
- AC6a: THE Pacman signal SHALL render as a SUBTLE particle effect along the task card's
  surface boundary — small particles (reusing the `OrbCanvas` particle language from
  `components/iris/XurOrb.tsx` for brand consistency), NOT large or attention-grabbing. The
  particle intensity SHALL scale with learning activity (more avoided/retried/crystallized ⇒
  more visible motion), and SHALL be driven by an explicit backend trigger event so the
  effect is a verified signal that the learning loop is working, not a decorative animation.
- AC7: THE SYSTEM SHALL keep the displayed step list and the spoken narration mutually
  coherent: a step shown as "working" in chat SHALL be the step the agent is currently
  narrating; a step shown as "done" SHALL match a spoken or displayed completion.
- AC8: THE SYSTEM SHALL consume the existing `IRISStreamEvent.TOOL_CALL` / `VALIDATION_FAILED`
  / result events already emitted by `agent_kernel.py` (no new backend event contract
  needed) and SHALL map them to `TaskStep` records with real `toolName` + `resultPreview`.
- AC8a: THE SYSTEM SHALL consume a NEW backend→frontend learning event (e.g.
  `iris:task_learning` carrying `avoided` / `retried` / `crystallized` counts + a `simulate`
  flag) that triggers the Pacman particle effect (AC6a). The event is the verified signal
  that the learning loop fired; the frontend SHALL NOT animate the particles without it.
- AC9: WHEN a backend event for a step is missing THEN THE SYSTEM SHALL render "unknown"
  rather than fabricating output or marking the step done.

**Edge Cases:**
- Step vetoed (never executed): render "vetoed / not executed", no phantom output, no
  `resultPreview`.
- Step still in-flight: render "working" state, not a completed card.
- If a collapsed-children design is adopted using the existing `steps` structure, it SHALL
  collapse only on explicit COMPRESS with labels preserved (interacts with REQ-1 FAILED
  labeling); no forced child rendering is required.
- Document panel: when a step produces a document, the document SHALL be the real artifact,
  and any chat mention of it SHALL link to that real document (no orphaned references).

### REQ-9: Narration + TTS observability log (tuning instrumentation)
**User Story:** As the system tuner I want a timestamped log of every narration and TTS
playback, organized by conversation thread and task, so that I can see how often the physics
triggers fire and what was spoken — and use that to tune the narration thresholds.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL write a structured log entry for EVERY narration decision (including
  the silence decision), containing: `timestamp`, `conversation_id`, `task_id`, `step_id`,
  `trigger` (one of: `oscillating→converged` / `split` / `subloop_collapse` / `completion` /
  `silence`), `speak_text`, `display_text`, and `tts_status` (one of: `spoken` / `muted` /
  `failed` / `n/a`).
- AC2: THE SYSTEM SHALL write a separate TTS playback entry for each spoken line, containing
  `timestamp`, `conversation_id`, `task_id`, `text`, `duration_ms` (if known), and
  `playback_status` (queued / started / completed / interrupted / error).
- AC3: THE SYSTEM SHALL scope all log entries by `conversation_id` (the per-thread identifier
  already present on `AgentKernel`) so a conversation thread's narration history is
  reconstructable end-to-end, including the tasks within it.
- AC4: THE SYSTEM SHALL make the log queryable for trigger frequency — a reader SHALL be able
  to compute, per `conversation_id` and per `task_id`, how many times each `trigger` fired
  and the interval between firings — so over/under-narration is measurable.
- AC5: THE SYSTEM SHALL persist the log to a durable store (append-only file or table) that
  survives session restart, and SHALL NOT block the narration path (write is fire-and-forget
  or async, never on the user-facing latency critical path).
- AC6: THE SYSTEM SHALL include, for `split` and `subloop_collapse` triggers, the `u`/`ξ`
  value at the moment of the event, so the trigger threshold can be correlated with the
  physics state that caused it.

**Edge Cases:**
- Silence decision: still logged (trigger=`silence`, speak_text empty) so frequency analysis
  is complete (silence is a decision, not an absence).
- TTS muted / unavailable: `tts_status=muted`, playback entry still written with
  `playback_status=queued` then `error`/`n/a`.
- Conversation_id missing/None: fall back to `session_id` (existing fallback in AgentKernel).
- High-volume tasks: log write MUST stay off the critical path (async/queue); never delay a
  narration or step.

## REQ-11 — ContextPill shows REAL context + compact phase code (Wave 8)

**As a** user watching the chat widget, **I want** the context-usage pill to
reflect the *actual* model context window in use and to stay compact, **so
that** I can trust the budget number and the pill doesn't overflow with
verbose phase text.

**Acceptance Criteria:**
- **AC1:** The pill denominator SHALL be the real `max_tokens` reported
  by the backend (`context:usage` event → `iris:context_usage`), sourced
  from `resolve_context_window()` (the model in use), NOT a hardcoded 128k.
  The `128000` literal in `chat-view.tsx` is ONLY the pre-first-event
  placeholder/fallback and MUST never be treated as the real value.
- **AC2:** The phase label SHALL be a 2-3 letter code — `WRK` (working),
  `SRH` (searching), `SPK` (speaking), `IDL` (idle), `ERR` (error),
  `BLC` (balanced) — never a full word (`WORKING`/`SEARCHING`/
  `BALANCED`) that overflows the `max-w-[160px]` pill at `text-[9px]`.
  The full phase name stays in the `title` tooltip only.
- **AC3:** `currentAction` (the live "Reading example.com (2/5)" style
  string) SHALL be truncated to a fixed cap (e.g. 24 chars + ellipsis)
  for the *visible* label, with the untruncated string in `title` only.
  A long action string MUST NEVER render as a full sentence in the pill body.
- **AC4:** The unit/contract test `tests/components/ContextPill.test.tsx`
  SHALL assert: (a) `maxTokens` prop drives the denominator exactly
  (`128000` → `128.0k`, `200000` → `200.0k`); (b) phase→code
  mapping is correct; (c) a 60-char `currentAction` is truncated in
  the visible label but full in `title`. The stale `128k` assertion
  (component now formats with one decimal) MUST be fixed.

**Edge Cases:**
- Backend `context:usage` not yet received (cold start): pill shows the
  `128000` placeholder; the moment the first event arrives it switches to
  the real window. No crash, no stuck placeholder after a real event.
- `max_tokens` missing from payload: fall back to `resolve_context_window()`
  default, never to a silent 128k assumption in display logic.
- `currentAction` absent: pill shows the phase code only (no empty/overflow).

## REQ-12 — ContextPill live on EVERY model response (Wave 9)

**As a** user, **I want** the context pill to reflect real usage on every
model response (not just inside the DER loop), **so that** the budget number
is live from the first reply and stays correct when I switch conversation threads.

**Acceptance Criteria:**
- **AC1:** The backend SHALL emit `context:usage` (`IRISStreamEvent.CONTEXT_USAGE`)
  at the completion of EVERY non-DER model response (the direct path in
  `process_text_message`), in addition to the existing per-step DER emit.
  Same event shape, same `max_tokens = resolve_context_window()` denominator.
- **AC2:** The numerator SHALL be the kernel's real per-thread token count
  `self._tokens_used` (restored from the context store per conversation_id,
  agent_kernel.py:547) — NOT a hardcoded 0.
- **AC3 (the "never 0" rule):** When a conversation thread is ACTIVE
  (has history) or the user switches to a DIFFERENT thread, the pill SHALL
  show that thread's real `used_tokens` — it MUST NEVER display 0 for an
  active/switched thread. Only a genuinely brand-new thread with no history
  may report 0 (which is honest — nothing has happened yet).
- **AC4:** DER and non-DER paths SHALL share the SAME event contract
  (same shape, same `resolve_context_window()` denominator, same
  `self._tokens_used` numerator). They need not share logic — intertwine
  via the contract, not via duplicated code. A single helper
  `_emit_context_usage()` SHALL be the only emitter so the shape cannot drift.

**Edge Cases:**
- Switching threads: `restore_context_from_store()` runs, `self._tokens_used`
  becomes that thread's real count → emit reflects it. Never 0 for a thread
  that has history.
- DER task with zero steps (plan rejected before execution): the final
  `_emit_context_usage()` at `_execute_plan_der` return still fires, so the
  pill shows real usage even when no step emitted.
- Cold start (no thread, no history): `self._tokens_used` defaults to 0 →
  pill shows 0/real-window. This is the ONLY legitimate 0 and is honest.
- EventBus unavailable: emit is wrapped in try/except (no crash, matches
  existing DER emit pattern at agent_kernel.py:6547).

## REQ-13 — Ledger-learning signals are real measurements, not constants (Wave 10)

**User Story:** As the coach process I want all three of my anti-hack guards to be live
measurements from the ledgers so that the compound gate REQ-2 specifies actually gates,
instead of appearing to gate while only one signal can ever fire.

**Verified:** REAL GAP — REQ-2's *intent* is right and `_compound_accepts` exists, but
**only 1 of its 3 guards is functional**. Traced against code:

| REQ-2 guard | Status | Evidence |
|---|---|---|
| `natural_exit_rate` improves | **LIVE** | `ne_hits / n` from a real ledger column ([outer_loop.py:130-141](backend/agent/outer_loop.py:130)) |
| `verified_fraction` does not degrade | **DEAD — hardcoded constant** | [outer_loop.py:136](backend/agent/outer_loop.py:136): `vf_sum += 1.0 if vc == 0 else 1.0` — **both ternary branches are `1.0`**, so `verified_fraction` is always exactly 1.0. The check `proposed < baseline - tol` becomes `1.0 < 1.0 - 1e-6`, which is never true. The comment explains the `vc == 0` case; the `else` branch is an unfilled stub. |
| `tokens_per_verified` does not degrade | **DEAD — input never populated** | `tpv_sum += (tt / vc) if vc > 0 else 0.0` at [outer_loop.py:137](backend/agent/outer_loop.py:137) reads `tokens_total`, but the **only production caller** of `record_session_exit` ([memory.py:329-336](backend/agent/memory.py:329)) omits the `tokens_total` argument, so it defaults to `0.0` ([caducean_trajectory.py:333](backend/agent/caducean_trajectory.py:333)). The check `proposed > baseline + tol` becomes `0.0 > 0.0 + 1e-6`, never true. |

Two further REQ-2 acceptance criteria are also unmet:

- **AC4 (per-domain gate)** is unimplemented. `run_once` accepts a `domain` and passes it to
  `_ledger` ([outer_loop.py:184](backend/agent/outer_loop.py:184)), but there is no iteration
  over domains and no "≥2 sessions per domain" requirement. Every production caller
  (`run_outer_loop`, [outer_loop.py:261](backend/agent/outer_loop.py:261)) passes `domain=None`,
  so the gate is always pooled.
- **AC5 (reject "never split")** is unreachable rather than guarded. `U_SPLIT` candidates are
  `[0.4, 0.5, 0.6, 0.7]` ([outer_loop.py:39](backend/agent/outer_loop.py:39)) — `1.0` cannot be
  proposed, so the hack the AC names is prevented by the proposal list, not rejected by the
  gate. `verified_count` *is* correctly derived from the honest `der_commits` ledger
  ([caducean_trajectory.py:351-360](backend/agent/caducean_trajectory.py:351)), so the input
  for a real `verified_fraction` is already available — it is simply not used.

Net effect: the outer loop currently accepts any proposal that raises `natural_exit_rate`,
which is precisely the single-metric reward-hacking REQ-2 was written to prevent. Tasks T3
and T19 remain unchecked in `tasks.md`, so this is a half-executed requirement rather than a
regression.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL record `tokens_total` at session exit from the session's real
  accumulated LLM token count, so `tokens_per_verified` has a non-zero input.
- AC2: THE SYSTEM SHALL compute `verified_fraction` as the actual ratio of VERIFIED steps to
  total executed steps for each held-out session, read from the `der_commits` ledger, and
  SHALL NOT return a constant for any input.
- AC3: WHERE a held-out session has zero executed steps THEN THE SYSTEM SHALL treat its
  `verified_fraction` as neutral (excluded from the mean rather than counted as 1.0), so a
  fresh session neither penalizes nor inflates the guard.
- AC4: THE SYSTEM SHALL apply the compound gate per domain for every domain with ≥2 held-out
  sessions, and SHALL reject the proposal if the gate fails in ANY such domain (REQ-2 AC4).
- AC5: WHERE fewer than 2 sessions exist in every domain THEN THE SYSTEM SHALL fall back to
  the pooled compound gate, preserving current behavior.
- AC6: THE SYSTEM SHALL include a proposal value in `_PROPOSALS["U_SPLIT"]` that constitutes
  the "never split" hack (a value at or above the point where no split can occur), so REQ-2
  AC5 is enforced by the gate rather than by omission from the candidate list — and the
  behavioral test SHALL assert the gate rejects it.
- AC7: THE SYSTEM SHALL assert, by test, that each of the three guards can independently
  reject a proposal — a proposal that improves `natural_exit_rate` while degrading
  `verified_fraction` SHALL be rejected, and likewise for `tokens_per_verified`.
- AC8: THE SYSTEM SHALL log every rejection with which guard(s) failed and the numeric
  baseline/proposed values, so a gate that never fires is visible in the logs. (The current
  dead guards were invisible precisely because rejection reasons were not itemized.)

**Edge Cases:**
- Sessions archived before AC1 lands have `tokens_total = 0` → excluded from the
  `tokens_per_verified` mean rather than pulling it to 0, so historical rows cannot
  permanently disable the guard.
- A domain with exactly 2 sessions → gate applies (AC4 boundary is inclusive).
- Token count unavailable for a session (no tokenizer / streaming with no usage block) →
  estimate via the existing 4-chars≈1-token convention (`agent_kernel.py:5283`) and mark the
  row estimated; do not write 0, which would look like a real measurement of zero.
- All three guards passing trivially because the held-out set is homogeneous → AC8's logging
  makes this observable; not a correctness failure, but it must not be silent.

## REQ-14 — DER's budget is allocated from the model's REAL context window (Wave 11)

**User Story:** As the Director I want my step budget derived from the context window the model
actually has, so that I do not plan long-horizon work against capacity that does not exist.

**Verified:** REAL BUG, fixed 2026-07-28 outside the spec; this requirement exists so it cannot
regress. Observed live: `provider=cerebras model=gemma-4-31b` resolved to the **8,192** default
(no `cerebras` entry in `_KNOWN_CONTEXT_WINDOWS`, [`agent_kernel.py:884-932`](backend/agent/agent_kernel.py:884)),
and DER then reported `budget=40000`:

```
_model_window = 8_192   →  8_192 * 0.9      =  7_372
_floor        = DER_TOKEN_BUDGETS["implement"] = 40_000
_token_budget = max(7_372, 40_000)             = 40_000   ← 4.9x the window
```

The code comment stated the flat table was *"kept only as a SAFETY FLOOR... never as a ceiling."*
Because every entry is 15k–80k, the floor beat the derived value for **any model under ~44k**, so
the derivation was dead code and DER kept issuing steps while every call truncated against the real
window. `derive_work_units_0()` read the same 8,192 and produced 5 units — so the token budget and
the termination resource disagreed by 5x with each other.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL derive the DER step budget from `resolve_context_window()`, and the budget
  SHALL NEVER exceed that window.
- AC2: THE SYSTEM SHALL treat `DER_TOKEN_BUDGETS[task_class]` as a per-class **ceiling** — the most
  a task class may request — and SHALL NOT apply it as a floor.
- AC3: THE SYSTEM SHALL apply the minimum floor **last** and SHALL clamp the floor itself by the
  window, so a floor can never reintroduce an overcommit on a small model.
- AC4: THE SYSTEM SHALL derive `_token_budget` and `derive_work_units_0()` from the **same**
  `context_window` value, so the token budget and the termination resource cannot disagree.
- AC5: THE SYSTEM SHALL log the resolved budget together with the window, task class, and work
  units, so an overcommit is visible in one line rather than inferred from behavior.
- AC6: WHERE a provider/model has no known context window THEN THE SYSTEM SHALL log that the
  default was used, and the conservative default SHALL constrain the budget (never the reverse).

**Edge Cases:**
- Window smaller than the floor (e.g. a 2k model) → budget clamps to `window * 0.9`; the floor is
  ignored, not applied.
- Very large window (256k) with `task_class="quick"` → the mode ceiling (15k) binds, so a
  single-tool task is not handed 230k. This is why the mode table must be **kept**, not deleted:
  `DirectorQueue._decide_mode` ([`der_loop.py:220`](backend/agent/der_loop.py:220)) routes to QUICK
  below `BUDGET_ABSOLUTE_MIN`, and `_should_escalate`
  ([`:283-289`](backend/agent/der_loop.py:283)) compares remaining budget against `mode_budget`.
  Both lose their basis if the table is removed.
- Model swapped mid-session → budget is resolved per DER invocation, so the next task picks up the
  new window without a restart.

**Cross-spec:**
- `local-model-provider-parity` **REQ-5b** fixes the same class of defect for **local** models
  (loaded `n_ctx` beating the substring table). It does **not** cover API providers, which resolve
  through the same table and hit the same default. That gap is REQ-15 below.
- `lfm25-encoder-integration` **REQ-5** makes `task_class` encoder-derived. Because `task_class`
  selects the budget **ceiling** (AC2), a misclassification now mis-sizes the budget directly. That
  coupling is stated in neither spec and must be tested on both sides.
- Pacman filters tokens into the context window. A wrong window means Pacman optimizes against a
  fictional capacity — so this one lookup corrupts DER's budget, DER's work units, Pacman's
  filtering target, and the ContextPill denominator simultaneously.

## REQ-15 — API providers resolve a real context window (Wave 11)

**User Story:** As a user on a hosted provider I want the app to know my model's real window, so
that the ContextPill is honest and DER is not sized against a placeholder.

**Verified:** REAL GAP. `_KNOWN_CONTEXT_WINDOWS` has entries for cohere / openai / groq / deepseek /
mistral / openrouter / lmstudio / iris_local / local — and **none for `cerebras`**
([`agent_kernel.py:884-932`](backend/agent/agent_kernel.py:884)). Lookup requires
`reg_provider == provider` ([`:951-955`](backend/agent/agent_kernel.py:951)), so an unlisted
provider always falls to the 8,192 default. Live symptom: the ContextPill reads `0/8.2k` for every
turn regardless of the model in use.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL resolve a context window for every configured API provider, not only those
  present in the static table.
- AC2: WHERE a provider exposes model metadata THEN THE SYSTEM SHALL prefer that over the substring
  table — the same precedence `local` already applies to a loaded `n_ctx` (REQ-5b).
- AC3: THE SYSTEM SHALL keep the user override (`_context_window_overrides`) highest-precedence.
- AC4: IF no window can be determined THEN THE SYSTEM SHALL use a conservative default, log it, and
  surface it in the debug endpoint — an unknown window SHALL be visible, not silent.
- AC5: THE SYSTEM SHALL NOT guess a window from a model-name substring when an authoritative value
  is available.

**Edge Cases:**
- Provider-wide fallback entries (the `("openrouter", "", 32_000)` pattern) → permitted as a
  documented default, but AC4 still requires it be logged as a default rather than a known value.
- A provider reporting a window larger than the account's actual quota → out of scope; the budget
  is sized from the model's window, not from rate limits.

## Non-Requirements (Out of Scope)
- Rewriting the four-scale recursive operator or the Caducean `u`/`ξ` split physics.
- Changing the single-resolver architecture or deleting the web-regex override (already done).
- Retuning `U_SPLIT` / `AVG_STEP_COST` values (only making them tunable/correctly consumed).
- Shadow-mode A/B against the legacy loop (recommended follow-up, not in this spec).
- Session-exit stale-sweep for orphaned (crashed) sessions (recommended follow-up, REQ-2
  notes it as a gap; out of scope here to keep this spec bounded).

## Open Questions
- Should the depth-check (REQ-4) use sub-step count or token investment as the depth signal?
  (Recommend token investment; confirm with user.)
- Is the `zone="tool"` + `chunk_type="der_failure"` fragmentation (agent_kernel.py:5287)
  sufficient, or should failures also write a `der_failure` ZONE? (Verify; likely fine.)
- Exact `u`/`ξ` band threshold for the oscillating→converged narration crossing — RESOLVED
  in principle (oscillating→converged + split + Sub-Loop collapse all narrate the transition,
  e.g. "now moving into sub-task" on split); confirm numeric threshold during Wave 3.
- Pacman particle placement — RESOLVED: subtle `OrbCanvas`-style particles on the task
  card's surface boundary, small + brand-consistent, intensity scales with learning
  activity, driven by a new `iris:task_learning` backend event (verified signal).

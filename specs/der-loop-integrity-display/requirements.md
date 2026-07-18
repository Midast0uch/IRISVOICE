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

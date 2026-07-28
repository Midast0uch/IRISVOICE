# Tasks: DER Loop Integrity + Honest Display

> Each task links to a requirement ID. Grouped into waves for parallel execution.
> Branch: `feat/agent-multi-step-tool-execution`. Baseline: 103 real DER tests pass
> (3 stale failures pre-existing). Verify against `backend/tests/test_der_*.py`.

## Wave 1 — Backend integrity (the three real gaps)
- [ ] T1 (REQ-1): Change `agent_kernel.py:6551` gate so `record_commit` is called for
  VERIFIED/UNVERIFIED/FAILED (pass `verified_label`). Gate crystallization + hit-scoring on
  VERIFIED only inside the call. — `backend/agent/agent_kernel.py`,
  `backend/agent/caducean_trajectory.py`
- [ ] T2 (REQ-1): Add `verified_label` param to `CaduceanTrajectoryRecorder.record_commit`
  and persist it (new column or extend message). Ensure miss-scoring (−0.08) + AVOID header
  generation fire from FAILED outcomes. — `backend/agent/caducean_trajectory.py`,
  `backend/memory/mycelium/scorer.py`
- [ ] T3 (REQ-2): Extend `outer_loop._score` to return
  `{natural_exit_rate, verified_fraction, tokens_per_verified}`; change `run_once` acceptance
  to compound gate (all three). Use existing `domain` column for per-domain gate. —
  `backend/agent/outer_loop.py`
- [ ] T4 (REQ-3): Replace flat `work_units -= len(_children)` (agent_kernel.py:5564, 6852)
  with `work_units -= max(1, measured_tokens // AVG_STEP_COST)`; add measured-token capture
  per step; clamp AVG_STEP_COST minimum. — `backend/agent/agent_kernel.py`,
  `backend/agent/der_constants.py`

## Wave 2 — Minor intent fixes (D/E) + stale tests
- [ ] T5 (REQ-4): Add explicit VERIFIED-but-shallow depth check in
  `agent_kernel.py:6827` gap-analysis block (use token investment vs expected depth per
  task class); document any intentional exclusion. — `backend/agent/agent_kernel.py`
- [ ] T6 (REQ-5): Confirm `explorer.propose` returns `reasoning` (not `crawler_query`) for
  non-research unparseable; ensure evidence block passed for `kind="reasoning"`. —
  `backend/agent/explorer.py`
- [ ] T7 (REQ-6): Fix `test_der_phase0.py:175,226` relative paths (repo-root absolute from
  `__file__`); add `expected_output` to `_Item` mock in
  `test_der_a1_a2_a3_memory_bridge.py:99`. — `backend/tests/`
- [ ] T8 (REQ-6): Run full DER suite; assert 0 failures (103 + 3 repaired).

## Wave 3 — Agent-driven communication (REQ-7, backend + TTS)
- [ ] T9 (REQ-7): Replace the fixed 12s `narration.py` heartbeat with a `communicate()`
  post-step hook that reads the ALREADY-WRITTEN commit-ledger record (REQ-1) and applies a
  LOCAL, cheap decision rule (task shape + physics-event signal). No new inference on silent
  steps; LLM invoked ONLY to author `speak_text` when a narration is warranted. —
  `backend/agent/narration.py`, `backend/agent/agent_kernel.py`
- [ ] T10 (REQ-7): Subscribe the narration trigger to PHYSICS EVENTS in the Caducean
  trajectory — `|u|` band crossing (oscillating→converged), split firing, Sub-Loop collapse
  — NOT a timer, NOT a step counter. Same `u`/`ξ` that governs execution governs narration
  timing. Narration describes the TRANSITION itself (e.g. on split: "now moving into
  sub-task"). — `backend/agent/narration.py`, `backend/gateway/iris_ffi`
- [ ] T11 (REQ-7): Split every communication into `speak_text` (condensed, TTS) and
  `display_text` (full, chat/doc); ensure `speak_text` is agent-authored, never derived from
  "[step N completed]"; add coherence + cancellation (spoken ⊆ visible; cancel/supersede
  stale on state change); handle TTS-unavailable, user-interrupt, mid-task failure. —
  `backend/agent/tts.py`, `backend/agent/narration.py`
- [ ] T12 (REQ-7): Contract test `tests/contract/test_narration_contract.py` — short⇒silence,
  physics-event⇒incremental (not timer), `speak_text` never "[step N completed]", stale
  cancelled, `speak ⊆ display`. Behavioral `tests/behavioral/test_narration_flow.py` — full
  task, spoken matches visible, mid-fail speaks failure.
- [ ] T12b (REQ-9): Add narration + TTS observability log — structured append-only entries
  (timestamp, conversation_id, task_id, step_id, trigger, speak_text, display_text,
  tts_status; plus TTS playback entries with duration/status). Scoped by conversation_id;
  includes u/ξ at split/collapse; async/off-critical-path. Reader computes per-thread trigger
  frequency. — `backend/agent/narration.py`, `backend/agent/tts.py`, new
  `backend/agent/narration_log.py`

## Wave 4 — Honest, live frontend display (REQ-8, frontend)
- [ ] T13 (REQ-8): Audit `components/chat/TaskListCard.tsx` + `components/chat-view.tsx` for
  DER-internal narration and phantom cards; map each `TaskStep` to QueueItem + commit-ledger
  (real `toolName`/`resultPreview`/status). — `components/chat/`
- [ ] T14 (REQ-8): Make the card UPDATE LIVE to the agent's ongoing activity — status
  transitions (pending→working→done/fail/vetoed/error) + real `resultPreview` as each step
  resolves. No forced child rendering; if a collapsed-children design falls out of the
  existing `steps` structure, collapse only on explicit COMPRESS with labels preserved. —
  `components/chat/TaskListCard.tsx`
- [ ] T15 (REQ-8): Render real tool/params/result from `IRISStreamEvent.TOOL_CALL` + result
  events; explicit "reasoning"/"no output"/"vetoed"/"working"/"unknown" states; never
  fabricate `resultPreview`; FAILED/UNVERIFIED true status + real error (fail/error styling
  exists). — `components/chat/TaskListCard.tsx`
- [ ] T16 (REQ-8): Surface Pacman / learning signals as a SUBTLE particle effect on the task
  card's surface boundary — small particles reusing the `OrbCanvas` particle language from
  `components/iris/XurOrb.tsx` (brand consistency), intensity scaling with learning activity
  (avoided/retried/crystallized). Driven by a NEW backend `iris:task_learning` event
  (verified signal the learning loop fired) — frontend SHALL NOT animate without it. Keep
  chat + spoken mutually coherent; document panel links to real artifact. —
  `components/chat/TaskListCard.tsx`, `components/iris/orb/OrbCanvas.tsx`, `hooks/useTaskProgress.ts`
- [ ] T16b (REQ-8): Backend emits the `iris:task_learning` event (via the existing WS→
  CustomEvent pipeline, same shape as `iris:task_update`) carrying `avoided` / `retried` /
  `crystallized` counts + `simulate` flag, fired when the learning loop records a
  failure/avoidance/crystallization. This is the verified trigger for T16's particle effect.
  — `backend/agent/agent_kernel.py`, `backend/agent/caducean_trajectory.py`
- [ ] T17 (REQ-8): Behavioral `tests/behavioral/test_display_flow.py` — TaskListCard driven by
  real records; live update on step resolve; no phantom card on no-output; FAILED renders
  fail not done; Pacman signals visible; spoken matches visible. Contract
  `tests/contract/test_event_shape.py` — event→TaskStep mapping pinned.

## Wave 5 — Verification (contract + behavioral + standing CDD harness)
- [ ] T18 (REQ-1): Contract `tests/contract/test_ledger_contract.py` — record_commit for all
  3 labels; miss-score fires on FAILED; crystallization skipped on FAILED/UNVERIFIED.
- [ ] T19 (REQ-2): Behavioral `tests/behavioral/test_outer_loop_hack.py` — "never split"
  REJECTED; all-three improvement ACCEPTED; per-domain gate; metric shape pinned.
- [ ] T20 (REQ-3): Unit `tests/unit/test_work_units.py` — debit == measured//AVG_STEP_COST; Φ
  non-increasing.
- [ ] T21 (REQ-4): Behavioral `tests/behavioral/test_depth_check.py` — VERIFIED-but-shallow
  triggers analyze_gaps.
- [ ] T22 (G1–G5): Behavioral `tests/behavioral/test_der_invariants.py` — stay green (no
  regression from REQ-1).
- [ ] T23 (CDD HARNESS): Create `scripts/validate_der_*.py` standing harness — replays
  recorded trajectories through the FULL stack; asserts contracts (tests/contract/) +
  behaviors (tests/behavioral/) on EVERY run. Wire into CI / pre-commit.
- [ ] T24 (final): Full suite green (unit + contract + behavioral + CDD harness) +
  `npm run lint` + `npx tsc --noEmit` on frontend; commit per wave with message referencing
  REQ IDs.

## Dependency notes
- T1 before T2 (signature first) and before T18.
- T3 independent of T1/T2 but shares outer_loop.py — sequence after T1 to avoid churn.
- T9–T12 (communication, REQ-7) and T13–T17 (display, REQ-8) are independent of backend
  waves; can run in parallel with Wave 1. REQ-7's `communicate()` hook depends on REQ-1's
  committed outcome existing, so land T1/T2 before T9.
- Tests organized as tests/unit/ + tests/contract/ + tests/behavioral/; the CDD harness (T23)
  wires them together and runs on every change.
- T22 (invariants) must pass before T24 final commit.

## Wave 8 - ContextPill hardening (REQ-11)
- [ ] T25 (REQ-11): ContextPill SHALL render the REAL agent context window,
  not a hardcoded 128k. Backend already emits `context:usage` with
  `max_tokens = resolve_context_window()` (agent_kernel.py:6532) + live
  `used_tokens`; WS bridge forwards it; chat-view.tsx listens on
  `iris:context_usage` and feeds `ContextPill` maxTokens. Verify the pill
  reflects the model in use (e.g. a 200k model shows 200.0k, not 128.0k)
  when the kernel reports it. The `128000` in chat-view.tsx:368 is ONLY the
  pre-first-event placeholder and MUST stay as a fallback, never a literal.
- [ ] T26 (REQ-11): ContextPill phase label SHALL be a 2-3 letter code
  (WRK / SRH / SPK / IDL / ERR / BLC), never a full word (WORKING /
  SEARCHING / BALANCED). The verbose word overflows the max-w-[160px]
  pill at text-[9px]. Letter code is the visible label; full phase name
  stays in the `title` tooltip only.
- [ ] T27 (REQ-11): ContextPill SHALL cap/truncate `currentAction`
  so it can NEVER render a full sentence into the pill. Long action text
  is truncated to N chars (e.g. 24) with an ellipsis for the visible
  label; the untruncated string stays in `title` only. This closes the
  'phase label displayed a full sentence' defect.
- [ ] T28 (REQ-11): Unit/contract `tests/components/ContextPill.test.tsx`
  SHALL assert: (a) maxTokens from props drives the denominator exactly
  (128000 -> '128.0k', 200000 -> '200.0k'); (b) phase code maps
  correctly (working->WRK, searching->SRH, balanced->BLC, idle->IDL,
  error->ERR); (c) a 60-char currentAction is truncated in the visible
  label but full in title. Fix the stale '128k' assertion (component now
  formats with one decimal).

## Wave 9 - ContextPill live on every response (REQ-12)
- [ ] T29 (REQ-12): Add `_emit_context_usage()` helper in agent_kernel.py
  that emits `IRISStreamEvent.CONTEXT_USAGE` with
  `used_tokens = self._tokens_used` (real per-thread, restored at :547) and
  `max_tokens = self.resolve_context_window()`. Wrapped in try/except so
  EventBus failure never crashes the response path.
- [ ] T30 (REQ-12 AC1/AC2): Call `_emit_context_usage()` at the end of
  the non-DER direct response path in `process_text_message` (before the
  `return response` at ~:4011), so the pill is live from the first reply.
- [ ] T31 (REQ-12 AC3): Verify thread-switch keeps real `used_tokens`
  (restore_context_from_store sets self._tokens_used; emit reflects it;
  never 0 for a thread with history). Add a unit test asserting a restored
  conversation emits its real token count, not 0.
- [ ] T32 (REQ-12 AC4): Call `_emit_context_usage()` at the return of
  `_execute_plan_der` (~:7302) so DER tasks with zero steps still emit
  final state. Confirm DER per-step emit (:6535) and this final emit share
  the same helper/shape (no drift).
- [ ] T33 (REQ-12): Backend unit test for `_emit_context_usage` — asserts
  event fired with correct used/max, and that an active (restored) thread
  emits non-zero used_tokens while a fresh thread may emit 0.

## Wave 10 — Ledger-learning: make all three anti-hack guards live (REQ-13)

> Context: REQ-2 specified a three-signal compound gate. Verification found **only 1 of 3
> guards is functional** — `verified_fraction` is a hardcoded constant and
> `tokens_per_verified` reads a column nothing populates. T3 and T19 above remain unchecked;
> this wave completes them properly rather than re-stating them.
>
> Wave 10 is backend-only and independent of Waves 4/8/9 (frontend). It may run in parallel
> with them.

- [ ] T34 (REQ-13 AC1): Pass a real `tokens_total` into `record_session_exit` at
  [memory.py:329-336](backend/agent/memory.py:329). The call currently omits the argument, so
  it defaults to `0.0` ([caducean_trajectory.py:333](backend/agent/caducean_trajectory.py:333)).
  Source the value from the session's accumulated LLM token count (`self._tokens_used` /
  `_der_tokens_used`, `agent_kernel.py:396`). Mark estimated counts per REQ-13 edge case.
  RIPPLE: `record_session_exit`'s signature already accepts `tokens_total`
  ([caducean_trajectory.py:327-335](backend/agent/caducean_trajectory.py:327)) and the column
  already exists in the schema ([caducean_trajectory.py:88](backend/agent/caducean_trajectory.py:88))
  — **no schema migration is needed**, only the caller. Existing rows keep `0`, which AC/edge-case
  handling must exclude rather than treat as a measurement.

- [ ] T35 (REQ-13 AC2/AC3): Replace the constant `verified_fraction` at
  [outer_loop.py:136](backend/agent/outer_loop.py:136) (`vf_sum += 1.0 if vc == 0 else 1.0` —
  both branches `1.0`) with the real ratio of VERIFIED steps to total executed steps per
  session, read from `der_commits`. Exclude zero-step sessions from the mean (AC3) rather than
  scoring them 1.0.
  RIPPLE: `verified_count` is already derived from the honest ledger inside
  `record_session_exit` ([caducean_trajectory.py:351-360](backend/agent/caducean_trajectory.py:351)),
  so the numerator exists. The **denominator** (total executed steps) is not currently on the
  session-exit row — read it by counting all `der_commits` rows for the session regardless of
  label, which REQ-1 guarantees exists for every executed action. Do not add a column.

- [ ] T36 (REQ-13 AC4/AC5): Implement the per-domain compound gate. Group held-out sessions by
  `domain`, apply `_compound_accepts` within each domain having ≥2 sessions, and reject if the
  gate fails in **any** such domain. Fall back to the pooled gate when no domain reaches 2.
  RIPPLE: `run_once` already threads a `domain` into `_ledger`
  ([outer_loop.py:184](backend/agent/outer_loop.py:184)) but never iterates; every production
  caller passes `domain=None` ([outer_loop.py:261](backend/agent/outer_loop.py:261)), so the
  gate is pooled today. The `domain` column exists on both ledgers
  (`caducean_trajectories.domain`, `caducean_session_exits.domain`) — no schema change.

- [ ] T37 (REQ-13 AC6): Add the "never split" value to `_PROPOSALS["U_SPLIT"]`
  ([outer_loop.py:39](backend/agent/outer_loop.py:39), currently `[0.4, 0.5, 0.6, 0.7]`) so the
  hack REQ-2 AC5 names is **proposable and rejected by the gate**, not merely absent from the
  candidate list.
  RIPPLE: this deliberately makes a bad proposal reachable — it is only safe once T35 lands, or
  the dead `verified_fraction` guard would let it through. **Sequence T35 before T37.**

- [ ] T38 (REQ-13 AC8): Itemize rejection logging in `_compound_accepts` / `run_once`: which
  guard(s) failed, with baseline and proposed values for all three signals.
  RIPPLE: the current `logger.info("[outer_loop] rejected %s=%s (compound gate failed: %s)")`
  at [outer_loop.py:220-223](backend/agent/outer_loop.py:220) prints the metrics dict but not
  *which* guard tripped — which is why two permanently-passing guards went unnoticed. This task
  is the observability fix that makes a dead guard visible next time.

- [ ] T39 (REQ-13 AC7): Complete `tests/behavioral/test_outer_loop_hack.py` (T19's real
  content). Assert **each guard independently rejects**:
  - a proposal improving `natural_exit_rate` while degrading `verified_fraction` → rejected;
  - a proposal improving `natural_exit_rate` while degrading `tokens_per_verified` → rejected;
  - the "never split" `U_SPLIT` proposal from T37 → rejected;
  - a genuinely better proposal → accepted.
  Plus a regression assertion that `verified_fraction` is **not constant** across two
  differently-composed held-out sets — the single assertion that would have caught
  [outer_loop.py:136](backend/agent/outer_loop.py:136).
  RIPPLE: `tests/behavioral/test_outer_loop_hack.py` already exists and calls
  `record_session_exit` ([test_outer_loop_hack.py:28](backend/tests/behavioral/test_outer_loop_hack.py:28))
  — extend it; do not rewrite it, and do not weaken any assertion it already makes.

- [ ] T40 (REQ-13): Contract test `tests/contract/test_ledger_signals_contract.py` — every
  `caducean_session_exits` row written by production code has `tokens_total > 0` OR is
  explicitly marked estimated; `_score` returns three signals of which none is constant across
  varied inputs.
  RIPPLE: pins the boundary so a future refactor cannot re-stub a metric. Pairs with T39 as the
  contract decomposition of that behavioral gap.

- [ ] T41 (REQ-13): Run the full DER suite plus `scripts/validate_der_integrity.py`. Zero new
  failures. Then mark T3 and T19 above as complete, since Wave 10 fulfills them, and record the
  pre-fix constant-`verified_fraction` failure via
  `record_test(..., outcome='fail', description='verified_fraction was a hardcoded constant; 2 of 3 anti-hack guards could never fire')`.

## Wave 11 — Budget derivation + honest context windows (REQ-14, REQ-15)

- [x] **T11.1** (REQ-14 AC1/AC2/AC3) `resolve_der_token_budget(context_window, task_class)` in
  `der_constants.py`: mode value is a CEILING, window is the hard cap, floor applied last and
  clamped by the window. **DONE 2026-07-28** — replaced `max(window*0.9, floor)` at
  `agent_kernel.py:5352`.
  RIPPLE: `DER_TOKEN_BUDGETS` and `get_token_budget` are UNCHANGED — `_decide_mode`
  (`der_loop.py:220`) and `_should_escalate` (`:283-289`) still read them. Do **not** delete the
  mode table; without it a 256k model hands a single-tool "quick" task 230k and escalation loses
  its comparison basis.

- [x] **T11.2** (REQ-14 AC4/AC5) Log budget + window + class + work units in one line, both derived
  from the same `context_window`. **DONE 2026-07-28**.

- [ ] **T11.3** (REQ-15) Resolve real context windows for API providers. Add the missing `cerebras`
  entries and prefer provider metadata over the substring table.
  RIPPLE: ⚠️ **Do not invent window values.** The whole defect class here is a guess outranking a
  known value. Take the number from the provider's own metadata or from the user, not from a
  model-name heuristic. `_context_window_overrides` stays highest precedence.

- [ ] **T11.4** (REQ-14 AC6, REQ-15 AC4) Surface the resolved window + whether it was a default in
  `/api/debug/caducean`.

- [ ] **T11.5** Tests:
  - `backend/tests/unit/test_der_budget_allocation.py` — parametrized over windows
    {2k, 8k, 32k, 128k, 256k} x classes {quick, implement, full}: budget **never** exceeds the
    window; the mode ceiling binds on large windows; the floor never exceeds the window.
    Dropping a window or a class from the parametrize list is a test modification.
  - `backend/tests/contract/test_budget_workunits_agree.py` — REQ-14 AC4: both derive from the
    same window.
  - `backend/tests/behavioral/test_no_budget_overcommit.py` — an unknown provider must **not**
    produce a budget above its resolved window (the live cerebras case).

- [ ] **T11.6** (cross-spec) Add the `task_class` → budget-ceiling coupling to
  `lfm25-encoder-integration` REQ-5: an encoder misclassification mis-sizes the budget.

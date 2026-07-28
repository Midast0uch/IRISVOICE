# Tasks: Phase 2 — The Instrument

> **Blocked on Phase 1 Wave 5.** Nothing else blocks it.
> Supersedes `der-loop-integrity-display` REQ-7/8/9 and `cross-thread-crawl-fix` T36–T38.
>
> **Three fixes already landed in `01e6625b` and have NO tests.** Wave 1 exists to protect them
> before anything new is built on top.

---

## Wave 0 — Baseline

- [ ] **T0.1** Record the current card behaviour on a real websearch: what the tool label says, what
  the plan rows say at start vs end, whether anything moves before the first page arrives.
  RIPPLE: the "before" for REQ-1/2/3/4. `01e6625b` already changed three of these, so record what
  the **current build** does, not what the logs from the earlier session showed.

- [ ] **T0.2** Confirm whether the agent speaks at all during a long task now that the `NameError` is
  fixed. Capture `[SpeakTool] SPEAK intent` lines.
  RIPPLE: REQ-7's baseline. Before `01e6625b` this was **always zero**.

- [ ] **T0.3** `npx jest` — record `7 failed suites, 0 tests` and the parse errors.

---

## Wave 1 — Make the suite run, then pin what already landed (REQ-6, REQ-2, REQ-3, REQ-7)

- [ ] **T1.1** (REQ-6 AC1/AC4) Fix the jest config so the frontend suite executes.
  RIPPLE: ⚠️ **First task in the phase (D-4).** Three display bugs survived indefinitely because no
  frontend test has ever run. Writing REQ-2–REQ-5 into an unverifiable suite repeats the exact
  condition that produced them.
  Exclude vendored `llama.cpp-prismml-src/` from the project's type gate rather than "fixing" its
  errors. A suite that cannot be made to run is deleted or quarantined **with a stated reason** —
  never left failing silently (REQ-6 edge case).

- [ ] **T1.2** (REQ-2 AC6) ⚠️ **Pin the plan-immutability fix — it has no test.**
  `__tests__/useTaskProgress.plan-immutable.test.ts`: a `task:progress` with `update_step` leaves
  `description` **byte-identical** and writes `activeDetail`.
  RIPPLE: this is the regression guard for the bug that erased the agent's plan as it executed. It
  is the single most valuable test in the phase.

- [ ] **T1.3** (REQ-3, REQ-2 AC3) Pin the other two landed fixes:
  - `__tests__/useTaskProgress.toolname.test.ts` — `tool:call` overwrites a pre-resolution
    `toolName`; a missing `tool_name` does **not** clear an existing one.
  - `__tests__/useTaskProgress.detail-cleared.test.ts` — parametrized over **all four** terminal
    transitions (`tool:result`, `tool:error`, `step_done`, `task:done`).
  RIPPLE: dropping a terminal transition from the parametrize list is a test modification.

- [ ] **T1.4** (REQ-7, CT-I5) Pin the speak fix: a successful `speak()` emits `UTTERANCE_START`
  carrying `priority` and `interrupt`.
  RIPPLE: ⚠️ without this, a future refactor silently re-mutes the agent — exactly what happened when
  `speak`/`_speak_inner` was split for `CallClass.SPEAK` scoping. The failure mode is invisible:
  `tool_bridge` swallows it and the app keeps working.

- [ ] **T1.5** (REQ-6 AC3) `__tests__/TaskListCard.test.tsx` — working step animated; failed step
  failed-styled; detail beside the tool name; no bare "Step N".

---

## Wave 2 — Long tool calls become visible (REQ-4)

- [ ] **T2.1** (REQ-4, OQ-1) **Read `orchestrator.py` and `crawl_runner.py` and identify the phase
  seams** before writing any emitter.
  RIPPLE: ⚠️ the module boundaries are known (`crawl_planner`, `crawl_runner`, `crawl_worker`,
  `rerank`, `credibility`, `cite`); the seams are **not**. Do not guess phase names — read the
  control flow. This is OQ-1 and it gates T2.2.

- [ ] **T2.2** (REQ-4 AC1/AC3/AC4) Emit structured phase transitions from those seams.
  RIPPLE: today `_on_page_done` is the **only** progress emitter in the entire pipeline — plan,
  search, rerank, extract and cite are invisible, which is why the card sits at 0/2 during real
  work. Emission must be off the critical path (AC3) and rate-bounded (AC4).
  Do **not** restructure the pipeline (Non-Requirement) — add emission only.

- [ ] **T2.3** (REQ-4 AC2) Consume phase transitions in `useTaskProgress` without requiring step
  completion.
  RIPPLE: reuses the `activeDetail` field from `01e6625b`; no new step field needed.

- [ ] **T2.4** (REQ-3 AC5) Resolve `task_kernel._on_task_start`
  ([`:211-219`](backend/agent/task_kernel.py:211)) dropping `steps` — forward them, or document why
  this second `task:start` path deliberately carries none.
  RIPPLE: the frontend comment at `useTaskProgress` says the backend emits `task:start` **twice**
  (plan skeleton, then DER queue). One path carries steps and one does not; the reconciliation logic
  depends on knowing which.

- [ ] **T2.5** Tests: `backend/tests/behavioral/test_card_moves_without_a_page.py` — **fails today**.

---

## Wave 3 — One card, honest states (REQ-1, REQ-5)

- [ ] **T3.1** (REQ-1 AC3) Replace the no-steps "thinking…" branch
  ([`chat-view.tsx:2973`](components/chat-view.tsx:2973)) with a minimal state of the **same** card.
  RIPPLE: this is the "different card" the user sees — not a second component, but the absence of
  one. CT-I1 pins that exactly one render site remains.

- [ ] **T3.2** (REQ-1 AC4/AC5) Drive status from real records; render "unknown" for a missing event
  rather than fabricating or marking done.

- [ ] **T3.3** (REQ-5) Verify sub-loop append under a real DER split; keep `totalSteps` coherent and
  preserve completed steps across plan revision.
  RIPPLE: `add_step` already emits real `description` + `tool_name`
  ([`agent_kernel.py:7724-7732`](backend/agent/agent_kernel.py:7724)) — **NO CHANGE needed** to the
  emitter. What is unverified is behaviour under splits. Test, do not rewrite.

- [ ] **T3.4** Tests: `test_subloop_appends_to_same_card.py`, `test_failed_step_renders_failed.py`,
  `__tests__/useTaskProgress.substeps.test.ts`.

---

## Wave 4 — Agent-driven speech (REQ-7) + close T36

- [ ] **T4.1** (REQ-7 AC7) **Close `cross-thread-crawl-fix` T36 and update its two tests together.**
  - `test_narration_contract.py:63` asserts `"Still" in t`
  - `test_narration_flow.py:175` asserts `"researching"`
  Both assert wording that `cross-thread-crawl-fix` REQ-8 AC5 **requires removing**, and
  [`narration.py:140`](backend/agent/narration.py:140) already removed it.
  RIPPLE: ⚠️ this is a spec/test conflict, not a code bug. Update the tests to assert the **new**
  contract, and mark T36 done in the same change so spec and tests move together. Do **not** change
  `narration.py` back to satisfy the old assertions.

- [ ] **T4.2** Fix `test_kernel_separation_behavior::test_utterance_forwarded_during_expand`.
  RIPPLE: asserts synchronous `tts.speak`; `_on_utterance_start` now dispatches via a daemon thread
  ([`conversation_kernel.py:415-420`](backend/agent/conversation_kernel.py:415)). The **code is
  correct**; the test encodes the pre-threading design and is racy. Await the thread; do not revert
  the threading.

- [ ] **T4.3** Fix the two `test_crawler_task_progress` failures.
  RIPPLE: stub `_fake_run` is missing `job_id` (production gained the parameter) and `InternetGate`
  blocks `search` in-fixture. Both are **double/fixture repairs** — correcting a stub's signature to
  match production is not weakening a test.

- [ ] **T4.4** (REQ-7 AC1/AC2) Make narration agent-decided per task rather than interval-only.
  RIPPLE: OQ-2 — inline preserves ordering with the DER step; off-path is safer for latency. Decide
  from measured per-call latency, not in advance.

- [ ] **T4.5** (REQ-7 AC5/AC6, D-5) Rate-limit speech below the final answer, and make a swallowed
  speech exception log at **failure** level.
  RIPPLE: ⚠️ a 100% failure rate presented as intermittence for as long as the `NameError` existed,
  because `tool_bridge` logged it as a WARNING and continued. Any swallow that leaves TTS silent must
  be loud.

- [ ] **T4.6** (REQ-7 AC3, CT-I6) Enforce spoken ⊆ visible.

- [ ] **T4.7** Tests: `test_agent_speaks_during_long_task.py`, `test_speech_failure_is_loud.py`.

---

## Wave 5 — Learning signal (REQ-8) + observability (REQ-9)

- [ ] **T5.1** (REQ-8 AC3) Emit the backend learning event carrying
  `avoided` / `retried` / `crystallized`.
  RIPPLE: the frontend already accepts `task:learning` and stores `learningSignal` — **NO CHANGE**
  needed in `useTaskProgress`. The trigger and the rendering are what is missing.

- [ ] **T5.2** (REQ-8 AC1/AC2/AC4) Render as a subtle boundary effect consistent with the existing
  orb particle language; intensity scales with activity.
  RIPPLE: ⚠️ AC3 — never animate without the backend event. The effect is **evidence** the learning
  loop fired, not decoration. An always-on animation would be a phantom card in a new form.

- [ ] **T5.3** (REQ-9) Structured logs for narration and card transitions, off the critical path.

---

## Wave 6 — Verification + close-out

- [ ] **T6.1** Contract tests CT-I1..CT-I7.
- [ ] **T6.2** Behavioral: `test_websearch_card_tells_truth.py` (the end-to-end REQ-1/2/3 assertion).
- [ ] **T6.3** Build `scripts/validate_display_coherence.py` with all 8 harness assertions.
  RIPPLE: assertions **3 and 8** are the regression guards for the two `01e6625b` fixes that
  currently have none; **7** is what proves REQ-4 landed rather than being satisfied by page events.
- [ ] **T6.4** Full regression: `pytest backend/tests`, `npx jest`, `npx tsc --noEmit`.
- [ ] **T6.5** Manual verification against T0.1–T0.3 — drive a real websearch and a long multi-step
  task; confirm the card, the plan text, the rotation, and the speech.
- [ ] **T6.6** Update `docs/CADUCEAN_ARCHITECTURE.md` §9 (**append**) and `bootstrap/GOALS.md`.

---

## Dependency / parallelization notes

**Hard sequencing:**
- **Phase 1 Wave 5 before anything here.**
- **T1.1 before every other frontend task.** Without a running suite, nothing after it is verifiable.
- **T2.1 before T2.2.** Do not invent phase names; read the control flow first.
- **T4.1 closes T36 and its tests together** — not separately.

**Parallelizable:**
- **Wave 2 (backend phase emission) and Wave 3 (frontend card states) are independent.**
- Wave 4 (speech) is independent of Waves 2–3.
- T5.3 (logging) can be written any time.
- All test-writing precedes its implementation task.

**Riskiest tasks:**
1. **T1.2/T1.4 — skipping the pins.** Three fixes are live and unprotected. Both failure modes are
   silent: the plan quietly stops being preserved, or the agent quietly stops speaking.
2. **T4.1 — "fixing" narration.py to satisfy the old tests.** That reverts an implemented
   requirement to satisfy a superseded assertion. The tests are what move.
3. **T4.2 — reverting the threading.** `_on_utterance_start` dispatching off the EventBus thread is
   correct; a multi-second utterance must not block other subscribers.
4. **T2.2 — emitting from the wrong layer.** Progress must reflect real phase transitions, not a
   timer. A bar that moves without evidence is the phantom-card failure again.
5. **T5.2 — animating without the event.** Same failure class as 4.

**Known pre-existing failures resolved by this phase:** `test_narration_contract`,
`test_narration_flow` (T4.1); `test_kernel_separation_behavior` (T4.2);
`test_crawler_task_progress` ×2 (T4.3); `npx jest` running 0 tests (T1.1).

### Baseline record
<!-- T0.1-T0.3 record "before"; T6.5 records "after". -->

| Observation | Before | After |
|---|---|---|
| Tool label shown on a websearch step | | |
| Plan row text at task start vs end | | |
| Card movement before first page fetched | | |
| Sub-loop steps: same card? | | |
| Spoken utterances during a long task | | |
| `npx jest` | 7 suites failed, 0 tests | |

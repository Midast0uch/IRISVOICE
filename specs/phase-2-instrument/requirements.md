# Requirements: Phase 2 — The Instrument (narration + honest live display)

> **Execution position: SECOND.** Blocked only on Phase 1 Wave 5.
> Phases 3–5 are validated by watching IRIS work; this phase is what makes watching reliable.
>
> **Supersedes** `der-loop-integrity-display` REQ-7/8/9 and `cross-thread-crawl-fix` REQ-8 (T36–T38).
> Those documents remain for history; **this file is authoritative for Phase 2.**

## Decisions Locked

Resolved with the user 2026-07-28. Do **not** re-litigate.

1. **One task card, always.** No fallback card type, no second component. The single card handles
   websearch, multi-step execution, and sub-loop steps identically.
2. **The plan is immutable; progress is separate.** A step's `description` is what the agent set out
   to do and never changes. Live progress goes to a separate field rendered beside the tool name.
3. **Query/source URLs rotate beside the tool name**, not in place of the plan text.
4. **A step never displays as bare "Step N".** Every step shows real intent.
5. **Sub-loop steps update the same card.** Newly discovered steps append; they do not spawn a
   second card.
6. **The agent decides when to speak, not a timer.** Narration is agent-driven per task, not a
   fixed-interval heartbeat.
7. **Spoken ⊆ visible.** Anything spoken must correspond to something shown. Internal DER narration
   is never spoken and never rendered as a result.

## Introduction

Four things had to be true before this phase could be written, and three of them just became true:

- **The speak tool raised `NameError` on every call** — `UTTERANCE_START` was never emitted, so TTS
  could not fire from the agent's own speech path. Fixed in `01e6625b`. Narration was *dead*, not
  inconsistent.
- **`update_step` overwrote the step's `description`**, replacing the plan with transient progress.
  Fixed in `01e6625b` — progress now writes `activeDetail`.
- **`tool:call` never wrote the resolved tool name** to the step, so the card showed the planner's
  pre-resolution guess for the whole task. Fixed in `01e6625b`.
- **The frontend test suite runs 0 tests** (7/7 suites fail to parse). Still true — REQ-6.

What remains is the part those fixes exposed: the card is only told about *fetched pages*. Every
other phase of a crawl — plan, search, rerank, extract, cite — is invisible, which is why a card sits
at 0/2 while real work happens.

### Success criteria

- Every step shows its **real** tool name and real intent — never "tool", never bare "Step N".
- The plan visible in the dropdown is **unchanged** for the life of the task; progress appears
  beside the tool name and rotates per source.
- A long tool call produces visible movement without a fetched page (phase transitions, not just
  page events).
- A sub-loop step appends to the **same** card.
- The agent speaks during long-horizon work, and everything spoken corresponds to something visible.
- A failed or vetoed step renders as failed or vetoed — never success-styled, never a phantom card.
- `npx jest` runs the frontend suite.

## Requirements

---

### REQ-1: One task card, driven by real execution records

**User Story:** As a user I want one consistent card for every kind of task, so that a websearch and
a multi-step build look and behave the same.

**Verified:** Partially in place. There is exactly **one** `TaskListCard` render site
([`chat-view.tsx:2986`](components/chat-view.tsx:2986)), gated on `taskProgress.steps.length > 0` —
so there is no competing component. But `:2973` renders a plain "thinking…" when there are no steps,
which is the degenerate state that reads as a "different card".

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL drive the card from real `QueueItem` / commit-ledger records — real
  `toolName`, real `resultPreview`, real status — never from DER-internal narration text.
- AC2: THE SYSTEM SHALL use the **same** card for websearch, multi-step execution, and sub-loop
  work. No second card component and no fallback card SHALL exist.
- AC3: WHEN a task produces no plan steps THEN THE SYSTEM SHALL show a single consistent minimal
  state, not a visually different card.
- AC4: THE SYSTEM SHALL render a step's true status (`pending` / `working` / `done` / `fail` /
  `error` / `vetoed` / `skipped`) — a failed step SHALL NOT be success-styled.
- AC5: WHEN a backend event for a step is missing THEN THE SYSTEM SHALL render "unknown" rather than
  fabricating output or marking the step done.

**Edge Cases:**
- Step vetoed and never executed → "vetoed / not executed", no `resultPreview`.
- Step still in flight → "working", not a completed card.
- Task with a single step → same card, one row.

---

### REQ-2: The plan is immutable; live progress is separate and rotates

**User Story:** As a user I want the dropdown to keep showing what the agent set out to do, while
the header shows what it is doing right now.

**Verified:** REAL BUG — **fixed 2026-07-28 in `01e6625b`**, unprotected by tests. `update_step`
previously did `steps[workingIdx] = { ...step, description: action }`, replacing *"Search for recent
Python 3.13 features"* with *"Reading example.com (2/5)"* — the plan was erased as it executed. Now
writes `activeDetail` / `activeProgress`; `description` is immutable.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL treat a step's `description` as immutable for the life of the step. Live
  progress SHALL NOT overwrite it.
- AC2: THE SYSTEM SHALL render the live source (URL, host, or title) **beside the tool name**, and
  SHALL rotate it as sources change.
- AC3: THE SYSTEM SHALL clear live detail on every terminal transition, so a finished step never
  advertises a source it is no longer reading.
- AC4: THE SYSTEM SHALL take the live detail from a **structured** field, and SHALL NOT parse it out
  of a display sentence.
- AC5: THE SYSTEM SHALL animate the currently-executing step distinctly from pending and completed
  steps.
- AC6: THE SYSTEM SHALL prove AC1–AC3 by test — the fix currently has none.

**Edge Cases:**
- Very long URL or title → truncated in place, full value available on hover.
- Source changes faster than it can be read → rotation is throttled; the card must not flicker.
- Task ends with a step still carrying live detail → AC3 clears it.

---

### REQ-3: Every step shows real intent — never "tool", never "Step N"

**User Story:** As a user I want each row to say what is actually being done, so the card is
readable at a glance.

**Verified:** REAL BUG — **root cause found and fixed in `01e6625b`.** The card was emitted from
`_plan.steps` **one second before** tool resolution ran:

```
16:57:04  [AgentKernel] TASK_CARD ... steps=2
16:57:05  [DER] box resolved tool='crawler_query' for step 1 (source=llm)
```

`tool:call` carried the resolved name but the frontend never wrote it to the step. Separately,
`task_kernel._on_task_start` ([`:211-219`](backend/agent/task_kernel.py:211)) forwards only
`task_id` / `description` / `task` — **it drops `steps` entirely**, so one of the two `task:start`
paths carries no step data at all.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL display the **resolved** tool name, updating the step when resolution lands
  after the plan renders.
- AC2: THE SYSTEM SHALL NOT display a generic placeholder (`tool`, `direct`, `unknown`) where a real
  tool name is available.
- AC3: THE SYSTEM SHALL NOT display a bare positional label ("Step 3") as a step's description.
- AC4: WHERE a step is reasoning-only with no tool THEN THE SYSTEM SHALL render an explicit
  "reasoning" state rather than an empty or generic tool label.
- AC5: THE SYSTEM SHALL make `task_kernel._on_task_start` forward step data, or SHALL document why a
  second `task:start` path exists that deliberately carries none.

**Edge Cases:**
- Tool resolution fails → the step shows the failure, not the pre-resolution guess.
- A tool with no friendly title → title-cased tool name, not the raw identifier.

---

### REQ-4: Long tool calls produce visible movement

**User Story:** As a user I want to see progress during a long websearch, so I know the agent is
working rather than stuck.

**Verified:** REAL GAP — progress is emitted from **one place in the whole pipeline**.
`_on_page_done` ([`tool_bridge.py:1745`](backend/agent/tool_bridge.py:1745)) fires on
`CRAWLER_PAGE_FETCHED` and nothing else does. A crawl also spans plan → search → rerank → extract →
cite (`crawl_planner`, `crawl_runner`, `crawl_worker`, `rerank.py`, `credibility.py`, `cite.py`), and
every one of those phases is invisible. This is why a card sits at 0/2 while real work happens.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL emit a progress event on **phase transitions** within a long tool call, not
  only on fetched pages.
- AC2: THE SYSTEM SHALL update the card on each such transition without requiring the step to
  complete.
- AC3: THE SYSTEM SHALL keep progress emission off the critical path — an emit failure SHALL NOT
  fail or stall the tool.
- AC4: THE SYSTEM SHALL bound progress event frequency so a fast pipeline cannot flood the UI.
- AC5: WHERE a tool reports no phases THEN THE SYSTEM SHALL still show the step as working, and
  SHALL NOT imply completion.

**Edge Cases:**
- Crawl returns zero pages → phases still emitted; the step resolves with an honest empty result.
- Tool fails mid-phase → last phase visible, then the failure state (REQ-1 AC4).
- Non-crawler long tool → AC5 baseline behaviour.

---

### REQ-5: Sub-loop steps update the same card

**User Story:** As a user I want steps the agent discovers mid-task to appear in the existing plan,
so I can follow one list instead of hunting for a new card.

**Verified:** Mechanism exists and is correct — `add_step` is emitted with the real `description` and
`tool_name` ([`agent_kernel.py:7724-7732`](backend/agent/agent_kernel.py:7724)) and the frontend
appends it ([`useTaskProgress.ts`](hooks/useTaskProgress.ts) `add_step` branch). What is unverified is
that it holds under sub-loop splits and that `totalSteps` stays coherent.

**Acceptance Criteria:**
- AC1: WHEN DER discovers a new step THEN THE SYSTEM SHALL append it to the existing card.
- AC2: THE SYSTEM SHALL NOT create a second card for sub-loop or grafted steps.
- AC3: THE SYSTEM SHALL keep the step counter coherent as steps are appended — the denominator
  SHALL grow with the list.
- AC4: THE SYSTEM SHALL preserve already-completed steps when the plan is revised.
- AC5: THE SYSTEM SHALL give every appended step a real description and tool name (REQ-3).

**Edge Cases:**
- Sub-loop splits into several children → all append to the same card.
- A revised plan arrives after steps completed → completed status preserved (AC4).
- Step limit reached → capped with an explicit indication, not silently truncated.

---

### REQ-6: The frontend test suite runs

**User Story:** As a maintainer I want frontend tests to execute, so that display regressions are
caught by CI rather than by the user.

**Verified:** REAL GAP — `npx jest` reports **7 failed suites, 0 tests**, all
`SyntaxError: Cannot use import statement outside a module`. **No frontend test has run.** This is
why the `description`-overwrite bug (REQ-2) survived in a hook indefinitely.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL make `npx jest` execute the frontend suite with zero configuration errors.
- AC2: THE SYSTEM SHALL make the suite fail on a real regression — a green run on a broken build is
  not acceptance.
- AC3: THE SYSTEM SHALL cover `useTaskProgress` state transitions and `TaskListCard` rendering.
- AC4: THE SYSTEM SHALL keep `npx tsc --noEmit` clean for `components/`, `hooks/`, and `app/`.

**Edge Cases:**
- Vendored directories (`llama.cpp-prismml-src/`) produce type errors → excluded from the project's
  own type gate, not "fixed".
- A suite that cannot be made to run → deleted or quarantined with a stated reason, never left
  failing silently.

---

### REQ-7: The agent decides when to speak

**User Story:** As a user I want IRIS to tell me what it is doing during long work, in its own
words, at moments that matter.

**Verified:** Newly testable. The speak tool raised `NameError` on **every** call until `01e6625b`
([`speak_tool.py`](backend/agent/tools/speak_tool.py) — `_speak_inner` read `priority`/`interrupt`
without receiving them, raising above the inner try/except so `UTTERANCE_START` was never emitted).
`tool_bridge` swallowed it as a WARNING, so it read as inconsistency. The crawl progress narration at
[`tool_bridge.py:1757`](backend/agent/tool_bridge.py:1757) has therefore **never** spoken.

`cross-thread-crawl-fix` REQ-8 AC5 / T36 already requires replacing the generic
`"Still researching the web."` heartbeat with real progress; the implementation did so
([`narration.py:140`](backend/agent/narration.py:140)) but **T36 is still unchecked** and two tests
still assert the old wording.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL let the agent decide, per task, whether and when to speak — not a fixed
  interval alone.
- AC2: THE SYSTEM SHALL speak progress during long-horizon work, using real content rather than a
  generic string.
- AC3: THE SYSTEM SHALL keep everything spoken a subset of what is visible (Decision Locked #7).
- AC4: THE SYSTEM SHALL never speak DER-internal narration or step-resolution strings.
- AC5: THE SYSTEM SHALL rate-limit speech so progress cannot interrupt the final answer.
- AC6: IF speech fails THEN THE SYSTEM SHALL log it as a failure — a swallowed exception that leaves
  TTS silent SHALL NOT be treated as normal operation.
- AC7: THE SYSTEM SHALL close `cross-thread-crawl-fix` T36 and update the two tests that assert the
  superseded wording, so spec and tests move together.

**Edge Cases:**
- Speech unavailable (no TTS) → logged once, work continues.
- User speaking / recording → suppressed by the existing phase gate, not queued indefinitely.
- Very long task → AC5 throttle prevents narration spam.

---

### REQ-8: Learning signals are visible

**User Story:** As a user I want to see that IRIS learned something — what it avoided, retried, or
crystallized — so the value of learning-from-failure is visible rather than internal.

**Verified:** NEW. `learningSignal` already flows to the card
([`useTaskProgress.ts`](hooks/useTaskProgress.ts) `task:learning` branch) and is accepted by
`TaskListCard`; what is missing is the backend trigger and the rendering.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL surface `avoided` / `retried` / `crystallized` signals on the card.
- AC2: THE SYSTEM SHALL render them as a **subtle** effect on the card's boundary, consistent with
  the existing orb particle language — not a large or attention-grabbing element.
- AC3: THE SYSTEM SHALL drive the effect from an explicit backend event, and SHALL NOT animate
  without one — the effect is evidence the learning loop fired, not decoration.
- AC4: THE SYSTEM SHALL scale intensity with learning activity.
- AC5: THE SYSTEM SHALL NOT clear steps or working state when a learning signal arrives.

**Edge Cases:**
- No learning this task → no effect, no placeholder.
- Signal arrives after task completion → rendered on the completed card, then decays.

---

### REQ-9: Narration and display are observable

**User Story:** As the tuner I want a timestamped record of what was spoken and shown, scoped by
thread, so narration thresholds can be set from data.

**Verified:** Partially — `[SpeakTool] SPEAK intent` already logs ts / conv / turn / priority / uid /
text ([`speak_tool.py:124-132`](backend/agent/tools/speak_tool.py:124)). That log line is what
raised the `NameError`; it now works.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log every narration with timestamp, conversation, turn, and text.
- AC2: THE SYSTEM SHALL log every card state transition with the step id and new status.
- AC3: THE SYSTEM SHALL make spoken-vs-visible coherence checkable from logs alone (AC3 of REQ-7).
- AC4: THE SYSTEM SHALL keep logging off the critical path.

**Edge Cases:**
- High-volume progress → sampled or aggregated, never silent.
- Missing thread id → logged with an explicit `unknown` scope.

---

## Non-Requirements (Out of Scope for Phase 2)

- **Rewriting the crawl pipeline.** REQ-4 adds phase *emission*; it does not restructure
  `orchestrator` / `crawl_runner` / `crawl_worker`.
- **The encoder** → Phase 4. Semantic step verification is not part of honest display.
- **The model switcher, Send-pill removal, ContextPill redesign** → Phase 5.
- **The local model loader** → Phase 3.
- **Changing DER band thresholds** (`0.8` / `0.3`) or the mode table.
- **Outer-loop guard repair** (`der-loop-integrity-display` REQ-13 / Wave 10) — separate concern,
  unblocked but not scheduled here.

## Open Questions

- **OQ-1:** Which crawl phases are worth emitting for REQ-4? Needs a read of `orchestrator.py` and
  `crawl_runner.py` — the module boundaries are known, the seams are not. Do this first in Wave 2.
- **OQ-2:** Should REQ-7 narration be inline with the DER step or dispatched off-path? Inline
  preserves ordering; off-path is safer for latency.
- **OQ-3:** Jest ESM vs CommonJS for REQ-6 — whichever makes the existing suites run with the least
  reshaping of what they assert.

# Tasks: Phase 5 — Model Switcher + ContextPill

> **Blocked on Phase 1** (persistence, `loaded`), **Phase 3** (`loaded` truthful for local models),
> **Phase 4** (`purpose` filter, so encoders are never offered).
> Everything needed is in this spec.

---

## Wave 0 — Baseline

- [ ] **T0.1** (REQ-1) Audit every send path: `Enter` at
  [`chat-view.tsx:1535`](components/chat-view.tsx:1535) and
  [`:3252`](components/chat-view.tsx:3252), plus any touch / on-screen-keyboard / IME path.
  RIPPLE: ⚠️ if a path exists that cannot reach `Enter`, **REQ-1 AC1 is blocked and that is a
  finding** — do not remove the button and work around it.

- [ ] **T0.2** (REQ-5, REQ-6) Record the ContextPill's current numbers: denominator on a DER task and
  on a direct reply; whether it updates outside DER; what it shows on a fresh thread.
  RIPPLE: Phase 1 already changed the denominator. Record what the **current build** shows.

- [ ] **T0.3** Confirm Phases 1, 3, 4 landed: `loaded` truthful, `purpose` present,
  `ModelInferenceSection` already filtered to `purpose === "chat"`.

- [ ] **T0.4** Baseline: `pytest backend/tests`, `npx jest`, `npx tsc --noEmit`.

---

## Wave 1 — Send removal, guards first (REQ-1)

- [ ] **T1.1** (REQ-1 AC3) ⚠️ **Move the guards into the send path BEFORE deleting anything.**
  `!inputText.trim() || isTyping || voiceState === 'listening'`
  ([`:3296`](components/chat-view.tsx:3296)) becomes a precondition inside `handleSendMessage`.
  RIPPLE: ⚠️ **The single silent regression available in this phase.** The button is the sole holder
  of those conditions; `Enter` calls `handleSendMessage` directly. Delete first and `Enter` sends
  while IRIS is listening or mid-response — no error, no failing test.

- [ ] **T1.2** (REQ-1 AC1/AC2/AC4) Remove the Send pill
  ([`:3293-3310`](components/chat-view.tsx:3293)) and reflow the row.
  RIPPLE: also resolve the pre-existing overflow at
  [`:3347-3368`](components/chat-view.tsx:3347) — `ContextPill` declares `max-w-[200px]` inside a
  fixed `w-[32px] h-[32px]` container. Fix it here rather than positioning the switcher against a
  container whose real width nothing states.

- [ ] **T1.3** Tests: `__tests__/InputRow.test.tsx` — Send absent; `Enter` sends; `Shift+Enter`
  newlines; **each of the three removed conditions still blocks a send**, parametrized. Dropping a
  condition is a test modification.

---

## Wave 2 — The switcher (REQ-2, REQ-4)

- [ ] **T2.1** (REQ-2 AC1, REQ-3 AC1) Build `ModelSwitcher` as a **sibling** of `ContextPill`,
  reading `useInferenceState` and writing through its existing `sendRoleBinding`.
  RIPPLE: no new endpoint, no new socket message — the hook already fetches
  `/api/inference/state`, merges `iris:provider_added` / `iris:role_bindings_updated`, and exposes
  the writer ([`:47-121`](hooks/useInferenceState.ts:47)). A second path to the same state is how
  the switcher and settings panel end up disagreeing (REQ-4 AC4).
  **`ContextPillProps` is NOT extended** (CT-S1).

- [ ] **T2.2** (REQ-2 AC2/AC3/AC4) Filter: API providers with `has_key`, local models with `loaded`,
  **`purpose === "chat"` only**.
  RIPPLE: Phase 4 registers `embedding` / `rerank` instances that must not appear here. Phase 4 T2.2
  already filtered the **settings** panel — this is the chat-row equivalent, not a duplicate of that
  logic. Do not re-implement the settings filter.

- [ ] **T2.3** (REQ-2 AC7) Independent Brain and Tool selection.
  RIPPLE: OQ-1 — two dropdowns vs one with a role toggle. **Measure the row's width budget after
  T1.2's reflow before choosing.**

- [ ] **T2.4** (REQ-2 AC6, REQ-4 AC3) Show the active model; a failed bind surfaces the error and
  **leaves the previous selection active**.
  RIPPLE: never show the new selection as active before the bind succeeds — that is the switcher
  telling the user something untrue.

- [ ] **T2.5** (REQ-2 AC8/AC9) `has_key` boolean only — no key, prefix, length, or masked form
  crosses the boundary. Actionable empty state; loading state **distinct** from empty.
  RIPPLE: `ModelInferenceSection.tsx:33` already types `has_key?: boolean` — follow it. An empty list
  during load reads as "nothing configured" and sends users to settings for no reason.

- [ ] **T2.6** (REQ-4 AC1/AC2/AC5) Derive availability from the registry; update on both provider
  events; show persisted state after a restart.

- [ ] **T2.7** (REQ-7) Log each switch: role, previous id, new id, outcome. Never a credential.

- [ ] **T2.8** Tests: `__tests__/ModelSwitcher.test.tsx`, `test_switch_from_chat_row.py`,
  `test_switch_failure_keeps_previous.py`, `test_brain_and_tool_independent.py`,
  `test_switcher_survives_restart.py`.

---

## Wave 3 — ContextPill truth and liveness (REQ-5, REQ-6)

- [ ] **T3.1** (REQ-6 AC1/AC2) Emit `context:usage` at the completion of **every non-DER** model
  response (the direct path in `process_text_message`), with the **same shape and the same
  `resolve_context_window()` denominator** as the DER per-step emit.
  RIPPLE: ⚠️ two emitters with two denominators is worse than a stale number — it looks live and is
  wrong. CT-S3 pins parity.

- [ ] **T3.2** (REQ-6 AC3/AC4) Reflect the correct thread's usage on a thread switch; keep emission
  off the critical path.

- [ ] **T3.3** (REQ-5) Verify the pill sources `max_tokens` from the event, renders the compact phase
  code with the full name in `title`, caps action text, and never reverts to the cold-start
  placeholder once a real event has arrived.
  RIPPLE: ⚠️ **the displayed denominator changed when Phase 1 landed** — a 16k-loaded Mistral shows
  16k not 32k, and unlisted providers no longer show 8.2k. **Expected. Do not "fix" it back.**

- [ ] **T3.4** Tests: `test_context_usage_on_direct_reply.py` (**fails today**),
  `test_context_usage_thread_switch.py`, `__tests__/ContextPill.test.tsx`,
  `backend/tests/contract/test_context_usage_parity.py` (CT-S3).

---

## Wave 4 — Harness and close-out

- [ ] **T4.1** Contract tests CT-S1..CT-S5.
- [ ] **T4.2** Build `scripts/validate_switcher.py` with all 7 harness assertions.
  RIPPLE: assertion **7** (every send-blocking condition still blocks) is worth running on every
  commit — it is the only guard against a silent UX regression that produces no error and no report.
- [ ] **T4.3** Full regression: `pytest`, `npx jest`, `npx tsc --noEmit`. Compare against T0.4.
- [ ] **T4.4** Manual verification against T0.1–T0.2: switch models from the chat row, confirm
  settings agrees, confirm the pill is live on a direct reply, confirm `Enter` still refuses to send
  while listening.
- [ ] **T4.5** Update `docs/CADUCEAN_ARCHITECTURE.md` §9 (**append**) and `bootstrap/GOALS.md`
  (**Domain 26**).

---

## Dependency / parallelization notes

**Hard sequencing:**
- **Phases 1, 3, 4 before Wave 2.** The switcher needs truthful `loaded` and `purpose`.
- **T1.1 before T1.2.** Guards move before the button goes. Non-negotiable.
- **T1.2 before T2.3.** The width budget for OQ-1 only exists after the reflow.

**Parallelizable:**
- **Wave 3 (ContextPill / `context:usage`) is independent of Waves 1–2** — different files, backend
  vs frontend.
- T2.7 (logging) any time.
- All test-writing precedes its implementation task.

**Riskiest tasks:**
1. **T1.1/T1.2 — the disabled guards.** Deleting the button deletes
   `!inputText.trim() || isTyping || voiceState === 'listening'` unless they move first. Symptom:
   `Enter` sends while IRIS is listening or mid-response, with no error.
2. **T3.1 — mismatched denominators.** A pill that shows one number during DER and another outside
   it looks live and is wrong.
3. **T2.4 — showing a selection as active before it binds.** The switcher lying about the model in
   use is worse than not having a switcher.
4. **T2.2 — forgetting the `purpose` filter.** An embedding model offered as your brain.
5. **T3.3 — "fixing" the changed denominator.** It is correct now; reverting it undoes Phase 1.

### Baseline record
<!-- T0.1-T0.2 record "before"; T4.4 records "after". -->

| Observation | Before | After |
|---|---|---|
| ContextPill denominator on a DER task | | |
| ContextPill denominator on a direct reply | | |
| Pill updates outside DER | | |
| Model switchable from the chat row | | |
| Brain and Tool independently bound from the row | | |
| `Enter` blocked while `voiceState === 'listening'` | | |

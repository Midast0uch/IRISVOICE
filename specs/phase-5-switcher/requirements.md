# Requirements: Phase 5 — Model Switcher + ContextPill

> **Execution position: FIFTH.** Blocked on Phase 1 (persistence, `loaded`), Phase 3 (`loaded` is
> truthful for local models), and Phase 4 (`purpose` filter, so encoders are not offered).
>
> Everything needed is in this spec.

## Decisions Locked

Resolved with the user 2026-07-28. Do **not** re-litigate.

1. **Keep ContextPill's design.** Token count, usage bar, phase code, brand glow, dark glass — all
   stay. This phase adds a switcher beside it and reorganises the button row; it does not restyle
   the pill.
2. **The Send button goes.** `Enter` already sends. The pill is redundant and its 32px slot is the
   space the switcher needs.
3. **The switcher lists what is actually usable** — API providers with a configured key, local
   models actually loaded. Chat purposes only.
4. **Brain and Tool stay independently bindable.** The switcher must not collapse mix-and-match into
   a single selection.
5. **No key or key fragment ever reaches the frontend.** Availability is a boolean.

## Introduction

The chat input row carries a Send pill that does nothing `Enter` does not already do
([`chat-view.tsx:3293-3310`](components/chat-view.tsx:3293); `Enter` handlers at
[`:1535`](components/chat-view.tsx:1535) and [`:3252`](components/chat-view.tsx:3252)), while the
model actually in use is not visible from the chat at all.

Two ContextPill defects ride along, because they share the same surface:

- The pill must show the **real** `max_tokens` from `resolve_context_window()`, not a hardcoded
  128k placeholder. Phase 1 makes that value truthful; this phase makes sure the pill consumes it.
- The pill currently updates only inside the DER loop, so a direct (non-DER) reply leaves the budget
  number stale from the first turn.

All the data the switcher needs already exists. `useInferenceState`
([`hooks/useInferenceState.ts`](hooks/useInferenceState.ts)) already fetches
`/api/inference/state`, merges `iris:provider_added` and `iris:role_bindings_updated`, and exposes
`sendRoleBinding(role, instanceId, modelOverride?)` ([`:112-121`](hooks/useInferenceState.ts:112)).
**No new backend endpoint and no new socket message are required.**

### Success criteria

- The user switches the active model from the chat input row without opening settings.
- The Send pill is gone and message sending is unchanged — including every guard the button carried.
- Brain and Tool can still be bound to different providers.
- The pill shows the model's real context window and updates on **every** response, DER or not.
- No key or fragment is rendered, transmitted, or logged.
- ContextPill's visual design is unchanged.

## Requirements

---

### REQ-1: Remove the redundant Send control

**User Story:** As a user I want the input row to carry only controls that do something, so the
space goes to the model switcher.

**Verified:** REAL — the Send pill at [`chat-view.tsx:3293-3310`](components/chat-view.tsx:3293)
calls `handleSendMessage`, which `Enter` already invokes at
[`:1535-1537`](components/chat-view.tsx:1535) (`if (e.key === "Enter" && !e.shiftKey)`) and again at
[`:3252-3254`](components/chat-view.tsx:3252). Removing the button removes no capability.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL remove the Send button from the chat input row.
- AC2: THE SYSTEM SHALL continue to send on `Enter` and insert a newline on `Shift+Enter`.
- AC3: THE SYSTEM SHALL preserve the button's disabled conditions — empty input, `isTyping`,
  `voiceState === 'listening'` — as guards **inside the send path**, so removing the button does not
  remove the guard it carried.
- AC4: THE SYSTEM SHALL keep every other control in the row functional and correctly spaced.

**Edge Cases:**
- A path that cannot reach `Enter` (touch / on-screen keyboard) → must be identified before removal;
  if one exists, AC1 is blocked and that is a finding.
- IME composition where `Enter` commits a candidate → existing behaviour, unchanged.
- Empty input + `Enter` → no-op, as today.

---

### REQ-2: A model switcher in the chat input row

**User Story:** As a user I want to switch models from where I am typing.

**Verified:** NEW UI over existing data — see Introduction. `useInferenceState` already has the
state and the writer.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL present a dropdown in the chat input row listing selectable models.
- AC2: THE SYSTEM SHALL include an API provider only WHERE it has a configured key.
- AC3: THE SYSTEM SHALL include a local model only WHERE it is currently `loaded`.
- AC4: THE SYSTEM SHALL include only providers whose `purpose` is `chat` — embedding and rerank
  instances SHALL NOT appear.
- AC5: WHEN the user selects a model THEN THE SYSTEM SHALL bind it via the existing
  `set_role_binding` path and reflect the change without a reload.
- AC6: THE SYSTEM SHALL show which model is currently active before the dropdown is opened.
- AC7: THE SYSTEM SHALL allow Brain (`reasoning`) and Tool (`tool_execution`) to be set
  independently.
- AC8: THE SYSTEM SHALL NOT display, transmit, or log any API key or fragment.
- AC9: THE SYSTEM SHALL remain usable with no provider configured, showing an actionable empty
  state; a still-loading state SHALL be distinct from an empty one.

**Edge Cases:**
- Provider configured but its key removed → disappears; if it was bound, AC6 shows the binding as
  unavailable rather than silently showing a working model.
- Local model unloaded while its entry is open → selection fails visibly; never silently binds
  elsewhere.
- Many providers → the list scrolls; it must not resize the input row.

---

### REQ-3: ContextPill keeps its design and gains no new responsibility

**User Story:** As a user I want the pill I like to stay as it is.

**Verified:** REAL — [`ContextPill.tsx`](components/chat/ContextPill.tsx) renders token count, usage
bar, and a 3-letter phase code, with live action text capped at 24 chars
([`:50`](components/chat/ContextPill.tsx:50)) because full words overflow the `max-w-[160px]` label.
Props are `usedTokens`, `maxTokens`, `phase`, `currentAction`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL keep `ContextPillProps` unchanged — the switcher SHALL be a **sibling**
  component, not a new prop.
- AC2: THE SYSTEM SHALL keep the visual design unchanged: dark glass, brand glow, monospace tabular
  count, usage colour thresholds, phase codes.
- AC3: THE SYSTEM SHALL keep the input row within its existing width at the smallest supported
  window size, with no horizontal overflow.

**Edge Cases:**
- Long model name in the switcher → truncated, following the pill's own `ACTION_CAP` precedent; full
  name in `title`.
- Narrow window → the switcher collapses to an icon **before** the pill loses information. The pill
  is the thing being protected.
- ⚠️ `ContextPill` currently renders inside a fixed `w-[32px] h-[32px]` container alongside
  `ConversationChips` ([`chat-view.tsx:3347-3368`](components/chat-view.tsx:3347)) while declaring
  `max-w-[200px]` itself — the child already exceeds its container. Removing the Send pill frees
  32px plus a gap; resolve this existing overflow rather than positioning the switcher against a
  container whose real width nothing states.

---

### REQ-4: The switcher reflects real state, including after a restart

**User Story:** As a user I want the switcher to show what is actually loaded and bound.

**Verified:** Phase 1 makes providers declarative with a `loaded` status; Phase 3 makes `loaded`
truthful for local models.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL derive availability from the provider registry, not from local UI state.
- AC2: THE SYSTEM SHALL update on `iris:provider_added` and `iris:role_bindings_updated`.
- AC3: WHEN a binding fails THEN THE SYSTEM SHALL surface the failure and leave the previous
  selection active — it SHALL NOT show the new selection as active.
- AC4: THE SYSTEM SHALL show the same active model as the settings panel; the two SHALL NOT disagree.
- AC5: AFTER a restart THE SYSTEM SHALL show persisted bindings and persisted providers.

**Edge Cases:**
- Backend restarts while the UI is open → state refetched; no stale loaded-state.
- Race between `provider_added` and a manual refetch → last snapshot wins, as the hook already does
  ([`:94-110`](hooks/useInferenceState.ts:94)).

---

### REQ-5: ContextPill shows the REAL context window and a compact phase code

**User Story:** As a user watching the chat widget I want the pill to reflect the *actual* model
context window and stay compact, so I can trust the number and it does not overflow.

**Verified:** Phase 1 REQ-2 makes `resolve_context_window()` authoritative. The pill's own docstring
already states the denominator is the real `max_tokens` via `iris:context_usage` and that the 128000
fallback is *"only the cold-start placeholder before the first event arrives"*
([`ContextPill.tsx:59-62`](components/chat/ContextPill.tsx:59)). The compact phase code
(`PHASE_CODES`, [`:38-45`](components/chat/ContextPill.tsx:38)) already exists.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL source `max_tokens` from `resolve_context_window()` via the
  `context:usage` event, never a hardcoded value.
- AC2: THE SYSTEM SHALL render a compact phase code in the visible label, keeping the full phase
  name in `title` only.
- AC3: THE SYSTEM SHALL cap live action text so a long string can never render as a full sentence in
  the pill.
- AC4: THE SYSTEM SHALL treat the cold-start placeholder as a placeholder — once a real event
  arrives it SHALL NOT revert to it.

**Edge Cases:**
- ⚠️ **The displayed denominator will change** once Phase 1 lands — a 16k-loaded Mistral shows 16k
  not 32k, and an unlisted provider stops showing 8.2k. Expected; do not "fix" it back.
- No event yet → placeholder, visibly distinguishable from a measured value.

---

### REQ-6: ContextPill is live on EVERY model response

**User Story:** As a user I want the pill live from the first reply and correct when I switch
threads, not only inside the DER loop.

**Verified:** REAL GAP — `context:usage` (`IRISStreamEvent.CONTEXT_USAGE`) is emitted per DER step
but **not** on the direct path in `process_text_message`, so a non-DER reply leaves the number stale.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL emit `context:usage` at the completion of **every** non-DER model response
  (the direct path in `process_text_message`), in addition to the existing per-step DER emit.
- AC2: THE SYSTEM SHALL use the same event shape and the same
  `max_tokens = resolve_context_window()` denominator on both paths.
- AC3: WHEN the user switches conversation threads THEN THE SYSTEM SHALL reflect that thread's usage,
  not the previous thread's.
- AC4: THE SYSTEM SHALL keep emission off the critical path — an emit failure SHALL NOT fail a reply.

**Edge Cases:**
- Streaming reply → emit at completion, not per chunk.
- Thread with no turns yet → zero used against a real denominator, not a placeholder.
- Voice turn → same emission, same shape.

---

### REQ-7: Switching is observable

**User Story:** As the maintainer I want model switches logged so "it switched to the wrong model"
is diagnosable from a log.

**Verified:** NEW.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log each switch with the role, previous instance id, new instance id, and
  outcome.
- AC2: THE SYSTEM SHALL NOT log any credential or fragment.
- AC3: THE SYSTEM SHALL keep logging off the critical path.

**Edge Cases:**
- High-frequency switching → logged per switch; volume is not a reason to log nothing.

---

## Non-Requirements (Out of Scope for Phase 5)

- **Restyling ContextPill.** Decision Locked #1.
- **Adding API providers from the switcher.** Configuration stays in settings; the switcher selects
  among what is configured.
- **Loading or unloading a local model from the switcher.** It lists loaded models; loading remains a
  settings action.
- **Changing the send path itself.** REQ-1 removes a button; `handleSendMessage` is untouched.
- **New backend endpoints or socket messages for switching.**
- **Per-conversation model memory.** Switching sets the current binding, not a per-thread override.
- **Provider persistence, routing mode, credential handling** → Phase 1.

## Open Questions

- **OQ-1:** Two dropdowns (Brain / Tool) or one with a role toggle. Two is clearer, one is smaller.
  **Measure the row's width budget after REQ-1's reflow before choosing** — do not guess.
- **OQ-2:** A provider whose key was removed: disabled-with-reason, or hidden. Disabled explains
  more; hidden is tidier.

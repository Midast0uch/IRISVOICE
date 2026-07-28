# Requirements: ContextPill Model Switcher + Provider Config Persistence

## Decisions Locked

Resolved with the user on 2026-07-28. Do **not** re-litigate.

1. **Keep ContextPill's design.** The user likes it. Token count, usage bar, phase code, brand
   glow, dark glass — all stay. This spec adds a switcher next to it and reorganises the button
   row; it does not restyle the pill.
2. **The Send button goes.** `Enter` already sends
   ([`chat-view.tsx:1535`](components/chat-view.tsx:1535) and
   [`:3252`](components/chat-view.tsx:3252)). The pill is redundant and its 32px slot is the space
   the switcher needs.
3. **The switcher lists what is actually usable** — API providers with a configured key, and local
   models that are actually loaded. Not everything that could theoretically be selected.
4. **Providers persist as a collection keyed by id.** The config's single flat `api_base_url` /
   `api_key` pair is replaced by a per-provider collection. This is what makes the frontend's
   multi-provider mix-and-match survive a restart.
5. **A provider's URL is never written without that provider's key.** They are one unit. Writing
   one without the other produces a configuration that authenticates to the wrong host.
6. **The flat config is migrated, not dropped.** An existing single-provider install must come up
   with that provider intact and bound.
7. **Routing mode is not touched.** `InferenceConfig.provider` (`api | lm_studio | ollama |
   iris_local`) stays exactly as it is. This spec changes *where credentials live*, not how
   requests are routed.
8. **`local-model-provider-parity` Wave 1 is a prerequisite** for the loaded-state half — the
   switcher needs a truthful `loaded` flag. The provider-persistence half (REQ-5..REQ-8) is
   independent and may land first.

## Introduction

Two problems that meet at the same surface.

**The UI problem.** Switching models means opening settings. The chat input row carries a Send pill
that does nothing `Enter` does not already do
([`chat-view.tsx:3293-3310`](components/chat-view.tsx:3293)), while the model in use is not visible
from the chat at all.

**The persistence problem — the more serious one.** The frontend lets a user configure multiple API
providers and bind Brain and Tool roles independently, but `InferenceConfig` stores **one**
`api_base_url` and **one** `api_key`
([`iris_config.py:192-193`](backend/iris_config.py:192)). There is nowhere to put a second
provider's credentials. Configure Cerebras after OpenAI and the OpenAI key is gone — the running
registry still holds both because it is in-memory, so the app appears to work until it restarts.

That flat pair also makes a genuinely dangerous state reachable: `api_base_url` and `api_key` are
separate fields with separate writers, so a partial write leaves **provider B's URL paired with
provider A's key** — sending one vendor's secret to another vendor's server. Requirement 6 exists
for that specifically.

Adding a model switcher on top of storage that cannot hold two providers would make the switcher
lie after every restart. Persistence comes first.

### Success criteria

- Two API providers with different keys are configured, bound to different roles, and **both
  survive a restart** with their own credentials intact.
- No configuration state exists in which a provider's `api_base_url` is paired with a different
  provider's `api_key`.
- An existing single-provider install upgrades with that provider intact and still bound — no
  re-entry of keys.
- The user switches the active model from the chat input row without opening settings.
- The Send pill is gone and message sending is unchanged.
- Routing mode behaves exactly as before.
- No key or key fragment is ever rendered, logged, or sent to the frontend.

## Requirements

---

### REQ-1: Remove the redundant Send control

**User Story:** As a user I want the input row to carry only controls that do something, so that
the space goes to the model switcher instead.

**Verified:** REAL — the Send pill is at
[`chat-view.tsx:3293-3310`](components/chat-view.tsx:3293), calling `handleSendMessage`. The same
function is already invoked by `Enter` at
[`:1535-1537`](components/chat-view.tsx:1535) (`if (e.key === "Enter" && !e.shiftKey)`) and again at
[`:3252-3254`](components/chat-view.tsx:3252). Removing the button removes no capability.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL remove the Send button from the chat input row.
- AC2: THE SYSTEM SHALL continue to send on `Enter` and to insert a newline on `Shift+Enter`,
  unchanged.
- AC3: THE SYSTEM SHALL preserve the existing disabled conditions — empty input, `isTyping`,
  `voiceState === 'listening'` — as guards inside the send path, so removing the button does not
  remove the guard it carried.
- AC4: THE SYSTEM SHALL keep every other control in the row (upload, conversation chips,
  ContextPill) functional and correctly spaced.

**Edge Cases:**
- Touch or on-screen-keyboard users with no convenient `Enter` → if any such path exists, it must
  be identified before removal; AC1 assumes `Enter` is universally reachable in this desktop app.
- IME composition where `Enter` commits a candidate → existing behaviour, unchanged by this spec.
- Empty input + `Enter` → no-op, as today.

---

### REQ-2: A model switcher in the chat input row

**User Story:** As a user I want to switch models from where I am typing, so that changing model
does not mean leaving the conversation.

**Verified:** NEW UI. The data is already there: `useInferenceState`
([`hooks/useInferenceState.ts`](hooks/useInferenceState.ts)) already fetches
`/api/inference/state`, already merges `iris:provider_added` and `iris:role_bindings_updated`
events, and already exposes `sendRoleBinding(role, instanceId, modelOverride?)`
([`:112-121`](hooks/useInferenceState.ts:112)). No new backend endpoint and no new socket message
are required.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL present a dropdown in the chat input row listing selectable models.
- AC2: THE SYSTEM SHALL include an API provider only WHERE it has a configured key.
- AC3: THE SYSTEM SHALL include a local model only WHERE it is currently loaded.
- AC4: WHEN the user selects a model THEN THE SYSTEM SHALL bind it via the existing
  `set_role_binding` path and reflect the change without a reload.
- AC5: THE SYSTEM SHALL show which model is currently active before the dropdown is opened.
- AC6: THE SYSTEM SHALL allow Brain (`reasoning`) and Tool (`tool_execution`) to be set
  independently, preserving the mix-and-match model rather than collapsing both to one selection.
- AC7: THE SYSTEM SHALL NOT display, transmit, or log any API key or key fragment. Availability is
  conveyed by a boolean only.
- AC8: THE SYSTEM SHALL remain usable when no provider is configured, showing an actionable empty
  state rather than an empty dropdown.

**Edge Cases:**
- A provider configured but its key removed → disappears from the list; if it was bound, AC5 shows
  the binding as unavailable rather than silently showing a working model.
- A local model unloaded while its dropdown entry is open → the selection fails with a visible
  error; it must not silently bind to something else.
- Many providers → the list scrolls; it must not resize the input row.
- Provider state still loading → loading state, not an empty list, which would read as "none
  configured".

---

### REQ-3: ContextPill keeps its design and gains no new responsibility

**User Story:** As a user I want the pill I like to stay as it is, so that adding a switcher does
not cost me the thing I asked to keep.

**Verified:** REAL — [`ContextPill.tsx`](components/chat/ContextPill.tsx) renders token count,
usage bar, and a 3-letter phase code, with the live action text capped at 24 chars
([`:50`](components/chat/ContextPill.tsx:50)) specifically because full words overflow the
`max-w-[160px]` label. Its props are `usedTokens`, `maxTokens`, `phase`, `currentAction`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL keep `ContextPillProps` unchanged — the switcher SHALL be a sibling
  component, not a new prop.
- AC2: THE SYSTEM SHALL keep the pill's visual design unchanged: dark glass, brand glow, monospace
  tabular token count, usage colour thresholds, phase codes.
- AC3: THE SYSTEM SHALL keep the denominator sourced from the backend's real `max_tokens` via
  `iris:context_usage`, never a hardcoded value.
- AC4: THE SYSTEM SHALL keep the input row within its existing width at the smallest supported
  window size, with no horizontal overflow.

**Edge Cases:**
- A long model name in the switcher → truncated, following the pill's own `ACTION_CAP` precedent;
  full name in `title`.
- Narrow window → the switcher collapses to an icon before the pill loses information; the pill is
  the thing being protected.

---

### REQ-4: The switcher reflects real state, including after a restart

**User Story:** As a user I want the switcher to show what is actually loaded and bound, so that
picking a model from it does not fail.

**Verified:** BLOCKED on `local-model-provider-parity` Wave 1 for `loaded`. Today a local provider
does not exist until a load succeeds
([`iris_gateway.py:7896`](backend/iris_gateway.py:7896)), so "configured but not loaded" is not
representable.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL derive availability from the provider registry, not from local UI state.
- AC2: THE SYSTEM SHALL update the list when providers are added or bindings change, using the
  existing `iris:provider_added` and `iris:role_bindings_updated` events.
- AC3: WHEN a binding fails THEN THE SYSTEM SHALL surface the failure and leave the previous
  selection in place — it SHALL NOT show the new selection as active.
- AC4: THE SYSTEM SHALL show the same active model as the settings panel; the two views SHALL NOT
  disagree.
- AC5: AFTER a restart THE SYSTEM SHALL show the persisted bindings and persisted providers
  (REQ-5), not an empty or default list.

**Edge Cases:**
- Backend restarts while the UI is open → state refetched; the switcher must not show stale
  loaded-state.
- Binding to a provider that has since become unavailable → AC3 failure path.
- Race between `provider_added` and a manual refetch → last snapshot wins, as the hook already
  does ([`:94-110`](hooks/useInferenceState.ts:94)).

---

### REQ-5: Providers persist as a collection keyed by id

**User Story:** As a user I want every provider I configure to be remembered with its own
credentials, so that configuring a second provider does not erase the first.

**Verified:** REAL GAP, **narrower than it first appears** — the gap is the *config file*, not the
credential store.

- **Already works:** the keyring is **already keyed by provider id**.
  `ProviderInstance.to_dict` falls back to `get_secret(self.id)`
  ([`provider.py:49-53`](backend/agent/inference/provider.py:49)), with the comment *"legacy config
  keys are persisted there keyed by provider id at router init."* `has_key` is **already emitted**
  ([`:65`](backend/agent/inference/provider.py:65)). `ProviderInstance.api_key` is a per-instance
  field ([`:42`](backend/agent/inference/provider.py:42)), so the **registry already holds several
  providers' keys simultaneously.**
- **REAL GAP:** `InferenceConfig` holds **one** `api_base_url` and **one** `api_key`
  ([`iris_config.py:192-193`](backend/iris_config.py:192)). There is nowhere to persist a second
  API provider's endpoint. `role_bindings` is *already* a persisted list
  ([`:230`](backend/iris_config.py:230)), so bindings can reference several providers the config
  cannot store.

That asymmetry is the whole bug: the registry and the keyring both handle multiple providers
correctly, and the config file is the single-slot bottleneck between them. It is also why the
failure only appears at restart — everything upstream of persistence already works.

**Cross-spec (C1):** the `providers` collection is introduced by `local-model-provider-parity` T1.4
(which lands first) and **extended** here with API entries. This spec migrates
`api_base_url`/`api_key` **only**; the flat `local_model_*` fields are migrated by that spec.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL persist providers as a collection keyed by provider id, each entry holding
  that provider's own endpoint, credential reference, label, kind, and model.
- AC2: THE SYSTEM SHALL support **at least two** API providers with **different** keys persisted
  simultaneously.
- AC3: THE SYSTEM SHALL make a persisted `role_bindings` entry resolvable to a persisted provider
  entry — a binding referencing an absent provider SHALL be reported, not silently dropped.
- AC4: THE SYSTEM SHALL keep credentials in the OS keyring **keyed by provider id** — the scheme
  `get_secret(self.id)` already uses ([`provider.py:53`](backend/agent/inference/provider.py:53)) —
  storing only a reference in the config file. No key SHALL be written to the config in clear.
  This is an existing mechanism to be wired to, **not** a new store to build.
- AC5: THE SYSTEM SHALL keep the persisted collection and the in-memory registry consistent — a
  provider present in one and absent from the other is a defect, not a state.
- AC6: THE SYSTEM SHALL persist a provider on configuration, not on first successful use.

**Edge Cases:**
- Two providers sharing an endpoint with different keys → distinct entries; the id is the key, not
  the URL.
- A provider deleted while bound → AC3 reports the dangling binding.
- Keyring unavailable → the provider is not persisted and the user is told, rather than the key
  silently landing in the config file.

---

### REQ-6: A provider's URL is never written without that provider's key

**User Story:** As a user I want a provider's endpoint and credential written together, so that my
key for one vendor is never sent to another vendor's server.

**Verified:** REAL RISK — `api_base_url` and `api_key` are independent fields
([`iris_config.py:192-193`](backend/iris_config.py:192)) read independently by `from_dict`
([`:241-242`](backend/iris_config.py:241)) and written by the `set_model_selection` payload, whose
`api_key` and `api_base_url` are **both optional**
([`useInferenceState.ts:131-132`](hooks/useInferenceState.ts:131)). Sending one without the other
is therefore expressible today, and it produces a configuration in which one provider's URL is
paired with a different provider's key.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL treat a provider's endpoint and credential as a single unit — both are
  written together or neither is.
- AC2: IF a write would set an endpoint without its matching credential, or a credential without
  its matching endpoint, THEN THE SYSTEM SHALL reject the write and report it.
- AC3: THE SYSTEM SHALL make a partially-written provider entry unreachable — an interrupted write
  SHALL leave the previous entry intact, not a hybrid.
- AC4: THE SYSTEM SHALL NOT allow a credential stored under one provider id to be used for a
  request to a different provider id's endpoint.
- AC5: THE SYSTEM SHALL log the rejection in AC2 without including the credential or any fragment
  of it.

**Edge Cases:**
- Editing only the endpoint of an existing provider → permitted; the existing credential belongs to
  that same id, so the unit is preserved. AC1 forbids *mismatched* pairs, not all partial edits.
- Rotating only the key of an existing provider → same reasoning, permitted.
- Crash mid-write → AC3; the previous entry survives.
- A user pasting provider A's key into provider B's form → out of scope. The system cannot know a
  key's vendor; AC4 only guarantees the stored pairing is honoured.

---

### REQ-7: The flat config migrates

**User Story:** As an existing user I want my configured provider to still be there after the
upgrade, so that I do not re-enter keys.

**Verified:** REAL — every existing install has flat `api_base_url` / `api_key` /
`lm_studio_url` / `ollama_url` / `local_model_*` fields
([`iris_config.py:191-211`](backend/iris_config.py:191)) and a `role_bindings` list that may
already reference ids the new collection must contain
([`:230`](backend/iris_config.py:230)).

**Acceptance Criteria:**
- AC1: WHEN a config with flat provider fields is loaded THEN THE SYSTEM SHALL migrate it into the
  keyed collection, preserving endpoint, key, and model.
- AC2: THE SYSTEM SHALL migrate existing `role_bindings` so they resolve to migrated provider
  entries — a binding that resolved before the upgrade SHALL resolve after it.
- AC3: THE SYSTEM SHALL leave the flat `local_model_*` fields to `local-model-provider-parity`
  T1.4, which migrates them into local entries of the **same** `providers` collection. This spec
  SHALL NOT migrate them (cross-spec C1 — a field migrated by two once-only migrations is the
  failure both all-or-nothing rules exist to prevent), and SHALL verify that local entries produced
  there resolve alongside the API entries produced here.
- AC4: THE SYSTEM SHALL run migration exactly once and SHALL be idempotent if run again.
- AC5: IF migration fails THEN THE SYSTEM SHALL leave the original config untouched and report the
  failure — it SHALL NOT start with a partially migrated config.
- AC6: THE SYSTEM SHALL preserve the migrated key in the keyring (REQ-5 AC4) without requiring the
  user to re-enter it.

**Edge Cases:**
- Flat fields empty (fresh install) → empty collection, no migration, no error.
- Flat fields present **and** a keyed collection already present → the collection wins; flat fields
  are ignored, not merged. Merging two sources of truth for the same provider is how a URL ends up
  with the wrong key.
- A `role_bindings` entry referencing the literal `"local"` → migrated per
  `local-model-provider-parity` REQ-2 AC4, in the same change, not left dangling.
- Config file read-only → AC5 reports; the app runs on the unmigrated config rather than losing it.

---

### REQ-8: Routing mode is unchanged

**User Story:** As a user I want request routing to behave exactly as it does today, so that a
storage change does not alter which backend serves my requests.

**Verified:** `InferenceConfig.provider` (`api | lm_studio | ollama | iris_local`,
[`iris_config.py:187`](backend/iris_config.py:187)) selects routing mode and is read at
[`:238`](backend/iris_config.py:238) with an `active_provider` alias fallback. Decision Locked #7
puts it out of scope.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL leave the `provider` routing-mode field and its semantics unchanged.
- AC2: THE SYSTEM SHALL preserve the `active_provider` alias fallback in `from_dict`.
- AC3: THE SYSTEM SHALL NOT change which backend serves a request for any configuration that works
  today.
- AC4: THE SYSTEM SHALL keep `lm_studio_url` and `ollama_url` behaviour unchanged for installs that
  use them.

**Edge Cases:**
- A config setting `provider` to a value with no matching entry in the new collection → existing
  behaviour preserved; this spec does not add a validation that would newly reject a working config.

---

### REQ-9: Switching and persistence are observable

**User Story:** As the maintainer I want model switches and provider writes logged, so that "it
forgot my provider" is diagnosable from a log rather than a repro.

**Verified:** NEW.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log each switch with the role, previous instance id, new instance id, and
  outcome.
- AC2: THE SYSTEM SHALL log each provider write with the provider id and outcome, and SHALL NOT
  log the credential or any fragment of it.
- AC3: THE SYSTEM SHALL log migration with the number of providers migrated and the outcome
  (REQ-7).
- AC4: THE SYSTEM SHALL log a rejected endpoint/credential write with the reason (REQ-6 AC5).
- AC5: THE SYSTEM SHALL keep logging off the critical path — a logging failure SHALL NOT fail a
  switch or a write.

**Edge Cases:**
- High-frequency switching → logged per switch; volume is not a reason to log nothing.
- Credential in an error message from a downstream library → redacted before logging.

---

## Non-Requirements (Out of Scope)

- **Restyling ContextPill.** Decision Locked #1.
- **Changing routing mode.** REQ-8. Decision Locked #7.
- **Adding API providers from the switcher.** Configuration stays in settings; the switcher selects
  among what is already configured.
- **Loading or unloading a local model from the switcher.** It lists loaded models (REQ-2 AC3);
  loading remains a settings action.
- **Changing the send path itself.** REQ-1 removes a button; `handleSendMessage` is untouched.
- **New backend endpoints or socket messages for switching.** `useInferenceState` already has
  everything (REQ-2 Verified).
- **Per-conversation model memory.** Switching sets the current binding, not a per-thread override.
- **Changing the keyring backend.**

## Open Questions

- **OQ-1:** Whether Brain and Tool get two dropdowns or one dropdown with a role toggle. Two is
  clearer; one is smaller. The row's width budget after removing Send (32px + gap) decides it —
  measure before choosing.
- **OQ-2:** Whether the switcher shows a provider whose key was removed as disabled-with-reason or
  hides it. Disabled explains more; hidden is tidier.
- **OQ-3:** The exact config schema version marker for REQ-7 AC4's once-only migration.

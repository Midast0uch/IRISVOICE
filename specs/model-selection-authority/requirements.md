# Requirements: Model Selection Authority

## Decisions Locked
- **Dropdowns are the authority.** An explicit frontend selection (Provider Setup APPLY, Brain/Tool dropdowns, ModelSwitcher, wheel-view provider change) always wins. `iris_config.json` is a cold-start seed, never an override.
- **Config never clobbers live state.** Restart replay and widget remounts must preserve the last explicit choice. A remount sends no selection traffic (frontend only sends on gesture — verified `ModelInferenceSection.tsx:176-246`, `useInferenceState.ts:305-341`).
- **Local GGUF models are first-class test providers.** Real end-to-end proof runs against a locally loaded model (free, offline) — never synthetic mocks, never paid trial keys.
- **Selection is global (single user, one choice everywhere).** The role table stays process-wide; a switch in one window applies to all. Per-window selection is out of scope.
- **Swarm interplay is a clean seam, not this spec's logic.** A switch arriving while swarm is active is deferred as a timestamped intent (persisted + visible), never silently dropped; applying it on swarm end belongs to the future swarm spec.
- **Unload mid-session falls back LOUDLY.** If a bound local model unloads, turns fall back to the last API provider with a visible flag AND a user-facing error message (silent fallback is a revert by another name).
- **Two symptoms, one architecture.** The provider-switch revert AND loaded-local-models-missing-from-dropdowns are both selection-authority failures and ship together.

## Introduction
Model selection (which provider/model answers) silently reverts or disagrees across surfaces: a Cerebras pick served Cohere (2026-09-03, trial key burned), cross-provider model wear ("cohere · gemma-4-31b"), and loaded local models missing from dropdowns. For a widget app where components mount/unmount constantly, selection must be unambiguous and durable. This spec makes the authority explicit, timestamped, and permanently guarded.

### Success criteria
- A provider switch via any dropdown is served on the very next turn, survives backend restart AND frontend remount, with zero silent reverts across 20 consecutive scripted switch/restart/remount cycles.
- A locally loaded model appears in every model dropdown within one snapshot tick of `local_model_status loaded=true`.
- Every selection decision emits one authority-chain log line naming what won and why.
- Zero regressions in the existing provider behavioral suite.

## Requirements

### REQ-1: Explicit provider switch takes effect immediately
**User Story:** As the user I want the provider I pick to answer my next message so that I control cost, quality, and availability.

**Verified:** `backend/iris_gateway.py:1762-1799` (switch detection + rebind), `components/ModelInferenceSection.tsx:209-246` (APPLY sender), `backend/agent/agent_kernel.py:14717-14737` (preserve vs bind branches)

**Acceptance Criteria:**
- AC1: WHEN a card APPLY names a provider different from the current reasoning binding THEN THE SYSTEM SHALL rebind reasoning AND tool_execution to the named provider with the card's models before acknowledging the APPLY.
- AC2: WHEN `set_model_selection` arrives with `preserve_bindings` unset/false THEN THE SYSTEM SHALL bind roles exactly to the payload and persist them with overrides intact.
- AC3: WHEN a switch is applied THEN THE SYSTEM SHALL broadcast the new bindings so every surface (switcher, dashboard, router) shows them within one snapshot tick.

**Edge Cases:**
- Named provider not in registry → reject with `role_binding_error`, keep previous bindings (never half-bind).
- Empty model string with a named provider → resolve the provider's catalog default, never inherit the previous provider's model (the "cohere · gemma" wear class).
- Concurrent APPLYs → last writer wins, each fully applied (no mixed provider/model pairs).

### REQ-2: Echo APPLY and remounts preserve Brain/Tool splits
**User Story:** As the user I want unrelated APPLYs and widget remounts to leave my split setup alone so that my configuration doesn't decay while I use the app.

**Verified:** `backend/iris_gateway.py:1800-1814` (preserve branch), `hooks/useInferenceState.ts:270-303` (remount re-fetch, version-guarded, never re-sends)

**Acceptance Criteria:**
- AC1: WHEN a card APPLY names the SAME provider the reasoning binding already serves THEN THE SYSTEM SHALL change no binding (Brain/Tool splits across providers survive).
- AC2: WHEN a frontend component remounts THEN THE SYSTEM SHALL send zero selection messages (re-fetch state only).
- AC3: WHEN a new conversation is constructed THEN THE SYSTEM SHALL inherit the live role table, never replay config over it.

**Edge Cases:**
- Remount during in-flight APPLY → version guards discard stale snapshot (frontend, already implemented — contract-locked).
- New kernel mid-turn → inherits, never seeds.
- Switch arrives while swarm active → recorded as deferred timestamped intent (visible in snapshot); applied by the swarm lifecycle, never dropped.
- Two backends sharing one config file → last-writer-wins by timestamp; pid-stamped logs disambiguate which wrote.
- Downgrade (old backend rewrites config) → new timestamp fields may drop; system falls back to legacy heuristic + warning, never guesses blind.

### REQ-3: Boot restore applies the newest record and binds at true cold start
**User Story:** As the user I want my last choice waiting after a restart so that rebooting doesn't silently change providers.

**Verified:** `backend/main.py:604-642` (restore with preserve heuristic), `backend/agent/inference/router.py:336-382` (seed-only-if-unbound), `backend/iris_config.py:277-340` (schema: flat fields + role_bindings, no timestamps — GAP)

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL stamp every explicit selection with a timestamp and persist provider, bindings, AND model overrides together.
- AC2: WHEN the flat provider record and the role_bindings record disagree at boot THEN THE SYSTEM SHALL apply the newer record (explicit choice beats stale file, either direction).
- AC3: WHEN the role table is empty at boot THEN THE SYSTEM SHALL bind the winning record (register-only leaves a dead router).
- AC4: WHEN the role table is already bound THEN THE SYSTEM SHALL NOT replay config over it.

**Edge Cases:**
- No timestamp on either record (pre-migration config) → current heuristic preserved (flat treated as stale copy) + warning logged.
- Persisted binding points at a provider absent from the registry (e.g. local model unloaded) → discard that binding, fall back per existing rules, log loudly (never a dead binding).
- Corrupt/partial config → boot unbound (wait-for-user), never guess.

### REQ-4: Loaded local models appear in every model dropdown
**User Story:** As the user I want a model I just loaded to be selectable immediately so that local inference is actually usable.

**Verified:** NEW (discovery pending — T0 establishes whether the break is scan, registry, snapshot, or frontend filter)

**Acceptance Criteria:**
- AC1: WHEN `local_model_status loaded=true` fires THEN THE SYSTEM SHALL include the loaded instance in the next inference snapshot (`providers` + addressable `role_bindings` values).
- AC2: WHEN the snapshot contains a loaded local instance THEN THE SYSTEM SHALL render it in the Brain dropdown, Tool dropdown, and ModelSwitcher option lists within one snapshot tick.
- AC3: WHEN a loaded local model is selected THEN THE SYSTEM SHALL route turns to it with zero API calls (assertable: no `api.*` POST during the turn).

**Edge Cases:**
- Model unloads → instance disappears from options; in-flight binding falls back to the last API provider WITH a visible flag AND a user-facing error message (silent fallback is forbidden).
- A binding held on an unloaded model shows pending status (never silently rebound elsewhere).
- Load fails → error status, dropdowns unchanged.
- Provider keys persist per provider (keyring) — switching back never requires re-entry; covered in e2e (T8).

### REQ-5: Authority-chain observability
**User Story:** As the debugger I want one log line per selection decision so that the next revert is explainable in seconds, not hours.

**Verified:** NEW (partial precedent: `iris_gateway.py:1791-1826` switch/preserve logs)

**Acceptance Criteria:**
- AC1: WHEN any apply/restore/seed decision completes THEN THE SYSTEM SHALL log one line naming source (card/set_role_binding/restore/seed), winner, previous binding, and reason.
- AC2: THE SYSTEM SHALL include the selection timestamp in the persisted record and the snapshot.

**Edge Cases:**
- Logging failure → swallowed (observability never breaks routing).

### REQ-6: No cross-provider model wear
**User Story:** As the user I want the model shown to always belong to the provider shown so that I never burn the wrong key on the wrong model.

**Verified:** `components/ModelInferenceSection.tsx:213-221` (frontend guard), `backend/iris_gateway.py:1702-1713` (catalog-default fallback)

**Acceptance Criteria:**
- AC1: IF a model name would be served under a different provider than it was chosen for THEN THE SYSTEM SHALL substitute that provider's catalog default instead.
- AC2: THE SYSTEM SHALL reject unknown provider/model pairs at bind time with `role_binding_error`, keeping previous bindings.

**Edge Cases:**
- Catalog unavailable → keep previous bindings, error surfaced (never blank-model bind).

## Non-Requirements (Out of Scope)
- New providers, billing/quota management, trial-key UX.
- Frontend visual redesign of the Models card (behavioral wiring only).
- Changing the 3-retry transport policy (separate concern).
- Whisper/STT, TTS, wake-word work (separate tracks, all green).

## Open Questions
- None blocking. Trial-budget surfacing ("you have N calls left") is a future feature, not this spec.

# Tasks: ContextPill Model Switcher + Provider Config Persistence

> Each task links to a requirement. Waves are dependency-ordered.
>
> **Cross-spec ordering (C1):** `local-model-provider-parity` **T1.4 creates the `providers`
> collection**; this spec extends it with API entries. T1.1 should follow T1.4. If this spec starts
> first, T1.1 must create the dict with exactly the name, key space and entry shape that spec
> specifies — the one thing that must not happen is two collections.
>
> **Wave 3 (the switcher) needs `local-model-provider-parity` Wave 1** for a truthful `loaded`
> flag. Waves 1–2 otherwise run independently of it.

---

## Wave 0 — Baseline (no behaviour change)

- [ ] **T0.1** Capture the current-state evidence: configure provider A, configure provider B,
  restart, record that A's key is gone.
  RIPPLE: ⚠️ record this **before** touching anything. It is the acceptance evidence for the whole
  spec, and it is the observation that is impossible to reconstruct afterwards.

- [ ] **T0.2** (REQ-8) Record routing-mode behaviour for all four `provider` values (`api`,
  `lm_studio`, `ollama`, `iris_local`): which backend serves a request in each.
  RIPPLE: this is the "unchanged" that REQ-8 AC3 asserts against. Without a recorded before, "no
  change" is an opinion.

- [ ] **T0.3** (REQ-1) Confirm no send path depends on the button: `Enter` at
  [`chat-view.tsx:1535`](components/chat-view.tsx:1535) and
  [`:3252`](components/chat-view.tsx:3252), plus any touch/IME path.
  RIPPLE: REQ-1's edge case. If a path exists that cannot reach `Enter`, removal is blocked and
  that is a finding, not something to work around.

- [ ] **T0.4** Green-suite baseline for backend + frontend.

---

## Wave 1 — Provider collection and atomic credential pairing (REQ-5, REQ-6)

- [ ] **T1.1** (REQ-5 AC1) Add the API `PersistedProvider` entry shape and `config_version` to
  `InferenceConfig`.
  RIPPLE: ⚠️ **Cross-spec (C1).** The `providers: dict[str, ...]` collection itself is created by
  `local-model-provider-parity` T1.4, which lands first. **Extend that dict — do not declare a
  second collection.** If that spec has not landed, create the dict with the same name, key space
  and shape it specifies.
  `endpoint` and `cred_ref` are fields of **one record** — that is what makes REQ-6 structural
  rather than a validation rule (D-2). Do **not** add a standalone `api_base_url` to the new shape;
  a writer that can touch it alone reintroduces the mismatched pair.
  `role_bindings` is untouched — it was already a list ([`iris_config.py:230`](backend/iris_config.py:230)).

- [ ] **T1.2** (REQ-5 AC4) Wire `cred_ref` to the **existing** per-id keyring.
  RIPPLE: ⚠️ **Smaller than it looks — do not build a new credential store.** `get_secret(self.id)`
  already resolves credentials keyed by provider id
  ([`provider.py:49-53`](backend/agent/inference/provider.py:49)), and `has_key` is already emitted
  ([`:65`](backend/agent/inference/provider.py:65)). The registry already holds several providers'
  keys at once via the per-instance `api_key` field ([`:42`](backend/agent/inference/provider.py:42)).
  **Only persistence is single-slot.** Replacing the working keyring path would be re-implementing
  the half that already works and risking the half that already works.
  Project rule stands: credentials never land in a config file. `test_no_key_in_config_file` asserts
  on the **file bytes**, not on the object — a `__repr__` that hides a field is not the same as a
  file that does not contain it.

- [ ] **T1.3** (REQ-6 AC1/AC2/AC3) Implement the atomic provider write: endpoint + credential
  written together, mismatched pairs rejected, crash leaves the previous entry intact.
  **Keyring first, then config** (D-3).
  RIPPLE: ⚠️ ordering is load-bearing. Config-then-keyring leaves a `cred_ref` pointing at nothing —
  a provider that looks configured, gets offered in the switcher, and fails at request time. The
  reverse leaves an inert unreferenced keyring entry.
  Permit endpoint-only and key-only edits of an **existing** provider (REQ-6 edge case) — the rule
  forbids *mismatched* pairs, not all partial edits. Over-applying it blocks legitimate key rotation.

- [ ] **T1.4** (REQ-6 AC4) Enforce that a credential stored under one id is never used for another
  id's endpoint.
  RIPPLE: this is the actual harm the spec exists to prevent — one vendor's secret sent to another
  vendor's server.

- [ ] **T1.5** (REQ-6 AC5, REQ-9 AC2/AC4) Log provider writes and rejections **without** the
  credential or any fragment.
  RIPPLE: also redact credentials appearing in downstream library error strings (REQ-9 edge case).

- [ ] **T1.6** (REQ-5 AC5, REQ-4 AC5) Hydrate the provider registry from the persisted collection at
  startup.
  RIPPLE: REQ-5 AC5 — a provider in the config and absent from the registry (or vice versa) is a
  defect, not a state. This is also what makes the switcher truthful after a restart.

- [ ] **T1.7** Tests:
  - `backend/tests/unit/test_provider_collection.py` — two providers, different keys (REQ-5 AC2).
  - `backend/tests/unit/test_endpoint_cred_atomic.py` — all **three** cases: url-without-key
    rejected, key-without-url rejected, endpoint-only edit of an existing provider permitted.
  - `backend/tests/unit/test_no_cross_provider_credential.py` — REQ-6 AC4.
  - `backend/tests/unit/test_no_key_in_config_file.py` — asserts on file bytes.
  - `backend/tests/contract/test_config_schema.py` — CT-P6.
  - `backend/tests/behavioral/test_second_provider_does_not_erase_first.py` — **no restart**;
    isolates the storage bug from the reload path. Today the in-memory registry masks it for the
    entire session anyone would test in.

---

## Wave 2 — Migration and routing-mode freeze (REQ-7, REQ-8)

- [ ] **T2.1** (REQ-7 AC1/AC4/AC5) Implement the migrator: flat → collection, gated on
  `config_version`, idempotent, all-or-nothing.
  RIPPLE: ⚠️ gate on `config_version`, **not** on "flat fields are present" — the latter re-runs
  forever on any config that legitimately retains them. On failure leave the original untouched
  (AC5); a partially migrated config has two sources of truth for one provider, which is how a URL
  acquires the wrong key.

- [ ] **T2.2** (REQ-7 AC2) Migrate `role_bindings` so every binding that resolved before the upgrade
  resolves after it.
  RIPPLE: a binding referencing the literal `"local"` migrates per `local-model-provider-parity`
  REQ-2 AC4 — **in the same change**, not left dangling. A dangling binding looks configured and
  serves nothing.

- [ ] **T2.3** (REQ-7 AC3) **Verify** — do not perform — the local-entry migration.
  `local-model-provider-parity` T1.4 owns migrating the flat `local_model_*` fields
  ([`iris_config.py:201-211`](backend/iris_config.py:201)) into local entries of the same
  `providers` dict. Assert here that local and API entries coexist in one collection and both
  resolve from `role_bindings`.
  RIPPLE: ⚠️ **Cross-spec (C1) — migrating them here too would double-migrate them.** Two
  "once-only" migrations over one source field is precisely the partial/conflicting state both
  specs' all-or-nothing rules exist to prevent. The id scheme is that spec's REQ-2 AC1
  (`local:<model-stem>`); two specs inventing two schemes for one model is a dead binding by
  construction.

- [ ] **T2.4** (REQ-7 AC6) Move the migrated key into the keyring without user re-entry.

- [ ] **T2.5** (REQ-7 edge case) Flat fields **and** collection both present → collection wins, flat
  ignored, **never merged**.
  RIPPLE: merging is the direct route to a mismatched endpoint/credential pair (D-4).

- [ ] **T2.6** (REQ-8) Verify routing mode is untouched: `provider` field, its vocabulary, the
  `active_provider` alias ([`iris_config.py:238`](backend/iris_config.py:238)), and
  `lm_studio_url` / `ollama_url` behaviour.
  RIPPLE: ⚠️ **Decision Locked #7 — do not "clean up" the routing-mode field while restructuring
  the config around it.** It is the most natural thing to tidy in this diff and explicitly out of
  scope. CT-P5 pins it.

- [ ] **T2.7** (REQ-9 AC3) Log migration: providers migrated, outcome.

- [ ] **T2.8** Tests:
  - `backend/tests/unit/test_migration.py` — REQ-7 AC1/AC2/AC4/AC5.
  - `backend/tests/unit/test_migration_collection_wins.py` — REQ-7 edge case.
  - `backend/tests/contract/test_routing_mode_frozen.py` — CT-P5.
  - `backend/tests/behavioral/test_upgrade_preserves_existing_provider.py` — from a real
    pre-upgrade config (REQ-7 AC6).
  - `backend/tests/behavioral/test_routing_mode_unchanged.py` — parametrized over **all four**
    `provider` values against T0.2's record. Dropping one is a test modification.
  - `backend/tests/behavioral/test_two_providers_survive_restart.py` — the headline assertion
    (REQ-5 AC2, REQ-4 AC5). **Fails today.**

---

## Wave 3 — Input row and switcher (REQ-1, REQ-2, REQ-3, REQ-4)

> Needs `local-model-provider-parity` Wave 1 for `loaded`.

- [ ] **T3.1** (REQ-1) Remove the Send pill
  ([`chat-view.tsx:3293-3310`](components/chat-view.tsx:3293)) and reflow the row.
  RIPPLE: ⚠️ the button carried
  `disabled={!inputText.trim() || isTyping || voiceState === 'listening'}`
  ([`:3296`](components/chat-view.tsx:3296)). Those guards must move **into** the send path (REQ-1
  AC3) or they are deleted along with the button — and `Enter` would then send while listening or
  mid-response. This is the one silent regression in the wave.
  Also resolve the existing overflow at [`:3347-3368`](components/chat-view.tsx:3347): `ContextPill`
  (`max-w-[200px]`) renders inside a fixed `w-[32px] h-[32px]` container. Fix it here rather than
  positioning the switcher against a container whose real width nothing states (D-5).

- [ ] **T3.2** (REQ-2, REQ-4) Build `ModelSwitcher` as a **sibling** of `ContextPill`, reading
  `useInferenceState` and writing through the existing `sendRoleBinding`.
  RIPPLE: no new endpoint, no new socket message — the hook already fetches
  `/api/inference/state`, merges `iris:provider_added` / `iris:role_bindings_updated`, and exposes
  the writer ([`useInferenceState.ts:47-121`](hooks/useInferenceState.ts:47)). A second path to the
  same state is how the switcher and the settings panel end up disagreeing (REQ-4 AC4).
  `ContextPillProps` is **not** extended (REQ-3 AC1, CT-P2).

- [ ] **T3.3** (REQ-2 AC2/AC3) Filter the list: API providers with `has_key`, local models with
  `loaded`. Chat purposes only — embedding and rerank instances are not bindable.
  RIPPLE: `purpose` comes from `local-model-provider-parity` REQ-2 AC3; `lfm25-encoder-integration`
  registers `embedding`/`rerank` instances that must **not** appear here (that spec's REQ-6 AC3).

- [ ] **T3.4** (REQ-2 AC6) Independent Brain and Tool selection.
  RIPPLE: OQ-1 (two dropdowns vs one with a role toggle) — decide from the row's width budget after
  T3.1's reflow, measured, not guessed.

- [ ] **T3.5** (REQ-2 AC5, REQ-4 AC3) Show the active model; a failed bind surfaces the error and
  leaves the previous selection active.
  RIPPLE: never show the new selection as active before the bind succeeds — that is the switcher
  telling the user something that is not true.

- [ ] **T3.6** (REQ-2 AC7, REQ-2 AC8) `has_key` boolean only — no key, prefix, length, or masked
  form crosses the boundary. Actionable empty state; loading state distinct from empty.
  RIPPLE: `ModelInferenceSection.tsx:33` already types `has_key?: boolean` — follow it. An empty
  list rendered during load reads as "nothing configured" and sends users to settings for no reason.

- [ ] **T3.7** (REQ-9 AC1) Log each switch: role, previous id, new id, outcome.

- [ ] **T3.8** Tests:
  - `__tests__/InputRow.test.tsx` — Send absent; `Enter` sends; `Shift+Enter` newlines; **the
    removed disabled conditions still block a send** (REQ-1 AC3).
  - `__tests__/ModelSwitcher.test.tsx` — REQ-2 AC2/AC3/AC8, REQ-4 AC3.
  - `backend/tests/contract/test_inference_state_payload.py` — CT-P1 (additive fields; **no**
    credential anywhere in the payload).
  - `__tests__/ContextPill.test.tsx` — CT-P2, props unchanged.

---

## Wave 4 — Harness and close-out

- [ ] **T4.1** Build `scripts/validate_provider_persistence.py` with all eight harness assertions.
  RIPPLE: assertions 3 and 4 (no credential in any written config file, none in any
  `/api/inference/state` response) are worth running on every commit regardless of what changed — a
  credential leak is the failure here that no user would ever report, because nothing about it is
  visible from the app.

- [ ] **T4.2** Full-suite regression: backend + `npx jest` + `npx tsc --noEmit`.

- [ ] **T4.3** Update `docs/CADUCEAN_ARCHITECTURE.md` §9 (**append** a row — `local-model-provider-parity`
  T5.5 and `lfm25-encoder-integration` T5.5 edit the same table; do not rewrite it) and
  `bootstrap/GOALS.md` with a **Domain 24** entry (22 → `local-model-provider-parity`,
  23 → `lfm25-encoder-integration`).

- [ ] **T4.4** Manual verification against T0.1: two providers, different keys, bound to different
  roles, restart, both intact and switchable from the chat row.

---

## Dependency / parallelization notes

**Hard sequencing:**

- **T0.1 / T0.2 before everything.** Both record a "before" that cannot be reconstructed later.
- **`local-model-provider-parity` T1.4 before T1.1** (C1) — that task creates the `providers`
  collection this one extends. Not a blocker if this spec goes first, but then T1.1 owns matching
  its name, key space and shape exactly.
- **Wave 1 before Wave 2.** The migrator needs a target shape to migrate into.
- **T1.2 before T1.3.** The atomic write stores a `cred_ref`; the keyring path must exist first.
- **Wave 2 before Wave 3.** A switcher on unmigrated storage shows providers that vanish on restart.
- **`local-model-provider-parity` Wave 1 before T3.3** — needs `loaded`.
- **T2.3 must use the same id scheme as `local-model-provider-parity` REQ-2 AC1.** Two schemes for
  one model is a dead binding by construction.

**Parallelizable:**

- **Waves 1–2 (backend persistence) and T3.1 (Send removal + reflow) are independent.** Different
  files, no shared state — the input-row cleanup can land while persistence is in progress.
- T0.3 (send-path audit) is independent of everything.
- All test-writing precedes its implementation task.

**Riskiest tasks:**

1. **T3.1 — the disabled guards.** Deleting the button deletes
   `!inputText.trim() || isTyping || voiceState === 'listening'` unless they are moved first. The
   symptom is `Enter` sending while IRIS is listening or mid-response — a UX regression with no
   error and no failing test unless `InputRow.test.tsx` asserts it.
2. **T1.3 — write ordering.** Config-then-keyring produces providers that look configured and
   cannot authenticate, and only after a crash at exactly the wrong moment.
3. **T2.1 — partial migration.** Two sources of truth for one provider is the direct route to a URL
   paired with the wrong key. All-or-nothing, or not at all.
4. **T2.6 — tidying routing mode.** It is the most natural thing to clean up while restructuring the
   config around it, and it is explicitly out of scope (Decision Locked #7). CT-P5 pins it.
5. **T1.2 / T3.6 — credential exposure.** The one failure mode here that produces no visible symptom
   and no user report. Harness assertions 3 and 4 are the only detectors.
6. **T2.3 — id scheme divergence.** Silent until a binding stops resolving, at which point it looks
   like a persistence bug rather than a naming one.

### Baseline record
<!-- T0.1 / T0.2 record the "before" here; T4.4 records the "after". -->

| Observation | Before (T0.1/T0.2) | After (T4.4) |
|---|---|---|
| Provider A key present after configuring B | | |
| Provider A key present after restart | | |
| Both roles bound to different providers after restart | | |
| Routing: `api` | | |
| Routing: `lm_studio` | | |
| Routing: `ollama` | | |
| Routing: `iris_local` | | |

# Tasks: Phase 1 — Foundation

> Each task links to a requirement. Waves are dependency-ordered.
>
> **This spec has NO external blockers.** Everything needed is in this repo today. Do not consult
> `local-model-provider-parity`, `contextpill-model-switcher`, or `der-loop-integrity-display` for
> Phase 1 scope — this file supersedes them for these requirements.
>
> **Nothing in Phases 2–5 may start until Wave 5 is green.**

---

## Wave 0 — Baselines (record before changing anything)

- [ ] **T0.1** (REQ-9) Record routing behaviour for **all four** `provider` values
  (`api`, `lm_studio`, `ollama`, `iris_local`): which backend serves a request in each.
  RIPPLE: ⚠️ this is the "before" that REQ-9 AC3 asserts against. Without it, "unchanged" is an
  opinion. Cannot be reconstructed after the change.

- [ ] **T0.2** (REQ-6) Record the current failure: configure provider A, configure provider B,
  restart, confirm A's key is gone. Also confirm it is **present before** the restart — that
  distinction is what proves the bug is persistence, not registration.

- [ ] **T0.3** (REQ-2) Record the resolved window + ContextPill denominator for every provider you
  have configured. Note which are the 8,192 default.

- [ ] **T0.4** Green-suite baseline: `pytest backend/tests` (note the pre-existing failures listed
  at the bottom of this file so real breaks are distinguishable from stale artifacts).

---

## Wave 1 — Budget + window truth (REQ-1, REQ-2, REQ-10)

- [x] **T1.1** (REQ-1 AC1/AC2/AC3) `resolve_der_token_budget(window, task_class)` — mode value is a
  CEILING, window the hard cap, floor applied last and clamped. **DONE `01e6625b`.**
  RIPPLE: `DER_TOKEN_BUDGETS` / `get_token_budget` UNCHANGED — `_decide_mode` (`der_loop.py:220`)
  and `_should_escalate` (`:283-289`) read them. **Do not delete the mode table** (REQ-1 AC6).

- [x] **T1.2** (REQ-1 AC5) Log budget + window + class + work units in one line, both derived from
  the same window. **DONE `01e6625b`.**

- [ ] **T1.3** (REQ-1 AC7) ⚠️ **Write the budget tests — they do not exist.** The T1.1 fix is
  currently unprotected.
  - `backend/tests/unit/test_der_budget_allocation.py` — parametrized {2k, 8k, 32k, 128k, 256k} ×
    {quick, implement, full}. Budget ≤ window always; ceiling binds on large windows; floor never
    exceeds the window.
  - `backend/tests/contract/test_budget_workunits_agree.py` — CT-F2.
  - `backend/tests/behavioral/test_no_budget_overcommit.py` — the live cerebras case.
  RIPPLE: reducing the parametrize matrix is a test modification. The 2k and 256k ends are the ones
  that catch floor-overcommit and ceiling-underuse respectively.

- [ ] **T1.4** (REQ-2, REQ-10 AC1) Reorder `resolve_context_window` to D-2 precedence
  (override → authoritative → table → default) and return the `source` tag.
  RIPPLE: ⚠️ the authoritative branch **already exists** at
  [`agent_kernel.py:960-975`](backend/agent/agent_kernel.py:960) with a comment saying the table
  *"would otherwise under/over-size the budget"* — it just runs after the table. This is a reorder,
  not a rewrite. Live bug: a 16k-loaded Mistral currently reports 32,768.
  ⚠️ **ContextPill's displayed denominator will change** as a result. Expected — do not "fix" it back.

- [ ] **T1.5** (REQ-2 AC1/AC6) Add confirmed table entries only.
  RIPPLE: ⚠️ **Never guess a window upward** (D-3). Budget is `window × 0.9`, so an overstated
  window silently re-creates the overcommit; an understated one merely wastes capacity and is
  correctable by an override. `("cerebras", "gemma-4-31b", 256_000)` landed in `01e6625b`; a
  provider-wide `("cerebras", "", N)` was deliberately **not** added. `test_no_raised_provider_default`
  guards this.

- [ ] **T1.6** (REQ-2 AC4, REQ-10 AC5) Surface window + source + provider load state in
  `/api/debug/caducean`.
  RIPPLE: that endpoint is strictly read-only — keep it so.

---

## Wave 2 — One collection, one registry (REQ-3, REQ-4, REQ-5, REQ-6)

- [ ] **T2.1** (REQ-6 AC1/AC7) Add `ProviderEntry` and `providers: dict[str, ProviderEntry]` +
  `config_version` to `InferenceConfig`.
  RIPPLE: ⚠️ **ONE collection for API and local entries, one key space** (D-6). Do not add a
  separate `local_providers` list — two collections reproduce at the config layer the split-registry
  problem REQ-5 exists to delete. `endpoint` and `cred_ref` are fields of the **same record**; do not
  add a standalone `api_base_url` a writer could touch alone.
  `role_bindings` untouched — already a list (`iris_config.py:230`).

- [ ] **T2.2** (REQ-6 AC4) Wire `cred_ref` to the **existing** per-id keyring.
  RIPPLE: ⚠️ **Smaller than it looks — do not build a credential store.** `get_secret(self.id)`
  already resolves per provider id ([`provider.py:49-53`](backend/agent/inference/provider.py:49)),
  `has_key` is already emitted (`:65`), and `api_key` is per-instance (`:42`). The registry and
  keyring already handle multiple providers; **only persistence is single-slot.** Rebuilding risks
  the half that works.

- [ ] **T2.3** (REQ-7) Atomic provider write: endpoint + credential together, mismatch rejected,
  crash leaves the previous entry intact. **Keyring first, then config** (D-5).
  RIPPLE: ⚠️ ordering is load-bearing. Config-then-keyring leaves a `cred_ref` pointing at nothing —
  a provider that looks configured and fails at request time.
  **Permit** endpoint-only and key-only edits of an *existing* provider; the rule forbids
  *mismatched* pairs, not all partial edits. Over-applying blocks key rotation.

- [ ] **T2.4** (REQ-4) Namespace local ids as `local:<model-stem>`; add `purpose` to
  `ProviderInstance` and `ProviderEntry`.
  RIPPLE: migrate **every** literal `"local"` in the same change (AC4) — `agent_kernel.py:962`,
  `:8476`, `:8544`, plus `iris_gateway.py:7896`, `:8580`. A partially-migrated id is a dead binding
  that *looks* configured. Grep for the literal afterward.

- [ ] **T2.5** (REQ-3 AC1/AC2) Register local providers from configuration at
  `InferenceRouter._apply_config` init — **before any load**. Add `loaded` / `loading` to
  `ProviderInstance`, keeping `to_dict` additive.
  RIPPLE: this is the inversion the phase rests on. `ModelInferenceSection.tsx` must keep working
  unmodified (CT-F7) — additive fields only.

- [ ] **T2.6** (REQ-3 AC6) Convert the binding guard at
  [`iris_gateway.py:8580`](backend/iris_gateway.py:8580) from a **veto** into a status flag.
  RIPPLE: `role_binding_error` message shape unchanged — still emitted for genuinely invalid
  bindings, just not for "not loaded yet".

- [ ] **T2.7** (REQ-5 AC1/AC2/AC5) Make the registry process-wide and thread-safe.
  RIPPLE: read from the DER executor thread, written from the WS handler. Preserve
  `InferenceRouter`'s public surface (AC4).

- [ ] **T2.8** (REQ-5 AC3) Delete **all three** fan-out loops: `iris_gateway.py:7910`,
  `:8605-8618`, `:6012`.
  RIPPLE: ⚠️ **all three, not just `:7910`.** The comment at `:7913-7914` names the other two. A
  shared registry racing a surviving propagation loop is worse than either alone — and `:8605` is
  the handler **Phase 5's switcher writes through**, so a half-deletion surfaces there first and
  looks like a switcher bug.
  Also reconcile the startup restore path `:1339-1407`: hydration must not double-apply, and its
  `set_model_selection` → `set_role_binding` ordering comment must survive.

- [ ] **T2.9** (REQ-5 AC6) Verify the phase-scheduler gate call inside `InferenceRouter.generate()`
  survives the registry refactor.
  RIPPLE: ⚠️ easy to drop while moving registry code. CT-F3 pins it. The phase scheduler is the one
  Caducean component that has **passed** live testing — do not regress it here.

---

## Wave 3 — Migration (REQ-8)

- [ ] **T3.1** (REQ-8 AC1/AC3/AC4) Migrator: flat → collection, gated on `config_version`,
  idempotent, all-or-nothing. Migrates **both** `api_base_url`/`api_key` **and** `local_model_*`.
  RIPPLE: ⚠️ gate on `config_version`, **not** "flat fields present" — the latter re-runs forever.
  ⚠️ **Both field groups migrate here, in one migrator.** Splitting them across two once-only
  migrations is how a field gets migrated twice and a URL acquires the wrong key.

- [ ] **T3.2** (REQ-8 AC2) Migrate `role_bindings` so every binding that resolved before resolves
  after — including entries referencing the literal `"local"`.
  RIPPLE: must use T2.4's id scheme. A dangling binding looks configured and serves nothing.

- [ ] **T3.3** (REQ-8 AC5) Move the migrated key into the keyring without user re-entry.

- [ ] **T3.4** (REQ-8 AC6) Flat **and** collection both present → collection wins, flat ignored,
  **never merged**.
  RIPPLE: merging is the direct route to a mismatched endpoint/credential pair.

- [ ] **T3.5** (REQ-9) Verify routing mode untouched: `provider` field, vocabulary, the
  `active_provider` alias (`iris_config.py:238`), `lm_studio_url` / `ollama_url`.
  RIPPLE: ⚠️ **Do not "clean up" the routing-mode field while restructuring the config around it.**
  It is the most natural thing to tidy in this diff and explicitly out of scope. CT-F5 pins it.

---

## Wave 4 — Observability (REQ-10)

- [ ] **T4.1** (REQ-10 AC1/AC2) Structured logs: resolved window + source; DER budget + window +
  class + units.

- [ ] **T4.2** (REQ-10 AC3/AC4) Log provider writes, rejections, and migration outcomes — **never**
  the credential or any fragment. Redact credentials appearing in downstream library errors.

- [ ] **T4.3** (REQ-10 AC5) Expose window, source, and provider load state in
  `/api/debug/caducean` (extends T1.6).

---

## Wave 5 — Verification + close-out

- [ ] **T5.1** Contract tests: CT-F1..CT-F9 (`backend/tests/contract/`).

- [ ] **T5.2** Behavioral tests: `test_two_providers_survive_restart`,
  `test_second_provider_does_not_erase_first`, `test_bind_before_load`, `test_two_local_models`,
  `test_binding_survives_restart`, `test_upgrade_preserves_existing_provider`,
  `test_routing_mode_unchanged`, `test_no_silent_provider_fallback`.

- [ ] **T5.3** Build `scripts/validate_phase1_foundation.py` with all 11 harness assertions.
  RIPPLE: assertions 2, 5 and 6 are worth running on every commit regardless of what changed — an
  overcommit and a credential leak both fail silently and neither produces a user report.

- [ ] **T5.4** Full-suite regression + `npx tsc --noEmit`. Compare against T0.4.

- [ ] **T5.5** Manual verification against T0.1–T0.3: two providers with different keys survive a
  restart; a local provider is bindable while unloaded; ContextPill shows the real window; routing
  unchanged for all four modes.

- [ ] **T5.6** Update `docs/CADUCEAN_ARCHITECTURE.md` §9 (**append** a row) and `bootstrap/GOALS.md`
  (**Domain 22**).

- [ ] **T5.7** Record the baseline table below. **Phases 2–5 unblock only when this wave is green.**

---

## Dependency / parallelization notes

**Hard sequencing:**
- **Wave 0 before everything.** T0.1 and T0.3 record "before" states that cannot be reconstructed.
- **T1.4 before T1.5.** Reorder the precedence, then add entries — otherwise new entries are added
  into a path that still loses to the table.
- **T2.1 before T2.2/T2.3.** The entry shape must exist before writers target it.
- **T2.4 before T3.2.** Bindings migrate to the new id scheme; the scheme must exist first.
- **Wave 2 before Wave 3.** The migrator needs a target shape.
- **T2.8 with T2.7**, not after. Deleting fan-out before the registry is shared loses propagation
  with nothing replacing it.

**Parallelizable:**
- **Wave 1 (budget/window) and Wave 2 (registry/config) are independent** — different files, no
  shared state. Two agents can run them concurrently.
- T1.3 (budget tests) is independent of everything else in Wave 1.
- T4.x can be written at any point.
- All test-writing precedes its implementation task.

**Riskiest tasks:**
1. **T2.8 — partial fan-out deletion.** Three sites; the comment at `:7913` names them. Missing one
   leaves a shared registry racing a propagation loop, and it surfaces in Phase 5's UI.
2. **T2.3 — write ordering.** Config-then-keyring produces providers that look configured and cannot
   authenticate, and only after a crash at exactly the wrong moment.
3. **T1.5 — guessing a window upward.** Silently re-creates the overcommit this whole phase removes.
4. **T3.1 — partial migration.** Two sources of truth for one provider is the direct route to a URL
   paired with the wrong key.
5. **T2.9 — dropping the phase gate.** The phase scheduler is the one component that has passed live
   testing. Regressing it here would be the worst outcome of this phase.
6. **T2.4 — partial id migration.** A dead binding that looks configured.
7. **T3.5 — tidying routing mode.** Natural to clean up, explicitly out of scope.

**Known pre-existing failures (NOT caused by this phase — do not "fix" by editing tests):**
- `test_narration_contract` / `test_narration_flow` — assert `"Still"` / `"researching"`, wording
  that `cross-thread-crawl-fix` T36 requires removing. **Phase 2 resolves these** as part of closing
  T36.
- `test_kernel_separation_behavior::test_utterance_forwarded_during_expand` — asserts synchronous
  `tts.speak`; `_on_utterance_start` now dispatches via a daemon thread. **Phase 2.**
- `test_crawler_task_progress` ×2 — stale stub (`_fake_run` missing `job_id`) and `InternetGate`
  blocking in-fixture. Legitimate stub repairs; **Phase 2.**
- `npx jest` runs **0 tests** — 7/7 suites fail to parse (ESM config). Frontend has no working test
  enforcement. Not this phase's scope, but it means Phase 1's frontend impact is `tsc`-verified only.

### Baseline record
<!-- T0.1-T0.3 record "before"; T5.5 records "after". -->

| Observation | Before | After |
|---|---|---|
| Provider A key present after configuring B (no restart) | | |
| Provider A key present after restart | | |
| Two roles bound to different providers after restart | | |
| Local provider bindable while unloaded | | |
| Resolved window / source — provider 1 | | |
| Resolved window / source — provider 2 | | |
| ContextPill denominator | | |
| DER budget for a real task | | |
| Routing: `api` / `lm_studio` / `ollama` / `iris_local` | | |

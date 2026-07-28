# Requirements: Phase 1 — Foundation (budget, context window, provider registry)

> **Execution position: FIRST.** Nothing in this spec is blocked on another spec.
> Phases 2–5 are all blocked on this one. Do not start them until this is green.
>
> **This file is authoritative for Phase 1.** Everything needed is here.

## Decisions Locked

Resolved with the user 2026-07-28. Do **not** re-litigate.

1. **One provider collection, keyed by id.** `InferenceConfig.providers: dict[str, ProviderEntry]`
   holds API and local entries in a single key space. Not two collections.
2. **Endpoint and credential are one record.** A provider's URL and its credential reference live
   in the same entry, written together. A mismatched pair must be unrepresentable, not merely
   rejected.
3. **The keyring is already per-provider-id and stays.** `get_secret(self.id)` already works
   ([`provider.py:49-53`](backend/agent/inference/provider.py:49)). Wire to it; do not rebuild it.
4. **Routing mode is frozen.** `InferenceConfig.provider` (`api | lm_studio | ollama | iris_local`)
   is not touched by this phase. This phase changes *where credentials live*, not how requests route.
5. **The DER mode table is a CEILING, never a floor.** The window is the hard cap. The floor is
   applied last and is itself clamped by the window.
6. **Per-class ceilings are FRACTIONS of the window, not absolute tokens.** A constant tuned for
   an 8k-32k era caps a 256k model at 17% utilisation, which is the opposite of what long-horizon
   work needs. The absolute `DER_TOKEN_BUDGETS` table is retained for escalation comparisons.
7. **A too-high context-window default is worse than a too-low one.** Budget is `window × 0.9`, so
   an over-stated window re-creates the overcommit. Under-sizing is safe. Never guess a window
   upward.

## Introduction

Three subsystems currently disagree with reality, and they share one cause: **an authoritative
value exists but a guess outranks it.**

- **DER's token budget** was `max(window × 0.9, DER_TOKEN_BUDGETS[class])`. Every table entry is
  15k–80k, so the "floor" beat the derived value for any model under ~44k.
- **Context windows** come from a `(provider, substring)` table that has no entry for several
  configured providers, so they silently resolve to an 8,192 default.
- **Providers** exist in memory but cannot be persisted: `InferenceConfig` holds **one**
  `api_base_url` and **one** `api_key`, while `role_bindings` is already a list that can reference
  several.

These are not three bugs. `resolve_context_window()` feeds DER's token budget, DER's work units,
Pacman's context-filtering target, and the ContextPill denominator — so one bad lookup produces
four symptoms that look unrelated.

### Success criteria

- DER's budget **never** exceeds the model's real context window, at any window size or task class.
- `_token_budget` and `derive_work_units_0()` derive from the **same** window value.
- Every configured provider resolves a context window that is either authoritative or explicitly
  logged as a default.
- A local provider exists in the registry from **configuration**, before any model is loaded.
- **Two** API providers with **different** keys persist and survive a restart with their own
  credentials.
- No state exists in which one provider's endpoint is paired with another's credential.
- An existing single-provider install upgrades with its provider intact and still bound — no key
  re-entry.
- Routing behaves exactly as it does today for every `provider` value.

## Requirements

---

### REQ-1: DER's budget is allocated from the model's real context window

**User Story:** As the Director I want my step budget derived from the window the model actually
has, so that I do not plan long-horizon work against capacity that does not exist.

**Verified:** REAL BUG — **fix landed 2026-07-28 in commit `01e6625b`** (`resolve_der_token_budget`
in [`der_constants.py`](backend/agent/der_constants.py), consumed at
[`agent_kernel.py:5352`](backend/agent/agent_kernel.py:5352)). This requirement exists so it cannot
regress, and because **its tests were never written** (AC7).

Observed live: `provider=cerebras model=gemma-4-31b` resolved to the 8,192 default and DER reported
`budget=40000`:

```
window 8_192 → 8_192 × 0.9 = 7_372 ;  floor = DER_TOKEN_BUDGETS["implement"] = 40_000
_token_budget = max(7_372, 40_000) = 40_000          ← 4.9× the window
derive_work_units_0(8_192) = 5 units ≈ 7_372 tokens  ← disagrees with the budget by 5×
```

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL derive the DER step budget from `resolve_context_window()`, and the budget
  SHALL NEVER exceed that window.
- AC2: THE SYSTEM SHALL express the per-class ceiling as a **fraction of the usable window**
  (`DER_MODE_WINDOW_FRACTION`), never as an absolute token count, so capacity scales with the model.
  It SHALL NOT be applied as a floor.
- AC2b: THE SYSTEM SHALL retain `DER_TOKEN_BUDGETS` in **absolute** tokens alongside the fractions.
  Two structures answer two different questions: *"how much of this window may this class use"*
  (fractions, here) versus *"does this mode have room left"*
  ([`der_loop.py:283-289`](backend/agent/der_loop.py:283), absolute). Replacing the absolute table
  breaks escalation.
- AC3: THE SYSTEM SHALL apply the minimum floor **last** and SHALL clamp the floor by the window,
  so a floor can never reintroduce an overcommit.
- AC4: THE SYSTEM SHALL derive `_token_budget` and `derive_work_units_0()` from the **same**
  `context_window` value.
- AC5: THE SYSTEM SHALL log the resolved budget with the window, task class, and work units in one
  line.
- AC6: THE SYSTEM SHALL retain `DER_TOKEN_BUDGETS` and `get_token_budget` unchanged —
  `DirectorQueue._decide_mode` ([`der_loop.py:220`](backend/agent/der_loop.py:220)) and
  `_should_escalate` ([`:283-289`](backend/agent/der_loop.py:283)) both read them.
- AC7: THE SYSTEM SHALL prove AC1–AC4 by test across window sizes {2k, 8k, 32k, 128k, 256k} × task
  classes {quick, implement, full}.

**Edge Cases:**
- Window smaller than the floor (2k model) → budget clamps to `window × 0.9`; the floor is ignored.
- 256k window with `task_class="quick"` → the 10% fraction binds at ~23.6k; a single-tool task is
  not handed the whole window, but it still scales with the model.
- 8k window with `task_class="quick"` → 10% of 7,372 is 737, below `DER_BUDGET_MIN_FLOOR`, so the
  floor raises it to 4,000. Correct: the floor exists for exactly this case, and AC3's clamp keeps
  it under the window.
- Model swapped mid-session → budget resolves per DER invocation; no restart needed.

---

### REQ-2: Every configured provider resolves a real context window

**User Story:** As a user on any provider I want the app to know my model's real window, so that
the ContextPill is honest and DER is not sized against a placeholder.

**Verified:** REAL GAP. `_KNOWN_CONTEXT_WINDOWS`
([`agent_kernel.py:884-932`](backend/agent/agent_kernel.py:884)) is a `(provider, substring)` list.
Lookup requires `reg_provider == provider` ([`:951-955`](backend/agent/agent_kernel.py:951)), so an
unlisted provider always falls to 8,192. Live symptom: the ContextPill read `0/8.2k` for every turn.
A confirmed `("cerebras", "gemma-4-31b", 256_000)` entry landed in `01e6625b`; the general gap
remains.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL resolve a context window for every configured provider, not only those in
  the static table.
- AC2: WHERE an authoritative window is available (provider metadata, or a local model's loaded
  `n_ctx`) THEN THE SYSTEM SHALL prefer it over the substring table.
- AC3: THE SYSTEM SHALL keep the user override (`_context_window_overrides`) highest-precedence.
- AC4: IF no window can be determined THEN THE SYSTEM SHALL use a conservative default, log that a
  default was used, and expose that fact — an unknown window SHALL be visible, not silent.
- AC5: THE SYSTEM SHALL NOT infer a window from a model-name substring when an authoritative value
  is available.
- AC6: THE SYSTEM SHALL NOT introduce a provider-wide default that is **higher** than the
  conservative default (Decision Locked #6).

**Edge Cases:**
- Provider-wide fallback entries (the `("openrouter", "", 32_000)` pattern) → permitted, but AC4
  still requires logging it as a default.
- Provider reports a window larger than the account's quota → out of scope; sizing is from the
  model's window, not rate limits.
- A local model loaded at a different `n_ctx` than its filename suggests → AC2; the loaded value
  wins. (This is the old `parity` REQ-5b, folded in here.)

---

### REQ-2b: Work units are debited by measured cost, not by step count

**User Story:** As the termination resource I want each step to consume its real token cost, so
that a 50k-char crawler result and a 200-char `read_file` are not billed equally.

**Verified:** Folded from the DER integrity audit (finding G). Belongs here because
`work_units` and the token budget must stay coupled to the **same** `resolve_context_window()`
resource (REQ-1 AC4) — splitting them across phases is how they drifted 5x apart in the first place.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL debit `work_units` by `max(1, measured_tokens / AVG_STEP_COST)` per
  executed step, where `measured_tokens` is the real cost of that step's result + prompt.
- AC2: THE SYSTEM SHALL retain `AVG_STEP_COST` as a tunable constant (currently 1500) consumed by
  the debit formula.
- AC3: WHEN a split occurs THEN THE SYSTEM SHALL still prepay `width` units up front, preserving
  the strictly-decreasing Lyapunov invariant.
- AC4: THE SYSTEM SHALL keep `work_units` and the token budget derived from the same
  `resolve_context_window()` value (REQ-1 AC4).

**Edge Cases:**
- Token count unavailable (no tokenizer) → debit 1 unit as a safe floor, debug log.
- Split child with zero measured cost → debit floor of 1.
- `AVG_STEP_COST` tuned to 0 or negative → clamp to a minimum (e.g. 200) to avoid div-by-zero.

---

### REQ-2c: Resolver fallback is reasoning, not a web tool

**User Story:** As the resolver I want the safe fallback for a non-web goal to be reasoning, so
that I do not inject a tool preference at the wrong layer.

**Verified:** Folded from the DER integrity audit (finding E). Belongs here because it is
the same defect shape as REQ-2 — a fallback outranking a better-informed answer.

**Acceptance Criteria:**
- AC1: WHEN the LLM proposal is unparseable or invalid AND the goal's `task_class != "research"`
  THEN THE SYSTEM SHALL fall back to pheromone top-1 or `reasoning` — **never** `crawler_query`.
- AC2: WHEN `task_class == "research"` AND capability allows THEN THE SYSTEM SHALL prefer
  `crawler_query` as first fallback (current behaviour, preserved).
- AC3: THE SYSTEM SHALL pass the evidence block into the prompt for `kind="reasoning"` steps
  identically to `kind="tool"` steps.

**Edge Cases:**
- No pheromone prediction and not research → return `reasoning` (tool=None).
- Evidence empty → prompt still builds with a blank evidence section.

---

### REQ-3: Local providers are declarative, not a side effect of loading

**User Story:** As a user I want to configure a local model the same way I configure an API
provider, so that binding a role to it does not depend on what I did first.

**Verified:** REAL GAP — the local `ProviderInstance` is constructed **inside the model-load
handler** at [`iris_gateway.py:7896`](backend/iris_gateway.py:7896), so it does not exist until a
load succeeds. The binding guard at [`:8580`](backend/iris_gateway.py:8580) then rejects a binding
because nothing is loaded — a circular dependency.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL register local providers from **configuration** at router init, before any
  load.
- AC2: THE SYSTEM SHALL expose an explicit `loaded` / `loading` status on every provider, additive
  to the existing payload.
- AC3: THE SYSTEM SHALL allow a role to be bound to a **configured but unloaded** local provider.
- AC4: WHEN a request arrives for a role bound to an unloaded local provider THEN THE SYSTEM SHALL
  load it on demand or fail with a typed, actionable error — and SHALL NOT silently answer from a
  different provider.
- AC5: THE SYSTEM SHALL make a role binding to a local provider survive a restart.
- AC6: THE SYSTEM SHALL convert the binding guard at `iris_gateway.py:8580` from a **veto** into a
  status flag.

**Edge Cases:**
- Model file missing at load → provider stays registered, `loaded=false`, typed error naming the
  path.
- Load fails repeatedly → status reflects the error; the provider does not vanish from the registry.

---

### REQ-4: Providers are identified by a namespaced, stable id

**User Story:** As a user I want two local models bound to my two roles at once, so that a small
tool model and a large reasoning model can serve different jobs.

**Verified:** REAL GAP — the local instance is created with the literal id `"local"`
([`iris_gateway.py:7896`](backend/iris_gateway.py:7896)), so a second local model overwrites the
first. Phase 4 needs this: Embedding-350M and ColBERT are additional local models that must coexist
with a local chat model.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL identify each local provider by a stable id derived from the model
  (`local:<model-stem>`), never the bare literal `"local"`.
- AC2: THE SYSTEM SHALL support at least two local instances registered and bound simultaneously to
  different roles.
- AC3: THE SYSTEM SHALL carry a `purpose` field on every provider (`chat` | `embedding` | `rerank`),
  defaulting to `chat`.
- AC4: THE SYSTEM SHALL migrate every code path matching the literal `"local"` in the same change —
  a partially-migrated id is a dead binding.
- AC5: THE SYSTEM SHALL namespace local ids so collision with an API preset id
  (`openai`, `cerebras`) is impossible.

**Edge Cases:**
- Same GGUF configured twice under different ids → allowed; distinct instances.
- Existing persisted bindings referencing `"local"` → migrated (REQ-8), not dropped.
- `purpose` undeterminable for a scanned model → default to `chat` and surface the ambiguity.

---

### REQ-5: One process-wide provider registry

**User Story:** As a maintainer I want provider state in one place, so the API endpoint and the
WebSocket session cannot disagree about which models exist.

**Verified:** REAL GAP — registration is fanned out across **every peer kernel's** router in a loop
at [`iris_gateway.py:7910`](backend/iris_gateway.py:7910). The code comment at `:7913-7914` states
the same workaround was already applied twice more. All three sites exist:

| Site | What |
|---|---|
| `:7910` | provider registration fan-out |
| `:8605-8618` | `set_role_binding` peer propagate |
| `:6012` | `_handle_set_model_selection` |
| `:1339-1407` | startup restore path calling both, with a load-bearing ordering comment |

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL hold provider instances and role bindings in a single process-wide
  registry, not per-kernel.
- AC2: THE SYSTEM SHALL make `/api/inference/state` and the WebSocket session read the **same**
  registry.
- AC3: THE SYSTEM SHALL delete **all three** fan-out loops rather than extend them.
- AC4: THE SYSTEM SHALL preserve `InferenceRouter`'s public surface (`resolve`, `generate`,
  `snapshot`, `bind_role`).
- AC5: THE SYSTEM SHALL keep registry access thread-safe — it is read from the DER executor thread
  and written from the WS handler.
- AC6: THE SYSTEM SHALL preserve the phase-scheduler gate call inside `InferenceRouter.generate()`.

**Edge Cases:**
- Kernel created after registration → sees the shared registry immediately, no propagation step.
- Startup restore path (`:1339-1407`) → registry hydration must not double-apply against it, and
  its `set_model_selection` → `set_role_binding` ordering must survive.

---

### REQ-6: Providers persist as one collection keyed by id

**User Story:** As a user I want every provider I configure remembered with its own credentials, so
that configuring a second does not erase the first.

**Verified:** REAL GAP, narrower than it appears. **Already works:** the keyring is keyed by
provider id ([`provider.py:49-53`](backend/agent/inference/provider.py:49)), `has_key` is already
emitted ([`:65`](backend/agent/inference/provider.py:65)), and `ProviderInstance.api_key` is
per-instance ([`:42`](backend/agent/inference/provider.py:42)) — so the **registry already holds
several providers' keys at once**. **The gap:** `InferenceConfig` holds one `api_base_url` and one
`api_key` ([`iris_config.py:192-193`](backend/iris_config.py:192)). `role_bindings` is already a
persisted list ([`:230`](backend/iris_config.py:230)) that can reference providers the config
cannot store. That asymmetry is why the failure only appears at restart.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL persist providers as **one** collection keyed by id, holding each entry's
  own endpoint, credential reference, label, kind, model, and `purpose`.
- AC2: THE SYSTEM SHALL support at least two API providers with **different** keys persisted
  simultaneously.
- AC3: THE SYSTEM SHALL make every persisted `role_bindings` entry resolvable to a persisted
  provider entry; a dangling binding SHALL be reported, not silently dropped.
- AC4: THE SYSTEM SHALL keep credentials in the OS keyring keyed by provider id, storing only a
  reference in the config. No key SHALL be written to the config file in clear.
- AC5: THE SYSTEM SHALL keep the persisted collection and the in-memory registry consistent.
- AC6: THE SYSTEM SHALL persist a provider on configuration, not on first successful use.
- AC7: THE SYSTEM SHALL hold local and API entries in the **same** collection and key space. Local
  entries carry `model_path` / `profile` / `purpose` and **no** `cred_ref` (local providers are
  keyless and unmetered, [`provider.py:16-22`](backend/agent/inference/provider.py:16)).

**Edge Cases:**
- Two providers sharing an endpoint with different keys → distinct entries; the id is the key, not
  the URL.
- Keyring unavailable → the provider is **not** persisted and the user is told; the key never falls
  back into the config file.

---

### REQ-7: A provider's endpoint is never written without its own credential

**User Story:** As a user I want a provider's endpoint and credential written together, so my key
for one vendor is never sent to another vendor's server.

**Verified:** REAL RISK — `api_base_url` and `api_key` are independent fields
([`iris_config.py:192-193`](backend/iris_config.py:192)) read independently by `from_dict`
([`:241-242`](backend/iris_config.py:241)), and the `set_model_selection` payload marks **both**
optional ([`useInferenceState.ts:131-132`](hooks/useInferenceState.ts:131)). "Write B's URL, leave
A's key" is expressible today.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL treat a provider's endpoint and credential as one unit — both written
  together or neither.
- AC2: IF a write would pair an endpoint with a different provider's credential THEN THE SYSTEM
  SHALL reject the write and report it.
- AC3: THE SYSTEM SHALL make a partially-written entry unreachable — an interrupted write SHALL
  leave the previous entry intact, never a hybrid.
- AC4: THE SYSTEM SHALL NOT allow a credential stored under one provider id to be used for a
  request to a different id's endpoint.
- AC5: THE SYSTEM SHALL log a rejection without the credential or any fragment of it.
- AC6: THE SYSTEM SHALL write the keyring **before** the config entry, so an interruption leaves an
  inert orphan rather than an entry whose `cred_ref` resolves to nothing.

**Edge Cases:**
- Editing only the endpoint of an existing provider → **permitted**; the credential belongs to the
  same id, so the unit holds. AC1 forbids mismatched pairs, not all partial edits.
- Rotating only the key of an existing provider → permitted, same reasoning.
- User pastes provider A's key into provider B's form → out of scope; the system cannot know a
  key's vendor. AC4 only guarantees the stored pairing is honoured.

---

### REQ-8: The flat config migrates, once, atomically

**User Story:** As an existing user I want my configured provider still there after the upgrade, so
that I do not re-enter keys.

**Verified:** REAL — every install has flat `api_base_url` / `api_key` / `local_model_*` fields
([`iris_config.py:191-211`](backend/iris_config.py:191)) and a `role_bindings` list that may
already reference ids the new collection must contain.

**Acceptance Criteria:**
- AC1: WHEN a config with flat fields is loaded THEN THE SYSTEM SHALL migrate **both** the API
  fields (`api_base_url`, `api_key`) and the local fields (`local_model_*`) into the single keyed
  collection, preserving endpoint, key, and model.
- AC2: THE SYSTEM SHALL migrate existing `role_bindings` so every binding that resolved before the
  upgrade resolves after it — including entries referencing the literal `"local"` (REQ-4 AC4).
- AC3: THE SYSTEM SHALL run migration exactly once, gated on a `config_version` marker, and SHALL
  be idempotent if run again.
- AC4: IF migration fails THEN THE SYSTEM SHALL leave the original config untouched and report —
  never a partially migrated config.
- AC5: THE SYSTEM SHALL move the migrated key into the keyring without user re-entry.
- AC6: WHERE flat fields **and** a collection are both present THEN the collection SHALL win and
  the flat fields SHALL be ignored, **never merged**.

**Edge Cases:**
- Fresh install (flat fields empty) → empty collection, no migration, no error.
- Config file read-only → AC4 reports; the app runs unmigrated rather than losing the config.
- Gating on "flat fields present" instead of `config_version` → re-runs forever; AC3 forbids it.

---

### REQ-9: Routing mode is unchanged

**User Story:** As a user I want request routing to behave exactly as today, so a storage change
does not alter which backend serves my requests.

**Verified:** `InferenceConfig.provider` ([`iris_config.py:187`](backend/iris_config.py:187))
selects routing mode and is read at [`:238`](backend/iris_config.py:238) with an `active_provider`
alias fallback.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL leave the `provider` routing-mode field and its semantics unchanged.
- AC2: THE SYSTEM SHALL preserve the `active_provider` alias fallback in `from_dict`.
- AC3: THE SYSTEM SHALL NOT change which backend serves a request for any configuration that works
  today, for **all four** values (`api`, `lm_studio`, `ollama`, `iris_local`).
- AC4: THE SYSTEM SHALL keep `lm_studio_url` and `ollama_url` behaviour unchanged.

**Edge Cases:**
- `provider` set to a value with no matching collection entry → existing behaviour preserved; this
  phase adds no validation that would newly reject a working config.

---

### REQ-10: Foundation decisions are observable

**User Story:** As the tuner I want the resolved window, budget, and provider writes logged, so
"it forgot my provider" and "the budget was wrong" are diagnosable from a log.

**Verified:** NEW.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log the resolved context window with its **source** (`override` |
  `authoritative` | `table` | `default`).
- AC2: THE SYSTEM SHALL log the DER budget with window, task class, and work units (REQ-1 AC5).
- AC3: THE SYSTEM SHALL log each provider write with the provider id and outcome, and SHALL NOT log
  the credential or any fragment.
- AC4: THE SYSTEM SHALL log migration with the number of providers migrated and the outcome.
- AC5: THE SYSTEM SHALL expose the resolved window, its source, and provider load state through
  `/api/debug/caducean`.
- AC6: THE SYSTEM SHALL keep logging off the critical path.

**Edge Cases:**
- Credential appearing in a downstream library's error string → redacted before logging.

---

## Non-Requirements (Out of Scope for Phase 1)

- **The auto-optimizing loader** (config derivation, GPU degradation ladder, VRAM estimation, tok/s
  feedback, folder scanning) → **Phase 3**.
- **The encoders** → **Phase 4**.
- **Any UI** — no switcher, no Send-pill removal, no ContextPill change → **Phase 5**.
  Phase 1 only makes the payload additive and truthful.
- **Narration and live task-card display** → **Phase 2**.
- **Changing routing mode** → REQ-9 freezes it.
- **Changing the DER band thresholds** or the mode-table *values*.

## Open Questions

- ~~**OQ-1:** fractions vs absolute ceilings~~ — **RESOLVED 2026-07-28: fractions.** Now
  Decision Locked #7 and REQ-1 AC2. Effect on a 256k window: `implement` 40,000 -> 94,371,
  `full` 60,000 -> 212,336. Small windows are unaffected (still clamped by the window, then the
  floor).
- **OQ-2:** Which providers expose model metadata for REQ-2 AC2, and via what call? Needs a survey;
  until then the override plus confirmed table entries carry it.
- **OQ-3:** The `config_version` value for REQ-8 AC3.

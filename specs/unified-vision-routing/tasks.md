# Tasks: Unified Vision Capability Routing

> **STATUS 2026-08-18 — CODE COMPLETE. 205 backend tests + 8 ModelBrowserPanel tests
> green; standing harness `scripts/validate_der_vision_routing.py` 32/32, exit 0.**
> Every task T0a–T17 is landed. The ONLY remaining work is **T14b: live confirmation
> on real hardware**, which cannot be done by an agent — see the ordered progression
> in MCM pin_6c28ccf0a705.
>
> Nothing in this feature has ever run against a real GPU. In particular these are
> IMPLEMENTED AND TESTED BUT NEVER OBSERVED LIVE: the `--fit off` fix for the slow
> first vision request (T4, `ttr_sec` is logged but unmeasured), tier-1 answering with
> NO llama-server spawn (success criterion #1), the badge reading LOADED across a
> reload and ERROR after a failed load, and the `vision:unavailable` chat system
> message on the no-fit path.
>
> KNOWN UNRELATED RED: `__tests__/components/TaskListCard.test.tsx` fails against an
> already-modified `components/chat/TaskListCard.tsx` that predates this work. Not
> touched by this feature.


> Each task links to a requirement. Waves group work that can proceed in parallel.
> RIPPLE notes name what else the task touches or relies on.

## Wave 0 — Baseline characterization — ✅ COMPLETE 2026-08-18 (37 tests green)

> Landed: `backend/tests/unit/test_scan_models_baseline.py`,
> `test_build_server_cmd_baseline.py`, `test_vision_selection_baseline.py`,
> `test_local_provider_migration_baseline.py`,
> `backend/tests/contract/test_local_model_status_baseline.py` (32 tests, 6.6s), plus
> `__tests__/components/ModelBrowserPanel.test.tsx` and `model-status-badge.test.tsx`
> (5 tests, 2.4s). No production code was touched.
>
> Two spec corrections came out of it: the estimator is `_compute_vision_gpu_layers`
> (`:374`), not `_resolve_gpu_layers`; and REQ-7 AC3 was unsatisfiable as scoped,
> forcing the T10a/T10b split.


> Six of the ten change sites have NO test pinning today's behavior. Without these,
> a regression from T1/T4/T7/T8 is invisible. These tests assert what the code does
> TODAY — they are expected to be edited exactly once, by the task that changes the
> behavior they pin, and that edit must be called out in the task's report.

- [x] **T0a (pins T1)**: Characterize `scan_models` AS IT IS — assert the current
  result INCLUDES `mmproj-*.gguf` rows and record the entry count and field set
  — `backend/tests/unit/test_scan_models_baseline.py`
  BASELINE GAP: `tests/behavioral/test_local_model_load.py:163` asserts only that
  every entry has `path`/`filename`/`loaded`. Nothing pins the projector rows T1
  removes, so T1 cannot be shown to have removed exactly them.

- [x] **T0b (pins T4, T8)**: Characterize `_build_server_cmd` — snapshot the exact
  argv for a known model, asserting `--fit off` IS present and `--mmproj` is NOT
  — `backend/tests/unit/test_build_server_cmd_baseline.py`
  BASELINE GAP: **zero** tests reference `_build_server_cmd` today. It is the
  function T8 edits and the one T4 mirrors.

- [x] **T0c (pins T7)**: Characterize vision model selection — `_find_vision_model`
  returns a single `(model, mmproj)` pair and prefers the 3B unconditionally;
  `_compute_vision_gpu_layers` returns 0 (CPU) when the model does not fit the reserve
  — `backend/tests/unit/test_vision_selection_baseline.py`
  BASELINE GAP: **zero** tests on either function. T7 changes the first from a pair
  to a ladder — a signature change that ripples to every caller — and collides with
  the second (see Open Question: AC4 vs the CPU fallback).

- [x] **T0d (pins T3)**: Characterize the config migration — a migrated
  `LOCAL_OPENAI` ProviderEntry today carries endpoint `http://127.0.0.1:8081`
  — `backend/tests/unit/test_local_provider_migration_baseline.py`
  BASELINE GAP: no test exercises this migration path. It runs on every config load.

- [x] **T0e (pins T10, CT-4)**: Characterize the badge path end to end — what the
  backend persists as `inference.local_model_status`, what the WS handler emits, and
  what the dashboard seeds at mount (today: nothing)
  — `backend/tests/contract/test_local_model_status_baseline.py`,
  `__tests__/components/model-status-badge.test.tsx`
  BASELINE GAP: `local_model_status` appears in **no** backend test and **no**
  frontend test. CT-4 is entirely greenfield.

- [x] **T0f (pins T9)**: Characterize `ModelBrowserPanel` rendering against a fixture
  `/api/models` payload — `__tests__/components/ModelBrowserPanel.test.tsx`
  BASELINE GAP: the panel has no test at all. T9 extends a two-row plan it cannot
  currently prove it preserved.

### Already covered — do NOT re-derive
- `estimate_vram_gb`: `tests/unit/test_vram_estimate_includes_kv.py` — extend for
  the projector term (T7/T8), do not replace.
- Vision lease / idle-stop: `tests/contract/test_vision_lease.py` — 7 tests, CT-3 is
  MOSTLY WRITTEN. Only the `_stop_owned_vision_server` never-kills-an-unowned-PID
  case is missing; T11 EXTENDS this file rather than creating CT-3.
- `router.resolve()`: covered across 30+ behavioral/contract files.
- `ProviderInstance.to_dict()`: `tests/contract/test_build_inference_snapshot.py`
  and `test_local_provider_visible_when_loaded.py` guard T2's additive field.

## Wave 1 — Foundation — ✅ COMPLETE 2026-08-18 (94 tests green incl. Wave 0)

> T1, T2, T3, T4 and T10a landed. 269 insertions across the six files the Ripple-Effect
> Map predicted; no unexpected file touched. Live check: the real models dir went 18
> rows (4 projectors) -> 14 rows, 0 projector rows, all 4 projectors matched to their
> base model across different subdirectories.
> T4 needs a LIVE GPU run to confirm it fixes the slow first vision request — the spawn
> now logs `ttr_sec`, so one vision request measures it.


- [x] **T1 (REQ-5)**: Exclude `mmproj-*.gguf` from `scan_models`; attach each
  projector to its base model as `has_vision` / `mmproj_path` / `mmproj_size_gb`,
  matched by stem — `backend/agent/local_model_manager.py`
  RIPPLE: `/api/models` payload shape → `ModelBrowserPanel.tsx` reads it (T9);
  removes 3 of 18 rows, so any test asserting a model count changes. Locked by CT-2.

- [x] **T2 (REQ-1)**: Add `vision_loaded: bool` to `ProviderInstance` and a
  `(provider_id, model_substring)` vision table mirroring `_KNOWN_CONTEXT_WINDOWS`
  — `backend/agent/inference/provider.py`, `backend/agent/agent_kernel.py`
  RIPPLE: `ProviderInstance.to_dict()` feeds `provider_added` and the inference
  snapshot → ModelSwitcher; new field must be additive. Locked by CT-1.

- [x] **T3 (REQ-8)**: Derive the migrated local ProviderEntry endpoint from
  `LocalModelManager.PORT` instead of the hardcoded `8081`
  — `backend/iris_config.py:382`
  RIPPLE: touches config migration, which runs on every load; a wrong port here
  sends a migrated binding at the vision server. Independent of all other tasks.

- [x] **T4 (REQ-6)**: Pass `--fit off` plus explicit `--ctx-size` /
  `--n-gpu-layers` / `--batch-size` when spawning the vision server; log
  time-to-ready — `backend/tools/lfm_vl_provider.py`
  RIPPLE: mirrors the fix already in `local_model_manager._build_server_cmd`
  (e9d2fc89). Likely resolves the reported slow first vision request on its own,
  so land it early and measure before the rest.

## Wave 2 — Capability resolution (T5 depends on T2)

- [x] **T5 (REQ-1)**: Implement `supports_vision(instance)` covering API (table),
  LOCAL_OPENAI/INPROCESS (`vision_loaded`, NOT disk presence), OLLAMA
  (`/api/show`); unknown → False — `backend/agent/inference/router.py`
  RIPPLE: needs T2's field. Must not raise for an unrecognised kind — CT-1.
  CARRIED FROM T2: the API table landed as `_KNOWN_VISION_MODELS` in
  `agent_kernel.py`, but its MATCHING SEMANTICS (case-insensitive substring on the
  model, exact match on provider_id) are currently pinned by a helper defined INSIDE
  `backend/tests/unit/test_known_vision_models_table.py` — i.e. the test exercises its
  own helper, not production code. T5 SHALL implement those exact semantics in
  `supports_vision`, then REPOINT that test at the real function and delete the
  test-local helper. Until that happens the semantics are unenforced.

- [x] **T6 (REQ-2, REQ-9)**: Implement `resolve_vision_provider()` — brain → tool
  → fallback, returning a `VisionResolution`; log tier, provider, whether a load is
  required and free VRAM — `backend/agent/inference/router.py`
  RIPPLE: depends on T5. Calls `router.resolve()`, which raises on unbound roles —
  must swallow and continue. Consumed by T7.
  LEASE (Decisions Locked 8): `VisionResolution` SHALL carry a lease handle whenever
  the resolved provider is LOCAL (LOCAL_OPENAI / INPROCESS), at ANY tier — tier 1 and
  tier 2 local models take `acquire_vision_lease()` exactly as tier 3 does. A REMOTE
  provider (API / OLLAMA) takes none. Add `takes_lease: bool` to `VisionResolution`
  and extend CT-3 to assert a tier-1 LOCAL resolution acquires and releases a lease.

## Wave 3 — Fallback and projector loading (parallel after Wave 2)

- [x] **T7 (REQ-3, REQ-9)**: Replace the unconditional 3B preference with
  size-selection over a widest-first ladder (3B → 450M) against real free VRAM,
  adding projector size to the weights term and preserving
  `_VISION_VRAM_RESERVE_GB`; log the ladder and each rejection
  — `backend/tools/lfm_vl_provider.py:277-299`
  RIPPLE: reuses `get_hardware_info()` (nvidia-smi, true free VRAM) and
  `estimate_vram_gb(file_size_gb=…)` from e9d2fc89. Must not disturb lease /
  idle-stop / owned-PID lifecycle — CT-3.

- [x] **T8 (REQ-4)**: Pass `--mmproj` in `_build_server_cmd` when the base model
  has a projector; add `with_projector` to the load path; include projector size in
  pre-flight and in `plan_load`; set `vision_loaded` on the registered provider
  — `backend/agent/local_model_manager.py`, `backend/iris_gateway.py`
  RIPPLE: changes the VRAM budget for every multimodal model, so `plan_load`
  output on the card shifts (T9). `load_local_model` must still accept payloads
  without `with_projector` — CT-5. Sets the field T5 reads.

## Wave 4 — Frontend (parallel with Wave 3; only T9 needs T1/T8)

- [x] **T9 (REQ-4 AC5, REQ-5 AC3)**: Show vision capability on the model card and
  the measured projector cost (−35% generation, +1.2GB on gemma-4-E4B); allow
  loading without the projector — `components/dashboard/ModelBrowserPanel.tsx`
  RIPPLE: consumes T1's `has_vision` and T8's `with_projector`. The card already
  renders a two-row plan (e9d2fc89) — extend, do not restructure.

- [x] **T10a (REQ-7 AC3/AC4) — BACKEND, was missing**: Persist `"error"` on the
  failed-load path so ERROR survives a reload — `backend/iris_gateway.py:8553`
  RIPPLE: T0e proved `"error"` is written by NO path today; only `"loaded"` (`:8423`)
  and `"unloaded"` (`:8606`, `:1906`) are, and a failed load persists nothing. Without
  this, AC3 is unsatisfiable no matter what the frontend does. T10b depends on it.

- [x] **T10b (REQ-7 AC1/AC2)**: Seed the MODEL STATUS badge from the backend's
  persisted `inference.local_model_status` at dashboard mount, and reconcile to
  UNLOADED when nothing is listening — `hooks/useIRISWebSocket.ts`,
  `components/dark-glass-dashboard.tsx`
  REUSE, DO NOT BUILD: a `get_local_model_status` WS request handler ALREADY EXISTS
  (`iris_gateway.py:685` → `_handle_get_local_model_status` `:8838`) and has NO
  frontend caller today (T0e confirmed by grep). Seeding is likely a matter of calling
  it on mount, not of inventing a new channel. Alternative seam: `_handle_request_state`
  (`:6720`) fires on every WS open/reconnect and pushes `initial_state` —
  it never touches `local_model_status`, and adding it there covers reconnect too.
  RIPPLE: the WS bucket half is already fixed (e9d2fc89, writes
  `local-model-card`); this is the SEEDING half only. Locked by CT-4.

- [x] **T10c (REQ-7 AC3) — BACKEND, found by T10b**: Surface the PERSISTED
  `cfg.inference.local_model_status` to the frontend, so a failed load still reads
  ERROR after a reload — `backend/iris_gateway.py`
  WHY IT IS NEEDED: T10a persists `"error"`, and T10b seeds the badge by calling
  `get_local_model_status` — but `_handle_get_local_model_status` (`:8853`) returns
  `mgr.get_status()` VERBATIM, which is LIVE PROCESS STATE ONLY (`loaded: bool`, no
  error field, no `status` key — pinned by
  `test_local_model_status_baseline.py::test_get_local_model_status_response_has_no_status_key`).
  The persisted `"error"` therefore reaches no WS channel the frontend can call, and
  AC3 remains unsatisfied even with T10a AND T10b landed.
  APPROACH (T10b's recommendation, endorsed): push `local_model_status` from
  `_handle_request_state` (`:6720`) — or fold it into `initial_state.field_values` —
  reading `cfg.inference.local_model_status` DIRECTLY. That seam fires on every WS
  open AND reconnect, not just first mount, so it closes AC3 for real and demotes
  T10b's `get_local_model_status` call to a live-state reconciliation backstop.
  RIPPLE: `initial_state` payload shape is consumed by the dashboard's seeding path —
  additive only. Reconcile-to-UNLOADED (REQ-7 edge case) stays with the live check.
  MUST NOT start before T8 releases `backend/iris_gateway.py`.

> **STATUS 2026-08-18 — T5, T6, T7, T8, T10b, T10c landed. 145 tests green.**
> Two DEVIATIONS from the spec text, both deliberate and documented in code —
> confirm or correct them before closing the feature:
>  1. REQ-3 edge case says "free VRAM unreadable -> use the most conservative
>     candidate". T7 instead runs on CPU when VRAM is unreadable, arguing there is
>     no budget to select against. A machine with NO GPU also stays on CPU (a
>     genuinely different case from "does not fit", correctly separated).
>  2. T7's candidate DISCOVERY still walks hardcoded directory names
>     (`LFM2.5-VL-3B` / `-450M`). Size-selection over what it finds is fully
>     VRAM-driven and model-agnostic, but the search paths are not. T7 documents
>     this as inherited and explicitly defers it to **T15**, which must replace the
>     hint list with scanned `has_vision` models to satisfy REQ-10 AC7.
> The `vision:unavailable` frontend case is wired (`hooks/useIRISWebSocket.ts`),
> so the chat system message reaches the user end to end.

## Wave 4.5 — WIRING (the feature is INERT without this)

- [x] **T16 (REQ-2, REQ-3 AC4) — FOUND BY T12, 2026-08-18. THE FEATURE DOES NOT
  RUN WITHOUT IT.** Route the vision consumers THROUGH `resolve_vision_provider()`
  — `backend/automation/vision.py`, `backend/agent/vision_guided_operator.py`,
  `backend/iris_gateway.py:195`, `backend/agent/inference/router.py`
  EVIDENCE: `grep -rn "resolve_vision_provider" backend/ --include=*.py` outside
  tests returns ONLY its own definition and log lines — **zero production callers**.
  All three consumers construct `LFMVLProvider()` directly, so production still
  routes every vision task to tier 3 unconditionally, exactly as before this feature.
  Success criterion #1 ("a multimodal API brain answers a vision task with ZERO local
  model loads") DOES NOT HOLD in the running system, even though the hierarchy is
  implemented and 63 tests pass around it.
  WHY IT WAS MISSED: the Ripple-Effect Map marked the two consumers NO CHANGE
  (verified) on the reasoning that they consume "the resolved endpoint, not the
  resolver" — true, but nothing was ever tasked with making that endpoint COME from
  the resolver. Both rows are now corrected, and a third construction site
  (`iris_gateway.py:195`) was missing from the map altogether.
  ALSO FIX HERE: `resolve_vision_provider()`'s tier-3 `try/except`
  (`router.py` ~699-712) swallows `VisionModelUnavailable` and returns a clean
  `VisionResolution(model_path=None)`. Latent today because nothing calls it — but
  the moment T16 wires it up, the user's "fail loudly" decision (REQ-3 AC4) is
  silently defeated at the hierarchy's own entry point. The VISION_UNAVAILABLE emit
  (AC6) fires either way, so only the raise is lost. Re-raise it.
  GUARD: extend T12's `test_no_fit_fails_loudly_and_emits_full_payload_through_full_hierarchy`
  once the raise propagates, and add a test asserting at least one production caller
  exists — the gap that hid this.

- [x] **T17 (REQ-2) — FOUND BY T16, 2026-08-18**: two MORE vision consumers still
  bypass the hierarchy — `backend/vision/screen_monitor.py:75` and
  `backend/tools/media_tools.py:109` both construct `LFMVLProvider()` directly, so
  they always spawn tier 3 no matter what the bound brain/tool can already do.
  Neither appeared in the original Ripple-Effect Map. Route both through
  `resolve_vision_client()` exactly as T16 did for the other three.
  NOT A BUG IN T16 — they were outside its named consumer list; T16 flagged them
  rather than silently widening its own scope.
  KEEP AS-IS (verified intentional, do not "fix"): `iris_gateway.py:200`
  (`self._vision_provider`) is the deliberate tier-3 fallback default, and
  `lfm_vl_provider.py:290` is the module's own singleton.
  GUARD: extend T16's wiring test so it asserts NO production module outside
  `router.py` / `lfm_vl_provider.py` constructs `LFMVLProvider()` directly except the
  two sanctioned sites above — a grep-shaped contract test. That is the guard which
  would have caught all five bypasses at once, instead of two rounds of discovery.

## Wave 5 — Verification

- [x] **T11 (REQ-1..5)**: Contract tests CT-1, CT-2, CT-4, CT-5 — `backend/tests/contract/`.
  CT-3 is EXTENDED, not created: `tests/contract/test_vision_lease.py` already covers
  lease-blocks-idle-stop, hard expiry, release paths and lease counting; add only the
  `_stop_owned_vision_server` never-kills-an-unowned-PID case
  RIPPLE: CT-2 and CT-4 encode bugs actually observed live (projector-as-model,
  badge section key), turning both into permanent guards.

- [x] **T12 (REQ-2, REQ-3)**: Behavioral tests for all four tier permutations —
  `backend/tests/behavioral/`
  RIPPLE: the multimodal-API-brain case must assert **no** llama-server spawn and
  unchanged free VRAM — the whole point of the feature.

- [x] **T13 (REQ-9)**: Extend the standing CDD harness with a vision-routing replay
  — `scripts/validate_der_*.py`
  RIPPLE: runs every invocation; guards against a future edit collapsing the
  hierarchy back to "always spawn the server".

- [x] **T14 (Open Question) — RESOLVED 2026-08-18 by the user, no longer a gate**:
  the 450M IS good enough for browser control; the user ran it before the 3B upgrade.
  T7's ladder needs NO quality floor and the fast-brain-plus-fallback story stands.

- [ ] **T14b (rescoped) — LIVE PATH CONFIRMATION**: prove the hierarchy routes and
  serves on real hardware. This is a PATH test, not a quality test.
  MUST RUN IN A NEW THREAD — never in the working conversation, and never against an
  invented conversation_id (established user preference).
  Confirm, in order:
   1. Local brain resident + no vision on either binding -> tier 3 fires, and the
      ladder size-selects the 450M because a local model holds the VRAM (REQ-3).
   2. The spawn carries `--fit off` and logs `ttr_sec` — MEASURE IT. This is the
      reported "vision server slow on first request"; T4 is the candidate fix and
      has never been timed on real hardware.
   3. A vision answer actually returns through the tool path (REQ-2 Decisions 2).
   4. Badge reads LOADED after a page reload, and ERROR after a failed load
      (REQ-7 AC2/AC3 — T10a + T10c, never exercised live).
   5. Force the no-fit case and confirm the `vision:unavailable` chat system message
      renders with free VRAM, the smallest requirement and the rejected ladder
      (REQ-3 AC6 — the user's "fail loudly" decision, never seen live).
  Tier 1 / tier 2 (a multimodal brain answering directly, zero local loads) is worth
  confirming too if an API key for a multimodal provider is available.

- [x] **T15 (REQ-10) — COMPLETE** (backend landed before a session crash; AC2 finished by T15b):
  DONE: `cfg.inference.vision_fallback_ladder` (iris_config.py:313/454);
  `_discover_vision_candidates` now sources candidates from
  `LocalModelManager.scan_models()` `has_vision` entries — the hardcoded
  model-family directory walk is GONE (AC1/AC3/AC4/AC5/AC6/AC7, 30 tests green,
  guarded by `test_vision_fallback_ladder_model_agnostic_contract.py`).
  NOT DONE: **AC2 — the frontend surface to SELECT and ORDER the ladder.**
  `components/dashboard/ModelBrowserPanel.tsx` has zero ladder references. Without
  it the ladder can only be set by hand-editing config, which is most of what the
  user actually asked for ("give users a choice"). See T15b.
  BROKE ON LANDING: `scripts/validate_der_vision_routing.py` (T13) stages synthetic
  candidates under the OLD hardcoded directory names, so scan_models-based discovery
  no longer finds them and the harness exits non-zero. T13 flagged this exact
  dependency; T15 was scoped out of `scripts/`, so neither agent could see the other.
  See T13b. NOT a defect in either task — a concurrency seam.

- [x] **T13b — fix the harness fixture broken by T15** — DONE. 32/32, exit 0; wiring
  guard re-proven red via an in-process monkeypatch (no repo edit to stage it).
  ROOT CAUSE WAS NOT THE DIRECTORY NAMES (the initial diagnosis, including mine, was
  wrong). The harness staged every synthetic candidate with the SAME filename
  (`model.gguf`), and `scan_models` dedupes by filename STEM GLOBALLY across the whole
  walk (`seen_bases`, local_model_manager.py:1208/1251) — so the second pair collapsed
  into the first and was counted as a SHARD of it. Fixed by deriving unique filenames
  from the slot directory, matching what the two passing test files already did.
  FINDING SPUN OUT (pre-existing, NOT introduced here, deliberately out of scope):
  that global stem dedupe means two DIFFERENT models in different directories sharing
  a filename silently collapse in production too — and since REQ-10's ladder sources
  candidates from `scan_models` `has_vision` entries, a collision would silently drop a
  configured fallback with only a debug log. Tracked as a separate task.

- [x] **T15b (REQ-10 AC2) — the user-facing half of T15**: ladder selection + ordering
  UI in `components/dashboard/ModelBrowserPanel.tsx`, persisted to
  `cfg.inference.vision_fallback_ladder`. Extend T9's card work in its idiom.

- [ ] ~~T15 original~~ superseded by the two entries above — Frontend surface to select and order the vision fallback
  ladder from scanned `has_vision` models; persist in `cfg.inference`; auto-select
  when unset — `components/dashboard/ModelBrowserPanel.tsx`,
  `backend/iris_config.py`, `backend/tools/lfm_vl_provider.py`
  RIPPLE: consumes T1's `has_vision` metadata, so it needs T1 but nothing else.
  Changes T7's input from a built-in ladder to a configured one — land T7 first,
  then swap its source. Add a contract test asserting no hardcoded GGUF id in the
  fallback path and graceful degradation when configured models are absent.

## Dependency / parallelization notes
- **Wave 0 gates Wave 1.** T0a-T0f must be green against UNCHANGED code before any
  Wave 1 edit lands, otherwise the first four tasks change behavior nothing measures.
  T0a-T0f are themselves fully parallel.
- **Wave 1 is fully parallel.** T3 and T4 are independent of everything; T4 alone
  may resolve the slow-first-vision complaint — land and measure it before Wave 3.
- **T5 needs T2** (the `vision_loaded` field). **T6 needs T5.** **T7 and T8 are
  independent of each other** and may run in parallel once Wave 2 lands.
- **Frontend (T9, T10b) is backend-independent except for T9's payload fields** —
  BUT T10b now depends on T10a (backend `"error"` persistence), which T0e proved is
  missing. T10a is small and independent of everything else, so land it first; T10b
  then runs in parallel with all remaining backend work.
- **NO-CHANGE-verified areas needing only contract tests:** `automation/vision.py`
  and `vision_guided_operator.py` are consumers, not resolvers (evidence in the
  Ripple-Effect Map) — no code change, but CT-3 pins the lease/idle contract they
  depend on.
- **T15 needs only T1**, and de-risks T14: if the 450M proves too weak, the user
  can simply choose a better fallback rather than the ladder needing a quality floor.
- **T14 is a quality gate, not code.** It can run in parallel from day one and
  should, because a negative result changes T7's design.

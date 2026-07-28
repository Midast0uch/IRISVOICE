# Tasks: Local Model Provider Parity + Auto-Optimizing Loader

> Every task links to a requirement and carries a RIPPLE note. Waves are dependency-ordered.
>
> **This spec is gating.** `specs/lfm25-encoder-integration/` needs Wave 2's multi-instance local
> providers (Embedding-350M and ColBERT-350M are local models that must coexist with a local chat
> model). `specs/contextpill-model-switcher/` needs Wave 1's `loaded` status.
>
> Per `CLAUDE.md`: run the QUALITY CHECK before every test run; a test's **inputs** are part of the
> test; when a test and this spec genuinely conflict, **report — do not reconcile**.

---

## Wave 0 — Baseline

- [ ] **T0.1** Record the current-state baseline: `pytest backend/tests -q` counts, and a manual
  note of what the local path does today (bind-before-load rejected, one `"local"` slot, fixed
  32k context). Write both into "Baseline record" below.
  RIPPLE: nothing modified. Without it, REQ-3's "no regression" and the Wave 5 close-out are
  unverifiable, and a pre-existing failure gets misattributed to this spec.

- [ ] **T0.2** Capture a reference model set for the deriver: at least one small (<4B), one mid
  (7–14B), and one large (>27B) GGUF from the configured folder, with their parsed metadata
  (`parse_gguf_metadata`) saved to `backend/tests/fixtures/local_model_metadata.json`.
  RIPPLE: consumed by `test_config_deriver.py` and harness assertion 4. Real metadata, not
  invented — a deriver validated against fabricated params proves nothing about real models.

### Baseline record
<!-- T0.1 fills this in -->

---

## Wave 1 — Declarative providers (REQ-1, REQ-3)

> Land as one change. A declarative provider with a per-kernel registry still diverges between
> `/api/inference/state` and the WS session.

- [ ] **T1.1** (REQ-1 AC2) Extend `ProviderInstance` with `loaded: bool`, `loading: bool`,
  `purpose: str = "chat"`, `active_config: Optional[dict]`. Keep `to_dict()` **additive**.
  RIPPLE: `ModelInferenceSection.tsx` consumes this payload and must keep working **unmodified**
  (CT-L1, CT-L6). Rendering the new fields belongs to `contextpill-model-switcher`, not here.

- [ ] **T1.2** (REQ-3) Move `ProviderRegistry` + `RoleBindingTable` to a process-wide singleton
  with a `threading.Lock`. Preserve `InferenceRouter`'s public surface exactly
  (`resolve` / `generate` / `snapshot` / `bind_role`).
  RIPPLE: read from the DER executor thread and written from the WS handler — same concurrency
  shape as the phase registry. ⚠️ **`InferenceRouter.generate()` carries the phase-scheduler gate
  call** (`caducean-phase-scheduler` REQ-13). Do not drop it while refactoring; **CT-L5** pins it.

- [ ] **T1.3** (REQ-3 AC3) Delete the peer-kernel fan-out loop at
  [`iris_gateway.py:7910`](backend/iris_gateway.py:7910) and the two sibling loops its comment
  names (`set_model_selection`, `set_role_binding`).
  RIPPLE: **delete, do not extend.** The comment documents the bug it patches —
  `/api/inference/state` reads the `"default"` kernel while the WS session uses another. One
  registry removes the class; a fourth copy of the workaround does not.

- [ ] **T1.4** (REQ-1 AC1) Add `local_providers: List[LocalProviderConfig]` to `iris_config`, and
  register them in `InferenceRouter._apply_config` at init — **before any load**. Migrate the
  existing flat `local_model_path` / `local_model_id` fields into a single entry.
  RIPPLE: this is D-1, the inversion the whole spec rests on. Existing configs must migrate
  silently; a user who has a local model configured today must not have to reconfigure it.

- [ ] **T1.5** (REQ-1 AC6) Convert the binding guard at
  [`iris_gateway.py:8580`](backend/iris_gateway.py:8580) from a **veto** into a **status flag**.
  Binding to a configured-but-unloaded local provider succeeds.
  RIPPLE: `role_binding_error` message shape is unchanged (CT-L6) — it is still emitted for
  genuinely invalid bindings (unknown instance, missing role). Only the not-loaded case stops
  being an error.

- [ ] **T1.6** (REQ-1 AC1/AC5) Stop **creating** the instance in the load handler at
  [`iris_gateway.py:7896`](backend/iris_gateway.py:7896); flip `loaded`/`loading` on the existing
  registered instance instead.
  RIPPLE: this is the line that makes local a side effect. After this, loading is a state
  transition and bindings survive restart because the provider no longer depends on a load having
  happened.

- [ ] **T1.7** (REQ-1, REQ-3) Tests — write **before** T1.1–T1.6:
  - `backend/tests/behavioral/test_bind_before_load.py` — configure, bind, never load; binding
    succeeds. **Fails today.**
  - `backend/tests/behavioral/test_binding_survives_restart.py` — REQ-1 AC5.
  - `backend/tests/contract/test_provider_payload_contract.py` — CT-L1, CT-L6.
  - `backend/tests/contract/test_registry_single_source.py` — CT-L3.
  RIPPLE: `test_bind_before_load` failing against current code is the acceptance evidence for
  Wave 1. Record that pre-fix failure via `record_test(..., outcome='fail', ...)`.

---

## Wave 2 — Multi-instance local ids (REQ-2)

> Unblocks `lfm25-encoder-integration`.

- [ ] **T2.1** (REQ-2 AC1) Namespace local ids as `local:<model-stem>`. Add the `purpose` field to
  distinguish `chat` / `embedding` / `rerank` instances.
  RIPPLE: `purpose` is what lets Embedding-350M and ColBERT register without competing for
  `reasoning` / `tool_execution` bindings (REQ-2 AC3).

- [ ] **T2.2** (REQ-2 AC4) Migrate **every** site matching the literal `"local"` as a provider id,
  in this same change:
  [`iris_gateway.py:7896`](backend/iris_gateway.py:7896),
  [`:8580`](backend/iris_gateway.py:8580),
  [`agent_kernel.py:962`](backend/agent/agent_kernel.py:962),
  [`:8476`](backend/agent/agent_kernel.py:8476),
  [`:8544`](backend/agent/agent_kernel.py:8544).
  RIPPLE: ⚠️ **A partial migration is worse than none** — a persisted binding referencing `"local"`
  against a registry holding `local:qwen3-9b` is dead **and looks configured in the UI**. Grep for
  the literal after the change and confirm zero remaining provider-id uses (CT-L2). Note
  `agent_kernel.py:689-690` (`node_id="local"`, `origin="local"`) are **memory** fields, not
  provider ids — leave them.

- [ ] **T2.3** (REQ-2 AC4) Handle the context-window table at
  [`agent_kernel.py:926-931`](backend/agent/agent_kernel.py:926), keyed `("local", <model>)`.
  RIPPLE: ⚠️ **Highest-risk silent failure in this wave.** `resolve_context_window` feeds
  `DER_WORK_UNITS_0 = context_window / AVG_STEP_COST`, which is the DER loop's termination
  resource. If the lookup silently misses after renaming, the DER token budget changes and nothing
  errors. **CT-L7** pins the resolved value per model across the migration.

- [ ] **T2.4** (REQ-2 AC5, D-2) Migrate persisted bindings referencing bare `"local"`: resolve to
  the single configured local instance when exactly one exists; otherwise surface as **unresolved**
  rather than silently choosing.
  RIPPLE: silently picking one would reintroduce the invisible-wrong-provider failure REQ-1 AC4
  exists to prevent.

- [ ] **T2.5** (REQ-2) Tests:
  - `backend/tests/behavioral/test_two_local_models.py` — two local instances bound to the two
    roles simultaneously, each serving its own. **Impossible today** — the headline assertion.
  - `backend/tests/contract/test_local_id_namespacing.py` — CT-L2.
  - `backend/tests/contract/test_context_window_stable.py` — CT-L7.

---

## Wave 3 — Auto-optimizing loader (REQ-4, REQ-5, REQ-7)

- [ ] **T3.1** (REQ-4 AC3) Fix `estimate_vram_gb`
  ([`local_model_manager.py:906`](backend/agent/local_model_manager.py:906)) to include **KV cache
  at the target context** alongside weights.
  RIPPLE: ⚠️ **Do this first.** Today's formula (`params_b × bpw / 8 × 1.1`) is
  **context-independent**, so it cannot rank one context against another — the whole D-3 search is
  meaningless until this changes. `test_vram_estimate_includes_kv` fails against current code by
  design.

- [ ] **T3.2** (REQ-4 AC1/AC2) Implement `ConfigDeriver`: walk `CTX_LADDER` downward; for each,
  estimate VRAM (T3.1) and throughput; select the **largest** context predicted to clear
  `TARGET_TPS` (25).
  RIPPLE: replaces `recommend_profile`'s two-outcome preset selection
  ([`:930-948`](backend/agent/local_model_manager.py:930)). Keep `PROFILES` as user-selectable
  overrides (REQ-4 AC4) — and keep `balanced_mtp` / `force_subprocess` reachable so MTP
  speculative decoding does not regress. Q1: the initial throughput estimate only needs to rank
  candidates; REQ-6's loop corrects the constant after one real load.

- [ ] **T3.3** (REQ-5) Implement the degradation ladder — context → GPU layers → batch — retrying
  the load at each step, with `MIN_CTX` as the floor.
  RIPPLE: this **reverses** a deliberate policy. The comment at
  [`:941-946`](backend/agent/local_model_manager.py:941) chose rejection on purpose ("rather than
  silently falling back to CPU"). It is correct for a fixed deployment and wrong for Decision
  Locked #3. Degradation must be **reported**, not silent (REQ-5 AC2) — that addresses the concern
  behind the original policy.

- [ ] **T3.4** (REQ-7) Implement `ConfigCache` at `.mcm/local_model_configs.json`: fingerprint on
  path+size+mtime, `hw_fingerprint` invalidation, corrupt-file tolerance.
  RIPPLE: follows the `outer_loop._load_params` pattern (`.mcm/der_params.json`,
  `provider_ceilings.json`). A stale config against a swapped model file is exactly the
  inconsistency this spec exists to remove — AC2's fingerprint is what prevents it.

- [ ] **T3.5** (REQ-4, REQ-5) Wire `load_model` to consume `DerivedConfig` and drive the
  degradation retry loop.
  RIPPLE: `_parse_load_progress` is untouched (NO CHANGE, verified) — progress phases are
  orthogonal to configuration choice.

- [ ] **T3.6** (REQ-8) Symlink traversal + dedupe + `SCAN_MAX_DEPTH` in `scan_models`.
  RIPPLE: the user's models live in a **symlinked HF cache**, so without AC1 the primary source is
  invisible. Preserve split-shard grouping ([`:670-680`](backend/agent/local_model_manager.py:670)).
  Dedupe matters because a model reachable via both symlink and real path would otherwise register
  twice under different ids.

- [ ] **T3.7** Tests:
  - `backend/tests/unit/test_vram_estimate_includes_kv.py` — estimate increases with context.
  - `backend/tests/unit/test_config_deriver.py` — small/mid/large from T0.2 yield **three
    different** contexts.
  - `backend/tests/unit/test_degradation_order.py` — ctx before layers before batch.
  - `backend/tests/unit/test_config_cache.py` — fingerprint, hw invalidation, corrupt tolerance.
  - `backend/tests/behavioral/test_degrades_not_rejects.py`,
    `test_unseen_model_autotunes.py`.

---

## Wave 4 — Close the throughput loop (REQ-6, REQ-9)

- [ ] **T4.1** (REQ-6 AC1) Replace the hardcoded 8 tok/s threshold in `record_tps`
  ([`:1189`](backend/agent/local_model_manager.py:1189)) with `TARGET_TPS` (25, env-overridable).

- [ ] **T4.2** (REQ-6 AC2/AC3) Write corrections to `ConfigCache`: sustained below target →
  reduced context next load; comfortably above with headroom → increased. Apply `TPS_DEADBAND`
  (0.15) so a measurement near target records nothing.
  RIPPLE: ⚠️ This is the **fourth** compute-and-discard in this codebase (see
  `docs/CADUCEAN_ARCHITECTURE.md` §10 rule 1). tok/s is measured, logged, and never acted on.
  `test_closed_loop_tuning` must assert the **next-load config changed** — not merely that a
  warning was emitted, which is what passes today.

- [ ] **T4.3** (REQ-6 AC4) Corrections apply at **next load only**; never reconfigure a running
  model.
  RIPPLE: a tight loop would reload mid-conversation. Same reasoning as the outer loop tuning
  physics constants between sessions rather than within one. The test must assert the running
  config was untouched.

- [ ] **T4.4** (REQ-6 edge case) Attribute measurements with prompt length so one huge prompt does
  not trigger a spurious correction.

- [ ] **T4.5** (REQ-9) Observability: one structured line per load (fingerprint, config source,
  chosen params, est VRAM, predicted tps); a line per degradation step; a line per correction.
  Expose local-provider state via the read-only debug surface.
  RIPPLE: extend `/api/debug/caducean` with a `local_models` section, or add a sibling endpoint —
  the same read-only, side-effect-free discipline (it must not trigger a load).

- [ ] **T4.6** Tests: `test_tps_correction.py` (unit), `test_closed_loop_tuning.py` (behavioral).

---

## Wave 5 — Harness + close-out

- [ ] **T5.1** Create `scripts/validate_local_model_path.py` with all eight assertions from
  design.md.
  RIPPLE: **assertion 4 is the one that decides whether REQ-4 landed** — three model sizes must
  yield three different contexts. Identical contexts mean presets are still in charge under a new
  name. Assertion 8 guards MTP against regression.

- [ ] **T5.2** Full verification: `pytest backend/tests -q` plus all five `validate_*` harnesses.
  Zero new failures vs the T0.1 baseline. Record the numbers in this file.

- [ ] **T5.3** Manual verification (this path cannot be fully proven by tests):
  - Load three **different real** models from the symlinked HF folder; confirm each gets a
    context appropriate to its size and sustains **≥25 tok/s**.
  - Bind two different local models to `reasoning` and `tool_execution`; confirm both serve.
  - Restart; confirm bindings survive.
  - Load an oversized model; confirm it **degrades** rather than being rejected.

- [ ] **T5.4** MCM anchoring: `record_test` per new test file, `pin_add`,
  `mcm_define_feature(name='local_model_provider_parity', seed_files=[...])`,
  `mcm_crystallize_landmark`, `mcm_compress`.

- [ ] **T5.5** Update `docs/CADUCEAN_ARCHITECTURE.md` §9 with the local provider path and its
  status, and `bootstrap/GOALS.md` with a Domain 22 entry.

---

## Dependency / parallelization notes

**Hard sequencing:**

- **T0.1 / T0.2 gate everything.** T0.2 especially — the deriver cannot be validated against
  invented metadata.
- **Wave 1 lands as one change.** Declarative providers with a per-kernel registry still diverge.
- **T1.7 tests before T1.1–T1.6.** `test_bind_before_load` failing is the acceptance evidence.
- **T3.1 before T3.2.** A context-independent VRAM estimate makes the search meaningless.
- **Wave 2 before `lfm25-encoder-integration` starts** — that spec needs `purpose` and multi-instance ids.
- **Wave 1 before `contextpill-model-switcher`** — that spec needs `loaded`.

**Parallelizable:**

- Wave 3's T3.6 (scanning) is independent of T3.1–T3.5 (derivation) — different functions.
- Wave 4's T4.5 (observability) can be written at any point.
- All test-writing precedes its implementation task.

**Riskiest tasks:**

1. **T2.3 — the context-window table.** Silent failure: `resolve_context_window` misses, the DER
   token budget changes, nothing errors. CT-L7 exists solely for this.
2. **T2.2 — partial id migration.** A binding referencing the old literal is dead *and looks
   configured*. Grep for the literal afterward.
3. **T1.2 — the phase-gate call inside `InferenceRouter.generate()`.** Easy to drop while
   refactoring the registry; CT-L5 pins it.
4. **T3.3 — reversing the GPU-only policy.** It was a deliberate choice; the reversal is only safe
   because degradation is *reported* (REQ-5 AC2). Do not make it silent.
5. **T4.2 — asserting the correction, not the warning.** The current code already warns; a test
   that checks for a warning would pass without the loop being closed.

### Baseline record
<!-- T5.2 fills this in -->

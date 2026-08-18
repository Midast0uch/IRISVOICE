# Tasks: Unified Vision Capability Routing

> Each task links to a requirement. Waves group work that can proceed in parallel.
> RIPPLE notes name what else the task touches or relies on.

## Wave 1 — Foundation (no behavior change yet; all parallel)

- [ ] **T1 (REQ-5)**: Exclude `mmproj-*.gguf` from `scan_models`; attach each
  projector to its base model as `has_vision` / `mmproj_path` / `mmproj_size_gb`,
  matched by stem — `backend/agent/local_model_manager.py`
  RIPPLE: `/api/models` payload shape → `ModelBrowserPanel.tsx` reads it (T9);
  removes 3 of 18 rows, so any test asserting a model count changes. Locked by CT-2.

- [ ] **T2 (REQ-1)**: Add `vision_loaded: bool` to `ProviderInstance` and a
  `(provider_id, model_substring)` vision table mirroring `_KNOWN_CONTEXT_WINDOWS`
  — `backend/agent/inference/provider.py`, `backend/agent/agent_kernel.py`
  RIPPLE: `ProviderInstance.to_dict()` feeds `provider_added` and the inference
  snapshot → ModelSwitcher; new field must be additive. Locked by CT-1.

- [ ] **T3 (REQ-8)**: Derive the migrated local ProviderEntry endpoint from
  `LocalModelManager.PORT` instead of the hardcoded `8081`
  — `backend/iris_config.py:382`
  RIPPLE: touches config migration, which runs on every load; a wrong port here
  sends a migrated binding at the vision server. Independent of all other tasks.

- [ ] **T4 (REQ-6)**: Pass `--fit off` plus explicit `--ctx-size` /
  `--n-gpu-layers` / `--batch-size` when spawning the vision server; log
  time-to-ready — `backend/tools/lfm_vl_provider.py`
  RIPPLE: mirrors the fix already in `local_model_manager._build_server_cmd`
  (e9d2fc89). Likely resolves the reported slow first vision request on its own,
  so land it early and measure before the rest.

## Wave 2 — Capability resolution (T5 depends on T2)

- [ ] **T5 (REQ-1)**: Implement `supports_vision(instance)` covering API (table),
  LOCAL_OPENAI/INPROCESS (`vision_loaded`, NOT disk presence), OLLAMA
  (`/api/show`); unknown → False — `backend/agent/inference/router.py`
  RIPPLE: needs T2's field. Must not raise for an unrecognised kind — CT-1.

- [ ] **T6 (REQ-2, REQ-9)**: Implement `resolve_vision_provider()` — brain → tool
  → fallback, returning a `VisionResolution`; log tier, provider, whether a load is
  required and free VRAM — `backend/agent/inference/router.py`
  RIPPLE: depends on T5. Calls `router.resolve()`, which raises on unbound roles —
  must swallow and continue. Consumed by T7.

## Wave 3 — Fallback and projector loading (parallel after Wave 2)

- [ ] **T7 (REQ-3, REQ-9)**: Replace the unconditional 3B preference with
  size-selection over a widest-first ladder (3B → 450M) against real free VRAM,
  adding projector size to the weights term and preserving
  `_VISION_VRAM_RESERVE_GB`; log the ladder and each rejection
  — `backend/tools/lfm_vl_provider.py:277-299`
  RIPPLE: reuses `get_hardware_info()` (nvidia-smi, true free VRAM) and
  `estimate_vram_gb(file_size_gb=…)` from e9d2fc89. Must not disturb lease /
  idle-stop / owned-PID lifecycle — CT-3.

- [ ] **T8 (REQ-4)**: Pass `--mmproj` in `_build_server_cmd` when the base model
  has a projector; add `with_projector` to the load path; include projector size in
  pre-flight and in `plan_load`; set `vision_loaded` on the registered provider
  — `backend/agent/local_model_manager.py`, `backend/iris_gateway.py`
  RIPPLE: changes the VRAM budget for every multimodal model, so `plan_load`
  output on the card shifts (T9). `load_local_model` must still accept payloads
  without `with_projector` — CT-5. Sets the field T5 reads.

## Wave 4 — Frontend (parallel with Wave 3; only T9 needs T1/T8)

- [ ] **T9 (REQ-4 AC5, REQ-5 AC3)**: Show vision capability on the model card and
  the measured projector cost (−35% generation, +1.2GB on gemma-4-E4B); allow
  loading without the projector — `components/dashboard/ModelBrowserPanel.tsx`
  RIPPLE: consumes T1's `has_vision` and T8's `with_projector`. The card already
  renders a two-row plan (e9d2fc89) — extend, do not restructure.

- [ ] **T10 (REQ-7)**: Seed the MODEL STATUS badge from the backend's persisted
  `inference.local_model_status` at dashboard mount, and reconcile to UNLOADED when
  nothing is listening — `hooks/useIRISWebSocket.ts`,
  `components/dark-glass-dashboard.tsx`
  RIPPLE: the WS bucket half is already fixed (e9d2fc89, writes
  `local-model-card`); this is the SEEDING half only. Locked by CT-4.

## Wave 5 — Verification

- [ ] **T11 (REQ-1..5)**: Contract tests CT-1..CT-5 — `backend/tests/contract/`
  RIPPLE: CT-2 and CT-4 encode bugs actually observed live (projector-as-model,
  badge section key), turning both into permanent guards.

- [ ] **T12 (REQ-2, REQ-3)**: Behavioral tests for all four tier permutations —
  `backend/tests/behavioral/`
  RIPPLE: the multimodal-API-brain case must assert **no** llama-server spawn and
  unchanged free VRAM — the whole point of the feature.

- [ ] **T13 (REQ-9)**: Extend the standing CDD harness with a vision-routing replay
  — `scripts/validate_der_*.py`
  RIPPLE: runs every invocation; guards against a future edit collapsing the
  hierarchy back to "always spawn the server".

- [ ] **T14 (Open Question)**: Evaluate LFM2.5-VL-450M quality on real browser and
  desktop control tasks — **blocks shipping T7**
  RIPPLE: the 450M becomes the default whenever a local brain is resident. If it is
  not good enough, T7's ladder needs a quality floor and the whole
  fast-brain-plus-fallback story changes.

## Dependency / parallelization notes
- **Wave 1 is fully parallel.** T3 and T4 are independent of everything; T4 alone
  may resolve the slow-first-vision complaint — land and measure it before Wave 3.
- **T5 needs T2** (the `vision_loaded` field). **T6 needs T5.** **T7 and T8 are
  independent of each other** and may run in parallel once Wave 2 lands.
- **Frontend (T9, T10) is backend-independent except for T9's payload fields**, so
  T10 can start immediately and in parallel with all backend work.
- **NO-CHANGE-verified areas needing only contract tests:** `automation/vision.py`
  and `vision_guided_operator.py` are consumers, not resolvers (evidence in the
  Ripple-Effect Map) — no code change, but CT-3 pins the lease/idle contract they
  depend on.
- **T14 is a quality gate, not code.** It can run in parallel from day one and
  should, because a negative result changes T7's design.

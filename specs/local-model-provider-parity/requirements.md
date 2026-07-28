# Requirements: Local Model Provider Parity + Auto-Optimizing Loader

## Decisions Locked

Resolved with the user on 2026-07-28. Do **not** re-litigate.

1. **Local providers must be first-class in the mix-and-match model.** The frontend lets a user
   configure multiple API providers and bind `reasoning` (Brain) and `tool_execution` (Tool) to
   any combination. Local models must join that on equal terms — including *two different local
   models* bound to the two roles.
2. **Throughput target: ≥25 tok/s, maximizing context.** The loader's job is to find the largest
   context window that still sustains ≥25 tok/s for the model actually loaded, on the hardware
   actually present. Not to apply a preset tuned for a different model.
3. **The user swaps models frequently.** Auto-recognition and auto-tuning are the feature, not a
   convenience. A model the user has never loaded before must work without hand-tuning.
4. **Model discovery is folder-based and user-configurable.** A symlinked Hugging Face cache
   holds the models; the frontend can point the backend at any folder to scan.
5. **This spec is gating.** `specs/lfm25-encoder-integration/` needs multi-instance local
   providers (Embedding-350M and ColBERT-350M are additional local models that must coexist with
   a local chat model), and `specs/contextpill-model-switcher/` needs a truthful provider list.

## Introduction

The API-provider path works: a user pastes a key, the provider exists, roles bind to it, and it
survives restart. The local path does none of those things reliably — and the reason is
structural, not a bug.

**A local provider is created as a side effect of loading a model; an API provider is created by
configuring one.** Everything else follows from that asymmetry.

Separately, the loader does not do what its own profile table claims. Profiles are static presets
tuned for one reference model on one GPU, throughput is measured but never fed back, and a model
too large for VRAM is rejected rather than degraded.

### Success criteria

- A local provider appears in the registry from **configuration**, before any model is loaded,
  with an explicit `loaded` status — exactly as an API provider appears from a pasted key.
- **Two different local models** can be bound to `reasoning` and `tool_execution` simultaneously.
- A role bound to a local provider **survives restart** — no dead bindings.
- Loading a model the user has never used before selects parameters that sustain **≥25 tok/s**
  at the **largest context that fits**, verified by measurement rather than by preset.
- A model too large for available VRAM **degrades** (fewer GPU layers / smaller context) instead
  of being rejected outright.
- Measured throughput **changes subsequent load parameters** for that model — the loop closes.
- `/api/inference/state` and the WS session see the **same** provider registry; the per-kernel
  fan-out loop is deleted, not extended.

## Requirements

---

### REQ-1: Local providers are declarative, not a side effect of loading

**User Story:** As a user I want to configure a local model the same way I configure an API
provider, so that binding a role to it does not depend on what I did first.

**Verified:** REAL GAP — the local `ProviderInstance` is constructed **inside the model-load
handler** at [`iris_gateway.py:7896`](backend/iris_gateway.py:7896), so it does not exist until a
load succeeds. The binding guard at
[`iris_gateway.py:8580`](backend/iris_gateway.py:8580) then rejects any attempt to bind a role:
`if instance_id == "local" and _router.registry.get("local") is None`. An API provider, by
contrast, is registered from config at router init
([`router.py:_apply_config`](backend/agent/inference/router.py)).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL register a local provider instance from **configuration**, at router
  init, independent of whether any model is currently loaded.
- AC2: THE SYSTEM SHALL expose a `loaded: bool` (and `loading: bool`) status on local provider
  instances, so a configured-but-unloaded model is representable rather than absent.
- AC3: THE SYSTEM SHALL permit binding a role to a configured local provider **before** its
  model is loaded; the binding is valid and takes effect once loading completes.
- AC4: WHEN a role is bound to a local provider whose model is not loaded AND a request arrives
  for that role THEN THE SYSTEM SHALL either load it on demand or fail with a typed, actionable
  error — and SHALL NOT silently fall back to a different provider.
- AC5: THE SYSTEM SHALL persist local provider configuration so bindings survive a restart.
- AC6: THE SYSTEM SHALL NOT reject a role binding solely because a model is not yet loaded
  (superseding the `iris_gateway.py:8580` guard, which becomes a status flag rather than a veto).

**Edge Cases:**
- Configured local model whose file has been deleted → provider present, `loaded: false`, and a
  load attempt reports "file not found" rather than a generic failure.
- Role bound to local, app restarts, model not auto-loaded → binding intact, status unloaded;
  first request triggers AC4.
- Two roles bound to the same local instance → one model serves both (current behavior preserved).

---

### REQ-2: Local providers are multi-instance, addressed by distinct ids

**User Story:** As a user I want a fast small local model for tool execution and a larger one for
reasoning, so that local participates fully in mix-and-match.

**Verified:** REAL GAP — the id is the hardcoded literal `"local"`
([`iris_gateway.py:7896`](backend/iris_gateway.py:7896)), and the binding guard matches on that
same literal ([`:8580`](backend/iris_gateway.py:8580)). There is therefore exactly **one** local
slot in the entire registry, forever.

This also blocks `specs/lfm25-encoder-integration/`: Embedding-350M and ColBERT-350M are
additional **local** models that must coexist with a local chat model. Under a single `"local"`
id they cannot.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL identify each local provider by a distinct, stable id derived from the
  model (e.g. `local:<model-stem>`), not by a shared literal.
- AC2: THE SYSTEM SHALL support **at least two** local instances registered and bound
  simultaneously to different roles.
- AC3: THE SYSTEM SHALL support local instances whose purpose is not chat (embedding, reranking),
  registered alongside chat models without competing for the same role bindings.
- AC4: THE SYSTEM SHALL keep any code path that matches the literal string `"local"` working
  during migration, or migrate every such path in the same change — a partially-migrated id is a
  dead binding.
- AC5: WHERE hardware cannot hold two models simultaneously THEN THE SYSTEM SHALL report that
  as a capacity condition at bind or load time, and SHALL NOT silently unload the other model.

**Edge Cases:**
- Same GGUF file configured twice under different ids → allowed; they are distinct instances that
  may carry different profiles.
- An id colliding with an API preset id (`openai`, `cerebras`) → local ids are namespaced so
  collision is impossible.
- Existing persisted bindings referencing the old literal `"local"` → migrated on load, not
  dropped.

---

### REQ-3: One process-wide provider registry

**User Story:** As a maintainer I want provider state to live in one place, so that the API
endpoint and the WebSocket session cannot disagree about which models exist.

**Verified:** REAL GAP — provider registration is fanned out across **every peer kernel's**
router in a loop at [`iris_gateway.py:7910`](backend/iris_gateway.py:7910), with a code comment
stating that `/api/inference/state` reads the `"default"` kernel which "may differ from the WS
session kernel — without peer propagation the local model never appears in the Brain/Tool
dropdowns." The fan-out is a workaround for per-kernel registries, and the comment notes the same
pattern was already applied twice elsewhere (`set_model_selection`, `set_role_binding`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL hold provider instances and role bindings in a single process-wide
  registry, not per-kernel.
- AC2: THE SYSTEM SHALL make `/api/inference/state` and the WebSocket session read the **same**
  registry, so their views cannot diverge.
- AC3: THE SYSTEM SHALL delete the peer-kernel fan-out loops rather than extend them.
- AC4: THE SYSTEM SHALL preserve `InferenceRouter`'s existing public surface
  (`resolve`, `generate`, `snapshot`, `bind_role`) so callers are unaffected.
- AC5: THE SYSTEM SHALL keep registry access thread-safe — it is read from the DER executor
  thread and written from the WS handler.

**Edge Cases:**
- A kernel created after registration → sees the shared registry immediately, with no propagation
  step.
- Concurrent bind from two clients → last write wins, both observe the same final state.

---

### REQ-4: Load parameters are derived from the model and the hardware

**User Story:** As a user who swaps models constantly I want the loader to work out the right
settings for whatever model I picked, so that I do not hand-tune every time.

**Verified:** REAL GAP — `PROFILES` are **static presets**
([`local_model_manager.py:92-140`](backend/agent/local_model_manager.py:92)). `balanced`
hardcodes `n_ctx = 32768`, `n_batch = 2048`, `n_gpu_layers = -1`, and its own comment says
*"VERIFIED: 45+ tok/s on RTX 3070 8GB with Qwen3.5-9B-Q3_K_S"* — tuned for one model on one GPU.
`recommend_profile` ([`:930-948`](backend/agent/local_model_manager.py:930)) computes
`vram_needed` but produces only **two** outcomes (`performance` if tight, else `balanced`) and
never adjusts `n_ctx` or `n_gpu_layers` to the model in hand.

Consequence: a small model is capped at 32k when it could hold far more, and a large model is
pushed at settings that do not fit.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL derive `n_ctx`, `n_gpu_layers`, and `n_batch` from the **parsed model
  metadata** (already available via `parse_gguf_metadata`) and **measured hardware**
  (`get_hardware_info`), rather than selecting a fixed preset.
- AC2: THE SYSTEM SHALL maximize context subject to the throughput floor: choose the **largest**
  `n_ctx` predicted to sustain ≥`TARGET_TPS` (default 25) for this model on this hardware.
- AC3: THE SYSTEM SHALL account for KV-cache size at the chosen context and quantization when
  estimating VRAM, not model weights alone — `estimate_vram_gb`
  ([`:906`](backend/agent/local_model_manager.py:906)) currently models weights only
  (`params_b × bpw / 8 × 1.1`), which understates usage at long context.
- AC4: THE SYSTEM SHALL retain the named profiles as **user-selectable overrides**; automatic
  derivation is the default, not a replacement for explicit control.
- AC5: WHERE the user has set an explicit profile or custom parameters THEN THE SYSTEM SHALL
  honor them and SHALL NOT silently re-derive.

**Edge Cases:**
- Model metadata unparseable → fall back to the current `balanced` preset and log why, rather
  than failing the load.
- Hardware probe unavailable (no CUDA) → derive CPU-appropriate parameters; see REQ-5.
- A model whose minimum viable context still misses the target → REQ-5's degradation path.

---

### REQ-5: Degrade rather than reject

**User Story:** As a user I want a too-large model to load slower rather than not at all, so that
switching models never dead-ends.

**Verified:** REAL GAP — the policy is explicit in the code comment at
[`local_model_manager.py:941-946`](backend/agent/local_model_manager.py:941): *"GPU-ONLY policy:
never recommend the CPU 'eco' profile... let the pre-flight check reject the load if VRAM is truly
insufficient — rather than silently falling back to CPU."* Rejection is intentional today; with
frequent model-swapping it is the wrong default.

**Acceptance Criteria:**
- AC1: WHEN a model does not fit at the derived parameters THEN THE SYSTEM SHALL reduce context
  first, then GPU layers, then batch size — in that order — until it fits.
- AC2: THE SYSTEM SHALL report the degradation to the user with the reason and the resulting
  expected throughput, rather than degrading silently.
- AC3: THE SYSTEM SHALL only fail a load when no viable configuration exists at all.
- AC4: THE SYSTEM SHALL keep a floor on context (`MIN_CTX`, default 4096) below which it reports
  the model as unusable on this hardware rather than loading it uselessly.
- AC5: WHERE the resulting configuration falls below `TARGET_TPS` THEN THE SYSTEM SHALL load it
  anyway and surface the expected rate — the target is a goal, not a hard gate.

**Edge Cases:**
- CPU-only machine → degradation ends at a CPU configuration; the GPU-only policy no longer
  blocks it.
- Model larger than total system RAM → AC3 failure with a specific message.
- VRAM freed by another process mid-degradation → the search uses one hardware snapshot; it does
  not need to be re-entrant.

---

### REQ-6: Close the throughput loop

**User Story:** As the loader I want measured throughput to change what I do next time, so that
tuning improves with use instead of only producing warnings.

**Verified:** REAL GAP — `record_tps`
([`local_model_manager.py:1189-1234`](backend/agent/local_model_manager.py:1189)) maintains a
3-sample window, and on sustained slowness it logs a warning and spawns a subprocess to write a
note to the coordinate graph. It **never adjusts** `n_ctx`, `n_gpu_layers`, `n_batch`, or the
profile. Its threshold is **8 tok/s** (GPU), not the 25 this spec targets.

Measured, logged, never acted on — the same compute-and-discard pattern recorded three times in
`docs/CADUCEAN_ARCHITECTURE.md` §10 rule 1.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL use `TARGET_TPS` (default 25, configurable) as the throughput target,
  replacing the current 8 tok/s warning threshold.
- AC2: WHEN measured throughput for a loaded model is sustained below `TARGET_TPS` THEN THE
  SYSTEM SHALL record a corrected configuration for that model, to be applied on its **next**
  load — reducing context before reducing GPU layers.
- AC3: WHEN measured throughput is comfortably above target with context headroom remaining THEN
  THE SYSTEM SHALL record an increased context for the next load, so the search converges upward
  as well as downward.
- AC4: THE SYSTEM SHALL NOT change parameters of a **currently loaded** model in response to
  measurements — corrections apply at next load, so a running session is never disrupted.
- AC5: THE SYSTEM SHALL keep the existing coordinate-graph note as observability, but SHALL NOT
  treat writing it as the response to degradation.

**Edge Cases:**
- Throughput low because the *prompt* was huge, not because config is wrong → measurements are
  attributed with context length so a single long prompt does not trigger a correction.
- Model unloaded before 3 samples accumulate → no correction recorded; insufficient evidence.
- Oscillation between two contexts across loads → damped by requiring a minimum step and a
  stable-state deadband.

---

### REQ-7: Per-model learned configuration cache

**User Story:** As a user who returns to the same models repeatedly I want the loader to remember
what worked, so that the second load of a model is immediate and correct.

**Verified:** NEW (unverified — implementation pending). No per-model persisted configuration
exists; `load_model_settings` ([`:2095`](backend/agent/local_model_manager.py:2095)) holds global
settings only, so the derivation in REQ-4 would repeat from scratch on every load.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL persist, per model fingerprint, the last known-good configuration and its
  measured throughput.
- AC2: THE SYSTEM SHALL key the cache on a fingerprint that changes when the model file changes
  (path + size + mtime, or a metadata hash) so a replaced file is not loaded with stale settings.
- AC3: WHEN a cached configuration exists THEN THE SYSTEM SHALL use it as the starting point and
  SHALL NOT re-derive from scratch.
- AC4: THE SYSTEM SHALL invalidate a cached configuration when the hardware profile changes
  (different GPU, materially different free VRAM).
- AC5: THE SYSTEM SHALL tolerate a corrupt or missing cache file by falling back to derivation,
  following the `outer_loop._load_params` pattern.

**Edge Cases:**
- Same model on a machine with a different GPU → AC4 invalidation.
- Cache file hand-edited to an invalid config → validated on read; invalid entries discarded.
- First-ever load of a model → no cache, derive per REQ-4, then populate.

---

### REQ-8: Model discovery over a user-configured folder

**User Story:** As a user I want to point IRIS at my Hugging Face cache and have it find every
model I have, so that I do not maintain a separate model directory.

**Verified:** PARTIAL — `scan_models` already walks `effective_models_dir` with
`rglob("*.gguf")` and groups split shards
([`local_model_manager.py:668-680`](backend/agent/local_model_manager.py:668)), and
`set_models_directory` ([`:281`](backend/agent/local_model_manager.py:281)) accepts a
user-supplied path. What is unverified is symlink traversal and whether every discovered model
becomes a **registrable provider instance** under REQ-1/REQ-2 rather than just a list entry.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL follow symlinks when scanning, so a symlinked Hugging Face cache is
  traversed rather than skipped.
- AC2: THE SYSTEM SHALL surface every discovered model as a **configurable provider instance**
  candidate, so discovery feeds REQ-1 registration directly.
- AC3: THE SYSTEM SHALL keep discovery non-blocking — scanning a large cache SHALL NOT stall
  startup or the WS handler.
- AC4: THE SYSTEM SHALL deduplicate models reachable by more than one path (symlink + real path)
  so one model does not appear twice.
- AC5: THE SYSTEM SHALL report scan errors per-entry and continue, rather than aborting the whole
  scan on one unreadable file.

**Edge Cases:**
- Circular symlink → traversal is depth-bounded and does not hang.
- Folder changed at runtime → rescan on demand without restart.
- Non-GGUF models in the folder (safetensors, e.g. Encoder-350M) → ignored by this spec's GGUF
  scan; `specs/lfm25-encoder-integration/` handles safetensors discovery separately.

---

### REQ-9: Observability for load and tuning decisions

**User Story:** As the person diagnosing a slow model I want to see why the loader chose its
parameters, so that I can tell a bad heuristic from bad hardware.

**Verified:** NEW (unverified — implementation pending). Load progress is parsed and reported
(`_parse_load_progress`), but the **decision** — why this context, why this many GPU layers — is
not recorded anywhere.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log one structured line per load recording: model fingerprint, source of
  the configuration (cache / derived / user override), chosen `n_ctx` / `n_gpu_layers` /
  `n_batch`, estimated VRAM, and predicted throughput.
- AC2: THE SYSTEM SHALL log every degradation step (REQ-5) with the constraint that triggered it.
- AC3: THE SYSTEM SHALL log every recorded correction (REQ-6) with the measurement that caused it
  and the configuration it will apply next load.
- AC4: THE SYSTEM SHALL expose current local-provider state — configured instances, loaded
  status, active configuration, recent throughput — through the existing read-only debug surface
  (`/api/debug/caducean` or a sibling), so live verification does not require a debugger.
- AC5: THE SYSTEM SHALL keep per-token or per-request logging off the hot path; throughput
  logging is aggregate.

**Edge Cases:**
- Load fails before any decision is made → log the failure reason, not a partial decision record.
- Debug endpoint polled during a load → reports `loading` status without blocking.

---

## Non-Requirements (Out of Scope)

- **Changing the API-provider path.** It works; this spec brings local up to parity with it, not
  the other way around.
- **Model download / installation.** Discovery is over an existing folder; fetching models from
  Hugging Face is a separate concern.
- **Safetensors / non-GGUF loading.** Covered by `specs/lfm25-encoder-integration/` (Encoder-350M
  is safetensors + torch).
- **The ContextPill dropdown UI.** Covered by `specs/contextpill-model-switcher/`, which depends
  on this spec's `loaded` status and multi-instance ids.
- **MTP / speculative decoding behavior.** The `balanced_mtp` profile and llama-server routing
  stay as-is; this spec must not regress them.
- **Replacing llama-server with something else.** The subprocess path stays.

## Open Questions

- **Q1 — How is predicted throughput estimated before the first measurement?** A rough model
  (params × quant × memory bandwidth) is enough to rank candidate contexts, but the constant needs
  calibrating. REQ-6's closed loop corrects it after one real load, so the initial estimate only
  needs to be approximately right. Non-blocking.
- **Q2 — Should two local models be allowed to load simultaneously by default?** REQ-2 AC5 says
  report capacity limits rather than silently unload. Whether the default is "load both if they
  fit" or "one at a time unless the user opts in" is a UX call. Recommend: load both if the VRAM
  estimate says they fit, with the capacity message otherwise.
- **Q3 — Cache location.** Per-model configs could live in `.mcm/local_model_configs.json`
  (alongside `der_params.json` and `provider_ceilings.json`) or next to the models. Recommend
  `.mcm/` for consistency with the existing params-store pattern.

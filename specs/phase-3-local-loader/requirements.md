# Requirements: Phase 3 — Local Model Loader

> **Execution position: THIRD.** Blocked on Phase 1 Wave 5 (registry, ids, `purpose`).
> Independent of Phase 2 — may run in parallel with it.
>
> **Supersedes** `local-model-provider-parity` REQ-4/5/5b/6/7/8/9. That document is history;
> **this file is authoritative.** Everything needed is here — do not open it.

## Decisions Locked

Resolved with the user 2026-07-28. Do **not** re-litigate.

1. **Throughput target ≥25 tok/s, maximizing context.** The loader finds the largest context that
   still sustains ≥25 tok/s for the model actually loaded on the hardware actually present.
2. **The user swaps models constantly.** Auto-recognition and auto-tuning are the feature. A model
   never loaded before must work without hand-tuning.
3. **Discovery is folder-based and user-configurable.** A symlinked Hugging Face cache holds the
   models; the frontend can point the backend at any folder.
4. **GPU-only for chat models — degrade within GPU, never fall back to CPU.** CPU offload causes
   memory spikes this machine cannot absorb. The ladder is context → batch. `n_gpu_layers` stays
   `-1`. Nothing fits → clean failure and unload, not a slow CPU load.
5. **Device policy keys on `purpose`, not on "being local".** `chat` → GPU. `embedding` / `rerank`
   → **CPU**. Parakeet ASR is GPU by its own separate service config and is untouched here.
6. **`purpose` is the selector because the models share a folder.** Embedding-350M and ColBERT ship
   GGUF and live in the *same* user scan folder as chat models, so any folder- or filename-based
   rule drags them onto the GPU and eats the VRAM the chat model's context depends on.

## Introduction

The loader does not do what its own profile table claims.

- `PROFILES` are **static presets** ([`local_model_manager.py:92-140`](backend/agent/local_model_manager.py:92)).
  `balanced` hardcodes `n_ctx = 32768`, `n_batch = 2048`, `n_gpu_layers = -1`, and its comment says
  *"VERIFIED: 45+ tok/s on RTX 3070 8GB with Qwen3.5-9B-Q3_K_S"* — one model, one GPU.
- `recommend_profile` ([`:930-948`](backend/agent/local_model_manager.py:930)) computes
  `vram_needed` but produces only **two** outcomes and never adjusts `n_ctx` to the model in hand.
- `estimate_vram_gb` ([`:906`](backend/agent/local_model_manager.py:906)) is weights-only
  (`params_b × bpw / 8 × 1.1`) — **context-independent**, so it cannot rank one context against
  another.
- `record_tps` ([`:1189`](backend/agent/local_model_manager.py:1189)) measures throughput and only
  **warns**, at a threshold of 8 tok/s. Nothing feeds back.

Consequence: a small model is capped at 32k when it could hold far more, a large model is rejected
outright instead of loading at a smaller context, and measured throughput never changes anything.

**The compute-and-discard pattern.** `record_tps` measuring and discarding is the same defect shape
found four times in this codebase (nucleus nudge, amplitude, `cur_a`, tok/s). REQ-4 exists to close
the loop, and its test asserts the *correction*, not the warning — the warning already exists and a
test for it would pass without the loop closing.

### Success criteria

- Loading a model never loaded before selects parameters sustaining **≥25 tok/s** at the **largest
  context that fits**, verified by measurement rather than preset.
- A chat model too large for VRAM **degrades** (smaller context, then smaller batch — never fewer
  GPU layers) instead of being rejected.
- An `embedding` or `rerank` model loads on **CPU** alongside a GPU-resident chat model, without
  competing for VRAM.
- Measured throughput **changes the next load's parameters** for that model.
- A model in the symlinked HF cache is discovered.
- The same model on the same hardware reuses a cached config instead of re-deriving.

## Requirements

---

### REQ-1: Load parameters are derived from the model and the hardware

**User Story:** As a user who swaps models constantly I want the loader to work out the right
settings for whatever model I picked, so I do not hand-tune every time.

**Verified:** REAL GAP — see Introduction. `PROFILES` static, `recommend_profile` two-outcome.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL derive `n_ctx`, `n_gpu_layers`, and `n_batch` from the **parsed model
  metadata** (parameter count, quantization, architecture) and the **live hardware snapshot**.
- AC2: THE SYSTEM SHALL select the **largest** context predicted to sustain `TARGET_TPS` (25).
- AC3: THE SYSTEM SHALL estimate VRAM including the **KV cache at the target context**, not weights
  alone.
- AC4: THE SYSTEM SHALL retain `PROFILES` as user-selectable **overrides**.
- AC5: WHERE the user selects an explicit profile THEN THE SYSTEM SHALL honour it and skip
  derivation.
- AC6: THE SYSTEM SHALL keep `balanced_mtp` and `force_subprocess` reachable so MTP speculative
  decoding does not regress.

**Edge Cases:**
- Metadata unparseable → fall back to the `balanced` preset, log the reason, continue.
- Hardware probe unavailable → REQ-2's failure path.
- A model whose minimum viable context still misses the target → REQ-2 AC6 loads it anyway and
  surfaces the expected rate.

---

### REQ-2: Chat models degrade **within GPU**, never fall back to CPU

**User Story:** As a user I want an oversized chat model to fit by using less context, not by
spilling onto the CPU — CPU offload causes memory spikes this machine cannot absorb.

**Verified:** The existing GPU-only policy is **correct and stays**
([`local_model_manager.py:941-946`](backend/agent/local_model_manager.py:941)). What is missing is
the GPU-side lever: the loader has no way to reduce **context**, so its only options are "load at
the preset 32k" or "reject". Context reduction reclaims KV-cache VRAM at **zero throughput cost**.

#### Policy Domain

| Model class | Device | Ladder | Counts against VRAM | Selector |
|---|---|---|---|---|
| Local chat / reasoning GGUF | **GPU only** | ctx → batch | yes | `purpose == "chat"` |
| Parakeet ASR service | **GPU** | — | (separate service) | not registry-loaded |
| Embedding models | **CPU** | none | **no** | `purpose == "embedding"` |
| Reranking models | **CPU** | none | **no** | `purpose == "rerank"` |

**Acceptance Criteria:**
- AC1: WHILE loading a `chat` model, WHEN it does not fit THEN THE SYSTEM SHALL reduce **context**
  first, then **batch size**, and SHALL NOT reduce `n_gpu_layers` or move any layer to CPU.
- AC2: THE SYSTEM SHALL keep `n_gpu_layers = -1` for every derived and degraded `chat` config.
- AC3: WHEN no `chat` config at or above `MIN_CTX` (4096) fits THEN THE SYSTEM SHALL fail cleanly,
  **unload any partial allocation**, and report the shortfall in GB.
- AC4: IF a GPU error occurs during or after a `chat` load THEN THE SYSTEM SHALL unload gracefully,
  release VRAM, mark `loaded=false`, report — and SHALL NOT retry on CPU.
- AC5: THE SYSTEM SHALL report every degradation step with its reason and expected throughput.
- AC6: WHERE the result falls below `TARGET_TPS` THEN THE SYSTEM SHALL load it anyway and surface
  the expected rate — the target is a goal, not a gate.
- AC7: THE SYSTEM SHALL retain the `eco` (CPU) profile as an **explicit user override only**, never
  auto-selected.
- AC8: THE SYSTEM SHALL default `embedding` and `rerank` to **CPU**, and SHALL NOT subject them to
  the ladder, the VRAM fit check, or `TARGET_TPS`.
- AC9: THE SYSTEM SHALL NOT count a CPU-resident model against the VRAM budget used to size a chat
  model.
- AC10: WHERE a user explicitly requests GPU for an `embedding`/`rerank` model THEN THE SYSTEM SHALL
  honour it and count it against VRAM while loaded.
- AC11: THE SYSTEM SHALL resolve device, ladder, VRAM accounting, and throughput target in **one**
  place keyed on `purpose`.

**Edge Cases:**
- CPU-only machine → report that local **chat** models require a GPU; embedding/rerank load normally.
- Model larger than total VRAM even at `MIN_CTX` → AC3 clean failure naming the shortfall.
- GPU OOM *after* a successful load → AC4 graceful unload, not a CPU retry.
- `purpose` undeterminable → default to `chat` (the GPU-gated path) and surface the ambiguity.
  Mis-classifying a chat model as embedding puts a 9B model on CPU silently; the reverse fails loudly.

---

### REQ-3: A loaded model reports its **actual** context window

**User Story:** As the DER loop I want the real context window of the model that is loaded, so my
token budget is not computed from a guess.

**Verified:** REAL BUG, live today. `resolve_context_window`
([`agent_kernel.py:934-975`](backend/agent/agent_kernel.py:934)) consults the substring table
**before** the live model manager, even though the manager branch's own comment says substring
guessing *"is unreliable for custom GGUF names and would otherwise under/over-size the budget vs the
real window."* A `Mistral-7B-*.gguf` loaded at 16k matches the table's `"mistral"` entry and reports
**32,768**.

> **Phase 1 REQ-2 AC2 already requires authoritative-over-table precedence.** This requirement is
> the local-side half: the loader must *expose* the loaded `n_ctx` so Phase 1's resolver has
> something authoritative to prefer. If Phase 1 is green, verify rather than re-implement.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL expose the actual configured `n_ctx` of a loaded local model.
- AC2: THE SYSTEM SHALL make that value outrank the substring table for a loaded model.
- AC3: THE SYSTEM SHALL keep the user override highest-precedence.
- AC4: THE SYSTEM SHALL use the table only when nothing is loaded.
- AC5: THE SYSTEM SHALL log the resolved value and its source.

**Edge Cases:**
- Model unloaded mid-session → falls back to the table, logged as such.
- Manager unavailable → table fallback, not a crash.

---

### REQ-4: Measured throughput changes the next load

**User Story:** As a user I want the loader to learn from what actually happened, so a model that
ran slowly is configured better next time.

**Verified:** REAL GAP — `record_tps` ([`:1189`](backend/agent/local_model_manager.py:1189)) warns
at 8 tok/s and **never adjusts** `n_ctx`, `n_gpu_layers`, `n_batch`, or the profile. Its threshold
is not even the 25 this phase targets.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL compare measured throughput against `TARGET_TPS` (25, env-overridable), not
  a hardcoded 8.
- AC2: WHEN sustained throughput is below target THEN THE SYSTEM SHALL record a **reduced-context**
  configuration for that model's **next** load.
- AC3: WHEN sustained throughput is comfortably above target with VRAM headroom THEN THE SYSTEM
  SHALL record an **increased** context for the next load.
- AC4: THE SYSTEM SHALL NOT reconfigure a **running** model — corrections apply to the next load.
- AC5: THE SYSTEM SHALL apply a deadband (`TPS_DEADBAND`) so measurements near the target record
  nothing, preventing oscillation.
- AC6: THE SYSTEM SHALL NOT measure `embedding`/`rerank` models against `TARGET_TPS` or record
  corrections for them.

**Edge Cases:**
- Single anomalous slow generation → deadband plus sustained-measurement requirement prevents a
  knee-jerk correction.
- Model unloaded before enough samples → record nothing.
- Correction oscillating between two contexts → AC5 deadband; log if it recurs.

---

### REQ-5: Per-model config cache

**User Story:** As a user I want a model I have used before to load with known-good settings
immediately, so I do not pay the derivation cost every time.

**Verified:** NEW. Follows the existing `.mcm/der_params.json` / `provider_ceilings.json` pattern.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL cache the derived/corrected configuration per model at
  `.mcm/local_model_configs.json`.
- AC2: THE SYSTEM SHALL fingerprint the model on path + size + mtime, so a swapped file invalidates.
- AC3: THE SYSTEM SHALL use a cached config as the starting point, still subject to the current
  hardware snapshot.
- AC4: THE SYSTEM SHALL invalidate on `hw_fingerprint` mismatch (different GPU, materially different
  free VRAM) and re-derive.
- AC5: IF the cache file is corrupt THEN THE SYSTEM SHALL discard it and derive fresh.

**Edge Cases:**
- Same filename, different content → AC2 fingerprint catches it.
- Cache present, hardware changed → AC4 re-derive.
- Concurrent writes from two loads → last write wins; the file is advisory, not authoritative.

---

### REQ-6: Model discovery follows symlinks and is user-configurable

**User Story:** As a user I want the backend to find the models in my symlinked Hugging Face cache,
so the models I actually use appear.

**Verified:** REAL GAP — the user's models live in a **symlinked** HF cache. Without symlink
traversal the primary source is invisible. Split-shard grouping exists at
[`:670-680`](backend/agent/local_model_manager.py:670) and must be preserved.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL follow symlinks when scanning the configured model folder.
- AC2: THE SYSTEM SHALL let the user configure the scan folder from the frontend.
- AC3: THE SYSTEM SHALL preserve split-shard grouping (a sharded model is one entry).
- AC4: THE SYSTEM SHALL de-duplicate a model reachable via both a symlink and its real path.
- AC5: THE SYSTEM SHALL bound recursion by `SCAN_MAX_DEPTH` and skip unreadable entries.

**Edge Cases:**
- Circular symlink → depth bound plus visited-set prevents a hang.
- Folder does not exist → empty result plus a clear message, not a crash.
- Model reachable twice → AC4 dedupe; otherwise it registers twice under different ids.

---

### REQ-7: Loader decisions are observable

**User Story:** As the tuner I want to see why the loader chose what it chose, so thresholds can be
set from data.

**Verified:** Progress phases are already parsed (`_parse_load_progress`); the **decision** is not
logged.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log, per load: the model, the config source
  (`cache` | `derived` | `user_override` | `degraded`), chosen `n_ctx` / `n_gpu_layers` / `n_batch`,
  estimated VRAM, and expected throughput.
- AC2: THE SYSTEM SHALL log every degradation step with its reason (REQ-2 AC5).
- AC3: THE SYSTEM SHALL log measured throughput with the correction it produced, or that it fell in
  the deadband (REQ-4).
- AC4: THE SYSTEM SHALL expose loader state and the active config through `/api/debug/caducean`.
- AC5: THE SYSTEM SHALL keep logging off the critical path.

**Edge Cases:**
- Load fails before a config is chosen → log the failure and the attempted config.
- Debug endpoint polled during a load → read-only, must not perturb the load.

---

## Non-Requirements (Out of Scope for Phase 3)

- **Provider registration, ids, `purpose`, persistence, the registry** → Phase 1. This phase
  *consumes* them.
- **The encoders themselves** → Phase 4. This phase only guarantees `embedding`/`rerank` load on CPU.
- **Any UI** → Phase 5.
- **Parakeet ASR.** Separate FastAPI service with its own `--device` flag defaulting to `cuda`
  ([`parakeet_service.py:99`](backend/audio/parakeet_service.py:99)). Untouched.
- **Changing the GPU-only policy for chat models.** Decision Locked #4.
- **Adding CPU offload as a degradation step.** Explicitly forbidden.

## Open Questions

- **OQ-1:** The initial throughput estimate for REQ-1 AC2 only needs to *rank* candidates; REQ-4's
  loop corrects the constant after one real load. Confirm the ranking function is monotonic in
  context before trusting it.
- **OQ-2:** `TPS_DEADBAND` width. Set from observed variance after the first few real loads.

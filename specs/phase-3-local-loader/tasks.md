# Tasks: Phase 3 — Local Model Loader

> **Blocked on Phase 1 Wave 5** (registry, namespaced ids, `purpose`). Independent of Phase 2 —
> may run in parallel with it.
>
> Supersedes `local-model-provider-parity` REQ-4/5/5b/6/7/8/9. Everything needed is in this spec —
> **do not open that document.**

---

## Wave 0 — Fixtures and baseline

- [ ] **T0.1** Confirm Phase 1 landed: namespaced local ids exist, `purpose` exists, two local
  instances can register, the registry is process-wide.
  RIPPLE: hard gate. Without it T1.1 has nothing to key on.

- [ ] **T0.2** Capture **real GGUF metadata** for a small, a medium, and a large model from the
  user's actual folder (params, quant, file size), plus a real hardware snapshot.
  RIPPLE: ⚠️ **gates the whole phase.** The deriver cannot be validated against invented metadata —
  the entire point is that it responds to the model in hand. Do not synthesize these numbers.

- [ ] **T0.3** Record current behaviour: load each of the three models, note the chosen `n_ctx`,
  whether it was a preset, measured tok/s, and whether anything changed on the second load.
  RIPPLE: the "before" for REQ-1 and REQ-4. Expect identical presets and no second-load change —
  that is the defect.

- [ ] **T0.4** Green-suite baseline (`pytest backend/tests`), noting pre-existing failures.

---

## Wave 1 — Device policy first (REQ-2 AC8–AC11)

- [ ] **T1.1** (REQ-2 AC11) Add `resolve_device_policy(purpose, user_override) -> DevicePolicy` —
  the **single** place device, ladder, `counts_against_vram` and `throughput_target` are decided.
  `chat` → GPU, ladder `("ctx","batch")`, counts VRAM, target `TARGET_TPS`.
  `embedding`/`rerank` → CPU, **empty** ladder, no VRAM, no target.
  Explicit GPU override flips device **and** `counts_against_vram` together.
  RIPPLE: ⚠️ **Do this before T2.x–T3.x** — they all branch on its output. Do **not** scatter
  `if purpose == "chat"` through the deriver, degrader, VRAM accountant and tok/s recorder: three of
  those four fail **silently** when one is forgotten (D-1). The GPU-only policy is scoped to
  `purpose == "chat"`, not to "being local" — Embedding-350M and ColBERT ship GGUF and live in the
  **same** scan folder, so any folder- or filename-based rule drags them onto the GPU.

- [ ] **T1.2** Tests: `backend/tests/unit/test_device_policy.py` — parametrized over **all three**
  purposes plus the override case (CT-L1).

---

## Wave 2 — Derivation (REQ-1)

- [ ] **T2.1** (REQ-1 AC3) Fix `estimate_vram_gb`
  ([`:906`](backend/agent/local_model_manager.py:906)) to include the **KV cache at the target
  context** alongside weights.
  RIPPLE: ⚠️ **Do this first in the wave.** Today's `params_b × bpw / 8 × 1.1` is
  **context-independent**, so it returns the same number for 8k and 128k — the whole search is
  meaningless until this changes. `test_vram_estimate_includes_kv` fails against current code **by
  design**.

- [ ] **T2.2** (REQ-1 AC1/AC2) Implement `ConfigDeriver`: walk the context ladder downward; for each
  candidate estimate VRAM (T2.1) and throughput; select the **largest** context predicted to clear
  `TARGET_TPS` (25).
  RIPPLE: replaces `recommend_profile`'s two-outcome selection
  ([`:930-948`](backend/agent/local_model_manager.py:930)). Keep `PROFILES` as user overrides
  (AC4) **and keep `balanced_mtp` / `force_subprocess` reachable** so MTP speculative decoding does
  not regress (AC6). OQ-1: the initial throughput estimate only needs to *rank* candidates — REQ-4's
  loop corrects the constant after one real load. Verify it is monotonic in context.

- [ ] **T2.3** Tests: `test_config_deriver.py` — the three T0.2 models yield **three different**
  contexts from the same code path.

---

## Wave 3 — Degradation + load wiring (REQ-2 AC1–AC7)

- [ ] **T3.1** (REQ-2 AC1/AC2/AC3) Implement the **GPU-only** degradation ladder for
  `purpose == "chat"` — context → batch — retrying the load at each step, `MIN_CTX` (4096) as the
  floor. `n_gpu_layers` stays `-1` throughout. Nothing fits → fail cleanly, unload any partial
  allocation, report the shortfall in GB.
  RIPPLE: ⚠️ **The existing GPU-only policy at
  [`:941-946`](backend/agent/local_model_manager.py:941) is CORRECT and stays.** CPU offload causes
  memory spikes this machine cannot absorb — not a degradation step, not a fallback. What is being
  added is the missing **GPU-side lever**: context reduction reclaims KV-cache VRAM at **zero
  throughput cost**. Do **not** add `n_gpu_layers` to the ladder. Keep `eco` reachable only as an
  explicit user override (AC7), never auto-selected.
  A model whose `DevicePolicy.ladder` is empty must **not enter this function at all** — not enter
  and return early, since an early return still runs the VRAM fit check AC9 forbids.

- [ ] **T3.2** (REQ-2 AC4) Graceful unload on GPU error/OOM: release VRAM, `loaded=false`, report,
  **no CPU retry**.

- [ ] **T3.3** (REQ-1, REQ-2) Wire `load_model` to branch on `resolve_device_policy` **before** any
  hardware-fit reasoning, then consume `DerivedConfig` and drive the ladder on the GPU branch.
  RIPPLE: `_parse_load_progress` untouched (NO CHANGE, verified). The CPU branch skips
  `estimate_vram_gb`, `ConfigDeriver` and the degrader entirely, and must still reach `loaded=true`
  and register — Phase 4's embedding provider depends on it.

- [ ] **T3.4** (REQ-2 AC9) Exclude CPU-resident instances from the VRAM budget used to size a chat
  model.
  RIPPLE: ⚠️ the **silent** half. Counting a CPU embedding model against VRAM produces no error — it
  just hands the chat model a smaller context forever.
  `test_cpu_model_does_not_shrink_chat_context` is the only thing that catches it.

- [ ] **T3.5** Tests:
  - `test_degradation_order.py` — ctx before batch; `n_gpu_layers == -1` in **every** candidate.
  - `test_degrades_within_gpu.py`, `test_gpu_error_unloads_cleanly.py`.
  - `test_embedding_loads_on_cpu.py` — **no CUDA present**, zero VRAM consumed.
  - `test_cpu_model_does_not_shrink_chat_context.py`.

---

## Wave 4 — Closed loop + cache (REQ-4, REQ-5)

- [ ] **T4.1** (REQ-4 AC1) Replace the hardcoded 8 tok/s threshold in `record_tps`
  ([`:1189`](backend/agent/local_model_manager.py:1189)) with `TARGET_TPS` (25, env-overridable).

- [ ] **T4.2** (REQ-4 AC2/AC3/AC5) Write corrections to `ConfigCache`: sustained below target →
  reduced context for the next load; comfortably above with headroom → increased; within
  `TPS_DEADBAND` → nothing.
  RIPPLE: ⚠️ **assert the correction, not the warning.** The current code already warns; a test that
  checks for a warning passes without the loop closing. This is the fourth occurrence of
  compute-and-discard in this codebase — the test must prove the value *changed something*.

- [ ] **T4.3** (REQ-4 AC4) Never reconfigure a **running** model.
  RIPPLE: corrections apply to the next load. Reconfiguring mid-session would drop the user's
  context to satisfy a throughput target.

- [ ] **T4.4** (REQ-4 AC6) Do not measure `embedding`/`rerank` against `TARGET_TPS`.
  RIPPLE: without this, the closed loop permanently punishes a model never meant to hit 25 tok/s.

- [ ] **T4.5** (REQ-5) Implement `ConfigCache` at `.mcm/local_model_configs.json`: fingerprint on
  path+size+mtime, `hw_fingerprint` invalidation, corrupt-file tolerance.
  RIPPLE: follows the `outer_loop._load_params` pattern (`.mcm/der_params.json`,
  `provider_ceilings.json`). A stale config against a swapped model file is exactly the
  inconsistency AC2's fingerprint prevents.

- [ ] **T4.6** Tests: `test_tps_correction.py`, `test_config_cache.py`,
  `test_closed_loop_tuning.py`, `test_cpu_model_not_measured_against_target.py`.

---

## Wave 5 — Discovery + context exposure (REQ-3, REQ-6)

- [ ] **T5.1** (REQ-6) Symlink traversal, dedupe, and `SCAN_MAX_DEPTH` in `scan_models`.
  RIPPLE: the user's models live in a **symlinked HF cache**, so without AC1 the primary source is
  invisible. Preserve split-shard grouping
  ([`:670-680`](backend/agent/local_model_manager.py:670)). Dedupe matters because a model reachable
  via both symlink and real path would otherwise register twice under different ids.

- [ ] **T5.2** (REQ-6 AC2) Let the frontend configure the scan folder.

- [ ] **T5.3** (REQ-3) Expose the loaded model's actual configured `n_ctx`.
  RIPPLE: ⚠️ **Phase 1 REQ-2 AC2 already requires authoritative-over-table precedence in
  `resolve_context_window`.** If Phase 1 is green, this task is *verify and expose*, not
  re-implement. Live bug if Phase 1 slipped: a 16k-loaded Mistral reports 32,768.

- [ ] **T5.4** Tests: `test_symlinked_model_discovered.py`,
  `test_loaded_context_window_wins.py` (**fails today**).

---

## Wave 6 — Observability, harness, close-out (REQ-7)

- [ ] **T6.1** (REQ-7 AC1/AC2/AC3) Log per load: model, config source, chosen params, estimated
  VRAM, expected throughput; every degradation step with its reason; measured throughput with the
  correction it produced (or that it fell in the deadband).

- [ ] **T6.2** (REQ-7 AC4) Expose loader state + active config in `/api/debug/caducean` (read-only).

- [ ] **T6.3** Build `scripts/validate_local_model_path.py` with all 9 harness assertions.
  RIPPLE: assertion **2** decides whether REQ-1 landed — identical contexts across three model sizes
  means presets are still in charge under a new name. **6 and 7** decide whether the device scoping
  landed.

- [ ] **T6.4** Full regression vs T0.4. Manual verification vs T0.3: load the three real models,
  confirm three different contexts, confirm a second load uses a corrected config.

- [ ] **T6.5** Update `docs/CADUCEAN_ARCHITECTURE.md` §9 (**append**) and `bootstrap/GOALS.md`.

---

## Dependency / parallelization notes

**Hard sequencing:**
- **Phase 1 Wave 5 before T1.1.**
- **T0.2 before Wave 2.** Real metadata or the deriver is validated against fiction.
- **T1.1 before T2.x and T3.x.** Everything branches on `DevicePolicy`; retrofitting the branch is
  how the scoping ends up as scattered `if` guards.
- **T2.1 before T2.2.** A context-independent VRAM estimate makes the search meaningless.
- **T4.1 before T4.2.**

**Parallelizable:**
- **Wave 5 (scanning + context exposure) is independent of Waves 2–4** (derivation) — different
  functions.
- T6.1 (logging) can be written at any point.
- All test-writing precedes its implementation task.
- **This entire phase runs parallel to Phase 2.**

**Riskiest tasks:**
1. **T3.1 — reversing the GPU-only policy.** The temptation is to add CPU offload as one more rung;
   that reintroduces the memory spikes the policy exists to prevent. `test_degradation_order`
   asserts `n_gpu_layers == -1` in every candidate so it is impossible, not merely discouraged.
2. **T1.1 / T3.4 — widening the GPU policy back to "all local models".** The natural mistake: every
   one of these models is local and they share a folder. Fails silently in **both** directions — an
   embedding model on GPU steals the chat model's context; a CPU instance counted against VRAM
   shrinks it with no error.
3. **T4.2 — asserting the warning instead of the correction.** The warning already exists; a test
   for it passes without the loop closing.
4. **T2.1 — leaving the estimate context-independent.** Everything downstream silently becomes a
   coin flip.
5. **T5.3 — re-implementing Phase 1's resolver.** Two precedence chains for one question.

### Baseline record
<!-- T0.2/T0.3 record "before"; T6.4 records "after". -->

| Model (real, from T0.2) | Params / quant | Before: n_ctx, source, tok/s | After: n_ctx, source, tok/s |
|---|---|---|---|
| small | | | |
| medium | | | |
| large | | | |

| Check | Before | After |
|---|---|---|
| Three models → three different contexts | | |
| Second load uses a corrected config | | |
| Symlinked model discovered | | |
| Embedding model loads with zero VRAM | | |
| Chat context unchanged with encoders loaded | | |

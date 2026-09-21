# Tasks: Closed-loop local model tuning

> Each task links to a requirement. Waves are ordered; tasks within a wave may run in parallel.

## Wave 0 — Configuration location (COMPLETE)

- [x] **T0 (REQ-4 AC5, AC6)** — Move calibration state out of `.mcm/` into
      `.iris-config/` at the project root.
      - `local_model_manager.py`: added module-level `LOCAL_MODEL_CONFIGS_PATH` (`:283`) as the
        single source of truth; `ConfigCache.__init__` (`:308`) and `_machine_path()` (`:386-388`)
        both use it. The latter previously hardcoded the `.mcm` path as a fallback, which would
        have silently split the two caches apart.
      - `.gitignore`: added `.iris-config/` as regenerated per-machine state.
      - Rationale recorded in the `ConfigCache` docstring so it is not re-litigated.
      - Verified: both paths resolve to `C:\dev\IRISVOICE\.iris-config\`; local-model suite
        **53 passed / 1 failed**, the single failure being the known pre-existing environmental
        one. No migration needed — the old file never existed on this machine.
      — RIPPLE: none at runtime. `_save()` already calls `mkdir(parents=True, exist_ok=True)`
        (`:442`), so the new directory is created on first write.

## Wave 1 — Measurement (no behaviour change yet)

- [ ] **T1 (REQ-1 AC1, AC2)** — Add `_extract_timings(payload) -> Optional[float]` to
      `backend/agent/inference/transport.py`, placed next to `_extract_usage` (`:398`).
      Reads `payload["timings"]["predicted_per_second"]`. Returns `None` for missing block,
      non-dict payload, non-numeric, zero, negative, or non-finite values. Never raises,
      never estimates.
      — RIPPLE: none. Pure function, additive, no callers yet.

- [ ] **T2 (REQ-1 AC1, AC4)** — Add `self.last_tps: Optional[float] = None` to
      `OpenAICompatTransport` (`:851`) beside `self.last_usage` (`:867`). Reset it at `:914`
      where `last_usage` is reset. Set it from `_extract_timings` at every point `last_usage`
      is currently set — the non-streaming path feeding `_record_success` (`:946`) and the
      streaming chunk path (`:1047-1049`).
      — RIPPLE: `ApiHttpxTransport` (`:457`) shares `_record_success`-style flow; T3 covers it.

- [ ] **T3 (REQ-1 AC1, AC4)** — Mirror T2 on `ApiHttpxTransport` (`:457`) so local-over-HTTP
      configs report timing too.
      — RIPPLE: none. Additive attribute; `getattr` defaults elsewhere return `None`.

- [ ] **T4 (REQ-1 AC3)** — Add `self.last_tps` to `InferenceRouter.__init__` beside
      `self.last_usage` (`:275`), and set it in `generate()` immediately after the existing
      `self.last_usage = getattr(transport, "last_usage", None)` at `:973`.
      — RIPPLE: **CONTRACT LOCK** — do not touch the return signature. Pinned by CT-1.

## Wave 2 — Close the loop

- [ ] **T5 (REQ-2 AC1, AC2, AC5)** — After `self.last_tps` is set in `router.generate()`,
      invoke `record_tps` when the call went to a local provider and `last_tps` is not `None`.
      Local instances are namespaced `local:<stem>` (`router.py:474`, `:492`) — see Open
      Question 2 for whether to use an id-prefix test or add an explicit `is_local` flag.
      Wrap the call so any exception is logged and swallowed.
      — RIPPLE: this is the single edge that makes the whole engine run. It causes
      `_write_tps_correction` (`:2574`) to execute for the first time in the project's life,
      which writes both cache files. Verify `record_tps` is idempotent across concurrent calls.

- [ ] **T6 (REQ-5 AC1, AC2, AC3)** — Add the logging: DEBUG for each sample received
      (measured, rolling mean, target), INFO for each correction written (model, measured tps,
      derived `base_tps`, bandwidth, old `n_ctx`, new `n_ctx, direction), INFO when a sample is
      dropped because `last_tps` was `None`.
      — RIPPLE: log volume. Keep per-sample lines at DEBUG; this path runs on every generation.

## Wave 3 — Transparency (decision log + user-facing readout)

- [ ] **T7 (REQ-6 AC1, AC2)** — Emit the `derive_config` decision line: `vram_budget_gb`,
      `weights_gb`, `kv_bytes`, `kv_gb`, `total_est_gb`, and which term bound the result
      (VRAM / throughput / profile ceiling / native context).
      — RIPPLE: none behavioural. This is the diagnostic that resolves the outstanding
      question of why `n_ctx` lands on 21,175 for TwIL-LM3, which matches neither the VRAM cap
      (~106,000) nor the throughput cap (16,384). It is ALSO the `bound_by` source for T7a.

- [ ] **T7a (REQ-7 AC1, AC2, AC3)** — Build the read-only calibration readout: `model`,
      `calibrated`, `measured_tps`, `n_ctx`, `bound_by`, `samples` (N of 3), `last_correction`.
      Derived from `ConfigCache` + `_tps_window` + T7's decision log. No new store — this is a
      view over state that already exists.
      — RIPPLE: **CONTRACT LOCK** — must not alter the `inference_event` WS payload (CT-2).
      Transport mechanism is Open Question 6; do not invent one before that is resolved.

- [ ] **T7b (REQ-7 AC4, AC5)** — Add a manual "re-calibrate" action that invalidates the cached
      entry and clears `_tps_window`. Useful after a driver or GPU change where the hardware
      fingerprint did not change but real performance did.
      — RIPPLE: none. Must remain strictly optional — a load SHALL NEVER block on it (AC5).
      Verify that clearing the window mid-generation cannot corrupt an in-flight correction
      (`ConfigCache` is lock-guarded, `:304`).

## Wave 4 — Tests

- [ ] **T8 (REQ-1)** — Unit tests for `_extract_timings`: realistic llama.cpp block parses;
      every malformed shape returns `None`; never raises. Plus a unit test that `last_tps`
      resets between calls.
      — RIPPLE: none.

- [ ] **T9 (REQ-1, REQ-3)** — Contract test **CT-4**: `_extract_timings` never raises and never
      estimates across the full malformed-input matrix.
      Contract test **CT-1**: `generate()` returns a 3-tuple for every transport.
      — RIPPLE: CT-1 guards the CONTRACT LOCK on the router return signature (8+ call sites).

- [ ] **T10 (REQ-4)** — Contract test **CT-3**: a `ConfigCache` entry written by
      `_write_tps_correction` round-trips with `measured_tps` preserved, and a legacy entry
      lacking `measured_tps` still loads.
      — RIPPLE: guards the on-disk format consumed by `ConfigCache.get()` (`:330-348`).

- [ ] **T11 (REQ-2, REQ-4)** — Behavioral test: drive three generations against a **non-local**
      provider and assert `record_tps` is never called and no cache entry is created.
      — RIPPLE: none.

- [ ] **T12 (REQ-2, REQ-3)** — Behavioral test: three generations at injected sub-target tps
      shrink the NEXT load's `n_ctx`. This is
      `test_closed_loop_tuning.py::test_next_load_uses_reduced_context`, which is **already
      red and was red before this work** (verified by reverting to HEAD: identical failure).
      Its cause is environmental — the test patches `_load_inprocess`, but `load_model` routes
      to the subprocess path because the venv's llama-cpp-python has no GPU offload
      (`local_model_manager.py:814`), then times out spawning a real server. Fix by making the
      test force the in-process path or supply a fake server. **Do not weaken the assertion.**
      — RIPPLE: this test is the behavioural proof of the entire feature. It must go green
      without changing what it asserts or reducing the sample count.

- [ ] **T13 (REQ-4)** — Contract test **CT-2**: the `inference_event` WS payload shape is
      unchanged, so this work cannot silently break `InferenceConsolePanel`.
      — RIPPLE: guards the frontend contract at `iris_gateway.py:5358-5372`.

- [ ] **T14 (REQ-2, REQ-4)** — Extend `scripts/validate_local_model_lifecycle.py` (or a
      sibling harness) to run a scripted three-turn local generation and assert both
      calibration artefacts exist afterwards, so the loop cannot silently go dormant again.
      — RIPPLE: none.

## Wave 5 — MoE support (REQ-8, REQ-9)

> Grounded in a measured benchmark — see design.md "Benchmark Evidence". Do not attempt the
> placement work before reading it.

- [ ] **T15 (REQ-8 AC1, AC6)** — MoE detection. Extend `parse_gguf_metadata` (`:1462`) to expose
      an expert count, and record it as a model attribute. Unknown or malformed metadata must
      degrade to "not MoE" without raising. Include expert placement in the REQ-6 decision line.
      — RIPPLE: `parse_gguf_metadata` output feeds `derive_config` and `ConfigCache`; adding a
      field must not change any existing key (CT-3 pins the cache shape).

- [ ] **T16 (REQ-8 AC2, AC3, AC4)** — Add expert placement as a tunable dimension in
      `ConfigCache`, defaulting to full GPU. Add `-ncmoe` / `-cmoe` / `-ot` to
      `_build_server_cmd` **only when placement is non-default**.
      — RIPPLE: **CONTRACT LOCK (CT-5)** — default argv must stay byte-identical to today. The
      benchmark shows CPU placement costs 6.9-18.3x here, so an unconditional change regresses
      every current model.

- [ ] **T17 (REQ-8 AC5)** — When a model cannot fit VRAM under any GPU-only placement, fall back
      to partial CPU expert placement but **surface the measured throughput cost before loading**
      rather than degrading silently.
      — RIPPLE: needs a pre-flight signal the frontend can display. Surface via the REQ-7 readout,
      not a new WS event (CT-2).

- [ ] **T18 (REQ-9 AC1)** — Cheap, cached, non-blocking startup probe for an alternate MoE
      engine. Absence must be a normal, silent outcome.
      — RIPPLE: startup path. Must not delay first response; probe off the critical path.

- [ ] **T19 (REQ-9 AC2, AC4)** — Register the alternate engine as an `InferenceRouter` provider
      and route to it only when: it is available AND the model is MoE AND its weights exceed what
      GPU-only placement can hold.
      — RIPPLE: `InferenceRouter` provider registry and role bindings (`router.py:474`, `:492`).
      Do not fork lifecycle management — reuse the existing provider machinery.

- [ ] **T20 (REQ-9 AC3, AC5, AC6)** — Fallback to llama-server on any alternate-engine failure
      (won't start, unsupported quantisation), apply the REQ-2 loop identically regardless of
      engine, and log which engine served each request and why.
      — RIPPLE: REQ-2 must be engine-agnostic. Verify `record_tps` fires for the alternate engine
      too, or calibration silently stops when routing changes.

## Wave 6 — MoE tests

- [ ] **T21 (REQ-8)** — Contract test **CT-5**: default argv contains `-ngl -1` and contains NO
      `-cmoe` / `-ncmoe` / `-ot` for any model that fits VRAM. This is the permanent guard against
      quietly reintroducing CPU offload.
      — RIPPLE: locks the GPU-only rule that the benchmark justified.

- [ ] **T35 (REQ-11)** — Contract test **CT-6**: `resolve_device_policy` remains the single
      source of truth and `_build_server_cmd` never contradicts it — chat/tool argv byte-identical
      to today (also CT-5), embedding/rerank may carry `n_gpu_layers 0`.
      — RIPPLE: locks the policy delegation so the old unconditional force cannot return.

- [ ] **T36 (REQ-12)** — Behavioral: an injected OOM failure shrinks the next attempt's `n_ctx`;
      an injected non-OOM failure marks the model unusable and does NOT shrink; the identical
      config is never re-attempted; the retry cap of three is enforced.
      — RIPPLE: guards against REQ-12's own failure modes — the sticky retry loop on one side,
      walking `n_ctx` to zero on the other.

- [ ] **T37 (REQ-13)** — Behavioral: size the brain while vision is NOT resident, then simulate
      vision loading, and assert the brain's config was already budgeted for it (no over-commit).
      Plus: unload releases the ledger entry; a stale entry is reconciled away.
      — RIPPLE: regression test for the live bug. It must drive BOTH processes' lifecycles, or
      it proves nothing.

- [ ] **T22 (REQ-8)** — Unit tests: MoE GGUF yields an expert count; dense and malformed GGUF
      degrade to "not MoE" without raising; `ConfigCache` round-trips the placement field.
      — RIPPLE: `ConfigCache` shape pinned by CT-3.

- [ ] **T23 (REQ-9)** — Behavioral test: with no alternate engine installed, an MoE model still
      loads and serves via llama-server exactly as before, and no feature is unavailable.
      — RIPPLE: this is the "optional dependency" guarantee (AC3). It must stay green if
      FreeToken is never installed.

## Wave 7 — Frontend wiring contracts (REQ-10)

- [ ] **T24 (REQ-10 AC1)** — Contract test pinning the exact key set of the `inference_event` WS
      payload (`iris_gateway.py:5358-5372`). Adding, removing or renaming a key must fail the
      build.
      — RIPPLE: `InferenceConsolePanel` is the consumer and currently has NO protection. This is
      the highest-value missing test in the whole spec.

- [ ] **T25 (REQ-10 AC4)** — Contract test pinning the `local_model_loading` progress event shape,
      asserting `pct` is monotonic and that a successful load emits `pct: 100`. Guards the
      progress fix shipped earlier in this session against regression.
      — RIPPLE: the fix added `-lv 5` to argv; if a future build drops that flag, progress goes
      silent again and only this test catches it.

- [ ] **T26 (REQ-10 AC3)** — For each value the frontend renders from this feature, assert the
      frontend reads it under the exact key the backend emits. Backend-only assertions are not
      sufficient — the seam is the point.
      — RIPPLE: requires adding to `__tests__/`, which currently has exactly one model-related
      test file (`ModelSwitcher.test.tsx`).

- [ ] **T27 (REQ-8 AC7)** — Extend the calibration key so it captures CPU and system-memory
      capability, or give placement its own key. `_hw_fingerprint` (`:325`) is only
      `gpu_name:total_VRAM` and cannot distinguish machines where CPU MoE placement is viable
      from ones where it is catastrophic.
      — RIPPLE: changing the fingerprint INVALIDATES every existing cache entry. That is correct
      and desirable (there are none yet), but it must happen before any calibration is shipped
      or users will inherit stale entries.

## Wave 8 — Failure recovery, VRAM ledger, device enforcement (REQ-11, REQ-12, REQ-13)

> These are DEFECT FIXES, not enhancements. The ledger and failure-learning address live bugs;
> device enforcement fixes a policy contradiction. Ranked by user impact.

- [ ] **T28 (REQ-13 AC1, AC2, AC3)** — Build the VRAM ledger. Every resident model registers its
      footprint; `derive_config`'s budget at `:2099` changes from `hw["vram_free_gb"]` to
      `vram_total − ledger_total − headroom`. Reserve the vision server's expected footprint up
      front, whether or not it is resident.
      — RIPPLE: this is the fix for the mid-conversation OOM (the session-268 failure). Touches
      `derive_config`, the vision server lifecycle (`lfm_vl_provider.py`, which RESPAWNS after
      idle-stop — a stale entry would double-count), and `unload_model` (AC4).

- [ ] **T29 (REQ-13 AC4, AC5)** — Ledger release and reconciliation. Release on unload;
      reconcile against actual `nvidia-smi` usage on every load so a crashed process cannot
      leave a phantom claim.
      — RIPPLE: `unload_model` (~`:3224`) and the vision respawn path. `get_hardware_info` keeps
      its meaning — it feeds reconciliation, not budgeting.

- [ ] **T30 (REQ-12 AC1, AC4)** — Failure classification + negative correction. Classify load
      failures BEFORE any retry: VRAM exhaustion → write a reduced-`n_ctx` correction and retry
      (bounded); anything else → mark unusable and stop. Never re-attempt the exact config that
      just failed.
      — RIPPLE: `load_model` failure paths and the `ConfigCache` entry (extend CT-3; legacy
      entries must still load). Highest-value task in the spec — this is the
      "signal aborted at 98%" loop breaker.

- [ ] **T31 (REQ-12 AC2, AC5)** — Retry bounds and failure surfacing. Cap at three attempts,
      surface the failure class in the log and the REQ-7 readout, let T7b's re-calibrate clear
      an "unusable" mark.
      — RIPPLE: readout payload (REQ-10 AC2). See Open Question 13 (does "unusable" persist
      across restarts?) — resolve before implementing; recommend time-limited.

- [ ] **T32 (REQ-11 AC3, AC4)** — Replace the unconditional `n_gpu_layers = -1` force
      (`:3691-3698`) with delegation to `resolve_device_policy`. Chat/tool argv stays
      byte-identical; embedding/rerank may use CPU.
      — RIPPLE: **CT-5 still applies** — default chat argv must not change. `PROFILES["eco"]`
      (`:114`) goes from dead code to live; verify no caller depended on the override.

- [ ] **T33 (REQ-11 AC1, AC2)** — Loud no-GPU failure for chat/tool: an actionable error naming
      the missing capability, never a silent force to `-1` that fails later and mysteriously.
      — RIPPLE: error must travel through an existing error channel, not a new event shape (CT-2).

- [ ] **T34 (REQ-2 AC6, AC7)** — Conservative bias for uncalibrated machines: prefer the smaller
      end, and grow incrementally on correction rather than jumping to the VRAM ceiling.
      — RIPPLE: `derive_config`'s uncalibrated branch only; must never push below `MIN_CTX`.

## Dependency / parallelization notes

- **T1 is a prerequisite for T2, T3 and T8.** Pure function first.
- **T2, T3 and T8 may run in parallel** once T1 lands — independent classes and independent tests.
- **T4 depends on T2/T3** (needs something to read off the transport), but only the `getattr`
  default is required, so T4 can be written defensively in parallel and verified after.
- **T5 depends on T4.** It is the single most important task and the only one that changes
  runtime behaviour — everything before it is additive and inert.
- **T6 can be written in parallel with T5** but should land with or immediately after it,
  because T5 turning the loop on without T6's logging makes the first calibration invisible.
- **T0 is COMPLETE.** It is listed so the location decision is discoverable; nothing depends on
  doing it again. Any future work that adds calibration state MUST place it under
  `.iris-config/` via `LOCAL_MODEL_CONFIGS_PATH`, never in `.mcm/` and never beside the models.
- **T7a depends on T7** for the `bound_by` field, and on T5/T6 for `measured_tps` and
  `last_correction` to ever be non-empty. It can be built against empty state and verified after.
- **T7b is independent** of T7a and can land at any time.
- **T12 is blocked on T5** and on resolving how to force the in-process path in a test
  environment where it is disabled. It is the acceptance gate for the feature.
- **No task modifies the `inference_event` payload** (CT-2 pins it). The REQ-7 readout is a NEW
  surface; resolve Open Question 6 before choosing its transport.
- **Waves 5 and 6 are independent of Waves 1-4** and may proceed in parallel — MoE placement and
  the alternate engine do not depend on the calibration loop, though T20 (REQ-9 AC5) should
  verify the loop fires for both engines once T5 lands.
- **T15 gates T16, T17, T19** — nothing can reason about MoE until detection exists.
- **T16 must land with T21.** Adding placement flags without the CT-5 guard is how a measured
  18x regression gets reintroduced later.
- **T18 gates T19, T20** — no routing without a probe.
- **T24 and T25 are independent of everything else** and are the highest-value tests here — they
  protect seams that currently have no coverage at all. They can land immediately.
- **Wave 8 is the highest-impact wave in the spec** — T28 and T30 fix live bugs users hit today
  (mid-conversation OOM; the retry-forever loop). It is independent of Waves 1-5. If you do only
  one wave, do this one.
- **T28 gates T29 and T37** — no release/reconcile or test without the ledger.
- **T30 gates T31 and T36** — classification before bounds and tests.
- **T32 must land with T35 (CT-6)** — changing device enforcement without pinning the policy
  delegation is how the unconditional force returns.
- **T34 depends on nothing** and is small; land it with T5/T6 so the first real calibration
  session already exercises the grow path.
- **T27 must land before any calibration data is shipped.** It invalidates cache entries by
  design; doing it later means real users inherit stale ones.
- **T26 depends on the REQ-7 transport decision** (Open Question 6).
- Tasks that modify code: T1, T2, T3, T4, T5, T6, T7, T7a, T7b, T15, T16, T17, T18, T19, T20,
  T27, T28, T29, T30, T31, T32, T33, T34. (T0 already done.)
  Tasks that only add tests/harness: T8-T11, T13, T14, T21, T22, T23, T24, T25, T26, T35, T36, T37.
  T12 modifies test infrastructure only (not the assertion).

## Blocked on user decisions

- ~~Open Questions 7-10~~ **RESOLVED** — moved to Decisions Locked; implemented as REQ-11
  (T32, T33), REQ-2 AC6/AC7 (T34), REQ-12 (T30, T31), REQ-13 (T28, T29). The user confirmed the
  brain stays on the GPU: *"I usually don't ever run the brain on my CPU."*
- **T31's persistence semantics** depend on Open Question 13 (does "unusable" survive a restart?).
  Recommended: time-limited, so a transient VRAM squatter cannot permanently blacklist a model.
- **T28's headroom value** depends on Open Question 11 (how much slack for non-IRIS processes).
  Must live in the calibration cache, never in source (AC8) — but it needs a starting value.
- **T18/T19** depend on whether seed calibration ships (Open Question 8) — RESOLVED as "no
  seeds", so this is unblocked; the probe exists purely to detect an installed engine.
- **REQ-7 ledger visibility** (Open Question 12) — decide together with the readout transport
  (Q6). Recommended: include it; "brain 4.9 GB · vision 1.0 GB · free 1.4 GB" makes over-commit
  obvious to the user.

## Out of scope for this spec (tracked separately)

- Profile `n_ctx` ceiling: `local_model_manager.py:2824-2827`, narrow-only `min()`.
- Server binary selection: `:3388` `_find_llama_server_binary` returns the first existing path;
  should become capability-based.

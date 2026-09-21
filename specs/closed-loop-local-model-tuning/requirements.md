# Requirements: Closed-loop local model tuning

## Decisions Locked

- **The self-tuning engine already exists and is dormant.** `record_tps()`,
  `_write_tps_correction()`, `ConfigCache` and machine-bandwidth calibration are all
  implemented and unit-tested. `record_tps` is called from **zero** production paths. The
  work is to *invoke* it, not to build it.
- **Measurement source is llama.cpp's own `timings` block**, not a wall-clock estimate. The
  existing `iris_gateway.py:5368` `tps` value measures an entire agent turn using a
  `len(text) // 4` character heuristic and is unsuitable for calibration.
- **Corrections apply to the NEXT load only.** The running model is never reconfigured
  (T4.3). This is an existing guarantee pinned by a test and is non-negotiable.
- **Profile `n_ctx` ceiling and server binary selection are OUT OF SCOPE** for this spec.
  They are real gaps and are tracked separately.
- **Calibration state lives in `.iris-config/` at the project root** — NOT in `.mcm/`
  (the MCM SDK's own directory, holding `coordinates.db` plus ~2.5 GB of backups, and
  gitignored) and NOT next to `SETTINGS_FILE` (because `MODELS_DIR` is user-configurable
  and points at `~/.lmstudio/models` on this machine — IRIS must not write its config
  into a user's model library). Matches the existing `.iris-logs/` / `.iris-pids/`
  convention. **DONE** — see T0.
- **No benchmark is required of the user, ever.** The engine must produce a working config
  with zero user action: GGUF header gives architecture, weights and KV cost are exact
  arithmetic, machine bandwidth is one number learned once and shared by all models. A
  brand-new model inherits everything the machine already knows. Manual controls are
  additive and never block a load.
- **The frontend gets a readout, not a benchmark button.** Users need to see that the engine
  is calibrated and why it chose what it chose — not to run a benchmark themselves.
- **Q1 RESOLVED — device enforcement is purpose-aware, and the brain stays on the GPU, always.**
  User confirmed: *"I usually don't ever run the brain on my CPU."* `chat` and `tool` remain
  GPU-only; a CPU brain is unusable for a voice assistant and this is a deliberate product
  stance. But `embedding` and `rerank` follow `resolve_device_policy` (`:528-540`), which already
  declares them CPU purposes — the argv builder must stop ignoring it. See REQ-11.
- **Q2 RESOLVED — ship no seed calibration. Bias conservative, then grow.** Seeds measured on our
  hardware are exactly the hardware-specific constants REQ-8 AC8 forbids. The asymmetry decides
  it: being slightly too small costs a little context, being too big costs an OOM. An
  uncalibrated machine therefore gets a smaller `n_ctx` and the loop grows it. Cost is one
  imperfect load per *machine*, not per model, because machine bandwidth is shared.
- **Q3 RESOLVED — the loop learns from failure, not only from slowness.** A failing config must
  never be retried identically forever — that is the "signal aborted at 98%" loop. Failure modes
  are distinguished: OOM shrinks and retries (bounded); anything else marks the model unusable
  and stops. See REQ-12.
- **Q4 RESOLVED — VRAM is budgeted against a ledger, not against "whatever is free right now."**
  Confirmed bug: no ledger exists, so the brain is over-committed when the separate vision server
  loads afterwards and the failure surfaces mid-conversation. See REQ-13.
- **MoE placement is for END USERS on hardware we cannot see.** The reference-box benchmark
  (6.9x–18.3x penalty for CPU placement) is evidence that placement matters, not a constant to
  encode. Default GPU, then measure per machine (REQ-8 AC7/AC8).

## Introduction

A local model's ideal context size depends on the model's architecture and the machine's
memory bandwidth. Today the loader guesses: it falls back to a hardcoded `base_tps = 50.0`
because no calibration has ever run. The correction machinery exists but is never fed, so
every load starts cold and no model ever improves.

### Success criteria

- A single generation against a local model produces a `record_tps()` call.
- After three generations, `.mcm/local_model_configs.json` exists and contains an entry
  with a non-null `measured_tps`.
- `local_model_machine_bandwidth.json` exists and contains a non-zero `effective_bandwidth`.
- A subsequent load logs `base_tps` with `source=machine_bandwidth` instead of
  `source=uncalibrated_default`.
- No change to the `generate()` return signature or to the `inference_event` WS payload.

## Requirements

### REQ-1: Extract real generation throughput from the local server

**User Story:** As the tuning engine I want the true tokens/sec reported by llama-server so
that calibration uses a measured number rather than a character-count guess.

**Verified:** `backend/agent/inference/transport.py:398` (`_extract_usage` establishes the
extraction pattern), `:867` (`OpenAICompatTransport.last_usage`), `:946`
(`_record_success(_text, self.last_usage)`), `backend/agent/inference/router.py:973`
(surfacing pattern `self.last_usage = getattr(transport, "last_usage", None)`).

**Acceptance Criteria:**

- AC1: WHEN a chat/completions response from a local provider contains a `timings` block,
  THEN THE SYSTEM SHALL extract `timings.predicted_per_second` and expose it as
  `transport.last_tps` as a float.
- AC2: IF the `timings` block is absent, malformed, or `predicted_per_second` is not a
  finite positive number, THEN THE SYSTEM SHALL set `last_tps` to `None` and SHALL NOT
  fabricate or estimate a value.
- AC3: WHEN `generate()` returns, THEN THE SYSTEM SHALL set `router.last_tps` from the
  transport WITHOUT altering the return signature.
- AC4: THE SYSTEM SHALL reset `last_tps` to `None` at the start of each call, mirroring
  `self.last_usage = None` at `transport.py:914`.

**Edge Cases:**

- Streaming: llama.cpp emits `timings` only in the final chunk — mid-stream chunks have none.
- `predicted_n == 0` (empty completion) → `None`, not a division by zero.
- Non-local providers (OpenAI, Anthropic) return no `timings` → `None`, harmlessly.
- Ollama uses a different response shape → `None` unless a native field is mapped.

### REQ-2: Feed measured throughput into the correction loop

**User Story:** As a user I want the system to learn from ordinary use so that I never have
to benchmark a newly downloaded model by hand.

**Verified:** `backend/agent/local_model_manager.py:2523` (`record_tps`), `:2574`
(`_write_tps_correction`). Confirmed zero production callers: grep across
`backend/iris_gateway.py` and `backend/agent/` surfaces only the definition and comments
(`:273`, `:741`, `:2764`, `:2769`); the sole caller in the repository is
`backend/tests/unit/test_closed_loop_tuning.py`.

**Acceptance Criteria:**

- AC1: WHEN a generation completes against a local provider and `last_tps` is not `None`,
  THEN THE SYSTEM SHALL invoke `LocalModelManager.record_tps(last_tps)`.
- AC2: THE SYSTEM SHALL NOT invoke `record_tps` for a non-local provider.
- AC3: WHILE fewer than three samples have been recorded, THE SYSTEM SHALL record no
  correction (existing behaviour, `local_model_manager.py:2561-2562`).
- AC4: WHILE the rolling mean lies within `TPS_DEADBAND` (0.15) of the target, THE SYSTEM
  SHALL record no correction (existing behaviour, `:2567-2569`).
- AC5: IF `record_tps` raises for any reason, THEN THE SYSTEM SHALL log the exception and
  complete the turn — a failed calibration SHALL never fail a user response.
- AC6: WHILE the machine is uncalibrated (no bandwidth entry), THE SYSTEM SHALL bias the derived
  `n_ctx` toward the conservative end rather than the maximum that fits. Being slightly too small
  costs a little context; being too large costs an OOM or a slow model — the asymmetry is one-sided.
- AC7: WHEN the loop corrects an uncalibrated machine upward, THE SYSTEM SHALL grow `n_ctx`
  incrementally rather than jumping straight to the VRAM ceiling, so a single optimistic
  measurement cannot commit the whole card.

**Edge Cases:**

- No local model loaded → no call, no error.
- Uncalibrated AND the model barely fits → AC6 must not push `n_ctx` below `MIN_CTX`; in that case
  the conservative choice is the smallest workable value, and REQ-8 AC5 surfaces the trade.
- Purpose is `embedding` or `rerank` → `resolve_device_policy` returns a `None` throughput
  target and `record_tps` returns early by design.
- Model loaded but `_current_model_path` / `_current_model_meta` unset →
  `_write_tps_correction` returns early by design (`:2585-2586`).
- Concurrent generations → `record_tps` mutates only an in-memory window plus a
  lock-guarded cache write.

### REQ-3: Corrections never disturb the running model

**User Story:** As a user I want tuning to happen between loads so that a generation in
flight is never reconfigured underneath me.

**Verified:** `backend/tests/unit/test_closed_loop_tuning.py:54-67` (REQ-4 AC4: `record_tps`
must never mutate the running model's params); design intent documented at
`local_model_manager.py:2534-2535`.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL apply a correction only to the configuration used by a SUBSEQUENT
  load.
- AC2: WHEN a correction is written, THEN THE SYSTEM SHALL leave
  `LocalModelManager._current_params` unchanged for the lifetime of the loaded model.

**Edge Cases:**

- A correction fires while a streaming response is in flight → running generation unaffected.
- Unload/load racing a correction write → `ConfigCache` is lock-guarded (`:292`).

### REQ-4: Calibration persists and invalidates itself

**User Story:** As a user I want calibration to survive restarts but be discarded when my
hardware or a model file changes, so stale numbers never mislead the loader.

**Verified:** `local_model_manager.py:295` (`ConfigCache`), `:283` (`LOCAL_MODEL_CONFIGS_PATH`
→ `.iris-config/local_model_configs.json`), `:325` (`_hw_fingerprint` = gpu name + total VRAM),
`:331` (`_model_fingerprint` = path + size + mtime), `:386-388` (machine bandwidth path derives
from the same directory via `with_name`), `:417` / `:428` (put/get machine bandwidth),
`:350-356` (fingerprint mismatch → re-derive), `:442` (`mkdir(parents=True)` on save).
Location change verified: both paths resolve to `C:\dev\IRISVOICE\.iris-config\` and the local
model suite passes 53/54 (the single failure is the known pre-existing environmental one).

**Acceptance Criteria:**

- AC1: WHEN a correction is computed, THEN THE SYSTEM SHALL persist it to both the per-model
  `ConfigCache` and the machine bandwidth cache.
- AC2: IF the current `hw_fingerprint` differs from the cached one, THEN THE SYSTEM SHALL
  discard the entry and re-derive.
- AC3: IF a model file's size or mtime changes, THEN THE SYSTEM SHALL treat it as a new model.
- AC4: IF either cache file is unreadable or corrupt, THEN THE SYSTEM SHALL discard it,
  log a warning, and derive fresh — it SHALL NOT fail the load.
- AC5: THE SYSTEM SHALL store calibration state under `.iris-config/` at the project root and
  SHALL NOT write it into `.mcm/` nor into any user-configured models directory.
- AC6: THE SYSTEM SHALL derive the machine bandwidth path from the per-model cache path so the
  two can never drift apart.

**Edge Cases:**

- Cache directory missing entirely (current state) → `_save()` creates it via
  `mkdir(parents=True, exist_ok=True)` (`:442`).
- Disk write failure → log and continue; never block a load.
- Two models with identical content at different paths → separate entries by design.
- A pre-existing cache left behind at the old `.mcm/` location → ignored; there is no data to
  migrate because that file has never existed on this machine.

### REQ-5: Observability for calibration

**User Story:** As the tuner I want every calibration decision logged with its inputs so
that I can tell whether the loop is converging and tune the thresholds.

**Verified:** NEW (unverified — implementation pending).

**Acceptance Criteria:**

- AC1: WHEN `record_tps` receives a sample, THEN THE SYSTEM SHALL log the measured tps,
  the rolling mean, and the target at DEBUG level.
- AC2: WHEN `_write_tps_correction` writes, THEN THE SYSTEM SHALL log at INFO level: model
  name, measured tps, derived `base_tps`, derived bandwidth, old `n_ctx`, new `n_ctx`, and
  direction (grow / shrink).
- AC3: THE SYSTEM SHALL log at INFO when a sample is discarded because `last_tps` was
  `None`, so the reason a model never calibrates is visible.

**Edge Cases:**

- High call volume → DEBUG only for per-sample lines; INFO reserved for corrections.
- Missing session id → fall back to model name as the log scope.

### REQ-6: Deriver decision log

**User Story:** As the tuner I want the loader to show its arithmetic so I can see which
term actually bounded the chosen context size.

**Verified:** NEW (unverified). Observed `derive_config` output is a single line
(`local_model_manager.py:2827-2840` region) that reports `n_ctx` without the budget, weights,
KV cost, or whether the throughput veto applied.

**Acceptance Criteria:**

- AC1: WHEN `derive_config` selects an `n_ctx`, THEN THE SYSTEM SHALL log at DEBUG:
  `vram_budget_gb`, `weights_gb`, `kv_bytes`, `kv_gb`, `total_est_gb`, and whether the
  throughput veto bound the result.
- AC2: THE SYSTEM SHALL log which term was the binding constraint (VRAM / throughput /
  profile ceiling / native context).

**Edge Cases:**

- Any term unknown or zero → log as `None`, still emit the line.
- Derivation raises → existing handler logs a warning; the decision line SHALL be emitted
  before the failure where possible.

### REQ-7: Calibration readout

**User Story:** As a user I want to see that the engine is calibrated and why it chose what it
chose, so that I trust the automatic config without having to run a benchmark myself.

**Verified:** NEW (unverified — implementation pending). Data sources already exist or are
added by this spec: `ConfigCache.measured_tps` (`:359`), `_tps_window` length (`:2557-2559`),
the REQ-6 decision log, and the REQ-5 AC2 correction log.

**Acceptance Criteria:**

- AC1: WHEN calibration state is queried for a model, THEN THE SYSTEM SHALL report: whether
  it is calibrated or still on the uncalibrated fallback, the measured tok/s when known, the
  chosen `n_ctx`, and which term bound that choice.
- AC2: WHILE fewer than three samples have been recorded, THEN THE SYSTEM SHALL report the
  sampling progress (N of 3) rather than presenting an uncalibrated value as final.
- AC3: WHEN a correction changed `n_ctx` for the next load, THEN THE SYSTEM SHALL surface it
  with both the old and new values and the direction (grow / shrink).
- AC4: THE SYSTEM SHALL expose a manual "re-calibrate" action that invalidates the cached
  entry and clears the sample window.
- AC5: THE SYSTEM SHALL NOT require any user action to produce a working configuration —
  the re-calibrate action is additive and a load SHALL NEVER block on it.

**Edge Cases:**

- No model loaded → report "no model" rather than an empty calibration.
- Cache absent or entry discarded by hardware change → report uncalibrated honestly; SHALL
  NOT fabricate a measurement.
- Model loaded for the first time → report uncalibrated with 0 of 3 samples.
- Purpose is embedding/rerank → no throughput target; report "not applicable" rather than
  an error.

### REQ-8: Measured MoE expert placement

**User Story:** As a user running MoE models I want expert placement decided by measurement on
my machine rather than by a rule written for someone else's hardware, so I never lose throughput
to a placement policy that does not fit my box.

**Verified:** `local_model_manager.py:3598` (`--n-gpu-layers` handling); the PrismML build
exposes `-cmoe` / `--cpu-moe`, `-ncmoe` / `--n-cpu-moe N`, `-ot` / `--override-tensor` and
`-sm` / `--split-mode {none,layer,row,tensor}`.

> **This requirement is for END USERS on hardware we cannot see — not for the developer's
> machine.** A benchmark on the reference box (RTX 3070 8 GB, i7-7700 4c, 16 GB DDR4) measured
> CPU MoE placement at 6.9x–18.3x *slower*. That number is **evidence that placement matters**,
> NOT a constant to encode. A user with unified memory, a high-core-count CPU, or fast DDR5 may
> reach the opposite conclusion, and the engine must be free to. The rule is: **default to GPU
> because weights that fit in VRAM are always faster there — then measure, per machine.**

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL detect an MoE model from GGUF metadata (expert count / expert tensor
  naming) and record it as a model attribute.
- AC2: THE SYSTEM SHALL default MoE expert placement to full GPU offload, unchanged from today.
- AC3: THE SYSTEM SHALL treat expert placement as a tunable dimension in the same `ConfigCache`
  the REQ-2 loop already writes, so a measured win on a given machine can persist.
- AC4: THE SYSTEM SHALL NOT enable CPU expert placement unless a measurement on THIS machine
  shows it is faster, or unless the model provably cannot fit in VRAM at all.
- AC5: WHEN the model cannot fit in VRAM under any GPU-only placement, THEN THE SYSTEM SHALL
  fall back to partial CPU expert placement and SHALL surface the expected throughput cost
  before loading rather than silently degrading.
- AC6: THE SYSTEM SHALL log expert placement as part of the REQ-6 decision line.
- AC7: THE SYSTEM SHALL key placement calibration by a fingerprint that captures the CPU and
  system-memory capability relevant to the decision — NOT by GPU name and VRAM alone. The
  current `_hw_fingerprint` (`local_model_manager.py:325`) is only `gpu_name:total_VRAM` and
  therefore cannot distinguish a machine where CPU placement is viable from one where it is
  catastrophic.
- AC8: THE SYSTEM SHALL NOT encode any hardware-specific throughput constant or placement
  threshold derived from a single machine. Measured values belong in the calibration cache,
  never in source.

**Edge Cases:**

- MoE model whose experts all fit in VRAM → GPU only, never consider CPU.
- Dense model → REQ-8 does not apply; placement stays `n_gpu_layers = -1`.
- Machine with very high CPU-GPU bandwidth (e.g. unified memory) → measurement may favour
  CPU placement; the loop must be free to reach that conclusion (AC7/AC8 guarantee it can).
- Model too large for VRAM even partially → AC5 surface-and-confirm path.
- User has no supported GPU at all → see Open Question 7; today this path is broken.

### REQ-9: Pluggable alternate serving backend for large MoE

**User Story:** As a user who plans to run 35B+ MoE models I want the loader to be able to use a
specialised MoE engine when one is available, without making it a dependency for everyone.

**Verified:** NEW (unverified — implementation pending). `InferenceRouter` already supports
multiple transports (`transport.py:457` `ApiHttpxTransport`, `:851` `OpenAICompatTransport`,
`:1216` `InProcessTransport`, `:1286` `OllamaTransport`) and role bindings with namespaced
provider ids (`router.py:474`, `:492`), so an OpenAI-protocol engine drops in as a provider
rather than requiring a rewrite. FreeToken (arXiv 2608.16157) publishes an OpenAI/Anthropic-
compatible API and is installable via `uv pip install "freetoken[accel]"` (Apache 2.0).

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL probe for an alternate MoE engine at startup and record availability.
  The probe SHALL be cheap, cached, and SHALL NOT block startup.
- AC2: WHERE an alternate engine is available AND the model is MoE AND its weights exceed the
  VRAM that GPU-only placement can hold, THE SYSTEM SHALL prefer the alternate engine.
- AC3: THE SYSTEM SHALL remain fully functional when no alternate engine is installed —
  llama-server stays the default path and no feature is gated on the alternate engine.
- AC4: THE SYSTEM SHALL route through the existing `InferenceRouter` so the alternate engine is
  a provider, not a parallel code path with its own lifecycle.
- AC5: THE SYSTEM SHALL apply the REQ-2 throughput loop to the alternate engine identically, so
  calibration is not lost when routing changes.
- AC6: THE SYSTEM SHALL log which engine served a request and why it was chosen.

**Edge Cases:**

- Alternate engine installed but fails to start → fall back to llama-server and log.
- Alternate engine does not support the model's quantisation (its published formats are MXFP4,
  NVFP4, FP8, BF16; this project's library is GGUF) → fall back, do not fail.
- Model fits fine in VRAM → llama-server, do not invoke the alternate engine.
- Two engines both claim the model → deterministic precedence, logged.

### REQ-10: Frontend wiring is contract-pinned

**User Story:** As a developer I want every backend→frontend boundary this feature touches to be
pinned by a test, so a payload change cannot silently break the UI on a user's machine.

**Verified:** GAP CONFIRMED. Only one frontend test file references models at all
(`__tests__/ModelSwitcher.test.tsx`). The `inference_event` WS payload emitted at
`iris_gateway.py:5358-5372` is **not pinned by any frontend test** — the only backend tests that
mention it (`backend/tests/test_chunk_callback_fix.py` and its behavioural twin) concern chunk
callbacks, not the payload shape. `InferenceConsolePanel` therefore has zero protection against
a backend shape change. By contrast the contract and behavioural suites are well populated
(`backend/tests/contract/`, `backend/tests/behavioral/` including
`test_local_model_lifecycle.py` and `test_local_model_switching_foundation.py`).

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL have a contract test pinning the exact key set of the `inference_event`
  WS payload, so adding, removing or renaming a key fails the build.
- AC2: THE SYSTEM SHALL have a contract test pinning the REQ-7 readout payload shape once its
  transport is chosen (Open Question 6).
- AC3: WHERE the frontend renders a value this feature computes, THE SYSTEM SHALL have a test
  asserting the frontend consumes it under the exact key the backend emits — not merely that the
  backend emits it.
- AC4: THE SYSTEM SHALL pin the `local_model_loading` progress event shape, including that `pct`
  reaches 100 on success (the defect fixed earlier in this session).

**Edge Cases:**

- A key added with a safe default → still fails the pin; the test is the point, not the default.
- Frontend tolerates a missing key today → the pin still applies, because the readout is new.
- Payload emitted by more than one code path → pin each path or factor to one emitter.

### REQ-11: Purpose-aware device enforcement

**User Story:** As a developer I want the GPU-only rule applied where it matters and not where it
doesn't, so that CPU-appropriate workloads work on machines without a supported GPU while the
brain is never silently run on the CPU.

**Verified:** CONTRADICTION CONFIRMED. `_build_server_cmd` forces `n_gpu_layers = -1` whenever it
is `0`, **unconditionally and for every purpose** (`local_model_manager.py:3691-3698`), logging a
warning. Consequences today: (a) `PROFILES["eco"]["n_gpu_layers"] = 0` (`:114`) is dead code;
(b) `resolve_device_policy` (`:528-540`) declares `embedding` and `rerank` to be CPU purposes and
is ignored by the argv builder; (c) a user with no supported GPU cannot load a local model at all,
even for CPU-appropriate work. Pre-flight already branches on device policy — `_preflight_resource_check`
returns early for CPU purposes (`:2339-2345`) — so the builder is the odd one out.

**Acceptance Criteria:**

- AC1: WHILE the purpose is `chat` or `tool`, THE SYSTEM SHALL require GPU placement and SHALL
  NOT fall back to the CPU.
- AC2: IF `chat` or `tool` is requested and no supported GPU is present, THEN THE SYSTEM SHALL
  fail with an explicit, actionable error — it SHALL NOT silently force `-1` and fail later.
- AC3: WHILE the purpose is `embedding` or `rerank`, THE SYSTEM SHALL honour
  `resolve_device_policy` and permit CPU placement.
- AC4: THE SYSTEM SHALL treat `resolve_device_policy` as the single source of truth for device
  selection; `_build_server_cmd` SHALL NOT override it.

**Edge Cases:**

- No GPU and purpose is embedding → CPU, works (this is the case that is broken today).
- No GPU and purpose is chat → loud failure naming the missing capability.
- `eco` profile selected for chat → AC1 wins; the profile cannot smuggle in a CPU brain.
- GPU present but insufficient VRAM → not a device question; handled by REQ-8 AC5 / REQ-13.

### REQ-12: Learn from failure, not only from slowness

**User Story:** As a user I want a config that fails to be tried differently next time, so I am
never stuck in a loop where the same bad load is retried forever.

**Verified:** GAP CONFIRMED. `record_tps` (`:2523`) is the only correction path and it fires only
after a *successful* generation. A load that OOMs or crashes writes nothing, so the identical
config is re-attempted indefinitely. This is the mechanism behind the reported "stuck at 98%,
then signal aborted" experience.

**Acceptance Criteria:**

- AC1: WHEN a load fails with a VRAM-exhaustion signature, THEN THE SYSTEM SHALL write a negative
  correction reducing the attempted `n_ctx` before any retry.
- AC2: THE SYSTEM SHALL bound retries at three attempts and SHALL surface the failure to the user
  if all three fail.
- AC3: IF a load fails for a reason OTHER than VRAM exhaustion (corrupt file, unsupported
  quantisation, missing binary), THEN THE SYSTEM SHALL mark the model unusable and SHALL NOT
  shrink further — otherwise `n_ctx` walks toward zero on a genuinely broken model.
- AC4: THE SYSTEM SHALL NOT re-attempt the exact configuration that just failed.
- AC5: THE SYSTEM SHALL classify the failure and include the class in the log and in the REQ-7
  readout.

**Edge Cases:**

- Failure with no recognisable signature → AC3 default (mark unusable, do not shrink).
- Failure caused by another process taking VRAM concurrently → REQ-13's ledger should prevent it;
  if it still happens, treat as VRAM exhaustion but do not shrink below `MIN_CTX`.
- Retry succeeds → the successful config is what gets cached; the failure leaves no permanent mark.
- Model marked unusable → user must be able to clear the mark manually (T7b's re-calibrate).

### REQ-13: VRAM ledger for concurrently resident models

**User Story:** As a user I want the loader to budget against what is actually available for the
whole session, so that loading a second model doesn't break the first one mid-conversation.

**Verified:** BUG CONFIRMED. There is no VRAM ledger anywhere in the codebase. `derive_config`
budgets against `hw["vram_free_gb"]` (`:2099`), sourced from nvidia-smi `total - used`
(`:1140-1141`) — whatever is free at that instant, with no reservation for models that will load
later. IRIS runs a brain (port 8082) and a separate vision server (port 18181, LFM2.5-VL-3B,
~1 GB) concurrently. If the brain is sized before vision is resident, its KV cache is sized
against memory vision will later take, and the failure surfaces as an OOM mid-conversation. This
is the same failure described in the session-268 note at `iris_gateway.py:8731-8738`.
`_mmproj_reserve` (~`:2766`) reserves for a projector attached to *this* model, not for a separate
process, so it does not cover this case.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL maintain a ledger of VRAM claimed by every resident model, including
  models served by separate processes.
- AC2: WHEN deriving a config, THE SYSTEM SHALL budget against
  `vram_total − ledger_total − headroom`, NOT against instantaneous free VRAM.
- AC3: THE SYSTEM SHALL reserve the vision server's expected footprint up front, before the brain
  is sized, whether or not vision is currently resident.
- AC4: WHEN a model is unloaded, THE SYSTEM SHALL release its ledger entry.
- AC5: IF a ledger entry is stale (process died without deregistering), THEN THE SYSTEM SHALL
  reconcile the ledger against actual GPU usage rather than accumulating phantom claims.

**Edge Cases:**

- Two brains (model switch) → the outgoing entry is released before the incoming is sized.
- Vision server dies and restarts → AC5 reconciliation prevents double-counting.
- Non-IRIS process takes VRAM (another app, browser) → ledger cannot know; headroom absorbs it,
  and REQ-12 AC1 handles the residual OOM.
- Headroom value is machine-specific → belongs in the calibration cache, not in source (AC8).

## Non-Requirements (Out of Scope)

- Removing the profile `n_ctx` hard ceiling (`local_model_manager.py:2824-2827`,
  "the deriver may only NARROW a profile's context, never widen it"). Tracked separately.
- Capability-based server binary selection (`:3388` `_find_llama_server_binary` returns the
  first existing path). Tracked separately.
- Any change to the **existing** `inference_event` WS payload. The REQ-7 readout is a NEW
  surface; it must not alter the shape `InferenceConsolePanel` already consumes (CT-2).
- A head-to-head benchmark UI or model leaderboard. The closed loop learns this for free
  during normal use; a manual comparison surface is a separate feature if users ask for it.
- **Replacing llama-server with an alternate engine.** REQ-9 adds one as an *additional* provider
  used only when the model cannot fit in VRAM. llama-server remains the default for everything
  else, and no user is required to install anything extra.
- **Relaxing the GPU-only rule for dense models.** The benchmark shows CPU placement costs 7-18x
  on this hardware, so `n_gpu_layers = -1` stays. REQ-8 only permits deviation for MoE models,
  and only when measurement or physical capacity forces it.
- Merging `SETTINGS_FILE` (`models/gguf/.iris_model_settings.json`, `:685` — `last_profile`,
  `last_ctx`, `last_gpu_layers`) with `ConfigCache`. These are two per-model stores holding
  overlapping data. Consolidating them is desirable but is a live-code change touching
  `save_model_settings` / `load_model_settings`, so it is deferred — see Open Question 5.
- Benchmarking builds against one another (`GGML_CUDA_FORCE_CUBLAS`, fork choice). Prior
  claims about `GGML_CUDA_FA_ALL_QUANTS` were tested and disproven — FlashAttention is
  already enabled for f16, q8_0 and q4_0 KV caches on the running binary.

## Open Questions

1. **Where should the `record_tps()` call live?** Options: (a) in `InferenceRouter.generate()`
   right after `self.last_tps` is set — central, sees role and provider id, one site;
   (b) in `AgentKernel` alongside the existing `last_usage` consumer at
   `agent_kernel.py:787-800` — closer to turn semantics. Recommend (a) for a single choke
   point, but this is the user's call.
2. **How should "local provider" be detected?** Local instances are namespaced
   `local:<stem>` (`router.py:474`, `:492`). Is an id-prefix test acceptable, or should the
   router expose an explicit `is_local` flag?
3. **Should the first generation of a brand-new model force a measurement?** A cold model
   with no cache entry will take three turns to calibrate. Is that acceptable, or should the
   first load after an unknown model run a short synthetic calibration?
4. **Sample window length** is fixed at 3 (`local_model_manager.py:2558`). Tune later, or
   make it a constant now?
5. **Should `SETTINGS_FILE` and `ConfigCache` be merged?** They are two per-model stores with
   overlapping data (`:685` vs `:291`). Merging is cleaner but touches live settings code, so
   it was deferred out of this spec. Merge now, or after the loop is proven working?
6. **How should the REQ-7 readout reach the UI?** A new WS event, a REST endpoint polled by
   the dashboard, or folded into an existing status payload? Must not alter `inference_event`.
7. **RESOLVED (→ Decisions Locked, REQ-11).** Device enforcement becomes purpose-aware; the brain
   stays GPU-only per the user's confirmation. Embedding/rerank may use CPU.
8. **RESOLVED (→ Decisions Locked, REQ-2 AC6/AC7).** No seed calibration ships. Bias conservative
   on an uncalibrated machine and let the loop grow.
9. **RESOLVED (→ Decisions Locked, REQ-12).** The loop learns from failure. OOM shrinks and
   retries (bounded at 3); other failures mark the model unusable and stop.
10. **RESOLVED (→ Decisions Locked, REQ-13).** Confirmed bug — no VRAM ledger exists and the brain
    is over-committed when the separate vision server loads afterwards. Ledger required.

### Still open

11. **Headroom value for the VRAM ledger (REQ-13 AC5).** How much slack to leave for non-IRIS
    processes? This is machine-specific, so it belongs in the calibration cache — but what is the
    starting value before any calibration exists?
12. **Should the REQ-7 readout show ledger state?** Seeing "brain 4.9 GB · vision 1.0 GB · free
    1.4 GB" would make over-commitment obvious to the user. Worth the extra surface?
13. **Does REQ-12's "mark unusable" persist across restarts?** A transient failure (another app
    briefly holding VRAM) should not permanently blacklist a model. Time-limited, or cleared on
    explicit user action only?

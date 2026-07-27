# Tasks: Caducean Phase Manager (Trig Functional Scheduler) + Inference Rate-Limit Hardening

> Every task links to a requirement ID and carries a RIPPLE note naming the areas it touches
> or depends on. Waves are dependency-ordered; parallelization notes are at the bottom.
>
> **Wave 1 is shipped independently of the scheduler and is NOT behind the feature flag** —
> it is a set of defect fixes (REQ-17 AC3). Waves 2–4 are behind `IRIS_PHASE_SCHEDULER`.
>
> Per `CLAUDE.md`: run the QUALITY CHECK before every test run, never modify a test to make
> code pass, and record MCM events (`record_edit` / `record_create` / `record_test`) as you go.

---

## Wave 0 — Baseline (do this first, it is not optional)

- [ ] **T0.1** Establish a green test baseline. Run the full DER suite and record which tests
  pass, which fail, and which fail for *stale* reasons rather than real breaks. Write the
  counts into this file under "Baseline record" below.
  `pytest backend/tests -q` — RIPPLE: nothing modified. Without this, Wave 1's REQ-17 AC4
  ("no behavioral change with the flag off") is unverifiable, and a pre-existing failure will
  be misattributed to this spec.
- [ ] **T0.2** Capture a replay trajectory for the standing harness: one real multi-step DER
  run with timestamps, provider ids, and per-call roles. Save to
  `backend/tests/fixtures/phase_scheduler_trajectory.json`.
  RIPPLE: consumed by `scripts/validate_phase_scheduler.py` (T4.6) and by the flag-off/flag-on
  comparison. Capture it **before** any edit, or the "before" side of the comparison is lost.

### Baseline record
<!-- T0.1 fills this in: total / passed / failed / stale-failed, with test ids -->

---

## Wave 1 — Stop the bleeding (rate-limit hardening, not behind the flag)

This wave alone is expected to fix the observed `429` behavior. Ship and verify it before
starting Wave 2.

- [ ] **T1.1** (REQ-3) Create `backend/agent/inference/errors.py` with `RateLimitedError`
  carrying `provider_id`, `attempts`, `retry_after`.
  RIPPLE: **new module deliberately separate from `transport.py`** so `resilience.py` can
  import it without creating the cycle `resilience ← agent_kernel → inference.router →
  inference.transport`. Consumed by T1.2, T1.4, T1.5. Pinned by CT-6.

- [ ] **T1.2** (REQ-2) Add a `Retry-After` parser to `backend/agent/inference/transport.py`:
  delta-seconds and HTTP-date forms, clamped to `[0, RETRY_AFTER_MAX_S]`, returning `None` on
  absent/unparseable/negative.
  RIPPLE: used by every `429` branch (T1.3) and published to the meter in Wave 2 (T2.4 wires
  `observe_429`). Keep it a module-level pure function so `test_retry_after_parse.py` can test
  it without HTTP.

- [ ] **T1.3** (REQ-1) Fix the no-sleep `429` retry in **both** streaming paths:
  `ApiHttpxTransport._stream` (`transport.py:259-269`) and `OpenAICompatTransport` streaming
  (`transport.py:517-527`). The `continue` currently jumps past the backoff sleep at
  `transport.py:329-330`. Sleep before continuing, using the T1.2 `Retry-After` when present
  else exponential backoff (`base=1.0, cap=8.0`, jitter — matching `resilience.py:47-52`).
  Do **not** sleep on the final attempt.
  RIPPLE: the non-streaming paths (`transport.py:374-375`, `:618-624`) already sleep correctly
  — verify, do not duplicate. `OllamaTransport` has no `429` branch (local, never rate-limits)
  and must stay unchanged. Guarded by `test_backoff_actually_sleeps.py` (T1.8).

- [ ] **T1.4** (REQ-3) Remove the fabricated-response path. After exhausted `429` retries,
  raise `RateLimitedError` instead of falling through to `return clean or "(I see.)"`
  (`transport.py:345`). Preserve the genuine-empty-`200` reasoning fallback at
  `transport.py:341-342` exactly, and keep `"(I see.)"` reachable **only** for a real empty
  `200`. Apply to both streaming and non-streaming paths of both API-capable transports.
  RIPPLE: this is the user-visible honesty fix — a rate-limited voice turn currently *speaks*
  `"(I see.)"`. Downstream consumers of the raised error: T1.5 (classification), T1.6 (step
  reporting). Guarded by `test_rate_limit_honesty.py` (T1.8) and CT-7.

- [ ] **T1.5** (REQ-4) Add `NO_RETRY_ERRORS = (RateLimitedError,)` to
  `backend/agent/resilience.py` and check it **before** `TRANSIENT_ERRORS` in **both** twins
  (`retry_with_backoff` `:56-77` and `retry_with_backoff_sync` `:96-117`). Re-raise immediately.
  RIPPLE: both twins must change — the sync twin is what the DER loop uses
  (`agent_kernel.py:5674`), the async twin is used by skill/concurrent paths. Missing one leaves
  half the stacking in place. `RateLimitedError` must be in **neither** `TRANSIENT_ERRORS` nor
  `PERMANENT_ERRORS` (CT-6): a rate limit is not permanent, and the distinction changes the
  graft path's messaging.

- [ ] **T1.6** (REQ-3 AC4/AC5, REQ-4 AC3) In `agent_kernel.py`, surface the rate-limit cause
  honestly. In `_run_step` (`:5656-5671`), let `RateLimitedError` propagate rather than being
  re-wrapped as `ValueError`. In `_der_handle_step_failure`, include provider id and retry hint
  in the step failure text so the existing `TASK_BLOCKED` escalation reports the real cause.
  RIPPLE: touches the graft/failure path shared with every other step failure — assert the
  existing failure behavior for non-rate-limit errors is unchanged. The commit-ledger row must
  be written with `verified_label="FAILED"`, preserving `specs/der-loop-integrity-display`
  REQ-1 (CT-7).

- [ ] **T1.7** (REQ-4 edge case) Make the extra/parallel step retry at
  `agent_kernel.py:5766-5771` respect single-retry-authority: its ad-hoc `time.sleep(0.5)` +
  re-execute must not fire for `RateLimitedError`.
  RIPPLE: this path is easy to miss because it is a hand-rolled retry outside
  `retry_with_backoff_sync`. It is a third retry layer on the concurrent branch specifically.

- [ ] **T1.8** (REQ-1, REQ-2, REQ-3, REQ-4) Tests for Wave 1:
  - `backend/tests/unit/test_retry_after_parse.py` — all six header cases.
  - `backend/tests/behavioral/test_backoff_actually_sleeps.py` — patch the transport sleep,
    assert one sleep per `429` retry in the **streaming** path.
  - `backend/tests/behavioral/test_rate_limit_honesty.py` — the headline test: response is
    never `"(I see.)"`, `RateLimitedError` propagates, step reported failed with provider
    named, `FAILED` ledger row exists, total HTTP attempts ≤ 3 (**not 9**).
  - `backend/tests/contract/test_rate_limit_error_contract.py` — CT-6, CT-7.
  RIPPLE: `test_backoff_actually_sleeps` is the permanent guard for the exact defect at
  `transport.py:259` (Intertwined principle — the behavioral gap becomes a contract).

- [ ] **T1.9** (REQ-5) Bound the concurrent fan-out. Add an `asyncio.Semaphore` sized by
  `DER_MAX_CONCURRENT_STEPS` (new constant in `der_constants.py`, env-overridable) inside
  `_der_exec_steps_concurrent` (`agent_kernel.py:6960-6977`). Acquire per task, release in a
  `finally`.
  RIPPLE: the return contract `{step_id: (result, success)}` must hold for **every** submitted
  item (CT-2) — `_execute_plan_der` indexes it directly at `agent_kernel.py:5765`, so a missing
  key is a `KeyError` in the loop. Keep the serial fallback at `:5758-5763` intact.
  `DER_MAX_CONCURRENT_STEPS` goes in `der_constants.py` (not the scheduler modules) because it
  genuinely is DER-scoped.

- [ ] **T1.10** (REQ-5) `backend/tests/behavioral/test_bounded_fanout.py` — 8 ready
  parallel-safe steps with limit 3; assert peak in-flight ≤ 3 and all 8 results returned.
  Plus `backend/tests/contract/test_concurrent_exec_contract.py` for CT-2.
  RIPPLE: CT-2 is what stops a future refactor from silently dropping a step from the result
  dict.

- [ ] **T1.11** Re-run the full DER suite. Compare against the T0.1 baseline. Zero new
  failures. Then `record_test` each new test as passing and `pin_add` the Wave 1 decision.
  RIPPLE: gate for starting Wave 2. Do not proceed on a red suite.

---

## Wave 2 — Measurement: per-provider adaptive rate meter (behind the flag)

- [ ] **T2.1** (REQ-6, REQ-8) Create `backend/agent/rate_meter.py`: `ProviderRateMeter`
  singleton with `ProviderWindow` / `Sample` dataclasses, a `threading.Lock` (same discipline
  as `coupled_registry.py:93`), age-based eviction bounded by `METER_MAX_SAMPLES`, and
  `metered` derived from `ProviderInstance.kind` alone (`API` metered; `LOCAL_OPENAI`,
  `OLLAMA`, `INPROCESS` unmetered).
  RIPPLE: must be safe under concurrent access from the event loop **and** the DER executor
  thread (`agent_kernel.py:6949`). No per-provider allowlist — REQ-8 AC4 requires deriving from
  `kind`, so registering a cloud proxy as `local_openai` is a documented misconfiguration, not
  a code branch. Include a `reset_*_for_testing()` accessor per `coupled_registry.py:234`.

- [ ] **T2.2** (REQ-6 AC1/AC4) Implement `record_request(quota_id, tokens, priority,
  estimated, label=None)` and `draw(quota_id) -> {requests, tokens, window_s}`, both keyed by
  quota identity (REQ-6 AC1, design D-9) — never by `ProviderInstance.id`. The optional `label`
  is the instance id, retained for logs only (REQ-6 AC1b). Token count from the
  provider's usage block when available, else estimated from character length using the
  existing 4-chars≈1-token convention (`agent_kernel.py:5283`), flagged `estimated=True`.
  RIPPLE: `draw()` must be side-effect free — it is called from the coupling path on every
  advance. Negative sample age (clock skew) → treat as 0, never evict the window.

- [ ] **T2.3** (REQ-7) Implement the AIMD ceiling: multiplicative decrease `×CEILING_MD` on
  `429` floored at `CEILING_MIN_RPM`; additive increase `+CEILING_AI_RPM` after
  `CEILING_PROBE_S` without a `429`, capped at `min(CEILING_MAX_RPM, configured_max_rpm)`.
  Ceilings strictly per provider.
  RIPPLE: REQ-7 AC6 — a `429` from one provider must not touch another's ceiling. This is the
  single most important isolation property of Decision Locked #2 and gets its own unit test.

- [ ] **T2.4** (REQ-7 AC5) Persist learned ceilings to `.mcm/provider_ceilings.json`, following
  the `outer_loop.py:62-64` params-store pattern with the same corrupt-file tolerance as
  `outer_loop._load_params` (`:69-76`). Load on init, save on change (debounced).
  RIPPLE: **separate file** from `.mcm/der_params.json` — do not touch the outer loop's store.
  Unknown keys in a file written by a future version must be ignored, not fatal.

- [ ] **T2.5** (REQ-2 AC5, REQ-6 AC1, REQ-7 AC2) Wire the transport's `429` observation into the
  meter: `observe_429(quota_id, retry_after)` from every `429` branch. Implement
  `quota_key(inst) = f"{inst.api_base_url}|{sha256(credential)[:12]}"` and pass it into the
  transport constructor at `router._build_transport`
  ([router.py:310-339](backend/agent/inference/router.py:310)), where `inst` is in scope.
  RIPPLE: **do NOT change the transport cache key.** Transports are cached by
  `(kind, api_base_url)` ([router.py:49-62](backend/agent/inference/router.py:49)) and that is
  fine — the meter is keyed by *quota identity*, not by transport or instance, so the shared-cache
  question is moot (design **D-9**). Two earlier candidate fixes are explicitly rejected there and
  should not be re-derived: keying by `inst.id` **over-partitions** (two instances on one real
  quota each learn half the truth, and their summed ceilings can exceed the real limit, producing
  unexplainable `429`s); keying by `api_base_url` alone **under-partitions** (two accounts at one
  provider would corrupt each other's ceiling). Because the quota key is derived from
  `(base_url, credential)`, a shared transport carries the *correct* key by construction — no
  per-call threading. Credential is hashed, never logged (logs use `label_ids`, REQ-6 AC1b) and
  never persisted in clear (REQ-7 AC5 keys the ceilings file by fingerprint).

- [ ] **T2.6** (REQ-10) Implement the hard rail: `PHASE_HARD_MAX_RPM` per provider, never
  raised by learning. Log at WARNING once per provider when the rail is the binding constraint
  (i.e. below the learned ceiling).
  RIPPLE: the rail's interaction with the priority lane is REQ-10 AC4 — priority is admitted
  even when the rail is exhausted. Write the honest-limit paragraph (REQ-10 AC5) into the
  module docstring now, while the reasoning is fresh.

- [ ] **T2.7** (REQ-6, REQ-7, REQ-8, REQ-10) Tests:
  - `backend/tests/unit/test_meter_window.py` — eviction, bound, clock skew, estimation flag.
  - `backend/tests/unit/test_ceiling_aimd.py` — MD/AI, floors, caps, **cross-quota isolation**.
  - `backend/tests/unit/test_quota_key.py` — all four D-9 partitioning cases (same endpoint +
    same key → same quota; same endpoint + different keys → different quotas; different endpoints
    → different; no credential → stable `"nokey"`), plus: the raw credential never appears in the
    key.
  - `backend/tests/behavioral/test_local_provider_never_gated.py` — mixed cloud/local plan.
  - `backend/tests/contract/test_quota_key_contract.py` — CT-10: meter windows, ceilings, and
    coupling groups are all keyed by `quota_id` and never by `ProviderInstance.id`; no credential
    appears in any log line, persisted file, or exception message.
  RIPPLE: the mixed-plan test catches an accidental global ceiling (Decision Locked #2). CT-10 is
  the guard against the two rejected keying schemes in design **D-9** creeping back in — both are
  easy to reach for and each is wrong in a different direction.

---

## Wave 3 — The Caducean Phase Manager (behind the flag)

- [ ] **T3.1** (REQ-14) Create `backend/agent/call_context.py`: `CallClass` enum,
  `PRIORITY_CLASSES`, the `ContextVar` defaulting to `BACKGROUND`, a `set_call_class()`
  setter, and a `call_class()` reader.
  RIPPLE: mirror `backend/monitoring/session_correlation.py:18-21`, which is the existing
  `ContextVar` precedent in this codebase. The `BACKGROUND` default is load-bearing: an
  unclassified call must be **gated**, never accidentally privileged (REQ-14 AC3).

- [ ] **T3.2** (REQ-11, REQ-15, REQ-16) Create `backend/agent/phase_manager.py`:
  `PhaseOscillator` (`__slots__`, per `coupled_registry.py:76`), the thread-safe singleton
  registry, `register` / `unregister` / `snapshot`, idempotent re-registration that
  **preserves** θ and `r` (REQ-11 AC3), and deterministic widest-gap placement among
  oscillators sharing the provider (REQ-11 AC2).
  RIPPLE: no API may let one registrant address another (REQ-15 AC2) — this is enforced by
  omission, so review the public surface deliberately. `MIN_PERIOD_S` clamp prevents divide-by-
  zero on `natural_period_s <= 0`. Include `reset_*_for_testing()`.
  ⚠️ **Group by `quota_id`, not `ProviderInstance.id`** (REQ-11 AC1, REQ-12 AC6, design D-8/D-9).
  Instance grouping under-couples two instances that share one real quota — they would land in
  separate coupling groups and be free to fire simultaneously into the one limit the scheduler
  protects, with every unit test still green. `test_shared_quota_is_coupled.py` (T3.9) is the guard.
  Keep `provider_label` on the oscillator for logs only.

- [ ] **T3.3** (REQ-12) Implement `advance()` with the repulsive Kuramoto rule
  `dθᵢ/dt = ωᵢ_eff + (K/N)·Σ_{j≠i} sin(θᵢ − θⱼ)`, `K > 0`, summed **only** over oscillators
  sharing the same `quota_id` (D-8 — **not** `ProviderInstance.id`; instance grouping under-couples
  two instances on one real quota). Lazy `dt` from elapsed wall-clock, clamped to
  `TICK_MAX_DT_S`. `N` recomputed live per advance (REQ-16 AC3).
  **Import the coupling kernel from `backend/agent/trig_coupling.py`** — do NOT inline the sine
  math. If that module does not exist yet, land
  `specs/caducean-kernel-unification/` T3.1 + T3.2 first (they are small, self-contained, and
  have no other dependency). See `specs/CADUCEAN_SPEC_RECONCILIATION.md` C3.
  RIPPLE: **the sign is the whole feature.** `+(K/N)Σ sin(θᵢ − θⱼ)` repels; the standard
  `+(K/N)Σ sin(θⱼ − θᵢ)` attracts and would produce the opposite of the goal. Verify against
  `test_phase_math.py` (T3.9) before wiring anything else. No `ffi_caducean_*` call may appear
  in this module, and `trig_coupling.py` must stay import-pure so consuming it cannot breach
  CT-4 (kernel-unification CU-1 enforces that).

- [ ] **T3.4** (REQ-9) Implement amplitude: `r` relaxing toward `1 − load_fraction` with rate
  `R_GAMMA`, floored at `R_MIN`, and applied as `ω_eff = ω · r`. A new registrant into a
  saturated provider starts at `1 − load_fraction`, not 1.0.
  RIPPLE: reads `rate_meter.draw()` (T2.2) and the learned ceiling (T2.3), so Wave 2 must land
  first. Unmetered provider → `load_fraction = 0` → `r → 1.0` → amplitude inert (REQ-8/REQ-9
  consistency). Do **not** touch `max_tokens` (REQ-9 AC6).

- [ ] **T3.5** (REQ-13, REQ-14, REQ-10) Implement the gate: `acquire()` (sync, `time.sleep`)
  and `acquire_async()` (async, `asyncio.sleep`) with identical semantics. Order of checks:
  flag off → admit; priority class → admit with zero wait; unmetered provider → admit;
  advance + amplitude; hard rail; phase firing mark; wait clamped to `PHASE_MAX_WAIT_S`; on
  admit reset θ toward the next cycle atomically (REQ-13 AC5). Wrap the whole body so any
  internal exception logs at WARNING and **admits** (fail-open, REQ-13 edge case).
  RIPPLE: follow the twin pattern at `resilience.py:37/80`. `acquire_async` must never call
  `time.sleep` (CT-9) — sleeping on the event-loop thread would stall WS and audio streaming.

- [ ] **T3.6** (REQ-13 AC1/AC4, REQ-6 AC2/AC3) Wire the gate into
  `InferenceRouter.generate()` (`router.py:343-399`): lazy import, `acquire` before dispatch,
  `record_request` after. Signature and 3-tuple return unchanged.
  RIPPLE: this single insertion governs every loop (D-1) — `AgentKernel.infer`
  (`agent_kernel.py:610`), `Reviewer` (`der_loop.py:597`), `TrailingDirector`
  (`trailing_director.py:100`), `spec_engine`, `ask_user_tool`, the memory paths, the four
  direct kernel sites, and `tool_decision.py:292`. **No loop file is edited.** Verify CT-1
  before and after.

- [ ] **T3.7** (REQ-14 AC4) Set the call class explicitly at the top of `_execute_plan_der`
  ([agent_kernel.py:5239](backend/agent/agent_kernel.py:5239)) and at the user-turn entry point,
  and set `CallClass.SUBLOOP` on Sub-Loop children. Set `CallClass.SPEAK` around `speak_tool`'s
  output path ([speak_tool.py:46](backend/agent/tools/speak_tool.py:46)).
  RIPPLE — **two distinct executor hops; the first is confirmed and load-bearing, the second is
  defensive:**
  1. **Entry hop (CONFIRMED reachable).** The whole DER loop runs off the event loop. The REST
     path is an explicit `await loop.run_in_executor(None, lambda: kernel.process_text_message(...))`
     ([api/chat.py:199](backend/api/chat.py:199)); the WS paths call
     `process_text_message` synchronously from a worker thread
     ([iris_gateway.py:2699](backend/iris_gateway.py:2699),
     [:4623](backend/iris_gateway.py:4623)). `run_in_executor` does **not** copy `contextvars`
     (unlike `asyncio.to_thread`), so a ContextVar set on the event loop is invisible in that
     thread and `call_class()` returns the `BACKGROUND` default. **This is why the explicit set
     must happen inside `_execute_plan_der`, in that thread.** `test_contextvar_across_executor`
     (T3.9) asserts that removing the set breaks the behavior, so it is provably load-bearing.
  2. **Nested hop (defensive — currently NOT reachable in normal config).** Also set the call
     class at the top of `_run_step_direct`
     ([agent_kernel.py:6626](backend/agent/agent_kernel.py:6626)), taking it as a parameter.
     Reason: `_der_run_step_execution_async` reaches `_run_step_direct` through a *second*
     `loop.run_in_executor` ([:6947-6951](backend/agent/agent_kernel.py:6947)), which loses the
     context again. **Verified currently unreachable** — that branch needs a `parallel_safe` step
     with no tool, and `is_parallel_safe(None)` returns `False` (fail-closed,
     [tool_registry.py:159-179](backend/agent/tool_registry.py:159)), so tool-less steps never
     enter the concurrent batch. It becomes reachable if `_tool_bridge is None` (degraded/test
     config) or if a reasoning step is ever marked parallel_safe. The serial path is safe — it
     calls `_run_step_direct` **directly**, same thread
     ([:6905](backend/agent/agent_kernel.py:6905)). Add the guard anyway: it is one parameter, and
     the failure mode if the path ever opens is silent (a user turn quietly gets gated, no error
     anywhere).

- [ ] **T3.8** (REQ-17) Feature flag `IRIS_PHASE_SCHEDULER`, default disabled. Flag-off makes
  `acquire`/`acquire_async` immediate no-ops with no advance, no metering, no coupling. Log the
  flag state exactly once at first gate use, at INFO. Unparseable value → disabled + warning.
  RIPPLE: Wave 1's fixes (T1.1–T1.11) are **not** behind the flag (REQ-17 AC3) — they are
  defect fixes. Only Waves 2–4 are gated. `test_flag_off_is_identical` (T3.9) patches the
  scheduler internals and fails on any call.

- [ ] **T3.9** (REQ-9, REQ-11, REQ-12, REQ-13, REQ-14, REQ-16, REQ-17) Tests:
  - `backend/tests/unit/test_phase_math.py` — separation at Δθ=0.1, coupling ≈0 at splay for
    N=2 and N=3, `K=0` safe, `dt` clamp, deterministic placement N=1..5.
  - `backend/tests/unit/test_amplitude_relaxation.py` — relaxation, `R_MIN` floor, new
    registrant starts below 1.0 in a saturated provider.
  - `backend/tests/behavioral/test_priority_lane_never_waits.py` — saturated past the hard
    cap, `USER_TURN` and `SPEAK` both admitted with zero wait and no sleep invoked.
  - `backend/tests/behavioral/test_contextvar_across_executor.py` — correct class inside the
    executor thread; removing the explicit set fails the assertion.
  - `backend/tests/behavioral/test_flag_off_is_identical.py` — REQ-17 AC2/AC4.
  - `backend/tests/contract/test_phase_gate_contract.py` — CT-1, CT-9.
  - `backend/tests/contract/test_scheduler_isolation.py` — CT-3, CT-4: patch the FFI and the
    coupled registry, fail on any call from scheduler modules.
  - `backend/tests/behavioral/test_phase_physics_invariance.py` — inject `u ∈ {−1, 0, +1}`
    and assert identical θ/wait/amplitude; and assert `|u| < U_SPLIT` still yields split
    width 3 with the flag on (`agent_kernel.py:6170-6185`).
  - `backend/tests/behavioral/test_shared_quota_is_coupled.py` — two oscillators on **different
    `ProviderInstance.id`s resolving to the same `quota_id`** land in ONE coupling group and are
    spread in θ; two on the same endpoint with **different credentials** land in separate groups
    and are NOT spread. Distinguishes quota grouping from instance grouping (design D-8).
  - Rebalance test for REQ-16 AC4 (three → two converge to ~π within `REBALANCE_TICKS`).
  RIPPLE: `test_scheduler_isolation` is the enforceable form of D-2. Without it, "the scheduler
  does not read reasoning state" is an intention rather than a property.

- [ ] **T3.10** (REQ-20) Instrumentation: one structured line per gate decision (oscillator id,
  provider id, call class, θ, amplitude, computed wait, actual wait, admitted/blocked, reason);
  DEBUG for admitted-with-zero-wait, INFO+ for waits/blocks/ceiling changes; every line scoped
  by provider id and conversation-or-session id; `metrics()` snapshot per provider including
  draw, ceiling, `429` count, admissions, waits, total wait time, and **mean/stddev of
  inter-request gaps**.
  RIPPLE: the gap distribution is what makes the ≥50% stddev-reduction success criterion
  checkable (REQ-20 AC6) and is what the harness (T4.6) reads. Missing conversation id (REST
  path, `backend/api/chat.py:305`) → fall back to session id then `"unknown"`; never raise from
  the logging path. Follows the `CLAUDE.md` requirement of a context identifier in every log line.

---

## Wave 4 — Bounded Sub-Loop batching at the compression seam (behind the flag)

- [ ] **T4.1** (REQ-11 AC1, REQ-18 AC1) Extend registration with `join_point` and `independent`,
  and expose `window(oscillator_id)` returning the oscillator's current θ so the batcher can
  test proximity.
  RIPPLE: these are the *only* two additional facts the manager learns (concept doc §7), and
  they must stay optional with safe defaults so REQ-15 AC1 still holds — a registrant that
  knows nothing about batching is unaffected.

- [ ] **T4.2** (REQ-18) Create `backend/agent/batch_dispatch.py`: `SubLoopBatcher` with
  `BatchGroup`, grouping only children that share a `join_point`, are `independent`, whose θ
  fall within `BATCH_WINDOW_RAD`, capped at `BATCH_MAX_CHILDREN` (3), and never held longer
  than `BATCH_MAX_HOLD_S`.
  RIPPLE: consumes `_split_step` output unchanged — children already arrive with
  `is_subloop=True` (`agent_kernel.py:6252`), `tool=None`, per-child `expected_output`
  (`:6251`), and ids `{parent}_s{i}` (`:6246`) giving a natural `join_point`. `_split_step`
  itself is **NO CHANGE (verified)**. `BATCH_MAX_CHILDREN = 3` matches `DER_MAX_GRAFTS`
  (`der_constants.py:104`) and the wide-split width (`agent_kernel.py:6182`).

- [ ] **T4.3** (REQ-19 AC1) Compose the batched prompt: one sub-task per child, each fenced by
  an unambiguous machine-parseable delimiter keyed to the child's `step_id`, each carrying its
  own `expected_output` criterion.
  RIPPLE: heterogeneous `expected_output` across children is the normal case, so per-child
  criteria are required for `_verify_step_result` (`agent_kernel.py:6995`) to stay meaningful.

- [ ] **T4.4** (REQ-19) Parse and attribute: exactly one segment per child, matched **by
  `step_id` label, not by position**; assign to `QueueItem.result`. IF any requested child is
  unmatched THEN discard the whole batched response and re-dispatch every child individually,
  logging at WARNING with the child ids. Never populate a child's result from a partial parse
  or infer it from siblings. Unmatched *extra* segments are ignored and do not themselves
  trigger the fallback.
  RIPPLE — **the propagation path is NOT `depends_on`; know the real one before you start.**
  `_split_step` creates children with **no `depends_on`** and with
  `step_number = parent.step_number` ([agent_kernel.py:6245-6254](backend/agent/agent_kernel.py:6245)).
  `resolve_dependent_params` injects a completed item's result into a pending item when *either*
  the pending item lists it in `depends_on` **or** — the reachable case here — the pending item has
  **no `depends_on` and `step_number == completed.step_number + 1`**
  ([der_loop.py:519-525](backend/agent/der_loop.py:519)). Since every child carries the parent's
  `step_number`, a child's result is injected into **the step following the parent**, via that
  implicit-sequential rule. It lands in `params["_dependency_results"][child_step_id]` and also
  substitutes any `{{step_id}}` / `{{step_number}}` placeholder in string params
  ([der_loop.py:534-538](backend/agent/der_loop.py:534)). `resolve_dependent_params` is called for
  **every** finalized item including children
  ([agent_kernel.py:7299](backend/agent/agent_kernel.py:7299)), so there is no path where a
  misattributed child result stays contained. That is why REQ-19 AC3's fallback discards the whole
  batch rather than salvaging part of it — a partial attribution is not a degraded result, it is
  wrong input to a later step, surfacing far from its cause. Each child then runs its normal
  `_verify_step_result` unchanged (REQ-19 AC5). Pinned by CT-5, CT-8.

- [ ] **T4.5** (REQ-18 AC5/AC6) Integrate the batcher into the DER path so batching is
  transparent to the parent: the parent still observes exactly **one** collapse into a single
  `COMPRESS`. Count a batched dispatch as **one** request in the meter. Respect soft-cancel
  (`agent_kernel.py:5613`) by abandoning the batch and attributing no results.
  RIPPLE: this is the load-bearing claim of concept doc §7, verified against
  `agent_kernel.py:6252` — the parent never watched children individually, so batching adds no
  new wait. If integration requires the parent to observe children, stop: the premise has
  broken and the design needs revisiting before proceeding.

- [ ] **T4.6** (REQ-18, REQ-19, REQ-20 AC6) Tests + standing harness:
  - `backend/tests/behavioral/test_batch_attribution.py` — three children, exactly **one**
    transport invocation, all three results from their own segment, one parent collapse.
  - `backend/tests/behavioral/test_batch_parse_failure_fallback.py` — one-segment response;
    batch discarded, no partial/inferred result, all three re-dispatched, WARNING with ids.
  - `backend/tests/behavioral/test_batch_never_holds_fast_child.py` — fast child dispatches
    within `BATCH_MAX_HOLD_S`; the concept doc §7 "honest tension" as an assertion.
  - `backend/tests/contract/test_batch_contract.py` — CT-5, CT-8.
  - `scripts/validate_phase_scheduler.py` — replays the T0.2 trajectory through the full stack
    **twice** (flag off, flag on) and asserts all seven harness properties from design.md,
    including the ≥50% inter-request-gap stddev reduction.
  RIPPLE: the harness joins `validate_der_integrity.py` / `validate_der_tool_resolution.py` as
  a standing instrument. It is where `PHASE_K` actually gets chosen — concept doc §8 is explicit
  that the constant cannot be assumed in advance, so do not hardcode a "tuned" value before the
  harness has produced a number.

- [ ] **T4.7** Tune and record. Run the harness across `PHASE_K ∈ {0.2, 0.4, 0.6, 0.9}` and
  `BATCH_WINDOW_RAD ∈ {0.2, 0.35, 0.5}`. Record the chosen values and the measured stddev
  reduction in this file under "Tuning record". Answer Open Questions Q1–Q4 from the data where
  possible.
  RIPPLE: closes the loop on requirements.md Open Questions. Update the **Decisions Locked**
  section with any question the data settles, so a future session does not re-litigate it.

### Tuning record
<!-- T4.7 fills this in: PHASE_K, BATCH_WINDOW_RAD, measured stddev reduction, Q1-Q4 answers -->

---

## Wave 5 — Close-out

- [ ] **T5.1** Full-suite verification: `pytest backend/tests -q` plus all four
  `scripts/validate_*.py` harnesses, with the flag **off** and then **on**. Zero new failures
  in either configuration versus the T0.1 baseline.
- [ ] **T5.2** MCM anchoring per `CLAUDE.md`: `record_test` for every new test file,
  `pin_add(title='caducean_phase_scheduler', pin_type='decision')`, then
  `mcm_define_feature(name='caducean_phase_scheduler', seed_files=['backend/agent/phase_manager.py',
  'backend/agent/rate_meter.py', 'backend/agent/call_context.py', 'backend/agent/batch_dispatch.py',
  'backend/agent/inference/transport.py'], thread_id='<session-id>')`, then
  `mcm_crystallize_landmark(...)`, then `mcm_compress(...)`.
- [ ] **T5.3** Mark `docs/caducean-phase-manager-trig-scheduling.md` as superseded for as-built
  purposes, with a pointer to this spec and to the corrections table in requirements.md. Leave
  the concept doc intact — it is the design rationale and remains worth reading; it is just not
  the as-built description.

---

## Dependency / parallelization notes

**Hard sequencing:**

- **T0.1 and T0.2 gate everything.** T0.2 especially — the flag-off replay baseline cannot be
  captured after the code changes.
- **Wave 1 → Wave 2.** T2.5 (`observe_429` wiring) needs `RateLimitedError` (T1.1) and the
  `Retry-After` parser (T1.2) to exist.
- **Wave 2 → Wave 3.** T3.4 (amplitude) reads `draw()` (T2.2) and the learned ceiling (T2.3).
  T3.5's hard-rail branch needs T2.6.
- **Wave 3 → Wave 4.** T4.2 needs `window()` (T4.1) which needs the registry (T3.2).
- **T3.3 before everything else in Wave 3.** If the coupling sign is wrong, every downstream
  behavioral test is measuring the opposite of the intended effect. Verify T3.3 against
  `test_phase_math.py` in isolation first.

**Parallelizable:**

- Inside Wave 1: **T1.9/T1.10 (bounded fan-out) are fully independent of T1.1–T1.8** (rate-limit
  handling). Two agents can take these concurrently — they touch different files
  (`agent_kernel._der_exec_steps_concurrent` vs `transport.py`/`resilience.py`).
- Inside Wave 2: T2.1–T2.4 (meter + ceiling, `rate_meter.py`) and T2.5 (transport wiring) can
  proceed in parallel once the `observe_429` signature is agreed. Agree it in writing first.
- Inside Wave 3: T3.1 (`call_context.py`) is independent of T3.2/T3.3 (`phase_manager.py`) and
  can be done concurrently.
- All test-writing tasks (T1.8, T1.10, T2.7, T3.9, T4.6) can be written **before** their
  implementation tasks — the tests are the requirement (`CLAUDE.md`, absolute rule). Writing
  them first is the recommended order, not merely permitted.
- **No frontend work exists in this spec at all**, so there is no backend/frontend split to
  coordinate.

**NO-CHANGE-verified areas that need only a contract test** (no implementation work — reviewers
should see at a glance that these are not being modified):

| Area | Contract test | Task |
|---|---|---|
| `coupled_registry.py` — reasoning-state coupling stays as-is | CT-3 | T3.9 |
| Caducean FFI — never called from the scheduler | CT-4 | T3.9 |
| `QueueItem` field shape | CT-5 | T4.6 |
| `outer_loop.py` — no LLM calls, not registered | none needed | — |
| `der_loop.Reviewer` — governed via `AgentKernel.infer` with zero edits | CT-1 | T3.9 |
| `_split_step` / `_growth_width` — physics-driven shape, out of scope | physics-invariance test | T3.9 |
| `ws_event_bridge.py` + frontend — no new bridged event | none needed | — |

**Riskiest tasks, flagged for extra review.** Each was re-validated against the code on
2026-07-27; the notes below record what is confirmed, what is conditional, and — for T3.3 — where
the earlier draft of this list was **wrong**.

1. **T3.3 — the coupling sign. VALID, but this list previously overstated it.**
   The earlier wording claimed "every higher-level test would still pass." **That is false**, and
   an implementer should know the guards exist rather than inventing new ones:
   - `test_phase_math.py` (T3.9) asserts two oscillators at Δθ=0.1 **separate**. A flipped sign
     makes them converge → this test fails. It is the cheap, primary guard.
   - Harness assertion 6 (`validate_phase_scheduler.py`, T4.6) requires inter-request-gap stddev
     to *fall* ≥50%. Synchronization *raises* stddev, so the harness fails too.
   What remains true is the narrower and still-important point: **no behavioral test catches it**,
   because sync and splay both produce "calls were made, nothing crashed." Get the sign right by
   construction, then let `test_phase_math.py` confirm it before anything else is wired.
   **The sign in REQ-12 AC2 is correct as written — verified by hand:** with
   `dθᵢ/dt = ωᵢ_eff + (K/N)·Σ sin(θᵢ − θⱼ)`, `K > 0`, and N=2 at θ₁=0, θ₂=0.1 —
   θ₁ gets `+(K/2)·sin(−0.1) < 0` (moves down), θ₂ gets `+(K/2)·sin(+0.1) > 0` (moves up) →
   they separate. At Δθ=π, `sin(±π) = 0` → coupling vanishes (splay fixed point). At 2π/3 spacing
   with N=3, `sin(−2π/3) + sin(−4π/3) = −0.866 + 0.866 = 0` → also vanishes. Note the argument
   order is `(θᵢ − θⱼ)`; the **standard sync** form is `sin(θⱼ − θᵢ)`. Reversing the subtraction
   is exactly the bug.

2. **T2.5 — VALID, and the fix changed.** The risk is real: attributing a `429` to the wrong
   quota corrupts a learned ceiling. But **both remedies this list originally proposed were
   wrong** — keying by `inst.id` over-partitions a shared quota; keying by `api_base_url` alone
   under-partitions separate accounts. Superseded by design **D-9**: key the meter by
   `quota_key(inst) = (api_base_url, credential-fingerprint)` and **leave the transport cache
   alone**. Do not re-derive the rejected options.

3. **T3.7 — VALID and confirmed, with a second hop that is currently unreachable.**
   Hop 1 (entry) is confirmed: [api/chat.py:199](backend/api/chat.py:199) is an explicit
   `run_in_executor`, so the DER loop runs off the event loop and a ContextVar set there is
   invisible. Silent failure mode: the priority lane stops working and every user turn gets gated,
   with no error anywhere. `test_contextvar_across_executor` (T3.9) makes it loud.
   Hop 2 (nested, [:6947-6951](backend/agent/agent_kernel.py:6947)) is real but **verified
   currently unreachable** — it needs a tool-less `parallel_safe` step and
   `is_parallel_safe(None)` returns `False` (fail-closed). Guard it anyway; see T3.7 for why.

4. **T4.4 — VALID, and the propagation path is not the obvious one.** Children have **no
   `depends_on`**; they inherit the parent's `step_number`, so results propagate through
   `resolve_dependent_params`' **implicit-sequential** rule
   ([der_loop.py:519-525](backend/agent/der_loop.py:519)) into the step *after the parent* — not
   through an explicit dependency edge. An implementer looking only at `depends_on` would conclude
   children are isolated and that the blunt discard-everything fallback is over-engineering. It is
   not. See T4.4's ripple note.

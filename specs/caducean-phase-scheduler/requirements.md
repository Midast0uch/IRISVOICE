# Requirements: Caducean Phase Manager (Trig Functional Scheduler) + Inference Rate-Limit Hardening

## Decisions Locked

These were resolved with the user on 2026-07-27. Do **not** re-litigate them.

1. **Scope is both, sequenced.** Wave 1 stops the bleeding (the real 429 cause: retry
   stacking + a no-sleep hot-retry path + unbounded concurrent fan-out). Waves 2–3 build
   the phase manager as the architectural layer that keeps it fixed as loops multiply.
   The spec is explicit that Wave 1 is what fixes *today's* 429s, and the phase manager
   is what prevents the next class of them.
2. **Multiple cloud providers rate-limit.** Limits are therefore **strictly per-provider-
   instance** with independent sliding windows and **no shared global ceiling**. Exact
   caps are unknown, so ceilings are **learned adaptively** from observed `429` +
   `Retry-After` responses (AIMD), never hardcoded.
3. **Priority lane, never gated.** The user's turn and `speak_tool` output bypass the
   phase gate entirely and draw against the budget without waiting. Only derived /
   background work (Sub-Loop children, pacman compression, trailing director,
   auto-research, query refinement, synthesis) is phase-gated. Spoken latency is not
   allowed to regress.
4. **Bounded Sub-Loop batching is in scope** as Wave 4, fully specified including the
   multi-part response parser and per-child attribution contract.

### Corrections to `docs/caducean-phase-manager-trig-scheduling.md` (concept doc)

The concept doc's *mechanism* is sound; its *model of the problem* does not match the
as-built code. These corrections are load-bearing and are folded into the requirements
below. The concept doc is a design essay, not an as-built description — treat this spec
as authoritative where they disagree.

| Concept doc claim | As-built reality | Evidence |
|---|---|---|
| "sub-loop, outer loop, pacman loop each decide for themselves when to act" — three concurrent peers colliding | The DER loop is **serial** — one `while` loop draining one queue. Sub-Loop children are not a separate loop; `_split_step` pushes `QueueItem`s into the **same** `DirectorQueue`, drained by that same serial loop. | `agent_kernel.py:5441` (serial while), `agent_kernel.py:6206-6266` (`_split_step` returns QueueItems), `der_loop.py:346` (`next_ready`) |
| The outer loop contributes to rate-limit bursts | `run_outer_loop` makes **zero LLM calls** — it only reads SQLite ledgers. It cannot cause a 429. | `outer_loop.py:89-99`, `outer_loop.py:261-273` |
| Collisions are the cause of the rate limiting | The real burst sources are (a) an **unbounded `asyncio.gather`**, (b) **retry stacking** to 9 HTTP attempts per step, (c) a **429 branch that skips its own backoff sleep**. | `agent_kernel.py:5747`, `agent_kernel.py:5654-5680` + `transport.py:246`, `transport.py:259-269` |
| A single global amplitude / "how full is the room" number | Providers are heterogeneous: `LOCAL_OPENAI` / `OLLAMA` / `INPROCESS` have **no rate limit at all**. A global ceiling would throttle free local inference on a cloud provider's behalf. | `provider.py:16-22`, `provider.py:75-92` |
| Phase = the Caducean `ξ` already in the engine | `ξ` is already consumed for reasoning-state quadrants and for `coupled_registry` alignment coupling. Reusing it would couple scheduling to reasoning state — which §5 of the concept doc explicitly forbids. The scheduler needs its **own** θ. | `agent_kernel.py:5459-5472`, `coupled_registry.py:183` |
| (not addressed) | The gate must exist as a **sync/async twin pair**: `router.generate()` is sync and is called both from the DER executor thread and from async paths. Sleeping on the event-loop thread would stall WS/audio streaming. | `router.py:343` (sync), `agent_kernel.py:6949` (executor), `resilience.py:37/80` (existing twin precedent) |
| Splay state settles "over the next few ticks" | A voice turn lives 1–3 s and is gone before coupling converges. **Deterministic even placement at registration must be the primary mechanism**; coupling is only the slow corrector. (The concept doc's §4.1 already allows this — the spec makes it mandatory.) | Design decision D-4 |

## Introduction

IRIS Voice is hitting provider rate limits (`429`) during multi-step DER execution. The
concept doc attributes this to independent loops firing at the same instant. Code tracing
shows the dominant causes are different: a rate-limit retry path that retries *instantly*
(and then fabricates a response), a retry wrapper stacked on top of the transport's own
retry loop, and an unbounded `asyncio.gather` over every ready parallel-safe step.

This spec (a) repairs those three defects, (b) introduces a per-provider-instance adaptive
rate meter, and (c) adds a **Caducean Phase Manager**: a scheduling layer owned by the
Caducean Engine that keeps any number of registered work sources from converging on the
same instant, using anti-phase (negative-coupling) Kuramoto phase repulsion. Volume is
regulated through the *same* mechanism — a self-limiting amplitude that modulates each
oscillator's effective clock rate — so timing and volume are one coupled-oscillator model
rather than two bolted-together mechanisms.

The scheduler is loop-agnostic by construction: a registrant declares only how often it
wants to act and which provider it draws from. No loop ever learns that another loop
exists.

### Success criteria

- Zero instant-retry-on-429 paths remain: every `429` retry sleeps for at least the
  server-supplied `Retry-After`, or an exponential backoff when the header is absent.
- A rate-limited call **never** returns a fabricated assistant response. Today three
  exhausted 429 attempts return the literal string `"(I see.)"` to the user
  (`transport.py:345`); after this spec it raises a typed error that the DER loop reports
  honestly.
- Maximum HTTP attempts per DER step is **3**, not 9 (single retry authority).
- Concurrent parallel-safe step fan-out is bounded by a configured semaphore, never `len(ready)`.
- With the scheduler enabled and ≥2 registered non-priority oscillators sharing a provider,
  the measured minimum inter-request gap at that provider is ≥ `1/(rpm_ceiling/60)` for
  non-priority traffic, and the standard deviation of inter-request gaps falls by ≥50%
  versus the flag-off baseline on the replay harness.
- p50 added latency on the user-facing turn is **0 ms** (priority lane is never gated),
  verified by a behavioral test asserting `acquire()` returns without sleeping for
  `CallClass.USER_TURN` even when the provider window is saturated.
- `IRIS_PHASE_SCHEDULER=0` (the default) reproduces current behavior byte-for-byte on the
  existing DER suite — no regression on the G1–G5 invariant tests.
- Wave 4: batching N independent Sub-Loop children into one dispatch reduces LLM calls for
  that group from N to 1, with every child's `QueueItem.result` populated from the parsed
  response, and a documented fallback to individual dispatch that never fabricates a child
  result.

## Requirements

---

### REQ-1: Rate-limit retries must actually back off

**User Story:** As the inference layer I want a `429` to be followed by a real wait so that
I stop amplifying the very condition that produced it.

**Verified:** REAL GAP — `backend/agent/inference/transport.py:259-269`. In
`ApiHttpxTransport._stream`, the `429` branch calls `continue`, which jumps to the next
iteration of `for attempt in range(3)` and **skips the backoff sleep at lines 329-330
entirely**. Three `429`s are therefore hammered with zero delay. The same defect exists in
`OpenAICompatTransport` streaming at `transport.py:517-527`. The non-streaming paths are
correct (`transport.py:374-375`, `transport.py:618-624`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL sleep before every rate-limit retry attempt in **all** transport
  paths — streaming and non-streaming alike.
- AC2: WHEN a transport receives HTTP `429` AND at least one retry attempt remains THEN THE
  SYSTEM SHALL sleep for the resolved backoff interval before issuing the next attempt.
- AC3: THE SYSTEM SHALL apply exponential backoff with jitter when no server-supplied delay
  is available, using the codebase convention `base=1.0, cap=8.0` established in
  `resilience.py:47-52`.
- AC4: IF the final retry attempt also returns `429` THEN THE SYSTEM SHALL NOT sleep again
  before failing (no pointless terminal wait).
- AC5: THE SYSTEM SHALL log each rate-limit retry at WARNING with the provider instance id,
  the attempt number, and the actual sleep duration.

**Edge Cases:**
- Local providers (`OLLAMA`, `INPROCESS`) never emit `429` — behavior unchanged; no new
  sleep path is introduced for them.
- `429` on attempt 3 of 3: fail immediately per AC4, surfaced via REQ-3.
- A transport that raises before reading the status code retains its existing transient
  retry path (`transport.py:319-330`) unchanged.

---

### REQ-2: Honor the server's `Retry-After`

**User Story:** As the inference layer I want to wait exactly as long as the provider told
me to so that I stop guessing and stop being penalized for guessing wrong.

**Verified:** REAL GAP — no occurrence of `Retry-After` anywhere in
`backend/agent/inference/`. Confirmed by search across `transport.py`, `router.py`,
`provider.py`. Every `429` currently uses a blind local backoff.

**Acceptance Criteria:**
- AC1: WHEN a `429` response carries a `Retry-After` header THEN THE SYSTEM SHALL parse it
  and use it as the sleep duration for the next attempt, in preference to local backoff.
- AC2: THE SYSTEM SHALL accept both `Retry-After` forms: delta-seconds (integer) and an
  HTTP-date, converting the date form to a delta against local clock time.
- AC3: THE SYSTEM SHALL clamp the parsed delay to `[0, RETRY_AFTER_MAX_S]` so a hostile or
  misconfigured header cannot stall a voice turn indefinitely.
- AC4: IF the header is absent, unparseable, or negative THEN THE SYSTEM SHALL fall back to
  the REQ-1 AC3 exponential backoff and SHALL NOT raise.
- AC5: WHEN a `Retry-After` is observed THEN THE SYSTEM SHALL publish it to the provider rate
  meter (REQ-7) as a ceiling-reduction signal.

**Edge Cases:**
- `Retry-After: 0` → treat as "retry immediately" but still yield once (no busy spin).
- Header present on a non-`429` response (e.g. `503`) → parsed and honored identically.
- Clock skew making an HTTP-date delta negative → clamped to 0 per AC3/AC4.

---

### REQ-3: A rate-limited call never returns a fabricated response

**User Story:** As a user I want to be told the provider refused my request so that I am
never read a made-up acknowledgement that hides a failure.

**Verified:** REAL GAP, user-visible — `backend/agent/inference/transport.py:246-345`.
After three exhausted `429` attempts, `_stream` falls out of the retry loop with
`full_reply == ""` and `_tool_calls == []`, skips the reasoning fallback at line 341, and
returns `clean or "(I see.)"` at line 345. A rate-limited voice turn therefore **speaks the
fabricated string `"(I see.)"`** as if the model had answered. This directly violates the
project's honest-display invariant (`specs/der-loop-integrity-display/requirements.md`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define a typed exception `RateLimitedError` carrying
  `provider_id`, `attempts`, and `retry_after` (nullable float).
- AC2: WHEN all rate-limit retry attempts are exhausted THEN THE SYSTEM SHALL raise
  `RateLimitedError` and SHALL NOT return a placeholder, default, or filler string.
- AC3: THE SYSTEM SHALL NOT return the `"(I see.)"` fallback for any response whose emptiness
  was caused by a non-200 status; that fallback remains reachable **only** for a genuine
  empty-content `200` response.
- AC4: WHEN a DER step fails with `RateLimitedError` THEN THE SYSTEM SHALL surface the
  provider and wait hint in the step's failure text so `_der_handle_step_failure` and the
  `TASK_BLOCKED` escalation report the real cause.
- AC5: THE SYSTEM SHALL record the failed step in the commit ledger with
  `verified_label="FAILED"`, preserving the REQ-1 contract of
  `specs/der-loop-integrity-display`.

**Edge Cases:**
- Genuine empty `200` with non-empty `reasoning_content` → existing fallback at
  `transport.py:341-342` is preserved unchanged.
- `RateLimitedError` raised inside the concurrent gather → that step alone fails; siblings
  are unaffected (`asyncio.gather` results are per-task).
- Reviewer path (`AgentKernel.infer`, `agent_kernel.py:605-617`) swallows all exceptions and
  returns empty text by design (membrane, not gate) — that is correct and stays, because the
  Reviewer falling back to `PASS` is not a fabricated *user-facing* answer.

---

### REQ-4: One retry authority — no stacked retry loops

**User Story:** As an operator I want a bounded, predictable number of HTTP attempts per
step so that a single failing step cannot issue nine requests into a rate-limited provider.

**Verified:** REAL GAP — `agent_kernel.py:5654-5680` wraps a step in
`retry_with_backoff_sync(max_retries=2)` (3 tries), and each try enters
`transport.py:246` `for attempt in range(3)` (3 more). Worst case **9 HTTP attempts per
step**. The extra-step path at `agent_kernel.py:5766-5771` adds a further hand-rolled
`time.sleep(0.5)` retry, making that path even deeper.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL treat the transport as the sole retry authority for HTTP-level
  rate limiting; the step-level wrapper SHALL NOT re-attempt a call that already exhausted
  transport rate-limit retries.
- AC2: THE SYSTEM SHALL classify `RateLimitedError` as non-retryable at the step level by
  adding it to an explicit no-retry set in `resilience.py`, distinct from both
  `TRANSIENT_ERRORS` and `PERMANENT_ERRORS`.
- AC3: WHEN a step fails with `RateLimitedError` THEN THE SYSTEM SHALL fail that step fast
  and route it to the existing graft/failure path without further HTTP attempts.
- AC4: THE SYSTEM SHALL keep step-level retry active for genuine transient errors
  (`ConnectionError`, `TimeoutError`, `OSError`) — that behavior is correct and is not
  changed by this requirement.
- AC5: THE SYSTEM SHALL cap total HTTP attempts per logical step at
  `TRANSPORT_MAX_ATTEMPTS` (default 3) for rate-limit causes, assertable by counting
  transport invocations in a behavioral test.

**Edge Cases:**
- A step that fails first with `ConnectionError` (retried) and then `RateLimitedError`
  (not retried) → total attempts stay bounded; the terminal error is the reported one.
- The extra/parallel step path's ad-hoc `time.sleep(0.5)` retry at `agent_kernel.py:5768`
  must respect AC1 as well — a `RateLimitedError` there is not retried.
- Flag-off: with `IRIS_PHASE_SCHEDULER=0` these retry-classification changes still apply.
  They are correctness fixes, not scheduler features, and are **not** behind the flag.

---

### REQ-5: Bounded concurrent step fan-out

**User Story:** As the provider's client I want the number of simultaneous in-flight step
executions to be bounded so that a wide plan does not arrive as one instantaneous burst.

**Verified:** REAL GAP — `agent_kernel.py:5740-5751` builds `_extra_ready` from **every**
ready `parallel_safe` step and passes the whole list to `_der_exec_steps_concurrent`, which
does an unguarded `asyncio.gather(*tasks)` at `agent_kernel.py:6972-6976`. There is no
semaphore anywhere in that path. `parallel_safe` is derived from the tool registry
(`agent_kernel.py:5331`), so this is active for read-only tools, not hypothetical.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL bound simultaneous in-flight executions inside
  `_der_exec_steps_concurrent` with an `asyncio.Semaphore` of size
  `DER_MAX_CONCURRENT_STEPS` (default 3).
- AC2: THE SYSTEM SHALL preserve the existing return contract of
  `_der_exec_steps_concurrent` exactly: `{step_id: (step_result, step_success)}` for every
  submitted item, in no guaranteed order.
- AC3: WHEN the number of ready parallel-safe steps exceeds the semaphore size THEN THE
  SYSTEM SHALL execute them in bounded batches and SHALL NOT drop, reorder-dependently, or
  merge any step.
- AC4: THE SYSTEM SHALL keep the existing serial fallback at `agent_kernel.py:5758-5763`
  intact for the case where the concurrent path raises.
- AC5: THE SYSTEM SHALL make `DER_MAX_CONCURRENT_STEPS` overridable by environment variable
  so it can be tuned without a code change.

**Edge Cases:**
- Exactly one ready extra step → semaphore is uncontended; behavior identical to today.
- Zero ready extra steps → `_extra_ready` is empty and the block is skipped, as today.
- A step inside the batch raising → per-task result carries the failure; the semaphore is
  released in a `finally` so one exception cannot deadlock the batch.

---

### REQ-6: Per-provider-instance request/token metering

**User Story:** As the scheduler I want to know how much is currently being drawn from each
provider so that regulation is based on measurement, not assumption.

**Verified:** NEW (unverified — implementation pending). No rate meter exists. Token
accounting exists but only per-session and after the fact:
`agent_kernel.py:5298` (`_tokens_used`), `agent_kernel.py:396` (`_der_tokens_used`),
`caducean_trajectory.py:334` (`tokens_total` in the session-exit ledger). None of these is
a live rolling window, and none is keyed by provider.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL maintain, per `ProviderInstance.id`, a sliding-window meter of
  requests issued and tokens consumed over the trailing `METER_WINDOW_S` (default 60 s).
- AC2: THE SYSTEM SHALL record every LLM request against its resolved provider instance id
  at the single inference chokepoint, regardless of which loop or role initiated it.
- AC3: THE SYSTEM SHALL count **priority-lane** calls in the meter even though they are
  never gated, so that background amplitudes correctly ease off in response to user traffic.
- AC4: THE SYSTEM SHALL expose `draw(provider_id) -> {requests, tokens, window_s}` as a
  read-only snapshot with no side effects.
- AC5: THE SYSTEM SHALL bound meter memory: each provider window retains at most
  `METER_MAX_SAMPLES` entries and evicts by age, so the meter can never grow unbounded.
- AC6: THE SYSTEM SHALL be safe under concurrent access from both the event loop and the DER
  executor thread, using a `threading.Lock` (the same discipline as
  `coupled_registry.py:93`).

**Edge Cases:**
- Token count unavailable (streaming response, no usage block) → estimate from character
  length using the existing 4-chars≈1-token convention documented at `agent_kernel.py:5283`;
  mark the sample `estimated=True`.
- Provider id unresolvable → record under the literal id `"unknown"` and log at debug; never
  raise from the metering path.
- Clock going backwards → treat a negative age as 0 rather than evicting the whole window.

---

### REQ-7: Adaptive per-provider ceiling learned from `429` / `Retry-After`

**User Story:** As an operator with several cloud providers whose exact limits I do not know
I want the system to learn each provider's real ceiling from its refusals so that I never
have to hand-configure a number I do not have.

**Verified:** NEW (unverified — implementation pending). Decision Locked #2. No configured
rate-limit fields exist on `ProviderInstance` (`provider.py:25-42`) or `InferenceConfig`
(`iris_config.py:183-212`), which is why the ceiling must be learned rather than read.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL maintain a learned soft ceiling per provider instance, expressed as
  requests-per-minute and tokens-per-minute, initialized to `CEILING_INIT_RPM` /
  `CEILING_INIT_TPM`.
- AC2: WHEN a `429` is observed for a provider THEN THE SYSTEM SHALL multiplicatively
  decrease that provider's ceiling by factor `CEILING_MD` (default 0.5), floored at
  `CEILING_MIN_RPM`.
- AC3: WHILE a provider has gone `CEILING_PROBE_S` (default 120 s) without a `429` THE
  SYSTEM SHALL additively increase its ceiling by `CEILING_AI_RPM` (default 2 rpm), capped
  at `CEILING_MAX_RPM`.
- AC4: WHERE an explicit ceiling is supplied by configuration or environment for a provider
  instance THEN THE SYSTEM SHALL treat it as a hard upper bound on the learned value and
  SHALL NOT probe above it.
- AC5: THE SYSTEM SHALL persist learned ceilings across process restarts to the same
  `.mcm/` params-store pattern the outer loop already uses (`outer_loop.py:62-64`,
  `.mcm/der_params.json`), in a separate file, and SHALL fall back to defaults if the file
  is missing or corrupt.
- AC6: THE SYSTEM SHALL keep each provider's ceiling fully independent — a `429` from one
  provider SHALL NOT reduce any other provider's ceiling.

**Edge Cases:**
- First-ever run, no persisted file → initialize from defaults; do not block startup.
- A provider that `429`s on its very first request → ceiling floors at `CEILING_MIN_RPM`
  rather than reaching 0, so the provider is never permanently locked out.
- Persisted file written by a previous version with unknown keys → unknown keys ignored,
  known keys merged over defaults (same tolerance as `outer_loop._load_params`).

---

### REQ-8: Local providers are never rate-gated

**User Story:** As a user running LM Studio or Ollama locally I want zero scheduling overhead
on local inference so that free local capacity is never throttled on a cloud provider's behalf.

**Verified:** REAL CONSTRAINT — `provider.py:16-22` defines `LOCAL_OPENAI`, `OLLAMA`, and
`INPROCESS` kinds; `provider.py:90-91` shows LM Studio as `needs_key: False`.
`OllamaTransport` has no `429` handling at all (verified: no `429` branch in the Ollama
class), because local servers do not rate-limit.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL classify `ProviderKind.LOCAL_OPENAI`, `ProviderKind.OLLAMA`, and
  `ProviderKind.INPROCESS` as unmetered.
- AC2: WHEN a call resolves to an unmetered provider THEN the phase gate SHALL return
  immediately with zero wait, regardless of call class or global load.
- AC3: THE SYSTEM SHALL still record unmetered calls in the meter for **observability only**
  (REQ-20), and SHALL NOT let those samples affect any ceiling or amplitude.
- AC4: THE SYSTEM SHALL derive metered/unmetered status from `ProviderInstance.kind` alone,
  with no per-provider allowlist to maintain.

**Edge Cases:**
- A cloud provider reached through an OpenAI-compatible proxy registered as `LOCAL_OPENAI`
  → correctly treated as unmetered by AC4; documented as a known misconfiguration whose
  remedy is registering it with `kind: "api"`.
- Mixed plan: some steps on Cerebras, some on LM Studio → only the Cerebras steps are gated.

---

### REQ-9: Amplitude coupling — volume regulated through the same oscillator

**User Story:** As the Caducean engine I want each registrant's volume to ease off when its
provider is busy and swell back when there is headroom, expressed as a property of the same
rotating arrow as its phase, so that timing and volume are one model and not two.

**Verified:** NEW (unverified — implementation pending). Grounded in the concept doc §6 and
in the existing self-limiting-amplitude precedent: the Duffing law `F(u) = 2u − 2u³` with
attractors at `u* = ±1`, referenced at `der_constants.py:129-142` and clamped in
`coupled_registry.py:24-26`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL give every registered oscillator an amplitude `r ∈ [R_MIN, 1.0]`
  in addition to its phase θ.
- AC2: THE SYSTEM SHALL relax `r` toward the current headroom of the oscillator's provider,
  `r_target = 1 − load_fraction`, where
  `load_fraction = clamp(draw / learned_ceiling, 0, 1)` — a **moving** attractor, not a
  fixed cap, mirroring the Duffing self-limiting form.
- AC3: THE SYSTEM SHALL apply amplitude by modulating the oscillator's effective angular
  velocity, `ω_eff = ω · r`, so a loaded provider makes its registrants fire *less often*
  through the same phase mechanism rather than through a separate counter.
- AC4: THE SYSTEM SHALL floor `r` at `R_MIN` (default 0.1) so no registrant is ever starved
  to a complete stop by amplitude alone.
- AC5: THE SYSTEM SHALL NOT let amplitude affect priority-lane calls (REQ-14), which are
  never gated and therefore have no firing window to modulate.
- AC6: THE SYSTEM SHALL NOT reduce `max_tokens` or otherwise alter request *content* based
  on amplitude in this spec; amplitude affects firing rate only. (Content-scaling is listed
  in Non-Requirements.)

**Edge Cases:**
- `learned_ceiling == 0` (should be impossible per REQ-7 floor) → treat `load_fraction` as
  1.0 and let `r` fall to `R_MIN`; log at warning.
- Unmetered provider → `load_fraction = 0`, so `r → 1.0` and amplitude is inert, consistent
  with REQ-8.
- A brand-new oscillator registering into a saturated provider → starts at
  `r = 1 − load_fraction` rather than 1.0, so it does not get one free full-rate burst.

---

### REQ-10: Hard-cap safety rail

**User Story:** As an operator I want a last-resort ceiling that catches a mistuned coupling
so that a bad constant cannot produce a runaway request storm.

**Verified:** PARTIAL — a hard brake precedent exists but only for cycles, not requests:
`DER_EMERGENCY_STOP = 200` at `der_constants.py:102`. No request-rate cap exists anywhere.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL enforce a hard per-provider request ceiling
  `PHASE_HARD_MAX_RPM` that is independent of, and never raised by, the adaptive learning in
  REQ-7.
- AC2: WHEN a non-priority call would exceed the hard cap THEN THE SYSTEM SHALL block it
  until the window admits it or `PHASE_MAX_WAIT_S` elapses, whichever comes first.
- AC3: WHEN `PHASE_MAX_WAIT_S` elapses with the hard cap still exceeded THEN THE SYSTEM SHALL
  fail the call with `RateLimitedError` rather than issue it, and SHALL log at ERROR that the
  hard rail fired.
- AC4: THE SYSTEM SHALL NOT block a priority-lane call under any circumstances, including
  hard-cap exhaustion (Decision Locked #3).
- AC5: THE SYSTEM SHALL document, in the module docstring, the honest limit of AC4: if
  priority traffic alone exceeds a provider's real limit, the scheduler cannot prevent a
  `429`, and REQ-1/2/3 handling is what makes that outcome honest rather than silent.

**Edge Cases:**
- Hard cap set below the learned ceiling → the hard cap wins; log at warning once per
  provider that the rail is the binding constraint.
- Hard cap firing during a voice turn → per AC4 the voice turn still proceeds; only
  background work is blocked.

---

### REQ-11: Phase registry with deterministic splay placement

**User Story:** As a new registrant I want to be placed in an already-well-spaced slot
immediately so that short-lived work gets collision avoidance without waiting for coupling
to converge.

**Verified:** NEW (unverified — implementation pending). A structurally similar registry
already exists and is the model to follow: `CoupledTrajectoryRegistry` at
`coupled_registry.py:87-216` (thread-safe dict, idempotent `register_session`,
`unregister_session`, `list_sessions`, singleton accessor at `coupled_registry.py:225`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide `register(oscillator_id, natural_period_s, provider_id,
  call_class, join_point=None, independent=False)` returning the oscillator's initial state.
- AC2: WHEN registering the *N*-th oscillator THEN THE SYSTEM SHALL place its phase
  deterministically at the widest available gap in the current phase distribution, rather
  than randomly, so the splay condition holds from the first tick.
- AC3: THE SYSTEM SHALL make `register` idempotent: re-registering an existing id updates
  its period, provider, and class while **preserving** its current phase and amplitude.
- AC4: THE SYSTEM SHALL provide `unregister(oscillator_id)` that is a no-op for unknown ids
  and never raises.
- AC5: THE SYSTEM SHALL expose `snapshot()` returning every oscillator's
  `(id, theta, omega, amplitude, provider_id, call_class, last_fired_at)` for tests and
  observability, with no side effects.
- AC6: THE SYSTEM SHALL be a process-wide singleton with a `reset_*_for_testing()` accessor,
  matching the pattern at `coupled_registry.py:225-238`.

**Edge Cases:**
- N=1 → placement is trivially θ=0; the coupling sum is empty and the oscillator advances on
  its natural rhythm alone.
- Registering an oscillator with `natural_period_s <= 0` → clamped to `MIN_PERIOD_S` and
  logged; never divides by zero.
- Rapid register/unregister churn (voice turns) → `snapshot()` and `advance()` must not
  raise on a dict mutated between calls; all reads happen under the lock.

---

### REQ-12: Anti-phase coupling using the scheduler's own θ

**User Story:** As the Caducean engine I want registered oscillators to repel each other in
phase so that they spread evenly around the clock face without any registrant knowing the
others exist.

**Verified:** NEW (unverified — implementation pending). The `ξ` reuse hazard is REAL and
verified: `ξ` is consumed as a reasoning-state quadrant at `agent_kernel.py:5459-5472` and
for alignment coupling at `coupled_registry.py:183`. Concept doc §5 forbids the phase
manager from touching reasoning-state decisions, so θ must be independent.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL maintain its own phase variable θ per oscillator, in `[0, 2π)`, and
  SHALL NOT read or write the Caducean `ξ` (`ffi_caducean_get_xi` / `ffi_caducean_set_params`)
  for any scheduling decision.
- AC2: THE SYSTEM SHALL advance phases by the repulsive (anti-phase) Kuramoto rule
  `dθᵢ/dt = ωᵢ_eff + (K/N) · Σ_{j≠i} sin(θᵢ − θⱼ)` with `K > 0`, which is the standard
  Kuramoto form with negative coupling and whose stable fixed point is the evenly-spread
  splay state.
- AC3: THE SYSTEM SHALL drive the advance lazily from elapsed wall-clock time at each gate
  check, and SHALL NOT require a dedicated background timer task.
- AC4: THE SYSTEM SHALL clamp the per-advance phase delta so that a long idle gap cannot
  produce a single enormous jump; an elapsed time greater than `TICK_MAX_DT_S` is treated as
  `TICK_MAX_DT_S`.
- AC5: WHEN all oscillators sharing a provider are evenly spread THEN the coupling term SHALL
  evaluate to approximately zero, so the nudging stops once collisions are no longer likely.
- AC6: THE SYSTEM SHALL compute the coupling sum only over oscillators sharing the same
  `provider_id`, because spacing traffic against a provider that is not shared has no effect
  on that provider's limit.

**Edge Cases:**
- Two oscillators at exactly the same θ → `sin(0) = 0` yields no repulsion; the
  implementation SHALL apply a deterministic epsilon separation at registration (AC2 of
  REQ-11 makes exact ties impossible for new registrants) and SHALL document that identical
  phases are a fixed point that placement, not coupling, prevents.
- `K` set to 0 → coupling disabled, oscillators run on natural rhythm; must not crash. This
  is the documented way to isolate placement from coupling during tuning.
- Fewer than 2 oscillators on a provider → coupling sum empty, pure ω advance.

---

### REQ-13: Phase gate at the single inference chokepoint, with sync and async twins

**User Story:** As the scheduler I want one place to gate every LLM call so that no loop can
route around me and no loop needs modifying to be governed.

**Verified:** VERIFIED CHOKEPOINT — `InferenceRouter.generate()` at `router.py:343-399` is
the single funnel. Every LLM call reaches it: `AgentKernel.infer` → `router.generate`
(`agent_kernel.py:610`), which is what `Reviewer.review` (`der_loop.py:597`),
`TrailingDirector` (`trailing_director.py:100`), `spec_engine` (`spec_engine.py:135`),
`ask_user_tool` (`ask_user_tool.py:73`), and the memory distillation/skills/working paths
(`memory/distillation.py:286`, `memory/skills.py:176`, `memory/working.py:215`) all use;
plus the four direct kernel call sites (`agent_kernel.py:2157`, `4025`, `7925`) and
`tool_decision.py:292`. **Thread hazard is REAL:** `router.generate` is sync and is invoked
from the DER executor thread (`agent_kernel.py:6949`) as well as from async paths, and
`resilience.py:37/80` already establishes the twin pattern for exactly this reason.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL gate LLM calls at `InferenceRouter.generate()` and SHALL NOT require
  any change to a calling loop in order to govern it.
- AC2: THE SYSTEM SHALL provide two gate entry points with identical semantics: a blocking
  `acquire()` that uses `time.sleep`, and an `acquire_async()` that uses `asyncio.sleep`.
- AC3: THE SYSTEM SHALL NOT call `time.sleep` on the event-loop thread; the async twin is
  mandatory for any call originating in a coroutine.
- AC4: THE SYSTEM SHALL preserve `generate()`'s existing signature and 3-tuple return shape
  `(text, thinking, tool_calls)` exactly; the gate adds behavior, never a new required
  parameter.
- AC5: WHEN the gate admits a call THEN THE SYSTEM SHALL reset that oscillator's phase toward
  its next cycle, so admission and countdown-reset are one atomic step.
- AC6: THE SYSTEM SHALL cap any single gate wait at `PHASE_MAX_WAIT_S`, after which the call
  proceeds (for non-hard-cap waits) rather than waiting indefinitely.

**Edge Cases:**
- A caller whose oscillator was never registered → the gate SHALL auto-register it with
  default period and `CallClass.BACKGROUND`, and log at debug. No call is ever dropped for
  being unregistered.
- Gate raising internally → the gate SHALL swallow its own exceptions and admit the call
  (fail-open), so a scheduler bug can never block inference. Log at warning.
- Feature flag off → the gate is a no-op returning immediately (REQ-17).

---

### REQ-14: Never-gated priority lane for user-facing work

**User Story:** As a user speaking to IRIS I want my turn answered without scheduling delay
so that the assistant never feels slower because of background housekeeping.

**Verified:** NEW (unverified — implementation pending). Decision Locked #3. The contextvar
carrier has a precedent at `backend/monitoring/session_correlation.py:18-21`. **Propagation
hazard is REAL:** `loop.run_in_executor` (used at `agent_kernel.py:6949`) does **not** copy
`contextvars` into the worker thread, unlike `asyncio.to_thread`. The call class must
therefore be set explicitly inside the executor-side entry point, not merely inherited.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define a `CallClass` enum with at least `USER_TURN`, `SPEAK`,
  `SUBLOOP`, and `BACKGROUND`.
- AC2: THE SYSTEM SHALL classify `USER_TURN` and `SPEAK` as the priority lane, and SHALL
  admit priority-lane calls immediately with zero wait, under all load conditions.
- AC3: THE SYSTEM SHALL carry the current call class in a `ContextVar` that defaults to
  `BACKGROUND`, so an unclassified call is conservatively gated rather than accidentally
  privileged.
- AC4: THE SYSTEM SHALL set the call class explicitly at the top of the DER plan executor so
  the value is correct inside the thread-pool thread, because `run_in_executor` does not
  propagate context.
- AC5: THE SYSTEM SHALL record priority-lane calls in the meter (REQ-6 AC3) so background
  amplitudes respond to user traffic even though priority calls are never delayed.
- AC6: THE SYSTEM SHALL allow an explicit per-call override so a caller that knows it is
  user-facing can assert `CallClass.USER_TURN` without relying on ambient context.

**Edge Cases:**
- A background loop running inside a user turn's task tree → the explicit set at AC4/AC6
  wins over ambient inheritance; the Sub-Loop child is `SUBLOOP`, not `USER_TURN`.
- `speak_tool` invoked from a background flow → still `SPEAK` and still ungated, because
  audible output must never stutter.
- Context var unset in a fresh thread → defaults to `BACKGROUND` per AC3.

---

### REQ-15: Loop-agnostic registration (the modularity invariant)

**User Story:** As a developer adding a fifth loop next year I want to register it and be
governed without editing any existing loop so that collision avoidance does not cost me an
O(N) refactor.

**Verified:** CONTRACT — this is the concept doc's §3 thesis and the reason the layer is
separate. Enforceable against the code: today's loops learn nothing about each other because
they all funnel through `router.generate` (`router.py:343`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL require exactly two facts from a registrant: a natural period and a
  provider id. Everything else (`call_class`, `join_point`, `independent`) SHALL be optional
  with safe defaults.
- AC2: THE SYSTEM SHALL NOT expose any API by which one registrant can query, name, or
  address another registrant.
- AC3: THE SYSTEM SHALL contain all collision-avoidance logic — placement, coupling,
  gating, rebalancing — inside the phase-manager module, with no scheduling branch added to
  any loop's own code.
- AC4: THE SYSTEM SHALL NOT branch on registrant identity, kind, or name anywhere in the
  coupling or gating path; behavior SHALL depend only on `(theta, omega, amplitude,
  provider_id, call_class)`.
- AC5: A contract test SHALL assert AC4 by registering an oscillator with an arbitrary
  unknown id and verifying it is gated identically to a known one.

**Edge Cases:**
- A registrant that never calls `acquire` → occupies a phase slot but consumes no budget;
  `unregister` on idle timeout `IDLE_UNREGISTER_S` reclaims the slot.
- Two registrants sharing one id → idempotent per REQ-11 AC3; they share one oscillator,
  which is the documented way to treat a pool of identical workers as one rhythm.

---

### REQ-16: Rebalancing on registration change requires no special-case logic

**User Story:** As the scheduler I want the spread to re-form automatically when work sources
appear or disappear so that churn does not need bespoke handling.

**Verified:** NEW (unverified — implementation pending). Concept doc §4.4.

**Acceptance Criteria:**
- AC1: WHEN an oscillator is added or removed THEN THE SYSTEM SHALL re-form the spread using
  only the REQ-11 placement rule and the REQ-12 coupling rule, with no code path specific to
  addition or removal.
- AC2: THE SYSTEM SHALL keep surviving oscillators' phases continuous across a
  registration change — no phase is reset merely because a sibling left.
- AC3: THE SYSTEM SHALL recompute the coupling normalization `N` from the live registrant
  count on every advance, so the coupling strength self-adjusts to population size.
- AC4: A physics-aware test SHALL assert that after removing one of three evenly-spread
  oscillators, the remaining two converge to approximately π apart within
  `REBALANCE_TICKS` advances.

**Edge Cases:**
- All oscillators unregistered → registry empty; `advance` is a no-op and `acquire`
  auto-registers per REQ-13.
- Registration change mid-wait → the waiting call SHALL use the wait it computed at acquire
  time and SHALL NOT be extended by a new arrival, so arrivals cannot starve waiters.

---

### REQ-17: Feature flag with byte-identical off behavior

**User Story:** As an operator I want to disable the scheduler instantly so that a
mistuned constant is one environment variable away from being reverted.

**Verified:** NEW (unverified — implementation pending).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL read `IRIS_PHASE_SCHEDULER` and SHALL default to disabled.
- AC2: WHILE the flag is disabled THE SYSTEM SHALL make `acquire`/`acquire_async` immediate
  no-ops and SHALL perform no phase advance, no metering, and no coupling.
- AC3: THE SYSTEM SHALL keep the REQ-1 through REQ-5 corrections active regardless of the
  flag, because those are defect fixes rather than scheduler features.
- AC4: THE SYSTEM SHALL verify AC2 by running the full existing DER suite with the flag off
  and asserting no behavioral change versus the pre-spec baseline.
- AC5: THE SYSTEM SHALL log the flag state exactly once at first gate use, at INFO.

**Edge Cases:**
- Flag toggled at runtime → read per-call (cheap boolean) so a restart is not required;
  document that toggling mid-flight leaves existing phases in place and harmless.
- Flag set to an unparseable value → treated as disabled and logged at warning.

---

### REQ-18: Bounded batching of independent Sub-Loop children at the compression seam

**User Story:** As the DER loop I want several independent Sub-Loop children dispatched as
one call so that a wide split costs one request instead of N, without any child waiting on a
slower sibling.

**Verified:** REAL AND SOUND — the concept doc §7 premise checks out against code.
`_split_step` creates children with `is_subloop=True` (`agent_kernel.py:6252`) and the parent
never observes them individually; children carry **no tool** (`agent_kernel.py:6245-6254`),
so each routes to `_run_step_direct` (`agent_kernel.py:6626`) = exactly one LLM call each.
Batching N children therefore maps cleanly to one composed prompt with N sub-tasks.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL batch only children that share a `join_point` AND are marked
  `independent`, per the concept doc's unchanged precondition that dependent children are
  never grouped.
- AC2: THE SYSTEM SHALL batch only children whose phase windows already fall within
  `BATCH_WINDOW_RAD` of each other, so grouping never forces artificial synchronization.
- AC3: THE SYSTEM SHALL never hold a ready child longer than `BATCH_MAX_HOLD_S` waiting for
  a sibling; on expiry the child SHALL dispatch alone.
- AC4: THE SYSTEM SHALL cap batch size at `BATCH_MAX_CHILDREN` (default 3), aligned with
  `DER_MAX_GRAFTS = 3` (`der_constants.py:104`) and the wide split width of 3
  (`agent_kernel.py:6182`).
- AC5: THE SYSTEM SHALL leave the parent's contract untouched: the parent still observes
  exactly one collapse into a single `COMPRESS` observation, whether children ran batched or
  individually.
- AC6: THE SYSTEM SHALL count a batched dispatch as **one** request in the meter (REQ-6),
  because that is what the provider sees.

**Edge Cases:**
- One eligible child → dispatch individually; no composed prompt, no parser.
- Children with heterogeneous `expected_output` → each sub-task carries its own criterion in
  the composed prompt so per-child verification still works.
- A child cancelled mid-batch (soft-cancel, `agent_kernel.py:5613`) → the batch is abandoned
  and no results are attributed; the cancel semantics win.

---

### REQ-19: Batch response attribution with an honest fallback

**User Story:** As the DER loop I want every batched child's result traced back to that
specific child so that batching never invents, duplicates, or silently drops a child's
outcome.

**Verified:** NEW (unverified — implementation pending). Depends on REQ-18. The result sink
is `QueueItem.result` (`der_loop.py:90`), consumed by `TrailingDirector.analyze_gaps` and
by `resolve_dependent_params` (`der_loop.py:486-540`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL compose the batched prompt with each sub-task labelled by an
  unambiguous, machine-parseable delimiter keyed to the child's `step_id`.
- AC2: THE SYSTEM SHALL parse the response into exactly one segment per child and SHALL
  assign each segment to that child's `QueueItem.result`.
- AC3: IF the response cannot be parsed into one segment per child THEN THE SYSTEM SHALL
  discard the batched response entirely and re-dispatch every child in the batch
  individually.
- AC4: THE SYSTEM SHALL NOT populate any child's `result` from a partially parsed batch, and
  SHALL NOT infer a missing child's result from its siblings.
- AC5: THE SYSTEM SHALL run each child's existing verification unchanged
  (`_verify_step_result`, `agent_kernel.py:6995`) against its attributed segment, so a
  batched child is held to the same standard as an individually dispatched one.
- AC6: THE SYSTEM SHALL log at WARNING with the child ids whenever AC3's fallback fires, so
  parser failure rate is measurable.

**Edge Cases:**
- Model returns segments in a different order than requested → attribution is by `step_id`
  label, not position, so order does not matter.
- Model returns an extra segment for a nonexistent id → unmatched segments are ignored and
  the presence of an unmatched segment does not itself trigger the fallback, provided every
  requested child matched.
- Model answers only the first sub-task → parse yields fewer segments than children →
  AC3 fallback fires; no partial credit.

---

### REQ-20: Observability and tuning instrumentation

**User Story:** As the person who has to tune `K`, the ceilings, and the batch window I want
every scheduling decision measurable so that the next iteration is grounded in data rather
than in another design essay.

**Verified:** NEW (unverified — implementation pending). Required because the concept doc's
§8 states plainly that coupling strength "would need empirical tuning against your actual
call patterns, not a value assumed in advance." No such measurement exists today — notably,
a search of the log corpus found **no recorded `429` events at all**, which is why the caps
in REQ-7 are learned rather than configured.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log, for every gate decision, a single structured line containing:
  oscillator id, provider id, call class, θ at decision, amplitude, computed wait,
  actual wait, admitted/blocked, and the reason.
- AC2: THE SYSTEM SHALL log every ceiling change (REQ-7) with the old value, new value,
  trigger (`429` / probe), and the observed `Retry-After` when present.
- AC3: THE SYSTEM SHALL keep instrumentation off the hot path: logging SHALL be at DEBUG for
  admitted-with-zero-wait decisions and at INFO or above only for waits, blocks, and ceiling
  changes.
- AC4: THE SYSTEM SHALL expose a `metrics()` snapshot providing, per provider: current draw,
  learned ceiling, count of `429`s in the window, gate admissions, gate waits, total wait
  time, and mean/stddev of inter-request gaps.
- AC5: THE SYSTEM SHALL scope every log line by `provider_id` and by conversation or session
  id where available, matching the structured-logging convention required by
  `CLAUDE.md` ("context identifier in every log line").
- AC6: THE SYSTEM SHALL record the inter-request gap distribution needed to verify the
  ≥50% stddev-reduction success criterion, so that criterion is checkable rather than
  aspirational.

**Edge Cases:**
- Very high call volume → AC3's DEBUG default keeps the common case cheap; `metrics()` is
  pull-based, not pushed per call.
- Missing conversation id (REST path, `api/chat.py`) → fall back to session id, then to
  `"unknown"`; never raise from the logging path.
- Flag off → emit the single INFO line from REQ-17 AC5 and nothing further.

---

## Non-Requirements (Out of Scope)

- **Gating the outer loop.** `run_outer_loop` makes no LLM calls (`outer_loop.py:89-99`); it
  reads SQLite ledgers only. Registering it would add cost and zero benefit.
- **Replacing or merging `CoupledTrajectoryRegistry`.** It couples *reasoning* state (`u`/`ξ`)
  across sessions and stays as-is. The phase manager is a sibling layer, not a replacement.
  Its interface is a CONTRACT LOCK in the design's ripple map.
- **Changing Caducean `ξ` semantics or the `_growth_width` / `_split_step` split decision.**
  Concept doc §5: the manager decides *when* a registrant may act, never *what* it does or
  how wide it splits.
- **Amplitude-driven content scaling** (shrinking `max_tokens` or context under load). REQ-9
  AC6 explicitly defers this; it changes answer quality, not just timing, and needs its own
  spec.
- **Rate-limiting non-LLM external APIs** (Exa / crawler search providers,
  `backend/crawler/search_providers/`). Different limits, different failure mode; separate spec.
- **Embedding / vector-store call gating.** Not currently a `429` source.
- **Frontend UI for scheduler state.** No new bridged event is added; `ws_event_bridge.py`
  uses an explicit allowlist (`ws_event_bridge.py:33-64`), so nothing reaches the frontend
  unless deliberately added. Observability is log- and `metrics()`-based only.
- **A background tick task.** Rejected in favor of lazy advance (REQ-12 AC3); see design
  decision D-3.
- **Distributed / multi-process scheduling.** The registry is process-local. A second backend
  process would have its own registry and its own view of the draw.

## Open Questions

- **Q1 — Initial ceiling values.** `CEILING_INIT_RPM` / `CEILING_INIT_TPM` need starting
  points. AIMD will find the real ceiling either way, but starting too high means the first
  minutes of a session absorb `429`s to learn. Non-blocking: Wave 2 ships conservative
  defaults (30 rpm) and the tuning data from REQ-20 AC4 answers this properly.
- **Q2 — Should `K` be per-provider or global?** Spec'd as global for Wave 3 simplicity.
  If providers turn out to have very different burst tolerances, per-provider `K` is a
  one-line change to the constants table. Non-blocking.
- **Q3 — Idle-unregister timeout.** `IDLE_UNREGISTER_S` reclaims slots from registrants that
  stopped calling. Too short causes churn in the splay; too long leaves phantom slots that
  dilute everyone's share. Wave 3 ships 300 s; REQ-20 data settles it.
- **Q4 — Does the Reviewer deserve its own oscillator or should it share the DER step
  oscillator?** Spec'd as sharing (one oscillator per session's DER activity) because the
  Reviewer call is serially adjacent to the step call, not concurrent with it
  (`agent_kernel.py:5549-5585`). Revisit if REQ-20 shows Reviewer calls arriving in bursts.

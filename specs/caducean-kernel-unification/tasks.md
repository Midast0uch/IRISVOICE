# Tasks: Caducean Kernel Unification

> Every task links to a requirement and carries a RIPPLE note. Waves are dependency-ordered.
>
> **Binding rule** (`CLAUDE.md`, absolute): `test_coupled_registry.py`,
> `test_conversation_kernel.py`, `test_trajectory_controller.py`, and
> `test_caducean_trajectory.py` must pass **unedited** throughout. If a change requires editing
> one, the change is wrong. Run the QUALITY CHECK before every test run and record MCM events
> (`record_edit` / `record_create` / `record_test`) as you go.
>
> **Risk ordering is deliberate.** Wave 1 is strictly corrective and ships alone. Wave 4
> activates a code path with zero production runtime to date and is flag-off by default.

---

## Wave 0 — Baseline

- [ ] **T0.1** Green-test baseline. Run `pytest backend/tests -q` and record total / passed /
  failed, separating real breaks from stale-test artifacts. Fill in "Baseline record" below.
  RIPPLE: nothing modified. Without this, "the four locked files still pass" is unverifiable and
  a pre-existing failure gets misattributed to this spec.

- [ ] **T0.2** Capture the parameter-drift baseline: instrument a scripted 200-update session
  with 10 barge-ins and 5 TOPO_VIOLATIONs, log `(a, b, s)` per update, save to
  `backend/tests/fixtures/param_drift_baseline.json`.
  RIPPLE: this is the "before" side of the REQ-1 success criterion and of harness assertion 3.
  **Capture it before T1.x lands** — the ratchet cannot be measured once it is fixed.

- [ ] **T0.3** Confirm the conversation→session resolution mechanism for Open Question Q2. Read
  `backend/tests/unit/test_active_kernel_registry.py` and the registry it exercises; determine
  whether a conversation id can be resolved to the kernel session id that the trajectory
  recorder writes under. Write the answer into requirements.md Decisions Locked.
  RIPPLE: **gates T2.1 and T2.3.** REQ-4 AC2 and REQ-6 AC3 must use the same rule, and guessing
  it would put a third key mismatch into the same path this spec is repairing.

### Baseline record
<!-- T0.1: total / passed / failed / stale-failed, with ids. T0.2: starting and ending (a,b,s). -->

### Q2 resolution
<!-- T0.3: canonical identifier and the resolution mechanism, with file:line -->

---

## Wave 1 — Parameter homeostasis + the one-line correctness fixes

Strictly corrective. Ships and verifies independently of everything else.

- [ ] **T1.1** (REQ-2) Create `backend/agent/param_homeostasis.py`: `ParamBaseline` dataclass,
  thread-safe singleton with `reset_*_for_testing()`, `get_baseline(session_id)` defaulting to
  `(2.0, 2.0, 0.35)`, `set_baseline(session_id, a, b, s)`, and `MAX_BASELINES` eviction by
  `last_touched`.
  RIPPLE: follow the singleton/lock pattern at
  [coupled_registry.py:225-238](backend/agent/coupled_registry.py:225). The default is the Gate 1
  baseline documented at
  [trajectory_controller.py:196-200](backend/agent/trajectory_controller.py:196) — cite it in the
  module docstring so the number is traceable, not magic.

- [ ] **T1.2** (REQ-1) Implement `relax_params(session_id)` and `maybe_relax(session_id,
  update_count)`: read current `(a,b,s)` via `ffi_caducean_get_state`, move each `RELAX_STEP`
  (10%) of its distance to baseline, skip parameters within `RELAX_DEADBAND`, clamp to
  `a,b ∈ [1,4]` / `s ∈ [0.1,0.8]`, write via `ffi_caducean_set_params`. Fire every
  `RELAX_EVERY_N_UPDATES` (10) updates **OR** every `RELAX_MAX_INTERVAL_S` (60 s) wall-clock,
  whichever comes first (REQ-1 AC2/AC2b).
  RIPPLE (cross-spec): the wall-clock floor is not cosmetic. With
  `specs/caducean-phase-scheduler/` enabled, amplitude coupling throttles background step rate
  under provider load, which would throttle an update-count-only cadence at exactly the wrong
  time. Add a behavioral assertion in T1.7 that relaxation still fires with the update counter
  frozen. See `specs/CADUCEAN_SPEC_RECONCILIATION.md` C5.
  RIPPLE: the clamp ranges must match
  [trajectory_controller.py:250-252](backend/agent/trajectory_controller.py:250) exactly, or
  `test_tune_dffing_params_clamps` becomes inconsistent with reality. FFI failure → debug log,
  never raise (REQ-1 AC6). Verify no overshoot: proportional steps must never cross baseline.

- [ ] **T1.3** (REQ-1 AC2) Wire `maybe_relax` into the DER update site at
  [agent_kernel.py:7327-7350](backend/agent/agent_kernel.py:7327), after the existing
  `tune_dffing_params` call at [:7367](backend/agent/agent_kernel.py:7367). Maintain the
  per-session update counter needed for the cadence.
  RIPPLE: this is inside the DER step's `try` block that already swallows into
  `loud_error(_cad_exc, "caducean_trajectory_immortus")` — confirm relaxation failure cannot
  abort the trajectory record or the chain append that follow it. Order matters: relax **after**
  the perturbing writers so the counterweight sees their result.

- [ ] **T1.4** (REQ-2 AC1) Re-anchor the baseline from the operator endpoint at
  [main.py:2487-2494](backend/main.py:2487): after the post-clamp read-back, call
  `set_baseline` with the **clamped** values.
  RIPPLE: the response contract is marked FROZEN at
  [main.py:2470-2472](backend/main.py:2470) — do not add fields (REQ-2 AC5, CU-8). Record the
  clamped value, not the requested one, or relaxation targets an unreachable point and the
  deadband never engages.

- [ ] **T1.5** (REQ-3) One-line physics fix: pass `self._get_current_balance()` into
  `ffi_caducean_get_direction_signal` at
  [conversation_kernel.py:154](backend/agent/conversation_kernel.py:154), replacing the
  hardcoded `balance=1.0`.
  RIPPLE: `_get_current_balance()` already clamps to `[0.1, 3.0]`
  ([:137](backend/agent/conversation_kernel.py:137)) and already falls back to 1.0 on failure
  ([:140](backend/agent/conversation_kernel.py:140)) — so today's behavior becomes the failure
  path rather than the normal path. Method signature unchanged, so
  `test_speak_response_uses_kernel_chunk_size` holds. **This re-enables the correction that
  overview §3 says converts metastable → stable.**

- [ ] **T1.6** (REQ-15 AC1/AC2) Register perturbations with the homeostat: the barge-in write at
  [conversation_kernel.py:290](backend/agent/conversation_kernel.py:290) and
  `tune_dffing_params` at
  [trajectory_controller.py:255](backend/agent/trajectory_controller.py:255) each increment their
  writer's counter. Add the `metrics()`-style snapshot (current, baseline, perturbation counts by
  writer, relaxation count).
  RIPPLE: `tune_dffing_params` already logs its own adjustment at
  [:260-270](backend/agent/trajectory_controller.py:260); do not duplicate — add the cumulative
  distance-from-baseline field that made the ratchet invisible in existing logs.

- [ ] **T1.7** (REQ-1, REQ-2, REQ-3) Tests:
  - `backend/tests/unit/test_param_homeostasis.py` — proportional step, deadband no-op, clamping,
    default baseline, re-anchor, eviction, **no overshoot**.
  - `backend/tests/behavioral/test_param_ratchet_recovery.py` — the headline: 200 updates /
    10 barge-ins / 5 violations ends within ±0.15 of baseline; **and** with relaxation disabled
    the ratchet reproduces (`s` at floor), proving the test measures the fix.
  - `backend/tests/behavioral/test_voice_balance_live.py` — chunk size responds to balance;
    forcing balance constant makes it provably unable to.
  - `backend/tests/contract/test_param_safe_ranges.py` — CU-6, CU-8.
  RIPPLE: the disabled-relaxation half of `test_param_ratchet_recovery` is what stops a future
  refactor from silently removing the counterweight and leaving a green suite.

- [ ] **T1.8** Run the full suite. The four locked files pass **unedited**; zero new failures vs
  T0.1. Then `record_test` each new file and `pin_add` the Wave 1 decision.
  RIPPLE: gate for Wave 2. Do not proceed on red.

---

## Wave 2 — Physics↔memory coordinate integrity

The three breaks that null out "data gathered while thinking like this." Independent of Waves 3–4.

- [ ] **T2.1** (REQ-4) Fix the coordinate lookup key at
  [agent_kernel.py:3211](backend/agent/agent_kernel.py:3211): resolve the conversation id to the
  recording session id using the T0.3 mechanism, try that first, fall back to the conversation id
  (REQ-4 AC3), and log at **warning** with both keys tried when neither resolves (REQ-4 AC4).
  RIPPLE: `get_latest_coordinate` queries `WHERE session_id = ?`
  ([caducean_trajectory.py:281-285](backend/agent/caducean_trajectory.py:281)) while rows are
  written with `session_id=_session`
  ([agent_kernel.py:7342](backend/agent/agent_kernel.py:7342)); the two identifiers are
  documented as distinct at
  [agent_kernel.py:5426-5436](backend/agent/agent_kernel.py:5426). The REST path *does* use the
  conversation id as the kernel session (`api/chat.py:305`), which is why AC3's fallback is
  required rather than optional. `get_latest_coordinate` has **no other callers**, so this is a
  contained change. The AC4 warning must distinguish "no rows yet" from "key mismatch" or the log
  is not actionable.

- [ ] **T2.2** (REQ-5 AC1/AC2) Add `format_coords(x, y, xi, u) -> str` and
  `parse_coords(s) -> Optional[Tuple[float,float,float,float]]` to
  `backend/agent/caducean_trajectory.py`. Empty or unparseable → `None`; `NaN`/`inf` → format
  emits `""`.
  RIPPLE: single definition consumed by both chain-append sites and by the proximity reader. The
  document path currently inlines the format string at
  [agent_kernel.py:3215](backend/agent/agent_kernel.py:3215) — replace it with the shared
  formatter so the format has exactly one definition (REQ-5 AC2).

- [ ] **T2.3** (REQ-5 AC3/AC4, REQ-6) Fix the DER chain append at
  [agent_kernel.py:7388-7395](backend/agent/agent_kernel.py:7388): pass real coordinates via
  `format_coords(_ex, _ey, _xi, _u)` (all four already in scope at
  [:7343-7347](backend/agent/agent_kernel.py:7343)) instead of `coordinate_signal`; route the
  prose `coordinate_signal` to `insight` so its sub-task hints and failure warnings survive
  (REQ-5 AC4); use the canonical chain identifier from T0.3 for `thread_id` (REQ-6).
  RIPPLE: `coordinate_signal` is prose — it accumulates `"\nSUB-TASK HINT: …"` and
  `"\nPAST FAILURE WARNING: …"` at
  [agent_kernel.py:5529-5541](backend/agent/agent_kernel.py:5529) — so it must not be discarded,
  only moved. The document path uses `thread_id=conversation_id`
  ([:3312](backend/agent/agent_kernel.py:3312)) and the query filters on the same
  ([:3759](backend/agent/agent_kernel.py:3759)); whichever identifier T0.3 chooses must be applied
  at **all three** sites or the chains stay split. Also check the
  `ffi_immortus_chain_keep_latest` call site — pruning is per `thread_id`, so consolidating chains
  changes what it retains (REQ-6 edge case).

- [ ] **T2.4** (REQ-4, REQ-5, REQ-6) Tests:
  - `backend/tests/unit/test_coord_format.py` — round-trip; prose rejected; empty accepted;
    `NaN`/`inf` → empty.
  - `backend/tests/behavioral/test_trajectory_coordinate_recall.py` — **the memory end-to-end
    test**: record a DER step, store a document, query by coordinate, assert the document
    returns. Any one of REQ-4/5/6 still broken yields an empty result, so this single test covers
    all three.
  - `backend/tests/contract/test_coords_format_contract.py` — CU-3: every non-empty
    `coords_from` parses as four floats.
  RIPPLE: `test_caducean_trajectory.py` must pass unedited — T2.1/T2.2 add a warning and two
  helpers; the schema and `record()` signature are untouched.

- [ ] **T2.5** Full suite + the four locked files. Zero new failures.
  RIPPLE: gate for Wave 3. Waves 2 and 3 touch disjoint files, so a reviewer can land Wave 2
  independently if Wave 3 slips.

---

## Wave 3 — Shared trig module + voice band mapping + EML retrieval path

- [ ] **T3.1** (REQ-7) Create `backend/agent/trig_coupling.py`: `circular_delta`,
  `splay_coupling` (repulsive, `+(k/N)Σsin(θᵢ−θⱼ)`), `align_coupling` (attractive, opposite
  sign). Pure functions over floats; imports limited to `math` and `typing`. Sign convention
  documented in each docstring.
  RIPPLE: **no import of `iris_ffi`, `coupled_registry`, or `phase_manager`** (REQ-7 AC2,
  REQ-14 AC1, CU-1) — this module is the erosion path for the scheduler's CT-3/CT-4 locks, so the
  purity constraint is load-bearing, not stylistic. Signatures accept and return only floats and
  float sequences (CU-2), so no domain object can smuggle reasoning state across the boundary.

- [ ] **T3.2** (REQ-7 AC5) `backend/tests/unit/test_trig_coupling.py` — splay separates and hits
  its fixed point at even spacing (N=2, N=3); align converges; **splay and align have opposite
  signs for identical input**; `circular_delta(0.05, 6.23) ≈ 0.1`; empty list → 0.0; `k=0` → 0.0.
  RIPPLE: the opposite-sign assertion is what makes these two distinct kernels rather than a
  copy-paste error, and the `circular_delta` case is the REQ-8 AC2 wrap bug as a one-liner. Write
  this **before** T3.1 — the test is the requirement.

- [ ] **T3.3** (REQ-7) Refactor the phase manager to consume `splay_coupling` instead of an
  inline implementation.
  RIPPLE: **conditional** — if `specs/caducean-phase-scheduler/` Wave 3 (T3.3 there) has not
  landed, this is a no-op and the module simply awaits its consumer. Coordinate with that spec's
  status before starting. Contract tests CT-3/CT-4 and the new CU-7 must pass after the refactor
  (REQ-14 AC2).

- [ ] **T3.4** (REQ-12) Replace `force_magnitude` scaling in
  [conversation_kernel.py:155](backend/agent/conversation_kernel.py:155) with `|u|`-band
  selection, importing `U_SPLIT` / `U_CONVERGED` from
  [der_constants.py:129-142](backend/agent/der_constants.py:129). Bands: `< U_SPLIT` → short,
  mid → medium, `>= U_CONVERGED` → long. Keep `[TTS_CHUNK_MIN, TTS_CHUNK_MAX]` bounds, the `int`
  return type, and the existing midpoint default on failure.
  RIPPLE: `F(u) = 2u − 2u³` is **zero at both `u=0` and `u=±1`**, so today the least- and
  most-resolved states get identical pacing while the ambivalent middle gets the longest chunks —
  backwards. Band boundaries must match the DER convention exactly (`< U_SPLIT`, `< U_CONVERGED`,
  else converged) so voice and DER never disagree. The consumer at
  [iris_gateway.py:2989-2992](backend/iris_gateway.py:2989) converts tokens→words and is
  unchanged (CU-4). Note the import direction (voice → `der_constants`) in the module docstring
  per design D-7.

- [ ] **T3.5** (REQ-12) Tests:
  - `backend/tests/behavioral/test_chunk_size_bands.py` — `|u|=0.0` and `|u|=1.0` produce
    **different** chunk sizes. This fails today and is the clearest statement of the defect.
  - Physics-aware: chunk size is **monotonic non-decreasing in `|u|`** across
    `{−1.0, −0.6, 0.0, 0.6, 1.0}` — states the intended property independently of the constants,
    so re-tuning `U_SPLIT` cannot break the test.
  - `backend/tests/contract/test_chunk_contract.py` — CU-4.
  RIPPLE: `test_conversation_kernel.py`'s six consolidation tests must pass unedited — they
  assert wiring and that chunk size is *used*, not what it equals.

- [ ] **T3.6** (REQ-13) Add `maybe_refit()` to `TrajectoryController` that delegates to the
  existing `_needs_refit()` milestone logic, and call it from the DER update site.
  RIPPLE: `fit()` reads **all** trajectory rows and runs `np.linalg.lstsq`
  ([trajectory_controller.py:120-133](backend/agent/trajectory_controller.py:120)) — it must run
  at most once per milestone crossing, never per step (REQ-13 AC2). `_REFIT_MILESTONES` and the
  `count < _last_fit_count` reset branch already exist at
  [:96-108](backend/agent/trajectory_controller.py:96); reuse, do not reimplement. numpy failure →
  bootstrap EML rule at [:170-172](backend/agent/trajectory_controller.py:170) (AC3).
  `should_fire`'s signature is unchanged so `test_trajectory_controller.py` holds.

- [ ] **T3.8** (REQ-16 AC1/AC4/AC5/AC6) Make the EML cache per-session in
  `backend/agent/caducean_trajectory.py`: replace the class-level `_eml_cache: float` at
  [:107](backend/agent/caducean_trajectory.py:107) with a lock-guarded
  `Dict[str, Tuple[float, float, float]]` holding `(eml, x, y)`, written from `record()` at
  [:195](backend/agent/caducean_trajectory.py:195) keyed by that call's `session_id`, bounded by
  `MAX_EML_SESSIONS` (64) with age eviction. Add a per-session accessor.
  RIPPLE: ⚠️ **`_eml_cache` is a class attribute written unconditionally**, so today one session's
  EML overwrites every other's — swapping the FFI call for `get_cached_eml()` *without* this task
  would trade a small cost for a real correctness bug. **T3.8 must land before T3.9.**
  `auto_research.py:343` is the only existing caller (REQ-16 AC5, CU-10): either preserve a
  no-argument form with documented process-wide-latest semantics, or update that call site in this
  same change. `record()`'s signature already carries `session_id`, so no new plumbing is needed.
  This file is also edited by T2.2 (`format_coords`) — same agent, or sequence them.

- [ ] **T3.9** (REQ-16 AC2/AC3) Read the cached EML on the DER mid-loop retrieval path
  ([agent_kernel.py:5496-5504](backend/agent/agent_kernel.py:5496)) instead of calling
  `ffi_calculate_eml(_session)` per step. On a cache miss (a session's first step) make **one** live
  FFI call and let `record()` populate the cache for subsequent steps.
  RIPPLE: staleness is exactly one step and that is correct — EML is a function of the `(x, y)`
  accumulators, which advance only when a step runs, so it **cannot change while no step runs**
  (design D-8). Do **not** add a TTL. The existing `try/except` at
  [:5505-5506](backend/agent/agent_kernel.py:5505) must keep preserving today's default limit/score
  when the engine is unavailable. This edit sits ~145 lines from the nearest
  `caducean-phase-scheduler` edit (`_run_step`, ~:5656) — no textual overlap, but re-read the region
  rather than trusting the line number.

- [ ] **T3.10** (REQ-17) Replace the three-branch retrieval cliff at
  [agent_kernel.py:5493-5504](backend/agent/agent_kernel.py:5493) with a continuous explore-pressure
  `p ∈ [-1, +1]` derived from `(eml, x, y)`, mapped to `(limit, min_score)` by **piecewise-linear
  interpolation through the three existing anchors**. Clamp `limit` to `[1, 8]` and `min_score` to
  `[0.30, 0.80]`; round `limit` to an int ≥ 1. Define all band constants and anchors in one place.
  RIPPLE: ⚠️ **`limit` is V-shaped across the anchors** — `explore 5 → neutral 2 → consolidate 3` —
  while `min_score` is monotone (0.40 → 0.55 → 0.65). A single lerp from explore to consolidate
  would put `limit ≈ 4` at neutral and silently double the common case's retrieval work, and **no
  existing test would catch it**. Anchor reproduction (REQ-17 AC3) is the non-regression property —
  assert it before anything else. `episodic.retrieve_similar`'s signature
  ([episodic.py:401-407](backend/memory/episodic.py:401)) is untouched (AC7, CU-9). Do **not** retune
  the anchor values in this task (design D-9).

- [ ] **T3.11** (REQ-17 AC5) Point the cognitive-state phase label at
  [agent_kernel.py:5310-5311](backend/agent/agent_kernel.py:5310) at the same band constants as
  T3.10, removing its independent copies of `1.5` / `1.0`.
  RIPPLE: two consumers currently hardcode the same thresholds and are free to drift. This is the
  smallest task in the wave and the one most likely to be skipped — the drift it prevents is silent.

- [ ] **T3.12** (REQ-16, REQ-17) Tests:
  - `backend/tests/unit/test_eml_cache.py` — **per-session isolation** (session A's write not
    visible to B — fails against today's class attribute), `(eml, x, y)` round-trip, fresh-session
    miss, age eviction, concurrent writes from two session ids.
  - `backend/tests/unit/test_eml_bands.py` — **anchor reproduction** (AC3), `limit` V-shape
    preserved, `min_score` monotone, clamps hold at degenerate `eml`, `limit ≥ 1`,
    `x == y == 0` → neutral pair.
  - `backend/tests/behavioral/test_retrieval_breadth_continuity.py` — (a) zero
    `ffi_calculate_eml` calls on the retrieval path after a session's first step (patch and count);
    (b) two concurrent sessions in different cognitive states get **different** breadths; (c)
    breadth varies smoothly across an EML sweep rather than in three jumps.
  - `backend/tests/contract/test_retrieval_contract.py` — CU-9, CU-10.
  RIPPLE: write these **before** T3.8–T3.11 — the test is the requirement. Assertion (b) and the
  isolation unit test are the two that fail against current code; record those pre-fix failures in
  the MCM as evidence the bugs were real.

- [ ] **T3.7** Full suite + the four locked files. Zero new failures.
  *(Runs last in the wave — after T3.8–T3.12 as well as T3.1–T3.6.)*

---

## Wave 4 — Registry repair and activation (flag-off by default)

Highest risk in the spec: this code path has **never run in production**, so REQ-8/9's fixes are
unproven against real sessions by definition.

- [ ] **T4.1** (REQ-11) Define `DOMAIN_WINDINGS` in one place with rationale per entry:
  `{"der": (1,1), "voice": (2,1), "research": (3,3)}` → `c_eff` 1.000 / 1.581 / 3.000, all inside
  the D-series validated range (overview §4). Pass windings to **both**
  `ffi_caducean_init_session` at
  [agent_kernel.py:5204](backend/agent/agent_kernel.py:5204) and `register_session`
  (REQ-11 AC3). Default `(1,1)` for unclassified sessions (AC4).
  RIPPLE: today the only `init_session` call takes the `l=1, m=1` signature defaults
  ([iris_ffi.py:1189](backend/gateway/iris_ffi.py:1189)), so `c_eff = 1.0` everywhere and every
  ratio is trivially 1:1 — `_is_rational_ratio` always returns `True` and the irrational branch is
  dead. `(2,1)` vs `(3,3)` is `√5:√18`, the C1 configuration from overview §10, which is what makes
  the irrational branch reachable. Note that the registry docstring's suggested `voice (2,2)` gives
  `c_eff = 2.0` — a clean 2:1 *rational* ratio that would leave the irrational branch just as dead
  (Open Question Q3).

- [ ] **T4.2** (REQ-11 AC5) `backend/tests/unit/test_winding_map.py` — at least two distinct
  `c_eff`; at least one configured pair returns `False` from `_is_rational_ratio`.
  RIPPLE: `_compute_c_eff` and `_is_rational_ratio` are **not modified**, so
  `test_c_eff_formula` and `test_rational_ratio_detection` pass unedited.

- [ ] **T4.3** (REQ-8) Replace the discrete alignment gate in
  [coupled_registry.py:183](backend/agent/coupled_registry.py:183) with continuous coupling:
  `circular_delta` for the phase difference and `align_coupling` for the magnitude. Remove the
  `abs(xi1 - xi2) < _PHASE_ALIGNMENT_RAD` threshold as a *gate* on whether coupling happens.
  Preserve the rational/irrational selector (AC4) and all safety bounds (AC3).
  RIPPLE: two bugs fixed at once — the cliff (7° apart got nothing) and the non-wrap-aware
  subtraction (0.05 and 6.23 rad read as 6.18 apart and never coupled). `apply_coupling` must
  still return an event count with `events >= 1` for a rational aligned pair, or
  `test_apply_coupling_rational`'s assertion at
  [test_coupled_registry.py:155](backend/tests/test_coupled_registry.py:155) breaks (REQ-8 AC5,
  CU-5). The existing early return for no partners at
  [:148-149](backend/agent/coupled_registry.py:148) is unchanged.

- [ ] **T4.4** (REQ-9) Fix the symmetry break. Add `role` / `role_assigned_at` to
  `_SessionRecord` (keep `__slots__`). Compute the role from a deterministic, order-independent
  function of **both** sessions' state with a stable total-order tiebreak on session id, then
  apply the nudge in the direction implied by the role of the session being updated — barrier
  positive, nucleus negative. Expire roles per AC4 transience.
  RIPPLE: **this is the bug that makes overview §10's central prediction unreachable.** Today
  `nudge_nucleus = -0.02` is computed at
  [coupled_registry.py:189](backend/agent/coupled_registry.py:189) and never applied; the comment
  claims the other session handles it, but that session runs identical code and also nudges itself
  toward barrier — both become barriers. Because each session invokes `apply_coupling`
  independently with no shared transaction
  ([:136](backend/agent/coupled_registry.py:136)), the rule must be a pure function of both
  states (design D-4). AC3 forbids computing a value and not applying it — that pattern is the
  original defect.

- [ ] **T4.5** (REQ-10) Wire the registry, behind flag `IRIS_CADUCEAN_COUPLING` defaulting to
  **disabled**: `register_session` at Caducean session init, `update_session_state(_session, xi,
  u)` immediately followed by `apply_coupling(_session)` at
  [agent_kernel.py:7327-7350](backend/agent/agent_kernel.py:7327), `unregister_session` at
  conversation end, `MAX_COUPLED_SESSIONS` cap (8).
  RIPPLE: `update_session_state` currently has **zero callers**, so `last_xi`/`last_u` are stuck
  at the `_SessionRecord` initializer zeros
  ([:83-84](backend/agent/coupled_registry.py:83)) — the ordering in AC2 is what makes coupling
  read real state. Skip partners that were registered but never updated rather than coupling
  against zeros (REQ-10 edge case). Any failure logs at debug and never propagates into step
  execution (AC5). Flag-off must mean zero registry calls and zero extra FFI writes.

- [ ] **T4.6** (REQ-8, REQ-9, REQ-10) Tests:
  - `backend/tests/behavioral/test_nucleus_barrier_differentiation.py` — couple two rational
    sessions; assert **exactly one** positive and one negative bias. Must fail before T4.4.
  - `backend/tests/behavioral/test_coupling_order_independence.py` — invoke in both orders;
    assert identical role assignment.
  - `backend/tests/behavioral/test_coupling_flag_off.py` — flag disabled → zero registry calls,
    zero extra FFI writes on the DER path.
  - `backend/tests/contract/test_coupling_contract.py` — CU-5, CU-6.
  - Physics-aware: with two distinct windings, `Twrap` ratios match `1/c_eff` ratios — the
    overview §4 prediction, reachable at runtime for the first time.
  RIPPLE: `test_nucleus_barrier_differentiation` failing before the fix is the proof that the bug
  was real and that the test measures it. Record that failure in the MCM before fixing.

- [ ] **T4.7** (REQ-14, REQ-15) Isolation + observability close-out:
  - `backend/tests/contract/test_trig_coupling_purity.py` — CU-1, CU-2: `trig_coupling` imports
    nothing forbidden and its public functions accept/return only floats and float sequences.
    CU-7 is satisfied by **re-running the scheduler spec's existing
    `backend/tests/contract/test_scheduler_isolation.py` unmodified** — do NOT create a
    second near-identically-named isolation file (see
    `specs/CADUCEAN_SPEC_RECONCILIATION.md` C7).
  - Coupling-event logging per REQ-15 AC3: both session ids, both `c_eff`, rational verdict,
    wrap-aware phase difference, assigned role, applied delta.
  - `scripts/validate_caducean_kernels.py` — all eight harness assertions from design.md.
  RIPPLE: CU-7 is the guard that this spec's unification did not quietly undo the scheduler
  spec's central design decision. Harness assertion 3 (mean-reverting drift, slope ≈ 0) is what
  settles Open Question Q1's `RELAX_STEP`; assertion 6 proves the winding degeneracy is gone
  rather than moved.

- [ ] **T4.8** Tune and record. Run the harness across `RELAX_STEP ∈ {0.05, 0.10, 0.20}` and
  `RELAX_EVERY_N_UPDATES ∈ {5, 10, 25}`; record chosen values, measured drift slope, and answers
  to Q1/Q3/Q4 in "Tuning record" below. Move anything settled into Decisions Locked.

### Tuning record
<!-- T4.8: RELAX_STEP, RELAX_EVERY_N_UPDATES, drift slope with/without relaxation, Q1/Q3/Q4 -->

---

## Wave 5 — Close-out

- [ ] **T5.1** Full verification: `pytest backend/tests -q` plus all four
  `scripts/validate_*.py` harnesses, with `IRIS_CADUCEAN_COUPLING` off and then on. The four
  locked test files pass **unedited** in both configurations. Zero new failures vs T0.1.

- [x] **T5.2** ~~Correct `docs/CADUCEAN_TECHNICAL_OVERVIEW.md`~~ — **DONE 2026-07-27, ahead of
  implementation.** §11 rewritten (built-and-wired with actual limitations; cross-kernel shared Σ
  moved from "future work" to explicitly rejected), §10 gained a dormancy warning, and a new
  §13 "As-Built Reality" records findings F1–F7 with file:line evidence plus the two
  under-documented things that genuinely work (EML→retrieval modulation; NBL/Duffing structural
  parallel).
  **Remaining sub-task for whoever finishes Wave 4:** once the registry is repaired and enabled,
  update §10's dormancy warning and §13 F4 to reflect the new state rather than deleting them —
  the history of *why* they were dormant is the useful part.
  RIPPLE: the stale §11 is what let three separate bugs accumulate in the registry unnoticed —
  the doc claimed things were unbuilt that were built, and presented as validated a structure
  that had never run. Doing this edit first means implementers read an accurate doc.

- [ ] **T5.3** MCM anchoring per `CLAUDE.md`: `record_test` for every new test file (and
  `record_test(..., outcome='fail', description=...)` for the pre-fix
  `test_nucleus_barrier_differentiation` failure, which revealed the symmetry bug),
  `pin_add(title='caducean_kernel_unification', pin_type='decision')`, then
  `mcm_define_feature(name='caducean_kernel_unification', seed_files=[
  'backend/agent/trig_coupling.py', 'backend/agent/param_homeostasis.py',
  'backend/agent/coupled_registry.py', 'backend/agent/conversation_kernel.py',
  'backend/agent/caducean_trajectory.py'], thread_id='<session-id>')`, then
  `mcm_crystallize_landmark(...)`, then `mcm_compress(...)`.

---

## Dependency / parallelization notes

**Hard sequencing:**

- **T0.3 gates T2.1 and T2.3.** REQ-4 AC2 and REQ-6 AC3 must use the same conversation→session
  resolution rule. Guessing it would add a third key mismatch to the path this spec repairs.
- **T0.2 must precede Wave 1.** The ratchet cannot be measured after it is fixed.
- **T1.1 → T1.2 → T1.3 → T1.4** is a strict chain (baselines, then relaxation, then wiring, then
  re-anchoring).
- **T3.1 → T3.3 → T4.3/T4.4.** The shared module must exist before either consumer adopts it.
- **T3.2 before T3.1** (test first — the test is the requirement).
- **T3.8 → T3.9 (hard).** Reading the cache before it is per-session introduces cross-session
  contamination. This is the one ordering in Wave 3 that produces a *correctness* bug if inverted,
  not just churn.
- **T3.10 → T3.11.** The band constants must exist in one place before the second consumer points
  at them.
- **T3.7 last in Wave 3**, after T3.8–T3.12.
- **T4.3 → T4.4 → T4.5.** Repair the coupling math and the symmetry break *before* wiring it into
  the DER path; wiring a bugged coupling into step execution is the one ordering that could
  actually damage a session.

**Parallelizable:**

- **Wave 1, Wave 2, and Wave 3 touch disjoint file sets** and can run concurrently across three
  agents after T0.x:
  - Wave 1 → `param_homeostasis.py`, `conversation_kernel.py:154`, `main.py:2491`
  - Wave 2 → `caducean_trajectory.py`, `agent_kernel.py:3211/3312/7390`
  - Wave 3 → `trig_coupling.py`, `conversation_kernel.py:155`, `trajectory_controller.py`,
    `agent_kernel.py:5310` + `:5493-5504`, `caducean_trajectory.py` (cache), `auto_research.py:343`
  - **Collision to coordinate #1:** Wave 1 (T1.5, line 154) and Wave 3 (T3.4, line 155) edit
    *adjacent lines* of `get_tts_chunk_size`. Assign both to the same agent, or land T1.5 first.
  - **Collision to coordinate #2:** Wave 2 (T2.2, `format_coords`) and Wave 3 (T3.8, EML cache) both
    edit `caducean_trajectory.py`. Different regions — schema helpers vs. the class-level cache —
    but same file: same agent, or sequence them.
- Within Wave 3, the EML sub-thread (T3.8–T3.12) is independent of the trig sub-thread
  (T3.1–T3.3) and of the voice sub-thread (T3.4–T3.5). Three agents can take them concurrently,
  subject to collision #2 above.
- Within Wave 1, T1.6 (observability) is independent of T1.2/T1.3.
- Within Wave 4, T4.1/T4.2 (windings) are independent of T4.3/T4.4 (coupling math).
- All test-writing tasks may be written **before** their implementation tasks. Recommended, not
  merely permitted.
- **No frontend work exists in this spec** — no new bridged event, verified against the
  `ws_event_bridge.py:33-64` allowlist.

**NO-CHANGE-verified areas needing only a contract test:**

| Area | Contract test | Task |
|---|---|---|
| Scheduler isolation from `ξ`/`u` (CT-3/CT-4 preserved) | CU-1, CU-2, CU-7 | T4.7 |
| `iris_ffi.py` — all signatures already sufficient | none needed | — |
| `der_constants.py` — read only, no new constant | CU-4 (via band behavior) | T3.5 |
| `iris_gateway.py` TTS consumer — type and bounds unchanged | CU-4 | T3.5 |
| Episodic EML-modulated retrieval (`agent_kernel.py:5496-5504`) | none needed | verify no interaction with T1.5 |
| `auto_research.py` — existing `fit()` caller unaffected | none needed | — |
| Event bus / bridge / frontend | none needed | — |

**Riskiest tasks, flagged for extra review:**

1. **T4.4** — the symmetry breaker. Two independent invocations must reach the same answer with
   no coordination. Get this wrong and you produce two nuclei or two barriers, i.e. the current
   bug with more code. `test_coupling_order_independence` exists to make it loud.
2. **T4.5** — wiring never-executed code into the DER step path. Flag-off default (design D-5) is
   the mitigation; verify flag-off is genuinely zero-cost, not merely zero-effect.
3. **T2.3** — three call sites must adopt the same chain identifier. Fixing two of three leaves
   the primitive just as broken, and the failure is silent (an empty result set, not an error).
4. **T1.3** — relaxation runs inside a `try` block that already swallows exceptions into
   `loud_error`. Confirm a relaxation failure cannot abort the trajectory record or chain append
   that follow it in the same block.
5. **T3.1** — the purity constraint. An innocuous-looking convenience import of `iris_ffi` into
   `trig_coupling.py` would silently dissolve the scheduler's contract locks, and nothing but
   CU-1 would notice.
6. **T3.9 landing without T3.8** — the only inverted ordering in this spec that causes a
   *correctness* regression rather than rework: retrieval breadth would be driven by whichever
   session recorded most recently. Silent, and plausible-looking in logs.
7. **T3.10's V-shaped `limit`** — the "obvious simplification" (one lerp from explore to
   consolidate) silently doubles retrieval work in the neutral case, which is the common case, and
   no existing test covers it. Assert anchor reproduction first.

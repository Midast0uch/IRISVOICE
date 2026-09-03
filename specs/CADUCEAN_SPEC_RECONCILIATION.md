# Caducean Spec Reconciliation

**Purpose.** Three specs now describe overlapping parts of one system. This file is the single
place recording how they fit together, which conflicts were found, and how each was resolved.
Read it before executing any of the three.

| Spec | Owns | Status |
|---|---|---|
| [`der-loop-integrity-display/`](der-loop-integrity-display/) | DER loop integrity, honest display, ledger learning | Partially executed — Waves 1–9 mixed, **Wave 10 (REQ-13) new** |
| [`caducean-phase-scheduler/`](caducean-phase-scheduler/) | Rate-limit hardening + the trig phase-manager scheduling layer | **Implemented + Wave 6 repair + REQ-22 close-out applied** (105 scheduler tests green; 1 known order-dependent failure) |
| [`caducean-kernel-unification/`](caducean-kernel-unification/) | Parameter homeostasis, shared trig math, physics↔memory coordinate integrity, EML retrieval path | **Ready to implement** — **20 REQs** (REQ-18 satisfied by the delivered kernel; REQ-19/20 added from the Wave 6 review) (REQ-16/17 added 2026-07-27 from [`docs/learned-scoreboard-vs-live-state.md`](../docs/learned-scoreboard-vs-live-state.md) §4C) |

The governing boundary across all three: **the scheduler layer never reads Caducean reasoning
state (`ξ`, `u`), and the cognitive layer never depends on scheduling.** Everything below either
protects that boundary or resolves an ambiguity that could erode it.

---

## Recommended execution order

```
1. der-loop-integrity-display    Wave 10  (REQ-13, ledger learning)   ← independent, backend-only
2. caducean-kernel-unification   Waves 0–1 (baseline + homeostasis)   ← strictly corrective
3. caducean-kernel-unification   T3.1 + T3.2 (trig_coupling + tests)  ← DONE (C10 resolved)
4. caducean-phase-scheduler      Waves 0–1 (rate-limit hardening)     ← DONE
5. caducean-kernel-unification   Wave 2   (memory coordinate integrity)
6. caducean-phase-scheduler      Waves 2–4 (meter, phase manager, batching)
7. caducean-kernel-unification   Waves 3–4 (band mapping, registry repair)
```

Rationale for the interleave, not a strict preference:

- **Step 1 is fully independent** — different files entirely, and it repairs a live
  reward-hacking hole.
- **Step 2 before everything Caducean-adjacent.** The parameter ratchet degrades every long
  session; fixing it first means all later measurement happens against a non-drifting baseline.
- **Step 3 is deliberately hoisted out of its own spec's Wave 3.** `trig_coupling.py` plus its
  unit tests is a small, dependency-free unit that both later consumers need. Landing it early
  prevents the phase manager from being written with inline math that immediately needs
  refactoring (conflict **C3**).
- **Step 4 is what actually stops the 429s** and is independent of all Caducean state.
- Steps 5–7 are the larger builds and can run in either order; 7 is last because registry
  activation is the highest-risk change in any of the three specs.

Waves within a spec that touch disjoint files may still be parallelized per that spec's own
notes. The one file both specs edit heavily is `agent_kernel.py` — see **C4**.

---

## Conflicts found and resolved

### C1 — `coupled_registry.py`: "contract lock" read as "frozen" ⚠️ **was a real risk**

**Conflict.** `caducean-phase-scheduler` classified `coupled_registry.py` as
`CONTRACT LOCK — stays as-is`, pinned by CT-3. `caducean-kernel-unification` REQ-8/9/10
*rewrites* that module's coupling math and wires it into the DER path. An agent executing the
scheduler spec, reading CT-3 as a freeze, could block or revert legitimate work.

**Resolution.** CT-3 is **directional** and always was, in substance: its assertion is that
*the scheduler never calls* `apply_coupling` / `register_session` / `update_session_state`, and
never writes `ffi_caducean_set_params`. It says nothing about whether the module may change. The
scheduler ripple-map row was the misleading part and has been corrected to say
"No change *from this spec*" with an explicit pointer here.

**Substantive check.** kernel-unification wires `apply_coupling` into the **DER update path**
(`agent_kernel.py:7327`), not into any scheduler module. CT-3 and CT-4 both still hold after
that wiring. No behavioral conflict — only a documentation one.

### C2 — `der_constants.py`: contradictory classifications ⚠️ **self-inconsistent**

**Conflict.** The scheduler spec's ripple row said `No` while its own note admitted adding
`DER_MAX_CONCURRENT_STEPS`. Separately, kernel-unification lists the file as
`NO CHANGE (verified)`.

**Resolution.** The scheduler row is corrected to `Yes (one constant only)`. The two specs are
compatible as written: the scheduler **adds** `DER_MAX_CONCURRENT_STEPS` (genuinely DER-scoped);
kernel-unification only **reads** `U_SPLIT` / `U_CONVERGED` and adds nothing. If the scheduler
lands first, kernel-unification's "verified NO CHANGE" becomes stale in wording but remains true
in substance — it still adds no constant.

**Note for later.** If a third consumer needs `U_SPLIT`/`U_CONVERGED`, move those two constants
to a physics-constants module (already flagged as kernel-unification design D-7's caveat about
voice importing from a DER-named module).

### C3 — `phase_manager.py` coupling math: duplicate implementation risk

**Conflict.** The scheduler spec created `phase_manager.py` with inline sine coupling;
kernel-unification T3.3 then refactored it to import `trig_coupling`. Whichever landed first,
one of the two would write or rewrite the same math.

**Resolution.** `trig_coupling.py` is the single home from the start. Scheduler T3.3 now
explicitly imports it and instructs landing kernel-unification T3.1+T3.2 first if the module is
absent. Reflected in the execution order above (step 3 hoisted).

**Guard.** kernel-unification CU-1 asserts `trig_coupling.py` imports nothing beyond stdlib, so
consuming it from the scheduler cannot breach CT-4. Without CU-1, a convenience import of
`iris_ffi` into the shared module would silently dissolve the scheduler's isolation — the single
most dangerous edit either spec enables.

### C4 — Both specs edit `agent_kernel.py`: merge coordination

**Conflict.** Not a semantic conflict — the two specs touch **disjoint regions** of an
8,700-line file:

| Spec | Regions |
|---|---|
| phase-scheduler | `_der_exec_steps_concurrent` (~:6960-6977), `_execute_plan_der` entry (~:5239), extra-step retry (~:5766-5771), `_run_step` (~:5656-5671) |
| kernel-unification | Caducean update block in `_der_finalize_step` (~:7305-7400), document path (~:3211, ~:3312) |

**Resolution.** No textual overlap; standard merge coordination suffices. Whoever lands second
should re-read the target region rather than trusting a line number from their spec — line
numbers in both specs are pinned to the current `HEAD` and will shift.

### C5 — Scheduler throttling would slow parameter recovery 🔴 **genuine emergent conflict**

**Conflict.** The one neither spec anticipated. kernel-unification's relaxation cadence was
counted purely in **engine updates** (every 10). The scheduler's amplitude coupling
(phase-scheduler REQ-9) deliberately **reduces background firing rate under provider load**,
which reduces DER steps per minute, which reduces engine updates per minute. So with both specs
active under load:

- Perturbations (TOPO_VIOLATIONs, barge-ins) continue at their own rate — they are driven by
  session difficulty and user behavior, not by step throughput.
- Recovery slows in proportion to the throttling.
- Net: **parameter drift accelerates precisely when the system is under stress**, which is when
  the ratchet fix matters most. The counterweight weakens exactly where it is needed.

**Resolution.** kernel-unification REQ-1 gains **AC2b**: relaxation additionally fires when
`RELAX_MAX_INTERVAL_S` (60 s) of wall-clock has elapsed, regardless of update count. This
decouples recovery rate from step rate. T1.2 and T1.7 updated to implement and assert it (a
behavioral test with the update counter frozen).

**Why this is worth noting beyond the fix.** Both specs individually reason about "cadence on the
existing update site" as a *simplification* (no new background task). It is — but two
independent components both riding the same cadence means anything that throttles that cadence
throttles both. Any future component tempted to ride the DER update site should check this
interaction first.

### C6 — `metrics()` naming collision (low severity)

**Conflict.** phase-scheduler REQ-20 AC4 defines `metrics()` on the rate meter;
kernel-unification REQ-15 AC2 defines a `metrics()`-style snapshot on `param_homeostasis`. Legal
Python, but ambiguous for any future observability aggregator importing both.

**Resolution.** Name them by subject: `rate_meter.provider_metrics()` and
`param_homeostasis.param_metrics()`. No requirement text changed — this is an implementation
naming convention recorded here so both implementers pick the same one.

### C7 — Near-duplicate isolation test files (maintenance hazard)

**Conflict.** phase-scheduler creates
`backend/tests/contract/test_scheduler_isolation.py` (CT-3, CT-4). kernel-unification originally
created `test_scheduler_isolation_preserved.py` (CU-1, CU-2, CU-7) — two files with near-identical
names asserting overlapping properties, the classic setup for one being updated and the other
silently rotting.

**Resolution.** kernel-unification's file is renamed to `test_trig_coupling_purity.py`, covering
only what is genuinely new (CU-1, CU-2 — shared-module purity and float-only signatures). CU-7
("scheduler isolation still holds") is satisfied by **re-running the scheduler spec's existing
file unmodified**, which is a stronger assertion anyway: it proves the original lock survived
rather than asserting a paraphrase of it.

### C8 — Wave and task-ID namespace collision (cosmetic, but confusing)

**Observation.** Both specs have a "Wave 3" and both have a task numbered "T3.3", doing unrelated
things. kernel-unification T3.3 already disambiguates by writing "(T3.3 there)".

**Resolution.** No renumbering — the specs are self-contained and renumbering would invalidate
existing cross-references. **Convention:** always qualify cross-spec task references as
`<spec-dir>/T<n>`, e.g. `caducean-phase-scheduler/T3.3`.

---

### C9 — REQ-16/REQ-17 (EML retrieval path) vs the scheduler: checked, clear

**Added 2026-07-27** when `caducean-kernel-unification` gained REQ-16 (per-session EML cache) and
REQ-17 (continuous retrieval breadth). Checked on four surfaces; **no conflict on any**, but the
reasoning is worth recording because one of them is the exact inverse of C5.

| Surface | Verdict |
|---|---|
| **Textual overlap in `agent_kernel.py`** | **None.** REQ-16/17 edit `:5310-5311` (phase label) and `:5493-5504` (retrieval block). The nearest scheduler edit is `_run_step` at ~`:5656` — ~145 lines away. Both specs already carry the standing instruction to re-read the region rather than trust a line number (**C4**). |
| **`caducean_trajectory.py`** | **No scheduler involvement.** The scheduler does not touch this file at all; kernel-unification already owns it (REQ-4/5). The only coordination needed is *within* kernel-unification — T2.2 and T3.8 edit different regions of the same file (recorded in that spec's parallelization notes). |
| **Does scheduler throttling make the EML cache stale?** | **No — and this is the inverse of C5.** The cache is written per `record()` call, i.e. **indexed by step, not wall clock**. EML is a function of the `(x, y)` accumulators, which advance only when a step runs, so EML *cannot change while no step runs*. Throttling reduces steps per minute and EML changes per minute in exact proportion, so a step-indexed cache stays exact under any amount of throttling. Contrast C5, where relaxation genuinely *did* need a wall-clock floor because parameter perturbations arrive independently of step throughput. **Same system, two caches, opposite correct answers — do not "fix" either to match the other.** See kernel-unification design D-8. |
| **Is retrieval a gated call?** | **No.** REQ-17 changes `limit` / `min_score` passed to `episodic.retrieve_similar`, which is a SQLite + embedding read, not an LLM call — so it never passes through `InferenceRouter.generate()` and is never phase-gated. Consistent with the scheduler spec's Non-Requirement excluding embedding/vector-store gating ("not currently a `429` source"). A larger `limit` costs local I/O, not provider quota. |

**One thing to watch, not a conflict.** REQ-17 can raise `limit` up to 8 (from today's max of 5).
That is more local retrieval work per step, and it lands on the DER step path — which is also where
the scheduler's `PHASE_MAX_WAIT_S` latency budget is spent. Neither spec's budget is threatened at
these magnitudes (SQLite reads against a local DB), but if the retrieval clamp is ever raised
further, check it against the scheduler's latency accounting rather than assuming headroom.

### C10 — The shared `trig_coupling` module was built defectively, defeating BOTH consumers ✅ RESOLVED 2026-07-27

> **Resolved.** The phase-scheduler Wave 6 repair landed the signed per-oscillator kernel
> (`splay_force` / `align_force`). Verified: leading `+0.029950`, trailing `-0.029950` —
> genuinely opposite signs. CU-1 still holds (imports are `math`/`typing` only), so CT-4
> isolation is intact. **One trap remains:** `splay_coupling` / `align_coupling` survive as
> aliases to the NON-NEGATIVE magnitude aggregates. kernel-unification REQ-7/REQ-8 name
> `align_coupling` — calling it would reintroduce F4. Both specs now require `align_force`
> on every update path; the magnitude forms are diagnostic-only.


**Added 2026-07-27** after auditing the delivered phase-scheduler implementation.
`backend/agent/trig_coupling.py` exists (landed by phase-scheduler Wave 3, per this document's
recommended step 3). **CU-1 holds** — imports are `math` and `typing` only, so the scheduler's
CT-4 isolation is intact. But both kernels return a **single non-negative scalar** folded through
`abs()`:

```python
splay_coupling(thetas, k) = (k/N) * sum_i | sum_j sin(theta_j - theta_i) |   # >= 0
align_coupling(thetas, k) = -splay_coupling(thetas, k)                      # <= 0
```

**This defeats each consumer's purpose in the same way, for the same reason:**

| Consumer | What it needs | What the scalar does |
|---|---|---|
| phase-scheduler REQ-12 (repulsion) | Push oscillator *i* away from its neighbours | Applies the **same** value to every oscillator → absolute phase advances, **relative phase never changes** → zero spreading (verified: 200 ticks left Δθ at 0.100000) |
| kernel-unification REQ-8/REQ-9 (differentiation) | One session → nucleus, the other → barrier (**opposite** signs) | Applies the same non-positive value to both → **both become barriers** → this is overview finding **F4** reproduced inside the shared module |

Compounding: the inner term is `sin(θⱼ − θᵢ)` — the **attractive** convention — inside a function
documented as *repulsive*, with `abs()` masking the contradiction. And `align = -splay` is not the
sign-flip of a signed force; it is the negation of a magnitude.

**Resolution.** One change satisfies both specs, and it must be made once:

- phase-scheduler **T6.1** (Wave 6 repair, REQ-21 AC1/AC2)
- kernel-unification **REQ-18** (amendment appended 2026-07-27)

Export a **signed per-oscillator** primitive (`pair_force(θᵢ, θⱼ) = sin(θᵢ − θⱼ)`, or
`forces(thetas, k) -> List[float]`), derive both kernels from it by sign alone, and never `abs()`
a value used to advance a phase or nudge a parameter. A magnitude aggregate may remain for
diagnostics under a name that says so.

**Whichever spec executes first lands it; the other consumes it.** Do **not** implement
kernel-unification REQ-8/REQ-9 against the current scalar kernels — the result would pass a
positivity test and produce no differentiation, indistinguishable from the F4 bug the spec exists
to fix.

**Lesson worth keeping.** This is the first defect to hit both specs through their *shared*
dependency, which is the risk C3 created when it centralized the math. Centralizing was still
right — one fix now repairs both consumers instead of two divergent hand-rolled versions — but it
means **`trig_coupling.py` needs the strictest test discipline of any module in these three
specs**. CU-1 guarded its *imports*; nothing guarded its *semantics*. Both amendments now require
a direction assertion (leading vs trailing oscillator get opposite signs), not a sign-of-aggregate
assertion.

---

## Non-conflicts worth recording

These look like conflicts and are not. Recorded so nobody "fixes" a non-problem.

- **Winding numbers do not affect scheduling.** kernel-unification REQ-11 changes `c_eff`, which
  changes the Caducean `ξ` advance rate and `Twrap`. The scheduler uses its **own** θ (D-2), so
  the change has *zero* effect on scheduling. This is the isolation paying off — and it is the
  clearest demonstration of why D-2 was worth the extra state.
- **`resilience.py`** is touched only by phase-scheduler (`NO_RETRY_ERRORS`). kernel-unification
  does not touch it.
- **`.mcm/` files are disjoint**: `der_params.json` (outer loop, existing),
  `provider_ceilings.json` (phase-scheduler). kernel-unification persists nothing — its baselines
  are in-memory and reset on restart, which is consistent with the FFI's own params resetting on
  restart. Not a gap.
- **Both specs add zero `IRISStreamEvent` members** and both independently verified the
  `ws_event_bridge.py:33-64` allowlist. No frontend work in either. Consistent.
- **Feature flags are distinct and independently defaulted off**: `IRIS_PHASE_SCHEDULER`,
  `IRIS_CADUCEAN_COUPLING`. Four combinations are all valid; the C5 interaction is the only one
  where the combination matters, and it is now resolved.
- **`der-loop-integrity-display` Wave 10 is fully independent** of both Caducean specs — it edits
  `outer_loop.py`, `memory.py`, and adds tests. No overlap with either ripple map.

---

## Shared contract-lock register

The locks that span specs. Breaking any of these breaks a *different* spec's guarantee than the
one you are working in, which is why they are collected here.

| Lock | Asserted by | Protects | Must not be read as |
|---|---|---|---|
| **CT-3** | phase-scheduler | Scheduler never *calls* the coupled registry | "`coupled_registry.py` is frozen" (see C1) |
| **CT-4** | phase-scheduler | Scheduler never calls `ffi_caducean_*` | "nothing may call the FFI" |
| **CU-1** | kernel-unification | `trig_coupling.py` imports nothing beyond stdlib | a style rule — it is what keeps CT-4 enforceable once both layers share a module |
| **CU-7** | kernel-unification | CT-3/CT-4 still pass after unification | a reason to duplicate the isolation test (see C7) |
| **4 locked test files** | kernel-unification | `test_coupled_registry.py`, `test_conversation_kernel.py`, `test_trajectory_controller.py`, `test_caducean_trajectory.py` pass **unedited** | optional — per `CLAUDE.md` the test is the requirement |
| **`QueueItem` field shape** | both (CT-5 / CU-5 adjacent) | `result`, `is_subloop`, `depth_layer`, `expected_output` stable for `resolve_dependent_params` | safe to extend without re-running both specs' tests |

---

## Open cross-spec questions

- **Q-X1 — Should relaxation and the scheduler share one cadence source?** C5 was resolved by
  giving relaxation an independent wall-clock floor. A cleaner long-term answer is a single
  "system tick" abstraction that both consume, but that reintroduces the background task both
  specs deliberately avoided (phase-scheduler D-3, kernel-unification D-1). Deferred; revisit
  only if a third component wants the same cadence.
- **Q-X2 — Where do `U_SPLIT` / `U_CONVERGED` ultimately live?** Currently `der_constants.py`,
  read by voice after kernel-unification T3.4. Fine for two consumers; move to a physics-constants
  module at three. See C2.
- **Q-X3 — Does the scheduler ever get to read memory?** Explicitly out of scope in both specs
  today. The defensible future version reads *Mycelium pheromone weights* (a learned prior over
  which work matters) to set `natural_period_s`; the indefensible version reads live `u`/`ξ`. If
  this is ever built, the line is "learned prior, yes; live reasoning state, no" — and it needs
  its own spec plus an amendment to CT-4's rationale, not a quiet import.

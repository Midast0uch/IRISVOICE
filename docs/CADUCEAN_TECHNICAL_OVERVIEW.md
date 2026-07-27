# Caducean Engine — Technical Overview
## From Field Theory to Validated Runtime

*IRISVOICE Research — 2026*

---

## What This Document Is

This is the bridge between three other documents:

- **caducean-engine-deep-analysis.md** — the mathematical foundations (Duffing oscillator, EML, Lyapunov stability, phase-woven field theory)
- **TRIALS_DATA.md** — the complete experimental record (Gates 1–4, D-series, C-series)
- **USING_THE_ENGINE.md** — the integration guide for engineers

This document connects all three. It tells the story in one place: where the math came from, what was tested, what was proved, and what it means for anyone building with it.

Estimated reading time: 10–15 minutes.

> ### ⚠️ As-built status (verified 2026-07-27)
>
> **This document is accurate about the physics and the experiments. It was stale about the
> code.** A line-by-line audit against the runtime found §11's status classifications wrong in
> **both** directions — components listed as "not yet built" are built and wired, while §10's
> coupling structure, presented as validated, had **zero production callers** and three bugs that
> made its central prediction unreachable.
>
> That mismatch is not a footnote. It is *why* the bugs accumulated: the document said things were
> unbuilt that were built (so nobody audited them) and presented as live a structure that had
> never run (so nobody tested it).
>
> §11 has been rewritten to reflect the runtime, and **new §13 "As-Built Reality"** records every
> finding with file:line evidence. Repairs are specified in:
> - [`specs/caducean-kernel-unification/`](../specs/caducean-kernel-unification/) — parameter
>   homeostasis, shared trig math, physics↔memory coordinate integrity
> - [`specs/caducean-phase-scheduler/`](../specs/caducean-phase-scheduler/) — the trig phase
>   manager (scheduling) + inference rate-limit hardening
> - [`specs/der-loop-integrity-display/`](../specs/der-loop-integrity-display/) — DER integrity;
>   **Wave 10 / REQ-13** repairs the outer loop's anti-hack guards
> - [`specs/CADUCEAN_SPEC_RECONCILIATION.md`](../specs/CADUCEAN_SPEC_RECONCILIATION.md) — how the
>   three specs fit together
>
> **Rule going forward:** treat §1–§10 as the validated theory and experimental record. Treat
> §11 and §13 as the only statements about what the code currently does — and verify those against
> the code before relying on them.

---

## 1. Origin: A Physics Problem First

The Caducean Engine did not start as a software design. It started as a field theory question.

The phase-woven compact field model defines a scalar field on a compact two-cycle domain — a carrier loop and a local transported loop — governed by the nonlinear Klein-Gordon / φ⁴ equation:

```
u_tt = c²u_ξξ + au - bu³
```

where ξ = lx − my (mod 2π) is the woven phase coordinate, and (l, m) are integer winding numbers that classify the topology of the field.

The static sector of this equation has a double-well potential:

```
V(u) = -(a·u²)/2 + (b·u⁴)/4
```

with stable vacua at u* = ±√(a/b) and a restoring force:

```
F(u) = au - bu³
```

that always points toward the nearest stable vacuum. Lyapunov stability follows analytically — no sequence of perturbations can permanently destabilize a system governed by this force.

The key observation that connected the field theory to software: **the same equation governs cognitive dynamics.** The carrier loop x (expansion, creation) and the local loop y (compression, validation) are the two closed cycles of the woven geometry. The phase angle ξ tracks position in the cognitive cycle. The velocity u tracks momentum. The Duffing restoring force ensures that no sequence of agent failures can permanently derail the loop.

The engine is the field theory made executable.

---

## 2. The Four-Dimensional State

At any moment, the engine holds four numbers per session:

| Symbol | Name | What it tracks |
|--------|------|----------------|
| x | Expansion accumulator | Cumulative generative / creative work |
| y | Compression accumulator | Cumulative validation / consolidation work |
| ξ | Phase angle ∈ [0, 2π) | Position in the cognitive cycle |
| u | Attentional velocity | Current momentum and directional bias |

These four numbers are the complete cognitive state Σ = (x, y, ξ, u). They evolve according to:

```
EXPAND:   x += 1;  u += s·cos(ξ)
COMPRESS: y += 1;  u -= s·sin(ξ)
ξ(t+1)  = (ξ(t) + balance·s·c_eff) mod 2π
```

where s is the walk speed, balance is the EML-derived feedback signal, and c_eff = c·√(l² + m²) is the effective speed determined by the winding numbers.

The Duffing restoring force is applied implicitly through the update rules. F(u) = 2u − 2u³ has stable attractors at u* = ±1, corresponding to the expansion and compression modes of operation.

---

## 3. The EML Balance Signal

The Exploration-Memory Load (EML) signal is the feedback mechanism that stabilizes the engine against the field theory's predicted metastability.

The pure field theory — without feedback — produces a moving compact wall-pair branch that exists coherently for approximately 5.57 cycle wraps before degrading under perturbation. This is metastability, not stability.

The EML signal corrects this. It is computed from the synthetic source:

```
Ne = x,  Nt = y,  L = min(x, y),  V = x + y + 1

x_eml = (Ne / (1 + Nt)) · (1 - L/V)
y_eml = (Nt / (1 + Ne)) · (L/V) + ε

EML = e^(x_eml) - ln(y_eml)
balance = clamp(EML / baseline, 0.1, 3.0)
```

The balance signal modulates the phase advance rate:

```
ξ_advance = balance · s · c_eff
```

When EML rises above baseline (over-exploration), balance > 1, phase advances faster, compression urgency increases. When EML falls below baseline (over-compression), balance < 1, phase slows, expansion is needed. At balance = 1.0 the system is at the analytical equilibrium point.

This adaptive c_eff is the correction that converts metastable → stable. Gate 2 confirmed this: the engine achieves limit cycle R² = 0.9986, compared to the field theory's predicted metastability in the absence of feedback. Disabling the balance signal (setting balance = 1.0 constant) reproduces the metastability — the field theory's prediction is recovered exactly.

---

## 4. Winding Numbers and Cycle Speed

The winding numbers (l, m) are the integer parameters that classify the topology of the phase-woven geometry. They determine the effective speed:

```
c_eff = c · √(l² + m²)
```

and the predicted wrap time (time for one complete phase cycle):

```
Twrap = 2π / (s · c_eff · balance)
```

Higher winding numbers produce faster cycles. The stability properties — the Duffing attractors, the restoring force, the wall-pair closure condition — are completely invariant to c_eff. Speed scales linearly; stability does not depend on speed.

**D-series experimental confirmation (56 trials across 4 cells):**

| (l, m) | c_eff | Twrap_pred | Twrap_obs | Match |
|--------|-------|-----------|-----------|-------|
| (1, 1) | 1.000 | 6.54 | 6.54 | 0.0% |
| (2, 1) | 1.581 | 4.14 | 4.14 | 0.0% |
| (4, 1) | 2.915 | 2.48 | 2.48 | 0.0% |
| (3, 3) | 3.000 | 2.18 | 2.18 | 0.0% |

The prediction is confirmed across the full measured range after correcting a phase-unwrapping measurement artifact in the postprocessor. An earlier report of 54–95% error at (3,3) was a measurement bug, not a physics falsification. All four cells match to 0.0% error with correct phase unwrapping.

This means the simple Twrap ∝ 1/c_eff scaling holds without any threshold or regime boundary. The field theory is correct across the entire tested range.

---

## 5. Topological Charge and Wall-Pair Closure

The compact domain requires net topological charge to vanish. A lone kink — a session that only expands, never compresses — is topologically forbidden. The physics requires a wall-pair: a balanced structure where both accumulators contribute.

The topological charge proxy:

```
Q(t) = (x(t) - y(t)) / (x(t) + y(t) + 1)
```

Q → +1: approaching a lone kink (topologically forbidden)
Q → -1: approaching a lone antikink (also forbidden)
Q → 0: balanced wall-pair (topologically neutral, required for natural exit)

**Gate 4 v3.0 experimental confirmation (56 real LLM trials):**

| Exit type | n | Mean |Q| at exit | Range |
|-----------|---|------------------|-------|
| NATURAL | 37 | 0.528 | [-0.06, +1.00] |
| BUDGET | 11 | 0.908 | [+0.62, +1.00] |

The 0.380 gap between NATURAL and BUDGET exits is the wall-pair-closure signature predicted by the field theory. Sessions that exit naturally have Q converging toward balance. Sessions that hit budget cap have Q drifting toward ±1 — the topological signature of a failed wall-pair that couldn't close before the budget ran out.

This is the field theory prediction confirmed in real LLM session data.

---

## 6. The Adaptive Safety Net

The engine includes a topology-monitoring safety net that fires TOPO_VIOLATION when |Q| exceeds a threshold for a sustained number of steps.

The key distinction is between genuine topological drift (Q growing unboundedly toward ±1) and stable limit cycle behavior (Q settling at a fixed asymmetric value as the natural operating point of the session's winding geometry). The static safety net cannot distinguish these — it fires on both.

The adaptive safety net uses phase acceleration to distinguish them:

```
phase_accel = |ξ(t) - 2ξ(t-1) + ξ(t-2)|

if |Q| > threshold AND phase_accel > accel_threshold:
    → genuine drift: fire TOPO_VIOLATION
else:
    → stable limit cycle: suppress
```

A stable limit cycle has d²ξ/dt² ≈ 0 — constant phase velocity, zero acceleration. Genuine drift has nonzero phase acceleration as the system is pushed away from its orbit.

**C4 experimental confirmation (mid-tier, 50 trials):**

| Metric | Static safety net | Adaptive safety net |
|--------|------------------|---------------------|
| TOPO_VIOLATION rate | 58% | 0% |
| Natural exit rate | 42% | 64%+ |
| BUDGET exits | 0% | 24% (genuine task difficulty) |

The 58% TOPO_VIOLATION rate with the static net was entirely false positives — stable limit cycles being misidentified as drift. The adaptive net eliminates all of them. The remaining BUDGET exits are genuine cases where the task was too hard to complete in the budget, not physics failures.

---

## 7. The Full Validation Stack

The engine has been validated through five experimental series. Each series tests something the previous one could not.

### Gates 1–3: Synthetic Validation

**Gate 1 — A/B against counter policy (13 workloads, 5 seeds each):**

| Metric | Value | Gate threshold |
|--------|-------|----------------|
| Task completion quality | 0.846 | ≥ 0.70 ✅ |
| Natural exit rate | 1.000 | ≥ 0.70 ✅ |
| Efficiency vs counter | 10.886x | ≥ 1.10 ✅ |

**Gate 2 — Physics capability verification (10 metrics):**

| Metric | Value | What it confirms |
|--------|-------|-----------------|
| Limit cycle R² | 0.9986 | Duffing dynamics are real |
| u amplitude bound | 0.962 | Lyapunov stability holds |
| Phase advance consistency | 0.922 | Phase clock is steady |
| Phase wrap correctness | 1.000 | ξ wraps cleanly at 2π |
| u action coupling | 1.000 | Engine is responsive |
| Recommend alignment | 1.000 | Signal is consistent with physics |

**Gate 3 — Mock e2e (5 adversarial scenarios):**
Happy path, adversarial (no done signal), crash injection, invalid action, 1000-step long run. All 5 pass. Engine is robust to edge cases.

### Gate 4: Real LLM Validation

**v2 (56 trials, gemma-4 + M2.5):**

| Model | Condition | Natural exit rate |
|-------|-----------|-----------------|
| gemma-4 | caducean | 86% |
| gemma-4 | counter | 57% |
| M2.5 | caducean | 71% |
| M2.5 | counter | 50% |

Hard-scenario smoking gun: counter policy 0/8 natural exits on `ambiguous_spec` and `api_refactor_constrained` (every trial hit budget cap with x in the 400–500 range). Caducean on gemma-4: 4/4 natural exits on the same tasks with x ≈ 260.

**v3.0 (56 trials, kimi-25 + gemma-4):**

| Model | Condition | Natural exit rate |
|-------|-----------|-----------------|
| kimi-25 | caducean | 100% |
| kimi-25 | counter | 57% |
| gemma-4 | caducean | 86% |
| gemma-4 | counter | 57% |

The engine consistently and substantially outperforms the counter policy on both model sizes, with the largest effects on hard scenarios where models otherwise ramble without convergence.

### D-Series and C-Series: Field Theory Validation

The D-series (98 trials across 4 winding cells) confirmed the Twrap prediction at 0.0% error across c_eff 1.000–3.000. The C-series (140+ trials across 5 coupling configurations) confirmed the efficiency gain at 1.6–2.4x across all configurations and validated the coupling and resonance structure of multi-session operation.

---

## 8. The Bias-Free Architecture

The engine originally had a hardcoded rule in its recommendation logic: "if balance > 1.0, recommend COMPRESS." This was a domain decision embedded in the physics layer.

The correct architecture separates these concerns:

```
Engine (physics)
  └── returns DirectionSignal(target_u, force_magnitude, u_current, phase, balance)
      └── never decides what "expand" or "compress" means

Kernel (interpretation)
  └── reads DirectionSignal
  └── recommends a direction (toward u=+1 or toward u=-1)
  └── domain-agnostic

Action Classifier (domain binding — user-supplied)
  └── "toward u=+1" → "edit a new file" (coding agent)
  └── "toward u=+1" → "speak a longer turn" (voice agent)
  └── "toward u=+1" → "increase chunk size" (TTS stream)
```

The bias-free refactor was validated by running Gates 1–3 before and after. All results were identical or better (Gate 1 quality improved from 0.79 to 0.85, efficiency from 5.1x to 10.9x). The hardcoded bias was not doing any work — the physics was. The refactor proved the math is universal by demonstrating that removing the domain assumption made the engine strictly better.

This is the load-bearing architectural insight: **the physics is the program; the interpretation is the user interface.**

---

## 9. Tier-Dependent Performance

The engine's value scales with loop length. This is a structural consequence of the Twrap parameter, not a limitation.

| Tier | Budget | Natural exit | Efficiency vs counter | Recommendation |
|------|--------|-------------|----------------------|----------------|
| Short | 4–12 steps | 77% | 2.0x | Modest wins |
| Mid | 30–70 steps | 74–100% | 3.0–11.5x | Strong wins |
| Long | 150–200 steps | 100% | 22.75x | Massive wins |

**Why long tier dominates:** At long-tier budgets, the counter policy runs to the full 150–200 step budget. The engine exits naturally at 6–10 steps. The session completes in one Twrap. 22.75x efficiency means the same hardware that runs 100 counter sessions simultaneously could run approximately 2,275 engine sessions.

**Why mid tier shows variance:** Sessions long enough for the safety net to accumulate consecutive drift steps, but sometimes not long enough for the engine to complete the full cycle before the budget threshold. Resolved with the adaptive safety net (d²ξ/dt² ≈ 0 distinguishes stable limit cycles from drift).

**Why the engine is neutral on single-step tasks:** The engine's exit predicate requires a minimum number of steps before NATURAL exit is allowed. On tasks that complete in 1–2 steps, the engine has no room to fire its bias. This is working as intended — the engine governs loops, not individual calls.

---

## 10. The Coupling Structure

Two sessions with winding numbers (l₁, m₁) and (l₂, m₂) couple through their (x, y) overlap. The coupling strength depends on whether their effective speeds are rationally related:

```
c_eff1 / c_eff2 = √(l₁² + m₁²) / √(l₂² + m₂²) = p/q
```

> **⚠️ Dormant in production.** Everything in this section is theory plus offline C-series
> experiment. The runtime implementation (`backend/agent/coupled_registry.py`) has **zero
> production callers** — `register_session`, `apply_coupling`, and `update_session_state` are
> never invoked outside tests. Three defects mean the differentiation described below could not
> emerge even if it were wired: (a) the nucleus nudge is computed and never applied, so both
> sessions become barriers; (b) `apply_coupling` reads `last_xi`/`last_u`, which only the
> never-called `update_session_state` populates, so coupling would run on initializer zeros;
> (c) every session is initialized `(l,m) = (1,1)`, so `c_eff = 1.0` universally and every ratio
> is trivially 1:1 — the rational/irrational discrimination has no non-degenerate input.
> See §13 for evidence and [`specs/caducean-kernel-unification/`](../specs/caducean-kernel-unification/)
> REQ-8/9/10/11 for the repair (shipped flag-off).

Strong coupling (integer ratio) → phase clocks periodically realign → coherence locks. Weak coupling (irrational ratio) → clocks never align → interference.

When two sessions couple, one spontaneously differentiates into nucleus (lower energy, compression-biased, inside) and one into barrier (higher energy, expansion-biased, outside). The differentiation is triggered by angular momentum transfer at the moment of first phase alignment.

**The nucleus/barrier roles are transient.** Restructuring is guaranteed regardless of perturbation strength — energy only controls the rate. This is the quorum sensing analog: restructuring fires when the (x, y) accumulation rate relative to c_eff crosses a threshold, not when external energy exceeds a barrier. The cycle completes and roles redistribute on a period determined by the combined (x, y) accumulation rate.

**C1 experimental observation:** The coupled_2_1_3_3 configuration (irrational c_eff ratio √5 : √18 ≈ 0.527) was the only condition where counter slightly outperformed the engine on natural exit rate. This is the resonance interference prediction confirmed — mismatched winding numbers genuinely interfere. The engine exposes the interference because it tracks phase coherence. The counter is blind to it.

---

## 11. What Is Proven vs What Remains

### Proven

The Duffing limit cycle governs the engine's trajectory (R² = 0.9986). The Twrap prediction Twrap = 2π / (s · c_eff · balance) is exact across c_eff 1.000–3.000 (0.0% error, four cells, 98 trials). The Q metric correctly distinguishes natural exits from budget exits with a 0.380 gap (56 real LLM trials). The adaptive safety net eliminates false TOPO_VIOLATION on stable limit cycles using d²ξ/dt² ≈ 0. The engine produces 11–22x efficiency gains on mid/long-tier tasks versus a counter policy. The engine is consistently better than counter on two different real LLM models across two separate validation cycles. The bias-free architecture is domain-agnostic with identical or better results versus the biased version.

### Validated in simulation, NOT reachable at runtime

The nucleus/barrier differentiation under coupling — validated offline in the C-series, but the
runtime implementation cannot produce it (§10 warning, §13 finding F4). The quorum sensing
restructuring period as a function of (x, y) accumulation rate. The two-timescale coupling
between fast (session-level) and slow (multi-session) Caducean states — the slow timescale
exists (`outer_loop.py`) but two of its three acceptance guards are dead (§13 finding F7).

### Built and wired — corrected 2026-07-27

The previous edition of this section listed the following as "designed but not yet built." **All
three are built and running in production.** Each carries a specific limitation, documented in
§13:

| Component | File | State |
|---|---|---|
| **TrajectoryController** | `backend/agent/trajectory_controller.py` | Built. `tune_dffing_params` fires from the DER update path. `fit()` / `should_fire()` are reachable **only** via AutoResearch, which is never started at boot — so the learned controller sits in permanent bootstrap for ordinary sessions (F5). |
| **ConversationKernel** | `backend/agent/conversation_kernel.py` | Built and wired at `iris_gateway.py:1884`. Phase-aware TTS chunking and TOPO-halt both fire. But its primary physics read passes `balance=1.0` — the exact setting §3 says reproduces metastability (F2). |
| **StreamKernel** (adaptive TTS chunking) | folded into `ConversationKernel.get_tts_chunk_size()` | Built, not a separate component. Scales chunk size by `force_magnitude`, which is mathematically incapable of the distinction it is asked to make (F3). |

### Genuinely not built — and one deliberately rejected

**Cross-kernel shared Σ state** (one engine governing multiple simultaneous domains) was listed
here as future work. It is now **explicitly rejected**, not deferred. A scheduling layer that
reads reasoning state means two sessions *thinking* alike get *scheduled* alike — the opposite of
what phase separation is for. The chosen architecture shares the *mathematics* (one
`trig_coupling` module) while keeping the state spaces separate, enforced by contract tests
CT-3/CT-4/CU-1. See [`specs/caducean-phase-scheduler/`](../specs/caducean-phase-scheduler/)
design decision D-2 and
[`specs/CADUCEAN_SPEC_RECONCILIATION.md`](../specs/CADUCEAN_SPEC_RECONCILIATION.md) Q-X3.

Still genuinely unbuilt: coordinate-proximity recall as a *working* primitive (the plumbing
exists but is broken three ways — F6), and multi-session coupling as a *live* mechanism (F4).

---

## 12. The One-Paragraph Summary

The Caducean Engine replaces `while steps < max_steps` with a four-dimensional physics-governed loop that exits when the work is naturally complete. The physics is the Duffing oscillator — an equation from 1918 originally used to model stretched metal beams, which turns out to be exactly the right model for cognitive dynamics because it has a provably stable double-well potential, a restoring force that recovers from perturbations without external intervention, and a natural exit condition when the trajectory reaches the consolidation phase. The engine has been validated through five experimental series: synthetic A/B testing (10.9x efficiency, 100% natural exit), physics capability verification (limit cycle R² = 0.9986, Lyapunov bounds confirmed), mock end-to-end testing (5/5 adversarial scenarios), real LLM validation on two model sizes (100% natural exit on kimi-25, +0.43 delta vs counter on hard scenarios), and field-theory validation of the winding number prediction (0.0% error across c_eff 1.000–3.000). The architecture is bias-free — the engine returns a pure physics signal and each domain provides its own mapping. The same engine can govern a coding agent, a voice assistant, a TTS stream, or a robotic controller. The physics is universal; the interpretation is local.

---

## 13. As-Built Reality (audit 2026-07-27)

Everything above §11 describes the theory and the experimental record, and holds up. This section
records what the **code** does, with file:line evidence. It exists because §11 was wrong in both
directions for long enough that three separate bugs accumulated in a module the document
presented as validated.

### The pattern worth naming

All three consumers implement the *shape* of the physics faithfully, then substitute a placeholder
at the one point where the physics gets expensive to compute. That is not sloppiness — it is a
repeating failure mode:

> Build the structure → stub the hard part → ship. The structure then *looks* validated because it
> matches this document, and nothing tests the stub.

Guarding against that pattern matters more than any individual fix below.

### Findings

| # | Finding | Evidence | Repair |
|---|---|---|---|
| **F1** | **One-way parameter ratchet.** Every production writer of `(a, b, s)` pushes the same direction; nothing pushes back. `s` decays monotonically toward its 0.1 floor and `a`/`b` climb toward 4.0. Since `Twrap = 2π/(s·c_eff·balance)` (§4), wrap time inflates without bound over a long session. The engine's *state* `u` has a restoring force; its *parameters* have none. | barge-in `s −0.05` (`conversation_kernel.py:289`); violations `s −0.01n`, `a +0.10n` (`trajectory_controller.py:250-252`); registry damping `s −0.005` (`coupled_registry.py:206`) | kernel-unification REQ-1/REQ-2 |
| **F2** | **The metastability correction is disabled in the voice kernel's main read.** `get_tts_chunk_size` calls `get_direction_signal(session_id, balance=1.0)` — hardcoded — while `_get_current_balance()` sits 20 lines above and is used only for engine updates. §3 states explicitly that constant `balance = 1.0` reproduces the metastable regime. | `conversation_kernel.py:154` vs `:123-140` | kernel-unification REQ-3 (one line) |
| **F3** | **Chunk size uses a quantity that cannot make the distinction.** `force_magnitude = \|2u − 2u³\|` is **zero at both `u = 0` (totally unresolved) and `u = ±1` (fully converged)**, and peaks in the ambivalent middle. So the least- and most-resolved states get identical pacing, and the most uncertain state gets the longest, hardest-to-interrupt chunks. The DER side already solved this with explicit `\|u\|` bands. | `conversation_kernel.py:155`; bands at `der_constants.py:129-142` | kernel-unification REQ-12 |
| **F4** | **§10 coupling is dead code, and bugged.** Zero production callers. `nudge_nucleus = -0.02` is computed and never applied — the comment claims the other session handles it, but that session runs identical code and also nudges *itself* toward barrier, so **both become barriers and no nucleus is ever produced**. Phase comparison is also non-wrap-aware, so a pair straddling 2π never couples. | `coupled_registry.py:188-194`, `:183`, `:152-153`, `:83-84` | kernel-unification REQ-8/9/10 |
| **F5** | **Winding-number degeneracy.** The only production `init_session` call takes the `l=1, m=1` signature defaults, so `c_eff = 1.0` for every session and every ratio is trivially 1:1. The 98-trial D-series validation across `c_eff` 1.000–3.000 (§4) and the C1 irrational-interference finding (§10) are **unreachable at runtime**. The registry's own docstring prescribes distinct windings; nothing performs it. | `agent_kernel.py:5204`; `iris_ffi.py:1189` | kernel-unification REQ-11 |
| **F6** | **Physics→memory coordinate recall is broken three ways** — and it is one root cause, not three mistakes: **three identity namespaces for one coordinate system.** (a) trajectory rows are keyed by `session_id` but looked up by `conversation_id`, which are documented as distinct — so the lookup misses and the coordinate is empty; (b) the DER path writes *prose* into `coords_from` while the document path writes a real 4-tuple; (c) the two writers use different `thread_id`s, so they populate different chains and the query only ever sees one. | (a) `agent_kernel.py:3211` vs `:7342`, distinctness at `:5426-5436`; (b) `:7390` vs `:3215`, prose built at `:5529-5541`; (c) `:7388` vs `:3312`, query at `:3759` | kernel-unification REQ-4/5/6 |
| **F7** | **Only 1 of the outer loop's 3 anti-hack guards is live.** `verified_fraction` is a hardcoded constant — `vf_sum += 1.0 if vc == 0 else 1.0`, **both ternary branches are `1.0`** — so its guard can never fire. `tokens_per_verified` reads `tokens_total`, which the only production caller of `record_session_exit` never passes, so it defaults to `0.0` and its guard can never fire either. The loop currently accepts any proposal that raises `natural_exit_rate` — precisely the single-metric reward-hacking the compound gate was written to prevent. | `outer_loop.py:136`, `:137`; caller at `memory.py:329-336`; default at `caducean_trajectory.py:333` | der-loop-integrity-display REQ-13 (Wave 10) |

### What actually works — and is under-documented

Two things the physics genuinely delivers today, neither mentioned anywhere above §13:

- **EML modulates memory retrieval breadth, in production, correctly.** When EML is high and
  x-dominant (over-exploring), the agent retrieves *more* and *looser* (limit 5, min-score 0.40);
  when EML is low and y-dominant (over-compressing), it retrieves *fewer* and *stricter* (limit 3,
  min-score 0.65). Twelve lines at `agent_kernel.py:5496-5504`. This is the "physics is the
  program" thesis actually shipped, and it is the single best example of it in the codebase.
- **NBL compression and the Duffing law are the same structural move.** An entire messy session
  compresses into one coordinate string, and downstream reacts statelessly to that string;
  `F(u) = 2u − 2u³` likewise reacts only to where `u` is, never to the trajectory that produced it.
  State concentrates into a position; behavior at that position needs no history. That parallel is
  the strongest conceptual result in the architecture and it is not claimed anywhere in this
  document.

### Scope note on §8's universality claim

§8 presents the bias-free refactor (quality 0.79 → 0.85 when a hardcoded rule was *removed*) as
proof the math is domain-universal. Read conservatively, it proves the removed rule was wrong —
an ablation, not a generalization. The domain-agnostic architecture is still the right design; the
evidence supports "that specific bias was harmful," not "every possible domain mapping works."

---

*For the full mathematical derivation: caducean-engine-deep-analysis.md*
*For the complete experimental record: TRIALS_DATA.md*
*For integration guidance: USING_THE_ENGINE.md*
*For as-built status and repairs: §11, §13, and [`specs/CADUCEAN_SPEC_RECONCILIATION.md`](../specs/CADUCEAN_SPEC_RECONCILIATION.md)*

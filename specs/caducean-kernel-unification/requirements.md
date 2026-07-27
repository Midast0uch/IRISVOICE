# Requirements: Caducean Kernel Unification — Parameter Homeostasis, Shared Trig Coupling, and Physics↔Memory Coordinate Integrity

## Decisions Locked

Carried forward from the audit conversation on 2026-07-27. Do **not** re-litigate.

1. **Unify the math, not the state.** One shared pure-trig module exports the coupling
   kernels; each consumer keeps its own state space. The scheduler's isolation from Caducean
   `ξ` (contract-locked as CT-3/CT-4 in `specs/caducean-phase-scheduler/`) is **preserved
   unchanged** — scheduling must never become a function of reasoning state.
2. **The parameter ratchet is the highest-priority defect.** Every production writer of
   `(a, b, s)` pushes the same direction. Fixed first, in Wave 1, because it silently degrades
   every long session regardless of what else is built.
3. **`CADUCEAN_TECHNICAL_OVERVIEW.md` §11 is stale in both directions** and is corrected by
   this spec rather than trusted: it lists ConversationKernel and TrajectoryController as
   "designed but not yet built" (both are built and wired), while the §10 coupling structure it
   presents as validated is dead code in production.
4. **Scope note — REQ-4/5/6 are additions beyond the six audit items.** They were discovered
   while verifying the memory coupling for this spec and are included because they break the
   same physics-to-memory contract the other requirements strengthen. Called out explicitly so
   the growth in scope is visible, not silent.

## Introduction

Three Caducean consumers were cultivated from `docs/CADUCEAN_TECHNICAL_OVERVIEW.md`: the DER
governor (working), the ConversationKernel (wired but running at roughly half its design), and
the CoupledTrajectoryRegistry (§10 — **zero production callers**, and bugged such that its
central prediction could not emerge even if wired).

Verification found five classes of defect: a one-way parameter ratchet shared by every writer;
the metastability correction disabled in the voice kernel's main physics read; a
symmetry-breaking bug that makes nucleus/barrier differentiation impossible; a winding-number
degeneracy that makes the entire resonance apparatus unreachable; and two key/format
mismatches that silently null out the flagship memory primitive ("data gathered while thinking
like this").

This spec repairs all five and factors the shared sine-coupling mathematics into one module, so
the phase scheduler and the cognitive registry are two consumers of one validated kernel rather
than two hand-rolled approximations of the same equation.

### Success criteria

- A 200-step session with 10 barge-ins and 5 TOPO_VIOLATIONs ends with `(a, b, s)` within
  ±0.15 of baseline `(2.0, 2.0, 0.35)`, instead of pinned at the `s=0.1` floor and
  `a→4.0` ceiling.
- `ConversationKernel.get_tts_chunk_size()` reads live EML balance; a behavioral test shows
  chunk size responding to balance, which it provably cannot do today.
- Two coupled sessions with rationally-related `c_eff` produce **exactly one nucleus and one
  barrier**, asserted by opposite-signed `u` bias. Today both become barriers.
- At least two distinct `c_eff` values exist at runtime, so `_is_rational_ratio` has a
  non-degenerate input. Today every session is `(1,1)` → `c_eff = 1.0` → every pair trivially
  1:1.
- `coords_from` is a parseable 4-tuple on **every** Immortus chain entry that claims to carry a
  coordinate; a contract test rejects prose in that field.
- Trajectory-proximity recall returns a non-empty result set for a session whose trajectory was
  recorded — currently impossible via the document path because of a lookup-key mismatch.
- `backend/tests/test_coupled_registry.py`, `test_conversation_kernel.py`,
  `test_trajectory_controller.py`, and `test_caducean_trajectory.py` pass **unmodified**
  (verified compatible — see the note below).

### Existing-test compatibility (verified, and binding)

Per `CLAUDE.md`, tests are the requirement and must never be edited to accommodate code. The
existing assertions were checked against every change in this spec:

| Test | Assertion | Compatible because |
|---|---|---|
| `test_coupled_registry.py::test_apply_coupling_rational` | `events >= 1` and `abs(Δa) > 0 or abs(Δs) > 0` | Any param change satisfies it; the symmetry fix (REQ-9) still changes one param on the self session. |
| `test_coupled_registry.py::test_c_eff_formula` | `_compute_c_eff` values for (1,1), (2,1), (3,3) | `_compute_c_eff` is not modified. |
| `test_coupled_registry.py::test_rational_ratio_detection` | exact/irrational pairs | `_is_rational_ratio` is not modified. |
| `test_trajectory_controller.py::test_tune_dffing_params_clamps` | `a,b ∈ [1,4]`, `s ∈ [0.1,0.8]` | Homeostatic relaxation (REQ-1) operates strictly inside these ranges. |
| `test_conversation_kernel.py` (6 consolidation tests) | no duplicate VAD/TTS, callbacks wired, chunk size used, halt breaks loop | REQ-3/REQ-12 change the chunk-size *value*, not the wiring or the call contract. |

If any of these fails, the change is wrong — not the test.

---

## Requirements

---

### REQ-1: Homeostatic relaxation of the Duffing parameters (fix the one-way ratchet)

**User Story:** As a long-running session I want the engine's own parameters to recover toward
baseline after perturbation so that a few barge-ins and violations cannot permanently cripple
my walk speed.

**Verified:** REAL GAP — every production writer of `(a, b, s)` pushes the same direction, and
nothing pushes back:

| Writer | `s` | `a` / `b` |
|---|---|---|
| Barge-in nudge, [conversation_kernel.py:289-292](backend/agent/conversation_kernel.py:289) | **−0.05** | — |
| `tune_dffing_params`, [trajectory_controller.py:250-252](backend/agent/trajectory_controller.py:250) | **−0.01 × violations** | **+0.10 / +0.05 × violations** |
| Registry damping, [coupled_registry.py:206-207](backend/agent/coupled_registry.py:206) (dormant) | **−0.005** | **+0.02** |

`s` decays monotonically toward its 0.1 floor and `a`/`b` climb toward 4.0. Since
`Twrap = 2π / (s · c_eff · balance)` (overview §4), wrap time inflates without bound. The
engine's *state* `u` has a restoring force; its *parameters* have none.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide a single `relax_params(session_id)` operation that moves
  `(a, b, s)` a bounded step toward the session's baseline.
- AC2: THE SYSTEM SHALL apply relaxation on a cadence of every `RELAX_EVERY_N_UPDATES`
  engine updates (default 10), invoked from the existing DER update site so no new timer or
  background task is introduced.
- AC2b: THE SYSTEM SHALL **additionally** relax when `RELAX_MAX_INTERVAL_S` (default 60 s) has
  elapsed since the last relaxation for that session, regardless of update count.
  **Why this exists (cross-spec interaction, see `specs/CADUCEAN_SPEC_RECONCILIATION.md` C5):**
  an update-count-only cadence is throttled by anything that slows the step rate. The phase
  scheduler's amplitude coupling (`specs/caducean-phase-scheduler/` REQ-9) deliberately reduces
  background firing rate under provider load, which reduces engine updates per minute — so
  recovery would slow down at exactly the moment perturbations (violations, barge-ins) are most
  likely. A wall-clock floor decouples recovery rate from step rate and closes the interaction.
- AC3: THE SYSTEM SHALL move each parameter by at most `RELAX_STEP` fraction (default 0.10) of
  its distance to baseline per invocation, so relaxation is a gentle pull and never a reset
  that erases a legitimate perturbation.
- AC4: THE SYSTEM SHALL keep every relaxed value inside the established safe ranges
  `a, b ∈ [1.0, 4.0]` and `s ∈ [0.1, 0.8]`, preserving the invariant asserted by
  `test_tune_dffing_params_clamps`.
- AC5: WHEN a parameter is already within `RELAX_DEADBAND` (default 0.02) of baseline THEN THE
  SYSTEM SHALL leave it unchanged, so relaxation does not generate perpetual no-op FFI writes.
- AC6: IF the FFI is unavailable THEN THE SYSTEM SHALL skip relaxation, log at debug, and
  never raise into the DER step path.

**Edge Cases:**
- Unknown session → `ffi_caducean_get_state` returns defaults, which *are* baseline, so
  AC5's deadband makes relaxation a no-op. Correct behavior, no special case needed.
- Sustained perturbation (a violation every step) → relaxation and perturbation reach a
  dynamic equilibrium away from baseline. This is intended: the parameters should reflect a
  genuinely unstable session, just not ratchet permanently.
- A single catastrophic session that pins `s` to 0.1 → relaxation recovers it over
  ~`ceil(log(0.02/0.25)/log(0.9))` ≈ 25 invocations ≈ 250 updates. Document this recovery time.

---

### REQ-2: Manual parameter override re-anchors the baseline

**User Story:** As an operator tuning the engine through the API I want my chosen values
respected rather than slowly undone by the homeostat.

**Verified:** REAL CONFLICT — a fourth `set_params` writer exists that REQ-1 would fight:
[main.py:2487-2491](backend/main.py:2487), a FROZEN-response HTTP endpoint accepting explicit
`(a, b, s)`. Without this requirement, REQ-1 would silently drag an operator's deliberate
setting back toward 2.0/2.0/0.35 over a few hundred updates.

**Acceptance Criteria:**
- AC1: WHEN parameters are set through the operator API THEN THE SYSTEM SHALL record the
  supplied values as that session's new relaxation baseline.
- AC2: THE SYSTEM SHALL default a session's baseline to `(2.0, 2.0, 0.35)` — the Gate 1
  baseline documented in `trajectory_controller.py:197-200` — when no override has been made.
- AC3: THE SYSTEM SHALL scope baselines per session id and SHALL NOT let one session's
  override affect another's.
- AC4: THE SYSTEM SHALL bound baseline storage so a long-lived process accumulating many
  session ids cannot grow without limit, evicting by last-touch age.
- AC5: THE SYSTEM SHALL NOT alter the operator endpoint's frozen response contract
  (`{"ok", "session_id", "applied"}`).

**Edge Cases:**
- Override that is itself out of safe range → the FFI clamps it (per the endpoint's read-back
  at `main.py:2494`); the baseline SHALL record the **clamped** value, not the requested one,
  so relaxation targets a reachable point.
- Override during an active DER run → takes effect on the next relaxation cadence; no
  mid-step reconfiguration.

---

### REQ-3: Voice kernel reads live EML balance (re-enable the metastability correction)

**User Story:** As the voice pipeline I want my phase-driven decisions to use the adaptive
balance signal so that I am not running in the regime the field theory predicts is metastable.

**Verified:** REAL GAP — [conversation_kernel.py:154](backend/agent/conversation_kernel.py:154)
calls `ffi_caducean_get_direction_signal(session_id, balance=1.0)` with balance **hardcoded to
1.0**, while `_get_current_balance()` — which computes the real value — sits 20 lines above at
[conversation_kernel.py:123-140](backend/agent/conversation_kernel.py:123) and is used only for
`ffi_caducean_update`. Overview §3 states plainly that constant `balance = 1.0` *reproduces the
metastable regime exactly*: "Disabling the balance signal (setting balance = 1.0 constant)
reproduces the metastability." The single correction that converts metastable → stable is
therefore switched off in the voice kernel's primary physics read.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL pass the live balance from `_get_current_balance()` into
  `ffi_caducean_get_direction_signal`.
- AC2: THE SYSTEM SHALL keep balance clamped to `[0.1, 3.0]` per the v2 Caducean contract
  already implemented at `conversation_kernel.py:137`.
- AC3: IF balance computation fails THEN THE SYSTEM SHALL fall back to 1.0 and log at debug —
  preserving today's behavior as the failure path rather than as the normal path.
- AC4: THE SYSTEM SHALL NOT change the method's signature or return type, so the six
  consolidation tests in `test_conversation_kernel.py` remain valid unmodified.

**Edge Cases:**
- No active session (`session_id_getter()` returns `None`) → existing early return at
  `conversation_kernel.py:152-153` is unchanged.
- Engine unavailable → AC3 fallback; chunk size degrades to today's value, never to a crash.

---

### REQ-4: Trajectory-coordinate lookup uses the key the trajectory was written under

**User Story:** As the memory layer I want a document's reasoning-state coordinate to actually
resolve so that trajectory-proximity recall has coordinates to match against.

**Verified:** REAL GAP, silent — the write and the read use **different keys**:

- Written: `recorder.record(session_id=_session, …)` at
  [agent_kernel.py:7341-7342](backend/agent/agent_kernel.py:7341), where `_session` is the
  kernel session.
- Read: `get_latest_coordinate(conversation_id)` at
  [agent_kernel.py:3211](backend/agent/agent_kernel.py:3211), which queries
  `WHERE session_id = ?` ([caducean_trajectory.py:281-285](backend/agent/caducean_trajectory.py:281)).

`conversation_id` and `session_id` are documented as distinct in this very file — the WS handler
passes the client id as `session_id` and the conversation/thread id as `conversation_id`
([agent_kernel.py:5426-5436](backend/agent/agent_kernel.py:5426)). So for every WebSocket
session the lookup misses, `_coord is None`, and `coords_from` stays `""`. The flagship
primitive described at `agent_kernel.py:3202-3206` — "what lets W7/O1 do trajectory-proximity
recall" — is storing documents at *no coordinate at all*. `get_latest_coordinate` has zero other
callers, so this is its only use.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL query the latest trajectory coordinate using the same identifier the
  recorder writes rows under.
- AC2: WHERE the caller holds only a conversation id THEN THE SYSTEM SHALL resolve it to the
  recording session id through an explicit, documented mapping rather than assuming the two are
  interchangeable.
- AC3: THE SYSTEM SHALL fall back to the conversation id as a secondary lookup, so
  REST-path sessions (which do use the conversation id as the kernel session, per
  `api/chat.py:305`) continue to resolve.
- AC4: WHEN no coordinate resolves under either key THEN THE SYSTEM SHALL log at **warning**
  with both keys tried, not silently produce `""`.
- AC5: THE SYSTEM SHALL keep the empty-string fallback as the behavior of last resort so a
  missing coordinate never blocks a document store.

**Edge Cases:**
- Genuinely first document of a session, before any trajectory row exists → `""` is correct;
  AC4's warning must distinguish "no rows yet" from "key mismatch" so the log is actionable.
- Session id changes mid-conversation (conversation switching, per
  `specs/session-conversation-switching/`) → AC2's mapping must be read at call time, not cached.

---

### REQ-5: One coordinate format on the Immortus chain

**User Story:** As a coordinate-proximity query I want every `coords_from` value to be a
coordinate so that I can compare them.

**Verified:** REAL GAP — the same field carries two incompatible formats on the same chain:

- Document path: `coords_from = "{x:.4f},{y:.4f},{xi:.4f},{u:.4f}"` — a real 4-tuple
  ([agent_kernel.py:3215](backend/agent/agent_kernel.py:3215)).
- DER step path: `coords_from=getattr(item, "coordinate_signal", "")` at
  [agent_kernel.py:7390](backend/agent/agent_kernel.py:7390) — but `coordinate_signal` is
  **prose**, accumulating `topology_position` plus `"\nSUB-TASK HINT: …"` and
  `"\nPAST FAILURE WARNING: …"` at [agent_kernel.py:5529-5541](backend/agent/agent_kernel.py:5529).

So `ffi_immortus_chain_query_by_coordinate` ([agent_kernel.py:3755](backend/agent/agent_kernel.py:3755))
can never match a DER step entry — half the chain is unqueryable by the primitive that
justifies the chain's existence.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL write `coords_from` in exactly one canonical format: four
  comma-separated fixed-precision floats `x,y,xi,u`.
- AC2: THE SYSTEM SHALL provide one shared formatter and one shared parser for that format, used
  by every writer and reader, so the format is defined in a single place.
- AC3: WHEN a DER step appends to the chain THEN THE SYSTEM SHALL supply the live
  `(x, y, ξ, u)` — already in scope at that call site as `_ex`, `_ey`, `_xi`, `_u`
  ([agent_kernel.py:7343-7347](backend/agent/agent_kernel.py:7343)) — instead of
  `coordinate_signal`.
- AC4: THE SYSTEM SHALL preserve the prose `coordinate_signal` by routing it to the `insight`
  field or another descriptive field, so the sub-task hints and failure warnings it carries are
  not lost.
- AC5: IF a coordinate cannot be produced THEN THE SYSTEM SHALL write an empty string rather
  than a partial or prose value, so the parser's contract is "valid 4-tuple or empty".
- AC6: A contract test SHALL reject any non-empty `coords_from` that does not parse as four
  floats.

**Edge Cases:**
- Pre-existing chain rows written with prose → the parser SHALL treat unparseable values as
  "no coordinate" and skip them, never raise. No migration is required.
- Coordinate containing `NaN`/`inf` from a degenerate engine state → formatter SHALL emit empty
  rather than a token that parses to `NaN` and poisons distance comparisons.

---

### REQ-6: One chain identity for physics-adjacent entries

**User Story:** As a proximity query I want the entries I am comparing to be on the same chain
so that a match is possible at all.

**Verified:** REAL GAP — DER step entries use `thread_id=_session`
([agent_kernel.py:7388](backend/agent/agent_kernel.py:7388)) while document entries use
`thread_id=conversation_id` ([agent_kernel.py:3312](backend/agent/agent_kernel.py:3312)), and
the query filters by `thread_id=conversation_id`
([agent_kernel.py:3759](backend/agent/agent_kernel.py:3759)). The two writers therefore populate
**different chains**, and the query only ever sees one of them. Combined with REQ-4 and REQ-5,
all three legs of the proximity primitive are independently broken.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL use one consistent chain identifier for all entries intended to be
  mutually queryable by coordinate.
- AC2: THE SYSTEM SHALL document, at both append sites, which identifier is canonical and why.
- AC3: WHERE a session id and a conversation id differ THEN THE SYSTEM SHALL apply the same
  resolution rule adopted for REQ-4 AC2, so the two requirements cannot drift apart.
- AC4: A behavioral test SHALL record a DER step and store a document in one conversation, then
  assert a coordinate query returns the document — end-to-end proof the three legs now line up.

**Edge Cases:**
- Existing rows on the "wrong" chain → treated as historical; no migration. The test asserts
  new-entry behavior only.
- `keep_latest` pruning (`ffi_immortus_chain_keep_latest`) operating per thread id → consolidating
  onto one chain changes what pruning retains. Verify the pruning call site is consistent with
  the chosen identifier.

---

### REQ-7: One shared trig-coupling module (unify the math, not the state)

**User Story:** As a maintainer I want the sine-coupling mathematics implemented once so that
the scheduler and the cognitive registry cannot drift into two different approximations of the
same equation.

**Verified:** DUPLICATION CONFIRMED — the cognitive registry hand-rolls a square-wave
approximation (threshold test `abs(xi1 - xi2) < 0.1` plus a fixed ±0.02 nudge at
[coupled_registry.py:183-194](backend/agent/coupled_registry.py:183)) of the same
sine-of-phase-difference relation that `specs/caducean-phase-scheduler/` REQ-12 implements
properly. Both are instances of `f(Δθ) = ε · sin(Δθ)`, differing only in sign convention and
what they modulate.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide a pure-math module exporting at least two kernels: a repulsive
  (splay) coupling for scheduling and an attractive (differentiating) coupling for cognitive
  phase alignment.
- AC2: THE SYSTEM SHALL keep the module free of I/O, FFI, logging side effects, and any import
  of the phase manager, the registry, or the Caducean gateway — it takes floats and returns
  floats.
- AC3: THE SYSTEM SHALL document the sign convention explicitly, since the two consumers need
  opposite signs and a flipped sign silently inverts the intended behavior.
- AC4: THE SYSTEM SHALL NOT introduce shared mutable state between consumers; each keeps its
  own state space (Decision Locked #1).
- AC5: THE SYSTEM SHALL be covered by unit tests asserting the splay fixed point (coupling → 0
  at even spacing for N=2 and N=3) and the alignment fixed point.

**Edge Cases:**
- Empty neighbor list → returns 0.0 (no coupling), not a division by zero.
- Identical phases → returns 0.0; both consumers must document that ties are prevented by
  placement, not resolved by coupling.
- `K = 0` → coupling disabled; both consumers must remain functional.

---

### REQ-8: Continuous sine coupling replaces the discrete alignment threshold

**User Story:** As the cognitive registry I want coupling strength to vary smoothly with phase
distance so that differentiation is graded rather than an on/off event at an arbitrary
tolerance.

**Verified:** REAL GAP — [coupled_registry.py:183](backend/agent/coupled_registry.py:183) fires
only when `abs(xi1 - xi2) < _PHASE_ALIGNMENT_RAD` (0.1 rad ≈ 6°) and then applies a fixed
±0.02. Two consequences: (a) sessions 7° apart get *nothing*, which is a cliff not a coupling;
(b) the comparison is a raw subtraction, so it is **not wrap-aware** — phases at 0.05 and 6.23
rad are ~0.1 rad apart on the circle but read as 6.18 apart and never couple.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL compute coupling from the REQ-7 kernel as a continuous function of
  phase difference, with no threshold gate on whether coupling occurs.
- AC2: THE SYSTEM SHALL compute phase differences on the circle (wrap-aware), so a pair
  straddling `2π` is treated as close.
- AC3: THE SYSTEM SHALL preserve the existing safety bounds on all applied values:
  `u ∈ [-1, 1]`, `a, b ∈ [1, 4]`, `s ∈ [0.1, 0.8]`.
- AC4: THE SYSTEM SHALL keep the rational/irrational `c_eff` discrimination as the selector
  between attractive and damping coupling — that structure is validated (overview §10, C1) and
  is not being replaced, only its phase term.
- AC5: THE SYSTEM SHALL keep `apply_coupling`'s return contract (count of coupling events
  applied) so `test_apply_coupling_rational`'s `events >= 1` assertion holds unmodified.

**Edge Cases:**
- Exactly antiphase (Δ = π) under attractive coupling → `sin(π) = 0`, an unstable fixed point.
  Document it; do not add a special case.
- Single registered session → no partners, early return at
  [coupled_registry.py:148-149](backend/agent/coupled_registry.py:148) unchanged.

---

### REQ-9: Nucleus/barrier differentiation actually breaks symmetry

**User Story:** As two coupled sessions I want exactly one of us to become the nucleus and the
other the barrier so that the differentiation the field theory predicts can actually occur.

**Verified:** REAL BUG — at
[coupled_registry.py:188-194](backend/agent/coupled_registry.py:188), `nudge_nucleus = -0.02`
is computed and **never applied**. The comment claims the nucleus role is "handled in the other
session's own apply_coupling call" — but the other session runs the identical code and also
nudges *itself* toward barrier (`nudge_barrier`). Both sessions become barriers; no nucleus is
ever produced. The nucleus/barrier differentiation presented in overview §10 as an observed
Gross-Pitaevskii analog cannot emerge from this implementation.

**Acceptance Criteria:**
- AC1: WHEN two sessions couple at phase alignment THEN THE SYSTEM SHALL assign the barrier
  role to exactly one and the nucleus role to exactly one.
- AC2: THE SYSTEM SHALL select the role by a deterministic, order-independent symmetry breaker
  computed from both sessions' state, so both parties' independent invocations agree on the
  assignment without coordination.
- AC3: THE SYSTEM SHALL apply the nudge in the direction implied by the role assigned to the
  session being updated — barrier positive, nucleus negative — and SHALL NOT compute a value it
  does not apply.
- AC4: THE SYSTEM SHALL keep role assignment transient, consistent with overview §10's
  statement that "the nucleus/barrier roles are transient" and redistribute on the cycle period.
- AC5: A behavioral test SHALL couple two sessions and assert **opposite-signed** bias — one
  positive, one negative. The current implementation must fail this test before the fix.

**Edge Cases:**
- Perfectly symmetric sessions (identical state) → the breaker SHALL fall back to a stable
  total order (e.g. session id comparison) so a decision is always reached and is stable
  across invocations.
- Three or more coupled sessions → roles assigned pairwise; document that a global one-nucleus
  guarantee is not claimed for N>2, since the field theory's prediction is a pair property.

---

### REQ-10: Wire the registry to live state at the existing update site

**User Story:** As the coupling layer I want to receive real `(ξ, u)` values so that my
decisions are based on the sessions' actual physics rather than on zeros.

**Verified:** DEAD CODE + STALE-STATE BUG. `register_session`, `apply_coupling`, and
`update_session_state` have **zero callers** outside the module and its tests (verified by
search). And even if `apply_coupling` were called, it reads `self_rec.last_xi` / `last_u`
([coupled_registry.py:152-153](backend/agent/coupled_registry.py:152)), which only
`update_session_state` populates — so every coupling decision would run on the
`_SessionRecord` initializers `last_xi = 0.0, last_u = 0.0`
([coupled_registry.py:83-84](backend/agent/coupled_registry.py:83)). The module's own docstring
prescribes the call order (`update_session_state` then `apply_coupling`); nothing performs it.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL register a session with the registry when its Caducean session is
  initialized.
- AC2: THE SYSTEM SHALL call `update_session_state` with the live `(ξ, u)` immediately before
  `apply_coupling`, at the existing DER update site where both values are already in scope
  ([agent_kernel.py:7327-7350](backend/agent/agent_kernel.py:7327)).
- AC3: THE SYSTEM SHALL unregister a session when its conversation ends, so the registry does
  not accumulate phantom partners that dilute coupling.
- AC4: THE SYSTEM SHALL guard the wiring behind a feature flag defaulting to **disabled**, so
  activating multi-session coupling is a deliberate act and the DER path's behavior is unchanged
  until then.
- AC5: THE SYSTEM SHALL keep coupling off the critical path: any failure logs at debug and
  never propagates into step execution.
- AC6: THE SYSTEM SHALL bound per-update coupling cost: `apply_coupling` is O(partners), so the
  registry SHALL cap active partners at `MAX_COUPLED_SESSIONS` (default 8).

**Edge Cases:**
- Single active session → `apply_coupling` early-returns 0; no FFI writes, no cost.
- Session registered but never updated → `last_xi`/`last_u` remain 0.0; AC2's ordering makes
  this reachable only for a session that never executed a step. Document that coupling skips
  never-updated partners rather than coupling against zeros.
- Flag off → registry stays empty and inert (AC4).

---

### REQ-11: Distinct winding numbers per kernel domain

**User Story:** As the resonance machinery I want more than one `c_eff` in the system so that
the rational/irrational discrimination I was validated on has a non-degenerate input.

**Verified:** REAL DEGENERACY — the only production call is `ffi_caducean_init_session(_session)`
at [agent_kernel.py:5204](backend/agent/agent_kernel.py:5204), which takes the signature
defaults `l=1, m=1` ([iris_ffi.py:1189](backend/gateway/iris_ffi.py:1189)). No other call site
exists. So `c_eff = (1/√2)·√2 = 1.0` for every session, every ratio is trivially 1:1, and
`_is_rational_ratio` always returns `True`. The 98-trial D-series validation across
`c_eff` 1.000–3.000 (overview §4) and the C1 irrational-interference finding (overview §10) are
both unreachable at runtime. `coupled_registry.py`'s own docstring prescribes distinct windings
(`voice l=2, m=2` vs `coding l=1, m=1`); it never happens.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL assign winding numbers by kernel domain, with at least two distinct
  `c_eff` values present when both a voice and a coding/DER session are active.
- AC2: THE SYSTEM SHALL define the domain→winding mapping in one place, with the rationale for
  each pair recorded alongside it.
- AC3: THE SYSTEM SHALL pass the assigned winding numbers to **both**
  `ffi_caducean_init_session` and `registry.register_session`, so the engine and the registry
  agree on `c_eff`.
- AC4: THE SYSTEM SHALL keep `(1, 1)` as the default for any unclassified session, preserving
  today's behavior where no domain is known.
- AC5: THE SYSTEM SHALL verify by test that at least two distinct `c_eff` values arise from the
  mapping and that `_is_rational_ratio` returns `False` for at least one configured pair — so
  the irrational branch is reachable.

**Edge Cases:**
- Re-initializing an existing session with different windings → `register_session` is idempotent
  and updates `l, m, c_eff` ([coupled_registry.py:105-108](backend/agent/coupled_registry.py:105));
  the engine side must tolerate the same.
- A domain whose winding produces a very high `c_eff` → `Twrap` shrinks proportionally
  (overview §4). Keep windings small (≤3) so wrap times stay in the validated range.

---

### REQ-12: TTS chunk size from `|u|` bands, not force magnitude

**User Story:** As a listener I want speech pacing to reflect how resolved the agent actually
is, so that a confident answer flows and an uncertain one stays easy to interrupt.

**Verified:** REAL DESIGN DEFECT — `get_tts_chunk_size` scales by `sig.force_magnitude`
([conversation_kernel.py:155](backend/agent/conversation_kernel.py:155)). The Duffing force is
`F(u) = 2u − 2u³` (overview §2), which is **zero at both `u = 0` and `u = ±1`**. Force magnitude
therefore cannot distinguish "calm because converged" from "calm because completely
unresolved" — the two states that should produce opposite speech pacing map to the same chunk
size. The DER side already solved this with explicit `|u|` bands (`U_SPLIT = 0.5`,
`U_CONVERGED = 0.85` at [der_constants.py:129-142](backend/agent/der_constants.py:129)); the
voice side never adopted them.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL derive chunk size from the `|u|` band using the same thresholds
  `U_SPLIT` / `U_CONVERGED` that govern the DER split decision, so one physics reading drives
  both.
- AC2: WHEN `|u| >= U_CONVERGED` THEN THE SYSTEM SHALL select a long chunk (fluent, confident
  delivery).
- AC3: WHEN `|u| < U_SPLIT` THEN THE SYSTEM SHALL select a short chunk (unresolved — keep
  speech easy to interrupt).
- AC4: WHERE `|u|` is mid-band THEN THE SYSTEM SHALL select an intermediate chunk.
- AC5: THE SYSTEM SHALL keep the existing `[TTS_CHUNK_MIN, TTS_CHUNK_MAX]` bounds and the
  existing return type, so the consuming code at
  [iris_gateway.py:2989-2992](backend/iris_gateway.py:2989) and the consolidation test
  `test_speak_response_uses_kernel_chunk_size` remain valid unmodified.
- AC6: IF the direction signal is unavailable THEN THE SYSTEM SHALL return the existing
  midpoint default (`TTS_CHUNK_MAX // 2`), unchanged.

**Edge Cases:**
- `u` exactly at a band boundary → band membership SHALL match the DER convention exactly
  (`< U_SPLIT`, `< U_CONVERGED`, else converged) so the two consumers never disagree.
- First turn of a session, `u = 0` → falls in the short-chunk band, which is the desired
  behavior for an agent that has not yet resolved anything.

---

### REQ-13: The learned controller is reachable outside AutoResearch

**User Story:** As the trajectory learner I want to be fitted for ordinary sessions so that I am
not permanently in bootstrap for every user who never invokes self-improvement.

**Verified:** PARTIAL WIRING — `tune_dffing_params` does fire from the DER update path
([agent_kernel.py:7367](backend/agent/agent_kernel.py:7367)), but `fit()` and `should_fire()`
are called only from `AutoResearchRunner`
([auto_research.py:310, 323](backend/agent/auto_research.py:310)), which is reachable only via
the `improve_self` tool ([tool_bridge.py:1618-1622](backend/agent/tool_bridge.py:1618)) and is
never started at boot (verified: no `runner.start()` in `main.py` or `iris_gateway.py`). The
controller has its own refit-milestone logic already (`_REFIT_MILESTONES = (100, 500, 1000)` at
[trajectory_controller.py:27](backend/agent/trajectory_controller.py:27)) that nothing exercises
in a normal session.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL invoke the controller's refit check on the existing DER update cadence,
  reusing its built-in `_needs_refit()` milestone logic rather than adding a new schedule.
- AC2: THE SYSTEM SHALL keep fitting off the hot path: `fit()` reads all trajectory rows and
  runs a least-squares solve, so it SHALL run at most once per milestone crossing and SHALL NOT
  execute on every step.
- AC3: IF fitting fails or numpy is unavailable THEN THE SYSTEM SHALL continue with the
  bootstrap EML-threshold rule already implemented at
  [trajectory_controller.py:170-172](backend/agent/trajectory_controller.py:170).
- AC4: THE SYSTEM SHALL log each fit with the row count so fit frequency is measurable.
- AC5: THE SYSTEM SHALL NOT change `should_fire`'s signature or return shape, so
  `test_trajectory_controller.py` passes unmodified.

**Edge Cases:**
- Fewer than 100 trajectory rows → `_needs_refit()` returns `False`
  ([trajectory_controller.py:98-99](backend/agent/trajectory_controller.py:98)); bootstrap rule
  applies. No change.
- Trajectory table reset mid-session → the existing `count < _last_fit_count` branch triggers a
  refit. Already handled; verify it still is.

---

### REQ-14: The scheduler's isolation from reasoning state is preserved

**User Story:** As the author of the phase-scheduler spec I want its contract locks to survive
this spec so that unifying the math does not quietly couple scheduling to reasoning state.

**Verified:** CONTRACT — `specs/caducean-phase-scheduler/` design decision D-2 and contract
tests CT-3/CT-4 forbid the scheduler from reading `ξ`, `u`, or calling the Caducean FFI. This
spec introduces a module both layers import, which is exactly where such a lock erodes.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL keep the shared trig module free of any import of the Caducean gateway,
  the coupled registry, or the phase manager (REQ-7 AC2), enforced by test.
- AC2: THE SYSTEM SHALL leave contract tests CT-3 and CT-4 passing unmodified.
- AC3: THE SYSTEM SHALL NOT introduce any path by which the phase manager reads `ξ` or `u`,
  directly or through the shared module.
- AC4: A contract test SHALL assert that the shared module's public functions accept and return
  only plain floats and sequences of floats — no domain objects that could smuggle state across
  the boundary.

**Edge Cases:**
- A future consumer wanting both scheduling and reasoning coupling → must hold two separate
  state objects and call two kernels; the module SHALL NOT offer a combined convenience wrapper
  that would blur the boundary.

---

### REQ-15: Observability for parameter drift and coupling events

**User Story:** As the person tuning relaxation rates and coupling strengths I want the drift
and the coupling decisions logged so that the next iteration is grounded in measurement.

**Verified:** NEW (unverified — implementation pending). Needed because REQ-1's recovery time,
REQ-8's coupling strength, and REQ-11's winding choices are all empirical. Today
`tune_dffing_params` logs its own adjustment
([trajectory_controller.py:260-270](backend/agent/trajectory_controller.py:260)) but nothing
tracks cumulative drift, so the ratchet was invisible in the logs that exist.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log every parameter change with session id, old and new
  `(a, b, s)`, the writer that caused it, and the current distance from baseline.
- AC2: THE SYSTEM SHALL expose a per-session snapshot of `(a, b, s)`, the baseline, cumulative
  perturbation count by writer, and cumulative relaxation count.
- AC3: THE SYSTEM SHALL log every coupling event with both session ids, both `c_eff` values,
  the rational/irrational verdict, the wrap-aware phase difference, the assigned role, and the
  applied delta.
- AC4: THE SYSTEM SHALL keep drift logging at DEBUG for individual relaxation steps and at INFO
  for perturbations and role assignments, so the common case stays cheap.
- AC5: THE SYSTEM SHALL include a session or conversation identifier in every line, per the
  `CLAUDE.md` structured-logging requirement.
- AC6: THE SYSTEM SHALL record enough to verify the REQ-1 success criterion (parameters within
  ±0.15 of baseline after a perturbation-heavy session) without additional instrumentation.

**Edge Cases:**
- High-frequency relaxation → AC4's DEBUG default keeps cost low; the snapshot is pull-based.
- Session id unavailable → fall back to `"unknown"`; never raise from the logging path.

---

---

### REQ-16: Per-session cached EML on the DER retrieval hot path

**User Story:** As the DER step loop I want the cognitive-state read that gates memory retrieval to
come from a per-session cache rather than a live FFI call, so that I am not paying an FFI
round-trip per step for a value that cannot have changed.

**Verified:** REAL GAP, with a **latent cross-session bug in the intended fix**.
[`agent_kernel.py:5498`](backend/agent/agent_kernel.py:5498) calls
`ffi_calculate_eml(_session)` **inside the DER step loop**, once per step, purely to pick a
retrieval limit and min-score. A cache exists for exactly this purpose —
`CaduceanTrajectoryRecorder.get_cached_eml()` at
[`caducean_trajectory.py:266-269`](backend/agent/caducean_trajectory.py:266) — and is currently
used only by AutoResearch ([`auto_research.py:343`](backend/agent/auto_research.py:343)).

⚠️ **The cache cannot be used as-is.** `_eml_cache` is a **class attribute**
([`caducean_trajectory.py:107`](backend/agent/caducean_trajectory.py:107)) written unconditionally
by `record()` ([`caducean_trajectory.py:195`](backend/agent/caducean_trajectory.py:195)):
`CaduceanTrajectoryRecorder._eml_cache = float(eml_after)`. In a multi-session process, session A's
step overwrites the value session B would read. Swapping the FFI call for `get_cached_eml()`
without fixing this would trade an FFI cost for a correctness bug — retrieval breadth driven by
another conversation's cognitive state. The cache must be made per-session first.

**Staleness is bounded at exactly one step and that is semantically correct.** The cache is written
in `record()` during `_der_finalize_step` (after a step completes); the retrieval read happens at
the *start* of a step. So a read always sees the previous step's EML — which is the right value for
"what is my cognitive state entering this step," and is arguably more coherent than a mid-step live
read. EML is a function of the `(x, y)` accumulators, so it **cannot change while no step runs**;
wall-clock staleness is therefore irrelevant (contrast REQ-1 AC2b, where wall-clock *did* matter).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL key the EML cache by session id, so one session's recorded EML can never be
  read by another.
- AC2: THE SYSTEM SHALL read the cached EML — not a live FFI call — on the DER mid-loop retrieval
  path.
- AC3: WHEN no EML has been cached for a session yet (first step) THEN THE SYSTEM SHALL fall back to
  a single live FFI call, and SHALL NOT use another session's value or a bare default that
  misrepresents state.
- AC4: THE SYSTEM SHALL bound cache memory by session count, evicting by last-write age, so a
  long-lived process cannot grow the cache without limit.
- AC5: THE SYSTEM SHALL keep `get_cached_eml()` working for its existing caller
  (`auto_research.py:343`) — either by preserving a no-argument form with documented
  process-wide-latest semantics, or by updating that call site in the same change. It SHALL NOT be
  left silently reading a now-per-session structure through a stale signature.
- AC6: THE SYSTEM SHALL cache the full `(eml, x, y)` triple, not `eml` alone, because the retrieval
  decision consumes all three ([`agent_kernel.py:5498-5504`](backend/agent/agent_kernel.py:5498)).

**Edge Cases:**
- Session's very first step → AC3's single live call; subsequent steps hit the cache.
- Engine unavailable → existing `try/except` around the block
  ([`agent_kernel.py:5505-5506`](backend/agent/agent_kernel.py:5505)) keeps the default limit/score.
  Unchanged.
- Session evicted from the cache mid-run (AC4) → treated as "no value cached", so AC3's live call
  reinstates it. Never reads a neighbour's value.
- Concurrent write from two sessions → per-session keying (AC1) plus a lock makes this a non-event;
  today it is a silent overwrite.

---

### REQ-17: Continuous EML modulation of retrieval breadth

**User Story:** As the retrieval layer I want breadth to vary smoothly with cognitive state so that
a small change in EML does not produce a cliff in how much memory I search.

**Verified:** REAL DESIGN DEFECT (same class as REQ-8 and REQ-12) —
[`agent_kernel.py:5493-5504`](backend/agent/agent_kernel.py:5493) is a three-branch `if/elif` over
hardcoded pairs:

| Condition | limit | min_score | Meaning |
|---|---|---|---|
| default | 2 | 0.55 | neutral — minimal work |
| `eml >= 1.50 and ex >= 0.60` | 5 | 0.40 | explore — many loose matches |
| `eml < 1.00 and ey >= 0.70` | 3 | 0.65 | consolidate — few strict matches |

⚠️ **`limit` is not monotonic across these anchors** (5 → 2 → 3, V-shaped) while `min_score` is
(0.40 → 0.55 → 0.65). A naive linear interpolation between "explore" and "consolidate" would
silently break the neutral case, which is deliberately the *cheapest*. Any implementer who
"simplifies" this to one lerp introduces a regression that no existing test would catch.

The same magic numbers (1.5 / 1.0) are independently hardcoded a second time as the
`EXPLORE / BALANCE / VERIFY` phase label at
[`agent_kernel.py:5310-5311`](backend/agent/agent_kernel.py:5310) — two consumers, two copies, free
to drift.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL compute a single scalar *explore pressure* `p ∈ [-1, +1]` from
  `(eml, x, y)`, where `+1` is fully explore-dominant, `-1` fully consolidate-dominant, and `0`
  neutral.
- AC2: THE SYSTEM SHALL derive `limit` and `min_score` as **piecewise-linear interpolations through
  the three existing anchor points**, so `limit` retains its V-shape and `min_score` its monotone
  shape.
- AC3: THE SYSTEM SHALL reproduce today's exact `(limit, min_score)` pairs at the three anchor
  conditions, within rounding tolerance for the integer `limit`. This makes the change a
  refinement rather than a retuning, and makes non-regression testable.
- AC4: THE SYSTEM SHALL round `limit` to an integer of at least 1, so retrieval is never requested
  with a zero or negative limit.
- AC5: THE SYSTEM SHALL define the EML band constants (the `1.50` / `1.00` thresholds and the three
  anchor pairs) in **one** place, consumed by both the retrieval path and the cognitive-state phase
  label at [`agent_kernel.py:5310-5311`](backend/agent/agent_kernel.py:5310).
- AC6: THE SYSTEM SHALL clamp `min_score` to `[0.30, 0.80]` and `limit` to `[1, 8]`, so a
  degenerate EML value cannot request an unbounded or empty retrieval.
- AC7: THE SYSTEM SHALL NOT change `episodic.retrieve_similar`'s signature
  ([`episodic.py:401-407`](backend/memory/episodic.py:401)) — only the arguments passed to it.

**Edge Cases:**
- `eml` exactly at an anchor threshold → AC3's anchor reproduction defines the value; no ambiguity.
- Degenerate `x == y == 0` → `p = 0` (neutral), giving today's default pair.
- `eml` far above any observed range (e.g. 5.0) → clamped by AC6 rather than extrapolated.
- A future third consumer of the bands → AC5's single definition means it reads, not re-copies.

## Non-Requirements (Out of Scope)

- **Rewriting the Caducean C++ engine or the FFI surface.** All work is Python-side; the FFI
  contract is unchanged.
- **Migrating existing Immortus chain rows** to the canonical coordinate format (REQ-5) or the
  canonical chain identity (REQ-6). Old rows are historical; parsers tolerate them.
- **Changing the EML formula, the Duffing force, or the safe parameter ranges.** The physics is
  validated; only its plumbing is being repaired.
- **Enabling multi-session coupling by default.** REQ-10 AC4 ships it flag-off. Turning it on is
  a separate decision informed by REQ-15's data.
- **Building the StreamKernel as a separate component** (overview §11). REQ-12 puts adaptive
  chunking where it already lives, in the ConversationKernel.
- **Cross-kernel shared Σ state** (overview §11, "one engine governing multiple simultaneous
  domains"). Directly contradicts Decision Locked #1 and REQ-14; explicitly rejected.
- **Modifying any existing test.** Verified compatible above; if a change requires a test edit,
  the change is wrong.
- **The phase scheduler itself.** That is `specs/caducean-phase-scheduler/`. This spec only
  preserves its contract locks (REQ-14) and factors out the shared math (REQ-7).

## Open Questions

- **Q1 — Relaxation rate.** `RELAX_STEP = 0.10` per 10 updates gives ~250-update recovery from
  a pinned floor. Too slow to matter in a 40-cycle DER run; appropriate for a long voice
  session. Non-blocking: REQ-15 AC6 data settles whether a faster rate is safe.
- **Q2 — Which identifier is canonical for REQ-4/REQ-6?** The session id is what the trajectory
  recorder writes; the conversation id is what the document query filters on. Both defensible.
  Recommendation is to resolve conversation → session through the active-kernel registry
  (`backend/tests/unit/test_active_kernel_registry.py` implies such a mapping exists), and to
  confirm that during implementation rather than guessing now.
- **Q3 — Winding assignment per domain.** The registry docstring suggests voice `(2,2)`, coding
  `(1,1)`. Note `(2,2)` gives `c_eff = 2.0`, a clean 2:1 ratio — *rationally* related, so it
  exercises the attractive branch but never the irrational one. Reaching the irrational branch
  needs something like `(2,1)` vs `(3,3)` (`√5 : √18`, the C1 configuration). Deferred to
  REQ-11 AC5's test, which forces at least one irrational pair to exist.
- **Q4 — Should the barge-in nudge remain a parameter write at all?** It perturbs `s`
  ([conversation_kernel.py:289](backend/agent/conversation_kernel.py:289)) to influence `u`
  indirectly, with a comment admitting it is "a tiny nudge" and that the real interrupt path is
  elsewhere. A direct `u` injection would need a new FFI export (deferred to v3 per
  [coupled_registry.py:166-169](backend/agent/coupled_registry.py:166)). Left as-is; REQ-1 now
  makes its ratcheting harmless.

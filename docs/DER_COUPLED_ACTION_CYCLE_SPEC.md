# DER — Coupled Action Cycle: Implementation Spec (Kiro-style)

**Status:** DRAFT v2.0 — full depth, ready for implementation.
**Supersedes:** `docs/DER_EXECUTION_LAYER_DELIBERATION.md` (kept as "what we pivot from"),
`docs/DER_COUPLED_ACTION_CYCLE_SPEC.md` v1.0 (surface-level; replaced).
**Foundational refs:** `docs/DER_LOOP_MYCELIUM.md`, `docs/handoffs/morphohdl-irisvoice-handoff.md`.
**Rollout:** Direct replace (no flag). Commit at every phase gate. Live-validated via
WS-driven task battery (`scripts/validate_der_*.py`).
**Method:** Kiro SDD — Requirements (EARS) → Design (per-phase) → Tasks (traceable).
Phase gates are HARD: Phase N+1 cannot begin until Phase N passes ALL hard requirements.

---

# SYSTEM INVARIANT (binds all phases — read first)

The DER loop, Sub-Loops, context-window pruning/compaction, and the outer self-tuning loop
are **NOT separate mechanisms**. They are ONE recursive operation — *fan-out / fold-back* —
observed at four scales, governed by the same Caducean `u`/`ξ` physics:

| Scale | Operation | Governing constant | Existing code |
|---|---|---|---|
| Step | fan into tool calls | `u`/`ξ` (growth-width) | `agent_kernel.py` D2.1 |
| Sub-Loop | fold children into parent as COMPRESS | `u`/`ξ` | handoff §1 |
| Context window | DCP prune (light) / MCM compress (heavy) | `W0`/token budget | `dcp.py`, `mcm_check_compress.py` |
| Session / Outer loop | fold trajectories, tune constants | `U_SPLIT`, `avg_step_cost` | Phase 4 |

**The invariant:** *fanning-out and folding-back are dual operations at every scale. The
same `u`/`ξ` that decides whether a step splits also decides whether a context compaction
may fold, and the same resource (`W0` = token budget / avg_step_cost) bounds both the DER
work-unit counter and the context window.* When the agent prunes its window, it is doing a
Sub-Loop collapse on its own memory; when it compacts, it takes a snapshot of the fan. No
layer may drift from the others — they share one resource and one physics.

**Consequence for every phase:**
- Phase 0 makes the fold *honest* (no fake success, no silent drop — including DCP dropping
  tool calls without a trace).
- Phase 1 makes the fan *informed* (evidence block).
- Phase 2 makes fan/fold *physics-driven* (`u`/`ξ`), with `U_SPLIT` as the compression
  threshold (low `|u|` ⇒ keep fan unfolded; high `|u|` ⇒ collapse).
- Phase 3 makes the fold *auditable* (invariants G1–G5).
- Phase 4 tunes the *threshold* at which fanning becomes folding — and fires when memory is
  about to fold (the same signal as context compaction), not on an arbitrary cadence.

---

# DESIGN DECISIONS (open questions resolved)

- **D-1 `W0` tied to token budget:** `W0 = resolve_context_window() / avg_step_cost`
  (`avg_step_cost` a learned constant, Phase 4-tunable). The work-unit counter and the
  context window are the SAME resource at two layers; they cannot drift. When the agent
  burns context, `work_units` and `token_budget_remaining` decrease together.
- **D-2 `U_SPLIT` = compression threshold:** start 0.5. Low `|u|` ⇒ fan stays unfolded in
  memory (still exploring); high `|u|` ⇒ collapse aggressively. Governs both split AND
  compaction permission.
- **D-3 Phase 4 first cut tunes `U_SPLIT` + `avg_step_cost` FIRST** (the fan/fold dials),
  then `interpreter.py` cutoffs (0.05/1.0) later. Inverts handoff §9.4 order.
- **D-4 Outer loop triggers on the compaction signal:** fire when the agent is about to
  compact its window (context approaching limit via `mcm_check_compress`) OR at
  `record_session_exit`. Not on MCM 70% cadence — that is a proxy for "memory full"; we have
  the actual fold event, so observe at the moment of truth.
- **D-5 Fan-trace preservation (new, from user):** DCP pruning and MCM compress MUST leave a
  structural trace of the tool-call fan (tool_sequence + `u`/`ξ` + outcome) so the agent
  "still sees the fanning" after compaction. This is Phase 0 work (honest bookkeeping), not
  a later add-on. See D0.8–D0.10.

---

# ENFORCEMENT vs EMPOWERMENT (algorithm taxonomy — read before implementing)

User principle: **enforce the math and the budget; empower the agent on choice and
verification; never inject standing context (nudges/context-injection are token bloat and
noise in practice).** Every mechanism below is classified into THREE tiers. Implementation
MUST respect the classification — do not "helpfully" promote a subjective mechanism to hard
enforcement, and do not inject a record into the prompt as a standing nudge.

**Critical distinction:** the enforced tiers are NOT all "binary correctness." Tier-1 is
binary bookkeeping (prevent lies). Tier-2 is **PHYSICS-BASED enforcement** — dynamical-system
rules (Lyapunov potential, Duffing governor, `U_SPLIT`) that guarantee *convergence to a
well*, not per-step correctness. These are hard-enforced AS dynamical rules, but their
*values* are continuous and learned. Do not mistake Tier-2 for binary if/else.

### TIER 1 — BINARY BOOKKEEPING (hard-enforced, no physics, prevent lies)
- D0.1 stub-kill (`_verify_step_result` regex+length) — **algorithm: pattern match**
- D0.2 veto emits no edge (code-path removal) — **algorithm: none, just don't call**
- D0.3 escalation remaining (arithmetic) — **algorithm: subtraction**
- D0.5 episodic EWMA (`0.7*old+0.3*new`) — **algorithm: fixed update rule**
- D0.6 outcome coarsening (`verified_fraction` from `expected_output` assertions) —
  **algorithm: substring-ratio, no LLM**
- D0.8 fan-trace WRITE (on DCP drop) — **algorithm: hash+insert** (a STORE write, NOT a
  prompt injection — adds zero standing token cost)
- D0.9 recovery preamble FAN SUMMARY (embedded at fold time) — **algorithm: string build
  from store** (fires only on compaction, not per-step)
- D0.10 shared resource (`resolve_context_window` / `W0`) — **algorithm: division**
- Phase 4 public/private split (survival on `r_new` only) — **algorithm: comparison**
- Phase 4 single-variable proposal (reject multi) — **algorithm: arity check**

### TIER 2 — PHYSICS-BASED ENFORCEMENT (hard-enforced AS dynamical rule, values learned)
These are NOT binary. They are stability/phase-plane rules from the Caducean Duffing
governor. The RULE is enforced; the THRESHOLD is tuned by Phase 4.
- **Appendix B termination** — **algorithm: Lyapunov potential Φ** (work-unit counter where
  split prepays `width`). Φ decreases monotonically ⇒ trajectory converges to a well. This is
  a *stability guarantee*, not a per-step pass/fail. Enforced by the integer arithmetic +
  refusal rule, but the guarantee is dynamical.
- **D2.1 growth-width / `U_SPLIT`** — **algorithm: Duffing phase-plane decision**. Split when
  `|u| < U_SPLIT` (oscillating ⇒ fan out); atomic when converged. `|u|` is a CONTINUOUS state,
  not a boolean. The agent splits because it is *oscillating*, not because it failed a check.
- **D-2 `U_SPLIT` as compression threshold** — folding permitted when `|u|` high (converged);
  fan kept unfolded when `|u|` low. Physics condition, not a rule.
- **D2.3 adaptive verify strictness** — gated by `|u|` BAND: deterministic-only when converged
  (`|u|≥0.85`), +LLM rubric when mid-oscillation. Physics-gated, not binary.

### TIER 3 — SUBJECTIVE / EMPOWERED (agent decides; MUST NOT be hard-enforced or token-bloated)
- D1.2 tool resolution: LLM *proposes*, validator *backstops*. Agent empowered.
- D1.1 evidence block: **CONDITIONAL + STRUCTURED only** (see rewrite below). Injected ONLY
  when the resolver is uncertain (low `|u|` OR top-1 pheromone confidence < threshold). When
  converged/confident, inject NOTHING. Structured key-value, never prose. This is the
  explicit guard against the "nudge = noise" anti-pattern.
- D2.3 rubric verdict: the LLM rubric returns a VERDICT (met/not-met), not advice. A CHECK,
  not a nudge.

### ANTI-PATTERNS EXPLICITLY FORBIDDEN
- Standing context injection every step (token bloat + noise). Evidence block is conditional.
- "Nudges" / soft suggestions in the prompt. The agent is empowered by data + tools, not
  coached by text.
- Writing fan_traces INTO the prompt. They go to the store; recalled only by the conditional
  evidence block (D1.1) when uncertain.
- Treating Tier-2 physics rules as binary if/else (e.g. "if `|u|<0.5` then split" with no
  potential-function backing). The guarantee comes from Φ, not the threshold.

---

# PART 1 — REQUIREMENTS (EARS format)

> EARS = Easy Approach to Requirements Syntax. Each requirement is testable and maps to
> a design section and a task. `WHEN <trigger> THE SYSTEM SHALL <response>`.

## R0 — Signal Integrity (Phase 0)
- **R0.1** WHEN a step's raw result matches the stub pattern (`/\[step \d+ completed\]/`
  with no tool output) THE SYSTEM SHALL label the step `FAILED` and SHALL NOT mark it
  complete.
- **R0.2** WHEN an action is vetoed by the Reviewer membrane and never executed THE
  SYSTEM SHALL emit NO tool-outcome record for it.
- **R0.3** WHEN `check_escalation` is called THE SYSTEM SHALL receive the true
  `token_budget_remaining = mode_budget - tokens_used` (not tokens consumed).
- **R0.4** WHEN a `QueueItem` is created THE SYSTEM SHALL carry an `expected_output`
  field, and `TrailingDirector.analyze_gaps` SHALL read it and return ≥1 gap item when a
  gap is detected.
- **R0.5** WHEN an episode is stored that is ≥0.95 cosine-similar to an existing episode
  THE SYSTEM SHALL update `outcome_score` via EWMA (`0.7*old + 0.3*new`) and SHALL update
  `outcome_type` to the latest value (so failure can ratchet down).
- **R0.6** WHEN a step result is classified THE SYSTEM SHALL coarsen outcome into
  `hit | partial | miss` from verified fraction, not a binary `[STEP ERROR` substring.
- **R0.7** WHEN a failure is recorded THE SYSTEM SHALL use the canonical zone `der_failure`
  (no off-vocab `failure` zone).
- **R0.8** WHEN DCP prunes/dedups a tool-call message (dcp.py Pass 2/3) THE SYSTEM SHALL
  write a `fan_trace` observation (tool, args-hash, outcome, `u`/`ξ` at call time, parent
  step_id) to the trajectory store, so the fan is preserved, not destroyed (System Invariant:
  folding must not lose the fan).
- **R0.9** WHEN `MCM.compress` fires and `inject_recovery` replaces the context (mcm.py:207)
  THE SYSTEM SHALL embed the `fan_trace` structural summary in the recovery preamble, so the
  post-compaction agent still sees the shape of its tool-call tree.
- **R0.10** THE SYSTEM SHALL couple DCP `turn_protection`, MCM compress `budget_pct`, and the
  DER `work_units` counter to ONE resource: `resolve_context_window()` (agent_kernel.py:892)
  and `W0 = resolve_context_window() / avg_step_cost` (D-1). No layer may use an independent
  budget.

## R1 — Memory-Coupled Acting Prompt (Phase 1)
- **R1.1** WHEN a step is about to execute THE SYSTEM SHALL assemble an evidence block
  (≤300 tokens) fusing: tier2 predicted next tools, proven tool_sequences, tier3 AVOID
  failures, active contracts, and live working memory, and SHALL inject it into the
  acting prompt.
- **R1.2** WHEN a step needs a tool THE SYSTEM SHALL resolve it at execution time via a
  SINGLE resolver that reads the live `tool_registry` + evidence, and the LLM planner
  SHALL NOT pre-assign `tool`/`params` to steps.
- **R1.3** WHEN the LLM resolver emits an unparseable/invalid proposal THE SYSTEM SHALL
  fall back to the pheromone top-1 predicted tool (never a stub).
- **R1.4** WHEN a web-intent goal is given THE SYSTEM SHALL still route to `crawler_query`
  via registry + evidence (the regex override SHALL be deleted).
- **R1.5** THE SYSTEM SHALL maintain stub rate = 0 under the new path (R0.1 preserved).

## R2 — Emergent Shape (Phase 2, the "athlete")
- **R2.0** THE SYSTEM SHALL make the split/execute decision a STATEFUL function of live
  Caducean `u`/`ξ` (NOT a stateless predicate) — per the MorphoHDL-break constraint
  (handoff §5 "Breaks"): the engine is explicitly stateful; flattening it to stateless would
  destroy the physics governance value.
- **R2.1** WHEN a goal's Caducean `|u| < U_SPLIT` (unresolved/oscillating in phase plane) OR
  a step verification FAILED THE SYSTEM SHALL split the step into ≤3 child `QueueItem`s via
  ONE operator (recovery graft + growth-width unified), and children SHALL execute as
  Sub-Loops that collapse back to the parent as one COMPRESS observation (handoff §1).
- **R2.2** WHEN `|u|` is high (near attractor) THE SYSTEM SHALL use deterministic
  verification only; WHEN mid-oscillation THE SYSTEM SHALL additionally apply an LLM rubric.
- **R2.3** THE SYSTEM SHALL demote `ExecutionMode` to a budget envelope; changing mode
  SHALL NOT alter step decomposition for the same goal. Per-step fan-out is owned by the
  growth-width operator; whole-route activation (Immortus `drift`/`route_score`) is kept
  separate (handoff §6 open Q6).
- **R2.4** THE SYSTEM SHALL guarantee termination via the unified work-unit potential
  Φ = `work_units` + (MAX_DEPTH − depth) + token_budget_remaining, where split PREPAYS
  `width` work units (so Φ strictly decreases by 1 on every split, by 2 on complete/veto,
  by 1 on token burn — proven in Appendix B). Loop exits within `DER_WORK_UNITS_0=12`,
  `MAX_DEPTH=3`, `DER_MAX_GRAFTS=3`, `max_cycles=40`, veto cap=2. Split is refused when
  `work_units < width` or `depth == MAX_DEPTH`.

## R3 — Verification Rigor + Invariants (Phase 3)
- **R3.1** THE SYSTEM SHALL enforce G1–G5 as a permanent deterministic test suite run on
  every DER change.
- **R3.2** WHEN a step is synthesis/reasoning (no deterministic check applicable) and
  deterministic checks pass THE SYSTEM SHALL apply the LLM verification rubric (≤150
  tokens, temp 0).
- **R3.3** THE SYSTEM SHALL crystallize landmarks ONLY from VERIFIED outcomes, and every
  landmark SHALL trace to trajectory IDs (G4).
- **R3.4** THE SYSTEM SHALL write a `(state, action, verified_label)` triple on every
  COMMIT (G5) — the data the outer loop needs.

## R4 — Outer Self-Tuning Loop (Phase 4, the "coach": AIDE² over Caducean constants)
- **R4.0** THE SYSTEM SHALL implement the outer loop as a SEPARATE, slower process that
  reads completed `caducean_trajectories` and proposes changes to governing constants; it
  SHALL NOT run tasks itself (it watches tape). This is Level-1 constant auto-tuning, not
  recursive self-improvement. THE SYSTEM SHALL trigger it on the context-compaction signal
  (pre-compress hook + `record_session_exit`), NOT on an arbitrary MCM cadence (D-4).
- **R4.1** WHEN the outer loop proposes a constant change THE SYSTEM SHALL propose exactly
  ONE variable (single-variable only; multi-variable rejected) — legibility constraint.
- **R4.2** THE SYSTEM SHALL evaluate the proposal on a HELD-OUT session batch (disjoint from
  the inspiring batch) using a PUBLIC/PRIVATE split: the inner loop sees only the public
  pheromone/confidence score; survival is decided ONLY on the private held-out metric =
  natural exit rate (primary), `TOPO_VIOLATION` rate, tokens per verified step.
- **R4.3** THE SYSTEM SHALL adopt the new value ONLY if it beats the incumbent on the
  private held-out metric, and SHALL log both accepted and rejected proposals in an NBL
  ledger (before/after + held-out result).
- **R4.4** THE SYSTEM SHALL exclude `drift`/`route_score`/any step-success-derived signal
  from the held-out metric (Immortus caution, handoff §9.4) — these are gameable.
- **R4.5** THE SYSTEM SHALL cap evaluation cost (fixed replay sessions/compute) and SHALL
  require the held-out batch to span ≥2 `domain` coordinate values (task heterogeneity).
- **R4.6** THE SYSTEM SHALL NOT extend to rewriting growth-width logic until step-tuning is
  stable, and SHALL pass G1–G5 under any tuned constant set (no regression).

---

# PART 2 — DESIGN (per phase, with exact signatures + data contracts)

## Cross-cutting architecture (the loop we are building)

```
DIRECT   → sense goal + working memory
SENSE     → retrieve tier2/tier3/proven/contracts + (u,ξ)
PERCEIVE  → fuse into ≤300-tok evidence block  [NEW — fixes F1]
PROPOSE   → single resolver: LLM proposes, validator backstops  [fixes F6]
MEMBRANE  → Reviewer approve/veto (no tool outcome on veto)  [fixes F4]
ACT+VERIFY→ execute via tool_bridge; verify (deterministic + rubric)  [fixes F4]
COMMIT    → store (state,action,verified_label); episodic EWMA  [fixes F5]
SPLIT?    → if |u|<U_SPLIT or FAILED → split (≤3)  [Phase 2]
```

**Coach/athlete framing (from MorphoHDL handoff):** the DER loop + growth-width rule
(Phases 1–2) is the *athlete* — governed live by `u`/`ξ`. The Phase 4 outer loop is the
*coach* — a separate, slower process that tunes the athlete's constants from tape. They are
deliberately decoupled; the coach never runs tasks.

**Layer dependencies (verified against code this session):**
- `tool_registry.py` — ALREADY the single source of truth. API used by resolver:
  `get_registry_tools() -> List[Dict]` (LLM-facing, capability-gated),
  `resolve_tool(name) -> Optional[ToolSpec]` (alias-aware),
  `validate_tool_call(name, params) -> (bool, str)`,
  `capability_allowed(spec) -> bool`, `is_parallel_safe(name) -> bool`.
  → **No new registry API needed.** The resolver calls `get_registry_tools()` directly.
- `mycelium/interpreter.py:BehavioralPredictor.predict(session_id, current_node_ids,
  task_class, completed_tools, conn) -> List[str]` (top-3) — tier2 source.
- `mycelium/interpreter.py:ResolutionEncoder.encode_with_resolution(failure, conn)` —
  tier3 AVOID source.
- `mycelium/kyudo.py:TaskClassifier.classify(task_text) -> (task_class, space_subset)` —
  task class for evidence + prediction.
- `agent/caducean_trajectory.py:CaduceanTrajectoryRecorder.record(...)` — trajectory sink.
- `agent/coupled_registry.py:get_coupled_registry()` — multi-session (u,ξ) coupling (Phase 4).
- `gateway/iris_ffi:ffi_caducean_get_state(session_id) -> {x,y,xi,u,a,b,s,...}` — live (u,ξ).

---

## PHASE 0 — Signal Integrity

**Goal:** Make the learning signal honest. No new behavior — correct bookkeeping only.

### D0.1 Stub-kill + verification stage
**New function** in `agent_kernel.py`:
```python
def _verify_step_result(self, goal: str, expected: Optional[str],
                        result: str) -> Literal["VERIFIED","UNVERIFIED","FAILED"]:
    # 1. Stub pattern → FAILED unconditionally
    if re.search(r"\[step \d+ completed\]", result or "") and not result.strip().lstrip("[").startswith("step"):
        # only the bare stub, no real output
        if len(result.strip()) <= 40:
            return "FAILED"
    # 2. Deterministic checks: expected substring/contract present?
    # 3. If synthesis/reasoning and checks pass → caller applies rubric (Phase 3)
    ...
```
**Wire into** `_der_finalize_step` (~line 5975): replace the binary `step_success` with
`verified = _verify_step_result(...)`. `mark_complete` only when `verified in
(VERIFIED, UNVERIFIED)`. Stub → `FAILED` → graft recovery (not success edge).

### D0.2 Veto signal
`agent_kernel.py:5080-5088` — the veto path currently calls
`mycelium_ingest_tool_call(success=False, ...)` for a tool that never ran. **Remove** the
tool-outcome record on veto. Membrane decision is logged separately (audit), not as a
tool outcome.

### D0.3 Escalation inversion
`agent_kernel.py:6298`: change
`token_budget_remaining=_tokens_used` → `token_budget_remaining=_token_budget - _tokens_used`.
Verify `der_loop.py:280` (early-return when remaining<min) and `:322`
(`budget_used = mode_budget - remaining`) now behave correctly.

### D0.4 Revive TrailingDirector
- `der_loop.py:69`: add field `expected_output: Optional[str] = None` to `QueueItem`.
- `_execute_plan_der` (`:4782-4800`) and `_plan_task`: populate `expected_output` from
  planner output (the planner already emits a goal description; we add an explicit
  expected-output line to the planner prompt).
- `trailing_director.py:91`: `analyze_gaps` reads `completed_step.expected_output` — now
  valid. Returns ≥1 gap item when result ≠ expected.

### D0.5 Episodic unlearning
`episodic.py:326-342`: on duplicate (≥0.95 cosine):
```python
outcome_score = 0.7*old_score + 0.3*score
outcome_type  = new_type   # updated, not frozen
```
Remove the `MAX(outcome_score, ?)` ratchet. Keep `full_content` append.

### D0.6 Outcome coarsening + verified_fraction definition (resolves G0.1)
`agent_kernel.py:5297-5300`: replace `[STEP ERROR` substring check with
`verified_fraction` → `hit` (≥0.8) / `partial` (0.3–0.8) / `miss` (<0.3).

**`verified_fraction` is defined concretely (not hand-waved):** it is the fraction of
checkable assertions derived from `item.expected_output` that the result satisfies.
`expected_output` is already a field on the plan-step model (`core_models.py:725`) and is
consumed by `trailing_director.py:36,91`. Derivation:
```python
def _verified_fraction(self, expected: Optional[str], result: str) -> float:
    if not expected:
        return 1.0 if result and not _is_stub(result) else 0.0
    assertions = [a.strip() for a in expected.split(";") if a.strip()]  # "X; Y; Z"
    if not assertions:
        return 1.0 if result else 0.0
    satisfied = sum(1 for a in assertions if a.lower() in result.lower())
    return satisfied / len(assertions)
```
This makes R0.6 deterministic and testable (test: expected="file created; tests pass",
result contains both ⇒ 1.0; contains one ⇒ 0.5 ⇒ partial).

### D0.7 Failure zone + tool-name field
- `agent_kernel.py:5205,5504`: use canonical `der_failure` zone.
- `agent_kernel.py:6052`: `tool_name=getattr(item,"tool","")` (not `tool_name`).

### D0.8 DCP fan-trace pass (resolves R0.8 — System Invariant: folding must not lose the fan)
`dcp.py` currently dedups tool calls by hash and **drops** older results (Pass 2/3) with no
record of the fan. Add **Pass 4**: before dropping a deduped/aged tool message, write a
`fan_trace` observation to `CaduceanTrajectoryRecorder`:
```python
def _emit_fan_trace(self, msg, session_id, parent_step_id, cad):
    # msg = the tool-call message about to be dropped
    self._traj.record_fan_trace(
        session_id=session_id,
        step_id=parent_step_id,
        tool=msg.tool_name,
        args_hash=hashlib.sha256(msg.tool_args.encode()).hexdigest()[:12],
        outcome=msg.tool_outcome,          # success/fail from the message
        u=cad.get("u"), xi=cad.get("xi"),  # live Caducean state at call time
        ts=time.time())
```
This makes pruning *produce* memory instead of destroying it — the agent "still sees the
fanning across several tool calls" after DCP runs. `record_fan_trace` is a new lightweight
method on `CaduceanTrajectoryRecorder` (appends to a `der_fan_traces` table; cheap, WAL-safe).

### D0.9 Recovery preamble includes fan-trace (resolves R0.9)
`mcm.py:207 inject_recovery` does a HARD replace (keeps only system prompt + active task +
recovery preamble). Extend the preamble builder (`_build_recovery_preamble`, mcm.py:239) to
embed a structural fan summary pulled from `der_fan_traces` for the session:
```
FAN SUMMARY: crawler_query→parse→store (3 tools, converged u=0.91); ...
```
So post-compaction the agent sees the *shape* of its tool-call tree, not just a flat summary.
This is the "snapshot of collapsed observation" — generated at fold time.

### D0.10 Couple all layers to one resource (resolves R0.10, D-1)
- `W0 = resolve_context_window() / avg_step_cost` (D-1). `resolve_context_window` already
  trusts live `n_ctx` (agent_kernel.py:892). `avg_step_cost` starts at a constant, tuned by
  Phase 4.
- DCP `turn_protection` (keep last N turns) and MCM compress `budget_pct` (mcm_check_compress.py)
  both derive from `resolve_context_window()` — no independent budget constant.
- DER `work_units` decrements on the SAME token burn that drives DCP/compress. One resource,
  three observers. This is what prevents the layers from drifting (your core concern).

### Phase 0 hard requirements (ALL must pass to gate Phase 1)
G1 (no silent no-op): stub ⇒ FAILED, never `mark_complete` with VERIFIED.
G2 (honest feedback): vetoed action ⇒ zero tool-outcome records.
F3 gone: escalation triggers when budget mostly unused early.
F2 revived: `analyze_gaps` returns ≥1 for injected gap.
F5 fixed: success-then-5×failure ⇒ `outcome_type=failure`, score lowered.
**R0.8:** DCP drop ⇒ `fan_trace` written (asserted: `der_fan_traces` has a row after a
dedup event).
**R0.9:** `inject_recovery` preamble contains FAN SUMMARY (asserted via preamble capture).
**R0.10:** DCP/compress/DER all read `resolve_context_window()`; no independent budget
(asserted: grep confirms no hardcoded turn/budget constant in dcp.py/compress path).
**MODE-AGNOSTIC (your constraint):** D0.8/D0.9/D0.10 are active in DEV mode and PROD mode
identically. DCP already runs unconditionally before every LLM call; the fan-trace Pass 4
rides that always-on path. `inject_recovery` fires on real compaction regardless of mode.
The ONLY mode-dependent aspect is LOG VERBOSITY (dev may log fan-trace writes at DEBUG);
behavior and data written are identical. No feature flag, no `if DEV` guard.

### Phase 0 tests — `backend/tests/test_der_phase0.py`
1. `test_stub_is_failed` — `_verify_step_result("g","e","[step 1 completed]")` ⇒ FAILED.
2. `test_veto_emits_no_edge` — veto path does not call `mycelium_ingest_tool_call`.
3. `test_escalation_remaining_correct` — patch budget=30000, used=500 ⇒
   `check_escalation` sees remaining=29500.
4. `test_trailing_director_fires` — QueueItem(expected_output=...) + mock gap ⇒
   `analyze_gaps` ≥1.
5. `test_episodic_unlearn` — store success then 5× failure ≥0.95 cosine ⇒
   `outcome_type=="failure"`, score decreased.
6. `test_outcome_coarsening` — fraction 0.5 ⇒ `partial`.
7. `test_dcp_fan_trace` — force a DCP dedup event ⇒ `der_fan_traces` gains a row with
   tool/args-hash/outcome/u/xi.
8. `test_recovery_has_fan_summary` — `inject_recovery` preamble contains "FAN SUMMARY".
9. `test_layers_share_resource` — DCP/compress/DER all call `resolve_context_window()`;
   no independent budget constant (grep/monkeypatch assert).

### Phase 0 commit
`git commit -m "DER Phase 0: signal integrity (stub-kill, honest veto/escalation, episodic unlearn, TrailingDirector revive, DCP fan-trace + recovery fan-summary + shared W0/token resource)"`
Record `phase_complete` event + `record_test` for all 9.

---

## PHASE 1 — Couple Memory to Acting Prompt

**Goal:** A step is a *goal + success criterion*. Tool selection = runtime,
memory-conditioned policy with ONE authority. Fixes F1 (route retrieval to prompt) + F6
(one authority).

### D1.1 Evidence block (PERCEIVE)
**New module** `agent/evidence.py`:
```python
def assemble_evidence(goal: str, session_id: str,
                      myc,                       # MyceliumInterface (self._memory_interface._mycelium)
                      completed_tools: List[str],
                      task_class: str) -> str:
    """≤300 tokens, NBL style. Sections:
    PREDICTED NEXT : BehavioralPredictor top-3
    PROVEN PATH    : top pheromone edge tool_sequences for goal
    AVOID          : ResolutionEncoder tier3 failures (space:tool:condition)
    CONTRACTS      : active conduct/style constraints from working memory
    WORKING MEM    : last ≤3 working-memory facts
    (u,xi)         : ffi_caducean_get_state(session_id) summary
    """
    # Integration (verified against existing code this session):
    #   conn          = myc._store._conn            # recall_decoder.py:475
    #   current_node_ids = list(myc._registry.get_active(session_id))  # recall_decoder.py:466
    #   predictor = BehavioralPredictor(myc)        # live_context.py:127
    #   preds = predictor.predict(session_id, current_node_ids, task_class, completed_tools)
```
Called in `_run_step_direct` (`:5789-5826`) and the Explorer proposal prompt. Injected as
a fenced block. **This is the fix for F1** — the mid-loop retrieval at `:5041-5053` now
writes into this block, not the dead `coordinate_signal`. The `conn`/`current_node_ids`
sources are the SAME accessors the existing `recall_decoder` / `live_context` use, so no
new DB plumbing is introduced.

### D1.2 Single resolver (PROPOSE)
**New** `agent/explorer.py:propose(goal, evidence, live_tools) -> dict`:
```python
{"kind": "tool"|"reasoning"|"done",
 "tool": str, "params": dict, "rationale": str}
```
- LLM emits JSON against `live_tools = get_registry_tools()`.
- Validator = existing `validate_tool_call(tool, params)` (`:5126` path) checks registry +
  schema. On unparseable/invalid ⇒ pheromone top-1 from `BehavioralPredictor` (once).
  **Never a stub.**
- **Capability-based web fallback (resolves G1.3):** if the LLM proposal is unparseable AND
  the goal's `task_class == "research"` (from `TaskClassifier`, D1.1) AND
  `capability_allowed(registry.resolve("crawler_query"))` is True, the resolver prefers
  `crawler_query` over blind pheromone top-1. This is safe because `crawler_query` is already
  in the registry with `aliases=["web_search","google_search"]` and `executor="crawler"`
  (tool_registry.py:602), and `tool_bridge.py:888-943` already canonicalizes web aliases →
  `crawler_query` dispatch. So deleting the regex override (D1.4) loses NO routing — the
  registry's alias + capability system replaces it.
- Replaces planner pre-assign (`:3658`), web-regex override (`:4814-4876`), queue-exhaustion
  Explorer (`:6436`), recovery graft (`:5516`) — all four authorities collapse into this.

### D1.3 Planner emits goals
`_plan_task` (`:3658`): emit `description` + `expected_output`; **drop `tool`/`params`**
from step schema. Steps become pure goals.

### D1.4 Delete regex override
`agent_kernel.py:4814-4876`: remove the web-intent regex that force-assigns `crawler_query`.
Resolver handles web intent via evidence + registry. Verify `crawler_query` still reachable
(unit test D1.4).

### D1.5 Route C.4/A1 into evidence
`agent_kernel.py:5041-5053`: write hints into `assemble_evidence` inputs, not
`coordinate_signal`.

### D1.6 Empowered `_run_step_direct`
`agent_kernel.py:5789-5826`: build prompt WITH evidence block. If step needs a tool →
call `explorer.propose` → `validate_tool_call` → execute via `tool_bridge.execute_tool`
(bridge already exists, registry-aware). Verify result.

### Phase 1 hard requirements (ALL must pass to gate Phase 2)
F1 fixed: evidence block present in acting prompt for ≥1 step in multi-step task
(asserted via prompt capture/log).
F6 fixed: exactly ONE tool-resolution authority; regex override deleted; `crawler_query`
still routable.
No hand-holding: planner output has no `tool` field.
G1 preserved: stub rate = 0 under new path.
Deterministic backstop: garbage LLM ⇒ top-1 pheromone tool, not stub.

### Phase 1 tests — `backend/tests/test_der_phase1.py`
1. `test_evidence_in_prompt` — capture Explorer prompt; assert PREDICTED NEXT / PROVEN
   PATH / AVOID / CONTRACTS sections present.
2. `test_single_authority` — grep confirms regex override removed; resolver is only
   `execute_tool` caller from planning.
3. `test_planner_no_tool_field` — `_plan_task` steps have no `tool` key.
4. `test_resolver_fallback` — LLM garbage ⇒ valid registry tool (top-1), not stub.
5. `test_crawler_still_routable` — web-intent goal ⇒ `crawler_query` via evidence.
6. `test_stub_rate_zero` — WS battery (Phase 0 set) ⇒ 0 stubs under new path.

### Phase 1 commit
`git commit -m "DER Phase 1: memory-coupled acting prompt + single runtime tool resolver (F1/F6 fixed)"`
Record `phase_complete` + tests.

---

## PHASE 2 — Emergent Shape (the "athlete": growth-width rule from Caducean physics)

**Goal:** Execution-tree *shape* emerges from the live Caducean state Σ=(x,y,ξ,u), not from
a QUICK/AGENTIC/FULL mode chosen up front. Recovery graft + growth-width → ONE operator.
Mode → budget envelope only.

**Source concepts (from `docs/handoffs/morphohdl-irisvoice-handoff.md` §5, §4):**
- The Duffing-oscillator governor: restoring force `F(u)=2u−2u³`, stable attractors at
  `u*=±1`. High `|u|` ⇒ near an attractor ⇒ confident/converged ⇒ treat step as atomic and
  execute. `u≈0` ⇒ still oscillating ⇒ uncertain ⇒ split into child steps. This is the
  concrete link between "growing circuits" (MorphoHDL) and "always-optimizing agent loops."
- **MorphoHDL break (§5 "Breaks") — HARD CONSTRAINT:** MorphoHDL cells are stateless and
  history-independent (same input always regrows the same topology). The Caducean Engine is
  explicitly **stateful** — Σ evolves, decisions depend on accumulated trajectory history.
  **Therefore the split/execute decision MUST use live `u`/`ξ` on purpose. It is NOT a pure
  stateless function.** This is the upgrade over MorphoHDL, not a violation of it. Do not
  "simplify" `_split_step` into a stateless predicate — that would flatten the
  state-dependent behavior that makes the physics governance valuable.
- **Sub-Loop mechanism (§1):** nested temporary Caducean sessions that collapse back into
  the parent as a single `COMPRESS` observation. Split children SHOULD be executed as
  Sub-Loops that collapse back, not as flat siblings — this preserves the trajectory as one
  coherent reasoning arc.

### D2.1 Split operator (stateful, physics-driven) + work-unit termination
**New** `agent_kernel.py:_split_step(item, trigger, caducean_state, work_units) -> List[QueueItem]`:
```python
def _split_step(self, item: QueueItem, trigger: str,
                cad: Dict[str, float], work_units: int) -> List[QueueItem]:
    """trigger in {"unresolved_u", "verify_failed"}.
    Stateful: width depends on live |u| from caducean_state, NOT a fixed rule.
    Low |u| (unresolved/oscillating) -> wider; high |u| (converged) -> narrower.
    Children run as Sub-Loops (handoff §1) that collapse back to parent as one COMPRESS.
    TERMINATION: split is PERMITTED only if work_units >= width. Split PREPAYS `width`
    work units up front (see D2.4 / Appendix B). This is what makes Phi strictly decrease."""
    u = cad.get("u", 0.0)
    width = self._growth_width(u)            # |u| low -> 3, |u| high -> 1
    width = min(width, DER_MAX_GRAFTS, work_units)  # cap 3 AND bounded by remaining work
    if width < 1 or item.depth_layer >= MAX_DEPTH:
        return []                            # refused -> step forced atomic
    children = []
    for i in range(width):
        child = QueueItem(
            step_id=f"{item.step_id}_s{i}",
            step_number=item.step_number,
            description=f"{item.description} (sub {i+1})",
            objective_anchor=item.objective_anchor,
            depth_layer=item.depth_layer + 1,
            expected_output=item.expected_output,
            is_subloop=True,                   # collapses back to parent as COMPRESS
        )
        children.append(child)
    return children

def _growth_width(self, u: float) -> int:
    # Three explicit bands (reconciles D2.3 with split decision):
    #   |u| < U_SPLIT (0.5)        -> unresolved/oscillating -> split wide (3)
    #   U_SPLIT <= |u| < 0.85      -> mid-band: atomic step BUT needs LLM rubric (D2.3)
    #   |u| >= 0.85                -> converged -> atomic, deterministic verify only
    au = abs(u)
    if au < U_SPLIT:        return 3
    if au < 0.85:           return 1   # atomic; verification strictness handled by D2.3
    return 1
```
`U_SPLIT` is a NEW named constant (start 0.5; tuned empirically by the Phase 4 outer loop).
`MAX_DEPTH=3` enforced in `der_loop.py:DirectorQueue`. `DER_MAX_GRAFTS=3` (der_constants.py).
`DER_WORK_UNITS_0` is DERIVED, not hardcoded (D-1): `DER_WORK_UNITS_0 = max(1, int(resolve_context_window() / avg_step_cost))`.
`avg_step_cost` starts at a constant (e.g. 1500 tokens) and is Phase-4-tunable. So the work-unit
counter and the context window are the SAME resource (System Invariant). See Appendix B base case.

### D2.2 PERCEIVE (u,ξ) at the split point
`ffi_caducean_get_state(session_id)` (gateway/iris_ffi) is already called at
`agent_kernel.py:6223`. Thread `cad` into the step-consumption point so `_split_step` reads
live `u`. If FFI unavailable, fall back to
`CaduceanTrajectoryRecorder.get_latest_coordinate(session_id)` (returns latest x,y,ξ,u).

### D2.3 Adaptive verify strictness
Stage ACT+VERIFY: `|u|` high (near attractor) ⇒ deterministic checks only; mid-oscillation
(`|u|` mid-band) ⇒ additionally apply the LLM rubric (Phase 3 `verify_rubric.py`). This
matches the governor's confidence: verify harder where the physics says we're uncertain.

### D2.4 Mode demotion + work-unit counter
`der_constants.py:ExecutionMode` — keep token budgets (15k/30k/60k) + UI; **strip all shape
authority**. The QUICK/AGENTIC/FULL distinction becomes a pure budget envelope. Step
decomposition is now exclusively the growth-width operator's job (D2.1). This resolves the
overlap the handoff §6 warned about: Immortus's `drift`/`route_score` (route-level cliff)
and the per-step `u`/`ξ` growth-width (continuous) must NOT both decide fan-out — growth-width
owns per-step; Immortus owns whole-route activation (kept separate, per handoff §6 open Q6).

**Work-unit counter (termination):** introduce a single `work_units` integer per task,
initialized `DER_WORK_UNITS_0 = max(1, int(resolve_context_window() / avg_step_cost))` (D-1).
It is the unified termination resource: split prepays `width` units, complete/fail/veto
consume 1, token burn is tracked separately. The Duffing governor decides *intent* to split
(via `|u|`); `work_units` decides *permission* (split refused when `work_units < width`).
Governor and budget act in tandem — shape from physics, termination from the counter. The
counter is the SAME resource as the context window (System Invariant). See Appendix B for the
proof + base case.

### Phase 2 hard requirements (ALL must pass to gate Phase 3)
- **Emergence:** goal unresolved at `|u|≈0` ⇒ ≥2 child steps (split), not single forced exec.
- **Recovery unified:** FAILED verification ⇒ SAME `_split_step` operator as the physics
  trigger (no separate graft code path remains).
- **Stateful, not stateless (MorphoHDL break):** `_split_step` reads live `u`; a unit test
  that freezes `u` shows width changes with `u` (proves it is not a fixed predicate).
- **Sub-Loop collapse:** split children carry `is_subloop=True` and collapse to parent as
  one COMPRESS observation (asserted via trajectory log).
- **Termination (G3):** Φ non-increasing per cycle; exits within bounds (fuzz 200 graphs).
- **Mode is budget only:** AGENTIC vs FULL ⇒ identical decomposition for same goal, different
  token budget.

### Phase 2 tests — `backend/tests/test_der_phase2.py`
1. `test_split_on_unresolved` — mock `u=0.05` ⇒ ≥2 children.
2. `test_split_on_failure` — verification FAILED ⇒ split (same operator).
3. `test_no_split_on_converged` — mock `u=0.95` ⇒ atomic, no split.
4. `test_split_is_stateful` — freeze `u=0.1` vs `u=0.9` ⇒ different widths (proves not
   stateless; MorphoHDL-break constraint).
5. `test_subloop_collapse` — split children recorded with `is_subloop` and collapse to parent
   as one COMPRESS (trajectory log).
6. `test_termination_potential` — fuzz 200 random task graphs ⇒ all exit; Φ non-increasing.
7. `test_mode_is_budget_only` — same goal, AGENTIC vs FULL ⇒ identical decomposition.

### Phase 2 commit
`git commit -m "DER Phase 2: emergent growth-width split/execute from Caducean (u,xi); Sub-Loop collapse; recovery unified; mode demoted to budget (MorphoHDL athlete rule)"`
Record `phase_complete` + tests.

---

## PHASE 3 — Verification Rigor + G1–G5 Invariant Suite

**Goal:** Lock the five enforceable invariants as a permanent suite. The "guarantee" layer.

### D3.1 Verification rubric
`agent/verify_rubric.py`:
```python
RUBRIC_PROMPT = """GOAL: {desc}
EXPECTED: {expected_output}
RESULT: {result[:1500]}
Does RESULT meet GOAL per EXPECTED? JSON: {"met":bool,"confidence":0-1,"reason":str}"""
# call at temp 0, same pattern as Reviewer
```

### D3.2 Invariants
- **G1** no silent no-op: stub ⇒ FAILED, never `mark_complete` VERIFIED.
- **G2** honest feedback: no success record without verification artifact.
- **G3** termination: Φ non-increasing (proven in Appendix B).
- **G4** non-forgetting w/ provenance: crystallization only from VERIFIED; decay only
  touches unverified/unretrieved; landmark → trajectory IDs.
- **G5** learning data always exists: every COMMIT writes `(state, action, verified_label)`.

### D3.3 Concrete crystallization + COMMIT sinks (resolves G3.1, G3.2)
**G4 gate (verified source):** the crystallization path is
`workflow_capture.register_verified_skill(stub, memory, confidence=0.9)`
(workflow_capture.py:136) — it writes `category="named_skills"`, `verified=True` to
`memory.semantic`. **Gate:** `register_verified_skill` is called ONLY when the step's
`_verify_step_result` == `VERIFIED` (Phase 0 D0.1). A `partial`/`miss`/`FAILED` step never
reaches it. Provenance: the `stub["tool_sequence"]` already carries the trajectory IDs
(step_ids) → satisfies "landmark traces to trajectory IDs." Decay (mycelium edge decay)
touches only `unverified`/`unretrieved` edges, never VERIFIED landmarks.

**G5 schema (concrete "state"):** every COMMIT writes a row to a new
`der_commits` table via `CaduceanTrajectoryRecorder`:
```python
def record_commit(self, session_id, state_hash, action, verified_label, step_id):
    # state_hash = sha256(coordinate_snapshot + working_memory_hash)  # compact, replayable
    # action     = tool name or "reasoning"
    # verified_label = "VERIFIED"|"UNVERIFIED"|"FAILED"  # from _verify_step_result
```
This is the exact `(state, action, verified_label)` triple the Phase 4 outer loop consumes
as its learning signal — it exists for EVERY commit, satisfying G5.

### Phase 3 hard requirements (ALL — gate for Phase 4)
G1–G5 all enforced by `backend/tests/test_der_invariants.py`.
G3 proof appended (Appendix B).
Full WS battery passes: stub rate=0, Pacman>0, veto≤2, verified-rate ≥ baseline.

### Phase 3 tests — `backend/tests/test_der_invariants.py`
1. `test_g1_no_silent_noop` 2. `test_g2_honest_feedback` 3. `test_g3_termination`
4. `test_g4_monotone_auditable` 5. `test_g5_schema_fixed`

### Phase 3 commit
`git commit -m "DER Phase 3: verification rigor + G1-G5 invariant suite (guarantee layer)"`
Record `phase_complete` + tests. **Phase 4 may not begin until this passes.**

---

## PHASE 4 — Outer Self-Tuning Loop (the "coach": AIDE² over Caducean constants)

**Goal:** A disciplined auto-tuner for the engine's named constants. Viable ONLY because
Phases 0–3 make trajectories carry VERIFIED labels and the growth-width rule (Phase 2) is
the tunable "athlete." This is **Level 1** self-improvement (net positive vs manual tuning)
per Weco's framing — NOT recursive self-improvement in the strong sense. Keep that
distinction explicit.

**Source concepts (from `docs/handoffs/morphohdl-irisvoice-handoff.md` §9):**
- **Inner loop (athlete)** = DER loop + growth-width rule (Phase 2), governed live by
  `u`/`ξ`. Already built.
- **Outer loop (coach)** = a SEPARATE, slower process that reads completed session
  trajectories and proposes small changes to the **governing constants themselves** — it
  does NOT run tasks, it watches tape.
- **Three safety properties that do the work (§9.1):**
  1. **Public/private split** — the inner loop only sees a "public" score to steer itself;
     whether a change survives is decided on a "private" held-out score it never sees. This
     stops the system from learning to look good on its own metric (reward-hacking).
  2. **Fixed cost budget** — proposed changes can't win by spending more compute; they must
     be genuine efficiency gains.
  3. **Task heterogeneity** — every proposed change tested across a varied task set, forcing
     generalizable improvements instead of narrow overfitting.
- **Raw material already recorded (§9.2):** `caducean_trajectories` (per-step
  `x,y,ξ,u,action,outcome,eml_after,recommendation` via `CaduceanTrajectoryRecorder.record`),
  `mycelium_traversals`, episodic memory. Unused for this purpose until now.
- **Immortus caution (§9.4 — CRITICAL):** `TemporalCoordinate.drift`/`momentum` is a SEPARATE
  scoring system from `u`/`ξ`, computed from the very step-success signal a constant change
  might be gaming. **The held-out metric must NOT be `drift`** (or any signal derived from
  step-success). It must be genuinely external: natural exit rate, `DER_EMERGENCY_STOP` rate,
  token cost, downstream task success.
- **First target constant (D-3, INVERTS handoff §9.4 order):** the fan/fold dials
  `U_SPLIT` (new, Phase 2) and `avg_step_cost` (D-1) are probed FIRST — they ARE the
  compression threshold and the shared resource. The `interpreter.py` pairwise
  `CoordinateInterpreter.resolve()` cutoffs (confidence-diff `0.05`, recency-diff `1.0`)
  are downstream similarity thresholds, tuned LATER once fan/fold balance is right. Plus
  the topology thresholds below.
- **NBL ledger (§9.4):** log the outer loop's own history cheaply as an NBL-style ledger:
  "constant X: was V1, tried V2, held-out result R, kept/rejected" — costs almost nothing,
  permanent signal.

### D4.0 Exit-type signal (resolves G4.1 — natural exit rate needs a source)
`caducean_trajectories` records per-step `x,y,xi,u,action,outcome,eml_after,recommendation`
but has **NO explicit session exit-type** (NATURAL vs EMERGENCY_STOP). `DER_EMERGENCY_STOP=200`
(der_constants.py:105) is a cycle-count brake, not a stored signal; "NATURAL EXIT" is an MCM
`_ctx.gov` value not persisted to the trajectory store. So the held-out metric must be made
derivable. **Add** to `CaduceanTrajectoryRecorder`:
```python
def record_session_exit(self, session_id: str, exit_type: str) -> None:
    # exit_type in {"NATURAL","EMERGENCY_STOP","TIMEOUT","ERROR"}
    self._conn.execute(
        "CREATE TABLE IF NOT EXISTS caducean_session_exits "
        "(session_id TEXT, exit_type TEXT, ts REAL)")
    self._conn.execute(
        "INSERT INTO caducean_session_exits VALUES (?,?,?)",
        (session_id, exit_type, time.time()))
```
Hook it from `ConversationMemory.archive_on_session_end` (memory.py:282): classify exit as
NATURAL if `task_records` final outcome is success AND step count < `DER_EMERGENCY_STOP`;
else EMERGENCY_STOP/TIMEOUT/ERROR as appropriate. The outer loop's `_score` reads
`natural_exit_rate = NATURAL / total` from this table. **This is a Phase 4 prerequisite
sub-task (4.1b) — without it the metric is undefined.**

### D4.1c Domain field on trajectories (resolves G4.2 — heterogeneity needs a source)
`caducean_trajectories` has NO `domain` column and `get_trajectories` has no domain filter
(caducean_trajectory.py:127-152). The R4.5 heterogeneity requirement ("held-out spans ≥2
`domain` values") has no data source yet. **Add** `domain` the same idempotent way the
existing `recommendation` column was added (caducean_trajectory.py:43-47):
```python
_SQL_ADD_DOMAIN_COLUMN = "ALTER TABLE caducean_trajectories ADD COLUMN domain TEXT"
# in _ensure_table(): try/except ALTER (ignore "already exists")
# in record(): add `domain: str = "general"` param -> INSERT includes domain
# in get_trajectories(): add `domain: Optional[str] = None` -> WHERE domain = ?
```
`domain` is derived from the session's primary coordinate space (via
`myc._registry.get_active` / the session's top coordinate) or passed in by the caller. The
WS battery (Appendix C) seeds ≥100 trajectories across ≥2 domains by running tasks tagged
to different domains (e.g. "code", "research"). **Phase 4 prerequisite sub-task 4.1c.**

### D4.1 Tunable constant set (concrete, from code)
From `backend/memory/mycelium/spaces.py` and `topology.py` (verified this session):
- `CONVERGENCE_THRESHOLD = 0.08` (topology.py:41) — Z ≥ this ⇒ ACQUISITION
- `DIVERGENCE_THRESHOLD = -0.06` (topology.py:42) — Z ≤ this ⇒ EVOLUTION
- `PRUNE_THRESHOLD = 0.08` (spaces.py:172) — delete edge below this
- `HIGHWAY_THRESHOLD = 0.85` (spaces.py:173) — highway bonus above this
- `SPLIT_THRESHOLD = 0.40` (spaces.py:178) — split node on variance above this
- `interpreter.py` `resolve()` cutoffs: confidence-diff `0.05`, recency-diff `1.0`
- `U_SPLIT` (NEW, Phase 2) — growth-width unresolved threshold (start 0.5)
- edge-scoring deltas in `scorer.py` (hit +0.05, partial +0.02, miss −0.08, highway +0.01)

### D4.2 The algorithm (7 steps, single-variable, guarded — handoff §9.3)
**New module** `agent/outer_loop.py:OuterTuner`:
```python
class OuterTuner:
    def run_once(self):
        # 1. TRIGGER (D-4): fire when memory is about to fold — the SAME signal as context
        #    compaction, not an arbitrary cadence. Subscribe to mcm_check_compress's
        #    pre-compress hook AND record_session_exit (memory.py:282). At that moment the
        #    trajectory has just folded and "did we fold well?" is live.
        batch = CaduceanTrajectoryRecorder().get_trajectories(min_count=100)
        # 2. PROPOSE ONE CHANGE: pick a single named constant, one bounded nudge
        const, old_v, new_v = self._propose_one(batch)   # NEVER multi-variable
        # 3. EVALUATE ON HELD-OUT (public/private split): replay new_v on a SEPARATE
        #    batch; score with metric INDEPENDENT of the tuned score
        heldout = self._heldout_batch()                   # disjoint from `batch`
        r_old = self._score(batch, const, old_v)          # public (inner-loop sees)
        r_new = self._score(heldout, const, new_v)        # private (survival decided here)
        # 4. BUDGET-CAP: fixed replay sessions / compute per proposal
        # 5. TASK HETEROGENEITY: heldout spans >1 `domain` coordinate value
        # 6. KEEP ONLY IF WINS; LOG EVERYTHING
        kept = r_new > r_old
        self._ledger.append({const, old_v, new_v, r_old, r_new, kept})
        if kept:
            self._apply(const, new_v)                     # update constant in module
        # 7. DO NOT extend to rewriting growth-width LOGIC until step-tuning stable
```
- **Step 2 single-variable guard:** `_propose_one` returns exactly one (const, nudge). A
  multi-variable proposal is rejected by construction (legibility constraint — AIDE²'s
  evolved agent became hard to maintain; we prevent that from day one).
- **Step 3 public/private:** `r_old` uses the live pheromone/confidence score (what the
  inner loop optimizes — "public"); `r_new` uses the held-out metric (natural exit rate —
  "private"). Survival is decided ONLY on `r_new`. This is the anti-reward-hack split.
- **Step 4 budget-cap:** `max_replay_sessions = DER_MAX_CYCLES` (or fixed N); evaluation
  compute capped so tuning can't become "run more sessions."
- **Step 5 heterogeneity:** `_heldout_batch()` filters `caducean_trajectories` by DISTINCT
  `domain` coordinate values (≥2). Reuse `mycelium` `domain` space mapping.
- **Step 6 ledger:** NBL-style (`nbl.py` `build_mito_tag` pattern) permanent log of every
  accepted AND rejected proposal. AIDE² rejected ~90% — that ratio is a feature.

### D4.3 Held-out metric (your choice: natural exit rate primary)
- **Primary:** `natural_exit_rate` = fraction of held-out sessions ending in NATURAL EXIT
  (not `DER_EMERGENCY_STOP`, not timeout). Computed from `caducean_trajectories` outcome +
  MCM `_ctx.gov`.
- **Secondary:** `TOPO_VIOLATION` rate (lower is better), `tokens_per_verified_step`
  (lower is better).
- **Explicitly excluded:** `drift`, `route_score`, any step-success-derived signal (Immortus
  caution §9.4).

### D4.4 Where it runs
Background job triggered by the **context-compaction signal** (D-4): subscribes to
`mcm_check_compress`'s pre-compress hook and `record_session_exit` (memory.py:282). NOT
inside the DER hot path. Reads WAL `caducean_trajectories` (concurrent-safe). The 70%-budget
cadence is explicitly NOT used — it is a proxy for "memory full"; we observe at the actual
fold event.

### Phase 4 hard requirements (ALL must pass)
- **Public/private split enforced:** survival decided on held-out metric, never on the
  tuned pheromone/confidence score (asserted: `r_new` is the gate variable).
- **Single-variable only:** `_propose_one` returns exactly one constant; multi-variable
  proposal rejected (unit test).
- **Immortus caution:** held-out metric set excludes `drift`/`route_score`/step-success
  signals (asserted by metric whitelist).
- **Heterogeneity:** held-out batch spans ≥2 `domain` values (asserted).
- **Ledger:** accepted AND rejected proposals both logged with before/after + held-out
  result (asserted via ledger length).
- **No regression:** G1–G5 invariants pass under ANY tuned constant set (Phase 3 suite re-run).
- **Level-1 framing:** docstring/comments state this is constant auto-tuning, not recursive
  self-improvement.

### Phase 4 tests — `backend/tests/test_der_phase4.py`
1. `test_outer_loop_heldout_metric` — mock trajectories; proposed constant evaluated on
   held-out set (disjoint), not inspiring set; survival uses `r_new`.
2. `test_outer_loop_single_variable` — `_propose_one` returns exactly one (const, nudge);
   injected multi-variable proposal rejected.
3. `test_outer_loop_metric_whitelist` — metric set excludes `drift`/`route_score`;
   natural_exit_rate present.
4. `test_outer_loop_heterogeneity` — held-out batch spans ≥2 `domain` values.
5. `test_outer_loop_ledger` — accepted + rejected proposals both logged with before/after.
6. `test_outer_loop_no_regression` — tuned constants still pass G1–G5 invariant suite.

### Phase 4 commit
`git commit -m "DER Phase 4: AIDE2-style outer self-tuning loop (MorphoHDL/Caducean coach); tunes U_SPLIT + topology/interpreter constants on held-out natural-exit-rate; NBL ledger; Immortus-drift excluded"`
Record `phase_complete` + tests.

---

# PART 3 — TASKS (traceable sub-tasks)

## Phase 0 tasks
- [ ] 0.1 Add `_verify_step_result` to `agent_kernel.py`; wire into `_der_finalize_step`.
  _Requirements: R0.1_
- [ ] 0.2 Remove tool-outcome record on veto path (`:5080-5088`). _Requirements: R0.2_
- [ ] 0.3 Fix escalation remaining (`:6298`). _Requirements: R0.3_
- [ ] 0.4 Add `expected_output` to `QueueItem`; populate in `_execute_plan_der`/`_plan_task`;
  confirm `analyze_gaps` reads it. _Requirements: R0.4_
- [ ] 0.5 Episodic EWMA + `outcome_type` update (`:326-342`). _Requirements: R0.5_
- [ ] 0.6 Outcome coarsening (`:5297-5300`). _Requirements: R0.6_
- [ ] 0.7 Canonical `der_failure` zone + `tool_name` field (`:5205,5504,6052`). _Requirements: R0.7_
- [ ] 0.8 Add DCP Pass 4 fan-trace (`dcp.py`); `CaduceanTrajectoryRecorder.record_fan_trace`
  + `der_fan_traces` table. _Requirements: R0.8_
- [ ] 0.9 Extend `inject_recovery` preamble (`mcm.py:207,239`) to embed FAN SUMMARY from
  `der_fan_traces`. _Requirements: R0.9_
- [ ] 0.10 Couple DCP `turn_protection` + MCM compress `budget_pct` + DER `work_units` to
  `resolve_context_window()` / `W0` (D-1). _Requirements: R0.10_
- [ ] 0.11 Write `test_der_phase0.py` (9 tests); run; commit. _Requirements: R0.1-R0.10_

## Phase 1 tasks
- [ ] 1.1 Create `agent/evidence.py:assemble_evidence`. _Requirements: R1.1_
- [ ] 1.2 Create `agent/explorer.py:propose`. _Requirements: R1.2, R1.3_
- [ ] 1.3 Planner emits goals only (drop `tool`/`params`). _Requirements: R1.2_
- [ ] 1.4 Delete web-regex override (`:4814-4876`). _Requirements: R1.4_
- [ ] 1.5 Route C.4/A1 into evidence. _Requirements: R1.1_
- [ ] 1.6 Empower `_run_step_direct` with evidence + resolver. _Requirements: R1.1, R1.5_
- [ ] 1.7 Write `test_der_phase1.py` (6 tests); run; commit. _Requirements: R1.1-R1.5_

## Phase 2 tasks
- [ ] 2.1 Add `_split_step` operator. _Requirements: R2.1_
- [ ] 2.2 PERCEIVE (u,ξ) earlier; feed `|u|` to split. _Requirements: R2.1, R2.2_
- [ ] 2.3 Adaptive verify strictness. _Requirements: R2.2_
- [ ] 2.4 Demote `ExecutionMode`; add `U_SPLIT`. _Requirements: R2.3_
- [ ] 2.5 Write `test_der_phase2.py` (5 tests); run; commit. _Requirements: R2.1-R2.4_

## Phase 3 tasks
- [ ] 3.1 Add `agent/verify_rubric.py`. _Requirements: R3.2_
- [ ] 3.2 Crystallization gated on VERIFIED + trajectory trace. _Requirements: R3.3_
- [ ] 3.3 COMMIT writes `(state,action,verified_label)`. _Requirements: R3.4_
- [ ] 3.4 Write `test_der_invariants.py` (G1–G5). _Requirements: R3.1_
- [ ] 3.5 Full WS battery; commit. _Requirements: R3.1_

## Phase 4 tasks
- [ ] 4.1 Create `agent/outer_loop.py:OuterTuner`; trigger on compaction signal (subscribe
  to mcm_check_compress pre-compress hook + `record_session_exit`); pull `caducean_trajectories`
  batch. _Requirements: R4.0_
- [ ] 4.1b Add `CaduceanTrajectoryRecorder.record_session_exit` + `caducean_session_exits`
  table; hook from `ConversationMemory.archive_on_session_end` (memory.py:282). _Requirements: R4.2 (metric source)_
- [ ] 4.1c Add `domain` column to `caducean_trajectories` (idempotent ALTER, like
  `recommendation`); `record()` takes `domain`; `get_trajectories(domain=)` filter.
  _Requirements: R4.5 (heterogeneity source)_
- [ ] 4.2 `_propose_one` returns exactly one (const, nudge); multi-variable rejected.
  _Requirements: R4.1_
- [ ] 4.3 Public/private split: `r_old` (public pheromone score) vs `r_new` (private
  held-out natural-exit-rate from `caducean_session_exits`); survival uses `r_new`.
  _Requirements: R4.2_
- [ ] 4.4 Metric whitelist excludes `drift`/`route_score`; natural_exit_rate primary.
  _Requirements: R4.4_
- [ ] 4.5 Budget-cap (fixed replay sessions) + heterogeneity (held-out spans ≥2 `domain`).
  _Requirements: R4.5_
- [ ] 4.6 NBL ledger logs accepted + rejected with before/after + held-out result.
  _Requirements: R4.3_
- [ ] 4.7 Regression guard: re-run G1–G5 suite under tuned constants. _Requirements: R4.6_
- [ ] 4.8 Write `test_der_phase4.py` (6 tests); commit. _Requirements: R4.0-R4.6_

---

# PART 4 — APPENDICES

## A. Verification rubric prompt (Phase 3)
```
GOAL: {item.description}
EXPECTED OUTPUT: {item.expected_output}
RESULT: {result[:1500]}
Does the RESULT meet the GOAL per EXPECTED OUTPUT?
Answer JSON: {"met": true|false, "confidence": 0-1, "reason": "..."}
```

## B. Termination potential (G3) proof — corrected (Lyapunov potential, physics-based)

**The broken version:** Φ = (#unverified) + graft_budget + (MAX_DEPTH−depth) +
token_budget. A split of width w adds w unverified items but only −1 graft ⇒ Φ *increases*
by (w−1). Not a proof. Fixed below.

**This is a Lyapunov-style potential (Tier-2 physics enforcement), NOT a binary gate.** Φ
decreasing monotonically is a *stability* property: the trajectory converges to a well
(terminates), regardless of any single step's "correctness." The guarantee is dynamical.

**Corrected potential (unified work-unit counter):**
```
W  = remaining work units (single counter, init DER_WORK_UNITS_0 = max(1, int(resolve_context_window()/avg_step_cost)))
Φ  = W + (MAX_DEPTH − depth) + token_budget_remaining
```
Branching accounting — split PREPAYS `width` units up front:
```
split (width w):   W -= w ;  unverified += (w − 1)   # net unverified +w−1, W −w
complete:          unverified -= 1 ;  W -= 1
fail → split:      same as split (W -= w)
veto-consume:      unverified -= 1 ;  W -= 1
token burn:        token_budget_remaining -= 1
```
Φ per event (depth, token unchanged unless noted):
- **split**: ΔW = −w, Δunverified = +(w−1) ⇒ ΔΦ = −w + (w−1) = **−1** (strictly down, ∀w). ✓
- **complete**: ΔW = −1, Δunverified = −1 ⇒ ΔΦ = **−2**. ✓
- **fail→split**: same as split ⇒ **−1**. ✓
- **veto**: ΔΦ = **−2**. ✓
- **token burn**: ΔΦ = **−1**. ✓

Φ strictly decreases on EVERY event ⇒ loop terminates as long as `W ≥ 0` is enforced
(split refused when `W < width`, and at `depth == MAX_DEPTH`). Bounds: `DER_WORK_UNITS_0 =
max(1, int(resolve_context_window()/avg_step_cost))` (D-1), `MAX_DEPTH=3`, `DER_MAX_GRAFTS=3`,
`max_cycles=40`, veto cap=2.

**Base case (long-horizon branching task, "implement a feature"):**
Say `resolve_context_window()=32768`, `avg_step_cost=1500` ⇒ `W0 = 21`. Init W=21, depth=0,
MAX_DEPTH=3. Φ₀ = 21 + 3 = 24.
- Step 1: `|u|=0.1` ⇒ split w=3. W: 12→9, items 1→3. Φ: 15 → 9 + 2 = 11 (**−4**).
- 3 children at `|u|=0.9` ⇒ atomic complete. W: 9→6, items 3→0. Φ: 11 → 6 + 0 = 6 (**−5**).
- Done in 4 events, W=6 remaining. **No blowup.** A pathological oscillating chain is capped
  by MAX_DEPTH (split refused at depth 3 ⇒ forced atomic). Φ never rises. Termination holds.

## C. WS task battery (`scripts/validate_der_*.py`)
A reusable harness that drives the backend over WebSocket (port 8090) with a fixed task
set. **Also seeds the Phase 4 held-out pool** (≥100 trajectories across ≥2 domains):
1. Single-step factual ("what is 2+2") — domain="general" — asserts VERIFIED, no stub.
2. Multi-step code task ("implement fib in Python, run it") — domain="code" — asserts
   evidence block in prompt (log-captured), tool resolved at runtime, VERIFIED.
3. Web-intent ("research X") — domain="research" — asserts `crawler_query` routed via
   resolver (capability fallback, D1.2).
4. Failing task (force a tool error) — domain="code" — asserts FAILED (not success edge),
   graft recovery (split operator).
5. Local-model task (requires GPU + RotorQuant llama-server, n_ctx=32768) — asserts
   budget = context_window*0.9, Pacman stores >0.
Asserts per run: stub rate=0, Pacman>0, veto loops≤2, verified-rate ≥ baseline.
**Seeding:** run the battery N times (N≥20) across the 3 domains to accumulate ≥100
`caducean_trajectories` rows with distinct `domain` values (per D4.1c) — this is the
held-out pool the Phase 4 outer loop draws from.

## D. Rollout / version control
- Direct replace (no flag). Commit at EVERY phase gate (§commits above).
- Record `phase_complete` event + `record_test` after each phase's tests pass.
- If a later phase regresses an earlier invariant, `git revert` the single phase commit.
- Live validation after each backend restart via `scripts/validate_der_*.py`.

## E. Resolved risk from prior draft
The other agent flagged that replacing 4 tool authorities with one resolver needs the live
`tool_registry` API. **Resolved:** `tool_registry.py` is already a mature single source of
truth with `get_registry_tools()`, `validate_tool_call()`, `resolve_tool()`,
`capability_allowed()`, `is_parallel_safe()`. The resolver calls `get_registry_tools()`
directly — no new API, no import cycle (registry is importable with zero heavy side-effects
by design). The four authorities are *call sites* to collapse, not a missing capability.

## F. MorphoHDL / Caducean concept map (where each handoff concept lives in this spec)
| Handoff concept | Location in spec | Why |
|---|---|---|
| Growth-width rule (§5) — the "athlete" | Phase 2 (D2.1–D2.4, R2.0–R2.4) | Per-step split/execute driven by live `u`/`ξ`; stateful by design (MorphoHDL break) |
| Sub-Loop collapse (§1) | Phase 2 D2.1 (`is_subloop`, COMPRESS) | Split children collapse to parent as one observation |
| Duffing governor `F(u)=2u−2u³` (§4) | Phase 2 D2.1 (`_growth_width`) | `|u|` low ⇒ split wide; `|u|` high ⇒ atomic |
| Mode/shape overlap warning (§6 Q6) | Phase 2 D2.4 | Growth-width owns per-step; Immortus owns whole-route (kept separate) |
| AIDE² outer loop (§9.3) — the "coach" | Phase 4 (D4.1–D4.4, R4.0–R4.6) | 7-step single-variable tuner over constants |
| Public/private split (§9.1) | Phase 4 D4.2/R4.2 | Anti-reward-hack; survival on held-out metric |
| Fixed cost budget + heterogeneity (§9.1) | Phase 4 D4.4/R4.5 | No compute-gaming; generalizable gains |
| Immortus caution: don't tune on `drift` (§9.4) | Phase 4 D4.3/R4.4 | Held-out metric excludes step-success signals |
| First target: `interpreter.py` cutoffs (§9.4) | Phase 4 D4.1 | confidence-diff 0.05, recency-diff 1.0 probed first |
| NBL ledger (§9.4) | Phase 4 D4.3/R4.3 | Permanent accept/reject history, near-zero cost |
| Raw material: `caducean_trajectories` (§9.2) | Phase 4 D4.1 | Already recorded via `CaduceanTrajectoryRecorder.record` |
| Tunable constants (topology.py/spaces.py) | Phase 4 D4.1 | CONVERGENCE_THRESHOLD, DIVERGENCE_THRESHOLD, PRUNE/HIGHWAY/SPLIT_THRESHOLD, U_SPLIT |

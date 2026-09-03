# Tasks: Phase 6 — DER Integrity + Self-Tuning

> **Blocked on Phase 2** (honest displayed labels) and **Phase 4** (semantic verification producing
> them). Last phase. Everything needed is in this spec.
>
> This phase repairs a guard that **appears** to work. Two of three branches can never fire, nothing
> raises, and nothing logs. Test accordingly: every guard must be proven able to reject
> **independently**.

---

## Wave 0 — Baseline: confirm the gap is real

- [ ] **T0.1** Snapshot `/api/debug/caducean` → `outer_loop`. Expect `live_guards: 1` with
  `verified_fraction` and `tokens_per_verified` listed as dead.
  RIPPLE: this is a **negative** baseline — you are confirming a known defect exists, not that a
  feature works. If `live_guards` is anything other than 1, something changed since the audit;
  report it before proceeding.

- [ ] **T0.2** Drive 4–5 conversations to completion so session-exit rows accumulate, then re-read.
  RIPPLE: needs real sessions. A synthetic ledger would not prove the production path is dead.

- [ ] **T0.3** Confirm Phases 2 and 4 landed: displayed labels are honest, `_verified_fraction` is
  semantic, bands still `0.8`/`0.3`.
  RIPPLE: ⚠️ Phase 4 **raises the VERIFIED rate**, which moves `verified_fraction`'s baseline. Any
  threshold calibrated before Phase 4 is wrong on arrival.

- [ ] **T0.4** Baseline: `pytest backend/tests`.

---

## Wave 1 — Make the two dead guards live (REQ-2)

- [ ] **T1.1** (REQ-2 AC5) Replace
  [`outer_loop.py:136`](backend/agent/outer_loop.py:136) —
  `vf_sum += 1.0 if vc == 0 else 1.0` — with the **actual ratio** of VERIFIED steps to executed
  steps, read per held-out session from the `der_commits` ledger.
  RIPPLE: ⚠️ **The single most important line in this phase.** Both ternary branches are `1.0`, so
  the value is always exactly 1.0 and `proposed < baseline - tol` is never true. The input already
  exists — `verified_count` is correctly derived from the honest ledger at
  [`caducean_trajectory.py:351-360`](backend/agent/caducean_trajectory.py:351). It is simply unused.

- [ ] **T1.2** (REQ-2 AC6) Exclude zero-step sessions from the `verified_fraction` mean — **neutral**,
  not 1.0, not 0.0.
  RIPPLE: counting them as 1.0 is how the dead branch behaved, and it is wrong in the direction that
  **hides degradation** — a batch with several fresh sessions drags the mean toward 1.0 and masks a
  real drop.

- [ ] **T1.3** (REQ-2 AC4) Populate `tokens_total` at session exit from the session's real
  accumulated LLM token count.
  RIPPLE: the **only production caller** of `record_session_exit`
  ([`memory.py:329-336`](backend/agent/memory.py:329)) omits the argument, so it defaults to `0.0`
  ([`caducean_trajectory.py:333`](backend/agent/caducean_trajectory.py:333)) and
  `0.0 > 0.0 + 1e-6` is never true. Fixing `outer_loop.py:137` alone changes nothing — **the caller
  is the bug.**
  OQ-3: prompt + completion tokens both; confirm against Phase 1's `AVG_STEP_COST` calibration.

- [ ] **T1.4** (REQ-6 AC5) Introduce `GuardResult` with **distinct** `live` and `passed` fields; a
  non-live guard cannot contribute a pass.
  RIPPLE: ⚠️ this is the class-level fix. Conflating "no signal" with "no objection" is what let a
  three-metric gate accept on one metric. CT-D5 pins that `live=False` can never imply `passed=True`.

- [ ] **T1.5** Tests:
  - `test_verified_fraction_is_not_constant.py` — **parametrized over several distinct batches**;
    the value must take **more than one** value. ⚠️ A single-batch test passes against the bug.
  - `test_zero_step_session_excluded.py`
  - `test_tokens_per_verified_nonzero.py`
  - `test_guard_unavailable_is_not_pass.py`

---

## Wave 2 — Prove each guard can reject (REQ-2 AC7, REQ-4)

- [ ] **T2.1** (REQ-2 AC7) ⚠️ **The acceptance test for this phase.**
  `test_each_guard_rejects_independently.py` — parametrized over **all three** guards: construct a
  proposal that improves the other two and degrades exactly one, assert rejection in each case.
  RIPPLE: ⚠️ dropping a guard from the parametrize list is a test modification — **and it is exactly
  how two dead guards survived.** A compound gate tested only end-to-end passes with two dead branches.

- [ ] **T2.2** (REQ-4 AC1) Add the "never split" value to
  `_PROPOSALS["U_SPLIT"]` ([`outer_loop.py:39`](backend/agent/outer_loop.py:39)).
  RIPPLE: candidates are `[0.4, 0.5, 0.6, 0.7]` — `1.0` cannot be proposed, so the hack the
  acceptance criterion names has **never been exercised**. The guard is assumed, not proven.
  OQ-2: the value must be provably past the point where a split can occur, given `U_SPLIT`'s comparison.

- [ ] **T2.3** (REQ-4 AC2/AC3) Assert the gate **rejects** it: it wins `natural_exit_rate` and loses
  `verified_fraction`.
  RIPPLE: ⚠️ if a degenerate held-out batch ever lets it pass, that is a **finding about the batch**.
  Do **not** remove the candidate to make the suite green — removing it restores exactly the
  "prevented by omission" state this task exists to end.

- [ ] **T2.4** Tests: `test_never_split_rejected.py`.

---

## Wave 3 — Per-domain gating (REQ-3)

- [ ] **T3.1** (REQ-3 AC1/AC2) Iterate the compound gate per domain for every domain with **≥2**
  held-out sessions; reject if it fails in **any**.
  RIPPLE: `run_once` already accepts and forwards `domain`
  ([`outer_loop.py:184`](backend/agent/outer_loop.py:184)) but never iterates, and every production
  caller passes `domain=None` ([`:261`](backend/agent/outer_loop.py:261)).

- [ ] **T3.2** (REQ-3 AC3) Pooled fallback when no domain has ≥2 sessions.
  RIPPLE: pooled runs **first**, then per-domain — so per-domain gating is monotonic and can only
  tighten. It can never accept something pooled rejected.

- [ ] **T3.3** (REQ-3 AC4) Make per-domain outcomes observable: which gated, which passed, which
  rejected.

- [ ] **T3.4** Tests: `test_per_domain_veto.py`, `test_pooled_fallback.py`.

---

## Wave 4 — Ledger completeness + depth check (REQ-1, REQ-5)

- [ ] **T4.1** (REQ-1 AC1) Write a `(state, action, verified_label)` row for **every** executed
  action — VERIFIED, UNVERIFIED and FAILED alike.
  RIPPLE: a reasoning-only step (`tool=None`) still writes a row with `action="reasoning"`.

- [ ] **T4.2** (REQ-1 AC2/AC3/AC4) Wire the consequences: VERIFIED → crystallization-eligible +
  hit-scoring; UNVERIFIED → +0.02 partial credit, no crystallization, at most one re-propose;
  FAILED → −0.08 miss-scoring + a tier-3 AVOID header.
  RIPPLE: reward-adjacent consequences are gated on VERIFIED **only** (AC2).

- [ ] **T4.3** (REQ-1 edge case) A **vetoed** action that never executed writes **no** row.
  RIPPLE: absence is data. Writing a row for work that never happened is the phantom-card failure in
  the ledger.

- [ ] **T4.4** (REQ-1 AC5) A ledger write failure logs at debug and does **not** crash the step.

- [ ] **T4.5** (REQ-5) Run `TrailingDirector.analyze_gaps` on a VERIFIED step whose measured depth is
  below the expected depth for its task class; route detected gaps through the **same** queue path as
  failure-triggered gaps.
  RIPPLE: ⚠️ OQ-1 — calibrate the threshold from **post-Phase-4** labels. Semantic verification
  raises the VERIFIED rate, so more steps reach this check; a threshold tuned on substring labels
  flags too much and trains the operator to ignore it. Document any task class intentionally excluded
  (AC3) — no silent coverage loss.

- [ ] **T4.6** Tests: `test_failed_step_writes_commit_row.py`, `test_vetoed_step_writes_no_row.py`,
  `test_shallow_verified_flagged.py`, `test_depth_threshold.py`.

---

## Wave 5 — Observability, harness, close-out (REQ-6)

- [ ] **T5.1** (REQ-6 AC1/AC2) Report live-guard count, name any dead guards, and report **each
  metric's computed value**, not just pass/fail.
  RIPPLE: target is `live_guards: 3` with an empty dead list (CT-D6).

- [ ] **T5.2** (REQ-6 AC3/AC4) Log every accepted and rejected proposal with all three metric values
  and the deciding guard; include per-domain outcomes.

- [ ] **T5.3** Build `scripts/validate_outer_loop.py` with all 9 harness assertions.
  RIPPLE: assertions **2 and 4** decide whether the phase landed — 2 catches the literal defect
  (a constant `verified_fraction`), 4 catches the **class** of defect (a gate that looks compound and
  gates on one signal).

- [ ] **T5.4** Re-snapshot `/api/debug/caducean` and confirm `live_guards: 3` against T0.1's `1`.

- [ ] **T5.5** Full regression vs T0.4.

- [ ] **T5.6** Update `docs/CADUCEAN_ARCHITECTURE.md` §9 (**append**) and `bootstrap/GOALS.md`
  (**Domain 27**).

---

## Dependency / parallelization notes

**Hard sequencing:**
- **Phases 2 and 4 before Wave 0.** This phase consumes labels; repairing guards against dishonest
  labels tunes against noise.
- **T1.3 before T1.5's `tokens_per_verified` test.** The caller is the bug, not the formula.
- **Wave 1 before Wave 2.** You cannot prove a guard rejects independently until it is live.
- **T0.3 before T4.5.** The depth threshold must be calibrated post-Phase-4.

**Parallelizable:**
- **Wave 3 (per-domain) is independent of Wave 4 (ledger + depth).**
- T4.1–T4.4 (ledger completeness) are independent of the guard work in Waves 1–2.
- All test-writing precedes its implementation task.

**Riskiest tasks:**
1. **T1.1 — fixing the formula without checking the input.** `verified_count` is already correct;
   the defect is that a literal replaced it. Verify the ratio actually varies (T1.5).
2. **T1.3 — fixing `outer_loop.py:137` instead of the caller.** The formula is fine; `tokens_total`
   is never passed. Editing the consumer changes nothing.
3. **T2.1 — testing the gate end-to-end only.** That is how two dead branches survived a compound
   gate. Each guard must reject **independently**.
4. **T2.3 — removing the hack candidate to make the suite green.** Restores exactly the
   "prevented by omission" state this phase ends.
5. **T1.2 — counting zero-step sessions as 1.0.** Hides degradation in the direction that matters.
6. **T4.3 — writing a row for a vetoed action.** A ledger that records work that never happened is
   worse than one with gaps.
7. **T4.5 — calibrating depth pre-Phase-4.** Flags too much; trains the operator to ignore it.

### Baseline record
<!-- T0.1-T0.2 record "before"; T5.4 records "after". -->

| Observation | Before | After |
|---|---|---|
| `live_guards` | 1 (expected) | 3 (target) |
| Dead guards listed | `verified_fraction`, `tokens_per_verified` | none |
| `verified_fraction` computed value | 1.0 constant | |
| `tokens_per_verified` computed value | 0.0 | |
| "never split" candidate present | no | yes |
| "never split" rejected by the gate | untested | |
| Per-domain gating active | no (always pooled) | |

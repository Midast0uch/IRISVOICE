# Requirements: Phase 6 — DER Integrity + Self-Tuning

> **Execution position: SIXTH and LAST.** Blocked on Phase 2 (honest displayed labels) and Phase 4
> (semantic verification feeding those labels).
>
> Everything needed is in this spec.

## Decisions Locked

Resolved with the user 2026-07-28. Do **not** re-litigate.

1. **Every executed action commits a labeled outcome** — VERIFIED, UNVERIFIED and FAILED alike. A
   vetoed action that never executed writes **no** row; that is honesty, not an omission.
2. **The outer loop's acceptance gate is compound and must actually gate.** Three live measurements,
   all three able to reject independently.
3. **The "never split" hack must be rejected by the gate, not prevented by omission from the
   candidate list.** A guard that is never tested against the attack it names is not a guard.
4. **This phase is last** because it consumes labels. Repairing the guards before the labels are
   honest would tune against noise.

## Introduction

The outer self-tuning loop has a compound acceptance gate whose *intent* is correct and whose
implementation **cannot gate**. Traced against code:

| Guard | Status | Evidence |
|---|---|---|
| `natural_exit_rate` improves | **LIVE** | `ne_hits / n` from a real ledger column ([`outer_loop.py:130-141`](backend/agent/outer_loop.py:130)) |
| `verified_fraction` does not degrade | **DEAD — hardcoded** | [`outer_loop.py:136`](backend/agent/outer_loop.py:136): `vf_sum += 1.0 if vc == 0 else 1.0` — **both ternary branches are `1.0`**, so the value is always exactly 1.0 and `proposed < baseline - tol` becomes `1.0 < 1.0 - 1e-6`, never true. The `else` branch is an unfilled stub. |
| `tokens_per_verified` does not degrade | **DEAD — input never populated** | `tpv_sum += (tt / vc) if vc > 0 else 0.0` ([`:137`](backend/agent/outer_loop.py:137)) reads `tokens_total`, but the **only production caller** of `record_session_exit` ([`memory.py:329-336`](backend/agent/memory.py:329)) omits that argument, so it defaults to `0.0`. `proposed > baseline + tol` becomes `0.0 > 0.0 + 1e-6`, never true. |

**Net effect: the outer loop accepts any proposal that raises `natural_exit_rate`** — precisely the
single-metric reward-hacking the compound gate was written to prevent. This was confirmed live: the
debug endpoint reports `live_guards: 1` with both dead guards listed.

Two further gate criteria are unmet:

- **Per-domain gating is unimplemented.** `run_once` accepts a `domain` and passes it to `_ledger`
  ([`:184`](backend/agent/outer_loop.py:184)), but there is no iteration over domains and no
  "≥2 sessions" requirement. Every production caller passes `domain=None`
  ([`:261`](backend/agent/outer_loop.py:261)), so the gate is always pooled.
- **The "never split" rejection is unreachable rather than guarded.** `U_SPLIT` candidates are
  `[0.4, 0.5, 0.6, 0.7]` ([`:39`](backend/agent/outer_loop.py:39)) — `1.0` cannot be proposed, so the
  named hack is prevented by the proposal list, not rejected by the gate.

The input for a real `verified_fraction` **already exists**: `verified_count` is correctly derived
from the honest `der_commits` ledger
([`caducean_trajectory.py:351-360`](backend/agent/caducean_trajectory.py:351)). It is simply not used.

### Success criteria

- All three guards are live measurements; **each can independently reject** a proposal.
- A proposal that improves `natural_exit_rate` while degrading `verified_fraction` is **rejected**.
- A "never split" proposal is present in the candidate list and is **rejected by the gate**.
- Every executed action writes a `(state, action, verified_label)` row — failures included.
- A VERIFIED-but-shallow step is flagged rather than passing silently.
- `live_guards` reports **3**, with no dead guards listed.

## Requirements

---

### REQ-1: Commit a labeled outcome for every executed action

**User Story:** As the learning substrate I want every executed action recorded with its true label,
so I can learn from failures, not just successes.

**Verified:** Folded from the DER integrity audit (finding B). Phase 2 makes the displayed label
honest; Phase 4 makes the verification semantic. This requirement makes the **ledger** record all of
them.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL write a `(state, action, verified_label)` triple to the commit ledger for
  **every** action that reaches execution — VERIFIED, UNVERIFIED and FAILED alike.
- AC2: WHEN `verified_label == "VERIFIED"` THEN THE SYSTEM SHALL mark the step eligible for
  crystallization and hit-scoring — reward-adjacent consequences gated on VERIFIED **only**.
- AC3: WHEN `verified_label == "UNVERIFIED"` THEN THE SYSTEM SHALL apply partial credit
  (+0.02 edge score), SHALL NOT crystallize, and SHALL permit at most one re-propose before
  accepting.
- AC4: WHEN `verified_label == "FAILED"` THEN THE SYSTEM SHALL apply miss-scoring (−0.08 edge delta)
  and SHALL generate a tier-3 failure header (AVOID source) from the outcome.
- AC5: IF the commit ledger write fails THEN THE SYSTEM SHALL log at debug level and SHALL NOT crash
  the step.

**Edge Cases:**
- Vetoed action, never executed → **no commit row.** Honest, not a lie.
- Reasoning-only step (`tool=None`) → still writes a row with `action="reasoning"`.
- Ledger DB unavailable → step continues, debug log only.

---

### REQ-2: The compound acceptance gate is three live measurements

**User Story:** As the coach process I want to accept a tuned constant only when it is genuinely
better, so I cannot reward-hack myself by tuning the metric I measure.

**Verified:** REAL GAP — see the Introduction table. One guard live, two structurally dead.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL evaluate every proposed constant change on a held-out batch **disjoint** from
  the inspiring batch.
- AC2: THE SYSTEM SHALL compute three held-out metrics: `natural_exit_rate`, `verified_fraction`,
  and `tokens_per_verified_step`.
- AC3: THE SYSTEM SHALL apply a proposed change **only if all three hold**: `natural_exit_rate`
  improves AND `verified_fraction` does not degrade AND `tokens_per_verified_step` does not degrade.
- AC4: THE SYSTEM SHALL record `tokens_total` at session exit from the session's **real accumulated
  LLM token count**, so `tokens_per_verified` has a non-zero input.
- AC5: THE SYSTEM SHALL compute `verified_fraction` as the actual ratio of VERIFIED steps to total
  executed steps for each held-out session, read from the `der_commits` ledger, and **SHALL NOT
  return a constant for any input**.
- AC6: WHERE a held-out session has zero executed steps THEN THE SYSTEM SHALL treat its
  `verified_fraction` as **neutral** — excluded from the mean rather than counted as 1.0 — so a
  fresh session neither penalizes nor inflates the guard.
- AC7: THE SYSTEM SHALL assert **by test** that each of the three guards can independently reject a
  proposal.

**Edge Cases:**
- Fewer than `held_out_count` sessions → tuner returns None; no proposal. Current behaviour.
- All held-out sessions already exit naturally → the conservative rule may consolidate, but must
  still pass the compound gate.
- Ledger missing a column → the guard reading it must report as **unavailable**, not silently pass.

---

### REQ-3: Per-domain gating

**User Story:** As the coach I want a constant to hold up in every domain it affects, so a change
that helps research and hurts coding is not accepted on a pooled average.

**Verified:** REAL GAP — `run_once` accepts and forwards a `domain`
([`outer_loop.py:184`](backend/agent/outer_loop.py:184)) but never iterates, and every production
caller passes `domain=None` ([`:261`](backend/agent/outer_loop.py:261)).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL apply the compound gate per domain for every domain with **≥2** held-out
  sessions.
- AC2: THE SYSTEM SHALL reject the proposal if the gate fails in **any** such domain.
- AC3: WHERE fewer than 2 sessions exist in every domain THEN THE SYSTEM SHALL fall back to the
  pooled compound gate, preserving current behaviour.
- AC4: THE SYSTEM SHALL make the per-domain outcome observable — which domains gated, which passed,
  which rejected.

**Edge Cases:**
- Domain column absent or empty → pooled gate (AC3), logged as such.
- One domain with 20 sessions and another with 2 → both gate; AC2 means the small one can veto.
- A domain present only in the inspiring batch → not gated; it is not held-out data.

---

### REQ-4: The "never split" hack is rejected by the gate

**User Story:** As the coach I want the reward-hack the gate names to be actually tested against it,
so the guard is proven rather than assumed.

**Verified:** REAL GAP — `U_SPLIT` candidates are `[0.4, 0.5, 0.6, 0.7]`
([`outer_loop.py:39`](backend/agent/outer_loop.py:39)). `1.0` cannot be proposed, so the hack is
prevented by omission, not rejection.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL include in `_PROPOSALS["U_SPLIT"]` a value constituting the "never split"
  hack — at or above the point where no split can occur.
- AC2: THE SYSTEM SHALL reject that proposal **via the compound gate**: it wins `natural_exit_rate`
  and loses `verified_fraction`.
- AC3: THE SYSTEM SHALL assert AC2 by behavioral test.

**Edge Cases:**
- Adding the hack value must not let it be accepted in any configuration — if a held-out batch is
  degenerate enough that it passes, that is a **finding about the batch**, not a reason to remove the
  candidate.
- Other tuned constants with an analogous degenerate extreme → same treatment where one exists.

---

### REQ-5: Explicit depth check on VERIFIED-but-shallow steps

**User Story:** As the reflection layer I want a verified step done too shallowly to be flagged, so
"verified but inadequate" does not pass silently.

**Verified:** Folded from the DER integrity audit (finding D).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL, on a VERIFIED step, run `TrailingDirector.analyze_gaps` when the step's
  measured depth (sub-step count / token investment) is below the expected depth for its task class.
- AC2: IF a gap is detected on a VERIFIED step THEN THE SYSTEM SHALL add a gap item to the queue via
  the same path as failure-triggered gaps.
- AC3: WHERE depth analysis is intentionally skipped for a task class THEN THE SYSTEM SHALL document
  that exclusion in code — no silent coverage loss.

**Edge Cases:**
- `TrailingDirector` unavailable → skip the check, debug log (current graceful no-op).
- Step already at max depth → no further split attempted.
- Semantic verification (Phase 4) raising the VERIFIED rate → **more** steps reach this check; the
  depth threshold must be validated against post-Phase-4 labels, not pre.

---

### REQ-6: Guard health is observable

**User Story:** As the tuner I want to see how many guards are actually live, so a dead guard is
visible rather than inferred from behaviour.

**Verified:** The debug endpoint already reports `live_guards` and lists dead guards — that is how
this gap was confirmed. It must go from 1 to 3.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL report the number of live guards and name any dead ones.
- AC2: THE SYSTEM SHALL report each held-out metric's computed value, not just pass/fail.
- AC3: THE SYSTEM SHALL log every accepted and rejected proposal with the three metric values and
  the deciding guard.
- AC4: THE SYSTEM SHALL report per-domain gate outcomes (REQ-3 AC4).
- AC5: THE SYSTEM SHALL treat a guard whose input is unavailable as **dead**, not as passing.

**Edge Cases:**
- No proposals yet → report the metrics as computed on the current baseline, not as absent.
- A metric that is legitimately constant across a homogeneous held-out set → observable via AC2, and
  flagged as low-signal rather than as a live guard.

---

## Non-Requirements (Out of Scope for Phase 6)

- **Changing DER band thresholds** (`0.8` / `0.3`). Phase 4 froze them; this phase consumes the
  labels they produce.
- **Changing the semantic scorer** → Phase 4.
- **Changing the displayed outcome** → Phase 2.
- **Adding new tuned constants.** This phase repairs the gate; it does not widen what is tuned.
- **Rewriting the Caducean `u`/`ξ` split physics.**
- **Budget or work-unit derivation** → Phase 1.

## Open Questions

- **OQ-1:** The expected-depth threshold per task class for REQ-5. Must be set from **post-Phase-4**
  labels — semantic verification raises the VERIFIED rate, so a threshold tuned on substring labels
  would be wrong on arrival.
- **OQ-2:** The exact "never split" value for REQ-4 AC1. It must be provably past the point where a
  split can occur, given `U_SPLIT`'s comparison.
- **OQ-3:** Whether `tokens_total` should count prompt tokens, completion tokens, or both. Both is
  the honest reading of "cost per verified step"; confirm against how `AVG_STEP_COST` is calibrated
  in Phase 1.

# Feasibility Audit: can each consumer ever be calibrated?

Produced 2026-10-08 (session 392) at the owner's request, after the probe proved
d1 grounds images and the owner asked which consumers are worth collecting at
all. Measured with `scripts/consumer_enforcement_report.py --json`.

## The headline

**Every labelled row in the store is labelled by the incumbent. There is not one
outcome label anywhere.**

| | |
|---|---|
| consumers reported | 19 |
| distinct labelled rows | 171 |
| rows labelled `incumbent` | **171 (100%)** |
| rows labelled by an outcome | **0** |
| consumers with declared sites but zero rows | **7** |

The seven with zero rows: `done`, `sufficient`, `escalate_incomplete`,
`needs_action`, `use_thinking`, `recovery_strategy`, `mode`.

## Why this is the whole problem

The bar's hardest clause is out-of-fold AUROC >= 0.65 - "does the confidence
rank the ERRORS". With an incumbent label, a row's "correct" means *the legacy
decider chose the same thing d1 chose*. That is a **parity** measurement, not a
correctness measurement. Two largely independent scorers disagree at close to
chance, so the observed AUROC sits at chance by construction.

`tool_choice` measures **0.5225**. That number is not evidence that d1 is bad at
choosing tools. It is evidence that **we have never measured whether d1 is bad
at choosing tools.** The two are indistinguishable until the label changes.

So the barrier to enforcement is not traffic, and it is not d1's quality. It is
that the label definition cannot support the question being asked.

## The owner's correction, and the axis it forces

The owner: *"each node/step is a tool call, so the class we have for correctness
might need to be another layer deep."*

Correct, and it is the key structural point. `DER_DAG.md` §4: a node is
`run_node`, a **loop of up to 12 tool calls**. So one "step" is not one
decision. There are three decision layers and they do not line up:

| Layer | What happens | Decision examples | Outcome that becomes observable |
|---|---|---|---|
| **L1 call** | one tool call inside the node loop | `tool_choice`, `click_safety`, `needs_action` | that call's own result: exit code, verification, `_node_failed_after_change` |
| **L2 node** | `run_node` returns; `_der_finalize_step` runs | `done`, `sufficient`, `depth_met`, `review_verdict`, `recovery_strategy`, `escalate_incomplete` | the node's `outcome`, `verified_fraction`, covered/blocked facts; for completion questions the **turn** outcome |
| **L3 turn** | loop ends, synthesis, run grade | `mode`, `web_intent`, `presentation`, `narration`, `depth_route`, `event_family`, `user_feedback` | contract met, run grade, TASK_DONE/FAIL, blocked facts |

**A decision's truth often lives one layer ABOVE the decision.** `done` is
decided at L2 but its truth ("was the task actually finished?") only exists at
L3, after the whole loop closes. This is why the user's instinct matters: a row
written at decision time **cannot be labelled at decision time**.

The mechanism that fixes it is **deferred labelling with a scope key**: write
the row PENDING with the scope it belongs to, and resolve it when that scope
closes. The scope is chosen **per consumer** to match where its truth lives.
This is AC6.3a and AC6.3b in the spec, promoted from "nice to have" to the
central mechanism.

## The list

Verdicts: **JOIN** (truth already exists in the data, only the join is missing)
· **REWIRE** (the site exists but no rows land - a wiring bug, not a usage
problem) · **SAMPLED** (truth exists only by trying) · **DROP** (no ground truth
exists; enforcement would be theatre).

| Consumer | Layer decided | Truth layer | Verdict | Note |
|---|---|---|---|---|
| `tool_choice` | L1 | L1 | **JOIN** | Highest value. The dispatched call's own outcome already labels it. Converts 57 parity rows into 57 truth rows and re-measures AUROC honestly. The 0.52 may be entirely a label artefact. |
| `review_verdict` | L2 | L2 | **JOIN** | 34 rows. The vetoed step's own `outcome`/verification is the truth, at the same layer. Second highest value. |
| `depth_route` | L2 | L2 | **REGISTER + JOIN** | Truth is literally recorded - `_der_note_depth_route(route)` names the route actually taken. Produces rows, is absent from `CONSUMERS`, so it is never counted. (spec T1.9) |
| `user_feedback` | L3 | L3 | **JOIN** | Truth IS the user's correction. Labelling from the incumbent instead is the bug. 3 rows. |
| `needs_action` | L1 | L1 | **REWIRE + JOIN** | "Does this goal need a tool?" Truth: did the node make a call. Cleanest truth signal in the system. Zero rows despite a declared site. |
| `sufficient` | L2 | L3 | **REWIRE + JOIN** | Truth = contract met / coverage C at turn end. Zero rows despite a declared site. |
| `done` | L2 | L3 | **REWIRE + JOIN** | Same. Zero rows despite declared sites in `monitor_shadow` and the kernel. |
| `call_closing` **(new, REQ-10)** | **L1, after a call that CLAIMED to close** | **L1, one iteration later** | **JOIN — exact and free, but MEASUREMENT-ONLY** | The closing rule at `node_executor.py:629` is exact: loop closed means the claim was right, loop continued means it was premature. Asked only about candidate closings, so cost is bounded by construction. **Permanent tier C (AC10.0):** never enforced, never sampled, and a contract test asserts `node_executor` never reads its answer. The owner's fear — the agent stopping early and abandoning the goal contract — is answered by three fences, not by naming. | |
| `recovery_strategy` | L2 | L2 | **REWIRE + JOIN** | Truth: did the step pass after the graft. Zero rows despite a declared site. |
| `escalate_incomplete` | L2 | L2 | **REWIRE + JOIN** | Truth: was the result actually incomplete (verification). Zero rows despite a declared site. |
| `depth_met` | L2 | L3 | **JOIN** | 19 rows. Truth = run grade + coverage at turn end. |
| `web_intent` | L3 | L3 | **JOIN (weak)** | Truth = did the task succeed after routing. Weak but real. 18 rows. |
| `event_family`, `event_type:*` | L3 | - | **DROP as enforcement** | They classify what already happened. The "truth" would be a human label. These are learning rows; they should never appear in an enforcement bar. 18 rows across 4 consumers. |
| `narration` | L3 | none | **DROP** | Nobody can say a narration was wrong. 19 rows. Observability only. |
| `presentation` | L3 | none | **DROP** | Same. 3 rows. |
| `mode` | L3 | none | **DROP** | No ground truth, zero rows, and deliberately not re-wired (locked in the previous spec). |
| `use_thinking` | L1 | none | **WEAK - needs an A/B** | "Did this need extended reasoning?" has no per-turn truth. The only honest measure is an A/B on task success. Zero rows. Do not collect until the A/B exists. |
| `click_safety` | L1 | by trying | **SAMPLED** | Only a real click reveals the danger. No data fix exists. Tier B, refuse direction only. |

### The short list

- **JOIN now, highest value:** `tool_choice`, `review_verdict`. Two consumers,
  91 rows, truth already in the data. This single change is what makes the
  AUROC measurement mean anything.
- **REWIRE:** five consumers have a declared site and produce nothing. That is a
  wiring bug, and it is why "run the app more" was the wrong remedy.
- **DROP or demote:** 6 consumers (26 rows) have no ground truth and cannot be
  enforced honestly.
- **SAMPLED:** 1 consumer.

## What this changes about the plan

1. **The method is not "collect rows".** It is "stop writing parity labels and
   start writing truth labels". The bar was never the problem; the label was.
2. **Replay is no longer the priority.** Replay multiplies *parity* rows, which
   is the thing that does not work. It stays useful only after the label is fixed.
3. **The A/B harness (AGENTS.md Mode A) is the honest instrument** for
   `use_thinking` and for proving the JOIN changes did not regress the product.
4. **Three consumers are structurally dead and should be deleted**, on the same
   precedent as `on_track` and `retry_same`: `browser_next` and `web_depth` (job
   assignments, no producer - spec T1.8) and, if the owner agrees, the DROP tier.

## Open item this audit cannot settle

Whether d1's state contains the information that decides each decision. The
JOIN fixes the *label*, which makes the measurement honest, but if the state is
blind the honest measurement will be low. `tool_choice` is the known case
(candidate_cap 6, veto applied upstream at menu build), and the JOIN will answer
it definitively rather than leaving 0.52 on the table as an open question.
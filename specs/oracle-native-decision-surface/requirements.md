# Requirements: Oracle Native Decision Surface (d1 shapes, honoured state, honest rows)

Source work order: owner, 2026-10-08, session 392. Evidence: PiN
`pin_7b9965d6932b` (the probe result and its correction of `pin_513ce49156d3b`).

## PROBE RESULTS (2026-10-08, `scripts/probe_spec_claims.py`) — read before Wave 0

Three load-bearing claims were measured before any code was written. Two hold.
One does not, and it changes REQ-5.

**P1 STABILITY — PASS.** Four consumers, five identical calls each:
`tool_choice`, `review_verdict`, `done`, `click_safety` all returned **1 distinct
answer, max probability spread 0.0000**. Reversal rate **0/4**. d1 is
deterministic at temperature 0 on our states, so confidence can rank
observations and the banded-accuracy diagnostic (AC13.6) is sound. The published
3.25-11.14% reversal figures do **not** apply here.

**P2 LABEL JOIN — PASS, WITH A NUMBER THAT CHANGES THE TIMELINE.** Over the last
4000 ledger events: **192 dispatched (outcome-bearing) = 4.8%**; 3057
incumbent-only; 751 without a decision payload. So the join is possible —
`tool_choice` (742 rows), `review_verdict` (466) and `depth_route` (45) all have
dispatched rows. **But truth is ~5% of traffic.** The bar wants 100 *distinct
true* rows per consumer, so a JOINable consumer needs on the order of **2000
relevant turns, not 100**. This is a 20x multiplier on the volume problem and it
must be stated in every schedule. Replay (AC7.6) does not help here: a replayed
turn carries its recorded incumbent outcome, not a fresh one.

**P3 REAL SCREEN — FAIL, and it narrows REQ-5.** A real 768x432 screenshot, split
into 3x2 = 6 positional cells (matching `candidate_cap` 6), with ground truth
**computed from the pixels**: detail by standard deviation, brightness by mean.

| question | gold | got | confidence |
|---|---|---|---|
| most detail | A | A | 0.28 |
| darkest | E | C | 0.39 |
| brightest | A | E | 0.25 |

**1 of 3.** Chance on six options is 17%. The earlier synthetic result (3/3 at
0.95-1.00 on 1/2/3 coloured circles) was **too easy and does not transfer**.

Two things this does and does not mean:
- **It does NOT mean d1 is confidently wrong.** Confidence stayed at 0.25-0.39 on
  the misses. That is the safe failure mode: the model is uncertain, and it says
  so. Confidently-wrong grounding would be the dangerous outcome.
- **It DOES mean coarse POSITIONAL cells are not enough.** The candidate list
  carried only position ("the top-left region"), so d1 had to do all the work
  from raw pixels and answer a *global image-statistics* question, which is a
  computation rather than a perception. The working synthetic probe asked a
  *semantic* question ("which panel shows the word ZEPHYR") over candidates the
  model could match against content.

  **Therefore REQ-5 is narrowed:** an image-grounded consumer's candidate list
  must carry **semantic content per candidate** (an element's name, role or
  label), not just its position. This is also what the published indexed-element
  pattern does. Screen *grounding for clicking* is NOT proven by P3 and is not
  in scope for this spec; REQ-5 ships only what `click_safety` needs, which is a
  yes/no safety question about one named action, not a locate-the-pixel task.

## Decisions Locked

- **The owner was right and the earlier negative was a probe bug.** d1-3B reads
  images. Measured live on `:8082` with the route proven (`prompt_tokens`
  300-302 with an image vs 46-48 without, +252 image tokens):
  LiquidAI's published schema scored **3/3 at confidence 0.95-1.00** on 1/2/3
  shapes, and the permutation test (question byte-identical, only the image
  moves) answered **A, B, C against gold A, B, C at 0.988-0.992**.
- **NO SECOND VISION MODEL.** d1 is the only vision model. This spec must not
  add one, must not add a second VL endpoint, and must not reintroduce the
  retired LFM2.5-VL pair.
- **The readout changes.** The A/B/C letter menu on `/completion` is replaced
  by LiquidAI's native named-criteria shape on `/v1/chat/completions` for every
  consumer that carries a decision type. This is the root fix; the residual
  defect it removes is that the letter shape collapses to a constant answer
  when the question text varies, while reporting high confidence.
- **Rows reset.** The readout is part of the decision identity (oracle.md §2,
  §16, REQ-22/25). Every row collected under the letter readout becomes
  `other_backend`. This is the rule working, not data loss. Today that is
  `tool_choice` 57 distinct / 65 raw, `review_verdict` 34, `web_intent` 18,
  `presentation` 3, `user_feedback` 3, and four consumers at 0.
- **Nothing is weakened.** The hardened bar (`consumer_bar.py`) keeps every
  clause. No clause is relaxed, rounded, or re-tuned to obtain a flip. The bar
  is what exposed `tool_choice` AUROC 0.5225; weakening it would destroy the
  only instrument we have.
- **`tool_choice` AUROC 0.5225 is NOT invalidated by this spec.** That consumer
  is text-only and the V1 probe validated the letter readout for text at 98.7%.
  The readout defect is specific to image-grounded consumers. Do not claim the
  reset "fixes" that number.

## The owner's constraint, stated as a requirement

The owner (2026-10-08): *"i dont want to lose the job routing functionality and
all the capabilities the oracle had ... it works with phase domains for
concurrency with jobs and decisions, theres a lot there that i dont think we
should have to eliminate or regress. d1 is faster and has vision."*

Therefore **REQ-9 (Preservation) is load-bearing and is verified by its own
gate.** This spec ADDS a decision surface. It does not replace the engine, the
job routing, the phase domain, the consumer registry, or the bar. Any wave that
removes or degrades one of those is a failed wave, not a simplification.

## Introduction

The Oracle drives d1 as if d1 were a chat model. It sends an instruction
string and a letter menu to `/completion`, pools log probabilities per letter,
and does one HTTP round trip per consumer per turn. d1 is not a chat model. Its
published API is `system_one(state, questions, images=None)`: a state is read
once, a set of typed questions is answered over it in one forward pass with zero
output tokens, and the answer is a typed value (`noul` / `choice` / `score`)
with calibrated probabilities.

Six consequences follow, and they are the requirements below.

### Success criteria

- Every consumer with a declared decision type is scored through the native
  named-criteria shape, and the readout is keyed by option NAME.
- The engine reads the fields its job declares. A job whose declared fields are
  `("coverage","open_facts","depth_met","grade","goal")` produces a state in
  which all five appear.
- A calibrated threshold cannot survive a change of readout or of criteria.
- A consumer can acquire honest, outcome-labelled rows without a human driving
  the app.
- The job routing, the phase domain, the consumer registry, and every consumer
  in `CONSUMERS` are intact and measurably unchanged after the spec.

## Requirements

### REQ-0(gate): Pre-implementation verifications

- **AC0.1** Re-run `scripts/probe_d1_image_grounding.py --mode native` and
  `--mode backend` against the live server and pin both outputs. Native must
  score 3/3; the backend permutation test must return `follows=True`. A native
  regression stops the spec and is reported, not engineered around.
- **AC0.2** Record the pre-change baseline: `python
  scripts/consumer_enforcement_report.py --json` output, per-consumer distinct
  and raw counts, and the `benchmarks/consumer_bar_record.json` contents. No
  wave may claim a regression it cannot compare.
- **AC0.3** Record `d1` identity (`model_id`), the served routes that answer
  (`/completion`, `/v1/chat/completions`), and whether `/v1/chat/completions`
  returns `completion_probabilities` or the OpenAI `logprobs` shape. **The
  readout MUST read `id`, never `bytes[0]`.** A `bytes[0]` read yields a
  character code (116 == "t") and silently voids every measurement; this was a
  real defect in the probe and is the reason AC0.3 exists.
- **AC0.4** Pin the current job-routing surface: `ORACLE_JOBS`, `CONSUMER_JOBS`,
  `oracle_job()`, `job_input()`, and the two CT-DE-7 enumeration tests. These
  are the REQ-9 contract.

### REQ-1 (readout): Native named criteria replace the letter menu

- **AC1.1** `decision_backend_d1` scores through `/v1/chat/completions` with the
  image-capable message shape. `DecisionScore`, `CandidateScore`, and the
  engine's `noul()` unwrapping keep their exact current shapes - the envelope
  is a contract (CT-DE-1) and does not change.
- **AC1.2** A `choice` question renders LiquidAI's criteria block: a mapping of
  `name -> description`. The readout pools over the NAME tokens, and
  `CandidateScore.name` carries the name.
- **AC1.3** A `noul` question renders the yes/no instruction and pools over the
  yes/no token forms. `yes` is normalised to `true` wherever the caller ordered
  its options otherwise (the current behaviour at
  `decision_backend_d1.py:386-390` is preserved).
- **AC1.4** The letter menu is **retired from scoring**. A fallback that scores
  through letters is not permitted; a failure to score returns `None` and the
  consumer fails closed, exactly as today.
- **AC1.5** Every text consumer's rows collected under the letter readout remain
  in the ledger and are reported as `other_backend`. They are **never deleted**.
- **AC1.6** A consumer with no declared type scores nothing (`None`). It does
  not inherit another consumer's shape and it does not borrow a generic one.

### REQ-2 (identity): The decision identity includes the readout and the criteria

- **AC2.1** The identity key is `model_id + readout_mode + criteria_hash`, where
  `criteria_hash` is a stable digest of the rendered criteria block. It replaces
  the current model-file-only key (`_current_backend_identity()`,
  `decision_engine.py:432`).
- **AC2.2** `threshold_for()` resolves `None` when the active identity has no
  entry. Fail-closed is preserved and remains the default (oracle.md §5).
- **AC2.3** `superseded_flips()` treats a readout or criteria change as a
  superseded configuration, so a flip measured under the letter readout cannot
  stand.
- **AC2.4** A consumer whose criteria text changes is re-identified. Editing an
  instruction is a new identity, per oracle.md §19.3.6 - the existing rule,
  now actually enforceable because the criteria are addressable.

### REQ-3 (state): The engine builds the state, and the backend reads all of it

- **AC3.1** `job_input()` renders the job's declared `fields` in the declared
  order into ONE state. The state is a structured object, not a goal string.
- **AC3.2** `decision_backend_d1` stops reading only `frame["goal"]`
  (`decision_backend_d1.py:360`). It reads the rendered state. A job that
  declares five fields produces a state containing all five.
- **AC3.3** Reference fields (`incumbent_route`, `brain_*`, any field carrying
  the answer) are **never** placed in the state. A row whose input carries its
  own answer measures nothing (oracle.md §19).
- **AC3.4** The job's `budget_ids` continues to cap the rendered text. The cap
  is applied by the backend, logged when it trims, and never silent.
- **AC3.5** A contract test pins, per job, that every declared field appears in
  the rendered state and that no reference field appears.

### REQ-4 (types): The decision type is declared, not inferred

- **AC4.1** `ConsumerSpec` gains a `decision_type` field, one of `noul`,
  `choice`, `score`. It is **required**, not defaulted: a consumer without one
  scores nothing (AC1.6).
- **AC4.2** `ConsumerSpec.criteria` stops being a `bool`
  (`decision_engine.py:209`). It carries the `name -> description` mapping for
  `choice`, the yes/no statement for `noul`, and the ordered level descriptions
  for `score`.
- **AC4.3** The heuristic at `decision_backend_d1.py:376-379`
  (`len(opts) == 2 and opts <= {yes,no}`) is **deleted**. Type comes from the
  declaration.
- **AC4.4** Every consumer currently in `CONSUMERS` plus `event_oracle`'s
  `event_family` / `event_type:*` / `user_feedback` / `click_safety` is given a
  type and criteria in the SAME change that starts relying on it. The three
  consumers documented as noul (`sufficient`, `done`, `depth_met`, oracle.md
  AC14.6) are declared noul.
- **AC4.5** `score` is declared for consumers whose answer is an ordered level,
  and pools over the level tokens in order. It is not required to be used by
  this spec, but the type must exist in the schema and in the renderer.

### REQ-5 (images): The frame can carry an image

- **AC5.1** The frame gains an `images` field. A consumer whose job declares an
  image reads it; a consumer whose job declares none never receives one.
- **AC5.2** `click_safety` is the first image consumer, because its question is
  visual by construction. It keeps its rules -> judge -> escalation ladder and
  its existing shadow row sink unchanged.
- **AC5.3** Image capture for a consumer goes through the session-scoped
  screenshot (`session_vision_adapter.py:71` is absolute:
  `screenshot_to_bytes` is ALWAYS the browser session's screenshot). The
  module-level OS capture is not used for a consumer input.
- **AC5.4** **The framing ratio is fixed in this spec's scope**: the capture
  layer must return the scale factor between image pixels and screen pixels and
  must not discard it (`vision/screen_capture.py:142` computes `ratio` and
  drops it). Any consumer that maps an image-space point to a screen pixel
  depends on this value. `ScreenCapture.capture_base64`'s signature change is
  additive - existing callers keep working.
- **AC5.5** No display-scaling (DPR) assumption is introduced. Physical pixels
  are what mss returns; the returned scale factor is the only translation
  source, and it is measured, not guessed.

### REQ-6 (rows): A sampled rung, so rows can be earned without a human

- **AC6.1** `consumer_bar.ConsumerBar.status` gains a third value, `sampled`,
  between `shadow` and `enforced`. `derive_status` returns it under stated
  conditions; it is never inferred from a partial measurement.
- **AC6.2** A `sampled` consumer DECIDES on a bounded fraction of consults, and
  only where the decision is cheap and reversible. The incumbent remains the
  fallback for every other consult.
- **AC6.3** A `sampled` row is labelled by **outcome**, not by the incumbent.
   This is the only mechanism in the system that can break the label ceiling
   (oracle.md §0.7, B1). A shadow row's label is the incumbent's result, so
  shadow can only ever show agreement.
- **AC6.4** The sampled fraction is a named constant with a stated default and a
  kill switch. It is never tuned upward by a measurement that does not include
  the outcome labels.
- **AC6.5** The four zero-row consumers (`needs_action`, `recovery_strategy`,
  `sufficient`, `use_thinking`) must acquire a live consult site or be
  declared dead. A consumer nothing consults is a calibration line that can
  never move - the same reasoning that removed `on_track` and `retry_same`
  (2026-10-05, Wave 4 T4.5) applies here.
- **AC6.3a** **The join key exists; this spec carries it.** Verified 2026-10-08:
  `turn_id` appears 198 times in `agent_kernel.py` and is available on the
  instance (`self._current_turn_id`); the gateway passes `turn_id` with the
  conversation id at turn entry (DER_DAG §1). The Wave 3 finding "the ledger
  lacks a turn column" is true only of the ROW, not of the turn - the id is
  present at every consult site and is simply not carried into the Oracle row
  payload. The row payload gains `turn_id` and `step_id` (`QueueItem.step_id`,
  DER_DAG §8).
- **AC6.3a-1 (RIDGE — the dedup eats rows before they can be joined).**
  `tool_bridge.record_decision` dedups SHADOW rows at write time on
  `(consumer_id, engine, confidence, chosen, brain_choice|brain_bool)`
  (`tool_bridge.py:2649-2657`) — **no `turn_id`, no `step_id`**. Two different
  turns that score identically collapse to one row. The Wave 3 B6 fix (10,541 of
  18,467 rows were repeats) made this correct for the OLD goal (keep the store
  distinct-only) and **fatal for the NEW goal** (join each row to its own turn's
  outcome): a row can be dropped before its outcome exists, so the join has
  nothing to attach to and the survivors are a **biased subset** — only the turns
  that happened to score uniquely.

  Two sanctioned fixes; the wave picks ONE and pins it:
  (a) add `turn_id` + `step_id` to the dedup key — distinct turns stay distinct,
  at the cost of a larger store; or
  (b) move dedup to AFTER outcome labelling, so the key is built on the joined
  row — cheaper store, one extra pass.

  Either way the wave reports the store-size effect. **Doing neither silently
  caps every JOIN at a biased subset, which would make this spec's central
  measurement a lie.** This is the single most dangerous unlisted edge case found
  in review.
- **AC6.3b** **The outcome labels exist and are outside evidence.** At turn end
  (DER_DAG §6) the system already computes: whether the goal contract was met
  (a boolean), the run grade (`_der_report_run_grade`, from coverage C), task
  done or task fail, and the blocked-facts list. These are facts about what
  happened, not the incumbent's opinion - exactly what the label ceiling
  forbids shadow rows from producing.
- **AC6.6 (sampling policy — TWO gates, both must pass).** A consumer may only be
  sampled if it clears BOTH axes. Neither alone is sufficient, and they answer
  different questions:

  **Gate 1 — REVERSIBILITY (is a wrong answer survivable?).** The published
  decision-model engineering ladder:
  - **L1 read-only** — search, classify, rerank, delivery shape. Automate after
    validation. A wrong answer costs a little quality.
  - **L2 reversible** — truncate context, create temporary records, write a
    temporary file. Retain conservatively.
  - **L3 irreversible** — deletion, charges, access removal, writing project
    files. **Never delegate to a decision model alone.**

  **Gate 2 — GROUND TRUTH (can the answer ever be labelled?).** If no outcome
  signal exists, reversibility is irrelevant: a safely-reversible decision that
  cannot be labelled can never earn enforcement, only observation. Gate 2 is what
  `FEASIBILITY.md` audits per consumer.

  | consumer | Gate 1 reversibility | Gate 2 truth | outcome |
  |---|---|---|---|
  | `use_thinking`, `presentation` | L1 | L1: no ground truth | observation only (Gate 2 fails) |
  | continuation gate | L1 | turn outcome | **samplable** |
  | `click_safety`, `review_verdict` | refuse direction only | only by trying | **sampled, refuse direction** |
  | `done`, `sufficient`, `depth_met` | L2 | turn outcome | JOIN only, **never sampled** |
  | `needs_action`, `recovery_strategy`, `escalate_incomplete` | L2 | node outcome | **samplable** |
  | `call_closing` | L1 | exact, same-layer (AC10.4) | **measurement only, permanently** |
  | `tool_choice` | **L3** | call outcome | JOIN only, **never sampled** |
  | `mode` | L2 | none | **DROP** |
  | `narration`, `presentation`, `event_family`, `event_type:*` | L1 | **none** | **DROP as enforcement** (Gate 2) |

  Note the two corrections this makes to the first draft of this table:
  `presentation` and `narration` are **L1, the safest tier on Gate 1** — they were
  not "unsafe", they have **no ground truth**, which is a Gate 2 failure. And
  `tool_choice` is **L3 irreversible**, which is a stronger reason to keep it in
  shadow than "it writes files" implied. "Confidence is not a safety proof"
  (published decision-model guidance) is why both gates are required.

- **AC6.6b** A consumer with no reversibility tier cannot be sampled, and neither
  can a consumer with no ground truth. Neither gate has a default.

### REQ-7 (throughput): Per-job batching — one run, one STATE

**Owner decision, 2026-10-08: batching is adopted.** This SUPERSEDES the pinned
`one question per run` rule (REQ-20, oracle.md §9) in its LETTER, while
preserving its INTENT. Say so plainly in the commit: §9 becomes "each run stays
one STATE, answering that state's questions". The intent — one coherent decision
event per admission, and a participant angle that stays interpretable — is
kept, because a job already *is* a state definition.

**Why it is safe at all, and why it was deferred first.** The conflict is a unit
mismatch: d1 batches over the STATE, the dial admits by the QUESTION. The
resolution is that `ORACLE_JOBS` already groups consumers that share a state —
`judge_goal` carries `done`/`depth_met`/`sufficient` on one field list, `guard`
carries `click_safety`/`needs_action`/`use_thinking`, `interpret` carries
`mode`/`web_intent`/`user_feedback`. A job is already one participant on the
dial. So the batch is not a new grouping; it is the existing one, used
honestly.

- **AC7.1 (the unit change).** One admitted run = one **state** = one forward
  pass carrying that state's current questions. The dial's participant remains
  the JOB. Never batch across jobs — two jobs read different fields, so they are
  different states, and merging them would break the participant model.
- **AC7.2 (consulted-only — owner decision).** A run carries **only the
  consumers actually consulted on this turn**, never a job's full declared set.
  Carrying unconsulted consumers was rejected: it manufactures rows for
  questions nobody asked, which is noise, and it inflates run size with work
  that does not correspond to a real decision. Consequence accepted: the run
  size varies per turn (0, 1, or 3 questions), so the angle's dwell time varies.
  AC7.3 is what absorbs that.
- **AC7.3 (load counts questions, not runs).** The Decision domain's load signal
  must count **questions in flight**, not runs. Otherwise a three-question run
  occupies three times the CPU for one admission and is admitted three times too
  often. With questions counted, admission rate tracks real CPU work and a
  three-consumer job is admitted a third as often — fair by the work performed.
  This is a semantic change to the load function and is the single most
  important line in this requirement.
- **AC7.4 (the method is deliberately NOT fixed).** How the group is formed, what
  the cap is, and whether a single-question run degenerates to the unbatched
  path are all left **configurable and measured**, not decided here. The owner
  (2026-10-08): *"lets not be deterministic on the method of batching... once we
  test it we will see the data to decide."* Two runs that produce different
  groupings must be comparable afterwards, so each row records the grouping it
  came from.
- **AC7.5 (per-question isolation — new risk, must be pinned).** Two contract
  tests, because batching creates failure modes a single-question call cannot
  have:
  1. **Criteria isolation.** Consumer A's criteria must never appear in consumer
     B's question within one batched pass. A leak here silently corrupts
     calibration and no single-question test could catch it.
  2. **Failure isolation.** One malformed consumer must not fail its
     neighbours. Decide and pin which: the whole batch fails closed (`None` for
     every member, safe but starving), or the render is separable and only the
     malformed member returns `None`. Either is acceptable; silently mixing them
     is not.
- **AC7.6 (rows produced before REQ-6's JOIN are parity rows).** Batching makes
  rows cheaper. It does not make them **true**. Until the label join lands, a
  batched row is still incumbent-labelled and must not be counted toward any
  bar. Stated here so the two changes are never confused.
- **AC7.7 (the phase-domain gate is not waived).** Batching ships only with the
  measurement attached: participant count, dial behaviour, decisions/s, and
  reply latency before and after. **The Bench P3 result (273/273 identical) and
  the live gate P4 (coding 15/15, research 8/8) measured the unbatched
  semantics and are INVALIDATED by this change** — they must be re-taken, not
  cited. A batching wave that does not re-measure the dial does not ship.
- **AC7.8 (no turn merging).** Batching must never merge the questions of two
  different turns, and one consumer's admission must not delay another's reply
  path.

### REQ-8 (verification): Every wave is measured on the real backend

- **AC8.1** Each wave runs the Oracle contract suite
  (`backend/tests/contract/test_decision_engine_contract.py`,
  `test_bar_record_enforcement.py`, `test_oracle_jobs_contract.py`,
  `test_click_safety_contract.py`) plus the enumeration tests touched.
- **AC8.2** Each wave runs `scripts/consumer_enforcement_report.py` and states
  per-consumer distinct counts before and after. A wave that changes no count
  and claims a calibration effect is a failed wave.
- **AC8.3** Each wave runs at least one live eval through `evals/run_evals.py`
  and reports pass count plus `reply_s`. No standards regression is accepted.
- **AC8.4** Where a change resets rows, the reset is reported in the wave notes
  with the counts, and the pin says so.

### REQ-9 (preservation): Nothing is eliminated or regressed

This is the owner's explicit constraint. **It is a clause with named, enumerated
exceptions** — found in review 2026-10-08, when three of this spec's own tasks
turned out to contradict it. The exceptions are listed here rather than left
implicit, because a preservation clause that silently contradicts the work order
is worse than no clause.

- **AC9.1** `ORACLE_JOBS` (8 jobs), `oracle_job()` and `job_input()` keep their
  names, members and budgets. **`CONSUMER_JOBS` keeps 17 of its 19 entries and
  all 8 job names.** `CT-DE-7` (`test_consumers_and_counters`) asserts
  `set(de.CONSUMERS) == {...}` — EXACT set equality — so it **must** be updated
  as an explicit STALE-BY-SPEC change, in the SAME commit as the change it
  tracks, and the diff must show only the intended additions.

  **Sanctioned exceptions to AC9.1, and nothing beyond these three:**
  1. `browser_next` and `web_depth` are **removed** from `CONSUMER_JOBS`
     (T1.8). Verified 2026-10-08: they have job assignments and **no call site
     anywhere in the backend** — the same class as `on_track` and `retry_same`,
     both deleted for exactly that reason. 19 entries → 17.
  2. `depth_route` is **added to `CONSUMERS`** (T1.9). Verified: five live
     kernel call sites via `_der_note_depth_route` plus the writer at
     `tool_decision.py:2720`, but absent from `CONSUMERS`, so its rows were
     never reported and it could never be calibrated.
  3. `call_closing` is **added to `CONSUMERS`** (T1.10), permanently
     non-enforceable and never sampled (AC10.0).
  4. The `guard` job's field list **gains an image declaration** (AC5.2) so
     `click_safety` can receive a screenshot. Its text fields are unchanged.

  Any other change to `ORACLE_JOBS`, `CONSUMER_JOBS` or the CT-DE-7 enumerations
  is a **spec violation**, not an implementation choice.
- **AC9.2** Every consumer in `CONSUMERS` still exists and is still consulted at
  the same site, **plus the three sanctioned additions above**. The engine still
  builds the input; no call site builds its own.
- **AC9.3** The phase domain Decision layer keeps one dial, one position per
  job, exit-driven admission, and `IRIS_ORACLE_PHASE` / `IRIS_ORACLE_PHASE_EXIT`
  behaviour; the scheduling domain is untouched. **The ONE sanctioned change is
  the load signal counting questions instead of runs (AC7.3), which REQ-7's owner
  decision explicitly supersedes.** No other part of the dial changes.
- **AC9.4** The bar keeps all clauses: 100 distinct rows, precision 0.90, ECE
  0.05, both classes present, minority >= 5%, out-of-fold AUROC >= 0.65, a
  calibrated threshold with Wilson 95% lower bound >= 0.85 on >= 50 rows above
  it. No clause is added, removed or relaxed. **Adding the `sampled` status
  (AC6.1) is additive and removes no clause.**
- **AC9.5** No capability is traded away: d1's vision is ADDED, its speed is
  kept, and nothing that worked before this spec stops working after it. **The
  single sanctioned reduction is AC7.1: the letter reading of oracle.md §9's
  "one question per run" becomes "one state per run", by owner decision.** It is
  named here so it is not discovered later as an unexplained regression.
- **AC9.6** `scripts/validate_orphans.py` gains no new orphan. A module this
  spec orphans is removed or reconnected in the same wave.

### REQ-10 (per-call): `call_closing` — is this call the step's closing call?

Owner request 2026-10-08: *"we need a version of done after a tool call"*, with
the owner's stated fear: *"the agent stops its work early thinking its done and
not adhering to the goal contract... it messes up the DER-DAG."*

A node is `run_node`, a **loop of up to 12 tool calls** (DER_DAG §4), so one
"step" is not one decision. `done` is decided ONCE at L2; this consumer is
decided after EVERY call at L1.

**The name is deliberate and is a safety requirement.** It is `call_closing`,
NOT `step_satisfied`, NOT `done_at_call`, and never a loop-control verb. The
question is "is this the closing call of the step?" — an assessment of one call,
which is exactly what the truth measures. It must never read as an instruction
to stop. `done` asks whether the TASK is finished; `call_closing` asks whether
one particular call was the last one.

- **AC10.0 (OWNER'S CONCERN, structurally answered — three independent fences).**
  The risk is real, and it is not hypothetical for `done`: `agent_kernel.py:20962`
  already passes `enforced=_done_dec` and `:20970` already writes the Oracle's
  answer into `data["done"]`, the bit the loop reads. So a consumer of this class
  CAN end a step early today. Fences:

  1. **It is MEASUREMENT-ONLY, permanently.** `call_closing` is added to the
     AC6.6 **tier C** list, which is a refusal, not a default. It is excluded
     from `oracle_acts()`, from every `enforced=` argument, from the sampled
     rung, and from threshold resolution. No flag, config value or later wave
     may enable it. If the measurement earns something, the RESULT is a number
     about the loop's closing rule — never a decision about stopping.
  2. **A contract test asserts the answer is never consumed.** No code path in
     `node_executor.py` may read `call_closing`'s `DecisionScore`, probability or
     `Noul` into the loop's continuation, the `max_calls` check, or the closing
     return at `:629`/`:648`. This test fails if anyone wires it. Naming is not
     the defence; this test is.
  3. **The goal contract is the existing backstop and is already stronger than
     this consumer.** `agent_kernel.py:20983-20989`: the turn shall not end while
     a required fact is open and unblocked, and a cover step is requested
     instead of honouring the claim. `call_closing` sits below that veto and can
     never reach it.

- **AC10.1** A new noul consumer `call_closing` ("is this the closing call of
  this step?"). It does **NOT** reuse or repurpose `done`, which asks whether
  the TASK is finished at the turn layer. Each decision point needs its own scope
  key; that is the mechanism REQ-6 depends on.
- **AC10.2** **Scope it to candidate closings only.** It is asked ONLY about calls
  where the model claimed `step_done=true` (or wrote a status line) — never about
  every call. Most calls make no such claim, so this is a small fraction of the
  loop. Three consequences, all intended: the GPU cost is bounded by construction
  rather than by hope; the premature-close risk is exactly the subset being
  measured; and the name stays honest, because only candidates are asked.
  Non-claiming calls are counted, never silently dropped.
- **AC10.3** The decision is taken after the claiming call returns, inside the
  node loop, with the goal, the call and the call's result in the state.
- **AC10.4** **The truth is the closing rule and it is exact.**
  `node_executor.py:629` returns `NodeResult(True, ...)` from inside the loop
  only when `not batch_failed and not batch_changed and (batch_done or
  _STATUS.search(text))`. So the label is: **the loop closed after this call ->
  the claim was correct; the loop continued -> it was premature.** Resolved one
  iteration later, same layer, no rollup and no turn-end wait.
- **AC10.5** **A call that changed a file is EXCLUDED from the question.** Such a
  call can never close the step even when the model claims done - the rule added
  2026-10-02 after a small model closed a step with a buggy method nobody ran
  (`node_executor.py:625-628`). On those calls the claim is POLICY, not
  judgement; asking d1 about them teaches a rule the system already enforces and
  makes the measurement meaningless. Excluded rows are counted, never silently
  dropped.
- **AC10.6** The score runs on the `oracle_shadow` lane, deferred. It is **never
  inline**: `surface_shadow.py:225-227` measured inline shadow scoring at
  **326-561 ms per turn each**, for rows nothing on the reply path reads. The
  reply must not wait for it. AC10.2 bounds the call count; this bounds the
  placement.
- **AC10.7** `call_closing` gets its own job in `ORACLE_JOBS` and its own entry in
  `CONSUMER_JOBS`. Existing jobs and entries are unchanged (AC9.1).
- **AC10.8** Per REQ-4 it is declared with a type and criteria in the SAME change
  (Wave 1), and it joins on `turn_id` + `step_id` + the call ordinal (Wave 5).
- **AC10.9** **The reply path and the DAG are unchanged, and this is proven, not
  assumed.** A live eval must show identical pass counts, no standards
  regression, and no change to `reply_s` beyond the declared noise. The only
  permitted effect is added rows.

### REQ-11 (deferred): a "positive call" consumer is NOT built yet

- **AC11.1** No per-call usefulness truth exists today, so a "did this call help"
  consumer would be another parity row. Verified 2026-10-08: `NodeResult.helped`
  is NOT a usefulness signal - it is the reason the Brain helper role took over
  (`node_executor.py:208`, `:434`). The three candidate truths each fail: a later
  verification exists only for changing calls and lands at L2; `repeats` is
  partial; coverage is computed once per step, not per call.
- **AC11.2** Therefore this consumer is out of scope until a usefulness signal is
  defined and measured. Recording parity rows under a name that promises
  usefulness would be exactly the kind of pseudo-evidence the bar exists to
  reject. It ships after REQ-10, and only if a real signal exists.

### REQ-13 (edge cases found in review, 2026-10-08)

Every item here was a gap: a place where the spec previously said nothing and a
wave would have had to improvise. Improvising at these points is how a
measurement silently becomes a lie.

- **AC13.1 `capture_base64`'s return is NOT additive.** It returns a 2-tuple
  `(b64, is_new)` and **three callers unpack it** (`tool_bridge.py:551`,
  `screen_monitor.py:185`, `:189`). Appending a third element breaks all three at
  once. Sanctioned: add a **separate** method or a small result dataclass
  (`CapturedFrame(png, is_new, scale, origin)`) and leave the 2-tuple intact.
  Whichever is chosen, a test drives all three existing callers unchanged.
- **AC13.2 `call_closing` has no bar and therefore no defined success.** It is
  permanently tier C, so it can never be enforced — which means the enforcement
  bar does not apply to it and "reach the bar" is not a goal it could ever meet.
  Its success criterion is stated instead: **report the premature-close rate and
  the rate at which d1's P(false) would have caught it.** A wave that ships
  `call_closing` without that number has shipped nothing.
- **AC13.3 `candidate_cap` belongs inside the identity.** The cap (currently 6,
  `decision_engine.py:1236`) changes the rendered criteria block, so it changes
  the `criteria_hash` (AC2.1). Changing the cap re-identifies every choice
  consumer, exactly as editing its criteria text does. State it in the identity
  definition so nobody "harmlessly" tunes the cap and keeps a stale flip.
- **AC13.4 the register functions are idempotent, so a stale spec never
  upgrades.** `register_surface_consumers()` and its siblings skip any consumer
  where `get_consumer_spec(cid) is not None`. After REQ-4 changes `ConsumerSpec`,
  an already-registered consumer would keep its OLD spec forever and the change
  would appear to work in tests (fresh registry) and not in production (warm
  registry). Sanctioned: the declaration wave **replaces** specs whose shape is
  pre-REQ-4, and a test registers a stale-shaped spec and asserts it is replaced.
- **AC13.5 dynamic consumers need an explicit rule.** `event_type:<family>` ids
  are generated at runtime by `event_oracle.register_consumers()` and are not in
  `CONSUMERS`. REQ-4 requires a declared type for every consumer, so the rule is:
  a dynamically created consumer inherits the **type and criteria of its family**
  (`event_family`), never a generic fallback (AC1.6), and an unknown family
  creates no consumer rather than an untyped one.
- **AC13.6 the single AUROC is replaced by banded accuracy.** A bare AUROC is what
  let `tool_choice`'s 0.5225 sit unexplained for a session. The diagnostic is
  **observed accuracy per confidence band**, per consumer, reported by
  `consumer_enforcement_report.py`. If accuracy does not rise with confidence the
  curve is flat, and **no threshold can ever work** — visible immediately, in
  bands, instead of after collecting a hundred rows. This is the diagnostic that
  makes the JOIN verdicts readable rather than merely honest.
- **AC13.7 stability is measured before it is assumed.** The published
  "JEV-as-a-Judge" work measured run-to-run reversal on repeated identical inputs
  at 3.25% on one benchmark and **11.14% on another**. Until d1's own reversal
  rate on our states is measured, an unknown share of the 171 rows may be noise
  rather than signal. Sanctioned: a probe in Wave 0 that issues N identical
  scores per consumer and reports the reversal rate. A rate high enough to
  swamp the confidence spread is a **stop-and-report** finding, not something to
  calibrate around.
- **AC13.8 `superseded_flips` only inspects enforced consumers.** It returns early
  unless `bar.flipped` (REQ-3 of `consumer_bar.py`). A `sampled` consumer is
  therefore never reported as superseded. Acceptable, but it must be **stated**,
  because a sampled consumer is live-ish and a config change should be visible.

### REQ-14 (label integrity under batching)

Owner, 2026-10-08: *"we will need to figure out how to make the row true through
testing and tuning when we batch."* This requirement is the answer, and it
**corrects REQ-10's original two-valued label**, which review found to be wrong.

- **AC14.1 (THE PRINCIPLE) A batch is a TRANSPORT unit, never a LABEL unit.**
  Batching saves a forward pass. It must not merge identity, timing or truth.
  Inside one batched pass, every question keeps its **own** scope key —
  `(turn_id, step_id, node_exec_id, call_ordinal, consumer_id)` — resolves at
  its **own** time, and receives its **own** label. Batch-mates routinely resolve
  at different moments in different orders: `call_closing` resolves one loop
  iteration later, `needs_action` when the node's next call does or does not
  happen, `tool_choice` when the call's own result is verified. **A batch is
  never written, labelled, deduplicated or counted as one row.** Any code that
  treats a batch as atomic is a defect, and a test asserts it cannot.
- **AC14.2 (CORRECTION — the label is N-valued, not boolean).** REQ-10 originally
  said two outcomes: loop closed → correct, loop continued → premature. Review
  against the code found **six** exits from the node loop, and four of them never
  adjudicate the claim at all:

  | exit | site | label |
  |---|---|---|
  | loop returns `NodeResult(True, ...)` — closing rule accepted the claim | `:648` | **CORRECT** |
  | another loop iteration follows | `:453` onward | **PREMATURE** |
  | call-limit break | `:652-653` | **UNTESTED** — the loop never judged it |
  | time-budget break, then a forced `STATUS` generate | `:657-658`, `:663` | **UNTESTED** — the loop never judged it; the later status is the same model grading itself with no fresh evidence |
  | exception | `:672-674` | **UNTESTED** |
  | repeat hand-over (`_MAX_REPEATS`) | `:521-528` | **UNTESTED** — the loop ends for a different reason |

  A split is decided at `_der_finalize_step`, **outside** the loop, so a split
  parent never closes and its rows are also **UNTESTED**.

  **UNTESTED rows are excluded from the fit and COUNTED, never dropped.** The
  untested rate is reported per consumer. A high untested rate is a **finding**
  — it means the label is mostly unavailable — not noise to be averaged away.
- **AC14.3 (`node_exec_id`, because a step can execute twice).** DER_DAG §3:
  `_der_start_node` runs `run_step` **with retry**. One logical step can
  therefore produce two node executions, and both write rows. Without a
  `node_exec_id` they collide on `(turn_id, step_id, call_ordinal)`. Pinned
  decision: the **final** execution is the truth; a superseded execution's rows
  are **UNTESTED** and counted. Without this, a retry silently double-counts or
  overwrites, and the store reports a confidence that two disagreeing executions
  produced.
- **AC14.4 (PENDING rows need a sweeper and a counter).** A deferred row is
  written PENDING and resolved when its scope closes. If the process dies, the
  turn aborts, or the lane drops the job, it never resolves. Sanctioned: a sweep
  marks aged PENDING rows as **abandoned** (a distinct, counted value), and the
  fit **never counts a PENDING row as either class**. A PENDING row counted as a
  negative is a fabricated observation.
- **AC14.5 (LABEL INTEGRITY is the tuning target — the answer to the owner's
  question).** New metric, reported per consumer and per grouping:

  ```
  label_integrity = (CORRECT + PREMATURE)
                    / (CORRECT + PREMATURE + UNTESTED + abandoned)
  ```

  This is what gets tuned when the grouping method is tuned (AC7.4). **TG-6 may
  not pass on latency alone:** a grouping that lowers label integrity is a net
  loss even if it is faster, because it buys cheaper rows that cannot be scored.
  Every grouping the wave tries is reported on BOTH axes — latency and integrity
  — so the choice is made from the pair, never from one.
- **AC14.6 (the mapping is PROVEN by fixture, not only observed live).** Live
  traffic can show a rate; only a constructed fixture can prove that an exit
  maps to the label it claims. Sanctioned: a fixture harness over the existing
  `scripts/gen_turn_replay_fixtures.py` / `scripts/replay_corpus.py` substrate,
  driving a node execution with a known call count and a known exit, asserting
  the resolved label. **One case per row of the AC14.2 table** — six cases — plus
  one for the retry case (AC14.3) and one for abandoned PENDING (AC14.4).

## Non-Requirements (Out of Scope)

- **No second vision model.** No LFM2.5-VL, no new endpoint, no new GGUF pair.
- **No click pipeline and no coordinate mapping.** Grounding is proven; the
  click path is a later spec. AC5.4 makes the scale factor available and stops
  there.
- **No refit of any existing threshold** and no flip. This spec changes the
  identity and empties the map; the next spec earns a threshold.
- **No change to the DER loop, the planner, or the Brain.** The Oracle advises;
  the planner remains the gate (oracle.md §15).
- **No re-wiring of `mode`** as a node-mode dependency (locked in the previous
  spec; do not "fix" it).
- **No second batch wave folded into a foundation wave** (see AC7.1).

## Open Questions

**Both prior questions are CLOSED (2026-10-08, from DER_DAG.md plus code
verification). They are recorded here because the answers shaped AC6.3a, AC6.3b
and AC6.6, and a reader must not have to re-derive them.**

1. ~~**The sampled rung needs an owner decision on blast radius.**~~ **CLOSED.**
   The answer is structural, not a matter of taste, and it is now TWO gates
   rather than one (AC6.6): **reversibility** (the L1/L2/L3 ladder) AND
   **ground truth** (can it ever be labelled?). `done` is JOIN-only because a
   false `done` ends the turn with work open — the worst failure the system has.
   `tool_choice` is JOIN-only because it is **L3 irreversible**. The
   continuation gate and `needs_action`/`recovery_strategy`/`escalate_incomplete`
   pass both and are the samplable set. No owner choice remains.
2. ~~**The turn key.**~~ **CLOSED, and it was never missing.** `turn_id` exists
   at every consult site (198 uses; `self._current_turn_id`; passed by the
   gateway), and turn end already produces genuine outcome signals - contract
   met, run grade, task done or fail, blocked facts. Wave 5 is therefore NOT
   blocked; it needs AC6.3a (carry the ids into the row) and AC6.3b (label from
   the turn-end outcome), both of which are ordinary work. The earlier claim in
   this spec that Wave 5 was blocked on a missing turn column was WRONG and is
   withdrawn.

## Still Open

3. **`score` consumers.** No current consumer is clearly an ordered level. If
   none is, the `score` type ships as schema-only (AC4.5) rather than as a
   fabricated use.
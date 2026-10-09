# Tasks: Oracle Native Decision Surface

Spec: `specs/oracle-native-decision-surface/` (`requirements.md`,
`design.md`). Verification record: `VERIFY.md`, created in Wave 0.

Every wave ends with **three checks that are not optional**: the contract suite
(AC8.1), the row-count before/after from `consumer_enforcement_report.py`
(AC8.2), and one live eval through `evals/run_evals.py` reporting pass count and
`reply_s` (AC8.3). A wave that changes no row count and claims a calibration
effect has failed.

Every wave also ends with **the REQ-9 preservation check**. It is a task, not a
remark: the enumeration tests pass unchanged, `validate_orphans.py` gains no
orphan, and the phase-domain flags are untouched.

## Wave 0 - Verifications and baselines (gate TG-0)

- **T0.1** Re-run both probes and pin the output (AC0.1).
  `python scripts/probe_d1_image_grounding.py --mode native` must score 3/3.
  `--mode backend` must report `answer follows the image: True`.
  A native regression STOPS the spec and is reported.
- **T0.2** Record the calibration baseline (AC0.2): the full
  `consumer_enforcement_report.py --json` output, per-consumer distinct and raw
  counts, and `benchmarks/consumer_bar_record.json`. Save as the Wave 0 section
  of `VERIFY.md`.
- **T0.3** Record the transport facts (AC0.3): `model_id`, which routes answer,
  and which logprob shape each returns. Pin the `id`-not-`bytes[0]` rule with a
  test that feeds both shapes and asserts the same token ids.
- **T0.4** Pin the job-routing surface as the REQ-9 contract (AC0.4):
  `ORACLE_JOBS` (8), `CONSUMER_JOBS` (19), `oracle_job()`, `job_input()`, and
  the two CT-DE-7 enumeration tests. These tests are the definition of "nothing
  was lost".
- **T0.5** Record the live eval baseline for the tasks later waves touch: pass
  count and `reply_s`. The machine must be quiet during every measurement.

**TG-0 green when:** both probes reproduce, all three baselines are written to
`VERIFY.md`, and the transport rule is pinned by a test.

## Wave 1 - Declared types and real criteria (gate TG-1)

Pure declaration change. The letter readout still serves; nothing scores
differently yet.

- **T1.1** Change `ConsumerSpec`: `criteria: bool` becomes the typed criteria
  value; add a required `decision_type` (REQ-4, AC4.2).
- **T1.2** Give every consumer in `CONSUMERS` a type and criteria (AC4.4).
  `sufficient`, `done` and `depth_met` are noul. `review_verdict` is a
  three-option choice with the quality bar in its criteria descriptions.
  `tool_choice`, `recovery_strategy` are choices over their real menus.
- **T1.3** Give `event_family`, `event_type:*`, `user_feedback` and
  `click_safety` a type and criteria in the same change (AC4.4).
- **T1.4** A consumer with no declared type scores nothing: no inherited shape,
  no generic fallback (AC1.6, AC4.1). Enforced by test.
- **T1.5** Add `score` to the schema and the renderer as schema-only
  (AC4.5). No consumer is promoted to `score` in this wave (Open Question 3).
- **T1.6** Delete the inference heuristic at `decision_backend_d1.py:376-379`
  (AC4.3) **after** T1.2/T1.3, so no consumer is ever undeclared.
- **T1.7** REQ-9 check: CT-DE-7 enumerations pass unchanged; no consumer lost.
- **T1.8 (dead routing, found 2026-10-08):** `browser_next` and `web_depth` have
  job assignments (`decision_engine.py:165`) and NO call site anywhere in the
  backend. They are declared jobs that nothing produces - the same class as
  `on_track` and `retry_same`, both removed for exactly that reason. Remove
  both assignments, or give each a real consult site. Removing them is the
  default; the spec does not invent a producer for them.
- **T1.9 (undeclared producer, found 2026-10-08):** `depth_route` HAS live call
  sites - `_der_note_depth_route` at five kernel sites (`cover_open_fact`,
  `bonus_ceiling`, `deepen`, `finalize`, `next_step`) plus the writer at
  `tool_decision.py:2720` - but it is **not in the `CONSUMERS` tuple**, so its
  rows are never reported and it can never be calibrated. Register it as a
  declared consumer with a type and criteria, or stop writing its rows. It is
  producing data nobody counts.
- **T1.10 (REQ-10):** declare `call_closing` — a noul asked after a tool call
  **that claimed to close the step**, not once per step and not after every call.
  Type, criteria, its own job in `ORACLE_JOBS`, its own entry in `CONSUMER_JOBS`
  (AC10.1, AC10.2, AC10.7). Declaration only in this wave; the consult and the
  join land in Wave 5. The name is a safety requirement: never a loop-control
  verb, never `step_satisfied`.
- **T1.11 (REQ-10 AC10.0 fence 1):** pin `call_closing` into the AC6.6 **tier C**
  refusal list permanently, and add a contract test that it is excluded from
  `oracle_acts()`, from every `enforced=` argument, and from threshold
  resolution. No flag or config may enable it.
- **T1.12 (REQ-10 AC10.0 fence 2):** **the fence that matters** — a contract test
  asserting that no code path in `node_executor.py` reads `call_closing`'s
  `DecisionScore` / `Noul` / probability into the loop's continuation, the
  `max_calls` check, or the closing return at `:629`/`:648`. This test fails if
  anyone wires it. Naming is not the defence; this test is.
- **T1.13 (REQ-10 AC10.5):** implement the changed-file exclusion now, as part of
  the declaration, so it is pinned before any row exists: a call whose batch
  changed a file is not a question d1 is asked, because `node_executor.py:629`
  already forbids it from closing. Excluded rows are counted, never dropped
  silently.
- **T1.14 (REQ-11):** record in the wave notes that a "positive call" consumer is
  deliberately NOT built, with the reason: `NodeResult.helped` is the Brain
  helper takeover reason, not a usefulness signal, and the three candidate truths
  each fail. This stops it being re-proposed.

**TG-1 green when:** every consumer has a type and criteria, the enumeration
tests pass unchanged, no row count moved, and the two dead job assignments and
the undeclared producer are resolved.

## Wave 2 - The native readout (gate TG-2)

The transport swap. This is where behaviour changes.

- **T2.1** Render through `/v1/chat/completions` with the image-capable message
  shape (AC1.1). `DecisionScore` and `CandidateScore` do not change.
- **T2.2** `choice`: render the criteria block, pool per NAME token,
  `CandidateScore.name` carries the name (AC1.2).
- **T2.3** `noul`: render the yes/no instruction, pool per yes/no form,
  normalise `true` first regardless of caller order - the current normalisation
  is preserved exactly (AC1.3).
- **T2.4** Parse BOTH logprob shapes; `id` is authoritative and `bytes[0]` is
  never used (AC0.3, design §5).
- **T2.5** Remove the letter scoring path (AC1.4). A failure to score returns
  `None` and the consumer fails closed, exactly as today.
- **T2.6** Re-run the native probe as a regression check: still 3/3 (AC0.1).
- **T2.7** Confirm the letter rows are still in the ledger and now report as
  `other_backend` (AC1.5). Nothing is deleted.
- **T2.8** REQ-9 check plus a live eval. Measure per-consumer latency; the
  native route adds vision-capable framing, so confirm the text consumers did
  not regress.

**TG-2 green when:** the native probe is still 3/3, the live eval passes with no
standards regression, and the letter rows are present and reclassified.

## Wave 3 - Identity includes readout and criteria (gate TG-3)

- **T3.1** Build the identity as `model_id|readout_mode|criteria_hash`
  (AC2.1). Record the retired letter mode as `legacy_letters` so historical rows
  address a real identity.
- **T3.2** `threshold_for()` returns `None` on an unknown identity. Fail-closed
  is preserved (AC2.2).
- **T3.3** `superseded_flips()` compares `readout_mode` and `criteria_hash`
  (AC2.3).
- **T3.4** A criteria edit re-identifies the consumer (AC2.4). Test: change one
  consumer's criteria text, assert its threshold resolves to `None` and its
  recorded flip is reported superseded.
- **T3.5** Report the reset honestly in the wave notes and the pin, with the
  per-consumer counts (AC8.4).

**TG-3 green when:** a readout change and a criteria edit each demonstrably
kill the threshold, and the map is legitimately empty.

## Wave 4 - The state is honoured, and images (gate TG-4)

- **T4.1** `OracleState` as a structured value: job, declared fields, capped
  text, declared images (design §3).
- **T4.2** `job_input()` renders all declared fields in order (AC3.1).
- **T4.3** The backend reads the rendered state, not `frame["goal"]` (AC3.2).
  `route` must produce a state containing coverage, open_facts, depth_met,
  grade and goal.
- **T4.4** Reference fields never enter the state (AC3.3).
- **T4.5** The budget still caps the text, and a trim is logged (AC3.4).
- **T4.6** Contract test per job: every declared field appears, no reference
  field appears (AC3.5).
- **T4.7** The frame gains `images`; `job_input()` includes them only when the
  job declares them (AC5.1).
- **T4.8** `click_safety` becomes the first image consumer, with its rules ->
  judge -> escalation ladder and its shadow row sink unchanged (AC5.2). Its
  input is the session-scoped screenshot (AC5.3).
- **T4.9** `capture_base64` returns the measured scale factor additively;
  existing callers keep working (AC5.4). No DPR assumption is introduced
  (AC5.5).

**TG-4 green when:** the field-presence contract is green per job, `click_safety`
still refuses and escalates correctly with an image in its state, and the scale
factor is available to any future mapper.

## Wave 5 - The sampled rung (gate TG-5)

**NOT blocked** (the earlier "blocked on the turn key" was wrong and is
withdrawn - see requirements Open Questions). The id exists and the outcome
signals exist; this wave adds them to the row.

- **T5.0** Carry `turn_id` and `step_id` into the Oracle row payload (AC6.3a).
  `turn_id` is already on the instance; this is a payload change, not a new
  concept.
- **T5.1** `ConsumerBar.status` gains `sampled`; `derive_status` returns it under
  stated conditions, never inferred from a partial measurement (AC6.1).
- **T5.2** A `sampled` consumer decides on a bounded fraction and only where a
  wrong answer is cheap and reversible; the incumbent remains the fallback
  (AC6.2). **Eligibility comes from the AC6.6 tier table, not from a per-run
  judgement.** Tier C is refused outright and an untiered consumer cannot be
  sampled.
- **T5.3** Sampled rows are labelled by OUTCOME (AC6.3), joined on `turn_id` from
  the signals turn end already computes: contract met, run grade, task done or
  fail, blocked facts (AC6.3b). This is the only mechanism that can break the
  label ceiling.
- **T5.4** The fraction is a named constant with a stated default and a kill
  switch; it is never raised without outcome labels in the measurement (AC6.4).
- **T5.5** The four zero-row consumers (`needs_action`, `recovery_strategy`,
  `sufficient`, `use_thinking`) acquire a live consult site or are declared dead
  (AC6.5). Same reasoning that removed `on_track` and `retry_same`.
- **T5.6** Demonstrate rows appearing with NO human driving the app. This is the
  wave's whole point; without it TG-5 is not green.
- **T5.7 (REQ-10):** land the `call_closing` consult inside the node loop,
  **deferred on the `oracle_shadow` lane, never inline** (AC10.6), asked only
  about candidate closings (AC10.2) with the goal, the call and the call's result
  in the state.
- **T5.8 (REQ-10 AC10.4):** implement the deferred label: the row is written
  PENDING and resolved one iteration later from the closing rule at
  `node_executor.py:629` - loop closed means the claim was correct, loop
  continued means it was premature. This is the first consumer in the system
  whose label is exact, same-layer and free.
- **T5.9 (REQ-10 AC10.6, AC10.9):** prove the reply path and the DAG are
  unchanged. `surface_shadow.py:225-227` measured inline shadow scoring at
  326-561 ms per turn each; a live eval must show identical pass counts, no
  standards regression, and `reply_s` within declared noise. The only permitted
  effect is added rows. A regression here fails the wave.
- **T5.10:** demonstrate that `call_closing` rows carry an OUTCOME label, not an
  incumbent label. That is the first consumer in the audit to show
  `label_source != incumbent`, and it is the proof the mechanism works.
- **T5.11 (audit follow-up, found 2026-10-08):** `done` STILL reports 0 rows even
  though `agent_kernel.py:20945-20949` records that the bare-`pass` row-dropping
  bug was found and fixed. So the monitor_shadow lane-to-ledger path is still not
  landing rows. Find it before touching anything else about `done` — this is the
  concrete suspect the REWIRE verdict needs.
- **T5.12 (REQ-14 — THE MAKING-TRUE TASK):** carry the full scope key
  `(turn_id, step_id, node_exec_id, call_ordinal, consumer_id)` on every deferred
  row, and implement the **six-exit label** of AC14.2 — CORRECT / PREMATURE /
  UNTESTED — **not** the two-valued label REQ-10 originally stated, which review
  found wrong. UNTESTED rows are excluded from the fit and counted. Add
  `node_exec_id` (AC14.3: a step retries, so one step can execute twice) and the
  PENDING sweeper with its `abandoned` value (AC14.4).
- **T5.13 (REQ-14 AC14.6):** build the **fixture harness** that PROVES the label
  mapping — a constructed node execution with a known call count and a known
  exit, asserting the resolved label. One case per AC14.2 exit (six), plus the
  retry case and the abandoned-PENDING case. Live traffic can show a rate; only a
  fixture proves the mapping. Substrate: `scripts/replay_corpus.py`.
- **T5.14 (REQ-14 AC14.5):** report **label integrity** per consumer and per
  grouping, alongside latency. This is the metric the batching method is tuned
  against, and TG-6 may not pass on latency alone.

**TG-5 green when:** outcome-labelled rows accumulate unattended, the sampled
fraction is bounded and reversible, and the bar's own clauses still decide any
promotion to enforced.

## Wave 6 - Per-job batching (gate TG-6)

Owner decision 2026-10-08: batching is ADOPTED. This supersedes the pinned
`one question per run` rule in its letter; one run is now one **state**
answering that state's current questions. The Bench P3 and live gate P4
measurements were taken under the unbatched semantics and must be RE-TAKEN
(AC7.7), not cited.

- **T6.1** Batch **within a job only** (AC7.1). One run = one state = one forward
  pass. The dial's participant stays the JOB. Never merge two jobs — they read
  different fields and are different states.
- **T6.2** A run carries **only the consumers consulted on this turn** (AC7.2),
  never the job's full declared set. Non-consulted consumers would manufacture
  rows for questions nobody asked.
- **T6.3** **The load signal counts QUESTIONS, not runs** (AC7.3). This is the
  most important line in the wave: without it a three-question run is admitted
  three times too often. Assert it in a test.
- **T6.4** Leave the grouping method **configurable and measured, not fixed**
  (AC7.4): cap, formation rule, and the degenerate single-question case. Each
  row records which grouping produced it, so two different groupings stay
  comparable afterwards.
- **T6.4b (REQ-14 AC14.1, the non-negotiable):** a batch is a **transport** unit,
  never a label unit. Every question in a batched pass keeps its own scope key,
  its own resolution time and its own label, and a batch is never written,
  labelled, deduplicated or counted as one row. Pin it with a test.
- **T6.4c (REQ-14 AC14.5):** report **label integrity** for every grouping tried,
  next to its latency. **TG-6 may not pass on latency alone** — a grouping that
  lowers integrity is a net loss even if faster.
- **T6.5** **Criteria-isolation contract test** (AC7.5): consumer A's criteria
  must never appear in consumer B's question within one batched pass. A leak
  here corrupts calibration invisibly.
- **T6.6** **Failure-isolation decision, then a test** (AC7.5): decide and pin
  whether one malformed consumer fails the whole batch closed or is isolated.
  Pin the decision; do not leave it implicit.
- **T6.7** Re-take the phase-domain measurement: participant count, dial
  behaviour, decisions/s, reply latency before and after (AC7.7).
- **T6.8** REQ-9 check: the Decision layer still runs one dial, jobs are still
  participants, the scheduling domain is untouched (AC9.3).
- **T6.9** State in the wave notes that **rows produced before REQ-6's JOIN are
  parity rows** and count toward no bar (AC7.6). Batching makes rows cheaper; it
  does not make them true.

**TG-6 green when:** the dial measurement is re-taken and shows no regression,
latency improves, **AND label integrity holds or improves (AC14.5)**; the load
signal demonstrably counts questions; and all three isolation tests pass. Any one
of the three halves alone is not enough.

## Standing rules for every wave

- Never modify a test to make a wave green. The tests are the requirement.
- Never weaken a bar clause. The bar is the only instrument that found
  `tool_choice` AUROC 0.5225.
- Report values, not code. A signal with no production consumer, or one that
  sits on a clamp, is a failure.
- Record in MCM: `record_edit` / `record_create`, `record_test` with the measured
  outcome, and a `pin_add` for the wave's root cause and fix.
- `VERIFY.md` is written as the waves land, with the measured numbers, not
  summarised after the fact.
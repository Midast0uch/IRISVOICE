# Design: Oracle Native Decision Surface

Read with `requirements.md` (the contract), `docs/architecture/oracle.md` (the
current engine), and `docs/architecture/PHASE_DOMAINS.md` (the concurrency
model this design does not touch).

## 0. What a consumer is, precisely

Recorded because the owner asked for it and the answer shapes the whole spec.

A **consumer** is a named decision point in the application: a **question** plus
the **list of possible answers**. "Consumer" is producer/consumer terminology -
the DER loop and planner produce decision points, the Oracle consumes them by
scoring. It has nothing to do with training a model.

There are two shapes, and the code shows they are the same mechanism:

- **noul (yes/no)** - the question is a statement; the answer is the probability
  that it is true. `done`: is the task finished. `sufficient`: is the goal
  covered. `click_safety`: is this action safe.
- **choice (pick one)** - the answers ARE the candidates. `tool_choice` passes
  the tool candidates. `review_verdict` passes pass / refine / veto.
  `recovery_strategy` passes the recovery options.

`noul()` is not a separate path. `decision_engine.noul` (`:1440`) calls the same
`decide()` with the two options `["yes","no"]` and reads back the probability
for `"yes"` - a multiple choice with two answers.

**d1 never returns a decision.** It returns probabilities: one number for a
noul, one per option for a choice. It never writes a sentence and never reasons
in text. This is precisely why a threshold is needed - 0.62 is not a decision,
and the line is the single number calibrated per consumer. It is also why REQ-4
requires a declared type: the two shapes have different readouts, and inferring
the shape from `len(options) == 2` misreads a genuine two-option choice.

**The candidate list is capped at 6** before it reaches the model
(`decision_engine.decide`, `:1236`, `candidate_cap`). So `tool_choice` is not d1
choosing from the whole menu - it is d1 choosing from a shortlist of at most six
built upstream. Any change to how the shortlist is built is a change to what d1
can possibly answer, and therefore part of the consumer's identity.

## 1. The mismatch, stated once

d1 is a typed decision function. Its published API is
`system_one(state, questions, images=None)`: a state is read once, typed
questions are answered over it in one forward pass with zero output tokens, and
each answer is a typed value with calibrated probabilities.

The Oracle currently calls it as a text generator with a letter menu:

| | today | target |
|---|---|---|
| route | `/completion` | `/v1/chat/completions` |
| input | `frame["goal"]` only | the job's rendered state |
| question | one instruction string | typed: `noul` / `choice` / `score` |
| options | `A <name>` lines, letters as the answer | `name: description`, the name is the answer |
| readout | max-pool per letter token | max-pool per NAME token |
| images | impossible on this route | `images=[...]`, one argument |
| type | inferred from `len(opts)==2` | declared on the consumer |
| passes | one per consumer per turn | one per consumer (batching deferred, REQ-7) |

Each row in that table is a measured defect, not a preference. The letter shape
collapses to a constant answer when the question text varies while reporting
0.99 confidence (probe, backend mode, trials 1-6). The native named shape scores
3/3 at 0.95-1.00 (probe, native mode). The permutation test separates the two
cleanly: identical question, only the image moves, native follows A/B/C.

## 2. The decision identity

Today the identity is the served GGUF filename variant, resolved by
`_current_backend_identity()` (`decision_engine.py:432`) and consumed by
`threshold_for()` (`:691`) and `oracle_calibration.threshold()` (`:567`).

That is the whole key, and it is too small. The probe showed the readout
changes the model's behaviour more than any instruction does. oracle.md §19.3.6
already says a changed input is a new identity; the readout is the largest such
input and it was not in the key.

```
identity = f"{model_id}|{readout_mode}|{criteria_hash}"
```

- `model_id` - unchanged: `d1-3b-ad-q4_k_m`.
- `readout_mode` - `native_choice` | `native_noul` | `native_score`. The retired
  letter mode is recorded as `legacy_letters` so historical rows and any
  surviving calibration file address a real, nameable identity rather than
  silently matching.
- `criteria_hash` - a stable digest of the rendered criteria block, so editing a
  consumer's criteria re-identifies it.

Consequences, accepted deliberately:

- Every row collected under `legacy_letters` becomes `other_backend` on the
  report. Today that is 57 + 34 + 18 + 3 + 3 distinct rows. They stay in the
  ledger forever (oracle.md §16).
- `benchmarks/oracle_calibration.json` entries keyed by the old identity stop
  resolving. `threshold_for()` returns `None` and every consumer fails closed,
  which is the current state anyway - no consumer is enforced today.
- `superseded_flips()` (`consumer_bar.py:219`) gains `readout_mode` and
  `criteria_hash` to its compared keys, so a flip measured under the letter
  readout is reported as superseded rather than standing.

`tool_choice`'s out-of-fold AUROC of 0.5225 is **not** affected by this
rationale. It is a text consumer; the letter readout was validated for text at
98.7% (Wave 0 V1). The number stands as measured.

## 3. The state

`OracleJob` already fixes which frame fields the model reads and in what order
(`decision_engine.py:135-160`), and `job_input()` renders them. The mechanism is
correct. The reader throws the result away:
`decision_backend_d1.py:360` reads `str(frame.get("goal",""))`.

Target: `job_input()` returns a structured state; the backend reads it whole.

```python
@dataclass(frozen=True)
class OracleState:
    job: str                  # the job that built it
    fields: tuple[str, ...]   # declared fields, in order
    text: str                 # the rendered, budget-capped text
    images: tuple[bytes, ...] # declared images only (REQ-5)
```

- All eight jobs keep their declared fields and budgets. `route` declares
  `("coverage","open_facts","depth_met","grade","goal")` at 64 ids; all five must
  appear in the rendered state. Today only `goal` does.
- The budget still caps the text. The cap is applied where it is applied today,
  logged when it trims, never silent.
- Reference fields never enter the state. AC3.3 is enforced by a test, because a
  row whose input carries its own answer measures nothing.
- The frame gains `images` as an optional field. `job_input()` includes images
  only when the job declares them, so a text consumer can never accidentally
  receive an image and pay for the vision tokens.

### Why the state is structured rather than a string

It is not tidiness. The identity hash needs the criteria, the row needs to know
which fields were present, and AC3.5 needs to assert field presence. A string
throws all three away.

## 4. The consumer registry

`ConsumerSpec` today carries `criteria: bool = True` (`:209`) - a flag, not a
criteria. That is the structural reason the named-criteria shape was
unreachable: there was nowhere to put a description.

```python
@dataclass(frozen=True)
class ConsumerSpec:
    consumer_id: str
    decision_type: str                       # "noul" | "choice" | "score"  (required)
    instruction: str
    criteria: Mapping[str, str] | tuple[str, ...] | None   # by type
    job: str
```

- `noul` - criteria optional; `{"true": ..., "false": ...}` names each side.
- `choice` - `name -> description`, required.
- `score` - ordered level descriptions, lowest first, required.

`decision_type` is required. A consumer without one scores nothing. It does not
inherit a shape and it does not get a generic fallback, because a generic
fallback is exactly how `review_verdict` ended up asking an under-specified
question that the incumbent passed 96% of the time.

The inference heuristic (`decision_backend_d1.py:376-379`) is deleted. Type is a
property of the decision point.

Migration is one wave and it is not optional: every consumer in `CONSUMERS`, plus
`event_family`, `event_type:*`, `user_feedback` and `click_safety`, gets a type
and criteria in the same change that starts relying on it (AC4.4).

## 5. Rendering and readout

One renderer, three types. The readout vocabulary comes from the server's own
tokenizer, as `_ensure_letter_ids` does today (`decision_backend_d1.py:232`),
extended from letters and yes/no to criterion names and level tokens.

- `choice` renders the criteria block; the readout pools per NAME token;
  `CandidateScore.name` is the name.
- `noul` renders the yes/no instruction; the readout pools per yes/no form;
  `true` is normalised first regardless of the caller's option order (the
  current normalisation at `:386-390` is preserved exactly).
- `score` renders the ordered levels; the readout pools per level token.

`DecisionScore` and `CandidateScore` do not change. CT-DE-1 pins that envelope
and the engine's `noul()` unwrapping depends on it.

One transport fact, learned the hard way (AC0.3): on `/v1/chat/completions`
llama.cpp may return either `completion_probabilities` or the OpenAI
`logprobs.content[].top_logprobs` shape. In the OpenAI shape each entry has `id`
(the token id) and `bytes` (the utf-8 byte list). **Reading `bytes[0]` yields a
character code** - 116 is the letter "t" - and every readout silently misses.
The probe measured 0/3 because of this and not because of the model. Both shapes
are parsed; `id` is authoritative; `bytes[0]` is never an id.

## 6. Images and the framing ratio

`click_safety` is the first image consumer because its question is visual.

The capture question is separate and this spec answers only the part the Oracle
needs. Capture lives in `backend/vision/` and `backend/tools/vision_provider.py`;
the Oracle does not capture. What the Oracle needs is a scale factor it can
trust, and today it does not exist:

- `ScreenCapture.capture_base64` computes `ratio = max_width / img.width` to
  resize, then discards it, returning `(b64, is_new)`.
- mss returns physical pixels; on a scaled Windows display physical and logical
  pixels differ, and nothing in the capture path reads the scale.

So `capture_base64` gains an additive scale factor in its return (AC5.4).
Existing callers keep working. Any future consumer that maps an image-space
point to a screen pixel depends on that value, and this spec makes it
obtainable without building the mapping.

The OS-level module capture is not used for a consumer input. The
session-scoped screenshot rule stands (`session_vision_adapter.py:71`): a
consumer's image is the browser session's screenshot.

## 7. The sampled rung

Two states cannot produce evidence that d1 is better than the incumbent.

- **shadow** - d1 scores, the incumbent decides. The row's label is the
  incumbent's outcome. This measures agreement only.
- **enforced** - d1 decides. Requires the full bar, which no consumer has met.

So the map is empty and cannot fill. The missing rung is a consumer that
**decides on a bounded fraction**, with the outcome recorded. Only an outcome
label breaks the ceiling (oracle.md §0.7).

```
shadow ──(owner + reversibility review)──> sampled ──(full bar on outcome rows)──> enforced
   ^                                          |
   └────────────(any regression)───────────────┘
```

- `derive_status` returns `sampled` under stated conditions, never inferred from
  a partial measurement.
- The sampled fraction is a named constant with a kill switch (AC6.4). It is
  never raised by a measurement that lacks outcome labels.
- **Which consumers qualify is structural, not a matter of taste.** Reversibility
  follows two independent gates (requirements AC6.6, which carries the full
  table): **reversibility** (is a wrong answer survivable? the L1 read-only /
  L2 reversible / L3 irreversible ladder, where L3 says never delegate alone)
  AND **ground truth** (can the answer ever be labelled?). Both must pass.
  `done` fails the first in spirit — a false `done` ends the turn with work open,
  so it is JOIN-only and never sampled. `presentation` and `narration` pass
  reversibility comfortably (L1) and fail on ground truth instead, which is the
  correction this gate surfaced.
- **The turn key is not a blocker.** It was never missing: `turn_id` is on the
  instance (198 uses in `agent_kernel.py`) and the gateway passes it at turn
  entry. What was missing is only its presence in the Oracle row payload
  (AC6.3a), and turn end already produces real outcome signals - contract met,
  run grade, task done or fail, blocked facts (AC6.3b, DER_DAG §6). This design
  previously called Wave 5 blocked on this; that was wrong and is withdrawn.

## 8. The phase domain: one run becomes one state

The Decision layer runs one dial; every Oracle job is a participant on it. This
section records an owner decision that changes the admission semantics, and it
is the one place in this design where a pinned rule is deliberately superseded.

### The conflict

d1 batches over the **STATE** (`system_one(state, questions, images=None)` — the
state is read once for all its questions). The dial admitted by the **QUESTION**
(oracle.md §9: each run stays one question). Different granularities; one had to
give.

The rule is not arbitrary. A participant's angle means "one decision since this
participant last ran". If one admission carries five questions, dwell time
multiplies and the angle stops meaning that — which is what makes exit-driven
admission and fairness interpretable.

### The resolution (owner, 2026-10-08)

**A job already IS a state.** `ORACLE_JOBS` exists precisely to fix which fields
the model reads, so it is a state definition — and `CONSUMER_JOBS` already groups
consumers onto shared field lists:

| job | field list | consumers |
|---|---|---|
| `judge_goal` | goal, open_facts, evidence | `done`, `depth_met`, `sufficient` |
| `guard` | goal | `click_safety`, `needs_action`, `use_thinking` |
| `interpret` | goal | `mode`, `web_intent`, `user_feedback` |
| `route` | coverage, open_facts, depth_met, grade, goal | `tool_choice`, `recovery_strategy` |

A job is also **already one participant on the dial**. So batching within a job
is not a new grouping — it is the existing grouping, used honestly. The rule
becomes "each run stays one **state**, answering that state's questions", which
is d1's native API and what the job already meant.

### Consulted-only, and why

The owner chose to carry **only the consumers consulted this turn**, not the
job's full declared set: carrying unconsulted consumers manufactures rows for
questions nobody asked, which is noise, and pads the run with work that
corresponds to no real decision. The accepted consequence is a variable run size
(0, 1 or 3 questions), so dwell time varies per turn.

### What absorbs the variation

**The load signal counts questions, not runs.** Without this, a three-question
run occupies three times the CPU for one admission and is admitted three times
too often. With it, admission tracks real work and a three-consumer job is
admitted a third as often — fair by the work performed. This is the load
function's semantic change and the most important line in the change.

### Two new risks batching creates

Neither exists in a single-question call, so both need pinned tests:

1. **Criteria bleed.** Consumer A's criteria must never appear in consumer B's
   question within one pass. A leak here corrupts calibration invisibly, and no
   single-question test could catch it.
2. **Poisoned batch.** Today a malformed consumer returns `None` for itself
   alone. Batched, it could fail every neighbour. Fail-closed-for-all is safe
   but starving; per-question isolation needs a separable render. The choice is
   pinned, not left implicit.

On IRIS's own mutable state, batching **reduces** contention: the engine already
serialises scoring under one lock, so three questions in one pass take one lock
acquisition instead of three. The shared-state risk lives entirely on the
question-isolation side of the boundary.

### What this invalidates

Bench P3 (273/273 identical decisions) and live gate P4 (coding 15/15, research
8/8, no regression) were measured under the unbatched semantics. They are
**invalidated** and must be re-taken. They are not evidence for this change.

### Honest limit on the win

Batching makes rows cheaper. It does not make them **true**. Until the REQ-6
label join lands, a batched row is still incumbent-labelled and counts toward no
bar. The two changes are independent and must not be credited to each other.

## 9. Waves and gates

| Wave | Content | Gate |
|---|---|---|
| 0 | AC0.1-AC0.4 verifications, baselines pinned | both probes reproduce; baseline recorded |
| 1 | REQ-4: declared types + real criteria on every consumer | CT-DE-7 enumerations pass unchanged; nothing scores yet |
| 2 | REQ-1: native readout on `/v1/chat/completions` | native probe 3/3; live eval, no standards regression |
| 3 | REQ-2: identity includes readout + criteria | a readout change demonstrably returns `None`; superseded flip reported |
| 4 | REQ-3 + REQ-5: state honoured, images in the frame | per-job field-presence contract green; scale factor returned |
| 5 | REQ-6: sampled rung | outcome-labelled rows appear without a human; REQ-9 intact |
| 6 | REQ-7: batching, only if the dial measures better | phase-domain measurement attached; AC7.1 one-question default intact |

Wave 1 lands before Wave 2 deliberately: giving every consumer a declared type
and real criteria while the letter readout still serves them is a pure
declaration change with no behaviour risk, and it makes Wave 2 a single
transport swap instead of a registry rewrite.

## 10. What this design refuses to do

- It does not replace the engine, the job routing, the registry, the bar, or
  the phase domain. Every one of those is a REQ-9 clause with a gate.
- It does not add a vision model.
- It does not relax a bar clause to manufacture a flip.
- It does not build the click pipeline. The probe proved grounding; the scale
  factor is made available; the mapping is a later spec.
- It does not claim `tool_choice` improves. The reset empties the map. The next
  spec earns a threshold or does not.
# Oracle - Architecture Blueprint

The Oracle is IRIS's local decision engine. This file describes what it is, every
layer it touches, how a decision is made, how it earns the right to act, and how well
it performs. History and chronology live in `oracle-history.md`.

Source of truth is the code. Names in `code font` are real identifiers.

---

## 1. What the Oracle is

One small local model answers ONE question per run and returns a probability
distribution over the answers the caller offered.

- **Model**: d1-3B (`d1-3B-AD-Q4_K_M.gguf`), a typed "System One" decision model.
  It is served by the shared `llama-server` on `:8082`, the same server and the same
  loaded model that vision uses (with its `mmproj` projector). The Oracle only
  borrows it: it never spawns, restarts or loads anything.
- **Question shapes** (`DECISION_TYPES`): `choice` (pick one named option),
  `noul` (P(statement is true), yes/no), `score` (ordered levels, schema only; no
  consumer uses it).
- **One question per run.** A run reads a state, renders one question, and reads the
  answer from the logits at the single answer slot. Zero text is generated.
- **It is not an LLM chat and not a batch classifier.** It never writes prose, never
  writes arguments, never writes memory, never emits events, never calls a hosted
  provider. A model that is not d1 on the shared server means "Oracle unavailable";
  there is no fallback model.
- **Its guesses are never evidence.** Evidence is outside only: a tool outcome, a
  test, a completion, a user correction. The Oracle's own answer never labels itself.
- **Shadow until it earns a job.** Every consumer starts in shadow: the incumbent
  (a rule, a keyword list or the Brain) decides, the Oracle is scored beside it, and
  the pair is recorded. A consumer acts only when the owner has switched it on AND it
  has passed the measured bar AND a threshold was fitted for the running model
  (section 5). With nothing switched on, the Oracle decides nothing.
- **Failure is silent to the user.** Every Oracle call returns a score or `None`.
  `None` always means "the incumbent decides", byte-for-byte as if the Oracle did
  not exist.

Display name `Oracle`; config block id `oracle` in `backend/agent/agent_config.yaml`;
module `backend/agent/decision_engine.py` (the identity key `d1-3b-ad-q4_k_m...`
keys every calibrated threshold, so these keys are never renamed as a label change).

---

## 2. Layer diagram

### 2.1 Runtime stack (one tool decision)

```
 USER TURN  (voice / text)
     |
     v
 AGENT KERNEL ........................ backend/agent/agent_kernel.py
   plan -> DER steps -> verify -> synthesise -> speak/display
     |
     |  each DER step runs a NODE
     v
 NODE LOOP ........................... backend/agent/node_executor.py  run_node()
   NodeContext { generate, execute, on_result, choose_tool,
                 history, last_result_text, tools }
     |
     | (1) before EVERY model call, unless the last call was a model slip:
     |     forced = ctx.choose_tool()
     v
 KERNEL HOOK  _choose_tool ........... agent_kernel.py (node path)
   reads the step's live state: history_text, last result, step_facts,
   done_when, ORACLE_HINTS option lines (tool_registry.oracle_hint)
     |
     v
 ToolDecisionBox.choose_node_tool .... backend/agent/tool_decision.py
   decides("tool_choice")  -> enforced?   else sampled_consult_ok() -> sampled?
   menu = _order_engine_names + _compose_engine_menu (cap 32, DELEGATE/NONE)
   frame = goal, done_when, calls_this_step, step_facts, last_result
     |
     v
 DecisionEngine.decide ............... backend/agent/decision_engine.py
   job_input()  -> OracleState (job fields + budget + images + option_criteria)
   phase gate   -> domain "decision.oracle_cpu"  (IRIS_ORACLE_PHASE)
   inference thread (never the caller's step thread)
     |
     v
 D1Backend.decide .................... backend/agent/decision_backend_d1.py
   render prompt (im_start markup, letter-coded options)
   POST /completion  n_predict=1  n_probs=512  temperature=1.0
   softmax over the option-code tokens at the answer slot
     |
     v
 llama-server :8082 .................. d1-3B-AD-Q4_K_M.gguf + mmproj (shared with vision)
     ^
     |  DecisionScore { chosen, confidence, distribution, engine_latency_ms }
     |
 back in choose_node_tool:
   DELEGATE / NONE            -> None (the model keeps the full menu)
   enforced: oracle_acts()    -> calibrated(conf) >= threshold, else None
   sampled:  read-only gate   -> side-effect tool refused unless eval switch
   -> returns (tool, row{route, criteria_version tc-decide-v3, menu_fp, state})
     |
 back in _choose_tool:
   binding iff route == "enforced"  OR  confidence >= IRIS_ORACLE_FORCE_MIN (0.9)
     |
     v
 run_node: gen_tools = [that one tool]; gen_extra["tool_choice"] = tool
     |
     v
 InferenceRouter.generate ............ backend/agent/inference/router.py
   sanitises the tool name, forwards `tool_choice` only to a transport whose
   generate() names the keyword; on a 400/422/"tool_choice" refusal retries
   ONCE with "auto" (logged); remaps sanitised names back
     |
     v
 Transport ........................... backend/agent/inference/transport.py
   body["tool_choice"] = {"type":"function","function":{"name": tool}}  (else "auto")
     |
     v
 TOOL MODEL writes the ARGUMENTS (or ends the step without a call)
     |
     v
 ctx.execute -> AgentToolBridge dispatch -> tool runs -> result
     |
     v
 ctx.on_result(name, params, ok)  (fires with the PRE-CALL state still readable)
   |-- label_decided_row(...)         ok / failed / overridden / finished
   |-- record_shadow_tool_choice      parity row, lane("oracle_shadow")
   |-- browser_next_shadow            on browser_act with an element_id
   `-- tool_approval_shadow           post-hoc yes/no, outcome-labelled
     |
     v
 shadow-row sink (installed by AgentKernel) -> AgentToolBridge.record_decision
   -> write-time dedupe (bounded LRU) -> system_events
      event_type='tool_execution', interaction_payload.decision
   -> data/memory.db  (resolved by resolve_memory_store_path)
```

### 2.2 Learning loop (offline, manual)

```
 data/memory.db  system_events.decision rows
     |
     |  scripts/consumer_enforcement_report.py      (read-only; --write persists)
     |    load_rows: label (decision_label), collapse repeats, scope by engine,
     |               optional --scope CONSUMER=criteria_version
     |    fit_consumer (via fit_oracle_calibration): isotonic map + threshold,
     |               5-fold out-of-fold AUROC / ECE / Brier / precision / Wilson LB
     |    consumer_bar.derive_status: shadow | sampled | enforced + the gap
     v
 benchmarks/consumer_bar_record.json   (status per consumer + the identity it was
                                        measured on)
     |
 scripts/fit_oracle_calibration.py     (offline; --dry-run prints only)
     v
 benchmarks/oracle_calibration.json    (knots + threshold per identity/consumer)
     |
     v
 decision_engine.decides() / oracle_acts()   <- the ONE enforcement chokepoint
     ^                                          reads the bar record, the
     |                                          calibration file, the owner's
     |                                          IRIS_DECISION_ENFORCE list
 scripts/replay_tool_choice.py         re-ask d1 on recorded states (no writes)
 scripts/export_tool_choice_training.py  outcome-checked decisions -> JSONL
 scripts/finetune_d1_lora.py           LoRA fine-tune (optional; new identity)
```

### 2.3 Shadow and sampled consumers around the engine

```
                     +-----------------------------------------+
                     |  DecisionEngine  (one resident backend)  |
                     +-----------------------------------------+
   route job  ---- tool_choice (enforced) | recovery_strategy | depth_route
                   browser_next (shadow, element ids as options)
   approve job --- tool_approval (shadow, post-hoc)
   guard job ----- click_safety (shadow + refuse-only sample) | needs_action
                   | use_thinking
   judge_step ---- review_verdict | escalate_incomplete
   judge_goal ---- done | sufficient | depth_met
   judge_call ---- call_closing (REFUSED: measurement only)
   shape job ----- presentation | narration
   interpret job - web_intent | user_feedback
   classify_event  event_family | event_type:<family>
   boot: main.py _boot_load_d1 loads d1 (+mmproj) on :8082 at startup
   lanes: oracle_shadow (most consults), click_safety_shadow,
          event_oracle, memory_events   (backend/utils/durability_queue.lane)
```

### 2.4 Boot and serving

- `backend/main.py` `_boot_load_d1` starts as an async task right after the TTS
  prewarm. It reads the pinned vision model; it loads only a file whose name contains
  `d1-3b` (any other pin is refused with a log). It prefers a same-named file on the
  `D:/lmstudio/models` SSD twin to the `C:` copy, skips the load if d1 is already
  resident on the shared server, and calls `LocalModelManager.load_model(...,
  with_projector=True, custom_params={"n_ctx": ...})`. `n_ctx` is the `last_ctx`
  of the model's entry in `models/gguf/.iris_model_settings.json` (default 8192).
- The shared server port is `LocalModelManager.PORT` (env `IRIS_LOCAL_MODEL_PORT`,
  default 8082).
- `D1Backend` checks `GET /v1/models` for a served id whose file name contains
  `d1-3b`. The result is cached for `IRIS_D1_CHECK_TTL_S` (default 300 s). If the
  server hosts anything else, every decision returns `None`.
- The load is borrow-only and `retry_load = True`: a miss at boot is transient, and
  the engine probes again on the next decision.
- HTTP uses one pooled keep-alive client (`httpx.Client`, timeout
  `IRIS_D1_TIMEOUT_S`, default 20 s). `IRIS_D1_N_PROBS` (default 512) is how many top
  token logprobs the server returns at the answer slot.

---

## 3. Concepts

### 3.1 Consumers

A consumer is one decision point (one question asked at one place in the app).
Each has an id, a declared decision type and criteria, and one job.

`CONSUMERS` (the declared set, `decision_engine.py`) and the declaration table
`CONSUMER_DECLARATIONS` give the type per consumer:

| Consumer | Job | Type | Incumbent that decides today | Where |
|---|---|---|---|---|
| `tool_choice` | route | choice | the tool model | node loop (`choose_node_tool`, enforced) and post-hoc shadow row |
| `tool_approval` | approve | noul | none (labelled by the call's outcome) | `tool_approval_shadow`, post-hoc |
| `browser_next` | route | choice | the tool model's element pick | `browser_next_shadow`, each `browser_act` |
| `click_safety` | guard | choice (safe/unsafe/unsure) | rules, then Brain judge, then ask the user | `tools/browser_tools.py`, `click_safety_shadow` |
| `recovery_strategy` | route | choice | the recovery ladder | `ToolDecisionBox.recovery_strategy` |
| `depth_route` | route | choice | the loop's own continuation | `ToolDecisionBox.depth_route` |
| `review_verdict` | judge_step | choice (pass/refine/veto) | the Brain reviewer | `der_loop.Reviewer` |
| `escalate_incomplete` | judge_step | noul | incomplete-result keyword list | `der_loop` |
| `done`, `sufficient` | judge_goal | noul | Brain done-bit / sufficiency gate | `monitor_shadow` |
| `depth_met` | judge_goal | noul | the loop's run grade | `surface_shadow`, run-grade point |
| `needs_action` | guard | noul | goal heuristics | `tool_decision` |
| `use_thinking` | guard | noul | ~40-phrase trigger list | `agent_kernel` |
| `presentation` | shape | choice | reply-surface rules | `agent_kernel` reply surface |
| `narration` | shape | choice | deterministic beat rule | `agent_kernel` |
| `web_intent` | interpret | noul | duplicated web-trigger keyword lists | `explorer` |
| `user_feedback` | interpret | choice | none (a Brain sample is the reference) | `event_oracle` |
| `event_family`, `event_type:<family>` | classify_event | choice | rule label, Brain sample | `event_oracle` |
| `call_closing` | judge_call | noul | the node closing rule | measurement only |

Rules of the registry:

- A consumer with NO declared decision type is registered undeclared and the engine
  REFUSES to score it. It never borrows another consumer's shape.
- `event_type:<family>` consumers inherit the `event_family` declaration.
- `REFUSED_CONSUMERS = {"call_closing"}`: never enforced, never sampled, never
  resolved to a threshold, whatever any flag says. It is asked only about calls that
  claimed to close a step and never about a call that changed a file.
- The owner's allow-list (`IRIS_DECISION_ENFORCE`) only accepts ids that are members
  of `CONSUMERS`. `tool_approval`, `click_safety`, `browser_next`, `user_feedback` and
  the event consumers cannot be switched on by that flag.
- Retired and absent: `mode`, `on_track`, `has_gaps`, `retry_same`. `tier0_classify`
  is a recorded non-fit (a sub-millisecond rule would become a ~150 ms model call).

### 3.2 Jobs (`ORACLE_JOBS`)

A job is the KIND of question. It fixes what the model reads (which frame fields, in
which order) and how much (a text budget in token ids). The engine builds the input;
a call site cannot make it longer, shorter or blind. Fields not declared by the job are
dropped by `job_input()`. Reference fields (`incumbent_route`, `brain_*`) are never
declared, because an input that carries the answer measures nothing.

| Job | Question | Declared fields (render order) | Budget (ids) |
|---|---|---|---|
| `route` | which of these next actions? | coverage, open_facts, depth_met, grade, goal, done_when, calls_this_step, step_facts, last_result, task_class, previous_chosen, previous_outcome, step_index, needs_vision, vision_candidates, ruled_out, error_snippet, pushes_used | 384 |
| `approve` | is this the right tool for this goal? | goal, calls_this_step, last_result, proposed_tool, tool_description, args, offered_tools | 384 |
| `guard` | is this action safe without asking? | goal; image field `screenshot` | 128 |
| `interpret` | what does the user's message mean? | goal | 64 |
| `judge_step` | did this step do its part? | goal | 96 |
| `judge_goal` | is the objective met, deep and sufficient? | goal, open_facts, evidence | 128 |
| `shape` | how should this answer be delivered? | goal, content_chars, has_structure, card_already_rendered, zone, mode, steps, beats_authored, beats_admitted, multi_segment | 128 |
| `classify_event` | which event family/type? | goal | 64 |
| `judge_call` | was this call the closing call? | goal, call, result | 96 |
| `general` | a consumer with no job | goal | 128 |

Mapping: `CONSUMER_JOBS`. The budget is a cap, not a floor. The backend cuts the state
at `max(64, budget) * 4` characters from the END (so the field order protects what
matters) and logs every trim. Only `guard` declares an image; a text consumer never
receives one even if its frame carries one.

### 3.3 Job input and frame (tool_choice as the example)

`job_input(consumer, frame)` renders `goal` as plain text and every other declared
field as `field: value` (lists joined by `; `, floats to 2 places), skipping absent
fields. The `tool_choice` frame on the node path carries, with the call-site caps:

- `goal` (200 chars) - the step goal
- `done_when` (200) - the step's own criterion
- `calls_this_step` (400) - `history_text`: the last 6 calls of this step, e.g.
  `read_file m.py ok; edit_file m.py FAILED`
- `step_facts` (400) - `node_executor.step_facts`: for each file the step names,
  whether it exists and whether this step already read or changed it ("read in this
  step", "read N times in this step", "does not exist yet"); files seen in the last
  result and not yet read; the last command and whether it worked
- `last_result` (600) - what THIS step's last call returned (read at call time, not
  the previous step's result)
- `option_criteria` - the per-option text (below); it never renders into the state

Order puts `calls_this_step` and `step_facts` before `last_result`, so when the budget
cuts the state it cuts the long result snippet and never the history.

**Menu and option lines.** The options are the tools the node offers, ordered by
`_order_engine_names` (vision tools first for a vision-relevant goal; in developer
mode the coding tools in `_DEV_MENU_ORDER` first; else registry order), then
`_compose_engine_menu` reserves two slots inside the cap for the control labels
`DELEGATE` ("Not sure - let the model choose the tool") and `NONE` ("No tool - the step
is already done"). Each option renders as `{code} {text}`; the text is the tool's
decision line from `tool_registry.ORACLE_HINTS` - one short "when to choose it, with its
precondition" line per tool (24 tools plus the two controls), for example `read_file`:
"Read a file that exists but is not read in this step". A tool with no hint falls back to
the first sentence of its description (`oracle_hint`).

**Option codes.** `A`..`Z` when there are at most 26 options, else `00`, `01`, ...
A code that is not a distinct single token falls back to a bounded pool (`A`..`Z`, then
`00`..`99`). If no distinct code exists the consumer fails closed. The general bound
on any consumer's option count is `OPTION_CEILING = 120`; `candidate_cap` (32) is the
width of the tool menu only.

**Menu fingerprint.** Every tool-choice row carries `menu_fp`, a short hash of the
offered names in order plus their option text (`_menu_fingerprint`). A tool added or
re-described changes it.

### 3.4 Prompt and readout (`decision_backend_d1`)

The prompt is built by hand, no chat template, no system turn:

```
<|startoftext|><|im_start|>user
{state}

QUESTION:
{instruction}

Options:
A {option text}
B {option text}
...

Reply with the option code only.<|im_end|>
<|im_start|>assistant
```

- `noul` renders the yes/no template ("Reply with yes or no only."), adding the
  declaration's `Yes:` / `No:` lines; the readout pools `yes/Yes/YES` against
  `no/No/NO`.
- `choice` pools each option's code token with its space-prefixed form. The server
  returns the top `n_probs` token logprobs at the single answer slot; an option whose
  code token is absent scores -inf; the answer is a softmax over the options.
- `confidence` is P(chosen). A noul row stores confidence in the CHOSEN answer
  (`max(p, 1-p)`) and keeps the raw `probability` beside it.
- A scoring failure of any kind returns `None`.
- Images ride `image_data` on the same request (the `guard` job).
- `decide_batch` / `DecisionEngine.decide_many` / `shadow_many` (one pass over one
  shared state, `IRIS_ORACLE_BATCH_CAP`, default 8) exist, but nothing outside the
  tests calls them; every production consult is one question per run.

### 3.5 Decision identity and cohorts

```
identity = model_id | readout_mode | criteria_hash
         = d1-3b-ad-q4_k_m+letters | letters | <12 hex of sha1(type, criteria, cap)>
```

- `model_id` is the served GGUF stem, lowercased, plus the readout tag (`+letters`).
  A row's `engine` field holds this string.
- `criteria_hash(consumer, candidate_cap)` digests the declared type, the declared
  criteria and the candidate cap. Editing criteria or the cap re-identifies the
  consumer, so its old threshold no longer resolves and it falls back to shadow.
- A bar flip records the identity it was measured on (`config.backend_id`). It stands
  only while the running identity equals it.
- The frame is NOT inside `criteria_hash`. A frame or question change is tracked by
  the row's `criteria_version` stamp instead: `tc-frame-v8` (post-hoc tool_choice
  parity rows), `tc-decide-v3` (Oracle-decided rows), `tool_approval/v3`,
  `browser_next/v1`. The report and the fit take `--scope CONSUMER=STAMP` to measure
  one cohort and never blend two.

### 3.6 Enforcement allow-list

`decision_engine.decides(consumer)` is the ONE chokepoint. It returns the calibrated
threshold only when all four keys hold, else `None`:

1. the owner switched the consumer on: `IRIS_DECISION_ENFORCE` (comma list, default
   empty, members of `CONSUMERS` only);
2. the bar record (`benchmarks/consumer_bar_record.json`) says `enforced`, measured on
   the identity now running;
3. a threshold was fitted for that identity in `benchmarks/oracle_calibration.json`;
4. the configuration is not stale (`candidate_cap == calibrated_cap`, both 32).

`oracle_acts(consumer, raw_conf)` then applies the per-decision test: the calibrated
confidence (isotonic map of the raw confidence in the chosen answer) must be at least
the threshold. Below it the existing path decides. `enforced_consumers()` is the
intersection of the owner's list and the earned bar, never a union. `decides` never
raises; a fault means "does not decide". One INFO line per process (and again if the
engine identity changes) names who decides and why each allow-listed consumer that
does not, does not.

### 3.7 The sampled rung

Between shadow and enforced sits `sampled`: a bar status for a consumer that fails the
enforcement bar but is sampling-eligible and has at least one outcome-labelled row.
`sampled_consult_ok(consumer, scope_key)` decides whether the Oracle's answer may
replace the incumbent on THIS consult:

- Tiers: `TIER_SAMPLABLE` = needs_action, recovery_strategy, escalate_incomplete,
  tool_choice. `TIER_REFUSE_ONLY` = click_safety, review_verdict (may only tighten:
  refuse or veto where the incumbent allowed, never loosen). `TIER_JOIN_ONLY` = done,
  sufficient, depth_met (labelled by outcome, never sampled). A consumer in no tier
  (and every refused consumer) is never sampled.
- Fraction: `SAMPLE_FRACTION = 0.05`, overridden by `IRIS_ORACLE_SAMPLE_FRACTION`, and
  per consumer by `IRIS_ORACLE_SAMPLE_FRACTION_<CONSUMER>` (for example
  `..._TOOL_CHOICE=1` for 100%). `IRIS_ORACLE_SAMPLE=0` kills sampling.
- Deterministic: a SHA-256 of `consumer|scope_key` against the fraction, so a retried
  consult answers the same way.
- Read-only gate for tool picks: a sampled `tool_choice` pick may force only a tool
  whose `permission_tier` is `read_only`. A side-effect tool (edit, write, run, browser
  input) acts on a sample only when `IRIS_ORACLE_SAMPLE_SIDE_EFFECTS=1` (the eval
  switch; eval work folders are throw-away). An unknown tier counts as not read-only.
  An enforced pick has no such gate.
- Sampled rows are labelled by outcome, never by the incumbent. A tool pick is labelled
  by its call (section 4). Other consumers register the row pending
  (`register_turn_pending`, 256 turns, oldest dropped) and it is labelled `turn_ok` /
  `turn_fail` at turn end.

### 3.8 Option ceiling and candidate cap

`OPTION_CEILING = 120` bounds any consumer's options (the code pool). `CANDIDATE_CAP_DEFAULT
= 32` (and `agent_config.yaml` `oracle.constraints.candidate_cap: 32`, which overrides
the code default) bounds the tool menu: up to 30 real tools plus `DELEGATE` and `NONE`.
The node tool set (24 tools) plus the two controls fits whole. The cap is inside
`criteria_hash` and `calibrated_cap` is 32; a deployed cap that differs marks every
threshold stale and enforcement is refused.

---

## 4. The decide path for a tool call

1. **Ask first.** Before every model call in `run_node`, unless the previous call was a
   model slip (a malformed or empty tool-call reply), `ctx.choose_tool()` runs. After a
   slip the model keeps the full menu: the full menu is the recovery.
2. **Gate.** `choose_node_tool` returns `None` at once, with no d1 call, if there is no
   engine, no candidates, and the consumer is neither enforced (`decides`) nor drawn by
   the sampled share.
3. **Pick.** One d1 question over the offered tools on the step's live state. This is
   the one Oracle call a node waits for (typical 112-302 ms; section 7).
4. **Filter.** `DELEGATE` / `NONE` never act. Enforced: the calibrated confidence must
   clear the threshold (`oracle_acts`). Sampled: the read-only gate.
5. **Bind or drop** (`_choose_tool` in the kernel). A pick is binding when
   `route == "enforced"` (it already cleared its calibrated threshold) or, for a sampled
   pick, raw confidence is at least `IRIS_ORACLE_FORCE_MIN` (default 0.9). A pick is
   either binding or absent; a non-binding pick does not narrow the menu. The row is
   marked `binding: true` and held pending.
6. **Force at the API.** `run_node` passes only that tool in `tools` and sets
   `tool_choice=<tool>` (only if the tool is in the node's allowed set). The router
   forwards a named `tool_choice` to a transport that accepts the keyword; the
   transport sends `{"type":"function","function":{"name": ...}}`; a refusal (400/422
   or an error naming `tool_choice`) retries once with `auto`.
7. **Arguments by the tool model.** The tool model writes the call's arguments. It may
   also answer without a call (the step finishes).
8. **Dispatch and outcome.** `ctx.execute` runs the tool through the tool bridge.
   `ctx.on_result(name, params, ok)` fires with the pre-call state still readable.
9. **Label** (`label_decided_row`). The pending row is stamped `label_source: "outcome"`
   and one `outcome_label`:

   | outcome_label | meaning | `outside_label` | scored |
   |---|---|---|---|
   | `ok` | the model called the chosen tool and it succeeded | True | right |
   | `failed` | the model called the chosen tool and it failed | False | wrong |
   | `overridden` | the model called a different tool | False | wrong (kept apart from `failed`) |
   | `finished` | the step ended without calling a tool | none | counted, never scored |

   `outside_label = (called == chosen and ok)`. `decision_label` reads `outside_label`
   on every row first; a decided row with no outside label is unadjudicated and is
   counted, not scored.
10. **Post-hoc shadow rows.** For every executed call, a second parity row is scored on
    the `oracle_shadow` lane (`record_shadow_tool_choice`, same menu and frame, paired
    with the tool the model actually called and `brain_ok`); `browser_next` and
    `tool_approval` rows are scored on the same lane. The pair rows are calibration
    evidence and fine-tuning data; they do not change what ran.

When the pick is NOT binding: the Oracle is unavailable; the node just had a model
slip; the pick was `DELEGATE` or `NONE`; the tool is not in the node's allowed set;
enforced but the calibrated confidence is below the threshold; sampled below
`IRIS_ORACLE_FORCE_MIN`, or sampled on a side-effect tool.

Other call sites read the same chokepoint (`needs_action`, `use_thinking`,
`sufficient`, `depth_met`, `done`, `escalate_incomplete`, `web_intent`,
`recovery_strategy`, `presentation`). `ToolDecisionBox.resolve()` and
`explorer.propose()` also gate on `decides("tool_choice")` but have no production
caller; the DER node path is the live deciding path.

---

## 5. The bar

A consumer moves shadow -> enforced only on measured evidence. The measurement is
`scripts/consumer_enforcement_report.py` using the out-of-fold fit in
`scripts/fit_oracle_calibration.py`; the clauses are `consumer_bar._derive_hardened`.
All must hold, and the first one missing is recorded as the gap:

| # | Clause | Value |
|---|---|---|
| 1 | distinct rows | >= 100 (`MIN_ROWS`) |
| 2 | both classes present; minority share | >= 5% (`MIN_MINORITY`) |
| 3 | out-of-fold AUROC (does confidence rank errors?) | >= 0.65 (`MIN_AUROC`) |
| 4 | a calibrated threshold exists with out-of-fold precision at it | >= 0.90 (`MIN_PRECISION`) |
| 5 | Wilson 95% lower bound at that threshold | >= 0.85 (`MIN_WILSON_LB`) |
| 6 | distinct rows at or above the threshold | >= 50 (`MIN_ROWS_ABOVE`) |
| 7 | out-of-fold calibrated ECE | <= 0.05 (`MAX_ECE`) |

How the numbers are made:

- **Distinct rows.** Rows with the same (consumer, engine, rounded confidence, chosen,
  reference, label) collapse into one that carries `repeats`. A repeated input is not
  new evidence.
- **Label** (`decision_label`, one rule for the report and the calibration script).
  An `outside_label` (observed outcome, structural signal) is used first. Otherwise a
  shadow row is correct when the Oracle's answer equals the incumbent's recorded answer
  (`brain_choice` as a name, `brain_bool` as a bool). A dispatched row is correct when
  the event outcome is success. Not scoreable, counted and never scored: a shadow row
  whose reference was truncated off the scored menu, a control-label answer
  (`DELEGATE`/`NONE`) against a parity reference, an outcome-labelled row with no
  outside label, a row with no reference.
- **Confidence scale.** For a noul consumer, the confidence in the chosen answer.
- **Fit.** Isotonic (monotone) map from raw confidence to P(correct); pool-adjacent-
  violators with blocks pooled to at least 20 rows; 5-fold stratified out-of-fold
  predictions, so a map is never judged on its own rows. The threshold is the smallest
  calibrated value whose out-of-fold precision, Wilson bound and row count all hold.
- **Status** (`derive_status`): `enforced` when every clause holds; `sampled` when the
  bar is unmet, the consumer is sampling-eligible and has at least one outcome-labelled
  row; otherwise `shadow` with the first missing clause as the gap.
- **Persist.** `consumer_enforcement_report.py --write` writes
  `benchmarks/consumer_bar_record.json` with each consumer's own decision identity;
  `fit_oracle_calibration.py` writes `benchmarks/oracle_calibration.json` under the
  backend identity and under every consumer's decision identity. The calibration file is
  re-read when its mtime changes; the bar record is re-read on every `decides()` call. A
  new `--write` takes effect without a restart. The owner's allow-list is an environment
  variable and needs a restart.

**Staying accurate as tools are added or changed.**

- A new node tool must declare its decision line in `ORACLE_HINTS`
  (`test_oracle_tool_hints_contract` fails for a node tool without one).
- `menu_fp` on every row separates evidence measured on one menu from another.
- A frame or question change gets a new `criteria_version` stamp and its own cohort;
  a criteria or cap change changes `criteria_hash` and drops the old threshold.
- `scripts/replay_tool_choice.py` re-asks d1 on recorded `state` / menu under a variant
  and reports agreement and confidence bands without writing, so a design change is
  tested before any live run.
- After any of these the fit is re-run for the new cohort; the bar is re-earned.

**Limits.**

- A parity label caps a consumer at its incumbent's quality; consumers without an
  outside label (web_intent, user_feedback, presentation, narration, most monitors)
  measure agreement, not correctness.
- Its calibrated threshold applies to the cohort it was fitted on (`tc-decide-v3`).
- `call_closing` is measurement only by design.

---

## 6. Learning over time

- **The weights are fixed.** Nothing in the running app trains d1.
- **Traffic adds rows automatically.** Every node tool call writes lane rows (parity,
  approval, browser element) and, when it decided, an outcome-labelled row. Sampled
  consults and user/loop outcomes add outcome labels at turn end. Rows go through the
  single bridge writer into `data/memory.db`; the write-time dedupe is a bounded LRU
  (4096) keyed by consumer, engine, confidence, chosen, reference and scope.
- **Re-measure and refit are manual.** No scheduled job runs the report or the fit.
  An operator runs `consumer_enforcement_report.py --write` and
  `fit_oracle_calibration.py`, then the new bar and threshold apply to the next
  `decides()` call. Adding a consumer to enforcement is the owner's edit of
  `IRIS_DECISION_ENFORCE`.
- **Optional fine-tune path (manual, not part of the running app).**
  1. `scripts/export_tool_choice_training.py` writes JSONL examples: the exact prompt
     d1 reads, and the option code of a call that WORKED (an Oracle-decided row with
     `outside_label` True, or a `tc-frame-v6+` shadow row with `brain_ok` True). A
     failed, overridden or missing call is never a target.
  2. `scripts/finetune_d1_lora.py` trains a 4-bit LoRA on the one answer-slot token,
     with the same readout the app uses. The split is by task. It scores the held-out
     set before and after (accuracy, and accuracy per confidence band). The backend
     must be stopped first (the served d1 shares the GPU).
  3. `--merge` writes bf16 weights; the operator converts them with llama.cpp
     (`convert_hf_to_gguf.py`, `llama-quantize`) and serves the result.
  4. A merged model is a NEW identity (a different served file name; it must still
     contain `d1-3b`). Every consumer's calibration restarts; no threshold carries
     over. A fine-tune that does not raise held-out accuracy at high confidence is not
     shipped.

---

## 7. Performance and measurables

All figures are as of 2026-10-12.

### 7.1 Headline

| Measure | Value |
|---|---|
| `tool_choice` bar | passed: 388 distinct rows (294 correct, 94 wrong), OOF AUROC 0.754, OOF ECE 0.037 |
| `tool_choice` threshold | 0.790 calibrated (about 0.64 raw confidence); 201 rows above it; precision 0.9005; Wilson LB 0.851 |
| Oracle enforced live | node tool calls: coding 11/15, browser 10/10 (eval groups) |
| Live frontend browser runs | Oracle picks `browser_open` at confidence 0.92-0.923; `browser_act` at 0.73-0.80 |
| Decision latency | 112-302 ms typical; 2.1 s worst seen |
| d1 boot load | about 30 s warm |
| Model size on disk | `d1-3B-AD-Q4_K_M.gguf` 1.66 GB + `mmproj` 0.86 GB; shared with vision; the Oracle adds no second model |
| Fine-tune pilot (not shipped) | held-out accuracy 61.8% -> 76.5%; calls at confidence >= 0.9: 10 -> 25 of 68, at 92% accuracy |
| Routing | rules remain the incumbent; the Oracle is shadow for routing |
| `browser_next` | shadow only |

### 7.2 Per consumer (from `consumer_bar_record.json` and `oracle_calibration.json`)

Distinct rows and out-of-fold numbers on the running identity. "On" means in the
owner's `IRIS_DECISION_ENFORCE`; "earned" means the bar record says `enforced`.

| Consumer | Distinct rows | OOF AUROC | OOF ECE | Threshold | Status |
|---|---|---|---|---|---|
| `tool_choice` | 388 | 0.754 | 0.037 | 0.790 | earned, ON (decides node tool calls) |
| `escalate_incomplete` | 292 | 0.829 | 0.022 | 0.618 (273 above, precision 0.908, Wilson 0.868) | earned, not on |
| `narration` | 289 | 0.713 | 0.031 | 0.857 (151 above, precision 0.907, Wilson 0.850) | earned, not on |
| `review_verdict` | 950 | 0.617 | 0.045 | 0.786 (50 above) | sampled rung (AUROC below 0.65) |
| `tool_approval` | 1216 | 0.575 | 0.037 | none | shadow (AUROC below 0.65) |
| `depth_met` | 352 | 0.436 | 0.088 | none | shadow (AUROC below 0.65) |
| `call_closing` | 556 | 0.496 | - | none | shadow, refused by design |
| `web_intent` | 157 | 0.473 | 0.000 | none | shadow (AUROC below 0.65) |
| `user_feedback` | 128 | 0.454 | 0.021 | none | shadow (AUROC below 0.65) |
| `browser_next` | 76 | 0.634 | 0.101 | none | shadow (rows below 100) |
| `click_safety` 46, `event_family` 21, `depth_route` 17, `done` 12, `presentation` 9 | below 100 | - | - | none | shadow (rows below 100) |
| `needs_action`, `recovery_strategy`, `sufficient`, `use_thinking` | 0 | - | - | none | shadow (no rows) |

`event_type:<family>` consumers (1 to 13 rows each) are shadow. The bar record also
holds a row for the retired `mode` consumer; it is not a declared consumer.

Enforcement today: only `tool_choice` is on and earned, so only `tool_choice` decides.
The bar record's `precision` and `ece` fields are the pre-hardening scalars (0.0 and
null); the hardened numbers are in the calibration file (`oof` block).

### 7.3 Cost per decision

- One Oracle question is one forward pass of a 3B model, one output token.
- On the node path the pre-call `choose_node_tool` question is the only Oracle call a
  node waits for. For every executed call, up to three more consults run on the
  `oracle_shadow` lane (parity, approval, and browser element on a `browser_act`);
  none of them is on the answer path.
- Prefill is bounded by the job budget: 384 ids (1536 chars) for `route`/`approve`,
  at most 128 for the rest.
- The HTTP client is pooled; a fresh connection per decision measured about 400 ms of
  Windows TCP setup, a pooled one about 1 ms.
- Admission under `IRIS_ORACLE_PHASE=1`: no engine lock; each question is a
  participant `"{session}:{consumer}"` in the phase domain `decision.oracle_cpu`, and
  with `IRIS_ORACLE_PHASE_EXIT=1` a decision starts when a run slot frees (capacity
  `cores // intra_op`, which is 2); reply decisions have right of way; a gate fault
  admits (fail-open). Without the flag: one engine lock (`acquire_timeout_s` 2.0 s)
  and a single-worker inference thread; an overrun returns no verdict.
- Lanes (`backend/utils/durability_queue.lane`): one FIFO and one daemon worker per
  lane, bounded at 512 pending jobs. A full lane drops the job, counts it and logs it;
  `submit()` never blocks and never raises.

---

## 8. Operations

### 8.1 Environment flags

| Flag | Default | Effect |
|---|---|---|
| `IRIS_DECISION_ENFORCE` | empty (`.env` sets `tool_choice`) | comma list of consumers the owner lets decide; remove a name to return that decision to the incumbent |
| `IRIS_ORACLE_FORCE_MIN` | 0.9 | raw confidence a SAMPLED tool pick needs to be binding |
| `IRIS_ORACLE_SAMPLE` | on | `0` kills all sampling |
| `IRIS_ORACLE_SAMPLE_FRACTION` | 0.05 | sampled share for every samplable consumer |
| `IRIS_ORACLE_SAMPLE_FRACTION_<CONSUMER>` | unset | per-consumer share, for example `_TOOL_CHOICE=1` |
| `IRIS_ORACLE_SAMPLE_SIDE_EFFECTS` | unset | `1` lets a sampled pick force a side-effect tool (eval work folders only) |
| `IRIS_ORACLE_PHASE`, `IRIS_ORACLE_PHASE_EXIT` | `.env` sets both to 1 | phase-model admission; `0` returns to the engine lock |
| `IRIS_ORACLE_PHASE_PERIOD_S`, `_MAX_WAIT_S`, `_K` | 0.3, 0.3, 0.6 | phase gate tuning (timed gate) |
| `IRIS_ORACLE_BATCH_CAP` | 8 | width of a batched pass (no production caller) |
| `IRIS_ORACLE_REVIEW_OUTCOME` | off | stamps pending `review_verdict` rows with the step's settled label (VERIFIED / UNVERIFIED / FAILED) as the outside label |
| `IRIS_D1_CHECK_TTL_S`, `IRIS_D1_TIMEOUT_S`, `IRIS_D1_N_PROBS` | 300, 20, 512 | serving check cache, HTTP timeout, logprobs returned |
| `IRIS_LOCAL_MODEL_PORT` | 8082 | the shared llama-server port |

**Off switches.** Remove `tool_choice` from `IRIS_DECISION_ENFORCE`: the tool model
decides every call again (the sampled rung then applies at 5%, read-only tools,
confidence >= 0.9; set `IRIS_ORACLE_SAMPLE=0` to remove that too). Stop the shared
server or serve another model: every consumer returns to its incumbent.

### 8.2 Scripts

```
# per-consumer status vs the bar (read-only); --write persists the bar record
python scripts/consumer_enforcement_report.py [--json] [--write] [--scope tool_choice=tc-decide-v3]

# fit the calibration map and threshold (offline); --dry-run writes nothing
python scripts/fit_oracle_calibration.py [--dry-run] [--scope tool_choice=tc-decide-v3]

# reliability table, ECE/Brier, coverage curve, recommended threshold (read-only;
# refuses below 50 rows; exit 3 = insufficient data, 4 = store unreadable)
python scripts/calibrate_decision_threshold.py [--since ...] [--json]

# re-ask d1 on recorded tool_choice states under a variant (needs :8082; writes nothing)
python scripts/replay_tool_choice.py [--variants descriptions,hints] [--stamps tc-frame-v8] [--limit N]

# outcome-checked decisions -> fine-tuning JSONL (read-only on the store)
python scripts/export_tool_choice_training.py --out data/training/tool_choice.jsonl

# LoRA fine-tune of d1 (stop the backend first; base weights must be on disk)
python scripts/finetune_d1_lora.py --model <d1-3B dir> --data data/training/tool_choice.jsonl \
    --out <dir> --epochs 3 --merge
```

- `calibrate_decision_threshold.py` holds `decision_label`, the one labelling rule the
  report and the fit both import.
- `benchmarks/oracle_jobs_bench.py` measures per-job latency on the real model.
- Live validation of a change to the Oracle: `python evals/run_evals.py --group coding`
  and `--group browser` (and `research`); read pass and `reply_s` against
  `evals/standards.json`.
- The scripts take `--db`; the default is the store path from `scripts/_app_store.py`,
  which uses the application's own resolver (`resolve_memory_store_path`).

### 8.3 Reading the logs

- `Oracle enforcement: deciding=[...]; allow-listed but NOT deciding=[...]` - once per
  process; names the missing key for each listed consumer that does not decide.
- `[TOOL_DECISION] Oracle decides tool=... conf=... route=enforced|sampled` - a decided
  node pick. `Oracle decide ... decision_latency_ms=...` - one line per decision.
- `NOT enforcing <consumer> - its bar was measured on ...` - running identity differs
  from the one the bar was earned on. `thresholds are STALE` - deployed cap differs
  from `calibrated_cap`.
- `[InferenceRouter] named tool_choice refused ... retrying with auto` - a provider
  refused a forced pick; the pick was soft on that provider.

---

## 9. Contracts and guards

Under `backend/tests/` (`contract/` unless a path is given).

**Engine, identity, chokepoint**

- `test_decision_engine_contract.py`, `unit/test_decision_engine.py` - envelope shape, lazy lifecycle, degrade to `None`.
- `test_oracle_enforcement_contract.py` - `decides()` needs all four keys; default decides nothing.
- `test_bar_record_enforcement.py` - a flip fires only on the engine it was measured on.
- `test_decision_identity_contract.py` - `model|readout|criteria_hash`; a criteria or cap edit empties the threshold.
- `test_consumer_declarations_contract.py`, `test_consumer_registry.py`, `test_consumer_tasks_contract.py`, `test_surface_observer_contract.py` - declared types and criteria; an undeclared consumer scores nothing.
- `test_readonly_engine.py` - the engine writes nothing to the memory graph.
- `test_oracle_phase_contract.py`, `test_phase_domain_exit_admission.py`, `behavioral/test_oracle_phase_identity.py` - phase admission and identical answers alone and under load.

**Input, readout, jobs**

- `test_d1_native_readout_contract.py`, `test_d1_logprob_shape_contract.py` - the reference prompt and letter readout; token `id`, never `bytes[0]`.
- `test_oracle_jobs_contract.py`, `test_oracle_frame_evidence_contract.py` - the engine owns the input and budget; reference fields never reach the model; frames render their evidence.
- `test_oracle_batch_contract.py`, `behavioral/test_batch_single_encode.py` - batching isolation.

**Tool choice**

- `test_oracle_tool_hints_contract.py` - every node tool declares an `ORACLE_HINTS` line.
- `test_menu_composition_contract.py`, `test_tool_choice_menu_reachability_contract.py`, `test_shadow_tool_choice_menu.py` - control labels survive the cap; every tool is reachable; the shadow scores the offered menu.
- `unit/test_node_executor.py` - the node loop, including the forced pick.
- `test_sampled_rung_contract.py` - tiers, fraction, deterministic draw, read-only gate, outcome join.
- `unit/test_tool_decision_threshold_resolution.py`, `unit/test_threshold_retune.py` - the threshold is keyed to the active backend.

**Rows, labels, calibration**

- `test_decision_engine_ledger.py`, `test_shadow_row_sink.py`, `test_monitor_shadow_off_answer_path.py` - one ledger row per decision through the real bridge; shadow scoring off the answer path.
- `test_consumer_row_reference.py`, `test_oracle_reference_separation_contract.py`, `test_decision_label_unscoreable_contract.py` - every row has a reference; outside-label and incumbent curves never blend; off-menu and control-label rows are counted, not scored.
- `test_oracle_calibration_contract.py`, `test_consumer_bar_record.py`, `unit/test_consumer_enforcement_report.py`, `unit/test_calibration_quality.py` - confidence scale, distinct rows, the hardened bar, the report's label rules.
- `test_review_outcome_label_contract.py` - the review outcome-label wrapper.

**Per consumer**

- `test_tool_approval_contract.py` - the call's own result never enters the frame.
- `test_browser_next_contract.py` - page elements are the options; an unoffered element is unscoreable.
- `test_click_safety_contract.py` - browser actions pass the click-safety gate.
- `test_call_closing_fence_contract.py` - `call_closing` is refused everywhere; the node loop never reads it.
- `test_verdict_consumer_shape.py`, `test_presentation_observer_contract.py`, `behavioral/test_decision_engine_behavioral.py`, `behavioral/test_decision_engine_gates.py` - verdict envelope, presentation writes no steering field, a full DER step, surface and narration gates.

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
    approve job --- tool_approval (ENFORCED: the pre-call guard; post-hoc rows keep flowing)
    guard job ----- click_safety (shadow + refuse-only sample) | needs_action (v7, ENFORCED: the DIRECT/REACT mode rule)
    judge_review -- review_verdict (ENFORCED, refuse-only)
    judge_step ---- escalate_incomplete (ENFORCED)
    judge_goal ---- done | sufficient
    judge_depth --- depth_met (ENFORCED, tighten-only)
    judge_call ---- call_closing (REFUSED: measurement only)
    shape job ----- presentation | narration
    interpret job - web_intent (v2, turn-outcome label) | user_feedback
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
- After d1 is resident, `_boot_load_d1` proves the shared server multimodal once (`[D1BOOT] vision verdict proved in N s`); a proven verdict does not expire (a failed vision call drops it). Before 2026-10-13 a 300 s re-probe sent a 1x1 PNG inside turns and held the one-slot server 13.6 s while the node's `tool_choice` decision waited 9.8 s.
- d1 starts with `--cache-ram 0` (`local_model_manager._build_server_cmd`, d1-3b models only): Oracle prompts share about 4 tokens, so the host prompt cache never paid, yet it kept every prompt. After one eval run it held 592 prompts / 1.6 GB, each decision spent 240-380 ms on the cache update (3-6 ms after boot), and its per-request listing wrote about 10 MB/min to the backend log. After: no cache updates; a whole backend run logged 6.5 MB.

---

## 3. Concepts

### 3.1 Consumers

A consumer is one decision point (one question asked at one place in the app).
Each has an id, a declared decision type and criteria, and one job.

`CONSUMER_DECLARATIONS` (`decision_engine.py`) declares the type of every consumer below. `CONSUMERS` is the smaller set of 14 ids the owner can switch on; `click_safety`, `browser_next`, `user_feedback` and the event consumers are declared but are not members of it (`tool_approval` joined 2026-10-18 when its pre-call guard became its live decision).

| Consumer | Job | Type | Incumbent that decides today | Where |
|---|---|---|---|---|
| `tool_choice` | route | choice | the tool model | node loop (`choose_node_tool`, enforced) and post-hoc shadow row |
| `tool_approval` | approve | noul | none (labelled by the call-level outcome) | `tool_approval_shadow` post-hoc; ENFORCED: the pre-call guard in `node_executor.run_node` |
| `browser_next` | route | choice | the tool model's element pick | `browser_next_shadow`, each `browser_act` |
| `click_safety` | guard | choice (safe/unsafe/unsure) | rules, then Brain judge, then ask the user | `tools/browser_tools.py`, `click_safety_shadow` |
| `recovery_strategy` | route | choice | the recovery ladder | `ToolDecisionBox.recovery_strategy` |
| `depth_route` | route | choice | the loop's own continuation | `ToolDecisionBox.depth_route` |
| `review_verdict` | judge_review | choice (pass/refine/veto) | the Brain reviewer | `der_loop.Reviewer`; ENFORCED, refuse-only, outcome-labelled |
| `escalate_incomplete` | judge_step | noul | incomplete-result keyword list | `der_loop` |
| `done`, `sufficient` | judge_goal | noul | Brain done-bit / sufficiency gate | `monitor_shadow` |
| `depth_met` | judge_depth | noul | the loop's run grade below threshold | `surface_shadow`, run-grade point; ENFORCED, tighten-only, labelled by the EXTERNAL turn verdict |
| `needs_action` | interpret_step | noul | the node mode rule (`external_reference.mode_for_goal`: DIRECT only for a question-word goal) | `agent_kernel._der_run_node`: outcome row at each REACT node end; v7, shadow (see 7.2/7.4) |
| `presentation` | shape | choice | reply-surface rules | `agent_kernel` reply surface |
| `narration` | shape | choice | deterministic beat rule | `agent_kernel` |
| `web_intent` | interpret | noul | duplicated web-trigger keyword lists | `explorer`; v2 turn-outcome label |
| `user_feedback` | interpret | choice | none (a Brain sample is the reference) | `event_oracle` |
| `event_family`, `event_type:<family>` | classify_event | choice | rule label, Brain sample | `event_oracle` |
| `call_closing` | judge_call | noul | the node closing rule | measurement only |

Rules of the registry:

- A consumer with NO declared decision type is registered undeclared and is never
  scored: the engine logs it and the d1 backend refuses it (`decision_backend_d1.py`).
  It never borrows another consumer's shape.
- `event_type:<family>` consumers inherit the `event_family` declaration.
- `REFUSED_CONSUMERS = {"call_closing"}`: never enforced, never sampled, never
  resolved to a threshold, whatever any flag says. It is asked only about calls that
  claimed to close a step and never about a call that changed a file.
- The owner's allow-list (`IRIS_DECISION_ENFORCE`) only accepts ids that are members
  of `CONSUMERS`. `tool_approval`, `click_safety`, `browser_next`, `user_feedback` and
  the event consumers cannot be switched on by that flag.
- Retired and absent: `mode`, `on_track`, `has_gaps`, `retry_same`. `tier0_classify`
  is a recorded non-fit (a sub-millisecond rule would become a ~150 ms model call). `use_thinking` (removed 2026-10-13, owner: models think natively, Mercury ignores the thinking flag, and its only callers were dead dispatch paths; `_needs_thinking` keeps its phrase rule).

### 3.2 Jobs (`ORACLE_JOBS`)

A job is the KIND of question. It fixes what the model reads (which frame fields, in
which order) and how much (a text budget in token ids). The engine builds the input;
a call site cannot make it longer, shorter or blind. Fields not declared by the job are
dropped by `job_input()`. Reference fields (`incumbent_route`, `brain_*`) are never
declared, because an input that carries the answer measures nothing.

| Job | Question | Declared fields (render order) | Budget (ids) |
|---|---|---|---|
| `route` | which of these next actions? | coverage, open_facts, depth_met, grade, goal, done_when, calls_this_step, step_facts, last_result, task_class, previous_chosen, previous_outcome, step_index, needs_vision, vision_candidates, ruled_out, error_snippet, pushes_used | 384 |
| `approve` | will this call succeed? | goal, calls_this_step, last_result, proposed_tool, tool_description, args, offered_tools | 384 |
| `guard` | is this action safe without asking? | goal; image field `screenshot` | 128 |
| `interpret_step` | does this STEP need a tool, or does it only answer from what is known? | goal, expected | 160 |
| `interpret` | what does the user's message mean? | goal | 64 |
| `judge_step` | did this step do its part? | goal | 96 |
| `judge_review` | did this step do its part? | goal | 288 |
| `judge_goal` | is the objective met, deep and sufficient? | goal, open_facts, evidence | 128 |
| `judge_depth` | is the objective met, deep and sufficient? | evidence, coverage, open_facts, goal | 384 |
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
precondition" line per tool (25 node tools plus the two controls), for example `read_file`:
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
  parity rows), `tc-decide-v3` (Oracle-decided rows), `tool_approval/v6`,
  `browser_next/v1`, `needs_action/v7`, `review_verdict/v4`, `depth_met/v3`,
  `web_intent/v3`. The report and the fit take `--scope CONSUMER=STAMP` to measure
  one cohort and never blend two. A stamp is never reused: v2 of
  `review_verdict` was withdrawn (62 obsolete rows) and v5 of `tool_approval`
  was superseded the same day, and neither name comes back.

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

**Threshold on the raw scale.** `EngineConfig.threshold_for(consumer)` serves callers that hold a RAW confidence (the evidence-prior cap, ledger rows, `recovery_strategy`/`depth_route` rows, the presentation surface). It reads an explicit per-consumer override, then `agent_config.yaml` `backend_thresholds` (retired backends only: `lfm2-350m-extract`, `gliner25-decide-onnx-int8`), then the fitted curve for the active decision identity through `oracle_calibration.raw_threshold`: the smallest raw confidence whose calibrated value clears the fitted threshold (`tool_choice` 0.6407 raw = 0.7902 calibrated). Before 2026-10-13 the last step did not exist: the yaml store has no d1 key, so every d1 row recorded threshold 1.01 and `ToolDecisionBox` logged a false "no threshold for the active backend" warning. Enforcement itself never read that store; it reads `decides()` / `oracle_acts()`. Guard: `test_raw_threshold_contract.py`.

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
The node tool set (25 tools) plus the two controls fits whole (27 options); with the 5 screen tools the menu is exactly 32. The cap is inside
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

Other call sites read the same chokepoint (`needs_action`,
`sufficient`, `depth_met`, `done`, `escalate_incomplete`, `web_intent`,
`recovery_strategy`, `presentation`). `ToolDecisionBox.resolve()` and
`explorer.propose()` also gate on `decides("tool_choice")` but have no production
caller; the DER node path is the live deciding path.

### 4.1 needs_action: the step mode

Each DER step runs DIRECT (one text answer, no tools) or REACT (the tool loop). The rule `external_reference.mode_for_goal` picks DIRECT only for a goal that opens with a question word; a REACT step that needs no tool pays a full tool-loop call and makes zero calls.

**Label (v6, unchanged in v7).** At the end of every REACT step `_der_run_node` writes one `needs_action` row on the `oracle_shadow` lane (`surface_shadow._submit_shadow(..., outside_label=...)`, `criteria_version` `needs_action/v7`, `label_source` `outcome`). The label comes from `surface_shadow.needs_action_label(goal, calls, success)`:

- a call that RAN and a goal that names an action ANYWHERE -> True (a tool was needed);
- a call that RAN and a goal that names NO action anywhere (`_NA_ACTION_ANYWHERE`) -> NO ROW (v6, the mirror rule): the loop forced that call, the goal did not. v5 counted these as True; they are 6% of rows and 45% of the error mass, and their label is a coin flip (30 of 79 ran a call) - the signature of a non-causal label;
- zero calls, a successful step, and a goal that does not name a tool action -> False;
- zero calls, a successful step, and an ACTION-led goal ("Run main.py to verify...", "Write the slugify function to textutils.py") -> NO ROW: that is a slip, not proof the goal needed no tool. v3 counted these as False and poisoned 15 of 294 real pairs;
- a planner artifact ("Duplicate of step 1 (already completed)...") -> no row;
- a call set with no successful call -> no row.

`brain_bool` is the rule's answer (True: the rule chose REACT).

**Decision.** With `needs_action` enforced, before the tool loop starts the Oracle is asked; a 'no tool' answer whose calibrated confidence clears the threshold moves the step to DIRECT. The rule's own DIRECT choices are never changed. A step moved to DIRECT writes no outcome row, so later cohorts see fewer of those cases.

**Question (v7).** 'Does this step take an ACTION in the project - read, write, edit, create, implement, fix, run, search or browse - or does it only give an ANSWER from what is already known? Decide about the action the step must perform, not about the wording of the goal.'

v5 history (kept): measured 2026-10-19 on 294 real goal+outcome pairs, the write/edit/update/add goals were misread as 'no' whenever the artifact verb sat on the answer side; v4 put the verbs on the yes side, then the live replay showed the model judged the WORDING of the goal (a READ goal read 'no' at 0.82, an EDIT goal at 0.65). v5 added the action/wording clause: live 11/11 on real (goal, expected_output) pairs and 10/11 on the hard probe. A variant that also names 'a file'/'a command' scores 20/22: the nouns pull analysis steps to 'yes'.

v7 (2026-10-20): measured by full-cohort replay on the 474 distinct recorded inputs (the honest v6 cohort, input_key-joined to the backend log), judged by `fit_consumer` with the acting-aware threshold pick. v5's yes side is a CLOSED verb list, and the remaining wrong acting "no"s are action goals whose verbs sit outside it ('Implement the parse_duration function based on tests' 0.84, 'Create inventory.py...' 0.79, 'Fix the identified bugs...' 0.71). Adding create/implement/fix to the list is the whole change: OOF AUROC 0.8345, ECE 0.025, threshold 0.8041 (398 above, precision 0.9648, Wilson 0.9418), ACTING 58 rows at 0.9483 (Wilson 0.8586) - every clause met on the replay. Two prose variants that describe the fetch/change outcome instead of listing verbs score WORSE (AUROC 0.80/0.81, no threshold): d1 reads the closed verb list better than prose. The label rule and the frame are unchanged from v6; the stamp moved to `needs_action/v7`.

**Frame (v4/v5).** Job `interpret_step`, fields `goal, expected` (160 ids). The `expected` field is what moved four hard write goals from 'no' (0.95-0.99) to 'yes' (0.77-0.86) in the offline probe.

RESOLVED 2026-10-19: the planner now declares `expected_output`. The prompt carries the field, `_plan_task` passes it onto `PlanStep`, and the plan-to-queue conversion was dropping it (every node item had `expected_output=None`); it now carries it through. Live verification: empty in 21/21 rows before, populated after ("Successful execution of app.py without errors"). The user request is NOT a substitute for it: frame `goal+request` scores 7/12 - a request that mentions running tests makes analysis steps read as tool-needing.

**State (2026-10-21, v7, live gate passed).** 641 distinct rows (598 correct / 43 wrong) on the running identity, OOF AUROC 0.8634, OOF ECE 0.0167, calibrated threshold 0.6244 (614 rows above, precision 0.9479, Wilson 0.9274). Clause 8 on live traffic: the acting answer ("no") holds 101 rows above the threshold at precision 0.9208 (Wilson 0.8514). Every clause of the hardened bar is met; the bar record was written scoped (`--scope needs_action=needs_action/v7` with a scope for every enforced consumer) and `decides("needs_action")` returns 0.6244 - the consumer is ON. The full-corpus replay (981 recorded inputs, both eras, re-scored under the v7 question) had predicted exactly this: threshold 0.8362, acting 121 rows at 0.9174 - the live gate confirmed it (see 7.2a).

The count itself is new: until 2026-10-20 the report's dedupe key had no input identity, and the quantized engine emits few distinct confidences, so DIFFERENT goals with equal (confidence, chosen) collapsed - 483 real sites (474 distinct goals) counted as 226. `surface_shadow.input_key` now binds each row to its input at the call site; the report prefers it; the existing cohorts were backfilled from the backend logs (positional join on the FIFO lane, verified on step_id + label). The key also had to be added to the bridge's `_DECISION_META_KEYS` whitelist - without it every row written through the bridge reached the ledger without the key (435 v7 rows; found and fixed 2026-10-21).

**History.** v1 earned the bar on 2026-10-13 (235 rows, 216 distinct, OOF AUROC 0.8043, ECE 0.0404, precision 0.9174 at 109 rows above) and was demoted 2026-10-18 when the label was found to count the loop's `ok` instead of the call outcome, which turned informative pytest runs into 'no tool needed' rows. v2 (call-level label) and v3 (concrete-outcome question) never re-earned the bar.

---

## 5. The bar

A consumer moves shadow -> enforced only on measured evidence. The measurement is
`scripts/consumer_enforcement_report.py` using the out-of-fold fit in
`scripts/fit_oracle_calibration.py`; the clauses are `consumer_bar._derive_hardened`.
All must hold, and the first one missing is recorded as the gap:

| # | Clause | Value |
|---|---|---|
| 1 | distinct rows | >= 100 (`MIN_ROWS`) |
| 2 | both classes present; minority share | >= 5% (`MIN_MINORITY`) - or the NO-ERROR-MASS WAIVER: when the wrong class is under 5% because the data statistically EXCLUDES a 5% error rate (one-sided binomial, p <= `WAIVER_ALPHA` 0.01), clauses 2 and 3 are untestable rather than failed and the remaining clauses carry the certification; the waiver is re-derived on every recompute and recloses the moment real errors reach 5% (2026-10-22, owner-approved after measurement: tool_choice/v4 held 2 wrong in 275 rows where a 5% rate would have shown ~14) |
| 3 | out-of-fold AUROC (does confidence rank errors?) | >= 0.65 (`MIN_AUROC`) |
| 4 | a calibrated threshold exists with out-of-fold precision at it | >= 0.90 (`MIN_PRECISION`) |
| 5 | Wilson 95% lower bound at that threshold | >= 0.85 (`MIN_WILSON_LB`) |
| 6 | distinct rows at or above the threshold | >= 50 (`MIN_ROWS_ABOVE`) |
| 7 | out-of-fold calibrated ECE | <= 0.05 (`MAX_ECE`) |
| 8 | ACTING clause (asymmetric consumers only): rows above the threshold that carry the answer which changes behaviour | >= 50 (`MIN_ACTING_ROWS_ABOVE`), precision >= 0.90, Wilson LB >= 0.85 |

**Clause 8 - why it exists (2026-10-19).** Clauses 4-6 measure precision over the
confidence in the CHOSEN answer. For a consumer that changes behaviour in one
direction only, the other direction can carry that precision while the acting
side is unsafe. Measured on `needs_action/v5` (111 rows): aggregate precision
0.9492 at the fitted threshold passed every clause, while the acting answer
("no tool needed", the only one that moves a step to DIRECT) stood at 13 rows
above the threshold and precision 0.71. The consumer is now `sampled`, with the
acting gap recorded. `ACTING_ANSWER` declares which answer acts per consumer;
`ACTING_ENFORCED` lists the consumers that have ADOPTED the clause (today
`needs_action` only). Adoption is explicit so a report run can never silently
demote a consumer that is already deciding (that would be a policy change
disguised as a measurement).

The report checks the clauses in this order and names the first one that fails: rows, both classes, minority share, AUROC, a threshold exists, rows at or above it, precision, Wilson bound, ECE.

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
  calibrated value whose out-of-fold precision, Wilson bound and row count all hold -
  and, for a consumer in `ACTING_ENFORCED`, whose ACTING-side clauses also hold at it
  (6.1 rule 5; without this the clean non-acting side drags the pick to the floor).
- **Status** (`derive_status`): `enforced` when every clause holds; `sampled` when the
  bar is unmet, the consumer is sampling-eligible and has at least one outcome-labelled
  row; otherwise `shadow` with the first missing clause as the gap.
- **Persist.** `consumer_enforcement_report.py --write` writes
  `benchmarks/consumer_bar_record.json` with each consumer's own decision identity;
  `fit_oracle_calibration.py` writes `benchmarks/oracle_calibration.json` under the
  backend identity and under every consumer's decision identity. The calibration file is
  re-read when its mtime changes; the bar record is re-read on every `decides()` call. A
  new `--write` takes effect without a restart. The owner's allow-list is an environment
  variable and needs a restart. Measure a consumer on its own cohort: `--scope tool_choice=tc-decide-v3` (the flag repeats for more consumers; a comma list is not supported). Unscoped, `tool_choice` blends the `tc-frame-*` parity rows with the decided rows and fails the bar (2026-10-13: 1977 rows, AUROC 0.6836, no threshold), so a `--write` without the scope would remove its enforced status.

**Staying accurate as tools are added or changed.**

- A new node tool must declare its decision line in `ORACLE_HINTS`
  (`test_oracle_tool_hints_contract` fails for a node tool without one).
- `menu_fp` on every row separates evidence measured on one menu from another.
- A frame or question change gets a new `criteria_version` stamp and its own cohort;
  a criteria or cap change changes `criteria_hash` and drops the old threshold.
- `scripts/replay_tool_choice.py` re-asks d1 on recorded `state` / menu under a variant
  and reports agreement and confidence bands without writing, so a design change is
  tested before any live run.
- Since 2026-10-17 every `review_verdict`, `tool_approval` and `web_intent` consult
  also logs its rendered frame (a step- or turn-keyed DEBUG line in the backend log),
  so a live cohort can be replayed against a changed frame or question even though
  the ledger row does not store the state. Join by the logged key, never by sequence
  (an order-based pairing across runs measured 0.7429 on misaligned pairs - noise).
- `depth_met`'s outside label arrives from OUTSIDE the process: the eval harness
  reports each turn's hidden-test verdict to `POST /api/eval/verdict`
  (`backend/api/eval_verdict.py`), and `turn_verdict_label` holds the row until it
  arrives (bounded, swept, counted). A live turn's honest label - a user correction
  or a re-ask - can use the same endpoint.
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

### 6.1 Traffic methodology (measured 2026-10-13..20)

Traffic buys ROWS, not truth. Every defect this file records was found OFFLINE on
recorded rows, and the passes run before these rules were measured were partly
wasted. The rules, each one paid for:

1. **One input, one row.** A row counts once per distinct input
   (`surface_shadow.input_key`, bound at the call site), never once per rescore.
   Before the key existed the report's dedupe used the rounded confidence, and the
   quantized engine emits few distinct confidences, so DIFFERENT goals collapsed:
   483 real sites counted as 226 (7.2a). After every pass, read the raw/distinct
   ratio and `skipped["duplicates"]`: a pass that adds rows without adding distinct
   inputs added nothing.
2. **Diagnose offline, confirm with traffic.** A question, label or frame change is
   measured by replay on the recorded cohort first
   (`scripts/replay_needs_action.py`; `scripts/replay_tool_choice.py` for the tool
   menu). v4, v5, v6 and v7 of `needs_action` were each found and proven this way -
   minutes of engine time. A full eval pass is ~2 hours and can only CONFIRM a fix;
   it can never find one. Traffic is the last step, never the loop.
3. **Never feed a quality-blocked consumer.** Rows cannot fix OOF AUROC < 0.65
   (`web_intent` 0.46, `call_closing` 0.50, `depth_met` unscoped 0.52, `depth_route`
   0.56, `tool_approval` post-hoc 0.60, `done` 0.62 - see 7.2). For those, fix the
   question or the label on the rows already recorded; more traffic is more of the
   same noise at the same cost.
4. **Volume-blocked consumers fill themselves.** Consumers that fire every turn
   (`event_family`, `mode`, `presentation`, `event_type:*`) reach 100 rows from
   ordinary passes. No dedicated traffic is ever spent on them.
5. **The threshold pick honours the acting side** (2026-10-20). For an asymmetric
   consumer the clean non-acting side drags the smallest qualifying threshold to
   the floor, and clause 8 then judges every acting answer ever given, including the
   weak ones the threshold exists to exclude (measured: `needs_action` yes side
   0.98 clean, threshold picked at 0.4762, acting precision 0.8172 judged there).
   `pick_threshold` now requires the acting clauses at the picked threshold, so the
   pick can only move UP - more restrictive, never less.
6. **The measured sequence for one consumer:** replay -> fix -> stamp a new
   `criteria_version` -> ONE pass -> scoped report -> bar record (`--write` with a
   scope for EVERY enforced consumer, or the recompute demotes them) -> the owner's
   `IRIS_DECISION_ENFORCE`. Repeated passes over one fixed task set are not a path
   to the bar (7.2a: rows doubled while true distinct grew by 10).

---

## 7. Performance and measurables

Figures in 7.1 are as of 2026-10-12 unless dated. Table 7.2 is the measurement of 2026-10-13 evening after two full eval rounds; the bar record and calibration were written that evening with `--scope needs_action=needs_action/v1 --scope tool_choice=tc-decide-v3`.

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

| Consumer | Distinct rows (correct/wrong) | OOF AUROC | OOF ECE | Threshold (rows above, precision, Wilson) | Measured status | Gap |
|---|---|---|---|---|---|---|
| `tool_choice` (scope `tc-decide-v4`, 2026-10-22) | 275 (273/2) | untestable (waiver: 2 wrong in 275 rows excludes a 5% rate, p < 1e-5) | 0.0034 | 0.9524 (275, 0.9927, 0.9739) | meets the bar; ON - the no-error-mass waiver, named in the record | - |
| `escalate_incomplete` (2026-10-13) | 513 (446/67) | 0.8403 | 0.0335 | 0.4675 (478, 0.9038, 0.874) | meets the bar; ON | - |
| `review_verdict` (scope `review_verdict/v4`, 2026-10-21 recompute) | 1464 (1142/322) | 0.6563 | 0.0164 | none | sampled: DEMOTED 2026-10-21 - the grown cohort (184 -> 1464 rows) holds no 0.90-precision threshold | re-earn on a frame revision, measured offline first |
| `depth_met` (scope `depth_met/v3`, 2026-10-18) | 303 | 0.7103 | 0.0208 | 0.8963 (90, 0.9333, 0.8621) | meets the bar; ON (tighten-only) | - |
| `tool_approval` (scope `tool_approval/v6`, 2026-10-21 recompute) | 2143 (1524/619) | 0.6816 | 0.0096 | 0.7908 (474, 0.9008, 0.8706) | meets the bar; ON (the pre-call guard) | - |
| `needs_action` (scope `needs_action/v7`, 2026-10-21) | 641 (598/43) | 0.8634 | 0.0167 | 0.6244 (614, 0.9479, 0.9274) | meets the bar; ON - ACTING: 101 rows above at 0.9208 (Wilson 0.8514) | - |
| `user_feedback` (2026-10-21 recompute) | 628 (535/93) | 0.8808 | 0.0325 | 0.0005 (594, 0.9007, 0.874) | enforced in the bar record; no live decision site | wire a decision site |
| `narration` (2026-10-21 recompute) | - | - | - | - | enforced in the bar record | - |
| `web_intent` (scope `web_intent/v2`) | 607 (462/145) | 0.4433 | 0.0434 | none | shadow | AUROC < 0.65 (quality-blocked: fix the question/label offline, never with traffic) |
| `browser_next` | 126 (71/55) | 0.7059 | 0.095 | none | shadow | no threshold reaches precision 0.90 on 50 rows |
| `call_closing` | 657 (122/535) | 0.4998 | 0.0 | none | shadow, refused by design | AUROC < 0.65 |
| `click_safety` | 92 (89/3) | 0.3034 | 0.0003 | 0.9595 | shadow | rows < 100 (and minority < 5%) |
| `depth_route` 27, `event_family` 99, `done` 47, `presentation` 48, `event_type:*` 1-53, `mode` (retired) 77 | below 100 | - | - | none | shadow | rows < 100 |
| `recovery_strategy`, `sufficient` | 0 on d1 | - | - | none | shadow | failure-only paths (below) |

### 7.2a The directional split: an aggregate bar can pass on the side that changes nothing

`needs_action` met every clause on 2026-10-19 (111 distinct, OOF AUROC 0.6926,
ECE 0.0414, threshold 0.8278, 59 rows above, precision 0.9492, Wilson 0.8608).
The flip would have been unsafe, and the reason is in the metric, not the code.

Only a "no tool needed" answer CHANGES behaviour: it moves a REACT step to
DIRECT. A confident "yes" changes nothing (the rule already chose REACT). The
bar's precision is over the confidence in the CHOSEN answer, so both directions
pool into one number. Measured on the same 111 scored rows:

| Threshold | Rows above | Precision (all) | No-side rows | No-side precision | Yes-side rows | Yes-side precision |
|---|---|---|---|---|---|---|
| 0.8278 | 76 | 0.868 | 17 | 0.706 | 59 | 0.915 |
| 0.90 | 51 | 0.902 | 13 | 0.769 | 38 | 0.947 |
| 0.95 | 24 | 1.000 | 7 | 1.000 | 17 | 1.000 |

**Traffic does not fix it (measured 2026-10-19/20, three coding passes).** The
same 24 coding tasks ran three times:

| Pass | Distinct rows | Fitted threshold | No-side rows above | No-side precision | TRUE distinct no-pairs |
|---|---|---|---|---|---|
| 1 (mixed groups) | 111 | 0.8278 | 13 | 0.71 | 26 |
| 2 (coding) | 156 | 0.9065 | 11 | 0.91 | 31 |
| 3 (coding) | 214 | 0.8312 | 16 | 0.75 | 36 |

Rows doubled (+103) while the true number of distinct "no" inputs grew by 10:
a repeat of the same task produces the same goal text with a slightly different
confidence, which the dedupe key counts as new. That is row inflation, not
evidence. The acting pocket also moves AGAINST the traffic: more "yes" rows lift
the fitted threshold, and the "no" rows then sit below it (13 -> 11 -> 16 rows
across passes whose thresholds moved 0.83 -> 0.91 -> 0.83). Its precision swings
0.71 -> 0.91 -> 0.75 on 11-16 rows. ECE also drifts toward the bound
(0.0414 -> 0.0454 -> 0.0493). Conclusion: needs_action needs DISTINCT analysis
steps, not more runs of the same tasks; repeated passes are not a path to
clause 8.

**28 distinct analysis tasks did not fix it either (2026-10-20).** c25-c52 were
authored for exactly this (read a file or run a command, then state one exact
fact; no edits; 27/28 pass). They added 21 distinct "no" goals and 58 distinct
rows (214 -> 272, threshold 0.8576, 92 above, 0.9239, Wilson 0.8512, ECE 0.0414,
AUROC 0.6543). The acting side moved 16 -> 18 rows above the CALIBRATED
threshold. On RAW confidence in the chosen answer, the 79 "no" rows distribute:

| Confidence band | No-rows | Precision |
|---|---|---|
| 0.50-0.60 | 2 | 0.500 |
| 0.60-0.70 | 12 | 0.583 |
| 0.70-0.80 | 14 | 0.500 |
| 0.80-0.90 | 30 | 0.600 |
| 0.90-0.95 | 14 | 0.429 |
| 0.95-1.00 | 7 | 1.000 |

Above the fitted threshold: 39 rows at 0.615. Above 0.90: 21 rows at 0.619.
Above 0.95: 7 rows at 1.000.

The bands are flat from 0.50 to 0.95 (0.43-0.60) and only the last one is clean.

**The cause was the LABEL, not the model (found later the same day).** The first
reading of that table - "the question cannot rank its own no answers" - was
wrong, and the measurement that overturned it is per goal SHAPE. On 495 real
(goal, expected) pairs scored with the live v5 question, split by shape:

| Shape | Label | n | Model says "no" | Accuracy |
|---|---|---|---|---|
| A analysis verb + an action verb later | True | 29 | 3 | 0.90 |
| B analysis verb, NO action verb | True | 30 | 24 | **0.20** |
| B analysis verb, NO action verb | False | 49 | 39 | 0.80 |
| C action verb leads | True | 345 | 6 | 0.98 |
| D other | - | 32 | - | 0.81 |

Group B run with a call is 6% of the rows and 45% of the error mass (24 of 53).
Its label is also UNSTABLE: for an identical shape, 30 of 79 ran a call - a coin
flip. That is the signature of a non-causal label: the call was the REACT loop's
choice, not a property of the goal. The label rule said "a call that RAN = a tool
was needed", so an analysis step where the loop re-read material already in
context was scored as needing a tool, and a CORRECT "no" became an error.

v6 (2026-10-20) refuses that row, symmetric with the v4 slip rule ("a goal that
names an action completed with no call is a slip"). A goal that names no action
ANYWHERE (`_NA_ACTION_ANYWHERE`) yet ran a call did not force that call. The
stamp moved to `needs_action/v6`; the question and the frame are unchanged.

Effect on the first 24 v6 rows: raw AUROC 0.825 (v5: 0.665), acting side 8 of 8
correct. The signal was there all along and the label mixture had destroyed it.
The lesson is the general one this file keeps recording: when a confidence table
is flat, suspect the LABEL before the model, and split by shape before
concluding a capability limit.

The pass is carried by the yes side. At the fitted threshold, ~29% of the
confident "no" decisions are wrong: 5 of 17 steps would be sent to DIRECT when
they needed a tool. At 0.95 the no side is clean (7/7) but has 7 rows - it needs
50 before it can be trusted.

**The instrument was starving the bar, not the traffic (2026-10-20).** The
dedupe key was (consumer, engine, confidence, chosen, reference, correct) with
no input identity, and the quantized engine emits few distinct confidences, so
DIFFERENT goals with equal (confidence, chosen) collapsed into one row. Two
full passes wrote 483 real sites - 474 distinct goals, measured from the
backend log's `[needs_action]` lines - and the report counted 226. The earlier
"row inflation" reading above was half right for the wrong reason: repeats do
slip through when their confidence jitters, but the dominant error on this
cohort was the opposite one, collapse. Both failures have one cause: the key
does not name the input.

The fix is `surface_shadow.input_key` (sha1 of consumer + statement + frame,
bound at the call site, stamped on every new row); the report prefers it when
present and falls back to the legacy tuple for old rows. The existing v6
cohort was backfilled in one pass: the `oracle_shadow` lane is FIFO with one
writer and zero measured drops, so DB insertion order equals log line order;
each row was joined to its log line and verified on (step_id, label) - 483/483
matched, 472 distinct inputs, 11 true repeats now collapse honestly.

On the honest count every aggregate clause passes (472 rows, OOF AUROC 0.8309,
ECE 0.0146, threshold 0.62, 472 above at 0.9153, Wilson 0.8867) and the acting
row count passes (89 >= 50). What still fails is acting PRECISION: 0.8427
(Wilson 0.7531) < 0.90. The wrong "no"s pulled up by input key are action
goals read as answerable: "Implement the parse_duration function based on
tests" (0.84), "Create inventory.py with the Inventory class..." (0.79), "Fix
the identified bugs in the geometry module." (0.71), "Implement the
balance_on(date) method in the Ledger class" (0.89), "Compile and return the
list of failing test names" (0.86), "Read the contents of textstats.py to
identify the function with wrong results" (0.84). The next question revision
is measured OFFLINE on these recorded rows - the v4/v5/v6 sequence each took
minutes on recorded pairs, and each traffic pass costs two hours. Traffic is
the confirmation step, never the diagnosis step.

The same collapse applies to every consumer whose rows lack an input key, so
the honest distinct counts in 7.2 are lower bounds for them.

**The v7 live seeding (2026-10-21 night) - three findings.**

1. THE WHITELIST DROP. The bridge's `_DECISION_META_KEYS` whitelist did not
   carry `input_key`, so every row written through the bridge reached the
   ledger WITHOUT it: a full seeding pass (435 needs_action/v7 rows)
   deduped on the confidence tuple - the exact collapse the key exists to
   prevent. Found by the join audit (0 of 435 rows carried the key while the
   call site stamped every one); fixed the same day, and the 435 rows were
   backfilled by the same verified FIFO log join across the five sequential
   v7-era backends (435/435 matched on (step_id, label), 428 distinct
   inputs). Lesson: a new row field must be added to the whitelist in the
   same change, or it silently never lands.

2. THE 10 WRONG ACTING "NO"S, CLASSIFIED BY WHAT THE STEP ACTUALLY DID
   (pulled from the log's tool-dispatch lines around each site). Seven are
   GENUINE model errors and two question gaps: a write goal with no file
   named ("Write the Inventory class code..." at 0.90 while the step ran
   write_file) and web-material goals ("Extract ... from the page" at 0.96
   while the step ran browser_act). Three are LABEL defects: the noun "a
   copy" matches the verb "copy" in `_NA_ACTION_ANYWHERE`; "modify" sits in
   the label's action regex but not in the question's verb list, so the
   model is scored against actions it was never taught; and an action-led
   goal whose step only listed/read because the action happened in another
   step. The label-defect class is the v6 mirror in new shapes - when model
   and label disagree, audit the label first.

3. THE FULL-CORPUS REPLAY MEETS THE BAR. All 981 recorded inputs from both
   eras (the v6-era goals carry the same label rule; v7 changed only the
   question), re-scored through the real engine under the CURRENT v7
   question and frame, judged by `fit_consumer(acting="no")` with the
   acting-aware pick: threshold 0.8362, 837 rows above at precision 0.9606
   (Wilson 0.9451), ACTING 121 rows at 0.9174 (Wilson 0.8545) - every
   clause met. The live 445-row cohort fails only on volume: the v7 era had
   run 1.5 passes; the corpus is the two-pass size. A label variant (L3:
   the action regex narrowed to the question's own verb list, plus an
   article guard so "a copy" is a noun) also passes on the same corpus
   (acting 171 rows at 0.9181, Wilson 0.8673) and is the next lever if the
   live gate lands marginal.

Finding (2026-10-19): for an ASYMMETRIC consumer (only one direction acts) the
bar must measure the acting side separately. A direction-scoped clause is the
right fix; it is a bar change and needs the owner's decision, so the consumer
stays shadow until then. Do not flip on the aggregate number.

Enforcement today (2026-10-22): `tool_choice`, `needs_action`, `escalate_incomplete`,
`depth_met` and `tool_approval` are ON (`decides()` returns their fitted thresholds;
`.env` `IRIS_DECISION_ENFORCE=tool_choice,escalate_incomplete,needs_action,review_verdict,depth_met,tool_approval`).
`review_verdict` is allow-listed but NOT deciding: the 2026-10-21 recompute on its
GROWN cohort (184 -> 1464 rows) no longer meets the bar (AUROC 0.624 < 0.65) -
fail-closed by design, and the next offline diagnosis (the 6.1 method). `narration`
earned on 2026-10-21 and lost the threshold in the 2026-10-22 recompute - the same
honest recompute at work. `user_feedback` earns (807 rows, AUROC 0.88) but has no
live decision site. The five deciding consumers each cost one question at their
site: `tool_choice` before the model call (a confident pick is forced at the API),
`needs_action` before the tool loop (a confident "no tool needed" moves a REACT
step to DIRECT), `escalate_incomplete` at step settle, `depth_met` at the run grade
(tighten-only), and `tool_approval` before each call (refuse-only, bounded at
`_MAX_GUARD_CORRECTIONS=2` per node). Below each threshold the incumbent decides.

### 7.2b tool_choice v4: the label defect, and the bar's error-mass problem (2026-10-21)

The 2026-10-21 demotion cause was found offline, the 6.1 way. The honest
state-keyed v3 cohort (2428 rows - the rows carry the full rendered `state`,
so the input identity is computable from the row itself; 2885 raw rows held
2635 distinct inputs but counted as 2231 under the confidence tuple) showed
BINDING run_command rows ranking at CHANCE (AUROC 0.4982, 488 rows). The v3
label read the loop's `ok`, which counts a non-zero returncode as failure, so
a mid-iteration pytest exit - the command RAN, the call did its job - was
labeled a wrong pick. Measured from the logs: 36 of 39 failed run_command
calls were ran-and-exited, not errored. v4 reads the call-level outcome
(`approval_ok`), the exact tool_approval/v6 precedent; the offline re-label
takes the honest cohort from AUROC 0.657 to 0.7988 (an upper bound - the
per-row call-level outcome is not recoverable from the old rows, so the
v3 cohort was retired, not converted). Shipped as `tc-decide-v4` with
`input_key` on every row; the structural pins proven to fail on the old
code (`test_tool_choice_label_contract.py`).

The live v4 cohort after two seeding passes (100% sampling + the eval
side-effects switch, the documented seeding mechanism for a demoted
consumer): 98 rows, 97 correct / 1 wrong, every row a binding pick at
confidence >= 0.9. Two findings:

1. **The demoted consumer can only seed one confidence band.** A sampled
   pick binds only at raw confidence >= `IRIS_ORACLE_FORCE_MIN` (0.9);
   below it `_choose_tool` discards the row. So while demoted, the cohort
   is structurally conf >= 0.9 - the full range only forms under
   enforcement. The v3 cohort's range came from its enforced era.
2. **The bar needs error mass, and the fixed consumer barely makes
   errors.** The minority clause (>= 5% wrong) exists to prove the
   confidence RANKS errors; a consumer that is genuinely ~99% right in its
   acting range cannot supply that mass, and at a 1-2% true error rate the
   clause may never pass - the bar's clauses assume errors exist. This is
   a FINDING for the owner, not a clause to lower: the certification of a
   near-perfect consumer is a bar-design question (does a 99%-precision
   consumer need AUROC proof, or is the acting-range precision + Wilson
   bound sufficient?).

State: the fix is shipped and live-excellent (97/98 at the only confidence
where a demoted pick acts); the consumer stays sampled; the cohort grows
~55 rows per seeding pass or ~3 per ordinary pass; each re-measure is one
report run. The v3-era simulation says the full-range behavior under the v4
label is AUROC ~0.80 with every aggregate clause met.

**RESOLVED 2026-10-22: measure first, design second - and the measurement
decided.** Four chained seeding passes grew the cohort to 275 distinct rows:
273 correct / 2 wrong (0.7%). A 5% true error rate would have shown ~14
wrong in 275 rows (p < 1e-5), so the data EXCLUDES the minority rate
outright - the consumer is genuinely near-perfect in its acting range, and
the minority+AUROC clauses are untestable by construction, not failed. The
owner approved the NO-ERROR-MASS WAIVER (section 5, clause 2): it opens
only when the binomial test excludes the 5% rate (thin data never qualifies
- 100 rows with 4 wrong does not exclude it; one-class data is refused
before it), every other clause applies at full strength, and it is
re-derived on every recompute so real errors reclose it. tool_choice
certified on the acting-range evidence - threshold 0.9524, 275 rows above
at precision 0.9927 (Wilson 0.9739), ECE 0.0034 - and `decides()` returns
0.9524: the consumer is ON again. The waiver is NAMED in the bar record's
gap field so no one later mistakes this for a fully-ranked consumer.

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

### 7.4 Why the other consumers do not meet the bar (2026-10-13; updated 2026-10-18)

The 2026-10-13 diagnoses below are kept as the record of what was wrong. Every
one of the four label-defect consumers has since been fixed by the 7.5 method
and three of them now decide (see 7.2):

- **`needs_action`: given a live home 2026-10-13** (section 4.1) and switched on after two eval rounds. **`use_thinking`: removed** (section 3.1). **Demoted 2026-10-18**: the bar, recomputed on its accumulated v1 cohort (1126 rows), no longer holds a 90%-precision threshold - fail-closed by design. v2 (call-level label) and v3 (concrete-outcome question) never re-earned. **v4 2026-10-19** fixed three things and still does not earn: (a) the label no longer counts a zero-call ACTION step as "no tool needed" (15 of 294 real pairs were slips); (b) the question keeps the artifact verbs on the yes side only (the v3 wording's "it only writes..." matched "Write X" on the no side); (c) the frame gained `expected`. Measured limits: the planner leaves `expected` empty on every coding step, and the user request is not a substitute (7/12, it makes analysis steps read as tool-needing). The remaining misreads are write/edit goals; the new run-and-report tasks (c17-c24) build the honest False class but do not touch that error. It stays shadow until `expected_output` is populated or the write-goal reading is fixed.
- **`recovery_strategy`, `sufficient`: failure-only paths.** 183 `recovery_strategy` rows and 5 `sufficient` rows exist, none on the d1 identity with a label; both are asked only after a step fails.
- **`depth_met`: FIXED 2026-10-18** (was "a rule's output as the reference", oof AUROC 0.40, inverted). The external verdict label (`turn_verdict_label` + `POST /api/eval/verdict` from the eval harness) and the `judge_depth` job (evidence first, coverage in, grade out) took it to 0.7103 - ENFORCED.
- **`web_intent`: label FIXED 2026-10-18** (was "a noisy reference"). The v2 turn-outcome label (URL-by-rule, else web-usage-and-passed) works and the question is replay-validated at 0.7679 on real pairs; the cohort is capped by the eval's fixed task set (~61 distinct inputs) and needs diverse traffic (the 10 added r26-r35 tasks, browser groups, live usage).
- **`tool_approval`: FIXED 2026-10-18** (was "the label answers another question", 0.5821). Two defects: the question (v4-v5) and, decisively, the LABEL - the DER site labelled a call by the loop's `failed`, which counts a non-zero returncode as failure, so every informative pytest run mid-iteration was a "failed" call. v6 labels by the CALL-level outcome and asks "Will this call succeed? Most calls do. Answer no only on a concrete problem..."; 0.7313 - ENFORCED as the pre-call guard.
- **`review_verdict`: FIXED 2026-10-17** (was "the evidence is cut", 0.6271). The evidence-only frame (envelope lines; the step prose and problem-shaped objectives were the hedge drivers) took v4 to 0.8994 - ENFORCED, refuse-only.
- **`rows below 100`** (`click_safety`, `depth_route`, `done`, `presentation`, event consumers, `browser_next` precision): more live traffic, no code change.
- Decision rows do not store the rendered `state` - but since 2026-10-17 every review, approval and web consult logs its frame (step/turn-keyed DEBUG lines), so a live cohort CAN be replayed against a changed frame. That instrument drove every fix above.

### 7.5 The method that took the label-defect consumers to the bar (2026-10-17/18)

The order, proven four times (review_verdict, tool_approval, depth_met, and
needs_action's v2-v4 relabels): (1) find the LIVE decision the consumer should own
and its caller; (2) give it an OUTCOME label - something that happened outside
the Oracle - instead of agreement with a rule; (3) make the question ask what
the label measures; (4) replay the wording on REAL frames with REAL outcomes
through real d1 before any live run - hand-picked cases first, then the
turn-keyed join once live frames exist (an order-based pairing across runs
measured 0.7429 on misaligned pairs and was noise: join by a key, never by
sequence); (5) stamp a new `criteria_version` and measure only that cohort
(`--scope`); (6) earn the bar on eval traffic, write it scoped - with a scope
for EVERY enforced consumer, or the recompute demotes them - switch it on, run
the live gate. Never lower a bar clause to get there.

The remaining consumers, in order of tractability:

- **`narration`, `user_feedback`** - only ECE misses (0.0512, 0.0544 vs 0.05); more rows usually settle it. `user_feedback` also needs adding to `CONSUMERS` before the owner can switch it on.
- **`web_intent`** - the label and question are done; it needs diverse traffic to reach 100 distinct rows.
- **`needs_action`** - re-earn on v5: the label, the question, the frame and the frame source are all fixed and measured (21/22 on the hard+live probe set). What is missing is ROWS: 11 distinct against a 100-row minimum with 50 rows above the threshold. More coding and run-and-report traffic, no code change.
- **`browser_next`** - a precision problem at every threshold; a frame fix (the same replay recipe) is the next lever.
- **`click_safety`, `depth_route`, `done`, `presentation`, event consumers** - rows below 100; more traffic.

---

## 8. Operations

### 8.1 Environment flags

| Flag | Default | Effect |
|---|---|---|
| `IRIS_DECISION_ENFORCE` | empty (`.env` sets `tool_choice,escalate_incomplete,needs_action,review_verdict,depth_met,tool_approval`) | comma list of consumers the owner lets decide; remove a name to return that decision to the incumbent |
| `IRIS_ORACLE_FORCE_MIN` | 0.9 | raw confidence a SAMPLED tool pick needs to be binding |
| `IRIS_ORACLE_SAMPLE` | on | `0` kills all sampling |
| `IRIS_ORACLE_SAMPLE_FRACTION` | 0.05 | sampled share for every samplable consumer |
| `IRIS_ORACLE_SAMPLE_FRACTION_<CONSUMER>` | unset | per-consumer share, for example `_TOOL_CHOICE=1` |
| `IRIS_ORACLE_SAMPLE_SIDE_EFFECTS` | unset | `1` lets a sampled pick force a side-effect tool (eval work folders only) |
| `IRIS_ORACLE_PHASE`, `IRIS_ORACLE_PHASE_EXIT` | off in code; `.env` sets both to 1 | phase-model admission; `0` returns to the engine lock |
| `IRIS_ORACLE_PHASE_PERIOD_S`, `_MAX_WAIT_S`, `_K` | 0.3, 0.3, 0.6 | phase gate tuning (timed gate) |
| `IRIS_ORACLE_BATCH_CAP` | 8 | width of a batched pass (no production caller) |
| `IRIS_ORACLE_REVIEW_OUTCOME` | off in code; `.env` sets 1 | stamps pending `review_verdict` rows with the step's settled label (VERIFIED / UNVERIFIED / FAILED) as the outside label; ON since 2026-10-17 (the v4 cohort is outcome-labelled) |
| `IRIS_D1_CHECK_TTL_S`, `IRIS_D1_TIMEOUT_S`, `IRIS_D1_N_PROBS` | 300, 20, 512 | serving check cache, HTTP timeout, logprobs returned |
| `IRIS_LOCAL_MODEL_PORT` | 8082 | the shared llama-server port |

**Off switches.** Remove `tool_choice` from `IRIS_DECISION_ENFORCE`: the tool model
decides every call again (the sampled rung then applies at 5%, read-only tools,
confidence >= 0.9; set `IRIS_ORACLE_SAMPLE=0` to remove that too). Stop the shared
server or serve another model: every consumer returns to its incumbent.

### 8.2 Scripts

```
# per-consumer status vs the bar (read-only); --write persists the bar record
python scripts/consumer_enforcement_report.py [--json] [--write] [--scope tool_choice=tc-decide-v3 ...]   # repeat --scope; never --write unscoped

# fit the calibration map and threshold (offline); --dry-run writes nothing
python scripts/fit_oracle_calibration.py [--dry-run] [--scope tool_choice=tc-decide-v3 --scope needs_action=needs_action/v1]

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
- `test_raw_threshold_contract.py` - `threshold_for` resolves the active identity's fitted curve on the raw scale.

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




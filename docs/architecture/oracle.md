﻿# Oracle - Architecture Blueprint

The Oracle is IRIS's local decision engine. This file describes the CURRENT
system: what it is, every layer it touches, how a decision is made, how it earns
the right to act, how well it performs, and how to replace its model.

Source of truth is the code. Names in `code font` are real identifiers. Every
number is a measurement on the running model unless the line says otherwise.

History lives in `oracle-history.md`. A code comment that cites "oracle.md
<section>" with a date on or before 2026-11-09 refers to the archived copy at the
end of that file ("ARCHIVED BLUEPRINT"), which keeps the old section numbers.

---

## 0. Never mix up results (MANDATORY - read before quoting any number)

Owner, 2026-11-10: two costly mistakes in one session came from mixing results.
(1) `tool_choice` was reported as FAILING the bar from an unscoped report that
pooled every question version since v1 (13664 rows, AUROC 0.646); on its live
stamp `tc-decide-v9` it PASSES (1575 rows, AUROC 0.770, 0.950 / Wilson 0.936)
and decides live. (2) A "word rule beats d1 48/50" figure was quoted that no run
reproduces (re-measured: 16/50). Both sent work in the wrong direction. Rules:

1. **Every number names its cohort.** Consumer, criteria stamp, engine id,
   ledger (app store live rows vs `data/oracle_bench` bench rows), label source
   (user / answer sheet / parity / outcome), and how it was measured (in-sample,
   out-of-fold, held-out, live eval). A number without these is not reported.
2. **Status comes only from the scoped report.** Run
   `scripts/consumer_enforcement_report.py --scope <consumer>=<live stamp>` for
   every consumer whose status you state. The unscoped report mixes question
   versions and engines; it is a ledger census, never a verdict. The live stamp
   is the `criteria_version` the code writes today - grep it, do not remember it.
3. **No figure without its command.** Quote a number only from a run you can
   name (the command, or the results file / log path). If you cannot re-run it,
   say "not reproduced" and do not use it.
4. **Same-conditions comparison only.** Compare two runs only when model,
   provider, code and machine load match, or run the A/B back to back in one
   session (the committed code vs the change, same tasks). Never compare a
   DeepSeek run with a MiniMax run, a cold run with a warm one, or a run that
   overlapped other work, as evidence about a code change.
5. **In-sample is not proof.** A question, threshold or rule worded or tuned
   against a sheet is in-sample for that sheet. Only the held-out sheet
   (`evals/safety/heldout_sheet.jsonl`, scored ONCE per change) or live rows
   prove it. Never read held-out misses to reword a question.
6. **Bench rows never pass as live rows.** Simulated traffic (answer sheet) and
   the user's real answers are different evidence; report them separately.
7. **Before writing "passes" or "fails", re-run the scoped command.** A verdict
   from memory, from an earlier session, or from a summary is re-measured first.

---

## 1. Current state at a glance

**2026-11-11: outcome-labelled traffic and the merged gate.** Targeted traffic
(scratchpad manifest `ttraffic_manifest.jsonl`; commit 917e94d1; backend started
with `IRIS_ORACLE_SAMPLE_FRACTION_{ROUTE_V2,BROWSER_NEXT,CLICK_SAFETY,RECOVERY_STRATEGY}=1`)
ran browser x2, done x2, recovery x1 and 24 new calibration tasks. Scoped report
on the OUTCOME stamps (verdict-labelled, never pooled with parity rows):

| Stamp | Distinct rows | Right / wrong | Note |
|---|---|---|---|
| `route_v2/outcome-v1` | 50 | 37 / 13 | clean window (before 09:11 UTC 11-11): 14/14, incl. 3 gate overrides that passed. From 09:11 the backend degraded (TTS hung; /health 503 at 10:02) and 8 of 17 turns failed by timeout, 5 of them where the Oracle and the gate chose the SAME route - those labels measure the hang, not the route (all-rows AUROC 0.33 is therefore not a verdict) |
| `browser_next/outcome-v1` | 29 | 28 / 1 | the Oracle's clicks at 100% cost browser tasks: 7/10 and 9/10 vs 14/14 with the tool model |
| `click_safety/outcome-v1` | 23 | 18 / 5 | |
| `recovery/outcome-v1` | 2 | 2 / 0 | fires only on a step that fails after its retry |
| `done/v4` | 14 | 5 / 9 | fires ~1 per 9 tasks (only when the goal is unmet after the first steps) |
| `sufficient/verdict-v1` | 0 | - | fires only on a failed critical gather step |

None has 100 distinct rows. REPEATED tasks add no distinct rows (route_v2: 32 raw
-> 24 distinct after the repeats); only new tasks do. Merged gate on e068e066
(retirement + page consumers + the direct-path shadow fix): coding 8/8, research
8/8, browser 10/10, 0 tracebacks; the coding reply_s standards (2026-09-30) are
missed as on every commit of 2026-11-10 (provider speed; no same-hour A/B, so no
speed claim either way).


**Measured 2026-11-10 after 104 traffic tasks** (scoped report, every consumer on
its live stamp, engine `d1-2b-q4_k_m+systemone`, app store; traffic on commit
58a47ff5, manifest per section 0 rule 3). One row per job, with the solution:

| Job (live stamp) | Rows | Verdict | Solution |
|---|---|---|---|
| tool_choice (`tc-decide-v9`) | 2772 | above threshold 0.968 / Wilson 0.959, AUROC 0.736; the MINORITY clause now reads 4.7% < 5% (110 wrong of 2353) | DECIDES (persisted bar record). OWNER: the 5% minority clause fails a job for being too accurate while 110 errors are plenty to rank; a `--write` would switch it off |
| web_intent (`web_intent/v3`) | 938 | earned (waiver) | DECIDES (allow-listed after its live gate) |
| route_v2 (`route_v2/binary-v1`) | 1346 parity + sampled | earned on a parity label | SITE (commit e06a1b8f): `agent_kernel._route_v2_route` at the turn-route fork - acts on the sampled rung (5% of turns, labelled by the turn verdict) and when the bar lets it decide. Live check with every turn sampled (8 tasks): 7/8 pass (r21 fails in every run), 3 overrides of the gate (c13, cal_a02, cal_a03 -> direct), all 3 passed and faster (c13 reply 9.6 s vs 21.6-30 s) |
| user_feedback | 955 | earned (waiver) | not switchable |
| tool_approval (`safety-v3`) | 470 bench | in-sample only; held-out fails (section 9) | shadow; live rows from the user's permission answers |
| narration (`shape-v3`) | 172 | loses to the trivial rule 0.820 vs 0.872 (AUROC 0.878) | RETIRED 2026-11-10 (owner): the planner's duration gate decides |
| presentation (`shape-v3`) | 238 | loses 0.378 vs 0.937; spec AC23.6 bars the only extra input (the reply text) | RETIRED 2026-11-10 (owner): the reply-surface rules decide (show-presence) |
| review_verdict (`v13`) | 944 | AUROC 0.483; no step-level truth | RETIRED 2026-11-10 (owner): the Reviewer (heuristic / Brain) decides |
| depth_route (`v3`) / depth_met (`v4`) | 356 / 417 | AUROC 0.543 / 0.591 | RETIRED 2026-11-10 (owner): the continuation branches / the run grade decide |
| needs_action (`v7`) | 4367 | no threshold holds 0.90 (the label is True on 96% of rows) | RETIRED 2026-11-10 (owner): the node mode rule and the lexical NONE guard decide |
| call_closing | 2909 | earned | refused by design |
| done (`done/v4`) | 8 | fires ~1 per 9 tasks, every row right | shadow; not fillable by traffic in useful time |
| sufficient (`sufficient/verdict-v1`) | 0 | its gate was dead since 2026-09-29 (`item.tool` on node steps) | FIXED (commit 68bc2f80): runs on failed gather steps, labelled by the turn verdict when the Brain said "enough" |
| recovery_strategy, click_safety (sampled rows) | 57 / 33 sampled | never scored: choice rows got no outside label | FIXED (68bc2f80): a sampled row's label is its turn outcome |
| recovery_strategy (parity rows) | 581 | reference is the constant "delegate": no label | no honest parity label; sampled rows only |
| browser_next (`v1`) | 14 on this engine | the tool model has not clicked since 2026-10-23 | shadow; no honest label |

Allow-list (owner's local `.env`): `tool_choice,web_intent`.


| Area | State |
|---|---|
| Model | d1-2B (`d1-2B-Q4_K_M.gguf`), native Decision Index API, identity `d1-2b-q4_k_m+systemone` |
| `tool_choice` | LIVE in its own role: the Oracle decides the tool CLASS, the tool model picks the tool (section 5); the bar CERTIFIES this role at its live gate |
| Deciding through the bar | `tool_choice` (row above; `tc-decide-v9`: 1575 distinct rows, OOF AUROC 0.770, precision 0.950 / Wilson 0.936 - measured 2026-11-10; 132 class decisions in 8 coding tasks, none fell back) and `web_intent` (allow-listed 2026-11-10 after its live gate: research 31/35 = the 2026-11-05 run, no standard regressed; on those goals it agreed with the keywords 10/10, median 50 ms per goal). Measure `tool_choice` ONLY on its live stamp: the unscoped report mixes every stamp since v1 (13664 rows, AUROC 0.646) and reads as a failure it is not |
| Earned, no decision site | `call_closing` (refused by design), `tool_approval` (safety question: the v3 question earns the bar on the answer sheet it was worded against, and FAILS on the held-out sheet - section 9) |
| Earned, has a site, not switched on | `user_feedback` (waiver; not switchable) |
| Shadow (the incumbent decides) | `done`, `sufficient`, `recovery_strategy`, `browser_next`, `click_safety`, event consumers |
| No decision site at all (`NO_DECISION_SITE`) | `tool_approval`, `page_relevance`, `page_blocked` (section 6.3): their rows are measurement only |
| Retired | `narration`, `presentation`, `review_verdict`, `depth_route`, `needs_action`, `depth_met` (2026-11-10, with the jobs `shape`, `judge_review`, `judge_depth`, `interpret_step`; guard `test_six_consumers_retired_contract.py`), `escalate_incomplete` (and its job `judge_step`), `mode`, `on_track`, `has_gaps`, `retry_same`, `use_thinking` |

Which jobs the Oracle should own and which it leaves to the incumbent: section 9.

---

## 2. What the Oracle is

One small local model answers ONE question per run and returns a probability
distribution over the answers the caller offered.

- **Model.** d1-2B (`d1-2B-Q4_K_M.gguf`), a typed "System One" decision model
  (architecture `lfm3`), served by the shared `llama-server` on `:8082`. It is the
  same server and the same loaded model that vision uses (with its `mmproj`
  projector). The Oracle only borrows it: it never spawns, restarts or loads
  anything.
- **Question shapes** (`DECISION_TYPES`): `choice` (pick one named option), `noul`
  (P(statement is true), yes/no), `score` (ordered levels; schema only, no consumer
  uses it).
- **One question per run.** A run reads a state, sends one typed question, and the
  server returns the answer distribution. Zero text is generated.
- **Not an LLM chat and not a batch classifier.** It never writes prose, arguments
  or memory, never emits events, never calls a hosted provider. If the shared
  server hosts anything that is not a d1 build, the Oracle is unavailable; there is
  no fallback model.
- **Its guesses are never evidence.** Evidence is outside only: a tool outcome, a
  test, a completion, a user correction. The Oracle's own answer never labels itself.
- **Shadow until it earns a job.** Every consumer starts in shadow: the incumbent (a
  rule, a keyword list, the tool model or the Brain) decides, the Oracle is scored
  beside it, and the pair is recorded. A consumer acts only when the owner switched
  it on AND it passed the measured bar AND a threshold was fitted for the running
  model (section 7).
- **Failure is silent to the user.** Every Oracle call returns a score or `None`.
  `None` always means "the incumbent decides", exactly as if the Oracle did not
  exist.

Display name `Oracle`; config block id `oracle` in `backend/agent/agent_config.yaml`;
module `backend/agent/decision_engine.py`; backend `backend/agent/decision_backend_d1.py`.

---

## 3. Layer diagram

### 3.1 Runtime stack (one tool decision)

```
 USER TURN  (voice / text)
     |
     v
 AGENT KERNEL ........................ backend/agent/agent_kernel.py
   plan -> DER steps -> verify -> synthesise -> speak/display
     |  each DER step runs a NODE
     v
 NODE LOOP ........................... backend/agent/node_executor.py  run_node()
     | before each tool-model call (not after a model slip):
     |     ctx.choose_tool()
     v
 KERNEL HOOK  _choose_tool ........... agent_kernel.py
   reads the step's live state: calls this step, last result, step_facts,
   done_when, ORACLE_HINTS option lines (tool_registry.oracle_hint)
     |
     v
 ToolDecisionBox.choose_node_tool .... backend/agent/tool_decision.py
   class mode: the FULL offered menu (cap 32, with DELEGATE / NONE)
   frame = goal, done_when, calls_this_step, step_facts, last_result
     |
     v
 DecisionEngine.decide ............... backend/agent/decision_engine.py
   job_input()  -> OracleState (job fields + budget + images + option criteria)
   phase gate   -> domain "decision.oracle_cpu"  (IRIS_ORACLE_PHASE)
   inference thread (never the caller's step thread)
     |
     v
 D1Backend.decide .................... backend/agent/decision_backend_d1.py
   POST /v1/systemone {state, questions:{q0:{type, instructions, criteria}}}
     |
     v
 llama-server :8082 .................. d1-2B-Q4_K_M.gguf + mmproj (shared with vision)
     |  DecisionScore { chosen, confidence, distribution, engine_latency_ms }
     v
 back in choose_node_tool (section 5):
   class margin >= 0.30 -> every offered tool of the top-1 tool's class
   else                 -> the top-5 shortlist of the full distribution
   + every offered tool outside the class map
     |
     v
 run_node: gen_tools = that list; NO named tool_choice
     |
     v
 InferenceRouter.generate -> transport -> TOOL MODEL picks the tool and
   writes the arguments (or ends the step without a call)
     |
     v
 ctx.execute -> AgentToolBridge -> tool runs -> result
     |
     v
 ctx.on_result(name, params, ok)   (the pre-call state is still readable)
   |-- label the decided row (outcome label, action class)
   |-- record_shadow_tool_choice      parity row, lane("oracle_shadow")
   |-- browser_next_shadow            on browser_act with an element_id
   `-- tool_approval_shadow           safety yes/no at the user's permission answer
     |
     v
 shadow-row sink -> AgentToolBridge.record_decision -> write-time dedupe
   -> system_events (event_type='tool_execution', interaction_payload.decision)
   -> data/memory.db (resolved by resolve_memory_store_path)
```

The forced single-tool path (a named `tool_choice` at the API) still exists for
an `enforced` bar pick or `IRIS_ORACLE_TOOL_CHOICE_ALWAYS=1`. Both are off.

### 3.2 Learning loop (offline, manual)

```
 data/memory.db  system_events.decision rows
     |
     |  scripts/consumer_enforcement_report.py     (read-only; --write persists)
     |    load_rows: label (decision_label), collapse repeats, active engine only,
     |               fold group + rule key, --scope CONSUMER=criteria_version
     |    declared_only: retired consumers never re-enter
     |    fit_consumer: grouped out-of-fold map (isotonic or none), threshold,
     |               AUROC / ECE / precision / Wilson, trivial-rule baseline
     |    consumer_bar.derive_status: shadow | sampled | enforced + the gap
     v
 benchmarks/consumer_bar_record.json   (status per consumer + the identity it was measured on)
     |
 scripts/fit_oracle_calibration.py     (offline; --dry-run prints only)
     v
 benchmarks/oracle_calibration.json    (knots + threshold per identity / consumer)
     |
     v
 decision_engine.decides() / oracle_acts()   <- the ONE enforcement chokepoint
                                                 (bar record + calibration +
                                                 IRIS_DECISION_ENFORCE)
 replay instruments (no writes): replay_consumer.py, replay_tool_choice.py,
   bench_tool_safety.py (answer sheet -> bench ledger)
```

### 3.3 Consumers around the engine

```
                      +-----------------------------------------+
                      |  DecisionEngine  (one resident backend)  |
                      +-----------------------------------------+
    route job ------ tool_choice (class role, LIVE) | route_v2 (earned, shadow only) |
                     recovery_strategy | browser_next
    approve job ---- tool_approval (shadow; safety question; earned on the answer sheet; no site)
    guard job ------ click_safety (shadow + refuse-only sample)
    judge_goal ----- done | sufficient
    judge_call ----- call_closing (REFUSED: measurement only)
    interpret_web -- web_intent    interpret - user_feedback
    classify_event - event_family | event_type:<family>
    lanes: oracle_shadow, click_safety_shadow, event_oracle, memory_events
           (backend/utils/durability_queue.lane)
```

### 3.4 Boot and serving

- `backend/main.py` `_boot_load_d1` runs as an async task after the TTS prewarm. It
  reads the pinned vision model (`field_values.vision.vision_model`, the Models
  card) and loads it only when `decision_backend_d1.is_d1_build` accepts the name
  (else it logs `[D1BOOT] pinned vision model is not the d1 ...`). It prefers a
  same-named file on the `D:/lmstudio/models` SSD twin, skips the load if a d1 build
  is already resident, and loads with the projector. `n_ctx` is the model's
  `last_ctx` in `models/gguf/.iris_model_settings.json` (default 8192).
- `is_d1_build` matches `_D1_BUILD_TOKENS` in the served file name. This tuple is
  the ONE place that says which model family the Oracle accepts: the boot pin check,
  the server command flags and the backend's serving check all read it.
- The shared server port is `LocalModelManager.PORT` (`IRIS_LOCAL_MODEL_PORT`,
  default 8082).
- `D1Backend` checks `GET /v1/models` for a served d1 build. When the server reports
  `output_modalities`, the build must declare `decisions` (Decision Index metadata);
  a build without it answers `/v1/systemone` with 501 and every decision returns
  `None`. The check is cached for `IRIS_D1_CHECK_TTL_S` (300 s).
- The load is borrow-only with `retry_load = True`: a miss at boot is transient.
- HTTP uses one pooled keep-alive client (`IRIS_D1_TIMEOUT_S`, 20 s). A fresh
  connection per decision costs about 400 ms of Windows TCP setup; pooled, about 1 ms.
- For a d1 build the server runs with `--batch-size` and `--ubatch-size` EQUAL to the
  context window: the native API builds one graph for the whole prompt, and the
  512 default rejects a 27-tool menu ("input is too large to process"). Measured on
  the 8 GB card: ctx 8192 / batch 8192 = +2776 MiB VRAM, 2.5 s to ready.
- For a d1 build the server also runs with `--cache-ram 0`: Oracle prompts share
  almost no prefix, so a host prompt cache only grows (it reached 1.6 GB and added
  240-380 ms per decision before it was turned off).
- After d1 is resident, boot proves the server multimodal once
  (`[D1BOOT] vision verdict proved in N s`); a proven verdict does not expire.

---

## 4. Concepts

### 4.1 Consumers

A consumer is one decision point: one question asked at one place in the app. Each
has an id, a declared decision type and criteria, and one job.

`CONSUMER_DECLARATIONS` declares every consumer below. `CONSUMERS` is the set of 10
ids the owner can switch on with `IRIS_DECISION_ENFORCE`; `browser_next`,
`click_safety`, `user_feedback` and the event consumers are declared but cannot be
switched on.

| Consumer | Job | Type | Incumbent | Where | Status |
|---|---|---|---|---|---|
| `tool_choice` | route | choice | the tool model | `ToolDecisionBox.choose_node_tool` | class role LIVE and certified (section 5) |
| `route_v2` | route | choice | the kernel's turn route (`"der" if planned else "direct"`) | kernel, `eng.shadow` only | earned; no decision site |
| `recovery_strategy` | route | choice | the recovery ladder | `ToolDecisionBox.recovery_strategy` | shadow (0 rows: failure-only path) |
| `browser_next` | route | choice | the tool model's element pick | `browser_next_shadow` | shadow |
| `tool_approval` | approve | noul | the user's own permission answer; the owner-policy answer sheet (`evals/safety`) | `tool_approval_shadow.record_permission_answer`, called from `permissions.respond_to_permission`; no decision site | shadow |
| `click_safety` | guard | choice (safe/unsafe/unsure) | rules, then the Brain judge, then the user | `tools/browser_tools.py`, `click_safety_shadow` | shadow |
| `done`, `sufficient` | judge_goal | noul | the Brain done-bit / sufficiency gate | `monitor_shadow` (`register_monitor_consumers` registers the declared type, so the declared question reaches the model) | shadow |
| `call_closing` | judge_call | noul | the node closing rule | measurement only | refused |
| `web_intent` | interpret_web | noul | the web-trigger keyword lists | `explorer` (decision site) | earned, not on the allow-list |
| `user_feedback` | interpret | choice | none (a Brain sample is the reference) | `event_oracle` | earned (waiver), no decision site |
| `event_family`, `event_type:<family>` | classify_event | choice | the rule label | `event_oracle` | shadow (rows < 100) |
| `page_relevance` | judge_page | noul | none (every usable page is extracted) | `CrawlOrchestrator._research_inner`, before the passage split (`page_shadow`) | shadow; no decision site (section 6.3) |
| `page_blocked` | inspect_page | noul | none (every Tier-1 failure is escalated) | `FetchCrawlCapability.fetch_one`, at the Tier-1 -> browser fork (`page_shadow`) | shadow; no decision site (section 6.3) |

Retired 2026-11-10 (owner), each with its consult removed and its incumbent
deciding exactly as before: `narration` (the planner's duration gate),
`presentation` (the reply-surface rules), `review_verdict` (the Reviewer),
`depth_route` (the continuation branches), `needs_action` (the node mode rule
and the lexical NONE guard), `depth_met` (the run grade). Section 1 has the
measured reason for each.

Rules of the registry:

- A consumer with no declared decision type is never scored; the d1 backend refuses
  it. It never borrows another consumer's shape.
- `event_type:<family>` consumers inherit the `event_family` declaration.
- `REFUSED_CONSUMERS = {"call_closing"}`: never enforced, never sampled, never
  resolved to a threshold, whatever any flag says.
- The report and the fit measure DECLARED consumers only (`declared_only`), so a
  retired consumer's old rows never write a bar record or a calibration entry.
- `NO_DECISION_SITE` names the switchable consumers whose answer no code reads.
  An earned bar changes nothing for them, and the enforcement log lists them as
  "earned, but no decision site: shadow only". `test_no_decision_site_contract.py`
  pins the set against the source in both directions: wiring a site, or removing
  one, fails the test until the set is updated. Before you call a consumer "live",
  find its `decides()` / `oracle_acts()` caller.
- `tier0_classify` is a recorded non-fit: a sub-millisecond rule would become a
  model call.

### 4.2 Jobs (`ORACLE_JOBS`)

A job is the KIND of question. It fixes what the model reads (which frame fields, in
which order) and how much (a budget in token ids). The engine builds the input; a
call site cannot make it longer, shorter or blind. `job_input()` drops fields the job
does not declare. Reference fields (`incumbent_route`, `brain_*`) are never declared:
an input that carries the answer measures nothing.

| Job | Question | Declared fields (render order) | Budget (ids) |
|---|---|---|---|
| `route` | which of these next actions? | goal, done_when, calls_this_step, step_facts, last_result, task_class, previous_chosen, previous_outcome, step_index, needs_vision, vision_candidates, ruled_out, error_snippet | 384 |
| `approve` | is this the right tool for this goal? | goal, calls_this_step, last_result, proposed_tool, tool_description, args, offered_tools | 384 |
| `guard` | is this action safe to take without asking? | goal; image `screenshot` | 128 |
| `interpret_web` | what does the user's message mean? | goal | 128 |
| `interpret` | what does the user's message mean? | goal | 64 |
| `judge_goal` | is the objective met, deep and sufficient? | goal, open_facts, evidence | 128 |
| `classify_event` | which event family/type is this? | goal | 64 |
| `judge_call` | was this call the closing call of the step? | goal, call, result | 96 |
| `judge_page` | does this fetched page answer the question? | goal, title, url, page_head | 384 |
| `inspect_page` | is this page blocked from being read? | url, title, status, page_head | 256 |
| `general` | a consumer not yet assigned to a job | goal | 128 |

Mapping: `CONSUMER_JOBS`. The budget is a cap, not a floor: the backend cuts the
state at `max(64, budget) * 4` characters from the END (so field order protects
what matters) and logs every trim. Only `guard` declares an image; a text consumer
never receives one.

### 4.3 Job input and frame (tool_choice as the example)

`job_input(consumer, frame)` renders `goal` as plain text and every other declared
field as `field: value` (lists joined by `; `, floats to 2 places), skipping absent
fields. The `tool_choice` frame carries, with the call-site caps:

- `goal` (200 chars) - the step goal
- `done_when` (200) - the step's own criterion
- `calls_this_step` (400) - the last 6 calls of this step, e.g.
  `read_file m.py ok; edit_file m.py FAILED`
- `step_facts` (400) - `node_executor.step_facts`: for each file the step names,
  whether it exists and whether this step already read or changed it; files seen in
  the last result and not yet read; the last command and whether it worked
- `last_result` (600) - what THIS step's last call returned

`calls_this_step` and `step_facts` render before `last_result`, so a budget cut
removes the long result and never the history.

**Menu and option lines.** The options are the offered tools, ordered by
`_order_engine_names` (vision tools first for a vision goal; in developer mode the
coding tools in `_DEV_MENU_ORDER` first; else registry order). `_compose_engine_menu`
reserves two slots inside the cap for the control labels `DELEGATE` and `NONE`. Each
option's text is the tool's decision line in `tool_registry.ORACLE_HINTS` ("when to
choose it, with its precondition"); a tool with no hint falls back to the first
sentence of its description (`oracle_hint`).

**Menu fingerprint.** Every tool-choice row carries `menu_fp`, a short hash of the
offered names in order plus their option text. A tool added or re-described changes it.

### 4.4 Request and readout (`decision_backend_d1`)

The native Decision Index API builds the prompt SERVER-SIDE from a typed question.
The backend sends no hand-written prompt and reads no logprobs:

```json
POST /v1/systemone
{"state": "{state}",
 "questions": {"q0": {"type": "choice",
                      "instructions": "{instruction}",
                      "criteria": {"option name": "option text"}}},
 "images": ["data:image/png;base64,..."]}
```

- `choice` names every option and its text in `criteria`; the answer carries the
  option NAME, its `probabilities` and a `confidence`.
- `noul` uses `criteria` with the `true` / `false` descriptions; the answer carries
  `noul` = P(true). A noul row stores the confidence in the CHOSEN answer
  (`max(p, 1-p)`) and the raw `probability` beside it.
- `score` lists ordered levels lowest first; the answer carries the median level,
  a `legend` and the per-level probabilities.
- **Option text is capped at 120 characters** (`_OPTION_TEXT_CAP`). A decision costs
  the PREFILL of the prompt, and the criteria are most of it: the 27-tool menu is
  1619 tokens / 177 ms with full tool documentation and 703 tokens / 82 ms capped
  (RTX 3070). The cap also improves the pick: the tool FAMILY was right on 29/30
  real eval tasks capped against 17/30 with full text. The option NAME is never cut.
- **Option text must not argue for an answer.** On `review_verdict`, descriptive
  option text ("vague, incomplete or uses the wrong tool") made confidence rank the
  errors backwards (OOF AUROC 0.40); the bare option names ranked them at 0.80. The
  instruction carries the meaning; the options only name the answers.
- A scoring failure of any kind returns `None`. Images ride the `images` field (the
  `guard` job). `decide_batch` / `decide_many` / `shadow_many` exist but have no
  production caller: every production consult is one question per run.

### 4.5 Decision identity and cohorts

```
identity = model_id | readout_mode | criteria_hash
         = d1-2b-q4_k_m+systemone | systemone | <12 hex of sha1(type, criteria, cap)>
```

- `model_id` is the served GGUF stem, lowercased, plus the readout tag
  (`CURRENT_READOUT_MODE = "systemone"`). A row's `engine` field holds it.
- `criteria_hash(consumer, candidate_cap)` digests the declared type, criteria and
  candidate cap. Editing criteria or the cap re-identifies the consumer: its
  threshold no longer resolves and it falls back to shadow.
- A bar flip records the identity it was measured on (`config.backend_id`) and
  stands only while the running identity equals it. A new model is a new identity:
  every consumer starts "not earned". This is the fail-closed design, not a fault.
- The frame is NOT inside `criteria_hash`. A frame or question change is tracked by
  the row's `criteria_version` stamp. Current stamps: `tc-decide-v4` (tool_choice bar
  path; certified as the class role: `tc-decide-v9`), `route_v2/binary-v1`,
  `tool_approval/safety-v3`, `done/v4` (the first rows that ask the declared question),
  `web_intent/v3`. (The retired consumers' last stamps, kept in the ledger:
  `needs_action/v7`, `review_verdict/v13`, `depth_met/v4`, `depth_route/v3`,
  `narration/shape-v3`, `presentation/shape-v3`.) The report and the
  fit take `--scope CONSUMER=STAMP` to measure one cohort. A stamp is never reused.

### 4.6 Enforcement chokepoint

`decision_engine.decides(consumer)` is the ONE chokepoint. It returns the threshold
only when all four keys hold, else `None`:

1. the owner switched the consumer on: `IRIS_DECISION_ENFORCE` (comma list, members
   of `CONSUMERS` only);
2. the bar record says `enforced`, measured on the identity now running;
3. a threshold was fitted for that identity in `benchmarks/oracle_calibration.json`;
4. the configuration is not stale (`candidate_cap == calibrated_cap`, both 32).

`oracle_acts(consumer, raw_conf)` then applies the per-decision test: the calibrated
confidence (the consumer's map applied to the raw confidence in the chosen answer)
must reach the threshold; below it the incumbent decides. A map with
`method: identity` (knots `[[0,0],[1,1]]`) leaves the raw confidence unchanged.
`decides` never raises. One INFO line per process (again if the identity changes)
names who decides and why each allow-listed consumer does not; a consumer in
`NO_DECISION_SITE` is never listed as deciding.

`EngineConfig.threshold_for(consumer)` serves callers that hold a RAW confidence
(ledger rows, `recovery_strategy` rows): it
reads a per-consumer override, then `agent_config.yaml` `backend_thresholds` (retired
backends only), then the fitted curve of the active identity through
`oracle_calibration.raw_threshold`. Guard: `test_raw_threshold_contract.py`.

### 4.7 The sampled rung

`sampled` is a bar status between shadow and enforced: the consumer fails the bar,
is in a sampling tier, and has at least one outcome-labelled row.
`sampled_consult_ok(consumer, scope_key)` decides whether the Oracle's answer
replaces the incumbent on THIS consult. It reads only the tier, the kill switch and
the share, not the allow-list; the caller asks it when the consumer is not enforced.

- Tiers: `TIER_SAMPLABLE` = recovery_strategy, tool_choice, route_v2, browser_next.
  `TIER_REFUSE_ONLY` = click_safety (may only tighten:
  refuse where the incumbent allowed). `TIER_JOIN_ONLY` = done, sufficient
  (labelled by outcome, never sampled). No tier = never sampled.
- Share: `SAMPLE_FRACTION = 0.05`, `IRIS_ORACLE_SAMPLE_FRACTION`, per consumer
  `IRIS_ORACLE_SAMPLE_FRACTION_<CONSUMER>`; `IRIS_ORACLE_SAMPLE=0` kills sampling.
- Deterministic: SHA-256 of `consumer|scope_key` against the share, so a retried
  consult answers the same way.
- A sampled tool pick may force only a `read_only` tool unless
  `IRIS_ORACLE_SAMPLE_SIDE_EFFECTS=1` (eval work folders only).
- Sampled rows are labelled by outcome, never by the incumbent
  (`register_turn_pending`, 256 turns; `turn_ok` / `turn_fail` at turn end).

### 4.8 Option ceiling and candidate cap

`OPTION_CEILING = 120` bounds any consumer's options. `CANDIDATE_CAP_DEFAULT = 32`
(`agent_config.yaml` `oracle.constraints.candidate_cap: 32`) bounds the tool menu: up
to 30 tools plus `DELEGATE` and `NONE`. The 25 node tools plus the two controls fit
whole (27); with the 5 screen tools the menu is exactly 32. The cap is inside
`criteria_hash`; a deployed cap that differs from `calibrated_cap` marks every
threshold stale and enforcement is refused.

---

## 5. tool_choice: the class decision + shortlist

The Oracle decides the tool CLASS; the tool model picks the specific tool and writes
the arguments. This is candidate compression: a small ranker narrows the action
space and the LLM resolves the call.

```
DER step -> choose_node_tool
  frame: goal, done_when, calls_this_step, step_facts, last_result
  menu:  the FULL offered tools
  -> DecisionEngine.decide("tool_choice", menu, frame)      [route job]
  -> top1 class = classify_tool(chosen)
     masses, margin = class_masses(distribution, top1 class)
       # margin = mass(top1 class) - max(other classes, unmapped-tool mass)
     if class in {READ, WRITE, RUN} and margin >= 0.30:
         tools = every offered tool of that class           (route "class")
     else:
         tools = shortlist_from_distribution(distribution, K=5)   (route "shortlist")
     tools += every offered tool outside the class map (never removed)
  -> run_node: gen_tools = tools; no named tool_choice
  -> the tool model picks the tool and writes the arguments
  -> _on_result labels the row: route, class_decided, class_margin,
     shortlist_served, outcome label, action class
```

Pieces:

- `backend/agent/tool_choice_action_class.py`: `classify_tool`, `required_classes`,
  `action_class_ok` (the class map and the row label), `class_masses`,
  `shortlist_from_distribution` (top-k, controls removed, low-value tools
  `list_directory`, `recall_memory`, `read_command_output`, `stop_command` demoted by
  0.20), and the flag readers.
- `tool_decision.choose_node_tool`: class mode, shortlist mode, and the forced mode
  (`IRIS_ORACLE_TOOL_CHOICE_ALWAYS`, off).
- `agent_kernel._choose_tool` returns the list for `route in ("shortlist", "class")`.
- `node_executor.run_node`: a list becomes `gen_tools` with no `tool_choice`.
- The class map covers the coding tools. Every offered tool outside it (`search`,
  `crawler_query`, the browser and desktop tools, `get_system_info`) rides along
  with the class list and the shortlist, and its mass counts as a competitor in the
  margin. Guard: `test_tool_choice_class_unmapped_contract.py`.
- While the class decision is on, the goal-only node menu cut
  (`_narrow_node_tools`) does not run unless `IRIS_NODE_TOOL_MENU_K` is set. Guard:
  `test_node_menu_cut_yields_to_class_decision_contract.py`.

Measured:

| Measure | Value |
|---|---|
| Class accuracy (398 stored rows) | 93.7% (class-mass argmax 92.96%) |
| By margin | < 0.1: 64.7%; 0.1-0.3: 88.5%; 0.3-0.7: 92.4%; >= 0.7: 97.7% |
| c14 end to end, same backend | no Oracle 126 s; shortlist 103.5 s; class decision 73 s; forced top-1 301 s |
| c13 end to end | shortlist 77.6 s; class decision 59.7 s |
| Rows clearing the 0.30 margin | 1342 of 1361 labelled rows |

The forced top-1 stays off: it picked `list_directory` where the tool model's own
pick was better. Web and browser menus are not yet measured (almost every stored
decided row offered coding tools only); the unmapped-tool rule keeps them safe until
a web live gate runs on a working network.

**Certification.** The bar certifies this role on cohort `tc-decide-v9`:
- the label is the action class (did the Oracle pick the right CLASS?);
- the confidence is the class margin (`consumer_enforcement_report.class_margin_confidence`), not the tool confidence;
- a pick of a tool with no class is unscoreable (`unscoreable_unmapped`): the
  action-class label cannot judge it and the role never class-decides it;
- the policy point is the live gate (`POLICY_RAW_THRESHOLD["tool_choice"] =
  CLASS_MARGIN_MIN`), so the bar measures precision exactly where the app acts.

Result: 859 rows (790 right / 69 wrong), OOF AUROC 0.776, ECE 0.024, 753 rows
above the gate at precision 0.936 (Wilson 0.917): enforced. The record certifies
the class role only: `enforced` counts only in class mode, and the forced path's
tool-confidence check never runs in class mode, so a margin threshold never gates
a tool confidence. Guard: `test_tool_choice_class_certification_contract.py`.

---

## 6. Other decision sites

### 6.1 route_v2: the turn route (shadow only, by measurement)

`route_v2` asks whether a turn should answer `direct` (from what is known) or run
a `der` plan (job `route`, choice). The incumbent is the kernel's own fork,
`"der" if planned else "direct"`, and the kernel only calls `eng.shadow` for it:
there is no decision site. Its bar is earned (threshold 0.6148 on raw confidence,
no calibration map: section 7.3), but on a PARITY label: agreement with that fork,
which the kernel comment notes is not truth (the rule calls every memory ask
`direct`). To give it a job it needs (1) an outcome label, for example whether the
turn ran a tool, (2) a decision site that reads `decides("route_v2")`, and then
(3) a live gate.

CORRECTION (2026-11-10, later): the comparison below labelled each turn from the
gate's OWN route (a passed direct turn = "direct was right", a passed DER turn
that used a tool = "der was right"), so the gate was right by construction and
the figure cannot show where the Oracle is better. route_v2 now has a site
(`agent_kernel._route_v2_route`): the sampled rung lets its route act on a
bounded share of turns and labels them by the turn verdict - the honest outcome
label. The original text follows for the record.

Measured on an outcome label (2026-11-10, 1207 labelled eval turns: "der needed" =
the DER turn made a project action and passed; "direct was enough" = it passed on
the direct route, or on DER with no tool call): the gate is right 97.9%, the
Oracle 92.2%. Even its confident der -> direct switches (conf >= 0.95) are right
25 of 32. The label itself is partly wrong where the planner read files it did not
need ("Explain how binary search works... Do not use the web" ran `list_directory`),
and the truth there is readable from the prompt's own words. So route_v2 gets NO
decision site: wiring it would lower quality against the gate and add a model call
(0.2-0.3 s) to every turn. The speed it could bring - knowledge questions skipping
DER planning - belongs to the gate (`compile_dag`), as a rule.

### 6.2 needs_action: the step mode (RETIRED 2026-11-10)

Each DER step runs DIRECT (one text answer) or REACT (the tool loop).
`external_reference.mode_for_goal` picks DIRECT only for a goal that opens with a
question word, and it decides alone. The `needs_action` Oracle consult that could
move a REACT step to DIRECT was retired by the owner: no threshold reached
precision 0.90 on the v7 cohort (the label was True on 96% of rows, so "always use a
tool" beat it). Its frame (job `interpret_step`), its question, its outcome label
and its row writer are deleted; the lexical NONE guard in
`tool_decision._goal_needs_action` decides without a consult as well.

### 6.3 page_relevance and page_blocked: the research path (shadow, 2026-11-10)

Two noul questions about ONE fetched page, both in `NO_DECISION_SITE`: nothing
reads the answer, every page is still extracted and every escalation still runs.
Code: `backend/agent/page_shadow.py`; both consults run on `lane("oracle_shadow")`;
rows reach the ledger through the kernel's shadow sink. Guard:
`test_page_shadow_contract.py` (fails on the committed crawler files).

| | `page_relevance` (`page_relevance/v1`) | `page_blocked` (`page_blocked/text-v1`) |
|---|---|---|
| Asked | once per usable page, after the final fetch, BEFORE split / rerank / extraction (`orchestrator._research_inner`) | when Tier 1 (httpx) came back unusable and the crawler escalates to the pooled browser (`capabilities.FetchCrawlCapability.fetch_one`) |
| Frame | the search query, page title, url, page text head (800 chars) | the Tier-1 page: url, title, HTTP status, text head (600 chars). Text only: no screenshot exists at this fork |
| True label | the turn PASSED and the extraction cited the page (`[n](url)` in the summary or a key finding; `note_extraction` at `_notify_dashboard`), joined at `turn_verdict_label.report_verdict` | the browser fetch made a request (a HAR entry) and `page_is_usable` judged it NOT usable |
| False label | the turn PASSED, the extraction cited >= 1 page, not this one | the browser fetch produced usable content |
| No label | failed turn; a ONE-page job (the citation binding cites the only page by construction: 47 of 53 such recorded inputs cited); no verdict (live turns); extraction not landed before the verdict or cited nothing | the browser raised before a request (lease, launch, navigation timeout) or was cancelled (a lost crawl/vision race) |
| Not asked | pages from the rerank re-query and the same-site hop | Tier-1 usable, Tier-1 bare 401/403 (parked), browser latched off, Tier 1 raised (no text) |

What the page_relevance label cannot see: whether the reply used the cited claim (on
`crawler_query` the agent reads raw page content, not the extraction); the binding is
token overlap, so a near-duplicate page can take another page's sentence.

**Replay, 2026-11-10** (`.venv` python `scripts/replay_page_relevance.py --results
"C:/dev/IRISVOICE/evals/results/2026*.json"`; cohort: `page_relevance/v1` question,
engine `d1-2b-q4_k_m+systemone`, data = the app store's recorded crawler tool
results joined to their research records and eval verdicts, frame without a title;
the question was not worded against this data, so it is held-out for the wording):
96 distinct labelled inputs (61 cited, 35 not). Accuracy at 0.5 is 55/96 = 0.573
against 61/96 = 0.635 for "always yes"; P(yes) ranks the label at AUROC 0.560; the
fit's OOF AUROC is 0.492, ECE 0.078, no threshold. **At chance; fails the bar**
(rows < 100, AUROC < 0.65). Before the one-page rule the same run read 150 inputs,
AUROC 0.473.

**page_blocked has no replay.** No recorded store keeps the Tier-1 body of an
unusable page: `data/captures` saves usable pages only, `data/har` holds status,
headers and a body hash, the tool results hold usable pages only. Its cohort starts
with live traffic (~125 escalations in the 2026-11-10 log).

---

## 7. The bar

A consumer moves shadow -> enforced only on measured evidence. The measurement is
`scripts/consumer_enforcement_report.py` with the fit in
`scripts/fit_oracle_calibration.py`; the clauses are `consumer_bar._derive_hardened`.
All must hold; the first one missing is recorded as the gap.

### 7.1 Clauses

| # | Clause | Value |
|---|---|---|
| 1 | distinct rows | >= 100 (`MIN_ROWS`) |
| 2 | both classes present; minority share | >= 5% (`MIN_MINORITY`), or the NO-ERROR-MASS WAIVER |
| 3 | out-of-fold AUROC (does confidence rank errors?) | >= 0.65 (`MIN_AUROC`) |
| 3b | the model beats a TRIVIAL RULE that decides without it | model > rule |
| 4 | a calibrated threshold with out-of-fold precision at it | >= 0.90 (`MIN_PRECISION`) |
| 5 | Wilson 95% lower bound at that threshold | >= 0.85 (`MIN_WILSON_LB`) |
| 6 | distinct rows at or above the threshold | >= 50 (`MIN_ROWS_ABOVE`) |
| 7 | out-of-fold calibrated ECE | <= 0.05 (`MAX_ECE`) |
| 8 | ACTING clause: the answer that changes behaviour, above the threshold | >= 50 rows (`MIN_ACTING_ROWS_ABOVE`), precision >= 0.90, Wilson >= 0.85 |

- **The waiver (clause 2).** When the wrong class is under 5% because the data
  statistically EXCLUDES a 5% error rate (one-sided binomial, p <= `WAIVER_ALPHA`
  0.01), clauses 2 and 3 are untestable rather than failed; every other clause still
  applies. It is re-derived on every recompute, so real errors close it again. Thin
  data never qualifies (100 rows with 4 wrong does not exclude 5%).
- **The trivial rule (clause 3b).** `fit_oracle_calibration.rule_baseline` learns,
  on the same folds, a rule that sees only the input's key: the proposed tool when
  the question has one, otherwise nothing (the base rate / the most common answer).
  For a yes/no consumer the comparison is how well P(yes) ranks the truth (AUROC);
  for a choice consumer it is accuracy against the reference. The waiver does not
  lift it. The rule must decide WITHOUT the model: a rule keyed on the model's own
  answer only re-ranks the model and proves nothing. The fit also records
  `acting_region` (model vs rule on the rows above the threshold).
- **The acting clause (clause 8).** For a consumer that changes behaviour in one
  direction only, the other direction can carry the aggregate precision while the
  acting side is unsafe. `ACTING_ANSWER` names the acting answer
  (tool_approval "yes" - a confident "safe" skips the user's prompt; needs_action
  "no", review_verdict "veto" and depth_met "no" left with their consumers, 2026-11-10);
  `ACTING_ENFORCED` holds every asymmetric consumer. A new asymmetric consumer must
  be added to both. The threshold pick (`pick_threshold`) also requires the acting
  clauses at the picked value, so the pick can only move up.

Order of the gap: rows, both classes, minority, AUROC, the trivial rule, a threshold
exists, rows above it, precision, Wilson, ECE, acting.

### 7.2 Grouped out-of-fold folds

`fit_oracle_calibration.assign_folds` keeps every run of one eval task
(`eval-<task>-<6 hex>` -> `eval-<task>`, `consumer_enforcement_report.fold_group`) or
one session in ONE fold, dealt so each fold stays even in rows and in the rarer
label. A group larger than one fold is split into single rows (`split_rows`); a row
with no session stands alone. The eval cohorts repeat the same ~90 tasks, and a
split by row trains and scores on near-identical runs of one task.

### 7.3 The map must beat no map

`choose_map` keeps the isotonic map only when, on held-out groups of its own rows
(inner grouped folds), it is better calibrated (ECE) than the RAW confidence;
otherwise the entry stores `method: identity` and knots `[[0,0],[1,1]]`. The
out-of-fold score makes the same choice inside every outer fold (nested), so the
choice is scored on rows it never saw. A map fitted on some tasks can be
overconfident on unseen ones: on route_v2 the isotonic top bin said 0.963 and was
right 0.931 (ECE 0.060) while raw confidence held 0.042.

### 7.4 How the numbers are made

- **Distinct rows.** A row that carries `input_key` (bound at the call site: a hash
  of consumer, statement and frame) counts once per input; older rows dedupe on
  (consumer, engine, rounded confidence, chosen, reference, label). Repeats carry
  `repeats` and count once.
- **Label** (`decision_label`, one rule for the report, the fit and the replays). An
  `outside_label` (an observed outcome) is used first. Otherwise a shadow row is
  correct when the Oracle's answer equals the incumbent's (`brain_choice` as a name,
  `brain_bool` as a bool); a dispatched row is correct when its event outcome is
  success. Counted, never scored: a reference truncated off the menu, a control
  label against a parity reference, an outcome row with no outside label, a row with
  no reference. When ANY outcome rows exist, the fit uses only those
  (`mixed_dropped` reports the parity rows left out): two references never share
  one curve.
- **Fit.** Isotonic map (pool-adjacent-violators, blocks of at least 20 rows) or no
  map (7.3); 5 grouped folds (7.2). The threshold is the smallest calibrated value
  whose out-of-fold precision, Wilson bound and row count hold, plus the acting
  clauses for an `ACTING_ENFORCED` consumer.
- **Status** (`derive_status`): `enforced` when every clause holds; `sampled` when it
  is not, the consumer is in a sampling tier and has at least one outcome row;
  otherwise `shadow` with the gap.
- **Persist.** `consumer_enforcement_report.py --write` writes the bar record with
  each consumer's own decision identity; `fit_oracle_calibration.py` writes the
  calibration under the backend identity and every consumer's decision identity. The
  bar record is re-read on every `decides()` call and the calibration file when its
  mtime changes, so a new write applies without a restart. `IRIS_DECISION_ENFORCE`
  needs a restart.
- **Scope every enforced consumer on `--write`.** An unscoped consumer is measured on
  all its rows, which can blend stamps and demote it. Pass `--scope C=STAMP` for every
  consumer with a stamp (the flag repeats; a comma list is not supported), the same
  scopes for the fit.

### 7.5 Staying accurate as the app changes

- A new node tool declares its decision line in `ORACLE_HINTS`
  (`test_oracle_tool_hints_contract` fails without one).
- `menu_fp` separates evidence measured on one menu from another.
- A frame or question change gets a new `criteria_version` stamp; a criteria or cap
  change changes `criteria_hash` and drops the old threshold.
- Every writer stores the rendered question in the row's `state`
  (`test_sampled_rows_store_state_contract.py`), so every cohort can be replayed
  against a changed question or a new model.
- The turn verdict (first built for `depth_met`, retired 2026-11-10) arrives from outside the process: the eval harness
  posts each turn's hidden-test verdict to `POST /api/eval/verdict`
  (`backend/api/eval_verdict.py`); `turn_verdict_label` holds the row until it lands.

### 7.6 Limits

- A parity label caps a consumer at its incumbent's quality. When the incumbent is a
  deterministic rule, "always the most common answer" is a strong rival
  (`narration`, `presentation` lose to it).
- A frame field that IS the reference (narration `beats_admitted`, presentation
  `card_already_rendered`) lets a question that restates the rule pass every clause
  while measuring nothing. Such a pass is a copy, not a job: do not ship it. Both
  fields left the frames in `shape-v3` (2026-11-10).
- The engine's `confidence` field is documented upstream (System One API) as
  `1 - H(p)/ln(N)`, distribution concentration, "not calibrated correctness".
  Checked 2026-11-10 on every stored choice row: it ranks errors exactly as the
  top probability does (identical AUROC on browser_next, depth_route, narration,
  review_verdict, tool_choice), and the top-1 minus top-2 margin gains nothing
  outside tool_choice's class role. The readout is not why a job fails.
- A threshold applies to the cohort it was fitted on.
- IRIS records no trustworthy step-level truth today, so no step-completion consumer
  (a step judge, a post-execution review) can be certified until one exists.
- A narrow pass depends on the fold split: check it over several fold seeds
  (route_v2 passes on 16 of 20).

---

## 8. Performance and measurables

### 8.1 Headline

| Measure | Value |
|---|---|
| Decision latency (27-tool menu, 12 real coding tasks) | 175-190 ms p50, 418 ms p95 |
| Decision latency seen in node and turn logs | 19-358 ms; a turn-route consult 0.26-1.7 s (the first call after boot is the slow one) |
| Prefill, 27-tool menu | 703 tokens / 82 ms (option text capped at 120 chars) |
| Model on disk | `d1-2B-Q4_K_M.gguf` 1.10 GB + `mmproj-d1-2B-F16.gguf` 0.38 GB, shared with vision |
| VRAM for the d1 server | +2776 MiB at ctx 8192 / batch 8192 (8 GB card) |
| tool_choice class accuracy | 93.7% (398 rows); section 5 |
| tool_choice end to end, c14 | 73 s with the class decision vs 126 s without the Oracle |

### 8.2 Per consumer (bar record and calibration, identity `d1-2b-q4_k_m+systemone`)

Grouped folds, trivial-rule clause and map choice applied. "Rule" is the trivial
rule's number on the same metric (truth AUROC for yes/no, accuracy for choice).

The needs_action, review_verdict, narration, presentation, depth_met and depth_route
rows below are the measurement record of consumers RETIRED 2026-11-10.

| Consumer (stamp) | Distinct rows (right/wrong) | OOF AUROC | Model vs rule | OOF ECE | Map | Threshold (rows above, precision, Wilson) | Status / gap |
|---|---|---|---|---|---|---|---|
| route_v2 (`route_v2/binary-v1`) | 1240 (1091/149) | 0.785 | accuracy 0.880 vs 0.867 | 0.049 | none | 0.6148 (1195, 0.9004, 0.8821) | enforced in the record (parity label); no decision site |
| web_intent (`web_intent/v3`) | 430 (419/11) | 0.959 | truth 0.993 vs 0.464 | 0.007 | none | 0.6364 (430, 0.9744, 0.9548) | enforced (waiver); not on the allow-list |
| user_feedback | 742 (739/3) | 0.610 | accuracy 0.996 vs 0.992 | 0.001 | isotonic | 0.9938 (742, 0.996, 0.988) | enforced (waiver); no decision site |
| call_closing | 2570 (1878/692) | 0.681 | - | 0.030 | isotonic | 0.9594 (77, 0.935, 0.857) | enforced in the record; refused, never decides |
| needs_action (`needs_action/v7`) | 3570 (3334/236) | 0.823 | truth 0.953 vs 0.424 | 0.005 | isotonic | none | sampled: no threshold holds the acting "no" |
| review_verdict (`review_verdict/v11`) | 572 (321/251) | 0.492 | - | 0.070 | isotonic | none | sampled: AUROC; no decision site |
| tool_choice class role (`tc-decide-v9`) | 859 (790/69) | 0.776 | - | 0.024 | isotonic | 0.7596 = margin 0.30 (753, 0.936, 0.917) | enforced (class margin; section 5) |
| narration (`narration/shape-v2`) | 1002 (604/398) | 0.753 | accuracy 0.603 vs 0.811 | 0.059 | isotonic | 0.6674 (376, 0.902, 0.867) | shadow: the trivial rule wins (0.934 vs 0.902 above the threshold) |
| presentation (`presentation/shape-v2`) | 647 (312/335) | 1.000 | accuracy 0.482 vs 0.988 | 0.031 | isotonic | 0.1048 (339, 0.920, 0.887) | shadow: the trivial rule wins (0.985 vs 0.920 above the threshold) |
| tool_approval (`tool_approval/v6`, reliability; retired) | 11897 (6183/5714) | 0.499 | truth 0.578 vs 0.762 | 0.002 | isotonic | none | retired 2026-11-10: a per-tool rule beat it |
| tool_approval (`tool_approval/safety-v1`, answer sheet) | 470 (353/117) | 0.683 | truth 0.837 vs 0.594 (per-tool rule) | 0.035 | isotonic | 0.7599 (201, 0.906, 0.857; acting "yes" 195, 0.903, 0.853) | superseded: the question named only 4 of the policy's unsafe classes |
| tool_approval (`tool_approval/safety-v3`, answer sheet) | 470 (368/102) | 0.728 | truth 0.857 vs 0.593 (per-tool rule) | 0.021 | isotonic | 0.7931 (acting "yes" 207, 0.908, 0.861) | in-sample for the WORDING (v2 and v3 were written against these rows) |
| tool_approval (`safety-v3`, HELD-OUT sheet, threshold + map from the row above) | 200 (147/53) | 0.684 | agreement 0.735 vs the permission rule's 0.560 | - | (fixed) | 0.7931: acting "yes" 84, 0.869, Wilson 0.781 | FAILS: shadow. Confident misses: `cat ~/.ssh/*`, a force push, a folder deleted when one file was named |
| depth_met (`depth_met/v4`, the live question) | 200 (144/56) | 0.733 | - | 0.064 | isotonic | none | shadow: no threshold holds the acting "no" (clause 8 is unreachable: see 8.2 replays) |
| depth_route (`depth_route/v3`) | 334 (243/91) | 0.529 | accuracy 0.728 vs 0.716 | 0.062 | isotonic | none | shadow: AUROC |
| done (`done/v2`) | 176 (127/49) | 0.582 | truth 0.760 vs 0.419 | 0.046 | isotonic | none | shadow: AUROC |
| event_family | 54 | - | - | - | - | none | shadow: rows < 100 |
| recovery_strategy, sufficient | 0 | - | - | - | - | none | shadow: failure-only paths |

Replay measurements on recorded cohorts (`replay_consumer.py`, faithful frames and
the live question; the best variant):

| Consumer | OOF AUROC | Acting answer precision | Why it does not pass |
|---|---|---|---|
| needs_action | 0.94 (best criteria; 0.91 on a 2182-row hash-exact extended cohort) | "no" at most 40 of its top 50 right (needs 48) | only 44 of 1233 rows truly need no tool; the label is partly a function of the goal's WORDING (an action verb leads -> True by construction; no action word -> False by construction); re-measured 2026-11-10 on 1,233 distinct v7 rows: "always use a tool" is right 96.4%, d1's "no" is right 35 of 185 (16 of its top 50, 12 of its top 20); the earlier "word rule 48/50" figure did not reproduce; a "facts already gathered" field carries no signal and lowers d1 |
| tool_approval (v1-v6 reliability question, retired) | 0.667 (0.698 with the tool's recent outcomes) | "no" 27% (34% with them) | the gain is the model learning which tools are broken on this machine; a per-tool failure-rate rule beats it on every number |
| review_verdict | 0.43-0.56 | "veto" 0-44% | a pre-execution gate labelled by the post-execution outcome |
| depth_met | 0.69-0.79 (v3 and v4 rows; truth AUROC 0.87-0.91) | "no" 16-18% right | ranks the truth well, but only ~6% of turns fail and about half of those fail on infrastructure (rate limits, no browser) that a depth push cannot fix; clause 8 needs 48 right of 50 "no" answers and the v4 cohort holds 7 failing turns: unreachable at any wording |
| done | <= 0.51 (63 replayable rows) | - | the declared question never reached the model until 2026-11-10 (the registrar left the spec untyped, so the backend asked the generic AUTO_INSTRUCTION; `sufficient` the same); new rows are `done/v4` |

### 8.3 Cost per decision

- One Oracle question is one prefill of the rendered prompt; zero tokens are generated.
- On the node path, the pre-call `choose_node_tool` question is the only Oracle call a
  node waits for. Up to three more consults per executed call (parity, approval,
  browser element) run on the `oracle_shadow` lane, off the answer path.
- Prefill is bounded by the job budget: 384 ids (1536 chars) for `route` and
  `approve`; at most 128 for the rest.
- Admission under `IRIS_ORACLE_PHASE=1`: each question is a participant
  `"{session}:{consumer}"` in the phase domain `decision.oracle_cpu`; with
  `IRIS_ORACLE_PHASE_EXIT=1` a decision starts when a run slot frees (capacity 2);
  reply decisions have right of way; a gate fault admits. Without the flag: one
  engine lock (`acquire_timeout_s` 2.0 s) and a single-worker inference thread.
- Lanes (`backend/utils/durability_queue.lane`): one FIFO and one daemon worker per
  lane, bounded at 512 jobs; a full lane drops, counts and logs the job;
  `submit()` never blocks.

---

## 9. Core or boon: which jobs the Oracle owns

Every consumer is a JOB the application needs done, and every job already has an
INCUMBENT that does it. The Oracle takes a job over only when it is measurably better
than the incumbent AND a trustworthy outside label exists to prove it. A consumer
that cannot pass is not a broken job: the incumbent keeps it.

- CORE: the Oracle's answer changes speed or accuracy on the answer path in a way the
  incumbent cannot match. Worth label work.
- BOON: the incumbent is adequate; the Oracle is an improvement only if it earns the
  bar. No label work until a cheap outside label exists.

| Job (consumer) | Class | State | What it needs next |
|---|---|---|---|
| tool_choice (route) | CORE | LIVE and certified (class margin, 0.936 at the gate) | keep; measure web/browser menus on a working network |
| route_v2 (route) | incumbent decides (measured) | passes the bar on parity; on an outcome label the gate is better (97.9% vs 92.2%) | no site; send knowledge questions direct in the gate rule instead |
| narration, presentation (shape) | incumbent decides (measured: no honest pass) | the frame carries the answer: narration's reference is `steps >= 2` (and `beats_admitted` IS the reference); presentation's is `card_already_rendered`. Honest variants stay below the most-common-answer rule (narration 0.17-0.77 vs 0.825; presentation 0.980 vs 0.988 with the flag removed); only variants that copy the rule into the question pass | RETIRED 2026-11-10 (owner): both consults removed; reopen only with an outside label the incumbent can get wrong (a dismissed or reopened card, an interrupted narration) |
| tool_approval (approve) | shadow; the permission rule stays | the safety question beats the permission rule on agreement (sheet 0.783 vs 0.609; held-out 0.735 vs 0.560) but does NOT hold the bar on held-out rows (acting "yes" 0.869, Wilson 0.781). As "ask more" (refuse-only: P(safe) < t adds a prompt) no threshold reaches 0.90 on 50 rows. The real gap was the rule: with auto-approve on, 150 of the sheet's 179 unsafe calls ran unasked - fixed in the rule itself (`permissions.classify_tool`, 2026-11-10: 27/179 on the sheet, 24/86 held-out; PROGRESS S167) | stays shadow; live rows from the user's own permission answers (eval sessions never label). `evals/safety/heldout_sheet.jsonl` is the gate for any new wording - never word a question against it |
| depth_met (judge_depth) | incumbent decides (measured) | ranks the truth (0.87-0.91) but its acting "no" is right 16-18%: acting would push wasted work on most turns | RETIRED 2026-11-10 (owner), with its enforced depth push; reopen only with a failure-rich outside label (turns a depth push CAN fix) |
| review_verdict (judge_review) | BOON | at chance | RETIRED 2026-11-10 (owner); reopen only when a step-level truth exists |
| needs_action (interpret_step) | the incumbent rule (measured) | the label is True on 96.4% of 1,233 distinct rows; d1's acting "no" is right 16 of its top 50 | RETIRED 2026-11-10 (owner); fix the label's censoring first if the job is reopened |
| done, sufficient (judge_goal) | BOON | the declared question reaches the model only since 2026-11-10 | new `done/v4` rows; `sufficient` needs failure traffic (no rows) |
| web_intent (interpret_web) | DECIDES (allow-listed 2026-11-10) | earned; live gate research 31/35, no regression, ~50 ms per goal | keep; it agreed with the keywords on every gated goal, so its value is on goals without trigger words |

Before label or question work on a consumer, name its class here. CORE first; a BOON
only when a cheap outside label exists. A job with no trustworthy label stays with its
incumbent and is never forced to a pass.

---

## 10. Methods

### 10.1 Improving one consumer (hours, not days)

1. **Triage (minutes, read-only).** `consumer_enforcement_report.py --json --scope
   C=STAMP` on the newest stamp. Read accuracy, confidence quartiles, the acting side
   and the model-vs-rule numbers. Classify: (A) accurate but unprovable, (B) accurate
   but confidence does not rank, (C) often wrong (fix the question or the label),
   (D) too few rows, (E) a trivial rule matches it (the job is not the Oracle's).
2. **Replay (minutes per variant).** `scripts/replay_consumer.py --consumer C --stamps
   STAMP --variants current,bare,custom --options <json>`. Read the fidelity line
   first: "fresh ask vs the recorded row: same pick" must reproduce the recorded picks
   on the running model, or the replay measures a different question. Each variant
   prints the BAR's own verdict (`fit_consumer` + `derive_status`) and the per-answer
   precision.
3. **One change per variant.** Ship the winner under a new `criteria_version` stamp;
   never blend stamps.
4. **One confirming live cohort**, only for the replay winner; then `--write` and the
   fit with a `--scope` for every consumer with a stamp.
5. **Live gate.** Allow-list it, restart, run the eval group that exercises it against
   a same-session baseline, then record a landmark and a PROGRESS Standards row.

Rules each paid for by a measurement:

- **Diagnose offline, confirm with traffic.** A full eval pass takes about 2 hours
  and can only confirm a fix; a replay finds one in minutes.
- **Never feed a quality-blocked consumer.** Rows cannot fix AUROC < 0.65; more
  traffic is more of the same noise.
- **One input, one row.** Check the raw/distinct ratio and `skipped["duplicates"]`
  after a pass: a pass that adds rows without distinct inputs added nothing.
  Repeating one fixed task set doubled rows while true distinct inputs grew by 10.
- **When a confidence table is flat, suspect the LABEL before the model.** Split by
  input shape before concluding a capability limit.
- **A new row field goes into the bridge whitelist (`_DECISION_META_KEYS`) in the
  same change**, or it never reaches the ledger.
- **Join a log to rows by a key (`input_key`), never by sequence.**
- **Read the right eval number.** `reply_s` includes setup and seed turns; a memory
  recall's latency is `reply_s_ask`. Compare with a same-session baseline, not the
  stored standards, on this machine.

### 10.2 Replacing the decision model

A threshold describes ONE model's confidence curve, so a new model resets every
consumer to "not earned" (fail-closed by design). The swap is safe only when the
candidate is measured OFFLINE on the recorded cohorts BEFORE it serves live traffic.

**Step 1 - Check that the candidate fits the role.**

- It must answer the Decision Index API `/v1/systemone` with typed `choice` and
  `noul` questions and zero generated tokens: the GGUF carries Decision Index
  metadata and the server lists `decisions` in `output_modalities`. A model without
  it needs a new backend class (the `D1Backend.decide` contract: a `DecisionScore` or
  `None`) and a new readout name in `CURRENT_READOUT_MODE`. That is a larger change:
  write a spec first.
- It is also the VISION model (one shared server, one pin). Confirm it has a vision
  projector and that vision still works, or vision breaks with the swap.
- It must fit the VRAM budget with `--batch-size` = `--ubatch-size` = `n_ctx` (the
  native API needs the whole prompt in one batch). Measure VRAM and time to ready.
- Add its family token to `decision_backend_d1._D1_BUILD_TOKENS`. That one tuple is
  read by the boot pin check, the server command flags and the serving check.
- Tests that pin model file names (`test_model_pin.py`,
  `unit/test_wave2_d1_tool_server.py`) change with the pin; state each change.

**Step 2 - Freeze the baseline on the current model.**

- Copy `benchmarks/consumer_bar_record.json` and `benchmarks/oracle_calibration.json`
  aside.
- Record each consumer's bar numbers (section 8.2), the tool_choice class accuracy
  and margin buckets, and the decision latency (`benchmarks/oracle_jobs_bench.py`).
- Run same-session eval baselines: `evals/run_evals.py --task c13_explain_code
  --task c14_run_and_report` and `--group memory`.
- Run each replay once on the CURRENT model and confirm its fidelity line
  reproduces the recorded picks. A replay that does not reproduce on the current
  model cannot judge a candidate.

**Step 3 - Replay every consumer's newest cohort through the candidate.**

Serve the candidate on `:8082` (pin it, restart), then, with `--engine` set to the
CURRENT model's id (the source cohort):

- `scripts/replay_consumer.py --consumer C --engine <current id> --stamps <stamp>`
  for each stateful consumer;
- `scripts/replay_tool_choice.py --engine <current id>` for the tool menu; score the
  class of each fresh top-1 with `tool_choice_action_class.classify_tool` against the
  rows' action-class label (the label `scripts/action_class_label.py` reads).

The replay judges with the bar's own derivation (grouped folds, trivial rule, map
choice). Outside labels and parity labels carry over to the candidate unchanged. A
label that depended on what the outgoing model's pick made happen (a forced pick's
outcome) does not transfer: count those rows separately.

**Step 4 - Decide on numbers, then swap.**

- Keep the candidate only if every consumer that DECIDES today (an earned bar AND
  a decision site; `NO_DECISION_SITE` has none) holds its bar on the replay, the class accuracy and margin buckets are no worse, and latency p50 / p95
  stay within budget. A consumer that loses its bar returns to its incumbent; name it
  in the decision.
- Re-tune the questions BY REPLAY ON THE CANDIDATE before the swap. Questions tuned
  on one model do not transfer to another.
- Swap: pin the candidate in the Models card, set its `last_ctx`, restart. The boot
  log shows `[D1BOOT]` and the enforcement line shows every consumer "not earned":
  this is expected.
- Never copy bar records or thresholds to the new identity. Re-earn: the live cohort
  for each replay winner (the report scopes rows to the active engine itself), then
  `--write` and the fit with a `--scope` for every consumer with a stamp.
- Run each deciding consumer's live gate against the baseline from step 2, record a
  landmark and a PROGRESS row, and update sections 1, 2, 8 and 9 of this file.
- A fine-tune is model-specific: `scripts/finetune_d1_lora.py` trains only the
  format it was written for. A new model needs its own trainer, and a merged
  fine-tune is a NEW identity that re-earns every bar.

**Mistakes the last swap made - do not repeat them:**

| Mistake | Cost | Rule now |
|---|---|---|
| Questions tuned on the outgoing model went live untuned | most bars failed on the incoming model | re-tune by replay on the candidate (step 4) |
| Rows stored no question | those cohorts could not be replayed at all | every writer stores `state` (guarded) |
| The replay asked a different question (label, criteria, instruction, frame) | variants looked good offline and failed live | fidelity line first, on the current model |
| Live traffic was the tuning loop while labels and questions changed | about a week of 2-hour passes | offline first; one live cohort only to confirm |
| Folds split by row on repeated eval tasks | optimistic out-of-fold numbers | grouped folds (built in) |
| A model-free rule could pass the bar | a "pass" that measured broken tools, not decisions | trivial-rule clause (built in) |
| A calibration map overfit the tasks it saw | a real ECE miss on unseen tasks | the map must beat no map (built in) |
| The aggregate passed while the acting side was unsafe | a consumer pushing wrong work 95% of the time came close to passing | acting clause for every asymmetric consumer |
| `--write` without a scope for every enforced consumer | demotes the consumers it blends | always scope every consumer with a stamp |
| A narrow pass read from one fold split | a coin-flip certification | re-run the bar over several fold seeds |
| An earned bar was read as a live decision | a consumer with no decision site was reported as deciding | find the `decides()` caller; `NO_DECISION_SITE` + its guard |

---

## 11. Operations

### 11.1 Environment flags

| Flag | Default (`.env`) | Effect |
|---|---|---|
| `IRIS_DECISION_ENFORCE` | empty (owner's local `.env`, 2026-11-10: `tool_choice,web_intent`) | consumers the owner lets decide; each also needs an earned bar on the running identity AND a decision site; a retired consumer in the list is ignored (only `CONSUMERS` members parse) |
| `IRIS_ORACLE_TOOL_CHOICE_CLASS_DECISION` | unset (1) | the class decision of section 5 |
| `IRIS_ORACLE_TOOL_CHOICE_SHORTLIST_K` | unset (5) | shortlist depth; also the class-mode fallback; `0` = off |
| `IRIS_ORACLE_TOOL_CHOICE_ALWAYS` | unset (0) | `1` = forced top-1; keep OFF |
| `IRIS_ORACLE_FORCE_MIN` | 0.9 | raw confidence a SAMPLED tool pick needs to be binding |
| `IRIS_ORACLE_SAMPLE` | on | `0` kills all sampling |
| `IRIS_ORACLE_SAMPLE_FRACTION` | 0.05 | sampled share for every samplable consumer |
| `IRIS_ORACLE_SAMPLE_FRACTION_<CONSUMER>` | unset (`_TOOL_CHOICE=1`) | per-consumer share |
| `IRIS_ORACLE_SAMPLE_SIDE_EFFECTS` | unset | `1` lets a sampled pick force a side-effect tool (eval folders only) |
| `IRIS_ORACLE_PHASE`, `IRIS_ORACLE_PHASE_EXIT` | off (1, 1) | phase-model admission; `0` returns to the engine lock |
| `IRIS_ORACLE_PHASE_PERIOD_S`, `_MAX_WAIT_S`, `_K` | 0.3, 0.3, 0.6 | phase gate tuning |
| `IRIS_ORACLE_BATCH_CAP` | 8 | width of a batched pass (no production caller) |
| `IRIS_NODE_TOOL_MENU_K` | unset | re-enables the goal-only node menu cut while the class decision is on |
| `IRIS_D1_CHECK_TTL_S`, `IRIS_D1_TIMEOUT_S` | 300, 20 | serving check cache, HTTP timeout |
| `IRIS_LOCAL_MODEL_PORT` | 8082 | the shared llama-server port |

**Off switches.** A consumer: remove it from `IRIS_DECISION_ENFORCE` and restart. The
tool_choice role: `IRIS_ORACLE_TOOL_CHOICE_CLASS_DECISION=0` and
`IRIS_ORACLE_TOOL_CHOICE_SHORTLIST_K=0` return the full menu to the tool model.
Everything: serve a model that is not a d1 build; every consumer returns to its
incumbent.

### 11.2 Scripts

```
# per-consumer status vs the bar (read-only); --write persists the bar record
python scripts/consumer_enforcement_report.py [--json] [--write] --scope C=STAMP ...

# fit the calibration maps and thresholds; --dry-run writes nothing (same scopes)
python scripts/fit_oracle_calibration.py [--dry-run] --scope C=STAMP ...

# reliability table, ECE/Brier, coverage curve (read-only)
python scripts/calibrate_decision_threshold.py [--since ...] [--json]

# replay a consumer's recorded questions through the served model (no writes)
python scripts/replay_consumer.py --consumer C --stamps STAMP [--variants current,bare,custom --options <json>] [--engine ID]
python scripts/replay_tool_choice.py [--stamps ...] [--engine ID]
python scripts/bench_tool_safety.py [--limit N]   # evals/safety/answer_sheet.jsonl -> data/oracle_bench/tool_safety.db
python scripts/replay_page_relevance.py [--dry-run] [--max 300] [--results <glob>]   # section 6.3

# the tool_choice action-class label on the stored rows (read-only)
python scripts/action_class_label.py

# per-job decision latency on the real model
python benchmarks/oracle_jobs_bench.py [--reps 9]

# outcome-checked decisions -> fine-tuning JSONL in the native request format
python scripts/export_tool_choice_training.py --out data/training/tool_choice.jsonl
```

All scripts take `--db`; the default is `scripts/_app_store.py`, which uses the
application's own resolver (`resolve_memory_store_path`). The store is encrypted:
run them with `.venv` python. Replays need the backend up (the d1 server on `:8082`).
Live validation: `python evals/run_evals.py --group coding|memory|browser|research`.

### 11.3 Reading the logs

- `Oracle enforcement: deciding=[...]; allow-listed but NOT deciding=[...]` - once per
  process, at the first decision; names the missing key per consumer.
- `Oracle decide consumer=... chosen=... conf=... decision_latency_ms=...` - one line
  per decision.
- `[TOOL_DECISION] Oracle decides tool=... route=class|shortlist ...` - a node pick;
  `class` means the Oracle chose the class, `shortlist` the top-k.
- `NOT enforcing <consumer> - its bar was measured on ...` - the running identity
  differs from the bar's. `thresholds are STALE` - the cap differs from
  `calibrated_cap`.
- `[D1BOOT] ...` - boot load, pin check and the vision proof.

---

## 12. Contracts and guards

Under `backend/tests/` (`contract/` unless a path is given).

**Engine, identity, chokepoint**

- `test_decision_engine_contract.py`, `unit/test_decision_engine.py` - envelope, lazy lifecycle, degrade to `None`.
- `test_oracle_enforcement_contract.py` - `decides()` needs all four keys; the default decides nothing.
- `test_bar_record_enforcement.py` - a flip fires only on the identity it was measured on.
- `test_decision_identity_contract.py` - `model|readout|criteria_hash`; a criteria or cap edit empties the threshold.
- `test_model_pin.py`, `unit/test_wave2_d1_tool_server.py` - the pinned build and its server flags.
- `test_consumer_declarations_contract.py`, `test_consumer_registry.py`, `test_surface_observer_contract.py` - declared types and criteria; an undeclared consumer scores nothing.
- `test_escalate_incomplete_retired_contract.py` - the retired consumer and its job stay removed.
- `test_six_consumers_retired_contract.py` - narration, presentation, review_verdict, depth_route, needs_action and depth_met (and their four jobs) stay out of every registry and record; no former site consults the Oracle; each incumbent still decides.
- `test_no_decision_site_contract.py` - `NO_DECISION_SITE` matches the source; the log never calls a shadow-only consumer "deciding".
- `test_page_shadow_contract.py` - page_relevance / page_blocked: production callers, lane-only consults, frames without the label, the outside labels and their unlabelled cases.
- `test_readonly_engine.py` - the engine writes nothing to the memory graph.
- `test_oracle_phase_contract.py`, `test_phase_domain_exit_admission.py` - phase admission.
- `test_raw_threshold_contract.py` - `threshold_for` resolves the active curve on the raw scale.

**Input, readout, jobs**

- `test_d1_native_readout_contract.py` - the typed question, the answer shape, the fail-closed paths.
- `test_oracle_jobs_contract.py`, `test_oracle_frame_evidence_contract.py` - the engine owns input and budget; reference fields never reach the model.
- `test_oracle_batch_contract.py` - batching isolation.

**Tool choice**

- `test_oracle_tool_hints_contract.py` - every node tool declares an `ORACLE_HINTS` line.
- `test_menu_composition_contract.py`, `test_tool_choice_menu_reachability_contract.py`, `test_shadow_tool_choice_menu.py` - control labels survive the cap; every tool is reachable.
- `unit/test_tool_choice_action_class.py`, `test_tool_choice_label_contract.py`, `test_tool_choice_outcome_label_contract.py`, `test_tool_choice_class_unmapped_contract.py` - the class decision, the margin gate, the shortlist, unmapped tools.
- `test_node_menu_cut_yields_to_class_decision_contract.py` - one narrowing, not two.
- `unit/test_node_executor.py` - the node loop, the shortlist / class list branch.
- `test_sampled_rung_contract.py` - tiers, share, deterministic draw, read-only gate.

**Rows, labels, the bar**

- `test_decision_engine_ledger.py`, `test_shadow_row_sink.py` - one ledger row per decision through the real bridge, off the answer path.
- `test_consumer_row_reference.py`, `test_oracle_reference_separation_contract.py`, `test_decision_label_unscoreable_contract.py` - every row has a reference; curves never blend; unscoreable rows are counted.
- `test_sampled_rows_store_state_contract.py` - every sampled writer stores its question.
- `test_oracle_calibration_contract.py`, `test_consumer_bar_record.py`, `unit/test_consumer_enforcement_report.py` - confidence scale, distinct rows, the clauses.
- `test_bar_grouped_folds_rule_contract.py` - grouped folds, the trivial-rule clause, the map-or-no-map choice (nested).
- `test_replay_consumer_instrument_contract.py` - the replay asks the live question with the bar's label and verdict.
- `test_memory_oracle_view_contract.py` - the Memory view's ten-clause ladder.

**Per consumer**

- `test_tool_approval_contract.py` - the safety frame carries no verdict; only the user's own permission answer (never an eval session's) labels a row.
- `test_browser_next_contract.py` - page elements are the options.
- `test_click_safety_contract.py` - browser actions pass the click-safety gate.
- `test_call_closing_fence_contract.py` - `call_closing` is refused everywhere.

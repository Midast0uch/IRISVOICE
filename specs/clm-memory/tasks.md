# Tasks: CLM Memory

Revised 2026-11-11 with `requirements.md` and `design.md` (read both first).
START HERE: MCM `pin_0fc690093220` (recall hand-off) and the pin titled
"PLAN 2026-11-11: CLM spec revised + kernel decomposition blueprint".

Every task carries DONE = (the one observable end condition) and NOT THIS = (the
over-build it invites). A task ends when DONE is true. Each wave ends with a live
gate; a wave behind a flag that is off is not finished (CLAUDE.md step 8).

Method for every wave: the measured loop (app-testing skill, Mode A). Backend
detached, `/health` 200, tool model loaded, quiet machine, targeted tests only,
same-conditions A/B, numbers named with their cohort.

> ### GATE G-KERNEL (before Wave 1)
> The kernel context domain is extracted (`docs/architecture/KERNEL_DECOMPOSITION.md`
> Stage A guards + move M3 "context"). CLM code is written in `context_view.py`,
> `context_gauge.py` and the extracted context module, never in the `agent_kernel.py`
> facade. If the owner wants CLM first, Waves 0-1 may run before the split ONLY IF
> they add nothing but call sites to the kernel; say so in the commit.
> **Record here:** [x] PASSED date: 2026-11-11 evidence: move M3 commit 4b52c867 (`backend/agent/kernel/context.py`); all twelve moves done (a6061534); live cohort 21/21 before and after

## Wave 0 - Baseline and questions (no behavior change)

- [x] **T0.1** (CLM-0 AC1-AC3): instrument and measure the blind cuts and the three
  estimators over the cohort (coding 8, research >= 10, memory 3). Output:
  `evals/results/clm-baseline-<date>.json` + a table in this file.
  DONE = the table exists with drop counts, estimator error distributions per
  (provider, model), and block-size distributions per kind.
  NOT THIS = a metrics framework; fixing anything found; a new table.
  RIPPLE: `router.py:487-494` (count what the warning already knows),
  `transport.py:436-481`.
  **T0.1 RESULT (2026-11-12, cohort coding 8 + research 10 + memory 3, opencodego /
  deepseek-v4.1-flash, 137 model calls, instrument failures 0, lane drops 0;
  `evals/results/clm-baseline-2026-11-12.json`, instrument flag `IRIS_CLM_BASELINE=1`,
  report `scripts/clm_baseline_report.py`):**

  | Measure | Value |
  |---|---|
  | Router cap drops (`_cap_messages_to_window`) | 0 calls, 0 messages, 0 tokens in 24 conversations |
  | Direct path: recency cut / chars-4 budget trim / align pops | 0 / 0 / 0 |
  | Direct path: derived `<memory>` suppressed | 8 conversations (research 2, memory 6) |
  | `_mcm_orch.pre_call` (DCP) message count change | 0 |
  | Estimator error vs real `prompt_tokens`, n = 129: kernel chars/4 | median -33.6 %, 90 % of calls within +/-73.9 %, worst 84.0 % |
  | router chars/3.5 + 16 | median +10.0 %, within +/-31.7 %, worst 36.6 % |
  | `MCM.count_tokens` (tiktoken cl100k) | median -32.6 %, within +/-75.4 %, worst 85.1 % |
  | Block sizes (router unit): tools schema | median 1,733, p95 5,968 |
  | user message | median 359, p95 3,400, max 16,193 (the planner prompt) |
  | tool result | median 38, p95 2,237, max 2,298 |
  | system | median 499, p95 1,396 |
  | Direct path (chars/4 unit): system prompt 1,147; recall chunks median 257, max 832; profile median 203, max 801; history | n = 0 (every eval turn is a first turn) |

  **What this baseline means for the later waves (read before TG-1 / TG-2):**
  - THIS COHORT HAS NO PRESSURE. Zero blind cuts before CLM, so "blind drops = 0" on
    this cohort proves nothing. TG-2 must show it on `--group context` (T2.7), whose
    tasks assert their own pressure ratio. This cohort stays the NO-REGRESSION check.
  - The estimator gap is real: the two low estimators miss the tools schema and tool
    calls. T1.4's 5 % target is measured against these numbers.
  - No eval turn has history, so the direct-path history trim and the "empty history
    when the budget is negative" case (T0.1 finding 7) are NOT exercised. T2.7 needs
    one multi-turn task.
  - Finding (T1.4 must fix): `transport.last_usage` is shared by concurrent calls to
    one provider, so a parallel node can read another call's usage.
  - Open (Q3): no cached-token field is parsed; the instrument does not capture raw
    usage. Add one raw capture when T5.3 starts.

- [ ] **T0.2** (CLM-0 AC4): answer design Q1-Q4 with file:line; write the answers into
  `design.md` "Open questions" and correct the Ripple-Effect Map.
  DONE = Q1-Q4 each have an answer with evidence, and the map has no "maybe".
  NOT THIS = starting the view.
  STATUS 2026-11-12: Q1-Q4 answered in `design.md` "Open questions"; Q3 provider facts
  stay OPEN (need one raw usage/timings capture per provider; T0.1/T5.3 instrument).
- [ ] **T0.3** (CLM-0): re-measure the Inherited Ground counts on the live store
  (read-only, `.venv` python - only it has sqlcipher3) and replace the 2026-11-01
  numbers in `requirements.md`.
  DONE = the counts carry today's date.
  NOT THIS = any write to the store.
  STATUS 2026-11-12: done, counts and findings are in `requirements.md` "Inherited Ground".
- [ ] **TG-0**: owner answers Q-A, Q-B, Q-C (requirements "Open Questions"); the
  answers move to Decisions Locked.

## Wave 1 - The view at parity + the one gauge (still no shrink change)

> **Wave 1 part A done 2026-11-12 (modules only, nothing wired):**
> `backend/agent/context_view.py` (Ref, Block, ContextView.admit/render),
> `backend/agent/context_gauge.py` (estimate_tokens = the router rule; ContextGauge with
> a per-(provider, model) EMA ratio), `contract/test_view_parity_contract.py` (CT-1, 9
> tests; 4 fail on a reordered render), `contract/test_context_gauge_contract.py` (13
> tests) with the 129 real Wave 0 calls as fixture.
> **Decisions (Director, 2026-11-12):**
> - Block kind names on the direct path are the Wave 0 instrument's names
>   (`system_prompt`, `recall_episodic`, `recall_profile`, `recall_chunks`, `history`,
>   `current_user`); node-path kinds are named in T1.3.
> - CT-9 is two tests: CT-9a the gauge behavior (exists), CT-9b the source guard that
>   the three old estimators are gone (written with the T1.4 wiring).
> - The first observation seeds the ratio (not 1.0): the raw rule is ~10 % high.
> - THE 5 % TARGET IS NOT YET PROVEN REACHABLE. Offline on the Wave 0 calls the one
>   ratio gives signed median -0.5 %, |p95| 18.7 % (raw: +10.0 %, 32.8 %). More terms
>   do not help (two-term and per-kind least squares are worse). BUT those calls were
>   recorded BEFORE the per-call usage fix (0b88901c): a parallel call could carry
>   another call's `prompt_tokens`, which is noise in the "real" column. T1.4's live
>   gate re-measures on clean data; the bar is then set from that measurement and
>   written here. Do not add a second term before that.
>   **RE-MEASURED 2026-11-12 on clean data** (228 calls recorded AFTER the per-call
>   usage fix, same cohort + a second coding pass, opencodego / deepseek-v4.1-flash):
>   raw rule signed median +7.1 %, |median| 7.7 %, |p95| 21.7 % (the old data's 32.8 %
>   was partly the usage race); calibrated |median| 3.5 %, |p90| 12.0 %, |p95| 18.0 %,
>   max 40.4 %. Calls without tools are worse (+11.2 % median) than calls with tools
>   (+5.9 %). So a character rule with one ratio centres the estimate but cannot make
>   single calls 5 % accurate; that needs a tokenizer, which CLM-4 excludes.
>   **THE BAR (set from this measurement, replaces "p95 <= 5 %" in T1.4 and CLM-4):**
>   calibrated |median| <= 5 % AND |p95| <= 20 % per calibrated (provider, model); and
>   the harness shrink MARGIN (T2.3) is never smaller than the measured |p95| of that
>   pair (default 20 %), so an under-estimate inside the p95 cannot overflow the
>   window. The margin, not the estimate's precision, is what guarantees the window.
> - Finding: `import backend.agent.context_view` runs `backend/agent/__init__.py`,
>   which imports the whole kernel (~75 modules). The modules themselves import only
>   the standard library. Fix = a lazy package `__init__` (own measured change).
> - The view renders BEFORE `_mcm_orch.pre_call`; the wiring runs `pre_call` on
>   `render()` (CLM-9 AC5).

- [x] **T1.1** (CLM-1 AC1-AC3, AC6): `context_view.py` with `Ref`, `Block`,
  `ContextView.admit/render`; route `_assemble_direct_context` through it.
  DONE = CT-1 passes on recorded inputs (byte-equal) and fails when one block is
  reordered.
  NOT THIS = zones, policy, placeholders, a base class, a plugin point.
  RIPPLE: `_sanitize_messages` order; `_mcm_orch.pre_call` (`_assemble_direct_context`, last lines) still runs
  after AND mutates the list (`pre_call_flow.json`: `dcp_prune`, `mito_inject` at `[1]`, `pacman_recall` at
  `[2]`): CT-1's "old builder" output is assemble + pre_call, recorded after pre_call (Q1).
- [x] **T1.2** (CLM-1 AC2): references on blocks. Chunk ids via T0.2/Q2; chain,
  episode, thread, pin ids from their rows; `ephemeral` for system and user turn.
  DONE = on the T0.1 cohort replay, 100 % of non-ephemeral blocks resolve to a row.
  NOT THIS = changing recall scoring or its return order.
  Q2 answer: the `with_meta` dict lacks `id`; add `"id": cid` (`episodic.py:1616-1625`).
  RIPPLE: every caller of `retrieve_context_chunks` (kernel x6, `tool_bridge.py:552`,
  `evidence.py:225`, `recall_decoder.py:436`, `research_memory.py:482`) keeps its current return shape.
- [x] **T1.3** (CLM-1): the DER node list and synthesis through the view (points from Q1).
  DONE = CT-1 covers node and synthesis inputs; BT-W10-2 and the synthesis diet
  contract pass.
  NOT THIS = touching the planner prompt.
  RIPPLE (Q1): the node list is built in `backend/agent/node_executor.py` `run_node` (`:648`), not in
  the kernel, so this task edits that file (call sites only); `_der_bound_step_context` is not a
  pressure site (it cuts a field no prompt reads) and is left alone; synthesis is one user message
  (`kernel/der/report.py:1450`), not a list.
- [x] **T1.4** (CLM-4 AC1, AC2, AC5; CT-9): `context_gauge.py`; move the router
  estimator into it; delete `_count_tokens` and `_DIRECT_CTX_BUDGET`; `observe()` from
  the router after each call.
  DONE = CT-9 passes; live error |median| <= 5 % and |p95| <= 20 % per calibrated (provider, model) (THE BAR above) on the
  cohort, reported beside the T0.1 "before".
  NOT THIS = loading a tokenizer; persisting calibration; a per-provider class.
  RIPPLE: ContextPill value source (CT-6; T29 / parity tests - state any input change).
- [x] **T1.5** (CLM-2 AC6, CLM-8 AC3): the router cap reports each drop to the view
  counter; the per-call structured line.
  DONE = the cohort report shows blind drops per task equal to the T0.1 drop counts
  (nothing prevented yet - the alarm is proven live first).
  NOT THIS = preventing the drops in this task.
> **TG-1, part B1 (direct path + router), PASSED 2026-11-12:** cohort 21/21 and the 8
> coding tasks a second time 8/8 (default reasoning, opencodego / deepseek-v4.1-flash);
> `view_fallback` = 0 over 8 direct rows; blind drops 0 (this cohort has no pressure);
> instrument failures 0; gauge on 205 live calls: |median| 3.7 %, |p90| 12.0 %,
> |p95| 17.8 % (inside THE BAR). Function-level parity: old vs new
> `_assemble_direct_context` byte-equal on 11 inputs. Done in B1: T1.1 (direct path),
> T1.4 (one estimator in the router, GAUGE.observe; the kernel's chars/4 trim STAYS
> until T2.3 - replacing it changes which history messages are kept: 46 vs 40 on a
> long history), T1.5. Open for B2: T1.2 (refs), T1.3 (node list, synthesis).
> **TG-1 FULL, PASSED 2026-11-12 (Wave 1 complete):** cohort 21/21 and the 8 coding
> tasks a second time 8/8; `view_fallback` = 0 on the direct path, the node path and
> synthesis (219 calls, 10 direct rows, 0 fallback log lines); blind drops 0; instrument
> failures 0; S2 `test_answer_path_standards` 13 pass. Parity proofs: direct path 11
> inputs, node path 11 cases at EVERY model call, synthesis 6 cases - all byte-equal;
> each harness fails on a 1-character change. Refs: 745 of 745 recall rows carry a row
> id (chain 387/387 and chunk 358/358 resolve on the live store, read-only).
> **Carried into Wave 2 (from the T1.2 / T1.3 reports):**
> - Earlier step results and memory facts are TEXT inside the one `step_goal` message
>   (`node_executor._user_message`), not blocks. Splitting them is a behavior change;
>   if Wave 2 wants them offloadable, that split is its own task with its own parity
>   exception stated.
> - A tool call and its results are separate blocks today (`assistant_tool_calls` +
>   the `tool_result`s that follow). The offload gate MUST treat them as one unit.
> - `Block.tokens` of a live block goes stale after an in-place edit (a replaced
>   screenshot keeps the image count). T2.3 recounts before it decides.
> - The merged recall block is offloaded/expanded as ONE unit with its ordered refs.
> - Node-path kinds for the instrument: a ContextVar `RENDER_KINDS` in `context_view`
>   set by the node loop's send, read (pre-cap) by `clm_baseline.record_call`.
> - `generate` now receives a fresh list per call (not the loop's live list). No
>   consumer keeps it today (router, cap, transports checked).
> - Node blocks are `ephemeral` (no row yet): a tool result's row id must come from
>   where the result is stored (`der_fan_traces` / tool-event rows) - T2.2 names it.
- [x] **TG-1 (live gate)**: same cohort, parity commit vs baseline: pass counts equal,
  `reply_s` within the standards' tolerance, `view_fallback` = 0.

## Wave 2 - Offload, placeholder, re-expand (the first behavior change)

> **Wave 2 state 2026-11-12.**
> DONE (unwired): T2.1 + T2.2 core in `context_view.py` (placeholder, MIN_SAVING = 256
> from 730 real tool messages, `offload_decision` with nine counted refusal reasons,
> `set_aside_batch` / `restore`; a set-aside keeps every message in place and replaces
> only the result CONTENT, so no orphan tool_calls and no role change);
> `contract/test_view_offload_gate_contract.py` 16 tests. T2.7 the `--group context`
> tasks x01-x05 with seeded fixtures, `evals/context_report.py`, `prior_turns` in the
> harness, and an eval-only message dump (`IRIS_CLM_DUMP_DIR`).
>
> **BEFORE run of `--group context` (two passes, opencodego / deepseek-v4.1-flash,
> window 128,000, no offload code live):** x01, x02, x03, x04 PASS 2/2; x05 FAIL 2/2
> (the 30,000-char pasted turns each start heavy work: 168 model calls, ~30 min, a
> prior turn got no reply - the task as built measures a timeout, not history; it
> must be redesigned before it counts). Max context fill 0.06-0.20 (x05 0.31), blind
> drops 0, needed facts in the final call: x01 7/7, x02 1/1, x04 4/4, x03 3/12 (it
> still passed: the model carried computed values, not the leaves).
> **What this means:** on a 128k model the node path cannot fill the window (one node
> tops out near 42k tokens = 0.33) and these tasks pass WITHOUT CLM. The gain must be
> shown where pressure exists: a small-window local model (T2.8). T2.8 therefore moves
> INTO the Wave 2 gate: same tasks, same small model, offload off vs on.
>
> **WHERE A TOOL RESULT LIVES (owner decision 2026-11-12, replaces "document store"):**
> the document store is for ARTIFACTS (web/research results, documents the agent
> makes); tool results do not go there. The exact text of a node tool result goes to
> the CHAT RECORD (`data/conversations.db`, `backend/conversation_store.py`) in a new
> table keyed by conversation and turn, deleted with its conversation; the NODE
> TAXONOMY carries the reference: the `OFFLOADED` memory event (label already seeded,
> payload = the ref, never content - S12) links the node to that row, so the memory
> dashboard can show it on the strand. Rules: write on an ordered lane, never on the
> answer path; only a result longer than what later steps keep (> 2,500 chars);
> never a store read; a size cap per row and a row cap per conversation (growth has
> a budget); `Ref(kind="tool_result", id)`. Note for the owner: conversations.db is
> a PLAINTEXT sqlite file (memory.db is encrypted); chat messages already live
> there in plaintext, and tool results (file contents) would too.
> The in-node `held` ref (the view returns its own bytes while the node runs) stays
> for the node's own restore; a placeholder that can outlive the node carries the
> `tool_result` ref.

- [ ] **T2.1** (CLM-2 AC1, AC5): placeholder format + break-even from T0.1 data.
  DONE = unit tests on format and arithmetic; `MIN_SAVING` written with its measurement.
  NOT THIS = a template system.
- [ ] **T2.2** (CLM-2 AC2; CT-2): the offload gate (ref readable, bounded wait on a
  queued write, open items carried, tool call/result unit).
  DONE = CT-2 passes; on a replay, offloaded-but-unreadable = 0.
  NOT THIS = a new lane; a retry scheduler.
- [ ] **T2.3** (CLM-5 AC5, CLM-10 AC2): harness default shrink order at node boundaries
  and the gauge margin, one batch per boundary.
  DONE = BT-2 passes (no model edits, run stays in budget, blind drops = 0).
  NOT THIS = a policy engine; per-tool configuration; an Oracle consult.
- [ ] **T2.4** (CLM-2 AC3, AC4; CT-3; BT-3): expand by reference with the four named
  failure cases; forget guard extended to this path.
  DONE = CT-3 and BT-3 pass.
  NOT THIS = fuzzy lookup when the ref misses.
- [ ] **T2.5** (CLM-8 AC1, AC2, AC5; CT-4): emit `OFFLOADED`, `RESTRETCHED`,
  `PREMATURE_EVICTION` on the `memory_events` lane.
  DONE = CT-4 passes and fails on a version that writes on the loop thread; the memory
  dashboard shows the three events from a live run.
  NOT THIS = new labels; a new table.
- [ ] **T2.6** (CLM-4 AC3, AC4; CLM-6 AC2, AC4; Q-B; CT-5, CT-8): the gauge line and
  reminder in tool results; `recall_memory` `expand` / `set_aside`; the reference-data
  frame.
  DONE = CT-5 and CT-8 pass; a live run shows one model-initiated set-aside or expand
  in the events (if none in the cohort, report 0 - do not prompt for it).
  NOT THIS = policy text in the tool description; a second tool.
- [ ] **T2.7** (CLM-7 AC1): the `--group context` eval tasks (KV store, log triage,
  needle retention, sketchpad), each asserting its pressure ratio, graded from the
  captured view.
  DONE = the group runs detached and reports per-task pass.
  NOT THIS = grading from the store; lowering pressure to pass.
- [ ] **T2.8** (CLM-5 AC5, CLM-6 AC2; owner 2026-11-12): the small-model run. Load
  `D:/lmstudio/models/LiquidAI/LFM3-1.7B-GGUF/LFM3-1.7B-Q8_0.gguf` through the app's model
  load manager (`POST /api/models/load`; check first that the load does not evict d1 on
  :8082 - the Oracle needs it) and run `--group context` with it as the node model.
  Report two numbers per task: (a) harness result - pass, in budget, blind drops = 0 with
  NO model edit (the guarantee, BT-2); (b) model-initiated edits - count of `set_aside` /
  `expand` calls the model made itself (the option). Then the same for the other small
  models in that folder that load (LFM2.5-2.6B, LFM3-Omni-2B).
  DONE = the table exists in this file with (a) and (b) per model per task.
  NOT THIS = prompting the model to edit so the count is not 0; a per-model prompt;
  counting a harness offload as a model edit.
> **Wave 2-4 live results (2026-11-15).**
> CLOUD (opencodego deepseek-v4.1-flash, 128k): flag OFF cohort 21/21 + context 5/5;
> flag ON cohort 21/21 + context 5/5 (evals/results/20261115-123853, -125311 off;
> -132735, -134339 on). Flag on: 27 tool results recorded, step ref lists reached
> 29 of 217 later calls, gauge line in 58; nothing set aside (128k never fills).
> SMALL MODEL T2.8 (LFM3-1.7B-Q8_0 on :8091 as tool_execution, 8,192 tokens per
> request, reasoning on the cloud model): context 0/5 with the flag OFF and 0/5 ON
> (-142445 off, -144640 on). The model returns structured tool calls (probe: ALL
> STRUCTURED AND CORRECT; 158 node calls). Flag on: 4 set-asides, 38 boundaries
> where nothing could leave, router blind drops 24 calls / 117 messages / ~83k
> tokens. CAUSE: on 8k the PROTECTED blocks alone exceed the shrink limit (3,072
> tokens) - the tools schema (p95 5,968 tokens), the system prompt, and the step
> message's RESULTS OF EARLIER STEPS (24,000-char clip). Offloading tool results
> cannot fix that. (b) model-initiated edits: 0 set_aside, 0 expand by the model.
> -> OWNER DIRECTION 2026-11-15 (MCM pin_b17a0497b192): a Jupyter-style persistent
> Python workspace as the DAG's main execution backend, folded into this spec
> (fewer, richer calls; large values stay in the workspace namespace). Design by
> the Fable 5.2 advisor, then a new requirement + wave below.
- [ ] **TG-2 (live gate)**: `scripts/validate_view_replay.py` distributions sane ->
  cohort A/B: blind drops 0, context group result recorded, coding/research/memory
  pass counts not lower, standards no regression, BT-1 passes. Then the flag goes on,
  or the reason it stays off is written here with the number and date. On pass:
  crystallize a landmark.

## Wave 3 - Pins with provenance (independent of Wave 2 after T1.2)

- [ ] **T3.1** (CLM-3 AC1): summary -> `PinStore.add` with author = model and source
  links. Check `LINK_VOCABULARY` before adding a relationship.
  DONE = a live summary produces one pin with >= 1 resolving source link.
  NOT THIS = a second pin surface; the raw-INSERT swarm writers.
- [ ] **T3.2** (CLM-3 AC2-AC4; CT-10): render as distinguishable reference data; never
  in the instruction block; never promotes.
  DONE = CT-10 passes; promotions from pins over the cohort = 0.
- [ ] **T3.3** (CLM-3 AC5, CLM-6 AC3): pin audit returns the source set and whether
  each resolves.
  DONE = the audit of a pin with one pruned source reports it.
  NOT THIS = a scheduled auditor.

## Wave 4 - Zones, ledger, re-stretch

- [ ] **T4.1** (CLM-5 AC1, AC2): zones and open-item carry-forward.
  DONE = open items lost = 0 over a 10-turn replay.
- [ ] **T4.2** (CLM-5 AC3): the dead-end ledger block from existing `DEAD_END` events.
  DONE = repeated dead-end actions before/after on the same cohort, reported.
  NOT THIS = a ledger table.
- [ ] **T4.3** (CLM-5 AC4; BT-4): the three re-stretch triggers.
  DONE = BT-4 passes; trigger fired / should-have-fired counted on the context group.
  NOT THIS = a model call to decide a trigger.
- [ ] **T4.4** (CLM-5 AC6, AC7): the landmark header (fixed size, stale flagged) and
  L1 thread placeholders.
  DONE = a live cross-thread question shows an L1 placeholder expanded; S2
  (`test_answer_path_standards`) passes.
  NOT THIS = a new index without running S2 first.
- [ ] **TG-4 (live gate)**: as TG-2, plus the Wave 4 counters.

## Wave 5 - The rubber-band measurement (completion)

- [ ] **T5.1** (CLM-7 AC2): time-frame and domain recall tasks; the bar is set from
  the first measured run and written here.
- [ ] **T5.2** (CLM-7 AC3, CLM-8 AC4): one report script for the counter set.
- [ ] **T5.3** (CLM-10 AC1, AC3, AC4): prefix stability check (a volatile value in the
  prefix is a finding) and re-processed tokens, edit vs append, per backend that
  reports it.
- [ ] **TG-5**: the full gate; standards rows added to PROGRESS; landmark crystallized.

## Wave 6 - DCP removal (after TG-2; small)

- [x] **T6.1 DONE 2026-11-16** - DCP removed: backend/agent/dcp.py and the
  mcm_protocol dcp_prune action deleted; the dcp_prune step left pre_call_flow.json (it
  ran on every direct call and changed nothing in 42 measured runs); DCPConfig and the
  mcm_core.json "dcp" block removed; the swarm MCM:999 code removed (handler, constant,
  pattern, rule text) - swarm context is the later multi-agent view spec. Tests: the
  two DCP-only tests (test_dcp_fan_trace, test_layers_share_resource) removed from both
  copies of test_der_phase0.py; tests/behavioral/test_subloop_footprint_survives_pruning.py
  keeps its subject with a plain history truncation as the pruner, its first test
  renamed test_footprint_survives_history_pruning. No dcp import left in backend/.
  Original task:
- [x] **T6.1** (CLM-9): migrate or remove the two DCP callers; delete `dcp.py` and its
  tests; state each removed test in the commit.
  Also (Q1): remove the `dcp_prune` step from `mcm_protocol/workflows/pre_call_flow.json`; that
  workflow runs on the live direct path, so DCP is not only a swarm path (requirements U1 is too narrow).
  DONE = `grep -r "dcp" backend --include=*.py` shows no import; CT-7 passes.
  NOT THIS = a compatibility shim.

## Wave 7 - The Workbench (CLM-11; owner direction 2026-11-15, advisor design)

Flag `IRIS_WORKBENCH` (off = the fine-grained node path byte-equal, proven by the
parity harnesses). Order is the priority; T7.0 decides whether to proceed.

- [x] **T7.0 baseline - PASSED 2026-11-15, proceed.** The cloud gate's node calls
  (both arms, logs/iris.log 11:58-13:44; 108 nodes, 219 node tool calls): READ-class
  146 (67 %), run_command 34 (16 %) -> READ+RUN 82 % (bar >= ~30 %); 61 % of all node
  calls sit in runs of >= 3 consecutive READ/RUN calls (what one script absorbs);
  calls per node median 1, p90 4, max 11. Interpreter start, warm: system python
  111-122 ms, .venv python 101-103 ms -> lazy start (no pre-warm); cold start (after a
  reboot, hard disk C:) not measured yet - measure at TG-7.
  Original task text: From the recorded runs (cohort coding 8,
  context x01-x04): share of node model calls that follow READ-class or run_command
  calls; calls per node; steps per plan; interpreter spawn time cold and warm.
  DONE = the table here; proceed only if the share is >= ~30 %.
  NOT THIS = any code in backend/.
> **Memory (owner concern 2026-11-16: no memory spike in the app; efficiency).**
> Measured with the T7.1 client, .venv python, the WHOLE process tree (on Windows a
> venv python.exe is a launcher that starts the real interpreter as a child, so the
> launcher's own RSS - 4.4 MB - hides the worker): the IRIS app process 74.3 -> 74.5
> MB when a workbench starts (the workbench lives OUTSIDE the app process); worker
> idle 32 MB; the whole x01 task as ONE script (read 14 logs, 103 KB, count error
> codes) 34 MB and 4 ms - the fine-grained path needs ~10 model calls for it; a 200
> MB value -> 234 MB, back to 33 MB after `del`; close 0.1 s, no process left.
> DECISIONS: (1) the per-workbench cap drops from 1 GB to 512 MB and the
> process-wide budget is 768 MB across live workbenches (oldest idle ends first); (2)
> the digest tells the Brain the workbench size once it passes 256 MB ("holds N MB;
> del what you no longer need") - the Brain manages its memory, the cap is the
> safety net; (3) launch the base interpreter directly (sys._base_executable of the
> resolved venv) to drop the launcher process. Small-model run with the two CLM
> budget fixes (T7.6 + menu budget), offload on: context 1/5 (x01 passes; was 0/5),
> blind-drop calls 21 (was 24) - evals/results/20261115-165745.json.
- [x] **T7.1** `protocol.py` + `worker.py` + `client.py` - DONE 0e806270 (24 contract tests).
  DONE = contract tests pass and fail on a seeded frame change; soft stop keeps state;
  hard kill changes the incarnation. NOT THIS = async, rich MIME output, tool callbacks
  from inside Python.
- **Wave 7, Round 4 tasks (2026-11-16, CURRENT; design.md "Round 4"):**
  > Re-run after F1-F4 (5778022e), stopped after 2 of 5 rounds for Round 4: off 10/10, on 7/10;
  > calls 135 vs 188; prompt tokens 1.14 M vs 1.07 M; completion 65 k vs 84 k; escalations 2
  > in 18 code nodes (was 19 in 26 - F4 works). Failures: x01 check passed on empty
  > placeholders, x02 per-file plan left a step unresolved, x03 E_PLANNER_EMPTY.
  > evals/results/20261116-{113241,115350,121223,123037}.json.
  - [ ] **W0 measurement**: call_kind + HTTP sends on baseline rows; planner raw head logged on
    a None parse; `_wb_stats` wb_wait_s / scripts / exploring; analysis script in evals/.
  - [ ] **W1**: D1 (effort low, ground + inline skeleton in the repair), D7 (claim before the
    clock), D2 (log + quote rule; parser fix from the logged cause).
  - [ ] **W2**: D3 ground function + tests, D6 diet, D8 spill outputs only.
  - [ ] **W3**: D3 wiring (node, planner, repair), D4 plan shape + entry rule, D5 result
    manifest - flag-off parity suites must stay byte-equal.
  - [ ] **TG-7 v2 cloud** (A0/A1, all cohorts, >= 5 rounds) against the pass bar.
  - [ ] **W4**: T7.0b on both small models (level 0 vs 1, with ground; one fenced-code
    variant), then TG-7 v2 small (B0/B1).
- **Wave 7, Round 3 tasks (2026-11-16; the order is the priority):**
  - [x] **T7.11 scope** - DONE d4353926 (8 contract tests; personal workbench refuses the IRIS repo, case workbench_scope; a mode change ends the workbench). One profile; run_python out of `_TERMINAL_TOOLS`; a personal
    workbench refuses a workdir at or under the IRIS repo. DONE = contract tests: a
    personal workbench refuses that workdir and a write into the IRIS repo; developer
    mode unchanged. NOT THIS = a Job Object, network rules.
  - [x] **T7.9 callbacks** - DONE (18 contract tests; no-op callback round trip median 0.085-0.104 ms over 50; each callback = one calls[] entry via run_python and one card count; run_python dispatch deadline 90 -> 630 s, guard test_step_deadline_exceeds_the_longest_python_script). (protocol v2 `ev:call` / `op:result` through the node's
    `_execute`). DONE = a callback reaches box.dispatch, appears in calls[], holds the
    browser claim, the budget error keeps state; no-op overhead < 5 ms. NOT THIS = a
    second dispatcher, an async worker, nested exec.
  - [x] **T7.12 check + auto-close + role** - BUILT (14 contract tests: a passing check closes the node with one model call; the code-mode node counts toward the task card). Live part of DONE runs at TG-7. `check` in exec (worker evaluates); code
    nodes on `tool_execution`; brief rendering in the step message. DONE = a node
    closes on a passing check with one model call, live. NOT THIS = a model call to
    judge the check.
  - [x] **T7.13 planner brief fields** - BUILT 61415764 (8 contract tests; flag-off planner prompt byte-equal). Live part (cohort 21/21 with the fields) runs at TG-7. (inputs, outputs, check, approach, tools) in
    the existing planner call. DONE = cloud cohort 21/21 with the fields present; a
    step without them still runs. NOT THIS = a second planner call.
  - [x] **T7.14 escalation hook** - PROVEN (test drives the real _der_run_node: roles tool_execution, tool_execution, reasoning x1, tool_execution; skeleton in the namespace; log line "escalated to the Brain after 2 failed checks"; 10 failing scripts -> still one Brain call, the node ends at max_calls and goes to DER recovery; _hand_over cannot fire in a code node, helper_role None). `on_check_failed` -> one Brain repair brief with a
    skeleton. DONE = a seeded failing step shows two attempts, one Brain call, a third
    attempt, in the log. NOT THIS = role hand-over; an unbounded loop.
  - [ ] **T7.0b probe** (needs T7.12): ten brief-to-script tasks with checks on each
    small model, level 0 and level 1. DONE = a pass-rate table here; the default start
    level written from it. NOT THIS = a per-model prompt.
  - [x] **T7.10 fresh / close / spill** - BUILT (16 contract tests: a wb: ref expands to its spilled text after fresh, close, idle end and cap eviction; hard kill -> workbench_gone; spill rows wbspill-<inc>-<name>, 32,000 chars each, newest 24 named values; spill and close run OUTSIDE the manager lock). T7.8 with it: keep()/kept removed; one code row per run_python execution on the tool_results lane. Live part at TG-7.
  - [x] **T7.15 `repair_route`** - BUILT, shadow (14 contract tests with T7.14; pattern = page_shadow.py; job judge_repair; label REPAIR = the next check passed with no Brain brief between, ESCALATE = passed after a brief, unlabelled = no pass; read the bar PER ATTEMPT - the rule escalates at attempt 2, so REPAIR labels come only from attempt-1 rows). Rows on a live task at TG-7. Oracle shadow rows. DONE = rows with labels. NOT THIS
    = enforcement.
  > **TG-7 cloud arm, first run (2026-11-16 08:36-10:40, commit 6386f9f5).** deepseek-v4.1-flash
  > on both roles, developer mode, `--group context`, IRIS_WORKBENCH 0 vs 1 INTERLEAVED x3 (15
  > task-runs per arm), IRIS_CLM_BASELINE=1 for per-call usage. Results evals/results/20261116-
  > {085457,091853,093524,100112,101735,104040}.json; analysis scratch wb_ab/analyze.py.
  > | | off | on |
  > |---|---|---|
  > | pass | 14/15 | 11/15 (x01 1/3, x02 1/3) |
  > | model calls (total / median per task) | 230 / 15 | 284 / 17 |
  > | prompt tokens total | 1,912,672 | 1,487,855 (-22 %) |
  > | completion tokens total | 100,870 | 155,500 (+54 %) |
  > | max prompt tokens of any call | 53,079 | 28,183 (-47 %) |
  > | reply_s median | 124.0 | 178.4 |
  > | code nodes / fallbacks / escalations | - | 26 / 0 / 19 |
  > Per task (median): x01 calls 17 -> 9, prompt tokens 240k -> 41k (-83 %), reply 140 -> 120 s,
  > but 2/3 fail; x03 equal; x04 calls 15 -> 37, reply 89 -> 439 s (4-5 escalations per run);
  > x05 runs no code node (control: reply 274 vs 342 s = the run-to-run noise). repair_route rows
  > live: 46 raw / 30 distinct, labelled (16 correct, 14 wrong). Task card events (task:progress
  > per step) equal in both arms. CAUSES FOUND: F1 - a passing check closes the step with the
  > purpose line + the digest's 80-char previews, so the output VALUES never reach synthesis (x01
  > and x02 replies say "truncated"; the namespace held the right answer). F2 - the callback
  > dispatch slot is per conversation, so parallel code nodes overwrite / clear each other's
  > handler ("ToolError: tools are not available here" in x04). F3 - the shadow-row sink keeps
  > only the decision block: attempt / error_type / check_error never reach the store (no replay).
  > Verdict: the flag stays OFF until F1-F2 are fixed and this arm is re-run.
  - [ ] **TG-7 (Round 3), four arms, same conditions:** small tool model (LFM3-1.7B,
    then LFM2.5-2.6B) ReAct vs the loop; cloud model on both roles ReAct vs the loop.
    Per arm: --group context and cohort pass counts; model calls per step by role;
    Brain calls per reply; escalation rate and the level at which steps pass; max
    prompt tokens of any tool-model call; router blind drops; reply_s medians; steps
    where the check passed but the verifier failed; wb_degraded. Proof: small arm
    above 1/5 with blind drops 0 and every call inside the window; cloud arm 21/21 and
    5/5 with fewer model calls per step. Then the flag goes on, or the reason it stays
    off is written here with the number and date.
  - Superseded by Round 3: Round 2's personal profile / Job Object (T7.11 old), the
    tool_choice shadow rows from callbacks (T7.13 old), "every node a code node on the
    Brain" (T7.12 old), the tool model as fallback.
- **Wave 7, Round 2 tasks (2026-11-16; superseded by Round 3 where they differ):**
  - [ ] **T7.8** remove keep(); record a code row per submission. DONE = no `kept`
    in a frame; one code row per execution live. NOT THIS = a new table.
  - [ ] **T7.9** protocol v2 callbacks. DONE = contract tests: a callback reaches
    box.dispatch, appears in calls[], holds the browser claim, the budget error keeps
    state; no-op callback overhead measured (target < 5 ms). NOT THIS = an async
    worker, nested exec, a second dispatcher.
  - [ ] **T7.10** `fresh` / `close` and the spill. DONE = a dead ref expands to its
    spilled text. NOT THIS = pickle snapshots.
  - [ ] **T7.11** profiles + Job Object; run_python out of `_TERMINAL_TOOLS`. DONE =
    personal-profile tests refuse each listed event and a child process. NOT THIS =
    AppContainer.
  - [ ] **T7.12** every node a code node; interpreter order (bundled Python for the
    installed app). DONE = flag-off parity byte-equal; flag-on cohort uses code
    nodes. NOT THIS = a planner prompt change.
  - [ ] **T7.13** tool_choice shadow rows from callbacks. DONE = rows written with
    labels. NOT THIS = enforcement in code nodes.
  - [ ] **TG-7 (Round 2)**, flag off vs on, same conditions: cohort 21/21 and context
    5/5; model calls per step and per reply; prompt tokens per call; reply_s medians;
    wb_fallback rate; app process RSS flat and the tree peak under the caps;
    tool_results rows per conversation; orphan processes 0; one personal-mode run.
  - Superseded by Round 2: T7.5 keep()/promotable, T7.7 exec_mode, the code-mode entry
    rule of T7.4 (every node becomes a code node; the rule's tests stay as the
    fallback guard until T7.12).
- [ ] **T7.2** `manager.py` + `run_python` registration + the bridge handler.
  DONE = a live developer turn runs one script; personal mode does not list the tool;
  no orphan process after close. NOT THIS = a pool, a config surface.
- [ ] **T7.3** `digest.py` + `wb` refs + expand/inspect.
  DONE = offload-gate tests pass with a `wb` ref; `workbench_gone` test passes; code
  records keep the code (calls[].args keeps only _ID_KEYS today - check).
  NOT THIS = snapshots, pickling.
- [ ] **T7.4** code mode in `_der_run_node` + the node claim + fallback.
  DONE = flag-off parity byte-equal; flag-on x01-x04 run code nodes; wb_fallback counted.
  NOT THIS = a planner prompt change; run_python in the fine-grained menu.
- [ ] **T7.5** `policy.py` + `keep()`. DONE = one live pin with a resolving link;
  refusals counted. NOT THIS = automatic promotion.
- [ ] **T7.6** the step-message clips (task 8,000, prior 24,000 chars) scale with
  `ctx.window`. DONE = no protected-block overflow on 8k in a replay.
- [ ] **T7.7** Oracle `exec_mode` shadow rows. DONE = rows written with labels.
  NOT THIS = enforcement.
- [ ] **TG-7 (live gate)**, flag off vs on, same conditions: cloud cohort 21/21 and
  context 5/5 with model calls per code node, prompt tokens per call, reply_s medians;
  small model (LFM3 as tool_execution): `--group context` pass count against 0/5,
  router blind drops against 24 calls, max prompt tokens within the window; plus
  wb_fallback, tool_results rows per conversation, orphan processes = 0. Note: code
  nodes run on the Brain, so a small-model pass shows the harness works WITH a small
  tool model, not that the small model writes code - report its call counts beside it.

Owner questions (asked 2026-11-15; working answers = the advisor's recommendations
until the owner says otherwise): (1) interpreter in the installed app = the project's
or PATH python, unavailable when none (alternative: bundle an embeddable Python);
(2) lifetime = the conversation with a 10-minute idle end (alternative: the turn);
(3) code nodes always on the Brain this wave (revisit with exec_mode data).

## Dependency / parallelization notes

- Wave 0 blocks everything. Wave 1 blocks 2, 3, 4. Wave 3 may run beside Wave 2.
  Wave 4 needs Wave 2. Wave 5 needs 1-4. Wave 6 needs TG-2.
- Only T1.1, T1.3, T1.4, T2.3, T2.6 touch kernel call sites (T1.3 also `node_executor.py`); no two of them run at the
  same time, and none runs during a kernel move commit (blueprint rule R9).
- Do NOT touch: the chunk codec, the two planes, the decay law, recall scoring.
- Multi-agent views are a later spec.

## Coverage matrix

| REQ | Tasks | Tests / verification |
|---|---|---|
| CLM-0 | T0.1-T0.3 | baseline file |
| CLM-1 | T1.1-T1.3, T2.5 | CT-1, TG-1 |
| CLM-2 | T1.5, T2.1-T2.4 | CT-2, CT-3, BT-1, BT-3 |
| CLM-3 | T3.1-T3.3 | CT-10 |
| CLM-4 | T1.4, T2.6 | CT-9, CT-6, live error |
| CLM-5 | T2.3, T4.1-T4.4 | BT-2, BT-4 |
| CLM-6 | T2.6, T3.3 | CT-2, CT-8, CT-10 |
| CLM-7 | T2.7, T5.1, T5.2 | `--group context`, gates |
| CLM-8 | T1.5, T2.5, T5.2 | CT-4 |
| CLM-9 | T6.1 | CT-7 |
| CLM-10 | T2.3, T5.3 | T5.3 report |

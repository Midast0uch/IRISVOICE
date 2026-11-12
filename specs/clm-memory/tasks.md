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

- [ ] **T1.1** (CLM-1 AC1-AC3, AC6): `context_view.py` with `Ref`, `Block`,
  `ContextView.admit/render`; route `_assemble_direct_context` through it.
  DONE = CT-1 passes on recorded inputs (byte-equal) and fails when one block is
  reordered.
  NOT THIS = zones, policy, placeholders, a base class, a plugin point.
  RIPPLE: `_sanitize_messages` order; `_mcm_orch.pre_call` (`_assemble_direct_context`, last lines) still runs
  after AND mutates the list (`pre_call_flow.json`: `dcp_prune`, `mito_inject` at `[1]`, `pacman_recall` at
  `[2]`): CT-1's "old builder" output is assemble + pre_call, recorded after pre_call (Q1).
- [ ] **T1.2** (CLM-1 AC2): references on blocks. Chunk ids via T0.2/Q2; chain,
  episode, thread, pin ids from their rows; `ephemeral` for system and user turn.
  DONE = on the T0.1 cohort replay, 100 % of non-ephemeral blocks resolve to a row.
  NOT THIS = changing recall scoring or its return order.
  Q2 answer: the `with_meta` dict lacks `id`; add `"id": cid` (`episodic.py:1616-1625`).
  RIPPLE: every caller of `retrieve_context_chunks` (kernel x6, `tool_bridge.py:552`,
  `evidence.py:225`, `recall_decoder.py:436`, `research_memory.py:482`) keeps its current return shape.
- [ ] **T1.3** (CLM-1): the DER node list and synthesis through the view (points from Q1).
  DONE = CT-1 covers node and synthesis inputs; BT-W10-2 and the synthesis diet
  contract pass.
  NOT THIS = touching the planner prompt.
  RIPPLE (Q1): the node list is built in `backend/agent/node_executor.py` `run_node` (`:648`), not in
  the kernel, so this task edits that file (call sites only); `_der_bound_step_context` is not a
  pressure site (it cuts a field no prompt reads) and is left alone; synthesis is one user message
  (`kernel/der/report.py:1450`), not a list.
- [ ] **T1.4** (CLM-4 AC1, AC2, AC5; CT-9): `context_gauge.py`; move the router
  estimator into it; delete `_count_tokens` and `_DIRECT_CTX_BUDGET`; `observe()` from
  the router after each call.
  DONE = CT-9 passes; live error |median| <= 5 % and |p95| <= 20 % per calibrated (provider, model) (THE BAR above) on the
  cohort, reported beside the T0.1 "before".
  NOT THIS = loading a tokenizer; persisting calibration; a per-provider class.
  RIPPLE: ContextPill value source (CT-6; T29 / parity tests - state any input change).
- [ ] **T1.5** (CLM-2 AC6, CLM-8 AC3): the router cap reports each drop to the view
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
- [ ] **TG-1 (live gate)**: same cohort, parity commit vs baseline: pass counts equal,
  `reply_s` within the standards' tolerance, `view_fallback` = 0.

## Wave 2 - Offload, placeholder, re-expand (the first behavior change)

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

- [ ] **T6.1** (CLM-9): migrate or remove the two DCP callers; delete `dcp.py` and its
  tests; state each removed test in the commit.
  Also (Q1): remove the `dcp_prune` step from `mcm_protocol/workflows/pre_call_flow.json`; that
  workflow runs on the live direct path, so DCP is not only a swarm path (requirements U1 is too narrow).
  DONE = `grep -r "dcp" backend --include=*.py` shows no import; CT-7 passes.
  NOT THIS = a compatibility shim.

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

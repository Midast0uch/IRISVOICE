# Execution audit — progress log

## START HERE (next session)

**Foundations (2026-09-30):** the roadmap is `.mcm/GOALS.md` (the old `bootstrap/GOALS.md` is
archived there); CLAUDE.md/AGENTS.md now carry "BUILD + VERIFY IRIS — THE MEASURED LOOP" and
"READING THIS CODEBASE — PHASE MODEL, PHYSICS, LANES"; validate every change with the
`app-testing` skill, Mode A (`.opencode/skills/app-testing/SKILL.md`) — MCM `pin_6c81e87956b8`.

**NEXT AGENT: read MCM `pin_21357eeec9fc` (HANDOFF 8) FIRST** - it supersedes HANDOFF 7's order
of work: Brain calls cut (S19), turn-end bookkeeping off the reply path (S20), the local TOOL MODEL
now runs node calls with a Brain helper, node/step audit fixes, new providers (OpenRouter, Inception
Labs, NVIDIA), startup findings (owner actions: Defender exclusions + D: NVMe). Open, in order:
idempotency/DUPLICATE write_file on c04, work after the reply ([AMEND]), full eval C + standard.

**Earlier the same session (2026-10-01 evening, session e5b83fff): log "2026-10-01 (session e5b83fff)" below** -
HANDOFF 7 C1 (brake at every boundary, idle arm shadow, S18) and C9 (dead failure-warning path
removed) DONE, coding 15/15, reply sum 278 s. Then (same session): Brain calls per task cut
(S19), C5 turn-end bookkeeping off the reply path (S20), node-ripple chokepoint `_step_calls`,
skills must recur. NEXT: eval B (tool model runs every node call), eval C (Brain helper), then one
engine in both modes (owner rule: developer mode = self-modification only), step size, the hung
cloud call (see the log entry).

**NEXT AGENT: read MCM `pin_e62617d22e5a` (HANDOFF 7) FIRST.** The Oracle work is done and
PAUSED (owner); go back to the audit items - HANDOFF 7 sections C (everything carried over from
HANDOFF 6/5, with status), D (new open items) and F (suggested order).

**Previous (2026-10-01, session f2fd8db3): the log section "2026-10-01 (session
f2fd8db3)" below** - measured answer-path fixes (coding reply sum 1385 s -> 461 s, 15/15),
Sigma physics REVERTED (K4 live guard failed), Oracle JOBS (oracle.md §19), Oracle phase domain
live gate. Then HANDOFF 6 for the older context.

**Previous (2026-10-01): read MCM `pin_522fe69c7e61` (HANDOFF 6) FIRST.** It lists
what session 64237209 built (store 6.6 -> 0.28 GB, S12; one Chromium + click-safety browser; research
memory; relevance-gated Immortus chain; meaningful Sigma - LIVE GUARD PENDING; event taxonomy v1 +
emitters + Oracle shadow consumers; Oracle phase domain behind `IRIS_ORACLE_PHASE`, default off) and
what is left. Owner priority: the AUDIT work items below come first; then the live gates in HANDOFF 6.
Nothing after `3d9d802f` is pushed.

**Previous: read MCM `pin_57d2554decaf` (HANDOFF 5).** Research
Wave A is done and measured (research 7/8, r01 154 s -> 44 s); the owner APPROVED three follow-ups
(extractor off the answer path, test changes that improve the feature, store cleanup of 4.84 GB
with a no-regrowth guard); then spec Wave B (real browser control,
`specs/websearch-vision-browser/`). Details: the session 13a261c7 log below.

**Previous handoff: read MCM `pin_069f18710552` (HANDOFF 4) first, then its ADDENDUM `pin_d4b9bd81e9f5`
and the owner notes `pin_7484ace0deee` (`bootstrap/coordinates.db` is unused and
`bootstrap/GOALS.md` is STALE — this folder's PROGRESS/README are the roadmap of record) and
CORRECTION `pin_f1cb33f20a88`: `data/memory.db` stays the PRIMARY app store
(`memory_config.json` reverted; `D:\IRIS\data\memory.db` is an unused leftover — never delete the
C: store).** (The disk move
was executed 2026-09-30 — see `disk-move-execution-report.md`; the site-packages SWITCH and the
reboot measurements are still the owner's; tooling scripts now resolve the store via
`scripts/_app_store.py`; new item D5: the per-launch `__pycache__` purge). Then: verify the
move + Standard S9, address `pin_22b078571d73`, then the remaining audit items.

Read in this order: this section -> MCM pins `pin_069f18710552` (HANDOFF 4), `pin_8c65c2f38078` (HANDOFF 3),
`pin_01a6c7f883b5` (STANDARDS — check before touching these paths), `pin_c8d898bc13c3`
(latency pattern), `pin_fe189f29c30b` (physics lane), `pin_4de2bce61834` (EML root cause) ->
the log below ->
`README.md` (owner decisions) -> `execution-audit.html` / `reply-surface.html` for design detail.
Older handoffs: `pin_afa4442771d1` (HANDOFF 2), `pin_dc96cc9c9681` (superseded).

**Where it stands (2026-09-29 late).** Phase 0 + Phase 1 blockers done; Phase 2 core live.
**Coding eval 15/15** (`evals/results/20260929-223059.json`; baseline 0/15). c10 was fixed by giving
each node the user's request word for word (`NodeContext.task`). Answer-path latency work since
then (see the log): per-step physics on its own ordered lane with fold-back at shape decisions,
two missing indexes on the 6.3 GB `data/memory.db`, and one ordered ledger writer lane. c10 reply
now arrives at **16.9 s** (was 63-226 s). Research group (1/6 baseline) not re-run.

**Update 2026-09-30.** TTS cold start DONE (commit `19f8a6cb`, Standards S7): loads with the
backend, `/health` 503 until ready, warm-up sentence, no idle unload, concurrent-spawn hang and
`set_voice` local-shadow fixed, git-status disk hog fixed (S8). ROOT CAUSE of every cold number:
**C: is a 97%-full 7200 rpm hard disk** (D: is an empty NVMe SSD) — cold 110 s vs warm 5.1 s for
the same imports. Owner chose "plan a move to D:": `disk-move-plan.md` (owner-run). Open decisions:
MCM `pin_22b078571d73` (topology halt; 7.5 min index build).

**Next work, in order** (each with DONE / NOT THIS per CLAUDE.md):
1. DONE 2026-09-30: standard recorded from a full coding run, **15/15**, group wall time
   ~36 min -> 18 min, replies 14-145 s (median ~50 s; c11 53 s, c10 16 s, c07 20 s) —
   `evals/results/20260930-065124.json` -> `evals/standards.json`. Re-record after the owner runs
   `disk-move-plan.md` (expect lower cold numbers).
2. **Oracle takes decisions** (owner rule, memory `iris-oracle-takes-decisions`). First target
   MEASURED AND DROPPED 2026-09-30: skipping the continuation consult's Brain call under COMPRESS
   saves ~0.8 s/turn (423 prompt / 6 completion tokens) but leaves the `done` rows without their
   Brain reference label (unpaired rows are unscorable — the Session 366 starvation).
   Bar report 2026-09-30 (`scripts/consumer_enforcement_report.py`, active engine
   gliner25-decide-onnx-int8): NOTHING enforced by the bar. Closest: `tool_choice` precision 1.0
   at t=0.4 (22 rows above), AUROC 0.79, gap = ECE 0.107 > 0.05 (calibration only);
   `presentation` precision 1.0 but ECE 0.565, one class; `done` 99 rows but precision 0.729;
   `mode` 0.725, `escalate_incomplete` 0.728; `depth_met`/`depth_route` have no threshold for the
   active engine. BLOCKER FIXED 2026-10-01: `scripts/calibrate_decision_threshold.py` scored a
   SHADOW row by its event outcome (the outcome of the Brain's pick), so web_intent read acc 1.0
   in every band vs parity precision 0.377. Now ONE rule, `decision_label()` in the calibrate
   script, used by both instruments (shadow = parity with `brain_choice`/`brain_bool`, no
   reference = skipped and counted; dispatched = outcome). Guard:
   `unit/test_calibrate_decision_threshold.py::TestOneLabelRule` (fails on the old script).
   Live store after the fix, active engine, both instruments identical: `tool_choice` 401 rows,
   ECE 0.059 (bar 0.05), 22 above threshold; `web_intent` 1138 rows, precision 0.381, ECE 0.49
   (conf < 0.5 agrees 97%, 0.5-0.6 agrees 4% — confidence is anti-calibrated there).
   Next: fit calibration for `tool_choice`. Then a per-turn breakdown of Brain calls by caller
   to find decisions worth moving. Pre-existing: `test_missing_db_unverified` fails
   (`from _app_store import` in `main()` needs `scripts/` on `sys.path`).
3. Turn-end bookkeeping before synthesis (`_save_card_footprint`, `mycelium_record_plan_stats`,
   `_store_task_episode` + crystallize, `_maybe_trigger_skill_creation`, agent_kernel ~10600-10745)
   -> an ordered lane; fold-back at the next turn's recall if recall must see it.
4. Remove the TEMP `IRIS_STACK_DUMP_S` hook in `start-backend.py` once timing work ends.
5. Reply surface Phase A (`reply-surface.html`, "Order of work" A): one `create_artifact(title,
   kind, summary, content, language?, artifact_id?)` tool built from
   `tool_bridge._execute_render_document` + `agent_kernel._store_document_data` + the existing
   `DOCUMENT_RENDER` event; remove markdown demotion (`agent_kernel` ~4874,
   `artifact_policy.is_artifact_document`), fallback mint (`_mint_artifact_card`), the web-format
   question (`_maybe_escalate_web_format`); rewrite the `[RESPONSE FORMAT]` prompt block; `show`
   JSON converts to the same event; Oracle `presentation` stays shadow-only. Pinned tests:
   `contract/test_structured_response.py`, `contract/test_document_render_contract.py`,
   `contract/test_render_as_tool.py`, `contract/test_surface_observer_contract.py`,
   `behavioral/test_reply_surface_behavior.py` (run behavioral tests with a time cap).
6. Phase 2 rest: `plan_update` tool, tool-model argument repair, personal-mode research through
   `run_node` with web-family policies. Then Phase 3 (turn protocol + turn store), the live
   execution matrix (`app/cli-preview`), reply surface B-D.
7. Owner decisions pending — facts, options and recommendations in MCM `pin_22b078571d73`:
   (a) `TopologyViolationException` never halted the loop (always swallowed); rec==3 fired in
   0 of 1,048 trajectory rows. Recommendation: make the halt live at the fold-back, low priority.
   (b) `idx_memory_chain_created` took ~7.5 min to build, blocking startup. The store is 6.61 GB
   with only 0.23 GB free pages; `memory_chain` is small, so the cost is cold random reads across
   the file (cause under investigation, ~5 GB not yet attributed). Recommendation: build indexes
   off the startup path now; decide VACUUM / BLOB relocation after an offline size breakdown.
   (c) planning is one Brain call of 13-19 s per turn (model time).
8. Smaller open items: native `calculate_eml` still hits 1-6 s outliers (2 MB page cache per
   native connection); `[AgentKernel] _get_failure_warnings failed (AttributeError)` every turn
   (ResolutionEncoder path, pre-existing) - DONE 2026-10-01: dead path removed (owner, C9).

**Standards (measured; do not regress).** Each row is guarded by something that FAILS, proven
to fail on the old state. Change a number only with a new measurement and the reason.

| # | Standard | Before -> after (how measured) | How / why | Guard |
|---|---|---|---|---|
| S1 | per-session `system_events` counts (calculate_eml input) use `idx_system_events_session` | 16-84 s per DER step -> ~1 ms (stack dump + `[EML-DIAG]` probe, c10) | cold 6.3 GB store; SCAN read rows with payload/BLOBs | `contract/test_answer_path_standards.py::test_s1_*` (plan has no `SCAN system_events`) |
| S2 | recall recency order uses `idx_memory_chain_created` | widest scope 119 s cold, turn-start stall 40 s -> 0.000 s (EXPLAIN + timing, c07) | the unindexed sort read every row; `memory_chain` is small (~1.5 MB), so the cost is cold random reads across the 6.6 GB file (corrected 2026-09-30; `pin_22b078571d73`) | `test_s2_*` (no `TEMP B-TREE FOR ORDER BY`) |
| S3 | a step's answer path never waits for its physics; shape decisions fold back on `fold.ready` | reply held 16-106 s -> 0 s on the answer path (stack dump) | physics on `lane("physics")`; only shape decisions call `_der_physics_settle` | `test_s3_*` (finalize returns while the physics is blocked) |
| S4 | ledger rows go through ONE ordered lane, and a blocked row reports itself | ~90 contending threads + "database is locked" -> zero lock errors (stack dump, eval logs) | thread-per-row on one connection fell back to the native writer | `contract/test_ledger_write_watchdog.py` (drives the real lane) |
| S5 | each node sees the user's request word for word | c10 FAIL (rules lost in the paraphrase) -> PASS; coding 12/15 -> 15/15 | planner paraphrase dropped "qty <= 0" rules | coding eval (`evals/standards.json` once recorded) |
| S7 | TTS is ready with the backend; `/health` 503 while TTS loads, 200 + `tts.status=error` on a failed load | c11 reply 213.6 s -> 116.8 s; startup timeouts / zero audio in turns: many -> 0 (eval logs 2026-09-30) | lazy load landed inside turns (5 min 6 s cold on the C: hard disk) and starved pytest; now loads in the lifespan, warm-up before "ready", no idle unload (growth recycle caps memory) | `contract/test_startup_readiness_standards.py::test_s7_*`; hang: `behavioral/test_tts_memory_envelope_behavior.py::test_concurrent_first_speak_spawns_exactly_one_worker` |
| S8 | the git-status poll never runs back to back on a slow repo | ran every 5 s, each run a 5 s timeout -> at most ~10% of disk time | fixed 5 s TTL + 5 s timeout on a huge dirty repo on the hard disk; TTL now x10 the last run's cost | `test_startup_readiness_standards.py::test_s8_*` |
| S10 | the Oracle model hash comes from a cache on a repeat start (`data/oracle_model_hash.json`, keyed by abs path + size + mtime_ns) | ~16 s of `_hash_model_file` frames at startup -> 0; start -> first Oracle decide 23.0 / 38.6 / 70.4 s -> 5.3 s (one run, model file warm) (stack dump + log, 2026-09-30) | `load()` read the 642 MB model twice (ORT session + sha256) on the C: hard disk, competing with the TTS worker load | `contract/test_startup_readiness_standards.py::test_s10_*` (unchanged file is not read again; a changed file is re-hashed) |
| S12 | one `memory_chain` row is bounded (`iris_ffi._CHAIN_RESULT_CAP` = 64 K chars + a `truncated` marker) and stored once (legacy `content` written empty; every reader reads `result`) | `data/memory.db` 6.61 GB -> 0.277 GB (VACUUM, 2026-09-30); 28 rows > 1 MB held 4.83 GB, each byte twice; 84 captured store listings in `document_data` held 1.23 GB | S11 stopped new nested captures; the chain writer still copied any size into both `result` and `content` | `contract/test_answer_path_standards.py::test_s12_*` (legacy-shape store; fails on the old writer); `contract/test_document_data_store.py::test_s12_*` (document chain row is a reference) |
| S13 | a user turn is never "idle": background warm-ups wait for the turn to END | c01 reply 351 s -> 78 s (whisper warm-up held the first pytest 220 s; stack dumps, 2026-10-01) | `IdleTracker.busy()` via `_turn_in_flight` on `process_text_message` (voice, chat AND the dev orchestrator); warm-up waits 90 s + 20 s idle | `contract/test_idle_tracker_turn_busy.py` |
| S14 | a SHADOW Oracle score never holds the reply | per coding run: done 166.7 s, on_track 60.5 s, review_verdict 59.0 s, depth_route 32.7 s inline -> 0 (lane `oracle_shadow`) | `monitor_bool(defer=)`, `Reviewer.set_shadow_sink`, `depth_route(async_=)`, `DecisionEngine.shadow()` for new consumers; `INLINE_DECISION_COUNTS` logged every 100 | `contract/test_monitor_shadow_off_answer_path.py` |
| S15 | Oracle input bounded by its JOB (<= 128 ids) | worst decision 2.3 s -> 0.42 s (`benchmarks/oracle_jobs_bench.py`); live `done` p50 2331 -> 774 ms | `ORACLE_JOBS` + `job_input()` in `decide`; backend cuts text at the budget | `contract/test_oracle_jobs_contract.py` + the bench |
| S16 | the goal-contract push is bounded per fact; a prohibition is not a deliverable | c06 reply 366 s (36 pushes) -> 58 s / 27 s | `GOAL_COVER_PUSH_MAX = 2` then BLOCKED no_progress; `_PROHIBITION_RE` | `contract/test_goal_contract_cover_bound.py` |
| S17 | every transport HTTP client reuses the process TLS context | 14 dumps (~56 s) of one turn in `ssl.create_default_context` -> 0 | `verify=get_ssl_context()` on the Ollama client; sidecar probe pooled + adoption remembered | `contract/test_transport_shared_ssl.py` |
| S18 | the stuck-streak brake decides at EVERY step boundary (not only when the user steers), once per newly settled step; its idle arm is shadow-only | brake reached only with a queued steering record (never in practice) -> every boundary; idle arm live: coding 14/15 (5/15 false fires, c15 replan dropped the fix step, `20261001-194110`) -> idle shadow: 15/15, reply sum 278 s, 6 shadow fires all on passing runs (`20261001-202503`) | gate moved in front of the steering early return; `DirectorQueue.streak_gate_settled`; idle = "fraction unmoved", which reads and a first red test run always are | `contract/test_der_steering_channels.py::test_stuck_streak_brakes_without_any_steering`, `::test_brake_does_not_refire_until_a_new_step_settles` (both fail on the old code); `behavioral/test_envelope_loop_behavior.py::test_bt2_idling_streak_is_shadow_only` |
| S19 | no Brain call whose answer changes nothing; a step closes in its last tool call; node steps are keyed by their calls; <= 2 brake replans per run | 205 Brain calls / 15 coding tasks (60% node loop, ~43 close-only, 16 ignored progress checks, 13 consults discarded under COMPRESS) -> 133 before reply (eval D `20261001-221317`), 29/46 steps closed in the tool call | `step_done`/`step_summary` args on node tools; `_der_check_full_progress` removed; consult skipped under COMPRESS; `_step_digest`; `STREAK_GATE_MAX_FIRES` | `unit/test_node_executor.py` (close-in-tool-answer, step_done), `behavioral/test_envelope_loop_behavior.py` (no consult under COMPRESS, progress check gone, node key, max 2 replans) |
| S20 | turn-end bookkeeping never holds the reply; the next turn folds back before planning | 2-8.5 s per task between run grade and synthesis (stack dumps: `crystallize_landmark -> _auto_connect`) -> 0 on the reply path | one ordered job on `lane("memory_events")` (`_turn_end_submit` / `_turn_end_settle`) | `contract/test_turn_end_off_answer_path.py` |
| S6 | eval pass flags and `reply_s` per task | c10 reply 63-226 s -> 16.9 s | all of the above | `evals/standards.json` + `run_evals.py` STANDARDS check (exit 5 on regression; tolerance x1.5 + 10 s for cloud-model variance). Record with `--record-standard` after a clean full run (pending: after the TTS fix) |

**How to run the evals safely (learned the hard way).**
- Start the backend DETACHED, never with `preview_start` (a Claude crash kills a preview server,
  and vice versa):
  `Start-Process C:\Python314\python.exe -ArgumentList C:\dev\IRISVOICE\start-backend.py -WorkingDirectory C:\dev\IRISVOICE -WindowStyle Hidden -RedirectStandardOutput logs\backend_eval_stdout.log -RedirectStandardError logs\backend_eval_stderr.log`
- Load the tool model (LFM2.5-2.6B on :8082): `python evals/load_tool_model.py` (waits for
  the API, then sends WS `load_local_model`). The Brain is `gemma4:31b-cloud` on Ollama :11434.
- Wait ~75 s after start: the backend freezes up to ~45 s after startup / model load
  (RetentionManager and warm-ups), and the harness preflight needs `/health` within 5 s.
- Start the RUNNER detached too for anything over ~8 min (`Start-Process ... run_evals.py
  --group coding -RedirectStandardOutput logs\eval_coding_stdout.log ...`): a tool timeout that
  kills the runner skips its `finally`, which is how `data/iris_config.json` was left in
  developer mode before.
- Run small subsets: `python evals/run_evals.py --task c01_fix_off_by_one --task c10_create_module`
  or `--group coding` (~35 min now incl. harness gaps). Research tasks take 5-10 min each.
- Read `reply_s` (time until the reply text), not `seconds`: the harness keeps the socket open
  while the reply is SPOKEN, so `seconds` includes speech.
- Use `127.0.0.1`, never `localhost`, for local llama-server ports (+2 s per request here).
- The backend `/health` is on **:8090** (`http://127.0.0.1:8090/health`). A wait loop must also
  stop when the start process exits: `start-backend.py` can kill the stale backend and then
  fail with "port 8090 is still occupied" because it checks before the port is released (a
  second start a few seconds later works).
- NEVER sample the backend from outside (py-spy / `python -m asyncio ps`): it killed the backend
  and Claude Code. For timing, set `IRIS_STACK_DUMP_S=4` before starting the backend and read
  `logs/stackdump.log` (first line `start_epoch`; dump k is at start + 4k s). EXPLAIN QUERY PLAN
  any query on the answer path: a SCAN of a table with big rows is a multi-second stall on a
  cold 6 GB store.
- Targeted test runs only, each with a time cap; `test_mcp_dispatch.py` deletes a tracked
  fixture skill (restore with `git checkout`). `test_der_chain_landing.py` copies the 6 GB store.
- Known pre-existing test failures (not caused by this work): `test_capability_escalation::
  test_t23...`, `test_standing_list::test_edge...`, 3 in `test_decision_engine` (fake backend
  lacks `instruction`), 3 in `test_skill_creator` (wrong fixture path), 5 router tests in
  `test_context_window_negotiation` (fake transport lacks `budget_check`),
  `contract/test_der_t8_all_nodes_contract::test_plan_steps_carry_node_record` (stub lambda
  takes no args), `behavioral/test_der_success_synthesizes::test_success_path_deterministic_fallback...`,
  both `test_mid_loop_injects_failure_warning_and_proven_approach`, plus the stale list in
  `pin_dc96cc9c9681`.

**Owner to-do.** Done 2026-09-29: `data/iris_config.json` is back to `"mode": "personal"` with no
`iris-evals` project. Nothing after commit `b4b62fa4` is committed or pushed.

---

Running log of work after the Phase 1 commit (`a21b641c`). Each entry is also recorded in
MCM (`record_edit` / `record_test` / `pin_add`).

## 2026-10-01 (session e5b83fff) — HANDOFF 7 C1 (brake every boundary) + C9 (dead path removed)

- **C1, owner: the brake runs at every step boundary.** `_der_check_steering` returned before
  `_der_streak_gate` when no steering record was queued, so the T9 brake never ran on a run
  nobody steered. Now the gate runs at every boundary; it decides again only after a new step
  settles (`DirectorQueue.streak_gate_settled`) - otherwise the loop re-enters the boundary right
  after a replan with the same tail and replans once per boundary.
- **Live gate run 1 (`20261001-194110`): 14/15.** Only `idle_streak:2` fired: 5/15 runs, always
  s2+s3 (success, new, matched, verified fraction unmoved). Reads and a first red test run verify
  nothing yet, so normal coding looks "idle". c15's replan produced 2 steps with 0 tool calls and
  dropped the fix -> FAIL. The stuck arm (repeat/empty/mismatch) never fired.
- **Owner: idle arm -> shadow.** The gate logs `SHADOW would fire (idle_streak:N)` and counts
  `idle_shadow`; the stuck, coverage and topology arms stay live. **Run 2 (`20261001-202503`):
  15/15, no regression, reply sum 278 s** (HANDOFF 7: 340 s), 6 shadow fires all on passing runs,
  0 physics fold-back waits >= 0.5 s. Standard S18. Test change (stated): `test_bt2_idling_streak_fires`
  -> `test_bt2_idling_streak_is_shadow_only` (the requirement changed by owner decision).
- **C9, owner: remove.** `_get_failure_warnings` read `_mycelium.conn` (the attribute is `_conn`),
  so it raised every turn. The one-line fix would have been worse: it encodes the CURRENT task as
  the failed "tool" and returns `[outcome:miss | tool:<task text> ...]` for every task and every
  step, after a `LIKE '%<task>%'` scan of `episodes` per step. Removed with both call sites
  (planning prompt keeps `FAILURE WARNINGS: None`, as before). Tests changed (stated): deleted
  `unit/test_failure_warnings.py`; `test_failure_evidence_contract.py` AC24.2 class ->
  `TestFailureWarningsRemoved`; A1 assertion in both copies of `test_der_a1_a2_a3_memory_bridge.py`
  inverted. A real failure lookup could use `episodic.retrieve_failures` (exists) - open item.
- Pre-existing failures found (fail on the committed code too, not in HANDOFF 7 E):
  `contract/test_der_integration_smoke.py::test_integration_full_cycle` and
  `behavioral/test_websearch_without_encoder.py::...test_websearch_full_task_without_encoder`
  (resolver returns tool None), `tests/contract/test_der_trace_contract.py::test_steering_signal_recorded`
  (stub lacks `budget_deadline`), the a1 bridge test (`_Step` lacks `expected_output`).
- C5 mapped (not built): the four turn-end calls run BEFORE synthesis (`agent_kernel` ~10929-11071);
  `_store_task_episode` + `_maybe_trigger_skill_creation` take only immutable args;
  `_save_card_footprint` reads `self._active_card_id` (capture it if moved). The store's lane
  writer is `lane("memory_events")` (`record_task_end` is already submitted there just before the
  episode). A fold-back is needed: the next turn reads episodes in `_build_context` / `_plan_task`.
  Measure which call costs the ~1.2 s before moving any. -> DONE later the same session (S20).
- **Brain calls per task (owner: fewer calls for ALL tasks, not the suite).** Breakdown of
  `20261001-202503`: 205 calls; node loop 122 (N tool calls cost N+1: the node ends only on an
  answer without a tool call), FULL-mode progress check 16 (answer ignored), continuation consult 18
  (13 under COMPRESS, discarded), synthesis 17, planning ~18. Built: close a step through
  `step_done`/`step_summary` tool args (a STATUS line in the tool answer never fired - the model
  leaves the text empty when it calls tools), progress check removed, consult skipped under
  COMPRESS (S19). A2 (`20261001-212212`) exposed a replan storm on c15 (49 calls): node steps had
  ONE repeat key (`params_digest(None, {})`), so with the brake at every boundary any node could read
  as a repeat -> `_step_digest` (node = its calls) + `STREAK_GATE_MAX_FIRES = 2`. A2b
  (`20261001-213633`, 5 tasks): 81 -> 58 calls, Brain time 59.9 -> 48.7 s.
- **Node ripple audit (owner).** Since 2026-09-29 a step is a node loop with many calls and no
  `item.tool`. Graft / sufficiency / recovery seed: no live fault in developer mode (gather-tool
  checks never match a node; nodes have no web tools) - wrong once web tools enter nodes. Seven
  data readers took `item.tool` -> one chokepoint `_step_calls` (see commit `4ba39ae8`). Not moved
  on purpose: envelope `capture_skipped` (a node would read as flat_tire) and verify mode.
  Pre-existing, found on the way: `tests/contract/test_subloop_footprint_contract.py` and
  `tests/behavioral/test_subloop_footprint_survives_pruning.py` fail at the session start too - a
  split child's footprint holds "RESOLVE: ..." instead of the parent's objective (split ripple);
  `behavioral/test_der_phase0.py` x5 fail on committed code.
- **Skills.** With real calls, capture fired on every coding run (5 one-task "skills" named after
  the first tool, overwriting each other; deleted with the owner's approval). Now a shape must recur
  in >= 3 successful similar episodes and is named by the whole shape.
- **Eval D (`20261001-221317`): 15/15**, 133 Brain calls before reply, Brain time 128 s (run 2:
  139 s); reply sum 410 s of which c02 = 129 s: one cloud synthesis call HUNG 120 s (timeout ->
  deterministic reply). Earlier runs had 43 s / 12 s single-call stalls. OPEN: a hung cloud call
  costs the user minutes - measure the stall rate, then bound it (e.g. no first token in N s ->
  cancel + one retry). Reply time without the hang is flat (282 vs 271 s): fewer calls, but node
  prompts grew (closed steps carry tool output) and the ~6 s/task kernel floor did not move.
- **Owner rules recorded** (`pin_7f8931e36169`): developer mode = self-modification only (engine,
  tools, graft/sufficiency/recovery the same in both modes); permissions ask only on destructive
  tools; personal mode gets the "add project folder" toolbar; ChatView redesign in both modes
  (frontend item, not started). Tool model for ALL node calls, Brain helper on struggle
  (`pin_0c6b61417b81`) - evals B and C next.
- Ops: `start-backend.py` waits up to 15 s for the killed backend's port; after a restart only a
  health 200 from the NEW pid counts (the old one answers for a few seconds).
- **2026-10-02 (same session) - local tool model + Brain helper.** Owner: the loaded tool model does
  node calls (`e143f8ce`); four SYSTEM faults it hit were fixed (rate limit only on destructive tools;
  llama-server 500 on the model's malformed tool JSON fed back instead of "Could not connect"; the
  project folder written `.`; thinking off per call). Then: stuck detector (`821d6554`, `a0388d1f`),
  empty answer fed back (`4b198227`), Brain helper once per node when tool != Brain (`6abfc62d`), no
  early close after a change + 2 repeats (`318095aa`), node sees DONE WHEN / parent step / review
  note (`ab58586b`; step/node audit: 1 node per step in all 15 tasks, but the verifier graded a
  criterion the node never saw), .py syntax check on writes (`8d7f3ec9`). Voice: split lines in
  plain words (owner). Providers: OpenRouter, Inception Labs (mercury-2.5), NVIDIA (`e7097371`,
  `e2f22557`, `9cab968d`). Eval C (mercury-2.5 Brain + TwIL-LM3-Pro tool, `20261002-095120`): 11/15;
  re-runs `20261002-101407`, `20261002-103355`: c05/c06 4-8x faster, c08/c12/c13 PASS; c04 still
  FAILS (30 failed writes; 58 DUPLICATE CALL + idempotency cache HITs on write_file - next item).
  Startup measured: cold backend 23 min, frontend 23 min + 404s (poisoned Turbopack cache, fixed by
  clearing .next/dev); git poller fixed (`9cab968d`). MCM `pin_21357eeec9fc` (HANDOFF 8).

## 2026-10-01 (session f2fd8db3) — measured answer path, physics revert, Oracle jobs + phase

Three coding runs, same machine (`evals/results/`): `20261001-104424` (start) reply sum 1385 s
-> `111006` 535 s -> `120004` 461 s (Oracle jobs + `IRIS_ORACLE_PHASE=1`); 15/15 each,
"STANDARDS: no regression" on the last two. Commits: `569e1698` `6bf92d5a` `d16f833c`
`ebeea6ce` `8c9443f5` `fbfea380` `689911e3` (+ this doc). Nothing pushed.

1. **Oracle instruments agree** (`569e1698`): calibrate scored SHADOW rows by event outcome;
   one `decision_label()` now. **Shadow `tool_choice` menu** (`6bf92d5a`): both kernel callers
   passed no candidates, so 278/278 rows scored a vision-only menu (Brain's tool never on it).
   tool_choice rows before `6bf92d5a` are not calibration evidence.
2. **Stalls found by stack dumps** (`d16f833c`): whisper warm-up inside c01 (S13); turn-end
   shadow monitors inline (S14); a new TLS context per Ollama call + sidecar re-probe (S17);
   goal-contract loop on "do not change app.py" (S16); `_current_turn_id` had 13 readers and no
   writer; TTS worker exit code now logged.
3. **K4 guard FAILED -> `adbf69f8` reverted** (`ebeea6ce`, owner rule). `caducean_trajectories`
   eval-c*: before action 0 on 47/47 rows, after action 1 on 98/98 - a coding step is a NODE
   with no tool, so `_physics_action(None)` = COMPRESS always; rec never 1, so the continuation
   gate never suppressed an Explorer step (11 -> 0; Explorer steps 6 -> 55; replies ~2x).
   Before K4 the brake was ALSO a constant (rec ~1). Path back: classify a node step by
   `NodeResult.calls`, replay on node traces, live guard. A real continuation-termination rule
   is still owed (it rides a constant today).
4. **Oracle jobs** (`fbfea380`, `689911e3`; oracle.md §19 has the diagram): latency follows input
   length (30 words 150 ms, 400 words 2.3 s); the backend read ONLY `frame["goal"]`. Now
   `ORACLE_JOBS` (interpret / route / guard / judge_step / judge_goal / shape / classify_event,
   budgets 64-128 ids) and `job_input()` in `decide`; `DecisionEngine.shadow()` is the off-path
   call; criteria versions bumped (`done/v2`, `on_track/v2`, `depth_met/v2`, `depth_route/v2`).
   Per-job bench p50 265-417 ms. Floor: ~117 ms (2 labels, 5 words) - under 150 ms needs a
   smaller model, not a smaller budget.
5. **Oracle phase domain live gate (P4)**: coding run 3 with `IRIS_ORACLE_PHASE=1`: no
   regression, phase_wait p50 0 ms / max 252 ms over 342 decisions. Research run
   `20261001-120656`: 8/8, no regression (r01 44 -> 22 s, r05 48 -> 34 s; r03 19 -> 27 s and
   r04 10 -> 25 s slower - research has no recorded standard yet, record one). P4 PASSED:
   `IRIS_ORACLE_PHASE=1` is now set in `.env` (local, untracked - like `IRIS_PHASE_SCHEDULER`).

6. **Later the same day** (commits `c3484f51`..`eee33b94`): ColBERT placeholder REMOVED (owner);
   Sigma REDONE by node calls (`52e6e851`, `scripts/replay_sigma.py` replays on the native
   engine; landmark `lm_34630e8be75c70ce`); the developer-mode switch no longer runs a 13-17 min
   `git worktree add` of the whole repo (owner: ask before every creation; separate-repo sandbox
   in GOALS 7c); `faulthandler.enable` armed after 3 native crashes in python314.dll at offset
   0x2ab7db (`logs/crash_traceback.log`); classical vs phase vs semaphore control (oracle.md
   19.6: semaphore won reply latency) -> owner choice A: EXIT-DRIVEN admission in the phase
   domain (oracle.md 19.7; tie with the semaphore, reply p50 398 -> 203 ms), live gate passed
   (`20261001-163433`: 15/15, no regression, reply sum **340 s**; landmark
   `lm_f34858a6bdab8028`; `IRIS_ORACLE_PHASE_EXIT=1` in `.env`). Batched "decide together"
   rejected twice (the export leaks rows into each other; oracle.md 19.6).

7. **Audio crash root-caused** (`9a375780` armed faulthandler; `fb53cb6d`): two threads played
   one utterance (sounddevice's global stream) -> access violation; one process-wide playback
   lock. **Coupling gate** (`evals/run_pairs.py`): T4 PASS, T8 INCONCLUSIVE (means 478 vs 479 s,
   14/14 everywhere, 0 collisions) -> coupling stays off (oracle.md §0). **Oracle work PAUSED
   (owner) - back to the audit items.** HANDOFF 7 pin lists everything open.

OPEN (in order): see HANDOFF 7 (sections C + D); record a research standard (`--record-standard` after a clean run); move shadow scores
from the FIFO lane to phase participants (rows stay on their writer); `depth_met` still inline
(0.4-0.9 s, feeds the continuation only when enforced); `mode` / `narration` / `presentation`
shadow scores inline (counts in the `Oracle inline decisions` log line); streak-gate-only-on-
steering (owner decision; c06 proved the brake is needed); `tool_choice` live max 5.9 s once
(not explained); Sigma redo by node calls; the HANDOFF 6 list (Wave U, Wave C browser_next).
Pre-existing failures verified on committed code this session: 9 Oracle fakes lacking
`instruction`; `test_bt_gc6_*` x2 (MCP file_manager); `test_encode_with_meta_backend_is_hash`
(fails while the embedding sidecar runs); `test_missing_db_unverified` (`_app_store` import).

## 2026-09-30 (session 64237209) — HANDOFF 5 follow-ups: A5, test change, store cleanup (S12)

**Wave B** runs in a Sonnet builder subagent in its own worktree (B1-B4); TG-B (live drive,
Mode B) and Wave C stay with the Director.

**(1) A5 — extractor off the agent answer path** (commit `0d65d398`). `research()` takes
`defer_extraction`; `tool_bridge` crawler_query sets it. The funnel returns right after rerank;
`extract_and_cite` runs on `durability_queue.lane("web_extract")` and hands OPEN_TAB (same
payload) then CRAWLER_COMPLETE back to the caller's loop. The gateway path is unchanged
(synchronous). Log line: `[web_timing] job_id=... deferred extract_ms=`. Effect: the agent tool
result's `summary` and the job registry's summary/cited_markdown are empty on the agent path (the
agent reads `content`). AC3.2/AC3.3 were already done in Wave A. MEASURED 2026-09-30 17:01 (warm, quiet): r01 PASS reply 50.0 s, r05 PASS 24.8 s (was 48 s), r06 PASS 30.1 s (new check). All three answered from the quick `search` tier - `crawler_query` never ran, so A5 was NOT exercised; r05's gain is routing (search 2.8 s vs its earlier crawl 31.8 s). A5's ceiling per crawl = the earlier r05 `extract_ms=1745`. r01's 50 s: one cold Exa call `search_ms=13557` (the open Exa-cold finding). Exercise A5 with a task that needs a crawl.

**(2) Test changes (owner-approved).** `contract/test_search_discovery_contract.py::
test_capability_path_consults_robots_before_fetching`: `startswith("Mozilla")` -> `==
capabilities._TIER1_USER_AGENT` (the contract is gate UA == fetch UA). NEW
`contract/test_crawl_orchestrator_contract.py::test_deferred_extraction_returns_before_blocked_extractor`.
`evals/tasks.json` r06: the `million` pattern now also accepts a 7+ digit or comma-grouped figure
(r06's correct answer said "14,246,219").

**(3) Store cleanup + S12.** Backend stopped; backup `D:\iris-backup\2026-09-30\memory.db*`
(sizes verified). Writer: `iris_ffi._PythonFallbackEngine.immortus_chain_append` copied `result`
into the legacy NOT NULL `content` column (no reader uses `content`, native engine included).
Fix: `_bound_chain_result` caps at 64 K chars with a marker (Python writer + native branch);
`content` written empty. Store: `content` blanked where it equalled `result`; 84 results capped;
84 `document_data` rows that were captured store listings (`{"success": true,
"conversation_id": ..., "documents": [...]}`, 1.23 GB) blanked to a marker JSON (row identity
kept); VACUUM -> 0.277 GB. `test_chain_coordinate_store_contract.py` copies the live store —
run it after the VACUUM only.

**Immortus chain = the 4D time layer (owner note).** The document landing (`agent_kernel._store_document_data`) wrote the whole canonical document (content + variants) into the chain row's `result`, so the chain held the payload instead of the document's place in time. Now the row is a REFERENCE (`document_id`, format, trust, chars, 400-char head); `retrieve_documents_by_trajectory` rehydrates the document from `document_data` by `file_path`; `coords_to` = `coords_from` (a point event, was the format string); written on the ordered durability lane (was a thread per row). Guard: `contract/test_document_data_store.py::test_s12_*`. TEST HARNESS CHANGE (both copies of `test_document_data_store.py`): `_run_process` now drains the fragment queue and the durability lane before asserting (the asserts had won a thread-start race). Load 0.277 GB store: recall newest-5 0.123 s -> 0.000 s (warm). OPEN gaps from the read-only map (for an owner decision): coordinate-addressed recall has no production caller (`retrieve_documents_by_trajectory`, `immortus_chain_query_by_coordinate`); `created_at` is used only for recency ranking (no windows, decay or trajectory replay); `api/chat.py` writes `rest:input:<turn>` pseudo-coordinates and `agent/mcm.py` writes Python lists as coordinates (both unparseable by the coordinate query).

## 2026-09-30 (session 13a261c7) — post-move check, startup disk contention, S10

**State of the move.** Site-packages SWITCH not done (still a real dir on C:), no reboot since
2026-09-27 -> S9 (cold start) still waits for the owner. LM Studio junction, HF_HOME on D: and
`data/memory.db` (primary, C:) verified. Page file is on D: (peak use 22.8 GB since boot).

**Coding eval after the move: 15/15** (`evals/results/20260930-115609.json`, warm backend).
Replies c02-c15 12-105 s. One STANDARDS flag: c01 reply 452.6 s (standard 144.6 s). Cause
(stack dumps): its first `pytest` subprocess took 4.5 min (11:37:42 -> 11:42:15) because the
background whisper warm-up (`main._delayed_whisper_warm_up` -> `voice_command._do_warm_up` ->
`import faster_whisper` -> `ctranslate2` -> `transformers`) was still importing from the C: hard
disk 8+ min after start. The second pytest in the same task took 20 s. A heavy grep of mine also
ran during c01's first ~40 s. Not an agent regression; do not re-record the standard from this run.

**Startup disk contention (finding, not fixed).** Three starts: TTS ready never (worker hung
>7 min at 0 CPU / 0 reads, then "Worker exited during startup" with no traceback), 123 s, 116 s.
Standalone the same worker loads in ~10 s. In the hung start the weights load took 336 s; the
worker's own TEMP stack dump blocked mid-line for minutes. During every start the backend reads
~1 GB (Oracle ORT load + hash of the 642 MB model at `C:\temp\gliner-onnx`, embeddings, imports)
while the worker imports torch from site-packages on the same hard disk; the whisper warm-up
adds `transformers` at +90 s. Main lever: the owner's site-packages switch to D: (plan Step 1);
then consider moving `C:\temp\gliner-onnx` to D: (`IRIS_DECISION_MODEL_DIR`). Open: why the
worker exits silently after a late load (exit code is not logged). TEMP probe added:
`tts_worker.main` writes `logs/stackdump_tts.log` when `IRIS_STACK_DUMP_S` is set (remove with
the `start-backend.py` hook, item 4).

**S10 (owner option 2): Oracle model hash cache.** `GlinerOnnx._hash_model_file` returns a
cached digest when (abs path, size, mtime_ns) match `data/oracle_model_hash.json` (gitignored);
miss/corrupt -> hash as before + atomic write; a cache failure never fails `load()`. Same digest
logged (`hash=61dd40d59032`), 0 hash frames at startup. Tests: model-pin + onnx-backend unit and
contract (18 passed), `test_startup_readiness_standards.py` 4 passed; `test_s10_*` fails on the
old code ("an unchanged model file was read again").

**S9 cold baseline (BEFORE the site-packages switch).** Owner rebooted 12:08; backend started
13:00:37 (52 min after boot, site-packages still on the C: hard disk): `/health` 200 at 13:13:08 =
**12 min 31 s**. Backend imports 2.6 min before the TTS spawn; TTS worker imports (torch +
pocket_tts) 8.9 min (its TEMP stack dump shows `torch._load_dll_libraries` ~4 min in); model load
25.7 s; warm-up 34 s; first Oracle decide 47.7 s (scoring 20.6 s cold). Warm starts the same day:
116-123 s. The switch to D: is the fix to measure next (owner runs it with Claude Code closed).

**Research re-measured (warm):** r01 PASS reply 154 s, r02 PASS reply 64 s. r01 split: plan 18 s,
Exa URL planning 16 s, crawl 36 s (3 pages in ~6 s; both en.wikipedia.org URLs "Tier-1 unusable
(reason=challenge)" -> pooled browser -> 25 s run budget -> parked), `data_extractor` Brain pass
43 s, goal-contract extract + synthesis 30 s. Wikipedia check: plain HTTP with no / httpx /
Chrome-like User-Agent -> 403; a UA-policy User-Agent (app name + contact URL) -> 200 in 0.54 s,
and the good page itself contains the word "challenge".

**pin_22b078571d73 (b) RESOLVED — where the 6.6 GB went.** Full read-only page attribution of
`data/memory.db` (a sequential walker over every b-tree / overflow page; `dbstat` is not compiled
in): `memory_chain` **4.89 GB**, `document_data` 1.24 GB, `context_chunks` 0.22 GB, everything
else < 0.01 GB, freelist 0.23 GB. **37 `memory_chain` rows hold 4.84 GB** (single rows up to
841 MB; `content` and `result` duplicate each other, 2.44 GB each), threads `de-domain`
(2026-09-20) and `r3`/`r4`/`r10` (2026-09-27). Each is a `get_rendered_documents` result
(`{"success": true, "documents": [...]}` with the FULL content of every stored document)
captured by `_capture_tool_result` as a NEW document, so the next read nests it again, escaped
again — size doubles per round. CORRECTION: the 2026-09-30 note "memory_chain is small, the S2
cost is cold random reads" was wrong (it sampled the first 200 rows); the ORIGINAL S2 explanation
(the recency sort walked huge rows' overflow pages) was right. Index-build decision: NOT moved
off startup — a background `CREATE INDEX` holds the write lock for its whole run (ledger/memory
writes would fail with "database is locked"), the 7.5 min build happened only on this bloated
store, which already has both indexes, and a fresh store builds them in milliseconds.
Code fix: store-read tools (`_DER_READ_TOOLS`) are not capture-worthy. Data cleanup (owner):
blank or delete the 37 rows, then VACUUM (back up first) -> the store shrinks to ~1.8 GB.

**Spec rev 2 Wave A implemented + measured (research group, warm).** Before: r01 PASS 154 s, r02
PASS 64 s (others not measured today; 2026-09-29: r02/r03 FAIL at 600 s). First run after Wave A:
3/8 FAIL — the quick tier's new `results` list (title/url/300-char snippet) was read by
`_format_tool_result` BEFORE `content` (its key order is result, results, content...), so the agent
saw snippets only; and the success-synthesis floor `max(80, 40*steps)` rejected a correct 46-char
one-step answer twice and served a raw JSON close. Fixed: key renamed `source_list` (the one new
builder test that pinned the name updated with it), each source gets an equal share of the 8 k cap
with its highlight first, floor = 40 chars per step (as its own comment intended), stub text logged.
After: **7/8 PASS, reply_s r01 44, r02 15, r03 19, r04 10, r05 48, r06 20, r07 13, r08 13**
(`evals/results` 2026-09-30 14:54). r06 answer is CORRECT (Tokyo 14,246,219 vs Osaka 2,816,247)
but the check wants the word "million" — check unchanged (test rule). OPEN for the owner: A5 lane
move conflicts with `contract/test_crawl_orchestrator_contract.py::test_funnel_order_and_events`
(asserts `cited_markdown` + OPEN_TAB before CRAWLER_COMPLETE on return); A2's policy UA fails
`contract/test_search_discovery_contract.py::test_capability_path_consults_robots_before_fetching`
(asserts the robots UA `startswith("Mozilla")`; its purpose, gate UA == fetch UA, still holds).
AC2.5 dropped (the only budget is the absolute run deadline, so a post-semaphore clock changes
nothing). Findings logged for later: `_der_check_steering` returns before `_der_streak_gate` when
no steering is queued — the stuck-streak gate (and its rec==3 override) runs only when the user
steers.

**pin_22b078571d73 (a) DONE — option B, the topology halt is live.** `_der_topology_halt` (module
level, next to `_der_physics_settle`) runs at each step boundary in `_execute_plan_der`, before
the steering check, outside every advisory try. It reads only a LANDED update (never waits: S3),
raises `TopologyViolationException` once per update (`fold.halted`), and
`_der_execute_with_recovery` runs its targeted recovery (Caducean reset + DER_RECOVERY + one
retry). Note: an unacted violation left by the previous turn halts the next turn's first boundary.
Guard: `contract/test_topology_halt.py` (9 tests, all fail on the old code). DER behavioral files
loop/concurrent/invariants/batch_expansion/rejects_stub/phase3 pass; `test_der_c1_error_propagation`
fails on the committed code too (stand-in `_Step` has no `expected_output`, pre-existing).

**Owner note (2026-09-30): websearch / research has always been slow and must improve.** Next:
Mode A on the research group, one task at a time, timeline + stack dumps before any change.

## 2026-09-29 (session aa473536) — c10, then answer-path latency

### c10 fixed; coding 15/15

- Cause: `_der_run_node` passed only `item.description` (the planner's paraphrase) to the node;
  "qty <= 0 raises ValueError" and "ValueError when not enough" were lost, and the Brain wrote a
  generic inventory class (KeyError, `< 0`). Fix: `NodeContext.task` = `plan.original_task`,
  shown word for word above the STEP goal (`node_executor._user_message`). c10 8/8; full coding
  group **15/15** (`evals/results/20260929-223059.json`).

### Where turn time went (stack dumps, `IRIS_STACK_DUMP_S=4`)

A 63-185 s turn held ~11 s of real work. Every stall found was on the answer path, none in
model or physics math:

| Stall | Measured | Cause | Fix |
|---|---|---|---|
| per-step physics in `_der_finalize_step` | 16-84 s | `calculate_eml` counts SCAN `system_events` (no `session_id` index) on a cold 6.3 GB file: 18.3 s python SQL cold vs 0.26 s native warm | `idx_system_events_session` (migration 001's definition, never applied) in `_PythonFallbackEngine._run_migrations`; physics moved off the answer path (below) |
| turn-start DAG compile | 40 s | `ontology_recall` `ORDER BY created_at` on `memory_chain` read every row (widest scope 119 s cold). CORRECTED 2026-09-30: not row size — the table is ~1.5 MB; cold random reads across the 6.6 GB file (`pin_22b078571d73`) | `idx_memory_chain_created` in `migrate_memory_chain_schema` (guarded) -> 0.000 s. First startup builds it once (~7.5 min) |
| ledger write storm | ~90 threads | thread-per-row on one shared connection; "database is locked" fell back to the native writer and blocked | one ordered ledger lane |
| harness "63 s" | ~20-26 s | the harness drain counts the reply's SPEECH | `reply_s` in the results |
| c11 step 1 | ~110 s | Pocket-TTS model load (61.5 s) inside the turn starved `pytest` | NEXT (item 1) |

### Physics side lane (Caducean fold-back)

- `_der_submit_physics` / `_der_physics_step`: EML, integrator update, coupling, trajectory row,
  rec==3 handling, homeostasis, controller refit, Immortus chain append and REQ-7 physics
  narration run on `durability_queue.lane("physics")` (one FIFO consumer = sequential
  integrator). Node-record stamping / goal contract / links stay inline.
- Fold-back barrier `_der_physics_settle(owner, session)` (module level, so kernel stand-ins in
  tests still run the guarded read) waits on `fold.ready` (set right after the integrator
  update, not after the bookkeeping). Only SHAPE DECISIONS call it: streak-gate topology
  override, both split-width reads, continuation expansion (rec read moved after the consult).
  Modulation readers (planner temperature, envelope hint, edge scoring) never wait.
  `DER_PHYSICS_FOLD_WAIT_S = 30` bounds a decision's wait, never cancels the update; it fired
  once (106 s stall, before the index) and kept a bonus step COMPRESS would have dropped.
- Envelope coords + topology stop fold in under `fold.lock` (`_der_fold_envelope`), whichever
  of the lane and the envelope build finishes second.
- Finding (not changed): the rec==3 `TopologyViolationException` was always swallowed by
  finalize's own `except Exception`; it never halted the loop.

### Lanes (`backend/utils/durability_queue.py`)

- `_Lane`: one bounded FIFO + one daemon worker; optional single watcher thread per lane.
  Module API = the default lane (unchanged callers); `lane(name)` for `physics` and `ledger`.
- `tool_bridge._LEDGER_LANE` writes every ledger row; its watcher runs `_watch_ingest` on each
  row, so a blocked row still logs "has not returned". After the change: zero "database is
  locked" / "has not returned" lines in the eval runs. The Python writer does NOT retry
  "locked": `execute`+`commit` on the shared connection would write a row twice.

### Tests

- Targeted: 61 finalize/envelope/split/narration/ledger tests pass; node executor 7/7.
- Owner-approved test changes: `test_ledger_write_watchdog::test_the_writer_is_watched` now
  drives the real ledger lane; `test_screenshot_memory::test_record_tool_event_forwards_screenshot_blob`
  flushes the ledger lane before asserting; both copies of
  `test_der_a1_a2_a3_memory_bridge::test_fragment_failed_output_stored` wait on the pacman
  fragment worker (a sentinel) before asserting. No assertion changed.

### Numbers (reply_s = time until the reply text)

| Task | Before (harness s) | After, reply_s |
|---|---|---|
| c10 | 63-226 | **16.9** |
| c07 | 63 (37 in-backend) | 75.3 (first turn after restart; 19 s planning + cold physics) |
| c11 | 77-243 | 213.6 (TTS model load during the turn, item 1) |

## 2026-09-29 (session 5958c478)

### Eval re-runs (coding subset c01, c04, c15)

| Run | Result | Turn seconds | What failed |
|---|---|---|---|
| Baseline (pre-fix) | 0/3 | 140 / 63 / 136 | reads hit the IRIS repo (Errno 2) |
| Run 1 (Phase 1 loaded) | 0/3 | 146 / 123 / 228 | reads OK; writes went to `C:\durations.py`, `C:\home\user\mathutils.py` |
| Run 2 (+ rooted-path fix) | 0/3 | 321 / 76 / 88 | paths OK; **no step ever resolved to write_file/edit_file** |

Results: `evals/results/20260929-170722.json`, `evals/results/20260929-173113.json`.

### Fixes

- `backend/agent/tool_bridge.py` `_anchor_file_paths` + `_reroot_into_workdir`: a rooted
  path with no drive (`/durations.py`, `/home/user/x.py`) is re-rooted into the session
  workdir (longest suffix whose parent exists). On Python 3.14/Windows such paths are not
  `isabs`, and `os.path.join(workdir, "/x")` kept only the drive. Test:
  `backend/tests/unit/test_file_tools_rooted_path.py` (4 cases, all fail on the old code).
- `backend/agent/local_model_manager.py`: llama-server `D` (debug) lines are no longer
  forwarded to `logs/iris.log`; `-lv 5` stays for load progress. At -lv 5 the server wrote
  ~10 lines per token (log reached 2 GB). Test:
  `backend/tests/unit/test_llama_debug_lines_not_logged.py`.
- `evals/run_evals.py`: leak guard ignores `.iris-worktree/` (the developer-mode switch
  builds it, not the agent).

- **B9 + split roles (Brain writes file bodies).** New `edit_file(path, old, new)` in
  `backend/mcp/builtin_servers.py` (exact single match, CRLF-safe, atomic), `read_file`
  `start_line`/`end_line`, atomic `write_file`. Wired in `tool_bridge.py` (tool list, MCP map,
  self-edit route, turn-write tracking), `tool_registry.py` (specs, `authored_by: "brain"` on
  `edit_file.old/new` and `write_file.content`), `capabilities.py`, and the developer Oracle
  menu (`edit_file` in the top 4). New `backend/agent/brain_author.py`: after the box picks
  `edit_file`/`write_file`, the Brain gets the step goal, the current file and earlier step
  results, and returns SEARCH/REPLACE blocks that are checked against the file before any
  call (one block -> `edit_file`, several -> one verified `write_file`, missing file -> whole
  `write_file`). Hook: `agent_kernel._der_run_step_execution`, right after box resolution.
  The box handshake no longer asks the Brain for `authored_by` fields with 200 tokens and no
  file (`tool_decision._missing_required`). Tests: `test_edit_file_tool.py` (6),
  `test_brain_author.py` (7).
- **Self-edit route bypass (B10 area).** `_route_self_edit` joined the path by hand, so a
  rooted `/x.py` or a `file_path` key skipped the IRIS check and could write the live tree.
  It now resolves through `_anchor_file_paths` (both keys).
- Neighbouring suites: 73 pass; 5 failures are pre-existing (same 5 fail with these changes
  stashed): `test_capability_escalation::test_t23...`, `test_standing_list::test_edge...`,
  3 in `test_decision_engine` (fake backend lacks the `instruction` kwarg).

- **Eval run 4 (c01 only, B9 + Brain authoring loaded): PASS** — first coding pass since the
  audit (330 s turn). Run 5 (all three, with the perf fixes below): 0/3 but turns 144/82/63 s
  (was 321/76/88 and 330). Failure: the tool model resolved every c01 step to `read_file`
  (6 times), so the choice itself is the weak seam -> Phase 2.
- **Speed (measured with in-process faulthandler dumps, `logs/stackdump.log`):**
  - Oracle `done` monitor passed the whole planner prompt to ONNX: 28.6 s for one call,
    65.7 s over 4; every other consumer queued behind it on the single inference thread and
    6 gave up at the 9 s budget. Fix: `decision_backend_onnx._MAX_INPUT_IDS = 512` cap in
    `encode()` (test `test_decision_input_cap.py`).
  - Embedding sidecar ran two health checks per embed, each a new httpx client + SSL context,
    under a global lock. Fix: health check on the pooled client; `touch()` after a successful
    embed no longer re-checks.
  - `calculate_eml` FFI (20 s+ once) was also called on every system-prompt build -> removed
    with B17. It is still called per step in `_der_finalize_step` (not changed yet).
  - Turn-start memory recall (ontology 16 s, episodic 18 s) and the Whisper warm-up
    (first turn after start, GIL contention) remain.
- **B17 done:** 772 mojibake lines in `agent_kernel.py` repaired (reversible cp1252->UTF-8,
  only where valid; file parses); EML/Caducean lines removed from the system prompt; today's
  date added; `_`-prefixed test skills kept out of the PersonalityManager prompt via
  `skills_loader.prompt_skills()` (tests still require `load_all_skills()` and
  `get_skill_prompt_context()` to list them). Test `test_prompt_skills_exclude_fixtures.py`.
- **B8 done:** `SemanticLogicGate.compile_dag(..., developer=True)` routes every non-chitchat
  request to DER; the kernel passes the launcher mode. The pinned verb list is unchanged.
  Test `test_developer_mode_routes_to_der.py`; 68 gate tests pass.
- **B1 done:** Ollama transport sends `tools`, converts the OpenAI-shaped history (arguments
  as objects, `tool_name` on tool results), returns tool calls in the OpenAI shape, accepts a
  tool-only reply, and honours `timeout_s` (default 120 s, was a fixed 30 s). A plain call
  keeps the old payload. Test `contract/test_ollama_transport_tools.py`.
- **Phase 2 started — node executor:** `backend/agent/node_executor.py` `run_node(goal, ctx)`:
  the Brain runs a bounded tool loop per DER step (developer tools only), sees its own calls
  and results, ends on a reply without a tool call or at the time budget (300 s); tool
  exceptions become typed results; a failing last `run_command` fails the node. Kernel hook:
  `_der_run_step_execution` -> `_der_run_node` (developer mode, tool-less steps); tools go
  through `ToolDecisionBox.dispatch` (ledger rows, deadlines, permissions). Tests
  `test_node_executor.py` (5). Not yet: plan_update tool, shadow Oracle rows per node call,
  tool-model argument repair, transcript summarising for long nodes.

- **Eval run 6 (Phase 2 loaded): c01, c04, c15 = 3/3 PASS** (174 s, 63 s, 94 s). Full coding
  group running (7/7 so far at 19:09).
- Node loop records an Oracle shadow row per Brain tool call (`NodeContext.on_call` ->
  `record_shadow_tool_choice(async_=True)`), owner decision 2.
- Developer prompt names the bound project folder when it is outside IRIS, instead of "full
  access to the IRISVOICE source ... iris-agent branch" + PROJECT.md
  (`_bound_external_project`, test `test_developer_prompt_names_project.py`).
- **B10 done:** `tool_bridge._self_edit_view` maps live-repo paths into `.iris-worktree` for
  `read_file`/`list_directory`, grep/glob scope and the command cwd while a session edits IRIS
  (test `test_self_edit_reads_worktree.py`; caught a `\.` suffix bug on the repo root).
- **B13 done:** `_decide_mode` treats `code` (from `code_task`) and `quick_edit` as AGENTIC, so
  a short coding request no longer runs in QUICK (test `test_short_coding_request_is_agentic.py`;
  director contract 40/40).

### Findings

- Tool model runs on the GPU: 31/31 layers on CUDA0 (RTX 3070). The embedding sidecar
  (:18183) is CPU-only by spec (REQ-1 AC6).
- Speed: tool calls take 2–5 s, Brain calls 0.5–12 s (Ollama server log), but the DER loop
  sat idle 20–60 s between steps with no model working and CPU at 13–30 %. Cause under
  investigation (static code reading).
- `localhost` costs 2 s per request to IPv4-only llama-server ports on this machine
  (`::1` tried first). The backend already uses `127.0.0.1` for :8082 and :18183, so this
  is not the idle-gap cause. Rule: new clients of a local llama-server use `127.0.0.1`.
- `pytest` startup took 96 s during a turn vs 2.5 s idle (machine contention). The agent's
  own `run_command pytest` pays the same cost (56.7 s in c01 run 2).
- The backend stops answering for 20–45 s about a minute after start / after a model
  load. One capture: `[RetentionManager] Starting retention cycle` 18:06:08 ->
  `No episodes to delete` 18:06:29 — a single synchronous `DELETE` on the event loop, with
  `busy_timeout` only 5 s, so it waited on something else (likely the shared
  `check_same_thread=False` connection held by another thread). The next start it took
  10 ms. Under investigation with in-process `faulthandler` dumps
  (`IRIS_STACK_DUMP_S`, TEMP hook in `start-backend.py` — remove after).
- The Claude desktop app runs a ~1 GB `git.exe` every few seconds on this dirty repo; this
  is test-setup load, not IRIS.

### Warning — do not repeat

- Sampling the backend from outside (`py-spy dump` + `python -m asyncio ps <pid>` every
  3 s) killed the backend at the start of a turn with no traceback, and Claude Code crashed
  with it (the backend ran as a Claude preview server). Use static reading or in-process
  logging instead. Start eval backends from the owner's terminal, not `preview_start`.
- After that crash `data/iris_config.json` kept `"mode": "developer"` and a `projects`
  entry `iris-evals`. Restore by hand: set `"mode": "personal"` and remove the
  `iris-evals` project.

**MCM:** all entries are recorded (events for every file above; pins `pin_667d96e1f0ab`,
`pin_4ab08d0e1e3d`, `pin_04ca19e140d9`, `pin_00396afe0eae` (sampling warning),
`pin_40f41890e505` (where turn time went), `pin_afa4442771d1` (HANDOFF 2 — read first)).

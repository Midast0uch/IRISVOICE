# Execution audit — progress log

## START HERE (next session)

**Foundations (2026-09-30):** the roadmap is `.mcm/GOALS.md` (the old `bootstrap/GOALS.md` is
archived there); CLAUDE.md/AGENTS.md now carry "BUILD + VERIFY IRIS — THE MEASURED LOOP" and
"READING THIS CODEBASE — PHASE MODEL, PHYSICS, LANES"; validate every change with the
`app-testing` skill, Mode A (`.opencode/skills/app-testing/SKILL.md`) — MCM `pin_6c81e87956b8`.

**2026-10-06 (session ee236373, later) - PHASE 3 + 4 DONE LINES MET LIVE.** Phase 3: every turn ends with exactly one `turn.end` (5 real recordings, `__tests__/fixtures/turns/recorded_*.json`); an error shows in the chat (a turn cut by a backend restart ends "IRIS restarted during this turn" via `initial_state.boot_id` + `endsForLostTurns`); replay tests of RECORDED turns pass in both modes (`__tests__/turns/recordedTurns.replay.test.ts`). Phase 4: prompt -> matrix (rows appear/run/fold) -> rendered answer; no sideways scroll (scrollWidth = clientWidth); `>cmd` is an EXEC row with its output. Also fixed live: `turn.end` settles a card that still works (a stuck card turned every message into a steer); a stopped turn stays quiet (its late reply drew an empty IRIS entry); Stopped / error lines survive a reload (`_persist_turn_outcome`); STOPPED / FAILED fold words come from the turn's end; `?mode=` syncs the backend mode (`>cmd` was refused as personal); a refused `>cmd` fails visibly; an empty open strand no longer says "Select a conversation". OPEN: a live VOICE turn (needs the owner's wake word); legacy couriers not retired (not in Phase 3 DONE); the reply sometimes starts with "ANSWER:" (model text leak, reply surface).

**NEXT AGENT: read MCM HANDOFF 14 (`pin_6d8db9f7b4c8`) FIRST** - Phase 3/4 status, what is missing, Phase 5 (not started), the port-registry request; commits after 9d9ebf59 are NOT pushed (owner reviews first).

**2026-10-06 (session ee236373) - LIVE GATE OF PHASE 3/4 ON THE OWNER'S MACHINE (commit c471431f).** Owner: the developer view did not match `iris-strands.html`. Found live and fixed: developer turns showed NO matrix (the personal-mode card bound withheld every task/tool frame; `_developer_mode()` opens both gate sites); DER-DAG nodes reported `tool_name="direct"` (rows read DIRECT, settled cards dropped as tool-less; `_step_tool_name()` sends the decisive call); developer timeline keeps tool-less cards and puts the matrix BEFORE the answer; settled cards read 0:00; `>cmd` sent `>` to the shell; a text-less notice printed "steering:ack"; `write_file` wrote CRLF over LF files on Windows (8 edit-diff guards failed on Windows). Look: matrix = concept devTurn (no frame / TASK header, status note, one fold line), dev prompt = `.you` bubble; dashboard rail Settings / Surfaces moved ONTO the spine (owner disliked the concept pill too). OPEN (pin_b7aa8453a9dc): streak gate re-plans while the planned summary node is pending (3x work); a stuck `isWorking` card turns every message into a steer; TTS final-answer playback hang; `logs/iris.log` 2.28 GB; stopped receipt lost on reload; personal-mode settled cards now stay (check the look live).

**2026-10-06 (session 01UufETT, rev 4) - THE DASHBOARD JOINS THE SPINE (S74).** Owner approved `docs/design/chatview-2026-10-06/iris-dashboard.html` with changes: rail = spine with Settings / Surfaces views; Monitor + Inference console = ONE Monitor page (instrument panel, `docs/architecture/MONITOR.md`); orb rows only for plain setting fields; one shared `◉` menu (`components/chrome/WingMenu.tsx`); `@` = who hears, `#` = what you point at (IRIS made + This project, file refs reach the agent as addresses); hub drops go to a Views lane. Also: "Learned" replaces "Crystallized" on the task card; knots are clickable with a hover card; one thinking line per mode. OPEN: owner to confirm updating the "APPLY" / "LOCAL MODEL" selectors in two older tests (they fail on `fetch is not defined` in every run today); then delete the six unused Monitor/console panel files.

**2026-10-06 (session 01UufETT, later) - THE APPROVED CHAT DESIGN IS BUILT (S69-S73).** Strands + summary thread list, edit diffs + undo that tells IRIS, brand palette + edge lights + dashboard ink, the spine, the composer (project bar both modes, `to`, `#` refs, steer, Stop), in-turn asks / lens / `±` review / MADE rows, the header (Xur orbit, strand map, rename, `◉`). Map: `docs/architecture/CHAT_VIEW.md` §9-§12. NEXT: (1) the LIVE GATE on the owner's machine - a text turn, a voice turn, an error turn, a Stop, an edit + Undo, a strand create/switch (record with `IRIS_TURN_RECORD_DIR`); (2) owner decision on the "Crystallized" footer word (CHAT_VIEW §8); (3) a clean checkout cannot import `backend.core.logging_config` (`ShareableRotatingFileHandler` is in no commit) - the owner's local `backend/monitoring/structured_logger.py` must be committed.

**2026-10-06 (session 01UufETT) - execution-audit PHASE 3 BUILT (turn protocol + turn store + chat-view split); owner approved the chat-view design (concept 2 rev 3). Read `docs/architecture/CHAT_VIEW.md` first, then `docs/design/chatview-2026-10-06/README.md` (every approved design decision).** Commits "feat(turns)...", "feat(chat): live turns render...", "refactor(chat): move ... (1/3, 2/3, 3/3)". Done: every turn is `turn.start` / numbered `turn.part` / exactly one `turn.end` (text + voice paths, event bridge routes bus events into the live turn; S66); the frontend turn store files turns by the event's conversation and the chat renders live turns, reasoning, notices, errors (+Retry) and "Stopped" in their turn (S67); audit bugs closed (card-anchor early return, 500-char clamp while streaming, chunks to the active conversation, pills without conversation_id, fetch inside a state updater + stray "Retrying...", no listener for errors/reasoning, frontend failed-search rule) + a voice-path UnboundLocalError (`_sttproc_stop` on the pending-question return). Split: `chat-view.tsx` 5,645 -> 3,396 lines (the shell) + `components/chat/` Composer, ChatHeader, NotificationsPanel, HistoryPanel, Timeline, TurnView, TaskCardEntry, `turn/TurnParts` (pure moves, line-compared). Test inputs changed, owner-approved: `chat-view-surface.contract.test.ts` reads the shell + its timeline files as one source; `test_one_task_card_render_site.py` expects the site in `TaskCardEntry.tsx`; CT-10 triage lines for the new files. Verified here (cloud, no live app): tsc (2 pre-existing errors), frontend jest 10 failing tests in 5 suites that ALSO fail on the pre-change code (TaskListCard, dark-glass-dashboard.apply, model-status-badge, useTaskProgress.ordering, useTaskProgress.update-step-writeset), pytest turn-protocol + render-site 34/34. NOT done: the live gate on the owner's machine (one text, one voice, one error turn; record with `IRIS_TURN_RECORD_DIR` and add as fixtures); retiring the legacy couriers; strands in the conversation store. PHASE 4 BUILT the same day (S68; `docs/architecture/CHAT_VIEW.md` §7): prompt line, live matrix (`components/chat/matrix/`), markdown answer in mono, `>cmd` as an EXEC row; GUI/ANSI parity test; the ANSI renderer stays for export. CSS NOTE: the app loads `public/globals.css` (compiled from `css-src/globals.css`), NOT `app/globals.css`; the matrix keyframes are in both css-src and public. Live gate for Phase 3+4 on the owner's machine is still open. NEXT (approved design, in order): the timeline spine (Xur trail, knots, chips on the spine; personal-mode spine through the card), `±` diffs + review lens, reply-surface Phase B (compact cards + receipts in the turn) and D (MADE / ASK / permission matrix rows), strands in the conversation store, then retire the legacy couriers.

**NEXT AGENT: read MCM HANDOFF 13 (`pin_465d549a12e6`) FIRST, then this note, then `docs/architecture/DER_DAG.md`.** Work: execution-audit **Phase 3** (turn protocol + turn store + `chat-view.tsx` split) and **Phase 4** (live execution matrix) - the owner wants them DONE. Before you build, VERIFY that everything below is clean, has no regression, and supports the backend (section "Verify first").

**2026-10-05/06 (session ae9c2fb9) - HANDOFF 13: DAG accuracy, speed, reply-surface Phase A + R5, Whisper fallback-only, Oracle calibration + two-key enforcement (S51-S65).** Commits: the session's 14 commits, from "fix(dag)" (e48165da before the rewrite) to "feat(oracle): Stage B". PUSH NOTE: no push had worked since 2026-09-15 - commit dffd1bd4 (2026-09-21) added six files over GitHub's 100 MB limit (Parakeet encoder.int8.onnx, llama.cpp-prismml CUDA DLLs and zips). On 2026-10-05 (owner decision) the 264 commits after 9337ac8f were rewritten without those six files (kept on disk, now in .gitignore), so EVERY commit ID after 2026-09-15 changed; the old IDs in this file map by commit subject, and the pre-rewrite history is on the local branch backup/pre-strip-20261005. Pushed (fast-forward) to origin/feat/agent-multi-step-tool-execution-20260915; origin/feat/agent-multi-step-tool-execution holds an older, unrelated history and was NOT force-pushed. A fresh clone needs the six files copied in by hand.

**What is done (each guarded by a test that fails on the old code; live gates green):**
- DER-DAG accuracy (S51-S56, S61): goal contract covers a fact by its own NAME (else an own word, or a passing run after the step's last change); COMPRESS no longer skips an open fact (fixed-text cover push); every settled step gets a node record (added steps count); node results keep each call's head and DER evidence is not cut twice; node mediator = the decisive call; prior research once per finding; a reply that calls a covered fact "missing" is written once more; a node that changed files and whose last run failed is UNVERIFIED; node failures reach the failure router and the missing-artifact graft; dead semaphore executor deleted. r09 three-fact task 10/10.
- Speed/transport (S58, S59, S63): planner `reasoning_effort="low"` (4.17 -> 1.63 s per plan); reasoning resend floor 1,024 tokens; provider 5xx retried to the 3rd attempt; hedge after 2 x p75 (was 2 x p90, which the stalls pushed to 35-39 s).
- Reply surface (S60, S62): HTML artifacts render in a sandboxed iframe (R5); `create_artifact(title, kind, summary, content, language?, artifact_id?)` is the ONE door to a card (Phase A); `{speak, show}` converts to it; demotion, fallback mint, web-format question and `render_document` deleted.
- Voice: Whisper is the fallback only - no boot warm-up; boot pre-reads Parakeet's files (39-75 s, idle, low priority); the eval gate waits for that line (max 10 min).
- Oracle (S64, S65): honest measurement + per-consumer isotonic calibration (Stage A) and one chokepoint `decision_engine.decides()` with two keys (Stage B): a consumer decides only when the owner switched it on (`IRIS_DECISION_ENFORCE`, default EMPTY) AND it earned the hardened bar AND a threshold was fitted. Default: nothing decides. All non-deciding Oracle calls run on the `oracle_shadow` lane. oracle.md §0 and oracle.html are current.

**DER-DAG in one paragraph (details + diagrams: `docs/architecture/DER_DAG.md`):** the planner (`_plan_task`, one Brain call, low reasoning) writes GOALS (no tools) with `depends_on` edges -> `DirectorQueue` (der_loop.py) -> ONE scheduler (`_der_start_node` / `_der_post_step`, module level in agent_kernel.py) starts every ready node on its own thread through the `execution.der_nodes` phase domain (browser/screen claims serialize) -> each node is `node_executor.run_node` (the tool model with NODE_TOOLS, loops until `step_done`, read-only sibling calls side by side) -> `_der_finalize_step` verifies (exit codes, `_node_failed_after_change`), stamps the node record, marks goal coverage, scores the (region, mediator) edge inline, writes commit/links/physics on ordered lanes, then the continuation gate (goal contract met -> no consult; open fact -> cover push; else one consult) -> turn end: synthesis (`_der_synthesize_success_outcome` -> `_synthesize_response`, evidence from `_der_node_record_evidence`, marked `bounded`), run grade, bookkeeping lane. Cross-cutting: one model chokepoint (`InferenceRouter.generate`), one store writer (`db.app_write` -> native iris_core), ordered lanes (`utils/durability_queue.lane`), Caducean physics (rec 0 EXPAND / 1 COMPRESS / 2 CONTINUE / 3 TOPO_VIOLATION; the scheduler never reads live u/xi).

**What the chat receives today (Phase 3 replaces this with one turn protocol):**
- Event bus (`backend/agent/event_bus.py` IRISStreamEvent): agent:start/stop/error, text:response_chunk / text:response_done, utterance:start/chunk/done, document:render, tool:call / tool:result / tool:error, task:start / task:progress / task:milestone / task:done / task:fail / task:learning / task:blocked / task:paused / task:resumed, memory:event, steering:ack, permission:request / granted / denied, question:ask / answered / timeout, browser:takeover_requested, mode:changed, context:usage.
- WebSocket (iris_gateway.py `_handle_chat`, `text_message` branch): `chat_chunk` {chunk, turn_id} streamed for direct replies; on the DER path the reply is produced whole and THEN sent through the same chunk callback (no true streaming - the turn protocol should carry text deltas); `chat_reasoning`; the final message; reconnect buffer `buffer_message`.
- `document:render` (create_artifact) payload: format, content, title, kind, summary, language, document_id (= artifact_id, UUID), card_id (stable per artifact), turn_id, conversation_id, trust, sources, har_path, partial, updated/revision on a new version. Stored in `data/memory.db` table `document_data` (one row per artifact; images in `document_blobs`); an edit overwrites the row and bumps `revision` - NO version history (owner offered a versions table; not decided).
- Frontend today: `components/chat-view.tsx` 5,645 lines (39 useState / 39 useEffect), `hooks/useIRISWebSocket.ts` forwards `document:render` as `iris:document_render`, `chat-view.tsx` ~1478-1580 handles it (title from the event wins), `lib/documentMerge.ts` merges hydrated docs, `components/chat/RichDocument.tsx` renders cards (HTML in `SandboxedHtml`), task card via `useTaskProgress`, matrix concept in `app/cli-preview`. The frontend copy of the failed-search rule (`_isEmptyResultDoc`, chat-view.tsx ~3957) is still there (remove in Phase 3). Bugs the audit expects Phase 3 to close: card-anchor early return, 500-char clamp while streaming, chunk/text/plan events written to the ACTIVE conversation instead of the named one, suggestion pills send without conversation_id, retry fetch inside a state updater, backend errors / live reasoning with no listener.
- Specs to follow: execution-audit.html Phase 3 (DONE: every turn ends with exactly one `turn.end`; an error shows in the chat; replay tests of recorded turns pass in both modes; NOT THIS: a visual redesign in the same change) and Phase 4 (DONE: a developer turn shows the prompt line, a live matrix whose rows appear/run/fold as nodes do, a rendered answer; fits the wing width; `>cmd` shows as an EXEC row; NOT THIS: personal-mode look changes, removing the ANSI export renderer). Reply-surface Phases B-D (compact cards, receipts, page artifacts, developer rows) build on Phase 3.

**Verify first (no regression, supports the backend):**
1. `python -m compileall -q backend`; `npx tsc --noEmit`; jest: `npx jest __tests__/components` (29 suites / 239 tests passed on 2026-10-05).
2. Targeted pytest (never the full suite), each new guard: contract/test_goal_contract_own_terms_contract.py, test_node_evidence_every_call_contract.py, test_node_mediator_contract.py, test_der_dag_seams_contract.py, test_research_prior_dedupe_contract.py, test_reasoning_effort_contract.py, test_api_hidden_reasoning_contract.py, test_api_gateway_retry_contract.py, test_api_hedge_contract.py, test_create_artifact_contract.py, test_create_artifact_tool.py, test_parakeet_prewarm_child_contract.py, test_oracle_calibration_contract.py, test_oracle_enforcement_contract.py.
3. Known failures that ALSO fail on the committed code (do not chase as regressions): test_ct_gc13_failure_path_feeds_learning_hooks, test_bt_gc6 x2, test_der_phase0 x5 (behavioral) + 4 (root copy), test_der_success_synthesizes x2, test_der_t26 ac3 x2, test_der_invariants::test_g1_stub_is_failed, test_partial_artifacts_contract::test_the_der_loop_grafts_the_remainder_after_a_file_step, test_missing_db_unverified, test_voice_command_parakeet::test_transcribe_delegates_when_loaded, test_mode_routing::test_inference_is_shadowed_not_replaced (stale), 10 router/transport tests (context_window_negotiation, phase_gate_present...), the 10 strip_leading_narration whitespace tests listed in commit c2be0c5e, test_iris_core_smoke 9 errors. FLAKY (a finding): behavioral/test_wave5_replay_behavior.py pytest INTERNALERROR in ~15-25% of runs since its Oracle scoring moved to the lane (stub the engine there).
4. Live gate (app-testing skill, Mode A): `bash evals/live/ab_parallel.sh r09_three_facts 3 1` then `... c01_fix_off_by_one,c02_add_slugify,c06_fix_import_error,c10_create_module,r01_python_origin,r06_tokyo_osaka,r07_first_iphone 1 1`; read pass + reply_s. Gates 9-12 were green (see S61-S65). Check for stale gate/waiter processes before and after (Win32_Process: ab_parallel / run_evals / "until grep") - a `nohup ... &` from the Bash tool survives the call.
5. Measurement hygiene: reply time is ~50% the Brain provider (planner + synthesis) and provider stalls of 12-131 s are common (mercury-2.5); compare medians over several runs, never one run.

**Open (not Phase 3/4):** the reply model's reading fault is mitigated (rewrite on contradiction) not gone; facts without a name use own words / passing runs; edge scoring inline (log `[DER] slow step scoring`); `agent_kernel.py` ~22k lines (Phase 5); native access-violation crash needs a Windows crash dump (owner setting); artifact version history (owner decision); Oracle: no consumer worth switching on yet (oracle.md §0.7); screenshot_page_tool emits its own image card; c14 once saw a missing EVAL_WORKDIR (unexplained).

**2026-10-05 (session ae9c2fb9, part 3) - speed, R5, the DAG seams (S58-S61); concept map `docs/architecture/DER_DAG.md`.** Commits 9c880251 4a0391a4. Planner at low hidden reasoning (median 4.17 -> 1.63 s per plan); reasoning-resend floor (the Oracle reference label works again); HTML artifacts sandboxed (R5); five DAG seams closed (DER_DAG.md section 9). Gates 8-9: 25/26 (one c14 flake: its pytest saw a missing EVAL_WORKDIR - workdir deleted before it could be read). End-to-end reply medians are within run noise (n=2 per task); the time split before the change: synthesis 25%, planner 24%, node calls 16%, IRIS 15%, search 10%. OPEN for the owner: hedge after 2 x p75 instead of 2 x p90 (Brain calls: median 3.85 s, normal calls end by ~10 s, 33 of 326 stalled 12-131 s; p90 is pulled up by the stalls, so the hedge waits ~20 s) - the hedge test pins 2 x p90. Phase A DONE (S62, commit c2be0c5e). STOP before Phase 3/4 (owner: the chat-view redesign for both modes needs the owner's go). Open: screenshot_page_tool still emits its own image card; the frontend copy of the failed-search rule (chat-view.tsx) stays until Phase 3; Whisper pre-warm (fallback STT) took 22 min once under disk load - owner question pending.

**2026-10-05 (session ae9c2fb9) - HANDOFF 12 C1 + C4 done: the DAG answers every asked fact (S51-S54).** r09 ten times per gate: 9/10 -> (overlapped run, invalid) -> 8/10 -> 9/10 -> **10/10** on the final code; c02/c06/c10/r01/r06 15/15 across gates 3-5. Four seams, each found by the run before: the goal contract covered a fact on any shared word (and grouped two facts in one); COMPRESS skipped the push for an open fact; the reply evidence cut the middle search of a three-search node out (twice: 8000 then 6000 window); steps added after planning had no node record, so a cover step's result never counted. Node mediator fixed (C4). Replay tools: session scratchpad `replay_now.py` (old vs new coverage over eval replies + stored searches), `rebuild834.py` (rebuild a node's reply evidence from document_data). The three OPEN items of this note are DONE (S55-S57, gate 6: 14/15, the one fail a provider 503 on a node). Speed, clean gates vs 2026-10-04: r09 reply median 23.2 -> 20.2 s, p90 69.6 -> 36.0 s; c02 18 s, c06 29 s, c10 13 s, c14 20 s (standards 53 / 64 / 16 / 24 s). 5xx retry widened to the third attempt (1 s, 3 s; owner-approved test change, commit 4db34e2f). OPEN: the reply model sometimes writes "not included" for facts that ARE in its evidence (r09 conv-834, conv-884: 2 of 25 final-code runs; the rebuilt evidence holds "330 metres" and "May 28, 1937" in the NEW results). Suspects: the cross-check label `not_rechecked` reads like "not checked", and raw page tables bury the answer; candidate fix: a short deterministic KEY LINES head per required fact (sentences holding the fact's name + a number) - measure first.

**2026-10-04 (session 8161c922, part 3) - mode parity: the gaps were IRIS-side costs (S36-S40).** Commits 7318bebe 27dc532b 3ad1906e. A controlled series showed the MODE made no difference (developer+cli 34/58 s, developer+chat 202/76, personal+chat 166/263); splitting each turn into model wait / tool wait / IRIS time found the IRIS-side costs: a rate ceiling stuck at the 30 rpm guess (slow start, S37), a page digest of menus that sent the blind model to a screenshot reader that misread facts (S38), a loop guard that remembered calls across turns (S39), and node evidence cut to 400 chars before the synthesis (S40). After: 8/8 runs 16-30 s, 8/8 correct, IRIS time 1.6-4.6 s. Mojibake: 0 left in backend/. OPEN, by priority: (1) the DAG executes serially - planned steps are goal-only (tool=None) and `is_parallel_safe(None)` is False, and the concurrent executor runs fixed tools, not nodes, so independent branches never run side by side (design decision pending: which node pairs may overlap - one browser page and one workdir per conversation are shared resources); (2) DB lock waits in `_der_finalize_step` (record_commit, pin_store.link inline; 0-3 lock lines per run now) - moving them to a lane changes when existing tests can see the rows (report before changing); (3) goal-contract any-word coverage; (4) step creep (bounded by S31); (5) the 36 s dispatch tail seen once.

**2026-10-04 (session 8161c922, part 2) - node bound, mode parity, UI model load (S31-S35).** Commits d0482b49 f912de74 a2f45492. Owner asked: nodes are one step now (no 300 s wander), personal 58 s is the standard and developer must not be slower, a model loaded from the UI must behave and report like the test loads. Developer vs personal had NO developer-only cost in code: the gaps were shared causes that hit whichever run came first - the Whisper warm-up import (torch+transformers via ctranslate2 converters, ~19 min cold; then ~7.5 min after a sleep), a cold first page open, a stale element mark, a section toggle sent to the user, DB lock waits in the step close, provider stalls. Live after the fixes (Kilimanjaro, mercury Brain+tool): personal 77 / 96 s correct, 32 s and 72 s WRONG (no facts / "5,510 m"); developer 146 / 183 s correct. The 58 s standard is NOT met yet. OPEN, by priority: (1) answer quality - two wrong browser answers in 8 runs (vision readings are now logged with 200 chars to find the source); (2) DB lock waits on the answer path - `record_commit` and `pin_store.link` inside `_der_finalize_step` waited ~16 s together in one run, 715 lock lines in 400 MB of log (writers outside lanes); (3) goal-contract coverage matches ANY one word of a fact (C=0.667 after only the homepage opened) - it cannot be the stop signal for remaining steps until it is strict; (4) dispatcher tail - one browser_open returned after 30 s but dispatch reported 66.6 s (stack dumps showed `<freed thread state>`, Python 3.14 faulthandler gaps); (5) step creep - a node given the whole request often does the whole request in step 1 (bounded now by S31; a "context only" prompt was tried and reverted: no measured gain); (6) iris_gateway.py has 164 mojibake sequences (one user-facing fixed). MCM was unreachable for the pins of this part - record from this note.

**2026-10-03 (session 8161c922) - nodes in every mode (V10) + DSpark pairing (S29, S30).** A step with no tool now runs as a node in personal mode too (owner: nodes are universal); the one-tool decision path is deleted; node calls get the direct step's bookkeeping (a node web call saved no sources before). DSpark drafters pair with their base at load (2.6B +58%, VL-3B +20%; the 8B MoE is slower and is not paired). Four old tests that pinned the one-tool path were retargeted to the node (owner-approved). OPEN: D1 first goto 45 s seen again on a cold browser; `database is locked` is pervasive (715 lines in 400 MB of log before this session); a node can wander inside its step (personal run 1: links clicked for 300 s). Pin: MCM `pin_6726baee4d0e`; landmarks `lm_d64ffeac2cbd09eb` (nodes-every-mode-live), `lm_baf545e8c76e5306` (dspark-drafter-pairing-live).

**NEXT AGENT: read MCM `pin_46a134ca8617` (HANDOFF 12) FIRST** - it supersedes HANDOFF 11. Done 2026-10-04/05 (session 9f5a1d93, S41-S50): one native writer for data/memory.db, parallel DAG scheduler + natural split of a node's sibling calls, the slowdown fixed (audit lock, provider hedge, per-thread reads, targeted flushes). NEXT in order: (1) accuracy - DONE 2026-10-05 (S51-S53, r09 10/10); (2) the native access-violation crash; (3) the measured speed budget (planner 5.1 s, synthesis 3.6 s, node calls, ~4 s IRIS per turn); (4) the node mediator - DONE (S54).

**Previous: read MCM `pin_f857f6d9f60c` (HANDOFF 11)** - it supersedes HANDOFF 10. PRIORITY 1 (owner 2026-10-04): universal parallel execution of independent DAG nodes - deep dive on the method first, then build; validate the wiring to grafts, split sub-loops and mediators (`_der_mediator_for` still reads item.tool, so node steps get mediator "none").

**Previous: read MCM `pin_d718e7a76b92` (HANDOFF 10)** - it supersedes HANDOFF 9 + its addendum for the order of work (run scripts: `evals/live/`).

**2026-10-03 (session 6f7c200a) — Phase B1 done + browser speed (S25-S28).** B1 V2-V9, V12 fixed and live (`73690b69` `f1191d85` `bd48d513` `72cfe109`; landmark `lm_5e98e365e033c7c6` browser-vision-fallback-live: the local LFM2.5-VL-3B autoloads as the fallback and reads screenshots 2.7-3.2 s). Rotorquant removed (`d18345ff`). The same Kilimanjaro browser task went 474 s (A) -> 522 (A3) -> 138 (A5) -> **95 s (A9)**, correct every time (logs `logs/live_b1_A*_dev.log`). Interactive maps replace the web/browser MDs: `docs/architecture/web-browser-architecture.html`, `oracle.html` (serve the folder: `.claude/launch.json` `arch-docs`). OPEN: the first navigation inside the backend sometimes waits the full 45 s (A6/A7) while the same goto standalone takes 0.4-2.1 s - the call log is now logged (600 chars); the cause of a mid-task page close (A5) is now logged (`page CLOSED/CRASHED`); live run B (Ternary-Bonsai with its own vision); rename `lfm_vl_provider.py`; DSpark draft pairing; V10/V11/V14/V15. Recorded in MCM: landmark `lm_d0c3da0ba242a2f6` (browser-task-speed-live), HANDOFF 10 `pin_d718e7a76b92`.

**NEXT AGENT: read MCM `pin_12c36422de28` (HANDOFF 9) FIRST** - it supersedes HANDOFF 8's order of
work: re-measure all 15 coding tasks x 2 setups (API tool / local TwIL tool) with model + tool call
counts and system vs provider time; system-side speed; C6 model-call stall bound; unify the Inference
Console into Monitor (and feed it from the router); c14; then H8 C4-C10; vision/browser addendum.
**ALSO READ the addendum `pin_7125f6739038` (browser control + vision, 2026-10-02)** and the audit
addendum (`execution-audit.html`, section "Addendum 2026-10-02 · Browser control and vision", rows
V1-V15). Owner goal: the user never needs another browser - IRIS ships one. Two live browser runs
failed and the vision model took no part. Fixed: V1 restore crash + V13 window cap (`289d2ce0`),
browser tools in developer nodes / web toggle the only gate (`35c315bd`). Fix order for Phase B1:
V2 V3 V4 (vision discovery: local server excluded, false 'can see' probe, paid probing) -> V5 V6 V7
(one resolver + auto-load driven by the fallback ladder, owner decision) -> V9 (API vision from
provider metadata) -> V8 (vision in the browser loop) -> V12 (replan relevance gate); then live runs
(mercury + local LFM2.5-VL-3B fallback; Ternary-Bonsai-2-27B with its own vision) and a browser eval
group with a standard. Phase B2 (the experience: live screencast by default, shared wheel, plan on
the page, action timeline, Oracle browser_next/web_depth, persistent profile, warm Chromium) and
V10 (= C4 one engine) / V11 / V14 / V15 follow. How the next agent orders this against HANDOFF 9 C:
C1 re-measure first (it decides what costs most), then B1, then the rest by measured cost.

**Previous: NEXT AGENT: read MCM `pin_21357eeec9fc` (HANDOFF 8) FIRST** - it supersedes HANDOFF 7's order
of work: Brain calls cut (S19), turn-end bookkeeping off the reply path (S20), the local TOOL MODEL
now runs node calls with a Brain helper, node/step audit fixes, new providers (OpenRouter, Inception
Labs, NVIDIA), startup findings (owner actions: Defender exclusions + D: NVMe). Open, in order:
~~idempotency/DUPLICATE write_file on c04~~ DONE 2026-10-02 (S21: the guards ignored file changes
between identical calls; c04 6/13 -> 11/13 hidden, 617 -> 242 s; the last 2 are the tool model's
code), work after the reply ([AMEND]), full eval C + standard. Setup note: `evals/load_tool_model.py`
now holds its socket until the model reports "loaded" (it closed at port-open, so the model was
never registered); never `unload_local_model` before an eval - the tool role falls back to the
first API provider (Cerebras, bad key: every node call 401) and a reload does not rebind it.
**2026-10-02 later (same session, commits b007b591..014fb028, local only):** C2 DONE (S22). API
tool model parity (owner: no regression with an API tool model) - S23. Agent commands - S24 (owner
approved: one process per command, Git Bash if installed, 5xx retry, shell-syntax count in
run_evals; stall early return + workspace Live commands panel with Stop). API-only coding run
(Brain mercury-2.5 + tool mercury-2, `20261002-151234`): 13/13 recorded, c14 FAIL (missing pattern
"3 fail" in its reply - not yet looked at), but 8 reply_s regressions: 4 x 300 s command hangs (S24
fixes), 2 x 504 (retry added), 11 provider read-timeout stalls of 60 s each (NEXT: per-model stall
bound for model calls = HANDOFF 8 C6). OpenRouter free tier = 50 requests/day (used up; resets
00:00 UTC); NVIDIA 26-228 s per call (unusable for evals). NEXT, in order: re-run c02/c03/c09/c11
with S24 loaded; C6 model-call stall bound; c14; full eval C (local TwIL tool) + record standards
per setup; then H8 C4-C10. Separate task offered: dashboard load sends ~36 config/save (some 500).

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
| S21 | the dispatcher's repeat guard, idempotency cache and permanent-replay guard treat a call as a repeat only if NO file changed since the identical call; the cache stores successes only | c04 (TwIL tool model, conv-622): 22 test runs + 36 writes blocked "Duplicate call ... loop detected" after real edits, 6/13 hidden, reply 617 s -> 0 blocks, 11/13 hidden, reply 242 s (`20261002-131032`); the 2 left are code gaps (`"h"`, `"1h1h"` not rejected), not blocks | `ToolDecisionBox._change_epoch` (bumped by a successful `_FILE_CHANGE_TOOLS` call) is part of every guard key; the call that bumps it is re-stamped so a back-to-back retry still matches | `contract/test_dispatch_repeat_after_change_contract.py` (2/3 fail on the old code) |
| S22 | a node does no work after its turn ends (reply sent, budget or user stop) | c04 conv-622: a recovery node made model + tool calls for 3 min after the 600 s reply, into the next task -> live 2026-10-02: `[run_node] ... turn ended ... no more work` right after a budget reply | `_der_run_node._turn_live()` before every node model call and tool call (`_der_turn_active`, same `_der_turn_id`, not `_der_stop_requested`) | `contract/test_node_stops_when_turn_ends_contract.py` (4/5 fail on the old code) |
| S23 | an API model gets its real window, keeps its node history, and has room for hidden reasoning | API tool/Brain (NVIDIA/OpenRouter/Inception): window 8192 default -> prompt budget 256 -> every API node call = system + last message (`budget=256`, up to 14 dropped), Brain "read_file returned no content"; mercury-2.5 at max_tokens=1024 cut by 818-979 hidden reasoning tokens. After: c02 nemotron+mercury FAIL 75 s -> PASS 22 s; API-only coding run 13/13 (`20261002-151234`) | `provider_catalog.prefetch_api_windows` (GET /models context_length, prefetched at startup + bind, lookup reads cache only); router answer reserve <= window/2; `ApiHttpxTransport._reasoning_headroom` + one resend on a reasoning cut; one retry on a gateway 502/503/504 | `contract/test_api_context_window_contract.py`, `test_node_history_fits_window_contract.py`, `test_api_hidden_reasoning_contract.py`, `test_api_gateway_retry_contract.py` |
| S24 | an agent command never holds the agent blind: own process, empty closed stdin, non-interactive env; no output AND no CPU for 30 s returns a handle; every end keeps its output | c02 `python - <<'PY'` ate the session shell's completion marker: 2 x 300 s hangs (566 s of a 636 s reply) -> live 2026-10-02: `python server.py` running -> waiting at 35 s -> agent stop_command at 36 s, correct reply | `SubprocessManager.run_isolated` (Git Bash if installed, else PowerShell; psutil tree CPU), `read_command_output` / `stop_command`, `agent_command` events, workspace Live commands panel + user Stop (`agent_command_stop`) | `contract/test_agent_command_isolated_contract.py`, `test_agent_command_stall_contract.py` (stall, busy not cut, timeout keeps output, env, git editor, user stop) |
| S25 | a browser task's first page opens in seconds: web ON prewarms Chromium + keyring and holds one spare context+page; the launch is one shared task no caller's bound can cancel; the dispatcher never cuts a browser tool before its own ceiling | Kilimanjaro task (developer mode, mercury Brain+tool): first `browser_open` 180 s (two 90 s cut-offs, run A3) -> 4.4 s (`spare=True`, page 0 ms, A5/A9); keyring import 9.5 s on the browser loop -> off-loop | `browser_pool` `_launch_task` / `set_web_hold` / `take_spare_page`, `browser_session` keyring `to_thread`, `DEADLINE_BROWSER_S` 150 | `contract/test_browser_launch_never_cancelled_contract.py` (5) |
| S26 | a hosted model call far past its normal time is cut and retried once; the per-model profile survives a restart | mercury-2 node call 121 s (A3) / Inception 120 s hold + 504 (A6) -> cut at max(30 s, 4 x p90), retried (A5, A8: 30 s) | `ApiHttpxTransport._nonstream` first-attempt read = `stall_bound()`; `data/model_call_times.json` via `lane("model_call_times")` | `contract/test_api_stall_bound_contract.py` |
| S27 | an open or a page-changing act returns the element list; a closed page is not a live session; only the call that starts a vision probe waits for it | A8: 51 tool / 55 model calls, 283 s -> A9: 8 / 13, 95 s, same correct answer | `browser_tools._with_observation`, `BrowserSession.available()`, `_vision_live` | `contract/test_browser_liveness_contract.py` (3) |
| S28 | a met goal contract ends the run: no continuation consult, no streak-gate re-plan, the success path answers (even after a failed attempt), a short factual answer is not a stub | A5: 46 s after C=1.000; A4 correct 101-char answer replaced by the step dump; A6 crash after a post-goal re-plan; A7 failure template with the facts in hand -> A9 `continuation consult skipped - the goal contract is met`, clean answer | `AgentKernel._goal_contract_met` at the continuation gate, `_der_streak_gate`, the Phase 1.5 failure branch; stub floor 40 chars + digit rule | `contract/test_goal_met_skips_consult_contract.py` (6), `behavioral/test_der_success_synthesizes.py::test_a_short_factual_answer_is_an_answer_not_a_stub` |
| S29 | a step with no tool runs as a node in BOTH modes (V10): one node menu (`NODE_TOOLS`; screen tools only for a screen goal), the mode's capability filter stays in the bridge list; every node call gets the per-call bookkeeping a direct step gets (external mark, browser warm, crawl budget, ToolCallTree, result capture) and verification reads the node's decisive call | personal mode ran one tool per step (no retry of a failed call, no page screenshot to a model); node web calls saved no sources and verified by assertion, not content -> live 2026-10-03, Kilimanjaro task, mercury Brain+tool: personal 58 s correct (run 1: 600 s budget, cold first goto 81 s = D1 + a node that clicked links for 300 s), developer 226 s correct | `_der_run_step_execution` (gate removed, one-tool box block deleted), `_der_before_call` / `_der_after_call`, `_step_tool(item)` at verify | `contract/test_node_every_mode_contract.py` (fails on the old code), `behavioral/test_websearch_without_encoder.py` (retargeted to the node; fails without `_der_after_call` in the node) |
| S30 | a DSpark drafter (arch `dflash`) is never a model: it is paired with the dense base it names (`general.base_model.0.name`) and loads with it (`-md --spec-type draft-dspark`); its VRAM (file + 0.6 GB) is reserved and it is dropped first when the card is short; MoE bases are not paired | standalone (prismml server, RTX 3070, greedy, 3 prompts x 256 tok): LFM2.5-2.6B 164 -> 259 tok/s (+58%, acceptance 0.70), LFM2.5-VL-3B + mmproj 150 -> 181-187 (+20-24%, 0.57), LFM2.5-8B-A1B 194 -> 182 (-6%, not paired); VRAM +800 / +1128 MiB at 8k ctx; live: the vision autoload started VL-3B with mmproj + drafter (`speculative decoding enabled: draft-dspark`), ~190 tok/s | `LocalModelManager._attach_drafter`, `_find_drafter_for_model`, `load_model` (reserve, drop-first, refuse a drafter), `_build_server_cmd(draft_path=)` | `contract/test_dspark_pairing_contract.py` (4, all fail on the old code) |
| S31 | a node is one step: it stops at 12 tool calls (p99 of 1,334 successful nodes; 93% use <= 5) and says whether its step is met; the Brain helper engages when the tool model is a different MODEL even on the same provider | a browser node clicked through linked articles for its whole 300 s budget (~22 calls) -> bounded to 12 calls (~30-60 s); helper compared provider ids only (mercury-2.5 + mercury-2 = one id) | `NodeContext.max_calls`, `_der_run_node` helper (id, model) | `contract/test_node_step_bound_contract.py`, `test_node_every_mode_contract.py::test_the_brain_helps_a_tool_model_on_the_same_provider` |
| S32 | the Whisper warm-up never imports torch/transformers and never holds a turn: ctranslate2 conversion modules are stubbed; a low-priority child reads the files first | ~19 min cold import (stack dumps 2026-10-03 11:04-11:23) over two live turns; after a sleep ~7.5 min with Oracle decisions waiting 34-38 s -> 2.9 s warm, child-isolated | `VoiceCommandHandler._get_whisper` stubs, `prewarm_files`, `main._delayed_whisper_warm_up` | `contract/test_whisper_import_skips_converters_contract.py`, `test_whisper_prewarm_child_contract.py` |
| S33 | a cold first page open uses the spare page in flight; a click that rebuilds its field types in the focused field; a section toggle is a safe click | first open after a cold start 56 s -> 17 s (spare used, nav 8.8 s; warm 0.8-1.8 s); select-before-type waited 30 s (act 40 s) -> 1.5 s bound; a Wikipedia toggle waited 53 s for the user -> rule | `browser_pool.take_spare_page`, `BrowserSession._perform`, `click_safety._DISCLOSE_LABEL` | `contract/test_browser_open_waits_for_spare_contract.py`, `test_browser_type_rebuilt_field_contract.py`, `test_click_safety_disclosure_contract.py` |
| S34 | a UI model load reports the truth: one rising %, the real ctx/vision/draft in the pre-flight message, the status tick carries the local slot (panel rescans on change), cards plan the load's context and count the resident model as free, a clip projector is never a model | UI load of LFM2.5-2.6B: % 18 -> 5 -> 12; card "8k ctx" for a 32768 load; VL-3B autoload invisible until rescan; Ternary mmproj listed with a Load button -> live 2026-10-04: 0..100 rising, "VRAM check passed - 32768 ctx + DSpark draft", tick n_ctx 32768 draft_loaded | `_rising_progress`, `plan_load`, `status_snapshot.local_model`, `ModelBrowserPanel` reconcile + draft tag, scan `clip` rule | `contract/test_model_load_reporting_contract.py` (5) |
| S35 | a DSpark drafter never costs context: it loads only when it fits at the full config, else it is dropped before any ladder cut; its reserve grows with n_ctx (+800 MiB at 8k, +1040 MiB at 32k measured) | the drafter's reserve cut the tool model n_ctx 32768 -> 8192 on a UI load -> 32768 + drafter | `LocalModelManager.draft_reserve_gb`, `load_model` draft check | `contract/test_dspark_never_costs_context_contract.py` (3) |
| S36 | developer and personal turns take the same time: the mode changes nothing on the turn path; measured as span = model wait + tool wait + IRIS time (`[InferenceRouter] call done` lines + TOOL_DISPATCH, interval union) | Kilimanjaro browser task, mercury Brain+tool, same backend: before 34-263 s (dev+cli 34/58, dev+chat 202/76, personal+chat 166/263), IRIS time up to 100 s -> after 16-30 s in all 8 runs, 8/8 correct, IRIS time 1.6-4.6 s (the 58 s standard is now ~20 s) | S37-S40 below | `unit/test_ceiling_slow_start.py`, `contract/test_observe_digest_main_content_contract.py`, `test_dispatch_repeat_per_turn_contract.py`, `test_node_evidence_window_contract.py` |
| S37 | an unknown provider limit is not a 30 rpm limit: slow start doubles the ceiling when reached without a 429; after a 429 AIMD as before; the hard rail caps it | 31 of 42 calls held 2 s (55 s of a 166 s turn), no 429 in any run -> gate waits 0.5-4 s per turn | `ProviderRateMeter.record_request` slow start, `ProviderWindow.learned` | `unit/test_ceiling_slow_start.py` (fails on the old meter) |
| S38 | browser_observe's text digest is the page's MAIN content (1500 chars) | Wikipedia digest was header+menus; 12-14 screenshot readings a turn with misreads ("The infobox height is 250.") -> 0-2 readings; the infobox facts are in the digest | `_OBSERVE_JS` digest | `contract/test_observe_digest_main_content_contract.py` (real Chromium; fails on the old script) |
| S39 | the dispatcher loop guard lives in one turn; browser tools are exempt (run_node's detector stops a real loop) | "Duplicate call to 'browser_open' ... loop detected" in 4 of 6 consecutive turns -> 0 | `ToolDecisionBox.dispatch` (`_last_call_turn`, `_IDEMPOTENT_READ_TOOLS`) | `contract/test_dispatch_repeat_per_turn_contract.py` (2 of 3 fail on the old code) |
| S40 | a node step's evidence (later steps, window, synthesis) keeps what it read | node steps got the 400-char by-tool default (item.tool is None): the facts after the summary were cut, the reply said they were missing -> read/gather window | `_step_evidence_cap(item)` | `contract/test_node_evidence_window_contract.py` (fails with the old cap) |
| S41 | a node step that gathered (search/fetch/read inside the node) gives the SYNTHESIS its results, not the 300-char record summary - the gather check reads `_step_calls(item)`, not `item.tool` | r01/r06/r07 0/3 on 2026-10-04 ("the results did not return the figures", synthesis prompt 1668 chars; 8/8 on 2026-10-01, before V10 made every step a node) -> 3/3, reply 12/42/13 s | `AgentKernel._der_node_record_evidence` | `contract/test_der_t26_synthesis_diet_contract.py::test_ac1_node_step_that_gathered_keeps_its_results` (fails on the old code) |
| S42 | the per-step commit and link writes never hold the answer path: `_der_finalize_step` submits record_commit and der_links.write_node_links to lane("memory_events") (state read at finalize, row written after) | r06 2026-10-04: a 22 s gap with no model/tool call in a 42 s reply (stack: write_node_links -> PinStore.link on 'database is locked') -> no lock gap in finalize on the re-run (r06 time now = model wait). Still inline and failing on the lock: record_fan_trace, trajectory record, episode store, research_memory chain append (8 lock failures in 5 tasks) | `_der_finalize_step`, `_der_handle_step_failure` | `contract/test_der_finalize_writes_off_answer_path_contract.py` (fails on the old code) |
| S43 | ONE WRITER for data/memory.db: the native core's writer thread owns the file; Python writers call `backend/memory/db.py app_write` (queued, group-committed, the caller never waits). Moved: trajectory rows, fan traces, commits, session exits, memory events + cases, pin links, episodes, context chunks, chain rows, system events, document evict. A value computed from the store (chain sequence, evict excess) is computed INSIDE the SQL on the writer thread | 5 eval tasks: 8 'database is locked' -> 0; native write failures 0; r06 reply 42-44 s -> 13 s, c11 123 s -> 34 s, 5/5 pass. Bench: caller 522 -> 7.4 us/write; 4 concurrent writers 283 s + 50 lock errors -> 0.05 s + 0 | `iris_core` DBManager::submit_write + group commit, `db_submit_write`; `iris_ffi.ffi_native_write`; `db.app_write` | `contract/test_one_writer_contract.py` (locked store never blocks a write; order; every type round-trips; queued chain appends take distinct sequences - fails on read-MAX-then-insert) |
| S44 | NO production code writes the app store outside `db.app_write` (reviewed exceptions listed with reasons); a side lane reads on its OWN connection; only a reader that decides on a row it just wrote flushes the queue | scan: 101 direct writes -> 0; c03 answer path waited 4+ s on the shared mycelium connection behind the memory lane's full-table LIKE, and 1.6 s on a recall flush -> neither | `db.app_write`, `db.lane_connection`, `memory_events._RECALL_DONE_SQL` | `contract/test_app_store_one_writer_scan_contract.py`, `contract/test_memory_lane_reads_contract.py` (both fail on the old code) |
| S45 | one audit logger serves every event loop: its lock is a THREAD lock (parallel nodes each run tool calls under their own asyncio.run) | c03 with two parallel nodes: edit_file/read_file CRASHED ('bound to a different event loop') + a 60 s hung read -> 0 crashes over 30 tasks | `SecurityAuditLogger._lock` | `contract/test_audit_logger_many_loops_contract.py` (fails with the live error on the old code) |
| S46 | a stalled provider request is hedged: no answer after max(3 s, 2 x p90) -> the same request again, first answer wins (stall bound + retry still behind it) | 12 of 148 mercury-2.5 calls >= 30 s (stall then a ~3 s answer); r06 lost 60 s of 88 s -> 0 stalls in 20 tasks | `transport._post_hedged`, `hedge_delay` | `contract/test_api_hedge_contract.py` (with hedging off it waits 20 s and fails) |
| S47 | ONE scheduler for every DER node: the DAG decides WHAT is ready, the `execution.der_nodes` phase domain WHEN; independent nodes overlap, a dependent never; browser/screen nodes take turns; a split parent waits for its children and the first VERIFIED child completes it (siblings stop); `IRIS_DER_PARALLEL=0` = one node at a time | 5 eval tasks x2 after the fixes: 10/10 pass, times at parity with the serial build (plans were chains); the parallel gain needs plans that branch - the planner chose 1 step in 6 of 8 three-fact runs (open) | `_execute_plan_der` loop, `_der_start_node`/`_der_post_step`/`_der_settle_split`, `DirectorQueue.split_pending`, `_plan_step_deps` | `contract/test_parallel_nodes_contract.py` (overlap / chain / browser / race x2 / stop; fails on the serial loop) |
| S48 | a read never waits behind another thread's statement: when the native writer owns the store, `AppStoreConnection.execute` runs SELECT/WITH on the CALLING thread's own connection; a document read waits for the writer queue only when this store queued the document it needs | a node waited 16 s on the shared episodic connection behind a 56k-chunk recall scan; `document_store.get` flushed 34x / 149 s (max 14.4 s) on the answer path -> 0 such waits in 24 tasks | `db.AppStoreConnection.execute`, `db.lane_connection`, `DocumentDataStore._settle/_note_pending` | `contract/test_one_writer_contract.py::test_a_read_never_waits_behind_another_threads_statement` (old: waited 2.04 s) |
| S49 | the one writer stays fast: no checkpoint inside a commit (PASSIVE checkpoint when idle >= 30 s, forced after 120 s); slow statements / begins / commits / checkpoints are logged; episode rows are bounded (newest 20k chars); the document evict uses a `created_at` index (created through the writer) and trims to 90% of the cap | group commits 0.8-1.4 s, evict DELETE 2.6-5.5 s, an episode row at 321 KB rewritten in 1.9 s, `ensure_table failed: database is locked` -> stress 70 s -> 25 s per 23k-write round, 0 failures | `DBManager::run_writer_loop`, `episodic.store`, `DocumentDataStore._ensure_table/_evict_if_needed` | native tests 52 pass / 9 pre-existing errors; `[DB] slow ...` lines in the backend log are the live guard |
| S50 | the calls ONE node answer asks for are siblings: when every one is read-only (permission tier) and drives no exclusive resource, they run side by side and settle in the model's order; the gateway never waits on the browser warm-up | a one-step three-fact node ran its searches 2.5 + 3.6 + 3.3 s in a row; one web toggle held the gateway 48 s -> siblings overlap (contract), toggle returns at once. Final interleaved A/B, 6 tasks x 2: parallel 284 s vs serial 353 s total (24/24 pass; without one serial IRIS outlier: parity) | `node_executor._prefetch_siblings`, `agent_kernel._node_call_parallel_ok`, gateway `set_web_mode` | `contract/test_node_sibling_calls_contract.py` |
| S51 | the goal contract covers a fact by its OWN NAME as whole words ("Golden Gate Bridge"); a list after a colon lead-in is one fact per item (commas inside a call or a quote do not split); paths, quotes and code identifiers are not names; a fact with no name keeps the any-word rule | r09: one Eiffel Tower search covered all 3 facts via "year" / a PRIOR RESEARCH block ("first", "published", "Gate", "Bridge"); replay over 204 stored single-topic searches: old rule covered >1 fact in 204, new in 1 (a multi-topic query); coding replies at parity | `goal_contract.extract_required`, `_names_in`, `mark_coverage` | `contract/test_goal_contract_own_terms_contract.py` (fails on the old code) |
| S52 | an open required fact gets a step even in COMPRESS (rec=1): the push is fixed text, no consult; every settled step gets a node record at finalize, so steps added after planning (continuation, recovery, replans, grafts) count for coverage | conv-733: C read 1.0, rec=1 skipped the consult, 2 facts never searched; conv-836: the cover step searched the fact, it stayed open, 2 pushes, BLOCKED -> one push covers it (gate 5: 0 blocked) | `_goal_contract_cover_step`, continuation gate, `_der_finalize_step` record | same test file (`test_compress_does_not_skip_an_open_fact`, `test_a_step_added_after_planning_still_marks_coverage`) |
| S53 | each call of a closing node answer keeps its head (`NODE_BLOCK_HEAD` 2500, share = 8000 / n); the node evidence window grows per call; the synthesis prompt does not cut DER evidence a second time | conv-810/820: three searches, C=1.0, the reply said two facts were missing (one 8000 head+tail window, then a 6000 one, cut the middle search out) | `node_executor` closing answer, `_step_evidence_cap`, `TaskContext.get_results_summary` (`bounded`) | `contract/test_node_evidence_every_call_contract.py` (old: "1937" cut) |
| S54 | a node step's mediator is its decisive call (`tool:args_hash`), not "none"; REQ-23/REQ-26 edge scoring now runs for node steps | every node step recorded mediator "none" -> no (region, mediator) edge ever learned from node work | `_der_mediator_for` | `contract/test_node_mediator_contract.py` |
| S55 | PRIOR RESEARCH lists each earlier finding once (records deduped by body at recall); the reply writer treats a fact found only in PRIOR RESEARCH as a result with its date, not as missing | r09 conv-834: one prior line printed 3x above the new results, reply "the search did not return the height or the year" -> gate 6 0 such replies | `research_memory.recall_prior_research`, `_record_body`, synthesis prompt line | `contract/test_research_prior_dedupe_contract.py` (fails on the old code) |
| S56 | a fact without a name is covered by one of its OWN words (a word another fact holds cannot cover it), or by a passing run of the code / tests after the step's last file change | own words alone left a c10 spec fact open live (2 pushes, reply 15 -> 47 s); the any-word rule let "year" cover two facts -> gate 6: 0 pushes on 6 coding tasks, c10 11 s | `goal_contract.mark_coverage`, `_checked_after_change` | `contract/test_goal_contract_own_terms_contract.py` (nameless + passing-run tests) |
| S57 | per-step edge scoring stays INLINE (the next step decides on its edges / miss episode) and logs `[DER] slow step scoring` above 0.25 s | node steps score since S54; gates 4-6: 0 slow lines, 0 flush waits | `_der_finalize_step` scoring call | the log line is the live guard |
| S58 | the planner asks for LOW hidden reasoning (`reasoning_effort="low"`, sent only to providers that take it: inceptionlabs) | planner call median 4.17 s (74 calls) -> 1.63 s (29 calls), tokens per plan ~3,050 -> ~2,120; offline 6/6 valid plans | `_plan_task`, router `reasoning_effort` pass-through, `_REASONING_EFFORT_PROVIDERS` | `contract/test_reasoning_effort_contract.py` |
| S59 | a reasoning-cut answer is resent with at least 1,024 more tokens; a provider 5xx is retried to the third attempt (1 s, 3 s; owner-approved test change) | Oracle Brain reference (16 tokens) cut at 15, resent at 46, 19/19 lost -> 0 lost in gates 8-9; 11 of 24 single 5xx retries failed again | transport `_REASONING_RESEND_FLOOR`, 5xx branch | `test_api_hidden_reasoning_contract.py::test_a_tiny_call_cut_by_reasoning_gets_real_room`, `test_api_gateway_retry_contract.py` |
| S60 | every HTML artifact renders in a sandboxed iframe (no same-origin; web HTML sanitized + no scripts; agent HTML scripts isolated; injected CSP: no network/forms/navigation) - reply-surface R5 | agent HTML was injected raw into the app DOM (inline handlers ran with the app's origin) | `RichDocument.tsx` `SandboxedHtml` | `__tests__/components/html-artifact-sandbox.test.tsx` |
| S61 | the DAG seams: a node that changed files and whose last run after it failed is UNVERIFIED; node failures reach the failure router and the missing-artifact graft (project folder, queued steps respected); facts map to the planner step that names them; a reply that calls a covered fact missing is written once more; dead semaphore executor deleted | gate 9 13/13 (c01 c02 c06 c10 c14 c15 r01 r06, r09 x5) | `_node_failed_after_change`, `_der_route_step_failure`, `_der_graft_missing_artifacts`, `map_to_steps`, `_claims_missing` | `contract/test_der_dag_seams_contract.py` |
| S62 | ONE door to a card: `create_artifact(title, kind, summary, content, language?, artifact_id?)` on the real document store; `{speak, show}` converts to it; the demotion, fallback mint, failed-search demotion, web-format question and `render_document` are gone; the prompt states the 4-line rule (reply-surface Phase A) | five rules decided "text or card" and the prompt contradicted two; `render_document` crashed / its revise path called methods that never existed; `update_document` read a missing attribute (every revision minted a second card) -> gate 10 10/10 | `AgentKernel.create_artifact`, `DocumentDataStore` title/kind/summary/language, `[RESPONSE FORMAT]` | `contract/test_create_artifact_contract.py`, `contract/test_create_artifact_tool.py` |
| S63 | the hedge goes out after max(3 s, 2 x p75) of the model's recent calls, not 2 x p90 (owner-approved) | stalls fed p90: the hedge fired at 34.6 s / 39.0 s on 37-53 s Brain stalls; p75 ~5 s is not moved by the stall tail -> hedge at ~10 s | transport `hedge_delay`, `_HEDGE_QUANTILE` | `contract/test_api_hedge_contract.py` (fails on the old rule) |
| S64 | the Oracle measures honestly: yes/no rows carry the confidence in the CHOSEN answer (max(p,1-p)) and the raw `probability`; reports and fits count DISTINCT rows; every consumer has its own isotonic calibration + fitted threshold (precision >= 0.90, Wilson LB >= 0.85, >= 50 rows above, 5-fold out-of-fold); the bar needs >= 100 distinct rows, two classes, AUROC >= 0.65, calibrated ECE <= 0.05 | inverted AUROC (web_intent 0.218, escalate_incomplete 0.003); 10,308 of 18,467 rows were repeats; one hand-set threshold 0.40 for all; no calibration -> only narration earns the bar (AUROC 0.78, precision 0.905) | `oracle_calibration.py`, `scripts/fit_oracle_calibration.py`, `consumer_bar.derive_status`, `benchmarks/oracle_calibration.json` | `contract/test_oracle_calibration_contract.py` |
| S65 | ONE chokepoint `decision_engine.decides()`: a consumer decides only when the owner switched it on (`IRIS_DECISION_ENFORCE`, default EMPTY) AND its bar record says enforced AND a threshold was fitted AND the config is not stale; every deciding site goes through it; every non-deciding Oracle call runs on the `oracle_shadow` lane; on_track / has_gaps removed | web_intent decided unearned at 0.8 (precision 0.41), recovery_strategy / depth_met (private tau) / tool_choice ('enforced at birth') likewise; earned consumers had no path; median 3.8 s/turn of Oracle on the reply path, narration on the asyncio loop 3.6x/turn -> gate 12: 0 Oracle calls on the event loop, narration and web_intent once per turn, 'deciding=none' logged, 10/10 pass | `decides`, `oracle_acts`, `enforced_consumers` (intersection) | `contract/test_oracle_enforcement_contract.py` (49, all fail on the old code) |
| S66 | every chat turn reaches the frontend as `turn.start`, numbered `turn.part` (seq 1..N, dense under concurrency) and EXACTLY ONE `turn.end` (ok / error / cancelled, final text + spoken line); an exception becomes a visible `error` part; bridged bus events (tool / task / card / permission / question / notice) are filed into the live turn; the TS types are generated from the one Python SCHEMA | one reply rode three couriers (chat_chunk / chat_message / text_response + bridged events) and the chat matched them by turn-id strings; backend errors and live reasoning had no listener | `backend/agent/turn_protocol.py` (`TurnEmitter`, `route_bus_event`), gateway text + voice paths, `ws_event_bridge`, `scripts/gen_turn_protocol_ts.py` -> `lib/turns/protocol.ts` | `contract/test_turn_protocol_contract.py` (32; the two wiring guards failed on the old code) |
| S67 | the chat files live turns by the conversation the EVENT names, orders parts by seq, keeps one end, never clamps a streaming reply; errors / reasoning / notices / cancel render in their turn (both modes); card anchor always created; pills / retry take the one send / resend path; no frontend failed-search rule | chunks were written to the ACTIVE conversation; card-anchor early return (orphan pile); 500-char clamp + remount while streaming; pills sent without conversation_id; fetch inside a state updater + stray "Retrying..."; `_isEmptyResultDoc` second copy | `lib/turns/turnStore.ts`, `lib/turns/mergeTurns.ts`, `components/chat/turn/TurnParts.tsx`, `chat-view.tsx` | `__tests__/turns/turnStore.test.ts` (13), `__tests__/turns/turnView.replay.test.tsx` (12: fixtures replayed + rendered in personal and developer mode) |
| S68 | a developer turn is a prompt line + a LIVE matrix (rows born / running / fold; split children in a "looked closer" chamber; the agent Xur rides the spine to the running row; finished runs fold to one plain-word line) + a markdown answer in the mono family; it fits the wing (no pre, no sideways scroll); a `>cmd` is a one-node matrix with an EXEC row opening to its output; GUI matrix and ANSI export render the same rows / order / verbs | the developer card was a 68-column ANSI string in a 9 px `<pre>` that scrolled sideways; answers printed raw `**` and fences; `>cmd` output went to a store nothing in the chat drew | `components/chat/matrix/*`, `lib/cli/shellRuns.ts`, `TaskCardEntry` developer branch, `MarkdownMessage` cli variant | `__tests__/matrix/liveMatrix.test.tsx` (15; the TaskCardEntry guard fails on the old `<pre>`) |
| S69 | the thread list is a SUMMARY read: `GET /api/threads` returns id, title, pinned, updated_at, strand_count, message_count, last_preview (<= 80) from ONE indexed query (`idx_conversations_parent`); the header orbit never calls `fetchConversations`; a strand IS a conversation row; deleting a root deletes its strands | opening the thread list downloaded every thread with every message (`openHistory()` -> `fetchConversations()`) and lagged | `backend/conversation_store.py`, `backend/api/chat.py`, `lib/strands/api.ts`, `components/chat/header/ThreadOrbit.tsx` | `backend/tests/contract/test_strands_contract.py` (9; 7 fail on the old store, the cascade test fails on the old delete), `__tests__/header/ThreadOrbit.test.tsx` |
| S70 | every agent file edit (`write_file` / `edit_file` at `AgentToolBridge.execute_mcp_tool`) carries a bounded diff on its step's `tool:result`, also in a card-free turn; an undo restores the exact bytes or one hunk, only when the file still matches, runs mid-turn, and tells IRIS; the UI marks a hunk undone ONLY after an ok `diff_undo_result` | edits were invisible in the chat; nothing could undo them; the card gate withheld small-turn results | `backend/agent/edit_diffs.py`, `tool_bridge.py`, `ws_event_bridge.py`, `iris_gateway._handle_diff_undo`, `components/chat/diff/*`, `lib/diffs/*` | `backend/tests/contract/test_edit_diff_contract.py` (31; 25 fail on the old wiring), `__tests__/turnui/diffReview.test.tsx` |
| S71 | Stop ends the running turn: `stop` cancels that conversation's text-turn task (`cancel_turn_tasks`) AND reaches the DER loop through the steering inbox; the turn ends `cancelled`; a stop for another conversation cancels nothing; Enter while a turn runs sends `steer`, not a prompt | there was no stop button; a stop only reached the inbox | `backend/main.py`, `components/chat/Composer.tsx` | `backend/tests/contract/test_stop_turn_contract.py` (3), `__tests__/composer/composer.test.tsx` (14) |
| S72 | the chat chrome follows the approved concept: one brand palette (`useBrandPalette`, three neighbouring hues) for the Xur, the spine and both edge lights; the spotlight aperture is set into each wing's top edge (same handler, titles and position); spotlight dimming unchanged (0.3, saturate(0.6) blur(2px), no pointer events); every old header control is reachable from `◉`; animations stop under reduced motion | one flat colour; a bordered aperture button cut in half by `overflow:hidden`; header controls in a row | `components/chrome/*`, `components/chat/header/*`, `components/chat/spine/*`, `hooks/useBrandPalette.ts` | `__tests__/chrome/*` (22), `__tests__/header/*` (34), `__tests__/spine/*` (33) |
| S73 | asks wait IN the turn (ASK row / inside the card) with y / n keys, a countdown only when the backend sent `timeout_seconds`, and leave a receipt; artifacts open in the in-wing lens (pop out, drag to the Workspace Hub); no engine words on screen | permission / question cards floated outside the turn; artifacts only opened full-wing | `components/chat/turn/AskPrompt.tsx`, `lib/turns/asks.ts`, `components/chat/lens/*`, `components/workspace/DeveloperWorkspace.tsx` | `__tests__/turnui/*` (69) |
| S74 | the dashboard is built from the chat's parts: ONE `◉` menu component in both wings; the rail is a spine with Settings / Surfaces views (no Inference console entry; `open_inference_console` lands on Monitor's stream); orb rows only for plain setting fields, other content keeps its own layout; Monitor shows every value ONCE (model calls only in the stream, Logs hides them and counts them); hub drops are Views, never tabs | the dashboard only borrowed the ink; Monitor and the Inference console showed the same calls, tokens and latency twice; drops became project tabs | `components/dark-glass-dashboard.tsx`, `components/dashboard/{DashboardRail,MonitorPage,settingsModel,ModelRoutingTable}.tsx`, `components/chrome/WingMenu.tsx`, `components/workspace/ViewsLane.tsx` | `__tests__/dashboard/*`, `__tests__/monitor/*`, `__tests__/workspace/viewsLane.test.tsx`, `__tests__/refs/*`, `backend/tests/contract/test_file_refs_contract.py` |
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

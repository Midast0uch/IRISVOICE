# Execution audit — progress log

## START HERE (next session)

Read in this order: this section -> MCM pin `pin_afa4442771d1` (HANDOFF 2) -> the log below
-> `README.md` (owner decisions) -> `execution-audit.html` / `reply-surface.html` for design
detail. Older handoff: `pin_dc96cc9c9681` (its NEXT list is superseded).

**Where it stands.** Phase 0 harness and Phase 1 blockers (B1-B17) are done. Phase 2 core is
live: in developer mode every tool-less DER step runs `backend/agent/node_executor.run_node`
(a bounded Brain tool loop). Coding eval: baseline 0/15 -> 12/15 full run
(`evals/results/20260929-191746.json`) -> after the STATUS-line fix c11 + c14 also pass
(est. 14/15). Only `c10_create_module` still fails. Research group (1/6 baseline) not re-run.

**Next work, in order** (each with DONE / NOT THIS per CLAUDE.md):
1. `c10_create_module` — inspect the reply and hidden tests (`evals/fixtures/c10_create_module/`),
   find why the Brain's one-shot module fails 8 hidden tests. DONE: c10 passes and the full
   coding group reaches >= 14/15. NOT THIS: task-specific prompt hacks.
2. Remove the TEMP `IRIS_STACK_DUMP_S` faulthandler hook in `start-backend.py` once no more
   timing work is planned (it is off unless the env var is set).
3. Reply surface Phase A (`reply-surface.html`, "Order of work" A): one `create_artifact(title,
   kind, summary, content, language?, artifact_id?)` tool built from
   `tool_bridge._execute_render_document` + `agent_kernel._store_document_data` + the existing
   `DOCUMENT_RENDER` event; remove markdown demotion (`agent_kernel` ~4874,
   `artifact_policy.is_artifact_document`), fallback mint (`_mint_artifact_card`), the web-format
   question (`_maybe_escalate_web_format`); rewrite the `[RESPONSE FORMAT]` prompt block; `show`
   JSON converts to the same event; Oracle `presentation` stays shadow-only. Pinned tests:
   `contract/test_structured_response.py`, `contract/test_document_render_contract.py`,
   `contract/test_render_as_tool.py`, `contract/test_surface_observer_contract.py`,
   `behavioral/test_reply_surface_behavior.py` (run behavioral tests with a time cap).
4. Phase 2 rest: `plan_update` tool (model adds/splits/closes DAG nodes via existing graft/amend),
   tool-model argument repair (hands), personal-mode research through `run_node` with the
   research guards moved to web-tool-family policies. Then Phase 3 (turn protocol + turn
   store), then the live execution matrix (`app/cli-preview`), then reply surface B-D.
5. Open performance items: turn-start recall (ontology 16 s + episodic 18 s), `calculate_eml`
   FFI per step in `_der_finalize_step` (20 s seen once).

**How to run the evals safely (learned the hard way).**
- Start the backend DETACHED, never with `preview_start` (a Claude crash kills a preview server,
  and vice versa):
  `Start-Process C:\Python314\python.exe -ArgumentList C:\dev\IRISVOICE\start-backend.py -WorkingDirectory C:\dev\IRISVOICE -WindowStyle Hidden -RedirectStandardOutput logs\backend_eval_stdout.log -RedirectStandardError logs\backend_eval_stderr.log`
- Load the tool model (LFM2.5-2.6B on :8082): `python evals/load_tool_model.py` (waits for
  the API, then sends WS `load_local_model`). The Brain is `gemma4:31b-cloud` on Ollama :11434.
- Wait ~75 s after start: the backend freezes up to ~45 s after startup / model load
  (RetentionManager and warm-ups), and the harness preflight needs `/health` within 5 s.
- Run small subsets: `python evals/run_evals.py --task c01_fix_off_by_one --task c10_create_module`
  or `--group coding` (~20 min). Research tasks take 5-10 min each; run them one at a time.
- Use `127.0.0.1`, never `localhost`, for local llama-server ports (+2 s per request here).
- NEVER sample the backend from outside (py-spy / `python -m asyncio ps`): it killed the backend
  and Claude Code. For timing, set `IRIS_STACK_DUMP_S=4` before starting the backend and read
  `logs/stackdump.log` (first line `start_epoch`; dump k is at start + 4k s).
- Targeted test runs only, each with a time cap; `test_mcp_dispatch.py` deletes a tracked
  fixture skill (restore with `git checkout`).
- Known pre-existing test failures (not caused by this work): `test_capability_escalation::
  test_t23...`, `test_standing_list::test_edge...`, 3 in `test_decision_engine` (fake backend
  lacks `instruction`), 3 in `test_skill_creator` (wrong fixture path), 5 router tests in
  `test_context_window_negotiation` (fake transport lacks `budget_check`), plus the stale list
  in `pin_dc96cc9c9681`.

**Owner to-do.** `data/iris_config.json` still holds `"mode": "developer"` and a `projects`
entry `iris-evals` from the crashed eval run: set `"mode": "personal"` and remove that entry
(an automated rewrite was blocked). Nothing after this commit is pushed.

---

Running log of work after the Phase 1 commit (`a21b641c`). Each entry is also recorded in
MCM (`record_edit` / `record_test` / `pin_add`).

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

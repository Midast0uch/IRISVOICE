# Tasks: Developer-Mode CLI as IDE (dev-cli-ide)

Work is organised as **progressive gates**, not parallel waves. Each gate has an ENTRY condition, a task set, and an EXIT GATE that must be *demonstrated* before the next gate opens.

---

## HOW TO READ A TASK (D8 — anti-overcoding policy)

Every task carries three lines. They are the contract, not commentary:

- **DO** — the change to make.
- **DONE =** — the single observable condition that ends the task. When it is true, stop. Not "when it feels complete."
- **NOT THIS =** — the specific over-builds this task invites. Producing any of them is a task failure even if the code works.

You are measured against `DONE =` and `NOT THIS =`, never against your own sense of completeness. `DONE =` is the falsifiable half; `NOT THIS =` is the half that stops scope creep, because the ladder tells you *how small* to build and says nothing about *how far* to go.

Apply the AGENTS.md minimality ladder inside a task; apply these two lines to its edges. Rungs run AFTER understanding — never instead of it. Understanding, verification, error handling, and security are never what you minimize.

If `DONE =` is unreachable without producing something on the `NOT THIS =` list, that is a **finding**: stop and report the conflict. Do not quietly widen the bound.

## HOW GATES WORK

1. **Gates are sequential.** Do not start Gate N+1 tasks until Gate N's EXIT GATE has been demonstrated. Tasks *within* a gate may run in parallel unless a dependency is stated.
2. **The EXIT GATE is demonstrated, not asserted.** Run the check. Paste the actual output. "It should work" does not open a gate.
3. **A failed exit gate is a stop, not a detour.** Do not proceed while telling yourself you will come back.
4. **If an exit gate cannot be met as written, that is a FINDING.** Name the conflict, show the evidence, propose the smallest change to the gate. Never rewrite the gate to match what you built — that is the test-modification failure mode (AGENTS.md, THE TEST RULE) applied to gates.
5. **Record at each gate:** `record_edit` / `record_test` for what ran, `pin_add` for what the gate revealed — then **verify the write landed** with `db_query`. An MCM call that times out at the client may still have committed (Gate 0 saw one timed-out `pin_add` commit and one timed-out `record_test` not commit). Retrying blind duplicates rows; not retrying silently loses them.

## WHAT GATE 0 LEARNED — apply these in every later gate

Gate 0 was the first time anything in this spec was executed rather than reasoned about. Four lessons, each with a concrete rule:

**L1 · Reading code predicts the SET of problems, not the ORDER, and misses whole classes.**
Of 9 predicted build blockers: 3 right, 1 right-with-wrong-mechanism, 1 wrong on severity, 3 missed. The very first real failure was a config-schema error nobody predicted, and it made every predicted blocker unreachable.
→ **Rule:** before building against a `**Verified:**` claim, execute the thing once. Call the tool, run the file, insert a marker. Two minutes of execution outranks an hour of reading.

**L2 · This codebase has a house pattern: confident assertion, absent implementation.**
Four independent instances found in one session:
- `CLAUDE.md` documented 4 MCM tools that do not exist — including `claim_work()`, STEP 1 of its own workflow.
- `next.config.mjs` had a 45-line `webpack:` block commented as applying to production builds. It never ran.
- `git_ops.py` `approve_write` is documented at `main.py:1478` as *"apply to disk and commit."* It sets a string.
- `RebuildPage.tsx` renders a full rebuild pipeline wired to `mockRebuildStatus`.
→ **Rule:** treat a docstring, comment, or config comment as a **claim to test**, never as evidence. When a requirement rests on "the code says it does X," verify X happens. Expect more of these in Gates 1-3 — the pattern is systemic, not incidental.

**L3 · A timeout tells you nothing about whether the write landed.** (See rule 5 above.)
→ **Rule:** every recording step gets a read-back.

**L4 · A live dev server and backend block measurement.**
Gate 0 could not clear `.next` (dev server held `.next/dev/cache/turbopack/`) and could not start the sidecar for a runtime test (backend held :8090).
→ **Rule:** each gate states up front whether it needs a quiet machine. Gates that bind ports or clear caches do. Never kill the user's running processes to get a measurement — report the obstruction instead.


> **Gate 0 is not optional and not a formality.** Every blocker in REQ-17 and REQ-20 was read from configuration and source code — **not one was reproduced by running a build**. Gate 0 is where predictions become facts, and where blockers nobody predicted show up. Skipping it makes every later failure ambiguous between "I broke it" and "it was already broken."

---

## GATE 0 — Baseline: measure what is true today

**STATUS: RUN 2026-08-25 by an external agent (Claude Code, session 258). Results: [`GATE0-FINDINGS.md`](./GATE0-FINDINGS.md).**
Read that file before starting Gate 1. It records the observed baseline, which predicted blockers confirmed, which mechanism was restated, and **one blocker that was missed entirely (G0-01) and preceded every predicted one**.

**ENTRY:** none. This is first.

- [x] **T-B1 (REQ-21 AC1): Record the starting state.** ✅ DONE — commit `9216a7b1`, 131 dirty entries, 45 passed / 1 pre-existing failure (`test_tool_bridge_gates.py:145`).
  DO: record branch, commit, and working-tree state (the tree currently carries substantial uncommitted churn across backend, components, and tests). Run the project's targeted test command for the areas this spec touches — dev, agent tools, terminal, git_ops. Record what passes and what already fails.
  DONE = a written baseline naming the commit and listing pre-existing failures by name.
  NOT THIS = fixing the pre-existing failures; running the full suite (targeted only — behavioral tests hang and imports are heavy); cleaning the working tree. Measure, do not repair.

- [x] **T-B2 (REQ-21 AC2-AC4): Attempt a full packaged build. Fix nothing.** ✅ RUN — 1 wall cleared (G0-01 config schema, minimally fixed per T-B2). See findings file for the full ordered list.
  DO: clean clone → install → `build:static` (or current equivalent) → `tauri build` → install the artifact → launch it. Record every failure, in order, with its actual error text. Where a build cannot proceed, fix only enough to reach the next wall, and record that too.
  DONE = an ordered list of real, observed build/launch failures — each marked *predicted by REQ-17/REQ-20* or *not predicted*.
  NOT THIS = fixing the blockers (that is Gate 4); a build script; a CI pipeline; making the build green. **The deliverable is a known list, not a working build.**
  RIPPLE: REQ-21 AC3 — a predicted blocker that does NOT reproduce is a spec correction to make, not a line to quietly delete. A wrong prediction is information.

**EXIT GATE 0:** ✅ **MET**
- ✅ Baseline commit (`9216a7b1`) and the pre-existing failure recorded.
- ✅ A packaged-build attempt was run; failures captured with real error text in `GATE0-FINDINGS.md`.
- ✅ REQ-17 / REQ-18 / REQ-20 / REQ-21 corrected against what was observed (REQ-21 AC3).
- ✅ G0-08 (MCM tool docs) root-caused and FIXED — CLAUDE.md/AGENTS.md corrected against the live server. This was the one item flagged as blocking Gate 1'''s start; it is closed.
- ✅ **Gate 1 is open.**

> **One production change was made during Gate 0** — the `bundle.resources` schema fix in `src-tauri/tauri.conf.json` (G0-01), sanctioned by T-B2's "fix only enough to reach the next wall." Everything else in this gate was measurement.

---

## GATE 1 — IRIS is the agent

> **START HERE IF YOU ARE TAKING OVER.** Full handoff briefing: `pin_34bdf2246af5`
> (`pin_search("HANDOFF dev-cli-ide Gate 1")`). It carries the read order, the ~20
> minutes of verification to run BEFORE building, the operational gotchas, the four
> production changes already on disk, and what is still open and not the agent'''s to
> decide. Read it and GATE0-FINDINGS.md before the first edit.

**ENTRY:** Gate 0 exit demonstrated.

> Nothing downstream matters until these land. This is the difference between "the CLI works" and "IRIS can build itself."

- [x] **T0 (REQ-0): Route `dev_cli` to the IRIS AgentKernel; delete the external CLI registry.** ✅ DONE 2026-08-25, session 259.
  DO: dispatch `dev_cli` to the AgentKernel turn path with session workdir + conversation context. Delete `backend/dev/cli_tools.yaml` and `backend/dev/cli_registry.py`. Remove `_select_tool` and its LLM call from `backend/dev/orchestrator.py`. Repoint `GET /api/dev/cli-tools` (`backend/main.py:1221`) at IRIS's own command surface.
  DONE = `/run <query>` produces an IRIS agent turn with no external executable on PATH, and `cli_started`/`cli_activity`/`cli_output` still arrive in the shapes at types/iris.ts:258-272.
  NOT THIS = a plugin architecture for "pluggable agent backends"; a compatibility shim keeping the YAML loadable; a deprecation period. D7 says removed, not demoted — delete the files.
  RIPPLE (REQ-0 AC6, found in `pin_c30f0b9f8547`, NOT by reading code): three artifacts consume the deleted registry —
    - `backend/tests/contract/test_cli_tools_endpoint.py` (existing contract test; goes red on deletion)
    - `components/terminal/HelpPanel.tsx:63` ("Available delegate tools" list)
    - the `/help` local answer path in `chat-view.tsx`
  The test conflict is ALREADY RESOLVED in REQ-0 AC7 — read it before you touch the test. Short version: the
  assertion intent ("registry, not a hardcoded copy") survives and stays asserted; only the registry's identity
  changes. Re-point the test at IRIS's own command surface and SAY SO IN YOUR REPORT. Do not weaken it, do not
  delete it, and do not decide this yourself at build time.
  > **Executed:** registry + YAML deleted; orchestrator dispatches `kernel.process_text_message` in an executor with chunk→`cli_output` line streaming; gateway passes `_active_conversation_id` so /run joins the live thread; `/api/dev/cli-tools` serves `IRIS_DEV_COMMANDS` (/run /help /review /debt /term /clear). **CALLED-OUT TEST CHANGE per REQ-0 AC7:** `test_cli_tools_endpoint.py` re-pointed at the command surface, assertion intent kept strict (`names == EXPECTED_COMMANDS`, field set, availability), old `kilo_code` assertion inverted to assert absence. All three ripple consumers resolved: contract test re-pointed; HelpPanel.tsx is data-driven over the endpoint shape (unchanged fields) — stale "IRIS picks a CLI tool" copy corrected; TERMINAL_HELP copy corrected. Probe finding: kilo/claude/opencode are ALL on PATH on this machine, so a live /run would have spawned a foreign agent — exit-gate demo strips their host dirs from PATH.

- [x] **T0b (REQ-4 AC5-AC6): Bind session workdir into the agent's tool-execution context.** ✅ DONE 2026-08-25, session 259.
  DO: resolve the session workdir once per turn and thread it into `_execute_dev_tool` (`tool_bridge.py:1742`). Replace the `startswith(_DEFAULT_REPO)` guard (`:1755`) with an allowlist built from `GET /api/projects` (`backend/main.py:1288`). `_DEFAULT_REPO` stays as the no-tab-active fallback.
  DONE = with a tab open on a registered non-IRIS project, `git_status` and `run_command` execute in THAT directory; a path under no registered root is rejected with the same explicit error text as today.
  NOT THIS = a path-permission framework, per-tool cwd overrides, a sandbox/chroot layer. One resolver, one allowlist check, same error string.
  RIPPLE: this is what makes D6 true. Without it, opening a tab on another project still edits IRISVOICE.
  > **Executed:** orchestrator binds per-turn via `set_session_workdir`; resolution = explicit param > session workdir > repo root; allowlist sourced from `data/iris_config.json` (same store GET /api/projects serves) with separator-aware containment — which also closes the sibling-prefix hole the old `startswith` guard had. Legacy rejection string byte-identical (probe-verified before and after). 6/6 execution checks passed.

- [x] **T0h (REQ-18): Ripgrep-backed `grep_files` + `glob_files`.** ✅ DONE 2026-08-25, session 259.
  DO: register two read-only, parallel-safe tools wrapping a **bundled** `rg` binary (resolved from the app bundle before PATH). `grep_files`: regex + path scope + glob/type filter + output mode (`files_with_matches` default / `content` / `count`) + context lines + result cap. `glob_files`: glob pattern, mtime-descending, result cap. Both respect `.gitignore` by default with an opt-out, honour the REQ-4 workdir + allowlist, and state when results were truncated. Bound `list_directory(recursive=True)` (`builtin_servers.py:459` — `Path.rglob("*")`, currently unbounded and ignore-blind).
  DONE = `grep_files` for a symbol returns matching paths in one call with zero `node_modules` hits and an explicit notice if capped; `glob_files("**/*.tsx")` returns most-recently-modified first.
  NOT THIS = a semantic/embedding index (the coordinate graph is already the semantic layer); a language server, symbol table, or AST search; a query DSL; a result-ranking model; a search cache. Two tools, one binary, ripgrep's own flags.
  RIPPLE: **gates T7.** The ladder's rung 2 is "already in the codebase?" — an agent that cannot cheaply answer writes duplicates, the most common over-build there is.
  > **Executed:** `backend/agent/search_tools.py`; registry 36→38 tools. rg 14.1.1 vendored at `src-tauri/resources/rg.exe` — **Gate 0's "rg happens to be on this machine" did NOT reproduce; rg is nowhere on PATH here**, making AC6 mandatory rather than prudent. Found by execution: ripgrep only honours `.gitignore` inside a git repo by default — `--no-require-git` added so non-git projects get ignore semantics too. `--no-ignore` over the whole repo walks node_modules and hits the bounded 60s timeout loudly (REQ-18's own measurement, now enforced). `list_directory(recursive=True)` bounded at 2000 + truncation notice pointing at glob_files. Search dispatch shares the REQ-4 scope resolution + allowlist (typed `workdir_denied`). 10/10 execution checks passed.

- [x] **T0i (REQ-19): FAULTLINE labels for the dev/shell surface.** ✅ DONE 2026-08-25, session 259.
  DO: `register_error_label(...)` for `workdir_denied`, `cap_reached`, `aborted`, `shell_spawn_failed`, `output_truncated`, `injection_suppressed`, `worktree_unavailable`, per the REQ-19 AC1 dimension table. Make a non-zero command exit surface as `success: True` + `returncode`, never an `error_type`. Exclude `aborted` from the REQ-12 failure budget and the tool-decision veto memory. EXTEND `backend/tests/unit/test_tool_errors.py` — its 17 existing tests stay.
  DONE = `> pytest` with a failing test yields `success: True, returncode: 1`; a workdir rejection yields `error_type: workdir_denied, retryable: "no"`; a user abort does not count against the failure budget.
  NOT THIS = new branches in the reviewer, a retry-policy engine, per-label handling code. FAULTLINE §2: a new label is a DATA edit.
  > **Executed:** 7 labels registered verbatim from the AC1 table; duplicate registration now REFUSED (REQ-19 edge case — was silently overwritten); workdir rejection typed `workdir_denied` with `details["raw"]` preserved and legacy message text intact; `_run`/`run_command` report non-zero exit as `success: True` + `returncode`; git_commit's internal check moved to `returncode`. `aborted` excluded from the failure budget; veto memory verified structurally unreachable for aborts (written only from web-gather budget policy). Suite extended 17→30, all passing.

**EXIT GATE 1:** ✅ **MET — demonstrated 2026-08-25, session 259.**
- ✅ `/run "list the files in this project"` completes on IRIS's own agent **with kilo, claude, and opencode absent from PATH** (host dirs stripped, `shutil.which` → None ×3; event sequence `cli_activity → cli_started → cli_output×N → text_response` with exact types/iris.ts:258-272 shapes; kernel received query + conversation_id + turn id). **UPGRADED TO LIVE 2026-08-25:** backend restarted on current code (user authorized restarts — `pin_9f7642c70131`); a real WS `dev_cli` drive returned `cli_activity{IRIS Agent}` → `cli_started{iris-agent-*}` → live `file_activity` stream → `text_response` from IRIS's kernel. Turn content was `[IRIS error] planner returned no valid plan` — the fresh backend has no LLM provider configured (environmental); the ROUTING contract is what REQ-0 owns and it is demonstrated live.
- ✅ With a tab open on a registered non-IRIS project, an agent `git_status` returns THAT project's status — not IRISVOICE's (real `git status` + `cd` executed in the registered directory).
- ✅ `grep_files` finds a known symbol in one call, returns paths only, zero `node_modules` hits (`backend/dev/orchestrator.py`, no content leak).
- ✅ A deliberately failing test run reports `success: True, returncode: 1` — not a tool error.
- ✅ Opens Gate 2.

> **Pre-existing failure status update (pin_62388c758eef):** `test_unknown_tool_not_resolved_but_still_runs_dispatch` has EVOLVED from a fast AssertionError into an indefinite hang. Attribution probe (git-stash of all Gate 1 agent-layer edits, rerun at HEAD) reproduced the hang — it is NOT Gate 1's. Suites containing it must run with `--deselect` until fixed deliberately; EXIT GATE 5 must record it.

---

## GATE 2 — Safety rails before IRIS touches its own source

**ENTRY:** Gate 1 exit demonstrated.

> Gate 1 gave the agent reach. Gate 2 is what makes that reach survivable. Do not point the agent at IRIS's own tree before this gate closes.

- [x] **T0d (REQ-13): Self-edit isolation.** ✅ DONE 2026-08-25, session 259.
  DO: when the resolved workdir is the IRIS repo root, route the agent's file writes into the sandbox worktree via the existing `ensure_worktree()` (`git_ops.py:191`). Show the sandbox state in the terminal panel header. Note in the turn result when an edited module is one the running backend has loaded.
  DONE = an agent edit to a file under the IRIS root lands in the worktree and NOT the live tree; the header says so; promotion requires the user calling `/api/git/worktree/merge`.
  NOT THIS = auto-restart, hot-reload, a module-dependency graph, an auto-promote heuristic. AC4 is a one-line note, not a reload system.
  > **Executed:** `_route_self_edit` in tool_bridge intercepts write_file/create_directory/delete_file before MCP dispatch; workdir-under-root ⇒ path rewritten into `.iris-worktree`; worktree failure = typed `worktree_unavailable` rejection (never silent live write); loaded-module edits get the AC4 restart note; successful writes queued for diff review. TerminalPanel header shows a SANDBOX badge with the worktree path (AC3). Verified end-to-end on a hermetic fixture repo: write landed in worktree, live tree clean.

- [x] **T0e (REQ-14): Make the diff-review gate actually gate.** ✅ DONE 2026-08-25, session 259.
  DO: `approve_write` applies and commits (returns the hash); `reject_write` discards. Scope `_pending_writes` per session and bound it (module-level global at `git_ops.py:139`). Make it a pre-apply gate for REQ-13 writes; keep the session-end scan as a backstop.
  DONE = approve produces a real commit, reject leaves no trace on disk, two concurrent sessions cannot see each other's queue.
  NOT THIS = a review UI, an approval-policy engine, multi-reviewer flow, an audit log. Two functions currently return ok without doing anything — make them do the thing.
  > **Executed:** queue is per-session (lock-guarded dict) and bounded at 50/session; approve stages + commits in the sandbox worktree returning the hash (`[agent-sandbox 317f97a]` seen in branch log); reject restores tracked files byte-identically and deletes untracked ones — no trace. The existing `/api/diff/approve|reject` endpoints now call real gates (Gate 0's "confident assertion, absent implementation" example closed). Session-end scan kept as backstop (its `queue_write` call is signature-compatible).

**EXIT GATE 2:** ✅ **MET — demonstrated 2026-08-25, session 259** (10-check hermetic fixture-repo run):
- ✅ An agent edit to a file under the IRIS root is present in the worktree and **absent from the live tree** (end-to-end write dispatch: file exists at `.iris-worktree/e2e.txt`, absent at repo root).
- ✅ Approve produces a commit hash that `git log` shows (`317f97a session A change` on `agent-sandbox`); reject leaves `git status` clean (untracked deleted, tracked restored to HEAD).
- ✅ Two concurrent sessions cannot see each other's pending queue (sessA/sessB disjoint views).
- ✅ Opens Gate 3.

---

## GATE 3 — The CLI surface

> **START HERE IF YOU ARE TAKING OVER.** Full handoff briefing: `pin_bcc8690c29b7`
> (`db_query` it by ID). It carries what Gates 1-2 already landed (don't rebuild any
> of it), the Gate 3 dependency map, the execution probes to run before building,
> operational gotchas (pre-existing hanging test — deselect it; backend restarts
> allowed; provider config), machine facts, and what is still open.

**ENTRY:** Gate 2 exit demonstrated. ✅ Met 2026-08-25 session 259.

### 3a — Backend

- [ ] **T1 (REQ-1): `backend/dev/terminal_handler.py` — persistent per-session shell.**
  DO: platform-aware persistent shell (PowerShell `-NoExit` / `$SHELL`), output streaming via `_ws_send`, spawn-failure retry on next input.
  DONE = `> dir` returns real output; `> cd x` then `> dir` reflects the new cwd; an externally killed shell causes a reported restart on next input.
  NOT THIS = a PTY/terminal emulator, ANSI colour parsing, in-shell tab completion, an interactive-program handler. It is a pipe, not a terminal.
  RIPPLE: resolves the dangling import at `iris_gateway.py:10495`.

- [ ] **T0c (REQ-1 AC5): Unify the agent's shell onto the session ShellSession.**
  DO: route `run_command` and `git_*` through the same `ShellSession` as user `>` commands, inheriting cwd/env persistence, output bounds, the semaphore, and abort.
  DONE = an agent-launched `run_command` appears in the terminal panel, counts against the global cap, and is killable with Ctrl+C.
  NOT THIS = a command-execution abstraction layer, a queue/scheduler, a retry policy. Swap the call site.
  RIPPLE: depends T1. Removes the one-shot `subprocess.run` at `tool_bridge.py:1830`.

- [ ] **T2 (REQ-5 AC1-AC6, REQ-12 AC2): Caps and bounds in `subprocess_manager.py`.**
  DO: global semaphore (default 4, queue-with-position), per-session output-rate and memory bounds, bounded output buffers. Agent commands count against the same cap.
  DONE = the 5th concurrent session gets an explicit "N running, position M"; a flooding process is terminated with a stated reason.
  NOT THIS = a priority scheduler, fair-share allocation, cgroups/job objects, dynamic cap tuning. One semaphore, one counter, one message.

- [ ] **T3 (REQ-4 AC3): Backend workdir validation.**
  DO: reject nonexistent/inaccessible paths with an error naming the path; default when omitted.
  DONE = a bad `workdir` produces an error containing the offending path.
  NOT THIS = path-normalization utilities, symlink policy, a virtual-filesystem layer.

- [ ] **T4 (REQ-2): ShellRecord queue + context injection at turn assembly.**
  DO: queue `{command, exit_code, head, tail, elided_bytes, workdir, ts}` per session; AgentKernel pulls at turn assembly. Redact per REQ-2 AC4's pattern set + deny-list. Enforce the per-turn aggregate budget.
  DONE = `> pytest` then "fix the failing test" produces a turn quoting the REAL failure text; `> cat .env` renders in the panel but injects a suppression notice.
  NOT THIS = a context-management framework, relevance scoring, output summarization, a configurable injection policy engine. Queue, truncate, redact, inject.
  RIPPLE: depends T1.

- [ ] **T4b (REQ-15): Verification gate on turns that edited files.**
  DO: after a dev turn that wrote files, run the TARGETED test command for the touched paths; attach pass/fail + failing test names. Report "no covering test" when nothing maps; never report success on failure.
  DONE = a turn breaking a covered file reports unverified with the failing test named.
  NOT THIS = a coverage tool, test generation, full-suite runs, flaky-test retry. Targeted only — a slow gate is a skipped gate.

- [ ] **T7 (REQ-9): Ladder ruleset + scope-bound injection + adherence verdict.**
  DO: compact (<600 tok) MINIMALITY + DEPTH ladders into the dev-mode system prompt; intensity (lite/full/ultra/off) per workspace; inherited into DER worker prompts; off injects nothing. Inject the active task's `DONE =` / `NOT THIS =` verbatim. Emit the structured adherence verdict REQ-12 logs.
  DONE = a dev turn's assembled prompt contains the ruleset and, when a task is active, its two scope lines; the ledger shows a verdict row after `/review`.
  NOT THIS = a prompt-template engine, per-turn dynamic ruleset generation, an intensity auto-tuner. Static text, four levels, one verdict shape.
  RIPPLE: **depends T0h** — injecting the ladder before fast search exists produces the over-build it was meant to prevent.

- [ ] **T8a (REQ-10): `/review` — delete-list contract + adherence verdict.**
  DO: delegate with a review contract outputting ONLY a delete-list, never a rewrite. Scope arg limits the diff. Empty diff short-circuits with no agent call. Emit the REQ-9 AC7 verdict per changed file.
  DONE = on a seeded over-built diff, output is a delete-list containing no replacement code; empty diff returns "no changes to review" without an agent call.
  NOT THIS = auto-applying deletions, a severity ranking system, an interactive review loop.

- [ ] **T8b (REQ-11): `/debt` — marker scan into task cards.**
  DO: scan for `ponytail:`, `TODO(deferred):`, `IRIS-DEBT:`; render as cards tagged `debt`; dedupe by `file:line`; exclude vendored dirs; skip binaries; bound depth.
  DONE = a seeded repo produces one card per marker, no duplicates across two runs, nothing from node_modules.
  NOT THIS = a new ledger store, marker-syntax configuration, aging/priority scoring, auto-resolution.

### 3b — Frontend

- [ ] **T9 (REQ-3): De-unify rendering.** Remove the `unifiedTimeline`/`renderTimeline` shell-line merge (`chat-view.tsx:706-722, 731`).
  DONE = shell lines no longer appear in the chat stream; the panel shows them; the question-answer path (`:1623-1637`) still resolves.
  NOT THIS = redesigning the panel, a layout system, refactoring the scrollback store.

- [ ] **T10 (REQ-4 AC1-AC4): Active-tab workdir (frontend).** Send `workdir` on `terminal_input`/`dev_cli` (`chat-view.tsx:1670, 1690`); virtual tabs send nothing; header shows the effective workdir.
  DONE = switching tabs changes the header path and the directory `> dir` runs in.
  NOT THIS = a workdir picker, per-command overrides, recent-directory history.
  RIPPLE: depends T3 and T0b.

- [ ] **T11 (REQ-6): Command history.** ↑/↓ with draft stashing, consecutive dedupe, 200-entry bound, persisted per conversation via the scrollback store (not localStorage).
  DONE = ↑ recalls the previous distinct command, ↓ returns to the live draft, history survives a reload.
  NOT THIS = fuzzy history search, Ctrl+R, cross-conversation history, a history browser.

- [ ] **T12 (REQ-7): Slash-command menu.** Filtered menu on `/` sourced from `GET /api/dev/cli-tools`; `>` hint row; Tab/Enter accept; Escape dismiss; suppressed while listening; must not hijack `@taskcard` (`chat-view.tsx:4312`).
  DONE = `/` filters commands from the endpoint; `@` still opens the card picker unchanged.
  NOT THIS = argument autocomplete, inline help panels, a command palette, fuzzy matching.

- [ ] **T13 (REQ-8): Abort wiring.** Ctrl+C sends `dev_abort` when a subprocess runs (backend exists at `iris_gateway.py:10451`), clears input otherwise; log the abort line.
  DONE = Ctrl+C kills a `ping -t`-style endless command and input stays usable.
  NOT THIS = a process manager UI, per-process kill buttons, signal-level configuration.
  RIPPLE: depends T2.

- [ ] **T14 (REQ-5 AC3): Session state badge.** idle / working / blocked / done, driven by `cli_*` events.
  DONE = starting a command flips to working; a pending question flips to blocked; completion flips to done.
  NOT THIS = a session dashboard, transition history, notifications. Four states from events already on the wire.

### 3c — Context lifetime and concurrency lanes (added 2026-08-26)

Added mid-Gate-3 after T4 was demonstrated. T4 worked and was wrong: it delivered
shell context by persisting it into dialogue history. Fixing that exposed the
retention gap, and the retention gap exposed the WebSocket lock. All four tasks
below are Executed.

- [x] **T20 (REQ-22 AC1): Ephemeral shell-context delivery.** Delete the `add_message("system", block)` in `process_text_message`; append the drained block to the LOCAL per-turn context list beside the @-card block.
  DONE = the block reaches planning and synthesis for the turn with shell activity, and appears in no later turn and in no `conversation.json`.
  NOT THIS = a new context-assembly abstraction, a zone system, a token budgeter, touching `ConversationMemory`'s eviction policy.
  Executed: `agent_kernel.py` — `_shell_block` is initialised before the memory try-block and appended immediately after the @-card block. Verified the routing position is unchanged: the block still lands in `context` before `_needs_planning(text, context)` -> `compile_dag`, exactly where `get_context()` used to put it.

- [x] **T21 (REQ-22 AC2-AC5, AC7): Retention, index, and exact read.** `drain()` retains instead of discarding; every record carries a ref; retained records not carried verbatim get one index line; `read_shell_output(ref)` returns the exact retained text.
  DONE = a second turn shows the newest command verbatim and older ones as index lines, and `read_shell_output` returns the earlier bytes exactly.
  NOT THIS = a search API over shell history, persistence to disk, a scrollback mirror in the backend, a summariser, an eviction policy beyond the two bounds.
  Executed: `backend/dev/shell_records.py` — `MAX_HISTORY_RECORDS=20`, `MAX_HISTORY_SESSIONS=32`, `MAX_INDEX_LINES=10`, plus `clear_session`. Proof run: drain 1 both commands verbatim and no index; drain 2 newest verbatim with `ref=s1`/`ref=s2` demoted to index and the old output NOT re-injected; `get_output('s2')` returns the exact `AssertionError` text and `exit=1`; unknown ref and cross-session ref both return `None`; a session with no shell activity drains to `""`.
  Security proof: `API_KEY=sk-...` reads back as `[REDACTED:api-key]` on BOTH paths — retention stores the already-redacted record.

- [x] **T22 (REQ-22 AC4, AC6 / REQ-23): Register the read tool; remove the dead zone.** `ToolSpec read_shell_output` (category shell, executor internal, `permission_tier="read_only"`, parallel-safe) + `ToolBridge` dispatch + `_TERMINAL_TOOLS` gate. Remove `MemoryInterface.update_tool_state` and every `active_tool_state` entry in `ContextManager`.
  DONE = `resolve_tool('read_shell_output')` resolves read_only, and no context zone exists without a production writer.
  NOT THIS = a shell-history browser tool, a second read tool for the frontend, refactoring `ContextManager`'s zone model while in there.
  Executed: 55 specs total after registration. Removed the zone from `ZONES_ORDER`, `ZONE_WEIGHTS`, `ANCHOR_ZONES`, and both zone initialisers; `specs/agent_loop_design.md` carries a SUPERSEDED note at the line that prescribed it.
  TEST CHANGES, CALLED OUT (see REQ-23 edge cases): `test_interface.py::test_update_tool_state_delegates_to_context` deleted with the API it covered; `test_working.py::TestToolState` deleted for the same reason; `test_...initialized_zones` now asserts 4 zones instead of 5; `test_follows_zones_order`'s fixture no longer seeds the removed zone. Result: 46 passed. One pre-existing Windows teardown ERROR in `test_initializes_all_components` (`PermissionError [WinError 32]` unlinking a temp sqlite file) is environmental and unrelated.

- [x] **T23 (REQ-24): Unlock the terminal lane.** Dispatch `terminal_input` as a background task without `_session_message_locks`.
  DONE = a `>` command typed while the agent works runs immediately instead of after the turn.
  NOT THIS = a general priority/queue system, per-message-type policy config, making it a `_CONTROL_FRAME` (it can run for minutes and would block the reader loop).
  Executed: `main.py` — `_UNLOCKED_FRAMES = {"terminal_input"}`; the dispatch closure binds `unlocked` as a default argument so the flag is captured per frame, not read from the loop variable. Order is preserved by `SubprocessManager._cmd_lock`. Developer-mode gating is untouched: `CapabilitySet.require(TERMINAL)` still rejects personal mode.

- [x] **T24 (REQ-25): Send to the steering channel.** Route a message typed while a card is working to `steer`; accept `text`/`message_id` from top level or `payload`; drop pre-task records at task start.
  DONE = a message sent mid-task revises the running plan at the next step boundary, in both modes, and starts no second turn.
  NOT THIS = a steering UI panel, an ack timeline, pause/stop buttons, disabling the input during a turn, a queue of pending steers.
  Executed: `chat-view.tsx` — `anyCardWorking` gates the branch in `handleSendMessage`, ahead of the WebSocket primary path and after the developer-mode `>` routing, so `>` commands still go to the terminal; a `system` message tells the user the task was steered. `main.py` — the steer push reads `text`/`message_id` from the frame or its `payload`. `agent_kernel.py` — the per-task steering reset now drains and acknowledges records queued before the task started, so a steer never revises a task it was not aimed at. `npx tsc --noEmit` exit 0.

### 3d — Narration (added 2026-08-26)

Raised by the user after the REQ-25 live run: the steer was silent, and the
websearch narration "just repeats 'reading:' when it's not reading and is doing
much more than that".

- [x] **T25 (REQ-26 AC1-AC4, AC6): Speak the steer acknowledgement on RECEIPT.**
  DO: when a `steer` frame with non-empty text is queued, speak one short line through the SpeakTool singleton at priority `low`.
  DONE = a steer sent mid-task produces an audible "heard" within a second, and does not interrupt speech already playing.
  NOT THIS = a steering voice UI, an "applied" announcement, a second audio path, acknowledging pause/stop/resume, speaking a steer that was dropped as stale.
  Executed: `main.py`, in the steering branch beside `emit_queued_ack`. Says *"Got it. I will switch after this step."* — AC2: HEARD, not APPLIED, because the record is consumed at the next step boundary and claiming otherwise is a lie for the length of the running step. Priority `low` queues behind in-flight speech on the existing narration lock (AC3/AC4). AC6 holds by construction: the stale sweep in `agent_kernel` speaks nothing.

- [x] **T26 (REQ-27 AC1-AC5, AC7): Stop the heartbeat repeating itself; give it real detail.**
  DO: track the last line the heartbeat spoke; stay silent when the next line would be identical, and log the silence. Feed the crawl's live page detail into the heartbeat's `status_fn`.
  DONE = a crawl narrates changing detail ("reading example.com, 3 of 8") instead of the word "reading" on every tick.
  NOT THIS = a narration template engine, a phrase bank, per-tool narration config, a second narrator, rewriting the display label ladder.
  Executed: `narration.py` — `last_spoken` guard; an identical line is skipped and logged as `Narration silent / unchanged_since_last_line` (AC7). Because the fixed verb never varies, the guard alone caps the bare `_TOOL_VERB` fallback at **one utterance per run** instead of one per tick.
  `tool_bridge.py` — `self._crawl_progress[session_id]` written by `_on_page_done` and read by a `status_fn` now passed at the `run_with_narration` call site, which previously passed **none at all** (the root cause). Falls back to `plan_title`, the model's own words for the task, before the fixed verb (AC1/AC4). The slot is cleared before and after the crawl in a `finally`.

- [x] **T27 (REQ-28 AC1-AC7): A streamed spoken brief for long answers.**
  DO: after the body is sent, generate a brief and feed it to TTS one SENTENCE at a time so audio starts before generation finishes; correct the `spoken` string afterwards.
  DONE = a long answer is spoken as a brief covering its conclusion, first audio begins while the brief is still generating, and the word highlight tracks what is actually heard.
  NOT THIS = re-summarising short answers, a summarisation service, a second model role, caching briefs, speaking the brief AND the body, blocking the body on the brief.
  Executed, three layers:
  - `agent_kernel.stream_spoken_brief(full_response, on_sentence)` — streams the brief through `self._router.generate(..., chunk_callback=...)` and hands each COMPLETE sentence to `on_sentence` the moment it closes, rather than returning one string at the end. `spoken_brief_needed()` shares `SPOKEN_BRIEF_WORD_THRESHOLD = 120` with `prepare_spoken_text` so the two cannot drift about what "long" means.
  - `iris_gateway` — the brief path engages only when the answer is long AND the agent supplied no `speak` line of its own (AC6: a single call stays the common path). It feeds a `queue.Queue` into the QUEUE FORM of `_speak_response`, which already existed and was unused here; that form synthesises the first sentence immediately instead of waiting for a whole string. Body dispatch is untouched and still goes out first (AC4). AC5: if the brief fails or yields nothing, the fallback truncation is pushed to the queue instead — a failed brief must never produce a silent turn.
  - `chat_spoken_update` frame + `useIRISWebSocket` + `chat-view` — re-points `spoken`/`words` at the brief once it is complete. Without it the highlight would track the fallback line while something else is heard, the exact desync the `spoken` field was introduced to fix.
  **Why streaming, not generate-then-speak:** the user's constraint — "make sure the tts plays before the generation ends so it doesn't feel delayed or out of sync". A brief generated to completion first would start speaking seconds after the text landed.
  Proof (in-process, fake streaming router): sentences reached TTS at t=0.120s, t=0.271s, t=0.322s while generation ran to t=0.323s — **first audio 0.203s before generation finished**, on a stream that took 0.3s total. With a real model the margin scales with generation time. Threshold helper verified both ways.

### 3e — Reliability of the turn itself (added 2026-08-26)

Not planned. Found by live-testing 3c/3d and traced to root cause. These are the
defects that made the agent look unreliable; every one is a constant, a guard,
or a shape mismatch rather than a model limitation.

- [x] **T28 (REQ-30): Parse the planner's JSON by balanced scan, not a greedy regex.**
  DONE = a plan wrapped in prose or preceded by an example still parses.
  NOT THIS = a JSON repair library, retry-with-reprompt, switching the planner to tool-calling (that is a bigger change, see the open item below).
  Executed: `_iter_json_objects` + `_parse_planner_json` in `agent_kernel.py`, plus the raw-reply log on parse failure that only the LM Studio branch had. Proven 7/7 including a control showing the old greedy regex fails the live case with the same error class the log recorded. LIVE: 3/3 ordinary questions answered, 0 apologies, where roughly half of turns died before.

- [x] **T29 (REQ-29): Stop paying for planner fields the parser discards.**
  DONE = the planner prompt asks for exactly the fields the parser reads.
  NOT THIS = removing the capability list (it is why capable requests are not planned as trivial), touching `depends_on`/`critical` (that is the DAG), changing tool selection.
  Executed: tool block 1,131 -> 187 tokens (names only); `tool` and `params` and three RULES lines removed from the schema. LIVE: plan parsed first try, `_plan_task` 2,227 tokens vs 6,178-6,251 before (different prompt, indicative not controlled), tool calling and the card re-verified unchanged.

- [x] **T30 (REQ-4 AC7-AC9): Resolve a relative workdir before the allowlist check.**
  DONE = `grep_files(path='backend')` runs; `../../Windows` is still refused.
  NOT THIS = relaxing the allowlist, removing the guard, per-tool path handling.
  Executed: one `_resolve_scope` helper used at both call sites. Proven 7/7 — three previously-broken cases allowed, two security cases still blocked, two fallbacks correct. LIVE: `task:done` 1 / `task:fail` 0 where the same question previously failed with every tool call refused; answer checked against ground truth, every named file real.

- [x] **T31 (REQ-34): Give the search tools an evidence window that fits a list.**
  DONE = a search returning 18 matches is not cut to 6 before the agent sees it.
  NOT THIS = adding them to `_DER_GATHER_TOOLS` (that set drives the sufficiency gate and the graft decision), embedding-ranked selection, raising every tool's window.
  Executed: separate `_DER_SEARCH_TOOLS`, 8000 chars. Proven 9/9 via AST against the real class body. NOT yet demonstrated live — the confirming run died in tool resolution for an unrelated reason.

- [x] **T32 (REQ-33): Make the live harness assert the outcome.**
  DONE = a turn ending in `task:fail` cannot report PASS.
  NOT THIS = a test framework, snapshot assertions, asserting on exact wording.
  Executed: added `no_step_failed`, `task_did_not_fail`, `agent_did_not_report_failure`, `answer_is_substantive`. The run that had passed 3/3 fails 3/7 under it. This task exists because the harness produced a FALSE PASS on this spec's own work, and the user caught it by listening to the TTS while the report said PASS.

- [x] **T33 (REQ-35, REQ-31): A trivial plan answers instead of apologising.**
  DONE = a planner that returns no steps produces an answer, not the canned apology.
  NOT THIS = trusting the planner's incidental `answer` field, emitting `task:done`, removing the empty-DER fallback.
  Executed: the skip-DER branch now calls `_respond_direct` for real. The old comment claimed it "forces the direct path below" while setting `""`, which the next `is not None` guard swallowed straight into the apology. Deliberately re-asks with the full prompt and context rather than trusting a by-product. Scope verified via AST. NOT live-verified — the path needs a turn where planning runs and yields zero steps, which the T28 fix has made rarer; three probe questions all routed elsewhere (two direct, one a real 1-step plan).

- [x] **T34 (REQ-35 AC1/AC3): A model that replies without naming a tool gets REASON, not FAIL.**
  DONE = the step runs directly instead of failing the turn.
  NOT THIS = marking the step successful, skipping the memory lookup, inventing a new decision kind.
  Executed: `tool_decision.py` returns the existing `DecisionKind.REASON` — already documented as "model decided no tool needed (valid reasoning step)" and already routed by the kernel to `_run_step_direct`. It was simply never produced for a prose reply. A dead model with no text still FAILS. Also replaced the error string that said "Model unavailable" for every arrival, including when the model demonstrably answered.

- [x] **T35 (REQ-36 AC1-AC3): The spoken brief must not read the model's thinking aloud.**
  DONE = a reasoning-fallback result is discarded and the truncation is spoken instead.
  NOT THIS = changing `_dispatch_api`'s fallback (highest blast radius in the repo — raised as an open decision), suppressing reasoning globally, disabling the brief.
  Executed: `stream_spoken_brief` captures reasoning separately and discards output that arrived only on the reasoning stream.

**STILL OPEN after 3e:**
- The central `_dispatch_api` reasoning fallback (REQ-36 "NOT DONE") — one function, every path. Needs a deliberate decision.
- `pytest.ini timeout = 120` is shorter than the `agent_kernel` import on this machine, so kernel-importing tests are flaky by construction and a timed-out run still exits 0. This blocks Gate 5, which is entirely kernel-importing tests.
- T31 and T33 are unit-proven but not live-demonstrated.

### 3f — The widget itself (added 2026-08-26)

Raised by the user: IRIS is a desktop widget whose panels mount and unmount, the
window is draggable and transparent, and the agent's work has to survive all of
it. Two settings-panel defects were reported alongside.

- [x] **T36 (REQ-39 AC1-AC5): APPLY and CLOSE stop blocking on themselves.**
  DONE = APPLY feels instant; CLOSE closes immediately and still persists.
  NOT THIS = removing the duplicate-launch cooldown, changing the save endpoint, touching the unmount cleanup's dirty check.
  Executed: `dark-glass-dashboard.tsx` — removed the unconditional `await new Promise(r => setTimeout(r, 2000))` (the cooldown is enforced independently by `applyCooldownRef`'s timer in the `finally`, so the guard is intact); per-section saves moved to `Promise.all`; `handleCloseWithSave` no longer awaits the apply. MEASURED: `/api/config/save` answers in 412ms cold, 3-4ms warm — the endpoint was never slow, the sleep WAS the wait. `tsc --noEmit` exit 0.

- [x] **T37 (REQ-38 AC1-AC5): Agent work survives unmount.**
  DONE = a task keeps running and keeps showing across a panel unmount/remount, and every consumer sees the same state.
  NOT THIS = a global state library, a React context provider, moving card state to the backend, rewriting the reducer or the bounds.
  Executed: `hooks/useTaskProgress.ts` converted from per-component `useState` + unmount-scoped listeners to a module-level subscriber store read via `useSyncExternalStore` — the same pattern `components/terminal/terminalScrollback.ts` already proved and documents. Every handler body is BYTE-IDENTICAL: each `useEffect(() => {...}, [])` became `;(() => {...})()` run once at module scope, so the cleanup that removed listeners is simply discarded, which is the point. Snapshot is cached (useSyncExternalStore needs a stable reference). Install guarded for SSR and React 18 double-invocation. Verified no stale `ref.current` remained. `tsc --noEmit` exit 0.

- [ ] **T38 (REQ-40 AC1-AC5): Drag + transparency verified in the packaged Tauri window.**
  DONE = the window drags from the orb and the wheel, stays transparent and undecorated, a drag is not read as a click, and a remount does not strand a drag.
  NOT THIS = switching to `data-tauri-drag-region`, changing the window config, rewriting the hook.
  BLOCKED ON A LIVE TAURI SESSION. Config confirmed correct by inspection (`transparent: true`, `decorations: false`, `shadow: false`, `dragDropEnabled: false`) and `getCurrentWindow` matches the installed Tauri v2 (`@tauri-apps/api ^2.10.1`, `tauri = "2"`). Movement is NOT verified: `useManualDragWindow` "falls back gracefully in browser/dev mode", so every live check this session — all through the web WebSocket path — exercised the fallback, never the real API.

- [ ] **T39 (REQ-38 AC2/AC4): Watch a task survive a real unmount.**
  DONE = start a task, open the dashboard (unmounting the chat view), close it, and see the SAME card still working with its steps intact.
  NOT THIS = asserting on the store in isolation; the point is the round trip through a real mount/unmount.
  Pairs with T38 — both need the packaged widget, and one live session covers both.

**LIVE VERIFICATION — 2026-08-26, backend restarted on current code, conversation `conv-57` created through `POST /api/conversations` (a NEW thread; no existing conversation was touched).** Harness: a WebSocket client that answers `ping` and `permission:request` like a real client. Full event capture in the session scratchpad (`live_verify_events.jsonl`).

| Criterion | Evidence | Verdict |
|---|---|---|
| Delivery is ephemeral (T20) | `shell context injected (129 chars, ephemeral)` then `(304 chars, ephemeral)`; no `add_message` | PASS |
| Retention + index + exact read (T21/T22) | `read_shell_output ref='s1' -> hit (96 chars)`; agent answered *"The exact number printed by the earlier SECRET command was 441928"* | PASS |
| Read tool is gated (T22) | `gated_call tool=read_shell_output tier=read_only mode=developer action=auto_approve` | PASS |
| Shell runs during a turn (T23) | turn started t=37.77; command sent t=39.78, output t=39.85 (**71 ms**); that turn did not finish until t=111.43 | PASS |
| Steer lands during a turn (T24) | `steering:ack` **queued at t=127.553**, 2 ms after send, while the turn ran | PASS |
| Steer applies at a boundary, not mid-step (T24) | `steering:ack considered` at t=264.01 — held through a 62 s `grep_files` step and consumed at the boundary after it | PASS |
| The steer actually redirects the work (T24) | remaining steps re-issued as `steer-4`, `steer-5`; step 4 = *"Read wake word configuration file"* — the steer text, not the original Porcupine search | PASS |

The read-back number is the load-bearing detail: `441928` was generated by `random.randint`, appeared **only** in the retained record behind `ref=s1`, and was absent from the turn's context block. It could not have been produced by paraphrase, by the index line (which carries the command, not the output), or by re-running the command.

**Two harness defects found and fixed during verification — neither is a product defect, but both are worth knowing:**
1. A client that does not answer the server `ping` is disconnected after 30 s (`ws_manager`), which silently truncated the first run.
2. A client that does not answer `permission:request` burns a 120 s timeout per request. In run 3 the agent called `read_shell_output`, then *also* tried `run_command` to re-run the generator — which would have printed a DIFFERENT number and presented it as the original. The permission gate blocked it. Worth noting as model behaviour: the read tool is reachable and correct, but a prompt that does not forbid re-running invites a non-deterministic command to be re-run as a substitute for reading.

**Two permanent diagnostics were added while chasing a false alarm** (a first run where the block came back empty):
- `agent_kernel`: the drain logs its `session_id`, the block length, and the queue's known session ids. The queue and the drain are keyed by `session_id` on opposite sides of the process, and a key mismatch is otherwise silent — empty block, no error.
- `tool_bridge`: `read_shell_output` logs the ref and hit/MISS. A missed read is a silent quality failure, because the agent falls back to re-running the command.

The "empty block" was not a mismatch. It was REQ-24 working: `terminal_output` STREAMS while a command runs, but the `ShellRecord` is queued only after it COMPLETES — and now that `terminal_input` is off the session lock, a turn sent at that moment can win the race and drain an empty queue. See the REQ-24 edge case.

**ADDED TO EXIT GATE 3** (the criteria above are unchanged; these are additional). All three are DEMONSTRATED LIVE, see the table above:
- A `>` command run while the agent is mid-task executes immediately, and its output reaches the agent on the next turn.
- Asking about an earlier command's output makes the agent CALL `read_shell_output` and quote exact bytes, rather than paraphrasing.
- A message sent during a running task revises that task at its next step boundary and does not start a second turn — verified in BOTH personal and developer mode.

**EXIT GATE 3:** every success criterion in `requirements.md` that does not concern packaging:
- `> dir` executes and its output is visible to the agent on the next turn.
- Opening a project tab makes that directory the workdir for `>`, `/run`, **and** the agent's own tools.
- Two conversations run concurrently against two directories with no cross-talk; the cap queues.
- ↑/↓ recall; `/` opens the menu; Ctrl+C aborts — including an agent-launched command.
- A turn that changed code reports its targeted test result, and reports *unverified* when those tests fail.
- ✅ Opens Gate 4.

---

## GATE 4 — The packaged widget

**ENTRY:** Gate 3 exit demonstrated. **Gate 0's observed failure list is in [`GATE0-FINDINGS.md`](./GATE0-FINDINGS.md) — work it first.** The tasks below were written from predictions; Gate 0 already showed the predicted *ordering* was wrong, so treat the findings file as authoritative and these as a checklist.

> Gate 0 found out what actually breaks. This gate fixes it. Work Gate 0's real list first; the tasks below are the *predicted* blockers and may be incomplete or partly wrong.

- [x] **T0f0 (REQ-17 blocker 0): `bundle.resources` schema form.** ✅ DONE in Gate 0 — array-of-objects → map. Listed here so the fix is attributable, not invisible in the diff. Verify it survives any later `tauri.conf.json` edit.

- [ ] **T0f (REQ-17 AC1, AC3, AC4): Updater plugin, bundle targets, cloneable repo.**
  DO: add `nsis` to `bundle.targets`. Add `tauri-plugin-updater` (Cargo + JS), `plugins.updater` with `pubkey` + `endpoints`, `bundle.createUpdaterArtifacts: true`. Register `iris-launcher` in `.gitmodules` with its URL (or vendor it).
  DONE = `iris-launcher/` populates on a clean clone; the updater plugin is registered and configured.
  NOT THIS = the CI workflow, release process, rollback, payload split — launcher spec's (D4).
  RIPPLE: private key to CI secrets only; there is no revocation if it leaks.

- [ ] **T0f2 (REQ-17 AC2): Make the frontend statically exportable.** *(bigger than it looks — not config)*
  DO: repoint chat-view's REST fallback (`chat-view.tsx:1851, 2024, 2080`) at the backend directly and remove `app/api/` — both handlers are `POST` (`app/api/chat/route.ts:12`, `app/api/logs/structured/route.ts:17`) and `output: 'export'` supports only static GET, so the export build fails while they exist. Introduce one runtime base-URL constant and thread it through all 27 relative `fetch("/api/...")` sites. Add `build:static`; repoint `beforeBuildCommand`.
  DONE = `npm run build:static` emits `dist/`, and the packaged widget's chat REST fallback still works when the WS is down.
  NOT THIS = deleting the REST fallback because it is inconvenient (it keeps chat alive when the socket drops); an API-client abstraction or generated SDK; refactoring call sites beyond the base-URL swap.
  RIPPLE: 27 sites across `app/`, `components/`, `lib/`, `hooks/`, `contexts/`. Dev and packaged builds must resolve identically or bugs appear only in the bundle.

- [ ] **T0f3 (REQ-17 AC6): Wire the sidecar rebuild into the release build.**
  DO: put `scripts/build/build_backend.py` on the release path so `src-tauri/binaries/iris-backend-*.exe` is rebuilt from current source. Ensure `llama.cpp/build/bin/Release` (gitignored, referenced by `bundle.resources`) is produced or the bundle step fails loudly.
  DONE = a release build produces a sidecar newer than HEAD, and a missing llama.cpp artifact fails the build rather than shipping a broken bundle.
  NOT THIS = a build-orchestration system, restructuring the PyInstaller spec. Wire the existing script in.
  RIPPLE: the checked-in sidecar is dated **2026-05-07** — roughly four months stale. Without this, the packaged widget runs a backend containing NONE of Gates 1-3.

- [ ] **T0f5 (REQ-20): Make the sidecar actually run.**
  DO: declare which subsystems the bundle supports and which defer to post-install download (AC1). Add the PyInstaller collection flags each supported dependency needs — `HIDDEN_IMPORTS` currently covers only the web stack (`build_backend.py:74-100`) while `requirements.txt` pulls torch, torchaudio, transformers, faster-whisper, pvporcupine. Add `--collect-*`/`--add-data` for model files, `.ppn` assets, and `backend/data/`. Give deferred subsystems an explicit degraded state (AC4). Fail the build when a declared-supported subsystem is missing (AC5).
  DONE = the sidecar starts and serves a real chat turn **on a machine with no Python and no project venv**, and any deferred subsystem reports a named "not installed" state rather than crashing.
  NOT THIS = bundling everything by default (the 38 MB binary vs multi-GB torch is why AC1 exists — decide, declare, do not silently ship a broken bundle); a plugin/component framework; a model downloader UI.
  RIPPLE: this is where REQ-17 AC5's payload split stops being advisory.

- [ ] **T0g (REQ-16): Pin the updater interface the launcher calls.**
  DO: add `GET /api/update/status` and `POST /api/update/check`; define shapes in `types/iris.ts`.
  DONE = the launcher's RebuildPage can replace `mockRebuildStatus` (`RebuildPage.tsx:4`) with a real call and render live values.
  NOT THIS = implementing rebuild, download, install, or rollback. Endpoints + types.

**EXIT GATE 4:**
- A clean clone builds a signed NSIS bundle plus updater artifacts.
- The installed widget launches **on a machine with no Python and no venv**, its sidecar starts, and a real chat turn completes.
- The sidecar in the bundle is newer than HEAD (it contains Gates 1-3).
- Any deferred subsystem reports a named "not installed" state rather than crashing.
- ✅ Opens Gate 5.

---

## GATE 5 — Verification

**ENTRY:** Gate 4 exit demonstrated. Contracts land before behaviour, per CDD.

- [ ] **T15 (REQ-0,1,2,4,12): Contract tests CT-1..CT-6.**
  DO: `tests/contract/test_dev_cli_ws_shapes.py` (cli_* shapes), `test_terminal_capability_gate.py`, `test_question_answer_precedence.py`, `__tests__/slashMenuPrecedence.test.tsx` (`@` beats `/`), `test_scrollback_bound.py` (500 lines), `test_workdir_payload_additive.py`.
  DONE = all six pass, and fail if the interface moves.
  NOT THIS = property-based test infrastructure, a fixture framework, contract-generation tooling. Six files, named above.

- [ ] **T16 (REQ-13,14,15,19): Safety-rail tests.**
  DO: `test_self_edit_isolation.py`, `test_diff_gate_applies.py`, `test_verification_gate.py`. EXTEND `backend/tests/unit/test_tool_errors.py` for the REQ-19 labels — its 17 existing tests stay.
  DONE = each rail fails loudly when its guard is removed; a non-zero exit never produces an `error_type`.
  NOT THIS = testing the worktree implementation or git behaviour; rewriting the FAULTLINE suite. Test the rail; extend the taxonomy tests.

- [ ] **T16b (REQ-18): Search behavior tests.**
  DO: `tests/unit/test_search_tools.py` (mtime ordering, cap + truncation notice, invalid-regex error names the pattern); `tests/contract/test_search_scope.py` (`.gitignore` respected, allowlist honoured, `files_with_matches` returns paths not contents).
  DONE = a search seeded to overflow the cap reports truncation rather than silently returning a short list.
  NOT THIS = benchmarking ripgrep or testing its matching. Test the wrapper's scope, bounds, error surface.

- [ ] **T17 (REQ-0..REQ-20): Behavioral full-loop drives.**
  DO: extend the `scripts/validate_der_*.py` replay family with a dev-cli trajectory: IRIS's own agent runs the turn with no external CLI on PATH; shell → inject → agent turn quotes REAL output; "where is X handled?" resolves via one `grep_files` call with no `node_modules` hits; a failing test surfaces as a non-zero exit and the reviewer does NOT re-run it; two conversations / two workdirs concurrent with zero cross-talk and queueing at cap; `/review` returns a delete-list only; `/debt` produces deduped cards; Ctrl+C kills an endless command; blocked-question state flips the badge without breaking shell parsing.
  DONE = the trajectory runs green in the standing harness on every run.
  NOT THIS = a new test framework, a recording tool, a scenario DSL. Extend the existing family.

**EXIT GATE 5:**
- Contract tests pass and fail correctly when an interface is moved.
- The dev-cli trajectory runs green in the standing harness.
- Gate 0's pre-existing failures are either fixed or explicitly still recorded as pre-existing — never silently absorbed.
- ✅ Spec complete.

---

## What this spec still does NOT deliver

Stated plainly, so a closed Gate 5 is not read as more than it is:

- **The release pipeline.** D4 defers rebuild / download / install / rollback and the CI workflow to the iris-launcher spec — **which does not exist yet and must be written.** Gate 4 produces an installable, signed, updatable bundle; it does not produce a way to ship updates.
- **Agent-to-agent coordination.** Moved to `specs/agent-blackboard-coordination` (REQ-5 scope split).
- **A guarantee.** Gates 1-3 are verified by tests; Gate 4's exit is verified by one packaged build on the machines it was run on. Neither is the same as "no issues."

## Cross-gate notes

- Within a gate, tasks may run in parallel unless a dependency is stated. Across gates, they may not.
- T0h before T7 (search gates the ladder). T0c and T4 depend on T1. T10 depends on T3 and T0b. T13 depends on T2.
- T0i is a data edit depending on nothing, but belongs with T0b/T0c/T2, which introduce the failure modes it labels.
- Former T5 (blackboard coordination records) and T6 (agent-side card sharing) moved to `specs/agent-blackboard-coordination`.
- NO-CHANGE-verified, contract tests only: WorkspaceTabBar, FilePickerModal, types/iris.ts cli_* shapes, capability gate, question-answer resolution.

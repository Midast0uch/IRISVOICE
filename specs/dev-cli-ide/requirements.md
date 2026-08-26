# Requirements: Developer-Mode CLI as IDE (dev-cli-ide)

## Decisions Locked
- **D1 (Shell→agent context): AUTOMATIC.** Every shell command's result (exit code + output) is appended to the agent's conversation context. No opt-in prefix. Token cost accepted; bounded by REQ-12 truncation.
- **D2 (Working directory): Active workspace tab drives workdir**, AND multiple agents must run simultaneously per conversation without system degradation (herdr-inspired isolation: per-session workdir + subprocess + resource caps).
- **D3 (Discipline): FULL ponytail set** (ladder + /review + /debt ledger + intensity levels) **plus a DEPTH ladder** — the agent must not take the shortest surface-level path; it must verify behavior, cover edge cases, and optimize where it matters. Minimalism applies to CODE, never to UNDERSTANDING or VERIFICATION.
- **D4 (Updater): OUT OF SCOPE — deferred to iris-launcher, with a pinned contract.** iris-launcher is how the widget is launched in developer mode; it owns the rebuild / update / rollback pipeline and drives it through the backend API on **:8090** (verified: `backend/main.py:1028-1062` launcher mode, `:1254` launcher status, `:1431` git+diff API "Domain 13.1 — iris-launcher developer mode"; the launcher UI itself is a Vite/Tauri app on :8080 — `iris-launcher/package.json`). Two things this spec must still do, because the launcher cannot supply them: (a) name the interface the launcher will call (REQ-16), and (b) land the widget-repo build config the pipeline depends on, which lives in `src-tauri/` and `next.config.mjs` and therefore cannot live in the launcher's repo (REQ-17). Everything else — release cadence, rollback UX, split payloads, CI — stays with the launcher spec.
- **D5 (Rendering): chat messages and shell lines are NOT visually unified.** Shell output reaches the agent via context (D1), not by merging streams in the UI.
- **D6 (User intent):** developer mode is for working on NEW and EXISTING projects, including adjusting IRIS's own code. The CLI must feel like a built-in IDE code environment.
- **D7 (External dev CLIs): REMOVED.** Routing dev work to kilo / claude / opencode (`backend/dev/cli_tools.yaml`) was a months-old stopgap. It is superseded: driving through a third-party coding platform loses IRIS's memory robustness — the coordinate graph, the ledger, and the conversation context do not follow the work into another tool. `dev_cli` routes to IRIS's own AgentKernel (REQ-0). The registry is deleted, not demoted.
- **D8 (Anti-overcoding is policy, not prose): the SCOPE BOUND is a first-class part of every task.** Each task in `tasks.md` carries an explicit `DONE =` line and a `NOT THIS =` line. The agent's output is measured against those two lines, not against its own sense of completeness. This is the same policy framework as the AGENTS.md / CLAUDE.md minimality ladder, applied at task granularity so it binds before code is written rather than after.

## Introduction
Developer mode's ChatView must operate as a real CLI/IDE code environment driven by **IRIS's own agent**: working shell, agent-visible shell results, per-project working directories, parallel agent sessions, and a discipline system that produces minimal-but-deep code. The end state is IRIS building IRIS — so the spec also covers what that requires and what it risks: the agent must reach directories other than its own repo, its self-edits must land in a sandbox before the live tree, and a turn that changed code must have actually run the tests. This spec closes the verified gaps (external-CLI routing, agent pinned to the IRIS root, missing shell handler, dead workdir, decorative diff gate, no history/autocomplete/abort) and integrates ponytail concepts without cloning the repo.

### Success criteria
- `/run` executes a turn on **IRIS's own agent** with no external coding CLI installed on PATH.
- `> dir` in developer mode executes a real shell command and its output appears in the terminal panel AND is visible to the agent on the next turn.
- Opening a project tab via "+" makes that tab's directory the workdir for subsequent `>` and `/run` commands **and for the agent's own file/git/shell tools** — the agent edits the project on screen, not IRISVOICE.
- An agent edit to IRIS's own source lands in the sandbox worktree; approving it in the diff gate produces a real commit; rejecting it leaves nothing on disk.
- A dev turn that changed code reports the targeted test result, and reports *unverified* when those tests fail.
- Two conversations run shell/agent sessions against two different directories concurrently with no cross-talk and bounded memory.
- ↑/↓ recalls past commands; typing `/` opens a command menu; Ctrl+C aborts a running command — including an agent-launched one.
- The agent finds "where is X handled?" in ONE `grep_files` call scoped to the active project, without walking `node_modules`, and gets paths back rather than a context flood.
- A shell failure reaches the DER reviewer with a FAULTLINE label whose `retryable` dimension is correct, and a failing test surfaces as a non-zero exit rather than as a tool error.
- A dev-mode task executed by the agent shows ladder + depth-ladder adherence AND scope-bound adherence (no over-build, no surface-level pass, no work outside the task's `NOT THIS`) as a structured verdict in the ledger.
- A clean `git clone` builds a signed, updatable widget bundle, and iris-launcher can read live update status from :8090 instead of mock data.
- The installed widget launches on a machine with no Python and no venv, its sidecar starts, and a real chat turn completes.

## Requirements

> ### ⚠ HOW THESE WERE VERIFIED — read before trusting any "Verified:" line
>
> **21 requirements carry a `**Verified:**` claim. Exactly one — REQ-17 — was verified by RUNNING something. The other twenty were verified by READING code.**
>
> Gate 0 measured the accuracy of the reading method on the one requirement where predictions could be tested against reality (REQ-17, 9 predicted blockers vs. an actual `tauri build`):
>
> | outcome | count |
> |---|---|
> | confirmed as predicted | 3 |
> | confirmed, but stated mechanism was wrong | 1 |
> | **wrong on severity, in a way that changed the fix's urgency** | **1** |
> | **missed entirely** | **3** |
>
> Roughly **a third of the real blockers were absent from the spec**, and the predicted *ordering* was wrong — the first thing the build actually hit (a config-schema error) was not in the spec at all and made every predicted blocker unreachable.
>
> **Apply the same discount to every READ-verified claim below.** They are good hypotheses with precise file:line evidence — they are not observations. Specifically:
> - A file:line citation proves the code *exists as written*. It does not prove the code *runs*, or that running it produces the described effect. (Gate 0 found a 45-line config block whose own comment asserted it applied to production builds; it never executed.)
> - "No X exists" claims are the weakest kind — absence is hard to prove by reading.
>
> **What Gate 1+ should do about it:** before building against a READ-verified claim, spend the two minutes to *execute* the thing — call the tool, run the file, add a marker — and correct the requirement if it disagrees. A wrong prediction is information (REQ-21 AC3), not an embarrassment to hide.


### REQ-0: `dev_cli` runs IRIS's own agent (external CLI registry removed)
**User Story:** As the owner of IRIS I want developer mode to run IRIS's agent, not a third-party coding CLI, so that the work keeps IRIS's memory — coordinate graph, ledger, conversation context — instead of losing it into another tool's process.
**Verified:** REAL GAP — `dev_cli` does not run the IRIS agent today. `backend/dev/cli_tools.yaml` registers three external executables (`kilo`, `claude`, `opencode`); `backend/dev/orchestrator.py:73-79` replies *"No CLI tools are available on PATH. Install kilo, claude, or opencode first."* when none is present. Every `/run` is a subprocess handoff to a foreign agent.
**Acceptance Criteria:**
- AC1: WHEN a `dev_cli` message arrives THEN THE SYSTEM SHALL dispatch it to the IRIS AgentKernel turn path, in the session's workdir (REQ-4), with the session's conversation context — NOT to an external executable.
- AC2: THE SYSTEM SHALL delete `backend/dev/cli_tools.yaml` and `backend/dev/cli_registry.py`, and remove `_select_tool` and the tool-selection LLM call from `backend/dev/orchestrator.py`.
- AC3: THE SYSTEM SHALL keep `DevOrchestrator`'s surviving responsibilities — subprocess lifecycle, output streaming, file-watcher wiring, `cli_started`/`cli_activity`/`cli_output` emission — so the frontend contract (types/iris.ts:258-272) is unchanged.
- AC4: `GET /api/dev/cli-tools` (`backend/main.py:1221`) SHALL return IRIS's own dev command surface (the REQ-7 command list), making it the single source of truth the slash menu reads — not a second hardcoded list.
- AC5: IF an external CLI is ever wanted again THEN it SHALL enter as a normal agent tool through `tool_registry.py`, never as a routing layer above the agent.
- AC6: THE SYSTEM SHALL update the three artifacts that consume the deleted registry. Found via `pin_c30f0b9f8547` (session 240, 2026-08-19, task T13c) — NOT by reading the code, which is why the original Ripple map missed them:
  - `backend/tests/contract/test_cli_tools_endpoint.py` — an **existing contract test** that asserts the endpoint surfaces `cli_tools.yaml` (`:7`, `:25`). Deleting the YAML turns this test red.
  - `components/terminal/HelpPanel.tsx:63` — renders "Available delegate tools" with per-tool availability.
  - The `/help` local answer path in `chat-view.tsx` that feeds the panel.
- AC7: **THE SPEC-VS-TEST CONFLICT IS RESOLVED HERE, IN WRITING — the agent SHALL NOT resolve it at build time.** `test_cli_tools_endpoint.py` pins two separate things: (a) *the endpoint surfaces a registry rather than a hardcoded copy*, and (b) *that registry is `cli_tools.yaml`*. Claim (a) SURVIVES and REQ-0 AC4 preserves it. Claim (b) is the thing D7 deletes. The test's **subject** changes; its **assertion intent** does not. Per THE TEST RULE (AGENTS.md), this update SHALL be called out explicitly in the task report, never made silently. Re-pointing the test at IRIS's own command surface is correct; weakening or deleting the test is not.

**Edge Cases:** an in-flight external subprocess at upgrade time (none survive a restart — no migration needed); `tool_hint` field present in an old client payload (ignored, not an error); HelpPanel rendering an empty delegate list mid-migration (show IRIS's own commands, never an empty modal).

### REQ-1: Direct shell execution
**User Story:** As a developer-mode user I want `> <command>` to run a real shell command so that the CLI behaves like a terminal.
**Verified:** REAL GAP — `backend/iris_gateway.py:10495` imports `backend/dev/terminal_handler.py` which does not exist; every `>` command errors out. `backend/dev/` contains only cli_registry.py, cli_tools.yaml, file_watcher.py, orchestrator.py, subprocess_manager.py.
**Acceptance Criteria:**
- AC1: WHEN the user sends `terminal_input` with a non-empty line THEN THE SYSTEM SHALL execute the line in a persistent per-session shell subprocess and emit output events (`terminal_output` or equivalent) to the originating client.
- AC2: THE SYSTEM SHALL preserve shell state (cwd, env) across commands within one session.
- AC3: IF the shell subprocess dies THEN THE SYSTEM SHALL restart it on the next input and report the restart in the output stream.
- AC4: WHEN developer mode is not active THEN THE SYSTEM SHALL reject `terminal_input` with the existing capability-gate error (verified: iris_gateway.py:10486-10492 — NO CHANGE).
- AC5: THE SYSTEM SHALL execute the agent's `run_command` and `git_*` tools through the SAME `ShellSession` as user-typed `>` commands. Verified need: `backend/agent/tool_bridge.py:1830` runs a one-shot `subprocess.run(shell=True, timeout=120)` — no cwd/env persistence, no output bound, no abort path, and its output never reaches REQ-2 injection. Two substrates means the user's shell is bounded and the agent's is not, and REQ-8's abort cannot stop the runaway case that actually matters (an agent-launched command).
- AC6: THE SYSTEM SHALL emit the event named in the contract — `terminal_output` (types/iris.ts:258-272, CT-1). AC1's "or equivalent" is withdrawn; a CONTRACT LOCK and an unnamed event cannot coexist.
**Edge Cases:** empty line (toggle terminal — existing behavior, chat-view.tsx:1675-1683); command producing unbounded output (truncated per REQ-12); command never exiting (REQ-8 abort + idle timeout); agent command and user command interleaved in one session (serialized on the session shell — the shell is single-threaded by construction).

### REQ-2: Automatic shell→agent context
**User Story:** As a developer-mode user I want the agent to see what my shell commands did so that follow-up requests build on real state, not guesses.
**Verified:** REAL GAP — shell output currently goes to scrollback only; no path into agent context.
**Acceptance Criteria:**
- AC1: WHEN a shell command completes THEN THE SYSTEM SHALL append a structured record (command, exit code, truncated output) to the session's agent context before the next agent turn.
- AC2: THE SYSTEM SHALL render the injected record in the chat as a compact system notice (one line), NOT as a full chat message (D5).
- AC3: IF output exceeds the truncation budget THEN THE SYSTEM SHALL inject head+tail with an elided-marker and full output remains in the terminal panel.
- AC4: THE SYSTEM SHALL redact secrets from output BEFORE injection, against a named pattern set — `AWS[A-Z0-9]{16,}`, `gh[pousr]_[A-Za-z0-9]{16,}`, `sk-[A-Za-z0-9]{20,}`, `-----BEGIN [A-Z ]*PRIVATE KEY-----`, `[A-Za-z0-9+/]{40,}={0,2}` when preceded by a `key|token|secret|password` assignment — replacing each match with `[REDACTED:<kind>]`. THE SYSTEM SHALL additionally never inject output from commands whose target matches the deny-list (`.env*`, `*.pem`, `*.key`, `*_rsa`, `id_*`, keyring paths); such commands render in the terminal panel only, with a one-line notice that injection was suppressed. Rationale: D1 makes injection AUTOMATIC and the workdir is the user's repo — `> cat .env` and `> git remote -v` are ordinary commands, and for a cloud-routed model injection means the bytes leave the machine.
- AC5: THE SYSTEM SHALL enforce a per-turn AGGREGATE injection budget (default 24 KB) across all queued records, evicting oldest-first and emitting one `N earlier commands elided` marker. REQ-12 AC2's 8 KB bounds a single command; without an aggregate bound, twenty `> pytest` runs between turns inject 160 KB.
**Edge Cases:** binary/non-UTF8 output (sanitize); agent turn in flight (queue to next turn); redaction pattern matches legitimate output (accepted — false positives are cheap, leaks are not).

### REQ-3: Split rendering (de-unify)
**User Story:** As a developer-mode user I want chat and terminal as separate surfaces so that neither pollutes the other.
**Verified:** CHANGE NEEDED — `components/chat-view.tsx:706-722` (`unifiedTimeline`) and `:731` (`renderTimeline`) merge shell lines into the chat stream.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL render chat messages and shell lines in separate surfaces (chat stream vs terminal panel/slide-over).
- AC2: WHEN a shell command completes THEN THE SYSTEM SHALL surface the terminal panel state (new output indicator) without scrolling chat.
- AC3: THE SYSTEM SHALL preserve the existing question-answer resolution path (chat-view.tsx:1623-1637 — NO CHANGE).
**Edge Cases:** terminal panel closed when output arrives (badge/indicator); conversation switch (per-conversation scrollback already persisted by store).

### REQ-4: Active-tab working directory
**User Story:** As a developer-mode user I want the active workspace tab's directory to be the shell/agent workdir so that "+" tab = switching project context.
**Verified:** REAL GAP — `dev_cli` payload sends `{query}` only (chat-view.tsx:1670); backend accepts `workdir` (backend/dev/orchestrator.py:5, types/iris.ts:261). Workspace tabs carry `path` (WorkspaceTabBar.tsx:91-99) but it is unwired.
**Acceptance Criteria:**
- AC1: WHEN a workspace tab with a local directory path is active THEN THE SYSTEM SHALL send that path as `workdir` on every `terminal_input` and `dev_cli` message.
- AC2: WHEN no tab is active THEN THE SYSTEM SHALL omit `workdir` and the backend SHALL use its default.
- AC3: IF the workdir does not exist or is inaccessible THEN THE SYSTEM SHALL reject the command with an explicit error naming the path.
- AC4: THE SYSTEM SHALL display the effective workdir in the terminal panel header/prompt indicator.
- AC5: THE SYSTEM SHALL bind the resolved session workdir into the AGENT's tool-execution context, so `run_command`, `git_*`, and the file tools operate in the active tab's directory. **Verified blocker:** `backend/agent/tool_bridge.py:1742-1757` resolves cwd from a hardcoded `_DEFAULT_REPO` (`<tool_bridge.py>/../..` = the IRISVOICE root, `:1738-1740`) and then *hard-rejects* anything else — `if not cwd.startswith(repo_root): return {"error": "Working directory ... is outside the project root. Aborting."}`. Wiring `workdir` onto the WS payload alone changes nothing for the agent: open a tab on another project, ask the agent to fix it, and it silently edits IRISVOICE instead. This makes D6 ("NEW and EXISTING projects") structurally impossible and is a correctness bug, not a nicety.
- AC6: THE SYSTEM SHALL replace the `startswith(_DEFAULT_REPO)` guard with an allowlist of registered workspace roots, sourced from the existing project registry (`GET /api/projects`, `backend/main.py:1288`). A path under no registered root SHALL be rejected with the same explicit error. `_DEFAULT_REPO` remains the fallback ONLY when no tab is active. The guard is currently the only thing preventing the agent from running shell commands anywhere on disk — it must be replaced, never merely deleted.
**Edge Cases:** virtual (isVirtual) tabs — no filesystem path, excluded from workdir binding; path with spaces/unicode; tab closed mid-command (in-flight command completes in its original workdir); tab path not in the project registry (rejected — the user registers it via the launcher's ProjectsPage first).

### REQ-5: Parallel agent sessions (process isolation)
> **SCOPE SPLIT.** The blackboard-coordination half of this requirement (former AC6-AC11: coordination record types in `.mcm/coordinates.db`, pointer-only WS doorbell, task-card-as-agent-pointer) moves to its own spec, `specs/agent-blackboard-coordination`. Reasons: (a) nothing in REQ-0..REQ-4 needs agent-to-agent coordination — the stated success criterion "two conversations, two directories, no cross-talk" is satisfied by AC1-AC5 alone; (b) it was the largest scope item and the least connected to "the CLI works"; (c) it adds record types to `.mcm/coordinates.db`, which CLAUDE.md commits to transferring into the *application runtime store* at hand-off via `scripts/migrate_build_store_inheritance.py` — a migration obligation that belongs in a spec that owns it. Tasks T5/T6 move with it. T14 (session-state badge) stays here and is decoupled — REQ-5 AC3's four states are derivable from `cli_*` events alone.

**User Story:** As a developer-mode user I want multiple conversations each running agents/shells against different projects simultaneously so that I can work in parallel without crashes or cross-talk.
**Verified:** PARTIAL — DevOrchestrator "manages active subprocess lifecycle" per call (backend/dev/orchestrator.py:39); no global concurrency cap, no per-session resource bounds, no state surfacing, no coordination records.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL scope each conversation's shell subprocess, workdir, and agent context independently (no shared mutable state across sessions).
- AC2: THE SYSTEM SHALL enforce a global cap on concurrent dev subprocesses (default 4, configurable) and queue or reject beyond it with an explicit message.
- AC3: THE SYSTEM SHALL surface per-session state (idle / working / blocked-awaiting-question / done) in the UI so parallel sessions are monitorable at a glance.
- AC4: IF a session's subprocess exceeds its output-rate or memory bound THEN THE SYSTEM SHALL terminate it and mark the session failed with the reason.
- AC5: THE SYSTEM SHALL bound total retained scrollback per session (existing 500-line bound — terminalScrollback.ts, verified — CONTRACT LOCK).
- AC6: THE SYSTEM SHALL count agent-invoked commands (REQ-1 AC5) against the same global cap as user-typed commands — one budget, not two.
**Edge Cases:** same directory targeted by two sessions (allowed; last-write-wins at the filesystem — conflict detection is the blackboard spec's problem, not this one's); backend restart (sessions rebuild lazily, no state to recover); cap reached (queue with position shown).

### REQ-6: Command history
**User Story:** As a CLI user I want ↑/↓ to recall previous commands so that the input feels like a shell.
**Verified:** REAL GAP — no ArrowUp/ArrowDown handling in chat-view.tsx; terminalScrollback.ts comments claim history persistence but the store does not implement it.
**Acceptance Criteria:**
- AC1: WHEN the input is focused and empty-or-recalling THEN ArrowUp SHALL recall the previous distinct command and ArrowDown the next, ending at the live draft.
- AC2: THE SYSTEM SHALL persist history per conversation via the terminalScrollback store's rehydration path. (Decided: NOT localStorage — the widget runs in a Tauri webview where localStorage is per-webview and is cleared on some reinstall paths.)
- AC3: THE SYSTEM SHALL bound stored history (default 200 entries, oldest evicted).
**Edge Cases:** draft text present on first ArrowUp (stashed and restored on return); multi-line draft (skip recall — textarea needs arrows); identical consecutive commands (deduped).

### REQ-7: Slash-command autocomplete
**User Story:** As a CLI user I want a command menu when typing `/` or `>` so that I can discover the CLI surface.
**Verified:** REAL GAP — no autocomplete exists.
**Acceptance Criteria:**
- AC1: WHEN input starts with `/` THEN THE SYSTEM SHALL show a filtered menu of available commands with one-line descriptions, sourced from `GET /api/dev/cli-tools` (REQ-0 AC4) — NOT a second hardcoded list in the frontend. Initial surface: /run, /help, /review, /debt, /term, /clear.
- AC2: WHEN input starts with `>` THEN THE SYSTEM SHALL show a hint row (workdir + "shell mode") without blocking typing.
- AC3: WHEN the user accepts a menu item (Tab/Enter/click) THEN THE SYSTEM SHALL insert the command with trailing space and keep focus in the input.
- AC4: IF input no longer starts with the trigger THEN THE SYSTEM SHALL dismiss the menu.
**Edge Cases:** menu open while voice listening (input disabled — menu suppressed); Escape closes menu without clearing input; menu must not hijack the @taskcard picker (chat-view.tsx:4312 — CONTRACT LOCK).

### REQ-8: Abort running work
**User Story:** As a CLI user I want Ctrl+C (and an on-screen stop) to abort the running command/agent turn so that I am never stuck watching a runaway process.
**Verified:** REAL GAP (half-built) — backend `_handle_dev_abort` exists (iris_gateway.py:10451) and orchestrator has `abort_session`; no frontend wiring.
**Acceptance Criteria:**
- AC1: WHEN the user presses Ctrl+C in the input WHILE a dev subprocess is running THEN THE SYSTEM SHALL send `dev_abort` and the backend SHALL terminate that session's subprocess tree.
- AC2: WHEN abort succeeds THEN THE SYSTEM SHALL log the abort line to the terminal panel and restore input focus.
- AC3: IF nothing is running THEN Ctrl+C SHALL clear the input line (standard shell semantics).
**Edge Cases:** subprocess ignores termination (escalate to tree-kill after grace period); abort during agent turn (turn cancelled, partial output retained); double-abort (idempotent).

### REQ-9: Discipline ladder (ponytail + depth)
**User Story:** As a developer-mode user I want the agent to write minimal code AND go deep on understanding/verification so that results are neither over-built nor surface-level.
**Verified:** NEW — no ladder exists; IRIS AGENTS.md quality-check philosophy is the seed.
**Acceptance Criteria:**
- AC1: WHEN developer mode is active THEN THE SYSTEM SHALL inject the discipline ruleset into the agent system prompt: the MINIMALITY ladder (1 need exist? → 2 already in codebase? → 3 stdlib? → 4 platform-native? → 5 installed dep? → 6 one line? → 7 minimum that works) followed by the DEPTH ladder (a read the code the change touches before writing; b trace the real flow; c enumerate edge cases handled; d verify with the project's own tests; e optimize only measured hot paths).
- AC2: THE SYSTEM SHALL state in the ruleset that rungs run AFTER understanding, never instead of it, and that validation, error handling, security, and accessibility are never cut.
- AC3: THE SYSTEM SHALL support intensity levels (lite / full / ultra / off) persisted per workspace, selectable from the workspace bar.
- AC4: WHEN the agent spawns DER sub-workers THEN THE SYSTEM SHALL inherit the active ruleset into their prompts.
- AC5: IF intensity is off THEN THE SYSTEM SHALL inject nothing.
- AC6: THE SYSTEM SHALL inject the task's SCOPE BOUND (D8) alongside the ruleset when the turn is executing a spec task: the task's `DONE =` line and `NOT THIS =` line, verbatim. The ladder answers "how small"; the scope bound answers "how far" — and the second is what actually prevents over-coding, because a ladder with no boundary still lets the agent decide that more is in scope.
- AC7: THE SYSTEM SHALL make ladder adherence MEASURABLE, not merely asserted. `/review` (REQ-10) SHALL emit a structured verdict per changed file — `{file, rung_violated, scope_violated: bool, delete_list: [...]}` — and REQ-12 AC1 SHALL log that verdict to the ledger. Without this, "adherence verifiable in the ledger" is an unfalsifiable claim: REQ-12 currently logs only *intensity changes*, which says nothing about whether the model followed the ruleset.
**Edge Cases:** prompt budget (ruleset compact, <600 tokens; scope bound adds <80); non-dev modes unaffected; model ignores ladder (AC7's verdict is the detection path — the ledger records the violation and `/review` surfaces it before commit); no active spec task (AC6 injects nothing, ruleset still applies).

### REQ-10: /review — delete-list diff review
**User Story:** As a developer-mode user I want `/review` to audit the current diff for over-engineering and return a delete-list so that bloat is removed before commit.
**Verified:** NEW — ponytail-review concept; IRIS has git access via shell (REQ-1) and agent delegation (/run).
**Acceptance Criteria:**
- AC1: WHEN the user sends `/review` THEN THE SYSTEM SHALL delegate to the agent with a review contract: output ONLY a delete-list (what to remove/simplify + why), never a rewrite.
- AC2: WHEN `/review` targets a scope argument (`/review src/foo.py`) THEN THE SYSTEM SHALL limit the diff to that path.
- AC3: IF the diff is empty THEN THE SYSTEM SHALL report "no changes to review" without an agent call.
**Edge Cases:** huge diff (chunk by file); review of IRIS's own code (allowed — D6); no git repo in workdir (explicit error).

### REQ-11: /debt — deferred-work ledger
**User Story:** As a developer-mode user I want `ponytail:`-style deferred markers harvested into a ledger so that "later" never becomes "never".
**Verified:** NEW — ponytail-debt concept; IRIS task-card system (taskProgress.cards) is the ledger surface.
**Acceptance Criteria:**
- AC1: WHEN the user sends `/debt` THEN THE SYSTEM SHALL scan the active workdir for deferred markers (`ponytail:`, `TODO(deferred):`, `IRIS-DEBT:`) and render each as a task card tagged `debt`.
- AC2: THE SYSTEM SHALL dedupe cards by file:line across repeated runs.
- AC3: IF no markers are found THEN THE SYSTEM SHALL report a clean ledger.
**Edge Cases:** markers inside vendored/node_modules dirs (excluded); binary files (skipped); very large repos (scoped to workdir root + src, bounded depth).

### REQ-12: Observability & budgets
**User Story:** As the tuner I want measured signals on CLI usage, context injection size, and ladder adherence so that I can tune truncation budgets and intensity defaults.
**Verified:** NEW
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log (timestamped, session-scoped): shell dispatch, output size, injected-context size, abort events, ladder intensity changes, and the REQ-9 AC7 adherence verdict (rung violated, scope violated).
- AC2: THE SYSTEM SHALL enforce a configurable output-truncation budget (default 8 KB injected / 2 KB chat notice) and a scrollback bound (500 lines, existing).
- AC3: THE SYSTEM SHALL keep all logging off the user-visible latency path (fire-and-forget).
**Edge Cases:** log write failure (silent, never blocks command); clock skew (monotonic ordering by event sequence).

### REQ-13: Self-edit isolation
**User Story:** As the owner of IRIS I want the agent's edits to IRIS's own source to land in a sandbox first so that a bad change cannot brick the running assistant.
**Verified:** REAL GAP in the SPEC, not the code — D6 explicitly covers "adjusting IRIS's own code" but no requirement addresses the case where the workdir IS the running source. The infrastructure already exists and is unused: `ensure_worktree()` (`backend/git_ops.py:191`) and `/api/git/worktree/ensure|commit|merge|reset` (`backend/main.py:1518-1546`).
**Acceptance Criteria:**
- AC1: WHEN the resolved workdir is the IRIS repo root THEN THE SYSTEM SHALL route the agent's file writes into the sandbox worktree (`ensure_worktree()`), NOT the live tree.
- AC2: THE SYSTEM SHALL require an explicit user action to promote worktree changes to the main tree (`/api/git/worktree/merge`); the agent SHALL NOT self-promote.
- AC3: THE SYSTEM SHALL display, in the terminal panel header, that the session is operating in the sandbox worktree and not the live tree.
- AC4: WHEN the agent edits a Python module currently loaded by the running backend THEN THE SYSTEM SHALL note it in the turn result ("this change requires a backend restart to take effect") — no auto-restart.
**Edge Cases:** worktree creation fails (REJECT the write with an explicit error — never silently write live); user's own `>` commands (NOT redirected — the user's shell is the user's shell); non-IRIS workdirs (AC1 does not apply, writes go direct).

### REQ-14: Working diff-review gate
**User Story:** As the owner of IRIS I want approve/reject on a pending write to actually apply or discard it so that the review step is a gate, not a log.
**Verified:** REAL GAP — `approve_write` / `reject_write` (`backend/git_ops.py:161-176`) only set `w["status"] = "approved"|"rejected"` and return ok. Nothing is applied to disk, nothing is committed, despite `backend/main.py:1478` documenting it as *"Approve a pending write — apply to disk and commit."* The agent has already written to disk by the time review happens: the queue is filled by a **post-hoc** session-end scan (`backend/sessions/session_manager.py:286-336`). `_pending_writes` is a module-level list (`git_ops.py:139`) — unbounded, process-global, lost on restart, and in direct violation of this spec's own REQ-5 AC1 ("no shared mutable state across sessions").
**Acceptance Criteria:**
- AC1: `approve_write` SHALL apply the queued change to the target tree and commit it, returning the commit hash; `reject_write` SHALL discard it (worktree reset for that path) so the change does not survive.
- AC2: THE SYSTEM SHALL scope the pending-write queue per session and bound it; it SHALL survive a backend restart, or SHALL be explicitly rebuilt from the worktree diff on startup — silent loss is not acceptable for a safety gate.
- AC3: THE SYSTEM SHALL make the queue a PRE-apply gate for agent writes under REQ-13 AC1 (worktree -> review -> promote), keeping the session-end scan only as a backstop for writes that bypassed it.
**Edge Cases:** approve on a path since modified by the user (conflict reported, not force-applied); approve after backend restart (AC2 rebuild path); queue empty (no-op, not an error).

### REQ-15: Verification gate on agent turns that edited files
**User Story:** As the owner of IRIS I want a dev-mode turn that changed code to have actually run the project's tests so that "done" means verified, not plausible.
**Verified:** NEW — REQ-9 AC1(d) ("verify with the project's own tests") is prompt text today. Nothing in the system checks it. For self-building this is the difference between IRIS shipping a green change and IRIS shipping a convincing one.
**Acceptance Criteria:**
- AC1: WHEN a dev-mode agent turn wrote to one or more files THEN THE SYSTEM SHALL run the project's targeted test command for the touched paths and attach the result (pass/fail + failing test names) to the turn result.
- AC2: THE SYSTEM SHALL run TARGETED tests, not the full suite — scoped to the touched paths and their direct test files. (Full-suite runs are slow enough here that the agent will learn to skip the gate, which defeats it.)
- AC3: IF tests fail THEN THE SYSTEM SHALL report the turn as unverified and surface the failure; it SHALL NOT report success.
- AC4: IF no test file maps to the touched paths THEN THE SYSTEM SHALL say so explicitly ("no covering test") rather than reporting a pass.
**Edge Cases:** non-code file edited (skip, note it); test command not discoverable for the workdir (report "no test command configured", never assume green); test run counts against the REQ-5 cap like any other command.

### REQ-16: Updater interface contract (implementation deferred to iris-launcher)
**User Story:** As the owner of IRIS I want the widget-to-launcher update interface pinned here so that the launcher spec has something concrete to implement against.
**Verified:** REAL GAP — the launcher's rebuild pipeline is a UI mock: `iris-launcher/src/pages/RebuildPage.tsx:4` imports `mockRebuildStatus` from `@/lib/mock-data`, the "Trigger Rebuild" button has no handler, the five pipeline steps are hardcoded JSX, and `iris-launcher/src/lib/iris-api.ts` exposes no rebuild or update method at all. D4 defers correctly, but it currently defers to nothing callable.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL expose, on the backend (:8090), the endpoints the launcher's RebuildPage needs: `GET /api/update/status` (current version, available version, last-good commit, rebuild-required flag) and `POST /api/update/check`.
- AC2: THE SYSTEM SHALL define the response shapes in `types/iris.ts` so both repos compile against one definition.
- AC3: THIS SPEC SHALL NOT implement the rebuild, download, install, or rollback behavior — only the interface and the build config (REQ-17). The pipeline is the launcher spec's.
**Edge Cases:** launcher polls while no release channel is configured (returns `configured: false`, not an error).

### REQ-17: Build prerequisites for the update path
**User Story:** As the owner of IRIS I want the widget repo to actually produce an updatable, signed bundle so that the launcher's pipeline has something to install.
**Verified — GATE 0 RUN 2026-08-25, see `GATE0-FINDINGS.md`.** Predictions below were tested against a real `tauri build`. One blocker was missed entirely and precedes all of them; one mechanism was stated wrongly. Blockers, in the order the build actually hits them:

  0. **(G0-01 — NOT PREDICTED, now fixed)** `tauri build` aborted at config-schema validation: `bundle > resources` used the array-of-objects form `[{"src":…,"target":…}]`, which Tauri v2 rejects — it takes an array of strings or a map of `path → target`. This fired **before** `beforeBuildCommand`, before the Rust compile, and before the `dist` check, making every blocker below unreachable. Minimal unblock applied during Gate 0: `"resources": { "../llama.cpp/build/bin/Release": "llama-server" }`.

Original four blockers, all in THIS repo (none can live in the launcher's repo):
  1. `src-tauri/tauri.conf.json` `bundle.targets` is `["msi","deb","appimage"]`. **MSI cannot self-update** — Tauri's Windows updater path requires **NSIS**. *(Not yet reached by a build — the run did not get past bundling.)*
  2. `frontendDist` is `"../dist"`, but `next.config.mjs` has no `output: 'export'` and defines `rewrites()`, which is *incompatible* with static export. `npm run build` produces `.next`. **CORRECTED by Gate 0 (G0-02):** the npm build itself **succeeds cleanly** (exit 0, Next.js 16.2.6, 10 static pages) — the spec previously implied it fails. The defect is solely that its output location and `frontendDist` disagree, so `dist/` is never produced. Conclusion unchanged; mechanism restated.
  3. No `tauri-plugin-updater` in `src-tauri/Cargo.toml`, no `plugins.updater` block, no signing pubkey, no `bundle.createUpdaterArtifacts`.
  4. `iris-launcher` is committed as a gitlink (mode `160000` @ `555a40b1`) with **no `.gitmodules` entry** — `git clone` yields an empty directory and no URL to fetch from, so the component D4 defers to is unbuildable from the repo as pushed.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL add `nsis` to `bundle.targets` (MSI retained for first-install distribution only).
- AC2: THE SYSTEM SHALL produce `frontendDist` reproducibly: a `build:static` script with `output: 'export'` and `beforeBuildCommand` repointed at it. This is NOT a config-only change — three things must move with it:
  - **AC2a — POST route handlers must go.** `app/api/chat/route.ts:12` and `app/api/logs/structured/route.ts:17` are both `POST`. **CORRECTED by Gate 0 (G0-03): the export build does NOT fail on them.** It succeeds, warns about `rewrites`, and **silently omits `api/` from the output** — verified: `out/` had no `api/` directory. That is worse than a build failure: the widget packages, ships, and `/api/chat` 404s at runtime, killing the REST fallback precisely when the WS is already down. `/api/chat` is not dead code — it is chat-view's live REST fallback when the WS is unavailable (`chat-view.tsx:1851, 2024, 2080`). That fallback SHALL be repointed at the backend directly; `app/api/` SHALL then be removed. Deleting the fallback outright is not acceptable — it is the path that keeps chat working when the socket drops.
  - **AC2b — the 27 relative `/api` call sites must resolve without rewrites.** Static export drops `rewrites()`, so every `fetch("/api/...")` (27 sites across `app/`, `components/`, `lib/`, `hooks/`, `contexts/`) breaks. A single runtime base-URL constant SHALL be introduced and threaded through all of them.
  - **AC2c — packaged and dev builds must agree.** The base URL resolves to the rewrite-free backend origin in both modes, so a bug cannot appear only in the packaged widget.
  - **AC2d — the output directory must match `frontendDist`.** *(Gate 0, G0-03b — NOT previously predicted.)* Static export emits to **`out/`**, while `tauri.conf.json` sets `frontendDist: "../dist"`. Enabling `output: 'export'` alone therefore does not resolve AC2 — `distDir` must be set, or `frontendDist` repointed to `../out`. (This also explains the stale checked-in `dist/`: its layout matches `out/` exactly, so it was produced by an export build and placed by hand. Nothing in the current build path reproduces it.)
- AC6: THE SYSTEM SHALL rebuild the backend sidecar as part of the release build. Verified: `src-tauri/binaries/iris-backend-x86_64-pc-windows-msvc.exe` is dated **2026-05-07** — roughly four months stale against the current backend, and `scripts/build/build_backend.py` is wired into no build path. A widget that launches a four-month-old backend is not a working widget, and none of this spec's backend work (REQ-0/1/4/13/14/15/18/19) would be present in it.
- AC3: THE SYSTEM SHALL add `tauri-plugin-updater` (Cargo + JS), a `plugins.updater` block with `pubkey` and `endpoints`, and `bundle.createUpdaterArtifacts: true`. The private key SHALL live in CI secrets only — never in the repo. (There is no key-revocation mechanism: a leaked key means every installed client trusts the attacker's payload.)
- AC4: THE SYSTEM SHALL register `iris-launcher` as a real submodule with its URL in `.gitmodules`, or vendor it into the repo — a clean clone SHALL build.
- AC5: THE SYSTEM SHALL NOT hard-bind the Python backend and llama-server into the updater payload (`externalBin: ["binaries/iris-backend"]`, `resources: ../llama.cpp/build/bin/Release`). Widget-shell updates and backend/model updates are separate payloads, or every UI tweak is a multi-hundred-MB download. The split's *implementation* is the launcher spec's; this spec only ensures the widget bundle does not require carrying them.
**Edge Cases:** signing key absent in a local build (build succeeds unsigned, updater artifacts skipped, with a warning); `llama.cpp/build/bin/Release` missing on a clean clone (the `bundle.resources` entry points at a build artifact that is gitignored — the release build must produce it or the bundle step fails).
**GATE 0 HAS RUN.** These are no longer pure predictions — see `GATE0-FINDINGS.md` for what was observed, which blockers confirmed, which mechanism was restated, and the one blocker (G0-01) that was missed entirely and preceded all others. Blockers not yet *reached* by a build are marked as such above; reaching them is Gate 4's job.

### REQ-18: Fast codebase search (ripgrep-backed `grep_files` + `glob_files`)
**User Story:** As a developer-mode user I want the agent to locate files and code in a directory in one call, the way a good coding environment does, so that finding something costs one round trip instead of a recursive directory crawl.
**Verified:** REAL GAP — the agent has **no codebase search tool at all**.
  - `tool_registry.py` file tools are `read_file`, `write_file`, `list_directory`, `create_directory`, `delete_file` (`:608-632`). The tool named `search` (`:948`) is a **web** tool (`category="web"`, `requires_internet=True`) — not a code search.
  - The only recursive option is `list_directory(recursive=True)`, implemented as `Path(path).rglob("*")` with **no ignore rules and no result bound** (`backend/mcp/builtin_servers.py:459-467`). Pointed at a repo root it walks `node_modules`, `.next`, `venv`, `llama.cpp` and returns every entry into agent context.
  - Measured on this repo: `rg --files` enumerates all **8,653** tracked files instantly; `find node_modules -type f` **could not finish counting in 100 seconds**. `rglob("*")` walks the second tree, not the first.
  - No ripgrep anywhere in the codebase (`grep -rl ripgrep backend/ lib/` → no hits), so the agent's only current fallback is `run_command` with `dir /s` / `findstr` — slow, Windows-only, and unbounded.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide `grep_files` (content search): regex pattern, optional path scope, optional glob/file-type filter, output modes `files_with_matches` (default) / `content` / `count`, optional context lines, and a default result cap.
- AC2: THE SYSTEM SHALL provide `glob_files` (path search): a glob pattern (`**/*.tsx`), optional path scope, results sorted **most-recently-modified first**, with a default result cap.
- AC3: BOTH tools SHALL respect `.gitignore` by default, with an explicit opt-out flag. This is the property that makes them fast — not raw scan speed. Skipping `node_modules` is the difference between 8,653 files and a tree that cannot be counted in 100 s.
- AC4: BOTH tools SHALL bound their output by default (cap results, truncate long lines) and state when a result set was truncated. An unbounded search result is a context-window failure, not a search.
- AC5: `grep_files` in `files_with_matches` mode SHALL return **paths only**. The agent then reads what matters. Returning file contents by default converts one cheap call into a context flood.
- AC6: THE SYSTEM SHALL execute both tools against a **bundled** ripgrep binary, resolved from the app bundle before PATH. Verified: `rg` 14.1.1 happens to be on this machine, but a tool the agent depends on cannot be conditional on the user's PATH. Ship it in `src-tauri` resources alongside the existing `externalBin` entries.
- AC7: BOTH tools SHALL honour the REQ-4 workdir binding and the REQ-4 AC6 allowlist — search is scoped to the active project, not the filesystem.
- AC8: BOTH tools SHALL be `permission_tier="read_only"` and `parallel_safe=True`, so they can run concurrently and need no approval prompt.
- AC9: THE SYSTEM SHALL NOT substitute the MCM `mcm_grep` / `mcm_glob` tools for these. **Closed by Gate 0 (G0-06):** `mcm_glob("**/react/package.json")` at the repo root **timed out after 120 s** on the same machine where `rg --files` enumerated 8,653 files instantly. They carry the same unbounded-walk problem as `Path.rglob("*")`. They remain useful for topology-ranked queries on known-small scopes; they are not the fast-search primitive.
**Why this is load-bearing for D3/D8:** the minimality ladder's rung 2 is *"is it already in the codebase?"* That question is unanswerable without fast search. An agent that cannot cheaply check for an existing implementation will write a new one — which is the single most common over-build on the NOT THIS list. REQ-18 is a prerequisite for REQ-9 working at all, not a convenience.
**Edge Cases:** binary files (skipped, not decoded); very large match sets (capped per AC4 with an explicit truncation notice); pattern that is invalid regex (explicit error naming the pattern, never a silent empty result — an empty result and a bad pattern must not look alike); repo with no `.gitignore` (AC3 falls back to a built-in ignore list covering `node_modules`, `.next`, `venv`, `__pycache__`, `.git`, `dist`, `build`); symlink loops (ripgrep handles; do not reimplement).

### REQ-19: FAULTLINE labels for the dev/shell surface
**User Story:** As the tuner I want shell and dev-tool failures to arrive typed so that the DER reviewer stops re-planning around failures that re-planning cannot fix.
**Verified:** PARTIAL — FAULTLINE (`docs/architecture/FAULTLINE.md`, `backend/agent/tool_errors.py`) already covers this surface *structurally*: `normalize_failure` runs at the `ToolBridge.execute_tool()` choke point, which every dev tool passes through, so nothing escapes untyped. But §8's coverage table lists **dev/git** under **Roadmap** — "currently auto-classified from message heuristics" — so a shell failure today arrives with a *guessed* label. Worse, REQ-1 AC5 and REQ-4 AC6 introduce failure modes that have no label at all and would land in the Layer-3 unclassified bucket indefinitely.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL register explicit Layer-2 labels for the dev/shell surface via `register_error_label(...)` — a DATA edit, never new branches (FAULTLINE §2):

  | label | retryable | blame | info_state | raised when |
  |---|---|---|---|---|
  | `workdir_denied` | no | query | blocked | path outside the REQ-4 AC6 allowlist — an identical retry can never succeed |
  | `cap_reached` | yes | self | missing | REQ-5 semaphore full — the same call succeeds once a slot frees |
  | `aborted` | maybe | self | unknown | REQ-8 user abort — **not** a tool defect |
  | `shell_spawn_failed` | maybe | world | blocked | no shell resolvable / workdir vanished |
  | `output_truncated` | no | world | missing | REQ-12 budget hit; full output is in the panel, not lost |
  | `injection_suppressed` | no | self | blocked | REQ-2 AC4 deny-list — output exists but must not enter context |
  | `worktree_unavailable` | maybe | world | blocked | REQ-13 sandbox could not be created; the write was refused |

- AC2: THE SYSTEM SHALL distinguish **a tool that failed** from **a command that ran and exited non-zero**. A failing `pytest` is a SUCCESSFUL tool call carrying `returncode != 0`. If it is typed as a tool failure, the reviewer re-runs the test instead of fixing the code — the exact blind-retry loop FAULTLINE was built to end (§1). Non-zero exit SHALL surface as `success: True` with the exit code and output in the result, never as an `error_type`.
- AC3: THE SYSTEM SHALL preserve `details["raw"]` on every dev failure (FAULTLINE §3) — the original stderr/exception text is never replaced by the label.
- AC4: `aborted` SHALL NOT be counted as a tool failure against the REQ-12 failure budget or the tool-decision veto memory. The user stopping something is not the tool being unreliable.
**Edge Cases:** a failure matching two labels (most specific wins; `workdir_denied` outranks `shell_spawn_failed`); an unlabelled new dev failure (Layer-3 bucket + `unknown_label_counts()` — promotion via `promote_unknown()` once it recurs, per FAULTLINE §2); label registered twice (registration is refused, not silently overwritten).

### REQ-20: Packaged runtime completeness (the sidecar must actually run)
**User Story:** As the owner of IRIS I want the bundled backend to start and serve a real turn on a machine with no Python and no venv, so that "the widget launches" means the product works rather than the window opens.
**Verified:** REAL GAP — `scripts/build/build_backend.py` declares `HIDDEN_IMPORTS` covering only the web stack (`uvicorn*`, `fastapi`, `starlette`, `pydantic`, `dotenv`, `sqlite3`, `json`, `asyncio` — `:74-100`). It passes **no** `--collect-all` / `--collect-data` / `--add-data` for any ML or audio dependency, while `requirements.txt` pulls `torch>=2.0.0`, `torchaudio`, `transformers>=5.12.0`, `faster-whisper>=1.0.0`, `pvporcupine>=4.0.0`. PyInstaller's static analysis does not follow dynamic imports, native libraries, or data files, so those are almost certainly absent from the bundle. **CONFIRMED BY GATE 0 (G0-04).** A marker scan of the checked-in sidecar found `numpy` (14), `uvicorn` (3), `sqlite3` (3), `fastapi` (2) — and **zero** occurrences of `torch`, `transformers`, `faster_whisper`, `pvporcupine`, or `llama`. The binary is **36.45 MB**; torch alone ships 2-3 GB, so size settles it independently of the scan. The bundled sidecar cannot run STT, wake word, or local inference. `pvporcupine` additionally documents downloading its shared library "automatically on first use" (`requirements.txt:21`) — a network dependency at runtime.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL declare, explicitly, which subsystems the packaged sidecar supports and which are deferred to a post-install download. A bundle that silently lacks STT, wake word, or local inference is a broken product, not a small one.
- AC2: FOR each supported subsystem THE SYSTEM SHALL add the PyInstaller collection flags its dependency requires (`--collect-all` / `--collect-data` / `--add-data`), including model files, `.ppn` wake-word assets, and `backend/data/` content the runtime reads.
- AC3: THE SYSTEM SHALL verify the sidecar on a machine with **no Python install and no project venv** — the only test that distinguishes "PyInstaller succeeded" from "the binary runs."
- AC4: IF a subsystem is deferred to post-install download THEN THE SYSTEM SHALL degrade explicitly at runtime — a named, surfaced "component not installed" state, never a crash and never a silent capability gap.
- AC5: THE SYSTEM SHALL fail the build when a declared-supported subsystem is missing from the bundle, rather than shipping a binary that starts and then fails on first use.
**Edge Cases:** GPU/CUDA builds of torch (bundle CPU-only or defer — do not ship a CUDA build that fails on machines without the runtime); `pvporcupine` first-use download with no network (AC4 degraded state); model files far exceeding the updater payload budget (this is the REQ-17 AC5 split, and it is where that split becomes mandatory rather than advisory).

### REQ-21: Known baseline before any work starts
**User Story:** As the owner of IRIS I want the current state measured before the first task, so that every later failure can be attributed to a change rather than to something that was already broken.
**Status: EXECUTED 2026-08-25 — results in `GATE0-FINDINGS.md`.** Necessary because the working tree carries substantial uncommitted churn (measured: **131 dirty entries** — 91 untracked, 23 modified, 17 deleted) (deleted, modified, and untracked files across backend, components, and tests) on branch `feat/agent-multi-step-tool-execution`. Nothing in this spec establishes what currently passes, and **no packaged build has been run** — every REQ-17 and REQ-20 blocker is read from config and source, not reproduced.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL record, before Gate 1 begins: the branch and commit under test, the working-tree state, and the result of the project's targeted test command for the areas this spec touches.
- AC2: THE SYSTEM SHALL attempt one full packaged build (`build:static` → `tauri build` → install → launch) and record every failure encountered, **without fixing any of them**. The output of this exercise is a known list, not a green build.
- AC3: THE SYSTEM SHALL treat any REQ-17 / REQ-20 blocker that does NOT reproduce as a spec correction to be made, not as a blocker to skip silently. A prediction that proved wrong is information.
- AC4: THE SYSTEM SHALL record blockers found that appear in NEITHER REQ-17 nor REQ-20. The predicted list is near-certainly incomplete; discovering that early is the point of this requirement.
**Edge Cases:** the build fails so early that later stages cannot be reached (record the wall, fix only enough to reach the next wall, record again — the goal is depth of knowledge, not a passing build); tests already failing before any change (recorded as pre-existing, never attributed to this spec's work).

### REQ-22: Shell-context lifetime — ephemeral delivery, bounded retention, exact read-back
**User Story:** As a developer-mode user I want the agent to see what my shell commands did without that output living in the conversation forever, and I want it to READ an earlier command's output rather than remember it.
**Verified:** REAL — REQ-2's first implementation persisted the injected block via `ConversationMemory.add_message("system", ...)`. Measured consequences: the window is count-based FIFO (`max_messages=10`), every windowed message is re-sent on EVERY LLM call, and a DER turn makes 5-15 calls, so one ~500-token block is re-paid 5-15x per turn for ~5 exchanges while occupying 1 of 10 slots; `add_message` also rewrites `conversation.json`, so shell bytes reach session archives. Separately verified: after `drain()` the BACKEND KEEPS NO COPY — terminal scrollback is a browser-side module store (`components/terminal/terminalScrollback.ts`) the backend cannot read, and `recall_memory` is semantic (`episodic.retrieve_similar`, `min_score=0.40`) so it returns ranked summaries, never bytes.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL deliver the drained shell block by appending it to the turn's LOCAL outgoing context list and SHALL NOT write it to conversation memory. The precedent is the @-card block in the same function ("Appended to the LOCAL context list, never add_message()'d").
- AC2: THE SYSTEM SHALL retain every drained record — kept AND budget-evicted — in a bounded per-session history, and SHALL bound BOTH the records per session and the number of sessions retained.
- AC3: THE SYSTEM SHALL give every record a stable ref and SHALL emit one index line per retained record that is not carried verbatim in the current block, naming the command, exit code, ref, and retained size.
- AC4: THE SYSTEM SHALL expose a read-only tool that returns the EXACT retained text for a ref, and SHALL return an explicit error naming why a ref can expire when the ref is unknown.
- AC5: THE SYSTEM SHALL return from the read path only text that already passed REQ-2 AC4 redaction and truncation. A read SHALL NOT surface what an injection would have withheld.
- AC6: THE SYSTEM SHALL gate the read tool behind the same TERMINAL capability as `run_command`.
- AC7: WHEN a session has no shell activity and no retained history THEN THE SYSTEM SHALL inject nothing at all.
**Edge Cases:** deny-listed command (never recorded, so never retained — the suppression notice is unchanged); ref from an evicted record (explicit error, never a silent empty result); ref from another session (not found — history never crosses sessions); elided middle of an over-budget record (unrecoverable by design, the terminal panel keeps it).
**Rationale for the index (do not remove it):** an opt-in read fails silently when the user says only "fix the failing test". The index is ALWAYS present, so retrieval is opt-in but AWARENESS is not. Without it the agent has no ground truth for older output and will reconstruct it — the exact hallucination this requirement exists to prevent.

### REQ-23: Working-memory zone hygiene — no unwired anchor zones
**User Story:** As a maintainer I want no context zone that nothing writes to, so that the next person wiring live output does not pick the leaking one.
**Verified:** REAL — `ContextManager` shipped an `active_tool_state` zone in `ZONES_ORDER` / `ZONE_WEIGHTS` / `ANCHOR_ZONES`. `MemoryInterface.update_tool_state` was its only writer and had ZERO production callers (tests only). `specs/agent_loop_design.md` prescribed it for step results; the DER loop writes those to `working_history` instead ("WORKING MEMORY: accumulate findings for later steps"), with excerpting and compression. The zone is in `ANCHOR_ZONES` (never compressed) and `ContextManager.clear_session` has no caller in `agent_kernel.py` (only `mycelium_clear_session`), so any future writer would leak context for the process lifetime.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL NOT define a context zone that no production code writes to.
- AC2: THE SYSTEM SHALL remove `update_tool_state` and every `active_tool_state` entry from `ContextManager`.
- AC3: THE SYSTEM SHALL mark the superseding decision at the spec line that prescribed the zone, naming the zone that replaced it.
- AC4: THE SYSTEM SHALL keep `working_history` as the single channel for step results.
**Edge Cases:** tests that exercised the removed API are removed WITH it (not weakened); tests that used the zone name to exercise the generic `append(zone=...)` mechanism are re-pointed, and every such change is called out in the report rather than left in the diff.

### REQ-24: Terminal input must not queue behind an agent turn
**User Story:** As a developer-mode user I want to run a shell command while the agent works, because a terminal that stops working whenever the agent thinks is not a terminal.
**Verified:** REAL GAP — `backend/main.py` holds `_session_message_locks[session]` for a turn's WHOLE duration. `_CONTROL_FRAMES` (`ping`, `pong`, `request_state`, `notification_response`, `question_response`) and the REQ-15 steering channels bypass it; `terminal_input` does NOT, so it falls to the locked dispatch branch and waits for the running turn to finish.
**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL dispatch `terminal_input` as a background task WITHOUT acquiring the per-session ordering lock.
- AC2: THE SYSTEM SHALL NOT handle `terminal_input` inline in the WebSocket reader loop. A command can run for minutes and would block every other frame on that socket.
- AC3: THE SYSTEM SHALL preserve per-session command ORDER. This holds without the lock because `SubprocessManager` owns a per-session `_cmd_lock` ("one shell => serialized commands").
- AC4: THE SYSTEM SHALL leave every other message type on the locked lane. Only frames named in the unlocked set skip the lock.
**Edge Cases:** two commands typed quickly (the shell's own lock orders them); a command typed while the agent runs its own `run_command` (the agent's path is the tool bridge, not this lane — unaffected); developer-mode gate unchanged (`CapabilitySet.require(TERMINAL)` still rejects personal mode).

### REQ-25: A message sent during a running turn steers that turn
**User Story:** As a user I want to redirect a task that is going the wrong way, in either mode, instead of waiting for it to finish being wrong.
**Verified:** REAL GAP, and larger than it looks. The backend steering channel is COMPLETE (REQ-15 T25/T26: inbox, boundary drain at `_der_check_steering`, plan revision, queued/considered acks) and **the frontend never sent to it** — a repo-wide search for a `steer` frame returns nothing outside the backend. The chat input is not disabled during a turn, so a message typed mid-task became a `text_message` that queued behind the session lock; `handleSendMessage` carries the comment recording a 23-minute case. Two further defects found while wiring it: (a) the WS client sends `{type, payload, seq}` while the REQ-15 handler read `text` from the TOP level only, so a steer would have arrived with `text=""`, acked, and revised nothing; (b) records are drained ONLY inside the DER loop, so anything queued while no task ran would be applied to the NEXT task.
**Acceptance Criteria:**
- AC1: WHEN a task is running for the active conversation AND the user sends a message THEN THE SYSTEM SHALL send it on the steering channel instead of as a new turn.
- AC2: THE SYSTEM SHALL accept the steering text and message id from either the frame's top level or its `payload`.
- AC3: THE SYSTEM SHALL discard and acknowledge any steering record queued BEFORE the current task started, so a steer aimed at one task never revises another.
- AC4: THE SYSTEM SHALL show the user that the message steered the running task rather than starting a new one.
- AC5: THE SYSTEM SHALL behave identically in personal and developer mode. Steering carries no capability gate.
- AC6: THE SYSTEM SHALL keep REQ-15's boundary contract — a steer is applied at the next step boundary, never mid-step.
**Edge Cases:** message sent as the task settles (either it lands before the last boundary and revises, or the sweep drops it at the next task — never applied to the wrong task); several messages during one turn (REQ-15's "last non-empty steering wins" is unchanged); a turn with no DER loop (no card is working, so the UI sends a normal message).

### REQ-24 addendum — the terminal now races the turn (found in live verification)

Removing the lock makes the shell genuinely concurrent with the agent, and that
changes one observable behaviour that was previously impossible:
`terminal_output` STREAMS while a command runs, but the `ShellRecord` is queued
only after the command COMPLETES. A turn sent in that window drains an empty
queue and sees no shell context. Under the old lock this could not happen,
because the turn could not start until the command's frame had been handled.

- AC7: THE SYSTEM SHALL treat a record that misses its turn as DELAYED, never
  lost — it is retained, indexed, and delivered on the following turn (REQ-22).
- AC8: THE SYSTEM SHALL NOT re-introduce the lock to close this window. The
  window is bounded by one command's runtime, and the cost of closing it is the
  coupling REQ-24 exists to remove.

**Edge Cases:** the user types a command and hits Enter on a chat message in the
same instant (the command's output arrives on the NEXT turn, with an index line
naming it — the agent is never unaware that it happened); a command that never
terminates (its record is never queued, and the terminal panel remains the live
view, which is the pre-existing behaviour).

### REQ-26: A steer must be audible, not only visible

**User Story:** As a voice-first user I want to hear that my redirect landed, so
that I do not repeat myself into a system that already heard me.

**Verified:** REAL GAP, measured in the live run of 2026-08-26. The steering path
(`_der_apply_steering` and its caller `_der_check_steering`) contains ZERO calls
to the speak surface — confirmed by inspection of the whole span. A steer today
produces exactly two signals: a `steering:ack` status frame, and the chat system
line added by REQ-25. Neither is speech. Measured consequence in `conv-57`:
the steer was queued at t=127.6; the DER loop was 2 s into a 62 s `grep_files`
step, so the next `task:progress` the user heard was **"Using grep_files"** —
the OLD objective — and the steer was not consumed until t=264.0. That is
**136 seconds** in which a voice user has no evidence the redirect was received,
while the narration actively describes the work they just asked to stop.

This does not break REQ-15's boundary contract, and the contract should not be
relaxed to fix it: applying a steer mid-step is exactly what CT-APERTURE-1-style
boundary rules exist to prevent. The gap is in FEEDBACK, not in timing.

**Acceptance Criteria:**
- AC1: WHEN a steering record is queued for a running task THEN THE SYSTEM SHALL
  emit an audible acknowledgement that the redirect was received.
- AC2: THE SYSTEM SHALL distinguish RECEIVED from APPLIED. A steer is received
  immediately and applied at the next boundary; an acknowledgement that implies
  the plan already changed is a lie for as long as the current step runs.
- AC3: THE SYSTEM SHALL route the acknowledgement through the SpeakTool
  singleton so it serializes against in-flight narration on the existing
  narration lock. It SHALL NOT open a second audio path.
- AC4: THE SYSTEM SHALL NOT interrupt or truncate speech already in flight.
- AC5: WHEN the steer is consumed and a revision is applied THEN the next
  step narration SHALL describe the REVISED objective, so the applied change is
  self-evident without a second announcement.
- AC6: THE SYSTEM SHALL stay silent for a steer that is dropped as stale
  (REQ-25 AC3) — a discarded record must not be acknowledged as accepted.

**Edge Cases:** a steer arriving while the previous answer is still being spoken
(observed: TTS was at word 42 of 43 when the steer landed — the acknowledgement
must queue behind it, not cut it); several steers during one long step (the last
non-empty wins per REQ-15, so acknowledge receipt each time but do not promise
each one separately); a steer sent in a text-only session (the visual system line
already covers it; speech is additive, never the only channel).

**OPEN — the timing choice belongs to the user, not to this spec:**
acknowledge on RECEIPT (immediate, honest about "heard, not yet applied") versus
on APPLICATION (accurate, but silent for the length of the running step). The
measured 136 s gap argues for receipt. Not implemented pending that decision.


### REQ-27: Narration must say what is actually happening

**User Story:** As a user listening while the agent works I want the spoken
progress to describe the real work, so that I can tell a working agent from a
stuck one without watching the screen.

**Verified:** REAL — three fixed vocabularies, all confirmed at the source.
1. `backend/agent/narration.py` defines `_TOOL_VERB = {"crawler_query": "reading",
   "web_search": "searching", "open_url": "opening", "search": "searching"}`, and
   the heartbeat speaks `f"{verb}…"` whenever no detail is supplied.
2. The crawler call site (`tool_bridge.py`, `run_with_narration(...)` for
   `crawler_query`) passes **no `status_fn`**. So `detail` is always empty and
   the heartbeat speaks the single word **"reading…"** on every interval for the
   entire crawl — while the tool is in fact searching, fetching, extracting,
   ranking and synthesising. The one word is wrong for most of the run.
3. The display label is a second fixed ladder (`tool_bridge._action_label`-style
   `if tool_name in (...)` chain producing `Reading <file>`, `Using <tool>`), so
   the visible text and the spoken text are separately hardcoded.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL source the narration line from the work the agent itself
  described — the current DER step's description and the plan title are written
  by the model, not by this table — before falling back to any fixed verb.
- AC2: THE SYSTEM SHALL NOT speak the same line twice in succession. A repeated
  line carries no new information and is the specific behaviour that makes the
  narration feel broken.
- AC3: WHEN a tool passes through distinct phases THEN THE SYSTEM SHALL narrate
  the CURRENT phase, and SHALL NOT keep announcing the first one.
- AC4: THE SYSTEM SHALL treat the fixed verb map as a last resort, reached only
  when neither a step description nor a phase is available.
- AC5: THE SYSTEM SHALL prefer SILENCE to a repeated or inaccurate line. A
  heartbeat exists to report progress; with nothing new to report there is no
  progress to announce.
- AC6: THE SYSTEM SHALL keep every spoken line on the SpeakTool singleton and
  its narration lock. No new audio path, no second speaker.
- AC7: THE SYSTEM SHALL keep the REQ-9 narration observability log entry for
  every decision, including each decision to stay silent and why.

**Edge Cases:** a step description that is very long (trimmed to a speakable
length at a word boundary, never mid-word); a step description containing a path
or URL (spoken as its basename/host, not character by character); a tool with no
step context at all, e.g. one invoked outside the DER loop (falls back to AC4); a
phase that changes faster than the heartbeat interval (the heartbeat reports the
phase current at its tick, and never queues a backlog of stale phases).

### REQ-28: A long answer gets a spoken brief, not its first sentence

**User Story:** As a user who is not looking at the screen I want to hear what
the whole answer said, so that I do not have to open the chat to find out
whether it answered me.

**Verified:** REAL — `AgentKernel.prepare_spoken_text` states the rule outright:
over 120 words it returns "first sentence to boundary (≤ 60 words)" plus "in the
chat window". That is TRUNCATION, not summary: the listener hears the opening of
the answer and never learns its conclusion. The stated reason is latency — "No
second LLM call — direct text processing keeps first-audio latency to synthesis
time only".
The plumbing for a real brief ALREADY EXISTS and is simply not reached: the
Issue C.1 speak/show contract carries a `speak` line, `iris_gateway` prefers
`agent_kernel._last_spoken_text` over `prepare_spoken_text`, and
`_process_structured_response` sets it. But the `[RESPONSE FORMAT]` prompt asks
for `speak` ONLY when the reply is a stored DOCUMENT (`show`). A long
CONVERSATIONAL answer is plain text by that same prompt's rule, so
`_last_spoken_text` is `""` and the truncation path is what runs. The gap is
between the two halves of one contract.

**Acceptance Criteria:**
- AC1: WHEN a response exceeds the spoken-length threshold THEN THE SYSTEM SHALL
  speak a BRIEF that conveys the answer's substance and its conclusion, not its
  opening sentence.
- AC2: THE SYSTEM SHALL keep the brief separate from the chat body. The body is
  never shortened (the existing "content lives in exactly one place" rule
  stands), and the brief is never stored as the answer.
- AC3: THE SYSTEM SHALL bound the brief to a speakable length, on the order of
  the existing 20-25 second target.
- AC4: THE SYSTEM SHALL NOT block the chat body on producing the brief. The body
  streams as it does today; the brief follows.
- AC5: THE SYSTEM SHALL give brief generation an explicit deadline and SHALL
  fall back to the current truncation when it expires. A slow brief must never
  turn into a silent turn.
- AC6: THE SYSTEM SHALL prefer a brief the answering model supplied over one
  generated afterwards, so a single call remains the common path.
- AC7: THE SYSTEM SHALL apply the brief to CONVERSATION as well as to documents.
  The document path already works; the conversational path is the gap.

**Edge Cases:** an answer that is mostly code (code is already stripped before
counting, and the brief describes what the code does rather than reading it); an
answer that is a list of many items (the brief gives the count and the shape, not
every item); a brief that comes back longer than the body (rejected, fall back);
a response under the threshold (spoken verbatim exactly as today — this
requirement changes nothing there).

- AC8: THE SYSTEM SHALL begin speaking BEFORE brief generation finishes. A brief
  generated to completion and only then spoken lands seconds after the text the
  user is already reading, and reads as lag rather than as a companion voice.
  Sentences SHALL be delivered to the speech path as they close.

**RESOLVED 2026-08-26 (the fork recorded here earlier is closed).** The chosen
placement is: send the body, generate the brief after it, and correct the
`spoken` string with a `chat_spoken_update` frame once the brief is complete.
The early-audio requirement is met by the QUEUE form of
`iris_gateway._speak_response`, which already existed and was unused on this
path — it accepts a `queue.Queue` of sentences and synthesises the first one
immediately instead of waiting for a whole string.

**NOT THIS:** re-summarising short answers; a summarisation service; a second
model role; caching briefs; speaking the brief AND the body; blocking the body
on the brief.

### REQ-29: The planner must not pay for fields the parser discards

**User Story:** As the owner of the token budget I want the planner to ask for
exactly what the system uses, so that every planner call is not carrying a
catalogue and two fields that are thrown away.

**Verified:** REAL, measured 2026-08-26. Three separate wastes in one prompt:
1. `_plan_task` injected an AVAILABLE TOOLS block listing all 47 advertised
   tools **with full descriptions** — measured **1,131 tokens on every planner
   call** — instructing the model to "set its `tool` to the EXACT name below".
2. The JSON schema required `"tool"` and `"params"` on every step, with three
   RULES lines explaining how to fill them, spending OUTPUT tokens too.
3. The parser has honoured NONE of it since Phase 1 (D1.3): it hard-sets
   `tool=None, params={}` because `explorer.propose` owns tool selection at
   execution time. The tool is then re-decided per step at roughly 4.6k tokens.
So the system paid input tokens for a catalogue, output tokens for two fields,
discarded both, and resolved the tool a third time at runtime. Every extra
required field was also another chance to emit malformed JSON — the failure
class REQ-30 covers.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL NOT ask the planner for any field the parser discards.
- AC2: THE SYSTEM SHALL keep a capability list in the planner prompt, by NAME
  only. It is load-bearing for a different reason than tool selection: without
  it the planner plans capable requests as trivial speak-only steps
  (2026-08-12, "use screenshot_page" planned as trivial). The descriptions
  never served that purpose; the names do.
- AC3: THE SYSTEM SHALL keep `depends_on` and `critical` in the schema. They
  are the DAG — dependency ordering and step gating read them.
- AC4: THE SYSTEM SHALL leave tool selection with the runtime resolver, and the
  task card's `toolName` SHALL continue to come from the RESOLVED tool at
  execution time, not from the planner.
- AC5: THE SYSTEM SHALL keep the planner prompt's stated rules consistent with
  what the parser reads. A prompt that instructs and a parser that ignores is a
  defect even when the output happens to work.

**Edge Cases:** a request that names a tool explicitly ("use screenshot_page")
— still planned as a real step, because AC2's capability names tell the planner
it is possible; a plan with zero steps (out of scope here, see REQ-31); a tool
bridge that fails to initialise (the block is omitted, as before, and the
planner degrades to describing goals without knowing the capability set).

**MEASURED:** tool block 1,131 -> 187 tokens per call (944 saved, directly
measured and prompt-independent). Live (conv-62, backend restarted): the plan
parsed on the FIRST attempt, `_plan_task` accrued 2,227 tokens against
6,178-6,251 on earlier turns (different prompt, so indicative not controlled),
and no retry was needed where earlier turns spent a second full planner call.
Tool calling and the card were re-verified in the same run: 3 steps on the
card, 9 `task:progress`, 7 `tool:call` / 3 `tool:result`, and the resolver
picked `list_directory`, `grep_files`, `list_directory` from goal descriptions
alone.

### REQ-30: The planner's JSON must survive the model's wrapper text

**User Story:** As a user I want an ordinary question answered, not "the planner
returned no valid plan", when the model wrapped its JSON in a sentence.

**Verified:** REAL, and it was the single largest source of failed turns
measured on 2026-08-26 — roughly half. `_plan_task` extracted the plan with one
GREEDY `re.search(r"\{[\s\S]+\}", plan_raw)`, which spans from the FIRST brace
in the reply to the LAST. Correct only when the model emits exactly one object
and nothing else. A preamble, a fenced block plus an example, or any prose
containing a brace yields an unparseable span. Two user-visible endings: "[IRIS
error] The planner returned no valid plan." and — via the retry that then
returned `keys=['answer'], raw_steps=0` — "I wasn't able to put together an
answer for that."
It survived because the failure was UNOBSERVABLE: only the LM Studio branch
logged `plan_raw`, so on every other provider nobody could see what the model
actually said.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL parse the planner's JSON by scanning for BALANCED
  objects, not by matching the first brace to the last.
- AC2: THE SYSTEM SHALL track string literals and escapes while scanning, so a
  brace inside a quoted value cannot close an object early.
- AC3: WHEN several objects parse THEN THE SYSTEM SHALL prefer one carrying
  `steps` or `plan_title` over the first that merely parses, so a leading
  example object is not mistaken for the plan.
- AC4: THE SYSTEM SHALL log the planner's raw reply, bounded, whenever parsing
  fails, on EVERY provider.
- AC5: THE SYSTEM SHALL return None rather than raising when no object parses.

**Edge Cases:** prose containing a brace before the plan; a fenced block plus a
worked example; a brace inside a quoted value; an escaped quote inside a string;
a reply with no JSON at all; the plain single-object happy path (unchanged).

**PROVEN:** 7/7 in-process cases, including a control that shows the OLD greedy
regex fails the live case with the same error class the log recorded
("Expecting property name enclosed in double quotes").

### REQ-31: A planner that answers instead of planning must not lose the answer

**User Story:** As a user I want the answer the model already wrote, not an
apology, when the planner decided my question needed no plan.

**Verified:** REAL, observed on conv-59. The planner returned
`keys=['answer'], raw_steps=0`. `_should_skip_der` then set `_der_response = ""`
with the comment "forces the direct path below", but the very next guard is
`if _der_response is not None:` — an empty string is NOT None, so the guard
passes, nothing matches, and control reaches the empty-DER handler, which
returns `_empty_der_fallback_message`. There is no `_respond_direct` call
between the two points. The model's own answer is discarded and the user gets
"I wasn't able to put together an answer for that."

**Acceptance Criteria:**
- AC1: WHEN the planner returns an answer and no steps THEN THE SYSTEM SHALL
  deliver that answer rather than an apology.
- AC2: THE SYSTEM SHALL make the "skip DER" sentinel mean what its comment says,
  or replace the comment with what the code does. The two SHALL agree.
- AC3: THE SYSTEM SHALL preserve the empty-DER fallback for the case it was
  built for — a DER run that genuinely produced nothing.

**Edge Cases:** the error path two branches away sets
`_der_response = "[IRIS error: ...]"` and relies on the same `is not None`
guard, so the sentinel cannot simply be changed to None without checking it;
`test_model_routing_contract` asserts the phrase "couldn't generate" never
reaches a `chat_message`, so the fallback's wording is itself under contract.

**NOT FIXED — needs its own task and test.** The guard is load-bearing for two
other branches and the fallback carries its own contract. REQ-30's fix may make
this path much rarer; whether it still fires is the first thing to measure.

### REQ-4 addendum — the allowlist guard rejected every relative path

**Verified:** REAL, found live 2026-08-26 (conv-62). REQ-4 AC6 replaced the old
`startswith(_DEFAULT_REPO)` guard with a registered-root allowlist, and the
allowlist works — but both call sites checked the path BEFORE resolving it:

```python
scope = os.path.normpath(scope_param)            # 'backend' stays RELATIVE
if not any(self._path_under(scope, root) ...):   # roots are ABSOLUTE
```

A relative path can never lie under an absolute root, so every relative path was
refused. A relative path is exactly what a model produces: the agent resolved
`grep_files(path='backend')` for a folder of this very project and the turn died
with *"Working directory 'backend' is outside the project root. Aborting."* Both
`_execute_search_tool` and `_execute_dev_tool` carried it.

- AC7: THE SYSTEM SHALL resolve a relative working directory against the session
  workdir, else the default repo root, BEFORE the allowlist check.
- AC8: THE SYSTEM SHALL keep the allowlist check on the RESOLVED absolute path.
  Resolving first is not a weakening: the result is normalised, so a `..` escape
  becomes an absolute path outside every root and is still rejected.
- AC9: THE SYSTEM SHALL apply one resolution helper at every call site. Two
  copies of this check is how one of them stayed wrong.

**Edge Cases:** `backend` and `backend/agent` (allowed, resolved under the root);
an absolute path inside the project (unchanged); `../../Windows` and an absolute
path outside (still rejected); a session workdir bound to a subfolder (relative
paths resolve against it); an empty path (falls back to the base, never the
process CWD).

**PROVEN:** 7/7 in-process — three previously-broken cases now allowed, two
security cases still blocked, two fallback cases correct. Live (conv-63):
`task:done` 1 / `task:fail` 0, where the same question previously produced
`task:fail` with every tool call refused.

### REQ-33: A live check must assert the OUTCOME, not the mechanism

**User Story:** As the person reading a verification report I want a PASS to mean
the agent did the job, not that the machinery moved.

**Verified:** REAL, and it produced a false PASS in this spec's own work on
2026-08-26. The first `live_tools` harness asserted three things — the plan had
steps, the card received them, and `tool:call` fired. All three were TRUE while
the turn ended in `task:fail` with every tool call refused by the workdir guard.
The tools ran; they were rejected; the harness called it a pass. The user caught
it by LISTENING to the TTS: the agent said it had failed while the report said
PASS.

**Acceptance Criteria:**
- AC1: A live check SHALL fail when `task:fail` is emitted, regardless of what
  else it observed.
- AC2: A live check SHALL fail when any step reports a failure reason.
- AC3: A live check SHALL fail when the agent's own answer says it could not do
  the thing. The response is evidence about the outcome, not proof of one.
- AC4: A live check SHALL assert the answer is substantive, not merely present.
- AC5: WHERE ground truth is computable, the check SHALL compare the agent's
  answer against it rather than accepting that an answer arrived.
- AC6: A mechanism assertion SHALL NOT be reported as evidence the task
  succeeded. "The tool ran" and "the tool worked" are different claims.

**Edge Cases:** a turn that legitimately has nothing to do (no steps is a valid
outcome — assert on the answer, not the step count); a partial success (report
it as partial, never as PASS); an agent that hedges correctly ("at least six")
where ground truth is larger — truthful and incomplete is not the same failure
as fabricated, and the report SHALL distinguish them.

**Applied:** the harness now also asserts `no_step_failed`, `task_did_not_fail`,
`agent_did_not_report_failure`, and `answer_is_substantive`. The run that had
passed 3/3 fails 3/7 under it.

### REQ-34: A search tool must get an evidence window that fits a list

**User Story:** As a user asking "how many files mention X" I want the real
count, not the first few the window happened to fit.

**Verified:** REAL, measured live 2026-08-26 (conv-63). `_der_evidence_cap`
returned 8000 for `_DER_GATHER_TOOLS` and **400 for everything else**, and
`_DER_GATHER_TOOLS` is `{crawler_query, web_search, search, fetch_url,
read_file, browser_read}`. REQ-18 introduced `grep_files` / `glob_files` as the
codebase-search surface and never added them, so a tool whose whole purpose is
returning a LIST was capped at 400 characters. `grep_files` was NOT the limit --
its `max_results` defaults to 100 and it returned all 18 matches. At ~21 chars
per entry that is ~420 characters of paths before the JSON envelope, so the
agent could not physically see them all and answered "at least six" where the
true count is 18.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL give the codebase-search tools an evidence window sized
  for a list of results, not the default single-value window.
- AC2: THE SYSTEM SHALL NOT achieve this by adding them to
  `_DER_GATHER_TOOLS`. That set also drives the sufficiency gate and the graft
  decision; widening it there changes loop semantics that are not the defect.
- AC3: THE SYSTEM SHALL leave every other tool's window unchanged at 400.
- AC4: WHERE a result genuinely exceeds any window, the truncation SHALL be
  visible to the agent, so a partial evidence set is hedged rather than
  presented as complete.

**Edge Cases:** a search returning more than the window (AC4 -- the agent should
hedge, which it demonstrably already does: "at least six" was correct behaviour
on partial evidence, not a hallucination; every file it named was real); a
search returning nothing (unchanged); a non-search tool (still 400).

**PROVEN:** 9/9 against the real class body via AST — grep_files and glob_files
now 8000; crawler_query, web_search, read_file unchanged at 8000; run_command,
list_directory, take_screenshot, and None still 400; the `@staticmethod`
decorator intact.

**NOT THIS:** embedding-ranked result selection. The list fits the window once
the window is right; ranking 18 items to choose 6 would be machinery serving a
limit that should not exist. Semantic selection belongs to a different
requirement — choosing WHICH results survive when a set genuinely overflows any
window — and should be raised with measurements, not retrofitted here. See also
the existing non-requirement rejecting embedding-based code search.

### REQ-35: A decision point may accept a terminal answer — but only the SYSTEM declares success

**User Story:** As a user I want the agent to use an answer it already has
instead of apologising — and I want it to stop claiming it finished when it did
not. Both, or neither is worth having.

**Verified:** REAL at two sites, measured live 2026-08-26.
1. **Planner** (conv-59): returns `{"answer": ...}` with 0 steps — "this needs
   no plan, here is the answer". `_should_skip_der` sets `_der_response = ""`
   intending the direct path, `if _der_response is not None` swallows the empty
   string, and the empty-DER handler returns the canned apology. The model's
   answer is discarded.
2. **Tool resolver** (conv-64): asked to name a tool, the model replied in prose
   — "Step 1 already listed all files... From the evidence, the search returned
   matches from several files: ./api/chat.py, ..." — i.e. "no tool needed, the
   work is done". Nothing parsed, memory had no suggestion, the step FAILED and
   the turn ended `task:fail`.
Same shape at both: the model gives a valid TERMINAL answer where the system
accepts only "do this next", so a correct reply becomes a failure.

**THE DANGER THIS REQUIREMENT EXISTS TO BOUND.** The obvious fix — "accept the
answer as success" — is worse than the bug. Evidence from the same conv-64 turn:
the model asserted it had seen "matches from multiple files", and the final
answer then said "Only one backend file mentions Porcupine" against a true count
of 18, unhedged, with no mention that a step had failed. **The model's
self-assessment was demonstrably unreliable in the very turn where it claimed
completion.** A widened decision point that trusts that claim converts a visible
failure into a silent wrong answer, which is strictly worse: the first is
diagnosable, the second is not.

**Acceptance Criteria:**
- AC1: WHEN a decision point receives a terminal answer THEN THE SYSTEM SHALL
  admit it as a CANDIDATE that changes what happens next, and SHALL NOT treat it
  as a verdict on whether the objective was met.
- AC2: THE SYSTEM SHALL keep ownership of the outcome label. The model may say
  "I am done"; only the system may say "it succeeded". These are different
  claims and SHALL NOT be collapsed.
- AC3: THE SYSTEM SHALL route a terminal answer through the verification that
  already exists — the per-step verifier and `_der_findings_sufficient` — rather
  than around it. Widening the ENTRY to a decision point SHALL NOT widen the
  EXIT criteria.
- AC4: THE SYSTEM SHALL NOT emit `task:done` on the strength of a terminal
  answer alone. An unverified terminal answer is delivered as an ANSWER, at the
  same epistemic standing as any direct reply, without a completion claim.
- AC5: WHEN a step failed THEN the user-facing answer SHALL say so. A confident
  answer that omits a failure it knows about is the "success spoken after a
  failure" defect this project's own CDD doctrine names.
- AC6: THE SYSTEM SHALL record `verified_label` for the terminal-answer outcome
  exactly as for every other outcome. A new path that does not reach the ledger
  is a new blind spot.
- AC7: THE SYSTEM SHALL preserve the canned fallback for what it was built for —
  a run that genuinely produced nothing. Fewer arrivals there is the goal; an
  empty fallback path is not.

**Edge Cases:** the model claims completion but the evidence is partial (AC3
catches it — the sufficiency gate judges the findings, not the claim); the model
claims completion and is right (delivered as an answer, no `task:done`, no
regression); the model answers where a tool was genuinely required (the answer
is delivered and the failed step is still reported per AC5, so the user can see
the gap rather than being told a false success); a step fails AFTER a terminal
answer was admitted (the failure still surfaces — admission is not absolution).

**RESOLVED USING WHAT WAS ALREADY THERE (2026-08-26).** Site 2 needed no new
concept: `DecisionKind.REASON` already exists and is documented as "model
decided no tool needed (valid reasoning step)", and the kernel already routes it
— the comment reads "REASON: item.tool stays None -> falls to _run_step_direct
below". It was simply never PRODUCED when the model replied in prose instead of
emitting a structured decision. `tool_decision.py` now returns REASON in that
case (after the memory lookup has had its chance), carrying the reply as the
rationale. AC2/AC4 hold by construction: nothing on that path marks the step
successful, `_run_step_direct` returns a result through the normal outcome path,
and the loop still decides whether the objective was met. A genuinely dead model
— no text at all — still FAILS.
Site 1 deliberately stopped short of flipping `step_success`: `_ok=False` drives
the retry classification in `_run_step`, and no verifier grades a `True` result
there, so flipping it would have been exactly the false success AC2 forbids.

**MEASUREMENT THAT DECIDES WHETHER THIS WORKED:** the count of turns ending in
the canned apology SHALL fall, AND the count of confidently-wrong answers SHALL
NOT rise. Either number moving alone is not success. Baseline from 2026-08-26:
roughly half of turns died before the fixes to REQ-30; conv-63 answered "at
least six" (hedged, partial, honest); conv-64 answered "Only one" (unhedged,
wrong). The target is conv-63's honesty with conv-63's or better completeness —
never conv-64's confidence.

### REQ-36: The model's THINKING must never be delivered as its answer

**User Story:** As a user I want to hear the agent's answer, not the agent
reading its own reasoning — or worse, reading our system prompt back to me.

**Verified:** REAL, one root cause producing two separate user-visible defects,
both measured live 2026-08-26. `_dispatch_api`'s streaming path ends with:

```python
# Reasoning fallback: some models return answer in reasoning_content
# with empty content. When using reasoning fallback, skip _parse_thinking
# since the reasoning IS the answer (preamble stripping would kill it).
if not full_reply.strip() and reasoning_text.strip() and not _tool_calls:
    return reasoning_text, reasoning_text, []
```

`command-a-plus-05-2026` streams through `reasoning_content` and leaves
`content` empty, so this returns RAW THINKING as the answer, with preamble
stripping deliberately skipped. Two victims:
1. **The spoken brief** (REQ-28) came back as *"The user gave a description of
   WebSocket handshake. The instruction: 'You write the SPOKEN version of an
   answer the user is already reading...'"* — our own system prompt, read aloud.
2. **The tool resolver** (REQ-35) received *"1. Step 1 already listed all files
   in the backend directory / 2. Step 2 already read each file..."* — numbered
   reasoning, which parsed as no tool and failed the step.
The fallback is not wrong in general: for models that genuinely answer through
`reasoning_content` it is the only thing that works. It is wrong for a model
whose reasoning is actually reasoning, and callers have no way to tell.

**Acceptance Criteria:**
- AC1: A caller SHALL be able to distinguish "the model produced content" from
  "the dispatcher substituted reasoning for content".
- AC2: A caller that cannot use raw reasoning SHALL reject it and fall back to
  its own safe path rather than presenting thinking as an answer.
- AC3: THE SYSTEM SHALL NOT speak reasoning to the user under any path. Spoken
  output is the narrowest surface — a wrong spoken line cannot be re-read or
  scrolled back.
- AC4: THE SYSTEM SHALL preserve the fallback for models that genuinely answer
  through `reasoning_content`. Removing it trades one silent failure for another.

**Edge Cases:** a model that emits both content and reasoning (unchanged — the
fallback does not fire); a model that emits neither (unchanged); reasoning that
IS the answer (AC4 — still delivered); reasoning that is meta-commentary about
the prompt (rejected by the caller under AC2).

**APPLIED — caller-side, deliberately not in the dispatcher.**
`stream_spoken_brief` now passes a `reasoning_callback`, captures reasoning
separately, and discards the result when nothing arrived on the CONTENT stream
AND the returned text matches the captured reasoning. It then returns "" so the
caller speaks the truncation instead. A blunt spoken line beats reading our own
prompt aloud.

**THE OBVIOUS CENTRAL FIX DOES NOT WORK — checked, not assumed.** The tempting
change is "run `_parse_thinking` on the reasoning fallback and keep the stripped
form". It would have fixed NEITHER observed case. That stripper is lexical: it
removes leading paragraphs matching a fixed opener list —
`okay|alright|let me|i need to|i should|i will|the user (is|has|wants|asked)|
looking at|wait|so the|hmm`. The brief's leak opened with *"The user **gave** a
description…"* (`gave` is not in the alternation) and the resolver's opened with
*"1. Step 1 already listed all files…"* (matches nothing). Widening a regex of
English opener phrases to chase this is guesswork that fails on the next model.

**THE MECHANISM THAT DOES WORK IS STRUCTURAL, NOT LEXICAL.** Do not ask "does
this text look like thinking"; ask "did this text arrive on the reasoning
stream". A caller that passes a `reasoning_callback` can compare what it
captured against what was returned and know for certain. That is what
`stream_spoken_brief` now does, and it is why the fix is caller-side rather than
in the dispatcher.

**REMAINING CENTRAL WORK IS CLEANLINESS, NOT CORRECTNESS.** Both known victims
are handled — the brief structurally (above) and the tool resolver via REQ-35's
REASON routing, which is the better fix there anyway because it uses machinery
the codebase already had. A dispatcher-level change would only spare future
callers from repeating the comparison, e.g. by returning the fallback as an
explicit signal rather than as indistinguishable text. Worth doing; not urgent;
should not be done by widening a phrase list.

### REQ-37: Thinking control must apply to every model that can accept it

**User Story:** As the owner of a model-agnostic assistant I want my thinking
setting to mean the same thing on every provider, not just the local one.

**Verified:** REAL, two defects in one place, found 2026-08-26 while chasing
REQ-36's reasoning leak.
1. **The API path had NO thinking control at all.** `_needs_thinking` and the
   user-facing `_thinking_style` setting (`concise` / `balanced` / `thorough`)
   already existed and were wired to the LM Studio dispatcher ONLY. Every
   API-backed model — which is what the product actually runs on — ignored the
   setting entirely, which is why an API reasoning model returned its
   deliberation as the answer.
2. **The LM Studio control was almost certainly a no-op.** It set
   `_body["extra_body"] = {"chat_template_kwargs": {...}}` and then POSTed
   `_body` as raw JSON over httpx. `extra_body` is an OpenAI *SDK* concept — the
   SDK merges its contents into the top level — so as a literal JSON key it is
   not an API field and servers ignore it. Over raw HTTP the hint belongs at the
   TOP level. The one place that supposedly controlled thinking was sending it
   in a form nothing reads.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL apply the thinking decision on EVERY dispatch path, not
  one, and both SHALL read the same `_thinking_style` setting through the same
  helper.
- AC2: THE SYSTEM SHALL send the hint in the form the transport actually carries
  — top level for a raw POST, never the SDK-only `extra_body` key.
- AC3: WHEN a provider rejects the hint THEN THE SYSTEM SHALL strip it and
  retry, never fail the turn. The hint is an optimisation; the turn is not.
- AC4: THE SYSTEM SHALL remember a rejecting endpoint for the process, so a
  strict provider costs one wasted request rather than one per call.
- AC5: WHEN thinking is wanted THEN THE SYSTEM SHALL send no hint at all, so
  `thorough` behaves exactly as it does today.

**Edge Cases:** a provider that ignores unknown fields (hint sent, no effect,
no harm); a provider that 400s (AC3/AC4); a model with no thinking mode (hint is
inert); `_thinking_style = thorough` (AC5 — nothing sent).

**PROVEN 5/5** in-process: top-level form emitted, `extra_body` never used, no
hint when thinking is wanted, refusal remembered per endpoint and not re-sent,
other endpoints unaffected, and the retry helper a no-op when no hint was set.

**MEASUREMENT — the leak is INTERMITTENT, so it is judged on a rate.** conv-68
leaked 13,562 characters opening "Thus we must produce a single paragraph..."
while conv-69 answered the SAME question cleanly in 1,691. One clean run after a
fix therefore proves nothing. Baseline: 1 leak in 2 observed. The verifying run
asks the identical question repeatedly and counts leaks structurally
(deliberation markers in the opening, or a body far over the requested length).
A small sample against a ~50% base rate is suggestive, not conclusive, and SHALL
be reported as such.

### REQ-38: Agent work must survive component unmount

**User Story:** As a user of a desktop widget whose panels mount and unmount
constantly, I want the agent's thinking and working to keep going and keep
showing, not reset because I opened the dashboard.

**Verified:** REAL. `hooks/useTaskProgress.ts` holds all task-card state in
COMPONENT state and subscribes in an effect that unsubscribes on unmount:

```ts
const [cardsState, setCardsState] = useState<CardsState>(EMPTY_CARDS_STATE)
useEffect(() => {
  window.addEventListener("iris:task_update", handler)
  return () => window.removeEventListener("iris:task_update", handler)
}, [])
```

Two consequences, both user-visible in a widget that mounts and unmounts:
1. **State dies on unmount** and remounts as `EMPTY_CARDS_STATE`.
2. **Events arriving while unmounted are lost outright** — the listener is gone,
   so the state cannot even be rebuilt from them afterwards.
And because the hook is called by FIVE consumers — `chat-view`,
`TaskListCard`, `XurOrb`, `AmbientCrawlTier`, `terminalScrollback` — each holds
its OWN independent copy, rebuilt separately from the same event stream. There
is no single source of truth for what the agent is doing.

**THE PATTERN ALREADY EXISTS IN THIS REPO.** `components/terminal/terminalScrollback.ts`
solved precisely this problem and says so: *"WHY MODULE-LEVEL: REQ-13 requires
the terminal to preserve its scrollback when the slide-over is closed. Component
state dies with the component; a module-level store survives ANY unmount
(closing the slide-over, switching to the dashboard, HMR remounts)... The store
is a plain subscriber store (no React) so it can be driven from window event
listeners that live for the whole session, not just while the panel is
mounted."* Every word of that applies here.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL hold task-card state in a module-level store whose
  event subscription lives for the session, not for a component's lifetime.
- AC2: THE SYSTEM SHALL NOT lose a `task_update` that arrives while no consumer
  is mounted.
- AC3: THE SYSTEM SHALL present ONE shared state to every consumer, so the orb
  and the chat view can never disagree about what the agent is doing.
- AC4: A consumer that mounts mid-task SHALL see the task's CURRENT state, not
  an empty one.
- AC5: THE SYSTEM SHALL keep the existing bounds (`MAX_CARDS_PER_CONVERSATION`,
  `MAX_TRACKED_CONVERSATIONS`, `MAX_STEPS`). A session-lifetime store must stay
  bounded or it becomes a leak.

**Edge Cases:** a conversation switch while unmounted (the store handles it, as
the listeners are still live); HMR remount in dev (the store survives, which is
the pattern's stated benefit); the very first mount with no prior events
(unchanged — empty is correct there).

**NOT THIS:** a global state library, moving card state to the backend, a React
context provider (the terminal store deliberately avoids React so it can be
driven by window listeners outside the tree), rewriting the reducer.

### REQ-39: The settings panel must not block on its own save

**User Story:** As a user I want APPLY to feel instant and CLOSE to close.

**Verified:** REAL, measured 2026-08-26. `handleApplySettings` in
`dark-glass-dashboard.tsx` did three things that cost the user time:
1. `await new Promise(r => setTimeout(r, 2000))` — an unconditional two-second
   sleep on every apply. Its stated purpose (guarding duplicate subprocess
   launches) is ALREADY served by `applyCooldownRef`, whose timer is set in the
   `finally` and runs regardless of the handler's duration.
2. A `for` loop awaiting `/api/config/save` once PER SECTION, serially.
3. `handleCloseWithSave` **awaited** the whole of the above before calling
   `onClose()`, so every close paid the full apply cost — the reported symptom
   that closing "seems to trigger apply and takes a considerable long time".
The endpoint is not the problem: measured 412ms cold, then **3-4ms** warm. The
sleep WAS the wait.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL NOT block the apply handler on a fixed sleep. A
  cooldown that disables the button SHALL be enforced by a timer that does not
  delay the handler.
- AC2: THE SYSTEM SHALL save independent sections concurrently.
- AC3: CLOSE SHALL return immediately and SHALL NOT await the save.
- AC4: Closing SHALL still persist unsaved edits. The existing unmount cleanup
  is documented as "the single chokepoint that catches EVERY close path" and
  fires the same POSTs with `keepalive: true`, which is designed to outlive
  unmount — awaiting on the close path bought nothing.
- AC5: THE SYSTEM SHALL NOT double-save. The unmount cleanup's dirty check
  against `lastAppliedRef` remains the arbiter.

**Edge Cases:** close with no unsaved edits (cleanup's dirty check skips, as
before); close immediately after APPLY (`lastAppliedRef` is fresh, so the
cleanup skips); a section whose POST fails (logged, others unaffected — which
concurrency makes true rather than aborting the rest).

### REQ-40: The widget must stay draggable and transparent under Tauri

**User Story:** As a desktop-widget user I want to drag IRIS anywhere, with no
window chrome and no opaque background, and I want that to keep working.

**Verified — CONFIGURATION IS CORRECT, BEHAVIOUR IS UNPROVEN.**
`src-tauri/tauri.conf.json` window `main`: `transparent: true`,
`decorations: false`, `shadow: false`, `alwaysOnTop: true`,
`dragDropEnabled: false`. Dragging is manual —
`hooks/useManualDragWindow.ts` tracks mouse deltas and calls
`getCurrentWindow().setPosition(new PhysicalPosition(...))` rather than using
`data-tauri-drag-region`. `getCurrentWindow` is the Tauri **v2** API and the
project is on `@tauri-apps/api ^2.10.1` with `tauri = { version = "2" }`, so the
API matches the installed version. Nothing here is broken by inspection.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL keep the window transparent and undecorated.
- AC2: Dragging SHALL move the window from the orb and the wheel.
- AC3: Dragging SHALL survive a consumer unmounting and remounting — the hook
  is per-component, so a remount must re-attach cleanly and not strand a
  half-finished drag.
- AC4: A drag SHALL NOT be interpreted as a click, and a click SHALL NOT move
  the window.
- AC5: These SHALL be verified in the packaged Tauri window, not the browser
  dev server. The hook explicitly "falls back gracefully in browser/dev mode",
  which means the browser cannot exercise the real path at all.

**Edge Cases:** multi-monitor (physical vs logical coordinates — the hook uses
`PhysicalPosition` while `useWindowResize` uses `LogicalPosition`, worth
confirming they agree); display scaling; drag started over a child element that
unmounts mid-drag.

**NOT VERIFIED.** AC5 is why: this needs the Tauri build running, and every
live check this session went through the web WebSocket path instead. Config and
API version are confirmed by inspection; movement is not.

### REQ-41: A desktop widget must not be classified as a mobile viewport

**User Story:** As a widget user I want the orb, because the orb IS the widget.

**Verified:** REAL, found live 2026-08-26 when the user reported "only the
chatview is visible, the XurOrb is not — the tauri window might not be big
enough". The instinct was right and inverted: the window was not too small to
FIT the orb, it was too narrow to be RECOGNISED as a desktop.

`hooks/use-mobile.ts`: `useIsMobile(breakpoint = 768)` sets
`isMobile = window.innerWidth < breakpoint`.
`src-tauri/tauri.conf.json`: the widget window is **680x680**.
`app/page.tsx:251`: `if (isMobile || isTailscaleAccess || isRemoteView) { ...`
returns a simplified full-screen chat that NEVER renders `XurOrb`.

680 < 768, so every Tauri launch took the mobile branch. Confirmed it is not a
rendering fault: in a browser at the identical 680x680 the orb renders — a
120x120 2D canvas dead-centre at (279,279), root `MAIN.bg-transparent`, no
WebGL involved. The browser escaped the bug only because its viewport was
resized AFTER mount and emulated resizing does not fire the page's `resize`
listener.

**Acceptance Criteria:**
- AC1: A Tauri window SHALL NOT be treated as a mobile viewport at any size.
- AC2: The breakpoint SHALL continue to govern real browser viewports.
- AC3: The Tauri check SHALL NOT drag heavyweight modules into the width check.
  `hooks/useDeepLink.ts` exports the canonical `isTauri()`, but imports
  `@tauri-apps/api/event` at module scope; importing it here would load the
  Tauri event API into every page that merely asks about width — the same class
  of defect as REQ-37's dead litellm import. The check is inlined, with a
  comment naming the canonical copy so the two stay in step.

**Edge Cases:** a genuinely small browser window (still mobile, unchanged); a
Tauri window resized below the breakpoint (stays desktop, AC1); a future widget
size above 768 (unaffected either way).

### REQ-42: Mode selection happens before the widget, in the launcher

**User Story:** As a user I want to choose personal or developer mode when IRIS
starts, rather than landing in whatever mode was left over.

**Verified:** REAL as a launch-flow gap, not a code defect. IRIS is TWO Tauri
apps: `IRIS Launcher` (1100x720, decorated, opaque, Vite :8080) and `IRIS
Widget` (680x680, undecorated, transparent, Next :3000). `ModeSelectPage.tsx`
states the intent — "the launcher will spawn the widget as a separate window" —
and the launcher POSTs the chosen mode to `/api/mode`, which `backend/main.py`
applies at startup via `set_launcher_mode`. Running `npx tauri dev` at the REPO
ROOT builds the WIDGET directly and skips the launcher entirely, which is why a
session lands in whatever mode was last persisted.

**Acceptance Criteria:**
- AC1: The documented start path SHALL be the launcher, not the widget.
- AC2: The launcher SHALL reach the backend without depending on an untracked
  default. `iris-api.ts` falls back to `http://localhost:8000` and only works
  because `.env` sets `VITE_IRIS_BACKEND_URL=http://localhost:8090`; if that
  file goes missing the launcher silently talks to a dead port.
- AC3: Mode SHALL be selected before the widget renders, so the widget never
  has to guess.

**Edge Cases:** widget started directly for development (valid, but it inherits
the persisted mode — that is the current behaviour and should be documented,
not "fixed" by force); backend not yet up when the launcher starts.

**NOT A CODE CHANGE YET.** The correct entry point is
`cd iris-launcher && npx tauri dev`. Whether the repo-root `tauri dev` should
CHANGE to launch the launcher is a product decision, not a defect — raised, not
taken.

## Non-Requirements (Out of Scope)
- Tauri rebuild / download / install / rollback BEHAVIOR (D4 — owned by iris-launcher spec). The interface (REQ-16) and the build config (REQ-17) are in scope; the pipeline is not.
- Release cadence, CI workflow, and split-payload delivery (iris-launcher spec).
- Agent-to-agent blackboard coordination — moved to `specs/agent-blackboard-coordination` (see REQ-5 scope split).
- External agent CLIs (kilo / claude / opencode) — REMOVED, not deferred (D7). If ever wanted again they enter as a normal agent tool, never as a routing layer.
- Visual unification of chat + shell streams (explicitly rejected, D5).
- Remote/SSH sessions (herdr has them; IRIS is local-first).
- Semantic / embedding-based code search. REQ-18 is lexical (ripgrep). The coordinate graph already carries the semantic layer; a second semantic index is duplicate machinery.
- A language server, symbol index, or AST-aware search. `grep_files` + `glob_files` is what the reference environment ships and what the ladder needs.
- Git push/commit automation beyond what the user types into the shell.

## Open Questions
- Subprocess cap default (4) — confirm against typical machine memory budget.
- Whether `/review` should also run the project's test suite before reviewing (cost vs signal). *Leaning no — REQ-15 already runs targeted tests on any turn that edited files, so `/review` running them again is duplicated cost for the same signal.*
- REQ-13 AC1: does self-edit isolation apply to `/debt` and `/review` (read-only, so arguably not) or only to write paths? *Assumed write-paths-only until contradicted.*
- REQ-17 AC5: is the backend/model payload split a launcher-spec item, or does the widget bundle need restructuring first? *Assumed launcher-spec; revisit if `tauri build` cannot produce a shell-only bundle.*

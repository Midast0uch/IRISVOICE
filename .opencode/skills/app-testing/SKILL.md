---
name: app-testing
description: >
  Live-test IRIS Voice end to end. Mode A (primary for any agent/DER/latency
  change): the MEASURED EVAL LOOP — run real tasks through the real backend with
  evals/run_evals.py, read pass + reply_s, find stalls with in-process stack dumps
  and query plans, fix the cause, prove it, and guard it as a standard. Mode B:
  UI-driven testing — launch backend+frontend detached, orient in the widget,
  plan a SCOPED test, drive via UI or WebSocket. Pivot on blockers, record
  learnings to pins. Use when validating any change, live-testing the app, or
  orienting for the first time.
---

# App Testing — IRIS Voice

A **methodology, not a test suite**. You cannot test everything at once: scope,
plan, drive, pivot, record.

## The loop

1. **Scope** — which layer? (DER/PACMAN execution, memory, audio, UI reflection, crawl.)
2. **Understand first** — read the design MDs for that layer (index below). You cannot
   test what you don't understand, and understanding is what lets you pivot instead of stall.
3. **Define success** — concrete and observable: expected backend WS events AND expected
   frontend states.
4. **Bug vs. feature** — a feature may look odd but be intended. A **bug breaks the
   contract**: the frontend does not reflect what the backend did.
5. **Log the scope** — WS capture, console, screenshots, a running notes file.
6. **Record** — pins for gotchas and contracts; update this skill.

**Two modes — pick by the question you are answering:**

| Question | Mode |
|---|---|
| Does the agent now DO the task? Is it faster? Did my change regress anything? | **A — measured eval loop** (below) |
| Does the UI reflect what the backend did? Does a click/voice trigger work? | **B — UI-driven** (Step 0 onward) |

Unit tests are necessary, never sufficient: this app is a system (DER loop + physics lanes
+ phase-gated model calls + TTS + stores), and in the 2026-09-29 audit a green unit suite
coexisted with 0/15 coding tasks passing and 185 s turns holding ~11 s of real work.

---

## Mode A — The measured eval loop (primary for agent / DER / latency work)

Established 2026-09-29/30 (execution audit, docs/audits/2026-09-29/PROGRESS.md). It took
coding from 0/15 to 15/15 and the full group from ~36 min to 18 min, and every fix in it
was found by measuring, not guessing.

**0. Bound the task.** Write DONE = (one observable condition) and NOT THIS = (the
over-builds it invites) before touching code (CLAUDE.md "THE SCOPE BOUND").

**1. Start the backend DETACHED, with stack dumps on, and wait for REAL readiness.**
```powershell
$env:IRIS_STACK_DUMP_S = '4'   # in-process thread dump every 4 s -> logs/stackdump.log
npm run iris:start:backend      # or: Start-Process python start-backend.py -WindowStyle Hidden ...
# poll /health until 200 — it answers 503 {"status":"starting","tts":{"status":"loading"}}
# until the TTS worker is warm (by design since 2026-09-30); budget 300 s cold.
python evals/load_tool_model.py # loads the LFM2.5 tool model on :8082 via WS load_local_model
```
Wait ~45-75 s after the model load before a run (warm-ups). The Brain is `gemma4:31b-cloud`
on Ollama :11434; use `127.0.0.1`, never `localhost`, for local ports (+2 s/request here).

**2. Run real tasks, DETACHED, and read the right number.**
```powershell
Start-Process python -ArgumentList 'evals\run_evals.py','--task','c10_create_module' `
  -WindowStyle Hidden -RedirectStandardOutput logs\eval_stdout.log -RedirectStandardError logs\eval_stderr.log
# groups: --group coding (15 tasks, ~18 min) | --group research (heavy, one at a time)
```
- A tool timeout that kills the runner skips its `finally` → `data/iris_config.json` is left
  in developer mode. Runs over ~8 min MUST be detached.
- Read **`reply_s`** (time until the reply text). `seconds` also counts the reply being
  SPOKEN (the harness drains frames until 2 s of silence).
- The run prints a STANDARDS section and exits **5** on a regression against
  `evals/standards.json`. Record a new standard only from a clean full run:
  `--record-standard`.
- Keep the machine quiet during a run — no disk scans, no test runs. A folder-size scan
  during one run turned a 20 s reply into 274 s. A harness "LEAK into IRIS repo" note can
  be YOUR OWN edits during the run.
- Workdirs are deleted unless `--keep-workdirs`; keep them when you need to read what the
  agent wrote (that is how c10's root cause was found: the written module had KeyError and
  `< 0` where the request said ValueError and `<= 0` — the node never saw the request).

**3. When it is slow or wrong, find the cause — do not guess.**
- Timeline: grep `logs/iris.log` for `dev_cli`, `_plan_task] parsed`, `run_node]`,
  `physics lane`, `physics fold-back`, `continuation gate`, `success synthesis`,
  `DER response`. Gaps between them are where time went.
- Inside a gap: `python scripts/stackdump_summary.py HH:MM:SS HH:MM:SS [--grep text]` —
  the same frames repeating across dumps IS the stall.
- A DB call in a stall: `EXPLAIN QUERY PLAN` it read-only. A `SCAN` of a table on this
  machine's store is a multi-second stall when pages are cold (C: is a 7200 rpm disk).
- Many threads in one writer (`ingest_event`, `database is locked`): a thread-per-row
  pattern — route through ONE ordered lane (`backend/utils/durability_queue.lane(name)`).
- NEVER sample the backend from outside (py-spy, `python -m asyncio ps`): it killed the
  backend and Claude Code. NEVER use `preview_start` for the backend (a Claude crash kills
  it). Probes go IN the process, marked TEMP, removed after.

**4. Fix the cause at its chokepoint** — one resolver, one lane, one index — not the
instance (see CLAUDE.md "READING THIS CODEBASE").

**5. Prove it.** Targeted tests (never the full suite), then re-run the same eval tasks
and compare `reply_s` and pass. Baseline any failing test on the committed code
(`git stash push -- <file>` → run → `git stash pop`) before calling it yours or not.

**6. Guard it as a standard** (memory `iris-measured-standards`): a pin with before/after,
how measured, how/why fixed; a row in PROGRESS.md "Standards"; and a guard that FAILS on
the old state — a contract test on the STRUCTURAL cause (e.g. the query plan has no SCAN;
finalize returns while the physics is blocked), or `evals/standards.json` for wall-clock
(with a stated tolerance). Prove the guard fails on the old code.

**7. Record** — `record_edit`/`record_test`/`pin_add`, commit with `git commit -F <file>`
(PowerShell here-strings become pathspecs), update this skill.

---

## Step 0 — Launch and poll

**Every server command blocks forever. NEVER run one directly** — not
`npm run dev`, not `python start-backend.py`, not `start_all.py`, not `start_vl.bat`.
You will hang until the tool times out and the server dies with it.

Use these four commands. They return immediately on every platform, because the
Python manager handles the OS differences for you.

```bash
npm run iris:start:backend     # detaches, prints a PID, returns in ~0s
npm run iris:start:frontend    # same
npm run iris:status            # pid + alive + memory per service
npm run iris:stop              # kills every tracked service and its tree
```

Logs: `.iris-logs/<service>-<timestamp>.log`. PIDs: `.iris-pids/`.
Nothing else is needed — no shell-specific quoting, no `&`, no `nohup`, no
`Start-Process`, no `cmd /c start`.

> All four verified 2026-08-12. Previously `iris:start` was undocumented and broken:
> it crashed with `FileNotFoundError [WinError 2]` on `npm` (Windows `npm` is
> `npm.cmd`, which `Popen(shell=False)` cannot exec) and it **blocked** even when it
> worked, holding a Job Object open for the child's lifetime. Both fixed —
> `shutil.which()` resolves the executable, and `--detach` skips the job so the
> command returns. If you invoke the manager directly, `--detach` must come BEFORE
> the service name (`service_cmd` is `nargs=REMAINDER` and swallows anything after it).

### Poll — deadline, not iteration count

```bash
end=$(( $(date +%s) + 300 ))
while [ "$(date +%s)" -lt "$end" ]; do
  [ "$(curl -s -m 2 -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/health)" = "200" ] \
    && { echo READY; break; }
  sleep 3
done
```

- **Bound on wall clock, not loop count.** `N` iterations of a 2s timeout + 1s sleep is
  a `3N`-second wait — easy to believe you waited 20s when you waited 60.
- **Backend: ready = `/health` 200, which now includes TTS** (2026-09-30: the Pocket-TTS
  worker loads WITH the backend; `/health` answers **503** `{"status":"starting",
  "tts":{"status":"loading"}}` until it is warm — that is readiness, not a failure).
  Measured 19-71 s warm, up to ~5 min cold (C: is a hard disk; imports alone were 110 s
  cold vs 5 s warm). Budget 300 s. A failed TTS load answers 200 with `tts.status=error`.
- **Frontend: do NOT poll HTTP.** Next compiles the route on first request, so the
  connection is accepted while the request hangs — `curl` returned `000` for 124s on a
  server whose log already said `✓ Ready in 13.0s`. Poll for the **listener** on 3000
  (`netstat -ano -p TCP | findstr :3000`) or `Ready in` in `.iris-logs/frontend-*.log`.

#### Frontend accepts TCP but never answers → WEDGED, not compiling

**Symptom**: `http://localhost:3000` "can't be reached" / times out; even static
assets (`/favicon.ico`) hang; a raw TCP connect succeeds but the server sends **0 bytes**.

**The distinguishing test** — is the server *working* or *wedged*?

```powershell
$p = Get-Process -Id <next-server-pid>   # owner of :3000, NOT the npm wrapper
$c1 = $p.TotalProcessorTime.TotalSeconds; Start-Sleep 8
$p2 = Get-Process -Id <next-server-pid>
"CPU delta: $([Math]::Round($p2.TotalProcessorTime.TotalSeconds-$c1,2))s  handles=$($p2.HandleCount)  threads=$($p2.Threads.Count)"
```

- **Compiling** → CPU delta is large (seconds), handles in the hundreds.
- **Wedged** → CPU delta ≈ `0s` AND **handles ≈ 100,000+** (Windows handle exhaustion).
  The request thread is blocked on a handle-constrained file watcher, so it burns no CPU.

**Root cause**: `.next` (Turbopack dev cache) bloats to **200k+ files**. Turbopack's
file watcher opens a handle per file; the process hits the Windows handle ceiling and
request threads block. Measured 2026-09-13: `.next` = **200,366 files**, server held
**100,253 handles** at **0 CPU**, every route timed out (including static). This is the
"slow drive / AV realtime scan" hang called out in `next.config.mjs` — the fast-cache
junction mitigation (`scripts/setup_fast_next_cache.py`, referenced by `.env.local`) was
**not active**, so `.next` lived on the slow project drive under Defender realtime.

**Fix** (the `.next` dir is pinned by the wedged process, so stop first):

```powershell
python scripts/iris_process_manager.py stop-named frontend
taskkill /F /T /PID <next-server-pid>        # manager kills only the npm wrapper
Rename-Item .next .next.bloated               # rename is instant; a recursive delete of 200k files is not
npm run iris:start:frontend
```

**Verify**: first request now returns **200 in ~2.5s** (cold), server handles in the
hundreds. If handles are still ~100k after a clean `.next`, the cache is bloating again
within one session — relocate it via `setup_fast_next_cache.py` or add a Defender
exclusion for the project drive.

> **NOW AUTOMATIC (2026-09-15) — both launch paths self-heal.** The junction is created
> and repaired automatically: `iris_process_manager._ensure_fast_next_cache()` runs it on
> every `iris:start:frontend`, and `scripts/dev-servers.mjs` runs it before Tauri dev
> starts Next. So the manual rename/restart recipe above is now a fallback, not the norm.
> If the wedge recurs, first check `fsutil reparsepoint query .next` — if it is NOT a
> junction, the cache is back on the slow drive and the auto-setup was bypassed (e.g. a
> start path that calls `next dev` directly).

> **CRITICAL — the `.next` junction ALONE breaks the app (2026-09-15).** A bare junction
> makes Node resolve the cache to its REAL path (`%LOCALAPPDATA%\iris-next-cache`), then
> walk UP for `node_modules` and find none → every external import dies with
> `Failed to load external module react/jsx-runtime` (and the server answers 200 on `/`
> but the route errors). The fix is a `node_modules` junction at the CACHE ROOT pointing
> at the project's real `node_modules` — one instance, so no duplicate-React "invalid hook
> call". `setup_fast_next_cache.py` now creates BOTH junctions. Do NOT try to fix this
> with `--preserve-symlinks` (risk of a second React instance). Also: detect the junction
> target with `fsutil reparsepoint query` (`Print Name:`), NOT `dir /AL` — `dir /AL`
> lists the directory's CONTENTS, so once the nested `node_modules` junction exists it
> reports THAT and the setup mis-detects a healthy junction as wrong (it churned the
> junction on every start until fixed).

> **Manager gotcha**: `stop-named frontend` kills the npm wrapper PID only. The real
> `next-server` child (the owner of :3000) **survives** and keeps holding `.next`. Always
> find the :3000 owner and `taskkill` it explicitly. A process stuck in a kernel wait
> (0 handles, 1 thread) may be **unkillable** — `taskkill`/WMI Terminate fail with
> `ReturnValue=2`; if so, rename `.next` out of the way and start fresh, and expect the
> zombie to linger until reboot.

### Teardown

`npm run iris:stop` — kills every tracked service and its tree, then verify the ports
are clear. Always tear down what you started; an orphan holding 8090 causes the
stale-port failure below.

If you started something outside the manager, kill the tree by PID and expect noise:
`taskkill /F /T /PID <pid>` reports `ERROR: ... could not be terminated` for children
`/T` already killed. That is success, not failure — **verify by port, not by exit code**.
Prefer `taskkill` over `Stop-Process` from git-bash, which often cannot reach Windows PIDs.

### Port contract — 8090, single source of truth

Backend binds **8090** (`data/iris_config.json` → `ports.backend_port`; env
`IRIS_BACKEND_PORT` wins). Frontend WS uses
`ws://<host>:${NEXT_PUBLIC_BACKEND_PORT || 8090}/ws/iris` (`hooks/useIRISWebSocket.ts`).
Keep them equal. **Confirm before any UI test**: `netstat -ano -p TCP | findstr :8090`.
If nothing is listening, the orb sits in "reconnecting" and nothing is testable.

Do not recreate divergent launchers (that caused the old 8091-drift bug). Under the
hood: `start-backend.py`, `start_all.py` (adds Parakeet ASR `:8765`), `start_vl.bat`
(vision `:8081`). **Start them through the manager, never directly.** For UI-only
testing you need backend + frontend only — skip Parakeet and vision.

---

## Step 1 — Orient

The **orb** (centre) and **wings** (ChatWing left, DashboardWing right) are the stable
anchors; card layouts evolve. You must be able to: find the orb, open ChatWing, open
DashboardWing, reach settings (WheelView). If you cannot orient, stop — the app is not
testable yet.

**Orb click interception — the one gotcha that wastes the most time.**
Orb labels (`→ CHAT ←`, `↑ MENU`, `↑↑ VOICE`, arrows) are `<span>`s inside a
3D-transformed container (`perspective: 900px`). The canvas and its parents intercept
uid-targeted clicks: **`chrome-devtools_click` reports "Successfully clicked" while the
label receives nothing.** Never trust that return value on an orb-subtree element.

Use a JS dispatch instead:

```js
() => {
  for (const s of document.querySelectorAll('main span')) {
    const t = s.textContent?.toLowerCase().trim();
    if (t?.includes('→ chat') || t?.includes('chat ←')) {
      s.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true, view:window}));
      return 'clicked';
    }
  }
  return 'not found';
}
```

Then **verify with a snapshot** (chat textbox + "Start a conversation"). If the dispatch
reports clicked but nothing opens, the 3D container swallowed it — click a `HexNode`
button instead (those have real React onClick handlers and respond to uid clicks).

**Getting back**: clicking the **orb itself** navigates backwards to the root view where
the labels are visible again. There is no back button; that is the way out of any panel.

**New conversation**: the "new conversation" icon lives in the **ChatWing header** (top
row of the chat panel, alongside Conversation History / Close Chat). It has been there
permanently — do not hunt for a "start new chat" text button, there isn't one. Click the
header icon, then confirm the chat area shows "Select a conversation / or start a new one"
before driving the next test. (Owner-supplied, 2026-09-15.)

Non-orb elements (chat wing, dashboard buttons) work fine with normal uid clicks.

---

## Step 2 — Understand (doc index)

- **UI/UX**: `docs/Screen-Wings.md`, `docs/Design/XurOrb-Design.md`,
  `docs/Design/ChatCard-Redesign-Design.md`, `docs/Design/Hex-Pattern-Wheel-View.md`
- **Architecture**: `docs/architecture/agent-multi-step-architecture.md` (DER/PACMAN),
  `web-browser-architecture.html` (web search + browser control, interactive map; serve the
  folder over http so `archmap.js` loads), `oracle.html` + `oracle.md`, `audio-pipeline.md`,
  `trust-routing-document-memory.md`
- **Test strategy**: `docs/TESTING_STRATEGY.md`, `docs/LIVE_TESTING_CHECKLIST.md`,
  `backend/benchmarks/live_benchmark.py`

## Step 3 — Plan, then drive

Write the plan to a notes file + a pin before poking. Example (DER/PACMAN + memory):

- **Drive**: a prompt that triggers tool use + memory.
- **Backend asserts**: `task:start` → `tool:call` → `tool:result` → `task:done`,
  plus `inference_event` and memory ingest.
- **Frontend asserts**: `TaskListCard` steps pending→working→done, orb phase change,
  final chat response.
- **Bug vs. feature**: no `TaskListCard` on `task:start` = bug. Unusual card layout = feature.

**Drive by UI**: open `http://localhost:3000`, click orb/chat, type. Browser MCP order:
**Browser MCP → Chrome DevTools MCP → Playwright (last resort)**. Browser MCP needs the
user to connect the extension first (errors `No connection to browser extension` until
they do). Chrome DevTools MCP is the verified-working path. Playwright needs
`waitUntil: domcontentloaded` — the persistent WebSocket blocks the default `load` event
and it times out at 30s.

**Drive by WS**: connect `ws://localhost:8090/ws/{client_id}?session_id=`, send
`text_message` / `confirm_card`, observe events.

Note: chat send is REST `POST /api/chat` (proxied `:3000` → `:8090` via next.config.mjs);
the WS `text_message` is a fallback.

## Step 4 — Perception (delegate; keep main context lean)

- **Screenshots**: capture via Chrome DevTools MCP (`chrome_devtools_take_screenshot`,
  pass `filePath`). If you have vision, read it directly. If not, route the file to
  **`vision-minimax`** with a focused prompt ("orb phase, which wings open, what cards
  visible, any error toasts"). **Never assert UI state from an uninterpreted image.**
  `vision-minimax` misreports exact colours — corroborate colour via computed styles.
- **Logs/files**: delegate to **`deepseek`**; for large logs have it return the relevant
  window (errors, the test's timestamp range) as a SUMMARY, not the whole file.
- `vision-minimax` and `deepseek` are the **only** sub-agents used with this skill.
- You own plan + drive + assertions; sub-agents only supply perception.

## Step 5 — Pivot, then record

Blocked (tool fails, UI doesn't reflect, provider down)? Change the prompt, target a
different layer, or switch drive method. Do not stall.

Record with `pin_add(title, content, tags)`: gotchas, component contracts,
bug-vs-feature calls, launch quirks.

---

## Example scoped sequence — DER + prism cards + cross-thread

1. **Chitchat, fresh conversation** — web mode ON. Expect: prism card (MARKDOWN label +
   "Expand to panel"), a TaskListCard, and **no duplicate plain-text below the card**.
2. **Websearch** — a prompt needing real-time data. Expect DER loop + crawl planner URLs.
   **Verify a crawl actually happened**: a new `data/har/*.har` with a current timestamp
   (otherwise the LLM answered from training data).
3. **Re-render** — "show that as a comparison table". Expect the card format to change
   and a format switcher to appear.
4. **New thread** — ask about step 2's data. Expect recall across threads, and old context
   NOT leaking in until asked.
5. **Multi-tool** — a prompt needing sequential calls. Expect ordered execution, retained
   chitchat context, combined final answer.

## Known issues (expected — not regressions)

- **CSS is PRE-COMPILED — recompile after adding utility classes**: the app
  serves `public/globals.css` (built from `css-src/globals.css` via
  `npx @tailwindcss/cli -i css-src/globals.css -o public/globals.css`). A new
  Tailwind class in a component (e.g. `pl-[5px]`) silently does not exist
  until you rerun the CLI. The `app/globals.css` and `styles/globals.css`
  copies are NOT the served source. Also: the global `* {margin:0;padding:0}`
  reset MUST stay inside `@layer base` — un-layered it beats every Tailwind
  utility (cascade-layer rule) and kills all margin/padding spacing app-wide
  (session 246: dead ml-auto footers, cramped badges, lost indents).
- **Web mode desync**: after reload/reconnect the toggle may show ON while the backend
  thinks OFF. Toggle off→on to re-sync `set_web_mode`.
- **Stale localStorage** persists conversations across loads. `localStorage.clear()` for
  a truly fresh state.
- **Internet disabled** → crawler/web tools fail by design.
- **`_memory_interface`**: `AgentToolBridge._memory_interface` never initialised
  (`tool_bridge.py:66`); `recall_memory` → `AttributeError` on tool-failure recovery.
  Latent until a tool fails.
- **Dilithium `data/memory.db`**: "file is not a database" — unresolved.
- **`.next` cache bloat → frontend wedge (2026-09-13)**: Turbopack's dev cache can grow
  to 200k+ files; the server then holds ~100k handles at 0 CPU and answers **nothing**
  (see Step 0 "WEDGED, not compiling"). Fix = stop, `taskkill` the :3000 owner, rename
  `.next` aside, restart. Recurrence risk while `.next` sits on the slow drive with
  Defender realtime on — activate `setup_fast_next_cache.py` or exclude the drive.
- **ALL ROUTES 404 with a healthy layout (2026-09-18) — poisoned persistent cache**:
  a DIFFERENT failure from the wedge. Symptoms: every route returns **404**
  (`/`, `/dashboard`, even `/favicon.ico`), yet the layout renders normally, the page
  `<title>` is the app's real title, the RSC route tree resolves to `/_not-found`, the
  dev log shows `Compiling /_not-found/page` and **zero errors**, and the first request
  takes minutes (`GET / 404 in 6.6min`) while later 404s are fast. Requests are NOT
  stuck — this is not the handle-exhaustion wedge (CPU/responses are fine), so the
  CPU/handle test does not catch it. Cause: the Turbopack persistent filesystem cache
  (the junctioned `%LOCALAPPDATA%\iris-next-cache`) had gone stale/corrupt — Next
  compiled fine but served `not-found` for every page. Fix (5 min):
  `python scripts/iris_process_manager.py stop-named frontend`, then
  `taskkill /F /T /PID <:3000 owner>` if a next-server survived, then
  `cmd /c rmdir .next` (removes the JUNCTION only — never delete through it, that would
  delete the cache target's contents), `Rename-Item $env:LOCALAPPDATA\iris-next-cache
  iris-next-cache.bloated`, then `npm run iris:start:frontend` (auto-setup recreates both
  junctions). Verify: `GET /` → 200 with `<title>Control Center | TTS Chatbot</title>`
  as the ONLY title in the head. A head with BOTH `404: This page could not be found.`
  AND the app title is still the failure — the 404 page renders inside the real layout.
- **Port drift (fixed)**: a stale backend held 8090, the launcher fell back to 8091, the
  WS never connected and the orb showed a phantom inner glow. Divergent launchers deleted;
  `start-backend.py` now tree-kills the stale process and fails loudly rather than drifting.
  A healthy idle orb has a connected WS and **no** inner glow.
- **Duplicate localhost:3000 tabs CANCEL your in-flight turn (2026-09-14)**: every tab
  connects as the same WS client id `iris`; the second connection makes the backend log
  `client_replace cancelled in-flight thread conv-NNN` and the running turn dies silently
  (the UI shows the user message with no reply). This cost a whole T2 run. Close every
  duplicate app tab before driving. (Close via `chrome-devtools_list_pages` → `close_page`.)
- **WS liveness watchdog false-positives (2026-09-14)**: `hooks/useIRISWebSocket.ts:2411`
  (`SILENCE_TIMEOUT_MS=75_000`) force-closes and reconnects whenever no frame arrives for
  75s. A long tool wait (a >75s gated command or crawl) is mistaken for a wedged backend,
  and the reconnect then cancels the in-flight turn (same `client_replace` path). Watch for
  `[IRIS WebSocket] No frame for Ns ... treating the backend as wedged and reconnecting` in
  the browser console during long turns.
- **Memory = the TTS worker, not a leak**: `backend.audio.tts_worker` (a python
  subprocess) holds ~1-2 GB and jumps ~+1 GB during a synthesis. Since 2026-09-30 it is
  **resident while the backend runs** (idle unload OFF by default, owner decision "TTS ready
  with the backend"); memory is capped by the growth recycle (`IRIS_TTS_MAX_GROWTH_MB`,
  500 MB over the post-load baseline), after which the reaper reloads it at once.
  `IRIS_TTS_IDLE_TIMEOUT_S>0` restores the old idle unload. Measure with
  `scripts/mem_watch.py` (writes `.iris-logs/mem_watch.csv`). This is the biggest RAM
  swing in the app and the owner watches for it.
- **`run_command` dispatch deadline (90s) < permission window (120s) (2026-09-14, OPEN)**:
  `DEADLINE_DEFAULT_S=90` in `der_constants.py`; a gated command can hit
  `[TOOL_DISPATCH] ... CRASHED error='TimeoutError'` before the user approves the card.
- **Card view can stay "Active Execution" after settle (2026-09-14, OPEN)**: the backend
  DID emit `task:fail` (see `.iris-logs/backend-events.jsonl`) and the frontend log shows
  `matrix_transition ...:e->:f`, yet the card rendered "Active Execution" with a frozen
  timer. The emit is present — the bug is downstream in the card view/reducer.
- **Pooled browser corpse after a login wall (2026-09-14, OPEN)**: after the in-app browser
  hits a Bing login wall the shared Chromium can die; later `browser.new_context()` calls
  fail with `'NoneType' object has no attribute 'send'` and `browser_pool.acquire_browser`'s
  `is_connected()` self-heal did not catch it. `search_discovery` is the owner-mandated
  natural websearch path, so this must be robust.

## Providers (verified)

- **Cerebras**: reachable and working. The old "Cloudflare 1010 / egress ban" was a misread
  Windows Schannel revocation error (`CRYPT_E_NO_REVOCATION_CHECK`), already handled by
  `backend/utils/ssl_context.py`. `curl` needs `--ssl-no-revoke`; the app does not. Select
  it in the frontend Models card. Never assume it is down.
- **Cohere**: works (`command-a-03-2025`).
- **Exa**: when `search.provider="exa"` + `EXA_API_KEY` set, the crawler uses Exa for URL
  generation. Unconfigured, it falls back to LLMSearchProvider, which invents paywalled
  academic URLs.

## Local models — load through the UI, on GPU

**Never load via CLI/code.** The profile (`balanced`, `gpu_layers`, `ctx`) is part of the
contract and is recorded per model in `models/gguf/.iris_model_settings.json`.

**UI path**: root → CHAT → **Open Dashboard** → **LOCAL MODEL** (MODEL & INFERENCE card)
→ **BROWSE & MANAGE MODELS** → row **Load**. This fires `load_local_model` over WS with
`profile`/`n_ctx`/`n_gpu_layers`/`model_path`.

- **Verify first**: backend `:8090` `/health` AND the model server (LM Studio `:1234`,
  llama-server, or Ollama `:11434`) are up.
- **GPU-ONLY (hard rule)**: a load landing on CPU is a **failure to investigate**, not a
  pass. Confirm VRAM/GPU layer counts after load. The `cpu_only`/`eco` profile
  (`n_gpu_layers:0`) and `recommend_profile`'s `eco`-when-no-CUDA are CPU fallbacks and
  must be rejected.
- **Budget VRAM first**, then tune for **max tok/s at the largest context** the card
  allows. Fitting is necessary, not sufficient.
- **Preferred**: `27B ternary bonsai`, `LFM 2.5 8B` (`LFM2.5-8B-A1B-Q4_K_M.gguf`,
  `balanced`, ctx 32768, gpu_layers -1). Smaller `bonsai` models power swarm workers;
  a ~245MB LFM is the small fallback.
- **RotorQuant / ternary GGUFs** (Bonsai 27B dspark Q4_1) use planar3/iso3 KV cache and
  **cannot** be loaded by stock `llama-cpp-python` (fails `Failed to load model from file`).
  They need the `johndpope/llama-cpp-turboquant` fork (`feature/planarquant-kv-cache`)
  built as a CUDA `llama-server`; its compressed KV cache is also what makes 32k ctx +
  >30 tok/s fit. `local_model_manager._rotorquant_available` probes this via whether
  `Llama.__init__` accepts a string `cache_type_k`. The binary is resolved by
  `_find_llama_server_binary()`: `IK_LLAMA_SERVER` env → bundled → PATH → common build
  dirs — build the fork into one of those so the app owns the subprocess.
- **Load failure triage**: (a) is the GGUF RotorQuant (needs the fork), (b) is the build
  CUDA or CPU-only (`GGML_CUDA` on `llama_cpp.llama_cpp`), (c) is VRAM sufficient.

## Reference — WS protocol

- **Endpoint**: `ws://localhost:8090/ws/{client_id}?session_id=` (frontend uses `/ws/iris`).
- **Send**: `text_message`, `confirm_card` (model_selection), `set_web_mode`.
- **Receive**: `chat_message`, `task:start`/`done`/`fail`, `tool:call`/`result`,
  `inference_event`, `audio_envelope`, `listening_state`, `task:progress`, `document:render`.

## Companion skills

`frontend-design` (UI/UX intent) · `systematic-debugging` (on a bug) ·
`research-doc` (write it up) · `mcp-eml-testing` (MCM-EML contracts).

## Reading the logs through the architecture (why IRIS is not a normal harness)

IRIS is one recursive operator (DER) steered by physics (Caducean `u`/`ξ`) and gated by a
phase scheduler — see CLAUDE.md "READING THIS CODEBASE". What that means for a tester:

- **Answer path vs side lanes.** The reply waits only for plan → node work → verification →
  synthesis. Physics, ledger rows, fragments and the chain run on ordered lanes
  (`durability_queue.lane("physics"|"ledger")`, pacman fragment worker). A stall on a
  lane must never show up in `reply_s`; if it does, something slipped back onto the path.
- **Fold-back.** Only SHAPE decisions wait for the physics (`[DER] physics fold-back ...
  waited Xs`): split width, the streak-gate topology override, and plan expansion under
  COMPRESS (`continuation step SUPPRESSED during COMPRESS (rec=1)`). A fold-back that times
  out (`not landed after 30.0s`) decides on stale physics — seen once, it kept a bonus step
  that COMPRESS would have dropped. Slow physics is a real bug, not noise.
- **Useful lines:** `[DER] physics lane session=... landed in Xs` (update cost),
  `[tool-event] ledger write ... has not returned` (a blocked ledger row — the lane watcher),
  `[TTSManager] boot load finished`, `Oracle decide consumer=X ... latency_ms` (0.2-0.7 s
  normal; seconds = contention).
- **The Oracle is shadow until it earns a flip** (`scripts/consumer_enforcement_report.py`:
  rows ≥ 100, precision ≥ 0.90, ECE ≤ 0.05 on the ACTIVE engine). Its wrong-looking picks
  (e.g. `tool_choice chosen=vision_get_context conf=0.21`) are below threshold and do not act.

## Maintain this skill

After a session, append what a future agent would need: new contracts, launch quirks,
provider notes, pivots that worked. **Correct anything you find to be false** — the old
`cmd /c start` recipe and the "30s startup" figure were both wrong and cost real time.
Last revised 2026-09-30 (session aa473536): added Mode A, TTS readiness, TTS memory
lifecycle, the architecture-reading section. The Claude Code entry point is a pointer at
`.claude/skills/app-testing/SKILL.md` — edit THIS file, never the pointer.

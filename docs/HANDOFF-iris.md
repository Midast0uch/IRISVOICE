# IRIS Voice — Handoff: Execution, Web-Search & Frontend Feedback

**Purpose:** Handoff for a new agent continuing work on IRIS Voice. Focuses on the
cluster of bugs we have been chasing around *web search*, *backend crashes*, and
*frontend execution feedback*, and on the **underlying architecture problem** the
user believes is causing them.

**How to use this doc:** Read §1 (vision) and §2 (architecture assessment) first —
they explain *why* the bugs in §3 exist. §4 is the file map. §5 is what to
actually investigate next. §6 is run/test state.

**Branch:** `feat/agent-multi-step-tool-execution`
**Last feature commit:** `0f40c217` (stop-listening + narration unification + Phase 1 Orbital cards)
**Live state (2026-07-13):** backend pid **13224** on `:8090` (restarted with the
subprocess-isolation fix); frontend pid **21276** (`npm run dev`, `:3000`);
MCM server pid **16032** (`python -m mcm.mcp_cad`).

---

## 1. The vision (what we are building)

> A system where **IRIS drives the application based on the user's prompts**, and
> the **frontend correctly displays content and provides feedback *while* it
> executes** (live plan/steps, narration, orb phase, search progress, etc.).

So the two halves that must work together are:
1. **Backend agent loop** — take a prompt → plan → execute tools (incl. web
   search/crawl) → produce a spoken + visual response.
2. **Frontend feedback** — render, in real time, *what IRIS is doing and what it
   found*, driven by a stream of backend events.

When either half breaks, the *experience* breaks even if no exception is thrown.
Most of the bugs below are **experience bugs**, not crashes — except the backend
crash, which is the loudest symptom of the architecture issue.

---

## 2. Architecture assessment (the user's hypothesis — confirmed)

**The user's instinct is correct: there is a fundamental architecture problem.**
It is not one bug; it is a set of structural choices that make the system fragile
and make the feedback layer unreliable. Evidence below.

### 2.1 Monolithic single-process backend mixing criticality levels
`backend/main.py` imports **everything** into one FastAPI app and `uvicorn` serves
it as **one OS process**:
- audio engine / STT (`get_audio_engine`, `AudioPipeline`, `VoiceCommandHandler`)
- TTS / narration (`get_tts_manager`)
- the agent loop / DER (`agent_kernel`, `der_loop`, `immortus`)
- the **web crawler** (`crawl4ai` / `CrawlerEngine`)
- WebSocket server + `iris_gateway` + `ws_event_bridge`
- MCP servers (browser, GUI automation, system, file, github…)

A native crash in **any** of these takes down **all** of them at once — including
the audio pipeline and the WS connection the frontend depends on. This is exactly
what we observed: a web crawl (Chromium, C-level) crashed and the whole backend
went to "NOT LISTENING on 8090", killing STT/TTS/WS simultaneously.

### 2.2 No fault isolation, no supervision
- `backend/monitoring/memory_watchdog.py` only **reads RSS** — it does not restart
  anything.
- `scripts/iris_process_manager.py` wraps the child in a Windows **Job Object**
  only when *it* launches the process. When the backend is started via
  `Start-Process` directly (detached), **nothing supervises it**.
- Consequence: a crash = silent total outage. The frontend gets **no
  "disconnected" signal** and the orb freezes. There is no auto-reconnect that
  re-syncs execution state.

### 2.3 "Event soup" feedback model instead of authoritative execution state
The frontend reconstructs "what IRIS is doing" from a stream of loosely-coupled
events bridged by `backend/agent/ws_event_bridge.py`:
`listening_state`, `task:progress` / `TASK_PROGRESS`, `audio_envelope`,
`tool_result`, `tool_call`, `question_ask`, `permission_request`, …
There is **no single source of truth** for execution state. If the backend dies
or any event is dropped, the UI desyncs and cannot recover. The task/plan card
only updates on `crawler_query`'s `TASK_PROGRESS` — other tools don't feed it
consistently (see Bug 4).

### 2.4 Context is threaded to the LLM prompt but NOT to tool parameters
`context_package` (conversation history, Mycelium directives, topology) flows into
the **LLM prompt** (`_run_step_direct` builds the prompt from
`context_package.get_system_zone_content()`), which is good. But **tools receive
only `params` + `session_id`** — never `context_package`. Worse, the DER
forced-tool fallback builds the web-search query from `plan.original_task` (the
**single last message**) at `agent_kernel.py:4612` / `:4581`. So multi-turn
context is lost at the tool boundary — the root of Bug 3.

### 2.5 Fragile planner → executor contract
The DER forced-tool regex hack at `agent_kernel.py:4580-4642` exists because the
**planner emits steps with `tool=None` or mode names** (`"agentic"` / `"quick"` /
`"full"`) instead of real, executable tool names. Execution patches this at
runtime with regex. This is brittle and will break for other intents; it is a
symptom of the planner not being a reliable source of executable plans.

### 2.6 Implicit, off-loop threading
The DER loop runs in a **thread pool** (`run_in_executor`), off the main event
loop (`ws_event_bridge.py:7`). EventBus handlers are sync and use
`run_coroutine_threadsafe`. This works but is error-prone: blocking calls in the
agent thread, silent thread deaths, and — critically — **native crashes (Chromium)
cannot be guarded by `try/except`**, which is why the subprocess fix (§3, Bug 1)
was necessary.

---

## 3. Bug register

Status legend: **FIXED** · **MITIGATED** (symptom reduced, root not solved) ·
**OPEN** (not addressed) · **KNOWN** (diagnosed, fix pending).

| # | Bug | Status | Primary files |
|---|-----|--------|---------------|
| 1 | Backend crashes (C-level) during web crawl, killing whole assistant | **MITIGATED** | `crawler_engine.py`, `crawl_runner.py`(new), `crawl_worker.py`(new), `main.py`, `memory_watchdog.py` |
| 2 | Web search routed to DuckDuckGo `search` tool instead of unified `crawler_query` | **FIXED** | `agent_kernel.py`(~4580-4642), `tool_bridge.py`(1438/1609/1229) |
| 3 | Web search uses only last message, not conversation context | **OPEN** | `agent_kernel.py`(4605-4641), `tool_bridge.py`(`_execute_crawler_query` sig), `conversation_context_store.py`, `der_loop.py` |
| 4 | Live search events not reaching the task/plan card | **FIXED** (via Bug 2) | `tool_bridge.py`(1513), `TaskListCard.tsx`, `useTaskProgress.ts`, `ws_event_bridge.py` |
| 5 | No active narration during search unless backend closed | **FIXED** | `tool_bridge.py`(~1474-1524) |
| 6 | Query extraction bug: "do a web search **on** X" captures "on X" | **FIXED** | `agent_kernel.py`(~4619) |
| 7 | Stop-listening voice command (transcribed speech, not wake word) | **FIXED** + committed | `agent_kernel.py`, `conversation_kernel.py`, `voice_command.py`, `docs/architecture/audio-pipeline.md` |
| 8 | Narration unification (utterance == narration; orb driven by `audio_envelope`) | **FIXED** + pinned | frontend `audio_envelope`, `ws_event_bridge.py`, `conversation_kernel.py` |

### Bug 1 — Backend crash during web crawl (the loudest symptom)
- **Symptom:** during a live web search the backend died; frontend showed
  "NOT LISTENING on 8090"; STT/TTS/WS all gone.
- **Root cause:** `crawl4ai`/Chromium ran **in-process** (`CrawlerEngine` used as
  an async context manager inside the agent process). A C-level Chromium crash
  cannot be caught by `try/except` and kills the monolithic backend (see §2.1/2.2).
- **What we did (this session):** moved the crawl into a **child process**.
  - `backend/crawler/crawl_worker.py` — subprocess entry; runs the crawl, emits
    JSON progress/result lines on stdout.
  - `backend/crawler/crawl_runner.py` — `run_crawl_subprocess()` spawns the
    worker, relays progress to the caller's `on_page_done`, reconstructs a
    `CrawlResult`, and on crash/timeout returns a `CrawlResult` with `.error` set
    (never raises). Sets `cwd`/PYTHONPATH to repo root; ASCII-safe JSON; 90s
    timeout (env `CRAWL_SUBPROCESS_TIMEOUT_S`).
  - `tool_bridge._execute_crawler_query` now calls `run_crawl_subprocess` and
    returns `{"success": False, "error": ...}` on failure instead of crashing.
  - Added `error: Optional[str]` to `CrawlResult` (`crawler_engine.py`).
- **Verified:** worker + runner tested end-to-end (real crawl of example.com,
  progress relay, 2-page crawl, timeout-kills-child-and-parent-survives, dead-child
  can't kill parent). `test_crawler_task_progress.py` updated to mock
  `run_crawl_subprocess` (3 pass).
- **NOT solved (important):** this only isolates the **crawler**. Parakeet (GPU
  STT), TTS, and the GUI/browser-automation MCP servers are **still in-process**
  and equally fragile. There is still **no supervisor** to restart on crash.

### Bug 2 — Web search went to DuckDuckGo `search` tool
- **Symptom:** first live search scraped `html.duckduckgo.com/?q=` (legacy
  `search` tool) instead of the unified `crawler_query`; results presented
  differently and produced no task-card progress.
- **Root cause:** the DER forced-tool fix-up only overrode empty/`direct`/mode-name
  tools, not an explicit `"search"`. The user wants **`crawler_query` for both
  quick AND deep search** (unified flow).
- **Fix:** forced-tool now also remaps `"search"` / `"web_search"` →
  `"crawler_query"` (`agent_kernel.py:4595`). The `search` tool still exists but is
  no longer the web-intent path.
- **Left:** consider deprecating/removing the `search` tool entirely.

### Bug 3 — Web search ignores conversation context  **[OPEN — likely the real "fundamental" bug]**
- **Symptom:** follow-up searches lose prior-turn context (e.g. "now search the
  pricing of *those*" fails because the query is built from the last message only).
- **Root cause (diagnosed):** tools receive only `params`+`session_id`, never
  `context_package` (§2.4). The DER forced-tool fallback derives the query from
  `plan.original_task` (single last message) at `agent_kernel.py:4612`/`:4581`.
  Conversation history reaches the LLM prompt but is **not carried into the tool
  query**.
- **Not fixed.** Next agent should: (a) confirm by reproducing a multi-turn search;
  (b) either pass a compact context summary into `_execute_*` tool params, or make
  the planner/forced-tool incorporate conversation history when building the query.

### Bug 4 — Live search events not reaching the task card
- **Symptom:** plan card didn't show live search progress.
- **Root cause:** `TASK_PROGRESS` with `update_step=True` is emitted **only** by
  `crawler_query`'s `on_page_done` (`tool_bridge.py:1513`); the legacy `search`
  tool didn't emit it, and the card is event-driven.
- **Fix:** routing to `crawler_query` (Bug 2) restored the events. Card renders
  from `hooks/useTaskProgress.ts` ← `ws_event_bridge` ← `TASK_PROGRESS`.
- **Left:** other tools don't emit consistent progress, so the card is uniform only
  for crawler flows. See §2.3.

### Bug 5 — No narration during search
- **Fix:** `_execute_crawler_query` now flips `LISTENING_STATE` →
  `processing_tool` during the crawl and speaks "Researching — fetched page N of M"
  per page (`tool_bridge.py:~1474-1524`).
- **Left:** live-verify with the restarted backend.

### Bug 6 — "do a web search on X" captured "on X"
- **Fix:** added `(?:on\s+)?` to the query-extraction regex alternations in
  `agent_kernel.py:~4619`.

### Bug 7 — Stop-listening voice command  **[FIXED + committed `0f40c217` + 2 pins]**
- Transcribed speech (not a wake word) triggers sleep; `_sleeping_sessions` tracks
  asleep sessions; `_enter_sleep_mode` releases VAD/recording/ASR but keeps Porcupine
  armed. Documented in `docs/architecture/audio-pipeline.md` (TOC #17, SLEEP state).

### Bug 8 — Narration unification  **[FIXED + pinned]**
- "utterance" == "narration"; frontend "speaking" driven only by `audio_envelope`
  (phase speaking→idle) + `listening_state`.

---

## 4. Key files map

**Crawl / isolation (new this session)**
- `backend/crawler/crawl_worker.py` — subprocess worker (JSON protocol on stdout)
- `backend/crawler/crawl_runner.py` — `run_crawl_subprocess()` orchestration
- `backend/crawler/crawler_engine.py` — `CrawlerEngine` (in-proc browser wrapper) + `CrawlResult.error`
- `backend/crawler/crawl_planner.py` — `_fallback_plan` uses `lite.duckduckgo.com` (planner fallback only)

**Agent / web-search routing**
- `backend/agent/agent_kernel.py` — DER forced-tool logic (~4580-4642), query
  extraction (~4605-4641), `_is_web_search_request` (3551), context threading
  (3793-3933, 5136-5330)
- `backend/agent/tool_bridge.py` — `_execute_crawler_query` (1438), `_execute_web_search`
  (1609, legacy DuckDuckGo), tool dispatch (1229/1060), `_tool_action_label` (1229)
- `backend/agent/conversation_context_store.py` — per-conversation history DB
- `backend/agent/der_loop.py` — DER loop, context threading to LLM

**Frontend feedback**
- `components/chat/TaskListCard.tsx` — presentational plan/step card
- `hooks/useTaskProgress.ts` — maps `search`→WebSearch, `crawler_query`→WebCrawl; consumes `task:progress`
- `backend/agent/ws_event_bridge.py` — bridges EventBus → WebSocket (single delivery path)
- `backend/agent/event_bus.py` — internal kernel-to-kernel event bus (singleton)

**Process / supervision**
- `backend/main.py` — monolithic FastAPI app (imports everything)
- `backend/monitoring/memory_watchdog.py` — RSS reader only (no restart)
- `scripts/iris_process_manager.py` — Job Object only when it launches
- `start-backend.py`, `start_backend_logged.py`, `scripts/start_tauri.py` — launch variants

**Tests**
- `backend/tests/test_crawler_task_progress.py` — crawler events (updated this session, 3 pass)
- Pre-existing failures (NOT ours): `test_domain2_voice.py` ×4 (`DER_TOKEN_BUDGETS["voice_first"]` KeyError at `agent_kernel.py:52`); `test_barge_in.py::test_idle_timer_is_daemon`

---

## 5. Recommended investigation directions (for the next agent)

The user is right that these bugs share a root cause. Prioritized:

1. **Generalize process isolation + add supervision.** The crawl subprocess
   (`crawl_runner`/`crawl_worker`) is the template. Move *all* native/heavy
   components (crawler, browser-automation MCP, ideally Parakeet/TTS) into
   worker processes behind a message-passing boundary. Add a supervisor that
   restarts the backend on crash and exposes a health endpoint; give the frontend
   a "backend disconnected" state + auto-reconnect that **re-syncs execution
   state** (not just re-opens the socket).

2. **Replace the event-soup with an authoritative execution-state model.** Define
   one `ExecutionState` (current task, ordered steps, per-step status, phase,
   last result) that the frontend renders. Events become *deltas* to that state,
   not the source of truth. The task card reads from `ExecutionState`, so it works
   uniformly for every tool and survives missed/dropped events and backend restarts.

3. **Thread conversation context into tool parameters** (Bug 3). Either pass a
   compact context summary into `_execute_*` tool params, or make the
   planner/forced-tool incorporate conversation history when building the query.
   Reproduce a multi-turn search first to confirm.

4. **Harden the planner → executor contract.** Make the planner emit validated,
   executable plans (tool names from a fixed registry). Replace the regex
   forced-tool hack with boundary validation/repair. This removes the fragility
   that caused Bug 2/6.

5. **End-to-end resilience tests.** Add a test that simulates a backend crash
   mid-task and asserts (a) the agent survives / reports failure, and (b) the
   frontend recovers or at least shows a disconnected state rather than freezing.

---

## 6. Run / test / verify

```powershell
# Backend (single process, all components)
cd C:\dev\IRISVOICE
python -m uvicorn backend.main:app --port 8090 --host 127.0.0.1
# (currently running: pid 13224; logs: backend/logs/uvicorn_restart.log)

# Frontend
npm run dev        # :3000  (currently pid 21276 via iris_process_manager)

# MCM coordinate graph server
python -m mcm.mcp_cad   # pid 16032
```

```powershell
# Crawler subprocess unit/integration (3 pass)
python -m pytest backend/tests/test_crawler_task_progress.py -v

# Manual crawl isolation smoke test
python -c "import asyncio,sys; sys.path.insert(0,'.'); from backend.crawler.crawl_runner import run_crawl_subprocess;
async def m():
    r=await run_crawl_subprocess('test',['https://example.com'],'summarize',max_pages=1,delay_ms=200);
    print('error=',r.error,'pages=',len(r.pages))
asyncio.run(m()"
```

**Live-test checklist (what the user exercises by voice):**
- [ ] Say "stop listening" → IRIS sleeps (transcribed, not wake word) — Bug 7
- [ ] "Search the web for X" / "do a web search on X" → uses `crawler_query`, not DuckDuckGo — Bugs 2/6
- [ ] Multi-turn: "search for A" then "now the pricing of those" → context carried — Bug 3 (OPEN)
- [ ] During search: orb shows researching + per-page narration + live task-card steps — Bugs 4/5
- [ ] Kill the crawl child process mid-search → backend stays up, agent reports failure — Bug 1 (MITIGATED)

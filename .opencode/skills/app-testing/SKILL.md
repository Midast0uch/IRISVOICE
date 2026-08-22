---
name: app-testing
description: >
  Live-test IRIS Voice end to end: launch backend+frontend detached, poll until
  ready, orient in the widget, then plan a SCOPED test (success parameters,
  bug-vs-feature, logging) before driving via UI or WebSocket. Pivot on blockers,
  record learnings to pins. Use when live-testing the running app, validating a
  layer after a change, or orienting for the first time.
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
- **Backend: ~216s to ready** (measured; pocket-tts model load dominates). Budget 300s.
  It is not hung. Signal: `/health` → 200, or `Application startup complete` in the log.
- **Frontend: do NOT poll HTTP.** Next compiles the route on first request, so the
  connection is accepted while the request hangs — `curl` returned `000` for 124s on a
  server whose log already said `✓ Ready in 13.0s`. Poll for the **listener** on 3000
  (`netstat -ano -p TCP | findstr :3000`) or `Ready in` in `.iris-logs/frontend-*.log`.

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

Non-orb elements (chat wing, dashboard buttons) work fine with normal uid clicks.

---

## Step 2 — Understand (doc index)

- **UI/UX**: `docs/Screen-Wings.md`, `docs/Design/XurOrb-Design.md`,
  `docs/Design/ChatCard-Redesign-Design.md`, `docs/Design/Hex-Pattern-Wheel-View.md`
- **Architecture**: `docs/architecture/agent-multi-step-architecture.md` (DER/PACMAN),
  `web-toggle-crawl-flow.md`, `audio-pipeline.md`, `trust-routing-document-memory.md`
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
- **Port drift (fixed)**: a stale backend held 8090, the launcher fell back to 8091, the
  WS never connected and the orb showed a phantom inner glow. Divergent launchers deleted;
  `start-backend.py` now tree-kills the stale process and fails loudly rather than drifting.
  A healthy idle orb has a connected WS and **no** inner glow.

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

## Maintain this skill

After a session, append what a future agent would need: new contracts, launch quirks,
provider notes, pivots that worked. **Correct anything you find to be false** — the old
`cmd /c start` recipe and the "30s startup" figure were both wrong and cost real time.

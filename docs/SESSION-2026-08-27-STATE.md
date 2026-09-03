# Session state — 2026-08-26/27

> Written to a file because the **mcm-cad MCP server disconnected mid-session**,
> so `pin_add` was unavailable. Fold this into a PiN when the server is back.
> Follows pins: `pin_ea3c4c0008ca`, `pin_298b5a687ef5`, `pin_b5fd769b81cc`,
> `pin_afde772eda6c`, `pin_738086aa1b61`, `pin_63d251934f48`, `pin_cb0aedc7f186`.
> Committed so far: `9fb148ba` (pushed). Submodule `iris-launcher` = `eca87ea`,
> **unpushed — it has no git remote**.

---

## SHIPPED AND VERIFIED

**One Tauri app.** `launch_widget` / `launch_launcher` used to run
`cmd /c npx tauri dev` on a *second* Tauri application — a cargo build plus
another dev server per click, and a duplicate instance blocking on a held port.
Both windows now belong to one app; switching is `show()` + `set_focus()`.

**First packaged build this repo has produced.** `frontendDist` pointed at
`../dist`, which had never existed. Fixed via `IRIS_STATIC_EXPORT` gating
`output:'export'`, moving the `/api` rewrite into the client (`lib/apiOrigin`,
Tauri-only so browser + Tailscale keep relative paths), moving the structured
log sink to the backend, and dropping the redundant `/api/chat` proxy.
Verified: `tauri build` exit 0, MSI produced, packaged exe runs with
`MainWindowTitle = "IRIS Launcher"`.

**Geometry.** `lib/orbWingGeometry` is now the only copy of maths that had
drifted across four files. Idle window 680×680 → 420×420; both-open 1750 → 1400.
`min_size` in `main.rs` AND `minWidth` in `tauri.conf.json` were both 680 and
silently floored every shrink.

**Monitor snap-back.** `useWindowResize` cached the home position on first wing
open. Now derived live, using Tauri `scaleFactor()` not `devicePixelRatio`,
gated to `label === 'main'`, and skipped while hidden — Windows reports hidden
windows at (-32000,-32000), which would move the widget off-screen so `show()`
succeeds and reveals nothing.

**Detachable wings.** Same frontend, same process, so `ws_client`'s AppHandle
emit reaches every window over the ONE socket. Borderless, with a drag handle on
both headers (the dashboard had none).

**Orb.** Scrim plate → per-particle contrast → finally **solid core in
`source-over` + additive bloom**. The rAF loop can no longer be killed by a
thrown frame, and orb errors route to the structured log.

**Developer CLI.** Assistant *and* user messages render monospaced/preformatted;
input is mono with a `❯` prompt and brand caret.

**Wake word honesty.** `engine.py` now asks `is_enabled()` instead of logging
"Porcupine initialized" one second after the detector logged its own failure.

---

## THE TRAPS — each found only by MEASURING, never by reasoning

1. **`filter: blur()` inside the orb's `xurFloat` wrapper = 0.2 fps vs 60.2.**
   Toggling one property and counting rAF callbacks settled it in one call.
2. **`WebviewUrl::External` gets NO IPC**, even at your own dev server, and
   `remote.urls` does not rescue it. Proven by a `println!` at command arrival:
   ZERO arrivals from a user click.
3. **`WebviewUrl::App` IGNORED its path in dev** — the launcher window loaded the
   dev root and rendered the WIDGET, surfacing as
   `set_position not allowed on window "launcher"`.
4. **`public/launcher/` was a build from 24 MAY** shadowing the Next rewrite, so
   every launcher frontend edit was invisible. Found from RESPONSE HEADERS
   (`Accept-Ranges` / `ETag` / `Last-Modified`), not from reading code.
5. **A webview whose initial navigation fails does NOT retry.** Two attempts to
   fix the blank launcher by WAITING (readiness gate on one route, then both)
   both failed with the route verifiably ready. The fix is to check the OUTCOME:
   poll `url()`, and re-`navigate()` while it is still `about:blank`.
   Verified: `[Tauri] launcher window loaded: http://localhost:3000/launcher/index.html`.

---

## DUPLICATE REACT KEYS — root cause and full fix

Symptom: ~2,900 console errors, and replies appearing to "double send". React
says it outright: *"Non-unique keys may cause children to be duplicated and/or
omitted"* — the doubling was a RENDER artifact, not a second backend turn
(verified: 5 `text_message` → 5 turns → 5 responses).

Cause: ids minted independently as `Date.now().toString()` in **ten** places.
Two items created in the same millisecond share a React key.

Fix: one generator in `chat-view.tsx`.

```ts
let __messageSeq = 0
function newMessageId(): string {
  __messageSeq += 1
  return `${Date.now()}-${__messageSeq}`
}
```

Applied to all ten sites — 7 message ids, the plan-event id
(`plan-${...}-${detail.type}`, which collided as
`plan-1787837301636-plan:recovery_start` during recovery bursts), the
steer-notice id, and **2 CONVERSATION ids** (the last two, and the cause of the
final `1787846251365` report — a conversation id is a React key too).

NOT changed: `message_id: steer-${Date.now()}` — that is a *protocol* field sent
to the backend, not a React key, and altering its format could break correlation.

Checked first: nothing parses these ids as numbers, so the `-N` suffix is safe.

---

## WEBSEARCH — three layers, peeled in order

1. **`browser_session` blew its budget**: `elapsed_ms=76495` vs `max_ms=30000`,
   killed → `search_discovery` `transport_error` → `crawler_query`
   `no candidate urls` → no browser animations (nothing reached the page-event
   stage; the animation code was never broken).
2. **Root cause**: `self._started_at` is set in `__init__`, but
   `acquire_browser()` — the cold Chromium launch — runs later in `open()`. The
   launch was billed to the BROWSING budget. Fixed by starting the clock AFTER
   acquisition. The 30 s value is unchanged; what changed is what it measures.
   The `(REQ-19 AC8)` reference in that code is STALE — the spec defines no
   `max_wall_ms`.
   A startup warm-up was added too, but is NOT sufficient on its own: the pool's
   idle watchdog stops the browser ~3 min after use (`10:22:32` started →
   `10:25:48` stopped), so the cold path is hit routinely.
3. **Next failure, newly exposed** (the crawl now runs 7.7 min instead of dying
   at 30 s): `ValueError: The future belongs to a different loop`.
   `orchestrator._emit` is a SYNC callback whose `asyncio.ensure_future()` binds
   each log task to whatever loop is live at that moment — worker threads have
   their own — so `_pending_log_tasks` holds tasks from several loops, and
   `_drain_log_tasks`'s `gather` refuses a foreign future and aborted the whole
   crawl at its final drain. Fixed: gather only tasks whose `get_loop()` is the
   current loop; count and skip the rest (they complete on their own loop).

**Architecture note — NOT a regression.** `search_discovery` driving its own
headless Playwright session is the DESIGN: `specs/vision-browser-stage` REQ-14
says "the agent drives a headless Playwright session server-side while the
iframe is a downstream mirror". The visible in-app browser is a mirror, not the
thing the agent uses. I called this a regression before reading the spec; it is
not.

---

## OPEN

- **Wake word is dead and cannot be fixed from code**:
  `PorcupineActivationRefusedError` — Picovoice refuses the AccessKey
  server-side (device/activation limit or revoked). Key is present, 56 chars,
  loaded correctly from `.env.local`. **Rotate it** — it was also pasted into a
  chat transcript.
- **Vision server cold start = 6.2 min** (`ttr_sec=370.37`). NOT stuck — measured:
  spawned 11:50:58, ready 11:57:08, and the crawl that was waiting on it died
  15 s later on the loop bug above. `llama-server.exe` loading LFM2.5-VL-3B with
  2.94 GB of GPU offload. This is the SAME SHAPE as the browser cold start: a
  large one-time cost paid INSIDE a user-facing operation, so the user sees a
  spinner and assumes a hang. Same class of fix available (warm it ahead of the
  first use), but it holds GPU memory, so it is a decision, not a drive-by.
- `[IRIS WebSocket] backend error: No active category` ×150 —
  `iris_gateway.py:2301`, not investigated.
- Footer: chips dropdown clipping unverified after the `mr-3` inset.
- Launcher submodule unpushed (no remote).
- The readiness gate blocks Tauri `setup()` while it polls; harmless now that
  the retry does the real work, but it belongs off the main thread.

---

## METHOD NOTES — the expensive lessons

- **A live process is not a working one.** Twice a stalled build was called
  "fine" and a finished one "stalled". Sample CPU across an interval FIRST:
  `rustc` at 0.03 s delta over 10 s is stalled, not linking.
- **`cargo check` alongside `tauri dev` contends for the artifact lock** and
  stalls the build. Happened TWICE. Stay on one command, or pass
  `--no-default-features` so artifacts are shared.
- **Never leave a browser tab open on the widget's dev URL while the user
  tests.** It connects as client `iris`, evicts the widget's socket, and cancels
  in-flight agent work — caused a "chat spins forever" report.
- **HMR reloads kill in-flight turns.** Do not edit frontend files while asking
  the user to test a conversation.
- **Measure before adjusting layout.** The footer took five attempts because the
  spec comment quoted widths (116 px model, 174 px pill) that no longer matched
  the code (86 px, ~176 px), and because `ContextPill` caps itself at
  `max-w-[200px]` so it can never absorb slack handed to it. `ml-auto` on one
  element puts the slack in ONE place; `justify-*` scatters it.
- **Read the spec the user names BEFORE claiming a regression.**

---

# NEXT TASK — vision server: reuse an existing server instead of spawning
# (option 1, chosen by the user 2026-08-27)

## THE MEASUREMENT

`ttr_sec=370.37` (6.2 min) is REAL — measured from `subprocess` spawn to the
first HTTP 200 on `/health`. Spawned 11:50:58, ready 11:57:08; the crawl waiting
on it died 15 s later on the event-loop bug. The user's crawl was therefore
mostly WAITING ON THIS.

## RULED OUT — do not re-derive these

**Antivirus.** `lfm_vl_provider.py` (~line 430) documents on-access scanning as
a known cause (measured 73 s on the mmproj) and prints an `av_probe`. IT IS NOT
THE CAUSE HERE: the user had already added the Defender exclusions before this
session, and a previous agent had already traced it to something else. Do not
spend time on `Add-MpPreference`. (Ask the user what that earlier agent found —
it was not captured here and is the single most valuable missing input.)

## MEASUREMENTS — take these as given, do not re-derive

Two consecutive cold loads of LFM2.5-VL-3B:

| load | free VRAM at spawn | GPU need | ttr_sec |
|------|--------------------|----------|---------|
| 1    | 4.36 GB            | 2.94 GB  | 370.37  |
| 2    | **6.42 GB**        | 5.13 GB  | **428.36** |

**More free VRAM produced a SLOWER load.** That substantially weakens the
VRAM-contention hypothesis — do not start there.

Model files: `LFM2.5-VL-3B-Q4_K_M.gguf` 1,674,454,240 B +
`mmproj-LFM2.5-VL-3B-F16.gguf` 853,993,088 B = **2.53 GB total**.

  - llama-server effective rate: 2.53 GB / 428 s = **~5.9 MB/s**
  - plain sequential read of the SAME mmproj via `dd bs=1M count=400`:
    **48 MB/s** (400 MiB in 8.7 s)

**An 8x gap on the same bytes.** The bottleneck is therefore NOT raw disk
bandwidth and NOT VRAM. Something slows llama-server's ACCESS specifically.

Next diagnostic steps, in order:
  1. Confirm whether the Defender PROCESS exclusion covers `llama-server.exe`
     specifically — the user has path exclusions in place, but
     `lfm_vl_provider.py` states the PROCESS exclusion is the one that matters
     because the verdict cache is per-process. Reading exclusions needs an
     ADMIN shell (`Get-MpPreference` returned "Must be an administrator").
     NOTE: a previous agent already traced this away from AV — ASK THE USER what
     that agent found before spending time here.
  2. Check llama-server's own load-time logging (its stderr is captured to
     `vision_stderr`) for where the time actually goes — the code comments note
     llama.cpp emits NOTHING between "load_model: loading model" and
     "loaded multimodal model", so consider raising its verbosity.
  3. Compare against the IN-PROCESS path on the same file: load the same GGUF
     through `llama_cpp.Llama` and time it. If in-process is fast on the SAME
     bytes, the difference is the process, not the file.

48 MB/s is itself modest for an SSD — worth confirming what drive
`C:\Users\midas\.lmstudio\models` actually lives on.

## STILL OPEN AS CAUSES

1. **Two different load MECHANISMS.** This is what the user asked about, and the
   asymmetry is real:
     - Model Manager -> `from llama_cpp import Llama`, IN-PROCESS in the backend
       process (`IRIS_INPROCESS_LLAMA=1` by default). No spawn, no HTTP, no
       second copy. Loads in seconds.
     - Vision -> spawns `llama-server.exe`, which loads its OWN copy of the GGUF
       and must then answer `/health`.
2. **VRAM — WEAKENED by the table above, keep only as a secondary.** 8 GB card. At the slow spawn:
   `vision needs 2.94GB, 4.36GB free (reserving 1.00GB ...)` with `ngl=999`
   forcing every layer onto the GPU, i.e. 2.94 GB into ~3.4 GB usable while the
   brain model held the rest. A load that does not fit cleanly spills over PCIe.
   Observed during a later load: GPU used 1446 -> 5032 MiB.
   Worth testing directly: cap `ngl` and re-measure `ttr_sec`.

## WHAT ALREADY EXISTS (do not rebuild it)

`_ensure_vision_server_running(base_url)` in `backend/tools/lfm_vl_provider.py`
(~line 1070) is ALREADY structured for reuse:

  1. **Health fast path OUTSIDE the lock** — `GET {base_url}/models`. If it
     answers, it returns True and NEVER SPAWNS. Reuse already works for whatever
     `base_url` points at.
  2. Single-flight spawn under `_spawn_lock` (REQ-1): concurrent callers from any
     entry point coalesce onto ONE attempt; `attempt.done` is always set in a
     `finally`, so a waiter cannot hang.

`disable()` already states the ownership rule: it only kills a server IRIS
started (PID-tracked). "If the user is running their own llama-server on the
vision port, we leave it alone."

GOTCHA, already fixed once, do not regress: `base_url` ALREADY ENDS IN `/v1`, so
the endpoint is `/models`, NOT `/v1/models`. Appending `/v1` again gives
`.../v1/v1/models`, which 404s forever (live proof 2026-08-10).

## WHAT IS ACTUALLY MISSING

The provider only ever probes ONE endpoint (default
`http://127.0.0.1:18181/v1`). It cannot discover a compatible server already
running elsewhere, so it spawns a SECOND copy of a model that may already be
resident.

Implement **candidate discovery before the spawn branch** — inside
`_ensure_vision_server_running`, after the existing fast path fails and BEFORE
taking `_spawn_lock`.

Candidates, in order:
  1. `base_url` (already covered by the fast path).
  2. `lmstudio_endpoint` from the inference config — the gateway logs it as
     `"lmstudio_endpoint": "http://localhost:1234"`. It was NOT running during
     this session (`:1234` -> 000), so treat it as opportunistic.
  3. Any other configured local OpenAI-compatible endpoint.

## THE HARD REQUIREMENT — verify MULTIMODALITY before reusing

A text-only server answers `/models` happily and then fails every vision call,
turning a slow-but-working path into a broken one. This is how this change goes
wrong, so gate on it:

  - `GET {candidate}/models` and require the served model id to match the
    configured vision model, OR
  - send a MINIMAL multimodal request (a 1x1 PNG) and require a non-error reply.

Prefer the second: an id match is a GUESS about capability; a successful
multimodal round trip is PROOF. Cache the verdict per endpoint so the probe is
paid once, not per call.

If no candidate verifies, fall through to the existing spawn path unchanged.

## CONTRACTS TO KEEP

  - Single-flight (REQ-1) — do not add a second spawn path around the lock.
  - Ownership — NEVER kill a server IRIS did not start. A reused endpoint must
    not be registered as owned; `_stop_owned_vision_server()` is PID-tracked,
    keep it that way.
  - Idle stop — the idle watchdog must not stop a borrowed server.
  - `_ensure_vision_server_running` keeps returning a plain bool and must never
    raise; every entry point treats False as "vision unavailable".

## TESTS

`backend/tests/contract/test_browser_pool_contract.py` is the shape to copy
(28 tests pass there). Add for the vision provider:
  - a reachable but TEXT-ONLY candidate is NOT reused (the regression that
    matters);
  - a verified multimodal candidate IS reused and NO subprocess is spawned;
  - a borrowed endpoint is never killed by `disable()` or the idle watchdog;
  - no candidate -> spawn path unchanged.


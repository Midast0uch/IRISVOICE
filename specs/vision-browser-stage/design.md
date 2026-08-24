# Design: Vision Browser Stage

> Read requirements.md first. This document names the seams, the mechanisms,
> and the test strategy. Every "reuse" note is binding: this codebase's
> recurring failure mode is building a second mechanism beside an existing one.

## 1. Architecture overview

Three layers, one event contract:

```
BACKEND LIFECYCLE                    EVENT CONTRACT                 FRONTEND STAGE
─────────────────                    ──────────────                 ──────────────
LFMVLProvider lifecycle    ────────► vision_status (WS)   ───────► LifecycleChip
  single-flight spawn                                        ───────► BrowserNavigationOverlay
  ownership-safe cleanup                                     ───────► AmbientTier (new)
  direct spawn (REQ-3)                                              ► VisionStageSimulator (dev)
orchestrator / fetch.vision ───────► crawler_* + crawler_vision_action (UNCHANGED)
capture_store / proxy      ───────► /api/browser/capture|proxy (+ injected scaler)
```

The event contract is FROZEN by this spec. All new behavior hangs off the
existing `iris:*` CustomEvents and the existing `vision_status` WS message.
The simulator works precisely because the contract is real.

## 2. Backend: VLM lifecycle

### 2.1 Single-flight spawn (REQ-1)

`lfm_vl_provider.py` gains module-level state:

```python
_spawn_lock = threading.Lock()          # serializes attempt CREATION
_spawn_in_flight: Optional[_SpawnAttempt] = None   # shared result object
```

`_ensure_vision_server_running()` becomes:

1. Fast path: health check OK -> True (unchanged).
2. Under `_spawn_lock`: if `_spawn_in_flight` is alive -> attach as waiter
   (log "awaiting in-flight spawn"), release lock, wait on the attempt's
   completion event, return its result.
3. Else create the attempt (owns its own threading.Event + result), store it,
   release `_spawn_lock`, run the existing spawn+ready-poll INSIDE the attempt,
   publish result, clear `_spawn_in_flight`.

Why a threading primitive and not asyncio.Lock: callers enter from both
`asyncio.to_thread` workers and sync paths; a threading.Event is correct under
both. Waiters block their worker thread for at most the ready-poll budget —
identical to today's cost of spawning themselves, minus the duplicate process.

Failure semantics: the ATTEMPT owns cleanup (2.2). Waiters never clean up.
A failed attempt clears itself so the next call retries fresh.

### 2.2 Ownership-safe cleanup (REQ-2)

The attempt records `proc.pid` (the REAL server PID after REQ-3). Failure
cleanup kills only that PID via the existing `_kill_pid`, plus — on Windows —
`taskkill /T` for the child tree. The netstat port-scan kill is deleted from
this path entirely. `_resolve_listener_pid` survives only if some other caller
still needs it; otherwise removed (REQ-3 AC5).

PID-reuse guard: before killing, read the process command line
(`wmic process where processid=X get commandline` or psutil-free fallback:
skip the check and log when unavailable) and abort the kill if it does not
contain the spawned binary name. Best-effort, logged both ways.

### 2.3 Direct detached spawn (REQ-3)

Replace:

```python
cmd = [sys.executable, "-c", _LAUNCHER_SRC] + cmd   # wrapper interpreter
```

with a plain direct spawn (**AS SHIPPED 2026-08-24**):

```python
_popen_kwargs = {}
if os.name == "nt":
    _popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
else:
    _popen_kwargs["start_new_session"] = True
proc = subprocess.Popen(
    cmd,
    stdout=subprocess.DEVNULL,      # llama.cpp logs to stderr; nothing to drain
    stderr=vision_stderr,           # log file — diagnosable, no pipe to fill
    stdin=subprocess.DEVNULL,       # never block on a console read
    cwd=str(Path(binary).parent),   # Windows loader finds the CUDA DLLs
    env=env,                        # inherited verbatim
    **_popen_kwargs,
)
```

**The earlier draft of this section was wrong and is corrected here.** It
prescribed `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`
and justified it as breaking a "torch-CUDA parent" inheritance chain. There is
no such hang (see REQ-3 "Verified"), and `DETACHED_PROCESS` specifically was
measured to make the stall WORSE. It also wrote `stdout=stderr_log,
stderr=subprocess.STDOUT`; the shipped code sends stdout to DEVNULL because
llama.cpp logs to stderr, and an undrained `stdout=PIPE` is a latent deadlock
(the removed wrapper had exactly that bug — nothing read the pipe until after
readiness).

`IRIS_VISION_SPAWN_WRAPPER` and the stdout-PID protocol are DELETED, not
flag-disabled. `_VISION_SERVER_PID` is `proc.pid` directly (AC3) and `ttr_sec`
logging is untouched (AC4).

Readiness is PATIENT by design (REQ-3 AC6): a live process is never killed for
silence, because llama.cpp emits nothing for the whole model+mmproj load and a
process blocked in a filesystem filter driver shows flat cpu, flat io and flat
log size. `_proc_cpu_seconds()` is an ADDITIONAL progress signal, never a
liveness veto.

### 2.4 Search-scoped warmth (REQ-4)

New function in `lfm_vl_provider.py`: `request_warm(trigger: str)` —
idempotent, bounded (one in-flight warm), honors reserve, emits lifecycle
events, delegates the actual spawn to `_ensure_vision_server_running`
(inheriting single-flight).

Hook site: the gateway already observes crawl starts (`iris_gateway.py`
crawl_research handler). On `CRAWLER_STARTED`, schedule
`loop.create_task(self._warm_vision_for_search())` which awaits pool readiness
(the pool exposes a ready signal or a short bounded poll of worker liveness;
when `IRIS_CRAWL_POOL=0`, await the fallback worker warm flag) then calls
`request_warm("search-scoped")`. Boot prewarm switches to
`request_warm("boot")`. Lazy first-call remains trigger `"lazy-call"`.

Starvation guard (conv-53): the warm task runs AFTER pool readiness, not
concurrently with pool spin-up, and the VRAM reserve math is unchanged.

### 2.5 Lifecycle broadcast (REQ-5)

`set_vision_idle_callback` pattern generalized: provider calls a registered
`_notify_lifecycle(state, reason)` on transitions:
cold (idle-stop fired / boot default) -> spawning (attempt starts) ->
warm (health check passes) -> error (spawn failed / no model fits).

Gateway forwards as `vision_status` WS messages using the EXISTING message
shape, adding `{state, reason?, trigger?}` fields additively. Frontend
`useIRISWebSocket.ts` already has a `vision_status` case
(`useIRISWebSocket.ts:1072-1104`) — extend its detail mapping, dispatch
`iris:vision_status`.

Chip component (`components/iris/browser/VisionLifecycleChip.tsx`): 8px dot +
label, colors: cold=slate, spawning=amber pulse, warm=emerald, error=red.
Rendered in the browser panel header row while `crawlState.active || state!=='cold'`.
Best-effort emission wrapped in try/except (never fails a vision call).

## 3. Frontend stage

### 3.1 Ambient tier (REQ-6)

New `components/iris/AmbientCrawlTier.tsx`, mounted in the app shell OUTSIDE
DashboardWing (same level as the orb shells — the wing-independent layer where
XurOrb lives). Consumes `useCrawlContext()` (the hoisted CrawlProvider — no
duplicate listeners, AC4).

Rendering contract:
- Wing closed OR dashboard not on browser sub-app OR chat-spotlighted ->
  ambient tier ACTIVE: a compact ring around/beside the orb showing phase
  (loading/dispersing/crawling pulses at low intensity), page counter text,
  current vision action word, escalation color shift. Sized ~40px footprint.
- Browser panel open & visible -> ambient tier MINIMAL: dot only (panel is
  primary).
- prefers-reduced-motion -> static text line ("reading 3/5 · scrolling").
- Reuses OrbCanvas engine at small size for visual continuity; does NOT
  duplicate the shutter geometry.

Visibility predicate shared with DashboardWing's spotlight logic — extract
`useWingVisibility()` helper so panel and ambient tier agree on "is the panel
actually visible" instead of each guessing.

### 3.2 Backfill (REQ-7)

`useBrowserNavOverlay` accepts optional seed input derived from
`useCrawlContext()` inside DarkGlassDashboard and passed down:

```ts
const { status } = useBrowserNavOverlay({ seedFrom: crawlState })
```

On mount (and when `seedFrom` identity changes to an active run), compute the
equivalent NavOverlayStatus (state=crawling if pages exist else loading,
pagesDone/pagesTotal, last visionAction step/coords). Idempotency: track a
`seededRunRef` keyed by session/query+start marker so SSE snapshot replays do
not double-seed (mirrors `processedCrawlTabsRef` pattern at
`dark-glass-dashboard.tsx:697`).

### 3.3 The eye: blink, hex-scan, notice (REQ-8)

The border canvas becomes the VLM's eye. Three grammar elements on ONE canvas
in the EXISTING rAF loop (REQ-8 AC4 — no new canvases, no per-cell DOM):

**Blink (attention).** Unchanged impulse path, extended: `shutterRef.current
= 1` fires on `pagesDone` changes AND in the `visionStep` effect (line 288).
One blink = one act of attention by the model.

**Hex-scan (reading).** During vision interaction (`visionAction !== ""` and
actions arriving), the edge-wash band renders a hexagonal cell lattice:

- Geometry: precomputed ONCE per measure() — hex centers tiled across the
  four edge bands (depth = existing `edgeGradients` base depth), axial hex
  tiling, cell radius ~9px scaled by `sizeScale`. Stored as flat Float32Array
  of (x, y, band-normal) — no objects, no allocation per frame.
- Activation front: a scalar `scanPhase` integrated per frame exactly like
  `phaseRef` (dt/lapMs gearing reuses the live crawl cadence). Each cell's
  alpha = falloff of its projected arc-position distance behind the scan head,
  times a per-cell shimmer `sin(cellSeed + elapsed*0.003)`.
- Cursor bias: cells within an angular window centered on the cursor's side
  of the perimeter get a 1.5x intensity multiplier with soft falloff — the
  eye "concentrates" where the model is acting.
- Draw: single pass, `globalCompositeOperation: "lighter"` over the dark
  vignette, fillRect-free (per-cell small arcs or pre-rendered hex sprite
  stamped via drawImage — pick during implementation, benchmark both; the
  sprite stamp avoids 200+ beginPath/arc calls per frame).
- Lifecycle: lattice alpha eases to 0 when actions stop arriving (one lap
  timeout) — scan means READING, not decoration.

Frame budget: bounded by edge-band cell count (~150–300 cells at maximised
size); with the sprite-stamp approach this is one drawImage per lit cell —
well under the budget the particle streams already use. If profiling shows
otherwise, halve cell density before touching anything else.

**Notice (escalation).** On `escalated: true` first action: aperture pinned
open (shutterRef held 0) for NOTICE_MS=1600, scan front speed x2 and
brightness x1.5, glowColor lerped toward violet for the window, one expanding
ring reusing `.iris-nav-touch` keyframes. Throttle 5s via ref. Reduced
motion: color shift only (AC5/AC6).

Reduced-motion degradation: lattice renders as a static lit band at fixed low
alpha; blinks become opacity steps (no eased close/open).

### 3.4 Aspect-correct cursor (REQ-9)

Mapping util in `useBrowserNavOverlay`:

```ts
function mapPoint(x, y, vw, vh, boxW, boxH) {
  // letterbox-aware: scale source viewport into box preserving aspect,
  // center the remainder on the other axis
}
```

Applied where cursor/trail positions are computed (lines 288-298 consume
fractions). Absent vw/vh -> identity (current behavior).

### 3.5 Fit-to-width reading surface (REQ-10)

Server-injected scaler (survives opaque-origin sandbox AND the served CSP,
AC3). CRITICAL MECHANISM NOTE found in ripple review: both serve paths run
`script-src 'nonce-{nonce}'` CSP (`browser_surface.py:82`) and inject the
view-agent through `inject_view_agent(html, nonce=nonce)` (`:169` capture,
`:307` proxy; upstream CSP already scrubbed on the proxy path `:182`). The
scaler MUST ride the SAME mechanism:

- Add `inject_view_scaler(html: str, nonce: str) -> str` in
  `backend/proxy/view_agent.py` (same file, same idempotency marker pattern,
  same nonce attribute on the script tag), called immediately after
  `inject_view_agent` at BOTH sites. A bare `<script>` without the nonce is
  silently dead — the failure mode the CSP comment block (:45-73) documents
  from live experience.

Scaler script (nonce-tagged, idempotent):

```html
<script nonce="{nonce}" data-iris-scaler>
(function(){
  function fit(){
    var w = document.documentElement.scrollWidth || document.body.scrollWidth;
    var target = window.innerWidth;              // frame client width
    var s = Math.min(1, target / w);
    document.documentElement.style.transformOrigin = '0 0';
    document.documentElement.style.transform = s < 1 ? 'scale(' + s + ')' : '';
    document.documentElement.style.width = target + 'px';
    window.__irisScale = s;
  }
  addEventListener('resize', fit); addEventListener('load', fit); fit();
})()
</script>
```

- Scroll mirroring translation: `sendScrollTo(top)` from parent sends raw
  offsets; the view-agent script multiplies by `window.__irisScale` before
  applying — keeps REQ-10 AC4 without changing the parent-side contract.
- Old captures without scaler: served unchanged (edge case honored).
- Fixed-width narrower pages: `s = min(1, ...)` never upscales; centering via
  existing body margin auto behavior — acceptable v1.

Implementation home: `backend/proxy/view_agent.py` (NOT a new module — one
injection mechanism, not two), unit-tested against fixture HTML (headless
doc, existing head, idempotent double-injection).

OPTIMIZATION GATE: injection is ONE linear pass appending before `</head>`/
prepend — no full-document regex rescan, no per-request DOM parse. The store
holds ORIGINAL bytes; injection happens at SERVE time and must stay O(n) with
a single scan for the insertion point (reuse whatever anchor search
`inject_view_agent` already does — share the helper, do not write a second
search).

### 3.7 Single Live Reading surface (REQ-15)

Replace the tab-per-page effect (`dark-glass-dashboard.tsx:697-727`) with a
stable-tab navigator:

- ONE tab id `live-reading` (type `web`) created lazily on the first fetched
  page. Its provenance fields (`captureJobId`/`capturePageNumber`/
  `captureFetchedAt`) are REWRITTEN on every page event — `useActiveFrameSrc`
  already resolves the frame src from per-tab provenance, so a src swap is
  the only navigation primitive needed. No contract change there.
- Following mode: the surface points at the latest page event, coalescing
  arrivals inside a 300ms window (latest wins) so concurrent dispatch cannot
  flicker through intermediate pages.
- Pin mode: selecting a source from the PlanCard sets the surface to that
  source's capture address and pauses following; a "LIVE" pill on the address
  bar resumes following (and shows when following is active). Pin state dies
  with the run.
- Non-stored captures (challenge walls): same routing as today — tab without
  replayable provenance goes through the proxy.
- Summary tab: untouched; arrives via backend `open_tab` as before.
- The processed-set ref (idempotency vs snapshot replay) survives in the same
  role: keyed by `${jobId}:${addr}`, now guarding NAVIGATION instead of tab
  creation.

PlanCard sources become clickable: each source row already holds
`jobId` + `capturePage`; clicking dispatches a local event
(`iris:view_source {job_id, capture_page}`) consumed by the dashboard to pin
the reading surface. No new backend surface.

### 3.8 Space reclamation (REQ-11)

- `dark-glass-dashboard.tsx:1834` browser branch: `p-4 md:px-10` -> `p-1.5`
  (6px) uniformly; card keeps rounded-2xl.
- Tab strip h-9 (36px) stays (touch target); address bar h-10 -> h-9.
- Verify overlay ResizeObserver picks up new geometry (it measures — just
  confirm visually via simulator scenario k).
- No other sub-app branches touched (AC4): the padding class is scoped to the
  browser ternary branch only.

## 4. Vision Stage Simulator (REQ-12)

New dev-only surface: route `/dev/vision-stage` (guarded by
`useLauncherMode().isDeveloper`) plus a hidden rail entry in developer mode.

Architecture — inject through the REAL contract:

```ts
// simulator/scenarios.ts
export const SCENARIOS: Scenario[] = [
  { id: 'crawl-full', label: 'Crawl: loading→crawling→complete',
    steps: [
      { ev: 'iris:crawler_started', detail: {...}, atMs: 0 },
      { ev: 'iris:crawler_page_fetched', detail: {...}, atMs: 1200 },
      ...
    ] },
  ...
]
```

Runner: `setTimeout` chain dispatching `window.dispatchEvent(new CustomEvent(ev, {detail}))`.
For scenarios needing CrawlProvider state (j: backfill), the runner drives the
SSE fallback path instead — `useCrawlSSE` re-dispatches the same events, so
CustomEvent injection reaches the provider too (verify during implementation;
if the provider filters synthetic events, extend the runner to also POST a
local replay endpoint — decision recorded in tasks T-SIM notes).

Scenario list = the Sign-off checklist in tasks.md, items a–m (authoritative;
REQ-12 AC1 mirrors it), each with a written expected-beat
checklist rendered next to the run button (checkboxes persisted to
localStorage so sign-off survives reloads). Reset button dispatches
`iris:crawler_complete` + clears provider state. Live-crawl guard: disabled
buttons + notice when `crawlState.active`.

Fixtures: one wide captured HTML page (~1600px natural width) committed under
`__tests__/fixtures/wide-page.html` served through the capture endpoint stub
for scenario k.

## 5. Pipeline reduction (REQ-13)

- VRAM read-once: `_find_vision_model` and `_compute_vision_gpu_layers` take
  an optional pre-read `(free_gb, readable, cuda_available)` tuple; the spawn
  path reads once and threads it through. Signatures stay backward-compatible
  (default None -> read internally) so tests pass unchanged (AC5).
- Lease-held probe skip: `_call()` checks `has_active_lease()` -> skips health
  GET. Liveness under lease: the idle watchdog already defers to leases; add a
  cheap supervision tick — the lease holder (fetch.vision loop) wraps each
  action call; a connection error triggers single-flight respawn (AC4).
  Net effect per 8-step session: up to 8 probes removed.
- Shared-Chromium evaluation (AC3): spike task measures (a) crash blast radius
  of sharing, (b) cold-start savings. Decision recorded in tasks.md before
  spec close; implement only if isolation preserved via separate CONTEXTS
  (Playwright browser + isolated contexts) AND a vision crash cannot poison
  pool workers. Default posture: record rejection unless both hold.

## 6. Error handling summary

| Failure | Outcome |
|---|---|
| Concurrent spawns | One attempt; waiters share result (REQ-1) |
| Spawn fails | Attempt cleans own tree; lifecycle `error`; VISION_UNAVAILABLE path unchanged |
| Server dies mid-lease | Next action call errors -> respawn via single-flight; session degrades gracefully (existing REQ-7 AC6 behavior) |
| Warm blocked (VRAM) | lifecycle error + reason; search proceeds crawl-only |
| Scaler injection fails (malformed HTML) | Serve original bytes; log debug |
| Simulator event during live crawl | Blocked with notice |

## 7. Testing strategy (contract → behavioral → unit)

Contract tests (pin boundaries BEFORE behavior work):
- CT-1: spawn coalescing — two threads call ensure; assert ONE Popen (mock),
  both get same result. Pins REQ-1.
- CT-2: failure cleanup kills only attempt-owned PID; unowned listener
  survives. Pins REQ-2.
- CT-3: direct spawn argv carries detachment flags; `_VISION_SERVER_PID` set
  synchronously post-spawn; ttr_sec still logged. Pins REQ-3.
- CT-4: `crawler_vision_action` payload carries `escalated` (ux_map +
  emitter). Pins REQ-8 backend half.
- CT-5: capture/proxy responses contain scaler injection for well-formed
  fixtures; malformed HTML passes through byte-identical. Pins REQ-10.
- CT-6: overlay pointer-events guard (grep-shaped over component source).
  Pins REQ-14 AC1.
- CT-7: no inbound control channel into BrowserSession (grep-shaped).
  Pins REQ-14 AC2.
- CT-8: vision_status payload shape additive vs existing consumers.

Behavioral tests:
- BT-1: full simulated run through simulator runner asserting
  `iris:nav_overlay_state` trace sequence matches scenario script (structured,
  not pixels — mirrors REQ-18 AC9 pattern).
- BT-2: backfill — mount panel mid-run from seeded provider state; assert
  first trace transition originates from seed, not idle.
- BT-3: warm-for-search sequencing — mock pool readiness; assert request_warm
  fires after ready signal, once per run.

Unit tests:
- UT-1: mapPoint aspect cases (wide/tall/equal/absent).
- UT-2: inject_viewport_scaler fixtures.
- UT-3: request_warm idempotency/bounds.

Live confirmation (cannot be done by agent, mirrors T14b discipline):
- LV-1: measure ttr_sec on real hardware for direct-spawn path.
- LV-2: conv-numbered live run: search 10min after boot sees chip spawning→warm.
- LV-3: visual sign-off of all simulator scenarios by the user (THE gate).

## 8. Ripple-effect map (files expected to change)

Backend:
- `backend/tools/lfm_vl_provider.py` (REQ-1,2,3,4,5,13)
- `backend/iris_gateway.py` (REQ-4 hook, REQ-5 forward, **REQ-8 `escalated`
  key added to the CRAWLER_VISION_ACTION whitelist at :10205 — the code
  comment there warns new fields die in exactly this tuple**)
- `backend/crawler/ux_map.py` (REQ-8 escalated field)
- `backend/orchestrator.py` or its emit site (escalated flag source)
- `backend/api/browser_surface.py` (REQ-10: call the scaler injector at BOTH
  serve sites :169/:307)
- `backend/proxy/view_agent.py` (REQ-10: scaler injector lives HERE, next to
  the view-agent — one injection mechanism)
- `backend/agent/tool_bridge.py` (NO EDIT — but named: its :734 direct
  `_ensure_vision_server_running` call is a covered REQ-1 entry point and CT-1
  must exercise it; a future editor adding a fifth bypass caller is what the
  single-flight function itself guards)

Frontend:
- `hooks/useBrowserNavOverlay.ts` (REQ-7,8,9)
- `components/iris/browser/BrowserNavigationOverlay.tsx` (REQ-8)
- `components/dark-glass-dashboard.tsx` (REQ-11 padding, chip mount, seed
  pass, REQ-15 live-reading navigator)
- PlanCard component (REQ-15 clickable sources)
- `components/dashboard-wing.tsx` (visibility helper extraction only)
- `components/iris/AmbientCrawlTier.tsx` (NEW)
- `components/iris/browser/VisionLifecycleChip.tsx` (NEW)
- `app/dev/vision-stage/page.tsx` + `simulator/` (NEW)
- `hooks/useIRISWebSocket.ts` (vision_status detail extension)
- `hooks/useViewProtocol.ts` / view-agent script (scale-aware scrollTo)

Tests: `backend/tests/contract/`, `backend/tests/unit/`,
`__tests__/components/`, `__tests__/simulator/`.

Anything outside this list requires justification in the task report.

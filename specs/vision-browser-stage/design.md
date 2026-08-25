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
- Scroll round-trip fusion (landed 2026-08-24, T15): `BrowserSession._execute`
  issued TWO `page.evaluate` calls per scroll — the `scrollBy`, then a second
  read of `{y, h}` for the REQ-16 AC7 absolute-position mirror. A vision
  session is scroll-dominated, so that doubled the CDP traffic of its hottest
  action for a value available on the same tick: `window.scrollBy` with the
  default (instant) behavior applies synchronously, so reading
  `pageYOffset`/`scrollHeight` in the SAME script already observes the
  post-scroll document. Now one round trip. The mirror read sits in a JS
  try/catch so a failed read still cannot cost the scroll; the evaluate itself
  is deliberately NOT wrapped in Python try/except, because it now performs the
  scroll and a failure must surface as `last_error` (REQ-7 AC6) rather than be
  swallowed as a missing mirror reading.

- Shared-Chromium evaluation (AC3): **REJECTED 2026-08-24 — see tasks.md T17
  for the measurements.** The gate condition "isolation preserved via separate
  CONTEXTS" turns out to rest on a false premise: contexts are cookie/storage
  domains, not crash domains. Killing the browser process killed BOTH contexts
  (`TargetClosedError` on each) and disconnected the browser, so one consumer's
  crash necessarily destroys the other's. Separately, sharing would trade a
  0.145s warm launch for a 1.701s CDP attach — ~11x slower at steady state —
  and both sides already avoid per-use launches entirely (`browser_pool.py` for
  vision, `_WarmCrawlPool` for crawl), so there was no cold-start saving left
  to capture.

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

## 9. REQ-16 design notes (AmbientCrawlTier repurposed — Wave 6, not started)

User-directed 2026-08-24 across multiple feedback rounds. THE VERBATIM INTENT:
the user loves the tier's design/style and wants it PROMOTED to be the orb's
working presence everywhere, replacing OrbBadge entirely. Detailed below so an
implementing agent needs nothing else.

### 9.1 The two forms of the tier

**FORM A — COUNTER FORM (no wings open, task/crawl active):**

- The tier renders AS a radial progress counter. There is **NO mini orb
  thumbnail positioned to its left** — the user explicitly rejected that
  layout ("without orb positioned to the left"). The tier's own identity
  (ring + moving particles) IS re-expressed as the counter:
  - a RADIAL PROGRESS RING (SVG stroke-dasharray or conic-gradient, glowColor)
    whose fill = unified done/total (see 9.4);
  - the `[done/total]` text bubble INSIDE/beside the ring, styled exactly like
    CardChassis `chassis-counter` (9.5px mono bold, vein tint bg/border);
  - the existing OrbCanvas particle field drifting BEHIND the counter (same
    engine, same breath grammar — T11 OPT gate preserved);
  - the one-line status (query · pages · vision action) retained beneath.
- Position: anchored at the counter location near the orb (where OrbBadge used
  to sit relative to the XurOrb) — NEVER overlapping the XurOrb, never with a
  duplicate mini-orb beside it.
- INTERACTIVE: clicking the counter opens a small inline text input anchored
  to the tier (glass style matching the tier). Enter submits;
  Esc/blur dismisses. This is how the user asks/types WITHOUT opening wings.

**FORM B — SWALLOWED FORM (any wing open, task/crawl active):**

- Trigger: any wing (ChatWing OR DashboardWing) opens while a run is active.
- The XurOrb appears to be SWALLOWED by the tier: FLIP-style transition —
  measure the orb's centre rect and the tier's anchor rect, animate the orb's
  scale+translate into the tier over ~450ms ease-in-out while the tier fades/
  expands around it. After the swallow, the tier displays WITH the orb inside
  it (the OrbCanvas in the tier represents the absorbed orb).
- HARD EXCLUSIVITY: while a wing is open during an active run, the XurOrb and
  the tier are never both visible. The orb is hidden (opacity 0,
  pointer-events none) for the whole swallowed period.
- Supersedes T11's old "minimal dot when panel visible" mode — any wing open
  means Form B, not the dot.

### 9.2 Release transition

- Trigger: the active task/crawl COMPLETES (crawl terminal state AND task
  progress no longer running). Fires regardless of wing state.
- Reverse FLIP: the tier contracts toward the orb's resting centre, the orb
  fades back in at centre, the tier unmounts (idle null-gate takes over).
- If completion lands MID-swallow: finish the swallow, then immediately play
  the release. No half-states, no skipped frames.

### 9.3 OrbBadge retirement

- Remove the OrbBadge mount from `XurOrb.tsx` (:487) and its visibility
  computation (:136-141). The tier inherits the working-indicator job in FULL.
- Keep `OrbBadge.tsx` on disk until the "?" question-variant fate is decided
  (Open Question in requirements.md).

### 9.4 Unified counting (AC5)

- done/total merges useTaskProgress steps AND CrawlProvider pages: steps-only
  runs show steps; crawl-only runs show pages; mixed runs sum both. NEVER
  render `[0/0]` — hide the bubble until at least one unit of progress exists
  (mirrors the overlay counter rule).
- Data arrives via the existing WS dispatch path (no polling, no new
  listeners beyond what T11/T10 already installed).

### 9.5 Thread-safe inline ask (AC4)

- Submit sends `sendMessage("text_message", { message, conversation_id })`
  where conversation_id is sourced EXACTLY as ChatView sources it. The socket
  owns identity (LEARN/SUPPLY, useIRISWebSocket :1741-1804) — the tier must
  NOT read localStorage directly and must NOT invent an id. If no active
  thread exists, route through ChatView's thread-creation path first.
- Contract test required: submitted payload carries the id of the thread
  active AT SUBMIT TIME (guards against stale-localStorage merge — the
  conv-merge incident).

### 9.6 Reduced motion (AC7)

- Swallow/release become simple opacity crossfades (~200ms). Counter form
  identical minus particle drift (static ring + bubble).

### 9.7 Locked decisions (user-directed)

1. OrbBadge retires; the tier inherits its job ("same thing but better").
2. NO left-side mini orb in Form A — the tier IS the counter.
3. The tier's design/style is loved — do NOT restyle it while repurposing;
   extend, don't replace.
4. Simulator checklist frozen at a–m; T21's new scenarios need explicit user
   ack before the checklist table gains rows.

Ripple additions for REQ-16: `components/iris/XurOrb.tsx` (badge retirement +
swallow hooks), `components/chat-view.tsx` / wing visibility source (any-wing
signal), `components/iris/AmbientCrawlTier.tsx` (both forms + transitions),
and a contract test pinning the inline-ask conversation_id behavior.

Tests: `backend/tests/contract/`, `backend/tests/unit/`,
`__tests__/components/`, `__tests__/simulator/`.

Anything outside this list requires justification in the task report.

## 10. Mesh film design notes (REQ-17 — signed off 2026-08-24)

Lives entirely in `BrowserNavigationOverlay.tsx`, beside `drawHexScan` and
sharing its clock. Drawn BEFORE the band each frame so the signed-off border
lattice keeps its visual weight on top.

**Geometry (once per resize).** Its own honeycomb, pitch derived from
`meshR = hexR * MESH_CELL_SCALE` — NOT from `hexR`. A lattice is only
self-consistent, and its walls only shared, when spacing matches the radius it
is drawn at; scaling the radius while leaving the pitch behind silently breaks
the dedup and every cell goes private again. Starts at `rows[1] + hexR + meshR`
so the first course abuts the band rather than floating inside it.

**Walls, not cells.** The lattice is decomposed into unique undirected EDGES,
keyed on quantised endpoints so the two cells meeting at a wall agree on its
identity. Measured 35-42% of emitted walls collapse. This dedup IS the
mechanism: a wall is one object two cells share, which is what lets growth
cross between them. Stroking whole hexes can only ever read as cells blinking.

**Arrival.** Each wall stores its position on the 0..1 scale a wave sweeps:

    arrival = depth + contourNoise + patchJitter + ringSpread

- `depth` — dominant; boundary first, centre last. Makes waves travel inward.
- `contourNoise` — REQUIRED (REQ-17 AC5). `depth` is distance to the nearest
  edge, whose iso-contours are concentric RECTANGLES, so a front sweeping it
  collapses as a square. The warp uses two different-frequency trig terms on x
  and y MULTIPLIED — a `sin(x)+sin(y)` leaves visible axis grain, the same
  failure in another costume. Measured: front depth-spread 0.008-0.018 without
  it (a clean rectangle), 0.043-0.046 with.
- `patchJitter` — so neighbouring patches do not ignite on one contour line.
- `ringSpread` — within a patch the seed is reached before the rim, so a comb
  ASSEMBLES from its middle as the wave crosses rather than snapping on.

**Waves.** One launched per kick-pulse shutter, several alive at once. Every
third runs centre-outward: a purely inward cadence trains the eye to expect the
collapse and makes it more legible each repetition, and an outward wave sweeps
the contours in the opposite order so the two never superimpose. Behind each
front a wall traces in (dash animation), holds, then fades — that fade is the
trail. Deep walls are softened so the centre reads as growth petering out.

**Two relationships that are arithmetic, not taste:**
1. `DRAW+HOLD+FADE` vs launch spacing. Narrower leaves dark gaps and distinct
   marching rings; wider merges into continuous comb. Measured: band 0.49 at a
   620ms launch rate saturated to 100% lit within 4s.
2. `MESH_WAVE_LIFE` must cover the deepest arrival INCLUDING noise/jitter/
   spread. It is derived from those constants, not hand-set, so it cannot drift
   out of step when they are tuned.

**Cost (AC7).** Geometry, adjacency and growth order resolved at resize.
Completed walls batch into one path per alpha bucket; only walls mid-trace pay
a `setLineDash` + individual stroke — ~160-200 strokes/frame instead of ~1200
state changes.

**Parity (AC8).** The enable switch is a localStorage PREFERENCE
(`MESH_PREF_KEY`) read identically by the overlay and the simulator, never a
simulator-only event — so no dev-only render path exists and what is signed off
is what ships. Default ON; only an explicit "0" disables.

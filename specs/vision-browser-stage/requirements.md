# Requirements: Vision Browser Stage (VLM lifecycle + visual framework + reading surface)

## Decisions Locked
User-resolved 2026-08-23. Do not re-litigate.

1. **The VLM spawn is single-flight.** Concurrent callers of
   `_ensure_vision_server_running` await ONE spawn. No second llama-server is
   ever launched while a spawn is in progress.
2. **Cleanup never kills an unowned listener.** The failed-start path kills
   only processes THIS attempt spawned, verified by lineage — never "whatever
   listens on the port".
3. **The spawn path is SIMPLIFIED, not just locked.** The launcher-wrapper +
   netstat PID-adoption dance is replaced by a direct spawn whose PID IRIS owns
   from the start. Fewer steps, same functionality.
4. **Warmth is search-scoped.** `crawler_started` triggers a staggered re-warm
   when the owned server is cold. The boot prewarm stays. Neither may starve
   the crawl pool (conv-53 lesson: the Session-248 search-start prewarm was
   rejected for starving pool workers — the new trigger is sequenced AFTER the
   pool is live and honors the VRAM reserve).
5. **Vision lifecycle truth reaches the UI.** cold / spawning / warm / error
   states are broadcast on the existing `vision_status` channel and rendered as
   a chip in the browser panel. Dead air during a 25–40s spawn becomes
   narrated air.
6. **The visual framework must be visible wherever the user is.** An ambient
   tier carries the animation grammar on a surface that exists even when the
   DashboardWing is closed or chat-spotlighted. The full shutter remains on the
   browser panel.
7. **Every animation is simulatable on demand.** A Vision Stage Simulator can
   inject scripted agent-action event sequences that drive EVERY overlay state
   deterministically, so the user signs off each effect during implementation —
   without running real searches or a real VLM.
8. **The overlay never interferes with anyone.** It stays pointer-events-none
   (pinned by test), and the agent's headless session is architecturally
   independent of the iframe mirror. Both facts become permanent guards.
9. **The reading surface fits the frame.** Captured pages are scaled to the
   iframe width; the whole page width is always visible without horizontal
   scrolling. Height scrolls naturally.
10. **Dead space around the iframe is reclaimed.** The browser viewport uses
    the panel area between the dashboard borders; padding is audited and
    minimized deliberately, not inherited.
11. **Pipeline steps are reduced where they are redundant**, keeping
    functionality: one spawn path, no per-call redundant work, no duplicate
    browser-stack cold starts where a shared resource already exists.
12. **One reading surface, not a tab per page.** The panel does not open a
    new tab per crawled page. A single Live Reading tab navigates
    capture-to-capture as the agent reads; sources are browsable from the
    existing source list, and the end-of-run summary tab stays.

## Introduction

The unified-vision-routing spec landed the BRAIN -> TOOL -> VL-fallback
hierarchy; post-spec additions added boot-time VLM prewarm and a particle-
shutter overlay on the browser panel. Live behavior falls short in three ways:

- The VLM server launch is brittle under concurrency (no spawn lock; the
  failure path can kill a healthy server it did not start) and its prewarm
  evaporates to the 120s idle-stop before most searches begin.
- The visual framework (shutter, orb cursor, scroll mirror) is mounted inside
  the browser sub-app of a wing that may be closed, dimmed, or blurred — so
  users consistently see only the brief shutter burst when a tab opens.
- The reading surface replays raw captured HTML at natural page width inside a
  narrow frame with inherited padding, so pages render far larger than the
  frame and dead space surrounds the viewport.

This feature makes the vision-browser stage reliable, visible, sign-off-able,
and simpler.

### Success criteria
- Two concurrent vision escalations produce exactly ONE llama-server spawn,
  and the loser of a failed race cannot kill the winner's server.
- A search started 10 minutes after backend boot finds a warm VLM endpoint or
  sees "spawning" in the UI within 2s of crawler_started — never silent dead air.
- Every overlay state (loading, dispersing, crawling, complete, error, cursor
  click/type/scroll, escalation beat, idle-stop) can be demonstrated by
  clicking a scenario button in the simulator, with zero backend involvement.
- A captured page renders fit-to-width in the browser panel; no horizontal
  scrollbar at any panel size.
- The overlay passes a contract test asserting it consumes no pointer events.

## Requirements

### REQ-1: Single-flight VLM spawn
**User Story:** As IRIS I want concurrent vision consumers to share one server
spawn, so races cannot multiply processes or fail sessions spuriously.

**Verified:** REAL GAP. `_ensure_vision_server_running`
(`backend/tools/lfm_vl_provider.py:808`) has no lock: health-check miss ->
spawn -> poll. Callers that overlap during the ~25–40s ready window each spawn;
losers fail port-bind, and their cleanup (`:1004-1007`) kills whatever listens
on the port — including the winner. Overlap is structural — FOUR production
entry points funnel into it: boot prewarm (`iris_gateway.py:398`), the lazy
call path (`lfm_vl_provider.py:1068`), explicit enable (`start()`,
`:1149`), and the vision MCP tool path (`tool_bridge.py:734-736`). The
orchestrator compounds this by racing fetch.crawl vs fetch.vision per URL
(`orchestrator.py:1457-1479`) and dispatching N URLs concurrently.

**Acceptance Criteria:**
- AC1: WHEN a spawn is in progress THEN THE SYSTEM SHALL make concurrent
  `_ensure_vision_server_running` calls await the SAME in-flight attempt and
  return its result, not start a second spawn — from ANY of the four entry
  points.
- AC2: THE SYSTEM SHALL serialize spawn attempts across both the sync caller
  path (`asyncio.to_thread`) and any direct sync entry, using one lock that is
  correct under threads.
- AC3: WHEN two escalations start simultaneously against a cold server THEN
  exactly one llama-server process SHALL exist afterward.
- AC4: THE SYSTEM SHALL log the coalescing ("awaiting in-flight spawn") once
  per waiter, so concurrency behavior is observable.
- AC5: THE HEALTH FAST PATH SHALL stay OUTSIDE the lock — a warm server must
  never contend on the mutex just to be checked (per-call hot path).

**Edge Cases:**
- The in-flight spawn fails -> all waiters receive False together; the next
  call may retry.
- A waiter times out waiting -> it returns False without cancelling the
  in-flight attempt (the attempt owns the outcome).

### REQ-2: Ownership-safe cleanup
**User Story:** As a user I want a failed vision start to clean up only its own
processes, so a healthy server (mine or another attempt's) is never killed.

**Verified:** REAL GAP. Failure path resolves "whatever is on the port" via
netstat substring match and kills it (`lfm_vl_provider.py:1004-1007`,
`:213-232`).

**Acceptance Criteria:**
- AC1: WHEN a spawn attempt fails THEN THE SYSTEM SHALL kill only the process
  tree IT created (its own PID and verified children).
- AC2: THE SYSTEM SHALL NOT resolve or kill a listener by port scan on the
  failure path.
- AC3: WHEN IRIS did not spawn the running server (user-run llama-server) THEN
  disable()/idle-stop SHALL continue to leave it alone (existing contract).

**Edge Cases:**
- PID reuse between spawn and kill -> kill is skipped if the process command
  line does not name the spawned binary (best-effort check, logged).

### REQ-3: Simplified spawn path
**User Story:** As a maintainer I want one direct spawn with a known PID, so
the launcher wrapper and netstat adoption disappear.

**Verified (CORRECTED 2026-08-24 — the original premise was falsified):**
The launcher wrapper was introduced on the theory that "a torch-CUDA parent
hangs llama.cpp's device probe (documented live 2026-08-12)". That theory is
FALSE and must not be reinstated. Measured refutation, session s_2ce855d976aa:

- the identical stall reproduces from a parent that never imports torch/CUDA,
  console-less (`GetConsoleWindow()==0`), with a fully inherited env;
- it reproduces from a plain shell with a plain `Popen`;
- a parent that HAS imported torch, `llama_cpp` and `local_model_manager`
  spawns a healthy server in 3.7s;
- `-ngl 0` (pure CPU, zero GPU allocation) stalls too.

The real cause is HOST I/O CONTENTION on the model files, not process context
— see the new Edge Cases below and REQ-3's operational note. Spawn mechanics
were exhaustively ruled out: wrapper vs plain, `cwd`, `stdin=DEVNULL`,
`CREATE_NEW_PROCESS_GROUP`, env mutation, port, VRAM headroom, batch size and
binary choice all show BOTH fast and stalled runs.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL spawn llama-server directly — no wrapper interpreter.
  On Windows it SHALL use `CREATE_NEW_PROCESS_GROUP` (signal isolation) and
  SHALL pass `cwd=<binary dir>` so the Windows loader resolves the CUDA
  runtime DLLs shipped beside the binary, mirroring
  `local_model_manager._build_server_cmd`. It SHALL NOT use
  `DETACHED_PROCESS`, which was measured to make the stall WORSE.
- AC2 (**SUPERSEDED 2026-08-24 — deviation recorded**): the original AC2
  required keeping the launcher as a flagged fallback in case the
  "device-probe hang" persisted. Since that hang does not exist, the fallback
  guarded nothing. The launcher, its stdout-PID protocol and
  `IRIS_VISION_SPAWN_WRAPPER` are REMOVED OUTRIGHT. This is a deliberate
  deviation from the AC as written, and it lands CLOSER to Decisions Locked #3
  ("the launcher-wrapper + netstat PID-adoption dance is replaced by a direct
  spawn") than the hedge it replaces. Do not re-add the wrapper.
- AC3: THE SYSTEM SHALL know the server PID immediately after spawn (no
  post-hoc adoption); `_VISION_SERVER_PID` SHALL be the real server PID.
  (Now trivially true: `proc.pid` IS the server.)
- AC4: Time-to-ready logging (`ttr_sec`) SHALL be preserved unchanged.
- AC5: THE SYSTEM SHALL remove the netstat-based `_resolve_listener_pid` use
  from the spawn path; any remaining use MUST be justified in code comment.
- AC6 (**NEW**): THE SYSTEM SHALL NOT treat silence as death. llama.cpp emits
  NOTHING between `load_model: loading model '<gguf>'` and `loaded multimodal
  model`, and while blocked in a filesystem filter driver its CPU time, io
  counters AND log size are all legitimately flat. Readiness SHALL give a live
  process the benefit of the doubt to the hard deadline.
- AC7 (**NEW**): THE SYSTEM SHALL NOT retry a stalled spawn by default
  (`IRIS_VISION_SPAWN_ATTEMPTS=1`). Retry was measured HARMFUL: 3 attempts x a
  60s window all "wedged" and failed at 296s, while one patient attempt on the
  same machine completed at 75.66s. Killing and respawning discards a
  part-finished AV scan and starts a fresh one.

**Edge Cases:**
- Binary requires LD_LIBRARY_PATH (POSIX upstream build) -> env passthrough
  preserved with platform-correct separator.
- **Host I/O contention (THE dominant real-world failure).** On-access AV and
  other filesystem filter drivers block llama-server INSIDE the kernel while
  it opens the GGUF/mmproj, with no cpu, no io and no log output. Captured
  trace: `read_bytes` flat at 11MB for 73 SECONDS while `MsMpEng.exe` burned
  CPU linearly, then jumped to 826MB and the server was ready at 75.66s. It
  was never hung. Mitigation is OPERATIONAL, not code — see
  "Host prerequisites" in tasks.md. The code's duty is only to stay patient
  and to name the cause in the log (`av_scan_suspected`).
- Pre-reading the model files from the backend process does NOT help: AV
  verdict caches are scoped per accessing process. Measured — a full 2.5GB
  pre-read cost 29.7s and llama-server was still blocked 481s afterwards. Only
  an 8MiB timing PROBE is justified, purely as a diagnostic.

### REQ-4: Search-scoped warmth
**User Story:** As a user I want vision warm when my search needs it, so
escalation never pays a mid-search cold start silently.

**Verified:** Boot prewarm warms at t+25s but `_IDLE_TIMEOUT=120`
(`lfm_vl_provider.py:62`) stops the server ~2min later; a later search pays
full cold start. The Session-248 search-start prewarm was REJECTED for
starving crawl workers (conv-53, `iris_gateway.py:332-338`) — this requirement
re-introduces the intent with sequencing, not concurrency.

**UPDATE 2026-08-24 — the 120s auto-stop is GONE (user-resolved).** Its
premise was "a small model is cheap to restart". Measured false on this class
of machine: the identical spawn took 3.87 / 4.90 / 11.04 / 19.84 / 44.95s and,
twice, past 580s, depending on host I/O contention. So the auto-stop did not
buy a cheap restart — it guaranteed every use re-paid a load of unpredictable
duration, and it routinely tore the server down in the gap between a
`crawler_started` prewarm and the vision call that followed. THAT is the
mechanism behind "vision is randomly unavailable".

Vision now loads on FIRST USE and STAYS WARM for the process lifetime.
`_IDLE_TIMEOUT` defaults to a stay-warm sentinel (~10 years) and
`IRIS_VISION_IDLE_TIMEOUT=<seconds>` re-enables auto-stop for small-VRAM
machines. `should_idle_stop()` keeps its exact "idle past the timeout"
semantics so the lease contract and its tests still test the real predicate.
Implementation notes for whoever touches this: `threading.Timer` raises
`OverflowError: timeout value is too large` well below the sentinel, so
`_idle_timer_interval()` caps the wait and `_idle_stop()` RE-ARMS instead of
returning dead. REQ-4's AC1–AC5 below are unaffected — a re-warm is still
sequenced after pool readiness and still honors the VRAM reserve; there is
simply far less to re-warm.

**Acceptance Criteria:**
- AC1: WHEN `crawler_started` fires AND the owned vision server is not running
  THEN THE SYSTEM SHALL schedule a re-warm that begins only after the crawl
  pool reports live workers (or pool disabled), off the crawl critical path.
- AC2: THE SYSTEM SHALL honor `_VISION_VRAM_RESERVE_GB` on every warm path.
- AC3: WHEN a re-warm is in flight AND a real vision request arrives THEN the
  request SHALL join REQ-1's single-flight spawn rather than starting its own.
- AC4: THE SYSTEM SHALL emit the lifecycle event naming the trigger
  (boot | search-scoped | lazy-call) for observability.
- AC5: THE SYSTEM SHALL bound re-warms to at most one in-flight per search run.

**Edge Cases:**
- VRAM insufficient at re-warm time -> REQ-5 error state surfaced; the search
  proceeds crawl-only (existing degraded mode).
- Pool disabled (`IRIS_CRAWL_POOL=0`) -> re-warm starts after the fallback
  worker warm-up completes.

### REQ-5: Vision lifecycle status broadcast + chip
**User Story:** As a user I want to SEE vision warming/warm/error, so 30s of
spawn reads as progress, not a freeze.

**Verified:** A `vision_status` WS channel and idle-stop broadcast exist
(`iris_gateway.py:9997-10043`, `useIRISWebSocket.ts:1072-1104`) but nothing
broadcasts spawning/warm/error transitions from the provider.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL broadcast a vision lifecycle state — `cold`, `spawning`,
  `warm`, `error` (+reason) — on every transition of the owned server.
- AC2: THE SYSTEM SHALL route the state through the existing `vision_status`
  message shape (additive field), not invent a transport.
- AC3: THE BROWSER PANEL SHALL render a compact chip (dot + label) showing the
  current state while a crawl is active; `error` carries the reason on hover.
- AC4: EMISSION SHALL be best-effort and off the inference path — a broken
  broadcast never fails a vision call.

**Edge Cases:**
- User-run server (not owned) -> state reported as `warm` (external) without
  lifecycle claims.

### REQ-6: Ambient visual tier
**User Story:** As a user I want the agent's browsing to be visible even when
the dashboard wing is closed or backgrounded, so the interactive experience is
not gated on panel state.

**Verified:** REAL GAP. All overlay rendering lives inside
`activeSubApp === 'browser'` (`dark-glass-dashboard.tsx:1841-1863`), which sits
inside DashboardWing; when the wing is closed, or chat-spotlighted (opacity
0.3 + blur + pointer-events none, `dashboard-wing.tsx:167-190`), every
animation plays invisibly. The sub-app auto-open at `crawler_started`
(`dark-glass-dashboard.tsx:1063-1068`) only helps when the WING itself is open.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide an ambient surface — driven by the SAME
  `iris:crawler_*` / `iris:crawler_vision_action` events — that renders the
  crawl/vision state (phase ring or equivalent, page counter, current action)
  outside the browser panel, visible whenever ANY part of the app is visible.
- AC2: WHEN the browser panel IS open and unobscured THEN the ambient tier
  SHALL yield (stay minimal) so the full shutter remains the primary surface.
- AC3: THE AMBIENT TIER SHALL respect prefers-reduced-motion (static state
  text instead of animation).
- AC4: THE AMBIENT TIER SHALL consume CrawlProvider state (single source of
  truth), not register duplicate window listeners.

**Edge Cases:**
- Remote/mobile view (`isRemoteView`) -> ambient tier renders flat, no tilt.
- Both wings open balanced -> ambient tier attaches to the orb shell region,
  never overlapping chat text.

### REQ-7: Overlay state backfill on mid-run mount
**User Story:** As a user opening the browser panel mid-search I want the
overlay to show the CURRENT state immediately, not idle until the next event.

**Verified:** REAL GAP. `useBrowserNavOverlay` starts at IDLE and only moves on
new CustomEvents; a panel opened after `crawler_started` misses the run's
history even though CrawlProvider retains it (`useCrawl.ts` accumulates pages,
visionActions, phase).

**Acceptance Criteria:**
- AC1: WHEN the overlay hook initializes OR the panel mounts mid-run THEN THE
  SYSTEM SHALL derive initial overlay state from CrawlProvider state (active ->
  loading/crawling, pagesDone/pagesTotal, last vision action) without waiting
  for a new event.
- AC2: THE SYSTEM SHALL NOT double-count replayed snapshot events (idempotent
  with the SSE/snapshot re-dispatch path).

**Edge Cases:**
- Provider state empty (stale session restored) -> overlay stays idle.

### REQ-8: The shutter is the VLM's eye — blink, scan, notice
**User Story:** As a user I want the border animation to read as the vision
model's eye looking at the page through the iframe: it BLINKS when the model
attends, SCANs with a hexagonal cell wave while the model reads/interacts, and
has a distinct "notice" moment on escalation.

**Verified:** REAL GAP + DESIGN INTENT (user-resolved 2026-08-23). The shutter
impulse fires only on `pagesDone` changes
(`BrowserNavigationOverlay.tsx:337-360`); vision actions move the cursor but
never kick the aperture. Escalation is visually indistinguishable from normal
crawling. No scan grammar exists.

DESIGN INTENT (binding): the border IS the VLM's eye.
  - BLINK   = one attention event (page fetched OR vision action taken).
  - SCAN    = the model actively reading — a hexagonal cell lattice in the
              border band with a traveling activation front, evoking a sensor
              sampling the page. Runs WHILE vision interaction is in flight,
              synced to action cadence and biased toward the cursor's side.
  - NOTICE  = escalation — the eye dilates (aperture holds open) and the scan
              brightens before returning to cadence.

**Acceptance Criteria:**
- AC1: WHEN a `crawler_vision_action` arrives THEN THE SYSTEM SHALL fire the
  same blink impulse a fetched page fires (one aperture close + speed kick).
- AC2: WHILE a vision session is interacting (scroll/click/type actions
  arriving) THEN THE OVERLAY SHALL render a hexagonal-lattice scan in the
  border wash band: hex cells ignite in a traveling front whose speed follows
  the live action/page cadence (reuses lapMs gearing) and whose intensity is
  biased toward the current cursor position's side of the card.
- AC3: WHEN a vision ESCALATION begins (first vision action of a URL that was
  escalated, distinguishable via payload/orchestrator context) THEN THE
  OVERLAY SHALL play a one-shot "notice" beat: aperture locks open (no blink),
  scan front brightens and doubles speed, color shifts, then cadence resumes.
- AC4: THE SCAN LATTICE SHALL be drawn on the EXISTING border canvas in the
  SAME rAF loop (no second canvas, no second rAF, no per-cell DOM nodes);
  cell geometry precomputed on measure(); per-frame cost bounded by the cell
  count of the edge band only.
- AC5: THE NOTICE BEAT SHALL be bounded (< 2s), reduced-motion aware (color
  shift only, no traveling front), and SHALL NOT change layout or block
  content.
- AC6: UNDER prefers-reduced-motion THE SCAN SHALL degrade to a static lit
  border band (no traveling wave); blinks become opacity steps.

**Edge Cases:**
- Multiple escalations in one run -> notice plays per escalation, throttled
  to at most once per 5s.
- Vision actions stop arriving (session ended, crawl continues) -> scan fades
  back to plain shutter cadence within one lap.
- Narrow panel (< 320px) -> hex cell size scales down; lattice stays legible,
  never clips into content beyond the existing wash depth.

### REQ-9: Aspect-correct vision cursor
**User Story:** As a user I want the cursor to sit where the model actually
acted, regardless of viewport aspect differences.

**Verified:** REAL GAP. Coordinates arrive as 0..1 fractions plus
`viewport_w`/`viewport_h` (`ux_map.py:47-61`), but the consumer uses raw
fractions against the iframe box (`useBrowserNavOverlay.ts:158-186`) — a
headless viewport wider than the frame stretches x placements.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL map the action point through the source viewport
  aspect (`viewport_w/h`) into the frame box so relative positions are
  preserved (letterbox-aware mapping), not naively stretched.
- AC2: WHEN `viewport_w/h` are absent THEN THE SYSTEM SHALL fall back to the
  current naive mapping (never drop the point).

### REQ-10: Reading surface fit-to-width
**User Story:** As a user I want the whole page WIDTH visible in the browser
panel, so I can actually read what the agent reads.

**Verified:** REAL GAP. `/api/browser/capture/{job}/{page}` serves raw captured
HTML (`capture_store.py:17-19`) rendered at natural width inside a ~430–660px
frame; no scaling exists anywhere in the chain.

**Acceptance Criteria:**
- AC1: THE CAPTURE RENDER PATH SHALL scale captured content to the frame's
  client width (fit-to-width), preserving layout proportions; height overflows
  vertically and scrolls.
- AC2: THE SCALING SHALL apply to BOTH capture replays and proxied live pages.
- AC3: THE MECHANISM SHALL survive the opaque-origin sandbox AND the served
  CSP: injected scaling code SHALL carry the per-response nonce through the
  EXISTING injection mechanism (`backend/proxy/view_agent.py` pattern, wired
  at BOTH serve sites — capture `browser_surface.py:169`, proxy `:307`). A
  bare inline script is CSP-blocked (`script-src 'nonce-…'`,
  `browser_surface.py:82`) and silently dead — this exact failure killed the
  view-agent once before (see the CSP comment block :45-73). Scaling is
  performed by the served response itself, never by the parent reaching into
  the frame.
- AC4: THE VIEW-AGENT scroll mirroring (`sendScrollTo`) SHALL remain functional
  under scaling (offsets translated by the scale factor).
- AC5: A USER-INITIATED zoom control (fit-width / 100%) MAY be provided; when
  absent, fit-width is the default.

**Edge Cases:**
- Pages with fixed-width layouts narrower than the frame -> centered, not
  stretched.
- Capture lacking the injected scaler (old captures) -> rendered unscaled
  (current behavior), never broken.

### REQ-11: Reclaim dead space around the iframe
**User Story:** As a user I want the browser viewport to use the available
panel area, so content is as large as the hardware allows.

**Verified:** REAL GAP. The browser branch wraps the card in
`p-4 md:px-10` (`dark-glass-dashboard.tsx:1834`) inside a wing capped at
360–680px (`dashboard-wing.tsx:125-130`); measured margins around the card are
disproportionate at every spotlight width.

**Acceptance Criteria:**
- AC1: THE BROWSER SUB-APP SHALL reduce its outer padding to the minimum that
  preserves the card's rounded-border aesthetic (target: <= 8px at all
  spotlight widths), reclaiming width for the viewport.
- AC2: THE PANEL CHROME (tab strip + address bar) heights SHALL be audited and
  tightened where possible without losing touch targets (>= 32px interactive
  height).
- AC3: THE OVERLAY GEOMETRY SHALL remain correct after any resize (it measures
  via ResizeObserver — verify, do not assume).
- AC4: NO OTHER SUB-APP'S LAYOUT SHALL CHANGE as a side effect.

### REQ-12: Vision Stage Simulator (sign-off harness)
**User Story:** As the user I want to trigger every animation and effect on
demand from scripted agent-action scenarios, so I can visually sign off each
one during implementation without running real searches.

**Verified:** NEW. This is the acceptance instrument for REQ-6..REQ-11's
visual work and for existing effects that were never demonstrable on demand.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide a simulator surface (dev-only route or hidden
  dev-panel entry) listing scripted scenarios covering AT MINIMUM:
    a. crawl loading -> dispersing -> crawling -> complete
    b. crawl error terminal
    c. vision cursor click (with coordinates)
    d. vision cursor type
    e. vision scroll (iframe mirror + cursor hold)
    f. escalation notice beat (REQ-8 AC3)
    g. rapid multi-page cadence (shutter re-timing)
    h. vision lifecycle chip transitions cold->spawning->warm->error (REQ-5)
    i. ambient tier states with the browser panel CLOSED (REQ-6)
    j. mid-run mount backfill (REQ-7)
    k. fit-to-width rendering of a wide captured fixture (REQ-10)
    l. hex-scan during sustained scroll interaction (REQ-8 AC2) — front
       follows action cadence and biases toward cursor side
    m. single Live Reading surface (REQ-15/T12b) — 5-page scripted run stays
       in ONE tab, surface follows the latest page, clicking a source pins it,
       the LIVE pill resumes. ADDED 2026-08-24: REQ-15 landed after this AC
       was written, so (m) existed in the sign-off checklist but not here.
       The checklist (a–m) is authoritative on the scenario set.
- AC2: EACH SCENARIO SHALL inject the real `iris:*` CustomEvents (and CrawlProvider
  state where REQ-7 requires) with realistic payloads and timing — the SAME
  contract production emits — so the simulator exercises the real pipeline
  front-end, never a parallel mock renderer.
- AC3: EACH SCENARIO SHALL be repeatable (reset-to-idle between runs) and
  runnable in both motion and reduced-motion modes.
- AC4: THE SIMULATOR SHALL include a written sign-off checklist (scenario ->
  expected visual beats) that the user ticks during implementation review.
- AC5: THE SIMULATOR SHALL require zero backend/VLM/GPU involvement.

**Edge Cases:**
- Simulator events leaking into a LIVE crawl in progress -> scenarios are
  blocked (with notice) while `crawlState.active` is true.

### REQ-13: Pipeline step reduction (behavior-preserving)
**User Story:** As a maintainer I want fewer moving parts in the
search->vision chain, so there is less to race, time out, or break.

**Verified:** Redundancies identified in audit:
  - Two independent Playwright stacks: crawl worker subprocesses
    (`crawl_runner.py` pool) AND vision `BrowserSession` each pay Chromium
    cold starts separately.
  - Per-call health probe inside every `_call()` (`lfm_vl_provider.py:1068`)
    even when a lease is held and the server was just verified.
  - Launcher+netstat indirection (REQ-3 removes it).
  - nvidia-smi subprocess invoked independently by selection AND gpu-layer
    decision within one spawn (two probes where one suffices).

**Acceptance Criteria:**
- AC1: WITHIN ONE SPAWN DECISION, THE SYSTEM SHALL read free VRAM ONCE and
  share the figure across candidate selection and GPU-layer computation.
- AC2: WHILE a vision lease is active, `_call` SHALL skip the per-call health
  probe (the lease guarantees liveness supervision instead — see AC4).
- AC3: THE SYSTEM SHALL evaluate sharing ONE Chromium instance between the
  crawl pool and vision sessions behind a flag; IF implemented THEN crash
  isolation semantics MUST be preserved or explicitly re-justified (a vision
  crash must not take down crawl workers). This evaluation SHALL be recorded
  (implemented or rejected with reason) before this spec closes.
- AC4: ANY liveness optimization SHALL NOT reintroduce silent death: if the
  server dies mid-lease, the next call detects it and triggers REQ-1's
  single-flight respawn.
- AC5: EVERY REMOVED STEP SHALL have its function preserved by an existing
  test that still passes unchanged (tests are the functionality contract).

**Edge Cases:**
- Flag-off environments (IRIS_CRAWL_POOL=0) keep today's isolated stacks.

### REQ-14: Non-interference contract (overlay & agent)
**User Story:** As the user I want certainty that visuals never interfere with
agent actions or user input.

**Verified:** TRUE TODAY, UNPINNED. Overlay root is `pointer-events-none`
(`BrowserNavigationOverlay.tsx:666`, canvas `:673`); the agent drives a
headless Playwright session server-side while the iframe is a downstream
mirror. Nothing pins either fact.

**Acceptance Criteria:**
- AC1: A CONTRACT TEST SHALL assert the overlay root and ALL its rendered
  children carry pointer-events: none (grep/DOM-shaped guard).
- AC2: A CONTRACT TEST SHALL assert no frontend component sends input events
  into the vision session's Playwright page (the session has no inbound
  control channel from the UI — grep-shaped guard over `browser_session.py`).
- AC3: THE SCROLL MIRROR (`sendScrollTo`) SHALL affect ONLY the local iframe
  view and SHALL send nothing toward the backend vision session.

### REQ-15: Single Live Reading surface (no tab-per-page)
**User Story:** As a user I want the panel to follow the agent's reading in
ONE place, so the tab strip is not flooded with a tab per crawled page.

**Verified:** REAL GAP (user-resolved 2026-08-23: "never understood the
opening of a new tab on every new page crawl"). The tab-creation effect
(`dark-glass-dashboard.tsx:697-727`) opens one web tab per fetched page AND
`openTab` auto-activates it — so the viewport already jumps page-to-page while
the strip accumulates history. The PlanCard already renders every source with
status via `useCrawl.sources`, duplicating the same list. The end-of-run
summary tab (`open_tab`, dashboard type) is a separate, legitimate artifact.

**Acceptance Criteria:**
- AC1: WHEN pages are fetched during a run THEN THE SYSTEM SHALL navigate ONE
  stable "Live Reading" web tab to each new capture address (iframe src swap),
  creating NO per-page tabs.
- AC2: THE LIVE READING TAB SHALL carry the SAME provenance behavior as
  today: the capture badge (job id + fetch time) reflects the page currently
  displayed; a page whose bytes were not stored routes through the proxy,
  never at a 404 replay address.
- AC3: EVERY fetched source SHALL remain browsable after and during the run
  from the existing source list (PlanCard sources): selecting a source points
  the reading surface at that source's capture address.
- AC4: THE END-OF-RUN SUMMARY TAB SHALL be unchanged (separate dashboard tab).
- AC5: OUT-OF-ORDER page arrival (concurrent dispatch) SHALL NOT cause visual
  thrash: the surface follows the LATEST page event without flickering through
  intermediate arrivals arriving within a short window (coalesce ≤300ms).
- AC6: USER-OPENED TABS (typed URLs, code/html/dashboard tabs) SHALL behave
  exactly as today; this requirement changes only crawl-derived tab creation.

**Edge Cases:**
- A source selected from the list mid-crawl, then new pages land -> the
  surface returns to following the live feed (following mode), unless the
  user pinned their selection (manual selection pauses following until the
  next run or an explicit resume).
- Session restore / snapshot replay -> the reading surface ends on the last
  captured page; no duplicate navigation churn during replay.

## Non-Requirements (Out of Scope)
- Changing vision routing hierarchy (unified-vision-routing spec owns it).
- Changing the VISION_UNAVAILABLE fail-loudly contract.
- Making the agent's actions controllable from the panel (read-only mirror).
- Rewriting the dual WS/SSE transport (contract-motivated duplication).
- New VLM models or quality changes.
- Mobile-specific layouts beyond what isRemoteView already handles.

## Open Questions
- REQ-13 AC3: shared-Chromium flag — implement now or record rejection?
  Default posture: evaluate first, implement only if crash isolation can be
  preserved cheaply.
- REQ-10 AC5: zoom control in v1 or defer? Suggested: defer unless trivial.

# Vision Browser Stage — Architecture

> **Status: as-built, 2026-08-25. Spec COMPLETE — every task closed.** This is the durable reference for the
> feature. requirements.md says what was asked for and design.md says how it was
> planned; THIS says what actually exists, why, and what will break if you
> change it.
>
> It is also the **preservation record for the Vision Stage Simulator**, which
> was removed after sign-off. Section 7 carries its event contract and scenario
> definitions so the sign-off harness can be rebuilt from this document alone.

---

## 1. The shape of the thing

Three layers joined by ONE event contract. The contract is the load-bearing
part: every visual hangs off `iris:*` CustomEvents that the backend already
emits, which is why a simulator could drive the real UI with no mock renderer.

```
BACKEND LIFECYCLE                 EVENT CONTRACT                FRONTEND STAGE
─────────────────                 ──────────────                ──────────────
LFMVLProvider                ──►  vision_status (WS)       ──►  VisionLifecycleChip
  single-flight spawn                                      ──►  BrowserNavigationOverlay
  ownership-safe cleanup                                        · border band (REQ-8)
  direct spawn (REQ-3)                                          · mesh film (REQ-17)
  stay-warm lifecycle                                      ──►  AmbientCrawlTier
orchestrator / fetch.vision  ──►  crawler_* events         ──►  CrawlProvider
browser_pool + BrowserSession ─►  /api/browser/capture|proxy ─► panel iframe
```

**Direction of control is one-way.** The agent drives a headless Playwright
session server-side; the panel iframe is a downstream MIRROR. Nothing in the UI
can send input into the vision session — there is no inbound channel, and
contract tests (CT-6/CT-7, REQ-14) grep-guard both that fact and the overlay's
`pointer-events: none`.

---

## 2. Backend: the VLM lifecycle

`backend/tools/lfm_vl_provider.py`.

**Single-flight spawn.** `_spawn_lock` (threading, not asyncio — callers arrive
from both `asyncio.to_thread` workers and sync paths) serializes attempt
CREATION. Concurrent callers attach as waiters to one `_SpawnAttempt` and share
its result. The attempt owns cleanup; waiters never clean up.

**Ownership-safe cleanup.** Failure kills only the PID this attempt spawned,
verified by lineage. The old netstat port-scan kill is gone — it could kill a
listener IRIS did not start.

**Direct spawn.** `argv[0]` IS the llama-server binary. There is no launcher
interpreter, and `IRIS_VISION_SPAWN_WRAPPER` is DELETED, not flag-disabled.

> **The wrapper theory is falsified. Do not resurrect it.** The story was that a
> torch-CUDA parent made llama.cpp's device probe hang. It does not. The
> launcher produced 0KB stderr logs and zero successful loads; direct mode loads
> and listens in ~3s. `DETACHED_PROCESS` specifically made the stall WORSE.

> **Host I/O contention is real but was NOT the cause of "vision unavailable."**
> On-access AV scanning of the 854MB mmproj genuinely does block llama-server in
> the kernel with flat CPU, flat IO and no log output, and the exclusions in
> "Host prerequisites" (tasks.md) genuinely speed up a cold load. But that story
> absorbed the blame for a code bug for two sessions — see the probe finding
> below. Confirm the prerequisites FIRST precisely so you can rule them out.

> **THE READINESS PROBE HAD NEVER RUN (found 2026-08-25, T16.1).** httpx is
> imported inside `_ensure_vision_server_running`, which binds it as a LOCAL to
> that function. The readiness poll lives in `_spawn_vision_server_now`, where
> it was never in scope and there is no module-level import — so every poll
> raised `NameError` and `except Exception: pass` swallowed it. A server
> listening in ~3s was reported `not_ready` 300s later and killed under REQ-2
> cleanup. `ttr_sec` 305.61/FAIL -> 4.01/PASS.
>
> Two lessons worth more than the fix. (1) A bare `except Exception: pass`
> around a network probe will hide a programming error indefinitely, and the
> symptom it produces — flat log, flat CPU, live process — is IDENTICAL to the
> AV-contention failure this codebase already knew about, so it misdirected the
> investigation twice. `NameError`/`AttributeError`/`TypeError` now re-raise
> ahead of the catch-all. (2) Confirming the host prerequisites is what SOLVED
> this, by eliminating the explanation everyone reached for first.

**Lifecycle is announced at the point of COMMITMENT, not at the Popen.**
Everything between the decision and the spawn is real work — nvidia-smi, the
candidate ladder, GGUF metadata reads, the AV probe — measured at 12.96s from
cold. Emitting `spawning` at the Popen left the chip on `cold` for that whole
span, which is the dead air REQ-5 exists to narrate. The fast-path health
check also aligned 2.0s -> 1.0s to match the readiness poll (same request,
same server); it matters because a closed port on this host silently DROPS
rather than refuses, so it cost its full budget on every cold start.

**Readiness is patient by design.** A live process is never killed for silence:
llama.cpp emits nothing for the whole model+mmproj load. `_proc_cpu_seconds()`
is an additional progress signal, never a liveness veto.

**The probe must target `127.0.0.1` explicitly.** `localhost` resolves `::1`
first on this host and llama-server binds IPv4 only. That probe bug — not any
load hang — is what reported healthy servers as dead and killed them. It went
untested until 2026-08-24; `test_vlm_spawn_baseline.py` now asserts it.

**Warmth is search-scoped.** `crawler_started` triggers a staggered re-warm when
the owned server is cold, sequenced AFTER the crawl pool is live and honoring
the VRAM reserve. (conv-53: an earlier search-start prewarm starved pool
workers and was rejected.)

---

## 3. Backend: the browser surface

### 3.1 Two Chromium stacks, deliberately

| | vision | crawl |
|---|---|---|
| where | `backend/vision/browser_pool.py` | `backend/crawler/crawl_runner.py` |
| shape | ONE Chromium in the backend process, per-session `new_context()` | resident `--serve` worker SUBPROCESSES (`_WarmCrawlPool`) |
| why | escalation cost 4 cold launches per 4-URL job; now 1 | a Chromium C-level crash cannot be caught by try/except — it would kill the backend |
| warm cost | `new_context()` 0.033s | INIT paid once per pool lifetime at boot |

**They are NOT shared, and that was measured, not assumed (REQ-13 AC3 / T17).**
The gate condition was "isolation preserved via separate CONTEXTS". That premise
is false: contexts are cookie/storage domains, **not crash domains**. Killing the
browser process killed BOTH contexts (`TargetClosedError` each) and disconnected
the browser. Sharing would also trade a 0.145s warm launch for a 1.701s CDP
attach — ~11x slower at steady state — and both sides already avoid per-use
launches, so there was no cold-start saving left to capture.

> Method trap that cost one wrong result: matching `--remote-debugging-port`
> anywhere in a cmdline ALSO matches Chromium's renderer/GPU/utility children,
> which inherit the flag. Killing one of those is survivable by design and
> reports a bogus "SURVIVED". **The browser process is the match carrying no
> `--type=` switch.**

### 3.2 The serving boundary

`backend/api/browser_surface.py`, prefix `/api/browser`:
`GET /capture/{job_id}/{page_number}`, `GET /proxy?url=`, `POST /session`.

**Two gates, both 404 on refusal** (`browser_auth.py:130`): a loopback/tailnet
ADDRESS check, then a surface TOKEN (cookie or header — an iframe cannot set
headers, so the cookie is the real path). 404 rather than 403 so a wrong-network
caller learns nothing about what exists.

> Any test calling these endpoints MUST present a loopback peer AND a valid
> token. 17 tests silently measured the auth refusal instead of their subject
> for as long as the gate existed — including the SSRF/egress guard cases.

### 3.3 Three CSP directives that are load-bearing in the OPPOSITE direction

Every one of these shipped as a bug, was fixed, and is now pinned by
`backend/tests/contract/test_browser_surface_headers.py`. Older tests asserting
the buggy values were themselves corrected.

| directive | the bug | why |
|---|---|---|
| `frame-ancestors 'none'` | makes every served page UNFRAMEABLE | it is `X-Frame-Options: DENY` by another name — the exact failure this feature exists to fix. (`frame-src` restricts what a page may embed; `frame-ancestors` restricts who may embed IT.) |
| `base-uri 'none'` | breaks REQ-2 AC3 | the browser ignores the injected `<base href>`, so relative refs resolve against the APP origin |
| `script-src 'none'` | breaks REQ-4 | the injected view-agent never runs, so no scroll/ready message reaches the parent |

**And `Access-Control-Allow-Origin: null` is not a restriction — it is the
vulnerability.** `"null"` IS the opaque origin a sandboxed document presents, so
sending it grants read access to precisely the reader the sandbox excludes. The
correct value is **no `access-control-*` header at all**.

### 3.4 BrowserSession

`backend/vision/browser_session.py`. Leases a pooled browser, takes its OWN
`new_context()` (run-scoped cookie isolation), and enforces action-count and
wall-clock bounds — raising `SessionBudgetExceeded` BEFORE executing.

**Scroll is ONE CDP round trip, not two.** `window.scrollBy` with default
(instant) behavior applies synchronously, so the REQ-16 AC7 mirror read of
`{y, h}` happens in the SAME script. A vision session is scroll-dominated, so
this halves traffic on its hottest action. The mirror read sits in a JS
try/catch; the evaluate itself is deliberately NOT wrapped in a Python
try/except, because it now performs the scroll and a failure must surface as
`last_error` (REQ-7 AC6) rather than be swallowed as a missing mirror reading.

---

## 4. The event contract (FROZEN)

`hooks/useIRISWebSocket.ts` translates WS messages into `iris:*` CustomEvents.
Consumers: `hooks/useBrowserNavOverlay.ts` (the overlay) and `hooks/useCrawl.ts`
(crawl state).

**Eleven `crawler_*` events are emitted:**

| event | consumed by |
|---|---|
| `crawler_started` | overlay, useCrawl |
| `crawler_page_fetched` | overlay, useCrawl |
| `crawler_complete` | overlay, useCrawl |
| `crawler_error` | overlay, useCrawl |
| `crawler_vision_action` | overlay, useCrawl |
| `crawler_progress` | useCrawl |
| `crawler_phase` | useCrawl |
| `crawler_source_parked` | useCrawl |
| `crawler_sources_added` | useCrawl |
| `crawler_sync_required` | useCrawl |
| `vision_status` | VisionLifecycleChip |

> **KNOWN PARITY GAP.** The simulator only ever drove the first five plus
> `vision_status`. The last five were **never simulated**, so any behavior they
> drive was signed off blind. If the harness is rebuilt, add a contract test
> asserting BOTH directions: every scenario event name is one production emits,
> AND every production `crawler_*` name is covered by at least one scenario. The
> second half is what would have caught this.

---

## 5. Frontend: the overlay

`components/iris/browser/BrowserNavigationOverlay.tsx`. Root is
`absolute inset-0 pointer-events-none z-30`; the canvas paints the whole panel.

**States:** `idle → loading → dispersing → crawling → complete | error`, with
intensity `0 / 0.34 / 0.72 / 1 / 0.85`.

### 5.1 Border band (REQ-8)

Two rows of hexes on the rounded perimeter path. Circumradius is DERIVED from
perimeter spacing (`R = ds/√3`, so flat-to-flat width equals `ds` and columns
touch exactly); row 2 nests `1.5·R` inward with a `ds/2` arc offset.

Cells rest DARK. Each shutter impulse (a page landing) fires a pulse whose
wavefront sweeps OUTWARD over the same ~620ms the shutter takes to decay. During
sustained scroll with no page landings a gentler pulse fires every ~900ms.
Geometry rebuilt only on resize.

Design decisions that were reached by elimination — **do not revisit**:
single-ring aperture (multi-gradient/stroke/triangle builds were all rejected);
hexes must NOT orbit the border like the comet streams; the escalation NOTICE is
a black↔white treatment (white ring, scattered black hex spots re-rolled every
350ms, darkness border pulse, `NOTICE_DURATION_MS = 2600`), which replaced an
earlier violet shift during sign-off.

### 5.2 Mesh film (REQ-17)

The surface counterpart to the band, and **standard behavior** as of sign-off.
Drawn BEFORE the band so the band keeps its weight on top.

**It draws WALLS, not cells.** The lattice is decomposed into unique undirected
edges, keyed on quantised endpoints so the two cells meeting at a wall agree on
its identity; 35-42% of emitted walls collapse. Each wall traces itself in via
`setLineDash`/`lineDashOffset`. That dedup IS the mechanism — a wall is one
object two cells share, which is what lets growth cross between them. Stroking
whole hexes can only ever read as cells blinking.

> **`meshR` must EQUAL the lattice pitch radius exactly.** At `0.94·R` the
> vertices of neighbouring cells never coincide, 0% of walls are shared, and
> growth cannot propagate. The pitch is derived from `meshR`, never from the
> band's `hexR`.

**Arrival** = `depth + contourNoise + patchJitter + ringSpread`, a wall's
position on the 0..1 scale a wave sweeps.

> **`contourNoise` is REQUIRED.** `depth` is distance to the NEAREST EDGE, whose
> iso-contours ARE concentric rectangles — so any front sweeping it collapses as
> a **square funnel**. The warp multiplies two different-frequency trig terms on
> x and y; a `sin(x)+sin(y)` leaves visible axis grain, the same failure in
> another costume. Measured front depth-spread: 0.008-0.018 without, 0.043-0.046
> with.

**Waves.** One launched per kick-pulse shutter; several coexist so they follow
each other inward and fill the surface. Every third runs centre-outward — a
purely inward cadence trains the eye to expect the collapse and makes it more
legible each repetition, while an outward wave sweeps the contours in the
opposite order so the two never superimpose. Behind each front a wall traces in,
holds, then fades; that fade is the trail. Deep walls are softened so the centre
reads as growth petering out.

**Two relationships that are arithmetic, not taste:**

1. `DRAW+HOLD+FADE` vs launch spacing. Narrower → dark gaps and distinct
   marching rings. Wider → continuous comb. Measured: a band twice the spacing
   saturated to 100% lit within 4s and the wave read vanished. Wave count is
   controlled by throttling the LAUNCH RATE — **never** by evicting a live wave,
   which blanks every wall it still lit.
2. `MESH_WAVE_LIFE` must cover the deepest arrival INCLUDING noise/jitter/
   spread. It is derived from those constants, not hand-set, so it cannot drift
   out of step when they are tuned.

**Activity gate:** loading / dispersing / crawling, or any vision action. A
crawl emits `crawler_page_fetched`, NOT `crawler_vision_action` — gating on
vision actions alone silently disables the film during the exact case it exists
for. Renders nothing under `prefers-reduced-motion`.

**Cost:** geometry, adjacency and growth order resolved once per resize; the
draw loop is a pure read with no allocation. Completed walls batch into one path
per alpha bucket; only walls mid-trace pay per-edge state changes — ~160-200
strokes/frame instead of ~1200 state changes.

**Enable switch** is a localStorage PREFERENCE (`MESH_PREF_KEY`) read
identically by the app and the simulator, **never a simulator-only event**, so
no dev-only render path can exist. Default ON; only an explicit `"0"` disables.

---

## 6. Testing posture

Layered, never unit-only, because the bugs live in the SEAMS:

- `tests/contract/`, `backend/tests/contract/` — boundary pins (event shape,
  headers, auth, non-interference).
- `tests/behavioral/`, `backend/tests/behavioral/` — full loop.
- `backend/tests/unit/` — pure logic.

**Running the backend suite:** a single hanging test aborts the WHOLE pytest
session via the pytest-timeout dump, yielding zero summary — which looks like a
silent death. Run per directory with `-v` so the hanging nodeid is written live,
`--deselect` it, re-run, repeat. Run suites SEQUENTIALLY; a concurrent jest run
makes pytest look pathologically slow.

**Standing red (2026-08-24):** ~4480 passed, with residual failures in voice,
telegram, parakeet, porcupine, `iris_core` DLL and lmstudio — all
environment-dependent, verified pre-existing against a clean `HEAD` worktree,
and owned by other domains. Use a worktree, not `git stash`: the dev server and
backend run against the working tree.

---

## 7. PRESERVED: the Vision Stage Simulator (removed, restored, removed)

Dev-only surface at `/?mode=developer&dev=vision-stage`, gated on
`useLauncherMode().isDeveloper`, blocked while a real crawl was active. It
dispatched **real** `iris:*` CustomEvents through the production listeners —
there was no mock renderer anywhere, which is precisely why sign-off on it meant
something.

It was cut after the a-m sign-off, restored for Wave 6 (the swallow and
release are sub-second animations that cannot be judged on a live run), and
cut again once Wave 6 closed. The files are in git history now; the MOUNT in
`app/page.tsx` has never been tracked and must be rebuilt from the runner
contract below.

Files removed: `app/dev/vision-stage/page.tsx`,
`components/iris/simulator/VisionStagePanel.tsx`, `simulator/scenarios.ts`,
`simulator/runner.ts`, `__tests__/BT-1.simulator-traces.test.ts`, plus the
slide-over mount in `app/page.tsx`.

**Runner contract** (all that is needed to rebuild it):

```ts
// A scenario is an ordered list of timed CustomEvent dispatches.
type Step = { ev: string; detail: Record<string, unknown>; atMs: number }
// runScenario walks the steps on a timer and dispatches:
window.dispatchEvent(new CustomEvent(step.ev, { detail: { ...step.detail } }))
// resetToIdle() dispatches iris:crawler_complete to return the stage to rest.
```

**Sign-off checklist — all 13 approved by the user 2026-08-24**, persisted under
localStorage key `iris-vision-stage-signoff-v1`:

| id | scenario | expected beats |
|---|---|---|
| a | crawl full lifecycle | dim stream → bloom outward → shutter cadence with per-page kicks → settle ring fade |
| b | crawl error terminal | border settles AMBER and fades, auto-dismisses to idle |
| c | vision cursor CLICK | orb travels to point (~620ms ease), tightens into cursor, trail decays |
| d | vision cursor TYPE | same travel grammar at the type point; cursor holds between keystrokes |
| e | vision SCROLL | real page loads via proxy; content scrolls smoothly per event; cursor holds position |
| f | escalation NOTICE | **black↔white** treatment, aperture HOLDS open, streams suppressed, 2600ms |
| g | rapid multi-page | ring lap speed re-times from median page gap; particles never jump |
| h | lifecycle chip | cold → spawning (amber pulse) → warm (emerald) → error (red + reason) |
| i | ambient tier | wing CLOSED: ring+counter near orb; wing open: dot only |
| j | mid-run mount | overlay opens already crawling at the correct page count |
| k | fit-to-width | wide fixture fully visible in width; scroll mirror still works |
| l | hex-scan | during sustained scroll: cells ignite in a travelling front, biased to cursor side |
| m | live reading | 5-page scripted run: ONE tab, surface follows latest page; click a source → pins; LIVE pill resumes |

> Scenario (f)'s row preserves the ORIGINAL expected-beats text for the record;
> the grammar was REDESIGNED during sign-off (violet shift → black↔white) and
> the as-signed behavior supersedes it.

**Fixture rules that mattered:**
- Scenarios a/e/g/j/m used **REAL URLs** with `capture_available: false`, so
  live-reading took the proxy path. Synthetic URLs 404 as missing captures.
- Scenario k needed a wide-page HTML fixture rendered inline.
- Scenario i had to be run twice — once with the dashboard wing closed, once
  open on Browser — and stays ACTIVE by design until RESET.
- `scroll_height` fixture value is **8000** (raised from 4000; called out per
  the test rule).
- BT-1 asserted trace sequences for scenarios a/b/c/e/f.

---

## 8. If you change one thing, check this

| change | what breaks |
|---|---|
| mesh cell radius ≠ lattice pitch radius | wall sharing → 0%; growth stops propagating |
| remove `contourNoise` | the square funnel returns |
| widen mesh band past launch spacing without throttling launches | saturates to 100% lit; wave read gone |
| tune noise/jitter/spread without `MESH_WAVE_LIFE` | waves retire mid-fade and blank their walls |
| gate the film on vision actions only | film dies during crawls |
| add a second `page.evaluate` in `BrowserSession.act` | doubles CDP traffic; trips the evaluate-count guard |
| set `frame-ancestors`/`script-src`/`base-uri` to `'none'` | unframeable pages / dead view-agent / broken relative refs |
| send `Access-Control-Allow-Origin: null` | grants read access to the sandboxed reader |
| call a `/api/browser` endpoint without loopback peer + token | 404 before the handler; tests measure the refusal |
| share one Chromium between crawl and vision | one crash destroys both; ~11x slower at steady state |
| swallow NameError/AttributeError in the readiness poll | the probe silently stops running; healthy servers get killed as `not_ready` |
| emit the `spawning` lifecycle event at the Popen | the chip shows `cold` through ~13s of pre-spawn work |
| let the fast-path health timeout exceed the readiness poll's | the two disagree about liveness; on a drop-not-refuse host it also delays the first narration |

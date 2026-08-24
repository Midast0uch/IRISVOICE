# Tasks: Vision Browser Stage

> **STATUS 2026-08-23 — WAVES 0–3 CODE COMPLETE (T0a–T12b landed).
> Backend: 133 relevant tests green (spawn baselines flipped to contract
> guards, lease/ladder/surface contracts intact). Frontend: tsc clean,
> 384 jest tests pass; the only failures are pre-existing tests/bugfix
> exploration suites verified identical on a stashed clean tree.
>
> DEVIATIONS FROM SPEC TEXT (deliberate, called out per THE TEST RULE):
> 1. T0a+T0b consolidated into ONE file (test_vlm_spawn_baseline.py) — both
>    pin the same function; each baseline was still edited exactly once.
> 2. REQ-10 coordinate contract REFINED during implementation: the scaler is
>    visual-transform ONLY (no document width rewrite, NO __irisScale
>    multiplication of scroll offsets) — CSS transforms do not change layout,
>    so scroll mirroring stays correct without translation. Documented in
>    view_agent.py and pinned by test_view_scaler_injection.py.
> 3. test_vision_server_spawn_cmd.py lost its `_resolve_listener_pid` patch
>    line (the function was deleted by T3); gained _kill_process_tree +
>    hermetic VRAM patches instead.
> 4. ESLint cannot run in this environment (config module resolution fails
>    before linting — pre-existing); tsc --noEmit is the standing gate.
>
> REMAINING (as of 2026-08-23): Wave 4 (T13 simulator + sign-off checklist —
> user returns for this), T14 non-interference guards, T15 full-suite re-run,
> T16 LIVE gates (user-in-the-loop), T17 shared-Chromium spike decision.

> **STATUS 2026-08-24 — T3 RE-LANDED; T14 IS DONE (the line above is stale).**
> Actually remaining: **T13, T15, T16, T17.**
>
> A full prior session was spent chasing a VLM "spawn hang" that does not
> exist. The theory it was built on (a torch-CUDA parent hanging llama.cpp's
> device probe) is FALSIFIED — see REQ-3 "Verified (CORRECTED)". The real
> blocker was HOST I/O CONTENTION on the model files (on-access AV + a kernel
> anti-cheat filter driver + RAM starvation), which blocks llama-server inside
> the kernel with flat cpu, flat io and no log output. **Read "Host
> prerequisites" below BEFORE any live vision measurement.**
>
> Landed 2026-08-24 in `lfm_vl_provider.py`: launcher wrapper + env
> sanitization + `IRIS_VISION_SPAWN_WRAPPER` DELETED; patient readiness with a
> `_proc_cpu_seconds` progress signal; **stay-warm lifecycle** (the 120s
> auto-stop is gone — REQ-4 updated); preflight reap of an unresponsive owned
> server; `_probe_av_latency()` diagnostic. 20/20 pinned tests green, none
> modified.
>
> **T13 IS NOT BLOCKED ON VISION.** REQ-12 AC5: the simulator "SHALL require
> zero backend/VLM/GPU involvement". Start it without a warm VLM.
>
> CAUTION: `backend/tests/integration/test_vision_mcp.py` has a PRE-EXISTING
> hanging async test — run it with `-k`, never whole-file.

> Each task links to a requirement. Waves group parallelizable work.
> Wave 0 baselines MUST be green against unchanged code before any edit.
> THE TEST RULE applies: never weaken a test to go green; report conflicts.

## OPTIMIZATION GATE — applies to EVERY task, no exceptions

> Standing rule (user-directed 2026-08-23): the path of least resistance is
> how this pipeline accumulated its debt. Every task report MUST include a
> short HOT-PATH NOTE answering, for the code it touches: what runs per-call /
> per-frame / per-event, what is hoisted or precomputed, every allocation on
> the hot path and why it is acceptable. A task whose note says "works" without
> this analysis is NOT done — same standing as the AGENTS.md quality check.
> Task-specific gates are called out inline below; they are MINIMUMS.

## Wave 0 — Baselines (fully parallel, no production edits)

- [x] **T0a (pins T1/T2)**: Characterize `_ensure_vision_server_running`
  concurrency AS IS — two threads, assert today's behavior (N spawns / N
  Popens) and the failure-path kill-by-port-scan —
  `backend/tests/unit/test_vlm_spawn_baseline.py`
  WHY: REQ-1/REQ-2 change exactly this; without the pin the change is
  unmeasurable.

- [x] **T0b (pins T3)**: Snapshot the spawn argv + PID bookkeeping AS IS —
  launcher wrapper present, `_VISION_SERVER_PID` = launcher pid then netstat
  adoption, `ttr_sec` log line shape — extend
  `backend/tests/unit/test_build_server_cmd_baseline.py` or new file.
  WHY: REQ-3 replaces the mechanism; the observable contract (ttr_sec line,
  ready semantics) must survive verbatim.

- [x] **T0c (pins T8)**: Capture/proxy response snapshot — current bytes for a
  fixture URL contain NO scaler injection; view-agent script present in
  captures — `backend/tests/contract/test_capture_scaler_baseline.py`.
  WHY: REQ-10 injects into these responses; baseline proves the delta.

- [x] **T0d (pins T-CHIP)**: `vision_status` WS message shape as consumed by
  `useIRISWebSocket.ts:1072` — fields today, so additive extension is provable
  — `__tests__/hooks/vision-status-shape.test.ts`.

## Wave 1 — Backend lifecycle (T1–T5; T4 needs T1)

- [x] **T1 (REQ-1)**: Single-flight spawn — `_spawn_lock` +
  `_spawn_in_flight` attempt object; waiters coalesce; failure clears attempt;
  waiter log line — `backend/tools/lfm_vl_provider.py`.
  GUARD: CT-1 becomes permanent (one Popen under concurrency) and MUST drive
  at least two DISTINCT entry points (e.g. the `_call` path AND
  `tool_bridge.py:734`'s direct call) — four production callers exist, not
  one; a lock that only two of them hit is a false green.
  OPT GATE: health fast path OUTSIDE the lock (REQ-1 AC5); waiters block on
  an Event, zero polling; attempt object allocated once per SPAWN, never per
  call.

- [x] **T2 (REQ-2)**: Ownership-safe cleanup — kill only attempt-owned tree;
  delete port-scan kill from failure path; PID-reuse command-line check
  (best-effort) — same file.
  GUARD: CT-2.
  OPT GATE: reuse check runs ONLY on the failure path; no extra subprocess on
  the success path.

- [x] **T3 (REQ-3)**: Direct spawn — **RE-LANDED 2026-08-24, see REQ-3
  "Verified (CORRECTED)".** Windows `CREATE_NEW_PROCESS_GROUP` only (NOT
  `DETACHED_PROCESS` — measured worse) / POSIX `start_new_session`;
  `cwd=<binary dir>` for CUDA DLL resolution; `stdout=DEVNULL`,
  `stderr=<log file>`, `stdin=DEVNULL`; env inherited VERBATIM;
  `_VISION_SERVER_PID` = `proc.pid` immediately; netstat adoption gone;
  LD_LIBRARY_PATH separator fixed per-platform — same file.
  The launcher wrapper, its stdout-PID protocol and
  `IRIS_VISION_SPAWN_WRAPPER` are DELETED (REQ-3 AC2 superseded). The old
  DEBT RULE about contract-testing the fallback is void — there is no
  fallback. **Do not re-add the wrapper**; its premise was falsified and its
  undrained `stdout=PIPE` was a latent deadlock.
  Also landed here: patient readiness + `_proc_cpu_seconds` progress signal
  (REQ-3 AC6), retry off by default (AC7), preflight reap of an unresponsive
  owned server, and `_probe_av_latency()` diagnostic.

- [x] **T4 (REQ-13 AC1/AC2)**: VRAM read-once threading through selection +
  gpu-layer decision; lease-held probe skip in `_call`; dead-server respawn
  via single-flight on connection error — same file.
  CONSTRAINT: existing tests pass UNCHANGED (AC5) — signatures gain optional
  params only.
  OPT GATE: the nvidia-smi read happens ONCE per spawn decision and is passed
  as a value, never re-read inside either consumer; probe skip keys off
  `has_active_lease()` (already O(1) bookkeeping), no new I/O.

- [x] **T5 (REQ-4 + REQ-5 backend)**: `request_warm(trigger)` idempotent warm;
  gateway hook on CRAWLER_STARTED after pool-ready signal; boot prewarm
  migrated to trigger="boot"; lifecycle notify -> `vision_status` additive
  fields {state, reason?, trigger?} — `lfm_vl_provider.py`,
  `iris_gateway.py`.
  RIPPLE: ws_event_bridge NOT touched (vision_status already bridged);
  contract test CT-8 pins shape.
  OPT GATE: lifecycle notify is a registered callback invoked outside any
  inference path; duplicate transitions coalesced (no event spam when state
  flaps within one second — document the debounce).

## Wave 2 — Event contract + reading surface (parallel with Wave 1)

- [x] **T6 (REQ-8 backend half)**: `escalated: bool` on first vision action of
  an escalated session — emitter site in orchestrator/fetch.vision payload,
  ux_map entry updated, CT-4 — `orchestrator.py`, `fetch_vision.py`,
  `ux_map.py`.
  RIPPLE (found in review, MANDATORY): add `"escalated"` to the gateway's
  CRAWLER_VISION_ACTION key whitelist (`iris_gateway.py:10205-10209`) — that
  tuple is the documented second place new fields silently die; CT-4 asserts
  the field survives the FULL WS hop, not just the emit site.

- [x] **T7 (REQ-10)**: `inject_view_scaler(html, nonce)` in
  `backend/proxy/view_agent.py` (NEXT TO the view-agent — one injection
  mechanism, shared anchor-search helper, nonce-tagged script per REQ-10 AC3);
  wire at BOTH serve sites (`browser_surface.py:169` capture, `:307` proxy);
  scale-aware scrollTo in the view-agent (`window.__irisScale`
  multiplication); UT-2 fixtures incl. headless doc, malformed HTML
  passthrough, DOUBLE-INJECTION idempotency.
  GUARD: CT-5; T0c baseline edited EXACTLY ONCE here (call it out).
  OPT GATE: single linear pass per response, reusing inject_view_agent's
  insertion-point search; store keeps ORIGINAL bytes; no regex over the full
  document beyond that one scan; zero work for non-HTML responses.

## Wave 3 — Frontend stage (needs T6 for flourish; rest parallel)

- [x] **T8 (REQ-7, REQ-9)**: Overlay backfill from CrawlProvider seed
  (idempotent vs snapshot replay) + aspect-correct cursor mapping util +
  UT-1 — `useBrowserNavOverlay.ts`.
  OPT GATE: seed derivation runs on mount / run-identity change only (ref
  keyed like `processedCrawlTabsRef`), never per render; mapPoint is a pure
  function, no allocation per frame beyond its return value.

- [x] **T9 (REQ-8 frontend half)**: The eye — blink kick on visionStep;
  hex-lattice scan in the border band (precomputed Float32Array geometry on
  measure(), integrated scanPhase, cursor-side bias, sprite-stamp draw,
  action-timeout fade) per design.md 3.3; escalation "notice" beat (aperture
  hold + violet shift + ring, 1600ms, 5s throttle); reduced-motion
  degradations (static band, opacity-step blinks) —
  `BrowserNavigationOverlay.tsx`.
  PERF GATE: profile at maximised panel; if frame cost exceeds the existing
  particle streams' budget, halve cell density first. Lattice geometry is
  rebuilt ONLY in measure() (resize), never per frame; zero per-frame
  allocations (typed arrays written in place).

- [x] **T10 (REQ-5 frontend)**: VisionLifecycleChip consuming
  `iris:vision_status`; mount in browser panel header row — NEW component +
  `dark-glass-dashboard.tsx` + `useIRISWebSocket.ts` detail extension.
  OPT GATE: chip subscribes to the existing WS dispatch path; no polling, no
  new listeners beyond one CustomEvent.

- [x] **T11 (REQ-6)**: AmbientCrawlTier — wing-independent mount point (app
  shell), consumes CrawlProvider, minimal-when-panel-visible predicate via
  extracted `useWingVisibility()` helper shared with DashboardWing;
  reduced-motion static text — NEW component, `dashboard-wing.tsx`
  (extraction only), app shell mount site.
  OPT GATE: ambient tier renders NOTHING (returns null) when idle — no rAF,
  no timers while no crawl is active; shares OrbCanvas rather than importing
  a second particle engine.

- [x] **T12 (REQ-11)**: Browser branch padding `p-4 md:px-10` -> `p-1.5`;
  address bar h-10 -> h-9; verify overlay geometry via simulator scenario k;
  confirm zero diff on other sub-app branches — `dark-glass-dashboard.tsx`.
  RIPPLE (found in review, MANDATORY): update `browserChromeInset`'s
  hardcoded `40` (`dark-glass-dashboard.tsx:643`) to match the new address
  bar height — it feeds the overlay's orb centring and top-wash depth, so a
  missed constant drifts the eye 4px off centre. Better: derive both heights
  from ONE shared constant pair instead of two literals.

- [x] **T12b (REQ-15)**: Single Live Reading surface — replace tab-per-page
  effect with stable `live-reading` tab whose provenance (and thus frame src)
  rewrites per page event; 300ms coalesce window; pin/follow modes with LIVE
  pill; clickable PlanCard sources via `iris:view_source`; processed-set ref
  repurposed as navigation guard; summary tab untouched —
  `dark-glass-dashboard.tsx`, PlanCard component.
  GUARD: extend the crawl behavioral test asserting exactly ONE web tab
  exists after an N-page run and its final capture address equals the last
  page event.
  OPT GATE: coalesce timer is ONE ref-held timeout, cleared on unmount and
  run end (no timer per page event); provenance rewrite mutates the single
  live-reading tab object — no array copies per event beyond the one setTabs
  update; verified against useActiveFrameSrc's memo deps (tabs identity
  changes → src recomputes → iframe reloads — confirmed workable in review).

## Wave 4 — Simulator (needs T8–T12 landed to be meaningful; runner can start earlier)

- [ ] **T13 (REQ-12)**: Vision Stage Simulator — `/dev/vision-stage` dev route
  + scenario runner dispatching real `iris:*` CustomEvents; scenarios a–m per
  REQ-12 AC1; localStorage-persisted sign-off checklist; reset-to-idle;
  live-crawl guard; wide-page fixture for scenario k — NEW
  `app/dev/vision-stage/page.tsx`, `simulator/scenarios.ts`,
  `simulator/runner.ts`, `__tests__/fixtures/wide-page.html`.
  DECISION TO RECORD: if CrawlProvider filters synthetic events for scenario j,
  extend runner via local replay endpoint — record choice here.
  BT-1 asserts trace sequences for scenarios a/b/c/e/f.
  **NOT BLOCKED ON VISION (2026-08-24).** REQ-12 AC5 is explicit: the simulator
  "SHALL require zero backend/VLM/GPU involvement". Scenario (h) drives the
  lifecycle chip cold->spawning->warm->error with SYNTHETIC `vision_status`
  events — do NOT wire it to a real spawn, and do not wait on a warm VLM to
  start this task. If the chip currently seeds only from a live
  `get_vision_status` on mount, that is an AC5 violation to fix here, not a
  reason to boot a VLM.
  Partial work already on disk (untracked): `app/dev/vision-stage/page.tsx`,
  `components/iris/simulator/VisionStagePanel.tsx`. Verify against the
  scenario list before assuming coverage.
  **SCENARIO RANGE — resolved 2026-08-24.** Four places disagreed: this task
  said `a–m`, REQ-12 AC1 stops at (l), `design.md:368` and T16.3 said `a–k`.
  The **Sign-off checklist at the bottom of this file is authoritative: a–m,
  13 scenarios.** It is the superset and the thing the user actually ticks.
  The others are stale by accretion, not by disagreement: (l) hex-scan was
  added with REQ-8 AC2 and (m) live-reading with REQ-15/T12b, and the earlier
  `a–k` text predates both. REQ-12 AC1 has been extended with (m) to match.

- [x] **T14 (REQ-14)**: Non-interference guards — CT-6 pointer-events grep
  guard over overlay source; CT-7 no-inbound-channel grep guard over
  `browser_session.py`; assert scroll mirror sends nothing backendward.

## Host prerequisites (READ BEFORE ANY LIVE VISION MEASUREMENT)

Added 2026-08-24 after a full session was lost to this. The vision server's
"hangs" were host I/O contention on the model files, not code. Before treating
a slow/stalled vision load as a bug, confirm ALL of these — otherwise you will
be debugging someone's antivirus:

1. **AV exclusions in place** (Administrator PowerShell):
   `Add-MpPreference -ExclusionPath 'C:\dev\IRISVOICE'` — covers all FIVE
   llama-server builds in the tree (`llama.cpp\build\bin\Release`,
   `llama.cpp-prismml\bin`, `llama.cpp-prismml-src\build\bin`,
   `llama.cpp-turboquant\build\bin`, `src-tauri\binaries\llama-server`) plus
   any future one.
   `Add-MpPreference -ExclusionPath '<LM Studio models dir>'` — the GGUFs live
   OUTSIDE the repo (`C:\Users\<you>\.lmstudio\models`), so the repo exclusion
   alone does NOT cover them.
   Verify with `Get-MpPreference | Select -ExpandProperty ExclusionPath` and
   `... ExclusionProcess` (two SEPARATE lists — a process exclusion never
   appears under paths).
2. **No other filesystem filter drivers active.** Kernel anti-cheat is the one
   that bit us (MapleStory's `BlackCipher64.aes`, resident during every failing
   run and absent during every fast one). EDR/backup agents count too.
3. **Free host RAM.** A 2.5GB model cannot stay in page cache at 1.4GB free of
   16GB, so every load becomes a full cold disk read. Check the backend's own
   footprint first — it was measured at 3.85GB.
4. **Sanity-check raw disk throughput** on the GGUF before blaming the spawn.

Expected healthy result once the above hold: **~3–4s to ready**, repeatable.
Anything in the tens of seconds means a host condition, not a code regression.

## Wave 5 — Verification

- [ ] **T15**: Full suite green: backend pytest + frontend jest + tsc --noEmit
  + lint. Existing suites pass UNCHANGED except the two called-out baseline
  edits (T0c->T7). Any other test edit is a REPORTABLE DEVIATION.

- [ ] **T16 (LV-1..LV-3) — LIVE GATES, user-in-the-loop**:
   1. Measure `ttr_sec` direct-spawn on real GPU. **REWRITTEN 2026-08-24** —
      the old instruction ("if device-probe hang persists, flip
      IRIS_VISION_SPAWN_WRAPPER=1 and re-measure") is DEAD: that flag no
      longer exists and the hang it hedged against does not exist either.
      The correct procedure when `ttr_sec` is bad:
        a. Confirm the Host prerequisites above are actually in effect.
        b. Check the backend log for `av_scan_suspected` — if present, the
           blocker is a filesystem filter driver, NOT the spawn code.
        c. Sample the child while it stalls: `psutil` `cpu_times()` +
           `io_counters()` against `MsMpEng.exe` CPU. Flat `read_bytes` with
           AV CPU climbing == on-access scanning. Flat everything with no AV
           CPU == some other filter driver (anti-cheat, backup agent, EDR).
        d. Compare `dd`/raw read throughput of the GGUF against a known-good
           baseline (3.5 GB/s cached on this box; 57–282 MB/s when contended).
      Record the measured `ttr_sec` AND the host conditions it was measured
      under — a `ttr_sec` without host context is not a result.
   2. Search 10min post-boot: chip shows spawning→warm within 2s of
      crawler_started; escalation finds warm endpoint.
   3. USER SIGNS OFF every simulator scenario a–m (checklist complete —
      all 13 rows in the Sign-off checklist below).
      This is the feature's completion gate — no crystallization before it.

- [ ] **T17 (REQ-13 AC3)**: Shared-Chromium spike + recorded decision
  (implement only if crash isolation preserved via isolated contexts AND
  vision-crash cannot poison pool workers; otherwise record rejection with
  measurements). Must close before spec close; may conclude "rejected".

## Dependency notes
- Wave 0 gates everything.
- T1 gates T4's respawn path and T5's request_warm internals.
- T6 gates T9 (flourish needs the field) but T8 is independent.
- T13's scenario list references T8–T12 behaviors; runner scaffolding can
  land after T6 alone, scenarios fill in per-wave.
- T16.3 (user sign-off) is the LAST gate; everything else serves it.

## Sign-off checklist (rendered by the simulator; mirrored here)
| Scenario | Expected beats | Signed |
|---|---|---|
| a crawl-full | dim stream → bloom → shutter cadence w/ page kicks → settle ring fade | ☐ |
| b crawl-error | amber settle | ☐ |
| c cursor-click | orb travels (620ms ease), tightens, trail decays | ☐ |
| d cursor-type | same grammar at type point | ☐ |
| e scroll | iframe content scrolls smoothly; cursor holds position | ☐ |
| f escalation | eye NOTICE: aperture holds open, violet shift, scan brightens x2 ≤1.6s, throttled | ☐ |
| g rapid pages | lapMs re-times from median gap; no particle jumps | ☐ |
| h lifecycle chip | cold→spawning(amber pulse)→warm(emerald)→error(red+reason) | ☐ |
| i ambient tier | panel CLOSED: ring+counter visible near orb; panel open: dot only | ☐ |
| j mid-run mount | overlay opens already crawling at correct page count | ☐ |
| k fit-to-width | wide fixture fully visible in width; scroll mirror still works | ☐ |
| l hex-scan | during sustained scroll: hex cells ignite in traveling front, biased to cursor side, fades when actions stop | ☐ |
| m live reading | 5-page scripted run: ONE tab, surface follows latest page; click a source -> pins; LIVE pill resumes | ☐ |




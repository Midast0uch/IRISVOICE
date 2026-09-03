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

> **STATUS 2026-08-24 (LATEST — supersedes both blocks above).**
> T13 DONE (all 13 scenarios signed off live). T14 DONE. **T17 CLOSED —
> shared-Chromium REJECTED with measurements.** T15 backend suite RUN for the
> first time (4480 passed; 22 failures fixed, all edits itemised under T15;
> the residual red verified pre-existing against a clean HEAD worktree and
> owned by other domains).
>
> **STATUS 2026-08-25 — WAVES 0–5 COMPLETE + REQ-17. WAVE 6 NOT STARTED.**
>
> CORRECTION: an earlier version of this header claimed "SPEC COMPLETE, every
> task closed". That was wrong — it counted only the tasks worked that session.
> **T18–T21 (Wave 6 / REQ-16, the orb-badge retirement) have never been
> started.** They are the last open work in this spec.
>
> T16 CLOSED. Both live gates were measured and BOTH FAILED, exposing a P0:
> **the vision readiness probe had never executed once.** httpx was imported
> as a local of a different function, every poll raised NameError, and a bare
> `except Exception: pass` ate it — so a healthy server listening in ~3s was
> reported dead 300s later and killed. `ttr_sec` 305.61/FAIL -> 4.01/PASS.
> Separately the lifecycle chip sat on `cold` for 12.96s after crawler_started
> (13s of pre-spawn work ran before the notify); now 1.66s, inside the 2s AC.
> See T16 for the full record and for what was ruled out along the way.
>
> This is the real cause behind "vision randomly unavailable", the falsified
> torch-CUDA spawn-hang theory, and a session lost to blaming antivirus. The
> host prerequisites below are genuinely useful for cold-load speed and were
> confirmed in effect — which is precisely what eliminated the host
> explanation and forced the search into the code.
>
> T22/T23/T24 closed: the REQ-17 mesh film is STANDARD browser behavior, its
> sign-off is recorded below the frozen a–m table (not inside it), and guard
> tests exist for both the film and the readiness probe — each verified to
> FAIL against the bug it pins.
>
> The Vision Stage Simulator was REMOVED after sign-off; see ARCHITECTURE.md
> section 7, which preserves its contract and scenarios.
>
> Also landed 2026-08-24 under T15: the vision scroll path now costs ONE CDP
> round trip instead of two (design.md §5), and the IPv4 readiness probe —
> the bug that reported healthy vision servers as dead and killed them — is
> under test for the first time.
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

> **T13 IS DONE AND THE SIMULATOR HAS SINCE BEEN REMOVED (2026-08-24).** It was
> built, it did its job (all 13 scenarios signed off live), and it was deleted
> from the shipping tree once sign-off closed. The task text below is kept
> as-built for the record. See the Sign-off checklist note at the bottom of this
> file for what was removed and how to recover it.

- [x] **T13 (REQ-12)**: Vision Stage Simulator — `/dev/vision-stage` dev route
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

- [~] **T15**: Full suite. **BACKEND RUN COMPLETED 2026-08-24** (the previous
  attempt died silently; see method note). Frontend was already green:
  391/399 jest, the only 8 failures the documented pre-existing
  `tests/bugfix` exploration suites; `tsc --noEmit` clean (re-confirmed).

  **METHOD — how to run this suite at all.** A single hanging test aborts the
  WHOLE pytest session via the pytest-timeout dump, so a per-directory run
  yields zero summary and looks like a silent death. Run per directory with
  `-v` so the hanging nodeid is written live, then `--deselect` it and re-run;
  repeat. Script kept at `scratchpad/run_dir.sh`. Suites must run
  SEQUENTIALLY — a concurrent jest run makes pytest look pathologically slow.

  **BACKEND RESULT: 4480 passed, 214 failed, 33 errors, 31 hangs quarantined**
  across unit / contract / behavioral / integration / backend-root / root
  tests.

  **Pre-existence verified without disturbing the working tree**: the failing
  node ids were re-run against a clean `HEAD` in a separate `git worktree`
  (NOT `git stash` — the dev server and backend are live against this tree).
  The residual failures are the repo's standing red — voice/audio, telegram,
  parakeet, porcupine, `iris_core` DLL, lmstudio — all environment-dependent
  and untouched by this spec.

  **22 FAILURES FIXED. Every test edit is a REPORTABLE DEVIATION, listed:**

  1. `test_browser_session_contract.py:225` — exact-string assertion re-pinned
     after the scroll and the REQ-16 AC7 mirror read were FUSED into one
     `evaluate` (see the REQ-13 note below). Still exact equality against a
     literal spelled out in the test; no loosening. Its sibling at `:247`
     (evaluate count == 2) then passed UNCHANGED — the fusion RESTORED that
     guard, which had been red since `d537ffb6` added the second evaluate.
  2. `test_document_rehydration_wave0.py` — the fake `penalize_url` took two
     args; the real one grew `last_error` with REQ-10/T12 and the orchestrator
     passes it, so the call raised TypeError, was swallowed by
     `_apply_har_penalties`, and the assertion saw an empty list. Stub
     signature corrected in BOTH tests in the file (the sibling was a latent
     false-green). Assertions untouched.
  3. `test_document_rehydration_wave0_prov.py` — fixture drove
     `markdown="m"`, one char, below `MIN_CONTENT_CHARS=20`, so
     `_learn_from_crawl`'s REQ-1 usability filter returned before the registry
     and the input never reached the assertion. The fixture encoded the
     PRE-REQ-1 behavior that filter exists to kill. Content raised above the
     floor; assertion and load unchanged (still exactly one page).
  4. `test_vlm_spawn_baseline.py` — HALF-APPLIED T3 EDIT, not a regression.
     The test NAME and its assertion still pinned the launcher wrapper while
     the same file's module docstring, its section header, REQ-3 "Verified
     (CORRECTED)" and tasks.md all state the spawn is DIRECT. Flipped to guard
     direct spawn and renamed `test_spawn_is_direct_and_probe_is_ipv4`.
     STRENGTHENED: the IPv4 probe half of the name was never asserted at all —
     the health-probe double now records URLs and the test asserts every probe
     targets `127.0.0.1`. That probe bug is what reported healthy vision
     servers as dead and killed them; it was untested until now.
  5. `tests/contract/test_proxy_contract.py` (8),
     `tests/contract/test_capture_replay_contract.py` (4),
     `tests/behavioral/test_in_app_browser_acceptance.py` (5) — ONE root
     cause. These build a bare app and called the endpoints with NO surface
     credentials. Since the browser surface grew its two gates
     (`browser_auth.py:130`, wired at `browser_surface.py:132/:231`) an
     unauthenticated request is refused 404 BEFORE the handler runs, so every
     assertion measured the auth refusal instead of its subject — silently
     including the REQ-5 egress guard cases (loopback / private /
     redirect-to-loopback) and the REQ-6 gate-closed 403. The clients now
     present a loopback peer and a valid token, matching the PASSING suite
     `backend/tests/contract/test_browser_surface_auth.py`. No assertion
     touched by the fixture change.

     Three assertions inside those files then reached real behavior and were
     found to be PINNING SHIPPED BUGS, each contradicted by the newer, passing
     `test_browser_surface_headers.py`. All three were corrected to the fixed
     contract and made STRICTER, not weaker:
       - `script-src 'none'` -> must exist, must NOT be 'none', must be
         nonce-scoped. `'none'` stops the injected view-agent running (REQ-4
         dead) — `browser_surface.py:44-59`.
       - `frame-ancestors 'none'` -> must exist, must NOT be 'none', must
         carry `'self'`, never a wildcard. `'none'` is `X-Frame-Options: DENY`
         by another name and makes every served page unframeable — the exact
         failure this feature fixes; pinned by
         `test_browser_surface_headers.py:45`.
       - `Access-Control-Allow-Origin == "null"` -> NO `access-control-*`
         header of any kind. `"null"` IS the opaque origin a sandboxed document
         presents, so sending it grants read access to precisely the reader the
         sandbox excludes (`browser_surface.py:108-111`); pinned by
         `test_no_cors_header_at_all`. The behavioral file accepted
         `(None, "null")` and was tightened to reject `"null"`.

  ESLint still cannot run in this environment (pre-existing config module
  resolution failure); `tsc --noEmit` remains the standing gate.

  REMAINS OPEN: the standing red above is not this spec's to fix, but it means
  "full suite green" is not literally true and T15 stays partially checked.

- [x] **T16 — CLOSED 2026-08-25. All three gates met, and T16.1 caught a P0.**

  **Host prerequisites CONFIRMED IN EFFECT** (user ran the elevated check):
  exclusions cover BOTH `C:\dev\IRISVOICE` and `C:\Users\midas\.lmstudio\models`;
  filter drivers are a stock Windows set (WdFilter is Defender's own — no
  anti-cheat, no EDR); 5.53GB free RAM of 15.96; RTX 3070 with 5862MiB free.
  Per this file's own runbook that eliminates the host explanation, which is
  what forced the search into the code.

  **T16.1 — `ttr_sec` direct spawn. FAILED, then FIXED.**

      before: ttr_sec=305.61  ok=False   (twice, cold and warm cache)
      server's OWN log, same run: listening on 127.0.0.1:18181 at 2.90s
      after:  ttr_sec=4.01    ok=True

  ROOT CAUSE — **the readiness probe had never executed. Not once.**
  `_ensure_vision_server_running` imports httpx INSIDE its own body, binding
  it as a LOCAL to that function. The readiness poll lives in a different
  function, `_spawn_vision_server_now`, where httpx was never in scope and
  there is no module-level import. Every poll raised `NameError`, and
  `except Exception: pass` ate it. The loop then ran on log-growth and CPU
  signals alone, went quiet when the load finished at ~3s, and declared the
  healthy listening server dead 300s later — then killed it under REQ-2.

  This is the true cause behind "vision randomly unavailable", the falsified
  torch-CUDA spawn-hang theory, and a whole session lost to blaming
  antivirus. The AV exclusions are genuinely useful for the cold load but
  were never the cause of THIS; the signature (flat log, flat CPU, live
  process) matched the AV story closely enough to misdirect twice. The
  previous commit's patience fix is why the symptom moved 120s -> 300s while
  the probe underneath stayed dead.

  Ruled out before finding it, so nobody redoes the work: not the timeout
  (the exact call succeeds 8/8 at ~0.43s), not the heavy imports (6/6 from a
  fully-imported process), not proxy env, not the URL, not a crash
  (`proc.poll()` stayed None).

  **T16.2 — chip `spawning` within 2s of `crawler_started`. FAILED, FIXED.**

      spawning after trigger: 12.96s -> 2.57s -> 1.66s   (AC: <= 2s)
      escalation finds warm endpoint: PASS
        (_ensure fast-path 0.56s, /v1/models 200 in 0.45s,
         advertising LFM2.5-VL-3B-Q4_K_M.gguf)

  Two causes. (a) `spawning` was emitted at the Popen, AFTER nvidia-smi, the
  candidate ladder, GGUF metadata reads and the AV probe — 13s of real work
  during which the chip said `cold`. Moved to the point of commitment.
  (b) The fast-path health check used `timeout=2.0` and sat directly in front
  of it; a closed port on this host silently DROPS rather than refuses, so it
  cost its full budget every cold start. Aligned to 1.0, matching the
  readiness poll's timeout for the same request against the same server.

  **T16.3 — user sign-off: complete** (13/13 scenarios, 2026-08-24).

  NOTE ON VARIANCE: `warm` was observed at 15-29s across runs. The spec's own
  matrix records 3.87 / 3.95 / 4.90 / 11.04 / >100s for the same argv inside
  one 20-minute window — cold page-cache reads dominate. `ttr_sec` is the
  gate's measurement; end-to-end `warm` timing is not stable enough to gate on.

- [x] **T16 (LV-1..LV-3) — original text, kept for the record**:
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

- [x] **T17 (REQ-13 AC3)**: Shared-Chromium spike + recorded decision —
  **REJECTED, 2026-08-24.** Both gate conditions fail, and the benefit the
  flag was meant to buy has already been banked by other means.

  **(a) Crash blast radius — measured, and it disqualifies the design.**
  AC3 permits sharing only if "crash isolation semantics MUST be preserved"
  and "a vision crash must not take down crawl workers". Spike: launch one
  Chromium, open two contexts (one standing for a crawl, one for a vision
  session), kill the BROWSER process, observe both.

      both_alive_before        [true, true]
      killed_pid               22532          (browser process)
      crawl_ctx                DIED: TargetClosedError
      vision_ctx               DIED: TargetClosedError
      browser_connected        false

  Contexts are COOKIE/STORAGE domains, not CRASH domains. A browser-process
  crash takes every context with it, so one consumer's crash necessarily
  destroys the other's work. The design.md:390 condition "isolation preserved
  via separate CONTEXTS" is not achievable — the premise is false.

  METHOD NOTE, because the first run said the opposite: matching the debug
  port anywhere in the cmdline also matches Chromium's renderer/GPU/utility
  CHILDREN, which inherit the flag. Killing one of those is survivable by
  design and produced a bogus "SURVIVED". The browser process is the match
  carrying NO `--type=` switch (3 matched, 2 were children). The corrected
  run is the one recorded above.

  **(b) Cold-start savings — measured, and already captured elsewhere.**

      launch_cold_s   3.052     launch_warm_s   0.145
      cdp_attach_s    1.701     new_context_s   0.033

  Sharing would replace a 0.145s warm launch with a 1.701s CDP attach — it is
  ~11x SLOWER at steady state, which is the state that matters. Both sides are
  already warm-pooled and pay no per-use launch:
    - vision: `browser_pool.py` holds one Chromium, per-session
      `new_context()` at 0.033s (was 4 cold launches per 4-URL escalation).
    - crawl: `_WarmCrawlPool` (`crawl_runner.py:111`) keeps resident `--serve`
      workers, so Crawl4AI/Chromium INIT is paid once per pool lifetime at
      boot, never mid-search (was ~19s per worker; ~72s for 5 URLs).
  The residual saving is one resident Chromium's memory, against merging two
  crash domains.

  **Feasibility was never the blocker.** crawl4ai 0.8.6's `BrowserConfig` does
  accept `cdp_url` / `use_managed_browser`, so this is implementable. It is
  rejected on isolation and on steady-state latency, not on effort.

  Secondary hazard, recorded so it is not rediscovered: the pool's idle
  watchdog stops the shared browser after `IRIS_BROWSER_IDLE_TIMEOUT` (180s)
  based on ITS OWN lease accounting. A CDP-attached crawl worker is not a
  lease holder, so the browser could be stopped under a live crawl — a new
  race with no counterpart today.

  Flag-off environments (`IRIS_CRAWL_POOL=0`) keep today's isolated stacks
  either way, per REQ-13's edge case.

## Dependency notes
- Wave 0 gates everything.
- T1 gates T4's respawn path and T5's request_warm internals.
- T6 gates T9 (flourish needs the field) but T8 is independent.
- T13's scenario list references T8–T12 behaviors; runner scaffolding can
  land after T6 alone, scenarios fill in per-wave.
- T16.3 (user sign-off) is the LAST gate; everything else serves it.

## Mesh film (REQ-17) — LANDED + SIGNED OFF 2026-08-24

- [x] **T22 (REQ-17 AC1-AC8)**: Surface mesh film in
  `BrowserNavigationOverlay.tsx` — shared-wall honeycomb across the panel,
  traced edge-by-edge, driven by waves launched from the kick-pulse shutter.
  User signed off live after seven iterations. **STANDARD BEHAVIOR** (default
  ON; `MESH_PREF_KEY` exists only as an opt-out).

  Seven iterations, each rejected for a reason worth keeping — every one was a
  mechanism error, not a taste disagreement:
  1. Gated on `visionActionRef` only -> never ran during a CRAWL (which emits
     `crawler_page_fetched`, not `crawler_vision_action`). Also rode
     `hexPulseRef`, which only advances inside `drawHexScan` and therefore
     never ticks without a vision action. Now gates on crawl states and
     schedules its own clock off the same shutter edge.
  2. Depth-scaled cell taper read as a perspective tunnel -> uniform size.
  3. Per-cell random ignition read as a dither screen -> clustered.
  4. Clusters averaged 2.2 cells (bucket smaller than the grid pitch) and read
     as disconnected specks -> bucket widened to hold ~13 adjacent cells.
  5. Shared cluster phase forced every cell in a comb to appear on the same
     frame ("stuck together") -> per-ring stagger from the patch seed. The
     stagger SIGN was also inverted, so outer rings led and combs collapsed
     inward ("disappearing inward").
  6. Whole hexes stroked at 0.94x the tiling radius: vertices never coincided,
     so 0% of walls were shared and growth could not cross between cells.
     Radius must EQUAL the pitch radius exactly.
  7. Band twice the launch spacing -> 100% lit within 4s, wave read gone.
     Fixed by throttling the LAUNCH RATE, never by evicting live waves.
  Final: contour noise to break the rectangular iso-contours (the "square
  funnel"), every third wave outward, depth softening at the centre.

- [x] **T23 (REQ-17)**: Sign-off record for the film — DONE 2026-08-25.
  The a–m table is NOT edited: it is the frozen record of what the user ticked
  in the simulator on 2026-08-24, the simulator no longer exists, and adding a
  fourteenth row would misrepresent that session. The film's sign-off is
  recorded as its own entry below the table instead, which is accurate — it was
  approved live, in the running app, after seven iterations.

- [x] **T24 (REQ-17 AC7)**: Guard tests — DONE 2026-08-25.
  `__tests__/mesh-film-guards.test.ts`, 9 source guards in the CT-6/CT-7 idiom
  (canvas output cannot be meaningfully unit-tested; every guard pins a failure
  that ACTUALLY happened during the seven build iterations, not a hypothetical):
  pitch derived from `meshR` not `hexR` (the 0.94x radius gave 0% wall sharing),
  wall dedup on quantised endpoints, `MESH_WAVE_LIFE` derived from every arrival
  term, contour noise present and non-trivial, wave count throttled at launch
  rather than by eviction, reduced-motion gate, crawl states in the activity
  gate, preference-not-event parity, default-ON.
  **Verified failing**: flipping the pitch back to `hexR` turns the guard red.

  Also added `backend/tests/contract/test_vision_readiness_probe.py` (4 tests)
  for the T16.1 defect — the probe must actually issue a request, must target
  IPv4, a programming error inside the poll must re-raise, and an ordinary
  connection error must still be tolerated. **Verified failing**: removing the
  httpx import turns 3 of 4 red with `NameError`.

## Wave 6 — AmbientCrawlTier repurposed (REQ-16; user-directed 2026-08-24)

> **DONE 2026-08-25.** T18-T20 landed; T21's harness is restored.
>
> THE RULE THAT MAKES THIS WORK — and that the spec did not state: **the tier
> shows only what no VISIBLE surface is already showing.** Retiring OrbBadge
> removed one duplicate indicator; always showing the unified counter would
> have immediately introduced another (ChatView open on a live TaskListCard
> reading [3/7], tier beside the orb also reading [3/7]).
>
>   browser panel visible -> shutter owns the crawl -> tier drops pages
>   ChatView + LIVE card  -> card owns the steps    -> tier drops steps
>   both                  -> nothing to add         -> minimal presence dot
>   neither               -> tier is the ONLY indicator -> shows both
>
> "Live card" reuses chat-view's own `taskProgressStillRunning` predicate
> (chat-view.tsx:590): the card drives its indicator only while a step is
> unresolved. Once every step resolves the card goes static and the tier speaks
> again — covering the synthesis phase that measured 79s of silent UI.

- [x] **T18 (REQ-16 AC1/AC5) — DONE 2026-08-25**: Counter form — new tier body reusing the
  CardChassis counter grammar (`[done/total]` bubble) + a radial progress ring
  + the existing OrbCanvas particles; unified done/total read across task
  steps AND crawl pages (useTaskProgress + CrawlProvider). Retire OrbBadge
  from the orb-only view (XurOrb.tsx) — keep the component file until the "?"
  question-variant fate is decided (Open Question below).
  OPT GATE: tier stays null when idle; no polling — counts arrive via the
  existing WS dispatch path.
- [x] **T19 (REQ-16 AC2/AC3/AC7) — DONE 2026-08-25**: Swallow/release transitions — when any
  wing opens during an active task/crawl, the XurOrb animates into the tier
  (FLIP-style: measure orb centre vs tier position, animate transform), tier
  becomes the sole working indicator; on completion the reverse plays.
  Reduced-motion: opacity fades only. Mutual exclusivity of orb and tier while
  a wing is open is a HARD contract (grep guard candidate like CT-6).
- [x] **T20 (REQ-16 AC4) — DONE 2026-08-25**: Inline ask — click on the counter form opens an
  input anchored at the tier; submit sends `text_message` with the CURRENT
  active conversation_id per socket LEARN/SUPPLY rules; no thread invention.
  If no active thread exists, route through ChatView's thread-creation path.
  GUARD: contract test asserting the submitted payload carries the id of the
  thread active at submit time (not localStorage-stale).
- [x] **T21 — simulator restored, used for Wave 6, then REMOVED AGAIN
  2026-08-25.** Restored so the swallow/release transitions (sub-second
  animations, impractical to judge on a live run) could be judged; Wave 6 is
  now complete and the harness is out of the shipping tree again.
  Recoverable this time — the files are in git history (commits 1bad87a5 /
  54d1296d), unlike the first removal where they were untracked. The MOUNT in
  app/page.tsx has never been tracked and must be rewritten from
  ARCHITECTURE.md section 7 if the harness is ever needed again.
  ORIGINAL NOTE: simulator RESTORED 2026-08-25 (it was committed before removal, so recovery was a `git checkout`; the MOUNT in app/page.tsx was never tracked and had to be rewritten). Scenario coverage for the counter form / swallow / release still needs your ACK before the frozen a–m table is touched.
  ORIGINAL: Simulator coverage — extend the Vision Stage Simulator with
  scenarios for: counter form (no wings), swallow transition (wing opens
  mid-crawl), release transition (task completes). NOTE: the sign-off
  checklist was frozen at a–m; adding rows n–o/p REQUIRES user ack before the
  checklist table is edited.

## Sign-off checklist (WAS rendered by the simulator; mirrored here)

> **THE SIMULATOR WAS REMOVED 2026-08-24**, after this checklist was completed.
> It is no longer rendered anywhere; this table and
> `ARCHITECTURE.md` section 7 are the record. The source is recoverable via
> `git show` on the commit immediately preceding the removal — that commit
> exists solely so the per-step `atMs` timings and full detail payloads, which
> the architecture doc does NOT reproduce, are not lost.
>
> Removed: `app/dev/vision-stage/page.tsx`,
> `components/iris/simulator/VisionStagePanel.tsx`, `simulator/scenarios.ts`,
> `simulator/runner.ts`, `__tests__/BT-1.simulator-traces.test.ts`, and the
> slide-over mount in `app/page.tsx`.
>
> COVERAGE LOST, stated plainly: BT-1 pinned trace sequences for scenarios
> a/b/c/e/f and went with it. Nothing else asserted those sequences.

> ✅ SIGNED OFF IN FULL — 2026-08-24, all 13 scenarios approved by the user
> live at /?mode=developer&dev=vision-stage (localStorage
> iris-vision-stage-signoff-v1). This closes T16.3, the feature's completion
> gate. Design iterations applied during sign-off are recorded in
> BrowserNavigationOverlay.tsx comments (hex kick-pulse, single-ring aperture,
> border flash, B&W escalation) and pin_655f5497e798 / pin_7c62601fde5f.

| Scenario | Expected beats | Signed |
|---|---|---|
| a crawl-full | dim stream → bloom → shutter cadence w/ page kicks → settle ring fade | ☑ |
| b crawl-error | amber settle | ☑ |
| c cursor-click | orb travels (620ms ease), tightens, trail decays | ☑ |
| d cursor-type | same grammar at type point | ☑ |
| e scroll | iframe content scrolls smoothly; cursor holds position | ☑ |
| f escalation | eye NOTICE: aperture holds open, violet shift, scan brightens x2 ≤1.6s, throttled | ☑ |
| g rapid pages | lapMs re-times from median gap; no particle jumps | ☑ |
| h lifecycle chip | cold→spawning(amber pulse)→warm(emerald)→error(red+reason) | ☑ |
| i ambient tier | panel CLOSED: ring+counter visible near orb; panel open: dot only | ☑ |
| j mid-run mount | overlay opens already crawling at correct page count | ☑ |
| k fit-to-width | wide fixture fully visible in width; scroll mirror still works | ☑ |
| l hex-scan | during sustained scroll: hex cells ignite in traveling front, biased to cursor side, fades when actions stop | ☑ |
| m live reading | 5-page scripted run: ONE tab, surface follows latest page; click a source -> pins; LIVE pill resumes | ☑ |

### Mesh film (REQ-17) — signed off separately, 2026-08-25

| Scenario | Expected beats | Signed |
|---|---|---|
| n mesh film | on each kick-pulse shutter a wave launches from the boundary inward; combs assemble seed-first and trace wall-by-wall; waves overlap into continuous honeycomb with a fading trail; no square funnel at the centre; every third wave runs outward | ☑ |

> NOT part of the frozen a–m table above. That table records what the user
> ticked in the Vision Stage Simulator on 2026-08-24; the simulator has since
> been removed, and back-filling a row into it would misrepresent that session.
> The film was approved live in the running app on 2026-08-25 after seven
> iterations — see T22 for what each one rejected and why.

> NOTE (f): the escalation grammar was REDESIGNED during sign-off per user
> feedback — violet shift replaced by black↔white treatment (white ring,
> scattered black hex spots, darkness border pulse), notice held to 2600ms.
> The row above preserves the ORIGINAL expected-beats text for the record;
> the as-signed behavior supersedes it.




# Requirements: Vision–Browser E2E Reliability & Performance

## Decisions Locked

These were derived from the end-to-end audit of the vision model path and browser
channels (initialization → provider selection → browser tools → event channels →
frontend response). Do not re-litigate.

1. **The resolver is the single source of vision serving.** Vision consumers must
   obtain their serving client from `backend/agent/inference/router.py`
   (`resolve_vision_client` / `resolve_vision_provider`), not by constructing the
   tier-3 `LFMVLProvider` directly. The existing hierarchy (BRAIN → TOOL → VL
   fallback) already exists and is already enforced for other consumers by
   `backend/tests/contract/test_no_direct_lfm_vl_provider_bypass.py`; the
   browser/vision consumers are the remaining bypass.
2. **The frontend mirror is a replay surface, not a control surface.** The
   sandboxed iframe renders captured HTML (opaque origin, no `allow-same-origin`).
   It cannot drive the server-side browser. Takeover must therefore be wired
   through an explicit, audited command channel, not by assuming the iframe is
   interactive.
3. **No artificial latency.** "Human-like" means intent and targeting, not
   slowness. Machine speed is the target; micro-settles are bounded and
   env-overridable.
4. **No unmeasured performance claims.** Every latency/throughput target in this
   spec is either grounded in a measured baseline or explicitly marked UNVERIFIED
   with a live-measurement task. The audit produced no reliable live baseline
   (backend was up; frontend had no listener; two browser drives timed out), so
   most targets below are UNVERIFIED by construction.
5. **The existing browser pool and capture-address design are KEPT.** The pooled
   Playwright/Chromium (`backend/vision/browser_pool.py`) and the capture slot
   stride (`CAPTURE_SLOT_STRIDE`) are load-bearing and are not redesigned here.
6. **Progress is measured by evidence, not by action-type repetition.** A
   consecutive-repeat heuristic that stops the loop on identical action *kinds*
   is not a progress signal and must be replaced by a visual/DOM progress signal.
7. **Takeover drives the SESSION, not a copy (OQ-1 RESOLVED, 2026-09-17).** The
   user acts inside the agent's own browser context through a CDP screencast with
   input forwarding. "Open the URL in another browser" is REJECTED, and the
   rejection is arithmetic, not preference: the pooled Chromium is launched
   `headless=True` (`backend/vision/browser_pool.py:285-290`), each context
   carries a spoofed user agent (`backend/vision/browser_session.py:111-131`),
   and a wall's clearance (a CAPTCHA clearance token, a pending 2FA, a login
   session) lives in the session that must be cleared. A separate browser cannot
   deliver that state back, so REQ-5 AC3 is unreachable through it. Evidence:
   `pin_b6d4658a903c`.
8. **The resume signal is the EXISTING answer funnel (OQ-4 RESOLVED).**
   `question_response` on WS -> `backend/iris_gateway.py:6220-6246` ->
   `AskUserTool.resolve_answer()`. No new WS command type is introduced. The wall
   is cleared by detection re-check (`browser_session.detect_wall()`), never by a
   bare user assertion.
9. **Session cookies come from the OS keyring (OQ-5 RESOLVED; REQ-12).** One
   isolated context per run, cookie payload keyed by host, injected at context
   creation only. No keyring entry means anonymous browsing.
10. **One page owner at any instant.** While a takeover grant is open the vision
    action loop is SUSPENDED. Agent actions and user input never race for the
    page.
11. **Screencast frames are a separate contract from vision-action events.**
    Frames ride their own event type and channel. They do NOT enter the
    capture-store slot design, and they do NOT join the
    `CRAWLER_VISION_ACTION` shape.
12. **Verification must be AGENT-DRIVEABLE (owner, 2026-09-17).** A vision run
    SHALL write its emitted events to a run-scoped machine-readable journal, the
    deterministic steps SHALL run against a loopback fixture with no network and
    no external model, and the standing harness SHALL run headlessly with an
    exit-code gate. Rationale: release 1 of the verification plan was manual and
    did not complete; and a model that can read the journal can prove its own
    work without a human in the loop.
13. **The browser acquire cost is bounded by MECHANISM, never by a guessed
    number.** The hot path is the ~33s COLD Chromium launch, not the model
    (`pin_000d74279a82`: "browser acquired in 32918ms (cold pool)"). Decisions
    Locked 4 still holds: the latency NUMBER is set only after the step-10
    baseline. This amendment bounds the BEHAVIOUR (warmth held for a run,
    cold launch announced, launch not charged to the action budget, hard
    timeout) and leaves the number UNVERIFIED until measured.
14. **THE VISION TIER LADDER IS EXPLICIT (OQ-2 RESOLVED, owner 2026-09-18).** One
    ordered ladder answers "who can see?", first rung that can serve wins:
    - **Tier 1 — CLOUD VISION.** A cloud-API brain that has vision, or a
      configured cloud vision provider. Wins when it exists.
    - **Tier 2 — LOCAL VISION CHOICE.** The user's local vision selection. A local
      model doing TOOL CALLING may still have vision (`supports_vision` decides
      capability, not the role name — `backend/agent/inference/router.py:707`), so tier 2 is the local
      vision choice, never "leftover cloud".
    - **Tier 3 — ALREADY-RUNNING LOCAL VL SERVER (borrowed only).** A warm
      `llama-server` we did not start or did start earlier. Never spawned, never
      waited for, never killed (Decision 15).
    - **Else — VISION UNAVAILABLE.** Degrade on the existing path; park the URL.
    Rung order and the no-vision outcome are both part of the contract, so no
    consumer invents its own preference.
    **PRECEDENCE (OQ-20 RESOLVED, owner 2026-09-18):** when a cloud-API brain WITH
    vision and a local vision model are BOTH available, **CLOUD WINS** — the brain
    answers its own sight, and the local vision model is the fallback. This matches
    today's code (`backend/agent/inference/router.py:698-724` returns the first role that
    `supports_vision`, brain first) and is adopted as the CONTRACT rather than left
    to emerge from iteration order.
15. **The browser path NEVER waits for a 6-minute model load (OQ-19 RESOLVED,
    owner 2026-09-18).** The spawn-and-wait path is REMOVED as an option for the
    browser path. If no bound provider has vision and no server is already warm,
    the system degrades and parks rather than blocking for a cold load
    (`ttr_sec=370+` measured). Spawning remains the job of the explicit user
    toggle and the search-scoped prewarm, never of a URL's action loop.
16. **Vision output is UNTRUSTED until it is digested (OQ-7 RESOLVED, owner
    2026-09-18).** Nothing read from a page becomes usable fact on arrival. Vision
    content enters the trust membrane as `untrusted` and is recalled
    zone-scoped. Targets, findings, and any latency claim derived from a run stay
    UNVERIFIED until the digest confirms the content is safe, non-malicious, and
    credible or useful. This CONSUMES existing machinery (verified:
    `agent_kernel.py:4598-4610` force-downgrades `content_origin in ("vision",
    "reconciled")` to `untrusted`; `_pacman_zone_for_turn` `:831`; recall zones
    `["trusted","tool"]` `:2816`; the cross-source gate in
    `specs/vision-goal-directed-search` REQ-11). It does not re-specify it.
17. **The resolver bypass scan runs in DEVELOPER MODE only (OQ-18 RESOLVED,
    owner 2026-09-18).** The AST scan is an authoring-time guard for code work,
    not a runtime gate. In Personal mode it does not run.

## Introduction

The vision model path lets IRIS drive a real server-side browser to read pages
that plain crawling cannot (bot challenges, JS-rendered content), and mirror that
session into the in-app browser panel. Today the path is functionally present but
unreliable and under-instrumented: browser consumers bypass the provider
resolver, the model is asked for CSS selectors it cannot produce, its own action
history is never fed back, the loop can stop on a false "stuck" signal, the
frontend replay is mistaken for an interactive surface, and there is no end-to-end
latency instrumentation. This spec makes the path correct, observable, and
measurably fast.

### Success criteria

- A vision session resolves its serving client through the hierarchy; no browser
  consumer constructs `LFMVLProvider()` directly. (Measurable: extend the
  existing AST bypass scan to cover `backend/vision/`.)
- The action suggestion the model receives names a target the executor can
  resolve (a stable handle), and `type` actions carry their input value
  separately from the target.
- The model receives its own recent action history and the no-repeat constraint.
- The loop terminates on measured lack of progress, not on repeated action kinds;
  a productive multi-scroll or multi-click session is not stopped early.
- The panel reflects the true session state (frames, scroll, action cadence) and
  a takeover request is honored through a real command channel.
- Per-stage latency is logged (capture, inference, action, publish) with a run id,
  so the next tuning iteration is measured, not guessed. Target numbers are set
  AFTER baseline capture (UNVERIFIED until then).

## Requirements

### REQ-1: Unified vision serving for browser consumers
**User Story:** As the operator I want every vision consumer to use the one
resolver so that a bound multimodal brain/tool is used instead of always spawning
the tier-3 server.
**Verified:** `backend/vision/fetch_vision.py:513-526` (`_get_provider` →
`get_lfm_vl_provider`), `backend/vision/search_discovery.py:366-375`
(`_get_provider`), `backend/agent/inference/router.py:1162+`
(`_DirectVisionClient`, `resolve_vision_client`), guard test
`backend/tests/contract/test_no_direct_lfm_vl_provider_bypass.py`.
**ADDED 2026-09-17 (owner clarification):** the tier-3 server is the SAME
`llama-server` the auto-loader uses for a local model — it exists so vision still
works when the brain/tool model has no sight. The provider already prefers an
ALREADY-RUNNING multimodal server over spawning (`lfm_vl_provider.py:71-99`,
`IRIS_VISION_REUSE_ENABLED`), gated on a real multimodal round trip, and it never
kills a server it did not start (`_stop_owned_vision_server`, `:679`;
`should_idle_stop`, `:481`). The spawn-own path is the fallback and it is
EXPENSIVE and VARIABLE: "a ~6-minute cold load on this class of machine — measured
ttr_sec=370+" (`:72-73`), with samples of 3.87s / 3.95s / 4.90s / 11.04s / >100s
(`:417`). Ports differ: vision `18181` (`iris_config.py:69`), local model manager
its own port (`backend/iris_gateway.py:9514`). So "always spawn tier 3" is not just a
wasted VRAM/spawn cost — it can add MINUTES and duplicate a model the user already
loaded.
**F2 (blocking call) — traced 2026-09-18 and now owned by T1:**
`backend/vision/search_discovery.py:482-490` calls `prov.read_text(img)` (`:484`)
and `prov.analyze_screen(...)` (`:486`) SYNCHRONOUSLY inside the async
`discover_urls_via_vision()`. That blocks the event loop for every concurrent task
— WS, audio, other crawls — which is worse than being slow: it stalls unrelated
users of the loop. `fetch_vision` already does this correctly via
`asyncio.to_thread`. REQ-1's ACs cover the RESOLVER, not the blocking call, so the
defect is named here AND in T1's scope (it had no AC and no task before this
audit).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL obtain the browser/vision serving client via
  `resolve_vision_client()` (or the equivalent resolver surface), preserving the
  existing `analyze_screen` / `read_text` / `suggest_action` / `health_check`
  method surface so call-site semantics do not change. **AMENDED 2026-09-18:** the
  AST bypass scan that proves this SHALL run in DEVELOPER MODE ONLY (Decision 17),
  and SHALL NOT fire on the legitimate lifecycle/health sites (see OQ-18's
  allowlist rule).
- AC2: WHEN a multimodal brain or tool provider is already bound THEN THE SYSTEM
  SHALL route vision calls to it and SHALL NOT spawn the tier-3 llama-server.
  **AMENDED 2026-09-18 (Decision 14):** callers SHALL NOT invent their own
  preference — the ladder is Tier 1 cloud vision → Tier 2 local vision choice →
  Tier 3 an already-running local VL server → else vision unavailable, first rung
  that can serve wins.
- AC3: IF the resolver raises `VisionModelUnavailable` THEN THE SYSTEM SHALL
  degrade exactly as today (return the existing "vision unavailable" observation),
  never raising into the crawl/vision hot path.
- AC4: THE SYSTEM SHALL keep the lease/idle-stop lifecycle the exclusive concern
  of tier 3 (the resolver's tier-3 branch), so a bound provider takes no lease.
  **AMENDED 2026-09-17 (owner clarification):** inside that branch the system SHALL
  prefer an ALREADY-RUNNING server over spawning one, and it SHALL distinguish
  OWNED (IRIS spawned it this run) from BORROWED (found already running — e.g. the
  local model the auto-loader loaded). The idle-stop and disable paths SHALL apply
  ONLY to an OWNED server. A borrowed server SHALL never be stopped, killed, or
  idled out: **vision SHALL NEVER unload the user's auto-loaded local model.**
  **AMENDED 2026-09-18 (Decision 15):** the browser path SHALL NOT spawn-and-wait
  at all. No bound vision provider and no warm server means DEGRADE + PARK — never
  a blocking cold load.

**Edge Cases:**
- Resolver unavailable (import failure) → same graceful degradation as a missing
  provider.
- Borrowed/remote provider → no lease, no spawn.
- Local bound provider → lease taken at any tier per Decisions Locked 8 of
  `specs/unified-vision-routing`.

### REQ-2: Action contract the executor can satisfy
**User Story:** As the vision loop I want the model to name a resolvable target
and a separate input value so that clicks/types actually hit the intended element.
**Verified:** `backend/tools/lfm_vl_provider.py:2226-2260` (`suggest_action`
prompt asks for `TARGET: [what to interact with]`),
`backend/agent/inference/router.py:1257-1263` (same free-text target),
`backend/vision/fetch_vision.py:550-570` (`_map_action` passes `target` straight
through), `backend/vision/browser_session.py` `act()` (treats `target` as a CSS
selector), `VisionAction` (`value` is a separate field).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL request an element identifier the executor can resolve
  (e.g. a role+name or an explicit selector handle) rather than an open-ended
  natural-language description, and SHALL request the `type` value in its own
  field.
- AC2: WHEN the model returns a target that does not resolve to an element THEN
  THE SYSTEM SHALL record the failure as a `last_error` observation and continue
  the loop (REQ-7 AC6 semantics), not abort.
- AC3: THE SYSTEM SHALL parse the suggestion into `VisionAction(kind, target,
  value, reason)` such that `type` populates `value` and never embeds the text in
  `target`.
- AC4: WHERE a description-only suggestion is returned THE SYSTEM SHALL attempt a
  bounded resolution step (role/name lookup) before treating the action as
  unresolvable.

**Edge Cases:**
- Ambiguous description → bounded resolution; on failure, observation + continue.
- Missing value for a `type` action → recorded observation, no silent empty type.
- Malformed model output → same graceful stop path as today.

### REQ-3: The model sees its own trajectory
**User Story:** As the vision loop I want the recent action history and the
no-repeat constraint included in the prompt so that the model does not loop.
**Verified:** `backend/vision/fetch_vision.py:114-175` (`ActionTrajectory`,
`TrajectoryStep`, `window_steps`, no-progress detection) and `:326`
(`trajectory = ActionTrajectory()`) — the trajectory is created and recorded but
its `format_prompt`/window is never passed into `_suggest_action`
(`fetch_vision.py:526-548`).

**Acceptance Criteria:**
- AC1: WHEN the loop requests the next action THEN THE SYSTEM SHALL include the
  recent window of actions (kind, target, outcome, visual delta) in the prompt.
- AC2: THE SYSTEM SHALL include the constraint that a recently-tried,
  no-progress action must not be repeated.
- AC3: THE SYSTEM SHALL record every executed action into the trajectory with its
  outcome and its measured visual delta.
- AC4: IF trajectory formatting fails THEN THE SYSTEM SHALL fall back to the
  un-augmented prompt and never fail the action request.

**Edge Cases:**
- First action (empty window) → prompt is the un-augmented baseline.
- Very long history → only the bounded window is included.

### REQ-4: Progress-based loop termination
**User Story:** As the operator I want the loop to continue while it is making
progress and to stop only when it truly stalls, so a legitimate multi-step page
is not abandoned early.
**Verified:** `backend/vision/fetch_vision.py:325-365` (`repeats` list and the
"repeat itself 3x in a row (stuck in a click loop)" stop),
`backend/vision/fetch_vision.py:70-101` (`visual_delta`),
`backend/vision/fetch_vision.py:143-156` (`_step_is_no_progress`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL compute a perceptual delta between consecutive frames and
  record it per step.
- AC2: THE SYSTEM SHALL stop the loop only after N consecutive actions whose
  measured delta is below the no-progress threshold (or an equivalent
  progress predicate), not on repeated action kinds alone.
- AC3: WHEN an action produces a measurable change THEN THE SYSTEM SHALL reset the
  no-progress counter, even if the action kind repeats the previous one.
- AC4: THE SYSTEM SHALL keep the existing hard bounds (`_MAX_LOOP_STEPS`,
  `SessionBounds.max_actions`, `max_wall_ms`) as an outer limit regardless of the
  progress signal.

**Edge Cases:**
- Undecodable frames → delta treated as "changed" (keep going), per existing
  `visual_delta` contract.
- Rapid identical clicks that DO change the page → not stopped.
- A page that genuinely does not change → stopped within the bound.

### REQ-5: Takeover is wired to the real session
**User Story:** As a user I want the takeover flow to let me clear a wall in the
actual browser session and have the agent resume, so an unsolvable checkpoint
does not abort the task.
**Verified:** `backend/vision/browser_session.py:1070-1095` (takeover wait +
`detect_wall` re-check), `components/iris/browser/BrowserNavigationOverlay.tsx:1774+`
(takeover banner, `pointerEvents: auto`), `hooks/useBrowserNavOverlay.ts`
(`takeover` state), `components/dark-glass-dashboard.tsx` (iframe + view protocol,
`hooks/useViewProtocol.ts`).

**Acceptance Criteria:**
- AC1: WHEN a wall is detected that the agent cannot clear THEN THE SYSTEM SHALL
  raise a takeover request carrying the wall kind and guidance, and SHALL surface
  it to the panel.
- AC2: WHILE a takeover is open THE SYSTEM SHALL allow the user to act on the
  SESSION (not merely a static replay) and SHALL provide an explicit "completed"
  signal.
- AC3: WHEN the takeover completes THEN THE SYSTEM SHALL re-run wall detection and
  resume the loop only if the wall is cleared; otherwise SHALL record the
  unresolved state.
- AC4: IF the takeover is never answered THEN THE SYSTEM SHALL time out and
  degrade without hanging the run.

**Edge Cases:**
- User cannot clear the wall → recorded, not silently retried forever.
- Panel closed mid-takeover → request remains representable / times out cleanly.
- Multiple walls in one session → each is representable.

### REQ-6: One coherent event contract across transports
**User Story:** As the frontend I want every vision/browser event to carry the
same fields on WS and SSE so the panel state never diverges by transport.
**Verified:** `backend/agent/tool_bridge.py:3562-3589` (`_UI_EVENT_DEFAULTS`,
`_crawl_ui_emitter`), `backend/iris_gateway.py:11100-11130` (`_on_progress`,
`CRAWLER_VISION_ACTION` hand-written key tuple), `backend/crawler/ux_map.py:47`,
`hooks/useIRISWebSocket.ts:1600+`, `hooks/useCrawlSSE.ts`,
`backend/tests/contract/test_vision_action_fields_reach_the_panel.py`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define the vision-action payload shape in ONE place and
  both forwarders SHALL forward it whole (no independent hand-maintained key
  tuples).
- AC2: WHEN a producer adds a field (e.g. scroll or viewport) THEN THE SYSTEM SHALL
  carry it end to end without editing a middle allowlist.
- AC3: THE SYSTEM SHALL emit identical `type` values on WS and SSE for the same
  event.
- AC4: THE SYSTEM SHALL include a monotonic sequence number so a dropped or
  reordered event is detectable by the consumer.

**Edge Cases:**
- Missing optional field → consumer degrades, never throws.
- Duplicate delivery → idempotent by sequence number.

### REQ-7: Frontend reflects true session state
**User Story:** As a user I want the panel to show where the session actually is
(scroll, current action, cadence) so the mirror is trustworthy.
**Verified:** `hooks/useBrowserNavOverlay.ts:160-260` (state machine, saccadic
cadence, scroll mirror), `components/dark-glass-dashboard.tsx:646-660`
(sequence-keyed scroll mirror effect), `components/iris/browser/VisionLifecycleChip.tsx`
(`iris:vision_status`).

**Acceptance Criteria:**
- AC1: WHEN the session scrolls THEN THE SYSTEM SHALL mirror the ABSOLUTE scroll
  position keyed by sequence, so the iframe re-anchors on every event.
- AC2: WHEN a vision action occurs THEN THE SYSTEM SHALL update action label,
  step/total, and cursor coordinates without dropping a coordinate when one is
  absent.
- AC3: THE SYSTEM SHALL expose the vision server lifecycle state (cold/spawning/
  warm/error) and SHALL render it truthfully.
- AC4: WHEN a run completes or errors THEN THE SYSTEM SHALL NOT revive the
  animation on a late event.

**Edge Cases:**
- Coordinate absent → keep previous point.
- Late event after complete → ignored.
- No injected view-agent → panel degrades, never throws.

### REQ-8: End-to-end latency instrumentation
**User Story:** As the tuner I want per-stage timing with a run id so I can find
the real bottleneck instead of guessing.
**Verified:** `backend/vision/browser_session.py:72-79` (timeouts),
`backend/vision/fetch_vision.py:500-501` (`duration_ms`), existing telemetry
logging noted in `bootstrap/GOALS.md`. No per-stage breakdown found.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log, per run id, the duration of: browser acquire/open,
  each screenshot capture, each model inference, each action execution, each
  frame publish, and total session.
- AC2: THE SYSTEM SHALL log counts that reveal waste (model calls per page,
  redundant screenshots per settled state, frames published vs skipped).
- AC3: THE SYSTEM SHALL keep instrumentation off the critical path (non-blocking,
  bounded, never raising).
- AC4: THE SYSTEM SHALL make the log consumable by a live measurement script so
  targets are validated against the running system.

**Edge Cases:**
- Instrumentation failure → never fails a session.
- High volume → sampled/bounded.

### REQ-9: Avoid redundant model and capture work
**User Story:** As the operator I want each settled page state observed once so we
do not pay repeated inference for an unchanged frame.
**Verified:** `backend/vision/frame_extraction.py:125-160` (triage-before-extract
loop, scroll walk), `backend/vision/session_vision_adapter.py` (binds session
frames to provider), `backend/vision/fetch_vision.py:526-548`
(`_suggest_action` takes a fresh screenshot each step),
`backend/vision/browser_session.py:1113+` (`_publish_frame` dedupes by structure).

**Acceptance Criteria:**
- AC1: WHEN two consecutive observations are structurally identical THEN THE
  SYSTEM SHALL reuse the prior observation instead of issuing a new inference.
- AC2: THE SYSTEM SHALL share a single captured frame between triage and
  extraction for the same settled state where the contract allows.
- AC3: THE SYSTEM SHALL bound screenshots per settled state (no double capture for
  the same decision).
- AC4: THE SYSTEM SHALL preserve correctness: a changed frame always gets a fresh
  observation.

**Edge Cases:**
- Frame changed → fresh inference.
- Frame unavailable → existing graceful path.
- Triage says challenge → existing challenge handling.

### REQ-10: Observability & tuning signals
**User Story:** As the tuner I want timestamped, run-scoped signals so I can tune
thresholds (no-progress delta, saccadic cadence, micro-settle) from data.
**Verified:** NEW (no dedicated vision-loop tuning signal found).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log, scoped by run id, the no-progress delta per step, the
  termination cause, and the action cadence.
- AC2: THE SYSTEM SHALL log takeover frequency and outcome.
- AC3: THE SYSTEM SHALL keep these signals off the critical path.

**Edge Cases:**
- Missing run id → fall back to job id.
- High volume → bounded.

### REQ-11: Pooled-browser crash self-heal (corpse recovery)
**User Story:** As the operator I want a crashed shared Chromium to recover
automatically so that one bad page (e.g. a login wall) does not poison every
later vision session until a backend restart.
**Verified:** PARTIAL — pool-level detection EXISTS and is tested
(`backend/vision/browser_pool.py:311-332`, pinned by
`backend/tests/contract/test_browser_pool_contract.py:184`
`test_crashed_browser_is_restarted_on_next_acquire`); the SESSION-level
`'NoneType' object has no attribute 'send'` reset+retry exists
(`backend/vision/browser_session.py:486-510`) but has NO contract test. A prior
session's note claiming the pool "never self-heals" is STALE — the code moved on.

**Acceptance Criteria:**
- AC1: WHEN `acquire_browser` finds `_browser` non-None but `is_connected()` is
  False THEN THE SYSTEM SHALL tear down the stale handles and relaunch Chromium
  (one relaunch, not a loop).
- AC2: WHEN `new_context()` raises the corpse signature
  (`'NoneType' object has no attribute 'send'`) THEN THE SYSTEM SHALL force-reset
  the pool, re-acquire, and retry EXACTLY ONCE; any other error propagates.
- AC3: IF the retry also fails THEN THE SYSTEM SHALL mark the session unavailable
  and degrade — never raise into the run (REQ-6 AC1 edge).
- AC4: THE SYSTEM SHALL log corpse detection and self-heal, scoped by job id, so
  recovery frequency is measurable.

**Edge Cases:**
- Chromium missing / launch crash on relaunch → session degrades unavailable.
- Two sessions racing the corpse → single-flight via the pool start lock.
- Playwright not installed → ImportError path unchanged.

### REQ-12: Session cookies from the OS keyring — OWNED ELSEWHERE (cross-spec reference)
**Structural note (audit 2026-09-18):** this entry intentionally omits
`User Story`, `Verified`, `Acceptance Criteria`, and `Edge Cases`. It is NOT a
requirement of this spec — it is a POINTER to the spec that owns it. It carries
ZERO acceptance criteria and contributes ZERO to this spec's traceability count
(the matrix records it as "consumed, not restated"). It holds this number so that
OQ-5 and Decision 9 have a resolvable target.
**This is NOT a new requirement of this spec.** The section exists only so that
Decisions Locked 9 and OQ-5 resolve. The requirement is OWNED by
`specs/vision-goal-directed-search` REQ-12 ("Secure Session & Cookie Injection via
OS Keyring with HAR Redaction", AC12.1/12.2/12.3), and it is already implemented:
`backend/vision/browser_session.py:101-102`
(`_KEYRING_SERVICE = "iris_voice_sessions"`), `_inject_keyring_cookies` at
`:292-331` (its docstring names "REQ-12 AC12.1/12.2"), applied at `:510-512` when
the context is created. Task T8 of that spec is marked `[x]`.

**Why this section exists.** The spec's OQ-5 cited "REQ-12 keyring cookie
injection" while this spec's own list stopped at REQ-11, which read as a dangling
reference. It is not dangling — it points at the SEARCH spec. This spec CONSUMES
that requirement and does not restate its ACs, so this amendment adds ZERO ACs to
the traceability count.

**Consumed ACs (authority: `specs/vision-goal-directed-search`):** AC12.1 (read
the cookie payload for the host from the OS keyring), AC12.2 (inject through
`context.add_cookies`), AC12.3 (HAR redaction of cookie/auth headers).

**Edge Cases (this spec's concern only):** a takeover must not create a second
context, so the injected cookie set is the one the takeover sees (Decision 9).

### REQ-13: Live interactive takeover transport (CDP screencast)
**User Story:** As a user I want to see and drive the REAL session while a wall
blocks the agent so that I can clear the wall in the only browser that can be
cleared, and the agent then continues.
**Verified:** NO CDP code exists in the backend today (searches for
`new_cdp_session`, `startScreencast`, `dispatchMouseEvent`, `dispatchKeyEvent`
return zero hits). The request/answer/verify/resume seam already exists and is
the mount point: `backend/vision/browser_session.py:1017` (`request_takeover`),
`:1067` (threaded wait), `:1073` (answer must be `completed`), `:1080`
(`detect_wall` re-check), `:1090` (post-takeover frame). Caller:
`backend/vision/fetch_vision.py:340-348`. Frontend request path:
`hooks/useIRISWebSocket.ts:1735` -> `iris:browser_takeover_requested` ->
`hooks/useBrowserNavOverlay.ts:277-286`.

**Acceptance Criteria:**
- AC1: WHEN a takeover is requested for a wall other than PAYWALL THEN THE SYSTEM
  SHALL open a CDP session on the SESSION's page and start a screencast that
  streams frames to the panel.
- AC2: THE SYSTEM SHALL acknowledge every delivered frame so the browser
  continues to send, and SHALL bound the in-flight frame count.
- AC3: WHEN the takeover resolves, times out, is cancelled, or the run ends THEN
  THE SYSTEM SHALL stop the screencast, release the CDP session, and return the
  session to the deterministic DOM path.
- AC4: IF CDP is unavailable or the protocol errors THEN THE SYSTEM SHALL degrade
  to the existing replay mirror plus the request/answer path, and SHALL NOT fail
  the run.

**Edge Cases:**
- Page navigates during takeover → screencast is re-attached or stopped, never
  left dangling on a dead page.
- Panel disconnects mid-takeover → screencast stops on the grant timeout.
- A second takeover request while one is open → the open grant is reused or
  cleanly replaced; never two live screencasts on one page.
- PAYWALL → never offers takeover (existing rule, unchanged).
### REQ-14: Takeover input authority
**User Story:** As the operator I want the user's help to be bounded and audited
so that a live input channel into an autonomous browser can never become an
unrestricted remote control, and never leaks a secret into memory or logs.
**Verified:** NEW. No input channel exists today: the panel frame is a sandboxed
opaque-origin replay (`backend/api/browser_surface.py:77-101` isolation headers)
and `hooks/useViewProtocol.ts` validates parent-side messages only. The existing
grant-free path is the answer funnel (`backend/iris_gateway.py:6220-6246`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL forward user pointer and keyboard input to the SESSION
  ONLY while a takeover grant is open, and SHALL reject any input event that
  arrives outside an open grant.
- AC2: THE SYSTEM SHALL bound the grant by start time, wall kind, question id,
  and a max duration, and SHALL log grant open and close with the run id.
- AC3: THE SYSTEM SHALL restrict forwarded input to page-level events (pointer,
  wheel, key, text). It SHALL NOT accept browser-level or navigation commands
  from the input channel.
- AC4: THE SYSTEM SHALL treat a user-typed value as ephemeral. It SHALL NOT write
  it to memory, the ledger, the event stream, or a log, and SHALL NOT echo it back
  inside a frame event.
- AC5 (ADDED 2026-09-18, OQ-12): WHEN a login wall needs a stored secret THEN THE
  SYSTEM SHALL be able to apply that secret from the OS keyring to a session field
  under an open grant — the agent USES the secret without SEEING it. The value
  SHALL NOT enter the model context, memory, the ledger, the event stream, or any
  log, and the frame stream SHALL show only the page's own rendering.
- AC6 (ADDED 2026-09-18, OQ-12): THE SYSTEM SHALL require explicit user
  authorisation before applying a stored secret, and SHALL record that
  authorisation (grant id + a secret REFERENCE id) with no value attached, so the
  action is auditable without the secret being recoverable from the record.

**Edge Cases:**
- No keyring entry for the host → the wall is surfaced as a takeover for the user
  to solve by hand; never a silent failure and never a guessed credential.
- More than one stored secret for a host → the system asks which to use; it never
  tries several, because repeated failed logins can lock the account.
- User declines the authorisation → no application, no retry, wall stays parked.
- Secret entry exists but the page has no matching field → recorded as an
  unresolvable wall; nothing is typed anywhere else (no blind field filling).
- Input arrives after the grant closes → rejected and counted, never applied.
- A key or button outside the allowlist → dropped, logged by kind only.
- Two panels attached → the grant binds to the session and the question id, not
  to a socket, so only the owning panel's input is applied.
- Malformed input event → dropped, no raise.

### REQ-15: Loop suspension and ownership handoff
**User Story:** As the operator I want exactly one owner of the page at any
instant so that the agent never fights the user for the same page, and the loop
resumes only after a verified clear.
**Verified:** PARTIAL — the handoff exists but is implicit. `request_takeover` is
awaited INLINE inside the action loop (`backend/vision/fetch_vision.py:340-348`),
which does suspend the loop by construction, and `browser_session.py:1080`
already re-checks the wall before resuming. No explicit ownership record, no
grant lifecycle, and no suspension contract exist.

**Acceptance Criteria:**
- AC1: WHILE a takeover grant is open THE SYSTEM SHALL suspend the vision action
  loop, so no model call and no DOM action occurs on that session.
- AC2: WHEN the takeover completes THEN THE SYSTEM SHALL re-run wall detection on
  the SESSION and SHALL resume the loop only if no wall remains (REQ-5 AC3
  semantics, unchanged).
- AC3: IF the grant times out, the panel closes, or the run is cancelled THEN THE
  SYSTEM SHALL release the grant, stop the screencast, record the unresolved
  state, and park or degrade within the existing bounds — never hang.
- AC4: THE SYSTEM SHALL record each ownership handoff (agent→user, user→agent)
  scoped by run id, and SHALL ensure at most one owner holds the page.
- AC5 (ADDED 2026-09-18, OQ-13): WHEN a completed takeover has produced session
  cookies that would be useful on a later run THEN THE SYSTEM SHALL persist them
  ONLY through an explicit CONSENT AFFORDANCE. Without that consent the new
  cookies die with the context. The affordance SHALL name the host and what will
  be stored, and SHALL be revocable.
- AC6 (ADDED 2026-09-18, OQ-16): WHEN the user navigates away from the target
  domain during a takeover THEN THE SYSTEM SHALL continue from the page the user
  left it on — it SHALL NOT auto-park on a domain change — and SHALL re-evaluate
  the task guardrails against that page. WHEN a guardrail would block and the
  agent cannot determine a safe continuation THEN THE SYSTEM SHALL ask the user
  through `AskUserQuestion` rather than silently parking or silently proceeding.

**Edge Cases:**
- Wall survives the handoff → unresolved, recorded, no silent retry loop.
- Cancellation mid-takeover → screencast stopped, CDP session released, browser
  context closed, vision lease released; no orphan Chromium.
- Takeover requested for a page that has already navigated → re-detect first,
  offer only if a wall is still present.

### REQ-16: Screencast frame stream contract
**User Story:** As the frontend I want one bounded frame contract so the live
takeover view stays ordered, cheap under load, and clearly separate from the
vision-action event stream.
**Verified:** NEW. The canonical vision-action shape lives in
`backend/agent/tool_bridge.py:3562-3589` (`_UI_EVENT_DEFAULTS`), and the WS path
carries JSON (`hooks/useIRISWebSocket.ts`). No binary or continuous frame
transport exists.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL emit each screencast frame with one canonical envelope:
  `{run_id, question_id, seq, frame_seq, ts, viewport_w, viewport_h, format,
  bytes}`.
- AC2: THE SYSTEM SHALL carry frames on the WS channel only, and SHALL NOT route
  them through the capture-store slot design or the `CRAWLER_VISION_ACTION`
  shape.
- AC3: THE SYSTEM SHALL bound delivery: under backpressure it SHALL drop frames
  latest-wins rather than queue without limit, and SHALL report a dropped count.
- AC4: THE SYSTEM SHALL use a monotonic per-takeover sequence so the renderer
  detects a gap and re-anchors, consistent with REQ-6 AC4.

**Edge Cases:**
- Panel slower than the frame rate → latest-wins drop, no unbounded queue.
- `question_id` missing → frame is dropped (a frame without an owner is
  unattributable).
- Frame payload undecodable on the client → renderer keeps the last good frame
  and reports the gap; it never throws.
- Takeover ends → no frame is emitted after the terminal event for that
  `question_id`.

### REQ-17: Agent-driveable verification harness
**User Story:** As an agent (or a tuner) I want to drive a full vision run
deterministically and read exactly which events it emitted so that I can prove
the loop, the contracts, and the takeover myself — with no network, no external
model, and no human.
**Verified:** REAL GAP (2026-09-17). The instruments exist but the vision path has
none of them wired: 25 `scripts/validate_*` harnesses exist
(`validate_der_cli_harness.py` is the drive pattern), and a frame recorder exists
(`scripts/validate_websearch_trajectory.py` + `tests/traces/*.json`, schema v1,
redacted) — but those traces contain **ZERO vision events** (grep for
`CRAWLER_VISION_ACTION`/`crawler_vision_action` returns no hits), so T13's "reuse
recorded trajectories" has no corpus. The deterministic overlay driver is GONE:
`app/dev/vision-stage` does not exist (`specs/vision-browser-stage` REQ-12 reads
"SATISFIED, THEN REMOVED"). Steps 6–9 of the verification plan are manual.
Evidence: `pin_207db7c880dd`.

**Acceptance Criteria:**
- AC1: WHEN the harness runs THEN THE SYSTEM SHALL serve deterministic fixture
  pages over loopback HTTP (including one page carrying a wall), so the action
  loop, the wall path, and the takeover path run with NO network access and NO
  external model.
- AC2: THE SYSTEM SHALL write every emitted vision, frame, and grant event of a
  run to ONE run-scoped, machine-readable journal (JSON Lines), bounded in size,
  with the run id recorded first, so an agent can diff the emitted sequence
  against the contract.
- AC3: THE SYSTEM SHALL be able to RECORD a trajectory from a real or fixture run
  and REPLAY it through the standing harness, so contract and behavioral
  assertions run on every invocation.
- AC4: WHEN a contract or behavioral assertion fails THEN the harness SHALL exit
  non-zero and name the offending invariant, so the gate is usable without a
  human reading log lines.

**Edge Cases:**
- No network available → fixture steps still run; live steps are reported SKIPPED.
- No journal writable (read-only disk) → the run proceeds; the harness reports
  the journal as unavailable rather than failing the run.
- Journal grows unbounded on a long session → bounded by a max-lines/max-bytes
  cap with an explicit truncation marker.
- Fixture port already in use → the harness picks another port and reports it.

### REQ-18: Browser warm-path bound and cold-launch accounting
**User Story:** As the operator I want the browser hot path bounded and truthful
so that a cold launch is a measured, announced cost instead of an unexplained
freeze that eats the session budget.
**Verified:** CONFIRMED DEFECT (2026-09-17). The dominant cost is the COLD
Chromium launch: `browser_session.py:395-425` logged
"browser acquired in 32918ms (cold pool)" (`pin_000d74279a82`), and a prior run
died at `elapsed_ms=76495 vs max_ms=30000` — killed before ONE url. The pool
defaults to a 60s idle grace with `IRIS_BROWSER_HOLD_OPEN` defaulting to `"0"`
(`browser_pool.py:54-59`), so a cold start after 60s idle pays the full launch
again. `test_browser_pool_contract.py:251-293` pins the idle/LEASE semantics,
but the plan-time prewarm at `backend/crawler/orchestrator.py:1779` has NO test. REQ-8 AC1
measures acquire; nothing bounds its behaviour. Evidence: `pin_207db7c880dd`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL record, per run id, the browser acquire duration AND
  whether the acquire was a COLD launch or a WARM reuse, so the split is visible
  without re-measuring.
- AC2: WHILE a run has declared that it needs the browser THEN THE SYSTEM SHALL
  hold the pool warm for that run, so the pool's idle-stop SHALL NOT fire between
  two URLs of the same run (a cold launch is paid at most once per run where a
  warm pool was achievable).
- AC3: WHEN a cold launch occurs THEN THE SYSTEM SHALL announce it on the
  existing lifecycle/status channel and SHALL NOT charge the launch against the
  session's action budget or `max_actions`.
- AC4: THE SYSTEM SHALL bound the acquire with an explicit timeout and SHALL fail
  open — a wedged launch degrades the session to unavailable and never pins the
  run or the pool start lock.

**Edge Cases:**
- Pool held by another run's lease → this run waits bounded, then degrades.
- Chromium missing entirely → ImportError path unchanged; session unavailable.
- Idle-stop fires mid-run because nothing declared intent → recorded as a COLD
  acquire with the reason, so the accounting shows who should have declared.
- The latency NUMBER stays UNVERIFIED until the step-10 baseline (Decision 13).

## Non-Requirements (Out of Scope)

- Replacing Playwright or the Chromium pool.
- Making the sandboxed iframe itself same-origin or scriptable (isolation is
  load-bearing). A screencast does NOT change this: frames arrive as image data
  and input leaves as protocol events, so the frame stays opaque-origin.
- Launching the OS browser from any agent-initiated path. The user-initiated
  "open externally" control (`components/dark-glass-dashboard.tsx:2329`) remains
  the only path by which an agent-touched URL reaches the OS browser, per
  `specs/long-horizon-der-execution` REQ-16 AC4.
- Solving CAPTCHAs (detection + takeover only).
- Changing the capture slot-stride address design.
- Archiving or replaying the screencast stream after the takeover ends. The
  stream is a live view, not a recording.
- Any target latency NUMBER stated as fact without a live baseline (targets are
  UNVERIFIED pending REQ-8 measurement).

## Open Questions

These are deferred, non-blocking for Wave 1 but **BLOCKING** for the wave noted.
Resolve WITH the owner; on resolution move to Decisions Locked and run the
Amendment Protocol (triplet rule).

RESOLVED (moved to Decisions Locked 2026-09-17 — do not re-litigate):
- OQ-1 → Decisions Locked 7. Takeover uses a CDP screencast with input forwarding
  INTO the agent's own context. "Open the real browser" is rejected on arithmetic
  grounds (it cannot reach REQ-5 AC3). Evidence: `pin_b6d4658a903c`.
- OQ-4 → Decisions Locked 8. The resume signal is the EXISTING `question_response`
  funnel. No new WS command. The wall clears only through detection re-check.
- OQ-5 → Decisions Locked 9 + REQ-12. ONE shared context per run; cookies come
  from the OS keyring at context creation.
- OQ-9 partial → Decisions Locked 10/11 cover the ownership and stream split.
- OQ-14 (was BLOCKING T17/T19) → RESOLVED 2026-09-17, owner-authorised. The owner
  amends `specs/vision-browser-stage` REQ-14 (AC1/AC2 narrowed to a grant-scoped
  exception, plus ADDED AC4/AC5), its Decisions Locked 8, and its read-only
  Non-Requirement; the narrowed guards CT-6b/CT-7b are owned THERE as that spec's
  **T25** and live in a NEW file
  (`backend/tests/contract/test_takeover_input_authority_contract.py`).
  CT-6/CT-7 stay UNMODIFIED — the amendment adds guards, never relaxes one.
  Evidence: `pin_54db2ac956a0`.

RESOLVED 2026-09-18 (owner answers, session-338). The entries below are kept as the
QUESTION RECORD. Each answer is written into Decisions Locked 14–17, REQ-14
AC5/AC6, and REQ-15 AC5/AC6. Do not re-litigate:
**READ THIS FIRST:** the "(BLOCKS Tn)" wording that appears INSIDE the entries
below is the ORIGINAL ASKED-FORM and is SUPERSEDED. Nothing below blocks anything.
Every entry is answered in the list that follows, and the answers are the
authority. Do not start work on the basis of a "(BLOCKS ...)" note in this
archive — it is history, not status.
- OQ-2 → Decision 14 (explicit tier ladder: cloud vision, then local vision choice,
  then a warm borrowed server, else unavailable).
- OQ-3 → T4/REQ-8: separate budgets; a model-call budget is added.
- OQ-6 → `(run_id, seq)` approved.
- OQ-7 → Decision 16 (nothing is verified until the content is digested as safe,
  non-malicious, and credible).
- OQ-8 → approved: the hand-written key tuple in `iris_gateway._on_progress` is
  replaced by whole-payload forwarding.
- OQ-9 → one sequential mirror.
- OQ-10 → base64, one message per frame.
- OQ-11 → ack-paced, latest-wins, quality 60, ≤2 fps.
- OQ-12 → REQ-14 AC5/AC6: the agent USES a secret without seeing it.
- OQ-13 → REQ-15 AC5: persist only through a revocable consent affordance.
- OQ-15 → option (a): the scan fades; no new shutter state.
- OQ-16 → REQ-15 AC6: keep fetching, re-evaluate, ask when unsure.
- OQ-17 → a LIVE marker replaces the capture badge while the grant is open.
- OQ-18 → Decision 17: the scan runs in DEVELOPER MODE only.
- OQ-19 → Decision 15: the spawn-and-wait path is REMOVED for the browser path.
- OQ-2: Is a bound multimodal brain (tier 1) acceptable for browser-vision by
  default, or should browser-vision prefer the local VL tier for privacy? Note the
  real consequence: tier 1 sends page pixels to a cloud provider.
- OQ-3: What is the acceptable cost ceiling per page, and are model calls counted
  separately from DOM actions (`max_actions` / `max_extractions` / a new
  `max_inferences`)? (BLOCKS T4's counter design.)
- OQ-6: Is a monotonic `seq` acceptable on the `CRAWLER_VISION_ACTION` contract
  for dedupe/ordering across WS + SSE, and is the dedupe key `(run_id, seq)`
  rather than `seq` alone? (BLOCKS T3 and REQ-16 AC4.)
- OQ-7: What are the owner's ceiling numbers (per-action, per-URL) — the values
  that make the run "too slow"? Targets stay UNVERIFIED until step 8 measures.
- OQ-8: May this spec modify the shared `iris_gateway._on_progress` forwarder, or
  must the fix be producer-side only? (BLOCKS T3.)
- OQ-9: For a multi-URL escalation, does the panel show one sequential browser
  mirror or several? Is parallel vision browsing wanted (VRAM/GPU contention)?
- OQ-10 (NEW, BLOCKS T16): Frame encoding on the WS channel — raw binary frames or
  base64 in the JSON envelope? Binary needs a binary branch in
  `hooks/useIRISWebSocket.ts`; base64 costs ~33% more bytes but no transport
  change.
- OQ-11 (NEW, BLOCKS T15): Frame rate and quality ceiling for the screencast
  (`Page.startScreencast` quality / maxWidth / maxHeight / everyNthFrame), and the
  in-flight frame bound.
- OQ-12 (NEW, BLOCKS T17): Does a value the user types during takeover ever enter
  memory or the ledger? REQ-14 AC4 says no. Confirm, because the credential-request
  path stores some user-provided values elsewhere.
- OQ-13 (NEW, BLOCKS T18): After a successful takeover, should the session's new
  cookies be written back to the OS keyring? Convenient for later runs, but it
  writes a session token to the keyring without an explicit consent step.
  (Design D13 proposes NO writeback in v1.)
- OQ-15 (NEW, BLOCKS T16): Does the takeover get a distinct shutter/eye state?
  `specs/vision-browser-stage` REQ-8 drives blink/scan/notice from
  `crawler_vision_action` events, and its own edge case says the scan fades when
  action events stop — which is exactly what a takeover causes. Options:
  (a) let it fade to plain shutter cadence (NO CHANGE); (b) add a held-open
  "hands on the wheel" state for the grant's duration.
- OQ-16 (NEW, BLOCKS T18): When the user navigates during a takeover, does the
  post-takeover page still satisfy the agent's task guardrails (`DOMAIN_BOUND`)?
  The user can leave the target domain, and the loop would resume there and keep
  acting. Options: (a) re-evaluate `TaskGuardrails` on resume and park if violated;
  (b) treat a user-navigated page as the new target; (c) restore the pre-takeover
  URL on resume.
- OQ-17 (NEW, BLOCKS T16): What replaces the capture badge (job id + fetch time)
  while the reading surface shows LIVE frames? The badge currently implies a stored
  capture address, which a live frame is not (REQ-16 AC2).
- OQ-18 (NEW, BLOCKS T1): What is the AST bypass scan's SCOPE RULE? The scan must
  separate VISION SERVING (must go through the resolver) from LIFECYCLE CONTROL and
  HEALTH (must talk to tier 3 directly). Verified direct tier-3 sites:
  `backend/tools/vision_mcp_server.py:49-50` (the whole `vision.*` MCP tool family — is
  this a serving bypass to FIX, or a legitimate dedicated vision server to
  ALLOW?), `backend/iris_gateway.py:10907-10909` (vision_status lifecycle SEED),
  `backend/iris_gateway.py:10972-10976` (`set_vision_enabled` — the user toggle that starts
  and stops the tier-3 server; this one MUST keep constructing tier 3 directly),
  `inference_router.py:318-319` (health_check). Options: (a) explicit allowlist of
  the lifecycle/health sites + scan the rest of `backend/`; (b) scan
  `backend/vision/` + the MCP vision server only; (c) scan all of `backend/` with
  inline exemptions. Note the scan must NOT be widened without this rule, or it
  fails on legitimate code and gets disabled. Evidence: `pin_83640fb0e27b`.
- OQ-19 (NEW, BLOCKS T1/T20 — owner clarification 2026-09-17): For the BROWSER
  path, what is the tier-3 PREFERENCE ORDER? The owner states the tier-3 server is
  the same `llama-server` the auto-loader uses for a local model, and it exists for
  when the brain/tool model has no sight. The code already prefers an
  already-running multimodal server over spawning (`lfm_vl_provider.py:71-99`),
  gated on a real multimodal round trip, and never kills a server it did not start.
  Questions to settle: (a) confirm BORROW-FIRST as the browser path's rule, with
  spawn-own only as the last resort; (b) may the browser path borrow a CLOUD
  endpoint (the reuse discovery can select another configured provider with an API
  key — a METERED endpoint), or must the browser path stay local-only; (c) should
  the browser path's acquisition wait for a spawn at all, or park the URL and
  resume when the server is warm? The spawn-own cost is minutes and highly
  variable (ttr_sec=370+; samples 3.87s → >100s). (d) confirm that a borrowed
  server is NEVER idle-stopped by vision, so the user's auto-loaded local model is
  never unloaded (already implemented via `_stop_owned_vision_server` + a borrowed
  server holding no PID).

## Still Open

NONE. Every open question this spec raised is RESOLVED as of 2026-09-18.

- OQ-20 (was: cloud vs an explicit local vision choice when both are bound) →
  RESOLVED 2026-09-18 (owner, option (a)): **CLOUD WINS** whenever the brain has
  vision; the local vision model is the fallback. Recorded in Decision 14 as the
  PRECEDENCE rule, so the order is a contract and not an artefact of iteration
  order (`backend/agent/inference/router.py:698-724`). The privacy consequence — page pixels leaving the
  machine when the brain has sight — is accepted by the owner and is reversible by
  a future toggle if wanted.

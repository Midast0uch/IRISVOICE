# Requirements: Vision-Driven Interactive Browser Websearch

## Decisions Locked

These were resolved with the user on 2026-08-10. Do not re-litigate them.

1. **Architecture: server-side Playwright, iframe mirrors it.** The real browser is a
   persistent Chromium session on the backend. The frontend iframe is a *view* of that
   session, not the session itself. Rejected: driving the existing proxied iframe via an
   extended `view_agent` postMessage protocol — the iframe is sandboxed **without**
   `allow-same-origin` (backend/api/browser_surface.py), so neither the parent page nor
   the backend can read its pixels or DOM. Vision would be blind. That sandbox decision
   is load-bearing and stays.
2. **Engagement: escalation, not replacement.** Plain crawl remains the fast path. Vision
   engages when crawl yields nothing usable. Cheap queries must not pay vision latency.
3. **Shape: modular DAG nodes, not a linear ladder.** `fetch.crawl` and `fetch.vision`
   are interchangeable DER node types over one interface. Traversal is per-URL, may run
   in parallel across URLs, and is reversible (`crawl → vision → crawl` is normal, not a
   fallback). Vision's common job is to *settle* a page and hand the DOM back to crawl.
4. **Racing policy.** Parallelise across URLs always. Race both capabilities on the *same*
   URL only when that domain has failed before (source_registry has the history).
5. **Wall policy: autonomous first, ask without blocking.** On a wall vision cannot pass,
   the agent moves to another source immediately. It also raises a question card, but
   **does not wait**. If an answer arrives later — by card click *or* by voice — the
   parked source is resumed. The run is never blocked on the human.
6. **Voice answering is a featured option, not an accident.** The user must be able to
   answer a pending question card by speaking after the wake word.
7. **The existing websearch animations are as important as the search itself.** No
   redesign of the browser panel visuals. Vision's involvement adds signal to the existing
   animation surface; it does not replace it.
8. **Websearch survives component unmount.** The task continues while only
   `components/iris/XurOrb.tsx` is visible. Closing the dashboard wing must not stop,
   pause, or lose the run.
9. **Vision is a content source, not only a navigator.** LFM2.5-VL reads frames as it
   scrolls and its extraction is reconciled against crawl content rather than either being
   discarded (REQ-17). Triage-then-extract keeps the cost bounded.
10. **The existing persistence spine is preserved and joined, not replaced.** HAR entries,
    the document store, and pacman fragmentation are live consumers with real downstream
    effects — source penalties, document rehydration, and trust-zoned memory. The vision
    path writes into the same stores with its own provenance (REQ-18). Deleting or
    bypassing any of them is explicitly out of scope.

## Introduction

IRIS websearch currently fails silently. Crawls that retrieve nothing are reported as
successes, the answer is written from model knowledge and presented as researched, and
the two mechanisms built to recover from a bad fetch never fire. This feature makes the
fetch path honest, adds a vision-driven interactive browser session as a second fetch
capability for pages plain crawling cannot reach, and makes the whole run survive the UI
being closed.

### Success criteria

- A crawl that retrieves zero usable content never reports `success=True`, and the answer
  built from it is never presented as sourced.
- The broaden-and-retry path fires at least once on a run where every page is unusable.
  Baseline: it has fired **0 times** in 401MB of history.
- A Cloudflare/Turnstile interstitial reached by the *primary* crawl path is labelled as a
  challenge, not extracted as content.
- A page that plain crawl cannot read, but a human could read in a browser, is retrieved
  by the vision capability.
- Closing the dashboard wing mid-websearch loses no events and no progress; reopening it
  shows the run's current state.
- A pending question card can be answered by voice after the wake word.

## Requirements

### REQ-1: One shared definition of a usable page

**User Story:** As the fetch pipeline I want a single predicate for "this page is usable"
so that every layer agrees on whether a fetch succeeded.

**Verified:** Three layers disagree today. `backend/crawler/crawl_runner.py:347` uses
`if p.markdown`; `backend/crawler/orchestrator.py:204` uses `if not p.error`;
`backend/crawler/rerank.py:141-146` uses a 0.30 score threshold. On the traced Palworld
run these returned 0, 2, and 0 usable pages respectively for the same fetch.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL expose exactly one `page_is_usable(page)` predicate in a single
  module, and every layer that judges fetch success SHALL call it.
- AC2: THE SYSTEM SHALL classify a page as unusable WHEN its markdown is empty, its
  markdown is below a minimum content length, or it is a bot-challenge interstitial.
- AC3: THE SYSTEM SHALL treat `error is None` as insufficient evidence of usability on
  its own.
- AC4: WHEN a page is judged unusable THEN THE SYSTEM SHALL record the specific reason
  (empty / too-short / challenge / transport-error) on the page record.

**Edge Cases:**
- Page with whitespace-only markdown → unusable (`too-short`), not usable.
- Page with markdown consisting solely of challenge boilerplate → `challenge`, not
  `too-short`; the distinction drives different recovery.
- Minimum content length must not reject legitimately short pages (definitions, stubs);
  the threshold is tunable and instrumented under REQ-16.

### REQ-2: The broaden-and-retry gate reads the shared predicate

**User Story:** As a user whose first three URLs were all dead I want the system to
broaden the query and try again so that I get an answer instead of a shrug.

**Verified:** The retry exists at `backend/crawler/orchestrator.py:205-225` and is
correct. Its gate at `:204` is not: `ok_pages = [p for p in fetched.pages if not p.error]`
counted 2 empty-markdown fallback pages as successes, so the gate never opened.
`grep -c "Exa retry" logs/iris.log` = **0** across 401MB.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL gate the broaden-and-retry path on `page_is_usable` (REQ-1), not
  on `error is None`.
- AC2: WHEN no fetched page is usable THEN THE SYSTEM SHALL broaden the query and re-run
  Plan→Fetch exactly once.
- AC3: WHILE a retry is in progress THE SYSTEM SHALL emit a progress event describing it.
- AC4: THE SYSTEM SHALL NOT retry more than once per research call.

**Edge Cases:**
- Broadened plan returns zero URLs → do not retry, proceed to the unusable path (REQ-15).
- Retry also returns nothing usable → escalate to vision (REQ-6) if enabled, else REQ-15.

### REQ-3: The rerank re-query signal is acted on

**User Story:** As the fetch pipeline I want a below-threshold rerank result to trigger
recovery so that the signal is not computed and discarded.

**Verified:** `backend/crawler/rerank.py:141-146` returns `[]` with the comment
`# empty => orchestrator should re-query (handled at call site)`. The call site,
`backend/crawler/orchestrator.py:250`, assigns the result and falls through to
`extract_and_cite` at `:257`. It is **not** handled at the call site. The traced run
logged `top score 0.000 below threshold 0.300 -> prefer re-query` one second before
`CRAWLER_COMPLETE`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL distinguish "no passages produced" from "passages produced but
  all below threshold" as separate return states from rerank.
- AC2: WHEN rerank signals re-query preference THEN THE SYSTEM SHALL escalate rather than
  proceed to citation with empty passages.
- AC3: THE SYSTEM SHALL NOT call `extract_and_cite` with an empty passage set and treat
  its output as sourced content.

**Edge Cases:**
- Rerank returns empty because the page set was empty → already covered by REQ-2; do not
  double-escalate.
- Escalation budget exhausted → REQ-15 honest failure.

### REQ-4: Challenge detection on the primary fetch path

**User Story:** As the tuner I want bot walls detected wherever they occur so that I can
measure how much they actually cost us.

**Verified:** `_is_challenge_page()` at `backend/crawler/crawl_runner.py:453` correctly
detects Cloudflare/Turnstile including the "Just a moment…" marker. It has **exactly one
caller**, at `:515`, inside the plain-HTTP fallback. `grep -c "challenge"
backend/crawler/crawler_engine.py` = **0** — the primary Playwright path has no detection
at all. Measured consequence: 2 labelled challenges vs 136 timeouts across 401MB, an
undercount by construction.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL apply challenge detection to content retrieved by the primary
  Playwright/crawl4ai path, not only the plain-HTTP fallback.
- AC2: WHEN a challenge interstitial is detected THEN THE SYSTEM SHALL mark the page
  unusable with reason `challenge` and SHALL NOT persist it to the capture store.
- AC3: WHEN a challenge is detected THEN THE SYSTEM SHALL log the URL, status, and
  detection marker so challenge frequency is measurable per domain.
- AC4: IF a fetch times out on a domain previously seen serving challenges THEN THE
  SYSTEM SHALL record the timeout as challenge-suspected, so the two buckets can be
  reconciled.

**Edge Cases:**
- Legitimate page containing the phrase "just a moment" in body text → detection must key
  on structural markers (challenge-platform script, challenge-form), not prose alone.
- Challenge detected on the retry attempt as well → escalate to vision (REQ-6).

### REQ-5: Bot-challenge mitigation on the crawl path

**User Story:** As a user I want routine public pages to be readable so that a soft bot
wall does not cost a whole search.

**Verified:** Mitigation today is a 3-entry UA rotation pool
(`backend/crawler/crawler_engine.py:36-70`). `_STEALTH_EXTRA_HEADERS` is defined at `:50`
and the comment at `:48` states it is deliberately **not** passed to crawl4ai. No cookie
persistence, no timing jitter, no stealth patches.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL send a coherent header set with each request such that
  `User-Agent`, `Accept-Language`, `Sec-CH-UA` and related headers are mutually
  consistent for the advertised browser.
- AC2: THE SYSTEM SHALL persist cookies per domain across requests within a research run
  so that consent and session cookies set on the first request apply to later ones.
- AC3: THE SYSTEM SHALL continue to honour `robots.txt` via the existing
  `backend/crawler/robots_checker.py`, and this requirement SHALL NOT weaken it.
- AC4: THE SYSTEM SHALL apply randomised inter-request delay per domain rather than
  issuing requests at a fixed machine cadence.
- AC5: IF mitigation fails and the page is still challenged THEN THE SYSTEM SHALL escalate
  to vision (REQ-6) rather than retrying the same approach.

**Edge Cases:**
- A domain that sets a cookie jar too large or malformed → cap and discard, never fail the
  fetch.
- Cookie persistence must be scoped to the research run and must not leak user credentials
  or cross-run identity; see Non-Requirements.

### REQ-6: Fetch capability interface with two implementations

**User Story:** As the DER planner I want fetch capabilities to be interchangeable nodes
so that the execution graph can choose, combine, and reverse between them.

**Verified:** NEW (unverified — implementation pending). Existing DER node/edge machinery
that this must reuse: node records stamped in `_der_finalize_step`
(`backend/agent/agent_kernel.py`, per pin `pin_6388302d760e`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define one fetch capability interface taking `(url, goal)` and
  returning page evidence plus a usability verdict from REQ-1.
- AC2: THE SYSTEM SHALL provide two implementations — `fetch.crawl` (headless, no vision)
  and `fetch.vision` (interactive browser session, REQ-7).
- AC3: THE SYSTEM SHALL register both as DER node types so traversal, records, and edges
  use the existing DER machinery rather than a parallel execution model.
- AC4: THE SYSTEM SHALL allow a URL to be re-dispatched to a different capability without
  restarting the research run.
- AC5: WHEN `fetch.vision` settles a page THEN THE SYSTEM SHALL permit handing the settled
  DOM back to `fetch.crawl` for extraction.

**Edge Cases:**
- Capability unavailable (vision server absent, Playwright missing) → the node reports
  unavailable and the graph proceeds with the remaining capability; never raises.
- Both capabilities unusable for every URL → REQ-15.

### REQ-7: Vision-driven interactive browser session

**User Story:** As a user I want the agent to actually operate a browser — scroll, click,
dismiss, type — so that pages requiring interaction can be read.

**Verified:** NEW. Vision provider exists at `backend/tools/lfm_vl_provider.py`
(LFM2.5-VL on llama-server:8081). Playwright/Chromium already present via crawl4ai
(`backend/crawler/crawler_engine.py:165-195`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL maintain a server-side browser session that persists across
  multiple actions within one research run.
- AC2: THE SYSTEM SHALL provide the vision capability with navigate, reload, back,
  forward, scroll, click, type, and wait actions against that session.
- AC3: WHEN the vision model is asked to act THEN THE SYSTEM SHALL supply it with a
  current frame of the browser session and SHALL act only on the returned action.
- AC4: THE SYSTEM SHALL bound a vision session by a maximum action count and a maximum
  wall-clock duration, both configurable.
- AC5: WHEN the goal is satisfied or the bound is reached THEN THE SYSTEM SHALL close the
  session and release its resources.
- AC6: IF an action fails THEN THE SYSTEM SHALL report the failure to the vision model as
  observation rather than aborting the session.

**Edge Cases:**
- Page navigates away mid-action → re-capture before the next decision, never act on a
  stale frame.
- Infinite scroll → the action bound is the stop condition.
- Session crash → the node reports unusable; the run continues with other URLs.

### REQ-8: Vision server lifecycle and session lease

**User Story:** As the agent I want the vision server started and stopped gracefully, and
held open exactly as long as I need it, so that a long interactive session is not killed
mid-flight.

**Verified:** Lifecycle largely exists — auto-start when unreachable
(`backend/tools/lfm_vl_provider.py:221-296`), idle auto-stop via watchdog at `:99-107`,
`_IDLE_TIMEOUT` default 120s at `:41`, PID-tracked so only IRIS-spawned servers are
stopped (`:30-31`, `:79-94`), and `set_vision_idle_callback` at `:49` for status
broadcast. The gap is the absence of an explicit lease.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide an explicit lease that prevents the idle watchdog from
  stopping the vision server while at least one lease is held.
- AC2: WHEN the last lease is released THEN THE SYSTEM SHALL resume normal idle-timeout
  behaviour.
- AC3: THE SYSTEM SHALL release a lease even when the holding session fails or raises.
- AC4: THE SYSTEM SHALL NOT stop a vision server it did not start.
- AC5: WHEN the vision server is starting THEN THE SYSTEM SHALL surface a startup state to
  the UI rather than appearing idle.
- AC6: IF the vision server cannot start THEN THE SYSTEM SHALL report the vision capability
  unavailable (REQ-6 AC1 edge) and SHALL NOT fail the research run.

**Edge Cases:**
- Lease held by a crashed session → leases carry a hard expiry so they cannot leak forever.
- Two concurrent research runs → leases are counted, not boolean.

### REQ-9: Vision input scoped to the browser session

**User Story:** As the user I want the vision model looking at the browser session and
nothing else, so that websearch never reads my desktop.

**Verified:** `screenshot_to_bytes()` at `backend/tools/lfm_vl_provider.py:298` captures
the **desktop screen**, optionally by region. There is no browser-scoped capture path.

**Acceptance Criteria:**
- AC1: WHILE performing websearch THE SYSTEM SHALL supply the vision model with frames
  captured from the browser session only.
- AC2: THE SYSTEM SHALL NOT use desktop screen capture for any websearch vision call.
- AC3: THE SYSTEM SHALL capture browser frames irrespective of whether any frontend
  component is mounted or visible.
- AC4: THE SYSTEM SHALL keep the existing desktop-capture vision tools unchanged for their
  current non-websearch callers.

**Edge Cases:**
- Browser session not yet started when a frame is requested → return unavailable, do not
  silently fall back to desktop capture.

### REQ-10: Parallel and reversible traversal

**User Story:** As a user I want the search to be fast, so that using vision on one
stubborn source does not stall the others.

**Verified:** NEW.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL fetch distinct URLs concurrently, up to a configurable limit.
- AC2: THE SYSTEM SHALL allow different URLs in one run to be in different capabilities
  simultaneously.
- AC3: WHERE a domain has prior recorded failures THE SYSTEM SHALL be permitted to run
  both capabilities against that URL concurrently and take the first usable result.
- AC4: THE SYSTEM SHALL NOT race both capabilities on a domain with no failure history.
- AC5: WHEN one capability returns a usable result for a raced URL THEN THE SYSTEM SHALL
  cancel the other and release its resources.

**Edge Cases:**
- Concurrency limit reached → queue, do not drop URLs silently (REQ-16 logs any deferral).
- Both raced capabilities return usable results → prefer the crawl result (cheaper to
  extract), record that the race was unnecessary for tuning.

### REQ-11: Live iframe mirror preserving the existing animation surface

**User Story:** As a user I want to watch the agent work in the browser panel, with the
animations I already have, so that the search feels alive rather than opaque.

**Verified:** Panel content is served by `backend/api/browser_surface.py` —
`/api/browser/capture/{job_id}/{page_number}` for replay and `/api/browser/proxy?url=`
for live. Frames are stored via `backend/crawler/capture_store.py` (`save`/`load`/`has`).
Frontend animation and tab state live inline in `components/dark-glass-dashboard.tsx`
(listeners at `:628`, `:797`, `:1026-1029`). Observed failure: `[browser-surface] capture
unavailable job=… page=2` repeated through the traced run — the panel had nothing to show.

**Acceptance Criteria:**
- AC1: WHILE a vision session is active THE SYSTEM SHALL publish frames of that session so
  the panel can display it.
- AC2: THE SYSTEM SHALL reuse the existing capture/serve mechanism and the existing crawl
  event types rather than introducing a second display path.
- AC3: THE SYSTEM SHALL NOT change the existing browser panel visual design, tab
  behaviour, or animation timing.
- AC4: WHEN vision performs an action THEN THE SYSTEM SHALL emit an event carrying the
  action so the panel can annotate it on the existing animation surface.
- AC5: IF frame publication fails THEN THE SYSTEM SHALL continue the vision session and
  degrade the panel to its existing "capture unavailable" state.

**Edge Cases:**
- Frame rate must be bounded; publication is best-effort and never blocks a vision action.
- Panel closed → publication continues at a reduced rate or pauses, but the session does
  not stop (REQ-12).

### REQ-12: Websearch survives component unmount

**User Story:** As a user I want to close the dashboard and keep only the orb on screen
while a websearch continues, so that the UI is not a dependency of the work.

**Verified:** All crawl listeners are registered inside `components/dark-glass-dashboard.tsx`
(`:628`, `:797`, `:1026-1029`), so unmounting it destroys crawl UI state. The
purpose-built `hooks/useCrawl.ts` that should own this state has **zero production
consumers** — dead code with its own passing test file (`__tests__/useCrawl.test.tsx`).
Replay infrastructure already exists: `backend/crawler/event_log.py` provides `append`,
`replay(after_seq)`, `snapshot`, and a `sync_required` flag for evicted events; the SSE
fallback is `hooks/useCrawlSSE.ts`. `XurOrb` already consumes `useTaskProgress` and
`useAgentQuestion` and renders `OrbWorkingIndicator` and `OrbBadge`
(`components/iris/XurOrb.tsx:81-82, 141-148, 479-493`).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL continue a websearch run to completion while the browser panel is
  unmounted.
- AC2: THE SYSTEM SHALL own crawl UI state above any component that can unmount, so that
  unmounting the panel does not reset or lose it.
- AC3: WHEN the panel remounts THEN THE SYSTEM SHALL restore the run's current state from
  the server-side event log rather than restarting the run.
- AC4: WHILE the panel is unmounted THE SYSTEM SHALL surface run progress on the orb using
  its existing working-indicator and badge surfaces.
- AC5: THE SYSTEM SHALL NOT require the vision session, frame capture, or fetch traversal
  to observe frontend mount state.
- AC6: IF events were evicted before replay THEN THE SYSTEM SHALL perform a full snapshot
  sync rather than presenting a partial timeline as complete.

**Edge Cases:**
- Panel unmounted for longer than the event-log TTL → snapshot sync path (AC6).
- Multiple mounts of the panel → state is shared, not duplicated per mount.

### REQ-13: Non-blocking question card with parked sources

**User Story:** As a user I want the agent to ask me about a blocked source without
stopping, so that it keeps making progress and picks the source back up if I answer.

**Verified:** `_handle_ask_user_question` at `backend/agent/tool_bridge.py:939` calls
`tool.wait_for_answer(question)` at `:965`, which blocks for up to
`ASK_USER_QUESTION_TIMEOUT = 120` seconds (`backend/agent/tools/ask_user_tool.py:33`).
`ask()` at `:67` already returns immediately; only `wait_for_answer` blocks.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL provide a non-blocking ask mode that raises the question card and
  returns immediately with a handle.
- AC2: WHEN a source cannot be passed THEN THE SYSTEM SHALL park that source, raise a
  non-blocking question, and continue with remaining sources in the same run.
- AC3: WHEN an answer to a parked question arrives THEN THE SYSTEM SHALL resume the parked
  source without restarting the research run.
- AC4: IF the run reaches synthesis with questions still unanswered THEN THE SYSTEM SHALL
  proceed with what it has and SHALL report which sources were parked.
- AC5: THE SYSTEM SHALL preserve the existing blocking ask mode for its current callers.
- AC6: THE SYSTEM SHALL NOT raise more than one question per parked domain per run.

**Edge Cases:**
- Answer arrives after the run has completed → discard cleanly, do not resurrect a
  finished run; log it (REQ-16).
- Multiple parked sources → each carries its own question handle.

### REQ-14: Answering a question card by voice

**User Story:** As a hands-free user I want to answer a question card by speaking after
the wake word, so that I do not have to open the UI and click.

**Verified:** Designed and unwired. `backend/agent/tools/ask_user_tool.py:5-6` documents
"Voice mode: question spoken via TTS, user speaks answer, fuzzy match".
`fuzzy_match_answer()` at `:183` is fully implemented and unit-tested
(`backend/tests/contract/test_ask_user_tool.py:92-114`) with **zero production callers**.
`receive_answer()` at `:105` has exactly one production caller —
`backend/iris_gateway.py:5043`, reached only by `msg_type == "question_response"` from
the frontend card. The STT path has no pending-question awareness.

**Acceptance Criteria:**
- AC1: WHILE a question is pending THE SYSTEM SHALL treat the next completed voice
  transcript as a candidate answer to that question.
- AC2: WHEN a candidate answer is received THEN THE SYSTEM SHALL match it against the
  question's options using the existing `fuzzy_match_answer`.
- AC3: WHEN the match confidence is at or above threshold THEN THE SYSTEM SHALL resolve
  the question with the matched option and SHALL emit the same resolution event the card
  click emits.
- AC4: IF the match confidence is below threshold THEN THE SYSTEM SHALL leave the question
  pending and SHALL ask the user to repeat, rather than guessing.
- AC5: THE SYSTEM SHALL allow the card click path to resolve the question at any time,
  and the first resolution SHALL win.
- AC6: IF no question is pending THEN THE SYSTEM SHALL route the transcript to the normal
  command path unchanged.

**Edge Cases:**
- User says something unrelated while a question is pending → below threshold → AC4, and
  the utterance must not be swallowed; it falls through to the normal path.
- Question times out between transcript capture and matching → resolve as timed-out, do
  not apply the answer to a dead question.
- Two questions pending → most recent wins; the other stays pending.

### REQ-15: Honest reporting of fetch outcomes

**User Story:** As a user I want to be told when a search found nothing, so that I never
receive model recall dressed up as research.

**Verified:** On the traced run, `[TOOL_DISPATCH] tool=crawler_query success=True
error_type=permanent` was logged for a crawl that retrieved zero usable content, and the
DER answer that followed was written from model knowledge and rendered in a prism card
that claimed "failed page fetches" while the chat presented sourced-looking prose.

**Acceptance Criteria:**
- AC1: WHEN a research call produces no usable page THEN THE SYSTEM SHALL report the tool
  call as unsuccessful.
- AC2: THE SYSTEM SHALL NOT report a tool result as both successful and permanently
  errored.
- AC3: WHEN an answer is produced without any usable retrieved content THEN THE SYSTEM
  SHALL state that it is not based on retrieved sources, in both the displayed answer and
  the spoken output.
- AC4: THE SYSTEM SHALL list the attempted sources and their per-URL failure reasons in
  the displayed result.
- AC5: THE SYSTEM SHALL apply the existing speak/display contract, so spoken text remains
  a companion-style subset of visible text.

**Edge Cases:**
- Partial success (1 of 3 URLs usable) → report success, but still list the failed sources
  and their reasons.
- Zero usable content and web mode off → keep the existing web-mode advisory wording from
  the T36 gate work rather than inventing new phrasing.

### REQ-16: Observability and tuning instrumentation

**User Story:** As the tuner I want every escalation, race, park, and challenge measured
so that the next iteration can set thresholds from data instead of intuition.

**Verified:** The need is proven. The current challenge counter is an instrumentation
artifact: 2 labelled challenges against 136 timeouts across 401MB, because detection runs
only on the fallback path (REQ-4). We could not answer "how often does bot protection
cost us a search?" from the logs.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log every capability escalation with the URL, the triggering
  reason, and the deciding predicate value.
- AC2: THE SYSTEM SHALL log every per-URL terminal outcome with its usability reason from
  REQ-1 AC4.
- AC3: THE SYSTEM SHALL log vision session start, action count, duration, and terminal
  cause.
- AC4: THE SYSTEM SHALL log every race started, its winner, and the loser's cancellation.
- AC5: THE SYSTEM SHALL log every park, question raised, and resolution source (card /
  voice / timeout / run-ended).
- AC6: THE SYSTEM SHALL include a conversation or run identifier in every log line emitted
  by this feature.
- AC7: THE SYSTEM SHALL keep instrumentation off the critical path such that a logging
  failure never fails a fetch.

**Edge Cases:**
- High-volume frame publication must not be logged per frame; log rate-limited summaries.
- Missing run identifier → fall back to a stable placeholder, never omit the field.

### REQ-17: Vision as a content source, cross-checked against crawl

**User Story:** As a user I want the vision model to read what is actually on screen while
it scrolls, so that content the crawler's text extraction missed is still captured.

**Verified:** The capability exists and is unused for this purpose. `LFM2.5-VL` exposes
`vision.read_text` (OCR/extraction), `vision.analyze_screen` (question answering over a
frame), and `vision.describe_live_frame` — documented as "Fast single-sentence description
(monitoring/streaming)" at `backend/tools/vision_mcp_server.py:5-11`. Today no websearch
path calls any of them. The observed cost of not doing this: on the reference run the
crawler produced markdown that reranked at 0.000 while the pages were, to a human,
readable.

**Acceptance Criteria:**
- AC1: WHILE a vision session scrolls a page THE SYSTEM SHALL capture frames and extract
  their visible content, not only decide the next action.
- AC2: THE SYSTEM SHALL triage each captured frame with a cheap call before spending a
  full extraction call on it, so that frames with no new content are skipped.
- AC3: THE SYSTEM SHALL assemble frame extractions into one ordered content record per
  URL, de-duplicated across overlapping scroll positions.
- AC4: WHEN both crawl content and vision content exist for the same URL THEN THE SYSTEM
  SHALL reconcile them into a single evidence record rather than discarding either.
- AC5: WHEN crawl content and vision content materially disagree THEN THE SYSTEM SHALL
  record the disagreement, because it distinguishes a challenge page the crawler extracted
  from real content the crawler missed.
- AC6: THE SYSTEM SHALL mark vision-derived content with its own provenance so that
  downstream trust scoring can distinguish it from DOM-derived text.
- AC7: WHERE a page's extracted text is disproportionately small relative to its rendered
  content THE SYSTEM SHALL be permitted to run vision extraction even though the crawl was
  nominally usable.
- AC8: THE SYSTEM SHALL bound total extraction calls per URL, and the bound SHALL be
  configurable.

**Edge Cases:**
- Frames from a page that never changes while scrolling → triage rejects them; no
  extraction cost.
- Vision extraction on a challenge page → produces challenge boilerplate; must be judged by
  `page_is_usable` (REQ-1) like any other content, not trusted because vision produced it.
- Vision content only, crawl empty → usable, but flagged vision-only in provenance.
- OCR noise (misread characters) must not silently enter the evidence record as fact; the
  disagreement record from AC5 is the mechanism that surfaces it.

### REQ-18: Persistence and provenance continuity

**User Story:** As the system I want content retrieved by the vision path to land in the
same stores as crawled content, so that the search's memory, provenance, and source
scoring keep working.

**Verified:** All three stores are live consumers, not vestigial.
`_apply_har_penalties` (`backend/crawler/orchestrator.py:451-470`) reads HAR entries and
feeds `SourceRegistry.penalize_url`, treating 403/404/timeout as dead — it is how domains
get down-weighted. `backend/agent/document_store.py:29` defines the `document_data` table
with `trust`, `variants`, `revision`, and a 500-document eviction bound, and
`agent_kernel.py:3398 _store_document_data` populates it with `source_document_id`,
`sources`, and `har_path` so documents rehydrate. Pacman fragments content into MCM with
trust zones (`agent_kernel.py:4806-4831`, `10039` forwarding untrusted web scoring per
REQ-22).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL record HAR entries for vision-session requests using the existing
  HAR path, so `_apply_har_penalties` scores vision-visited domains on the same basis.
- AC2: THE SYSTEM SHALL persist vision-derived content to the document store through the
  existing `_store_document_data` path, carrying its provenance from REQ-17 AC6.
- AC3: THE SYSTEM SHALL fragment vision-derived content into pacman with a trust zone
  consistent with its provenance, and SHALL NOT assign it a higher trust than equivalent
  crawled web content.
- AC4: THE SYSTEM SHALL preserve the existing `chunk_id → url` citation index so
  vision-derived passages remain attributable to their source URL.
- AC5: THE SYSTEM SHALL NOT remove, bypass, or duplicate the HAR, document-store, or
  pacman paths; the vision capability joins them rather than replacing them.
- AC6: IF a persistence write fails THEN THE SYSTEM SHALL complete the research run and
  record the failure, rather than failing the fetch.

**Edge Cases:**
- Vision session visits many intermediate URLs (redirects, consent domains) → HAR records
  them, but only the goal URL is persisted as content.
- Document store at its 500-document cap → existing eviction applies unchanged.
- Vision-only content with no DOM equivalent → still needs a stable `chunk_id` for AC4.

### REQ-19: Vision drives a search engine when the planner yields no URLs

**User Story:** As a user I want the agent to go find sources itself when its URL
planner comes back empty, so that a search-provider outage or a missing key does not
turn into "I couldn't find anything".

**Verified:** NEW (unverified — implementation pending). The dead end is real and
observed live on 2026-08-10: `[CrawlPlanner] LLM planning produced no URLs for '...';
no search-engine fallback (DuckDuckGo removed). Crawl will report 'no candidate urls'.`
The capability to recover already exists and is unused for this — `BrowserSession`
(REQ-7 AC2) has navigate, click, type and scroll, and vision can read the rendered
results page.

**Rationale:** every rung of the existing ladder assumes the planner produced URLs.
REQ-2's broaden-and-retry re-plans, so when the planner itself is the failure the
retry re-fails identically — which is exactly what the live run showed: two plan
calls, both yielding nothing. A browser that can type into a search box is a
*different* acquisition channel, not a retry of the same one.

**Acceptance Criteria:**
- AC1: WHEN the planner returns zero URLs THEN THE SYSTEM SHALL attempt source
  discovery by driving a search engine in the vision browser session.
- AC2: THE SYSTEM SHALL navigate to a search engine, enter the query, and read the
  results page to extract candidate URLs.
- AC3: THE SYSTEM SHALL feed the extracted URLs back into the normal per-URL dispatch
  (REQ-6), so discovered sources are fetched by the same capabilities and judged by
  the same predicate as planned ones.
- AC4: THE SYSTEM SHALL bound discovery by the existing `SessionBounds` and SHALL
  extract at most a configurable number of candidate URLs.
- AC5: IF the search engine presents a bot challenge or CAPTCHA THEN THE SYSTEM SHALL
  park and report it (REQ-13) and SHALL NOT attempt to solve it.
- AC6: THE SYSTEM SHALL record that the URLs were discovered by vision rather than
  planned, so their provenance is distinguishable (REQ-18 AC2).
- AC7: THE SYSTEM SHALL attempt search-engine discovery at most once per research run.
- AC8: IF vision is unavailable THEN THE SYSTEM SHALL report the honest
  no-sources outcome (REQ-15) rather than failing silently.

**Edge Cases:**
- Search engine blocks automated access entirely → AC5 park-and-report; do not rotate
  through engines indefinitely.
- Results page yields only ads/navigation → treated as zero candidates, REQ-15 applies.
- Discovery succeeds but every discovered URL is unusable → normal REQ-15 path; the
  discovery attempt itself must appear in the reported source list.
- Must respect robots.txt on discovered URLs exactly as planned URLs do (REQ-5 AC3).

## Non-Requirements (Out of Scope)

- **Solving or bypassing CAPTCHAs.** The system detects them, parks the source, and asks
  the human (REQ-13). It must not attempt to defeat a CAPTCHA or human-verification check.
- **Entering credentials.** Vision must not type passwords, card numbers, or other
  credentials into any page. Login-walled sources are parked, never authenticated
  autonomously.
- **Weakening robots.txt compliance.** REQ-5 explicitly preserves it.
- **Commercial proxy or residential-IP rotation.** Not part of this feature.
- **Purchases, form submissions, or any state-changing action on a third-party site.**
  Vision is read-and-navigate only: scroll, click to reveal or paginate, dismiss consent,
  navigate. It must not submit forms that create, buy, post, or send.
- **Redesign of the browser panel visuals.** Locked decision 7.
- **Decomposition of `agent_kernel.py`.** Tracked separately in pin `pin_1bb97f28e137`.
- **Follow-up crawl context carryover.** Tracked separately in pin `pin_229958557c46`.

## Open Questions

- Minimum content length for REQ-1's `too-short` verdict — start at a conservative value
  and tune from REQ-16 AC2 data.
- Vision action bound for REQ-7 AC4 — needs one real session to calibrate.
- Fuzzy-match confidence threshold for REQ-14 AC3 — `fuzzy_match_answer` already returns a
  confidence; pick from measured distribution rather than guessing.
- Whether parked-source resumption should re-run the whole DER step or only the fetch node.

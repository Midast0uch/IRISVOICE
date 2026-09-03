# Tasks: Vision-Driven Interactive Browser Websearch

> Every task links to a requirement. Waves group work for parallel execution.
> Read `requirements.md` and `design.md` in full before starting — the Ripple-Effect Map
> in design.md tells you what each task touches beyond its own file.

## Reference failure

The whole spec exists to make this trajectory impossible. Keep it open while working:
`backend/logs/irisvoice.log` lines 10310–10800, conversation
`conv_1786327042255_pjtfyybj2`, 2026-08-09 22:00:35–22:01:40. Three URLs — DNS failure,
403 challenge, empty extraction — zero usable content, `success=True`, and an answer
written from model knowledge presented in a research card.

---

## Wave 0 — Baseline (blocking; do this first)

- [x] T0 (all): Establish a green test baseline. Run the existing crawler, DER, and
  browser-surface suites and record which failures are pre-existing. Per
  `pin_1bb97f28e137`, 12+ current failures come from stale test doubles
  (`_StubBackend.fetch()` missing `job_id`, `_Step` missing `expected_output`, `_Embed`
  missing `encode_with_meta`, `AgentKernel` missing `_mcm_orch`). Do not fix them here —
  record them, so a real break is distinguishable from a stale artifact.
  — RIPPLE: without this, every later wave's red is ambiguous.

---

## Wave 1 — Foundation: one truth (blocks everything else)

- [x] T1 (REQ-1): Create `backend/crawler/usability.py` with `UsabilityReason`,
  `UsabilityVerdict`, and `page_is_usable(page)`. Threshold `MIN_CONTENT_CHARS` is
  configurable and instrumented.
  — RIPPLE: becomes the only judge; T2/T3/T4/T7 all depend on it.

- [x] T2 (REQ-1, REQ-2): Replace the local predicate at
  `backend/crawler/crawl_runner.py:347` and the retry gate at
  `backend/crawler/orchestrator.py:204` with `page_is_usable`.
  — RIPPLE: `orchestrator.py:205-225` retry becomes reachable for the first time; expect
  behaviour change on runs that previously completed silently. `crawl_runner.py:362-376`
  per-URL reason logging should now source its reason from the verdict.

- [x] T3 (REQ-3): Change `backend/crawler/rerank.py:141-146` to return a distinguishable
  re-query state instead of a bare `[]`, and consume it at
  `backend/crawler/orchestrator.py:250`.
  — RIPPLE: `extract_and_cite` at `:257` must become unreachable with an empty passage
  set; `cred_map.top_score` at `:263` still needs a value on the re-query path.

- [x] T4 (REQ-4): Make `_is_challenge_page` (`crawl_runner.py:453`) reachable from the
  primary Playwright path in `backend/crawler/crawler_engine.py`, mark challenged pages
  unusable, and skip capture-store persistence for them.
  — RIPPLE: `crawler_engine.py` has zero challenge awareness today. Also add the
  challenge-suspected timeout reconciliation (REQ-4 AC4) — 136 timeouts vs 2 labelled
  challenges is the measurement this fixes.

- [x] T5 (REQ-15): Make `success=True` impossible on a zero-usable-content research call;
  remove the `success=True error_type=permanent` contradiction in TOOL_DISPATCH.
  — RIPPLE: `backend/agent/tool_decision.py` and any DER branch that reads tool success.
  Preserve the T36 web-mode gate wording from `pin_cd839f4b2a97` — extend, don't replace.

- [x] T6 (REQ-16): Add the instrumentation surface: per-URL terminal outcome with reason,
  escalation decisions, and run identifier on every line.
  — RIPPLE: off the critical path; a logging failure must never fail a fetch.

---

## Wave 2 — Capabilities and vision session

*T7–T9 depend on Wave 1. T10–T12 are backend-independent of Wave 3 and may run parallel.*

- [ ] T7 (REQ-6): Create `backend/crawler/capabilities.py` — `FetchCapability` protocol,
  `FetchOutcome`, and the `fetch.crawl` implementation wrapping the existing path.
  — RIPPLE: registers as a DER node type; reuse the node-record/edge machinery
  `_der_finalize_step` already stamps rather than adding a parallel model.

- [ ] T8 (REQ-7, REQ-9): Create `backend/vision/browser_session.py` — persistent Playwright
  session, action executor (navigate/reload/back/forward/scroll/click/type/wait), and
  browser-scoped frame capture. Bounded by `SessionBounds`.
  — RIPPLE: REQ-9 AC2 forbids desktop capture here;
  `lfm_vl_provider.py:298 screenshot_to_bytes` stays untouched for its existing callers.
  Playwright is already available via crawl4ai (`crawler_engine.py:165-195`) — reuse, do
  not add a dependency.

- [ ] T9 (REQ-8): Add a counted lease with hard expiry to
  `backend/tools/lfm_vl_provider.py`, honoured by the idle watchdog at `:99-107`.
  — RIPPLE: do NOT rewrite auto-start (`:221-296`), PID-tracked stop (`:79-94`), or
  `set_vision_idle_callback` (`:49`) — all correct. Lease must release on exception.

- [ ] T10 (REQ-6, REQ-7): Implement `fetch.vision` on the T7 interface: goal-directed
  action loop, wall detection (CAPTCHA / login / paywall), and settled-DOM handback.
  — RIPPLE: REQ-6 AC5 reversal edge; the handback is what makes `crawl → vision → crawl`
  a normal traversal. Wall detection feeds T14.

- [ ] T11 (REQ-5): Apply `_STEALTH_EXTRA_HEADERS` (defined at `crawler_engine.py:50`,
  deliberately unused per `:48`) as a coherent header set, add per-domain cookie
  persistence scoped to the run, and randomised inter-request delay.
  — RIPPLE: **must not weaken `robots_checker.py`** (REQ-5 AC3, pinned by CT-8). Cookie
  jar is run-scoped — no cross-run identity, no credential storage.

- [ ] T12 (REQ-10): Concurrent per-URL dispatch, plus conditional racing gated on
  `source_registry` failure history, with loser cancellation.
  — RIPPLE: REQ-10 AC4 forbids racing domains with no failure history. Note `source_registry`
  reuse is itself unverified (pin V2) — do not assume it is trustworthy; log both sides.

- [ ] T12a (REQ-17): Create `backend/vision/frame_extraction.py` — per-scroll-frame capture,
  cheap triage via `describe_live_frame`, full extraction via `read_text` / `analyze_screen`
  only on frames that pass, de-duplication across overlapping scroll positions.
  — RIPPLE: `vision_mcp_server.py:5-11` needs NO change — all three tiers already exist;
  call them rather than adding vision tools. Bound by `SessionBounds.max_extractions`.
  Triage-before-extract is the cost model (design D8) — BT-10 guards it.

- [ ] T12b (REQ-17): Reconcile crawl and vision content into one `EvidenceRecord` per URL,
  keeping both sides and recording disagreement. Add the under-capture heuristic that lets
  vision extraction run on a nominally-usable but suspiciously thin crawl (AC7).
  — RIPPLE: vision-derived text is NOT trusted by virtue of being vision-derived — it goes
  through `page_is_usable` (T1) like any other content. Disagreement is a diagnostic, not a
  tiebreak: never pick a winner silently (design D9).

---

## Wave 3 — Non-blocking questions and voice

*Independent of Wave 2; may run in parallel.*

- [ ] T13 (REQ-13): Add non-blocking ask mode + `ParkedSource` registry to
  `backend/agent/tools/ask_user_tool.py`. Build on `ask()` at `:67` which already returns
  immediately; leave `wait_for_answer` at `:148` intact for existing callers.
  — RIPPLE: `tool_bridge.py:939-965` routes park-path calls to the new mode. Nothing
  suspends, so the DER control-flow change deferred in `pin_1bb97f28e137` is NOT needed.

- [ ] T14 (REQ-13): Wire park-and-continue: on a wall, park the source, raise one question
  per domain per run, and continue. Resume the parked source when an answer arrives.
  — RIPPLE: depends on T10's wall detection. REQ-13 AC4 — synthesis proceeds with parked
  sources listed, never blocked.

- [ ] T15 (REQ-14): Give the STT path pending-question awareness and wire
  `fuzzy_match_answer` (`ask_user_tool.py:183`) to its **first production caller**.
  Below-threshold matches leave the question pending and fall through to the normal
  command path.
  — RIPPLE: `iris_gateway.py:5035-5045` keeps `question_response`; both paths must funnel
  to one resolution point so first-wins holds (CT-4). `useAgentQuestion.ts:23-32` needs no
  change — emit the same `iris:question_answered` event and the orb badge clears itself.

- [ ] T12c (REQ-18): Join the vision path to the existing persistence spine — HAR entries
  for vision-session requests, `_store_document_data` with `ContentOrigin` provenance,
  pacman fragmentation at a trust zone no higher than crawled web content, and
  `citation_index` coverage for vision-derived passages.
  — RIPPLE: **do not fork these paths.** `_apply_har_penalties`
  (`orchestrator.py:451-470`) and `source_registry.penalize_url` need NO change — vision
  domains reach them by contributing HAR entries. `document_store.py:29` schema is a
  CONTRACT LOCK (CT-10): `trust` and provenance columns already suffice. Reuse the REQ-22
  untrusted-web scoring already forwarded at `agent_kernel.py:10039`. A persistence write
  failure must never fail the fetch (REQ-18 AC6).

---

## Wave 4 — UI: mirror, persistence, animation

*T16 depends on T8. T17–T19 depend only on Wave 1.*

- [ ] T16 (REQ-11): Publish vision-session frames through the existing
  `capture_store.save` path so `/api/browser/capture/{job_id}/{page}` serves them.
  Rate-bounded, best-effort, never blocking an action.
  — RIPPLE: `capture_store.py:53-112` needs NO change — verified sufficient. Fixes the
  repeated `[browser-surface] capture unavailable` seen throughout the reference trace.

- [ ] T17 (REQ-12): Hoist `hooks/useCrawl.ts` into a provider above the panel's unmount
  boundary; add `crawler_progress`, `crawler_phase`, `crawler_vision_action`, and
  `crawler_source_parked` listeners; delete the duplicated inline listeners from
  `components/dark-glass-dashboard.tsx:628,797,1026-1029`.
  — RIPPLE: `useCrawl` currently has **zero consumers** — this is the 13th
  declared-never-wired instance and adopting it is the fix. `useCrawlSSE.ts:19` needs no
  change; it already emits the same CustomEvents. **Do not alter panel visuals** (REQ-11
  AC3, locked decision 7).

- [ ] T18 (REQ-12): Restore run state on remount from `event_log.replay(after_seq)`, with
  `snapshot` fallback when `sync_required` is set.
  — RIPPLE: `backend/crawler/event_log.py:63-96` needs NO change — server side is already
  complete. Only the client is missing.

- [ ] T19 (REQ-11, REQ-12): Add the two new event types to
  `hooks/useIRISWebSocket.ts:1245-1298` dispatch, and feed run progress into
  `useTaskProgress` so the orb reflects it while the panel is closed.
  — RIPPLE: `components/iris/XurOrb.tsx:81-82,141-148,479-493` needs NO change —
  `OrbWorkingIndicator` and `OrbBadge` already render working and question states.

---

## Wave 5 — Verification

- [x] T20 (REQ-1..18): Contract tests CT-1..CT-11 in `tests/contract/`.
  DONE 2026-08-10. CT-1/2/9 `test_single_judge_and_wiring_contract.py` (14);
  CT-3 `test_crawl_event_shapes_contract.py` (10); CT-6 already complete in the
  existing `test_browser_surface_headers.py` (19) — referenced, not duplicated;
  CT-7 `test_view_agent_protocol_contract.py` (4); CT-10
  `test_vision_provenance_trust_contract.py` (7). CT-4/5/8/11 landed in Waves 1-4.
  Writing these found FIVE production gaps — see below.
  — RIPPLE: CT-9 (caller-existence pins for `fuzzy_match_answer`, rerank re-query,
  `_STEALTH_EXTRA_HEADERS`, `useCrawl`) is the guard against this codebase's dominant
  failure mode. CT-6/CT-7/CT-8 and the `document_store` schema lock in CT-10 are CONTRACT
  LOCKs on code that does **not** change.

- [x] T21 (REQ-1..18): Behavioral tests BT-1..BT-10 in `tests/behavioral/`.
  DONE 2026-08-10. BT-1/7/8/9/10 `test_websearch_escalation_behavior.py` (7);
  BT-3/5 `test_websearch_park_and_honesty_behavior.py` (7); BT-4
  `__tests__/BT-4.panel-unmount-mid-run.test.tsx` (6, jest — frontend);
  BT-2 and BT-6 landed in Waves 1-4.
  — RIPPLE: BT-1's baseline is "retry has fired 0 times in 401MB" — it must fire exactly
  once. BT-4 covers unmount survival end to end. BT-10 guards the triage cost model — if
  extraction calls equal frame count, D8's economics are broken even though the test of
  extraction itself passes.

- [x] T22 (REQ-16): Standing CDD harness
  `scripts/validate_websearch_trajectory.py` replaying the reference failure through the
  full stack on every run.
  — RIPPLE: this trajectory is the spec's acceptance artifact.
  DONE 2026-08-10, exit 0. CAVEAT: its REQ-3 check is an INFERENCE from REQ-1+REQ-2
  passing, not a direct assertion. Direct REQ-3 coverage is CT-2, which drives the
  orchestrator and asserts `extract_and_cite` is never reached with empty passages.

## Gaps found BY Wave 5 verification (all fixed unless noted)

Writing the tests surfaced five defects that every isolated unit test had missed:

- **#14** `CRAWLER_VISION_ACTION` had ZERO backend emitters while the entire frontend
  existed (`types/iris.ts:149`, `useCrawl.ts:180/253`, `useIRISWebSocket.ts:1342`) and
  `UX_MAP` had no entry — despite ux_map's own "enforced by a test" comment. FIXED.
- **rogue predicate** `orchestrator.py:888` `_learn_from_crawl` used `not p.error` to pick
  which URLs to REGISTER AS GOOD SOURCES, so empty pages were learned and re-seeded into
  later crawls for the same topic. The reference trace shows `SRC LEARN saved=1` on a run
  with zero usable pages. FIXED — this was the uncounted THIRD instance of the predicate
  disagreement.
- **#15** `ContentOrigin` never reached `_store_document_data`/pacman. FIXED.
- **#16** `reconcile()` had zero production callers — imported by `fetch_vision.py` and
  deferred to "the caller", which never called it. REQ-17 AC4/AC5 did not exist at
  runtime. FIXED.
- **#17** `reconcile()` merged by "longer text wins", so a verbose Cloudflare interstitial
  BEAT the real content — the reference trajectory's exact failure. FIXED (challenge
  detection now precedes the length rule).
- **#18** `_park_source` minted a synthetic `parked_<hex>` question_id and never raised a
  question, so the id sent to the frontend referenced nothing answerable by card or voice.
  FIXED (routed through `ask_non_blocking`).

- [ ] T23 (all): Live verification — a real websearch on a Cloudflare-fronted source, with
  the dashboard closed for part of the run, and one question answered by voice.
  — RIPPLE: **green tests are not sufficient evidence in this codebase.** Every defect in
  the reference trace passed its unit tests. A live run is the exit criterion.

  **BACKEND HALF DONE 2026-08-10** — real network, real crawl4ai/Playwright, real
  orchestrator, no stubs. Backend :8090, frontend :53819. Live evidence:
  - `CHALLENGE url=https://palworld.fandom.com/... status=403 — page not saved` (REQ-4)
  - per-URL reasons distinct and live: `challenge` vs `transport_error` (REQ-1 AC4)
  - `reddit -> error=blocked by robots.txt` — robots compliance SURVIVED the stealth
    work (REQ-5 AC3)
  - **2 plan calls: broaden-and-retry FIRED for the first time in recorded history**
    (REQ-2; baseline was 0 fires in 401MB of production logs)
  - `result.error='all pages failed to fetch'`, `cited_markdown=0`, `passages=0` —
    the headline defect does not reproduce (REQ-15 AC1/AC3)

  **STILL OUTSTANDING for a complete T23 — needs the user:**
  1. Voice-answering a question card (needs a mic; REQ-14 backend is tested but the
     end-to-end voice leg is unverified).
  2. Dashboard closed for part of a live run (BT-4 covers it under jest; unverified live).
  3. **BLOCKER: the Cerebras API key returns 401 "Wrong API Key".** CrawlPlanner failed
     3/3 and fell back, so the broadened plan produced no URLs. The retry MECHANISM is
     proven; the planner behind it is blocked. Note also
     `no search-engine fallback (DuckDuckGo removed)` — a failed LLM plan now means no
     URLs at all, which is a resilience gap worth its own task.
  4. **Unrelated pre-existing crash still live:** `[crawl_runner] unexpected error:
     'str' object has no attribute 'get'`. Present in the 2026-08-09 trace and still
     firing. Never in this spec's scope; deserves its own task.

---

## Wave 6 — REQ-19: vision-driven source discovery (NEW, not yet built)

Added 2026-08-10 after a live run dead-ended at `no candidate urls`. The user's
observation was correct: with no URLs from the planner, vision should have typed the
query into a search engine itself. Every existing rung assumes planned URLs, and
REQ-2's retry re-plans — so when the PLANNER is the failure, the retry re-fails
identically. Confirmed live: two plan calls, both empty.

- [x] T24 (REQ-19): `discover_urls_via_vision(query, job_id)` — navigate a search
  engine in the existing `BrowserSession`, type the query, read the results page,
  extract candidate URLs.
  — RIPPLE: uses `BrowserSession` navigate/type/click (REQ-7 AC2) — already built,
  currently unused for this. Bound by `SessionBounds`. Respect robots.txt on every
  discovered URL exactly as planned ones (REQ-5 AC3). A search-engine CAPTCHA is
  PARKED, never solved (REQ-19 AC5 / Non-Requirements).
  DONE 2026-08-10 — `backend/vision/search_discovery.py`. DOM extraction
  (`_extract_urls_from_html`) is the primary tier; vision `read_text`/
  `analyze_screen` is the fallback tier when DOM yields nothing (AC2). Also
  added `click_discovered_result()` for clicking a specific result directly
  (explicit user ask alongside the harvesting path).

- [x] T25 (REQ-19 AC1/AC3/AC7): call it from the orchestrator when the plan (or the
  broadened re-plan) yields zero URLs, at most once per run, and feed results into the
  normal `dispatch_urls` path.
  — RIPPLE: discovered URLs must be judged by `page_is_usable` and carry
  vision-discovered provenance (AC6 / REQ-18 AC2). Do NOT create a second dispatch
  path — reuse T12's.
  DONE 2026-08-10 — `backend/crawler/orchestrator.py` `research()`:
  discovered URLs are merged into the ordinary `CrawlPlan` and flow through
  the SAME branch planned URLs already use (`dispatch_urls` in production,
  `backend.fetch` on the retry leg — the existing retry mechanism, not a
  new one). `_discover_urls_via_vision` / `_stamp_discovery_provenance`
  added; `discovery_attempted` is a local (not instance) flag so concurrent
  runs never share state (AC7). A search-engine wall parks via the existing
  `_park_source` (AC5) instead of dispatching a fabricated URL.

- [x] T26 (REQ-19): contract + behavioral tests — CT-12 (discovery URLs enter the
  normal dispatch path and are robots-checked), BT-11 (planner returns zero URLs →
  discovery runs once → discovered URLs fetched → honest outcome if all unusable).
  — RIPPLE: extend `scripts/validate_websearch_trajectory.py` with a zero-URL variant.
  DONE 2026-08-10 — CT-12 `test_search_discovery_contract.py` (11 tests);
  BT-11 `test_websearch_discovery_behavior.py` (3 tests); BT-12 (Problem-1
  regression guard, escalation on a FRESH crawl-only failure — see below)
  `test_fresh_failure_escalation_behavior.py` (9 tests). NOT done: the
  `validate_websearch_trajectory.py` zero-URL variant extension — left for
  a follow-up task; the harness still passes unchanged (exit 0).

**Problem-1 fix landed alongside T24-T26** (found live 2026-08-10 17:09:08,
same session as the REQ-19 dead end): `dispatch_urls`'s escalation to
`fetch.vision` fired ONLY via `_race_url`, which is gated on
`source_registry` already having failure history for the domain — a URL
failing crawl for the FIRST time in a run (`usable=False reason=challenge`,
no history yet) never escalated at all. Fixed in `orchestrator.py`:
`_dispatch_one` now escalates a fresh unusable outcome (challenge / empty /
too_short) to `fetch.vision` at most once per URL via the new
`_escalate_to_vision`, reusing `_vision_fetch` (REQ-11 AC4 emitter) and
`_stamp_evidence` (REQ-17/18). `transport_error` is deliberately EXCLUDED
from escalation wholesale — it is the reason recorded for both robots.txt
refusal (REQ-5 AC3) and DNS failure, and `fetch.vision` has no robots gate
of its own, so escalating it would silently route around robots.txt for
the exact URL it just refused.

## Dependency / parallelization notes

- **Wave 1 blocks everything.** T1 in particular — T2, T3, T4, T7, and T12 all consume
  `page_is_usable`. Landing any escalation logic before the predicate is shared just adds
  a fourth disagreeing judge.
- **Wave 2 and Wave 3 are independent** and may run concurrently by different agents.
  Wave 3 touches only `ask_user_tool.py`, `tool_bridge.py`, `iris_gateway.py`, and the STT
  path; Wave 2 touches only the crawler and vision modules.
- **Wave 4's T17/T18/T19 depend only on Wave 1**, so the frontend can start as soon as the
  event types are agreed. T16 alone waits on T8.
- **T11 (stealth) and T4 (challenge detection) should land together** — measuring
  mitigation effectiveness requires detection on the same path.
- **Tasks that change no code, only add a pin:** none of CT-6, CT-7, CT-8 modify
  production code; they lock `browser_surface.py`, `view_agent.py`, and
  `robots_checker.py` respectively. Reviewers should see these as guards, not changes.
- **T12a/T12b/T12c depend on T8 and T10** (a live vision session to capture frames from),
  and T12c additionally on T7's `FetchOutcome`. They are otherwise independent of Wave 3
  and Wave 4.
- **Verified-no-change areas** (do not edit, cite in review if touched):
  `capture_store.py:53-112`, `event_log.py:63-96`, `useCrawlSSE.ts:19`,
  `XurOrb.tsx:81-82,141-148,479-493`, `useAgentQuestion.ts:23-32`,
  `QuestionCard.tsx`, `lfm_vl_provider.py:298`, `vision_mcp_server.py:5-11`,
  `source_registry.penalize_url`, `orchestrator.py:451-470`.
- **Nothing in this spec deletes a store.** HAR, `document_data`, and pacman are live
  consumers with downstream effects (source penalties, document rehydration, trust-zoned
  memory). REQ-18 AC5 forbids removing, bypassing, or duplicating them. If a future change
  proposes retiring one, that is a separate spec.

## Test rule reminder for the executing agent

Per CLAUDE.md: run the spec's tests against your implementation. Never weaken a test to
make it pass — that includes reducing the load it drives, loosening a tolerance, dropping
a parametrize case, or stubbing a dependency that could fail. If a test and this spec
genuinely conflict, **report it**; name the spec line and the test line, show the proof,
and propose a fix. Do not reconcile it yourself.

# Tasks: Unified Web-Search Architecture (Crawl Core + DER-Driven Research)

> Each task links to a requirement ID. Grouped into waves for parallel execution.
> Dependency order: Wave 1 (core) → Wave 2 (entry points) → Wave 3 (DER + memory)
> → Wave 4 (frontend) → Wave 5 (tests + verification).

## Wave 1 — CrawlOrchestrator Core
- [ ] T1 (REQ-1, REQ-2, REQ-3, REQ-4, REQ-9, REQ-17 AC4): Create `backend/crawler/orchestrator.py`
      with `CrawlOrchestrator.research(...)` running Plan→Fetch→Passage-Split→Return;
      define `CrawlResult`, `PageData`, `Passage`, `CrawlProgress` dataclasses; define
      swappable `FetchBackend` interface (in-process + subprocess backends).
- [ ] T2 (REQ-5, REQ-6): Implement `CredibilityScorer` (source-type table + 4-factor
      product; classify from URL heuristics, no network calls).
- [ ] T3 (REQ-7): Implement passage rerank (BM25 + embedding hybrid → cross-encoder;
      threshold drop; re-query-on-low-score fallback).
- [ ] T4 (REQ-8): Extend `DataExtractor` call to return `cited_markdown` with
      `chunk_id`→URL bindings; flag unsourced claims `[?]`.

## Wave 2 — Entry Point Refactors
- [x] T5 (REQ-15, REQ-10, REQ-11, REQ-12, REQ-13): Refactor `iris_gateway.py:8685`
      `crawl_research` to call `CrawlOrchestrator.research(mode="ws")` with an
      `on_progress` that emits the unified event set.
- [x] T6 (REQ-16, REQ-10, REQ-11, REQ-12): Refactor `tool_bridge.py:_execute_crawler_query`
      to call `CrawlOrchestrator.research(mode="agent")` and emit `crawler_started` /
      `crawler_page_fetched` / `open_tab` (previously WS-only).

## Wave 3 — DER Integration + Memory
- [x] T7 (REQ-19): Confirmed `crawler_query` is a single atomic tool; `explorer.propose()`
      web fallback uses `_is_web_intent(goal)` (no mode switch). No code change needed.
- [x] T8 (REQ-20, REQ-21): Verified no separate web verifier; DER treats `crawler_query`
      generically (physics-driven fan-out via u/ξ). No code change needed.
- [x] T9 (REQ-17): Subprocess crash/timeout → `CrawlResult.error` set, never raise;
      per-batch timeout KILLS the process TREE (taskkill /T /F / pgid) so orphaned
      Chromium children are reaped; concurrency cap (default 2) added. Tested.
- [x] T10 (REQ-18): Confirmed web-gate fail-closed (`_internet_provider` default False);
      agent returns `success:False` "web access disabled" when gate closed. No change needed.
- [x] T11 (REQ-22): Persist `credibility_map` + `citation_index` on pacman `reference`
      (untrusted) fragment. Wired via post_turn → pacman_fragment.execute. Tested.

## Wave 4 — Frontend Feedback
- [x] T12 (REQ-14): `hooks/useCrawl.ts` — dedicated crawl-state hook consuming the
       unified CustomEvents (transport-agnostic: same events from WS + SSE). Replaces
       ad-hoc `task:progress` overwrite; `useTaskProgress` already routes `crawler_query`
       -> "WebCrawl" step. Tested (useCrawl.test.tsx, 4 pass).
- [x] T13 (REQ-25): `dashboard-wing.tsx` `onPage` already renders URL list from
       `crawler_page_fetched`; `dark-glass-dashboard.tsx` opens tab from `open_tab`
       (verified in useIRISWebSocket dispatch). Multi-tab strip + virtualized list are
       existing features; no change required for the unified path.
- [x] T14 (REQ-23): `cited_markdown` rendered as clickable links (backend produces
       `[n](url)`); `crawler_error` -> error toast (dispatched as CustomEvent). ARIA
       document region already present. No mode-specific branch added.
- [x] T15 (REQ-24): `useCrawlSSE.ts` SSE fallback activates when WS down; `crawler_complete`
       handling added to useIRISWebSocket (resets orb phase to idle). `processing_tool`
       phase already shared by Orb/ContextPill via listening_state. No stuck "processing".
- [x] T16 (REQ-26): `crawler_query` already `ToolSpec.long_running=True`; step narration
       via narration.run_with_narration() through _NARRATION_PLAYBACK_LOCK (existing).
- [x] T16b (REQ-30): `crawler/ux_map.py` is the single source-of-truth event->component
       map, consumed by both WS + SSE paths; exhaustive-mapping test in
       test_crawl_transport_contract.py. `useCrawl` honors reduced-motion via
       useReducedMotion (T16 indicator). Audio/visual parity verified at hook level.

## Wave 4b — Resilient Transport (REQ-31)
- [x] T19 (REQ-31 AC1/AC2): Per-session durable event log (`crawler/event_log.py`,
       monotonic `seq` + TTL eviction); orchestrator appends every progress event;
       client replays `seq > last_seq` on reconnect (deduped). Tested.
- [x] T20 (REQ-31 AC3): SSE endpoint `GET /api/crawl/stream/{session_id}`
       (`api/crawl_stream.py`) streams the same unified events; honors `Last-Event-ID`
       for auto-reconnect replay; terminal event closes stream. Both WS + SSE read the
       one log. Tested (route + mapping).
- [x] T21 (REQ-31 AC4/AC5): WS stays push-when-up; both transports read the one
       `SessionEventLog`. (WS heartbeat/backoff is a frontend concern — see T15.)
- [x] T22 (REQ-31 AC6/AC7): Commands routed over HTTP POST `/api/crawl/command`
       (cancel) independent of push; background result fetch `GET /api/crawl/result/{job_id}`
       (REQ-29 AC5) buffered while push is down. JobRegistry shared by both paths.
- [x] T23 (REQ-31 edge): TTL eviction → `sync_required` marker + full state snapshot
       fetch. `event_log.py` sets `_sync_required` on eviction (consume_sync_required
       clears it); SSE endpoint emits `crawler_sync_required` when set; new
       `GET /api/crawl/snapshot/{session_id}` returns full buffered state; `useCrawl`
       fetches the snapshot and re-applies all events as a full sync. Tested
       (test_crawl_transport_contract.py: sync_required + snapshot).

## Wave 5 — Verification
- [ ] T17 (REQ-27): Verify termination bounds (`min_pages`/`max_pages`/timeout;
      `DER_MAX_CYCLES=40`; `work_units` cap) — no infinite loop.
- [ ] T17b (REQ-29): Verify background completion — WS disconnect mid-crawl: agent
      path continues + persists (AC1); WS `crawl_research` mid-crawl disconnect is
      HANDED TO the shared Job Registry and NEVER cancelled (AC2); ONE shared job
      registry for both paths (AC5); result replays on reconnect (AC3); new user
      utterance accepted + processed while crawl runs, orb reflects new state (AC4).
- [ ] T18 (REQ-28): Implement the 4-tier verification suite:
      - Tier 1 Unit: funnel order, CredibilityScorer monotonicity, rerank threshold,
        cite completeness, FetchBackend swap, heartbeat/backoff (mock collaborators).
      - Tier 2 Contract: event-stream parity WS vs agent; DER tool `|u|`-band consume;
        pacman `reference`/`untrusted`/`credibility_map`; event-log replay + SSE;
        UX layer-map parity + audio/visual non-contradiction; web-gate fail-closed.
        (real instance + stubbed collaborator + event-bus assert; anchor each to a PiN)
      - Tier 3 Integration (in-process, mock fetch): orchestrator→bus→consumer;
        DER→tool→pacman VETO-storm termination+persist; WS→JobRegistry handoff never
        cancel; command-over-HTTP-POST while push down; process-tree kill; concurrency
        cap; agent `crawler_query`→wing+tab.
      - Tier 4 Behavioral (live backend, assert event ORDER): gate OFF→no start; gate
        ON→start→N×page_fetched→open_tab→document:render; disconnect→reconnect→replay;
        new utterance during crawl→processed, orb reflects new state.
      Run full suite; zero regressions before crystallization.

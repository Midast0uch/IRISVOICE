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
- [ ] T12 (REQ-14): Remove `task:progress` "Reading host (N/M)" overwrite in
      `hooks/useTaskProgress.ts`; route search progress to `crawler_page_fetched`.
- [ ] T13 (REQ-25): Ensure `dashboard-wing.tsx` `onPage` renders URL list from
      `crawler_page_fetched` (both paths); `dark-glass-dashboard.tsx` tab from `open_tab`;
      multi-tab strip for deep research; TaskListCard "Researching…" step from
      `crawler_page_fetched` counts; responsive/virtualized list.
- [ ] T14 (REQ-23): Render `cited_markdown` citations as clickable links; unverified
      badge + DOMPurify; `_maybe_escalate_web_format` → QuestionCard; error-toast owner
      for `crawler_error`; ARIA document region + unsourced-claim labels.
- [ ] T15 (REQ-24): Orb/ContextPill/XurOrb/OrbWorkingIndicator consume the SAME
      `listening_state` `processing_tool` during research (no mode fan-out); orb returns
      to idle on completion/error (no stuck "processing").
- [ ] T16 (REQ-26): Mark `crawler_query` `ToolSpec.long_running=True`; step-level
      narration via `narration.run_with_narration()` through `_NARRATION_PLAYBACK_LOCK`.
- [ ] T16b (REQ-30): Implement the single event→component→state UX map; verify
      audio/visual non-contradiction (narration co-occurs with `processing_tool` + wing
      URL N; final answer speech follows orb-idle + document render); reduced-motion
       indicator for orb/pill.

## Wave 4b — Resilient Transport (REQ-31)
- [ ] T19 (REQ-31 AC1/AC2): Add per-session durable event log (monotonic `seq` + TTL);
      client tracks `last_seq`; replay `seq > last_seq` on reconnect (deduped).
- [ ] T20 (REQ-31 AC3): Add SSE endpoint streaming the same unified events; verify
      `EventSource` auto-reconnect + `Last-Event-ID` recovers missed push.
- [ ] T21 (REQ-31 AC4/AC5): Keep WS as command channel + push-when-up; both read the
      one log; add WS heartbeat (ping/pong) + exponential backoff with full jitter.
- [ ] T22 (REQ-31 AC6/AC7): Route client commands (utterance, set_web_mode) over HTTP
      POST (independent of push); verify command processed + result buffered while
      push is down; background crawls (REQ-29) unaffected by transport state.
- [ ] T23 (REQ-31 edge): TTL eviction → `sync_required` marker + full state snapshot
      fetch (not partial replay).

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

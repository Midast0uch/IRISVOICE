# Requirements: Fast Research + Real In-App Browser Control (rev 2, 2026-09-30)

> **Rev 2 replaces rev 1** (the pre-Oracle draft, still in git history at `528a9435`). Rev 1 was
> checked line by line against the code on 2026-09-30 (two audits + live measurements, recorded in
> `docs/audits/2026-09-29/PROGRESS.md`, session 13a261c7). Much of it was stale, already done, or
> built on components that no longer exist (an "LFM2-350M sub-50 ms decision engine"; a
> `backend/browser/` package). Rev 2 keeps the owner's goals and states only what the code needs.

## Owner goals (2026-09-30)

1. Research / websearch must be much faster. It "has always been slow".
2. KEEP the frontend emit events that drive the in-app browser iframe, and the animations shown
   when the agent takes control of the browser (particle cursor overlay).
3. The agent must ACTUALLY use the mouse and keyboard on pages in the in-app browser. The owner
   has never seen it click or type once vision is connected.
4. Use the Oracle where it measurably pays (better UX and performance).

## Measured baseline (2026-09-30, warm backend, `evals/run_evals.py`)

| Task | Pass | reply_s | Where the time went |
|---|---|---|---|
| r01_python_origin | PASS | 154 s | plan 18 s; Exa URL planning 16 s; crawl 36 s (3 pages in ~6 s, then waited for 2 Wikipedia URLs that could not succeed); `data_extractor` 43 s (~34 s of it pre-work, not model time); synthesis + extras 30 s |
| r02_websocket_rfc | PASS | 64 s | `search` quick tier crashed ("Event loop is closed"), fell back to the full crawl (44.8 s); synthesis returned a stub, reply was a raw `--- Source:` dump |

Root causes found (file:line as of 2026-09-30; re-verify before editing):

- **RC1 Wikipedia is lost.** Tier-1 sends a generic `Mozilla/5.0 (Windows NT 10.0; Win64; x64)` UA
  (`backend/crawler/capabilities.py:127`); Wikipedia answers 403; any 401/403 is labelled
  `challenge` (`capabilities.py:472`). Measured: a UA-policy User-Agent gets 200 in 0.54 s. The
  challenge then escalates to the pooled browser anyway (`capabilities.py:232-241`), where
  `new_context()` / `new_page()` (`:564-565`) have no timeout, and the 25 s run budget cuts it.
  A `run_budget` park never calls `record_wall()` (`orchestrator.py:1759-1775`), so it repeats.
- **RC2 The crawl waits for its slowest URL.** `asyncio.gather` over all URLs
  (`orchestrator.py:1576`); `min_pages` is accepted and never read.
- **RC3 The quick tier returns empty results.** Exa returns `text` / `highlights` at the result's
  top level; `exa.py:~98` reads `r["content"]` -> every item has empty content and snippet
  (verified live). Separately, a module-cached `httpx.AsyncClient` (`exa.py:40`,
  `search_providers/__init__.py:69`) is reused across the fresh event loop each tool call runs in
  (`tool_decision.py:718-749`) -> "Event loop is closed" -> fallback to the full crawl.
- **RC4 Web goals are hard-routed to the heavy tool.** `_mem_lookup`
  (`agent_kernel.py:~15935`) returns `crawler_query` with the whole goal sentence as the query.
- **RC5 Redundant model passes.** `DataExtractor` (`data_extractor.py:117`) runs on the heavy
  `_respond_direct` path (episodic retrieval, possible tool attachment, 8-round loop) and its JSON
  is NOT what the agent consumes (`_format_tool_result` takes `content`, `agent_kernel.py:~15105`);
  it only feeds the dashboard `OPEN_TAB` payload. Four ~1 s `SourceRegistry._extract_topics`
  Brain calls per search on the same query (`crawl_planner.py:128,273`, `orchestrator.py:2487`,
  `tool_bridge.py:3510`) although a deterministic `quick=True` path exists (`source_registry.py:85`).
- **RC6 Output quality.** `goal_contract.extract_required` stores `--- Source: URL ---` lines as
  facts (`agent_kernel.py:18634`), which triggered a needless bonus pass in r02; a 14-token
  synthesis stub fell through to a raw source dump.
- **RC7 The agent has no browser-interaction tool.** `vision_*` tools capture the user's DESKTOP
  (`tools/vision_mcp_server.py`) and only describe; `gui_click`/`gui_type` are raw desktop x/y.
  The only code that clicks a page (`vision/fetch_vision.py` loop, Playwright `locator.click` /
  `fill` by a VLM-guessed selector from an unmarked screenshot) runs only as a failed-crawl
  fallback (`orchestrator.py:1327-1335`) and did not run once in ~2.5 days of logs.
- **RC8 The iframe is a mirror.** It shows HTML captures (`api/browser_surface.py:147-215`)
  published only on open / navigate / settle / popup / takeover (`browser_session.py:662,762,821,
  1192,1357`), so a click's result is invisible until the session ends. Vision events are emitted
  AFTER the action (`fetch_vision.py:446` then `:509`); failed actions are emitted as `ok`
  (`BrowserSession.act` swallows into `last_error`, never read).

## The event contract that MUST NOT break (owner goal 2)

Transport: agent path `_crawl_ui_emitter` (`tool_bridge.py:~4339`, message `type` = lowercased
event name) -> WebSocket -> `hooks/useIRISWebSocket.ts` re-dispatches as `iris:<type>`.

| Event | Consumers (keep working) |
|---|---|
| `CRAWLER_STARTED`, `CRAWLER_PAGE_FETCHED`, `CRAWLER_COMPLETE`, `CRAWLER_ERROR` | `hooks/useBrowserNavOverlay.ts`, `useCrawl`, dashboard tab creation |
| `OPEN_TAB` | `dark-glass-dashboard.tsx`, `useBrowserNavOverlay`, `useCrawl` |
| `CRAWLER_VISION_ACTION` | `useBrowserNavOverlay.ts:~234` (reads `kind`, `action_index`, `total`, `x`, `y` as 0..1 viewport fractions, `viewport_w`, `viewport_h`, `scroll_y`, `scroll_height`, `escalated`, `seq`, `run_id`; missing x/y = hold position), `useCrawl`, `terminalScrollback.ts` |
| `CRAWLER_PHASE`, `CRAWLER_PROGRESS`, `CRAWLER_SOURCES_ADDED`, `CRAWLER_SOURCE_PARKED` | `useCrawl`, `useTaskProgress` |
| `takeover_frame`, `browser:takeover_requested` | `TakeoverLiveSurface.tsx`, `useBrowserNavOverlay` |

New fields MAY be added. Existing names and fields MUST NOT be renamed or removed. (Rev 1's
`visionX` / `visionY` / `action_status` names appear in no producer or consumer - do not use them.)

---

## Requirements

### REQ-1: A factual lookup answers from search results without crawling
**User story:** As a user asking a quick factual question, I get the answer in seconds.

- AC1.1: THE Exa provider SHALL read each result's top-level `text` and `highlights` (keeping a
  `content.text` fallback), so a search item carries its content and snippet.
- AC1.2: THE search provider's HTTP client SHALL be valid on the event loop that calls it (no
  client bound to a closed loop); "Event loop is closed" SHALL NOT occur on repeated tool calls.
- AC1.3: WHEN a web goal is a factual lookup THEN THE SYSTEM SHALL call `search` (quick tier)
  first, with a query shaped from the goal, not the whole goal sentence; `crawler_query` is the
  escalation when the quick result is insufficient (RC4).
- AC1.4: THE quick tier SHALL return title, URL and snippet/content per source, plus
  `requires_deep_crawl: true` when the combined content is under 300 characters.
- **Measure:** r01, r02, r04, r08 reply_s; quick-tier `TOOL_DISPATCH duration_ms`.

### REQ-2: The crawl returns when it has enough, and never waits on a dead URL
- AC2.1: Tier-1 SHALL send a descriptive User-Agent that follows common bot policies (app name
  + contact URL, configurable via env), for page fetches AND robots.txt.
- AC2.2: A 401/403 with no challenge markers SHALL be classified `blocked` (not `challenge`), and
  SHALL be parked and recorded with `record_wall()` without a browser escalation.
- AC2.3: Browser escalation steps (`new_context`, `new_page`, `goto`) SHALL each have a bounded
  timeout inside the per-URL budget.
- AC2.4: WHEN `min_pages` usable pages are in (default 3) THEN THE SYSTEM SHALL stop waiting for
  the rest after a short grace (default 2 s), cancel them, and continue to extraction. Cancelled
  URLs are logged as `cancelled_enough`, not parked.
- AC2.5: The per-URL budget SHALL start when the URL starts, not before its semaphore wait.
- **Measure:** crawl phase time in r01 (was 36 s); Wikipedia pages usable (were 0/2).

### REQ-3: One model pass over the pages on the answer path
- AC3.1: In agent mode THE `DataExtractor` SHALL NOT run on the answer path. It runs on an
  ordered side lane (`backend/utils/durability_queue.lane`) after the tool result returns, and
  its `OPEN_TAB` dashboard payload is emitted when it lands (owner goal 2 preserved).
- AC3.2: The extractor's model call SHALL use the light inference path with tools disabled
  (as `source_registry.py:208` does), never `_respond_direct`.
- AC3.3: Topic extraction for the source registry SHALL use the deterministic `quick=True` path
  or a per-query cache: at most one model call per distinct query per turn.
- AC3.4: `goal_contract` fact extraction SHALL ignore source-header lines (`--- Source: ... ---`)
  and other page scaffolding.
- AC3.5: A synthesis result under the length floor SHALL retry once with the same inputs; it
  SHALL NOT fall through to a raw source dump.
- **Measure:** r01 time from `TOOL_DISPATCH` to reply (was ~30 s + 43 s extractor inside the tool).

### REQ-4: The agent can see and act on the page in the in-app browser (owner goal 3)
- AC4.1: THE SYSTEM SHALL offer agent-facing tools bound to ONE live Playwright page per
  conversation (the pooled browser): `browser_open(url)`, `browser_observe()`,
  `browser_act(action, element_id, text?)` with actions `click | type | select | scroll | back |
  press`.
- AC4.2: `browser_observe` SHALL return a Set-of-Marks list built from the DOM: every visible
  interactive element (links, buttons, inputs, selects, `[role=button]`, `[onclick]`,
  `[contenteditable]`) numbered 1..N with role, accessible name / text (trimmed), and bounding box;
  plus page title, URL and a short visible-text digest. A screenshot with the numbers drawn on it
  SHALL be attached only when a vision model is available.
- AC4.3: `browser_act` SHALL resolve `element_id` to the element's CURRENT bounding box (scroll
  into view, recompute), and act at its center with real mouse / keyboard input (Playwright
  `mouse.move` + `mouse.click`, `keyboard.type` with a per-key delay of 30-90 ms).
- AC4.4: An invalid or stale `element_id` SHALL return an error result naming the problem (never
  a silent success), and the agent SHALL be able to re-observe.
- AC4.5: Browser actions on one page SHALL be serialized by one lock per page.
- AC4.6: The planner / node SHALL see the `browser_*` tools for goals that need interaction
  (log in, fill a form, click through, use a site's own search, a page that only works in a
  browser), and the crawl SHALL be able to hand a page it cannot read to the same session.

### REQ-5: The user sees every action before it happens (owner goals 2 + 3)
- AC5.1: BEFORE each `browser_act` THE SYSTEM SHALL emit `CRAWLER_VISION_ACTION` with the
  existing fields (`kind`, `x`, `y` as 0..1 fractions of the viewport, `viewport_w`,
  `viewport_h`, `scroll_y`, `scroll_height`, `seq`, `run_id`, `action_index`, `total`) and the
  added field `phase: "approach"`; then wait the overlay travel time (default 180 ms) before the
  input.
- AC5.2: AFTER the action THE SYSTEM SHALL emit `CRAWLER_VISION_ACTION` with `phase: "done"` and
  `ok: true|false` (+ `error` when false). A failed action SHALL NOT be reported as `ok`.
- AC5.3: AFTER each action that changes the page, THE SYSTEM SHALL publish a fresh capture of the
  live page to the iframe (the existing capture store + `CRAWLER_PAGE_FETCHED` / `OPEN_TAB`
  flow), so the iframe follows the agent within one action.
- AC5.4: A frontend disconnect SHALL NOT block or fail a browser action.

### REQ-6: The Oracle earns web decisions (owner goal 4)
- AC6.1: Add Oracle consumers in SHADOW, each with a Brain/outcome reference label so rows are
  scorable: `web_depth` (options: `answer_from_snippets | crawl | interact`) at the point where
  the quick-tier result is judged, and `browser_next` (options: the observed element ids +
  `done`) inside the browser loop.
- AC6.2: A consumer acts only after it passes the bar (`scripts/consumer_enforcement_report.py`:
  rows >= 100, precision >= 0.90, ECE <= 0.05 on the active engine). No enforcement flag is
  flipped by this spec.

### REQ-7: Per-turn web timing is visible
- AC7.1: Every web tool call SHALL log one structured line with `search_ms`, `crawl_ms`,
  `pages_usable`, `pages_cancelled`, `extract_ms`, `browser_actions`, `cursor_events`.

---

## Out of scope (rev 1 items removed or deferred)

- "Caducean dual-wave with phase repulsion" on one CDP session (rev 1 REQ-2): replaced by one
  lock per page (AC4.5). The physics does not schedule browser I/O.
- Media ingestion (rev 1 REQ-10: audio-only yt-dlp, cookie handoff, transcript-guided frames):
  a separate spec.
- A self-driven Google/DuckDuckGo SERP harvest across 4 pages with anti-bot typing (rev 1 REQ-8):
  deferred. With REQ-4 the agent CAN use a search engine's page like any site; a dedicated
  SERP-harvest provider is a later decision, measured against Exa.
- Renaming or restructuring any frontend event.
- New search providers (SearXNG / Brave / DDG) - not needed for the measured problem.

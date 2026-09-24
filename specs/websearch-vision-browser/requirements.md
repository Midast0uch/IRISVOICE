# Requirements: Progressive WebSearch, In-App Browser & Vision System

## Decisions Locked

- **3-Tier Progressive Architecture:** The web intelligence pipeline is strictly tiered into:
  1. Tier 1: Instant Search API (HTTP REST, <400ms, zero browser spawn).
  2. Tier 2: Deep Targeted Crawl (Crawl4AI headless DOM scrape, 1.5s–3.5s).
  3. Tier 3: Interactive Vision Browser (Playwright CDP + Set-of-Marks VLM agent).
- **Caducean Concurrency for Web Tasks:** Reject disjoint sequential fallback modes. When a deep or interactive web task is active, Headless Crawl (Wave 1, $\theta_1 = 0^\circ$) and Interactive Vision (Wave 2, $\theta_2 = 180^\circ$) run concurrently on the same browser session via CDP. Phase repulsion ($\sin(\theta_i - \theta_j)$) prevents browser action collisions.
- **Set-of-Marks (SoM) over Raw Coordinates:** Raw $(x, y)$ coordinate prediction by VLMs is rejected due to image downsampling and DPI scaling errors. The browser extracts interactive elements via the CDP accessibility tree, paints numbered badges (`[1]`, `[2]`, `[3]`), and the VLM returns the discrete ID. The backend extracts the true DOM bounding box center $(cx, cy)$ and emits it.
- **Particle Cursor Saccadic Pre-Glide:** The backend emits `CRAWLER_VISION_ACTION` *before* executing the mouse click or keyboard input. This gives the frontend `BrowserNavigationOverlay.tsx` the exact coordinates and travel time (`SACCADIC_TRAVEL_MS = 180ms`) to animate the 3-shell particle cursor.
- **Goal Preservation via NodeRecord:** The invariant user goal is locked in `NodeRecord.objective_anchor`. Intermediate knowledge accumulates in `content_summary`. Gaps are tracked in `remaining`. Findings fold back via `folded_back`. Messages across separate agent processes use `ToolRequest` and `ToolResponse` envelopes carrying `user_intent` and `prior_results`.
- **Decision Engine as Sub-50ms Micro-Dispatcher:** The resident `LFM2-350M-Extract` model acts as an in-process micro-dispatcher. It evaluates whether `content_summary` satisfies `expected_output` to short-circuit the task, or routes visual roadblocks directly to the Vision Agent in <50ms without invoking the heavy Brain LLM.
- **Autonomous Human-Like SERP Navigation:** The agent can navigate directly to Google or DuckDuckGo in the in-app browser tab. It extracts live organic result links and snippets via the DOM and Set-of-Marks, eliminating reliance on third-party APIs (`EXA_API_KEY`) and preventing dead or hallucinated URLs from LLM training weights (`search_providers/llm.py`).
- **Optimized Media Ingestion Pipeline:** When consuming YouTube or media URLs, the agent retrieves only the compressed audio stream (`bestaudio/best`) for Parakeet speech-to-text processing, bypassing multi-gigabyte video downloads. The downloader shares cookies with the active Playwright Chromium browser session to bypass YouTube bot detection. Visual keyframes are extracted strictly at timestamps correlated with slide, equation, or diagram mentions in the Parakeet transcript, eliminating blind 1.0s interval frame dumps.

## Introduction

IRIS web intelligence currently suffers from architectural coupling and dormant visual features. The `search` tool erroneously executes the heavy multi-page Crawl4AI browser orchestrator, taking 8–15 seconds for simple lookups. The 3-shell particle cursor in `BrowserNavigationOverlay.tsx` is completely dormant because crawl loops discard non-page events and relegate vision to a post-mortem bot-wall error handler. Furthermore, there is no concurrent collaboration between DOM scraping and visual inspection.

This feature decouples instant search into a sub-400ms HTTP REST pipeline, introduces Caducean dual-wave concurrency for browser tasks, enables Set-of-Marks element interaction with pixel-perfect coordinate streaming, deploys the resident Decision Engine as a sub-50ms micro-dispatcher, and introduces autonomous human-like SERP navigation in the in-app browser tab.

### Success Criteria

- **Instant Search Latency:** `search(query)` p50 latency ≤ 400ms (down from 8,000ms+), spawning 0 browser subprocesses.
- **Deep Crawl Latency:** `crawler_query` p50 latency ≤ 3.0s by targeting authoritative URLs from search rather than speculative LLM planning.
- **Particle Cursor Activation:** 100% of interactive vision actions emit `CRAWLER_VISION_ACTION` with normalized coordinates $(x, y)$, animating the frontend particle cursor along a saccadic trajectory.
- **VLM Interaction Accuracy:** ≥ 95% successful element clicks on dynamic SPAs using Set-of-Marks (SoM) element tagging, compared to < 65% with raw coordinate prediction.
- **Autonomous SERP Extraction:** 100% of live Google / DuckDuckGo searches in the in-app browser extract fresh organic URLs without calling Exa API or generating hallucinated URLs from LLM training memory.
- **Zero Goal Degradation:** 100% of inter-agent messages between Brain, Tool Executor, and Vision Agent preserve `user_intent` and `objective_anchor`.
- **Micro-Dispatch Latency:** Decision Engine action selection and short-circuit evaluation p50 ≤ 50ms on CPU.

---

## Requirements

### REQ-1: Decoupled Instant Search Provider
**User Story:** As a user asking a quick factual question I want instant search results so that I get answers in under 400ms without waiting for a browser to launch.

**Verified:** NEW (currently `tool_bridge.py:3459` invokes `CrawlOrchestrator().research(...)`).

**Acceptance Criteria:**
- AC1.1: THE SYSTEM SHALL execute `search(query)` via a lightweight HTTP REST provider without launching Chromium or Playwright subprocesses.
- AC1.2: WHEN `search(query)` executes THEN THE SYSTEM SHALL return top source snippets and URLs in less than 400ms p50.
- AC1.3: THE SYSTEM SHALL format search results as structured markdown containing title, URL, and snippet.
- AC1.4: IF the extracted snippets contain fewer than 300 characters or explicitly state content is truncated THEN THE SYSTEM SHALL set `requires_deep_crawl = True` in the tool output payload.

**Edge Cases:**
- Empty or whitespace query → Return validation error immediately without network call.
- HTTP provider timeout or 429 → Fallback gracefully to secondary search provider or return empty results without crashing.

---

### REQ-2: Caducean Dual-Wave Parallel Web Execution
**User Story:** As the agent loop I want headless DOM extraction and visual inspection to run concurrently on the same page so that visual gaps are filled without redundant re-crawling or sequential delays.

**Verified:** NEW (currently `orchestrator.py:1316` executes `_escalate_to_vision` only after crawl fails).

**Acceptance Criteria:**
- AC2.1: WHEN a deep web task executes THEN THE SYSTEM SHALL attach both the Headless DOM Crawler (Wave 1) and the Vision Inspector (Wave 2) to the same Chrome DevTools Protocol (CDP) session.
- AC2.2: THE SYSTEM SHALL assign distinct Caducean phase angles to Wave 1 ($\theta_1 = 0^\circ$) and Wave 2 ($\theta_2 = 180^\circ$) governed by `docs/CADUCEAN_CONCURRENCY_MODEL.md`.
- AC2.3: WHILE Wave 1 extracts DOM text into `content_summary`, Wave 2 SHALL inspect the rendered viewport for visual elements missing from the DOM (canvas, SVG, dynamic SPAs, modal overlays).
- AC2.4: THE SYSTEM SHALL apply phase repulsion force $\sin(\theta_i - \theta_j)$ to prevent Wave 1 and Wave 2 from dispatching conflicting browser actions at the same point in time.

**Edge Cases:**
- Simple static text page → Wave 1 completes and satisfies `expected_output`; Wave 2 is cancelled before executing actions.
- Anti-bot interstitial appears → Wave 1 pauses; Wave 2 solves challenge and signals Wave 1 to resume.

---

### REQ-3: Set-of-Marks (SoM) Element Interaction & Bounding Box Resolution
**User Story:** As the vision agent I want interactive elements tagged with clear numeric identifiers so that I can click and type into elements with >95% accuracy without pixel coordinate hallucinations.

**Verified:** NEW (currently `fetch_vision.py:341-455` relies on raw coordinate or heuristic DOM selectors).

**Acceptance Criteria:**
- AC3.1: THE SYSTEM SHALL extract interactive elements (buttons, inputs, links, dropdowns) from the browser accessibility tree using CDP.
- AC3.2: THE SYSTEM SHALL render visual marker badges (`[1]`, `[2]`, `[3]`) over the bounding boxes of interactive elements on the screenshot provided to the VLM.
- AC3.3: WHEN the VLM selects an action THEN THE SYSTEM SHALL parse the discrete element ID (e.g., `{"action": "click", "element_id": 4}`).
- AC3.4: THE SYSTEM SHALL resolve the element ID to its ground-truth DOM bounding box and compute the exact center coordinates $(cx, cy)$.
- AC3.5: THE SYSTEM SHALL execute the browser action (click, type, hover) at the exact computed center $(cx, cy)$.

**Edge Cases:**
- VLM outputs an invalid element ID → Fallback to heuristic DOM selector matching or request a re-observation.
- Element scrolls out of view before action → Auto-scroll element into viewport and recompute coordinates before clicking.

---

### REQ-4: Frontend Particle Cursor & Saccadic Pre-Glide
**User Story:** As a user watching the in-app browser I want to see the 3-shell particle cursor glide smoothly to elements before they are clicked so that I can visually verify what the agent is doing.

**Verified:** NEW (currently `orchestrator.py:1290` filters out all non-page events, leaving `BrowserNavigationOverlay.tsx` permanently dormant).

**Acceptance Criteria:**
- AC4.1: WHEN an action has a resolved target $(cx, cy)$ THEN THE SYSTEM SHALL emit a `CRAWLER_VISION_ACTION` WebSocket event prior to action execution with normalized coordinates `visionX = cx / viewportWidth`, `visionY = cy / viewportHeight`, and `action_status = "approaching"`.
- AC4.2: THE SYSTEM SHALL preserve `CRAWLER_VISION_ACTION` events through the `CrawlOrchestrator` forwarder (`orchestrator.py:1290`) without dropping or filtering them.
- AC4.3: WHEN the frontend receives `CRAWLER_VISION_ACTION` THEN `BrowserNavigationOverlay.tsx` SHALL animate the particle cursor from its current position to $(visionX, visionY)$ along a saccadic trajectory over 180ms.
- AC4.4: WHEN the action completes THEN THE SYSTEM SHALL emit `CRAWLER_VISION_ACTION` with `action_status = "completed"`, triggering the element click burst effect on the canvas.

**Edge Cases:**
- WebSocket disconnection during crawl → Action execution proceeds on backend without blocking on frontend animation.
- Rapid successive actions → Saccadic curve dynamically repaths from current interpolated position to new target.

---

### REQ-5: Multi-Agent Goal & Information Propagation
**User Story:** As an operator running multi-agent tasks I want search goals and intermediate results reliably passed between Brain, Tool Executor, and Vision Agent so that context is never lost across delegation hops.

**Verified:** NEW (formalizes the `NodeRecord` memory contract across web search tools).

**Acceptance Criteria:**
- AC5.1: THE SYSTEM SHALL initialize every web task node with an immutable `objective_anchor` defining the user's primary goal.
- AC5.2: WHEN delegating across agent processes THEN THE SYSTEM SHALL wrap requests in `ToolRequest` carrying `user_intent`, `step_rationale`, and `prior_results`.
- AC5.3: WHEN receiving tool results THEN THE SYSTEM SHALL update `content_summary` with extracted facts and `remaining` with unresolved queries.
- AC5.4: WHEN child vision steps complete THEN THE SYSTEM SHALL fold their observations back into the parent `NodeRecord.folded_back` list.
- AC5.5: IF the Brain Agent runs as all three roles in-process THEN THE SYSTEM SHALL read and mutate `NodeRecord` directly in memory without serialization overhead.

**Edge Cases:**
- Sub-agent returns truncated or malformed JSON → Parse with `OutputParser` 5-format priority chain; preserve original text in `output_data`.
- Long multi-step task exceeding token limit → Bounded memory condensation preserves `objective_anchor` while summarizing `content_summary`.

---

### REQ-6: Decision Engine Micro-Dispatcher & Short-Circuit Gate
**User Story:** As the runtime I want the resident 350M Decision Engine to handle high-frequency browser micro-decisions so that the system operates at low latency without invoking the heavy Brain LLM on every step.

**Verified:** NEW.

**Acceptance Criteria:**
- AC6.1: THE DECISION ENGINE SHALL evaluate candidate micro-actions (`crawl_dom`, `vision_click`, `scroll`, `synthesize`) in a single forward pass with latency ≤ 50ms on CPU.
- AC6.2: AFTER each DOM extraction step, THE DECISION ENGINE SHALL evaluate whether `content_summary` satisfies `NodeRecord.expected_output`.
- AC6.3: WHEN `expected_output` is satisfied THEN THE DECISION ENGINE SHALL short-circuit the web task directly to synthesis, bypassing further vision or crawl actions.
- AC6.4: WHEN a visual barrier or empty DOM is detected THEN THE DECISION ENGINE SHALL route the task to Wave 2 Vision in ≤ 50ms without invoking the external Brain LLM.

**Edge Cases:**
- Decision Engine confidence below threshold (0.85) → Escalate micro-decision to primary reasoning model via existing fallback ladder.
- Ambiguous satisfaction criteria → Default to conservative continuation until maximum step budget is reached.

---

### REQ-7: Observability & Web Latency Instrumentation
**User Story:** As the tuner I want detailed latency and event metrics across search, crawl, vision, and cursor paths so that I can verify sub-second targets.

**Verified:** NEW.

**Acceptance Criteria:**
- AC7.1: THE SYSTEM SHALL log structured JSON metrics for every web turn containing `search_latency_ms`, `crawl_latency_ms`, `vision_step_count`, `cursor_event_count`, and `decision_engine_dispatch_ms`.
- AC7.2: THE SYSTEM SHALL record Caducean phase angles ($\theta_1, \theta_2$) and collision avoidance events in the event ledger.
- AC7.3: THE SYSTEM SHALL emit telemetry counter `web_quick_search_short_circuits` whenever Tier 1 satisfies a query without escalating to Tier 2/3.

**Edge Cases:**
- High-volume telemetry → Logging runs off the critical async path and never blocks browser I/O.

---

### REQ-8: Autonomous In-App Browser Search & Headless Handoff Pipeline
**User Story:** As a user I want the agent to type queries naturally into Google or DuckDuckGo inside the in-app browser tab, harvest candidate links across the first 4 pages, filter out SEO spam, and hand the best URLs to headless crawl so that the system evades bot detection and finds high-quality information without paid search APIs.

**Verified:** NEW (currently `backend/crawler/search_providers/llm.py` hallucinates URLs from training data and `backend/crawler/search_providers/exa.py` requires external paid API keys).

**Acceptance Criteria:**
- AC8.1: WHEN executing autonomous in-app browser search THEN THE SYSTEM SHALL navigate to the search engine homepage and type the goal query into the search input using randomized keystroke intervals (40–110ms) and saccadic cursor movement to prevent bot detection.
- AC8.2: THE SYSTEM SHALL mirror the search page in the in-app browser tab iframe and harvest candidate search results across the first 3 to 4 result pages (gathering 20–40 candidate URLs, titles, and snippet descriptions).
- AC8.3: THE SYSTEM SHALL filter harvested candidate links by stripping sponsored advertisements (`[Sponsored]`), affiliate redirects, duplicate domains, and keyword-stuffed SEO scraper farms.
- AC8.4: THE SYSTEM SHALL score and rank candidate URLs using `backend/crawler/credibility.py` (`_SOURCE_TYPES`, domain authority scoring) and select the top 3–5 most authoritative, high-signal destination URLs.
- AC8.5: THE SYSTEM SHALL hand off the top 3–5 curated destination URLs to the parallel Headless Crawler (`fetch.crawl` / `Crawl4AI`) for high-throughput text extraction, with visual fallback only if a destination page contains an interactive roadblock.

**Edge Cases:**
- Search engine displays a cookie banner or bot verification → Vision Agent clicks "Accept all" or solves challenge using Set-of-Marks.
- Zero search results returned → Fallback to secondary search engine (DuckDuckGo / Bing) or query reformulation.

---

### REQ-9: Recursive Query Refinement, Canonical URL Deduplication & Anti-Circling
**User Story:** As the agent loop I want the search engine to refine keywords, paginate deeper, and deduplicate visited URLs when initial results are incomplete, so that the agent discovers fresh information without repeating failed searches or re-crawling duplicate pages.

**Verified:** NEW (formalizes recursive refinement with `backend/agent/agent_kernel.py:14438` CIRCLING prevention).

**Acceptance Criteria:**
- AC9.1: WHEN `content_summary` fails to satisfy `NodeRecord.objective_anchor` and `remaining` contains unresolved items THEN THE AGENT SHALL formulate a refined search query targeting the specific missing criteria.
- AC9.2: THE SYSTEM SHALL maintain a session-scoped `visited_urls` set and a canonicalization normalizer that strips tracking parameters (`utm_*`, `ref`, `fbclid`, `gclid`), fragments (`#`), and trailing slashes.
- AC9.3: WHEN harvesting SERP links across repeated search cycles THEN THE SYSTEM SHALL filter out all URLs present in `visited_urls`, `NodeRecord.ruled_out`, or the active document store, admitting only novel unvisited links.
- AC9.4: IF candidate links on pages 1–4 are predominantly already visited or ruled out THEN THE AGENT SHALL advance SERP pagination to subsequent pages (pages 5–8) or execute a keyword pivot.
- AC9.5: THE SYSTEM SHALL enforce a maximum refinement limit (`MAX_SEARCH_REFINEMENTS = 3`); IF the goal remains unfulfilled after 3 iterations THEN THE SYSTEM SHALL synthesize accumulated findings and state the unresolved gaps honestly without looping.

**Edge Cases:**
- All candidate links on all paginated pages are duplicates → Trigger query broadening or prompt user for clarification.
- Transient network error on refinement → Preserve existing `content_summary` and synthesize partial answer.

---

### REQ-10: Autonomous Media Ingestion (Audio Stream, Transcript-Guided Keyframes & Cookie Handoff)
**User Story:** As an agent processing YouTube or web video tasks I want to extract audio directly for fast Parakeet transcription and capture visual frames only at slide/diagram timestamps so that video understanding executes in seconds without downloading multi-gigabyte video files or flooding the vision model with thousands of redundant images.

**Verified:** NEW (currently `media_source.py:73` downloads `best[ext=mp4]/best` and `media_tools.py:69` extracts 1 frame per second sequentially).

**Acceptance Criteria:**
- AC10.1: THE SYSTEM SHALL support audio-only stream extraction (`format: "bestaudio/best"`, `ext: "m4a"` or `"opus"`) in `backend/agent/media_source.py` for speech-to-text processing, bypassing multi-gigabyte video file downloads.
- AC10.2: THE SYSTEM SHALL export and pass active Chromium browser session cookies from `backend/browser/chromium_browser_manager.py` to `yt-dlp`, bypassing YouTube bot challenges and sign-in walls.
- AC10.3: THE SYSTEM SHALL correlate the Parakeet timestamped transcript with slide, diagram, equation, and code mentions, extracting visual keyframes *only* at those identified timestamps (capping total extracted frames to ≤ 10 per 30-minute video).
- AC10.4: In `backend/tools/media_tools.py`, THE SYSTEM SHALL accept explicit timestamp lists (`timestamps: List[float]`) in `analyze_video_frames`, extracting frames strictly at targeted points rather than at uniform 1.0s intervals.
- AC10.5: In the in-app browser tab, THE SYSTEM SHALL support autonomous YouTube search and navigation, selecting top video candidate links via Set-of-Marks, extracting the canonical video URL, and passing the URL to the media ingestion pipeline.

**Edge Cases:**
- Video has no audio track → Fail fast with `EMPTY_AUDIO` outcome without invoking Parakeet.
- Transcript identifies 0 slide/diagram mentions → Extract first frame (title slide) and middle frame as fallback.
- YouTube bot challenge blocks stream URL → Surface browser session authentication prompt in in-app browser tab.

---

## Non-Requirements (Out of Scope)

- Replacing Crawl4AI or Playwright with custom browser engines.
- Replacing the Next.js frontend or Tailwind CSS styling.
- Adding third-party hosted router APIs (e.g., Laya hosted cloud services).
- Modifying the underlying Tauri desktop window frame or system tray architecture.

---

## Decisions Locked Summary

1. Instant search uses pure HTTP REST (no browser spawn).
2. Dual-wave concurrency runs on the same CDP session via Caducean phase separation.
3. Element interaction uses Set-of-Marks with ground-truth coordinate emission.
4. Particle cursor pre-glide is emitted before action execution.
5. Invariant goal state travels in `NodeRecord.objective_anchor`.
6. Resident 350M Decision Engine acts as the sub-50ms micro-dispatcher.
7. Autonomous SERP navigation in in-app browser tab extracts live URLs without Exa API or LLM hallucinations.
8. Recursive query refinement enforces canonical URL deduplication and caps iterations at 3 to prevent circling.
9. Media ingestion downloads audio-only streams for Parakeet and samples keyframes strictly at transcript-guided timestamps using shared browser session cookies.

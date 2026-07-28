# Requirements: Cross-Thread Document Isolation + Crawl Reliability

## Decisions Locked
- Documents are stored per-conversation in frontend state (Option B), matching how messages already work.
- The `document:render` payload from backend already includes `conversation_id` (`agent_kernel.py:3065`). Frontend simply ignores it. Fix: store in conversation.documents array.
- Crawl4AI uses headless Chromium with realistic browser headers (User-Agent, Accept-Language, Sec-Fetch-*). Always-on, no toggle.
- Exa retry uses a broader/rewritten query on second attempt, user-visible status message.
- The crawl pipeline retries failed URLs with Exa-expanded sources before declaring failure.
- TaskListCard renders when `taskProgress.steps.length > 0` (`chat-view.tsx:2697`). Need to verify the event pipeline from EventBus → WSEventBridge → WebSocket → useTaskProgress hook. Events may carry `conversation_id` from backend but frontend may not filter by active conversation.

## Introduction
Two problems were found in Session 166 live testing:
1. Rendered documents (prism cards) from previous conversations leak into new threads — thread isolation is broken.
2. Websearch frequently returns no results because crawl4ai gets blocked by bot detection, and there's no retry with additional URLs when the first batch fails.

### Success criteria
- A new conversation thread shows ONLY documents created in that thread.
- Crawl4AI successfully fetches content from sites that previously returned 403/timeout.
- When the first batch of crawl URLs fails, the system automatically retries with additional URLs from Exa.

## Requirements

### REQ-1: Per-Conversation Document Storage (Frontend)
**User Story:** As a user I want rendered documents scoped to their conversation thread so that switching threads doesn't show stale cards from other conversations.

**Verified:** Verified gap — `components/chat-view.tsx:219` stores documents in flat `renderedDocuments: DocRender[]` state shared across ALL conversations. The backend `document:render` payload includes `conversation_id` (`agent_kernel.py:3065`) but frontend handler (`chat-view.tsx:522-533`) does NOT extract or use it.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL store `documents: DocRender[]` inside each conversation object alongside `messages: Message[]` (Option B).
- AC2: THE SYSTEM SHALL extract `conversation_id` from the `document:render` payload and append the document to the matching conversation's documents array.
- AC3: WHEN the user switches conversation threads THEN THE SYSTEM SHALL display only the documents from the active conversation's documents array.
- AC4: WHEN a new `document:render` event arrives THEN THE SYSTEM SHALL append it to the active conversation's documents array (not the flat array).
- AC5: THE SYSTEM SHALL persist conversation documents in localStorage alongside messages.

**Edge Cases:**
- Empty conversation (no documents yet) → empty document list, no crash.
- Document arrives with `conversation_id` that doesn't match any known conversation → discard silently, log warning.
- Document arrives without `conversation_id` → discard and log warning (protocol contract violation).
- Conversation loaded from localStorage has no `documents` field (migration from flat array) → default to empty array.
- `renderedDocuments` ref used for duplicate detection (`chat-view.tsx:1094`) must be updated to check per-conversation, not global.

### REQ-2: Document Hydration on Conversation Switch
**User Story:** As a user I want my documents to appear instantly when I switch back to a previous conversation so that the experience is seamless.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: WHEN the active conversation changes THEN THE SYSTEM SHALL render only `conversation.documents` for the active conversation.
- AC2: WHEN documents are hydrated from the backend (get_documents) THEN THE SYSTEM SHALL store them in the active conversation's documents array.
- AC3: THE SYSTEM SHALL NOT merge documents across conversation boundaries.

**Edge Cases:**
- Backend returns documents for wrong conversation ID → discard and log warning.
- Network failure during hydration → show empty document list, retry on next switch.

### REQ-3: Headless Browser Crawl with Stealth Headers (Backend)
**User Story:** As a system I want to crawl websites using a real headless browser so that I can bypass bot detection and reliably fetch content.

**Verified:** Verified gap — `crawler_engine.py:138-141` uses `BrowserConfig(headless=True, user_agent=IRIS-Agent/1.0)` with a bot-like user-agent. Sites like nasa.gov block this immediately. The `user_agent` field is cosmetic only — it doesn't set real browser headers.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL configure crawl4ai with `BrowserConfig` that sets `headless=True` and launches a real Chromium browser instance.
- AC2: THE SYSTEM SHALL set a real Chrome user-agent string (e.g. `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ... Chrome/131.0.0.0 Safari/537.36`).
- AC3: THE SYSTEM SHALL set realistic browser headers including Accept-Language, Accept-Encoding, and Sec-Fetch-* headers to match what a real Chrome browser sends.
- AC4: THE SYSTEM SHALL rotate user-agent strings from a pool of common browser agents across requests to avoid fingerprinting.
- AC5: WHEN a crawl returns 403 or Cloudflare challenge THEN THE SYSTEM SHALL retry once with a different user-agent before recording the failure.
- AC6: THE SYSTEM SHALL NOT use any付费 proxy services — all stealth measures must be local browser configuration only.

**Edge Cases:**
- crawl4ai version doesn't support stealth features → graceful fallback to current behavior with warning log.
- All user-agents blocked → record failure, don't infinite retry.
- Browser launch fails with stealth config → fallback to basic config, log warning.
- Chromium not installed → log clear error with install instructions, don't crash.

### REQ-4: Exa URL Retry with Expanded Query (Backend)
**User Story:** As a system I want to retry with additional URLs when the first crawl batch fails so that the user gets results instead of an error message.

**Verified:** Verified gap — `orchestrator.py:160-162` returns "no candidate urls" on empty plan. `crawl_planner.py:186-192` returns immediately when LLM produces no URLs. No retry with Exa.

**Acceptance Criteria:**
- AC1: WHEN all URLs in a crawl batch return errors (403/404/timeout) THEN THE SYSTEM SHALL query the search provider (Exa or LLM) with a rewritten/broader query to obtain additional URLs.
- AC2: WHEN retrying with additional URLs THE SYSTEM SHALL exclude URLs already attempted in the first batch.
- AC3: THE SYSTEM SHALL cap total retry attempts at 2 (initial + 1 retry) to bound latency.
- AC4: WHEN the retry also fails THEN THE SYSTEM SHALL return the original error with a note that retry was attempted.
- AC5: THE SYSTEM SHALL log each retry attempt with the original query, rewritten query, and URL count for observability.
- AC6: WHEN retrying with additional URLs THE SYSTEM SHALL display a user-visible status message (e.g. "Narrowing search...") so the user knows a retry is in progress.

**Edge Cases:**
- Search provider is rate-limited (429) → respect Retry-After header, fall back to error message.
- Rewritten query produces same URLs → deduplicate, return error.
- Search provider unavailable → skip retry, return original error.

### REQ-6: Websearch TaskListCard with Progress Indicator
**User Story:** As a user I want to see a dedicated websearch card with a searching icon/effect during a crawl so that I know the system is actively searching, while the "thinking..." indicator is reserved for normal LLM responses.

**Verified:** Verified gap — Session 166 testing confirmed TaskListCard did NOT appear during websearch. Only "thinking..." was shown, which is indistinguishable from a normal chitchat response.

**Audit findings:**
- TaskListCard renders at `chat-view.tsx:2697` when `taskProgress.steps.length > 0`
- `useTaskProgress` hook (`hooks/useTaskProgress.ts`) listens for `window "iris:task_update"` events
- Backend emits `task:start` with `steps[]` and `conversation_id` (`agent_kernel.py:5349-5372`)
- WSEventBridge (`backend/agent/ws_event_bridge.py`) broadcasts ALL events to the WebSocket client (no conversation_id filter)
- Frontend WebSocket handler (`useIRISWebSocket.ts:1361`) dispatches `iris:task_update` with full payload
- Possible causes: (a) useTaskProgress may filter by conversation_id incorrectly, (b) steps array may arrive empty on first event, (c) REST response may clear state before TaskListCard renders

**Acceptance Criteria:**
- AC1: WHEN a websearch prompt is sent THEN THE SYSTEM SHALL display a dedicated websearch TaskListCard with a searching icon/effect (e.g. globe spinning or magnifying glass animation) INSTEAD of the generic "thinking..." indicator.
- AC2: THE SYSTEM SHALL reserve the "thinking..." indicator for normal chitchat/LLM-only responses that do not involve crawling.
- AC3: WHEN the crawl is in progress THEN THE SYSTEM SHALL update the websearch TaskListCard to show current step (e.g. "Searching 3 sources..." or "Reading nasa.gov...").
- AC4: WHEN the crawl completes or fails THEN THE SYSTEM SHALL update the websearch TaskListCard to show final status (e.g. "Found 2 results" or "No results found").
- AC5: THE SYSTEM SHALL NOT show only "thinking..." during a websearch — the websearch TaskListCard must appear within 5 seconds of prompt send and replace the "thinking..." state.
- AC5: THE USE TASK PROGRESS hook SHALL NOT filter events by `conversation_id` until per-conversation task isolation is explicitly required.
- AC6: THE SYSTEM SHALL log `iris:task_update` events at debug level so the event pipeline can be verified.

**Edge Cases:**
- Websearch TaskListCard component not mounted → fallback to "thinking..." indicator (graceful degradation).
- WebSocket disconnects during websearch → websearch TaskListCard stays at last known state with frozen animation, doesn't crash.
- Steps array empty on `task:start` → websearch TaskListCard shows "Starting search..." with indeterminate spinner.
- Multiple websearches in same conversation → websearch TaskListCard updates for the latest search only; previous card is consumed into history.

### REQ-7: Observability for Crawl Pipeline (was REQ-5)
**User Story:** As the tuner I want timestamped logs scoped by crawl job so that I can measure crawl success rates and identify persistent blockers.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log a structured entry for each crawl attempt including: job_id, query, URL count, success/fail per URL, user-agent used, retry count, total duration.
- AC2: THE SYSTEM SHALL log stealth mode activation/deactivation so blocked-vs-clean fetches are distinguishable.
- AC3: THE SYSTEM SHALL log Exa retry attempts with original vs rewritten query.

**Edge Cases:**
- Log volume high → off critical path, use async logging.

### REQ-8: Conversational Crawl Narration with Content Snippets
**User Story:** As a user I want the agent to speak less frequently and more conversationally during websearch, sharing actual information it finds rather than robotic status updates.

**Verified:** Verified gap — Current narration during websearch fires every ~3 seconds:
- Page-fetch narration: `"Fetched page N of M — {host}"` every ~8s (`tool_bridge.py:1736`, `_NARRATION_COOLDOWN_S = 8.0`)
- Generic heartbeat: `"Still researching the web."` every ~12s (`narration.py:89`, `_HEARTBEAT_INTERVAL_S = 12`)
- With overlapping page fetches every ~3s, these interleave and the user hears 6-8 utterances in a 30s crawl
- The `CRAWLER_PAGE_FETCHED` payload only has `url`, `page_number`, `total`, `host` — NO `title` or content snippet (`orchestrator.py:275-281`)
- But the page title IS extracted in `crawler_engine.py:245` during crawl — just not passed to the event
- Page content (markdown) IS available at the time `CRAWLER_PAGE_FETCHED` fires but no snippet is extracted

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL include `title` in the `CRAWLER_PAGE_FETCHED` payload so narration can use the actual page title instead of the hostname.
- AC2: THE SYSTEM SHALL include a short content `snippet` (first meaningful 120-180 chars from page markdown) in the `CRAWLER_PAGE_FETCHED` payload for conversational narration.
- AC3: THE SYSTEM SHALL increase narration cooldown between crawl speech updates from 8s to at least 25s so the agent doesn't chatter excessively (currently speaks ~6-8 times in a 30s crawl).
- AC4: THE SYSTEM SHALL replace "Fetched page N of M — {host}" with conversational phrasing that mentions something from the snippet, e.g. "I'm reading an article on {title} which mentions {snippet}..."
- AC5: THE SYSTEM SHALL replace the generic "Still researching the web." heartbeat with a message that includes actual progress, e.g. "I just finished reading a page about {title} from {host}..."
- AC6: THE SYSTEM SHALL NOT repeat the same domain/host in back-to-back narrations — rotate to avoid monotony.
- AC7: WHEN the crawl is complete THE SYSTEM SHALL speak a brief summary of the most interesting finding rather than "Crawl complete."

**Edge Cases:**
- Page has no title → fall back to domain name, speak the snippet.
- Page has no meaningful content/extraction failed → skip narration for that page entirely.
- All pages crawled very quickly (< 25s) → only speak 1-2 times total during the crawl.
- Multiple pages from same host → deduplicate host mention; speak about different topics.
- Snippet contains sensitive/truncated text → truncate cleanly at sentence boundary.
- No interesting snippets found across all pages → speak a single "I've searched several sources..." summary instead of per-page narration.

### REQ-9: Follow-Up Questions During Active Crawl
**User Story:** As a user I want to ask a chitchat question while a websearch is running so that I don't have to wait 30-60 seconds for the crawl to finish before getting a response.

**Verified:** Verified gap — The REST `/api/chat` endpoint (`backend/api/chat.py:381-388`) awaits `_run_agent_kernel()` which runs the full DER loop sequentially. The agent kernel has no concurrency lock or busy state (`agent_kernel.py` — no `asyncio.Lock` or `threading.Lock` found). Two concurrent REST requests for the same `thread_id` would race on the same kernel instance. No mechanism exists to run a crawl in the background while accepting new user input.

**Acceptance Criteria:**
- AC1: WHEN a websearch crawl is in progress AND the user sends a new message THEN THE SYSTEM SHALL process the new message (chitchat) in a new DER loop while the background crawl continues independently.
- AC2: THE SYSTEM SHALL spawn the crawl as a background `asyncio.Task` so it doesn't block new user messages.
- AC3: WHEN the background crawl completes THEN THE SYSTEM SHALL push the results via WebSocket (`document:render` events) so the frontend displays them without a page reload.
- AC4: THE SYSTEM SHALL return the chitchat response immediately via the REST endpoint while the crawl runs independently in the background.
- AC5: THE SYSTEM SHALL NOT execute a second crawl while one is already running for the same conversation — queue or reject with "Crawl in progress."
- AC6: THE SYSTEM SHALL maintain a per-conversation lock so concurrent writes (document storage, memory) don't race.

**Edge Cases:**
- User sends 3 chitchat messages during a single crawl → all 3 answered in order. Crawl results arrive after the last chitchat response.
- Crawl finishes while chitchat response is being generated → queue crawl results and push via WS after chitchat response is sent.
- User switches conversation threads during a background crawl → crawl continues for original thread; results push to original conversation.
- User sends another websearch while one is running → second crawl rejected with "Crawl in progress."
- Backend crashes during background crawl → partial results lost. Acceptable for v1.
- REST request for chitchat times out → background crawl continues; results push via WS when done.

## Non-Requirements (Out of Scope)
- Proxy rotation or付费 proxy services.
- Headless browser fingerprint spoofing beyond user-agent and headers.
- Changes to the backend document_store.py schema (it already has conversation_id).
- Changes to the LLM context window or memory isolation (separate investigation).
- Crawl4AI JavaScript rendering (not needed for static content sites).
- Parallel execution of MULTIPLE crawls for the same conversation — only one crawl at a time per conversation.
- Background crawl results for a conversation the user has navigated away from — results still push to original conversation; no cross-conversation forwarding.

## Open Questions
- None — all decisions locked.

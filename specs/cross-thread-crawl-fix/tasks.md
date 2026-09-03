# Tasks: Cross-Thread Document Isolation + Crawl Reliability

> Each task links to a requirement. Group into waves for parallel execution.

## Wave 1 — Frontend Document Isolation
- [ ] T1 (REQ-1): Add `documents: DocRender[]` to Conversation interface — `components/chat-view.tsx:119-128` — RIPPLE: localStorage migration, any component that reads Conversation type
- [ ] T2 (REQ-1): Initialize `documents: []` in new conversation creation — `components/chat-view.tsx` (handleNewConversation) — RIPPLE: none
- [ ] T3 (REQ-1): Default `documents` to `[]` for conversations loaded from localStorage (migration from flat array) — `components/chat-view.tsx` (localStorage hydration) — RIPPLE: check if old `renderedDocuments` in localStorage needs migration
- [ ] T4 (REQ-2): Update `handleDocumentRender` to extract `conversation_id` from payload detail and append to `conversations[idx].documents` — `components/chat-view.tsx:522-533` — RIPPLE: `documentMerge.ts` (caller signature change)
- [ ] T5 (REQ-2): Update conversation switch to render only active conversation's documents — `components/chat-view.tsx:2630` (currently maps over `renderedDocuments`) — RIPPLE: use `conversations.find(c => c.id === activeConversationId)?.documents ?? []` 
- [ ] T6 (REQ-1): Persist documents per conversation in localStorage — `components/chat-view.tsx` (localStorage save in useEffect) — RIPPLE: localStorage size (documents can be large)
- [ ] T7 (REQ-2): Update `lib/documentMerge.ts` — `mergeRenderedDocuments` must accept `activeConversationId` and merge into correct conversation's documents instead of flat array — RIPPLE: chat-view.tsx:608 (caller), any other callers of mergeRenderedDocuments
- [ ] T8 (REQ-1): Update duplicate detection at `chat-view.tsx:1094` — check `renderedDocumentsRef` per-conversation, not globally — RIPPLE: none
- [ ] T9 (REQ-1): Update expanded doc lookup at `chat-view.tsx:2888` — search within active conversation's documents, not flat `renderedDocuments` — RIPPLE: none

## Wave 2 — Backend Crawl Stealth (Headless Browser)
- [ ] T10 (REQ-3): Create `STEALTH_USER_AGENTS` pool and `_get_random_ua()` helper — `backend/crawler/crawler_engine.py` — RIPPLE: none
- [ ] T11 (REQ-3): Replace basic BrowserConfig with headless Chromium config (real user-agent, viewport, Accept-Language, Sec-Fetch-* headers) — `backend/crawler/crawler_engine.py:138-141` — RIPPLE: crawl_runner.py (subprocess)
- [ ] T12 (REQ-3): Add user-agent rotation across crawl4ai requests — `backend/crawler/crawler_engine.py` (inside `_fetch_single`) — RIPPLE: none
- [ ] T13 (REQ-3): Add retry-on-403 with different user-agent before recording failure — `backend/crawler/crawler_engine.py` — RIPPLE: HAR entries (new retry metadata)
- [ ] T14 (REQ-7): Add structured logging for stealth mode: job_id, user-agent, status, retry count — `backend/crawler/crawler_engine.py` — RIPPLE: event_log.py

## Wave 3 — Backend Crawl Retry with Exa
- [ ] T15 (REQ-4): Add `_rewrite_query_for_retry(query)` method to CrawlOrchestrator that broadens the query — `backend/crawler/orchestrator.py` — RIPPLE: none
- [ ] T16 (REQ-4): Add retry flow in `research()`: after all pages fail, call search provider with rewritten query for new URLs — `backend/crawler/orchestrator.py:184-187` — RIPPLE: crawl_planner.py (URL generation)
- [ ] T17 (REQ-4): Send user-visible status message ("Narrowing search... retrying") during retry — `backend/crawler/orchestrator.py` — RIPPLE: WebSocket event pipeline (task:progress with user-visible message)
- [ ] T18 (REQ-4): Deduplicate URLs between initial and retry batches — `backend/crawler/orchestrator.py` — RIPPLE: none
- [ ] T19 (REQ-4): Enforce retry cap (max 2 total attempts) — `backend/crawler/orchestrator.py` — RIPPLE: none
- [ ] T20 (REQ-7): Log retry attempts with original query, rewritten query, URL counts — `backend/crawler/orchestrator.py` — RIPPLE: event_log.py

## Wave 4 — TaskListCard Fix
- [ ] T21 (REQ-6): Add debug logging in `useTaskProgress.ts` to verify `iris:task_update` events arrive during websearch — RIPPLE: none (observability only)
- [ ] T22 (REQ-6): Run live test — send websearch prompt, check browser console logs for `iris:task_update` events — RIPPLE: determines next task
- [ ] T23 (REQ-6): Create dedicated websearch TaskListCard component with searching icon/effect (globe or magnifying glass animation) — `components/websearch-card.tsx` — RIPPLE: chat-view.tsx (import + conditional render)
- [ ] T24 (REQ-6): Replace generic "thinking..." with websearch card when crawl is active. Keep "thinking..." for normal LLM responses — `components/chat-view.tsx:2697` — RIPPLE: task:start event detection (is_crawl flag)
- [ ] T25 (REQ-6): If `task:start` events arrive but TaskListCard doesn't show: fix conditional rendering in `chat-view.tsx:2697` — RIPPLE: taskProgress state management
- [ ] T26 (REQ-6): If `task:start` events don't arrive: investigate EventBus → WSEventBridge pipeline (backend/agent/ws_event_bridge.py) — RIPPLE: backend event pipeline

## Wave 5 — Conversational Crawl Narration
- [ ] T33 (REQ-8): Add `title` and `snippet` (first 120-180 meaningful chars from markdown) to `CRAWLER_PAGE_FETCHED` payload — `backend/crawler/orchestrator.py:275-281` — RIPPLE: tool_bridge.py (consumer of the event)
- [ ] T34 (REQ-8): Increase `_NARRATION_COOLDOWN_S` from 8s to 25s — `backend/agent/tool_bridge.py:1736` — RIPPLE: none
- [ ] T35 (REQ-8): Rewrite page-fetched narration to be conversational using title+snippet (e.g. "I just read an article on {title} that mentions {snippet}...") — `backend/agent/tool_bridge.py:1748-1749` — RIPPLE: none
- [ ] T36 (REQ-8): Replace "Still researching the web." heartbeat with meaningful progress (e.g. "I found some information about {topic}. Let me check a few more sources.") — `backend/agent/narration.py:89-96` — RIPPLE: none
- [ ] T37 (REQ-8): Add per-domain rotation to avoid repeating the same host in back-to-back narrations — `backend/agent/tool_bridge.py:1759-1768` — RIPPLE: none
- [ ] T38 (REQ-8): If page has no title or no meaningful snippet, skip narration entirely for that page — `backend/agent/tool_bridge.py:1745` — RIPPLE: none

## Wave 7 — Follow-Up Questions During Active Crawl (Parallel Execution)
- [ ] T39 (REQ-9): Add per-conversation `asyncio.Lock` to `agent_kernel.py` to prevent race conditions when concurrent messages arrive — `backend/agent/agent_kernel.py` — RIPPLE: all kernel callers
- [ ] T40 (REQ-9): Modify chat endpoint to detect websearch/crawl intent and spawn crawl as `asyncio.create_task()` instead of blocking on full DER loop — `backend/api/chat.py` — RIPPLE: agent_kernel.py, iris_gateway.py (WS push)
- [ ] T41 (REQ-9): When background crawl completes, push results via WebSocket `document:render` events — `backend/iris_gateway.py` — RIPPLE: ws_event_bridge.py
- [ ] T42 (REQ-9): Add per-conversation crawl-in-progress flag to agent_kernel to reject duplicate crawl requests while one is running — `backend/agent/agent_kernel.py` — RIPPLE: api/chat.py
- [ ] T43 (REQ-9): Handle chitchat messages during crawl: return response immediately while crawl runs in background — `backend/api/chat.py` — RIPPLE: agent_kernel.py, conversation_store.py

## Wave 8 — Verification
- [ ] T44 (REQ-1, REQ-2): Manual test — create docs in Thread A, switch to Thread B, verify no contamination — `frontend` — RIPPLE: none
- [ ] T45 (REQ-3): Manual test — crawl nasa.gov, verify stealth headers in HAR, verify no 403 — `backend` — RIPPLE: none
- [ ] T46 (REQ-4): Manual test — websearch with narrow query, verify retry fires with broader query — `full stack` — RIPPLE: none
- [ ] T47 (REQ-6): Manual test — send websearch, verify websearch TaskListCard appears with searching icon (not "thinking...") — `frontend` — RIPPLE: none
- [ ] T48 (REQ-8): Manual test — send websearch, verify narration speaks 1-3 times (not 6-8), with conversational snippets — `full stack` — RIPPLE: none
- [ ] T49 (REQ-9): Manual test — send websearch, while crawl runs send chitchat, verify chitchat answered without blocking crawl — `full stack` — RIPPLE: none
- [ ] T50 (REQ-1 through REQ-9): Run existing test suite to verify no regressions — `tests/` — RIPPLE: none

## Dependency / parallelization notes
- Wave 1 (frontend document isolation) and Wave 2 (backend stealth) are independent — can run in parallel.
- Wave 3 (Exa retry) depends on Wave 2 (stealth must be in place before retry makes sense).
- Wave 4 (TaskListCard) is independent — can run in parallel with Waves 1-3. Depends only on investigation results.
- Wave 5 (narration) depends on Wave 2 + Wave 3 (needs stealth + retry working first, and title+snippet from page fetch events).
- Wave 7 (parallel execution) is independent — can run in parallel with Waves 1-6. Changes are in api/chat.py + agent_kernel.py only.
- Wave 8 (verification) depends on all prior waves.
- T1-T3 (interface + migration) must land before T4-T9 (behavior changes).
- T10-T12 (stealth config) must land before T13 (retry-on-403).
- T15-T16 (retry flow) must land before T17-T20 (status message + dedup + cap + logging).
- T39 (lock) must land before T40-T43 (background crawl + chitchat handling).

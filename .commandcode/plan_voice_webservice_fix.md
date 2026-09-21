# Plan: Fix voice→agent feedback loop + web-search UI/UX gap

## Diagnosis (verified by code trace)

### A. Voice → agent path: "dead air, no processing visual"
1. **OrbBadge hidden during chat** — `XurOrb.tsx` only shows `OrbBadge` when
   `uiState === UI_STATE_IDLE` (orb-only). During a voice turn the chat/dashboard
   wing is open, so the background-working badge never appears. The orb itself
   only does a passive breath (0.3) via `useCadenceDetection`, with no explicit
   "agent is thinking / executing tools" state driven by real events.
2. **No wiring to task/agent events** — backend emits `task:start`/`task:progress`/
   `task:done` (forwarded as `iris:task_update`) and `agent_status`, but `XurOrb`
   never consumes them. Result: user sees nothing change between transcript bubble
   and final TTS.
3. **The file pasted (`components/Xur.tsx`) is NOT the mounted orb.** The real orb
   is `components/iris/XurOrb.tsx`. So "Xur not visible" = wrong file; the orb IS
   there but gives no task feedback.
4. **Audio feedback (STTPROC loop)** is gated by `_sttproc_stop` and killed if the
   LLM returns before playback starts; with the TTS half-duplex gate this produces
   silence ("dead air"). The activation beep + processing loop need to guarantee
   at least one iteration plays while `processing_conversation` is active.

### B. Web search: "exact query typed into browser, no results"
1. **Crawler events unlistened** — `dashboard-wing.tsx` does NOT subscribe to
   `iris:crawler_started`, `iris:crawler_page_fetched`, `iris:crawler_error`.
   Only `dark-glass-dashboard.tsx` listens for `iris:open_tab`. So there is no
   progress UI and no per-page feedback during crawl.
2. **Fallback plan returns raw search URL** — `crawl_planner._fallback_plan` returns
   `https://duckduckgo.com/html/?q=<query>`. If the LLM plan fails (or returns no
   URLs), the browser tab navigates to a DuckDuckGo results page of the literal
   query → "the agent just typed my exact response into the browser." No parsed
   results are shown because `dashboard_data` extraction either failed or the tab
   type wasn't `dashboard`.
3. **No synthesized search query** — there is no step that turns the user's spoken
   query into an actual web search (e.g. a real search-engine URL or a crawl of
   result pages). The planner asks the LLM for URLs but has no guaranteed-search
   fallback that yields parseable result content.

## Implementation Plan

### 1. Orb task/agent feedback (frontend)
- In `XurOrb.tsx`, consume `useAgentQuestion` + `useTaskProgress` (already imported)
  and ADD a visible "thinking / working" indicator that shows whenever
  `taskProgress.isWorking` OR `voiceState === "processing_conversation"` OR
  `processing_tool`, **regardless of wing open state**. Replace the idle-only
  `showOrbBadge` gate so it also appears as an orb ring/label during processing.
- Add a distinct visual (e.g. pulsing arc or "PROCESSING" glitch label) bound to
  `processing_conversation` so the user clearly sees the agent is working, not dead.

### 2. Crawler progress UI (frontend)
- In `dashboard-wing.tsx`, subscribe to `iris:crawler_started` /
  `iris:crawler_page_fetched` / `iris:crawler_error` and render a live progress
  panel (query, N/total pages fetched, errors) in the dashboard wing while a crawl
  runs. This gives real-time "agent is searching" feedback instead of a silent tab.

### 3. Web-search actual results (backend)
- In `crawl_planner.py`: when the LLM returns no usable URLs, synthesize a real
  search by crawling a search-engine results page (or use a proper search source)
  so `dashboard_data` contains parsed results, not a raw query URL.
- In `iris_gateway._handle_crawler_query`: ensure `open_tab` is sent with
  `tab_type: "dashboard"` + populated `data` (the extracted `DashboardData`) so
  `dark-glass-dashboard` renders `DashboardRenderer` with real results — never an
  iframe of the raw query.
- Verify `data_extractor.extract` actually returns content; if it returns empty,
  fall back to rendering raw page markdown in the dashboard tab.

### 4. Audio feedback guarantee (backend)
- In `_process_voice_transcription`: ensure the STTPROC processing loop plays at
  least one full iteration while `processing_conversation` is active, and only stop
  it after `tts_started` fires (not on first LLM token). Keep the `finally` gate
  release from the earlier fix.

## Verification
- Voice a question (web toggle OFF): orb shows listening → processing (visible
  indicator) → speaking; transcript processed; TTS plays with audio.
- Toggle web ON, voice a search: dashboard wing shows crawler progress; browser
  tab shows parsed results (DashboardRenderer), not a raw query URL.
- Check backend log for crawler extraction success and no `content_filter`/playwright
  errors.

# Requirements: Exa Search Provider Integration

## Introduction

Integrate Exa's neural search API as a configurable search backend for IRIS
Voice. Exa provides semantic/embedding-based web search that finds URLs and
content by *meaning* rather than keywords, with built-in content extraction
(highlights + full text). It replaces the current LLM-generated-URL approach
as an *option* — the user chooses which provider to use via config + settings
UI, and the key is stored securely out of git.

### Success criteria
- User can input an Exa API key in the frontend settings and select Exa as the
  search provider — subsequent `search` and `crawler_query` calls use Exa.
- The `search` tool (quick lookup) returns Exa results at ~1s latency with
  extracted content and source URLs — no Crawl4AI invocation.
- The `crawler_query` tool (deep crawl) uses Exa for URL discovery, then
  feeds those URLs into the existing Crawl4AI subprocess pipeline for
  comprehensive extraction + scoring + citation.
- Provider can be toggled back to "LLM" (current behavior) without restarting
  the backend — config change takes effect on the next crawl.
- All 28 existing crawl tests still pass; new contract + integration tests
  cover the Exa provider in isolation.

---

## Requirements

### REQ-1: SearchProvider abstraction
**User Story:** As a developer I want a common interface for all search backends
so that adding a new provider (Exa, Brave, Tavily) is a single new class with
no changes to the orchestrator or tools.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define an abstract `SearchProvider` class at
  `backend/crawler/search_providers/base.py` with a `search(query, max_results)`
  async method returning a `SearchResult` dataclass.
- AC2: THE SYSTEM SHALL define a `SearchResult` dataclass with fields `query`,
  `results: list[SearchResultItem]`, `provider: str`.
- AC3: THE SYSTEM SHALL define a `SearchResultItem` dataclass with fields
  `url`, `title`, `snippet`, `content`, `score`, `published_date`.
- AC4: WHEN a new provider class inherits from `SearchProvider` THEN it SHALL
  be usable by the orchestrator and tools with zero glue-code changes.

**Edge Cases:**
- Empty query → return empty results list (not error).
- Provider raises `SearchProviderError` → caller catches and falls back.

---

### REQ-2: ExaSearchProvider implementation
**User Story:** As a user with an Exa API key I want the assistant to search
the web using Exa's neural embedding index so that results are semantically
relevant and include extracted content.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL implement `ExaSearchProvider(base_url="https://api.exa.ai")`
  at `backend/crawler/search_providers/exa.py`.
- AC2: WHEN `search(query, max_results=10)` is called THEN THE SYSTEM SHALL
  POST to `{base_url}/search` with the query, `numResults`, `type: "auto"`,
  and `contents: {text: true, highlights: true}`.
- AC3: THE SYSTEM SHALL map each Exa result item to `SearchResultItem` with
  url, title, snippet (highlights joined or text truncated), content (full text
  or highlights), score, and publishedDate.
- AC4: IF Exa returns `results: []` THEN THE SYSTEM SHALL return a
  `SearchResult` with empty items list (not error).
- AC5: THE SYSTEM SHALL read the Exa API key from the `EXA_API_KEY` environment
  variable (not from a git-tracked file).

**Edge Cases:**
- `EXA_API_KEY` not set / empty → `ExaSearchProvider.__init__` raises
  `ValueError("EXA_API_KEY not set")`.
- Exa API returns HTTP 401 → `SearchProviderError("invalid API key")`.
- Exa API returns HTTP 429 → `SearchProviderError("rate limited")` with a
  `retry_after_seconds` field.
- Exa API times out (30s) → `SearchProviderError("upstream timeout")`.
- Exa returns partial results (some items have no content) → items with no
  content are included (url + title at minimum).

---

### REQ-3: Configurable search provider selection
**User Story:** As a user I want to choose which search backend the assistant
uses so I can switch between LLM-generated URLs (free) and Exa (higher quality
results) depending on my needs.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL read the active search provider from
  `iris_config.json` key `search.provider` (values: `"llm"` | `"exa"`).
- AC2: WHEN `search.provider` is `"llm"` THEN THE SYSTEM SHALL use the existing
  `LLMSearchProvider` (Cerebras generates URLs, no search engine).
- AC3: WHEN `search.provider` is `"exa"` THEN THE SYSTEM SHALL use
  `ExaSearchProvider`.
- AC4: THE SYSTEM SHALL default to `"llm"` when `search.provider` is unset or
  unknown.
- AC5: WHEN the config is changed at runtime (not restart) THEN the next
  `search` or `crawl` call SHALL use the new provider — no restart required.

**Edge Cases:**
- Config file missing → default to `"llm"` (safe fallback).
- Config has `search.provider: "brave"` (not yet implemented) → default to
  `"llm"` and log a warning.

---

### REQ-4: `search` tool uses Exa directly (no Crawl4AI)
**User Story:** As a user asking a quick factual question I want the `search`
tool to return results in ~1 second using Exa's built-in content extraction so
I get a fast answer without waiting for Crawl4AI to crawl pages.

**Acceptance Criteria:**
- AC1: WHEN `search.provider` is `"exa"` THEN `_execute_web_search` SHALL call
  `ExaSearchProvider.search(query)` and return the results directly (no
  `CrawlOrchestrator`, no Crawl4AI subprocess).
- AC2: THE SYSTEM SHALL build the result dict `content` from the top-5 results'
  highlights/snippets, formatted as a text block with source URLs.
- AC3: THE SYSTEM SHALL include a `sources` list with all result URLs.
- AC4: THE SYSTEM SHALL tag the result with `trust: "untrusted"` (routed to
  reference zone, same as current behavior).
- AC5: WHEN `search.provider` is `"llm"` THEN `_execute_web_search` SHALL
  continue using `CrawlOrchestrator.research()` (current behavior unchanged).

**Edge Cases:**
- Exa returns 0 results → `search` returns `success: True` with empty content
  and an explanatory message.
- Exa rate-limited → `search` falls back to `CrawlOrchestrator.research()`
  (LLM-URL path) so the user still gets an answer.

---

### REQ-5: `crawler_query` tool uses Exa for URL discovery + Crawl4AI for extraction
**User Story:** As a user asking for deep research I want the `crawler_query`
tool to discover URLs via Exa's neural search and then extract full content
from those pages via Crawl4AI so I get comprehensive, crawled results.

**Acceptance Criteria:**
- AC1: WHEN `search.provider` is `"exa"` THEN `CrawlPlanner.plan()` SHALL call
  `ExaSearchProvider.search(query)` and build a `CrawlPlan` from the returned
  URLs (replacing the LLM-generated-URL path).
- AC2: `CrawlPlan.urls` SHALL be the URLs from the first `max_pages` Exa
  results (capped at `CRAWL4AI_MAX_PAGES`).
- AC3: `CrawlPlan.title` SHALL be derived from `query` (or from Exa results
  title).
- AC4: THE SYSTEM SHALL then feed the `CrawlPlan` into the existing
  `CrawlOrchestrator` funnel (plan → fetch → extract → cite → score →
  dashboard) unchanged.
- AC5: Fetch SHALL use `SubprocessFetchBackend` (Crawl4AI subprocess with
  `_kill_tree`) — same crash isolation as today.

**Edge Cases:**
- Exa returns 0 URLs → `plan()` returns a `CrawlPlan` with empty `urls` →
  orchestrator emits `CRAWLER_ERROR "no candidate urls"`.
- Exa URL discovery succeeds but some URLs fail on Crawl4AI crawl → per-page
  `PageData.error` (existing behavior, no full failure).

---

### REQ-6: LLMSearchProvider (refactor existing behavior)
**User Story:** As a user without an Exa key I want the LLM-generated-URL
search path to remain fully functional so existing behavior is preserved.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL move the existing `CrawlPlanner._call_llm` and
  `_parse` and `_fallback_plan` logic into an `LLMSearchProvider` class at
  `backend/crawler/search_providers/llm.py` implementing `SearchProvider`.
- AC2: `LLMSearchProvider.search(query, max_results)` SHALL call the LLM
  (Cerebras) with the existing prompt and return a `SearchResult` with
  `results` items built from the LLM-generated URLs.
- AC3: WHEN the LLM produces no URLs THEN `LLMSearchProvider` SHALL return an
  empty `SearchResult` (no DuckDuckGo fallback — matches current behavior).
- AC4: `CrawlPlanner.plan()` SHALL delegate to the active `SearchProvider`
  (either `ExaSearchProvider` or `LLMSearchProvider`) via a uniform call.

**Edge Cases:**
- LLM call times out → return empty `SearchResult` (log warning).

---

### REQ-7: Secure credential storage
**User Story:** As a security-conscious user I want my Exa API key stored
outside of git-tracked files so it isn't accidentally committed.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL read `EXA_API_KEY` from environment variables
  (`.env` file or actual env var) — NOT from `iris_config.json`.
- AC2: THE SYSTEM SHALL provide a frontend settings input for the user to
  enter the Exa API key, which SHALL save it to `.env` (append or update
  `EXA_API_KEY=...` line) or to the OS keyring via `credential_store`.
- AC3: WHERE the key is stored in `.env` THE SYSTEM SHALL ensure `.env` is
  gitignored (verify existing `.gitignore` covers `.env`).

**Edge Cases:**
- `.env` file missing → backend falls back to `LLMSearchProvider`.
- Key saved to `.env` but backend needs restart → next `search` call
  re-reads env (or read on each search from the `.env` file).

---

### REQ-8: Frontend settings UI
**User Story:** As a user I want to configure the search provider and enter my
Exa API key from the IRIS Voice settings panel so I don't have to edit files
manually.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL add a "Search" section to the settings/wheel-view
  sidebar with a provider dropdown (`"LLM"` | `"Exa"`).
- AC2: WHEN "Exa" is selected THEN THE SYSTEM SHALL show an API key text
  input field (password-masked) and a "Save" button.
- AC3: WHEN the user clicks "Save" THEN THE SYSTEM SHALL send the API key
  to the backend via a WebSocket message or REST endpoint, and the backend
  SHALL save it to `.env` (or credential store).
- AC4: WHEN the user toggles the provider dropdown THEN THE SYSTEM SHALL
  send the new provider value to the backend, which SHALL update
  `iris_config.json`.
- AC5: WHEN the provider is "LLM" THEN THE SYSTEM SHALL hide the API key
  input field (not applicable).

**Edge Cases:**
- Empty API key submitted → show validation error ("API key cannot be empty").
- Backend returns error saving key → show error toast to user.
- User closes settings before saving → unsaved changes are discarded (no
  auto-save).

---

### REQ-9: Error handling and fallback chain
**User Story:** As a user I want searches to still work even when the Exa API
is unreachable so I never get a silent failure.

**Acceptance Criteria:**
- AC1: IF `ExaSearchProvider.search()` raises any exception THEN the caller
  (`CrawlPlanner.plan` or `_execute_web_search`) SHALL fall back to
  `LLMSearchProvider` (the LLM-generated-URL path).
- AC2: THE SYSTEM SHALL log the Exa failure at `WARNING` level before
  falling back, including the error details.
- AC3: THE SYSTEM SHALL NOT attempt to re-query Exa on the same request after
  a fallback (no retry loop — fail once, fall back immediately).
- AC4: IF `LLMSearchProvider` also fails THEN the existing empty-plan /
  CRAWLER_ERROR behavior applies (no dangling request).

**Edge Cases:**
- Exa returns `results: []` → this is NOT an error; `search` returns empty
  results (user sees "no results found"), `plan` returns empty plan.
- Fallback to LLM when Exa is down → the step is slower (LLM + Crawl4AI) but
  completes.

---

### REQ-10: Exa provider contract + integration tests
**User Story:** As a developer I want automated tests for the Exa provider so
that regressions are caught before deployment.

**Acceptance Criteria:**
- AC1: A contract test SHALL verify `ExaSearchProvider` sends the correct HTTP
  payload shape to the Exa API (test with a mock HTTP server).
- AC2: A contract test SHALL verify the response mapping from Exa JSON ->
  `SearchResultItem` (all fields populated correctly, empty fields handled).
- AC3: A contract test SHALL verify error mapping (401 → invalid key,
  429 → rate limited, timeout → upstream timeout).
- AC4: An integration test SHALL verify the fallback chain (Exa fails →
  LLMSearchProvider used).
- AC5: An integration test SHALL verify `CrawlPlanner.plan()` uses the
  configured provider and returns a valid `CrawlPlan`.

**Edge Cases:**
- No `EXA_API_KEY` env var → `ExaSearchProvider.__init__` raises `ValueError`.
- Exa returns non-JSON response → `SearchProviderError("unexpected response")`.

---

## Non-Requirements (Out of Scope)
- Brave/Tavily/Linkup provider implementations (future work; the
  `SearchProvider` abstraction is ready for them).
- Caching of Exa results (Exa has its own caching / `maxAgeHours`).
- Changing the frontend's crawl-event rendering (existing `crawler_started` /
  `page_fetched` / `open_tab` / `crawler_complete` events are provider-agnostic).
- Exa's Deep Search / Deep Reasoning / structured-output modes (future; start
  with `auto` search type).
- Exa's `find_similar` endpoint (future; useful for research agents).

---

## Open Questions
- Should the API key be stored in `.env` or OS keyring? My recommendation:
  `.env` for simplicity (matches `PICOVOICE_ACCESS_KEY` pattern); can
  upgrade to keyring later. **Decision deferred to design phase.**

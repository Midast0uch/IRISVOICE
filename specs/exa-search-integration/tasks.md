# Tasks: Exa Search Provider Integration

> Each task links to a requirement. Grouped into 4 waves for sequential execution.
> All new files go under `backend/crawler/search_providers/`.

---

## Wave 1 — Foundation: SearchProvider abstraction + data models

- [ ] T1 (REQ-1): Create `backend/crawler/search_providers/` package with
  `__init__.py` — `backend/crawler/search_providers/base.py`
  - `SearchProvider` ABC with `search(query, max_results)` abstract method
  - `SearchResultItem` dataclass: url, title, snippet, content, score,
    published_date, metadata
  - `SearchResult` dataclass: query, results list, provider, total
  - `SearchProviderError` exception with `retry_after_seconds` field
  - Verify: `SearchResultItem`, `SearchResult`, `SearchProviderError` import
    and construct cleanly.

- [ ] T2 (REQ-2): Implement `ExaSearchProvider` at
  `backend/crawler/search_providers/exa.py`
  - Constructor: reads `EXA_API_KEY` from `os.environ`; raises `ValueError`
    if missing.
  - `search(query, max_results)` → POST to `https://api.exa.ai/search` with
    `{query, numResults, type: "auto", contents: {text, highlights}}`.
  - Map response JSON fields to `SearchResultItem` (highlights → snippet,
    text → content, score → score, url → url, title → title).
  - Map Exa errors: 401 → `SearchProviderError("invalid API key")`,
    429 → `SearchProviderError("rate limited", retry_after=N)`,
    5xx/timeout → `SearchProviderError("upstream timeout")`.
  - Handle empty results (return `SearchResult` with empty items list).
  - Handle non-JSON response (raise `SearchProviderError("unexpected response")`).

- [ ] T3 (REQ-6): Refactor existing `CrawlPlanner._call_llm` + `_parse` +
  `_fallback_plan` into `LLMSearchProvider` at
  `backend/crawler/search_providers/llm.py`
  - `LLMSearchProvider` implements `SearchProvider`.
  - `search(query, max_results)` → calls LLM with existing prompt, parses
    JSON, returns `SearchResult` with items built from parsed URLs.
  - Move the prompt (`_PLAN_PROMPT`) and `_parse` logic into the class.
  - `_fallback_plan` returns empty `SearchResult` (no DuckDuckGo — matches
    current behavior).
  - Verify: `CrawlPlanner` still imports and uses `LLMSearchProvider`
    identically.

- [ ] T4 (REQ-1, REQ-3): Add `get_search_provider()` factory in
  `backend/crawler/search_providers/__init__.py`
  - Reads `iris_config.json` → `search.provider` (default `"llm"`).
  - Returns `LLMSearchProvider` for `"llm"`, `ExaSearchProvider` for `"exa"`.
  - Unrecognized provider → log warning, return `LLMSearchProvider`.
  - `ExaSearchProvider.__init__` raises `ValueError` → log warning, return
    `LLMSearchProvider`.
  - **Caches the provider instance** (no restart needed to change config —
    config changes on next call).

---

## Wave 2 — Integration into crawl pipeline

- [ ] T5 (REQ-3, REQ-5): Modify `CrawlPlanner.plan()` to use the active
  `SearchProvider`
  - `CrawlPlanner.__init__` takes an optional `provider: SearchProvider`
    parameter (default `None` → uses `get_search_provider()`).
  - `plan(query)` → `provider.search(query, max_results=CRAWL_MAX_PAGES)` →
    build `CrawlPlan` from returned URLs.
  - `CrawlPlan.urls` = first N URLs from search results (N ≤ `CRAWL_MAX_PAGES`).
  - `CrawlPlan.title` = query (truncated).
  - `CrawlPlan.result_type` = `"mixed"`.
  - If `SearchResult.results` is empty → return `CrawlPlan(urls=[])` (existing
    empty-plan behavior).
  - Test: `CrawlPlanner` with `ExaSearchProvider` mock returns `CrawlPlan`
    with correct URLs.

- [ ] T6 (REQ-4): Modify `_execute_web_search` in `tool_bridge.py` to use
  `SearchProvider` directly when Exa is active
  - Read `search.provider` config at call time.
  - WHEN `"exa"`: skip `CrawlOrchestrator`, call
    `ExaSearchProvider.search(query, max_results=5)`.
    Build result dict from highlights + URLs (top 5 items).
  - WHEN `"llm"`: keep existing `CrawlOrchestrator.research()` path.
  - IF Exa raises `SearchProviderError`: log warning, fall back to
    `CrawlOrchestrator.research()` path.
  - Return shape unchanged: `{success, query, content, url, sources, trust}`.

- [ ] T7 (REQ-4, REQ-5): Verify `CrawlOrchestrator.research()` handles
  `CrawlPlan` from Exa-provider URLs
  - No structural change needed — `CrawlPlan.urls` is already the plane input.
  - Ensure `SubprocessFetchBackend` receives the Exa-generated URLs correctly.
  - Smoke test: call orchestrator with a plan from Exa mock → verify
    `run_crawl_subprocess` is called with the right URLs.

- [ ] T8 (REQ-7): Add `EXA_API_KEY` to `.env.example` (if exists) and ensure
  `.env` is gitignored.
  - Verify `.gitignore` already includes `.env` (or add it).
  - Create `.env.example` with `EXA_API_KEY=` commented placeholder.

---

## Wave 3 — Frontend settings UI

- [ ] T9 (REQ-8): Add "Search" section to the settings/wheel-view sidebar
  - New subsection with:
    - Provider dropdown: `<select>` with `"LLM"` and `"Exa"` options.
    - API key input: `<input type="password">` (shown only when Exa selected).
    - "Save API Key" button.
  - Use existing settings UI pattern (look at wake-word card or audio
    settings for reference).

- [ ] T10 (REQ-7, REQ-8): Wire the "Save" button to the backend
  - Frontend sends `save_search_config` WS message (or `POST` to existing
    settings endpoint) with `{provider, exa_api_key}`.
  - Backend handler:
    - Update `iris_config.json` `search.provider`.
    - Write `EXA_API_KEY=...` to `.env` file (append if key exists, add if not).
    - Clear the cached `SearchProvider` instance so next call picks up the
      new provider.
  - Return `{success: true/false}`.
  - Show success toast or error toast on the frontend.

- [ ] T11 (REQ-8): Wire the provider dropdown change to the backend
  - On dropdown change (no save button needed for provider-only), frontend
    sends `set_search_provider` WS message with `{provider}`.
  - Backend updates `iris_config.json` `search.provider` and clears the
    cached provider instance.
  - Return `{success: true}` — no need for the user to click "Save" just
    for toggling the provider.
  - IF Exa selected but no key saved yet → show inline hint:
    "Enter your Exa API key below and click Save."

---

## Wave 4 — Verification

- [ ] T12 (REQ-10): Contract tests for `ExaSearchProvider`
  - File: `backend/tests/contract/test_exa_provider.py`
  - `test_exa_search_sends_correct_payload` — mock HTTP POST, verify JSON
    body has query, numResults, type, contents keys.
  - `test_exa_maps_response_fields` — mock returns full JSON, verify
    `SearchResultItem` has all fields populated.
  - `test_exa_handles_empty_results` — mock returns `{results: []}`, verify
    empty `SearchResult.results`.
  - `test_exa_error_401` — mock returns 401, verify
    `SearchProviderError("invalid API key")`.
  - `test_exa_error_429` — mock returns 429 with `Retry-After`, verify
    error message + `retry_after_seconds`.
  - `test_exa_error_timeout` — mock raises `httpx.ReadTimeout`, verify
    `SearchProviderError("upstream timeout")`.
  - `test_exa_error_non_json` — mock returns `text/plain` body, verify
    `SearchProviderError("unexpected response")`.
  - `test_exa_missing_key` — clear `EXA_API_KEY`, verify `ValueError`.

- [ ] T13 (REQ-10): Contract tests for `LLMSearchProvider`
  - File: `backend/tests/contract/test_llm_provider.py`
  - `test_llm_search_returns_urls` — mock LLM returns valid JSON, verify
    `SearchResult` has items with correct URLs.
  - `test_llm_search_empty_on_no_json` — mock LLM returns plain text, verify
    empty `SearchResult`.
  - `test_llm_search_empty_on_no_urls` — mock LLM returns `{urls: []}`,
    verify empty `SearchResult`.

- [ ] T14 (REQ-9, REQ-10): Integration tests for fallback + provider switching
  - File: `backend/tests/integration/test_search_providers.py`
  - `test_fallback_exa_to_llm` — mock Exa raises, verify `LLMSearchProvider`
    is called as fallback.
  - `test_fallback_both_empty` — both Exa and LLM return empty, verify
    `CrawlPlan` has no URLs.
  - `test_provider_switching` — set config to `"exa"`, verify
    `get_search_provider()` returns `ExaSearchProvider`; switch to `"llm"`,
    verify returns `LLMSearchProvider`.
  - `test_unknown_provider_falls_back` — set config to `"brave"`, verify
    returns `LLMSearchProvider` with warning.

- [ ] T15: Run full existing crawl test suite and verify 28 tests still pass
  - `tests/contract/test_crawl_orchestrator_contract.py` (8)
  - `tests/contract/test_crawl_transport_contract.py` (10)
  - `tests/integration/test_crawl_integration.py` (6)
  - `tests/behavioral/test_crawl_behavior.py` (4)
  - All must PASS with no regressions.

---

## Wave 5 — Documentation and polish

- [ ] T16: Update `docs/architecture/audio-pipeline.md` (if search provider
  affects audio/narration — it shouldn't, but verify).
- [ ] T17: Update `data/iris_config.json` with default `search.provider: "llm"`
  entry.
- [ ] T18: MCM event recording + `pin_add` for key decisions tested.

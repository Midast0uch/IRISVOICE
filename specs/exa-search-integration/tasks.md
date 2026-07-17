# Tasks: Exa Search + Smart Source Registry

> All tasks link to requirements. Grouped into 7 waves for sequential execution.
> New files go under `backend/crawler/search_providers/`.

---

## Wave 0 — Pre-work: Verify existing state

- [ ] T0: Run the full existing crawl test suite to confirm baseline:
  - `tests/contract/test_crawl_orchestrator_contract.py` (8)
  - `tests/contract/test_crawl_transport_contract.py` (10)
  - `tests/integration/test_crawl_integration.py` (6)
  - `tests/behavioral/test_crawl_behavior.py` (4)
  - **All 28 must PASS** before any changes.

---

## Wave 1 — Foundation: SearchProvider abstraction + data models

- [ ] T1 (REQ-1): Create `backend/crawler/search_providers/` package
  - `__init__.py` — package init, `get_search_provider()` factory
  - `base.py` — `SearchProvider` ABC, `SearchResultItem`, `SearchResult`, `SearchProviderError`
  - Verify: all dataclasses import and construct cleanly.

- [ ] T2 (REQ-2): Implement `ExaSearchProvider` at `backend/crawler/search_providers/exa.py`
  - Constructor reads `EXA_API_KEY` from `os.environ`; raises `ValueError` if missing.
  - `search(query, max_results)` → POST to `https://api.exa.ai/search`
  - Map response JSON to `SearchResultItem` (highlights → snippet, text → content)
  - Map errors: 401, 429, timeout, non-JSON, empty results.
  - Use `httpx.AsyncClient` with 30s timeout.

- [ ] T3 (REQ-6): Refactor existing `CrawlPlanner._call_llm` + `_parse` + `_fallback_plan`
  into `LLMSearchProvider` at `backend/crawler/search_providers/llm.py`
  - `search(query, max_results)` → calls LLM with existing prompt, parses JSON, returns `SearchResult`.
  - `_fallback_plan` returns empty `SearchResult` (no DuckDuckGo).
  - Verify: `CrawlPlanner` imports and uses `LLMSearchProvider` identically.

- [ ] T4 (REQ-3, REQ-6): Wire `get_search_provider()` factory in `__init__.py`
  - Reads `iris_config.json` → `search.provider` (default `"llm"`).
  - Returns `LLMSearchProvider` for `"llm"`, `ExaSearchProvider` for `"exa"`.
  - Unknown provider → log warning, return `LLMSearchProvider`.
  - `ExaSearchProvider.__init__` raises `ValueError` → log warning, return `LLMSearchProvider`.
  - Caches instance; clears on config change.

---

## Wave 2 — SourceRegistry: learned topic→URL knowledge base

- [ ] T5 (REQ-11): Implement `SourceRegistry` at `backend/crawler/source_registry.py`
  - `__init__`: takes `SemanticStore` reference, config threshold/TTL.
  - `_extract_topics(query)`: LLM call → return list of 3-5 topic strings.
  - `_lookup_topics(topics)`: query `SemanticStore.retrieve(category="source_registry",
    key="topic:<normalized>")` for each topic.
  - `_score_coverage(sources)`: weighted sum of credibility × freshness decay.
  - `resolve(query) → ResolveResult(hit, sources, coverage_score, topics)`:
    HIT if coverage ≥ threshold, MISS otherwise.
  - `learn(query, search_result, credibility_map)`:
    Extract topics, for each result item with credibility ≥ 0.3 → save to semantic store.
    Update existing entries (weighted running average credibility, increment crawl_count,
    update last_crawled). Penalize failed URLs (credibility × 0.5).
  - Freshness decay: entries older than `registry_ttl_days` have credibility halved.

- [ ] T6 (REQ-11, REQ-15): Integrate `SourceRegistry` with `SemanticStore`
  - Register new category `"source_registry"` in `SemanticStore.HEADER_CATEGORIES`.
  - Key format: `topic:<normalized_topic>` (lowercase, underscores for spaces).
  - Value format: JSON list of `RegisteredSource` dicts.
  - For credibility reads: query the episodic `reference` zone via
    `EpisodicStore` or `pacman_fragment` API for per-URL historical credibility.
  - Fallback: if reference zone has no data for a URL, use `crawl_count / total_crawls`
    as credibility proxy.

- [ ] T7 (REQ-14): Freshness and decay logic
  - `last_crawled` timestamp per entry.
  - On `resolve()`: if `age_days > TTL`, credibility × 0.5.
  - If `age_days > TTL × 2`, credibility × 0.1 (nearly discarded).
  - If ALL sources for a topic are past TTL and credibility penalized below threshold
    → return MISS (forces fresh search).
  - On `learn()`: update `last_crawled` for refreshed URLs.

---

## Wave 3 — Integration: CrawlPlanner + tools use registry

- [ ] T8 (REQ-12): Modify `CrawlPlanner.plan()` to use SourceRegistry
  - `CrawlPlanner.__init__` takes `registry: SourceRegistry` (default `None` → creates).
  - `plan(query)`:
    1. Call `registry.resolve(query)`.
    2. HIT → build `CrawlPlan` from cached URLs, return (skip SearchProvider).
    3. MISS → call `SearchProvider.search(query)` with seeds from
       `resolve_result.sources` if any → build `CrawlPlan` with all URLs.
    4. Return `CrawlPlan`.
  - After orchestration completes (post-plan): call `registry.learn()` with
    the search result + credibility_map.

- [ ] T9 (REQ-4, REQ-12): Modify `_execute_web_search` in `tool_bridge.py`
  - Read `search.provider` + use `SourceRegistry`.
  - HIT → build result dict from cached sources' snippets/content (no Exa, no Crawl4AI).
  - MISS:
    - If provider is `"exa"`: call `ExaSearchProvider.search()` directly,
      build result from highlights + URLs, learn.
      Fall back to `LLMSearchProvider` if Exa fails.
    - If provider is `"llm"`: use existing `CrawlOrchestrator.research()` path.
  - Return shape unchanged: `{success, query, content, url, sources, trust}`.

- [ ] T10 (REQ-5, REQ-12): Wire `_execute_crawler_query` to use SourceRegistry
  - `_execute_crawler_query` already calls `CrawlOrchestrator.research()`.
  - `CrawlOrchestrator` calls `CrawlPlanner.plan()`.
  - After `research()` returns, call `SourceRegistry.learn(query, search_result,
    credibility_map)` in `_execute_crawler_query` or in `research()` itself.
  - Recommended: add a `post_research` hook in `research()` that emits
    `(query, search_result, credibility_map)` for external consumers.

- [ ] T11 (REQ-7): Add `EXA_API_KEY` to `.env.example`; ensure `.env` gitignored.
  - Verify `.gitignore` has `.env`.

---

## Wave 4 — Backend memory integration

- [ ] T12 (REQ-15): Add `"source_registry"` category to `SemanticStore.HEADER_CATEGORIES`
  - In `backend/memory/semantic.py`, append `"source_registry"` to the list.
  - This ensures the category is included in startup context/dumps.

- [ ] T13 (REQ-15): Verify `pacman_fragment` feeds credibility into reference zone
  - No change needed — `pacman_fragment.execute()` already persists
    `credibility_map` + `citation_index` to reference zone.
  - Add a test: after `execute()`, SourceRegistry can read back credibility
    for a given domain via the reference zone.

---

## Wave 5 — Frontend settings UI

- [ ] T14 (REQ-8): Add "Search" section to settings/wheel-view sidebar
  - Provider dropdown: `<select>` with `"LLM"` and `"Exa"`.
  - API key input: `<input type="password">` (shown only when Exa selected).
  - "Save API Key" button.
  - Inline hint when Exa selected but no key saved.

- [ ] T15 (REQ-7, REQ-8): Wire Save button + provider dropdown to backend
  - Frontend sends `save_search_config` WS message `{provider, exa_api_key}`.
  - Backend: update `iris_config.json` `search.provider` + write
    `EXA_API_KEY=...` to `.env` + clear cached `SearchProvider` + `SourceRegistry`.
  - Return `{success}`, show toast.
  - Provider dropdown change (without Save) sends `set_search_provider` →
    backend updates config + clears cache.

---

## Wave 6 — Verification

- [ ] T16 (REQ-10): Contract tests for `ExaSearchProvider`
  - `test_exa_search_payload` — mock POST, verify JSON shape.
  - `test_exa_maps_response` — mock full response, verify `SearchResultItem`.
  - `test_exa_empty_results` — mock `{results: []}`.
  - `test_exa_error_401` → `SearchProviderError("invalid API key")`.
  - `test_exa_error_429` → `SearchProviderError("rate limited")` with retry_after.
  - `test_exa_error_timeout` → `SearchProviderError("upstream timeout")`.
  - `test_exa_error_non_json` → `SearchProviderError("unexpected response")`.
  - `test_exa_missing_key` → `ValueError`.

- [ ] T17 (REQ-10): Contract tests for `SourceRegistry`
  - `test_resolve_hit` — pre-populate semantic store, resolve → HIT.
  - `test_resolve_miss` — empty store → MISS.
  - `test_coverage_scoring` — known sources with specific credibilities → expected score.
  - `test_freshness_decay` — source aged past TTL → score halved.
  - `test_freshness_discard` — source aged past 2× TTL → score near zero.
  - `test_learn_adds_new` — learn called → store has new entry.
  - `test_learn_updates_existing` — learn called for existing URL → credibility averaged.
  - `test_learn_penalizes_failure` — failed crawl → credibility ×0.5.

- [ ] T18 (REQ-10): Integration tests for providers + registry
  - `test_provider_switching` — config `"exa"` → ExaSearchProvider; `"llm"` → LLMSearchProvider.
  - `test_unknown_provider_falls_back` → `"brave"` → LLMSearchProvider + warning.
  - `test_fallback_exa_to_llm` — Exa mock raises, verify LLM called.
  - `test_fallback_both_empty` — both Exa + LLM empty → CrawlPlan has no URLs.
  - `test_seed_urls_on_partial_hit` — registry MISS with partial sources → plan includes seeds.

- [ ] T19 (REQ-10): Integration tests for full pipeline with SourceRegistry
  - `test_crawl_planner_hit_no_search` — registry HIT → plan has URLs, SearchProvider NOT called.
  - `test_crawl_planner_miss_calls_search` — registry MISS → SearchProvider called.
  - `test_web_search_hit_returns_cached` — registry HIT → `execute_web_search` returns from cache.
  - `test_web_search_miss_calls_exa` — registry MISS → Exa called, result returned, learned.

- [ ] T20: Run full existing crawl test suite — confirm all 28 tests still PASS.

---

## Wave 7 — Documentation and polish

- [ ] T21: Update `data/iris_config.json` with default `search` section.
- [ ] T22: MCM event recording + `pin_add` for key architectural decisions.

# Requirements: Exa Search + Smart Source Registry

## Introduction

Integrate Exa's neural search API as a configurable search backend, paired with
a **learned SourceRegistry** that maps topics to known authoritative URLs. The
SourceRegistry grows smarter with every crawl: instead of firing Exa on every
request, the system first checks whether it already knows high-quality URLs for
the topic. Only when the registry has insufficient coverage does it call Exa or
the LLM. The registry lives in **semantic memory** (cross-session), and URL
credibility feeds from the **reference zone** (episodic memory) — connecting
directly to the existing agent memory framework.

### Success criteria
- User can input an Exa API key in settings and select Exa as provider.
- The first query on a new topic fires Exa, returns URLs, Crawl4AI extracts them.
- The second query on a related topic uses **cached URLs from the SourceRegistry**
  — zero Exa calls for known topics.
- SourceRegistry entries are stored in semantic memory (`category="source_registry"`)
  and persist across sessions.
- All 28 existing crawl tests still pass; new tests cover registry + decision + learning.

---

## Requirements

### REQ-1: SearchProvider abstraction
**User Story:** As a developer I want a common interface for all search backends
so that adding a new provider (Exa, Brave, Tavily) is a single new class.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define an abstract `SearchProvider` class at
  `backend/crawler/search_providers/base.py` with `search(query, max_results)`
  returning `SearchResult`.
- AC2: THE SYSTEM SHALL define `SearchResult` and `SearchResultItem` dataclasses
  (query, provider, results list; url, title, snippet, content, score, date).
- AC3: WHEN a new provider class inherits from `SearchProvider` THEN it SHALL be
  usable by `CrawlPlanner` and tools with zero glue-code changes.

---

### REQ-2: ExaSearchProvider implementation
**User Story:** As a user with an Exa API key I want the assistant to search
the web using Exa's neural embedding index.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL implement `ExaSearchProvider` at
  `backend/crawler/search_providers/exa.py` reading `EXA_API_KEY` from env.
- AC2: WHEN `search(query, max_results=10)` is called THEN THE SYSTEM SHALL POST
  to `https://api.exa.ai/search` with the query, `numResults`, `type: "auto"`,
  and `contents: {text: true, highlights: true}`.
- AC3: THE SYSTEM SHALL map each Exa result to `SearchResultItem` (url, title,
  snippet from highlights, content from text, score, publishedDate).

**Edge Cases:**
- Missing key → `ValueError`. 401 → invalid key. 429 → rate limited with retry_after.
- Timeout / non-JSON → `SearchProviderError("upstream timeout")`.
- Empty results → return `SearchResult` with empty items (not error).

---

### REQ-3: Configurable provider selection
**User Story:** As a user I want to choose Exa or LLM-based search via config.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL read `search.provider` from `iris_config.json`
  (`"llm"` | `"exa"`), defaulting to `"llm"` when unset or unknown.
- AC2: WHEN config changes THEN the next search call SHALL use the new provider
  (no restart required — cached instance cleared on config change).

---

### REQ-4: `search` tool uses Exa content directly (fast path)
**User Story:** As a user asking a quick factual question I want the `search`
tool to return results in ~1 second using Exa's built-in content.

**Acceptance Criteria:**
- AC1: WHEN `search.provider` is `"exa"` THEN `_execute_web_search` SHALL call
  `ExaSearchProvider.search()` and build the result from highlights + URLs
  directly (no `CrawlOrchestrator`, no Crawl4AI subprocess).
- AC2: IF Exa returns 0 results or raises an error THEN THE SYSTEM SHALL fall
  back to `LLMSearchProvider`.
- AC3: WHEN `search.provider` is `"llm"` THEN `_execute_web_search` SHALL use
  the existing `CrawlOrchestrator.research()` path unchanged.

---

### REQ-5: `crawler_query` uses Exa URLs + Crawl4AI (deep path)
**User Story:** As a user asking for deep research I want the assistant to
discover URLs via Exa's neural search and extract full content via Crawl4AI.

**Acceptance Criteria:**
- AC1: WHEN `search.provider` is `"exa"` THEN `CrawlPlanner.plan()` SHALL call
  `ExaSearchProvider.search(query)` and build a `CrawlPlan` from the returned
  URLs (replacing the LLM-generated-URL path).
- AC2: The `CrawlPlan` SHALL feed into the existing `CrawlOrchestrator` pipeline
  (fetch via `SubprocessFetchBackend` → extract → cite → score → dashboard)
  unchanged.

---

### REQ-6: LLMSearchProvider (refactor existing behavior)
**User Story:** As a user without an Exa key I want LLM-URL search to remain
fully functional.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL move `CrawlPlanner._call_llm` + `_parse` into
  `LLMSearchProvider` at `backend/crawler/search_providers/llm.py`.
- AC2: `search()` SHALL return `SearchResult` with items from LLM-generated
  URLs, or empty when the LLM produces no URLs (no DuckDuckGo fallback).

---

### REQ-7: Secure credential storage
**User Story:** As a security-conscious user I want my API key outside of git.
- AC1: `EXA_API_KEY` SHALL be read from `.env` (not `iris_config.json`).
- AC2: The settings UI SHALL save the key to `.env` via the backend.

---

### REQ-8: Frontend settings UI
**User Story:** As a user I want to configure search provider + API key from
the settings panel.
- AC1: Settings sidebar SHALL have a "Search" section with provider dropdown.
- AC2: WHEN "Exa" is selected SHALL show a password-masked API key input.
- AC3: Save button SHALL send key + provider to backend via WS/REST.

---

### REQ-9: Error handling + fallback chain
**User Story:** As a user I want searches to work even when Exa is unreachable.
- AC1: IF Exa fails THEN THE SYSTEM SHALL fall back to `LLMSearchProvider`.
- AC2: IF both fail THEN the existing empty-plan / `CRAWLER_ERROR` applies.

---

### REQ-10: Contract + integration tests for providers
- AC1–AC5: Contract tests for Exa payload/mapping/errors; integration tests
  for fallback and provider switching.

---

### REQ-11: SourceRegistry — learned topic→URL knowledge base
**User Story:** As a user I want the assistant to learn which URLs are good for
which topics over time, so searches get smarter without repeating work.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL implement `SourceRegistry` at
  `backend/crawler/source_registry.py` storing topic→URL mappings in semantic
  memory (category `"source_registry"`, keyed by normalized topic).
- AC2: `SourceRegistry.resolve(query)` SHALL:
  1. Extract 3-5 key topics from the query via an LLM call.
  2. Look up each topic in the registry.
  3. Compute a **coverage score**: weighted sum of (credibility × freshness)
     across all known URLs for those topics.
  4. Return `ResolveResult(hit=True, sources=[...])` if score ≥ threshold,
     or `ResolveResult(hit=False)` if insufficient.
- AC3: `SourceRegistry.learn(query, search_result, credibility_map)` SHALL:
  1. Extract topics from the query.
  2. For each `SearchResultItem` whose URL credibility ≥ 0.3: save the mapping
     (topic → URL, credibility score, last_crawled timestamp, crawl_count).
  3. Update existing entries (new credibility = weighted running average).
- AC4: THE SYSTEM SHALL use the existing `SemanticStore` for persistence
  (new category `"source_registry"`, key format `topic:<normalized_topic>`).

**Edge Cases:**
- Empty query → return MISS with empty topic list.
- Known topic but all URLs stale (age > configurable TTL, default 7 days) →
  return MISS so fresh search fires.
- Known topic but all URLs have low credibility (< 0.5) → return MISS.
- LLM topic extraction fails → return MISS (safe fallback — fires search).

---

### REQ-12: Decision function — when to search vs use cached URLs
**User Story:** As a user I want the system to intelligently decide whether it
already has good enough coverage for my query or needs to search fresh.

**Acceptance Criteria:**
- AC1: `CrawlPlanner.plan()` SHALL call `SourceRegistry.resolve(query)` FIRST.
  - HIT → build `CrawlPlan` from cached URLs, **skip SearchProvider entirely**.
  - MISS → call configured `SearchProvider.search(query)`, then call
    `SourceRegistry.learn()` with the results.
- AC2: `_execute_web_search()` SHALL call `SourceRegistry.resolve(query)` FIRST.
  - HIT → return results from cached sources' snippets/content directly
    (no Exa call, no Crawl4AI).
  - MISS → call `SearchProvider.search()`, learn, return results.
- AC3: The coverage threshold SHALL be configurable in `iris_config.json`
  (`search.registry_threshold`, default `2.0`). Higher = more conservative
  (searches more often). Lower = more aggressive (caches more often).

**Edge Cases:**
- Registry has partial coverage (some topics known, some not) → MISS with
  known URLs passed as seed URLs + SearchProvider fires for new ones.
  (Future: hybrid plan that merges cached + searched URLs.)

---

### REQ-13: Learning from crawl results (automatic feedback loop)
**User Story:** As a user I want every crawl to automatically improve the
SourceRegistry so it learns which URLs are good for which topics.

**Acceptance Criteria:**
- AC1: AFTER each successful `CrawlOrchestrator.research()` call completes,
  THE SYSTEM SHALL pass the query, `SearchResult` (used), and
  `credibility_map` + `citation_index` to `SourceRegistry.learn()`.
- AC2: `learn()` SHALL only save URLs with credibility ≥ 0.3 (ignore junk).
- AC3: AC2 SHALL increment `crawl_count` for URLs already in the registry
  (reinforcing good sources) and update `last_crawled` timestamp.
- AC4: IF a URL fails to crawl (timeout, error, empty content) THEN its entry
  SHALL be penalized (credibility reduced ×0.5) so the system gradually
  stops suggesting broken URLs.

**Edge Cases:**
- Same URL crawled multiple times → credibility = weighted running average
  (new credibility × 0.3 + old credibility × 0.7).
- URL that was once good but consistently fails → credibility drops below
  0.3 → removed from registry.

---

### REQ-14: Freshness and decay of cached URLs
**User Story:** As a user I want the system to notice when a cached URL is
stale and re-fetch it rather than serving outdated content.

**Acceptance Criteria:**
- AC1: Each SourceRegistry entry SHALL have a `last_crawled` timestamp.
- AC2: WHEN calculating coverage score, entries older than `registry_ttl_days`
  (default 7, configurable in config) SHALL have their score halved (deemphasized
  but not automatically discarded — they may still be relevant).
- AC3: WHEN the only sources for a topic are past their TTL THEN
  `resolve()` SHALL return MISS (forces fresh search).
- AC4: AFTER a fresh crawl, `learn()` SHALL update `last_crawled` for existing
  entries (refreshing them).

**Edge Cases:**
- A perpetually stale topic (e.g., a domain that always returns old content) →
  credibility drops → removed from registry after repeated failures.
- User explicitly wants "refresh this topic" → future tool.

---

### REQ-15: Integration with Mycelium memory framework
**User Story:** As a developer I want the SourceRegistry to read/write through
the existing memory system so it's connected to the agent's knowledge.

**Acceptance Criteria:**
- AC1: SourceRegistry WRITE SHALL use `SemanticStore.store()` with category
  `"source_registry"`, key `topic:<normalized_topic>`, value = JSON list of
  URL entries. This stores cross-session learned knowledge.
- AC2: SourceRegistry READ for credibility SHALL query the `reference` zone
  (episodic memory, `_ZONE_REFERENCE`) to get per-URL credibility scores from
  past crawls. (The `credibility_map` is already persisted there by
  `pacman_fragment.execute()`.)
- AC3: WHERE the `reference` zone has no credibility for a URL, the registry
  SHALL use the URL's own `crawl_count` ÷ total_crawls as a credibility proxy
  (frequent successful crawls = higher trust).
- AC4: THE SYSTEM SHALL NOT duplicate data across zones — the SourceRegistry
  stores topic→URL MAPPINGS in semantic memory, and the reference zone stores
  per-URL CREDIBILITY. The two are joined at query time.

---

### REQ-16: System prompt injection for existing sources
**User Story:** As a user I want the agent to naturally know when it already
has sources for a topic, without needing an explicit tool call.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL inject known topic→URL mappings from the SourceRegistry
  into the agent's system prompt or tool descriptions so the LLM is aware of
  its known sources.
- AC2: WHEN the agent has high-confidence sources for a topic AND the user asks
  a related question THEN the agent SHALL prefer using those URLs over calling
  `search` or `crawler_query`.
- AC3: This SHALL be implemented as a prompt augmentation at the DER step
  resolution level, not a separate tool call (zero additional latency when
  sources are known).

**Edge Cases:**
- Too many known sources → inject top 5 by credibility only (avoid context
  bloat).
- User asks for something the agent has sources for but the user explicitly
  says "search fresh" → the agent should respect the explicit instruction.

---

## Non-Requirements (Out of Scope)
- Brave/Tavily/Linkup provider implementations (future; abstraction is ready).
- Exa's `deep`/`deep-reasoning` search modes (future; start with `auto`).
- Exa's `find_similar` endpoint (future).
- Manual source management UI (add/remove known URLs by hand) — phase 2.
- Cross-user SourceRegistry sharing (single-user assistant).

---

## Open Questions
- Should Exa be the DEFAULT provider, or "opt-in" behind LLM? Design decision:
  LLM stays default, Exa is opt-in via settings → safer, no key needed to start.
- SourceRegistry TTL default: 7 days? 30? Start at 7 (conservative).
- Coverage threshold default: 2.0? This means 2 topics with credibility 0.8
  each = 1.6 < 2.0 → MISS. 3 topics at 0.8 = 2.4 ≥ 2.0 → HIT. Reasonable.

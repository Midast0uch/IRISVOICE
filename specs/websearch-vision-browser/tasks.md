# Tasks: Fast Research + Real In-App Browser Control (rev 2, 2026-09-30)

Read `requirements.md` and `design.md` first. Every task carries DONE / NOT THIS (CLAUDE.md "THE
SCOPE BOUND"). Re-verify every file:line before editing. Targeted test runs only (never the full
suite; behavioral tests with a time cap). Never start the backend with `preview_start`; the
Director runs the live evals. THE TEST RULE: existing tests are the requirement - never change
an existing test's assertions or inputs; if one conflicts with this spec, STOP and report it.

Baseline any failing test on the committed code (`git stash push -- <file>`, run, `git stash
pop`) before calling it yours. Known pre-existing failures are listed in
`docs/audits/2026-09-29/PROGRESS.md` ("How to run the evals safely").

---

## Wave A - research speed and correctness (implement first; the Director measures after)

- [ ] **A1 (REQ-1 AC1.1-1.2, RC3): Exa quick tier works.**
  Parse top-level `text` / `highlights` (fallback `content.text`); make the HTTP client valid on
  the calling loop (D1). Record one real Exa response as a test fixture (strip the API key).
  DONE = a contract test parses the fixture into items with non-empty content + snippet, and two
  `search()` calls under two separate `asyncio.run` loops both succeed.
  NOT THIS = new providers, provider registry changes, changing Exa `type`.

- [ ] **A2 (REQ-2 AC2.1-2.3, AC2.5, RC1): policy User-Agent; 403 = blocked.**
  `IRIS_CRAWL_USER_AGENT` default per D3 for Tier-1 and robots.txt; bare 401/403 -> `blocked`
  -> park + `record_wall()`, no Tier-2 escalation; bounded timeouts on `new_context`, `new_page`,
  `goto` in the Tier-2 path.
  DONE = unit tests: 403 without markers -> `blocked` and no browser call; a challenge marker page
  -> `challenge` (unchanged); a hanging `new_context` stub returns within its bound.
  NOT THIS = UA rotation, stealth plugins, retry loops.

- [ ] **A3 (REQ-2 AC2.4-2.5, RC2): quorum return.**
  `dispatch_urls` returns at `min_pages` usable + grace and cancels the rest (D4); per-URL budget
  starts after the semaphore.
  DONE = a test with 5 stub URLs (3 fast usable, 2 that never finish) returns in < grace + 1 s
  with 3 pages and 2 `cancelled_enough`, none parked.
  NOT THIS = changing concurrency limits, the run budget value, or rerank.

- [ ] **A4 (REQ-1 AC1.3-1.4, RC4): factual goals try `search` first.**
  `_mem_lookup` routes web goals to `search` with a shaped query (D2, reuse an existing helper
  if present); quick-tier result carries `requires_deep_crawl`; insufficient -> `crawler_query`.
  DONE = a unit test: a factual web goal resolves to `search` with a query that no longer contains
  "search the web"; a `requires_deep_crawl` result escalates to `crawler_query` once.
  NOT THIS = a new classifier, Oracle enforcement, changing `_MAX_CRAWLS_PER_TASK`.

- [ ] **A5 (REQ-3 AC3.1-3.3, RC5): one model pass on the answer path.**
  Agent-path `DataExtractor` on `durability_queue.lane("web_extract")`, emitting the same
  `OPEN_TAB` payload when it lands; its model call on the light path with tools off; topic
  extraction via `quick=True` or a per-query cache.
  DONE = a test proves `research()` (agent mode) returns before a blocked extractor finishes and
  the `OPEN_TAB` event still arrives with the dashboard payload after it unblocks; a test counts
  <= 1 topic-extraction model call per distinct query.
  NOT THIS = changing the gateway (user-initiated) path, the extractor prompt, or the dashboard
  payload shape.

- [ ] **A6 (REQ-3 AC3.4-3.5, RC6): output quality.**
  `goal_contract` ignores `--- Source: ... ---` and page scaffolding lines; a synthesis below the
  length floor retries once, never dumps raw sources.
  DONE = unit tests for both, using r02's real inputs where available (the `--- Source:` content
  shape).
  NOT THIS = rewriting synthesis prompts.

- [ ] **A7 (REQ-7): one timing line per web tool call** (`search_ms`, `crawl_ms`,
  `pages_usable`, `pages_cancelled`, `extract_ms`, `browser_actions`, `cursor_events`).
  DONE = the line appears in a test run's log output with all keys.
  NOT THIS = a metrics framework, a new logger module.

- [ ] **TG-A (gate):** run the targeted tests of every file touched (crawler, capabilities,
  orchestrator, tool_bridge web paths, agent_kernel `_mem_lookup`, goal_contract, search
  providers) and report pass/fail with pre-existing failures baselined. The Director then runs
  r01-r08 live.

---

## Wave B - real browser control (after Wave A is measured)

- [ ] **B1 (REQ-4 AC4.1-4.2, 4.5): session holder + `browser_observe`.** On `BrowserSession`
  (D6): per-conversation holder (bounded, LRU), observe script with `data-iris-mark`, text marks,
  marked screenshot only when a vision model is live.
  DONE = behavioral test against a local static fixture page lists the button, input and link
  with correct roles/names and boxes.
- [ ] **B2 (REQ-4 AC4.3-4.4, REQ-5 AC5.1-5.2): `browser_act` with pre-glide events.** Real
  mouse/keyboard, approach event before input with x/y fractions, done event after with `ok`,
  errors surfaced (fix the `last_error` swallow).
  DONE = behavioral test: click changes the fixture DOM; typing fills the input with per-key
  delays; events arrive approach -> done in order with correct x/y; an unknown id returns
  `ok=false` and emits no approach.
- [ ] **B3 (REQ-5 AC5.3): the iframe follows.** Publish a capture after each page-changing act.
  DONE = test asserts a new capture page is published after a click that changes the DOM.
- [ ] **B4 (REQ-4 AC4.1, 4.6): tools registered and offered.** `browser_open/observe/act` in
  `tool_registry.py` + `tool_bridge.py`; offered for interaction goals; the crawl can hand an
  unreadable page to the session; `fetch.vision` spec `hidden=True`.
  DONE = contract test: the tool registry exposes the three tools with schemas; `fetch.vision`
  is not LLM-facing.
- [ ] **TG-B (gate):** targeted tests + the Director drives one live interaction task through the
  real app and watches the overlay (Mode B), then records the frontend contract result.

## Wave C - Oracle (after Wave B)

- [ ] **C1 (REQ-6):** `web_depth` and `browser_next` shadow consumers with reference labels.
  DONE = consumer registry contract test lists both; rows appear in the store after an eval run.
  NOT THIS = enforcement, threshold changes.

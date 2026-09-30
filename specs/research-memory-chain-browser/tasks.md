# Tasks: Research Memory, the Immortus Time Layer, Autonomous Browser (rev 1, 2026-09-30)

Read `requirements.md` and `design.md` first. Every task carries DONE / NOT THIS (CLAUDE.md "THE
SCOPE BOUND"). Re-verify every file:line before editing. Targeted test runs only (never the full
suite; behavioral tests with a time cap). Never start the backend or run evals - the Director
measures live. The owner allows test changes that improve these features: state EVERY change to
an existing test (what and why) in the commit message. Baseline any failing test on the committed
code (`git stash push -- <file>`, run, `git stash pop`) before calling it yours; known
pre-existing failures: `docs/audits/2026-09-29/PROGRESS.md` + pin_57d2554decaf.

Waves R, K and W touch different files and run in parallel (separate builders, separate
worktrees). Shared file: `backend/agent/tool_bridge.py` (R: search/crawler result sections; W:
consent gate skip + explore dispatch) - keep each edit small and local.

---

## Wave R - research memory (REQ-1, REQ-2, REQ-3 backend)

- [ ] **R1 (REQ-1): `research_memory.record_research` + landing hooks.** D1. Called from the
  orchestrator landing (deferred lane job and sync path, via an optional `on_dashboard` callback
  that tool_bridge passes and that also completes the job registry with the summary - AC1.3) and
  from the quick-tier `search` executor.
  DONE = contract test: a landed research result produces one document_data row (fmt research),
  one chain row (nbl_outcome research, file_path = document id, result is a reference < 2 KB), and
  one fragment job with chunk_type research_summary / zone reference - all written from a lane,
  none on the answer path (a blocked lane does not delay the tool result). Registry result has the
  summary after the extraction lands.
  NOT THIS = a new store/table, a class hierarchy, embedding inline, changing the dashboard payload.
- [ ] **R2 (REQ-2 AC2.1-2.2): concurrent prior lookup.** `recall_prior_research` runs in a thread
  started with the web call in `search` and `crawler_query`; bounded 3 s; the result gets a PRIOR
  RESEARCH section (<= 1,500 chars). Excludes the record produced by the same job.
  DONE = behavioral test with a real EpisodicStore on a temp DB (a stub embedder is allowed ONLY
  if the real one cannot load in tests - say so): record A about topic X; a later search on a
  paraphrase of X returns a result whose content contains A's summary and date; an unrelated query
  does not; a blocked lookup does not delay the result beyond its bound.
  NOT THIS = answering from memory without searching, Oracle enforcement, a new retrieval engine.
- [ ] **R3 (REQ-2 AC2.3): cross-check.** `cross_check` labels confirmed / changed / not_rechecked /
  new; the section lists them with both dates; one synthesis instruction line (D2).
  DONE = unit tests: a prior claim "Tokyo population 13,960,000 (2021)" vs new text with
  "14,246,219" -> changed; the same number -> confirmed; unrelated -> not_rechecked.
  NOT THIS = an LLM judge, contradiction search across all history.
- [ ] **R4 (REQ-2 AC2.4): `recall_research` tool.** read_only ToolSpec + tool_bridge executor;
  in `_DER_READ_TOOLS`.
  DONE = contract test: registry exposes it read_only with schema; S11 capture gate returns False
  for it; by-id and by-query both return records.
- [ ] **R5 (REQ-3 AC3.1): API.** `GET /api/research/history`, `GET /api/research/{id}`.
  DONE = API test (FastAPI TestClient on a temp store): list returns metadata only (no content
  blob); get returns the record; unknown id -> 404.
  NOT THIS = auth changes, pagination beyond `limit`.

## Wave K - the Immortus chain as the time layer (REQ-4)

- [ ] **K1 (AC4.1): real coordinates or NULL at every writer.** `api/chat.py`, `agent/mcm.py`,
  the DER step fold's missing-prior case, `_store_document_data`'s empty case.
  DONE = contract test per writer: the row's coords are `format_coords` output or NULL - never
  `rest:`, `[`, or `0.00,0.00,0.00,0.00` for "unknown".
  NOT THIS = rewriting old rows, physics changes (F7 is reported, not fixed).
- [ ] **K2 (AC4.2, AC4.4): hybrid recall at `_der_recall_neighborhood`.** Meaning filter (widened
  candidate pool) x state proximity x recency (D4); reference rows show their head; one
  `[chain_recall] rows= ms=` log line.
  DONE = behavioral test on a temp store: two rows with the same topic, one near the current
  coordinate and recent, one far and old -> the near/recent one ranks first; a row from another
  topic at the SAME coordinate is not returned (meaning first); S2 still holds (EXPLAIN shows the
  index, no temp sort - run `test_answer_path_standards.py`).
  NOT THIS = a new vector index, reading u/xi in the router, changing RecallFilters semantics.
- [ ] **K3 (AC4.3): task timeline.** `chain_timeline(thread_id, limit=8)`; injected where replan /
  continuation context is built.
  DONE = unit test for the format and bound; a contract test that the replan context contains the
  timeline block when the thread has rows.
  NOT THIS = a new table, the full history.

## Wave W - one browser, exploration, autonomous actions (REQ-5, REQ-6, REQ-7)

- [ ] **W1 (REQ-5): BrowserHost.** D5. One loop thread, one Chromium, pool + sessions through it,
  memory flags, crawl contexts block media/font.
  DONE = behavioral test (real Chromium, local fixture, no network): a pool crawl fetch and a
  browser session run concurrently from two different event loops and both succeed; exactly ONE
  Chromium launch happens (count launches); the existing browser tests still pass
  (`test_browser_control_behavior.py`, `test_browser_tools_contract.py`,
  `contract/test_browser_warm_path_contract.py`, capability tests). Report the Chromium process
  tree working set for "one crawl + one session" before/after (psutil), measured in the test run.
  NOT THIS = moving the crawl4ai subprocess, a browser farm, config knobs nobody asked for.
- [ ] **W2 (REQ-7): self-gated browser tools + ClickSafety + escalation + pivot + shadow row.** D7.
  DONE = contract tests: no PERMISSION_REQUEST is emitted for browser_* with auto-approve OFF;
  rules classify a fixture set (buy/checkout/delete/password-submit -> unsafe; nav link, next
  page, search box, cookie decline -> safe; an ambiguous "Continue" -> unsure); unsure + Brain
  unsure + user timeout -> `ok=false, pivot=true`, no input dispatched, no approach event; unsure +
  user yes -> acts; one click_safety shadow row per assessment with the gate verdict label.
  NOT THIS = Oracle enforcement, a policy engine/DSL, prompting for safe clicks.
- [ ] **W3 (REQ-6): exploration.** D6 crawl same-site hop + `browser_explore` tool (self-gated,
  read_only).
  DONE = behavioral test on a local multi-page fixture site: goal-relevant subpages are visited
  and irrelevant ones are not; bounds hold (pages, time); the crawl hop runs only when kept
  passages are insufficient.
  NOT THIS = sitemap crawling, depth > 1 for the crawl, crawling other hosts.

## Wave U - history in the dashboard (REQ-3 AC3.2) - after R5 lands

- [ ] **U1:** history list in the dashboard tab; open -> stored dashboard via the existing
  renderer. DONE = `npx tsc --noEmit` clean + a component test or a Mode B UI check by the
  Director. NOT THIS = a new page, a new renderer.

## Gates (Director)

- [ ] **TG-R:** live evals: run r06 twice in two new conversations; the second reply states what
  was confirmed/changed since the first. Measure reply_s vs the first.
- [ ] **TG-K:** a live coding task; log shows `[chain_recall]` rows > 0 and ms; replan context
  shows the timeline.
- [ ] **TG-W:** Mode B UI drive: one browser task with a safe click (no prompt), an unsafe click
  (refused), an unsure click (question card; let it time out -> the agent pivots). Chromium
  working set measured idle and busy.

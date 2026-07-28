# Requirements: Unified Web-Search Architecture (Crawl Core + DER-Driven Research)

IRISVOICE · backend/agent + backend/crawler + frontend · July 2026

---

## Introduction

IRIS Voice has two divergent web-search paths — the `crawl_research` WebSocket
handler (`iris_gateway.py:8685`) and the agent `crawler_query` tool
(`tool_bridge.py:1521`) — that use the same crawl family but emit different
events and render differently in the UI. This spec unifies them into a single
shared `CrawlOrchestrator` core driven by the DER loop, raises retrieval quality
to the Perplexity-grade standard (credibility scoring, passage-level reranking,
inline citation binding), and emits one consistent event stream to the frontend
and audio feedback layer.

### Hard architectural constraints (non-negotiable)

- **DER blueprint §1 (System Invariant):** ONE recursive operator fans out and
  folds back at FOUR scales (step, Sub-Loop, context window, outer loop), driven
  by the SAME Caducean physics (`u/ξ`), sharing ONE resource
  `W0 = resolve_context_window() / avg_step_cost`. **No mode-driven fan-out, no
  web-regex override.** All behavior collapses into the one operator.
- **`ExecutionMode` is display-only** (`der_constants.py:21-31`). It MUST NOT
  drive execution-tree shape. Step shape is decided by live `(u, ξ)` via
  `_split_step` / `_growth_width`.
- **Steps are physics-based, hard rules (Tier 2):** `_growth_width(u)` → split
  WIDE (3) when `|u| < U_SPLIT` (0.5), atomic when `U_SPLIT ≤ |u| < 0.85`
  (mid-band, LLM rubric), atomic-deterministic when `|u| ≥ 0.85` (converged).
  Termination = `work_units` (from `W0`), `MAX_DEPTH=3`, `DER_MAX_GRAFTS=3`,
  `DER_MAX_CYCLES=40`.
- **Blueprint-pure narration:** all TTS serialized through
  `_NARRATION_PLAYBACK_LOCK`; no mode-driven fan-out, no web-regex override.

### Success criteria

- Both `crawl_research` (WS) and agent `crawler_query` emit the IDENTICAL event
  sequence (`crawler_started` → `crawler_page_fetched`* → `open_tab` →
  `crawler_error`) for the same query.
- Every factual sentence in a synthesized web answer is bound to a source
  citation (`chunk_id` → URL).
- A `crawler_query` step is verified by the SAME `|u|`-band path as any other DER
  step; no special web verifier exists.
- Sub-topic fan-out for deep research emerges from `_split_step` (`u/ξ`), not
  from a "research mode".
- Web access gate closed → agent returns `success:False` "web access disabled";
  no fetch attempted.
- Crawl subprocess crash/timeout → `CrawlOrchestrator` returns `CrawlResult.error`
  set, never raises; backend survives.
- Existing test suite passes with zero regressions (DER smoke, doc-render trust,
  web-gate, capture, both contract suites).

---

## Requirements

### REQ-1: CrawlOrchestrator Core Module
**User Story:** As the backend, I want a single crawl core that both entry points
call, so that retrieval logic lives in one place and cannot diverge.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define `CrawlOrchestrator` in `backend/crawler/orchestrator.py`
  with a single public async entry
  `research(query: str, *, mode: Literal["ws","agent"], session_id: str, on_progress: Callable[[CrawlProgress], None], max_pages: int = 5) -> CrawlResult`.
- AC2: THE SYSTEM SHALL NOT change any existing method signature outside this
  module and the `tool_bridge.py` / `iris_gateway.py` refactors.
- AC3: WHEN `mode == "ws"` THEN THE SYSTEM SHALL fetch via the in-process `CrawlerEngine`.
- AC4: WHEN `mode == "agent"` THEN THE SYSTEM SHALL fetch via `run_crawl_subprocess`
  (isolated process) and SHALL return even on subprocess crash (see REQ-17).
- AC5: THE SYSTEM SHALL run the internal funnel in this fixed order: Plan → Fetch
  → Passage-Split → Credibility-Score → Passage-Rerank → Extract+Cite → Return.

**Edge Cases:** module import failure → backend startup must still succeed (lazy
import of heavy crawl deps); `on_progress` is None → events are no-ops.

### REQ-2: Plan Stage
**User Story:** As the orchestrator, I want a ranked URL plan before fetching, so
that fetch effort targets the most relevant sources.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL invoke `CrawlPlanner` (existing LLM) to produce ranked
  candidate URLs, extraction instructions, and a `result_type`, unchanged from
  current behavior.
- AC2: WHEN `CrawlPlanner` returns zero URLs THEN THE SYSTEM SHALL emit
  `crawler_error` with reason "no candidate urls" and return `CrawlResult` with
  `pages=[]`.

**Edge Cases:** planner timeout → treat as zero URLs; planner returns duplicate
URLs → dedupe before fetch.

### REQ-3: Fetch Stage
**User Story:** As the orchestrator, I want each planned URL fetched with
per-page error isolation, so one bad page does not sink the batch.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL fetch each planned URL via the mode-appropriate engine and
  SHALL produce `PageData{url, title, markdown, html, metadata, error}` per page.
- AC2: WHEN a page fetch fails THEN THE SYSTEM SHALL set `PageData.error` and SHALL
  continue to the next URL (partial results allowed).
- AC3: THE SYSTEM SHALL cap fetched pages at `max_pages` (default 5) and SHALL
  honor a per-batch timeout (default 90s) — see REQ-17.

**Edge Cases:** all pages error → return empty passages, emit `crawler_error`;
redirect loop → cap redirects, mark error.

### REQ-4: Passage-Split Stage
**User Story:** As the reranker, I want pages split into logical chunks, so
citations can bind to precise spans, not whole documents.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL split each successfully fetched page into logical chunks
  of ≈300–600 tokens using heading/paragraph boundaries.
- AC2: EACH chunk SHALL carry metadata `{url, position, heading_path}`.
- AC3: WHEN a page has no extractable text THEN THE SYSTEM SHALL skip it from
  passage candidates but SHALL retain it in `pages` with `error="empty"`.

**Edge Cases:** very long single paragraph → split by sentence window; table-only
page → treat cells as chunks.

### REQ-5: Credibility Scorer
**User Story:** As the synthesizer, I want each source scored for trust, so the
final answer weights reliable sources higher.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL define `CredibilityScorer` assigning each SOURCE a
  credibility score in [0,1].
- AC2: THE SYSTEM SHALL classify every fetched source into exactly one source type
  from the REQ-6 table and SHALL apply that type's base weight.
- AC3: THE SYSTEM SHALL compute final credibility as
  `base_weight × freshness_factor × corroboration_factor × structural_factor`,
  clamped to [0,1].
- AC4: WHEN two or more independent primary_official or academic sources agree on
  a claim THEN THE SYSTEM SHALL boost that claim's credibility in the final synthesis.
- AC5: WHEN a source has no publish/update date THEN `freshness_factor` SHALL
  default to 0.5.

**Edge Cases:** unknown TLD → type `unknown`; paywalled/blocked page →
structural_factor low.

### REQ-6: Source-Type Table
**User Story:** As the credibility scorer, I want a fixed type→weight map, so
scoring is deterministic and reviewable.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL use these source types and base weights:

| type | examples | base_weight |
|---|---|---|
| primary_official | .gov, .edu, RFCs, docs, press releases | 0.9 |
| academic | papers, journals, arXiv | 0.85 |
| news | reputable outlets | 0.7 |
| reference | encyclopedias, Wikis | 0.6 |
| blog | personal/company blogs | 0.4 |
| forum | Reddit, HN, StackOverflow | 0.3 |
| unknown | unclassified | 0.5 |

- AC2: THE SYSTEM SHALL derive type from URL TLD/class heuristics and SHALL NOT
  require network calls to classify.

**Edge Cases:** ambiguous host (e.g. subdomain blog on a news domain) → apply most
specific match rule, document in code comment.

### REQ-7: Passage Rerank Stage
**User Story:** As the orchestrator, I want passages ranked and thresholded, so
low-quality spans never reach synthesis.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL rank passage candidates using hybrid scoring (BM25 +
  embedding similarity to the query).
- AC2: THE SYSTEM SHALL apply a cross-encoder reranker over the top passage
  candidates and SHALL drop any passage whose rerank score falls below the
  configured threshold (default 0.3).
- AC3: WHEN the top passage rerank score is below threshold THEN THE SYSTEM SHALL
  prefer re-querying (narrow the query, re-run Plan→Fetch for up to one additional
  internal attempt) over returning low-credibility citations.
- AC4: THE SYSTEM SHALL produce `Passage{chunk_id, url, text, credibility, score}`
  for each retained passage, ordered by score descending.

**Edge Cases:** embedding model unavailable → fall back to BM25-only; reranker
unavailable → use hybrid score as final.

### REQ-8: Extract + Cite Stage
**User Story:** As the user, I want every factual claim tied to a source, so I can
verify the answer.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL invoke `DataExtractor` (existing LLM) to build the
  structured answer from retained passages.
- AC2: THE SYSTEM SHALL require `DataExtractor` to bind EVERY factual claim to a
  `chunk_id` present in `passages` (inline citation).
- AC3: THE SYSTEM SHALL return `cited_markdown` in which each cited sentence
  carries an annotation `[n](url)` referencing the source URL of that `chunk_id`.
- AC4: WHEN `DataExtractor` cannot ground a claim to any passage THEN THE SYSTEM
  SHALL mark that claim as unsourced in `cited_markdown` (e.g. `[?]`) and SHALL
  record it in `credibility_map.unsourced_claims`.

**Edge Cases:** extractor returns no citations → all claims flagged unsourced;
extractor hallucinates a `chunk_id` not in passages → drop citation, flag unsourced.

### REQ-9: CrawlResult Structure
**User Story:** As the caller, I want a single well-defined result object, so WS
and agent paths consume identical shapes.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL return `CrawlResult{query, pages, passages,
  dashboard_data, cited_markdown, credibility_map, duration_ms, error}`.
- AC2: `credibility_map` SHALL contain `{per_source: {url: score},
  unsourced_claims: [int], top_score: float}`.
- AC3: WHEN `research` completes normally THEN `error` SHALL be `None`.

**Edge Cases:** partial batch → `pages` may be shorter than planned; `passages`
may be empty if all reranked out.

### REQ-10: Unified Event — crawler_started
**User Story:** As the UI, I want a single "search started" signal, so the orb and
pill can enter the processing state consistently.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL emit `IRISStreamEvent.CRAWLER_STARTED` with
  `{query, url_count}` as the FIRST event of a research batch, for BOTH `ws` and
  `agent` modes.
- AC2: THE SYSTEM SHALL emit this via the `on_progress` callback passed to `research`.

**Edge Cases:** zero URLs (REQ-2) → still emit `crawler_started` then `crawler_error`.

### REQ-11: Unified Event — crawler_page_fetched
**User Story:** As the dashboard wing, I want each fetched URL streamed with its
full URL, so the user sees what is being read regardless of entry point.

**Acceptance Criteria:**
- AC1: WHEN a page is fetched during research THEN THE SYSTEM SHALL emit
  `IRISStreamEvent.CRAWLER_PAGE_FETCHED` with the FULL URL (not merely a host
  string), `{url, page_number, total, host}`, for BOTH entry points.
- AC2: THE SYSTEM SHALL emit one `crawler_page_fetched` per successfully fetched
  page, in fetch order.

**Edge Cases:** fetch error → no `crawler_page_fetched` for that URL (it is not
"fetched"); duplicate URL → emit once per unique fetch.

### REQ-12: Unified Event — open_tab
**User Story:** As the dashboard, I want the parsed result opened as a tab, so the
user can inspect structured findings.

**Acceptance Criteria:**
- AC1: WHEN research yields a structured result THEN THE SYSTEM SHALL emit
  `IRISStreamEvent.OPEN_TAB` with `{tab_type:"dashboard", id, title, data}` so the
  dashboard wing renders the parsed result, for BOTH entry points.
- AC2: THE SYSTEM SHALL populate `data` from `dashboard_data` (DataExtractor output).

**Edge Cases:** `dashboard_data` empty → still emit `open_tab` with minimal data
(no crash in wing).

### REQ-13: Unified Event — crawler_error
**User Story:** As the UI, I want a single error signal for a failed batch, so
error toasts are consistent.

**Acceptance Criteria:**
- AC1: WHEN a batch fails to produce any result (no URLs, all fetches error,
  timeout) THEN THE SYSTEM SHALL emit `IRISStreamEvent.CRAWLER_ERROR` with
  `{message}`.
- AC2: THE SYSTEM SHALL NOT emit `open_tab` when `crawler_error` is emitted for
  that batch.

**Edge Cases:** partial success (some pages) → no `crawler_error`; only full
failure triggers it.

### REQ-14: Deprecate TASK_PROGRESS Search Overwrite
**User Story:** As the frontend, I want one source of truth for search progress, so
the two entry points never render differently.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL remove the `task:progress` "Reading host (N/M)" overwrite
  used for search progress in `hooks/useTaskProgress.ts` (lines ~268-273).
- AC2: THE SYSTEM SHALL route live URL feedback for search exclusively through
  `crawler_page_fetched` → dashboard-wing `onPage` (see REQ-20/25).
- AC3: Non-search `task:progress` consumers SHALL remain unchanged.

**Edge Cases:** other tools that used the same overwrite key → verify none break.

### REQ-15: WS Entry Point Refactor (crawl_research)
**User Story:** As the WS handler, I want to delegate to the shared core, so WS and
agent behavior cannot drift.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL refactor `iris_gateway.py:8685` `crawl_research` to call
  `CrawlOrchestrator.research(mode="ws", …)` instead of invoking `CrawlerEngine`
  directly.
- AC2: THE SYSTEM SHALL pass an `on_progress` callback that emits the unified
  events (REQ-10–13) using the existing event-bus emit path.
- AC3: THE SYSTEM SHALL preserve the existing `text_response` final delivery.

**Edge Cases:** WS client disconnects mid-crawl → `on_progress` emit must not
raise.

### REQ-16: Agent Entry Point Refactor (crawler_query)
**User Story:** As the agent tool, I want to delegate to the shared core AND emit
the same events, so the UI shows URLs/tabs for agent-driven search too.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL refactor `tool_bridge.py:_execute_crawler_query` to call
  `CrawlOrchestrator.research(mode="agent", …)`.
- AC2: THE SYSTEM SHALL pass an `on_progress` callback that emits
  `crawler_started`, `crawler_page_fetched`, and `open_tab` (previously WS-only for
  the agent path).
- AC3: THE SYSTEM SHALL return the `CrawlResult` dict (pages, cited_markdown,
  credibility_map) to the agent, unchanged in consumer shape from today.

**Edge Cases:** agent path must still work when no WS client is connected (events
buffered/dropped safely).

### REQ-17: Crash-Isolation & Graceful Degradation (subprocess backend)
**User Story:** As the backend, I want a crawl crash to never take down the
process and the crawl to complete reliably in the background, so web search is
fault-tolerant and non-blocking.

**Acceptance Criteria:**
- AC1: WHEN the crawl subprocess crashes or times out THEN `CrawlOrchestrator`
  SHALL return a `CrawlResult` with `.error` set (never raise), so the agent
  degrades gracefully and the backend survives.
- AC2: THE SYSTEM SHALL set a per-batch timeout (default 90s) and SHALL kill the
  ENTIRE subprocess TREE (process group / job object on Windows, not just the
  parent PID) on timeout, so orphaned Chromium child processes are reaped.
- AC3: WHEN `research` returns `error` set THEN the agent tool SHALL return
  `success:False` with the error message and SHALL NOT emit `open_tab`.
- AC4: THE SYSTEM SHALL isolate fetch behind a swappable `FetchBackend` interface
  (`FetchBackend.research(query, max_pages) -> list[PageData]`) so the subprocess
  implementation can later be promoted to a long-lived crawl-worker DAEMON without
  changing the funnel (Plan→…→Extract). `mode="ws"` uses the in-process backend;
  `mode="agent"` uses the subprocess backend.
- AC5: THE SYSTEM SHALL cap concurrent crawl subprocesses (default 2) so that
  parallel DER Sub-Loop children (REQ-20) cannot spawn unbounded Chromium
  processes and OOM the host; excess batches SHALL queue or degrade to fewer pages.

**Edge Cases:** subprocess hangs on shutdown → force-kill process tree; orphaned
chromium → reaped by group kill; daemon backend later replaces subprocess with no
funnel change.

### REQ-18: Web Access Gate (fail-closed)
**User Story:** As the system, I want web access disabled to block all fetches, so
the user's privacy gate is enforced.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL NOT perform any web fetch WHEN the global internet-access
  gate (`set_global_internet_access`) is closed.
- AC2: WHEN the gate is closed and `crawler_query` is invoked THEN THE SYSTEM SHALL
  return `success:False` with error "web access disabled" and SHALL emit no crawl
  events.
- AC3: THE SYSTEM SHALL keep `_internet_provider` defaulting to `lambda: False`
  (`tool_registry.py:73`) — fail-closed.

**Edge Cases:** gate toggles mid-crawl → in-flight batch may finish; new batches
blocked.

### REQ-19: DER Integration — Single Atomic Tool
**User Story:** As the DER loop, I want web search to be one ordinary tool, so it
obeys the single-operator invariant.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL treat `crawler_query` as ONE atomic DER tool whose internal
  engine is `CrawlOrchestrator` (one retrieval batch). `crawler_query` SHALL NOT
  implement its own research loop.
- AC2: WHEN the Resolver (L3 `propose`) classifies a goal as requiring web evidence
  THEN THE SYSTEM SHALL resolve the step to `crawler_query` via the standard
  `propose()` path using `_is_web_intent(goal)` (not `task_class=="research"`),
  WITHOUT any mode switch or web-regex override.

**Edge Cases:** ambiguous intent → fall back to non-web tool; never force web.

### REQ-20: DER Integration — Physics-Driven Fan-Out
**User Story:** As the DER loop, I want deep research to fan out based on the
Caducean signal, so decomposition is physics-driven, not mode-driven.

**Acceptance Criteria:**
- AC1: WHEN a `crawler_query` step is unresolved (`|u| < U_SPLIT`) or its verifier
  returns FAILED/VETO THEN `_split_step` (L7) SHALL spawn Sub-Loop children that
  each re-invoke `CrawlerOrchestrator` with a narrowed query.
- AC2: THE SYSTEM SHALL bound split width by
  `min(_growth_width(u), DER_MAX_GRAFTS, work_units)` and SHALL refuse split at
  `depth_layer >= MAX_DEPTH`.
- AC3: THE SYSTEM SHALL collapse Sub-Loop children to the parent as ONE COMPRESS
  where Lyapunov Φ strictly decreases (split prepays `width` work units;
  completion consumes 1).
- AC4: THE SYSTEM SHALL NOT branch on `ExecutionMode` to change split width or
  verify strictness for web-search steps (mode is display-only).

**Edge Cases:** `work_units` exhausted → no split, step marked terminal;
`DER_MAX_GRAFTS` reached → stop grafting.

### REQ-21: DER Integration — Standard Verification
**User Story:** As the Reviewer, I want web steps verified by the same path, so
there is no special-case web logic.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL verify a `crawler_query` step result via the SAME `|u|`-band
  path as any other step: `_verify_step_result` (deterministic: stub→FAILED,
  `_verified_fraction` ≥0.8→VERIFIED) plus, when `U_SPLIT ≤ |u| < U_CONVERGED`, the
  LLM `verify_rubric` verdict.
- AC2: THE SYSTEM SHALL NOT introduce a separate web verifier.
- AC3: WHEN the verifier returns VETO THEN THE SYSTEM SHALL route to `_split_step`
  (REQ-20), not to a hardcoded re-query branch.

**Edge Cases:** rubric unavailable → fall back to deterministic verdict.

### REQ-22: PacMan Trust Persistence
**User Story:** As memory, I want web fragments stored as untrusted with their
credibility map, so recall knows what was sourced.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL store every `crawler_query` output fragment in the pacman
  `reference` zone tagged `trust:"untrusted"` (existing `_EXTERNAL_TOOLS` routing).
- AC2: THE SYSTEM SHALL persist `credibility_map` and `citation_index` alongside
  the fragment so future recall knows which claims were sourced vs unsourced.
- AC3: THE SYSTEM SHALL NOT store web fragments in `trusted` or `system` zones.

**Edge Cases:** fragment too large → chunk before store; citation_index empty →
store with empty index.

### REQ-23: Document Render — Citations & Trust Badge
**User Story:** As the user, I want web answers clearly marked unverified with
clickable sources, so I can judge trust.

**Acceptance Criteria:**
- AC1: WHEN the frontend renders a web-sourced document (`document:render`) THEN
  THE SYSTEM SHALL display an unverified-source badge and SHALL sanitize content
  via DOMPurify (RichDocument).
- AC2: THE SYSTEM SHALL render `cited_markdown` citations as clickable links that
  open the source URL in a dashboard tab (reuse `open_tab` / browser-tab renderer).
- AC3: WHEN the agent is unsure of format THEN `_maybe_escalate_web_format` SHALL
  escalate to QuestionCard with options Markdown/Table/HTML/Diagram/Plain text.
- AC4: WHEN `crawler_error` is received THEN `dark-glass-dashboard.tsx` (or the
  chat-view error surface) SHALL render a non-blocking error toast with the message;
  the toast owner SHALL be the SAME component for both WS and agent paths.
- AC5: THE SYSTEM SHALL expose the rendered document and its citation list to
  assistive tech via an ARIA `role="document"` region and SHALL announce citation
  navigation; unsourced claims (`[?]`) SHALL carry `aria-label="unsourced claim"`.

**Edge Cases:** unsourced claims (`[?]`) → render with a distinct warning style;
malformed URL → link disabled, not crashed; error toast auto-dismisses and does
not block the orb.

### REQ-24: Frontend Feedback — Orb, ContextPill & Indicators
**User Story:** As the user, I want every visual indicator to agree that IRIS is
researching, so the state is unambiguous.

**Acceptance Criteria:**
- AC1: WHEN research is in progress THEN THE SYSTEM SHALL reflect `listening_state`
  `processing_tool` (not `listening`) on the orb and ContextPill.
- AC2: THE SYSTEM SHALL consume `listening_state` from `useIRISWebSocket.ts` with
  no mode-driven fan-out.
- AC3: THE SYSTEM SHALL pin XurOrb and OrbWorkingIndicator to the SAME
  `listening_state` source as the orb/ContextPill, so all three indicators show
  `processing_tool` during research (no component derives its own search state).
- AC4: WHEN research completes or errors THEN THE SYSTEM SHALL return the orb to
  its idle/listening state within one `listening_state` transition (no stuck
  "processing" after a long background crawl).

**Edge Cases:** rapid start/stop → debounce state flicker; long background crawl
finishing while user is idle → orb returns to idle, not screensaver-lock.

### REQ-25: Frontend Feedback — Dashboard Wing, Tabs & TaskListCard
**User Story:** As the user, I want the live URL list, result tabs, and task card
consistent for agent-driven search too, so both paths look identical.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL render the live URL list in `dashboard-wing.tsx` `onPage`
  from `crawler_page_fetched` (now fed by BOTH paths).
- AC2: THE SYSTEM SHALL render the parsed result in a browser tab from `open_tab`
  (`dark-glass-dashboard.tsx` ~1274).
- AC3: WHEN deep research spawns multiple `crawler_query` steps (REQ-20) THEN THE
  SYSTEM SHALL manage multiple browser tabs (one per `open_tab`) ordered by
  arrival, with a tab strip that supports switching/closing, so the user is not
  limited to a single result view.
- AC4: THE SYSTEM SHALL render a "Researching…" step in `TaskListCard`
  (`chat-view.tsx` ~2622) during an in-progress `crawler_query`, replacing the
  removed `task:progress` "Reading host" overwrite (REQ-14); the card SHALL show
  the query and a determinate/indeterminate progress derived from
  `crawler_page_fetched` counts, NOT from `task:progress` host strings.
- AC5: THE SYSTEM SHALL virtualize the wing URL list and SHALL remain usable on
  narrow/small viewports (responsive layout; list collapses to a scrollable panel).

**Edge Cases:** many URLs → virtualize list; duplicate URLs → dedupe in UI; many
tabs → tab strip scrolls; TaskListCard step removed on error/cancel.

### REQ-26: Frontend Feedback — Narration
**User Story:** As the user, I want progress speech that never overlaps the answer,
so audio feedback is coherent.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL serialize all narration utterances (step-level
  "Researching — fetched page N of M" via `narration.run_with_narration()`, and the
  final answer `speak`) through `_NARRATION_PLAYBACK_LOCK`.
- AC2: THE SYSTEM SHALL mark `crawler_query` `ToolSpec.long_running = True` so the
  generic heartbeat drives progress speech.

**Edge Cases:** narration TTS unavailable → skip speech, no crash.

### REQ-27: Success / Termination Parameters
**User Story:** As the system, I want research to always terminate, so no infinite
loops.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL consider a research batch complete WHEN it has fetched ≥
  `min_pages` (default 3) pages OR exhausted `max_pages` (default 5) OR the crawl
  subprocess timed out (default 90s), WHICHEVER occurs first.
- AC2: THE DER research loop SHALL terminate WHEN all sub-topic steps are completed
  OR the Director's cycle budget (`DER_MAX_CYCLES=40`) is reached OR the Reviewer
  reports convergence on the coverage checklist (`expected_output`/`gap_analysis`).
- AC3: THE SYSTEM SHALL NOT loop indefinitely; `work_units` from `W0` is the hard cap.

**Edge Cases:** VETO storm → `DER_MAX_CYCLES` bounds it; `work_units` hit zero →
force terminal.

### REQ-28: Layered Verification Strategy (unit / contract / integration / behavioral)
**User Story:** As the project, I want the unification verified at every layer AND
at the seams between layers, so both isolated behavior and cross-layer interaction
are proven and regressions are caught.

**Context (why layered):** The feature is a stack of SEPARATE layers — CrawlOrchestrator
funnel, event bus, DER loop, pacman store, WS/SSE transport, frontend components —
that ALSO interact. A test that only checks one layer in isolation misses seam bugs
(event emitted but not consumed; DER step returns but pacman stores wrong trust);
a test that only checks the end-to-end path misses layer-internal regressions. The
spec therefore mandates FOUR tiers, each with a defined scope, method, and proof
obligation, plus explicit CROSS-LAYER interaction tests.

**Acceptance Criteria:**

- **Tier 1 — Unit (layer-internal):** THE SYSTEM SHALL unit-test each layer in
  isolation with collaborators stubbed: `CrawlOrchestrator` funnel order (REQ-1
  AC5); `CredibilityScorer` type classification + monotonicity (REQ-5/6); passage
  rerank threshold + re-query (REQ-7); `cited_markdown` binding completeness
  (REQ-8); `FetchBackend` swap (REQ-17 AC4); heartbeat/backoff-jitter logic
  (REQ-31 AC5). Method: real module + stubbed `CrawlPlanner`/`DataExtractor`/
  fetch; assert return structures, NOT events.
- **Tier 2 — Contract (layer boundary / event contract):** THE SYSTEM SHALL
  contract-test each layer's PUBLIC CONTRACT against stubbed neighbors using the
  repo convention (real instance + stubbed collaborator + event-bus subscription
  asserting emitted events, anchored to a pin): (a) unified event-stream parity —
  WS and agent paths emit the IDENTICAL `crawler_started`→`crawler_page_fetched`→
  `open_tab`→`crawler_error` sequence for the same query (REQ-10–13); (b) DER
  `crawler_query` contract — given a web goal, the tool returns `CrawlResult` and
  the verifier consumes it via the `|u|`-band path (REQ-19/21); (c) pacman
  contract — `crawler_query` fragment lands in `reference` zone tagged
  `trust:"untrusted"` with `credibility_map` (REQ-22); (d) transport contract —
  event log replays `seq > last_seq` and SSE streams the same events (REQ-31
  AC1/AC3).
- **Tier 3 — Integration (cross-layer, in-process):** THE SYSTEM SHALL integration-
  test pairs of layers wired together WITHOUT a live network: orchestrator→event
  bus→a fake consumer asserting the wing/tab received the events (REQ-11/12);
  DER loop→`crawler_query`→pacman proving a VETO storm terminates within
  `DER_MAX_CYCLES` and persists (REQ-20/21/22/27); WS disconnect→Job Registry
  handoff→persist, NEVER cancelled (REQ-29 AC2); command-over-HTTP-POST processed
  while push down, result buffered (REQ-31 AC6/AC7). Method: in-process wiring,
  mock the fetch engine (never hit live web).
- **Tier 4 — Behavioral (end-to-end, live):** THE SYSTEM SHALL behavioral-test the
  FULL path against a running backend over the real WS/SSE transport, asserting the
  ORDERED event sequence a client receives (mirroring `scripts/ws_behavioral_test.py`):
  web OFF → no `crawler_started` on plain text; web ON → `crawler_started` → N×
  `crawler_page_fetched` (full URL) → `open_tab` → `document:render`; disconnect
  mid-crawl → reconnect → missed events replayed; new utterance during crawl →
  processed, orb reflects new state (REQ-29/30/31). Method: live connection, real
  or recorded fetch, assert event TYPE ORDER and payload invariants.
- **AC-Last:** ALL four tiers SHALL pass before crystallization; Tier 2/3/4 tests
  SHALL be anchored to a PiN recording the contract they enforce.

**Edge Cases:** flaky network → Tier 1–3 mock the fetch engine, never hit live web;
Tier 4 may use a recorded/replayed fetch; a contract test that emits an event the
consumer ignores SHALL FAIL (proves the seam, not just the emitter).

### REQ-29: Background Completion & Disconnect Tolerance (true background)
**User Story:** As the user, I want a crawl to keep running and persist its result
even if I close the window or the WS drops, AND I want to keep talking to IRIS and
work on other prompts while it researches — so web search is a true background job,
not a blocking request.

**Acceptance Criteria:**
- AC1: WHEN a `crawler_query` (agent path) is running and the WS client disconnects
  THEN THE SYSTEM SHALL let the crawl subprocess continue to completion and SHALL
  persist the `CrawlResult` to pacman (REQ-22) so the result is not lost.
- AC2: WHEN the WS `crawl_research` handler is mid-crawl and the client disconnects
  THEN THE SYSTEM SHALL NOT raise in `on_progress` AND SHALL hand the in-flight crawl
  OFF to the SAME background mechanism used by the agent path (a tracked background
  job), so the crawl ALWAYS continues to completion and persists — it SHALL NOT be
  cancelled. The handler SHALL emit no further events to the dead socket; on
  reconnect the job's events resume from current state.
- AC3: WHEN a background crawl completes with no connected client THEN THE SYSTEM
  SHALL store the result and SHALL surface it on the next client connect (e.g. via
  a pending-result queue / last-result replay), so the user sees the finished
  research and its tab on return.
- AC4: THE SYSTEM SHALL treat the crawl as a background job that does not block the
  agent's ability to handle a new user utterance; a new utterance SHALL be accepted
  and processed WHILE a crawl runs, so the user can prompt IRIS to do other work
  (answer a question, draft text, run another tool) during the research and receive
  the crawled result + tab when it finishes. The orb/ContextPill SHALL reflect the
  new utterance's state, not stay locked on "researching".
- AC5: THE SYSTEM SHALL track every background crawl as a job with a stable job id,
  so the WS path and agent path share ONE job registry and ONE completion/persist
  path (no two background implementations).

**Edge Cases:** client reconnects mid-crawl → events resume from current state, no
duplicate `crawler_started`; result ready before reconnect → replayed once; user
issues a second web search while one runs → second job tracked independently (bounded
by concurrency cap, REQ-17 AC5).

### REQ-30: UX/UI/Audio Completeness Across All Layers
**User Story:** As the user, I want every layer the search touches — audio and
visual — to behave consistently and accessibly, so the experience is coherent
end-to-end.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL cover these interaction layers for web search, with a single
  owner and consistent state per layer: Orb + XurOrb + OrbWorkingIndicator
  (`listening_state`), ContextPill (`processing_tool`), dashboard-wing URL list
  (`crawler_page_fetched`), browser tabs (`open_tab`), TaskListCard ("Researching…"
  step), RichDocument (`document:render` + citations + unverified badge),
  QuestionCard (format escalate), error toast (`crawler_error`), and TTS narration
  (`_NARRATION_PLAYBACK_LOCK`).
- AC2: THE SYSTEM SHALL ensure audio and visual feedback never contradict: WHILE
  narration speaks "Researching — fetched page N of M", the orb SHALL show
  `processing_tool` and the wing SHALL list URL N; the final answer speech SHALL
  follow only after the orb returns to idle and the document is rendered.
- AC3: THE SYSTEM SHALL respect reduced-motion / accessibility preferences: the orb
  and pill SHALL use a static or low-motion indicator during research when the user
  prefers reduced motion, and the URL list SHALL be exposed to screen readers as a
  live region.
- AC4: THE SYSTEM SHALL define the visual owner for each event in a single mapping
  table (event → component → state) so no two components invent conflicting search
  UI; this table SHALL be the source of truth for both WS and agent paths.

**Edge Cases:** component missing the mapping → falls back to the documented owner,
never renders a second conflicting indicator.

### REQ-31: Resilient Transport & Resumable Event Log (widget-safe)
**User Story:** As a widget user on a flaky connection, I want IRIS to survive
frequent WS drops and still receive every update (orb, wing URLs, tabs, document)
when it reconnects — and I want to keep sending commands while push is interrupted —
so the app feels always-on despite an unreliable socket.

**Context (why):** The browser WebSocket API does NOT auto-reconnect and the
desktop widget backgrounds/suspends often, so raw WS is not guaranteed. The
frontend is overwhelmingly server→client push (orb/pill/wing/tabs/document/TTS),
with client→server being only commands (utterance, set_web_mode). That profile
favors a **resumable server-side event log + SSE fallback** over "just fix WS".

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL buffer every emitted event per session in a durable,
  sequence-numbered event log (TTL-bounded) so no event is lost when the socket
  drops; each event SHALL carry a monotonic `seq` and the session id.
- AC2: THE SYSTEM SHALL assign the client a `last_seq` it acknowledges; on
  reconnect the client SHALL send `last_seq` and THE SYSTEM SHALL replay all events
  with `seq > last_seq` (deduped), so the widget receives exactly the updates it
  missed (orb state, `crawler_page_fetched` URLs, `open_tab`, `document:render`).
- AC3: THE SYSTEM SHALL provide an SSE endpoint (`text/event-stream`) that streams
  the SAME unified events (REQ-10–13) for pure server→client push, using native
  `EventSource` auto-reconnect with `Last-Event-ID`; this is the resilient fallback
  for the widget's push channel.
- AC4: THE SYSTEM SHALL keep the WebSocket for the bidirectional command channel
  (client→server utterances/commands + server→client push when connected) but SHALL
  treat SSE as the authoritative resumable push source; both read from the SAME
  event log (REQ-31 AC1).
- AC5: THE SYSTEM SHALL implement WS client heartbeat (ping/pong) + exponential
  backoff with FULL JITTER on reconnect, so half-open connections are detected and
  reconnect storms are avoided.
- AC6: THE SYSTEM SHALL accept client→server commands (new utterance, set_web_mode)
  over HTTP POST (and over WS when up) INDEPENDENTLY of the push channel, so the
  user can keep talking to IRIS and issue prompts even while the push socket is
  down; commands SHALL be processed and their resulting events buffered in the log
  for replay.
- AC7: WHEN the push channel is down, THE SYSTEM SHALL NOT block background crawls
  (REQ-29) or command processing; the crawl job continues server-side and its
  events wait in the log for replay on reconnect.

**Edge Cases:** widget suspends mid-crawl → on wake, SSE/WS reconnect replays
missed `crawler_page_fetched`/`open_tab`/`document:render`; command sent while push
down → processed, result buffered, replayed; event log TTL evicts very old events →
client receives a `sync_required` marker and fetches a full state snapshot instead
of a partial replay.

---

## Non-Requirements (Out of Scope)

- Changing `ExecutionMode` semantics — it remains display-only.
- A separate web verifier module — verification reuses the `|u|`-band path.
- Re-implementing the DER research loop inside `CrawlerOrchestrator` — the loop is
  emergent from `_split_step` (`u/ξ`).
- Cross-encoder reranker model selection (local Ollama vs hosted) — deferred to
  implementation; interface only is specified here.
- Citation hover-preview in the wing (Perplexity-style) — v2 nice-to-have.
- Changes to `CrawlPlanner` / `DataExtractor` LLM prompts beyond the citation
  binding requirement (REQ-8).
- Modifying non-search `task:progress` consumers.

---

## REQ-32: Per-Thread Conversation Scoping (no cross-thread context bleed)

**Problem observed:** the agent referenced a *previous* web-search result inside a
*new* conversation thread. Conversation threading exists at the routing layer
(`POST /api/chat` accepts `thread_id`; `get_agent_kernel(conversation_id=thread_id)`
returns one kernel per thread), but context still leaks across threads because
(a) web-search findings are persisted to **global** memory (Mycelium semantic/episodic
store + the `reference`-zone credibility map / citation index) and are retrieved into
the prompt regardless of thread, and (b) `activeConversationId` is restored from
`localStorage` across sessions, so a stale thread id can be reused for a new session's
first message.

### Requirements

- **REQ-32.1 (scope):** The agent MUST respond using ONLY the active conversation
  thread's own context (messages + thread-local memory). It MUST NOT surface content
  from a different thread unless the user explicitly asks (e.g. "what did we find in
  the other thread?" / "summarise my previous research").
- **REQ-32.2 (memory isolation):** Web-search results, citations, and credibility maps
  written by a crawl MUST be tagged with the originating `thread_id` and MUST NOT be
  retrieved into the prompt of a different thread by default. Cross-thread retrieval is
  opt-in only.
- **REQ-32.3 (fresh session):** Starting a new chat (or a new session) MUST create a
  NEW thread id; a previously persisted `activeConversationId` from another session
  MUST NOT be auto-reused as the active thread for a new session.
- **REQ-32.4 (explicit override):** When the user references another thread or asks the
  agent to recall prior research, the agent MAY cross-reference, but this is an explicit
  user-initiated action, not default behavior.

### Acceptance Criteria

- AC1: Send a web-search request in thread A; open a NEW thread B and ask a generic
  question → the agent's response contains NO findings from thread A's search.
- AC2: Inspect the prompt/context assembled for thread B → it contains only thread B's
  messages + thread-B-local memory; no `reference`-zone credibility map from thread A.
- AC3: Reload the app / start a new session → the first message lands in a freshly
  generated thread id, not a restored stale thread.
- AC4: Explicit "what did we find earlier?" → agent may retrieve across threads (opt-in).

### Anti-requirements

- Do NOT make the agent kernel a global singleton that shares `ConversationMemory`
  across threads (already avoided: kernel is keyed by `conversation_id`).
- Do NOT retrieve global Mycelium memory into a thread's prompt without the
  `thread_id` tag filter.

---

## Open Questions (for implementation session, not blocking)

1. Cross-encoder reranker: local model (Ollama) or lightweight hosted? Latency
   budget per batch is the constraint.
2. Should `crawler_query` Sub-Loop children be auto-`parallel_safe`, or should the
   Director decide per sub-topic? (Recommend: Director decides; default
   conservative.)
3. Citation hover-preview in the wing — v2.
4. **Resolved (transport):** raw WebSocket is not guaranteed for the widget; adopt
   a resumable server-side event log + SSE fallback (REQ-31). Remaining choice:
   **where does the event log live?** Options: (a) the existing MCM/SQLite store
   (already WAL, project-local, safe for concurrent processes — lowest new
   infra), (b) an in-memory ring per session (simplest, lost on backend restart),
   (c) Redis-style stream (most scalable, new dependency). Recommend (a) reusing
   MCM/SQLite with a TTL-indexed events table, since the project already depends on
   it and it survives backend restart.

# Requirements: Research Memory, the Immortus Time Layer, Autonomous Browser (rev 1, 2026-09-30)

## Owner goals (2026-09-30, session 64237209)

1. After a search the user (and the agent) cannot reach earlier summaries. A new search that is
   semantically close to an earlier one must BUILD ON it: compare and contrast, confirm or
   contradict, not start from zero. "All the ingredients are there."
2. Connect the Immortus chain (`memory_chain`) properly: it is the 4D TIME layer of memory that
   organizes memory and gives the agent statefulness.
3. One browser if the memory concern is solved (the owner's concern: CPU/memory bloat). The agent
   must explore ALL pages of an address that are relevant to the search or browser task.
4. No permission prompts during active browser use. A click-safety filter (the Oracle, in context)
   decides; the agent escalates to the user ONLY when unsure; if the user does not answer in time,
   the agent pivots to another way to complete the task.

## Measured facts (2026-09-30; file:line as of commit 727a7b44 - RE-VERIFY before editing)

- **F1 Research results scatter and expire.** The job registry keeps a result 600 s in memory
  (`backend/crawler/job_registry.py:63-125`). The dashboard summary (DataExtractor output) is only
  an `OPEN_TAB` event (`orchestrator.py` `_emit_dashboard`); on the agent path it lands later on
  lane `web_extract` (`_submit_deferred_extract`) and is stored NOWHERE. Mycelium keeps raw web
  fragments in zone `reference` (`pacman_fragment.py` `_EXTERNAL_TOOLS`), not the summary.
- **F2 Semantic recall exists and filters.** `EpisodicStore.retrieve_context_chunks(query,
  chunk_types=[...], zones=[...], limit, min_similarity)` (`backend/memory/episodic.py:890`):
  cosine 80 % + recency 20 %, newest 200 candidate rows. It returns content strings only.
  `fragment_and_store(content, session_id, chunk_type, zone, tool_name)` embeds on CPU (~5 s per
  1 KB chunk) - it must never run on the answer path.
- **F3 No prior-research lookup.** `_mem_lookup` (`agent_kernel.py` ~15886-16000) and the search
  executors never consult earlier research. No history UI; no list endpoint (only
  `GET /api/crawl/result/{job_id}`, `backend/api/crawl_stream.py:115-132`).
- **F4 Cross-source agreement is one-sided.** `credibility._apply_corroboration` boosts claims seen
  in >= 2 sources; nothing records contradiction, and nothing compares against earlier research.
- **F5 The chain is written but barely read.** 3,902 rows; 1,737 carry numeric coordinates
  (`step_*` rows from the DER fold, `document_render` rows). Readers: `filtered_chain_recall`
  (topic/domain filters + recency, limit 3, per DER step at `agent_kernel.py:10048` via
  `_der_recall_neighborhood` ~6810; and `semantic_gate.py:646`). Coordinate recall
  (`immortus_chain_query_by_coordinate`, `caducean_recall` `semantic_gate.py:893`,
  `retrieve_documents_by_trajectory`) has NO production caller. `created_at` is used only as a
  recency sort. No reader gives the planner "what happened so far in this task".
- **F6 Pseudo coordinates.** `backend/api/chat.py` ~165 writes `rest:input:<turn>` (165 rows);
  `backend/agent/mcm.py` ~132 writes Python lists. 260 step rows have `coords_from =
  0.00,0.00,0.00,0.00` (no prior coordinate) and 175 document rows have `coords_from = ''`.
- **F7 The coordinate is low-information because its INPUTS are constant (not by design).**
  `Caducean::update` (`src-tauri/src/iris_core/caducean.cpp:73`): action 0 -> x+=1, u+=s*cos(xi);
  any other action -> y+=1, u-=s*sin(xi); xi += balance*s*c_eff. The kernel
  (`agent_kernel._der_physics_step` ~17724) sends action 1 only for run_command/git_commit/git_push
  and 2 for a failure: 1,137 of 1,168 steps were EXPAND, including edits, tests and syntheses. With
  y = 0 the native EML (`iris_core.cpp:162`) is ~12.5 (-log(1e-5) alone is 11.5), the kernel clamps
  balance to 3.0, so xi advances 3.0*0.35*1.0 = 1.05 every step and u follows cos(xi): Sigma is a
  step counter, and every one-step task ends at (1, 0, 1.05, 0.35). The owner: coordinates are NOT
  supposed to be meaningless -> REQ-8.
- **F8 Three Chromium launch sites.** `crawler_engine.py:320` (crawl4ai, inside the crawl
  subprocess), `browser_pool.py:346` (shared pool, bound to the loop that started it),
  `browser_tools.py:125` (browser tools; private Chromium on a dedicated loop thread, because each
  tool call runs on a fresh loop and a Playwright object only works on its own loop). No renderer
  or JS heap limits on either launch.
- **F9 Consent.** `tool_bridge.py` ~1729-1790: `classify_tool` reads the registry tier;
  `get_permission_action` (`permissions.py` ~526) asks for `side_effect` tools unless the
  auto-approve toggle is on. `browser_act` is `side_effect`, so every click asks.
  `ask_user_tool.py`: QUESTION_ASK with a 120 s timeout; a timeout returns no answer.
- **F10 Crawls are one hop.** No same-site follow-up; outlinks are only listed (tool_bridge
  "--- Outlinks (uncrawled candidates)", no relevance score, no same-origin gate).

## Requirements (EARS)

### REQ-1 Research memory: every research result is kept
- AC1.1 WHEN a research result lands (agent path deferred extraction, gateway path, and the
  `search` quick tier) THE system SHALL store ONE research record: query, summary, claims (each
  with its source URLs), sources, created_at, conversation_id, job_id.
- AC1.2 The record SHALL be stored in `document_data` (fmt `research`), SHALL get an Immortus
  chain REFERENCE row (`nbl_outcome='research'`, real coordinates, topic_domain), and SHALL be
  embedded for semantic recall (chunk_type `research_summary`, zone `reference`) - all off the
  answer path.
- AC1.3 The job registry result SHALL carry the summary once the extraction lands (A5 left it
  empty on the agent path).

### REQ-2 Research builds on research
- AC2.1 WHEN the agent runs `search` or `crawler_query` THE system SHALL look up prior research
  records semantically close to the query (cross-conversation), CONCURRENTLY with the web call -
  the lookup adds no wall time when the web call is slower.
- AC2.2 The tool result SHALL carry a bounded PRIOR RESEARCH section (date, query, summary, top
  claims with sources) when a close record exists.
- AC2.3 THE system SHALL cross-check prior claims against the new evidence and label each:
  `confirmed` (supported again), `changed` (same subject, different number/date/name),
  `not_rechecked` (no new evidence either way); new claims are `new`. The synthesis SHALL state
  confirmations and changes with both dates.
- AC2.4 The agent SHALL have a read-only `recall_research` tool (by query or document_id). It is a
  store read: never captured as a new document (Standard S11).

### REQ-3 The user can reach earlier research
- AC3.1 `GET /api/research/history` SHALL list research records (metadata only; optional
  `conversation_id`, `q` semantic filter) and `GET /api/research/{document_id}` SHALL return one.
- AC3.2 The dashboard tab SHALL show a history list; opening an entry renders its stored
  dashboard with the existing dashboard renderer (no new renderer).

### REQ-4 The Immortus chain is the time layer - consulted, never dumped
Owner rule (2026-09-30): chain data enters the agent's context ONLY when it is relevant to the
current task. No per-turn or per-step injection (context debt).
- AC4.1 Every chain writer SHALL write a real coordinate (from the trajectory recorder) or NULL -
  never a pseudo value, a list, or `0,0,0,0` as a stand-in for "unknown".
- AC4.2 THE existing per-step "RELEVANT NEIGHBORS" injection (`_der_recall_neighborhood`) SHALL
  inject a row only when it passes a relevance bar (same topic AND text similarity to the current
  step goal above a threshold, then ranked by state proximity and recency); when no row passes,
  NOTHING is injected. Measured: rows injected per step before/after.
- AC4.3 THE chain SHALL be consulted at DECISION points where it changes the decision: (a) a
  replan after a failure gets this task's own timeline (what was tried, in order) and the
  mediators tried near the current state (`immortus_chain_query_mediators`); (b) a web goal gets
  prior research (REQ-2, similarity-gated). Nowhere else.
- AC4.4 Coordinate recall SHALL have a production caller (AC4.2/AC4.3) and SHALL be measured
  (rows returned per decision, ms per query).

### REQ-5 One browser, bounded memory
- AC5.1 In the backend process ONE Chromium SHALL serve both the crawl pool and agent browser
  sessions, hosted on ONE dedicated event-loop thread; each conversation gets its own
  BrowserContext (bounded, LRU, idle-closed).
- AC5.2 The launch SHALL bound memory: renderer process limit, JS heap limit, no GPU; heavy
  resources (media, fonts) blocked for crawl contexts; the browser stops when idle.
- AC5.3 A measured before/after: peak working set of Chromium processes for (a) one crawl + one
  session, (b) idle.

### REQ-6 Explore every relevant page of an address
- AC6.1 WHEN a crawled page is relevant but insufficient THE crawl SHALL follow SAME-SITE links
  ranked by relevance to the goal (anchor text + URL tokens + goal terms), bounded (pages, depth,
  time).
- AC6.2 A `browser_explore(goal)` capability SHALL visit the relevant same-site links of the
  session's current address and return what each page adds, bounded.

### REQ-7 Autonomous browser actions with a click-safety gate
- AC7.1 `browser_open`, `browser_observe`, `browser_act` SHALL never raise the generic permission
  prompt.
- AC7.2 EVERY `browser_act` SHALL pass a click-safety gate in context (task goal, element role,
  name, href, form fields, page URL): `safe` -> act; `unsafe` -> refuse with a reason;
  `unsure` -> escalate.
- AC7.3 Escalation SHALL ask the user ONE question (what, where, why) with a bounded timeout. On
  "yes" -> act; on "no" or timeout -> the tool returns `ok=false` with `pivot=true` and a reason,
  and the agent chooses another way (no retry of the same element).
- AC7.4 The Oracle SHALL have a `click_safety` consumer in SHADOW with a reference label from the
  active gate, so it can earn the decision later (CLAUDE.md "THE ORACLE EARNS ITS JOBS").

### REQ-8 A meaningful coordinate (PENDING OWNER DECISION on the action mapping)
- AC8.1 The action sent to the physics SHALL reflect what the step did: EXPAND for gathering and
  exploring (search, crawl, read, browse, list, recall), COMPRESS for consolidating (synthesis,
  verification, tests, edits/writes, commits, summaries). A failure SHALL NOT be counted as
  compression; it feeds u (attention) through the outcome instead.
- AC8.2 The balance SHALL NOT sit at its clamp: two sessions with different expand/compress mixes
  SHALL reach different xi. Measured on the eval groups: distinct Sigma per task, share of steps
  at the clamp (target: not 100 %).
- AC8.3 Behavior guard: the recommend() mix (EXPAND/COMPRESS/CONTINUE/TOPO_VIOLATION) and the
  coding/research eval pass rates SHALL be measured before/after; a regression blocks the change.


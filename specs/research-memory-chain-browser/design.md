# Design: Research Memory, the Immortus Time Layer, Autonomous Browser (rev 1, 2026-09-30)

Read `requirements.md` first. Line numbers are from commit 727a7b44; RE-VERIFY before editing.
Rules that bind every decision: CLAUDE.md "ANSWER PATH vs SIDE LANES" (anything the reply does not
need goes on `durability_queue.lane(name)`), "ONE CHOKEPOINT", "THE ORACLE EARNS ITS JOBS",
Standards S1-S12 in `docs/audits/2026-09-29/PROGRESS.md`.

## Shape

```
web goal ─> search / crawler_query ───────────────┐       (answer path)
     └──> recall_prior_research(query)  (concurrent, bounded 3 s)
                                                    ├─> cross_check(prior, new) -> PRIOR + CROSS-CHECK sections
result lands (quick tier now / crawl extraction on lane web_extract)
     └──> lane("research_memory"): record_research(...)  -> document_data(fmt=research)
                                                        -> Immortus chain reference row
                                                        -> fragment_and_store(research_summary, reference)
DER step recall ─> filtered_chain_recall (meaning) ∪ coordinate neighbours (state) -> rank(time) -> NEIGHBORS
replan/continue  ─> chain timeline of this thread (time order, last N)
browser_* ─> BrowserHost (one loop thread, one Chromium, context per conversation)
browser_act ─> ClickSafety(rules -> Brain judge if unsure) ─> act | refuse | ask user (timeout -> pivot)
                                   └──> Oracle click_safety shadow row (reference label = gate verdict)
```

## D1 One module owns research memory: `backend/agent/research_memory.py`
Functions (no class hierarchy, no registry - one implementer):
- `record_research(record: dict) -> None` - SUBMITS to `lane("research_memory")`; the lane job
  writes the three homes (REQ-1 AC1.2). The document_data row reuses `DocumentDataStore.store`
  (fmt `research`, content = JSON record). The chain row is a reference (same shape as the S12
  document row: id, format, chars, head) with `nbl_outcome='research'`. The fragment text is
  `"[research <iso-date> doc=<id>] Q: <query>\n<summary>\n- <claim> (<host>)..."` so the returned
  string carries its own id and date (F2: recall returns strings only). Header parse is one regex.
- `recall_prior_research(query, *, limit=3, min_similarity=0.55, exclude_job_id=None) -> list[dict]`
  - `retrieve_context_chunks(query, chunk_types=["research_summary"], zones=["reference"])`, parse
  headers, load the records by id (document_data), dedupe per record. Sync; callers run it in a
  thread with a 3 s bound (a timeout degrades to "no prior", never cancels a write).
- `cross_check(prior_records, new_passages_or_text) -> list[dict]` - deterministic: for each prior
  claim, find the best new passage by token overlap (reuse `crawler.cite._best_match`/`_tok`);
  `confirmed` when overlap is high and the claim's numbers/dates all appear; `changed` when the
  subject tokens match but a number/date differs; else `not_rechecked`. New claims come from the
  new summary when present, else nothing (no LLM call on the answer path).
- `format_prior_section(records, checks) -> str` - bounded (<= 1,500 chars).
Callers: the deferred-extraction job and the synchronous path in `orchestrator.py` (after
`_emit_dashboard`), the quick-tier `search` executor in `tool_bridge.py` (its result already has
per-source text), and `_execute_crawler_query` / the search executor for the concurrent lookup.
The registry update (AC1.3) happens in the same landing callback: the orchestrator gets an
optional `on_dashboard(dashboard_data)` callback from tool_bridge, called on the caller's loop
after `_emit_dashboard` (deferred and sync paths alike).

## D2 The synthesis uses it without a new model call
The PRIOR + CROSS-CHECK sections ride in the tool result `content` (the field the agent reads).
One line is added to the synthesis instruction where web results are synthesized: "If a CROSS-CHECK
section is present, say which facts are confirmed since <date> and which changed." No extra Brain
pass. `recall_research` is a `read_only` ToolSpec added to `_DER_READ_TOOLS` (S11).

## D3 History for the user
`backend/api/research.py` (router mounted where `crawl_stream` is): `GET /api/research/history`
(metadata: id, query, created_at, conversation_id, source count; `q` -> `recall_prior_research`),
`GET /api/research/{id}` (the record + its dashboard payload). Frontend: a small history list in
the existing dashboard tab (hooks/useCrawl.ts owns the dashboard state); opening an entry sets
`dashboard` to the stored payload - the existing renderer draws it.

## D4 The chain: consulted at decisions, gated by relevance (Immortus)
- Writers (AC4.1): `api/chat.py` and `agent/mcm.py` get the coordinate from
  `get_trajectory_recorder(mi).get_latest_coordinate(session_id)` and pass `format_coords(...)`
  or None. The DER step fold passes None for coords_from when there is no prior coordinate.
- Relevance gate (AC4.2) at `_der_recall_neighborhood`: `run_filtered_recall` stays the topic
  filter; each candidate must ALSO clear a text-similarity bar against the step goal (token
  overlap on insight/result head - no embedding on the step path); survivors are ranked by state
  proximity then recency; empty -> no block at all. Log `[chain_recall] cand=<n> kept=<k> ms=<t>`.
- Decision points (AC4.3): the replan-after-failure context gets `chain_timeline(thread_id, 8)`
  (this task only, time order) and the mediators tried near Sigma_now. Web goals: REQ-2.
- REQ-8 (meaningful Sigma) is a physics INPUT change in `_der_physics_step` (action from the
  step's tool/node kind) - waits for the owner's decision; state proximity only becomes useful
  after it.

## D5 BrowserHost: one Chromium on one loop
Promote the browser tools' private runtime (`_BrowserRuntime`, browser_tools.py ~75-110: a daemon
thread running its own loop; `run(coro, timeout)` = `run_coroutine_threadsafe`) to
`backend/vision/browser_host.py`, and make `browser_pool` launch and hand out its browser THROUGH
the host: every coroutine that touches a Playwright object runs on the host loop
(`await host.call(coro_fn, *args)` wraps `asyncio.wrap_future(run_coroutine_threadsafe(...))`).
Crawl entry points that use the pool (fetch.vision / Tier-2 in-process fetch, orchestrator
prewarm) hand their whole page coroutine to the host. The crawl4ai subprocess (F8, crash
isolation for crawls in agent mode) stays as is and is out of scope.
Memory bounds (AC5.2) in the one launch: `--renderer-process-limit=4`,
`--js-flags=--max-old-space-size=256`, `--disable-gpu`, `--disable-dev-shm-usage`,
`--disable-extensions`; crawl contexts route-abort `media` and `font`; sessions max 2 contexts
(LRU), idle 300 s; browser idle stop 180 s (existing). Measure with the Chromium process tree's
working set (psutil) before/after.
If a design detail here is unreachable without an over-build, STOP and report (CLAUDE.md).

## D6 Exploration
- Crawl (AC6.1): in the orchestrator, after rerank, when kept passages are below the sufficiency
  bar for a host that produced relevant passages, collect that host's same-origin links from the
  fetched pages, score them `goal-token overlap(anchor text + URL path)`, fetch the top 4 through
  the same Tier-1 fetch (one hop, depth 1, 15 s budget), and rerank again. Reuse the outlink
  extraction regexes now in tool_bridge (move them to a crawler helper used by both).
- Browser (AC6.2): `browser_explore(goal, max_pages=5)` on the host: from the session's current
  page, rank same-origin links from `observe()` marks the same way, visit each in the same context
  (new page, closed after), return per page: url, title, top passage (<= 400 chars). Bounded 30 s.

## D7 ClickSafety and consent
- ToolSpec gains `self_gated: bool = False`; the consent gate in `tool_bridge` (~1729) skips the
  generic prompt when the spec is self-gated. `browser_open/observe/act/explore` are self-gated.
  (One field, one check - the honest statement that the tool enforces its own consent.)
- `backend/agent/tools/click_safety.py`: `assess(goal, mark, page_url, form_fields) -> (verdict,
  reason)`. Rules first: UNSAFE = purchase/pay/checkout/place order/subscribe/delete/remove/
  cancel account/send/post/publish/submit a form with password, payment or personal fields,
  file downloads/executables, OAuth/permission grants. SAFE = links and buttons that navigate,
  expand, paginate, sort, filter, switch tabs, open search, type into search boxes, dismiss or
  DECLINE cookie banners. Otherwise UNSURE -> Brain judge (one short `InferenceRouter.generate`
  call, light path, tools off, JSON verdict) -> still unsure -> escalate.
- Escalate via `ask_user_tool` QUESTION_ASK with timeout 45 s; timeout/no -> `{ok: false, pivot:
  true, reason}`; the session remembers refused marks for the rest of the task.
- Oracle: a `click_safety_shadow` row module wired like `monitor_shadow` (`set_row_sink`, wired
  at `agent_kernel.py` ~967-972), one row per assessment with the gate verdict as reference label.

## D8 Memory that builds shape (owner 2026-09-30: beyond recall; the Oracle, not RAG)

Measured state (2026-09-30): 30 active landmarks, all `task_class='bootstrap'` (build-time), empty
`traversal_sequence`; 6,256 landmark edges, all `similarity` at 0.4; 872 `mycelium_traversals` and
887 `mycelium_plan_stats` rows recorded at runtime but never folded into shape. The chain holds
~1,700 transitions with (after REQ-8) meaningful Sigma. The ingredients exist; nothing connects them.

The model: memory is a MAP with a CLOCK, not a pile of text.
- Chain = the clock: ordered transitions (Sigma_from -> Sigma_to, what was done, outcome).
- Sigma = the phase of work (how much gathered vs consolidated, where in the cycle, attention).
- Landmarks = places that recur: a crystallized ROUTE (sequence of step kinds + Sigma path +
  outcome), not a document.
- Edges = roads between places, TYPED (precedes, same_shape_other_domain, supersedes,
  contradicts), each with hit/miss counts.
- Oracle = the router: it decides WHETHER memory is needed and WHICH structure answers it, then a
  structured query answers - never "top-k similar text into the prompt".

Five mechanisms, in build order (each shadow-first where it steers anything):
1. M1 Memory router (Oracle consumer `memory_need`, SHADOW): options `none | prior_facts |
   procedure | what_failed_here | user_preference | continuity`, frame = step goal. The active
   decision stays the relevance gate (K2/REQ-2) until the bar; the Brain labels a sample for
   calibration. Only a non-`none` answer opens the matching lens. This is the owner's
   "no context debt" rule made a learnable decision.
2. M2 Belief timeline (research): every research claim becomes a belief with a history of
   observations (date, source, value) on the chain; the Oracle types the relation of a new
   observation to the belief (`claim_relation`: supports | updates | contradicts | unrelated,
   SHADOW; the deterministic cross_check (R3) is the active label). A belief's observed
   volatility sets its recheck need: stable facts can be answered from memory with their date,
   volatile ones are re-searched. The dashboard shows how a fact changed.
3. M3 Routes (procedural memory): a consolidation job folds finished tasks' chain segments into
   landmark routes (step kinds + Sigma path + outcome), merging near-identical routes. At plan
   time, when the live task's opening matches a route (shape match on Sigma path + step kinds, then
   Oracle `route_match` SHADOW), the planner gets ONE line: the route's next step and its known
   pitfall. Measure: steps-to-success and failure rate on repeated task classes, before/after.
4. M4 Divergence: when the live Sigma path leaves the matched route (e.g. gathering far past the
   route's usual consolidation point), raise it at the next decision point (a streak-gate input) -
   earlier than the TOPO check.
5. M5 Cross-domain shape: routes with the same Sigma-path shape in different topic domains get a
   `same_shape_other_domain` edge; a proven procedure is offered across domains only when M3's
   match holds and the Oracle agrees (SHADOW until the bar). This is where coordinates carry value
   that text similarity cannot: shape is domain-independent.
Consolidation (M2 folding, M3 routes, M5 edges, decay of unused edges) runs on an idle lane
("sleep"), never on the answer path; it extends the existing DistillationProcess cycle.

## D9 Typed events and the landmark policy (owner 2026-09-30; brief `docs/Design/CLM_MYCELIUM_DESIGN_BRIEF.md` 7.9, 7.11)

Measured state: the app records ONE event type (`system_events.tool_execution`, 5,653 rows); step
verification exists (`der_commits.verified_label`: VERIFIED 1,060 / UNVERIFIED 83 / FAILED 20) but
feeds nothing; landmarks crystallize at episode end from the run score (>= 0.45, not "miss"),
cluster = the 6 most-used Mycelium nodes of ALL spaces (not this session's), permanence = 8
activations (usage, not truth); no evidence types, no dependencies, no staleness, no demotion.

Events (one module `backend/memory/memory_events.py`, written on `durability_queue.lane("memory_events")`,
never on the answer path; each event is a chain row - the time layer - `nbl_outcome='event:<TYPE>'`,
`file_path=<case_id>`, compact JSON `result`, real Sigma):
- BUG: a step failed (success False or verified FAILED) -> open or reuse the CASE keyed by the error
  signature (`sha1(tool + normalized first error line)[:12]`; digits, paths, hex, quotes stripped).
- ATTEMPT: an UNVERIFIED step while a case of this task is open.
- DEAD_END: a failed step while a case of this task is open (a negative marker; the action
  signature `tool + target` is stored so a repeat can be counted).
- FIX: a VERIFIED step after a BUG in the same task (the step the verifier touched - event-level
  credit, never the whole run).
- VERIFIED_FIX: outside evidence for a FIX: the task completes successfully, or a later test
  command passes, or the user confirms. Only these deposit trail strength. The model's claim never.
- LESSON: the FIX step's own description, model-authored, stored as a CANDIDATE with provenance
  (case id, chain row, Sigma); it never promotes itself and re-enters context as data.
Cases (`memory_cases`: case_id, signature, tool, status open|fixed|verified|stale|demoted,
depends_on JSON (files/commands/urls the fix touched), falsify_if, attempts, dead_ends,
verified_count, last_verified, contradictions, first_seen, last_seen). A later edit of a dependency
marks the case STALE; a BUG with the same signature after VERIFIED_FIX is a CONTRADICTION ->
`demoted`, history kept.

Landmark policy (`mycelium_landmarks` gains tier, evidence JSON, depends_on JSON, falsify_if,
last_verified, contradictions; idempotent ALTER like the memory_chain migration):
- Tiers: candidate -> landmark -> stale | demoted. A crystallized landmark starts as CANDIDATE.
- Promotion needs OUTSIDE evidence of >= 2 kinds or sessions among: task_complete (episode success),
  test_pass (a VERIFIED test command in the session), user_confirm, recurrence (a merge with an
  independent session's landmark). The model's claim never counts. The threshold is a constant to
  be set from the brief's section 9 measurements, starting at 2.
- Event-level credit: the landmark's traversal_sequence records the VERIFIED step events of the
  session (chain row ids), not the whole run.
- Truth vs usefulness stay separate numbers: tier/evidence = truth; activation_count = recall
  usefulness. `is_permanent` requires tier == landmark AND the activation threshold.
- Falsification: depends_on from the verified events (files, commands, urls) + falsify_if text;
  a dependency edit -> stale (re-check on next use, flagged when shown); a contradicting failure ->
  demoted (kept).
Trail surfacing (7.11, relevance by construction - owner rule): ONLY at a replan after a failure,
when the live BUG signature matches a case: one block (<= 400 chars) with the fix, times verified,
last verified, dependency status, dead ends to avoid. Counters logged for the section 9 tests:
promoted, demoted, stale_used, repeated_dead_end.

# Requirements: Tool-Result Envelope & Drift-Gated Coordination

## Decisions Locked
- (User, session-312 close) The agent must NEVER repeat a step/tool call without knowing it, absent genuine failure or misaligned results. (carried from pin_ac112bbf6295)
- (User, session-312 close) Raw pages/tool payloads must NEVER enter the context window — digests only; raw lives at the durable store.
- (User, this spec) Render-time caps and text-zone pruning (prior "D1–D5" proposal) are REJECTED as surface-level. The fix is at WRITE TIME: wrap every tool result in an envelope before it re-enters the loop.
- (User, this spec, amended session-316) The envelope carries a DECISION WRAPPER in words, not physics units — `status / match / novelty / suggestion` — plus the raw `coords_from → coords_to` pair passed through VERBATIM for future wormhole hashing. The Director reasons over sentences ("repeat of Step 1 — read it instead of re-fetching"), never over vector norms. The 4D phase-space `coordinate_delta` formulation is REJECTED (user-locked: numbers the decider cannot feel are decoration).
- (User, this spec, amended session-316) `semantic_fingerprint` is CUT entirely — no field, no per-step encode, no counters. Semantic ranking of past findings (ex-OQ-3) belongs to `specs/wormhole-aperture/` (wormhole Tier-1/Tier-2 recall), not to the reporter. The envelope keeps recency order + `raw_ref` pointers.
- (User, this spec) Role-differentiated views over the same graph node: Executor reads `raw_ref`; Reviewer reads `status` + wrapper + summary; Director reads `summary` + wrapper ONLY — the Director never pays context cost for raw tool output.
- (User, this spec, amended session-316) Hierarchy C (locked): WALLED/permanent-failure and CIRCLING are HARD rules — a repeat is never re-executed (resolve via `raw_ref`), a walled tool is never retried in-run. Mismatch / empty / transient-failure / idling are STRONG SUGGESTIONS the Director may override with a logged reason.
- (User, this spec, amended session-316) Prevention owns the decision, envelope owns the evidence: the pre-dispatch guard (gather gate + turn URL memory) blocks repeats before a tool call is paid for; the envelope labels what happened — INCLUDING failures, which ARE written to working memory — so a slip-through is undeniable.
- (User, this spec, amended session-316) Expectation is per-tool-family and weighted: every envelope judges its step against that family's bar (gather: got-what-was-asked + sources; read: ref resolved; synthesis: covers prior summaries, no raw dump; action: side effect confirmed) and carries CRITICALITY — load-bearing / supporting / cosmetic, planner-DECLARED at plan time and consumption-CONFIRMED at finalize (option C, locked: declaration sets intent, consumption proves it). The run reports `done + grade`: a load-bearing mismatch caps the run below full pass no matter how green the rest is.
- (User, this spec) Replanning is gated on a stuck-streak over wrapper labels (consecutive repeats / empties / mismatches, idling streak), reusing the existing TOPO_VIOLATION-style physics detection as an override — NOT called every loop iteration.
- (User, this spec, amended session-316) Aperture compatibility (reporter-only contract): the envelope NEVER mints hashes, NEVER walks the graph, NEVER scores recall. It stamps `doc_id + card_id + step_id + session/turn + coords pair verbatim + wrapper + criticality` so wormhole/aperture land later with zero rework.
- (User, this spec) "Update plan" trigger question resolved: conditional on stuck-streak, never unconditional per-iteration.
- (User, session-318) The visited-URL ledger rides prompts as POINTERS, never payloads — URLs, doc_ids, step ids may enter prompts; page bodies never do. The session-312 "digests only" lock is preserved: a ledger of addresses is the same class of thing as the `raw_ref` doc_ids already on every envelope.
- (User, session-318) Never-recrawl is per-URL HARD, with a VLM recovery-lane caveat: re-fetching the SAME address in-turn is never re-dispatched — but a VLM-led in-site recovery MAY navigate to UNVISITED pages under the same site (e.g. a 404 whose siblings hold the answer). The ban is on addresses, not on sites. Recovery is its own step with its own envelope (`recovery_of` = parent step), its own page+depth budget and deadline; an empty-handed return settles honestly and streak-counts.
- (User, session-318) The brain never blocks on the VLM/recovery lane: recovery runs async beside the main plan (it is one lane of websearch, not a pause button). Dependent steps wait bounded by the recovery deadline; independent steps proceed. The recovery envelope joins the same ledger on return.
- (User, session-318) Content identity is EXACT-match stdlib hashing of normalized extracted text — a barcode scanner, not face recognition. The session-316 fingerprint CUT stands: no vectors, no encodes, no similarity ranking (ranking still belongs to `specs/wormhole-aperture/`).
- (User, session-318) Every tool execution carries a deadline plus a progress heartbeat. Expiry settles the step as `status`=timeout (honest, streak-counted) — never a silent kill, never an infinite wait.
- (User, session-319) The recovery trigger is NOT a cost/benefit trade-off. The session-318 lock already says the brain never waits on the VLM lane; therefore firing recovery on ANY dead address costs the main plan nothing. The trigger is `at least one dead address in the step`, NOT `the step returned zero sources` — the zero-sources gate was an implementation reading that made the lane unreachable for the exact failure it exists to fix (a blocker inside an otherwise-successful crawl).
- (User, session-319) The recovery lane must be GENUINELY concurrent, not a serial queue insertion. session-318 AC9.6 promised "the brain never blocks on it"; a `queue.add_item` recovery step is ordering, not concurrency, and consumes turn time and context. Trigger and concurrency move together — widening the trigger without real concurrency would manufacture the latency cost the lock forbids.
- (User, session-319) Recovery depth is AGENT-DETERMINED, not a fixed page count. The lane continues while the parent step's information need is unmet (envelope `match` ≠ matched) and its deadline has not expired. A 25-page ceiling exists ONLY as a runaway safety net; it is not the operating limit. The previous 5-page cap and the `RECOVERY_DEPTH=2` constant (defined and consumed nowhere) are retired.
- (User, session-319) Deadlines cover the FINAL SYNTHESIS call, not just tool paths. REQ-11's "every wait on a tool path" left the largest and slowest call of the turn — the user-facing answer — as the only unbounded wait. It gets a deadline; on expiry it degrades to the existing deterministic summary. The deadline is a safety net, not the primary speed mechanism.
- (User, session-319) Speed is solved by STREAMING plus a smaller prompt, never by degrading answer quality. The transport already supports streaming; the final synthesis simply does not use it. Owner explicitly lifted the session-316 "No frontend changes" Non-Requirement for this.
- (User, session-319) The prism card must present information legibly: table cells must not break words mid-token, and the card's `format` selection must prefer `text` or a text/table combination when markdown tables would cramp the content. Owner-supplied screenshot evidence: headers rendered as "STA TUS", "Moonshin e", "Par tia l", "Fai led".

## Introduction
Tool-call results currently re-enter the DER loop as raw or near-raw text (up to an 8000-char gather window at agent_kernel.py:11463-11468), leaking provider chrome into working memory (conv-99: 71.5k chars vs 64k window) and forcing every consumer — Director, Reviewer, Executor — to read the same undifferentiated blob. This spec introduces a ToolResultEnvelope computed once at write time, routes role-appropriate views to each consumer, and gates replanning on stuck-streak instead of iteration count. The remaining session-312 fixes (embedder warm-at-boot, transport Empty-retry, fallback report formatting) ride this spec as REQ-6 because they were pinned as owed work (pin_7930379e0f41).

### Success criteria
- Planning/step prompts carry NO raw tool payload text — verified live by context-pill size staying well under the window on a 3-crawl research turn (baseline: conv-99 hit 71.5k/64k; target: <50% window on the same probe shape).
- No URL re-crawled within a turn on the comparison probe (gather gate filters registry URLs against turn memory — already live from session-312, must survive this refactor).
- Replan gate fires only on stuck-streak, not per step: counter shows ≥1 blocked (below-threshold) gate evaluation on a nominal 3-step task, and fires on a genuine repeat/empty/mismatch streak or idling run.
- Run grade honest: a probe run with re-crawls or a load-bearing mismatch MUST NOT report full pass — grade caps at partial with reasons; over-exceed means beating baselines (faster than conv-96 5:15, zero re-crawls, citations intact, no raw user-visible).
- Embed breaker CLOSED through a full live run (warm-at-boot); zero `Empty response from API` step failures on a 10-step run (transport retry).
- Fallback report: no raw tool payloads user-visible; per-step envelope summaries with line breaks.
- Turn time on the comparison probe < ~4 min (baselines: conv-96 5:15 / conv-97 5:38 / conv-99 6:40).
- Zero same-address re-fetch within a turn on the re-run probe — including near-duplicates (same seed re-picked across queries, identical bodies under different URLs); the conv-102 failure (one wiki seed dispatched 3x at ~110/90/82s) must be impossible, not merely unlikely.
- Recovery lane proven live: a seeded 404 resolves via in-site VLM navigation inside its page budget, with its own envelope; the dead address itself is never re-fetched.
- Every tool step settles within its deadline + small epsilon; any hang surfaces as a `timeout` envelope (never a silent stall); run grade caps below pass when timeouts hit load-bearing steps.

## Requirements

### REQ-1: ToolResultEnvelope written at wrap time
**User Story:** As the DER loop I want every tool result wrapped in a bounded envelope at write time so that downstream consumers never see unbounded raw payloads.

**Verified:** NEW (implementation pending). Substrate verified: `_capture_tool_result` (agent_kernel.py:4791-4840) already persists raw output to the document store keyed by `document_id` — the envelope's `raw_ref` rides that id. `NodeRecord` (der_loop.py:74-188) already carries `outcome`, `content_summary`, `expected_output`, `remaining`, `ruled_out`, `coords_from`, `coords_to`, `mediator` stamped at the finalize site.

**Acceptance Criteria:**
- AC1.1: THE SYSTEM SHALL wrap every executed tool-call result into an envelope with fields: `status` (success | error | partial), `summary` (≤2 lines, ≤300 chars), `raw_ref` (`doc_id` from the document store — doc-only, never chunk ids), the decision wrapper (per REQ-3: `status / match / novelty / suggestion` in words), the `coords_from → coords_to` pair carried VERBATIM for future wormhole hashing, `criticality` (load-bearing | supporting | cosmetic) with `criticality_source` (declared | confirmed), step identity (`card_id, step_id, session_id, turn_id`), and — when status ≠ success — `error_type` and `recovery_hint`.
- AC1.2: WHEN a tool result is produced THEN THE SYSTEM SHALL compute the envelope exactly once, at the finalize site (alongside the existing node-record stamping, agent_kernel.py:14054-14100), and attach it to the step's QueueItem — never re-derived per consumer.
- AC1.3: THE SYSTEM SHALL persist the raw result exactly once (existing document store + Pacman fragment path — both already run on every step result, agent_kernel.py:13261-13316) and reference it via `raw_ref` doc id ONLY — Pacman filing is async (`_submit_fragment_job`), so chunk ids are NOT available at wrap time and SHALL never be waited on; the envelope SHALL introduce NO new persistence — no new tables, no new encodes, no new vectors.
- AC1.4: IF envelope construction fails THEN THE SYSTEM SHALL degrade to a minimal envelope (status from the step outcome, summary = existing content_summary, raw_ref = document id or "", wrapper = match:unclear / novelty:new / suggestion:proceed, coords as available) and log the failure — never break the DER loop.
- AC1.5: THE SYSTEM SHALL stamp the step's `coords_from → coords_to` pair VERBATIM (canonical `format_coords` form when available) for future wormhole hashing; WHEN no coordinate signal exists for a step (tool-less direct step with no record) THEN THE SYSTEM SHALL record coords explicitly empty with basis "none" — never a fabricated zero coordinate.
- AC1.6: THE SYSTEM SHALL carry the planner-DECLARED `criticality` on the envelope at plan time and CONFIRM it at finalize from `raw_ref` consumption (a step declared supporting whose `doc_id` later steps actually consume is re-stamped confirmed load-bearing, and the declaration-vs-consumption divergence is logged as a tuning signal) — option C, zero LLM calls, O(1) counter lookups.

**Edge Cases:**
- Tool result is a dict with success=False (tool bridge errors) → status=error, error_type from the existing structured error shape (tool_errors.py).
- Capture gate skips persistence (`_is_capture_worthy` returns False) → raw_ref = "" with summary-only view + explicit "[uncaptured]" marker (coords still stamped when available); never a silent empty.
- Envelope for tool-less (`_run_step_direct`) steps → status from verification, summary = bounded response digest.

### REQ-2: No raw payload re-enters the loop
**User Story:** As the Director I want prompts assembled only from envelope fields so that my context stays bounded regardless of crawl size.

**Verified:** REAL GAP — current leak sites traced: working-memory append (agent_kernel.py:13382-13396, appends up to 8000-char gather excerpt AND skips failures entirely at :13387, so the next step cannot see the flat tire it just hit), planning prompt full-thread render (agent_kernel.py:5239-5249), continuation OUTPUT block (agent_kernel.py:14557-14572 — full raw `i.result` for the last 10 steps in the done_summary half plus `out[:600]` in the outputs_block half), user-facing fallback evidence (agent_kernel.py:11463-11468, 8000-char raw window; :11626-11692 summaries consume it).

**Acceptance Criteria:**
- AC2.1: WHEN working memory accumulates a step finding THEN THE SYSTEM SHALL append the envelope LINE (status + summary + wrapper labels + raw_ref doc id) for EVERY settled step INCLUDING failures — never the raw result excerpt and never a silent skip. (Session-319 correction: this AC is currently VIOLATED for genuinely failed steps, not merely under-tested. `_der_finalize_step` (agent_kernel.py:14187-15670) is the only writer of both the envelope and turn URL memory, and the step loop skips it entirely on failure — `_der_handle_step_failure` (:10803) builds no envelope. A failed or crashed step therefore produces neither an envelope nor URL memory, which is also why a repeat re-crawl follows an error. The envelope build SHALL run on the failure path too. This is an existing-AC defect, not new scope.)
- AC2.2: WHEN the continuation loop reports completed-step outputs (`_der_plan_next_step` OUTPUT block) THEN THE SYSTEM SHALL render envelope summaries + wrapper labels only, with BOTH halves bounded (the full-`i.result` done_summary half capped to envelope lines exactly like the outputs block).
- AC2.3: WHEN the user-facing deterministic fallback summaries render THEN THE SYSTEM SHALL render envelope summary + wrapper lines with line breaks — raw gather text MUST NOT be user-visible (this satisfies the pinned fix 7 acceptance bar).
- AC2.4: WHEN a prompt requires conversation history THEN THE SYSTEM SHALL render history messages through existing inline summaries only; raw tool payload text MUST NOT appear in any planning or step prompt.
- AC2.5: WHEN a consumer needs the full output THEN THE SYSTEM SHALL resolve the `raw_ref` doc id on demand (Executor paths only, per REQ-4).

**Edge Cases:**
- Envelope missing on a legacy QueueItem (pre-envelope steps in flight across a hot reload) → fall back to existing `_smart_excerpt` bounded evidence.
- raw_ref unresolvable (doc pruned) → summary-only view + explicit "[source unavailable]" marker, never a silent empty.

### REQ-3: Decision wrapper computed at wrap time (words, not physics)
**User Story:** As the Director I want each result labeled in words I can act on — did it work, did it match, is it new, what next — so I can steer without doing math.

**Verified:** NEW (substrate traced: outcome + `expected_output` + continuous `verified_fraction` 0..1 + coords pair + Caducean rec are ALL in scope at finalize, agent_kernel.py:14026-14100; fraction recomputed at :14090-14097; TOPO_VIOLATION rec=3 already "stops the line" at der_loop.py:536; turn URL memory `_der_crawled_urls` + gather gate at :12151; `tool_errors.py` walled/transient taxonomy).

**Acceptance Criteria:**
- AC3.1: THE SYSTEM SHALL compute the wrapper deterministically at envelope write time from already-recorded signals (zero LLM calls, zero token cost): `status` (success | error | partial — from step outcome + `tool_errors.py` shape), `match` (matched | mismatched | unclear — result vs the step's `expected_output` judged against that TOOL FAMILY's bar: gather = asked-terms present + sources cited; read = ref resolved; synthesis = covers prior envelope summaries with no raw dump; action = side effect confirmed), `novelty` (new | repeat_of_step_X | empty — against turn memory: crawled URLs, tool+params, output overlap), `suggestion` (proceed | retry_same | try_different | stop).
- AC3.2: THE SYSTEM SHALL classify every envelope into the stuck taxonomy from recorded values: circling (repeat of a prior step), dry well (success-shaped but empty/chrome-only), wrong package (real output, `match`=mismatched), flat tire (`status`=error / capture-skipped / vetoed), idling-in-neutral (success + new + matched yet `verified_fraction` unmoved across steps) — single-step visible for the first four, streak-counted for idling.
- AC3.3: THE SYSTEM SHALL enforce hierarchy C: WALLED/permanent-failure and CIRCLING are HARD rules — a repeat is NEVER re-executed (pre-dispatch block reroutes to read the original `doc_id` via `raw_ref`, T6B), a walled tool is NEVER retried in-run; mismatch / empty / transient-failure / idling are STRONG SUGGESTIONS the Director may override, and every override SHALL be logged with its reason.
- AC3.4: THE SYSTEM SHALL treat a Caducean TOPO_VIOLATION recommendation (der_loop.py:536) as an authoritative override forcing `suggestion`=stop plus streak-gate fire (physics-aware first, per the reuse-existing-detection lock).
- AC3.5: THE SYSTEM SHALL compute the wrapper with O(1) work over in-scope values only — no embedding encode, no vector math, no DB write in the builder (pure, deterministic, unit-testable).

**Edge Cases:**
- coords_to == coords_from (no movement recorded) → stamped as-is (verbatim passthrough); movement claims come from wrapper streaks, never from coordinate arithmetic.
- Tool-less direct step → wrapper from verification only (`match` vs `expected_output`, `novelty`=new unless duplicate response digest).

### REQ-4: Role-differentiated consumption
**User Story:** As the system I want each role to read only its view of a result so that context cost matches decision needs.

**Verified:** Substrate verified — Reviewer gate exists (agent_kernel.py:8319-8368, `reviewer.review(item, completed_steps, context_package, is_mature)` → PASS/REFINE/VETO); continuation Director exists (`_der_plan_next_step`, agent_kernel.py:14531-14616); Executor is the executing step itself (`_run_step_direct` :11914 + tool dispatch).

**Acceptance Criteria:**
- AC4.1: WHEN the Reviewer evaluates a step THEN THE SYSTEM SHALL pass it the envelope's status + wrapper + summary (plus existing review inputs) — not the raw result.
- AC4.2: WHEN the continuation Director decides whether more work is needed THEN THE SYSTEM SHALL build its prompt from envelope summaries + wrapper labels only (and report `done + grade` per AC5.6, never bare `done`).
- AC4.3: WHEN an Executor step needs prior raw output (e.g. read a fetched document) THEN THE SYSTEM SHALL resolve it via `raw_ref` from the durable store — the only role with raw access.
- AC4.4: THE SYSTEM SHALL keep the existing ReviewVerdict (PASS/REFINE/VETO) semantics unchanged — the envelope changes the Reviewer's INPUTS, not its contract output.

**Edge Cases:**
- Reviewer disabled/unavailable (exception → PASS at :8327-8328) → unchanged fallback behavior.
- raw_ref fetch fails mid-Executor-read → bounded "[source unavailable]" + step proceeds honestly.

### REQ-5: Stuck-streak-gated replanning + weighted run grade
**User Story:** As the owner I want replanning to fire only when the agent is actually stuck — and the run to report whether it cleared the bar, not just whether it finished — so nominal runs don't pay replan cost and low-bar passes can't masquerade as success.

**Verified:** REAL GAP — the current replan entry points are user-steering (`_replan` at agent_kernel.py:9488, boxed with turn budget) and the post-plan continuation loop (`_der_plan_next_step` :14531, invoked after planned steps complete, answering bare done true/false with no quality notion). Neither consults wrapper streaks or step criticality.

**Acceptance Criteria:**
- AC5.1: WHEN the active task's envelope wrapper stream shows a stuck streak — N consecutive `novelty`=repeat/empty or `match`=mismatched, or an idling streak (success + new + matched with unmoved `verified_fraction`) — THEN THE SYSTEM SHALL trigger the replan path (existing steering/replan machinery).
- AC5.2: WHEN wrapper streaks are below all thresholds THEN THE SYSTEM SHALL NOT invoke any replan inference — the current plan continues.
- AC5.3: THE SYSTEM SHALL reuse the existing Caducean recommendation levels (der_loop.py:528: EXPAND/CONTRACT/MAINTAIN/TOPO_VIOLATION) as the detector substrate where a phase signal is available, with TOPO_VIOLATION forcing the gate regardless of streak arithmetic; the wrapper streak is the fallback detector when no phase signal exists.
- AC5.4: WHEN a streak-triggered replan fires THEN THE SYSTEM SHALL record the triggering envelopes (step ids + wrapper labels) in the log/ledger so the trigger is auditable post-run.
- AC5.5: THE SYSTEM SHALL bound gate evaluation to O(envelope count) arithmetic — no LLM call in the gate itself.
- AC5.6: WHEN the run completes THEN THE SYSTEM SHALL report `done + grade`: any load-bearing step with `match`≠matched caps the run below full pass (partial with reasons); supporting/cosmetic misses alone never sink it; beating the pinned baselines (faster than conv-96 5:15, zero re-crawls, citations intact, no raw user-visible) marks over-exceed.

**Edge Cases:**
- Fewer than N steps completed → gate cannot fire (insufficient evidence), never fires on step 1.
- All steps tool-less (no wrapper streak) → gate never fires; existing continuation logic owns the decision (grade still reported from verification).
- Replan itself fails (provider down) → existing boxed failure path (:9488-9524) — keep current plan.

### REQ-6: Session-312 pinned fixes (embedder warm, transport retry)
**User Story:** As the user I want the embedding breaker closed and provider-empty responses retried so that a cold start doesn't degrade a whole run.

**Verified:** REAL GAP — transport.py:839-840 raises `RuntimeError("Empty response from API")` after the 3-attempt HTTP loop (transport.py:773-824) with zero retry (Empty disease seen at 4 call sites across conv-96/97/98/99). rerank.py:133-182: cold first encode burns the 20s budget (`_EMBED_BUDGET_S`, rerank.py:28) then the breaker skips embeddings for the cooldown → BM25-only all run; EmbeddingService backend load is lazy on first encode (embedding.py:791-793) and the shared singleton is `get_embedding_service()` (embedding.py:957) covering rerank + SemanticVerifier + episodic.

**Acceptance Criteria:**
- AC6.1: WHEN the FastAPI lifespan starts THEN THE SYSTEM SHALL warm the shared EmbeddingService in a background task (one `encode("warmup")` via `get_embedding_service()`), best-effort, non-blocking to readiness.
- AC6.2: IF the warm-up fails THEN THE SYSTEM SHALL log the failure and continue serving — startup MUST NOT block or crash on a cold/dead sidecar.
- AC6.3: WHEN a non-streaming API response returns empty (no content AND no tool_calls) and attempts remain THEN THE SYSTEM SHALL retry the SAME payload before raising; the final failure keeps the existing `"Empty response from API"` error.
- AC6.4: THE SYSTEM SHALL preserve the existing rate-limit (`RateLimitedError`) and non-200 error paths unchanged.

**Edge Cases:**
- Sidecar dead at boot → warm fails fast, breaker path unchanged (BM25 fallback still works).
- Empty responses on all attempts → raise after retries (existing downstream sub-loop handling unchanged).

### REQ-7: Observability instrumentation
**User Story:** As the tuner I want counters for the envelope and streak gate so thresholds are measurable and tunable.

**Verified:** NEW. (Counters-as-instruments is a user-locked process convention from session-309.)

**Acceptance Criteria:**
- AC7.1: THE SYSTEM SHALL log, scoped by conversation/step, per envelope: status, match, novelty, suggestion, criticality (+ declared-vs-confirmed divergence), summary length — enough to reconstruct a run's stuck trajectory from logs alone.
- AC7.2: THE SYSTEM SHALL count: envelopes written, raw_ref fetches by role AND by consuming step (criticality confirmation), gate evaluations (fired vs blocked; hard-rule blocks vs suggestion overrides with reasons), context chars per assembled prompt (planning and step prompts), run grade inputs.
- AC7.3: THE SYSTEM SHALL log the embed breaker state transition and warm-up outcome at startup with timing.

**Edge Cases:**
- High-volume logging → debug-level for per-envelope lines, info for gate fires; never on the hot path's critical section.

### REQ-8: Visited-URL ledger rides the envelope and the prompts
**User Story:** As the brain I want the list of already-visited addresses pinned to my desk before every decision, so I stop sending the clerk back to the same shops.

**Verified:** REAL GAP (session-318, conv-102 evidence) — `_der_crawled_urls` IS populated at finalize (agent_kernel.py:13743-13751) but NO prompt renders it: envelope `line()` (tool_envelope.py:158-178) carries status/match/novelty/suggestion + doc_id + summary and zero URLs, and no planning/continuation prompt includes a visited-ledger block. The brain re-reads receipts that never name the shops.

**Acceptance Criteria:**
- AC8.1: THE SYSTEM SHALL stamp `sources` on every envelope — the URLs actually fetched for the step (derived at wrap time from in-scope result text, max 8, truncation marked) — with zero new I/O.
- AC8.2: WHEN a planning or continuation prompt is assembled THEN THE SYSTEM SHALL render a bounded VISITED block (turn's crawled URLs, max 20, with step join keys) plus the pivot rule: known-only discovery = pivot, never re-fetch.
- AC8.3: THE SYSTEM SHALL carry pointers ONLY in the ledger (URLs, doc_ids, step ids) — page bodies MUST NOT enter any prompt (digests-only lock preserved).
- AC8.4: THE SYSTEM SHALL make every ledger entry joinable (step_id + doc_id + session + turn) so wormhole/aperture reads it later with zero rework (reporter stamps, graph reads).

**Edge Cases:**
- Ledger empty (first step) → block omitted, never an empty header.
- Ledger over cap → most-recent-first truncation with an explicit `+N more` marker; refusal/exclusion logic always uses the FULL set even when the rendered block is truncated.
- Hot-reload mid-turn (ledger lost) → degrade to no-ledger behavior + warning log, never a block.

### REQ-9: The URL chooser sees the map (exclusions in, outlinks out, recovery lane)
**User Story:** As the loop I want the clerk who picks buildings to hold the crossed-out list, so the same address can never be picked twice — while a specialist may still explore unvisited rooms of a known building.

**Verified:** REAL GAP (session-318) — `CrawlPlanner.plan(query: str)` (crawl_planner.py:113) accepts ONLY a query: no exclusions, no history. Orchestrator dedup is scoped to one dispatch (`already attempted in this run`, orchestrator.py:~1410), so separate runs re-pick freely. Guard URL check reads `params["known_urls"|"url"]` (agent_kernel.py:12778-12799) which `crawler_query` steps never carry; resolved seeds are never checked at queue time.

**Acceptance Criteria:**
- AC9.1: WHEN seeds are resolved for a dispatch (planner output or crawler-resolved) THEN THE SYSTEM SHALL filter them against the turn visited set BEFORE paying for the fetch — reusing the existing `_der_crawled_urls` instruments (gather-gate shape + guard branch-2); a fully-known seed set refuses the dispatch (re-seed or pivot, logged). Exclusion is HARD — same class as CIRCLING, no LLM override. (Correction, session-318: per-URL exclusion machinery already exists for registry-suggested URLs — this AC wires the fresh-discovery road into those same instruments instead of building new ones. Whether exclusions enter `plan()` as a parameter or filter its output at queue time is implementer's choice — CT-12 pins the behavior.)
- AC9.2: THE SYSTEM SHALL widen orchestrator dedup from run scope to turn scope — resolved seeds are checked against the turn crawled set at queue time; a fully-known seed set refuses the dispatch (re-seed or pivot, logged).
- AC9.3: THE SYSTEM SHALL feed crawler-resolved seeds back into turn memory so the pre-dispatch guard judges addresses actually about to be fetched, not just `params["known_urls"]`.
- AC9.4: WHEN a page is extracted THEN THE SYSTEM SHALL return its bounded outlink set with crawled/uncrawled marking, as next-candidates for within-site pivots.
- AC9.5: WHEN a fetch dies (4xx / empty / dead body) THEN THE SYSTEM SHALL open a VLM in-site recovery step — targets MUST be unvisited pages under the same site, with its own envelope (`recovery_of` = parent), budget and deadline; an empty-handed return settles honestly (dry-well/flat-tire) and streak-counts. Same-address re-fetch stays blocked inside recovery too. (Session-319 correction: "a fetch dies" means AT LEAST ONE dead address in the step, whether the step otherwise succeeded or failed. The trigger SHALL be evaluated for FAILED steps as well as successful ones — the session-318 implementation evaluated it only from the success-path finalize and additionally required zero sources, which made the lane unreachable for a blocker inside an otherwise-successful crawl. The previous zero-sources precondition is RETIRED.)
- AC9.6: THE SYSTEM SHALL run recovery concurrent with the main plan — the brain never waits on it; dependents wait bounded by its deadline while independent steps proceed; the recovery envelope joins the ledger on return. (Session-319 correction: "concurrent" is a concurrency requirement, NOT an ordering requirement. Inserting a recovery step into the serial execution queue does not satisfy this AC — the session-318 implementation did exactly that. The lane SHALL NOT extend the critical path of independent work.)
- AC9.7: THE SYSTEM SHALL bound the recovery lane by the AGENT'S OWN sufficiency judgement plus its deadline, not by a fixed page count: the lane continues while the parent step's information need is unmet (envelope `match` ≠ matched) and the lane deadline has not expired. A runaway ceiling of 25 pages SHALL apply as a safety net only. WHEN the ceiling is reached THEN the lane SHALL settle honestly (budget-exhausted) and streak-count. The session-318 `RECOVERY_PAGE_BUDGET=5` operating cap and the `RECOVERY_DEPTH=2` constant (defined but consumed nowhere) are RETIRED.
- AC9.8 (session-319, FAULTLINE §11 "name the consumer"): `recovery_of` on the ENVELOPE (the parent step id stamped on a recovery envelope) SHALL have a NAMED reader or be removed. The session-319 ripple-map audit found it is written and stamped but read by nothing — all `recovery_of` reads in the codebase are on the QueueItem, not the envelope. **Named reader: the aperture's chain provenance** (`specs/wormhole-aperture` REQ-32 AC7), where a recovery node's parent link is part of the chain's provenance — the aperture requires `recall_trace_id` to survive "all the way to a FAULTLINE outcome and to a chain's provenance". Until the aperture lands, this field is a DECLARED INTERFACE rather than decoration, and its round-trip is pinned by CT-16. If the aperture work drops the parent link, this field is removed with it.

**Edge Cases:**
- Exclusion empties the seed set → planner returns no-seeds + the loop pivots (new query or lane), never a forced crawl.
- Recovery budget exhausted → honest empty return, parent suggestion becomes try_different.
- Site has no outlinks/sitemap → recovery closes immediately as dry-well, zero extra fetches.

### REQ-10: Content identity and dead-address memory
**User Story:** As the loop I want to recognize identical bags and condemned buildings, so the same groceries are never cooked twice and dead addresses are never revisited.

**Verified:** REAL GAP (session-318, conv-102) — the same README body counted as fresh evidence 3x and a 404 page was "read" 2x; nothing hashes extracted text or remembers dead addresses in-turn.

**Acceptance Criteria:**
- AC10.1: WHEN an extracted body hash-matches a body already held this turn THEN THE SYSTEM SHALL resolve via the original `raw_ref` read (no re-pay) and log the hash hit.
- AC10.2: THE SYSTEM SHALL remember dead addresses in-turn (4xx, empty, known-404 bodies) and never re-fetch them; recovery navigates AROUND them (AC9.5), never to them.
- AC10.3: THE SYSTEM SHALL compute identity as stdlib exact hashing of normalized text — no vectors, no encodes, no similarity scoring (fingerprint CUT stands).

**Edge Cases:**
- Near-identical bodies differing by chrome/timestamp → hash differs, treated as new (exact-match only, by design).
- Hash of an error page vs a later-fixed page → dead memory is in-turn only; next turn refetches honestly.

### REQ-11: Deadlines and monitoring for every tool execution
**User Story:** As the owner I want every errand to carry a hall pass with a return time, so nothing stands outside a shop forever and every overdue trip is written in red ink.

**Verified:** REAL GAP (partial) — the crawler enforces a run ceiling (`_DEFAULT_TIMEOUT_S` 90s, orchestrator.py:62-66, `wait_for` at :1319; worker ceiling crawl_runner.py:555-556), but NO universal per-step deadline exists at the DER dispatch layer, no stall heartbeat is required, and expiry has no honest `timeout` envelope status (conv-102's long steps simply ran 82-110s with zero monitoring lines).

**Acceptance Criteria:**
- AC11.1: WHEN any tool step dispatches THEN THE SYSTEM SHALL attach a per-family deadline from constants (defaults UNVERIFIED: crawl 150s — above the conv-102 observed 82-110s max; read/fetch 60s; default 90s; tuned later from counters).
- AC11.2: WHILE a tool step runs past STALL_WARN_S (UNVERIFIED default 30s) without a `task:progress` heartbeat THEN THE SYSTEM SHALL log a stall warning (warn only — abort happens on deadline alone, never on stall).
- AC11.3: WHEN a deadline expires THEN THE SYSTEM SHALL settle the step as `status`=timeout with `suggestion`=try_different, preserve any partial result via `raw_ref` when available, and log the cause with elapsed-vs-deadline.
- AC11.4: THE SYSTEM SHALL streak-count timeouts exactly like empties toward the replan gate.
- AC11.5: THE SYSTEM SHALL bound every wait on a tool path (queues, joins, sidecar calls) — no unbounded wait exists anywhere a step can hang. (Session-319 correction: this AC was read as "tool paths only" and therefore excluded the FINAL SYNTHESIS call — the largest prompt and the slowest call of the turn, which was left as the only unbounded wait in the system. The scope is the whole TURN, not just tool dispatch.)
- AC11.6: WHEN the final synthesis call dispatches THEN THE SYSTEM SHALL attach a deadline (default 120s, constant-tunable). On expiry the SYSTEM SHALL settle with the existing deterministic compressed-summary fallback and log the cause with elapsed-vs-deadline — never a silent stall, never an unbounded wait. The synthesis retry path SHALL NOT multiply the worst case beyond this deadline.

**Edge Cases:**
- Tool completes at the exact deadline boundary → completion wins, timeout never retro-fires.
- Heartbeat emitter itself broken → stall warnings only; the deadline remains the single abort authority.
- Recovery-lane step (AC9.5) carries the SMALLER of its lane budget-derived deadline and the family default.

### REQ-12: Instrumentation for ledger, chooser, identity, deadlines
**User Story:** As the tuner I want counters for every new instrument, so curfews, caps, and budgets are tuned from measurement, not guesswork.

**Verified:** NEW (extends the REQ-7 instruments convention).

**Acceptance Criteria:**
- AC12.1: THE SYSTEM SHALL count, scoped by conversation: ledger blocks rendered, exclusions applied, seeds refused at queue time, content-hash hits, dead-address hits, deadline hits, stall warnings, recovery opens with outcomes (recovered / empty / budget-exhausted).
- AC12.2: THE SYSTEM SHALL log per envelope: `sources` count, recovery flag + parent step when set, elapsed-vs-deadline seconds.
- AC12.3: THE SYSTEM SHALL leave existing warm/breaker logging (AC7.3) unchanged.
- AC12.4 (session-319, FAULTLINE §11 "name the consumer"): every counter this spec introduces SHALL name the site that READS it, or it SHALL be dropped. Named readers:
  - `envelope.recovery_opens` / `recovery_recovered` / `recovery_empty` — read by **T13** (the counter review) as the recovery lane's open→outcome funnel. If T13 does not read them, they are decoration and must be removed with the lane.
  - `envelope.deadline_hits`, `envelope.stalls`, `crawler.exclusions_applied`, `crawler.seeds_refused` — read by **T13** for the AC11.1/AC9.7 constant tuning (deadline durations, stall warn, page ceiling).
  - `envelope.hash_hits`, `envelope.dead_hits` — read by **T13** to confirm AC10.1/AC10.2 fire at all.
  - `envelope.ledger_renders` — read by **T13** to confirm AC8.2's VISITED block is actually rendered.
  This AC exists because the session-319 ripple-map audit found four signals in this lane with no reader; naming the consumer is what keeps a counter an instrument instead of a decoration.

**Edge Cases:**
- High-volume logging → per-step lines at debug, fires/refusals/timeouts at info; never inside the dispatch critical section.

### REQ-13: The answer is presented as it is produced, and legibly
**User Story:** As the user I want to watch the answer arrive and be able to read it, so a long research turn neither feels dead nor arrives as an unreadable slab.

**Verified:** REAL GAP (session-319, owner screenshot evidence) — the transport already supports streaming (`_stream` at transport.py:603 and :968 driven by `chunk_callback`) but `_synthesize_response` (agent_kernel.py:16053) passes no callback, so the entire answer is generated before the user sees anything; `_stream_and_collect` (:2839) exists and is never called. On presentation, `RichDocument.tsx` applies `overflow-wrap:anywhere` + `word-break:break-word` to `td`/`th` (:501-512) and forces `width:100%` (:542) with uppercase letter-spaced headers (:569-570), producing mid-word breaks ("STA TUS", "Moonshin e", "Par tia l", "Fai led").

**Acceptance Criteria:**
- AC13.1: WHEN the final answer is generated THEN THE SYSTEM SHALL stream it to the user progressively using the existing transport streaming path, so text appears as it is produced rather than only on completion. Streaming MUST NOT change the final text, the citation set, or the run grade.
- AC13.2: THE SYSTEM SHALL keep the synthesis deadline (AC11.6) as a safety net behind streaming — a stalled stream SHALL still settle within the deadline with the deterministic fallback, never hang.
- AC13.3: THE SYSTEM SHALL NOT break words mid-token inside prism-card table cells; table headers SHALL render on a single line, and a table wider than its container SHALL scroll horizontally rather than compress its columns.
- AC13.4: WHEN a document's content would present better as plain text or as a text/table combination than as a markdown table THEN THE SYSTEM SHALL select or offer that format — the existing `format` union (`markdown | html | table | diagram | text | json | image`) and the `alternatives`/`onFormatChange` affordance are the mechanism; no new format-picking framework SHALL be introduced.

**Edge Cases:**
- Streaming unavailable/failed at the transport layer → fall back to the non-streaming call; the user still gets the answer, just later.
- Client disconnects mid-stream → the turn settles normally; no orphaned generator.
- A table with one very long unbroken token (URL) → that cell alone may wrap; headers and normal prose still must not break mid-word.

## Non-Requirements (Out of Scope)
- No DCP rewrite or text-zone pruner (render-time caps rejected by user; envelope supersedes). Existing DCP call sites untouched.
- No change to the Reviewer's verdict contract, the planner's output schema, or tool selection authority (explorer.propose stays the single resolver).
- No new vector math / embedding models / per-step encodes — the wrapper is derived from existing recorded signals only (O(1), zero LLM); coords pass through verbatim for future wormhole hashing and are never arithmetized here.
- No graph scoring, hash minting, or recall ranking in the envelope (reporter-only; `specs/wormhole-aperture/` owns recall — ex-OQ-3 lives there).
- ~~No frontend changes (card renders whatever text arrives; envelope is backend-internal).~~ **LIFTED session-319 by owner.** The frontend IS in scope for two presentation requirements: (a) progressive rendering of the streamed final answer, and (b) prism-card legibility (no mid-token breaking in tables; format selection may prefer text or a text/table combination over a cramped markdown table). The envelope remains backend-internal; the frontend change is about how the answer is PRESENTED, not how it is computed.
- No touching pre-existing test failures (6 `_FakeKernel._router` fails; `test_der_phase1::test_single_authority`; voice_pipeline stale paths).
- No commit/push without explicit user approval.

## Open Questions
- (non-blocking) Stuck-streak thresholds (streak N per shape, idling N) + the grade rule start as constants in der_constants.py; tuned from REQ-7 counters after the first live run — per the instruments-locked process.
- (non-blocking) Whether envelope replaces `_der_node_record_evidence`'s 8000-char gather window for the SYNTHESIS prompt too, or only user-facing/loop surfaces — synthesis is already capped at 6000/step (session-247); decide from live evidence post-implementation.
- OQ-3 CUT (locked session-316): SEMANTIC SELECTION OF SESSION FINDINGS belongs to `specs/wormhole-aperture/` (wormhole Tier-1/Tier-2 recall). The envelope keeps recency order + `raw_ref` pointers; no fingerprint, no ranking here.
- (session-318, non-blocking) Deadline durations (AC11.1 family defaults 150/60/90s), STALL_WARN_S (30s), ledger caps (envelope `sources` ≤8, prompt block ≤20), recovery page/depth budget (default: 5 pages, depth 2) — all UNVERIFIED starting points in der_constants.py, tuned from REQ-12 counters after the first live re-probe. Owner confirms or adjusts before Wave 5 gates.

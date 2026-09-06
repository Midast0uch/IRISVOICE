# Tasks: Vision Goal-Directed Search, Turn-Aware Context, DAG Batch Execution & Hybrid Fetching

> Each task links directly to an EARS requirement and specifies intelligent, adaptive code edits. Grouped into waves for dependency ordering and parallel execution.

## Wave 1 — Foundation (Data Models, Schema Validation & Guardrails)
- [x] T1 (REQ-1, REQ-14): Implement `GoalAnatomy` dataclass, `target_anchor`, `TemporalDelta`, `TaskType`, `TemplateKind` enums, and real-time `mutate()` method — `backend/core_models.py` — RIPPLE: Updates `ExecutionPlan.original_task` and `PlanStep.expected_output`; implements `to_prompt()` and `__str__()` duck-typing so un-migrated callers do not break.
- [x] T2 (REQ-18): Implement `BatchToolCall`, `BatchItemResult`, and `BatchOutcome` dataclasses — `backend/core_models.py` — RIPPLE: Introduces composite batch node definitions into the DER execution model.
- [x] T3 (REQ-21): Implement 12-keyword `SchemaValidator` — `backend/vision/schema_validator.py` — RIPPLE: Validates `output_schema` against JSON Schema allowlist; enforces top-level object requirement and formats descriptive validation errors.
- [x] T4 (REQ-20): Implement `TaskGuardrails` semantic evaluator — `backend/vision/action_allowlist.py` — RIPPLE: Evaluates task-level semantic safety (`NO_PURCHASE`, `DOMAIN_BOUND`, `MAX_DEPTH`, `NO_EXTERNAL_AUTH`) prior to `ActionAllowlist.validate_action` element role checks.
- [x] T5 (REQ-19): Add `batch_records` and `batch_node_records` tables and migration to SQLite — `backend/memory/db.py` — RIPPLE: Sets up relational schema for parent-child batch tracking in SQLCipher WAL database.

---

## Wave 2 — Resilient Machine-Speed Execution, Discovery & PDF
- [x] T6 (REQ-16, REQ-17): Expose vision capability detection and dynamic cost tiering in `inference_router.py` — `backend/inference_router.py` — RIPPLE: Provides `has_vision_capability()` flag and Brain-managed routing logic across Tier 0 (HTTP ~100ms), Tier 1 (Local VLM ~400ms), and Tier 2 (Cloud Multimodal ~1.5s).
- [x] T7 (REQ-4, REQ-17): Implement `ActionTrajectory` and visual delta calculation — `backend/vision/fetch_vision.py` — RIPPLE: Records micro-step entries; computes perceptual luminance/hash delta; formats sliding window of last 3 actions for next prompt; injects negative constraints on zero-progress loops.
- [ ] T8 (REQ-4, REQ-5, REQ-6, REQ-12): Implement Human-Like Intent at Machine Speed, Modal Auto-Dismissal, Popup Adoption, and OS Keyring Session Injection in `BrowserSession` — `backend/vision/browser_session.py` — RIPPLE:
  - Instant teleport scrolling via `locator.scroll_into_view_if_needed()` and instant `window.scrollBy(0, delta)`.
  - Instant input filling via `locator.fill(value)` in 1ms with native event dispatches.
  - Pre-click bounding box center extraction $(cx / width, cy / height)$ for real-time cursor mirror emission.
  - Targeted element screenshots via `GoalAnatomy.target` element bounding boxes.
  - `OverlayDismissal` handler: catches `ElementClickInterceptedError`, sends `Escape`, clicks `DISMISS_SELECTORS`, falls back to `display: none` on persistent backdrop, retries original action and records `dismissed_overlay` in trajectory.
  - Popup / new window adoption via `context.on("page", self._on_new_page)`: awaits `domcontentloaded`, adopts as `self._page`, allocates next capture slot, emits `CRAWLER_PAGE_FETCHED`.
  - Secure session cookie injection via `keyring.get_password("iris_voice_sessions", domain)` into `context.add_cookies()`.
- [ ] T9 (REQ-9): Implement Hybrid Adversarial SEO and Affiliate Trap Filtering in search discovery — `backend/vision/search_discovery.py` — RIPPLE:
  - *Tier A (Fast Heuristic):* Regex rejection of affiliate query parameters (`aff_id`, `tag`, `click_id`, `ref`, `subid`, `afftrack`), redirect paths (`/out.php`, `/go/`), and spam TLDs.
  - *Tier B (Semantic Parasite Detection):* Evaluates keyword density, detects doorway pages and parasite SEO (coupon aggregators hosting product reviews), re-ranks by domain authority.
- [ ] T10 (REQ-15): Implement `fetch.pdf` fast native document extraction capability — `backend/crawler/capabilities.py` — RIPPLE: Implements `FetchCapability` protocol using PyMuPDF (`fitz`) / `pdfplumber` for $<1.5\text{s}$ binary text/table extraction; renders only specific target pages to PNG if visual chart inspection is required by `GoalAnatomy.target`.
- [ ] T11 (REQ-10): Extend `AskUserQuestion` with Contextual Browser Takeover Mode — `backend/agent/tools/ask_user_tool.py` — RIPPLE: Adds `kind="browser_takeover"` with `takeover_url` and `reason` fields; generates contextual guidance messages from page state; dispatches `iris:browser_takeover_requested` event; awaits user resolution, verifies challenge is cleared, and resumes execution.

---

## Wave 3 — DAG Batch Execution, Dynamic Query Adaptation, Verification & Temporal Memory
- [ ] T12 (REQ-7, REQ-18): Implement `BatchToolCall` scheduling with per-host concurrency governance and 429 circuit breaking in `der_loop.py` — `backend/agent/der_loop.py` — RIPPLE: Extends `all_ready_items()` to dispatch batch pools; enforces per-host semaphore (max 2 concurrent requests per domain); implements Host Circuit Breaker with exponential jitter backoff ($2\text{s} \pm 500\text{ms}$) on 429/503 responses.
- [ ] T13 (REQ-13): Implement Dynamic Real-Time Multi-Angle Query Synthesis & In-Flight Adaptation — `backend/agent/der_loop.py` & `backend/crawler/crawl_planner.py` — RIPPLE:
  - Brain agent dynamically analyzes user intent, domain context, and temporal requirements to synthesize 2–4 orthogonal query facets (NOT hardcoded templates).
  - Dispatches initial query set as a composite `BatchToolCall` in the DER DAG.
  - **In-Flight Adaptation Loop:** As intermediate findings accumulate in `StepFindingsAccumulator`, the Brain evaluates which schema fields remain missing or low-confidence. If critical knowledge gaps persist after initial URLs are processed, the Brain dynamically synthesizes targeted follow-up queries and enqueues them into the active DAG without restarting execution.
  - If domain blocks or unexpected layout shifts occur, the Brain mutates the query strategy in real time to seek alternative source domains.
- [ ] T14 (REQ-8, REQ-11): Implement `StepFindingsAccumulator` with Strict Schema Projection and Semantic Cross-Source Verification Gate — `backend/agent/der_loop.py` — RIPPLE:
  - Drops raw HTML/DOM; bounds memory to $\le 5\text{KB}$ per item; applies hierarchical extractive summarization above 32KB total.
  - Cross-Source Verification: requires corroboration across $\ge 2$ authoritative domains for critical fields; applies semantic normalization (currency reconciliation, condition-awareness for New vs Refurbished, bundle vs standalone pricing); flags irreconcilable discrepancies with source citations and context notes.
- [ ] T15 (REQ-14): Implement Semantic Temporal Snapshot Diffing in `document_store.py` — `backend/agent/document_store.py` — RIPPLE:
  - Compares current settled DOM with prior snapshots stored in `document_data`.
  - Generates natural-language semantic deltas (*"Price decreased by $200 (10% drop)"*, *"Availability: In Stock → Pre-order Only"*, *"Warranty updated from 1yr to 2yr"*).
  - Encapsulates in `TemporalDelta` and updates `revision = prior.revision + 1`.
- [ ] T16 (REQ-19): Implement atomic `save_batch_footprint` transaction — `backend/memory/card_footprint.py` & `backend/memory/db.py` — RIPPLE: Writes parent `BatchRecord` and all child `NodeRecord`s in a single SQLite transaction, preventing WAL lock contention.
- [ ] T17 (REQ-1): Wire real-time in-flight goal mutation into Brain turn handler — `backend/agent/der_loop.py` — RIPPLE: Allows user voice follow-up instructions to mutate active `GoalAnatomy` without restarting the execution plan.

---

## Wave 4 — Frontend Event Wiring, Saccadic Acceleration & Cards
- [ ] T18 (REQ-3, REQ-22): Zero-delay dual event emission in `tool_bridge.py` — `backend/agent/tool_bridge.py` — RIPPLE: Emits browser overlay events (`CRAWLER_PAGE_FETCHED`, `CRAWLER_VISION_ACTION` with `x`, `y`, `scroll_y`, `escalated`) AND chat card events (`TASK_PROGRESS` with `detail_url`, `detail_progress`, `phase`, `phase_sequence`) immediately without buffering or polling delays.
- [ ] T19 (REQ-3, REQ-10): Implement Saccadic Cursor Acceleration and Takeover Panel Unlock in `BrowserNavigationOverlay.tsx` — `components/iris/browser/BrowserNavigationOverlay.tsx` — RIPPLE: Dynamically scales transit duration down ($\le 180\text{ms}$) or particle-snaps when actions arrive rapidly ($\ge 3\text{ actions/sec}$); temporarily sets `pointer-events: auto` during user takeover; re-arms `pointer-events: none` on takeover resolution.
- [ ] T20 (REQ-22): Extend `TaskStep` and `TaskCard` interfaces and reducers — `hooks/useTaskProgress.ts` — RIPPLE: Adds `goalSnippet`, `extractedSchema`, `batchMetrics`, `temporalDelta`, and `verifiedFields` to module-level store; preserves state across component unmounts; retains `resultPreview` on completed rows.
- [ ] T21 (REQ-22): Update `TaskListCard.tsx` (Liquid Ink chassis for Personal Mode) — `components/chat/TaskListCard.tsx` — RIPPLE: Renders live `url` subtitle badges, rotating verbs (`SEARCH` $\rightarrow$ `READ` $\rightarrow$ `EXTRACT` $\rightarrow$ `CITE` $\rightarrow$ `SYNTH`), verified checkmarks for cross-source facts, temporal change pills (*"Price dropped 10%"*), and discrepancy alerts.
- [ ] T22 (REQ-22): Update `terminalScrollback.ts` (Blueprint Matrix chassis for Developer Mode) — `components/terminal/terminalScrollback.ts` — RIPPLE: Renders Goal Anatomy inspector, live `ActionTrajectory` sliding window, batch pool status, cross-verification status matrix, and dynamic query adaptation log.

---

## Wave 5 — Verification, Contracts & CDD Harness
- [ ] T23 (REQ-3, REQ-19): Contract tests for browser events, capability signatures, and batch DB transactions — `backend/tests/contract/test_crawler_vision_action_shape_contract.py`, `backend/tests/contract/test_fetch_vision_goal_contract.py`, `backend/tests/contract/test_batch_memory_atomic_contract.py` — RIPPLE: Locks CT-1 (`CRAWLER_VISION_ACTION` with `x`, `y`, `scroll_y`, `escalated`), CT-2 (`vision_status`), and CT-3 (`batch_records` atomic commit).
- [ ] T24 (REQ-3): Behavioral tests for zero-lag browser overlay choreography and saccadic cursor acceleration — `backend/tests/behavioral/test_browser_overlay_choreography_behavior.py` & `backend/tests/behavioral/test_saccadic_cursor_acceleration_behavior.py` — RIPPLE: Asserts overlay transitions `loading` $\rightarrow$ `dispersing` $\rightarrow$ `crawling` $\rightarrow$ `complete` without lag; asserts rapid-fire actions accelerate cursor without queue drift.
- [ ] T25 (REQ-5, REQ-6): Behavioral tests for modal auto-dismissal and popup adoption — `backend/tests/behavioral/test_modal_overlay_auto_dismissal_behavior.py` & `backend/tests/behavioral/test_popup_window_auto_adoption_behavior.py` — RIPPLE: Validates that intercepting cookie modals are cleared and links opening new tabs are adopted automatically.
- [ ] T26 (REQ-10): Behavioral tests for contextual user takeover mode via `AskUserQuestion` — `backend/tests/behavioral/test_user_takeover_mode_behavior.py` — RIPPLE: Asserts browser panel unlocks with contextual reason displayed, waits for user resolution, verifies challenge is cleared, and resumes automation upon click.
- [ ] T27 (REQ-11, REQ-14): Behavioral tests for semantic cross-source verification and temporal snapshot diffing — `backend/tests/behavioral/test_cross_source_verification_behavior.py` & `backend/tests/behavioral/test_temporal_snapshot_diffing_behavior.py` — RIPPLE: Asserts facts corroborated across $\ge 2$ domains are marked verified with semantic condition reconciliation; asserts price and availability changes are detected with natural-language delta statements.
- [ ] T28 (REQ-9, REQ-15): Behavioral tests for native PDF extraction and hybrid adversarial SEO filtering — `backend/tests/behavioral/test_native_pdf_extraction_behavior.py` & `backend/tests/behavioral/test_adversarial_seo_filtering_behavior.py` — RIPPLE: Asserts PDF documents extract in $<1.5\text{s}$; asserts search results filter out affiliate link mills AND parasite SEO doorways.
- [ ] T29 (REQ-2, REQ-7): Behavioral tests for per-host batch throttling, 429 circuit breaking, and early schema termination — `backend/tests/behavioral/test_per_host_batch_throttling_behavior.py` & `backend/tests/behavioral/test_early_schema_termination_behavior.py` — RIPPLE: Asserts per-domain concurrency bounds to 2, verifies 429 exponential jitter backoff, and validates early cancellation when schema is satisfied.
- [ ] T30 (REQ-13): Behavioral tests for dynamic real-time query adaptation — `backend/tests/behavioral/test_dynamic_query_adaptation_behavior.py` — RIPPLE: Injects partial batch findings with missing schema fields; asserts Brain dynamically synthesizes targeted follow-up queries and enqueues them into the active DAG without restarting execution.
- [ ] T31 (REQ-1, REQ-17, REQ-20): Behavioral tests for real-time goal mutation, dual vision routing, and task guardrails — `backend/tests/behavioral/test_realtime_goal_mutation_behavior.py` & `backend/tests/behavioral/test_dual_vision_routing_behavior.py` & `backend/tests/behavioral/test_task_guardrails_behavior.py` — RIPPLE: Asserts in-flight goal updates, direct Brain vision routing, and purchase blocking.
- [ ] T32 (REQ-12): Behavioral tests for secure session injection and HAR sanitization — `backend/tests/behavioral/test_secure_session_injection_behavior.py` — RIPPLE: Asserts cookies injected from OS Keyring; asserts exported HAR files redact all `Cookie`, `Set-Cookie`, `Authorization` headers to `[REDACTED]`.
- [ ] T33 (REQ-2): Benchmark harness for vision search efficiency — `backend/scripts/benchmark_vision_search_efficiency.py` — RIPPLE: Executes 5 standardized websearch extraction runs; measures and verifies $\ge 40\%$ reduction in round-trip latency and token count.

---

## Wave 6 — Websearch System-Memory Baseline, Diagnosis & Bound (REQ-23)
> Strictly additive: T1–T33 untouched. Chain order T34 → T35 → T36 (each needs the prior's output). No crawl-hot-path code changes in this wave — measure, attribute, then pin.
- [x] T34 (REQ-23 AC23.1–23.3): Implement `backend/scripts/benchmark_websearch_memory.py` reusing the `scripts/measure_memory.py` `measure()` psutil pattern (Private Bytes on win32, RSS fallback; same IRIS markers) — co-located with the T33 harness; import the pattern, do not duplicate it — RIPPLE: Out-of-process 3-phase sampler (idle → 1s-cadence peak → +60s return-to-idle) around the standardized 5-URL `dispatch_urls` run (default `CRAWL_CONCURRENCY=3`, ≥1 clean-domain fetch, race outcomes logged); as-built: driver tracked as an explicit `driver (self)` row + per-parent Child MB rollup (keeps `measure_memory.py` untouched under CT-4), `--repeat N` isolates incremental cost, `--assert-websearch` enforces pinned defaults (env-overridable). DONE 2026-09-06: live run 5 clean URLs x2, 5/5 usable, ~3s/iter.
- [x] T35 (REQ-23 diagnosis): Attribute the measured delta across the four suspects with file:line evidence and classify each REAL GAP / ALREADY FIXED / BY DESIGN — orchestrator semaphore + race loser-cancel (`orchestrator.py:869, 1496-1500`, ceiling `:81`), `browser_pool` lease vs 180s idle shutdown (`browser_pool.py:55`), `capture_store` disk-vs-RSS (`capture_store.py:79-80`), findings-accumulator context-vs-RSS + per-page screenshot release (`fetch_vision.py`) — RIPPLE: Read-only profiling using T34 data; confirms or exonerates the crawl-worker suspicion WITHOUT prescribing a fix; any code change becomes a follow-up spec, not a quiet widening of this one. DONE 2026-09-06: see Live outcome in design.md §9 (resident workers exonerated; REAL GAP = +315MB first-touch import commit per fresh process; idle 3.74GB floor reported out-of-scope).
- [x] T36 (REQ-23 AC23.4–23.5): Pin the measured bound into the spec + harness `--assert-websearch` flag; add `test_measure_markers_contract.py` (CT-4: markers cover `crawl_worker` + `browser_pool`) and `test_websearch_memory_baseline_behavior.py` (BT-11: table + JSON output, non-zero exit on breach, fail on resident worker outliving the run) — RIPPLE: Locks CT-4 so worker renames can't silently drop processes from accounting; tests assert harness behavior, not the UNVERIFIED number. DONE 2026-09-06: bounds pinned (IRIS peak ≤50 / return ≤25 / driver peak ≤350 MB, AC23.3); 9/9 tests pass; live `--assert-websearch` gate PASS.

---

## Dependency / Parallelization Notes

- **Parallelization Waves:**
  - **Wave 1 (T1–T5):** Data models, validator, guardrails, and DB schema; can run in parallel.
  - **Wave 2 (T6–T11):** Discovery filtering, PDF pipeline, resilient browser actions, and takeover mode can run concurrently once Wave 1 models land.
  - **Wave 3 (T12–T17):** Dynamic query synthesis & adaptation (T13), batch scheduler with host throttling (T12), semantic verification gate (T14), temporal diffing (T15), and schema projection can be developed concurrently with Wave 2.
  - **Wave 4 (T18–T22):** Frontend event wiring, saccadic acceleration (T19), and card enrichment can run in parallel with Wave 3.
  - **Wave 5 (T23–T33):** Contract tests (T23) are authored test-first; behavioral tests (T24–T32) and benchmark harness (T33) provide the final live verification gate.
- **Contract Locks:**
  - `CT-1`: `CRAWLER_VISION_ACTION` wire shape (`kind`, `action_index`, `total`, `x`, `y`, `scroll_y`, `scroll_height`, `viewport_w`, `viewport_h`, `escalated`).
  - `CT-2`: `iris:vision_status` wire shape (`status: "lifecycle"`, `state: "cold"|"spawning"|"warm"|"error"`).
  - `CT-3`: Capture store reserved slot offsets (`slot_capture_offset(idx)`: offset+1 for crawl HTML, offset+2..N for vision frames).

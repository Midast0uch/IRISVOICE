# Requirements: Vision Goal-Directed Search, Turn-Aware Context, DAG Batch Execution & Hybrid Fetching

## Decisions Locked

These are grounded in the actual codebase (`hooks/useTaskProgress.ts`, `hooks/useBrowserNavOverlay.ts`, `components/iris/browser/BrowserNavigationOverlay.tsx`, `components/iris/browser/VisionLifecycleChip.tsx`, `components/iris/AmbientCrawlTier.tsx`, `backend/crawler/orchestrator.py`, `backend/vision/browser_session.py`, `backend/agent/tools/ask_user_tool.py`, `backend/agent/document_store.py`, `backend/crawler/capabilities.py`). Do not re-litigate.

1. **Zero UX Regression on Curated Browser Surfaces:** The spec strictly preserves and wires directly into the existing browser navigation UX framework:
   - `BrowserNavigationOverlay.tsx`: 3-shell epitrochoid particle engine, 76px orb, 40px particle-trail cursor, 16px panel border radius, perimeter comet streams (`TRAIL_FRAC = 0.18`), lap pacing calibrated to live page interval, black-and-white escalation "notice" beat (`NOTICE_SOFT_WHITE`, `NOTICE_DURATION_MS = 2600`), and hex-mesh wavefront sweep.
   - `useBrowserNavOverlay.ts`: State machine choreography (`loading` $\rightarrow$ `dispersing` $\rightarrow$ `crawling` $\rightarrow$ `complete` / `error`).
   - `VisionLifecycleChip.tsx`: Consumes `iris:vision_status` (`cold`, `spawning`, `warm`, `error`) to display live VLM lifecycle status with heartbeat animation in the browser header.
   - `AmbientCrawlTier.tsx`: Consumes `CrawlProvider` + `useTaskProgress` to calculate `unifiedProgress` across task steps and crawl pages, providing a wing-independent working indicator and swallowing the orb when wings open.
   - `CaptureStore` Address Space: Preserves reserved capture slots (`slot_capture_offset(idx)`: offset+1 for crawl HTML, offset+2..N for vision frames) rendered into the Live Reading iframe without horizontal scrollbars.
2. **Preserve and Enhance Hybrid URL Fetching:** The 3-tier hybrid URL fetching pipeline in `backend/crawler/orchestrator.py` (`_dispatch_one`, `_race_url`, fresh-failure escalation) is strictly preserved and augmented:
   - Fast path: `fetch.crawl` (headless HTTP) runs first on clean domains.
   - Race path: Domains with recorded failure history in `source_registry` race `fetch.crawl` vs `fetch.vision` in parallel; first usable outcome wins, loser is immediately cancelled.
   - Escalation path: Bot challenges (Cloudflare, Turnstile) or empty DOMs escalate to `fetch.vision` (`crawl -> vision -> crawl`).
   - Early Termination: Evaluates `GoalAnatomy.schema` completeness after every page outcome; cancels remaining queued fetches and racers as soon as all required fields are satisfied.
3. **Human-Like Intent at Machine Speed (Zero Artificial Latency):** "Human-like" defines semantic intent and targeting, NOT artificial slowness. The backend runs at maximum machine speed:
   - Instant Teleport Scrolling: Uses `locator.scroll_into_view_if_needed()` or instant `window.scrollBy(0, delta)` with zero artificial animation loops. A micro-settle ($\le 100\text{--}200\text{ms}$) allows lazy-loaded DOM assets to hydrate without blocking.
   - Instant Input Filling: Uses `locator.fill()` executing in 1ms with native event dispatches, avoiding sluggish character-by-character typing delays.
   - Targeted Screenshots & Visual Bounding: Chromium-scoped viewport capture; crops directly to `GoalAnatomy.target` bounding boxes to preserve OCR resolution while cutting token latency by 60%.
   - Pre-Click Coordinate Emission: Captures locator center $(cx / width, cy / height)$ and emits $(x, y)$ instantly so the frontend particle cursor smoothly tracks the target without delaying backend execution.
4. **Real-Time Zero-Lag Frontend Reactivity with Saccadic Acceleration:** Zero delay between backend event emission and frontend overlay rendering. WebSocket frames dispatch immediately. When rapid-fire actions occur, the frontend overlay uses saccadic acceleration (dynamically compressing cursor transit time from 620ms down to $\le 180\text{ms}$ or snapping with particle bursts) so the cursor stays visually synchronized with the agent without lagging behind or buffering animations.
5. **Interactive Human-in-the-Loop Takeover via `AskUserQuestion`:** Unsolvable checkpoints (complex 2FA, SMS codes, slider captchas) do not abort the task. The agent emits `AskUserQuestion` with `kind="browser_takeover"` and contextual guidance, unlocks the in-app browser panel for direct user interaction, and automatically resumes execution once the user clicks "I've Completed It".
6. **Task Progress Single Source of Truth (`hooks/useTaskProgress.ts`):** All agent activity events (`task:start`, `tool:call`, `tool:result`, `tool:error`, `task:progress`, `task:done`, `task:fail`, `task:learning`, `memory:event`) flow through the module-level card store.
7. **Model-Agnostic Dual Vision Routing & Dynamic Cost/Latency Tiering:** The Brain model dynamically manages routing across three cost/latency tiers: Tier 0 (Headless HTTP crawl ~100ms), Tier 1 (Local VLM `LFM2.5-VL` ~400ms for micro-actions), and Tier 2 (Cloud Multimodal for complex visual synthesis), optimizing VRAM and token expenditure.
8. **Real-Time Dynamic Goal Synthesis & In-Flight Revision:** The 7-part `GoalAnatomy` is synthesized from user prompts using canonical templates (Templates A–H), and *mutated in real time* during execution upon follow-up instructions or environmental surprises.
9. **DAG-Native Batch Tool Execution & Atomic Persistence:** Batch tool execution is a first-class citizen of the DER DAG execution framework across all tools. Concurrency is governed per resource (Crawl: 10, Vision-VLM: 1-2, Brain-Vis: 4). Batch outcomes commit atomically to SQLCipher `memory.db` (WAL mode) and the Mycelium coordinate graph under a single parent `BatchRecord`.
10. **Task-Level Guardrails Execute BEFORE Allowlist Checks:** Semantic negative constraints (e.g., `NO_PURCHASE`, `DOMAIN_BOUND`, `MAX_DEPTH`) evaluate prior to `ActionAllowlist` role checks.
11. **12-Keyword Schema Contract:** Structured output conforms to the 12-keyword allowlist (`type`, `properties`, `required`, `items`, `enum`, `format`, `minItems`, `maxItems`, `minimum`, `maximum`, `nullable`, `propertyOrdering`), utilizing sample values to anchor extraction formatting.
12. **Websearch Perf Baseline Scope (2026-09-06, REQ-23):** Strictly additive
13. **Wave-7 seam follow-ups (2026-09-07, REQ-24–REQ-27):** Strictly additive — deferred for scope discipline, not uncertainty; each names its thin seam and its rejected widening (scheduler service, new dependency, hard type switch, test weakening). REQ-27 defaults to keeping Session-247 per-page step behavior pending live confirmation (OQ-3).
14. **Memory envelope (2026-09-07, REQ-28, LOCKED by user):** Idle ≤2.5GB committed with zero per-task growth and first-utterance ≤30s. Strategy = lazy at boot (no boot-time worker) + pre-warm on frontend connect + idle-unload after quiet period + singleflight respawn. Pure-lazy-without-prewarm was rejected (238s cold start); keep-early-spawn + amend-gate was rejected (user wants smallest idle). — REQ-1..REQ-22 objectives, success criteria, and UX contracts are untouched. The numeric spike bound is measure-first (UNVERIFIED until the T34 live run pins real numbers). Diagnosis precedes any fix (profile orchestrator / browser_pool / capture_store / findings accumulator before bounding). The harness reuses the `scripts/measure_memory.py` psutil pattern from the memory-optimization spec.

---

## Introduction

IRIS websearch and browser automation combine a high-fidelity visual frontend (`BrowserNavigationOverlay`, `VisionLifecycleChip`, `AmbientCrawlTier`, `TaskListCard`) with an async backend hybrid crawler (`CrawlOrchestrator`, `BrowserSession`, `fetch_vision`). Previously, the backend lacked goal-directed field filtering, structured schema contracts, and human-like interaction heuristics, while passing raw unparsed strings across turns.

This feature establishes an intelligent, adaptive goal-directed execution framework: real-time synthesis and revision of structured `GoalAnatomy`, human-like intent at maximum machine execution speed, enhanced hybrid URL fetching with early schema termination, model-agnostic dual vision routing with dynamic cost tiering, DAG-native batch tool execution, atomic multi-record memory commits, hybrid adversarial SEO filtering, interactive user takeover with contextual guidance, semantic cross-source fact verification, secure OS keyring cookie injection, **dynamic real-time orthogonal query synthesis**, semantic temporal snapshot diffing, native PDF deep extraction, and seamless zero-delay event streaming into the existing browser navigation overlay, lifecycle chip, and ambient crawl tier without UI regression.

### Success Criteria

- **Websearch Efficiency & Speed:** Vision-guided websearch duration reduced by $\ge \mathbf{40\%}$ across standardized extraction tasks through targeted field cropping, loop termination, hybrid racing, and early schema termination.
- **Frontend Real-Time Reactivity:** Zero noticeable latency between backend action dispatches and frontend overlay responses ($<50\text{ms}$ socket-to-render handoff).
- **Zero Cursor Desync:** Under high-speed execution ($\ge 5\text{ actions/sec}$), saccadic acceleration ensures the frontend particle cursor tracks the agent's target within $\le 100\text{ms}$.
- **Adaptive Query Coverage:** Multi-angle queries dynamically synthesize 2–4 orthogonal facets tailored to user intent, adapt in-flight based on discovered knowledge gaps, and achieve $\ge 90\%$ information completeness on multi-faceted topics.
- **Hybrid Adversarial SEO Rejection:** $\ge 92\%$ of content-farm, affiliate aggregator, and doorway links filtered out before spending crawl or vision resources.
- **Interactive Takeover Completion:** $100\%$ successful task resumption following user takeover resolution via `AskUserQuestion`.
- **Semantic Cross-Source Verification:** $100\%$ of numerical, pricing, and factual claims reconciled and verified across $\ge 2$ independent sources with context-aware condition handling (e.g., bundle deals, refurbished vs new).
- **Secure Keyring Authentication:** $100\%$ of sensitive credentials and auth cookies loaded from OS Keyring without plaintext exposure in prompts, logs, or HAR archives.
- **Semantic Temporal Diff Accuracy:** Instant identification of natural-language pricing, inventory, and policy deltas compared against previous visit snapshots in `document_store`.
- **Native PDF Extraction Speed:** 50-page PDF documents parsed and extracted in $<1.5\text{s}$ via the dedicated binary pipeline, bypassing browser scrolling loops.
- **Websearch Memory Baseline (pinned T36 from the 2026-09-06 live run — 5 clean URLs x2, 5/5 usable, ~3s/iter):** IRIS peak +0.0MB (bound ≤50MB), IRIS return +0.0MB (bound ≤25MB); driver first-touch import commit +292MB with ~0MB incremental per repeat search (driver peak bound ≤350MB). See REQ-23.

---

## Requirements

### REQ-1: Structured Goal Anatomy Model & Real-Time Synthesis
**User Story:** As the Brain agent, I want to synthesize and revise structured 7-part goals from user requests in real time using standardized templates, so that automation tools receive explicit, unambiguous parameters that adapt as information is discovered.

**Verified:** Traced against raw string blobs at `backend/core_models.py:737` (`original_task`) and `backend/agent/der_loop.py:213` (`objective_anchor`).

**Acceptance Criteria:**
- AC1.1: THE SYSTEM SHALL represent task goals using a structured `GoalAnatomy` dataclass containing:
  - `objective` (str): primary task objective.
  - `task_type` (TaskType): enum (`DATA_EXTRACTION`, `FORM_FILLING`, `MULTI_STEP_WORKFLOW`, `SEARCH_DISCOVERY`).
  - `target` (Optional[str]): specific screen region, table, or visual element to focus on.
  - `target_anchor` (Optional[str]): contextual anchor text/selector to disambiguate identical buttons.
  - `fields` (Optional[list[str]]): exact attribute names to extract.
  - `schema` (Optional[dict]): output JSON schema contract.
  - `steps` (Optional[list[str]]): sequential operational directives.
  - `guardrails` (list[str]): negative constraints (default: `["NO_PURCHASE", "DOMAIN_BOUND"]`).
  - `edge_cases` (dict[str, str]): condition-to-action rules (e.g., `{"out of stock": "set price to null"}`).
  - `memory_anchors` (dict[str, Any]): key entity bindings across steps.
- AC1.2: THE SYSTEM SHALL provide built-in template initializers for canonical task shapes (Templates A–H).
- AC1.3: THE SYSTEM SHALL allow the Brain agent to mutate and revise an active `GoalAnatomy` in real time upon receiving follow-up user instructions, detecting unexpected layouts, or hitting recoverable errors.
- AC1.4: THE SYSTEM SHALL implement `to_prompt()`, `to_json()`, and `__str__()` methods on `GoalAnatomy` ensuring backward-compatible string duck-typing for legacy callers.

---

### REQ-2: Enhanced Hybrid URL Fetching (Race, Escalation & Early Termination)
**User Story:** As the crawler orchestrator, I want to preserve and enhance the hybrid URL fetching pipeline with goal-directed early termination, so that websearches execute at maximum speed without redundant page visits.

**Verified:** Traced against `backend/crawler/orchestrator.py:840-900` (`_dispatch_one`), `orchestrator.py:1470-1530` (`_race_url`), and `orchestrator.py:943-950` (escalation).

**Acceptance Criteria:**
- AC2.1: THE SYSTEM SHALL maintain the three-tier hybrid URL fetching dispatch strategy in `CrawlOrchestrator`:
  - *Tier 1 (Fast Crawl):* Unseen or known-clean domains execute via `fetch.crawl` (headless HTTP).
  - *Tier 2 (Domain Failure Race):* Domains with recorded failure history in `source_registry` execute via `_race_url` (running `fetch.crawl` and `fetch.vision` concurrently; first usable outcome wins; loser is cancelled).
  - *Tier 3 (Challenge Escalation):* Fresh bot challenges (Cloudflare, Turnstile) or empty DOMs from Tier 1 escalate to `fetch.vision` to settle the page and extract content.
- AC2.2: THE SYSTEM SHALL pass `GoalAnatomy` to both `fetch.crawl` and `fetch.vision` racers in `_race_url`.
- AC2.3: WHEN executing a batch of URLs with an `output_schema`, THE SYSTEM SHALL evaluate schema completeness after every page outcome; IF all required fields are satisfied, THEN THE SYSTEM SHALL cancel remaining queued fetches and return immediately (Early Termination).
- AC2.4: WHEN `_race_url` completes, THE SYSTEM SHALL log which capability won and emit a structured `task_progress` event with `detail_url` and winning capability.

---

### REQ-3: Real-Time Browser Event Wiring & Zero-Lag Frontend Reactivity
**User Story:** As a user viewing the in-app browser or chat window, I want live crawler and vision actions rendered seamlessly and instantaneously through the existing browser navigation overlay, lifecycle chip, and ambient crawl tier, so that the curated frontend UX reacts dynamically without lag.

**Verified:** Traced against `hooks/useBrowserNavOverlay.ts:186-238`, `components/iris/browser/BrowserNavigationOverlay.tsx:50-84`, `components/iris/browser/VisionLifecycleChip.tsx:33-47`, and `components/iris/AmbientCrawlTier.tsx:100-123`.

**Acceptance Criteria:**
- AC3.1: THE SYSTEM SHALL emit all standard crawler lifecycle events over WebSocket without buffering or polling delays (`iris:crawler_started`, `iris:crawler_page_fetched`, `iris:crawler_complete`, `iris:crawler_error`).
- AC3.2: FOR EVERY vision action executed in `BrowserSession`, THE SYSTEM SHALL emit `CRAWLER_VISION_ACTION` via `tool_bridge.py` containing `kind`, `action_index`, `total`, `x`, `y`, `scroll_y`, `scroll_height`, `viewport_w`, `viewport_h`, and `escalated`.
- AC3.3: THE SYSTEM SHALL ensure the frontend overlay consumes `iris:crawler_vision_action` immediately on its client rAF loop. UNDER rapid-fire action emissions ($\ge 3\text{ actions/sec}$), THE SYSTEM SHALL apply Saccadic Acceleration (compressing cursor glide duration from 620ms down to $\le 180\text{ms}$ or snapping with a particle burst), guaranteeing the cursor stays locked to the agent's live action point without queuing or animation lag.
- AC3.4: THE SYSTEM SHALL emit `iris:vision_status` carrying `{ status: "lifecycle", state: "cold" | "spawning" | "warm" | "error", reason?: str }` to drive the `VisionLifecycleChip` in the browser header.
- AC3.5: THE SYSTEM SHALL ensure all frames published by `BrowserSession.settle()` write to reserved capture slots (`/capture/<job>/<offset+2>.html`), ensuring the live iframe never requests unallocated or 404 capture addresses.

---

### REQ-4: Human-Like Intent at Machine Speed (Instant Target Teleports & Filling)
**User Story:** As an operator, I want the agent's vision interactions to execute with human-like intent and precision at machine speed, so that tasks complete rapidly without artificial human typing or scrolling delays.

**Verified:** Traced against `backend/vision/browser_session.py:462-580`.

**Acceptance Criteria:**
- AC4.1: THE SYSTEM SHALL capture screenshots using browser-scoped Chromium frames (`page.screenshot(type="png")`). WHERE `GoalAnatomy.target` declares a specific visual container or table, THE SYSTEM SHALL crop directly around that bounding box to optimize VLM OCR resolution while cutting token latency.
- AC4.2: THE SYSTEM SHALL calculate the perceptual visual delta between consecutive screenshots. IF an action results in $\text{delta} < 0.05$ or targets the same element twice consecutively, THEN THE SYSTEM SHALL prompt the model with an explicit negative constraint prohibiting that action.
- AC4.3: WHEN navigating to an element or reading a page, THE SYSTEM SHALL execute **Instant Teleport Scrolling**:
  - Uses `locator.scroll_into_view_if_needed()` to align target elements immediately.
  - For page reading, executes `window.scrollBy(0, delta)` instantaneously and allows a minimal micro-settle ($\le 100\text{--}200\text{ms}$) for lazy-loaded DOM assets to hydrate without artificial multi-second scroll animation loops.
- AC4.4: PRIOR to clicking an interactive element, THE SYSTEM SHALL extract the bounding box center and emit normalized `(x, y)` coordinates on `CRAWLER_VISION_ACTION` before dispatching `locator.click()`, allowing the frontend particle cursor to smoothly animate the gesture.
- AC4.5: WHEN entering text into forms or search inputs, THE SYSTEM SHALL use **Instant Input Filling** (`locator.fill(value)`), firing native `input` and `change` events in 1ms rather than artificial character-by-character delays.

---

### REQ-5: Overlay & Modal Interception Auto-Dismissal
**User Story:** As an automation supervisor, I want intercepting cookie banners, newsletter overlays, and age gates auto-dismissed when they block clicks, so that the agent does not stall on intrusive web modals.

**Verified:** NEW

**Acceptance Criteria:**
- AC5.1: IF an attempted click on a target locator raises a Playwright `ElementClickInterceptedError`, THEN THE SYSTEM SHALL automatically trigger the `OverlayDismissal` handler in `BrowserSession`.
- AC5.2: THE SYSTEM SHALL attempt overlay dismissal in strict sequence:
  1. Issues an instant `page.keyboard.press("Escape")`.
  2. Queries for dismissal locators matching: `DISMISS_SELECTORS = ["button:has-text('Accept')", "button:has-text('I Agree')", "button:has-text('Close')", "[aria-label='Close']", "[data-testid*='close']"]`. If found, clicks the dismissal element.
  3. If persistent and non-essential, executes `page.evaluate("document.querySelectorAll('.modal-backdrop, [class*=\"overlay\"], [class*=\"cookie\"]').forEach(el => el.style.display = 'none')")`.
- AC5.3: UPON successful overlay dismissal, THE SYSTEM SHALL immediately retry the original target action and record `dismissed_overlay` in `ActionTrajectory`.

---

### REQ-6: Multi-Tab & Popup Window Auto-Adoption
**User Story:** As an automated browser driver, I want links that open in new windows or popups (`target="_blank"`) to be automatically tracked and adopted, so that the agent does not lose context when clicking external or child links.

**Verified:** NEW

**Acceptance Criteria:**
- AC6.1: `BrowserSession` SHALL register an async listener for `context.on("page", self._on_new_page)` upon `open()`.
- AC6.2: WHEN a click or navigation action causes a new page/tab to open in Playwright, THE SYSTEM SHALL:
  1. Await `new_page.wait_for_load_state("domcontentloaded")`.
  2. Adopt `new_page` as `self._page`.
  3. Close the prior parent tab if the navigation was an external link or auth redirect.
  4. Allocate the next reserved capture slot offset and publish the new frame to `/capture/<job>/<offset+2>.html`.
  5. Emit `CRAWLER_PAGE_FETCHED` with the new page URL so the live iframe updates immediately.

---

### REQ-7: Per-Domain Concurrency Bounding & 429 Circuit Breaking
**User Story:** As a batch crawl coordinator, I want concurrency throttled on a per-host basis, so that parallel batch jobs never trigger HTTP 429 (Too Many Requests) or IP bans on target domains.

**Verified:** NEW

**Acceptance Criteria:**
- AC7.1: WHILE executing batch tool calls across $N$ URLs, THE SYSTEM SHALL enforce a global batch concurrency limit (10) AND a per-host concurrency limit of at most 2 concurrent requests to the *same* domain name using a per-domain semaphore (`host_semaphores[netloc] = asyncio.Semaphore(2)`).
- AC7.2: IF a request to a host returns HTTP status 429, 503, or a rate-limit challenge twice consecutively, THEN THE SYSTEM SHALL activate the **Host Circuit Breaker**:
  1. Pauses pending requests to that host for an initial backoff window with exponential jitter ($2\text{s} \pm 500\text{ms}$).
  2. If subsequent attempts fail, marks remaining batch items for that host as `status="rate_limited"` without crashing the remaining batch queue.
  3. Logs a structured `WARNING` event to `memory.db` recording the domain backoff.

---

### REQ-8: Strict Schema Projection & Context Memory Bounding
**User Story:** As the memory subsystem, I want batch findings pruned strictly to declared schema fields before saving to plan context, so that multi-URL research tasks never saturate the LLM context window.

**Verified:** NEW

**Acceptance Criteria:**
- AC8.1: WHEN a batch extraction completes, `StepFindingsAccumulator` SHALL apply **Strict Schema Projection**:
  - Drops all raw HTML, full-text boilerplate, and non-schema DOM nodes.
  - Retains ONLY the extracted JSON object conforming to `GoalAnatomy.schema` and tagged entity identifiers.
- AC8.2: THE SYSTEM SHALL enforce a hard memory bound of $\le 5\text{KB}$ per completed batch item in `accumulated_context`.
- AC8.3: IF total accumulated findings across all steps exceed 32KB, THE SYSTEM SHALL apply hierarchical extractive summarization to preserve key entity anchors within token limits.

---

### REQ-9: Hybrid Adversarial SEO & Affiliate Trap Filtering
**User Story:** As the search discovery engine, I want low-quality content farms, affiliate spam links, and AI parasite scrapers filtered out before crawling, so that compute is spent only on authoritative sources.

**Verified:** Traced against `backend/vision/search_discovery.py:172-250`.

**Acceptance Criteria:**
- AC9.1: In `search_discovery.py`, candidate URLs harvested from search engine results SHALL be evaluated through a **Hybrid Adversarial SEO Filter**:
  - *Tier A (Fast Heuristic Rejection):* Drops URLs matching known affiliate query parameters (`aff_id`, `tag`, `click_id`, `ref`, `subid`, `afftrack`), redirect paths (`/out.php`, `/go/`), or spam TLDs.
  - *Tier B (Semantic Relevancy & Parasite Detection):* Evaluates title and snippet keyword density; penalizes keyword stuffing (density $> 0.35$); detects parasite SEO patterns (e.g. coupon aggregators hosting reviews).
- AC9.2: Harvested candidate URLs SHALL be dynamically re-ranked, prioritizing direct manufacturer domains, official documentation sites, primary sources, and verified technical publications.

---

### REQ-10: Interactive Human-in-the-Loop Takeover via `AskUserQuestion`
**User Story:** As an operator, I want the agent to explain why takeover is needed and let me resolve complex checkpoints (e.g. 2FA prompts, SMS codes, or complex captchas) directly in the browser panel, so that the task can continue without failing.

**Verified:** Traced against `backend/agent/tools/ask_user_tool.py:41-60`.

**Acceptance Criteria:**
- AC10.1: WHEN `BrowserSession` encounters an unresolvable bot wall, 2FA prompt, or login checkpoint, THE SYSTEM SHALL trigger Takeover Mode via `AskUserQuestion`:
  - Instantiates `Question` with `kind="browser_takeover"`, `takeover_url=page.url`, and a descriptive message generated from the page context (e.g. *"Please solve the Cloudflare verification challenge on [Site Name] in the browser panel."*).
  - Emits `iris:browser_takeover_requested` with `{ takeover_url, job_id, reason }`.
  - Temporarily sets `pointer-events: auto` on the in-app browser panel container in `BrowserNavigationOverlay.tsx`.
- AC10.2: The frontend `QuestionCard` and `AmbientCrawlTier` SHALL render an interactive prompt with a primary action button: *"I've Completed It"*.
- AC10.3: UPON the user clicking *"I've Completed It"*, `AskUserQuestion` SHALL resolve with `answer="completed"`, `BrowserSession` SHALL re-arm `pointer-events: none` on the overlay, evaluate the resulting page state to confirm the obstacle is cleared, capture the new settled frame, and resume automation without restarting the plan.

---

### REQ-11: Semantic Cross-Source Fact & Price Verification Gate
**User Story:** As a research client, I want extracted prices and core factual specifications verified across multiple independent sources with intelligent context awareness, so that the final answer accounts for bundling, currency, and condition differences.

**Verified:** Traced against `backend/agent/der_loop.py:StepFindingsAccumulator`.

**Acceptance Criteria:**
- AC11.1: For tasks typed `DATA_EXTRACTION` where `GoalAnatomy.fields` contains critical numerical or factual properties (e.g. `price`, `release_date`, `model_number`), THE SYSTEM SHALL activate the **Cross-Source Verification Gate**.
- AC11.2: A field value SHALL be marked `verified=True` ONLY IF it is corroborated across at least 2 distinct authoritative domain names in the crawl set.
- AC11.3: The verification resolver SHALL apply **Semantic Normalization**:
  - Reconciles currencies using standard conversion rates.
  - Distinguishes product condition (e.g. New vs Refurbished) and offerings (e.g. Standalone MSRP vs Bundle deals with bundled games/accessories).
- AC11.4: IF sources report irreconcilable numbers (e.g. Official Store MSRP = $1,999 vs Scalper Marketplace = $2,499), THE SYSTEM SHALL mark `verified=False`, `discrepancy=True`, record all claims with source citations and context notes, and highlight the discrepancy clearly in the final task card.

---

### REQ-12: Secure Session & Cookie Injection via OS Keyring with HAR Redaction
**User Story:** As a user, I want the browser agent to authenticate with my private accounts using secure session cookies stored in my OS keyring, so that the agent accesses my personalized data without ever seeing or typing my password.

**Verified:** Traced against `backend/vision/browser_session.py:open()` and `backend/crawler/crawl_runner.py:_write_har_file`.

**Acceptance Criteria:**
- AC12.1: WHERE a task target domain matches a configured authenticated site, `BrowserSession` SHALL retrieve stored session cookies from the OS Keyring via `keyring.get_password("iris_voice_sessions", domain)`.
- AC12.2: Retrieved cookies SHALL be parsed from JSON and injected into Playwright via `await context.add_cookies(cookies)`.
- AC12.3: In `backend/crawler/crawl_runner.py:_write_har_file` and `capabilities.py`, THE SYSTEM SHALL sanitize all exported HAR evidence: any header with key matching `(?i)^(cookie|set-cookie|authorization|x-auth-token|proxy-authorization)$` SHALL have its value replaced with `"[REDACTED]"`. Session tokens SHALL never appear in VLM prompt payloads or transcripts.

---

### REQ-13: Dynamic Real-Time Multi-Angle Query Synthesis & Adaptation
**User Story:** As the research planner, I want the Brain agent to intelligently synthesize multiple orthogonal search queries that adapt in real time as discoveries are made, so that research thoroughly covers the topic without rigid hardcoded templates.

**Verified:** Traced against `backend/core_models.py` and `backend/agent/der_loop.py`.

**Acceptance Criteria:**
- AC13.1: The Brain agent SHALL dynamically analyze the user request, intent, and domain context to synthesize 2–4 orthogonal query facets covering distinct dimensions (e.g. technical specifications, pricing & availability, independent benchmarks, community-reported issues, or regulatory filings).
- AC13.2: The initial query set SHALL be enqueued as a composite `BatchToolCall` executed concurrently in the DER DAG.
- AC13.3: **In-Flight Query Adaptation:** During batch crawl execution, as intermediate findings accumulate in `StepFindingsAccumulator`:
  - If a key field in `GoalAnatomy.schema` remains empty or ambiguous after initial URLs are processed, the Brain agent SHALL dynamically synthesize targeted follow-up queries.
  - If unexpected layout shifts or domain blocks occur, the Brain agent SHALL mutate the query strategy in real time to seek alternative source domains.
- AC13.4: Findings from all query branches SHALL be merged, deduplicated by normalized URL, and structured into the findings accumulator.

---

### REQ-14: Semantic Temporal Snapshot Diffing via Document Store
**User Story:** As a monitoring agent, I want to compare current page content against past snapshots in the document store and explain what changed in natural language, so that I can report exact pricing or text changes over time.

**Verified:** Traced against `backend/agent/document_store.py:28-40` and `backend/crawler/capture_store.py`.

**Acceptance Criteria:**
- AC14.1: When crawling a URL, `BrowserSession` SHALL query `DocumentDataStore` using `document_id = f"url_snapshot:{sha256(canonical_url)[:16]}"` to retrieve any past snapshot.
- AC14.2: IF a prior snapshot exists, THE SYSTEM SHALL compute **Semantic Temporal Diffs**:
  - Compares structured schema fields (e.g. price, stock availability, spec values) and generates natural-language delta statements (*"Price dropped from $1,999 to $1,799 (-10%)"*, *"In Stock status changed to Sold Out"*).
  - Highlights modified policy sections or newly added specifications.
- AC14.3: Extracted deltas SHALL be encapsulated in a `TemporalDelta` object and rendered as visual change pills in `TaskListCard.tsx`.
- AC14.4: THE SYSTEM SHALL save the newly settled content into `DocumentDataStore` with `revision = prior.revision + 1`.

---

### REQ-15: Native PDF & Technical Document Deep Extraction (`fetch.pdf`)
**User Story:** As a research agent, I want PDF document URLs extracted via a fast native document pipeline, so that multi-page whitepapers and spec sheets are parsed in seconds without browser scrolling.

**Verified:** Traced against `backend/crawler/capabilities.py:409-450`.

**Acceptance Criteria:**
- AC15.1: IF a candidate URL ends in `.pdf` or returns Content-Type `application/pdf`, THE SYSTEM SHALL route the fetch to `fetch.pdf` (`FetchPDFCapability`).
- AC15.2: `fetch.pdf` SHALL download document bytes via `httpx` and parse text/tables directly using PyMuPDF (`fitz`) / `pdfplumber` in $<1.5\text{s}$ for up to 100 pages, bypassing Chromium browser processes.
- AC15.3: WHERE visual inspection of charts or figures is required by `GoalAnatomy.target`, `fetch.pdf` SHALL render ONLY the specific target page as a PNG image (`page.get_pixmap().tobytes("png")`) for VLM inspection.

---

### REQ-16: Dynamic Cost & Latency Tiering (Brain-Managed Routing)
**User Story:** As an operator, I want the Brain agent to dynamically delegate vision and crawl tasks across cost and latency tiers, so that simple extractions complete instantly while complex visual tasks receive full intelligence.

**Verified:** Traced against `backend/inference_router.py:41-70`.

**Acceptance Criteria:**
- AC16.1: The Brain agent SHALL route execution through a 3-tier hierarchy:
  - *Tier 0 (Fastest / Free, ~100ms):* Headless HTTP parse (`fetch.crawl`) handles clean, server-rendered pages.
  - *Tier 1 (Local VLM, ~400ms):* `LFM2.5-VL` handles interactive bot-settling and local micro-actions.
  - *Tier 2 (Cloud Multimodal, ~1.5s):* Cloud Brain model invoked *only* for high-ambiguity visual reasoning or complex multi-page synthesis.
- AC16.2: Tasks with straightforward DOM structures SHALL be fulfilled entirely at Tier 0; bot walls and interactive pages escalate to Tier 1; multi-factor visual ambiguities escalate to Tier 2, slashing multimodal token costs by up to 80%.

---

### REQ-17: Model-Agnostic Dual Vision Routing & Tri-Layer Context
**User Story:** As an operator, I want the system to leverage either the Brain model's native vision or the local vision server VLM, so that I can optimize for cloud intelligence, local privacy, or available GPU VRAM.

**Verified:** Traced against direct binding to `lfm_vl_provider.py` in `backend/vision/fetch_vision.py:308-314`.

**Acceptance Criteria:**
- AC17.1: THE SYSTEM SHALL support three distinct vision execution modes: `MODE_LOCAL_VLM`, `MODE_DIRECT_BRAIN`, and `MODE_COWORKING_HYBRID`.
- AC17.2: THE SYSTEM SHALL maintain an intra-tool `ActionTrajectory` sliding window (last 3 actions, targets, parameters, outcomes, and perceptual visual deltas) and format it into the action suggestion prompt regardless of which model is actively driving.
- AC17.3: IF 3 consecutive no-progress actions occur, THEN THE SYSTEM SHALL immediately terminate the action loop and proceed to DOM settle.

---

### REQ-18: DAG-Native Batch Tool Execution & Concurrency Governance
**User Story:** As the DER execution engine, I want to execute batch tool calls concurrently across DAG nodes with resource-aware governance, so that multi-entity and multi-URL tasks complete rapidly without overloading system resources.

**Verified:** Traced against `all_ready_items()` in `backend/agent/der_loop.py:546-591`.

**Acceptance Criteria:**
- AC18.1: THE SYSTEM SHALL allow the Director to emit composite `BatchToolCall` nodes or parallel `QueueItem` sets in the DER execution DAG where `parallel_safe=True` and `independent=True`.
- AC18.2: THE SYSTEM SHALL govern concurrent tool execution using resource-specific concurrency limiters (Crawl: 10, Vision-VLM: 1-2, Brain-Vis: 4).
- AC18.3: THE SYSTEM SHALL aggregate individual batch item outcomes into a consolidated `BatchOutcome` payload.

---

### REQ-19: Atomic Batch Recording in `memory.db` & Mycelium Graph
**User Story:** As the memory subsystem, I want batch tool executions to write atomically into `memory.db` and the coordinate graph, so that high-throughput batch operations never cause database locks or fragmented records.

**Verified:** Traced against single-record writes in `backend/memory/card_footprint.py:37-60` and `backend/memory/episodic.py:59-120`.

**Acceptance Criteria:**
- AC19.1: THE SYSTEM SHALL persist batch tool execution outcomes using an atomic transaction in `memory.db` (SQLCipher in WAL mode): creates one parent `BatchRecord` and linked child `NodeRecord` entries.
- AC19.2: THE SYSTEM SHALL register the parent `BatchRecord` and high-salience child extractions as episodic coordinates in the Mycelium coordinate graph.
- AC19.3: THE SYSTEM SHALL update the active task card footprint via `save_card_footprint` with aggregated batch metrics in a single non-blocking write.

---

### REQ-20: Hierarchical Guardrails (Semantic Task-Level vs. Action Allowlist)
**User Story:** As an automation safety supervisor, I want semantic task guardrails evaluated before element role allowlists, so that the agent is prevented from dangerous operations like making unauthorized purchases or leaving the target domain.

**Verified:** Traced against element-role-only checking in `backend/vision/action_allowlist.py:56-82`.

**Acceptance Criteria:**
- AC20.1: THE SYSTEM SHALL evaluate `TaskGuardrails` prior to calling `ActionAllowlist.validate_action` on every proposed action in `fetch_vision`.
- AC20.2: THE SYSTEM SHALL enforce standard declarative semantic guardrails (`NO_PURCHASE`, `DOMAIN_BOUND`, `MAX_DEPTH`, `NO_EXTERNAL_AUTH`).
- AC20.3: WHEN an action violates a task guardrail, THE SYSTEM SHALL block execution, record `rejected_guardrail` in the `ActionTrajectory`, and re-prompt the vision driver with a negative constraint.

---

### REQ-21: Schema-Driven Structured Extraction with 12-Keyword Allowlist
**User Story:** As an extraction client, I want web extraction to strictly enforce a validated JSON schema contract, so that output data requires no post-hoc parsing or sanitization.

**Verified:** Traced against unstructured `expected_output: Optional[str]` at `backend/core_models.py:727` and unbounded `read_text` at `backend/tools/lfm_vl_provider.py:2218`.

**Acceptance Criteria:**
- AC21.1: THE SYSTEM SHALL validate all declared `output_schema` definitions against a strict 12-keyword allowlist:
  - `type`, `properties`, `required`, `items`, `enum`, `format`, `minItems`, `maxItems`, `minimum`, `maximum`, `nullable`, `propertyOrdering`.
- AC21.2: THE SYSTEM SHALL reject unsupported keywords (`oneOf`, `additionalProperties`, `const`, `allOf`, `$ref`) with explicit 400 validation errors before tool execution.
- AC21.3: THE SYSTEM SHALL validate the extracted model payload against `output_schema`; IF validation fails, THE SYSTEM SHALL execute at most one self-correction pass specifying the validation error to the model.

---

### REQ-22: Enriched Task Progress Streaming & Dual-Mode UI Integration
**User Story:** As a user in Personal or Developer Mode, I want real-time task progress enriched with live tool calls, target URLs, phase transitions, and output summaries, so that I have complete visibility into the agent's work.

**Verified:** Traced against `hooks/useTaskProgress.ts:17-188, 800-1150` and `components/chat/TaskListCard.tsx:23-55`.

**Acceptance Criteria:**
- AC22.1: THE SYSTEM SHALL emit structured task lifecycle and tool events over `EventBus` and WebSocket (`task:start`, `tool:call`, `task:progress`, `tool:result`).
- AC22.2: THE SYSTEM SHALL ensure `hooks/useTaskProgress.ts` reduces these enriched events into `TaskStep` and `TaskCard`, preserving state across component unmounts and retaining `resultPreview` upon completion.
- AC22.3: WHILE in **Personal Mode**, THE SYSTEM SHALL render progress via `TaskListCard.tsx` (Liquid Ink chassis) with natural language status, rotating verbs (`SEARCH` $\rightarrow$ `READ` $\rightarrow$ `EXTRACT` $\rightarrow$ `CITE` $\rightarrow$ `SYNTH`), subtitle URL badges, verified fact badges, temporal diff pills, and bracketed `[done/total]` step counters.
- AC22.4: WHILE in **Developer Mode**, THE SYSTEM SHALL render progress via `components/terminal/terminalScrollback.ts` with Blueprint Matrix walls (`┌──┐` / `├──┤`), Goal Anatomy Inspector, live `ActionTrajectory` sliding window, batch pool status, and cross-verification status matrix.

---

### REQ-23: Websearch System-Memory Baseline & Spike Bound (Measure-First)
**User Story:** As an operator, I want a measured OS-memory baseline for a standardized websearch (idle vs peak vs return-to-idle) so that the "little-to-no spike" expectation is a grounded number rather than an assumption, and regressions are caught automatically.

**Verified:** IMPLEMENTED T34 (harness `backend/scripts/benchmark_websearch_memory.py`; live baseline 2026-09-06 recorded below in AC23.3; bound pinned T36). Precedent pattern traced against `scripts/measure_memory.py:39-84` (`_is_iris_process` / `_mem_mb` / `measure()`) and `scripts/measure_memory.py:24` (`IDLE_BUDGET_GB = 4.0` warm-idle gate).)

**Acceptance Criteria:**
- AC23.1: THE SYSTEM SHALL provide a measurement harness (`backend/scripts/benchmark_websearch_memory.py`) that reuses the `scripts/measure_memory.py` psutil pattern (Private Bytes on Windows, RSS fallback elsewhere; same IRIS process markers including `crawl_worker` and `browser_pool`) to record per-process memory before, at peak during, and after a standardized websearch run (5 URLs via `CrawlOrchestrator.dispatch_urls` at the default `CRAWL_CONCURRENCY=3` — `backend/crawler/orchestrator.py:61`).
- AC23.2: WHEN the harness runs the standardized search, THE SYSTEM SHALL report peak private-memory delta over idle AND return-to-idle delta measured 60s after completion. The pooled browser's full idle shutdown (`IRIS_BROWSER_IDLE_TIMEOUT=180` — `backend/vision/browser_pool.py:55`) is reported as direction at 60s, NOT required to have completed for the check to pass.
- AC23.3: THE SYSTEM SHALL enforce the T36-pinned spike bounds — IRIS peak ≤50MB, IRIS return-to-idle ≤25MB, driver peak ≤350MB (harness defaults, env-overridable via `IRIS_WEBSEARCH_PEAK_DELTA_MB` / `IRIS_WEBSEARCH_RETURN_DELTA_MB` / `DRIVER_WEBSEARCH_PEAK_DELTA_MB`). Pinned 2026-09-06 from the T34 live baseline (5 clean-domain URLs x2 iterations, 5/5 usable, ~3s/iter): IRIS peak +0.0MB / return +0.0MB over a 3742MB idle; driver +292MB peak. The driver figure is a one-time per-process import commit (`backend.crawler.capabilities` → `backend.agent.tool_registry`: numpy/pydantic/agent chain, no torch — isolated by bisection), with ~0MB incremental on the repeat iteration (import-only probe +316MB ≥ full 2-search run +297MB). Driver return is unbounded BY DESIGN (the commit is retained; accumulation across repeats would surface in the peak, which IS bounded).
- AC23.4: WHILE a websearch runs, THE SYSTEM SHALL NOT leave any resident `crawl_worker --serve` subprocess alive after the run (restates the locked memory-optimization REQ-4 AC4.1 as a harness assertion, not new behavior); the harness SHALL fail if a new persistent crawl worker outlives the run.
- AC23.5: IF the measured peak delta exceeds the pinned bound, THEN THE SYSTEM SHALL fail the harness with a per-process table (PID, name, private MB, working-set MB) so the dominant contributor is immediately visible.

**Edge Cases:**
- *Backend not running / no IRIS processes found:* harness reports "no processes" and exits non-zero when an assertion flag is passed (same convention as `measure_memory.py --assert-idle`).
- *Chromium still warm inside the browser_pool idle window:* return-to-idle delta is reported with a pool-warm caveat, not asserted as zero; the sustained post-shutdown delta is bounded separately once measured.
- *First-time vs raced domains:* the standardized run SHALL include at least one clean-domain fetch and SHALL document which URLs raced (`fetch.crawl` vs `fetch.vision`, loser cancelled — `backend/crawler/orchestrator.py:1496-1500`) so race overhead is represented, not hidden.
- *Capture bytes:* `capture_store` is file-backed (`data/captures`, bounded 100 pages / 256MB — `backend/crawler/capture_store.py:79-80`) and SHALL NOT count toward the RSS delta; disk growth is reported separately if at all.
- *Context vs OS memory:* REQ-8's $\le 5\text{KB}$/item and 32KB context bounds are LLM-token memory and are OUT OF SCOPE for this REQ; REQ-23 measures OS process memory only.

---

## Wave 7 — Seam follow-ups (additive 2026-09-07)

Strictly additive: REQ-1..REQ-23 objectives, success criteria, and UX contracts are untouched. Each item below was found modeled-but-unwired during Wave 5 and deliberately deferred — building any of them inside Wave 5 would have widened scope (a scheduler framework, a new dependency, a signature migration, or a test weakening). Each carries file:line grounding.

### REQ-24: DER-Native BatchToolCall Expansion & Per-Resource Governance
**User Story:** As the DER execution engine, I want composite batch nodes to expand into releasable items under per-resource caps, so that multi-URL/multi-entity work runs concurrently without overloading any single resource.

**Verified:** BatchToolCall/BatchOutcome dataclasses at `backend/core_models.py:958-983`; bridge `to_batch_tool_call` / `collect_batch_outcome` at `backend/agent/query_synthesizer.py` (session-302); `all_ready_items` at `backend/agent/der_loop.py:546-591` (batch-agnostic today); per-host cap exists in orchestrator dispatch; vision lease exists (`acquire_vision_lease`).

**Acceptance Criteria:**
- AC24.1: WHEN a DER node carries a `BatchToolCall` with `parallel_safe=True` and `independent=True`, THE SYSTEM SHALL expand it into releasable items through the existing `all_ready_items` path (no new scheduler service).
- AC24.2: WHILE batch items execute, THE SYSTEM SHALL enforce per-tool concurrency caps (Crawl global 10 + per-host 2, Vision-VLM 1-2 via the existing lease, Brain-Vis 4 via a new DER-owned semaphore).
- AC24.3: WHEN all items of a batch node settle, THE SYSTEM SHALL fold outcomes via `collect_batch_outcome` into one `BatchOutcome` on the node.
- AC24.4: IF a batch node is NOT parallel_safe, THE SYSTEM SHALL execute its items sequentially in declared order.

**Edge Cases:**
- Empty `items` → node completes immediately with an empty `BatchOutcome` (never hangs the DAG).
- A single item failure marks that item only; the node completes with partial results (DAG abort rules unchanged).
- Caps are re-entrant across nested dispatches (no self-deadlock: semaphores are per-tool, never per-node).

### REQ-25: Extracted-Payload Validation With One Self-Correction Pass
**User Story:** As an extraction client, I want a malformed extraction to get exactly one automatic fix attempt, so that output data needs no post-hoc parsing in the common case but can never loop forever.

**Verified:** Allowlist `validate_schema` at `backend/vision/schema_validator.py:76-91` (shape of the contract only — no instance checking); fail-closed entry check at `backend/crawler/orchestrator.py` dispatch (session-302); `extract` projection hook consumed per page in dispatch.

**Acceptance Criteria:**
- AC25.1: THE SYSTEM SHALL validate each extracted payload against `output_schema` with a stdlib-only instance checker covering exactly the 12 allowlisted keywords (no new dependency).
- AC25.2: WHEN a payload fails validation, THE SYSTEM SHALL run at most ONE correction pass that re-invokes extraction with the validation error stated in the prompt.
- AC25.3: IF the correction still fails validation, THE SYSTEM SHALL accept the payload as-is, flag the field set as unvalidated on the result, and continue the run (never raise, never retry again).
- AC25.4: WHERE no `output_schema` or no `extract` hook is declared, THE SYSTEM SHALL skip validation entirely (zero cost on the unprojected path).

**Edge Cases:**
- `extract` returns None → treated as missing payload, counted toward coverage as absent (consistent with AC2.3).
- Correction pass is bounded by the existing run ceiling (no separate budget, no new timeout surface).
- Unknown/extra payload keys are dropped by the existing strict projection before validation (validator never sees raw DOM).

### REQ-26: Structured Goal Plumbing (Union Type, Backward Compatible)
**User Story:** As the Brain agent, I want my structured goal (including custom guardrails) to reach the fetcher intact, so that per-task constraints are enforced rather than silently replaced by defaults.

**Verified:** `fetch_one(url, goal: str, ...)` at `backend/vision/fetch_vision.py:258-264`; `dispatch_urls(..., query: str, ...)` and `_race_url(url, goal: str, ...)` in orchestrator; guardrail gate with `["NO_PURCHASE", "DOMAIN_BOUND"]` defaults (session-302); duck-typing contract `backend/tests/contract/test_fetch_vision_goal_contract.py` (GoalAnatomy renders via `__str__`).

**Acceptance Criteria:**
- AC26.1: THE SYSTEM SHALL accept `goal: str | GoalAnatomy` (union) at `dispatch_urls`, `_race_url`, and `fetch_one` without breaking any existing string caller or fake.
- AC26.2: WHEN a `GoalAnatomy` arrives, THE SYSTEM SHALL render it via `__str__`/`to_prompt()` at every edge that speaks to a model or capability (string protocol preserved end to end).
- AC26.3: WHEN a `GoalAnatomy` arrives, THE SYSTEM SHALL feed `goal.guardrails` (not the defaults) into the REQ-20 gate; WHEN a plain string arrives, THE SYSTEM SHALL keep the current defaults.
- AC26.4: THE SYSTEM SHALL pass the existing duck-typing contract suite unchanged (no test modified to accommodate the union).

**Edge Cases:**
- `goal.guardrails` empty/None → defaults apply (fail safe, never fail open).
- Unknown guardrail name → existing fail-closed evaluation already rejects it (no new handling).
- Fakes implementing the bare 3-arg protocol keep working (union is accepted, never required).

### REQ-27: Page/Phase Progress Contract Reconciliation
**User Story:** As a user watching a crawl, I want each fetched page to advance its own progress step, so that cards never sit frozen while pages land.

**Verified:** Page events carry `phase`/`phase_sequence` at `backend/agent/tool_bridge.py:2602-2603` (Session-247 intent: per-page READ nodes); `test_progress_event_shape.py:124-138` asserts the key is ABSENT; `test_crawler_task_progress.py:186` partitions on absence and fails `0 == 2` at HEAD `c5b13352` (proven via detached-worktree rerun, session-302).

**Acceptance Criteria:**
- AC27.1: THE SYSTEM SHALL preserve the Session-247 behavior (page events advance their own step) unless live testing shows a regression, in which case the behavior reverts and the tests stand as written.
- AC27.2: WHEN live testing confirms per-page advancement, THE SYSTEM SHALL lock `detail_url`-presence as the page/phase discriminator (page events carry `detail_url`; phase events never do — already asserted at `test_progress_event_shape.py:167-170`) and update the two stale partition keys to the locked contract.
- AC27.3: THE SYSTEM SHALL keep both tests' strength after the update (page-count and phase-presence assertions unchanged — only the discriminator expression changes, under this spec's authority, not as a silent weakening).

**Edge Cases:**
- Live testing shows frozen/duplicated steps → REQ-27 resolves to Option B (strip `phase` from page events); the tests then pass unmodified and this REQ records the revert instead.
- Mixed streams with takeover/parks keep partitioning correctly under the locked discriminator (covered by the updated suites).

### REQ-28: Application Memory Envelope (idle low, zero per-task growth, functionality preserved)
**User Story:** As an operator, I want the app's idle footprint small and per-task memory flat, so that the assistant can sit in the tray all day without bloating the machine — while first-use responsiveness never regresses.

**Verified:** Backend main ~1.46GB + tts_worker ~2.3GB commit (~331MB resident) + llama-server ~345MB RSS ≈ 3.74GB idle floor (session-296/299 pins) vs the 2.5GB idle gate it breaches; warm-idle gate `IDLE_BUDGET_GB = 4.0` at `scripts/measure_memory.py:24`; websearch incremental ~0MB proven twice (T34 baseline + session-302 rerun: driver +297MB one-time import commit, ~0MB per repeat); TTS ~900MB transient native spike at encode finalization with ~0.9GB reclaim potential via short-lived helpers (session-300 pin); ~238s first-utterance cold start is what forced boot-time early-spawn (`d8941516`).

**Acceptance Criteria:**
- AC28.1: WHILE the app is idle (no active turn, no playback), THE SYSTEM SHALL hold total committed memory ≤2.5GB (restores the breached gate; measured floor today ≈3.7GB).
- AC28.2: WHILE synthesizing speech repeatedly, THE SYSTEM SHALL show no monotonic growth: 10 consecutive syntheses SHALL grow worker private bytes by ≤50MB (leak gate).
- AC28.3: WHEN the user requests the first utterance of a session, THE SYSTEM SHALL begin audible playback within 30s (functionality floor — the 238s failure must never return).
- AC28.4: THE SYSTEM SHALL keep the encode-finalization transient spike ≤500MB (down from ~900MB) or document with measurements why the native side cannot be moved.

**Edge Cases:**
- Respawn race (two speaks while worker is down) → singleflight spawn: exactly one worker, both speaks queue behind readiness.
- Respawn failure → explicit TTS-degraded error; chat and all other tools unaffected.
- Measurement reuses the `measure_memory.py` pattern (Private Bytes on win32) plus worker-log markers, so the gate runs the same way in CI and live.

---

## Non-Requirements (Out of Scope)

- **Automated CAPTCHA / Bot-Challenge Solving:** In compliance with REQ-19 AC5 of `vision-browser-websearch`, challenges are detected, parked, and reported to the user (or routed to User Takeover Mode via `AskUserQuestion`), never bypassed with black-hat solvers.
- **Headful Desktop Window Driving:** Automation targets headless Chromium inside the backend Playwright container; hijacking native desktop browser windows is excluded.
- **Simulated Human Slowness:** Artificial typing delays, mouse dragging pauses, or slow incremental scroll animations are explicitly excluded in favor of instant headless execution and client-side reactive rendering.
- **Full JSON Schema Specification Coverage:** Advanced meta-schemas, recursive `$ref`, and pattern properties are explicitly excluded in favor of the strict 12-keyword allowlist.

---

## Open Questions

- *OQ-1: Should batch execution support dynamic speculative pre-fetching for discovered candidate links?* (Recommendation: Deferred to follow-up; keep batch execution deterministic based on DAG plan nodes first).
- *OQ-2: Should Developer Mode allow inline editing of `GoalAnatomy` parameters during paused/breakpoint states?* (Recommendation: Yes, planned for Dev Mode Phase 2).
- *OQ-3 (REQ-27, resolves during live testing):* Do per-page progress steps render correctly (advance once per page, no duplicates)? YES → lock the `detail_url` discriminator and update the two stale tests under REQ-27 authority. NO → revert tool_bridge to phase-less page events; the tests stand as written.
- *OQ-4 (REQ-28, RESOLVED 2026-09-07):* User locked lazy-at-boot + pre-warm-on-connect + idle-unload/respawn for smallest idle. Amending the gate upward was rejected.

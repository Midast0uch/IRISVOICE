# Tasks: Progressive WebSearch, In-App Browser & Vision System

> Each task links to requirements. Waves are dependency-ordered; Wave 1 is foundation, Wave 2 integrates visual interaction, Wave 3 implements concurrent execution, Wave 4 deploys the micro-dispatcher and telemetry.

---

## Wave 1 — Foundation: Instant Search & Event Forwarding

- [ ] T1 (REQ-1): Implement lightweight HTTP REST search provider in `backend/crawler/search_providers.py` supporting SearXNG/Brave/DuckDuckGo Lite with structured markdown output. — RIPPLE: Zero browser subprocesses launched; isolated network module.
- [ ] T2 (REQ-1): Decouple `_execute_web_search` in `backend/agent/tool_bridge.py:3459` to invoke `search_providers.py` and populate `requires_deep_crawl` flag when snippets are truncated (<300 chars). — RIPPLE: Replaces `CrawlOrchestrator` call in `search` while keeping `crawler_query` intact.
- [ ] T3 (REQ-4): Update progress forwarder in `backend/crawler/orchestrator.py:1290` to forward `CRAWLER_VISION_ACTION` WebSocket events instead of discarding non-page events. — RIPPLE: Unblocks streaming path to `BrowserNavigationOverlay.tsx`.
- [ ] TG-1 (Wave 1 Gate): Run unit and contract tests proving AC1.1–1.4 and AC4.2 green. Verify `search` completes in <400ms.

---

## Wave 2 — Set-of-Marks & Particle Cursor Animation

- [ ] T4 (REQ-3): Implement CDP accessibility tree extraction and visual Set-of-Marks badge overlay (`[1]`, `[2]`, `[3]`) in `backend/vision/fetch_vision.py` with discrete element ID action parsing. — RIPPLE: Extends vision observation pipeline without breaking existing image logging.
- [ ] T5 (REQ-3): Implement bounding box ground-truth center resolution `(cx, cy)` and Playwright CDP click/type dispatch at exact center in `backend/vision/fetch_vision.py`. — RIPPLE: Replaces heuristic DOM text search with exact element bounding box coordinates.
- [ ] T6 (REQ-4): Implement pre-action glide event emission in `backend/vision/fetch_vision.py:477-510` emitting `CRAWLER_VISION_ACTION` (`approaching`, normalized `visionX`, `visionY`, 180ms duration) prior to action execution, followed by `completed` burst event. — RIPPLE: Drives saccadic particle glide in `BrowserNavigationOverlay.tsx`.
- [ ] T12 (REQ-8): Implement autonomous in-app browser search provider in `backend/crawler/search_providers/browser_search.py` supporting human-like typing (40–110ms delays), multi-page SERP harvesting (pages 1–4), SEO/spam filtering, and handoff of top 3–5 clean URLs to headless crawl via `credibility.py`. — RIPPLE: Eliminates dependency on `EXA_API_KEY` and LLM training hallucinations.
- [ ] TG-2 (Wave 2 Gate): Run tests proving AC3.1–3.5, AC4.1, AC4.3, AC4.4, and AC8.1–8.5 green. Verify particle cursor animation, anti-bot typing, and SERP harvesting.

---

## Wave 3 — Caducean Concurrency & Goal Propagation

- [ ] T7 (REQ-2): Implement Caducean dual-wave browser session attachment in `backend/crawler/orchestrator.py` allowing Wave 1 (Headless DOM, $\theta_1 = 0^\circ$) and Wave 2 (Vision Inspector, $\theta_2 = 180^\circ$) to run concurrently on the same CDP session with phase repulsion $\sin(\theta_i - \theta_j)$. — RIPPLE: Governed by `docs/CADUCEAN_CONCURRENCY_MODEL.md`.
- [ ] T8 (REQ-5): Verify and bind `NodeRecord` memory contract across web search tools in `backend/agent/der_loop.py` and `backend/agent/inter_model_communication.py`, ensuring `objective_anchor`, `expected_output`, `content_summary`, `remaining`, and `folded_back` are strictly propagated. — RIPPLE: Prevents search goal degradation across multi-agent hops.
- [ ] T13 (REQ-9): Implement canonical URL normalizer (stripping tracking parameters, fragments, trailing slashes), exclusion filtering (`visited_urls`, `NodeRecord.ruled_out`, document store), and bounded query refinement (`MAX_SEARCH_REFINEMENTS = 3`) in `backend/crawler/search_providers/browser_search.py` and `backend/agent/agent_kernel.py:14438`. — RIPPLE: Prevents redundant URL crawling and circular search loops.
- [ ] TG-3 (Wave 3 Gate): Run concurrent tests proving AC2.1–2.4, AC5.1–5.5, and AC9.1–9.5 green. Verify no duplicate URL fetches and bounded refinement termination.

---

## Wave 4 — Decision Engine Micro-Dispatcher & Observability

- [ ] T9 (REQ-6): Integrate resident `LFM2-350M-Extract` as micro-dispatcher in `backend/agent/decision_engine.py`, implementing sub-50ms action selection and fast-path short-circuit check evaluating `content_summary` against `expected_output`. — RIPPLE: CPU-only forward pass; avoids calling large Brain LLM for intermediate micro-steps.
- [ ] T10 (REQ-6): De-bias memory lookup in `backend/agent/agent_kernel.py:14187` so web goals route to instant `search` first instead of automatically forcing `crawler_query`. — RIPPLE: Restores progressive escalation tiering.
- [ ] T11 (REQ-7): Implement structured latency and event telemetry in `backend/crawler/orchestrator.py` logging search/crawl latency, vision steps, cursor events, and phase angles off the critical path. — RIPPLE: Observability only; no blocking I/O.
- [ ] TG-4 (Wave 4 Gate): Run tests proving AC6.1–6.4 and AC7.1–7.3 green. Verify end-to-end web search latency and telemetry logging.

---

## Wave 5 — Autonomous Media Ingestion & Timestamp Keyframes

- [ ] T14 (REQ-10): Implement audio-only stream extraction (`format: "bestaudio/best"`) in `backend/agent/media_source.py` and pass active Playwright Chromium browser session cookies from `backend/browser/chromium_browser_manager.py` to `yt-dlp`. — RIPPLE: Accelerates media download to <5s and bypasses YouTube bot sign-in challenges.
- [ ] T15 (REQ-10): Implement transcript-guided visual keyframe extraction in `backend/tools/media_tools.py` (`extract_keyframes_at_timestamps` and `analyze_video_frames(timestamps=...)`), restricting vision analysis to identified slide/diagram timestamps (≤ 10 frames). — RIPPLE: Prevents 1fps frame explosion and GPU context exhaustion.
- [ ] T16 (REQ-10): Implement YouTube search, video candidate selection via Set-of-Marks, and canonical video URL handoff in `backend/crawler/search_providers/browser_search.py`. — RIPPLE: Connects in-app browser navigation directly to media ingestion.
- [ ] TG-5 (Wave 5 Gate): Run behavioral tests proving AC10.1–10.5 green. Verify audio downloads in <5s and keyframes extracted at targeted timestamps.

---

## Traceability Matrix (MANDATORY — every AC accounted for)

| REQ | AC | Covering Tasks | Covering Tests | Status |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-1** | AC1.1 | T1 | `tests/unit/test_search_providers.py::test_http_provider_no_browser` | covered |
| **REQ-1** | AC1.2 | T1 | `tests/behavioral/test_search_latency.py::test_sub_400ms_response` | covered |
| **REQ-1** | AC1.3 | T1 | `tests/unit/test_search_providers.py::test_markdown_formatting` | covered |
| **REQ-1** | AC1.4 | T2 | `tests/contract/test_tool_bridge_search.py::test_requires_deep_crawl_flag` | covered |
| **REQ-2** | AC2.1 | T7 | `tests/contract/test_caducean_browser.py::test_shared_cdp_attachment` | covered |
| **REQ-2** | AC2.2 | T7 | `tests/unit/test_caducean_phase.py::test_dual_wave_phase_angles` | covered |
| **REQ-2** | AC2.3 | T7 | `tests/behavioral/test_dual_wave_execution.py::test_parallel_dom_and_visual` | covered |
| **REQ-2** | AC2.4 | T7 | `tests/unit/test_caducean_phase.py::test_phase_repulsion_no_action_clash` | covered |
| **REQ-3** | AC3.1 | T4 | `tests/unit/test_som_extraction.py::test_accessibility_tree_elements` | covered |
| **REQ-3** | AC3.2 | T4 | `tests/unit/test_som_extraction.py::test_numeric_badge_overlay` | covered |
| **REQ-3** | AC3.3 | T4 | `tests/contract/test_vlm_action_parse.py::test_discrete_id_parsing` | covered |
| **REQ-3** | AC3.4 | T5 | `tests/unit/test_som_extraction.py::test_ground_truth_box_center` | covered |
| **REQ-3** | AC3.5 | T5 | `tests/behavioral/test_playwright_action.py::test_exact_center_click` | covered |
| **REQ-4** | AC4.1 | T6 | `tests/contract/test_vision_cursor_events.py::test_pre_glide_event_payload` | covered |
| **REQ-4** | AC4.2 | T3 | `tests/contract/test_crawler_forwarder.py::test_vision_action_not_dropped` | covered |
| **REQ-4** | AC4.3 | T6 | `tests/behavioral/test_cursor_overlay.py::test_saccadic_glide_animation` | covered |
| **REQ-4** | AC4.4 | T6 | `tests/contract/test_vision_cursor_events.py::test_completion_burst_event` | covered |
| **REQ-5** | AC5.1 | T8 | `tests/unit/test_der_memory.py::test_objective_anchor_immutable` | covered |
| **REQ-5** | AC5.2 | T8 | `tests/contract/test_inter_model_comm.py::test_tool_request_intent_preserved` | covered |
| **REQ-5** | AC5.3 | T8 | `tests/unit/test_der_memory.py::test_content_summary_and_remaining_update` | covered |
| **REQ-5** | AC5.4 | T8 | `tests/unit/test_der_memory.py::test_vision_folded_back_findings` | covered |
| **REQ-5** | AC5.5 | T8 | `tests/unit/test_der_memory.py::test_unified_in_memory_mutation` | covered |
| **REQ-6** | AC6.1 | T9 | `tests/unit/test_decision_micro_dispatcher.py::test_sub_50ms_forward_pass` | covered |
| **REQ-6** | AC6.2 | T9 | `tests/unit/test_decision_micro_dispatcher.py::test_expected_output_evaluation` | covered |
| **REQ-6** | AC6.3 | T9 | `tests/behavioral/test_short_circuit_gate.py::test_instant_synthesis_bypass` | covered |
| **REQ-6** | AC6.4 | T10 | `tests/behavioral/test_decision_routing.py::test_visual_roadblock_sub_50ms` | covered |
| **REQ-7** | AC7.1 | T11 | `tests/unit/test_telemetry.py::test_web_turn_latency_log_format` | covered |
| **REQ-7** | AC7.2 | T11 | `tests/unit/test_telemetry.py::test_phase_angles_in_ledger` | covered |
| **REQ-7** | AC7.3 | T11 | `tests/unit/test_telemetry.py::test_short_circuit_telemetry_counter` | covered |
| **REQ-8** | AC8.1 | T12 | `tests/behavioral/test_browser_search.py::test_anti_bot_human_typing` | covered |
| **REQ-8** | AC8.2 | T12 | `tests/behavioral/test_browser_search.py::test_multi_page_serp_harvest` | covered |
| **REQ-8** | AC8.3 | T12 | `tests/unit/test_browser_search.py::test_seo_spam_filtering` | covered |
| **REQ-8** | AC8.4 | T12 | `tests/unit/test_credibility.py::test_rank_candidate_authoritative_urls` | covered |
| **REQ-8** | AC8.5 | T12 | `tests/behavioral/test_browser_search.py::test_headless_crawl_handoff` | covered |
| **REQ-9** | AC9.1 | T13 | `tests/behavioral/test_search_refinement.py::test_query_mutation_on_unresolved_remaining` | covered |
| **REQ-9** | AC9.2 | T13 | `tests/unit/test_url_canonicalization.py::test_strip_tracking_params_and_fragments` | covered |
| **REQ-9** | AC9.3 | T13 | `tests/unit/test_url_deduplication.py::test_exclude_visited_and_ruled_out_urls` | covered |
| **REQ-9** | AC9.4 | T13 | `tests/behavioral/test_search_refinement.py::test_pagination_escalation_on_exhausted_page` | covered |
| **REQ-9** | AC9.5 | T13 | `tests/behavioral/test_search_refinement.py::test_max_refinements_circling_guard` | covered |
| **REQ-10** | AC10.1 | T14 | `tests/unit/test_media_source.py::test_audio_only_stream_format` | covered |
| **REQ-10** | AC10.2 | T14 | `tests/contract/test_media_source_cookies.py::test_chromium_cookie_handoff` | covered |
| **REQ-10** | AC10.3 | T15 | `tests/behavioral/test_media_tools.py::test_transcript_correlated_timestamps` | covered |
| **REQ-10** | AC10.4 | T15 | `tests/unit/test_media_tools.py::test_analyze_video_frames_explicit_timestamps` | covered |
| **REQ-10** | AC10.5 | T16 | `tests/behavioral/test_browser_search.py::test_youtube_search_and_url_handoff` | covered |

**Matrix Audit:**
- Counted ACs in requirements.md: 44
- Matrix rows: 44
- Covered: 44
- Deferred: 0
- Unmapped: 0

---

## Dependency & Parallelization Notes

- **Wave 1 vs Wave 2:** Wave 1 (backend HTTP search provider and orchestrator forwarder) and Wave 2 (frontend/vision Set-of-Marks and coordinate math) can be implemented completely in parallel.
- **Wave 3 dependencies:** Wave 3 depends on Wave 1 and Wave 2 being green, as Caducean concurrency couples the CDP session established in Wave 1 with the vision tools established in Wave 2.
- **Wave 4 dependencies:** Wave 4 integrates the resident Decision Engine micro-dispatcher and de-biasing, depending on the unified pipeline from Wave 3.

# Tasks: Tool-Result Envelope & Drift-Gated Coordination

> Each task links to a requirement. Waves are dependency-ordered; Wave 1 is fully
> independent of Waves 2-3 and may land first. Backend is DOWN (verified — no listener
> on :8000); Wave 4 restarts it via start-backend.py. Branch:
> feat/agent-multi-step-tool-execution (uncommitted session-312 changes present —
> envelope work builds ON TOP of them; never stash).
>
> Session-318 amendment: Waves 1-3 DONE (T1-T10, TG-1..TG-3 green, 66/66 tests).
> T11 live probe (conv-102) verdict FAIL — one wiki seed dispatched 3x (~110/90/82s),
> identical bodies counted fresh 3x, a 404 read 2x; guard 0 / streak 0 / gather-filtered 0;
> honest single-source answer (no hallucinated citations), pill 16.8k/64k, 7:21 vs ~4min bar.
> Root cause is a coverage gap, not an implementation deviation (findings pinned
> session-318). Wave 5 below closes it. T12/T13 deferred until the T21 re-probe passes.

## Wave 1 — Pinned transport + warm fixes (independent, land first)
- [ ] T1 (REQ-6): Transport Empty-retry — move message-extraction + empty check inside the existing 3-attempt loop in `_nonstream`; same-payload retry; preserve RateLimitedError and non-200 paths — `backend/agent/inference/transport.py:773-843` — RIPPLE: all four downstream Empty call sites (step-result processing, final synthesis, decision box, sub-loop) get coverage from this one site; no downstream edits
- [ ] T2 (REQ-6, REQ-7 AC7.3): Embedder warm-at-boot — background task in lifespan calling `get_embedding_service().encode("warmup")`, timing + outcome logged, exception-swallowed, non-blocking to `app.state.ready` — `backend/main.py:169-249` — RIPPLE: rerank.py breaker (:160-182) and embedding.py lazy load (:791-793) intentionally untouched (design NO-CHANGE rows)
- [ ] T3 (REQ-7 AC7.3): Unit/contract tests for T1+T2 (CT-7, CT-8) — `backend/tests/contract/` — RIPPLE: none (new contract tests in existing layout; run with existing suites)

## Wave 2 — Envelope write time + role views (the core)
- [ ] T4 (REQ-1, REQ-3): Create `tool_envelope.py` — ToolResultEnvelope dataclass (status/summary/raw_ref{doc_id ONLY}/match/novelty/suggestion/stuck_shape/coords verbatim/criticality+source/identity/error fields; NO fingerprint, NO vectors, NO encodes), `build_envelope` (pure, deterministic, zero I/O; NO DB writes per AC1.3/CT-9), `derive_wrapper` (per-tool-family bars + stuck-shape classify + hierarchy-C suggestion), `confirm_criticality` (option C), `evaluate_streak` (repeat/empty/mismatch + idling streaks; TOPO_VIOLATION forces fire per AC3.4); streak + grade constants to `der_constants.py` — `backend/agent/tool_envelope.py` (NEW), `backend/agent/der_constants.py` — RIPPLE: der_loop.py QueueItem (T5); planner criticality declaration (T5); unit tests T9/T10; NO new persistence/encodes anywhere (KD-7)
- [ ] T5 (REQ-1): QueueItem gains `envelope: Optional[ToolResultEnvelope] = None` field — `backend/agent/der_loop.py:232 area` — PLUS planner step schema gains per-step `criticality` declaration (load-bearing|supporting|cosmetic) inside the existing `_plan_task` call (no extra inference) — RIPPLE: NodeRecord untouched (design lock); envelope stays Optional so pre-envelope items degrade per AC2.1 edge; Planner declaration is intent-only until T6 confirms it
- [ ] T6 (REQ-1, REQ-2 AC2.1): Build envelope at the finalize site — alongside existing node-record stamping (:14054-14100, outcome/expected_output/fraction/mediator/coords all in scope there); raw_ref = doc_id from `_capture_tool_result` (:4791) ONLY (Pacman chunk ids async-unavailable — never waited on); confirm criticality from `raw_ref` consumption + log declared-vs-confirmed divergence (AC1.6); emit per-envelope debug log (AC7.1) — `backend/agent/agent_kernel.py` — RIPPLE: gather gate + `_der_crawled_urls` (CT-6 CONTRACT LOCK) must be untouched by THIS task (T6B extends the path, never weakens the filter); Pacman store rows unchanged (CT-9)
- [ ] T6B (REQ-2, REQ-3 AC3.3): Pre-dispatch hard-rule guard — before paying for a tool call, block + reroute when the step's tool+params+URLs ⊆ turn memory (repeat → resolve by reading the ORIGINAL `doc_id` via `raw_ref`, never re-execute) or when the target is walled (existing `is_walled` — never retry in-run); emit the block + reroute in the log (CT-10 proves it) — `backend/agent/agent_kernel.py` (pre-dispatch path) — RIPPLE: prevention decides here, envelope testifies in T7; guard reads turn memory + wall ledger only, adds no inference and no store writes
- [ ] T7 (REQ-2 AC2.1, REQ-4 AC4.3): Working memory appends envelope LINE (status+summary+wrapper+raw_ref doc id) for EVERY settled step INCLUDING failures instead of `_smart_excerpt(step_result, cap)` — `backend/agent/agent_kernel.py:13382-13396` — RIPPLE: fixes the :13387 silent-skip (the guaranteed-repeat bug); `_run_step_direct` wm cap 6000 (:11943) stays as defense-in-depth (NO CHANGE verified); `_build_planning_prompt` (:5239) needs NO edit — history now contains envelope lines by construction (CT-2 proves it)
- [ ] T8 (REQ-4 AC4.1/AC4.2, REQ-2 AC2.2/AC2.3): Role views — Reviewer gate passes envelope views (:8319-8326, verdict semantics LOCKED per CT-3); continuation Director OUTPUT block renders envelope summaries + wrapper labels with BOTH halves bounded (cap the full-`i.result` done_summary half to envelope lines like the outputs block) and reports `done + grade` per AC5.6; deterministic fallback summaries render envelope lines with line breaks, replacing the 8000-char gather window in user-facing output (:11463-11468, :11626-11692) — `backend/agent/agent_kernel.py` — RIPPLE: fix 7 (pinned) lands here; `_der_node_record_evidence` keeps its 8000 synthesis window (OQ-2 defers the synthesis-prompt change)

## Wave 3 — Drift gate
- [ ] T9 (REQ-3, REQ-5, REQ-7): Streak-gate wiring — pure `evaluate_streak` unit tests (repeat/empty/mismatch streaks, idling streak, nominal run blocks; TOPO_VIOLATION-rec override fires regardless of streaks — AC3.4; hard-rule predicate: repeat/walled ALWAYS blocks — AC3.3/CT-10); gate call between steps in front of existing `_replan` (:9488, budget-boxed path reused); fired/blocked counters + suggestion-override log + audit log of triggering envelopes (AC5.4/AC7.2) — `backend/agent/agent_kernel.py`, `backend/tests/unit/` — RIPPLE: gate failure → "below threshold" (advisory-gate principle, design Error Handling); hard blocks need NO gate (proven in CT-10 via T6B); zero LLM calls in gate (AC5.5)

## Wave 4 — Verification (quality check → suite → live)
- [ ] T10 (REQ-1..7): Quality check (AGENTS.md checklist on every touched file) + run the SPEC tests: unit envelope/wrapper/shapes/streak tests, CT-1..CT-10, BT-1..BT-3, twins+loop-bounds suite (baseline MUST stay 39 pass / 6 pre-existing fails), py_compile both edited files — `backend/tests/` — RIPPLE: never touch the 6 pre-existing `_FakeKernel._router` fails
- [ ] T11 (REQ-6, REQ-7, success criteria): LIVE gate — restart backend via start-backend.py; verify /health 200, warm log line, sidecar :18183, breaker CLOSED; run the pinned comparison probe (fresh conversation: "Research which speech-to-text transcription models support real-time streaming. Compare whisper.cpp, WhisperX, and NVIDIA Parakeet — for each, cover whether it supports streaming, how, and any limits. Cite your sources.") — PASS BAR (handoff pin_7930379e0f41): no URL re-crawled ("gather gate filtered N/M" in log), repeats steer to reads, context pill well under window (target <50%), missing-model material commits honestly UNVERIFIED ("gather alignment MISS"), turn < ~4min, real per-model answer with citations — RIPPLE: screenshots to screenshots/ (canonical, gitignored); log to .iris-logs
- [ ] T12 (REQ-2, REQ-4): Recall probe — "Now, using task card card_f914cfb1-fd5 from my earlier speech-to-text research, recall what we found about whisper.cpp and summarize it." — RECALL row must read "N document(s) retrieved"; card continues relation — RIPPLE: verifies envelope lines did not break episodic/RECALL join
- [ ] T13 (REQ-7): Counter review from probe logs — streak-gate fired/blocked ratio, hard-rule blocks, suggestion-override rate, context chars per prompt, envelope wrap count, declared-vs-confirmed criticality divergence, breaker state, Empty-retry count, run grade distribution → tune streak thresholds + grade rule (constants only) — `der_constants.py` — RIPPLE: threshold changes are constants-only, no logic edits

## Wave 5 — Ledger visibility + chooser memory + deadlines (session-318 amendment)
Closes the conv-102 coverage gap: memory exists at finalize but never reaches the chooser or the prompts; no identity; no universal deadline.
- [ ] T14 (REQ-8): Envelope `sources` (≤8, truncation marked) + VISITED prompt block (≤20 + pivot rule, pointers-only, joinable keys) — `backend/agent/tool_envelope.py`, `backend/agent/agent_kernel.py` (finalize stamp + prompt render) — RIPPLE: wm LINE shape unchanged (AC2.1 lock holds); guard/novelty read `sources` as data
- [ ] T15 (REQ-9 minus recovery): wire fresh-discovery seeds into the EXISTING exclusion instruments (gather-gate shape + guard branch-2 over resolved seeds, turn-scope queue-time filter) + orchestrator dedup run→turn scope + bounded outlink sets with crawled marking — `backend/crawler/crawl_planner.py`, `backend/crawler/orchestrator.py`, `backend/agent/agent_kernel.py` guard — RIPPLE: no new exclusion system (owner-correct: the machinery mostly exists — this task connects the unguarded road); `_vision_fetch` untouched; SourceRegistry path keeps CT-6 behavior
- [ ] T16 (REQ-9 recovery lane): VLM in-site recovery step (unvisited URLs only, page budget 5 / depth 2 UNVERIFIED, own envelope `recovery_of`, own deadline; async join — dependents bounded-wait, independents proceed) reusing `_vision_fetch` (orchestrator.py:1722) — `backend/crawler/orchestrator.py`, `backend/agent/agent_kernel.py` queue — RIPPLE: no new event types (CT-5); no new fetch path
- [ ] T17 (REQ-10): Exact body-hash dedup (stdlib, normalized text) + in-turn dead-address memory — `backend/agent/tool_envelope.py`, `backend/agent/agent_kernel.py` finalize, crawler extract path — RIPPLE: fingerprint CUT stands (no vectors/encodes — CT-1 extension asserts absence)
- [x] T18 (REQ-11): Per-family dispatch deadlines (150/60/90s UNVERIFIED → **gather RESOLVED at 240s 2026-09-26**, read 60 / default 90 stand) + `task:progress` heartbeat watch (stall 30s UNVERIFIED → warn only) + `timeout` envelope + streak-counting + bound every wait — `backend/agent/agent_kernel.py`, `backend/agent/der_constants.py`, `backend/agent/tool_envelope.py` — RIPPLE: crawler's existing 90s ceiling stays (defense in depth); event_bus unchanged (TASK_PROGRESS exists). **STATUS 2026-09-26 (session 360): landed and pinned by `tests/contract/test_wave5_ledger_contract.py` (CT-11..CT-16) + `tests/behavioral/test_wave5_replay_behavior.py`; CT-15's expected gather constant moved 150 → 240 in the same session, because the code change measured the requirement's own UNVERIFIED value to be wrong.**
- [ ] T19 (REQ-12 + AC5.6 defect): Counters/logs for ledger/chooser/identity/deadline/recovery + TRACE AND FIX the missing `run grade` log (zero hits on the conv-102 live path — completes existing AC5.6, not new scope) — `backend/agent/agent_kernel.py`, `backend/agent/der_constants.py` — RIPPLE: none beyond named files
- [ ] T20 (tests): CT-11..CT-16 + BT-4/BT-5 green (see design.md Testing Strategy extension) — `backend/tests/` — RIPPLE: each new behavioral gap decomposes to its contract twin per the intertwined rule
- [ ] T21 (REQ-8..12, success criteria): LIVE re-probe — comparison probe with a seeded 404; bars: zero same-address re-fetch (log-proven), ledger lines in logs, recovery envelope present, turn <4min, honest citations, breaker closed, zero Empty — RIPPLE: screenshots to screenshots/; log to .iris-logs
- [ ] TG-5 (Wave 5 gate): CT-11..CT-16 + BT-4/BT-5 green AND T21 live bars pass per-AC; twins+loop-bounds baseline unchanged; THEN T12 recall probe + T13 counter review unblock

## Wave 6 — Failure-path envelope, honest recovery lane, bounded synthesis (session-319 amendment)
Owner-approved in session-319 after the live symptoms were traced to code. Two of these
are EXISTING-AC defects (AC2.1 failure path, AC9.6 concurrency), not new scope.
- [ ] T22 (REQ-2 AC2.1 defect): Build the envelope on the FAILURE path too — extract the envelope build out of the success-only `_der_finalize_step` so failed/crashed steps produce an envelope AND contribute their URLs to turn memory (`_der_handle_step_failure` :10803 builds none today). Ripple: turn URL memory is currently written only at :14278; a failed step is why a repeat re-crawl follows an error. Add a dispatch-time action record (tool+params+query — the crawl-budget bookkeeping at :13424-13436 already does this) so a total crash with no result text still blocks a repeat.
- [ ] T23 (REQ-9 AC9.5/AC9.6 defect): Unblock the recovery lane — move the trigger OFF the success-only finalize path (:15355 is inside `_der_finalize_step`), change the gate from "zero sources" (:5339) to "at least one dead address" (dead detection already exists at :5346-5357, currently unreachable), and make the lane genuinely CONCURRENT rather than a serial `queue.add_item` (:15362). Trigger and concurrency MUST land together — widening the trigger onto a serial lane manufactures the latency cost AC9.6 forbids.
- [ ] T24 (REQ-9 AC9.7): Recovery budget becomes agent-determined + deadline-bound with a 25-page runaway ceiling. Retire the 5-page operating cap (:13321-13329) and delete-or-enforce the dead `RECOVERY_DEPTH` constant (der_constants.py:308 — consumed nowhere). The recovery step already inherits the crawl-family deadline; that is the real bound.
- [ ] T25 (REQ-11 AC11.5/AC11.6): Give the final synthesis call a deadline (`_synthesize_response` :15969 → `router.generate` :16053, currently no timeout; transport `_nonstream` retries 3×60s). On expiry degrade to the existing deterministic fallback (:16088). Cap the synthesis retry so it cannot multiply the worst case.
- [ ] T26 (REQ-5 AC5.6 defect): Fire `_der_report_run_grade` when no PENDING steps remain (failed/aborted count as settled), not only on `queue.is_complete()` (:15505). Contract test: abort a step → grade logged exactly once.
- [ ] T27 (REQ-13): Stream the final answer through the existing transport streaming path (no callback is passed today) + fix prism-card legibility in `components/chat/RichDocument.tsx` (mid-token breaking at :501-512, forced `width:100%` at :542, uppercase letter-spaced headers at :569-570) + make format selection prefer text or a text/table combo when a markdown table would cramp (AC13.4 — use the existing `alternatives`/`onFormatChange` affordance, no new framework).
- [ ] T28 (TTS, out of envelope scope but pinned F5): Clear the stuck `load_error` on late-ready so narration is not silently lost (tts.py ~426-443, ~769).
- [ ] TG-6 (Wave 6 gate): T22-T28 tests green; AC2.1 proven on a failed step; AC9.5 proven by a seeded 404 firing the lane; AC13.3 proven against the owner's screenshot shape; twins+loop-bounds baseline unchanged.

## Traceability Matrix (MANDATORY — every AC accounted for)

| REQ | ACs | Covering tasks | Covering tests | Status |
|---|---|---|---|---|
| REQ-1 | AC1.1–AC1.6 | T4, T5, T6 | unit (envelope), CT-1, CT-9, BT-1 | covered (projected) |
| REQ-2 | AC2.1–AC2.5 | T6B, T7, T8, **T22** | CT-2, CT-10, BT-1, **BT-6** | **AC2.1 DEFECT on the failure path (session-319) — T22 closes** |
| REQ-3 | AC3.1–AC3.5 | T4, T6B, T9 | unit (wrapper+shapes), CT-10, BT-2 | covered (projected) |
| REQ-4 | AC4.1–AC4.4 | T8 | CT-2, CT-3, BT-1 | covered (projected) |
| REQ-5 | AC5.1–AC5.6 | T9, **T26** | unit (streak), BT-1 (grade), BT-2 | **AC5.6 DEFECT on the abort path — T26** |
| REQ-6 | AC6.1–AC6.4 | T1, T2, T3, T11 | CT-7, CT-8, live probe | covered (projected) |
| REQ-7 | AC7.1–AC7.3 | T2, T3, T6, T9, T13 | CT-5, live probe logs | covered (projected) |
| — | (OQ-3 CUT to wormhole-aperture; no deferred ACs) | — | — | — |
| REQ-8 | AC8.1–AC8.4 | T14 | CT-11, BT-4 (ledger rendered) | covered (projected) |
| REQ-9 | AC9.1–AC9.7 | T15, T16, **T23, T24** | CT-12, CT-13, CT-16, BT-4 (replay), **BT-7** | **AC9.5/AC9.6 DEFECT (session-319) — T23/T24 close; AC9.7 new** |
| REQ-10 | AC10.1–AC10.3 | T17 | CT-14, BT-4 (hash hits) | covered (projected) |
| REQ-11 | AC11.1–AC11.6 | T18, **T25** | CT-15, BT-5 (hang drive), **BT-8** | **AC11.5 scope corrected to the whole turn; AC11.6 new — T25** |
| REQ-12 | AC12.1–AC12.3 | T19 | CT-11..CT-16 counters, BT-4/BT-5 | covered (projected) |
| REQ-13 | AC13.1–AC13.4 | **T27** | **BT-9 (stream), BT-10 (table legibility)** | **NEW (session-319, owner-requested)** |

AC count: 54 + 8 new session-319 (AC9.7, AC9.8, AC11.6, AC12.4, AC13.1–AC13.4) = 62. Covered: 62. Deferred: 0. Unmapped: 0. ✅
Session-319 additions: AC9.7 (agent-determined recovery budget), AC9.8 (name the reader of `envelope.recovery_of` or remove it), AC11.6 (synthesis deadline), AC12.4 (every counter names its reader — FAULTLINE §11 applied to instrumentation), AC13.1–13.4 (streaming + prism-card legibility).
Defects found in session-319 that were previously marked "covered": AC2.1 (failure path), AC5.6 (abort path), AC9.5/AC9.6 (trigger + concurrency), AC11.5 (scope). Four ACs were marked green that live evidence and code reading show are not met.

## Wave gates (MANDATORY — no wave starts on a red gate)
- [ ] TG-1 (after Wave 1): CT-7 + CT-8 green; py_compile transport.py + main.py; twins+loop-bounds still 39/6
- [ ] TG-2 (after Wave 2): CT-1..CT-6 + CT-9 + CT-10 + BT-1 green; unit envelope/wrapper tests green; baseline 39/6 unchanged
- [ ] TG-3 (after Wave 3): unit streak tests + BT-2 green; baseline 39/6 unchanged
- [ ] TG-4 (Wave 4): T10 full-suite green + T11/T12 live probes pass their bars (the ONLY proof for the success-criteria targets — live gate, not unit green)
- [ ] TG-5 (Wave 5): CT-11..CT-16 + BT-4/BT-5 green AND T21 live re-probe bars pass per-AC (session-318 bars); no wave starts on red without explicit user override recorded in Decisions Locked

## Dependency / parallelization notes
- Wave 1 is fully independent (transport + lifespan) — can land and gate before any envelope work.
- Wave 2 depends on nothing in Wave 1 but shares agent_kernel.py; sequential edits to the same file, same session. T6B (pre-dispatch guard) is independent of T4/T5 (reads turn memory + wall ledger, needs no envelope shape) but lands in Wave 2 so TG-2's CT-10 proves the hard rules alongside the envelope.
- Wave 3 depends on T4/T5 (envelope + QueueItem field + criticality declaration) — cannot start before TG-2's T4/T5 portion.
- T11 requires backend DOWN→fresh restart (verified down); do NOT hot-reload over a stale process.
- NO-CHANGE-verified areas (rerank.py, embedding.py, working.py, dcp.py, frontend, planning prompt) need NO tasks — only their CONTRACT LOCK rows hold (CT-2, CT-5, CT-6).
- Wave 5 ordering: T14 (ledger data+view) first — T15/T16 read its shapes; T15 before T16 (recovery assumes exclusions exist); T17/T18 independent of T14-T16 (parallel-safe, shared files — sequential edits, same session); T19 needs T14-T18 counters defined; T20 after all; T21 last, TG-5 closes.
- Recovery lane never blocks Wave 5 sequencing: it is async work inside T21's turn, not a predecessor of any task.

# Tasks: Tool-Result Envelope & Drift-Gated Coordination

> Each task links to a requirement. Waves are dependency-ordered; Wave 1 is fully
> independent of Waves 2-3 and may land first. Backend is DOWN (verified — no listener
> on :8000); Wave 4 restarts it via start-backend.py. Branch:
> feat/agent-multi-step-tool-execution (uncommitted session-312 changes present —
> envelope work builds ON TOP of them; never stash).

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

## Traceability Matrix (MANDATORY — every AC accounted for)

| REQ | ACs | Covering tasks | Covering tests | Status |
|---|---|---|---|---|
| REQ-1 | AC1.1–AC1.6 | T4, T5, T6 | unit (envelope), CT-1, CT-9, BT-1 | covered (projected) |
| REQ-2 | AC2.1–AC2.5 | T6B, T7, T8 | CT-2, CT-10, BT-1 | covered (projected) |
| REQ-3 | AC3.1–AC3.5 | T4, T6B, T9 | unit (wrapper+shapes), CT-10, BT-2 | covered (projected) |
| REQ-4 | AC4.1–AC4.4 | T8 | CT-2, CT-3, BT-1 | covered (projected) |
| REQ-5 | AC5.1–AC5.6 | T9 | unit (streak), BT-1 (grade), BT-2 | covered (projected) |
| REQ-6 | AC6.1–AC6.4 | T1, T2, T3, T11 | CT-7, CT-8, live probe | covered (projected) |
| REQ-7 | AC7.1–AC7.3 | T2, T3, T6, T9, T13 | CT-5, live probe logs | covered (projected) |
| — | (OQ-3 CUT to wormhole-aperture; no deferred ACs) | — | — | — |

AC count: 6+5+5+4+6+4+3 = 33. Covered: 33. Deferred: 0. Unmapped: 0. ✅

## Wave gates (MANDATORY — no wave starts on a red gate)
- [ ] TG-1 (after Wave 1): CT-7 + CT-8 green; py_compile transport.py + main.py; twins+loop-bounds still 39/6
- [ ] TG-2 (after Wave 2): CT-1..CT-6 + CT-9 + CT-10 + BT-1 green; unit envelope/wrapper tests green; baseline 39/6 unchanged
- [ ] TG-3 (after Wave 3): unit streak tests + BT-2 green; baseline 39/6 unchanged
- [ ] TG-4 (Wave 4): T10 full-suite green + T11/T12 live probes pass their bars (the ONLY proof for the success-criteria targets — live gate, not unit green)

## Dependency / parallelization notes
- Wave 1 is fully independent (transport + lifespan) — can land and gate before any envelope work.
- Wave 2 depends on nothing in Wave 1 but shares agent_kernel.py; sequential edits to the same file, same session. T6B (pre-dispatch guard) is independent of T4/T5 (reads turn memory + wall ledger, needs no envelope shape) but lands in Wave 2 so TG-2's CT-10 proves the hard rules alongside the envelope.
- Wave 3 depends on T4/T5 (envelope + QueueItem field + criticality declaration) — cannot start before TG-2's T4/T5 portion.
- T11 requires backend DOWN→fresh restart (verified down); do NOT hot-reload over a stale process.
- NO-CHANGE-verified areas (rerank.py, embedding.py, working.py, dcp.py, frontend, planning prompt) need NO tasks — only their CONTRACT LOCK rows hold (CT-2, CT-5, CT-6).

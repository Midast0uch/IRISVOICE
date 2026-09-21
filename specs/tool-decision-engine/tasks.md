# Tasks: Tool Decision Engine

> Each task links to requirements. Waves are dependency-ordered; Wave 1 is
> backend-isolated, Wave 2 needs Wave 1 green, Wave 3 is quality + measurement.

## Wave 1 â€” Engine core (backend-only, no existing behavior changes)

- [x] T1 (REQ-1, REQ-7): `backend/agent/decision_engine.py` â€” lazy in-process
  `llama_cpp` load of the 350M from the models dir, CPU-only, bounded ctx/output,
  serialized context with bounded wait, availability flag, `shutdown()` wired into the
  lifespan teardown (`backend/main.py:960-1008`); `agent_config.yaml` gains the 350M
  entry. MODEL: not present locally â€” prefer a GGUF decoder variant suited to
  structured output (LFM2.5-350M Instruct / LFM2-350M-Extract family) via
  `local_model_manager.download_model` (hf_hub_download, :4275); record the chosen
  repo/file in this spec. â€” RIPPLE: agent_config.yaml entry mirrors executor style
  (:1-24); engine never calls `LocalModelManager.load_model` (VRAM ledger :791 must
  stay untouched).
- [x] T2 (REQ-2, REQ-4): candidate scoring â€” fixed decision prompt, forced-continuation
  logprob per candidate (incl. DELEGATE/NONE), softmax distribution, `{chosen,
  confidence, distribution}`; schema-constrained args stage; single bounded empty retry
  on generation. â€” RIPPLE: consumes `get_available_tools` shape unchanged
  (tool_bridge.py:378); unit tests only, box not yet wired.
- [x] TG-1 (REQ-1, REQ-2, REQ-4, REQ-7): unit suite for T1+T2 green with a real tiny
  GGUF or a faithful `llama_cpp` stub per existing test conventions; leak check
  (load â†’ score â†’ free) included.

## Wave 2 â€” Integration

- [x] T3 (REQ-3, REQ-9): `ToolDecisionBox.resolve()` routing â€” engine-first, threshold
  ladder (engine â†’ memory fallback â†’ escalation single-shot), `DecisionMeta` built and
  threaded through `dispatch()`; escalation call gains the bounded retry; DecisionKind
  never grows. â€” RIPPLE: tool_decision.py:421/:491/:689 edited; kernel seam untouched
  (CT-DE-2 proves it).
- [x] T4 (REQ-5): `execute_tool(decision_meta=None)` + `_record_tool_event` payload
  `decision` block; route-only rows (`outcome=None`) for REASON/FAIL decisions through
  the same writer; `dag_node_id` join field. â€” RIPPLE: tool_bridge.py:1247/:1936 edited;
  `ffi_ingest_event` signature untouched (payload_dict absorbs the block);
  `_summarize` bounding re-used for the new fields.
- [x] TG-2 (REQ-3, REQ-5, REQ-9): contract CT-DE-1..CT-DE-5 green (spec-owned test
  files; see Traceability Matrix).

## Wave 3 â€” Observability, calibration, live measurement

- [x] T5 (REQ-8): structured decision log line + counters (engine decisions,
  escalations, memory fallbacks, retries, unavailable events) â€” off critical path.
  â€” RIPPLE: none; logging only.
- [x] T6 (REQ-6): `scripts/calibrate_decision_threshold.py` â€” reliability table,
  threshold recommendation (refuses N<50, groups by model id), per-route latency
  p50/p95, escalation rate, big-model-calls-avoided. Reads `system_events` from
  `data/memory.db` via the read-only sqlite URI pattern (D13; honors the encryption
  flag, reports UNVERIFIED if encrypted). â€” RIPPLE: no writes.
- [ ] T7 (REQ-10): baseline capture (engine disabled) over the LT battery â†’ stored
  artifact; then engine-on run; LT doc gains route-latency/escalation rows; verdict +
  measured threshold applied to config if it beats 0.85 by the calibration rule.
  â€” RIPPLE: `docs/LIVE_TEST_VISION_BROWSER_E2E.md` gains rows; may re-run LT battery.
- [x] TG-3 (code parts; live verdict lands in TG-5): calibration script
  produces a report from a synthetic ledger fixture + live gate verdict recorded.

## Wave 4 â€” Surface and narration gates (consumers 2 & 3)

- \[x] T8 (REQ-13): consumer registry + enumerated feature-frame builders
  (`decide(consumer_id, options, frame)` API; per-consumer decision counters; shared
  serialized context; ledger `consumer_id` field). â€” RIPPLE: decision_engine.py (Wave
  1 file) extended; ToolDecisionBox re-expressed as consumer `tool_choice` without
  changing behavior (T3 contract tests must stay green).
- [x] T9 (REQ-11): presentation gate â€” engine Choice `{plain_text, prism_card,
  card_plus_summary}` at `agent_kernel.py:4280`; heuristic becomes degrade path;
  `_last_render_emitted` precondition first; shadow-mode flag with ledger recording;
  supportive excerpt emitted only for `card_plus_summary` (:4375). â€” RIPPLE:
  agent_kernel.py:4280/:4375 edited; `_supportive_text` unchanged in content;
  chat_message/document:render payload shapes frozen (CT-DE-6).
- [x] T10 (REQ-12): narration gate â€” engine Noul at `_speak_response` admission and
  `may_narrate`; AND-compose with toggle + timer; engine `silent` disables the
  backstop only when the engine actually answered; alerts bypass. â€” RIPPLE:
  iris_gateway.py:3434-3463/:3839 and narration.py:246 edited; speech_lanes.py
  untouched (CT-DE-8); conversation toggle read-only.
- [x] TG-4 (REQ-11, REQ-12, REQ-13): CT-DE-6/7/8 green + BT-DE-5/6/7 green + T3 suite
  re-green after the consumer-registry re-expression.

## Wave 5 â€” VLM-driven live verification

- [ ] T11 (REQ-14): `scripts/vision_live_gate_decision_engine.py` + LT battery rows â€”
  drive the app via the vision layer, assert surfaces vs ledger decisions, harvest
  decision counts, write the verdict rows. â€” RIPPLE: docs/LIVE_TEST_VISION_BROWSER_E2E.md
  rows; canonical screenshots dir; app-testing skill launcher conventions. REQUIRES
  TG-3 + TG-4 green.
- [ ] TG-5 (REQ-14, REQ-6, REQ-10): live battery executed; â‰¥ 50 decisions harvested
  across consumers; reliability report produced; threshold recommendations recorded;
  every behavioral gap decomposed into a CT-DE-*; verdict documented per row.

## Wave 6 — Continuity + vision coordination

- [x] T11b (core, unblocks the wave): ONE-PASS parallel option scoring —
  letter-indexed candidates, one prompt evaluation, letter logits. LIVE:
  2.1s cold (load+head) and 0.2-0.3s warm per decision vs 30-40s sequential.
- [x] T12 (REQ-15): cross-step continuity frame — box populates previous_chosen /
  previous_outcome / step_index from `_tool_call_nodes`; meta carries the same
  fields (AC15.2); tests assert first-step nulls and second-step propagation.
  — RIPPLE: tool_decision.py `_engine_try` frame ctor; no engine-side state.
- [x] T13 (REQ-16): vision coordination — `needs_vision` frame feature +
  vision-candidate guarantee (registry-ordered, inside the cap); a step matching
  the vision vocabulary never scores on a vision-less option set. — RIPPLE:
  tool_decision.py candidate assembly; decision_engine unchanged (frame consumer).
- [x] TG-6 (wave-6 contract+unit green; live-deployed accuracy/TBD); code inertia note: engine decided over head-KV restore + full-eval fallback
  vision-candidate invariants green; **live latency re-measured** — the one-pass
  scoring's whole point is the measured speed drop; record in the LT battery log.

## Traceability Matrix

| REQ | ACs | Covering tasks | Covering tests | Status |
|---|---|---|---|---|
| REQ-1 | AC1.1, AC1.2, AC1.3, AC1.4 | T1 | unit: lifecycle/load-fail/serialization; TG-1 leak check | covered |
| REQ-2 | AC2.1â€“AC2.5 | T2 | unit: softmax/argmax/prefix; CT-DE-4 | covered |
| REQ-3 | AC3.1â€“AC3.4 | T3 | unit: thresholds; CT-DE-2; BT-DE-1/2 | covered |
| REQ-4 | AC4.1â€“AC4.3 | T2, T3 | unit retry-once; BT-DE-3 | covered |
| REQ-5 | AC5.1â€“AC5.4 | T4 | CT-DE-3; BT-DE-4 | covered |
| REQ-6 | AC6.1â€“AC6.3 | T6, T11 | calibration script on fixture; TG-5 live harvest | covered |
| REQ-7 | AC7.1â€“AC7.4 | T1 | TG-1 leak check; CT-DE-4 | covered |
| REQ-8 | AC8.1, AC8.2 | T5 | asserted inside BT-DE-1..7 | covered |
| REQ-9 | AC9.1â€“AC9.3 | T3 | CT-DE-1, CT-DE-5 | covered |
| REQ-10 | AC10.1â€“AC10.4 | T4, T6, T11 | BT-DE-1..7; T7 baseline; TG-5 live verdict | covered |
| REQ-11 | AC11.1â€“AC11.5 | T9 | unit presentation gate; CT-DE-6; BT-DE-5 | covered |
| REQ-12 | AC12.1â€“AC12.5 | T10 | unit narration gate; CT-DE-8; BT-DE-6/7 | covered |
| REQ-13 | AC13.1â€“AC13.3 | T8 | CT-DE-7; regression of T3 suite | covered |
| REQ-14 | AC14.1â€“AC14.4 | T11 | TG-5 live gate (vision assertions) | covered |
| REQ-15 | AC15.1-AC15.4 | T12 | unit+contract: continuity frame, first-step nulls | covered |
| REQ-16 | AC16.1-AC16.4 | T13 | unit+contract: vision candidate guarantee, needs_vision feature | covered |

Verdict: 61 ACs — 61 covered, 0 deferred, 0 unmapped.

## Wave gates

- **TG-1** = unit suite for T1+T2 green (REQ-1, REQ-2, REQ-4, REQ-7 ACs), no existing
  backend test regressed.
- **TG-2** = CT-DE-1..CT-DE-5 green (REQ-3, REQ-5, REQ-9).
- **TG-3** = BT-DE-1..4 green + calibration script green on fixture + REQ-10 baseline
  captured (REQ-6, REQ-8, REQ-10).
- **TG-4** = CT-DE-6/7/8 + BT-DE-5/6/7 green + Wave-2 contract suite re-green (REQ-11,
  REQ-12, REQ-13).
- **TG-5** = VLM live gate executed with verdicts and harvest (REQ-14, REQ-6 live,
  REQ-10 live).

No wave starts while the previous gate is red (owner override recorded in Decisions
Locked if ever needed).

## Dependency / parallelization notes

- T1/T2 may be built by one hand; they are the only new-code unit of Wave 1.
- T3 and T4 are one logical change split for reviewability; land together to keep the
  ledger/meta contract coherent.
- T5/T6 are independent of each other once Wave 2 lands.
- T7 baseline must capture BEFORE engine code is active in live runs (shadow-excepted).
- T8 requires Waves 1-3; T9/T10 are independent of each other but both need T8.
- T11 requires TG-3 and TG-4 green; it IS the TG-5 vehicle.
- NO-CHANGE-verified areas (router, transports, kernel seam, memory layer,
  speech_lanes, frontend) need no tasks â€” only their CONTRACT LOCK tests.

## Live Iteration Log (session 343, Wave 1-4 code complete)

- T1 model resolved: mradermacher/LFM2-350M-Extract-GGUF -> LFM2-350M-Extract.Q4_K_M.gguf
  (task-tuned; base LFM2-350M produced near-random decisions).
- T2 fixes from live smoke: max_tokens=0 generated to context edge -> max_tokens=1
  (104s/option -> ~2.5s); logits_all=True required for echo scoring.
- candidate_cap 32 -> 8 after a 474s 25-candidate decision on loaded CPU.
- Engine injection only (no lazy global in the box) for unit determinism.
- GPU offload NOT enabled (AC1.2 stands); decision deferred to the REQ-10 gate with
  harvested data.
- TG-5 live harvest ran in full shadow (IRIS_DECISION_ENFORCE=""): rows recorded for
  presentation + tool_choice consumers.

## Performance Reference (2026-09-20, loaded CPU box, LFM2-350M-Extract Q4_K_M)

Chain: raw wrong (sequential) -> fixed pipeline:
- Broken max_tokens=0: 104s per option
- Per-option continuation: 2.5s/option (~10s/decision)
- One-pass parallel scoring (Jev): 0.26-0.47s/decision
- + head-KV cache + pre-tokenized letters + candidate cap 8: ~same steady state, ~0.9s load+warm
- Thread knob: flat (compute-bound; 8-core box)
- GPU knob present but INERT: installed llama-cpp-python is CPU-only wheel
  (lib/ggml-cpu.dll only); enabling CUDA requires a rebuild of the dependency.
  Cheaper CUDA path if ever needed: route scoring through the resident 8082
  llama-server (already CUDA) when the brain is already there.

Thresholds: per-consumer via EngineConfig.thresholds map; default 0.85 stands
until calibration (lap harvest in progress).

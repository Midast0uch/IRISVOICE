# Tasks: Phonon-2 STT Swap + d1-3B Vision/Oracle Adoption

> Each task links to a requirement. Wave order matches the work order:
> V1 first (it can invalidate the Oracle half), Phonon-2, d1 vision, d1 Oracle
> + recalibration + B-list, cleanup last. No wave starts on a red gate.

## Wave 0 — Verification gates (BLOCKING; failure stops the affected half)
- [x] T0.1 (REQ-0 AC0.3, V3): Parakeet consumer enumeration — DONE at
  spec-writing time with file:line evidence (see requirements.md AC0.3);
  RE-VERIFY with a fresh grep before any removal task runs — RIPPLE: every
  file named there
- [ ] T0.2 (REQ-0 AC0.2, V2): Phonon-2 Windows CPU smoke — install
  (`fermion-research torch safetensors soundfile scipy zstandard`), transcribe
  a recorded 16 kHz mono utterance, assert word-level timestamps and CPU-only
  operation — RIPPLE: none (probe only)
- [ ] T0.3 (REQ-0 AC0.1, V1): d1 decision-output probe — serve d1 under the
  bundled llama-server, drive the noul/choice/score prompt template, read
  logprobs over the criteria tokens, assert a calibrated probability is
  extractable. Owner expectation: PASS (d1 is JEV-style). Unexpected FAIL =>
  stop and report; d1 vision-only; REQ-5/REQ-6 halt — RIPPLE:
  `backend/agent/decision_engine.py` (which backend gets built)
- [ ] T0.5 (REQ-0 AC0.4, V4): Inception Mercury residency + role-binding
  probe — locate the weights (local GGUF path + size + context) or the hosted
  API endpoint + credential source; record the failure mode (VRAM vs provider
  outage); confirm the router CAN bind reasoning=Mercury,
  tool_execution=LFM2.5-2.6B (oracle.md §13.1 shape) — RIPPLE:
  `backend/agent/inference/roles.py` binding table, VRAM budget (re-run if
  local GGUF)
- [ ] T0.4: Baseline quality gate — confirm HEAD dc7139bc passes the Oracle
  contract suite subset and commit any remaining uncommitted session work
  (pin note: backend not restarted since dc7139bc; nothing live-verified yet)
  — RIPPLE: establishes the green baseline every later gate compares against
- [ ] TG-0 (gate for REQ-0): record V1/V2/V3/V4 outcomes in
  `specs/phonon2-d1-model-swap/VERIFY.md`, each with the exact command, the
  measured result, and the binary pass/fail. Next wave MUST NOT start on a
  red gate without an owner override recorded in Decisions Locked.

## Wave 1 — Phonon-2 streaming STT swap (REQ-1, REQ-2, part of REQ-3)
- [ ] T1.1 (REQ-1 AC1.1/AC1.2/AC1.5): Phonon-2 live-stream client behind the
  existing voice_command seam (`/v1/audio/stream`; interim hypotheses at
  ~0.35 s / ~2 Hz; final at 0.7 s silence or 30 s cap; sticky failure;
  `stt_backend` timing fields; whisper fallback for FINAL segments only) —
  `backend/audio/phonon2_stream.py` (new), `backend/audio/voice_command.py`
  — RIPPLE: `backend/main.py` boot warm (:321-340) and status line (:523);
  interim path TRACED at Wave 0 (VERIFY.md): add `iris:voice_interim`
  broadcast + useIRISWebSocket.ts dispatch + chat-view.tsx handler
- [ ] T1.2 (REQ-1 AC1.3/AC1.6): hotwords (<=25, wake word + command vocab),
  word-timestamp plumbing, and first-hypothesis latency in `_last_stt_timing`
  — RIPPLE: none beyond voice_command.py
- [ ] T1.3 (REQ-14 AC14.1): per-turn engine/timing/fallback-reason log —
  RIPPLE: log consumers in iris_gateway.py:3116
- [ ] T1.4 (REQ-2 AC2.1-2.3): explicit retirement flag for Parakeet,
  greppable; boot resolves at most one ASR engine or fails loudly —
  RIPPLE: `backend/audio/__init__.py` lazy-accessor docstring (:19-25)
- [ ] T1.5 (REQ-1 all): unit + behavioral tests (BT-P2-1 streaming shape;
  stream-client fakes; whisper final-fallback transitions) — RIPPLE: none
- [ ] T1.6 (REQ-13 AC13.2): LIVE gate — measured voice turn shows
  `stt_backend` = phonon-2 path, never `parakeet*`, with an interim hypothesis
  BEFORE the final segment — RIPPLE: app-testing Mode A harness (unchanged
  interface)
- [ ] TG-1 (gate for REQ-1, REQ-2, REQ-14.1): T1.5 green + T1.6 measured.
  Proving tests: BT-P2-1, worker unit tests, live log capture.

## Wave 2 — d1 as vision source (REQ-4, part of REQ-14)
- [ ] T2.1 (REQ-4 AC4.1/AC4.2): registry entry + scan discovery for the
  d1+mmproj pair; UI loadable with projector —
  `models/gguf/.iris_model_settings.json`, scan path — RIPPLE:
  ModelBrowserPanel.tsx (NO CHANGE verified), vision_provider probe (NO CHANGE
  verified)
- [ ] T2.2 (REQ-4 AC4.3/AC4.5; CONTRACT LOCK): CT-D1-1 contract test — probe
  proof required for d1; a text-only server named d1 can never be a vision
  target — RIPPLE: test_vision_server_reuse_contract.py family
- [ ] T2.3 (REQ-4 AC4.4): drop the separate VL GGUF from the live path;
  retirement flag (AC11.1) — RIPPLE: registry (AC11.2), any config/env naming
  the VL pair (V3-style enumeration first)
- [ ] T2.4 (REQ-13 AC13.3): LIVE gate — vision task through the shared server
  hosting d1, probe proof recorded — RIPPLE: none
- [ ] T2.5 (REQ-4 AC4.6, gated on T0.5/V4): bind reasoning=Inception Mercury,
  tool_execution=LFM2.5-2.6B-Q4_K_M via the §13.1 set_model_selection shape —
  RIPPLE: `backend/agent/inference/roles.py` binding table; if V4 found a
  local GGUF, re-check the VRAM budget first (D9)
- [ ] T2.6 (REQ-13 AC13.6): LIVE gate — a measured turn resolves reasoning to
  Mercury and tool execution to 2.6B (resolution log line) — RIPPLE: none
- [ ] TG-2 (gate for REQ-4): CT-D1-1 green + T2.4 measured + T2.6 measured +
  old VL path unreachable from live config.

## Wave 3 — d1 as Oracle + recalibration (REQ-5, REQ-6, REQ-7)
> Condition: TG-0 V1 PASSED (owner expectation: pass — d1 is JEV-style). If V1
> unexpectedly failed, work already stopped at TG-0 with a report; the B-list
> (Wave 4) still proceeds model-independently and the GLiNER retirement task
> (T5.3 extension) is DEFERRED with the reason recorded.

- [ ] T3.1 (REQ-5 AC5.1/AC5.4/AC5.5): d1 decision backend —
  `backend/agent/decision_backend_d1.py` (new): llama-server prompt template +
  logprobs; `decide()` contract only; no prose, no batching (guard:
  test_batch_single_encode.py stays green); latency measurement vs the 154 ms
  GLiNER baseline recorded — RIPPLE: `decision_engine.py` backend wiring
- [ ] T3.2 (REQ-5 AC5.2/AC5.3): variant-derived backend identity for d1 keyed
  in backend_thresholds; fail-closed until re-earned; GLiNER rows counted
  `other_backend`, never deleted — RIPPLE: `_current_backend_identity`
  (decision_engine.py:317), conftest.py:329 identity fixture, CT-D1-2
- [ ] T3.3 (REQ-7 AC7.1-7.3): label_source on shadow rows; outside labels
  (test outcome, user correction, observed completion) preferred; the fit
  reports label source per consumer; `mode` ground-truth path —
  RIPPLE: shadow row writers (explorer, monitor_shadow, surface_shadow),
  fit_oracle_calibration.py, consumer_enforcement_report.py
- [ ] T3.4 (REQ-6 AC6.1/AC6.4): row accumulation on d1 via real traffic
  (scripts/accumulate_rows.py) to >= 100 DISTINCT rows per live consumer —
  RIPPLE: system_events ledger (bounded by AC12.1 dedup)
- [ ] T3.5 (REQ-6 AC6.2/AC6.3): refit oracle_calibration.json + bar record on
  d1; record per-consumer bar outcome in the spec; enforcement flips ONLY via
  IRIS_DECISION_ENFORCE after owner review — RIPPLE: benchmarks/*.json
- [ ] T3.6 (REQ-13 AC13.4): LIVE gate — evals/run_evals.py on the touched
  tasks; reply_s within baseline + 15%; decision rows carry the new identity
  — RIPPLE: app-testing harness (unchanged)
- [ ] TG-3 (gate for REQ-5/6/7): BT-ORACLE-1 green, CT-D1-2 green, refit
  artifacts present and honest (no padded rows), T3.6 measured.

## Wave 4 — Pre-existing Oracle fixes (B-list: REQ-8, REQ-9, REQ-10, REQ-12, REQ-13.1)
- [ ] T4.1 (REQ-10 AC10.1-10.3): local-goal web veto moves to menu build;
  CT-VETO-1 contract test fails on the pre-fix shape —
  `backend/agent/tool_decision.py` — RIPPLE: `_memory_decision` (:915-956)
  keeps its per-route check as defence in depth; external_reference domain
  guard (dc7139bc) stays structural
- [ ] T4.2 (REQ-9 AC9.1-9.3): depth question scored at the monitor consult;
  skip-visibility logging; shadow lane only — `backend/agent/agent_kernel.py`
  (:7305-7503, :20026-20079, :20738-20780), `tool_decision.py` depth_route
  (:2699-2836) — RIPPLE: test_monitor_shadow_off_answer_path.py,
  test_oracle_enforcement_contract.py depth_met sites
- [ ] T4.3 (REQ-8 AC8.1-8.3): review_verdict + user_feedback prompt/option
  rework, refit, honest non-estimable reporting — RIPPLE: consumer specs,
  fit artifacts
- [ ] T4.4 (REQ-12 AC12.1): duplicate-row prevention at WRITE time
  (consumer + normalized input identity) — RIPPLE: shadow write sites,
  fit script shares the identity definition
- [ ] T4.5 (REQ-12 AC12.2/AC12.3): remove `retry_same` from CONSUMERS as a
  menu-level consumer — ONE change including all pinned-enumeration tests
  (test_decision_engine_contract, test_surface_observer_contract,
  test_decision_engine_gates, test_oracle_calibration_contract,
  test_verdict_consumer_shape); `retry_same_offered` remains a field —
  RIPPLE: tool_decision.py:89/:2619, tool_envelope suggestion enums
- [ ] T4.6 (REQ-13 AC13.1): stub the decision engine in
  test_wave5_replay_behavior.py; prove 20 consecutive green runs —
  RIPPLE: none
- [ ] TG-4 (gate for REQ-8..REQ-13.1): CT-VETO-1 + CT-CONS-1 + enumeration
  suites green; wave5 20/20 green; refit artifacts updated.

## Wave 5 — Cleanup C1-C5 + live certification (REQ-3 rest, REQ-11, REQ-13)
- [ ] T5.1 (REQ-11 AC11.1/AC11.3): retirement constants greppable; runtime
  reference to a retired asset fails loudly naming the constant —
  RIPPLE: all retired-asset modules
- [ ] T5.2 (REQ-11 AC11.2): registry cleanup — retired entries removed from
  the selectable set — RIPPLE: ModelBrowserPanel (NO CHANGE verified)
- [ ] T5.3 (REQ-3 AC3.1-3.3 + REQ-11 AC11.4/AC11.5, C5): delete Parakeet
  modules, `data/models/parakeet-sherpa/`, parakeet_* tests (or rewrite to
  Phonon-2), superseded VL pair, dead env vars (PARAKEET_PORT,
  IRIS_PARAKEET_PROVIDER, IRIS_PARAKEET_SHERPA_DIR, IRIS_STT_WARM_DISABLE if
  dead), `hooks/useParakeetSTT.ts` (dormant :8765 browser hook — V3 finding),
  `scripts/convert_parakeet_fp16.py`, and the parakeet labels in
  scripts/iris_process_manager.py / mem_watch.py / measure_memory.py;
  AND, gated on TG-3 green, delete GLiNER
  Decider 2.5 as code — `backend/agent/decision_backend_onnx.py`,
  `backend/models/gliner2.5-decide-onnx/`, vendored runner — with every
  GLiNER-pinning test updated or removed in the SAME change and oracle.md §0
  rewritten to name d1 the current engine (D10; ledger/calibration history
  stays). Commit message names what was verified — RIPPLE: start_all.py
  (:172-173), media_tools.py (:23), test_onnx_backend_contract.py,
  test_model_pin.py, conftest.py:329 identity fixture
- [ ] T5.4 (REQ-13 AC13.5): LIVE VRAM measurement; assert no LFM2.5-8B
  co-residency with d1 — RIPPLE: none
- [ ] T5.5 (REQ-14 AC14.2/AC14.3): once-per-process identity + enforcement
  log verified live; retirement log names constants — RIPPLE: none
- [ ] TG-5 (final gate): grep-clean (zero parakeet/gliner/old-VL references
  outside archive/docs/history), full targeted suites green, all live gates in
  this file measured GREEN, PROGRESS.md Standards rows added for C1/C2 guards.

## Traceability Matrix
| REQ | ACs | Covering tasks | Covering tests | Status |
|---|---|---|---|---|
| REQ-0 | AC0.1 | T0.3 | VERIFY.md V1 record + probe script | covered |
| REQ-0 | AC0.2 | T0.2 | VERIFY.md V2 record + smoke transcript | covered |
| REQ-0 | AC0.3 | T0.1 (done at spec time; re-verified) | grep evidence in requirements.md | covered |
| REQ-0 | AC0.4 | T0.5 | VERIFY.md V4 record + role-binding probe | covered |
| REQ-1 | AC1.1-1.6 | T1.1, T1.2 | BT-P2-1 (streaming); worker unit tests; live log (T1.6) | covered |
| REQ-2 | AC2.1-2.3 | T1.4 | boot-resolution unit test + live T1.6 | covered |
| REQ-3 | AC3.1-3.3 | T0.1, T5.3 | grep-clean proof in TG-5 | covered |
| REQ-4 | AC4.1-4.6 | T2.1, T2.2, T2.3, T2.5 | CT-D1-1; scan_models tests; live T2.4 + T2.6 | covered |
| REQ-5 | AC5.1-5.5 | T3.1, T3.2 | CT-D1-2; d1 backend unit tests; guard test_batch_single_encode.py | covered |
| REQ-6 | AC6.1-6.4 | T3.4, T3.5 | fit artifacts + enforcement report; replay harness refusal check | covered |
| REQ-7 | AC7.1-7.3 | T3.3 | shadow-row unit tests; fit label-source report | covered |
| REQ-8 | AC8.1-8.3 | T4.3 | refit artifacts; consumer spec tests | covered |
| REQ-9 | AC9.1-9.3 | T4.2 | test_monitor_shadow_off_answer_path.py; oracle enforcement contract sites | covered |
| REQ-10 | AC10.1-10.3 | T4.1 | CT-VETO-1 (fails on pre-fix shape) | covered |
| REQ-11 | AC11.1-11.5 | T5.1, T5.2, T5.3 | grep-clean TG-5; loud-failure unit test | covered |
| REQ-12 | AC12.1-12.3 | T4.4, T4.5 | CT-CONS-1; dedup unit tests | covered |
| REQ-13 | AC13.1-13.6 | T4.6, T1.6, T2.4, T2.6, T3.6, T5.4 | 20/20 wave5 runs; live gates (Mode A) | covered |
| REQ-14 | AC14.1-14.3 | T1.3, T5.5 | log-capture assertions in BT-P2-1 + live | covered |

Unmapped ACs: **0**. Deferred ACs: none at writing time.

## Wave gates
TG-0/TG-1/TG-2/TG-3/TG-4/TG-5 listed inline above. Each gate re-runs every
covering test named for that wave's REQs and records green/red per AC in
VERIFY.md. No wave starts on a red predecessor gate without an owner override
recorded in requirements.md Decisions Locked.

## Dependency / parallelization notes
- Wave 1 (STT) and Wave 2 (vision + role binding) touch disjoint code and MAY
  run in parallel once TG-0 is green. Wave 3 depends on TG-0 V1 AND on Wave 2's
  registry/serving work if d1 serves both roles from one server instance.
  T2.5/T2.6 additionally depend on TG-0 V4.
- Wave 4 tasks are largely disjoint files; T4.1/T4.5 both edit
  tool_decision.py — sequence them (T4.1 then T4.5) to keep the
  enumeration-removal single-change property.
- Wave 5 starts only after TG-1..TG-4 are green (C1: proof before removal).
- NO-CHANGE-verified areas (vision consumers, ModelBrowserPanel, eval
  harness, Porcupine, whisper fallback) appear here only as CONTRACT LOCK or
  verification targets — no code tasks.
- Uncommitted-state note: the pin warned "nothing committed"; commit dc7139bc
  (2026-10-08 03:07) has since landed the domain guard/provenance/mode work.
  T0.4 confirms the baseline and live-verifies it before any swap work.

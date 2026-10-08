# Requirements: Phonon-2 STT Swap + d1-3B Vision/Oracle Adoption

Source work order: PiN `pin_1a08a392eafa` (owner-approved handoff, 2026-10-08).

## Decisions Locked
- Parakeet is replaced by **Phonon-2 on CPU**, in its LIVE STREAMING mode
  (WebSocket `/v1/audio/stream`; hypothesis at ~0.35 s, updates ~2/s, segment
  finalizes at ~0.7 s silence or a 30 s cap) — streaming is REQUIRED: it is
  what replaces Parakeet inside the audio pipeline, not an optional extra.
  The owner has ACCEPTED the WER regression (Phonon-2 5.21 vs our Parakeet
  4.96 avg WER).
- **d1-3B-AD-Q4_K_M.gguf + mmproj-d1-3B-BF16.gguf**
  (`D:/lmstudio/models/AtomicChat/d1-3B-GGUF/`, 2.52 GB total, verified on disk)
  is adopted as the **primary vision source** under the EXISTING llama.cpp
  infrastructure AND as **the Oracle decision model**. d1 is a JEV-style
  decision model (LiquidAI/d1-3B: calibrated noul/choice/score). Gate V1 stays
  in the plan as a VERIFICATION of the llama.cpp serving detail, not as a
  feasibility doubt — the owner expects it to pass; if it unexpectedly fails,
  stop and report rather than engineering around it.
- **Model roles after the swap:** tool execution = LFM2.5-2.6B-Q4_K_M;
  reasoning = **Inception Mercury** paired with it. Mercury's residency (local
  GGUF on disk vs hosted Inception API) is UNVERIFIED — verification V4
  resolves it; a hosted Mercury costs zero VRAM.
- **Deletions after verification (C5, extended by owner):** Parakeet AND
  GLiNER Decider 2.5 (`decision_backend_onnx.py`,
  `backend/models/gliner2.5-decide-onnx/`, their tests, their env/flags) are
  REMOVED once their replacements are live-verified. Ledger rows and
  calibration HISTORY are never deleted — old rows stay as `other_backend`
  (oracle.md §16).
- Old and new engines are NEVER live at the same time (C1): two ASR engines or
  two vision paths on one 8 GB card is both a correctness and a VRAM hazard.
- Retirement is EXPLICIT and greppable (C2): retired models are flagged off,
  not merely unused.
- `mode` is deliberately NOT re-wired as a node-mode dependency. Node mode uses
  the structural signal `external_reference.mode_for_goal` (shipped in commit
  dc7139bc). Do not "fix" that.
- The pin's claim "nothing from that session is committed" is STALE: fixes 1
  (provenance), 2 (domain guard, `backend/agent/external_reference.py`), and
  mode unification landed in commit `dc7139bc` (2026-10-08 03:07). The claim
  "the backend has not been restarted, nothing is live-verified" STANDS.

## Introduction
IRIS runs Parakeet STT on the GPU and an ONNX GLiNER classifier as its Oracle
decision engine. The owner wants the GPU freed (ASR moves to CPU under
Phonon-2) and the owner's d1-3B build adopted as the vision source AND — if
architecturally possible under llama.cpp — as the Oracle's calibrated decision
model, with a full recalibration on the new (quantised) identity and fixes for
eight pre-existing Oracle issues measured on 2026-10-08.

### Success criteria
- Voice turns transcribe through Phonon-2 LIVE STREAMING on CPU (interim
  hypotheses at ~0.35 s with ~2/s updates, final segment at ~0.7 s silence or
  the 30 s cap), with faster-whisper as the only final-transcript fallback;
  Parakeet never loads. (Verified live: `stt_backend` log field never reads
  `parakeet*`.)
- Vision requests are served by the shared llama-server hosting d1 + mmproj;
  the capability probe (32x16 red/blue PNG, `vision_provider.py` _PROBE_PNG_B64)
  passes against d1 before any traffic is routed.
- The Oracle backend identity is the d1 GGUF variant (a JEV-style decision
  model); every consumer's calibration is re-earned on the d1 quantised
  weights (>=100 distinct rows per consumer, refit, bar re-derived); at least
  one consumer whose incumbent is a Brain call earns enforcement.
- Reasoning resolves to Inception Mercury; tool execution resolves to
  LFM2.5-2.6B-Q4_K_M (the two Brain roles are independent bindings,
  oracle.md §13.1). Mercury residency verified (local vs hosted).
- VRAM after the swap: d1 (1.66 GB) + mmproj (0.86 GB) + KV/activations
  (~1-1.5 GB) ~= 3.5-4 GB, plus LFM2.5-2.6B (~1.6 GB) => fits in 8 GB with
  headroom. LFM2.5-8B-A1B-Q4_K_M is NOT co-resident with d1. UNVERIFIED as a
  live measurement — a task must measure it.
- All C1-C5 cleanup requirements executed; zero dangling Parakeet/old-VL
  references (grep-clean).

## Requirements

### REQ-0（gate): Pre-implementation verifications V1-V3
**User Story:** As the owner I want the architecture-risks proven first so that
no implementation is built on a false premise.

**Verified:** NEW — these are probes against reality, code cannot pin them.

**Acceptance Criteria:**
- AC0.1 (V1): WHEN llama-server (the project's bundled build) serves
  d1-3B-AD-Q4_K_M.gguf THEN THE SYSTEM SHALL produce a calibrated structured
  decision answer (prompt template + logprobs over the noul/choice/score
  criteria tokens, per LiquidAI/d1-3B's documented API semantics) that a test
  can read as a probability. The owner expects PASS (d1 is a JEV-style
  decision model). IF it unexpectedly fails THEN THE SYSTEM SHALL stop and
  report — no workaround backend is built.
- AC0.2 (V2): WHEN Phonon-2 is installed on this Windows host
  (`pip install fermion-research torch safetensors soundfile scipy zstandard`)
  THEN THE SYSTEM SHALL transcribe a recorded 16 kHz mono test utterance on
  CPU with word-level timestamps, AND SHALL open the live streaming route
  (`GET /v1/audio/stream`) returning interim hypotheses (~0.35 s first, ~2/s
  updates, segment finalization ~0.7 s silence or 30 s cap), with no CUDA
  requirement (CUDA is a Linux container image only,
  ghcr.io/fermionresearch/phonon-cuda).
- AC0.3 (V3): THE SYSTEM SHALL enumerate, with file:line evidence, every caller
  of the standalone Parakeet :8765 service and of the in-pipeline Parakeet
  path BEFORE any removal. Current verified enumeration: in-pipeline
  `backend/audio/voice_command.py` (`parakeet_sherpa_worker` subprocess,
  `_WORKER_MODULE` line 87, `_transcribe_via_parakeet` line 1066); service
  launcher `start_all.py:172-173`; REST consumer
  `backend/tools/media_tools.py:23` (`transcribe_media`); warm-up at boot
  `backend/main.py:332-340`; streaming buffer `backend/audio/parakeet_buffer.py`;
  tests `backend/tests/test_parakeet_service.py`,
  `backend/tests/test_parakeet_integration.py`,
  `backend/tests/contract/test_parakeet_provider_contract.py`; duplicate test
  copies under `backend/tests/integration/`.
- AC0.4 (V4): THE SYSTEM SHALL verify Inception Mercury's residency and role
  binding BEFORE the model-pair task runs: where the weights or API live
  (local GGUF path with size, or hosted Inception endpoint), which quant/context
  applies, and that the router binds reasoning=Mercury,
  tool_execution=LFM2.5-2.6B (oracle.md §13.1 message shape). IF Mercury is
  hosted THEN THE SYSTEM SHALL record that its failure mode is a provider
  outage path, not VRAM.

**Edge Cases:**
- V1 fails unexpectedly → d1 vision-only is still delivered; d1-as-Oracle
  work stops and reports (owner expectation: pass).
- V2 fails → Phonon-2 swap blocked; Parakeet stays live; report to owner.
- V4 finds no Mercury access → reasoning role stays on the incumbent
  reasoning model; report to owner before proceeding.

### REQ-1 (phonon-2): Phonon-2 live streaming replaces Parakeet in the audio pipeline
**User Story:** As the user I want speech-to-text running on CPU with interim
results while I speak so that the GPU is free and replies start sooner after
I stop talking.

**Verified:** pipeline shape at `backend/audio/voice_command.py:71-267`
(primary engine as worker subprocess + whisper fallback); engine module
`backend/audio/parakeet_sherpa.py`; streaming buffer precedent
`backend/audio/parakeet_buffer.py` (`Hypothesis`, `ParakeetStreamingBuffer`)
shows the repo already has a streaming-hypothesis data shape to mirror;
model dir `data/models/parakeet-sherpa/`. Phonon-2 live mode verified from
docs by the pin: `fermion listen` and WS `GET /v1/audio/stream`, hypothesis
~0.35 s, updates ~2/s, final at ~0.7 s silence or 30 s cap.

**Acceptance Criteria:**
- AC1.1: WHEN a wake word fires and speech is captured THEN THE SYSTEM SHALL
  stream 16 kHz mono audio to Phonon-2 over its live route and surface INTERIM
  hypotheses on the existing interim-transcript path, with a FINAL segment at
  ~0.7 s silence or the 30 s cap.
- AC1.2: THE SYSTEM SHALL retain faster-whisper (tiny/int8 CPU) as the only
  FINAL-transcript fallback: an interim hypothesis is best-effort (a dropped
  hypothesis is logged, never fatal); a failed FINAL segment falls back to a
  whisper batch re-transcribe of the captured utterance, preserving the
  existing bounded-wait / sticky-failure semantics (`voice_command.py:1019-1135`).
- AC1.3: THE SYSTEM SHALL configure Phonon-2 hotwords (up to 25) for the wake
  word and command vocabulary, where the engine supports them.
- AC1.4: WHILE replacing the engine THE SYSTEM SHALL keep Porcupine wake-word
  detection unchanged — it is independent of the STT engine.
- AC1.5: IF Phonon-2 fails to load or connect THEN THE SYSTEM SHALL fall back
  to faster-whisper exactly as it does for Parakeet today, with the fallback
  visible in `stt_backend`.
- AC1.6: THE SYSTEM SHALL record word-level timestamps from Phonon-2 final
  segments into the reply-latency observability (`_last_stt_timing`), and the
  first-hypothesis latency SHALL be measurable from the same record.

**Edge Cases:**
- Empty audio → same empty-handling as today (log + fallback).
- Stream drops mid-utterance → final segment falls back to whisper batch;
  interim hypotheses already shown are marked provisional, never asserted.
- Interim display path: the pipeline's interim-transcript wiring is Verified
  NEW (traced at implementation; `parakeet_buffer.Hypothesis` is the mirror
  shape); if no downstream consumer exists, hypotheses are logged and the
  final segment drives the turn — report which is true.

### REQ-2 (c1): No simultaneous old+new engines
**User Story:** As the operator I want a hard rule against two ASR engines or
two vision servers so that one 8 GB card is never oversubscribed.

**Verified:** NEW.

**Acceptance Criteria:**
- AC2.1: THE SYSTEM SHALL prove the new path live (measured real task through
  the real backend) BEFORE the old path is switched off.
- AC2.2: WHILE Phonon-2 is being proven THE SYSTEM SHALL keep Parakeet loadable
  ONLY behind an explicit, greppable flag; the default boot path SHALL NOT load
  both.
- AC2.3: IF a configuration resolves to two live ASR engines or two vision
  model paths at once THEN THE SYSTEM SHALL fail loudly at startup with a
  named error, not silently run both.

### REQ-3 (c3): Enumerate-before-remove for all Parakeet artefacts
**User Story:** As the maintainer I want every caller found before removal so
that nothing falls back silently.

**Verified:** caller list from REQ-0 AC0.3.

**Acceptance Criteria:**
- AC3.1: THE SYSTEM SHALL NOT remove `parakeet_sherpa.py`, `parakeet_worker.py`,
  `parakeet_service.py`, `parakeet_buffer.py`, `data/models/parakeet-sherpa/`,
  or `scripts/convert_parakeet_fp16.py` until every caller in the V3
  enumeration is either migrated or retired.
- AC3.2: WHEN the :8765 service is retired THEN THE SYSTEM SHALL update
  `start_all.py` (health gate :172-173) and `backend/tools/media_tools.py`
  (`transcribe_media`, :23) to the Phonon-2 route, or retire the media
  transcribe tool with a named, greppable error.
- AC3.3: THE SYSTEM SHALL update or delete every Parakeet test listed in V3 in
  the same change as the code they cover (no orphaned red/green tests).

**Edge Cases:**
- A consumer missed by V3 and found later → restore, re-enumerate, repeat;
  the event is recorded as a PiN.

### REQ-4 (d1-vision): d1-3B as the primary vision source
**User Story:** As the user I want image/screen understanding served by the
owner's d1 build so that one model serves judgment and sight.

**Verified:** vision is consumed via `LFMVLProvider`
(`backend/tools/vision_provider.py`), a client of the SHARED llama-server
(port 8082, `IRIS_VISION_PORT`); resolution goes through
`InferenceRouter.resolve_vision_provider()` (`backend/agent/inference/router.py:888`)
and is proven by a real multimodal probe — a 32x16 red/blue PNG the model must
name (`vision_provider.py:79-86`). Vision-capable model discovery reads the
model registry scan (`mmproj_path` attached by stem match;
`test_scan_models_baseline.py`). No vision server is spawned from the provider
(specs/vision-single-server).

**Acceptance Criteria:**
- AC4.1: WHEN the shared llama-server hosts d1-3B-AD-Q4_K_M.gguf WITH
  `--mmproj mmproj-d1-3B-BF16.gguf` THEN THE SYSTEM SHALL route vision traffic
  to it only after the red/blue capability probe passes against d1.
- AC4.2: THE SYSTEM SHALL carry a registry entry making the d1+mmproj pair
  discoverable and selectable (models/gguf/.iris_model_settings.json plus the
  scan path), so the UI Models card can load it with the projector.
- AC4.3: IF d1 fails the capability probe THEN THE SYSTEM SHALL fail loudly
  (`VisionModelUnavailable`) and SHALL NOT silently fall back to any retired
  VL model — retirement is explicit (REQ-11).
- AC4.4: THE SYSTEM SHALL drop the separate VL GGUF from the live path when d1
  carries vision, freeing its VRAM (per the work-order budget).
- AC4.5: Vision consumers (`vision/browser_pool.py`, `vision/screen_monitor.py`,
  `vision/fetch_vision.py`, `vision/session_vision_adapter.py`,
  `vision/search_discovery.py`, `agent/vision_guided_operator.py`,
  `tools/vision_mcp_server.py`) SHALL require no calling-code changes — they
  consume `get_vision_provider()` and the shared-server contract, not a model
  name. Verified: all listed files import the provider, not a model id.
- AC4.6: THE SYSTEM SHALL bind the two Brain roles independently of the vision
  change (oracle.md §13.1): reasoning = Inception Mercury,
  tool_execution = LFM2.5-2.6B-Q4_K_M, verified by V4 (REQ-0 AC0.4) before the
  binding is set live.

**Edge Cases:**
- d1 quant (AD-Q4_K_M) token throughput hit with projector attached: measured
  ~-35% gen on gemma-4-E4B per UI copy (ModelBrowserPanel.tsx:648); a degraded
  gen rate is acceptable; a failing probe is not.

### REQ-5 (d1-oracle): d1-3B as the Oracle decision backend (gated by V1)
**User Story:** As the system I want the Oracle's calibrated decision output
served by d1 so that one owned model carries judgment.

**Verified:** Oracle engine `backend/agent/decision_engine.py`; current backend
`backend/agent/decision_backend_onnx.py` (`GlinerOnnx`, backend_id
`gliner25-decide-onnx-int8` line 500); the identity keys every calibrated
threshold (`decision_engine.py` docstring lines 5-15; `_current_backend_identity`
line 317); `decide(consumer_id, options, frame)` + `generate_args` contract
(lines 25-36); Jobs own input construction (section 19 of oracle.md;
`job_input` at decision_engine.py:~139).

**Acceptance Criteria:**
- AC5.1: THE SYSTEM SHALL implement a d1 decision backend that
  satisfies the `decide()` contract: caller-provided option set + feature frame
  -> calibrated probability distribution, one question per run (oracle.md §9:
  batching deliberately removed; guard test
  `backend/tests/behavioral/test_batch_single_encode.py` must stay green),
  never writing text, never calling a provider.
- AC5.2: THE SYSTEM SHALL give the d1 backend a NEW, variant-derived backend
  identity string (the quant IS the identity — oracle.md §5 levers;
  AD-Q4_K_M is not bf16), keyed in `backend_thresholds` under its own entry.
- AC5.3: THE SYSTEM SHALL fail-closed for every consumer until its calibration
  is re-earned on d1: with no d1 threshold fitted, `decides(consumer)` returns
  None and the incumbent decides (current mechanism: `_enforcement`,
  decision_engine.py:436-453). Old GLiNER rows SHALL be counted
  `other_backend`, not deleted (oracle.md §16, line 759).
- AC5.4: WHILE d1 is the Oracle THE SYSTEM SHALL NOT combine d1's generative
  ability with the Oracle role: no prose, no argument generation (§9 "No
  prose"); `generate_args` continues to degrade to the Brain ladder.
- AC5.5: IF d1's latency per decision exceeds the GLiNER baseline (~154 ms p50
  intra-4, §8.1) by more than 3x on the shadow lane for 95% of runs, THE
  SYSTEM SHALL record the measurement and the owner is consulted before
  proceeding — the Oracle must not become a turn-latency problem on the
  `oracle_shadow` lane.

**Edge Cases:**
- llama-server unreachable mid-turn → engine unavailable, legacy path,
  counted (`unavailable_events`), never a block on the reply path.
- The model answers off-menu → treated as the lowest-confidence outcome,
  never as agreement.

### REQ-6 (recalibration): Recalibrate the Oracle on the d1 identity
**User Story:** As the operator I want thresholds earned on the deployed
weights so that enforcement is evidence, not carry-over.

**Verified:** fit script `scripts/fit_oracle_calibration.py` (isotonic +
5-fold out-of-fold ECE/Brier/AUROC; MIN_BLOCK 20; threshold = smallest
calibrated t at precision >= 0.90, Wilson LB >= 0.85, >= 50 rows above it);
writes `benchmarks/oracle_calibration.json`; bar in
`backend/agent/consumer_bar.py` (`derive_status`: rows >= 100 distinct,
AUROC >= 0.65, ECE <= 0.05); report `scripts/consumer_enforcement_report.py
--write` -> `benchmarks/consumer_bar_record.json`; rows land via
`system_events` actor=agent_tool_bridge outcome='shadow'.

**Acceptance Criteria:**
- AC6.1: WHEN d1 becomes the Oracle THEN THE SYSTEM SHALL collect >= 100
  DISTINCT rows per consumer on the d1 weights BEFORE any enforcement flip
  (duplicate-collapse rule already in the fit/load path).
- AC6.2: THE SYSTEM SHALL refit `oracle_calibration.json` and re-derive the
  bar record on d1, and SHALL NOT carry any GLiNER-earned enforcement across
  (measured-on check at decision_engine.py:369-386 already enforces this —
  verify with `test_bar_record_enforcement.py`).
- AC6.3: THE SYSTEM SHALL record in the spec/design which consumers earned the
  bar on d1, and switch enforcement ONLY via `IRIS_DECISION_ENFORCE` after
  owner review.
- AC6.4: IF a consumer cannot reach 100 distinct rows on real traffic THEN THE
  SYSTEM SHALL say so in the report rather than padding with repeats
  (oracle.md §11.5/§0.1 duplicate-row history).

### REQ-7 (b1): Ground-truth labels where they exist
**User Story:** As the owner I want the Oracle able to BEAT its incumbent so
that calibration is not capped at the incumbent's quality.

**Verified:** THE LABEL IS THE CEILING (oracle.md §7.1, §0.2 line 44-46:
labels are agreement with the incumbent). Measured live 2026-10-08: `mode`'s
incumbent is `mode_detector._infer_mode`, a substring keyword scorer
(`backend/agent/mode_detector.py:311`, default IMPLEMENT/0.3) -> AUROC 0.4906.

**Acceptance Criteria:**
- AC7.1: WHERE an outside label exists (test outcome, user correction,
  observed completion) THE SYSTEM SHALL record it on the decision row as the
  calibration label, in preference to incumbent agreement.
- AC7.2: THE SYSTEM SHALL keep incumbent-agreement as the label only where no
  outside label exists, and the fit SHALL report which label source each
  consumer's curve is built on.
- AC7.3: `mode` SHALL carry a ground-truth label when the observed outcome is
  knowable, so its curve can be measured against reality — NOT against
  `_infer_mode`.

**Edge Cases:**
- A consumer with zero outside-label rows keeps its incumbent-agreement curve;
  no consumer may silently mix label sources in one curve.

### REQ-8 (b3): De-bias structurally biased consumers
**User Story:** As the owner I want review_verdict and user_feedback re-shaped
so that their curves are estimable.

**Verified:** review_verdict biased to "refine" (incumbent says pass 96%);
user_feedback 2.4% minority (oracle.md §0.6 table).

**Acceptance Criteria:**
- AC8.1: THE SYSTEM SHALL rework the review_verdict prompt/options so the
  incumbent no longer answers one class 96% of the time, then refit.
- AC8.2: THE SYSTEM SHALL rework the user_feedback options so both classes are
  reachable, then refit.
- AC8.3: IF after rework a consumer still has a one-class reference THEN THE
  SYSTEM SHALL report it as non-estimable and leave it shadow — never pad.

### REQ-9 (b4): depth_route/depth_met scoring fires at the consult site
**User Story:** As the owner I want the continuation-depth question scored
where the monitor actually asks it so that its rows exist.

**Verified:** `depth_met` consult sits in the kernel continuation gate
(`agent_kernel.py:7305-7503`, `_der_note_depth_route` at :20738; the gate
itself skipped during COMPRESS per :20042-20068 and skipped when the goal
contract is met per :20071-20079); the pin's claim "wired only where done is
True / done has 0 rows" is superseded by session-366 instrumentation at
:20026-20041 making the gate visible — the fix target is that scoring fires
at the monitor consult itself.

**Acceptance Criteria:**
- AC9.1: WHEN the continuation consult runs THEN THE SYSTEM SHALL score the
  depth question at that consult (the monitor consult itself), not at a
  downstream conditional.
- AC9.2: THE SYSTEM SHALL emit a visibility log line (as the continuation gate
  does at :20037-20041) whenever the depth consult is skipped, with the skip
  reason named.
- AC9.3: THE SYSTEM SHALL NOT re-add depth scoring to the reply path — shadow
  on the `oracle_shadow` lane (oracle.md §0.5).

### REQ-10 (b5): The local-goal web veto applies at menu build
**User Story:** As the owner I want a local task to never reach a web tool, on
every route, so that the measured bypass cannot recur.

**Verified:** veto lives in `ToolDecisionBox.resolve()`-adjacent logic and the
memory fallback now takes a `vetoed` set (`tool_decision.py:915-956`, "session
366, track B"); the pin's measured bypass chose via `source=memory` through a
route that never saw the set (`tool_decision.py:948-955`, :1918-2001 multiple
`source="memory"` sites). Related shipped guard:
`backend/agent/external_reference.py` (commit dc7139bc).

**Acceptance Criteria:**
- AC10.1: THE SYSTEM SHALL apply the local-goal web veto WHERE THE CANDIDATE
  MENU IS BUILT, so every route (engine ladder, legacy ladder, memory
  fallback, any future route) inherits it.
- AC10.2: IF a local goal's menu would contain a web tool THEN THE SYSTEM
  SHALL exclude it before any consumer sees the menu, and log the exclusion.
- AC10.3: THE SYSTEM SHALL be covered by a contract test that fails on the
  pre-fix shape (a memory-suggested web tool for a local goal reaches the
  menu).

**Edge Cases:**
- Empty menu after veto → escalate to the Brain, never silently pick a vetoed
  tool.

### REQ-11 (c2, c4): Explicit retirement flags + registry cleanup
**User Story:** As the maintainer I want retirement greppable so that nothing
silently falls back to Parakeet or the old VL model.

**Verified:** registry `models/gguf/.iris_model_settings.json` lists
LFM2.5-VL-3B-Q4_K_M.gguf and LFM2.5-8B-A1B(-UD)-Q* entries to be retired from
the live path; UI Models card reads the scan/registry
(`components/dashboard/ModelBrowserPanel.tsx`).

**Acceptance Criteria:**
- AC11.1: THE SYSTEM SHALL carry one explicit retirement constant/env per
  retired asset (STT engine, VL model, superseded model entries) so
  `grep` finds every retirement point.
- AC11.2: THE SYSTEM SHALL remove retired models from the selectable registry
  entries so the UI cannot re-select them.
- AC11.3: IF code references a retired asset at runtime THEN THE SYSTEM SHALL
  fail loudly with a named error naming the retirement constant — never a
  silent fallback.
- AC11.4 (C5): WHEN verification (REQ-13) passes THEN THE SYSTEM SHALL remove
  Parakeet artefacts, the superseded VL pair, and now-dead env vars, in a
  reviewable diff whose commit message names what was verified.
- AC11.5 (C5, owner extension): WHEN the d1 Oracle is live-verified (TG-3
  green) THEN THE SYSTEM SHALL remove GLiNER Decider 2.5 as CODE:
  `backend/agent/decision_backend_onnx.py`,
  `backend/models/gliner2.5-decide-onnx/`, its vendored runner, and its env/
  config switches, with every GLiNER-pinning test updated or removed in the
  SAME change. The Ledger never forgets: old calibration rows stay as
  `other_backend` history (oracle.md §16), and oracle.md §0 is rewritten to
  name d1 the current engine in the same change. The "no fallback model" rule
  (§9) already means the loss of GLiNER needs no safety net: without a
  backend the engine is unavailable and the incumbent decides.

### REQ-12 (b6, b7): Calibration-store hygiene
**User Story:** As the analyst I want the ledger to not accumulate duplicates
and the consumer vocabulary to match reality so that measurements stay honest.

**Verified:** fit skips `duplicates: 10541` but the STORE accumulates repeats
(B6); `retry_same` is declared in `CONSUMERS`
(`decision_engine.py:89`) with no row of its own — it rides
`recovery_strategy` as the `retry_same_offered` field
(`tool_decision.py:2619`; oracle.md §11.5 confirms and prescribes: removing it
means updating the pinned enumerations and their tests in ONE change).

**Acceptance Criteria:**
- AC12.1: THE SYSTEM SHALL prevent duplicate shadow rows at WRITE time
  (identity = consumer + normalized input), not only skip them in the fit.
- AC12.2: THE SYSTEM SHALL remove `retry_same` from the `CONSUMERS` enumeration
  and update every pinned-enumeration test in the SAME change
  (`test_decision_engine_contract.py`, `test_surface_observer_contract.py`,
  `test_decision_engine_gates.py`, `test_oracle_calibration_contract.py`,
  `test_verdict_consumer_shape.py` at minimum).
- AC12.3: THE SYSTEM SHALL keep `retry_same_offered` as a FIELD on
  `recovery_strategy` rows.

### REQ-13 (b8, live): Test-harness fix + live verification gates
**User Story:** As the owner I want the whole swap proven live, not only in
unit tests, so that green means real.

**Verified:** wave5 replay test INTERNALERROR "Bad file descriptor" in 15-25%
of runs since scoring moved to the lane
(`backend/tests/behavioral/test_wave5_replay_behavior.py`; oracle.md §0.7 item
4). Live verification method: app-testing skill Mode A
(`.opencode/skills/app-testing/SKILL.md`).

**Acceptance Criteria:**
- AC13.1: THE SYSTEM SHALL stub the decision engine in
  `test_wave5_replay_behavior.py` so it never loads the real model on a lane
  thread; the test SHALL pass 20 consecutive runs.
- AC13.2: WHEN Phonon-2 is live THEN a measured voice turn SHALL show
  `stt_backend` = the Phonon-2 path (never `parakeet*`) end to end, WITH an
  interim hypothesis surfaced before the final segment (first-hypothesis
  latency recorded from `_last_stt_timing`).
- AC13.3: WHEN d1 carries vision THEN a measured vision task SHALL pass
  through the shared server hosting d1 with the probe proof recorded.
- AC13.4: WHEN d1 is the Oracle THEN a measured eval run (evals/run_evals.py
  on the tasks the change touches) SHALL show decision rows with the new
  backend identity on them, and reply_s SHALL NOT regress beyond the measured
  pre-swap baseline + 15%.
- AC13.5: VRAM SHALL be measured live after the swap and recorded;
  LFM2.5-8B-A1B co-residency with d1 SHALL be asserted absent.
- AC13.6: WHEN the role pairing is live THEN a measured turn SHALL show the
  router resolving reasoning to Mercury and tool execution to
  LFM2.5-2.6B-Q4_K_M (resolution log line, not assumption).

### REQ-14 (observability): Swap observability
**User Story:** As the tuner I want the swap's effects measurable so that the
next iteration can tune.

**Verified:** existing instruments — `_last_stt_timing` fields
(`voice_command.py:566`), the once-per-process enforcement log
(`decision_engine.py:459-479`), consumer bar report script.

**Acceptance Criteria:**
- AC14.1: THE SYSTEM SHALL log, per voice turn, engine identity
  + time-to-transcript + fallback reason if any (`stt_backend` field).
- AC14.2: THE SYSTEM SHALL log once per process which Oracle backend identity
  is active and which consumers decide and why each allowed one does not.
- AC14.3: WHEN a retired asset is attempted THE SYSTEM SHALL log the
  retirement constant name, not only the failure.

**Edge Cases:**
- High-volume logging → all above is off the reply path or once-per-process.

## Non-Requirements (Out of Scope)
- LFM2.5-8B-A1B co-resident with d1 (does not fit; explicitly excluded).
- Re-wiring the `mode` consumer into node mode (deliberately structural via
  external_reference; owner decision).
- A new transformers/trust_remote_code inference path for d1. If the existing
  llama.cpp stack cannot serve the decision output (unexpected V1 fail), work
  stops and reports — a second inference stack is never built.
- Retuning the ORT/llama intra-op thread counts (measured optimum stands,
  oracle.md §8.1).
- Keeping GLiNER Decider 2.5 or Parakeet behind a flag "just in case" — the
  owner chose deletion after verification; git history is the archive.

## Open Questions
- None open. OQ-1..OQ-4 resolved by the owner 2026-10-08 and moved to
  Decisions Locked: d1 IS JEV-style and expected to verify (V1 = verification,
  not feasibility); Phonon-2 LIVE STREAMING mode is in scope and required;
  tool calling = LFM2.5-2.6B paired with Inception Mercury for reasoning
  (residency verified by V4); Parakeet AND GLiNER are both deleted after
  verification.

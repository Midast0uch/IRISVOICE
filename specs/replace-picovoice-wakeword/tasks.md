# Tasks: IRIS Audio Pipeline Overhaul

> Each task links to a requirement. Tasks are intentionally dependency-ordered and include ripple notes.
> This spec was broadened in session 278 to cover the entire audio pipeline, including the TTS subprocess worker (Wave 7).

## Wave 0 — Baseline and API audit

- [ ] T0 (REQ-1, REQ-3): Establish a green baseline for wake/audio/STT suites and inspect the installed `violawake` package/source for custom ONNX loading, OpenWakeWord assets, input shape, and CPU provider support — `backend/voice/` + environment — RIPPLE: blocks every detector implementation decision; do not guess the API.
- [ ] T1 (REQ-1, REQ-3): Validate `data/hey iris_237_1788045452.onnx` with ONNX metadata and the audited Viola loader — `scripts/validate_wake_pipeline.py` — RIPPLE: model path resolution, package dependencies, and status diagnostics.

## Wave 1 — Configuration and detector seam

- [ ] T2 (REQ-2, REQ-3): Add engine-neutral wake configuration for `Hey Iris` and the project-root-relative ONNX path — `backend/agent/wake_config.py` — RIPPLE: gateway config payloads and persisted settings must stop assuming `.ppn`.
- [ ] T3 (REQ-1, REQ-3, REQ-5): Implement the audited ViolaWake adapter with bounded 320-sample buffering, CPU-first ONNX provider, normalized `(detected, phrase)` output, and lifecycle status — `backend/voice/violawake_detector.py` — RIPPLE: detector API is the contract boundary for AudioEngine and all tests.
- [ ] T4 (REQ-3): Extend discovery/resolution for the trained `.onnx` model while retaining deterministic project-root/worktree behavior — `backend/voice/wake_word_discovery.py` — RIPPLE: config UI and startup diagnostics consume resolved model metadata.

## Wave 2 — Audio pipeline migration

- [ ] T5 (REQ-1, REQ-4): Replace Porcupine construction and processing with the Viola adapter while preserving wake gate, TTS suppression, callback, cooldown, and bounded frame conversion — `backend/audio/engine.py` — RIPPLE: startup diagnostics, audio callback latency, wake event contract, and barge-in.
- [ ] T6 (REQ-2, REQ-7): Remove active Picovoice/Porcupine runtime imports, key reads, `.ppn` fallback, and misleading error text after T5 is green — `backend/voice/porcupine_detector.py`, `backend/audio/engine.py`, `.env` — RIPPLE: existing Porcupine regression tests must be replaced, not silently deleted.
- [ ] T7 (REQ-6): Preserve or version wake readiness/error status and activation event payloads at every gateway/frontend seam — `backend/main.py`, `backend/iris_gateway.py`, `hooks/useIRISWebSocket.ts` if traced — RIPPLE: frontend must not interpret detector errors as wake activations.

## Wave 3 — STT and system ripple verification

- [ ] T8 (REQ-4): Keep Parakeet primary and ensure asynchronous warm-up never blocks a voice caller; route loading, empty, exception, and unavailable states to faster-whisper — `backend/audio/voice_command.py` — RIPPLE: model/GPU/RAM pressure, audio-thread latency, and live startup behavior.
- [ ] T9 (REQ-4): Add/maintain tests that faster-whisper is actually called and returns a transcript when Parakeet is loading or fails — `backend/tests/unit/test_voice_command_parakeet.py` — RIPPLE: guards the required backup path and prevents future "Parakeet-only" regressions.
- [ ] T10 (REQ-5): Verify detector inference and Parakeet/faster-whisper work do not block the asyncio event loop or Tauri WS liveness — `backend/tests/behavioral/` + live harness — RIPPLE: covers the backend wedge and widget freeze class, not just unit correctness.

## Wave 4 — Contract and behavioral tests

- [ ] T11 (REQ-1, REQ-3): Add CT-WW-1/CT-WW-2 for audited custom-ONNX loading and exact 16 kHz/320-sample input — `backend/tests/contract/test_violawake_detector_contract.py` — RIPPLE: catches installed-package/API drift before live microphone tests.
- [ ] T12 (REQ-4, REQ-6): Add CT-WW-3/CT-WW-5 for stable callback/status behavior and detector failure isolation — `backend/tests/contract/test_audio_wake_contract.py` — RIPPLE: locks the downstream wake-to-voice seam.
- [ ] T13 (REQ-2, REQ-7): Replace Porcupine regression coverage with CT-WW-4 and migration tests asserting no Picovoice key/path is required — `backend/tests/contract/test_violawake_migration_contract.py` — RIPPLE: prevents the removed dependency from returning through a fallback branch.
- [ ] T14 (REQ-1, REQ-4, REQ-5): Behavioral replay of positive/negative audio, cooldown, TTS suppression, detector failure, Parakeet loading, and faster-whisper fallback — `backend/tests/behavioral/test_violawake_audio_pipeline.py` — RIPPLE: verifies the whole audio path rather than isolated modules.
- [ ] T15 (REQ-8): Add bounded detector telemetry and a standing offline/live harness — `scripts/validate_wake_pipeline.py` — RIPPLE: supplies evidence for threshold and latency tuning without raw audio or secrets.

## Wave 5 — Dependency and packaging cleanup

- [ ] T16 (REQ-2, REQ-7): Update Python dependency manifests and packaging to include the audited ViolaWake/ONNX/OpenWakeWord runtime and remove Porcupine only after the suite is green — project dependency files — RIPPLE: clean installs, Tauri bundle startup, and CI environment.
- [ ] T17 (REQ-7): Keep the old `.ppn` and user model data untouched unless explicitly cleaned later; document migration of persisted settings — `docs/` or spec migration notes — RIPPLE: protects user data and rollback clarity.

## Wave 6 — Acceptance

- [ ] T18 (REQ-1-REQ-8): Run the full acceptance matrix: unit, contract, behavioral, standing harness, live microphone wake, manual recording, Parakeet primary, faster-whisper backup, Tauri reconnect, and no-key startup — test reports — RIPPLE: final gate for replacing the old wake engine.
- [ ] T19 (REQ-8): Record a redacted decision pin with model path basename, Viola package/API version, detector backend, threshold, measured latency, and fallback results — MCM — RIPPLE: future sessions can reproduce the exact working setup.

## Wave 7 — TTS subprocess worker

- [ ] T20 (REQ-9): Implement the TTS subprocess entry point — JSONL stdin/stdout loop that loads Pocket-TTS, accepts synthesize/set_voice/pre_synthesize_fillers commands, streams base64 audio chunks, and handles shutdown — `backend/audio/tts_worker.py` — RIPPLE: the worker is the GIL-free synthesis engine; every TTS feature depends on it.
- [ ] T21 (REQ-9): Refactor `TTSManager` into a proxy that spawns the subprocess, sends JSONL commands, reads base64 audio from stdout, and yields numpy arrays — `backend/agent/tts.py` — RIPPLE: `synthesize_stream` signature must stay identical; every caller works unchanged.
- [ ] T22 (REQ-9, REQ-10): Move voice state loading (`_load_voice_state`, `_load_catalog_voice`, `_load_pocket_tts`) into the subprocess worker — `backend/audio/tts_worker.py` — RIPPLE: voice cloning, catalog voices, and the "alba" fallback chain must all work identically.
- [ ] T23 (REQ-9): Move filler pre-synthesis (`_pre_synthesize_fillers`) into the subprocess worker — `backend/audio/tts_worker.py` — RIPPLE: `get_filler_audio()` must still return valid audio from the main process cache.
- [ ] T24 (REQ-9): Add subprocess crash detection and auto-restart — `backend/agent/tts.py` — RIPPLE: a crash mid-synthesis must raise a typed error so the caller can retry; the proxy must not silently hang.
- [ ] T25 (REQ-9, REQ-10): Add contract tests for the IPC protocol: chunk shape, sample rate, base64 encoding, done/fill_ready/voice_loaded message shapes, error handling, and shutdown — `backend/tests/contract/test_tts_subprocess_contract.py` — RIPPLE: pins the IPC boundary so the worker and proxy can be developed independently.
- [ ] T26 (REQ-9, REQ-10): Add integration tests: subprocess startup, synthesis through the proxy, voice switching, filler pre-synthesis, crash recovery, and concurrent request serialization — `backend/tests/integration/test_voice_pipeline.py` — RIPPLE: verifies the full TTS path end-to-end.
- [ ] T27 (REQ-9): Verify that TTS synthesis no longer blocks the asyncio event loop by measuring WS heartbeat latency during synthesis — `backend/tests/behavioral/` + live harness — RIPPLE: the acceptance gate for the GIL contention fix.

## Dependency / parallelization notes

- T0 gates T1-T5 because custom ONNX loading is not documented; no code may invent a loader API.
- T2, T3, and T4 can proceed in parallel after T0, but T5 depends on all three.
- T5 and T8 are distinct runtime seams and may be developed in parallel; T10 must exercise them together because they compete for CPU/GPU/RAM resources.
- T6 must follow T5 and the contract suite; removing Porcupine first would leave the audio pipeline without a detector during migration.
- T7 is a contract-lock task even if no frontend code changes: the existing event grammar must be proved, not assumed.
- T9 is mandatory even if Parakeet loads quickly in development; it proves the user-requested backup remains real.
- T11-T15 can run in parallel after the adapter seam exists; T14 is the acceptance gate.
- T16 is last in implementation order so a clean install is updated only after the audited runtime and tests are stable.
- Do not delete the user's `.ppn` or ONNX assets as part of these tasks.
- **T20-T27 (Wave 7) are independent of Waves 0-6.** The TTS subprocess worker does not depend on the ViolaWake migration and can be developed in parallel. The two changes share only the architectural pattern (subprocess for GIL-bound work) and the same test infrastructure.
- **T28 (documentation):** Update `docs/architecture/audio-pipeline.md` after Waves 0-6 and Wave 7 are complete — replace Porcupine references with ViolaWake, update TTS thread architecture to reflect subprocess, update memory budget table, and update the wake-word flow diagram. This is a post-implementation task; do not update the doc mid-implementation or it will drift from the code.
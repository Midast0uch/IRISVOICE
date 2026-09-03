# Requirements: IRIS Audio Pipeline Overhaul

> This spec was originally scoped to "Replace Picovoice wake word with ViolaWake"
> (session 274). It was broadened in session 278 to cover the entire audio
> pipeline, including the Pocket-TTS subprocess worker that eliminates GIL
> contention during speech synthesis. Both changes share the same architectural
> pattern — CPU-bound model inference in the same Python process as the asyncio
> event loop — and the same fix: move to a subprocess.

## Decisions Locked

- The wake phrase is **Hey Iris**.
- The trained model is `data/hey iris_237_1788045452.onnx`.
- Picovoice/Porcupine and the Picovoice access key are being removed; the stale key must not be required for startup.
- Parakeet remains the primary speech-to-text backend. faster-whisper remains a working fallback and is not removed.
- The existing IRIS audio pipeline, wake callback, TTS gating, barge-in behavior, and WebSocket event grammar remain stable unless a contract test proves a change is required.
- The implementation must verify the installed ViolaWake package's custom-ONNX loading API before coding. Public documentation confirms `WakeDetector`, 16 kHz mono int16 20 ms / 320-sample frames, and an OpenWakeWord runtime dependency, but does not document whether `WakeDetector(model=...)` accepts a filesystem path.
- Pocket-TTS moves to a subprocess (`backend/audio/tts_worker.py`) to eliminate GIL contention with the asyncio event loop. The `synthesize_stream` generator signature stays identical so every caller works unchanged.
- The TTS subprocess communicates via JSONL over stdin/stdout (portable, no sockets, no port conflicts).

## Introduction

IRIS currently initializes Porcupine with a stale Picovoice key and a `.ppn` model. Initialization fails, the audio engine disables wake detection, and the rest of the voice pipeline receives no wake event. ViolaWake provides the replacement ONNX-first wake detector and the project already contains the trained Hey Iris ONNX model.

### Success criteria

- Startup has no Picovoice access-key failure and no Porcupine initialization attempt.
- The Hey Iris ONNX model is discovered deterministically and validated before the detector is enabled.
- The audio callback continues to process 16 kHz mono audio without allocating unbounded buffers or blocking the event loop.
- A real wake detection invokes the existing IRIS wake callback exactly once per cooldown window.
- TTS playback still suppresses wake detection and existing barge-in behavior remains intact.
- Missing/invalid ViolaWake or ONNX dependencies fail closed for wake detection while audio capture and faster-whisper STT remain available.
- Existing backend/frontend contracts and standing audio tests remain green.

## Requirements

### REQ-1: Use ViolaWake as the wake detector

**User Story:** As an IRIS user, I want the assistant to listen for Hey Iris using the trained ONNX model so that wake detection works without a Picovoice key.

**Verified:** `backend/audio/engine.py:170-269` currently owns detector construction and `backend/voice/porcupine_detector.py:36-230` owns Porcupine initialization. ViolaWake integration is NEW.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL construct a ViolaWake detector for the Hey Iris model and SHALL NOT construct `PorcupineWakeWordDetector` during normal startup or reinitialization.
- AC2: THE SYSTEM SHALL use the trained model at `data/hey iris_237_1788045452.onnx`, resolved from the project root rather than the process working directory.
- AC3: THE SYSTEM SHALL use 16 kHz, mono, signed int16 PCM frames with 320 samples / 20 ms per ViolaWake inference frame.
- AC4: THE SYSTEM SHALL preserve the existing wake callback contract: a successful detection SHALL invoke the registered callback with a stable wake phrase identifier.

**Edge Cases:**

- The model path contains spaces.
- The backend is launched from a worktree or a directory other than the project root.
- The ONNX file is missing, unreadable, malformed, or has an incompatible input shape.
- ViolaWake is installed without its required OpenWakeWord runtime dependency.

### REQ-2: Remove Picovoice dependency and configuration

**User Story:** As an operator, I want Picovoice removed from the runtime configuration so that an expired or invalid key cannot disable audio startup.

**Verified:** `backend/voice/porcupine_detector.py:17-24,78-88`, `backend/audio/engine.py:18,190-266`, and `.env:9-12` currently depend on Picovoice/Porcupine.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL not read `PICOVOICE_ACCESS_KEY` for wake detection.
- AC2: THE SYSTEM SHALL not require `WAKE_WORD_PPN` or a `.ppn` file to enable wake detection.
- AC3: THE SYSTEM SHALL remove or deprecate Porcupine-specific runtime modules and imports only after all callers and tests have migrated.
- AC4: IF an obsolete Picovoice setting remains in an existing `.env` file THEN THE SYSTEM SHALL ignore it without logging or exposing the key value.

**Edge Cases:**

- Existing users have old `.ppn` files and stale access keys.
- An old persisted wake configuration contains a custom `.ppn` path.
- The Picovoice Python package is absent.

### REQ-3: Discover and validate the trained ONNX model

**User Story:** As an operator, I want model discovery to report a precise configuration error so that a missing Hey Iris model is diagnosable without making the whole audio pipeline fail.

**Verified:** `backend/voice/wake_word_discovery.py:34-183` only discovers filename-shaped `.ppn` files today. ONNX discovery and ViolaWake validation are NEW.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL resolve the default model path relative to the project root and SHALL allow an explicit non-secret configuration override for deployments.
- AC2: THE SYSTEM SHALL validate file existence, extension, file readability, and the ONNX model's input contract before enabling detection.
- AC3: THE SYSTEM SHALL verify the installed ViolaWake API can load a custom ONNX path; it SHALL not assume the undocumented `WakeDetector(model=path)` form is valid.
- AC4: WHEN validation fails THEN THE SYSTEM SHALL set wake detection to disabled, preserve audio capture and STT, and emit a structured diagnostic naming the missing dependency/model/shape without including secrets.

**Edge Cases:**

- A valid ONNX file is present but its model head requires a different OpenWakeWord embedding shape.
- The model file is replaced while IRIS is running.
- Multiple candidate ONNX files exist.
- The model is CPU-only while the rest of the machine is under GPU pressure.

### REQ-4: Preserve audio pipeline behavior

**User Story:** As an IRIS user, I want the wake engine replacement to be invisible to recording, STT, TTS, and barge-in so that fixing wake detection does not break voice interaction.

**Verified:** `backend/audio/engine.py:57-63,96-115,542-590` owns wake gating, TTS suppression, frame conversion, and callback dispatch. `backend/audio/voice_command.py:887-916` owns Parakeet-first STT and faster-whisper fallback.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL preserve `_wake_word_enabled` gating and SHALL not process wake inference while TTS is active.
- AC2: THE SYSTEM SHALL preserve the existing float32 audio callback input and SHALL convert only the detector frame view to int16 PCM.
- AC3: THE SYSTEM SHALL preserve the existing callback invocation and cooldown behavior.
- AC4: THE SYSTEM SHALL keep Parakeet as the primary STT path and faster-whisper as the fallback when Parakeet is unavailable, still loading, returns empty text, or raises.
- AC5: IF ViolaWake initialization fails THEN THE SYSTEM SHALL not prevent faster-whisper from transcribing a manually started or otherwise authorized recording.

**Edge Cases:**

- Audio arrives in chunks larger or smaller than 320 samples; the detector adapter must carry only a bounded remainder between calls.
- TTS starts or stops mid-frame.
- A wake callback raises; the audio capture loop must continue.
- Parakeet is still warming; the current utterance must use faster-whisper rather than queue behind model loading.

### REQ-5: Keep detector work off blocking application paths

**User Story:** As an operator, I want wake inference to remain bounded so that wake detection cannot wedge the backend or freeze the Tauri widget.

**Verified:** `backend/audio/engine.py:572-590` currently runs detector processing from the audio callback thread. The bounded Viola adapter is NEW.

**Acceptance Criteria:**

- THE SYSTEM SHALL process each 20 ms frame without network I/O, model download, filesystem scanning, or unbounded lock waits.
- THE SYSTEM SHALL use a bounded frame remainder and SHALL cap diagnostic logging frequency.
- IF the detector call exceeds the configured per-frame budget THEN THE SYSTEM SHALL record the overrun and continue audio processing without blocking the asyncio event loop.
- THE SYSTEM SHALL expose detector readiness and the last detector error through existing diagnostics or a new non-secret status field.

**Edge Cases:**

- ONNX Runtime initialization is slow on first use.
- CPU saturation occurs while Parakeet or faster-whisper is active.
- The detector produces repeated high scores; cooldown and confirmation must prevent callback storms.

### REQ-6: Preserve user-visible and backend event contracts

**User Story:** As a frontend maintainer, I want wake detection to keep its existing event semantics so that the UI does not need a parallel migration.

**Verified:** `backend/main.py:2658-2660` and gateway/audio callbacks consume a wake phrase; frontend event consumers must be traced during implementation. Event shape is CONTRACT LOCK pending a baseline test.

**Acceptance Criteria:**

- THE SYSTEM SHALL preserve the existing wake-to-IRIS activation event and payload shape unless a contract test documents an intentional versioned change.
- THE SYSTEM SHALL report detector state changes as diagnostics, not as fake wake detections.
- IF wake detection is disabled THEN THE SYSTEM SHALL distinguish disabled, loading, ready, and error states in logs/status.

**Edge Cases:**

- The frontend mounts before the detector is ready.
- The detector becomes unavailable after successful startup.
- Multiple audio clients or Tauri reconnects observe the same detector state.

### REQ-7: Migration and cleanup

**User Story:** As a maintainer, I want the old wake-word path removed cleanly so that future changes cannot accidentally restore the broken Picovoice flow.

**Verified:** `backend/tests/contract/test_porcupine_regression.py` and `backend/tests/test_porcupine_regression.py` explicitly pin current Porcupine assumptions. Migration is NEW.

**Acceptance Criteria:**

- THE SYSTEM SHALL replace Porcupine-specific tests with ViolaWake contract tests before deleting the old implementation.
- THE SYSTEM SHALL remove stale `.ppn` discovery/configuration from active code and SHALL leave no runtime path that silently falls back to Porcupine.
- THE SYSTEM SHALL preserve a migration note for old persisted configuration and SHALL not delete user audio/model data automatically.

**Edge Cases:**

- A test fixture still supplies a `.ppn` path.
- A user upgrades with only the old `.ppn` model present.
- ViolaWake is not installed in a developer environment.

### REQ-8: Observability and acceptance harness

**User Story:** As a tuner, I want timestamped wake detector telemetry so that I can measure false accepts, false rejects, latency, and startup readiness instead of guessing.

**Verified:** `backend/audio/engine.py:31-55` and `backend/main.py:2608-2660` already log wake outcomes and cooldown decisions. Viola-specific telemetry is NEW.

**Acceptance Criteria:**

- THE SYSTEM SHALL log detector lifecycle transitions, model path basename, backend/provider, frame count, score/threshold when safe, detections, suppressed detections, inference latency, and errors.
- THE SYSTEM SHALL scope high-volume telemetry to bounded debug sampling and SHALL never log API keys or raw audio.
- THE SYSTEM SHALL provide a deterministic offline harness that replays labeled 16 kHz mono audio and asserts detection/cooldown behavior.
- THE SYSTEM SHALL provide a live audio smoke test that confirms wake detection, recording, Parakeet-first STT, and faster-whisper fallback behavior.

**Edge Cases:**

- Logs rotate during a long run.
- The model path includes sensitive directory names.
- Audio input is silent or malformed.

### REQ-9: Move Pocket-TTS to a subprocess

**User Story:** As an IRIS user, I want TTS synthesis to not block the backend event loop so that the widget remains responsive during speech output.

**Verified:** `backend/agent/tts.py:422-470` (`_load_pocket_tts`) and `:621-723` (`_stream_pocket`) run in-process and hold the GIL during synthesis. The subprocess worker is NEW.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL spawn a dedicated Python subprocess for Pocket-TTS model loading and streaming synthesis.
- AC2: THE SYSTEM SHALL communicate with the subprocess via JSONL over stdin/stdout (portable, no sockets, no port conflicts).
- AC3: THE SYSTEM SHALL preserve the `synthesize_stream(text) → Generator[np.ndarray, None, None]` signature so every caller (`_speak_response`, `tts_play`, `conversation_kernel.py:490`, `chat.py:255`) works unchanged.
- AC4: THE SYSTEM SHALL preserve zero-shot voice cloning from `TOMV2.wav`, catalog voice loading, and the `_load_voice_state` fallback chain.
- AC5: THE SYSTEM SHALL preserve filler phrase pre-synthesis (`_pre_synthesize_fillers`) and `get_filler_audio()`.
- AC6: THE SYSTEM SHALL preserve text normalization (`_normalize`), sentence chunking (`_split_into_chunks`), inter-sentence silence gaps, and trailing silence.
- AC7: THE SYSTEM SHALL preserve diagnostic audio dumps (`_dump_raw_audio`) and structured playback logging (`[TTSManager] PLAYBACK`).
- AC8: THE SYSTEM SHALL preserve interrupt handling — `interrupted.is_set()` and `is_speech_interrupted()` must still stop synthesis immediately.
- AC9: IF the subprocess crashes mid-synthesis THEN THE SYSTEM SHALL restart it and raise a typed error so the caller can retry.
- AC10: THE SYSTEM SHALL pre-spawn the subprocess at backend startup (same as today's lazy load) so first-use latency is not increased.

**Edge Cases:**

- Subprocess startup is slow (~40s first import of pocket-tts with beartype).
- The subprocess crashes during a long synthesis.
- Multiple concurrent synthesis requests (must serialize through the proxy).
- The subprocess leaks memory over many synthesis calls.
- Windows pipe buffering causes the proxy to block on read.

### REQ-10: Preserve TTS configuration and voice management

**User Story:** As an operator, I want TTS voice selection, speaking rate, and enable/disable to work identically after the subprocess migration.

**Verified:** `backend/agent/tts.py:199-222` (`update_config`, `get_config`, `get_voice_info`) are thin wrappers that stay in the main process.

**Acceptance Criteria:**

- AC1: THE SYSTEM SHALL forward voice selection changes (`set_voice`, catalog voice downloads) to the subprocess via the JSONL protocol.
- AC2: THE SYSTEM SHALL forward configuration changes (`speaking_rate`, `tts_enabled`) to the subprocess.
- AC3: THE SYSTEM SHALL report subprocess readiness and the loaded voice name through `get_voice_info()`.
- AC4: THE SYSTEM SHALL preserve the `AVAILABLE_VOICES` list and catalog voice download logic (`_load_catalog_voice` → `hf_hub_download`).
- AC5: IF the subprocess fails to load a requested voice THEN THE SYSTEM SHALL fall back to the "alba" catalog voice (same as today) and report the error.

**Edge Cases:**

- The subprocess is still loading when a voice change request arrives.
- The HuggingFace Hub is unreachable during catalog voice download.
- The user requests a voice name that does not exist in the catalog.

## Non-Requirements (Out of Scope)

- Retraining the Hey Iris ONNX model.
- Changing Parakeet model architecture or removing Parakeet.
- Removing faster-whisper or replacing the broader STT fallback chain.
- Adding a new frontend wake-word designer.
- Tuning the ONNX threshold from production data before the offline replay harness exists.
- Automatically deleting old `.ppn` files or user model files.
- Fixing the Parakeet GIL starvation (separate subprocess — documented in pin_9d19afdb409b).
- Fixing the frontend lag after local model load (separate event-loop contention during load orchestration — documented in pin_940e6a3d36fb).
- The "TTS plays without voice cloning" issue (config/terms problem in `_load_voice_state` fallback chain — the subprocess preserves the exact same logic).

## Open Questions

- Which exact installed ViolaWake API loads a custom ONNX head, and does it require an OpenWakeWord backbone file/package at runtime? Resolve by inspecting the installed package/source and pin the result in design.md.
- Should the Viola detector run CPU-only to avoid competing with Parakeet/local LLM VRAM, or should ONNX Runtime CUDA be enabled only after a measured benchmark? Recommended default: CPU-only.
- Should the legacy wake settings UI expose only “Hey Iris” for this migration, or remain extensible for future ONNX models? Recommended: keep the data model extensible but expose only the validated model initially.

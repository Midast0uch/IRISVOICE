# Requirements: Backend Memory Optimization and Browser Pool Unification

## Decisions Locked

These were resolved with the user on 2026-09-02. Do not re-litigate them.

1. **Parakeet is 100% preserved.** Parakeet (`nvidia/parakeet-tdt-0.6b-v3`) is the primary voice command transcription engine and must not be removed, replaced, or degraded.
2. **Zero-latency utterance 1 via seamless Whisper bridging.** Eager startup pre-warming of Parakeet is eliminated. When the first voice command arrives post-boot, faster-whisper (`tiny/int8` CPU, <100ms) handles transcription instantly while Parakeet initializes in the background. Once loaded, all subsequent utterances automatically route to Parakeet on GPU.
3. **VAD and Whisper watchdog calibration.** The 60.0s hardcoded watchdog in `voice_command.py` is removed/calibrated to actual audio duration, and the artificial 4.0 GB free-RAM barrier is removed so `faster-whisper` never fails or falls back to external APIs during resource contention.
4. **Agent LLM failure handling in the voice pipeline.** Unhandled LLM exceptions (e.g. rate limits, timeouts) in `iris_gateway._process_voice_transcription` must be caught gracefully and speak/display an informative message, rather than crashing the voice pipeline into `VoiceState.ERROR`.
5. **Websearch remains siloed within the browser domain.** Websearch functionality must remain strictly encapsulated inside the browser panel and crawler subsystem.
6. **Crawler unification into `browser_pool.py` with Fast-HTTP hybrid acceleration.** The separate resident crawl worker pool (`crawl_worker.py --serve`, burning ~700 MB) is eliminated. Crawling unifies with the existing `backend.vision.browser_pool.py`. Within the browser silo, Tier 1 uses lightweight async HTTP extraction (~150ms, 0 MB browser overhead) for static pages, and Tier 2 falls back to `browser_pool.py` for JavaScript, single-page apps, and challenge pages.
7. **Pocket-TTS memory optimization.** Pocket-TTS is a CPU-only model; it masks CUDA (`CUDA_VISIBLE_DEVICES=""`) before torch initialization to avoid loading CUDA runtime DLLs, contexts, and caching allocators, and compacts its working set memory post-load.
8. **Target idle memory baseline is $\le$ 2.5 GB.** Total private memory of all backend processes combined at idle must return from ~8.2 GB to $\le$ 2.5 GB (projected: ~1.8–2.0 GB).

---

## Introduction

Following the memory regression documented in `research/handoff-2026-09-02-memory-regression.md`, the backend idle memory expanded from ~2.5 GB to ~8.2 GB due to simultaneous eager boot-time pre-warming across four child processes: Parakeet worker (4.2 GB), Pocket-TTS (2.3 GB), duplicate Crawl workers (0.7 GB), and the Uvicorn main process (1.4 GB). This severe memory saturation also starved CPU threads and available RAM, triggering premature transcription watchdogs and voice command failures.

This specification defines the requirements to restore the backend idle footprint to $\le$ 2.5 GB, unify crawler execution with the existing browser pool, implement Fast-HTTP hybrid acceleration within the browser silo, and ensure robust, error-free VAD and Whisper fallback.

### Success Criteria

- Total private memory across all backend processes at idle (after startup complete) is **$\le$ 2.5 GB** (measured via OS process tracking).
- Parakeet ASR is retained and operational on GPU.
- First voice command after boot is transcribed within **< 1.0s** via faster-whisper without hanging or throwing `VoiceState.ERROR`.
- Subsequent voice commands automatically route to Parakeet GPU ASR once the worker reports ready.
- Web search progress events (`CRAWLER_STARTED`, `CRAWLER_PAGE_FETCHED`, `CRAWLER_PHASE`, `OPEN_TAB`) continue to stream to the in-app browser panel with zero UI disruption.
- Duplicate resident crawl workers (`crawl_worker --serve`) are eliminated; browser operations utilize `backend.vision.browser_pool` with its 180s idle auto-shutdown.
- An LLM rate-limit or network failure during a voice turn speaks a friendly notice instead of flashing a red `VoiceState.ERROR` orb state.

---

## Requirements

### REQ-1: Parakeet Preservation and Deferred Initialization
**User Story:** As an IRIS voice user, I want high-accuracy Parakeet GPU transcription without paying a 4.2 GB memory penalty or multi-minute boot stall at application startup.

**Verified:** `backend/audio/voice_command.py:552`, `backend/audio/voice_command.py:108-132`

**Acceptance Criteria:**
- AC1.1: THE SYSTEM SHALL retain `ParakeetForTDT` (`nvidia/parakeet-tdt-0.6b-v3`) as the primary speech-to-text model on CUDA.
- AC1.2: THE SYSTEM SHALL NOT spawn or warm up the Parakeet worker subprocess during backend boot or `VoiceCommandDetector.__init__`.
- AC1.3: WHEN the first voice command is detected post-boot, THE SYSTEM SHALL launch the Parakeet worker in a background daemon thread if not already running.
- AC1.4: WHILE the Parakeet worker is loading or unready, THE SYSTEM SHALL route live utterances to `faster-whisper` without blocking the audio capture pipeline.
- AC1.5: WHEN the Parakeet worker reports ready and completes its initial inference warmup, THE SYSTEM SHALL route all subsequent utterances to Parakeet GPU ASR.
- AC1.6: IF no voice commands are received for 1200 seconds (20 minutes), THEN THE SYSTEM SHALL send a clean shutdown to the Parakeet worker subprocess to reclaim GPU VRAM and host RAM until the next voice activation.
- AC1.7: THE SYSTEM SHALL load Parakeet from a pre-converted fp16 cache (`data/models/parakeet-fp16/`, ~1.2 GB) when present, so the worker reads the fp16 safetensors directly instead of the 2.39 GB fp32 checkpoint and converting at load time. This cuts the warm load to ~17s.

**Edge Cases:**
- *Worker fails to load (CUDA OOM / Missing weights):* System marks `_load_error` and permanently falls back to `faster-whisper` without crashing.
- *Voice command arrives while worker is mid-spawn:* Utterance is transcribed by `faster-whisper` immediately.

---

### REQ-2: Seamless Faster-Whisper Fallback & VAD Pipeline Calibration
**User Story:** As a user speaking to IRIS, I want my first voice utterance and any fallback voice commands to transcribe cleanly and reliably without watchdog timeouts or false errors.

**Verified:** `backend/audio/voice_command.py:783-790`, `backend/audio/voice_command.py:993-1008`, `backend/audio/voice_command.py:1107-1158`

**Acceptance Criteria:**
- AC2.1: THE SYSTEM SHALL execute `faster-whisper` on CPU using `tiny/int8` deterministic settings (`beam_size=1`, `best_of=1`, `condition_on_previous_text=False`).
- AC2.2: THE SYSTEM SHALL NOT gate or abort `faster-whisper` CPU fallback based on total system available RAM.
- AC2.3: THE SYSTEM SHALL calibrate the transcription watchdog timeout dynamically based on captured audio length ($T_{\text{watchdog}} = \max(25.0, \text{audio\_seconds} \times 3.0)$) so high-load CPU conditions do not prematurely trigger `VoiceState.ERROR`.
- AC2.4: WHEN VAD detects end-of-speech, THE SYSTEM SHALL pass the concatenated audio frames directly to transcription without frame dropping.
- AC2.5: IF `faster-whisper` produces a valid transcript, THEN THE SYSTEM SHALL emit `VoiceState.SUCCESS` and invoke `_on_command_result` with the transcript and STT timing metadata.
- AC2.6: IF an downstream agent LLM call fails (e.g. `RateLimitedError`, connection timeout) during `_process_voice_transcription`, THEN THE SYSTEM SHALL speak and display a graceful error message rather than emitting an unhandled `VoiceState.ERROR` listening state.

**Edge Cases:**
- *Audio is pure silence / zero RMS:* VAD discards buffer and resets cleanly to `IDLE` without sending empty payloads to STT or LLM.
- *Watchdog fires during unexpected C-level freeze:* State machine resets `is_recording = False` and transitions back to `IDLE` after 2.0s.

---

### REQ-3: Hybrid Browser-Silo Websearch (Fast-HTTP Tier 1 + Browser Pool Tier 2)
**User Story:** As a user requesting web research, I want search queries to retrieve page content in under a second while keeping all browser activity siloed and RAM usage minimal.

**Verified:** `backend/crawler/orchestrator.py:834-890`, `backend/crawler/capabilities.py:68-120`

**Acceptance Criteria:**
- AC3.1: THE SYSTEM SHALL keep all web search and crawling functionality encapsulated strictly within the browser domain, emitting standard browser panel events (`CRAWLER_STARTED`, `CRAWLER_PAGE_FETCHED`, `CRAWLER_PHASE`, `OPEN_TAB`).
- AC3.2: WHEN fetching a planned URL, THE SYSTEM SHALL first attempt Tier 1 async HTTP retrieval (`httpx`) and parse readable text/markdown.
- AC3.3: IF Tier 1 retrieval succeeds and passes page usability checks (`page_is_usable`), THEN THE SYSTEM SHALL store the capture in `data/captures/<job_id>/<page_idx>.html` and return the result without launching Chromium.
- AC3.4: IF Tier 1 retrieval detects a challenge page, CAPTCHA, 403/401, or dynamic client-side SPA with insufficient text, THEN THE SYSTEM SHALL escalate to Tier 2 pooled browser retrieval.
- AC3.5: WHERE Tier 2 browser retrieval is required, THE SYSTEM SHALL execute page navigation through `backend.vision.browser_pool.acquire_browser()` using an isolated context.
- AC3.6: THE SYSTEM SHALL attach real per-request HAR evidence (status, response headers, body sha256) to each fetch outcome so the orchestrator's penalty scoring uses actual transport facts rather than a synthesized light entry.
- AC3.7: WHERE Tier 2 renders a page, THE SYSTEM SHALL extract the RENDERED visible text (preferring the semantic main-content container `<article>`/`<main>`) rather than a naive strip of the raw HTML, so JS-settled SPA content is captured.

**Edge Cases:**
- *Network timeout on Tier 1:* Immediately escalates to Tier 2 or records structured park failure.
- *Both Tier 1 and Tier 2 fail:* Records source park summary and falls through to honest retry/synthesis without crashing.

---

### REQ-4: Crawler Worker Unification with Existing `browser_pool.py`
**User Story:** As a developer/user, I want web searches to use a single shared browser pool so that duplicate Chromium instances do not consume background RAM.

**Verified:** `backend/crawler/crawl_runner.py:125-240`, `backend/vision/browser_pool.py:1-60`, `backend/iris_gateway.py:326-330`

**Acceptance Criteria:**
- AC4.1: THE SYSTEM SHALL NOT execute `_prewarm_crawl_worker()` or spawn persistent `crawl_worker.py --serve` subprocesses at boot.
- AC4.2: THE SYSTEM SHALL route all browser-based crawl jobs through `backend.vision.browser_pool`.
- AC4.3: THE SYSTEM SHALL isolate cookies, storage, and sessions across concurrent crawls using `browser.new_context()`.
- AC4.4: WHILE the shared browser has no active leases and exceeds `IRIS_BROWSER_IDLE_TIMEOUT` (180s), THE SYSTEM SHALL automatically shut down Chromium.

**Edge Cases:**
- *Browser process crashes mid-crawl:* `browser_pool` catches the dead process, clears internal references, and respawns lazily on next lease request.

---

### REQ-5: Pocket-TTS Subprocess Memory Optimization
**User Story:** As an IRIS user, I want instant voice responses from Pocket-TTS without the TTS worker consuming 2.3 GB of memory.

**Verified:** `backend/audio/tts_worker.py:60-95`, `backend/agent/tts.py:191-240`

**Acceptance Criteria:**
- AC5.1: THE SYSTEM SHALL set `os.environ["CUDA_VISIBLE_DEVICES"] = ""` in `backend/audio/tts_worker.py` prior to importing PyTorch or Pocket-TTS.
- AC5.2: THE SYSTEM SHALL verify that `torch.cuda.is_available()` evaluates to `False` inside the TTS worker process.
- AC5.3: WHEN model loading and voice-state extraction from `TOMV2.wav` complete, THE SYSTEM SHALL run garbage collection and invoke OS working set trimming via `ctypes.windll.psapi.EmptyWorkingSet`.
- AC5.4: THE SYSTEM SHALL maintain TTS synthesis audio quality at 24 kHz and streaming chunk latency $< 300\text{ms}$.
- AC5.5: THE SYSTEM SHALL NOT pre-load the TTS worker at backend boot (0 idle RAM for TTS). THE SYSTEM SHALL warm TTS on the first voice command (wake-word path) so the ~10s model load overlaps with the user speaking + agent thinking, avoiding a first-response delay.

**Edge Cases:**
- *`TOMV2.wav` missing or corrupt:* Falls back to default catalog voice cleanly.

---

### REQ-6: Uvicorn Main Process Memory Trimming & Deferral
**User Story:** As a system administrator, I want the core Uvicorn backend process to stay under 1.0 GB private memory at idle.

**Verified:** `backend/main.py:410-450`, `backend/audio/voice_command.py:549`

**Acceptance Criteria:**
- AC6.1: THE SYSTEM SHALL NOT eagerly call `self.warm_up()` inside `VoiceCommandDetector.__init__`.
- AC6.2: WHEN backend startup completes and all lifecycle routers are bound, THE SYSTEM SHALL invoke OS working set trimming on the Uvicorn process.
- AC6.3: THE SYSTEM SHALL ensure all heavy ML imports (`torch`, `transformers`, `ctranslate2`) are lazily imported within their respective worker or service calls.

---

### REQ-7: Observability and Memory Instrumentation
**User Story:** As an operator/tester, I want automated memory tracking and STT diagnostics so that regressions are immediately identified.

**Verified:** NEW

**Acceptance Criteria:**
- AC7.1: THE SYSTEM SHALL provide an automated measurement script (`scripts/measure_memory.py`) that logs PID, Process Name, Private Bytes (MB), and Working Set (MB) for all IRIS processes.
- AC7.2: THE SYSTEM SHALL record `[STT_LATENCY]` structured log lines on every transcription indicating `backend` (`whisper` or `parakeet`), `latency_ms`, `audio_s`, and `rtf`.
- AC7.3: THE SYSTEM SHALL assert in automated verification that idle memory across all Python processes is $\le 2.5\text{ GB}$.

---

## Non-Requirements (Out of Scope)

- Replacing Pocket-TTS with an alternative TTS engine (Pocket-TTS is locked).
- Replacing Porcupine or Violawake wake word detection.
- Redesigning the frontend browser panel UI or XurOrb animations.
- Removing or altering the DER DAG execution model or Har penalties.

---

## Open Questions

*All design and threshold questions have been resolved and locked in the Decisions Locked section.*

---

## Implementation Status (2026-09-03)

**Goal: ACHIEVED.** Live idle measurement after backend boot: **0.40 GB total private memory** (from the 8.2 GB regression — a 95% reduction, well under the ≤2.5 GB target).

| Metric | Original | Now |
|--------|----------|-----|
| Idle private memory | 8.2 GB | **0.40 GB** |
| TTS load (warm) | 55s cold | **10.4s** |
| Parakeet load (warm) | ~13 min | **17s** |
| Parakeet load (cold) | ~13 min | ~265s (disk-bound) |

**All 4 waves implemented and verified (86 tests pass).** Key as-built decisions beyond the original spec:
- **TTS is lazy** (not preloaded at boot) + warmed on the first wake-word voice command (REQ-5 AC5.5). 0 idle RAM, no first-response delay.
- **Parakeet loads a pre-converted fp16 cache** (`data/models/parakeet-fp16/`, via `scripts/convert_parakeet_fp16.py`) — REQ-1 AC1.7. Warm load ~17s.
- **`low_cpu_mem_usage=True` removed** from the Parakeet load (it routed through accelerate's slow mmap dispatch, ~13 min). Since Parakeet loads lazily, the transient CPU memory during load does not affect idle memory.
- **`FetchOutcome.har_entries`** added (REQ-3 AC3.6) — the hybrid tiers attach real per-request HAR evidence; `dispatch_urls` prefers it for penalty scoring.
- **Tier-2 content-aware extraction** (REQ-3 AC3.7) — reads rendered `innerText` preferring `<article>`/`<main>`.

**Known follow-ups (next session):**
- TTS warm-up currently fires only on the **wake-word** path; the **double-click** voice path does not pre-warm TTS (first response would wait ~10s). Mirror the wake-word warm-up in the double-click path.
- Full live end-to-end audio test (wake word → VAD → whisper → agent → TTS → playback) not yet run; only components were measured.
- Cold Parakeet load (~265s) is disk-bound (HDD); an SSD would make it ~17s even cold.

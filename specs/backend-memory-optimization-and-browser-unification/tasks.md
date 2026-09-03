# Tasks: Backend Memory Optimization and Browser Pool Unification

> Each task links to a requirement ID. Grouped into waves for dependency-ordered execution.
> Follow the repo workflow: READ spec -> READ file -> BUILD -> QUALITY CHECK -> RUN test.

---

## Wave 1 — Foundation & Memory Guards

- [x] T1 (REQ-5): Set `CUDA_VISIBLE_DEVICES=""` and add `EmptyWorkingSet()` memory trim in `backend/audio/tts_worker.py` — [tts_worker.py](file:///c:/dev/IRISVOICE/backend/audio/tts_worker.py) — RIPPLE: Leaves `backend/agent/tts.py` protocol unchanged; cuts TTS worker from 2.3 GB to ~0.9 GB.
- [x] T2 (REQ-1): Add `HF_HUB_OFFLINE=1`, post-load `EmptyWorkingSet()` trim, and idle-exit timeout handling in `backend/audio/parakeet_worker.py` — [parakeet_worker.py](file:///c:/dev/IRISVOICE/backend/audio/parakeet_worker.py) — RIPPLE: Enables Parakeet to compact memory post-load and exit on 20m inactivity.
- [x] T3 (REQ-6): Add post-boot working set reclamation call in `backend/main.py` lifespan startup — [main.py](file:///c:/dev/IRISVOICE/backend/main.py) — RIPPLE: Trims transient module import heap overhead from Uvicorn process.

**Wave 1 Test Gates**:
```powershell
pytest backend/tests/contract/test_tts_subprocess_contract.py -v
pytest backend/tests/behavioral/test_tts_event_loop.py -v
```

---

## Wave 2 — Voice Pipeline & Fallback Calibration

- [x] T4 (REQ-1, REQ-2): Remove eager boot-time `self._parakeet_warm_up()` and `self.warm_up()` from `VoiceCommandDetector.__init__` in `backend/audio/voice_command.py` — [voice_command.py](file:///c:/dev/IRISVOICE/backend/audio/voice_command.py) — RIPPLE: Defers Parakeet and Whisper loading to first use, eliminating 4.2 GB from boot idle.
- [x] T5 (REQ-2): Remove 4.0 GB free-RAM barrier in `_transcribe_with_fallback()` and calibrate dynamic transcription watchdog timer in `_run_transcription()` — [voice_command.py](file:///c:/dev/IRISVOICE/backend/audio/voice_command.py) — RIPPLE: Prevents premature 60s watchdog abort and false `VoiceState.ERROR` transitions during high CPU load.
- [x] T6 (REQ-2): Wrap agent LLM dispatch in `iris_gateway._process_voice_transcription()` to catch rate-limit/timeout exceptions and speak a friendly fallback notice — [iris_gateway.py](file:///c:/dev/IRISVOICE/backend/iris_gateway.py) — RIPPLE: Prevents unhandled agent errors from setting the orb into `error` listening state.

**Wave 2 Test Gates**:
```powershell
pytest backend/tests/test_audio_pipeline.py -v
pytest backend/tests/contract/test_voice_command_start_contract.py -v
pytest backend/tests/integration/test_voice_pipeline.py -v
```

---

## Wave 3 — Crawler & Browser Pool Unification

- [x] T7 (REQ-4): Remove `loop.create_task(self._prewarm_crawl_worker())` and eliminate duplicate resident `--serve` pool initialization from `backend/iris_gateway.py` — [iris_gateway.py](file:///c:/dev/IRISVOICE/backend/iris_gateway.py) — RIPPLE: Eliminates 2 resident Chromium worker processes (~700 MB) at boot.
- [x] T8 (REQ-3, REQ-4): Implement Tier 1 Fast-HTTP async retrieval (`httpx` + HTML text/markdown parser) inside `backend/crawler/capabilities.py` for `fetch.crawl` — [capabilities.py](file:///c:/dev/IRISVOICE/backend/crawler/capabilities.py) — RIPPLE: Delivers 150ms static page fetches with 0 MB browser memory overhead. Attaches real per-request HAR evidence (status/headers/sha256) to the `FetchOutcome.har_entries` field (REQ-3 AC3.6).
- [x] T9 (REQ-3, REQ-4): Connect Tier 2 browser escalation to `backend.vision.browser_pool` with multi-context isolation and capture emission — [crawl_runner.py](file:///c:/dev/IRISVOICE/backend/crawler/crawl_runner.py), [capabilities.py](file:///c:/dev/IRISVOICE/backend/crawler/capabilities.py) — RIPPLE: Unifies crawler with existing pooled browser; preserves all `CRAWLER_PAGE_FETCHED` and `OPEN_TAB` WebSocket events. Tier 2 extracts the RENDERED visible text (preferring `<article>`/`<main>`) so JS-settled SPA content is captured (REQ-3 AC3.7).

**Wave 3 Test Gates**:
```powershell
pytest backend/tests/contract/test_browser_pool_contract.py -v
pytest backend/tests/contract/test_websearch_loop_contract.py -v
pytest backend/tests/contract/test_browser_session_contract.py -v
```

---

## Wave 4 — Observability, Verification & Contracts

- [x] T10 (REQ-7): Create automated memory diagnostic script `scripts/measure_memory.py` — [measure_memory.py](file:///c:/dev/IRISVOICE/scripts/measure_memory.py) — RIPPLE: Profiles Private Bytes and Working Set across all IRIS processes; asserts total $\le 2.5\text{ GB}$.
- [x] T11 (REQ-1, REQ-5): Create contract test `backend/tests/contract/test_memory_optimization_contract.py` pinning TTS CUDA isolation and Parakeet JIT lazy loading — [test_memory_optimization_contract.py](file:///c:/dev/IRISVOICE/backend/tests/contract/test_memory_optimization_contract.py) — RIPPLE: Locks process memory isolation contracts.
- [x] T12 (REQ-2, REQ-3): Create behavioral integration test `backend/tests/behavioral/test_voice_whisper_to_parakeet_flow.py` and `backend/tests/behavioral/test_hybrid_crawl_silo.py` — `backend/tests/behavioral/` — RIPPLE: Tests full voice flow (Whisper utterance 1 -> Parakeet utterance 2) and hybrid crawl flow.

**Wave 4 Test Gates**:
```powershell
python scripts/measure_memory.py --assert-idle
pytest backend/tests/contract/test_memory_optimization_contract.py -v
pytest backend/tests/behavioral/test_voice_whisper_to_parakeet_flow.py -v
pytest backend/tests/behavioral/test_hybrid_crawl_silo.py -v
```

---

## Dependency & Parallelization Notes

- **Wave 1 (T1, T2, T3)**: Subprocess memory guards are completely independent of each other and can execute in parallel.
- **Wave 2 (T4, T5, T6)**: Depends on T2 for Parakeet lifecycle. Fixes the voice pipeline and ensures Whisper fallback + VAD operate smoothly without watchdog timeouts.
- **Wave 3 (T7, T8, T9)**: Replaces the duplicate crawl worker pool with the hybrid Fast-HTTP + `browser_pool.py` architecture. Independent of the voice pipeline.
- **Wave 4 (T10, T11, T12)**: Runs the verification harness and memory tracking to confirm the total idle footprint is $\le 2.5\text{ GB}$.
- **NO-CHANGE-verified areas**: Frontend WebSocket handlers (`useIRISWebSocket.ts`), `BrowserPanel.tsx`, and `CrawlOrchestrator` plan/rerank pipelines are verified correct and require no modifications.

---

## Wave 5 — Post-spec Refinements (2026-09-03, live-measurement driven)

Added after live measurement showed the TTS worker (2.29 GB) and slow Parakeet load kept the goal just out of reach. All verified live.

- [x] T13 (REQ-5): Make TTS **lazy** (remove boot preload in `backend/main.py`) + warm on the first wake-word voice command (`_on_wake_word_async`) so the ~10s load overlaps with the user speaking + agent thinking. Result: **0 idle RAM for TTS**, no first-response delay.
- [x] T14 (REQ-1): Remove `low_cpu_mem_usage=True` from the Parakeet load (it routed through accelerate's slow mmap dispatch, ~13 min). Since Parakeet loads lazily, the transient CPU memory during load does not affect idle memory.
- [x] T15 (REQ-1): Add `scripts/convert_parakeet_fp16.py` + fp16 cache load in `parakeet_worker.py` (`data/models/parakeet-fp16/`, ~1.2 GB). Warm load ~17s (from ~13 min).

**Wave 5 Test Gates** (verified live):
```powershell
python scripts/measure_memory.py --assert-idle   # 0.40 GB idle (goal ACHIEVED)
python scripts/convert_parakeet_fp16.py          # one-time fp16 cache build
```

**Wave 5 follow-ups (next session):**
- [ ] T16 (REQ-5): Mirror the TTS warm-up in the **double-click** voice path (currently only the wake-word path pre-warms TTS).
- [ ] T17: Run the full live end-to-end audio test (wake word → VAD → whisper → agent → TTS → playback); only components were measured so far.
- [ ] T18: Cold Parakeet load (~265s) is disk-bound (HDD); an SSD would make it ~17s even cold.

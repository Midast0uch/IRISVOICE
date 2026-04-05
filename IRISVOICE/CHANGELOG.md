# IRIS Changelog

## [Unreleased] — IRISVOICEv.4

### feat: replace CosyVoice3 with F5-TTS — full cleanup, CPU voice cloning preserved

**Why**: CosyVoice3-0.5B was a 9.1 GB model (despite the "0.5B" name), required ~4.25 GB
VRAM at runtime, conflicted with the local LLM on the RTX 3070 (8 GB VRAM), and caused
the PC to thrash at startup via an auto-prewarm thread. F5-TTS achieves the same zero-shot
voice cloning with 24 GB RAM unused, ~800 MB model, CPU RTF ~0.15 (still fast), and zero
VRAM impact.

**Migration**:
- `pip install f5-tts` — replaces all CosyVoice deps
- `backend/voice/pretrained_models/CosyVoice3-0.5B/` deleted (~6.3 GB freed this session,
  remaining from prior cleanup; full 9.1 GB now gone)
- `backend/voice/CosyVoice/` source directory deleted
- Matcha-TTS PYTHONPATH entry removed from `start-backend.py`
- CosyVoice deps (`conformer`, `hydra-core`, `hyperpyyaml`, `x-transformers`, `diffusers`)
  removed from `requirements.txt`; `f5-tts>=0.9.0` added

#### `backend/agent/tts.py` (full rewrite)

- **Engine replaced**: CosyVoice3 → F5-TTS (`F5TTS_v1_Base`, ~800 MB)
- **Voice cloning preserved**: TOMV2.wav is passed as `ref_file` to `f5tts.infer()` on every
  synthesis call — same reference audio, zero-shot cloning, no speaker registration step needed
- **Text normalizer wired in**: `_normalize()` calls `tts_normalizer.normalize_for_speech()`
  before every synthesis — strips markdown, expands symbols (`$`→"dollars", `%`→"percent",
  `->`, `**bold**`, etc.) so TTS never reads raw markup
- **Chunked synthesis**: `_split_into_chunks()` splits text at sentence boundaries
  (`.`, `!`, `?`) then at commas if sentences are too long (> 200 chars). Each chunk is
  synthesized and yielded immediately — approximates streaming with natural sentence pauses
- **CPU-only**: F5-TTS runs entirely on CPU, leaving full VRAM for the local LLM
- **Fallback chain unchanged**: Piper en_US-ryan-high → pyttsx3 SAPI5
- **`F5TTS_NATIVE_RATE`** constant replaces `COSYVOICE_NATIVE_RATE` (both 24 kHz)
- **`_prewarm_tts` RAM guard** lowered from 12 GB → 2 GB (F5-TTS is ~800 MB vs 9 GB)
- All CosyVoice constants, imports, and methods removed: `MODEL_DIR`, `COSYVOICE_DIR`,
  `SPK_ID`, `COSYVOICE3_PROMPT_PREFIX`, `_ensure_cosyvoice_paths`, `_load_cosyvoice`,
  `_register_speaker`, `_stream_cosyvoice`, `_warm_tts_pipeline`

#### Other files (comment cleanup)

- `backend/iris_gateway.py` — CosyVoice3 references in comments updated to F5-TTS;
  `_prewarm_tts` doc and RAM guard updated; `tts._warm_tts_pipeline()` → `tts._load_f5tts()`
- `backend/audio/engine.py`, `pipeline.py`, `voice_command.py`, `agent_kernel.py`,
  `agent/lfm_audio_manager.py` — inline CosyVoice comments updated to F5-TTS
- `requirements.txt` — CosyVoice comment block replaced; `f5-tts` added; old CosyVoice-only
  deps removed
- `start-backend.py` — Matcha-TTS PYTHONPATH injection removed
- `backend/tests/test_voice_pipeline.py` — `TestTTSManagerPaths` updated: `MODEL_DIR` /
  `COSYVOICE_NATIVE_RATE` tests replaced with `F5TTS_NATIVE_RATE` / `OUTPUT_SAMPLE_RATE`;
  `test_cosyvoice3_referenced_in_comments` replaced with `test_f5tts_referenced_in_requirements`

### fix: CosyVoice3 VRAM conflict with local LLM — switch default to Piper

**Why CosyVoice3-0.5B was 9.1 GB**: The "0.5B" refers only to the LLM text
encoder component. The full system includes a Flow model (~1.3 GB), HiFi-GAN
vocoder (80 MB), and ONNX speech tokenizer (~924 MB). On disk there were also
redundant files: the CosyVoice2-0.5B directory (3.3 GB, superseded), the RL
fine-tuned duplicate `llm.rl.pt` (1.9 GB, not used in inference), and the
`.batch.onnx` tokenizer variant (925 MB, not referenced).

**Runtime VRAM conflict**: CosyVoice3 loads ~3.3 GB into VRAM. An 8B Q4_K_M
LLM needs ~5 GB. Total = 8.3 GB — exceeds the RTX 3070's 8 GB VRAM. The two
cannot run simultaneously.

**Disk freed**: ~6.1 GB removed (CosyVoice2 + llm.rl.pt + speech_tokenizer_v3.batch.onnx).
CosyVoice3 on-disk footprint reduced from 9.1 GB to 6.3 GB.

#### `backend/agent/tts.py`

- **Default voice changed** from `"Cloned Voice"` (CosyVoice3, 3.3 GB VRAM) to
  `"Built-in"` (Piper, ~65 MB, CPU-only). Backend now starts without consuming
  any VRAM. Switch to "Cloned Voice" in Settings when you need voice cloning.
- **VRAM guard added** to `_select_engine()`: CosyVoice3 is now blocked when
  free VRAM < 4.5 GB. If a local LLM is loaded and using most of the VRAM,
  TTS automatically falls back to Piper with a logged warning instead of causing
  an OOM crash.
- **Voice change re-check**: `update_config()` now resets `_engine_selected` when
  `tts_voice` changes, so VRAM is re-evaluated on next synthesis with the new choice.

### fix: stop 9.1 GB CosyVoice3 model auto-loading at every backend start

**Root cause of PC becoming unresponsive**: `CosyVoice3-0.5B` weights on disk are
9.1 GB. `IRISGateway.__init__` was spawning a background thread to pre-load this
model 6 seconds after every backend start, regardless of whether the user was using
voice TTS. The RAM guard was set at 4.0 GB free — a threshold the model alone
exceeds. On a 16–32 GB consumer system already running Next.js + browser + Python,
loading 9.1 GB in the background saturated RAM and caused the OS to thrash.

#### `backend/iris_gateway.py`

- **Startup prewarm removed**: The `if _cosyvoice_model_dir.exists()` block in
  `__init__` no longer spawns the prewarm thread. `_tts_prewarmed = True` is set
  immediately so all "safety net" re-trigger paths are also suppressed.
  CosyVoice3 now loads **lazily** — only when the user sends their first voice
  message and `synthesize_stream()` runs for the first time. `synthesize_stream`
  already calls `_select_engine()` + `_load_cosyvoice()` itself; the prewarm was
  purely an optimisation that was killing the machine.
- **On-demand re-trigger removed**: The `if not self._tts_prewarmed` block in
  `_handle_voice` that spawned a second prewarm thread when voice started is also
  removed. Comments explain the lazy-load contract.
- **RAM guard raised**: `_prewarm_tts` RAM check raised from 4.0 GB → 12.0 GB
  (model = 9.1 GB + Python overhead + OS = minimum 12 GB headroom required).

### perf: eliminate PC-grinding memory spikes (frontend + backend)

Root-cause audit found 3 issues causing the PC to become unresponsive when both servers ran simultaneously.

#### `components/chat-view.tsx`

- **TTS word highlight (CRITICAL)** — `currentWordIndex` was stored inside the `Message`
  object, inside `conversations` state. Every 200 ms the interval called `setConversations`
  which mapped ALL conversations × ALL messages → ~10,000 object allocations per tick →
  50,000+ allocations/sec at peak. Each `setConversations` call also triggered the
  `conversations` useEffect which wrote the full JSON to `localStorage` (10MB+) every 200 ms.
  Additionally `messages` was in the `useEffect` deps so the interval was torn down and
  recreated on every keystroke, queuing 5–10 simultaneous intervals.
  **Fix:** `currentWordIndex` removed from `Message` type entirely. A single
  `ttsWordIndex: number` state is updated instead — one integer, zero conversation
  remapping, zero localStorage writes during TTS. `messages` removed from useEffect deps
  (words snapshotted at speak-start via local variable). localStorage persist debounced
  to 1 s so rapid state changes don't hammer disk I/O.

- **localStorage debounce** — conversations persistence now defers 1 s after the last
  change instead of writing synchronously on every mutation.

#### `backend/agent/local_model_manager.py`

- **Health check polling (HIGH)** — while waiting for the model server to start, the
  health probe fired every 0.5 s (2 HTTP requests/sec) for up to 3 minutes. This produced
  360+ HTTP calls during a single model load, thrashing the asyncio event loop and
  preventing other startup tasks from running.
  **Fix:** Exponential backoff starting at 1 s, doubling each missed poll, capped at 8 s.
  Worst-case load now produces ~25 health checks instead of 360.

#### `backend/audio/engine.py`

- **Audio frame conversion (HIGH)** — `_process_audio_frame` called `.tolist()` on the
  numpy int16 array before passing to Porcupine, allocating 512 Python `int` objects per
  frame × 31 frames/sec = ~16,000 object allocations/sec continuously while mic is active.
  **Fix:** numpy int16 array passed directly to `porcupine.process_frame()` — pvporcupine
  accepts any buffer-protocol sequence. Zero allocation overhead per frame.

#### `backend/voice/porcupine_detector.py`

- `process_frame` type hint updated to accept `Any` sequence (numpy array or list) without
  mypy complaints.

### fix: 10-bug audit — voice/text/tool pipeline hardening

Complete audit of the path from model load → voice input → LLM inference → tool execution → WebSocket delivery. All 10 bugs fixed.

#### `backend/agent/agent_kernel.py`

- **Bug 1+8** — Added `_normalise_endpoint()` static method: strips trailing `/` and `/v1`
  to prevent double `/v1/v1` URL on every OpenAI-compat request. Both `configure_lmstudio()`
  and `configure_openai_compat()` now call it. `configure_openai_compat(None)` safely sets
  `_model_provider = "uninitialized"` instead of crashing on `None.rstrip()`.
- **Bug 2+10** — DER loop Explorer phase called `self._tool_bridge.execute_tool()` without
  `await`, returning a coroutine object instead of the result. Wrapped with `asyncio.run()`
  and a ThreadPoolExecutor fallback. Tool calls now complete correctly.
- **Bug 5** — `_broadcast_inference_event` silently dropped WebSocket events when called
  from the thread pool (no running loop in that thread). Added `_broadcast_loop` attribute
  captured at startup + `run_coroutine_threadsafe` fallback. Inference console events now
  reach the frontend from background threads.
- **Bug 5** — Added `set_main_loop()` method and `set_main_loop(loop)` called during
  startup so the loop reference is available immediately.

#### `backend/main.py`

- **Bug 3+7** — Lifespan startup called `get_agent_tool_bridge()` (sync factory, never
  calls `initialize()`), leaving `_mcp_servers = {}` and all MCP tool calls failing.
  Changed to `await initialize_agent_tools()` which calls `bridge.initialize()` and wires
  all MCP servers.
- **Bug 5** — Added `agent_kernel.set_main_loop(asyncio.get_running_loop())` at startup.

#### `backend/agent/local_model_manager.py`

- **Bug 4** — Three occurrences of `asyncio.get_event_loop()` inside async methods
  (`load_model`, `_wait_for_ready`, HuggingFace download). On Python 3.10+ this raises
  `DeprecationWarning`; on 3.12+ raises `RuntimeError`. Replaced all three with
  `asyncio.get_running_loop()`.

#### `backend/iris_gateway.py`

- **Bug 6** — Both `chunk_callback` closures called
  `asyncio.run_coroutine_threadsafe(..., self._main_loop)` without checking if
  `self._main_loop` is None or still running. Added `if _loop and _loop.is_running():`
  guard around both calls — prevents crash when voice or text fires before the first
  async WebSocket dispatch.

#### `backend/voice/porcupine_detector.py`

- **Bug 9** — `__init__` raised `ValueError` on missing Picovoice access key and on no
  wake words configured, propagating through the audio pipeline startup and disabling
  voice entirely. Now sets `self._disabled = True` and logs a warning instead of raising.
  `_initialize_porcupine()` also degrades gracefully on engine failure. Added
  `is_enabled()` helper. All public methods no-op when disabled so the rest of the
  audio pipeline keeps running without a key or model file.

#### Bootstrap / tooling

- `session_start.py` — auto-syncs git commits into coordinate graph on every prompt (SHA-based idempotency)
- `.claude/settings.local.json` — Stop hook now runs `mid_session_snapshot.py` + `update_coordinates.py --auto`
- `bootstrap/on_git_commit.py` — removed (logic folded into session_start)
- `bootstrap/mid_sesssion_snapshot.py` — removed (typo duplicate)
- `AGENTS.md`, `CLAUDE.md`, `bootstrap/GOALS.md` — rewritten for platform/project agnostic use; quality gate checklist added to build sequence

---

### feat: DER loop fully wired into AgentKernel — spec compliance audit complete

### feat: DER loop fully wired into AgentKernel — spec compliance audit complete

All 11 gaps identified in the DER loop spec audit have been resolved.
18/18 spec tests pass (`backend/tests/test_der_loop.py`).

#### `backend/agent/agent_kernel.py`

- **Gap 1** — Added `_execute_plan_der()`: full Director→Reviewer→Explorer cycle
  with dependency-aware queue, per-step Mycelium signals, and ordered outcome
  recording (record_outcome → crystallize → clear → plan_stats).
- **Gap 2** — `self._task_classifier` (TaskClassifier) and `self._reviewer` (Reviewer)
  instantiated in `__init__()`. Reviewer's memory reference updated when
  `set_memory_interface()` is called.
- **Gap 3** — Added `_plan_task()`: DER-aware planner with maturity-aware temperature
  (0.1 mature / 0.25 exploring), `context_package` fed into planning prompt,
  `is_mature` / `task_class` / `context_package` parameters with safe defaults.
  Falls back to single-step plan on any model/parse failure.
- **Gap 4** — `process_text_message()` now classifies → assembles context → plans
  → routes `do_it_myself` strategy through `_execute_plan_der()`.
  `spawn_children` / `delegate_external` fall through to the existing ReAct loop.
  Entire DER path wrapped in try/except — ReAct is always the safety net.
- **Gap 5** — `mycelium_ingest_statement()` fires after planning with strategy signal.
- **Gap 6** — `register_address()` fires on the context package after plan injection
  when `is_mature=True`.
- **Gap 7** — Outcome recording sequence in correct spec order inside
  `_execute_plan_der()`.
- **Gap 8** — `mycelium_ingest_tool_call()` fires after every DER step (success,
  failure, and veto).
- **Gap 11** — DER constants (`DER_MAX_CYCLES`, `DER_MAX_VETO_PER_ITEM`,
  `DER_EMERGENCY_STOP`, `DER_TOKEN_BUDGETS`) re-exported at module level from
  `der_constants.py` for spec compliance.
- Added `infer()` adapter method so Reviewer can call the inference backend
  without a circular dependency.
- Added `_get_failure_warnings()` using `ResolutionEncoder` to surface high-signal
  Mycelium failure data into the planning prompt.
- Added `_run_step_direct()` for tool-less DER steps (direct model inference).

#### `backend/memory/interface.py`

- **Gap 9** — `mycelium_ingest_statement` proxy now passes `text=` keyword arg and
  `session_id=` (was silently dropping session_id).

#### `backend/core_models.py`

- **Gap 10** — `ExecutionPlan.to_context_string()` now includes
  `EXECUTION PLAN [{hza}]` header and `Reasoning: {self.reasoning}` line
  per spec format. Step count line replaced with `""` + `"Steps:"` separator.

---

## [bec8ad3] — feat: DER loop, Mycelium bootstrap, Skill Creator, MCP + Telegram

Gates 1-3 complete. DER loop classes built, Mycelium bootstrap system,
Skill Creator, MCP dispatch, Telegram bridge.

## [78fca62] — feat: unified chat interface with precision HUD alignment

## [c6fb83c] — fix: stabilize WebSocket by removing competing frontend heartbeat

## [082ee1c] — fix: eliminate TTS inter-sentence pauses via word-count chunking

## [66a04bc] — fix: TTS inter-sentence gaps, stuck pink orb, second wake-word ignored

# IRIS Changelog

## [Unreleased] — IRISVOICEv.4

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

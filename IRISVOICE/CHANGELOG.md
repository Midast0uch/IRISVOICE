# IRIS Changelog

## [Unreleased] — IRISVOICEv.4

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

# Caducean v2 — Plan Review Notes
## Findings from Cold Review (2026-06-13)

This document records the gaps, inaccuracies, and missing considerations found when reviewing `docs/plans/Cadv2plan.md` against the actual codebase. Each finding includes a proposed fix that should be incorporated into the plan before Phase 1 begins.

---

## Finding 1: Migration path is wrong (and the table already exists)

**Issue:** The plan says "create `backend/migrations/003_caducean_trajectories.sql`". This is wrong on three counts:

1. The migrations directory is `backend/memory/migrations/`, not `backend/migrations/`
2. `_run_migrations()` in `backend/gateway/iris_ffi.py` does NOT load SQL files from disk — schema is hardcoded in the Python wrapper and in the C++ `DBManager`
3. The `caducean_trajectories` table **already exists** in `backend/agent/caducean_trajectory.py` (via `initialize_db()`)

**What's already there** (from `backend/agent/caducean_trajectory.py`):
```sql
CREATE TABLE IF NOT EXISTS caducean_trajectories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    step_num INTEGER NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    xi REAL NOT NULL,
    u REAL NOT NULL,
    action INTEGER,
    outcome TEXT,
    eml_after REAL
)
```

**What's missing for v2:** One column — `recommendation INTEGER` (stores 0, 1, 2, or 3).

**Proposed fix in the plan:**
- Remove the `backend/migrations/003_caducean_trajectories.sql` line.
- Replace with: "**Add `recommendation` column** to the existing `caducean_trajectories` table via an `ALTER TABLE` in `_run_migrations()` (in `iris_ffi.py` line 240 area). Wrap in try/except for idempotency (column may already exist on dev machines)."
- Also need to add a `v2_columns` patch to the Python `initialize_db()` in `caducean_trajectory.py` for the runtime DB.

---

## Finding 2: `ffi_caducean_recommend()` does not return 3 (TOPO_VIOLATION) today

**Issue:** The plan says the C++ `recommend()` should return `3` (TOPO_VIOLATION). But reading `src-tauri/src/iris_core/caducean.cpp` line 35, the C++ function only returns 0, 1, or 2 — and `ffi_caducean_recommend()` in `iris_ffi.py` is a direct passthrough. The v2 plan needs to **add** the `3` case to C++ AND the Python wrapper.

**Proposed fix in the plan:**
- Make the C++ change to `recommend()` explicit in Component 1: "Add return code 3 (TOPO_VIOLATION) to the C++ recommend() function. The current code only returns 0/1/2 — v2 ADDS 3."
- Same in Component 2: "Update `_PythonCaduceanFallbackState.recommend()` to also have a code path for returning 3" (currently it only returns 2).

---

## Finding 3: Line numbers in the plan are wrong

**Issue:** The plan says "Update Caducean update step (around line 3860)" for `agent_kernel.py`. The actual location is **line 3756-3758** in the current `agent_kernel.py`.

**Proposed fix in the plan:**
- Update line references to match current code:
  - `agent_kernel.py`: Caducean update is at **line 3756-3758** (not 3860)
  - `der_loop.py`: existing Caducean call is at **line 84-89** (already uses `ffi_caducean_recommend`)

---

## Finding 4: `der_loop.py` already calls Caducean — plan understates the change

**Issue:** The plan says "Update queue selection modulation (`next_ready`) to fetch the `DirectionSignal`" as if Caducean isn't used today. But `der_loop.py` line 84-93 already calls `ffi_caducean_recommend()` and uses `rec == 1` to restrict to critical items. The v2 change is **additive** (handle `rec == 3` for TOPO_VIOLATION) plus **optional** migration to the bias-free `DirectionSignal.target_u` API.

**Proposed fix in the plan:**
- Reword Component 4: "**der_loop.py already uses `ffi_caducean_recommend`**. v2 adds handling for `rec == 3` (TOPO_VIOLATION → raise). The bias-free `DirectionSignal.target_u` API is a v3 candidate — current code uses the recommendation code directly, which is functionally equivalent and avoids an FFI round-trip per cycle."

This is an example of the bias-free refactor being **optional**, not required. The plan should not pretend current code is broken — it's just incomplete.

---

## Finding 5: `_get_caducean_state()` is the contract with `auto_research` and `skill_simulator`

**Issue:** The plan references `auto_research.py` and `skill_simulator.py` as consumers but doesn't document the **dict contract** that links them. Both files call something like:
```python
self._get_caducean_state().get("eml", 1.0)
```

We need to document what keys are in this dict and what defaults are safe.

**Proposed fix in the plan:**
- Add a "Caducean State Dict Contract" subsection listing the keys consumed:
  - `eml: float` (default 1.0) — used by `skill_simulator` and `auto_research`
  - `x: int`, `y: int` (default 0.5) — used by `skill_simulator`
  - `u: float` (default 0.0) — used by `auto_research` for skill variant prediction
  - `target_u: float` (default +1.0) — NEW in v2, for bias-free consumers
  - `force_magnitude: float` (default 0.0) — NEW in v2, for TTS chunk sizing
- All defaults must remain safe — Phase 0 fix made C++ live, so the dict is now populated; consumers that don't change still work because `.get(key, default)` semantics are preserved.

---

## Finding 6: Phase 0 follow-up — the `_caducean_engine_initialized` flag is unconsumed

**Issue:** Phase 0 added `self._caducean_engine_initialized` to `MemoryInterface`. But nothing currently consumes it. The flag is set but not checked.

**Proposed fix in the plan:**
- Add to Phase 0 follow-up: "Add a `memory.is_caducean_engine_live()` public method that returns `self._caducean_engine_initialized`. This is used by the FastAPI `/api/caducean/health` endpoint (Phase 5) and by the debug panel (Phase 6) to show the engine state."

---

## Finding 7: No plan for `mycelium_record_anomaly()` schema

**Issue:** The plan says "Add `mycelium_record_anomaly(session_id, signal_type)`" but doesn't specify what table it writes to. Looking at the codebase, there are several anomaly-related tables (`map_events`, `quorum_log`); v2 needs a clear home for `update_velocity_anomaly` signals.

**Proposed fix in the plan:**
- Specify: "Add to existing `quorum_log` table (already used by QuorumSensor). The `mycelium_record_anomaly()` method calls `_quorum_sensor.record_signal(signal_type='update_velocity_anomaly')` and runs the existing reorganization check. No new table."

---

## Finding 8: `trajectory_controller.py` tuning bounds are unstated

**Issue:** The plan says "Compute adjustments to `a, b, s`" but doesn't specify the algorithm or bounds. If `trajectory_controller` over-tunes, the engine can drift into non-physical regimes.

**Proposed fix in the plan:**
- Add explicit bounds and update rules to Component 4:
  ```python
  # trajectory_controller update rule
  violation_count = count of rec==3 in last N steps
  if violation_count > 0:
      new_a = clamp(prev_a + 0.1 * violation_count, 1.0, 4.0)
      new_b = clamp(prev_b + 0.05 * violation_count, 1.0, 4.0)
      new_s = clamp(prev_s - 0.01 * violation_count, 0.1, 0.8)
  ffi_caducean_set_params(session_id, new_a, new_b, new_s)
  ```
- Also: **persist** the tuned values to a `caducean_session_params` table so they survive across sessions (or at least log them to a file).

---

## Finding 9: CoupledRegistry coupling math is underspecified

**Issue:** The plan says "if `c_eff1 / c_eff2 = p/q` (rational), apply coupling" but doesn't define:
- Tolerance for "rational" (floating point comparison)
- How to compute p, q from the c_eff values
- When coupling events fire (per-step? per-phase-alignment?)
- How much angular momentum to transfer

**Proposed fix in the plan:**
- Add explicit math to Component 4:
  ```python
  # coupled_registry update rule
  c1 = sqrt(l1**2 + m1**2) / sqrt(2)
  c2 = sqrt(l2**2 + m2**2) / sqrt(2)
  ratio = c1 / c2
  # Rational test: ratio is within 0.01 of p/q with p,q < 10
  is_rational = any(abs(ratio - p/q) < 0.01 for p in range(1,10) for q in range(1,10))
  if is_rational:
      # Phase alignment: both ξ within 0.1 radians
      if abs(xi1 - xi2) < 0.1:
          # Transfer angular momentum — nucleus/barrier
          u1_new = u1 + 0.1   # barrier
          u2_new = u2 - 0.1   # nucleus
  else:
      # Destructive interference
      u1_new = u1 - 0.05
      u2_new = u2 - 0.05
  ```
- Tests should verify rational coupling actually produces differentiation.

---

## Finding 10: ConversationKernel session_id wiring is underspecified

**Issue:** The plan says "Frontend generates the session_id, passed via WS handshake" but the existing `_speak_response()` flow doesn't currently have a session_id context. The new `iris_gateway.set_caducean_session(session_id)` method needs to know which session is active.

**Proposed fix in the plan:**
- Add to Component 5: "The active session_id is already tracked in `iris_gateway` via the `session_id` parameter passed to `process_text_message(from_voice=True)`. v2's `set_caducean_session()` stores it as `self._caducean_session_id`. `ConversationKernel` reads this attribute in its callbacks (no new parameter passing)."

---

## Finding 11: No "rollback" plan if v2 destabilizes the system

**Issue:** The plan has risk mitigation per phase but no system-level rollback strategy. If v2 is deployed and causes regressions in production-like usage, how do we revert to the v1 stub?

**Proposed fix in the plan:**
- Add to "Risk Mitigation" section: "**System-level rollback:** The `ffi_init_engine()` call in `MemoryInterface.__init__` is wrapped in try/except. Setting `IRIS_CADUCEAN_V2_DISABLED=1` in the environment causes the init block to skip the call entirely, restoring the v1 stub fallback for all consumers. This is the kill switch for the whole v2 stack — one env var, no code changes."

---

## Finding 12: Missing: explicit "Definition of Done" per phase

**Issue:** Each phase has a "Test" and "Landmark" but no clear "Done" criteria. When is Phase 1 truly done? When Phase 2 starts? When something specific passes?

**Proposed fix in the plan:**
- Add a "Done Criteria" line to each phase:
  - Phase 0: "Engine init returns True; 415+ existing tests pass." — DONE (commit dbc4384f)
  - Phase 1: "DLL compiles clean via build_cpp_core.ps1; 6 new smoke tests pass; no existing tests regress."
  - Phase 2: "All FFI contract tests pass; Python fallback updated to return mock DirectionSignal."
  - Phase 3: "Memory tests pass; new trajectory column added; scorer/resonance read u correctly."
  - Phase 4: "DER tests pass; TOPO_VIOLATION raised on chaotic input; trajectory persisted; coupled registry differentiates roles in 1000-step test."
  - Phase 5: "Tauri commands register; FastAPI endpoints return correct JSON; API contract tests pass."
  - Phase 6: "useCaducean hook returns live values; debug panel shows state; sliders update C++."
  - Phase 7: "Existing 38 voice tests still pass; new conversation kernel tests pass; manual e2e shows phase transitions."

---

## Finding 13: Missing: language choice for `conversation_kernel.py`

**Issue:** The plan doesn't specify whether `conversation_kernel.py` should be sync or async. `iris_gateway` uses `asyncio.run_coroutine_threadsafe` to dispatch voice events; the kernel callbacks need to be safe to call from any thread.

**Proposed fix in the plan:**
- Add: "ConversationKernel uses **synchronous** FFI calls (`ffi_caducean_update` is sync, ctypes is sync). The callbacks (`_on_voice_state`, `_on_audio_level`) are called from the audio thread but ctypes calls are thread-safe per session_id (the C++ engine uses a per-session mutex). No asyncio bridge needed."

---

## Finding 14: Missing: plan for what `balance` value to pass on each FFI call

**Issue:** The plan says "send EXPAND/COMPRESS action to Caducean" but doesn't specify what `balance` value to pass. The C++ update signature is `update(session_id, action, balance)`. `balance` must be in [0.1, 3.0] for the phase advance to work correctly.

**Proposed fix in the plan:**
- Add: "For voice-initiated updates, compute `balance = ffi_calculate_eml(session_id)[2]` (the third return value). Fall back to `1.0` if EML is unavailable. Clamp to `[0.1, 3.0]` defensively."

---

## Finding 15: Missing: `ConversationKernel` registration with audio thread

**Issue:** The plan says "registers as additional observer on existing callbacks" but doesn't show HOW. The existing `_on_audio_level` callback is set via `set_audio_level_callback` in `VoiceCommandHandler.__init__`. Can it have multiple observers?

**Proposed fix in the plan:**
- Add: "`VoiceCommandHandler.set_state_callback` and `set_audio_level_callback` accept a single callable. v2 either: (a) chains callbacks via a small `CallbackChain` helper, or (b) `ConversationKernel` registers FIRST, then the existing `iris_gateway._on_audio_level` is wrapped to call both. Option (b) is simpler — 1 file modified in audio/voice_command.py (5 lines), or zero files if iris_gateway's existing callback invokes the kernel."

---

## Summary of Plan Corrections Needed

| # | Finding | Severity | Fix Type |
|---|---------|----------|----------|
| 1 | Migration path wrong + table exists | **HIGH** — would create dead code | Plan correction |
| 2 | `recommend()=3` doesn't exist yet | **HIGH** — plan assumes it does | Plan clarification |
| 3 | Line numbers wrong | Low | Plan correction |
| 4 | der_loop already uses Caducean | Medium | Plan reword |
| 5 | Caducean state dict contract undocumented | Medium | Plan addition |
| 6 | `_caducean_engine_initialized` unconsumed | Low | Phase 0 follow-up |
| 7 | `mycelium_record_anomaly` schema unclear | Medium | Plan clarification |
| 8 | trajectory_controller bounds unstated | Medium | Plan addition |
| 9 | CoupledRegistry math underspecified | Medium | Plan addition |
| 10 | ConversationKernel session_id wiring | Low | Plan clarification |
| 11 | No system rollback plan | Medium | Plan addition |
| 12 | No "Done Criteria" per phase | Low | Plan addition |
| 13 | Sync/async choice for kernel | Low | Plan clarification |
| 14 | `balance` value source | Medium | Plan clarification |
| 15 | Callback registration strategy | Low | Plan clarification |

**Total: 15 findings. 2 HIGH, 7 Medium, 6 Low.**

All findings should be incorporated into the plan before Phase 1 begins.

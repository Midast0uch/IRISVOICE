# Implementation Plan - Caducean Engine v2
## Mitochondria-to-Mycelium Upgrade

> **Branch:** `feat/caducean-v2-mitochondria-mycelium`
> **Date:** 2026-06-12
> **Status:** Foundational Blueprint — no code changes yet

---

## User Review Required

> [!IMPORTANT]
> This plan establishes the Caducean Engine as the **mitochondria** (energy/metabolic governor) of the Mycelium memory system. It hooks the engine's physical state (attentional velocity `u`, phase `ξ`, phase acceleration) into the memory graph's decay, resonance retrieval, and quorum reorganizer.
> 
> It also implements FFI core initialization at app startup, winding numbers, O(1) EML feedback, an adaptive safety net, parameter learning, multi-session coupling, and a voice-first ConversationKernel.

### Architecture Decisions (confirmed 2026-06-12)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Biometric key | **Option C** — frontend generates session ID, passed via WS handshake | Single owner pattern, no shared state |
| Tauri↔Python comms | **Option A** — HTTP POST to FastAPI `/api/caducean/*` | CORS already configured, trivial endpoints, testable |
| Frontend Caducean state | **Option A** — polling Tauri commands, 500ms interval | Simple, debuggable, latency acceptable for v1 |
| Future: voice latency | **Option B** — WebSocket broadcast from Python on every update | Defer until profiling shows polling is bottleneck |
| DLL ownership | **Python owns iris_core.dll** (single ctypes load) | No duplicate load, no memory spike risk |
| Tauri Rust code | Thin Tauri commands that proxy to Python HTTP | Keep Rust layer dumb, Python is smart |

### Architecture Pattern (Single Owner)

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         TAURI (Rust — thin shell)                          │
│  ┌─────────────┐   ┌─────────────┐   ┌──────────────────────────────┐     │
│  │ WebView     │   │ Sidecar     │   │ Tauri Commands (proxy)       │     │
│  │ (Next.js)   │   │ Manager     │   │ - get_caducean_state         │     │
│  │ Port 3000   │   │ (spawns Py) │   │ - get_direction_signal       │     │
│  └──────┬──────┘   └─────────────┘   └──────────────┬───────────────┘     │
│         │ WS                                         │ HTTP                │
└─────────┼─────────────────────────────────────────────┼────────────────────┘
          │                                             │
          ▼                                             ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                    PYTHON BACKEND (FastAPI :8000)                          │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ IrisCoreEngine (singleton)                                          │   │
│  │   - Loads iris_core.dll ONCE via ctypes                             │   │
│  │   - Exposes all FFI functions                                      │   │
│  │   - Falls back to pure-Python if DLL missing                       │   │
│  │   - Now ACTUALLY INITIALIZED in MemoryInterface.__init__ (FIX)     │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│         │                                                                  │
│  ┌──────┴──────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │ Agent       │  │ Mycelium    │  │ Voice       │  │ Coupled     │      │
│  │ Kernel      │  │ Memory      │  │ Pipeline    │  │ Registry    │      │
│  │ DER Loop    │  │ (scorer,    │  │ (Conv       │  │ (multi-     │      │
│  │             │  │  resonance) │  │  Kernel)    │  │  session)   │      │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘      │
│                                                                            │
│  New FastAPI endpoints: /api/caducean/state, /api/caducean/direction,     │
│                         /api/caducean/params                               │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Proposed Changes (11 Components)

We will modify the C++ core, Python FFI, memory interface, Mycelium memory, agent kernel, voice pipeline, Tauri shell, frontend, tests, and add three new modules.

---

### Component 0: Critical Engine Initialization Fix (P0 — Block everything)

#### [MODIFY] [backend/memory/interface.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/memory/interface.py)
**Bug:** The C++ core was never initialized. The `MemoryInterface.__init__` accepted a `biometric_key` but never called `ffi_init_engine()`. Every Caducean call fell back to the Python stub returning `MAINTAIN` (2).

**Fix:** Add engine initialization at the end of `MemoryInterface.__init__`:
```python
# In backend/memory/interface.py, inside __init__:
try:
    from backend.gateway.iris_ffi import ffi_init_engine
    ok = ffi_init_engine(db_path, biometric_key.hex())
    if not ok:
        logger.warning("[MemoryInterface] C++ engine init returned False — using Python fallback")
except Exception as _e:
    logger.warning(f"[MemoryInterface] C++ engine init failed: {_e} — using Python fallback")
```
- Wrapped in try/except so backend never crashes if DLL missing.
- Idempotent: `ffi_init_engine()` already checks `_initialized` flag in `IrisCoreEngine.init()`.

**Why P0:** Without this, the entire C++ engine is dead code. v1 features that depend on real Caducean state silently fail. Every downstream component (Mycelium modulation, DER queue, voice kernel) needs the live state.

---

### Component 1: C++ Core Engine (`src-tauri/src/iris_core`)

#### [MODIFY] [caducean.h](file:///C:/Users/midas/Desktop/IRISVOICE/src-tauri/src/iris_core/caducean.h)
- Add to `SessionState`:
  - `int l = 1, m = 1;` (winding numbers)
  - `double xi_prev1 = 0.0, xi_prev2 = 0.0;` (phase history)
  - `double c_eff = 1.0;` (precomputed cycle speed)
- Add a new C-compatible struct `DirectionSignal`:
  ```cpp
  struct DirectionSignal {
      double target_u;        // +1.0 or -1.0
      double force_magnitude; // |F(u)| = |a*u - b*u^3|
      double u_current;       // current u
      double phase;           // current ξ
      double balance;         // current EML-derived urgency
  };
  ```
- Declare on `Caducean` class:
  - `DirectionSignal get_direction_signal(const std::string& session_id);`
  - `void set_params(const std::string& session_id, double a, double b, double s);`
  - `void init_session(const std::string& session_id, int l, int m);`

#### [MODIFY] [caducean.cpp](file:///C:/Users/midas/Desktop/IRISVOICE/src-tauri/src/iris_core/caducean.cpp)
- In `init_session()`: compute `c_eff = (1.0 / sqrt(2.0)) * sqrt(l*l + m*m)`.
- In `update()`:
  - Shift history: `xi_prev2 = xi_prev1; xi_prev1 = xi;`
  - Advance phase: `xi = fmod(xi + balance * s * c_eff, 2.0 * M_PI)`
- Rewrite `recommend()` with **Adaptive Safety Net**:
  ```cpp
  double Q = std::abs(state.x - state.y) / (state.x + state.y + 1.0);
  double diff1 = std::remainder(state.xi - state.xi_prev1, 2.0 * M_PI);
  double diff2 = std::remainder(state.xi_prev1 - state.xi_prev2, 2.0 * M_PI);
  double phase_accel = std::abs(diff1 - diff2);
  if (Q > 0.8 && phase_accel > 0.05) return 3; // TOPO_VIOLATION
  // else: existing stable-orbit / force-based logic
  ```
- Implement `get_direction_signal()`:
  ```cpp
  double F = state.a * state.u - state.b * std::pow(state.u, 3);
  DirectionSignal sig;
  sig.target_u        = (state.u >= 0.0) ? 1.0 : -1.0;
  sig.force_magnitude = std::abs(F);
  sig.u_current       = state.u;
  sig.phase           = state.xi;
  sig.balance         = 1.0; // updated by caller via calculate_eml
  return sig;
  ```
- Implement `set_params()`: update `state.a`, `state.b`, `state.s`; recompute `c_eff` if `l,m` changed.

#### [MODIFY] [iris_core.h](file:///C:/Users/midas/Desktop/IRISVOICE/src-tauri/src/iris_core/iris_core.h)
- Define `DirectionSignal` in the FFI boundary (must match C++ struct exactly):
  ```c
  typedef struct {
      double target_u;
      double force_magnitude;
      double u_current;
      double phase;
      double balance;
  } IrisDirectionSignal;
  ```
- Declare FFI exports:
  ```c
  IRIS_API int caducean_init_session(const char* session_id, int l, int m);
  IRIS_API int caducean_get_direction_signal(const char* session_id, IrisDirectionSignal* out);
  IRIS_API int caducean_set_params(const char* session_id, double a, double b, double s);
  ```

#### [MODIFY] [iris_core.cpp](file:///C:/Users/midas/Desktop/IRISVOICE/src-tauri/src/iris_core/iris_core.cpp)
- Update `calculate_eml()`: if session has Caducean state, use O(1) accumulator formula:
  ```cpp
  // Ne=x, Nt=y, L=min(x,y), V=x+y+1
  // x_eml = (Ne/(1+Nt)) * (1 - L/V)
  // y_eml = (Nt/(1+Ne)) * (L/V) + 1e-5
  // EML = exp(x_eml) - log(y_eml)
  // balance = clamp(EML / 2.3418, 0.1, 3.0)
  ```
  Fall back to SQLite-based counts if no Caducean state.
- Implement the three new FFI wrappers as thin pass-throughs to `Caducean::get_instance()`.

---

### Component 2: Python FFI Bridge (`backend/gateway`)

#### [MODIFY] [iris_ffi.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/gateway/iris_ffi.py)
- Add `IrisDirectionSignal` ctypes structure:
  ```python
  class IrisDirectionSignal(ctypes.Structure):
      _fields_ = [
          ("target_u",        ctypes.c_double),
          ("force_magnitude", ctypes.c_double),
          ("u_current",       ctypes.c_double),
          ("phase",           ctypes.c_double),
          ("balance",         ctypes.c_double),
      ]
  ```
- In `_IrisFFI.__init__`:
  - Register argtypes/restypes for `caducean_init_session`, `caducean_get_direction_signal`, `caducean_set_params`
- Add wrapper methods that mirror the C++ signatures.
- Update `_PythonCaduceanFallbackState` to return a mock `IrisDirectionSignal` (target_u=+1, balance=1.0, etc.)
- Add module-level helpers:
  - `ffi_caducean_init_session(session_id, l=1, m=1) -> bool`
  - `ffi_caducean_get_direction_signal(session_id) -> IrisDirectionSignal`
  - `ffi_caducean_set_params(session_id, a, b, s) -> bool`

---

### Component 3: Mycelium Memory & Maintenance (`backend/memory`)

#### [MODIFY] [interface.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/memory/interface.py)
- **Component 0 fix** goes here (see above).
- Add `mycelium_record_anomaly(session_id, signal_type)` to expose the anomaly sensor to the agent kernel.
- New method to read the latest Caducean `u` for a session:
  ```python
  def get_caducean_state(self, session_id: str) -> Optional[Dict[str, float]]:
      """Returns {x, y, xi, u, balance, recommendation} or None."""
  ```

#### [MODIFY] [mycelium/interface.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/memory/mycelium/interface.py)
- Add `record_anomaly(session_id, signal_type)` → delegate to `_quorum_sensor.record_signal` + `_check_quorum_and_reorganize`.
- Add `get_latest_u(session_id)` → read last row from `caducean_trajectories` table.

#### [MODIFY] [mycelium/scorer.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/memory/mycelium/scorer.py)
- In `apply_decay()`, read latest `u` from `caducean_trajectories` for the session:
  - `u > 0` → `decay_multiplier = 0.5` (explore: preserve learning)
  - `u < 0` → `decay_multiplier = 1.8` (compress: prune unreinforced paths)
  - `u == 0` → `decay_multiplier = 1.0` (neutral)
- Read once at start of pass — no per-edge SQL.

#### [MODIFY] [mycelium/resonance.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/memory/mycelium/resonance.py)
- In `_score_candidate()`, read latest `u` (cached at top of `augment_retrieval`):
  - `u > 0` → multiply `resonance_multiplier` by `0.5` (creativity surge)
  - `u < 0` → multiply `resonance_multiplier` by `1.8` (focus lock)
  - `u == 0` → no change

#### [NEW] [backend/migrations/003_caducean_trajectories.sql](file:///C:/Users/midas/Desktop/IRISVOICE/backend/migrations/003_caducean_trajectories.sql)
```sql
CREATE TABLE IF NOT EXISTS caducean_trajectories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    x INTEGER NOT NULL,
    y INTEGER NOT NULL,
    xi REAL NOT NULL,
    u REAL NOT NULL,
    balance REAL NOT NULL,
    recommendation INTEGER NOT NULL,  -- 0=EXPAND, 1=COMPRESS, 2=CONTINUE, 3=TOPO_VIOLATION
    created_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_caducean_session_step
    ON caducean_trajectories(session_id, step);
```

Add migration call in `MemoryInterface.__init__` (idempotent).

---

### Component 4: Agent Kernel & DER Loop (`backend/agent`)

#### [MODIFY] [der_loop.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/agent/der_loop.py)
- In `DirectorQueue.next_ready()`:
  - Fetch `ffi_caducean_get_direction_signal(session_id)` once at top.
  - If `target_u == -1.0` (attractor → COMPRESS): restrict `ready_items` to `critical=True` only.
  - If `recommendation == 3` (TOPO_VIOLATION): raise `TopologyViolationException(session_id, direction_signal)`.

#### [MODIFY] [agent_kernel.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/agent/agent_kernel.py)
- In the Caducean update step:
  - Compute `balance = clamp(EML / 2.34, 0.1, 3.0)` (use the O(1) EML value from C++).
  - After `ffi_caducean_update(session_id, action, balance)`, check `ffi_caducean_recommend(session_id)`:
    - If `== 3` (TOPO_VIOLATION): call `memory.mycelium_record_anomaly(session_id, "update_velocity_anomaly")` and raise.
  - Persist trajectory row to `caducean_trajectories` table (fire-and-forget, try/except wrapped).

#### [MODIFY] [trajectory_controller.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/agent/trajectory_controller.py)
- After task completion, read `caducean_trajectories` for the session.
- If budget cap hit OR `TOPO_VIOLATION` count > threshold: compute adjustments to `a, b, s`:
  - `a += 0.1 * violation_count` (steeper potential well → faster recovery)
  - `b += 0.05 * violation_count` (deeper walls → less drift)
  - `s -= 0.01 * violation_count` (slower walk → less overshoot)
- Call `ffi_caducean_set_params(session_id, a, b, s)`.

#### [NEW] [coupled_registry.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/agent/coupled_registry.py)
- `class CoupledTrajectoryRegistry`:
  - Maintains `Dict[session_id, Dict[other_session_id, phase_delta]]`.
  - On each `caducean_update(session_id)`: scan registry for other active sessions.
  - If `c_eff1 / c_eff2` is rational (within 0.01 of p/q with small p,q): at phase alignment, exchange angular momentum (transfer ±0.1 to u between sessions → nucleus/barrier differentiation).
  - If irrational: apply destructive interference (`-= 0.05` to both `u` values).
- Singleton accessed by `get_coupled_registry()`.

---

### Component 5: Voice Pipeline — ConversationKernel (`backend/agent`)

> **Why this is in v2:** The technical overview lists ConversationKernel as "ready to build". The voice pipeline is the PRIMARY interface per CLAUDE.md. v2 makes the kernel phase-driven, not heuristic.

#### [NEW] [conversation_kernel.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/agent/conversation_kernel.py)
- `class ConversationKernel`:
  - Subscribes to Caducean `DirectionSignal` for the active session (via polling 100ms internal to backend, not over WS).
  - **Phase-based turn-taking:**
    - `ξ ∈ [0, π)`: AGENT_SPEAK (synthesize and stream TTS)
    - `ξ ∈ [π, 2π)`: AGENT_LISTEN (VAD active, expect user input)
  - **VAD feedback → Caducean:**
    - When user voice detected: `ffi_caducean_update(session_id, 1, balance)` (COMPRESS action)
    - When user finishes: `ffi_caducean_update(session_id, 0, balance)` (EXPAND action)
  - **TTS chunk sizing:**
    - `force_magnitude > 0.5` → synthesize larger chunks (confident, uninterrupted)
    - `force_magnitude < 0.1` → smaller chunks (easily interruptible)
  - **Interrupt handling:** if user voice during AGENT_SPEAK: record anomaly, force `target_u = -1.0`.

---

### Component 6: Tauri Shell — Thin Proxy Commands (`src-tauri/src`)

#### [NEW] [src-tauri/src/commands/caducean.rs](file:///C:/Users/midas/Desktop/IRISVOICE/src-tauri/src/commands/caducean.rs)
- `#[tauri::command] async fn caducean_get_state(session_id: String) -> Result<CaduceanState, String>`
  - HTTP GET `http://localhost:8000/api/caducean/state?session_id={id}`
  - Returns `{x, y, xi, u, balance, recommendation, target_u, force_magnitude}`
- `#[tauri::command] async fn caducean_get_direction_signal(session_id: String) -> Result<DirectionSignal, String>`
  - HTTP GET `http://localhost:8000/api/caducean/direction?session_id={id}`
- `#[tauri::command] async fn caducean_set_params(session_id: String, a: f64, b: f64, s: f64) -> Result<bool, String>`
  - HTTP POST `http://localhost:8000/api/caducean/params` with JSON body

#### [MODIFY] [src-tauri/src/main.rs](file:///C:/Users/midas/Desktop/IRISVOICE/src-tauri/src/main.rs)
- Register the three new commands via `.invoke_handler(tauri::generate_handler![...])`.
- No other changes — Rust remains a thin proxy.

---

### Component 7: FastAPI Endpoints (`backend/main.py`)

#### [MODIFY] [backend/main.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/main.py)
Add three endpoints:
- `GET /api/caducean/state?session_id=...` → `{x, y, xi, u, balance, recommendation}`
- `GET /api/caducean/direction?session_id=...` → `DirectionSignal` from `ffi_caducean_get_direction_signal`
- `POST /api/caducean/params` → body `{session_id, a, b, s}` → calls `ffi_caducean_set_params`

All endpoints: simple pass-through, no business logic. CORS already configured.

---

### Component 8: Frontend Hook (`app/`)

> **Confirmed: Option A polling for v1, Option B WS later.**

#### [NEW] [app/hooks/useCaducean.ts](file:///C:/Users/midas/Desktop/IRISVOICE/app/hooks/useCaducean.ts)
- React hook:
  ```typescript
  export function useCaducean(sessionId: string, pollMs = 500) {
    const [state, setState] = useState<CaduceanState | null>(null);
    useEffect(() => {
      const fetch = async () => {
        const r = await invoke('caducean_get_state', { sessionId });
        setState(r);
      };
      fetch();
      const id = setInterval(fetch, pollMs);
      return () => clearInterval(id);
    }, [sessionId, pollMs]);
    return state;
  }
  ```
- Uses `@tauri-apps/api` `invoke` (Tauri command, not HTTP).

#### [MODIFY] [app/components/VoiceInterface.tsx](file:///C:/Users/midas/Desktop/IRISVOICE/app/components/VoiceInterface.tsx)
- Consume `useCaducean(activeSessionId)`.
- Voice actions driven by Caducean state (replaces any hard-coded turn logic):
  - `target_u = +1` AND `force_magnitude > 0.3` → agent speaking phase, queue TTS
  - `target_u = -1` → agent listening phase, VAD active
  - `recommendation === 3` → show "topology violation" debug indicator (dev mode only)
- TTS chunk size: `Math.max(20, Math.min(200, force_magnitude * 300))` tokens.

#### [NEW] [app/components/CaduceanDebugPanel.tsx](file:///C:/Users/midas/Desktop/IRISVOICE/app/components/CaduceanDebugPanel.tsx)
- Dev-only floating panel: `(x, y, ξ, u, balance, target_u, force_magnitude)` as live values.
- Small phase-space plot (`u` vs `ξ`).
- Manual sliders for `a, b, s` calling `caducean_set_params`.

---

### Component 9: Verification Suite (`backend/tests`)

#### [MODIFY] [test_iris_core_smoke.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/test_iris_core_smoke.py)
- Add tests:
  - `test_caducean_init_session_returns_success` — `ffi_caducean_init_session("test", 1, 1)` returns True.
  - `test_caducean_direction_signal_fields` — struct has all 5 fields, types correct.
  - `test_caducean_direction_signal_target_u_sign` — `target_u` is +1 or -1.
  - `test_caducean_adaptive_safety_net_no_false_positive` — stable limit cycle does NOT fire TOPO_VIOLATION.
  - `test_caducean_adaptive_safety_net_real_drift` — chaotic input DOES fire TOPO_VIOLATION.
  - `test_caducean_set_params_updates_a_b_s` — verify via `get_direction_signal().u` after many updates with new params.

#### [NEW] [test_caducean_v2_integration.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/test_caducean_v2_integration.py)
- End-to-end: init engine → run 100 agent steps → verify `caducean_trajectories` table populated → verify Mycelium decay multiplier was modulated.
- 2-session coupling: register two sessions with rational c_eff → verify angular momentum exchange at phase alignment.

#### [NEW] [test_conversation_kernel.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/test_conversation_kernel.py)
- Mock VAD events → verify correct EXPAND/COMPRESS actions sent to Caducean.
- Verify TTS chunk size scales with `force_magnitude`.
- Verify interrupt during AGENT_SPEAK records anomaly.

---

## Build / Verification Plan

### Phase 0: Critical Fix (Engine Init)
1. Apply Component 0 fix.
2. Run `python -c "from backend.memory.interface import MemoryInterface; m = MemoryInterface(None, 'test.db', b'\\x00'*32); print('OK')"`
3. Verify `backend/native/iris_core.dll` is now actually loaded (check log).

### Phase 1: C++ Core + Python FFI
1. Run `.\build_cpp_core.ps1` — compile new DLL.
2. Run `python -m pytest backend/tests/test_iris_core_smoke.py -v`
3. All smoke tests + new `test_caducean_v2_integration.py` must pass.

### Phase 2: Mycelium Modulation
1. Apply Components 3 modifications.
2. Run `python -m pytest backend/memory/tests/test_mycelium_*.py -v`
3. All existing memory tests must pass + new modulation tests.

### Phase 3: Agent Kernel + DER Loop
1. Apply Components 4 modifications.
2. Run `python -m pytest backend/agent/tests/ backend/tests/test_der_loop.py -v`
3. All existing DER tests must pass.

### Phase 4: Tauri Shell + Frontend
1. Apply Components 6, 7, 8 modifications.
2. `cargo tauri dev` — verify app launches, debug panel populates.
3. Test: `useCaducean` returns live values, sliders update C++ state.

### Phase 5: Voice Kernel
1. Apply Component 5 (ConversationKernel).
2. Manual test: speak → verify phase transitions visible in debug panel.
3. Test TTS chunk size changes when `force_magnitude` crosses 0.5.

### Phase 6: Full Integration
1. `python -m pytest backend/tests/ backend/memory/tests/ backend/agent/tests/ -v`
2. All 250+ existing tests + new v2 tests must pass.
3. Manual e2e: wake word → speak → IRIS responds → debug panel shows live state.

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| DLL load failure blocks startup | `ffi_init_engine()` already returns False → Python fallback activates |
| Frontend polling overloads backend | 500ms interval = 2 req/s; backend endpoints are O(1) |
| Phase history initialization bug | Initialize `xi_prev1 = xi_prev2 = xi` on first `update()` |
| TOPO_VIOLATION false positives | Adaptive safety net (phase_accel > 0.05) — Gate 2 result: 0% FP |
| O(1) EML drift from real counts | Keep SQLite fallback for cross-validation in tests |
| TrajectoryController over-tunes params | Clamp `a ∈ [1.0, 4.0]`, `b ∈ [1.0, 4.0]`, `s ∈ [0.1, 0.8]` |
| CoupledRegistry thrashing on many sessions | Singleton with explicit `register_session()` / `unregister_session()` |

---

## Out of Scope (deferred to v3)

- WebSocket broadcast for real-time DirectionSignal (Option B from decision matrix)
- Multi-kernel shared Σ state across processes
- Cross-project landmark bridge with Caducean state
- ConvStreamKernel for TTS chunking driven by `force_magnitude`
- PiN auto-anchor triggered by Caducean state (e.g., "preserve this decision — we're in compress mode")

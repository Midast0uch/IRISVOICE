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

> **Architectural decision (2026-06-12 update):** The voice pipeline is a **rich existing communication layer** — `iris_gateway._on_voice_result` → `_process_voice_transcription` → `_speak_response` (with native C++ audio fast-path), `VoiceCommandHandler` (with energy-based VAD, audio-level callbacks, state transitions), and `TTSManager.synthesize_stream()` (with sentence chunking, interrupt support). **ConversationKernel is NOT a new system — it is a thin orchestrator that wraps these existing pieces** with Caducean phase-awareness. Zero duplication. Zero parallel state.

#### [NEW] [conversation_kernel.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/agent/conversation_kernel.py)
- `class ConversationKernel`:
  - **Constructor** takes references to already-wired singletons:
    ```python
    def __init__(self, voice_handler: VoiceCommandHandler, tts_manager: TTSManager,
                 audio_pipeline: AudioPipeline, get_caducean_state: Callable):
        ...
    ```
  - **NOT** a new event loop, NOT a new VAD, NOT a new TTS — only adds Caducean state to the decisions that existing classes already make.
  - **Hook into existing callbacks** (no rewiring):
    - `voice_handler.set_state_callback(self._on_voice_state)` — observe IDLE→RECORDING→PROCESSING transitions
    - `voice_handler.set_audio_level_callback(self._on_audio_level)` — observe RMS for VAD-fire signal
    - (Optional) hook into the existing `_on_audio_level` RMS path in `iris_gateway` — ConversationKernel reads the same level for phase updates
  - **Phase-to-action mapping** (the *only* new logic):
    | Caducean state | Existing class action (no change) | ConversationKernel addition |
    |----------------|-----------------------------------|-----------------------------|
    | `target_u = +1.0` AND `ξ ∈ [0, π)` | TTS streams via `_speak_response` | Read `force_magnitude`, scale TTS chunk size |
    | `target_u = -1.0` OR `ξ ∈ [π, 2π)` | VoiceCommandHandler is recording | If user speaks, send COMPRESS action to Caducean |
    | User voice during agent speech | `_speak_response` checks `interrupted` event | `force target_u = -1.0` via `ffi_caducean_set_params` |
    | `recommendation == 3` | (no existing behavior) | Halt TTS via `audio_pipeline.interrupt()` + `engine.interrupt_speech()` |
  - **Methods (thin wrappers, no parallel logic):**
    ```python
    def _on_voice_state(self, state: VoiceState, message: str) -> None:
        """Fires on every VoiceCommandHandler state transition. Updates Caducean
        with EXPAND when transitioning to IDLE (user turn complete) and COMPRESS
        when entering RECORDING (user turn started)."""
        if state == VoiceState.RECORDING:
            ffi_caducean_update(self._session_id, 1, self._current_balance)
        elif state == VoiceState.IDLE and self._was_speaking:
            ffi_caducean_update(self._session_id, 0, self._current_balance)

    def _on_audio_level(self, level: float) -> None:
        """Already wired in iris_gateway. We read the same level for force_magnitude
        → TTS chunk size scaling. No duplicate VAD — single source of truth."""
        self._current_audio_level = level
        if level > 0.5 and self._speaking_active:
            # User speaking during agent speech — barge-in
            self._interrupt_for_barge_in()

    def get_tts_chunk_size(self) -> int:
        """Returns the chunk size in tokens for the next TTS synthesis, scaled
        by force_magnitude. Called by _speak_response (via a wrapper) to replace
        the hardcoded FIRST_CHUNK_THRESHOLD/NORMAL_CHUNK_THRESHOLD constants."""
        sig = ffi_caducean_get_direction_signal(self._session_id)
        chunk = int(sig.force_magnitude * 300)
        return max(20, min(200, chunk))

    def should_halt_on_violation(self) -> bool:
        """Returns True if Caducean reports TOPO_VIOLATION. Called by _speak_response
        at chunk boundary. Halts TTS via existing audio_pipeline.interrupt()."""
        rec = ffi_caducean_recommend(self._session_id)
        if rec == 3:
            audio_pipeline.interrupt()  # existing method, no new logic
            return True
        return False
    ```
  - **No new threads, no new queues, no new state machines** — everything routes through existing `VoiceCommandHandler.state` enum, existing `_on_audio_level` callback, existing `audio_pipeline.interrupt()`, existing `engine.interrupt_speech()`.

#### [MODIFY] [iris_gateway.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/iris_gateway.py) — minimal hooks
- In `set_voice_handler()` (already exists, ~line 1479), instantiate the `ConversationKernel` and pass it the same references. **No other changes.**
- In `_speak_response()` (already exists, ~line 1925), replace the hardcoded `FIRST_CHUNK_THRESHOLD = 1` / `NORMAL_CHUNK_THRESHOLD = 8` constants with a call to `conversation_kernel.get_tts_chunk_size()` at the point where chunks are decided (~line 1955).
- In `_speak_response()`, add a single check per chunk: `if conversation_kernel.should_halt_on_violation(): break` (one line addition).
- **No other changes to iris_gateway.** All the wake-word, STT, agent routing, TTS, and interrupt logic remains untouched.

#### [MODIFY] [backend/main.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/main.py) — lifespan
- After the existing `iris_gateway.set_voice_handler(voice_handler)` call (~line in `lifespan`), add: `iris_gateway.set_caducean_session(session_id)`. This wires the active session_id into the kernel — frontend generates the session_id via the existing WS handshake (Option C from our decision matrix).

#### [MODIFY] [backend/agent/agent_kernel.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/agent/agent_kernel.py) — voice-first mode
- The existing `voice_first` mode (`DER_TOKEN_BUDGETS["voice_first"] = 15000` and `task_class == "voice_first"` single-step) is **unchanged**. The Caducean v2 integration is at the *physics* layer — agent_kernel is unaware. The existing mode detection in `_process_voice_transcription(from_voice=True)` continues to work.

#### Why this consolidation matters

| Concern | Old plan (parallel system) | New plan (thin wrapper) |
|---------|---------------------------|--------------------------|
| New VAD | Would duplicate VoiceCommandHandler's energy-based VAD | Reuse `_on_audio_level` callback |
| New TTS | Would need a separate streaming path | `TTSManager.synthesize_stream()` unchanged |
| New state machine | VoiceState + CaduceanState + ??? | VoiceState only (Caducean state is read-only input) |
| New interrupt logic | Three ways to interrupt TTS | Single path: `audio_pipeline.interrupt()` (existing) |
| Wiring changes | Touch every file in audio/ | Touch iris_gateway.set_voice_handler (one method) |
| Failure modes | N independent paths, N×M failures | Single path, single failure mode |
| Testing | Re-test all voice tests | Voice tests unchanged; add 1-2 new behavioral tests |

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

### Component 9: Verification Suite — Layered Testing (`backend/tests`)

> **Why this is 4 separate layers:** Unit tests prove the code runs. Integration tests prove the components connect. **Contract tests** prove the FFI boundary and API surface are stable. **Behavioral tests** prove the *physics behaves correctly* — that an agent in "explore mode" actually retains more memory than one in "compress mode" over 1000+ steps. Without behavioral tests, v2 could "pass all tests" while the Mycelium is actually getting worse.

#### Layer 1: Unit Tests (existing + new)

#### [MODIFY] [test_iris_core_smoke.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/test_iris_core_smoke.py)
- Add tests:
  - `test_caducean_init_session_returns_success` — `ffi_caducean_init_session("test", 1, 1)` returns True.
  - `test_caducean_direction_signal_fields` — struct has all 5 fields, types correct.
  - `test_caducean_direction_signal_target_u_sign` — `target_u` is +1 or -1.
  - `test_caducean_set_params_updates_a_b_s` — verify via `get_direction_signal().u` after many updates with new params.
  - `test_caducean_c_eff_formula_correct` — for (l=1,m=1): c_eff=1.0; (2,1): 1.414; (3,3): 2.121 (within 0.001).
  - `test_caducean_winding_number_rejected` — `init_session("t", 0, 0)` raises or rejects (l,m must be non-zero).

#### Layer 2: Integration Tests (cross-component)

#### [NEW] [test_caducean_v2_integration.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/test_caducean_v2_integration.py)
- `test_trajectory_table_populated` — init engine → run 100 agent steps → `SELECT COUNT(*) FROM caducean_trajectories WHERE session_id=?` returns 100.
- `test_o1_eml_matches_sql_eml` — for 20 randomized (x,y) pairs, compare O(1) formula result to SQLite-based result within 0.01 tolerance.
- `test_mycelium_decay_modulated_by_u` — run maintenance with u>0 vs u<0, verify edge score distributions differ as expected.
- `test_resonance_multiplier_modulated_by_u` — same episode set retrieved with u>0 vs u<0, verify different candidates selected.
- `test_der_queue_restricted_on_compress` — set target_u=-1, verify `next_ready()` returns only critical items.
- `test_topo_violation_raises_and_records_anomaly` — force TOPO_VIOLATION, verify exception raised AND `mycelium_anomaly` table has row.
- `test_2session_rational_coupling` — register sessions with (l=1,m=1) and (l=2,m=2) (rational c_eff ratio), run 200 steps, verify angular momentum exchange.
- `test_2session_irrational_interference` — sessions with (1,1) and (3,2) (irrational ratio), verify destructive interference (-0.05 to u).

#### [NEW] [test_conversation_kernel.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/test_conversation_kernel.py)
- **Consolidation tests (prove we didn't break the existing pipeline):**
  - `test_voice_handler_state_callbacks_wired` — ConversationKernel registers `_on_voice_state` AND `_on_audio_level` on the existing `VoiceCommandHandler` (no new callbacks added).
  - `test_no_duplicate_vad` — `AudioPipeline` is the only VAD source; ConversationKernel has no `is_voice_active` method (uses existing audio_level).
  - `test_no_duplicate_tts` — `TTSManager` is the only TTS source; ConversationKernel has no `synthesize` method (returns chunk size only).
  - `test_existing_voice_tests_still_pass` — full `test_domain2_voice.py` suite (38 tests) passes unchanged.
  - `test_speak_response_uses_kernel_chunk_size` — mock ConversationKernel returning chunk=200, verify `_speak_response` synthesizes 200-token chunks (not the old hardcoded thresholds).
  - `test_halt_on_violation_breaks_tts_loop` — mock `should_halt_on_violation()=True`, verify TTS loop breaks within 1 chunk.
- **Behavioral tests (the new physics):**
  - `test_vad_compress_action_sent` — mock VAD voice detected, verify `ffi_caducean_update(session_id, 1, balance)` called.
  - `test_vad_end_expand_action_sent` — mock VAD voice ended, verify `ffi_caducean_update(session_id, 0, balance)` called.
  - `test_tts_chunk_size_scales_with_force` — force_magnitude=0.1 → chunk=20 tokens; force_magnitude=1.0 → chunk=200 tokens.
  - `test_interrupt_during_speak_records_anomaly` — user voice during AGENT_SPEAK, verify anomaly recorded AND target_u forced to -1.

#### Layer 3: Contract Tests (FFI + API boundary stability)

> **Why contracts matter:** The C++ ↔ Python boundary and the HTTP API surface are both contractual. If `DirectionSignal` field order changes, ctypes silently corrupts memory. If a JSON field renames, frontend breaks at runtime. Contract tests fail loudly when the contract drifts.

#### [NEW] [test_caducean_ffi_contract.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/test_caducean_ffi_contract.py)
- **Struct shape contract:** `IrisDirectionSignal` ctypes structure has exactly 5 fields, all `c_double`, in this order: `target_u, force_magnitude, u_current, phase, balance`. Failure = "struct drift detected".
- **Argtype contract:** Every new FFI function has matching `argtypes` in `_IrisFFI.__init__`. Test iterates functions and checks against a frozen manifest.
- **Restype contract:** All void-returning FFI functions have `restype = None`; all int-returning have `restype = c_int`; double-returning have `c_double`. Drift = "FFI manifest stale".
- **Return code contract:** `caducean_recommend()` returns only {0, 1, 2, 3}. Any other value = "recommendation code drift".
- **Fallback parity contract:** When Python fallback is active (DLL missing), `ffi_caducean_get_direction_signal()` returns a DirectionSignal with all 5 fields populated (not None). Verifies graceful degradation.

#### [NEW] [test_caducean_api_contract.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/test_caducean_api_contract.py)
- Uses `httpx.AsyncClient` against a `TestClient(main.app)` instance.
- `GET /api/caducean/state` response schema: `{x: int, y: int, xi: float, u: float, balance: float, recommendation: int}` — all fields required, types enforced via Pydantic model.
- `GET /api/caducean/direction` response schema: matches `IrisDirectionSignal` exactly (5 doubles).
- `POST /api/caducean/params` request schema: `{session_id: str, a: float, b: float, s: float}` — Pydantic validation.
- `POST /api/caducean/params` response: `{ok: bool}` always (even on error, error in `error` field).
- 400/404/422 behavior: invalid session_id → 404; missing fields → 422 with detail; type errors → 422.
- Contract is frozen in a JSON file (`backend/tests/contracts/caducean_api_v2.json`) and checked in.

#### [NEW] [backend/tests/contracts/caducean_api_v2.json](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/contracts/caducean_api_v2.json)
- JSON Schema definitions for all request/response shapes. Used by both Python (`jsonschema` lib) and Rust (`schemars`) for cross-language validation.

#### Layer 4: Behavioral E2E Tests (physics behaves correctly over time)

> **Why behavioral tests are critical:** A "passing" integration test might confirm the table got a row, but it can't tell if Mycelium actually retains better in explore mode. Behavioral tests run long simulations and assert on the *statistical outcome* — that physics contract is honored.

#### [NEW] [test_caducean_behavioral.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/test_caducean_behavioral.py)
- **Test: explore mode retains more edges than compress mode.**
  - Setup: 1000 Mycelium edges with identical decay rates.
  - Run A: maintain u=+0.5 (explore) for 1000 maintenance cycles → measure retained edges.
  - Run B: maintain u=-0.5 (compress) for 1000 maintenance cycles → measure retained edges.
  - Assert: retained_A > retained_B (explore mode preserves memory, compress mode prunes).
- **Test: adaptive safety net has 0% false positives on stable limit cycles.**
  - Run 200 agent steps on a stable task (per Gate 2 mid-tier: 30–70 steps, success path).
  - Assert: TOPO_VIOLATION count = 0 over 100 trials (Gate 2 baseline: static net had 58% FPs).
- **Test: adaptive safety net catches real drift within 5 steps.**
  - Force a chaotic input sequence (random action, extreme balance).
  - Assert: TOPO_VIOLATION fires within ≤ 5 steps of drift onset.
- **Test: phase_accel invariant on stable limit cycle.**
  - Run 500 steps of balanced updates.
  - Assert: `mean(abs(phase_accel))` < 0.01 (limit cycle has zero acceleration).
- **Test: trajectory persistence is non-blocking.**
  - Call `ffi_caducean_update()` 1000 times in a tight loop with persistence enabled.
  - Assert: total wall time < 5 seconds (DB writes must not block hot path).
- **Test: coupled registry actually differentiates roles.**
  - Register 2 sessions with rational c_eff ratio, run 1000 cycles.
  - Assert: one session's `mean(u)` > 0 (barrier) AND other's `mean(u)` < 0 (nucleus).
- **Test: ConversationKernel respects physics within 100ms.**
  - Inject voice event → measure time until `DirectionSignal.target_u` reflects it.
  - Assert: latency < 100ms (real-time responsiveness).

#### Layer 5: Full Stack E2E (Tauri + Python + C++ + Mycelium + Voice)

> **Why full-stack E2E:** Component tests can all pass while the integrated system is broken (e.g., a Tauri command that can't find the Python server, or a frontend hook that calls the wrong field name). Full-stack E2E catches integration issues at the boundary.

#### [NEW] [backend/tests/e2e/conftest.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/e2e/conftest.py)
- Fixtures: `live_backend` (starts FastAPI on a free port), `live_tauri_app` (spawns Tauri dev or uses Tauri's mock harness), `playwright_browser` (chromium headless), `mock_audio_stream` (synthesizes PCM data for VAD/TTS).

#### [NEW] [backend/tests/e2e/test_caducean_full_stack.py](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/e2e/test_caducean_full_stack.py)
- **Test: Frontend hook → Tauri command → Python HTTP → C++ FFI roundtrip.**
  - Playwright opens the app, navigates to debug panel.
  - Wait for `useCaducean` first poll (≤1s).
  - Assert: panel displays non-zero `x, y, u, ξ`.
  - Move a slider → wait 1s → assert C++ state changed (read via `/api/caducean/state`).
- **Test: Voice pipeline phase transitions visible in UI.**
  - Inject mock PCM audio (3s of speech) into VAD pipeline.
  - Wait 2s for ConversationKernel to process.
  - Playwright checks debug panel: `target_u` flipped to `-1`, `phase` advanced into `[π, 2π)`.
- **Test: Mycelium decay rate changes when Caducean state changes.**
  - Pre-populate Mycelium with 100 edges (all same decay_rate=0.01, same age).
  - Force u=+0.8 via API. Run maintenance.
  - Verify: edges_retained > 80.
  - Force u=-0.8 via API. Reset, run maintenance.
  - Verify: edges_retained < 50.
- **Test: TOPO_VIOLATION halts DER loop and shows in UI.**
  - Force chaotic inputs via API for 10 steps.
  - Assert: `/api/caducean/state` returns `recommendation: 3` within 5 steps.
  - Assert: DER loop's next call raises `TopologyViolationException` (caught and surfaced).
  - Playwright checks: debug panel shows "TOPO_VIOLATION" red indicator.

#### [NEW] [backend/tests/e2e/run_e2e.sh](file:///C:/Users/midas/Desktop/IRISVOICE/backend/tests/e2e/run_e2e.sh) (and `run_e2e.ps1`)
- Orchestration script:
  1. Compile C++ DLL (`build_cpp_core.ps1`).
  2. Start FastAPI on test port (background).
  3. Start Tauri dev or load Tauri mock.
  4. Run pytest with `--e2e` marker.
  5. Teardown all processes (even on failure).
- Returns non-zero exit on any E2E failure → blocks CI.

#### Test Markers and CI Integration

- `pytest.mark.unit` — fast (<1s each), run on every commit.
- `pytest.mark.integration` — medium (1–10s each), run on every PR.
- `pytest.mark.contract` — fast (validates structure), run on every commit.
- `pytest.mark.behavioral` — slow (10s–5min each), run nightly.
- `pytest.mark.e2e` — very slow (minutes), run pre-release + manually on demand.

**Graduate condition for testing layer:**
- All unit + integration + contract tests pass on every commit (CI gate).
- All behavioral tests pass in 3 consecutive nightly runs.
- At least 1 full-stack E2E test runs successfully end-to-end (proves the wiring works).
- Contract JSON schema is versioned in git; any drift fails CI loudly.

---

## Build / Verification Plan (UPDATED)

### Phase 0: Critical Fix (Engine Init)
1. Apply Component 0 fix.
2. Run `python -c "from backend.memory.interface import MemoryInterface; m = MemoryInterface(None, 'test.db', b'\\x00'*32); print('OK')"`
3. Verify `backend/native/iris_core.dll` is now actually loaded (check log).
4. **NEW:** Run `pytest backend/tests/test_iris_core_smoke.py -v` — existing 9 tests must pass.

### Phase 1: C++ Core + Python FFI + Unit/Contract
1. Run `.\build_cpp_core.ps1` — compile new DLL.
2. Run `pytest -m unit backend/tests/test_iris_core_smoke.py -v` — new unit tests must pass.
3. **NEW:** Run `pytest -m contract backend/tests/test_caducean_ffi_contract.py -v` — FFI struct/argtype contracts must hold.

### Phase 2: Mycelium Modulation + Integration
1. Apply Components 3 modifications.
2. Run `pytest backend/memory/tests/test_mycelium_*.py -v` — existing + new tests must pass.
3. **NEW:** Run `pytest -m integration backend/tests/test_caducean_v2_integration.py -v`.

### Phase 3: Agent Kernel + DER Loop + Behavioral
1. Apply Components 4 modifications.
2. Run `pytest backend/agent/tests/ backend/tests/test_der_loop.py -v`.
3. **NEW:** Run `pytest -m behavioral backend/tests/test_caducean_behavioral.py -v` — must complete in <5 min, all pass.

### Phase 4: Tauri Shell + Frontend + API Contract
1. Apply Components 6, 7, 8 modifications.
2. `cargo tauri dev` — verify app launches, debug panel populates.
3. **NEW:** Run `pytest -m contract backend/tests/test_caducean_api_contract.py -v` — API schema frozen.
4. **NEW:** Move `caducean_api_v2.json` schema into a generated typescript type via `json-schema-to-typescript` so frontend drift fails at build time.

### Phase 5: Voice Kernel + Conversation E2E
1. Apply Component 5 (ConversationKernel).
2. Run `pytest -m unit backend/tests/test_conversation_kernel.py -v` — unit tests for kernel logic.
3. **NEW:** Run `pytest -m integration backend/tests/test_caducean_v2_integration.py::test_voice_phase_transitions -v` (integration with mock VAD).

### Phase 6: Full E2E (Manual + Automated)
1. `pytest backend/tests/ backend/memory/tests/ backend/agent/tests/ -v` — all unit/integration/contract pass.
2. `bash backend/tests/e2e/run_e2e.sh` — full-stack E2E suite runs end-to-end.
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

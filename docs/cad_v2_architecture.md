# Caducean Engine v2 — Architecture
## The Mitochondrial Cognitive Governor for Mycelium Memory

> **Branch:** `feat/caducean-v2-mitochondria-mycelium`
> **Date:** 2026-06-12

---

## 1. Executive Summary: Mitochondria to Mycelium

In the IRISVOICE architecture, the **Mycelium designed memory** acts as the structural nervous system — indexing nodes, recording relationships, and storing facts. However, a nervous system without a metabolic regulator is passive.

The **Caducean Engine v2** is the **mitochondria** of this system. It is a four-dimensional, physics-governed attention governor that regulates the pace, metabolic decay, and retrieval energy of the memory layer. By coupling the physics of the Duffing oscillator directly with the Mycelium graph, the system establishes a symbiotic relationship where cognitive momentum determines memory retention, search creativity, and loop termination.

```
                  ┌──────────────────────────────┐
                  │      Caducean Engine         │
                  │   Σ = (x, y, ξ, u) State     │
                  └──────────────┬───────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ Mycelium Decay  │     │ Resonance RAG   │     │ Quorum Sensor   │
│ Modulates rate  │     │ Scales retrieval│     │ Alerts on loop  │
│ based on u      │     │ creativity      │     │ instability     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │  Voice Pipeline (ConvKernel) │
                  │  Phase → speak/listen         │
                  │  force_magnitude → TTS chunk  │
                  └──────────────────────────────┘
```

---

## 2. Core Mathematical Foundations

At any moment, each session holds a four-dimensional state vector $\Sigma = (x, y, \xi, u)$ governed by the double-well Duffing potential:

$$V(u) = -\frac{a u^2}{2} + \frac{b u^4}{4}$$

which provides a restoring force:

$$F(u) = a u - b u^3$$

that pulls the attentional velocity $u \in [-1, 1]$ toward stable attractors at $u^* = \pm 1.0$ (representing the Expansion and Compression cognitive basins).

### 2.1 Winding Numbers & Cycle Speed

Winding numbers $(l, m) \in \mathbb{Z}^2$ classify the topology of the phase-woven domain and determine the effective cycle speed $c_{\text{eff}}$:

$$c_{\text{eff}} = \frac{1}{\sqrt{2}} \sqrt{l^2 + m^2}$$

The angular attention phase $\xi$ advances step-by-step:

$$\xi(t+1) = \left(\xi(t) + \text{balance} \cdot s \cdot c_{\text{eff}}\right) \pmod{2\pi}$$

where $s$ is the walk speed and $\text{balance}$ is the EML-derived feedback signal. Winding numbers allow different sessions to run at precisely controlled relative speeds.

### 2.2 $O(1)$ Epistemic Metabolic Learning (EML)

Rather than executing expensive database queries on every step to calculate EML, v2 computes it in $O(1)$ time directly from the live session accumulators:

$$N_e = x, \quad N_t = y, \quad L = \min(x, y), \quad V = x + y + 1$$

$$x_{\text{eml}} = \frac{N_e}{1 + N_t} \left(1 - \frac{L}{V}\right)$$

$$y_{\text{eml}} = \frac{N_t}{1 + N_e} \left(\frac{L}{V}\right) + 10^{-5}$$

$$\text{EML} = e^{x_{\text{eml}}} - \ln(y_{\text{eml}})$$

$$\text{balance} = \text{clamp}\left(\frac{\text{EML}}{2.3418}, 0.1, 3.0\right)$$

This O(1) calculation removes the database bottleneck entirely from the main execution loop. Gate 2 (LLM-validated) confirmed this gives the same signal as the SQL-based EML within numerical noise.

### 2.3 The Bias-Free DirectionSignal

The engine exposes its raw physics state to callers via a struct:

```cpp
struct DirectionSignal {
    double target_u;        // +1.0 (expansion attractor) or -1.0 (compression attractor)
    double force_magnitude; // |F(u)| = |a·u - b·u³|
    double u_current;       // current velocity
    double phase;           // current ξ ∈ [0, 2π)
    double balance;         // current EML-derived urgency ∈ [0.1, 3.0]
};
```

The **caller** (agent kernel, voice kernel, TTS stream) decides what "toward `target_u = +1`" means in its own domain. The physics provides the rhythm; the domain provides the interpretation.

---

## 3. Advanced Capabilities & Integrations

### 3.1 Caducean-Modulated Mycelium Decay

During memory maintenance cycles, edge score decay is scaled by the last recorded attentional velocity $u$:

| Mode | `u` | decay_multiplier | Effect |
|------|-----|------------------|--------|
| **Explore** | `> 0` | `0.5` | Preserve exploratory paths; graph expands |
| **Compress** | `< 0` | `1.8` | Prune unreinforced paths faster; graph cleans up |
| **Neutral** | `≈ 0` | `1.0` | Standard decay |

Read once at the start of `apply_decay()` — no per-edge SQL. The decision is made on the live physics, not on a heuristic.

### 3.2 Caducean-Modulated Resonance Retrieval

Episodic memory re-ranking dynamically adjusts its selectivity based on the cognitive momentum $u$:

| Mode | `u` | resonance multiplier | Effect |
|------|-----|---------------------|--------|
| **Creativity Surge** | `> 0` | `× 0.5` | Lower threshold; pull in distant episodes; foster creative problem-solving |
| **Focus Lock** | `< 0` | `× 1.8` | Higher threshold; force exact coordinate matches; prevent hallucinations |
| **Neutral** | `≈ 0` | `× 1.0` | Standard retrieval |

The cognitive state directly controls the precision-recall tradeoff in memory retrieval.

### 3.3 The Adaptive Safety Net

To distinguish between stable limit cycles (desirable) and genuine topological drift (unstable rambling), the safety net monitors **phase acceleration**:

$$\Delta\xi_1 = \text{remainder}(\xi - \xi_{\text{prev1}}, 2\pi)$$

$$\Delta\xi_2 = \text{remainder}(\xi_{\text{prev1}} - \xi_{\text{prev2}}, 2\pi)$$

$$\text{phase\_accel} = |\Delta\xi_1 - \Delta\xi_2|$$

If the topological charge proxy $|Q| = \frac{|x-y|}{x+y+1} > 0.8$ AND $\text{phase\_accel} > 0.05$, the system identifies a genuine drift anomaly and fires a `TOPO_VIOLATION` (return code `3`).

**Why this works:** A stable limit cycle has $\frac{d^2\xi}{dt^2} \approx 0$ — constant phase velocity, zero acceleration. Genuine drift has nonzero phase acceleration as the system is pushed away from its orbit. The static safety net misidentified 58% of stable limit cycles as violations (Gate 2 C4 results). The adaptive net eliminates all false positives while retaining immediate detection of genuine drift.

When a violation fires:
1. The Python agent kernel records `update_velocity_anomaly` to the Mycelium `QuorumSensor`.
2. If the QuorumSensor threshold is crossed, `QuorumReorganization` fires (existing v1 behavior, now physics-triggered).

### 3.4 Cross-Kernel Multi-Session Coupling

Multiple active kernels (e.g., coding agent, voice conversation, audio streaming) communicate using rationally related winding speeds:

$$\frac{c_{\text{eff1}}}{c_{\text{eff2}}} = \frac{\sqrt{l_1^2 + m_1^2}}{\sqrt{l_2^2 + m_2^2}} = \frac{p}{q}$$

When their phase clocks align (e.g., both hit $\xi = 0$ simultaneously), they transfer angular momentum:
- One session spontaneously settles into a compression bias (**nucleus** role — more inward energy)
- The other is pushed into an expansion bias (**barrier** role — more outward energy)
- If the speed ratio is irrational, the engine introduces destructive phase interference: both `u` values are reduced by 0.05, simulating resonance friction

The `CoupledTrajectoryRegistry` (new in v2) is a Python singleton that maintains the cross-session registry and computes alignment events. The C++ engine stays single-session; the coupling is a Python-level composition over `ffi_caducean_get_direction_signal()` calls.

### 3.5 Phase-Driven Voice Kernel (ConversationKernel) — NEW in v2

> **Architectural principle (consolidation, not greenfield):** The voice pipeline is the **richest communication layer** in the backend. `iris_gateway._on_voice_result → _process_voice_transcription → _speak_response` is a complete wake-word → STT → agent → TTS pipeline. `VoiceCommandHandler` already provides energy-based VAD, audio-level callbacks, and a `VoiceState` enum. `TTSManager.synthesize_stream()` already supports streaming and interrupt. **ConversationKernel is a thin orchestrator that adds Caducean phase-awareness to decisions these classes already make.** No new VAD, no new TTS, no new state machine, no new event loop.

The voice pipeline is the primary interface per CLAUDE.md. v2 makes it **phase-aware** rather than phase-replacing:

| Caducean state | Existing class behavior (unchanged) | ConversationKernel addition |
|----------------|--------------------------------------|------------------------------|
| `target_u = +1.0` AND `ξ ∈ [0, π)` | `_speak_response()` streams TTS | Read `force_magnitude`, scale chunk size |
| `target_u = -1.0` OR `ξ ∈ [π, 2π)` | `VoiceCommandHandler` is recording | Send COMPRESS to Caducean on user speech start |
| User voice during agent speech | `_speak_response` checks `interrupted` event | Force `target_u = -1.0` via `ffi_caducean_set_params` |
| `recommendation == 3` (TOPO_VIOLATION) | (no existing behavior) | Halt TTS via existing `audio_pipeline.interrupt()` |

**Wiring (3 minimal touches, no rewiring):**

1. `iris_gateway.set_voice_handler()` (existing, ~line 1479): instantiate `ConversationKernel` with references to the already-wired `voice_handler`, `tts_manager`, `audio_pipeline`, and a `get_caducean_state` callable.
2. `_speak_response()` (existing, ~line 1925): replace the hardcoded `FIRST_CHUNK_THRESHOLD = 1` / `NORMAL_CHUNK_THRESHOLD = 8` constants with `conversation_kernel.get_tts_chunk_size()`. Add one line: `if conversation_kernel.should_halt_on_violation(): break`.
3. `_on_voice_state` and `_on_audio_level` callbacks (already wired in `set_voice_handler`): ConversationKernel registers as an additional observer. Single source of truth for state.

**The same physics that governs coding agent loops now informs human conversation — but the voice pipeline keeps its existing structure.**

---

## 4. System Architecture (Single-Owner Pattern)

### 4.1 Process Topology

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
│  │   - NOW ACTUALLY INITIALIZED in MemoryInterface.__init__ (v2 fix)  │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│         │                                                                  │
│  ┌──────┴──────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │ Agent       │  │ Mycelium    │  │ Conversation│  │ Coupled     │      │
│  │ Kernel      │  │ Memory      │  │ Kernel      │  │ Registry    │      │
│  │ (DER Loop,  │  │ (scorer,    │  │ (voice-     │  │ (multi-     │      │
│  │  trajectory)│  │  resonance) │  │  first)     │  │  session)   │      │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘      │
│                                                                            │
│  New FastAPI endpoints: /api/caducean/state, /api/caducean/direction,     │
│                         /api/caducean/params                               │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Why Single-Owner?

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **Python owns DLL, Tauri proxies** | Single load, no duplication, Python fallback mature, simple CORS | Rust is dumb proxy | ✅ Chosen |
| Rust owns DLL, Python calls Rust | Rust-typed FFI | Duplicate loading risk, complex pyo3/pylib, version mismatch | ❌ |
| Both load DLL independently | Independent failures | Memory spikes, state divergence, race conditions | ❌ |
| Shared memory between processes | Fastest | Locking nightmare, brittle | ❌ |

### 4.3 Communication Protocols

| Direction | Protocol | Latency | Use case |
|-----------|----------|---------|----------|
| Frontend → Tauri | `invoke()` (Tauri IPC) | <1ms | Command call |
| Tauri → Python | HTTP GET/POST to `:8000/api/caducean/*` | ~5ms | State fetch |
| Python → iris_core.dll | ctypes (in-process) | <0.1ms | Engine call |
| Frontend → Python (existing) | WebSocket | <5ms | Streaming responses |

**Future:** Direct WS broadcast from Python → Frontend for `DirectionSignal` updates (skip Tauri proxy), reducing latency to ~2ms. Deferred to v3.

### 4.4 Why Polling for v1?

- 500ms interval = 2 req/s, trivial backend load
- Easy to debug (curl `/api/caducean/state` to inspect)
- No reconnection logic needed
- WebSocket broadcast becomes necessary only if voice latency becomes a felt problem

---

## 5. Data Flow Examples

### 5.1 Single-Step Update (DER Cycle)

```
1. Agent Kernel completes a step
2. → ffi_caducean_update(session_id, action=0, balance=0.85)
   → C++ updates x++, u += s*cos(xi), xi = fmod(xi + balance*s*c_eff, 2π)
   → Persists to in-memory state (no DB write)
3. → ffi_calculate_eml(session_id)
   → O(1) formula from current x, y
   → returns EML, balance
4. → INSERT INTO caducean_trajectories (...)  (fire-and-forget, try/except)
5. → ffi_caducean_recommend(session_id)
   → Adaptive safety net check (Q, phase_accel)
   → Returns 0/1/2/3
6. If 3 (TOPO_VIOLATION):
   → mycelium_record_anomaly(session_id, "update_velocity_anomaly")
   → raise TopologyViolationException
7. Next DER cycle reads ffi_caducean_get_direction_signal()
```

### 5.2 Mycelium Maintenance with Caducean Modulation

```
1. MemoryInterface triggers run_maintenance() every 5 tasks
2. → EdgeScorer.apply_decay()
   → Reads latest u for session from caducean_trajectories
   → Sets decay_multiplier = 0.5 (u>0) | 1.0 (u≈0) | 1.8 (u<0)
   → Loops edges, applies decay * multiplier, prunes below threshold
3. → MapManager.run_condense()  (unchanged)
4. → MapManager.run_expand()    (unchanged)
5. → LandmarkIndex.apply_landmark_decay()  (unchanged)
6. → ProfileRenderer.render_dirty_sections()  (unchanged)
7. → TopologyLayer.run_topology_maintenance()  (unchanged)
```

### 5.3 Voice Turn-Taking (consolidated with existing pipeline)

```
1. User says wake word
   → Porcupine detects → AudioEngine → VoiceCommandHandler.start_recording()
   → (existing) State transitions to RECORDING
   → (NEW) ConversationKernel._on_voice_state callback fires
   → ffi_caducean_update(session_id, action=1, balance)  # COMPRESS
   → Orb animates "listening" (existing WS broadcast)

2. User speaks, then stops
   → VAD detects silence
   → Whisper transcription runs
   → _on_voice_result fires → iris_gateway._process_voice_transcription()
   → process_text_message(from_voice=True) → voice_first mode → 1-step agent response
   → (NEW) ConversationKernel sees RECORDING→IDLE transition
   → ffi_caducean_update(session_id, action=0, balance)  # EXPAND

3. Agent response streams through _speak_response()
   → (MODIFIED) chunk size = conversation_kernel.get_tts_chunk_size()
   → (MODIFIED) per-chunk check: should_halt_on_violation()?
   → TTSManager.synthesize_stream() plays audio
   → Orb animates "speaking" (existing WS broadcast)

4. User barges in mid-speech
   → VAD detects voice → audio_level > 0.5
   → (existing) AudioEngine triggers interrupt path
   → (NEW) ConversationKernel._on_audio_level callback fires
   → ffi_caducean_set_params(session_id, a, b, s)  # force target_u = -1
   → TTS halts at next chunk boundary (existing interrupt path)
```

---

## 6. Why This Upgrade Improves the Backend

| Improvement | Mechanism | Validated |
|-------------|-----------|-----------|
| **Elimination of Database Latency** | O(1) EML formula removes SQLite from hot path | Gate 2 — sub-millisecond loop steps |
| **Zero False Alarm Safety Net** | Phase acceleration distinguishes drift from limit cycle | Gate 2 C4 — 0% FP rate (was 58%) |
| **Emergent System Coherence** | CoupledRegistry shares physics state across kernels | Gate 2 C1 — nucleus/barrier differentiation observed |
| **Adaptive Self-Tuning** | TrajectoryController adjusts (a, b, s) from real data | Trained on Gate 4 LLM data |
| **Voice Becomes First-Class** | ConversationKernel makes phase govern turn-taking | New — enabled by v2 |
| **Single Source of Truth** | Engine init bug fixed — C++ is no longer dead code | Audit — `ffi_init_engine` now called in `MemoryInterface.__init__` |

---

## 7. Out of Scope (v3 candidates)

- WebSocket broadcast for real-time `DirectionSignal` (skip Tauri proxy)
- Multi-kernel shared Σ state across processes
- Cross-project landmark bridge with Caducean state
- ConvStreamKernel for TTS chunking driven by `force_magnitude`
- PiN auto-anchor triggered by Caducean state (e.g., "preserve this decision — we're in compress mode")

---

## 8. Testing Strategy — Four Layers

Caducean v2 introduces the **mitochondrial governor** — the part of the system that quietly controls memory behavior across long sessions. This is exactly the kind of change where "all tests pass" can mask a regression. The testing strategy is layered to catch failures at the right granularity:

| Layer | What it proves | Where it runs | Speed |
|-------|----------------|---------------|-------|
| **Unit** | Code runs, fields exist, types correct | Every commit | <1s each |
| **Integration** | Components connect, data flows across boundaries | Every PR | 1–10s each |
| **Contract** | FFI struct shape, HTTP API schema, return codes | Every commit (frozen JSON) | <1s each |
| **Behavioral** | Physics actually behaves correctly over 1000+ steps | Nightly | 10s–5min each |
| **Full E2E** | Tauri + Python + C++ + Mycelium + Voice all wire up | Pre-release + manual | Minutes |

**Why behavioral tests are non-negotiable for v2:**

The most dangerous failure mode is one where every code path is "correct" but the physics contract is broken. Example: a Mycelium decay multiplier that always returns 1.0 regardless of `u`. The unit test for `decay_multiplier` would pass. The integration test for "edge score after maintenance" would pass (modulo the multiplier being 1.0). But the *behavioral* assertion "explore mode retains more edges than compress mode over 1000 cycles" would fail loudly.

Behavioral tests assert on the *statistical outcome of the physics* — they are the only way to prove v2 actually does what v2 claims to do.

**Why contract tests are non-negotiable for FFI:**

`ctypes.Structure` silently corrupts memory when field order drifts. A change to the C++ struct layout without a matching Python update produces garbage values, not crashes. The contract test freezes the field order as an explicit manifest — any drift fails CI before the corruption ever reaches production.

**Why full-stack E2E catches what unit tests miss:**

A unit test confirms `useCaducean` calls `invoke('caducean_get_state', { sessionId })`. A full-stack E2E test confirms the chain `JS invoke → Rust Tauri command → HTTP GET /api/caducean/state?session_id=X → Python FastAPI → ctypes → C++ → response → JSON serialize → HTTP response → Rust deserializes → invoke returns → React setState → DOM update` all work. Every layer is testable in isolation; only the chain is testable as a system.

See `docs/plans/Cadv2plan.md` Component 9 for the full test list and the orchestration script (`backend/tests/e2e/run_e2e.sh`).

---

## 8. References

- `docs/plans/Cadv2plan.md` — implementation plan with file-by-file change list
- `docs/CADUCEAN_TECHNICAL_OVERVIEW.md` — full mathematical derivation
- `docs/ACCESSIBLE_REPORT_UPDATED.md` — plain-English summary with Gate 1–5 results
- `bootstrap/GOALS.md` Domain 19 — roadmap entry for this work

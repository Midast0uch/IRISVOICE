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

The voice pipeline is the primary interface per CLAUDE.md. v2 makes the kernel **phase-driven** rather than heuristic:

| Caducean state | Voice Kernel action |
|----------------|---------------------|
| `ξ ∈ [0, π)` | **AGENT_SPEAK** — synthesize and stream TTS |
| `ξ ∈ [π, 2π)` | **AGENT_LISTEN** — VAD active, expect user input |
| `force_magnitude > 0.5` | **Large TTS chunks** (confident, uninterrupted) |
| `force_magnitude < 0.1` | **Small TTS chunks** (easily interruptible) |
| User voice during AGENT_SPEAK | **Interrupt** — record anomaly, force `target_u = -1` |
| `recommendation == 3` | **Halt TTS**, surface violation indicator |

The same physics that governs coding agent loops now governs human conversation. The voice is no longer a separate domain with its own state machine.

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

### 5.3 Voice Turn-Taking

```
1. User says wake word → STT → process_text_message()
2. ConversationKernel created (or resumed) for session
3. Backend polls ffi_caducean_get_direction_signal() every 100ms (internal)
4. Current state: ξ=0.5π, u=0.3, target_u=+1
   → AGENT_SPEAK mode
   → force_magnitude=0.4 → TTS chunk=120 tokens
   → Start synthesizing response
5. User starts speaking mid-response
   → VAD detects voice
   → ConversationKernel sends action=1 (COMPRESS) to Caducean
   → Caducean state updates: u decreases, ξ advances into [π, 2π)
   → Next poll: target_u=-1, AGENT_LISTEN mode
   → TTS halted at chunk boundary
6. User finishes sentence
   → ConversationKernel sends action=0 (EXPAND) to Caducean
   → Phase advances back to [0, π) on next cycle
   → AGENT_SPEAK resumes
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

## 8. References

- `docs/plans/Cadv2plan.md` — implementation plan with file-by-file change list
- `docs/CADUCEAN_TECHNICAL_OVERVIEW.md` — full mathematical derivation
- `docs/ACCESSIBLE_REPORT_UPDATED.md` — plain-English summary with Gate 1–5 results
- `bootstrap/GOALS.md` Domain 19 — roadmap entry for this work

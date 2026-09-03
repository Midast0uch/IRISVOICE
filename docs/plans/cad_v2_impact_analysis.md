# Caducean v2 — Impact Analysis on Tools, Skills, MCP Servers

> **Date:** 2026-06-12
> **Branch:** `feat/caducean-v2-mitochondria-mycelium`
> **Goal:** Identify every consumer of Caducean state, classify impact, and decide what gets touched in v2 vs. what is intentionally NOT touched.

---

## 1. Inventory: Where Does Caducean State Flow Today?

A grep across `backend/` shows Caducean is referenced in **14 Python files**, all in the agent layer:

```
backend/agent/agent_kernel.py              ← the governor
backend/agent/auto_research.py             ← reads state for skill variant prediction
backend/agent/caducean_trajectory.py       ← the in-memory recorder
backend/agent/der_loop.py                  ← reads ξ in queue selection
backend/agent/skill_simulator.py           ← reads eml, x, y as features
backend/agent/trajectory_controller.py     ← tunes (a, b, s) based on history
backend/benchmarks/live_benchmark.py       ← reads state for measurement
backend/gateway/iris_ffi.py                ← the FFI bridge (C++ + Python fallback)
```

**Caducean is NOT referenced in:**
- `backend/agent/tool_bridge.py` (no Caducean awareness)
- `backend/integrations/mcp_bridge.py` (no Caducean awareness)
- `backend/security/mcp_security.py` (no Caducean awareness)
- `backend/agent/skills/` (no Caducean awareness)
- `backend/audio/` (no Caducean awareness, but v2 will add ConversationKernel hook)
- `backend/memory/interface.py` (will add ffi_init_engine call in Phase 0)

**Conclusion:** Caducean v2 lives **entirely within the agent layer**. Tools, skills, and MCP servers are **not coupled to it** today and should not become coupled in v2.

---

## 2. Impact Classification: What v2 Changes vs. What It Doesn't

### 2.1 Caducean v2 INTERNAL changes (Component 1, 2 — C++ + Python FFI)

| File | Change | Risk |
|------|--------|------|
| `src-tauri/src/iris_core/caducean.h` | Add `l, m, xi_prev1, xi_prev2, c_eff` to SessionState | Low — additive |
| `src-tauri/src/iris_core/caducean.cpp` | Implement `c_eff`, phase history, adaptive safety net, `get_direction_signal()`, `set_params()` | Medium — physics change, but signature compatible |
| `src-tauri/src/iris_core/iris_core.h` | Declare `DirectionSignal` struct + 3 new FFI exports | Low — additive |
| `src-tauri/src/iris_core/iris_core.cpp` | O(1) EML formula; 3 new FFI wrappers | Medium — EML formula change validated (Gate 2 result) |
| `backend/gateway/iris_ffi.py` | Add `IrisDirectionSignal` ctypes struct; 3 new FFI bindings; update `_PythonCaduceanFallbackState` to return mock | Low — additive + fallback update |

**Consumers of these are NOT affected**, because the existing functions (`ffi_caducean_update`, `ffi_caducean_recommend`, `ffi_caducean_get_xi`, `ffi_calculate_eml`) keep their signatures. New functions are additive.

---

### 2.2 Caducean v2 → AGENT KERNEL changes (Component 4)

| File | Change | Risk | Reason |
|------|--------|------|--------|
| `backend/agent/der_loop.py` | In `next_ready()`: fetch `DirectionSignal`, restrict queue on `target_u=-1`; raise on `recommendation=3` | Medium | The DER loop's queue logic depends on the engine state — this is the core use case |
| `backend/agent/agent_kernel.py` | Compute `balance = clamp(EML/2.34, 0.1, 3.0)`; handle `TOPO_VIOLATION`; persist trajectory row | Medium | v2 needs trajectory persistence; existing update is unchanged otherwise |
| `backend/agent/trajectory_controller.py` | Tune `a, b, s` based on violation count | Low | v2 adds parameter learning, doesn't break existing behavior |
| `backend/agent/coupled_registry.py` (NEW) | Multi-session coupling singleton | Low | Pure addition, no existing code modified |

**Why these changes are required:** The agent kernel is where Caducean **governs** the loop. v2 makes the governor's output explicit (DirectionSignal) instead of implicit (MAINTAIN hardcoded). The trajectory recorder already exists (`caducean_trajectory.py`) — v2 just adds a column (recommendation).

---

### 2.3 Caducean v2 → MYCELIUM changes (Component 3)

| File | Change | Risk |
|------|--------|------|
| `backend/memory/interface.py` | `ffi_init_engine()` call in `__init__` (Phase 0); `mycelium_record_anomaly()` method | Low — fix bug, add method |
| `backend/memory/mycelium/interface.py` | `record_anomaly()` delegate; `get_latest_u()` reader | Low — additive |
| `backend/memory/mycelium/scorer.py` | Read latest `u` in `apply_decay()`; set multiplier 0.5/1.0/1.8 | Low — uses `IF u` not `MUST u`; reads once per pass |
| `backend/memory/mycelium/resonance.py` | Read latest `u` in `augment_retrieval()`; modulate multiplier by 0.5/1.8 | Low — same pattern |
| `backend/migrations/003_caducean_trajectories.sql` (NEW) | New table for trajectory rows | Low — pure addition |

**Why these changes are required:** Mycelium is the **memory layer** that Caducean v2 governs. Without these, the "mitochondria" has no organ to power. But the changes are **read-once-at-pass-start**, not per-edge — minimal hot-path impact.

---

### 2.4 Caducean v2 → SKILLS / TOOLS / MCP — **NOT TOUCHED**

This is the critical insight: **skills, tools, and MCP servers are decoupled from Caducean today, and v2 keeps them decoupled.**

| Layer | Current Caducean awareness | v2 plan |
|-------|---------------------------|---------|
| `tool_bridge.py` | None (no `caducean` in grep) | None — unchanged |
| `integrations/mcp_bridge.py` | None | None — unchanged |
| `security/mcp_security.py` | None | None — unchanged |
| `agent/skills/` (SkillCreator) | None | None — unchanged |
| `agent/auto_research.py` | **Yes** — reads `caducean_state` dict for skill variant prediction | **Unchanged** — still reads same dict, which now has live state instead of safe defaults |
| `agent/skill_simulator.py` | **Yes** — reads `eml, x, y` as ML features | **Unchanged** — still reads same dict |

**Why no changes needed:** `auto_research.py` and `skill_simulator.py` already consume a `caducean_state: Dict[str, float]` with safe defaults (`eml=1.0, x=0.5, y=0.5`). When v2 makes the engine actually initialize, these dicts get **real values** instead of safe defaults — a free upgrade with no code change.

The current safe-default behavior is:
```python
# backend/agent/auto_research.py line 331:
eml = self._get_caducean_state().get("eml", 1.0)
```
When `ffi_init_engine()` is called, `_get_caducean_state()` returns real values. The caller doesn't care.

**This is exactly the architectural property the bias-free DirectionSignal enables: Caducean is a pure physics signal, callers (skills, tools, research) consume it without modification.**

---

### 2.5 Caducean v2 → VOICE PIPELINE (Component 5) — THIN WRAPPER

| File | Change | Risk |
|------|--------|------|
| `backend/agent/conversation_kernel.py` (NEW) | Thin wrapper — registers as observer on existing callbacks | Low |
| `backend/iris_gateway.py` | 3 minimal touches: instantiate kernel in `set_voice_handler()`, replace 2 hardcoded constants in `_speak_response()`, add 1-line halt check | Low |
| `backend/main.py` | 1 line: `iris_gateway.set_caducean_session(session_id)` in lifespan | Low |
| `backend/audio/*` | **None** — `VoiceCommandHandler`, `AudioPipeline`, `TTSManager` are reused as-is | Zero |

---

### 2.6 Caducean v2 → FRONTEND / TAURI (Components 6, 7, 8)

| File | Change | Risk |
|------|--------|------|
| `src-tauri/src/commands/caducean.rs` (NEW) | 3 Tauri commands proxying to FastAPI | Low |
| `src-tauri/src/main.rs` | Register 3 commands in `invoke_handler` | Low |
| `backend/main.py` | 3 FastAPI endpoints: `/api/caducean/state`, `/direction`, `/params` | Low |
| `app/hooks/useCaducean.ts` (NEW) | React hook with 500ms polling | Low |
| `app/components/VoiceInterface.tsx` | Consume hook; map state to chunk size | Low |
| `app/components/CaduceanDebugPanel.tsx` (NEW) | Dev-only debug panel | Low |

**Why these don't affect tools/skills/MCP:** Frontend hook reads `/api/caducean/*` endpoints. Tauri commands are new. FastAPI endpoints are new. None of these touch `tool_bridge.py`, `mcp_bridge.py`, or `skills/`.

---

## 3. Failure Mode Analysis: What If a v2 Change Breaks a Consumer?

For each consumer, we ask: "If v2 introduces a bug, what's the worst that happens?"

| Consumer | What it reads | If v2 returns bad value | Mitigation |
|----------|---------------|--------------------------|------------|
| `agent_kernel.py` | `ffi_caducean_update` return code | DER loop diverges | v2 keeps same signature, same return codes; behavioral tests assert invariant |
| `der_loop.py` | `ffi_caducean_get_xi`, `recommend` | Queue restricted incorrectly | Contract tests assert `recommend` only returns {0,1,2,3}; v2 adds `3` (TOPO_VIOLATION) which is also a contract |
| `skill_simulator.py` | `eml, x, y` dict | ML predictions degrade | Reads with `dict.get("eml", 1.0)` — falls back to safe default if missing |
| `auto_research.py` | `caducean_state` dict | Variant scoring degrades | Same — safe defaults |
| `caducean_trajectory.py` | All updates, stores history | Trajectory table missing rows | v2 wraps in try/except — fail-soft, log warning |
| Mycelium `scorer.py` | `get_latest_u()` | Decay multiplier always 1.0 | v2 reads once at start of pass; if missing, uses 1.0 (current behavior) |
| Mycelium `resonance.py` | `get_latest_u()` | Resonance unchanged | Same — safe default |
| `tool_bridge.py` | **Does not read Caducean** | **No effect** | Unchanged |
| `mcp_bridge.py` | **Does not read Caducean** | **No effect** | Unchanged |
| `mcp_security.py` | **Does not read Caducean** | **No effect** | Unchanged |
| `skills/SkillCreator` | **Does not read Caducean** | **No effect** | Unchanged |

**The architectural property:** Caducean v2 is an **upstream producer**, not a **downstream consumer** of any other system. It only **adds** behavior to existing consumers that already opted in (`agent_kernel`, `auto_research`, `skill_simulator`). It cannot break systems that don't read it.

---

## 4. What Is INTENTIONALLY NOT TOUCHED in v2

To avoid overcoding, the following are **explicit non-goals** for v2:

1. **No Caducean awareness in `tool_bridge.py`** — Tools don't need it. The DER loop already mediates between the engine and tool calls.

2. **No Caducean awareness in MCP servers** — MCP servers are stateless request/response. They don't need phase awareness.

3. **No Caducean awareness in `mcp_security.py`** — Security is about allow/deny, not phase.

4. **No Caducean awareness in `SkillCreator`** — Skill creation is an atomic operation; phase doesn't change the skill content.

5. **No Caducean awareness in the audio pipeline directly** — The `ConversationKernel` is the only audio-side consumer, and it wraps the existing pipeline.

6. **No phase-driven TTS engine selection** — TTS engine priority (F5-TTS → Piper → pyttsx3) is hardcoded and works well. Caducean only modulates chunk size, not engine choice.

7. **No Caducean awareness in benchmarks** — `live_benchmark.py` reads state, doesn't need to know about v2 internals.

---

## 5. The Phase 0 Fix: What It Touches (and What It Doesn't)

**Phase 0 — Critical fix for engine init bug (Component 0):**

| File | Change | Lines | Lines of Effect |
|------|--------|-------|-----------------|
| `backend/memory/interface.py` | Add `ffi_init_engine()` call in `__init__` | +8 | Zero effect on other files |

**That's it.** Phase 0 is **one file, eight lines**.

The existing `_PythonCaduceanFallbackState` and the ctypes lazy-load in `iris_ffi.py` already handle the "DLL missing" case — so the fix is safe even if the DLL is absent.

**What Phase 0 does NOT do:**
- Does not change the engine's physics
- Does not change the FFI signatures
- Does not add new functions
- Does not modify any tests
- Does not touch tools, skills, or MCP servers
- Does not require recompiling C++

**What Phase 0 DOES do:**
- Makes `ffi_init_engine()` actually be called
- Makes the C++ engine start running (or the Python fallback, transparently)
- Means existing consumers (`agent_kernel`, `auto_research`, `skill_simulator`) start getting **real values** instead of safe defaults
- Is fully reversible: removing the call restores stub behavior

---

## 6. Summary: The "Don't Overcode" Rule

The v2 plan is deliberately minimal in scope. Here's the change count per file:

| Change Count | Files | Files |
|--------------|-------|-------|
| **NOT TOUCHED** | 9 | `tool_bridge.py`, `mcp_bridge.py`, `mcp_security.py`, `skills/*`, `audio/*` (5) |
| **TOUCHED in v2** | 12 | `MemoryInterface`, Mycelium files (4), agent files (4), Tauri (3), frontend (3) |
| **NEW in v2** | 6 | `coupled_registry.py`, `conversation_kernel.py`, `003_caducean_trajectories.sql`, `caducean.rs`, `useCaducean.ts`, `CaduceanDebugPanel.tsx` |

**Tools, skills, MCP servers: ZERO changes in v2.**

The architectural property that makes this possible: **Caducean is a pure signal, not a side-effecting orchestrator**. When v2 makes it real, every consumer that already opted in gets better data; every system that didn't opt in stays unaffected.

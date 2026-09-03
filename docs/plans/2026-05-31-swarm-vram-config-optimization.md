# Swarm + VRAM + Config Optimization Plan (FINAL)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a clean swarm mode that doesn't touch the working API provider setup. Director (brain, usually API) + Workers (local GGUF executors). Config saves never load models — explicit Load/Start buttons only. VRAM-aware, with fallbacks and warnings.

**Architecture:** Two new wheel-view cards ("Local Model" + "Swarm Setup") under the Agent category. SidePanel configures + saves. Models stay as a dashboard sub-app accessed via BrowseModels button. Swarm awareness lives in `agent_kernel.py` for DER+PAC-MAN+Caducean.

**Tech Stack:** Python 3.11+, `llama-server.exe`, `pynvml` (optional), `subprocess`, `asyncio`, React, Framer Motion

---

## 1. Final Card Layout (4 wheel-view cards, all under "Agent")

| # | Card ID | Label | Confirm does | Action buttons | Source |
|---|---------|-------|-------------|----------------|--------|
| 1 | `model_selection` | Model Selection | Saves config only | — | Keep, modify |
| 2 | `local_model` | Local Model | Saves config only | [Load Model] [Unload] [Browse & Manage Models] | New |
| 3 | `swarm_setup` | Swarm Setup | Saves config only | [Start Swarm] [Stop Swarm] [Browse & Manage Models] | New |
| 4 | `inference_mode` | Inference Mode | Saves config only | — | Simplify |

---

## 2. Card 1: Model Selection (modified)

**Changes from current:**
- Remove `local` from provider dropdown (LM Studio stays)
- Keep `lmstudio` option alongside API providers
- `tool_model` dropdown = API provider models + loaded local GGUFs (from Card 2)
- If user selects a local GGUF in `tool_model` but it's not loaded → inline warning: "⚠ This model is not loaded. Load it in the Local Model card."
- `use_same_model` toggle still works for API providers

**Provider list (final):**
```
['opencodego', 'cerebras', 'chutes', 'cohere', 'deepseek', 'anthropic', 'lmstudio']
```

**tool_model dropdown grouping (backend returns structured list):**
```
── Provider Models ──
gpt-4o
gpt-4o-mini
── Loaded Local Models ──
Bonsai-8B-Q3_K_M.gguf ✓
Bonsai-8B-1bit.gguf ✓
```

---

## 3. Card 2: Local Model (new)

```
┌──────────────────────────────────────┐
│  LOCAL MODEL                          │
│                                        │
│  Use same model for tools: [ON]       │  ← toggle, default ON
│                                        │
│  Reasoning Model:                      │
│  [dropdown: available GGUFs]           │
│                                        │
│  Tool Model: (when toggle OFF)         │
│  [dropdown: available GGUFs]           │
│                                        │
│  Profile: [eco | balanced | perf]      │
│  Context: [slider  1024 ───── 65536]   │
│  GPU Layers: [slider   -1 ─────── 128] │
│                                        │
│  ⚡ Status: ○ Idle                      │
│       (or: ● Loaded - Bonsai-8B.gguf) │
│                                        │
│  [Load Model]  [Unload]                │
│  [Browse & Manage Models]              │
└──────────────────────────────────────┘
```

**Behavior:**
- **Confirm** saves config only (model path, profile, ctx, gpu_layers)
- **Load Model** — launches in-process Llama with saved config
- **Unload** — kills the in-process Llama
- **Browse & Manage Models** — fires `open_models_screen` action, transitions dashboard to ModelBrowserPanel
- **Models directory not configured**: show message "Set a models directory in Settings → Storage to scan for local GGUFs"
- **Auto-unload on config change**: If a model is loaded and user changes the dropdown + confirms, the old model unloads automatically and the new config is saved. User still needs to click Load to load the new model. Warning shown: "Config changed — model was unloaded. Click Load to apply new model."

---

## 4. Card 3: Swarm Setup (new)

```
┌──────────────────────────────────────┐
│  SWARM SETUP                          │
│                                        │
│  ── DIRECTOR (reasoning brain) ──     │
│  Source: [● Use API Provider (Card 1) │
│           ○ Local GGUF]               │
│  If Local:  Model: [dropdown GGUFs]   │
│             GPU Layers: [slider]       │
│                                        │
│  ── WORKERS (executors) ────────────  │
│  Model: [dropdown of available GGUFs] │
│  Workers: [2]  (max 3 based on VRAM)  │
│  Context: [2048] [slider 1024-4096]  │
│                                        │
│  ⚡ Status: ○ Inactive                  │
│       (or: ● 2/2 workers running)     │
│  ○ VRAM Warning                       │
│                                        │
│  [Save Config Only]  [Start Swarm]     │
│  [Stop Swarm]  [Browse & Manage Models]│
└──────────────────────────────────────┘
```

**VRAM contention warning:** If `local_model` card has a loaded model AND swarm workers are active, show: "⚠ Local model + swarm workers may exceed 8 GB VRAM. Unload the local model before starting swarm for best performance."

**Behavior:**
- **Save Config Only** — saves config. Never launches anything.
- **Start Swarm** — detects VRAM, launches llama-server workers
- **Stop Swarm** — kills all worker processes
- **Browse & Manage Models** — fires `open_models_screen`

---

## 5. Card 4: Inference Mode (simplified)

**Keep:** `agent_thinking_style`, `max_response_length`, `reasoning_effort`, `tool_mode`
**Remove:** `swarm_enabled`, `swarm_mode`, `worker_context`, `models_directory`, `iris_local_model_path`, `profile`, `ctx`, `gpu_layers`

All model config moved to Cards 1-3. This card is purely about agent behavior.

---

## 6. Dashboard Changes

### 6a. Action bar (SYSTEM IDLE area)

Current:
```
[WS LIVE] [LFM-2-8B READY] [SYSTEM IDLE]                    [APPLY]
```

Changed to:
```
[WS LIVE] [Model: {loaded_model_name or "None"}] [SYSTEM IDLE]   [BrowseModels] [APPLY]
```

- **BrowseModels** button — fires `open_models_screen` → transitions to ModelBrowserPanel
- Loaded model name is dynamic from backend state (not hardcoded LFM)
- When nothing loaded: shows "Model: None" in dimmed text

### 6b. Sidebar navigation — redesigned to Pill Tabs (Style A)

**Position:** Stays on the left. No position change.

**Layout change:**
| Dimension | Before | After |
|-----------|--------|-------|
| Expanded width | 150px | **120px** (−30px) |
| Pill height | ~40px | **34px** |
| Gap between pills | ~20px | **12px** |
| Collapsed width | 56px | 56px (unchanged) |
| Border-radius | — | **9999px** (full pill) |
| Font size | 11px | 10px |
| Active indicator | 2px left glow bar | Glow fill inside pill |

**Active pill style (Style A):**
```css
/* State: active */
background-color: glowColor + '18';
color: white;
border: 1px solid glowColor + '25';
box-shadow: 0 0 12px glowColor + '15';
```

**Inactive pill style:**
```css
/* State: inactive */
background-color: transparent;
color: rgba(255,255,255,0.35);
border: 1px solid transparent;
```

**Collapsed state:** Icons only. Active pill shows a subtle pulse glow on the icon. Same 56px width as before.

### 6c. ModelBrowserPanel sub-app

Stays exactly where it is. Accessed via:
- BrowseModels button in action bar
- Browse & Manage Models button in SidePanel cards
- Models tab in sidebar

---

## 7. Cross-Card Behaviors

**LM Studio and Local Model Card are mutually exclusive:**
- LM Studio = external app manages the model. IRIS just connects to its endpoint.
- Local Model card = IRIS loads the GGUF in-process itself.
- You use one or the other. When MM Studio is selected, loaded local models do NOT appear in the tool_model dropdown.
- Loaded local models appear in Model Selection's tool_model ONLY when the provider is a cloud API (opencodego, cerebras, etc.)

| Situation | Behavior |
|-----------|----------|
| **Loaded local GGUF appears in Model Selection's tool_model** | Backend broadcasts `loaded_local_models` event. Card 1's tool_model dropdown adds these with ✓ marker (only when provider is a cloud API, not LM Studio) |
| **User picks unloaded local GGUF as tool_model** | Inline warning: "⚠ This model is not loaded. Load it in the Local Model card." |
| **User confirms Local Model card with different model while one is loaded** | Auto-unload old model. Warning: "Config changed — {old_model} unloaded. Click Load to apply {new_model}." |
| **User unloads a model that was selected as tool_model** | Backend detects, falls back to reasoning model for tools. Sends warning event to UI. |
| **Local model + Swarm both active** | VRAM contention warning in both cards. No auto-disable (user decides). |
| **LM Studio selected as provider** | Local Model card shows: "LM Studio is active. Use LM Studio for local models, or switch to a cloud API provider to use IRIS-loaded local models for tools." |
| **Cold start — no models directory set** | Card displays: "Set a models directory in Settings → Storage to scan for local GGUFs" |
| **Cold start — provider model list loading** | Dropdown shows "Loading..." until provider returns list |
| **Swarm active + local model card loaded** | VRAM warning shown in both cards. |

---

## 8. All Hard Discoveries & Fixes — Confirm All

| # | Discovery | Fix | Approved? |
|---|-----------|-----|-----------|
| **1** | `routing.mode` never SWARM_* | `_resolve_routing_mode()` called on swarm config save | ✅ |
| **2** | `inference_router.py` dead code | Swarm lives in agent_kernel directly. Router can be removed later. | ✅ |
| **3** | `_call_swarm()` is a stub | Agent kernel launches SwarmInferenceManager directly | ✅ |
| **4** | SwarmCoordinator disconnected | `create_collaboration()` → `find_joinable()` → `complete_task()` in DER loop | ✅ |
| **5** | `_handle_control_codes()` never called | Called at end of `_respond_direct()` + each DER iteration | ✅ |
| **6** | VRAM budget 8.0 GB | Dynamic `pynvml` → `psutil` → 5.44 GB fallback | ✅ |
| **7** | Hardcoded model paths | User picks explicitly from GGUF dropdown | ✅ |
| **8** | stderr=PIPE deadlock | File logging + health polling | ✅ |
| **9** | Agent kernel has own infer(), not swarm-aware | `infer()` gets swarm paths for director/worker dispatch | ✅ |

---

## 9. Additional Fixes

| Fix | Detail |
|-----|--------|
| **LFM cleanup (14 locations)** | All hardcoded `lfm2-8b` / `lfm2.5-1.2b-instruct` references in agent_kernel.py replaced with dynamic model names from config/loaded state |
| **Dynamic system prompts** | `_build_system_prompt()` reads actual reasoning_model / tool_model names instead of hardcoded LFM |
| **Dynamic aliases** | Model alias map (lines 4613-4652) resolved from loaded models, not hardcoded to LFM |
| **Loaded model health in action bar** | Bottom bar shows actual loaded model name, not hardcoded `LFM-2-8B READY` |
| **VRAM detection** | `_detect_usable_vram()` via pynvml → psutil → 5.44 GB fallback |
| **Worker count calculation** | `_calc_max_workers()` based on actual file size + ctx + gpu_layers |
| **stderr fix** | File logging + health polling instead of PIPE + sleep(2) |
| **SwarmCoordinator wired** | Lifecycle methods called from DER loop |
| **ContextControlHandler wired** | `_handle_control_codes()` called in response pipeline |
| **Notifications** | `swarm_status` + `model_load_progress` → dashboard-wing notifiction system |

---

## 10. Files Changed

### Frontend
| File | Change |
|------|--------|
| `data/cards.ts` | Remove `local` from model_selection provider. Add `local_model` card fields. Add `swarm_setup` card fields. Simplify `inference_mode` card. |
| `data/navigation-constants.ts` | Add `local_model`, `swarm_setup` section mappings. Add card icon entries. |
| `components/wheel-view/SidePanel.tsx` | Handle `open_models_screen` action. Show warning for unloaded local tool model. |
| `components/dashboard/ModelBrowserPanel.tsx` | Add swarm status section. Keep existing model library + load/unload. |
| `components/dark-glass-dashboard.tsx` | Add BrowseModels button in action bar. Dynamic model name display. Handle `open_models_screen` → transitions to models sub-app. |
| `components/dashboard-wing.tsx` | Add swarm status + local model loaded notifications to existing notification system. |

### Backend
| File | Change |
|------|--------|
| `backend/iris_config.py` | Add `SwarmRoleConfig`, `SwarmDirectorConfig`, `SwarmWorkerConfig`. Extend `InferenceConfig`. |
| `backend/iris_gateway.py` | Add `model_selection` provider list filter. Handle `local_model` card confirm. Handle `swarm_setup` card confirm. `_resolve_routing_mode()` helper. `swarm_action` WS handler (start/stop). Loaded models broadcast. Warning for unloaded tool model. |
| `backend/agent/agent_kernel.py` | LFM cleanup (14 locations → dynamic names). Dynamic system prompts. SwarmCoordinator wired into DER. ContextControlHandler wired into response pipeline. `infer()` swarm-aware paths. |
| `backend/agent/swarm_inference_manager.py` | Dynamic VRAM detection. Remove hardcoded model paths. `_calc_max_workers()`. File logging + health polling. |
| `backend/agent/swarm/coordinator.py` | No changes needed (already has lifecycle methods). |
| `backend/agent/swarm/context_control.py` | No changes needed (already has detect_codes). |
| `backend/main.py` | Add `POST /api/swarm/start`, `POST /api/swarm/stop`, `GET /api/swarm/status`. Add `POST /api/models/local/load`, `POST /api/models/local/unload`. |

---

## 11. Execution Order

```
1. SidePanel width 155px → 100px          — visual only
2. Card definitions + navigation constants — cards.ts, navigation-constants.ts
3. Simplify inference_mode card            — remove local + swarm fields
4. Backend config model                     — iris_config.py (SwarmRoleConfig etc.)
5. Backend gateway handlers                 — iris_gateway.py (confirm_card + swarm_action)
6. VRAM detection + worker count            — swarm_inference_manager.py
7. stderr deadlock fix                      — file logging + health polling
8. LFM cleanup (14 locations)               — agent_kernel.py
9. Dynamic system prompts                   — agent_kernel.py _build_system_prompt()
10. Wire SwarmCoordinator + ControlHandler  — agent_kernel.py DER loop
11. Agent kernel swarm-aware infer()        — agent_kernel.py infer()
12. BrowseModels button + action bar        — dark-glass-dashboard.tsx
13. Dashboard notifications                 — dashboard-wing.tsx
14. ModelBrowserPanel enhancements          — swarm status display
15. API endpoints                           — main.py (/api/swarm/*, /api/models/local/*)
16. Unit tests                              — all new code paths
```

---

## 12. Not Touching

- `model_selection` card's API provider flow (user confirmed working)
- Dashboard sidebar position (stays on left)
- ModelBrowserPanel's existing GGUF scanning and metadata display
- WS message types for state sync
- Existing notification infrastructure
- DER loop core logic (only adding hooks, not changing flow)
- PAC-MAN, Caducean core logic (only wiring them to swarm)

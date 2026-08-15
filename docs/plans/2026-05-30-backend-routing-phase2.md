# Session Summary — 2026-05-30: Backend Routing Phase 2 (Extended)

## Mission
Wire `iris_config.json` as single source of truth for model routing (`inference_router.py` + `iris_config.py`) into the inference hot path. Replace silent `try/except` with visible error handling. Then verify end-to-end via the frontend UI.

---

## ✅ Verified: Frontend→Backend Pipeline

**The full pipeline works end-to-end:**
1. Message typed into chat textarea → React state update via `pressSequentially()`
2. Send button click → WebSocket `chat_message` sent to backend
3. Agent kernel receives and processes → routes through configured inference path
4. Response streamed back as `chat_chunk` → appears in chat bubble

**Confirmed working:**
- Frontend ChatView receives and displays responses (both errors and successful replies)
- Backend config loading from `iris_config.json` (routing mode, provider, model path)
- Error propagation: `_respond_direct` → `process_text_message` → `_execute_agent` → UI
- Logger output visible in server stdout

---

## Bugs Found & Fixed (Phase 2 Original)

### Bug 1: `ResponseNotRead` in `_dispatch_api` streaming error path
- **Root cause**: httpx streaming responses don't support `.text` until the body is consumed. The error handler read `_resp.text[:200]` inside the `with _client.stream(...) as _resp:` block, raising `ResponseNotRead`.
- **Fix**: Read the first chunk via `_resp.iter_bytes()` for error detail instead of `.text`.
- **File**: `backend/agent/agent_kernel.py` — `_dispatch_api()` streaming branch (line ~1885)

### Bug 2: Dead logger in `agent_kernel.py`
- **Root cause**: `agent_kernel.py` uses `logging.getLogger(__name__)` → `"backend.agent.agent_kernel"`, whose parent is the root logger. Python's root logger has **no handlers** by default. The structured "irisvoice" logger sets `propagate=False`. Result: every `logger.info/warning/error()` call in agent_kernel.py silently disappears.
- **Fix**: Added root logger configuration (`StreamHandler` + `Formatter`) in `setup_backend_logging()` in `backend/core/logging_config.py`. The handler only attaches if the root logger is bare (no handlers), so it doesn't duplicate with uvicorn.
- **File**: `backend/core/logging_config.py`

### Bug 3: Config `api_base_url` never loaded in SINGLE_API mode
- **Root cause**: `self._api_base_url` defaults to `"https://api.openai.com/v1"` (non-empty). The condition `if not self._api_base_url and config:` was always `False`, so the config's Chutes URL was never applied. Request went to OpenAI with a Chutes API key → 401.
- **Fix**: Changed to always load from config when available: `if config.inference.api_base_url: self._api_base_url = config.inference.api_base_url`
- **File**: `backend/agent/agent_kernel.py` — `_respond_direct()` SINGLE_API block (line ~1728)

### Bug 4: Model name never loaded from config
- **Root cause**: `_selected_reasoning_model` stays `None` for new sessions (no card confirmation sent). When `None`, `_respond_direct` falls back to `"command-a-03-2025"`.
- **Fix**: Added `if config.inference.reasoning_model: self._selected_reasoning_model = config.inference.reasoning_model` in the SINGLE_API block.
- **File**: `backend/agent/agent_kernel.py` — `_respond_direct()` SINGLE_API block

### Bug 5: Silent `try/except` in `process_text_message`
- **Root cause**: `except Exception` caught errors from `_respond_direct`, logged to dead logger, returned user-visible error string. Caller (`_execute_agent`) never knew an error occurred.
- **Fix**: Changed to `raise` after logging. Error now propagates to `_execute_agent`'s structured handler which logs properly and sends visible error to UI.
- **File**: `backend/agent/agent_kernel.py` — `process_text_message()` (line ~2641)

---

## 🔴 Critical Issues & Solutions (Session 3 Discovery)

### Issue 1: React State Not Updated by nativeSetter

**Problem:** Setting `input.value` via JavaScript's `nativeSetter` or `.value =` updates the DOM display but does NOT trigger React's `onChange` handler. The `dark-glass-dashboard.tsx` FieldRow component (line 364) uses `onChange={(e) => setValue(e.target.value)}` which calls `updateField(sectionId, field.id, newValue)` to update `localFieldValues` React state. When APPLY is clicked, `handleApplySettings` reads from `localFieldValues` — so if the value was set via `nativeSetter`, the old value is sent.

**Solution:** Always use `pressSequentially()` for form inputs that will be submitted. This fires real keyboard events that trigger React's `onChange`:

```javascript
// ✅ CORRECT: pressSequentially triggers React onChange
const input = page.locator('input[placeholder="(none — use Browse & Manage Models below)"]');
await input.click({ clickCount: 3 }); // select all
await page.keyboard.press('Delete');    // clear
await input.pressSequentially('C:/path/to/model.gguf', { delay: 5 });

// ❌ WRONG: nativeSetter updates DOM but NOT React state
const nativeSetter = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype, 'value'
).set;
nativeSetter.call(input, 'C:/path/to/model.gguf');
input.dispatchEvent(new Event('input', { bubbles: true }));
// This shows the new value in the UI but React state still has the old value!
```

**Files involved:**
- `components/dark-glass-dashboard.tsx` line 364: `onChange={(e) => setValue(e.target.value)}`
- `components/dark-glass-dashboard.tsx` line ~478: `localFieldValues` state
- `components/dark-glass-dashboard.tsx` line ~669: `handleApplySettings` reads from `localFieldValues`

---

### Issue 2: Multiple llama-cpp-server Processes Spawning

**Problem:** When APPLY is clicked, the frontend sends `confirm_card` for ALL active sections. The backend processes them in order:
1. `model_selection` confirm_card → calls `load_model()` for iris_local (loads in-process model)
2. `inference_mode` confirm_card → if swarm enabled, calls `start_swarm()` which spawns director (8081) + workers (8082)

Both run simultaneously with no coordination. Result: 3+ llama processes consuming CPU/RAM, not GPU.

**Solution:** Add a guard in the `inference_mode` confirm_card handler that checks if a local model was just loaded. If swarm is enabled AND provider is `iris_local`, the swarm should use the already-loaded model rather than spawning additional processes. The fix is in `backend/iris_gateway.py` around line 823:

```python
# In the inference_mode confirm_card handler, BEFORE start_swarm():
if provider == "iris_local" and not swarm_on:
    # SINGLE_LOCAL mode: load_model() was already called by model_selection
    # No additional processes needed
    pass
elif swarm_on:
    # SWARM mode: start_swarm() will spawn subprocesses
    # BUT: if iris_local model is already loaded in-process,
    # unload it first to free VRAM for swarm processes
    mgr = get_local_model_manager()
    if mgr.is_model_loaded():
        await mgr.unload_model()
    await mgr.start_swarm()
```

**Alternative (cleaner):** Move ALL model loading to the `inference_mode` handler. `model_selection` should ONLY save config — never call `configure_openai_compat()` or `load_model()`. Then `inference_mode` decides:
- If `iris_local` + no swarm → load in-process model + configure kernel
- If `iris_local` + swarm → unload in-process model + start swarm + configure kernel for swarm
- If `api`/`lmstudio`/`vps` → just configure kernel endpoint (no engine to start)

**Files involved:**
- `backend/iris_gateway.py` line ~1073: `model_selection` confirm_card handler (iris_local branch)
- `backend/iris_gateway.py` line ~810: `inference_mode` confirm_card handler (swarm branch)
- `backend/agent/swarm_inference_manager.py`: `start_swarm()` and `stop_swarm()`

---

### Issue 3: No Loading Progress Bar in UI

**Problem:** When the user clicks APPLY, there's no visual feedback while the model loads. The `LocalModelManager.load_model()` method has a `progress_cb` parameter that streams progress updates, but the `confirm_card` handler doesn't use it.

**Solution:** The `load_local_model` WebSocket handler (line ~5013) already has a `_progress_cb` that sends `model_load_progress` messages to the frontend. Wire the same pattern into the `confirm_card` handler:

```python
# In the model_selection confirm_card handler, iris_local branch:
async def _progress_cb(pct: float, msg: str):
    await self._safe_send(client_id, json.dumps({
        "type": "model_load_progress",
        "session_id": session_id,
        "percent": pct,
        "message": msg,
    }))

# Then call load_model with progress callback:
await mgr.load_model(
    _model_path,
    profile=_profile,  # from hardware_profile field
    progress_cb=_progress_cb,
)
```

The frontend already handles `model_load_progress` messages in the Models Browser. The Dashboard status bar ("COMMAND-R-PLUS-08-2024 READY") should also update during loading to show progress.

**Files involved:**
- `backend/iris_gateway.py` line ~5013: existing `load_local_model` handler with `_progress_cb`
- `backend/iris_gateway.py` line ~1102: new `load_model()` call in confirm_card (needs `progress_cb` and `profile` params)
- `backend/agent/local_model_manager.py` line 1221: `load_model()` signature with `progress_cb` and `profile` params
- `components/dark-glass-dashboard.tsx`: needs to handle `model_load_progress` WebSocket messages

---

### Issue 4: Hardware Profile Not Passed to load_model()

**Problem:** The `load_model()` call in the confirm_card handler (line 1102) only passes the model path: `await mgr.load_model(_model_path)`. It doesn't pass the `profile` parameter, so the model loads with default settings instead of the user's chosen hardware profile (Balanced, Performance, etc.).

The `HARDWARE_PROFILES` dict in `local_model_manager.py` (line 92) maps profile names to inference settings:

```python
HARDWARE_PROFILES = {
    "eco": {"n_gpu_layers": 0, "n_ctx": 2048, "flash_attn": False, ...},
    "balanced": {"n_gpu_layers": -1, "n_ctx": 16384, "flash_attn": True, ...},
    "performance": {"n_gpu_layers": -1, "n_ctx": 8192, "flash_attn": True, ...},
    "voice_first": {"n_gpu_layers": -1, "n_ctx": 4096, "flash_attn": True, ...},
    "research": {"n_gpu_layers": -1, "n_ctx": 32768, "flash_attn": True, ...},
}
```

**Solution:** Pass the `hardware_profile` field value from the confirm_card to `load_model()`:

```python
# In the model_selection confirm_card handler:
_profile = values.get("hardware_profile", "balanced")  # default to balanced
await mgr.load_model(_model_path, profile=_profile, progress_cb=_progress_cb)
```

**Critical:** The "balanced" profile sets `n_gpu_layers: -1` (auto/full offload). The previous config had `gpu_layers: 0` which forces CPU-only — 5-30× slower. The hardware profile dropdown in the UI must map correctly to these profiles.

**Files involved:**
- `data/cards.ts`: `hardware_profile` field in MODEL SELECTION card (dropdown with eco/balanced/performance/voice_first/research)
- `backend/iris_gateway.py` line 1102: `load_model()` call needs `profile` param
- `backend/agent/local_model_manager.py` line 92: `HARDWARE_PROFILES` dict
- `backend/agent/local_model_manager.py` line 1221: `load_model()` signature with `profile` param

---

## Code Changes Made This Session

### Backend (`backend/iris_gateway.py`):
- Added `await mgr.load_model(_model_path)` call in `model_selection` confirm_card handler for `iris_local` provider
- Added `models_directory` field handling in `inference_mode` confirm_card
- **NOTE:** The `load_model()` call is missing `profile` and `progress_cb` params — see Issue 3 and Issue 4 above for the fix

### Backend (`backend/agent/local_model_manager.py`):
- Added `effective_models_dir` property that checks instance override first, then class default
- Added `set_models_directory()` method for runtime override from config
- Changed `info()` and `scan_models()` to use `self.effective_models_dir` instead of `self.MODELS_DIR`

### Backend (`backend/iris_config.py`):
- Added `models_directory: str = ""` field to `InferenceConfig`

### Frontend (`data/cards.ts`):
- Renamed `iris_local_model_path` label from "Active GGUF Model" to "Selected Model"
- Changed placeholder from "(none — select in Models Browser)" to "(none — use Browse & Manage Models below)"
- Added `models_directory` field to INFERENCE MODE card with placeholder "~/.lmstudio/models"

### What Still Needs Fixing (Next Session)

1. **APPLY must call `load_model()` with progress feedback** — The code was added but the React state wasn't being updated properly via `nativeSetter`. Need to verify the `confirm_card` WebSocket message actually reaches the backend with the correct `iris_local_model_path` value. The `pressSequentially()` approach works for React state, but the APPLY button's `handleApplySettings` function needs to collect the current field values correctly.

2. **Loading progress bar in UI** — `LocalModelManager.load_model()` has a `progress_cb` parameter. The WebSocket should stream load progress events to the frontend so a progress bar can show model loading status. Currently there's no feedback — the user clicks APPLY and sees nothing until the model is ready.

3. **Graceful model loading** — Only ONE llama process should run at a time for SINGLE_LOCAL mode. The `load_model()` method already handles this (calls `unload_model()` first, uses `_load_lock`), but the swarm path bypasses it entirely.

4. **Correct llama-cpp-python server usage** — Per `.iris-worktree/docs/inference-profiles.md`, IRIS should use `python -m llama_cpp.server` on port 8082 with the correct hardware profile settings. The `load_model()` method already builds the correct command via `_build_server_cmd()` and uses the profile system. The issue is ensuring the profile from the UI (Hardware Profile dropdown) is passed through to `load_model()`.

---

## 🔴 Model/Inference Card Conflict (Phase 2 Discovery)

### The Problem
There is a **fundamental architecture conflict** between two UI sections that both try to control the inference engine:

| Section | What it does | Problem |
|---------|-------------|---------|
| **MODEL SELECTION** | Sets provider (api/iris_local/lmstudio/vps), API key/URL, GGUF path, routing mode. Calls `configure_openai_compat()` to wire kernel to in-process model endpoint. | Configures kernel for in-process inference |
| **INFERENCE MODE** | Configures swarm mode, response length, reasoning effort. If swarm enabled: calls `start_swarm()` which launches llama-server subprocesses on ports 8081/8082, then ALSO calls `configure_openai_compat()` overwriting the model_selection endpoint. | Overwrites kernel to use swarm subprocess endpoint |

**When APPLY is clicked**, the frontend sends `confirm_card` for ALL active sections. The backend processes them in order:
1. `model_selection` confirm_card → sets kernel endpoint for in-process model
2. `inference_mode` confirm_card → overwrites kernel endpoint for swarm

These fight over `configure_openai_compat()` and there's no coordination between them.

### Multiple APPLY Clicks → Orphaned Subprocesses
- `start_swarm()` calls `stop_swarm()` first, but `stop_swarm()` only kills processes tracked in `self.director_proc`/`self.workers_proc`
- If a second APPLY arrives before the first's subprocesses have spawned, `stop_swarm()` finds nothing to kill → orphaned `llama-server.exe` instances
- The frontend `isApplying` state guard releases immediately because `sendMessage()` is fire-and-forget (no `await` for backend processing)

### Fixes Applied (Previous Session)

**Frontend** (`components/dark-glass-dashboard.tsx`):
- Added `applyCooldownRef` (useRef) with a 2-second cooldown to prevent rapid re-clicks
- Added `await new Promise(r => setTimeout(r, 2000))` inside `handleApplySettings` to keep the button disabled while backend processes
- The cooldown ref also has a 2-second reset timer after `isApplying` clears

**Backend** (`backend/agent/swarm_inference_manager.py`):
- Added `asyncio.Lock` (`self._swarm_lock`) to `SwarmInferenceManager.__init__`
- Changed `start_swarm()` from sync to `async def start_swarm()`
- Wrapped the entire method body in `async with self._swarm_lock:` — only the first caller proceeds, concurrent calls return `False`

**Backend caller** (`backend/iris_gateway.py`):
- Changed `mgr.start_swarm()` to `await mgr.start_swarm()` at the call site (line 823)

### Proposed Long-Term Fix (Not Yet Implemented)
- `model_selection` should ONLY save config + set routing mode — remove its `configure_openai_compat()` call
- `inference_mode` should be the sole owner of engine startup:
  - If swarm enabled → start subprocess swarm + configure kernel for swarm endpoint
  - If swarm disabled AND provider is `iris_local` → start in-process model + configure kernel for local endpoint
  - For `api`/`lmstudio`/`vps` providers (no engine to start) → model_selection configures kernel normally

---

## 📝 Navigation & Browser Interaction Tactics

These tactics worked 3+ times during testing and should be baked into the browser skill:

### Tactic 1: Typing into React-controlled inputs
```javascript
// pressSequentially() correctly triggers React onChange
const textarea = page.locator('textarea');
await textarea.pressSequentially('your text here', {delay: 10});
```
❌ `page.fill()` or direct `.value =` assignment does NOT trigger React state

### Tactic 2: Clicking elements behind overlays
```javascript
// Use evaluate() when Playwright's click is intercepted by overlays
await page.evaluate(() => {
  const btn = document.querySelector('button[aria-label="Close Dashboard"]');
  btn.dispatchEvent(new MouseEvent('click', {bubbles: true, view: window}));
});
```
❌ `page.locator('button').click()` fails when `<div class="fixed">` overlay intercepts pointer events

### Tactic 3: Finding icon-only buttons
Buttons with only `<img>` children have empty `textContent`. Find them by `aria-label`:
```javascript
const label = btn.getAttribute('aria-label') || btn.getAttribute('title') || '';
```
Or use Playwright role selector: `page.getByRole('button', { name: 'Close Dashboard' })`

### Tactic 4: Clicking SVG wheel section nodes
The WheelView uses SVG `<g>` elements. `.click()` doesn't work on SVG elements:
```javascript
const g = text.closest('g');
g.dispatchEvent(new MouseEvent('click', {bubbles: true, view: window}));
```

### Tactic 5: Waiting for cycling text
The ChatActivationText cycles every 3s between:
- "Tap iris for menu"
- "Double-click for 🎙️"
- "Tap here for chat"

Poll with `page.evaluate()` to catch the right text, then click it:
```javascript
for (let i = 0; i < 12; i++) {
  await page.waitForTimeout(1000);
  const clicked = await page.evaluate(() => {
    for (const p of document.querySelectorAll('p')) {
      if (p.textContent?.includes('Tap here for chat')) {
        p.click(); return true;
      }
    }
    return false;
  });
  if (clicked) break;
}
```

### Tactic 6: Top-level UI navigation flow
```
Level 1 (Main)          → Click IRIS orb
Level 2 (WheelView)     → Click "Agent"
Level 3 (Sections)      → Click "Models" or "Inference" (SVG dispatch)
  Models dialog         → Set Provider → Fill GGUF path → Confirm settings
  Inference dialog      → Configure swarm/in-process → 
Dashboard (after Browse)→ Click APPLY
Chat                    → Test message → Wait for response
```

### Tactic 7: React state must be set via pressSequentially
Setting `input.value` via `nativeSetter` or `.value =` updates the DOM display but does NOT update React's internal state. When the form is submitted (APPLY), the old state values are sent. Always use `pressSequentially()` for form inputs that need to be submitted.

---

## Inference Profiles Reference

Per `backend/agent/local_model_manager.py` lines 92-201 (`PROFILES` dict):

| Profile | n_gpu_layers | n_ctx | Flash Attn | KV Cache | n_batch | Sweet spot |
|---------|-------------|-------|------------|----------|---------|------------|
| **Eco** | 0 (CPU only) | 2048 | OFF | F16/F16 | 512 | No GPU |
| **Balanced** | -1 (auto) | **32768** | ON | q8_0/q8_0 | 2048 | Everyday default |
| **Balanced-MTP** | -1 (auto) | 32768 | ON | q8_0/q8_0 | 2048 | MTP speculative decoding |
| **Performance** | -1 (auto) | 16384 | ON | q8_0/q8_0 | 2048 | Faster first-token |
| **Voice-First** | -1 (auto) | 8192 | ON | q8_0/q8_0 | 2048 | Voice latency |
| **Research** | -1 (auto) | **102400** | ON | **q4_0/q4_0** | 2048 | Long docs (~100k ctx) |
| **RotorQuant** | -1 (auto) | 131072 | ON | **planar3** | 2048 | Research (5-10× KV compression) |

**Key point:** Every profile except "eco" already sets `n_gpu_layers: -1` (full GPU offload). They ARE GPU-prioritized by design. The difference between profiles is **context length** and **KV cache compression** — not GPU vs CPU.

The `iris_local_profile` dropdown in the UI (`hardware_profile` in config) IS the same thing as the inference profile. The `iris_local_gpu_layers` slider is a separate fine-tuning override for users who want to manually control layer offload independent of the profile preset.

**RTX 3070 (8 GB VRAM):** The "balanced" profile is verified at 45+ tok/s with Qwen3.5-9B Q3_K_S / Q4_K_M at 32k context with q8_0 KV cache compression. "Performance" reduces context to 16k for slightly faster first-token. "Research" drops KV to q4_0 to fit 100k context in 8 GB VRAM. All use full GPU offload (`n_gpu_layers: -1`).

---

## Current Config (as of session end)
```json
{
  "routing": { "mode": "SINGLE_LOCAL", "director_source": "api" },
  "inference": {
    "provider": "iris_local",
    "reasoning_model": "apothic/bonsai-8B-1bit-turboquant",
    "local_model_path": "C:/Users/midas/.lmstudio/models/apothic/bonsai-8B-1bit-turboquant/Bonsai-8B.gguf",
    "local_model_id": "apothic/bonsai-8B-1bit-turboquant",
    "models_directory": "C:/Users/midas/.lmstudio/models",
    "api_base_url": "https://api.cohere.com/v2/chat",
    "api_key": "rtUtK4MUo7ZxhTKc5kfaatpnHDEvSl89mF5fhXgn",
    "gpu_layers": 99,
    "temperature": 0.6,
    "max_tokens": 8192,
    "reasoning_effort": "balanced",
    "response_length": "medium",
    "thinking_style": "balanced",
    "tool_mode": "auto",
    "swarm_enabled": false,
    "swarm_mode": "SWARM_TURBO",
    "swarm_worker_count": 2,
    "worker_context": "auto"
  }
}
```
- **Model**: `apothic/bonsai-8B-1bit-turboquant` (1.1 GB GGUF from LM Studio folder)
- **Mode**: SINGLE_LOCAL
- **Provider**: iris_local
- **GPU Layers**: 99 (full offload)

---

## ❌ Not Yet Verified (Next Session Required)

### Must-Fix Before Testing

1. **Pass `profile` and `progress_cb` to `load_model()`** — The confirm_card handler at `iris_gateway.py` line 1102 calls `await mgr.load_model(_model_path)` without the `profile` or `progress_cb` parameters. This means:
   - Model loads with default settings (no hardware profile applied → may use CPU instead of GPU)
   - No progress feedback to the UI during loading
   
   **Fix:** Change to `await mgr.load_model(_model_path, profile=_profile, progress_cb=_progress_cb)` where `_profile` comes from `values.get("hardware_profile", "balanced")` and `_progress_cb` sends `model_load_progress` WebSocket messages.

2. **Guard against double-loading when swarm is enabled** — If both `model_selection` (iris_local) and `inference_mode` (swarm enabled) confirm_cards fire, the model gets loaded in-process AND swarm subprocesses spawn. Need to either:
   - Unload in-process model before starting swarm, OR
   - Move all engine startup to `inference_mode` handler only

3. **Kill orphaned llama processes before restart** — Always run `taskkill /F /IM llama-server.exe` before restarting backend. Multiple APPLY clicks can leave orphaned processes.

### Verification Steps (After Fixes)

4. **Local model responds in chat** — After fixes above:
   - Kill orphaned processes
   - Restart backend
   - Open browser → Dashboard → Agent tab
   - Use `pressSequentially()` to set model path in Selected Model field
   - Set Hardware Profile to "balanced" (ensures GPU offload)
   - Verify swarm is OFF in INFERENCE MODE
   - Click APPLY → watch for model load progress
   - Test chat with lengthy conversation

5. **SINGLE_API mode** — Switch `routing.mode` to `"SINGLE_API"`, adjust config, restart, test

6. **Model card / Inference card separation refactor** — Long-term fix described in Issue 2

7. **Tool calling (G1.8)** — Requires working local model first

---

## How to Resume Next Session

```bash
# 0. Kill any orphaned llama processes first!
taskkill /F /IM llama-server.exe 2>nul
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *llama*" 2>nul

# 1. Ensure backend is running
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 2. Ensure frontend is running
npm run dev

# 3. Open browser to http://localhost:3000
# 4. Navigate: Click cycling text → Dashboard opens → Agent tab
# 5. MODEL SELECTION: Set Provider = iris_local, type GGUF path via pressSequentially()
# 6. INFERENCE MODE: Set GGUF Models Directory, verify swarm OFF
# 7. Click APPLY once — wait for model to load (watch backend logs for "Model loaded successfully")
# 8. Open Chat → type message → verify actual model response (not "No local model loaded")
```

### Critical: Kill orphaned processes before restart
Multiple `llama-server.exe` or `python -m llama_cpp.server` processes can be left running from failed APPLY attempts. Always check and kill before restarting.
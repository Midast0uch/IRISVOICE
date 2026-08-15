# Local-Model Load Wiring Fix — Plan (2026-07-10)

## Problem

Loading a local GGUF model from the UI reports "loaded" in the frontend even when
the backend load silently failed, and the loaded model never appears in the
reasoning/tool-model dropdowns. Vision (LFM2.5-VL) is also dead.

### Root cause (verified)

1. **Lying HTTP load handler.** `backend/main.py:1472` `api_load_model` calls
   `await mgr.load_model(...)` but **discards the boolean return**. It
   unconditionally broadcasts `model_load_progress` with `phase:"done"` and returns
   `{"status":"ok"}`. So the UI (`components/dashboard/ModelBrowserPanel.tsx`) always
   shows "loaded" — even when `load_model()` returned `False`.

2. **Two disconnected load paths.** `ModelBrowserPanel` uses the HTTP
   `POST /api/models/load` path. The dashboard's "Load Model" button uses the
   WebSocket `load_local_model` path (`backend/iris_gateway.py:7185`), which DOES
   honor `ok` and calls `configure_inprocess_local(mgr)` +
   `configure_openai_compat(..., provider_name="iris_local")`. The HTTP path never
   sets `inference_mode=iris_local` and never wires the kernel.

3. **Dropdowns only populate via the WS path.** `_handle_get_available_models`
   (`iris_gateway.py:5014`) returns the loaded GGUF under
   `inference_mode == "iris_local"` *and* `mgr.is_loaded()`. The HTTP path never
   reaches this, so even a successful HTTP load is invisible to the reasoning/tool
   lists.

4. **Vision blocked by missing `llama-server.exe`.** `backend/tools/lfm_vl_provider.py`
   spawns `llama-server` on port 18181. `_find_llama_server_binary()` prefers
   `~/llama.cpp-upstream/llama-server` (absent), then `ik_llama.cpp`/`llama.cpp`
   builds (absent), then PATH (none). No binary exists →
   `_ensure_vision_server_running()` returns `False` → no server ever starts.
   (The GGUF + mmproj for LFM2.5-VL are already present at
   `%USERPROFILE%\models\LFM2.5-VL-450M\`.)

### Verified environment facts (2026-07-10)

- Backend is launched via bare `python` = `C:\Python314\python.exe` (has `llama_cpp`).
  `backend\venv\Scripts\python.exe` does **not** have `llama_cpp` (only `.venv`).
  → in-process path is viable **only** under the `python` interpreter, not `venv`.
- Real brain GGUFs exist in `%USERPROFILE%\.lmstudio\models\` (LFM2.5-8B-A1B,
  LFM2.5-1.2B-Instruct, Bonsai-8B, Qwopus3.5-9B-Coder-MTP, etc.).
  `LocalModelManager.MODELS_DIR` resolves there, NOT the empty `models/gguf`.
- **Inference parity is already correct**: every kernel call site
  (`agent_kernel.py` 3248/5361/5663/…) routes through `_get_lmstudio_client()`, which
  returns `InProcessOpenAIAdapter` for `iris_local`. The adapter duck-types the openai
  surface (`choices[0].message.content`, `.tool_calls`, delta streaming). Tool-calling
  works via llama-cpp's OpenAI-format `tool_calls`. **Once a model is wired, local
  inference behaves identically to an API-key provider.**

### Memory / bloat (verified)

- `local_model_manager.py` imports **no** `torch` or `llama_cpp` at module level
  (both lazy). Importing the manager / starting the backend does NOT spike memory.
- Only the real `load_model()` call (the `Llama()` ctor) allocates weights/VRAM —
  expected, bounded by the profile's `n_gpu_layers`/`n_ctx`.
- The fix MUST preserve this: no new module-level heavy imports; the WS load path
  already runs `Llama()` under `run_in_executor` so the event loop stays free.

## Plan

### Phase 1 — Fix the lying load path (code)

- [ ] `backend/main.py` `api_load_model`: capture `ok = await mgr.load_model(...)`.
  On `False`: broadcast `model_load_progress` with `phase:"error"` + message, and
  return `{"status":"error","message": ...}` (do NOT return ok). On `True`: keep the
  existing done broadcast. No new imports.
- [ ] `components/dashboard/ModelBrowserPanel.tsx`: route the per-model **Load**
  button through the WebSocket `load_local_model` message (same message the dashboard
  "Load Model" button already sends in `data/cards.ts`), instead of
  `fetch('/api/models/load', …)`. Single source of truth that honors `ok` and wires
  the kernel. Keep the WS `model_load_progress` listener already present for the bar.

### Phase 2 — Visibility in reasoning/tool dropdowns

- [ ] Confirm the WS `load_local_model` handler (`iris_gateway.py:7185`) already
  calls `_handle_get_available_models` after a successful load — so the
  `iris_local` branch (line 5014) returns the loaded GGUF stem and the dropdowns
  populate. Add an integration test asserting: with `mgr` loaded + provider
  `iris_local`, `available_models` lists the stem; with no load, the list is empty.

### Phase 3 — Vision (environment; binary install held for user OK)

- [ ] Make `lfm_vl_provider._find_llama_server_binary()` robust: if
  `~/llama.cpp-upstream` is absent, fall through to `IK_LLAMA_SERVER` env, PATH, and
  `LocalModelManager._find_llama_server_binary()` (already does this). No code change
  strictly required — the gap is purely the missing binary.
- [ ] (User decision) Build/install `llama-server.exe` via `build_llama_server.ps1`
  or `scripts/build/start_vl.ps1` after binary exists. GGUF + mmproj already in place
  at `%USERPROFILE%\models\LFM2.5-VL-450M\`.

### Phase 4 — Testing (no GPU required where possible)

Add `backend/tests/test_local_model_load.py` (pytest-collected, lazy imports — do NOT
import torch/llama_cpp/numpy at collection time, per repo convention):

- [ ] **Regression**: mock `LocalModelManager.load_model` to return `False` → assert
  `api_load_model` broadcasts `phase:"error"` and returns `status:"error"` (no false
  "loaded"). Return `True` → asserts `phase:"done"` / `status:"ok"`.
- [ ] **Adapter wrapping**: `InProcessOpenAIAdapter` wraps
  `choices[0].message.tool_calls[0].function.{name,arguments}` and streaming
  `chunk.choices[0].delta.tool_calls` (feed a fake llama-cpp completion dict, assert
  attribute access matches what `agent_kernel` / `output_parse.py` read).
- [ ] **Status reflection**: `is_loaded()`/`get_status()` track load state;
  `scan_models()` returns discoverable entries from `MODELS_DIR` (LM Studio dir).
- [ ] **Dropdown gate**: `_handle_get_available_models` `iris_local` branch returns
  the stem only when `mgr.is_loaded()`; empty otherwise (proves no phantom entry on
  failed load).
- [ ] Run the suite with `pytest backend/tests/test_local_model_load.py -v` and fix
  any failures. Verify memory stays flat at collection/import (no module-level heavy
  imports).

## Definition of done

- Frontend cannot report "loaded" when the backend load failed.
- A successfully loaded local model appears in the reasoning/tool dropdowns and is
  driven through the same OpenAI call surface as an API provider (verified by the
  adapter-wrapping test + existing kernel call sites).
- New tests pass; no module-level torch/llama_cpp/numpy import; backend import does
  not spike memory.
- Vision: code path ready; binary install is a separate user-approved step.

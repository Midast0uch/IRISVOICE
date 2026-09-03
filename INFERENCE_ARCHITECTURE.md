# IRIS Local Inference Architecture

> Layer-by-layer map of how a user text message flows from the WebSocket
> through the backend to the local llama-server swarm, and where each
> configuration decision is made.

---

## 1. WebSocket Ingress Layer

**Files:** `backend/main.py`, `backend/ws_manager.py`

### Connection lifecycle
1. Browser opens `ws://127.0.0.1:8000/ws/iris?client_id=iris`
2. `main.py::websocket_endpoint()` calls `ws_manager.connect(websocket, client_id, session_id)`
3. `WebSocketManager.connect()`:
   - Accepts the WebSocket
   - Creates / restores session: `session_id = "session_iris"`
   - Registers `active_connections["iris"] = websocket`
   - Starts heartbeat task (`_heartbeat_loop`)
4. `main.py` creates a per-session `asyncio.Lock()` in `_session_message_locks`

### Message receive loop (`main.py:1487`)
```python
while True:
    data = await websocket.receive_text()
    message = json.loads(data)
    msg_type = message.get("type", "")
```

**Control frames** (`_CONTROL_FRAMES = {"ping", "pong", "request_state"}`) are handled inline.

**All other frames** (including `"text_message"`) are dispatched to a background task:
```python
async def _dispatch(msg, sid, cid):
    lock = _session_message_locks.get(sid)
    async with lock:            # per-session sequential ordering
        await handle_message(cid, sid, msg)
asyncio.create_task(_dispatch(message, active_session_id, client_id))
```

> **Critical:** `_dispatch` acquires a session lock. If a previous message
> (e.g. `confirm_card`) is still inside `handle_message`, the new
> `text_message` waits on the lock.

---

## 2. IRIS Gateway Routing Layer

**File:** `backend/iris_gateway.py`

### `handle_message(client_id, message, session_id)`

1. Captures the running event loop into `self._main_loop` (used later by
   `_chunk_cb` to dispatch WebSocket sends from executor threads).
2. Extracts `msg_type = message.get("type")`
3. Routes based on `msg_type`:

| `msg_type` | Handler |
|-----------|---------|
| `"text_message"`, `"clear_chat"` | `_handle_chat()` |
| `"confirm_card"` | `_handle_settings()` |
| `"get_available_models"` | `_handle_get_available_models()` |
| `"ping"`, `"pong"` | heartbeat helpers |
| ... | ... |

---

## 3. Configuration Path (`confirm_card`)

**File:** `backend/iris_gateway.py` (`_handle_settings`)

When the user clicks **Confirm** on a settings card, the frontend sends:
```json
{
  "type": "confirm_card",
  "payload": {
    "section_id": "inference_mode",
    "values": {
      "agent_thinking_style": "balanced",
      "max_response_length": "medium",
      "swarm_enabled": true,
      "swarm_mode": "quality_director",
      "worker_context": 2048
    }
  }
}
```

### `_handle_settings` flow for `section_id == "inference_mode"`

1. `kernel = get_agent_kernel(session_id)`
2. Reads `_legacy_mode = values.get("inference_mode")`
3. **Legacy provider block** (`if _legacy_mode is not None`):
   - Maps old `inference_mode` values to providers
   - Calls `kernel.configure_lmstudio()`, `kernel.configure_ollama()`,
     `kernel.configure_api()`, or `kernel.configure_vps()`
   - **For `"lmstudio"`**: calls `kernel.prewarm_lmstudio()`
   - Then calls `_handle_get_available_models()` (tries port 1234, logs
     warning if unreachable)
4. **Swarm block** (`if "swarm_enabled" in values`):
   - `kernel.set_swarm_enabled(True)`
5. **Swarm auto-config block** (`if swarm_on and "swarm_mode" in values`):
   - `mgr = SwarmInferenceManager()`
   - `cfg = mgr.apply_swarm_mode("quality_director", 2048)`
   - `mgr.start_swarm()` → launches Director (port 8081) + Workers (port 8082)
   - `kernel.configure_openai_compat("http://127.0.0.1:8081", provider_name="iris_local")`
   - Sets `kernel._selected_reasoning_model` and `kernel._selected_tool_execution_model`
   - **Broadcasts to all peer sessions** in `_agent_kernel_instances`

> **Bug fixed:** `_mode_map` used to default unknown values to `"lmstudio"`,
> triggering LM Studio pre-warm even for swarm mode. Now defaults to `None`
> and skips legacy provider configuration.

---

## 4. AgentKernel — The Inference Orchestrator

**File:** `backend/agent/agent_kernel.py`

### `__init__` defaults
```python
self._model_provider = "uninitialized"
self._lmstudio_endpoint = "http://localhost:1234"
self._ollama_endpoint = "http://localhost:11434"
```

### `get_agent_kernel(session_id)` — singleton per session

When a new kernel is created, it **inherits** from the first configured peer:
```python
if kernel._model_provider == "uninitialized":
    for peer_id, peer_kernel in _agent_kernel_instances.items():
        if peer_kernel._model_provider not in (None, "uninitialized"):
            kernel.set_model_selection(
                reasoning_model=peer_kernel._selected_reasoning_model,
                tool_execution_model=peer_kernel._selected_tool_execution_model,
                model_provider=peer_kernel._model_provider,
            )
            kernel._lmstudio_endpoint = peer_kernel._lmstudio_endpoint
            break
```

> **Key point:** If the peer kernel was never configured (e.g. backend
> restarted, no confirm_card processed yet), the new kernel stays
> `"uninitialized"`.

### Configuration mutators

| Method | What it sets |
|--------|-------------|
| `configure_lmstudio(endpoint)` | `_lmstudio_endpoint`, invalidates cached client |
| `configure_openai_compat(endpoint, provider_name)` | `_lmstudio_endpoint`, `_model_provider`, invalidates client |
| `configure_ollama(endpoint)` | `_ollama_endpoint`, `_model_provider = "local"` |
| `configure_api(key, base_url)` | `_api_key`, `_api_base_url`, `_model_provider = "api"` |
| `set_model_selection(r, t, provider)` | `_selected_reasoning_model`, `_selected_tool_execution_model`, `_model_provider` |

> **Danger:** `set_model_selection()` overwrites `_model_provider`. If the
> Models card is confirmed **after** the Inference card, this can clobber
> `provider_name="iris_local"` back to `"api"` or `"lmstudio"`.

---

## 5. Chat Message Processing Path

**File:** `backend/iris_gateway.py` (`_handle_chat`)

### Step-by-step

1. `agent_kernel = get_agent_kernel(session_id)`
2. Wire tool bridge if not set
3. **Send `chat_typing` active=true** to client (immediate WebSocket push)
4. **Offload to ThreadPoolExecutor:**
   ```python
   response = await loop.run_in_executor(None, _execute_agent)
   ```
5. Inside executor thread, `_execute_agent()` calls:
   ```python
   agent_kernel.process_text_message(text, session_id=..., chunk_callback=...)
   ```

---

## 6. AgentKernel `process_text_message`

**File:** `backend/agent/agent_kernel.py`

### Decision tree

```
process_text_message(text)
│
├─ _needs_planning(text)?
│  ├─ YES → _execute_plan_der()  (Director-Explorer-Reviewer loop)
│  └─ NO  → _respond_direct()
```

`_needs_planning()` looks for tool trigger keywords. For a simple chat
message like "say hello", it returns **NO** → direct response path.

---

## 7. `_respond_direct` — The Direct Inference Path

**File:** `backend/agent/agent_kernel.py`

### Provider dispatch

```python
def _respond_direct(self, text, ...):
    messages = self._build_messages(text)

    # 1. OpenAI-compatible (lmstudio, openai_compatible, iris_local)
    if self._is_openai_compat():
        client = self._get_lmstudio_client()
        ...
        resp = client.chat.completions.create(model=sel, messages=..., stream=True)
        return self._stream_and_collect(resp, chunk_callback, reasoning_callback)

    # 2. Remote API (Cohere, OpenAI, Groq, etc.)
    if self._is_api_provider():
        _resp = _llm.complete(model=sel, messages=..., api_key=..., api_base=...)
        ...

    # 3. Ollama native
    if self._model_provider == "local":
        ...

    # 4. Fallback
    logger.error("no model provider matched")
    return "[IRIS error: could not reach language model — ...]"
```

### `_get_lmstudio_client()` — OpenAI client builder

```python
def _get_lmstudio_client(self):
    if self._lmstudio_client is not None:
        return self._lmstudio_client
    self._lmstudio_client = _OpenAI(
        base_url=f"{self._lmstudio_endpoint}/v1",
        api_key="lm-studio",
        http_client=httpx.Client(
            limits=...,
            timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10),
        ),
    )
    return self._lmstudio_client
```

> **Critical:** If `_lmstudio_endpoint` is still `"http://localhost:1234"`
> (default) and LM Studio is not running, the `connect` attempt times out
> after 10 s. The exception is caught in `_respond_direct` or
> `prewarm_lmstudio`.

---

## 8. SwarmInferenceManager — Process Orchestration

**File:** `backend/agent/swarm_inference_manager.py`

### `apply_swarm_mode(mode_str, worker_ctx)`

Builds a `SwarmConfig` dataclass:
- `mode`: `SwarmMode.QUALITY_DIRECTOR`
- `director_model`: path to Q3_K_M model
- `worker_model`: path to TurboQuant model
- `director_endpoint`: `"http://localhost:8081/v1"`
- `workers_endpoint`: `"http://localhost:8082/v1"`

### `start_swarm()`

1. `stop_swarm()` — kills existing llama-server processes
2. If local Director needed:
   - `self._start_llama_server(model, port=8081, ...)`
   - `time.sleep(3)` — staggered start to avoid VRAM contention
3. Start Workers:
   - `self._start_llama_server(model, port=8082, ...)`
4. Returns `True` if either process started

### `_start_llama_server()`

Builds command:
```
llama-server.exe
  --model <path>
  --port <port>
  --ctx-size <size>
  --gpu-layers <n>
  --parallel <n>
  --flash-attn on
  ...
```

Launches via `subprocess.Popen`, waits 2 s for startup, checks `proc.poll()`.

---

## 9. Full Request Flow (Happy Path)

```
Browser ──WebSocket──► main.py websocket_endpoint
                        └──► while True: receive_text()
                             └──► _dispatch() ──► handle_message()
                                  └──► iris_gateway.handle_message()
                                       └──► _handle_chat()
                                            ├──► send "chat_typing"
                                            └──► run_in_executor(_execute_agent)
                                                 └──► agent_kernel.process_text_message()
                                                      └──► _respond_direct()
                                                           └──► _is_openai_compat()?
                                                                └──► YES ──► _get_lmstudio_client()
                                                                     └──► OpenAI client ──HTTP──► llama-server:8081
                                                                          └──► streaming chunks
                                                                               └──► _chunk_cb()
                                                                                    └──► run_coroutine_threadsafe()
                                                                                         └──► ws_manager.send_to_client("chat_chunk")
                                                                                              └──► Browser UI update
```

---

## 10. Known Failure Modes

| Symptom | Likely cause |
|--------|-------------|
| No `chat_typing` received | `_handle_chat` not called (lock held by previous message, or `msg_type` mismatch) |
| `chat_typing` received, then silence | `_respond_direct` hung on API call or `_get_lmstudio_client` connect timeout |
| `[API_DEBUG] LiteLLM call failed: 404` | `_model_provider` is `"api"` (persisted state or Models card overwrite), kernel trying to call remote API |
| `LM Studio not reachable at :1234` | `_handle_get_available_models` running as part of legacy mode block; non-fatal |
| Pre-warm fails with port 1234 | `_legacy_mode` mapped to `"lmstudio"` (fixed) |
| Swarm processes running but chat uses API | `configure_openai_compat` was called, but `set_model_selection(..., provider="api")` overwrites it later |

---

## 11. Configuration Persistence Hazard

**Session state files:**
- `sessions/session_iris/state.json`
- `sessions/session_iris/agent.json`

These store `model_provider`, `api_key`, `api_base_url`, etc. When the backend
restarts and the session is recreated, `ws_manager.connect()` loads this state.

However, **`AgentKernel` does NOT read session state directly.** The kernel is a
separate object in `_agent_kernel_instances`. The hazard is:

1. Backend restarts → `_agent_kernel_instances` is empty
2. Browser reconnects → `get_agent_kernel("session_iris")` creates new kernel
3. Kernel inherits from peer (if any peer is configured)
4. If no peer is configured, kernel stays `"uninitialized"`
5. User clicks Confirm on Inference → `configure_openai_compat(..., "iris_local")` sets provider
6. **Later**, if Models card auto-confirms with `provider="api"`, `set_model_selection()` **overwrites** `"iris_local"` → `"api"`
7. Next chat message → `_is_api_provider()` is True → tries to call Cohere API → 404

---

## 12. What Is Actually Breaking Right Now

### Observed symptoms
1. **Chat messages sent from UI receive no response** — no `chat_message`, no error, no typing indicator.
2. **Backend logs show `[API_DEBUG] LiteLLM call failed: 404`** even though swarm processes are running on ports 8081/8082.
3. **`_model_provider` is `"api"`** (persisted in session state) instead of `"iris_local"`.
4. **`_lmstudio_endpoint` reverts to `"http://localhost:1234"`** (default) instead of `"http://127.0.0.1:8081"`.
5. **Pre-warm threads still try port 1234** (now fixed via `_mode_map` change).

### Root cause chain
```
Backend restart
    → _agent_kernel_instances empty
    → Browser reconnects → new kernel created ("uninitialized")
    → Frontend auto-confirms Models card (provider="api") from persisted state
        → set_model_selection(provider="api") overwrites kernel._model_provider
        → configure_api(key, base_url) sets remote Cohere endpoint
    → User clicks Confirm on Inference settings
        → configure_openai_compat(endpoint=8081, provider_name="iris_local")
            → SHOULD set _model_provider = "iris_local"
        → BUT Models card already ran → kernel has provider="api"
        → IF Inference card runs AFTER Models card, order is:
            1. configure_api()   → provider="api"
            2. configure_openai_compat() → provider="iris_local" (CORRECT)
        → IF frontend re-sends Models confirm LATER (page reload, state sync)
            → set_model_selection(provider="api") OVERWRITES "iris_local" back to "api"
    → Chat message arrives
        → _is_api_provider() → True
        → _respond_direct tries Cohere API with "MiniMax-M2.5-TEE"
        → 404 Not Found
        → Error logged, but response may not reach UI
```

### Why responses don't reach the UI
- `_chunk_cb` dispatches via `asyncio.run_coroutine_threadsafe()` against `self._main_loop`
- If `_main_loop` is stale (captured before a reconnect) or the WebSocket was replaced, the chunk is dropped silently
- `_handle_chat` does not validate `send_to_client` return value for `chat_typing`
- If the client disconnected mid-inference, messages are buffered but `flush_pending` only runs on reconnect

---

## 13. Recommended Fixes for Smooth Real-Time Operation

### 13.1 Prevent provider overwrite (HIGHEST PRIORITY)

**Problem:** `set_model_selection()` blindly overwrites `_model_provider`.

**Fix:** Make `set_model_selection` respect swarm mode:
```python
def set_model_selection(self, reasoning_model, tool_execution_model, model_provider=None):
    self._selected_reasoning_model = reasoning_model
    self._selected_tool_execution_model = tool_execution_model
    if model_provider and not getattr(self, "_swarm_enabled", False):
        self._model_provider = model_provider
```

### 13.2 Centralize configuration authority

**Problem:** Inference settings and Models settings fight each other. Two cards → two config paths → race condition.

**Fix:** Add a `_commit_provider_config(provider, endpoint, ...)` method that:
1. Checks if swarm is enabled
2. If swarm is ON → only accepts `provider_name="iris_local"` and swarm endpoints
3. If swarm is OFF → allows the card's provider
4. Logs every transition so we can trace it

### 13.3 Validate WebSocket delivery

**Problem:** `_chunk_cb` silently drops chunks if `_main_loop` is wrong.

**Fix:**
```python
def _chunk_cb(chunk: str):
    _loop = self._main_loop
    if _loop and _loop.is_running():
        fut = asyncio.run_coroutine_threadsafe(
            self._ws_manager.send_to_client(client_id, {"type": "chat_chunk", ...}),
            _loop
        )
        try:
            fut.result(timeout=5.0)  # force confirmation of delivery
        except Exception:
            self._ws_manager.buffer_message(session_id, {"type": "chat_chunk", ...})
```

### 13.4 Re-hydrate kernel on every `confirm_card`

**Problem:** If a session kernel was created before swarm config, it stays uninitialized.

**Fix:** In `_handle_settings`, after configuring the kernel, always call:
```python
kernel = get_agent_kernel(session_id)
if swarm_on and kernel._model_provider != "iris_local":
    # Force re-apply swarm config to this kernel
    kernel.configure_openai_compat(_swarm_ep, provider_name="iris_local")
```

### 13.5 Broadcast to future sessions

**Problem:** `get_agent_kernel` only copies from peers at creation time. A session created after swarm config has no peers to copy from if the config was applied to a now-gone session.

**Fix:** Store the "last known good" swarm config in a module-level variable:
```python
_swarm_config_snapshot: Optional[dict] = None

def get_agent_kernel(session_id):
    ...
    if _swarm_config_snapshot and kernel._model_provider == "uninitialized":
        kernel.configure_openai_compat(_swarm_config_snapshot["endpoint"], provider_name="iris_local")
        kernel._selected_reasoning_model = _swarm_config_snapshot["reasoning_model"]
        kernel._selected_tool_execution_model = _swarm_config_snapshot["tool_model"]
    ...
```

### 13.6 Remove `_handle_get_available_models` LM Studio probe

**Problem:** `_handle_get_available_models` unconditionally tries `http://localhost:1234` when checking LM Studio models, causing false warnings.

**Fix:** Skip the LM Studio probe if `_model_provider` is not `"lmstudio"`.

---

## 14. Performance & Threading Model

### Current hot path
1. WebSocket `receive_text()` → fast (async)
2. `json.loads` → fast
3. `_dispatch` acquires lock → fast unless contended
4. `_handle_chat` → `get_agent_kernel` (fast dict lookup)
5. `run_in_executor` → thread pool dispatch (~1-2 ms)
6. `_execute_agent` → `process_text_message` → `_respond_direct`
   - If swarm: `_get_lmstudio_client()` creates `httpx.Client` (~5-10 ms)
   - HTTP POST to `localhost:8081/v1/chat/completions` (~50-200 ms TTFB)
   - Streaming chunks back through `_chunk_cb`
7. `_chunk_cb` uses `run_coroutine_threadsafe` to push chunks to event loop
8. `ws_manager.send_to_client` → `websocket.send_json` → kernel → TCP

### Bottlenecks
| Bottleneck | Impact | Fix |
|-----------|--------|-----|
| `run_in_executor` thread pool saturation | Chat messages queue up | Increase `max_workers` or use dedicated executor |
| `_get_lmstudio_client` re-creates `httpx.Client` per request | ~10 ms overhead | Cache client per endpoint, invalidate only on endpoint change |
| `asyncio.run_coroutine_threadsafe` + `result()` not checked | Chunks lost silently | Add `result(timeout=2.0)` and buffer on failure |
| `_handle_get_available_models` blocks event loop | 10-15 s LM Studio timeout | Run in executor or skip if not lmstudio mode |

---

## 15. Fix Checklist

- [x] `_mode_map` default: unknown values no longer map to `"lmstudio"`
- [x] **CRITICAL:** Guard `set_model_selection` so swarm `provider_name="iris_local"` cannot be overwritten by Models card
- [x] **CRITICAL:** Add module-level `_swarm_config_snapshot` so new sessions auto-inherit swarm settings
- [x] Skip LM Studio probe in `_handle_get_available_models` when provider is not lmstudio
- [x] Add defensive re-apply in `_handle_settings`: if swarm is ON but kernel provider != "iris_local", force re-configure
- [ ] Validate `send_to_client` delivery in `_chunk_cb`; buffer on failure
- [ ] Ensure `flush_pending` runs after every `send_to_client` failure, not just on reconnect
- [ ] Increase thread-pool `max_workers` or use `ProcessPoolExecutor` for `_execute_agent` to prevent head-of-line blocking

---

## 16. DEAD WIRE AUDIT — Frontend Settings Not Consumed by Backend

### Finding: Four inference card fields are "dead wire"

The frontend `inference_mode` card collects these settings:
- `agent_thinking_style` (concise / balanced / thorough)
- `max_response_length` (short / medium / long)
- `reasoning_effort` (fast / balanced / accurate)
- `tool_mode` (auto / ask_first / disabled)

They are stored in session state (`sessions/session_iris/state.json`), but **the backend never reads them.**

| Field | Stored? | Backend Reads? | Hardcoded Behavior |
|-------|---------|---------------|-------------------|
| `agent_thinking_style` | ✓ Yes | ✗ No | `_needs_thinking()` uses keyword heuristics only |
| `max_response_length` | ✓ Yes | ✗ No | `max_tokens=4096` hardcoded in `_respond_direct` |
| `reasoning_effort` | ✓ Yes | ✗ Partially | Only for Cohere API reasoning models; hardcoded `"high"`, never reads UI setting |
| `tool_mode` | ✓ Yes | ✗ No | Tool execution controlled by `_needs_planning()` → DER loop |

### Why this matters
- Users think they're controlling behavior, but nothing changes
- Technical debt: fields exist in `models.py`, session state, and UI but have no backend implementation
- Risk of future conflicts if someone wires them up without understanding the existing hardcoded paths

### What the backend actually does (hardcoded)
- **Thinking style:** `_needs_thinking(text)` decides based on keywords (`why`, `explain`, `debug`, `plan`, etc.). No UI override.
- **Response length:** `max_tokens=4096` everywhere. No UI override.
- **Reasoning effort:** For Cohere models only, if model name contains "reasoning", sets `reasoning_effort="high"`. The UI's "fast/balanced/accurate" is never mapped.
- **Tool mode:** `_needs_planning(text)` detects tool triggers. DER loop runs automatically. No "ask first" or "disabled" mode.

### Recommendation
Either:
1. **Implement wiring** — read these values from session state in `_handle_settings` and pass them to `_respond_direct` / `_execute_plan_der`, OR
2. **Remove from UI** — if they're not planned, remove from `models.py` so users don't think they work, OR
3. **Document as placeholders** — add a comment that these are "UI-collected, backend-not-yet-implemented"

Current status: **FIXED** — all four fields are now read from session state in `_handle_settings` and stored on the AgentKernel. They actively affect inference:
- `thinking_style` → `_needs_thinking()` returns False (concise), heuristic (balanced), or True (thorough)
- `max_response_length` → maps to `max_tokens` (short=1024, medium=4096, long=8192)
- `reasoning_effort` → maps to `temperature` (fast=0.9, balanced=0.6, accurate=0.3) and `reasoning_effort` for API models
- `tool_mode` → `_needs_planning()` returns False (disabled), prefix-only (ask_first), or heuristic (auto)

---

## 17. Models Card vs Inference Card — Conflict Matrix

### What each card configures

| Card | Sets on AgentKernel |
|------|---------------------|
| **Models** (`model_selection`) | `set_model_selection(reasoning_model, tool_model, provider)`<br>`configure_lmstudio(endpoint)`<br>`configure_api(key, base_url)`<br>`configure_ollama(endpoint)`<br>`configure_vps(...)` |
| **Inference** (`inference_mode`) | `set_swarm_enabled(true/false)`<br>`configure_openai_compat(endpoint, "iris_local")`<br>Legacy: `configure_lmstudio()`, `configure_api()`, `configure_ollama()`, `configure_vps()` |
| **Monitor** (`analytics`, `logs`, `diagnostics`) | `_handle_monitor_card()` pushes live data back to UI via `update_field` messages |

### Monitor cards (NEW — now wired)

Previously, the monitor cards (`analytics`, `logs`, `diagnostics`) were completely unhandled. The backend now processes them:

- **Diagnostics:** Checks kernel provider/endpoint, llama-server process status, GPU status via nvidia-smi, and pushes results into `system_health`, `troubleshoot`, `debug_info` fields
- **Logs:** Reads `backend_test.err` tail and pushes into `system_logs` and `error_logs` fields
- **Analytics:** Gathers active session count, provider, model names, swarm status, and pushes into `usage_stats` field

All data is sent back to the frontend via WebSocket `update_field` messages so the UI text fields populate with live system status.

### Conflicts (before my fixes)

1. **Provider overwrite:** Models card calls `set_model_selection(provider="api")` → overwrites swarm's `provider="iris_local"` → kernel routes to Cohere API instead of llama-server
2. **Endpoint confusion:** Inference card legacy mode sets `configure_lmstudio(:1234)` → Models card later sets `configure_api(cohere.com)` → kernel has Cohere endpoint but LM Studio client cached
3. **Dual authority:** Both cards think they own provider routing. The comment says "delegated to model_selection" but the code still processes legacy inference_mode.

### After fixes

- Models card `set_model_selection()` is **guarded** — if swarm is enabled, provider overwrite is ignored
- Inference card stores `_swarm_config_snapshot` — new sessions auto-hydrate
- Defensive re-apply catches any drift

### Still a risk

If the frontend sends `inference_mode` in the `inference_mode` card (legacy field), the backend still processes it and calls `configure_lmstudio()` / `configure_api()` / etc. This bypasses the Models card entirely. The `_mode_map` fix prevents unknown values from defaulting to lmstudio, but if the frontend explicitly sends `"lmstudio"`, it will still reconfigure the kernel.

**Safe path:** Ensure the frontend's `inference_mode` card does NOT send the legacy `inference_mode` field, only sends `swarm_enabled`, `swarm_mode`, `worker_context`, and the behavior fields (thinking_style, etc.).

---

## 18. Technical Debt Review of My Fixes

### Fix 1: `set_model_selection` swarm guard
- **File:** `backend/agent/agent_kernel.py:4269-4279`
- **Quality:** Clean. Uses `getattr(self, "_swarm_enabled", False)` for safety. Logs every blocked overwrite.
- **Peer propagation:** Also guarded (line 4307). Clean.
- **Risk:** Low. Does not change behavior when swarm is disabled.

### Fix 2: `_swarm_config_snapshot`
- **File:** `backend/agent/agent_kernel.py:4435-4439` (declaration), `4506-4527` (auto-hydrate)
- **File:** `backend/iris_gateway.py:912-926` (population), `865-876` (clear on disable)
- **Quality:** Clean. `Optional[dict]` typed. Only hydrates when `kernel._model_provider == "uninitialized"`.
- **Python scoping bug fixed:** Used `import backend.agent.agent_kernel as _ak_mod` + `_ak_mod._swarm_config_snapshot = {...}` instead of `from ... import _swarm_config_snapshot` which would create a local variable.
- **Risk:** Low. Snapshot is cleared when swarm is disabled.

### Fix 3: Defensive re-apply
- **File:** `backend/iris_gateway.py:951-965`
- **Quality:** Clean. Only runs when `swarm_on` is True AND provider != `"iris_local"`. Logs warning so we can see if it ever triggers.
- **Risk:** Low. Non-blocking — continues even if re-configure fails.

### Fix 4: LM Studio probe skip
- **File:** `backend/iris_gateway.py:2354-2386`
- **Quality:** Acceptable. Nested `try/except` is a bit defensive, but necessary because `get_agent_kernel` could theoretically fail. Returns early with swarm model info.
- **Risk:** Low. Falls through to normal flow on any exception.

### No dead code introduced
All new code paths are conditional and have clear activation conditions. No imports added at module level that would slow startup.

### One remaining concern
The `_swarm_config_snapshot` stores model names as `Path(cfg.director_model).stem`. If the model path contains spaces or unusual characters, `.stem` may produce an invalid model ID. This matches existing behavior, but should be reviewed.

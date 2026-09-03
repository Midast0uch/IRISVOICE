# Requirements: Local Model Lifecycle & Frontend Sync

## Decisions Locked
- **D1 — Bearer guard is a safety net, not a feature:** An API provider without a key MUST NOT route to `Bearer ` — it fails closed with a structured `Illegal header` replaced by a typed `provider_not_ready` error surfaced on `role_bindings_updated.status` + chat error, not a transport crash. Deferred: no auto-fallback to local.
- **D2 — Unload is authoritative from manager, not WS timing:** Unload success is defined as `LocalModelManager.is_loaded()==False` + config `local_model_status="unloaded"` + router has no `local:*` provider, not as "WS frame arrived".
- **D3 — Frontend reconciliation is pull + push:** On every WS `connected` transition the frontend re-pulls `/api/inference/state` snapshot AND `get_local_model_status`; WS pushes are deltas. Lost delta never leaves frontend stale past one reconnect.
- **D4 — One logical WS per app instance:** Tauri and browser both use `client="iris"` — the runtime SHALL keep a single shared `WebSocket` ownership (module singleton), not one per `useIRISWebSocket` instance. Multiple hook consumers share the same socket via the existing singleton stores + a shared connection manager.
- **D5 — Loading a local model does NOT auto-rebind brain (OQ-1 RESOLVED):** User confirmed the red trigger appears on the SAME local model they loaded AND set as brain in the ModelSwitcher — it is NOT about an API-provider brain. The red is the frontend `loaded` flag going stale (model is on GPU, UI shows not-loaded). User is OK with red as a signal, but it MUST be actionable: it must say WHAT is wrong and HOW to correct it. No auto-rebind — the user explicitly wants to keep control; the red must inform, not silently override.
- **D6 — Dashboard path field follows manager status:** When `local_model_status` arrives with `model_path`, the dashboard SHALL sync `local_model_path` field so the card reflects the resident model, not just the badge.
- **D7 — Observability is first-class:** Every load/unload/bearer-guard event logs with `session_id`, `instance_id`, `loaded` boolean at `INFO` so tuning the 90s typing watchdog / 30s PONG timeout is measurable.

## Introduction
Fix local-model load/unload fragility where a model remains resident on the GPU but the widget/frontend shows stale/unloaded/red state, unload requires a Tauri refresh, and sending a message crashes with `Illegal header value b'Bearer '`. The fix makes server lifecycle, router registry, and three frontend stores converge on every reconnect and makes the Bearer path fail closed.

### Success criteria
- `unload_local_model` clears GPU (manager `is_loaded==False`) AND badge reads `UNLOADED` AND ModelSwitcher no longer lists the `local:*` provider, without a window refresh, within 5s.
- Reloading the Tauri window or losing WS for 5s then reconnecting shows the *live* model state (loaded file is shown, unloaded file is not shown).
- Sending a message while Brain is bound to an API provider with no key does NOT crash with `Illegal header` — it returns a typed `provider_not_ready` error surfaced in chat + `role_binding_error` status `missing_api_key`.
- ModelSwitcher trigger is never red when the active local provider is resident; dashboard card shows `MODEL STATUS: LOADED` + path of the resident GGUF.
- No JS `JSON.parse` interleaving or `WebSocket is not connected. Need to call 'accept' first.` spurious error on rapid reconnect.

## Requirements

### REQ-1: Bearer header fail-closed
**User Story:** As a user I want sending a message never to crash the kernel with an illegal header when an API key is missing, so that I see a clear fix-it message instead of `Agent kernel error: Illegal header value`.

**Verified:** `backend/agent/inference/transport.py:546` (`f"Bearer {self._api_key}"` unconditional), `backend/agent/agent_kernel.py:2917` same, `backend/agent/inference/router.py:817` (`get_secret(...) or ""`), `backend/agent/inference/router.py:1138` guard exists as positive example.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL NOT emit `Authorization: Bearer ` (empty value) on any HTTP call.
- AC2: IF `get_secret(instance_id)` returns `None` or blank for a `ProviderKind.API` instance THEN THE SYSTEM SHALL treat `resolve(role)` health as NOT ok with `status=missing_api_key` and surface `role_binding_error` / chat error with `error="missing_api_key"` rather than constructing a transport.
- AC3: WHEN `ApiHttpxTransport.generate` is called with an empty key THEN THE SYSTEM SHALL raise a typed `ProviderNotReadyError(missing_api_key)` that the router maps to `role_binding_error` and the chat path maps to a user-visible message `API key missing for <provider> — add it in Settings → Model & Inference`, not `InvalidHeader`. The exception SHALL live in `backend/agent/exceptions.py` with a new `ErrorCode.PROVIDER_NOT_READY` (1005) so it is caught by the existing `AgentException`/`format_exception_for_response` machinery.
- AC4: THE SYSTEM SHALL strip surrounding whitespace from any key at storage and before header construction (keyring.py:82-85 already does).

**Edge Cases:**
- Key is all whitespace → treated as missing.
- Multiple API providers, one missing, one present → only the missing one is flagged.
- Local/OLLAMA/inprocess transports never send `Authorization` unless `api_key` is truthy (already true for `_DirectVisionClient`).

### REQ-2: Actionable unavailability signal
**User Story:** As a user I want the red trigger to tell me exactly what is wrong and how to fix it, so that a stale/loaded-but-not-reflected model is not a mystery.

**Verified:** `components/ModelSwitcher.tsx:226` (`brainAvailable || !brainBinding ? glow : red`), `components/ModelSwitcher.tsx:200` (title already appends `(unavailable)`), `hooks/useInferenceState.ts:130` filter (`has_key/loaded`), `backend/agent/inference/router.py:760 health_check`, `backend/agent/inference/router.py:254` (registry is process-wide singleton).

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL include a per-role health reason (`ok`, `reason`) in the inference snapshot so the frontend can render unavailable without probing.
- AC2: WHEN a bound provider is not in the usable list THEN THE SYSTEM SHALL render the trigger red AND surface the SPECIFIC reason + correction in the trigger `title` — distinguishing at minimum: `local_not_loaded` ("local model loaded on server but not reflected in UI — reconnecting"), `missing_api_key` ("API key missing for <provider> — add it in Settings → Model & Inference"), and `missing_provider` ("provider no longer registered — select a model").
- AC3: THE SYSTEM SHALL reconcile the frontend `loaded` flag from the backend on every WS `connected` (REQ-4) so a model that IS resident on the GPU is never shown red purely because the UI state went stale — the red is reserved for genuinely actionable conditions.
- AC4: THE SYSTEM SHALL keep the trigger red ONLY while the condition is real; once reconciled (loaded flag true) the trigger SHALL return to the glow color without a manual refresh.

**Edge Cases:**
- Model loaded on backend but frontend stale → red with `local_not_loaded` reason + auto-reconcile on reconnect (AC3), not a permanent red.
- Provider removed after unload while still bound → red with `missing_provider` reason.
- API provider with no key → red with `missing_api_key` reason + correction.
- No binding at all → glow (not red) — `!brainBinding` already returns glow.

### REQ-3: Reliable unload without refresh
**User Story:** As a user I want clicking Unload to always free the model and update every UI surface, so that I never need to refresh the Tauri window.

**Verified:** `backend/agent/local_model_manager.py:3223 unload_model` (drops `_llm`, `terminate()`, `kill_orphan_servers`), `backend/iris_gateway.py:9121 _handle_unload_local_model` (persists `unloaded`, de-wires kernel, removes `local:*` from registry, but only `send_to_client` for status), `components/dashboard/ModelBrowserPanel.tsx:254 doUnload + 138 handler (unloadInFlightRef gate)`.

**Acceptance Criteria:**
- AC1: WHEN `unload_local_model` is received THEN THE SYSTEM SHALL call `LocalModelManager.unload_model()` and on success persist `cfg.inference.local_model_status="unloaded"`, remove every `local:*` provider from the router registry, de-wire `kernel.configure_inprocess_local(None)` + `configure_openai_compat(None)`, and broadcast BOTH `local_model_status {loaded:false}` AND `role_bindings_updated` snapshot to the *session* (not just initiator) so any surviving socket reconciles.
- AC2: WHILE `local_model_status {loaded:false}` has been broadcast THEN THE SYSTEM SHALL ensure `mgr.is_loaded()==False` and `mgr.get_status().model_path is None` (no orphan `llama-server` pid remains — `kill_orphan_servers()`).
- AC3: THE SYSTEM SHALL complete AC1 within 5s on the in-process path; if confirmation is not received the frontend SHALL reconcile via `GET /api/inference/state` + `get_local_model_status` poll after 30s and clear the spinner.

**Edge Cases:**
- Double-click Unload → second is no-op (`loadPhase==='unloading'` guard remains but handler is terminal on any `loaded===false`, so stuck spinner still clears).
- Unload while a load is in flight → load's `crash_cb` + unload both converge to `unloaded`.
- Backend restart mid-load → boot reset `main.py:376` forces `unloaded` so no stale `local:*` remains.

### REQ-4: Frontend reconciliation on reconnect
**User Story:** As a user I want the widget to self-heal after a disconnect, so the ModelSwitcher, dashboard badge, and ModelBrowserPanel agree without manual refresh.

**Verified:** `hooks/useIRISWebSocket.ts:454 ws.onopen sends get_local_model_status + request_state`, `hooks/useIRISWebSocket.ts:1212 provider_added → iris:provider_added`, `hooks/useInferenceState.ts:56 fetch('/api/inference/state') on mount + 117 role_bindings_updated merge`, `components/dashboard/ModelBrowserPanel.tsx:143 iris:ws_message handler`.

**Acceptance Criteria:**
- AC1: WHEN WS transitions to `connected` THEN THE SYSTEM SHALL re-fetch `GET /api/inference/state` (providers/role_bindings) in `useInferenceState` and re-send `get_local_model_status` (already does) so a lost delta is repaired within one RTT.
- AC2: WHEN `role_bindings_updated` or `provider_added` arrives THEN THE SYSTEM SHALL merge field-wise (`?? prev`) without clobbering `provider_presets/model_catalog`.
- AC3: WHILE disconnected THEN THE SYSTEM SHALL queue `load_local_model` / `unload_local_model` and flush on reconnect (existing `messageQueueRef` does for non-NON_QUEUEABLE, but `load_local_model` is NOT in `NON_QUEUEABLE` so it already queues — verify and keep).
- AC4: THE SYSTEM SHALL maintain a single shared WS connection per app instance (not per hook instance), so `client="iris"` is not evicted by its own re-renders (fix churn described at `useIRISWebSocket.ts:38`).

**Edge Cases:**
- 3 rapid reconnects (drag, HMR) → at most one socket in `active_connections[iris]` and no `RuntimeError: WebSocket is not connected. Need to call 'accept' first.`
- Queued unload flushed after reconnect → backend idempotently returns `True` (already unloaded).
- Tauri vs browser path both converge — `isTauri` branch and `WebSocket` branch both emit the same `connected` reconciliation.

### REQ-5: Dashboard Local Model card truth
**User Story:** As a user I want the Local Model card under Agent to show the model I actually loaded, so that I don’t see a mismatch between ModelSwitcher and the card.

**Verified:** `data/cards.ts:204 local_model_path dropdown`, `components/dark-glass-dashboard.tsx:291 Model Status badge + 1037 handleLocalModelStatus (writes only status)`, `hooks/useIRISWebSocket.ts:1287 local_model_status case (maps loaded→status, writes both hyphen/underscore keys)`.

**Acceptance Criteria:**
- AC1: WHEN `local_model_status {loaded:true, model_path:".../foo.gguf"}` arrives THEN THE SYSTEM SHALL write BOTH `local_model_status="loaded"` AND `local_model_path="<path>"` into `localFieldValues` (`local_model` + `local-model-card` buckets) so the card shows the file name. The same path sync SHALL apply to the `get_local_model_status` pull response, which carries `model_path` from `mgr.get_status()` (iris_gateway.py:9363).
- AC2: WHEN `local_model_status {loaded:false}` arrives THEN THE SYSTEM SHALL clear `local_model_path` to `""` and set badge to `unloaded`.
- AC3: THE SYSTEM SHALL keep the card’s `status` mapping identical to the existing `useIRISWebSocket.ts:1293` chain (`status` string > `loaded` boolean > `unloaded`), adding path sync without changing that chain.

**Edge Cases:**
- Old backend payload with no `model_path` → path unchanged (no crash).
- `model_path` is absolute vs. stem — card shows `Path(...).name` (label) but stores full path for id.

### REQ-6: Single WS ownership for the widget
**User Story:** As a user I want the Tauri widget not to fight itself for the socket, so rapid switches don’t wedge the loader.

**Verified:** `hooks/useIRISWebSocket.ts:38 comment + per-instance wsRef`, `backend/ws_manager.py:102 replacing stale connection`, `hooks/useIRISWebSocket.ts:372 deferred close 2s`.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL keep exactly one `WebSocket` (or one Rust `ws:client`) per page instance shared by all `useIRISWebSocket` consumers, with ref-counted open/close.
- AC2: IF a new connection for `client="iris"` arrives while an old one is still in `active_connections` THEN THE SYSTEM SHALL replace the entry without calling `stale_ws.close()` before the new `accept()` (already does at `ws_manager.py:130-144`) and the frontend SHALL NOT open a second socket concurrently.
- AC3: THE SYSTEM SHALL keep the 2s deferred close for HMR but never hold two open sockets for the same `client_id`.

**Edge Cases:**
- HMR Fast Refresh remount during load progress → no duplicate `request_state` burst beyond the intended one per `connected`.
- Tauri `ws:disconnected` → same reconciliation as browser `onclose`.

### REQ-7: Observability
**User Story:** As the tuner I want load/unload/bearer-guard events logged with session and provider id so I can measure how often reconnection hides a state drift.

**Verified:** NEW

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log at INFO `session_id`, `instance_id`, `loaded`, `reason` on every `load_model` terminal (ready/error), `unload_model`, and `missing_api_key` guard, scoped by `session_id` so a replay harness can count trigger frequency.
- AC2: THE SYSTEM SHALL emit `system_status.inference` with `providers`/`role_bindings` at least every 30s so the standing harness sees convergence without waiting for user action.

**Edge Cases:**
- High-frequency switching (stress) → logging stays on the success path only, not per `local_model_loading` chunk.
- Missing `session_id` (unknown session) → log with `session=unknown` rather than crash.

## Non-Requirements (Out of Scope)
- Auto-rebinding Brain to newly loaded local model — explicit user pick via ModelSwitcher remains.
- New model download / HF hub integration — not touched.
- Diffusion/TTS model lifecycle — separate.
- Full offline queue for `text_message` without `conversation_id` — existing `SUPPLY_IF_MISSING` contract stays (text_message without id surfaces rather than invents).

## Open Questions
- **OQ-2 — VRAM-freeing guarantee:** Should unload assert VRAM is actually freed (via `get_hardware_info`) or only that `mgr.is_loaded()==False`? The in-process path sets `_llm=None` + `gc.collect()`; a reference cycle would keep VRAM resident. Recommend asserting `is_loaded()==False` as the contract and logging free-VRAM delta as observability, not a hard gate (VRAM reporting is platform-flaky).
- **OQ-3 — Red-trigger copy:** Exact wording of the `title` reasons (e.g. "local model loaded on server but not reflected in UI — reconnecting" vs "local model not loaded — load it in Models Browser"). Resolve during Wave 3 UI polish; the mechanism (REQ-2 AC2) is fixed regardless.

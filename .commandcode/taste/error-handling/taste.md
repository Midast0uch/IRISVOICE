# error-handling
- When fixing local model loading/wiring, verify end-to-end parity between local inference and API-provider inference — ensure the loaded model drives reasoning, tool calls, and streaming through the exact same call surface as the API path. Confidence: 0.72
- Test that model loading does not cause memory spikes or bloat — verify resource stability at load time alongside functional correctness. Confidence: 0.70
- Never let model loads fail or load silently — always log both start and completion (success or failure) visibly so progress and errors can be traced. Confidence: 0.88
- Ensure the audio pipeline has thorough logging at every stage so bugs and errors can be caught early. Confidence: 0.85
- When verifying the WS `load_local_model` path end-to-end, also test that the handler uses the message payload's `model_path` (not `cfg.inference.local_model_path`) — if it reads from config instead of the frontend's message, the frontend's load request is silently discarded. Confidence: 0.85
- The `iris_gateway.py` `_handle_load_local_model` and `_handle_unload_local_model` call `self._broadcast_json()` and `self._send_json()` — neither exists on IRISGateway; replace with `self._ws_manager.broadcast_to_session(session_id, ...)` and `self._ws_manager.send_to_client(client_id, ...)`. Confidence: 0.95
- The `mgr.load_model()` signature is `(model_path, profile="balanced", custom_params=None, progress_cb=None, crash_cb=None)` — do NOT pass `gpu_layers`, `context_length`, or `hardware_profile` as kwargs. Confidence: 0.90
- When a model local model loads over the in-process path, the handler must wire a `progress_cb` that broadcasts incremental progress (5%→95%→100%) so the frontend shows real progress and the load doesn't appear stuck. Confidence: 0.82

# Tasks: Session / Conversation Switching (cross-thread contamination fix)

> Each task links to a requirement. Grouped into waves for parallel execution.
> RIPPLE notes cite the Ripple-Effect Map in design.md so no dependent code is missed.

## Wave 1 — Make the message reachable (root cause)

- [ ] T1 (REQ-1): Add `"switch_conversation"` to the `_handle_chat` routing list at
  `backend/iris_gateway.py:503`
  (`elif msg_type in ["text_message", "clear_chat", "new_conversation", "switch_conversation"]`).
  — RIPPLE: enables REQ-2/3/4/5 handlers that already exist at lines 4331-4365 but were
  unreachable. No other file touched.

## Wave 2 — Fix the handler body

- [ ] T2 (REQ-3): In `_handle_chat` switch branch (`backend/iris_gateway.py:4331`), add
  `engine.interrupt_speech()` BEFORE updating `_active_conversation_id`, wrapped in
  try/except (mirror `iris_gateway.py:2082`). — RIPPLE: depends on T1; uses existing
  idempotent `audio/engine.py:323` (NO CHANGE verified).
- [ ] T3 (REQ-4 AC3): Fix the ack payload at `backend/iris_gateway.py:4358` —
  replace undefined `conversation_id` with `new_conv_id`. — RIPPLE: `useIRISWebSocket.ts:1319`
  reads `payload.conversation_id` (NO CHANGE verified); must match.
- [ ] T4 (REQ-4 AC2): Set `payload.status` to `"context_saved"` when the old-context save
  ran, else `"switched"` (`backend/iris_gateway.py:4356-4360`). — RIPPLE: matches contract
  test `test_voice_command_start_contract.py:137` (CONTRACT LOCK).
- [ ] T5 (REQ-2 AC1, REQ-5): Confirm `_active_conversation_id[session_id] = new_conv_id`
  (line 4350) and old-context save (line 4338) are correct as-written; no change unless
  verification shows otherwise. — RIPPLE: `_handle_voice` reads this at line 2343 (NO CHANGE
  verified).

## Wave 2.5 — Isolate in-flight old-thread work (REQ-6, soft-cancel)

- [ ] T13 (REQ-6 AC2): Add `self._cancel_requested = threading.Event()` to `AgentKernel`
  (`backend/agent/agent_kernel.py`, `__init__`). Poll it at DER step boundaries inside
  `process_text_message` (after each `dispatch` / before next step) — when set, return
  early without emitting further events. — RIPPLE: `process_text_message` runs in a thread
  pool (api/chat.py:199), so the flag self-cancels without killing the thread.
- [ ] T14 (REQ-6 AC1/AC4/AC6): In the `switch_conversation` handler (`iris_gateway.py:4331`),
  BEFORE re-pointing, call `get_agent_kernel(old_conv_id, session_id)._cancel_requested.set()`
  synchronously (microsecond, no await) so the switch returns immediately. SOFT cancel: do
  not kill an in-flight tool subprocess. — RIPPLE: depends on T1 (handler reachable) + T13.
- [ ] T15 (REQ-6 AC3/AC5, CT-3): Ensure DER-loop EventPayloads (`TOOL_RESULT`/`TOOL_CALL`/
  `TOOL_ERROR`/`TASK_*`/`VALIDATION_FAILED`) carry `conversation_id` in `data`
  (`agent_kernel.py` emit sites), and scope `WSEventBridge.broadcast_to_session` by
  `conversation_id` when present, falling back to `session_id` only when absent
  (`ws_event_bridge.py:112-131`). — RIPPLE: frontend `useIRISWebSocket.ts` already reads
  `payload.conversation_id` on `conversation_switched`; add a drop-gate for stale
  `conversation_id` on `TOOL_*`/`TASK_*` events (small frontend addition — verify, may be
  NO CHANGE if already gated).
- [ ] T16 (REQ-6 AC4): Verify an in-flight tool call running at switch time finishes once
  and its result is written to the OLD conversation's store (not broadcast to B). Add a
  guard so no SUBSEQUENT step fires for the old thread. — RIPPLE: `tool_decision.dispatch`
  already captures into `self.conversation_id` (agent_kernel.py:6642); only the broadcast
  path changes.
- [ ] T19 (REQ-8 AC1/AC2/AC4): In the `sync_state` handler (`iris_gateway.py:4262`), set
  `_active_conversation_id[session_id] = payload.conversation_id` when non-empty (same
  setter as switch/new_conversation); include `current_conversation_id` in `sync_state_ack`.
  — RIPPLE: `_handle_request_state` (line 6168) already returns this dict, so the frontend
  reconnect tiebreaker (`useIRISWebSocket.ts:530`) gets the right id once set.
- [ ] T20 (REQ-8 AC3): When `sync_state` re-binds to a DIFFERENT `conversation_id` than the
  current active one, soft-cancel the previously-active thread (reuse T13/T14 cancel flag).
  — RIPPLE: depends on T13 (flag exists) + T19 (setter).
- [ ] T22 (REQ-8 AC5): In `ws_manager.connect` reconnect-replacement (`ws_manager.py:63-99`),
  when a stale `client_id="iris"` socket is replaced, trigger the REQ-8 soft-cancel on the
  previously-active thread if the new `sync_state` resumes a different `conversation_id`
  (covers localhost→Tailscale flip mid-response). — RIPPLE: depends on T13 (flag) + T19
  (setter); `ws_manager` must call back into the gateway's cancel (pass a hook or import).

## Wave 3 — Tests (contract + behavioral + unit)

- [ ] T6 (CT-1, REQ-4): Extend `backend/tests/contract/test_voice_command_start_contract.py`
  `TestSwitchConversationContract` — assert `conversation_switched` carries
  `conversation_id == new_conv_id` and `status == "context_saved"`. — RIPPLE: locks the
  interface (CONTRACT LOCK).
- [ ] T7 (CT-2, REQ-1): New contract test — dispatch `switch_conversation` through the
  gateway, assert NO `Unknown message type` warning and NO `error` response; assert
  `_handle_chat` was reached (capture sent messages via mocked `_ws_manager`). — RIPPLE:
  depends on T1.
- [ ] T8 (BT-1, REQ-2/3): New `tests/behavioral/test_switch_cancels_tts.py` — full flow:
  voice cmd in thread A → TTS begins → `switch_conversation` to B → assert TTS interrupted,
  `_active_conversation_id[sid] == B`, subsequent wake-word resolves to B. — RIPPLE: depends
  on T1+T2.
- [ ] T9 (UT-1/UT-2, REQ-2/3): Unit tests — missing `conversation_id` → dict unchanged + ack
  sent (no NameError); `interrupt_speech` called once when engine present, zero when absent.
  — RIPPLE: depends on T2+T3.
- [ ] T17 (CT-3, REQ-6): Contract test — DER-loop EventPayloads carry `conversation_id`;
  `WSEventBridge` scopes broadcast by `conversation_id` (falls back to `session_id` when
  absent). — RIPPLE: locks event-tagging interface (CONTRACT LOCK).
- [ ] T18 (BT-3, REQ-6): Behavioral — slow tool mid-DER in A, switch to B, assert switch
  handler returns < 50 ms (no await on A), A's `_cancel_requested` set, A emits no further
  events post-switch, in-flight tool finishes once and writes to A's store not B's UI.
  — RIPPLE: depends on T13+T14+T15.
- [ ] T21 (BT-4, REQ-8): Behavioral — simulate WS reconnect via `sync_state{conversation_id:B}`
  while A was active with in-flight work; assert `_active_conversation_id==B`, A cancelled,
  `sync_state_ack.current_conversation_id==B`, wake-word resolves to B. — RIPPLE: depends on
  T19+T20.

## Wave 4 — Verification

- [ ] T10 (REQ-7): Verify switch logs include `session_id`, `old_conv_id`, `new_conv_id`,
  TTS-interrupt result, and cancel-requested flag (extend log at `iris_gateway.py:4334`).
  — RIPPLE: uses existing `extra={"session_id": ...}` pattern (line 718).
- [ ] T11: Run `pytest backend/tests/contract/test_voice_command_start_contract.py
  backend/tests/behavioral/test_switch_cancels_tts.py backend/tests/behavioral/test_switch_cancels_old_work.py backend/tests/behavioral/test_switch_reconnect_rebind.py backend/tests/behavioral/test_switch_tailscale_replacement.py` + new unit tests; all green.
- [ ] T12: Manual live test — in the widget, start a long response in thread A, switch to
  thread B mid-response, confirm old audio stops, no leaked "speaking"/task card in B, and
  B's UI is clean; wake-word in B responds in B. Also confirm switching is instant (no
  perceptible lag).

## Dependency / parallelization notes

- T1 is the gate — nothing else can be verified until `switch_conversation` is routed.
- T2/T3/T4/T5 are independent edits within the same handler block; can land together.
- T13/T14/T15/T16 (REQ-6) are backend-only and independent of T2-T5; can land in parallel
  with Wave 2 once T1 is committed. T14 depends on T13 (flag must exist).
- T6/T7/T8/T9/T17/T18/T23 are test-only; T7/T8 depend on T1+T2, T18 depends on T13-T15,
  T23 (Tailscale replacement) depends on T19+T20+T22.
- Switching stays INSTANT by design: T14 sets the cancel flag synchronously and returns —
  it never awaits the old loop's termination (widget responsiveness preserved).
- **Tailscale = same session, not multi-view.** Frontend connects with hardcoded
  `client_id="iris"` (`useIRISWebSocket.ts:172`), so `session_id` is always `session_iris`
  over localhost, LAN, or Tailscale. No separate Tailscale code path; the binding/cancel
  logic above automatically covers it. Only the `ws_manager.connect` reconnect-replacement
  (T22) needs a cancel hook so flipping localhost→Tailscale mid-response doesn't leave a
  stale in-flight loop.
- Frontend: `chat-view.tsx:1092` sender and `useIRISWebSocket.ts:1319` ack handler are
  NO CHANGE; only a possible small drop-gate for stale `conversation_id` on `TOOL_*`/`TASK_*`
  events (verify before assuming change needed).
- NO change to `audio/engine.py` or `agent_kernel.save_context_to_store`
  (all NO CHANGE verified in the Ripple-Effect Map). `ws_manager.py` gets a cancel hook
  (T22) but its broadcast behavior is unchanged.

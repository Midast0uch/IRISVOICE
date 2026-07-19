# Design: Session / Conversation Switching (cross-thread contamination fix)

## Context

The IRIS Voice desktop widget is a single `session_id` (the Tauri client) that can hold
many conversation threads (`conversation_id`). The user switches threads in the chat UI;
the frontend sends `switch_conversation` so the backend re-points the session at the new
thread. Today the backend's top-level dispatcher (`_route_message` / the `if/elif/else`
chain in `iris_gateway.py`) does not include `switch_conversation` in the list that
forwards to `_handle_chat`, so the message hits the `else` branch →
`WARNING: Unknown message type: switch_conversation` + an `error` response. The handler
that WOULD update `_active_conversation_id` and cancel TTS (lines 4331-4365) never runs.

Because TTS is dispatched via `broadcast_to_session(session_id, ...)` — session-scoped,
not conversation-scoped — any response still in flight when the user switches is played to
the system audio engine and shown on the orb for the SAME session, i.e. the new thread.
Result: old-thread audio leaks into the new thread and multiple TTS playbacks stack.

The fix is small and localized: make the message reachable, fix the ack payload bug, and
add a TTS interrupt on switch. No protocol change, no frontend change.

## Architecture Overview

```
Frontend (chat-view.tsx:handleSelectConversation)
   │  sendMessage('switch_conversation', {conversation_id, old_conversation_id})
   ▼
WebSocket ──► IRISGateway._route (iris_gateway.py:503 routing list)
   │  TODAY: falls to else → "Unknown message type"  ✗
   │  FIX:   add "switch_conversation" to the _handle_chat routing list
   ▼
IRISGateway._handle_chat (iris_gateway.py:4331)
   │  1. save old context (best-effort)
   │  2. engine.interrupt_speech()        ← NEW (REQ-3)
   │  3. _active_conversation_id[sid] = new_conv_id
   │  4. send conversation_switched {conversation_id: new_conv_id, status}
   ▼
Future wake-word voice_command_start → resolves to new_conv_id (REQ-2)
```

## Sequence / Data Flow

```mermaid
sequenceDiagram
    participant FE as Frontend (chat-view)
    participant WS as WebSocket
    participant GW as IRISGateway
    participant ENG as AudioEngine
    participant K as AgentKernel(old)

    FE->>WS: switch_conversation{conversation_id, old_conversation_id}
    WS->>GW: _route_message(msg)
    Note over GW: FIX: route to _handle_chat (was else→warning)
    GW->>K: save_context_to_store() (best-effort)
    GW->>ENG: interrupt_speech()  %% NEW: stop old-thread TTS
    GW->>GW: _active_conversation_id[sid] = new_conv_id
    GW-->>WS: conversation_switched{conversation_id:new_conv_id, status}
    WS-->>FE: conversation_switched (useIRISWebSocket.ts:1319)

    Note over ENG: old-thread TTS now stopped; new thread is active
    FE->>WS: (later) voice_command_start{}  %% no conversation_id
    WS->>GW: _handle_voice → resolves to _active_conversation_id[sid] = new_conv_id
```

## Data Models

- `_active_conversation_id: dict` (`iris_gateway.py:174`) — `session_id → conversation_id`.
  Mutated on `new_conversation` (line 4389) and (after fix) `switch_conversation`
  (line 4350). Read by `_handle_voice` (line 2343).
- Inbound message: `{"type": "switch_conversation", "payload": {"conversation_id": str,
  "old_conversation_id": str}}` (frontend `chat-view.tsx:1092`).
- Outbound ack: `{"type": "conversation_switched", "payload": {"conversation_id": str,
  "status": "context_saved" | "switched"}}` (contract test
  `test_voice_command_start_contract.py:128`).

## Key Decisions

1. **Route via existing `_handle_chat`, don't write a new top-level branch.** The handler
   already exists and is correct except for the ack bug. Adding `"switch_conversation"` to
   the routing list at line 503 is the minimal, lowest-risk change. Rejected alternative:
   a separate `_handle_switch_conversation` top-level `elif` — more code, duplicates the
   save/interrupt/ack logic.
2. **Interrupt TTS before re-pointing the session.** Order matters: cancel old audio while
   it is still attributed to the old thread, then flip `_active_conversation_id`. This
   guarantees the cancelled audio is never mistaken for new-thread audio.
3. **`status: "context_saved"` to match the contract test.** The existing contract test
   (`test_voice_command_start_contract.py:137`) asserts `status == "context_saved"`. We
   keep that value when the old-context save ran; use `"switched"` only when no save was
   attempted (e.g. missing old id). This keeps the contract test green without rewriting
   it.
4. **Fix the undefined `conversation_id` in the ack.** Line 4358 references
   `conversation_id`, which is not assigned in the switch branch (it is assigned later in
   the `text_message` branch at line 4403). Must use `new_conv_id`.
5. **Soft-cancel, widget-safe (REQ-6).** Switching must NEVER block. The `switch_conversation`
   handler sets a per-`conversation_id` `threading.Event` (`AgentKernel._cancel_requested`)
   on the OLD kernel — a synchronous microsecond op — and returns immediately. The old DER
   loop notices at its next step boundary (tens of ms) and exits without issuing further
   steps/TTS. This mirrors EdgeVox `InterruptController` (poll `threading.Event` between
   hops) and voiceclaw (gate stale events on a finish flag). We use SOFT cancel: an
   in-flight tool subprocess is allowed to finish once (no orphaned/killed writes), but no
    subsequent step or recovery narrative is produced for the old thread. Every bridged
    event carries `conversation_id` so the widget UI drops stale ones. Rejected alternative:
    hard-killing the worker thread or the tool subprocess — unsafe for a voice widget (could
    leave half-written files / leaked handles) and unnecessary since the loop self-exits.
6. **`sync_state` is a binding setter too (REQ-8).** The frontend sends `sync_state` with the
    resumed thread's `conversation_id` on every (re)connect, but the handler
    (`iris_gateway.py:4262`) restores the kernel WITHOUT updating `_active_conversation_id`.
    Because `_handle_request_state` (line 6168) returns that same dict as
    `current_conversation_id`, a stale binding propagates to the frontend's reconnect
    tiebreaker and a post-reconnect wake-word resolves to the wrong thread. Fix: treat
    `sync_state` as the third binding setter (alongside `switch_conversation` /
    `new_conversation`) and soft-cancel the previously-active thread when the resumed id
    differs.
7. **Tailscale is the SAME session, not multi-view.** The frontend always connects with a
    hardcoded `client_id="iris"` (`useIRISWebSocket.ts:172`), so `session_id` is always
    `session_iris` no matter the network path — localhost, LAN IP, or Tailscale
    (`100.x.x.x:8090/ws/iris`). There is therefore only ONE client per session; the
    `voice_result` relay (`iris_gateway.py:627`) and `broadcast_to_session` never fan out to
    a second physical client. Conversation history already persists in the shared store, so
    Tailscale automatically sees the same threads. The ONLY Tailscale-specific risk is the
    `ws_manager.connect` reconnect-replacement path (`ws_manager.py:63-99`): when a new
    `client_id="iris"` socket replaces a stale one (e.g. you flip localhost→Tailscale
    mid-response), the stale socket's heartbeat is cancelled but its in-flight DER loop is
    NOT — so the old loop keeps broadcasting to `session_iris` (now served by the new
    socket). That is benign for a single user (you still want the response) but the
    REQ-8 soft-cancel SHOULD also fire on reconnect-replacement when the active thread
    differs, for consistency. No separate Tailscale code path is needed.

## Ripple-Effect Map (MANDATORY — Workflow step 2)

| Area / File | Change? | Classification | Why / Evidence (file:line) |
|---|---|---|---|
| `iris_gateway.py:503` routing list | Yes | CHANGE NEEDED | Add `"switch_conversation"` so the message reaches `_handle_chat` instead of `else`. Root cause of the bug. |
| `iris_gateway.py:4331-4365` handler | Yes | CHANGE NEEDED | Add `engine.interrupt_speech()` (REQ-3); fix ack `conversation_id`→`new_conv_id` (REQ-4 AC3); set `status` per contract. |
| `iris_gateway.py:4358` ack payload | Yes | CHANGE NEEDED | `conversation_id` undefined in scope → NameError / wrong value. Use `new_conv_id`. |
| `audio/engine.py:323` `interrupt_speech()` | No | NO CHANGE (verified) | Already idempotent and safe-to-call-when-idle (called unconditionally at `iris_gateway.py:2183`). |
| `_handle_voice` resolution `iris_gateway.py:2343` | No | NO CHANGE (verified) | Already reads `_active_conversation_id.get(session_id)`; updating that dict on switch is sufficient. |
| `ws_manager.broadcast_to_session` `ws_manager.py:332` | No | NO CHANGE (verified) | Session-scoped broadcast is correct; we isolate by interrupting TTS + re-pointing, not by changing broadcast scope. |
| Frontend `chat-view.tsx:1092` sender | No | NO CHANGE (verified) | Already sends correct `{conversation_id, old_conversation_id}`. |
| Frontend `useIRISWebSocket.ts:1319` `conversation_switched` handler | No | NO CHANGE (verified) | Already reads `payload.conversation_id` and only debug-logs. |
| Contract test `test_voice_command_start_contract.py:110` | No | CONTRACT LOCK | Defines `switch_conversation`→`conversation_switched` shape + `status=="context_saved"`. Pin with CT-1 (below) so a future edit can't break the interface. |
| `agent_kernel.save_context_to_store` (called at `iris_gateway.py:4340`) | No | NO CHANGE (verified) | Best-effort save already wrapped in try/except; tolerates missing state. |
| `new_conversation` handler `iris_gateway.py:4379` | No | NO CHANGE (verified) | Same `_active_conversation_id` update pattern; switch reuses it. |
| `agent_kernel.py` DER loop (`process_text_message` :6576) | Yes | CHANGE NEEDED | Add a cancellation flag (`self._cancel_requested`) checked between DER steps; `switch_conversation` sets it on the OLD kernel instance. No such flag exists today (REQ-6 AC2). |
| `ws_event_bridge.py:112-131` | Yes | CHANGE NEEDED | Scope broadcasts by `conversation_id` when present, fall back to `session_id` only when absent (REQ-6 AC5). Today it is session-scoped only. |
| `agent_kernel.py:6642` tool-result capture | No | NO CHANGE (verified) | Already captures into `self.conversation_id` (old thread); the fix is to NOT broadcast it to the new thread (AC3/AC5), not to change capture. |
| EventBus payloads (`TOOL_RESULT`/`TASK_*`/`VALIDATION_FAILED`) | Yes | CHANGE NEEDED (CONTRACT LOCK) | Ensure `conversation_id` is present in the EventPayload `data` so the bridge can scope/drop. Pin with CT-3. |
| `sync_state` handler `iris_gateway.py:4262-4306` | Yes | CHANGE NEEDED | Restores kernel + sends `sync_state_ack` but NEVER sets `_active_conversation_id[session_id]` (REQ-8). On reconnect the session re-binds to a stale/empty thread → wake-word resolves wrong. Add the setter (same as switch/new_conversation) + soft-cancel old thread if different. |
| `_handle_request_state` `iris_gateway.py:6168` | No | NO CHANGE (verified) | Already returns `current_conversation_id: active_cid` from `_active_conversation_id`; once `sync_state` keeps that dict correct, reconnect tiebreaker (`useIRISWebSocket.ts:530`) gets the right id. |
| `voice_result` relay `iris_gateway.py:627-643` | No | NO CHANGE (verified) | Parrots transcript to all clients in the session. BUT the frontend always connects with `client_id="iris"` (hardcoded at `useIRISWebSocket.ts:172`), so `session_id` is always `session_iris` regardless of network path (localhost OR Tailscale). There is only ever ONE client per session — no multi-view. Tailscale is just a network path to the SAME session, so this relay is a no-op for cross-thread leakage. |

### Full ripple sweep (every downstream consumer — the user's "all areas need scoping")

**R1. `get_agent_kernel` call-site inconsistency → phantom `"default"` kernel (DOMINANT ripple — CHANGE NEEDED).**
`get_agent_kernel` (agent_kernel.py:8201) keys instances by `conversation_id` (line 8224);
`session_id`-only calls default `conversation_id="default"` (line 8202).

END-TO-END TRACE (both paths, verified):
- TEXT path: `chat-view.tsx:1080` → `text_message{conversation_id: activeUUID}` →
  `_handle_chat` → `get_agent_kernel(activeUUID, session_id)` (line 4276) → kernel keyed by
  `activeUUID`. ✅ real thread.
- VOICE path: `useIRISWebSocket.ts:1654` → `voice_command_start{conversation_id: cid}` →
  `_handle_voice` resolves `conversation_id` (line 2343) → `process_text_message` on
  `get_agent_kernel(conversation_id, session_id)` (line 8105) at line 2687. ✅ SAME real-thread
  kernel as text. `from_voice=True` (test_domain2_voice.py:159) only selects voice TTS/narration
  — it is ONE conversation with TWO input modalities, NOT two kernels. (User's framing confirmed:
  text + voice unify on the thread; they serve different communication roles, correctly.)

THE REAL ISSUE: ~20 `get_agent_kernel(session_id)` sites (one arg) resolve to a SEPARATE phantom
kernel `"default"` that the main thread never uses. Same `session_id=session_iris`, DIFFERENT
memory + DER loop from the active thread. CONFIRMED USER-FACING LEAKS into the phantom kernel:
- `backend/api/chat.py:305` — REST chat: `get_agent_kernel(session_id=thread_id)` → kernel
  `"default"`, but the message was saved to `thread_id` (line 302). Response generated by the
  WRONG kernel (no `thread_id` history; may write to wrong store).
- `iris_gateway.py:6873` — frontend `execute_tool` (user clicks a tool card): `get_agent_kernel(
  session_id)` → kernel `"default"`; result broadcast to active thread's UI (line 6884) but kernel
  state is `"default"`'s, not the thread's. Cross-contaminated UI.
- `iris_gateway.py:1661` — memory settings write → `"default"` kernel (lost to the active thread).
Affected (session_id-only form, MUST resolve via active thread, not `"default"`):
- `iris_gateway.py:1126, 1316, 1661, 2502, 4705, 4736, 5514, 5932, 6873, 7629, 7667, 7826, 7979`
- `iris_gateway.py:8324, 8434, 8468` (status/health — verify user-facing)
- `backend/api/chat.py:305` (REST chat — MUST use conversation_id)
- `backend/agent/status_snapshot.py:93`
- `backend/main.py:491`
OK as-is (system/singleton, not user threads): `get_agent_kernel("dev_orchestrator")`,
`("source_registry")`, `("crawl_planner")`, `("data_extractor")`, `("default")` at main.py:1553.
Correct already (conversation_id-keyed, unify text+voice): `iris_gateway.py:4276, 4339, 4391,
4419, 8105`.
→ Add Wave 5 (T23-T25): introduce `get_active_kernel(session_id)` that reads
`_active_conversation_id[session_id]` and calls `get_agent_kernel(conv_id, session_id)`; sweep
the session_id-only sites to use it so tool clicks / REST chat / settings resolve to the ACTIVE
thread's kernel (the same one text+voice already share). This eliminates the phantom `"default"`
kernel and makes text+voice+tools all serve the one conversation.

**R2. Frontend event consumers (NO CHANGE — verified, low risk).**
- `useIRISWebSocket.ts:926` `case "tool_result"` → logs only, explicitly "handled by the agent
  kernel" (no UI render, no leak).
- `useCadenceDetection.ts:60` `case "speaking"` → drives the ORB animation only (session-scoped
  visual, not thread content). TTS interrupt (REQ-3) stops it. No `conversation_id` gate needed.
- No other handler renders TOOL_*/TASK_*/agent_message content into a thread-specific view.
  So the leak surface is backend broadcast + kernel resolution, NOT the frontend.

**R3. DER loop invocation (NO CHANGE — verified, confirms cancel is feasible).**
`process_text_message` runs in a thread pool: `api/chat.py:199` `run_in_executor`, and
`iris_gateway.py:2783` `_execute_agent` via `run_in_executor(None, ...)`. So the
`_cancel_requested` flag checked between DER steps self-exits the worker thread without killing
it. Cancel is structurally sound.

**R4. Event broadcasters (NO CHANGE — verified, no bypass).**
All DER-loop events emit via `get_event_bus().emit(...)` (agent_kernel.py ~50 sites) →
`WSEventBridge` (ws_event_bridge.py:112) → `broadcast_to_session`. `conversation_kernel.py:394
_broadcast_narration` uses the SAME wired `broadcast_to_session` callable (line 398). No separate
broadcaster bypasses WSEventBridge for tool/task/agent events, so scoping at WSEventBridge (REQ-6
AC5) covers all of them.

**R5. Memory / store write on cancel (NO CHANGE — verified, but note).**
`save_context_to_store` (called at iris_gateway.py:4340 on switch, and at DER completion) writes
to the kernel's OWN `conversation_id` store. A cancelled loop exits BEFORE the final save (it
checks the flag between steps), so it cannot half-write the wrong thread. The in-flight tool
result (SOFT cancel) is captured into the OLD kernel's `self.conversation_id` (agent_kernel.py:6642)
and written to the OLD store — correct, not leaked. No change needed; documented so a future
edit doesn't move the save before the flag check.

## Structural Guarantees (how isolation is actually enforced)

The behavioral fixes are only safe if the underlying organization is sound. Verified
against code:

- **SG-1 — One kernel per conversation is the real isolation boundary.** `get_agent_kernel`
  (`agent_kernel.py:8201`) is keyed on `conversation_id` (line 8224: `if conversation_id not
  in _agent_kernel_instances`). Each thread has its OWN `AgentKernel` (own memory, own DER
  loop, own cancel flag). Switching does NOT share a kernel — isolation is structural.
  `_active_conversation_id` is only the session→conversation *pointer*; the kernel registry
  is the isolation.
- **SG-2 — Two uncoordinated session registries exist.** `_active_conversation_id`
  (`iris_gateway.py:174`, session→conversation pointer) and `coupled_registry._sessions`
  (`coupled_registry.py:93`, Caducean physics per `session_id`). The switch handler updates
  the first and cancels the old kernel (SG-1); the second is keyed by `session_id` so for a
  single user on `session_iris` it holds no cross-thread state (verified benign, NO CHANGE).
  Documented so a future multi-session feature doesn't regress.
- **SG-3 — `get_agent_kernel` call-site consistency is a latent risk.** Called four ways:
  `get_agent_kernel(session_id)` (many sites → resolves to `conversation_id = session_id`,
  line 8222, a DIFFERENT key), `get_agent_kernel(conversation_id, session_id)` (correct
  per-thread), `get_agent_kernel(conversation_id="default")`, and hardcoded singletons
  (`"dev_orchestrator"`, `"crawl_planner"`). Any user-message path MUST use the
  `conversation_id`-keyed form or it can resolve to the wrong kernel. The switch fix must not
  widen this.
- **SG-4 — Cancel state is net-new structure built by this spec.** `AgentKernel._cancel_requested`
  does not exist today (REQ-6 adds it). It is initialized per-kernel in `__init__` and checked
  at every DER step boundary, so cancellation is a property of the kernel (SG-1), not the
  gateway dict.

## Error Handling

- **Malformed / empty `conversation_id`**: handler treats as no-op for the dict update
  (REQ-2 AC3); still acks. No crash.
- **Audio engine not initialized**: `interrupt_speech()` wrapped in try/except,
  non-fatal (mirrors `iris_gateway.py:2082`).
- **Old-context save fails**: warning logged, switch continues (existing try/except at
  line 4338).
- **Ack send fails**: swallowed by existing try/except at line 4363.
- **Outer dispatcher exception** (`iris_gateway.py:735`): still catches any unexpected
  error and sends `error` — but with the fix the message no longer reaches `else`.

## Testing Strategy

Organized as `tests/contract` (boundary pins) + `tests/behavioral` (full-loop) +
`tests/unit` (pure logic). The standing CDD harness replays recorded switch trajectories.

### Contract tests (CT)
- **CT-1** (`tests/contract/test_voice_command_start_contract.py`, extend existing
  `TestSwitchConversationContract`): assert `switch_conversation` → `conversation_switched`
  with `payload.conversation_id == new_conv_id` and `status == "context_saved"`. Locks the
  interface shape (CONTRACT LOCK above).
- **CT-2** (new, `tests/contract/`): assert the dispatcher routes `switch_conversation` to
  `_handle_chat` (i.e. no `Unknown message type` warning, no `error` response). Mock
  `_ws_manager` and capture sent messages.
- **CT-3** (REQ-6 AC3/AC5, CONTRACT LOCK): assert that `TOOL_RESULT` / `TOOL_CALL` /
  `TOOL_ERROR` / `TASK_*` / `VALIDATION_FAILED` EventPayloads emitted by the DER loop carry
  `conversation_id` in `data`, and that `WSEventBridge` scopes the broadcast by
  `conversation_id` when present (falls back to `session_id` only when absent). Locks the
  event-tagging interface so a future edit can't silently re-leak old-thread events.

### Behavioral tests (BT)
- **BT-1** (`tests/behavioral/`): drive a full flow — start a voice command in thread A,
  let a TTS response begin, send `switch_conversation` to thread B, assert (a) TTS
  interrupted, (b) `_active_conversation_id[sid] == B`, (c) a subsequent wake-word
  `voice_command_start` resolves to B, (d) no `conversation_switched` for the wrong id.
- **BT-2**: rapid A→B→A double-switch; assert final binding is A and both acks sent with
  correct ids.
- **BT-3** (REQ-6, soft-cancel): start a long DER run in thread A (inject a slow tool so
  the loop is mid-step), send `switch_conversation` to B, assert (a) the switch handler
  returns immediately (no await on A's termination — measure latency < 50 ms), (b) A's
  `AgentKernel._cancel_requested` is set, (c) A's loop emits NO further `TOOL_*`/`TASK_*`/
  `agent_message` events after the switch, (d) any event A does emit carries
  `conversation_id == A` and the frontend/bridge drops it for active thread B, (e) an
  in-flight tool call that was already running at switch time is allowed to finish once
  (SOFT cancel) and its result is written to A's store, not B's UI.
- **BT-4** (REQ-8, reconnect re-bind): simulate a WS reconnect — send `sync_state` with
  `conversation_id == B` while thread A was the prior active binding (and A has in-flight
  work), assert (a) `_active_conversation_id[sid] == B`, (b) A's `_cancel_requested` is set
  (old thread cancelled on re-bind to a different thread), (c) `sync_state_ack` carries
  `current_conversation_id == B`, (d) a subsequent wake-word `voice_command_start` resolves
  to B, not A.

### Unit tests (UT)
- **UT-1**: `_handle_chat` with `switch_conversation` and missing `conversation_id` →
  dict unchanged, ack still sent (no NameError).
- **UT-2**: `interrupt_speech` called exactly once on switch when engine present; zero
  times when engine absent (mock engine).

### Standing CDD harness
- Extend `scripts/validate_der_*.py` family (or add `scripts/validate_switch_*.py`) to
  replay a recorded A-then-switch-to-B trajectory through the full stack and assert the
  contracts + behaviors above on every run.

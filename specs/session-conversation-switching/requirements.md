# Requirements: Session / Conversation Switching (cross-thread contamination fix)

## Decisions Locked

- **Switching MUST cancel in-flight TTS.** When the user switches conversation threads,
  any TTS audio currently playing from the OLD thread must be interrupted immediately
  (`engine.interrupt_speech()`). The user explicitly reported "multiple TTS playbacks
  stack" — letting old audio finish is not acceptable.
- **Backend owns the binding.** The backend is the single source of truth for which
  `conversation_id` a `session_id` is currently pointed at (`_active_conversation_id`).
  The frontend already sends `switch_conversation` with both `conversation_id` and
  `old_conversation_id`; the backend must honor it, not ignore it.
- **No new message types required.** The contract already exists: frontend sends
  `switch_conversation`, backend replies `conversation_switched`. We fix the routing gap
  and the ack payload, we do NOT invent a new protocol.
- **Wake-word path must follow the switch.** `_handle_voice` falls back to
  `_active_conversation_id[session_id]` when a `voice_command_start` carries no
  `conversation_id`. Updating that dict on switch is what keeps a wake-word response
  from landing in the OLD thread. This is already partially coded in `_handle_chat` —
  it just never runs because the message never arrives there.

## Structural Guarantees (how isolation is actually enforced)

The behavioral requirements above are only safe if the underlying organization is sound.
This section makes the structure explicit and locks it in. All claims are traced to code.

- **SG-1: One kernel per conversation is the real isolation boundary.** `get_agent_kernel`
  (`agent_kernel.py:8201`) is keyed on `conversation_id` (line 8224: `if conversation_id not
  in _agent_kernel_instances`). Each thread therefore has its OWN `AgentKernel` instance with
  its OWN memory, DER loop, and (once added) cancel flag. Switching threads does NOT share a
  kernel — isolation is structural, not just a pointer swap. THE SPEC SHALL treat the
  per-`conversation_id` kernel as the canonical isolation unit; `_active_conversation_id` is
  only the session→conversation *pointer*, not the isolation itself.
- **SG-2: A single canonical session registry MUST own the binding + cancel state.** Today the
  binding lives in `iris_gateway._active_conversation_id: dict` (`iris_gateway.py:174`) and a
  SEPARATE `coupled_registry.CoupledTrajectoryRegistry._sessions` (`coupled_registry.py:93`)
  tracks Caducean physics per `session_id`. These are two uncoordinated registries. THE SPEC
  SHALL NOT introduce a third; the switch handler SHALL update `_active_conversation_id` AND
  set the cancel flag on the OLD `conversation_id`'s kernel (SG-1), and SHALL verify
  `coupled_registry` holds no per-conversation state that survives a switch (it is keyed by
  `session_id`, so for a single user on `session_iris` it is benign — verified, no change
  needed, but documented so a future multi-session feature doesn't regress).
- **SG-3: `get_agent_kernel` call sites MUST be consistent.** The code calls it four ways:
  `get_agent_kernel(session_id)` (many sites), `get_agent_kernel(conversation_id, session_id)`
  (correct per-thread form), `get_agent_kernel(conversation_id="default")`, and hardcoded
  singleton names (`"dev_orchestrator"`, `"crawl_planner"`). THE SPEC SHALL require that any
  path that handles a user message uses the `conversation_id`-keyed form so it resolves to the
  correct thread's kernel; the `session_id`-only form resolves to `conversation_id = session_id`
  (line 8222) which is a DIFFERENT key and can return the wrong kernel. This is a latent
  contamination risk the switch fix must not widen.
- **SG-4: Cancel state is net-new structure, built by this spec.** `AgentKernel._cancel_requested`
  does not exist today (REQ-6 adds it). THE SPEC SHALL guarantee it is initialized per-kernel
  in `AgentKernel.__init__` and checked at every DER step boundary, so cancellation is a
  property of the kernel (SG-1), not of the gateway dict.

## Introduction

The frontend sends a `switch_conversation` WebSocket message whenever the user selects a
different conversation thread. The backend's `_handle_chat` method contains a correct
handler for it, but the top-level message dispatcher never routes `switch_conversation`
to `_handle_chat` — it falls through to the `else` branch and logs
`WARNING: Unknown message type: switch_conversation`, then sends an error back. As a
result the backend's `_active_conversation_id[session_id]` is never updated and any
in-flight TTS/response from the old thread is broadcast to the same `session_id` and
played by the system audio engine, contaminating the new thread. This spec fixes the
routing gap, the ack payload bug, and adds TTS cancellation on switch so threads stay
isolated.

### Success criteria

- `switch_conversation` is routed to its handler (no "Unknown message type" warning).
- On switch, `_active_conversation_id[session_id]` is updated to the new thread.
- On switch, any in-flight TTS audio from the old thread is interrupted.
- The backend replies `conversation_switched` with the correct `conversation_id`.
- A wake-word utterance immediately after switching targets the NEW thread.
- No old-thread TTS/state leaks into the new thread's UI.

## Requirements

### REQ-1: Route `switch_conversation` to its handler
**User Story:** As a user switching threads I want the backend to actually process my
switch request so that my session state follows me.

**Verified:** `backend/iris_gateway.py:503` — routing list is
`["text_message", "clear_chat", "new_conversation"]` and does NOT include
`switch_conversation`; handler exists at `backend/iris_gateway.py:4331` but is unreachable.

**Acceptance Criteria:**
- AC1: WHEN a WebSocket message of `type == "switch_conversation"` is received THEN THE
  SYSTEM SHALL dispatch it to `_handle_chat` (the same path as `text_message` /
  `new_conversation`).
- AC2: IF `switch_conversation` is received THEN THE SYSTEM SHALL NOT log
  `Unknown message type: switch_conversation` nor send an `error` response.
- AC3: THE SYSTEM SHALL keep `switch_conversation` out of the `else` fall-through branch.

**Edge Cases:**
- `conversation_id` missing in payload → treat as no-op switch, still ack (no crash).
- `old_conversation_id` missing → fall back to `session_id` (already coded at line 4333).
- Malformed payload (not a dict) → caught by the existing outer `except` at line 735.

### REQ-2: Update active conversation binding on switch
**User Story:** As a user switching threads I want future voice/wake-word responses to
land in the thread I'm now looking at, not the one I left.

**Verified:** `backend/iris_gateway.py:4350` — `self._active_conversation_id[session_id] =
new_conv_id` exists inside the (unreachable) handler; `_handle_voice` reads this dict at
`backend/iris_gateway.py:2343` (`result.get("conversation_id") or
self._active_conversation_id.get(session_id)`).

**Acceptance Criteria:**
- AC1: WHEN `switch_conversation` is processed with a non-empty `conversation_id` THEN THE
  SYSTEM SHALL set `_active_conversation_id[session_id] = conversation_id`.
- AC2: WHILE a wake-word `voice_command_start` arrives with no `conversation_id` THEN THE
  SYSTEM SHALL resolve the conversation to the value set by the most recent
  `switch_conversation` for that `session_id`.
- AC3: IF `conversation_id` is empty/None THEN THE SYSTEM SHALL leave
  `_active_conversation_id[session_id]` unchanged.

**Edge Cases:**
- Rapid double-switch (A→B then B→A within ms) → final dict value is the last message's
  `conversation_id`; both acks sent.
- Switch to a thread that has no kernel yet → `get_agent_kernel` lazily creates one
  (verified pattern at `backend/iris_gateway.py:4391`).

### REQ-3: Cancel in-flight TTS on switch
**User Story:** As a user switching threads I want the old thread's half-spoken response
to stop so it doesn't bleed into the new thread.

**Verified:** `backend/audio/engine.py:323` — `interrupt_speech()` exists and is
idempotent (called unconditionally-safe at `backend/iris_gateway.py:2183`); TTS is
dispatched via `broadcast_to_session(session_id, ...)` (`backend/iris_gateway.py:3003`)
which is session-scoped, not conversation-scoped — so old-thread audio reaches the same
session the new thread lives in.

**Acceptance Criteria:**
- AC1: WHEN `switch_conversation` is processed THEN THE SYSTEM SHALL call
  `engine.interrupt_speech()` to stop any TTS currently playing for the old thread.
- AC2: IF the audio engine is not initialized THEN THE SYSTEM SHALL swallow the exception
  (non-fatal, same pattern as `backend/iris_gateway.py:2082`).
- AC3: THE SYSTEM SHALL perform the interrupt BEFORE updating `_active_conversation_id` so
  the cancelled audio is attributed to the old thread.

**Edge Cases:**
- No TTS playing at switch time → `interrupt_speech()` is a no-op (idempotent).
- TTS queued but not yet started → interrupt flag consumed by `_speak_response` loop
  (verified at `backend/iris_gateway.py:2074-2082` comment).

### REQ-4: Acknowledge switch with correct payload
**User Story:** As the frontend I want a well-formed `conversation_switched` ack so I can
confirm the switch and avoid retrying.

**Verified:** `backend/iris_gateway.py:4353-4362` — ack sends
`{"type": "conversation_switched", "payload": {"conversation_id": conversation_id,
"status": "switched"}}` but `conversation_id` is UNDEFINED in this scope (NameError risk /
wrong value) — should be `new_conv_id`. Frontend handler at
`hooks/useIRISWebSocket.ts:1319` reads `payload.conversation_id`. Contract test
`backend/tests/contract/test_voice_command_start_contract.py:126` expects
`status == "context_saved"`.

**Acceptance Criteria:**
- AC1: WHEN `switch_conversation` is processed THEN THE SYSTEM SHALL send
  `conversation_switched` with `payload.conversation_id == new_conv_id`.
- AC2: THE SYSTEM SHALL set `payload.status` to `"context_saved"` (matching the existing
  contract test at `test_voice_command_start_contract.py:137`) after the old context
  save attempt, or `"switched"` if no save was attempted.
- AC3: THE SYSTEM SHALL NOT reference an undefined variable in the ack payload (fix the
  `conversation_id` → `new_conv_id` bug at line 4358).

**Edge Cases:**
- Old-context save fails → still ack `switched` (save is best-effort, already wrapped in
  try/except at line 4338).
- Send fails → swallowed by existing try/except at line 4363.

### REQ-5: Persist old-thread context on switch
**User Story:** As a user switching away I want my old thread's running context saved so
returning to it resumes correctly.

**Verified:** `backend/iris_gateway.py:4338-4344` — `get_agent_kernel(old_conv_id,
session_id).save_context_to_store()` already coded (best-effort, wrapped).

**Acceptance Criteria:**
- AC1: WHEN `switch_conversation` is processed THEN THE SYSTEM SHALL attempt to save the
  OLD conversation's context to the store before switching.
- AC2: IF the save raises THEN THE SYSTEM SHALL log a warning and continue (non-fatal).

**Edge Cases:**
- Old kernel not found → `get_agent_kernel` creates one; save is a no-op for empty
  context (verify `save_context_to_store` tolerates missing state).

### REQ-6: Cancel in-flight old-thread work + isolate its events (soft-cancel, widget-safe)
**User Story:** As a user switching threads in a hands-free widget I want any still-running
agent work from the thread I left — including failed-tool recovery, task updates, and
validation events — to STOP cleanly and never appear in the thread I switched to, WITHOUT
the switch itself ever blocking or feeling laggy.

**Verified:** `backend/agent/ws_event_bridge.py:112-131` — `WSEventBridge` forwards
`TOOL_RESULT`, `TOOL_CALL`, `TOOL_ERROR`, `TASK_*`, `VALIDATION_FAILED`, `RECOVERY_START`,
`TOPOLOGY_RECOVERY` via `broadcast_to_session(session_id, msg)` — **session-scoped, NOT
conversation-scoped**. `backend/agent/agent_kernel.py:6576` — the DER loop calls
`tool_decision.dispatch()` inside `process_text_message` and runs to completion; there is
**NO per-conversation cancellation token** (grep for `_cancel`/`_abort`/`should_stop` in
agent_kernel.py returns nothing for the DER loop). `process_text_message` runs in a thread
pool executor (`backend/api/chat.py:199` and the WS path), so a flag checked between steps
cancels it without killing the worker thread. So a failed tool in thread A triggers DER
recovery that keeps emitting events to the SAME session after the user switches to B.
`backend/agent/agent_kernel.py:6642` captures tool results into `self.conversation_id`
(old thread) but the *broadcast* is session-scoped, so the new thread's UI still receives
them.

**Design basis (industry pattern, verified via research):** EdgeVox `InterruptController`
uses a `threading.Event` (`interrupted`/`cancel_token`) polled between agent hops;
voiceclaw drops stale events after cancel by gating every message branch on a `didFinish`
flag; Ably/trpc cancel is **per-run/per-thread** and SOFT — in-flight tool calls finish
once, no further steps issued. We adopt the same: a per-`conversation_id` cancel
`threading.Event` on `AgentKernel`, checked at DER step boundaries, plus `conversation_id`
tagging on every bridged event so the widget UI drops stale ones.

**Acceptance Criteria:**
- AC1: WHEN `switch_conversation` is processed THEN THE SYSTEM SHALL set the OLD
  conversation's `AgentKernel` cancel event (`self._cancel_requested.set()`) — a
  synchronous, microsecond operation that does NOT await the old loop's termination, so the
  switch returns immediately (widget stays responsive).
- AC2: THE SYSTEM SHALL provide a cancellation `threading.Event` on `AgentKernel`
  (`self._cancel_requested`) that `process_text_message` and the DER loop poll between
  steps; when set, the loop exits cleanly after the current step, issuing NO further tool
  calls, recovery steps, or TTS for that conversation.
- AC3: WHEN an event from the cancelled old thread is nonetheless emitted THEN THE SYSTEM
  SHALL carry `conversation_id` in the EventPayload `data` so the frontend drops any event
  whose `conversation_id` != the active thread (mirrors voiceclaw's `didFinish` gate).
- AC4: IF a tool call is already executing at switch time THEN THE SYSTEM SHALL let that
  single in-flight call finish (SOFT cancel — do not kill a running subprocess mid-action)
  but MUST NOT dispatch any SUBSEQUENT step or recovery narrative for the old thread.
- AC5: THE SYSTEM SHALL scope `WSEventBridge` broadcasts by `conversation_id` when present
  in the payload, falling back to `session_id` only when `conversation_id` is absent
  (preserves single-user broadcast for legacy events).
- AC6: THE SYSTEM SHALL treat the cancel as per-conversation, not per-session — switching A→B
  cancels A's work only; any other in-flight conversation is untouched. THE SAME cancel
  SHALL apply when the user starts a `new_conversation` or `clear_chat` while old work is
  in flight (the old thread's DER loop must be cancelled before the new/clear context takes
  effect), so a cleared thread cannot keep emitting events into the fresh one.

**Edge Cases:**
- Old kernel not yet created (no in-flight work) → `set()` on a missing kernel is a no-op.
- Switch arrives between DER steps (not mid-tool) → loop checks flag at next step boundary
  and exits within one step (tens of ms).
- A tool subprocess is long-running at switch → allowed to finish once; its result is
  captured into the OLD conversation's memory but NOT broadcast to the new thread's UI
  (AC3/AC5 drop it). No orphaned writes — the result lands in the correct old thread's store.
- Rapid A→B→A → only the latest switch's old thread (B) is cancelled; re-entering A starts a
  FRESH `process_text_message` (the previously-cancelled A instance already exited).
- Switch while NO work is in flight → pure re-point + ack, sub-millisecond.

### REQ-8: Re-bind active conversation on `sync_state` (reconnect / resume)
**User Story:** As a user whose widget reconnected (WS drop, sleep/resume, app restart) I
want the backend to re-point the session at the thread I was actually looking at, not a
stale or empty one.

**Verified:** `backend/iris_gateway.py:4262-4306` — the `sync_state` handler restores the
kernel for `payload.conversation_id` and sends `sync_state_ack`, but it does NOT set
`self._active_conversation_id[session_id]`. The frontend sends `sync_state` with the
resumed thread's `conversation_id` on every (re)connect (`hooks/useIRISWebSocket.ts:436`)
and its own comment at `useIRISWebSocket.ts:524` states the backend "owns
`_active_conversation_id` per session (set on new_conversation / switch_conversation)" —
`sync_state` is the THIRD setter and is missing. Worse, `_handle_request_state`
(`iris_gateway.py:6168`) returns `current_conversation_id: active_cid` from that same dict,
so a stale `_active_conversation_id` propagates to the frontend's reconnect tiebreaker
(`useIRISWebSocket.ts:530`) and a post-reconnect wake-word resolves to the wrong thread.

**Tailscale note (verified):** The frontend connects with a hardcoded `client_id="iris"`
(`useIRISWebSocket.ts:172`), so `session_id` is ALWAYS `session_iris` regardless of network
path — localhost, LAN IP, or Tailscale (`ws://100.x.x.x:8090/ws/iris`). Tailscale is
therefore the SAME session as localhost, not a second client: same `_active_conversation_id`,
same in-flight DER loop, same conversation history (shared store). No separate Tailscale code
path is required; the binding/cancel logic above automatically covers Tailscale. The only
Tailscale-specific risk is the `ws_manager.connect` reconnect-replacement
(`ws_manager.py:63-99`): a new `client_id="iris"` socket replacing a stale one cancels the
old heartbeat but NOT the old socket's in-flight DER loop — see AC5.

**Acceptance Criteria:**
- AC1: WHEN a `sync_state` message carries a non-empty `payload.conversation_id` THEN THE
  SYSTEM SHALL set `_active_conversation_id[session_id] = payload.conversation_id` (same as
  the `switch_conversation` / `new_conversation` setters).
- AC2: IF `payload.conversation_id` is empty/None THEN THE SYSTEM SHALL leave
  `_active_conversation_id[session_id]` unchanged (do not clobber a valid binding with
  empty).
- AC3: THE SYSTEM SHALL apply the REQ-6 soft-cancel to the PREVIOUSLY-active thread when
  `sync_state` re-binds to a different `conversation_id` (a reconnect that resumes a
  different thread than was active must not let the old thread's in-flight work leak).
- AC4: THE SYSTEM SHALL include `current_conversation_id` in the `sync_state_ack` payload so
  the frontend can confirm the binding matches (already returned by `request_state` at
  `iris_gateway.py:6168`; mirror it here for symmetry).
- AC5: WHEN a new `client_id="iris"` WebSocket replaces a stale socket via
  `ws_manager.connect` (`ws_manager.py:63-99`) AND the active thread differs from the
  resumed `sync_state` thread THEN THE SYSTEM SHALL apply the REQ-6 soft-cancel to the
  previously-active thread (covers flipping localhost→Tailscale mid-response). If the active
  thread is the SAME, no cancel is needed (the user still wants that response).

**Edge Cases:**
- Reconnect with same thread as before → binding unchanged, no cancel.
- Reconnect resumes thread B but old thread A had in-flight work → A cancelled (AC3), B
  active.
- `sync_state` arrives before any `switch_conversation` (cold start) → sets initial binding.
- Multiple rapid reconnects → final `conversation_id` wins; each re-bind cancels the prior
  active thread's work if different.

### REQ-9: Observability for switch events
**User Story:** As the tuner I want timestamped, session-scoped logs of every switch so I
can confirm threads never contaminate each other.

**Verified:** NEW — logging already present at `backend/iris_gateway.py:4334` but should
include old→new ids and TTS-interrupt result.

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log each `switch_conversation` with `session_id`, `old_conv_id`,
  `new_conv_id`, and whether TTS was interrupted.
- AC2: THE SYSTEM SHALL scope the log line with `session_id` (consistent with the existing
  `extra={"session_id": ...}` pattern at line 718).

**Edge Cases:**
- High-frequency switching → logs are cheap string formats, off the TTS hot path.

## Non-Requirements (Out of Scope)

- Changing the frontend `switch_conversation` sender (already correct at
  `components/chat-view.tsx:1092`).
- Changing the `conversation_switched` frontend handler (already correct at
  `hooks/useIRISWebSocket.ts:1319`).
- Multi-session / multi-client conversation isolation beyond the single `session_id`
  model (Tailscale multi-view is a separate concern; `voice_result` relay at line 636 is
  untouched).
- Persisting switch history to disk / analytics.

## Open Questions

- None blocking. All decisions locked above.

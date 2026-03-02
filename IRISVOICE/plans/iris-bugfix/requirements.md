# IRIS Bug Fix Requirements

## Overview
This specification addresses 9 critical and medium-priority bugs identified in the IRIS codebase that prevent proper voice state synchronization, WebSocket message delivery, and stable UI behavior.

## Bug Classification

### Critical Bugs (Blocking)

#### BUG-01/08: NavigationContext Reload Loop
**Severity:** Critical  
**Component:** Frontend - NavigationContext.tsx

**Expected Behavior:**
- Navigation state should restore from localStorage once on mount
- State persistence should be stable and not trigger reload loops
- Animation transitions should not trigger persistence effects

**Actual Behavior:**
- Init useEffect dispatches RESTORE_STATE twice (lines 587 and 628)
- Second dispatch spreads stale closure (`...state` captures initial state, not restored state)
- Persist effects run on every state change including animation transitions (lines 643-677)

**Acceptance Criteria:**
- [ ] State restoration happens exactly once on mount
- [ ] No stale closure in second RESTORE_STATE dispatch
- [ ] Persist effects only run on meaningful state changes (exclude `isTransitioning`, `transitionDirection`)

---

#### BUG-02: WebSocket Event Bridge Incomplete
**Severity:** Critical  
**Component:** Frontend - useIRISWebSocket.ts, SidePanel.tsx

**Expected Behavior:**
- `iris:initial_state` event should be dispatched when backend sends initial state
- `iris:available_models`, `iris:audio_devices`, `iris:wake_words_list` events should be dispatched
- SidePanel should receive initial state and populate field values

**Actual Behavior:**
- SidePanel listens for `iris:initial_state` event (lines 90, 108)
- useIRISWebSocket dispatches some events but NOT `iris:initial_state`
- The event bridge between WebSocket messages and CustomEvents is incomplete

**Acceptance Criteria:**
- [ ] `initial_state` WebSocket message dispatches `iris:initial_state` CustomEvent
- [ ] `available_models` WebSocket message dispatches `iris:available_models` CustomEvent
- [ ] `audio_devices` WebSocket message dispatches `iris:audio_devices` CustomEvent
- [ ] `wake_words_list` WebSocket message dispatches `iris:wake_words_list` CustomEvent
- [ ] SidePanel receives `iris:initial_state` and populates field values correctly

---

#### BUG-03: Backend Voice Callbacks Never Awaited
**Severity:** Critical  
**Component:** Backend - iris_gateway.py, voice_pipeline.py

**Expected Behavior:**
- Voice state changes should broadcast to frontend via WebSocket
- Audio level updates should reach frontend
- Callbacks should be properly awaited

**Actual Behavior:**
- `_handle_voice` (line 436) registers callbacks using sync lambdas that call async methods
- Lambda `lambda state: self._on_voice_state_change(session_id, state)` returns coroutine but nothing schedules/awaits it
- `voice_pipeline.py` line 284-287 checks `asyncio.iscoroutinefunction(callback)` which returns `False` for lambdas wrapping async calls
- Voice state transitions never broadcast to frontend

**Acceptance Criteria:**
- [ ] Callback lambdas properly await async methods OR use bound method references
- [ ] Voice state changes reach frontend within 100ms
- [ ] Audio level updates reach frontend in real-time

---

#### BUG-07: SidePanel Reads Wrong State Key
**Severity:** Critical  
**Component:** Frontend - SidePanel.tsx

**Expected Behavior:**
- SidePanel should lookup field values using Section IDs (snake_case like 'inference_mode')
- Field values should populate from backend state

**Actual Behavior:**
- Lines 96-104: Uses `miniNode.id` (Card ID like 'inference-card') to lookup field values
- Backend stores under Section IDs (snake_case like 'inference_mode')
- Card ID to Section ID mapping exists in CARD_TO_SECTION_ID but is not used

**Acceptance Criteria:**
- [ ] SidePanel uses CARD_TO_SECTION_ID mapping for state lookups
- [ ] Field values populate correctly from backend state

---

### Medium Bugs (Stability)

#### BUG-04: IrisOrb Stale Closure on Double-Click
**Severity:** Medium  
**Component:** Frontend - IrisOrb.tsx

**Expected Behavior:**
- Double-click handler should have stable reference
- `useManualDragWindow` should not receive new inline function on every render

**Actual Behavior:**
- Lines 227-239: `useManualDragWindow` receives inline arrow function for double-click
- Function not memoized, new object every render
- Hook captures via `useCallback` but not in dependency array

**Acceptance Criteria:**
- [ ] Double-click handler is memoized with `useCallback`
- [ ] Handler reference is stable across renders
- [ ] `useManualDragWindow` receives stable callback reference

---

#### BUG-05: Voice Toggle Uses REST Instead of WebSocket
**Severity:** Medium  
**Component:** Frontend - card-ring.tsx (to be created)

**Expected Behavior:**
- Voice toggle should use WebSocket session path
- State changes should propagate through proper WebSocket session

**Actual Behavior:**
- File doesn't exist yet (part of restructuring)
- When created, needs to use WebSocket not REST API

**Acceptance Criteria:**
- [ ] Voice toggle uses `sendMessage('voice_command_start', {})` / `sendMessage('voice_command_end', {})`
- [ ] No REST API calls for voice state changes
- [ ] Proper error handling for WebSocket failures

---

#### BUG-09: Wake Word Callback Re-Registers on Voice State Change
**Severity:** Medium  
**Component:** Frontend - IrisOrb.tsx

**Expected Behavior:**
- Wake word callback should register once on mount
- Callback should not re-register on every voice state change

**Actual Behavior:**
- Lines 257-264: `onCallbacksReady` effect depends on `handleWakeDetected`
- Line 245-248: `handleWakeDetected` depends on `isListening`
- Every voice state change recreates callback and re-registers

**Acceptance Criteria:**
- [ ] Callback registration only happens once
- [ ] Wake detection uses stable callback reference
- [ ] No unnecessary re-registration on state changes

---

## Implementation Order (Dependency-Ordered)

1. **BUG-01/08** → Stops reload loop, makes everything testable
2. **BUG-03** → Backend voice state now propagates
3. **BUG-02** → Frontend starts receiving backend messages
4. **BUG-06** → Field changes reach backend (already fixed - verify)
5. **BUG-07** → Field values populate in SidePanel
6. **BUG-05** → Voice toggle through proper session path
7. **BUG-04/09** → Voice UX stable

## Testing Requirements

- Unit tests for NavigationContext state restoration
- Integration tests for WebSocket event dispatching
- Backend async callback tests
- SidePanel state lookup tests
- IrisOrb callback stability tests

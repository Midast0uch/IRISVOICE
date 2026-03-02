# Integration Gaps - Requirements

## Overview

This specification addresses 12 critical integration gaps between the IRIS backend (Python/FastAPI) and frontend (Next.js/TypeScript) that prevent proper message routing, state synchronization, and resource management.

## Critical Gaps

### GAP-01: Dual Message Routing System
**Severity:** Critical  
**Component:** Backend - main.py, iris_gateway.py

**Current Behavior:**
- Two separate message handling systems exist simultaneously
- `main.py` has `handle_message()` function (lines 305-498)
- `iris_gateway.py` has `IRISGateway.handle_message()` method (lines 57-181)
- Messages are routed inconsistently, causing race conditions

**Expected Behavior:**
- Single, unified message routing system
- All messages route through one handler
- No duplicate processing or race conditions

#### Acceptance Criteria
1. WHEN a WebSocket message is received THE SYSTEM SHALL route it through a single handler
2. IF duplicate message handlers exist THEN THE SYSTEM SHALL consolidate them into iris_gateway.py
3. THE SYSTEM SHALL ensure no message type is handled by both main.py and iris_gateway.py
4. WHEN main.py receives a message THE SYSTEM SHALL delegate to iris_gateway.py

---

### GAP-02: Mismatched Message Types
**Severity:** Critical  
**Component:** Frontend/Backend - NavigationContext.tsx, main.py, iris_gateway.py

**Current Behavior:**
| Frontend Sends | Backend Listens For | Match |
|----------------|---------------------|-------|
| `select_category` | `set_category` (main.py:314) | ❌ |
| `select_subnode` | `set_subnode` (main.py:320) | ❌ |
| `go_back` | `go_back` (main.py:324) | ✅ |
| `expand_to_main` | `expand_to_main` (main.py:357) | ❌ |

**Expected Behavior:**
- Frontend message types match backend handler expectations
- Consistent naming convention across codebase

#### Acceptance Criteria
1. WHEN frontend sends `select_category` THE SYSTEM SHALL handle it in backend
2. WHEN frontend sends `select_subnode` THE SYSTEM SHALL handle it in backend
3. THE SYSTEM SHALL use consistent message type naming (`select_*` not `set_*`)
4. IF backend receives unknown message type THEN THE SYSTEM SHALL log appropriate error

---

### GAP-03: Missing WebSocket Event Dispatches
**Severity:** High  
**Component:** Frontend - useIRISWebSocket.ts

**Current Behavior:**
- SidePanel listens for: `iris:initial_state`, `iris:available_models`, `iris:audio_devices`, `iris:wake_words_list`
- Missing dispatches: `iris:voice_state_change`, `iris:field_updated`

**Expected Behavior:**
- All events SidePanel listens for are dispatched via CustomEvent
- Components receive real-time updates for voice state and field changes

#### Acceptance Criteria
1. WHEN voice state changes THE SYSTEM SHALL dispatch `iris:voice_state_change` CustomEvent
2. WHEN field is updated THE SYSTEM SHALL dispatch `iris:field_updated` CustomEvent
3. THE SYSTEM SHALL include current state in event detail payload
4. IF window is undefined (SSR) THEN THE SYSTEM SHALL skip dispatch safely

---

### GAP-04: Backend Sends Messages Frontend Doesn't Handle
**Severity:** High  
**Component:** Frontend - useIRISWebSocket.ts

**Current Behavior:**
Backend sends these types without frontend handlers:
- `subnodes` (iris_gateway.py:214)
- `model_selection_updated` (iris_gateway.py:764)
- `wake_word_selected` (iris_gateway.py:1047)
- `cleanup_report` (iris_gateway.py:1141)
- `cleanup_result` (iris_gateway.py:1203)
- `category_expanded` (main.py:359)

**Expected Behavior:**
- All backend message types have corresponding frontend handlers
- Or unused types are removed from backend

#### Acceptance Criteria
1. WHEN backend sends `subnodes` message THE SYSTEM SHALL handle it in frontend
2. WHEN backend sends `model_selection_updated` THE SYSTEM SHALL handle it in frontend
3. WHEN backend sends `wake_word_selected` THE SYSTEM SHALL handle it in frontend
4. IF message type has no handler THEN THE SYSTEM SHALL log warning in development mode only

---

### GAP-05: State Update Message Format Mismatch
**Severity:** High  
**Component:** Frontend/Backend - useIRISWebSocket.ts, iris_gateway.py

**Current Behavior:**
- Backend sends: `{"type": "state_update", "state": {...}}`
- Frontend expects: `state_sync` (different name)
- Inconsistent formats between `state_update` (full state) and key/value updates

**Expected Behavior:**
- Consistent message type naming
- Unified state update format

#### Acceptance Criteria
1. WHEN backend sends state update THE SYSTEM SHALL use type `"state_sync"` not `"state_update"`
2. THE SYSTEM SHALL include full state object in payload.state
3. THE SYSTEM SHALL NOT send key/value format for state changes
4. WHEN frontend receives state_sync THE SYSTEM SHALL update all state fields atomically

---

### GAP-06: Voice Pipeline Callback Registration Not Unregistered
**Severity:** Medium  
**Component:** Backend - iris_gateway.py

**Current Behavior:**
- Voice callbacks registered in `_handle_voice()` (lines 467-474)
- Never unregistered when session ends or client disconnects
- Memory leaks and duplicate callbacks on reconnection

**Expected Behavior:**
- Callbacks unregistered on session cleanup
- No memory leaks or duplicate registrations

#### Acceptance Criteria
1. WHEN session ends THE SYSTEM SHALL unregister voice state callbacks
2. WHEN client disconnects THE SYSTEM SHALL unregister audio level callbacks
3. THE SYSTEM SHALL track registered callbacks per session
4. IF callback registration fails THEN THE SYSTEM SHALL log error and continue

---

### GAP-07: BUG-06 Verification Required
**Severity:** Medium  
**Component:** Frontend - WheelView.tsx

**Current Behavior:**
- Spec claims BUG-06 is "Already Fixed"
- Original bug: Only 2 Card IDs sent `update_field` to backend
- Need verification all cards (voice, memory, personality, system, shortcuts) send updates

**Expected Behavior:**
- All Card types send `update_field` messages to backend
- No hardcoded Card ID restrictions

#### Acceptance Criteria
1. WHEN any Card field changes THE SYSTEM SHALL send `update_field` via WebSocket
2. THE SYSTEM SHALL use `CARD_TO_SECTION_ID` mapping for all Cards
3. IF field update fails THE SYSTEM SHALL show error to user
4. THE SYSTEM SHALL NOT have hardcoded Card ID exceptions

---

### GAP-08: Error Handler Sends Generic Error Type
**Severity:** Medium  
**Component:** Frontend/Backend - useIRISWebSocket.ts, iris_gateway.py

**Current Behavior:**
- Backend sends: `{"type": "error", "payload": {"message": "..."}}` (iris_gateway.py:1246)
- Frontend has no handler for `"error"` type

**Expected Behavior:**
- Frontend handles error messages from backend
- Errors displayed to user appropriately

#### Acceptance Criteria
1. WHEN backend sends error message THE SYSTEM SHALL handle it in useIRISWebSocket.ts
2. THE SYSTEM SHALL set lastError state with error message
3. THE SYSTEM SHALL console.error the full error details
4. IF error payload is missing message THEN THE SYSTEM SHALL show generic error

---

### GAP-09: Validation Error Payload Format Mismatch
**Severity:** Medium  
**Component:** Frontend/Backend - useIRISWebSocket.ts, iris_gateway.py

**Current Behavior:**
- Backend sends nested: `payload.payload.field_id` (iris_gateway.py:1262)
- Frontend expects direct: `payload.field_id` (useIRISWebSocket.ts:357)

**Expected Behavior:**
- Consistent payload format between backend and frontend

#### Acceptance Criteria
1. WHEN backend sends validation_error THE SYSTEM SHALL use flat payload structure
2. THE SYSTEM SHALL include `field_id`, `subnode_id`, and `error` at payload level
3. THE SYSTEM SHALL NOT nest payload inside payload
4. WHEN frontend receives validation_error THE SYSTEM SHALL extract fields correctly

---

### GAP-10: Theme Update Response Format Inconsistent
**Severity:** Low  
**Component:** Frontend/Backend - useIRISWebSocket.ts, main.py, iris_gateway.py

**Current Behavior:**
- `iris_gateway.py` sends: `{"type": "theme_updated", "payload": {...}}`
- `main.py` sends: `{"type": "theme_updated", "glow": ..., "font": ...}` (direct properties)
- Frontend expects direct properties

**Expected Behavior:**
- Consistent theme update format across all backend handlers

#### Acceptance Criteria
1. WHEN backend sends theme_updated THE SYSTEM SHALL use direct properties (not nested payload)
2. THE SYSTEM SHALL include `glow`, `font`, and `state_colors_enabled` at top level
3. THE SYSTEM SHALL use same format in both main.py and iris_gateway.py
4. WHEN frontend receives theme_updated THE SYSTEM SHALL update theme state correctly

---

### GAP-11: Missing Session Cleanup on Disconnect
**Severity:** Medium  
**Component:** Backend - iris_gateway.py, main.py

**Current Behavior:**
- No cleanup when client disconnects
- Voice callbacks remain registered
- Session state not cleaned up
- Wake word listeners persist

**Expected Behavior:**
- Clean resource cleanup on disconnect
- No memory leaks

#### Acceptance Criteria
1. WHEN client disconnects THE SYSTEM SHALL unregister all voice callbacks
2. THE SYSTEM SHALL clean up session-specific resources
3. THE SYSTEM SHALL remove wake word listeners for disconnected session
4. THE SYSTEM SHALL log cleanup completion for debugging

---

### GAP-12: Field Update Missing Timestamp
**Severity:** Medium  
**Component:** Backend - main.py

**Current Behavior:**
- `main.py` sends: `{"type": "field_updated", "subnode_id": ..., "field_id": ..., "value": ...}` (line 395)
- Missing `timestamp` field
- `iris_gateway.py` includes timestamp (line 337)

**Expected Behavior:**
- Consistent field update format with timestamp
- Out-of-order update detection works correctly

#### Acceptance Criteria
1. WHEN main.py sends field_updated THE SYSTEM SHALL include timestamp field
2. THE SYSTEM SHALL use UTC timestamp in milliseconds
3. THE SYSTEM SHALL use same format as iris_gateway.py
4. WHEN frontend receives field_updated THE SYSTEM SHALL use timestamp for ordering

---

## Summary Table

| Gap | Severity | Component | Priority |
|-----|----------|-----------|----------|
| GAP-01 | Critical | Backend | 1 |
| GAP-02 | Critical | Frontend/Backend | 2 |
| GAP-03 | High | Frontend | 3 |
| GAP-04 | High | Frontend | 4 |
| GAP-05 | High | Frontend/Backend | 5 |
| GAP-06 | Medium | Backend | 6 |
| GAP-07 | Medium | Frontend | 7 |
| GAP-08 | Medium | Frontend/Backend | 8 |
| GAP-09 | Medium | Frontend/Backend | 9 |
| GAP-10 | Low | Frontend/Backend | 10 |
| GAP-11 | Medium | Backend | 11 |
| GAP-12 | Medium | Backend | 12 |

## Implementation Order

1. **Phase 1 - Message Routing (GAP-01, GAP-02)**
   - Consolidate message handlers
   - Fix message type mismatches
   
2. **Phase 2 - State Sync (GAP-05, GAP-12)**
   - Unify state update format
   - Add missing timestamps
   
3. **Phase 3 - Event Bridge (GAP-03, GAP-04)**
   - Add missing CustomEvent dispatches
   - Add missing message handlers
   
4. **Phase 4 - Error Handling (GAP-08, GAP-09)**
   - Add error message handler
   - Fix validation error format
   
5. **Phase 5 - Resource Management (GAP-06, GAP-11)**
   - Implement callback unregistration
   - Add session cleanup
   
6. **Phase 6 - Polish (GAP-07, GAP-10)**
   - Verify all cards send updates
   - Unify theme update format

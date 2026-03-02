# Integration Gaps - Implementation Tasks

## Phase 1: Message Routing Consolidation (GAP-01, GAP-02)

### GAP-01: Consolidate Dual Message Routing

- [ ] **Task 1.1:** Audit both message handlers
  - Document all message types handled by main.py
  - Document all message types handled by iris_gateway.py
  - Identify overlaps and gaps
  - _Requirements: GAP-01.1_

- [ ] **Task 1.2:** Import IRISGateway in main.py
  - Add import: `from backend.iris_gateway import IRISGateway`
  - Create singleton instance at module level
  - Initialize in app startup
  - Files: `IRISVOICE/backend/main.py`
  - _Requirements: GAP-01.1_

- [ ] **Task 1.3:** Simplify main.py handle_message to delegate
  - Remove all message type handlers from main.py handle_message()
  - Add single line: `await iris_gateway.handle_message(client_id, message)`
  - Keep only WebSocket lifecycle management in main.py
  - Files: `IRISVOICE/backend/main.py` (lines 305-498)
  - _Requirements: GAP-01.1_

- [ ] **Task 1.4:** Test message routing consolidation
  - Verify all messages route through iris_gateway
  - Test each message type: select_category, select_subnode, update_field, etc.
  - Ensure no duplicate processing
  - Run: `cd IRISVOICE/backend && python -m pytest tests/test_message_routing.py -v --timeout=30`
  - Timeout: 60s
  - Fallback if hanging: `cd IRISVOICE/backend && python -m pytest tests/test_message_routing.py -v --timeout=10 -x`
  - _Requirements: GAP-01.1_

### GAP-02: Fix Mismatched Message Types

- [ ] **Task 1.5:** Update iris_gateway.py to support select_* types
  - Change: `if msg_type in ["select_category", "select_subnode", "go_back"]:`
  - Also support legacy `set_*` types for backward compatibility
  - Files: `IRISVOICE/backend/iris_gateway.py` (line 109)
  - _Requirements: GAP-02.1, GAP-02.2, GAP-02.3_

- [ ] **Task 1.6:** Update _handle_navigation for select_category
  - Handle both `message.get("category")` and `message.get("payload", {}).get("category")`
  - Update message type check: `if msg_type in ["select_category", "set_category"]:`
  - Files: `IRISVOICE/backend/iris_gateway.py` (lines 194-236)
  - _Requirements: GAP-02.1_

- [ ] **Task 1.7:** Update _handle_navigation for select_subnode
  - Handle both `message.get("subnode_id")` and `message.get("payload", {}).get("subnode_id")`
  - Update message type check: `if msg_type in ["select_subnode", "set_subnode"]:`
  - Files: `IRISVOICE/backend/iris_gateway.py` (lines 194-236)
  - _Requirements: GAP-02.2_

- [ ] **Task 1.8:** Add expand_to_main handler
  - Add to iris_gateway.py message routing
  - Files: `IRISVOICE/backend/iris_gateway.py`
  - _Requirements: GAP-02.3_

- [ ] **Task 1.9:** Test message type compatibility
  - Send select_category from frontend, verify backend processes
  - Send select_subnode from frontend, verify backend processes
  - Run: `cd IRISVOICE && npm test -- --testNamePattern="message types" --watchAll=false --forceExit`
  - Timeout: 60s
  - Fallback if hanging: `cd IRISVOICE && npm test -- --testNamePattern="message types" --watchAll=false --forceExit --testTimeout=10000`
  - _Requirements: GAP-02.1, GAP-02.2, GAP-02.3_

---

## Phase 2: State Synchronization (GAP-05, GAP-12)

### GAP-05: Unify State Update Format

- [ ] **Task 2.1:** Change state_update to state_sync in backend
  - Update: `type: "state_sync"` instead of `"state_update"`
  - Ensure full state object is always sent
  - Files: `IRISVOICE/backend/iris_gateway.py` (line 1226)
  - _Requirements: GAP-05.1, GAP-05.2_

- [ ] **Task 2.2:** Remove key/value state update format
  - Remove or deprecate state updates with key/value format
  - Always send full state in `payload.state`
  - Files: `IRISVOICE/backend/main.py` (lines 273-285)
  - _Requirements: GAP-05.3_

- [ ] **Task 2.3:** Update frontend to handle state_sync
  - Ensure useIRISWebSocket.ts handles `state_sync` type
  - Update state atomically when received
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts` (line 271)
  - _Requirements: GAP-05.4_

### GAP-12: Add Timestamp to Field Updates

- [ ] **Task 2.4:** Add time import to main.py
  - Add: `import time` at top of file
  - Files: `IRISVOICE/backend/main.py`
  - _Requirements: GAP-12.1_

- [ ] **Task 2.5:** Add timestamp to field_updated response
  - Update response to include: `"timestamp": int(time.time() * 1000)`
  - Files: `IRISVOICE/backend/main.py` (lines 395-400)
  - _Requirements: GAP-12.1, GAP-12.2, GAP-12.3_

- [ ] **Task 2.6:** Verify timestamp format matches iris_gateway.py
  - Compare timestamp format between main.py and iris_gateway.py
  - Ensure both use milliseconds since epoch
  - _Requirements: GAP-12.3_

---

## Phase 3: Event Bridge (GAP-03, GAP-04)

### GAP-03: Add Missing CustomEvent Dispatches

- [ ] **Task 3.1:** Add iris:voice_state_change dispatch
  - Add dispatch in "listening_state" case
  - Include state in detail payload
  - Add SSR check: `if (typeof window !== 'undefined')`
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts` (lines 424-434)
  - _Requirements: GAP-03.1, GAP-03.3_

- [ ] **Task 3.2:** Add iris:field_updated dispatch
  - Add dispatch in "field_updated" case
  - Include subnode_id, field_id, value, timestamp in detail
  - Add SSR check
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts` (lines 301-355)
  - _Requirements: GAP-03.2, GAP-03.3_

- [ ] **Task 3.3:** Test CustomEvent dispatches
  - Add event listeners in test
  - Trigger voice state change, verify event fires
  - Trigger field update, verify event fires
  - Run: `cd IRISVOICE && npm test -- --testNamePattern="CustomEvent" --watchAll=false --forceExit`
  - Timeout: 60s
  - Fallback if hanging: `cd IRISVOICE && npm test -- --testNamePattern="CustomEvent" --watchAll=false --forceExit --testTimeout=10000`
  - _Requirements: GAP-03.1, GAP-03.2_

### GAP-04: Add Missing Message Handlers

- [ ] **Task 3.4:** Add subnodes message handler
  - Add case for "subnodes" in handleMessage switch
  - Update subnodes state with received data
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts`
  - _Requirements: GAP-04.1_

- [ ] **Task 3.5:** Add model_selection_updated handler
  - Add case for "model_selection_updated"
  - Log for debugging (may add state later)
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts`
  - _Requirements: GAP-04.2_

- [ ] **Task 3.6:** Add wake_word_selected handler
  - Add case for "wake_word_selected"
  - Log selection for debugging
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts`
  - _Requirements: GAP-04.3_

- [ ] **Task 3.7:** Add cleanup message handlers
  - Add cases for "cleanup_report" and "cleanup_result"
  - Log results for debugging
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts`
  - _Requirements: GAP-04.3_

- [ ] **Task 3.8:** Add category_expanded handler
  - Add case for "category_expanded"
  - Log for debugging
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts`
  - _Requirements: GAP-04.3_

- [ ] **Task 3.9:** Add warning for unknown message types (dev only)
  - In default case, log warning only in development mode
  - Reduce console noise in production
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts` (lines 612-616)
  - _Requirements: GAP-04.4_

---

## Phase 4: Error Handling (GAP-08, GAP-09)

### GAP-08: Add Error Message Handler

- [ ] **Task 4.1:** Add error case to handleMessage
  - Add case "error" to switch statement
  - Extract message from payload.message or payload.error
  - Call setLastError with error message
  - Log error details to console
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts`
  - _Requirements: GAP-08.1, GAP-08.2, GAP-08.3_

- [ ] **Task 4.2:** Handle missing error message gracefully
  - Show "Unknown error" if payload.message is missing
  - Ensure lastError is always a string
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts`
  - _Requirements: GAP-08.4_

### GAP-09: Fix Validation Error Format

- [ ] **Task 4.3:** Update _send_validation_error in iris_gateway.py
  - Change to flat payload structure
  - Send: `{"type": "validation_error", "field_id": ..., "error": ...}`
  - Remove nested payload structure
  - Files: `IRISVOICE/backend/iris_gateway.py` (lines 1261-1263)
  - _Requirements: GAP-09.1, GAP-09.2, GAP-09.3_

- [ ] **Task 4.4:** Update frontend to handle flat validation errors
  - Verify useIRISWebSocket.ts handles flat format
  - Remove any nested payload access
  - Files: `IRISVOICE/hooks/useIRISWebSocket.ts` (lines 357-393)
  - _Requirements: GAP-09.4_

---

## Phase 5: Resource Management (GAP-06, GAP-11)

### GAP-06: Implement Voice Callback Cleanup

- [ ] **Task 5.1:** Add callback tracking to IRISGateway
  - Add `_voice_callbacks: Dict[str, Dict[str, Any]]` to __init__
  - Initialize as empty dict
  - Files: `IRISVOICE/backend/iris_gateway.py`
  - _Requirements: GAP-06.3_

- [ ] **Task 5.2:** Store callback references on registration
  - After registering callbacks in _handle_voice, store in _voice_callbacks[session_id]
  - Store both state and audio callbacks
  - Files: `IRISVOICE/backend/iris_gateway.py` (lines 467-474)
  - _Requirements: GAP-06.3_

- [ ] **Task 5.3:** Add unregister methods to voice_pipeline.py
  - Add `unregister_state_callback(self, session_id, callback)`
  - Add `unregister_audio_level_callback(self, session_id, callback)`
  - Remove callbacks from internal sets
  - Files: `IRISVOICE/backend/voice/voice_pipeline.py`
  - _Requirements: GAP-06.1, GAP-06.2_

- [ ] **Task 5.4:** Add cleanup_session method to IRISGateway
  - Create `cleanup_session(self, session_id)` method
  - Unregister voice callbacks for session
  - Remove session from _voice_callbacks dict
  - Log cleanup completion
  - Files: `IRISVOICE/backend/iris_gateway.py`
  - _Requirements: GAP-06.1, GAP-06.2_

### GAP-11: Add Session Cleanup on Disconnect

- [ ] **Task 5.5:** Call cleanup_session on WebSocketDisconnect
  - In main.py except WebSocketDisconnect block, call `await iris_gateway.cleanup_session(active_session_id)`
  - Files: `IRISVOICE/backend/main.py` (line 293-296)
  - _Requirements: GAP-11.1_

- [ ] **Task 5.6:** Ensure cleanup in finally block
  - Add cleanup call in finally block as safety
  - Files: `IRISVOICE/backend/main.py` (line 297-299)
  - _Requirements: GAP-11.2_

- [ ] **Task 5.7:** Test session cleanup
  - Connect client, start voice command
  - Disconnect client
  - Verify callbacks are unregistered
  - Run: `cd IRISVOICE/backend && python -m pytest tests/test_session_cleanup.py -v --timeout=30`
  - Timeout: 60s
  - Fallback if hanging: `cd IRISVOICE/backend && python -m pytest tests/test_session_cleanup.py -v --timeout=10 -x`
  - _Requirements: GAP-11.3_

---

## Phase 6: Polish (GAP-07, GAP-10)

### GAP-07: Verify All Cards Send Updates

- [ ] **Task 6.1:** Audit WheelView handleValueChange
  - Verify all Card types use CARD_TO_SECTION_ID mapping
  - Check for hardcoded Card ID exceptions
  - Verify sendMessage is called for all field changes
  - Files: `IRISVOICE/components/wheel-view/WheelView.tsx` (lines 120-140)
  - _Requirements: GAP-07.1, GAP-07.4_

- [ ] **Task 6.2:** Test field updates for all Card types
  - Test voice-card fields
  - Test memory-card fields
  - Test personality-card fields
  - Test system-card fields
  - Test shortcuts-card fields
  - Verify all send update_field messages
  - _Requirements: GAP-07.1, GAP-07.2_

- [ ] **Task 6.3:** Add error handling for failed updates
  - Ensure UI shows error if update_field fails
  - Revert to previous value on error
  - Files: `IRISVOICE/components/wheel-view/WheelView.tsx`
  - _Requirements: GAP-07.3_

### GAP-10: Unify Theme Update Format

- [ ] **Task 6.4:** Update theme_updated in iris_gateway.py
  - Change from nested payload to direct properties
  - Send: `{"type": "theme_updated", "glow": ..., "font": ...}`
  - Match format used in main.py
  - Files: `IRISVOICE/backend/iris_gateway.py` (lines 388-393)
  - _Requirements: GAP-10.1, GAP-10.2_

- [ ] **Task 6.5:** Test theme updates from both handlers
  - Update theme via iris_gateway handler, verify frontend receives
  - Update theme via main.py handler, verify frontend receives
  - Ensure both use same format
  - _Requirements: GAP-10.3, GAP-10.4_

---

## Phase 7: Integration Verification

- [ ] **Task 7.1:** Run full backend test suite
  - Command: `cd IRISVOICE/backend && python -m pytest tests/ -v --timeout=60`
  - Timeout: 120s
  - Fallback if hanging: `cd IRISVOICE/backend && python -m pytest tests/ -v --timeout=30 -x`
  - All tests must pass

- [ ] **Task 7.2:** Run full frontend test suite
  - Command: `cd IRISVOICE && npm test -- --watchAll=false --forceExit`
  - Timeout: 120s
  - Fallback if hanging: `cd IRISVOICE && npm test -- --watchAll=false --forceExit --testTimeout=30000 --bail`
  - All tests must pass

- [ ] **Task 7.3:** TypeScript compilation check
  - Command: `cd IRISVOICE && npx tsc --noEmit`
  - Must have 0 errors

- [ ] **Task 7.4:** Python syntax check
  - Command: `cd IRISVOICE/backend && python -m py_compile iris_gateway.py main.py`
  - Must pass without errors

- [ ] **Task 7.5:** End-to-end integration test
  - Start backend and frontend
  - Connect WebSocket client
  - Test complete flow: navigation → field update → voice command → disconnect
  - Verify all gaps are resolved
  - _Requirements: All GAPs_

---

## Task Dependencies

```
Phase 1 (Message Routing)
├── Task 1.1 → 1.2 → 1.3 → 1.4
└── Task 1.5 → 1.6 → 1.7 → 1.8 → 1.9

Phase 2 (State Sync)
├── Task 2.1 → 2.2 → 2.3
└── Task 2.4 → 2.5 → 2.6
↑ Depends on: Phase 1

Phase 3 (Event Bridge)
├── Task 3.1 → 3.2 → 3.3
└── Task 3.4 → 3.5 → 3.6 → 3.7 → 3.8 → 3.9
↑ Depends on: Phase 2

Phase 4 (Error Handling)
├── Task 4.1 → 4.2
└── Task 4.3 → 4.4
↑ Depends on: Phase 3

Phase 5 (Resource Management)
├── Task 5.1 → 5.2 → 5.3 → 5.4
└── Task 5.5 → 5.6 → 5.7
↑ Depends on: Phase 4

Phase 6 (Polish)
├── Task 6.1 → 6.2 → 6.3
└── Task 6.4 → 6.5
↑ Depends on: Phase 5

Phase 7 (Verification)
└── Tasks 7.1 → 7.2 → 7.3 → 7.4 → 7.5
↑ Depends on: All previous phases
```

---

## Acceptance Criteria Mapping

| Task | Requirements Covered |
|------|---------------------|
| 1.1-1.4 | GAP-01.1 |
| 1.5-1.9 | GAP-02.1, GAP-02.2, GAP-02.3 |
| 2.1-2.3 | GAP-05.1, GAP-05.2, GAP-05.3, GAP-05.4 |
| 2.4-2.6 | GAP-12.1, GAP-12.2, GAP-12.3, GAP-12.4 |
| 3.1-3.3 | GAP-03.1, GAP-03.2, GAP-03.3 |
| 3.4-3.9 | GAP-04.1, GAP-04.2, GAP-04.3, GAP-04.4 |
| 4.1-4.2 | GAP-08.1, GAP-08.2, GAP-08.3, GAP-08.4 |
| 4.3-4.4 | GAP-09.1, GAP-09.2, GAP-09.3, GAP-09.4 |
| 5.1-5.4 | GAP-06.1, GAP-06.2, GAP-06.3 |
| 5.5-5.7 | GAP-11.1, GAP-11.2, GAP-11.3 |
| 6.1-6.3 | GAP-07.1, GAP-07.2, GAP-07.3, GAP-07.4 |
| 6.4-6.5 | GAP-10.1, GAP-10.2, GAP-10.3, GAP-10.4 |
| 7.1-7.5 | All GAPs |

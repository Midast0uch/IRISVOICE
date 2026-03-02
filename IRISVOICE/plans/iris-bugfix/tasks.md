# IRIS Bug Fix Implementation Tasks

## Phase 1: Critical Infrastructure (BUG-01/08, BUG-03)

### BUG-01/08: NavigationContext Reload Loop

- [x] **Task 1.1:** Write failing test that detects double RESTORE_STATE dispatch
  - Test: Check console logs or spy on dispatch to verify only one call
  - Timeout: 30s
  - Location: `IRISVOICE/__tests__/contexts/NavigationContext.test.tsx`

- [x] **Task 1.2:** Consolidate localStorage restoration into single effect
  - File: `IRISVOICE/contexts/NavigationContext.tsx`
  - Lines: 558-641
  - Changes:
    - Merge three separate try/catch blocks into single restoration flow
    - Build complete restored state object before dispatching
    - Dispatch RESTORE_STATE exactly once

- [x] **Task 1.3:** Remove stale closure in miniNodeValues restoration
  - File: `IRISVOICE/contexts/NavigationContext.tsx`
  - Lines: 627-634
  - Changes:
    - Remove `...state` spread from second dispatch
    - Assign miniNodeValues directly to restoredState object

- [x] **Task 1.4:** Optimize persist effects to exclude animation states
  - File: `IRISVOICE/contexts/NavigationContext.tsx`
  - Lines: 643-677
  - Changes:
    - Replace `[state]` dependency with specific fields
    - Add debounce (100ms) to prevent rapid writes
    - Skip persist when `isTransitioning` is true

- [~] **Task 1.5:** Run NavigationContext tests
  - Command: `cd IRISVOICE && npm test -- --testPathPattern=NavigationContext --no-coverage`
  - Timeout: 60s
  - Fallback: `npm test -- --testNamePattern="NavigationContext" --forceExit`

### BUG-03: Backend Voice Callbacks Never Awaited

- [ ] **Task 1.6:** Write failing test for voice state callback propagation
  - Test: Verify callback result is awaited (not just created)
  - Timeout: 30s
  - Location: `IRISVOICE/backend/tests/test_voice_callbacks.py`

- [x] **Task 1.7:** Fix callback registration in iris_gateway.py
  - File: `IRISVOICE/backend/iris_gateway.py`
  - Lines: 459-466
  - Changes:

```python
# Before:
self._voice_pipeline.register_state_callback(
    session_id,
    lambda state: self._on_voice_state_change(session_id, state)
)

# After:
async def state_change_callback(state: VoiceState) -> None:
    await self._on_voice_state_change(session_id, state)

self._voice_pipeline.register_state_callback(session_id, state_change_callback)
```

- [x] **Task 1.8:** Fix callback registration for audio level
  - File: `IRISVOICE/backend/iris_gateway.py`
  - Lines: 463-466
  - Changes: Same pattern as Task 1.7 for audio level callback

- [ ] **Task 1.9:** Verify asyncio.iscoroutinefunction check in voice_pipeline.py
  - File: `IRISVOICE/backend/voice/voice_pipeline.py`
  - Lines: 284-287

- [ ] **Task 1.10:** Run backend voice tests
  - Command: `cd IRISVOICE/backend && python -m pytest tests/test_voice_callbacks.py -v`
  - Timeout: 60s

---

## Phase 2: Frontend-Backend Bridge (BUG-02)

### BUG-02: WebSocket Event Dispatching

- [x] **Task 2.1:** Write failing test for initial_state event dispatch
  - Test: Mock WebSocket message and verify CustomEvent is dispatched
  - Timeout: 30s
  - Location: `IRISVOICE/__tests__/hooks/useIRISWebSocket.test.ts`

- [x] **Task 2.2:** Add initial_state event dispatch
  - File: `IRISVOICE/hooks/useIRISWebSocket.ts`

```typescript
case "initial_state": {
  if (payload.state) {
    setFieldValues(payload.state.field_values || {})
    setCurrentCategory(payload.state.current_category)
    setCurrentSubnode(payload.state.current_subnode)
    
    window.dispatchEvent(new CustomEvent('iris:initial_state', {
      detail: { state: payload.state }
    }))
  }
  break
}
```

- [ ] **Task 2.3:** Add available_models event dispatch
- [ ] **Task 2.4:** Add audio_devices event dispatch  
- [ ] **Task 2.5:** Add wake_words_list event dispatch
- [ ] **Task 2.6:** Run WebSocket hook tests

---

## Phase 3: Data Flow Verification (BUG-06, BUG-07)

### BUG-06 Verification (Already Fixed)

- [ ] **Task 3.1:** Verify CARD_TO_SECTION_ID mapping is used in WheelView
- [ ] **Task 3.2:** Write integration test for field update flow

### BUG-07: SidePanel Wrong State Key

- [ ] **Task 3.3:** Write failing test for SidePanel state lookup
- [ ] **Task 3.4:** Add CARD_TO_SECTION_ID import and mapping

```typescript
import { CARD_TO_SECTION_ID } from "@/data/navigation-constants"

const sectionId = CARD_TO_SECTION_ID[miniNode.id] || miniNode.id
const subnodeValues = state.fieldValues[sectionId]
```

- [ ] **Task 3.5:** Run SidePanel tests

---

## Phase 4: Voice Component Stability (BUG-04, BUG-05, BUG-09)

### BUG-04: IrisOrb Stale Closure

- [ ] **Task 4.1:** Write failing test for double-click handler stability
- [ ] **Task 4.2:** Memoize double-click handler

```typescript
const handleDoubleClick = useCallback(() => {
  if (!isListening) {
    startVoiceCommand()
  }
  if (onDoubleClick) onDoubleClick()
}, [isListening, startVoiceCommand, onDoubleClick])
```

- [ ] **Task 4.3:** Run IrisOrb tests

### BUG-09: Wake Word Callback Re-Registration

- [ ] **Task 4.4:** Write failing test for callback registration count
- [ ] **Task 4.5:** Break circular dependency with refs

```typescript
const isListeningRef = useRef(isListening)
isListeningRef.current = isListening

const handleWakeDetected = useCallback(() => {
  if (isListeningRef.current) return
  startVoiceCommand()
}, [startVoiceCommand])

useEffect(() => {
  if (onCallbacksReady) {
    onCallbacksReady({ handleWakeDetected, handleNativeAudioResponse })
  }
}, [])  // Empty deps - register once
```

- [ ] **Task 4.6:** Re-run IrisOrb tests

### BUG-05: Voice Toggle WebSocket Path

- [ ] **Task 4.7:** Document WebSocket pattern for future card-ring.tsx

---

## Phase 5: Integration Verification

- [ ] **Task 5.1:** End-to-end voice flow test
- [ ] **Task 5.2:** End-to-end field update flow test
- [ ] **Task 5.3:** Performance test - no reload loops
- [ ] **Task 5.4:** Run full test suite

---

## Task Dependencies

```
Phase 1 (Critical Infrastructure)
├── BUG-01/08 (NavigationContext) 
│   └── Task 1.1 → 1.2 → 1.3 → 1.4 → 1.5
└── BUG-03 (Backend Callbacks)
    └── Task 1.6 → 1.7 → 1.8 → 1.9 → 1.10

Phase 2 (Event Bridge)
└── BUG-02 (WebSocket Events)
    └── Task 2.1 → 2.2 → 2.3 → 2.4 → 2.5 → 2.6
    ↑ Depends on: Phase 1 complete

Phase 3 (Data Flow)
└── BUG-07 (SidePanel)
    └── Task 3.3 → 3.4 → 3.5
    ↑ Depends on: Phase 2 complete

Phase 4 (Voice Stability)
├── BUG-04 (IrisOrb stale closure)
│   └── Task 4.1 → 4.2 → 4.3
└── BUG-09 (Callback registration)
    └── Task 4.4 → 4.5 → 4.6
    ↑ Depends on: All previous phases complete

Phase 5 (Integration)
└── Tasks 5.1 → 5.2 → 5.3 → 5.4
```

# IRIS Bug Fix Design Specification

## Architecture Overview

This document provides the technical design for fixing 9 identified bugs in the IRIS system. The fixes span both frontend (React/TypeScript) and backend (Python/FastAPI) components.

## Design Principles

1. **Minimal Blast Radius:** Each fix should be surgical and not affect unrelated functionality
2. **Existing Patterns:** Use existing patterns like `CARD_TO_SECTION_ID` rather than inventing new abstractions
3. **Async Safety:** Properly handle async/await patterns in both frontend and backend
4. **Stable References:** Use memoization to prevent unnecessary re-renders and re-registrations

---

## BUG-01/08: NavigationContext Reload Loop Fix

### Root Cause Analysis
- **File:** `IRISVOICE/contexts/NavigationContext.tsx`
- **Lines:** 558-641 (init effect), 643-677 (persist effects)
- **Issue:** Double RESTORE_STATE dispatch with stale closure + over-eager persistence

### Current Code (Broken)
```typescript
// Lines 587, 628 - DOUBLE DISPATCH
dispatch({ type: 'RESTORE_STATE', payload: restoredState })
// ... later ...
dispatch({ 
  type: 'RESTORE_STATE', 
  payload: { 
    ...state,  // ← STALE CLOSURE: still has initial state!
    miniNodeValues: parsed 
  } 
})

// Lines 643-677 - Persist on every state change
useEffect(() => { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)) }, [state])
```

### Proposed Fix
1. **Consolidate restoration** into single dispatch after all localStorage reads complete
2. **Remove stale closure** by not spreading `...state` in second dispatch
3. **Add debounce/throttle** to persist effects or exclude animation-related fields

```typescript
// Single init effect
useEffect(() => {
  const saved = localStorage.getItem(STORAGE_KEY)
  const savedConfig = localStorage.getItem(CONFIG_STORAGE_KEY)
  const savedValues = localStorage.getItem(MINI_NODE_VALUES_KEY)
  
  let restoredState = initialState
  
  if (saved) {
    const parsed = JSON.parse(saved)
    // ... migration logic ...
    restoredState = { ...parsed, level: normalizeLevel(parsed.level) }
  }
  
  if (savedValues) {
    const parsed = JSON.parse(savedValues)
    restoredState.miniNodeValues = parsed  // Direct assignment, no stale closure
  }
  
  dispatch({ type: 'RESTORE_STATE', payload: restoredState })
  
  if (savedConfig) {
    setConfig({ ...DEFAULT_NAV_CONFIG, ...JSON.parse(savedConfig) })
  }
}, [])  // Run once on mount

// Debounced persist effect
useEffect(() => {
  // Only persist when meaningful state changes (not during transitions)
  if (state.isTransitioning) return
  
  const timer = setTimeout(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  }, 100)
  
  return () => clearTimeout(timer)
}, [state.level, state.selectedMain, state.selectedSub, state.miniNodeStack, 
    state.miniNodeValues, state.confirmedMiniNodes])
```

---

## BUG-02: WebSocket Event Bridge Fix

### Root Cause Analysis
- **Files:** `IRISVOICE/hooks/useIRISWebSocket.ts`, `IRISVOICE/components/wheel-view/SidePanel.tsx`
- **Issue:** WebSocket messages not dispatched as CustomEvents that SidePanel listens for

### Current Code (Broken)
```typescript
// SidePanel.tsx lines 90, 108 - Listening but never receives
const handleInitialState = (event: CustomEvent) => { /* ... */ }
window.addEventListener('iris:initial_state', handleInitialState)

// useIRISWebSocket.ts - initial_state message handling missing
```

### Proposed Fix
Add event dispatching in useIRISWebSocket.ts message handler:

```typescript
// In useIRISWebSocket.ts message handler
case "initial_state": {
  if (payload.state) {
    setFieldValues(payload.state.field_values || {})
    setCurrentCategory(payload.state.current_category)
    setCurrentSubnode(payload.state.current_subnode)
    
    // Dispatch CustomEvent for components listening via window
    window.dispatchEvent(new CustomEvent('iris:initial_state', {
      detail: { state: payload.state }
    }))
  }
  break
}

case "available_models": {
  window.dispatchEvent(new CustomEvent('iris:available_models', {
    detail: { models: payload.models }
  }))
  break
}

case "audio_devices": {
  window.dispatchEvent(new CustomEvent('iris:audio_devices', {
    detail: { 
      input_devices: payload.input_devices,
      output_devices: payload.output_devices 
    }
  }))
  break
}

case "wake_words_list": {
  window.dispatchEvent(new CustomEvent('iris:wake_words_list', {
    detail: { wake_words: payload.wake_words }
  }))
  break
}
```

---

## BUG-03: Backend Voice Callback Fix

### Root Cause Analysis
- **Files:** `IRISVOICE/backend/iris_gateway.py`, `IRISVOICE/backend/voice/voice_pipeline.py`
- **Lines:** 459-466 (callback registration), 284-287 (callback invocation)
- **Issue:** Sync lambdas calling async methods - coroutines created but never awaited

### Current Code (Broken)
```python
# iris_gateway.py lines 459-466
self._voice_pipeline.register_state_callback(
    session_id,
    lambda state: self._on_voice_state_change(session_id, state)  # Returns coroutine!
)

# voice_pipeline.py lines 284-287
if asyncio.iscoroutinefunction(callback):  # False for lambda wrapping async!
    await callback(new_state)
else:
    callback(new_state)  # Coroutine created but discarded
```

### Proposed Fix

**Option A: Use bound methods instead of lambdas (Recommended)**
```python
# iris_gateway.py
# Register bound async methods directly
self._voice_pipeline.register_state_callback(
    session_id,
    self._on_voice_state_change  # Method bound to self
)

# Modify callback signature to include session_id context
async def _on_voice_state_change(self, state: VoiceState) -> None:
    # Get session_id from closure or modify pipeline to pass it
    ...
```

**Option B: Make lambdas async and await in pipeline**
```python
# iris_gateway.py
self._voice_pipeline.register_state_callback(
    session_id,
    lambda state: self._on_voice_state_change(session_id, state)  # Still returns coroutine
)

# voice_pipeline.py - Always await if result is coroutine
result = callback(new_state)
if asyncio.iscoroutine(result):
    await result
```

**Option C: Wrap in async function that captures session_id**
```python
# iris_gateway.py
async def state_callback(state: VoiceState) -> None:
    await self._on_voice_state_change(session_id, state)

self._voice_pipeline.register_state_callback(session_id, state_callback)
```

**Recommended: Option C** - Cleanest, explicit, maintains session context.

---

## BUG-07: SidePanel State Key Mapping Fix

### Root Cause Analysis
- **File:** `IRISVOICE/components/wheel-view/SidePanel.tsx`
- **Lines:** 96-104
- **Issue:** Using Card ID instead of Section ID for state lookup

### Current Code (Broken)
```typescript
// SidePanel.tsx lines 96-104
if (state.fieldValues && miniNode.id) {
  const subnodeId = miniNode.id  // 'inference-card' - WRONG!
  const subnodeValues = state.fieldValues[subnodeId]
  ...
}
```

### Proposed Fix
Use existing `CARD_TO_SECTION_ID` mapping:

```typescript
import { CARD_TO_SECTION_ID } from "@/data/navigation-constants"

// SidePanel.tsx - lookup fix
if (state.fieldValues && miniNode.id) {
  const sectionId = CARD_TO_SECTION_ID[miniNode.id] || miniNode.id
  const subnodeValues = state.fieldValues[sectionId]  // 'inference_mode' - CORRECT!
  
  if (subnodeValues) {
    Object.entries(subnodeValues).forEach(([fieldId, value]) => {
      onValueChange(fieldId, value as FieldValue)
    })
  }
}
```

---

## BUG-04: IrisOrb Stale Closure Fix

### Root Cause Analysis
- **File:** `IRISVOICE/components/iris/IrisOrb.tsx`
- **Lines:** 227-239
- **Issue:** Inline function passed to hook, recreated every render

### Current Code (Broken)
```typescript
const { handleMouseDown } = useManualDragWindow(
  orbRef,
  handleInterceptedClick,
  () => {  // ← New function every render!
    if (!isListening) {
      startVoiceCommand()
    }
    if (onDoubleClick) onDoubleClick()
  },
  setDoubleClickFlash,
  setIsPressed
)
```

### Proposed Fix
Memoize the double-click handler:

```typescript
const handleDoubleClick = useCallback(() => {
  if (!isListening) {
    startVoiceCommand()
  }
  if (onDoubleClick) onDoubleClick()
}, [isListening, startVoiceCommand, onDoubleClick])

const { handleMouseDown } = useManualDragWindow(
  orbRef,
  handleInterceptedClick,
  handleDoubleClick,  // ← Stable reference
  setDoubleClickFlash,
  setIsPressed
)
```

---

## BUG-09: Wake Word Callback Registration Fix

### Root Cause Analysis
- **File:** `IRISVOICE/components/iris/IrisOrb.tsx`
- **Lines:** 245-264
- **Issue:** Circular dependency chain causing re-registration

### Current Code (Broken)
```typescript
// Line 245-248
const handleWakeDetected = useCallback(() => {
  if (isListening) return
  startVoiceCommand()
}, [isListening, startVoiceCommand])  // ← Recreates when isListening changes

// Lines 257-264
useEffect(() => {
  if (onCallbacksReady) {
    onCallbacksReady({
      handleWakeDetected,
      handleNativeAudioResponse
    })
  }
}, [onCallbacksReady, handleWakeDetected, handleNativeAudioResponse])  // ← Re-registers when handler changes
```

### Proposed Fix
Use refs to break dependency chain:

```typescript
const isListeningRef = useRef(isListening)
isListeningRef.current = isListening

const handleWakeDetected = useCallback(() => {
  if (isListeningRef.current) return  // Use ref, not direct value
  startVoiceCommand()
}, [startVoiceCommand])  // ← Stable deps

// Register callbacks only once
useEffect(() => {
  if (onCallbacksReady) {
    onCallbacksReady({
      handleWakeDetected,
      handleNativeAudioResponse
    })
  }
}, [])  // ← Empty deps - register once
```

---

## BUG-05: Voice Toggle WebSocket Path Design

### Design Notes
- **Future File:** `IRISVOICE/components/wheel-view/card-ring.tsx`
- **Requirement:** Use WebSocket instead of REST for voice toggle

### Implementation Pattern
```typescript
const { sendMessage, voiceState } = useNavigation()

const handleVoiceToggle = useCallback(() => {
  if (voiceState === 'idle') {
    sendMessage('voice_command_start', {})
  } else {
    sendMessage('voice_command_end', {})
  }
}, [voiceState, sendMessage])
```

---

## Integration Testing Strategy

### Test Order
1. NavigationContext unit tests
2. Backend voice callback unit tests  
3. WebSocket event dispatch integration tests
4. SidePanel state lookup integration tests
5. IrisOrb callback stability tests
6. End-to-end voice flow test

### Key Test Scenarios
- State restoration happens exactly once (console.log verification)
- Voice state changes propagate frontend → backend → frontend
- SidePanel populates with correct initial values
- No memory leaks from callback re-registration

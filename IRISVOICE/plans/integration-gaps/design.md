# Integration Gaps - Design Specification

## Architecture Overview

This document provides the technical design for fixing 12 integration gaps between the IRIS backend (Python/FastAPI) and frontend (Next.js/TypeScript). The design prioritizes backward compatibility, minimal blast radius, and unified message handling.

## Design Principles

1. **Single Source of Truth:** All WebSocket message routing goes through `iris_gateway.py`
2. **Backward Compatibility:** Existing message types continue to work during transition
3. **Consistent Naming:** Use `select_*` pattern for all navigation messages
4. **Resource Cleanup:** All registered callbacks must be unregistered on disconnect
5. **Flat Payloads:** Avoid nested payload structures for consistency

---

## GAP-01: Dual Message Routing System Fix

### Root Cause Analysis
- `main.py` handles messages directly in `handle_message()` function
- `iris_gateway.py` has its own `IRISGateway.handle_message()` method
- Both receive messages, causing race conditions and duplicate processing

### Proposed Fix

**Option A: Delegate main.py to iris_gateway.py (Recommended)**

```python
# main.py - Simplified to delegate to iris_gateway
from backend.iris_gateway import IRISGateway

# Initialize gateway at module level
iris_gateway = IRISGateway()

async def handle_message(client_id: str, session_id: str, message: dict):
    """Delegate all message handling to iris_gateway."""
    await iris_gateway.handle_message(client_id, message)
```

**Changes Required:**
1. Import `IRISGateway` in `main.py`
2. Create singleton instance
3. Remove duplicate message handlers from `main.py`
4. Delegate all calls to `iris_gateway.handle_message()`

### Files Modified
- `IRISVOICE/backend/main.py` - Remove duplicate handlers, add delegation

---

## GAP-02: Mismatched Message Types Fix

### Root Cause Analysis
- Frontend uses `select_category` but backend expects `set_category`
- Inconsistent naming convention between frontend and backend

### Proposed Fix

**Update backend to match frontend naming:**

```python
# iris_gateway.py - Update message type checks
if msg_type in ["select_category", "select_subnode", "go_back"]:
    await self._handle_navigation(session_id, client_id, message)

# _handle_navigation method
async def _handle_navigation(self, session_id: str, client_id: str, message: dict) -> None:
    msg_type = message.get("type")
    
    if msg_type == "select_category":
        category = message.get("category") or message.get("payload", {}).get("category")
        # Handle category selection...
        
    elif msg_type == "select_subnode":
        subnode_id = message.get("subnode_id") or message.get("payload", {}).get("subnode_id")
        # Handle subnode selection...
```

**Alternative: Support both naming conventions (Backward Compatible)**

```python
# Accept both select_* and set_* for transition period
if msg_type in ["select_category", "set_category"]:
    await self._handle_category_selection(session_id, client_id, message)
```

### Files Modified
- `IRISVOICE/backend/iris_gateway.py` - Add support for `select_*` message types

---

## GAP-03: Missing WebSocket Event Dispatches Fix

### Root Cause Analysis
- `useIRISWebSocket.ts` receives voice state and field updates
- No CustomEvent dispatch for `iris:voice_state_change` and `iris:field_updated`
- SidePanel cannot react to these changes

### Proposed Fix

**Add event dispatches in message handler:**

```typescript
// useIRISWebSocket.ts - Add to handleMessage switch statement

case "listening_state": {
  if (payload.state) {
    const newState = payload.state as VoiceState
    setVoiceState(newState)
    
    // Dispatch for SidePanel and other listeners
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('iris:voice_state_change', {
        detail: { state: newState }
      }))
    }
    
    // Reset audio level when leaving listening state
    if (newState !== "listening") {
      setAudioLevel(0)
    }
  }
  break
}

case "field_updated": {
  const { subnode_id, field_id, value, timestamp } = payload as { 
    subnode_id: string; 
    field_id: string; 
    value: string | number | boolean;
    timestamp?: number;
  }
  
  // Existing update logic...
  
  // Dispatch for SidePanel
  if (typeof window !== 'undefined' && subnode_id && field_id) {
    window.dispatchEvent(new CustomEvent('iris:field_updated', {
      detail: { subnode_id, field_id, value, timestamp }
    }))
  }
  
  break
}
```

### Files Modified
- `IRISVOICE/hooks/useIRISWebSocket.ts` - Add CustomEvent dispatches

---

## GAP-04: Backend Messages Without Frontend Handlers Fix

### Root Cause Analysis
- Backend sends messages that frontend doesn't handle
- Either add handlers or remove unused backend message types

### Proposed Fix

**Add missing handlers in useIRISWebSocket.ts:**

```typescript
// Add cases for missing message types

case "subnodes": {
  // Handle subnodes response
  if (payload.subnodes && Array.isArray(payload.subnodes)) {
    setSubnodes((prev) => ({
      ...prev,
      [currentCategory]: payload.subnodes
    }))
  }
  break
}

case "model_selection_updated": {
  // Handle model selection update
  console.log("[IRIS WebSocket] Model selection updated:", payload)
  break
}

case "wake_word_selected": {
  // Handle wake word selection
  console.log("[IRIS WebSocket] Wake word selected:", payload)
  break
}

case "cleanup_report":
case "cleanup_result": {
  // Handle cleanup operations
  console.log("[IRIS WebSocket] Cleanup result:", payload)
  break
}

case "category_expanded": {
  // Handle category expansion
  console.log("[IRIS WebSocket] Category expanded")
  break
}
```

### Files Modified
- `IRISVOICE/hooks/useIRISWebSocket.ts` - Add message handlers

---

## GAP-05: State Update Message Format Fix

### Root Cause Analysis
- Backend sends `state_update`, frontend expects `state_sync`
- Different formats: full state vs key/value updates

### Proposed Fix

**Option A: Change backend to match frontend (Recommended)**

```python
# iris_gateway.py - Change message type
await self._ws_manager.broadcast_to_session(
    session_id,
    {
        "type": "state_sync",  # Changed from "state_update"
        "state": state.model_dump()  # Always send full state
    },
    exclude_clients={exclude_client}
)
```

**Option B: Support both types (Backward Compatible)**

```typescript
// useIRISWebSocket.ts - Handle both types
case "state_update":
case "state_sync": {
  // Unified handling for both message types
  const state: IRISState = payload.state as IRISState
  if (state) {
    // Update all state fields
  }
  break
}
```

### Files Modified
- `IRISVOICE/backend/iris_gateway.py` - Change `state_update` to `state_sync`
- `IRISVOICE/hooks/useIRISWebSocket.ts` - Ensure handler supports correct format

---

## GAP-06: Voice Callback Unregistration Fix

### Root Cause Analysis
- Callbacks registered in `_handle_voice()` never unregistered
- Memory leaks on session end or disconnect

### Proposed Fix

**Track and cleanup callbacks:**

```python
# iris_gateway.py - Add callback tracking

class IRISGateway:
    def __init__(self, ...):
        # ... existing init ...
        self._voice_callbacks: Dict[str, Dict[str, Any]] = {}
    
    async def _handle_voice(self, session_id: str, client_id: str, message: dict) -> None:
        # ... existing code ...
        
        if success:
            # Create callbacks
            async def state_change_callback(state: VoiceState) -> None:
                await self._on_voice_state_change(session_id, state)
            
            async def audio_level_callback(level: float) -> None:
                await self._on_audio_level_update(session_id, level)
            
            # Register and track callbacks
            self._voice_pipeline.register_state_callback(session_id, state_change_callback)
            self._voice_pipeline.register_audio_level_callback(session_id, audio_level_callback)
            
            # Store references for cleanup
            self._voice_callbacks[session_id] = {
                "state": state_change_callback,
                "audio": audio_level_callback
            }
    
    async def cleanup_session(self, session_id: str) -> None:
        """Cleanup voice callbacks for session."""
        if session_id in self._voice_callbacks:
            callbacks = self._voice_callbacks.pop(session_id)
            self._voice_pipeline.unregister_state_callback(session_id, callbacks["state"])
            self._voice_pipeline.unregister_audio_level_callback(session_id, callbacks["audio"])
            self._logger.info(f"Cleaned up voice callbacks for session {session_id}")
```

**Add unregister methods to voice_pipeline.py:**

```python
# voice_pipeline.py

def unregister_state_callback(self, session_id: str, callback: Callable) -> None:
    """Unregister a state callback for session."""
    if session_id in self._state_callbacks:
        self._state_callbacks[session_id].discard(callback)

def unregister_audio_level_callback(self, session_id: str, callback: Callable) -> None:
    """Unregister an audio level callback for session."""
    if session_id in self._audio_level_callbacks:
        self._audio_level_callbacks[session_id].discard(callback)
```

### Files Modified
- `IRISVOICE/backend/iris_gateway.py` - Add callback tracking and cleanup
- `IRISVOICE/backend/voice/voice_pipeline.py` - Add unregister methods

---

## GAP-07: BUG-06 Verification

### Verification Approach

**Audit WheelView.tsx for all Card types:**

```typescript
// Check handleValueChange in WheelView.tsx
const handleValueChange = useCallback((fieldId: string, value: FieldValue) => {
  // Should use CARD_TO_SECTION_ID for ALL cards
  const sectionId = CARD_TO_SECTION_ID[miniNode.id]
  if (sectionId) {
    sendMessage('update_field', {
      subnode_id: sectionId,
      field_id: fieldId,
      value: value
    })
  }
}, [miniNode.id, sendMessage])
```

**Verify no hardcoded Card IDs:**
- Search for hardcoded Card ID checks
- Ensure all Cards use `CARD_TO_SECTION_ID` mapping

### Files to Review
- `IRISVOICE/components/wheel-view/WheelView.tsx` - Verify all cards send updates

---

## GAP-08: Error Handler Fix

### Proposed Fix

**Add error handler in useIRISWebSocket.ts:**

```typescript
case "error": {
  const errorMessage = payload.message || payload.error || "Unknown error"
  console.error("[IRIS WebSocket] Backend error:", errorMessage, payload)
  setLastError(typeof errorMessage === 'string' ? errorMessage : "Unknown error")
  break
}
```

### Files Modified
- `IRISVOICE/hooks/useIRISWebSocket.ts` - Add error case handler

---

## GAP-09: Validation Error Format Fix

### Proposed Fix

**Update backend to use flat payload:**

```python
# iris_gateway.py - Change from nested to flat
await self._send_validation_error(client_id, field_id, error_message)

async def _send_validation_error(self, client_id: str, field_id: str, error: str) -> None:
    """Send validation error with flat payload structure."""
    await self._ws_manager.send_to_client(client_id, {
        "type": "validation_error",
        "field_id": field_id,  # Flat, not nested
        "error": error  # Flat, not nested
    })
```

### Files Modified
- `IRISVOICE/backend/iris_gateway.py` - Fix payload structure

---

## GAP-10: Theme Update Format Fix

### Proposed Fix

**Unify theme update format in iris_gateway.py:**

```python
# iris_gateway.py - Change to direct properties
await self._ws_manager.broadcast_to_session(
    session_id,
    {
        "type": "theme_updated",
        "glow": glow_color,  # Direct, not nested
        "font": font_color,
        "state_colors_enabled": state_colors.get("enabled") if state_colors else None
    }
)
```

### Files Modified
- `IRISVOICE/backend/iris_gateway.py` - Change theme_updated format

---

## GAP-11: Session Cleanup Fix

### Proposed Fix

**Add disconnect handler:**

```python
# main.py - Add cleanup on disconnect

try:
    while True:
        data = await websocket.receive_text()
        message = json.loads(data)
        await handle_message(client_id, active_session_id, message)

except WebSocketDisconnect:
    logger.info(f"Client {client_id} disconnected.")
    await iris_gateway.cleanup_session(active_session_id)  # Add cleanup
    
finally:
    ws_manager.disconnect(client_id)
    await iris_gateway.cleanup_session(active_session_id)  # Ensure cleanup
```

### Files Modified
- `IRISVOICE/backend/main.py` - Add cleanup calls

---

## GAP-12: Field Update Timestamp Fix

### Proposed Fix

**Add timestamp to main.py field update:**

```python
# main.py - Add timestamp
await ws_manager.send_to_client(client_id, {
    "type": "field_updated",
    "subnode_id": subnode_id,
    "field_id": field_id,
    "value": value,
    "timestamp": int(time.time() * 1000)  # Add timestamp
})
```

### Files Modified
- `IRISVOICE/backend/main.py` - Add timestamp import and field

---

## Integration Testing Strategy

### Test Order
1. Message routing consolidation (GAP-01)
2. Message type compatibility (GAP-02)
3. State synchronization (GAP-05, GAP-12)
4. Event dispatching (GAP-03)
5. Message handlers (GAP-04, GAP-08)
6. Error handling (GAP-09)
7. Resource cleanup (GAP-06, GAP-11)
8. Format consistency (GAP-10)
9. Card verification (GAP-07)

### Key Test Scenarios
- Send `select_category` from frontend, verify backend receives and processes
- Verify `iris:voice_state_change` events fire correctly
- Disconnect client, verify callbacks are cleaned up
- Send validation error, verify frontend receives flat payload
- Update theme, verify consistent format from both handlers

---

## Files Modified Summary

| File | GAPs Addressed |
|------|----------------|
| `backend/main.py` | GAP-01, GAP-11, GAP-12 |
| `backend/iris_gateway.py` | GAP-01, GAP-02, GAP-05, GAP-06, GAP-09, GAP-10 |
| `backend/voice/voice_pipeline.py` | GAP-06 |
| `hooks/useIRISWebSocket.ts` | GAP-03, GAP-04, GAP-05, GAP-08 |
| `components/wheel-view/WheelView.tsx` | GAP-07 |

# IRIS Widget Wheel Information Reflection Plan

## Overview
Ensure all field definitions in SUB_NODES are properly bound to actual state management via useIRISWebSocket hook, with bidirectional data flow (read from state, update via API).

## Current State Analysis

### SUB_NODES Structure (6 main categories with subnodes/fields):

**voice**
- connection: endpoint (text)
- parameters: temperature (slider)

**agent**
- identity: assistant_name (text)
- wake: wake_phrase (text)

**settings**
- theme_mode: theme (dropdown)
- startup: launch_startup (toggle)

**memory**
- history: conversation_history (text)

**analytics**
- tokens: token_usage (text)

### useIRISWebSocket Provides:
- `fieldValues` - current field values from WebSocket
- `updateField` - function to update field values
- Currently NOT destructured in HexagonalControlCenter

## Implementation Plan

### Phase 1: Add fieldValues to destructuring
**File**: `components/hexagonal-control-center.tsx`
**Line**: ~484
**Action**: Add `fieldValues` to useIRISWebSocket destructuring

### Phase 2: Create MiniNodeStack component for active subnode
**File**: `components/hexagonal-control-center.tsx`
**Action**: Create component that renders when activeSubnodeId is set
- Shows field inputs from SUB_NODES definition
- Binds values to fieldValues
- Calls updateField on changes

### Phase 3: Implement field value binding
**Fields to bind**:
- voice.endpoint → fieldValues?.voice?.endpoint
- voice.temperature → fieldValues?.voice?.temperature
- agent.assistant_name → fieldValues?.agent?.assistant_name
- agent.wake_phrase → fieldValues?.agent?.wake_phrase
- settings.theme → fieldValues?.settings?.theme
- settings.launch_startup → fieldValues?.settings?.launch_startup
- memory.conversation_history → fieldValues?.memory?.conversation_history
- analytics.token_usage → fieldValues?.analytics?.token_usage

### Phase 4: Position mini node stack
**Logic**: When subnode selected:
- Calculate position at MINI_NODE_STACK_CONFIG.distanceFromCenter
- Render card stack with fields
- Animate in/out with AnimatePresence

## Success Criteria
- [ ] Clicking subnode shows mini stack with input fields
- [ ] Fields display current values from fieldValues
- [ ] Changing field updates via updateField
- [ ] Build passes without errors

## Files to Modify
1. `components/hexagonal-control-center.tsx` - Add fieldValues, create MiniNodeStack, bind fields

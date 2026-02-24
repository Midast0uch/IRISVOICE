# Main Category Settings Display Fix - Bugfix Design

## Overview

This bugfix addresses the issue where clicking any of the 6 main category nodes at Level 2 shows "no setting available for this category" instead of displaying the WheelView with settings. The root cause is that the `SELECT_MAIN` action in the NavigationContext reducer does not populate the `miniNodeStack`, which the WheelView component requires to render the dual-ring mechanism and side panel.

The fix will modify the `SELECT_MAIN` action handler to aggregate all mini-nodes from all sub-nodes under the selected main category, populating the `miniNodeStack` so that the WheelView can display settings immediately when a main category is clicked.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when a user clicks a main category node at Level 2, causing transition to Level 3 with empty `miniNodeStack`
- **Property (P)**: The desired behavior - WheelView displays with populated dual-ring mechanism showing all mini-nodes from the main category
- **Preservation**: Existing navigation flows (GO_BACK, SELECT_SUB, mini-node value persistence) that must remain unchanged by the fix
- **miniNodeStack**: Array of MiniNode objects stored in NavState that the WheelView uses to render the inner ring and side panel
- **SELECT_MAIN**: Redux action dispatched when a main category node is clicked at Level 2
- **handleSelectMain**: Function in NavigationContext that dispatches SELECT_MAIN and sends WebSocket message
- **subnodes**: Data structure from WebSocket containing sub-nodes and their mini-nodes, organized by main category ID
- **navReducer**: The reducer function in NavigationContext.tsx that handles all navigation state transitions

## Bug Details

### Fault Condition

The bug manifests when a user clicks any of the 6 main category nodes (Voice, Agent, Automate, System, Customize, Monitor) at Level 2. The `handleSelectMain` function dispatches the `SELECT_MAIN` action, which transitions to Level 3 but does not populate the `miniNodeStack`. The WheelView component checks if `miniNodeStack.length === 0` and displays "No settings available for this category" instead of rendering the dual-ring mechanism.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { action: NavAction, state: NavState, subnodes: Record<string, any[]> }
  OUTPUT: boolean
  
  RETURN input.action.type === 'SELECT_MAIN'
         AND input.state.level === 2
         AND input.subnodes[input.action.payload.nodeId] EXISTS
         AND input.subnodes[input.action.payload.nodeId].length > 0
         AND (input.state.miniNodeStack.length === 0 OR input.state.miniNodeStack will remain empty after action)
END FUNCTION
```

### Examples

- **Voice Category**: User clicks "Voice" main node → Level 3 with `selectedMain: 'voice'` but `miniNodeStack: []` → WheelView shows "No settings available"
- **Agent Category**: User clicks "Agent" main node → Level 3 with `selectedMain: 'agent'` but `miniNodeStack: []` → WheelView shows "No settings available"
- **System Category**: User clicks "System" main node → Level 3 with `selectedMain: 'system'` but `miniNodeStack: []` → WheelView shows "No settings available"
- **Edge Case - Empty Subnodes**: User clicks main category with no subnodes data → Should handle gracefully with empty array

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- GO_BACK action must continue to transition from Level 3 to Level 2 correctly, clearing miniNodeStack
- SELECT_SUB action (if still used) must continue to populate miniNodeStack with that sub-node's mini-nodes
- WheelView rendering with populated miniNodeStack must continue to work correctly
- Mini-node value updates and persistence to localStorage must continue to work
- WebSocket message sending in handleSelectMain must continue to work
- Confirmed nodes orbit functionality must remain unchanged

**Scope:**
All navigation actions that do NOT involve SELECT_MAIN should be completely unaffected by this fix. This includes:
- EXPAND_TO_MAIN action
- GO_BACK action from any level
- COLLAPSE_TO_IDLE action
- All mini-node stack rotation actions (ROTATE_STACK_FORWARD, ROTATE_STACK_BACKWARD, JUMP_TO_MINI_NODE)
- CONFIRM_MINI_NODE and UPDATE_MINI_NODE_VALUE actions
- SET_VIEW and SET_MAIN_VIEW actions

## Hypothesized Root Cause

Based on the bug description and code analysis, the root cause is:

1. **Missing miniNodeStack Population in SELECT_MAIN**: The `SELECT_MAIN` case in navReducer only sets `level: 3` and `selectedMain` but does not populate `miniNodeStack`. The original design assumed users would always select a sub-node first (via SELECT_SUB), which would populate the stack.

2. **Direct Main Category Selection Flow**: The hexagonal-control-center component allows direct main category clicks at Level 2, which calls `handleSelectMain(nodeId)`. This bypasses the sub-node selection flow entirely.

3. **WheelView Empty State Check**: WheelView correctly checks `if (miniNodeStack.length === 0)` and shows the empty state message, but the upstream navigation flow never populates the stack for main category selections.

4. **Subnodes Data Available**: The WebSocket hook provides `subnodes` data structure organized by main category ID, containing all sub-nodes and their mini-nodes. This data is available in NavigationContext but not used during SELECT_MAIN.

## Correctness Properties

Property 1: Fault Condition - Main Category Click Populates Mini-Nodes

_For any_ SELECT_MAIN action where the main category has associated sub-nodes with mini-nodes in the subnodes data structure, the navReducer SHALL populate miniNodeStack with all mini-nodes aggregated from all sub-nodes under that main category, enabling the WheelView to display the dual-ring mechanism with settings.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Non-SELECT_MAIN Navigation Behavior

_For any_ navigation action that is NOT SELECT_MAIN (including GO_BACK, SELECT_SUB, EXPAND_TO_MAIN, COLLAPSE_TO_IDLE, and all mini-node stack actions), the navReducer SHALL produce exactly the same state transitions as before the fix, preserving all existing navigation flows, mini-node value persistence, and WheelView rendering behavior.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `IRISVOICE/contexts/NavigationContext.tsx`

**Function**: `navReducer` (specifically the `SELECT_MAIN` case)

**Specific Changes**:

1. **Access Subnodes Data**: The navReducer needs access to the `subnodes` data structure from WebSocket. This requires either:
   - Passing subnodes as a parameter to navReducer (requires refactoring dispatch calls)
   - OR storing subnodes in NavState (simpler, follows Redux pattern)
   - OR creating a helper function outside the reducer that prepares the miniNodeStack before dispatching

2. **Aggregate Mini-Nodes**: When SELECT_MAIN is dispatched, iterate through all sub-nodes under the selected main category and collect all their mini-nodes into a single array:
   ```typescript
   const allMiniNodes: MiniNode[] = []
   const categorySubnodes = subnodes[action.payload.nodeId] || []
   for (const subnode of categorySubnodes) {
     if (subnode.miniNodes && Array.isArray(subnode.miniNodes)) {
       allMiniNodes.push(...subnode.miniNodes)
     }
   }
   ```

3. **Populate miniNodeStack**: Set `miniNodeStack: allMiniNodes` in the nextState for SELECT_MAIN action

4. **Set activeMiniNodeIndex**: Initialize `activeMiniNodeIndex: 0` to select the first mini-node

5. **Handle Empty Case**: If no mini-nodes are found, set `miniNodeStack: []` (current behavior, WheelView will show empty state)

**Recommended Approach**: Modify `handleSelectMain` in NavigationProvider to prepare the miniNodeStack before dispatching:

```typescript
const handleSelectMain = useCallback((nodeId: string) => {
  // Aggregate all mini-nodes from all sub-nodes under this main category
  const allMiniNodes: MiniNode[] = []
  const categorySubnodes = subnodes[nodeId] || []
  
  for (const subnode of categorySubnodes) {
    if (subnode.miniNodes && Array.isArray(subnode.miniNodes)) {
      allMiniNodes.push(...subnode.miniNodes)
    }
  }
  
  // Dispatch with aggregated mini-nodes
  dispatch({ 
    type: 'SELECT_MAIN', 
    payload: { nodeId, miniNodes: allMiniNodes } 
  })
  sendMessage('select_category', { category: nodeId })
}, [subnodes, sendMessage])
```

**Alternative Approach**: If subnodes structure doesn't contain miniNodes, we may need to:
- Fetch mini-nodes from a separate data source
- OR auto-select the first sub-node and use its mini-nodes
- OR modify the backend to include mini-nodes in the subnodes structure

### Action Type Update

**File**: `IRISVOICE/types/navigation.ts` (or wherever NavAction is defined)

**Change**: Update SELECT_MAIN action payload to include optional miniNodes:
```typescript
| { type: 'SELECT_MAIN'; payload: { nodeId: string; miniNodes?: MiniNode[] } }
```

### Reducer Update

**File**: `IRISVOICE/contexts/NavigationContext.tsx`

**Function**: `navReducer` - SELECT_MAIN case

**Change**: Use the miniNodes from payload if provided:
```typescript
case 'SELECT_MAIN': {
  const miniNodes = action.payload.miniNodes || []
  nextState = {
    ...state,
    level: 3,
    selectedMain: action.payload.nodeId,
    miniNodeStack: miniNodes,
    activeMiniNodeIndex: miniNodes.length > 0 ? 0 : state.activeMiniNodeIndex,
    history: [...state.history, { level: 2, nodeId: null }],
    transitionDirection: 'forward',
  }
  break
}
```

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Fault Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that simulate clicking each main category node at Level 2 and assert that miniNodeStack is populated with mini-nodes. Run these tests on the UNFIXED code to observe failures and understand the root cause.

**Test Cases**:
1. **Voice Category Test**: Click "Voice" main node at Level 2 → Assert miniNodeStack contains mini-nodes from Input, Output, Processing, Model sub-nodes (will fail on unfixed code - miniNodeStack will be empty)
2. **Agent Category Test**: Click "Agent" main node at Level 2 → Assert miniNodeStack contains mini-nodes from Identity, Wake, Speech, Memory sub-nodes (will fail on unfixed code)
3. **System Category Test**: Click "System" main node at Level 2 → Assert miniNodeStack contains mini-nodes from Power, Display, Storage, Network sub-nodes (will fail on unfixed code)
4. **Empty Subnodes Test**: Click main category with no subnodes data → Assert miniNodeStack is empty array and WheelView shows empty state (may pass on unfixed code)

**Expected Counterexamples**:
- miniNodeStack remains empty `[]` after SELECT_MAIN action is dispatched
- WheelView displays "No settings available for this category" message
- Possible causes: SELECT_MAIN doesn't populate miniNodeStack, subnodes data not accessible in reducer, miniNodes not present in subnodes structure

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL mainCategoryId WHERE subnodes[mainCategoryId] EXISTS AND has miniNodes DO
  initialState := { level: 2, selectedMain: null, miniNodeStack: [] }
  action := { type: 'SELECT_MAIN', payload: { nodeId: mainCategoryId, miniNodes: aggregatedMiniNodes } }
  
  result := navReducer_fixed(initialState, action)
  
  ASSERT result.level === 3
  ASSERT result.selectedMain === mainCategoryId
  ASSERT result.miniNodeStack.length > 0
  ASSERT result.activeMiniNodeIndex === 0
  ASSERT WheelView renders dual-ring mechanism (not empty state)
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL action WHERE action.type !== 'SELECT_MAIN' DO
  FOR ALL state IN validNavStates DO
    ASSERT navReducer_original(state, action) === navReducer_fixed(state, action)
  END FOR
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-SELECT_MAIN actions

**Test Plan**: Observe behavior on UNFIXED code first for GO_BACK, SELECT_SUB, and mini-node operations, then write property-based tests capturing that behavior.

**Test Cases**:
1. **GO_BACK Preservation**: Observe that GO_BACK from Level 3 to Level 2 clears miniNodeStack on unfixed code, then write test to verify this continues after fix
2. **SELECT_SUB Preservation**: Observe that SELECT_SUB populates miniNodeStack with sub-node's mini-nodes on unfixed code, then write test to verify this continues after fix
3. **Mini-Node Value Persistence**: Observe that UPDATE_MINI_NODE_VALUE persists to localStorage on unfixed code, then write test to verify this continues after fix
4. **WheelView Rendering Preservation**: Observe that WheelView renders correctly with populated miniNodeStack on unfixed code, then write test to verify this continues after fix

### Unit Tests

- Test SELECT_MAIN action with each main category (Voice, Agent, Automate, System, Customize, Monitor)
- Test SELECT_MAIN with empty subnodes data (edge case)
- Test that miniNodeStack is correctly aggregated from all sub-nodes
- Test that activeMiniNodeIndex is set to 0 when miniNodeStack is populated
- Test that GO_BACK from Level 3 still clears miniNodeStack correctly

### Property-Based Tests

- Generate random main category selections and verify miniNodeStack is always populated when subnodes exist
- Generate random navigation sequences (EXPAND_TO_MAIN → SELECT_MAIN → GO_BACK) and verify state consistency
- Generate random mini-node value updates and verify persistence works correctly after fix
- Test that all non-SELECT_MAIN actions produce identical results before and after fix

### Integration Tests

- Test full navigation flow: Level 1 → Level 2 → Click main category → Level 3 with WheelView showing settings
- Test switching between main categories and verify miniNodeStack updates correctly
- Test that confirmed nodes orbit continues to work after main category selection
- Test that WebSocket messages are sent correctly when main categories are clicked

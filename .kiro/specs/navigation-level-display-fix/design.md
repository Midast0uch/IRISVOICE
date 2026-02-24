# Navigation Level Display Fix - Bugfix Design

## Overview

The navigation system fails to display nodes at levels 3 and 4 due to a combination of issues: (1) the HexagonalControlCenter component relies on WebSocket-provided subnodes data that may be empty when the backend is offline, (2) there's no fallback to hardcoded subnode data when WebSocket data is unavailable, and (3) the component's rendering logic at level 3 depends on data that isn't guaranteed to exist. This prevents users from accessing folder/file configuration interfaces and mininode settings.

The fix will add fallback subnode data directly in the HexagonalControlCenter component, ensuring navigation levels 3 and 4 display correctly regardless of WebSocket connection status.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when navigation level 3 or 4 nodes fail to render in the DOM
- **Property (P)**: The desired behavior - level 3 and 4 nodes should render with their associated UI elements visible and interactive
- **Preservation**: Existing level 1 and 2 navigation behavior, WebSocket integration, and state management that must remain unchanged
- **HexagonalControlCenter**: The component in `components/hexagonal-control-center.tsx` that renders navigation nodes at levels 2 and 3
- **subnodes**: The data structure containing child nodes for each main category, sourced from WebSocket via NavigationContext
- **NavigationContext**: The context provider in `contexts/NavigationContext.tsx` that manages navigation state and WebSocket integration
- **Level 3**: Navigation level showing folders/files with data fields when a main category node is clicked
- **Level 4**: Navigation level showing mininode stack and compact accordion when a level 3 node is clicked

## Bug Details

### Fault Condition

The bug manifests when a user clicks on one of the 6 main category nodes at navigation level 2, expecting to see level 3 subnodes orbit around the selected main node. The HexagonalControlCenter component attempts to render subnodes by accessing `nav.subnodes[nav.state.selectedMain]`, but this data structure is empty when the WebSocket connection fails or the backend doesn't send subnode data. This results in an empty array being mapped, causing zero nodes to render in the DOM.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type { level: NavigationLevel, selectedMain: string | null, subnodes: Record<string, any[]> }
  OUTPUT: boolean
  
  RETURN input.level === 3
         AND input.selectedMain !== null
         AND (input.subnodes[input.selectedMain] === undefined 
              OR input.subnodes[input.selectedMain].length === 0)
         AND userExpectsSubnodesToRender()
END FUNCTION
```

### Examples

- User clicks "VOICE" main node → Level changes to 3 → `nav.subnodes["VOICE"]` is undefined or empty → No subnodes render → Only the "VOICE" label appears in the center orb
- User clicks "AGENT" main node → Level changes to 3 → `nav.subnodes["AGENT"]` is undefined or empty → No subnodes render → Cannot access personality/knowledge/behavior/memory settings
- User clicks "CUSTOMIZE" main node → Level changes to 3 → `nav.subnodes["CUSTOMIZE"]` is undefined or empty → No subnodes render → Cannot access theme/layout/widgets/shortcuts
- WebSocket connection fails (ERR_CONNECTION_REFUSED) → `subnodes` remains empty object `{}` → All level 3 navigation attempts fail

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Navigation at level 1 (idle IRIS orb) must continue to display correctly
- Navigation at level 2 (6 main category nodes) must continue to display correctly with proper hexagonal positioning
- WebSocket integration must continue to work when backend is available, allowing dynamic subnode updates
- State management and transition animations must remain unchanged
- The NavigationContext reducer logic must remain unchanged
- Level 4 rendering logic (mininode stack and compact accordion) must remain unchanged

**Scope:**
All inputs that do NOT involve navigating to level 3 with missing subnode data should be completely unaffected by this fix. This includes:
- Level 1 and level 2 navigation
- WebSocket message handling
- State persistence to localStorage
- Transition animations and timing
- Level 4 navigation (once level 3 is fixed)

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **Missing Fallback Data**: The HexagonalControlCenter component has hardcoded MAIN_NODES and SUB_NODES constants defined at the top of the file, but the component's rendering logic at level 3 uses `nav.subnodes` from the WebSocket context instead of the local SUB_NODES constant. When WebSocket data is unavailable, `nav.subnodes` is an empty object.

2. **WebSocket Dependency**: The NavigationContext provides `subnodes` from the useIRISWebSocket hook, which initializes as an empty object `{}` and only populates when the backend sends subnode data. The WebSocket connection errors (ERR_CONNECTION_REFUSED to ws://localhost:8000/ws/iris) indicate the backend is not running or not accessible.

3. **No Graceful Degradation**: There's no fallback mechanism to use the hardcoded SUB_NODES data when WebSocket data is unavailable. The component should prioritize WebSocket data when available but fall back to local data when not.

4. **Level 4 Cascade Failure**: Since level 3 nodes don't render, users cannot click them to navigate to level 4, making it impossible to test or access the mininode stack and compact accordion components.

## Correctness Properties

Property 1: Fault Condition - Level 3 Nodes Render with Fallback Data

_For any_ navigation state where the user has clicked a main category node (level === 3, selectedMain !== null) and WebSocket subnodes are unavailable or empty, the fixed HexagonalControlCenter component SHALL render the appropriate subnodes from the hardcoded SUB_NODES fallback data, displaying them in orbital positions around the selected main node with proper labels, icons, and click handlers.

**Validates: Requirements 2.1, 2.3**

Property 2: Preservation - WebSocket Data Priority and Existing Navigation

_For any_ navigation state where WebSocket subnodes ARE available (non-empty), the fixed component SHALL continue to use the WebSocket-provided subnodes data, preserving the dynamic data loading behavior. Additionally, for any navigation at levels 1, 2, or 4, the fixed code SHALL produce exactly the same behavior as the original code, preserving all existing navigation, state management, and animation functionality.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `components/hexagonal-control-center.tsx`

**Function**: `HexagonalControlCenter` component (specifically the `currentNodes` useMemo hook)

**Specific Changes**:

1. **Add Fallback Logic**: Modify the `currentNodes` useMemo to check if `nav.subnodes[nav.state.selectedMain]` exists and has length > 0. If not, fall back to the local `SUB_NODES[nav.state.selectedMain]` constant.

2. **Preserve WebSocket Priority**: Ensure WebSocket-provided subnodes are used when available, maintaining the existing dynamic data loading behavior.

3. **Update Subnode Rendering**: Change line ~107 from:
   ```typescript
   const subNodes = nav.subnodes[nav.state.selectedMain] || []
   ```
   to:
   ```typescript
   const subNodes = (nav.subnodes[nav.state.selectedMain]?.length > 0) 
     ? nav.subnodes[nav.state.selectedMain] 
     : (SUB_NODES[nav.state.selectedMain] || [])
   ```

4. **Verify Icon Handling**: Ensure the fallback SUB_NODES data structure matches the expected format with proper icon assignments (currently defaults to Settings icon).

5. **Test Level 4 Access**: Once level 3 nodes render, verify that clicking them properly transitions to level 4 with mininode stack or compact accordion display.

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code by attempting to navigate to level 3 with the backend offline, then verify the fix works correctly with both WebSocket data available and unavailable, while preserving all existing navigation behavior.

### Exploratory Fault Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm that level 3 nodes fail to render when WebSocket subnodes are unavailable.

**Test Plan**: Start the frontend without the backend running (ensuring WebSocket connection fails). Navigate to level 2 by clicking the IRIS orb, then click each of the 6 main category nodes. Inspect the DOM to verify that no subnodes appear at level 3. Run these tests on the UNFIXED code to observe failures and confirm the root cause.

**Test Cases**:
1. **VOICE Category Test**: Click "VOICE" main node → Verify level changes to 3 → Inspect DOM for subnode elements (will fail - no nodes found)
2. **AGENT Category Test**: Click "AGENT" main node → Verify level changes to 3 → Inspect DOM for subnode elements (will fail - no nodes found)
3. **CUSTOMIZE Category Test**: Click "CUSTOMIZE" main node → Verify level changes to 3 → Inspect DOM for subnode elements (will fail - no nodes found)
4. **Console Error Verification**: Check browser console for WebSocket connection errors (ERR_CONNECTION_REFUSED)

**Expected Counterexamples**:
- DOM inspection shows zero HexagonalNode components rendered at level 3
- Console shows "WebSocket connection to 'ws://localhost:8000/ws/iris' failed"
- Only the center orb label changes to the selected category name, but no orbiting nodes appear
- Possible causes: empty `nav.subnodes` object, missing fallback to SUB_NODES constant, WebSocket dependency without graceful degradation

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds (level 3 navigation with missing WebSocket data), the fixed function produces the expected behavior (subnodes render from fallback data).

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := HexagonalControlCenter_fixed(input)
  ASSERT result.renderedNodes.length > 0
  ASSERT result.renderedNodes === SUB_NODES[input.selectedMain]
  ASSERT result.nodesVisibleInDOM === true
END FOR
```

**Test Plan**: With backend offline, navigate to level 3 for each main category and verify subnodes render correctly from fallback data.

**Test Cases**:
1. **VOICE Subnodes Render**: Click "VOICE" → Verify 4 subnodes appear (Input, Output, Processing, Model)
2. **AGENT Subnodes Render**: Click "AGENT" → Verify 4 subnodes appear (Personality, Knowledge, Behavior, Memory)
3. **AUTOMATE Subnodes Render**: Click "AUTOMATE" → Verify 4 subnodes appear (Triggers, Actions, Conditions, Workflows)
4. **SYSTEM Subnodes Render**: Click "SYSTEM" → Verify 4 subnodes appear (Performance, Security, Backup, Updates)
5. **CUSTOMIZE Subnodes Render**: Click "CUSTOMIZE" → Verify 4 subnodes appear (Theme, Layout, Widgets, Shortcuts)
6. **MONITOR Subnodes Render**: Click "MONITOR" → Verify 4 subnodes appear (Dashboard, Logs, Metrics, Alerts)
7. **Level 4 Access**: Click a level 3 subnode → Verify level changes to 4 and appropriate UI renders

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold (WebSocket data available, or navigation at levels 1/2/4), the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT HexagonalControlCenter_original(input) = HexagonalControlCenter_fixed(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Start backend to ensure WebSocket connection succeeds and subnodes are provided dynamically. Verify that the fixed code uses WebSocket data when available. Also test levels 1, 2, and 4 navigation to ensure no regressions.

**Test Cases**:
1. **WebSocket Data Priority**: With backend running, navigate to level 3 → Verify WebSocket-provided subnodes are used (not fallback data)
2. **Level 1 Navigation Preservation**: Verify idle IRIS orb displays correctly and responds to clicks
3. **Level 2 Navigation Preservation**: Verify 6 main category nodes display in hexagonal pattern with correct positioning and animations
4. **Transition Animations Preservation**: Verify forward/backward transitions animate correctly with proper timing
5. **State Persistence Preservation**: Verify navigation state persists to localStorage correctly
6. **Level 4 Navigation Preservation**: Once level 3 works, verify level 4 mininode stack and accordion render correctly

### Unit Tests

- Test HexagonalControlCenter rendering at each navigation level (1, 2, 3, 4)
- Test fallback logic when `nav.subnodes` is empty object
- Test WebSocket data priority when `nav.subnodes` has data
- Test edge case where `nav.subnodes[selectedMain]` is undefined vs empty array
- Test that clicking level 3 subnodes properly transitions to level 4

### Property-Based Tests

- Generate random navigation states with varying `subnodes` data (empty, partial, full) and verify correct rendering
- Generate random main category selections and verify appropriate subnodes render from fallback or WebSocket
- Test that all non-level-3 navigation states produce identical behavior before and after fix

### Integration Tests

- Test full navigation flow from level 1 → 2 → 3 → 4 with backend offline (using fallback data)
- Test full navigation flow from level 1 → 2 → 3 → 4 with backend online (using WebSocket data)
- Test switching between main categories at level 3 and verify subnodes update correctly
- Test that visual feedback (animations, positioning, labels) works correctly at all levels
- Test backward navigation (level 4 → 3 → 2 → 1) preserves state correctly

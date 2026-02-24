# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Fault Condition** - Main Category Click Leaves miniNodeStack Empty
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Test all 6 main categories (Voice, Agent, Automate, System, Customize, Monitor) to ensure reproducibility
  - Test that clicking any main category at Level 2 results in empty miniNodeStack on UNFIXED code
  - Test implementation details from Fault Condition: `isBugCondition(input)` where `input.action.type === 'SELECT_MAIN'` AND `input.state.level === 2` AND subnodes exist but miniNodeStack remains empty
  - The test assertions should match Expected Behavior: miniNodeStack should be populated with aggregated mini-nodes from all sub-nodes
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found (e.g., "Voice category: miniNodeStack = [] instead of containing mini-nodes from Input, Output, Processing, Model sub-nodes")
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 2.1, 2.2, 2.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Non-SELECT_MAIN Navigation Behavior
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy inputs (all actions that are NOT SELECT_MAIN)
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements:
    - GO_BACK action transitions from Level 3 to Level 2 and clears miniNodeStack
    - SELECT_SUB action populates miniNodeStack with that sub-node's mini-nodes
    - Mini-node value updates persist to localStorage correctly
    - WheelView renders correctly with populated miniNodeStack
    - All mini-node stack rotation actions work correctly
    - Confirmed nodes orbit functionality works correctly
  - Property-based testing generates many test cases for stronger guarantees
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 3. Fix for main category settings display

  - [x] 3.1 Update NavAction type definition
    - Modify SELECT_MAIN action payload to include optional miniNodes array
    - Update type: `{ type: 'SELECT_MAIN'; payload: { nodeId: string; miniNodes?: MiniNode[] } }`
    - _Bug_Condition: isBugCondition(input) where input.action.type === 'SELECT_MAIN' AND miniNodeStack remains empty_
    - _Expected_Behavior: miniNodeStack populated with aggregated mini-nodes from all sub-nodes_
    - _Preservation: All non-SELECT_MAIN actions must produce identical state transitions_
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4_

  - [x] 3.2 Modify handleSelectMain to aggregate mini-nodes
    - Access subnodes data structure from WebSocket hook
    - Iterate through all sub-nodes under selected main category
    - Collect all mini-nodes from each sub-node into allMiniNodes array
    - Handle edge case where subnodes[nodeId] is undefined or empty
    - Dispatch SELECT_MAIN with aggregated miniNodes in payload
    - Continue sending WebSocket message as before
    - _Bug_Condition: isBugCondition(input) where subnodes exist but miniNodeStack not populated_
    - _Expected_Behavior: allMiniNodes array contains all mini-nodes from all sub-nodes_
    - _Preservation: WebSocket message sending must continue to work unchanged_
    - _Requirements: 2.1, 2.2, 2.3, 3.1_

  - [x] 3.3 Update navReducer SELECT_MAIN case
    - Extract miniNodes from action.payload (default to empty array if not provided)
    - Set miniNodeStack to miniNodes in nextState
    - Set activeMiniNodeIndex to 0 if miniNodes.length > 0
    - Maintain existing level, selectedMain, history, and transitionDirection logic
    - _Bug_Condition: isBugCondition(input) where SELECT_MAIN doesn't populate miniNodeStack_
    - _Expected_Behavior: nextState.miniNodeStack contains aggregated mini-nodes, activeMiniNodeIndex = 0_
    - _Preservation: All other reducer cases must remain unchanged_
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2_

  - [x] 3.4 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Main Category Click Populates Mini-Nodes
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - Verify miniNodeStack is populated for all 6 main categories
    - Verify activeMiniNodeIndex is set to 0
    - Verify WheelView renders dual-ring mechanism (not empty state)
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.5 Verify preservation tests still pass
    - **Property 2: Preservation** - Non-SELECT_MAIN Navigation Behavior
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm GO_BACK still clears miniNodeStack correctly
    - Confirm SELECT_SUB still works if used
    - Confirm mini-node value persistence still works
    - Confirm WheelView rendering with populated stack still works
    - Confirm all mini-node stack rotation actions still work
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 4. Integration testing

  - [x] 4.1 Test full navigation flow with each main category
    - Test: Level 1 → Level 2 → Click Voice → Level 3 with WheelView showing Voice settings
    - Test: Level 1 → Level 2 → Click Agent → Level 3 with WheelView showing Agent settings
    - Test: Level 1 → Level 2 → Click Automate → Level 3 with WheelView showing Automate settings
    - Test: Level 1 → Level 2 → Click System → Level 3 with WheelView showing System settings
    - Test: Level 1 → Level 2 → Click Customize → Level 3 with WheelView showing Customize settings
    - Test: Level 1 → Level 2 → Click Monitor → Level 3 with WheelView showing Monitor settings
    - Verify WheelView displays dual-ring mechanism with correct mini-nodes for each category
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 4.2 Test switching between main categories
    - Test: Click Voice → verify miniNodeStack populated → Click Agent → verify miniNodeStack updated
    - Test: Click System → verify miniNodeStack populated → Click Customize → verify miniNodeStack updated
    - Verify miniNodeStack updates correctly when switching categories
    - Verify activeMiniNodeIndex resets to 0 on each switch
    - _Requirements: 2.2, 2.3_

  - [x] 4.3 Test confirmed nodes orbit after main category selection
    - Select a main category and populate miniNodeStack
    - Confirm a mini-node (should add to confirmed nodes orbit)
    - Verify confirmed nodes orbit displays correctly
    - Verify orbit persists when navigating back and returning
    - _Requirements: 3.3_

  - [x] 4.4 Test WebSocket message sending
    - Click each main category and verify WebSocket 'select_category' message is sent
    - Verify message payload contains correct category nodeId
    - Verify message sending is not affected by miniNodes aggregation
    - _Requirements: 3.1_

  - [x] 4.5 Test edge case: main category with no subnodes
    - Simulate clicking a main category with empty or undefined subnodes data
    - Verify miniNodeStack is set to empty array
    - Verify WheelView shows "No settings available for this category" message
    - Verify no errors or crashes occur
    - _Requirements: 2.3_

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise

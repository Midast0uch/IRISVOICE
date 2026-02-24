# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Fault Condition** - Level 3 Nodes Fail to Render Without WebSocket Data
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to concrete failing cases - level 3 navigation with empty WebSocket subnodes for each main category
  - Test that when navigating to level 3 with selectedMain set and subnodes empty/undefined, level 3 nodes render in the DOM (from Fault Condition in design)
  - Test all 6 main categories: VOICE, AGENT, AUTOMATE, SYSTEM, CUSTOMIZE, MONITOR
  - Run test on UNFIXED code with backend offline (ensuring WebSocket subnodes are unavailable)
  - **EXPECTED OUTCOME**: Test FAILS (this is correct - it proves the bug exists)
  - Document counterexamples found: which categories fail to render subnodes, DOM inspection results, console errors
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - WebSocket Data Priority and Existing Navigation
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy inputs (levels 1 and 2 navigation, WebSocket connection handling)
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements:
    - Level 1 idle IRIS orb displays correctly
    - Level 2 main category nodes display in hexagonal pattern with correct positioning
    - WebSocket integration continues to work when backend is available
    - State management and transition animations work correctly
    - Navigation state persists to localStorage
  - Property-based testing generates many test cases for stronger guarantees
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 3. Fix for navigation level 3 and 4 display

  - [x] 3.1 Implement fallback logic in HexagonalControlCenter component
    - Modify the `currentNodes` useMemo hook in `components/hexagonal-control-center.tsx`
    - Add fallback logic to check if `nav.subnodes[nav.state.selectedMain]` exists and has length > 0
    - If WebSocket subnodes are unavailable or empty, fall back to local `SUB_NODES[nav.state.selectedMain]` constant
    - Update subnode rendering logic (around line 107) to prioritize WebSocket data when available
    - Change from: `const subNodes = nav.subnodes[nav.state.selectedMain] || []`
    - Change to: `const subNodes = (nav.subnodes[nav.state.selectedMain]?.length > 0) ? nav.subnodes[nav.state.selectedMain] : (SUB_NODES[nav.state.selectedMain] || [])`
    - Verify icon handling in fallback SUB_NODES data structure matches expected format
    - _Bug_Condition: isBugCondition(input) where input.level === 3 AND input.selectedMain !== null AND (input.subnodes[input.selectedMain] === undefined OR input.subnodes[input.selectedMain].length === 0)_
    - _Expected_Behavior: Level 3 nodes render from fallback SUB_NODES data when WebSocket subnodes unavailable, with proper labels, icons, and click handlers_
    - _Preservation: WebSocket data priority when available, levels 1/2/4 navigation unchanged, state management unchanged, animations unchanged_
    - _Requirements: 2.1, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5_

  - [x] 3.2 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Level 3 Nodes Render with Fallback Data
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1 with backend offline
    - Verify all 6 main categories now render their subnodes at level 3
    - Verify subnodes are visible in DOM with correct labels and icons
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.3_

  - [x] 3.3 Verify preservation tests still pass
    - **Property 2: Preservation** - WebSocket Data Priority and Existing Navigation
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - Test with backend online to verify WebSocket data is still prioritized over fallback
    - Verify levels 1 and 2 navigation still works identically to unfixed code
    - Verify state management, animations, and localStorage persistence unchanged
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

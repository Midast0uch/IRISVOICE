# Implementation Plan: Navigation Level Consolidation

## Overview

This implementation plan refactors the IRISVOICE navigation system from 4 levels to 3 levels by eliminating Level 4 and integrating mini-node labels into the Level 3 orbital ring with a side panel for input fields. The implementation preserves all 52 mini-nodes and 61 input fields while simplifying the navigation hierarchy.

## Tasks

- [ ] 1. Update NavigationContext state management for 3-level navigation
  - [ ] 1.1 Update NavigationLevel type from `1 | 2 | 3 | 4` to `1 | 2 | 3`
    - Modify type definition in NavigationContext
    - _Requirements: 1.1, 4.1_
  
  - [ ] 1.2 Update SELECT_SUB action to stay at Level 3 instead of transitioning to Level 4
    - Modify reducer to set level to 3 when sub-node is selected
    - Ensure miniNodeStack is populated at Level 3
    - _Requirements: 1.3, 1.4, 4.2_
  
  - [ ] 1.3 Update GO_BACK action to transition from Level 3 to Level 2
    - Modify reducer to handle backward navigation from Level 3
    - Clear miniNodeStack and selectedSub when going back
    - _Requirements: 4.3_
  
  - [ ] 1.4 Remove level4ViewMode state property and SET_LEVEL4_VIEW_MODE action
    - Remove from NavState interface
    - Remove from reducer
    - _Requirements: 1.2, 6.5_
  
  - [ ]* 1.5 Write property test for three-level navigation constraint
    - **Property 1: Three-Level Navigation Constraint**
    - **Validates: Requirements 1.1, 1.3, 1.4**
    - Test that navigation state level is always 1, 2, or 3
  
  - [ ]* 1.6 Write property test for GO_BACK from Level 3
    - **Property 8: GO_BACK from Level 3 Transitions to Level 2**
    - **Validates: Requirements 4.3**
    - Test that GO_BACK action from Level 3 always transitions to Level 2

- [ ] 2. Implement state validation and migration functions
  - [ ] 2.1 Create validateNavState function for 3-level validation
    - Validate level is between 1 and 3
    - Validate Level 3 requires selectedMain
    - _Requirements: 4.5, 4.6_
  
  - [ ] 2.2 Create migrateNavState function for backward compatibility
    - Normalize Level 4 to Level 3
    - Normalize invalid levels (0 or > 3) to Level 1
    - Remove obsolete level4ViewMode property
    - Preserve miniNodeValues regardless of level
    - _Requirements: 10.1, 10.2, 10.3, 10.4_
  
  - [ ]* 2.3 Write property test for Level 4 state migration
    - **Property 19: Level 4 State Migration to Level 3**
    - **Validates: Requirements 10.1**
    - Test that any stored state with level=4 migrates to level=3
  
  - [ ]* 2.4 Write property test for mini-node values preservation during migration
    - **Property 20: Mini-Node Values Preserved During Migration**
    - **Validates: Requirements 10.2**
    - Test that miniNodeValues are preserved regardless of stored level
  
  - [ ]* 2.5 Write property test for invalid level normalization
    - **Property 21: Invalid Level Normalization**
    - **Validates: Requirements 10.4**
    - Test that levels < 1 or > 3 normalize to level 1
  
  - [ ]* 2.6 Write unit test for Level 3 validation requiring selectedMain
    - **Property 10: Level 3 Validation Requires selectedMain**
    - **Validates: Requirements 4.5**
    - Test that validateNavState returns false when level=3 and selectedMain is null

- [ ] 3. Create OrbitalRingWithMiniNodes component
  - [ ] 3.1 Create component file and interface
    - Create IRISVOICE/components/orbital-ring-with-mini-nodes.tsx
    - Define OrbitalRingWithMiniNodesProps interface
    - _Requirements: 2.1_
  
  - [ ] 3.2 Implement mini-node distribution logic across inner and outer rings
    - Calculate splitPoint as ceil(miniNodes.length / 2)
    - Split miniNodes into outerRingNodes and innerRingNodes
    - Calculate segment angles for each ring
    - _Requirements: 2.2_
  
  - [ ] 3.3 Implement SVG rendering with curved text paths
    - Create arc path definitions for each mini-node segment
    - Render inner and outer ring circles
    - Render mini-node labels using textPath elements
    - Add click handlers for mini-node selection
    - _Requirements: 2.1, 2.3_
  
  - [ ] 3.4 Implement rotation animation to position selected node at top
    - Calculate rotation angle based on selected index
    - Use framer-motion for spring physics animation (stiffness: 80, damping: 16)
    - Position selected node at 12 o'clock
    - _Requirements: 2.5, 9.1_
  
  - [ ] 3.5 Add selection indicator and theme color integration
    - Render selection indicator at 12 o'clock position
    - Apply theme glow color to rings, segments, and highlights
    - Use hexToRgba for alpha-blended colors
    - _Requirements: 2.4, 7.1, 7.6_
  
  - [ ] 3.6 Add decorative rings with ambient animation
    - Render decorative rings with continuous rotation
    - Use different rotation speeds for visual depth
    - _Requirements: 9.6_
  
  - [ ]* 3.7 Write property test for mini-node distribution
    - **Property 2: Mini-Node Distribution Across Rings**
    - **Validates: Requirements 2.2**
    - Test that for any count n, outer ring has ceil(n/2) and inner ring has remaining
  
  - [ ]* 3.8 Write property test for rotation positioning
    - **Property 4: Rotation Positions Selected Node at Top**
    - **Validates: Requirements 2.5**
    - Test that rotation angle correctly positions selected node at 12 o'clock
  
  - [ ]* 3.9 Write unit test for mini-node selection
    - **Property 3: Mini-Node Selection Updates State**
    - **Validates: Requirements 2.3**
    - Test that clicking a mini-node updates activeMiniNodeIndex

- [ ] 4. Create MiniNodeSidePanel component
  - [ ] 4.1 Create component file and interface
    - Create IRISVOICE/components/mini-node-side-panel.tsx
    - Define MiniNodeSidePanelProps interface
    - _Requirements: 3.1_
  
  - [ ] 4.2 Implement panel layout with header and field container
    - Position panel adjacent to orbital ring
    - Add fade-in/scale animation (300ms)
    - Render mini-node icon and label in header
    - _Requirements: 3.1, 9.2_
  
  - [ ] 4.3 Create FieldRenderer component for all field types
    - Implement text input rendering
    - Implement slider rendering with value display
    - Implement dropdown rendering with options
    - Implement toggle rendering with animation
    - Implement color picker rendering
    - _Requirements: 3.2_
  
  - [ ] 4.4 Implement field value change handlers
    - Connect onChange handlers to updateMiniNodeValue
    - Update miniNodeValues in navigation state
    - _Requirements: 3.3_
  
  - [ ] 4.5 Add confirm button with animation
    - Render confirm button at bottom of panel
    - Trigger 360° orbital ring spin on confirm (800ms, easeInOut)
    - Trigger connection line retraction animation
    - Persist values to localStorage
    - _Requirements: 3.4, 3.5, 9.4, 9.5_
  
  - [ ] 4.6 Implement crossfade animation for mini-node changes
    - Use AnimatePresence with mode="wait"
    - Crossfade field content over 200ms
    - _Requirements: 3.7, 9.3_
  
  - [ ] 4.7 Apply theme colors and transparent backgrounds
    - Use theme glow color for borders and accents
    - Apply transparent backgrounds with backdrop blur
    - Ensure reactive color updates on theme change
    - _Requirements: 7.2, 7.4, 7.5_
  
  - [ ]* 4.8 Write property test for all fields rendered
    - **Property 5: All Fields Rendered for Selected Mini-Node**
    - **Validates: Requirements 3.1**
    - Test that for any mini-node with k fields, exactly k field controls are rendered
  
  - [ ]* 4.9 Write property test for field value updates
    - **Property 6: Field Value Updates Propagate to State**
    - **Validates: Requirements 3.3**
    - Test that modifying any field updates miniNodeValues[nodeId][fieldId]
  
  - [ ]* 4.10 Write unit test for all field types rendering
    - Test that text, slider, dropdown, toggle, and color fields render correctly
    - Verify each field type has appropriate input element
  
  - [ ]* 4.11 Write unit test for crossfade animation
    - **Property 7: Side Panel Crossfade on Mini-Node Change**
    - **Validates: Requirements 3.7**
    - Test that selecting different mini-nodes triggers crossfade

- [ ] 5. Create ConnectionLine component
  - [ ] 5.1 Create component file and interface
    - Create IRISVOICE/components/connection-line.tsx
    - Define ConnectionLineProps interface
    - _Requirements: 3.5_
  
  - [ ] 5.2 Implement animated glowing line
    - Render base line with gradient using theme glow color
    - Add glow effect with blur filter
    - Add animated pulse effect (2s loop)
    - _Requirements: 7.2_
  
  - [ ] 5.3 Implement retraction animation
    - Use scaleX animation with spring physics
    - Trigger retraction on confirm button click
    - _Requirements: 9.5_

- [ ] 6. Create Level3EnhancedView component
  - [ ] 6.1 Create component file
    - Create IRISVOICE/components/level-3-enhanced-view.tsx
    - Use NavigationContext for state access
    - _Requirements: 1.4_
  
  - [ ] 6.2 Implement component rendering logic
    - Get mini-nodes from miniNodeStack or getMiniNodesForSubnode
    - Render OrbitalRingWithMiniNodes when miniNodes exist
    - Render MiniNodeSidePanel when mini-node is selected
    - Use AnimatePresence for side panel transitions
    - _Requirements: 2.1, 3.1_
  
  - [ ] 6.3 Connect component to navigation context actions
    - Connect jumpToMiniNode action to orbital ring onSelect
    - Connect updateMiniNodeValue action to side panel onValueChange
    - Pass theme glow color to child components
    - _Requirements: 2.3, 3.3, 7.1_

- [ ] 7. Update page.tsx to integrate Level3EnhancedView
  - [ ] 7.1 Remove Level 4 component imports
    - Remove import for level-4-view.tsx
    - Remove import for level-4-orbital-view.tsx
    - _Requirements: 6.4_
  
  - [ ] 7.2 Add Level3EnhancedView import and rendering
    - Import Level3EnhancedView component
    - Render Level3EnhancedView when level === 3 and selectedSub is set
    - Remove Level 4 rendering logic
    - _Requirements: 1.4_
  
  - [ ] 7.3 Update navigation level display logic
    - Ensure level display shows 1, 2, or 3 (not 4)
    - _Requirements: 1.1_

- [ ] 8. Remove obsolete Level 4 components
  - [ ] 8.1 Delete level-4-view.tsx
    - Remove IRISVOICE/components/level-4-view.tsx
    - _Requirements: 6.1_
  
  - [ ] 8.2 Delete level-4-orbital-view.tsx
    - Remove IRISVOICE/components/level-4-orbital-view.tsx
    - _Requirements: 6.2_
  
  - [ ] 8.3 Delete CompactAccordion.tsx if it exists
    - Remove IRISVOICE/components/CompactAccordion.tsx
    - _Requirements: 6.3_

- [ ] 9. Implement error handling and edge cases
  - [ ] 9.1 Add error handling for missing mini-node data
    - Display fallback message when sub-node has no mini-nodes
    - _Requirements: 5.1_
  
  - [ ] 9.2 Add error handling for field value type mismatches
    - Implement getFieldValue function with type coercion
    - Handle undefined values with defaults
    - _Requirements: 5.3_
  
  - [ ] 9.3 Add error handling for async loadOptions failures
    - Implement loadDropdownOptions with timeout and fallback
    - Use static options if async load fails
    - _Requirements: 5.4_
  
  - [ ] 9.4 Add error handling for invalid theme colors
    - Implement hexToRgba with validation and fallback
    - _Requirements: 7.6_
  
  - [ ] 9.5 Add error handling for localStorage quota exceeded
    - Implement saveMiniNodeValues with quota error handling
    - Clear non-essential data and retry
    - _Requirements: 5.5_
  
  - [ ]* 9.6 Write property test for hexToRgba color conversion
    - **Property 15: HexToRgba Color Conversion**
    - **Validates: Requirements 7.6**
    - Test that for any hex color and alpha, hexToRgba produces valid rgba() string

- [ ] 10. Verify data preservation and ID consistency
  - [ ]* 10.1 Write property test for complete data preservation
    - **Property 11: Complete Data Preservation**
    - **Validates: Requirements 5.1, 5.2, 5.3, 2.6**
    - Test that all 52 mini-nodes preserve ID, label, icon, and field configurations
  
  - [ ]* 10.2 Write property test for async loadOptions support
    - **Property 12: Async LoadOptions Support**
    - **Validates: Requirements 5.4**
    - Test that dropdown fields with loadOptions return Promise resolving to options
  
  - [ ]* 10.3 Write property test for localStorage round-trip
    - **Property 13: LocalStorage Persistence Round-Trip**
    - **Validates: Requirements 5.5**
    - Test that saving and loading mini-node values produces equivalent data
  
  - [ ]* 10.4 Write property test for ID format validation
    - **Property 16: ID Format Validation**
    - **Validates: Requirements 8.1**
    - Test that all navigation IDs match lowercase-kebab-case pattern
  
  - [ ]* 10.5 Write property test for ID preservation
    - **Property 17: ID Preservation**
    - **Validates: Requirements 8.2, 8.3, 8.4**
    - Test that all 6 main category, 24 sub-node, and 52 mini-node IDs remain unchanged
  
  - [ ]* 10.6 Write property test for ID validation functions
    - **Property 18: ID Validation Functions Preserved**
    - **Validates: Requirements 8.5**
    - Test that isValidNodeId and normalizeId functions work correctly

- [ ] 11. Implement theme integration and reactivity
  - [ ]* 11.1 Write property test for theme color reactivity
    - **Property 14: Theme Color Reactivity**
    - **Validates: Requirements 7.1, 7.2, 7.5**
    - Test that theme color changes trigger re-renders with new color

- [ ] 12. Verify navigation state persistence
  - [ ]* 12.1 Write property test for mini-node values persistence across navigation
    - **Property 9: Mini-Node Values Persist Across Navigation**
    - **Validates: Requirements 4.4**
    - Test that miniNodeValues remain unchanged during navigation transitions

- [ ] 13. Final checkpoint - Integration testing and validation
  - Run all property-based tests (21 properties)
  - Run all unit tests
  - Verify all 52 mini-nodes and 61 input fields are accessible
  - Test navigation flows: Level 1 → 2 → 3, backward navigation
  - Test mini-node selection and field value updates
  - Test localStorage persistence and migration
  - Test theme color changes and visual consistency
  - Ensure all tests pass, ask the user if questions arise

## Notes

- Tasks marked with `*` are optional testing tasks and can be skipped for faster MVP
- Each task references specific requirements for traceability
- The implementation uses TypeScript with React and framer-motion
- Property tests use fast-check library with minimum 100 iterations
- All 21 correctness properties from the design document are included as test tasks
- Checkpoint at the end ensures all functionality works before completion

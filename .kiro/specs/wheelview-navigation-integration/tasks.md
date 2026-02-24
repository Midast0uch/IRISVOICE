# Implementation Plan: WheelView Navigation Integration

## Overview

This implementation consolidates the IRISVOICE navigation system from 4 levels to 3 levels by integrating the WheelView component with a working dual orbital ring mechanism. The WheelView combines Level 3 (sub-nodes) and Level 4 (mini-nodes) into a single enhanced view with outer and inner rings, fixing the broken inner ring that prevented access to all 52 mini-nodes.

The implementation follows a bottom-up approach: field components → connection line → side panel → dual ring mechanism → container → integration → testing.

## Tasks

- [x] 1. Update type system and navigation context
  - [x] 1.1 Update NavigationLevelType to 1 | 2 | 3
    - Modify `types/navigation.ts` to remove level 4 from type definition
    - Update LEVEL_NAMES constant to include only 3 entries
    - Update all type guards to validate only 1, 2, or 3
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 1.2 Update NavState interface
    - Remove `level4ViewMode` property from NavState interface
    - Ensure level property uses updated NavigationLevelType
    - Update state initialization to use 3-level system
    - _Requirements: 1.1, 4.4_

  - [x] 1.3 Update NavigationContext reducer actions
    - Modify SELECT_SUB action to set level to 3 (not 4)
    - Modify GO_BACK action to transition from level 3 to level 2
    - Remove SET_LEVEL4_VIEW_MODE action handler
    - Add state normalization function for level values
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 1.4 Add LocalStorage state migration
    - Create normalizeLevel function to convert level 4 → 3
    - Update state restoration to filter obsolete level4ViewMode property
    - Add error handling for corrupted localStorage data
    - Preserve Mini_Node_Stack and miniNodeValues during migration
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 1.5 Write property tests for navigation level invariants
    - **Property 1: Navigation Level Invariant**
    - **Property 2: Level Type Guard Validation**
    - **Property 16: LocalStorage Level Normalization**
    - **Validates: Requirements 1.5, 4.7, 10.6**

- [x] 2. Create field components with theme integration
  - [x] 2.1 Create ToggleField component
    - Implement sliding pill switch with spring animation
    - Apply glowColor for active state, white/10 for inactive
    - Add aria-pressed attribute for accessibility
    - Use React.memo for performance optimization
    - _Requirements: 5.2, 11.2, 12.1, 13.2_

  - [x] 2.2 Create SliderField component
    - Implement range input with value display
    - Support min, max, step, and unit props
    - Apply glowColor to accent color
    - Display value in monospace font
    - Use React.memo for performance optimization
    - _Requirements: 5.2, 11.2, 12.1_

  - [x] 2.3 Create DropdownField component
    - Implement select element with options rendering
    - Support static options and dynamic loadOptions
    - Add loading indicator for async loading
    - Implement options caching to prevent redundant calls
    - Add error handling with fallback to empty array
    - Apply glowColor to focus states
    - Use React.memo for performance optimization
    - _Requirements: 5.2, 11.2, 12.1, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

  - [x] 2.4 Create TextField component
    - Implement text input with placeholder support
    - Apply glowColor to caret and focus border
    - Use React.memo for performance optimization
    - _Requirements: 5.2, 11.2, 12.1_

  - [x] 2.5 Create ColorField component
    - Implement color picker with hex display
    - Display uppercase hex value in monospace font
    - Apply glowColor to focus states
    - Use React.memo for performance optimization
    - _Requirements: 5.2, 11.2, 12.1_

  - [x] 2.6 Write property tests for field components
    - **Property 17: Field Type Rendering**
    - **Property 18: Field Value Change Callback**
    - **Property 41: LoadOptions Invocation**
    - **Property 42: LoadOptions Caching**
    - **Property 43: LoadOptions Loading State**
    - **Property 44: LoadOptions Error Handling**
    - **Property 45: LoadOptions Interface Support**
    - **Property 46: Loaded Options Rendering**
    - **Validates: Requirements 5.2, 5.3, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 14.7**

  - [x] 2.7 Write unit tests for field components
    - Test each field type renders correctly
    - Test value change callbacks fire with correct parameters
    - Test theme color application
    - Test empty/invalid states
    - Test accessibility attributes (ARIA labels, focus states)
    - _Requirements: 5.2, 5.3, 11.2, 13.2_

- [x] 3. Create ConnectionLine component
  - [x] 3.1 Implement animated glowing line
    - Create SVG line with gradient (glowColor with alpha fade cc → 44)
    - Add glow layer with blur filter (alpha 44 → 11)
    - Implement shimmer effect with traveling highlight (28px width)
    - Add continuous linear motion animation (2s loop)
    - _Requirements: 5.4, 11.6_

  - [x] 3.2 Add spring-based extension/retraction
    - Implement scaleX animation (0 = retracted, 1 = extended)
    - Use spring configuration: stiffness 200, damping 25
    - Support lineRetracted prop to control state
    - _Requirements: 5.5, 6.6_

  - [x] 3.3 Write unit tests for ConnectionLine
    - Test line renders with correct gradient colors
    - Test extension/retraction animation triggers
    - Test shimmer animation plays continuously
    - Test spring configuration values
    - _Requirements: 5.4, 5.5, 6.6, 11.6_

- [x] 4. Create SidePanel component
  - [x] 4.1 Implement panel layout and styling
    - Position panel at orbSize/2 + 12px offset from orb
    - Set width to 100px, max height to 560px
    - Apply glass-morphism styling (backdrop blur, transparency)
    - Integrate ConnectionLine component
    - _Requirements: 5.1, 11.7_

  - [x] 4.2 Implement panel header and footer
    - Create header with mini-node label and indicator dot
    - Create footer with confirm button and icon
    - Apply glowColor to interactive elements
    - Add aria-label to confirm button
    - _Requirements: 5.1, 11.2, 13.3_

  - [x] 4.3 Implement field list with crossfade transitions
    - Render all fields from miniNode.fields array
    - Use AnimatePresence with mode="wait" for transitions
    - Implement exit animation: opacity 0, y -8, duration 0.2s
    - Implement enter animation: opacity 1, y 0, duration 0.2s
    - Key content by miniNode.id for proper transitions
    - _Requirements: 5.6, 12.4_

  - [x] 4.4 Add field rendering logic
    - Implement renderField function with switch statement
    - Handle all field types: text, slider, dropdown, toggle, color
    - Skip invalid field types with console warning
    - Pass glowColor and callbacks to all field components
    - _Requirements: 5.2, 15.3_

  - [x] 4.5 Implement empty state handling
    - Display "No settings available" when fields array is empty
    - Add explanatory text for empty state
    - _Requirements: 5.7, 15.2_

  - [x] 4.6 Wire up confirm button handler
    - Call onConfirm callback when button clicked
    - Trigger line retraction animation before confirm
    - _Requirements: 5.5_

  - [x] 4.7 Write property tests for SidePanel
    - **Property 5: Side Panel Field Display**
    - **Property 19: Confirm Line Retraction**
    - **Validates: Requirements 2.4, 3.3, 5.1, 5.5**

  - [x] 4.8 Write unit tests for SidePanel
    - Test panel renders with correct positioning
    - Test all field types render correctly
    - Test crossfade animation on mini-node change
    - Test empty state message displays
    - Test confirm button triggers callbacks
    - Test invalid field types are skipped
    - _Requirements: 5.1, 5.2, 5.6, 5.7, 15.2, 15.3_

- [x] 5. Create DualRingMechanism component
  - [x] 5.1 Implement ring distribution logic
    - Calculate splitPoint as Math.ceil(items.length / 2)
    - Distribute first half to outerItems array
    - Distribute second half to innerItems array
    - Use useMemo for distribution calculation
    - _Requirements: 2.5, 12.2_

  - [x] 5.2 Implement outer ring rendering
    - Create SVG circle with radius orbSize * 0.42
    - Set stroke width to 28px
    - Calculate segment angles: 360 / outerItems.length
    - Render clickable path segments for each item
    - Add diamond markers for segment separators
    - Render curved text labels along arc paths
    - _Requirements: 2.2, 3.5_

  - [x] 5.3 Implement inner ring rendering
    - Create SVG circle with radius orbSize * 0.18
    - Set stroke width to 22px
    - Calculate segment angles: 360 / innerItems.length
    - Render clickable path segments for each item
    - Add circle markers for segment separators
    - Render curved text labels along arc paths (radius + 14)
    - Apply drop shadows and glow effects
    - _Requirements: 2.3, 3.1, 3.5, 3.6_

  - [x] 5.4 Implement outer ring rotation logic
    - Calculate outerSelectedIndex from selectedIndex and splitPoint
    - Calculate rotation: -(outerSelectedIndex * outerSegmentAngle)
    - Apply rotation to center selected item at 12 o'clock
    - Use Framer Motion with spring physics (stiffness 80, damping 16)
    - _Requirements: 6.1_

  - [x] 5.5 Implement inner ring rotation logic
    - Calculate innerSelectedIndex from selectedIndex and splitPoint
    - Calculate rotation: -(innerSelectedIndex * innerSegmentAngle)
    - Apply rotation to center selected item at 12 o'clock
    - Use Framer Motion with spring physics (stiffness 80, damping 16)
    - _Requirements: 3.2, 3.4, 6.2_

  - [x] 5.6 Implement decorative rings
    - Create 3 decorative rings with dashed patterns
    - Ring 1 (innermost): radius * 0.18 - 6
    - Ring 2 (middle): radius * 0.30 + 6
    - Ring 3 (outermost): radius * 0.42 + 14 with 24 tick marks
    - Add CSS keyframe animations for continuous rotation
    - Apply glowColor with appropriate opacity
    - _Requirements: 11.5_

  - [x] 5.7 Implement groove separator
    - Position between outer and inner rings
    - Apply dark cavity styling with edge highlights
    - _Requirements: 2.2, 2.3_

  - [x] 5.8 Implement counter-spin animation
    - Add confirmSpinning prop support
    - When true, rotate outer ring +360° clockwise
    - When true, rotate inner ring -360° counter-clockwise
    - Use duration 0.8s with easeInOut easing
    - _Requirements: 6.3_

  - [x] 5.9 Add click handlers and ARIA labels
    - Attach onClick handlers to all ring segments
    - Add aria-label to each segment with item label
    - Set pointer-events to "auto" on interactive paths
    - Set pointer-events to "none" on decorative elements
    - _Requirements: 12.5, 13.1_

  - [x] 5.10 Apply theme colors throughout
    - Use glowColor for ring strokes with varying alpha
    - Use hexToRgba helper for color variations
    - Apply glowColor to text labels (60% for active, reduced for inactive)
    - Apply glowColor to glow effects and drop shadows
    - _Requirements: 11.2, 11.3, 11.4_

  - [x] 5.11 Write property tests for DualRingMechanism
    - **Property 4: Dual Ring Label Rendering**
    - **Property 6: Mini-Node Distribution**
    - **Property 8: Inner Ring Clickability**
    - **Property 9: Inner Ring Rotation Centering**
    - **Property 10: Curved Text Path Rendering**
    - **Property 11: Inner Ring Depth Styling**
    - **Property 20: Counter-Spin Animation**
    - **Property 36: HexToRgba Color Conversion**
    - **Property 37: SVG Pointer Events Optimization**
    - **Validates: Requirements 2.2, 2.3, 2.5, 3.1, 3.2, 3.5, 3.6, 3.7, 6.3, 11.3, 12.5**

  - [x] 5.12 Write unit tests for DualRingMechanism
    - Test ring distribution splits items correctly
    - Test outer and inner rings render with correct radii
    - Test rotation centers selected items at 12 o'clock
    - Test click handlers fire with correct indices
    - Test decorative rings render and animate
    - Test counter-spin animation triggers correctly
    - Test theme colors applied to all elements
    - _Requirements: 2.2, 2.3, 2.5, 3.1, 3.2, 6.1, 6.2, 6.3, 11.2_

- [x] 6. Create WheelView container component
  - [x] 6.1 Set up component structure and props
    - Define WheelViewProps interface
    - Accept categoryId, glowColor, expandedIrisSize, initialValues, onConfirm, onBackToCategories
    - Integrate with NavigationContext to fetch miniNodeStack
    - Integrate with BrandColorContext for theme colors
    - _Requirements: 2.1, 2.7, 11.1_

  - [x] 6.2 Implement internal state management
    - Add selectedSubNodeIndex state for outer ring
    - Add selectedMiniNodeIndex state for inner ring
    - Add confirmFlash state for flash animation
    - Add confirmSpinning state for counter-spin
    - Add lineRetracted state for connection line
    - Add showPanel state for panel visibility
    - _Requirements: 2.4, 5.5, 6.3, 6.4_

  - [x] 6.3 Implement mini-node selection logic
    - Calculate combined selectedIndex from outer/inner indices
    - Fetch activeMiniNode from miniNodeStack
    - Update showPanel when selection changes
    - Use useCallback for selection handlers
    - _Requirements: 2.4, 12.3_

  - [x] 6.4 Implement confirm animation sequence
    - Set lineRetracted to true
    - Set confirmSpinning to true
    - Set confirmFlash to true
    - Schedule onConfirm callback after 900ms
    - Reset animation states after completion
    - _Requirements: 6.3, 6.4, 6.5_

  - [x] 6.5 Implement animation race condition prevention
    - Add isAnimating state flag
    - Block selection input during animations
    - Clear flag after animation completes (~500ms)
    - _Requirements: 6.7, 15.6_

  - [x] 6.6 Render DualRingMechanism with props
    - Pass items (miniNodeStack)
    - Pass selectedIndex (combined index)
    - Pass onSelect handler
    - Pass glowColor and orbSize
    - Pass confirmSpinning state
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 6.7 Render SidePanel with props
    - Pass miniNode (activeMiniNode)
    - Pass glowColor
    - Pass values from miniNodeValues
    - Pass onValueChange handler
    - Pass onConfirm handler
    - Pass lineRetracted state
    - Pass orbSize
    - _Requirements: 2.4, 5.1_

  - [x] 6.8 Render center back button
    - Position at center of orb
    - Add onClick handler for onBackToCategories
    - Add aria-label for accessibility
    - Apply glowColor to hover states
    - _Requirements: 13.3_

  - [x] 6.9 Add flash overlay animation
    - Render overlay div with AnimatePresence
    - Animate scale: 0.8 → 1.4
    - Animate opacity: 0.3 → 1 → 0.3
    - Trigger on confirmFlash state
    - _Requirements: 6.4_

  - [x] 6.10 Add glow breathe animation
    - Render glow layer behind orb
    - Animate scale: 1 → 2.2 → 1
    - Intensify during confirm animation
    - Use glowColor with low opacity
    - _Requirements: 6.4, 11.6_

  - [x] 6.11 Implement empty state handling
    - Check if miniNodeStack is empty
    - Display "No settings available" message
    - Return early without rendering rings
    - _Requirements: 15.1_

  - [x] 6.12 Add error handling
    - Validate glowColor with hex pattern
    - Fallback to default color (#00D4FF) if invalid
    - Log warning for invalid colors
    - _Requirements: 15.4_

  - [x] 6.13 Write property tests for WheelView
    - **Property 3: WheelView Rendering at Level 3**
    - **Property 7: Theme Color Application**
    - **Property 21: Confirm Callback Timing**
    - **Property 22: Animation Race Condition Prevention**
    - **Property 48: Invalid Glow Color Fallback**
    - **Validates: Requirements 2.1, 2.7, 6.5, 6.7, 11.1, 11.2, 11.4, 15.4, 15.6**

  - [x] 6.14 Write unit tests for WheelView
    - Test component renders with all child components
    - Test empty state displays message
    - Test confirm animation sequence timing
    - Test invalid glow color fallback
    - Test animation race condition prevention
    - Test integration with NavigationContext
    - Test integration with BrandColorContext
    - _Requirements: 2.1, 2.7, 6.3, 6.4, 6.5, 6.7, 11.1, 15.1, 15.4, 15.6_

- [x] 7. Implement keyboard navigation
  - [x] 7.1 Add keyboard event listener
    - Attach keydown listener to window in useEffect
    - Clean up listener on unmount
    - Prevent default for navigation keys
    - _Requirements: 7.7_

  - [x] 7.2 Implement arrow key handlers
    - Arrow Right: select next outer ring item (wrap around)
    - Arrow Left: select previous outer ring item (wrap around)
    - Arrow Down: select next mini-node (wrap around)
    - Arrow Up: select previous mini-node (wrap around)
    - Use modulo arithmetic for wraparound
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

  - [x] 7.3 Implement Enter and Escape handlers
    - Enter: trigger handleConfirm
    - Escape: call onBackToCategories
    - _Requirements: 7.5, 7.6_

  - [x] 7.4 Add focus state visibility
    - Use whileFocus motion props on interactive elements
    - Add visible focus rings with glowColor
    - Ensure focus states meet WCAG AA contrast
    - _Requirements: 13.4, 13.5, 13.7_

  - [x] 7.5 Write property tests for keyboard navigation
    - **Property 23: Arrow Right Navigation**
    - **Property 24: Arrow Left Navigation**
    - **Property 25: Arrow Down Navigation**
    - **Property 26: Arrow Up Navigation**
    - **Property 27: Enter Key Confirm**
    - **Property 28: Escape Key Back**
    - **Property 29: Navigation Key preventDefault**
    - **Property 40: Focus State Visibility**
    - **Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 13.4, 13.5**

  - [x] 7.6 Write unit tests for keyboard navigation
    - Test each arrow key navigates correctly
    - Test wraparound at boundaries
    - Test Enter triggers confirm
    - Test Escape triggers back
    - Test preventDefault called for all navigation keys
    - Test focus states are visible
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 13.5_

- [x] 8. Checkpoint - Verify WheelView component works end-to-end
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Remove obsolete Level 4 components
  - [x] 9.1 Delete level-4-view.tsx file
    - Remove components/level-4-view.tsx
    - _Requirements: 9.1_

  - [x] 9.2 Delete level-4-orbital-view.tsx file
    - Remove components/level-4-orbital-view.tsx
    - _Requirements: 9.2_

  - [x] 9.3 Remove Level 4 imports from navigation router
    - Remove imports of Level4View and Level4OrbitalView
    - Remove any references to Level4ViewMode type
    - _Requirements: 9.3, 9.4_

  - [x] 9.4 Search and remove remaining Level 4 references
    - Search codebase for "Level4View", "level-4-", "level4ViewMode"
    - Remove any remaining imports or references
    - _Requirements: 9.3, 9.4, 9.5_

- [x] 10. Update main navigation router
  - [x] 10.1 Update navigation switch statement
    - Import WheelView component
    - Update case 3 to render WheelView (not Level3View)
    - Remove case 4 entirely
    - Pass required props to WheelView (categoryId, glowColor, etc.)
    - _Requirements: 2.1, 9.7_

  - [x] 10.2 Wire up WheelView callbacks
    - Connect onConfirm to save miniNodeValues to context
    - Connect onBackToCategories to dispatch GO_BACK action
    - _Requirements: 2.1, 4.3_

  - [x] 10.3 Write integration tests for navigation router
    - Test level 1 renders Level1View
    - Test level 2 renders Level2View
    - Test level 3 renders WheelView
    - Test no level 4 case exists
    - Test WheelView receives correct props
    - _Requirements: 2.1, 9.7_

- [x] 11. Add performance optimizations
  - [x] 11.1 Add React.memo to all field components
    - Wrap ToggleField, SliderField, DropdownField, TextField, ColorField
    - Verify memoization prevents unnecessary re-renders
    - _Requirements: 12.1_

  - [x] 11.2 Add useMemo for expensive calculations
    - Memoize arc path calculations in DualRingMechanism
    - Memoize segment angle calculations
    - Memoize item distribution (outerItems, innerItems)
    - _Requirements: 12.2_

  - [x] 11.3 Add useCallback for event handlers
    - Wrap all onClick handlers in useCallback
    - Wrap onValueChange handlers in useCallback
    - Include proper dependency arrays
    - _Requirements: 12.3_

  - [x] 11.4 Verify hardware-accelerated animations
    - Ensure all animations use only transform and opacity
    - Avoid animating width, height, top, left, or other layout properties
    - _Requirements: 12.6_

  - [x] 11.5 Write property tests for performance
    - **Property 38: Hardware-Accelerated Animations**
    - **Validates: Requirements 12.6**

  - [x] 11.6 Write performance tests
    - Test memoized components don't re-render unnecessarily
    - Test expensive calculations are memoized
    - Test callbacks maintain referential equality
    - Measure render time with 52 mini-nodes
    - _Requirements: 12.1, 12.2, 12.3, 12.7_

- [x] 12. Add accessibility enhancements
  - [x] 12.1 Add comprehensive ARIA labels
    - Add aria-label to all ring segments
    - Add aria-pressed to toggle buttons
    - Add aria-label to icon-only buttons
    - Add role="dialog" to SidePanel
    - _Requirements: 13.1, 13.2, 13.3, 13.6_

  - [x] 12.2 Verify color contrast ratios
    - Test text labels meet WCAG AA standards
    - Test focus states have sufficient contrast
    - Test against both light and dark backgrounds
    - _Requirements: 13.7_

  - [x] 12.3 Test screen reader compatibility
    - Verify screen reader announces selection changes
    - Verify field labels are read correctly
    - Verify button purposes are clear
    - _Requirements: 13.1, 13.2, 13.3_

  - [x] 12.4 Write property tests for accessibility
    - **Property 39: ARIA Labels for Interactive Elements**
    - **Validates: Requirements 13.1, 13.2, 13.3**

  - [x] 12.5 Write accessibility tests
    - Test all interactive elements have ARIA labels
    - Test keyboard navigation works without mouse
    - Test focus states are visible
    - Test color contrast meets WCAG AA
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.7_

- [x] 13. Add error boundary
  - [x] 13.1 Create WheelViewErrorBoundary component
    - Implement getDerivedStateFromError
    - Implement componentDidCatch with logging
    - Render fallback UI with error message
    - Add "Try again" button to reset error state
    - _Requirements: 15.7_

  - [x] 13.2 Wrap WheelView with error boundary
    - Add error boundary in navigation router
    - Ensure errors don't crash entire app
    - _Requirements: 15.7_

  - [x] 13.3 Write property tests for error handling
    - **Property 47: Invalid Field Type Handling**
    - **Property 49: Corrupted LocalStorage Handling**
    - **Property 50: Error Boundary Fallback**
    - **Validates: Requirements 15.3, 15.5, 15.7**

  - [x] 13.4 Write error handling tests
    - Test error boundary catches rendering errors
    - Test fallback UI displays
    - Test "Try again" button resets state
    - Test corrupted localStorage doesn't crash app
    - Test invalid field types are skipped
    - _Requirements: 15.3, 15.5, 15.7_

- [x] 14. Checkpoint - Verify all integration points work correctly
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Write comprehensive property-based tests
  - [x] 15.1 Write navigation state property tests
    - **Property 12: SELECT_SUB Sets Level 3**
    - **Property 13: SELECT_SUB Stores Mini-Node Stack**
    - **Property 14: GO_BACK from Level 3**
    - **Property 15: Level 3 State Preservation**
    - **Property 33: Obsolete Property Filtering**
    - **Property 34: Mini-Node Stack Restoration**
    - **Property 35: Mini-Node Values Application**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.5, 10.2, 10.3, 10.4**

  - [x] 15.2 Write data structure property tests
    - **Property 30: Field Config Property Preservation**
    - **Property 31: Mini-Node Stack Compatibility**
    - **Property 32: Mini-Node Serialization Round-Trip**
    - **Validates: Requirements 8.4, 8.5, 8.6**

- [x] 16. Write comprehensive unit tests
  - [x] 16.1 Write integration tests
    - Test NavigationContext integration
    - Test BrandColorContext integration
    - Test LocalStorage persistence
    - Test state restoration with migration
    - Test all 6 categories with their mini-nodes
    - _Requirements: 2.7, 8.1, 8.2, 8.3, 10.1, 10.3, 10.4, 11.1_

  - [x] 16.2 Write animation tests
    - Test ring rotation animations
    - Test confirm animation sequence
    - Test connection line extension/retraction
    - Test crossfade transitions
    - Test decorative ring rotations
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6_

  - [x] 16.3 Write data preservation tests
    - Test all 52 mini-nodes are accessible
    - Test all 61 fields are rendered
    - Test field values persist across selections
    - Test mini-node distribution matches spec
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [x] 16.4 Write edge case tests
    - Test empty mini-node stack
    - Test mini-node with no fields
    - Test invalid field types
    - Test invalid glow colors
    - Test corrupted localStorage
    - Test animation interruptions
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5, 15.6_

- [x] 17. Final checkpoint - Ensure all tests pass and feature is complete
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at key milestones
- Property tests validate universal correctness properties (50 properties total)
- Unit tests validate specific examples, edge cases, and integration points
- Implementation follows bottom-up approach: components → integration → testing
- All 52 mini-nodes and 61 fields must be preserved during migration
- TypeScript/React with Framer Motion for animations
- fast-check library for property-based testing (100 iterations minimum)

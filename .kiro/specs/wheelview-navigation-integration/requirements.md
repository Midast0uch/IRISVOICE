# Requirements Document

## Introduction

The IRISVOICE application currently implements a 4-level navigation hierarchy (Collapsed Orb → Main Categories → Sub-nodes → Mini-nodes). The Level 4 implementation (level-4-orbital-view.tsx) has a broken inner ring mechanism that prevents users from accessing all 52 mini-nodes properly. This feature consolidates the navigation system from 4 levels to 3 levels by integrating the WheelView component, which combines Level 3 and Level 4 into a single enhanced view with working dual orbital rings.

The WheelView component displays both sub-nodes (outer ring) and mini-nodes (inner ring) simultaneously, with a side panel for input fields. This eliminates the need for a separate Level 4 and fixes the broken inner ring functionality while preserving all 52 mini-nodes and their 61 input fields across 6 main categories.

## Glossary

- **Navigation_System**: The hierarchical navigation structure that allows users to access different settings and features
- **Level**: A depth in the navigation hierarchy (1=Collapsed, 2=Main Categories, 3=Sub-nodes, 4=Mini-nodes)
- **Main_Category**: One of 6 primary categories (Voice, Agent, Automate, System, Customize, Monitor) displayed as hexagonal nodes at Level 2
- **Sub_Node**: A secondary category within a Main_Category, displayed in an orbital ring at Level 3
- **Mini_Node**: A settings node containing input fields, currently displayed at Level 4
- **WheelView**: The new component that displays both Sub_Nodes and Mini_Nodes in dual orbital rings
- **Dual_Ring_Mechanism**: The SVG-based visualization showing outer ring (Sub_Nodes) and inner ring (Mini_Nodes)
- **Side_Panel**: The detail panel that displays input fields for the selected Mini_Node
- **Inner_Ring**: The inner orbital ring in the dual-ring mechanism that displays Mini_Node labels
- **Outer_Ring**: The outer orbital ring in the dual-ring mechanism that displays Sub_Node labels
- **Navigation_Context**: The React context managing navigation state and transitions
- **Navigation_Level_Type**: TypeScript type defining valid navigation levels
- **Field_Config**: Configuration object defining input field properties (type, label, options, etc.)
- **Mini_Node_Stack**: Array of Mini_Nodes associated with a selected Sub_Node
- **Orbital_View**: The circular visualization pattern used for displaying navigation nodes
- **Brand_Color_Context**: React context providing theme colors and glow effects
- **Local_Storage**: Browser storage used to persist navigation state and user settings

## Requirements

### Requirement 1: Navigation Level Type Consolidation

**User Story:** As a developer, I want the navigation system to support only 3 levels instead of 4, so that the codebase is simpler and matches the new WheelView architecture.

#### Acceptance Criteria

1. THE Navigation_System SHALL define Navigation_Level_Type as 1 | 2 | 3 (removing level 4)
2. WHEN Navigation_Level_Type is referenced in type definitions, THE Navigation_System SHALL use only values 1, 2, or 3
3. THE Navigation_System SHALL update all type guards and validation functions to accept only levels 1, 2, or 3
4. THE Navigation_System SHALL update LEVEL_NAMES constant to include only 3 levels
5. FOR ALL Navigation_Level_Type values, the type SHALL be one of {1, 2, 3} (invariant property)

### Requirement 2: WheelView Component Integration

**User Story:** As a user, I want to see both sub-nodes and mini-nodes in a single view, so that I can access settings without navigating to a separate level.

#### Acceptance Criteria

1. WHEN a Sub_Node is selected at Level 3, THE Navigation_System SHALL display the WheelView component
2. THE WheelView SHALL render Dual_Ring_Mechanism with Outer_Ring showing Sub_Node labels
3. THE WheelView SHALL render Dual_Ring_Mechanism with Inner_Ring showing Mini_Node labels
4. WHEN a Mini_Node is selected, THE WheelView SHALL display the Side_Panel with input fields
5. THE WheelView SHALL distribute Mini_Nodes across outer and inner rings based on count (split at midpoint)
6. THE WheelView SHALL preserve all 52 Mini_Nodes and their Field_Config definitions
7. THE WheelView SHALL integrate with Brand_Color_Context for theme colors and glow effects

### Requirement 3: Inner Ring Functionality

**User Story:** As a user, I want the inner ring to work properly, so that I can access all mini-nodes that were previously inaccessible.

#### Acceptance Criteria

1. WHEN Mini_Nodes are distributed to Inner_Ring, THE Dual_Ring_Mechanism SHALL render all Inner_Ring Mini_Nodes as clickable segments
2. WHEN a user clicks an Inner_Ring segment, THE WheelView SHALL rotate the Inner_Ring to center the selected Mini_Node at 12 o'clock position
3. WHEN an Inner_Ring Mini_Node is selected, THE Side_Panel SHALL display the corresponding Field_Config inputs
4. THE Inner_Ring SHALL use spring physics animation with stiffness 80 and damping 16 for rotation
5. THE Inner_Ring SHALL render curved text labels along the arc path for each Mini_Node
6. THE Inner_Ring SHALL apply proper depth styling with drop shadows and glow effects
7. FOR ALL Mini_Nodes in Inner_Ring, clicking SHALL trigger selection (no broken interactions)

### Requirement 4: Navigation Context Reducer Updates

**User Story:** As a developer, I want the navigation reducer to handle the 3-level system correctly, so that state transitions work without Level 4.

#### Acceptance Criteria

1. WHEN SELECT_SUB action is dispatched, THE Navigation_Context SHALL set level to 3 (not 4)
2. WHEN SELECT_SUB action is dispatched, THE Navigation_Context SHALL store Mini_Node_Stack in state
3. WHEN GO_BACK action is dispatched from Level 3, THE Navigation_Context SHALL transition to Level 2
4. THE Navigation_Context SHALL remove all Level 4 specific action handlers
5. THE Navigation_Context SHALL preserve Mini_Node_Stack and activeMiniNodeIndex in Level 3 state
6. WHEN state is restored from Local_Storage, THE Navigation_Context SHALL normalize any level 4 values to level 3
7. FOR ALL state transitions, level SHALL remain in range [1, 3] (invariant property)

### Requirement 5: Side Panel Input Field Display

**User Story:** As a user, I want to see input fields in a side panel when I select a mini-node, so that I can configure settings without leaving the orbital view.

#### Acceptance Criteria

1. WHEN a Mini_Node is selected, THE Side_Panel SHALL display all Field_Config inputs for that Mini_Node
2. THE Side_Panel SHALL render field types: text, slider, dropdown, toggle, color
3. WHEN a field value changes, THE Side_Panel SHALL call onValueChange callback with nodeId, fieldId, and value
4. THE Side_Panel SHALL display a glowing connection line from the orb to the panel
5. WHEN confirm button is clicked, THE Side_Panel SHALL trigger line retraction animation
6. THE Side_Panel SHALL use crossfade animation (opacity + y translation) when switching between Mini_Nodes
7. THE Side_Panel SHALL display empty state message when Mini_Node has no fields

### Requirement 6: Dual Ring Animation Coordination

**User Story:** As a user, I want smooth animations when navigating between nodes, so that the interface feels polished and responsive.

#### Acceptance Criteria

1. WHEN Outer_Ring selection changes, THE Dual_Ring_Mechanism SHALL rotate Outer_Ring using spring physics (stiffness 80, damping 16)
2. WHEN Inner_Ring selection changes, THE Dual_Ring_Mechanism SHALL rotate Inner_Ring using spring physics (stiffness 80, damping 16)
3. WHEN confirm button is clicked, THE Dual_Ring_Mechanism SHALL counter-spin Outer_Ring (+360°) and Inner_Ring (-360°)
4. WHEN confirm animation plays, THE WheelView SHALL display flash overlay with scale pulse (0.8 → 1.4)
5. WHEN confirm animation completes, THE WheelView SHALL call onConfirm callback after 900ms
6. THE Dual_Ring_Mechanism SHALL animate connection line extension using spring physics
7. FOR ALL ring rotations, the animation SHALL complete before accepting new selection input (no race conditions)

### Requirement 7: Keyboard Navigation Support

**User Story:** As a user, I want to navigate the wheel view using keyboard shortcuts, so that I can access settings efficiently without a mouse.

#### Acceptance Criteria

1. WHEN Arrow Right key is pressed, THE WheelView SHALL select next Sub_Node in Outer_Ring
2. WHEN Arrow Left key is pressed, THE WheelView SHALL select previous Sub_Node in Outer_Ring
3. WHEN Arrow Down key is pressed, THE WheelView SHALL select next Mini_Node in Inner_Ring
4. WHEN Arrow Up key is pressed, THE WheelView SHALL select previous Mini_Node in Inner_Ring
5. WHEN Enter key is pressed, THE WheelView SHALL trigger confirm action for current selection
6. WHEN Escape key is pressed, THE WheelView SHALL call onBackToCategories callback
7. THE WheelView SHALL prevent default browser behavior for all navigation keys

### Requirement 8: Data Structure Preservation

**User Story:** As a developer, I want all existing mini-node data to be preserved, so that no settings or configurations are lost during the migration.

#### Acceptance Criteria

1. THE Navigation_System SHALL preserve all 52 Mini_Node definitions across 6 Main_Categories
2. THE Navigation_System SHALL preserve all 61 Field_Config definitions across all Mini_Nodes
3. THE Navigation_System SHALL maintain Mini_Node distribution: Voice (7), Agent (9), Automate (11), System (4), Customize (4), Monitor (5)
4. THE Navigation_System SHALL preserve Field_Config properties: id, type, label, defaultValue, options, min, max, step, unit
5. THE Navigation_System SHALL maintain backward compatibility with existing Mini_Node_Stack data structure
6. FOR ALL Mini_Nodes, parsing then serializing SHALL produce equivalent data (round-trip property)

### Requirement 9: Component Removal and Cleanup

**User Story:** As a developer, I want obsolete Level 4 components removed, so that the codebase doesn't contain unused code.

#### Acceptance Criteria

1. THE Navigation_System SHALL remove level-4-view.tsx component file
2. THE Navigation_System SHALL remove level-4-orbital-view.tsx component file
3. THE Navigation_System SHALL remove all imports referencing Level4View or Level4OrbitalView
4. THE Navigation_System SHALL remove Level4ViewMode type and related state management
5. THE Navigation_System SHALL remove SET_LEVEL4_VIEW_MODE action from Navigation_Context reducer
6. THE Navigation_System SHALL remove level4ViewMode property from NavState interface
7. THE Navigation_System SHALL update main navigation component to use WheelView at Level 3

### Requirement 10: Local Storage State Migration

**User Story:** As a user, I want my navigation state to be preserved when upgrading, so that I don't lose my current position or settings.

#### Acceptance Criteria

1. WHEN Navigation_Context restores state from Local_Storage, THE Navigation_System SHALL normalize level 4 to level 3
2. WHEN level4ViewMode is found in Local_Storage, THE Navigation_System SHALL ignore the obsolete property
3. WHEN Mini_Node_Stack is restored, THE Navigation_System SHALL preserve all Mini_Node and Field_Config data
4. WHEN miniNodeValues are restored, THE Navigation_System SHALL apply values to corresponding Field_Config inputs
5. THE Navigation_System SHALL maintain STORAGE_KEY, CONFIG_STORAGE_KEY, and MINI_NODE_VALUES_KEY constants
6. FOR ALL restored states with level > 3, normalization SHALL set level to 3 (error correction property)

### Requirement 11: Theme Integration and Visual Consistency

**User Story:** As a user, I want the wheel view to match the application's theme, so that the interface looks cohesive.

#### Acceptance Criteria

1. THE WheelView SHALL retrieve theme colors from Brand_Color_Context using getThemeConfig
2. THE WheelView SHALL apply glowColor to all ring segments, text labels, and glow effects
3. THE WheelView SHALL use hexToRgba helper to create color variations with different alpha values
4. THE WheelView SHALL apply drop shadows using glowColor with appropriate opacity
5. THE WheelView SHALL render decorative rings with dashed patterns using glowColor
6. THE WheelView SHALL apply glow effects to connection line, panel edges, and selection indicators
7. THE WheelView SHALL use backdrop blur and transparency for glass-morphism effect on Side_Panel

### Requirement 12: Performance Optimization

**User Story:** As a developer, I want the wheel view to render efficiently, so that the interface remains responsive with 52 mini-nodes.

#### Acceptance Criteria

1. THE WheelView SHALL use React.memo for all field components (ToggleField, SliderField, DropdownField, TextField, ColorField)
2. THE WheelView SHALL use useMemo for expensive calculations (arc paths, segment angles, item distribution)
3. THE WheelView SHALL use useCallback for event handlers to prevent unnecessary re-renders
4. THE WheelView SHALL use AnimatePresence with mode="wait" for crossfade transitions
5. THE WheelView SHALL render SVG paths with pointer-events optimization (auto on interactive elements, none on decorative)
6. THE WheelView SHALL use hardware-accelerated CSS properties (transform, opacity) for animations
7. FOR ALL component re-renders, only changed props SHALL trigger updates (memoization property)

### Requirement 13: Accessibility Compliance

**User Story:** As a user with accessibility needs, I want the wheel view to be keyboard navigable and screen-reader friendly, so that I can use the application effectively.

#### Acceptance Criteria

1. THE WheelView SHALL provide ARIA labels for all interactive ring segments
2. THE WheelView SHALL use aria-pressed attribute for toggle field buttons
3. THE WheelView SHALL use aria-label for icon-only buttons (confirm, back)
4. THE WheelView SHALL support full keyboard navigation without mouse
5. THE WheelView SHALL provide visible focus states using whileFocus motion props
6. THE WheelView SHALL use role="dialog" for modal-like Side_Panel behavior
7. THE WheelView SHALL ensure color contrast ratios meet WCAG AA standards for text labels

### Requirement 14: Dynamic Dropdown Loading

**User Story:** As a user, I want dropdown options to load from the backend when needed, so that I see current device lists and dynamic options.

#### Acceptance Criteria

1. WHEN Field_Config includes loadOptions function, THE Side_Panel SHALL call loadOptions when Mini_Node mounts
2. THE Side_Panel SHALL cache loaded options to prevent redundant backend calls
3. WHEN loadOptions is pending, THE Side_Panel SHALL display loading indicator in dropdown
4. WHEN loadOptions fails, THE Side_Panel SHALL display error message and fallback to empty options array
5. THE Side_Panel SHALL support async loadOptions returning Promise<{label: string, value: string}[]>
6. THE Side_Panel SHALL render loaded options in dropdown select element
7. FOR ALL loadOptions calls, caching SHALL prevent duplicate requests for same Mini_Node (idempotence property)

### Requirement 15: Error Handling and Edge Cases

**User Story:** As a user, I want the application to handle errors gracefully, so that I don't experience crashes or broken states.

#### Acceptance Criteria

1. WHEN Mini_Node_Stack is empty, THE WheelView SHALL display "No settings available" message
2. WHEN Mini_Node has no fields, THE Side_Panel SHALL display "No settings available" with explanation
3. WHEN Field_Config has invalid type, THE Side_Panel SHALL skip rendering that field and log warning
4. WHEN glowColor is invalid hex, THE WheelView SHALL fallback to default theme color
5. WHEN Local_Storage is corrupted, THE Navigation_Context SHALL initialize with default state
6. WHEN ring rotation animation is interrupted, THE WheelView SHALL complete current animation before starting new one
7. IF any rendering error occurs, THEN THE WheelView SHALL catch error boundary and display fallback UI

# Requirements Document

## Introduction

This document specifies the requirements for refactoring the IRISVOICE navigation system from a 4-level hierarchy to a 3-level hierarchy. The current system uses Level 4 to display mini-node input fields in a separate orbital view. The new system will integrate mini-node labels into the Level 3 orbital ring and display input fields in a side panel, eliminating the need for Level 4 entirely.

## Glossary

- **Navigation_System**: The hierarchical navigation interface that allows users to browse and configure IRISVOICE settings
- **Level_1**: The collapsed IRIS orb state (idle state)
- **Level_2**: The expanded state showing 6 main category hexagonal nodes (Voice, Agent, Automate, System, Customize, Monitor)
- **Level_3**: The expanded state showing sub-nodes for a selected category in an orbital ring layout
- **Level_4**: The current deepest level showing mini-node input fields in an orbital view (to be removed)
- **Mini_Node**: A configuration item with an ID, label, icon, and associated input fields
- **Orbital_Ring**: A circular UI component displaying items arranged in a ring pattern with curved text labels
- **Side_Panel**: A panel displayed adjacent to the orbital ring showing input fields for the selected mini-node
- **Navigation_State**: The application state tracking current level, selected nodes, and navigation history
- **Theme_Config**: Configuration object containing brand colors and visual styling properties
- **Field_Value**: A configuration value that can be string, number, boolean, or object type

## Requirements

### Requirement 1: Remove Level 4 Navigation

**User Story:** As a developer, I want Level 4 removed from the navigation system, so that the architecture is simplified to 3 levels.

#### Acceptance Criteria

1. THE Navigation_System SHALL support exactly 3 navigation levels (Level 1, Level 2, Level 3)
2. THE Navigation_State SHALL NOT contain any Level 4 state properties
3. THE Navigation_System SHALL NOT transition to Level 4 when a sub-node is selected
4. WHEN a user selects a sub-node at Level 3, THE Navigation_System SHALL remain at Level 3 and display the mini-node interface
5. THE Navigation_System SHALL remove all Level 4 view components from the codebase

### Requirement 2: Integrate Mini-Node Labels into Level 3 Orbital Ring

**User Story:** As a user, I want to see mini-node labels integrated into the Level 3 orbital ring, so that I can select configuration items directly from the ring.

#### Acceptance Criteria

1. WHEN Level 3 is displayed, THE Orbital_Ring SHALL render mini-node labels as curved text segments on the ring
2. THE Orbital_Ring SHALL distribute mini-nodes across inner and outer ring segments based on the total count
3. WHEN a mini-node segment is clicked, THE Navigation_System SHALL select that mini-node and display its fields in the Side_Panel
4. THE Orbital_Ring SHALL highlight the selected mini-node segment using the Theme_Config glow color
5. THE Orbital_Ring SHALL rotate to position the selected mini-node at the top (12 o'clock position)
6. FOR ALL mini-nodes in a sub-node, THE Orbital_Ring SHALL preserve the mini-node ID, label, and icon from the mini-nodes data file

### Requirement 3: Display Mini-Node Fields in Side Panel

**User Story:** As a user, I want to see input fields for the selected mini-node in a side panel, so that I can configure settings without navigating to a separate level.

#### Acceptance Criteria

1. WHEN a mini-node is selected at Level 3, THE Side_Panel SHALL display all input fields for that mini-node
2. THE Side_Panel SHALL support all field types: text, slider, dropdown, toggle, and color
3. WHEN a user modifies a field value, THE Navigation_System SHALL update the Field_Value in the navigation state
4. THE Side_Panel SHALL display a confirm button that saves the current field values
5. WHEN the confirm button is clicked, THE Side_Panel SHALL animate a confirmation effect using the Theme_Config glow color
6. THE Side_Panel SHALL use transparent backgrounds and Theme_Config colors for visual consistency
7. WHEN a different mini-node is selected, THE Side_Panel SHALL crossfade to display the new mini-node's fields

### Requirement 4: Update Navigation State Management

**User Story:** As a developer, I want the navigation state to handle 3 levels instead of 4, so that state management is consistent with the new architecture.

#### Acceptance Criteria

1. THE Navigation_State type SHALL define NavigationLevel as 1, 2, or 3 (not 4)
2. THE Navigation_State SHALL track selectedMiniNode at Level 3 instead of using Level 4 state
3. WHEN GO_BACK action is dispatched at Level 3, THE Navigation_System SHALL transition to Level 2
4. THE Navigation_State SHALL preserve miniNodeValues across navigation transitions
5. THE Navigation_State validation function SHALL enforce that Level 3 requires selectedMain to be set
6. THE Navigation_State validation function SHALL NOT validate Level 4 constraints

### Requirement 5: Preserve Mini-Node Data and Configuration

**User Story:** As a developer, I want all existing mini-node data preserved, so that no configuration options are lost during the refactoring.

#### Acceptance Criteria

1. FOR ALL mini-nodes defined in the mini-nodes data file, THE Navigation_System SHALL preserve the mini-node ID, label, icon, and field configurations
2. THE Navigation_System SHALL maintain the mapping between sub-node IDs and their associated mini-nodes
3. THE Navigation_System SHALL preserve all field properties including type, label, min, max, options, and defaultValue
4. THE Navigation_System SHALL continue to support async loadOptions functions for dropdown fields
5. THE Navigation_System SHALL persist Field_Value data to localStorage using the existing storage key

### Requirement 6: Remove Obsolete Components

**User Story:** As a developer, I want obsolete Level 4 components removed, so that the codebase is clean and maintainable.

#### Acceptance Criteria

1. THE Navigation_System SHALL remove the level-4-view.tsx component file
2. THE Navigation_System SHALL remove the level-4-orbital-view.tsx component file
3. THE Navigation_System SHALL remove the CompactAccordion.tsx component file
4. THE Navigation_System SHALL remove all imports and references to removed components
5. THE Navigation_System SHALL remove Level 4 view mode configuration options

### Requirement 7: Theme Integration

**User Story:** As a user, I want the new Level 3 interface to use theme colors and transparent backgrounds, so that the visual design is consistent with the rest of the application.

#### Acceptance Criteria

1. THE Orbital_Ring SHALL use Theme_Config glow color for ring segments, highlights, and decorative elements
2. THE Side_Panel SHALL use Theme_Config glow color for borders, accents, and interactive elements
3. THE Orbital_Ring SHALL use transparent or semi-transparent backgrounds with backdrop blur effects
4. THE Side_Panel SHALL use transparent or semi-transparent backgrounds with backdrop blur effects
5. WHEN the theme color changes, THE Orbital_Ring and Side_Panel SHALL update their colors reactively
6. THE Orbital_Ring SHALL apply hexToRgba conversion for alpha-blended colors using the Theme_Config glow color

### Requirement 8: Navigation ID Consistency

**User Story:** As a developer, I want navigation IDs to remain consistent, so that existing data mappings and WebSocket communication continue to work.

#### Acceptance Criteria

1. THE Navigation_System SHALL use lowercase-kebab-case format for all navigation IDs
2. THE Navigation_System SHALL preserve all main category IDs from navigation-ids.ts
3. THE Navigation_System SHALL preserve all sub-node IDs from navigation-ids.ts
4. THE Navigation_System SHALL preserve all mini-node IDs from mini-nodes.ts
5. THE Navigation_System SHALL maintain the existing ID validation and normalization functions

### Requirement 9: Animation and Transitions

**User Story:** As a user, I want smooth animations when interacting with the Level 3 interface, so that the experience feels polished and responsive.

#### Acceptance Criteria

1. WHEN a mini-node is selected, THE Orbital_Ring SHALL animate rotation with spring physics (stiffness: 80, damping: 16)
2. WHEN the Side_Panel appears, THE Side_Panel SHALL fade in with a scale animation over 300ms
3. WHEN the Side_Panel content changes, THE Side_Panel SHALL crossfade between mini-nodes over 200ms
4. WHEN the confirm button is clicked, THE Orbital_Ring SHALL spin 360 degrees over 800ms with easeInOut easing
5. WHEN the confirm button is clicked, THE Side_Panel connection line SHALL retract with spring animation
6. THE Orbital_Ring decorative rings SHALL rotate continuously at different speeds for ambient animation

### Requirement 10: Backward Compatibility

**User Story:** As a user, I want my existing configuration values preserved, so that I don't lose my settings after the update.

#### Acceptance Criteria

1. WHEN the application loads with old Level 4 state in localStorage, THE Navigation_System SHALL normalize the state to Level 3
2. THE Navigation_System SHALL preserve all miniNodeValues from localStorage regardless of the stored level
3. WHEN level4ViewMode is set to 'accordion' in localStorage, THE Navigation_System SHALL change it to 'orbital'
4. THE Navigation_System SHALL validate and correct invalid navigation levels (0 or 4) to Level 1
5. THE Navigation_System SHALL maintain the MINI_NODE_VALUES_KEY for localStorage persistence

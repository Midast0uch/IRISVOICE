# Requirements Document

## Introduction

This feature addresses a critical ID mismatch issue between frontend and backend navigation systems that has caused recurring bugs. The system currently uses inconsistent ID formats (uppercase like "INPUT" in frontend vs lowercase like "input" in backend), leading to navigation failures when components interact with backend services. A single source of truth has been established at `data/navigation-ids.ts` using lowercase-kebab-case format.

Additionally, this feature integrates the existing DarkGlassDashboard component as a third Level 4 view option, providing users with an alternative simplified interface for accessing settings alongside the existing 'wheel' and 'accordion' modes.

## Glossary

- **Navigation_System**: The hierarchical navigation structure with 4 levels (collapsed, main categories, sub-categories, mini-nodes)
- **Navigation_ID**: A unique identifier for navigation nodes using lowercase-kebab-case format (e.g., 'voice', 'input', 'voice-processing')
- **Main_Category**: Level 2 navigation nodes representing primary feature areas (voice, agent, automate, system, customize, monitor)
- **Sub_Node**: Level 3 navigation nodes representing specific settings within a main category
- **Mini_Node**: Level 4 navigation nodes representing individual configuration items
- **Level4View**: The component that displays mini-nodes in different view modes
- **View_Mode**: The display format for Level 4 navigation ('accordion', 'wheel', or 'dashboard')
- **HexagonalControlCenter**: The component that renders main categories and sub-nodes in hexagonal layout
- **NavigationContext**: The React context that manages navigation state and validation
- **Single_Source_Of_Truth**: The canonical definition file (`navigation-ids.ts`) that all components must reference for IDs
- **ID_Mismatch**: When frontend uses different ID format than backend, causing navigation failures
- **DarkGlassDashboard**: An existing component providing a simplified tabbed interface for settings

## Requirements

### Requirement 1: Establish Single Source of Truth for Navigation IDs

**User Story:** As a developer, I want all navigation IDs defined in one canonical location, so that frontend and backend always use consistent identifiers.

#### Acceptance Criteria

1. THE Navigation_System SHALL use IDs exclusively from `data/navigation-ids.ts`
2. THE Navigation_System SHALL enforce lowercase-kebab-case format for all Navigation_IDs
3. WHEN a component needs a Navigation_ID, THE component SHALL import it from `navigation-ids.ts`
4. THE Navigation_System SHALL NOT allow hardcoded ID strings outside of `navigation-ids.ts`

### Requirement 2: Migrate HexagonalControlCenter to Standardized IDs

**User Story:** As a developer, I want the hexagonal control center to use standardized IDs, so that main category and sub-node selections work correctly with backend services.

#### Acceptance Criteria

1. WHEN HexagonalControlCenter renders Main_Categories, THE component SHALL use IDs from MAIN_CATEGORY_IDS constant
2. WHEN HexagonalControlCenter renders Sub_Nodes, THE component SHALL use IDs from SUB_NODE_IDS constant
3. THE HexagonalControlCenter SHALL NOT use uppercase ID strings (e.g., "VOICE", "INPUT")
4. WHEN a user selects a node, THE HexagonalControlCenter SHALL pass lowercase-kebab-case IDs to NavigationContext

### Requirement 3: Validate Navigation IDs at Runtime

**User Story:** As a developer, I want the navigation system to validate IDs at runtime, so that ID mismatches are caught early during development.

#### Acceptance Criteria

1. WHEN NavigationContext receives a Main_Category selection, THE NavigationContext SHALL validate the ID against MAIN_CATEGORY_IDS
2. WHEN NavigationContext receives a Sub_Node selection, THE NavigationContext SHALL validate the ID against SUB_NODE_IDS
3. IF an invalid Navigation_ID is provided, THEN THE NavigationContext SHALL log a warning with the invalid ID and expected format
4. IF an invalid Navigation_ID is provided, THEN THE NavigationContext SHALL normalize the ID using the normalizeId function
5. THE NavigationContext SHALL use isValidNodeId function to verify ID format compliance

### Requirement 4: Integrate DarkGlassDashboard as Third View Mode

**User Story:** As a user, I want to access settings through a dashboard view, so that I have a simpler alternative to the wheel and accordion interfaces.

#### Acceptance Criteria

1. THE Level4View SHALL support 'dashboard' as a valid View_Mode option
2. WHEN View_Mode is 'dashboard', THE Level4View SHALL render DarkGlassDashboard component
3. WHEN View_Mode is 'dashboard', THE Level4View SHALL pass miniNodeValues to DarkGlassDashboard
4. WHEN View_Mode is 'dashboard', THE Level4View SHALL pass updateMiniNodeValue callback to DarkGlassDashboard
5. THE Level4View SHALL allow users to toggle between 'accordion', 'wheel', and 'dashboard' modes

### Requirement 5: Update Type Definitions for Dashboard Mode

**User Story:** As a developer, I want TypeScript to recognize 'dashboard' as a valid view mode, so that I get proper type checking and autocomplete.

#### Acceptance Criteria

1. THE Level4ViewMode type SHALL include 'dashboard' as a valid option
2. THE Level4ViewMode type SHALL be defined as 'accordion' | 'wheel' | 'dashboard'
3. WHEN a component uses Level4ViewMode type, THE TypeScript compiler SHALL accept 'dashboard' value
4. THE NavAction type SHALL support SET_LEVEL4_VIEW_MODE action with 'dashboard' mode

### Requirement 6: Verify Mini-Nodes Data Consistency

**User Story:** As a developer, I want mini-nodes data to use standardized IDs, so that Level 4 navigation works correctly with backend services.

#### Acceptance Criteria

1. WHEN mini-nodes.ts defines Sub_Node mappings, THE file SHALL use IDs from SUB_NODE_IDS constant
2. THE mini-nodes.ts file SHALL use lowercase-kebab-case keys for all Sub_Node references
3. WHEN getMiniNodesForSubnode is called, THE function SHALL accept lowercase-kebab-case Sub_Node IDs
4. THE mini-nodes.ts file SHALL NOT use uppercase or mixed-case ID strings

### Requirement 7: Maintain Backward Compatibility During Migration

**User Story:** As a developer, I want the system to handle legacy uppercase IDs gracefully, so that the migration doesn't break existing functionality.

#### Acceptance Criteria

1. WHEN NavigationContext receives an uppercase ID, THE NavigationContext SHALL normalize it using migrateId function
2. WHEN NavigationContext normalizes an ID, THE NavigationContext SHALL log a deprecation warning
3. THE Navigation_System SHALL continue to function with legacy IDs during the migration period
4. WHERE legacy ID support is enabled, THE Navigation_System SHALL map old IDs to new IDs using ID_MIGRATION_MAP

### Requirement 8: Ensure Offline Fallback Data Uses Standardized IDs

**User Story:** As a user, I want the navigation to work correctly when backend is offline, so that I can still access settings using fallback data.

#### Acceptance Criteria

1. WHEN backend is offline, THE Navigation_System SHALL use fallback data with lowercase-kebab-case IDs
2. THE fallback Sub_Node definitions SHALL use IDs from SUB_NODE_IDS constant
3. WHEN HexagonalControlCenter uses fallback data, THE component SHALL match IDs with NavigationContext state
4. THE Navigation_System SHALL NOT experience ID mismatches between fallback data and navigation state

### Requirement 9: Update View Mode Toggle UI for Three Options

**User Story:** As a user, I want to cycle through all three view modes, so that I can choose my preferred interface for accessing settings.

#### Acceptance Criteria

1. WHEN user clicks the view mode toggle button, THE Level4View SHALL cycle through 'accordion' → 'wheel' → 'dashboard' → 'accordion'
2. THE view mode toggle button SHALL display an appropriate icon for the current View_Mode
3. THE view mode toggle button SHALL show a tooltip indicating the next View_Mode
4. WHEN View_Mode changes, THE Level4View SHALL animate the transition between views

### Requirement 10: Preserve Mini-Node Values Across View Mode Changes

**User Story:** As a user, I want my settings changes to persist when switching view modes, so that I don't lose my work.

#### Acceptance Criteria

1. WHEN user changes a setting in DarkGlassDashboard, THE NavigationContext SHALL update miniNodeValues
2. WHEN user switches from 'dashboard' to 'wheel' mode, THE WheelSpinMenu SHALL display the updated values
3. WHEN user switches from 'wheel' to 'accordion' mode, THE MiniNodeStack SHALL display the updated values
4. THE Navigation_System SHALL maintain a single source of truth for miniNodeValues across all View_Modes

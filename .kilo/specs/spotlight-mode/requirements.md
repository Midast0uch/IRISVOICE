# Requirements: Spotlight Mode

## Introduction

Spotlight Mode extends the existing `useUILayoutState` hook to add a sub-state system that works in two contexts:

1. **Chat-Only Mode** (`UI_STATE_CHAT_OPEN`): When only ChatWing is visible, spotlight expands the chat for maximum space
2. **Both-Open Mode** (`UI_STATE_BOTH_OPEN`): When both wings are visible, spotlight emphasizes one wing while dimming the other

Users can toggle between three spotlight configurations: **balanced** (default positioning), **chatSpotlight** (ChatWing expanded), and **dashboardSpotlight** (DashboardWing expanded). The implementation preserves the existing balanced state behavior while adding smooth spring-animated transitions between all spotlight states. The Iris Aperture button is always visible in the ChatWing header whenever the chat is open, allowing users to toggle spotlight mode regardless of dashboard visibility.

## Requirements

### Requirement 1: Spotlight State Enum Integration

**User Story:** As a developer, I want spotlight states integrated into the existing UI layout state system so that spotlight mode works seamlessly with the current state machine.

#### Acceptance Criteria

1. THE SYSTEM SHALL extend `useUILayoutState.ts` to include a `SpotlightState` enum with values: `balanced`, `chatSpotlight`, `dashboardSpotlight`
2. THE SYSTEM SHALL add `spotlightState` property to the hook's return interface
3. THE SYSTEM SHALL default `spotlightState` to `balanced` when entering `UI_STATE_BOTH_OPEN`
4. THE SYSTEM SHALL reset `spotlightState` to `balanced` when transitioning away from `UI_STATE_BOTH_OPEN`
5. THE SYSTEM SHALL allow spotlight transitions when `uiState === UI_STATE_BOTH_OPEN`
6. THE SYSTEM SHALL allow `chatSpotlight` and `balanced` states when `uiState === UI_STATE_CHAT_OPEN`
7. WHEN in `UI_STATE_CHAT_OPEN` THE SYSTEM SHALL display the Iris Aperture button in ChatWing header
8. WHEN in `UI_STATE_CHAT_OPEN` with `chatSpotlight` THE SYSTEM SHALL expand ChatWing to 340px width
9. THE SYSTEM SHALL pass `isDashboardOpen` prop to ChatWing to distinguish between single-wing and both-wing spotlight contexts

### Requirement 2: Spotlight Transition Methods

**User Story:** As a user, I want clear methods to transition between spotlight states so I can focus on either wing or return to balanced view.

#### Acceptance Criteria

1. THE SYSTEM SHALL provide `setSpotlightState(state: SpotlightState)` method for direct state setting
2. THE SYSTEM SHALL provide `toggleChatSpotlight()` method that toggles between `chatSpotlight` and `balanced`
3. THE SYSTEM SHALL provide `toggleDashboardSpotlight()` method that toggles between `dashboardSpotlight` and `balanced`
4. THE SYSTEM SHALL provide `restoreBalanced()` method that returns to `balanced` state from any spotlight state
5. WHEN calling `toggleChatSpotlight()` from `dashboardSpotlight` THE SYSTEM SHALL transition directly to `chatSpotlight`
6. WHEN calling `toggleDashboardSpotlight()` from `chatSpotlight` THE SYSTEM SHALL transition directly to `dashboardSpotlight`
7. THE SYSTEM SHALL include boolean helpers: `isBalanced`, `isChatSpotlight`, `isDashboardSpotlight`

### Requirement 3: Balanced State Specifications (Default)

**User Story:** As a user, I want the current balanced behavior preserved exactly as it functions today when I open both wings.

#### Acceptance Criteria

1. WHEN `spotlightState === balanced` THE SYSTEM SHALL render ChatWing at 255px width with 15deg rotateY tilt
2. WHEN `spotlightState === balanced` THE SYSTEM SHALL render DashboardWing at 280px width with -15deg rotateY tilt
3. WHEN `spotlightState === balanced` THE SYSTEM SHALL position ChatWing at left: 3%
4. WHEN `spotlightState === balanced` THE SYSTEM SHALL position DashboardWing at right: 3%
5. WHEN `spotlightState === balanced` THE SYSTEM SHALL render both wings at full opacity (1.0)
6. WHEN `spotlightState === balanced` THE SYSTEM SHALL enable pointer events on both wings
7. THE SYSTEM SHALL preserve the existing balanced state behavior that activates when clicking ChatActivationText or dashboard icon

### Requirement 4: ChatSpotlight State Specifications

**User Story:** As a user, I want to expand the chat wing for better readability while keeping dashboard accessible in the background.

#### Acceptance Criteria

1. WHEN entering `chatSpotlight` state THE SYSTEM SHALL animate ChatWing to 340px width with 0deg rotateY (flat)
2. WHEN in `chatSpotlight` state THE SYSTEM SHALL position ChatWing at left: 5%
3. WHEN in `chatSpotlight` state THE SYSTEM SHALL animate DashboardWing to 180px width with maintained -15deg tilt
4. WHEN in `chatSpotlight` state THE SYSTEM SHALL fade DashboardWing to 30% opacity
5. WHEN in `chatSpotlight` state THE SYSTEM SHALL apply `saturate(0.6) blur(2px)` filter to DashboardWing
6. WHEN in `chatSpotlight` state THE SYSTEM SHALL disable pointer events on DashboardWing
7. WHEN in `chatSpotlight` state THE SYSTEM SHALL set ChatWing z-index to 20 and DashboardWing z-index to 5

### Requirement 5: DashboardSpotlight State Specifications

**User Story:** As a user, I want to expand the dashboard for easier configuration while keeping chat visible in the background.

#### Acceptance Criteria

1. WHEN entering `dashboardSpotlight` state THE SYSTEM SHALL animate DashboardWing to 360px width with 0deg rotateY (flat)
2. WHEN in `dashboardSpotlight` state THE SYSTEM SHALL position DashboardWing at right: 5%
3. WHEN in `dashboardSpotlight` state THE SYSTEM SHALL animate ChatWing to 180px width with maintained 15deg tilt
4. WHEN in `dashboardSpotlight` state THE SYSTEM SHALL fade ChatWing to 30% opacity
5. WHEN in `dashboardSpotlight` state THE SYSTEM SHALL apply `saturate(0.6) blur(2px)` filter to ChatWing
6. WHEN in `dashboardSpotlight` state THE SYSTEM SHALL disable pointer events on ChatWing
7. WHEN in `dashboardSpotlight` state THE SYSTEM SHALL set DashboardWing z-index to 20 and ChatWing z-index to 5

### Requirement 6: Spring Animation Specifications

**User Story:** As a user, I want smooth, natural-feeling transitions between spotlight states that match the existing dashboard-wing.tsx animations.

#### Acceptance Criteria

1. WHEN any spotlight state transition occurs THE SYSTEM SHALL animate using Framer Motion spring physics
2. THE SYSTEM SHALL use spring configuration: stiffness 280, damping 25, mass 0.8 (consistent with dashboard-wing.tsx)
3. THE SYSTEM SHALL animate the following properties: width, left/right positioning, rotateY, opacity, filter
4. THE SYSTEM SHALL complete transitions in approximately 400-550ms
5. WHEN transitioning between spotlight states THE SYSTEM SHALL animate both wings simultaneously
6. THE SYSTEM SHALL ensure no visual clipping during transitions
7. THE SYSTEM SHALL maintain 80px minimum gap between wing edges throughout transitions

### Requirement 7: Iris Aperture Header Controls

**User Story:** As a user, I want a crystalline aperture maximize button in each wing's header that morphs between states to trigger spotlight mode.

#### Acceptance Criteria

1. THE SYSTEM SHALL render Iris Aperture button in ChatWing header between title and other icons
2. THE SYSTEM SHALL render Iris Aperture button in DashboardWing header between title and other icons
3. THE SYSTEM SHALL create a custom `IrisApertureIcon` component with diamond-to-aperture morphing animation
4. WHEN in rest state (balanced or other wing spotlighted) THE SYSTEM SHALL display four triangular points forming diamond shape (✦)
5. WHEN in active/maximized state (current wing spotlighted) THE SYSTEM SHALL display points expanded outward leaving square center (✧)
6. THE SYSTEM SHALL animate points moving along diagonals over 400ms spring transition
7. THE SYSTEM SHALL use 1px stroke in rest state with white/60 color (`${fontColor}60`)
8. THE SYSTEM SHALL use glow fill in active state with glowColor
9. THE SYSTEM SHALL set icon size to 14x14px
10. THE SYSTEM SHALL morph smoothly between states with no jarring transitions
11. THE SYSTEM SHALL match crystalline command aesthetic of the IRIS interface
12. WHEN clicking ChatWing aperture button THE SYSTEM SHALL call `toggleChatSpotlight()`
13. WHEN clicking DashboardWing aperture button THE SYSTEM SHALL call `toggleDashboardSpotlight()`
14. THE SYSTEM SHALL apply hover effects: background highlight and brightness increase on rest state

### Requirement 8: Keyboard Escape Handling

**User Story:** As a user, I want to press Escape to restore balanced state when in a spotlight mode.

#### Acceptance Criteria

1. WHEN in `chatSpotlight` state AND user presses Escape THE SYSTEM SHALL transition to `balanced` state
2. WHEN in `dashboardSpotlight` state AND user presses Escape THE SYSTEM SHALL transition to `balanced` state
3. WHEN in `balanced` state AND user presses Escape THE SYSTEM SHALL maintain existing behavior (close wings)
4. THE SYSTEM SHALL close any open notification dropdowns before spotlight state transition
5. THE SYSTEM SHALL handle Escape key at the page level with proper priority

### Requirement 9: Content Adaptation

**User Story:** As a user, I want wing content to adapt when spotlighted for better usability.

#### Acceptance Criteria

1. WHEN ChatWing enters `chatSpotlight` state THE SYSTEM SHALL expand message bubbles to 90% width
2. WHEN ChatWing enters `chatSpotlight` state THE SYSTEM SHALL increase horizontal padding from 16px to 20px
3. WHEN DashboardWing enters `dashboardSpotlight` state THE SYSTEM SHALL expand control inputs to 180px max width
4. WHEN DashboardWing enters `dashboardSpotlight` state THE SYSTEM SHALL apply full-bleed section headers with gradient
5. THE SYSTEM SHALL apply subtle scale (1.02) to content in spotlighted wing
6. THE SYSTEM SHALL maintain layout integrity during all content transitions

### Requirement 10: Notification System Compatibility

**User Story:** As a user, I want notifications to work correctly in all spotlight states.

#### Acceptance Criteria

1. WHEN in `chatSpotlight` state THE SYSTEM SHALL keep ChatWing notification bell functional
2. WHEN in `dashboardSpotlight` state THE SYSTEM SHALL keep DashboardWing notification bell functional
3. THE SYSTEM SHALL disable notification interactions on the minimized (background) wing
4. THE SYSTEM SHALL close notification dropdowns before spotlight state transitions
5. THE SYSTEM SHALL preserve notification state across spotlight transitions

### Requirement 11: Spatial Constraints

**User Story:** As a user, I want the wings to maintain proper positioning without overlap within the window.

#### Acceptance Criteria

1. THE SYSTEM SHALL enforce minimum 80px gap between wing edges in all spotlight states
2. THE SYSTEM SHALL limit maximum wing expansion to 360px (Chat: 340px, Dashboard: 360px)
3. THE SYSTEM SHALL limit minimum background wing width to 180px
4. THE SYSTEM SHALL calculate positions dynamically to prevent overlap
5. THE SYSTEM SHALL maintain layout integrity at 680px window size
6. THE SYSTEM SHALL ensure z-index layering: spotlighted wing z-20, background wing z-5

### Requirement 12: Integration with Existing Flow

**User Story:** As a user, I want the existing open flow (ChatActivationText → ChatOpen → Dashboard icon → BothOpen) to work exactly as before, with spotlight mode as an enhancement.

#### Acceptance Criteria

1. WHEN user clicks ChatActivationText THE SYSTEM SHALL open ChatWing (existing behavior preserved)
2. WHEN user clicks dashboard icon in ChatWing THE SYSTEM SHALL open DashboardWing to `balanced` state (existing behavior)
3. THE SYSTEM SHALL NOT change the existing UILayoutState transitions
4. THE SYSTEM SHALL only enable spotlight controls when `uiState === UI_STATE_BOTH_OPEN`
5. THE SYSTEM SHALL initialize `spotlightState` to `balanced` whenever entering `UI_STATE_BOTH_OPEN`
6. THE SYSTEM SHALL hide/disable spotlight controls when `uiState !== UI_STATE_BOTH_OPEN`

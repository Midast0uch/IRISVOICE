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
4. THE SYSTEM SHALL initialize `spotlightState` to `balanced` whenever entering `UI_STATE_BOTH_OPEN` from idle
5. THE SYSTEM SHALL enable spotlight controls when `uiState === UI_STATE_BOTH_OPEN`
6. THE SYSTEM SHALL enable `chatSpotlight` toggle when `uiState === UI_STATE_CHAT_OPEN`

### Requirement 13: Single-Wing Close Behavior (NEW)

**User Story:** As a user, I want clicking the exit icon in a wing to close only that specific wing while keeping the other wing open, allowing me to switch between single-wing views without returning to idle.

#### Acceptance Criteria

1. WHEN in `UI_STATE_BOTH_OPEN` AND user clicks Exit on ChatWing THE SYSTEM SHALL call `closeChat()` (not `closeAll()`)
2. WHEN `closeChat()` is called from `UI_STATE_BOTH_OPEN` THE SYSTEM SHALL transition to `UI_STATE_DASHBOARD_OPEN`
3. WHEN transitioning to `UI_STATE_DASHBOARD_OPEN` THE SYSTEM SHALL keep DashboardWing visible and interactive
4. WHEN in `UI_STATE_BOTH_OPEN` AND user clicks Exit on DashboardWing THE SYSTEM SHALL call `closeDashboard()` (not `closeAll()`)
5. WHEN `closeDashboard()` is called from `UI_STATE_BOTH_OPEN` THE SYSTEM SHALL transition to `UI_STATE_CHAT_OPEN`
6. WHEN transitioning to `UI_STATE_CHAT_OPEN` from `UI_STATE_BOTH_OPEN` THE SYSTEM SHALL restore `chatSpotlight` state if it was active
7. THE SYSTEM SHALL preserve wing content state (no remount) during single-wing close transitions
8. THE SYSTEM SHALL animate single-wing transitions with spring physics (stiffness 280, damping 25)

### Requirement 14: Dashboard Solo View (NEW)

**User Story:** As a user, I want a solo dashboard view that mirrors the ChatWing's angled orientation when opened alone, ensuring visual consistency across both wing types.

#### Acceptance Criteria

1. THE SYSTEM SHALL support `UI_STATE_DASHBOARD_OPEN` state for dashboard-only view
2. WHEN in `UI_STATE_DASHBOARD_OPEN` THE SYSTEM SHALL render DashboardWing at 280px width
3. WHEN in `UI_STATE_DASHBOARD_OPEN` THE SYSTEM SHALL apply rotateY(-15deg) rotation (mirroring ChatWing)
4. WHEN in `UI_STATE_DASHBOARD_OPEN` THE SYSTEM SHALL position DashboardWing at right: 3%
5. WHEN in `UI_STATE_DASHBOARD_OPEN` THE SYSTEM SHALL render DashboardWing at full opacity (1.0)
6. WHEN in `UI_STATE_DASHBOARD_OPEN` THE SYSTEM SHALL enable full pointer events on DashboardWing
7. WHEN in `UI_STATE_DASHBOARD_OPEN` THE SYSTEM SHALL set DashboardWing z-index to 10
8. THE SYSTEM SHALL provide `openDashboardSolo()` method to enter `UI_STATE_DASHBOARD_OPEN`
9. WHEN `openDashboardSolo()` is called THE SYSTEM SHALL set `spotlightState` to `DASHBOARD_SPOTLIGHT`
10. THE SYSTEM SHALL add `isSolo` prop to DashboardWing to distinguish solo vs shared view
11. THE SYSTEM SHALL enable `toggleDashboardSpotlight()` when `uiState === UI_STATE_DASHBOARD_OPEN`
12. WHEN in `UI_STATE_DASHBOARD_OPEN` THE SYSTEM SHALL render Iris Aperture icon in DashboardWing header
13. WHEN user clicks Iris Aperture in solo dashboard view THE SYSTEM SHALL toggle between `DASHBOARD_SPOTLIGHT` and `BALANCED`
14. WHEN in `DASHBOARD_SPOTLIGHT` solo mode THE SYSTEM SHALL expand DashboardWing to 380px width
15. WHEN in `BALANCED` solo mode THE SYSTEM SHALL render DashboardWing at 280px width with -15deg rotation
16. THE SYSTEM SHALL animate spotlight transitions in solo mode with spring physics (stiffness 280, damping 25)

### Requirement 18: Chat Open from Dashboard (NEW)

**User Story:** As a user, when I'm in dashboard-only solo view, I want to be able to open the ChatWing to return to the both-wing view without closing the dashboard first.

#### Acceptance Criteria

1. THE SYSTEM SHALL render a chat icon button in DashboardWing header between the notification icon and close icon
2. THE chat icon SHALL only be visible when `onOpenChat` prop is provided AND chat is not already open
3. THE SYSTEM SHALL provide `openChatFromDashboard()` method that transitions from `UI_STATE_DASHBOARD_OPEN` to `UI_STATE_BOTH_OPEN`
4. WHEN `openChatFromDashboard()` is called THE SYSTEM SHALL preserve `DASHBOARD_SPOTLIGHT` state if active
5. WHEN `openChatFromDashboard()` is called THE SYSTEM SHALL default to `BALANCED` if dashboard was not spotlighted
6. THE SYSTEM SHALL pass `onOpenChat={isDashboardOpen ? openChatFromDashboard : undefined}` to DashboardWing
7. THE SYSTEM SHALL pass `isChatOpen` prop to DashboardWing for visual state management
8. WHEN user clicks chat icon in dashboard solo view THE SYSTEM SHALL transition to both-open view
9. THE chat icon SHALL have hover effects matching other header icons
10. THE chat icon SHALL close notification panel when clicked (if open)
11. THE SYSTEM SHALL hide chat icon when in `UI_STATE_BOTH_OPEN` (chat already visible)
12. THE transition from dashboard solo to both-open SHALL use spring animation (stiffness 280, damping 25)

### Requirement 15: IrisOrb Dual-Close Behavior (NEW)

**User Story:** As a user, I want clicking the IrisOrb while both wings are open to close both wings simultaneously in a synchronized animation, returning to the idle centered state.

#### Acceptance Criteria

1. WHEN `uiState === UI_STATE_BOTH_OPEN` AND user clicks IrisOrb THE SYSTEM SHALL call `closeAll()`
2. WHEN `closeAll()` is called THE SYSTEM SHALL close both wings simultaneously
3. THE SYSTEM SHALL use synchronized spring animations for dual-close transition
4. THE SYSTEM SHALL maintain consistent animation timing (400-550ms) for dual-close
5. WHEN dual-close completes THE SYSTEM SHALL transition to `UI_STATE_IDLE`
6. THE SYSTEM SHALL ensure IrisOrb is centered and fully visible after dual-close
7. THE SYSTEM SHALL reset `spotlightState` to `BALANCED` when dual-close completes
8. THE SYSTEM SHALL clear `lastActiveWingRef` when dual-close completes

### Requirement 16: Active Wing Tracking (NEW)

**User Story:** As a developer, I want the system to track which wing was last active so state transitions can preserve the appropriate context.

#### Acceptance Criteria

1. THE SYSTEM SHALL maintain `lastActiveWingRef` with values: `'chat' | 'dashboard' | null`
2. WHEN `openChat()` is called THE SYSTEM SHALL set `lastActiveWingRef.current = 'chat'`
3. WHEN `openDashboardSolo()` is called THE SYSTEM SHALL set `lastActiveWingRef.current = 'dashboard'`
4. WHEN `closeChat()` is called from `UI_STATE_BOTH_OPEN` THE SYSTEM SHALL set `lastActiveWingRef.current = 'dashboard'`
5. WHEN `closeDashboard()` is called from `UI_STATE_BOTH_OPEN` THE SYSTEM SHALL set `lastActiveWingRef.current = 'chat'`
6. WHEN entering `UI_STATE_BOTH_OPEN` THE SYSTEM SHALL set `lastActiveWingRef.current = null`
7. THE SYSTEM SHALL expose `lastActiveWing` in the hook's return value for external use
8. THE SYSTEM SHALL clear `lastActiveWingRef` when entering `UI_STATE_IDLE`

### Requirement 17: Wing State Preservation (NEW)

**User Story:** As a user, I want wing content to be preserved during single-wing close transitions, avoiding flickering or remounting of components.

#### Acceptance Criteria

1. WHEN transitioning from `UI_STATE_BOTH_OPEN` to `UI_STATE_CHAT_OPEN` THE SYSTEM SHALL NOT remount ChatWing
2. WHEN transitioning from `UI_STATE_BOTH_OPEN` to `UI_STATE_DASHBOARD_OPEN` THE SYSTEM SHALL NOT remount DashboardWing
3. THE SYSTEM SHALL use React key stability to prevent remounting during transitions
4. WHEN a wing transitions from shared view to solo view THE SYSTEM SHALL preserve all internal state
5. THE SYSTEM SHALL maintain scroll position during single-wing close transitions
6. THE SYSTEM SHALL preserve notification panel state during single-wing close transitions
7. THE SYSTEM SHALL ensure spotlight toggle state persists across single-wing transitions
8. THE SYSTEM SHALL complete all state updates in a single render cycle to prevent flickering

### Requirement 13: IrisOrb Visibility

**User Story:** As a user, I want the IrisOrb (central aperture button) to remain visible whenever the ChatWing is open, providing visual continuity and a consistent anchor point.

#### Acceptance Criteria

1. WHEN `uiState === UI_STATE_CHAT_OPEN` THE SYSTEM SHALL render IrisOrb in the center of the screen
2. WHEN `uiState === UI_STATE_BOTH_OPEN` THE SYSTEM SHALL render IrisOrb in the center of the screen
3. WHEN IrisOrb is visible with wings open THE SYSTEM SHALL scale it to 85% of normal size
4. WHEN IrisOrb is visible with wings open THE SYSTEM SHALL reduce opacity to 60%
5. WHEN IrisOrb is visible with wings open THE SYSTEM SHALL apply 2px blur filter
6. WHEN IrisOrb is visible with wings open THE SYSTEM SHALL set `pointerEvents: 'none'` to prevent interaction blocking
7. WHEN IrisOrb is visible with wings open THE SYSTEM SHALL set z-index to 5 (behind wings)
8. WHEN `uiState === UI_STATE_IDLE` THE SYSTEM SHALL render IrisOrb at full scale (100%), full opacity (100%), no blur, with `pointerEvents: 'auto'`

### Requirement 14: Dashboard Icon Toggle

**User Story:** As a user, I want the Dashboard icon in the ChatWing header to toggle the DashboardWing open and closed, making it easy to switch between chat-only and both-wing views.

#### Acceptance Criteria

1. THE SYSTEM SHALL render Dashboard icon in ChatWing header between Notifications and Close icons
2. WHEN dashboard is NOT open THE SYSTEM SHALL display Dashboard icon at 60% opacity with neutral color
3. WHEN dashboard IS open THE SYSTEM SHALL display Dashboard icon at 90% opacity with highlighted background
4. WHEN user clicks Dashboard icon and dashboard is closed THE SYSTEM SHALL call `onDashboardClick()` to open dashboard
5. WHEN user clicks Dashboard icon and dashboard is open THE SYSTEM SHALL call `onDashboardClose()` to close only the chat wing
6. WHEN dashboard opens from chat-only view THE SYSTEM SHALL preserve `chatSpotlight` state if it was active
7. THE SYSTEM SHALL apply hover effects to Dashboard icon in both states for discoverability

### Requirement 15: Bidirectional State Transitions

**User Story:** As a user, I want smooth bidirectional transitions between chat-only spotlight and both-wing states, allowing me to expand and collapse the dashboard without losing my chat context.

#### Acceptance Criteria

1. WHEN in `UI_STATE_CHAT_OPEN` with `chatSpotlight` active AND user opens dashboard THE SYSTEM SHALL preserve the `chatSpotlight` state in `wasChatSpotlightRef`
2. WHEN transitioning from `UI_STATE_CHAT_OPEN` to `UI_STATE_BOTH_OPEN` THE SYSTEM SHALL maintain the spotlight state (not reset to balanced)
3. WHEN in `UI_STATE_BOTH_OPEN` AND user clicks Dashboard icon to close THE SYSTEM SHALL call `closeChat()` method
4. THE SYSTEM SHALL provide `closeChat()` method that closes only ChatWing while keeping DashboardWing visible
5. WHEN `closeChat()` is called THE SYSTEM SHALL transition from `UI_STATE_BOTH_OPEN` to a dashboard-only view (not idle)
6. THE SYSTEM SHALL NOT reset spotlight state when transitioning between `UI_STATE_CHAT_OPEN` and `UI_STATE_BOTH_OPEN`
7. THE SYSTEM SHALL ONLY reset spotlight state to `balanced` when entering `UI_STATE_IDLE`

### Requirement 16: Selective Close Behavior

**User Story:** As a user, I want the ChatWing close button to behave contextually—closing only the chat when both wings are open, or closing everything when only chat is open.

#### Acceptance Criteria

1. WHEN in `UI_STATE_BOTH_OPEN` AND user clicks ChatWing close button THE SYSTEM SHALL call `closeChat()` (not `closeAll()`)
2. WHEN in `UI_STATE_CHAT_OPEN` (only) AND user clicks ChatWing close button THE SYSTEM SHALL call `closeAll()`
3. WHEN `closeChat()` is called from `UI_STATE_BOTH_OPEN` THE SYSTEM SHALL keep DashboardWing open and visible
4. THE SYSTEM SHALL pass conditional `onClose` handler to ChatWing: `isBothOpen ? closeChat : closeAll`
5. WHEN chat closes while dashboard remains open THE SYSTEM SHALL ensure IrisOrb remains visible
6. THE SYSTEM SHALL wire `onDashboardClose={closeChat}` prop in page.tsx for dashboard toggle functionality

### Requirement 17: State Preservation

**User Story:** As a user, I want my chat spotlight state to be preserved when I temporarily open the dashboard and then close it, maintaining my preferred viewing configuration.

#### Acceptance Criteria

1. THE SYSTEM SHALL maintain `wasChatSpotlightRef` to track if user was in chat spotlight before opening dashboard
2. WHEN `openDashboard()` is called from `UI_STATE_CHAT_OPEN` THE SYSTEM SHALL save current spotlight state to ref
3. WHEN returning to chat-only view after closing dashboard THE SYSTEM SHALL restore the previous spotlight state
4. THE SYSTEM SHALL clear `wasChatSpotlightRef` when entering `UI_STATE_IDLE`
5. WHEN spotlight state is preserved across transitions THE SYSTEM SHALL animate smoothly to the restored state
6. THE SYSTEM SHALL NOT persist spotlight state across full application restarts (session-only)

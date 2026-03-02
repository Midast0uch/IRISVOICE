# Requirements: IRIS Wings V2

## Introduction

This spec covers a comprehensive UI redesign of the IRIS assistant's wing components — ChatWing (left) and DashboardWing (right). The redesign introduces a universal notification system shared across both wings, holographic visual effects, convergent-corner message bubbles, live TTS word highlighting, and a flexible dashboard configuration architecture. All changes must work within the existing component files and maintain strict dimension constraints.

**Design Philosophy:** Futuristic HUD (Heads-Up Display) aesthetic with holographic elements, edge glows, scanlines, and chromatic aberration effects. The wings should feel like transparent glass panels floating in 3D space.

---

## Requirements

### Requirement 1: Universal Notification System

**User Story:** As an IRIS user, I want to see notifications in both the ChatWing and DashboardWing, so that I can stay informed about alerts, permissions, errors, tasks, and completions regardless of which wing I'm viewing.

#### Acceptance Criteria

1.1 WHEN the ChatWing header renders THE SYSTEM SHALL display a notification bell icon between the History and Dashboard icons.

1.2 WHEN the DashboardWing header renders THE SYSTEM SHALL display a notification bell icon between the title and Close button.

1.3 WHEN a notification bell receives an unread notification THE SYSTEM SHALL display an animated indicator dot (2px, glow color) on the bell icon with a subtle pulse animation.

1.4 WHEN the user clicks the notification bell THE SYSTEM SHALL toggle the notification panel visibility with a 200ms height animation using `[0.22, 1, 0.36, 1]` easing.

1.5 WHEN the notification panel opens THE SYSTEM SHALL mark all notifications as read and hide the unread indicator.

1.6 IF notifications exist THEN THE SYSTEM SHALL render each notification with type-specific color coding (alert: #fbbf24, permission: #3b82f6, error: #ef4444, task: #a855f7, completion: #22c55e) and a subtle left border accent.

1.7 WHEN a permission-type notification is displayed THE SYSTEM SHALL render Allow and Deny action buttons with glow-color styling and hover effects.

1.8 WHEN a task-type notification is displayed THE SYSTEM SHALL render an animated progress bar showing completion percentage with glow color fill.

1.9 WHEN the user clicks "Clear all" THE SYSTEM SHALL remove all notifications from the panel with a fade-out animation.

1.10 IF the notification panel is open AND the user opens History (ChatWing) or another dropdown THE SYSTEM SHALL close the notification panel to maintain single-dropdown policy.

1.11 WHEN the backend sends a `notification` WebSocket message THE SYSTEM SHALL add the notification to the local state and show the unread indicator.

1.12 WHEN a permission notification's Allow/Deny button is clicked THE SYSTEM SHALL send a `notification_response` WebSocket message to the backend with the notification ID and response.

---

### Requirement 2: ChatWing Header Redesign (HUD Style)

**User Story:** As an IRIS user, I want a futuristic HUD-style ChatWing header, so that I can easily access conversation history, notifications, dashboard, and close controls with visual feedback.

#### Acceptance Criteria

2.1 WHEN the ChatWing renders THE SYSTEM SHALL display a 48px height header with icon order: Pulse indicator | Title | Notifications | History | Dashboard | Close.

2.2 WHEN a global error occurs THE SYSTEM SHALL display an animated red line (1px height) at the top of the header with pulsing opacity (2s infinite loop).

2.3 WHEN the voice state is "listening" THE SYSTEM SHALL animate the pulse indicator with a 1.2s breathing animation (scale 1→1.4→1, opacity 1→0.6→1) using the glow color.

2.4 WHEN a header icon is hovered THE SYSTEM SHALL apply a white/5% background and opacity transition to 90% with a 150ms ease transition.

2.5 WHEN the History icon is active THE SYSTEM SHALL apply glow color background (15% opacity) and glow color text.

2.6 THE SYSTEM SHALL render the header with a subtle bottom border using glow color at 15% opacity for HUD separation effect.

---

### Requirement 3: ChatWing Message Bubbles (Convergent HUD Design)

**User Story:** As an IRIS user, I want visually distinct message bubbles that indicate message direction with a futuristic aesthetic, so that I can easily distinguish my messages from IRIS responses.

#### Acceptance Criteria

3.1 WHEN a user message renders THE SYSTEM SHALL apply convergent corner styling: border-radius 16px 16px 4px 16px (sharp left toward Orb) with a subtle inner glow.

3.2 WHEN an IRIS message renders THE SYSTEM SHALL apply convergent corner styling: border-radius 16px 16px 16px 4px (sharp right toward Orb) with a left border accent using glow color at 50% opacity.

3.3 WHEN a user message is sent THE SYSTEM SHALL display a subtle glow effect (radial gradient) that fades over 300ms.

3.4 WHEN an IRIS message is being spoken (TTS active) THE SYSTEM SHALL highlight the currently spoken word with the glow color and text shadow (0 0 12px glowColor at 60% opacity).

3.5 WHEN TTS is active THE SYSTEM SHALL display an animated speaking indicator (3 bouncing dots with staggered delays: 0ms, 150ms, 300ms).

3.6 THE SYSTEM SHALL limit message bubble width to 85% of the container.

3.7 THE SYSTEM SHALL render message timestamps in 9px tabular-nums format with 50-70% opacity based on sender.

3.8 WHEN TTS word highlighting is active THE SYSTEM SHALL smoothly transition between words with 150ms ease animation.

---

### Requirement 4: ChatWing Input Area (Futuristic Command Line)

**User Story:** As an IRIS user, I want a futuristic command-line style input experience with visual feedback for voice state, so that I know when IRIS is listening and can see character counts.

#### Acceptance Criteria

4.1 WHEN the input area renders THE SYSTEM SHALL display a border-only input field (bottom border only, 2px) with a gradient fade background from deep black to transparent.

4.2 WHEN voice state is "listening" THE SYSTEM SHALL animate the border color based on audio level (alpha channel modulation from 50% to 100%).

4.3 WHEN voice state is "listening" THE SYSTEM SHALL display "● REC" indicator in the top-right corner with glow color and a blinking animation (1s infinite).

4.4 WHEN text is entered THE SYSTEM SHALL display character count in the top-right corner using 9px tabular-nums.

4.5 THE SYSTEM SHALL render a floating circular send button (36px diameter) positioned outside the input area to avoid clipping.

4.6 WHEN the send button is active (text present) THE SYSTEM SHALL apply a glow shadow (20px blur, 40% opacity) and chromatic aberration effect on hover (RGB split).

4.7 WHEN voice state is "listening" THE SYSTEM SHALL display an animated waveform visualization (12 bars, staggered animation with 50ms delays) below the input.

4.8 THE SYSTEM SHALL disable the send button when voiceState is "listening" or isTyping is true.

---

### Requirement 5: DashboardWing Header Redesign (HUD Style)

**User Story:** As an IRIS user, I want a consistent HUD-style header in the DashboardWing, so that I can access notifications and close the wing easily with visual feedback.

#### Acceptance Criteria

5.1 WHEN the DashboardWing renders THE SYSTEM SHALL display a 44px height header with icon order: Pulse indicator | Title | Notifications | Close.

---

### Requirement 5.5: Transparent Background Contrast

**User Story:** As an IRIS user, I want both wings to be readable over any background, so that the interface remains usable with transparent backgrounds.

#### Acceptance Criteria

5.5.1 THE SYSTEM SHALL apply a semi-transparent dark background (rgba(10, 10, 20, 0.95) minimum) to both wing containers to ensure readability over any background.

5.5.2 THE SYSTEM SHALL use high-contrast text colors (white at 85-95% opacity) for all primary text to ensure visibility.

5.5.3 THE SYSTEM SHALL apply backdrop-filter: blur(24px) to both wings to create visual separation from the background.

5.5.4 THE SYSTEM SHALL use glow color accents at sufficient opacity (minimum 50%) to ensure visibility against dark backgrounds.

5.5.5 THE SYSTEM SHALL ensure all interactive elements have visible borders or backgrounds (minimum rgba(255,255,255,0.08)) to distinguish them from the container.

5.2 THE SYSTEM SHALL apply the same notification bell behavior as Requirement 1 for the DashboardWing header.

5.3 WHEN the DashboardWing container renders THE SYSTEM SHALL apply inner glow effect: inset 8px 0 32px glowColor at 15% opacity on the left edge (facing the Orb).

5.4 THE SYSTEM SHALL render an edge Fresnel effect: 1px gradient line on the left edge with glow color at 40-60% opacity.

5.5 THE SYSTEM SHALL render the header with a subtle bottom border using glow color at 12% opacity for HUD separation effect.

---

### Requirement 6: DarkGlassDashboard Structure (Flexible HUD)

**User Story:** As an IRIS developer, I want the dashboard to use a flexible configuration structure, so that it can adapt to refactored settings without hardcoded IDs while maintaining a HUD aesthetic.

#### Acceptance Criteria

6.1 THE SYSTEM SHALL accept categories as a dynamic prop array with id, label, and icon properties.

6.2 THE SYSTEM SHALL support a collapsible "More" tab when more than 5 categories are provided.

6.3 WHEN "More" is clicked THE SYSTEM SHALL display a dropdown with additional categories using a slide-down animation.

6.4 THE SYSTEM SHALL render category tabs with layoutId animation for the active indicator (smooth sliding indicator).

6.5 WHEN a category is selected THE SYSTEM SHALL display a header with category icon, label, field count, and a reset button.

6.6 THE SYSTEM SHALL render fields in a full-width panel (no sidebar) with 48px row height and generous spacing.

6.7 THE SYSTEM SHALL apply a holographic background to the dashboard panel with subtle scanline and noise overlays.

---

### Requirement 7: Field Components (HUD Controls)

**User Story:** As an IRIS user, I want consistent, futuristic HUD-style form controls in the dashboard, so that I can easily configure IRIS settings with visual feedback.

#### Acceptance Criteria

7.1 WHEN a toggle field renders THE SYSTEM SHALL display a 40px × 20px switch with animated thumb (spring transition, stiffness 500, damping 30) and glow color when enabled.

7.2 WHEN a dropdown field renders THE SYSTEM SHALL display a styled select with white/6% background, hover border effect, and glow color focus state.

7.3 WHEN a slider field renders THE SYSTEM SHALL display a clickable track with gradient fill (glow color 80% to 100%), numeric value display, and subtle glow on the thumb.

7.4 WHEN a text/password field renders THE SYSTEM SHALL display an input with white/6% background, hover border effect, and glow color focus state with caret-color set to glow color.

7.5 WHEN a button field renders THE SYSTEM SHALL display a button with glow color border (35% opacity) and background (15% opacity).

7.6 WHEN a field has an error THE SYSTEM SHALL display an error message with red styling (#f87171), AlertCircle icon, and a subtle shake animation on the field row.

7.7 THE SYSTEM SHALL apply a hover background effect (white/2%) to field rows for better interactivity feedback.

---

### Requirement 8: Visual Effects System (Holographic HUD)

**User Story:** As an IRIS user, I want a cohesive holographic HUD visual theme, so that the interface feels futuristic and immersive.

#### Acceptance Criteria

8.1 THE SYSTEM SHALL apply holographic monochrome color scheme: bgDeep rgba(10, 10, 20, 0.98), bgSurface rgba(255, 255, 255, 0.03), bgElevated rgba(255, 255, 255, 0.06).

8.2 THE SYSTEM SHALL render scanline overlay: linear-gradient with 4px period at 2% opacity and mix-blend-mode: overlay.

8.3 THE SYSTEM SHALL render noise texture overlay: SVG fractalNoise filter at 3% opacity for film grain effect.

8.4 WHEN interactive elements are hovered THE SYSTEM SHALL apply chromatic aberration: 0.3px RGB split effect using box-shadow (red left, blue right).

8.5 THE SYSTEM SHALL apply edge glow on both wings: 8px blur, 15% opacity, facing the Orb (left for ChatWing, right for DashboardWing).

8.6 WHEN the Confirm button is hovered THE SYSTEM SHALL display a 2-second infinite shine sweep animation (linear gradient sweep across button).

8.7 THE SYSTEM SHALL use backdrop-filter: blur(24px) on both wing containers for the frosted glass HUD effect.

8.8 THE SYSTEM SHALL apply subtle 3D perspective to the wings (rotateY 15deg/-15deg, rotateX 2deg) for depth perception.

---

### Requirement 9: Critical Constraints (No Tolerance)

**User Story:** As an IRIS developer, I want clear dimensional constraints, so that the wings maintain their designed spatial relationship to the Orb.

#### Acceptance Criteria

9.1 THE SYSTEM SHALL set ChatWing width to 255px (±0px tolerance).

9.2 THE SYSTEM SHALL set DashboardWing width to 280px (±0px tolerance).

9.3 THE SYSTEM SHALL set both wings height to 50vh (±0vh tolerance).

9.4 THE SYSTEM SHALL position ChatWing at left: 3% with rotateY(15deg).

9.5 THE SYSTEM SHALL position DashboardWing at right: 3% with rotateY(-15deg).

9.6 THE SYSTEM SHALL NOT create new component files unless absolutely necessary.

9.7 THE SYSTEM SHALL work within existing components: ChatWing, DashboardWing, DarkGlassDashboard.

---

### Requirement 10: Backend Integration

**User Story:** As an IRIS developer, I want the wings to integrate seamlessly with the existing backend WebSocket system, so that all functionality works without errors.

#### Acceptance Criteria

10.1 WHEN the backend sends a `notification` message via WebSocket THE SYSTEM SHALL parse and add it to the notification state.

10.2 WHEN a user responds to a permission notification THE SYSTEM SHALL send a `notification_response` message with `{ notification_id, response: 'allow' | 'deny' }`.

10.3 THE SYSTEM SHALL use the existing `sendMessage` function from props for all backend communication.

10.4 THE SYSTEM SHALL read `voiceState` and `audioLevel` from the existing `useNavigation` context.

10.5 THE SYSTEM SHALL read `activeTheme` (with glow, primary, font colors) from the existing `useNavigation` context.

10.6 THE SYSTEM SHALL handle `fieldErrors` from the backend and display them on the corresponding fields.

10.7 THE SYSTEM SHALL call `updateMiniNodeValue` from context when field values change.

10.8 THE SYSTEM SHALL call `confirmMiniNode` from context when the Confirm button is pressed.

---

### Requirement 11: Accessibility & Performance

**User Story:** As an IRIS user with accessibility needs, I want the wings to be usable with assistive technologies and smooth animations.

#### Acceptance Criteria

11.1 THE SYSTEM SHALL maintain focusable elements with visible focus indicators (2px glow color outline).

11.2 THE SYSTEM SHALL provide title attributes on all icon buttons for screen readers.

11.3 THE SYSTEM SHALL use reduced-motion media query to disable animations when user prefers reduced motion.

11.4 THE SYSTEM SHALL ensure animations run at 60fps using GPU-accelerated properties (transform, opacity).

11.5 THE SYSTEM SHALL support keyboard navigation between header icons (Tab key) and dropdown activation (Enter/Space).

11.6 THE SYSTEM SHALL maintain ARIA labels on notification panel (aria-expanded, aria-live for new notifications).

---

### Requirement 12: Error Handling & Edge Cases

**User Story:** As an IRIS user, I want the wings to handle errors gracefully without crashing, so that I can continue using the application.

#### Acceptance Criteria

12.1 WHEN a WebSocket message fails to parse THE SYSTEM SHALL log the error and continue operating (not crash).

12.2 WHEN a notification type is unknown THE SYSTEM SHALL default to the glow color and Info icon.

12.3 WHEN the notification panel exceeds 50% height THE SYSTEM SHALL enable vertical scrolling.

12.4 WHEN field validation fails THE SYSTEM SHALL display the error inline and prevent confirmation until resolved.

12.5 WHEN the backend is disconnected THE SYSTEM SHALL show a subtle offline indicator in the header.

12.6 WHEN TTS word index is out of bounds THE SYSTEM SHALL gracefully fall back to displaying plain text.

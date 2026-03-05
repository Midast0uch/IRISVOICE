# Requirements: Theme Color System Cleanup

## Introduction

This spec consolidates the theme color system to eliminate confusion about which component controls what. Currently, multiple components and contexts are affecting colors, creating an inconsistent user experience. The goal is to establish a single source of truth for theme colors with a clean, intuitive UI.

## Requirements

### Requirement 1: Single Source of Truth for Theme Colors

**User Story:** As a user, I want theme colors to be consistent across the entire application, so that when I change a theme, all components update predictably.

#### Acceptance Criteria

1. WHEN a user selects a theme THE SYSTEM SHALL apply that theme consistently to:
   - Main node orbs (category buttons)
   - Wheel view components (rings, glows, accents)
   - Dashboard wing glow effects
   - Chat view glow effects
2. THE SYSTEM SHALL use `BrandColorContext` as the single source of truth for all theme colors
3. THE SYSTEM SHALL remove any duplicate or conflicting color contexts
4. THE SYSTEM SHALL ensure all components read from `BrandColorContext` via the `useBrandColor()` hook

### Requirement 2: Remove Conflicting Theme Components

**User Story:** As a user, I don't want to see multiple theme controls that conflict with each other, so that I have one clear way to change the theme.

#### Acceptance Criteria

1. THE SYSTEM SHALL remove `ThemeTestSwitcher.tsx` (testing component that's causing confusion)
2. THE SYSTEM SHALL remove any inline theme color controls from `SidePanel.tsx` that bypass `ThemeSwitcherCard`
3. THE SYSTEM SHALL remove any color picker fields from `cards.ts` that duplicate theme functionality
4. THE SYSTEM SHALL ensure `ThemeSwitcherCard` is the ONLY component for theme selection

### Requirement 3: ThemeSwitcherCard as Primary Control

**User Story:** As a user, I want a single, clear theme switcher that shows me the available themes, so that I can easily change the look of the application.

#### Acceptance Criteria

1. THE SYSTEM SHALL display `ThemeSwitcherCard` as a compact widget showing the 4 theme options:
   - Aether (cyan-blue)
   - Ember (copper-orange)
   - Aurum (gold)
   - Verdant (forest green)
2. WHEN a user clicks a theme preview THE SYSTEM SHALL immediately apply that theme
3. THE SYSTEM SHALL highlight the currently selected theme
4. THE SYSTEM SHALL persist the selected theme to `localStorage`

### Requirement 4: Improved SidePanel Theme UI

**User Story:** As a user, I want to see organized theme controls in the SidePanel when I select the theme card, so that I can fine-tune colors without clutter.

#### Acceptance Criteria

1. WHEN the theme card is selected THE SYSTEM SHALL display:
   - 4 theme preview cards (Aether, Ember, Aurum, Verdant) at the top
   - Collapsible "Brand Color" section with HSL sliders (Hue, Saturation, Lightness)
   - Collapsible "Base Plate" section with HSL sliders (Hue, Saturation, Lightness)
2. THE SYSTEM SHALL group sliders into sections that can be expanded/collapsed
3. THE SYSTEM SHALL show real-time color preview as sliders move
4. THE SYSTEM SHALL include a "Reset to Default" button for each color section
5. THE SYSTEM SHALL save custom color adjustments to `localStorage`

### Requirement 5: Component Integration

**User Story:** As a developer, I want clear documentation on how components should use theme colors, so that I don't accidentally create conflicts in the future.

#### Acceptance Criteria

1. THE SYSTEM SHALL document that ALL components MUST use `useBrandColor()` hook
2. THE SYSTEM SHALL remove any props that pass colors down (use context instead)
3. THE SYSTEM SHALL ensure `dashboard-wing.tsx` reads `glowColor` from `activeTheme.glow`
4. THE SYSTEM SHALL ensure `chat-view.tsx` reads `glowColor` from `activeTheme.glow`
5. THE SYSTEM SHALL ensure `wheel-view` components read from `BrandColorContext`

## Out of Scope

- Adding new themes beyond the 4 existing ones
- Creating separate color systems for different UI areas
- Adding animation effects to theme transitions
- Supporting external theme files

## Success Criteria

- User sees only ONE theme control interface
- All UI components use consistent colors from BrandColorContext
- SidePanel shows organized, collapsible color sections
- Theme selection persists across sessions
- No conflicting theme components remain in the codebase
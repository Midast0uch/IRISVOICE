# IRIS System HUD: Dashboard Design & Architecture Overview

The IRIS System HUD (Dashboard) is a high-performance, glassmorphic control interface designed for deep integration with the IRIS VOICE ecosystem. This document outlines the architectural decisions, design philosophies, and technical refinements implemented to achieve its premium aesthetic and functional precision.

## Design Philosophy

The dashboard adheres to a "Fluid Precision" aesthetic, balancing immersive visual depth with strict functional alignment.

1.  **Immersive Depth (Glassmorphism)**: 
    *   Primary background depth and `backdrop-blur-xl` are handled at the wrapper level (`DashboardWing.tsx`).
    *   Internal components utilize transparency to allow the global glass effects and dynamic gradients to "bleed through."
2.  **Visual Continuity**: 
    *   The Action Bar background extends fully to the dashboard edges, serving as a solid foundation that prevents the "clipped" look typically associated with boxed layouts.
3.  **Content Protection**: 
    *   A system of asymmetric and strategic padding (`pl-12 pr-24`) ensures that while backgrounds are fluid, critical content (text, buttons, indicators) remains protected within a safe visual buffer.

## Component Architecture

### 1. Dashboard Wrapper (`DashboardWing.tsx`)
*   **Role**: Global container and visual anchor.
*   **Key Logic**:
    *   Handles the primary `motion.div` transitions and glass effects.
    *   Manages the "Single Depth" render, ensuring that no internal component adds redundant background stacking.

### 2. Core Dashboard (`dark-glass-dashboard.tsx`)
*   **Role**: The main layout orchestrator for "System" and "Customize" hubs.
*   **Layout Sections**:
    *   **Header**: Standardized height (12px height in compact, h-16 in marketplace) with integrated navigation icons.
    *   **Subsection Bars**: Reusable expanding rows that mirror the field logic from the `WheelView` for data consistency.
    *   **Action Bar**: A bottom-docked status bar that displays connectivity (`Wifi`), engine state (`Brain`), and system status (`Activity`).
*   **Data Logic**: Implements an `Apply Settings` flow that persists data locally using `sendMessage('confirm_card', ...)`, ensuring parity with the side-panel interaction model.

### 3. Marketplace Hub (`MarketplaceScreen.tsx`)
*   **Role**: A dynamic integration portal for the IRIS ecosystem.
*   **Design Refinements**:
    *   **Zero-Clipping Layout**: Internal card padding (`p-6`) and margins (`mx-1`) are tuned to prevent clipping during hover-scale animations.
    *   **Synchronized Alignment**: Uses the same asymmetric padding logic as the main dashboard to maintain a perfectly straight vertical line across all views.

## Technical Refinements

### Fluid Layout vs. Fixed Buffer
To achieve the "seamless" Look the dashboard transitions between two states:
- **Global Wrapper Padding**: Provides a unified 12px "safe zone" around the entire component.
- **Selective Bleed**: To avoid clipping on the Action Bar, global padding is removed, and internal padding is applied selectively to components. This allows the Action Bar's dark background (`bg-black/60`) to fill the corner while the Header and Content areas maintain a visual buffer of `24px`.

### Precision Positioning
Interactive elements like the **APPLY** button are positioned using precise inline styles (e.g., `marginRight: '52px'`) to ensure they align perfectly with visual cues like status indicators, regardless of the dynamic resizing of parent containers.

### Data Persistence
- **Local Persistence**: All "Apply" actions trigger a `confirm_card` message.
- **State Sync**: The dashboard maintains a local `fieldValues` state that is synchronized with the global store upon application, ensuring that user changes are both immediate and persistent.

---

*Last Updated: 2026-03-17*

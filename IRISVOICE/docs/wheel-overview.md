# WheelView Architecture & Design Overview

This document provides a comprehensive breakdown of the **WheelView** component, a high-fidelity, interactive navigation and control interface designed for the IRISVOICE ecosystem. The design follows a data-driven, "Digital Energy" aesthetic, emphasizing depth, motion synchronization, and tactile feedback.

## 1. Visual Philosophy
The WheelView is built on an **Energy-First** architecture. 
- **Structural Elements** (Interactive Rings) are muted into slate-grey "mechanisms."
- **Energy Elements** (Kinetic Gliders, Glow Aura) utilize high-vibrancy brand colors to draw the eye to motion and status.
- **Topography** (White Labels) ensures razor-sharp legibility against complex background layers.

---

## 2. Layered SVG Stack (Bottom to Top)
The `DualRingMechanism` utilizes a strictly ordered SVG stack to achieve its layered depth effect.

| Order | Component Name | Description | Sizing/Radius |
| :--- | :--- | :--- | :--- |
| 1 | **Wide-Field Voice Aura** | Expanded Radial Gradient covering the entire stage. | `r=orbSize*0.7`, `0.95 idle opacity` |
| 2 | **Dynamic Background Aura** | Soft edge softening layer for depth transition. | `r=orbSize*0.52`, `blur: 40px` |
| 3 | **Bright Liquid Frame**| 5px Metallic ring with edge glow and 12s kinetic energy pulse. | `r=outerRadius+30`, `stroke: 5px` |
| 4 | **Neon Edge Bloom** | High-vibrancy neon pulse at the structural boundary. | `r=outerRadius+32.5`, `blur: 8px` |
| 5 | **Orbital Ticks** | 12 energetic reference points (30° intervals). | `r=outerRadius+14` to `+23` |
| 6 | **Barrier Kinetic Glider**| A high-density, segmented frame sitting on the tips of the ticks. | `r=outerRadius+23`, `strokeWidth: 2.7px` |
| 7 | **Interactive Outer Ring** | Solid metallic ring with segment edge glows. | `r=orbSize*0.39`, `opacity: 0.95` |
| 8 | **Gap Kinetic Glider** | A mid-density, segmented frame sitting between the interactive rings. | `r=orbSize*0.33`, `strokeWidth: 2.7px` |
| 9 | **Interactive Inner Ring** | Solid metallic ring with segment edge glows. | `r=orbSize*0.27`, `opacity: 0.95` |
| 10 | **Core Kinetic Glider** | A protective energy frame surrounding the central IrisOrb. | `r=orbSize*0.185`, `strokeWidth: 2.7px` |
| 11 | **IrisOrb (Tactile Core)** | The primary control point and category label. | `diameter: 64px`, `zIndex: 100` |
| 12 | **Safety Buffer** | 200px SVG margin + absolute overflow for zero clipping. | `overflow: visible` |
| 13 | **Connection Bridge** | High-intensity beam anchoring machine to panel. | `opacity: 0.9`, `gap: 25px` |

---

## 3. Kinetic Glider System
The Gliders are `motion.circle` elements utilizing `strokeDasharray` to create sophisticated digital patterns.

### Barrier Glider (Outermost)
- **Pattern**: 48 segments total (4 segments per 30° tick sector).
- **Segment Length**: ~18.6px.
- **Gaps**: ~4px ("Barely Touching").
- **Effect**: Creates a sophisticated, high-frequency digital loop that "caps" the energy ticks.

### Gap & Core Gliders
- **Pattern**: 2 long arcs (180° each) with a small gap.
- **Motion**: They utilize a counter-spin animation relative to the interactive rings to create visual parallax.

---

## 4. Interaction & Tactile Feedback
The interface is designed to feel physical despite its digital nature.

- **Tactile Center Button**: 
  - **Interaction**: Framer Motion `whileTap={{ scale: 0.88 }}`.
  - **Single-Click**: 
    - **Active Mode**: Immediately deactivates voice only.
    - **Idle Mode**: Transitions **Back to Level 2** (Category view).
  - **Double-Click**: Exclusive trigger to start the Voice Aura engine.
- **Connection Bridge**: 
  - **Hot Laser Beam**: High-intensity **3.2px technical beam** anchored at **438px** to avoid moving barrier gliders.
  - **Static Structural Frame**: Connects to a stationary, high-fidelity frame at **radius 146**, ensuring zero overlap with rotating segments.
  - **Centering**: Perfect horizontal bisection (375px Y) across Hub, Laser, and SidePanel.
  - **Panel Scale**: Vertical expansion to **680px** with **px-6 internal card padding** and **Rounded-XL** input styling.
- **Spring Physics**: All rotations and ring transitions use high-stiffness spring configurations (`stiffness: 120`, `damping: 14`) to ensure the wheel feels "weighted" and snappy.
- **Side Panel Connectivity**: 
  - Active nodes project a `ConnectionLine` (SVG Path) to the SidePanel.
  - The line uses a refined quadratic bezier curve for a "cabled" look.
  - **Interactivity**: Enabled via `pointerEvents: "auto"` for direct engagement.
  - **Centering**: Anchored to `top: 50%` for robust alignment with variable panel heights.

---

## 5. Technical Implementation Details
- **Component**: [DualRingMechanism.tsx](file:///c:/Users/midas/Desktop/dev/IRISVOICE/components/wheel-view/DualRingMechanism.tsx)
- **Container**: [WheelView.tsx](file:///c:/Users/midas/Desktop/dev/IRISVOICE/components/wheel-view/WheelView.tsx)
- **State Management**: Integrated via `NavigationContext` for level transitions (1 → 4).
- **Responsiveness**: Scaling is controlled via `orbSize` prop, allowing the widget to adapt from small icons to full-screen dashboards.

---

*Last Updated: 2026-02-24*

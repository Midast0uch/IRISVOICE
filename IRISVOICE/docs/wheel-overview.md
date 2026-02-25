# WheelView Architecture & Design Overview

This document provides a comprehensive breakdown of the **WheelView** component, a high-fidelity, interactive navigation and control interface designed for the IRISVOICE ecosystem. The design follows a data-driven, "Digital Energy" aesthetic, emphasizing depth, motion synchronization, and tactile feedback.

## 1. Visual Philosophy
The WheelView is built on an **Energy-First** architecture. 
- **Structural Elements** (Interactive Rings) are muted into slate-grey "mechanisms."
- **Energy Elements** (Kinetic Gliders, Glow Aura) utilize high-vibrancy brand colors to draw the eye to motion and status.
- **Topography** (White Labels) ensures razor-sharp legibility against complex background layers.

---

## 2. Layered SVG Stack (Bottom to Top)
The `DualRingMechanism` utilizes a strictly ordered SVG stack to achieve its layered depth effect. Moving background layers *inside* the SVG (Phase 101) ensures they sit correctly behind the machine rings but in front of the Voice Aura.

| Order | Component Name | Description | Sizing/Radius |
| :--- | :--- | :--- | :--- |
| 1 | **Wide-Field Voice Aura** | Expanded Radial Gradient covering the entire stage. | `r=orbSize*0.7`, `0.95 idle opacity` |
| 2 | **Dynamic Background Aura** | Soft edge softening layer for depth transition. | `r=orbSize*0.52`, `blur: 40px` |
| 3 | **Integrated BasePlate** | **Phase 101**: Industrial foundation plate (SVG Circle). | `r=147 (98%)`, `base-plate-gradient` |
| 4 | **Integrated DepthGroove** | **Phase 101**: Recessed industrial well (SVG Circle + Shadows). | `r=138 (92%)`, `blur: 4px` |
| 5 | **Bright Liquid Frame**| 5px Metallic ring with edge glow. | `r=outerRadius+30`, `stroke: 5px` |
| 6 | **Structural Counter-Beams**| **Phase 89**: 2 CCW beams rotating at Hyper-Flux speed. | `r=outerRadius+30`, `Hyper-Flux` |
| 7 | **Neon Edge Bloom** | High-vibrancy neon pulse at the structural boundary. | `r=outerRadius+32.5`, `blur: 8px` |
| 8 | **Orbital Ticks** | 12 reference points alternating between **White** and **Brand Color**. | `r=outerRadius+14` to `+23` |
| 9 | **Barrier Kinetic Glider**| A high-density, segmented frame sitting on the tips of the ticks. | `r=outerRadius+23`, `20s CW` |
| 10 | **Interactive Outer Ring** | Solid metallic ring with segment edge glows. | `r=orbSize*0.39`, `20s CW` |
| 11| **Mid-Ring Energy Beam** | **Phase 88/91**: 2 CCW beams rotating at Hyper-Flux speed. | `r=orbSize*0.33`, `Hyper-Flux` |
| 12| **Gap Kinetic Glider** | A mid-density, segmented frame sitting between the interactive rings. | `r=orbSize*0.33`, `15s CCW` |
| 13| **Interactive Inner Ring** | Solid metallic ring with segment edge glows. | `r=orbSize*0.27`, `15s CCW` |
| 14| **Core Energy Beam** | **Phase 89/91**: 1 CW beam rotating at Hyper-Flux speed. | `r=orbSize*0.185`, `Hyper-Flux` |
| 15| **Core Kinetic Glider** | A protective energy frame surrounding the central IrisOrb. | `r=orbSize*0.185`, `10s CW` |
| 16| **White Core Halo** | **Phase 87**: Double-layer glare hugging the button edge. | `r=orbSize*0.11`, `Static` |
| 17| **IrisOrb (Tactile Core)** | The primary control point and category label. | `diameter: 64px`, `zIndex: 100` |
| 18| **Connection Bridge** | High-intensity beam anchoring machine to panel. | `opacity: 0.9`, `gap: 25px` |

---

## 3. High-Intensity Energy Beams
These "Living Circuit" elements are the primary kinetic focal points. They utilize **Framer Motion** for rotation to ensure perfect centering and 60fps performance.

| Beam Location | Count | Direction | Radius | Duration | Animation Engine |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Structural Ring** | 2 | CCW (Counter) | `outerRadius + 30` | **6.0s** | Framer Motion |
| **Gap (Middle)** | 2 | CCW (Sync) | `orbSize * 0.33` | **3.5s** | Framer Motion |
| **Core (Inner)** | 1 | CW (Sync) | `orbSize * 0.185` | **4.0s** | Framer Motion |
| **Edge (Halo)** | - | Static | `orbSize * 0.11` | N/A | React State Pulse |

---

## 4. Lighting & Visual Design Specs

### Orbital Tick Alternation (Phase 94)
The 12 orbital ticks use a high-fidelity chromatic rhythm:
- **White Ticks** (Indices 0, 2, 4, 6, 8, 10): 
  - **Color**: `#FFFFFF`.
  - **Width**: `3.5px` (Bloom) / `2.2px` (Core).
  - **Effect**: Intense white bloom (3px blur) + White drop-shadow (5px).
- **Brand Ticks** (Indices 1, 3, 5, 7, 9, 11):
  - **Color**: `glowColor` (Brand).
  - **Width**: `2.5px` (Bloom) / `1.8px` (Core).
  - **Effect**: Soft industrial glow (2px blur).

### High-Intensity White Core Halo (Phase 87)
- **Location**: `r=orbSize*0.11` (Hugging the center button).
- **Dual-Layer Lighting**:
  - **Sharp Halo**: Concentrated white ring at the edge for definition.
  - **Soft Glare**: Outward-pulsing glare (12px blur) that expands/contracts to simulate a volumetric light source.

---

## 5. Interaction & Tactile Feedback
The interface is designed to feel physical despite its digital nature.

- **Tactile Center Button**: 
  - **Interaction**: Framer Motion `whileTap={{ scale: 0.88 }}`.
  - **Double-Click**: Starts the Voice Aura engine.
- **Side Panel Connectivity**: 
  - Active nodes project a `ConnectionLine` (SVG Path) to the SidePanel.
  - **Surgical Centering**: All components use Framer Motion `y: "-50%"` to ensure perfect eternal bisection.

---

## 6. Background Industrial Architecture (Modifying Colors)
To ensure absolute layering, the industrial base plate and depth effects are integrated directly into the SVG stack in `DualRingMechanism.tsx`.

### Modifying the Base Plate Color
1.  Locate [DualRingMechanism.tsx](file:///c:/Users/midas/Desktop/dev/IRISVOICE/components/wheel-view/DualRingMechanism.tsx).
2.  Search for the `<radialGradient id="base-plate-gradient">` tag inside the `<defs>` section.
3.  Adjust the hex codes in the gradient stops:
    - **Stop 1 (Center)**: The core color of the plate.
    - **Stop 2 (Edge)**: The shadow/outer color of the plate.
4.  The plate is rendered by a `<circle>` using `fill="url(#base-plate-gradient)"`.

### Modifying Atmospheric Glow
The `AmbientGlowLayer` (the soft atmospheric pulse behind everything) is still located in [WheelView.tsx](file:///c:/Users/midas/Desktop/dev/IRISVOICE/components/wheel-view/WheelView.tsx).
- Adjust the `radial-gradient` color and `blur` value for different environmental feels.

---

## 7. Technical Implementation Details
- **Component**: [DualRingMechanism.tsx](file:///c:/Users/midas/Desktop/dev/IRISVOICE/components/wheel-view/DualRingMechanism.tsx)
- **CSS Animations**: [globals.css](file:///c:/Users/midas/Desktop/dev/IRISVOICE/app/globals.css) (Standard ring rotations).
- **Performance**: High-intensity shimmers and beams use `will-change: transform` and `pathLength="1"` for browser-native optimization.

---

*Last Updated: 2026-02-25 (Phase 104)*

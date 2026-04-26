# Iris Orb Design & Layering Specs

This document specifies the finalized visual architecture of the **Iris Orb** as of Phase 113. The design follows a 6-layer "Liquid Metal & Prism Glass" stack, optimized for high-fidelity brand presence and kinetic energy.

## 1. Visual Stack (Bottom to Top)

| Layer | Component | Technical Specification | Visual Purpose |
| :--- | :--- | :--- | :--- |
| **0** | **Atmospheric Pulse** | `inset: -80`, `blur(50px)`, `Alpha 0.4-0.8` | Provides a massive, soft "breathing" aura of the brand color. |
| **1.1** | **Neon Core** | `inset: -4`, `border: 2px solid`, `blur(2px)` | Acts as the "hot gas" light source for the edge bloom. |
| **1.2** | **Shimmer Bloom** | `inset: -30`, `blur(20px)`, Rotating `conic spike` | Dynamic swirling light that "shimmers" off the orb's edge. |
| **2** | **Liquid Metal Ring** | Rotating `conic-gradient` (White/Steel/Brand) | Simulates flowing mercury with high-contrast specular glints. |
| **3** | **Glassmorphic Base** | `blur(12px)`, Brand Tint Gradient | The core body of the orb; tinted by the active theme. |
| **4** | **Convex Ridge** | Inverted Shadow (`box-shadow: 0 10px 30px`) | Transforms the center into a raised, voluminous glass dome. |
| **5** | **Content Layer** | Lucide Icons / Interactive Labels | The primary interaction point for navigation and state. |

## 2. Dynamic Refinements

### Liquid Metal (Mercury Flow)
The structural frame (Layer 2) no longer uses static silver. It utilizes a **rotating conic-gradient** (6s duration) that cycles through white specular highlights and deep steel shadows, creating the illusion of fluid movement.

### Kinetic Shimmering
Layer 1.2 features a secondary rotating layer with a `conic-gradient` light spike. This spike uses `mix-blend-mode: overlay` to catch the underlying neon and metal layers, creating a sophisticated "swirl" effect.

- **Haptics**: Instant scale-down to 0.92x on mouse-down for mechanical "press" feel.

### Phase 126: Interaction Recovery
- **Sensitivity**: Drag threshold tuned to 12px (prevents jitter skipping).
- **Control Flow**: 100% prop-driven navigation path.

### Phase 123: Voice Mode Overhaul
- **Color Shift**: `idle` (Theme) → `active` (#00f2ff Electric Cyan).
- **Expansion**: Scale 1.25x (Listening), 1.15x (Speaking).
- **Plasma Corona**: Layer 1.15; conic energy swirl (0.8s rotation) with energy-cyan blur.
- **Atmospheric Overdrive**: Inset -120; 1s pulse cycle; 1.0 opacity peak.

### Phase 113: Inverted Volume
The previous "inset groove" (carved-in) has been replaced with a **convex ridge** architecture. A white inner-glow at the top edge (`inset 0 2px 4px`) combined with a deep outer drop-shadow makes the central glass feel raised and 3D.

### Phase 121: Voice Control & Kinetic Pulses
- **Gestures**: Double-click starts engine (`voice_command_start`). Single-click stops engine (`voice_command_end`) if active.
- **Pulse - Listening**: Slow breathing on Layer 0 and Layer 1 (1.5s, scale 1.1x).
- **Pulse - Speaking**: Kinetic jitter on Layer 2 and Layer 5 (0.2s, subtle scale 1.03x).

## 4. Peripheral Alignment (Phase 115)

To maintain visual hierarchy, surrounding nodes (Hex nodes and Wheel segments) use a simplified version of the Iris Orb stack:
1. **Liquid Metal Frame**: Shared rotating mercury gradient for structural unity.
2. **Convex Ridge**: Shared "raised dome" lighting model.
3. **Exclusions**: Peripheral elements omit the **Layer 0 Atmospheric Pulse** and **Layer 1.2 Neon Shimmer** to prevent visual clutter and maintain focus on the central core.

### Static Structural Framing (Phase 117)
Surrounding nodes utilize **static structural framing**. All rotation animations have been arrested on peripheral metal rings and segments to ensure visual stability.

### Nested Prism Geometry
In peripheral orbs, internal separators are no longer circular. They replicate the **Prism Shape** (rounded rectangle) with a `1.6rem` border-radius, creating a perfectly aligned sub-container for icons and labels.

### Obsidian Glass Base (Phase 118)
Peripheral nodes no longer use backdrop blur. They feature an **Obsidian Base** (deep charcoal/black with 85% opacity), providing maximum contrast for the static internal metal rings. This removes atmospheric clutter and emphasizes the structural "nesting" design.

### Structural Nesting (Phase 120)
The internal **Nested Prism** rail has been reinforced:
- **Thickness**: 3px (increased from 2px).
- **Positioning**: 8px inset from outer perimeter.
- **Recessed Well**: Features an internal `inset shadow` with 0.8 opacity, creating a sharp 3D cavity for the icon/label.

---
*Last Updated: 2026-02-25 (Phase 113 Refinements)*

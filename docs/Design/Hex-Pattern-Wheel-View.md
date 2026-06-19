# Hex Pattern Wheel View — Design Document

> **Purpose:** Design rationale and architecture reference for the `HexPatternRingMechanism` component that replaces `DualRingMechanism.tsx` in the WheelView system.

**Date:** 2026-06-19
**Status:** Design complete, implementation plan at `docs/plans/2026-06-18-iris-orb-v2-spiral-dissolve-winner.md` (Tasks 21-25)
**Component name:** HexPatternRingMechanism
**Replaces:** `components/wheel-view/DualRingMechanism.tsx` (875 lines)
**Supersedes:** `docs/wheel-overview.md`

---

## Problem

The existing `DualRingMechanism.tsx` uses a **liquid metal** surface aesthetic for its interactive ring segments. While visually rich, it has drawbacks:

1. **Flat texture** — the smooth metal gradient lacks tactile depth. Segments look like polished chrome rather than engineered surfaces.
2. **No hex identity** — the IRISVOICE ecosystem uses hex nodes (HexNode component, hexagonal category menu) as its primary visual language. The wheel rings don't match.
3. **Heavy SVG filters** — the `liquid-metal-sheen` filter uses `feSpecularLighting` which is GPU-expensive and can cause frame drops on lower-end hardware.
4. **Weak selected state** — the only visual difference between selected and idle segments is a gradient swap. No edge glow, no texture change.

The Hex Pattern Surface variant solves these by:
- Overlaying a **honeycomb SVG pattern** on segment surfaces, giving the ring a textured hex feel
- Adding a **neon edge outline** that glows on selection (matching the hex node's active glow)
- Removing the expensive specular filter — the hex pattern provides visual interest without GPU-heavy filters
- Making the selected state unmistakable: pattern brightens (0.22 → 0.4 opacity) + neon edge appears with drop-shadow

---

## Design Exploration

We iterated through **4 ring surface variants** in `components/preview/WheelRingStyles.tsx`:

| Badge | Name | Description | Verdict |
|-------|------|-------------|---------|
| 1 | Glassmorphic Surface | Dark linear gradient with glow tint, inner shadow depth | Subtle but flat |
| **2** | **Hex Pattern Surface** | **Honeycomb SVG pattern overlay + neon edge outline** | **★ WINNER** |
| 3 | Neon Hex Surface | Neon-glass + hex pattern (most layered) | Too busy |
| 4 | Neon Glass Surface | Neon edge + glassmorphic base (no texture) | Good but no hex identity |

**Hex Pattern Surface won** because it:
- Matches the hex node aesthetic from the category menu
- Has clear selected vs idle states (pattern opacity + neon edge)
- Is lightweight (no specular filter, just a pattern fill + stroke)
- Looks engineered, not decorative

---

## Architecture

### Component Hierarchy

```
WheelView (container, 705 lines — unchanged)
  ├── AmbientGlowLayer (z-20, radial pulse)
  ├── BasePlateLayer (z-10, industrial foundation)
  ├── DepthGrooveLayer (z-0, recessed well)
  ├── HexPatternRingMechanism (NEW — replaces DualRingMechanism)
  │     └── SVG stack (see Layered SVG Stack below)
  ├── Voice Active Atmospheric Pulse (z-98)
  ├── Audio Level Visualization Rings (z-97)
  ├── Processing Spinner (z-96)
  ├── Error State Pulse (z-95)
  ├── Error Message Display (z-94)
  ├── Center Button (z-100, 5-layer core)
  │     ├── Atmospheric Brand Pulse
  │     ├── Neon Core + Edge Bloom
  │     ├── Liquid Metal Ring
  │     ├── Glassmorphic Base
  │     └── Content Area (category label)
  └── SidePanel (with ConnectionLine)
        ├── CollapsibleSection × N
        ├── Field renderers (Toggle, Slider, Dropdown, Text, Color)
        ├── ColorSliderGroup
        ├── LearnedSkillsPanel
        └── IntegrationListPanel
```

### Props Interface (identical to DualRingMechanism)

```ts
interface HexPatternRingMechanismProps {
  items: Card[]                    // Settings cards to distribute across rings
  selectedIndex: number            // Currently selected card index
  onSelect: (index: number) => void  // Segment click handler
  glowColor: string                // Brand/theme color (hex or hsl)
  basePlateColor?: string          // Base plate HSL color (default: hsl(220, 15%, 15%))
  orbSize: number                  // Orb diameter in px (typically 300)
  confirmSpinning?: boolean        // Confirm animation active
  isVoiceActive?: boolean          // Voice command active
  voiceIntensity?: number          // Audio level 0-1
}
```

### Use Cases (all preserved from DualRingMechanism)

| Use Case | How It Works |
|----------|-------------|
| **Browse settings** | Items split 50/50 across outer/inner rings. Click segment → spring rotation centers it at 12 o'clock. |
| **Edit fields** | Selected segment's card fields appear in SidePanel. ConnectionLine links orb to panel. |
| **Confirm changes** | Confirm button → `confirmSpinning` triggers counter-rotation animation → sends `confirm_card` WS message. |
| **Voice navigation** | `isVoiceActive` + `voiceIntensity` drive the voice aura pulse and audio level rings. |
| **Keyboard navigation** | Arrow keys cycle selection, Enter confirms, Escape goes back. |
| **Drag window** | `useManualDragWindow` on container allows repositioning the entire WheelView. |
| **Double-click voice** | Center button double-click toggles voice command (500ms window). |
| **Error feedback** | `voiceState === 'error'` shows red pulse + error message. |
| **Processing feedback** | `processing_conversation` / `processing_tool` shows orbital spinner. |

---

## Layered SVG Stack (Bottom to Top)

The `HexPatternRingMechanism` uses a strictly ordered SVG stack. Background layers sit inside the SVG (not as HTML divs) to ensure correct z-ordering behind the machine rings.

| Order | Component Name | Description | Sizing/Radius |
|:------|:---------------|:------------|:--------------|
| 1 | **Wide-Field Voice Aura** | Expanded radial gradient covering the entire stage. Pulses with `isVoiceActive`. | `r=orbSize*0.7`, `0.95 idle opacity` |
| 2 | **Dynamic Background Aura** | Soft edge softening layer for depth transition. | `r=orbSize*0.52`, `blur: 40px` |
| 3 | **Integrated BasePlate** | Industrial foundation plate (SVG Circle). | `r=orbSize*0.49`, `base-plate-gradient` |
| 4 | **Integrated DepthGroove** | Recessed industrial well (SVG Circle + shadows). | `r=orbSize*0.46`, `blur: 4px` |
| 5 | **Decorative Outer Frame** | 5px ring with edge glow at the structural boundary. | `r=outerRadius+30`, `stroke: 5px` |
| 6 | **Sharp Edge Glow** | High-intensity boundary line. | `r=outerRadius+32.5`, `stroke: 0.75px` |
| 7 | **Structural Counter-Beams** | 4 beams: 2 CCW + 2 CW counter-rotating pairs. | `r=outerRadius+30` and `+28` |
| 8 | **Barrier Kinetic Glider** | Framer-motion dashed ring, 8s CW (faster than ticks). | `r=outerRadius+23`, `strokeDasharray: 18.57 4` |
| 9 | **Orbital Ticks** | 12 dual-layer ticks (bloom + core), CSS `ring-outer-anim` 20s CW. | `r=outerRadius+18`, 12 count |
| 10 | **Outer Interactive Ring** | **Hex Pattern Surface** segments with spring rotation. | `r=orbSize*0.39`, `stroke: 28px` |
| 11 | **Gap Kinetic Glider** | CSS `ring-middle-anim` dashed ring + framer-motion CCW beam. | `r=orbSize*0.33`, `15s CCW` + `3.5s beam` |
| 12 | **Inner Interactive Ring** | **Hex Pattern Surface** segments with spring rotation. | `r=orbSize*0.2575`, `stroke: 22px` |
| 13 | **Core Kinetic Glider** | CSS `ring-inner-anim` dashed ring + framer-motion CW beam. | `r=orbSize*0.185`, `10s CW` + `4s beam` |
| 14 | **White Core Halo** | Double-layer glare hugging the center button edge. | `r=orbSize*0.11`, static + pulse |
| 15 | **Particle Chase Relay** | Dual particle "chase" synced to ENERGY_CYCLE. | `r=outerRadius+29`, ENERGY_CYCLE timing |
| 16 | **Structural Energy Circuit** | Rotating "power spark" ring. | `r=outerRadius+29` |

---

## Hex Pattern Surface — Segment Rendering

This is the **only difference** from DualRingMechanism. Each interactive segment (outer and inner ring) renders as:

### SVG Layers per Segment

```
┌─────────────────────────────────────────────┐
│  1. Glow Background                         │  ← blur(8px) when selected
│     stroke: hexToRgba(glowColor, 0.12)      │
│     strokeWidth: 28 (outer) / 22 (inner)    │
├─────────────────────────────────────────────┤
│  2. Base Metal Body                         │  ← hex-active / hex-idle gradient
│     stroke: url(#hex-active) or url(#hex-idle) │
│     strokeWidth: 28 (outer) / 22 (inner)    │
│     opacity: 0.95                           │
├─────────────────────────────────────────────┤
│  3. Hex Pattern Texture Overlay             │  ← honeycomb SVG pattern
│     stroke: url(#hex-pattern)               │
│     strokeWidth: 28 (outer) / 22 (inner)    │
│     opacity: 0.4 (selected) / 0.22 (idle)   │
├─────────────────────────────────────────────┤
│  4. Neon Edge Outline                       │  ← the bright line
│     stroke: glowColor (selected) / hexToRgba(glowColor, 0.2) (idle) │
│     strokeWidth: 1.5 (selected) / 0.75 (idle) │
│     filter: drop-shadow(0 0 6px) + drop-shadow(0 0 12px) when selected │
└─────────────────────────────────────────────┘
```

### SVG Defs

```xml
<defs>
  <!-- Active segment gradient -->
  <linearGradient id="hex-active" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stopColor={hexToRgba(glowColor, 0.25)} />
    <stop offset="50%" stopColor="rgba(10,10,12,0.7)" />
    <stop offset="100%" stopColor={hexToRgba(glowColor, 0.1)} />
  </linearGradient>

  <!-- Idle segment gradient -->
  <linearGradient id="hex-idle" x1="0%" y1="0%" x2="0%" y2="100%">
    <stop offset="0%" stopColor="rgba(30,32,40,0.5)" />
    <stop offset="100%" stopColor={hexToRgba(glowColor, 0.03)} />
  </linearGradient>

  <!-- Honeycomb pattern -->
  <pattern id="hex-pattern" x="0" y="0" width="8" height="9.24" patternUnits="userSpaceOnUse">
    <polygon
      points="4,0 8,2.31 8,6.93 4,9.24 0,6.93 0,2.31"
      fill="none"
      stroke={hexToRgba(glowColor, 0.4)}
      strokeWidth="0.4"
    />
  </pattern>
</defs>
```

### Comparison: Old vs New Segment

| Aspect | DualRingMechanism (liquid metal) | HexPatternRingMechanism (hex pattern) |
|--------|----------------------------------|---------------------------------------|
| Body fill | `url(#liquid-metal-gradient)` | `url(#hex-active)` / `url(#hex-idle)` |
| Surface texture | None | Honeycomb `<pattern>` overlay |
| Edge | 0.5px micro highlight | 1.5px neon edge with drop-shadow |
| Selected indicator | Gradient swap only | Pattern brightens + neon edge glows |
| SVG filter | `feSpecularLighting` (GPU-heavy) | None (pattern provides texture) |
| Idle opacity | 0.95 | 0.95 (body) + 0.22 (pattern) |
| Selected opacity | 0.95 | 0.95 (body) + 0.40 (pattern) |

---

## Kinetic Gliders & Energy Beams

All kinetic gliders and energy beams are **identical** to DualRingMechanism. They are the "Energy-First" elements that use high-vibrancy brand colors.

### Structural Ring Beams (4 beams — 2 CCW + 2 CW)

| Beam | Direction | Radius | Duration | Stroke | Opacity |
|------|-----------|--------|----------|--------|---------|
| CCW slower | Counter-clockwise | `outerRadius + 30` | 6.0s | 1.8 | 0.9 |
| CCW faster | Counter-clockwise | `outerRadius + 28` | 4.5s | 1.4 | 0.7 |
| CW slower | Clockwise | `outerRadius + 30` | 7.0s | 1.8 | 0.9 |
| CW faster | Clockwise | `outerRadius + 28` | 5.0s | 1.4 | 0.7 |

All beams use `pathLength={1}` with `strokeDasharray` for short arc segments. `transformOrigin` set to `${center}px ${center}px` for proper SVG rotation.

### Barrier Kinetic Glider

- **Radius**: `outerRadius + 23`
- **Animation**: Framer-motion, 8s CW (faster than orbital ticks)
- **Style**: White dashed ring, `strokeDasharray: 18.57 4`, opacity 0.6, drop-shadow glow
- **Gear effect**: Barrier moves faster than ticks, creating the visual impression of gear teeth moving off the tick marks

### Orbital Ticks (12 count)

- **Radius**: `outerRadius + 18` (tick span: -5 to +5)
- **Animation**: CSS `ring-outer-anim`, 20s CW (slower than barrier)
- **Alternation**: Even indices = white, odd indices = glowColor
- **Dual-layer**: Bloom layer (blur, low opacity) + Core layer (sharp, high opacity)

### Gap Kinetic Glider

- **Radius**: `(outerRadius + innerRadius) / 2` = `orbSize * 0.32375`
- **Dashed ring**: CSS `ring-middle-anim`, 15s CCW
- **Energy beam**: Framer-motion, 3.5s CCW, white, `strokeDasharray: 0.02 0.48`

### Core Kinetic Glider

- **Radius**: `orbSize * 0.185`
- **Dashed ring**: CSS `ring-inner-anim`, 10s CW
- **Energy beam**: Framer-motion, 4s CW, white, `strokeDasharray: 0.02 0.98`

### Core Halo

- **Radius**: `orbSize * 0.11`
- **Dual-layer**: Soft glare (12px blur, pulsing opacity 0.1→0.35→0.1, scale 1→1.1→1) + Sharp halo (2px stroke, static, drop-shadow)

### Particle Chase Relay

- **Radius**: `outerRadius + 29`
- **Two particles** (Alpha + Beta) chasing each other, synced to `ENERGY_CYCLE`
- **Alpha**: `strokeDashoffset: [0.75, -0.25]`, opacity flares during ENERGY_CYCLE segments
- **Beta**: `strokeDashoffset: [0.25, -0.75]`, opacity flares during ENERGY_CYCLE segments

---

## CSS Animations — CRITICAL: Local `<style jsx>` Override

**DualRingMechanism has a local `<style jsx>` block that OVERRIDES globals.css with 3x SLOWER rotation speeds.** This MUST be carried over to HexPatternRingMechanism verbatim. The preview (WheelRingStyles.tsx) uses globals.css (fast), but production uses the local block (slow).

| Class | globals.css (preview) | Local `<style jsx>` (production) |
|-------|----------------------|----------------------------------|
| `ring-outer-anim` | 20s CW | **60s CW** |
| `ring-middle-anim` | 15s CCW | **45s CCW** |
| `ring-inner-anim` | 10s CW | **30s CW** |

### Production `<style jsx>` block (MUST be included in HexPatternRingMechanism):

```jsx
<style jsx>{`
  .ring-outer-anim {
    animation: rotate-slow 60s linear infinite;
    transform-origin: center;
  }
  .ring-middle-anim {
    animation: rotate-slow 45s linear infinite reverse;
    transform-origin: center;
  }
  .ring-inner-anim {
    animation: rotate-slow 30s linear infinite;
    transform-origin: center;
  }
  @keyframes rotate-slow {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
`}</style>
```

**If you forget this block, the rings will spin 3x too fast in production.**

---

## Interaction & Tactile Feedback

### Segment Selection
- **Click**: `onSelect(index)` fires → parent updates `selectedIndex` → spring rotation centers the segment at 12 o'clock
- **Spring config**: `stiffness: 80, damping: 16` (smooth, not bouncy)
- **Visual feedback**: Segment's hex pattern brightens (0.22 → 0.4), neon edge outline appears with glow

### Confirm Animation
- **Trigger**: `confirmSpinning = true` from parent
- **Effect**: Outer ring rotates `+360°`, inner ring rotates `-360°` (counter-spin)
- **Duration**: 0.8s ease-in-out
- **After**: `onConfirm` callback fires with all field values

### Center Button — Core Halo Labeling

The center button (64px diameter, `zIndex: 100`) sits at the core of the wheel. It shows the **selected card's label** when a segment is clicked, falling back to the **category name** when no card is selected.

#### Label Logic

| State | What's Displayed | Example |
|-------|-----------------|---------|
| No segment selected | `categoryId` (category name) | "Voice" |
| Segment selected | `activeCard.label` (card display name) | "Microphone" |
| Segment deselected | Falls back to `categoryId` | "Voice" |

#### Animation

When the selected card changes, the label transitions with a **fade + scale** animation:

```tsx
<AnimatePresence mode="wait">
  <motion.span
    key={activeCard?.id ?? categoryId}  // re-mount triggers animation
    initial={{ opacity: 0, scale: 0.8 }}
    animate={{ opacity: 1, scale: 1 }}
    exit={{ opacity: 0, scale: 0.8 }}
    transition={{ duration: 0.3, ease: "easeOut" }}
  >
    {activeCard?.label ?? categoryId}
  </motion.span>
</AnimatePresence>
```

- **Duration**: 300ms
- **Easing**: easeOut
- **Mode**: `wait` — old label fully exits before new label enters
- **Key**: `activeCard?.id ?? categoryId` — ensures re-mount on card change

#### Center Button Stack (5 layers, unchanged except content area)

| Layer | Description | z-index |
|-------|-------------|---------|
| 1 | Atmospheric Brand Pulse (radial gradient) | 1 |
| 2 | Neon Core + Edge Bloom (glowColor) | 2 |
| 3 | Liquid Metal Ring (gradient border) | 3 |
| 4 | Glassmorphic Base (backdrop blur) | 4 |
| 5 | **Content Area** (card label / categoryId) | 10 |

#### Center Button Interactions

- **Single click** (500ms window): If voice active → cancel voice. Otherwise → `onBackToCategories()`
- **Double click**: Toggle voice command (`startVoiceCommand` / `endVoiceCommand`)
- **Tactile**: `whileTap={{ scale: 0.94 }}`, `whileHover={{ scale: 1.05 }}`
- **Voice reactive**: Scale modulates with `audioLevel`, boxShadow grows with voice intensity

### Keyboard Navigation
- **Arrow Right/Down**: Next segment
- **Arrow Left/Up**: Previous segment
- **Enter**: Confirm
- **Escape**: Back to categories

---

## SidePanel Integration

The SidePanel is **unchanged** — it connects to the same `activeCard` and renders the same field types:

| Field Type | Component | Use Case |
|------------|-----------|----------|
| Toggle | `ToggleField` | Boolean settings (enable/disable) |
| Slider | `SliderField` | Numeric ranges (temperature, speed) |
| Dropdown | `DropdownField` | Enumerated options (model provider, language) |
| Text | `TextField` | String input (API key, wake word) |
| Color | `ColorField` + `ColorSliderGroup` | HSL color picker (brand color, base plate) |

### ConnectionLine — Hex Pattern Aesthetic Update

The connection bridge between the orb and SidePanel is updated to match the hex pattern surface aesthetic. The current 4-layer beam gains a 5th layer: hex pattern texture overlay.

#### Current Layers (unchanged):

| # | Layer | Description | Style |
|---|-------|-------------|-------|
| 1 | Brand Color Saturation | Backlight glow | `glowColor`, blur 2px, opacity 0.7 |
| 2 | Neon Edge Bloom | Atmospheric haze | `glowColor`, blur 4px, opacity 0.6 |
| 3 | Main Energy Beam | Gradient conduit | `url(#line-base-gradient)`, drop-shadow, opacity 0.15 |
| 4 | Base Conduit | Perpetual beam | `glowColor`, drop-shadow 15px + 5px white, opacity 0.95 |

#### New Layer 5 — Hex Pattern Texture Overlay:

```tsx
// <defs> addition:
<pattern id="line-hex-pattern" x="0" y="0" width="8" height="9.24" patternUnits="userSpaceOnUse">
  <polygon
    points="4,0 8,2.31 8,6.93 4,9.24 0,6.93 0,2.31"
    fill="none"
    stroke={hexToRgba(glowColor, 0.4)}
    strokeWidth="0.4"
  />
</pattern>

// 5th layer (after base conduit):
<line
  x1="0" y1={containerHeight / 2} x2={lineWidth} y2={containerHeight / 2}
  stroke="url(#line-hex-pattern)"
  strokeWidth={lineHeight * 1.5}
  strokeLinecap="round"
  style={{ opacity: 0.3 }}
/>
```

#### Neon Edge Update (Layer 2):

The neon edge bloom filter is updated to match the hex pattern segment's neon edge style:

```tsx
// Old: filter="url(#line-glow-blur-hot)"
// New: matches hex pattern segment neon edge
style={{
  filter: `drop-shadow(0 0 6px ${glowColor}) drop-shadow(0 0 12px ${glowColor})`,
  opacity: 0.6
}}
```

#### Dimensions (unchanged):

- **Start X**: 487px (anchored to structural ring edge: 40px padding + 300px center + 147px outerRadius+30)
- **Line width**: `panelOffset - startX` (typically 523 - 487 = 36px)
- **Line height**: 3.2px (kinetic-level visibility)
- **Container height**: 60px (safety gutter for blooms)
- **Spring**: `stiffness: 140, damping: 22` for extension/retraction

#### SidePanel Power Intake Energy Border:

The SidePanel's border particle animation (lines 651-698 in SidePanel.tsx) already uses `glowColor` and `ENERGY_CYCLE` — it automatically matches the hex pattern aesthetic since it uses the same brand color. No changes needed to SidePanel.tsx.

---

## Technical Implementation Details

- **Component**: `components/wheel-view/HexPatternRingMechanism.tsx`
- **Parent**: `components/wheel-view/WheelView.tsx` (unchanged except import swap + core halo labeling)
- **CSS Animations**: Local `<style jsx>` block (60s/45s/30s — see above)
- **Performance**: `will-change: transform` and `pathLength="1"` for browser-native optimization on all rotating elements
- **SSR safety**: `polarToCartesian` rounds to 2 decimal places to prevent hydration mismatch
- **ENERGY_CYCLE**: Imported from `@/lib/timing-config` for particle chase relay synchronization

### Critical Functions to Carry Over Verbatim

#### `hexToRgba` (handles both hex AND hsl color formats)

```ts
function hexToRgba(color: string, alpha: number): string {
  if (color.startsWith('hsl')) {
    return color.replace('hsl(', 'hsla(').replace(')', `, ${alpha})`)
  }
  const r = parseInt(color.slice(1, 3), 16)
  const g = parseInt(color.slice(3, 5), 16)
  const b = parseInt(color.slice(5, 7), 16)
  return `rgba(${r},${g},${b},${alpha})`
}
```

#### `polarToCartesian` (rounds to 2 decimals for SSR safety)

```ts
function polarToCartesian(cx: number, cy: number, r: number, angleDeg: number) {
  const angleRad = (angleDeg - 90) * Math.PI / 180
  return {
    x: Math.round((cx + r * Math.cos(angleRad)) * 100) / 100,
    y: Math.round((cy + r * Math.sin(angleRad)) * 100) / 100
  }
}
```

#### `generateArcPath` (SVG arc path for ring segments)

```ts
function generateArcPath(cx: number, cy: number, r: number, startAngle: number, endAngle: number) {
  const start = polarToCartesian(cx, cy, r, endAngle)
  const end = polarToCartesian(cx, cy, r, startAngle)
  const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1"
  return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArcFlag} 0 ${end.x} ${end.y}`
}
```

#### `renderSegmentText` (text along arc path)

Renders uppercase labels along each segment's arc using `<textPath>`. Font sizes: 11px outer ring, 9.5px inner ring. Text is centered along the arc with `startOffset="50%"` and `textAnchor="middle"`.

### Ring Distribution & Rotation

#### Split Logic

```ts
const splitPoint = Math.ceil(items.length / 2)
const outerItems = items.slice(0, splitPoint)
const innerItems = items.slice(splitPoint)
```

#### Spring Rotation (centers selected segment at 12 o'clock)

```ts
const segmentAngle = 360 / items.length
// Outer ring: rotate so selected segment is at top
const outerRotation = -(selectedIndex * segmentAngle) - segmentAngle / 2
// Inner ring: adjust for split offset
const innerRotation = -((selectedIndex - splitPoint) * segmentAngle) - segmentAngle / 2

// Spring config
{ type: "spring", stiffness: 80, damping: 16 }
```

#### Confirm Spin (counter-rotation)

When `confirmSpinning` is true:
- Outer ring: `outerRotation + 360` (clockwise spin)
- Inner ring: `innerRotation - 360` (counter-clockwise spin)
- Duration: 0.8s ease-in-out

### Voice Aura

Dynamic background aura that pulses with `isVoiceActive` and `voiceIntensity`:

- **Wide-Field Voice Aura**: `r=orbSize*0.7`, radial gradient, opacity 0.95 idle → pulses with voiceIntensity
- **Dynamic Background Aura**: `r=orbSize*0.52`, blur 40px, softens depth transition
- When `isVoiceActive`: aura opacity modulates with `voiceIntensity` (0-1)
- When idle: aura at resting opacity

### Base Plate

Industrial foundation layers using `basePlateColor` prop:

- **BasePlate**: `r=orbSize*0.49`, `fill="url(#base-plate-gradient)"`, gradient uses `basePlateColor`
- **DepthGroove**: `r=orbSize*0.46`, recessed shadow effect, `blur: 4px`

### `originX`/`originY` → `transformOrigin` Fix

The original DualRingMechanism uses `originX: "50%"` and `originY: "50%"` inside the `style` object for framer-motion rotation. However, this can cause React warnings in some versions. The HexPatternRingMechanism should use `transformOrigin: "${center}px ${center}px"` instead, which is more reliable:

```tsx
// Old (DualRingMechanism):
style={{ originX: "50%", originY: "50%" }}

// New (HexPatternRingMechanism):
style={{ transformOrigin: `${center}px ${center}px` }}
```

---

## Migration Path

1. **Task 21**: Create `HexPatternRingMechanism.tsx` (copy DualRingMechanism, swap segment rendering)
2. **Task 22**: Wire into `WheelView.tsx` (1:1 import swap, identical props)
3. **Task 23**: Delete `DualRingMechanism.tsx`, redirect `wheel-overview.md`
4. **Task 24**: Add preview to `orb-preview` page
5. **Task 25**: End-to-end verification

Each step is a separate commit. If any step breaks the build, `git revert` that commit.

---

## File Inventory

| File | Status | Purpose |
|------|--------|---------|
| `components/wheel-view/HexPatternRingMechanism.tsx` | **NEW** | Production ring mechanism with hex pattern surface |
| `components/wheel-view/WheelView.tsx` | **MODIFIED** | Import swap (DualRingMechanism → HexPatternRingMechanism) |
| `components/wheel-view/ConnectionLine.tsx` | **MODIFIED** | Hex pattern texture overlay + neon edge matching ring segments |
| `components/wheel-view/DualRingMechanism.tsx` | **DELETED** | Replaced by HexPatternRingMechanism |
| `components/wheel-view/SidePanel.tsx` | Unchanged | Field panel (uses glowColor — auto-matches) |
| `components/wheel-view/ConnectionLine.tsx` | Unchanged | Animated connection line |
| `components/wheel-view/CollapsibleSection.tsx` | Unchanged | Reusable collapsible UI |
| `components/wheel-view/ColorSliderGroup.tsx` | Unchanged | HSL color picker sliders |
| `components/wheel-view/LearnedSkillsPanel.tsx` | Unchanged | Skills display panel |
| `components/wheel-view/WheelViewErrorBoundary.tsx` | Unchanged | Error boundary |
| `components/wheel-view/fields/` | Unchanged | Field type components |
| `components/preview/WheelRingStyles.tsx` | Unchanged | Preview mockups (keeps its own copy) |
| `docs/wheel-overview.md` | **MODIFIED** | Redirect to this design doc |
| `docs/Design/Hex-Pattern-Wheel-View.md` | **NEW** | This document |

---

*Last Updated: 2026-06-19*

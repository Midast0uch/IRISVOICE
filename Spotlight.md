```markdown
# IRIS Wings Spotlight Mode Design Spec

## Window Context
- Tauri window: 680x680 pixels
- ChatWing: 255px width, 50vh height, left: 3%, rotateY: 15deg
- DashboardWing: 280px width, 50vh height, right: 3%, rotateY: -15deg

---

## Core Concept: Spotlight Mode

Three visual states controlled by maximize button in each wing header:

| State | ChatWing | DashboardWing | Orb |
|-------|----------|---------------|-----|
| **Balanced** | 255px, 15deg tilt, full opacity | 280px, -15deg tilt, full opacity | 85% scale, blur 2px, 60% opacity |
| **Chat-focused** | 340px, 0deg flat, full opacity, left: 5% | 180px, -15deg tilt, 30% opacity, desaturated | 70% scale, blur 3px, 40% opacity |
| **Dashboard-focused** | 180px, 15deg tilt, 30% opacity, desaturated | 360px, 0deg flat, full opacity, right: 5% | 70% scale, blur 3px, 40% opacity |

---

## Spatial Math (680px window)

### Balanced Mode
- Chat: 255px + 3% margin (~20px) = ~275px from left edge
- Gap: ~130px for Orb visibility
- Dashboard: 280px + 3% margin = ~300px from right edge
- Orb centered in remaining space

### Chat-focused
- Chat expands to 340px (85px gain), moves to 5% margin (~34px)
- Gap shrinks to ~100px, Orb scales down to compensate
- Dashboard shrinks to 180px, fades to background accent

### Dashboard-focused
- Dashboard expands to 360px (80px gain), moves to 5% margin
- Mirror of chat-focused state

---

## Visual Treatment by State

### Focused Wing Enhancements
- Remove 3D tilt (rotateY: 0deg)
- Expand width within 680px constraint
- Intensified edge glow facing Orb
- Increased shadow depth for elevation
- Slight content scale (1.02) for presence
- Border luminosity increases 15% → 25%

### Background Wing Treatment
- Maintain original tilt (preserves spatial context)
- Reduce width to 180px (compact but visible)
- Opacity: 30% (peripheral awareness)
- Saturation: 60% (removes color intensity)
- Blur: 2px (softens detail)
- Pointer events disabled (no accidental interaction)
- No internal state changes (live preview only)

### Orb Behavior
- **Balanced**: 85% scale, 2px blur, 60% opacity, decorative
- **Focused modes**: 70% scale, 3px blur, 40% opacity, functional escape target
- Click restores balanced mode
- Visual hint appears: "Click to restore" text below

---

## Interaction Model

### Entering Focused Mode
- User clicks maximize button in either wing header
- Active wing expands and flattens over 400ms spring animation
- Inactive wing shrinks and fades simultaneously
- Orb retreats and blurs to create depth hierarchy
- Maximize icon changes to restore icon

### Exiting Focused Mode
- **Method 1**: Click restore button on focused wing
- **Method 2**: Click Orb (anywhere on Orb surface)
- **Method 3**: Press Escape key
- All wings return to balanced positions
- Orb returns to 85% scale with 2px blur

### Notification Handling
- Notification bell remains active in focused wing header
- Notification dropdown opens over focused content
- Background wing notifications suppressed (non-interactive)

---

## Header Icon Order

### ChatWing (left to right)
Pulse indicator → Title → Maximize/Restore → History → Notifications → Dashboard → Close

### DashboardWing (left to right)
Pulse indicator → Title → Maximize/Restore → Notifications → Close

---

## Animation Specifications

**Timing**: 400ms duration
**Easing**: Spring physics (stiffness: 200, damping: 25, mass: 0.8)
**Properties animated**:
- Width (smooth expansion/contraction)
- RotateY (tilt to flat transition)
- Left/Right positioning (margin adjustment)
- Opacity (fade to background)
- Filter blur and saturation
- Scale (Orb retreat)
- Box-shadow intensity (glow enhancement)

---

## Edge Glow Specifications

### ChatWing (glows on right edge, facing Orb)
- **Balanced**: `inset -8px 0 24px rgba(glowColor, 0.12)`
- **Focused**: `inset -8px 0 32px rgba(glowColor, 0.20), 0 0 60px rgba(glowColor, 0.15)`
- **Background**: `inset -8px 0 16px rgba(0,0,0,0.2)` (dimmed)

### DashboardWing (glows on left edge, facing Orb)
- **Balanced**: `inset 8px 0 24px rgba(glowColor, 0.12)`
- **Focused**: `inset 8px 0 32px rgba(glowColor, 0.20), 0 0 60px rgba(glowColor, 0.15)`
- **Background**: `inset 8px 0 16px rgba(0,0,0,0.2)` (dimmed)

---

## Content Adaptation

### ChatWing (340px focused)
- Message bubbles expand to 90% width (was 85%)
- Input field lengthens proportionally
- Send button maintains position
- History dropdown widens to match container
- Increased horizontal padding (16px → 20px)

### DashboardWing (360px focused)
- Category tabs spread wider (5+More comfortable)
- Field labels gain breathing room
- Control inputs expand (140px → 180px max)
- Section headers full-bleed with gradient accent
- Confirm button spans full width with enhanced glow

---

## Constraints & Safeguards

- **Minimum gap**: 80px between wing edges (prevents overlap)
- **Maximum expansion**: 360px (leaves 80px+ for Orb visibility)
- **Background wing minimum**: 180px (recognizable but subdued)
- **Orb minimum scale**: 70% (never disappears completely)
- **Z-index**: Focused wing z-20, Orb z-10, Background wing z-5

---

## Accessibility

- Focused wing maintains full contrast and interaction
- Background wing visually distinct but not invisible
- Orb always clickable as escape hatch
- Keyboard Escape always restores balance
- Screen reader: announce "maximized" / "restored" state changes

---

## Success Criteria

- [ ] Maximize button present in both wing headers
- [ ] Clicking maximize expands active wing to flat 0deg position
- [ ] Background wing fades to 30% with maintained tilt
- [ ] Orb remains visible and clickable in all states
- [ ] Clicking Orb restores balanced mode
- [ ] Escape key restores balanced mode
- [ ] Smooth spring transitions between all states
- [ ] No content clipping or layout breakage at 680px window size
- [ ] Notification system functional in focused mode
- [ ] Visual hierarchy clearly communicates active/background state
```
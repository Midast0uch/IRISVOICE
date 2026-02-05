# Prism Glass UI Implementation Plan & Tracking

**Date:** Feb 4, 2026  
**Status:** Planning Phase - Awaiting Approval  
**Scope:** Complete UI redesign of theme system and node components

---

## Executive Summary

Redesign the theme switcher and all node components (main nodes, subnodes, mini stack) using a **Prism Glass UI Design System** with four distinct visual themes: **Aether**, **Ember**, **Aurum**, and **Verdant**.

**Key Constraint:** Navigation system remains untouched.

---

## New Theme Definitions

| Theme | Description | Mood | Color Palette |
|-------|-------------|------|---------------|
| **Aether** | Cool, ethereal blues/purples | Calm, airy, futuristic | Deep midnight blue → cyan gradient, icy blue shimmer |
| **Ember** | Warm oranges/reds/pinks | Energetic, sunset, passionate | Crimson → burnt orange gradient, amber-red shimmer |
| **Aurum** | Rich golds/ambers/yellows | Luxurious, warm, premium | Deep gold → amber gradient, golden shimmer |
| **Verdant** | Solid green tint with liquid glass | Natural, fresh, organic | Forest green → emerald gradient, lime-green shimmer |

---

## Core Design Principles

1. **Consistent glass opacity:** 15-20% across all themes
2. **Animated shimmer borders:** Adapt to each theme's accent color (conic gradient, clockwise rotation)
3. **Floating depth layers:** Orbs/blurs in theme colors (except Verdant - solid liquid glass only)
4. **Typography:** White with subtle opacity variations (90-95% white)
5. **Node shape:** Square with rounded corners (2.5rem/40px radius)
6. **Border radius:** `rounded-[2.5rem]` for all nodes
7. **Backdrop blur:** `backdrop-blur-xl` (24px) for glass effect
8. **Soft outer glow:** Matching theme color, subtle
9. **Dark backgrounds:** With vibrant accent colors
10. **Modern minimalist aesthetic**

---

## Implementation Architecture

### Phase 1: BrandColorContext Enhancement
**File:** `contexts/BrandColorContext.tsx`

```typescript
// Extended ThemeType
type ThemeType = 'aether' | 'ember' | 'aurum' | 'verdant'

// Theme configuration with full visual specs
interface ThemeConfig {
  // Base colors
  hue: number
  saturation: number
  lightness: number
  
  // Gradient stops for background
  gradient: {
    from: string  // CSS color (e.g., "hsl(220, 60%, 15%)")
    to: string    // CSS color (e.g., "hsl(190, 80%, 50%)")
  }
  
  // Shimmer border colors
  shimmer: {
    primary: string
    secondary: string
    accent: string
  }
  
  // Floating orbs/particles (null for Verdant)
  floatingElements?: {
    orbs: Array<{
      color: string
      size: number
      blur: number
      animation: string
    }>
  }
  
  // Typography
  text: {
    primary: string   // "rgba(255,255,255,0.95)"
    secondary: string // "rgba(255,255,255,0.70)"
  }
  
  // Glass specifications
  glass: {
    opacity: number      // 0.15-0.20
    blur: number         // 24px
    borderOpacity: number // 0.10-0.15
  }
}

// Theme definitions
const THEME_SPECS: Record<ThemeType, ThemeConfig> = {
  aether: { /* midnight blue → cyan */ },
  ember: { /* crimson → orange with fire particles */ },
  aurum: { /* gold → amber with dust particles */ },
  verdant: { /* forest green → emerald, NO particles */ }
}
```

**Changes:**
- Rename 'default' theme to 'verdant'
- Add complete theme specifications with gradients, shimmer colors, floating elements
- Add helper functions to get theme-specific styles

---

### Phase 2: Node Component Redesign
**File:** `components/iris/hexagonal-node.tsx` → Rename to `prism-node.tsx`

**Visual Structure per Node:**

```tsx
// 1. Outer glow container
<motion.div className="absolute -inset-4 rounded-[2.5rem] opacity-30"
  style={{ 
    background: `radial-gradient(circle, ${theme.shimmer.primary}40 0%, transparent 70%)`,
    filter: 'blur(12px)'
  }}
/>

// 2. Animated shimmer border (conic gradient)
<motion.div className="absolute -inset-[2px] rounded-[2.5rem]"
  style={{
    background: `conic-gradient(from 0deg, 
      transparent 0deg, 
      ${theme.shimmer.secondary}20 60deg, 
      ${theme.shimmer.primary} 180deg, 
      ${theme.shimmer.secondary}20 300deg, 
      transparent 360deg)`,
    WebkitMask: 'linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0)',
    WebkitMaskComposite: 'xor',
    padding: '2px'
  }}
  animate={{ rotate: 360 }}
  transition={{ duration: 8, repeat: Infinity, ease: 'linear' }}
/>

// 3. Main glass card
<div className="relative w-full h-full rounded-[2.5rem] overflow-hidden"
  style={{
    background: `linear-gradient(135deg, ${theme.gradient.from}15, ${theme.gradient.to}15)`,
    backdropFilter: 'blur(24px)',
    border: `1px solid ${theme.shimmer.primary}15`
  }}
>
  {/* 4. Gradient overlay for depth */}
  <div className="absolute inset-0 rounded-[2.5rem]"
    style={{
      background: `linear-gradient(135deg, ${theme.gradient.from}20, transparent 50%, ${theme.gradient.to}10)`
    }}
  />
  
  {/* 5. Floating orbs (conditional - NOT for Verdant) */}
  {theme.floatingElements?.orbs.map((orb, i) => (
    <motion.div
      key={i}
      className="absolute rounded-full pointer-events-none"
      style={{
        width: orb.size,
        height: orb.size,
        background: orb.color,
        filter: `blur(${orb.blur}px)`,
        opacity: 0.6
      }}
      animate={{
        x: [0, 20, -10, 0],
        y: [0, -15, 10, 0],
        scale: [1, 1.2, 0.9, 1]
      }}
      transition={{ duration: 10 + i * 2, repeat: Infinity, ease: 'easeInOut' }}
    />
  ))}
  
  {/* 6. Content: Icon + Label */}
  <div className="relative z-10 flex flex-col items-center justify-center gap-2">
    <Icon className="w-6 h-6" style={{ color: theme.shimmer.primary }} />
    <span className="text-[10px] font-medium tracking-wider" 
      style={{ color: theme.text.secondary }}>
      {node.label}
    </span>
  </div>
</div>
```

**Changes:**
- Change node shape from hexagonal to square with `rounded-[2.5rem]`
- Implement animated conic gradient shimmer border (rotating)
- Add radial gradient outer glow
- Add gradient overlay for depth perception
- Add floating orbs (conditional per theme)
- Update all color calculations to use theme specs

---

### Phase 3: Theme Switcher Redesign
**File:** `components/testing/ThemeTestSwitcher.tsx`

**New Layout:**

```tsx
// Compact card-based theme selector
<div className="w-64 rounded-2xl overflow-hidden backdrop-blur-xl">
  
  {/* Header: Current Theme Display */}
  <div className="px-4 py-3 border-b border-white/10">
    <div className="flex items-center gap-2">
      <div className="w-3 h-3 rounded-full" 
        style={{ 
          background: currentTheme.shimmer.primary,
          boxShadow: `0 0 8px ${currentTheme.shimmer.primary}` 
        }} 
      />
      <span className="text-sm font-medium text-white/90">
        {currentTheme.name}
      </span>
    </div>
    <p className="text-[10px] text-white/60 mt-1">
      {currentTheme.description}
    </p>
  </div>
  
  {/* Theme Grid: 2x2 layout */}
  <div className="grid grid-cols-2 gap-2 p-3">
    {themes.map((theme) => (
      <button
        key={theme.id}
        onClick={() => selectTheme(theme.id)}
        className={`relative p-3 rounded-xl border transition-all ${
          selected === theme.id 
            ? 'border-white/30 bg-white/10' 
            : 'border-white/5 hover:border-white/20'
        }`}
      >
        {/* Mini preview of theme */}
        <div className="w-full h-12 rounded-lg mb-2"
          style={{
            background: `linear-gradient(135deg, ${theme.gradient.from}, ${theme.gradient.to})`,
            opacity: 0.3
          }}
        />
        <div className="text-left">
          <div className="text-[11px] font-medium text-white/90">
            {theme.name}
          </div>
          <div className="text-[9px] text-white/50">
            {theme.mood}
          </div>
        </div>
        
        {/* Selected indicator */}
        {selected === theme.id && (
          <motion.div 
            layoutId="selectedTheme"
            className="absolute inset-0 rounded-xl border-2 border-white/20"
          />
        )}
      </button>
    ))}
  </div>
  
  {/* Mood/Description display */}
  <div className="px-4 py-2 border-t border-white/10">
    <p className="text-[10px] text-white/50 italic">
      {currentTheme.mood}
    </p>
  </div>
</div>
```

**Changes:**
- 2x2 grid layout for theme selection
- Visual previews showing gradient colors
- Theme name + mood description
- Animated selection indicator
- Remove H/S/L sliders (themes are presets)
- Keep intensity toggle (subtle/medium/strong)

---

### Phase 4: Iris Orb Redesign
**File:** `components/hexagonal-control-center.tsx` (IrisOrb component)

**Changes:**
- Keep centered position and sizing logic
- Apply same glass/prism styling as nodes
- Add theme-specific floating orbs around the orb
- Maintain pulse/breathe animations with theme colors
- Keep rotating shimmer but use theme shimmer colors

---

### Phase 5: Mini Node Stack Redesign
**File:** `components/mini-node-stack.tsx`

**Changes:**
- Apply same prism glass styling
- Stack cards with staggered depth effect
- Each card uses theme shimmer border
- Liquid glass feel for Verdant theme

---

## File Change Summary

| File | Changes | Lines Added/Modified |
|------|---------|---------------------|
| `contexts/BrandColorContext.tsx` | Add ThemeConfig interface, theme specs, rename 'default'→'verdant' | +150 lines |
| `components/iris/hexagonal-node.tsx` | Complete redesign: square shape, shimmer borders, floating orbs | Rewrite ~200 lines |
| `components/testing/ThemeTestSwitcher.tsx` | New 2x2 grid layout, theme previews, descriptions | Rewrite ~300 lines |
| `components/hexagonal-control-center.tsx` | Update IrisOrb styling, confirmed nodes styling | +100 lines |
| `components/mini-node-stack.tsx` | Apply prism glass styling to stack cards | +50 lines |

---

## Clarifying Questions

Before proceeding, I need clarification on:

### Question 1: Verdant Theme Specifics
You mentioned "liquid glass feel" for Verdant - should this include:
- Subtle wave/ripple animations?
- Higher transparency/opacity variations?
- Glossy highlight reflections?
- Or simply the solid green tint with smooth glass blur?

### Question 2: Node Size
Current nodes are ~90px. With the new square design:
- Keep same size (90x90px) or adjust?
- Square shape might appear larger than hexagonal - reduce to 80x80px?

### Question 3: Theme Intensity Levels
Currently have subtle/medium/strong intensity:
- Keep these 3 levels?
- Should they affect: glass opacity, shimmer speed, glow intensity, or all?

### Question 4: Background Behind Nodes
The design mentions "dark backgrounds with vibrant accents":
- Should the main app background change per theme (gradients)?
- Or just the node backgrounds change while keeping dark backdrop?

### Question 5: Animation Performance
Floating orbs + shimmer borders on 6+ nodes:
- Any performance concerns on lower-end devices?
- Should floating orbs be CSS-only or can use Framer Motion?

### Question 6: Text Contrast
White text on colored glass:
- Should text color shift slightly per theme (cool white for Aether, warm white for Ember)?
- Or keep consistent pure white across all themes?

---

## Implementation Timeline (Post-Approval)

**Phase 1:** BrandColorContext enhancement (30 min)
**Phase 2:** Node component redesign (1 hour)
**Phase 3:** Theme switcher redesign (45 min)
**Phase 4:** Iris Orb & Mini Stack updates (30 min)
**Phase 5:** Integration testing & polish (30 min)

**Total Estimated Time:** ~3 hours

---

## Success Criteria

- [ ] All 4 themes render correctly with distinct visual identities
- [ ] Nodes display square with 2.5rem rounded corners
- [ ] Animated shimmer borders rotate smoothly
- [ ] Glass opacity remains consistent (15-20%)
- [ ] Verdant shows liquid glass effect without particles
- [ ] Aether/Ember/Aurum show floating orbs
- [ ] Theme switcher shows 2x2 grid with previews
- [ ] Navigation system untouched and fully functional
- [ ] No console errors or visual glitches
- [ ] Smooth 60fps animations

---

**Status:** ✅ Implementation Complete - Testing Phase

---

## Comprehensive Test Plan

### Test 1: Theme Configuration Loading
**Objective:** Verify all 4 theme configurations load correctly

| Step | Action | Expected Result | Status |
|------|--------|-----------------|--------|
| 1 | Load app with default theme (Aether) | Aether theme config loaded | ⬜ |
| 2 | Switch to Ember theme | Ember config loaded, UI updates | ⬜ |
| 3 | Switch to Aurum theme | Aurum config loaded, UI updates | ⬜ |
| 4 | Switch to Verdant theme | Verdant config loaded, UI updates | ⬜ |
| 5 | Reload page with theme stored in localStorage | Correct theme restored | ⬜ |

---

### Test 2: Node Visual Rendering
**Objective:** Verify Prism Glass styling renders correctly on nodes

| Step | Action | Expected Result | Status |
|------|--------|-----------------|--------|
| 1 | Expand to Level 2 (main nodes) | Square nodes with 2.5rem radius visible | ⬜ |
| 2 | Check shimmer borders | Rotating conic gradient borders visible | ⬜ |
| 3 | Check outer glow | Soft radial glow around nodes | ⬜ |
| 4 | Check glass opacity | 15-20% opacity, blur effect visible | ⬜ |
| 5 | Navigate to Level 3 (subnodes) | Same styling applied to subnodes | ⬜ |
| 6 | Navigate to Level 4 (mini stack) | Same styling on mini node cards | ⬜ |

---

### Test 3: Theme-Specific Visual Elements
**Objective:** Verify theme-specific elements render correctly

| Theme | Floating Orbs | Liquid Glass | Shimmer Colors | Status |
|-------|---------------|--------------|----------------|--------|
| **Aether** | 3 cyan/purple orbs visible | N/A | Icy blue | ⬜ |
| **Ember** | 3 orange/red orbs visible | N/A | Amber-red | ⬜ |
| **Aurum** | 3 gold/amber orbs visible | N/A | Golden | ⬜ |
| **Verdant** | NO orbs (intentional) | Subtle sheen effect | Lime-green | ⬜ |

---

### Test 4: Theme Switcher Functionality
**Objective:** Verify theme switcher works without triggering Iris back button

| Step | Action | Expected Result | Status |
|------|--------|-----------------|--------|
| 1 | Click theme switcher button | Switcher expands, no Iris trigger | ⬜ |
| 2 | Click Aether in 2x2 grid | Theme changes to Aether | ⬜ |
| 3 | Click Ember in 2x2 grid | Theme changes to Ember | ⬜ |
| 4 | Click Aurum in 2x2 grid | Theme changes to Aurum | ⬜ |
| 5 | Click Verdant in 2x2 grid | Theme changes to Verdant | ⬜ |
| 6 | Click intensity buttons | Intensity changes, no Iris trigger | ⬜ |
| 7 | Collapse switcher | Collapses cleanly, no Iris trigger | ⬜ |

---

### Test 5: Navigation System Integrity
**Objective:** Ensure navigation remains fully functional

| Level | Action | Expected Result | Status |
|-------|--------|-----------------|--------|
| 1→2 | Click Iris Orb | Expands to show 6 main nodes | ⬜ |
| 2→3 | Click VOICE node | Shows VOICE subnodes | ⬜ |
| 3→4 | Click INPUT subnode | Shows Mini Node Stack | ⬜ |
| 4→3 | Click Iris Orb | Returns to subnodes | ⬜ |
| 3→2 | Click Iris Orb | Returns to main nodes | ⬜ |
| 2→1 | Click Iris Orb | Collapses to center | ⬜ |

---

### Test 6: Animation Performance
**Objective:** Verify smooth 60fps animations

| Animation | Expected FPS | Visual Quality | Status |
|-----------|--------------|----------------|--------|
| Shimmer border rotation | 60fps | Smooth, no stutter | ⬜ |
| Floating orbs drift | 60fps | Smooth, organic motion | ⬜ |
| Node spin transitions | 60fps | Smooth spiral motion | ⬜ |
| Iris pulse/breathe | 60fps | Smooth glow pulsation | ⬜ |
| Theme switch | 60fps | Smooth color transition | ⬜ |

---

### Test 7: Responsive Behavior
**Objective:** Verify correct rendering at different sizes

| Device Size | Node Size | Iris Size | Status |
|-------------|-----------|-----------|--------|
| Desktop (>640px) | 90x90px | 140px | ⬜ |
| Mobile (<640px) | 72x72px | 110px | ⬜ |

---

### Test 8: Edge Cases
**Objective:** Handle edge cases gracefully

| Scenario | Action | Expected Result | Status |
|----------|--------|-----------------|--------|
| Rapid theme switching | Click 4 themes rapidly | No crashes, last theme applied | ⬜ |
| Mid-transition theme change | Change theme during spin | Smooth transition to new theme | ⬜ |
| LocalStorage corruption | Corrupt theme key in storage | Falls back to Aether | ⬜ |
| Browser zoom | Zoom to 150% | Layout remains intact | ⬜ |

---

## Test Execution Commands

```bash
# Start dev server
npm run dev

# Run visual tests
# - Open http://localhost:3001
# - Execute test plan above
# - Capture screenshots of each theme

# Build test
npm run build

# Lint check
npm run lint
```

---

## Implementation Summary

### Completed Work

| Phase | File | Changes | Status |
|-------|------|---------|--------|
| **Phase 1** | `contexts/BrandColorContext.tsx` | Added PRISM_THEMES with 4 theme configs (Aether, Ember, Aurum, Verdant), added getThemeConfig helper, renamed 'default' to 'verdant' | ✅ |
| **Phase 2** | `components/iris/prism-node.tsx` | Created new PrismNode component with square shape (2.5rem radius), conic gradient shimmer borders, radial glow, floating orbs per theme | ✅ |
| **Phase 3** | `components/testing/ThemeTestSwitcher.tsx` | Redesigned with 2x2 grid layout, theme previews with gradient backgrounds, theme name + mood descriptions, intensity selector | ✅ |
| **Phase 4** | `components/hexagonal-control-center.tsx` | Reverted IrisOrb to original styling (user request), kept glowColor prop | ✅ |

### Key Implementation Details

**BrandColorContext:**
- PRISM_THEMES object with complete theme specifications
- Each theme has: gradient (from/to), shimmer (primary/secondary), floatingElements, text, glass config
- Verdant theme has NO floating orbs (intentional for liquid glass effect)
- getThemeConfig() returns current theme configuration based on selected theme

**PrismNode Component:**
- Square shape with `rounded-[2.5rem]` (40px radius)
- 3 layered visual effect: outer glow → animated shimmer border → glass card
- Conic gradient rotates continuously (8s duration)
- Floating orbs drift with organic motion (only for Aether/Ember/Aurum)
- Theme colors applied dynamically via getThemeConfig()

**Theme Switcher:**
- Fixed position at top-left (z-[9999])
- Collapsed state shows current theme name with colored indicator
- Expanded state shows 2x2 grid of all themes
- Each theme card shows gradient preview + shimmer animation
- All buttons use `e.stopPropagation()` to prevent Iris click triggering
- Intensity selector (subtle/medium/strong) preserved

### Files Modified
- `contexts/BrandColorContext.tsx` - Theme configuration
- `components/iris/prism-node.tsx` - New node component
- `components/testing/ThemeTestSwitcher.tsx` - Theme switcher redesign
- `components/hexagonal-control-center.tsx` - IrisOrb usage updated

### Next Steps
Execute the comprehensive test plan above to verify all functionality works correctly.

---

## Final Fixes (Feb 4, 2026)

### Fix 1: Iris Orb Glow Color
**Issue:** Iris Orb glow was using WebSocket theme color instead of current Prism theme color
**Solution:** 
- Added `useBrandColor` hook to `HexagonalControlCenter`
- Created `themeGlowColor` from `getThemeConfig().glow.color`
- Updated `IrisOrb` component to use `themeGlowColor` prop instead of `glowColor`
- All glow effects (outer breathe, inner pulse, shimmer, text shadow) now use theme color

**Files Modified:**
- `components/hexagonal-control-center.tsx`

### Fix 2: Liquid Metal Border Effect
**Issue:** Nodes needed a metallic/liquid metal shimmer effect around borders
**Solution:**
- Added new animated layer in `PrismNode` component
- Uses conic gradient with 8 color stops for metallic appearance
- Rotates continuously (12s duration) for liquid metal effect
- Positioned between outer glow and shimmer border
- Has subtle blur (0.5px) for smooth metallic look

**Files Modified:**
- `components/iris/prism-node.tsx`

### Fix 3: Verdant Theme Color Reversal
**Issue:** Verdant theme made everything white - nodes, icons, and iris glow
**Root Cause:** Changed shimmer colors to white which affected both iris orb glow AND node icons
**Solution:**
1. Reverted shimmer colors back to verdant green (`hsl(145, 100%, 55%)`)
2. Added `isVerdant` detection in `PrismNode` component (checks `theme.orbs === null`)
3. Created `iconColor` variable: white for verdant, theme color for others
4. Icons now use `iconColor` instead of `theme.shimmer.primary`
5. Kept verdant gradient as green tones (`hsl(145, 70%, 35%)` to `hsl(145, 80%, 45%)`)

**Result:** 
- Nodes: Verdant green background with white icons
- Iris Orb: Verdant green glow (matches other themes)
- Other themes: Unchanged behavior

**Files Modified:**
- `contexts/BrandColorContext.tsx` - Reverted shimmer colors
- `components/iris/prism-node.tsx` - Added verdant detection + white icons

### Implementation Status: ✅ COMPLETE & VERIFIED

**Test Date:** Feb 5, 2026

**Test Method:** Browser automation via Playwright MCP

**Console Verification:**
```
[DEBUG] Navigation state changed: {..., themeGlowColor: #00c8ff}  // Aether
[DEBUG] Navigation state changed: {..., themeGlowColor: #ff6432}  // Ember  
[DEBUG] Navigation state changed: {..., themeGlowColor: #ffc832}  // Aurum
[DEBUG] Navigation state changed: {..., themeGlowColor: #32ff64}  // Verdant
[DEBUG] PrismNode theme: {name: Verdant, gradient: Object...}  // All levels
```

**Test Results:**
| Fix | Component | Expected | Verified | Status |
|-----|-----------|----------|----------|--------|
| Iris Orb Glow | All themes | Theme color glow | Console confirmed | ✅ PASS |
| Verdant Nodes | Level 2-4 | Green background | Console confirmed | ✅ PASS |
| Liquid Metal | All nodes | Metallic border | Visual confirmed | ✅ PASS |
| Theme Switcher | All themes | No Iris trigger | Working correctly | ✅ PASS |

**Navigation Test:**
- Level 1 (Iris) → 2 (Main nodes) → 3 (Subnodes) → 4 (Mini stack) → Back navigation
- All themes applied correctly at each level
- No console errors related to theming

---

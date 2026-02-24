# Wheel Spin Menu Implementation Plan

## Overview
Implement a radial wheel spin menu as an alternative view mode for Level 4 mini-nodes. This feature allows users to interact with mini-nodes via a draggable, spring-physics wheel instead of the vertical accordion stack.

## Requirements Summary
- **Integration Option B**: Alternative view mode (toggle between accordion and wheel)
- **Categories**: Map to existing categories (VOICE, AGENT, AUTOMATE, SYSTEM, CUSTOMIZE, MONITOR)
- **Interaction**: Draggable wheel with snap-to-nearest behavior
- **Selection**: Opens mini-node settings like accordion click
- **Styling**: Glass morphism with brand color theming, 384px size
- **Animation**: Spring physics, animate on enter Level 4
- **Accessibility**: Keyboard navigation (arrows, enter), reduced motion fallback
- **Data**: Dynamic adaptation for 2-8 mini-nodes per subnode

## Architecture

### New Components
1. `WheelSpinMenu` - Main wheel component with drag physics
2. `Level4View` - Modified to support view mode toggle

### State Management
- Add `level4ViewMode` to NavState ('accordion' | 'wheel')
- Add `SET_LEVEL4_VIEW_MODE` action
- Add `toggleLevel4ViewMode` helper

### Integration Points
- MiniNodeStack (existing accordion view)
- NavigationContext (view mode state)
- BrandColorContext (theming)
- useReducedMotion (accessibility)

## Implementation Steps

### Step 1: Update Types
**File**: `types/navigation.ts`

Add:
```typescript
export type Level4ViewMode = 'accordion' | 'wheel'

// Add to NavState:
level4ViewMode: Level4ViewMode

// Add to NavAction:
| { type: 'SET_LEVEL4_VIEW_MODE'; payload: { mode: Level4ViewMode } }
```

### Step 2: Create WheelSpinMenu Component
**File**: `components/iris/wheel-spin-menu.tsx`

Features:
- useMotionValue for rotation tracking
- Pan handlers for drag-to-spin
- Spring animation for snap-to-nearest
- Keyboard navigation (Arrow keys, Enter)
- Reduced motion fallback (simple list)
- Glass morphism styling with theme colors
- Dynamic item positioning based on count

### Step 3: Update NavigationContext
**File**: `contexts/NavigationContext.tsx`

Add:
- level4ViewMode to initialState
- Handle SET_LEVEL4_VIEW_MODE in reducer
- toggleLevel4ViewMode helper function
- Persist view mode preference

### Step 4: Modify Level4View
**File**: `components/level-4-view.tsx`

Changes:
- Import WheelSpinMenu
- Add view mode toggle UI (button/icon)
- Conditional render: MiniNodeStack vs WheelSpinMenu
- Pass required props to both views

### Step 5: Update MiniNodeStack
**File**: `components/mini-node-stack.tsx`

Add:
- View mode toggle button
- Consistent styling with wheel view

## Technical Details

### Wheel Physics
- Rotation tracked via useMotionValue(0)
- Angle per item: 360 / itemCount
- Radius: 140px from center
- Snap threshold: nearest angleStep
- Spring config: stiffness 200, damping 30

### Styling
- Center circle: 120px with progress arc
- Items: Glass cards with icon + label
- Active item: Glow effect with brand color
- Background: Transparent with blur

### Keyboard Navigation
- ArrowRight/ArrowDown: Next item
- ArrowLeft/ArrowUp: Previous item
- Enter: Select current item

### Reduced Motion Fallback
- Simple vertical list of buttons
- No rotation animations
- Immediate state changes

## Files to Modify

| File | Changes |
|------|---------|
| types/navigation.ts | Add Level4ViewMode type and state |
| contexts/NavigationContext.tsx | Add view mode state and actions |
| components/iris/wheel-spin-menu.tsx | Create new component |
| components/level-4-view.tsx | Add view toggle and conditional render |
| components/mini-node-stack.tsx | Add view toggle button |

## Testing Checklist

- [ ] Wheel renders with correct item count
- [ ] Drag rotates wheel smoothly
- [ ] Release snaps to nearest item
- [ ] Keyboard navigation works
- [ ] Enter opens mini-node settings
- [ ] View mode toggle switches views
- [ ] Reduced motion shows list view
- [ ] Theme colors apply correctly
- [ ] Animation enters on Level 4
- [ ] Works with 2-8 mini-nodes

## Future Enhancements
- Haptic feedback on snap
- Sound effects on rotation
- Velocity-based spinning
- Momentum scrolling

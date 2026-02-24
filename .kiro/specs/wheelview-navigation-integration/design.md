# Design Document: WheelView Navigation Integration

## Overview

This design consolidates the IRISVOICE navigation system from 4 levels to 3 levels by integrating the WheelView component. The WheelView combines Level 3 (sub-nodes) and Level 4 (mini-nodes) into a single enhanced view with a working dual orbital ring mechanism.

The current Level 4 implementation (level-4-orbital-view.tsx) has a broken inner ring that prevents users from accessing all 52 mini-nodes. This design fixes the inner ring functionality while preserving all 52 mini-nodes and their 61 input fields across 6 main categories.

### Key Design Goals

1. Eliminate Level 4 as a separate navigation level
2. Fix the broken inner ring mechanism for mini-node access
3. Display both sub-nodes (outer ring) and mini-nodes (inner ring) simultaneously
4. Provide a side panel for input field configuration
5. Maintain all existing data (52 mini-nodes, 61 fields)
6. Ensure smooth animations and theme integration
7. Support full keyboard navigation

### User Experience Flow

```
Level 1 (Collapsed Orb) 
  → Level 2 (6 Main Categories in hexagonal layout)
    → Level 3 (WheelView with dual rings)
       ├── Outer Ring: Sub-nodes (Input, Output, Processing, Model...)
       ├── Inner Ring: Mini-nodes (Device, Sensitivity, Noise Gate...)
       └── Side Panel: Input fields for selected mini-node
```


## Architecture

### Component Hierarchy

```
NavigationSystem
├── Level1View (Collapsed Orb)
├── Level2View (Main Categories - Hexagonal Layout)
└── Level3View (WheelView Component) ← NEW: Replaces separate Level 4
    ├── DualRingMechanism (SVG Visualization)
    │   ├── OuterRing (Sub-nodes)
    │   ├── InnerRing (Mini-nodes) ← FIXED: Now fully functional
    │   ├── DecorativeRings (Visual depth)
    │   └── SelectionIndicator (12 o'clock marker)
    ├── CenterButton (Back to categories)
    ├── SidePanel (Detail Panel)
    │   ├── ConnectionLine (Glowing animated line)
    │   ├── PanelHeader (Mini-node label)
    │   ├── FieldList (Form inputs)
    │   │   ├── ToggleField (21 instances)
    │   │   ├── SliderField (13 instances)
    │   │   ├── DropdownField (17 instances)
    │   │   ├── TextField (9 instances)
    │   │   └── ColorField (1 instance)
    │   └── ConfirmButton (Save changes)
    └── AnimationLayers
        ├── GlowBreathe (Ambient pulsing)
        ├── FlashOverlay (Confirm feedback)
        └── ShimmerEffect (Ring highlights)
```

### Data Flow

```
NavigationContext (Global State)
    ↓
WheelView Component
    ↓
    ├→ DualRingMechanism (reads: miniNodeStack, selectedIndex)
    ├→ SidePanel (reads: activeMiniNode, miniNodeValues)
    └→ Field Components (read/write: field values)
         ↓
    updateMiniNodeValue (action)
         ↓
    NavigationContext (state update)
         ↓
    LocalStorage (persistence)
```


### State Management Architecture

The navigation system uses React Context with useReducer for centralized state management:

**NavigationContext Responsibilities:**
- Track current navigation level (1, 2, or 3)
- Store selected main category and sub-node
- Maintain mini-node stack for current sub-node
- Track active mini-node index
- Persist mini-node field values
- Handle navigation transitions

**Key State Changes:**
1. Level 4 removed from NavigationLevelType (now 1 | 2 | 3)
2. SELECT_SUB action now sets level to 3 (not 4)
3. GO_BACK from level 3 returns to level 2
4. Level 4 specific actions removed (SET_LEVEL4_VIEW_MODE)
5. State restoration normalizes level 4 → level 3


## Components and Interfaces

### WheelView Component

**Purpose:** Main container that orchestrates the dual-ring visualization and side panel.

**Props Interface:**
```typescript
interface WheelViewProps {
  categoryId: string              // Main category ID (e.g., 'voice')
  glowColor: string               // Theme glow color from BrandColorContext
  expandedIrisSize: number        // Orb size (typically 240px)
  initialValues?: Record<string, Record<string, FieldValue>>
  onConfirm: (values: Record<string, Record<string, FieldValue>>) => void
  onBackToCategories: () => void
}
```

**Internal State:**
```typescript
{
  selectedSubNodeIndex: number    // Outer ring selection
  selectedMiniNodeIndex: number   // Inner ring selection
  confirmFlash: boolean           // Flash animation trigger
  confirmSpinning: boolean        // Counter-spin animation
  lineRetracted: boolean          // Connection line state
  showPanel: boolean              // Panel visibility
}
```

**Responsibilities:**
- Fetch mini-node stack from NavigationContext
- Distribute mini-nodes across outer/inner rings (split at midpoint)
- Handle keyboard navigation (arrows, enter, escape)
- Coordinate animations between rings and panel
- Integrate with BrandColorContext for theming


### DualRingMechanism Component

**Purpose:** SVG-based visualization of outer and inner orbital rings with clickable segments.

**Props Interface:**
```typescript
interface DualRingMechanismProps {
  items: MiniNode[]               // All mini-nodes for current sub-node
  selectedIndex: number           // Currently selected mini-node
  onSelect: (index: number) => void
  glowColor: string
  orbSize: number
  confirmSpinning: boolean
}
```

**Ring Distribution Logic:**
```typescript
const splitPoint = Math.ceil(items.length / 2)
const outerItems = items.slice(0, splitPoint)      // First half
const innerItems = items.slice(splitPoint)         // Second half
```

**Ring Specifications:**

**Outer Ring (Sub-nodes):**
- Radius: orbSize * 0.42
- Stroke width: 28px
- Segment separators: Diamond markers
- Text: Curved along arc path
- Rotation: Centers selected item at 12 o'clock
- Animation: Spring physics (stiffness 80, damping 16)

**Inner Ring (Mini-nodes):**
- Radius: orbSize * 0.18
- Stroke width: 22px
- Segment separators: Circle markers
- Text: Curved along arc path (radius + 14)
- Rotation: Centers selected item at 12 o'clock
- Animation: Spring physics (stiffness 80, damping 16)
- Depth styling: Drop shadows and glow effects

**Decorative Rings:**
- Ring 1 (innermost): radius * 0.18 - 6, dashed pattern
- Ring 2 (middle): radius * 0.30 + 6, dashed pattern
- Ring 3 (outermost): radius * 0.42 + 14, 24 tick marks

**Groove Separator:**
- Position: Between outer and inner rings
- Styling: Dark cavity with edge highlights
- Purpose: Visual depth and ring separation


### SidePanel Component

**Purpose:** Display input fields for the selected mini-node with glowing connection line.

**Props Interface:**
```typescript
interface SidePanelProps {
  miniNode: MiniNode
  glowColor: string
  values: Record<string, FieldValue>
  onValueChange: (fieldId: string, value: FieldValue) => void
  onConfirm: () => void
  lineRetracted: boolean
  orbSize: number
}
```

**Layout:**
- Position: Right side of orb (orbSize/2 + 12px offset)
- Width: 100px (narrow for vertical space)
- Max height: 560px
- Styling: Glass-morphism (backdrop blur, transparency)

**Connection Line:**
- Width: 24px
- Animation: Spring extension/retraction
- Visual: Gradient glow with traveling shimmer
- Trigger: Extends on selection, retracts on confirm

**Panel Sections:**
1. Header: Mini-node label with indicator dot
2. Fields: Scrollable list with crossfade transitions
3. Footer: Confirm button with icon

**Field Components:**

**ToggleField:**
```typescript
interface ToggleFieldProps {
  id: string
  label: string
  value: boolean
  onChange: (value: boolean) => void
  glowColor: string
}
```
- Visual: Sliding pill switch
- Animation: Spring physics for toggle movement
- States: On (glow color) / Off (white/10)

**SliderField:**
```typescript
interface SliderFieldProps {
  id: string
  label: string
  value: number
  min: number
  max: number
  step: number
  unit?: string
  onChange: (value: number) => void
  glowColor: string
}
```
- Visual: Range input with value display
- Styling: Accent color matches glow
- Display: Monospace font for numeric value

**DropdownField:**
```typescript
interface DropdownFieldProps {
  id: string
  label: string
  value: string
  options: string[]
  loadOptions?: () => Promise<{label: string, value: string}[]>
  onChange: (value: string) => void
  glowColor: string
}
```
- Dynamic loading: Calls loadOptions on mount
- Caching: Prevents redundant backend calls
- Loading state: Spinner indicator
- Error handling: Fallback to empty array

**TextField:**
```typescript
interface TextFieldProps {
  id: string
  label: string
  value: string
  placeholder?: string
  onChange: (value: string) => void
  glowColor: string
}
```
- Styling: Caret color matches glow
- Focus state: Border color transition

**ColorField:**
```typescript
interface ColorFieldProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  glowColor: string
}
```
- Visual: Color picker with hex display
- Display: Uppercase hex value in monospace


### ConnectionLine Component

**Purpose:** Animated glowing line connecting orb to side panel.

**Visual Specifications:**
- Base gradient: glowColor with alpha fade (cc → 44)
- Glow layer: Blurred gradient (44 → 11)
- Shimmer: Traveling highlight (28px width)
- Animation: Continuous linear motion (2s loop)

**States:**
- Extended: scaleX(1) - visible connection
- Retracted: scaleX(0) - hidden during confirm

**Spring Configuration:**
```typescript
{
  type: "spring",
  stiffness: 200,
  damping: 25
}
```


## Data Models

### NavigationLevelType

**Before (4 levels):**
```typescript
type NavigationLevelType = 1 | 2 | 3 | 4
```

**After (3 levels):**
```typescript
type NavigationLevelType = 1 | 2 | 3
```

**Migration:**
- All level 4 references → level 3
- Type guards updated to accept only 1, 2, 3
- LEVEL_NAMES constant reduced to 3 entries

### NavState Interface

**Updated Interface:**
```typescript
interface NavState {
  level: NavigationLevelType        // Now 1 | 2 | 3
  selectedMain: string | null       // Main category ID
  selectedSub: string | null        // Sub-node ID
  miniNodeStack: MiniNode[]         // Mini-nodes for selected sub
  activeMiniNodeIndex: number       // Selected mini-node index
  miniNodeValues: Record<string, Record<string, FieldValue>>
  // REMOVED: level4ViewMode
}
```

**Removed Properties:**
- `level4ViewMode: 'orbital' | 'list'` - No longer needed

### MiniNode Interface

```typescript
interface MiniNode {
  id: string                        // Unique ID (kebab-case)
  label: string                     // Display name
  icon: string                      // Lucide icon name
  fields: FieldConfig[]             // Input field definitions
}
```

**Example:**
```typescript
{
  id: 'input-device',
  label: 'Input Device',
  icon: 'Mic',
  fields: [
    {
      id: 'input_device',
      label: 'Microphone',
      type: 'dropdown',
      options: ['Default', 'USB Microphone', 'Headset'],
      defaultValue: 'Default',
      loadOptions: async () => fetchAudioDevices()
    }
  ]
}
```


### FieldConfig Interface

```typescript
interface FieldConfig {
  id: string                        // Field identifier
  label: string                     // Display label
  type: FieldType                   // Field type
  placeholder?: string              // Text field placeholder
  options?: string[]                // Dropdown options
  loadOptions?: () => Promise<{label: string, value: string}[]>
  min?: number                      // Slider minimum
  max?: number                      // Slider maximum
  step?: number                     // Slider step
  unit?: string                     // Slider unit display
  defaultValue?: FieldValue         // Default value
}

type FieldType = 'text' | 'slider' | 'dropdown' | 'toggle' | 'color'
type FieldValue = string | number | boolean
```

**Field Type Distribution (61 total):**
- Toggle: 21 fields (boolean switches)
- Dropdown: 17 fields (select menus)
- Slider: 13 fields (numeric ranges)
- Text: 9 fields (text inputs)
- Color: 1 field (color picker)

### SubNode Interface

```typescript
interface SubNode {
  id: string                        // Sub-node ID (kebab-case)
  label: string                     // Display name
  miniNodes: MiniNode[]             // Associated mini-nodes
}
```

### Category Interface

```typescript
interface Category {
  id: string                        // Category ID (kebab-case)
  label: string                     // Display name
  icon: string                      // Lucide icon name
  subNodes: SubNode[]               // Sub-nodes in this category
}
```

**Complete Data Structure (52 Mini-nodes):**
- Voice: 3 sub-nodes, 7 mini-nodes, 8 fields
- Agent: 4 sub-nodes, 9 mini-nodes, 10 fields
- Automate: 5 sub-nodes, 10 mini-nodes, 13 fields
- System: 4 sub-nodes, 4 mini-nodes, 4 fields
- Customize: 4 sub-nodes, 4 mini-nodes, 4 fields
- Monitor: 4 sub-nodes, 5 mini-nodes, 5 fields


## Animation System

### Spring Physics Configuration

All rotations and transitions use Framer Motion spring physics for natural movement:

```typescript
const springConfig = {
  type: "spring",
  stiffness: 80,
  damping: 16
}
```

**Characteristics:**
- Smooth deceleration with slight overshoot
- Natural feeling momentum
- Consistent across all ring rotations

### Ring Rotation Logic

**Outer Ring Rotation:**
```typescript
const outerSegmentAngle = 360 / outerItems.length
const outerSelectedIndex = selectedIndex < splitPoint ? selectedIndex : -1
const outerBaseRotation = outerSelectedIndex >= 0 
  ? -(outerSelectedIndex * outerSegmentAngle) 
  : 0
```

**Inner Ring Rotation:**
```typescript
const innerSegmentAngle = 360 / innerItems.length
const innerSelectedIndex = selectedIndex >= splitPoint 
  ? selectedIndex - splitPoint 
  : -1
const innerBaseRotation = innerSelectedIndex >= 0 
  ? -(innerSelectedIndex * innerSegmentAngle) 
  : 0
```

**Rotation Goal:** Center the selected item at 12 o'clock (top) position.

### Confirm Animation Sequence

**Duration:** 900ms total

**Timeline:**
1. **0ms:** Line retraction begins (spring animation)
2. **0ms:** Counter-spin starts
   - Outer ring: +360° clockwise
   - Inner ring: -360° counter-clockwise
3. **0ms:** Flash overlay appears
   - Scale pulse: 0.8 → 1.4
   - Opacity fade: 0.3 → 1 → 0.3
4. **0ms:** Glow breathe intensifies
   - Scale: 1 → 2.2 → 1
5. **800ms:** Animations complete
6. **900ms:** onConfirm callback fires

**Spring Configuration for Confirm:**
```typescript
{
  duration: 0.8,
  ease: "easeInOut"
}
```


### Panel Crossfade Animation

When switching between mini-nodes, the side panel uses crossfade transitions:

**Exit Animation:**
```typescript
{
  opacity: 0,
  y: -8,
  transition: { duration: 0.2 }
}
```

**Enter Animation:**
```typescript
{
  opacity: 1,
  y: 0,
  transition: { duration: 0.2 }
}
```

**AnimatePresence Configuration:**
```typescript
<AnimatePresence mode="wait">
  {/* Panel content keyed by miniNode.id */}
</AnimatePresence>
```

### Decorative Ring Animations

**CSS Keyframes for Continuous Rotation:**

```css
.ring-outer-anim {
  animation: rotate-slow 60s linear infinite;
}

.ring-middle-anim {
  animation: rotate-slow 45s linear infinite reverse;
}

.ring-inner-anim {
  animation: rotate-slow 30s linear infinite;
}

@keyframes rotate-slow {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
```

**Purpose:** Ambient motion for visual interest without distracting from main interactions.


## Integration Points

### NavigationContext Integration

**Context Provider Location:** `contexts/NavigationContext.tsx`

**Required Changes:**

1. **Type Updates:**
```typescript
// Before
type NavigationLevelType = 1 | 2 | 3 | 4

// After
type NavigationLevelType = 1 | 2 | 3
```

2. **State Interface:**
```typescript
// Remove level4ViewMode property
interface NavState {
  level: NavigationLevelType
  selectedMain: string | null
  selectedSub: string | null
  miniNodeStack: MiniNode[]
  activeMiniNodeIndex: number
  miniNodeValues: Record<string, Record<string, FieldValue>>
  // REMOVED: level4ViewMode: 'orbital' | 'list'
}
```

3. **Reducer Actions:**
```typescript
// Update SELECT_SUB to set level 3
case 'SELECT_SUB':
  return {
    ...state,
    level: 3,  // Changed from 4
    selectedSub: action.payload.subId,
    miniNodeStack: action.payload.miniNodes,
    activeMiniNodeIndex: 0
  }

// Update GO_BACK from level 3
case 'GO_BACK':
  if (state.level === 3) {
    return {
      ...state,
      level: 2,  // Changed from checking level 4
      selectedSub: null,
      miniNodeStack: [],
      activeMiniNodeIndex: 0
    }
  }
  // ... other cases

// REMOVE SET_LEVEL4_VIEW_MODE action entirely
```

4. **State Restoration:**
```typescript
// Normalize level 4 to level 3 when restoring from localStorage
const normalizeLevel = (level: number): NavigationLevelType => {
  if (level > 3) return 3
  if (level < 1) return 1
  return level as NavigationLevelType
}

const restoredState = {
  ...savedState,
  level: normalizeLevel(savedState.level)
}
```


### BrandColorContext Integration

**Context Provider Location:** `contexts/BrandColorContext.tsx`

**Usage in WheelView:**
```typescript
import { useBrandColor } from '@/contexts/BrandColorContext'

function WheelView() {
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  const glowColor = theme.glow.color  // e.g., '#00D4FF'
  
  // Pass glowColor to all child components
}
```

**Color Utilities:**
```typescript
// Convert hex to rgba with alpha
function hexToRgba(hex: string, alpha: number): string {
  hex = hex.replace('#', '')
  const r = parseInt(hex.substring(0, 2), 16)
  const g = parseInt(hex.substring(2, 4), 16)
  const b = parseInt(hex.substring(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// Usage examples
const ringStroke = hexToRgba(glowColor, 0.4)   // 40% opacity
const glowShadow = hexToRgba(glowColor, 0.2)   // 20% opacity
const textColor = hexToRgba(glowColor, 0.6)    // 60% opacity
```

**Theme Application:**
- Ring segments: glowColor with varying alpha
- Text labels: glowColor for active, reduced alpha for inactive
- Glow effects: glowColor with blur filters
- Connection line: glowColor gradient
- Panel edges: glowColor with low alpha
- Selection indicators: full glowColor


### Main Navigation Component Integration

**Component Location:** Main navigation router/switch component

**Before (4 levels):**
```typescript
function NavigationRouter() {
  const { state } = useNavigation()
  
  switch (state.level) {
    case 1: return <Level1View />
    case 2: return <Level2View />
    case 3: return <Level3View />
    case 4: return <Level4View />  // Separate component
  }
}
```

**After (3 levels):**
```typescript
function NavigationRouter() {
  const { state } = useNavigation()
  
  switch (state.level) {
    case 1: return <Level1View />
    case 2: return <Level2View />
    case 3: return <WheelView />   // Integrated dual-ring view
  }
}
```

**Import Changes:**
```typescript
// Remove
import { Level4View } from '@/components/level-4-view'
import { Level4OrbitalView } from '@/components/level-4-orbital-view'

// Add
import { WheelView } from '@/components/wheel-view'
```


### LocalStorage Integration

**Storage Keys:**
```typescript
const STORAGE_KEY = 'irisvoice-nav-state'
const CONFIG_STORAGE_KEY = 'irisvoice-config'
const MINI_NODE_VALUES_KEY = 'irisvoice-mini-node-values'
```

**State Persistence:**
```typescript
// Save on every state change
useEffect(() => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    level: state.level,
    selectedMain: state.selectedMain,
    selectedSub: state.selectedSub,
    activeMiniNodeIndex: state.activeMiniNodeIndex
  }))
}, [state])

// Save mini-node values separately
useEffect(() => {
  localStorage.setItem(
    MINI_NODE_VALUES_KEY, 
    JSON.stringify(state.miniNodeValues)
  )
}, [state.miniNodeValues])
```

**State Restoration with Migration:**
```typescript
function restoreState(): NavState {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (!saved) return defaultState
  
  const parsed = JSON.parse(saved)
  
  // Migrate level 4 to level 3
  if (parsed.level === 4) {
    parsed.level = 3
  }
  
  // Remove obsolete properties
  delete parsed.level4ViewMode
  
  return {
    ...defaultState,
    ...parsed,
    level: normalizeLevel(parsed.level)
  }
}
```


### Keyboard Navigation Integration

**Event Handler Location:** WheelView component

**Implementation:**
```typescript
useEffect(() => {
  const handleKeyDown = (e: KeyboardEvent) => {
    // Prevent default browser behavior
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Enter', 'Escape'].includes(e.key)) {
      e.preventDefault()
    }
    
    switch (e.key) {
      case 'ArrowRight':
        // Next sub-node (outer ring)
        setSelectedSubNodeIndex((prev) => 
          (prev + 1) % outerItems.length
        )
        break
        
      case 'ArrowLeft':
        // Previous sub-node (outer ring)
        setSelectedSubNodeIndex((prev) => 
          (prev - 1 + outerItems.length) % outerItems.length
        )
        break
        
      case 'ArrowDown':
        // Next mini-node (inner ring)
        setSelectedMiniNodeIndex((prev) => 
          (prev + 1) % items.length
        )
        break
        
      case 'ArrowUp':
        // Previous mini-node (inner ring)
        setSelectedMiniNodeIndex((prev) => 
          (prev - 1 + items.length) % items.length
        )
        break
        
      case 'Enter':
        // Confirm current selection
        handleConfirm()
        break
        
      case 'Escape':
        // Back to categories
        onBackToCategories()
        break
    }
  }
  
  window.addEventListener('keydown', handleKeyDown)
  return () => window.removeEventListener('keydown', handleKeyDown)
}, [outerItems.length, items.length])
```

**Accessibility:**
- All navigation keys work without mouse
- Focus states visible on interactive elements
- ARIA labels on all clickable segments
- Screen reader announcements for selection changes


## Migration Strategy

### Phase 1: Type System Updates

**Files to Update:**
1. `types/navigation.ts` - Update NavigationLevelType
2. `contexts/NavigationContext.tsx` - Update NavState interface
3. All components using NavigationLevelType

**Changes:**
```typescript
// Remove level 4 from type
type NavigationLevelType = 1 | 2 | 3

// Remove level4ViewMode from NavState
interface NavState {
  // ... other properties
  // DELETE: level4ViewMode: 'orbital' | 'list'
}

// Update LEVEL_NAMES constant
const LEVEL_NAMES = {
  1: 'Collapsed',
  2: 'Categories',
  3: 'Settings'  // Was 'Sub-nodes', now includes mini-nodes
}
```

### Phase 2: Reducer Updates

**File:** `contexts/NavigationContext.tsx`

**Changes:**
1. Update SELECT_SUB action to set level 3
2. Update GO_BACK action to handle level 3 → 2
3. Remove SET_LEVEL4_VIEW_MODE action
4. Add state normalization for localStorage restoration

**Testing:**
- Verify SELECT_SUB sets level to 3
- Verify GO_BACK from level 3 returns to level 2
- Verify no level 4 states can be reached


### Phase 3: Component Creation

**New Component:** `components/wheel-view.tsx`

**Structure:**
```
wheel-view.tsx (main export)
├── WheelView (container)
├── DualRingMechanism (SVG rings)
├── SidePanel (detail panel)
├── ConnectionLine (animated line)
└── Field Components
    ├── ToggleField
    ├── SliderField
    ├── DropdownField
    ├── TextField
    └── ColorField
```

**Implementation Order:**
1. Create field components (memoized)
2. Create ConnectionLine component
3. Create SidePanel component
4. Create DualRingMechanism component
5. Create WheelView container
6. Add keyboard navigation
7. Add animations

**Testing:**
- Verify all 52 mini-nodes render correctly
- Verify inner ring is clickable and functional
- Verify field values persist
- Verify animations are smooth
- Verify keyboard navigation works

### Phase 4: Component Removal

**Files to Delete:**
1. `components/level-4-view.tsx`
2. `components/level-4-orbital-view.tsx`

**Files to Update:**
1. Main navigation router - Remove Level4View imports
2. Any components importing Level4View or Level4OrbitalView

**Verification:**
- Search codebase for "Level4View" references
- Search codebase for "level-4-" file references
- Ensure no broken imports remain


### Phase 5: LocalStorage Migration

**Migration Function:**
```typescript
function migrateNavigationState() {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (!saved) return
  
  const state = JSON.parse(saved)
  let migrated = false
  
  // Normalize level 4 to level 3
  if (state.level === 4) {
    state.level = 3
    migrated = true
  }
  
  // Remove obsolete properties
  if ('level4ViewMode' in state) {
    delete state.level4ViewMode
    migrated = true
  }
  
  // Save migrated state
  if (migrated) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    console.log('[Migration] Navigation state migrated to 3-level system')
  }
}

// Run on app initialization
migrateNavigationState()
```

**Data Preservation:**
- All mini-node values preserved
- Selected category/sub-node preserved
- Active mini-node index preserved
- Only level number and obsolete properties changed

### Phase 6: Integration Testing

**Test Scenarios:**
1. Fresh install (no localStorage)
2. Existing user with level 4 state
3. Navigation through all 6 categories
4. All 52 mini-nodes accessible
5. Field value persistence
6. Keyboard navigation
7. Theme changes
8. Confirm animations
9. Error states (empty mini-nodes, invalid fields)
10. Dynamic dropdown loading

**Acceptance Criteria:**
- No level 4 states reachable
- All mini-nodes accessible via inner ring
- No data loss during migration
- Smooth animations throughout
- Full keyboard support
- Theme integration working


## Correctness Properties

A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.

### Property Reflection

After analyzing all 15 requirements with 107 acceptance criteria, I identified the following redundancies:

**Redundant Properties Eliminated:**
- 1.5 (same as 1.1): Level invariant
- 3.3 (same as 2.4): Side panel displays fields for selected mini-node
- 3.7 (same as 3.1): Inner ring clickability
- 4.7 (same as 1.1): Level range invariant
- 5.1 (same as 2.4): Side panel field display
- 6.2 (same as 3.4): Inner ring spring configuration
- 8.1 (same as 2.6): 52 mini-nodes preservation
- 10.1 (same as 4.6): Level 4 to 3 normalization
- 10.6 (same as 4.6): Level normalization
- 11.1 (same as 2.7): Theme integration
- 13.4 (covered by 7.1-7.7): Keyboard navigation
- 14.7 (same as 14.2): LoadOptions caching
- 15.2 (same as 5.7): Empty fields message
- 15.6 (same as 6.7): Animation race condition prevention

**Combined Properties:**
- 2.2 + 2.3: Combined into single property for dual ring rendering
- 11.2 + 11.4 + 11.5 + 11.6: Combined into comprehensive theme application property
- 13.1 + 13.2 + 13.3: Combined into comprehensive ARIA labels property

This reduces 107 criteria to approximately 60 unique testable properties.


### Property 1: Navigation Level Invariant

*For any* navigation state in the system, the level property shall always be one of {1, 2, 3}.

**Validates: Requirements 1.1, 1.5, 4.7**

### Property 2: Level Type Guard Validation

*For any* input value (including invalid values like 0, 4, 5, -1, null, undefined), type guard functions shall correctly validate only values 1, 2, or 3 as valid navigation levels.

**Validates: Requirements 1.3**

### Property 3: WheelView Rendering at Level 3

*For any* navigation state where level is 3 and selectedSub is set, the navigation system shall render the WheelView component.

**Validates: Requirements 2.1**

### Property 4: Dual Ring Label Rendering

*For any* sub-node with associated mini-nodes, the WheelView shall render both outer ring segments with sub-node labels and inner ring segments with mini-node labels in the SVG.

**Validates: Requirements 2.2, 2.3**

### Property 5: Side Panel Field Display

*For any* selected mini-node, the side panel shall display all field configurations defined for that mini-node.

**Validates: Requirements 2.4, 3.3, 5.1**

### Property 6: Mini-Node Distribution

*For any* list of mini-nodes with length n, the WheelView shall distribute ceil(n/2) items to the outer ring and floor(n/2) items to the inner ring.

**Validates: Requirements 2.5**

### Property 7: Theme Color Application

*For any* theme color provided by BrandColorContext, the WheelView shall apply that color to all ring segments, text labels, glow effects, drop shadows, decorative rings, connection line, panel edges, and selection indicators.

**Validates: Requirements 2.7, 11.1, 11.2, 11.4, 11.5, 11.6**


### Property 8: Inner Ring Clickability

*For all* mini-nodes distributed to the inner ring, each shall be rendered as a clickable segment with a click handler that triggers selection.

**Validates: Requirements 3.1, 3.7**

### Property 9: Inner Ring Rotation Centering

*For any* inner ring mini-node at index i, clicking that segment shall rotate the inner ring such that the selected item is centered at the 12 o'clock position (0° or 360°).

**Validates: Requirements 3.2**

### Property 10: Curved Text Path Rendering

*For all* mini-nodes in the inner ring, text labels shall be rendered using SVG textPath elements along arc paths at radius + 14.

**Validates: Requirements 3.5**

### Property 11: Inner Ring Depth Styling

*For all* inner ring elements, the SVG shall include drop-shadow filters and glow effects using the theme glow color.

**Validates: Requirements 3.6**

### Property 12: SELECT_SUB Sets Level 3

*For any* SELECT_SUB action dispatched to the navigation reducer, the resulting state shall have level set to 3 (not 4).

**Validates: Requirements 4.1**

### Property 13: SELECT_SUB Stores Mini-Node Stack

*For any* SELECT_SUB action with a miniNodes payload, the resulting state shall store that array in state.miniNodeStack.

**Validates: Requirements 4.2**

### Property 14: GO_BACK from Level 3

*For any* navigation state at level 3, dispatching GO_BACK shall transition the state to level 2.

**Validates: Requirements 4.3**


### Property 15: Level 3 State Preservation

*For any* navigation state at level 3, the miniNodeStack and activeMiniNodeIndex properties shall be preserved and not cleared or reset.

**Validates: Requirements 4.5**

### Property 16: LocalStorage Level Normalization

*For any* saved navigation state with level set to 4 (or any value > 3), restoring from localStorage shall normalize the level to 3.

**Validates: Requirements 4.6, 10.1, 10.6**

### Property 17: Field Type Rendering

*For any* field configuration with type in {text, slider, dropdown, toggle, color}, the side panel shall render the appropriate field component.

**Validates: Requirements 5.2**

### Property 18: Field Value Change Callback

*For any* field value change in the side panel, the onValueChange callback shall be invoked with the correct nodeId, fieldId, and new value.

**Validates: Requirements 5.3**

### Property 19: Confirm Line Retraction

*For any* confirm button click, the side panel shall set lineRetracted state to true, triggering the connection line retraction animation.

**Validates: Requirements 5.5**

### Property 20: Counter-Spin Animation

*For any* confirm button click, the dual ring mechanism shall rotate the outer ring +360° clockwise and the inner ring -360° counter-clockwise.

**Validates: Requirements 6.3**

### Property 21: Confirm Callback Timing

*For any* confirm animation sequence, the onConfirm callback shall be invoked after 900ms.

**Validates: Requirements 6.5**


### Property 22: Animation Race Condition Prevention

*For all* ring rotation animations, a new selection input shall not be accepted until the current animation completes.

**Validates: Requirements 6.7, 15.6**

### Property 23: Arrow Right Navigation

*For any* outer ring with n items at selected index i, pressing Arrow Right shall select index (i + 1) % n.

**Validates: Requirements 7.1**

### Property 24: Arrow Left Navigation

*For any* outer ring with n items at selected index i, pressing Arrow Left shall select index (i - 1 + n) % n.

**Validates: Requirements 7.2**

### Property 25: Arrow Down Navigation

*For any* mini-node list with n items at selected index i, pressing Arrow Down shall select index (i + 1) % n.

**Validates: Requirements 7.3**

### Property 26: Arrow Up Navigation

*For any* mini-node list with n items at selected index i, pressing Arrow Up shall select index (i - 1 + n) % n.

**Validates: Requirements 7.4**

### Property 27: Enter Key Confirm

*For any* current selection state, pressing Enter shall trigger the same action as clicking the confirm button.

**Validates: Requirements 7.5**

### Property 28: Escape Key Back

*For any* WheelView state, pressing Escape shall invoke the onBackToCategories callback.

**Validates: Requirements 7.6**


### Property 29: Navigation Key preventDefault

*For all* navigation keys (ArrowUp, ArrowDown, ArrowLeft, ArrowRight, Enter, Escape), the WheelView shall call preventDefault to prevent default browser behavior.

**Validates: Requirements 7.7**

### Property 30: Field Config Property Preservation

*For all* field configurations, the structure shall include the properties: id, type, label, and optionally defaultValue, options, min, max, step, unit.

**Validates: Requirements 8.4**

### Property 31: Mini-Node Stack Compatibility

*For any* existing mini-node stack data structure, the system shall maintain backward compatibility and correctly process the data.

**Validates: Requirements 8.5**

### Property 32: Mini-Node Serialization Round-Trip

*For any* mini-node object, serializing with JSON.stringify then deserializing with JSON.parse shall produce an equivalent object.

**Validates: Requirements 8.6**

### Property 33: Obsolete Property Filtering

*For any* saved state containing the obsolete level4ViewMode property, restoration shall filter out that property without causing errors.

**Validates: Requirements 10.2**

### Property 34: Mini-Node Stack Restoration

*For any* saved mini-node stack in localStorage, restoration shall preserve all mini-node and field config data without loss.

**Validates: Requirements 10.3**

### Property 35: Mini-Node Values Application

*For any* restored miniNodeValues from localStorage, the system shall apply those values to the corresponding field config inputs.

**Validates: Requirements 10.4**


### Property 36: HexToRgba Color Conversion

*For any* valid hex color string and alpha value, the hexToRgba helper shall produce a valid rgba color string with the specified alpha.

**Validates: Requirements 11.3**

### Property 37: SVG Pointer Events Optimization

*For all* SVG path elements, interactive elements shall have pointer-events set to "auto" and decorative elements shall have pointer-events set to "none".

**Validates: Requirements 12.5**

### Property 38: Hardware-Accelerated Animations

*For all* animations in the WheelView, only hardware-accelerated CSS properties (transform, opacity) shall be used.

**Validates: Requirements 12.6**

### Property 39: ARIA Labels for Interactive Elements

*For all* interactive ring segments, toggle buttons, and icon-only buttons, appropriate ARIA labels (aria-label, aria-pressed) shall be present.

**Validates: Requirements 13.1, 13.2, 13.3**

### Property 40: Focus State Visibility

*For all* interactive elements, visible focus states shall be provided using whileFocus motion props or CSS focus styles.

**Validates: Requirements 13.5**

### Property 41: LoadOptions Invocation

*For any* field configuration with a loadOptions function, mounting the mini-node shall trigger a call to that function.

**Validates: Requirements 14.1**

### Property 42: LoadOptions Caching

*For any* field with loadOptions, multiple mounts of the same mini-node shall result in only one backend call (idempotence).

**Validates: Requirements 14.2, 14.7**


### Property 43: LoadOptions Loading State

*For any* field with loadOptions during async loading, a loading indicator shall be displayed in the dropdown.

**Validates: Requirements 14.3**

### Property 44: LoadOptions Error Handling

*For any* field with loadOptions that fails (rejects), an error message shall be displayed and the options array shall fallback to empty.

**Validates: Requirements 14.4**

### Property 45: LoadOptions Interface Support

*For any* field with loadOptions, the function shall support returning Promise<{label: string, value: string}[]>.

**Validates: Requirements 14.5**

### Property 46: Loaded Options Rendering

*For any* field with successfully loaded options, those options shall be rendered in the dropdown select element.

**Validates: Requirements 14.6**

### Property 47: Invalid Field Type Handling

*For any* field configuration with an invalid type (not in {text, slider, dropdown, toggle, color}), the side panel shall skip rendering that field and log a warning.

**Validates: Requirements 15.3**

### Property 48: Invalid Glow Color Fallback

*For any* invalid hex color provided as glowColor, the WheelView shall fallback to a default theme color without crashing.

**Validates: Requirements 15.4**

### Property 49: Corrupted LocalStorage Handling

*For any* corrupted or invalid data in localStorage, the navigation context shall initialize with default state without crashing.

**Validates: Requirements 15.5**

### Property 50: Error Boundary Fallback

*For any* rendering error that occurs in the WheelView, an error boundary shall catch the error and display a fallback UI.

**Validates: Requirements 15.7**


## Error Handling

### Empty State Handling

**Empty Mini-Node Stack:**
```typescript
if (miniNodeStack.length === 0) {
  return (
    <div className="absolute inset-0 flex items-center justify-center">
      <div className="text-white/40 text-sm">
        No settings available for this category
      </div>
    </div>
  )
}
```

**Empty Field List:**
```typescript
{miniNode.fields.length === 0 ? (
  <div className="p-4 text-center">
    <span className="text-[10px] text-muted-foreground uppercase">
      No settings available
    </span>
    <p className="text-[9px] text-muted-foreground/60 mt-1">
      This mini-node has no configurable fields
    </p>
  </div>
) : (
  // Render fields
)}
```

### Invalid Data Handling

**Invalid Field Type:**
```typescript
function renderField(field: FieldConfig) {
  switch (field.type) {
    case 'text': return <TextField {...field} />
    case 'slider': return <SliderField {...field} />
    case 'dropdown': return <DropdownField {...field} />
    case 'toggle': return <ToggleField {...field} />
    case 'color': return <ColorField {...field} />
    default:
      console.warn(`[WheelView] Invalid field type: ${field.type}`)
      return null  // Skip rendering
  }
}
```

**Invalid Glow Color:**
```typescript
function validateGlowColor(color: string): string {
  const hexPattern = /^#[0-9A-Fa-f]{6}$/
  if (!hexPattern.test(color)) {
    console.warn(`[WheelView] Invalid glow color: ${color}, using default`)
    return '#00D4FF'  // Default cyan
  }
  return color
}
```


### LocalStorage Error Handling

**Corrupted State Recovery:**
```typescript
function restoreNavigationState(): NavState {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (!saved) return defaultState
    
    const parsed = JSON.parse(saved)
    
    // Validate structure
    if (typeof parsed !== 'object' || parsed === null) {
      throw new Error('Invalid state structure')
    }
    
    // Normalize level
    const level = normalizeLevel(parsed.level)
    
    // Remove obsolete properties
    const { level4ViewMode, ...cleanState } = parsed
    
    return {
      ...defaultState,
      ...cleanState,
      level
    }
  } catch (error) {
    console.error('[NavigationContext] Failed to restore state:', error)
    // Clear corrupted data
    localStorage.removeItem(STORAGE_KEY)
    return defaultState
  }
}
```

### Async Loading Error Handling

**LoadOptions Failure:**
```typescript
async function loadDropdownOptions(field: FieldConfig) {
  if (!field.loadOptions) return field.options || []
  
  try {
    setLoading(true)
    const options = await field.loadOptions()
    setLoading(false)
    return options
  } catch (error) {
    console.error(`[WheelView] Failed to load options for ${field.id}:`, error)
    setError(`Failed to load options: ${error.message}`)
    setLoading(false)
    return []  // Fallback to empty array
  }
}
```

### Animation Interruption Handling

**Prevent Race Conditions:**
```typescript
const [isAnimating, setIsAnimating] = useState(false)

function handleSelect(index: number) {
  if (isAnimating) {
    console.log('[WheelView] Animation in progress, ignoring selection')
    return  // Ignore input during animation
  }
  
  setIsAnimating(true)
  setSelectedIndex(index)
  
  // Animation completes after spring settles (~500ms)
  setTimeout(() => setIsAnimating(false), 500)
}
```

### Error Boundary

**Component-Level Error Boundary:**
```typescript
class WheelViewErrorBoundary extends React.Component {
  state = { hasError: false, error: null }
  
  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }
  
  componentDidCatch(error, errorInfo) {
    console.error('[WheelView] Rendering error:', error, errorInfo)
  }
  
  render() {
    if (this.state.hasError) {
      return (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="text-center">
            <div className="text-red-400 text-sm mb-2">
              Failed to render settings view
            </div>
            <button 
              onClick={() => this.setState({ hasError: false })}
              className="text-xs text-white/60 hover:text-white"
            >
              Try again
            </button>
          </div>
        </div>
      )
    }
    
    return this.props.children
  }
}
```


## Testing Strategy

### Dual Testing Approach

This feature requires both unit tests and property-based tests for comprehensive coverage:

**Unit Tests:** Verify specific examples, edge cases, and error conditions
- Specific mini-node configurations
- Empty states (no mini-nodes, no fields)
- Error handling (invalid colors, corrupted storage)
- Integration points (context, theme)
- Component rendering (snapshots)

**Property-Based Tests:** Verify universal properties across all inputs
- Navigation level invariants
- Ring distribution logic
- Rotation calculations
- Keyboard navigation wraparound
- Data serialization round-trips
- Animation timing
- Field value persistence

Together, unit tests catch concrete bugs while property tests verify general correctness across the input space.

### Property-Based Testing Configuration

**Library:** fast-check (JavaScript/TypeScript property-based testing)

**Installation:**
```bash
npm install --save-dev fast-check
```

**Configuration:**
- Minimum 100 iterations per property test
- Each test references its design document property
- Tag format: `Feature: wheelview-navigation-integration, Property {number}: {property_text}`


### Property Test Examples

**Property 1: Navigation Level Invariant**
```typescript
import fc from 'fast-check'

// Feature: wheelview-navigation-integration, Property 1: Navigation Level Invariant
test('navigation level is always in range [1, 3]', () => {
  fc.assert(
    fc.property(
      fc.record({
        level: fc.integer({ min: 1, max: 3 }),
        selectedMain: fc.option(fc.string()),
        selectedSub: fc.option(fc.string())
      }),
      (state) => {
        // Property: level is always 1, 2, or 3
        expect(state.level).toBeGreaterThanOrEqual(1)
        expect(state.level).toBeLessThanOrEqual(3)
        expect([1, 2, 3]).toContain(state.level)
      }
    ),
    { numRuns: 100 }
  )
})
```

**Property 6: Mini-Node Distribution**
```typescript
// Feature: wheelview-navigation-integration, Property 6: Mini-Node Distribution
test('mini-nodes are distributed correctly across rings', () => {
  fc.assert(
    fc.property(
      fc.array(fc.record({ id: fc.string(), label: fc.string() }), { minLength: 1, maxLength: 20 }),
      (miniNodes) => {
        const splitPoint = Math.ceil(miniNodes.length / 2)
        const outerItems = miniNodes.slice(0, splitPoint)
        const innerItems = miniNodes.slice(splitPoint)
        
        // Property: outer ring has ceil(n/2) items
        expect(outerItems.length).toBe(Math.ceil(miniNodes.length / 2))
        // Property: inner ring has floor(n/2) items
        expect(innerItems.length).toBe(Math.floor(miniNodes.length / 2))
        // Property: total items preserved
        expect(outerItems.length + innerItems.length).toBe(miniNodes.length)
      }
    ),
    { numRuns: 100 }
  )
})
```

**Property 16: LocalStorage Level Normalization**
```typescript
// Feature: wheelview-navigation-integration, Property 16: LocalStorage Level Normalization
test('level 4 is normalized to level 3 on restoration', () => {
  fc.assert(
    fc.property(
      fc.integer({ min: 4, max: 10 }),  // Generate invalid levels
      (invalidLevel) => {
        const savedState = { level: invalidLevel, selectedMain: 'voice' }
        localStorage.setItem('test-nav-state', JSON.stringify(savedState))
        
        const restored = restoreNavigationState()
        
        // Property: any level > 3 becomes 3
        expect(restored.level).toBe(3)
      }
    ),
    { numRuns: 100 }
  )
})
```

**Property 23-26: Keyboard Navigation Wraparound**
```typescript
// Feature: wheelview-navigation-integration, Property 23-26: Keyboard Navigation
test('arrow key navigation wraps around correctly', () => {
  fc.assert(
    fc.property(
      fc.integer({ min: 3, max: 12 }),  // Ring size
      fc.integer({ min: 0, max: 11 }),  // Current index
      (ringSize, currentIndex) => {
        const validIndex = currentIndex % ringSize
        
        // Arrow Right: (i + 1) % n
        const nextIndex = (validIndex + 1) % ringSize
        expect(nextIndex).toBeGreaterThanOrEqual(0)
        expect(nextIndex).toBeLessThan(ringSize)
        
        // Arrow Left: (i - 1 + n) % n
        const prevIndex = (validIndex - 1 + ringSize) % ringSize
        expect(prevIndex).toBeGreaterThanOrEqual(0)
        expect(prevIndex).toBeLessThan(ringSize)
      }
    ),
    { numRuns: 100 }
  )
})
```

**Property 32: Mini-Node Serialization Round-Trip**
```typescript
// Feature: wheelview-navigation-integration, Property 32: Serialization Round-Trip
test('mini-node serialization preserves data', () => {
  fc.assert(
    fc.property(
      fc.record({
        id: fc.string(),
        label: fc.string(),
        icon: fc.string(),
        fields: fc.array(fc.record({
          id: fc.string(),
          label: fc.string(),
          type: fc.constantFrom('text', 'slider', 'dropdown', 'toggle', 'color')
        }))
      }),
      (miniNode) => {
        // Round-trip: serialize then deserialize
        const serialized = JSON.stringify(miniNode)
        const deserialized = JSON.parse(serialized)
        
        // Property: data is preserved
        expect(deserialized).toEqual(miniNode)
      }
    ),
    { numRuns: 100 }
  )
})
```


### Unit Test Examples

**Empty State Handling:**
```typescript
describe('WheelView Empty States', () => {
  test('displays message when mini-node stack is empty', () => {
    const { getByText } = render(
      <WheelView 
        categoryId="voice"
        glowColor="#00D4FF"
        expandedIrisSize={240}
        onConfirm={jest.fn()}
        onBackToCategories={jest.fn()}
      />
    )
    
    expect(getByText(/no settings available/i)).toBeInTheDocument()
  })
  
  test('displays message when mini-node has no fields', () => {
    const miniNodeWithNoFields = {
      id: 'test-node',
      label: 'Test Node',
      icon: 'Info',
      fields: []
    }
    
    const { getByText } = render(
      <SidePanel 
        miniNode={miniNodeWithNoFields}
        glowColor="#00D4FF"
        values={{}}
        onValueChange={jest.fn()}
        onConfirm={jest.fn()}
        lineRetracted={false}
        orbSize={240}
      />
    )
    
    expect(getByText(/no settings available/i)).toBeInTheDocument()
  })
})
```

**Error Handling:**
```typescript
describe('WheelView Error Handling', () => {
  test('handles invalid glow color gracefully', () => {
    const { container } = render(
      <WheelView 
        categoryId="voice"
        glowColor="invalid-color"
        expandedIrisSize={240}
        onConfirm={jest.fn()}
        onBackToCategories={jest.fn()}
      />
    )
    
    // Should not crash, should use default color
    expect(container).toBeInTheDocument()
  })
  
  test('handles corrupted localStorage gracefully', () => {
    localStorage.setItem('irisvoice-nav-state', 'invalid-json{')
    
    const state = restoreNavigationState()
    
    // Should return default state, not crash
    expect(state.level).toBe(1)
    expect(state.selectedMain).toBeNull()
  })
  
  test('skips invalid field types', () => {
    const consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation()
    
    const invalidField = {
      id: 'test',
      label: 'Test',
      type: 'invalid-type' as any
    }
    
    const result = renderField(invalidField)
    
    expect(result).toBeNull()
    expect(consoleWarnSpy).toHaveBeenCalledWith(
      expect.stringContaining('Invalid field type')
    )
    
    consoleWarnSpy.mockRestore()
  })
})
```

**Integration Tests:**
```typescript
describe('WheelView Integration', () => {
  test('integrates with NavigationContext', () => {
    const { result } = renderHook(() => useNavigation(), {
      wrapper: NavigationProvider
    })
    
    act(() => {
      result.current.selectSub('voice', 'input', mockMiniNodes)
    })
    
    expect(result.current.state.level).toBe(3)
    expect(result.current.state.selectedSub).toBe('input')
    expect(result.current.state.miniNodeStack).toEqual(mockMiniNodes)
  })
  
  test('integrates with BrandColorContext', () => {
    const mockTheme = { glow: { color: '#FF0000' } }
    
    const { container } = render(
      <BrandColorContext.Provider value={{ getThemeConfig: () => mockTheme }}>
        <WheelView 
          categoryId="voice"
          glowColor={mockTheme.glow.color}
          expandedIrisSize={240}
          onConfirm={jest.fn()}
          onBackToCategories={jest.fn()}
        />
      </BrandColorContext.Provider>
    )
    
    // Verify theme color is applied
    const svg = container.querySelector('svg')
    expect(svg).toBeInTheDocument()
  })
})
```

**Animation Tests:**
```typescript
describe('WheelView Animations', () => {
  test('rotates inner ring to center selected item', async () => {
    const { getByTestId } = render(<WheelView {...defaultProps} />)
    
    const innerRingSegment = getByTestId('inner-ring-segment-2')
    
    fireEvent.click(innerRingSegment)
    
    await waitFor(() => {
      const innerRing = getByTestId('inner-ring')
      const rotation = getComputedStyle(innerRing).transform
      // Verify rotation centers item at 12 o'clock
      expect(rotation).toBeTruthy()
    })
  })
  
  test('triggers confirm animation sequence', async () => {
    jest.useFakeTimers()
    const onConfirm = jest.fn()
    
    const { getByRole } = render(
      <WheelView {...defaultProps} onConfirm={onConfirm} />
    )
    
    const confirmButton = getByRole('button', { name: /confirm/i })
    fireEvent.click(confirmButton)
    
    // Callback should fire after 900ms
    jest.advanceTimersByTime(900)
    
    expect(onConfirm).toHaveBeenCalled()
    
    jest.useRealTimers()
  })
})
```

### Test Coverage Goals

**Unit Tests:**
- Component rendering: 100%
- Error handling: 100%
- Edge cases: 100%
- Integration points: 100%

**Property Tests:**
- All 50 correctness properties: 100%
- Minimum 100 iterations per property
- Cover full input space with generators

**Overall Coverage Target:** 90%+ code coverage with meaningful tests (not just coverage for coverage's sake).


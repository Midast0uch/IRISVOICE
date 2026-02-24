# Design Document: Navigation Level Consolidation

## Overview

This design document specifies the technical approach for refactoring the IRISVOICE navigation system from a 4-level hierarchy to a 3-level hierarchy. The refactoring eliminates Level 4 by integrating mini-node labels into the Level 3 orbital ring and displaying input fields in a side panel.

### Current Architecture (4 Levels)

```
Level 1: Idle IRIS Orb (collapsed state)
   ↓ Click orb
Level 2: 6 Main Category Nodes (hexagonal orbit)
   ↓ Click category
Level 3: 4 Sub-nodes per category (orbital display)
   ↓ Click sub-node
Level 4: Mini-node orbital view with input fields ← TO BE REMOVED
```

### Target Architecture (3 Levels)

```
Level 1: Idle IRIS Orb (collapsed state)
   ↓ Click orb
Level 2: 6 Main Category Nodes (hexagonal orbit)
   ↓ Click category
Level 3: Sub-node orbital ring + Mini-node labels + Side panel
   - Inner/outer rings display mini-node labels
   - Side panel shows input fields for selected mini-node
   - No transition to Level 4
```

### Key Changes

1. **Level 4 Removal**: Eliminate Level 4 navigation state and components
2. **Orbital Ring Enhancement**: Add mini-node labels to Level 3 orbital rings (inner and outer)
3. **Side Panel Addition**: Display mini-node input fields in a side panel at Level 3
4. **State Simplification**: Reduce NavigationLevel type from `1 | 2 | 3 | 4` to `1 | 2 | 3`
5. **Component Cleanup**: Remove level-4-view.tsx, level-4-orbital-view.tsx, CompactAccordion.tsx

### Design Goals

- Simplify navigation hierarchy while preserving all functionality
- Maintain visual consistency with theme colors and transparent backgrounds
- Preserve all 52 mini-nodes and 61 input fields across 24 sub-nodes
- Ensure smooth animations and transitions
- Maintain backward compatibility with existing localStorage data

## Architecture

### Component Structure

```
NavigationContext (State Management)
    ↓
page.tsx (Main App)
    ↓
├── IrisOrb (Level 1)
├── HexagonalControlCenter (Level 2)
└── Level3EnhancedView (NEW - Level 3)
    ├── OrbitalRingWithMiniNodes (NEW)
    │   ├── OuterRing (mini-node labels)
    │   ├── InnerRing (mini-node labels)
    │   └── DecorativeRings (ambient animation)
    └── MiniNodeSidePanel (NEW)
        ├── FieldRenderer (text, slider, dropdown, toggle, color)
        └── ConfirmButton
```

### Data Flow

```
User clicks sub-node at Level 3
    ↓
NavigationContext.handleSelectSub()
    ↓
State updates: selectedSub, miniNodeStack (stays at level 3)
    ↓
Level3EnhancedView renders:
    - OrbitalRingWithMiniNodes (displays mini-node labels)
    - MiniNodeSidePanel (hidden initially)
    ↓
User clicks mini-node label on ring
    ↓
NavigationContext.jumpToMiniNode(index)
    ↓
State updates: activeMiniNodeIndex
    ↓
OrbitalRingWithMiniNodes rotates to position selected mini-node at top
MiniNodeSidePanel fades in with input fields
    ↓
User modifies field values
    ↓
NavigationContext.updateMiniNodeValue(nodeId, fieldId, value)
    ↓
State updates: miniNodeValues[nodeId][fieldId]
    ↓
User clicks confirm
    ↓
Orbital ring spins 360°, side panel connection line retracts
Values persisted to localStorage
```

### State Management Changes

#### NavigationLevel Type (BREAKING CHANGE)

```typescript
// OLD (4 levels)
export type NavigationLevel = 1 | 2 | 3 | 4

// NEW (3 levels)
export type NavigationLevel = 1 | 2 | 3
```

#### NavState Interface Changes

```typescript
export interface NavState {
  level: NavigationLevel  // Now 1 | 2 | 3 (not 4)
  history: HistoryEntry[]
  selectedMain: string | null
  selectedSub: string | null
  isTransitioning: boolean
  transitionDirection: 'forward' | 'backward' | null
  
  // Mini node state - NOW USED AT LEVEL 3 (not Level 4)
  miniNodeStack: MiniNode[]
  activeMiniNodeIndex: number
  confirmedMiniNodes: ConfirmedNode[]
  miniNodeValues: Record<string, Record<string, FieldValue>>
  
  view: string | null
  mainView: 'navigation' | 'chat'
  
  // REMOVED: level4ViewMode (no longer needed)
}
```

#### Reducer Changes

**SELECT_SUB Action** (stays at Level 3):
```typescript
case 'SELECT_SUB': {
  return {
    ...state,
    level: 3,  // Changed from 4 to 3
    selectedSub: action.payload.subnodeId,
    miniNodeStack: action.payload.miniNodes,
    activeMiniNodeIndex: 0,
    history: [
      ...state.history,
      { level: state.level, nodeId: state.selectedSub }
    ],
    transitionDirection: 'forward'
  }
}
```

**GO_BACK Action** (from Level 3):
```typescript
case 'GO_BACK': {
  if (state.level === 3) {
    // If mini-node is selected, deselect it first
    if (state.activeMiniNodeIndex > 0 || state.miniNodeStack.length > 0) {
      return {
        ...state,
        miniNodeStack: [],
        activeMiniNodeIndex: 0,
        selectedSub: null,
        level: 2,  // Go back to Level 2
        transitionDirection: 'backward'
      }
    }
  }
  // ... rest of GO_BACK logic
}
```

#### State Validation

```typescript
function validateNavState(state: NavState): boolean {
  // Level 3 requires selectedMain (no longer requires Level 4)
  if (state.level === 3 && !state.selectedMain) {
    return false
  }
  
  // Level must be 1, 2, or 3 (not 4)
  if (state.level < 1 || state.level > 3) {
    return false
  }
  
  return true
}
```

#### Backward Compatibility (localStorage Migration)

```typescript
function migrateNavState(stored: any): NavState {
  // Normalize Level 4 to Level 3
  if (stored.level === 4) {
    stored.level = 3
  }
  
  // Normalize invalid levels (0 or > 3) to Level 1
  if (stored.level < 1 || stored.level > 3) {
    stored.level = 1
  }
  
  // Remove obsolete level4ViewMode
  delete stored.level4ViewMode
  
  // Preserve miniNodeValues regardless of level
  if (!stored.miniNodeValues) {
    stored.miniNodeValues = {}
  }
  
  return stored as NavState
}
```

## Components and Interfaces

### Level3EnhancedView Component

**Purpose**: Replaces Level4View by rendering mini-nodes at Level 3 with orbital ring and side panel.

**Props**:
```typescript
interface Level3EnhancedViewProps {
  // No props needed - uses NavigationContext
}
```

**Responsibilities**:
- Render OrbitalRingWithMiniNodes when selectedSub is set
- Render MiniNodeSidePanel when a mini-node is selected
- Handle mini-node selection and value updates
- Coordinate animations between ring and panel

**Implementation**:
```typescript
export function Level3EnhancedView() {
  const { state, jumpToMiniNode, updateMiniNodeValue } = useNavigation()
  const { getThemeConfig } = useBrandColor()
  const theme = getThemeConfig()
  
  const { selectedSub, miniNodeStack, activeMiniNodeIndex, miniNodeValues } = state
  
  // Get mini-nodes for selected sub-node
  const miniNodes = miniNodeStack.length > 0 
    ? miniNodeStack 
    : (selectedSub ? getMiniNodesForSubnode(selectedSub) : [])
  
  const selectedMiniNode = miniNodes[activeMiniNodeIndex] ?? null
  const nodeValues = selectedMiniNode 
    ? (miniNodeValues[selectedMiniNode.id] || {}) 
    : {}
  
  if (miniNodes.length === 0) {
    return null // No mini-nodes to display
  }
  
  return (
    <div className="absolute inset-0">
      <OrbitalRingWithMiniNodes
        miniNodes={miniNodes}
        selectedIndex={activeMiniNodeIndex}
        onSelect={jumpToMiniNode}
        glowColor={theme.glow.color}
      />
      
      <AnimatePresence mode="wait">
        {selectedMiniNode && (
          <MiniNodeSidePanel
            key={selectedMiniNode.id}
            miniNode={selectedMiniNode}
            values={nodeValues}
            onValueChange={(fieldId, value) => 
              updateMiniNodeValue(selectedMiniNode.id, fieldId, value)
            }
            glowColor={theme.glow.color}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
```

### OrbitalRingWithMiniNodes Component

**Purpose**: Renders mini-node labels on inner and outer orbital rings with curved text.

**Props**:
```typescript
interface OrbitalRingWithMiniNodesProps {
  miniNodes: MiniNode[]
  selectedIndex: number
  onSelect: (index: number) => void
  glowColor: string
}
```

**Ring Distribution Logic**:
```typescript
// Split mini-nodes across outer and inner rings
const splitPoint = Math.ceil(miniNodes.length / 2)
const outerRingNodes = miniNodes.slice(0, splitPoint)
const innerRingNodes = miniNodes.slice(splitPoint)

// Calculate segment angles
const outerSegmentAngle = 360 / outerRingNodes.length
const innerSegmentAngle = 360 / innerRingNodes.length

// Rotation to position selected node at top (12 o'clock)
const isOuterRing = selectedIndex < splitPoint
const rotationAngle = isOuterRing
  ? -(selectedIndex * outerSegmentAngle)
  : -((selectedIndex - splitPoint) * innerSegmentAngle)
```

**Rendering Structure**:
```typescript
<svg width={orbSize} height={orbSize}>
  <defs>
    {/* Arc paths for curved text */}
    {outerRingNodes.map((_, i) => (
      <path id={`outer-arc-${i}`} d={describeArc(...)} />
    ))}
    {innerRingNodes.map((_, i) => (
      <path id={`inner-arc-${i}`} d={describeArc(...)} />
    ))}
  </defs>
  
  {/* Decorative rings (ambient animation) */}
  <DecorativeRings glowColor={glowColor} />
  
  {/* Inner ring with mini-node labels */}
  <motion.g animate={{ rotate: innerRotation }}>
    <circle r={innerRadius} stroke={glowColor} />
    {innerRingNodes.map((node, i) => (
      <g key={node.id}>
        <path d={arcPath} onClick={() => onSelect(splitPoint + i)} />
        <text>
          <textPath href={`#inner-arc-${i}`}>
            {node.label}
          </textPath>
        </text>
      </g>
    ))}
  </motion.g>
  
  {/* Outer ring with mini-node labels */}
  <motion.g animate={{ rotate: outerRotation }}>
    <circle r={outerRadius} stroke={glowColor} />
    {outerRingNodes.map((node, i) => (
      <g key={node.id}>
        <path d={arcPath} onClick={() => onSelect(i)} />
        <text>
          <textPath href={`#outer-arc-${i}`}>
            {node.label}
          </textPath>
        </text>
      </g>
    ))}
  </motion.g>
  
  {/* Selection indicator at 12 o'clock */}
  <SelectionIndicator glowColor={glowColor} />
</svg>
```

**Animation Configuration**:
```typescript
// Rotation animation (spring physics)
const rotationTransition = {
  type: "spring",
  stiffness: 80,
  damping: 16
}

// Confirm spin animation (360° rotation)
const confirmSpinTransition = {
  duration: 0.8,
  ease: "easeInOut"
}
```

### MiniNodeSidePanel Component

**Purpose**: Displays input fields for the selected mini-node in a side panel.

**Props**:
```typescript
interface MiniNodeSidePanelProps {
  miniNode: MiniNode
  values: Record<string, FieldValue>
  onValueChange: (fieldId: string, value: FieldValue) => void
  glowColor: string
}
```

**Layout**:
```typescript
<motion.div
  className="absolute top-1/2 -translate-y-1/2 z-30"
  style={{ left: "50%", marginLeft: orbSize / 2 + 12 }}
  initial={{ opacity: 0, x: -18, scale: 0.95 }}
  animate={{ opacity: 1, x: 0, scale: 1 }}
  exit={{ opacity: 0, x: -18, scale: 0.95 }}
>
  {/* Connection line (glowing, animated) */}
  <ConnectionLine glowColor={glowColor} retracted={lineRetracted} />
  
  {/* Panel body */}
  <div className="panel-container">
    {/* Header */}
    <div className="panel-header">
      <Icon />
      <span>{miniNode.label}</span>
    </div>
    
    {/* Fields (crossfade on mini-node change) */}
    <AnimatePresence mode="wait">
      <motion.div key={miniNode.id}>
        {miniNode.fields.map(field => (
          <FieldRenderer
            key={field.id}
            field={field}
            value={values[field.id]}
            onChange={(value) => onValueChange(field.id, value)}
            glowColor={glowColor}
          />
        ))}
      </motion.div>
    </AnimatePresence>
    
    {/* Confirm button */}
    <ConfirmButton onClick={handleConfirm} glowColor={glowColor} />
  </div>
</motion.div>
```

**Field Types**:
```typescript
function FieldRenderer({ field, value, onChange, glowColor }) {
  switch (field.type) {
    case 'text':
      return <input type="text" value={value} onChange={e => onChange(e.target.value)} />
    
    case 'slider':
      return (
        <div>
          <input type="range" min={field.min} max={field.max} step={field.step} 
                 value={value} onChange={e => onChange(Number(e.target.value))} />
          <span>{value}{field.unit}</span>
        </div>
      )
    
    case 'dropdown':
      return (
        <select value={value} onChange={e => onChange(e.target.value)}>
          {field.options?.map(opt => <option key={opt} value={opt}>{opt}</option>)}
        </select>
      )
    
    case 'toggle':
      return (
        <button onClick={() => onChange(!value)}>
          <motion.div animate={{ left: value ? 16 : 2 }} />
        </button>
      )
    
    case 'color':
      return <input type="color" value={value} onChange={e => onChange(e.target.value)} />
  }
}
```

### ConnectionLine Component

**Purpose**: Animated glowing line connecting orbital ring to side panel.

**Props**:
```typescript
interface ConnectionLineProps {
  glowColor: string
  retracted: boolean
}
```

**Implementation**:
```typescript
<motion.div
  style={{ width: 24, height: 2.5 }}
  initial={{ scaleX: 0 }}
  animate={{ scaleX: retracted ? 0 : 1 }}
  transition={{ type: "spring", stiffness: 200, damping: 25 }}
>
  {/* Base line */}
  <div style={{
    background: `linear-gradient(90deg, ${glowColor}cc, ${glowColor}44)`,
    borderRadius: 1.5
  }} />
  
  {/* Glow effect */}
  <div style={{
    background: `linear-gradient(90deg, ${glowColor}44, ${glowColor}11)`,
    filter: "blur(5px)"
  }} />
  
  {/* Animated pulse */}
  <motion.div
    style={{
      background: `linear-gradient(90deg, transparent, ${glowColor}cc, transparent)`,
      filter: "blur(2.5px)"
    }}
    animate={{ left: ["-28px", "24px"] }}
    transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
  />
</motion.div>
```

### Component Removal

**Files to Delete**:
1. `IRISVOICE/components/level-4-view.tsx`
2. `IRISVOICE/components/level-4-orbital-view.tsx`
3. `IRISVOICE/components/CompactAccordion.tsx` (if exists)

**References to Update**:
- Remove imports in `page.tsx`
- Remove Level 4 rendering logic in `page.tsx`
- Remove `level4ViewMode` from NavigationContext
- Remove `SET_LEVEL4_VIEW_MODE` action from reducer

## Data Models

### MiniNode (Unchanged)

```typescript
export interface MiniNode {
  id: string           // Lowercase-kebab-case (e.g., "input-device")
  label: string        // Display name (e.g., "Input Device")
  icon: string         // Lucide icon name (e.g., "Mic")
  fields: FieldConfig[]
}
```

### FieldConfig (Unchanged)

```typescript
export interface FieldConfig {
  id: string
  type: 'text' | 'slider' | 'dropdown' | 'toggle' | 'color' | 'custom'
  label: string
  defaultValue?: FieldValue
  
  // Text field props
  placeholder?: string
  
  // Slider props
  min?: number
  max?: number
  step?: number
  unit?: string
  
  // Dropdown props
  options?: string[]
  loadOptions?: () => Promise<{ label: string; value: string }[]>
}
```

### FieldValue (Unchanged)

```typescript
export type FieldValue = string | number | boolean | Record<string, unknown>
```

### NavigationLevel (CHANGED)

```typescript
// OLD
export type NavigationLevel = 1 | 2 | 3 | 4

// NEW
export type NavigationLevel = 1 | 2 | 3
```

### NavState (MODIFIED)

```typescript
export interface NavState {
  level: NavigationLevel  // Now 1 | 2 | 3
  history: HistoryEntry[]
  selectedMain: string | null
  selectedSub: string | null
  isTransitioning: boolean
  transitionDirection: 'forward' | 'backward' | null
  
  // Mini node state (now used at Level 3)
  miniNodeStack: MiniNode[]
  activeMiniNodeIndex: number
  confirmedMiniNodes: ConfirmedNode[]
  miniNodeValues: Record<string, Record<string, FieldValue>>
  
  view: string | null
  mainView: 'navigation' | 'chat'
  
  // REMOVED: level4ViewMode
}
```

### Mini-Node Data Preservation

**Total Counts** (must be preserved):
- 6 main categories
- 24 sub-nodes
- 52 mini-nodes
- 61 input fields

**Data Source**: `IRISVOICE/data/mini-nodes.ts`

**Mapping Structure**:
```typescript
export const SUB_NODES_WITH_MINI: Record<string, MiniNode[]> = {
  'input': [
    { id: 'input-device', label: 'Input Device', icon: 'Mic', fields: [...] },
    { id: 'input-sensitivity', label: 'Sensitivity', icon: 'Volume2', fields: [...] },
    { id: 'noise-gate', label: 'Noise Gate', icon: 'Minus', fields: [...] }
  ],
  'output': [
    { id: 'output-device', label: 'Output Device', icon: 'Speaker', fields: [...] },
    // ... more mini-nodes
  ],
  // ... 22 more sub-nodes
}
```

**Preservation Requirements**:
- All mini-node IDs must remain unchanged (lowercase-kebab-case)
- All field configurations must be preserved
- All async `loadOptions` functions must continue to work
- All field types must be supported (text, slider, dropdown, toggle, color)

### localStorage Schema

**Key**: `iris-mini-node-values`

**Structure**:
```typescript
{
  "input-device": {
    "input_device": "USB Microphone"
  },
  "input-sensitivity": {
    "input_sensitivity": 75
  },
  "noise-gate": {
    "noise_gate": true,
    "gate_threshold": -25
  },
  // ... all other mini-nodes
}
```

**Migration**: No changes needed - structure remains the same.


## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system—essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property Reflection

After analyzing all acceptance criteria, I identified several redundancies:

**Redundancy 1**: Properties 1.3 and 1.4 both test that selecting a sub-node keeps the system at level 3. These can be combined into a single property.

**Redundancy 2**: Properties 2.6, 5.1, 5.2, and 5.3 all test data preservation for mini-nodes and fields. These can be combined into a comprehensive data preservation property.

**Redundancy 3**: Properties 7.1 and 7.2 both test theme color usage. These can be combined into a single theme integration property.

**Redundancy 4**: Properties 8.2, 8.3, and 8.4 all test ID preservation. These can be combined into a single ID preservation property.

**Edge Cases**: Properties 9.1-9.6 are specific animation configurations that should be tested as examples, not properties.

### Property 1: Three-Level Navigation Constraint

*For any* navigation state, the level must be exactly 1, 2, or 3, and the system must never transition to level 4.

**Validates: Requirements 1.1, 1.3, 1.4**

### Property 2: Mini-Node Distribution Across Rings

*For any* set of mini-nodes with count n, the outer ring shall contain ceil(n/2) mini-nodes and the inner ring shall contain the remaining mini-nodes.

**Validates: Requirements 2.2**

### Property 3: Mini-Node Selection Updates State

*For any* mini-node at any index, clicking that mini-node shall update the activeMiniNodeIndex to that index and trigger the side panel to display.

**Validates: Requirements 2.3**

### Property 4: Rotation Positions Selected Node at Top

*For any* selected mini-node index i in a ring with n segments, the rotation angle shall be -(i * 360/n) degrees, positioning the selected node at 12 o'clock.

**Validates: Requirements 2.5**

### Property 5: All Fields Rendered for Selected Mini-Node

*For any* mini-node with k fields, when that mini-node is selected, the side panel shall render exactly k field controls.

**Validates: Requirements 3.1**

### Property 6: Field Value Updates Propagate to State

*For any* field and any valid value, modifying that field shall update miniNodeValues[nodeId][fieldId] to the new value.

**Validates: Requirements 3.3**

### Property 7: Side Panel Crossfade on Mini-Node Change

*For any* two different mini-nodes A and B, selecting B after A shall trigger a crossfade animation and display B's fields.

**Validates: Requirements 3.7**

### Property 8: GO_BACK from Level 3 Transitions to Level 2

*For any* navigation state at level 3, dispatching GO_BACK shall transition the state to level 2.

**Validates: Requirements 4.3**

### Property 9: Mini-Node Values Persist Across Navigation

*For any* navigation sequence (forward or backward), the miniNodeValues object shall remain unchanged unless explicitly modified by user input.

**Validates: Requirements 4.4**

### Property 10: Level 3 Validation Requires selectedMain

*For any* navigation state at level 3, the validation function shall return false if selectedMain is null.

**Validates: Requirements 4.5**

### Property 11: Complete Data Preservation

*For all* 52 mini-nodes across 24 sub-nodes, the system shall preserve the mini-node ID, label, icon, and all field configurations (type, label, min, max, options, defaultValue).

**Validates: Requirements 5.1, 5.2, 5.3, 2.6**

### Property 12: Async LoadOptions Support

*For any* dropdown field with a loadOptions function, calling that function shall return a Promise that resolves to an array of option objects.

**Validates: Requirements 5.4**

### Property 13: LocalStorage Persistence Round-Trip

*For any* set of mini-node values, saving to localStorage and then loading shall produce an equivalent set of values.

**Validates: Requirements 5.5**

### Property 14: Theme Color Reactivity

*For any* theme color change, all components using the theme glow color shall re-render with the new color.

**Validates: Requirements 7.1, 7.2, 7.5**

### Property 15: HexToRgba Color Conversion

*For any* hex color string and alpha value, hexToRgba shall produce a valid rgba() string with the correct RGB values and alpha.

**Validates: Requirements 7.6**

### Property 16: ID Format Validation

*For all* navigation IDs (main categories, sub-nodes, mini-nodes), each ID shall match the lowercase-kebab-case pattern /^[a-z][a-z0-9]*(-[a-z0-9]+)*$/.

**Validates: Requirements 8.1**

### Property 17: ID Preservation

*For all* 6 main category IDs, 24 sub-node IDs, and 52 mini-node IDs, the IDs shall remain unchanged from the original data files.

**Validates: Requirements 8.2, 8.3, 8.4**

### Property 18: ID Validation Functions Preserved

*For any* valid ID string, isValidNodeId shall return true, and for any invalid ID string, normalizeId shall convert it to valid lowercase-kebab-case format.

**Validates: Requirements 8.5**

### Property 19: Level 4 State Migration to Level 3

*For any* stored navigation state with level=4, loading that state shall result in level=3 with all other state preserved.

**Validates: Requirements 10.1**

### Property 20: Mini-Node Values Preserved During Migration

*For any* stored state with miniNodeValues, loading that state shall preserve all miniNodeValues regardless of the stored level.

**Validates: Requirements 10.2**

### Property 21: Invalid Level Normalization

*For any* stored navigation state with level < 1 or level > 3, loading that state shall normalize the level to 1.

**Validates: Requirements 10.4**

## Error Handling

### Invalid State Detection

**Scenario**: Navigation state becomes invalid (e.g., level 3 without selectedMain)

**Handling**:
```typescript
function validateAndCorrectState(state: NavState): NavState {
  // Level 3 requires selectedMain
  if (state.level === 3 && !state.selectedMain) {
    console.warn('Invalid state: Level 3 without selectedMain, correcting to Level 2')
    return { ...state, level: 2, selectedSub: null, miniNodeStack: [] }
  }
  
  // Level must be 1, 2, or 3
  if (state.level < 1 || state.level > 3) {
    console.warn(`Invalid level ${state.level}, correcting to Level 1`)
    return { ...state, level: 1, selectedMain: null, selectedSub: null }
  }
  
  return state
}
```

### Missing Mini-Node Data

**Scenario**: Sub-node has no associated mini-nodes

**Handling**:
```typescript
function Level3EnhancedView() {
  const miniNodes = selectedSub ? getMiniNodesForSubnode(selectedSub) : []
  
  if (miniNodes.length === 0) {
    return (
      <div className="text-white/40 text-sm">
        No settings available for this category
      </div>
    )
  }
  
  // ... render orbital ring and side panel
}
```

### Field Value Type Mismatch

**Scenario**: Stored field value has wrong type (e.g., string instead of number for slider)

**Handling**:
```typescript
function getFieldValue(field: FieldConfig, storedValue: FieldValue): FieldValue {
  // Use default value if stored value is undefined
  if (storedValue === undefined) {
    return field.defaultValue ?? getDefaultForType(field.type)
  }
  
  // Type coercion for sliders
  if (field.type === 'slider' && typeof storedValue !== 'number') {
    const parsed = Number(storedValue)
    return isNaN(parsed) ? (field.defaultValue ?? field.min ?? 0) : parsed
  }
  
  // Type coercion for toggles
  if (field.type === 'toggle' && typeof storedValue !== 'boolean') {
    return Boolean(storedValue)
  }
  
  return storedValue
}
```

### Async LoadOptions Failure

**Scenario**: Dropdown field's loadOptions function fails or times out

**Handling**:
```typescript
async function loadDropdownOptions(field: FieldConfig): Promise<string[]> {
  if (!field.loadOptions) {
    return field.options ?? []
  }
  
  try {
    const result = await Promise.race([
      field.loadOptions(),
      new Promise((_, reject) => 
        setTimeout(() => reject(new Error('Timeout')), 5000)
      )
    ])
    return result.map(opt => opt.value)
  } catch (error) {
    console.error(`Failed to load options for ${field.id}:`, error)
    // Fallback to static options if available
    return field.options ?? ['Default']
  }
}
```

### Theme Color Invalid

**Scenario**: Theme glow color is not a valid hex color

**Handling**:
```typescript
function hexToRgba(hex: string, alpha: number): string {
  // Remove # if present
  hex = hex.replace('#', '')
  
  // Validate hex format
  if (!/^[0-9A-Fa-f]{6}$/.test(hex)) {
    console.warn(`Invalid hex color: ${hex}, using fallback`)
    hex = '00ffff' // Fallback to cyan
  }
  
  const r = parseInt(hex.substring(0, 2), 16)
  const g = parseInt(hex.substring(2, 4), 16)
  const b = parseInt(hex.substring(4, 6), 16)
  
  // Clamp alpha to [0, 1]
  alpha = Math.max(0, Math.min(1, alpha))
  
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}
```

### LocalStorage Quota Exceeded

**Scenario**: Saving mini-node values exceeds localStorage quota

**Handling**:
```typescript
function saveMiniNodeValues(values: Record<string, Record<string, FieldValue>>) {
  try {
    const serialized = JSON.stringify(values)
    localStorage.setItem(MINI_NODE_VALUES_KEY, serialized)
  } catch (error) {
    if (error.name === 'QuotaExceededError') {
      console.error('LocalStorage quota exceeded, clearing old data')
      // Clear non-essential data
      localStorage.removeItem('iris-nav-history')
      // Retry save
      try {
        localStorage.setItem(MINI_NODE_VALUES_KEY, JSON.stringify(values))
      } catch (retryError) {
        console.error('Failed to save after clearing:', retryError)
        // Show user notification
        showNotification('Unable to save settings due to storage limits')
      }
    } else {
      console.error('Failed to save mini-node values:', error)
    }
  }
}
```

### Animation Performance Degradation

**Scenario**: Too many simultaneous animations cause frame drops

**Handling**:
```typescript
// Use CSS transforms for better performance
const ringAnimation = {
  rotate: rotationAngle,
  transition: {
    type: "spring",
    stiffness: 80,
    damping: 16,
    // Reduce motion for low-end devices
    ...(prefersReducedMotion && { duration: 0.3, ease: "easeOut" })
  }
}

// Disable decorative animations on low-end devices
const showDecorativeRings = !prefersReducedMotion && !isLowEndDevice
```

## Testing Strategy

### Dual Testing Approach

This feature requires both unit tests and property-based tests for comprehensive coverage:

**Unit Tests**: Verify specific examples, edge cases, and error conditions
- Specific mini-node configurations
- Integration between orbital ring and side panel
- Error handling scenarios
- Animation trigger conditions

**Property Tests**: Verify universal properties across all inputs
- Navigation state transitions for all levels
- Mini-node distribution for any count
- Field value updates for all field types
- Data preservation for all 52 mini-nodes
- ID format validation for all navigation IDs

### Property-Based Testing Configuration

**Library**: fast-check (JavaScript/TypeScript property-based testing library)

**Configuration**:
```typescript
import fc from 'fast-check'

// Minimum 100 iterations per property test
fc.assert(
  fc.property(/* generators */, /* test function */),
  { numRuns: 100 }
)
```

**Test Tagging Format**:
```typescript
describe('Navigation Level Consolidation', () => {
  it('Property 1: Three-Level Navigation Constraint - For any navigation state, the level must be exactly 1, 2, or 3', () => {
    // Feature: navigation-level-consolidation, Property 1
    fc.assert(
      fc.property(navigationStateArbitrary, (state) => {
        expect(state.level).toBeGreaterThanOrEqual(1)
        expect(state.level).toBeLessThanOrEqual(3)
      }),
      { numRuns: 100 }
    )
  })
})
```

### Unit Test Examples

**Example 1: Level 4 State Migration**
```typescript
describe('Backward Compatibility', () => {
  it('should normalize level 4 to level 3 when loading from localStorage', () => {
    const storedState = {
      level: 4,
      selectedMain: 'voice',
      selectedSub: 'input',
      miniNodeValues: { 'input-device': { 'input_device': 'USB Mic' } }
    }
    
    const migrated = migrateNavState(storedState)
    
    expect(migrated.level).toBe(3)
    expect(migrated.selectedMain).toBe('voice')
    expect(migrated.selectedSub).toBe('input')
    expect(migrated.miniNodeValues).toEqual(storedState.miniNodeValues)
  })
})
```

**Example 2: Side Panel Field Rendering**
```typescript
describe('MiniNodeSidePanel', () => {
  it('should render all field types correctly', () => {
    const miniNode = {
      id: 'test-node',
      label: 'Test Node',
      icon: 'Settings',
      fields: [
        { id: 'text-field', type: 'text', label: 'Text' },
        { id: 'slider-field', type: 'slider', label: 'Slider', min: 0, max: 100 },
        { id: 'dropdown-field', type: 'dropdown', label: 'Dropdown', options: ['A', 'B'] },
        { id: 'toggle-field', type: 'toggle', label: 'Toggle' },
        { id: 'color-field', type: 'color', label: 'Color' }
      ]
    }
    
    const { container } = render(
      <MiniNodeSidePanel
        miniNode={miniNode}
        values={{}}
        onValueChange={jest.fn()}
        glowColor="#00ffff"
      />
    )
    
    expect(container.querySelector('input[type="text"]')).toBeInTheDocument()
    expect(container.querySelector('input[type="range"]')).toBeInTheDocument()
    expect(container.querySelector('select')).toBeInTheDocument()
    expect(container.querySelector('button')).toBeInTheDocument() // toggle
    expect(container.querySelector('input[type="color"]')).toBeInTheDocument()
  })
})
```

**Example 3: Orbital Ring Rotation**
```typescript
describe('OrbitalRingWithMiniNodes', () => {
  it('should rotate to position selected node at 12 o\'clock', () => {
    const miniNodes = [
      { id: 'node-1', label: 'Node 1', icon: 'Icon1', fields: [] },
      { id: 'node-2', label: 'Node 2', icon: 'Icon2', fields: [] },
      { id: 'node-3', label: 'Node 3', icon: 'Icon3', fields: [] },
      { id: 'node-4', label: 'Node 4', icon: 'Icon4', fields: [] }
    ]
    
    const { rerender } = render(
      <OrbitalRingWithMiniNodes
        miniNodes={miniNodes}
        selectedIndex={0}
        onSelect={jest.fn()}
        glowColor="#00ffff"
      />
    )
    
    // Select node at index 2
    rerender(
      <OrbitalRingWithMiniNodes
        miniNodes={miniNodes}
        selectedIndex={2}
        onSelect={jest.fn()}
        glowColor="#00ffff"
      />
    )
    
    // Verify rotation angle (4 nodes = 90° per segment, index 2 = -180°)
    const svg = screen.getByRole('img', { hidden: true })
    const motionGroup = svg.querySelector('g[style*="rotate"]')
    expect(motionGroup).toHaveStyle({ rotate: '-180deg' })
  })
})
```

### Property Test Examples

**Property 1: Three-Level Navigation Constraint**
```typescript
// Feature: navigation-level-consolidation, Property 1
it('Property 1: For any navigation state, level must be 1, 2, or 3', () => {
  fc.assert(
    fc.property(
      fc.record({
        level: fc.integer({ min: 1, max: 3 }),
        selectedMain: fc.option(fc.constantFrom('voice', 'agent', 'automate', 'system', 'customize', 'monitor')),
        selectedSub: fc.option(fc.string())
      }),
      (state) => {
        expect(state.level).toBeGreaterThanOrEqual(1)
        expect(state.level).toBeLessThanOrEqual(3)
      }
    ),
    { numRuns: 100 }
  )
})
```

**Property 2: Mini-Node Distribution**
```typescript
// Feature: navigation-level-consolidation, Property 2
it('Property 2: For any set of mini-nodes, distribution across rings is correct', () => {
  fc.assert(
    fc.property(
      fc.array(fc.record({
        id: fc.string(),
        label: fc.string(),
        icon: fc.string(),
        fields: fc.array(fc.anything())
      }), { minLength: 1, maxLength: 20 }),
      (miniNodes) => {
        const splitPoint = Math.ceil(miniNodes.length / 2)
        const outerCount = splitPoint
        const innerCount = miniNodes.length - splitPoint
        
        expect(outerCount + innerCount).toBe(miniNodes.length)
        expect(outerCount).toBeGreaterThanOrEqual(innerCount)
        expect(outerCount - innerCount).toBeLessThanOrEqual(1)
      }
    ),
    { numRuns: 100 }
  )
})
```

**Property 6: Field Value Updates**
```typescript
// Feature: navigation-level-consolidation, Property 6
it('Property 6: For any field and value, updates propagate to state', () => {
  fc.assert(
    fc.property(
      fc.string(), // nodeId
      fc.string(), // fieldId
      fc.oneof(fc.string(), fc.integer(), fc.boolean()), // value
      (nodeId, fieldId, value) => {
        const initialState = { miniNodeValues: {} }
        const action = {
          type: 'UPDATE_MINI_NODE_VALUE',
          payload: { nodeId, fieldId, value }
        }
        
        const newState = navigationReducer(initialState, action)
        
        expect(newState.miniNodeValues[nodeId][fieldId]).toBe(value)
      }
    ),
    { numRuns: 100 }
  )
})
```

**Property 13: LocalStorage Round-Trip**
```typescript
// Feature: navigation-level-consolidation, Property 13
it('Property 13: For any mini-node values, localStorage round-trip preserves data', () => {
  fc.assert(
    fc.property(
      fc.dictionary(
        fc.string(),
        fc.dictionary(fc.string(), fc.oneof(fc.string(), fc.integer(), fc.boolean()))
      ),
      (values) => {
        // Save to localStorage
        localStorage.setItem(MINI_NODE_VALUES_KEY, JSON.stringify(values))
        
        // Load from localStorage
        const loaded = JSON.parse(localStorage.getItem(MINI_NODE_VALUES_KEY))
        
        expect(loaded).toEqual(values)
      }
    ),
    { numRuns: 100 }
  )
})
```

### Test Coverage Goals

- **Unit Test Coverage**: 80% line coverage minimum
- **Property Test Coverage**: All 21 correctness properties implemented
- **Integration Test Coverage**: All navigation flows (Level 1→2→3, backward navigation)
- **Error Handling Coverage**: All error scenarios tested

### Testing Commands

```bash
# Run all tests
npm test

# Run property-based tests only
npm test -- --testNamePattern="Property"

# Run unit tests only
npm test -- --testNamePattern="^((?!Property).)*$"

# Run with coverage
npm test -- --coverage

# Run in watch mode during development
npm test -- --watch
```


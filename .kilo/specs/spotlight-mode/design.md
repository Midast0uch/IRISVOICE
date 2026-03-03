# Design: Spotlight Mode (Integrated)

## Overview

Spotlight Mode is integrated into the existing `useUILayoutState` hook as a sub-state system. Users can toggle between spotlight configurations in two contexts:

1. **Chat-Only Mode** (`UI_STATE_CHAT_OPEN`): Only ChatWing is visible, spotlight expands the chat wing
2. **Both-Open Mode** (`UI_STATE_BOTH_OPEN`): Both wings visible, spotlight emphasizes one wing while dimming the other

Three spotlight configurations: **balanced**, **chatSpotlight**, and **dashboardSpotlight**. This approach preserves the existing state machine while adding spotlight functionality as an enhancement layer.

## Architecture

### State Hierarchy

```
UILayoutState
├── UI_STATE_IDLE
├── UI_STATE_CHAT_OPEN
│   └── SpotlightState (sub-state)
│       ├── balanced (default)
│       └── chatSpotlight
└── UI_STATE_BOTH_OPEN
    └── SpotlightState (sub-state)
        ├── balanced (default)
        ├── chatSpotlight
        └── dashboardSpotlight
```

### Chat-Only Spotlight

When only the ChatWing is open (`UI_STATE_CHAT_OPEN`), spotlight mode provides:
- **Expanded width**: 340px (vs 255px default)
- **Zero rotation**: rotateY(0deg) for flat presentation
- **Full opacity**: No background wing to dim
- **Aperture button visible**: Embedded in header for toggle access

This allows users to maximize chat space even when dashboard is not open.

### Integration Points

1. **useUILayoutState.ts** - Extended with spotlight state management
2. **chat-view.tsx** - Consumes spotlight state, renders maximize/restore button
3. **dashboard-wing.tsx** - Consumes spotlight state, renders maximize/restore button
4. **page.tsx** - Passes spotlight state to both wings

### Extended Hook Interface

```typescript
// Spotlight state enum
export enum SpotlightState {
  BALANCED = 'balanced',
  CHAT_SPOTLIGHT = 'chatSpotlight',
  DASHBOARD_SPOTLIGHT = 'dashboardSpotlight'
}

// Extended return interface
export interface UILayoutStateManager {
  // Existing properties
  state: UILayoutState
  isTransitioning: boolean
  transitionDirection: TransitionDirection
  navigationLevel: number
  
  // Existing methods
  openChat: () => void
  openDashboard: () => void
  closeAll: () => void
  canTransition: (targetState: UILayoutState) => boolean
  
  // Spotlight properties (NEW)
  spotlightState: SpotlightState
  isBalanced: boolean
  isChatSpotlight: boolean
  isDashboardSpotlight: boolean
  
  // Spotlight methods (NEW)
  setSpotlightState: (state: SpotlightState) => void
  toggleChatSpotlight: () => void
  toggleDashboardSpotlight: () => void
  restoreBalanced: () => void
}
```

## Data Models

### Spotlight Style Configurations

```typescript
interface SpotlightStyleConfig {
  chatWing: {
    width: string;
    left: string;
    rotateY: string;
    opacity: number;
    filter: string;
    zIndex: number;
    scale: number;
  };
  dashboardWing: {
    width: string;
    right: string;
    rotateY: string;
    opacity: number;
    filter: string;
    zIndex: number;
    scale: number;
  };
}

const SpotlightStyles: Record<SpotlightState, SpotlightStyleConfig> = {
  [SpotlightState.BALANCED]: {
    chatWing: {
      width: '255px',
      left: '3%',
      rotateY: '15deg',
      opacity: 1,
      filter: 'none',
      zIndex: 10,
      scale: 1
    },
    dashboardWing: {
      width: '280px',
      right: '3%',
      rotateY: '-15deg',
      opacity: 1,
      filter: 'none',
      zIndex: 10,
      scale: 1
    }
  },
  [SpotlightState.CHAT_SPOTLIGHT]: {
    chatWing: {
      width: '340px',
      left: '5%',
      rotateY: '0deg',
      opacity: 1,
      filter: 'none',
      zIndex: 20,
      scale: 1
    },
    dashboardWing: {
      width: '180px',
      right: '3%',
      rotateY: '-15deg',
      opacity: 0.3,
      filter: 'saturate(0.6) blur(2px)',
      zIndex: 5,
      scale: 1
    }
  },
  [SpotlightState.DASHBOARD_SPOTLIGHT]: {
    chatWing: {
      width: '180px',
      left: '3%',
      rotateY: '15deg',
      opacity: 0.3,
      filter: 'saturate(0.6) blur(2px)',
      zIndex: 5,
      scale: 1
    },
    dashboardWing: {
      width: '360px',
      right: '5%',
      rotateY: '0deg',
      opacity: 1,
      filter: 'none',
      zIndex: 20,
      scale: 1
    }
  }
};
```

## Custom Component: IrisApertureIcon

### Component Design

**Location:** `IRISVOICE/components/ui/IrisApertureIcon.tsx`

**Visual Specification:**
- **Size:** 14x14px viewBox
- **Rest State (Diamond ✦):** Four triangular points meeting at center
  - Point 1: Top (facing down)
  - Point 2: Right (facing left)
  - Point 3: Bottom (facing up)
  - Point 4: Left (facing right)
- **Active State (Aperture ✧):** Points expanded outward along diagonals
  - Each point moves 4px outward from center along its diagonal axis
  - Creates square negative space in center

**Animation:**
- **Duration:** 400ms
- **Easing:** Spring physics (stiffness: 280, damping: 25)
- **Motion:** Points translate along diagonals (45°, 135°, 225°, 315°)

**Styling:**
- **Rest:** 1px stroke, color: `${fontColor}60` (white/60)
- **Active:** Fill with glowColor, optional subtle glow filter
- **Line join:** Miter for sharp crystalline points
- **Line cap:** Butt for precise edges

**Implementation:**
```typescript
interface IrisApertureIconProps {
  isActive: boolean;  // true when wing is spotlighted
  glowColor: string;
  fontColor: string;
  size?: number;  // default 14
}

// SVG Structure:
// Four polygon elements (triangles) positioned at center
// Animated with Framer Motion:
// - Rest: translate(0, 0) for all points
// - Active: 
//   - Top point: translate(0, -4)
//   - Right point: translate(4, 0)
//   - Bottom point: translate(0, 4)
//   - Left point: translate(-4, 0)
```

## API / Interface Changes

### useUILayoutState.ts Extensions

```typescript
// New: Spotlight state management
const [spotlightState, setSpotlightState] = useState<SpotlightState>(SpotlightState.BALANCED);

// New: Spotlight transition methods
const toggleChatSpotlight = useCallback(() => {
  if (uiState !== UILayoutState.UI_STATE_BOTH_OPEN) return;
  setSpotlightState(prev => 
    prev === SpotlightState.CHAT_SPOTLIGHT 
      ? SpotlightState.BALANCED 
      : SpotlightState.CHAT_SPOTLIGHT
  );
}, [uiState]);

const toggleDashboardSpotlight = useCallback(() => {
  if (uiState !== UILayoutState.UI_STATE_BOTH_OPEN) return;
  setSpotlightState(prev => 
    prev === SpotlightState.DASHBOARD_SPOTLIGHT 
      ? SpotlightState.BALANCED 
      : SpotlightState.DASHBOARD_SPOTLIGHT
  );
}, [uiState]);

const restoreBalanced = useCallback(() => {
  setSpotlightState(SpotlightState.BALANCED);
}, []);

// New: Reset spotlight when leaving BOTH_OPEN
useEffect(() => {
  if (uiState !== UILayoutState.UI_STATE_BOTH_OPEN) {
    setSpotlightState(SpotlightState.BALANCED);
  }
}, [uiState]);
```

### IrisApertureIcon Props

```typescript
interface IrisApertureIconProps {
  isActive: boolean;
  glowColor: string;
  fontColor: string;
  size?: number;
}
```

### Usage in Wing Headers

```tsx
// In ChatWing header:
<IrisApertureIcon 
  isActive={spotlightState === SpotlightState.CHAT_SPOTLIGHT}
  glowColor={glowColor}
  fontColor={fontColor}
  size={14}
/>

// In DashboardWing header:
<IrisApertureIcon 
  isActive={spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT}
  glowColor={glowColor}
  fontColor={fontColor}
  size={14}
/>
```

### ChatWing Props Extension

```typescript
interface ChatWingProps {
  // ... existing props ...
  spotlightState?: SpotlightState;
  onToggleSpotlight?: () => void;
}
```

### DashboardWing Props Extension

```typescript
interface DashboardWingProps {
  // ... existing props ...
  spotlightState?: SpotlightState;
  onToggleSpotlight?: () => void;
}
```

## Sequence Diagram

```
User clicks ChatActivationText
        │
        ▼
┌─────────────────┐
│   openChat()    │
│ UI_STATE_CHAT_OPEN
└─────────────────┘
        │
        ▼
User clicks Dashboard icon in ChatWing
        │
        ▼
┌─────────────────┐
│ openDashboard() │
│ UI_STATE_BOTH_OPEN
│ spotlightState=BALANCED (default)
└─────────────────┘
        │
        ▼
User clicks Maximize on ChatWing
        │
        ▼
┌─────────────────┐
│toggleChatSpotlight│
│ spotlightState=CHAT_SPOTLIGHT
└─────────────────┘
        │
        ▼
ChatWing animates: width 255px→340px, rotateY 15deg→0deg
DashboardWing animates: width 280px→180px, opacity 1→0.3
        │
        ▼
User clicks Restore on ChatWing
        │
        ▼
┌─────────────────┐
│ restoreBalanced() │
│ spotlightState=BALANCED
└─────────────────┘
```

## Key Design Decisions

### 1. Sub-State Architecture
**Decision:** Spotlight mode is a sub-state of `UI_STATE_BOTH_OPEN`, not a separate state machine.

**Rationale:**
- Preserves existing UILayoutState semantics
- Maintains backward compatibility
- Cleaner integration with current code
- Spotlight only makes sense when both wings are open

### 2. Direct State Setting
**Decision:** Use direct state setting with validation rather than a complex transition system.

**Rationale:**
- Spotlight transitions are simpler than UI layout transitions
- No need for transition locking
- Spring animations handle the visual smoothing
- Toggle methods provide convenience

### 3. Automatic Reset
**Decision:** Reset spotlight to `balanced` when leaving `UI_STATE_BOTH_OPEN`.

**Rationale:**
- Ensures consistent starting state
- Prevents confusion when re-opening wings
- Maintains expected user experience

### 4. Spring Animation Consistency
**Decision:** Use the same spring configuration as dashboard-wing.tsx (stiffness 280, damping 25).

**Rationale:**
- Visual consistency with existing animations
- Users already familiar with the feel
- No jarring transitions between different animation styles

## Error Handling & Edge Cases

### 1. Invalid State Combinations
**Scenario:** `setSpotlightState` called when `uiState !== BOTH_OPEN`.

**Handling:** State update is allowed but has no visual effect (wings not rendered). Reset to `balanced` when re-entering `BOTH_OPEN`.

### 2. Rapid Spotlight Toggles
**Scenario:** User rapidly clicks maximize buttons.

**Handling:** Framer Motion spring physics naturally smooths rapid changes. No special locking needed.

### 3. Escape Key Priority
**Scenario:** Notification dropdown open AND in spotlight mode.

**Handling:** First Escape closes dropdown. Second Escape restores balanced state. Third Escape closes wings (existing behavior).

### 4. Theme Changes During Spotlight
**Scenario:** User changes theme while in spotlight mode.

**Handling:** Colors update immediately. No state transition required.

### 5. Window Resize
**Scenario:** Window resizes while in spotlight mode.

**Handling:** Wing positions recalculate proportionally. Maintain minimum 80px gap.

## Testing Strategy

### Unit Tests
1. Spotlight state transitions within BOTH_OPEN
2. Spotlight reset when leaving BOTH_OPEN
3. Toggle methods behavior
4. Boolean helper accuracy

### Integration Tests
1. Full flow: idle → chat_open → both_open (balanced) → chatSpotlight → balanced → idle
2. Direct spotlight transitions: chatSpotlight ↔ dashboardSpotlight
3. Escape key handling in all states
4. Notification dropdown interaction

### Visual Tests
1. All three spotlight states at 680px
2. Transition smoothness
3. Z-index layering verification
4. Pointer events blocking on background wing

## Implementation Phases

### Phase 1: Hook Extension
- Add SpotlightState enum
- Add spotlight state and methods to useUILayoutState
- Reset logic when leaving BOTH_OPEN

### Phase 2: ChatWing Integration
- Add spotlight props
- Add maximize/restore button
- Apply dynamic styles

### Phase 3: DashboardWing Integration
- Add spotlight props
- Add maximize/restore button
- Apply dynamic styles

### Phase 4: Page Integration
- Pass spotlight state to wings
- Update Escape key handling
- Test full flow

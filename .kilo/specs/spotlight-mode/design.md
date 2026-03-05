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
├── UI_STATE_DASHBOARD_OPEN (NEW)
│   └── SpotlightState (sub-state)
│       └── dashboardSpotlight (default)
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

### Dashboard-Only View (NEW)

When only the DashboardWing is open (`UI_STATE_DASHBOARD_OPEN`), it mirrors the ChatWing solo view:
- **Width**: 280px (matching ChatWing default) or 380px when spotlighted
- **Angled orientation**: rotateY(-15deg) for visual consistency (in balanced mode)
- **Flat orientation**: rotateY(0deg) when in spotlight mode
- **Right positioning**: Positioned at right side with consistent spacing
- **Full opacity**: No background wing to dim
- **Interactive**: Full pointer events enabled
- **Aperture button visible**: Embedded in header for spotlight toggle (functional in solo mode)
- **Chat icon visible**: Button to open ChatWing and return to both-open view

**Spotlight Toggle in Solo Mode:**
- Works identically to ChatWing solo spotlight toggle
- Toggles between `BALANCED` (280px, -15deg rotation) and `DASHBOARD_SPOTLIGHT` (380px, 0deg rotation)
- Spring animation for smooth transitions
- Aperture icon morphs between diamond (balanced) and expanded (spotlight) states

**Open Chat from Dashboard:**
- Chat icon button in header (between notifications and close)
- Only visible when in dashboard solo mode
- Clicking transitions from `UI_STATE_DASHBOARD_OPEN` to `UI_STATE_BOTH_OPEN`
- Preserves dashboard spotlight state if active
- Uses spring animation for smooth transition
- Icon has same hover/active styling as other header controls

This provides visual symmetry between chat-only and dashboard-only solo views with equivalent spotlight functionality and bidirectional navigation.

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
  
  // NEW: Selective close method
  closeChat: () => void  // Closes only ChatWing, keeps Dashboard open
  
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
// Spotlight state management
const [spotlightState, setSpotlightState] = useState<SpotlightState>(SpotlightState.BALANCED);

// NEW: Track chat spotlight state for bidirectional transitions
const wasChatSpotlightRef = useRef<boolean>(false);

// NEW: Selective close - closes only ChatWing, returns to dashboard-only or idle
const closeChat = useCallback(() => {
  if (uiState === UILayoutState.UI_STATE_BOTH_OPEN) {
    // Close chat but keep dashboard open
    setUiState(UILayoutState.UI_STATE_IDLE);  // Will show dashboard-only
    // Note: DashboardWing visibility controlled by isBothOpen, so we need
    // a dashboard-only state or handle this at page level
    
    // Reset spotlight state when leaving both-open
    setSpotlightState(SpotlightState.BALANCED);
    wasChatSpotlightRef.current = false;
  } else if (uiState === UILayoutState.UI_STATE_CHAT_OPEN) {
    // Close chat, go to idle
    setUiState(UILayoutState.UI_STATE_IDLE);
    setSpotlightState(SpotlightState.BALANCED);
    wasChatSpotlightRef.current = false;
  }
}, [uiState]);

// UPDATED: Open dashboard with chat spotlight preservation
const openDashboard = useCallback(() => {
  if (uiState === UILayoutState.UI_STATE_CHAT_OPEN) {
    // Check if we were in chat spotlight before opening dashboard
    const wasInChatSpotlight = spotlightState === SpotlightState.CHAT_SPOTLIGHT;
    wasChatSpotlightRef.current = wasInChatSpotlight;
  }
  setUiState(UILayoutState.UI_STATE_BOTH_OPEN);
  // Only default to balanced if we weren't preserving chat spotlight
  if (!wasChatSpotlightRef.current) {
    setSpotlightState(SpotlightState.BALANCED);
  }
}, [uiState, spotlightState]);

// UPDATED: Toggle chat spotlight works in both CHAT_OPEN and BOTH_OPEN
const toggleChatSpotlight = useCallback(() => {
  if (uiState === UILayoutState.UI_STATE_BOTH_OPEN) {
    // Toggle between balanced and chatSpotlight
    setSpotlightState(prev => 
      prev === SpotlightState.CHAT_SPOTLIGHT 
        ? SpotlightState.BALANCED 
        : SpotlightState.CHAT_SPOTLIGHT
    );
  } else if (uiState === UILayoutState.UI_STATE_CHAT_OPEN) {
    // In chat-only mode, toggle expands/contracts the chat wing
    setSpotlightState(prev => 
      prev === SpotlightState.CHAT_SPOTLIGHT 
        ? SpotlightState.BALANCED 
        : SpotlightState.CHAT_SPOTLIGHT
    );
  }
}, [uiState]);

const toggleDashboardSpotlight = useCallback(() => {
  // Allow spotlight toggle in both dashboard-open states (solo and both-open)
  if (uiState !== UILayoutState.UI_STATE_BOTH_OPEN && uiState !== UILayoutState.UI_STATE_DASHBOARD_OPEN) return;
  setSpotlightState(prev => 
    prev === SpotlightState.DASHBOARD_SPOTLIGHT 
      ? SpotlightState.BALANCED 
      : SpotlightState.DASHBOARD_SPOTLIGHT
  );
}, [uiState]);

const restoreBalanced = useCallback(() => {
  setSpotlightState(SpotlightState.BALANCED);
}, []);

// UPDATED: Only reset spotlight when entering IDLE, not when transitioning
// between chat-open and both-open
useEffect(() => {
  if (uiState === UILayoutState.UI_STATE_IDLE) {
    setSpotlightState(SpotlightState.BALANCED);
    wasChatSpotlightRef.current = false;
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
  isDashboardOpen?: boolean;  // NEW: Distinguishes single-wing vs both-wing context
  onDashboardClose?: () => void;  // NEW: Called when dashboard toggle closes dashboard
}
```

### Dashboard Icon Toggle Behavior

The Dashboard icon in the ChatWing header now toggles the DashboardWing open/close state:

```typescript
// Dashboard icon click handler in ChatWing
const handleDashboardClick = () => {
  if (isDashboardOpen && onDashboardClose) {
    // Dashboard is open, close it and return to chat-only view
    onDashboardClose();
  } else {
    // Dashboard is closed, open it
    onDashboardClick();
  }
};
```

**Visual State Feedback:**
- When dashboard is closed: Icon at 60% opacity, neutral color
- When dashboard is open: Icon at 90% opacity, highlighted background
- Hover effects apply in both states for discoverability

### Close Button Conditional Behavior

The ChatWing close button now behaves differently based on context:

```typescript
// In page.tsx - conditional close handler
<LazyChatWing
  isOpen={isChatOpen || isBothOpen}
  onClose={isBothOpen ? closeChat : closeAll}  // NEW: Selective close
  onDashboardClick={openDashboard}
  onDashboardClose={closeChat}  // NEW: Dashboard close callback
  ...
/>
```

**Behavior Matrix:**

| Context | Close Button Action | Result |
|---------|---------------------|--------|
| Only ChatWing open | closeAll() | Return to idle |
| Both wings open | closeChat() | Dashboard remains, chat closes |

### DashboardWing Props Extension

```typescript
interface DashboardWingProps {
  // ... existing props ...
  spotlightState?: SpotlightState;
  onToggleSpotlight?: () => void;
}
```

## Sequence Diagram

### Primary Flow: Idle → Chat → Both Open
```
User clicks ChatActivationText
        │
        ▼
┌─────────────────┐
│   openChat()    │
│ UI_STATE_CHAT_OPEN
│ IrisOrb visible
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
│ Preserves chat spotlight if was in that state
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

### Single-Wing Close Transitions (NEW)
```
UI_STATE_BOTH_OPEN
        │
        │ User clicks Exit on ChatWing
        ▼
┌──────────────────────────────────┐
│ closeChat()                       │
│ - Transitions to UI_STATE_DASHBOARD_OPEN
│ - DashboardWing remains visible   │
│ - Sets dashboardSpotlight         │
│ - Preserves content state         │
└──────────────────────────────────┘
        │
        ▼
UI_STATE_DASHBOARD_OPEN (solo view)
        │
        │ User clicks Exit on DashboardWing
        ▼
┌──────────────────────────────────┐
│ closeDashboard()                  │
│ - Transitions to UI_STATE_IDLE    │
│ - Both wings closed               │
│ - IrisOrb centered                │
└──────────────────────────────────┘
        │
        ▼
UI_STATE_IDLE

Alternative: Reverse Direction

UI_STATE_BOTH_OPEN
        │
        │ User clicks Exit on DashboardWing
        ▼
┌──────────────────────────────────┐
│ closeDashboard()                  │
│ - Transitions to UI_STATE_CHAT_OPEN
│ - ChatWing remains visible        │
│ - Restores chatSpotlight if was active
│ - Preserves content state         │
└──────────────────────────────────┘
        │
        ▼
UI_STATE_CHAT_OPEN (solo view)
        │
        │ User clicks Exit on ChatWing
        ▼
┌──────────────────────────────────┐
│ closeChat() / closeAll()          │
│ - Transitions to UI_STATE_IDLE    │
│ - Both wings closed               │
│ - IrisOrb centered                │
└──────────────────────────────────┘
        │
        ▼
UI_STATE_IDLE
```

### IrisOrb Dual-Close Behavior
```
UI_STATE_BOTH_OPEN
        │
        │ User clicks IrisOrb (center)
        ▼
┌──────────────────────────────────┐
│ handleSingleClick()               │
│ - Calls closeAll()                │
│ - Both wings close simultaneously │
│ - Synchronized animation          │
│ - Returns to UI_STATE_IDLE        │
└──────────────────────────────────┘
        │
        ▼
UI_STATE_IDLE (IrisOrb centered)
```

### Legacy: Bidirectional Dashboard Toggle
```
UI_STATE_CHAT_OPEN (chatSpotlight)
        │
        │ User clicks Dashboard icon
        ▼
┌──────────────────────────────────┐
│ openDashboard()                   │
│ - Transitions to UI_STATE_BOTH_OPEN
│ - Preserves chatSpotlight state   │
│ - Dashboard opens at balanced     │
│ - IrisOrb remains visible         │
└──────────────────────────────────┘
        │
        │ User clicks Dashboard icon again
        ▼
┌──────────────────────────────────┐
│ onDashboardClose()                │
│ - Calls closeChat()               │
│ - Returns to UI_STATE_DASHBOARD_OPEN
│ - Preserves dashboard visibility  │
└──────────────────────────────────┘
        │
        ▼
UI_STATE_DASHBOARD_OPEN (solo view)
```

### Dashboard Toggle Flow
```
User in UI_STATE_BOTH_OPEN
        │
        │ User clicks Dashboard icon in ChatWing header
        ▼
┌──────────────────────────────────┐
│ Dashboard icon toggles state:     │
│ IF dashboard is open:             │
│   - onDashboardClose() → closeChat()
│   - Returns to UI_STATE_CHAT_OPEN │
│ IF dashboard is closed:           │
│   - onDashboardClick() → openDashboard()
│   - Opens to UI_STATE_BOTH_OPEN   │
└──────────────────────────────────┘
```

### Close Button Behavior
```
User in UI_STATE_BOTH_OPEN
        │
        │ User clicks Close on ChatWing
        ▼
┌──────────────────────────────────┐
│ onClose behavior:                 │
│ IF isBothOpen:                    │
│   - closeChat() only              │
│   - Dashboard remains open        │
│   - Returns to dashboard-only view│
│ IF only ChatWing open:            │
│   - closeAll()                    │
│   - Returns to idle               │
└──────────────────────────────────┘
```

## IrisOrb Visibility

### Design Principle
The IrisOrb (central aperture button) remains visible whenever the ChatWing is open, providing consistent visual anchor and quick access to the main interaction point.

### Visibility Rules

| UI State | IrisOrb Visible | Position | Scale | Opacity | zIndex |
|----------|----------------|----------|-------|---------|--------|
| UI_STATE_IDLE | Yes | Center | 1.0 | 1.0 | 0 |
| UI_STATE_CHAT_OPEN | Yes | Center | 0.85 | 0.6 | 5 |
| UI_STATE_BOTH_OPEN | Yes | Center | 0.85 | 0.6 | 5 |

### Implementation

```typescript
// In page.tsx - IrisOrb container visibility
{(state.level !== 3 || isChatOpen || isBothOpen) && (
  <motion.div 
    className="absolute inset-0 flex items-center justify-center"
    animate={{
      scale: uiLayoutState !== UILayoutState.UI_STATE_IDLE ? 0.85 : 1,
      filter: uiLayoutState !== UILayoutState.UI_STATE_IDLE ? 'blur(2px)' : 'blur(0px)',
      opacity: uiLayoutState !== UILayoutState.UI_STATE_IDLE ? 0.6 : 1,
    }}
    transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
    style={{ 
      zIndex: (isChatOpen || isBothOpen) ? 5 : 0,
      pointerEvents: (isChatOpen || isBothOpen) ? 'none' : 'auto'
    }}
  >
    <IrisOrb ... />
  </motion.div>
)}
```

### Rationale
- **Visual continuity**: Users can always see the central orb when chat is active
- **Spatial reference**: Provides anchor point for the IRIS "personality"
- **Non-blocking**: `pointerEvents: 'none'` when wings are open prevents interference
- **Subtle presence**: Reduced scale and opacity keeps it from competing with wing content

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

# IRIS Screen Wings - Complete Design & Functionality Reference

> **Document Version**: 1.0  
> **Last Updated**: 2026-03-03  
> **Purpose**: Comprehensive reference for ChatWing, DashboardWing, and Spotlight Mode architecture  
> **Status**: Production Implementation

---

## Table of Contents

1. [Overview](#overview)
2. [Critical Constraints](#critical-constraints)
3. [UI State Architecture](#ui-state-architecture)
4. [ChatWing (chat-view.tsx)](#chatwing-chat-viewtsx)
5. [DashboardWing (dashboard-wing.tsx)](#dashboardwing-dashboard-wingtsx)
6. [Spotlight Mode System](#spotlight-mode-system)
7. [State Transitions](#state-transitions)
8. [Iris Orb Integration](#iris-orb-integration)
9. [Notification System](#notification-system)
10. [Component Props Reference](#component-props-reference)
11. [Troubleshooting](#troubleshooting)

---

## Overview

The IRIS Screen Wings system provides a dual-wing interface architecture consisting of:

- **ChatWing** (Left): 255px width, conversational interface with the IRIS AI assistant
- **DashboardWing** (Right): 280px width, settings and configuration interface

Both wings utilize a **perspective transform** (`rotateY`) to create a 3D "wing" appearance, angling toward the center Iris Orb. The system supports four distinct UI states with smooth spotlight-style transitions.

### Design Philosophy

- **Glass morphism**: Semi-transparent dark backgrounds with backdrop blur
- **Energy-first aesthetic**: Brand-colored glows and kinetic animations
- **Non-intrusive**: Wings overlay without blocking the central control interface
- **Responsive**: Smooth animations and state transitions (200-300ms)

---

## Critical Constraints

These dimensions are **ABSOLUTE** and must not be modified:

| Component | Width | Height | Position | Rotation |
|-----------|-------|--------|----------|----------|
| **ChatWing** | 255px | 50vh | left: 3% | rotateY: 15deg |
| **DashboardWing** | 280px | 50vh | right: 3% | rotateY: -15deg |
| **IrisOrb** | 64px diameter | - | Centered | No rotation |

### Constraints Notes

- Work within existing components: `ChatWing`, `DashboardWing`, `DarkGlassDashboard`
- NO new component files unless absolutely necessary
- Configuration structure is flexible - keep implementation adaptable
- All positioning uses percentage-based vertical centering (`top: 50%, transform: translateY(-50%)`)

---

## UI State Architecture

The `useUILayoutState` hook manages four distinct UI states:

```typescript
export enum UILayoutState {
  UI_STATE_IDLE = 'idle',                    // Nothing open
  UI_STATE_CHAT_OPEN = 'chat_open',          // Only ChatWing visible
  UI_STATE_DASHBOARD_OPEN = 'dashboard_open', // Only DashboardWing visible
  UI_STATE_BOTH_OPEN = 'both_open',          // Both wings visible
}

export enum SpotlightState {
  BALANCED = 'balanced',                     // Both wings at default
  CHAT_SPOTLIGHT = 'chat_spotlight',         // ChatWing expanded
  DASHBOARD_SPOTLIGHT = 'dashboard_spotlight', // DashboardWing expanded
}
```

### State Characteristics

| State | ChatWing | DashboardWing | IrisOrb | Description |
|-------|----------|---------------|---------|-------------|
| `UI_STATE_IDLE` | Hidden | Hidden | Visible | Default state, only orb visible |
| `UI_STATE_CHAT_OPEN` | Visible (255px) | Hidden | Visible | Chat-only spotlight mode |
| `UI_STATE_DASHBOARD_OPEN` | Hidden | Visible (280px) | Visible | Dashboard-only mode |
| `UI_STATE_BOTH_OPEN` | Visible (255px) | Visible (280px) | Visible | Standard dual-wing view |

### Spotlight Configuration by State

| State | Spotlight State | Effect |
|-------|----------------|--------|
| `UI_STATE_CHAT_OPEN` | `CHAT_SPOTLIGHT` | ChatWing expands, flattens, shifts right |
| `UI_STATE_DASHBOARD_OPEN` | `DASHBOARD_SPOTLIGHT` | DashboardWing expands, flattens, shifts left |
| `UI_STATE_BOTH_OPEN` | `BALANCED` | Both wings at default dimensions |
| `UI_STATE_IDLE` | `BALANCED` | Reset to default |

---

## ChatWing (chat-view.tsx)

### Dimensions & Positioning

```typescript
// Fixed positioning - DO NOT MODIFY
const WING_WIDTH = 255;
const WING_HEIGHT = '50vh';
const POSITION_LEFT = '3%';
const ROTATION = 'rotateY(15deg)';  // Angled toward center

// Vertical centering
position: fixed;
top: 50%;
left: 3%;
transform: translateY(-50%) rotateY(15deg);
```

### Component Structure

```
ChatWing Container (255px × 50vh)
├── Header (48px height)
│   ├── Left Section
│   │   ├── Pulse Indicator (animated voice state)
│   │   └── Title ("IRIS Assistant")
│   └── Right Section (Icons)
│       ├── History (↩️)
│       ├── Notifications (🔔)
│       ├── Dashboard (📊)
│       └── Close (✕)
├── Notification Dropdown (collapsible)
│   └── Notification List
├── Message Area (flex-grow, scrollable)
│   ├── User Messages (right-aligned, sharp left corners)
│   └── IRIS Messages (left-aligned, sharp right corners)
└── Input Area (fixed bottom)
    ├── Text Input
    └── Voice Button
```

### Header Icon Order (Left to Right)

1. **Pulse Indicator**: Animated dot showing voice state (listening = pulsing)
2. **Title**: "IRIS Assistant" text
3. **History Button**: Opens conversation history dropdown
4. **Notifications Button**: Bell icon with unread badge
5. **Dashboard Button**: Opens/closes DashboardWing (toggle behavior)
6. **Close Button**: Closes ChatWing

### Message Bubble Design

#### User Messages

```typescript
// Convergent corners - sharp toward orb (left side)
borderRadius: '16px 16px 4px 16px';
backgroundColor: `${primaryColor}cc`;  // Semi-transparent primary
boxShadow: '0 4px 20px rgba(0,0,0,0.3)';
maxWidth: '85%';
```

#### IRIS Messages

```typescript
// Convergent corners - sharp toward orb (right side)
borderRadius: '16px 16px 16px 4px';
backgroundColor: 'rgba(255,255,255,0.06)';
borderLeft: `2px solid ${glowColor}50`;
boxShadow: '0 4px 20px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.05)';
maxWidth: '85%';
```

### State Management

```typescript
// Internal state
const [notifications, setNotifications] = useState<Notification[]>([]);
const [showNotifications, setShowNotifications] = useState(false);
const [unreadCount, setUnreadCount] = useState(0);
const [showHistory, setShowHistory] = useState(false);

// Props from parent
interface ChatViewProps {
  isVisible: boolean;
  onClose: () => void;
  onDashboardClick: () => void;
  onDashboardClose?: () => void;  // For toggle behavior
  glowColor: string;
  fontColor: string;
  // ... other props
}
```

---

## DashboardWing (dashboard-wing.tsx)

### Dimensions & Positioning

```typescript
// Fixed positioning - DO NOT MODIFY
const WING_WIDTH = 280;
const WING_HEIGHT = '50vh';
const POSITION_RIGHT = '3%';
const ROTATION = 'rotateY(-15deg)';  // Angled toward center (opposite)

// Vertical centering
position: fixed;
top: 50%;
right: 3%;
transform: translateY(-50%) rotateY(-15deg);
```

### Component Structure

```
DashboardWing Container (280px × 50vh)
├── Header (48px height)
│   ├── Title Section
│   │   └── "Dashboard" title
│   └── Right Section (Icons)
│       ├── Notifications (🔔)
│       ├── Open Chat (💬) - visible in solo mode
│       └── Close (✕)
├── Notification Dropdown (collapsible)
│   └── Notification List
└── Content Area
    └── DarkGlassDashboard (reused component)
        └── Settings Interface
```

### Header Icon Order (Left to Right)

1. **Title**: "Dashboard" text
2. **Notifications Button**: Bell icon with unread badge
3. **Open Chat Button**: MessageSquare icon (visible when chat is closed)
4. **Close Button**: X icon

### Solo Mode Behavior

When DashboardWing is open without ChatWing:

```typescript
// DashboardWing shows "Open Chat" button
{onOpenChat && !isChatOpen && (
  <button onClick={onOpenChat} title="Open Chat">
    <MessageSquare size={16} />
  </button>
)}
```

### Props Interface

```typescript
interface DashboardWingProps {
  isVisible: boolean;
  onClose: () => void;
  onOpenChat?: () => void;  // Optional, for solo mode
  isChatOpen?: boolean;     // To conditionally show Open Chat button
  sendMessage: SendMessageFunction;
  // ... other props from DarkGlassDashboard
}
```

---

## Spotlight Mode System

### Purpose

Spotlight mode creates a "theater" effect when only one wing is open:
- The open wing expands slightly
- Rotation flattens (reduces rotateY)
- Wing shifts toward center to feel more present
- Creates focus on the active interface

### Chat-Only Spotlight State

Triggered when `uiState === UI_STATE_CHAT_OPEN`:

```typescript
const spotlightConfig = {
  width: 320,           // Expanded from 255px
  rotation: 5,          // Flattened from 15deg
  left: '5%',           // Shifted right from 3%
  transition: {
    duration: 0.4,
    ease: [0.22, 1, 0.36, 1]
  }
};
```

### Dashboard-Only Spotlight State

Triggered when `uiState === UI_STATE_DASHBOARD_OPEN`:

```typescript
const spotlightConfig = {
  width: 340,           // Expanded from 280px
  rotation: -5,         // Flattened from -15deg
  right: '5%',          // Shifted left from 3%
  transition: {
    duration: 0.4,
    ease: [0.22, 1, 0.36, 1]
  }
};
```

### Animation Curves

```typescript
// Smooth deceleration for professional feel
const easing = [0.22, 1, 0.36, 1];  // cubic-bezier

// Duration based on transition type
const durations = {
  quick: 0.2,    // Micro-interactions (hover, etc.)
  standard: 0.3, // State changes
  spotlight: 0.4 // Spotlight mode transitions
};
```

---

## State Transitions

### Opening Chat (from IDLE)

```typescript
// User clicks on IrisOrb text or chat activation area
function openChat() {
  setUiState(UILayoutState.UI_STATE_CHAT_OPEN);
  setSpotlightState(SpotlightState.CHAT_SPOTLIGHT);
}

// Visual result:
// - ChatWing fades in with spotlight animation
// - IrisOrb stays visible
// - DashboardWing remains hidden
```

### Opening Dashboard from Chat-Only

```typescript
// User clicks Dashboard icon in ChatWing header
function openDashboardFromChat() {
  // Track that we came from chat spotlight
  wasChatSpotlightRef.current = true;
  
  setUiState(UILayoutState.UI_STATE_BOTH_OPEN);
  setSpotlightState(SpotlightState.BALANCED);
  setDashboardOpen(true);
}

// Visual result:
// - DashboardWing fades in from right
// - ChatWing animates from spotlight to balanced
// - Both wings visible at default dimensions
```

### Closing Dashboard (returning to Chat-Only)

```typescript
// User closes DashboardWing when both are open
function closeDashboard() {
  if (wasChatSpotlightRef.current) {
    // Return to chat spotlight state
    setUiState(UILayoutState.UI_STATE_CHAT_OPEN);
    setSpotlightState(SpotlightState.CHAT_SPOTLIGHT);
    setDashboardOpen(false);
  } else {
    // Go to idle
    setUiState(UILayoutState.UI_STATE_IDLE);
    setDashboardOpen(false);
  }
}

// Visual result:
// - DashboardWing fades out
// - ChatWing animates back to spotlight
// - wasChatSpotlightRef determines destination
```

### Opening Dashboard Solo (from IDLE)

```typescript
// User directly opens DashboardWing
function openDashboardSolo() {
  setUiState(UILayoutState.UI_STATE_DASHBOARD_OPEN);
  setSpotlightState(SpotlightState.DASHBOARD_SPOTLIGHT);
  setLastActiveWing('dashboard');
  setDashboardOpen(true);
}

// Visual result:
// - DashboardWing fades in with spotlight animation
// - No chat spotlight history tracked
// - wasChatSpotlightRef remains false
```

### Closing Chat (when Both Open)

```typescript
// User closes ChatWing when both are open
function closeChat() {
  setUiState(UILayoutState.UI_STATE_DASHBOARD_OPEN);
  setSpotlightState(SpotlightState.DASHBOARD_SPOTLIGHT);
  setLastActiveWing('dashboard');
  // DashboardWing shows Open Chat button
}

// Visual result:
// - ChatWing fades out
// - DashboardWing animates to spotlight
// - Dashboard header shows "Open Chat" button
```

### IrisOrb Click Handler (Dual Close)

```typescript
function handleIrisOrbClick() {
  if (uiState === UI_STATE_BOTH_OPEN) {
    // Close both wings simultaneously
    closeAll();
  } else if (uiState === UI_STATE_CHAT_OPEN) {
    // Close chat only
    closeChat();
  } else if (uiState === UI_STATE_DASHBOARD_OPEN) {
    // Close dashboard only
    closeDashboard();
  } else {
    // Open chat from idle
    openChat();
  }
}
```

---

## Iris Orb Integration

### Positioning

```typescript
// Always centered, never moves
const orbConfig = {
  position: 'fixed',
  left: '50%',
  top: '50%',
  transform: 'translate(-50%, -50%)',
  zIndex: 100,
  size: 64,  // diameter in px
};
```

### Visibility Rules

| UI State | IrisOrb Visible | Z-Index |
|----------|-----------------|---------|
| All states | ✅ Yes | 100 |

**Important**: IrisOrb is **ALWAYS** visible whenever ChatWing is open:

```typescript
// In page.tsx rendering logic
{(uiState === UI_STATE_IDLE || 
  uiState === UI_STATE_CHAT_OPEN || 
  uiState === UI_STATE_BOTH_OPEN) && (
  <IrisOrb 
    onClick={handleIrisOrbClick}
    isChatActive={isChatActive}
  />
)}
```

### Interaction States

```typescript
// Idle state (no wings open)
- Single click: Opens ChatWing

// Chat-only open
- Single click: Closes ChatWing

// Dashboard-only open
- Single click: Closes DashboardWing

// Both wings open
- Single click: Closes BOTH wings simultaneously
```

---

## Notification System

### Universal Implementation

Both wings share an identical notification system:

```typescript
interface Notification {
  id: string;
  type: 'alert' | 'permission' | 'error' | 'task' | 'completion';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
  progress?: number;  // For task notifications (0-100)
}

// State management
const [notifications, setNotifications] = useState<Notification[]>([]);
const [showNotifications, setShowNotifications] = useState(false);
const [unreadCount, setUnreadCount] = useState(0);
```

### Unread Count Calculation

```typescript
useEffect(() => {
  setUnreadCount(notifications.filter(n => !n.read).length);
}, [notifications]);
```

### Auto-Mark as Read

```typescript
useEffect(() => {
  if (showNotifications) {
    setNotifications(prev => 
      prev.map(n => ({ ...n, read: true }))
    );
  }
}, [showNotifications]);
```

### Notification Icon with Badge

```typescript
<button
  onClick={() => setShowNotifications(!showNotifications)}
  className="relative"
  style={{ 
    color: showNotifications ? glowColor : 
           unreadCount > 0 ? glowColor : `${fontColor}60`
  }}
>
  <Bell size={16} />
  
  {unreadCount > 0 && (
    <motion.span
      initial={{ scale: 0 }}
      animate={{ scale: 1 }}
      className="absolute top-1 right-1 w-2 h-2 rounded-full"
      style={{ backgroundColor: glowColor }}
    />
  )}
</button>
```

### Notification Dropdown Panel

```typescript
<AnimatePresence>
  {showNotifications && (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: 'auto', opacity: 1 }}
      exit={{ height: 0, opacity: 0 }}
      transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
      className="overflow-hidden border-b"
      style={{ 
        borderColor: `${glowColor}10`,
        background: 'linear-gradient(180deg, rgba(10,10,20,0.98) 0%, rgba(10,10,20,0.9) 100%)',
        backdropFilter: 'blur(20px)',
        maxHeight: '50%'
      }}
    >
      {/* Notification list */}
    </motion.div>
  )}
</AnimatePresence>
```

### Notification Type Colors

```typescript
const getNotificationColor = (type: string) => {
  switch (type) {
    case 'alert': return '#fbbf24';      // amber
    case 'permission': return '#3b82f6'; // blue
    case 'error': return '#ef4444';      // red
    case 'task': return '#a855f7';       // purple
    case 'completion': return '#22c55e'; // green
    default: return glowColor;
  }
};
```

### Notification Icons

```typescript
const getNotificationIcon = (type: string) => {
  const iconProps = { size: 10, style: { color: getNotificationColor(type) } };
  switch (type) {
    case 'alert': return <AlertTriangle {...iconProps} />;
    case 'permission': return <Shield {...iconProps} />;
    case 'error': return <AlertCircle {...iconProps} />;
    case 'task': return <Loader {...iconProps} className="animate-spin" />;
    case 'completion': return <CheckCircle {...iconProps} />;
    default: return <Info {...iconProps} />;
  }
};
```

### Permission Notification Actions

```typescript
{notif.type === 'permission' && (
  <div className="flex gap-2 mt-2">
    <button
      onClick={() => handlePermissionGrant(notif.id)}
      style={{ background: `${glowColor}20`, color: glowColor }}
    >
      Allow
    </button>
    <button
      onClick={() => handlePermissionDeny(notif.id)}
      className="bg-white/10 text-white/70"
    >
      Deny
    </button>
  </div>
)}
```

### Task Notification Progress

```typescript
{notif.type === 'task' && (
  <div className="mt-2">
    <div className="h-1 bg-white/10 rounded-full overflow-hidden">
      <motion.div 
        className="h-full rounded-full"
        style={{ backgroundColor: glowColor }}
        initial={{ width: 0 }}
        animate={{ width: `${notif.progress || 0}%` }}
      />
    </div>
    <span className="text-[8px] text-white/40 mt-1 block">
      {notif.progress || 0}% complete
    </span>
  </div>
)}
```

---

## Component Props Reference

### ChatView Props

```typescript
interface ChatViewProps {
  // Visibility
  isVisible: boolean;
  
  // Callbacks
  onClose: () => void;
  onDashboardClick: () => void;
  onDashboardClose?: () => void;  // For toggle behavior
  
  // Theming
  glowColor: string;
  fontColor: string;
  primaryColor: string;
  
  // Voice/WebSocket
  voiceState: VoiceState;
  isSpeaking: boolean;
  sendMessage: SendMessageFunction;
  
  // Global state
  globalError: string | null;
  
  // Layout
  className?: string;
}
```

### DashboardWing Props

```typescript
interface DashboardWingProps {
  // Visibility
  isVisible: boolean;
  isChatOpen?: boolean;  // For showing Open Chat button
  
  // Callbacks
  onClose: () => void;
  onOpenChat?: () => void;  // Optional, for solo mode
  
  // Theming (inherited from DarkGlassDashboard)
  glowColor: string;
  fontColor: string;
  
  // WebSocket
  sendMessage: SendMessageFunction;
  
  // Settings state (from DarkGlassDashboard)
  fieldValues: Record<string, any>;
  updateField: (category: string, field: string, value: any) => void;
  
  // Layout
  className?: string;
}
```

### useUILayoutState Hook

```typescript
interface UseUILayoutStateReturn {
  // State
  uiState: UILayoutState;
  spotlightState: SpotlightState;
  isChatOpen: boolean;
  isDashboardOpen: boolean;
  lastActiveWing: 'chat' | 'dashboard' | null;
  
  // Actions
  openChat: () => void;
  closeChat: () => void;
  openDashboard: () => void;
  closeDashboard: () => void;
  openDashboardSolo: () => void;
  closeAll: () => void;
  toggleChatSpotlight: () => void;
  resetSpotlight: () => void;
}

function useUILayoutState(): UseUILayoutStateReturn;
```

---

## Styling Specifications

### Glass Background

```typescript
const glassStyles = {
  background: 'linear-gradient(180deg, rgba(10,10,20,0.98) 0%, rgba(10,10,20,0.9) 100%)',
  backdropFilter: 'blur(20px)',
  border: `1px solid ${glowColor}15`,
  borderRadius: '12px',
};
```

### Header Styling

```typescript
const headerStyles = {
  height: '48px',
  padding: '0 12px',
  borderBottom: `1px solid ${glowColor}15`,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
};
```

### Icon Button Styling

```typescript
const iconButtonStyles = {
  padding: '8px',
  borderRadius: '8px',
  transition: 'all 150ms',
  color: `${fontColor}60`,  // Default: muted
  
  // Hover state
  '&:hover': {
    color: `${fontColor}90`,
    backgroundColor: 'rgba(255,255,255,0.05)',
  },
  
  // Active/selected state
  '&.active': {
    color: glowColor,
    backgroundColor: `${glowColor}15`,
  },
};
```

### Typography Scale

| Element | Size | Weight | Opacity |
|---------|------|--------|---------|
| Title | 13px | 600 (semibold) | 90% |
| Button Label | 10px | 500 (medium) | 70% |
| Notification Type | 9px | 600 (semibold) | 100% |
| Notification Title | 11px | 500 (medium) | 90% |
| Notification Message | 10px | 400 (normal) | 60% |
| Timestamp | 8px | 400 (normal) | 30% |

---

## Troubleshooting

### Wings Not Visible

**Symptoms**: Wings don't appear when expected

**Checklist**:
1. Verify `uiState` is correct (not `UI_STATE_IDLE`)
2. Check `isVisible` prop is `true`
3. Ensure `display: flex` is set (not `display: none`)
4. Check z-index (wings should be above background, below modals)
5. Verify no CSS `visibility: hidden` or `opacity: 0`

### Spotlight Mode Not Working

**Symptoms**: Wings don't expand/flatten when opening solo

**Checklist**:
1. Verify `spotlightState` is being set correctly
2. Check `UILayoutState` transition is correct
3. Ensure `wasChatSpotlightRef` is being tracked
4. Verify animation duration/easing is applied
5. Check that width/rotation values are different from default

### Notification Badge Not Showing

**Symptoms**: Unread count indicator missing

**Checklist**:
1. Verify `unreadCount > 0`
2. Check notification `read` property is `false`
3. Ensure useEffect is calculating count correctly
4. Check motion.span is rendering (initial animation state)
5. Verify glowColor is not undefined

### Dashboard "Open Chat" Button Missing

**Symptoms**: No way to open chat from dashboard-only view

**Checklist**:
1. Verify `onOpenChat` prop is passed
2. Check `isChatOpen` is `false` (button hidden when chat visible)
3. Ensure `uiState === UI_STATE_DASHBOARD_OPEN`
4. Check `lastActiveWing` is tracked correctly

### State Transitions Broken

**Symptoms**: Wrong state after opening/closing wings

**Checklist**:
1. Verify `wasChatSpotlightRef.current` is set before `openDashboard()`
2. Check `closeDashboard()` logic respects spotlight history
3. Ensure `closeChat()` transitions to correct state
4. Verify `closeAll()` resets all state properly
5. Check IrisOrb click handler calls correct method

### Animation Jank

**Symptoms**: Choppy transitions between states

**Solutions**:
1. Use `will-change: transform` on animated elements
2. Ensure `transform` and `opacity` are the only animated properties
3. Check for layout thrashing (reading layout properties during animation)
4. Reduce animation duration for lower-end devices
5. Use Framer Motion's `layout` prop sparingly

---

## File Locations

| Component | Path |
|-----------|------|
| ChatView | `IRISVOICE/components/chat-view.tsx` |
| DashboardWing | `IRISVOICE/components/dashboard-wing.tsx` |
| DarkGlassDashboard | `IRISVOICE/components/dark-glass-dashboard.tsx` |
| useUILayoutState | `IRISVOICE/hooks/useUILayoutState.ts` |
| IrisOrb | `IRISVOICE/components/iris/IrisOrb.tsx` |
| IrisApertureIcon | `IRISVOICE/components/ui/IrisApertureIcon.tsx` |
| Main Page | `IRISVOICE/app/page.tsx` |

---

## Implementation Notes

### Critical Implementation Details

1. **Never modify wing dimensions** (255px, 280px) - These are fixed by design
2. **Always use percentage-based vertical centering** - Ensures consistent positioning
3. **Track spotlight history with refs** - Required for correct state transitions
4. **Use Framer Motion for animations** - Provides smooth, GPU-accelerated transitions
5. **Maintain z-index hierarchy** - Wings (50) < Modals (100) < Notifications (200)

### State Machine Rules

1. `UI_STATE_IDLE` → No wings visible
2. `UI_STATE_CHAT_OPEN` → Chat spotlight mode, IrisOrb visible
3. `UI_STATE_DASHBOARD_OPEN` → Dashboard spotlight mode, IrisOrb visible
4. `UI_STATE_BOTH_OPEN` → Both wings visible, balanced mode

### Transition Rules

- Opening dashboard from chat → Track `wasChatSpotlightRef`
- Closing dashboard when both open → Check `wasChatSpotlightRef` for destination
- Closing chat when both open → Always go to `UI_STATE_DASHBOARD_OPEN`
- IrisOrb click when both open → Close both simultaneously

### Testing Checklist

- [ ] ChatWing opens from idle
- [ ] DashboardWing opens from idle (solo mode)
- [ ] Dashboard opens from ChatWing (chat spotlight tracked)
- [ ] Closing Dashboard returns to chat spotlight (if opened from chat)
- [ ] Closing Dashboard goes to idle (if opened solo)
- [ ] Closing Chat goes to dashboard spotlight (if both were open)
- [ ] IrisOrb closes both when both are open
- [ ] Notification badge appears with unread count
- [ ] Notification panel slides open/closed
- [ ] Dashboard shows "Open Chat" button in solo mode
- [ ] All animations are smooth (60fps)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-03-03 | Initial comprehensive documentation |

---

## Related Documentation

- [Wing-screen-design.md](../Wing-screen-design.md) - Original design specification
- [orb-design.md](./orb-design.md) - IrisOrb design specifications
- [UI_ARCHITECTURE.md](./UI_ARCHITECTURE.md) - Overall UI architecture
- [SYSTEM_OVERVIEW.md](./SYSTEM_OVERVIEW.md) - Backend system overview

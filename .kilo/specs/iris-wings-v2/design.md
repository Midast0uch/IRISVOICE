# Design: IRIS Wings V2

## Overview

This design implements a **futuristic HUD (Heads-Up Display)** system for the IRIS assistant's wing components. The architecture maintains strict dimensional constraints while introducing a universal notification system, convergent-corner message bubbles, live TTS highlighting, and a flexible dashboard configuration. The visual language uses a **holographic monochrome palette** with glow-color accents derived from the active theme.

### HUD Design Principles
1. **Transparency & Depth**: Glass-like panels with backdrop blur and inner glows
2. **Edge Lighting**: Fresnel effects and chromatic aberration for futuristic feel
3. **Spatial Orientation**: Convergent corners pointing toward the Orb as the focal center
4. **Information Hierarchy**: Monochrome base with glow-color accents for critical elements
5. **Motion Design**: Smooth, purposeful animations that guide attention

### Key Architectural Decisions
- Inline notification system shared between ChatWing and DashboardWing
- Convergent corners (sharp toward center/Orb) for spatial orientation
- Border-only input design for command-line aesthetic
- Flexible category structure for future configuration refactoring
- Direct WebSocket integration using existing `sendMessage` and context hooks

---

## Architecture

### Component Hierarchy

```
ChatWing (chat-view.tsx)
├── Notification State (shared hook pattern)
│   ├── notifications[]
│   ├── showNotifications
│   └── unreadCount
├── Header (48px, HUD style)
│   ├── Global Error Line (conditional, animated)
│   ├── Pulse Indicator (animated, glow color)
│   ├── Title ("IRIS Assistant", tracking-wide)
│   └── Icon Group (flex gap-0.5)
│       ├── Notifications (bell + badge)
│       ├── History (with active state)
│       ├── Dashboard
│       └── Close
├── Notification Panel (conditional, AnimatePresence)
│   ├── Header ("Notifications" + Clear all)
│   └── NotificationList (scrollable, max-h 50%)
│       └── NotificationItem (type-colored, actions)
├── Messages Area (flex-1, overflow-y-auto)
│   ├── UserBubble (convergent left, 85% width)
│   ├── IRISBubble (convergent right, TTS highlight)
│   └── TypingIndicator (3 bouncing dots)
└── Input Area (HUD command line)
    ├── Border-only Input (bottom border, 2px)
    ├── Status Indicator (REC or char count)
    └── Floating Send Button (36px, chromatic aberration)
    └── Voice Waveform (12 bars, conditional)

DashboardWing (dashboard-wing.tsx)
├── Notification State (same pattern as ChatWing)
├── Container (280px, HUD glass panel)
│   ├── Scanline Overlay
│   ├── Noise Texture Overlay
│   ├── Inner Glow Effect (left edge)
│   ├── Edge Fresnel Effect (1px gradient)
│   └── DarkGlassDashboard
└── Header (44px, HUD style)
    ├── Pulse Indicator
    ├── Title ("IRIS Dashboard")
    ├── Notifications
    └── Close

DarkGlassDashboard (dark-glass-dashboard.tsx)
├── Tab Bar (collapsible, layoutId animation)
│   ├── Visible Tabs (up to 5, icon + label)
│   ├── More Button (if categories > 5)
│   └── Active Indicator (motion.div layoutId)
├── Category Header (sticky, gradient bg)
│   ├── Icon (in rounded box)
│   ├── Label + Field Count
│   └── Reset Button
├── Fields Panel (full-width, scrollable)
│   └── FieldRow[] (memoized, 48px height)
│       ├── FieldControl (type-specific)
│       └── Error Display (conditional)
└── Confirm Bar (fixed bottom, shine effect)
    └── Confirm Button (with sweep animation)
```

---

## Data Models

### Notification Type

```typescript
interface Notification {
  id: string;
  type: 'alert' | 'permission' | 'error' | 'task' | 'completion';
  title: string;
  message: string;
  timestamp: Date;
  read: boolean;
  progress?: number; // For task type (0-100)
}

// WebSocket message types
interface NotificationMessage {
  type: 'notification';
  payload: Notification;
}

interface NotificationResponseMessage {
  type: 'notification_response';
  payload: {
    notification_id: string;
    response: 'allow' | 'deny';
  };
}
```

### Dashboard Category (Flexible)

```typescript
interface DashboardCategory {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  fields: DashboardField[];
}

interface DashboardField {
  id: string;
  type: 'toggle' | 'dropdown' | 'slider' | 'text' | 'password' | 'button' | 'section' | 'info';
  label: string;
  description?: string;
  options?: string[];
  defaultValue?: any;
  min?: number;
  max?: number;
  unit?: string;
  placeholder?: string;
  onClick?: () => void;
}
```

### Message Type (Extended)

```typescript
interface Message {
  id: string;
  text: string;
  sender: 'user' | 'assistant' | 'error';
  timestamp: Date;
  errorType?: 'agent' | 'voice' | 'validation';
  words?: string[]; // For TTS highlighting
  currentWordIndex?: number; // Index of currently spoken word
}

// From useNavigation context
interface NavigationContextValue {
  voiceState: 'idle' | 'listening' | 'processing_conversation' | 'processing_tool' | 'speaking' | 'error';
  audioLevel: number; // 0-1
  activeTheme: {
    glow: string;
    primary: string;
    font: string;
  };
  fieldErrors: Record<string, string>; // "subnodeId:fieldId" -> error message
  sendMessage: (type: string, payload?: Record<string, unknown>) => boolean;
  updateMiniNodeValue: (subnodeId: string, fieldId: string, value: any) => void;
  confirmMiniNode: (subnodeId: string, values: Record<string, any>) => void;
  clearFieldError: (subnodeId: string, fieldId: string) => void;
  clearChat: () => void;
}
```

---

## Backend Integration Points

### WebSocket Message Handling

```typescript
// In ChatWing/DashboardWing useEffect
useEffect(() => {
  const handleMessage = (event: MessageEvent) => {
    try {
      const message = JSON.parse(event.data);
      
      switch (message.type) {
        case 'notification':
          setNotifications(prev => [...prev, message.payload]);
          break;
          
        case 'tts_word':
          // Update currentWordIndex for TTS highlighting
          setCurrentWordIndex(message.payload.word_index);
          break;
          
        case 'tts_end':
          setCurrentWordIndex(-1);
          break;
      }
    } catch (err) {
      console.error('[WebSocket] Failed to parse message:', err);
    }
  };

  window.addEventListener('message', handleMessage);
  return () => window.removeEventListener('message', handleMessage);
}, []);
```

### Backend Message Sending

```typescript
// Permission response
const handlePermissionResponse = (notificationId: string, response: 'allow' | 'deny') => {
  sendMessage('notification_response', {
    notification_id: notificationId,
    response
  });
  
  // Remove notification from local state
  setNotifications(prev => prev.filter(n => n.id !== notificationId));
};

// Field updates (already implemented in DarkGlassDashboard)
const handleFieldChange = (subnodeId: string, fieldId: string, value: any) => {
  updateMiniNodeValue(subnodeId, fieldId, value);
};

// Confirm changes
const handleConfirm = () => {
  if (selectedSub) {
    const values = selectedSub.fields.reduce((acc, field) => {
      acc[field.id] = fieldValues[selectedSub.id]?.[field.id] ?? field.defaultValue;
      return acc;
    }, {} as Record<string, any>);
    
    confirmMiniNode(selectedSub.id, values);
  }
};
```

---

## Interface Changes

### ChatWing Props (No Change)

```typescript
interface ChatWingProps {
  isOpen: boolean;
  onClose: () => void;
  onDashboardClick: () => void;
  sendMessage?: SendMessageFunction;
  fieldValues?: Record<string, any>;
  updateField?: (subnodeId: string, fieldId: string, value: any) => void;
}
```

### DashboardWing Props (No Change)

```typescript
interface DashboardWingProps {
  isOpen: boolean;
  onClose: () => void;
  sendMessage?: SendMessageFunction;
  fieldValues?: Record<string, any>;
  updateField?: (subnodeId: string, fieldId: string, value: any) => void;
}
```

### DarkGlassDashboard Props (Extended)

```typescript
interface DarkGlassDashboardProps {
  theme?: string;
  fieldValues?: Record<string, Record<string, string | number | boolean>>;
  updateField?: (subnodeId: string, fieldId: string, value: any) => void;
  // New optional props for flexible structure
  categories?: DashboardCategory[];
  onConfirm?: () => void;
  glowColor?: string; // Override from activeTheme
}
```

---

## Sequence Diagrams

### Notification Flow (with Backend)

```
Backend                    ChatWing                  User
  |                          |                       |
  |---notification msg------>|                       |
  |                          |--add to state------->|
  |                          |--show badge--------->|
  |                          |                       |
  |                          |<--------click bell---|
  |                          |                       |
  |                          |--open panel--------->|
  |                          |--mark all read------>|
  |                          |                       |
  |<---notification_response-|
  | (permission response)    |                       |
  |                          |--remove from state-->|
```

### TTS Word Highlighting Flow

```
Backend           ChatWing          IRISBubble           Word Span
  |                  |                  |                    |
  |--tts_word------->|                  |                    |
  |   {word_index}   |--update index-->|                    |
  |                  |                  |                    |
  |                  |                  |--animate current-->|
  |                  |                  |   glow + shadow    |
  |                  |                  |                    |
  |--tts_word------->|                  |                    |
  |   (next word)    |--update index-->|                    |
  |                  |                  |--fade previous--->|
  |                  |                  |--animate new----->|
  |                  |                  |                    |
  |--tts_end-------->|                  |                    |
  |                  |--reset index--->|                    |
  |                  |                  |--clear highlight-->|
```

### Dashboard Field Update Flow

```
User            FieldControl       DarkGlassDashboard      NavigationContext     Backend
  |                  |                    |                      |                |
  |--change value--->|                    |                      |                |
  |                  |--onChange--------->|                      |                |
  |                  |                    |--updateMiniNodeValue->|               |
  |                  |                    |                      |--send WS msg-->|
  |                  |                    |                      |                |
  |                  |                    |<--fieldErrors (if err)|<--validation---|
  |                  |                    |                      |                |
  |                  |<--show error-------|                      |                |
  |<--error display--|                    |                      |                |
```

---

## HUD Styling Specifications

### Transparent Background Contrast

Since both wings are displayed with transparent backgrounds, the following ensures readability:

| Element | Value | Purpose |
|---------|-------|---------|
| Container background | `rgba(10, 10, 20, 0.95)` minimum | Dark base for contrast |
| Backdrop blur | `blur(24px)` | Visual separation from background |
| Primary text | `rgba(255, 255, 255, 0.85-0.95)` | High contrast white |
| Secondary text | `rgba(255, 255, 255, 0.55-0.60)` | Readable but de-emphasized |
| Glow accents | 50%+ opacity | Visible against dark bg |
| Borders | `rgba(255, 255, 255, 0.08)` minimum | Distinguish elements |

### Glass Panel Effect

```typescript
// Container styling for both wings
const glassPanelStyles = {
  background: 'linear-gradient(135deg, rgba(12,12,24,0.95) 0%, rgba(8,8,16,0.98) 100%)',
  backdropFilter: 'blur(24px)',
  border: '1px solid rgba(255,255,255,0.08)',
  boxShadow: `
    inset -8px 0 32px ${glowColor}15,  // inner glow facing Orb
    24px 0 60px rgba(0,0,0,0.5),       // outer shadow
    0 0 0 1px rgba(255,255,255,0.03)   // subtle border
  `,
};
```

### Scanline Overlay

```typescript
// Absolute positioned overlay
const scanlineOverlay = {
  position: 'absolute',
  inset: 0,
  pointerEvents: 'none',
  zIndex: 10,
  background: 'linear-gradient(transparent 50%, rgba(0,0,0,0.02) 50%)',
  backgroundSize: '100% 4px',
  opacity: 0.6,
  mixBlendMode: 'overlay',
  borderRadius: 'inherit',
};
```

### Noise Texture Overlay

```typescript
// SVG noise filter overlay
const noiseOverlay = {
  position: 'absolute',
  inset: 0,
  pointerEvents: 'none',
  zIndex: 10,
  opacity: 0.03,
  backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`,
  borderRadius: 'inherit',
};
```

### Edge Fresnel Effect (DashboardWing)

```typescript
// Left edge glow
const fresnelEffect = {
  position: 'absolute',
  left: 0,
  top: 0,
  bottom: 0,
  width: '1px',
  background: `linear-gradient(
    180deg,
    transparent 0%,
    ${glowColor}40 20%,
    ${glowColor}60 50%,
    ${glowColor}40 80%,
    transparent 100%
  )`,
  pointerEvents: 'none',
};
```

### Chromatic Aberration on Hover

```typescript
// Applied to interactive elements
const chromaticAberration = {
  position: 'relative',
  '&:hover::after': {
    content: ' "" ',
    position: 'absolute',
    inset: 0,
    borderRadius: 'inherit',
    boxShadow: 'inset -1px 0 0 rgba(255,0,0,0.3), inset 1px 0 0 rgba(0,0,255,0.3)',
    pointerEvents: 'none',
  },
};
```

---

## Key Design Decisions

### Decision 1: Inline Notification State
**Choice:** Keep notification state within each wing component using useState, not a context.

**Rationale:**
- Notifications are wing-specific UI concerns
- No need for global notification context (not a core feature)
- Simpler implementation, less prop drilling
- Both wings can have independent notification panels

**Backend Integration:**
- Notifications received via WebSocket `notification` message type
- Responses sent via `notification_response` message type

### Decision 2: Convergent Corners
**Choice:** Use asymmetrical border-radius where the corner facing the Orb is sharp (4px) and outer corners are rounded (16px).

**Rationale:**
- Creates visual flow toward the Orb as center
- Spatially orients user within the IRIS interface
- Modern aesthetic different from standard chat bubbles
- Reinforces the HUD metaphor (information directed at center)

### Decision 3: Border-Only Input
**Choice:** Replace filled input with bottom-border-only design.

**Rationale:**
- Reduces visual weight of input area
- Creates clean horizontal line aesthetic
- Voice waveform has room to breathe below
- Floating send button provides clear action
- Resembles command-line interfaces (futuristic feel)

### Decision 4: Flexible Dashboard Categories
**Choice:** Accept categories as props with dynamic rendering instead of hardcoded tabs.

**Rationale:**
- Configuration structure is being refactored
- Allows backend-driven category changes
- Supports "More" collapse without code changes
- Future-proofs against settings reorganization

---

## Error Handling & Edge Cases

### Notification Panel

| Edge Case | Handling |
|-----------|----------|
| 50+ notifications | Panel scrolls, max-height 50% of wing |
| Permission without handler | Buttons disabled with tooltip |
| Task without progress | Shows 0%, no progress bar animation |
| Notification while panel open | Auto-marked read, no badge shown |
| Rapid notification clicks | Debounced toggle (150ms) |
| Unknown notification type | Defaults to glow color + Info icon |

### Message Bubbles

| Edge Case | Handling |
|-----------|----------|
| Message > 500 chars | Max-width 85%, wraps naturally |
| TTS word index out of sync | Graceful fallback to static text |
| Voice state error | Shows error bubble with retry hint |
| Empty message send | Button disabled, no action |

### Dashboard Fields

| Edge Case | Handling |
|-----------|----------|
| Field without options | Shows placeholder, disabled state |
| Slider min > max | Swaps values, logs warning |
| Dropdown with 20+ options | Native select with search (browser) |
| Validation error | Red border, error icon, message below |
| Backend disconnected | Shows offline indicator in header |

---

## Testing Strategy

### Visual Regression Tests
- ChatWing header at all states (idle, listening, error)
- Notification panel with all notification types
- Message bubbles with various content lengths
- Dashboard tabs with 3, 5, and 8 categories
- HUD effects (scanlines, noise, edge glow)

### Unit Tests
- Notification state management (add, mark read, clear)
- Field control rendering (all 7 types)
- TTS word highlighting logic
- Convergent corner radius calculation
- Helper functions (getNotificationColor, etc.)

### Integration Tests
- Opening notification closes history dropdown
- Sending message clears input and shows bubble
- Dashboard confirm sends correct payload
- Theme color propagation to all components
- WebSocket notification handling

### Accessibility Tests
- Keyboard navigation through header icons
- Screen reader announcements for notifications
- Focus visible states on all interactive elements
- Reduced motion preference respected

---

## Performance Considerations

### GPU Acceleration
- All animations use `transform` and `opacity` only
- `will-change` applied to animated message bubbles
- `layoutId` animations for tab indicators (Framer Motion optimization)

### Memoization
- `FieldRow` memoized to prevent re-render on unchanged fields
- `getNotificationColor` and `getNotificationIcon` use useCallback
- Dashboard categories memoized to prevent recalculation

### Lazy Loading
- Notification panel content only renders when open
- Dashboard fields use virtualization if > 20 fields
- Icons imported individually (tree-shaking)

### Bundle Size
- Lucide icons: individual imports (not full library)
- Framer Motion: use `m` (motion) for simple animations
- No additional dependencies beyond existing stack

---

## CSS Custom Properties (Theme Integration)

```css
/* Derived from activeTheme */
--glow-color: #00d4ff;      /* activeTheme.glow */
--primary-color: #00d4ff;   /* activeTheme.primary */
--font-color: #ffffff;      /* activeTheme.font */

/* Holographic palette */
--bg-deep: rgba(10, 10, 20, 0.98);
--bg-surface: rgba(255, 255, 255, 0.03);
--bg-elevated: rgba(255, 255, 255, 0.06);

/* Text hierarchy */
--text-muted: rgba(255, 255, 255, 0.35);
--text-secondary: rgba(255, 255, 255, 0.55);
--text-body: rgba(255, 255, 255, 0.85);
--text-bright: rgba(255, 255, 255, 0.95);

/* Notification colors */
--color-alert: #fbbf24;
--color-permission: #3b82f6;
--color-error: #ef4444;
--color-task: #a855f7;
--color-completion: #22c55e;

/* HUD effects */
--scanline-opacity: 0.6;
--noise-opacity: 0.03;
--edge-glow-opacity: 0.15;
--chromatic-aberration: 0.3px;
```

---

## Animation Specifications

| Animation | Duration | Easing | Properties |
|-----------|----------|--------|------------|
| Wing entrance | 400ms | spring (280, 25) | x, opacity, scale |
| Notification panel | 200ms | [0.22, 1, 0.36, 1] | height, opacity |
| Message bubble | 200ms | ease-out | opacity, y, scale |
| Pulse indicator | 1200ms | easeInOut | scale, opacity |
| Send button hover | 200ms | ease | scale, boxShadow |
| Tab indicator | 300ms | spring | layoutId |
| TTS word highlight | 150ms | ease | color, textShadow |
| Voice waveform bar | 500ms | easeInOut | height, opacity |
| Confirm shine | 2000ms | linear | background-position |
| Badge scale | 200ms | spring | scale |
| Error shake | 300ms | ease | x (±5px) |
| REC blink | 1000ms | steps(1) | opacity |

---

## Backend Integration Reference

### WebSocket Message Types

```typescript
// Backend → Frontend
interface NotificationMessage {
  type: 'notification';
  payload: {
    id: string;
    type: 'alert' | 'permission' | 'error' | 'task' | 'completion';
    title: string;
    message: string;
    timestamp: Date;
    read: boolean;
    progress?: number;
  };
}

interface TTSWordMessage {
  type: 'tts_word';
  payload: { word_index: number };
}

interface TTSEndMessage {
  type: 'tts_end';
  payload: {};
}

// Frontend → Backend
interface NotificationResponseMessage {
  type: 'notification_response';
  payload: {
    notification_id: string;
    response: 'allow' | 'deny';
  };
}
```

### Python Backend Handlers (Reference)

```python
# IRISVOICE/backend/gateway/iris_gateway.py

async def handle_notification_response(self, client_id: str, payload: dict):
    """Handle user response to permission notifications"""
    notification_id = payload.get('notification_id')
    response = payload.get('response')  # 'allow' or 'deny'
    # Process permission grant/deny...
    
async def send_notification(self, client_id: str, notification: dict):
    """Send notification to specific client"""
    await self.send_to_client(client_id, {
        'type': 'notification',
        'payload': notification
    })
    
async def send_tts_word(self, client_id: str, word_index: int):
    """Send current TTS word index for highlighting"""
    await self.send_to_client(client_id, {
        'type': 'tts_word',
        'payload': {'word_index': word_index}
    })
```

### Existing Context Integration (No Changes Required)

The following are already available from existing contexts:
- `voiceState`, `audioLevel` from `useNavigation()`
- `activeTheme.glow/primary/font` from `useNavigation()`
- `fieldErrors` from `useNavigation()`
- `sendMessage` from `useNavigation()`
- `updateMiniNodeValue` from `useNavigation()`
- `confirmMiniNode` from `useNavigation()`
- `clearFieldError` from `useNavigation()`
- `useReducedMotion` hook at `hooks/useReducedMotion.ts`

### Potential Issues & Solutions

| Issue | Solution |
|-------|----------|
| Backend doesn't send `tts_word` | Graceful fallback - disable TTS highlighting |
| Notification sync between wings | Use independent state per wing (simpler) |
| History feature not implemented | History shows conversation dropdown (Option C) |
| Field validation errors | Format: `fieldErrors["{subnodeId}:{fieldId}"]` |
| Dimension changes (231→255px) | Safe - positioning internal to components |

### Files Modified by This Spec

1. `IRISVOICE/components/chat-view.tsx` - ChatWing component
2. `IRISVOICE/components/dashboard-wing.tsx` - DashboardWing component  
3. `IRISVOICE/components/dark-glass-dashboard.tsx` - Dashboard content

### Backend Files Requiring Updates (Optional)

1. `IRISVOICE/backend/gateway/iris_gateway.py` - Add notification handlers
2. `IRISVOICE/backend/gateway/message_router.py` - Add message types
3. `IRISVOICE/backend/ws_manager.py` - WebSocket broadcast methods

### Critical Success Factors

1. **Dimensions Exact:** ChatWing 255px, DashboardWing 280px, both 50vh
2. **No New Dependencies:** Use existing Framer Motion, Lucide, Tailwind
3. **Backend Integration:** Handle `notification`, `tts_word` messages
4. **Error Handling:** Try-catch on all WebSocket parsing
5. **Performance:** 60fps animations, memoized components

### Ready for Execution

**Status:** ✅ SPEC APPROVED

**To execute:**
```
Switch to ⚡ Spec: Execute mode
Say: "Execute the spec in .kilo/specs/iris-wings-v2/"
```

**Estimated Time:** 16 hours  
**Risk Level:** Medium  
**Fallback Strategy:** Features work independently (TTS can be disabled, notifications work locally)

# Implementation Plan: IRIS Wings V2

---

## Task Group 1: Notification System Foundation

### 1.1 Add Notification Types and Helper Functions
- **What to build:** TypeScript interfaces for Notification and helper functions for colors/icons
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx` (add at top)
- **Requirements:** 1.6, 1.11, 1.12
- **Implementation notes:**
  ```typescript
  // Add after imports
  import { Bell, AlertTriangle, Shield, AlertCircle, Loader, CheckCircle, Info, History, RotateCcw, MoreHorizontal } from 'lucide-react';

  interface Notification {
    id: string;
    type: 'alert' | 'permission' | 'error' | 'task' | 'completion';
    title: string;
    message: string;
    timestamp: Date;
    read: boolean;
    progress?: number;
  }

  const getNotificationColor = (type: string, glowColor: string) => {
    switch (type) {
      case 'alert': return '#fbbf24';
      case 'permission': return '#3b82f6';
      case 'error': return '#ef4444';
      case 'task': return '#a855f7';
      case 'completion': return '#22c55e';
      default: return glowColor;
    }
  };

  const getNotificationIcon = (type: string, glowColor: string) => {
    const props = { size: 10, style: { color: getNotificationColor(type, glowColor) } };
    switch (type) {
      case 'alert': return <AlertTriangle {...props} />;
      case 'permission': return <Shield {...props} />;
      case 'error': return <AlertCircle {...props} />;
      case 'task': return <Loader {...props} className="animate-spin" />;
      case 'completion': return <CheckCircle {...props} />;
      default: return <Info {...props} />;
    }
  };
  ```

### 1.2 Add Notification State and WebSocket Handler to ChatWing
- **What to build:** useState hooks for notifications, showNotifications, unreadCount + WebSocket listener
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx`
- **Requirements:** 1.2, 1.3, 1.5, 1.11
- **Implementation notes:**
  ```typescript
  // Inside ChatWing component, add after existing state:
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [showHistory, setShowHistory] = useState(false);
  const [currentWordIndex, setCurrentWordIndex] = useState(-1); // For TTS

  // Calculate unread count
  useEffect(() => {
    setUnreadCount(notifications.filter(n => !n.read).length);
  }, [notifications]);

  // Mark all read when panel opens
  useEffect(() => {
    if (showNotifications) {
      setNotifications(prev => prev.map(n => ({ ...n, read: true })));
    }
  }, [showNotifications]);

  // WebSocket message handler for notifications
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      try {
        const message = JSON.parse(event.data);
        if (message.type === 'notification') {
          setNotifications(prev => [...prev, message.payload]);
        } else if (message.type === 'tts_word') {
          setCurrentWordIndex(message.payload.word_index);
        } else if (message.type === 'tts_end') {
          setCurrentWordIndex(-1);
        }
      } catch (err) {
        console.error('[ChatWing] Failed to parse WebSocket message:', err);
      }
    };

    // Note: In actual implementation, hook into existing WebSocket
    // This is a placeholder for the pattern
    return () => {
      // Cleanup
    };
  }, []);
  ```

### 1.3 Create HUD-Style Notification Bell Component (ChatWing Header)
- **What to build:** Bell icon button with unread badge between Title and History
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx` (header section)
- **Requirements:** 1.1, 1.3, 1.4, 2.1, 2.6
- **Implementation notes:** Replace existing header (lines 164-213) with new 48px header. Use HUD styling with glow color accents. Icon order: Pulse | Title | Notifications | History | Dashboard | Close. Include border-bottom with glowColor at 15% opacity.

### 1.4 Create Notification Panel Component
- **What to build:** Animated dropdown panel with notification list, type colors, action buttons
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx`
- **Requirements:** 1.4, 1.6, 1.7, 1.8, 1.9, 8.1
- **Implementation notes:** Add AnimatePresence wrapped panel after header. Panel max-height 50%, holographic background (rgba(10,10,20,0.98)), includes Clear all button, type-specific styling with left border accent, permission action buttons, task progress bars with glow color fill.

### 1.5 Implement Dropdown Exclusivity
- **What to build:** Ensure only one dropdown (History or Notifications) is open at a time
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx`
- **Requirements:** 1.10, 2.2
- **Implementation notes:** When opening notifications: `setShowNotifications(!showNotifications); setShowHistory(false);`. When opening history: `setShowHistory(!showHistory); setShowNotifications(false);`. When opening dashboard/close: close both.

### 1.6 Add Permission Response Handler
- **What to build:** Send notification_response WebSocket message when Allow/Deny clicked
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx`
- **Requirements:** 1.7, 1.12, 10.2
- **Implementation notes:**
  ```typescript
  const handlePermissionResponse = (notificationId: string, response: 'allow' | 'deny') => {
    sendMessage?.('notification_response', {
      notification_id: notificationId,
      response
    });
    setNotifications(prev => prev.filter(n => n.id !== notificationId));
  };
  ```

---

## Task Group 2: ChatWing HUD Visual Redesign

### 2.1 Update ChatWing Container (HUD Glass Panel)
- **What to build:** Apply inner glow, updated background gradient, scanline/noise overlays
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx`
- **Requirements:** 8.1, 8.2, 8.3, 8.7, 9.1, 9.4
- **Implementation notes:**
  - Width: 255px (update from 231px)
  - Left: 3%
  - Background: `linear-gradient(135deg, rgba(12,12,24,0.95) 0%, rgba(8,8,16,0.98) 100%)`
  - Backdrop-filter: blur(24px)
  - Box-shadow: `inset -8px 0 32px ${glowColor}15, 24px 0 60px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.03)`
  - Border: 1px solid rgba(255,255,255,0.08)
  - Add scanline overlay div as sibling
  - Add noise texture overlay div as sibling

### 2.2 Update Message Bubble Styling (User - Convergent Corners)
- **What to build:** Convergent corner border-radius for user messages with HUD effects
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx` (user message render)
- **Requirements:** 3.1, 3.3, 3.6, 3.7
- **Implementation notes:**
  - `borderRadius: '16px 16px 4px 16px'` (sharp left toward Orb)
  - Add subtle glow overlay div that fades on send (300ms)
  - `boxShadow: '0 4px 20px rgba(0,0,0,0.3)'`
  - Font sizes: message text 13px, timestamp 9px tabular-nums
  - Max-width: 85%

### 2.3 Update Message Bubble Styling (IRIS - TTS Highlighting)
- **What to build:** Convergent corners, TTS highlighting, speaking indicator
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx` (IRIS message render)
- **Requirements:** 3.2, 3.4, 3.5, 3.8
- **Implementation notes:**
  - `borderRadius: '16px 16px 16px 4px'` (sharp right toward Orb)
  - `borderLeft: 2px solid ${glowColor}50`
  - Split text into words array for TTS highlighting
  - Animate current word with glow color and `textShadow: 0 0 12px ${glowColor}60`
  - Add 3-dot speaking indicator with staggered delays (0ms, 150ms, 300ms)
  - Smooth 150ms transition between words

### 2.4 Redesign Input Area (HUD Command Line)
- **What to build:** Border-only input, floating send button, voice waveform
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx` (input section)
- **Requirements:** 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8
- **Implementation notes:**
  - Remove filled background, use bottom border only (2px)
  - Border color animates with audioLevel when listening (alpha modulation)
  - Gradient fade background from deep black to transparent
  - Top-right: "● REC" indicator (blinking) when listening, char count when typing
  - Floating circular send button (36px) positioned outside input
  - Chromatic aberration on hover: `boxShadow: 'inset -1px 0 0 rgba(255,0,0,0.3), inset 1px 0 0 rgba(0,0,255,0.3)'`
  - Voice waveform: 12 bars, 50ms staggered delays

### 2.5 Add Global Error Line to Header
- **What to build:** Animated red line at top of header when global error occurs
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx` (header)
- **Requirements:** 2.2
- **Implementation notes:** Add motion.div absolute positioned at top of header with pulsing opacity animation (2s infinite) when voiceState === 'error' or globalError prop is true.

---

## Task Group 3: DashboardWing HUD Redesign

### 3.1 Update DashboardWing Container (HUD Glass Panel)
- **What to build:** Inner glow, edge Fresnel effect, updated dimensions
- **Files to create/modify:** `IRISVOICE/components/dashboard-wing.tsx`
- **Requirements:** 5.3, 5.4, 8.5, 8.7, 9.2, 9.5
- **Implementation notes:**
  - Width: 280px (update from 248px)
  - Right: 3%
  - Background: `linear-gradient(225deg, rgba(12,12,24,0.95) 0%, rgba(8,8,16,0.98) 100%)`
  - Backdrop-filter: blur(24px)
  - Box-shadow: `inset 8px 0 32px ${glowColor}15, -24px 0 60px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.03)`
  - Border: 1px solid rgba(255,255,255,0.08)
  - Add Fresnel edge: 1px gradient line on left with glow color
  - Add scanline and noise overlays (same as ChatWing)

### 3.2 Add Notification System to DashboardWing
- **What to build:** Same notification state, bell icon, and panel as ChatWing
- **Files to create/modify:** `IRISVOICE/components/dashboard-wing.tsx`
- **Requirements:** 1.2, 5.1, 5.2
- **Implementation notes:** Copy notification types, state hooks, helper functions from ChatWing. Add bell icon between title and Close. Header height 44px (vs ChatWing 48px). Icon order: Pulse | Title | Notifications | Close. Include border-bottom with glowColor at 12% opacity.

### 3.3 Add WebSocket Handler to DashboardWing
- **What to build:** Listen for notification messages from backend
- **Files to create/modify:** `IRISVOICE/components/dashboard-wing.tsx`
- **Requirements:** 1.11
- **Implementation notes:** Same WebSocket message handler pattern as ChatWing (Task 1.2). Notifications should sync between wings or be independent - discuss with user if needed.

---

## Task Group 4: DarkGlassDashboard HUD Refactoring

### 4.1 Add Flexible Category Structure
- **What to build:** Props interface for dynamic categories, collapsible "More" tab
- **Files to create/modify:** `IRISVOICE/components/dark-glass-dashboard.tsx`
- **Requirements:** 6.1, 6.2, 6.3
- **Implementation notes:**
  ```typescript
  interface DashboardCategory {
    id: string;
    label: string;
    icon: React.ComponentType<{ className?: string }>;
    fields: DashboardField[];
  }
  
  // Add to props
  categories?: DashboardCategory[];
  
  // State for More dropdown
  const [showMore, setShowMore] = useState(false);
  const visibleCount = 5;
  ```

### 4.2 Update Tab Bar with layoutId Animation
- **What to build:** Animated active indicator using Framer Motion layoutId
- **Files to create/modify:** `IRISVOICE/components/dark-glass-dashboard.tsx` (tab bar)
- **Requirements:** 6.4
- **Implementation notes:** Replace existing tab indicator with `<motion.div layoutId="dashboard-tab" />`. Each tab shows icon (18px) and 6px uppercase label. Use existing MAIN_NODES_DATA as default if categories prop not provided.

### 4.3 Add Category Header
- **What to build:** Header showing active category icon, label, and field count
- **Files to create/modify:** `IRISVOICE/components/dark-glass-dashboard.tsx`
- **Requirements:** 6.5
- **Implementation notes:** Sticky header with gradient background (`linear-gradient(90deg, ${glowColor}10 0%, rgba(10,10,20,0.95) 60%)`), icon in rounded box (glowColor at 15% bg), reset button with RotateCcw icon.

### 4.4 Refactor Fields Panel (HUD Controls)
- **What to build:** Full-width field rows with 48px height, no sidebar
- **Files to create/modify:** `IRISVOICE/components/dark-glass-dashboard.tsx` (fields area)
- **Requirements:** 6.6, 6.7, 7.1, 7.2, 7.3, 7.4, 7.5, 7.7
- **Implementation notes:**
  - Remove sidebar navigation (currently has subnode list)
  - FieldRow memoized component with hover bg effect (white/2%)
  - Toggle: 40×20px with spring thumb (stiffness 500, damping 30)
  - Dropdown: white/6% bg, hover border white/12%, focus border glowColor/40
  - Slider: clickable track with gradient fill (glowColor 80% to 100%), numeric display
  - Text/Password: same styling as dropdown, caret-color: glowColor
  - Button: glowColor border (35% opacity), bg (15% opacity)
  - Apply holographic background with scanline/noise overlays

### 4.5 Add Error Display to FieldRow
- **What to build:** Error message with AlertCircle icon when validation fails
- **Files to create/modify:** `IRISVOICE/components/dark-glass-dashboard.tsx` (FieldRow)
- **Requirements:** 7.6
- **Implementation notes:** When error prop present, show red AlertCircle + error message below field with motion animation. Error key format: "{subnodeId}:{fieldId}". Use existing fieldErrors from NavigationContext.

### 4.6 Update Confirm Bar (HUD Button)
- **What to build:** Fixed bottom bar with shine animation on hover
- **Files to create/modify:** `IRISVOICE/components/dark-glass-dashboard.tsx` (confirm section)
- **Requirements:** 8.6
- **Implementation notes:** Position fixed bottom, gradient backdrop blur. Button has 2s infinite shine sweep animation using `background: linear-gradient(90deg, transparent, rgba(255,255,255,0.1), transparent)` with `animation: shine 2s infinite`.

---

## Task Group 5: Integration & Polish

### 5.1 Add Keyboard Navigation Support
- **What to build:** Tab key navigation between header icons
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx`, `IRISVOICE/components/dashboard-wing.tsx`
- **Requirements:** 10.5, 11.1
- **Implementation notes:** Ensure all icon buttons have tabIndex={0}, add focus-visible ring (2px glow color outline) using Tailwind's focus-visible: modifier.

### 5.2 Add Reduced Motion Support
- **What to build:** Respect prefers-reduced-motion media query
- **Files to create/modify:** All modified components
- **Requirements:** 10.3, 11.3
- **Implementation notes:**
  ```typescript
  const prefersReducedMotion = useReducedMotion(); // Use existing hook from hooks/useReducedMotion.ts
  // Pass to Framer Motion: transition={prefersReducedMotion ? { duration: 0 } : undefined}
  ```

### 5.3 Update Icon Imports
- **What to build:** Add all required Lucide icons
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx`, `IRISVOICE/components/dashboard-wing.tsx`
- **Requirements:** All
- **Implementation notes:** Import from 'lucide-react': Bell, AlertTriangle, Shield, AlertCircle, Loader, CheckCircle, Info, History, RotateCcw, MoreHorizontal. Already importing: Send, X, BarChart3 from existing code.

### 5.4 Integrate with NavigationContext
- **What to build:** Ensure all context values are properly used
- **Files to create/modify:** All wing components
- **Requirements:** 10.4, 10.5, 10.6, 10.7, 10.8
- **Implementation notes:**
  - Use `voiceState` and `audioLevel` from useNavigation for animations
  - Use `activeTheme.glow`, `activeTheme.primary`, `activeTheme.font` for colors
  - Use `fieldErrors` for validation display
  - Call `updateMiniNodeValue` on field changes
  - Call `confirmMiniNode` on confirm
  - Call `clearFieldError` when user starts editing

### 5.5 Verify Dimension Constraints
- **What to build:** Ensure all width/height/position values match spec exactly
- **Files to create/modify:** All wing components
- **Requirements:** 9.1, 9.2, 9.3, 9.4, 9.5
- **Implementation notes:**
  - ChatWing: 255px width, 50vh height, left: 3%, rotateY(15deg)
  - DashboardWing: 280px width, 50vh height, right: 3%, rotateY(-15deg)
  - No tolerance on these values - verify with pixel-perfect measurements

### 5.6 Add Error Boundary Wrapper
- **What to build:** Prevent crashes from notification parsing errors
- **Files to create/modify:** `IRISVOICE/components/chat-view.tsx`, `IRISVOICE/components/dashboard-wing.tsx`
- **Requirements:** 12.1
- **Implementation notes:** Wrap WebSocket message handlers in try-catch blocks. Log errors but don't crash the component.

---

## Task Group 6: Testing

### 6.1 Write Notification System Tests
- **What to build:** Unit tests for notification state management
- **Files to create/modify:** `IRISVOICE/tests/components/notifications.test.tsx` (new)
- **Requirements:** 1.2, 1.3, 1.5, 1.9
- **Implementation notes:** Test add notification, mark read on open, clear all, unread count calculation. Mock WebSocket messages.

### 6.2 Write Message Bubble Tests
- **What to build:** Visual regression tests for convergent corners
- **Files to create/modify:** `IRISVOICE/tests/components/chat-view.test.tsx`
- **Requirements:** 3.1, 3.2
- **Implementation notes:** Verify correct border-radius values for user vs IRIS bubbles. Test 85% max-width constraint.

### 6.3 Write Dashboard Field Tests
- **What to build:** Unit tests for all field control types
- **Files to create/modify:** `IRISVOICE/tests/components/dark-glass-dashboard.test.tsx`
- **Requirements:** 7.1-7.6
- **Implementation notes:** Test toggle, dropdown, slider, text, password, button rendering and interaction. Verify error display.

### 6.4 Run Full Test Suite
- **What to build:** Execute all tests and verify pass
- **Files to create/modify:** N/A
- **Requirements:** All
- **Implementation notes:** Run `npm test` and ensure no regressions in existing functionality. Check for console errors.

---

## Task Group 7: Final Verification

### 7.1 Verify All Requirements Coverage
- **What to build:** Checklist confirmation that all 67 acceptance criteria are satisfied
- **Files to create/modify:** N/A
- **Requirements:** All
- **Implementation notes:**

| Req | Criterion | Task(s) | Status |
|-----|-----------|---------|--------|
| 1.1 | ChatWing bell position | 1.3 | [ ] |
| 1.2 | DashboardWing bell position | 3.2 | [ ] |
| 1.3 | Unread indicator | 1.2, 1.3 | [ ] |
| 1.4 | Panel toggle animation | 1.4 | [ ] |
| 1.5 | Mark read on open | 1.2 | [ ] |
| 1.6 | Type colors | 1.1, 1.4 | [ ] |
| 1.7 | Permission buttons | 1.4, 1.6 | [ ] |
| 1.8 | Task progress | 1.4 | [ ] |
| 1.9 | Clear all | 1.4 | [ ] |
| 1.10 | Dropdown exclusivity | 1.5 | [ ] |
| 1.11 | WebSocket notification | 1.2 | [ ] |
| 1.12 | Permission response | 1.6 | [ ] |
| 2.1 | Header icon order | 1.3 | [ ] |
| 2.2 | Global error line | 2.5 | [ ] |
| 2.3 | Pulse animation | 1.3 | [ ] |
| 2.4 | Icon hover states | 1.3 | [ ] |
| 2.5 | History active state | 1.3 | [ ] |
| 2.6 | Header border | 1.3 | [ ] |
| 3.1 | User convergent corners | 2.2 | [ ] |
| 3.2 | IRIS convergent corners | 2.3 | [ ] |
| 3.3 | User glow effect | 2.2 | [ ] |
| 3.4 | TTS highlighting | 2.3 | [ ] |
| 3.5 | Speaking indicator | 2.3 | [ ] |
| 3.6 | Max-width 85% | 2.2, 2.3 | [ ] |
| 3.7 | Timestamp styling | 2.2, 2.3 | [ ] |
| 3.8 | Word transition | 2.3 | [ ] |
| 4.1 | Border-only input | 2.4 | [ ] |
| 4.2 | Border audio animation | 2.4 | [ ] |
| 4.3 | REC indicator | 2.4 | [ ] |
| 4.4 | Character count | 2.4 | [ ] |
| 4.5 | Floating send button | 2.4 | [ ] |
| 4.6 | Send button glow | 2.4 | [ ] |
| 4.7 | Voice waveform | 2.4 | [ ] |
| 4.8 | Send disabled states | 2.4 | [ ] |
| 5.1 | Dashboard header | 3.2 | [ ] |
| 5.2 | Dashboard notifications | 3.2 | [ ] |
| 5.3 | Inner glow | 3.1 | [ ] |
| 5.4 | Fresnel effect | 3.1 | [ ] |
| 5.5 | Header border | 3.2 | [ ] |
| 6.1 | Dynamic categories | 4.1 | [ ] |
| 6.2 | Collapsible More | 4.1 | [ ] |
| 6.3 | More dropdown | 4.1 | [ ] |
| 6.4 | layoutId animation | 4.2 | [ ] |
| 6.5 | Category header | 4.3 | [ ] |
| 6.6 | Full-width fields | 4.4 | [ ] |
| 6.7 | Holographic bg | 4.4 | [ ] |
| 7.1 | Toggle control | 4.4 | [ ] |
| 7.2 | Dropdown control | 4.4 | [ ] |
| 7.3 | Slider control | 4.4 | [ ] |
| 7.4 | Text/password control | 4.4 | [ ] |
| 7.5 | Button control | 4.4 | [ ] |
| 7.6 | Error display | 4.5 | [ ] |
| 7.7 | Hover effect | 4.4 | [ ] |
| 8.1 | Holographic colors | 2.1, 3.1 | [ ] |
| 8.2 | Scanlines | 2.1, 3.1 | [ ] |
| 8.3 | Noise texture | 2.1, 3.1 | [ ] |
| 8.4 | Chromatic aberration | 2.4 | [ ] |
| 8.5 | Edge glow | 2.1, 3.1 | [ ] |
| 8.6 | Confirm shine | 4.6 | [ ] |
| 8.7 | Backdrop blur | 2.1, 3.1 | [ ] |
| 8.8 | 3D perspective | 2.1, 3.1 | [ ] |
| 9.1 | ChatWing 255px | 2.1, 5.5 | [ ] |
| 9.2 | Dashboard 280px | 3.1, 5.5 | [ ] |
| 9.3 | Both 50vh | 2.1, 3.1 | [ ] |
| 9.4 | Left 3%, rotateY 15deg | 2.1, 5.5 | [ ] |
| 9.5 | Right 3%, rotateY -15deg | 3.1, 5.5 | [ ] |
| 9.6 | No new files | All | [ ] |
| 9.7 | Work in existing | All | [ ] |
| 10.1 | WebSocket notification | 1.2 | [ ] |
| 10.2 | Permission response | 1.6 | [ ] |
| 10.3 | sendMessage usage | 5.4 | [ ] |
| 10.4 | voiceState/audioLevel | 5.4 | [ ] |
| 10.5 | activeTheme colors | 5.4 | [ ] |
| 10.6 | fieldErrors display | 4.5 | [ ] |
| 10.7 | updateMiniNodeValue | 5.4 | [ ] |
| 10.8 | confirmMiniNode | 5.4 | [ ] |
| 11.1 | Focus indicators | 5.1 | [ ] |
| 11.2 | Title attributes | 5.3 | [ ] |
| 11.3 | Reduced motion | 5.2 | [ ] |
| 11.4 | 60fps animations | All | [ ] |
| 11.5 | Keyboard nav | 5.1 | [ ] |
| 11.6 | ARIA labels | 1.4 | [ ] |
| 12.1 | WS parse error handling | 5.6 | [ ] |
| 12.2 | Unknown type fallback | 1.1 | [ ] |
| 12.3 | Panel overflow | 1.4 | [ ] |
| 12.4 | Validation error handling | 4.5 | [ ] |
| 12.5 | Offline indicator | 4.5 | [ ] |
| 12.6 | TTS bounds checking | 2.3 | [ ] |

### 7.2 Code Review Checklist
- **What to build:** Review all changes for code quality, consistency
- **Files to create/modify:** All modified files
- **Requirements:** All
- **Implementation notes:** Check for:
  - [ ] Consistent formatting (Prettier)
  - [ ] No console.logs in production code
  - [ ] Proper TypeScript types on all functions
  - [ ] Accessibility attributes (aria-label, title)
  - [ ] Performance optimizations (memo, useCallback)
  - [ ] Error handling (try-catch on parsing)
  - [ ] Comment quality (English only)
  - [ ] No magic numbers (use constants)

### 7.3 Documentation Update
- **What to build:** Update any relevant documentation
- **Files to create/modify:** README or component docs if they exist
- **Requirements:** N/A
- **Implementation notes:** Document new notification system and flexible dashboard structure if user-facing docs exist.

---

## Summary

**Total Tasks:** 34 across 7 groups
**Estimated Implementation Time:** 12-16 hours
**Critical Path:** 
1. Task Group 1 (notifications + WebSocket)
2. Task Group 2 (ChatWing HUD)
3. Task Group 3 (DashboardWing HUD)
4. Task Group 4 (DarkGlassDashboard HUD)
5. Task Group 5 (Integration)

**Testing Requirements:** 6 test tasks covering unit, integration, and visual regression

**Dependencies:**
- Framer Motion (already in project)
- Lucide React (already in project)
- Tailwind CSS (already in project)
- useReducedMotion hook (already in project)
- NavigationContext (already in project)
- useIRISWebSocket hook (already in project)
- **No new dependencies required**

**Backend Integration Points:**
- WebSocket message type: `notification`
- WebSocket message type: `notification_response`
- WebSocket message type: `tts_word`
- WebSocket message type: `tts_end`
- Existing: `updateMiniNodeValue`, `confirmMiniNode`, `clearFieldError`

# IRISVOICE Implementation Plan

## Overview
This document splits all requested fixes between UI/UX and Backend agents to ensure no overlap and clean handoff points.

## Agent Assignments

---

## UI/UX AGENT SCOPE

### Priority 1: Remove Level 5 Navigation
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `contexts/NavigationContext.tsx`, `types/navigation.ts`, `components/hexagonal-control-center.tsx`, `components/iris/navigation-controller.tsx`

**Tasks:**
1. Remove `CONFIRM_MINI` action from navReducer
2. Remove `CONFIRM_MINI` from NavAction type
3. Update NavigationLevel type to exclude 5 (change to 1 | 2 | 3 | 4)
4. Remove Level 5 config from LEVEL_CONFIGS in navigation-controller.tsx
5. Update any Level 5 references in hexagonal-control-center.tsx
6. Confirmed nodes should now stay in orbit at Level 4 (not transition to 5)

**Success Criteria:** Navigation only has 4 levels, confirmed nodes remain visible at Level 4

---

### Priority 2: Increase Mini Stack Card Sizes
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `components/mini-node-stack.tsx`, `components/theme-switcher-card.tsx`

**Tasks:**
1. Increase mini-node card width from 140px to accommodate full field display
2. Increase heights for expanded accordion cards
3. Increase 2x2 grid dropdown to show more options (expand to 3x2 or make scrollable)
4. Update font sizes proportionally
5. Ensure theme switcher card matches new sizing

**Current Values:**
- Card width: 140px
- Grid: 2x2 (4 options max)
- Font sizes: 7px-10px

**Target:** Full option visibility without "+X more" truncation

---

### Priority 3: Add ARIA Labels via Iris Orb
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `components/hexagonal-control-center.tsx`, `components/iris/prism-node.tsx`, `components/iris/hexagonal-node.tsx`

**Tasks:**
1. Make Iris Orb display the active menu label as aria-label for screen readers
2. When label changes (IRIS → VOICE → INPUT → etc), update aria-label
3. Add aria-live="polite" region for navigation announcements
4. Add aria-pressed to active nodes
5. Add role="navigation" to node containers

**Implementation:**
```tsx
// IrisOrb component should receive activeLabel prop
<motion.div
  ref={orbRef}
  aria-label={`Active: ${centerLabel}`}
  aria-live="polite"
  role="button"
  ...
/>
```

---

### Priority 4: Fix Color Contrast Issues
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `app/globals.css`, `contexts/BrandColorContext.tsx`, `components/iris/prism-node.tsx`

**Tasks:**
1. Increase text opacity from 0.70 to 0.85 minimum for secondary text
2. Ensure glass backgrounds provide sufficient contrast
3. Add automatic contrast calculation to BrandColorContext
4. Verify all 4 themes meet WCAG AA (4.5:1 for normal text, 3:1 for large)

**Key Areas:**
- `--text-secondary` in all theme definitions
- Mini-node card text
- Toggle/dropdown labels
- Icon contrast against backgrounds

---

### Priority 5: Fix Motion Accessibility
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `hooks/useAnimationConfig.ts`, `components/iris/prism-node.tsx`, `components/hexagonal-control-center.tsx`, `hooks/useTransitionVariants.ts`

**Tasks:**
1. Ensure `prefers-reduced-motion` is checked before ALL animations
2. Disable floating orbs when reduced motion is preferred
3. Replace spin animations with instant transitions for reduced motion
4. Add instant mode to all transition styles
5. Test with system reduced motion enabled

**Implementation Pattern:**
```tsx
const shouldAnimate = !prefersReducedMotion;
// Only animate if shouldAnimate is true
```

---

### Priority 6: Fix Excessive Re-renders
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `contexts/NavigationContext.tsx`, `contexts/BrandColorContext.tsx`, `components/hexagonal-control-center.tsx`

**Tasks:**
1. Add React.memo to HexagonalNode and PrismNode components
2. Use useMemo for expensive calculations in NavigationContext
3. Debounce CSS variable updates in BrandColorContext (100ms)
4. Add useCallback for all event handlers
5. Audit useEffect dependencies for unnecessary triggers

**Key Improvements:**
- Memoize node arrays in navigation-controller.tsx
- Throttle brand color updates
- Remove console.log from render paths

---

### Priority 7: Clear Console Pollution
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** All components with console.log

**Files to Clean:**
- `components/hexagonal-control-center.tsx` (15+ logs)
- `contexts/NavigationContext.tsx` (reducer logs)
- `contexts/BrandColorContext.tsx` (mount logs)
- `components/iris/hexagonal-node.tsx` (transition logs)
- `components/iris/prism-node.tsx` (theme logs)

**Tasks:**
1. Remove all console.log statements
2. Replace with proper logging utility if needed for dev only
3. Wrap remaining logs in `if (process.env.NODE_ENV === 'development')`

---

### Priority 8: Remove Component Duplication
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `components/iris/prism-node.tsx`, `components/iris/hexagonal-node.tsx`

**Tasks:**
1. Delete `components/iris/hexagonal-node.tsx`
2. Keep `prism-node.tsx` as the single implementation
3. Update all imports from HexagonalNode to PrismNode
4. Remove compatibility alias at bottom of prism-node.tsx

---

### Priority 9: Fix Mobile Experience
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `components/hexagonal-control-center.tsx`, `components/mini-node-stack.tsx`

**Tasks:**
1. Increase touch target sizes (minimum 44x44px)
2. Add touch gesture support (swipe to navigate back)
3. Improve responsive breakpoints
4. Make mini-node stack wider on mobile
5. Add haptic feedback on selection (if available)

**Implementation:**
- Add touch event handlers for swipe detection
- Use proper viewport units
- Test on actual mobile devices

---

### Priority 10: Fix Menu Window Integration
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `components/menu-window-slider.tsx`, `components/dark-glass-dashboard.tsx`, `app/menu-window/page.tsx`, `components/mini-node-stack.tsx`

**Current Issue:** Opens in new tab, disconnected experience

**Tasks:**
1. Replace `window.open()` with slide-out panel from main widget
2. Animate dashboard in from right edge
3. Share state between widget and dashboard
4. Add close button to return to widget view
5. Keep MenuWindowSlider trigger in mini-node stack

**Target Behavior:** Dashboard slides in over/within the same window

---

### Priority 11: Fix Field Control Patterns
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `components/mini-node-stack.tsx`, `components/fields/`

**Current Issues:**
- Custom slider in mini-node-stack differs from SliderField
- Text fields are placeholders only (no input)

**Tasks:**
1. Use consistent SliderField component in mini-node stack
2. Replace text placeholders with actual TextField inputs
3. Ensure all field types work in mini-node context
4. Add proper onChange handlers

---

### Priority 12: Fix Dropdown Limitations
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `components/mini-node-stack.tsx`

**Current:** 2x2 grid = 4 options max

**Tasks:**
1. Expand to 3x2 grid (6 options) or make scrollable list
2. Add search/filter for long lists (device selection)
3. Show all options without truncation
4. Consider virtual scrolling for very long lists

---

### Priority 13: Fix Tauri Widget Drag
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `components/hexagonal-control-center.tsx`, `src-tauri/Cargo.toml`, `src-tauri/tauri.conf.json`

**Current Issue:** Drag not working in Tauri build

**Tasks:**
1. Verify Tauri window config has decorations: false, transparent: true
2. Check `useManualDragWindow` hook is properly detecting Tauri
3. Ensure `getCurrentWindow()` and `PhysicalPosition` are available
4. Add drag handle to entire widget (not just iris orb)
5. Test with `data-tauri-drag-region` attribute
6. Verify Windows Snap Assist bypass is working

**Debug Steps:**
- Check if `window.__TAURI__` exists
- Verify Tauri API imports
- Test setPosition calls

---

### Priority 14: Fix Wake Word Response
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `components/mini-node-stack.tsx`, `hooks/useIRISWebSocket.ts`

**Current Issue:** Wake word not triggering agent response

**Tasks:**
1. Verify wake word detection state is properly synced
2. Add visual feedback when wake word is detected (pulse iris orb)
3. Ensure WebSocket sends wake detection events
4. Add listening state indicator to UI
5. Test with different wake phrases

**Integration Point:** Backend agent handles actual wake word detection

---

### Priority 15: Consolidate Theme Systems
**Status:** NOT STARTED  
**Owner:** UI/UX Agent  
**Files:** `hooks/useIRISWebSocket.ts`, `contexts/BrandColorContext.tsx`

**Current:** Two theme systems exist

**Tasks:**
1. Remove legacy theme from useIRISWebSocket
2. Make BrandColorContext the single source of truth
3. Ensure WebSocket still receives theme updates
4. Update all components to use BrandColorContext only

---

## BACKEND AGENT SCOPE

### Priority 1: Backend Startup Coordination
**Status:** NOT STARTED  
**Owner:** Backend Agent  
**Files:** `src-tauri/src/main.rs`, `src-tauri/tauri.conf.json`, `package.json`, `start-backend.py`

**Current Issue:** Backend doesn't start automatically with Tauri

**Tasks:**
1. Add backend startup to Tauri sidecar configuration
2. Create sidecar binary packaging for Python backend
3. Configure Tauri to wait for backend before showing window
4. Add health check loop to verify backend is ready
5. Handle backend restart if it crashes

**Implementation Options:**
- Option A: Bundle Python with Tauri (sidecar)
- Option B: Use Tauri command API to spawn backend process
- Option C: Convert backend to Rust (long-term)

**Tauri Config Updates:**
```json
{
  "bundle": {
    "externalBin": ["backend"]
  }
}
```

---

### Priority 2: Fix Wake Word Detection
**Status:** NOT STARTED  
**Owner:** Backend Agent  
**Files:** `backend/`, WebSocket handlers

**Current Issue:** Wake word detection not responding

**Tasks:**
1. Verify VAD (Voice Activity Detection) is enabled
2. Check wake word model is loaded correctly
3. Ensure audio input stream is active
4. Add WebSocket events for:
   - `wake_detected` - when wake phrase heard
   - `listening_started` - when agent starts listening
   - `listening_ended` - when agent stops listening
5. Test with configured wake phrases
6. Add debug logging for wake word pipeline

**WebSocket Messages to Frontend:**
```json
{ "type": "wake_detected", "payload": { "phrase": "Hey Computer" } }
{ "type": "listening_state", "payload": { "state": "active|inactive" } }
```

---

### Priority 3: Support Level 4 Confirmed Nodes
**Status:** NOT STARTED  
**Owner:** Backend Agent  
**Files:** `backend/models.py`, `backend/ws_manager.py`, `backend/state_manager.py`

**Context:** UI is removing Level 5, confirmed nodes stay at Level 4

**Tasks:**
1. Update IRISState model to support Level 4 confirmed nodes
2. Ensure confirmed nodes are persisted in state
3. Modify WebSocket handlers for confirm action
4. Keep orbit position calculations in backend

**Model Updates:**
```python
# confirmed_nodes stay in Level 4 context
confirmed_nodes: List[ConfirmedNode]  # No level change on confirm
```

---

### Priority 4: Theme System Consolidation Backend
**Status:** NOT STARTED  
**Owner:** Backend Agent  
**Files:** `backend/models.py`, `backend/main.py`

**Tasks:**
1. Remove legacy ColorTheme model
2. Accept theme updates from frontend only
3. Persist theme preferences
4. Sync theme state on WebSocket connect

---

## SHARED INTERFACE CONTRACTS

### WebSocket Message Types

**Frontend → Backend:**
```typescript
// Existing
{ type: "select_category", payload: { category: string } }
{ type: "select_subnode", payload: { subnode_id: string } }
{ type: "field_update", payload: { subnode_id, field_id, value } }
{ type: "confirm_mini_node", payload: { subnode_id, values } }
{ type: "update_theme", payload: { glow_color, font_color, state_colors } }

// New for wake word
{ type: "wake_word_config", payload: { phrase, sensitivity } }
{ type: "request_listening_state" }
```

**Backend → Frontend:**
```typescript
// Existing
{ type: "initial_state", payload: { state: IRISState } }
{ type: "category_changed", payload: { category } }
{ type: "subnode_changed", payload: { subnode_id } }
{ type: "field_updated", payload: { subnode_id, field_id, value } }
{ type: "theme_updated", payload: { glow, font } }

// New
{ type: "wake_detected", payload: { phrase, confidence } }
{ type: "listening_state", payload: { state: "active|inactive|processing" } }
{ type: "backend_ready" }  // Signals backend is started
```

### State Interface
```typescript
interface IRISState {
  current_category: string | null;
  current_subnode: string | null;
  field_values: Record<string, any>;
  active_theme: ThemeConfig;  // Single theme system
  confirmed_nodes: ConfirmedNode[];  // Now at Level 4
  // Removed: Level 5 references
}
```

### Theme Interface
```typescript
interface ThemeConfig {
  name: 'aether' | 'ember' | 'aurum' | 'verdant';
  hue: number;
  saturation: number;
  lightness: number;
  // Full Prism Glass spec
}
```

---

## HANDOFF POINTS

### UI → Backend
1. **Theme Updates:** Frontend sends `update_theme` → Backend persists
2. **Field Changes:** Frontend sends `field_update` → Backend validates and persists
3. **Wake Config:** Frontend sends `wake_word_config` → Backend updates detection

### Backend → UI
1. **State Sync:** Backend sends `initial_state` on connect
2. **Wake Events:** Backend sends `wake_detected` → Frontend shows pulse animation
3. **Backend Ready:** Backend sends `backend_ready` → Frontend shows UI

---

## SEQUENCING

### Phase 1: Foundation (Week 1)
**UI/UX:**
- Remove Level 5
- Clear console pollution
- Remove component duplication
- Fix mobile touch targets

**Backend:**
- Backend startup coordination
- Wake word detection fix

### Phase 2: UX Polish (Week 2)
**UI/UX:**
- Increase mini stack sizes
- Fix dropdown limitations
- Fix field control patterns
- Fix menu window integration

**Backend:**
- Support Level 4 confirmed nodes
- Theme consolidation backend

### Phase 3: Accessibility (Week 3)
**UI/UX:**
- ARIA labels via iris orb
- Color contrast fixes
- Motion accessibility
- Excessive re-render fixes

### Phase 4: Integration (Week 4)
**Both:**
- End-to-end testing
- Tauri build verification
- Wake word E2E test
- Performance validation

---

## SUCCESS CRITERIA

- [ ] Navigation has only 4 levels (no Level 5)
- [ ] Mini-node cards show all options without truncation
- [ ] Iris orb displays active menu label for screen readers
- [ ] All text meets WCAG AA contrast (4.5:1)
- [ ] Reduced motion disables all animations
- [ ] No console.log in production
- [ ] Single PrismNode component (no duplication)
- [ ] Widget is draggable in Tauri build
- [ ] Wake word triggers agent response
- [ ] Backend starts automatically with Tauri
- [ ] Menu window slides in (not new tab)
- [ ] Mobile touch targets are 44x44px minimum
- [ ] All field controls work in mini-node stack
- [ ] Single theme system (BrandColorContext)

---

## Shared Tracking

See `IRISVOICE-FIXES-TRACKER.md` for real-time status updates from both agents.

---

*Last Updated: February 6, 2026*
*Plan Version: 1.0*

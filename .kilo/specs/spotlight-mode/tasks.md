# Implementation Plan: Spotlight Mode (Integrated)

## Task 1: Extend useUILayoutState Hook

### 1.1 Add SpotlightState Enum

### 1.5 Create IrisApertureIcon Component
**What to build:** Custom animated aperture icon component for maximize button
**Files to create:** `IRISVOICE/components/ui/IrisApertureIcon.tsx`
**Requirements:** 7.3-7.11

**Component implementation:**
```tsx
"use client";

import { motion } from "framer-motion";

interface IrisApertureIconProps {
  isActive: boolean;
  glowColor: string;
  fontColor: string;
  size?: number;
}

export function IrisApertureIcon({
  isActive,
  glowColor,
  fontColor,
  size = 14
}: IrisApertureIconProps) {
  // Point animation variants
  const pointVariants = {
    rest: { x: 0, y: 0 },
    active: (direction: string) => {
      switch (direction) {
        case 'top': return { x: 0, y: -4 };
        case 'right': return { x: 4, y: 0 };
        case 'bottom': return { x: 0, y: 4 };
        case 'left': return { x: -4, y: 0 };
        default: return { x: 0, y: 0 };
      }
    }
  };

  const transition = {
    type: "spring",
    stiffness: 280,
    damping: 25,
    mass: 0.8
  };

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="none"
      style={{ overflow: 'visible' }}
    >
      {/* Top point */}
      <motion.polygon
        points="7,2 8,7 6,7"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="top"
        transition={transition}
      />
      {/* Right point */}
      <motion.polygon
        points="12,7 7,8 7,6"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="right"
        transition={transition}
      />
      {/* Bottom point */}
      <motion.polygon
        points="7,12 6,7 8,7"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="bottom"
        transition={transition}
      />
      {/* Left point */}
      <motion.polygon
        points="2,7 7,6 7,8"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="left"
        transition={transition}
      />
    </svg>
  );
}
```

**Acceptance criteria:**
- [ ] Component created in `IRISVOICE/components/ui/IrisApertureIcon.tsx`
- [ ] Four triangular points render in diamond formation (✦) when rest
- [ ] Points expand outward (✧) when isActive=true
- [ ] Points move 4px along diagonals
- [ ] 400ms spring animation (stiffness 280, damping 25)
- [ ] 1px stroke in rest state with fontColor
- [ ] Fill with glowColor in active state
- [ ] 14x14px default size
- [ ] Smooth morphing between states
- [ ] Matches crystalline aesthetic

### 1.2 Add Spotlight State and Methods

### 1.3 Add Spotlight Reset Logic

### 1.4 Update Return Interface
**What to build:** Add SpotlightState enum to useUILayoutState.ts
**Files to modify:** `IRISVOICE/hooks/useUILayoutState.ts`
**Requirements:** 1.1, 1.2, 1.3, 1.4, 1.5

**Add after UILayoutState enum:**
```typescript
export enum SpotlightState {
  BALANCED = 'balanced',
  CHAT_SPOTLIGHT = 'chatSpotlight',
  DASHBOARD_SPOTLIGHT = 'dashboardSpotlight'
}
```

**Acceptance criteria:**
- [ ] SpotlightState enum exported from hook
- [ ] Three values: BALANCED, CHAT_SPOTLIGHT, DASHBOARD_SPOTLIGHT
- [ ] TypeScript compiles without errors

### 1.2 Add Spotlight State and Methods
**What to build:** Add spotlight state management to useUILayoutState hook
**Files to modify:** `IRISVOICE/hooks/useUILayoutState.ts`
**Requirements:** 1.1, 2.1-2.7

**Add to hook:**
```typescript
// Spotlight state (only meaningful in UI_STATE_BOTH_OPEN)
const [spotlightState, setSpotlightState] = useState<SpotlightState>(SpotlightState.BALANCED);

// Spotlight transition methods
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

// Boolean helpers
const isBalanced = spotlightState === SpotlightState.BALANCED;
const isChatSpotlight = spotlightState === SpotlightState.CHAT_SPOTLIGHT;
const isDashboardSpotlight = spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT;
```

**Acceptance criteria:**
- [ ] spotlightState initialized to BALANCED
- [ ] toggleChatSpotlight() toggles between CHAT_SPOTLIGHT and BALANCED
- [ ] toggleDashboardSpotlight() toggles between DASHBOARD_SPOTLIGHT and BALANCED
- [ ] restoreBalanced() sets state to BALANCED
- [ ] Boolean helpers correctly reflect state
- [ ] Spotlight methods only work in UI_STATE_BOTH_OPEN

### 1.3 Add Spotlight Reset Logic
**What to build:** Reset spotlight state when leaving BOTH_OPEN
**Files to modify:** `IRISVOICE/hooks/useUILayoutState.ts`
**Requirements:** 1.4, 1.5

**Add useEffect:**
```typescript
// Reset spotlight to balanced when leaving BOTH_OPEN state
useEffect(() => {
  if (uiState !== UILayoutState.UI_STATE_BOTH_OPEN) {
    setSpotlightState(SpotlightState.BALANCED);
  }
}, [uiState]);
```

**Acceptance criteria:**
- [ ] spotlightState resets to BALANCED when transitioning away from BOTH_OPEN
- [ ] spotlightState initializes to BALANCED when entering BOTH_OPEN

### 1.4 Update Return Interface
**What to build:** Add spotlight properties to hook return value
**Files to modify:** `IRISVOICE/hooks/useUILayoutState.ts`
**Requirements:** 1.1, 2.1-2.7

**Update return object:**
```typescript
return {
  // Existing properties
  state: uiState,
  isTransitioning,
  transitionDirection,
  navigationLevel: navState.level,
  
  // Existing methods
  openChat,
  openDashboard,
  closeAll,
  canTransition,
  
  // Spotlight properties (NEW)
  spotlightState,
  isBalanced,
  isChatSpotlight,
  isDashboardSpotlight,
  
  // Spotlight methods (NEW)
  setSpotlightState,
  toggleChatSpotlight,
  toggleDashboardSpotlight,
  restoreBalanced
}
```

**Acceptance criteria:**
- [ ] All spotlight properties and methods returned
- [ ] No breaking changes to existing return values
- [ ] TypeScript interface updated

---

## Task 2: ChatWing Spotlight Integration

### 2.1 Add Spotlight Props to ChatWing
**What to build:** Extend ChatWing to accept spotlight state and callbacks
**Files to modify:** `IRISVOICE/components/chat-view.tsx`
**Requirements:** 3.1-3.7, 7.1-7.8

**Add to imports:**
```typescript
import { Maximize2, Minimize2 } from 'lucide-react';
import { SpotlightState } from "@/hooks/useUILayoutState";
```

**Add to interface:**
```typescript
interface ChatWingProps {
  // ... existing props ...
  spotlightState?: SpotlightState;
  onToggleSpotlight?: () => void;
}
```

**Acceptance criteria:**
- [ ] ChatWing accepts spotlightState prop (defaults to BALANCED)
- [ ] ChatWing accepts onToggleSpotlight callback
- [ ] Imports added correctly

### 1.5 Create IrisApertureIcon Component
**What to build:** Custom animated aperture icon component for maximize button
**Files to create:** `IRISVOICE/components/ui/IrisApertureIcon.tsx`
**Requirements:** 7.3-7.11

**Component implementation:**
```tsx
"use client";

import { motion } from "framer-motion";

interface IrisApertureIconProps {
  isActive: boolean;
  glowColor: string;
  fontColor: string;
  size?: number;
}

export function IrisApertureIcon({
  isActive,
  glowColor,
  fontColor,
  size = 14
}: IrisApertureIconProps) {
  // Point animation variants
  const pointVariants = {
    rest: { x: 0, y: 0 },
    active: (direction: string) => {
      switch (direction) {
        case 'top': return { x: 0, y: -4 };
        case 'right': return { x: 4, y: 0 };
        case 'bottom': return { x: 0, y: 4 };
        case 'left': return { x: -4, y: 0 };
        default: return { x: 0, y: 0 };
      }
    }
  };

  const transition = {
    type: "spring",
    stiffness: 280,
    damping: 25,
    mass: 0.8
  };

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      fill="none"
      style={{ overflow: 'visible' }}
    >
      {/* Top point */}
      <motion.polygon
        points="7,2 8,7 6,7"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="top"
        transition={transition}
      />
      {/* Right point */}
      <motion.polygon
        points="12,7 7,8 7,6"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="right"
        transition={transition}
      />
      {/* Bottom point */}
      <motion.polygon
        points="7,12 6,7 8,7"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="bottom"
        transition={transition}
      />
      {/* Left point */}
      <motion.polygon
        points="2,7 7,6 7,8"
        fill={isActive ? glowColor : 'none'}
        stroke={isActive ? 'none' : fontColor}
        strokeWidth={1}
        variants={pointVariants}
        initial="rest"
        animate={isActive ? "active" : "rest"}
        custom="left"
        transition={transition}
      />
    </svg>
  );
}
```

**Acceptance criteria:**
- [ ] Component created in `IRISVOICE/components/ui/IrisApertureIcon.tsx`
- [ ] Four triangular points render in diamond formation (✦) when rest
- [ ] Points expand outward (✧) when isActive=true
- [ ] Points move 4px along diagonals
- [ ] 400ms spring animation (stiffness 280, damping 25)
- [ ] 1px stroke in rest state with fontColor
- [ ] Fill with glowColor in active state
- [ ] 14x14px default size
- [ ] Smooth morphing between states
- [ ] Matches crystalline aesthetic

### 2.2 Add Iris Aperture Button to ChatWing Header
**What to build:** Add Iris Aperture button between title and other icons
**Files to modify:** `IRISVOICE/components/chat-view.tsx` (header section)
**Requirements:** 7.1, 7.2, 7.12-7.14

**Insert between title and other icons:**
```tsx
{/* Iris Aperture Spotlight Button */}
{onToggleSpotlight && (
  <button
    onClick={onToggleSpotlight}
    className="p-2 rounded-lg transition-all duration-150 flex items-center justify-center"
    style={{ 
      backgroundColor: spotlightState === SpotlightState.CHAT_SPOTLIGHT 
        ? `${glowColor}15` 
        : 'transparent'
    }}
    onMouseEnter={(e) => {
      e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.backgroundColor = 
        spotlightState === SpotlightState.CHAT_SPOTLIGHT 
          ? `${glowColor}15` 
          : 'transparent';
    }}
    title={spotlightState === SpotlightState.CHAT_SPOTLIGHT ? "Restore" : "Maximize"}
  >
    <IrisApertureIcon
      isActive={spotlightState === SpotlightState.CHAT_SPOTLIGHT}
      glowColor={glowColor}
      fontColor={`${fontColor}60`}
      size={14}
    />
  </button>
)}
```

**Acceptance criteria:**
- [ ] Button renders between title and other icons
- [ ] IrisApertureIcon component used
- [ ] isActive prop correctly set based on spotlightState
- [ ] Clicking calls onToggleSpotlight
- [ ] Hover effects applied
- [ ] Tooltip shows "Maximize" or "Restore"

### 2.3 Apply Dynamic Styles to ChatWing Container
**What to build:** Animate ChatWing based on spotlight state
**Files to modify:** `IRISVOICE/components/chat-view.tsx` (main motion.div around line 123)
**Requirements:** 3.1-3.7, 6.1-6.7

**Determine computed styles:**
```typescript
const isBackground = spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT;
const isSpotlight = spotlightState === SpotlightState.CHAT_SPOTLIGHT;

// Style values based on spotlight state
const wingWidth = isSpotlight ? '340px' : isBackground ? '180px' : '255px';
const wingLeft = isSpotlight ? '5%' : '3%';
const wingRotateY = isSpotlight ? '0deg' : '15deg';
const wingOpacity = isBackground ? 0.3 : 1;
const wingFilter = isBackground ? 'saturate(0.6) blur(2px)' : 'none';
const wingZIndex = isSpotlight ? 20 : isBackground ? 5 : 10;
const pointerEvents = isBackground ? 'none' : 'auto';
```

**Apply to motion.div:**
```tsx
<motion.div
  // ... existing props ...
  animate={{
    width: wingWidth,
    left: wingLeft,
    opacity: wingOpacity,
  }}
  transition={{
    type: "spring",
    stiffness: 280,
    damping: 25,
    mass: 0.8
  }}
  style={{
    // ... existing styles ...
    transform: `translateY(-50%) rotateY(${wingRotateY}) rotateX(2deg)`,
    filter: wingFilter,
    pointerEvents,
    zIndex: wingZIndex,
  }}
>
```

**Acceptance criteria:**
- [ ] Width animates: 255px → 340px (spotlight) or 180px (background)
- [ ] Left animates: 3% → 5% (spotlight)
- [ ] RotateY: 15deg → 0deg (spotlight)
- [ ] Opacity: 1 → 0.3 (background)
- [ ] Filter applies blur/saturation when background
- [ ] Pointer events disabled when background
- [ ] Z-index correct (20 spotlight, 10 balanced, 5 background)
- [ ] Spring animation matches dashboard-wing.tsx

### 2.4 Adapt ChatWing Content for Spotlight
**What to build:** Adjust content layout when in spotlight
**Files to modify:** `IRISVOICE/components/chat-view.tsx`
**Requirements:** 9.1, 9.2, 9.5

**Apply to message bubbles:**
```tsx
className={`max-w-[${isSpotlight ? '90%' : '85%'}] px-3 py-2.5`}
```

**Apply to container:**
```tsx
className={`px-${isSpotlight ? '5' : '4'} flex-1 overflow-y-auto`}
```

**Acceptance criteria:**
- [ ] Message bubbles expand to 90% in CHAT_SPOTLIGHT
- [ ] Horizontal padding increases in CHAT_SPOTLIGHT
- [ ] Content scale 1.02 applied subtly

---

## Task 3: DashboardWing Spotlight Integration

### 3.1 Add Spotlight Props to DashboardWing
**What to build:** Extend DashboardWing to accept spotlight state
**Files to modify:** `IRISVOICE/components/dashboard-wing.tsx`
**Requirements:** 4.1-4.7, 7.1-7.8

**Add to imports:**
```typescript
import { Maximize2, Minimize2 } from 'lucide-react';
import { SpotlightState } from "@/hooks/useUILayoutState";
```

**Add to interface and props:** (Mirror of Task 2.1)

**Acceptance criteria:**
- [ ] DashboardWing accepts spotlightState and onToggleSpotlight props

### 3.2 Add Iris Aperture Button to DashboardWing Header
**What to build:** Add Iris Aperture button to DashboardWing header
**Files to modify:** `IRISVOICE/components/dashboard-wing.tsx`
**Requirements:** 7.1, 7.2, 7.12-7.14

**Insert between title and other icons:** (Mirror of Task 2.2 with adjusted isActive check)
```tsx
{/* Iris Aperture Spotlight Button */}
{onToggleSpotlight && (
  <button
    onClick={onToggleSpotlight}
    className="p-2 rounded-lg transition-all duration-150 flex items-center justify-center"
    style={{ 
      backgroundColor: spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT 
        ? `${glowColor}15` 
        : 'transparent'
    }}
    onMouseEnter={(e) => {
      e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)';
    }}
    onMouseLeave={(e) => {
      e.currentTarget.style.backgroundColor = 
        spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT 
          ? `${glowColor}15` 
          : 'transparent';
    }}
    title={spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT ? "Restore" : "Maximize"}
  >
    <IrisApertureIcon
      isActive={spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT}
      glowColor={glowColor}
      fontColor={`${fontColor}60`}
      size={14}
    />
  </button>
)}
```

**Acceptance criteria:**
- [ ] Button renders between title and other icons
- [ ] IrisApertureIcon component used
- [ ] isActive prop correctly set based on spotlightState
- [ ] Clicking calls onToggleSpotlight
- [ ] Hover effects applied
- [ ] Tooltip shows "Maximize" or "Restore"

### 3.3 Apply Dynamic Styles to DashboardWing Container
**What to build:** Animate DashboardWing based on spotlight state
**Files to modify:** `IRISVOICE/components/dashboard-wing.tsx`
**Requirements:** 4.1-4.7, 6.1-6.7

**Determine computed styles:**
```typescript
const isBackground = spotlightState === SpotlightState.CHAT_SPOTLIGHT;
const isSpotlight = spotlightState === SpotlightState.DASHBOARD_SPOTLIGHT;

const wingWidth = isSpotlight ? '360px' : isBackground ? '180px' : '280px';
const wingRight = isSpotlight ? '5%' : '3%';
const wingRotateY = isSpotlight ? '0deg' : '-15deg';
const wingOpacity = isBackground ? 0.3 : 1;
const wingFilter = isBackground ? 'saturate(0.6) blur(2px)' : 'none';
const wingZIndex = isSpotlight ? 20 : isBackground ? 5 : 10;
const pointerEvents = isBackground ? 'none' : 'auto';
```

**Apply to motion.div:** (Similar to ChatWing, with right positioning)

**Acceptance criteria:**
- [ ] Width animates: 280px → 360px (spotlight) or 180px (background)
- [ ] Right position animates: 3% → 5% (spotlight)
- [ ] RotateY: -15deg → 0deg (spotlight)
- [ ] All other animations correct

### 3.4 Adapt DashboardWing Content for Spotlight
**What to build:** Adjust content layout when in spotlight
**Files to modify:** `IRISVOICE/components/dashboard-wing.tsx`, `IRISVOICE/components/dark-glass-dashboard.tsx`
**Requirements:** 9.3, 9.4, 9.5

**Pass isSpotlight prop to DarkGlassDashboard:**
```typescript
<DarkGlassDashboard isSpotlight={isSpotlight} />
```

**Acceptance criteria:**
- [ ] Control inputs expand to 180px max in DASHBOARD_SPOTLIGHT
- [ ] Section headers full-bleed with gradient
- [ ] Content scale 1.02 applied

---

## Task 4: Page-Level Integration

### 4.1 Initialize Spotlight State in Page
**What to build:** Consume extended useUILayoutState hook
**Files to modify:** `IRISVOICE/app/page.tsx`
**Requirements:** All integration requirements

**Extract from useUILayoutState:**
```typescript
const {
  state: uiLayoutState,
  openChat,
  openDashboard,
  closeAll,
  isChatOpen,
  isBothOpen,
  // Spotlight (NEW)
  spotlightState,
  toggleChatSpotlight,
  toggleDashboardSpotlight,
  restoreBalanced
} = useUILayoutState();
```

**Acceptance criteria:**
- [ ] spotlightState extracted from hook
- [ ] toggle functions extracted
- [ ] No TypeScript errors

### 4.2 Wire Spotlight Props to Wings
**What to build:** Pass spotlight state and callbacks to both wings
**Files to modify:** `IRISVOICE/app/page.tsx`
**Requirements:** All integration requirements

**Update ChatWing:**
```tsx
<LazyChatWing
  isOpen={isChatOpen || isBothOpen}
  onClose={closeAll}
  onDashboardClick={openDashboard}
  sendMessage={sendMessage}
  spotlightState={spotlightState}
  onToggleSpotlight={toggleChatSpotlight}
/>
```

**Update DashboardWing:**
```tsx
<DashboardWing
  isOpen={isBothOpen}
  onClose={closeAll}
  sendMessage={sendMessage}
  spotlightState={spotlightState}
  onToggleSpotlight={toggleDashboardSpotlight}
/>
```

**Acceptance criteria:**
- [ ] ChatWing receives spotlightState and onToggleSpotlight
- [ ] DashboardWing receives spotlightState and onToggleSpotlight
- [ ] Props correctly wired

### 4.3 Update Escape Key Handling
**What to build:** Handle Escape key for spotlight restoration
**Files to modify:** `IRISVOICE/hooks/useKeyboardNavigation.ts` or inline in page.tsx
**Requirements:** 8.1-8.5

**Priority order for Escape key:**
1. Close notification dropdowns if open
2. Restore balanced spotlight state if in spotlight mode
3. Close wings (existing behavior)

**Acceptance criteria:**
- [ ] Escape in CHAT_SPOTLIGHT restores to BALANCED
- [ ] Escape in DASHBOARD_SPOTLIGHT restores to BALANCED
- [ ] Escape in BALANCED closes wings (existing)
- [ ] Escape closes dropdowns first

---

## Task 5: Testing & Verification

### 5.1 TypeScript Compilation
**Command:**
```bash
cd IRISVOICE && npm run build
```
**Acceptance criteria:**
- [ ] Build completes with 0 errors
- [ ] No TypeScript warnings

### 5.2 Visual Verification
**Test scenarios:**
- [ ] Balanced state matches existing behavior exactly
- [ ] ChatSpotlight expands ChatWing correctly
- [ ] DashboardSpotlight expands DashboardWing correctly
- [ ] Transitions are smooth (spring animation)
- [ ] Z-index layering correct
- [ ] Pointer events blocked on background wing

### 5.3 Functional Testing
**Test scenarios:**
- [ ] ChatActivationText → ChatOpen → Dashboard icon → BothOpen (balanced)
- [ ] Click ChatWing maximize → CHAT_SPOTLIGHT
- [ ] Click ChatWing restore → BALANCED
- [ ] Click DashboardWing maximize → DASHBOARD_SPOTLIGHT
- [ ] Click DashboardWing restore → BALANCED
- [ ] Direct toggle: CHAT_SPOTLIGHT → DASHBOARD_SPOTLIGHT
- [ ] Escape key restores BALANCED
- [ ] Closing wings resets to BALANCED for next open

### 5.4 Edge Cases
**Test scenarios:**
- [ ] Rapid maximize button clicks
- [ ] Theme change during spotlight
- [ ] Notification dropdown during spotlight
- [ ] Window resize during spotlight

---

## Success Criteria

- [ ] All 5 tasks complete
- [ ] All 12 requirements satisfied
- [ ] Build passes
- [ ] Existing behavior preserved
- [ ] Spotlight mode fully functional

**Estimated effort:** 1.5-2 development days
**Risk level:** Low-Medium (extends existing system)

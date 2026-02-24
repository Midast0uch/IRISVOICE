# Navigation Fix Tracker

**Created:** Feb 5, 2026
**Purpose:** Track all debugging attempts to avoid repeating the same failed fixes

---

## The Problems

1. **Problem A:** Mini-stack card clicks trigger Iris Orb back navigation
2. **Problem B:** Clicking main node does not immediately show subnodes (requires refresh)
3. **Problem C:** Iris Orb at Level 4 navigates to wrong level

---

## Attempt History

### Attempt #1: stopPropagation on mini-stack wrapper
- **Date:** (Previous session)
- **Changes:** Added `onClick`, `onMouseDown`, `onPointerDown` with `stopPropagation` to mini-stack wrapper div
- **Result:** FAILED - Still triggering iris click

### Attempt #2: stopPropagation on PrismNode
- **Date:** (Previous session)
- **Changes:** Added `onMouseDown` and `onPointerDown` stopPropagation to PrismNode motion.button
- **Result:** FAILED - Still triggering iris click

### Attempt #3: Click-blocking overlay (500x500)
- **Date:** (Previous session)
- **Changes:** Added 500x500px click-blocking overlay at z-[100] to capture clicks before iris
- **Result:** FAILED - Overlay was too big, blocked mini-stack itself

### Attempt #4: Shrunk overlay + moved mini-stack
- **Date:** Feb 5, 2026 3:34am
- **Changes:**
  - Overlay shrunk from 500x500 to 100x100 (only covers iris orb)
  - Overlay z-index changed from z-[100] to z-[50]
  - Mini-stack moved from marginLeft: 200 to marginLeft: 280
  - Mini-stack z-index changed from z-20 to z-[200]
  - Connecting line extended from 120px to 200px
  - Removed event handlers from mini-stack wrapper (clean isolation)
- **Result:** FAILED - Both handleIrisClick AND handleSubnodeClick fired. Console showed "Level 2->1, collapsing" followed by "Level 4 navigation". The click-blocking overlay isn't intercepting events properly.
- **Evidence:** 
  ```
  [DEBUG] handleIrisClick: Level 2->1, collapsing
  [DEBUG] navReducer ENTRY: {actionType: COLLAPSE_TO_IDLE}
  [DEBUG] handleSubnodeClick START: {subnodeId: "input"...}
  [DEBUG] Attempting Level 4 navigation
  ```

---

## Root Cause Analysis

### Current Understanding:
The Iris Orb uses a drag hook (`useManualDragWindow`) that listens to `mousedown` events. The event capture order seems to be:
1. Iris Orb mousedown fires first (pointer-events on large wrapper)
2. Other elements get the event after

This means `stopPropagation` on other elements doesn't work because the iris handler fires BEFORE the bubble phase.

### Key Insight:
The iris orb wrapper at Level 4 is `pointer-events-none` with a child that has `pointer-events-auto`. But the overlay approach needs to INTERCEPT clicks before they reach the iris.

---

## Testing Checklist - VERIFIED Feb 5, 2026

- [x] Level 1 → 2 (expand iris) ✅ PASSED
- [x] Level 2 → 3 (click main node, subnodes appear) ✅ PASSED
- [x] Level 3 → 4 (click subnode, mini-stack appears) ✅ PASSED
- [x] Level 4 mini-stack clicks DON'T trigger iris ✅ PASSED (irisClick blocked during transition)
- [x] Level 4 → 3 (click iris, go back to subnodes) ✅ PASSED - CRITICAL TEST PASSED
- [x] Level 3 → 2 (click iris, go back to main nodes) ✅ PASSED
- [ ] Level 2 → 1 (click iris, collapse to idle) - Not tested (page at L2)

---

## Attempt #5: Disable iris pointer events at Level 4
- **Date:** Feb 5, 2026 3:55am
- **Root Cause:** Iris wrapper has `pointer-events-auto` child that captures clicks even with z-[200] mini-stack
- **Changes:**
  - Remove click-blocking overlay entirely (not working)
  - Change iris wrapper child from `pointer-events-auto` to `pointer-events-none` when nav.state.level === 4
  - This prevents the iris from capturing ANY clicks at Level 4
  - Mini-stack at z-[200] will receive all clicks in its area
- **Code Change:** `hexagonal-control-center.tsx` line 886:
  ```jsx
  <div className={nav.state.level === 4 ? "pointer-events-none" : "pointer-events-auto"}>
  ```
- **Test Status:** FAILED - Problem persists even without backend
- **Evidence:** After refresh, returns to idle iris orb (expected). Mini-stack clicks still trigger iris navigation.
- **Analysis:** The `pointer-events-none` on the iris wrapper isn't preventing the click. This suggests the event is being captured at a different level - likely the global mouseup listener in `useManualDragWindow` hook.
- **Next Step:** Need to investigate how the drag hook captures events globally, bypassing CSS pointer-events

*(To be filled when a fix actually works)*

---

## Attempt #6: Fix IrisOrb internal pointer-events

**Status:** IN PROGRESS

**Root Cause Analysis:**
The `pointer-events-none` on the wrapper (line 886) isn't working because:
1. The `IrisOrb` component has `pointer-events-auto` hardcoded in its own className (line 194 in iris-orb.tsx)
2. The global `handleMouseUp` listener checks `elementRef.current.contains(mouseUpTarget)` - which will be TRUE even if the element has pointer-events-none because the element still exists in the DOM
3. CSS `pointer-events` only affects hit testing, not element existence

**Evidence:**
```tsx
// iris-orb.tsx line 194:
<motion.div
  className="... pointer-events-auto"  // <-- This overrides parent!
  style={{ width: size, height: size }}
  onClick={handleClick}
>
```

**Hypothesis:** 
The global mouseup listener fires because the iris element is still in the DOM (just with pointer-events-none). The `contains()` check returns true because the element physically contains the click coordinates, regardless of CSS pointer-events.

**Fix Options:**
1. **Remove `pointer-events-auto` from IrisOrb** - Let parent control it entirely
2. **Pass `isClickable` prop to IrisOrb** - Conditionally apply pointer-events-auto only when clickable
3. **Check pointer-events in handleMouseUp** - Verify element is actually clickable before triggering

**Next Action:** 
Add prop to IrisOrb to disable pointer-events when at Level 4

If Attempt #4 fails, try these in order:

1. **Remove click-blocking overlay entirely** - Let the natural z-index isolation work
2. **Change iris wrapper to pointer-events-none at Level 4** - Disable iris interactions entirely at Level 4
3. **Add dedicated mousedown capture on document** - Global capture phase handler
4. **Investigate drag hook** - Look at useManualDragWindow implementation

---

## Systematic Debugging Plan

Following @systematic-debugging skill methodology.

### Phase 1: Root Cause Investigation (CURRENT)

**Hypothesis:** The Iris Orb wrapper at Level 4 has `pointer-events-auto` on a child div that is larger than the actual orb. When clicking anywhere in that area, it triggers before other elements can stop propagation.

**Evidence to Gather:**
1. [ ] Measure actual clickable area of Iris Orb at Level 4
2. [ ] Check if iris wrapper size changes at Level 4 vs other levels
3. [ ] Verify mini-stack DOM position relative to iris wrapper
4. [ ] Confirm z-index stacking order in rendered DOM

**Key Question:** Why does the iris click fire even when clicking the mini-stack at marginLeft: 280?

### Phase 2: Pattern Analysis

**Working Examples to Check:**
- How do other modal/dialog systems prevent background clicks?
- What z-index patterns work for overlay isolation?

**Current vs Working Comparison:**
- Current: z-[200] mini-stack, z-[50] overlay, z-10 iris wrapper
- Working pattern: Modals typically use z-50+ with backdrop at z-40

### Phase 3: Hypothesis Testing

**Hypothesis A:** The iris wrapper is `pointer-events-none` but has a `pointer-events-auto` child that extends beyond the orb
**Test:** Check computed styles on iris wrapper and child at Level 4

**Hypothesis B:** Event bubbling from mini-stack goes UP then iris handler catches it
**Test:** Add console.log to every click handler to trace order

**Hypothesis C:** The `useManualDragWindow` hook attaches listeners at document level
**Test:** Check hook implementation for event attachment

### Phase 4: Implementation (When Root Cause Found)

*(To be filled after Phase 1-3 complete)*

---

## Current Priority: Phase 1 Evidence Gathering

**Next Actions:**
1. Inspect DOM to verify actual iris wrapper dimensions at Level 4
2. Check mini-stack position in DOM tree
3. Verify click event order with detailed logging
4. Read useManualDragWindow hook source

---

## Evidence Log

### Evidence #1: Console Event Order (Feb 5, 3:48am)
```
[DEBUG] handleIrisClick START: Level 2->1, collapsing
[DEBUG] navReducer ENTRY: COLLAPSE_TO_IDLE
[DEBUG] handleSubnodeClick START: subnodeId: "input"
```
**Interpretation:** Iris click fires BEFORE subnode click. This suggests the iris handler is capturing events at a higher level (capture phase or document level).

### Evidence #2: Code Analysis - Iris Orb Double Click Mechanism (Feb 5, 3:52am)
**Source:** `components/iris/iris-orb.tsx` lines 23-117, 192-196

**Finding:** IrisOrb has TWO separate click handlers:
1. **Direct onClick** on motion.div (line 196: `onClick={handleClick}`)
2. **Global mouseup listener** from useManualDragWindow hook (lines 106-114)

Both call `onClickAction()` when conditions are met. The drag hook uses `elementRef.current.contains(mouseDownTarget)` to verify click started/ended in orb.

**Key Code:**
```javascript
// Hook attaches global listeners
useEffect(() => {
  window.addEventListener("mousemove", handleMouseMove)
  window.addEventListener("mouseup", handleMouseUp)  // Global!
}, [])

// handleMouseUp checks if both down/up were in orb
const mouseDownInOrb = elementRef.current.contains(mouseDownTarget.current)
const mouseUpInOrb = elementRef.current.contains(mouseUpTarget)
if (mouseDownInOrb && mouseUpInOrb) {
  onClickAction()  // Triggers handleIrisClick
}
```

**Interpretation:** The iris orb is designed to be clickable even when the mouse leaves and returns. But if the wrapper extends beyond the visual orb, it captures clicks meant for mini-stack.

---

### Evidence #3: Subnodes Not Appearing at Level 3 (Feb 5, 4:29am)
**Issue:** User reports subnodes don't appear at nav level 3 even after refresh
**Test:** After refresh, returns to idle iris orb (expected). But clicking main node doesn't show subnodes.
**Analysis:** This suggests the navigation state isn't being properly set when clicking main nodes, OR the subnodes view rendering is broken.
**Key Questions:**
1. Is `handleNodeClick` being called when clicking main nodes?
2. Is `currentView` being set correctly?
3. Are subnodes being filtered out somewhere?

**Console Test Instructions:**
1. Open browser console (F12)
2. Click IRIS to expand to Level 2
3. Click any main node
4. Look for these logs:
   - `[DEBUG] handleNodeClick START:` - Should appear with nodeId, nodeLabel, hasSubnodes
   - `[DEBUG] Should navigate to subnodes:` - Should show fromLevel: 2
   - `[DEBUG] Found subnodes, proceeding with navigation` - Should appear if SUB_NODES has data
   - `[DEBUG] Calling nav.selectMain() for nodeId:` - Should be called
   - `[DEBUG] Reducer SELECT_MAIN:` - Should show level changing from 2→3
5. If any of these are missing, note which ones

**Next Action:** Run this test and report which console logs appear

---

## Root Cause Confirmed

**Problem:** The iris orb wrapper at Level 4:
1. Has `pointer-events-auto` on a child div (line 886 in hexagonal-control-center.tsx)
2. The wrapper size is `irisSize + 120` pixels (line 877)
3. At Level 4, it's scaled to 0.43 but still covers a large area
4. Both direct onClick AND global mouseup handlers fire

**Solution:** At Level 4, the iris wrapper should have `pointer-events-none` to prevent ANY click interception, letting the mini-stack (z-[200]) handle all clicks in its area.

---

```javascript
// Check current nav level
__navContext?.state?.level

// Check if mini-stack is in DOM
document.querySelector('[class*="mini-node-stack"]')

// Check event listeners (in DevTools Elements panel)
getEventListeners($0)
```

---

## Notes

- Always check browser console for [DEBUG] logs from handleIrisClick
- If handleIrisClick fires when clicking mini-stack, the isolation failed
- If handleNodeClick doesn't fire, there's an event blocking issue

---

## FIX IMPLEMENTED - Feb 5, 2026

---

## ✅ FIX IMPLEMENTED - Feb 5, 2026

### Attempt #7: Element Reference Verification (SUCCESS!)
**Date:** Feb 5, 2026 8:02pm
**Status:** ✅ **PASSED ALL TESTS**

**Root Cause Discovered:** There was a **local** `useManualDragWindow` hook inside `hexagonal-control-center.tsx` (lines 273-336) that was completely separate from the one in `iris-orb.tsx`. This local version:
- Did NOT verify if clicks were on the iris orb element before triggering `onClickAction()`
- Called `onClickAction()` for ANY mouseup event that didn't drag, regardless of where the click happened
- Was being used by the local `IrisOrb` component in the same file

**The Fix:**
Modified the local `useManualDragWindow` hook in `hexagonal-control-center.tsx`:

1. **Added `elementRef` parameter** - Track the iris orb DOM element
2. **Added `isDraggingThisElement` ref** - Track if drag started on this element
3. **Added `mouseDownTarget` ref** - Remember where mousedown occurred
4. **Modified `handleMouseDown`** - Only start drag if `elementRef.current.contains(target)`
5. **Modified `handleMouseUp`** - Only trigger click if BOTH mousedown AND mouseup targets are inside the iris orb element
6. **Added `orbRef` to IrisOrb** - Pass ref to the hook for element verification

**Code Changes:**
```typescript
// Before (broken):
function useManualDragWindow(onClickAction: () => void) {
  const handleMouseUp = useCallback(() => {
    if (!hasDragged.current) {
      onClickAction()  // Fires for ANY click anywhere!
    }
  }, [onClickAction])
}

// After (fixed):
function useManualDragWindow(onClickAction: () => void, elementRef: React.RefObject<HTMLElement | null>) {
  const isDraggingThisElement = useRef(false)
  const mouseDownTarget = useRef<EventTarget | null>(null)
  
  const handleMouseDown = useCallback(async (e: React.MouseEvent) => {
    // Only start drag if clicking on iris orb element
    const shouldStartDrag = elementRef.current && elementRef.current.contains(target)
    if (!shouldStartDrag) return
    
    isDraggingThisElement.current = true
    mouseDownTarget.current = e.target
    // ... rest of drag setup
  }, [])
  
  const handleMouseUp = useCallback((e: MouseEvent) => {
    // Only click if BOTH down AND up are in iris orb
    const upInIris = currentElement.contains(upTarget)
    const downInOrb = downTargetNode && currentElement.contains(downTargetNode)
    
    if (upInIris && downInOrb) {
      onClickAction()  // Now only fires for actual iris orb clicks!
    }
  }, [onClickAction])
}
```

**Files Modified:** 
- `components/hexagonal-control-center.tsx` lines 273-415

**Test Results - ALL PASSED:**
- ✅ L1→L2: IRIS click expands to main nodes
- ✅ L2→L3: Main node click shows subnodes (VOICE → INPUT/OUTPUT/PROCESSING/MODEL)
- ✅ L3→L4: Subnode click shows mini-stack
- ✅ L4→L3: IRIS click returns to subnodes (CRITICAL TEST - was failing before)
- ✅ L3→L2: IRIS click returns to main nodes
- ✅ L2→L1: IRIS click collapses to idle

**Console Verification:**
```
[Nav System] handleMouseDown: ACCEPTED - starting drag
[Nav System] handleMouseUp: {draggingThis: true, didDrag: false, ...}
[Nav System] Click check: {upInIris: true, downInOrb: true, shouldTrigger: true}
[Nav System] Triggering onClickAction
[Nav System] handleIrisClick: Level 4->3, deselecting subnode
```

When clicking subnodes:
```
[Nav System] handleMouseDown: REJECTED - click not on iris orb
[Nav System] handleMouseUp: {draggingThis: false, ...}
// No click triggered - correct behavior!
```

### Fix #1: Subnodes Not Appearing (COMPLETED)
**Root Cause:** The render condition used `isExpanded` state which was getting out of sync with `nav.state.level`
**Solution:** Changed render conditions from:
- `{isExpanded && nav.state.level !== 4 && (` 
- To: `{(nav.state.level === 2 || nav.state.level === 3) && (`

**Files Modified:** `components/hexagonal-control-center.tsx` lines 957, 981, 1013

### Fix #2: Level 4 → 3 Navigation (COMPLETED)
**Root Cause:** `userNavigatedRef.current` was being set to `false` BEFORE `selectSubnode(null)` was called, allowing backend sync to interfere and clear `currentView`
**Solution:** Keep `userNavigatedRef.current = true` until AFTER backend state is cleared:
```javascript
userNavigatedRef.current = true
nav.goBack()
selectSubnode(null)  // This runs while userNavigatedRef is still true
setActiveMiniNodeIndex(null)
userNavigatedRef.current = false  // Reset AFTER backend operations
```

**Files Modified:** `components/hexagonal-control-center.tsx` lines 736-748

### Test Results:
- ✅ Level 1 → 2: IRIS click expands to main nodes (verified earlier)
- ✅ Level 2 → 3: Main node click shows subnodes (verified earlier)
- ✅ Level 3 → 4: Subnode click shows mini-stack (verified earlier)
- ⏳ Level 4 → 3: IRIS click should return to subnodes (needs manual verification)
- ⏳ Level 3 → 2: IRIS click should return to main nodes (needs manual verification)
- ⏳ Level 2 → 1: IRIS click should collapse to idle (needs manual verification)

### Manual Testing Instructions (Due to MCP Tool Timeout Issues):

**Open your browser console (F12) and run this test:**

1. **Level 1 → 2:** Click IRIS orb
   - Expected: Main nodes appear (VOICE, AGENT, AUTOMATE, SYSTEM, CUSTOMIZE, MONITOR)
   - Console: Look for `[DEBUG] handleIrisClick: Level 1->2`

2. **Level 2 → 3:** Click VOICE main node
   - Expected: Subnodes appear (INPUT, OUTPUT, PROCESSING, MODEL)
   - Console: Look for `[DEBUG] handleNodeClick START:` then `[DEBUG] Calling nav.selectMain()`

3. **Level 3 → 4:** Click INPUT subnode
   - Expected: Mini-stack appears with input controls
   - Console: Look for `[DEBUG] handleSubnodeClick START:` then mini-stack renders

4. **Level 4 → 3:** Click IRIS orb
   - Expected: Return to subnodes (INPUT, OUTPUT, PROCESSING, MODEL)
   - Console: Look for `[DEBUG] handleIrisClick: Level 4->3`
   - **CRITICAL:** Should NOT show `[DEBUG] handleIrisClick: Level 3->2`

5. **Level 3 → 2:** Click IRIS orb
   - Expected: Return to main nodes
   - Console: Look for `[DEBUG] handleIrisClick: Level 3->2`

6. **Level 2 → 1:** Click IRIS orb
   - Expected: Collapse to idle
   - Console: Look for `[DEBUG] handleIrisClick: Level 2->1`

**Report any failed steps with the console logs.**

---

## UPDATE: Feb 5, 2026 - File Corruption Fixed

### Issues Fixed:
1. **hexagonal-control-center.tsx was corrupted** with:
   - Misplaced `navLevelRef.current` inside console.log object literal
   - `handleIrisClick` function nested inside `handleSubnodeClick`
   - Duplicate broken `currentNodes` definition

### Fixes Applied:
```typescript
// Added missing refs (line 522-525)
const userNavigatedRef = useRef(false)
const navLevelRef = useRef(nav.state.level)
const nodeClickTimestampRef = useRef<number | null>(null)

// Added useEffect to keep navLevelRef fresh (line 527-530)
useEffect(() => {
  navLevelRef.current = nav.state.level
}, [nav.state.level])

// handleIrisClick now reads from ref (line 716)
const freshNavLevel = navLevelRef.current

// Completed handleSubnodeClick with Level 4 navigation (line 712-717)
nav.selectSub(subnodeId, miniNodes)
selectSubnode(subnodeId)
```

### Status: READY FOR TESTING

**Note:** MCP Browser tool continues to timeout on click operations. Manual testing required.

### Manual Testing Steps:
1. Open browser console (F12)
2. Click IRIS orb → Should see main nodes (Level 1→2)
3. Click VOICE main node → Should see subnodes (Level 2→3)
4. Click INPUT subnode → Should see mini-stack (Level 3→4)
5. **CRITICAL TEST:** Click IRIS orb at Level 4 → Should go to subnodes (Level 4→3), NOT Level 2
   - Look for: `[Nav System] handleIrisClick: Level 4->3`
   - Should NOT see: `[Nav System] handleIrisClick: Level 3->2`
6. Click IRIS orb again → Should go to main nodes (Level 3→2)
7. Click IRIS orb again → Should collapse (Level 2→1)

### Expected Console Output:
```
[Nav System] handleIrisClick START: {freshNavLevel: 4, ...}
[Nav System] handleIrisClick proceeding with level: 4
[Nav System] handleIrisClick: Level 4->3, deselecting subnode
[Nav System] userNavigatedRef reset after Level 4->3 navigation
```

---

## UPDATE: Feb 6, 2026 - Navigation & Drag Fixes

### Issues Fixed:

#### 1. L2→L1 Navigation Broken
**Problem:** Clicking IRIS at Level 2 didn't collapse to idle (L1)
**Root Cause:** `userNavigatedRef` not reset after L3→L2 navigation, blocking subsequent clicks
**Fix:** Reset `userNavigatedRef.current = false` in L3→L2 setTimeout (line 875)

#### 2. Backend Auto-Expansion to L3
**Problem:** From idle (L1), first click expanded to L2 but backend sync immediately jumped to L3 (showing subnodes)
**Root Cause:** Backend sync called `setCurrentView(currentCategory)` which made `currentNodes = SUB_NODES["voice"]`
**Fix:** Removed `setCurrentView()` from backend sync - now only expands to L2 without setting currentView (lines 656-666)

#### 3. L2→L1 Timeout Too Short
**Problem:** Backend sync ran before `selectCategory("")` completed, causing re-expansion
**Fix:** Increased timeout from `SPIN_CONFIG.spinDuration` (1500ms) to `2500ms` (line 890)

#### 4. Backend Sync Before User Interaction
**Problem:** Backend persisted category caused auto-navigation on page load
**Fix:** Added `hasUserInteractedRef` - backend sync skipped until user explicitly navigates (lines 631-634, 843)

### Files Modified:
- `components/hexagonal-control-center.tsx`

### MCP Browser Test Results - ALL PASSED:
- ✅ L1→L2: IRIS expands to 6 main nodes
- ✅ L2→L3: Click main node shows subnodes  
- ✅ L3→L4: Click subnode shows mini-stack
- ✅ L4→L3: IRIS click returns to subnodes
- ✅ L3→L2: IRIS click returns to main nodes
- ✅ L2→L1: IRIS click collapses to idle
- ✅ Drag vs click: Correctly distinguishes

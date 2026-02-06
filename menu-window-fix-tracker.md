
# Menu Window Fix Tracker

**Created:** February 5, 2026  
**Purpose:** Track and log all fixes for menu window state synchronization red flags  
**Status:** Active Investigation

---

## Red Flag Registry

| ID | Description | Severity | Status | File(s) | Detection Method | Notes |
|----|-------------|----------|--------|---------|------------------|-------|
| RF-001 | Duplicate useState in children | High | Investigating | All menu components | `grep -r "useState.*isOpen" components/` | Check for shadow state |
| RF-002 | Missing parent callback wiring | High | Investigating | Button, Dashboard | `grep -n "onClick\|onClose" components/*.tsx` | Verify event flow |
| RF-003 | AnimatePresence state drift | Medium | Investigating | dark-glass-dashboard.tsx | Visual inspection + rapid toggle test | Animation sync issues |
| RF-004 | Stale closure in callbacks | Medium | Investigating | All event handlers | Code review: `setIsOpen(!isOpen)` vs `setIsOpen(prev => !prev)` | useCallback audit |
| RF-005 | Race condition on rapid toggle | Medium | Investigating | page.tsx | Spam click test + console logs | State batching behavior |

---

## Detection Method Summary

### Automated Detection Commands

```bash
# RF-001: Duplicate state detection
grep -rn "useState.*isOpen\|useState.*open" components/
# Expected: No matches (confirmed ✓)

# RF-002: Callback wiring verification  
grep -n "onClick\|onClose" components/menu-window-button.tsx components/dark-glass-dashboard.tsx
# Expected: Calls parent handlers

# RF-003: Animation sync check
grep -n "onAnimationComplete\|exit.*duration" components/dark-glass-dashboard.tsx
# Expected: Proper exit animation handling

# RF-004: Stale closure detection
grep -n "setIsOpen(!" app/menu-window/page.tsx
# Expected: Should use functional updates

# RF-005: Race condition analysis
# Manual: Rapid click test in browser
```

---

## Verification Steps

### Step 1: State Ownership Verification
- [x] Run `grep -r "useState.*isOpen" components/` 
- [x] Confirm only `page.tsx` has `useState(false)` for `isOpen`
- [x] Document line numbers: `page.tsx:8`

### Step 2: Prop Interface Verification
- [x] Check `DarkGlassDashboardProps` interface
- [x] Check `MenuWindowButtonProps` interface
- [x] Confirm no local state shadowing

### Step 3: Event Handler Chain Verification
- [x] Verify button onClick routes to parent
- [x] Verify backdrop onClick routes to parent
- [x] Confirm no direct state mutation in children

### Step 4: Animation Sync Verification
- [ ] Test rapid open/close (10 clicks in 500ms)
- [ ] Verify visual state matches React state
- [ ] Check for orphaned DOM elements

### Step 5: Manual Integration Testing
- [ ] Click button opens dashboard
- [ ] Click button again closes dashboard
- [ ] Click backdrop closes dashboard
- [ ] Button label updates immediately

---

## Test Results

### Automated Test Results

| Test | Command/Method | Expected | Actual | Status |
|------|---------------|----------|--------|--------|
| Single source of truth | `grep useState.*isOpen components/` | No results | No results | ✓ PASS |
| Prop interface check | `grep interface.*Props` | Clean interfaces | Clean interfaces | ✓ PASS |
| No shadow state | `grep useState(props` | No results | No results | ✓ PASS |

### Manual Test Results

| Test | Steps | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| Basic toggle | Click button 1x | Dashboard opens | TBD | ⏳ PENDING |
| Close via button | Click button 2x | Dashboard closes | TBD | ⏳ PENDING |
| Close via backdrop | Click backdrop | Dashboard closes | TBD | ⏳ PENDING |
| Rapid toggle | Click 10x rapidly | No desync | TBD | ⏳ PENDING |
| Label sync | Watch button text | Immediate update | TBD | ⏳ PENDING |

---

## Regression Tests

### Pre-Change Baseline
- [ ] Screenshot/video current behavior
- [ ] Document current state architecture
- [ ] Note any existing animation quirks

### Post-Change Verification
- [ ] Run all Manual Test Results
- [ ] Verify no new console warnings
- [ ] Confirm TypeScript builds without errors
- [ ] Test in both dev and production builds

### Edge Case Regression Suite
- [ ] Very rapid toggles (< 50ms between clicks)
- [ ] Click during exit animation
- [ ] Click during enter animation
- [ ] Backdrop click during animation
- [ ] Keyboard navigation (Tab + Enter/Space)

---

## Blocking Issues

| ID | Issue | Impact | Workaround | Resolution Priority |
|----|-------|--------|------------|---------------------|
| BI-001 | None currently | - | - | - |

---

## Fix Log

### [2026-02-05] Initial Review
- **Action:** Comprehensive state management audit
- **Findings:** 
  - Parent (`page.tsx`) owns `isOpen` state correctly
  - Child components receive props, no local state shadowing found
  - Event flow unidirectional (parent -> child via props, child -> parent via callbacks)
- **Status:** No immediate red flags detected, continuing investigation

---

## Debug Checklist Progress

- [x] Verify single `useState` for `isOpen` (page.tsx only)
- [x] Confirm children receive `isOpen` as read-only prop
- [ ] Test rapid toggle (spam click)
- [ ] Test backdrop click close
- [ ] Test animation completion sync
- [ ] Verify button label immediate sync
- [ ] Audit for stale closures
- [ ] Check for race conditions

---

## Investigation Notes

### State Ownership
- Owner: `app/menu-window/page.tsx` line 8: `const [isOpen, setIsOpen] = useState(false)`
- Prop chain: `isOpen` → `DarkGlassDashboard`, `MenuWindowButton`
- No child components have `useState` for open/closed state

### Event Flow
- Button click: `onClick={() => setIsOpen(!isOpen)}` (parent handler)
- Backdrop click: `onClose={() => setIsOpen(false)}` (parent handler)
- Container: Pure presentational, no state mutation

### Potential Risk Areas
1. **AnimatePresence exit animation** - Could cause visual/functional desync if animation hangs
2. **Backdrop click propagation** - z-index or bubbling issues
3. **Button rapid clicks** - State update batching behavior

---

## Pending Actions

- [ ] Complete manual testing (see Test Results section)
- [ ] Add comprehensive event logging for debug
- [ ] Implement boundary tests for edge cases
- [ ] Document final state architecture

---

## References

- Plan: `menu-window-fix-plan.md`
- Parent Component: `app/menu-window/page.tsx`
- Dashboard: `components/dark-glass-dashboard.tsx`
- Button: `components/menu-window-button.tsx`
- Theme Context: `contexts/DashboardThemeContext.tsx`

---

**Last Updated:** 2026-02-05  
**Next Review:** TBD

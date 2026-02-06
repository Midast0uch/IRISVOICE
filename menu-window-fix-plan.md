
# Menu Window Red Flag Fix Plan

Create comprehensive tracking system for menu window state synchronization issues and establish fix protocols.

---

## Current Status

Initial review of `app/menu-window/page.tsx` and components found state management appears correct (lifted state pattern), but establishing formal tracking to verify all edge cases and potential desync scenarios.

---

## One-Line Check

Quick validation command to verify state ownership:

```bash
# Verify only page.tsx has useState for isOpen
grep -r "useState.*isOpen\|useState.*open" components/ || echo "✓ No duplicate state in components"

# Verify prop drilling pattern
grep -A2 "interface.*Props" components/dark-glass-dashboard.tsx components/menu-window-button.tsx
```

**Expected Result:**
- Only `app/menu-window/page.tsx` should contain `useState(false)` for `isOpen`
- Child components (`DarkGlassDashboard`, `MenuWindowButton`) should receive `isOpen` via props only
- No `useState` patterns for open/close state in `components/` directory

---

## Investigation Areas

### 1. State Ownership Verification
- **File**: `app/menu-window/page.tsx` (line 8)
- **Check**: Confirm `useState(false)` is the single source of truth
- **Risk**: Child components might shadow state
- **Test**: Verify no `useState` for `isOpen` exists in child components
- **Code Ref**: `const [isOpen, setIsOpen] = useState(false);`

### 2. Prop Drilling Audit
- **Files**: `components/dark-glass-dashboard.tsx`, `components/menu-window-button.tsx`
- **Check**: Ensure props are read-only in children
- **Risk**: Children might cache props in local state
- **Test**: Search for `useState(props.isOpen)` patterns
- **Safe Pattern**: `interface MenuWindowButtonProps { onClick: () => void; isOpen: boolean; }`

### 3. Event Handler Chain
- **Files**: `components/menu-window-button.tsx`, `components/dark-glass-dashboard.tsx`
- **Check**: All state mutations route through parent
- **Risk**: Event handlers might bypass parent
- **Test**: Verify all `onClick` callbacks invoke parent handlers
- **Code Ref**: `onClick={() => setIsOpen(!isOpen)}` (parent handler in page.tsx)

### 4. AnimatePresence State Sync
- **File**: `components/dark-glass-dashboard.tsx` (lines 16-53)
- **Check**: Framer Motion exit animations don't cause state drift
- **Risk**: Animation completion might desync from React state
- **Test**: Rapid open/close cycles
- **Code Ref**: `<AnimatePresence>{isOpen && (<motion.div...>)}</AnimatePresence>`

### 5. Backdrop Click Handler
- **File**: `components/dark-glass-dashboard.tsx` (line 26)
- **Check**: Backdrop click reliably triggers `onClose`
- **Risk**: Event bubbling or z-index issues
- **Test**: Click various areas of backdrop
- **Code Ref**: `onClick={onClose}` on backdrop div

---

## Safe vs Unsafe Patterns

| Pattern | Safe | Unsafe |
|---------|------|--------|
| State Location | `useState` in parent only | `useState` in child + parent |
| Props Usage | Read `isOpen` from props | `useState(props.isOpen)` |
| Event Handling | Call parent callback | Direct state mutation in child |
| Animation Sync | `onAnimationComplete` callback | No sync mechanism |
| Callback Closure | Functional updates `setIsOpen(prev => !prev)` | Direct reference `setIsOpen(!isOpen)` |

---

## Fix Protocol

| Priority | Issue | Fix Approach | Verification Command |
|----------|-------|--------------|---------------------|
| P0 | Duplicate state in children | Remove child `useState`, use props only | `grep -r "useState.*isOpen" components/` |
| P1 | Missing parent callback | Wire child events to parent handlers | Verify `onClick` invokes parent setter |
| P1 | Stale closure in callback | Use functional updates or `useCallback` | `setIsOpen(prev => !prev)` |
| P2 | Animation state drift | Add `onAnimationComplete` sync | Test rapid toggle, verify sync |

---

## Verification Commands

### Pre-Implementation Checks
```bash
# 1. Verify single source of truth
grep -rn "useState.*isOpen\|useState.*open" app/menu-window/ components/
# Expected: Only app/menu-window/page.tsx:8

# 2. Check prop interfaces
grep -A3 "interface.*Props" components/dark-glass-dashboard.tsx
# Expected: isOpen: boolean; onClose: () => void;

# 3. Verify event handler wiring
grep -n "onClick\|onClose" components/menu-window-button.tsx components/dark-glass-dashboard.tsx
# Expected: Calls parent handlers only
```

### Post-Implementation Verification
```bash
# 1. Build check
npm run build

# 2. Type check
npx tsc --noEmit

# 3. Run dev server on isolated port
cd c:\dev\IRISVOICE && npx next dev -p 3003
```

### Runtime Verification (Browser Console)
```javascript
// Test 1: Rapid toggle
const btn = document.querySelector('button.fixed'); // Selects the menu button
for(let i=0; i<10; i++) setTimeout(() => btn.click(), i*50);

// Test 2: Backdrop click closes
const backdrop = document.querySelector('.fixed.inset-0.z-40');
if (backdrop) backdrop.click();

// Test 3: State sync check
console.log('Button text:', btn.textContent); // Should be "Menu Window" or "Close Menu"
console.log('Dashboard visible:', !!document.querySelector('.fixed.inset-0.z-40'));
```

---

## Rollback Strategy

### If Issues Detected
1. **Immediate**: Revert to last known good commit
   ```bash
   git log --oneline -5  # Find last good commit
   git checkout <commit-hash> -- app/menu-window/ components/
   ```

2. **Partial**: Disable problematic component
   ```tsx
   // In page.tsx - comment out problematic component
   {/* <DarkGlassDashboard isOpen={isOpen} onClose={() => setIsOpen(false)} /> */}
   ```

3. **Emergency**: Add safety wrapper
   ```tsx
   // Add state validation wrapper
   const safeSetIsOpen = (value: boolean) => {
     if (typeof value === 'boolean') setIsOpen(value);
   };
   ```

### Rollback Checklist
- [ ] Revert code changes
- [ ] Clear Next.js cache (`rm -rf .next`)
- [ ] Restart dev server
- [ ] Verify basic functionality restored
- [ ] Document failure reason in tracker

---

## Debug Checklist

- [ ] Verify single `useState` for `isOpen` (page.tsx only)
- [ ] Confirm all children receive `isOpen` as prop (not from context/state)
- [ ] Test rapid toggle (spam click button)
- [ ] Test backdrop click close
- [ ] Test programmatic close (if exposed)
- [ ] Verify button label syncs immediately ("Menu Window" <-> "Close Menu")
- [ ] Audit for stale closures (use functional updates)
- [ ] Check for race conditions (rapid state changes)

---

## Tracking File

All fixes and debug results logged to: `menu-window-fix-tracker.md`

---

## Constraints

- DO NOT modify navigation code (hexagonal-control-center, NavigationContext)
- Isolate all changes to menu window components only
- Maintain existing component interfaces where possible

---

## References

- Tracker: `menu-window-fix-tracker.md`
- Parent Component: `app/menu-window/page.tsx`
- Dashboard: `components/dark-glass-dashboard.tsx`
- Button: `components/menu-window-button.tsx`

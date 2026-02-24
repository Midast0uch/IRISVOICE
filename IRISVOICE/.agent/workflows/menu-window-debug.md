---
description: Debug and verify menu window state synchronization
---

# Menu Window Debug Workflow

This workflow automates the verification steps for the menu window state synchronization issues.

## 1. Quick State Check
Verify that state is properly isolated to the parent page component.

// turbo
```bash
grep -r "useState.*isOpen\|useState.*open" components/ || echo "✓ No duplicate state in components"
```

## 2. Verify Prop Interfaces
Ensure child components are receiving props correctly and not shadowing state.

// turbo
```bash
grep -A2 "interface.*Props" components/dark-glass-dashboard.tsx components/menu-window-button.tsx
```

## 3. Verify Event Handlers
Ensure that click handlers are properly wired to parent callbacks.

// turbo
```bash
grep -n "onClick\|onClose" components/menu-window-button.tsx components/dark-glass-dashboard.tsx
```

## 4. Animation Check
Check for AnimatePresence and exit animation configurations.

// turbo
```bash
grep -n "AnimatePresence\|exit.*duration" components/dark-glass-dashboard.tsx
```

## 5. Development Server
Start the development server on the isolated port (3003) for manual testing.

```bash
npx next dev -p 3003
```

## 6. Manual Verification Steps
Once the server is running, open http://localhost:3003/menu-window and perform:
1.  **Rapid Toggle**: Click the menu button 10 times rapidly.
2.  **Backdrop Close**: Open menu, then click the dark backdrop.
3.  **Label Sync**: Verify button text toggles between "Menu Window" and "Close Menu".


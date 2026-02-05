# Phase 5: Orbit System Plan

## Objective
Implement confirmed mini nodes orbiting around the shrunken IrisOrb with arc path animation and recall functionality.

## Tasks

1. **Create OrbitNode component**
   - 90px size confirmed node
   - Position along arc path (top of orbit)
   - Counter-rotation to stay upright
   - Click handler for recall

2. **Update NavigationContext**
   - Add recallConfirmedNode action
   - Update reducer to handle recall
   - Jump to mini node index on recall

3. **Integrate with HexagonalControlCenter**
   - Render confirmed nodes in orbit
   - Position relative to shrunken IrisOrb
   - Animate along arc path

4. **Implement arc path animation**
   - Calculate arc positions (top 180 degrees)
   - Animate nodes along arc
   - Smooth 60fps performance

5. **Add recall functionality**
   - Click orbit node to recall
   - Jump to corresponding mini node
   - Visual feedback on recall

6. **Cleanup on exit**
   - Orbit nodes fade out on L4→L3
   - Proper AnimatePresence handling

7. **Verify**
   - Nodes orbit smoothly
   - Recall works correctly
   - No navigation breaks

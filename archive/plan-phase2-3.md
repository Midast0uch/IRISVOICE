# Phase 3: IrisOrb Transformation Plan

## Objective
Implement IrisOrb shrink/grow animations for Level 4 transition.

## Tasks

1. **Modify IrisOrb component**
   - Add shrink scale animation (1 → 0.45, 600ms)
   - Add blur backdrop effect (8px)
   - Position shrunken orb top-left of mini node stack
   - Add grow animation for return to L3 (0.45 → 1, 400ms)

2. **Update HexagonalControlCenter**
   - Pass level prop to IrisOrb
   - Handle positioning when level === 4
   - Animate position change smoothly

3. **Add visual indicators**
   - Glow pulse on shrunken orb
   - Connection line from orb to active card

4. **Verify**
   - Smooth scale transitions (no jank)
   - Correct positioning at all levels
   - Navigation still works

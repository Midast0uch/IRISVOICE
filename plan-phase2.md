# Phase 2 Plan: Basic Transitions

## Objective
Implement Pure Fade and Pop Out transition animations.

## Files to Create/Modify
1. `lib/transitions.ts` - New file for transition variant functions
2. `components/hexagonal-control-center.tsx` - Integrate transitions

## Implementation Steps
1. Create transition variant functions:
   - Pure Fade: Simple opacity crossfade
   - Pop Out: Scale/translate burst animation

2. Create useTransitionVariants hook to get animation props based on current transition

3. Integrate into HexagonalNode component

4. Test both transitions with navigation

## Success Criteria
- Pure Fade transition works
- Pop Out transition works
- Can switch between transitions
- Visuals look correct
- Navigation works with both
- No console errors

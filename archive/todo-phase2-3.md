# Phase 2 Todo - Mini Node Stack System

## MiniNodeCard Component
- [ ] Create MiniNodeCard.tsx with props (miniNode, isActive, values, onChange, onSave)
- [ ] Add icon rendering using Lucide icons
- [ ] Implement field rendering switch (text/slider/dropdown/toggle/color)
- [ ] Add active state styling (white border 2px, scale 1.05)
- [ ] Create Save button with pulse animation on hover
- [ ] Implement confirm animation (scale 0.8 → 1.2 → 1)

## MiniNodeStack Component
- [ ] Create MiniNodeStack.tsx component
- [ ] Implement 4-card fan layout (0deg, -15deg, -30deg, -45deg)
- [ ] Add card spacing (100px apart)
- [ ] Connect to NavigationContext for rotation
- [ ] Add rotation animation (carousel effect, 300ms duration)
- [ ] Handle click on card to jump to that index
- [ ] Handle click behind cards for navigation

## Level4View Component
- [ ] Create Level4View.tsx for Level 4 rendering
- [ ] Integrate MiniNodeStack
- [ ] Handle empty miniNodeStack state
- [ ] Add entry animation (cards from center, scale 0→1)
- [ ] Add exit animation (cards retract to center)

## HexagonalControlCenter Integration
- [ ] Add Level 4 condition in render
- [ ] Import and render Level4View when level === 4
- [ ] Connect miniNodeStack from context
- [ ] Add rotation controls (arrows or swipe)

## Testing
- [ ] Cards render in fan layout
- [ ] Rotation animates smoothly
- [ ] Fields display and update values
- [ ] Save button triggers confirm animation
- [ ] Navigation L3→L4→L3 works

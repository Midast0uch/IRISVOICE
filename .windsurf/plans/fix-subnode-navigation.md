# Plan: Fix Subnode Navigation Transition

## Problem
Subnodes are not transitioning out when clicking a main node. The navigation flow is broken between main nodes and subnodes.

## Root Cause Analysis

### Navigation Flow Issues Found:

1. **State Synchronization Conflict** (hexagonal-control-center.tsx:810-817)
   - `currentView` is managed both locally AND synced from WebSocket `currentCategory`
   - Effect forces `currentView = currentCategory` when they differ
   - This overrides local navigation state mid-transition

2. **handleNodeClick Logic Problem** (hexagonal-control-center.tsx:840-861)
   - Only transitions if `!currentView` (null check)
   - Sets `currentView` immediately AND calls `selectCategory` after timeout
   - Race condition between local state and WebSocket sync

3. **Missing Transition Logic**
   - No handler for clicking a different main node when already in a category
   - No proper exit animation for current subnodes before showing new ones

4. **WebSocket Message Flow**
   - `selectCategory` sends message but doesn't await confirmation
   - Backend may reject or delay, causing desync

## Required Fixes

### Phase 1: Fix State Management
- [ ] Remove forced sync effect that overrides local navigation
- [ ] Ensure `pendingView` properly tracks requested transitions
- [ ] Handle WebSocket `category_changed` as confirmation, not override

### Phase 2: Fix handleNodeClick
- [ ] Handle clicking main node when already in a category (transition out, then in)
- [ ] Ensure proper exit animation before entering new category
- [ ] Fix race condition between local state and WebSocket

### Phase 3: Fix handleSubnodeClick
- [ ] Verify subnode selection triggers mini node stack display
- [ ] Ensure field components mount correctly

### Phase 4: Test Navigation Flows
- [ ] Main view → Click node → Subnodes appear
- [ ] Subnode view → Click different main node → Exit, then new subnodes appear
- [ ] Subnode view → Click same main node → Stay in category
- [ ] Subnode view → Click subnode → Mini node stack appears with fields

## Files to Modify
- `c:\dev\IRISVOICE\components\hexagonal-control-center.tsx`
- `c:\dev\IRISVOICE\hooks\useIRISWebSocket.ts` (if message flow needs adjustment)

# Phase 1: Infrastructure Plan

## Objective
Extend NavigationContext with mini node stack state management, types, and localStorage persistence.

## Tasks

1. **Extend types/navigation.ts**
   - Add MiniNode interface (id, label, icon, fields)
   - Add FieldConfig interface (id, type, label, etc)
   - Add ConfirmedNode interface (id, label, icon, values, orbitAngle, timestamp)
   - Extend NavState with miniNodeStack, activeMiniNodeIndex, confirmedMiniNodes, miniNodeValues
   - Add new NavAction types for stack rotation, confirm, update values

2. **Update NavigationContext.tsx**
   - Add new state fields to initialState
   - Implement reducer cases for new actions
   - Add localStorage persistence for miniNodeValues (iris-mini-node-values key)
   - Add helper functions: rotateStack, jumpToMiniNode, confirmMiniNode, updateMiniNodeValue

3. **Create mini node configuration**
   - Create data/mini-nodes.ts with SUB_NODES_WITH_MINI structure
   - Define field configurations for each mini node
   - Max 3 fields per mini node as per PRD

4. **Verify implementation**
   - Context has all new fields
   - localStorage saves/loads correctly
   - No TypeScript errors

# Design: sendMessage Signature Fix

## Overview

This fix addresses TypeScript type mismatches for the `sendMessage` function prop across React components. The solution involves:

1. Exporting a reusable type definition from the hook
2. Updating component prop interfaces to use the correct type
3. Fixing incorrect call sites where sendMessage was being called with wrong arguments
4. Verifying TypeScript compilation passes

## Architecture

### Type Definition Strategy

Export a type alias from `useIRISWebSocket.ts` that can be imported by components:

```typescript
// In hooks/useIRISWebSocket.ts
export type SendMessageFunction = (
  type: string,
  payload?: Record<string, unknown>
) => boolean;
```

### Component Updates

Update prop interfaces in affected components to use the exported type:

```typescript
// In components/chat-view.tsx and dashboard-wing.tsx
import { SendMessageFunction } from "@/hooks/useIRISWebSocket";

interface ChatWingProps {
  isOpen: boolean;
  onClose: () => void;
  onDashboardClick: () => void;
  sendMessage?: SendMessageFunction;
  fieldValues?: Record<string, any>;
  updateField?: (subnodeId: string, fieldId: string, value: any) => void;
}
```

### Call Site Fixes

Fix the incorrect sendMessage call in `chat-view.tsx`:

**Before:**
```typescript
sendMessage({
  source: "chat_view",
  type: "text_message",
  payload: { text: userMessage.text }
})
```

**After:**
```typescript
sendMessage("text_message", { text: userMessage.text })
```

## Files to Modify

| File | Changes |
|------|---------|
| `hooks/useIRISWebSocket.ts` | Export `SendMessageFunction` type |
| `components/chat-view.tsx` | Update prop type, fix call site |
| `components/dashboard-wing.tsx` | Update prop type |

## Sequence Diagram

```
┌─────────────┐          ┌─────────────────┐          ┌─────────────────────┐
│  ChatWing   │          │  useIRISWebSocket │          │   WebSocket Server  │
└──────┬──────┘          └────────┬────────┘          └──────────┬──────────┘
       │                          │                              │
       │  sendMessage(type, payload)                              │
       │─────────────────────────>│                              │
       │                          │                              │
       │                          │  ws.send({type, payload})    │
       │                          │─────────────────────────────>│
       │                          │                              │
       │                          │  Response                    │
       │                          │<─────────────────────────────│
       │                          │                              │
       │  return boolean          │                              │
       │<─────────────────────────│                              │
       │                          │                              │
```

## Key Design Decisions

### Decision 1: Export Type from Hook
**Choice:** Export `SendMessageFunction` type from `useIRISWebSocket.ts`
**Rationale:** 
- Single source of truth for the type definition
- Components that use the hook naturally import from the same location
- If the hook signature changes, the type automatically updates

**Alternative considered:** Create a separate types file
- Rejected because it adds unnecessary indirection for a single type

### Decision 2: Keep Optional Prop
**Choice:** Keep `sendMessage` as optional (`sendMessage?`)
**Rationale:**
- Components can be rendered without WebSocket functionality (e.g., in tests or standalone mode)
- Backward compatible with existing usages

### Decision 3: Payload as Optional
**Choice:** Payload parameter is optional (`payload?:`)
**Rationale:**
- Some messages like `request_state` don't require a payload
- Matches the existing hook implementation

## Error Handling

Components should handle the case where sendMessage returns false (indicating WebSocket not connected):

```typescript
const sent = sendMessage("text_message", { text });
if (!sent) {
  // Handle offline state - queue message or show warning
}
```

## Testing Strategy

1. **TypeScript Compilation:** Run `tsc --noEmit` to verify no type errors
2. **Unit Tests:** Verify ChatWing calls sendMessage with correct arguments
3. **Integration Tests:** Verify messages sent from chat reach the backend correctly

## Migration Path

1. Add type export to useIRISWebSocket.ts
2. Update ChatWing component (prop type + call site)
3. Update DashboardWing component (prop type)
4. Run TypeScript check to verify no errors
5. Run tests to verify functionality

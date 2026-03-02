# Implementation Plan: sendMessage Signature Fix

- [ ] 1. Export SendMessageFunction Type from useIRISWebSocket
  - [ ] 1.1 Add type export to useIRISWebSocket.ts
    - What to build: Export `SendMessageFunction` type alias
    - Files to modify: `IRISVOICE/hooks/useIRISWebSocket.ts`
    - _Requirements: 4.1, 4.2_
    - 
    - Add after line ~700 (after sendMessage definition):
    ```typescript
    // Export type for components that receive sendMessage as prop
    export type SendMessageFunction = (
      type: string,
      payload?: Record<string, unknown>
    ) => boolean;
    ```

- [ ] 2. Fix ChatWing Component
  - [ ] 2.1 Update ChatWingProps interface
    - What to build: Import and use SendMessageFunction type
    - Files to modify: `IRISVOICE/components/chat-view.tsx`
    - _Requirements: 1.1, 4.3_
    - 
    - Change line 20 from:
    ```typescript
    sendMessage?: (message: any) => void
    ```
    - To:
    ```typescript
    sendMessage?: SendMessageFunction
    ```
    - Add import at top:
    ```typescript
    import { SendMessageFunction } from "@/hooks/useIRISWebSocket";
    ```

  - [ ] 2.2 Fix sendMessage call site
    - What to build: Change object argument to separate type and payload arguments
    - Files to modify: `IRISVOICE/components/chat-view.tsx`
    - _Requirements: 1.2, 1.3, 3.1, 3.2_
    - 
    - Replace lines 112-120:
    ```typescript
    // Before (INCORRECT):
    if (sendMessage) {
      sendMessage({
        source: "chat_view",
        type: "text_message",
        payload: {
          text: userMessage.text
        }
      })
    }
    
    // After (CORRECT):
    sendMessage?.("text_message", { text: userMessage.text })
    ```

- [ ] 3. Fix DashboardWing Component
  - [ ] 3.1 Update DashboardWingProps interface
    - What to build: Import and use SendMessageFunction type
    - Files to modify: `IRISVOICE/components/dashboard-wing.tsx`
    - _Requirements: 2.1, 2.2, 4.3_
    - 
    - Change line 12 from:
    ```typescript
    sendMessage?: (message: any) => void
    ```
    - To:
    ```typescript
    sendMessage?: SendMessageFunction
    ```
    - Add import at top:
    ```typescript
    import { SendMessageFunction } from "@/hooks/useIRISWebSocket";
    ```

- [ ] 4. Verification and Testing
  - [ ] 4.1 Run TypeScript compilation check
    - What to build: Verify no type errors
    - Run: `cd IRISVOICE && npx tsc --noEmit`
    - _Requirements: 3.3_
    - 
    - Expected: No errors related to sendMessage types

  - [ ] 4.2 Run frontend test suite
    - What to build: Ensure no tests broken by type changes
    - Run: `cd IRISVOICE && npm test -- --passWithNoTests`
    - _Requirements: 3.1, 3.2_
    - 
    - Expected: All tests pass

  - [ ] 4.3 Verify sendMessage usages
    - What to build: Search for any remaining incorrect usages
    - Run: `grep -r "sendMessage({" IRISVOICE/components --include="*.tsx"`
    - _Requirements: 3.1_
    - 
    - Expected: No matches found (or only matches in other contexts)

---

## Summary

### Requirements Coverage

| Requirement | Criteria | Task |
|-------------|----------|------|
| Req 1.1 | ChatWing sendMessage prop type | Task 2.1 |
| Req 1.2 | ChatWing correct call pattern | Task 2.2 |
| Req 1.3 | Refactor object to separate args | Task 2.2 |
| Req 2.1 | DashboardWing sendMessage prop type | Task 3.1 |
| Req 2.2 | Match useIRISWebSocket signature | Task 3.1 |
| Req 3.1 | All call sites use correct pattern | Tasks 2.2, 4.3 |
| Req 3.2 | Chat message sends correctly | Task 2.2 |
| Req 3.3 | TypeScript compilation passes | Task 4.1 |
| Req 4.1 | Export SendMessageFunction type | Task 1.1 |
| Req 4.2 | Reusable type definition | Task 1.1 |
| Req 4.3 | Components use exported type | Tasks 2.1, 3.1 |

### Files Modified

1. `IRISVOICE/hooks/useIRISWebSocket.ts` - Add type export
2. `IRISVOICE/components/chat-view.tsx` - Fix prop type and call site
3. `IRISVOICE/components/dashboard-wing.tsx` - Fix prop type

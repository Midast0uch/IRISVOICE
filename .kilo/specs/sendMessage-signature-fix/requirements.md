# Requirements: sendMessage Signature Fix

## Introduction

This spec addresses TypeScript interface mismatches for the `sendMessage` function prop in React components. The `sendMessage` function from `useIRISWebSocket` hook has a specific signature `(type: string, payload: Record<string, unknown>) => boolean`, but several components define incorrect prop types that don't match this signature. This causes TypeScript compilation issues and potential runtime bugs where messages are malformed before being sent to the WebSocket.

## Requirements

### Requirement 1: Fix ChatWing sendMessage Prop Type

**User Story:** As a developer, I want the ChatWing component's sendMessage prop to match the actual function signature from useIRISWebSocket, so that TypeScript can catch type errors and the component can send messages correctly.

#### Acceptance Criteria

1. WHEN the `ChatWingProps` interface is defined THE SYSTEM SHALL declare `sendMessage` with signature `(type: string, payload?: Record<string, unknown>) => boolean`
2. WHEN `sendMessage` is called in `ChatWing` THE SYSTEM SHALL pass the message type as the first argument and payload as the second argument
3. IF `sendMessage` is called with an object containing `source`, `type`, and `payload` properties THE SYSTEM SHALL be refactored to use the correct two-argument pattern

### Requirement 2: Fix DashboardWing sendMessage Prop Type

**User Story:** As a developer, I want the DashboardWing component's sendMessage prop to match the actual function signature, so that future developers can use it correctly without type mismatches.

#### Acceptance Criteria

1. WHEN the `DashboardWingProps` interface is defined THE SYSTEM SHALL declare `sendMessage` with signature `(type: string, payload?: Record<string, unknown>) => boolean`
2. THE SYSTEM SHALL ensure the prop type matches the signature from useIRISWebSocket for consistency

### Requirement 3: Verify All sendMessage Call Sites

**User Story:** As a developer, I want all sendMessage call sites to use the correct signature, so that WebSocket messages are properly formatted when sent to the backend.

#### Acceptance Criteria

1. WHEN any component calls `sendMessage` THE SYSTEM SHALL use the pattern `sendMessage(type, payload)` not `sendMessage({type, payload})`
2. WHEN the chat message is sent from `ChatWing` THE SYSTEM SHALL send `sendMessage("text_message", { text: userMessage.text })`
3. THE SYSTEM SHALL pass TypeScript compilation without type errors related to sendMessage signatures

### Requirement 4: Consistent sendMessage Type Definition

**User Story:** As a developer, I want a single source of truth for the sendMessage type definition, so that all components can import and reuse it.

#### Acceptance Criteria

1. THE SYSTEM SHALL export a reusable `SendMessageFunction` type from a central location (hooks/useIRISWebSocket.ts or types/index.ts)
2. WHEN components need the sendMessage prop type THE SYSTEM SHALL use the exported type instead of redefining it
3. THE SYSTEM SHALL ensure all sendMessage prop definitions are consistent across the codebase

## References

- `useIRISWebSocket.ts` line 693: `const sendMessage = useCallback((type: string, payload: Record<string, unknown> = {}) => {...}`
- `chat-view.tsx` line 20: Incorrect prop type `sendMessage?: (message: any) => void`
- `dashboard-wing.tsx` line 12: Incorrect prop type `sendMessage?: (message: any) => void`
- `chat-view.tsx` lines 113-119: Incorrect usage passing object instead of separate arguments

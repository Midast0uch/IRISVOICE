# Requirements: Backend SQLite Conversation Store (replacing localStorage)

## Decisions Locked

- **PACMAN memory pipeline unaffected**: PACMAN operates on the backend episodic store independently of how the frontend stores conversations. The SQLite migration changes only the frontend-to-conversation-store path. PACMAN's `pacman_fragment` / `pacman_recall` actions are not modified.
- **Backend is source of truth**: All conversation CRUD goes through the existing REST endpoints (`GET /api/conversations`, `POST /api/conversations`, etc.). Frontend React state is a read-through cache of the server.
- **Documents stay in frontend Conversation.documents**: `DocRender[]` is a frontend-only concern (per-conversation document isolation, Wave 1). Documents are NOT stored in conversation_store.py — they come via WS `document:render` events. This is unchanged.
- **No offline support**: If the backend is unreachable, conversations are not available. This is acceptable for the widget use case where the backend runs locally.
- **localStorage removed for conversations**: `iris_conversations_v1` and `iris_active_conversation_id_v1` are no longer written or read. Other localStorage keys (theme, nav, field values) are untouched.
- **Existing REST endpoints are used as-is**: No new backend endpoints are needed. The existing `GET /api/conversations`, `POST /api/conversations`, `GET /api/conversations/{id}`, `POST /api/conversations/{id}/messages`, `DELETE /api/conversations/{id}`, `PATCH /api/conversations/{id}` handle the full CRUD lifecycle.

## Introduction

The IRIS Voice widget currently stores conversations in `localStorage` with React state as the working copy. This creates race conditions (desync between `activeConversationId` and `conversations` array), ~5MB size limits, no cross-tab safety, and silent data corruption under storage pressure. The backend already has a production-ready SQLite conversation store (`conversation_store.py`) with full REST endpoints (`main.py:1892-2047`). This migration replaces the localStorage path with the backend SQLite path, eliminating the desync bug and providing durable, consistent conversation storage.

### Success criteria

- Conversations survive page reload (fetched from backend, not localStorage)
- No `iris_conversations_v1` or `iris_active_conversation_id_v1` localStorage reads/writes for conversation data
- New conversations get server-assigned IDs from `POST /api/conversations`
- Messages are appended via `POST /api/conversations/{id}/messages` when the REST /api/chat response arrives
- Cross-thread document isolation (Wave 1) continues to work unchanged
- PACMAN memory pipeline unaffected

## Requirements

### REQ-1: Load conversations from backend on app mount
**User Story:** As a user I want my conversations to appear when I open the app so that I can continue where I left off.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL fetch conversations from `GET /api/conversations` when `chat-view.tsx` mounts.
- AC2: THE SYSTEM SHALL convert each backend conversation record to the frontend `Conversation` interface (`id`, `title`, `preview`, `messages`, `documents`, `timestamp`, `isPinned`, `lastMessagePreview`).
- AC3: THE SYSTEM SHALL restore `activeConversationId` from the fetched conversations (most recent non-pinned, or last-used tracked by the frontend).
- AC4: WHEN the backend is unreachable THEN THE SYSTEM SHALL show an empty conversation list (not crash).

**Edge Cases:**
- Backend returns empty list → show "No conversations yet"
- Backend returns 500 → show empty list, log warning
- Backend connection timeout → show empty list, log warning
- Conversation has messages but some fields missing → apply defaults, don't crash

### REQ-2: Create conversations via backend API
**User Story:** As a user I want new conversations to be recorded server-side so that they persist across page reloads.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: WHEN the user sends a first message THEN THE SYSTEM SHALL call `POST /api/conversations` with `{title, preview, messages: [{role: "user", text, ...}]}` to create a server-backed conversation.
- AC2: WHEN `POST /api/conversations` succeeds THEN THE SYSTEM SHALL use the server-returned `id` as the canonical conversation ID for all subsequent operations.
- AC3: IF `POST /api/conversations` fails THEN THE SYSTEM SHALL fall back to a local conversation (not persisted) so the user can still chat.

**Edge Cases:**
- User messages before the POST response arrives → queue until server ID is assigned
- Rapid concurrent conversation creation → each gets a unique server ID

### REQ-3: Persist ALL messages (user + assistant) to backend
**User Story:** As a user I want the full conversation thread (both my questions and the assistant's answers) to survive page reload so I can pick up where I left off.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: WHEN the user sends a follow-up message in an existing conversation THEN THE SYSTEM SHALL call `POST /api/conversations/{id}/messages` with `{role: "user", text}` to persist the question.
- AC2: WHEN the REST `/api/chat` response arrives THEN THE SYSTEM SHALL call `POST /api/conversations/{id}/messages` with `{role: "assistant", text, thinking, turn_id}` to persist the response.
- AC3: WHEN a tool-call document is rendered THEN THE SYSTEM SHALL NOT duplicate it into the message store (documents stay in frontend Conversation.documents, per REQ-7).
- AC4: IF the append fails THEN THE SYSTEM SHALL still show the message in the UI (optimistic — never block the user).
- AC5: THE SYSTEM SHALL call `PATCH /api/conversations/{id}` to update `preview` and `lastMessagePreview` after each turn.

**Edge Cases:**
- Append request fails (network error) → message shown in UI, not persisted until next fetch
- Duplicate append (retry) → server should deduplicate by turn_id or client message id

### REQ-4: Delete conversations via backend API
**User Story:** As a user I want to delete conversations and have that removal persist.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: WHEN the user deletes a conversation THEN THE SYSTEM SHALL call `DELETE /api/conversations/{id}`.
- AC2: IF `DELETE` succeeds THEN THE SYSTEM SHALL remove the conversation from frontend state.
- AC3: IF `DELETE` fails THEN THE SYSTEM SHALL keep the conversation in state and show a warning.
- AC4: THE SYSTEM SHALL also call `DELETE /api/conversations/{id}` when the WS `delete_conversation` event is received (cross-tab sync).

**Edge Cases:**
- Rapid delete of same conversation → second 404 is handled (ignore)

### REQ-5: Remove localStorage conversation persistence
**User Story:** As a developer I want to eliminate the localStorage-based conversation storage to prevent data races and corruption.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL NOT read `iris_conversations_v1` from localStorage on mount (remove from initial state).
- AC2: THE SYSTEM SHALL NOT write `iris_conversations_v1` to localStorage on conversation change (remove the debounced persist `useEffect` at `chat-view.tsx:238`).
- AC3: THE SYSTEM SHALL NOT read or write `iris_active_conversation_id_v1` from localStorage (remove the persist `useEffect` at `chat-view.tsx:254`).
- AC4: THE SYSTEM SHALL keep `activeConversationId` in React state only (no localStorage sync).

**Edge Cases:**
- Old localStorage keys still present → ignored, no migration needed (decaying data is harmless)
- User opens app with empty localStorage → conversations load from backend (or empty)

### REQ-6: Handle conversation API errors gracefully
**User Story:** As a user I want the app to keep working even if the conversation API has transient failures.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: IF the initial `GET /api/conversations` fails THEN THE SYSTEM SHALL start with an empty conversation list and retry on WS reconnect.
- AC2: WHEN a conversation create/append/delete fails THEN THE SYSTEM SHALL log the error and continue without blocking the UI.
- AC3: THE SYSTEM SHALL retry failed mutations when the WebSocket reconnects (if the conversation store is still unfinished).

### REQ-7: Preserve document isolation per-conversation (Wave 1 contract)
**User Story:** As a user I want documents from websearch to render in the correct conversation thread.

**Verified:** `chat-view.tsx:2000-2050` — `handleDocumentRender` scoped by `activeConversationIdRef.current`

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL continue using the `Conversation.documents` array for rendered documents (not moved to backend).
- AC2: THE SYSTEM SHALL continue filtering `document:render` WS events by `activeConversationIdRef.current`.
- AC3: WHEN conversations are fetched from the backend THEN THE SYSTEM SHALL initialize each conversation's `documents` array as empty (documents re-populate on WS events).

**Edge Cases:**
- Documents rendered before conversation is loaded from backend → queued and applied after conversation appears

### REQ-8: Rehydrate documents via existing WS path on load
**User Story:** As a user I want rendered websearch documents (MARKDOWN/TABLE cards) to re-appear after page reload so I don't lose the context.

**Verified:** RELIES ON EXISTING — `chat-view.tsx:602-649` (`hydrateDocuments` → WS `get_documents` → `iris:documents`). No new endpoint needed.

**Acceptance Criteria:**
- AC1: WHEN the WS `iris:sync_state_ack` event fires after page load THEN THE SYSTEM SHALL call the existing `hydrateDocuments()` function to re-fetch documents for the active conversation.
- AC2: THE SYSTEM SHALL populate `Conversation.documents[]` from the WS `iris:documents` response (same path used on WS reconnect and conversation switch).
- AC3: THE SYSTEM SHALL continue handling live WS `document:render` events (documents arriving from the DER loop are appended to `Conversation.documents`).
- AC4: IF `sync_state_ack` fires BEFORE conversations are loaded from the backend THEN THE SYSTEM SHALL queue the document fetch until conversations are available (or retry on conversation switch).

**Edge Cases:**
- `sync_state_ack` fires but `activeConversationId` is null (no conversation selected) → document fetch is a no-op (no active conversation to hydrate)
- WS `iris:documents` returns empty → `documents` array is empty, no error
- WS `iris:documents` returns unknown format → frontend treats it as plain text placeholder

### REQ-9: Preserve PACMAN memory pipeline
**User Story:** As the system I want the PACMAN fragmentation/recall pipeline to continue working unchanged.

**Verified:** `backend/mcp/` — PACMAN operates on episodic store, independent of conversation_store.py

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL NOT modify `pacman_fragment` or `pacman_recall` actions.
- AC2: THE SYSTEM SHALL NOT modify the episodic store or memory database.
- AC3: THE SYSTEM SHALL continue calling PACMAN actions from the backend MCP server unchanged.

### REQ-11: Truncate/rollback conversation to a specific turn
**User Story:** As a user I want to rollback a conversation to a specific point so I can correct the agent's direction when it goes off track.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL expose a `POST /api/conversations/{id}/truncate` endpoint accepting `{keep_until_message_id}`.
- AC2: WHEN the endpoint is called THEN THE SYSTEM SHALL delete all messages in the conversation with IDs after the specified message.
- AC3: THE SYSTEM SHALL update the conversation's `updated_at` timestamp after truncation.
- AC4: THE SYSTEM SHALL show a "revert" button on each assistant message in the frontend conversation thread.
- AC5: WHEN the revert button is clicked THEN THE SYSTEM SHALL call the truncate endpoint and remove all subsequent messages from React state.
- AC6: IF the API call fails THEN THE SYSTEM SHALL keep the current state and show a warning (optimistic but revertible).
- AC7: WHEN the last assistant message is reverted THEN THE SYSTEM SHALL enable the user to send a new message (the previous user prompt is preserved as the last message).

**Edge Cases:**
- Truncating at message 0 → deletes all messages (clears conversation)
- Truncating at the last message → no-op (nothing to delete)
- Conversation ID not found → return 404
- Truncate called on local-only conversation → ignore API call, update state locally

### REQ-12: Retry prompt on error message
**User Story:** As a user I want to retry a failed response so I don't have to re-type my prompt.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL show a "retry" button on assistant messages that have an error state.
- AC2: WHEN the retry button is clicked THEN THE SYSTEM SHALL re-send the last user message to `POST /api/chat` with the same `thread_id`.
- AC3: THE SYSTEM SHALL delete the error response from the conversation (frontend only — the backend truncate is NOT called on retry; the new response replaces the error message in React state).
- AC4: THE SYSTEM SHALL collapse both the user prompt and the error response into a loading state showing "Retrying..."
- AC5: IF the retry succeeds THEN THE SYSTEM SHALL replace the error with the new response.
- AC6: IF the retry fails again THEN THE SYSTEM SHALL keep the original error message and show a "still failing" indicator.

**Edge Cases:**
- Retry when the last user message was already re-sent recently (<500ms) → debounce/ignore
- Retry on a conversation that was deleted → no-op
- Retry while another request is in flight → queue

### REQ-10: Add observability for conversation API calls
**User Story:** As the tuner I want logged conversation API call timing so I can diagnose slow loads.

**Verified:** NEW (unverified — implementation pending)

**Acceptance Criteria:**
- AC1: THE SYSTEM SHALL log timestamped, conversation-scoped entries for `GET /api/conversations`, `POST /api/conversations`, `POST /api/conversations/{id}/messages`, `DELETE /api/conversations/{id}` calls with timing_ms.

**Edge Cases:**
- High-frequency calls (rapid sends) → coalesce logging, never block

## Non-Requirements (Out of Scope)

- Offline support: conversations are only available when the backend is reachable
- Cross-tab sync: not addressed (existing behavior preserved)
- Message search: no client-side search index
- Document variant history: only the latest variant per document is stored (overwritten on re-render)
- Migration of old localStorage conversations to SQLite: decaying data ignored
- Encrypted conversations: not in scope
- Migration of old localStorage conversations to SQLite: decaying data ignored
- PACMAN memory pipeline modifications: out of scope

## Open Questions

- None — all decisions locked above.

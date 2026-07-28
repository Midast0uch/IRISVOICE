# Tasks: Backend SQLite Conversation Store (replacing localStorage)

> Each task links to a requirement (REQ-x). Grouped into waves for parallel execution.

## Wave 1 — Core Migration (Frontend)

- [ ] T1 (REQ-1): **Replace conversation initialization with `GET /api/conversations`** — `components/chat-view.tsx`
  - Replace the localStorage init at lines 196-213 with a `fetchConversations()` call in a `useEffect` on mount.
  - Map backend conversation dict to frontend `Conversation` interface (id, title, messages, isPinned, timestamp).
  - Set `activeConversationId` to the most recent non-pinned conversation's ID.
  - On fetch failure, initialize to empty array (no conversations) and log warning.
  - RIPPLE: must happen BEFORE existing state-dependent effects (message listener, WS handlers).

- [ ] T2 (REQ-2): **Create conversation via `POST /api/conversations` on first message** — `components/chat-view.tsx`
  - In `handleSendMessage`, replace `const newConv = { id: Date.now().toString(), ... }` with a `POST /api/conversations` call.
  - Call signature: `POST /api/conversations { title, messages: [{role: "user", text, timestamp}] }`.
  - Use the returned `id` as the canonical conversation ID for `activeConversationId` and all subsequent operations.
  - Store a loading/placeholder state while the POST is in flight.
  - IF `POST /api/conversations` fails, create a local-only conversation with `id: "local-{timestamp}"` as fallback.
  - RIPPLE: REST `/api/chat` call at line 1105 must use the server ID (not stale `activeConversationId`).

- [ ] T3 (REQ-3): **Persist assistant responses via `POST /api/conversations/{id}/messages`** — `components/chat-view.tsx`
  - In the REST `/api/chat` response handler (lines 1140-1190), after updating React state, call `POST /api/conversations/{convId}/messages` with `{role: "assistant", text, thinking, turn_id}`.
  - Also call `PATCH /api/conversations/{convId}` to update `preview` and title after each turn.
  - Be optimistic: update UI immediately, log API failures but don't block the user.
  - RIPPLE: The third `prev.find()` fallback for orphan responses is no longer needed (the conversation is always found by canonical ID).

- [ ] T4 (REQ-3): **Persist follow-up user messages to backend** — `components/chat-view.tsx`
  - In `handleSendMessage`, when the user sends a message in an EXISTING conversation, call `POST /api/conversations/{id}/messages {role: "user", text}` after updating React state.
  - Do NOT call for the first message (it's already sent in `POST /api/conversations` create).
  - Be optimistic: update UI immediately, log failures but don't block.
  - RIPPLE: Both user and assistant messages are now persisted for EVERY turn.

- [ ] T5 (REQ-8): **Verify document rehydration via existing WS path** — `components/chat-view.tsx`
  - Verify that `hydrateDocuments()` (WS `get_documents` → `iris:documents`, line 602-649) fires correctly on page load after conversations are fetched.
  - The existing path fires on `sync_state_ack` and conversation switch — no new code needed.
  - IF `sync_state_ack` fires before `activeConversationId` is set: queue the hydration until conversations load.
  - Test: load page → verify `iris:documents` events fire → verify documents populate.
  - RIPPLE: No backend changes. Only frontend timing guard if needed.

- [ ] T6 (REQ-4): **Wire delete conversation to `DELETE /api/conversations/{id}`** — `components/chat-view.tsx`
  - Replace the current delete handler (which only removes from React state) with a call to `DELETE /api/conversations/{id}`.
  - On success, remove from React state.
  - On failure, keep in state and show a console warning (or toast).
  - RIPPLE: WS `delete_conversation` event handler must also call the API.

- [ ] T7 (REQ-5): **Remove localStorage conversation persistence effects** — `components/chat-view.tsx`
  - Remove the debounced persist `useEffect` at line 238 that writes `iris_conversations_v1`.
  - Remove the persist `useEffect` at line 254 that writes `iris_active_conversation_id_v1`.
  - Remove the initial localStorage read at lines 196-214 for both keys.
  - Keep `activeConversationId` in React state only — no localStorage sync.
  - RIPPLE: `STORAGE_KEY` and `ACTIVE_ID_KEY` constants become unused — remove them.

## Wave 1b — Revert & Retry UI

- [ ] T8 (REQ-11): **Add `truncate_conversation()` to conversation_store.py** — `backend/conversation_store.py`
  - Add method `truncate_conversation(conversation_id, keep_until_message_id: str) -> dict`.
  - Deletes all messages with `id > keep_until_message_id` for the given conversation.
  - Uses SQL `DELETE FROM messages WHERE conversation_id = ? AND id > ?`.
  - Returns `{truncated: True, kept_messages: N}`.
  - RIPPLE: Must handle non-existent conversation_id (return empty). Must handle message_id not found in conversation (return 404).

- [ ] T9 (REQ-11): **Add `POST /api/conversations/{id}/truncate` endpoint** — `backend/main.py`
  - New route calling `truncate_conversation(id, request.keep_until_message_id)`.
  - Returns `{truncated: true, kept_messages: N}` on success, 404 on invalid id.
  - RIPPLE: Add contract test CT-6 for the truncate endpoint shape.

- [ ] T10 (REQ-11): **Add revert button to assistant message action bar** — `components/chat-view.tsx`
  - Add a `RotateCcw` (or `Undo2`) icon button in the feedback action bar (lines 2650-2693).
  - Placement: after the TTS `<Volume2>` button (line 2667), before the `ml-auto` spacer (line 2669).
  - On click: call `handleRevertMessage(messageIndex)`.
  - `handleRevertMessage`:
    1. If conversation ID is not local: `POST /api/conversations/{id}/truncate` with `keep_until_message_id`.
    2. On success: strip all messages after `messageIndex` from React state.
    3. On failure: show warning, keep state unchanged.
    4. For local-only conversations: just update React state (no API call).
  - RIPPLE: Must update `Conversation.messages` via `setConversations`. Must clear documents that were associated with reverted turns.

- [ ] T11 (REQ-12): **Add retry button to error messages** — `components/chat-view.tsx`
  - Add a `RefreshCw` icon button in the error message block (lines 2715-2733), after the error text.
  - On click: call `handleRetryPrompt(errorMessageIndex)`.
  - `handleRetryPrompt`:
    1. Find the last user message before the error message.
    2. Remove the error message from React state.
    3. Show a loading state "Retrying..." in its place.
    4. Call `POST /api/chat` with `{text: lastUserMessage.text, thread_id}`.
    5. On success: replace loading state with new assistant response.
    6. On failure: restore original error message.
  - RIPPLE: Must debounce to prevent rapid retries (<500ms). Must handle the case where the last user message was already deleted.

## Wave 2 — Error Handling & Resilience

- [ ] T12 (REQ-6): **Network error handling for conversation API calls** — `components/chat-view.tsx`
  - Add a shared `callConversationApi(call, fallback)` helper wrapping all API calls with try/catch + logging.
  - Handle three cases: `GET` (fallback to empty), `POST` (fallback to local-only), `DELETE`/append (keep in state + warn).
  - RIPPLE: `setLocalTyping(false)` must still run even if API calls fail.

## Wave 3 — Verification

- [ ] T13 (REQ-1 through REQ-8): **Contract tests for conversation API shapes** — `tests/contract/test_conversation_api.py`
  - Assert `GET /api/conversations` returns `{conversations: [...]}` with expected fields.
  - Assert `POST /api/conversations` returns a conversation dict with `id`, `title`, `created_at`, `messages`.
  - Assert `POST /api/conversations/{id}/messages` returns a message dict.
  - Assert `DELETE /api/conversations/{id}` returns `{deleted: bool}`.
  - RIPPLE: Must pass BEFORE frontend changes to establish baseline.

- [ ] T14 (REQ-1 through REQ-12): **Behavioral tests — full loop** — Live testing via Playwright/CDP
  - B1: Open app → verify conversations load from backend → send message → reload → verify conversation persists.
  - B2: Send message in conversation A → create B → verify B has no documents from A (cross-thread isolation).
  - B3: Delete conversation → reload → verify gone.
  - B4: Kill backend → verify empty list → restart → verify conversations reappear.
  - B5: Run websearch → verify documents rendered → reload → verify documents re-appear via WS rehydration.

- [ ] T15 (CT-1 through CT-6): **Contract tests for unchanged interfaces** — `tests/contract/`
  - CT-1: PACMAN action shapes (`pacman_fragment`, `pacman_recall`) — signatures unchanged.
  - CT-2: WS `document:render` event shape — payload fields unchanged.
  - CT-3: REST `/api/chat` request/response shape — `{text, thread_id}` → `{content, turn_id, thread_id}`.
  - CT-4: Existing conversation REST endpoint shapes (baseline for T9).
  - RIPPLE: These are CONTRACT LOCKS. Must pass before AND after migration.

## Dependency / parallelization notes

- **W1 (T1-T7) must run sequentially** — each task depends on the previous one (init → create → append → rehydrate → delete → cleanup).
- **W1b (T8-T11) depends on W1** — revert/retry UI builds on the backend conversation store from W1. T8 (backend truncate) can run in parallel with T10-T11 (frontend UI) since they touch different files.
- **W2 (T12) depends on W1** — error handling wraps the API calls.
- **W3 (T13-T15) can run parallel with W1** — contract tests verify the existing backend. Run T13 before W1 to establish baseline. Run T15 to pin contract locks (including CT-6 for the new truncate endpoint).
- **`GET /api/conversations`** returns conversations WITH messages. No separate `loadConversation()` call needed on mount.
- **`POST /api/conversations`** takes `{title, messages}` — the frontend sends the user message in the create call. No separate `add_message` for the first turn.
- **Debounce removal**: The existing 1s debounced localStorage write at line 238 is eliminated — messages persist immediately on API success.

## Intentionally omitted from tasks (CONTRACT LOCKS — no code changes)

- **REQ-7** (document isolation per-conversation): Already implemented in Wave 1. WS `document:render` handler (`chat-view.tsx:2000-2050`) correctly scoped by `activeConversationIdRef.current`. No change needed.
- **REQ-9** (PACMAN pipeline): PACMAN operates on episodic store, independent of conversation_store.py. No change needed.
- **REQ-10** (observability): Covered by T12's error logging. Each API call logs timing_ms for diagnosis.

## NO-CHANGE areas (verified — need only contract tests)

| Area | Classification | Contract test |
|---|---|---|
| `backend/main.py` conversation endpoints | NO CHANGE (verified) | CT-4 (T11) |
| `backend/conversation_store.py` | NO CHANGE (verified) | CT-4 (T11) |
| PACMAN actions | CONTRACT LOCK | CT-1 (T11) |
| WS `document:render` | CONTRACT LOCK | CT-2 (T11) |
| REST `/api/chat` | CONTRACT LOCK | CT-3 (T11) |
| `backend/api/chat.py` (Immortus) | NO CHANGE (verified) | — |
| `backend/agent/immortus/` | NO CHANGE (verified) | — |

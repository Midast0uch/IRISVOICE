# Design: Backend SQLite Conversation Store (replacing localStorage)

## Context

The IRIS Voice widget currently stores conversations in `localStorage` (`iris_conversations_v1`, `iris_active_conversation_id_v1`). This has caused a persistent desync bug: `activeConversationId` captures a stale React state value (old server thread_id from a previous session) when `handleSendMessage` reads it, so the REST `/api/chat` response handler cannot find the conversation to update. The result: the user's prompt appears to vanish — the conversation is created in React state but the response is never appended.

The backend already ships a full conversation store: `backend/conversation_store.py` persists conversations + messages in SQLite (`data/conversations.db`) with WAL mode, and `backend/main.py` exposes seven REST endpoints (six existing + new `POST /api/conversations/{id}/truncate`) (`GET/POST /api/conversations`, `GET /api/conversations/{id}`, `POST /api/conversations/{id}/messages`, `DELETE /api/conversations/{id}`, `PATCH /api/conversations/{id}`). Document rehydration uses the existing WS `get_documents` → `iris:documents` path (`chat-view.tsx:602-649`), not a new REST endpoint.

This migration eliminates the bug at its root: the frontend reads/writes conversations through the backend API instead of localStorage. The server-assigned conversation ID is the canonical ID from the start, eliminating the local-ID-to-server-ID mismatch.

**PACMAN pipeline is unaffected.** PACMAN (`pacman_fragment` / `pacman_recall`) operates on the episodic store backend, independent of `conversation_store.py`. No PACMAN code is touched.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                              │
│                                                                      │
│  ┌─────────────────────┐     ┌──────────────────────────────────┐   │
│  │ chat-view.tsx        │     │  ConversationState               │   │
│  │  ┌─────────────────┐ │     │  ┌────────────────────────────┐ │   │
│  │  │ handleSendMessage│ │─────│  │ conversations: Conversation[]│ │   │
│  │  │ handleDelete     │ │     │  │ activeConversationId: str  │ │   │
│  │  │ handleApiError   │ │     │  └────────────────────────────┘ │   │
│  │  └─────────────────┘ │     └──────────────────────────────────┘   │
│  └──────────┬───────────┘                                            │
│             │ REST calls                     No localStorage          │
└─────────────┼────────────────────────────────────────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        Backend (FastAPI)                             │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ main.py                                                     │    │
│  │  GET    /api/conversations           → get_conversations()   │    │
│  │  POST   /api/conversations           → create_conversation() │    │
│  │  GET    /api/conversations/{id}      → get_conversation(id)  │    │
│  │  POST   /api/conversations/{id}/messages → add_message(...)  │    │
 │  │  DELETE /api/conversations/{id}      → delete_conversation() │    │
 │  │  PATCH  /api/conversations/{id}      → update_title/pin      │    │
 │  │  POST  /api/conversations/{id}/truncate → truncate(id, msgId)│    │
│  └─────────────────────────────────────────────────────────────┘    │
│                           │                                          │
│                           ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ conversation_store.py (SQLite)                              │    │
│  │  Path: data/conversations.db                                │    │
│  │  Mode: WAL (concurrent-safe)                                │    │
│  │  Tables: conversations(id, title, created_at, updated_at,  │    │
│  │          pinned), messages(id, conversation_id, role, text, │    │
│  │          turn_id, thinking, timestamp)                      │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                           │                                          │
│                           ▼                                          │
│  ┌─────────────────────────────────────────────────────────────┐    │
│   │  ┌─────────────────────────────────────────────────────────────┐    │
 │  │  PACMAN pipeline (UNCHANGED)    │
│  │  pacman_fragment / pacman_recall / EpisodicStore             │    │
│  │  Independent of conversation_store.py — no code changes     │    │
│  └─────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

## Sequence / Data Flow

### Load conversations on app mount

```
chat-view.tsx                        Backend (FastAPI)
     │                                     │
     │  GET /api/conversations              │
     │─────────────────────────────────────>│
     │                                     │
     │  {conversations: [                   │
     │    {id, title, created_at,           │
     │     updated_at, pinned,              │
     │     messages: [{id, role, text,      │
     │       turn_id, thinking, timestamp}] │
     │    }]                                │
     │<─────────────────────────────────────│
     │                                     │
     │  Convert to frontend Conversation[]  │
     │  Set activeConversationId            │
     │  (most recent non-pinned)            │
```

### Rehydrate documents via existing WS path (REQ-8)

Uses the existing `hydrateDocuments()` → WS `get_documents` → `iris:documents` pipeline
at `chat-view.tsx:602-649`. No new backend endpoint.

```
chat-view.tsx                        Backend (FastAPI)
     │                                     │
     │  GET /api/conversations              │
     │─────────────────────────────────────>│
     │  {conversations: [...]}              │
     │<─────────────────────────────────────│
     │                                     │
     │  ... WS connects, sync_state_ack     │
     │                                     │
     │  WS: get_documents                   │
     │  {conversation_id: "conv_xxx"}       │
     │─────────────────────────────────────>│
     │  WS: iris:documents                  │
     │  {documents: [{id, format,           │
     │    content, sources, trust}]}        │
     │<─────────────────────────────────────│
     │                                     │
     │  hydrateDocuments merges into        │
     │  Conversation.documents[]            │
```

### Send message (new conversation)

```
chat-view.tsx                        Backend (FastAPI)
     │                                     │
     │  POST /api/conversations             │
     │  {title: "Conversation 1",           │
     │   preview: "websearch ...",          │
     │   messages: [{role: "user",          │
     │     text: "websearch ..."}]}         │
     │─────────────────────────────────────>│
     │                                     │
     │  {id: "conv_xxx",                    │
     │   title: "Conversation 1",           │
     │   created_at: "...",                 │
     │   updated_at: "...",                 │
     │   pinned: false,                     │
     │   messages: [{...}]}                 │
     │<─────────────────────────────────────│
     │                                     │
     │  Use conv_xxx as canonical ID        │
     │  POST /api/chat                     │
     │  {text: "...",                      │
     │   thread_id: "conv_xxx"}            │
     │─────────────────────────────────────>│
     │         ... DER processes ...         │
     │  {content: "...",                    │
     │   thread_id: "conv_xxx",            │
     │   turn_id: "..."}                   │
     │<─────────────────────────────────────│
     │                                     │
     │  POST /api/conversations/conv_xxx/   │
     │       messages                       │
     │  {role: "assistant",                 │
     │   text: "...",                       │
     │   thinking: "..."}                   │
     │─────────────────────────────────────>│
     │                                     │
     │  PATCH /api/conversations/conv_xxx   │
     │  {preview: "..."}                    │
     │─────────────────────────────────────>│
```

### Truncate/rollback conversation (REQ-11)

```
chat-view.tsx                        Backend (FastAPI)
     │                                     │
     │  User clicks "revert" on msg N      │
     │                                     │
     │  POST /api/conversations/conv_xxx/  │
     │       truncate                      │
     │  {keep_until_message_id: "msg-N"}   │
     │─────────────────────────────────────>│
     │                                     │
     │  DELETE FROM messages                │
     │  WHERE id > "msg-N"                  │
     │  AND conversation_id = "conv_xxx"   │
     │                                     │
     │  {truncated: true,                   │
     │   kept_messages: N}                 │
     │<─────────────────────────────────────│
     │                                     │
     │  Strip messages after msg N         │
     │  from React state                   │
     │  Enable input for new message        │
```

### Delete conversation

```
chat-view.tsx                        Backend (FastAPI)
     │                                     │
     │  DELETE /api/conversations/conv_xxx  │
     │─────────────────────────────────────>│
     │  {deleted: true}                     │
     │<─────────────────────────────────────│
     │  Remove from React state             │
```

## Data Models

### Backend: Conversation (conversation_store.py)

```python
{
    "id": str,           # auto-generated e.g. "conv_1784646532303"
    "title": str,        # user-visible title
    "created_at": str,   # ISO timestamp
    "updated_at": str,   # ISO timestamp
    "pinned": bool,      # pinned to top
    "messages": [        # included in GET /api/conversations/{id} responses
        {
            "id": str,        # e.g. "msg-1"
            "role": str,      # "user" | "assistant" | "error"
            "text": str,      # message content
            "turn_id": str,   # server-assigned turn ID
            "thinking": str,  # LLM thinking/chain-of-thought
            "timestamp": str, # ISO timestamp
        }
    ]
}
```

### Backend: GET /api/conversations response

```python
{
    "conversations": [
        {
            "id": str,
            "title": str,
            "created_at": str,
            "updated_at": str,
            "pinned": bool,
            "messages": [],  # NOT included at list level (only full GET has messages)
            "last_message_text": str,  # preview text
        }
    ]
}
```

Wait — the current `get_conversations()` returns conversations WITH messages included (line 122 in conversation_store.py: `messages: []` is initialized for every conversation). The frontend would need messages with every conversation fetch unless we use `get_conversation(id)` for single conversation access.

### Frontend: Conversation interface

```typescript
interface Conversation {
    id: string;
    title: string;
    preview: string;          // truncated from last user message
    messages: Message[];      // full message thread
    documents: DocRender[];   // frontend-only, per Wave 1
    timestamp: Date;
    isPinned: boolean;
    lastMessagePreview: string; // displayed in sidebar
}
```

### Frontend: Message interface

```typescript
interface Message {
    id: string;
    text: string;
    sender: "user" | "assistant" | "error";
    timestamp: Date;
    thinking?: string;
    turn_id?: string;
}
```

## Key Decisions

| Decision | Rationale |
|---|---|
| **D1: Create conversation before /api/chat** | Creates the server ID before the REST call, so `restThreadId` is always the canonical ID. Eliminates the desync bug at the root. |
| **D2: Pessimistic create, optimistic append** | Conversation creation must succeed before sending to /api/chat. Message appends can be optimistic (show in UI, retry on failure). If create fails, fall back to local-only conversation. |
| **D3: Documents stay frontend-only** | Documents are transient render artifacts from WS `document:render` events. Moving them to the backend would require new endpoints and a DB migration. Out of scope. |
| **D4: No localStorage migration for old conversations** | Old localStorage conversations are decaying data. They are silently ignored. No migration script needed. The only cost is the user loses old chat history, which is acceptable for a development-stage widget. |
| **D5: Load full message threads on fetch** | `GET /api/conversations` returns conversations with messages. For <100 conversations this is fine. If scale becomes an issue, add a `?include_messages=false` flag later. |
| **D6: PACMAN unchanged** | PACMAN operates on the episodic store, not conversation_store.py. Conversation messages are persisted in SQLite independently of PACMAN memory fragments. |

## Ripple-Effect Map (MANDATORY)

Every change touches more than its target module. This map classifies every affected area.

| Area / File | Change? | Classification | Why / Evidence |
|---|---|---|---|---|
| `components/chat-view.tsx` | Yes | CHANGE NEEDED | Frontend conversation lifecycle. Replace localStorage initialization with `GET /api/conversations`. Replace local-ID creation with `POST /api/conversations`. Persist follow-up user messages via `POST /api/conversations/{id}/messages`. Persist assistant responses. Remove localStorage persist effects. Add API error handling. Document rehydration uses existing WS path (already wired at `chat-view.tsx:602-649`). |
| `backend/main.py` (lines 1900-1965) | No | NO CHANGE (verified) | Existing REST endpoints already handle full CRUD. No new endpoints needed. Document rehydration uses existing WS path. Verified at `main.py:1900-1965`. |
| `backend/agent/document_store.py` | No | NO CHANGE (verified) | Already stores documents per conversation. WS `get_documents` handler already returns them. Verified at `document_store.py:78-92`. WS handler at `iris_gateway.py:4351`. |
| `backend/conversation_store.py` | Add `truncate()` | CHANGE NEEDED | New method `truncate_conversation(id, keep_until_msg_id)` in SQLite. Deletes messages with `rowid > keep_until_msg_id` for the conversation. |
| `backend/main.py` (lines 1900-1965) | Add endpoint | CHANGE NEEDED | NEW: `POST /api/conversations/{id}/truncate` endpoint that calls `truncate_conversation()`. Also new: `GET /api/conversations/{id}/last_user_message{?before}` helper for retry. |
| `components/chat-view.tsx` — revert button | Add UI | CHANGE NEEDED | In feedback action bar (`chat-view.tsx:2650-2693`), add "↩ revert" button that calls new truncate API. Must add `handleRevertMessage(messageIndex)` handler. |
| `components/chat-view.tsx` — retry button | Add UI | CHANGE NEEDED | In error message block (`chat-view.tsx:2715-2733`), add "⟳ retry" button that re-sends last user prompt. Must add `handleRetryPrompt()` handler. |
| `components/SidePanel.tsx` | No | NO CHANGE (verified) | SidePanel reads `conversations` via `useTaskProgress` hook — no localStorage access. The conversation list renders from React state. |
| `lib/documentMerge.ts` | No | NO CHANGE (verified) | Pure function, operates on `Conversation.documents` — no localStorage involvement. |
| `hooks/useTaskProgress.ts` | No | NO CHANGE (verified) | Reads conversation from `activeConversation` prop — no localStorage. |
| `PACMAN pipeline` (`backend/mcp/` actions) | No | CONTRACT LOCK | PACMAN operates on episodic store, independent of conversation_store.py. Pin with contract test CT-1. |
| `localStorage` (`iris_conversations_v1`) | Remove usage | CHANGE NEEDED | Remove reads in initial state (`chat-view.tsx:196-213`). Remove writes in debounced persist effects (`chat-view.tsx:238`, `254`). |
| `localStorage` (`iris_active_conversation_id_v1`) | Remove usage | CHANGE NEEDED | Remove from initial state (`chat-view.tsx:214`). Remove persist effect (`chat-view.tsx:254`). |
| `localStorage` (other keys) | No | NO CHANGE (verified) | Theme, nav state, field values, web-mode, brand color — all untouched. Only conversation keys are removed. |
| `frontend/package.json` | No | NO CHANGE (verified) | No new dependencies needed (fetch API is built-in). |
| WS event `document:render` flow | No | CONTRACT LOCK | Documents continue to come via WS, scoped by `activeConversationIdRef.current`. Unchanged. Pin with contract test CT-2. |
| `POST /api/chat` REST flow | No | CONTRACT LOCK | Already uses `thread_id` parameter. Frontend will now send the canonical server ID. Response shape unchanged. Pin with contract test CT-3. |
| `backend/agent/agent_kernel.py` | No | NO CHANGE (verified) | Conversation management is orthogonal to agent processing. Agent only sees `conversation_id` from the REST handler. |
| `backend/api/chat.py` (Immortus chain recording) | No | NO CHANGE (verified) | Immortus thread_id is generated and recorded in `/api/chat` (ChatREST), which is called separately from conversation CRUD. Conversation create/delete in `main.py` do not touch Immortus — and don't need to. Verified: Immortus chain append at `chat.py:441-442`, thread_id generation at `chat.py:507-508`. |
| `backend/agent/immortus/` (entire subsystem) | No | NO CHANGE (verified) | Immortus constants, session management, routing thresholds — all independent of conversation_store.py. No code changes needed. |

## UI Placement

### Revert button (REQ-11)
Placed in the **Feedback action bar** at `chat-view.tsx:2650-2693` (the action toolbar at the bottom of each assistant message bubble):
```
┌─────────────────────────────────────────┐
│  [Copy] [TTS] [↩ Revert]    [👍] [👎]  │
│                          (spacer)        │
└─────────────────────────────────────────┘
```
Location: after the TTS `<Volume2>` button (line 2667), before the `ml-auto` spacer (line 2669). The revert button:
- Truncates all messages after the current message on click.
- Calls `truncateConversation(messageIndex)` which triggers `POST /api/conversations/{id}/truncate`.
- Uses a `RotateCcw` or `Undo2` icon from lucide-react.
- Needs a confirmation tooltip or second-click for safety: "Revert to here?"

### Retry button (REQ-12)
Placed on **error messages** at `chat-view.tsx:2715-2733` (the error message render block):
```
┌─────────────────────────────────────────┐
│  ⚠ Error                                │
│  Failed to generate response            │
│  [⟳ Retry]                              │
└─────────────────────────────────────────┘
```
Location: after the error `<p>` text (line 2732), inside the error `<motion.div>`. The retry button:
- Finds the last user message before this error.
- Calls `retryLastPrompt()` which re-sends it to `POST /api/chat`.
- Replaces the error message with a loading state.
- Remains as-is if the retry fails again.
- Uses a `RefreshCw` icon from lucide-react.

## Error Handling

| Failure Mode | Action |
|---|---|
| `GET /api/conversations` fails (network/500) | Show empty conversation list, log warning. User can still send new messages (fallback to local-only). |
| `POST /api/conversations` fails (network/500) | Create local-only conversation with a `local-{timestamp}` ID. Append messages to it. WS reconnect triggers retry. |
| `POST /api/conversations/{id}/messages` fails | Keep message in React state (optimistic). Log warning. Retry on WS reconnect. |
| `DELETE /api/conversations/{id}` fails | Keep conversation in state. Show toast warning. Retry on WS reconnect. |
| WS `sync_state_ack` fires before conversations load | Queue `hydrateDocuments` call until `activeConversationId` is set. |

## Testing Strategy

```
tests/unit/           pure logic only (no I/O)
tests/contract/       boundary pins
tests/behavioral/     full-loop drives (live testing via Playwright/CDP)
```

- **Contract tests (CT-x):**
  - CT-1: PACMAN action shapes unchanged (`pacman_fragment`, `pacman_recall` signatures)
  - CT-2: WS `document:render` event shape unchanged (frontend handler signature)
  - CT-3: REST `/api/chat` request/response shape unchanged (`{text, thread_id}` → `{content, turn_id, thread_id}`)
  - CT-4: Conversation REST API shapes paginated and indexed (`GET /api/conversations`, `POST /api/conversations`, `POST /api/conversations/{id}/messages`, `DELETE /api/conversations/{id}`)
- **Behavioral tests:**
  - B1: Click send → conversation appears in sidebar → reload page → conversation still appears
  - B2: Send message in conversation A → create conversation B → verify B has no documents from A (cross-thread isolation)
  - B3: Delete conversation → verify it's gone from state and backend
  - B4: Backend offline → verify app shows empty list and graceful fallback
  - B5: Run websearch → verify documents rendered → reload page → verify documents re-appear from backend
  - B6: Click revert on assistant message N → verify messages N+1 onward removed from UI + backend → verify input field enabled
  - B7: Send message → simulate error response → click retry → verify message re-sent and error replaced with new response

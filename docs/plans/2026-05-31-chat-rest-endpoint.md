# REST /api/chat Endpoint + Thread Management + Immortus Integration Plan

> **Attached to:** `docs/plans/2026-05-31-swarm-vram-config-optimization.md`
> **Parent plan:** Swarm + VRAM + Config Optimization (FINAL)
> **Rationale:** Swarm workers, external agents, and the Tauri widget need an
> HTTP-native path to send messages into IRIS. Thread management + Immortus
> integration provides persistent, browseable conversations with 4D temporal
> routing lineage.

---

## 1. Architecture

```
                           ┌─────────────────────────────┐
POST /api/chat ───────────►│  backend/api/chat.py         │
                           │  (APIRouter, prefix=/api)    │
                           │                              │
                           │  1. Validate request         │
                           │  2. Resolve/get session_id   │
                           │  3. Call process_text_message│
                           │  4. Save to conversation     │
                           │     store (bridge)           │
                           │  5. chain_append to Immortus │
                           │  6. Return response          │
                           └──┬───────────────────────────┘
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
         agent_kernel.            conversation_store.py
         process_text_message()   (persistent message log)
              │
              ▼
         DER loop, Pacman, Caducean, MCM, memory interface
              │
         ConversationMemory (AgentKernel, in-memory)
```

**Thread management endpoints (same router):**
```
GET    /api/chat/threads              → list threads
POST   /api/chat/threads              → create thread
GET    /api/chat/threads/{id}         → get thread + messages
DELETE /api/chat/threads/{id}         → delete thread
POST   /api/chat/threads/{id}/fork    → fork from message N
```

---

## 2. Immortus Integration Design

### 2a. Thread ID Format

Thread IDs follow the Immortus `thread_id` format already established in
`ImmortusBrain._assign_thread_id()`:

```
immortus:thread-{prefix}-{suffix}
```

Where:
- `prefix` = first 4 chars of a user-provided label, or auto-generated
- `suffix` = last 4 chars of session_id, or random hex

Example: `immortus:thread-swar-abcd`, `immortus:thread-myap-1a2b`

**Impacts ImmortusBrain._assign_thread_id():** The format must match exactly.
The REST endpoint calls `_assign_thread_id()` (or an extracted shared helper)
to avoid duplicating the format string.

This ensures REST-created threads are cross-compatible with Immortus's
`memory_chain` infrastructure. The same format is used by `MCM.compress()`
when it calls `chain_append()`.

### 2b. chain_append on every exchange

Every `POST /api/chat` call that succeeds appends to the Immortus memory chain:

```python
def _record_to_immortus(thread_id, text, response, insight):
    """Record a chat exchange in the Immortus memory chain."""
    try:
        from backend.gateway.iris_ffi import ffi_immortus_chain_append
        ffi_immortus_chain_append(
            thread_id=thread_id,
            result="chat",
            coords_from=None,      # resolved from Mycelium if available
            coords_to=None,
            nbl_outcome=response[:40],  # first ~40 chars as summary
            insight=insight,
        )
    except Exception:
        pass  # never block chat on Immortus failure
```

This gives Immortus temporal lineage for every REST chat exchange — the same
way MCM compression records checkpoints.

### 2c. ImmortusBrain alignment

The `ImmortusBrain.evaluate()` is currently called during the agent kernel's
plan execution (DER loop). The REST endpoint doesn't bypass Immortus — it calls
`process_text_message()` which eventually reaches the DER loop, so Immortus
activation happens naturally for deep tasks.

No ImmortusBrain changes needed. The thread_id flows through naturally when
`MCM.compress()` is called inside `process_text_message()`.

---

## 3. Conversation Store Bridge

### 3a. The gap today

```
conversation_store.py (REST API)     vs.     ConversationMemory (AgentKernel)
──────────────────────────────                ────────────────────────────────
In-memory dict of conversations               Per-session rolling window
Exposed via /api/conversations/*              Used by LLM for context
Not connected to agent kernel                 Not exposed via REST
```

Messages saved via `POST /api/conversations/{id}/messages` go to the **store**
but never reach the agent. Messages sent via WebSocket `text_message` go to the
**ConversationMemory** but never reach the store.

### 3b. The bridge

**Write path:** After `POST /api/chat` calls `process_text_message()` and gets
a response, it also saves both the user message and assistant response to
`conversation_store.py`:

```python
from backend.conversation_store import add_message

# Save user message
add_message(conv_id, "user", request.text, turn_id=turn_id)
# Save assistant response
add_message(conv_id, "assistant", response.content,
            thinking=response.thinking, turn_id=turn_id)
```

**Read path:** On server startup, `ConversationMemory` restores from
`conversation_store` for known threads. This means conversation history
survives server restarts.

### 3c. Data flow

```
REST POST /api/chat  ──→  process_text_message()  ──→  ConversationMemory (agent)
                              │
                              ▼
                         conversation_store.add_message()  (persistent)
                              │
                              ▼
                         immortus_chain_append()           (temporal lineage)
```

The `conversation_store` becomes the **persistent layer** underneath the
agent's volatile `ConversationMemory`. After a restart, the agent rehydrates
its memory from the store.

---

## 4. Thread Management Endpoints

All endpoints live in `backend/api/chat.py` under `APIRouter(prefix="/api", tags=["chat"])`.

### `GET /api/chat/threads`

List all available threads (conversations).

```json
Response 200:
{
  "threads": [
    {
      "id": "immortus:thread-myap-1a2b",
      "title": "Debugging the image pipeline",
      "created_at": "2026-05-31T10:30:00Z",
      "updated_at": "2026-05-31T11:15:00Z",
      "message_count": 12,
      "pinned": false,
      "immortus_active": true
    }
  ]
}
```

Backed by `conversation_store.get_conversations()`. The `immortus_active` flag
is true when the thread has a recent Immortus chain entry (depth >= 3 check via
`iris_ffi`).

### `POST /api/chat/threads`

Create a new conversation thread. Returns a thread_id the caller uses as
`session_id` in subsequent `/api/chat` calls.

```json
Request:  { "title": "optional thread title" }
Response 201:
{
  "thread_id": "immortus:thread-myap-1a2b",
  "session_id": "immortus:thread-myap-1a2b",
  "title": "optional thread title",
  "created_at": "2026-05-31T12:00:00Z"
}
```

The `thread_id` and `session_id` are the same value — Immortus thread ID IS the
session ID. This avoids maintaining two separate identifiers.

### `GET /api/chat/threads/{thread_id}`

Get full thread details including message history.

```json
Response 200:
{
  "thread_id": "immortus:thread-myap-1a2b",
  "title": "Debugging the image pipeline",
  "messages": [
    {
      "id": "msg-1",
      "role": "user",
      "text": "Why is the pipeline failing?",
      "timestamp": "2026-05-31T10:30:00Z",
      "turn_id": "turn-abc123"
    },
    {
      "id": "msg-2",
      "role": "assistant",
      "text": "Let me check the logs...",
      "thinking": "The user is asking about...",
      "timestamp": "2026-05-31T10:30:05Z",
      "turn_id": "turn-abc123"
    }
  ],
  "immortus_chain": [
    {"result": "chat", "nbl_outcome": "Let me check the logs...", "timestamp": "..."},
    {"result": "landmark", "nbl_outcome": "fixed pipe", "timestamp": "..."}
  ]
}
```

Messages come from `conversation_store.get_conversation()`. Immortus chain
entries come from `iris_ffi` memory_chain table (if available).

### `DELETE /api/chat/threads/{thread_id}`

Delete a thread and its conversation history. Also calls
`immortus_chain_keep_latest(thread_id, 0)` to purge the Immortus chain for this
thread.

```json
Response 200: { "deleted": true, "thread_id": "immortus:thread-myap-1a2b" }
```

### `POST /api/chat/threads/{thread_id}/fork`

Fork a thread from a specific message. Creates a new thread with all messages
up to (and including) `message_id`.

```json
Request:  { "message_id": "msg-1", "title": "fork: pipeline fix attempt" }
Response 201:
{
  "thread_id": "immortus:thread-fork-3c4d",
  "parent_thread_id": "immortus:thread-myap-1a2b",
  "forked_from_message": "msg-1",
  "title": "fork: pipeline fix attempt"
}
```

This enables tree-structured conversations — fork at a decision point, explore
alternatives in a new thread, keep the original intact. The `parent_thread_id`
is recorded as an Immortus chain entry linking the two threads.

---

## 5. Request / Response Schema (updated)

### POST /api/chat

```json
Request:
{
  "text": "string (required)",
  "thread_id": "string (optional — creates new thread if omitted, becomes session_id)",
  "turn_id": "string (optional — auto-generated if omitted)",
  "from_voice": false
}

Response 200:
{
  "content": "Assistant response text",
  "thinking": "Chain-of-thought (if any)",
  "turn_id": "uuid",
  "thread_id": "immortus:thread-xxx-yyy (same as session_id)",
  "session_id": "immortus:thread-xxx-yyy (alias for thread_id)",
  "model": "model name used",
  "timing_ms": 1234
}

Error 4xx/5xx:
{
  "error": "Error description",
  "turn_id": "uuid",
  "code": "AGENT_UNAVAILABLE | EMPTY_TEXT | INTERNAL_ERROR"
}
```

**Key change:** The field is `thread_id` instead of `session_id` in the
request, to make the Immortus thread concept explicit. Internally it maps
directly to the session ID used by `get_agent_kernel()`.

---

## 6. File Changes

### NEW: `backend/api/chat.py` (~250 lines)

Three sections:

1. **Pydantic models** — `ChatRequest`, `ChatResponse`, `ChatError`,
   `ThreadInfo`, `ForkRequest`
2. **`POST /api/chat`** — the core chat endpoint with conversation_store
   bridge + Immortus chain_append
3. **Thread management** — `GET/POST /api/chat/threads`,
   `GET/DELETE /api/chat/threads/{id}`, `POST /api/chat/threads/{id}/fork`

```python
"""
REST chat endpoint + thread management + Immortus integration.

Attached to swarm VRAM config optimization plan.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    text: str
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    from_voice: bool = False


class ChatResponse(BaseModel):
    content: str
    thinking: str = ""
    turn_id: str
    thread_id: str
    session_id: str  # alias for thread_id
    model: str = ""
    timing_ms: int = 0


# ... ThreadInfo, ForkRequest, etc.


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    # 1. Resolve thread_id (create new if omitted)
    # 2. Get/create AgentKernel for this thread/session
    # 3. Call process_text_message()
    # 4. Save to conversation_store (bridge)
    # 5. chain_append to Immortus
    # 6. Return response


@router.get("/chat/threads")
async def list_threads():
    """List all threads from conversation_store."""


@router.post("/chat/threads")
async def create_thread(title: Optional[str] = None):
    """Create new thread with Immortus-compatible thread_id."""


@router.get("/chat/threads/{thread_id}")
async def get_thread(thread_id: str):
    """Get thread + messages + optional Immortus chain."""


@router.delete("/chat/threads/{thread_id}")
async def delete_thread(thread_id: str):
    """Delete thread + purge Immortus chain."""


@router.post("/chat/threads/{thread_id}/fork")
async def fork_thread(thread_id: str, message_id: str, title: Optional[str] = None):
    """Fork new thread from a specific message."""
```

### MODIFIED: `backend/conversation_store.py`

Upgrade from in-memory dict to SQLite-backed persistence so conversations
survive server restarts:

```python
# Before: _conversations: dict[str, dict] = {}
# After:  SQLite table with same schema, auto-created on import

_conversations: dict[str, dict] = {}  # in-memory cache
_DB_PATH = "backend/data/conversations.db"

def _load_from_db():
    """Load all conversations into memory on startup."""

def _save_to_db(conv_id: str):
    """Persist a single conversation after mutation."""
```

This is a **transparent upgrade** — all existing callers (`main.py` endpoints)
continue to work unchanged. The dict remains the read cache; writes go to SQLite.

### MODIFIED: `backend/main.py`

```python
from backend.api.chat import router as chat_router
app.include_router(chat_router)
```

Placed alongside the existing `status_snapshot_router` include (line 726).

### UNCHANGED: `backend/iris_gateway.py`

The WebSocket `_handle_chat` handler stays exactly as-is. It does NOT write to
`conversation_store` — that's the REST endpoint's responsibility. The WS path
continues to use `ConversationMemory` directly, as it always has.

---

## 7. Immortus Integration — Detailed API Mapping

| REST operation | Immortus action |
|---------------|-----------------|
| `POST /api/chat` (new thread) | `immortus_chain_append(thread_id, result="chat_init")` |
| `POST /api/chat` (exchange) | `immortus_chain_append(thread_id, result="chat", nbl_outcome=summary)` |
| `POST /api/chat/threads` | No Immortus action (empty thread, no chain yet) |
| `DELETE /api/chat/threads/{id}` | `immortus_chain_keep_latest(thread_id, 0)` — purge chain |
| `POST .../fork` | `immortus_chain_append(new_id, result="fork", insight=f"forked from {parent_id}")` |
| `GET /api/chat/threads/{id}` | Optionally queries `memory_chain` table for chain display |

**Graceful degradation:** All Immortus FFI calls are wrapped in try/except. If
the C hybrid core isn't loaded or the memory_chain table doesn't exist, the
REST endpoint degrades to standard chat + conversation_store only.

---

## 8. Session / Thread Resolution Strategy

| Scenario | thread_id resolution |
|----------|---------------------|
| Caller provides `thread_id` | Used directly as session_id for `get_agent_kernel()` |
| Caller omits `thread_id` | Generate new `immortus:thread-{4-char-prefix}-{4-char-suffix}` |
| WebSocket session | Unchanged — WS uses its own session_id from ws_manager |
| Existing conversation_store thread | Load messages into ConversationMemory on first access |

**Thread → Session mapping:**

```python
def _resolve_thread(thread_id: Optional[str]) -> str:
    """Resolve thread_id, creating a new Immortus-compatible one if needed."""
    if thread_id:
        return thread_id
    import uuid
    suffix = uuid.uuid4().hex[:4]
    return f"immortus:thread-api-{suffix}"
```

---

## 9. Conversation Store Bridge — Detailed Design

### Write bridge

```python
# Inside POST /api/chat handler:
from backend.conversation_store import get_conversation, add_message

conv = get_conversation(thread_id)
if conv is None:
    # Auto-create conversation entry in store
    from backend.conversation_store import create_conversation
    conv = create_conversation(title=text[:40], conv_id=thread_id)

# Save user message
add_message(thread_id, "user", request.text, turn_id=turn_id,
            metadata={"source": "rest_api"})

# After agent responds:
add_message(thread_id, "assistant", response_content,
            thinking=thinking, turn_id=turn_id,
            metadata={"model": model_name, "timing_ms": elapsed_ms})
```

### Read bridge (startup restore)

```python
# In AgentKernel initialization, OR in REST handler on first access
def _hydrate_from_store(thread_id: str, conversation_memory):
    """Restore ConversationMemory from conversation_store entries."""
    conv = get_conversation(thread_id)
    if conv and conv.get("messages"):
        for msg in conv["messages"]:
            conversation_memory.add_message(
                msg["role"], msg["text"],
                task_id=msg.get("turn_id"),
            )
```

### Persistence upgrade for conversation_store.py

Current: `/api/conversations/{id}` endpoints already work but data is lost
on restart. The SQLite upgrade makes them durable.

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TEXT,
    updated_at TEXT,
    pinned INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id),
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    thinking TEXT DEFAULT '',
    turn_id TEXT,
    metadata TEXT DEFAULT '{}',
    timestamp TEXT NOT NULL
);
```

---

## 10. Risk Assessment (updated)

| Risk | Impact | Mitigation |
|------|--------|------------|
| Memory system breakage | None | Memory wired to AgentKernel instance, not transport |
| Immortus call failure | None | All FFI calls wrapped in try/except — degrades gracefully |
| Thread ID collision | Low | UUID suffix in auto-generated IDs |
| Session leak (REST threads) | Low | GC after 30 min inactivity (existing mechanism) |
| Auth bypass | None | Local-only (Tauri widget on same machine) |
| conversation_store corruption | Low | SQLite WAL mode, single-writer |
| conversation_store ≠ ConversationMemory out of sync | Low | conversation_store is authoritative; ConversationMemory rehydrates from it |
| Tauri widget inconsistency | None | Widget uses WS for full UI; REST is optional add |

**Verdict:** Low risk. The memory system is transport-agnostic. Immortus is
already hardened with try/except wrappers. conversation_store upgrade makes
existing data survive restarts. Total new code ~250 lines.

---

## 11. Code Deduplication Audit

Every line evaluated against what already exists. No duplicate code.

### 11a. Shared code vs. new code

| Component | Status | Why not duplicate |
|-----------|--------|-------------------|
| `process_text_message()` | **Reused** | The REST handler calls it — same method as WebSocket. Zero duplicate logic. |
| `AgentKernel` resolution | **Different by transport** | REST: thread→session→`get_agent_kernel()`. WS: client_id→`ws_manager.get_session_id_for_client()`. Different inputs (HTTP body vs. WS connection), same output (AgentKernel). This is adaptation, not duplication. |
| `immortus_chain_append()` | **Reused via FFI** | The REST handler calls the same FFI function that `MCM.compress()` calls. No wrapper, no abstraction layer — direct FFI call. |
| `conversation_store.add_message()` | **Reused** | Existing function. REST calls it after each exchange. No duplicate storage logic. |
| `conversation_store.get_conversation()` | **Reused** | Existing function. Thread management endpoints call it. |
| Thread ID generation | **Shared helper** | Extract from `ImmortusBrain._assign_thread_id()` into `backend/agent/immortus/__init__.py`. Both ImmortusBrain and REST import from same source. |
| Pydantic models | **New** | `ChatRequest`, `ChatResponse`, `ChatError`, `ThreadInfo`, `ForkRequest` — no existing models to duplicate. |
| `/api/chat` route | **New** | No existing chat REST route. The existing `/api/conversations/*` endpoints are for browsing/logging — different purpose. |
| Immortus chain for WS path | **N/A** | WS path doesn't call chain_append for chat (MCM.compress() handles checkpoint-level chain entries during DER loop). REST calls chain_append for every exchange. Different trigger, same function → NOT duplication. |
| SSE streaming | **Not built** | Avoided by design — would duplicate WebSocket streaming logic. |

### 11b. Verification mechanism

A CI check or manual review step to verify deduplication:
```bash
# Check that process_text_message is imported, not reimplemented
python -c "
import ast, sys
with open('backend/api/chat.py') as f:
    tree = ast.parse(f.read())
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef):
        if node.name == 'process_text_message':
            print('❌ DUPLICATED: process_text_message() found in chat.py')
            sys.exit(1)
print('✅ PASS: process_text_message not duplicated')
"
```

---

## 12. Technical Debt Assessment

### 12a. What we ARE adding

| Item | Lines | Certainty |
|------|-------|-----------|
| `backend/api/chat.py` | ~250 | New code |
| `conversation_store.py` upgrade | ~50 | Modify existing, add SQLite behind current dict API |
| `backend/agent/immortus/__init__.py` | +3 | Add shared `generate_thread_id()` helper |
| `backend/main.py` | +2 | Import + include_router |
| Test files | ~200 | New |

**Total new surface area:** ~500 lines of code + ~50 lines modified.

### 12b. What we are NOT adding (anti-debt)

- **No new dependencies** — FastAPI, Pydantic, sqlite3 are already available
- **No new configuration** — No env vars, no config files
- **No model loading** — Reuses whatever AgentKernel has
- **No provider management** — Model switching is transparent
- **No new FFI/C++ functions** — Uses existing `ffi_immortus_chain_append()`
- **No WebSocket changes** — WS path untouched, zero regression risk
- **No DER loop changes** — The REST endpoint just calls `process_text_message()` which enters DER naturally
- **No memory interface changes** — Memory is wired at AgentKernel level
- **No SSE streaming** — Avoided by design (prevents duplicating WS streaming)
- **No authentication** — Local-only (Tauri widget on same machine)
- **No TLS/HTTPS** — Local-only, downstream proxy handles this
- **No rate limiting** — Keepalive is caller's responsibility
- **No new IPC** — Everything in-process (FastAPI + AgentKernel same process)

### 12c. Debt categories and mitigation

| Potential Debt | Risk | Mitigation |
|---------------|------|------------|
| **REST + WS dual chat paths** | Two ways to do the same thing | They share `process_text_message()`. The REST endpoint is a pass-through, not a reimplementation. No divergence risk because the agent logic lives in one place. |
| **conversation_store + ConversationMemory dual storage** | Messages in two places | Standard cache-through: conversation_store is authoritative (SQLite), ConversationMemory is runtime cache (rehydrates from store on startup). Writes go to both. Reads from ConversationMemory for speed. |
| **Thread ID generation duplicated** | Format drifts from ImmortusBrain | Extracted shared helper `generate_thread_id()` in `immortus/__init__.py`. Both ImmortusBrain and REST import from same function. If the format changes, it changes everywhere. |
| **Immortus chain_append in two places** | Different callers, same function | This is intentional — MCM.compress() records checkpoints, REST records chat exchanges. Different event types, same FFI function. No duplication risk. |
| **New test infrastructure** | Tests diverge from existing patterns | Follow `tests/bugfix/test_websocket_integration.py` pattern (FastAPI TestClient + pytest). Use same fixtures. |

### 12d. Debt paydown opportunities (existing, not new)

While implementing, we can fix these pre-existing issues at no extra cost:
1. `conversation_store.py` is in-memory only (no restart survival) → SQLite upgrade fixes this
2. No FastAPI TestClient usage in `backend/tests/` → this establishes the pattern
3. No thread/conversation ID format shared with Immortus → shared helper fixes this

---

## 13. Comprehensive Testing

### 13a. Test philosophy

```
Three layers: Unit → Integration → E2E

Each layer answers a different question:
  Unit:        "Does the logic work in isolation?"
  Integration: "Does the HTTP endpoint work against the real FastAPI app?"
  E2E:         "Does the full flow work with real AgentKernel + conversation_store + Immortus?"
```

**Test files (new):**

| File | Layer | What it tests |
|------|-------|---------------|
| `backend/tests/test_chat_models.py` | Unit | Pydantic validation, thread ID generation |
| `backend/tests/test_chat_handler.py` | Integration | HTTP endpoints against TestClient |
| `backend/tests/test_chat_persistence.py` | Integration | conversation_store bridge, restart survival |
| `backend/tests/test_chat_immortus.py` | Integration | Immortus chain_append integration |
| `backend/tests/test_chat_e2e.py` | E2E | Full flow with real AgentKernel |

**Existing tests that must still pass (regression guard):**
- `tests/bugfix/test_websocket_integration.py`
- `backend/tests/test_*.py` (all)
- `backend/memory/tests/` (all)

### 13b. Unit Tests — `test_chat_models.py`

```python
import pytest
from pydantic import ValidationError
from backend.api.chat import ChatRequest, ChatResponse, ChatError

class TestChatRequest:
    def test_valid_request(self):
        req = ChatRequest(text="hello")
        assert req.text == "hello"
        assert req.thread_id is None  # optional
        assert req.turn_id is None
        assert req.from_voice is False

    def test_required_text(self):
        with pytest.raises(ValidationError):
            ChatRequest()  # missing required text field

    def test_empty_text_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(text="")  # empty string

    def test_whitespace_text(self):
        with pytest.raises(ValidationError):
            ChatRequest(text="   ")  # blank after strip

class TestChatResponse:
    def test_full_response(self):
        resp = ChatResponse(
            content="Hello!", turn_id="abc-123",
            thread_id="immortus:thread-test-abcd",
            session_id="immortus:thread-test-abcd"
        )
        assert resp.content == "Hello!"
        assert resp.turn_id == "abc-123"
        assert resp.thread_id == resp.session_id  # must be aliased

class TestThreadIdGeneration:
    def test_format_matches_immortus(self):
        from backend.agent.immortus import generate_thread_id
        tid = generate_thread_id()
        assert tid.startswith("immortus:thread-")
        assert len(tid) > len("immortus:thread-")  # has prefix + suffix
    
    def test_reproducible_with_same_args(self):
        from backend.agent.immortus import generate_thread_id
        tid1 = generate_thread_id(prefix="test")
        tid2 = generate_thread_id(prefix="test")
        # Same prefix should produce unique IDs (different suffix)
        assert tid1 != tid2
        assert "immortus:thread-test-" in tid1
```

### 13c. Integration Tests — `test_chat_handler.py`

Uses FastAPI TestClient against the real app fixture:

```python
import pytest
from fastapi.testclient import TestClient
from backend.main import app

@pytest.fixture
def client():
    """TestClient backed by the real FastAPI app."""
    return TestClient(app)

class TestChatEndpoint:
    """POST /api/chat"""

    def test_basic_chat(self, client):
        """Send a message and get a response."""
        response = client.post("/api/chat", json={"text": "Hello!"})
        assert response.status_code == 200
        data = response.json()
        assert "content" in data
        assert "turn_id" in data
        assert "thread_id" in data
        assert data["thread_id"].startswith("immortus:thread-")
        assert data["session_id"] == data["thread_id"]  # alias

    def test_reuses_thread(self, client):
        """Same thread_id across requests preserves conversation."""
        thread_id = "immortus:thread-test-abcd"
        r1 = client.post("/api/chat", json={
            "text": "First message", "thread_id": thread_id
        })
        assert r1.status_code == 200
        assert r1.json()["thread_id"] == thread_id

        r2 = client.post("/api/chat", json={
            "text": "Second message in same thread", "thread_id": thread_id
        })
        assert r2.status_code == 200
        assert r2.json()["thread_id"] == thread_id

    def test_missing_text_rejected(self, client):
        """Empty text returns 422."""
        response = client.post("/api/chat", json={})
        assert response.status_code == 422

    def test_empty_text_rejected(self, client):
        """Blank text returns 422."""
        response = client.post("/api/chat", json={"text": ""})
        assert response.status_code == 422

    def test_new_thread_on_no_thread_id(self, client):
        """Omitting thread_id creates a new thread."""
        r1 = client.post("/api/chat", json={"text": "Thread A"})
        r2 = client.post("/api/chat", json={"text": "Thread B"})
        assert r1.json()["thread_id"] != r2.json()["thread_id"]

    def test_from_voice_flag(self, client):
        """from_voice boolean is accepted."""
        response = client.post("/api/chat", json={
            "text": "Voice message", "from_voice": True
        })
        assert response.status_code == 200

class TestThreadEndpoints:
    """Thread management CRUD"""

    def test_list_threads_empty(self, client):
        """Initially no threads (or only the one just created)."""
        # Create one first
        client.post("/api/chat", json={"text": "populate thread"})
        response = client.get("/api/chat/threads")
        assert response.status_code == 200
        assert "threads" in response.json()
        assert len(response.json()["threads"]) >= 1

    def test_create_thread(self, client):
        """POST /api/chat/threads returns a valid thread."""
        response = client.post("/api/chat/threads", json={
            "title": "Test Thread"
        })
        assert response.status_code == 201
        data = response.json()
        assert "thread_id" in data
        assert data["thread_id"].startswith("immortus:thread-")
        assert "created_at" in data

    def test_get_thread(self, client):
        """GET /api/chat/threads/{id} returns thread + messages."""
        # Create thread via chat
        r = client.post("/api/chat", json={"text": "Message in thread"})
        thread_id = r.json()["thread_id"]
        
        response = client.get(f"/api/chat/threads/{thread_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["thread_id"] == thread_id
        assert len(data["messages"]) >= 1  # has the message we sent

    def test_get_nonexistent_thread(self, client):
        """Missing thread returns 404."""
        response = client.get("/api/chat/threads/does-not-exist")
        assert response.status_code == 404

    def test_delete_thread(self, client):
        """DELETE /api/chat/threads/{id} removes it."""
        r = client.post("/api/chat", json={"text": "delete me"})
        thread_id = r.json()["thread_id"]
        
        delete_resp = client.delete(f"/api/chat/threads/{thread_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["deleted"] is True
        
        # Verify gone
        get_resp = client.get(f"/api/chat/threads/{thread_id}")
        assert get_resp.status_code == 404

    def test_fork_thread(self, client):
        """Fork creates a new thread with parent linkage."""
        # Create thread with 2+ messages
        r1 = client.post("/api/chat", json={
            "text": "Msg 1", "thread_id": "immortus:thread-fork-parent"
        })
        r2 = client.post("/api/chat", json={
            "text": "Msg 2", "thread_id": "immortus:thread-fork-parent"
        })
        
        # Fork at the first message
        fork_resp = client.post(
            f"/api/chat/threads/immortus:thread-fork-parent/fork",
            json={"message_id": "1"}  # or whatever ID scheme
        )
        assert fork_resp.status_code == 201
        fork_data = fork_resp.json()
        assert fork_data["thread_id"] != "immortus:thread-fork-parent"
        assert fork_data["parent_thread_id"] == "immortus:thread-fork-parent"
```

### 13d. Persistence & Restart Tests — `test_chat_persistence.py`

```python
import pytest
from fastapi.testclient import TestClient

class TestConversationPersistence:
    """Verify conversation_store bridge works correctly."""

    def test_messages_saved_to_store(self, client):
        """After POST /api/chat, messages exist in conversation_store."""
        from backend.conversation_store import get_conversation
        
        response = client.post("/api/chat", json={
            "text": "Save me", "thread_id": "immortus:thread-persist-test"
        })
        assert response.status_code == 200
        
        # Check store has the messages
        conv = get_conversation("immortus:thread-persist-test")
        assert conv is not None
        messages = conv.get("messages", [])
        assert len(messages) >= 2  # user + assistant
        assert messages[0]["role"] == "user"
        assert messages[0]["text"] == "Save me"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"]  # response

    def test_survives_restart(self, client):
        """Messages survive server restart (SQLite persistence)."""
        import tempfile, os
        from backend import conversation_store as cs
        
        # Force a known SQLite path for testing
        original_db = cs._DB_PATH
        try:
            cs._DB_PATH = ":memory:"  # in-memory for test isolation
            cs._load_from_db()
            
            # Add a message
            cs.create_conversation(title="restart test",
                                   conv_id="immortus:thread-restart-test")
            cs.add_message("immortus:thread-restart-test",
                           "user", "Hello", turn_id="t1")
            
            # Simulate restart by reloading
            cs._conversations = {}
            cs._load_from_db()
            
            # Verify message survived
            conv = cs.get_conversation("immortus:thread-restart-test")
            assert conv is not None
            assert len(conv["messages"]) == 1
            assert conv["messages"][0]["text"] == "Hello"
        finally:
            cs._DB_PATH = original_db

    def test_hydrate_conversation_memory(self, client):
        """ConversationMemory rehydrates from store on access."""
        from backend.conversation_store import create_conversation, add_message
        
        # Pre-populate store
        create_conversation(title="hydrate test",
                            conv_id="immortus:thread-hydrate-test")
        add_message("immortus:thread-hydrate-test",
                    "user", "restored message", turn_id="t1")
        
        # Send a message — agent should see the stored history
        response = client.post("/api/chat", json={
            "text": "Do you remember the previous message?",
            "thread_id": "immortus:thread-hydrate-test"
        })
        assert response.status_code == 200
        # The response 'content' should reflect that history was available
        # (implicit — tested by the agent's behavior, not exact string match)
```

### 13e. Immortus Integration Tests — `test_chat_immortus.py`

```python
import pytest

class TestImortusChainAppend:
    """Verify Immortus chain_append is called for each exchange."""

    def test_chain_recorded(self, client):
        """After POST /api/chat, Immortus chain has an entry."""
        from backend.gateway.iris_ffi import ffi_immortus_chain_fetch
        
        response = client.post("/api/chat", json={
            "text": "Record in Immortus",
            "thread_id": "immortus:thread-immortus-test"
        })
        assert response.status_code == 200
        
        # Fetch chain entries for this thread
        entries = ffi_immortus_chain_fetch(
            "immortus:thread-immortus-test", limit=10
        )
        assert len(entries) >= 1
        latest = entries[-1]  # most recent
        assert latest["result"] == "chat"

    def test_graceful_degradation_when_ffi_down(self, client, monkeypatch):
        """chat still works even if immortus FFI fails."""
        # Simulate FFI failure
        monkeypatch.setattr(
            "backend.gateway.iris_ffi.ffi_immortus_chain_append",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("FFI not loaded"))
        )
        
        # Chat should still work
        response = client.post("/api/chat", json={
            "text": "Immortus is down but I should work"
        })
        assert response.status_code == 200

    def test_messages_have_chain(self, client):
        """Each message in a thread has a chain entry."""
        thread_id = "immortus:thread-chain-count"
        
        r1 = client.post("/api/chat", json={
            "text": "Chain entry 1", "thread_id": thread_id
        })
        assert r1.status_code == 200
        
        r2 = client.post("/api/chat", json={
            "text": "Chain entry 2", "thread_id": thread_id
        })
        assert r2.status_code == 200
        
        from backend.gateway.iris_ffi import ffi_immortus_chain_fetch
        entries = ffi_immortus_chain_fetch(thread_id, limit=10)
        assert len(entries) >= 2
```

### 13f. E2E Tests — `test_chat_e2e.py`

```python
import pytest

class TestFullFlow:
    """Complete flow: thread → messages → persistence → fork → verify."""

    def test_complete_thread_lifecycle(self, client):
        """Full lifecycle of a thread with Immortus integration."""
        from backend.conversation_store import get_conversation
        
        thread_id = "immortus:thread-e2e-full"
        
        # 1. Create thread via chat
        r1 = client.post("/api/chat", json={
            "text": "What is the capital of France?",
            "thread_id": thread_id
        })
        assert r1.status_code == 200
        cap_france = r1.json()["content"]
        
        # 2. Follow-up in same thread
        r2 = client.post("/api/chat", json={
            "text": "What is its population?",
            "thread_id": thread_id
        })
        assert r2.status_code == 200
        
        # 3. Verify conversation_store has both exchanges
        conv = get_conversation(thread_id)
        assert conv is not None
        assert len(conv["messages"]) == 4  # 2 user + 2 assistant
        
        # 4. Fork at first message
        fork_resp = client.post(
            f"/api/chat/threads/{thread_id}/fork",
            json={"message_id": conv["messages"][0]["id"]}
        )
        assert fork_resp.status_code == 201
        fork_id = fork_resp.json()["thread_id"]
        
        # 5. Verify fork has parent linkage
        assert fork_resp.json()["parent_thread_id"] == thread_id
        
        # 6. Send message in forked thread
        r3 = client.post("/api/chat", json={
            "text": "Tell me about the Eiffel Tower instead",
            "thread_id": fork_id
        })
        assert r3.status_code == 200
        
        # 7. Delete original thread
        delete_resp = client.delete(f"/api/chat/threads/{thread_id}")
        assert delete_resp.status_code == 200
        
        # 8. Fork still exists (independent)
        get_fork = client.get(f"/api/chat/threads/{fork_id}")
        assert get_fork.status_code == 200

    def test_concurrent_threads(self, client):
        """Multiple threads interleaved don't interfere."""
        t1 = "immortus:thread-e2e-concurrent-a"
        t2 = "immortus:thread-e2e-concurrent-b"
        
        r1 = client.post("/api/chat", json={
            "text": "Thread A message 1", "thread_id": t1
        })
        r2 = client.post("/api/chat", json={
            "text": "Thread B message 1", "thread_id": t2
        })
        r3 = client.post("/api/chat", json={
            "text": "Thread A message 2", "thread_id": t1
        })
        r4 = client.post("/api/chat", json={
            "text": "Thread B message 2", "thread_id": t2
        })
        
        assert all(r.status_code == 200 for r in [r1, r2, r3, r4])
        
        # Verify thread A has 2 exchanges (4 messages)
        from backend.conversation_store import get_conversation
        conv_a = get_conversation(t1)
        conv_b = get_conversation(t2)
        assert len(conv_a["messages"]) == 4
        assert len(conv_b["messages"]) == 4
        assert conv_a["messages"][0]["text"] == "Thread A message 1"
        assert conv_b["messages"][0]["text"] == "Thread B message 1"
```

### 13g. Regression Tests — No WebSocket Breakage

These tests run against the WebSocket path to confirm the REST endpoint doesn't
break existing functionality:

```python
class TestWebSocketRegression:
    """REST endpoint must not break existing WebSocket chat."""

    def test_websocket_still_works(self, ws_client):
        """Existing WS chat path is untouched."""
        # This test reuses the pattern from tests/bugfix/test_websocket_integration.py
        # It sends a text_message via WebSocket and expects chat_chunk + chat_message
        # Pass condition: same behavior as before the REST endpoint was added
        pass  # full body is in bugfix/test_websocket_integration.py

    def test_conversation_store_backward_compat(self, client):
        """Existing /api/conversations/* endpoints still work."""
        response = client.get("/api/conversations")
        assert response.status_code == 200
        # conversation_store.get_all_conversations() still returns dict format
```

### 13h. Test Run Command

```bash
# Run all chat tests
python -m pytest backend/tests/test_chat_*.py -v

# Run with coverage
python -m pytest backend/tests/test_chat_*.py --cov=backend.api.chat --cov=backend.conversation_store

# Run regression (existing tests)
python -m pytest tests/bugfix/test_websocket_integration.py -v
python -m pytest backend/tests/ -v
python -m pytest backend/memory/tests/ -v

# All tests must pass before marking landmark
python -m pytest backend/tests/test_chat_*.py tests/bugfix/ backend/tests/ backend/memory/tests/ -v
```

### 13i. Pass Criteria (immutable — don't relax to pass)

1. All unit tests pass
2. All integration tests pass against TestClient
3. All E2E tests pass with real AgentKernel
4. All existing tests pass (regression: WS, memory, core)
5. `POST /api/chat` with live AgentKernel returns valid `ChatResponse`
6. Thread management CRUD works for all 5 endpoints
7. conversation_store survives server restart (SQLite)
8. Immortus chain_append is called (verify with fetch)
9. Immortus FFI failure → chat still works (graceful degradation)
10. WebSocket chat still works identically (regression test)

---

## 14. Execution Order (updated with testing)

| Step | What | Validation | Depends on |
|------|------|-----------|------------|
| 1 | Extract `generate_thread_id()` to `immortus/__init__.py` | `test_chat_models.py::TestThreadIdGeneration` | Nothing |
| 2 | Upgrade `conversation_store.py` to SQLite-backend | `test_chat_persistence.py::test_survives_restart` | Nothing |
| 3 | Create `backend/api/chat.py` with models + POST /api/chat | `test_chat_handler.py::TestChatEndpoint` | Step 1, 2 |
| 4 | Wire conversation_store bridge (write path) | `test_chat_persistence.py::test_messages_saved_to_store` | Step 2, 3 |
| 5 | Wire Immortus chain_append | `test_chat_immortus.py::test_chain_recorded`, `test_graceful_degradation` | Step 3 |
| 6 | Add thread management endpoints | `test_chat_handler.py::TestThreadEndpoints` | Step 2, 3 |
| 7 | Register router in `main.py` | Manual: curl POST /api/chat | Step 3 |
| 8 | Run full regression suite | ALL tests pass | Step 7 |
| 9 | Record landmark | `agent_context.py --complete` | Step 8 |

**Scheduling:** Fits alongside swarm plan execution step 15 (API endpoints).
Steps 1-6 ~2-3 hours. Steps 7-9 ~1 hour of verification.

---

## 15. What This Unlocks

| Capability | Before | After |
|------------|--------|-------|
| Chat via HTTP | ❌ | ✅ POST /api/chat |
| Conversations survive restart | ❌ (in-memory only) | ✅ SQLite-backed |
| Thread listing | ❌ | ✅ GET /api/chat/threads |
| Thread forking / branching | ❌ | ✅ POST .../fork |
| Immortus temporal lineage for chat | ❌ | ✅ chain_append per exchange |
| WS ↔ REST chat coexistence | N/A | ✅ Same AgentKernel, no conflict |
| External agent integration | ❌ | ✅ curl, scripts, swarm workers |
| Full test coverage for new code | ❌ | ✅ 3 test layers, ~200 lines |
| Thread ID cross-compatibility | ❌ (only ImmortusBrain had format) | ✅ Shared helper, no format drift |
| conversation_store survives restarts | ❌ (in-memory dict) | ✅ SQLite persistence |

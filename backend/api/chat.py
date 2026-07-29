"""
REST /api/chat endpoint + thread management + Immortus integration.

Thin HTTP adapter over ``agent_kernel.process_text_message()`` —
the same method the WebSocket ``_handle_chat`` calls. No duplicate logic.

Attached to:  docs/plans/2026-05-31-swarm-vram-config-optimization.md
Plan:         docs/plans/2026-05-31-chat-rest-endpoint.md
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


# ── Pydantic models ────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""

    text: str
    thread_id: Optional[str] = None
    turn_id: Optional[str] = None
    from_voice: bool = False

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("text must not be empty or blank")
        return stripped


class ChatResponse(BaseModel):
    """Success response for POST /api/chat."""

    content: str
    thinking: str = ""
    turn_id: str
    thread_id: str
    session_id: str  # alias for thread_id
    model: str = ""
    timing_ms: int = 0


class ChatError(BaseModel):
    """Error response for POST /api/chat."""

    error: str
    turn_id: str
    code: str


class ThreadInfo(BaseModel):
    """Summary of a single conversation thread."""

    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    pinned: bool = False
    immortus_active: bool = False


class ThreadListResponse(BaseModel):
    """Response for GET /api/chat/threads."""

    threads: list[ThreadInfo]


class CreateThreadRequest(BaseModel):
    """Request body for POST /api/chat/threads."""

    title: Optional[str] = None


class CreateThreadResponse(BaseModel):
    """Response for POST /api/chat/threads."""

    thread_id: str
    session_id: str
    title: str
    created_at: str


class ThreadDetail(BaseModel):
    """Full thread detail including messages and optional Immortus chain."""

    thread_id: str
    title: str
    messages: list[dict[str, Any]]
    immortus_chain: list[dict[str, Any]] = []


class ForkRequest(BaseModel):
    """Request body for POST /api/chat/threads/{id}/fork."""

    message_id: str
    title: Optional[str] = None

    @field_validator("message_id")
    @classmethod
    def message_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message_id must not be empty")
        return v.strip()


class ForkResponse(BaseModel):
    """Response for POST /api/chat/threads/{id}/fork."""

    thread_id: str
    parent_thread_id: str
    forked_from_message: str
    title: str


# ── Helpers ────────────────────────────────────────────────────────────


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _generate_turn_id() -> str:
    """Generate a unique turn/event ID."""
    return uuid.uuid4().hex[:12]


def _record_to_immortus(
    thread_id: str,
    text: str,
    response: str,
    turn_id: str,
) -> None:
    """Record a chat exchange in the Immortus memory chain (non-blocking).

    All FFI calls are try/except wrapped — never blocks the chat response.
    """
    try:
        from backend.gateway.iris_ffi import ffi_immortus_chain_append

        ffi_immortus_chain_append(
            thread_id=thread_id,
            result="chat",
            nbl_outcome=response[:40],
            insight=f"turn:{turn_id} input:{text[:60]}",
            coords_from=f"rest:input:{turn_id}",
            coords_to=f"rest:output:{turn_id}",
        )
    except Exception as exc:
        logger.debug("[ChatREST] Immortus chain_append skipped: %s", exc)


def _resolve_thread_id(thread_id: Optional[str]) -> str:
    """Resolve a thread_id, creating a new Immortus-compatible one if needed.

    The returned value doubles as the ``session_id`` for
    ``get_agent_kernel()``.
    """
    if thread_id:
        return thread_id
    from backend.agent.immortus import generate_thread_id

    return generate_thread_id(prefix="rest")


async def _run_agent_kernel(
    kernel: Any,
    text: str,
    session_id: str,
    turn_id: str,
    from_voice: bool,
) -> tuple[str, str, int]:
    """Call ``process_text_message()`` in a thread pool executor.

    Returns ``(content, thinking, elapsed_ms)``.
    """
    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()

    content: str = await loop.run_in_executor(
        None,
        lambda: kernel.process_text_message(
            text=text,
            session_id=session_id,
            turn_id=turn_id,
            from_voice=from_voice,
        ),
    )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    # Collect thinking from the kernel (may be empty)
    thinking: str = getattr(kernel, "_pending_thinking", "") or ""
    if not thinking:
        thinking = getattr(kernel, "last_thinking", "") or ""

    return content, thinking, elapsed_ms


# ── Fire-and-forget TTS ────────────────────────────────────────────────


async def _fire_tts_background(text: str, session_id: str) -> None:
    """Synthesize and play TTS for the assistant response.

    Runs as a background asyncio task so the HTTP response returns
    immediately — the user sees text while TTS audio catches up.
    TTS errors are logged at DEBUG level and never break the response.
    """
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _sync_tts_playback, text)
    except Exception as exc:
        logger.warning("[ChatREST] Background TTS skipped: %s", exc)


def _sync_tts_playback(text: str) -> None:
    """Synchronous TTS synthesis + playback (runs in thread pool).

    Sequence: suppress Porcupine → synthesize → play → release.
    """
    engine = None
    try:
        from backend.agent.tts import get_tts_manager
        from backend.audio.pipeline import get_audio_pipeline
        from backend.audio.engine import get_audio_engine

        engine = get_audio_engine()
        if engine:
            engine.set_tts_active(True)

        tts = get_tts_manager()
        pipeline = get_audio_pipeline()

        chunks = list(tts.synthesize_stream(text))
        if chunks and pipeline:
            pipeline.play_stream(chunks)
    except Exception as exc:
        logger.warning("[ChatREST] TTS background playback error: %s", exc)
    finally:
        if engine is not None:
            engine.set_tts_active(False)


# ── POST /api/chat ─────────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Send a text message to IRIS and get a complete response.

    This is the REST complement to the WebSocket ``text_message`` handler.
    Calls the same ``agent_kernel.process_text_message()`` — no duplicated
    logic.  Messages are persisted to ``conversation_store`` and recorded
    in the Immortus memory chain.
    """
    from backend.agent.agent_kernel import get_agent_kernel
    from backend.conversation_store import (
        add_message,
        create_conversation,
        get_conversation,
    )

    turn_id = request.turn_id or _generate_turn_id()
    thread_id = _resolve_thread_id(request.thread_id)

    # DIAGNOSTIC: log what the frontend actually sends
    import logging as _lg

    _lg.getLogger("irisvoice").info(
        f"[DIAG] Chat request: text_len={len(request.text)} thread_id_in={request.thread_id} thread_id_resolved={thread_id} from_voice={request.from_voice}"
    )

    # ── 1. Resolve / create conversation-store entry ───────────────────
    conv = get_conversation(thread_id)
    if conv is None:
        conv = create_conversation(
            title=request.text[:40],
            conv_id=thread_id,
        )

    # ── 2. Save user message ───────────────────────────────────────────
    add_message(thread_id, "user", request.text, turn_id=turn_id, source="rest_api")

    # ── 3. Get / create agent kernel for this conversation ─────────────
    # Wave 5: key by conversation_id (thread_id), NOT session_id, so the REST
    # chat path shares the same kernel as the WS voice/text path for the thread
    # instead of spawning a disconnected "default" kernel.
    kernel = get_agent_kernel(conversation_id=thread_id, session_id=thread_id)

    # ── 4. Wire task events to frontend WS (so TaskListCard + tool calls
    #       appear live, not just at the end). ───────────────────────────
    _event_queue = []
    _event_bus_cleanup = None
    try:
        from backend.agent.event_bus import get_event_bus, IRISStreamEvent
        from backend.ws_manager import get_websocket_manager

        _event_bus = get_event_bus()
        _ws_mgr_captured = get_websocket_manager()

        # Capture the MAIN event loop (the one driving uvicorn). All async
        # WS broadcasts must go through THIS loop, NOT a thread-pool loop.
        try:
            _main_loop = asyncio.get_running_loop()
        except RuntimeError:
            _main_loop = None

        def _fw_event_sync(payload):
            """Synchronous handler called from kernel thread-pool via EventBus.
            Queues the event; _flush_events() processes them on the main loop."""
            _event_queue.append(payload)

        # Subscribe to all task-lifecycle events that drive the UI.
        for _evt in (
            IRISStreamEvent.TASK_START,
            IRISStreamEvent.TOOL_CALL,
            IRISStreamEvent.TOOL_RESULT,
            IRISStreamEvent.TASK_PROGRESS,
            IRISStreamEvent.DOCUMENT_RENDER,
            IRISStreamEvent.TASK_DONE,
            IRISStreamEvent.TASK_FAIL,
        ):
            _event_bus.subscribe(_evt, _fw_event_sync)

        # Cleanup function to run AFTER processing to flush + unsubscribe.
        async def _flush_events():
            # Process queued events on the main async loop.
            if not _ws_mgr_captured:
                return
            while _event_queue:
                p = _event_queue.pop(0)
                try:
                    await _ws_mgr_captured.broadcast_to_session(
                        "session_iris",
                        {
                            "type": p.event.value,
                            "payload": p.data,
                            "session_id": thread_id,
                        },
                    )
                except Exception:
                    pass
            # Unsubscribe handlers
            for _evt in (
                IRISStreamEvent.TASK_START,
                IRISStreamEvent.TOOL_CALL,
                IRISStreamEvent.TOOL_RESULT,
                IRISStreamEvent.TASK_PROGRESS,
                IRISStreamEvent.DOCUMENT_RENDER,
                IRISStreamEvent.TASK_DONE,
                IRISStreamEvent.TASK_FAIL,
            ):
                _event_bus.unsubscribe(_evt, _fw_event_sync)

        _event_bus_cleanup = _flush_events

    except Exception:
        _event_bus_cleanup = None  # No cleanup needed

    # ── 5. Process the message (in thread pool — synchronous method) ───
    try:
        content, thinking, elapsed_ms = await _run_agent_kernel(
            kernel,
            request.text,
            thread_id,
            turn_id,
            request.from_voice,
        )
    except Exception as exc:
        # Categorize error: 4xx LLM-API errors are not "server" errors,
        # they mean the user config (key, model, provider) is wrong.
        err_str = str(exc)
        status_code = 500
        err_code = "internal_error"
        if "API returned 401" in err_str or "API returned 403" in err_str:
            status_code = 502  # Bad Gateway — upstream rejected our auth
            err_code = "upstream_auth_error"
        elif "API returned 404" in err_str or "API returned 400" in err_str:
            status_code = 502
            err_code = "upstream_request_error"
        elif "API returned 429" in err_str:
            status_code = 429
            err_code = "rate_limited"
        # Strip the internal "Agent kernel error:" prefix and the raw JSON blob
        # so the user sees a friendly message instead of stack-trace noise.
        user_msg = err_str
        for prefix in ("Agent kernel error: ", "Agent kernel error:"):
            if user_msg.startswith(prefix):
                user_msg = user_msg[len(prefix) :]
                break
        # Try to extract a clean message field from the JSON body.
        import json as _json

        try:
            blob_start = user_msg.find("{")
            if blob_start != -1:
                parsed = _json.loads(user_msg[blob_start:])
                if isinstance(parsed, dict) and "message" in parsed:
                    user_msg = parsed["message"]
        except Exception:
            pass
        return JSONResponse(
            status_code=status_code,
            content={
                "ok": False,
                "error": err_code,
                "message": user_msg,
            },
        )

    # ── 6. Save assistant response ──────────────────────────────────────
    add_message(
        thread_id,
        "assistant",
        content,
        thinking=thinking,
        turn_id=turn_id,
        source="rest_api",
    )

    # ── 7. Record in Immortus chain (non-blocking) ──────────────────────
    _record_to_immortus(thread_id, request.text, content, turn_id)

    # ── 8. Fire TTS in background (non-blocking) ────────────────────────
    if content:
        _ = asyncio.create_task(_fire_tts_background(content, thread_id))

    # ── 9. Notify frontend task is done via WS (if connected) ────────────
    # The REST path completes synchronously, so the frontend's task progress
    # hook never receives the task:done WS event that WS path sends.  Emit it
    # here to clear the "working" flag and enable the textarea for follow-ups.
    try:
        from backend.ws_manager import get_websocket_manager

        _ws_mgr = get_websocket_manager()
        if _ws_mgr:
            await _ws_mgr.broadcast_to_session(
                "session_iris",
                {"type": "task:done", "payload": {"outcome": "success", "thread_id": thread_id}},
            )
    except Exception:
        _lg.getLogger("irisvoice").info("[ChatREST] Could not emit task:done via WS")

    # ── 10. Flush queued task events to frontend ─────────────────────────
    if _event_bus_cleanup:
        try:
            await _event_bus_cleanup()
        except Exception:
            pass

    return ChatResponse(
        content=content,
        thinking=thinking,
        turn_id=turn_id,
        thread_id=thread_id,
        session_id=thread_id,
        model=getattr(kernel, "current_model", "") or "",
        timing_ms=elapsed_ms,
    )


# ── Thread management ──────────────────────────────────────────────────


@router.get("/chat/threads", response_model=ThreadListResponse)
async def list_threads() -> ThreadListResponse:
    """List all conversation threads, most recent first."""
    from backend.conversation_store import get_conversations

    convs = get_conversations()
    threads = [
        ThreadInfo(
            id=c["id"],
            title=c["title"],
            created_at=c["created_at"],
            updated_at=c["updated_at"],
            message_count=len(c.get("messages", [])),
            pinned=c.get("pinned", False),
        )
        for c in convs
    ]
    return ThreadListResponse(threads=threads)


@router.post("/chat/threads", response_model=CreateThreadResponse, status_code=201)
async def create_thread(body: CreateThreadRequest) -> CreateThreadResponse:
    """Create a new conversation thread with an Immortus-compatible ID."""
    from backend.agent.immortus import generate_thread_id
    from backend.conversation_store import create_conversation

    thread_id = generate_thread_id(
        prefix=(body.title or "new").strip()[:4],
    )
    conv = create_conversation(
        title=body.title,
        conv_id=thread_id,
    )
    return CreateThreadResponse(
        thread_id=thread_id,
        session_id=thread_id,
        title=conv["title"],
        created_at=conv["created_at"],
    )


@router.get("/chat/threads/{thread_id}", response_model=ThreadDetail)
async def get_thread(thread_id: str) -> ThreadDetail:
    """Get a thread's full detail including messages."""
    from backend.conversation_store import get_conversation

    conv = get_conversation(thread_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id} not found")

    # Optionally fetch Immortus chain entries (graceful if unavailable)
    immortus_chain: list[dict[str, Any]] = []
    try:
        from backend.gateway.iris_ffi import _engine

        if _engine is not None:
            # Use IrisCoreEngine's SQLite connection to query memory_chain
            import sqlite3

            conn: sqlite3.Connection = _engine._conn
            rows = conn.execute(
                "SELECT result, nbl_outcome, insight, coords_from, coords_to, "
                "created_at FROM memory_chain WHERE thread_id = ? "
                "ORDER BY chain_index DESC LIMIT 20",
                (thread_id,),
            ).fetchall()
            for row in rows:
                immortus_chain.append(
                    {
                        "result": row[0],
                        "nbl_outcome": row[1],
                        "insight": row[2],
                        "coords_from": row[3],
                        "coords_to": row[4],
                        "timestamp": row[5],
                    }
                )
    except Exception:
        logger.debug("[ChatREST] Immortus chain fetch unavailable")

    return ThreadDetail(
        thread_id=thread_id,
        title=conv["title"],
        messages=conv.get("messages", []),
        immortus_chain=immortus_chain,
    )


@router.delete("/chat/threads/{thread_id}")
async def delete_thread(thread_id: str) -> dict[str, Any]:
    """Delete a thread, its messages, and purge its Immortus chain."""
    from backend.conversation_store import delete_conversation

    deleted = delete_conversation(thread_id)

    # Purge Immortus chain (non-blocking)
    try:
        from backend.gateway.iris_ffi import ffi_immortus_chain_keep_latest

        ffi_immortus_chain_keep_latest(thread_id, 0)
    except Exception:
        pass

    return {"deleted": deleted, "thread_id": thread_id}


@router.post(
    "/chat/threads/{thread_id}/fork", response_model=ForkResponse, status_code=201
)
async def fork_thread(thread_id: str, body: ForkRequest) -> ForkResponse:
    """Fork a new thread from a specific message in the parent thread.

    Creates a new thread containing all messages up to and including the
    specified ``message_id``, then records the fork in the Immortus chain
    as a parent linkage.
    """
    from backend.agent.immortus import generate_thread_id
    from backend.conversation_store import (
        add_message,
        create_conversation,
        get_conversation,
    )

    parent = get_conversation(thread_id)
    if not parent:
        raise HTTPException(
            status_code=404,
            detail=f"Parent thread {thread_id} not found",
        )

    parent_msgs = parent.get("messages", [])
    fork_idx: Optional[int] = None
    for i, msg in enumerate(parent_msgs):
        if msg.get("id") == body.message_id or msg.get("turn_id") == body.message_id:
            fork_idx = i + 1  # include this message
            break

    if fork_idx is None:
        raise HTTPException(
            status_code=404,
            detail=f"Message {body.message_id} not found in thread {thread_id}",
        )

    # Create new thread
    new_id = generate_thread_id(
        prefix=(body.title or "fork")[:4],
    )
    new_conv = create_conversation(
        title=body.title or f"Fork of {parent['title']}",
        conv_id=new_id,
    )

    # Copy messages up to fork point into the new thread
    for msg in parent_msgs[:fork_idx]:
        add_message(
            new_id,
            msg["role"],
            msg["text"],
            turn_id=msg.get("turn_id"),
            thinking=msg.get("thinking", ""),
            source="fork",
        )

    # Record fork in Immortus chain
    try:
        from backend.gateway.iris_ffi import ffi_immortus_chain_append

        ffi_immortus_chain_append(
            thread_id=new_id,
            result="fork",
            insight=f"forked from {thread_id} at message {body.message_id}",
            coords_from=f"thread:{thread_id}",
            coords_to=f"thread:{new_id}",
        )
    except Exception:
        logger.debug("[ChatREST] Immortus fork chain_append skipped")

    return ForkResponse(
        thread_id=new_id,
        parent_thread_id=thread_id,
        forked_from_message=body.message_id,
        title=new_conv["title"],
    )

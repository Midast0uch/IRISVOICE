"""Resilient crawl transport endpoints (REQ-31, REQ-29).

Exposes three HTTP surfaces that complement the raw WebSocket so the desktop
widget can survive suspend/resume drops and flaky WS:

  GET  /api/crawl/stream/{session_id}   SSE fallback (AC3)
       - Replays missed events from Last-Event-ID (partial replay via the
         server-side SessionEventLog), then streams new events live.
       - EventSource auto-reconnects; we honor Last-Event-ID on reconnect.

  POST /api/crawl/command                Command channel (AC6)
       - body: {"job_id": "...", "command": "cancel"}
       - Routes to the JobRegistry; independent of the push channel.

  GET  /api/crawl/result/{job_id}        Background result fetch (REQ-29 AC5)
       - Returns the stored result for a completed background crawl so a
         reconnecting client need not re-run the crawl.

Both the WS handler and this SSE endpoint read the SAME SessionEventLog, so
they never diverge (single source of truth).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

from crawler.event_log import get_event_log
from crawler.job_registry import get_job_registry
from crawler.ux_map import map_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crawl", tags=["crawl-stream"])


def _sse(event_id: int, msg_type: str, payload: dict) -> str:
    """Format one Server-Sent Event with an id (for Last-Event-ID replay)."""
    data = json.dumps({"type": msg_type, **payload}, default=str)
    return f"id: {event_id}\nretry: 3000\ndata: {data}\n\n"


@router.get("/stream/{session_id}")
async def crawl_stream(session_id: str, request: Request):
    """SSE stream of crawl events for a session, with replay on reconnect."""
    log = get_event_log()

    # Last-Event-ID is sent by EventSource on auto-reconnect.
    last_id_raw = request.headers.get("Last-Event-ID")
    try:
        after_seq = int(last_id_raw) if last_id_raw else 0
    except (TypeError, ValueError):
        after_seq = 0

    async def _gen():
        # 0) If TTL eviction already dropped events this client never replayed,
        #    partial replay is insufficient — tell the client to do a full
        #    snapshot sync instead (REQ-31 edge / T23).
        if await log.consume_sync_required(session_id):
            yield _sse(0, "crawler_sync_required", {"session_id": session_id})
        # 1) Replay any events missed since last_seq (partial replay).
        for ev in await log.replay(session_id, after_seq=after_seq):
            mapping = map_event(ev.event)
            yield _sse(ev.seq, mapping.msg_type, ev.payload)
        # 2) Stream new events until the client disconnects or the job ends.
        last_seq, _, _ = await log.snapshot(session_id)
        while True:
            if await request.is_disconnected():
                return
            events = await log.replay(session_id, after_seq=last_seq)
            for ev in events:
                mapping = map_event(ev.event)
                yield _sse(ev.seq, mapping.msg_type, ev.payload)
                last_seq = ev.seq
                if ev.event == "CRAWLER_COMPLETE" or ev.event == "CRAWLER_ERROR":
                    return  # terminal event — close the stream cleanly
            await asyncio.sleep(0.25)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/command")
async def crawl_command(request: Request):
    """Command channel for an in-flight crawl job (REQ-31 AC6)."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid JSON"}, status_code=400)

    job_id = body.get("job_id")
    command = body.get("command")
    if not job_id or command != "cancel":
        return JSONResponse(
            {"ok": False, "error": "expected job_id + command='cancel'"},
            status_code=400,
        )
    registry = get_job_registry()
    cancelled = await registry.cancel(job_id)
    return JSONResponse({"ok": cancelled, "job_id": job_id})


@router.get("/result/{job_id}")
async def crawl_result(job_id: str):
    """Fetch a (possibly background) crawl result by job_id (REQ-29 AC5)."""
    registry = get_job_registry()
    job = await registry.get(job_id)
    if job is None:
        return JSONResponse({"ok": False, "error": "unknown job"}, status_code=404)
    if job.status == "running":
        return JSONResponse({"ok": True, "status": "running", "job_id": job_id})
    if job.status == "cancelled":
        return JSONResponse({"ok": True, "status": "cancelled", "job_id": job_id})
    if job.status == "error":
        return JSONResponse(
            {"ok": True, "status": "error", "error": job.error, "job_id": job_id}
        )
    return JSONResponse(
        {"ok": True, "status": "complete", "result": job.result, "job_id": job_id}
    )


@router.get("/snapshot/{session_id}")
async def crawl_snapshot(session_id: str):
    """Full state snapshot fetch (REQ-31 edge / T23).

    When TTL eviction has dropped events a client has not replayed, partial
    SSE replay is insufficient. The client calls this endpoint to receive the
    COMPLETE current crawl state (all buffered events + sync_required flag) and
    re-applies it as a full sync. This is the recovery path after a
    ``crawler_sync_required`` signal.
    """
    log = get_event_log()
    last_seq, events, sync_required = await log.snapshot(session_id)
    return JSONResponse({
        "ok": True,
        "session_id": session_id,
        "last_seq": last_seq,
        "sync_required": sync_required,
        "events": [
            {"seq": ev.seq, "type": map_event(ev.event).msg_type, "payload": ev.payload}
            for ev in events
        ],
    })

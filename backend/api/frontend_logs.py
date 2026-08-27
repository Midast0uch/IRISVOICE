"""Structured frontend log sink.

  POST /api/logs/structured   append one JSON line to .iris-logs/

This used to be a Next.js route handler at app/api/logs/structured/route.ts.
It moved here because the widget is now packaged as a STATIC export: there is
no Next.js server in the bundle, so a route handler has nowhere to run. The
behaviour is deliberately identical to the route it replaces — same file, same
JSON-line format, same 5 MB rotation to `.1`, same best-effort contract where a
logging failure never reaches the caller.

The caller (lib/logger.ts) fires and forgets with `keepalive`, so this endpoint
must be cheap and must never raise.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Relative to the backend's working directory, matching the Next route's
# process.cwd() behaviour so both write to the same place during a dev session.
LOG_DIR = Path(".iris-logs")
LOG_FILE = LOG_DIR / "frontend-structured.jsonl"
MAX_BYTES = 5 * 1024 * 1024


def _append(entry: dict[str, Any]) -> None:
    """Append one line, rotating first if the file has grown past MAX_BYTES."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if LOG_FILE.stat().st_size > MAX_BYTES:
            LOG_FILE.replace(LOG_FILE.with_suffix(".jsonl.1"))
    except FileNotFoundError:
        pass  # first write — nothing to rotate
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


@router.post("/api/logs/structured")
async def post_structured_log(request: Request) -> JSONResponse:
    """Record one structured frontend event.

    Returns 400 only for a body that is not a JSON object. Every other failure
    is logged here and reported as ok, because observability must never break
    the path it instruments.
    """
    try:
        entry = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid entry"}, status_code=400)

    if not isinstance(entry, dict):
        return JSONResponse({"error": "invalid entry"}, status_code=400)

    try:
        # The write is small and buffered by the OS; doing it inline keeps the
        # endpoint dependency-free and ordered. If it ever shows up in a
        # profile, move it to a queue rather than to a thread per request.
        _append(entry)
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        logger.warning("[frontend_logs] could not append entry: %s", exc)

    return JSONResponse({"ok": True})

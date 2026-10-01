"""Research history endpoints (spec research-memory REQ-3 AC3.1).

  GET /api/research/history       list kept research records (metadata only)
       ?conversation_id=<id>      only that conversation's records
       ?q=<text>                  only records close in meaning to the text
       ?limit=<n>                 at most n (1..200, default 50)
  GET /api/research/{document_id} one record, with its stored dashboard payload

Reads the same ``document_data`` rows ``backend/agent/research_memory.py``
writes; the dashboard tab draws the stored payload with its existing renderer.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.agent import research_memory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/research", tags=["research"])

_MAX_LIMIT = 200


# Plain `def` handlers: FastAPI runs them on its thread pool, so the store read
# and the query embedding for `q` never block the event loop.
@router.get("/history")
def research_history(
    conversation_id: Optional[str] = None, q: Optional[str] = None, limit: int = 50,
):
    """Metadata only: id, query, created_at, conversation_id, job_id, counts."""
    limit = max(1, min(int(limit), _MAX_LIMIT))
    if q and q.strip():
        records = research_memory.recall_prior_research(
            q.strip(), limit=limit, min_similarity=0.4,
        )
        items = [
            {
                "id": r["id"], "query": r.get("query", ""), "created_at": r.get("created_at", ""),
                "conversation_id": r.get("conversation_id", ""), "job_id": r.get("job_id", ""),
                "source_count": len(r.get("sources") or []), "claim_count": len(r.get("claims") or []),
            }
            for r in records
            if not conversation_id or r.get("conversation_id") == conversation_id
        ]
    else:
        items = research_memory.list_records(conversation_id=conversation_id or "", limit=limit)
    return {"ok": True, "count": len(items), "items": items}


@router.get("/{document_id}")
def research_record(document_id: str):
    """One record (claims, sources, the dashboard payload), or 404."""
    record = research_memory.load_record(document_id)
    if record is None:
        return JSONResponse({"ok": False, "error": "unknown research record"}, status_code=404)
    return {"ok": True, "record": record}

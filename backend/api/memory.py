"""Read API of the Memory surface (MEMORY-SURFACE-BUILD.md phase 0).

  GET /api/memory/overview                         counts, territories, last integrity pass
  GET /api/memory/claims?territory=&tier=&limit=   live claim cards (the exporter's landmark shape)
  GET /api/memory/claims/{id}                      one claim: evidence, edges, merge survivor, observing episodes
  GET /api/memory/threads?limit=&include_eval=     thread roots + strands + memory activity + the "outside chat" group
  GET /api/memory/strand/{id}                      one strand's corridor data (exporter session shape)
  GET /api/memory/turn/{conversation_id}/{turn_id} a turn's recalls (refs resolved) and moments
  GET /api/memory/oracle                           per-consumer state from the bar record + calibration files (no DB)
  GET /api/memory/snapshot?threads=&events=&include_eval=  the whole dashboard model (the exporter's IRIS_MEMORY shape)

Read-only by construction: every SQL statement lives in backend/memory/surface_queries.py (read-only
connections, LIMIT on every query, index-backed). The handlers are plain `def`, so FastAPI runs them on its
worker thread pool: no store read ever blocks the event loop. Nothing here is on the answer path, writes a row,
counts as a recall, or returns a message body longer than a preview. Not built yet (later phases): search,
corrections, live WebSocket taps.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from backend.memory import surface_queries as sq

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BENCH = _REPO_ROOT / "benchmarks"


def _serve(route: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> JSONResponse:
    """Run one query function; every failure has an explicit outcome and a log line with a request ref."""
    ref = uuid.uuid4().hex[:8]
    try:
        return JSONResponse(fn(*args, **kwargs))
    except sq.NotFound as exc:
        return JSONResponse({"error": "not found", "id": str(exc)}, status_code=404)
    except sq.BadRequest as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except sq.StoreUnavailable as exc:
        logger.warning("[memory_api] ref=%s route=%s store unavailable: %s", ref, route, exc)
        return JSONResponse({"error": "the memory is resting", "ref": ref}, status_code=503)
    except sqlite3.Error as exc:
        logger.warning("[memory_api] ref=%s route=%s sqlite error: %s", ref, route, exc)
        return JSONResponse({"error": "the memory is resting", "ref": ref}, status_code=503)
    except Exception:  # noqa: BLE001 - a read endpoint must answer, never raise into the server
        logger.exception("[memory_api] ref=%s route=%s failed", ref, route)
        return JSONResponse({"error": "internal error", "ref": ref}, status_code=500)


@router.get("/overview")
def memory_overview():
    return _serve("overview", sq.overview)


@router.get("/claims")
def memory_claims(territory: Optional[str] = None, tier: Optional[str] = None, limit: int = 50):
    return _serve("claims", sq.claims, territory=territory or None, tier=tier or None, limit=limit)


@router.get("/claims/{claim_id}")
def memory_claim(claim_id: str):
    return _serve("claim", sq.claim, claim_id)


@router.get("/threads")
def memory_threads(limit: int = 30, include_eval: bool = False):
    return _serve("threads", sq.threads, limit=limit, include_eval=include_eval)


@router.get("/strand/{strand_id}")
def memory_strand(strand_id: str):
    return _serve("strand", sq.strand, strand_id)


@router.get("/turn/{conversation_id}/{turn_id}")
def memory_turn(conversation_id: str, turn_id: str):
    return _serve("turn", sq.turn, conversation_id, turn_id)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        logger.warning("[memory_api] oracle file unreadable: %s: %s", path.name, exc)
        return {}


def oracle_summary() -> dict:
    """One row per consumer: the bar record (state, rows, precision, ECE on the active engine, the gap in words)
    joined to its calibration entry (oof AUROC, threshold) by the engine id the record names."""
    bar = _read_json(_BENCH / "consumer_bar_record.json")
    cal = _read_json(_BENCH / "oracle_calibration.json")
    consumers = []
    for cid, v in sorted(bar.items()):
        if not isinstance(v, dict):
            continue
        entry = ((cal.get((v.get("config") or {}).get("backend_id")) or {}).get(cid)) or {}
        oof = entry.get("oof") or {}
        consumers.append({"consumer": cid, "state": v.get("status", "shadow"), "rows": v.get("rows") or 0,
                          "auroc": oof.get("auroc"), "ece": v.get("ece"), "ece_oof": oof.get("ece"),
                          "precision": v.get("precision"), "threshold": entry.get("threshold"),
                          "gap": v.get("gap") or "", "fitted_at": entry.get("fitted_at")})
    states: dict[str, int] = {}
    for c in consumers:
        states[c["state"]] = states.get(c["state"], 0) + 1
    return {"consumers": consumers, "states": states}


@router.get("/snapshot")
def memory_snapshot(threads: int = 48, events: int = 6000, include_eval: bool = False):
    """threads <= 120 and events <= 12000: a larger value is clamped, like the other limits."""
    return _serve("snapshot", sq.snapshot, threads=threads, events=events, include_eval=include_eval)


@router.get("/oracle")
def memory_oracle():
    return _serve("oracle", oracle_summary)

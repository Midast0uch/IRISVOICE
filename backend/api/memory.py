"""Read API of the Memory surface (MEMORY-SURFACE-BUILD.md phase 0).

  GET /api/memory/overview                         counts, territories, last integrity pass
  GET /api/memory/claims?territory=&tier=&limit=   live claim cards (the exporter's landmark shape)
  GET /api/memory/claims/{id}                      one claim: evidence, edges, merge survivor, observing episodes
  GET /api/memory/threads?limit=&include_eval=     thread roots + strands + memory activity + the "outside chat" group
  GET /api/memory/strand/{id}                      one strand's corridor data (exporter session shape)
  GET /api/memory/turn/{conversation_id}/{turn_id} a turn's recalls (refs resolved) and moments
  GET /api/memory/oracle                           per-consumer state from the bar record + calibration files (no DB)
  GET /api/memory/snapshot?threads=&events=&include_eval=  the whole dashboard model (the exporter's IRIS_MEMORY shape)
  GET /api/memory/search?q=&kinds=&limit=          text search built for memory.db: ranked by the memory's own law (not a recall)

The snapshot is single-flight and kept SNAPSHOT_TTL_S: concurrent requests share one computation, and
start_snapshot_warmup() (called once the app is ready) fills the cache while nobody waits (2026-10-21: the first call
after a backend start took > 300 s on the cold hard disk, the next 1.0 s). meta.generated tells the age of a result.

Read-only by construction: every SQL statement lives in backend/memory/surface_queries.py (read-only
connections, LIMIT on every query, index-backed). The handlers are plain `def`, so FastAPI runs them on its
worker thread pool: no store read ever blocks the event loop. Nothing here is on the answer path, writes a row,
counts as a recall, or returns a message body longer than a preview. Not built yet (later phases): corrections,
live WebSocket taps.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from concurrent.futures import Future
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


# -- the snapshot cache: single-flight, short TTL, bounded ----------------------------------------
SNAPSHOT_TTL_S = 60.0              # a result is served this long, then the next request recomputes
SNAPSHOT_CACHE_MAX = 4             # parameter sets kept (the default one plus a few); the oldest goes first
SNAPSHOT_DEFAULTS = (48, 6000, False)   # threads, events, include_eval: what the surface asks for
SNAPSHOT_WARMUP_DELAY_S = 20.0     # after the app is ready, before the warm-up reads the store
SNAPSHOT_WARMUP_TURN_WAIT_S = 300.0   # the warm-up defers to a running turn this long, then goes (as the STT warm does)

_snap_lock = threading.Lock()                       # guards the two dicts below; never held while computing
_snap_cache: dict[tuple, tuple[float, dict]] = {}   # key -> (monotonic time computed, snapshot)
_snap_flight: dict[tuple, Future] = {}              # key -> the computation in progress
_snap_gate = threading.Lock()                       # one snapshot() runs at a time, whatever its parameters


def _snapshot_key(threads: int, events: int, include_eval: bool) -> tuple:
    """The store (its path and its file's mtime/size) and the CLAMPED parameters: threads=999 and threads=120 are one
    entry. The file stamp makes a changed store (a new index, a checkpoint, another file) a new key; a live WAL store
    changes its main file only at a checkpoint, so ordinary writes do not defeat the cache - the TTL bounds those."""
    path = sq.memory_db_path()
    try:
        st = Path(path).stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        stamp = (0, 0)   # missing: the computation raises StoreUnavailable and nothing is cached
    return (str(path), stamp, max(1, min(int(threads), sq.SNAPSHOT_THREADS_MAX)),
            max(1, min(int(events), sq.SNAPSHOT_EVENTS_MAX)), bool(include_eval))


def snapshot_cached(threads: int = SNAPSHOT_DEFAULTS[0], events: int = SNAPSHOT_DEFAULTS[1],
                    include_eval: bool = SNAPSHOT_DEFAULTS[2]) -> dict:
    """sq.snapshot behind a single-flight cache. The first caller of a key computes; a concurrent caller of the same
    key waits for that result (or its exception) and never starts a second computation. A failure is not cached."""
    key = _snapshot_key(threads, events, include_eval)
    with _snap_lock:
        hit = _snap_cache.get(key)
        if hit is not None and time.monotonic() - hit[0] < SNAPSHOT_TTL_S:
            return hit[1]
        flight = _snap_flight.get(key)
        leader = flight is None
        if leader:
            flight = _snap_flight[key] = Future()
    if not leader:
        return flight.result()
    try:
        with _snap_gate:
            data = sq.snapshot(threads=key[2], events=key[3], include_eval=key[4])
    except BaseException as exc:
        with _snap_lock:
            _snap_flight.pop(key, None)
        flight.set_exception(exc)
        raise
    with _snap_lock:
        _snap_cache[key] = (time.monotonic(), data)
        while len(_snap_cache) > SNAPSHOT_CACHE_MAX:
            _snap_cache.pop(min(_snap_cache, key=lambda k: _snap_cache[k][0]))
        _snap_flight.pop(key, None)
    flight.set_result(data)
    return data


@router.get("/snapshot")
def memory_snapshot(threads: int = SNAPSHOT_DEFAULTS[0], events: int = SNAPSHOT_DEFAULTS[1],
                    include_eval: bool = SNAPSHOT_DEFAULTS[2]):
    """threads <= 120 and events <= 12000: a larger value is clamped, like the other limits."""
    return _serve("snapshot", snapshot_cached, threads=threads, events=events, include_eval=include_eval)


def _turn_running() -> bool:
    """True while a user turn is in flight (IdleTracker.busy(): idle_seconds() is exactly 0 only then)."""
    try:
        from backend.core.idle_tracker import get_idle_tracker  # noqa: PLC0415
        return get_idle_tracker().idle_seconds() == 0.0
    except Exception:  # noqa: BLE001 - a probe never blocks the warm-up
        return False


def _snapshot_warmup(delay_s: float) -> None:
    """Fill the default snapshot while nobody waits. Never raises; logs its duration and its failure."""
    try:
        time.sleep(delay_s)
        deadline = time.monotonic() + SNAPSHOT_WARMUP_TURN_WAIT_S
        while _turn_running() and time.monotonic() < deadline:   # no disk work while a turn runs
            time.sleep(2.0)
        t0 = time.perf_counter()
        data = snapshot_cached()
        logger.info("[memory_api] snapshot warm-up done in %.1fs (%d events, %d landmarks)", time.perf_counter() - t0,
                    len(data.get("events", [])), len(data.get("landmarks", [])))
    except Exception as exc:  # noqa: BLE001 - a warm-up is a bonus; a failure is logged, never raised into startup
        logger.warning("[memory_api] snapshot warm-up failed (the first request computes instead): %s: %s",
                       type(exc).__name__, exc)


def start_snapshot_warmup(delay_s: float = SNAPSHOT_WARMUP_DELAY_S) -> Optional[threading.Thread]:
    """Start the one-shot warm-up thread (daemon). Off with IRIS_MEMORY_SNAPSHOT_WARMUP=0. Never raises."""
    try:
        if os.environ.get("IRIS_MEMORY_SNAPSHOT_WARMUP", "1").strip() == "0":
            logger.info("[memory_api] snapshot warm-up off (IRIS_MEMORY_SNAPSHOT_WARMUP=0)")
            return None
        t = threading.Thread(target=_snapshot_warmup, args=(delay_s,), daemon=True, name="iris-memory-snapshot-warm")
        t.start()
        return t
    except Exception as exc:  # noqa: BLE001 - startup never fails on a warm-up
        logger.warning("[memory_api] snapshot warm-up not started: %s", exc)
        return None


@router.get("/search")
def memory_search(q: str = "", kinds: Optional[str] = None, limit: int = sq.SEARCH_LIMIT_DEFAULT):
    """q: words, "phrases" and facets (sq.parse_query); kinds: comma-separated. A search is never a recall: it writes nothing."""
    return _serve("search", sq.search, q, kinds=kinds or None, limit=limit)


@router.get("/oracle")
def memory_oracle():
    return _serve("oracle", oracle_summary)

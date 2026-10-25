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
  POST /api/memory/correct {action, target, reason?}   the user's correction of a claim (confirm | wrong | forget)
  POST /api/memory/correct/undo {correction_id}        undo it, within 10 minutes, once
  GET  /api/memory/corrections?limit=              the corrections, newest first (backend/memory/corrections.py)

The snapshot is single-flight and kept SNAPSHOT_TTL_S: concurrent requests share one computation, and
start_snapshot_warmup() (called once the app is ready) fills the cache while nobody waits (2026-10-21: the first call
after a backend start took > 300 s on the cold hard disk, the next 1.0 s). meta.generated tells the age of a result.

Read-only by construction, except the corrections: every SQL statement of a read lives in
backend/memory/surface_queries.py (read-only connections, LIMIT on every query, index-backed); a correction writes
through the app's one writer (db.app_write) on the memory interface's connection, in backend/memory/corrections.py. The handlers are plain `def`, so FastAPI runs them on its
worker thread pool: no store read ever blocks the event loop. Nothing here is on the answer path, writes a row,
counts as a recall, or returns a message body longer than a preview (a correction is the one deliberate write).
Not built yet (later phases): pin and strand corrections.
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
from pydantic import BaseModel

from backend.memory import corrections
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
    except corrections.CorrectionError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status)
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


ORACLE_CURVE_MAX = 24      # calibration knots sent per consumer, evenly thinned


def _thin(knots: Any, limit: int = ORACLE_CURVE_MAX) -> list:
    """The calibration knots as [[confidence, right], ...], at most `limit` of them, evenly spaced (first and last kept)."""
    pts = [[k[0], k[1]] for k in (knots or []) if isinstance(k, (list, tuple)) and len(k) == 2
           and all(isinstance(x, (int, float)) for x in k)]
    if len(pts) <= limit:
        return pts
    return [pts[round(i * (len(pts) - 1) / (limit - 1))] for i in range(limit)]


def _bar_clauses(cid: str, bar_row: dict, entry: dict) -> list[dict]:
    """The bar as a ladder of nine clauses, in the order a reader asks them. Values come from the ACTIVE engine's
    calibration entry, the limits from agent/consumer_bar.py (the bar's own constants, never copies). met is true | false |
    null: null = waived, not applicable, or not reached (an earlier clause already fails and this one has no number)."""
    from backend.agent import consumer_bar as cb

    oof = entry.get("oof") or {}
    cls = entry.get("classes") or {}
    n_raw = entry.get("rows_distinct")
    n = int(n_raw if n_raw is not None else (bar_row.get("rows") or 0))
    a, b = cls.get("correct"), cls.get("wrong")
    have_cls = isinstance(a, int) and isinstance(b, int) and a + b > 0
    minority = min(a, b) / (a + b) if have_cls else None
    # The waiver is re-derived from the numbers with the bar's own test, as the bar does on every recompute.
    waived = bool(have_cls and a > 0 and b > 0 and minority < cb.MIN_MINORITY
                  and cb._excludes_error_rate(n, b, cb.MIN_MINORITY))
    out: list[dict] = []

    def clause(id_: str, value: Any, need: Any, passed: bool, ok: str, bad: str, missing: str) -> None:
        if value is None:     # no number: false when nothing earlier fails (it is a gap), else not reached
            unreached = any(c["met"] is False for c in out)
            out.append({"id": id_, "met": None if unreached else False, "value": None, "need": need,
                        "words": "not reached: an earlier clause fails first" if unreached else missing})
        else:
            out.append({"id": id_, "met": bool(passed), "value": value, "need": need,
                        "words": ok if passed else bad})

    def waived_clause(id_: str, value: Any, need: Any) -> None:
        out.append({"id": id_, "met": None, "value": value, "need": need,
                    "words": f"waived: errors are too rare to rank ({b} wrong of {n})"})

    clause("rows", n, cb.MIN_ROWS, n >= cb.MIN_ROWS,
           f"enough distinct rows - {n}, needs {cb.MIN_ROWS}", f"needs more distinct rows - {n}, needs {cb.MIN_ROWS}", "")
    clause("classes", min(a, b) if have_cls else None, 1, have_cls and a > 0 and b > 0,
           f"the reference holds right and wrong answers ({a} right, {b} wrong)",
           f"the reference holds one kind of answer only ({a} right, {b} wrong) - precision and ranking prove nothing",
           "the right and wrong answers are not counted yet")
    if waived:
        waived_clause("minority", round(minority, 4), cb.MIN_MINORITY)
    else:
        clause("minority", None if minority is None else round(minority, 4), cb.MIN_MINORITY,
               minority is not None and minority >= cb.MIN_MINORITY,
               f"the rarer answer is {minority or 0:.1%} of rows, needs {cb.MIN_MINORITY:.0%}",
               f"needs more of the rarer answer to learn from - it is {minority or 0:.1%} of rows, needs {cb.MIN_MINORITY:.0%}",
               "the share of the rarer answer is not measured yet")
    auroc = oof.get("auroc")
    if waived:
        waived_clause("auroc", auroc, cb.MIN_AUROC)
    else:
        clause("auroc", auroc, cb.MIN_AUROC, auroc is not None and auroc >= cb.MIN_AUROC,
               f"ranks its errors - AUROC {auroc}, needs {cb.MIN_AUROC}",
               f"needs to rank its errors better - AUROC {auroc}, needs {cb.MIN_AUROC}",
               "its error ranking (AUROC) is not measured yet")
    t, prec = entry.get("threshold"), oof.get("precision_at_t")
    clause("precision", prec if t is not None else None, cb.MIN_PRECISION, prec is not None and prec >= cb.MIN_PRECISION,
           f"precision {prec} above its cut-off, needs {cb.MIN_PRECISION:.2f}",
           f"too many wrong answers above its cut-off - precision {prec}, needs {cb.MIN_PRECISION:.2f}",
           f"no confidence cut-off reaches precision {cb.MIN_PRECISION:.2f} yet")
    wlb = oof.get("wilson_lb")
    clause("wilson", wlb if t is not None else None, cb.MIN_WILSON_LB, wlb is not None and wlb >= cb.MIN_WILSON_LB,
           f"the worst case (Wilson lower bound) holds - {wlb}, needs {cb.MIN_WILSON_LB}",
           f"the worst case (Wilson lower bound) is too low - {wlb}, needs {cb.MIN_WILSON_LB}",
           "the worst case (Wilson lower bound) is not measured yet")
    above = entry.get("rows_above")
    clause("rows_above", above if t is not None else None, cb.MIN_ROWS_ABOVE,
           above is not None and above >= cb.MIN_ROWS_ABOVE,
           f"{above} distinct rows above the cut-off, needs {cb.MIN_ROWS_ABOVE}",
           f"too few rows above the cut-off - {above}, needs {cb.MIN_ROWS_ABOVE}",
           "the rows above the cut-off are not counted yet")
    ece = oof.get("ece")
    clause("ece", ece, cb.MAX_ECE, ece is not None and ece <= cb.MAX_ECE,
           f"its confidence is honest - ECE {ece}, needs at most {cb.MAX_ECE}",
           f"its confidence is not honest enough - ECE {ece}, needs at most {cb.MAX_ECE}",
           "its calibration error (ECE) is not measured yet")
    if cid in cb.ACTING_ENFORCED:     # the acting side's own bar, for a consumer that acts on one answer
        ans, a_above = oof.get("acting_answer"), oof.get("acting_rows_above")
        a_prec, a_wlb = oof.get("acting_precision"), oof.get("acting_wilson_lb")
        known = a_above is not None and a_prec is not None and a_wlb is not None
        clause("acting", a_prec if known else None, cb.MIN_PRECISION,
               known and a_above >= cb.MIN_ACTING_ROWS_ABOVE and a_prec >= cb.MIN_PRECISION and a_wlb >= cb.MIN_WILSON_LB,
               f"its '{ans}' answer holds - precision {a_prec} on {a_above} rows",
               f"its '{ans}' answer is not safe to act on - precision {a_prec} (needs {cb.MIN_PRECISION:.2f}), "
               f"Wilson lower bound {a_wlb} (needs {cb.MIN_WILSON_LB}), {a_above} rows (needs {cb.MIN_ACTING_ROWS_ABOVE})",
               "the acting answer is not measured yet")
    else:
        out.append({"id": "acting", "met": None, "value": None, "need": None,
                    "words": "not applicable: this consumer has no acting answer under the bar"})
    return out


def _bar_history() -> dict[str, list[dict]]:
    """consumer -> [{"at", "state"}], oldest first, only the CHANGES of state (benchmarks/consumer_bar_history.jsonl)."""
    from backend.agent.consumer_bar import HISTORY_NAME, read_history_lines

    rows = sorted(read_history_lines(_BENCH / HISTORY_NAME), key=lambda r: str(r.get("at") or ""))
    out: dict[str, list[dict]] = {}
    for r in rows:
        h = out.setdefault(r["consumer"], [])
        if not h or h[-1]["state"] != r["status"]:
            h.append({"at": r.get("at"), "state": r["status"]})
    return out


def oracle_summary() -> dict:
    """One row per consumer: the bar record (state, rows, precision, ECE on the active engine, the gap in words)
    joined to its calibration entry (oof AUROC, threshold) by the engine id the record names, plus what the Oracle view
    draws: the job, whether the owner switched it on (IRIS_DECISION_ENFORCE), the bar as nine clauses, the calibration
    curve and the history of its state. Read-only: nothing here switches anything."""
    from backend.agent import decision_engine as de

    bar = _read_json(_BENCH / "consumer_bar_record.json")
    cal = _read_json(_BENCH / "oracle_calibration.json")
    history = _bar_history()
    owner = de._owner_allow_list()
    consumers = []
    for cid, v in sorted(bar.items()):
        if not isinstance(v, dict):
            continue
        entry = ((cal.get((v.get("config") or {}).get("backend_id")) or {}).get(cid)) or {}
        oof = entry.get("oof") or {}
        clauses = _bar_clauses(cid, v, entry)
        cls = entry.get("classes")
        consumers.append({"consumer": cid, "state": v.get("status", "shadow"), "rows": v.get("rows") or 0,
                          "auroc": oof.get("auroc"), "ece": v.get("ece"), "ece_oof": oof.get("ece"),
                          "precision": v.get("precision"), "threshold": entry.get("threshold"),
                          "gap": v.get("gap") or "", "fitted_at": entry.get("fitted_at"),
                          "job": de.oracle_job(cid).name, "owner_switch": cid in owner,
                          "clauses": clauses,
                          "first_missing": next((c["id"] for c in clauses if c["met"] is False), None),
                          "curve": _thin(entry.get("knots")),
                          "classes": ({"correct": cls["correct"], "wrong": cls["wrong"]}
                                      if isinstance(cls, dict) and "correct" in cls and "wrong" in cls else None),
                          "history": history.get(cid, [])})
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


class CorrectBody(BaseModel):
    """Every field optional here: a missing or wrong one is the correction's own 400, not a 422."""
    action: Optional[str] = None
    target: Optional[str] = None
    reason: Optional[str] = None


class UndoBody(BaseModel):
    correction_id: Optional[str] = None


def _store_conn():
    """The app memory connection every other writer uses (the memory interface's mycelium connection). Tests replace it."""
    from backend.agent.ontology_recall import resolve_mycelium_conn  # noqa: PLC0415 - lazy: the agent package is heavy
    from backend.memory import get_memory_interface  # noqa: PLC0415

    conn = resolve_mycelium_conn(get_memory_interface())
    if conn is None:
        raise sq.StoreUnavailable("no memory store is open")
    return conn


@router.post("/correct")
def memory_correct(body: CorrectBody):
    return _serve("correct", lambda: corrections.correct(_store_conn(), body.action, body.target, body.reason))


@router.post("/correct/undo")
def memory_correct_undo(body: UndoBody):
    return _serve("correct_undo", lambda: corrections.undo(_store_conn(), body.correction_id))


@router.get("/corrections")
def memory_corrections(limit: int = corrections.LIST_LIMIT_DEFAULT):
    return _serve("corrections", lambda: corrections.list_corrections(_store_conn(), limit))

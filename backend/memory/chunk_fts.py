"""Exact words in memory: an FTS5 index over chunk text (REQ-3, Wave 3).

Recall was meaning-only: a file path, an error string or a name was found only
if the embedding happened to place it near the query. Measured 2026-10-27:
``sqlite_master`` held no FTS or virtual table; keyword lookup was a B-tree scan
plus Python token overlap.

The index uses SQLite's own FTS5 (no new dependency, owner rule) as an EXTERNAL
CONTENT table: the text is not copied, the index points at ``context_chunks``
by rowid. Triggers keep it in step with every write, including the native
one-writer path, so there is no second writer to forget. A store that predates
the index is backfilled with one ``'rebuild'`` command on a lane at first open.

Failure is never fatal (AC4): a missing or broken index makes ``search`` return
an empty list, and the caller recalls by meaning alone. Every miss is counted.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from backend.memory.db import app_write

logger = logging.getLogger(__name__)

COUNTERS: Dict[str, int] = {
    "queries": 0,        # FTS recalls attempted
    "hits": 0,           # FTS recalls that returned at least one row
    "missing": 0,        # index absent (the store predates it or the build failed)
    "error": 0,          # MATCH/IO error - recall continued by meaning
    "backfill_started": 0,
    "backfill_done": 0,
}

# Candidate rows the keyword rank may add to the union (T11). Small on purpose:
# the exact scorer is still the judge, and the token cap is downstream.
KEYWORD_CANDIDATES = 50
RRF_K = 60               # standard reciprocal-rank constant

_TERM = re.compile(r"[A-Za-z0-9_]{2,}")


def _terms(text: str, limit: int = 12) -> List[str]:
    """Query terms for MATCH. Quoted, so FTS operators in the text are inert."""
    seen: List[str] = []
    for m in _TERM.finditer(text or ""):
        t = m.group(0).lower()
        if t not in seen:
            seen.append(t)
        if len(seen) >= limit:
            break
    return seen


def ensure_schema(conn) -> bool:
    """Create the index and its triggers when absent. False = FTS unavailable.

    Cheap on an existing store (``IF NOT EXISTS``). Never raises: a store
    without FTS must still open and recall by meaning (AC4).
    """
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS context_chunks_fts USING fts5("
            "content, content='context_chunks', content_rowid='rowid')"
        )
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS context_chunks_fts_ai
            AFTER INSERT ON context_chunks BEGIN
                INSERT INTO context_chunks_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS context_chunks_fts_ad
            AFTER DELETE ON context_chunks BEGIN
                INSERT INTO context_chunks_fts(context_chunks_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
            END;
            CREATE TRIGGER IF NOT EXISTS context_chunks_fts_au
            AFTER UPDATE OF content ON context_chunks BEGIN
                INSERT INTO context_chunks_fts(context_chunks_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
                INSERT INTO context_chunks_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END;
            """
        )
        return True
    except Exception as exc:  # noqa: BLE001 - a broken FTS must not block recall
        logger.warning("[chunk_fts] schema unavailable: %s", exc)
        return False


def counts(conn) -> tuple[int, int]:
    """(indexed rows, chunk rows). Never raises; (-1, -1) on failure.

    ``SELECT count(*) FROM context_chunks_fts`` is served by the CONTENT table
    for an external-content table, so it reports every chunk even when the
    index is EMPTY (measured 2026-10-27: a brand-new index read as 146,973,
    which would have told the boot path "no backfill needed" forever). The
    ``_docsize`` shadow table holds one row per INDEXED document - that is the
    number that decides whether a backfill is needed.
    """
    try:
        return (
            int(conn.execute(
                "SELECT count(*) FROM context_chunks_fts_docsize").fetchone()[0]),
            int(conn.execute("SELECT count(*) FROM context_chunks").fetchone()[0]),
        )
    except Exception:
        return -1, -1


def backfill(conn) -> int:
    """Fill the index from the content table with ONE rebuild command.

    Runs on a lane at first open. The command is transactional: an interrupted
    rebuild leaves the index empty, and the next open tries again.
    """
    COUNTERS["backfill_started"] += 1
    try:
        from backend.memory.db import app_flush

        app_write(conn, "INSERT INTO context_chunks_fts(context_chunks_fts) VALUES('rebuild')")
        # The rebuild is queued on the one writer: read it back only after it
        # lands, or the count reports the index BEFORE the rebuild.
        drained = app_flush(60.0)
        indexed, total = counts(conn) if drained else (-1, -1)
        COUNTERS["backfill_done"] += 1
        logger.info("[chunk_fts] backfilled rows=%d of %d drained=%s", indexed, total, drained)
        return max(indexed, 0)
    except Exception as exc:  # noqa: BLE001 - recall stays meaning-only
        COUNTERS["error"] += 1
        logger.warning("[chunk_fts] backfill failed (recall stays meaning-only): %s", exc)
        return 0


def search(conn, query: str, *, session_id: Optional[str] = None,
           chunk_types: Optional[List[str]] = None, zones: Optional[List[str]] = None,
           limit: int = KEYWORD_CANDIDATES) -> List[int]:
    """Rowids ranked by FTS5 bm25 within the same filter. [] when unavailable."""
    terms = _terms(query)
    if not terms:
        return []
    COUNTERS["queries"] += 1
    match = " OR ".join('"%s"' % t for t in terms)
    sql = [
        "SELECT context_chunks_fts.rowid FROM context_chunks_fts",
        "JOIN context_chunks ON context_chunks.rowid = context_chunks_fts.rowid",
        "WHERE context_chunks_fts MATCH ?",
    ]
    params: List[object] = [match]
    # REQ-4 AC2: a folded near-duplicate is not a candidate. The probe keeps a
    # store that predates the column working (meaning only, no error counted).
    try:
        if "folded_into" in {r[1] for r in conn.execute("PRAGMA table_info(context_chunks)")}:
            sql.append("AND context_chunks.folded_into IS NULL")
    except Exception:  # noqa: BLE001 - the filter is an optimisation, not a gate
        pass
    if session_id:
        sql.append("AND context_chunks.session_id = ?")
        params.append(session_id)
    if chunk_types:
        sql.append("AND context_chunks.chunk_type IN (%s)" % ",".join("?" * len(chunk_types)))
        params.extend(chunk_types)
    if zones:
        sql.append("AND context_chunks.zone IN (%s)" % ",".join("?" * len(zones)))
        params.extend(zones)
    sql.append("ORDER BY bm25(context_chunks_fts) LIMIT ?")
    params.append(int(limit))
    try:
        rows = [int(r[0]) for r in conn.execute(" ".join(sql), params).fetchall()]
    except Exception as exc:  # noqa: BLE001 - AC4: meaning only, counted
        COUNTERS["missing" if "no such table" in str(exc).lower() else "error"] += 1
        logger.debug("[chunk_fts] keyword recall skipped: %s", exc)
        return []
    if rows:
        COUNTERS["hits"] += 1
    return rows


def fuse_by_rank(meaning: List[int], keyword: List[int], k: int = RRF_K) -> List[int]:
    """Reciprocal rank fusion of the two candidate lists (AC2).

    Fuses RANK, never raw score: bm25 and cosine are not comparable. The result
    is the union ordered by fused rank; the caller still scores every row
    exactly, so this changes WHICH rows are considered, not how they rank.
    """
    if not keyword:
        return list(meaning)
    if not meaning:
        return list(keyword)
    score: Dict[int, float] = {}
    for rows in (meaning, keyword):
        for rank, rid in enumerate(rows, 1):
            score[rid] = score.get(rid, 0.0) + 1.0 / (k + rank)
    return sorted(score, key=score.get, reverse=True)

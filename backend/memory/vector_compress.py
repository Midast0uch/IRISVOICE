"""Fill the compact recall forms of stored chunks (specs/memory-recall-reach REQ-4 AC1).

Every chunk already written carries a 4,096-byte float vector. This pass reads
it once and writes the 128-byte fingerprint and the 1,024-byte int8 code
(``backend/memory/vector_quant.py``). Chunks written after this change get the
forms at insert, so the pass only ever sees older rows.

Bounded and resumable by rowid, on the ``memory_vectors`` lane, writes through
``db.app_write`` only. ``drop`` removes the float for a chunk type - call it
only after ``evals/memory_bench.py`` showed int8 keeps recall@10 within 0.02 of
float for that type (the AC1 condition). The fingerprint is left untouched,
because it is the sign pattern and int8 does not change a sign.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable, Optional

from backend.memory import vector_quant
from backend.memory.db import app_flush, app_write

logger = logging.getLogger(__name__)

COMPRESS_LANE = "memory_vectors"
DEFAULT_SCAN_ROWS = 20_000
_UPDATE_EVERY = 2_000


def ensure_schema(conn) -> None:
    """Add the three columns if this store predates them. Idempotent, never raises.

    ``EpisodicStore`` runs the same ALTERs; a script that opens the store without
    constructing one still needs them.
    """
    cols = {
        "vec_fp": "BLOB",
        "vec_i8": "BLOB",
        "vec_scale": "REAL",
    }
    try:
        have = {row[1] for row in conn.execute("PRAGMA table_info(context_chunks)").fetchall()}
    except Exception:
        return
    for col, decl in cols.items():
        if col in have:
            continue
        try:
            app_write(conn, f"ALTER TABLE context_chunks ADD COLUMN {col} {decl}")
        except Exception as exc:  # noqa: BLE001 - a second writer may have added it
            logger.debug("[vector_compress] ALTER %s skipped: %r", col, exc)
    try:
        conn.commit()
    except Exception:
        pass


def compress_into(box: dict, conn, after: int, scan_rows: int = DEFAULT_SCAN_ROWS,
                  dim: int = vector_quant.DIM, drop: Optional[Iterable[str]] = None,
                  dry_run: bool = False) -> None:
    """One bounded pass. Result goes into ``box["result"]``; never raises."""
    t0 = time.perf_counter()
    result = {"scanned": 0, "compressed": 0, "skipped": 0, "failed": 0,
              "dropped": 0, "after_rowid": int(after), "done": False}
    try:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT rowid, embedding FROM context_chunks "
            "WHERE rowid > ? AND embedding IS NOT NULL AND vec_fp IS NULL "
            "ORDER BY rowid LIMIT ?",
            (int(after), int(scan_rows)),
        ).fetchall()
        result["scanned"] = len(rows)
        batch = []
        for rid, blob in rows:
            vec = vector_quant.float_of(blob)
            if vec is None or len(vec) != dim:
                result["skipped"] += 1
                continue
            fp, i8, scale = vector_quant.compress(vec)
            if fp is None or i8 is None:
                result["failed"] += 1
                continue
            batch.append((fp, i8, scale, int(rid)))
            if len(batch) >= _UPDATE_EVERY:
                if not dry_run:
                    _write(conn, batch)
                result["compressed"] += len(batch)
                batch = []
        if batch:
            if not dry_run:
                _write(conn, batch)
            result["compressed"] += len(batch)
        if rows:
            result["after_rowid"] = int(rows[-1][0])
        else:
            result["done"] = True

        if drop:
            types = [t for t in drop if t]
            if types:
                marks = ",".join("?" * len(types))
                result["dropped"] = int(conn.execute(
                    f"SELECT count(*) FROM context_chunks WHERE chunk_type IN ({marks}) "
                    "AND embedding IS NOT NULL AND vec_i8 IS NOT NULL", types).fetchone()[0])
                if not dry_run:
                    app_write(
                        conn,
                        f"UPDATE context_chunks SET embedding = NULL "
                        f"WHERE chunk_type IN ({marks}) AND vec_i8 IS NOT NULL",
                        types,
                    )
                app_flush(120.0)
                logger.info("[vector_compress] float dropped types=%s rows=%d dry_run=%s",
                            types, result["dropped"], dry_run)
    except Exception as exc:  # noqa: BLE001 - the CLI reports it
        logger.warning("[vector_compress] pass failed after=%s: %r", after, exc)
        result["error"] = repr(exc)
    result["elapsed_s"] = round(time.perf_counter() - t0, 2)
    box["result"] = result


def _write(conn, batch) -> None:
    """One app-store writer (never a second connection writing a row).

    ``executemany`` on the script's own connection was the first version and it
    silently lost the whole sweep: the writes sat in an uncommitted transaction
    while ``app_write`` queued the drop on the native writer - two writers, and
    neither one durably wrote. ``app_write`` per row + a flush keeps the single
    writer contract.
    """
    for fp, i8, scale, rid in batch:
        app_write(
            conn,
            "UPDATE context_chunks SET vec_fp = ?, vec_i8 = ?, vec_scale = ? WHERE rowid = ?",
            (fp, i8, scale, rid),
        )
    app_flush(30.0)


def coverage(conn) -> dict:
    """What store size the compact forms buy. Read-only; never raises."""
    try:
        row = conn.execute(
            "SELECT count(*), "
            "SUM(CASE WHEN vec_i8 IS NOT NULL THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN embedding IS NOT NULL THEN 1 ELSE 0 END), "
            "COALESCE(SUM(length(embedding)), 0), "
            "COALESCE(SUM(length(vec_i8)), 0), "
            "COALESCE(SUM(CASE WHEN vec_fp IS NOT NULL THEN length(vec_fp) ELSE 0 END), 0) "
            "FROM context_chunks").fetchone()
        total, compact, floats, float_bytes, i8_bytes, fp_bytes = (int(x or 0) for x in row)
    except Exception:
        return {}
    types = {}
    try:
        for ctype, n, fbytes, ibytes in conn.execute(
                "SELECT chunk_type, count(*), COALESCE(SUM(length(embedding)), 0), "
                "COALESCE(SUM(length(vec_i8)), 0) FROM context_chunks GROUP BY chunk_type").fetchall():
            types[ctype or ""] = {
                "rows": int(n),
                "float_b": int(fbytes),
                "int8_b": int(ibytes),
                "bytes_per_row": round((int(fbytes) + int(ibytes)) / max(int(n), 1), 1),
            }
    except Exception:
        types = {}
    return {
        "rows": total,
        "compact_rows": compact,
        "float_rows": floats,
        "float_bytes": float_bytes,
        "int8_bytes": i8_bytes,
        "fingerprint_bytes": fp_bytes,
        "bytes_per_row_vectors": round((float_bytes + i8_bytes + fp_bytes) / max(total, 1), 1),
        "by_type": types,
    }

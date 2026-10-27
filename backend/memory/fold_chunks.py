"""Fold near-duplicate chunks of one strand (specs/memory-recall-reach REQ-4 AC2).

The insert path already refuses a chunk that is >= 0.92 cosine from one of the
newest 50 of its (session, chunk_type) - ``_FRAG_DEDUP_THRESHOLD``. That guard
came late: rows written before it (and re-ingested documents) carry the same
content many times, and every copy is scanned, scored and shipped as a candidate
forever. This pass finds those copies and folds them: ONE canonical row stays
recallable, the others keep their text and get ``folded_into = <canonical id>``
- a reference, not a deletion, so a correction can put a folded row back
(``unfold``) and the surface can count what is folded.

The compression arm of the one operator: compress where outcomes agree. A group
is one strand's chunks of one type in one Kyudo zone - the outcome class. The
fold never crosses zones and never touches a pinned chunk (a pin link with
target_type 'chunk'; no such target exists today, the guard is ready for one).

Bounded: one pass folds at most ``scan_groups`` strand groups, on the
``memory_integrity`` lane, writes through ``app_write`` only. Resumable by group
key (session, type, zone) - groups are stable, old strands do not change.
"""
from __future__ import annotations

import logging
from typing import Iterable, List, Optional, Tuple

from backend.memory import vector_quant
from backend.memory.db import app_flush, app_write

logger = logging.getLogger(__name__)

FOLD_LANE = "memory_integrity"
FOLD_THRESHOLD = 0.92          # the existing _FRAG_DEDUP_THRESHOLD
DEFAULT_SCAN_GROUPS = 25
_BLOCK = 512                  # rows per pairwise block (block x n floats)


def ensure_schema(conn) -> None:
    """Add ``folded_into`` if this store predates it. Idempotent, never raises."""
    try:
        have = {row[1] for row in conn.execute("PRAGMA table_info(context_chunks)").fetchall()}
    except Exception:
        return
    if "folded_into" in have:
        return
    try:
        app_write(conn, "ALTER TABLE context_chunks ADD COLUMN folded_into TEXT")
        app_flush(30.0)
        logger.info("[fold_chunks] context_chunks: added folded_into")
    except Exception as exc:  # noqa: BLE001 - a second writer may have added it
        logger.debug("[fold_chunks] ALTER folded_into skipped: %r", exc)


def pinned_chunk_ids(conn) -> set:
    """Chunk ids a pin references. A pinned chunk is never folded (AC2)."""
    try:
        return {
            str(r[0]) for r in conn.execute(
                "SELECT target_id FROM mycelium_pin_links "
                "WHERE target_type IN ('chunk', 'context_chunk')").fetchall()
        }
    except Exception:
        return set()


def _groups(conn) -> List[Tuple[str, str, str, int]]:
    """(session, type, zone, rows) with more than one unfoldable row, ordered.

    A NULL session_id sorts as "" - the same key _load_group matches.
    """
    rows = conn.execute(
        "SELECT session_id, chunk_type, zone, count(*) FROM context_chunks "
        "WHERE folded_into IS NULL GROUP BY session_id, chunk_type, zone HAVING count(*) > 1 "
        "ORDER BY session_id, chunk_type, zone").fetchall()
    return [((r[0] or ""), (r[1] or ""), (r[2] or ""), int(r[3])) for r in rows]


def _load_group(conn, key: Tuple[str, str, str]) -> List[Tuple]:
    sid, ctype, zone = key
    session_sql = "session_id IS NULL" if sid == "" else "session_id = ?"
    params: List[object] = [] if sid == "" else [sid]
    params += [ctype, zone]
    return conn.execute(
        f"SELECT rowid, id, retrieval_count, vec_i8, vec_scale FROM context_chunks "
        f"WHERE {session_sql} AND chunk_type = ? AND zone = ? AND folded_into IS NULL "
        f"ORDER BY rowid",
        params,
    ).fetchall()


def _components(rows: List[Tuple], threshold: float) -> List[List[int]]:
    """Union-find over pairs with cosine >= threshold. Returns index groups."""
    import numpy as np

    vecs = []
    for _rid, _id, _rc, code, scale in rows:
        v = vector_quant.decompress(code, scale)
        if v is None or not len(v):
            v = np.zeros(vector_quant.DIM, dtype=np.float32)
        vecs.append(v)
    mat = (np.stack(vecs).astype(np.float32) if vecs
           else np.zeros((0, vector_quant.DIM), np.float32))
    mat /= np.maximum(np.linalg.norm(mat, axis=1, keepdims=True), 1e-9)
    n = len(rows)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for start in range(0, n, _BLOCK):
        sims = mat[start:start + _BLOCK] @ mat.T    # (block, n)
        ii, jj = np.nonzero(sims >= threshold)
        for a, b in zip(ii.tolist(), jj.tolist()):
            i, j = start + a, b
            if i != j:
                union(i, j)
    seen = {}
    for i in range(n):
        seen.setdefault(find(i), []).append(i)
    return [idx for idx in seen.values() if len(idx) > 1]


def fold_pass(box: dict, conn, after_key: Optional[Iterable] = None,
              scan_groups: int = DEFAULT_SCAN_GROUPS, threshold: float = FOLD_THRESHOLD,
              dry_run: bool = False) -> None:
    """One bounded pass. Result goes into ``box["result"]``; never raises."""
    result = {"groups_scanned": 0, "groups_folded": 0, "rows_folded": 0,
              "after_key": None, "done": False}
    try:
        ensure_schema(conn)
        after = tuple(after_key) if after_key else None
        pinned = pinned_chunk_ids(conn)
        todo = [g[:3] for g in _groups(conn) if after is None or g[:3] > after]
        if not todo:
            result["done"] = True
            box["result"] = result
            return
        batch = todo[: int(scan_groups)]
        for key in batch:
            result["groups_scanned"] += 1
            rows = [r for r in _load_group(conn, key) if r[1] not in pinned]
            if len(rows) < 2:
                continue
            folded_here = 0
            for idx in _components(rows, threshold):
                # canonical: the most-retrieved row; tie -> the oldest (lowest rowid)
                best = max(idx, key=lambda i: (int(rows[i][2] or 0), -int(rows[i][0])))
                canonical = rows[best][1]
                for i in idx:
                    if i == best:
                        continue
                    if not dry_run:
                        app_write(
                            conn,
                            "UPDATE context_chunks SET folded_into = ? "
                            "WHERE id = ? AND folded_into IS NULL",
                            (canonical, rows[i][1]),
                        )
                    folded_here += 1
            if folded_here and not dry_run:
                app_flush(60.0)
            if folded_here:
                result["groups_folded"] += 1
                result["rows_folded"] += folded_here
                logger.info("[fold_chunks] group=%s folded=%d", key, folded_here)
        result["after_key"] = list(batch[-1])
        last = batch[-1]
        result["done"] = not any(g[:3] > last for g in _groups(conn))
    except Exception as exc:  # noqa: BLE001 - the CLI reports it
        logger.warning("[fold_chunks] pass failed: %r", exc)
        result["error"] = repr(exc)
    box["result"] = result


def unfold(conn, canonical_id: str) -> int:
    """Put folded rows back (a correction's undo path). Returns rows restored."""
    try:
        before = int(conn.execute(
            "SELECT count(*) FROM context_chunks WHERE folded_into = ?", (canonical_id,)).fetchone()[0])
        app_write(conn, "UPDATE context_chunks SET folded_into = NULL WHERE folded_into = ?",
                  (canonical_id,))
        app_flush(30.0)
        return before
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fold_chunks] unfold failed: %r", exc)
        return 0


def counts(conn) -> dict:
    """Fold state for the Memory surface and the bench. Read-only; never raises."""
    try:
        folded, groups = conn.execute(
            "SELECT count(*), count(DISTINCT folded_into) FROM context_chunks "
            "WHERE folded_into IS NOT NULL").fetchone()
        return {"rows": int(folded or 0), "groups": int(groups or 0)}
    except Exception:
        return {"rows": 0, "groups": 0}

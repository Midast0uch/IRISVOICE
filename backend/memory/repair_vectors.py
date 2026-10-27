"""Repair vectors whose label says a model made them but a fallback did (REQ-2 AC3).

Backfilled 2026-10-27 by Wave 2 of specs/memory-recall-reach. The hash fallback
writes a sparse vector (one bucket per token), so a fallback vector has many
components that are exactly 0; a real 1024-d model vector almost never does.
Measured on the live store: 374 of 3,966 sampled ``lfm25-emb-350m`` chunk vectors
(9.4%) were more than half exact zeros, 14,428 rows in total.

One pass is BOUNDED (``scan_rows`` rows inspected) and RESUMABLE (it reports the
last rowid it scanned). Each pass re-embeds the suspects it finds:

  * the model answers  -> the row keeps its model label and gets a real vector;
  * the model fails    -> the row is RELABELLED with the fallback backend, so
    recall excludes it until a later pass re-embeds it (AC1/AC3).

Writes go through ``db.app_write`` only (AC4). The pass runs on the
``memory_repair`` lane so it never competes with the answer path, and it updates
the in-process fingerprint index for the rows it changed - otherwise
``recall_reach.refresh`` would keep the old (wrong) fingerprint for the life of
the process.
"""
from __future__ import annotations

import logging
import struct
from typing import Dict, List

from backend.memory.db import app_write
from backend.memory.embedding import BACKEND_HASH, BACKEND_LFM

logger = logging.getLogger(__name__)

REPAIR_LANE = "memory_repair"
DEFAULT_SCAN_ROWS = 2_000      # rows inspected per pass (blob reads only)
ZERO_SHARE = 0.5               # > this share of exact zeros = the hash signature


def _pack(vec: List[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def is_suspect(blob: bytes, dim: int = 1024) -> bool:
    """True when the stored vector carries the hash fallback's zero signature."""
    import numpy as np

    if not blob or len(blob) % 4:
        return False
    vec = np.frombuffer(blob, dtype="<f4")
    if vec.size != dim:
        return False
    return int((vec == 0).sum()) > vec.size * ZERO_SHARE


def repair_pass(
    conn,
    svc,
    store_path: str,
    after_rowid: int = 0,
    *,
    scan_rows: int = DEFAULT_SCAN_ROWS,
    backend: str = BACKEND_LFM,
    dim: int = 1024,
    dry_run: bool = False,
) -> Dict[str, object]:
    """Inspect one bounded batch of rows and repair the mislabelled ones.

    Returns ``{"scanned", "suspect", "repaired", "relabelled", "failed",
    "after_rowid", "done"}``. ``done`` is True when the store has no rows left
    above ``after_rowid`` - the caller then resets the watermark to 0 for a new
    sweep (a later pass may be able to re-embed a row that was only relabelled).
    """
    stats: Dict[str, object] = {
        "scanned": 0, "suspect": 0, "repaired": 0, "relabelled": 0,
        "unresolved": 0, "failed": 0, "after_rowid": after_rowid, "done": False,
    }
    # A row relabelled on an earlier pass is HASH-labelled and must be retried
    # on a later sweep (AC3: "until re-embedded"). Only 16 rows carried the hash
    # label on 2026-10-27, so including them costs almost nothing.
    rows = conn.execute(
        "SELECT rowid, embedding_backend, embedding FROM context_chunks "
        "WHERE rowid > ? AND embedding IS NOT NULL AND embedding_backend IN (?, ?) "
        "ORDER BY rowid LIMIT ?",
        (after_rowid, backend, BACKEND_HASH, scan_rows),
    ).fetchall()
    if not rows:
        stats["done"] = True
        return stats
    stats["scanned"] = len(rows)
    stats["after_rowid"] = rows[-1][0]
    suspects = [(rid, label) for rid, label, blob in rows if is_suspect(blob, dim)]
    stats["suspect"] = len(suspects)
    if not suspects:
        return stats

    contents: Dict[int, str] = {}
    for i in range(0, len(suspects), 400):
        part = [rid for rid, _ in suspects[i:i + 400]]
        contents.update(conn.execute(
            "SELECT rowid, content FROM context_chunks WHERE rowid IN (%s)"
            % ",".join("?" * len(part)),
            part,
        ).fetchall())

    changed: List[int] = []
    for rid, stored_label in suspects:
        text = contents.get(rid)
        if not text or not text.strip():
            continue
        try:
            meta = svc.encode_with_meta(text)
        except Exception as exc:  # noqa: BLE001 - one row never stops the pass
            stats["failed"] += 1
            logger.warning("[repair_vectors] row %s could not be re-embedded: %r", rid, exc)
            continue
        if meta.backend != backend and stored_label == BACKEND_HASH:
            # Already relabelled; nothing to write until the model answers.
            stats["unresolved"] += 1
            continue
        labelled = meta.backend
        if not dry_run:
            app_write(
                conn,
                "UPDATE context_chunks SET embedding = ?, embedding_backend = ? "
                "WHERE rowid = ?",
                (_pack(meta.vector), labelled, rid),
            )
        changed.append(rid)
        if labelled == backend:
            stats["repaired"] += 1
        else:
            stats["relabelled"] += 1

    if changed and not dry_run:
        try:
            from backend.memory import recall_reach

            recall_reach.update_if_indexed(store_path, conn, changed)
        except Exception as exc:  # noqa: BLE001 - the index is a cache, never a blocker
            logger.warning("[repair_vectors] fingerprint update skipped: %r", exc)
    return stats


def repair_into(
    box: Dict[str, object],
    conn,
    svc,
    store_path: str,
    after_rowid: int,
    **kwargs,
) -> None:
    """Lane entry point: put the pass result in ``box['result']`` (or ``box['error']``)."""
    try:
        box["result"] = repair_pass(conn, svc, store_path, after_rowid, **kwargs)
    except Exception as exc:  # noqa: BLE001 - the lane would swallow it; keep the reason
        box["error"] = repr(exc)

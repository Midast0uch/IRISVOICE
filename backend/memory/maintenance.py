"""The ONE compression pass for the app store (REQ-4 / REQ-5 AC2).

Order is the design, not an implementation detail:

  1. measure  - what each zone holds, how many bytes are dead
  2. forget   - the Kyudo law (decay + per-zone budget), bounded per pass
  3. reclaim  - VACUUM, only when explicitly allowed (it needs the file alone)
  4. report   - the before/after numbers, and MEMORY_PRUNED per prune

Encoding steps (zlib on content, 4-bit vectors) are NOT here yet: each needs its
own measurement first, and a pass that encodes before it knows the loss is how a
memory quietly stops recalling. `chunk_decay.decay_pass` is the only forgetting
mechanism called, so the trust law stays the single judge.

Never a scheduler: the caller decides when. `MemoryInterface` already runs
maintenance every 5 completed tasks; this rides that cadence.
"""
from __future__ import annotations

import logging

from backend.memory import chunk_decay

logger = logging.getLogger(__name__)

# Below this much dead space a VACUUM costs more than it returns.
VACUUM_MIN_FREE_BYTES = 8 * 1024 * 1024


def measure(conn) -> dict:
    """Rows and vector+text bytes per zone, plus dead space (never raises)."""
    zones = chunk_decay.zone_usage(conn)
    try:
        page = int(conn.execute("PRAGMA page_size").fetchone()[0] or 0)
        pages = int(conn.execute("PRAGMA page_count").fetchone()[0] or 0)
        free = int(conn.execute("PRAGMA freelist_count").fetchone()[0] or 0)
    except Exception:  # noqa: BLE001 - measurement is not worth a failed turn
        page = pages = free = 0
    return {
        "zones": zones,
        "file_bytes": page * pages,
        "free_bytes": page * free,
        "budget": {z: list(b) for z, b in chunk_decay.ZONE_BUDGET.items()},
        "over_budget": [
            z for z, u in zones.items()
            if z in chunk_decay.ZONE_BUDGET and (
                u["rows"] > chunk_decay.ZONE_BUDGET[z][0]
                or u["bytes"] > chunk_decay.ZONE_BUDGET[z][1])
        ],
    }


def reclaim(conn, *, dry_run: bool = False) -> dict:
    """Return dead pages to the filesystem. Needs the store to itself."""
    before = measure(conn)
    free = before["free_bytes"]
    if dry_run:
        return {"vacuumed": False, "free_bytes": free, "reason": "dry_run"}
    if free < VACUUM_MIN_FREE_BYTES:
        return {"vacuumed": False, "free_bytes": free, "reason": "below_minimum"}
    try:
        conn.execute("VACUUM")
    except Exception as exc:  # noqa: BLE001 - a busy store just keeps the pages
        logger.warning("[maintenance] VACUUM refused: %r", exc)
        return {"vacuumed": False, "free_bytes": free, "reason": repr(exc)}
    after = measure(conn)
    return {"vacuumed": True, "free_bytes": free,
            "file_bytes_before": before["file_bytes"], "file_bytes_after": after["file_bytes"]}


def maintain(conn, *, dry_run: bool = False, vacuum: bool = False) -> dict:
    """Run the pass in order. Returns the report; never raises."""
    report: dict = {"before": {}, "decay": {}, "reclaim": {}, "after": {}, "ok": False}
    try:
        report["before"] = measure(conn)
        box: dict = {}
        chunk_decay.decay_pass(box, conn, dry_run=dry_run)
        report["decay"] = box.get("result") or {}
        # REQ-9 AC7: file text is a cache. The filesystem holds the truth while
        # the hash matches, so file chunks are evicted to the budget and rebuilt
        # on demand (file_ingest.ensure) instead of competing with conversation.
        if not dry_run:
            try:
                from backend.memory import file_ingest  # noqa: PLC0415

                report["files_evicted"] = file_ingest.prune_to_budget(conn)
            except Exception as _f_exc:  # noqa: BLE001
                report["files_evicted"] = 0
                logger.debug("[maintenance] file eviction skipped: %r", _f_exc)
        if vacuum:
            report["reclaim"] = reclaim(conn, dry_run=dry_run)
        report["after"] = measure(conn)
        report["ok"] = True
        logger.info(
            "[maintenance] dry_run=%s pruned=%s zones_over=%s free_before=%.1fMB",
            dry_run, report["decay"].get("pruned"),
            report["before"].get("over_budget"),
            report["before"].get("free_bytes", 0) / 1024 ** 2,
        )
    except Exception as exc:  # noqa: BLE001 - maintenance never blocks a turn
        report["error"] = repr(exc)
        logger.warning("[maintenance] pass failed: %r", exc)
    return report


if __name__ == "__main__":  # manual run: python -m backend.memory.maintenance
    import argparse
    import sys

    sys.path.insert(0, r"C:\dev\IRISVOICE")
    from backend.memory.episodic import EpisodicStore

    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=r"D:\IRIS\store\memory.db")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--vacuum", action="store_true")
    args = ap.parse_args()
    _store = EpisodicStore(db_path=args.db, biometric_key=b"\0" * 32)
    _rep = maintain(_store.db, dry_run=args.dry_run, vacuum=args.vacuum)
    import json

    print(json.dumps(_rep, indent=2, default=str))

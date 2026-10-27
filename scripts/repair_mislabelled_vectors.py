"""Repair vectors labelled with a backend that did not make them (REQ-2 AC3).

    python scripts/repair_mislabelled_vectors.py --passes 3 --dry-run
    python scripts/repair_mislabelled_vectors.py --all
    python scripts/repair_mislabelled_vectors.py --restart --passes 50

Each pass inspects a bounded batch of rows in rowid order, finds the vectors
that carry the hash fallback's zero signature (more than half the components
exactly 0), and re-embeds them on the ``memory_repair`` lane. A row the model
now answers keeps its model label; a row it still cannot answer is RELABELLED
with the fallback backend so recall excludes it (never a model label on a
vector the model did not make). Writes go through ``db.app_write`` only.

Resumable: the watermark and the running totals live beside the store
(``repair_mislabelled_vectors.state.json``). A new rowid above the watermark is
picked up by the next run; ``--restart`` sweeps the whole table again (use it
after the embedding sidecar has been down for a long time).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# httpx sends 127.0.0.1 through an exported HTTP_PROXY (PROGRESS, environment
# hazards): every local embedding call then fails and the whole pass looks like
# "the model is down".
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._app_store import app_store_path  # noqa: E402
from backend.memory.db import open_encrypted_memory  # noqa: E402
from backend.memory.embedding import get_embedding_service  # noqa: E402
from backend.memory.repair_vectors import (  # noqa: E402
    DEFAULT_SCAN_ROWS,
    REPAIR_LANE,
    repair_into,
)
from backend.utils.durability_queue import lane  # noqa: E402

STATE_NAME = "repair_mislabelled_vectors.state.json"


def _state_path(store_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(store_path)), STATE_NAME)


def _load(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--passes", type=int, default=1, help="bounded passes (default 1)")
    ap.add_argument("--all", action="store_true", help="passes until one full sweep ends")
    ap.add_argument("--scan-rows", type=int, default=DEFAULT_SCAN_ROWS)
    ap.add_argument("--after-rowid", type=int, default=0,
                    help="start above this rowid instead of the saved watermark")
    ap.add_argument("--restart", action="store_true", help="ignore the saved watermark")
    ap.add_argument("--dry-run", action="store_true", help="report, write nothing")
    args = ap.parse_args()

    store_path = app_store_path()
    state_path = _state_path(store_path)
    state = {} if args.restart else _load(state_path)
    after = 0 if args.restart else int(state.get("after_rowid", 0) or 0)
    if args.after_rowid:
        after = args.after_rowid

    svc = get_embedding_service()
    conn = open_encrypted_memory(store_path, b"")
    mem_lane = lane(REPAIR_LANE)

    print(f"[repair] store={store_path}")
    print(f"[repair] state={state_path} after_rowid={after} dry_run={args.dry_run}")

    passes = 0
    while True:
        box: dict = {}
        ok = mem_lane.submit(
            "repair-pass", repair_into, box, conn, svc, store_path, after,
            scan_rows=args.scan_rows, dim=svc.EMBEDDING_DIM, dry_run=args.dry_run,
        )
        if not ok:
            print("[repair] lane refused the pass (queue full)", file=sys.stderr)
            return 2
        mem_lane.flush(timeout=1800)
        if "error" in box:
            print(f"[repair] pass failed: {box['error']}", file=sys.stderr)
            return 1
        result = box.get("result") or {}
        passes += 1
        print(
            "[repair] pass {n}: scanned={scanned} suspect={suspect} "
            "repaired={repaired} relabelled={relabelled} "
            "unresolved={unresolved} failed={failed} "
            "after_rowid={after_rowid} done={done}".format(n=passes, **result)
        )
        after = int(result.get("after_rowid", after))
        state.update({
            "after_rowid": after,
            "updated_at": int(time.time()),
            "passes": int(state.get("passes", 0) or 0) + 1,
            "repaired": int(state.get("repaired", 0) or 0) + int(result.get("repaired", 0)),
            "relabelled": int(state.get("relabelled", 0) or 0) + int(result.get("relabelled", 0)),
            "failed": int(state.get("failed", 0) or 0) + int(result.get("failed", 0)),
        })
        if not args.dry_run:
            _save(state_path, state)
        if result.get("done"):
            print("[repair] sweep complete")
            break
        if not args.all and passes >= args.passes:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

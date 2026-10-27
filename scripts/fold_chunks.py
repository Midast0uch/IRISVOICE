"""Fold near-duplicate chunks of one strand (REQ-4 AC2 / T15).

    python scripts/fold_chunks.py --report
    python scripts/fold_chunks.py --all
    python scripts/fold_chunks.py --dry-run
    python scripts/fold_chunks.py --unfold <canonical chunk id>

One pass folds at most ``--groups`` strand groups (session x chunk_type x
zone) on the ``memory_integrity`` lane; ``--all`` sweeps until every group has
been visited. Resumable: the last visited group key lives beside the store
(``fold_chunks.state.json``). A folded row keeps its text and points at its
canonical row (``folded_into``); recall reads ``folded_into IS NULL`` only, and
``--unfold`` puts a canonical's copies back.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._app_store import app_store_path  # noqa: E402
from backend.memory.db import open_encrypted_memory  # noqa: E402
from backend.memory.fold_chunks import (  # noqa: E402
    DEFAULT_SCAN_GROUPS,
    FOLD_LANE,
    FOLD_THRESHOLD,
    counts,
    fold_pass,
    unfold,
)
from backend.utils.durability_queue import lane  # noqa: E402

STATE_NAME = "fold_chunks.state.json"


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
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--all", action="store_true", help="passes until one full sweep ends")
    ap.add_argument("--groups", type=int, default=DEFAULT_SCAN_GROUPS)
    ap.add_argument("--threshold", type=float, default=FOLD_THRESHOLD)
    ap.add_argument("--restart", action="store_true", help="ignore the saved group watermark")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true", help="print fold counts and exit")
    ap.add_argument("--unfold", default="", help="put one canonical row's folded copies back")
    args = ap.parse_args()

    store_path = app_store_path()
    state_path = _state_path(store_path)
    conn = open_encrypted_memory(store_path, b"")

    if args.unfold:
        n = unfold(conn, args.unfold)
        print(f"[fold] unfolded {n} rows into {args.unfold}")
        return 0

    print(f"[fold] store={store_path}")
    if args.report:
        print(json.dumps(counts(conn), indent=2))
        return 0

    state = {} if args.restart else _load(state_path)
    after = state.get("after_key") or None
    print(f"[fold] state={state_path} after_key={after} dry_run={args.dry_run} "
          f"threshold={args.threshold}")

    mem_lane = lane(FOLD_LANE)
    passes = 0
    while True:
        box: dict = {}
        ok = mem_lane.submit(
            "fold-pass", fold_pass, box, conn, after_key=after,
            scan_groups=args.groups, threshold=args.threshold, dry_run=args.dry_run,
        )
        if not ok:
            print("[fold] lane refused the pass (queue full)", file=sys.stderr)
            return 2
        mem_lane.flush(timeout=1800)
        result = box.get("result") or {}
        if "error" in result:
            print(f"[fold] pass failed: {result['error']}", file=sys.stderr)
            return 1
        passes += 1
        print("[fold] pass {n}: groups={groups_scanned} folded_groups={groups_folded} "
              "rows_folded={rows_folded} after_key={after_key} done={done}".format(
                  n=passes, **result))
        after = result.get("after_key") or after
        state.update({
            "after_key": after,
            "updated_at": int(time.time()),
            "passes": int(state.get("passes", 0) or 0) + 1,
            "rows_folded": int(state.get("rows_folded", 0) or 0) + int(result.get("rows_folded", 0)),
            "counts": counts(conn),
        })
        if not args.dry_run:
            _save(state_path, state)
        if result.get("done"):
            print("[fold] sweep complete")
            break
        if not args.all and passes >= args.passes:
            break
    print(json.dumps(state.get("counts") or {}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

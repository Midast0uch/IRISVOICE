"""Fill the int8 + fingerprint forms of stored chunk vectors (REQ-4 AC1 / T14).

    python scripts/compress_vectors.py --report
    python scripts/compress_vectors.py --all
    python scripts/compress_vectors.py --drop-float document_data --dry-run
    python scripts/compress_vectors.py --drop-float document_data

``--all`` sweeps every row that has a float and no compact form, 20,000 rows per
pass on the ``memory_vectors`` lane. Resumable: the watermark and the totals live
beside the store (``compress_vectors.state.json``).

``--drop-float TYPE[,TYPE]`` removes the 4,096-byte float for a chunk type. Run
``python evals/memory_bench.py`` first: the standard keeps the float for a type
whose int8 recall@10 falls more than 0.02 below float. Use ``--dry-run`` to see
the row count, then run it for real.
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
from backend.memory import vector_quant  # noqa: E402
from backend.memory.vector_compress import (  # noqa: E402
    COMPRESS_LANE,
    DEFAULT_SCAN_ROWS,
    compress_into,
    coverage,
)
from backend.utils.durability_queue import lane  # noqa: E402

STATE_NAME = "compress_vectors.state.json"


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
    ap.add_argument("--scan-rows", type=int, default=DEFAULT_SCAN_ROWS)
    ap.add_argument("--after-rowid", type=int, default=0)
    ap.add_argument("--restart", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true", help="print coverage and exit")
    ap.add_argument("--drop-float", default="",
                    help="comma-separated chunk types whose float vector is removed")
    args = ap.parse_args()

    store_path = app_store_path()
    state_path = _state_path(store_path)
    conn = open_encrypted_memory(store_path, b"")
    drop = [t.strip() for t in (args.drop_float or "").split(",") if t.strip()]

    print(f"[compress] store={store_path}")
    cov = coverage(conn)
    print(f"[compress] rows={cov.get('rows')} compact={cov.get('compact_rows')} "
          f"float={cov.get('float_rows')} vector bytes/row={cov.get('bytes_per_row_vectors')}")
    if args.report:
        print(json.dumps(cov, indent=2))
        return 0

    state = {} if args.restart else _load(state_path)
    after = 0 if args.restart else int(state.get("after_rowid", 0) or 0)
    if args.after_rowid:
        after = args.after_rowid
    print(f"[compress] state={state_path} after_rowid={after} dry_run={args.dry_run} drop={drop}")

    mem_lane = lane(COMPRESS_LANE)
    passes = 0
    while True:
        box: dict = {}
        ok = mem_lane.submit(
            "compress-pass", compress_into, box, conn, after,
            scan_rows=args.scan_rows, dim=vector_quant.DIM, drop=drop,
            dry_run=args.dry_run,
        )
        if not ok:
            print("[compress] lane refused the pass (queue full)", file=sys.stderr)
            return 2
        mem_lane.flush(timeout=1800)
        if "error" in (box.get("result") or {}):
            print(f"[compress] pass failed: {box['result']['error']}", file=sys.stderr)
            return 1
        result = box.get("result") or {}
        passes += 1
        print("[compress] pass {n}: scanned={scanned} compressed={compressed} skipped={skipped} "
              "failed={failed} dropped={dropped} after_rowid={after_rowid} done={done} "
              "{elapsed_s}s".format(n=passes, **result))
        after = int(result.get("after_rowid", after))
        state.update({
            "after_rowid": after,
            "updated_at": int(time.time()),
            "passes": int(state.get("passes", 0) or 0) + 1,
            "compressed": int(state.get("compressed", 0) or 0) + int(result.get("compressed", 0)),
            "skipped": int(state.get("skipped", 0) or 0) + int(result.get("skipped", 0)),
            "failed": int(state.get("failed", 0) or 0) + int(result.get("failed", 0)),
            "dropped": int(state.get("dropped", 0) or 0) + int(result.get("dropped", 0)),
            "coverage": coverage(conn),
        })
        if not args.dry_run:
            _save(state_path, state)
        if result.get("done"):
            print("[compress] sweep complete")
            break
        if not args.all and passes >= args.passes:
            break
    print(json.dumps({k: v for k, v in (state.get("coverage") or {}).items() if k != "by_type"},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

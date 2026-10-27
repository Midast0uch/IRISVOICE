"""Distil proven claims' agreeing chunks into chain references (REQ-4 AC3 / T16).

    python scripts/distil_claims.py --report
    python scripts/distil_claims.py --all
    python scripts/distil_claims.py --dry-run

One pass distils at most ``--claims`` proven claims (tier 'landmark', not
absorbed) on the ``memory_integrity`` lane; ``--all`` sweeps until every proven
claim has been visited. Each claim gets ONE ``memory_chain`` row: the claim's own
text (proven = trust-allowed) plus REFERENCES to its agreeing chunks (ids, never
payloads), marked ``distilled = 1``. Idempotent: a claim that already has a
distilled row is skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# httpx sends 127.0.0.1 through an exported HTTP_PROXY (PROGRESS, environment
# hazards): every local embedding call would fail and look like "model down".
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._app_store import app_store_path  # noqa: E402
from backend.memory.db import open_encrypted_memory  # noqa: E402
from backend.memory.distil_claims import (  # noqa: E402
    DEFAULT_SCAN_CLAIMS,
    DISTIL_LANE,
    counts,
    distil_pass,
)
from backend.memory.embedding import get_embedding_service  # noqa: E402
from backend.utils.durability_queue import lane  # noqa: E402

STATE_NAME = "distil_claims.state.json"


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
    ap.add_argument("--claims", type=int, default=DEFAULT_SCAN_CLAIMS)
    ap.add_argument("--restart", action="store_true", help="ignore the saved watermark")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true", help="print distil counts and exit")
    args = ap.parse_args()

    store_path = app_store_path()
    state_path = _state_path(store_path)
    conn = open_encrypted_memory(store_path, b"")

    print(f"[distil] store={store_path}")
    if args.report:
        print(json.dumps(counts(conn), indent=2))
        return 0

    svc = get_embedding_service()
    embed = lambda t: svc.encode_with_meta(t).vector  # noqa: E731 - one callable, no class
    state = {} if args.restart else _load(state_path)
    after = 0 if args.restart else int(state.get("after_rowid", 0) or 0)
    print(f"[distil] state={state_path} after_rowid={after} dry_run={args.dry_run}")

    mem_lane = lane(DISTIL_LANE)
    passes = 0
    while True:
        box: dict = {}
        ok = mem_lane.submit(
            "distil-pass", distil_pass, box, conn, after_rowid=after,
            scan_claims=args.claims, embed=embed, dry_run=args.dry_run,
        )
        if not ok:
            print("[distil] lane refused the pass (queue full)", file=sys.stderr)
            return 2
        mem_lane.flush(timeout=1800)
        result = box.get("result") or {}
        if "error" in result:
            print(f"[distil] pass failed: {result['error']}", file=sys.stderr)
            return 1
        passes += 1
        print("[distil] pass {n}: claims={claims} distilled={distilled} "
              "already_done={skipped_done} no_refs={skipped_no_refs} "
              "after_rowid={after_rowid} done={done}".format(n=passes, **result))
        after = int(result.get("after_rowid", after))
        state.update({
            "after_rowid": after,
            "updated_at": int(time.time()),
            "passes": int(state.get("passes", 0) or 0) + 1,
            "distilled": int(state.get("distilled", 0) or 0) + int(result.get("distilled", 0)),
            "counts": counts(conn),
        })
        if not args.dry_run:
            _save(state_path, state)
        if result.get("done"):
            print("[distil] sweep complete")
            break
        if not args.all and passes >= args.passes:
            break
    print(json.dumps(state.get("counts") or {}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

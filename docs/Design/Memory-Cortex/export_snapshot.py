"""Export a bounded, read-only snapshot of IRIS app memory (the same model the Memory surface draws).

    python docs/Design/Memory-Cortex/export_snapshot.py            # all recent threads
    python docs/Design/Memory-Cortex/export_snapshot.py --no-eval  # skip eval-* threads
    python docs/Design/Memory-Cortex/export_snapshot.py --db C:/dev/IRISVOICE/data/memory.db  # explicit store

Writes docs/Design/Memory-Cortex/memory-snapshot.js (window.IRIS_MEMORY = {...}) - an offline copy of
the model for inspection (the mockup that read it was removed 2026-10-27). The snapshot holds personal
memory: it is git-ignored and must not be published or committed.

This file is only the command line. The model itself (every SQL statement, every mapping into the
dashboard's plain vocabulary, the optional-table detection) lives in backend/memory/surface_queries.py
snapshot(), the same function GET /api/memory/snapshot serves, so the export and the app read the same
shape from the same SQL (MEMORY-INTERFACE.md §10.3). Read-only URI connections, LIMIT on every
row query, no blobs or embeddings, references only. meta.available lists the optional tables found.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from _app_store import app_store_path  # noqa: E402  (the one store resolver for scripts)

OUT = Path(__file__).with_name("memory-snapshot.js")
CONV_DB = ROOT / "data" / "conversations.db"


def _surface_queries():
    """Load the query module by path: it needs only the standard library, so the exporter does not pull in
    the whole backend.memory package (embeddings, encryption, ...)."""
    spec = importlib.util.spec_from_file_location("iris_surface_queries", ROOT / "backend" / "memory" / "surface_queries.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-eval", action="store_true", help="leave out eval-* threads")
    ap.add_argument("--threads", type=int, default=48)
    ap.add_argument("--db", help="read this store instead of the configured one (a git worktree has no data/)")
    ap.add_argument("--events", type=int, default=6000)
    args = ap.parse_args()
    store = args.db or app_store_path()
    conv_db = Path(args.db).with_name("conversations.db") if args.db else CONV_DB
    snap = _surface_queries().snapshot(threads=args.threads, events=args.events, include_eval=not args.no_eval,
                                       db=store, conv_db=conv_db)
    OUT.write_text("window.IRIS_MEMORY = " + json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    n = {k: len(v) for k, v in snap.items() if isinstance(v, list)}
    print(f"[export_snapshot] wrote {OUT.name}: {n['sessions']} sessions, {n['events']} events, "
          f"{n['landmarks']} live landmarks, {n['edges']} edges, {n['episodes']} episodes, {n['artifacts']} artifacts, "
          f"{n['oracle']} decision points; {n['pins']} pins, {n['nodes']} nodes, {n['nodeEdges']} node edges, "
          f"{n['spaces']} spaces, {n['sectors']} sectors, {n['quorum']} quorum rows, {n['recalls']} recall turns; "
          f"tables={snap['meta']['available']}; warnings={snap['meta']['warnings']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

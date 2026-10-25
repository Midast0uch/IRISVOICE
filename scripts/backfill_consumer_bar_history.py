#!/usr/bin/env python3
"""Backfill benchmarks/consumer_bar_history.jsonl from the git versions of consumer_bar_record.json.

The history file (backend/agent/consumer_bar.py: save_bar_record appends one line per status CHANGE)
starts empty the day it ships, but the record has lived in git since 2026-10-05. This walks those
versions oldest first and writes one line per consumer whose status changed (or first appeared),
dated with the commit's date. It is idempotent: a line already in the file (same consumer, status
and time) is not written again, so a re-run writes nothing.

    python scripts/backfill_consumer_bar_history.py            # write
    python scripts/backfill_consumer_bar_history.py --dry-run  # print what would be written

Read-only against git. The file is kept sorted by time and capped at HISTORY_MAX lines.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from backend.agent.consumer_bar import (  # noqa: E402
    BAR_PATH, HISTORY_MAX, history_path, read_history_lines, write_history_lines,
)

REL = BAR_PATH.relative_to(REPO).as_posix()


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def _utc(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(timezone.utc).isoformat(timespec="seconds")


def git_versions() -> List[tuple]:
    """[(utc commit time, {consumer: {status, gap}})], oldest first."""
    out: List[tuple] = []
    for line in reversed(_git("log", "--format=%H %cI", "--", REL).splitlines()):
        sha, when = line.split(" ", 1)
        try:
            raw = json.loads(_git("show", f"{sha}:{REL}"))
        except (subprocess.CalledProcessError, ValueError):
            continue          # a version that is not readable JSON carries no state
        if isinstance(raw, dict):
            out.append((_utc(when), {c: v for c, v in raw.items()
                                      if isinstance(v, dict) and v.get("status")}))
    return out


def changes(versions: List[tuple]) -> List[Dict[str, str]]:
    """One row per consumer per version where its status differs from the version before (or is new)."""
    last: Dict[str, str] = {}
    rows: List[Dict[str, str]] = []
    for at, record in versions:
        for cid in sorted(record):
            status = record[cid]["status"]
            if last.get(cid) != status:
                rows.append({"at": at, "consumer": cid, "status": status, "gap": record[cid].get("gap") or ""})
                last[cid] = status
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="print the lines to add, write nothing")
    args = ap.parse_args(argv)

    path = history_path()
    existing = read_history_lines(path)
    have = {(r["at"], r["consumer"], r["status"]) for r in existing}
    new = [r for r in changes(git_versions()) if (r["at"], r["consumer"], r["status"]) not in have]
    per: Dict[str, int] = {}
    for r in new:
        per[r["consumer"]] = per.get(r["consumer"], 0) + 1
    print(f"{len(new)} line(s) to add to {path.name} ({len(existing)} already there)")
    for cid in sorted(per):
        print(f"  {cid}: {per[cid]}")
    if args.dry_run or not new:
        return 0
    merged = sorted(existing + new, key=lambda r: str(r.get("at") or ""))   # stable: same-time lines keep order
    write_history_lines(path, merged)
    print(f"wrote {path} ({min(len(merged), HISTORY_MAX)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

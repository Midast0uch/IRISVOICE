"""Undo the landmark merges that joined two DIFFERENT tasks (offline, human-run, once).

Why (2026-10-24, measured on the live store): 3,336 of 3,742 merges joined tasks whose words were
< 30% alike - "scrape the hockey teams page" absorbed into "who created Python" - because the merger
compared node clusters only and every task walked the same few nodes. Each merge also copied the
absorbed claim's evidence onto the survivor, so claims looked proven by tests of other tasks. The rule
is fixed (profile.task_key: a claim merges only with the SAME task, owner decision 2026-10-24); this
script repairs what the old rule did. Merged rows were never deleted (absorbed = 1), so it can.

For every logged merge whose survivor and absorbed claim are different tasks:
  * the absorbed claim is live again (absorbed = NULL);
  * the evidence the merge copied onto the survivor is taken back: one entry per entry of the absorbed
    row, matched on (kind, ref, session), plus the merge's own "recurrence / merged <id>" entry. The
    removal follows the survivor down its later SAME-task merges (the copy travelled there too); a later
    wrong merge is repaired by its own entry, so nothing is taken twice;
  * the tier is derived again from what is left: a 'landmark' that only borrowed its proof returns to
    'candidate' (stale / demoted stay as they are).
Not undone (the merge log does not record them): landmark edges re-pointed to the survivor, and nodes the
survivor's cluster took from the absorbed one. The maintenance pass (collapse_duplicates) re-merges
restored claims with their same-task peers under the new rule.

Idempotent: a merge whose absorbed claim is already live is skipped, so a second run changes nothing.
Every row it changes is written to a JSON log first (its values before), next to the store.

    python scripts/undo_wrong_landmark_merges.py            # dry run: report only
    python scripts/undo_wrong_landmark_merges.py --apply    # write (the backend must be stopped)
"""
from __future__ import annotations

import argparse
import collections
import json
import socket
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _app_store import app_store_path  # noqa: E402
from backend.memory.mycelium.landmark import PROMOTE_MIN_EVIDENCE, _independent  # noqa: E402
from backend.memory.mycelium.profile import task_key  # noqa: E402


def _backend_running(port: int = 8090) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _key(e: dict) -> tuple:
    return (e.get("kind"), e.get("ref") or "", e.get("session") or "")


def plan(con: sqlite3.Connection) -> dict:
    """What the repair would do, computed in memory: {restore, evidence, tier, wrong, merges}."""
    rows = {r[0]: {"label": r[1], "absorbed": r[2], "tier": r[3] or "candidate", "evidence": json.loads(r[4] or "[]")}
            for r in con.execute("SELECT landmark_id, label, absorbed, tier, evidence FROM mycelium_landmarks")}
    merges = con.execute("SELECT survivor_id, absorbed_id, created_at FROM mycelium_landmark_merges "
                         "ORDER BY created_at").fetchall()
    same = lambda a, b: bool(task_key(rows[a]["label"])) and task_key(rows[a]["label"]) == task_key(rows[b]["label"])
    # where each claim went, and when (a claim is absorbed once; the last log row wins)
    went = {a: (s, t) for s, a, t in merges if s in rows and a in rows}
    evidence = {lid: list(r["evidence"]) for lid, r in rows.items()}
    restore, taken = [], collections.Counter()
    wrong = [(s, a, t) for s, a, t in merges if s in rows and a in rows and not same(s, a)]
    for s, a, t in wrong:
        if rows[a]["absorbed"] != 1:
            continue                                                    # already live: done by an earlier run
        restore.append(a)
        moved = [_key(e) for e in rows[a]["evidence"]]
        target, since = s, t
        while target is not None:
            ev = evidence[target]
            for k in moved:
                i = next((j for j, e in enumerate(ev) if _key(e) == k), None)
                if i is not None:
                    ev.pop(i)
                    taken[target] += 1
            i = next((j for j, e in enumerate(ev) if e.get("kind") == "recurrence" and e.get("ref") == f"merged {a}"), None)
            if i is not None:
                ev.pop(i)
                taken[target] += 1
            nxt = went.get(target)
            # the copy travelled on only through a LATER merge of the same task
            target, since = (nxt[0], nxt[1]) if nxt and nxt[1] > since and same(nxt[0], target) else (None, None)
    tier = {}
    for lid in taken:
        old = rows[lid]["tier"]
        if old == "landmark" and _independent(evidence[lid]) < PROMOTE_MIN_EVIDENCE:
            tier[lid] = "candidate"
    return {"rows": rows, "restore": restore, "evidence": {lid: evidence[lid] for lid in taken}, "taken": taken,
            "tier": tier, "wrong": len(wrong), "merges": len(merges)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the repair (default: dry run)")
    ap.add_argument("--db", default=None, help="another store (default: the configured app store)")
    args = ap.parse_args()
    db = Path(args.db or app_store_path())
    if not db.exists():
        print(f"no store at {db}")
        return 2
    if args.apply and args.db is None and _backend_running():
        print("the backend is running (127.0.0.1:8090): stop it first - one writer per store")
        return 2
    uri = f"file:{db.as_posix()}?mode={'rw' if args.apply else 'ro'}"
    con = sqlite3.connect(uri, uri=True, timeout=30)
    try:
        p = plan(con)
        live_before = sum(1 for r in p["rows"].values() if r["absorbed"] != 1)
        print(f"store {db}")
        print(f"merges {p['merges']}, joined different tasks {p['wrong']}, claims to bring back {len(p['restore'])}")
        print(f"live claims {live_before} -> {live_before + len(p['restore'])}")
        print(f"evidence entries taken back {sum(p['taken'].values())} from {len(p['taken'])} claims; "
              f"proven -> learning {len(p['tier'])}")
        for lid in p["restore"][:5]:
            print(f"  back: {lid}  {str(p['rows'][lid]['label'])[:80]!r}")
        if not args.apply:
            print("dry run: nothing written (use --apply)")
            return 0
        if not p["restore"]:
            print("nothing to do")
            return 0
        touched = set(p["restore"]) | set(p["evidence"]) | set(p["tier"])
        log = db.with_name(f"landmark_merge_undo-{time.strftime('%Y%m%d-%H%M%S')}.json")
        log.write_text(json.dumps({"store": str(db), "at": time.time(), "before": {
            lid: {k: p["rows"][lid][k] for k in ("absorbed", "tier", "evidence")} for lid in sorted(touched)}}, indent=1))
        with con:
            con.executemany("UPDATE mycelium_landmarks SET absorbed = NULL WHERE landmark_id = ?",
                            [(lid,) for lid in p["restore"]])
            con.executemany("UPDATE mycelium_landmarks SET evidence = ? WHERE landmark_id = ?",
                            [(json.dumps(ev), lid) for lid, ev in p["evidence"].items()])
            con.executemany("UPDATE mycelium_landmarks SET tier = ? WHERE landmark_id = ?",
                            [(t, lid) for lid, t in p["tier"].items()])
        print(f"written; values before are in {log}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())

"""Remove the eval-synthetic rows from the memory recall paths (one-time /
per-measurement-cycle hygiene).

The memory eval group teaches invented facts in seed threads. Every run leaves
its rows in the store; the first A/B cycles showed what that costs - one
pathological m03 run wrote 20+ "green or blue?" chain rows that matched every
later m03 ask and misled the model (S137). The tasks now carry a per-run fact
suffix, so FUTURE runs cannot collide - but the rows already written keep
matching the ask's token gate until they age out of the newest-24 pool.

This script removes the synthetic rows from the three recall-delivery paths the
memory group reads (chain rows, episodes, recall-outcome events), identified by
their eval thread/session ids. It touches NOTHING else: no user strands, no
claims, no chunks (chunk recall is session-scoped and never sees them), no
conversations.db (chat history, not a planner recall path).

    python scripts/clean_eval_memory.py --dry-run   # counts only
    python scripts/clean_eval_memory.py             # deletes

Writes go through db.app_write + app_flush (the one writer).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._app_store import app_store_path  # noqa: E402
from backend.memory.db import app_flush, app_write, open_encrypted_memory  # noqa: E402

# (table, id column, LIKE pattern, label) - the memory store
TARGETS = (
    ("memory_chain", "thread_id", "eval-%", "chain rows (the turn-start + per-step recall pool)"),
    ("episodes", "session_id", "eval-%", "episodes (the episodic context search)"),
    ("memory_events", "thread_id", "eval-%", "recall-outcome events (HELPED/MISLED multipliers)"),
)

# conversations.db: the memory surface search reads its turns, and the model's
# own memory-lookup steps reach them (live 2026-10-28: m03's ask answered
# "green" from three OLD eval chats after the chain was already clean).
# Eval conversations are synthetic (title "[eval ..." / "[eval-seed ...",
# created by the runner); user threads never carry that prefix.
_CONV_TARGETS = (
    ("messages", "conversation_id",
     "SELECT id FROM conversations WHERE title LIKE '[eval%'", "eval chat messages"),
    ("conversations", "id", None, "eval chat threads"),
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="count only, delete nothing")
    args = ap.parse_args()

    conn = open_encrypted_memory(app_store_path(), b"")
    report: dict = {}
    for table, col, pattern, label in TARGETS:
        try:
            n = int(conn.execute(
                f"SELECT count(*) FROM {table} WHERE {col} LIKE ?", (pattern,)).fetchone()[0])
        except Exception as exc:
            report[table] = {"error": repr(exc)}
            continue
        report[table] = {"rows": n, "what": label}
        if n and not args.dry_run:
            app_write(conn, f"DELETE FROM {table} WHERE {col} LIKE ?", (pattern,))
            app_flush(120.0)
            # app_write queues to the native writer; verify it landed
            left = int(conn.execute(
                f"SELECT count(*) FROM {table} WHERE {col} LIKE ?", (pattern,)).fetchone()[0])
            report[table]["remaining"] = left

    # conversations.db (the chat history the surface search reads)
    conv_path = ROOT / "data" / "conversations.db"
    if conv_path.exists():
        import sqlite3

        ccon = sqlite3.connect(str(conv_path))
        try:
            eval_ids = [r[0] for r in ccon.execute(
                "SELECT id FROM conversations WHERE title LIKE '[eval%'").fetchall()]
            n_msgs = int(ccon.execute(
                "SELECT count(*) FROM messages WHERE conversation_id IN "
                "(SELECT id FROM conversations WHERE title LIKE '[eval%')").fetchone()[0])
            report["conversations.db"] = {
                "threads": len(eval_ids), "messages": n_msgs,
                "what": "synthetic eval chats (the surface-search turn path)"}
            if eval_ids and not args.dry_run:
                ccon.execute(
                    "DELETE FROM messages WHERE conversation_id IN "
                    "(SELECT id FROM conversations WHERE title LIKE '[eval%')")
                ccon.execute("DELETE FROM conversations WHERE title LIKE '[eval%'")
                ccon.commit()
                left = int(ccon.execute(
                    "SELECT count(*) FROM conversations WHERE title LIKE '[eval%'").fetchone()[0])
                report["conversations.db"]["remaining"] = left
        finally:
            ccon.close()
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

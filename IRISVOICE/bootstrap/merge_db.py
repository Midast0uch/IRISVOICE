"""
Mycelium Federation Merge
File: IRISVOICE/bootstrap/merge_db.py

Merge a remote IRIS coordinate DB into the local one.
Designed for a future where multiple IRIS instances share knowledge:
  - Permanent landmarks travel between instances
  - Wiki entries accumulate across the network
  - Pheromone edge weights compound (averaged, not overwritten)
  - Conflicts resolved by strategy (default: landmark_wins)
  - Every merge is audited in merge_log

Usage (run from IRISVOICE/):
    python bootstrap/merge_db.py --source /path/to/other/coordinates.db
    python bootstrap/merge_db.py --source /path/to/other/coordinates.db --strategy newer_wins
    python bootstrap/merge_db.py --dry-run --source /path/to/other/coordinates.db
    python bootstrap/merge_db.py --log   # show past merges

Strategies:
  landmark_wins  — keep local landmark if same name exists, skip remote (default)
  newer_wins     — overwrite with whichever was updated more recently
  manual         — list conflicts and exit without importing (for review)
"""

import sys
import os
import json
import sqlite3
import time
import uuid
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from bootstrap.coordinates import CoordinateStore, COORDINATES_DB


# ── Helpers ────────────────────────────────────────────────────────────────

def _open_remote(source_path: str) -> sqlite3.Connection:
    if not os.path.exists(source_path):
        print(f"ERROR: source DB not found: {source_path}")
        sys.exit(1)
    conn = sqlite3.connect(source_path)
    conn.row_factory = sqlite3.Row
    return conn


def _col_names(conn: sqlite3.Connection, table: str) -> set:
    """Return the set of column names for a table (handles schema version differences)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


# ── Import functions ───────────────────────────────────────────────────────

def _import_landmarks(
    local: CoordinateStore,
    remote_conn: sqlite3.Connection,
    strategy: str,
    dry_run: bool,
) -> tuple[int, int]:
    """
    Import permanent landmarks from remote.
    Returns (imported_count, conflict_count).
    """
    imported, conflicts = 0, 0
    remote_cols = _col_names(remote_conn, "landmarks")

    rows = remote_conn.execute(
        "SELECT * FROM landmarks WHERE is_permanent = 1"
    ).fetchall()

    with local._conn() as local_conn:
        for row in rows:
            r = dict(row)
            existing = local_conn.execute(
                "SELECT * FROM landmarks WHERE name = ?", (r["name"],)
            ).fetchone()

            if existing:
                conflicts += 1
                if strategy == "landmark_wins":
                    continue  # keep local
                elif strategy == "newer_wins":
                    local_last = existing["last_verified"] or existing["created_at"]
                    remote_last = r.get("last_verified") or r.get("created_at", 0)
                    if remote_last <= local_last:
                        continue  # local is newer
                elif strategy == "manual":
                    print(f"  CONFLICT: landmark '{r['name']}' exists locally and remotely")
                    continue

            if not dry_run:
                # Stamp provenance columns if the remote row has them
                origin_id = r.get("origin_id") or ""
                project_id = r.get("project_id") or ""
                # Use INSERT OR IGNORE so duplicate landmark_ids are skipped safely
                local_conn.execute(
                    "INSERT OR IGNORE INTO landmarks "
                    "(landmark_id, name, description, feature_path, test_command, "
                    " pass_count, is_permanent, session_number, created_at, "
                    " last_verified, origin_id, project_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        r["landmark_id"], r["name"], r["description"],
                        r["feature_path"], r["test_command"],
                        r["pass_count"], r["is_permanent"], r["session_number"],
                        r["created_at"], r.get("last_verified"),
                        origin_id, project_id,
                    )
                )
            imported += 1

    return imported, conflicts


def _import_wiki_entries(
    local: CoordinateStore,
    remote_conn: sqlite3.Connection,
    source_instance_id: str,
    strategy: str,
    dry_run: bool,
) -> tuple[int, int]:
    """
    Import wiki entries from remote.
    Permanent entries from remote always travel. Non-permanent only if not already present.
    Returns (imported_count, conflict_count).
    """
    # Check if remote has wiki_entries at all
    tables = {
        r[0] for r in
        remote_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "wiki_entries" not in tables:
        return 0, 0

    imported, conflicts = 0, 0
    rows = remote_conn.execute("SELECT * FROM wiki_entries").fetchall()

    with local._conn() as local_conn:
        for row in rows:
            r = dict(row)
            existing = local_conn.execute(
                "SELECT entry_id FROM wiki_entries WHERE entry_id = ?", (r["entry_id"],)
            ).fetchone()

            if existing:
                conflicts += 1
                if strategy == "landmark_wins":
                    # Permanent entries from remote win over non-permanent local
                    if not r.get("is_permanent"):
                        continue
                elif strategy == "newer_wins":
                    local_row = local_conn.execute(
                        "SELECT updated_at FROM wiki_entries WHERE entry_id = ?",
                        (r["entry_id"],)
                    ).fetchone()
                    if local_row and local_row["updated_at"] >= r.get("updated_at", 0):
                        continue
                elif strategy == "manual":
                    print(f"  CONFLICT: wiki entry '{r['title']}' ({r['entry_id']})")
                    continue

            if not dry_run:
                # Stamp origin_id as the remote instance that produced it
                origin = r.get("origin_id") or source_instance_id
                local_conn.execute(
                    "INSERT OR REPLACE INTO wiki_entries "
                    "(entry_id, title, content, tags, file_refs, image_refs, "
                    " project_id, origin_id, created_at, updated_at, is_permanent) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        r["entry_id"], r["title"], r.get("content",""),
                        r.get("tags","[]"), r.get("file_refs","[]"),
                        r.get("image_refs","[]"), r.get("project_id"),
                        origin, r["created_at"], r["updated_at"],
                        r.get("is_permanent", 0),
                    )
                )
            imported += 1

    return imported, conflicts


def _import_graph_edges(
    local: CoordinateStore,
    remote_conn: sqlite3.Connection,
    dry_run: bool,
) -> int:
    """
    Compound pheromone edge weights — add remote compound_count to local.
    Edges that don't exist locally are inserted fresh.
    Returns number of edges merged.
    """
    tables = {
        r[0] for r in
        remote_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "graph_edges" not in tables:
        return 0

    merged = 0
    rows = remote_conn.execute("SELECT * FROM graph_edges").fetchall()
    with local._conn() as local_conn:
        for row in rows:
            r = dict(row)
            existing = local_conn.execute(
                "SELECT edge_id, weight, compound_count FROM graph_edges WHERE edge_id = ?",
                (r["edge_id"],)
            ).fetchone()
            if existing:
                # Compound: average weights, sum compound counts
                new_weight = (existing["weight"] + r["weight"]) / 2.0
                new_count = existing["compound_count"] + r.get("compound_count", 0)
                if not dry_run:
                    local_conn.execute(
                        "UPDATE graph_edges SET weight = ?, compound_count = ?, "
                        "last_scored = ? WHERE edge_id = ?",
                        (new_weight, new_count, time.time(), r["edge_id"])
                    )
            else:
                if not dry_run:
                    local_conn.execute(
                        "INSERT OR IGNORE INTO graph_edges "
                        "(edge_id, source_type, source_id, target_type, target_id, "
                        " relationship, weight, compound_count, decay_rate, "
                        " last_scored, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            r["edge_id"], r["source_type"], r["source_id"],
                            r["target_type"], r["target_id"], r["relationship"],
                            r["weight"], r.get("compound_count", 0),
                            r.get("decay_rate", 0.020),
                            r.get("last_scored"), r["created_at"],
                        )
                    )
            merged += 1
    return merged


# ── Main merge ─────────────────────────────────────────────────────────────

def do_merge(source_path: str, strategy: str, dry_run: bool) -> None:
    local = CoordinateStore()
    remote_conn = _open_remote(source_path)

    # Get remote instance identity (may not exist in older DBs)
    tables = {
        r[0] for r in
        remote_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "instance_registry" in tables:
        row = remote_conn.execute(
            "SELECT instance_id, name FROM instance_registry LIMIT 1"
        ).fetchone()
        source_instance_id = row["instance_id"] if row else "unknown"
        source_name = row["name"] if row else source_path
    else:
        source_instance_id = "unknown"
        source_name = source_path

    mode = "[DRY RUN] " if dry_run else ""
    print(f"{mode}FEDERATION MERGE")
    print(f"  Source: {source_name} ({source_instance_id})")
    print(f"  Target: {COORDINATES_DB}")
    print(f"  Strategy: {strategy}")
    print()

    if strategy == "manual":
        print("Conflicts (manual review mode — nothing will be imported):")

    lm_imported, lm_conflicts = _import_landmarks(
        local, remote_conn, strategy, dry_run
    )
    wiki_imported, wiki_conflicts = _import_wiki_entries(
        local, remote_conn, source_instance_id, strategy, dry_run
    )
    edges_merged = _import_graph_edges(local, remote_conn, dry_run)

    remote_conn.close()

    print(f"  Landmarks imported:     {lm_imported}  ({lm_conflicts} conflict(s))")
    print(f"  Wiki entries imported:  {wiki_imported}  ({wiki_conflicts} conflict(s))")
    print(f"  Graph edges merged:     {edges_merged}")

    if not dry_run:
        merge_id = local.record_merge(
            source_instance_id=source_instance_id,
            source_path=source_path,
            landmarks_imported=lm_imported,
            wiki_entries_imported=wiki_imported,
            conflicts_resolved=lm_conflicts + wiki_conflicts,
            strategy=strategy,
        )
        print(f"\nMerge recorded: {merge_id}")
        print("Run 'python bootstrap/session_start.py --compact' to verify.")
    else:
        print("\n[DRY RUN] No changes written.")


def cmd_log(local: CoordinateStore) -> None:
    log = local.get_merge_log()
    if not log:
        print("No federation merges recorded.")
        return
    print(f"FEDERATION MERGE LOG ({len(log)} merge(s)):")
    print()
    for m in log:
        import datetime
        ts = datetime.datetime.fromtimestamp(m["merged_at"]).strftime("%Y-%m-%d %H:%M")
        print(f"  {m['merge_id']}  {ts}")
        print(f"    Source: {m['source_instance_id']}  ({m['source_path']})")
        print(f"    Landmarks: {m['landmarks_imported']}  Wiki: {m['wiki_entries_imported']}  "
              f"Conflicts: {m['conflicts_resolved']}  Strategy: {m['strategy']}")
        print()


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Mycelium Federation Merge — import permanent knowledge from another IRIS instance"
    )
    parser.add_argument("--source", metavar="PATH",
                        help="Path to the source coordinates.db to merge from")
    parser.add_argument(
        "--strategy",
        choices=["landmark_wins", "newer_wins", "manual"],
        default="landmark_wins",
        help="Conflict resolution strategy (default: landmark_wins)",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be imported without writing anything")
    parser.add_argument("--log", action="store_true",
                        help="Show the federation merge audit log")

    args = parser.parse_args()

    if args.log:
        cmd_log(CoordinateStore())
        return

    if not args.source:
        parser.print_help()
        sys.exit(1)

    do_merge(args.source, args.strategy, args.dry_run)


if __name__ == "__main__":
    main()

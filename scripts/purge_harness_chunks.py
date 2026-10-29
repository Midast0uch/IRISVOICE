"""Purge harness/eval chunks from the app store (owner 2026-10-28: it is all test data).

Targets the sessions the bench and the DER harness created: de-*, eval-*, s365*,
ct-*, r1, g1. Real conversation sessions (session_iris) are NOT touched.

    python scripts/purge_harness_chunks.py            # dry run
    python scripts/purge_harness_chunks.py --apply    # delete + VACUUM
"""
import os
import sys

sys.path.insert(0, r"C:\dev\IRISVOICE")

from backend.memory.config import resolve_memory_store_path  # noqa: E402

DB = str(resolve_memory_store_path())
WHERE = ("session_id LIKE 'de-%' OR session_id LIKE 'eval-%' "
         "OR session_id LIKE 's365%' OR session_id LIKE 'ct-%' OR session_id IN ('r1','g1')")
# T44 (REQ-12 AC7): the same harness ids also sit in the Immortus chain, where
# they crowd the recall candidate pool (24 rows) with eval transcripts. The
# chain keys on thread_id, not session_id.
CHAIN_WHERE = ("thread_id LIKE 'de-%' OR thread_id LIKE 'eval-%' "
               "OR thread_id LIKE 's365%' OR thread_id LIKE 'ct-%' "
               "OR thread_id IN ('r1','g1')")


def main(apply: bool) -> dict:
    from backend.memory.db import app_write
    from backend.memory.episodic import EpisodicStore

    st = EpisodicStore(db_path=DB, biometric_key=b"\0" * 32)
    con = st.db
    out = {"apply": apply}

    out["before"] = {
        "chunks": con.execute("SELECT COUNT(*) FROM context_chunks").fetchone()[0],
        "bytes": os.path.getsize(DB),
    }
    ids = [r[0] for r in con.execute(
        f"SELECT rowid FROM context_chunks WHERE {WHERE}")]
    out["tagged"] = len(ids)
    try:
        chain_ids = [r[0] for r in con.execute(
            f"SELECT rowid FROM memory_chain WHERE {CHAIN_WHERE}")]
    except Exception:  # noqa: BLE001 - table may not exist in an older store
        chain_ids = []
    out["tagged_chain"] = len(chain_ids)
    if not apply:
        out["would_delete"] = len(ids)
        out["would_delete_chain"] = len(chain_ids)
        return out

    for part in range(0, len(ids), 500):
        chunk = ids[part:part + 500]
        app_write(con, f"DELETE FROM context_chunks WHERE rowid IN "
                       f"({','.join('?' * len(chunk))})", chunk)
    for part in range(0, len(chain_ids), 500):
        chunk = chain_ids[part:part + 500]
        app_write(con, f"DELETE FROM memory_chain WHERE rowid IN "
                       f"({','.join('?' * len(chunk))})", chunk)
    # derived rows for the same sessions go too (thread_context is rebuildable)
    try:
        app_write(con, f"DELETE FROM thread_context WHERE {WHERE.replace('session_id', 'thread_id')}")
    except Exception:  # noqa: BLE001 - table may not exist in an older store
        pass

    out["after_delete"] = con.execute("SELECT COUNT(*) FROM context_chunks").fetchone()[0]
    try:
        con.execute("VACUUM")
        out["vacuumed"] = True
    except Exception as exc:  # noqa: BLE001
        out["vacuumed"] = False
        out["vacuum_error"] = repr(exc)
    out["after"] = {
        "chunks": con.execute("SELECT COUNT(*) FROM context_chunks").fetchone()[0],
        "bytes": os.path.getsize(DB),
    }
    out["free_mb"] = round((out["before"]["bytes"] - out["after"]["bytes"]) / 1048576, 1)
    return out


if __name__ == "__main__":
    import json

    print(json.dumps(main("--apply" in sys.argv), indent=2))

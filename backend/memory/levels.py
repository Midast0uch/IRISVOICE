"""L1 thread_context + L2 episode codec (REQ-11). Derived, rebuildable, one codec.

L1 is NOT truth: drop the table and this rebuilds it from context_chunks.
L2 already exists as a float32 `embedding`; this adds the int8 + fingerprint
form so all three levels scan with the same machinery.

    python -m backend.memory.levels --dry-run
    python -m backend.memory.levels --episodes
"""
from __future__ import annotations

import logging
import time

import numpy as np

from backend.memory import vector_quant
from backend.memory.db import app_write, owns_store

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS thread_context (
  thread_id      TEXT PRIMARY KEY,
  first_ts       REAL,
  last_ts        REAL,
  n_chunks       INTEGER NOT NULL DEFAULT 0,
  n_episodes     INTEGER NOT NULL DEFAULT 0,
  coords_from    TEXT,
  coords_to      TEXT,
  centroid_i8    BLOB,
  centroid_fp    BLOB,
  centroid_scale REAL,
  digest_ref     TEXT,
  chain_linked   INTEGER NOT NULL DEFAULT 0,
  updated_at     REAL NOT NULL
)
"""


def ensure_schema(conn) -> None:
    conn.execute(DDL)
    _cols = {r[1] for r in conn.execute("PRAGMA table_info(thread_context)").fetchall()}
    if _cols and "chain_linked" not in _cols:
        conn.execute("ALTER TABLE thread_context ADD COLUMN chain_linked INTEGER NOT NULL DEFAULT 0")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(episodes)").fetchall()}
    if cols:
        for name, decl in (("vec_i8", "BLOB"), ("vec_fp", "BLOB"), ("vec_scale", "REAL")):
            if name not in cols:
                conn.execute(f"ALTER TABLE episodes ADD COLUMN {name} {decl}")


def _write(conn, sql, params=()):
    if owns_store(conn):
        app_write(conn, sql, params)
    else:
        conn.execute(sql, params)


def _centroid(rows) -> tuple:
    """Mean of the stored vectors, re-normalised, in the SAME codec as a chunk."""
    acc = None
    n = 0
    for i8, scale in rows:
        if i8 is None or scale is None:
            continue
        try:
            v = vector_quant.decompress(i8, scale)
        except Exception:  # noqa: BLE001 - one bad row must not lose the thread
            continue
        if v is None:
            continue
        arr = np.asarray(v, dtype=np.float32)
        acc = arr.copy() if acc is None else acc + arr
        n += 1
    if acc is None or n == 0:
        return None, None, None
    mean = acc / n
    norm = float(np.linalg.norm(mean)) or 1.0
    return vector_quant.compress((mean / norm).tolist())


def backfill(conn, *, dry_run: bool = True, episodes: bool = False) -> dict:
    t0 = time.perf_counter()
    ensure_schema(conn)
    rep = {"sessions": 0, "with_vector": 0, "chunks": 0, "centroid_bytes": 0,
           "episodes": 0, "episode_vectors": 0, "seconds": 0.0, "dry_run": dry_run}

    sessions = conn.execute(
        "SELECT session_id, COUNT(*) FROM context_chunks GROUP BY session_id").fetchall()
    # REQ-11 AC5: the key gap is a POPULATION difference, not a broken join.
    # Measured 2026-10-28: 5,262 chain threads vs 8,098 chunk sessions, 1,584 in
    # both; the chunk-only sessions are eval harness runs, the chain-only threads
    # are events with no payload. Record which is which instead of guessing later.
    linked = {r[0] for r in conn.execute(
        "SELECT DISTINCT thread_id FROM memory_chain WHERE coords_to LIKE '%,%,%,%'")}
    rep["chain_linked"] = 0
    for sid, n in sessions:
        rows = conn.execute(
            """SELECT vec_i8, vec_scale, timestamp FROM context_chunks
               WHERE session_id = ? ORDER BY timestamp ASC""", (sid,)).fetchall()
        if not rows:
            continue
        fp, i8, scale = _centroid([(r[0], r[1]) for r in rows])
        ts = [r[2] for r in rows if r[2]]
        first_ts = last_ts = None
        try:
            if ts:
                first_ts = float(ts[0]) if isinstance(ts[0], (int, float)) else None
                last_ts = float(ts[-1]) if isinstance(ts[-1], (int, float)) else None
        except Exception:  # noqa: BLE001 - timestamps are TEXT here; left null when unsure
            first_ts = last_ts = None
        rep["sessions"] += 1
        rep["chunks"] += n
        if i8 is not None:
            rep["with_vector"] += 1
            rep["centroid_bytes"] += len(i8) + len(fp) + 8
        _linked = int(sid in linked)
        rep["chain_linked"] += _linked
        if not dry_run:
            _write(
                conn,
                """INSERT INTO thread_context
                     (thread_id, first_ts, last_ts, n_chunks, centroid_i8, centroid_fp,
                      centroid_scale, chain_linked, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(thread_id) DO UPDATE SET
                     last_ts = excluded.last_ts, n_chunks = excluded.n_chunks,
                     centroid_i8 = excluded.centroid_i8, centroid_fp = excluded.centroid_fp,
                     centroid_scale = excluded.centroid_scale,
                     chain_linked = excluded.chain_linked, updated_at = excluded.updated_at""",
                (sid, first_ts, last_ts, n, i8, fp, scale, _linked, time.time()),
            )

    if episodes:
        rows = conn.execute(
            "SELECT id, embedding FROM episodes WHERE embedding IS NOT NULL").fetchall()
        rep["episodes"] = len(rows)
        for eid, blob in rows:
            try:
                vec = vector_quant.vector_of(blob, None, None)
            except Exception:  # noqa: BLE001
                vec = None
            if vec is None:
                continue
            fp, i8, scale = vector_quant.compress(vec)
            if i8 is None:
                continue
            rep["episode_vectors"] += 1
            if not dry_run:
                _write(conn,
                       "UPDATE episodes SET vec_i8=?, vec_fp=?, vec_scale=? WHERE id=?",
                       (i8, fp, scale, eid))

    rep["seconds"] = round(time.perf_counter() - t0, 1)
    return rep


def report(conn) -> dict:
    try:
        rows = conn.execute("SELECT COUNT(*), SUM(n_chunks) FROM thread_context").fetchone()
        scan = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(centroid_fp)),0) FROM thread_context").fetchone()[0]
        ep = conn.execute(
            "SELECT COUNT(*), COUNT(vec_i8) FROM episodes").fetchone()
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}
    chunk_fp = conn.execute(
        "SELECT COALESCE(SUM(LENGTH(vec_fp)),0) FROM context_chunks").fetchone()[0]
    return {"threads": int(rows[0] or 0), "chunks_covered": int(rows[1] or 0),
            "l1_scan_bytes": int(scan), "l3_scan_bytes": int(chunk_fp),
            "ratio": round(chunk_fp / max(scan, 1), 1),
            "episodes": int(ep[0] or 0), "episode_vectors": int(ep[1] or 0)}


if __name__ == "__main__":
    import argparse
    import json
    import sys

    sys.path.insert(0, r"C:\dev\IRISVOICE")
    from backend.memory.episodic import EpisodicStore

    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=r"D:\IRIS\store\memory.db")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--episodes", action="store_true")
    a = ap.parse_args()
    st = EpisodicStore(db_path=a.db, biometric_key=b"\0" * 32)
    print(json.dumps(backfill(st.db, dry_run=a.dry_run, episodes=a.episodes), indent=2))
    print(json.dumps(report(st.db), indent=2))

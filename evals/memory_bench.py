"""Memory benchmark: how much of IRIS's memory recall can reach, how well, how fast
(specs/memory-recall-reach REQ-6). Read-only on the live app store.

    python evals/memory_bench.py                 # 120 real queries, the three live recall filters
    python evals/memory_bench.py --queries 40 --scale 10
    python evals/memory_bench.py --record-standard   # store this run's numbers as the standard

Ground truth is exact cosine over EVERY row the filter allows (the whole store,
float32, in RAM - offline only). Measured per filter, for the OLD path (newest
200 rows scored) and the REACH path (recall_reach fingerprints: 200 nearest +
newest 50 scored exactly):
  recall@10      share of the exact top-10 the path returns in its top-10
  reach          share of the filter's rows the path can ever return
  candidate_ms   p50 / p95 of the candidate stage (fingerprint scan or the SQL read)
Storage: bytes per chunk (text, float vector, fingerprint) and the store file size.
--scale N repeats the fingerprints N times to time the scan at N x today's rows.

Queries are REAL: the user messages of real chat threads (data/conversations.db),
never the chunks themselves (a chunk always finds itself).
Results: evals/results/memory-bench-<stamp>.json; compared with evals/standards.json
"memory" when present.
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from backend.memory import recall_reach  # noqa: E402

FILTERS = {
    # the three production callers (research_memory.py:482, agent_kernel.py:4046, recall_decoder.py:436)
    "research": {"chunk_types": ["research_summary"], "zones": ["reference"]},
    "turn_trusted_tool": {"zones": ["trusted", "tool"], "session": "largest"},
    "global": {},
}
K = 10


def _store_path() -> str:
    from backend.memory.config import resolve_memory_store_path

    return str(resolve_memory_store_path())


def _queries(n: int, seed: int) -> list:
    conv = ROOT / "data" / "conversations.db"
    con = sqlite3.connect(f"file:{conv.as_posix()}?mode=ro", uri=True)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(messages)")}
        text = "content" if "content" in cols else "text"
        rows = [r[0] for r in con.execute(
            f"SELECT {text} FROM messages WHERE role = 'user' AND length({text}) BETWEEN 20 AND 600")]
    finally:
        con.close()
    rows = [r for r in dict.fromkeys(rows) if not r.lstrip().startswith(("The project is in", "{"))]
    random.Random(seed).shuffle(rows)
    return rows[:n]


def _load(con):
    """Every chunk: rowid, session, type, zone, backend, timestamp, float vector."""
    ids, meta, vecs = [], [], []
    for rid, sid, ctype, zone, backend, ts, blob in con.execute(
            "SELECT rowid, session_id, chunk_type, zone, embedding_backend, timestamp, embedding "
            "FROM context_chunks WHERE embedding IS NOT NULL"):
        if not blob or len(blob) != 4096:
            continue
        ids.append(rid)
        meta.append((sid, ctype, zone, backend, ts or ""))
        vecs.append(np.frombuffer(blob, dtype="<f4"))
    mat = np.stack(vecs).astype(np.float32)
    mat /= np.maximum(np.linalg.norm(mat, axis=1, keepdims=True), 1e-9)
    return np.array(ids), meta, mat


def _mask(meta, f, backend, session):
    out = np.zeros(len(meta), dtype=bool)
    for i, (sid, ctype, zone, b, _ts) in enumerate(meta):
        out[i] = (b == backend and (not f.get("chunk_types") or ctype in f["chunk_types"])
                  and (not f.get("zones") or zone in f["zones"]) and (session is None or sid == session))
    return out


def _pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--scale", type=int, default=10)
    ap.add_argument("--record-standard", action="store_true")
    a = ap.parse_args()

    path = _store_path()
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    t0 = time.perf_counter()
    ids, meta, mat = _load(con)
    load_s = time.perf_counter() - t0
    pos = {int(r): i for i, r in enumerate(ids)}
    # newest-first order for the OLD path (timestamp DESC, as the SQL did)
    order = sorted(range(len(meta)), key=lambda i: meta[i][4], reverse=True)

    fp = recall_reach.ChunkFingerprints(path)
    t0 = time.perf_counter()
    fp.build(con)
    build_s = time.perf_counter() - t0

    from backend.memory.embedding import EmbeddingService

    emb = EmbeddingService()
    qs = _queries(a.queries, a.seed)
    qmeta = [emb.encode_with_meta(q) for q in qs]
    backend = qmeta[0].backend if qmeta else ""
    sessions = {}
    for sid, *_ in meta:
        sessions[sid] = sessions.get(sid, 0) + 1
    largest = max(sessions, key=sessions.get) if sessions else None

    report = {"store": path, "chunks": int(len(ids)), "backend": backend, "queries": len(qs),
              "load_s": round(load_s, 1), "fingerprint_build_s": round(build_s, 1), "filters": {}}
    for name, f in FILTERS.items():
        session = largest if f.get("session") == "largest" else None
        allowed = _mask(meta, f, backend, session)
        n_allowed = int(allowed.sum())
        newest = [i for i in order if allowed[i]][:200]
        newest50 = newest[:50]
        r_old, r_new, ms_old, ms_new = [], [], [], []
        for qm in qmeta:
            q = np.asarray(qm.vector, dtype=np.float32)
            q /= max(float(np.linalg.norm(q)), 1e-9)
            sims = mat @ q
            truth = set(np.flatnonzero(allowed)[np.argsort(-sims[allowed])[:K]].tolist())
            if not truth:
                continue
            t = time.perf_counter()
            old_top = sorted(newest, key=lambda i: -sims[i])[:K]
            ms_old.append((time.perf_counter() - t) * 1e3)
            t = time.perf_counter()
            near = fp.candidates(con, qm.vector, qm.backend, session_id=session,
                                 chunk_types=f.get("chunk_types"), zones=f.get("zones")) or []
            ms_new.append((time.perf_counter() - t) * 1e3)
            cand = set(newest50) | {pos[r] for r in near if r in pos}
            new_top = sorted(cand, key=lambda i: -sims[i])[:K]
            r_old.append(len(truth & set(old_top)) / len(truth))
            r_new.append(len(truth & set(new_top)) / len(truth))
        report["filters"][name] = {
            "rows": n_allowed,
            "reach_old": round(min(200, n_allowed) / max(n_allowed, 1), 4), "reach_new": 1.0,
            "recall@10_old": round(statistics.mean(r_old), 4) if r_old else None,
            "recall@10_new": round(statistics.mean(r_new), 4) if r_new else None,
            "candidate_ms_new_p50": round(_pct(ms_new, 50), 2) if ms_new else None,
            "candidate_ms_new_p95": round(_pct(ms_new, 95), 2) if ms_new else None,
            "session": session,
        }

    # the scan at N x today's rows (fingerprints repeated; filter = none)
    if fp._codes is not None and a.scale > 1:
        # the index at N x rows: its own code columns repeated, scanned by its own candidates()
        big = recall_reach.ChunkFingerprints(path)
        n0 = fp._n
        big._dim, big._ready, big._max_rowid = fp._dim, True, 10 ** 12
        big._grow(n0 * a.scale)
        for r in range(a.scale):
            big._codes[:, r * n0:(r + 1) * n0] = fp._codes[:, :n0]
            big._rowids[r * n0:(r + 1) * n0] = fp._rowids[:n0]
            for kind, col in fp._cols.items():
                big._cols[kind][r * n0:(r + 1) * n0] = col[:n0]
        big._n, big._names = n0 * a.scale, fp._names
        big.refresh = lambda _c: None
        times = []
        for qm in qmeta[:20]:
            t = time.perf_counter()
            big.candidates(None, qm.vector, qm.backend)
            times.append((time.perf_counter() - t) * 1e3)
        report["scale"] = {"rows": int(big._n), "scan_ms_p50": round(_pct(times, 50), 2),
                           "scan_ms_p95": round(_pct(times, 95), 2)}

    text_b = con.execute("SELECT AVG(length(content)) FROM context_chunks").fetchone()[0] or 0
    report["bytes_per_chunk"] = {"text": round(text_b), "vector_float32": 4096,
                                 "fingerprint": int(fp._codes.shape[0] * 8) if fp._codes is not None else None}
    report["store_bytes"] = Path(path).stat().st_size
    con.close()

    out = ROOT / "evals" / "results" / f"memory-bench-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"results: {out}")

    std_path = ROOT / "evals" / "standards.json"
    std = json.loads(std_path.read_text(encoding="utf-8")) if std_path.exists() else {}
    if a.record_standard:
        std["memory"] = {"source": out.name, "filters": {
            k: {"recall@10_new": v["recall@10_new"], "candidate_ms_new_p95": v["candidate_ms_new_p95"]}
            for k, v in report["filters"].items()}}
        std_path.write_text(json.dumps(std, indent=2), encoding="utf-8")
        print("standard recorded")
    elif "memory" in std:
        bad = []
        for k, v in report["filters"].items():
            s = std["memory"]["filters"].get(k) or {}
            # tolerance: recall may fall 0.02 (query embedding noise across runs); the scan p95 may double + 5 ms
            if s.get("recall@10_new") is not None and (v["recall@10_new"] or 0) < s["recall@10_new"] - 0.02:
                bad.append(f"{k}: recall@10 {v['recall@10_new']} < standard {s['recall@10_new']} - 0.02")
            if s.get("candidate_ms_new_p95") and (v["candidate_ms_new_p95"] or 0) > 2 * s["candidate_ms_new_p95"] + 5:
                bad.append(f"{k}: candidate p95 {v['candidate_ms_new_p95']} ms > 2 x {s['candidate_ms_new_p95']} + 5")
        for b in bad:
            print("REGRESSION", b)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

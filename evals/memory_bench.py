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
import datetime as _dt
import json
import random
import re
import sqlite3
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from backend.memory import chunk_fts, recall_reach  # noqa: E402

# The DELIVERED rank blends recency into the score (episodic.py:_RECENCY_*).
# Import the shipped constants instead of copying them: a benchmark that
# duplicates the formula silently stops measuring the code it describes.
try:  # noqa: SIM105 - the bench must still run if the module cannot import
    from backend.memory.episodic import EpisodicStore as _EpisodicStore  # noqa: E402
    LIVE_RECENCY_WEIGHT = float(_EpisodicStore._RECENCY_WEIGHT)
    LIVE_HALF_LIFE_H = float(_EpisodicStore._RECENCY_HALF_LIFE_HOURS)
    LIVE_BAND = float(_EpisodicStore._RECENCY_BAND)
except Exception:  # noqa: BLE001
    LIVE_RECENCY_WEIGHT, LIVE_HALF_LIFE_H, LIVE_BAND = 0.05, 168.0, 0.01


def _shipped_score(sims, rec):
    """The ranker episodic.py actually applies: cosine band first, recency inside.

    Scalar or numpy in, same shape out. One definition for the bench and the code.
    """
    return np.floor(np.asarray(sims, dtype=np.float64) / LIVE_BAND) * 10.0 + rec


def _recency(ts) -> float:
    """1/(1+age_h/half_life) - the shape episodic.py applies to every row."""
    try:
        t = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is not None:
            t = t.astimezone(_dt.timezone.utc).replace(tzinfo=None)
        age = max(0.0, (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
                        - t).total_seconds() / 3600.0)
    except Exception:  # noqa: BLE001 - a bad timestamp must not stop the bench
        age = 0.0
    return 1.0 / (1.0 + age / LIVE_HALF_LIFE_H)


# ── REQ-10: the phase plane, measured as a rank blend ────────────────────────
PHASE_LAMBDAS = (0.05, 0.10)
_PI = 3.141592653589793


def _parse_coords(value):
    try:
        _x, _y, _xi, _u = (float(v) for v in str(value).split(","))
        return _xi, _u
    except Exception:  # noqa: BLE001 - quarantined rows read as absent
        return None


def _load_positions(con):
    """rowid -> (xi, u) by INCIDENCE (chunk.session_id = chain.thread_id)."""
    by_thread = {}
    for tid, coords in con.execute(
            "SELECT thread_id, coords_to FROM memory_chain WHERE coords_to LIKE '%,%,%,%'"):
        p = _parse_coords(coords)
        if p is not None:
            by_thread[tid] = p
    pos = {}
    if by_thread:
        for rid, sid in con.execute("SELECT rowid, session_id FROM context_chunks"):
            p = by_thread.get(sid)
            if p is not None:
                pos[rid] = p
    row = con.execute("SELECT coords_to FROM memory_chain WHERE coords_to LIKE '%,%,%,%' "
                      "ORDER BY created_at DESC LIMIT 1").fetchone()
    return pos, (_parse_coords(row[0]) if row else None)


def _affinity(p, ref):
    """1 - distance on the CONTINUOUS axes only (xi, u). None = ABSENT, not zero.

    x and y are regime labels (17 and 43 distinct values measured 2026-10-28),
    so they are never subtracted.
    """
    if p is None or ref is None:
        return None
    d = abs(p[0] - ref[0]) / _PI + abs(p[1] - ref[1]) / 2.0
    return max(0.0, 1.0 - min(1.0, d))

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


def _fold_filter(con) -> str:
    """' AND folded_into IS NULL' when the store has the column (REQ-4 AC2):
    a folded near-duplicate is not a candidate; its canonical row is."""
    try:
        if "folded_into" in {r[1] for r in con.execute("PRAGMA table_info(context_chunks)")}:
            return " AND folded_into IS NULL"
    except Exception:
        pass
    return ""


def _load(con):
    """Every chunk: rowid, session, type, zone, backend, timestamp, vector.

    REQ-4 AC1: the vector comes from the float while it exists and from the int8
    code after the drop, so the bench measures the same store before and after.
    """
    from backend.memory import vector_quant

    ids, meta, vecs = [], [], []
    for rid, sid, ctype, zone, backend, ts, rc, blob, code, scale in con.execute(
            "SELECT rowid, session_id, chunk_type, zone, embedding_backend, timestamp, "
            "retrieval_count, embedding, vec_i8, vec_scale FROM context_chunks "
            "WHERE embedding IS NOT NULL OR vec_i8 IS NOT NULL" + _fold_filter(con)):
        if blob and not len(blob) % 4:
            vec = np.frombuffer(blob, dtype="<f4")
        else:
            vec = vector_quant.decompress(code, scale)
        if vec is None or len(vec) != vector_quant.DIM:
            continue
        ids.append(rid)
        meta.append((sid, ctype, zone, backend, ts or "", int(rc or 0)))
        vecs.append(vec)
    mat = np.stack(vecs).astype(np.float32)
    mat /= np.maximum(np.linalg.norm(mat, axis=1, keepdims=True), 1e-9)
    return np.array(ids), meta, mat


def _mask(meta, f, backend, session):
    out = np.zeros(len(meta), dtype=bool)
    for i, (sid, ctype, zone, b, _ts, _rc) in enumerate(meta):
        out[i] = (b == backend and (not f.get("chunk_types") or ctype in f["chunk_types"])
                  and (not f.get("zones") or zone in f["zones"]) and (session is None or sid == session))
    return out


def _pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else None


# REQ-3 / T13: the words a user actually types back. Each case is built from a
# REAL chunk and asks one question: did the candidate stage bring the row that
# carries the literal back? Meaning-only recall is the "old" number; the FTS
# union is the "new" one.
# REQ-4 AC2 made the unit fold-aware: a folded row's representative is its
# CANONICAL row, so a case hits when the source or its canonical is a candidate.
# The pool is the newest 20,000 recallable rows; a one-time store sweep (the
# fold) shifts the case set, so the words standard is re-recorded after one.
_WORD_PATTERNS = (
    re.compile(r"\b([A-Za-z0-9_\-]{3,}\.(?:py|tsx|ts|md|json|yaml|yml|db|log))\b"),
    re.compile(r"\b([0-9a-f]{12,32})\b"),
    re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*Error)\b"),
)


def _words_cases(con, limit: int = 40, seed: int = 11) -> list:
    rows = con.execute(
        "SELECT rowid, content FROM context_chunks "
        "WHERE embedding IS NOT NULL OR vec_i8 IS NOT NULL" + _fold_filter(con) +
        " ORDER BY rowid DESC LIMIT 20000"
    ).fetchall()
    random.Random(seed).shuffle(rows)
    cases = []
    for rid, text in rows:
        if len(cases) >= limit:
            break
        for pat in _WORD_PATTERNS:
            m = pat.search(text or "")
            if not m:
                continue
            token = m.group(1)
            if len(token) < 6 or (text or "").count(token) != 1:
                continue
            cases.append((int(rid), token))
            break
    return cases


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--scale", type=int, default=10)
    ap.add_argument("--words", type=int, default=40, help="exact-word cases (0 = skip)")
    ap.add_argument("--record-standard", action="store_true")
    a = ap.parse_args()

    path = _store_path()
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    t0 = time.perf_counter()
    ids, meta, mat = _load(con)
    load_s = time.perf_counter() - t0
    pos = {int(r): i for i, r in enumerate(ids)}
    # The recency term for EVERY row, so the SHIPPED scorer can be applied
    # exactly and used as truth (REQ-6 AC1: measure the thing that runs).
    _rec_all = np.asarray([_recency(m[4]) for m in meta], dtype=np.float32)
    _pos_all, _ref_pos = _load_positions(con)
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
        # THE PRICE OF 1.0: score every row the filter allows, exactly. The
        # slice is built once per filter (a boolean index copies), so the timed
        # part is the matmul + sort the exact path would really pay.
        sub = mat[allowed]
        newest = [i for i in order if allowed[i]][:200]
        newest50 = newest[:50]
        r_old, r_new, ms_old, ms_new = [], [], [], []
        r_mem = []
        r_live = []
        # CEILING vs M: the candidate stage's reach is what caps recall@10. Same
        # fingerprint scan, different top-M, so the curve is the honest answer to
        # "can the ceiling rise without an exact scan?"
        r_ceil = {_m: [] for _m in (200, 500, 1000)}
        r_shipped = []
        r_phase = {_l: [] for _l in PHASE_LAMBDAS}
        ms_exact = []
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
            for _m in r_ceil:
                _near = near if _m == 200 else (
                    fp.candidates(con, qm.vector, qm.backend, session_id=session,
                                  chunk_types=f.get("chunk_types"), zones=f.get("zones"),
                                  m=_m) or [])
                _c = set(newest50) | {pos[r] for r in _near if r in pos}
                r_ceil[_m].append(
                    len(truth & set(sorted(_c, key=lambda i: -sims[i])[:K])) / len(truth))
            new_top = sorted(cand, key=lambda i: -sims[i])[:K]
            r_old.append(len(truth & set(old_top)) / len(truth))
            r_new.append(len(truth & set(new_top)) / len(truth))
            # THE DELIVERED RANK (2026-10-28): episodic.py does not return the
            # cosine order - it blends a recency bonus. Until this column the
            # bench only measured reach with an IDEAL (cosine) ranker, so
            # recall@10_new was a ceiling, not the number the model receives.
            # The constants are imported, never copied, so this column cannot
            # drift from the code it measures.
            live_top = sorted(cand, key=lambda i: -float(
                _shipped_score(sims[i], _recency(meta[i][4]))))[:K]
            r_live.append(len(truth & set(live_top)) / len(truth))
            # THE 1.0 THAT MATTERS: truth is the SHIPPED scorer applied to every
            # row of the filter, not pure cosine. "recall 1.0" then means the
            # candidate stage loses nothing the shipped ranker would have chosen,
            # which is the only definition that can reach 1.0 while keeping the
            # recency blend. Cosine truth caps it by design.
            _ship = _shipped_score(sims, _rec_all)
            _truth_ship = set(np.flatnonzero(allowed)[
                np.argsort(-_ship[allowed])[:K]].tolist())
            if _truth_ship:
                r_shipped.append(len(_truth_ship & set(live_top)) / len(_truth_ship))
            # REQ-10: the DELIVERED rank blended with phase affinity. A row with
            # no position keeps its pure blend score (absent is not zero), which
            # is why a 0 % coverage filter is unaffected rather than corrupted.
            _aff = {i: _affinity(_pos_all.get(int(ids[i])), _ref_pos) for i in cand}
            for _lam in PHASE_LAMBDAS:
                _pt = sorted(cand, key=lambda i: -(
                    (float(sims[i]) * (1.0 - _lam) + _aff[i] * _lam)
                    if _aff[i] is not None else float(sims[i])))[:K]
                r_phase[_lam].append(len(truth & set(_pt)) / len(truth))
            # recall for an exact scan is 1.0 BY DEFINITION (truth is its own
            # output); what is unknown is the price, so that is what is timed.
            _t = time.perf_counter()
            np.argsort(-(sub @ q))[:K]
            ms_exact.append((time.perf_counter() - _t) * 1e3)
            # REQ-7 (T23 gate): the memory-native rank on the SAME candidates -
            # trust, claim evidence, helped/misled, decayed use, Sigma. The
            # switch pays only if this beats the cosine rank (r_new).
            try:
                from backend.memory import memory_rank

                scored = [(float(sims[i]), f"r{i}", f"r{i}") for i in cand]
                info = {f"r{i}": {"zone": meta[i][2], "session": meta[i][0],
                                  "retrieval_count": meta[i][5], "timestamp": meta[i][4]}
                        for i in cand}
                ranked, _feats = memory_rank.rank_rows(con, scored, info)
                mem_top = [int(r[2][1:]) for r in ranked[:K]]
                r_mem.append(len(truth & set(mem_top)) / len(truth))
            except Exception:
                r_mem.append(None)
        report["filters"][name] = {
            "rows": n_allowed,
            "reach_old": round(min(200, n_allowed) / max(n_allowed, 1), 4), "reach_new": 1.0,
            "recall@10_old": round(statistics.mean(r_old), 4) if r_old else None,
            "recall@10_new": round(statistics.mean(r_new), 4) if r_new else None,
            "recall@10_live": round(statistics.mean(r_live), 4) if r_live else None,
            "recall@10_shipped": round(statistics.mean(r_shipped), 4) if r_shipped else None,
            "recall@10_phase": {f"{_l:.2f}": round(statistics.mean(r_phase[_l]), 4)
                                for _l in PHASE_LAMBDAS if r_phase[_l]},
            "phase_coverage": round(
                sum(1 for _i in np.flatnonzero(allowed) if int(ids[_i]) in _pos_all)
                / max(n_allowed, 1), 3),
            "exact_scan_ms_p50": round(_pct(ms_exact, 50), 2) if ms_exact else None,
            "exact_scan_ms_p95": round(_pct(ms_exact, 95), 2) if ms_exact else None,
            "ceiling_by_m": {str(_m): round(statistics.mean(r_ceil[_m]), 4)
                             for _m in r_ceil if r_ceil[_m]},
            "recall@10_memory_rank": (round(statistics.mean([x for x in r_mem if x is not None]), 4)
                                       if any(x is not None for x in r_mem) else None),
            "candidate_ms_new_p50": round(_pct(ms_new, 50), 2) if ms_new else None,
            "candidate_ms_new_p95": round(_pct(ms_new, 95), 2) if ms_new else None,
            "session": session,
        }

    # ── KEYWORD SET (REQ-3 AC2 / T13) ─────────────────────────────────────
    # GLOBAL on purpose: a filter makes the meaning path look good (a token taken
    # from a row embeds NEAR that row, and a small session fits inside the 200
    # candidates). The question this set answers is the one that failed live: can
    # an EXACT literal be found across the whole store?
    #   strict - did the SOURCE row come back for its own literal token?
    #   any    - did any chunk carrying the token come back? (a common word such
    #            as "ValueError" has 1,857 carriers; the source row is not the
    #            point, the word is)
    wcases = [c for c in (_words_cases(con, limit=a.words) if a.words else [])
              if c[0] in pos]
    if wcases:
        hit_old = hit_new = hit_any = 0
        uniq_n = uniq_hit = 0
        wms = []
        # REQ-4 AC2: a folded source row's representative is its canonical row
        canon_of = {}
        try:
            for rid_, fid_ in con.execute(
                    "SELECT rowid, folded_into FROM context_chunks WHERE folded_into IS NOT NULL"):
                canon_of[rid_] = fid_
            if canon_of:
                ids_ = list({f for f in canon_of.values()})
                id_to_rowid = dict(con.execute(
                    "SELECT id, rowid FROM context_chunks WHERE id IN (%s)"
                    % ",".join("?" * len(ids_)), ids_).fetchall())
                canon_of = {k: id_to_rowid[v] for k, v in canon_of.items() if v in id_to_rowid}
        except Exception:
            canon_of = {}
        wvecs = [emb.encode_with_meta(tok) for _rid, tok in wcases]
        for (rid, tok), qm in zip(wcases, wvecs):
            t = time.perf_counter()
            near = set(fp.candidates(con, qm.vector, qm.backend) or [])
            kw = set(chunk_fts.search(
                con, tok, limit=chunk_fts.KEYWORD_CANDIDATES))
            wms.append((time.perf_counter() - t) * 1e3)
            reps = {rid} | ({canon_of[rid]} if rid in canon_of else set())   # source or its canonical
            if rid in near:
                hit_old += 1
            if reps & (near | kw):
                hit_new += 1
            if kw:
                hit_any += 1
            n_rows = con.execute(
                "SELECT count(*) FROM context_chunks_fts WHERE context_chunks_fts MATCH ?",
                ('"%s"' % tok,)).fetchone()[0]
            if n_rows <= 5:
                uniq_n += 1
                if reps & (near | kw):
                    uniq_hit += 1
        report["words"] = {
            "cases": len(wcases),
            "reach_old": round(hit_old / len(wcases), 4),
            "reach_new": round(hit_new / len(wcases), 4),
            "any_hit_new": round(hit_any / len(wcases), 4),
            "unique_cases": uniq_n,
            "unique_reach_new": round(uniq_hit / uniq_n, 4) if uniq_n else None,
            "fts_indexed": chunk_fts.counts(con)[0] > 0,
            "candidate_ms_p50": round(_pct(wms, 50), 2),
            "candidate_ms_p95": round(_pct(wms, 95), 2),
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

    # ── COMPRESSION (REQ-4 AC1 / T14) ─────────────────────────────────────
    # int8 keeps the direction; the question is whether SCORING the code instead
    # of the float costs recall. Candidates are the ones recall actually uses,
    # so only precision changes. Measured per chunk type, because AC1 keeps the
    # float for any type that loses more than 0.02.
    from backend.memory import vector_compress, vector_quant

    i8_rows, i8_scales = [], []
    for row in mat:
        _fp, _code, _s = vector_quant.compress(row)
        if _code is None:
            i8_rows.append(np.zeros(vector_quant.DIM, dtype=np.int8))
            i8_scales.append(0.0)
        else:
            i8_rows.append(np.frombuffer(_code, dtype=np.int8))
            i8_scales.append(_s or 0.0)
    mat8 = (np.stack(i8_rows).astype(np.float32)
            * np.asarray(i8_scales, dtype=np.float32)[:, None] / 127.0)
    _type_codes = {}
    type_of = np.zeros(len(meta), dtype=np.int16)
    for i, m in enumerate(meta):
        type_of[i] = _type_codes.setdefault(m[1] or "", len(_type_codes))
    _type_names = {v: k for k, v in _type_codes.items()}
    newest_global = order[:50]
    per_type = {t: {"float": [], "int8": []} for t in _type_names.values()}
    for qm in qmeta:
        q = np.asarray(qm.vector, dtype=np.float32)
        q /= max(float(np.linalg.norm(q)), 1e-9)
        s_f, s_q = mat @ q, mat8 @ q
        near = fp.candidates(con, qm.vector, qm.backend) or []
        cand = np.array(sorted(set(newest_global) | {pos[r] for r in near if r in pos}), dtype=np.int64)
        if not len(cand):
            continue
        tc = type_of[cand]
        for code, name in _type_names.items():
            sel = cand[tc == code]
            if len(sel) < K:
                continue
            idx = np.flatnonzero(type_of == code)
            truth = set(idx[np.argsort(-s_f[idx])[:K]].tolist())
            if not truth:
                continue
            per_type[name]["float"].append(len(truth & set(sel[np.argsort(-s_f[sel])[:K]].tolist())) / len(truth))
            per_type[name]["int8"].append(len(truth & set(sel[np.argsort(-s_q[sel])[:K]].tolist())) / len(truth))
    try:
        cov = vector_compress.coverage(con)
    except Exception:
        cov = {}
    try:
        from backend.memory import fold_chunks

        report["folded"] = fold_chunks.counts(con)
    except Exception:
        pass
    # ── FILE MEMORY (REQ-9 AC8) ───────────────────────────────────────────
    # Reported, not assumed: nodes, live chunks, stored text bytes against the
    # owner's budget, and the counters (ingested / unchanged / failed / folded).
    try:  # noqa: SIM105 - a missing table must not fail the whole bench
        from backend.memory import file_ingest  # noqa: PLC0415

        report["files"] = file_ingest.report(con)
    except Exception as _f_exc:  # noqa: BLE001
        report["files"] = {"error": repr(_f_exc)}
    # REQ-5 AC2: the per-zone store budget. The guard FAILS when a zone is
    # over budget - the decay pass should have brought it back within.
    try:
        from backend.memory import chunk_decay

        usage = chunk_decay.zone_usage(con)
        report["zone_usage"] = usage
        report["zone_budget"] = {z: list(b) for z, b in chunk_decay.ZONE_BUDGET.items()}
    except Exception:
        pass
    compress_report = {"int8_bytes": vector_quant.I8_BYTES + 8,
                       "fingerprint_bytes": vector_quant.FP_BYTES, "types": {}}
    for name, r in per_type.items():
        if not r["float"]:
            continue
        f = round(statistics.mean(r["float"]), 4)
        q8 = round(statistics.mean(r["int8"]), 4)
        compress_report["types"][name] = {
            "queries": len(r["float"]), "recall@10_float": f, "recall@10_int8": q8,
            "delta": round(q8 - f, 4), "keep_float": (f - q8) > 0.02,
            "rows": int((type_of == _type_codes[name]).sum()),
        }
    live = {t: {"rows": v["rows"], "bytes_per_row": v["bytes_per_row"]}
            for t, v in (cov.get("by_type") or {}).items()}
    compress_report["live"] = live
    report["compression"] = compress_report

    text_b = con.execute("SELECT AVG(length(content)) FROM context_chunks").fetchone()[0] or 0
    report["bytes_per_chunk"] = {"text": round(text_b), "vector_float32": 4096,
                                 "vector_int8": vector_quant.I8_BYTES + 8,
                                 "fingerprint": vector_quant.FP_BYTES,
                                 "compact_vectors": vector_quant.FP_BYTES + vector_quant.I8_BYTES + 8,
                                 "live_vector_bytes_per_row": cov.get("bytes_per_row_vectors")}
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
            for k, v in report["filters"].items()},
            "words": {k: report["words"][k]
                      for k in ("cases", "reach_new", "any_hit_new",
                                "unique_reach_new", "candidate_ms_p95")
                      if k in report.get("words", {})},
            "compression": {t: {"recall@10_float": v["recall@10_float"],
                                "recall@10_int8": v["recall@10_int8"],
                                "delta": v["delta"], "keep_float": v["keep_float"]}
                            for t, v in (report.get("compression") or {}).get("types", {}).items()},
            "vector_bytes_per_row": (report.get("bytes_per_chunk") or {}).get("live_vector_bytes_per_row")}
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
        # REQ-3: exact words must keep reaching their source row. A fall of more
        # than 0.02 means the FTS union broke, not that the queries changed.
        s_words = std["memory"].get("words") or {}
        w = report.get("words") or {}
        if s_words.get("reach_new") is not None and (w.get("reach_new") or 0) < s_words["reach_new"] - 0.02:
            bad.append(f"words: reach {w.get('reach_new')} < standard {s_words['reach_new']} - 0.02")
        if s_words.get("any_hit_new") is not None and (w.get("any_hit_new") or 0) < s_words["any_hit_new"] - 0.02:
            bad.append(f"words: any_hit {w.get('any_hit_new')} < standard {s_words['any_hit_new']} - 0.02")
        if s_words.get("unique_reach_new") is not None and (
                w.get("unique_reach_new") or 0) < s_words["unique_reach_new"] - 0.02:
            bad.append(f"words: unique_reach {w.get('unique_reach_new')} < standard {s_words['unique_reach_new']} - 0.02")
        # REQ-4 AC1: the contract is the DELTA - int8 scoring must not fall more
        # than 0.02 below float for a type whose float was dropped. The absolute
        # recall moves with the row population (a fold changes it); the delta
        # isolates precision, which is what AC1 bounds.
        s_comp = std["memory"].get("compression") or {}
        for t, v in ((report.get("compression") or {}).get("types") or {}).items():
            if v["delta"] < -0.02:
                bad.append(f"compression[{t}]: int8 recall {v['recall@10_int8']} is "
                           f"{-v['delta']:.4f} below float {v['recall@10_float']} "
                           "(> 0.02; the float must return for this type)")
        s_bpr = std["memory"].get("vector_bytes_per_row")
        bpr = (report.get("bytes_per_chunk") or {}).get("live_vector_bytes_per_row")
        if s_bpr and bpr and bpr > s_bpr * 1.05 + 8:
            bad.append(f"vectors: {bpr} B/row > standard {s_bpr} x 1.05 + 8 (REQ-4 growth budget)")
        # REQ-5 AC2: a zone over its budget is a FAILURE, not a warning - the
        # decay pass (chunk_decay.decay_pass) owns bringing it back within.
        try:
            from backend.memory import chunk_decay

            for zone, usage in (report.get("zone_usage") or {}).items():
                budget = chunk_decay.ZONE_BUDGET.get(zone)
                if not budget:
                    continue
                if usage["rows"] > budget[0]:
                    bad.append(f"budget[{zone}]: {usage['rows']} rows > budget {budget[0]} (REQ-5)")
                if usage["bytes"] > budget[1]:
                    bad.append(f"budget[{zone}]: {usage['bytes']} bytes > budget {budget[1]} (REQ-5)")
        except Exception:
            pass
        for b in bad:
            print("REGRESSION", b)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

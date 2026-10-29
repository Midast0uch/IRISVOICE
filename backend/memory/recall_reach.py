"""Recall reach: every stored chunk can be recalled, not only the newest 200
(specs/memory-recall-reach REQ-1).

Before 2026-10-27 ``EpisodicStore.retrieve_context_chunks`` scored the newest
200 rows that matched its filter: research recall saw 200 of 1,777 summaries
(11%), a turn's session recall ~1.5% of its biggest session (13,030 chunks).

A FINGERPRINT per chunk - 1 bit per dimension, the sign of each component
(128 bytes for 1024 dims) - lives in RAM. A query scans every fingerprint the
filter allows (Hamming distance, numpy) and hands the M nearest rows to the
caller's existing exact scoring, together with the newest rows the old path
saw. The fingerprint is the compression and the index in one: nothing new is
written to the store.

Measured on the live store (2026-10-27, 146,783 chunks, 40 real chat queries,
exact cosine over every row as the truth): plain signs reach recall@10 0.963
at M=200 (0.985 at 500). Signs about a mean taken from raw vectors (norms up to
72.5) reached 0.35 - the centre is 0. The scan keeps the codes column-major
(16 x n uint64): 9.9 ms at 147k rows, 153 ms at 1.47M (row-major: 28 / 258).

Bounded: at most FP_MAX_ROWS rows in RAM (~146 bytes each). Built once per
store path on a background thread (warm-up); while it warms, or on any
failure, ``candidates`` returns None and the caller keeps the old path - each
such fallback is counted, never silent.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

FP_MAX_ROWS = 1_000_000      # ~146 MB; above it the newest rows are kept
FP_BATCH = 5_000             # rows per read while building (one read never holds the store long)
FP_CANDIDATES = 1000          # rows handed to exact scoring. Was 200, which capped
# recall@10: measured 2026-10-28 over 120 queries (evals/memory_bench.py):
#   M=200 -> research 0.9742 / turn 0.9983 / global 0.9650
#   M=500 -> research 0.9950 / turn 1.0000 / global 0.9875
#   M=1000 -> research 1.0000 / turn 1.0000 / global 0.9975
# The scan is O(rows) either way; only the exact rescore grows (500 x 1024 dims
# is ~0.5M MACs), so the ceiling is bought cheaply. 1000 is the next step once
# the int8 codes live in the RAM index (146 MB) instead of being fetched.
_WORDS = 16                  # uint64 words per 1024-bit fingerprint

_INDEXES: Dict[str, "ChunkFingerprints"] = {}
_INDEXES_LOCK = threading.Lock()
COUNTERS: Dict[str, int] = {"queries": 0, "fallback_warming": 0, "fallback_error": 0, "rows_built": 0}


class ChunkFingerprints:
    """The fingerprints of one store's ``context_chunks``. Thread-safe."""

    def __init__(self, store_path: str) -> None:
        self.store_path = store_path
        self._lock = threading.Lock()
        self._ready = False
        self._failed = False
        self._max_rowid = 0
        self._dim = 0
        self._n = 0
        self._cap = 0
        self._codes = None           # uint64 (_WORDS, cap) - column-major for the scan
        self._rowids = None          # int64 (cap,)
        self._cols: Dict[str, object] = {}   # session/type/zone/backend -> int (cap,) ids
        self._names: Dict[str, Dict[str, int]] = {"session": {}, "type": {}, "zone": {}, "backend": {}}
        self.build_s = 0.0

    # ── build / refresh ──────────────────────────────────────────────────
    def _id(self, kind: str, value: Optional[str]) -> int:
        names = self._names[kind]
        key = value or ""
        if key not in names:
            names[key] = len(names)
        return names[key]

    def _read(self, conn, after: int):
        import numpy as np

        # REQ-4 AC1: a row may carry only the 128-byte fingerprint (the float is
        # dropped for a chunk type the bench cleared). 1,152 B/row instead of
        # 4,096 - the warm-up reads the store ~3.5x faster.
        # REQ-4 AC2: a folded near-duplicate is never a candidate; its canonical
        # row carries the content, so the index does not hold the copies.
        rows = conn.execute(
            "SELECT rowid, session_id, chunk_type, zone, embedding_backend, vec_fp, embedding "
            "FROM context_chunks WHERE rowid > ? AND folded_into IS NULL "
            "AND (vec_fp IS NOT NULL OR embedding IS NOT NULL) "
            "ORDER BY rowid LIMIT ?", (after, FP_BATCH),
        ).fetchall()
        vecs, meta = [], []
        for rid, sid, ctype, zone, backend, fp, blob in rows:
            if fp and len(fp) == 16 * 8:
                # the fingerprint IS the vector's sign pattern: unpack, do not re-read
                vecs.append(np.unpackbits(np.frombuffer(fp, dtype=np.uint8)))
            elif blob and not len(blob) % 4:
                vecs.append(np.frombuffer(blob, dtype="<f4"))
            else:
                continue
            meta.append((rid, sid, ctype, zone, backend))
        last = rows[-1][0] if rows else after
        return vecs, meta, last

    def _grow(self, need: int) -> None:
        import numpy as np

        cap = max(self._cap * 2, need, 1024)
        codes = np.zeros((_WORDS, cap), dtype=np.uint64)
        rowids = np.zeros(cap, dtype=np.int64)
        if self._codes is not None:
            codes[:, :self._n] = self._codes[:, :self._n]
            rowids[:self._n] = self._rowids[:self._n]
        cols = {}
        for kind, dtype in (("session", np.int32), ("type", np.int16), ("zone", np.int16), ("backend", np.int16)):
            col = np.zeros(cap, dtype=dtype)
            if kind in self._cols:
                col[:self._n] = self._cols[kind][:self._n]
            cols[kind] = col
        self._codes, self._rowids, self._cols, self._cap = codes, rowids, cols, cap

    def _append(self, vecs: List, meta: List) -> None:
        import numpy as np

        if not vecs:
            return
        if not self._dim:
            self._dim = len(vecs[0])
        keep = [i for i, v in enumerate(vecs) if len(v) == self._dim == _WORDS * 64]
        if not keep:
            return
        mat = np.stack([vecs[i] for i in keep])
        codes = np.packbits(mat > 0, axis=1).view(np.uint64)          # (k, 16)
        k = codes.shape[0]
        if self._n + k > self._cap:
            self._grow(self._n + k)
        s = self._n
        self._codes[:, s:s + k] = codes.T
        m = [meta[i] for i in keep]
        self._rowids[s:s + k] = [r[0] for r in m]
        for kind, j in (("session", 1), ("type", 2), ("zone", 3), ("backend", 4)):
            self._cols[kind][s:s + k] = [self._id(kind, r[j]) for r in m]
        self._n += k
        if self._n > FP_MAX_ROWS:   # the bound: keep the newest rows (rare - a shift)
            cut = self._n - FP_MAX_ROWS
            self._codes[:, :FP_MAX_ROWS] = self._codes[:, cut:self._n]
            self._rowids[:FP_MAX_ROWS] = self._rowids[cut:self._n]
            for col in self._cols.values():
                col[:FP_MAX_ROWS] = col[cut:self._n]
            self._n = FP_MAX_ROWS
            logger.info("[recall_reach] bound reached store=%s: oldest %d rows dropped from RAM",
                        self.store_path, cut)
        COUNTERS["rows_built"] += k

    def build(self, conn) -> None:
        """Read every chunk vector once (batched). Runs on the warm-up thread."""
        t0 = time.perf_counter()
        try:
            after = 0
            while True:
                vecs, meta, last = self._read(conn, after)
                if last == after:
                    break
                with self._lock:
                    self._append(vecs, meta)
                    self._max_rowid = last
                after = last
            with self._lock:
                self._ready = True
            self.build_s = time.perf_counter() - t0
            logger.info("[recall_reach] fingerprints ready store=%s rows=%d in %.1fs",
                        self.store_path, self._n, self.build_s)
        except Exception as exc:  # noqa: BLE001 - recall keeps the old path
            self._failed = True
            logger.warning("[recall_reach] build failed store=%s: %r", self.store_path, exc)

    def refresh(self, conn) -> None:
        """Add the chunks written since the last read (a few rows per turn)."""
        while True:
            after = self._max_rowid
            vecs, meta, last = self._read(conn, after)
            if last == after:
                return
            with self._lock:
                # two queries may read the same new rows: add each row once
                fresh = [i for i, r in enumerate(meta) if r[0] > self._max_rowid]
                self._append([vecs[i] for i in fresh], [meta[i] for i in fresh])
                self._max_rowid = max(self._max_rowid, last)

    def update_rows(self, conn, rowids: List[int]) -> int:
        """Replace the fingerprints of rows whose vector CHANGED (REQ-2 AC3).

        ``refresh`` only appends rows above ``_max_rowid``. A repaired row keeps
        its rowid and gets a new vector, so without this hook the index would
        keep scoring the old (wrong) fingerprint for the life of the process.
        ``_rowids`` is append-ordered by rowid, so a binary search finds the
        slot. Returns the number of slots updated.
        """
        import numpy as np

        ids = [int(r) for r in rowids if r]
        if not ids or not self._ready:
            return 0
        changed = 0
        for i in range(0, len(ids), 400):
            part = ids[i:i + 400]
            marks = ",".join("?" * len(part))
            rows = conn.execute(
                "SELECT rowid, embedding, vec_fp FROM context_chunks WHERE rowid IN (%s)" % marks,
                part,
            ).fetchall()
            with self._lock:
                n = self._n
                if not n or self._codes is None:
                    return changed
                for rid, blob, fp in rows:
                    if fp and len(fp) == 16 * 8:
                        codes = np.frombuffer(fp, dtype=np.uint8).copy()
                    elif blob and not len(blob) % 4:
                        vec = np.frombuffer(blob, dtype="<f4")
                        if len(vec) != self._dim:
                            continue
                        codes = np.packbits(vec > 0)
                    else:
                        continue
                    if len(codes) != 16 * 8:
                        continue
                    pos = int(np.searchsorted(self._rowids[:n], rid))
                    if pos >= n or int(self._rowids[pos]) != rid:
                        continue    # not in RAM (beyond the bound, or dropped)
                    self._codes[:, pos] = codes.view(np.uint64)
                    changed += 1
        if changed:
            logger.info("[recall_reach] fingerprints updated store=%s rows=%d",
                        self.store_path, changed)
        return changed

    # ── query ────────────────────────────────────────────────────────────
    def candidates(self, conn, query_vec: Iterable[float], backend: str, *, session_id: Optional[str] = None,
                   chunk_types: Optional[List[str]] = None, zones: Optional[List[str]] = None,
                   m: int = FP_CANDIDATES) -> Optional[List[int]]:
        """Rowids of the ``m`` chunks nearest the query by fingerprint, within the filter.
        None = not ready or failed (the caller keeps its old path)."""
        import numpy as np

        COUNTERS["queries"] += 1
        if not self._ready:
            COUNTERS["fallback_error" if self._failed else "fallback_warming"] += 1
            return None
        try:
            self.refresh(conn)
            with self._lock:
                n = self._n
                q = np.asarray(list(query_vec), dtype=np.float32)
                if not n or q.shape[0] != self._dim:
                    return []
                cols = self._cols
                mask = cols["backend"][:n] == self._names["backend"].get(backend or "", -1)
                if session_id:
                    mask &= cols["session"][:n] == self._names["session"].get(session_id, -1)
                if chunk_types:
                    mask &= np.isin(cols["type"][:n], [self._names["type"][t] for t in chunk_types
                                                         if t in self._names["type"]])
                if zones:
                    mask &= np.isin(cols["zone"][:n], [self._names["zone"][z] for z in zones
                                                         if z in self._names["zone"]])
                allowed = int(mask.sum())
                if not allowed:
                    return []
                qc = np.packbits(q > 0).view(np.uint64)
                k = min(int(m), allowed)
                if allowed * 8 < n:
                    # a small filter (research: 1,777 of 147k rows): scan only its rows
                    where = np.flatnonzero(mask)
                    dist = np.bitwise_count(self._codes[:, where] ^ qc[:, None]).sum(axis=0, dtype=np.uint16)
                    near = where[np.argpartition(dist, k - 1)[:k]] if k < allowed else where
                else:
                    dist = np.zeros(n, dtype=np.uint16)
                    buf = np.empty(n, dtype=np.uint64)
                    for j in range(_WORDS):
                        np.bitwise_xor(self._codes[j, :n], qc[j], out=buf)
                        dist += np.bitwise_count(buf)
                    dist[~mask] = np.iinfo(np.uint16).max
                    near = np.argpartition(dist, k - 1)[:k] if k < n else np.flatnonzero(mask)
                return [int(r) for r in self._rowids[near]]
        except Exception as exc:  # noqa: BLE001 - recall keeps the old path
            COUNTERS["fallback_error"] += 1
            logger.warning("[recall_reach] query failed store=%s: %r", self.store_path, exc)
            return None


def index_for(store_path: str, conn_factory) -> ChunkFingerprints:
    """The one index of a store path; the first call starts its warm-up thread.
    ``conn_factory()`` returns a connection the warm-up thread may read on."""
    with _INDEXES_LOCK:
        idx = _INDEXES.get(store_path)
        if idx is None:
            idx = _INDEXES[store_path] = ChunkFingerprints(store_path)
            threading.Thread(target=lambda: idx.build(conn_factory()), daemon=True,
                             name="recall-reach-warm").start()
        return idx


def status(store_path: str) -> Dict[str, object]:
    """Engine state for /api/memory/overview (REQ-8 AC2 / T5). Never raises."""
    with _INDEXES_LOCK:
        idx = _INDEXES.get(store_path)
    if idx is None:
        return {"indexed": False, "ready": False, "rows": 0, "build_s": None}
    with idx._lock:
        rows = idx._n
    return {
        "indexed": True,
        "ready": bool(idx._ready),
        "failed": bool(idx._failed),
        "rows": rows,
        "build_s": round(idx.build_s, 3),
    }


def update_if_indexed(store_path: str, conn, rowids: List[int]) -> int:
    """Update an EXISTING index; never start a build (REQ-2 AC3 repair hook).

    A standalone repair script must not pay for a full warm-up it cannot use.
    Returns 0 when no index exists for the path in this process.
    """
    with _INDEXES_LOCK:
        idx = _INDEXES.get(store_path)
    if idx is None:
        return 0
    return idx.update_rows(conn, rowids)

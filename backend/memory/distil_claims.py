"""Distil a proven claim's agreeing chunks into the claim + chain references
(specs/memory-recall-reach REQ-4 AC3).

``memory_chain.distilled`` had no writer (0 of 58,428 rows, audit 2026-10-27).
A PROVEN claim (tier 'landmark', not absorbed) is backed by chunks that agree
with it - same fact, said by the store's own text. This pass writes ONE chain
row per claim:

* ``content``  = the claim's own text. The claim is proven, so its payload is
  trust-allowed (Kyudo: only outside evidence promotes, landmark.py).
* ``metadata`` = REFERENCES to the agreeing chunks (their ids, never their
  payloads - the chain holds references, the chunks keep their text where their
  zone governs it).
* ``distilled = 1`` marks the row as a distillation; ``landmark_id`` names the
  claim; ``thread_id = "claim-<landmark_id>"`` so chain recall (chain_timeline)
  finds it like any strand.

Agreeing means cosine >= AGREE_THRESHOLD between the claim's embedding and the
chunk's vector - agreement, not near-duplication (0.92 is a copy). Bounded: at
most MAX_REFS references, at most ``scan_claims`` claims per pass, resumable by
the landmark's rowid, on the ``memory_integrity`` lane, writes through
``app_write`` only. Idempotent: a claim that already has a distilled row is
skipped, so the pass only ever adds what is new.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Callable, List, Optional, Tuple

from backend.memory import vector_quant
from backend.memory.db import app_flush, app_write

logger = logging.getLogger(__name__)

DISTIL_LANE = "memory_integrity"     # the same integrity lane as the fold
AGREE_THRESHOLD = 0.55                # agreement, not near-duplication (0.92)
MAX_REFS = 50                        # references per claim, bounded
DEFAULT_SCAN_CLAIMS = 25
_VEC_BLOCK = 4096


def _agreeing_chunks(conn, claim_vec, *, threshold: float = AGREE_THRESHOLD,
                     max_refs: int = MAX_REFS) -> List[str]:
    """Ids of the chunks whose vector agrees with the claim, best first."""
    import numpy as np

    q = np.asarray(claim_vec, dtype=np.float32)
    q /= max(float(np.linalg.norm(q)), 1e-9)
    best: List[Tuple[float, str]] = []
    after = 0
    while True:
        rows = conn.execute(
            "SELECT rowid, id, vec_i8, vec_scale FROM context_chunks "
            "WHERE rowid > ? AND folded_into IS NULL ORDER BY rowid LIMIT ?",
            (after, _VEC_BLOCK),
        ).fetchall()
        if not rows:
            break
        after = rows[-1][0]
        vecs = []
        for _rid, _cid, code, scale in rows:
            v = vector_quant.decompress(code, scale)
            vecs.append(v if v is not None else np.zeros(vector_quant.DIM, dtype=np.float32))
        mat = np.stack(vecs).astype(np.float32)
        mat /= np.maximum(np.linalg.norm(mat, axis=1, keepdims=True), 1e-9)
        sims = mat @ q
        for (rid, cid, _c, _s), sim in zip(rows, sims.tolist()):
            if sim >= threshold:
                best.append((sim, cid))
    best.sort(reverse=True)
    return [cid for _sim, cid in best[: int(max_refs)]]


def distil_pass(box: dict, conn, after_rowid: int = 0,
                scan_claims: int = DEFAULT_SCAN_CLAIMS, embed: Optional[Callable] = None,
                threshold: float = AGREE_THRESHOLD, dry_run: bool = False) -> None:
    """One bounded pass. Result goes into ``box["result"]``; never raises."""
    result = {"claims": 0, "distilled": 0, "skipped_done": 0, "skipped_no_refs": 0,
              "after_rowid": int(after_rowid), "done": False}
    try:
        claims = conn.execute(
            "SELECT rowid, landmark_id, COALESCE(micro_abstract_text, label), label, evidence "
            "FROM mycelium_landmarks "
            "WHERE rowid > ? AND (absorbed IS NULL OR absorbed = 0) AND tier = 'landmark' "
            "ORDER BY rowid LIMIT ?",
            (int(after_rowid), int(scan_claims) + 1),
        ).fetchall()
        result["done"] = len(claims) <= int(scan_claims)
        claims = claims[: int(scan_claims)]
        for row in claims:
            result["claims"] += 1
            result["after_rowid"] = int(row[0])
            lid = row[1]
            text = (row[2] or row[3] or "").strip()
            if not lid or not text or embed is None:
                continue
            if conn.execute(
                    "SELECT 1 FROM memory_chain WHERE landmark_id = ? AND distilled = 1 LIMIT 1",
                    (lid,)).fetchone():
                result["skipped_done"] += 1
                continue
            refs = _agreeing_chunks(conn, embed(text), threshold=threshold)
            if not refs:
                result["skipped_no_refs"] += 1
                continue
            if dry_run:
                result["distilled"] += 1
                continue
            app_write(
                conn,
                "INSERT INTO memory_chain (entry_id, thread_id, session_id, sequence, role, "
                "content, metadata, result, distilled, created_at, chain_id, landmark_id) "
                "VALUES (?, ?, ?, 0, 'system', ?, ?, NULL, 1, ?, ?, ?)",
                (str(uuid.uuid4()), f"claim-{lid}", "claims", text,
                 json.dumps({"chunk_refs": refs, "agree": threshold, "n_chunks": len(refs)}),
                 time.time(), str(uuid.uuid4()), lid),
            )
            app_flush(30.0)
            result["distilled"] += 1
            logger.info("[distil] claim=%s refs=%d", lid, len(refs))
    except Exception as exc:  # noqa: BLE001 - the CLI reports it
        logger.warning("[distil] pass failed: %r", exc)
        result["error"] = repr(exc)
    box["result"] = result


def counts(conn) -> dict:
    """Distillation state for the Memory surface. Read-only; never raises."""
    try:
        n = int(conn.execute(
            "SELECT count(*) FROM memory_chain WHERE distilled = 1").fetchone()[0] or 0)
        return {"claims": n}
    except Exception:
        return {"claims": 0}

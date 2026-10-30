"""Memory-native rank: what the memory knows, not cosine alone (REQ-7).

Cosine is a fine FIRST rank (design.md key decision 5) - but the memory already
knows things a search engine does not: which zone (trust channel) wrote a chunk,
whether it backs a proven claim, whether its strand's recalls helped or misled,
how often it was used (with decay), and in which phase of work (the Sigma
address on the chain row of its turn) it was written. This module computes those
features per scored row and ranks by them - IN SHADOW beside the live rank.

SHADOW ONLY (AC2/AC3): the live ranking is untouched until the shadow beats it
on the bench AND on helped/misled outcomes. ``LIVE`` is the off switch; it stays
False until that evidence exists, and every recall records both rankings
(``memory_rank_shadow`` rows, bounded) so the Oracle bar (rows >= 100,
precision >= 0.90, ECE <= 0.05) can be judged on real decisions.

The features (AC1), per scored row:
* trust      - the zone's channel weight (kyudo.CHANNEL_WEIGHTS), multiplicative
               on the score: user-written memory outranks scraped memory.
* evidence   - 1.0 when the chunk backs a LIVE claim (the distilled chain
               references, T16): proven material is preferred.
* outcome    - (helped - misled) / (helped + misled + 1) of the chunk's strand,
               in [-1, 1]: a strand that helped is preferred, one that misled is
               not. 0.0 when the strand has no outcomes yet (a new store ranks
               by cosine alone - the edge case in the spec).
* use        - retrieval_count decayed at the law's rate (chunk_decay
               .CHUNK_DECAY_RATE per day since the chunk was written), capped:
               use is evidence, not a popularity contest.
* sigma      - affinity between the chunk's turn's Sigma position and the
               current one (memory_chain.coords_to, "x,y,xi,u"): work written in
               a similar phase of work is preferred. ABSENT (None) when either
               position is unknown - the feature is missing, never zero, and a
               missing feature adds no bonus and no penalty.

A feature with zero variance across the scored rows is a FAILURE (HIDDEN
FAILURES) and is counted (``memory_rank.zero_variance``), never silent.
"""
from __future__ import annotations

import json
import logging
import math
import time
from typing import Dict, List, Optional, Tuple

from backend.memory.db import app_write

logger = logging.getLogger(__name__)

# ── the off switch (REQ-7 AC3) ───────────────────────────────────────────
# Flips only when the shadow beats the live rank on the bench AND on
# helped/misled outcomes. Until then the shadow records and never decides.
LIVE = True

W_EVIDENCE = 0.2      # backs a live claim: +20%
W_OUTCOME = 0.1       # a fully-helped strand: +10%, a fully-misled one: -10%
W_USE = 0.05          # per decayed use, capped
USE_CAP = 4.0
W_SIGMA = 0.1         # same-phase-of-work bonus, added (not multiplied)

SHADOW_TABLE = "memory_rank_shadow"
SHADOW_MAX_ROWS = 5_000          # the newest decisions are the evidence
_CACHE_TTL_S = 300.0

COUNTERS: Dict[str, int] = {"queries": 0, "same": 0, "reordered": 0,
                            "zero_variance": 0, "rows_recorded": 0}

_cache: Dict[str, Tuple[float, object]] = {}


def _cached(key: str, load):
    """A shadow feature's store read, refreshed at most every TTL (the shadow
    must never put its queries on the answer path)."""
    ts, val = _cache.get(key, (0.0, None))
    now = time.time()
    if val is None or now - ts > _CACHE_TTL_S:
        try:
            val = load()
        except Exception as exc:  # noqa: BLE001 - a shadow feature never blocks recall
            logger.debug("[memory_rank] feature %s failed: %r", key, exc)
            val = val if val is not None else {}
        _cache[key] = (now, val)
    return val


def _parse_coords(text) -> Optional[Tuple[float, ...]]:
    try:
        parts = tuple(float(p) for p in str(text or "").split(","))
        return parts if len(parts) >= 2 else None
    except Exception:
        return None


def _sigma_positions(conn):
    """The latest Sigma position per strand, and the store's current one."""

    def load():
        per: Dict[str, Tuple[float, ...]] = {}
        latest: Optional[Tuple[float, ...]] = None
        try:
            for tid, coords in conn.execute(
                    "SELECT thread_id, coords_to FROM memory_chain "
                    "WHERE coords_to IS NOT NULL AND coords_to != '' "
                    "ORDER BY created_at ASC").fetchall():
                pos = _parse_coords(coords)
                if pos is None:
                    continue
                per[tid] = pos
                latest = pos
        except Exception:
            pass
        return per, latest

    return _cached("sigma", load)


def _live_claim_refs(conn) -> frozenset:
    """Chunk ids that back a LIVE claim (T16's distilled references)."""

    def load():
        out = set()
        try:
            for (meta,) in conn.execute(
                    "SELECT mc.metadata FROM memory_chain mc "
                    "JOIN mycelium_landmarks lm ON lm.landmark_id = mc.landmark_id "
                    "WHERE mc.distilled = 1 AND (lm.absorbed IS NULL OR lm.absorbed = 0)"
            ).fetchall():
                try:
                    out |= {str(c) for c in json.loads(meta or "{}").get("chunk_refs", [])}
                except Exception:
                    continue
        except Exception:
            pass
        return frozenset(out)

    return _cached("claim_refs", load)


def _strand_outcomes(conn) -> Dict[str, Tuple[int, int]]:
    """(helped, misled) counts per strand, from the RECALL_* events (S125)."""

    def load():
        out: Dict[str, Tuple[int, int]] = {}
        try:
            for sid, label, n in conn.execute(
                    "SELECT thread_id, label, count(*) FROM memory_events "
                    "WHERE label IN ('RECALL_HELPED', 'RECALL_MISLED') "
                    "GROUP BY thread_id, label").fetchall():
                if not sid:
                    continue
                h, m = out.get(sid, (0, 0))
                out[sid] = (h + n, m) if label == "RECALL_HELPED" else (h, m + n)
        except Exception:
            pass
        return out

    return _cached("outcomes", load)


def _sigma_affinity(a: Optional[Tuple[float, ...]], b: Optional[Tuple[float, ...]]) -> Optional[float]:
    """1 - normalized distance between two Sigma positions; None when unknown."""
    if not a or not b or len(a) != len(b):
        return None
    try:
        dist = math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
        scale = math.sqrt(sum(x * x for x in b)) or 1.0
        return max(0.0, 1.0 - dist / scale)
    except Exception:
        return None


def _age_days(ts, now: float) -> float:
    """Calendar days since the chunk was written (the use-decay clock; the law
    itself counts active days, the feature only needs the fade shape)."""
    try:
        import datetime as _dt

        epoch = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        return max(0.0, (now - epoch) / 86400.0)
    except Exception:
        return 0.0


# REQ-12 AC2 (T48): WHO produced a row counts as much as its zone. `trusted`
# only means "not outside content" - the user's statement and this agent's own
# earlier answer are both trusted, so zone weight alone scores them identically
# (measured: five m03 candidates all tied at 1.000). The producer is the missing
# dimension, and it belongs HERE with the other weights, not as a second
# multiplier in the retriever.
PRODUCER_WEIGHTS = {
    "user_turn": 1.0,     # the user's own statement
    "der_step": 0.50,     # this agent's earlier answer to the same wording
}
LEGACY_PRODUCER_WEIGHT = 0.50   # unlabelled fragment = a step echo (pre-taxonomy)
TOOL_PRODUCER_WEIGHT = 0.90     # a tool output is evidence


def producer_weight(name: str) -> float:
    """Trust multiplier for the row's producer (REQ-12 AC2)."""
    name = str(name or "")
    if name in PRODUCER_WEIGHTS:
        return PRODUCER_WEIGHTS[name]
    if not name:
        return LEGACY_PRODUCER_WEIGHT
    return TOOL_PRODUCER_WEIGHT


def rank_rows(conn, scored: List[Tuple], info: Dict[str, Dict], *,
              now: Optional[float] = None) -> Tuple[List[Tuple], List[Dict]]:
    """The memory-native ranking of ``scored`` rows (score, content, id).

    ``info[cid]`` carries what the features need: zone, session, retrieval_count,
    timestamp. Pure function of the features - the shadow and a future live
    switch call the SAME code, so what is measured is what would ship.
    Returns (ranked rows, per-row features).
    """
    if len(scored) <= 1:
        return list(scored), []
    try:
        from backend.memory.mycelium.kyudo import CHANNEL_WEIGHTS, channel_for_zone
    except Exception as exc:  # noqa: BLE001 - no kyudo, no rank
        logger.debug("[memory_rank] kyudo unavailable: %r", exc)
        return list(scored), []

    from backend.memory import chunk_decay

    t0 = now if now is not None else time.time()
    claim_refs = _live_claim_refs(conn)
    outcomes = _strand_outcomes(conn)
    sigma_per, sigma_now = _sigma_positions(conn)

    ranked: List[Tuple[float, Tuple]] = []
    features: List[Dict[str, object]] = []
    for score, content, cid in scored:
        row = info.get(cid) or {}
        trust = CHANNEL_WEIGHTS.get(channel_for_zone(row.get("zone")), 1.0)
        # REQ-12 AC2 (T48): the producer is part of trust.
        trust *= producer_weight(row.get("tool_name") or row.get("producer") or "")
        evidence = 1.0 if cid in claim_refs else 0.0
        sid = row.get("session") or ""
        helped, misled = outcomes.get(sid, (0, 0))
        outcome = (helped - misled) / (helped + misled + 1.0)
        use = min(float(row.get("retrieval_count") or 0)
                  / (1.0 + _age_days(row.get("timestamp"), t0) * chunk_decay.CHUNK_DECAY_RATE),
                  USE_CAP)
        sigma = _sigma_affinity(sigma_per.get(sid), sigma_now)
        features.append({"trust": round(trust, 3), "evidence": evidence,
                         "outcome": round(outcome, 3), "use": round(use, 3),
                         "sigma": None if sigma is None else round(sigma, 3)})
        ranked.append((score * trust * (1.0 + W_EVIDENCE * evidence)
                       * (1.0 + W_OUTCOME * outcome) * (1.0 + W_USE * use)
                       + (W_SIGMA * sigma if sigma is not None else 0.0),
                       (score, content, cid)))
    ranked.sort(key=lambda x: x[0], reverse=True)

    # HIDDEN FAILURES: a feature with zero variance says nothing (every row the
    # same zone, no outcomes anywhere). Counted, never silent.
    for key in ("trust", "evidence", "outcome", "use"):
        vals = {f[key] for f in features}
        if len(vals) <= 1 and len(features) > 1:
            COUNTERS["zero_variance"] += 1
            break

    return [row for _s, row in ranked], features


def ensure_schema(conn) -> None:
    """The shadow decision table. Idempotent, never raises."""
    try:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {SHADOW_TABLE} ("
            "ts REAL NOT NULL, session TEXT, query TEXT, same INTEGER, "
            "live_topk TEXT, shadow_topk TEXT, features TEXT)")
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[memory_rank] schema skipped: %r", exc)


def shadow(conn, scored: List[Tuple], info: Dict[str, Dict], limit: int, *,
           session_id: Optional[str] = None, query: str = "") -> None:
    """Record the memory-native ranking BESIDE the live one (AC2). Never raises,
    never changes what recall returns while ``LIVE`` is False."""
    if len(scored) <= 1:
        return
    try:
        COUNTERS["queries"] += 1
        ranked, features = rank_rows(conn, scored, info)
        live_topk = [r[2] for r in scored[:limit]]
        shadow_topk = [r[2] for r in ranked[:limit]]
        same = live_topk == shadow_topk
        COUNTERS["same" if same else "reordered"] += 1
        if LIVE:
            return   # the caller ranks live; the shadow table is the evidence either way
        ensure_schema(conn)
        from backend.memory.db import app_flush

        app_write(
            conn,
            f"INSERT INTO {SHADOW_TABLE} (ts, session, query, same, live_topk, shadow_topk, features) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (time.time(), session_id, query[:200], 1 if same else 0,
             json.dumps(live_topk), json.dumps(shadow_topk),
             json.dumps(features[:limit])),
        )
        COUNTERS["rows_recorded"] += 1
        if COUNTERS["rows_recorded"] % 50 == 0:
            app_write(conn, f"DELETE FROM {SHADOW_TABLE} WHERE ts NOT IN "
                            f"(SELECT ts FROM {SHADOW_TABLE} ORDER BY ts DESC LIMIT {SHADOW_MAX_ROWS})")
            app_flush(10.0)
    except Exception as exc:  # noqa: BLE001 - a shadow never blocks retrieval
        logger.debug("[memory_rank] shadow skipped: %r", exc)


def status() -> Dict[str, object]:
    """Shadow state for the Memory surface (REQ-8). Never raises."""
    return {"live": LIVE, "queries": COUNTERS["queries"],
            "same": COUNTERS["same"], "reordered": COUNTERS["reordered"],
            "zero_variance": COUNTERS["zero_variance"],
            "rows_recorded": COUNTERS["rows_recorded"]}

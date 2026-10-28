"""Chunk decay: the ONE Kyudo law for context_chunks (REQ-5, T18-T20).

``EpisodicStore.cleanup_stale_chunks`` existed with no production caller and a
fixed 72-hour age rule - decay by calendar, not by law. This module is the same
law ``mycelium/decay.py`` states for edges and nodes, applied to chunks:

    strength = 1.0 - rate * m_zone * m_outcome * active_days * a(retrieval_count)
    a(n)     = 1 / (1 + n)          n = retrieval_count (use is the evidence)
    m_zone   = the channel the chunk's Kyudo zone maps to (trusted = USER 1.0,
               tool = VERIFIED 1.5, reference = EXTERNAL 3.0)
    m_outcome= 0.5 when the chunk's strand's recalls HELPED (the law's expand
               multiplier), 1.8 when they MISLED (its compress multiplier) -
               the same constants the quorum reorganization uses, because a
               recall that helped is reinforcement and one that misled is a
               suspect window.

A chunk is pruned when its strength reaches 0. Use slows the fade (a(n) with
more retrievals), never stops it - "a chunk recalled once long ago" decays at
half speed, it is not immortal. Crystallization candidates
(retrieval_count >= CRYSTALLIZE_THRESHOLD), pinned chunks and chunks that back a
LIVE claim (the distilled chain references, T16) are never pruned (AC3).

Growth and decay in one law (owner rule, MEMORY-INTERFACE Part II §F11): the
same pass enforces the per-zone store budget (AC2) - a burst of ingest cannot
outgrow it because the oldest unused rows go first - and every prune is typed
MEMORY_PRUNED with its reason, which the Memory surface already renders as
ghosts.

Bounded: at most MAX_EVAL oldest rows evaluated and MAX_PRUNE rows deleted per
pass, on the ``memory_integrity`` lane, writes through ``app_write`` only. The
law is stateless (computed from current values), so a pass that repeats changes
nothing except what newly crossed the floor.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Dict, List, Optional, Set

from backend.memory.db import app_flush, app_write
from backend.memory.mycelium import decay as kyudo
from backend.memory.mycelium.landmark import _emit_landmark_event

logger = logging.getLogger(__name__)

DECAY_LANE = "memory_integrity"      # the same integrity lane as the fold
CHUNK_DECAY_RATE = 0.02              # strength per ACTIVE day; a proven claim is 0.005
CRYSTALLIZE_THRESHOLD = 5            # episodic._CRYSTALLIZE_THRESHOLD - never pruned
MAX_EVAL = 20_000                    # oldest rows evaluated per pass
MAX_PRUNE = 5_000                    # rows deleted per pass

# The chunk's Kyudo zone -> the channel that wrote it (decay.CHANNEL_DECAY_MULTIPLIER)
ZONE_CHANNEL = {"trusted": 3, "tool": 2, "reference": 1}   # USER / VERIFIED / EXTERNAL

# REQ-5 AC2: the store budget per zone (rows, vector+text bytes). Measured on
# the live store 2026-10-27 (trusted 104,933 / 219 MB, tool 25,743 / 53 MB,
# reference 16,297 / 35 MB) x ~1.5 headroom for growth. A zone over budget
# prunes oldest-unused-first until it is back within; the bench REGRESSIONS on
# the same numbers (evals/memory_bench.py reads them from here).
ZONE_BUDGET = {
    "trusted":   (160_000, 320_000_000),
    "tool":      (40_000,  80_000_000),
    "reference": (25_000,  55_000_000),
}

_PIN_TARGETS = ("chunk", "context_chunk")


def _protected_ids(conn) -> Set[str]:
    """AC3: pinned chunks and chunks that back a LIVE claim are never pruned."""
    protected: Set[str] = set()
    try:
        protected |= {
            str(r[0]) for r in conn.execute(
                "SELECT target_id FROM mycelium_pin_links WHERE target_type IN (?, ?)",
                _PIN_TARGETS).fetchall()
        }
    except Exception:
        pass
    try:
        # T16: a distilled chain row references the chunks that back its claim;
        # the claim must be live (not absorbed) for the protection to hold
        for meta, in conn.execute(
                "SELECT mc.metadata FROM memory_chain mc "
                "JOIN mycelium_landmarks lm ON lm.landmark_id = mc.landmark_id "
                "WHERE mc.distilled = 1 AND (lm.absorbed IS NULL OR lm.absorbed = 0)"
        ).fetchall():
            try:
                protected |= {str(c) for c in json.loads(meta or "{}").get("chunk_refs", [])}
            except Exception:
                continue
    except Exception:
        pass
    return protected


def _outcome_multipliers(conn) -> Dict[str, float]:
    """m_outcome per session: HELPED slows the fade, MISLED speeds it (AC1)."""
    out: Dict[str, float] = {}
    try:
        for sid, label, n in conn.execute(
                "SELECT thread_id, label, count(*) FROM memory_events "
                "WHERE label IN ('RECALL_HELPED', 'RECALL_MISLED') "
                "GROUP BY thread_id, label").fetchall():
            if not sid:
                continue
            m = out.setdefault(sid or "", 1.0)
            factor = kyudo.PHASE_EXPAND_MULTIPLIER if label == "RECALL_HELPED" \
                else kyudo.PHASE_COMPRESS_MULTIPLIER
            out[sid or ""] = m * (factor ** min(int(n or 1), 4))
    except Exception as exc:  # noqa: BLE001 - outcome history is a modifier, not a gate
        logger.debug("[chunk_decay] outcome history unavailable: %s", exc)
    return out


def zone_usage(conn) -> Dict[str, Dict[str, int]]:
    """Rows and vector+text bytes per zone (the budget measure)."""
    usage: Dict[str, Dict[str, int]] = {}
    try:
        for zone, rows, nbytes in conn.execute(
                "SELECT zone, count(*), COALESCE(SUM("
                " COALESCE(length(content), 0) + COALESCE(length(vec_i8), 0) "
                " + COALESCE(length(vec_fp), 0) + COALESCE(length(embedding), 0)), 0) "
                "FROM context_chunks GROUP BY zone"):
            usage[zone or ""] = {"rows": int(rows), "bytes": int(nbytes)}
    except Exception:
        pass
    return usage


def _ts_epoch(ts) -> float:
    """A chunk timestamp (TEXT 'YYYY-MM-DD HH:MM:SS') as epoch seconds."""
    try:
        import datetime as _dt

        return _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _prune(conn, rowids: List[int], *, zone: str, reason: str, dry_run: bool) -> int:
    if not rowids:
        return 0
    if dry_run:
        return len(rowids)
    n = 0
    for start in range(0, len(rowids), 500):
        part = rowids[start:start + 500]
        app_write(
            conn,
            f"DELETE FROM context_chunks WHERE rowid IN ({','.join('?' * len(part))})",
            part,
        )
        n += len(part)
    app_flush(60.0)
    if n:
        try:
            _emit_landmark_event(
                conn, "MEMORY_PRUNED", ["context_chunks"], id_key="table",
                payload={"action": "decay", "reason": reason, "zone": zone, "n": n},
            )
        except Exception as exc:  # noqa: BLE001 - the prune stands; the ghost is best-effort
            logger.warning("[chunk_decay] MEMORY_PRUNED event failed: %r", exc)
        logger.info("[chunk_decay] pruned %d chunks zone=%s reason=%s", n, zone, reason)
    return n


def decay_pass(box: dict, conn, *, now: Optional[float] = None,
               dry_run: bool = False) -> None:
    """One bounded pass of the law. Result goes into ``box["result"]``; never raises."""
    result: Dict[str, object] = {"evaluated": 0, "pruned": 0, "protected": 0,
                                 "by_zone": {}, "budget": {}, "done": False}
    try:
        t0 = now or time.time()
        protected = _protected_ids(conn)
        outcomes = _outcome_multipliers(conn)
        clock = kyudo.ActivityClock(conn, since=0, now=t0)
        result["protected"] = len(protected)

        # ── the law: strength <= 0 prunes (AC1) ────────────────────────────
        rows = conn.execute(
            "SELECT rowid, id, session_id, zone, retrieval_count, timestamp "
            "FROM context_chunks ORDER BY timestamp ASC LIMIT ?",
            (MAX_EVAL,),
        ).fetchall()
        result["evaluated"] = len(rows)
        stale: Dict[str, List[int]] = {}
        for rid, cid, sid, zone, rc, ts in rows:
            if cid in protected or int(rc or 0) >= CRYSTALLIZE_THRESHOLD:
                continue
            zone = zone or "trusted"
            m = kyudo.channel_multiplier(ZONE_CHANNEL.get(zone, 0)) \
                * outcomes.get(sid or "", 1.0)
            days = clock.days_since(_ts_epoch(ts) or t0)
            strength = 1.0 - CHUNK_DECAY_RATE * m * days * kyudo.evidence_weight(rc)
            if strength <= 0.0:
                stale.setdefault(zone, []).append(int(rid))
        pruned = 0
        for zone, ids in stale.items():
            if pruned >= MAX_PRUNE:
                break
            take = ids[: MAX_PRUNE - pruned]
            got = _prune(conn, take, zone=zone, reason="kyudo_decay", dry_run=dry_run)
            pruned += got
            result["by_zone"][zone] = result["by_zone"].get(zone, 0) + got

        # ── the budget: oldest unused first until the zone is within (AC2) ──
        for zone, usage in zone_usage(conn).items():
            budget = ZONE_BUDGET.get(zone)
            over_rows = budget and usage["rows"] > budget[0]
            over_bytes = budget and usage["bytes"] > budget[1]
            result["budget"][zone] = {
                "rows": usage["rows"], "bytes": usage["bytes"],
                "budget_rows": budget[0] if budget else None,
                "budget_bytes": budget[1] if budget else None,
                "over": bool(over_rows or over_bytes),
            }
            if not budget or not (over_rows or over_bytes) or pruned >= MAX_PRUNE:
                continue
            need = (usage["rows"] - budget[0]) if over_rows else 0
            need = max(need, (usage["bytes"] - budget[1]) // 6_500 if over_bytes else 0)
            need = min(need, MAX_PRUNE - pruned)
            if need <= 0:
                continue
            picked: List[int] = []
            for rid, cid in conn.execute(
                "SELECT rowid, id FROM context_chunks WHERE zone = ? AND retrieval_count < ? "
                "ORDER BY retrieval_count ASC, timestamp ASC LIMIT ?",
                (zone, CRYSTALLIZE_THRESHOLD, need * 2)).fetchall():
                if cid in protected:
                    continue
                picked.append(int(rid))
                if len(picked) >= need:
                    break
            got = _prune(conn, picked, zone=zone, reason="zone_budget", dry_run=dry_run)
            pruned += got
            result["by_zone"][zone] = result["by_zone"].get(zone, 0) + got

        result["pruned"] = pruned
        result["done"] = True
    except Exception as exc:  # noqa: BLE001 - the CLI/caller reports it
        logger.warning("[chunk_decay] pass failed: %r", exc)
        result["error"] = repr(exc)
    box["result"] = result

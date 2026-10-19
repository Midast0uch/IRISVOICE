"""
Growth and decay as ONE law — the Kyudo self-cleaning of the coordinate graph.

docs/Design/Memory-Cortex/MEMORY-FOUNDATION-ANALYSIS.md §11. Every learned
strength (edge score, landmark-edge score, node confidence above its floor)
moves by the same law in both directions:

  growth (an observation):   s += delta * a(n)                  (REQ-26, scorer)
  decay  (an idle span):     s -= rate * m * days * a(n)
  a(n) = 1 / (1 + n)         n = the evidence behind s (observation count)
  m    = m_channel * m_phase * m_quorum

Net drift per day = a(n) * (delta * f - rate * m), f = reinforcements per day.
The SIGN depends only on f against f* = rate * m / delta, never on the age of
the belief: a young and an old belief cross at the same use frequency, and a
belief with more evidence moves more slowly in BOTH directions. Growth and decay
run at one speed.

Node confidence is the same pair in multiplicative form (a node has no count):
growth shrinks doubt, c -> 1 - (1 - c)(1 - r*w)  (store._accumulate_confidence);
decay shrinks the EARNED belief above the stated floor,
c -> floor + (c - floor) * exp(-rate * m * days). Each is proportional to its
distance from its bound, so the two meet at an equilibrium set by f.

Decay is incremental: a span is counted once, from max(last touch,
last_decayed_at). The quorum reorganization is this law with m_quorum, applied to
what the suspect window touched (kyudo.QuorumReorganization) — "the same way it
always does, just faster" (Kyudo Layer Guide, Part 4).
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Kyudo Layer Guide, Part 3 — decay multiplier by the channel that wrote the
# memory (keys are HyphaChannel values; SYSTEM = IRIS's own observation).
CHANNEL_DECAY_MULTIPLIER: Dict[int, float] = {
    4: 1.0,   # SYSTEM
    3: 1.0,   # USER
    2: 1.5,   # VERIFIED
    1: 3.0,   # EXTERNAL
    0: 5.0,   # UNTRUSTED
}

# Kyudo Layer Guide, Part 3 — the most confidence one observation from a
# lower-trust channel may carry. USER/SYSTEM are not capped here (their values
# are set by the extractors, e.g. stated = 0.4, Req 4.4).
CHANNEL_CONFIDENCE_CAP: Dict[int, float] = {
    2: 0.40,  # VERIFIED
    1: 0.30,  # EXTERNAL
    0: 0.15,  # UNTRUSTED
}

# Rows written before nodes carried a channel (2026-10-19). Measured on the live
# store: every such node came from an internal path (statements, tool calls,
# hardware, sessions) — none from the RAG/document bridges — so it decays at the
# SYSTEM/USER rate.
LEGACY_CHANNEL = 4

# Caducean phase over the decayed span (was a per-session latest-u read that
# never ran: the scorer asked the STORE for get_latest_u, which only the
# interface has). Expanding (u > 0) preserves; compressing (u < 0) prunes.
PHASE_EXPAND_MULTIPLIER = 0.5
PHASE_COMPRESS_MULTIPLIER = 1.8

# Node confidence never decays below the stated value (Req 4.4): decay removes
# what repetition EARNED, never the observation itself.
NODE_CONFIDENCE_FLOOR = 0.4
# Spaces without their own rate decay at the edge-table default (db.py).
NODE_DECAY_RATE_DEFAULT = 0.005

# The reorganization strips one day of growth at m_quorum from what the
# current and previous day touched.
QUORUM_SPAN_DAYS = 1.0

_COLUMNS = (
    ("mycelium_edges", "last_decayed_at", "REAL"),
    ("mycelium_landmark_edges", "last_decayed_at", "REAL"),
    ("mycelium_nodes", "last_decayed_at", "REAL"),
    ("mycelium_nodes", "source_channel", "INTEGER"),
)
def ensure_decay_columns(conn: Any) -> None:
    """Idempotent ALTERs for the decay bookkeeping. Run by db.py Block 5 on
    the application store only."""
    for table, column, sql_type in _COLUMNS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
            logger.info("[decay] %s ALTER added column %s", table, column)


def has_decay_columns(conn: Any, table: Optional[str] = None) -> bool:
    """True when the store carries the bookkeeping columns (of ``table``, or
    all). The application store always does (db.py); a store that predates
    them (or a test fixture built from an older schema copy) decays the old
    way - no channel, the idle span from last_traversed - the same
    absent-column tolerance as observation_count (store._row_to_edge).
    A few PRAGMAs: callers probe once per pass, or once per store."""
    try:
        for t, column, _ in _COLUMNS:
            if table is not None and t != table:
                continue
            if column not in {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}:
                return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[decay] column probe failed: %s", exc)
        return False


def evidence_weight(n: Optional[int]) -> float:
    """a(n): the same weight scorer.record_outcome gives an observation."""
    return 1.0 / (1.0 + max(0, int(n or 0)))


def channel_multiplier(channel: Optional[int]) -> float:
    ch = LEGACY_CHANNEL if channel is None else int(channel)
    return CHANNEL_DECAY_MULTIPLIER.get(ch, CHANNEL_DECAY_MULTIPLIER[0])


def cap_for_channel(confidence: float, channel: Optional[int]) -> float:
    cap = CHANNEL_CONFIDENCE_CAP.get(LEGACY_CHANNEL if channel is None else int(channel))
    return confidence if cap is None else min(confidence, cap)


def phase_multiplier(conn: Any, since: float, session_id: Optional[str] = None) -> float:
    """m_phase over the span being decayed: the MEAN of the per-step
    multipliers (expanding 0.5, compressing 1.8, u = 0 neutral). Decay adds up
    over the span, so the span's factor is the time-mean of its steps'.

    Not the multiplier of the mean u: the mean u is positive over every span
    of the live store (72% of steps expand), so that form was 0.5 always - a
    constant. The step mean varies with the work (0.68-1.37 per day,
    measured 2026-10-19). One indexed query (idx_ct_ts)."""
    try:
        sql = (
            "SELECT AVG(CASE WHEN u > 0 THEN ? WHEN u < 0 THEN ? ELSE 1.0 END) "
            "FROM caducean_trajectories WHERE ts > ?"
        )
        params: tuple = (PHASE_EXPAND_MULTIPLIER, PHASE_COMPRESS_MULTIPLIER, since)
        if session_id is not None:
            sql += " AND session_id = ?"
            params = params + (session_id,)
        row = conn.execute(sql, params).fetchone()
    except Exception as exc:  # noqa: BLE001 - a store without trajectories
        logger.debug("[decay] phase unavailable: %s", exc)
        return 1.0
    m = row[0] if row else None
    if m is None or not math.isfinite(m):
        return 1.0
    return float(m)


def edge_decay_amount(rate: float, multiplier: float, days: float, n: Optional[int]) -> float:
    """How much score one idle span removes from an edge."""
    return rate * multiplier * days * evidence_weight(n)


def node_confidence_after(confidence: float, rate: float, multiplier: float, days: float) -> float:
    """Node confidence after an idle span (only the earned part above the floor)."""
    if confidence <= NODE_CONFIDENCE_FLOOR:
        return confidence
    earned = confidence - NODE_CONFIDENCE_FLOOR
    return NODE_CONFIDENCE_FLOOR + earned * math.exp(-rate * multiplier * days)


def quorum_window_start(now: Optional[float] = None) -> float:
    """Start (UTC midnight) of the previous day: the 'current + previous
    session' window the reorganization treats as suspect."""
    now = time.time() if now is None else now
    return (math.floor(now / 86400.0) - 1) * 86400.0

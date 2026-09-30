"""ontology_recall.py — REQ-20 (T21): ontology-aware, filterable DER recall.

DER recall becomes filterable by node type, both domain axes, and
relationship (link-store predicate) — the relevant neighborhood instead of
the whole graph. Zero-hit queries WIDEN one level at a time and log the
winning scope (REQ-20 AC2), never silently return zero.

Semantics pinned by the ontology doc (specs/der-dag-inversion/ontology.md):

  - Filters are AND-ed at each level: relationship AND node_type AND
    topic_domain AND execution_domain.
  - Widen order (AC2): drop relationship -> drop node_type -> drop domain.
    The winning scope is logged at INFO so "which scope answered" is
    answerable from data.
  - Cross-conversation by default (AC1b, resolves OQ-2): ``thread_id`` is a
    RANKING input (recency), never a hard WHERE filter. A node written in
    another session is a legitimate candidate if it survives Kyudo decay.
  - Age is a ranking input, not a cutoff (AC2b): rows are ordered by
    created_at (recency) plus any decay/score standing, then similarity.
    An old node that survived decay is reachable; recency never hides it.
  - Unknown relationship value (not in LINK_VOCABULARY) is treated as NO
    relationship (widen to the type+domain scope) — the REQ-20 edge case.
  - The failed_like relationship turns AVOID recall into a graph walk
    (REQ-19 AC3): a node ``failed_like`` prior same-class failures in the
    shared link store.

The module is deliberately connection-based (no global state): every
function takes a SQLite connection, so the contract test drives the REAL
code against an in-memory store. All functions are read-only and never
raise — a recall failure returns the widened/empty scope, never an error.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

logger = logging.getLogger(__name__)

# Widen-order labels, in the order applied (AC2).
SCOPE_ALL_FILTERS = "relationship+type+domains"
SCOPE_NO_RELATIONSHIP = "type+domains"
SCOPE_NO_TYPE = "domains"
SCOPE_ALL = "unfiltered-all"

# mycelium_pin_links predicate -> SQL fragment for the link-store join.
# Only DER-relevant predicates are resolved here; unknown values widen.
_DER_PREDICATES = {
    "part_of",
    "depends_on",
    "derives_from",
    "relevant_to",
    "failed_like",
    "contains",
    "related_to",
}


@dataclass
class RecallFilters:
    """Filter set for a filtered chain recall.

    All fields optional; None = no filter on that axis (wider scope).
    """

    node_type: Optional[str] = None            # task | step | sub_loop
    topic_domain: Optional[str] = None         # registry value (DOMAIN_IDS)
    execution_domain: Optional[str] = None     # voice | der | research
    relationship: Optional[str] = None         # link-store predicate
    thread_id: Optional[str] = None            # RANKING input only (AC1b)
    limit: int = 5
    # True: an unknown/out-of-vocabulary relationship widens silently to the
    # type+domain scope (REQ-20 edge case). False: it drops the relationship
    # the same way — both widen; the flag only controls the log wording.
    unknown_relationship_widens: bool = True
    _active_filters: List[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._active_filters = []
        if self.relationship is not None:
            self._active_filters.append("relationship")
        if self.node_type is not None:
            self._active_filters.append("node_type")
        if self.topic_domain is not None or self.execution_domain is not None:
            self._active_filters.append("domain")

    @property
    def has_any(self) -> bool:
        return bool(self._active_filters)


def _chain_columns(conn) -> set:
    """Column names of memory_chain, for shape-agnostic queries."""
    try:
        rows = conn.execute("PRAGMA table_info(memory_chain)").fetchall()
        return {r[1] for r in rows}
    except Exception:
        return set()


def _resolve_relationship_ids(
    conn, relationship: str, limit: int
) -> List[str]:
    """Node ids in the link store linked by ``relationship`` (source OR target).

    Returns a bounded list so a pathological store cannot blow the query.
    Empty when the predicate is unknown or no links exist — the caller widens.
    """
    try:
        rows = conn.execute(
            "SELECT DISTINCT source_id, target_id FROM mycelium_pin_links "
            "WHERE relationship = ? ORDER BY created_at DESC LIMIT ?",
            (relationship, max(limit * 4, 64)),
        ).fetchall()
        ids: List[str] = []
        for src, tgt in rows:
            if src:
                ids.append(src)
            if tgt:
                ids.append(tgt)
        return ids[: limit * 2]
    except Exception:
        return []


def filtered_chain_recall(
    conn, filters: RecallFilters
) -> tuple[List[dict], str]:
    """Filtered recall over memory_chain with REQ-20 widen-order.

    Returns ``(rows, winning_scope)`` where ``rows`` are chain-row dicts
    (chain_id, result, node_type, topic_domain, execution_domain, insight,
    created_at when present) and ``winning_scope`` is the scope label that
    answered (SCOPE_* constants). Cross-conversation: thread_id ranks rows
    but never filters them (AC1b). Never raises.
    """
    try:
        cols = _chain_columns(conn)
        select_cols = [
            c
            for c in (
                "chain_id", "result", "node_type", "topic_domain",
                "execution_domain", "insight", "created_at", "coords_from",
            )
            if c in cols
        ]
        base = "SELECT {} FROM memory_chain".format(", ".join(select_cols) or "*")

        def _run(
            rel: Optional[str],
            ntype: Optional[str],
            tdom: Optional[str],
            edom: Optional[str],
        ) -> List[dict]:
            where: List[str] = []
            params: List[Any] = []
            # Relationship resolves through the link store (AVOID walk for
            # failed_like; neighborhood for part_of/depends_on/relevant_to).
            rel_ids: List[str] = []
            if rel is not None and rel in _DER_PREDICATES:
                rel_ids = _resolve_relationship_ids(conn, rel, filters.limit)
                if rel_ids:
                    # The link store keys nodes as ``node:<step_id>`` while
                    # memory_chain.chain_id holds the bare step id — match
                    # BOTH forms so a walk never misses its targets.
                    _norm = []
                    for _rid in rel_ids:
                        _norm.append(_rid)
                        if str(_rid).startswith("node:"):
                            _norm.append(str(_rid)[5:])
                    where.append("chain_id IN ({})".format(
                        ",".join("?" * len(_norm))
                    ))
                    params.extend(_norm)
            if ntype is not None:
                where.append("node_type = ?")
                params.append(ntype)
            if tdom is not None:
                where.append("topic_domain = ?")
                params.append(tdom)
            if edom is not None:
                where.append("execution_domain = ?")
                params.append(edom)
            sql = base
            if where:
                sql += " WHERE " + " AND ".join(where)
            # AC2b: age is a RANKING input, never a cutoff — recency first,
            # then rowid (insertion order) as a stable tiebreak.
            sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
            params.append(filters.limit)
            rows = conn.execute(sql, params).fetchall()
            out = []
            for r in rows:
                d = dict(zip(select_cols, r))
                d["distance"] = 0.0  # not a coordinate query
                out.append(d)
            return out

        # ── AC2 widen-order: relationship -> node_type -> domain ─────────
        rel = filters.relationship
        ntype = filters.node_type
        tdom = filters.topic_domain
        edom = filters.execution_domain
        rel_dropped_upfront = False

        # Unknown relationship -> treat as NO relationship (widen immediately).
        if rel is not None and rel not in _DER_PREDICATES:
            logger.info(
                "[ontology_recall] unknown relationship %r treated as no "
                "relationship — widening to type+domains scope (REQ-20 edge)",
                rel,
            )
            rel = None
            rel_dropped_upfront = True
        elif rel is not None:
            # A relationship with NO matching links in the store is a
            # zero-hit filter: it cannot match anything, so it widens to the
            # type+domains scope (AC2), logged — never silently no-ops.
            if not _resolve_relationship_ids(conn, rel, filters.limit):
                logger.info(
                    "[ontology_recall] relationship=%r has no links in the "
                    "store — zero-hit, widening to type+domains scope (AC2)",
                    rel,
                )
                rel = None
                rel_dropped_upfront = True

        if rel is not None or ntype is not None or tdom is not None or edom is not None:
            rows = _run(rel, ntype, tdom, edom)
            if rows:
                # If the relationship was dropped up-front (unknown or
                # no-links), the winning scope is the type+domains one, not
                # the full-filter label.
                return rows, (
                    SCOPE_NO_RELATIONSHIP if rel_dropped_upfront else SCOPE_ALL_FILTERS
                )

        if rel is not None:
            # relationship existed but zero-hit (or no links) -> drop it.
            logger.info(
                "[ontology_recall] scope widened: dropped relationship=%r "
                "(zero hits) — winning scope will be type+domains or wider",
                rel,
            )
            rel = None
            rows = _run(rel, ntype, tdom, edom)
            if rows:
                return rows, SCOPE_NO_RELATIONSHIP

        if ntype is not None:
            logger.info(
                "[ontology_recall] scope widened: dropped node_type=%r "
                "(zero hits) — winning scope: domains",
                ntype,
            )
            ntype = None
            rows = _run(rel, ntype, tdom, edom)
            if rows:
                return rows, SCOPE_NO_TYPE

        if tdom is not None or edom is not None:
            logger.info(
                "[ontology_recall] scope widened: dropped domain filters "
                "(zero hits) — winning scope: unfiltered-all",
            )
            tdom = edom = None
            rows = _run(rel, ntype, tdom, edom)
            if rows:
                return rows, SCOPE_ALL

        # Fully unfiltered query — today's behavior preserved.
        return _run(None, None, None, None), SCOPE_ALL
    except Exception as exc:
        logger.debug("[ontology_recall] filtered recall failed: %s", exc)
        return [], SCOPE_ALL


def recall_failed_like(
    conn, step_id: str, limit: int = 5
) -> List[dict]:
    """REQ-19 AC3 / REQ-20: AVOID recall as a graph walk.

    Returns prior failed nodes linked ``failed_like`` to ``step_id``
    (source=this node, target=prior same-class failure), newest first.
    This is the AVOID path: "what failed like this before?" is a walk over
    the shared link store, not a free-text scan. Never raises.
    """
    try:
        node_id = f"node:{step_id}" if not str(step_id).startswith("node:") else step_id
        rows = conn.execute(
            "SELECT target_id FROM mycelium_pin_links "
            "WHERE source_id = ? AND relationship = 'failed_like' "
            "ORDER BY created_at DESC LIMIT ?",
            (node_id, limit),
        ).fetchall()
        return [{"node_id": r[0]} for r in rows if r[0]]
    except Exception as exc:
        logger.debug("[ontology_recall] failed_like walk failed: %s", exc)
        return []


def record_widening_telemetry(winning_scope: str, filters: RecallFilters) -> None:
    """REQ-17-style telemetry for the recall filter path (off hot path).

    Logs one line naming the filters requested and the scope that answered,
    so "which scope answered" is answerable from data (AC2). Structured:
    a stable key prefix lets the log line be grepped across sessions.
    """
    requested = "+".join(filters._active_filters) or "none"
    logger.info(
        "[ontology_recall] scope=%s requested=%s ts=%.3f",
        winning_scope, requested, time.time(),
    )


def resolve_mycelium_conn(memory_interface):
    """Shared mycelium connection resolution (kernel + gate, REQ-6 AC3).

    The kernel's ``_der_recall_neighborhood`` and the semantic gate's Tier 2
    both need the live mycelium connection. mycelium exposes it as ``_conn``;
    some call sites alias it ``.conn`` — accept either. Returns None when the
    interface or store is unavailable (caller falls back to live state).
    """
    if memory_interface is None:
        return None
    _myc = getattr(memory_interface, "_mycelium", None)
    if _myc is None:
        return None
    return getattr(_myc, "conn", None) or getattr(_myc, "_conn", None)


def run_filtered_recall(conn, filters: RecallFilters, scope_out=None) -> list:
    """filtered_chain_recall + widen telemetry + error-swallow (REQ-6 AC3).

    The ONE code path for ontology chain recall — shared by the kernel's
    ``_der_recall_neighborhood`` and the semantic gate's Tier 2, so the
    widen-order and telemetry cannot drift between callers. Returns chain-row
    dicts, or [] on any failure — callers proceed on live state, never an
    error. ``scope_out`` (optional list) receives the winning widen scope so
    the gate can surface it on the [LAYERS] line (REQ-5 AC1, T8); the kernel
    caller passes nothing and is unaffected.
    """
    try:
        rows, scope = filtered_chain_recall(conn, filters)
        record_widening_telemetry(scope, filters)
        if scope_out is not None:
            scope_out.append(scope)
        return rows or []
    except Exception as exc:
        logger.debug("[ontology_recall] filtered chain recall failed: %s", exc)
        return []


# ── REQ-4 AC4.2 (K2): the relevance gate on the per-step neighbors ───────────
#
# The topic filter above only says a row is about the same area. A step must
# not carry a row just because it is recent and same-topic: chain rows enter
# the context only when they are relevant to THIS step's goal (owner rule
# 2026-09-30, context debt). Relevance = token overlap between the step goal
# and the row's insight/result head. No embedding on the step path (the CPU
# embedder costs ~5 s/KB). State proximity and recency only RANK rows that
# already passed. Nothing passes -> nothing is injected.

# Candidate pool read from the chain per step. The gate may keep at most
# ``keep`` of them (3, as before): a larger pool only widens what the gate can
# find, it never widens what the step carries.
CANDIDATE_POOL = 24
_MIN_SHARED_TOKENS = 2      # a row must share this many goal tokens (or all, if fewer)
_MIN_GOAL_COVERAGE = 0.4    # ... and cover this fraction of the goal's tokens
_ROW_TEXT_HEAD = 240        # chars of ``result`` read for the match

# Own tokenizer: importing crawler.rerank/_tok would load the whole crawler
# package (crawl4ai) onto the DER step path.
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "the and for with from into this that these those then than not are was "
    "were been being its can will use using".split()
)


def _tokens(text: Any) -> set:
    return {
        t for t in _TOKEN.findall(str(text or "").lower())
        if len(t) > 2 and t not in _STOP
    }


def _state_distance(state: Optional[Sequence[float]], coords_from: Any) -> float:
    """Euclidean distance between the current state and a row's coordinate;
    +inf when either is unknown, so such rows rank after rows with a position."""
    try:
        row = [float(p) for p in str(coords_from).split(",")]
        if state is None or len(row) != 4:
            return float("inf")
        return round(sum((a - b) ** 2 for a, b in zip(state, row)) ** 0.5, 2)
    except Exception:
        return float("inf")


def relevance_gate(
    rows: List[dict],
    goal: str,
    topic_domain: Optional[str] = None,
    state_fn=None,
    keep: int = 3,
) -> List[dict]:
    """Keep only the rows relevant to ``goal``: same topic AND token overlap.

    ``rows`` arrive newest-first (recall order). Survivors are ranked by state
    proximity (``state_fn`` -> "x,y,xi,u" text or None; called only when more
    than one row survived) then recency (the stable sort keeps recall order on
    ties), and cut to ``keep``. Empty goal or no survivor -> []. Never raises.
    """
    try:
        goal_tokens = _tokens(goal)
        if not goal_tokens:
            return []
        need = min(_MIN_SHARED_TOKENS, len(goal_tokens))
        kept: List[dict] = []
        for r in rows:
            if topic_domain and r.get("topic_domain") != topic_domain:
                continue
            text = "{} {}".format(
                r.get("insight") or "", str(r.get("result") or "")[:_ROW_TEXT_HEAD]
            )
            shared = len(goal_tokens & _tokens(text))
            if shared >= need and shared / len(goal_tokens) >= _MIN_GOAL_COVERAGE:
                kept.append(r)
        if len(kept) > 1 and state_fn is not None:
            state = None
            try:
                raw = state_fn()
                state = [float(p) for p in raw.split(",")] if raw else None
            except Exception:
                state = None
            if state is not None:
                kept.sort(key=lambda r: _state_distance(state, r.get("coords_from")))
        return kept[:keep]
    except Exception as exc:
        logger.debug("[ontology_recall] relevance gate failed: %s", exc)
        return []


def gated_neighborhood(
    conn,
    filters: RecallFilters,
    goal: str,
    state_fn=None,
    keep: int = 3,
) -> List[dict]:
    """The per-step neighbors: topic-filtered recall, then the relevance gate.

    Logs one ``[chain_recall] cand=<n> kept=<k> ms=<t>`` line per call so the
    rows-per-step before/after is answerable from data (AC4.4). Never raises.
    """
    t0 = time.perf_counter()
    candidates = run_filtered_recall(conn, filters)
    kept = relevance_gate(candidates, goal, filters.topic_domain, state_fn, keep)
    logger.info(
        "[chain_recall] cand=%d kept=%d ms=%.1f thread=%s",
        len(candidates), len(kept), (time.perf_counter() - t0) * 1000.0,
        filters.thread_id or "-",
    )
    return kept


# ── REQ-4 AC4.3 (K3): the chain at a DECISION point ──────────────────────────
#
# A replan after a failure is where the chain changes the decision: it tells the
# replanner what THIS task already tried, in order, and which mediators were
# tried near the current state. It is read only there - never per turn or per
# step (owner rule 2026-09-30). Bounded: <= 8 rows + 3 mediators, <= 900 chars.

TIMELINE_ROWS = 8
_TIMELINE_SQL = (
    "SELECT chain_id, result, insight, nbl_outcome, created_at "
    "FROM memory_chain WHERE thread_id = ? "
    "ORDER BY created_at DESC, rowid DESC LIMIT ?"
)
_MEDIATORS_KEPT = 3
_CONTEXT_MAX_CHARS = 900


def chain_timeline(conn, thread_id: str, limit: int = TIMELINE_ROWS) -> List[dict]:
    """The last ``limit`` chain rows of THIS thread, oldest first.

    Read-only and bounded by ``limit``; the query orders by the indexed
    ``created_at`` (S2). Never raises - a failed read returns [].
    """
    try:
        if not thread_id or limit < 1:
            return []
        rows = conn.execute(_TIMELINE_SQL, (thread_id, int(limit))).fetchall()
        keys = ("chain_id", "result", "insight", "nbl_outcome", "created_at")
        return [dict(zip(keys, r)) for r in reversed(rows)]
    except Exception as exc:
        logger.debug("[ontology_recall] chain_timeline failed: %s", exc)
        return []


def replan_chain_context(
    conn, thread_id: str, state: Optional[str] = None
) -> str:
    """K3: the text a replan-after-failure child carries; "" when the chain has
    nothing for this thread. ``state`` is the current "x,y,xi,u" coordinate,
    used only to rank the mediators by proximity. Logs one
    ``[chain_recall] replan ...`` line (rows returned + ms per decision, AC4.4).
    Never raises.
    """
    t0 = time.perf_counter()
    timeline: List[dict] = []
    mediators: List[str] = []
    try:
        timeline = chain_timeline(conn, thread_id)
        from backend.gateway.iris_ffi import ffi_immortus_chain_query_mediators

        vec = None
        if state:
            try:
                vec = [float(p) for p in state.split(",")]
            except Exception:
                vec = None
        tried = [
            m for m in (ffi_immortus_chain_query_mediators(thread_id) or [])
            if m.get("mediator") and m.get("mediator") != "none"
        ]
        # Newest first from the query; the stable sort keeps that on ties.
        tried.sort(key=lambda m: _state_distance(vec, m.get("coords_from")))
        seen: set = set()
        for m in tried:
            name = str(m["mediator"])[:40]
            if name in seen:
                continue
            seen.add(name)
            mediators.append("{}->{}".format(name, str(m.get("result") or "?")[:12]))
            if len(mediators) >= _MEDIATORS_KEPT:
                break
    except Exception as exc:
        logger.debug("[ontology_recall] replan mediators failed: %s", exc)

    parts: List[str] = []
    if timeline:
        steps = []
        for r in timeline:
            outcome = str(r.get("result") or "")
            outcome = outcome if len(outcome) <= 16 else ""  # long = a payload
            steps.append(" ".join(
                x for x in (
                    str(r.get("nbl_outcome") or "step"),
                    outcome,
                    str(r.get("insight") or "")[:70],
                ) if x
            ))
        parts.append("CHAIN TIMELINE (this task, oldest first): " + " > ".join(steps))
    if mediators:
        parts.append("MEDIATORS TRIED NEAR NOW: " + ", ".join(mediators))
    logger.info(
        "[chain_recall] replan rows=%d mediators=%d ms=%.1f thread=%s",
        len(timeline), len(mediators), (time.perf_counter() - t0) * 1000.0,
        thread_id or "-",
    )
    return ". ".join(parts)[:_CONTEXT_MAX_CHARS]

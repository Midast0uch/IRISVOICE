"""
Kyudo integrity pass - the memory cleans itself (owner decision, 2026-10-19:
"Kyudo should NATURALLY clean up old landmarks or anything that would interfere
with the structural integrity and credibility of the memory").

Run by MyceliumInterface.run_maintenance (the slow, normal cleaning; never on the
answer path). The quorum reorganization (kyudo.QuorumReorganization) is the same
cleaning in an emergency: while it holds the graph (crystallisation suspended)
this pass does not run, and it uses the SAME law (decay.py), not a second rule.

A landmark is a claim proven TRUE by outside evidence; its coordinates are the
place the claim was made. Four rules, in this order (every action is counted
(write_counters), logged, typed as a memory event, and goes through app_write):

 1. INTEGRITY. A landmark whose coordinates are not evidence of its claim is
    absorbed (absorbed = 1, row kept, the reason appended to falsify_if):
      a. dangling_cluster - fewer than half of its cluster nodes still exist;
      b. hub_cluster - its cluster is shared (Jaccard >= the merge threshold) by
         landmarks that make HUB_MIN_CLAIMS or more DIFFERENT claims (task_class).
         A place that "supports" three different claims says nothing about any of
         them: this is the old global-top-nodes cluster bug (live 2026-10-19: 83
         landmarks, 41 claims on one 6-node cluster), found by what it IS (many
         claims, one place), not by when it was made. Same claim + same place is a
         plain duplicate: LandmarkMerger.collapse_duplicates merges it (step 6).
    Protected (rules a and b): a permanent landmark, and a PROVEN claim
    (tier 'landmark' with outside evidence other than recurrence - recurrence
    between landmarks that share one hub cluster is circular).
 2. CREDIBILITY (the section 11 law on landmarks). credibility = score - rate *
    active_days_idle * a(n), the edge law with rate 0.005/day (the non-permanent
    landmark rate), n = activations + independent outside evidence, idle since
    the last touch (creation, activation, verification, evidence). Below
    LANDMARK_PRUNE_THRESHOLD the claim is absorbed (no_credibility). A claim with no
    evidence and no activation (a = 1) crosses in (score - 0.08) / 0.005 active days
    (74 days at the 0.45 crystallisation floor); a proven claim (n >= 2, a <= 1/3) in
    three times that. Permanent landmarks are exempt (the permanence rule).
 3. DANGLING REFERENCES. Rows that point at an absorbed or missing landmark:
    landmark edges, episode-index landmark_id, landmark-sector rows - re-pointed to
    the survivor of a merge (the chain of mycelium_landmark_merges), else removed
    (edges, sector rows) or cleared (episode-index landmark_id; the episode row stays).
    mycelium_edges whose endpoint node is gone are removed.
 4. ORPHAN NODES. A node (not a user "stated_*" node) with no edge, in no live landmark
    cluster, never accessed, at its space's confidence floor (earned part <= ORPHAN_NODE_EARNED_MAX: the
    node law already took back everything repetition gave), idle for
    ORPHAN_NODE_IDLE_ACTIVE_DAYS active days, is removed. Nodes are derived and
    re-created by the next observation; landmark ROWS are never deleted.
 5. (then) LandmarkMerger.collapse_duplicates: the live landmarks that still overlap
    (Jaccard >= the merge threshold) become one - the crystallisation merge rule applied
    to the backlog. Hubs are gone by now, so it only meets real duplicates.

Bounds per pass: MAX_LANDMARKS_PER_PASS dissolved, MAX_REFERENCE_LANDMARKS_PER_PASS
dead landmark ids swept, MAX_NODES_PER_PASS nodes and MAX_NODE_EDGES_PER_PASS
edges removed, collapse within one task's group of at most COLLAPSE_MAX_GROUP landmarks.
Idempotent: a second pass over the same store acts on nothing.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from backend.memory.db import app_flush, app_write

from .decay import ActivityClock, landmark_credibility
from .landmark import (
    _DECAY_NON_PERMANENT,
    OUTSIDE_EVIDENCE,
    _emit_landmark_event,
    _independent,
    _jaccard,
    ensure_landmark_policy_columns,
)
from .spaces import LANDMARK_PRUNE_THRESHOLD, MERGE_OVERLAP_THRESHOLD

logger = logging.getLogger(__name__)

# -- rule thresholds (start values; each was read against the live store, see
#    MEMORY-INTERFACE Part II section 16) ----------------------------------------------
HUB_MIN_CLAIMS = 3                  # different claims on one place -> the place proves none
MIN_LIVE_CLUSTER_FRACTION = 0.5     # the same bar as "the same landmark" (merge overlap)
CREDIBILITY_RATE = _DECAY_NON_PERMANENT   # per active day, landmark.apply_landmark_decay
ORPHAN_NODE_IDLE_ACTIVE_DAYS = 30   # of the store's 52 active days at the live read
ORPHAN_NODE_EARNED_MAX = 0.05       # node_confidence_after: e^-3 of an earned belief is gone
STATED_NODE_PREFIX = "stated_"      # extractor labels of the user's own statements

# -- bounds per pass ---------------------------------------------------------------------
MAX_LANDMARKS_PER_PASS = 100
MAX_REFERENCE_LANDMARKS_PER_PASS = 500
MAX_NODES_PER_PASS = 100
MAX_NODE_EDGES_PER_PASS = 500
COLLAPSE_MAX_GROUP = 500            # collapse_duplicates compares within one task's group: O(group^2)
_MERGE_CHAIN_MAX = 10
_CHUNK = 400                        # SQLite parameter limit is 999

_REASONS = ("dangling_cluster", "hub_cluster", "no_credibility")


def _chunks(seq: Sequence[Any], size: int = _CHUNK) -> Iterable[Sequence[Any]]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _marks(n: int) -> str:
    return ",".join("?" * n)


def _tables(conn) -> Set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# ---------------------------------------------------------------------------
# Rules 1 and 2 - landmarks
# ---------------------------------------------------------------------------

def _load_live(conn) -> List[dict]:
    """Every live landmark, parsed. ``ids`` is None for a landmark whose cluster is not
    a list of nodes (a bootstrap landmark holds a dict): no coordinates to judge."""
    out: List[dict] = []
    for (lid, task_class, cluster_json, acts, perm, tier, ev_json, created, last_act,
         last_ver, score) in conn.execute(
            "SELECT landmark_id, task_class, coordinate_cluster, activation_count, is_permanent,"
            " tier, evidence, created_at, last_activated, last_verified, cumulative_score"
            " FROM mycelium_landmarks WHERE absorbed IS NULL"):
        try:
            cluster = json.loads(cluster_json or "[]")
        except (json.JSONDecodeError, TypeError):
            cluster = []
        try:
            evidence = [e for e in json.loads(ev_json or "[]") if isinstance(e, dict)]
        except (json.JSONDecodeError, TypeError):
            evidence = []
        ids = None
        if isinstance(cluster, list):
            ids = frozenset(d["node_id"] for d in cluster if isinstance(d, dict) and d.get("node_id"))
        touches = [created or 0.0, last_act or 0.0, last_ver or 0.0] + [e.get("at") or 0.0 for e in evidence]
        out.append({
            "id": lid, "task_class": task_class, "ids": ids or None, "acts": acts or 0,
            "permanent": bool(perm), "created": created or 0.0, "score": score or 0.0,
            "n": (acts or 0) + _independent(evidence), "touch": max(touches),
            "proven": (tier or "candidate") == "landmark" and any(
                e.get("kind") in OUTSIDE_EVIDENCE and e.get("kind") != "recurrence" for e in evidence),
        })
    return out


def _hub_ids(live: List[dict]) -> Set[str]:
    """Landmarks whose cluster is shared with landmarks of >= HUB_MIN_CLAIMS different
    claims (this one counted). Candidates come from an index on node id."""
    by_node: Dict[str, List[dict]] = {}
    for lm in live:
        for nid in lm["ids"] or ():
            by_node.setdefault(nid, []).append(lm)
    hubs: Set[str] = set()
    for lm in live:
        if not lm["ids"]:
            continue
        claims = {lm["task_class"]}
        seen: Set[str] = {lm["id"]}
        for nid in lm["ids"]:
            for other in by_node[nid]:
                if other["id"] in seen:
                    continue
                seen.add(other["id"])
                if _jaccard(set(lm["ids"]), set(other["ids"])) >= MERGE_OVERLAP_THRESHOLD:
                    claims.add(other["task_class"])
        if len(claims) >= HUB_MIN_CLAIMS:
            hubs.add(lm["id"])
    return hubs


def _decide_dissolutions(conn, live: List[dict], now: float) -> Tuple[List[Tuple[str, str]], bool]:
    """([(landmark_id, reason)], truncated): at most MAX_LANDMARKS_PER_PASS, oldest first
    within a reason; ``truncated`` = the cap left more to do. Reads only."""
    node_ids = {r[0] for r in conn.execute("SELECT node_id FROM mycelium_nodes")}
    hubs = _hub_ids(live)
    picked: Dict[str, str] = {}
    for lm in sorted(live, key=lambda l: l["created"]):
        if lm["permanent"] or lm["proven"] or not lm["ids"]:
            continue
        if sum(1 for n in lm["ids"] if n in node_ids) / len(lm["ids"]) < MIN_LIVE_CLUSTER_FRACTION:
            picked[lm["id"]] = "dangling_cluster"
        elif lm["id"] in hubs:
            picked[lm["id"]] = "hub_cluster"
    rest = [lm for lm in live if not lm["permanent"] and lm["id"] not in picked]
    if rest:
        clock = ActivityClock(conn, min(lm["touch"] for lm in rest), now)
        for lm in sorted(rest, key=lambda l: l["created"]):
            if landmark_credibility(lm["score"], CREDIBILITY_RATE, clock.days_since(lm["touch"]),
                                    lm["n"]) < LANDMARK_PRUNE_THRESHOLD:
                picked[lm["id"]] = "no_credibility"
    order = {r: i for i, r in enumerate(_REASONS)}
    created = {lm["id"]: lm["created"] for lm in live}
    ranked = sorted(picked.items(), key=lambda kv: (order[kv[1]], created[kv[0]], kv[0]))
    return ranked[:MAX_LANDMARKS_PER_PASS], len(ranked) > MAX_LANDMARKS_PER_PASS


def _dissolve(conn, decisions: List[Tuple[str, str]]) -> Tuple[Dict[str, int], List[Tuple[List[str], str]]]:
    """Absorb the decided landmarks. Returns (count per reason, [(ids, reason)] to type)."""
    counts = {r: 0 for r in _REASONS}
    typed: List[Tuple[List[str], str]] = []
    for reason in _REASONS:
        ids = [lid for lid, why in decisions if why == reason]
        for lid in ids:
            # absorbed IS NULL: a landmark another writer already retired is not counted twice.
            app_write(
                conn,
                "UPDATE mycelium_landmarks SET absorbed = 1,"
                " falsify_if = COALESCE(falsify_if, '') || ? WHERE landmark_id = ? AND absorbed IS NULL",
                (f" | dissolved: {reason}", lid),
            )
        if ids:
            counts[reason] = len(ids)
            typed.append((ids, reason))
    return counts, typed


# ---------------------------------------------------------------------------
# Rule 3 - dangling references
# ---------------------------------------------------------------------------

def _survivors(conn, dead: Sequence[str]) -> Dict[str, Optional[str]]:
    """dead landmark id -> the live landmark that absorbed it (following the merge log
    through survivors that were absorbed later), or None (dissolved, or never merged)."""
    out: Dict[str, Optional[str]] = {d: None for d in dead}
    frontier = {d: d for d in dead}
    for _ in range(_MERGE_CHAIN_MAX):
        if not frontier:
            break
        step: Dict[str, Tuple[str, Optional[int], bool]] = {}
        for chunk in _chunks(sorted(set(frontier.values()))):
            for absorbed_id, survivor_id, flag, exists in conn.execute(
                    "SELECT m.absorbed_id, m.survivor_id, s.absorbed, s.landmark_id IS NOT NULL"
                    " FROM mycelium_landmark_merges m"
                    " LEFT JOIN mycelium_landmarks s ON s.landmark_id = m.survivor_id"
                    f" WHERE m.absorbed_id IN ({_marks(len(chunk))}) ORDER BY m.created_at",
                    list(chunk)):
                step[absorbed_id] = (survivor_id, flag, bool(exists))
        nxt: Dict[str, str] = {}
        for origin, cur in frontier.items():
            hit = step.get(cur)
            if hit is None or not hit[2]:
                continue
            survivor_id, flag, _ = hit
            if flag is None:
                out[origin] = survivor_id
            else:
                nxt[origin] = survivor_id     # the survivor was itself absorbed: follow
        frontier = nxt
    return out


def _dead_reference_ids(conn, tables: Set[str]) -> List[str]:
    parts = ["SELECT from_landmark_id AS x FROM mycelium_landmark_edges",
             "SELECT to_landmark_id FROM mycelium_landmark_edges"]
    if "mycelium_episode_index" in tables:
        parts.append("SELECT landmark_id FROM mycelium_episode_index"
                     " WHERE landmark_id IS NOT NULL AND landmark_id != ''")
    rows = conn.execute(
        f"SELECT DISTINCT x FROM ({' UNION '.join(parts)}) WHERE x IS NOT NULL AND x NOT IN"
        " (SELECT landmark_id FROM mycelium_landmarks WHERE absorbed IS NULL) LIMIT ?",
        (MAX_REFERENCE_LANDMARKS_PER_PASS,)).fetchall()
    return [r[0] for r in rows]


def _count_in(conn, sql_head: str, columns: Sequence[str], ids: Sequence[str]) -> int:
    """Rows of ``sql_head`` (SELECT <key> FROM t) whose any of ``columns`` is in ids."""
    seen: Set[Any] = set()
    for chunk in _chunks(list(ids)):
        where = " OR ".join(f"{c} IN ({_marks(len(chunk))})" for c in columns)
        params = list(chunk) * len(columns)
        seen.update(r[0] for r in conn.execute(f"{sql_head} WHERE {where}", params))
    return len(seen)


def _sweep_landmark_references(conn, tables: Set[str]) -> Dict[str, int]:
    out = {"landmark_edges_repointed": 0, "landmark_edges_removed": 0,
           "episode_index_repointed": 0, "episode_index_cleared": 0}
    dead = _dead_reference_ids(conn, tables)
    if not dead:
        return out
    survivor_of = _survivors(conn, dead)
    moved = [d for d in dead if survivor_of[d]]
    gone = [d for d in dead if not survivor_of[d]]
    edge_head = "SELECT edge_id FROM mycelium_landmark_edges"
    edge_cols = ("from_landmark_id", "to_landmark_id")

    out["landmark_edges_repointed"] = _count_in(conn, edge_head, edge_cols, moved)
    out["landmark_edges_removed"] = _count_in(conn, edge_head, edge_cols, gone)
    for d in moved:
        s = survivor_of[d]
        # Same statements as LandmarkMerger._persist_merge: OR IGNORE skips a pair the
        # survivor already has, the DELETE sweeps what was skipped.
        app_write(conn, "UPDATE OR IGNORE mycelium_landmark_edges SET from_landmark_id = ?"
                        " WHERE from_landmark_id = ? AND to_landmark_id != ?", (s, d, s))
        app_write(conn, "UPDATE OR IGNORE mycelium_landmark_edges SET to_landmark_id = ?"
                        " WHERE to_landmark_id = ? AND from_landmark_id != ?", (s, d, s))
        app_write(conn, "DELETE FROM mycelium_landmark_edges WHERE from_landmark_id = ?"
                        " OR to_landmark_id = ?", (d, d))
    for chunk in _chunks(gone):
        m = _marks(len(chunk))
        app_write(conn, f"DELETE FROM mycelium_landmark_edges WHERE from_landmark_id IN ({m})"
                        f" OR to_landmark_id IN ({m})", list(chunk) * 2)
    app_write(conn, "DELETE FROM mycelium_landmark_edges WHERE from_landmark_id = to_landmark_id")

    if "mycelium_episode_index" in tables:
        head = "SELECT idx_id FROM mycelium_episode_index"
        out["episode_index_repointed"] = _count_in(conn, head, ("landmark_id",), moved)
        out["episode_index_cleared"] = _count_in(conn, head, ("landmark_id",), gone)
        for d in moved:
            app_write(conn, "UPDATE mycelium_episode_index SET landmark_id = ? WHERE landmark_id = ?",
                      (survivor_of[d], d))
        for chunk in _chunks(gone):
            app_write(conn, f"UPDATE mycelium_episode_index SET landmark_id = NULL"
                            f" WHERE landmark_id IN ({_marks(len(chunk))})", list(chunk))
    return out


def _sweep_node_edges(conn) -> int:
    ids = [r[0] for r in conn.execute(
        "SELECT e.edge_id FROM mycelium_edges e"
        " WHERE NOT EXISTS (SELECT 1 FROM mycelium_nodes n WHERE n.node_id = e.from_node_id)"
        "    OR NOT EXISTS (SELECT 1 FROM mycelium_nodes n WHERE n.node_id = e.to_node_id)"
        " LIMIT ?", (MAX_NODE_EDGES_PER_PASS,))]
    for chunk in _chunks(ids):
        app_write(conn, f"DELETE FROM mycelium_edges WHERE edge_id IN ({_marks(len(chunk))})",
                  list(chunk))
    return len(ids)


# ---------------------------------------------------------------------------
# Rule 4 - orphan nodes
# ---------------------------------------------------------------------------

def _orphan_nodes(conn, store, now: float) -> List[Tuple[str, str]]:
    """[(node_id, space_id)] to remove, longest idle first, at most MAX_NODES_PER_PASS."""
    with_edges: Set[str] = set()
    for a, b in conn.execute("SELECT from_node_id, to_node_id FROM mycelium_edges"):
        with_edges.add(a)
        with_edges.add(b)
    in_cluster: Set[str] = set()
    for (cluster_json,) in conn.execute(
            "SELECT coordinate_cluster FROM mycelium_landmarks WHERE absorbed IS NULL"):
        try:
            cluster = json.loads(cluster_json or "[]")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(cluster, list):
            in_cluster.update(d["node_id"] for d in cluster if isinstance(d, dict) and d.get("node_id"))
    rows = [r for r in conn.execute(
        "SELECT node_id, space_id, confidence, created_at, updated_at, last_accessed, label"
        " FROM mycelium_nodes WHERE COALESCE(access_count, 0) = 0")
        # A "stated_*" node IS the user's own statement (extractor): Req 4.4, decay takes
        # back what repetition earned, never the observation itself. The other floor
        # nodes (tool, session, hardware, topic) are re-created by observing again.
        if r[0] not in with_edges and r[0] not in in_cluster
        and not (r[6] or "").startswith(STATED_NODE_PREFIX)]
    rows = [r for r in rows
            if (r[2] or 0.0) - store.spaces.confidence_floor(r[1]) <= ORPHAN_NODE_EARNED_MAX]
    if not rows:
        return []
    touch = {r[0]: max(r[3] or 0.0, r[4] or 0.0, r[5] or 0.0) for r in rows}
    clock = ActivityClock(conn, min(touch.values()), now)
    idle = [(clock.days_since(touch[r[0]]), r[0], r[1]) for r in rows]
    idle = sorted((x for x in idle if x[0] >= ORPHAN_NODE_IDLE_ACTIVE_DAYS), reverse=True)
    return [(nid, space) for _, nid, space in idle[:MAX_NODES_PER_PASS]]


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def run_integrity_pass(conn, store, merger, *, now: Optional[float] = None) -> Dict[str, int]:
    """One bounded pass of the rules above. Returns the count of every action (all keys
    always present; a quiet pass is all zeros). Never raises past a rule: a rule that
    fails is logged and counted, and the next rule runs."""
    from backend.agent import write_counters  # noqa: PLC0415 - heavy package, lazy as everywhere in memory/

    now = time.time() if now is None else now
    report: Dict[str, int] = {r: 0 for r in _REASONS}
    report.update({"landmark_edges_repointed": 0, "landmark_edges_removed": 0,
                   "episode_index_repointed": 0, "episode_index_cleared": 0,
                   "landmark_sector_rows_removed": 0, "node_edges_removed": 0,
                   "nodes_removed": 0, "landmarks_merged": 0})

    # Events leave AFTER the pass's own writes: the event lane commits on the shared
    # connection, so one emitted mid-pass would race the pass's next statements
    # (the same reason sectors.run_sector_lifecycle defers its events).
    pending: List[Tuple[tuple, dict]] = []

    def event(*args: Any, **kw: Any) -> None:
        pending.append((args, kw))

    def guarded(name: str, fn) -> Any:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - one rule never blocks the next
            write_counters.bump(f"kyudo.integrity.rule_failed.{name}")
            logger.warning("[integrity] rule %s failed: %s", name, exc)
            return None

    # 1 + 2: landmarks
    truncated = {"landmarks": False}

    def landmarks() -> None:
        ensure_landmark_policy_columns(conn)
        app_flush()
        decisions, truncated["landmarks"] = _decide_dissolutions(conn, _load_live(conn), now)
        counts, typed = _dissolve(conn, decisions)
        report.update(counts)
        for ids, reason in typed:
            event("LANDMARK_DISSOLVED", ids, payload={"reason": reason})

    guarded("landmarks", landmarks)

    # 3: references (reads see the dissolutions above)
    tables = _tables(conn)

    def references() -> None:
        app_flush()
        swept = _sweep_landmark_references(conn, tables)
        report.update(swept)
        for table, action, key in (
                ("mycelium_landmark_edges", "repointed", "landmark_edges_repointed"),
                ("mycelium_landmark_edges", "removed", "landmark_edges_removed"),
                ("mycelium_episode_index", "repointed", "episode_index_repointed"),
                ("mycelium_episode_index", "cleared", "episode_index_cleared")):
            if swept[key]:
                event("MEMORY_PRUNED", [table], id_key="table",
                      payload={"action": action, "n": swept[key]})

    guarded("references", references)

    def sector_rows() -> None:
        # The sector tables are written only by sectors.py (a scan test pins that).
        from .sectors import remove_dead_landmark_rows  # noqa: PLC0415

        n = remove_dead_landmark_rows(conn, MAX_REFERENCE_LANDMARKS_PER_PASS)
        report["landmark_sector_rows_removed"] = n
        if n:
            event("MEMORY_PRUNED", ["landmark_sector_rows"], id_key="table",
                  payload={"action": "removed", "n": n})

    guarded("sector_rows", sector_rows)

    def node_edges() -> None:
        app_flush()
        n = _sweep_node_edges(conn)
        report["node_edges_removed"] = n
        if n:
            event("MEMORY_PRUNED", ["mycelium_edges"], id_key="table",
                  payload={"action": "removed", "n": n})

    guarded("node_edges", node_edges)

    # 4: orphan nodes (dissolved landmarks no longer hold their nodes)
    def nodes() -> None:
        app_flush()
        orphans = _orphan_nodes(conn, store, now)
        for nid, _ in orphans:
            store.delete_node(nid)
        for space in {s for _, s in orphans}:
            app_write(conn, "UPDATE mycelium_profile SET dirty = 1 WHERE space_id = ?", (space,))
        report["nodes_removed"] = len(orphans)
        if orphans:
            event("MEMORY_PRUNED", [n for n, _ in orphans], id_key="node",
                  payload={"action": "removed", "reason": "orphan_node"})

    guarded("nodes", nodes)

    # 5: overlapping landmarks -> one (after the hub landmarks are gone, so a hub is
    #    never merged into a survivor that then looks proven by recurrence)
    def collapse() -> None:
        if truncated["landmarks"]:
            # Hub landmarks are still live: merging them now would crown one of their
            # claims. The next pass dissolves them first.
            write_counters.bump("kyudo.integrity.collapse_deferred")
            return
        app_flush()
        report["landmarks_merged"] = merger.collapse_duplicates(max_group=COLLAPSE_MAX_GROUP)
        if report["landmarks_merged"]:
            event("LANDMARK_MERGED", list(merger.last_absorbed), payload={"reason": "duplicate"})

    guarded("collapse", collapse)

    for args, kw in pending:
        _emit_landmark_event(conn, *args, **kw)
    for key, n in report.items():
        if n:
            write_counters.bump(f"kyudo.integrity.{key}", n)
    if any(report.values()):
        logger.info("[integrity] pass %s", " ".join(f"{k}={v}" for k, v in report.items() if v))
    return report

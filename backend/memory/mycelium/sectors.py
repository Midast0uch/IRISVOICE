"""
Sectors - a living registry of topics, in SHADOW MODE (MEMORY-INTERFACE Part II 5.1, W9).

A sector is a stable text path ("systems/memory/recall"), never a number. The 13
topic-domain registry keys (spaces.DOMAIN_IDS) are the proven ROOTS. Landmarks belong
to one or more sectors with a weight; sectors are born, proven, split, merged
(with an alias) and dissolved by the one fan-out / fold-back operator.

SHADOW: this module computes and LOGS. Nothing reads a sector - not recall, not the
prompt, not the cortex. Every lifecycle transition is a ``memory`` event with a
SECTOR_* label (event_alphabet); the tables are written and read only here (a scan
test pins that). The precision of membership, churn and false births are measured
before any consumer is allowed.

Kyudo (the trust door):
  - only a channel the ``domain`` write lock admits may create a candidate;
  - an EXTERNAL or UNTRUSTED source may propose a candidate but never close it
    (closure counts only VERIFIED-or-higher evidence);
  - the 30% untrusted cap that guards a landmark cluster guards a sector's members.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from backend.memory.db import app_flush, app_write

from .spaces import DOMAIN_IDS, MERGE_OVERLAP_THRESHOLD, domain_from_coordinate

logger = logging.getLogger(__name__)

# -- bounds (growth has a budget) - start values, tuned by measurement -----------------
SECTOR_MAX_DEPTH = 3              # a root is depth 0
SECTOR_MAX_CHILDREN = 8           # per parent
SECTOR_CANDIDATE_TTL_S = 30 * 86400.0   # a candidate that never closes folds back
BIRTH_MIN_SESSIONS = 3            # a term recurs in >= 3 sessions -> a candidate
BIRTHS_PER_PARENT = 3             # per pass
CLOSURE_MIN_LANDMARKS = 2         # outside-evidenced landmarks ...
CLOSURE_MIN_SESSIONS = 2          # ... from this many sessions (the landmark-promotion gate)
SPLIT_VARIANCE = 0.40             # the node-expand threshold, on outcomes in {-1, +1}
SPLIT_MIN_DECIDED = 4
CLUSTER_SECTORS_MAX = 3           # sectors a cluster-sourced landmark takes
CLOSE_MIN_CHANNEL = 2             # HyphaChannel.VERIFIED: weaker sources never close
_EVENT_LABELS = ("SECTOR_BORN", "SECTOR_PROVEN", "SECTOR_SPLIT", "SECTOR_MERGED",
                 "SECTOR_DISSOLVED")
_LEGACY_CHANNEL = 4               # decay.LEGACY_CHANNEL: an unmarked row is internal

_DDL = (
    """CREATE TABLE IF NOT EXISTS mycelium_sectors (
        sector_key       TEXT PRIMARY KEY,
        parent_key       TEXT,
        depth            INTEGER NOT NULL DEFAULT 0,
        status           TEXT NOT NULL DEFAULT 'candidate',
        alias_of         TEXT,
        born_from        TEXT,
        members          INTEGER DEFAULT 0,
        outside_evidence INTEGER DEFAULT 0,
        created_at       REAL NOT NULL,
        updated_at       REAL NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS mycelium_landmark_sectors (
        landmark_id TEXT NOT NULL,
        sector_key  TEXT NOT NULL,
        weight      REAL NOT NULL DEFAULT 1.0,
        source      TEXT NOT NULL,
        created_at  REAL NOT NULL,
        PRIMARY KEY (landmark_id, sector_key)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_landmark_sectors_sector ON mycelium_landmark_sectors(sector_key)",
    "CREATE INDEX IF NOT EXISTS idx_sectors_parent ON mycelium_sectors(parent_key)",
)

# Later columns are added with the ALTER pattern (a live store keeps its old shape).
_LATER_COLUMNS: Tuple[Tuple[str, str], ...] = ()


def ensure_sector_tables(conn) -> None:
    """Create the sector tables and seed the registry roots as proven. Idempotent.

    DDL runs directly (autocommitted, like every other ensure_* in the app store);
    the root rows are data and go through the one writer."""
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
        "('mycelium_sectors', 'mycelium_landmark_sectors')")}
    if have != {"mycelium_sectors", "mycelium_landmark_sectors"}:
        for stmt in _DDL:
            conn.execute(stmt)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(mycelium_sectors)")}
    for name, decl in _LATER_COLUMNS:
        if name not in cols:
            conn.execute(f"ALTER TABLE mycelium_sectors ADD COLUMN {name} {decl}")
    roots = conn.execute(
        "SELECT COUNT(*) FROM mycelium_sectors WHERE parent_key IS NULL AND depth = 0"
    ).fetchone()[0]
    if roots < len(DOMAIN_IDS):
        now = time.time()
        for key in DOMAIN_IDS:
            app_write(
                conn,
                "INSERT OR IGNORE INTO mycelium_sectors (sector_key, parent_key, depth, status,"
                " born_from, created_at, updated_at) VALUES (?, NULL, 0, 'proven', 'registry', ?, ?)",
                (key, now, now),
            )


# -- the sector of a landmark -----------------------------------------------------------

def plan_landmark_sectors(conn, label: Optional[str],
                          cluster: Iterable[Any]) -> List[Tuple[str, float, str]]:
    """The sectors a landmark belongs to: ``[(sector_key, weight, source)]``. Read-only.

    (1) the rule path research memory already uses - ``resolve_topic_domain`` on the
        task label (a miss resolves to ``general``, which is not a rule hit);
    (2) else the ``domain`` nodes in the landmark's own cluster, weighted by their
        confidence, the strongest CLUSTER_SECTORS_MAX, weights summing to 1;
    (3) else ``general``."""
    from .extractor import resolve_topic_domain   # lazy: the extractor is heavy

    key = resolve_topic_domain(label or "")
    if key != "general":
        return [(key, 1.0, "rule")]

    entries = [d for d in (cluster or []) if isinstance(d, dict) and d.get("space_id") == "domain"]
    ids = [d["node_id"] for d in entries if d.get("node_id")]
    labels: Dict[str, str] = {}
    if ids:
        labels = {nid: lab for nid, lab in conn.execute(
            f"SELECT node_id, label FROM mycelium_nodes WHERE node_id IN ({','.join('?' * len(ids))})",
            ids)}
    raw: Dict[str, float] = {}
    for d in entries:
        domain = None
        lab = labels.get(d.get("node_id")) or ""
        if lab.startswith("domain_") and lab[len("domain_"):] in DOMAIN_IDS:
            domain = lab[len("domain_"):]
        elif isinstance(d.get("coordinates"), (list, tuple)) and d["coordinates"]:
            domain = domain_from_coordinate(float(d["coordinates"][0]))
        if domain and domain != "general":
            raw[domain] = raw.get(domain, 0.0) + max(float(d.get("confidence") or 0.0), 0.0)
    if raw:
        top = sorted(raw.items(), key=lambda kv: (-kv[1], kv[0]))[:CLUSTER_SECTORS_MAX]
        total = sum(w for _, w in top)
        if total <= 0:   # every domain node at zero confidence: equal shares
            return [(k, 1.0 / len(top), "cluster") for k, _ in top]
        return [(k, w / total, "cluster") for k, w in top]
    return [("general", 1.0, "general")]


def assign_landmark_sectors(conn, landmark_id: str, label: Optional[str],
                            cluster: Iterable[Any]) -> List[Tuple[str, float, str]]:
    """Write a landmark's sectors (INSERT OR IGNORE: idempotent). Returns the plan."""
    ensure_sector_tables(conn)
    plan = plan_landmark_sectors(conn, label, cluster)
    now = time.time()
    for key, weight, source in plan:
        app_write(
            conn,
            "INSERT OR IGNORE INTO mycelium_landmark_sectors"
            " (landmark_id, sector_key, weight, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (landmark_id, key, weight, source, now),
        )
    return plan


def backfill_landmark_sectors(conn) -> Dict[str, int]:
    """Give every live landmark that has no sector one. Idempotent: a second run
    finds nothing to do. Returns counts by source."""
    ensure_sector_tables(conn)
    app_flush()   # a landmark saved a moment ago may still be queued
    rows = conn.execute(
        "SELECT l.landmark_id, l.label, l.coordinate_cluster FROM mycelium_landmarks l"
        " WHERE l.absorbed IS NULL AND NOT EXISTS"
        " (SELECT 1 FROM mycelium_landmark_sectors s WHERE s.landmark_id = l.landmark_id)"
    ).fetchall()
    counts = {"assigned": 0, "rule": 0, "cluster": 0, "general": 0}
    for landmark_id, label, cluster_json in rows:
        try:
            cluster = json.loads(cluster_json or "[]")
        except (json.JSONDecodeError, TypeError):
            cluster = []
        if not isinstance(cluster, list):   # a bootstrap landmark holds a dict
            cluster = []
        plan = assign_landmark_sectors(conn, landmark_id, label, cluster)
        counts["assigned"] += 1
        counts[plan[0][2]] += 1
    if counts["assigned"]:
        logger.info("[sectors] backfill assigned=%d rule=%d cluster=%d general=%d",
                    counts["assigned"], counts["rule"], counts["cluster"], counts["general"])
    return counts


def remove_dead_landmark_rows(conn, limit: int) -> int:
    """Remove the memberships of landmarks that are no longer live (absorbed or missing):
    the lifecycle ignores them, so they are dead weight. A merged landmark's survivor has
    its own memberships (assigned at save). At most ``limit`` landmarks per call; returns
    the rows removed. Run by the Kyudo integrity pass (integrity.py): the tables are
    written only in this module."""
    ensure_sector_tables(conn)
    app_flush()
    dead = [r[0] for r in conn.execute(
        "SELECT DISTINCT landmark_id FROM mycelium_landmark_sectors WHERE landmark_id NOT IN"
        " (SELECT landmark_id FROM mycelium_landmarks WHERE absorbed IS NULL) LIMIT ?", (limit,))]
    removed = 0
    for i in range(0, len(dead), 400):
        chunk = dead[i:i + 400]
        marks = ",".join("?" * len(chunk))
        removed += conn.execute(
            f"SELECT COUNT(*) FROM mycelium_landmark_sectors WHERE landmark_id IN ({marks})",
            chunk).fetchone()[0]
        app_write(conn, f"DELETE FROM mycelium_landmark_sectors WHERE landmark_id IN ({marks})", chunk)
    return removed


def resolve_sector_key(conn, key: str, _hops: int = 4) -> str:
    """Follow an alias (merged or dissolved sector) to the key that now holds its
    address, so an old address still resolves."""
    for _ in range(_hops):
        row = conn.execute(
            "SELECT alias_of FROM mycelium_sectors WHERE sector_key = ?", (key,)).fetchone()
        if not row or not row[0]:
            return key
        key = row[0]
    return key


# -- the lifecycle ----------------------------------------------------------------------

_STOP = frozenset(
    "about above after again also another because been before being between both "
    "could does doing done down each find from give have here into just like make "
    "many more most much need only other over please same should show some such "
    "tell than that their them then there these they this those through under "
    "until very want what when where which while will with would your yours "
    "you're that's what's".split())


def _terms(label: Optional[str]) -> set:
    """The distinguishing words of a task label (a sector key segment: [a-z0-9_])."""
    words = re.findall(r"[a-z][a-z0-9_]{3,23}", (label or "").lower())
    return {w for w in words if w not in _STOP and w not in DOMAIN_IDS}


def _default_can_write(channel: int) -> bool:
    from .registry import SpaceRegistry

    return SpaceRegistry.from_seed().can_write(channel, "domain")


def _emit_sector_event(conn, label: str, payload: dict, root: str) -> None:
    """Type one transition as a SECTOR_* event (memory family). Shadow: no chain row,
    no evidence claim (evidence 'none'). One writer: on the memory_events lane, like
    the landmark events. Never raises."""
    try:
        from backend.memory import memory_events as me
        from backend.utils.durability_queue import lane

        def _write(commit: bool) -> None:
            me.ensure_schema(conn)
            me.emit_event(conn, label=label, evidence="none", topic_domain=root,
                          payload=payload, commit=commit, chain=False)

        if lane("memory_events").in_worker():
            _write(False)
        else:
            lane("memory_events").submit(f"sector_event:{label}", _write, True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[sectors] counter event_skipped label=%s: %s", label, exc)


def run_sector_lifecycle(conn, *, now: Optional[float] = None,
                         can_write: Optional[Callable[[int], bool]] = None) -> Dict[str, list]:
    """Backfill, then one pass of birth -> closure -> split -> merge -> dissolve.
    COMPUTED and LOGGED: the decisions update the shadow tables and emit SECTOR_*
    events; no reader consumes them. Idempotent: a second pass over the same rows
    makes no transition. Run from maintenance - never on the answer path.

    ``can_write(channel) -> bool`` is the ``domain`` write lock (default: the seeded
    registry's)."""
    from .landmark import OUTSIDE_EVIDENCE   # the landmark-promotion evidence kinds
    from .kyudo import LANDMARK_TRUST_CAP

    now = time.time() if now is None else now
    can_write = can_write or _default_can_write
    out: Dict[str, list] = {k: [] for k in ("born", "proven", "split", "merged", "dissolved")}
    out["backfill"] = [backfill_landmark_sectors(conn)]   # type: ignore[assignment]
    # Events leave AFTER the pass's own writes: the event lane commits on this
    # connection, and a commit in the middle of the pass would split its writes.
    pending: List[Tuple[str, dict, str]] = []

    def emit(label: str, payload: dict, root: str) -> None:
        pending.append((label, payload, root))

    app_flush()

    # -- snapshot (one read; the pass decides on it and updates it as it goes) ----------
    sectors: Dict[str, dict] = {r[0]: {"parent": r[1], "depth": r[2], "status": r[3], "created": r[4]}
                                for r in conn.execute(
        "SELECT sector_key, parent_key, depth, status, created_at FROM mycelium_sectors")}
    channel_of: Dict[str, int] = {}
    try:
        for sid, ch in conn.execute(
                "SELECT session_id, MIN(source_channel) FROM mycelium_episode_index GROUP BY session_id"):
            channel_of[sid] = _LEGACY_CHANNEL if ch is None else int(ch)
    except Exception as exc:  # noqa: BLE001 - no index table: every landmark is internal
        logger.debug("[sectors] no episode index channels: %s", exc)
    lms: Dict[str, dict] = {}
    for lid, label, ref, tier, ev, score in conn.execute(
            "SELECT landmark_id, label, conversation_ref, tier, evidence, cumulative_score"
            " FROM mycelium_landmarks WHERE absorbed IS NULL"):
        try:
            kinds = {e.get("kind") for e in json.loads(ev or "[]") if isinstance(e, dict)}
        except (json.JSONDecodeError, TypeError):
            kinds = set()
        lms[lid] = {"label": label, "session": ref or "", "tier": tier or "candidate",
                    "outside": bool(kinds & OUTSIDE_EVIDENCE), "terms": _terms(label),
                    "channel": channel_of.get(ref or "", _LEGACY_CHANNEL)}
    members: Dict[str, set] = {}
    primary: Dict[str, str] = {}
    best_w: Dict[str, float] = {}
    for lid, key, w in conn.execute(
            "SELECT landmark_id, sector_key, weight FROM mycelium_landmark_sectors"):
        if lid not in lms:
            continue
        members.setdefault(key, set()).add(lid)
        if w > best_w.get(lid, -1.0) or (w == best_w.get(lid) and key < primary.get(lid, "~")):
            best_w[lid], primary[lid] = w, key

    def root_of(key: str) -> str:
        return key.split("/", 1)[0]

    def children_of(parent: str) -> int:
        return sum(1 for s in sectors.values() if s["parent"] == parent)

    def make_candidate(parent: str, term: str, born_from: str, landmark_ids: Iterable[str]) -> Optional[str]:
        key = f"{parent}/{term}"
        if key in sectors or sectors[parent]["depth"] + 1 > SECTOR_MAX_DEPTH \
                or children_of(parent) >= SECTOR_MAX_CHILDREN:
            return None
        depth = sectors[parent]["depth"] + 1
        sectors[key] = {"parent": parent, "depth": depth, "status": "candidate", "created": now}
        ids = sorted(landmark_ids)
        members[key] = set(ids)
        app_write(conn,
                  "INSERT OR IGNORE INTO mycelium_sectors (sector_key, parent_key, depth, status,"
                  " born_from, members, created_at, updated_at) VALUES (?, ?, ?, 'candidate', ?, ?, ?, ?)",
                  (key, parent, depth, born_from, len(ids), now, now))
        for lid in ids:
            app_write(conn,
                      "INSERT OR IGNORE INTO mycelium_landmark_sectors"
                      " (landmark_id, sector_key, weight, source, created_at) VALUES (?, ?, 1.0, 'cluster', ?)",
                      (lid, key, now))
        return key

    def set_status(key: str, status: str, alias_of: Optional[str] = None, **cols) -> None:
        sectors[key]["status"] = status
        sets = ["status = ?", "alias_of = COALESCE(?, alias_of)", "updated_at = ?"]
        params: list = [status, alias_of, now]
        for name, val in cols.items():
            sets.append(f"{name} = ?")
            params.append(val)
        app_write(conn, f"UPDATE mycelium_sectors SET {', '.join(sets)} WHERE sector_key = ?",
                  (*params, key))

    # -- birth: a term recurs in >= BIRTH_MIN_SESSIONS sessions under one parent ----------
    for parent in sorted(k for k, s in sectors.items() if s["status"] == "proven"):
        if sectors[parent]["depth"] >= SECTOR_MAX_DEPTH:
            continue
        by_term: Dict[str, set] = {}
        for lid in members.get(parent, ()):
            lm = lms[lid]
            # The Kyudo door: only a channel the domain write lock admits proposes.
            if primary.get(lid) != parent or not can_write(lm["channel"]):
                continue
            for t in lm["terms"]:
                by_term.setdefault(t, set()).add(lid)
        ranked = sorted(((len({lms[i]["session"] for i in ids}), t) for t, ids in by_term.items()),
                        key=lambda x: (-x[0], x[1]))
        taken = 0   # qualifying terms, new or already a sector: a second pass adds none
        for sessions, term in ranked:
            if sessions < BIRTH_MIN_SESSIONS or taken >= BIRTHS_PER_PARENT:
                break
            taken += 1
            key = make_candidate(parent, term, f"recurrence:{sessions}sessions", by_term[term])
            if key:
                out["born"].append(key)
                emit("SECTOR_BORN", {
                    "sector": key, "parent": parent, "sessions": sessions,
                    "landmarks": len(by_term[term])}, root_of(key))

    # -- closure: >= 2 outside-evidenced landmarks from >= 2 sessions ----------------------
    for key in sorted(k for k, s in sectors.items() if s["status"] == "candidate"):
        ids = members.get(key, set())
        if not ids:
            continue
        low = sum(1 for i in ids if lms[i]["channel"] < CLOSE_MIN_CHANNEL)
        if low / len(ids) > LANDMARK_TRUST_CAP:   # the 30% cap, on the sector's evidence
            continue
        proof = [i for i in ids if lms[i]["outside"] and lms[i]["channel"] >= CLOSE_MIN_CHANNEL]
        sessions = {lms[i]["session"] for i in proof}
        if len(proof) >= CLOSURE_MIN_LANDMARKS and len(sessions) >= CLOSURE_MIN_SESSIONS:
            set_status(key, "proven", outside_evidence=len(proof), members=len(ids))
            out["proven"].append(key)
            emit("SECTOR_PROVEN", {
                "sector": key, "landmarks": len(proof), "sessions": len(sessions)}, root_of(key))

    # -- split: a proven sector whose outcomes disagree grows a child on the minority ------
    for key in sorted(k for k, s in sectors.items() if s["status"] == "proven"):
        outcomes = {i: (1 if lms[i]["tier"] == "landmark" else -1)
                    for i in members.get(key, ()) if lms[i]["tier"] in ("landmark", "demoted")}
        if len(outcomes) < SPLIT_MIN_DECIDED:
            continue
        mean = sum(outcomes.values()) / len(outcomes)
        variance = 1.0 - mean * mean   # variance of values in {-1, +1}
        if variance <= SPLIT_VARIANCE:
            continue
        minority = -1 if mean > 0 else 1
        by_term: Dict[str, set] = {}
        for i, o in outcomes.items():
            if o == minority:
                for t in lms[i]["terms"]:
                    by_term.setdefault(t, set()).add(i)
        for term in sorted((t for t, ids in by_term.items() if len(ids) >= 2),
                           key=lambda t: (-len(by_term[t]), t)):
            child = make_candidate(key, term, "split", by_term[term])
            if child:
                out["split"].append(child)
                emit("SECTOR_SPLIT", {
                    "sector": key, "child": child, "variance": round(variance, 3),
                    "decided": len(outcomes)}, root_of(key))
                break

    # -- merge: landmark sets overlap >= MERGE_OVERLAP_THRESHOLD -> the absorbed key is an alias
    live = sorted(k for k, s in sectors.items()
                  if s["depth"] > 0 and s["status"] in ("candidate", "proven")
                  and len(members.get(k, ())) >= CLOSURE_MIN_LANDMARKS)
    gone: set = set()
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            if a in gone or b in gone or a.startswith(b + "/") or b.startswith(a + "/"):
                continue   # a child is a subset of its parent by construction
            ma, mb = members[a], members[b]
            overlap = len(ma & mb) / len(ma | mb)
            if overlap < MERGE_OVERLAP_THRESHOLD:
                continue
            rank = lambda k: (sectors[k]["status"] != "proven", -len(members[k]), len(k), k)  # noqa: E731
            keep, drop = sorted((a, b), key=rank)
            set_status(drop, "merged", alias_of=keep)
            gone.add(drop)
            out["merged"].append(drop)
            emit("SECTOR_MERGED", {
                "survivor": keep, "absorbed": drop, "overlap": round(overlap, 3)}, root_of(keep))

    # -- dissolve: a candidate that expanded for its whole time without closing -----------
    for key in sorted(k for k, s in sectors.items() if s["status"] == "candidate"):
        if now - sectors[key]["created"] > SECTOR_CANDIDATE_TTL_S:
            set_status(key, "dissolved", alias_of=sectors[key]["parent"])
            out["dissolved"].append(key)
            emit("SECTOR_DISSOLVED", {
                "sector": key, "folded_into": sectors[key]["parent"],
                "age_days": round((now - sectors[key]["created"]) / 86400.0, 1)}, root_of(key))

    for label, payload, root in pending:
        _emit_sector_event(conn, label, payload, root)
    if any(out[k] for k in ("born", "proven", "split", "merged", "dissolved")):
        logger.info("[sectors] shadow pass born=%d proven=%d split=%d merged=%d dissolved=%d",
                    len(out["born"]), len(out["proven"]), len(out["split"]),
                    len(out["merged"]), len(out["dissolved"]))
    return out

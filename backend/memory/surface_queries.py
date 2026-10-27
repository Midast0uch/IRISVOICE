"""Every SQL statement of the Memory surface, in one place (SURFACE-BUILD section 6/7, phase 0).

The surface READS the app memory (data/memory.db, opened only through resolve_memory_store_path) and the
chat store (data/conversations.db, the path conversation_store uses). It never writes either of them.

Rules this module keeps (and backend/tests/contract/test_memory_api_contract.py pins):
  * READ-ONLY. One connection per call, so one per worker thread: URI mode=ro plus PRAGMA query_only.
    A write through these connections raises. Connections are closed in a finally.
  * EVERY row query is LIMIT-bounded. Every list has a cap, every text field a preview length.
  * INDEX-BACKED. Each statement carries its EXPLAIN QUERY PLAN from the live store (2026-10-21,
    memory.db 899 MB). A statement that cannot use an index on a table that is big or can grow is NOT run:
    it is gated on the index existing (has_index_on) and reports the gap. Two indexes are missing today
    (see MISSING INDEXES). Small tables (landmarks 3.3k rows, landmark_edges 466, merges 3k, sectors 19,
    conversations 4.3k, pins 0) may SCAN; each such statement says so.
  * Optional tables and columns (sectors, pins, quorum log, tier, falsify_if, ...) read as "none" when the
    store lacks them, never as an error (table_cols / pick_cols, like export_snapshot.py).

VOCABULARY: the exporter's, unchanged. Raw tier codes ('candidate' = still learning, 'landmark' = proven),
evidence kinds mapped onto the closed alphabet (LM_EVIDENCE), families raw, territories = sector roots.
JSON keys follow docs/Design/Memory-Cortex/export_snapshot.py (landmark, event, episode, message shapes).
The word "session" in a key (event.session, claim.session) is the exporter's key for a memory thread id.

SNAPSHOT (end of file): snapshot() is the dashboard's WHOLE model in the exporter's shape (window.IRIS_MEMORY), moved here
from docs/Design/Memory-Cortex/export_snapshot.py, which is now a thin CLI over it; GET /api/memory/snapshot serves it.
Its statements follow the same rules. The one whole-table read left is the topic-domain count (GROUP BY topic_domain on
memory_chain and memory_events: no index carries the column; 16 + 12 MiB, ~70 ms warm on the live store). The statements
that would scan without memory_events(thread_id) / memory_chain(chain_id) are gated on has_index_on and warn in
meta.warnings. Pin links (mycelium_pin_links, 22k rows, no index) are read only when both ends are indexed.

MISSING INDEXES (owner decision needed; this module adds none):
  memory_events(thread_id [, ts])  - events of one strand. Until it exists, strand events come from a
      bounded ts-window scan (STRAND_EVENTS_WINDOW_SQL, at most WINDOW_SCAN_CAP rows) and the answer says
      "partial" when the window held more rows than the cap. With the index the direct query is used.
  memory_chain(chain_id)           - resolving the chain ids a RECALL_DELIVERED event names (refs). Without it
      the lookup is a full scan of a 42k-row table with big text columns (11 s warm, 98 s cold measured), so
      refs come back unresolved (resolved: false) and the turn says refs_resolved: false.
  Not needed by this module but noted: mycelium_landmark_merges(absorbed_id) (3k rows, scanned),
  mycelium_pin_links(source_id/target_id) (21k rows, pin links are not read at all).

TERRITORY RULE: a claim belongs to the root of the sector it weighs most in (mycelium_landmark_sectors). A live claim
with no sector row (30 of 72 today: the bootstrap seeds) is counted under "general" with sector null - the
exporter's default, and visible as sector null on the card.

SEARCH (end of file): search() answers GET /api/memory/search - text only, built for memory.db: claims, steps, moments, turns, pins,
artifacts, nodes and strands, ranked by the memory's own law (rank = match x kind x strength). It reads whole the small tables and a
newest-N WINDOW of the two big ones (memory_chain, memory_events), and says so in the answer. It adds no index and writes nothing.

NOT RECORDED (said once, here): which TURN received a claim. RECALL_* events name chain ids, not landmark
ids (export_snapshot.py says the same). What is derivable is the episodes that observed the claim
(mycelium_episode_index.landmark_id, indexed): claim detail returns them as observed_in, and claim_uses joins each
to the turn whose last event came just before it (USE_TURN_WINDOW_S).
"""
from __future__ import annotations

import heapq
import json
import logging
import math
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# ── bounds (every list the surface returns has one) ───────────────────────────────────────────────
CLAIMS_MAX = 200
THREADS_MAX = 100
STRANDS_PER_THREAD = 12
EVENTS_CAP = 400            # the exporter's per-thread bound
MESSAGES_CAP = 80
TRAJECTORY_CAP = 80
EPISODES_CAP = 100
CHILDREN_CAP = 50
PINS_CAP = 50
RECALL_ROWS_CAP = 400
REFS_PER_RECALL = 5         # the exporter's bound
WINDOW_SCAN_CAP = 6000      # rows of the ts window a strand-events scan may read
EVIDENCE_SHOWN = 100        # entries of one claim's evidence in the detail view
OBSERVED_CAP = 50
USES_MAX = 100              # "every time it was used": rows one call returns
USE_TURN_WINDOW_S = 600.0   # a use names the turn whose last event precedes it by at most this (live gaps 20-144 s)
EDGES_CAP = 50
MERGE_HOPS = 8
OUTSIDE_RECENT_STEPS = 3000
EVAL_SAMPLE_STEPS = 2000
PREVIEW_MESSAGE = 120
PREVIEW_INSIGHT = 140
PREVIEW_CLAIM = 280
EVAL_TITLE_PREFIXES = ("[eval]", "[pair]")   # conversations the eval harnesses create (evals/run_evals.py, run_pairs.py)
EVAL_TITLE_SQL = "(" + " OR ".join(f"title LIKE '{p}%'" for p in EVAL_TITLE_PREFIXES) + ")"
EVAL_THREAD_PREFIX = "eval-"           # memory thread ids of evaluation runs

# landmark evidence is written with its own words; map them onto the closed alphabet (exporter's table)
LM_EVIDENCE = {"task_complete": "completion", "test_pass": "test", "recurrence": "recurrence",
               "user": "user", "corroboration": "corroboration", "verifier": "verifier",
               "claim": "claim", "completion": "completion", "test": "test"}
TIER_ALIAS = {"proven": "landmark", "learning": "candidate", "landmark": "landmark", "candidate": "candidate"}
RECALL_LABELS = ("RECALL_DELIVERED", "RECALL_HELPED", "RECALL_MISLED")
INTEGRITY_LABELS = ("LANDMARK_DISSOLVED", "LANDMARK_MERGED", "MEMORY_PRUNED")


class StoreUnavailable(RuntimeError):
    """The memory store file is missing or cannot be opened."""


class NotFound(LookupError):
    """The id names nothing in the memory."""


class BadRequest(ValueError):
    """A query parameter the surface does not accept."""


# ── store access ─────────────────────────────────────────────────────────────────────────────────
def memory_db_path() -> Path:
    """The ONE app memory store (never a CWD-relative path)."""
    from backend.memory.config import resolve_memory_store_path  # noqa: PLC0415 - lazy, like the rest of memory/
    return resolve_memory_store_path()


def conversations_db_path() -> Path:
    """The chat store, by the path conversation_store itself uses (IRIS_CONVERSATIONS_DB aware)."""
    from backend import conversation_store  # noqa: PLC0415
    return Path(conversation_store._DB_PATH)


@contextmanager
def read_only(path: Path | str) -> Iterator[sqlite3.Connection]:
    """A read-only connection for the current thread; closed on exit."""
    p = Path(path)
    if not p.is_file():
        raise StoreUnavailable(f"store not found: {p.name}")
    uri = "file:" + quote(p.as_posix(), safe="/:") + "?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        raise StoreUnavailable(f"store not readable: {p.name}: {exc}") from exc
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")   # second lock on the door: a write raises even if mode=ro is lost
        yield con
    finally:
        con.close()


@contextmanager
def _optional_chat_store(path: Optional[Path | str] = None) -> Iterator[Optional[sqlite3.Connection]]:
    """The chat store (`path`, else the one conversation_store uses), or None when it does not exist (a fresh
    install): chat-side answers are then empty."""
    try:
        with read_only(path or conversations_db_path()) as con:
            yield con
    except StoreUnavailable:
        yield None


# ── small helpers (exporter's, hardened) ─────────────────────────────────────────────────────────
def ts_of(v: Any) -> Optional[float]:
    """Tables mix epoch floats, 'YYYY-MM-DD HH:MM:SS' (UTC) and ISO strings with an offset: epoch seconds."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    try:
        return float(s)
    except ValueError:
        pass
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def jload(s: Any, default: Any) -> Any:
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


def clip(v: Any, n: int = 80) -> Optional[str]:
    return None if v is None else str(v)[:n]


def table_cols(con: sqlite3.Connection, name: str) -> set[str]:
    """Column names of a table, empty when it does not exist. `name` is always a constant of this module."""
    return {r[1] for r in con.execute(f"PRAGMA table_info({name})")}


def pick_cols(have: set[str], want: tuple[str, ...]) -> str:
    """SELECT list of the wanted columns; one the store lacks is read as NULL."""
    return ", ".join(c if c in have else f"NULL AS {c}" for c in want)


def has_index_on(con: sqlite3.Connection, table: str, column: str) -> bool:
    """True when some index of `table` LEADS with `column` (so `WHERE column = ?` is a SEARCH)."""
    for ix in con.execute(f"PRAGMA index_list({table})").fetchall():
        first = con.execute(f"PRAGMA index_info({ix[1]})").fetchone()
        if first is not None and first[2] == column:
            return True
    return False


def _marks(n: int) -> str:
    return ",".join("?" * n)


def _chunks(seq: list, size: int = 400) -> Iterator[list]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def pretty_thread(tid: str) -> str:
    if tid.startswith(EVAL_THREAD_PREFIX):
        return "test run · " + tid[len(EVAL_THREAD_PREFIX):].rsplit("-", 1)[0].replace("_", " ")
    return tid


def _is_eval_thread(tid: str, title: Optional[str] = None) -> bool:
    return tid.startswith(EVAL_THREAD_PREFIX) or bool(title and title.startswith(EVAL_TITLE_PREFIXES))


# ── sectors / territories ────────────────────────────────────────────────────────────────────────
# PLAN  SELECT … FROM mycelium_sectors WHERE COALESCE(status,'proven') != 'dissolved' LIMIT 200
#       -> SCAN mycelium_sectors (19 rows; a registry, bounded by LIMIT)
def _sectors(con: sqlite3.Connection) -> list[dict]:
    cols = table_cols(con, "mycelium_sectors")
    if "sector_key" not in cols:
        return []
    want = ("sector_key", "parent_key", "label", "status", "members", "outside_evidence", "updated_at")
    out = []
    for r in con.execute(f"SELECT {pick_cols(cols, want)} FROM mycelium_sectors "
                         f"WHERE COALESCE(status, 'proven') != 'dissolved' LIMIT 200"):
        out.append({"key": r["sector_key"], "parent": r["parent_key"] or None,
                    "label": clip(r["label"], 60) or r["sector_key"].rsplit("/", 1)[-1],
                    "status": r["status"] or "proven", "members": r["members"] or 0,
                    "evidence": r["outside_evidence"] or 0, "last": ts_of(r["updated_at"])})
    return out


def _root_of(key: str, parent: dict[str, Optional[str]]) -> str:
    """A sector's territory: the root of its parent chain (the exporter's walk). A key the registry does
    not know falls back to its first path segment ('general/iris' -> 'general')."""
    root, hops = key, 0
    while parent.get(root) and hops < 6:
        root, hops = parent[root], hops + 1
    return root if root in parent else key.split("/", 1)[0]


# PLAN  SELECT landmark_id, sector_key, weight FROM mycelium_landmark_sectors LIMIT 20000
#       -> SCAN mycelium_landmark_sectors (143 rows; bounded by LIMIT)
def _best_sector(con: sqlite3.Connection, ids: Optional[list[str]] = None) -> dict[str, str]:
    """landmark id -> the sector it weighs most in. `ids` None = all rows (bounded by LIMIT)."""
    cols = table_cols(con, "mycelium_landmark_sectors")
    if not {"landmark_id", "sector_key"} <= cols:
        return {}
    w = "weight" if "weight" in cols else "1.0"
    best: dict[str, tuple[float, str]] = {}

    def take(rows) -> None:
        for r in rows:
            wt = r[2] or 0
            if r[0] not in best or wt > best[r[0]][0]:
                best[r[0]] = (wt, r[1])

    if ids is None:
        take(con.execute(f"SELECT landmark_id, sector_key, {w} FROM mycelium_landmark_sectors LIMIT 20000"))
    else:
        # PLAN  … WHERE landmark_id IN (…)  -> SEARCH … USING COVERING INDEX sqlite_autoindex_…_1 (landmark_id=?)
        for part in _chunks(ids):
            take(con.execute(f"SELECT landmark_id, sector_key, {w} FROM mycelium_landmark_sectors "
                             f"WHERE landmark_id IN ({_marks(len(part))}) LIMIT 5000", part))
    return {k: v[1] for k, v in best.items()}


def _last_integrity_pass(con: sqlite3.Connection, have: set) -> Optional[dict]:
    """The newest Kyudo cleaning event (rare labels, a handful of rows each), or None."""
    # PLAN  SELECT MAX(ts), COUNT(*) FROM memory_events WHERE family='memory' AND label=?
    #       -> SEARCH memory_events USING INDEX idx_memory_events_label (family=? AND label=?)
    last: Optional[dict] = None
    if "memory_events" in have:
        for lab in INTEGRITY_LABELS:
            ts, n = con.execute("SELECT MAX(ts), COUNT(*) FROM memory_events WHERE family = 'memory' AND label = ?",
                                (lab,)).fetchone()
            if ts is not None and (last is None or ts > last["ts"]):
                last = {"ts": ts, "label": lab, "total_of_label": n}
    return last


# ── overview ─────────────────────────────────────────────────────────────────────────────────────
def overview() -> dict:
    """Counts, territories and the last integrity pass: enough to draw the cortex labels."""
    out: dict[str, Any] = {"generated": time.time()}
    with read_only(memory_db_path()) as con:
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        counts: dict[str, Any] = {}
        # PLAN  SELECT COUNT(*) FROM memory_events -> SCAN … USING COVERING INDEX idx_memory_events_ts
        #       (41k index entries, 2.6 ms warm; the one deliberate index-only count - no filter, no row reads)
        counts["events"] = con.execute("SELECT COUNT(*) FROM memory_events").fetchone()[0] if "memory_events" in have else 0
        # PLAN  SELECT COUNT(*) FROM memory_chain -> SCAN … USING COVERING INDEX idx_memory_chain_created (42k entries)
        counts["steps"] = con.execute("SELECT COUNT(*) FROM memory_chain").fetchone()[0] if "memory_chain" in have else 0
        # PLAN  SELECT COUNT(*) FROM mycelium_landmark_edges -> SCAN … COVERING INDEX idx_landmark_edges_from (466 rows)
        counts["edges"] = con.execute("SELECT COUNT(*) FROM mycelium_landmark_edges").fetchone()[0] \
            if "mycelium_landmark_edges" in have else 0
        # PLAN  SELECT COUNT(*) FROM episodes -> SCAN … COVERING INDEX idx_ep_* (464 rows)
        counts["episodes"] = con.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] if "episodes" in have else 0
        # PLAN  SELECT COUNT(*) FROM document_data -> SCAN … COVERING INDEX idx_document_data_created (454 rows)
        counts["artifacts"] = con.execute("SELECT COUNT(*) FROM document_data").fetchone()[0] if "document_data" in have else 0

        # claims by state and tier
        # PLAN  SELECT COALESCE(absorbed,0), COALESCE(tier,'candidate'), COUNT(*) FROM mycelium_landmarks GROUP BY 1,2
        #       -> SCAN mycelium_landmarks + TEMP B-TREE FOR GROUP BY (3.3k rows, small table; no index on absorbed/tier)
        lm_cols = table_cols(con, "mycelium_landmarks")
        tier_expr = "COALESCE(tier, 'candidate')" if "tier" in lm_cols else "'candidate'"
        live: dict[str, int] = {}
        absorbed: dict[str, int] = {}
        if lm_cols:
            for a, tier, n in con.execute(f"SELECT COALESCE(absorbed, 0), {tier_expr}, COUNT(*) "
                                          f"FROM mycelium_landmarks GROUP BY 1, 2"):
                (absorbed if a else live)[tier] = n
        counts["claims_live"] = sum(live.values())
        counts["claims_absorbed"] = sum(absorbed.values())
        out["claims"] = {"live": live, "absorbed": absorbed}

        # territories: sector roots with their live claims (proven = tier other than candidate)
        sectors = _sectors(con)
        parent = {s["key"]: s["parent"] for s in sectors}
        terr: dict[str, dict] = {}
        for s in sectors:
            if not s["parent"]:
                terr[s["key"]] = {"key": s["key"], "label": s["label"], "status": s["status"], "claims": 0,
                                  "proven": 0, "learning": 0, "children": [], "last": s["last"]}
        for s in sectors:
            if s["parent"]:
                root = _root_of(s["key"], parent)
                terr.setdefault(root, {"key": root, "label": root, "status": "proven", "claims": 0, "proven": 0,
                                       "learning": 0, "children": [], "last": None})
                terr[root]["children"].append({"key": s["key"], "label": s["label"], "status": s["status"],
                                               "members": s["members"], "last": s["last"], "claims": 0})
        if lm_cols:
            # PLAN  SELECT landmark_id, tier FROM mycelium_landmarks WHERE absorbed IS NULL OR absorbed = 0
            #       -> SCAN mycelium_landmarks (3.3k rows; 72 live; ids and tier only)
            live_rows = con.execute(f"SELECT landmark_id, {tier_expr} FROM mycelium_landmarks "
                                    f"WHERE absorbed IS NULL OR absorbed = 0").fetchall()
            best = _best_sector(con)
            child_of = {c["key"]: c for t in terr.values() for c in t["children"]}
            for lid, tier in live_rows:
                key = best.get(lid)
                root = _root_of(key, parent) if key else "general"
                t = terr.setdefault(root, {"key": root, "label": root, "status": "proven", "claims": 0,
                                           "proven": 0, "learning": 0, "children": [], "last": None})
                t["claims"] += 1
                t["learning" if tier == "candidate" else "proven"] += 1
                if key in child_of:
                    child_of[key]["claims"] += 1
        territories = sorted(terr.values(), key=lambda t: (-t["claims"], t["key"]))
        for t in territories:
            t["proven_share"] = round(t["proven"] / t["claims"], 4) if t["claims"] else None   # None = nothing to share
        out["territories"] = territories

        # threads: the chat store
        with _optional_chat_store() as cdb:
            if cdb is not None:
                # PLAN  … FROM conversations WHERE parent_id IS NULL -> SEARCH … USING INDEX idx_conversations_parent
                roots, ev_roots = cdb.execute(f"SELECT COUNT(*), COALESCE(SUM({EVAL_TITLE_SQL}), 0) FROM conversations "
                                              "WHERE parent_id IS NULL").fetchone()
                # PLAN  … WHERE parent_id IS NOT NULL -> SEARCH … USING COVERING INDEX idx_conversations_parent (parent_id>?)
                strands = cdb.execute("SELECT COUNT(*) FROM conversations WHERE parent_id IS NOT NULL").fetchone()[0]
                counts["threads"], counts["threads_eval"], counts["strands"] = roots, ev_roots, strands
            else:
                counts["threads"] = counts["threads_eval"] = counts["strands"] = 0

        # eval share of the newest steps (a SAMPLE: the exact share needs memory_events(thread_id), see header)
        # PLAN  SELECT thread_id FROM memory_chain ORDER BY created_at DESC LIMIT 2000
        #       -> SCAN memory_chain USING INDEX idx_memory_chain_created (stops at the LIMIT; 2000 row lookups)
        sample = [r[0] for r in con.execute("SELECT thread_id FROM memory_chain ORDER BY created_at DESC LIMIT ?",
                                            (EVAL_SAMPLE_STEPS,))] if "memory_chain" in have else []
        out["eval_share"] = {"basis": "newest_steps", "eval": sum(1 for t in sample if t.startswith(EVAL_THREAD_PREFIX)),
                             "total": len(sample)}

        out["last_integrity_pass"] = _last_integrity_pass(con, have)
        # PLAN  SELECT ts, signal_type, shadow FROM mycelium_quorum_log ORDER BY ts DESC LIMIT 1
        #       -> SCAN mycelium_quorum_log USING INDEX idx_quorum_log_ts (LIMIT 1)
        q = None
        if table_cols(con, "mycelium_quorum_log"):
            row = con.execute("SELECT ts, signal_type, shadow FROM mycelium_quorum_log ORDER BY ts DESC LIMIT 1").fetchone()
            q = {"ts": row["ts"], "signal": row["signal_type"], "shadow": bool(row["shadow"])} if row else None
        out["last_quorum_signal"] = q
        out["available"] = {"sectors": "mycelium_sectors" in have, "pins": "mycelium_pins" in have,
                            "quorum": "mycelium_quorum_log" in have, "landmark_sectors": "mycelium_landmark_sectors" in have}
        out["counts"] = counts
    return out


# ── claims ───────────────────────────────────────────────────────────────────────────────────────
_CLAIM_COLS = ("landmark_id", "label", "task_class", "micro_abstract_text", "tier", "is_permanent", "evidence",
               "activation_count", "contradictions", "last_activated", "last_verified", "created_at",
               "conversation_ref", "absorbed", "falsify_if")


def _evidence(raw: Any, per_kind: Optional[int]) -> tuple[list[dict], dict[str, int]]:
    """Evidence entries in the closed alphabet. per_kind=4 is the exporter's card (a few dated entries per
    kind); None keeps every entry (detail view, capped by the caller)."""
    kinds: dict[str, int] = {}
    entries = []
    for e in jload(raw, [])[-400:]:
        if not isinstance(e, dict):
            continue
        k = LM_EVIDENCE.get(str(e.get("kind")), "claim")
        kinds[k] = kinds.get(k, 0) + 1
        if per_kind is None or kinds[k] <= per_kind:
            entries.append({"kind": k, "raw_kind": clip(e.get("kind"), 40), "at": ts_of(e.get("at")),
                            "session": e.get("session")})
    return entries, kinds


def _card(r: sqlite3.Row, sector: Optional[str], domain: str, channel: Optional[int], per_kind: Optional[int] = 4) -> dict:
    """The exporter's landmark shape. `fams` is not derivable without scanning events by landmark, so it is absent
    (the exporter's fallback [3, 6] would be a made-up value)."""
    ev, kinds = _evidence(r["evidence"], per_kind)
    return {"id": r["landmark_id"], "claim": clip(r["micro_abstract_text"] or (r["label"] or "").replace("_", " "), PREVIEW_CLAIM),
            "cls": r["task_class"] or "other", "tier": r["tier"] or "candidate", "permanent": bool(r["is_permanent"]),
            "evidence": ev, "evidence_counts": kinds, "activations": r["activation_count"] or 0,
            "contradictions": r["contradictions"] or 0, "last_activated": ts_of(r["last_activated"]),
            "last_verified": ts_of(r["last_verified"]), "born": ts_of(r["created_at"]),
            "session": r["conversation_ref"], "domain": domain, "sector": sector, "channel": channel,
            "absorbed": bool(r["absorbed"])}


def _channels(con: sqlite3.Connection, ids: list[str]) -> dict[str, int]:
    """Kyudo trust channel: the highest channel that ever observed the landmark."""
    cols = table_cols(con, "mycelium_episode_index")
    if not {"landmark_id", "source_channel"} <= cols or not ids:
        return {}
    out: dict[str, int] = {}
    # PLAN  … WHERE landmark_id IN (…) AND source_channel IS NOT NULL GROUP BY landmark_id
    #       -> SEARCH mycelium_episode_index USING INDEX idx_epindex_landmark (landmark_id=?)
    for part in _chunks(ids):
        for r in con.execute(f"SELECT landmark_id, MAX(source_channel) FROM mycelium_episode_index "
                             f"WHERE landmark_id IN ({_marks(len(part))}) AND source_channel IS NOT NULL "
                             f"GROUP BY landmark_id", part):
            out[r[0]] = r[1]
    return out


def _cards(con: sqlite3.Connection, rows: list[sqlite3.Row], parent: dict[str, Optional[str]],
           per_kind: Optional[int] = 4) -> list[dict]:
    ids = [r["landmark_id"] for r in rows]
    best = _best_sector(con, ids)
    chan = _channels(con, ids)
    return [_card(r, best.get(r["landmark_id"]),
                  _root_of(best[r["landmark_id"]], parent) if r["landmark_id"] in best else "general",
                  chan.get(r["landmark_id"]), per_kind) for r in rows]


def claims(territory: Optional[str] = None, tier: Optional[str] = None, limit: int = 50) -> dict:
    """Live claims, newest first. `territory` = a sector root; `tier` = candidate|landmark (or learning|proven)."""
    limit = max(1, min(int(limit), CLAIMS_MAX))
    want_tier = TIER_ALIAS.get((tier or "").strip().lower()) if tier else None
    if tier and want_tier is None:
        raise BadRequest(f"tier must be one of {sorted(TIER_ALIAS)}")
    with read_only(memory_db_path()) as con:
        have = table_cols(con, "mycelium_landmarks")
        if not have:
            return {"claims": [], "limit": limit, "territory": territory, "tier": want_tier, "count": 0}
        sel = pick_cols(have, _CLAIM_COLS)
        sectors = _sectors(con)
        parent = {s["key"]: s["parent"] for s in sectors}
        where, params = ["(absorbed IS NULL OR absorbed = 0)"], []
        if want_tier:
            where.append("COALESCE(tier, 'candidate') = ?" if "tier" in have else "'candidate' = ?")
            params.append(want_tier)
        if territory:
            # territory = the best-sector root of each claim (the same rule the overview counts by), resolved
            # in Python over the small landmark_sectors table, then fetched by primary key.
            best = _best_sector(con)
            # PLAN  SELECT landmark_id FROM mycelium_landmarks WHERE absorbed IS NULL OR absorbed = 0
            #       -> SCAN mycelium_landmarks (3.3k rows; id only)
            live_ids = [r[0] for r in con.execute("SELECT landmark_id FROM mycelium_landmarks "
                                                  "WHERE absorbed IS NULL OR absorbed = 0")]
            ids = [i for i in live_ids if (_root_of(best[i], parent) if i in best else "general") == territory]
            rows: list[sqlite3.Row] = []
            # PLAN  … WHERE (live) AND landmark_id IN (…) ORDER BY created_at DESC LIMIT ?
            #       -> SEARCH mycelium_landmarks USING INDEX sqlite_autoindex_mycelium_landmarks_1 (landmark_id=?)
            for part in _chunks(ids[:2000]):
                rows += con.execute(f"SELECT {sel} FROM mycelium_landmarks WHERE {' AND '.join(where)} "
                                    f"AND landmark_id IN ({_marks(len(part))}) ORDER BY created_at DESC LIMIT ?",
                                    params + part + [limit]).fetchall()
            rows = sorted(rows, key=lambda r: r["created_at"] or 0, reverse=True)[:limit]
        else:
            # PLAN  SELECT … FROM mycelium_landmarks WHERE (absorbed IS NULL OR absorbed = 0) [AND tier = ?]
            #       ORDER BY created_at DESC LIMIT ?
            #       -> SCAN mycelium_landmarks + TEMP B-TREE FOR ORDER BY (3.3k rows, small table; no index on
            #          absorbed/created_at). The partial index idx_landmarks_chart_origin covers only absorbed IS NULL.
            rows = con.execute(f"SELECT {sel} FROM mycelium_landmarks WHERE {' AND '.join(where)} "
                               f"ORDER BY created_at DESC LIMIT ?", params + [limit]).fetchall()
        cards = _cards(con, rows, parent)
    return {"claims": cards, "limit": limit, "territory": territory, "tier": want_tier, "count": len(cards)}


def _brief(r: sqlite3.Row) -> dict:
    return {"id": r["landmark_id"], "claim": clip(r["micro_abstract_text"] or (r["label"] or "").replace("_", " "), 160),
            "tier": r["tier"] or "candidate", "absorbed": bool(r["absorbed"])}


def claim(landmark_id: str) -> dict:
    """One claim: its card, every evidence entry, edges, the merge survivor if it was absorbed, the episodes
    that observed it. Not derivable: the turns that received it (see the module header)."""
    with read_only(memory_db_path()) as con:
        have = table_cols(con, "mycelium_landmarks")
        sel = pick_cols(have, _CLAIM_COLS)
        # PLAN  SELECT … FROM mycelium_landmarks WHERE landmark_id = ? -> SEARCH … USING INDEX sqlite_autoindex_…_1
        r = con.execute(f"SELECT {sel} FROM mycelium_landmarks WHERE landmark_id = ?", (landmark_id,)).fetchone() if have else None
        if r is None:
            raise NotFound(landmark_id)
        parent = {s["key"]: s["parent"] for s in _sectors(con)}
        out = _cards(con, [r], parent, per_kind=None)[0]
        entries, _ = _evidence(r["evidence"], None)
        out["evidence"] = entries[-EVIDENCE_SHOWN:]
        out["falsify_if"] = clip(r["falsify_if"], 240)

        # edges: out via idx_landmark_edges_from; in via the same table (to_landmark_id has no index: SCAN of 466 rows)
        edges: list[dict] = []
        if table_cols(con, "mycelium_landmark_edges"):
            # PLAN  … WHERE from_landmark_id = ? ORDER BY score DESC LIMIT ?
            #       -> SEARCH mycelium_landmark_edges USING INDEX idx_landmark_edges_from (from_landmark_id=?) + TEMP B-TREE
            # PLAN  … WHERE to_landmark_id = ? ORDER BY score DESC LIMIT ?
            #       -> SCAN mycelium_landmark_edges (466 rows, small) + TEMP B-TREE
            for direction, col in (("out", "from_landmark_id"), ("in", "to_landmark_id")):
                for e in con.execute(f"SELECT edge_id, from_landmark_id, to_landmark_id, score, edge_type, traversal_count, "
                                     f"hit_count, miss_count, last_traversed FROM mycelium_landmark_edges "
                                     f"WHERE {col} = ? ORDER BY score DESC LIMIT ?", (landmark_id, EDGES_CAP)):
                    edges.append({"id": e["edge_id"], "a": e["from_landmark_id"], "b": e["to_landmark_id"], "dir": direction,
                                  "type": e["edge_type"], "score": e["score"], "traversals": e["traversal_count"] or 0,
                                  "hits": e["hit_count"] or 0, "misses": e["miss_count"] or 0, "last": ts_of(e["last_traversed"])})
            others = sorted({(e["b"] if e["dir"] == "out" else e["a"]) for e in edges})
            brief: dict[str, dict] = {}
            for part in _chunks(others):
                # PLAN  -> SEARCH mycelium_landmarks USING INDEX sqlite_autoindex_…_1 (landmark_id=?)
                for o in con.execute(f"SELECT {sel} FROM mycelium_landmarks WHERE landmark_id IN ({_marks(len(part))})", part):
                    brief[o["landmark_id"]] = _brief(o)
            for e in edges:
                e["other"] = brief.get(e["b"] if e["dir"] == "out" else e["a"])
        out["edges"] = edges[:EDGES_CAP * 2]

        # cleaning: follow mycelium_landmark_merges to the live survivor (the log chains when a survivor is absorbed later)
        out["state"] = "live" if not out["absorbed"] else "dissolved"
        out["survivor"], out["merged_from"], out["merge_path"] = None, [], []
        if table_cols(con, "mycelium_landmark_merges"):
            if out["absorbed"]:
                cur, hops = landmark_id, 0
                while hops < MERGE_HOPS:
                    # PLAN  … WHERE absorbed_id = ? ORDER BY created_at DESC LIMIT 1
                    #       -> SCAN mycelium_landmark_merges (3k rows, small; the table has an index on survivor_id only)
                    m = con.execute("SELECT survivor_id FROM mycelium_landmark_merges WHERE absorbed_id = ? "
                                    "ORDER BY created_at DESC LIMIT 1", (cur,)).fetchone()
                    if m is None:
                        break
                    s = con.execute(f"SELECT {sel} FROM mycelium_landmarks WHERE landmark_id = ?", (m[0],)).fetchone()
                    if s is None:
                        break
                    cur, hops = m[0], hops + 1
                    out["merge_path"].append(m[0])   # a survivor that was itself cleaned later stays visible here
                    if not s["absorbed"]:
                        out["survivor"], out["state"] = _brief(s), "merged"
                        break
            # PLAN  … WHERE survivor_id = ? ORDER BY created_at DESC LIMIT ?
            #       -> SEARCH mycelium_landmark_merges USING INDEX idx_merges_survivor (survivor_id=?) + TEMP B-TREE
            out["merged_from"] = [m[0] for m in con.execute(
                "SELECT absorbed_id FROM mycelium_landmark_merges WHERE survivor_id = ? ORDER BY created_at DESC LIMIT 20",
                (landmark_id,))]
        out["cleaned_reason"] = out["falsify_if"] if out["absorbed"] else None

        # the episodes that observed it (thread = memory thread id)
        observed: list[dict] = []
        if {"landmark_id", "episode_id", "session_id"} <= table_cols(con, "mycelium_episode_index"):
            # PLAN  … WHERE landmark_id = ? ORDER BY created_at DESC LIMIT ?
            #       -> SEARCH mycelium_episode_index USING INDEX idx_epindex_landmark (landmark_id=?) + TEMP B-TREE
            for o in con.execute("SELECT episode_id, session_id, source_channel, created_at FROM mycelium_episode_index "
                                 "WHERE landmark_id = ? ORDER BY created_at DESC LIMIT ?", (landmark_id, OBSERVED_CAP)):
                observed.append({"thread": o["session_id"], "episode": o["episode_id"], "channel": o["source_channel"],
                                 "at": ts_of(o["created_at"])})
        out["observed_in"] = observed
    return out


def claim_uses(landmark_id: str, limit: int = OBSERVED_CAP) -> dict:
    """Every time a claim was used, newest first: {"uses": [{ts, thread, turn, episode, outcome, step}], "total"}.

    The truest record that names a claim is mycelium_episode_index (episode_id, session_id, landmark_id, created_at):
    one row per episode stored while the claim was in play (indexed by landmark_id; Kyudo re-points a merged
    claim's rows to its survivor). It names the THREAD (session_id) and the moment; the TURN is the one whose last
    event (memory_events episode_id "<conversation>:<turn>") in that thread came just before the row, within
    USE_TURN_WINDOW_S (episodes are stored at the turn's end; an episode id of that form wins when present), null
    when none is that close. `step` is null: nothing records which step was given the claim.
    `outcome` is the user's own verdict on the episode (episodes.user_confirmed -> helped, user_corrected -> misled);
    null when the user said nothing - never the episode's success flag, which means only "did not fail"."""
    limit = max(1, min(int(limit), USES_MAX))
    with read_only(memory_db_path()) as con:
        # PLAN  SELECT 1 FROM mycelium_landmarks WHERE landmark_id = ? -> SEARCH … USING COVERING INDEX sqlite_autoindex_…_1
        if not table_cols(con, "mycelium_landmarks") or con.execute(
                "SELECT 1 FROM mycelium_landmarks WHERE landmark_id = ?", (landmark_id,)).fetchone() is None:
            raise NotFound(landmark_id)
        if not {"landmark_id", "episode_id", "session_id", "created_at"} <= table_cols(con, "mycelium_episode_index"):
            return {"uses": [], "total": 0}
        # PLAN  SELECT COUNT(*) … WHERE landmark_id = ? -> SEARCH mycelium_episode_index USING COVERING INDEX idx_epindex_landmark (landmark_id=?)
        total = con.execute("SELECT COUNT(*) FROM mycelium_episode_index WHERE landmark_id = ?", (landmark_id,)).fetchone()[0]
        # PLAN  … WHERE landmark_id = ? ORDER BY created_at DESC LIMIT ?
        #       -> SEARCH mycelium_episode_index USING INDEX idx_epindex_landmark (landmark_id=?) + TEMP B-TREE FOR ORDER BY
        rows = con.execute("SELECT episode_id, session_id, created_at FROM mycelium_episode_index WHERE landmark_id = ? "
                           "ORDER BY created_at DESC LIMIT ?", (landmark_id, limit)).fetchall()
        verdict: dict[str, str] = {}
        # The episode row names the CONVERSATION; the index row names the claim graph's session (a chat turn ran on
        # the WS session - Episode.graph_session_id, 2026-10-26). A use belongs to the conversation when it is known.
        conv_of: dict[str, str] = {}
        if rows and {"id", "session_id", "user_confirmed", "user_corrected"} <= table_cols(con, "episodes"):
            # PLAN  … WHERE id IN (…) -> SEARCH episodes USING INDEX sqlite_autoindex_episodes_1 (id=?)
            for r in con.execute(f"SELECT id, user_confirmed, user_corrected, session_id FROM episodes WHERE id IN "
                                 f"({_marks(len(rows))})", [r[0] for r in rows]):
                if r[2]:
                    verdict[r[0]] = "misled"
                elif r[1]:
                    verdict[r[0]] = "helped"
                if r[3]:
                    conv_of[r[0]] = r[3]
        rows = [(episode, conv_of.get(episode) or thread, at) for episode, thread, at in rows]
        # The TURN of a use (2026-10-26): no writer records it on the index row, and episode ids are uuids shared by
        # turns (store() updates a near-duplicate episode), so "<conversation>:<turn>" ids are 0 of 4,460 live rows.
        # Every turn's events carry episode_id "<conversation>:<turn>" and the episode is stored at the turn's END,
        # so the turn is the one whose last event in the same thread precedes the row, within USE_TURN_WINDOW_S.
        # Live: the newest use -> the turn it came from, 20-54 s after that turn's last event, 0.1 ms per lookup.
        turn_of: dict[int, str] = {}
        if rows and {"thread_id", "ts", "episode_id"} <= table_cols(con, "memory_events"):
            for i, (_episode, thread, at) in enumerate(rows):
                if not thread or at is None:
                    continue
                # PLAN  … WHERE thread_id = ? AND ts <= ? AND ts >= ? … ORDER BY ts DESC LIMIT 1
                #       -> SEARCH memory_events USING INDEX idx_memory_events_thread_ts (thread_id=? AND ts>? AND ts<?)
                r = con.execute("SELECT episode_id FROM memory_events WHERE thread_id = ? AND ts <= ? AND ts >= ? "
                                "AND instr(episode_id, ':') > 0 ORDER BY ts DESC LIMIT 1",
                                (thread, float(at), float(at) - USE_TURN_WINDOW_S)).fetchone()
                conv, _, turn = (r[0] if r else "").partition(":")
                if turn and conv == thread:
                    turn_of[i] = turn
    uses = []
    for i, (episode, thread, at) in enumerate(rows):
        conv, _, turn = (episode or "").partition(":")
        uses.append({"ts": ts_of(at), "thread": thread,
                     "turn": turn if turn and conv == thread else turn_of.get(i),
                     "episode": episode, "outcome": verdict.get(episode), "step": None})
    return {"uses": uses, "total": total}


# ── shapes shared by strand and turn ─────────────────────────────────────────────────────────────
_EVENT_COLS = ("event_id, ts, family, label, valence, actor, evidence, episode_id, step_index, thread_id, links, "
               "payload, topic_domain")


def _event(r: sqlite3.Row) -> dict:
    """The exporter's event shape (payload is read only to name a landmark; it is never returned)."""
    links, payload = jload(r["links"], {}), jload(r["payload"], {})
    lid = ((links.get("landmark_id") or links.get("landmark")) if isinstance(links, dict) else None) or \
          (payload.get("landmark") if isinstance(payload, dict) else None)
    return {"id": r["event_id"], "ts": r["ts"], "family": r["family"], "label": r["label"], "valence": r["valence"],
            "actor": r["actor"], "evidence": r["evidence"], "episode": r["episode_id"], "step": r["step_index"],
            "session": r["thread_id"], "domain": r["topic_domain"] or "general",
            "landmark": lid if isinstance(lid, str) else None}


# ── threads / strands ────────────────────────────────────────────────────────────────────────────
def _activity(mem: sqlite3.Connection, cdb: Optional[sqlite3.Connection], strand_id: str, with_messages: bool = True) -> dict:
    """Per-strand memory activity from the indexes that exist: steps and last activity from memory_chain."""
    # PLAN  SELECT COUNT(*), MAX(created_at) FROM memory_chain WHERE thread_id = ?
    #       -> SEARCH memory_chain USING COVERING INDEX idx_memory_chain_thread (thread_id=?)
    n, last = mem.execute("SELECT COUNT(*), MAX(created_at) FROM memory_chain WHERE thread_id = ?", (strand_id,)).fetchone()
    out = {"steps": n, "last_activity": last}
    if with_messages and cdb is not None:
        # PLAN  SELECT COUNT(*) FROM messages WHERE conversation_id = ? -> SEARCH messages USING COVERING INDEX idx_messages_conv
        out["messages"] = cdb.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (strand_id,)).fetchone()[0]
    return out


def _outside_chat(mem: sqlite3.Connection, conv_ids: set[str], include_eval: bool, limit: int) -> dict:
    """Memory thread ids with no conversation. Non-eval ones are found by a loose index scan over the
    thread_id index of memory_chain (one seek per distinct id, the ranges that skip 'conv-…' and 'eval-…'
    ids, which are chats and evaluation runs). Evaluation runs are counted from the newest steps and listed
    only with include_eval."""
    # PLAN  WITH RECURSIVE t(tid) AS (SELECT MIN(thread_id) … UNION ALL SELECT (SELECT MIN(thread_id) … WHERE thread_id > t.tid …))
    #       -> SEARCH memory_chain USING COVERING INDEX idx_memory_chain_thread (thread_id>? AND thread_id<?), one seek per id
    ids: list[str] = []
    ranges = (("thread_id < 'conv-'", "thread_id < 'conv-'"),
              ("thread_id >= 'conv.' AND thread_id < 'eval-'", "thread_id < 'eval-'"),
              ("thread_id >= 'eval.'", "1"))
    for first, more in ranges:
        ids += [r[0] for r in mem.execute(
            f"WITH RECURSIVE t(tid) AS (SELECT MIN(thread_id) FROM memory_chain WHERE {first} UNION ALL "
            f"SELECT (SELECT MIN(thread_id) FROM memory_chain WHERE thread_id > t.tid AND {more}) FROM t "
            f"WHERE tid IS NOT NULL LIMIT 2000) SELECT tid FROM t WHERE tid IS NOT NULL")]
    items = []
    for tid in ids:
        if tid in conv_ids:
            continue
        a = _activity(mem, None, tid, with_messages=False)
        items.append({"id": tid, "label": pretty_thread(tid), "source": "outside", **a})
    recent_eval = 0
    if include_eval:
        # PLAN  SELECT thread_id, COUNT(*), MAX(created_at) FROM (… ORDER BY created_at DESC LIMIT 3000) GROUP BY thread_id
        #       -> SCAN memory_chain USING INDEX idx_memory_chain_created (stops at the LIMIT) + TEMP B-TREE FOR GROUP BY
        for tid, n, last in mem.execute(
                "SELECT thread_id, COUNT(*), MAX(created_at) FROM (SELECT thread_id, created_at FROM memory_chain "
                "ORDER BY created_at DESC LIMIT ?) WHERE thread_id >= ? AND thread_id < ? GROUP BY thread_id",
                (OUTSIDE_RECENT_STEPS, EVAL_THREAD_PREFIX, "eval.")):
            recent_eval += 1
            items.append({"id": tid, "label": pretty_thread(tid), "source": "evaluation", "steps": n, "last_activity": last})
    items.sort(key=lambda i: i["last_activity"] or 0, reverse=True)
    return {"count": len([i for i in items if i["source"] == "outside"]), "evaluation_recent": recent_eval,
            "items": items[:limit], "eval_included": include_eval}


def threads(limit: int = 30, include_eval: bool = False) -> dict:
    """Thread roots with their strands (conversations.parent_id) and each strand's memory activity, plus the
    'outside chat' group. A strand IS a conversation row; the root is its own first strand. Memory thread id =
    conversation id (3,233 of 3,246 non-eval memory threads resolve this way)."""
    limit = max(1, min(int(limit), THREADS_MAX))
    with read_only(memory_db_path()) as mem, _optional_chat_store() as cdb:
        roots: list[dict] = []
        conv_ids: set[str] = set()
        total = hidden_eval = 0
        if cdb is not None:
            # PLAN  SELECT COUNT(*), SUM(title LIKE '[eval]%') FROM conversations WHERE parent_id IS NULL
            #       -> SEARCH conversations USING INDEX idx_conversations_parent (parent_id=?)
            total, hidden_eval = cdb.execute(f"SELECT COUNT(*), COALESCE(SUM({EVAL_TITLE_SQL}), 0) FROM conversations "
                                             "WHERE parent_id IS NULL").fetchone()
            # PLAN  SELECT id FROM conversations -> SCAN conversations USING COVERING INDEX sqlite_autoindex_conversations_1 (4.3k)
            conv_ids = {r[0] for r in cdb.execute("SELECT id FROM conversations")}
            flt = "" if include_eval else f"AND NOT {EVAL_TITLE_SQL} "
            # PLAN  SELECT … FROM conversations WHERE parent_id IS NULL [AND title NOT LIKE ?] ORDER BY updated_at DESC LIMIT ?
            #       -> SEARCH conversations USING INDEX idx_conversations_parent (parent_id=?) + TEMP B-TREE FOR ORDER BY
            #          (4.3k rows, small; conversations has no updated_at index - chat's own thread list reads the same way)
            rows = cdb.execute("SELECT id, title, created_at, updated_at, pinned, tags, project_id FROM conversations "
                               f"WHERE parent_id IS NULL {flt}ORDER BY updated_at DESC LIMIT ?",
                               (limit,)).fetchall()
            kids: dict[str, list] = {}
            ids = [r["id"] for r in rows]
            for part in _chunks(ids):
                # PLAN  … WHERE parent_id IN (…) ORDER BY created_at LIMIT ? -> SEARCH conversations USING INDEX idx_conversations_parent
                for k in cdb.execute(f"SELECT id, parent_id, title, created_at, updated_at, tags, reports_to FROM conversations "
                                     f"WHERE parent_id IN ({_marks(len(part))}) ORDER BY created_at LIMIT ?",
                                     part + [len(part) * STRANDS_PER_THREAD]):
                    kids.setdefault(k["parent_id"], []).append(k)
            for r in rows:
                strands = [{"id": r["id"], "title": r["title"], "parent": None, "root": True, "created": ts_of(r["created_at"]),
                            "updated": ts_of(r["updated_at"]), "reports_to": None,
                            **_activity(mem, cdb, r["id"])}]
                for k in kids.get(r["id"], [])[:STRANDS_PER_THREAD - 1]:
                    strands.append({"id": k["id"], "title": k["title"], "parent": k["parent_id"], "root": False,
                                    "created": ts_of(k["created_at"]), "updated": ts_of(k["updated_at"]),
                                    "reports_to": k["reports_to"], **_activity(mem, cdb, k["id"])})
                roots.append({"id": r["id"], "title": r["title"], "pinned": bool(r["pinned"]), "eval": _is_eval_thread(r["id"], r["title"]),
                              "updated": ts_of(r["updated_at"]), "tags": clip(r["tags"], 200), "project": r["project_id"],
                              "strand_count": 1 + len(kids.get(r["id"], [])), "strands": strands,
                              "last_activity": max([s["last_activity"] or 0 for s in strands]) or None})
        outside = _outside_chat(mem, conv_ids, include_eval, limit)
    return {"threads": roots, "limit": limit, "total": total, "eval_hidden": 0 if include_eval else hidden_eval,
            "outside_chat": outside}


# PLAN  SELECT e.<cols> FROM (SELECT event_id FROM (SELECT event_id, thread_id FROM memory_events
#         WHERE ts >= ? AND ts <= ? ORDER BY ts DESC LIMIT 6000) WHERE thread_id = ? LIMIT 400) w
#       JOIN memory_events e ON e.event_id = w.event_id ORDER BY e.ts DESC
#       -> SEARCH memory_events USING INDEX idx_memory_events_ts (ts>? AND ts<?), then SEARCH e USING INDEX
#          sqlite_autoindex_memory_events_1 (event_id=?). Reads at most WINDOW_SCAN_CAP index entries.
STRAND_EVENTS_WINDOW_SQL = (
    f"SELECT {', '.join('e.' + c.strip() for c in _EVENT_COLS.split(','))} FROM "
    "(SELECT event_id FROM (SELECT event_id, thread_id FROM memory_events WHERE ts >= ? AND ts <= ? "
    "ORDER BY ts DESC LIMIT ?) WHERE thread_id = ? LIMIT ?) w JOIN memory_events e ON e.event_id = w.event_id "
    "ORDER BY e.ts DESC")
# PLAN  with memory_events(thread_id, ts): SEARCH memory_events USING INDEX <that index> (thread_id=?)
STRAND_EVENTS_DIRECT_SQL = f"SELECT {_EVENT_COLS} FROM memory_events WHERE thread_id = ? ORDER BY ts DESC LIMIT ?"
# PLAN  SELECT COUNT(*) FROM (SELECT 1 FROM memory_events WHERE ts >= ? AND ts <= ? LIMIT 6001)
#       -> SEARCH memory_events USING COVERING INDEX idx_memory_events_ts (ts>? AND ts<?)
WINDOW_FULL_SQL = "SELECT COUNT(*) FROM (SELECT 1 FROM memory_events WHERE ts >= ? AND ts <= ? LIMIT ?)"


def _strand_events(mem: sqlite3.Connection, strand_id: str, lo: Optional[float], hi: Optional[float]) -> tuple[list[dict], bool, str]:
    """(events newest first, partial, how). partial = the ts window held more rows than the scan cap."""
    if has_index_on(mem, "memory_events", "thread_id"):
        return [_event(r) for r in mem.execute(STRAND_EVENTS_DIRECT_SQL, (strand_id, EVENTS_CAP))], False, "index"
    if lo is None or hi is None:
        return [], False, "window"
    lo, hi = lo - 60.0, hi + 600.0
    rows = mem.execute(STRAND_EVENTS_WINDOW_SQL, (lo, hi, WINDOW_SCAN_CAP, strand_id, EVENTS_CAP)).fetchall()
    partial = mem.execute(WINDOW_FULL_SQL, (lo, hi, WINDOW_SCAN_CAP + 1)).fetchone()[0] > WINDOW_SCAN_CAP
    return [_event(r) for r in rows], partial, "window"


def strand(strand_id: str) -> dict:
    """One strand's corridor data in the exporter's session shape: events, message previews, trajectory,
    episodes, child strands, pins."""
    now = time.time()
    with read_only(memory_db_path()) as mem, _optional_chat_store() as cdb:
        conv = None
        if cdb is not None:
            # PLAN  SELECT … FROM conversations WHERE id = ? -> SEARCH conversations USING INDEX sqlite_autoindex_conversations_1
            conv = cdb.execute("SELECT id, title, created_at, updated_at, parent_id, tags, reports_to, project_id "
                               "FROM conversations WHERE id = ?", (strand_id,)).fetchone()
        act = _activity(mem, cdb, strand_id)
        if conv is None and act["steps"] == 0:
            raise NotFound(strand_id)
        # PLAN  SELECT MIN(created_at), MAX(created_at) FROM memory_chain WHERE thread_id = ?
        #       -> SEARCH memory_chain USING COVERING INDEX idx_memory_chain_thread (thread_id=?)
        lo, hi = mem.execute("SELECT MIN(created_at), MAX(created_at) FROM memory_chain WHERE thread_id = ?", (strand_id,)).fetchone()
        if lo is None and conv is not None:
            lo, hi = ts_of(conv["created_at"]), ts_of(conv["updated_at"])
        events, partial, how = _strand_events(mem, strand_id, lo, hi)

        traj: list[dict] = []
        exit_kind = "natural"
        if table_cols(mem, "caducean_trajectories"):
            # PLAN  SELECT x, y, xi, u FROM caducean_trajectories WHERE session_id = ? ORDER BY id LIMIT 80
            #       -> SEARCH caducean_trajectories USING INDEX idx_ct_session (session_id=?) (rowid order: no sort)
            traj = [{"x": r[0] or 0.0, "y": r[1] or 0.0, "xi": r[2] or 0.0, "u": r[3] or 0.0}
                    for r in mem.execute("SELECT x, y, xi, u FROM caducean_trajectories WHERE session_id = ? "
                                         "ORDER BY id LIMIT ?", (strand_id, TRAJECTORY_CAP))]
        if table_cols(mem, "caducean_session_exits"):
            # PLAN  SELECT natural_exit, drift FROM caducean_session_exits WHERE session_id = ? ORDER BY id DESC LIMIT 1
            #       -> SEARCH … USING INDEX idx_se_session (session_id=?)
            x = mem.execute("SELECT natural_exit, drift FROM caducean_session_exits WHERE session_id = ? "
                            "ORDER BY id DESC LIMIT 1", (strand_id,)).fetchone()
            if x and x[1] and not x[0]:
                exit_kind = "drift"

        episodes: list[dict] = []
        if table_cols(mem, "episodes"):
            # PLAN  SELECT … FROM episodes WHERE session_id = ? ORDER BY timestamp DESC LIMIT 100
            #       -> SEARCH episodes USING INDEX idx_ep_session (session_id=?) + TEMP B-TREE FOR ORDER BY
            for r in mem.execute("SELECT id, task_summary, outcome_type, outcome_score, failure_reason, user_corrected, "
                                 "user_confirmed, duration_ms, tool_sequence, timestamp FROM episodes WHERE session_id = ? "
                                 "ORDER BY timestamp DESC LIMIT ?", (strand_id, EPISODES_CAP)):
                tools = [s.get("tool") for s in jload(r["tool_sequence"], []) if isinstance(s, dict) and s.get("tool")][:12]
                episodes.append({"id": r["id"], "session": strand_id, "summary": (r["task_summary"] or "")[:160],
                                 "outcome": r["outcome_type"] or "partial", "score": r["outcome_score"] or 0.0,
                                 "failure_reason": clip(r["failure_reason"], 200), "corrected": bool(r["user_corrected"]),
                                 "confirmed": bool(r["user_confirmed"]), "duration": (r["duration_ms"] or 0) / 1000.0,
                                 "tools": tools, "ts": ts_of(r["timestamp"])})

        messages: list[dict] = []
        children: list[dict] = []
        if cdb is not None:
            # PLAN  SELECT role, timestamp, substr(text,1,120), length(text) FROM messages WHERE conversation_id = ?
            #       ORDER BY timestamp LIMIT 80 -> SEARCH messages USING INDEX idx_messages_conv (conversation_id=?)
            for r in cdb.execute("SELECT role, timestamp, substr(text, 1, ?), length(text), turn_id FROM messages "
                                 "WHERE conversation_id = ? ORDER BY timestamp LIMIT ?", (PREVIEW_MESSAGE, strand_id, MESSAGES_CAP)):
                messages.append({"role": "user" if r[0] == "user" else "iris", "ts": ts_of(r[1]), "text": r[2],
                                 "len": r[3] or 0, "turn": r[4]})
            # PLAN  SELECT id, title, created_at, updated_at FROM conversations WHERE parent_id = ? LIMIT 50
            #       -> SEARCH conversations USING INDEX idx_conversations_parent (parent_id=?)
            for r in cdb.execute("SELECT id, title, created_at, updated_at FROM conversations WHERE parent_id = ? LIMIT ?",
                                 (strand_id, CHILDREN_CAP)):
                children.append({"id": r[0], "title": r[1], "started": ts_of(r[2]), "ended": ts_of(r[3])})

        pins: list[dict] = []
        project = conv["project_id"] if conv is not None else None
        pin_cols = table_cols(mem, "mycelium_pins")
        if project and pin_cols:
            want = ("pin_id", "title", "pin_type", "tags", "file_refs", "image_refs", "url_refs", "project_id", "created_at",
                    "is_permanent")
            # Pins of the strand's PROJECT (conversations.project_id = mycelium_pins.project_id): pins carry no strand
            # id. Pin links (mycelium_pin_links, 21k rows, no index) are not read; links counts the refs only.
            # PLAN  … FROM mycelium_pins WHERE project_id = ? ORDER BY created_at DESC LIMIT 50
            #       -> SCAN mycelium_pins + TEMP B-TREE (an explicit-memory table: 0 rows today, tens by design)
            for r in mem.execute(f"SELECT {pick_cols(pin_cols, want)} FROM mycelium_pins WHERE project_id = ? "
                                 f"ORDER BY created_at DESC LIMIT ?", (project, PINS_CAP)):
                tags = [str(t) for t in jload(r["tags"], []) if isinstance(t, (str, int))][:8]
                nrefs = sum(len(jload(r[k], [])) for k in ("file_refs", "image_refs", "url_refs"))
                pins.append({"id": r["pin_id"], "title": clip(r["title"], 80), "type": r["pin_type"] or "note",
                             "created": ts_of(r["created_at"]), "permanent": bool(r["is_permanent"]),
                             "held": bool({"held", "context"} & set(tags)), "links": nrefs, "tags": tags[:6]})

    stamps = [e["ts"] for e in events] or [t for t in (lo, hi) if t]
    started = min(stamps) if stamps else (ts_of(conv["created_at"]) if conv is not None else None)
    ended = max(stamps) if stamps else (ts_of(conv["updated_at"]) if conv is not None else None)
    live = ended is not None and now - ended < 600
    title = conv["title"] if conv is not None and conv["title"] else pretty_thread(strand_id)
    return {"id": strand_id, "objective": title, "in_chat": conv is not None, "eval": _is_eval_thread(strand_id, title),
            "parent": conv["parent_id"] if conv is not None else None, "reports_to": conv["reports_to"] if conv is not None else None,
            "started": started, "ended": None if live else ended, "exit": "live" if live else exit_kind,
            "activity": {**act, "events": len(events), "events_partial": partial, "events_how": how},
            "traj": traj, "events": events, "episodes": episodes, "messages": messages, "strands": children, "pins": pins}


# ── turn ─────────────────────────────────────────────────────────────────────────────────────────
# PLAN  SELECT <cols> FROM memory_events WHERE episode_id IN (?, ?) AND thread_id = ? ORDER BY ts LIMIT 400
#       -> SEARCH memory_events USING INDEX idx_memory_events_episode (episode_id=?) + TEMP B-TREE FOR ORDER BY
TURN_EVENTS_SQL = ("SELECT {cols} FROM memory_events WHERE episode_id IN (?, ?) AND thread_id = ? ORDER BY ts LIMIT ?")
# PLAN  SELECT chain_id, MIN(thread_id), … FROM memory_chain WHERE chain_id IN (…) GROUP BY chain_id LIMIT 400
#       -> SCAN memory_chain WITHOUT an index on chain_id: NEVER RUN unless has_index_on(memory_chain, chain_id)
CHAIN_REFS_SQL = ("SELECT chain_id, MIN(thread_id), MIN(insight), MIN(result), MIN(mediator), MIN(created_at), MIN(node_type) "
                  "FROM memory_chain WHERE chain_id IN ({marks}) GROUP BY chain_id LIMIT ?")


def turn(conversation_id: str, turn_id: str) -> dict:
    """A turn's recalls (RECALL_DELIVERED + verdict joined by recall_trace_id, refs resolved to chain rows when
    memory_chain(chain_id) is indexed) and its moments. Live turns carry a bare episode id ('f14d665f-043');
    evaluation turns carry '<thread>:<id>' - both are tried, and the thread must match."""
    with read_only(memory_db_path()) as mem:
        if "memory_events" not in {r[0] for r in mem.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}:
            raise NotFound(turn_id)
        rows = mem.execute(TURN_EVENTS_SQL.format(cols=_EVENT_COLS),
                           (turn_id, f"{conversation_id}:{turn_id}", conversation_id, RECALL_ROWS_CAP)).fetchall()
        if not rows:
            raise NotFound(f"{conversation_id}/{turn_id}")
        traces: dict[str, dict] = {}
        moments: list[dict] = []
        for r in rows:
            if r["label"] not in RECALL_LABELS:
                moments.append(_event(r))
                continue
            tid = (jload(r["links"], {}) or {}).get("recall_trace_id")
            if not tid:
                continue
            t = traces.setdefault(tid, {"trace": tid, "outcome": None, "step": None, "ts": None, "source": None, "refs": []})
            if r["label"] == "RECALL_DELIVERED":
                p = jload(r["payload"], {}) or {}
                t.update(step=r["step_index"], ts=r["ts"], source=p.get("source") or "neighbors",
                         refs=[x for x in (p.get("refs") or []) if isinstance(x, str) and x][:REFS_PER_RECALL])
            else:
                t["outcome"] = "helped" if r["label"] == "RECALL_HELPED" else "misled"
        steps = sorted((t for t in traces.values() if t["ts"] is not None), key=lambda t: t["ts"])

        want = sorted({c for t in steps for c in t["refs"]})
        resolved = bool(want) and has_index_on(mem, "memory_chain", "chain_id")
        chain: dict[str, dict] = {}
        if resolved:
            for part in _chunks(want):
                for r in mem.execute(CHAIN_REFS_SQL.format(marks=_marks(len(part))), part + [RECALL_ROWS_CAP]):
                    chain[r[0]] = {"id": r[0], "session": r[1], "did": (r[2] or "")[:PREVIEW_INSIGHT], "result": r[3] or None,
                                   "tool": (r[4] or "").split(":")[0] or None, "ts": ts_of(r[5]), "kind": r[6] or "step",
                                   "resolved": True}
        for t in steps:
            t["refs"] = [chain.get(c, {"id": c, "session": None, "did": "", "result": None, "tool": None, "ts": None,
                                       "kind": "step", "resolved": False}) for c in t["refs"]]
    return {"conversation": conversation_id, "turn": turn_id, "recalls": steps, "moments": moments,
            "refs_resolved": resolved or not want, "truncated": len(rows) >= RECALL_ROWS_CAP}


# ── snapshot: the whole memory model of the dashboard (docs/Design/Memory-Cortex/export_snapshot.py) ──
# ONE model, ONE shape: window.IRIS_MEMORY = {meta, famCounts, domCounts, sessions, events, landmarks, edges,
# episodes, artifacts, oracle, mind, sectors, pins, spaces, nodes, nodeEdges, quorum, recalls}. The offline exporter
# is now a thin CLI over snapshot(); the mockup and the app read the same shape from the same SQL.
SNAPSHOT_THREADS_MAX = 120          # API bound; the exporter's default is 48
SNAPSHOT_EVENTS_MAX = 12000         # API bound; the exporter's default is 6000
SNAPSHOT_EVENTS_PER_THREAD = 400    # the exporter's per-thread bound (EVENTS_CAP)
SNAPSHOT_RECALL_ROWS = 8000
SNAPSHOT_EVAL_SAMPLE = 6000         # events sampled for eval_share while memory_events(thread_id) is not indexed
SNAPSHOT_LANDMARKS = 1000            # 516 live after the 2026-10-25 repair (400 cut territories short); the scene keeps
                                     # 2 texels per claim in one row: 1000 x 2 <= 2048, WebGL2's guaranteed width
SNAPSHOT_CLAIM_STEPS = 12           # nodes of a claim's traversal the page draws (its steps)
SNAPSHOT_THREAD_CANDIDATES = 4      # x threads: the wider set the eval-title cut draws from
SNAPSHOT_EDGES = 3000
SNAPSHOT_TRAJECTORY_ROWS = 6000
SNAPSHOT_TRAJECTORY_STEPS = 80
SNAPSHOT_EPISODES = 300
SNAPSHOT_ARTIFACTS = 80
SNAPSHOT_PINS = 200
SNAPSHOT_PIN_LINKS = 4000
SNAPSHOT_NODES = 600
SNAPSHOT_NODE_EDGES = 4000
SNAPSHOT_QUORUM = 80
REPORT_SOURCE = "strand_report:"              # messages.source of a helper's report (= conversation_store.REPORT_SOURCE)
SNAPSHOT_GHOSTS = 60                          # dissolved claims the health view outlines (UX-PLAN 7.5)
GHOST_DAYS = 7                                # ... for a week after the integrity pass dissolved them
SNAPSHOT_RECALL_TURNS = 60
# the topic-domain registry (memory_chain.topic_domain values): a pin may name one in its tags
DOM_KEYS = ["general", "web", "science", "data", "finance", "ai", "design", "mobile", "systems", "devops", "security", "hardware"]
FAMILIES = ["intent", "control", "problem", "knowledge", "feedback", "delivery", "memory", "safety", "environment"]
DOC_KIND = {"image": "image", "research": "web", "json": "doc", "markdown": "doc", "code": "code", "document": "doc",
            "video": "video", "audio": "audio"}
DOC_FOLDER = {"research": "research records", "json": "structured data", "markdown": "notes", "image": "images"}
_BENCH_BAR = Path(__file__).resolve().parents[2] / "benchmarks" / "consumer_bar_record.json"


def _snap_oracle(warnings: list[str]) -> list[dict]:
    """Per-consumer state from the bar record (the exporter's shape; GET /oracle serves the richer one). No DB."""
    out: list[dict] = []
    try:
        for cid, v in json.loads(_BENCH_BAR.read_text(encoding="utf-8")).items():
            out.append({"consumer": cid, "state": v.get("status", "shadow"), "rows": v.get("rows") or 0,
                        "auroc": v.get("auroc") or 0.5, "ece": v.get("ece"), "precision": v.get("precision") or 0.0})
    except (OSError, ValueError, AttributeError) as exc:
        warnings.append(f"consumer bar record unreadable: {exc}")
    return out


def snapshot(threads: int = 48, events: int = 6000, include_eval: bool = False, *,
             db: Optional[Path | str] = None, conv_db: Optional[Path | str] = None) -> dict:
    """The dashboard's memory model, bounded and read-only. `threads` newest threads with their `events` newest
    events (at most 400 each), 1000 live landmarks, 300 episodes, 80 artifacts, 600 nodes, ... include_eval=False
    drops eval-* threads. `db` / `conv_db` name another store (the exporter's --db; a git worktree has no data/).
    Optional tables a newer build adds read as "none" (meta.available says which were found).

    Every statement is LIMIT-bounded or a small-table read; the ones that would SCAN a big table when memory_events
    (thread_id) / memory_chain(chain_id) are not indexed are gated on has_index_on and say so in meta.warnings."""
    threads = max(1, min(int(threads), SNAPSHOT_THREADS_MAX))
    events = max(1, min(int(events), SNAPSHOT_EVENTS_MAX))
    warnings: list[str] = []
    available: dict[str, bool] = {}
    # WHERE THE TIME GOES (2026-10-21: a first call after a backend start took > 300 s, the next 1.0 s): one INFO line
    # per call with the total and each part, so the next cold start names the slow statement group.
    ref, t_start, parts = uuid.uuid4().hex[:8], time.perf_counter(), {}
    t_lap = t_start

    def lap(part: str) -> None:
        nonlocal t_lap
        t_now = time.perf_counter()
        parts[part] = parts.get(part, 0.0) + (t_now - t_lap)
        t_lap = t_now

    with read_only(db or memory_db_path()) as con:
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        lap("open")
        # ① counts. PLAN (live store 2026-10-21): every COUNT(*) below is a SCAN of the table's smallest covering index
        # (events 42k, chain 42k, chunks 120k index entries) or of a small table (landmarks 3.3k, edges 466, merges 3k,
        # episodes 464, documents 454); no row is read.
        def n(table: str, where: str = "") -> int:
            return con.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0] if table in have else 0

        lm_cols = table_cols(con, "mycelium_landmarks")
        live_sql = "WHERE COALESCE(absorbed, 0) = 0" if "absorbed" in lm_cols else ""
        counts = {"events": n("memory_events"), "chain": n("memory_chain"),
                  "landmarks": n("mycelium_landmarks", live_sql),
                  "landmarks_absorbed": n("mycelium_landmarks", "WHERE absorbed = 1") if "absorbed" in lm_cols else 0,
                  "edges": n("mycelium_landmark_edges"), "merges": n("mycelium_landmark_merges"),
                  "episodes": n("episodes"), "fragments": n("context_chunks"), "artifacts": n("document_data")}
        integrity = _last_integrity_pass(con, have)   # the territory health line names the last cleaning (UX-PLAN 7.2)
        lap("counts")
        ev_cols = table_cols(con, "memory_events")
        ev_thread_idx = "memory_events" in have and has_index_on(con, "memory_events", "thread_id")

        # PLAN  SELECT family, COUNT(*) FROM memory_events GROUP BY family
        #       -> SCAN memory_events USING COVERING INDEX idx_memory_events_label (family, label) (42k entries)
        fam_counts = {r[0]: r[1] for r in con.execute("SELECT family, COUNT(*) FROM memory_events GROUP BY family")} \
            if "memory_events" in have else {}
        lap("fam_counts")
        # territories of the lattice: topic domains. memory_chain is the only table that carries them in volume
        # (2026-10-18: memory_events ~90% NULL); NULL counts as "general"
        dom_counts: dict[str, int] = {}
        for tbl in ("memory_chain", "memory_events"):
            if tbl in have and "topic_domain" in table_cols(con, tbl):
                # PLAN  SELECT COALESCE(topic_domain,'general'), COUNT(*) FROM <tbl> GROUP BY 1
                #       -> SCAN <tbl> USING COVERING INDEX idx_<tbl>_domain + TEMP B-TREE FOR GROUP BY (the index the app
                #          schema builds since 2026-10-25). On a store without it, the one whole-table read of the
                #          snapshot: 40-50 s each cold on the hard disk, measured in the [memory_snapshot] log line.
                for r in con.execute(f"SELECT COALESCE(topic_domain, 'general'), COUNT(*) FROM {tbl} GROUP BY 1"):
                    dom_counts[r[0]] = dom_counts.get(r[0], 0) + r[1]
                lap(f"dom_counts_{tbl}")
        # eval share of the events: exact when thread_id is indexed (a range count on the index), else a sample
        # of the newest events (the ts index; bounded) and a warning
        eval_share = [0, 0]
        if "memory_events" in have:
            if ev_thread_idx:
                # PLAN  SELECT COUNT(*) FROM memory_events WHERE thread_id >= 'eval-' AND thread_id < 'eval.'
                #       -> SEARCH memory_events USING COVERING INDEX <the thread_id index> (thread_id>? AND thread_id<?)
                eval_share = [con.execute("SELECT COUNT(*) FROM memory_events WHERE thread_id >= ? AND thread_id < ?",
                                          (EVAL_THREAD_PREFIX, "eval.")).fetchone()[0], counts["events"]]
            else:
                # PLAN  SELECT SUM(...), COUNT(*) FROM (SELECT thread_id FROM memory_events ORDER BY ts DESC LIMIT ?)
                #       -> SCAN memory_events USING INDEX idx_memory_events_ts (stops at the LIMIT)
                s, t = con.execute("SELECT SUM(thread_id LIKE 'eval-%'), COUNT(*) FROM "
                                   "(SELECT thread_id FROM memory_events ORDER BY ts DESC LIMIT ?)",
                                   (SNAPSHOT_EVAL_SAMPLE,)).fetchone()
                eval_share = [s or 0, t or 0]
                warnings.append(f"eval_share is a sample of the newest {t} events: memory_events(thread_id) is not indexed")
        lap("eval_share")

        # ② events (newest first, bounded) and the threads they belong to
        # PLAN  SELECT <cols> FROM memory_events [WHERE thread_id NOT LIKE 'eval-%'] ORDER BY ts DESC LIMIT ?
        #       -> SCAN memory_events USING INDEX idx_memory_events_ts (ts order; stops at the LIMIT)
        where = "" if include_eval else "WHERE thread_id NOT LIKE 'eval-%'"
        ev_want = ("event_id", "ts", "family", "label", "valence", "actor", "evidence", "episode_id", "thread_id", "links",
                   "payload", "topic_domain")
        chat_path = conv_db if conv_db else (Path(db).with_name("conversations.db") if db else None)
        eval_convs: Optional[set] = None
        if not include_eval and ev_thread_idx:
            with _optional_chat_store(chat_path) as cdb:
                if cdb is not None:
                    # PLAN  SELECT id FROM conversations WHERE <eval titles> -> SCAN conversations (5.8k rows, the chat store)
                    eval_convs = {r[0] for r in cdb.execute(f"SELECT id FROM conversations WHERE {EVAL_TITLE_SQL}")}
        if eval_convs is not None:
            # The eval harness runs as chat conversations (conv-NNNN, "[eval] ..."): 2026-10-24, 5,881 of the newest 6,000
            # events were theirs, so a ts-ordered window held 4 real threads. The newest REAL threads come first, then each
            # thread's own newest events (warm: 14 ms + 3 ms on the live store; cold 1.5 s).
            # PLAN  SELECT thread_id, MAX(ts) … GROUP BY thread_id -> SCAN memory_events USING COVERING INDEX
            #       idx_memory_events_thread_ts + TEMP B-TREE FOR ORDER BY (one entry per thread)
            newest = [r[0] for r in con.execute(
                "SELECT thread_id, MAX(ts) AS last FROM memory_events WHERE thread_id NOT LIKE 'eval-%' "
                "GROUP BY thread_id ORDER BY last DESC") if r[0] and r[0] not in eval_convs]
            ev_rows = []
            for t in newest[:threads * SNAPSHOT_THREAD_CANDIDATES]:
                if len(ev_rows) >= events:
                    break
                # PLAN  … WHERE thread_id = ? ORDER BY ts DESC LIMIT ? -> SEARCH … USING INDEX idx_memory_events_thread_ts
                ev_rows += con.execute(f"SELECT {pick_cols(ev_cols, ev_want)} FROM memory_events WHERE thread_id = ? "
                                       "ORDER BY ts DESC LIMIT ?", (t, SNAPSHOT_EVENTS_PER_THREAD)).fetchall()
        else:
            ev_rows = con.execute(f"SELECT {pick_cols(ev_cols, ev_want)} FROM memory_events {where} ORDER BY ts DESC LIMIT ?",
                                  (events,)).fetchall() if "memory_events" in have else []
        by_thread: dict[str, list] = {}
        for r in ev_rows:
            if r["thread_id"]:
                by_thread.setdefault(r["thread_id"], []).append(r)
        thread_ids = sorted(by_thread, key=lambda t: by_thread[t][0]["ts"], reverse=True)
        thread_ids = thread_ids[:threads if include_eval else threads * SNAPSHOT_THREAD_CANDIDATES]
        if ev_thread_idx:
            # PLAN  SELECT COUNT(*) FROM (SELECT DISTINCT thread_id FROM memory_events)
            #       -> SCAN memory_events USING COVERING INDEX <the thread_id index> (42k entries)
            counts["sessions"] = con.execute("SELECT COUNT(DISTINCT thread_id) FROM memory_events").fetchone()[0]
        else:
            counts["sessions"] = len(by_thread)
            warnings.append("sessions counts the threads of the newest events: memory_events(thread_id) is not indexed")
        lap("events")

        # ②b the sessions the page lists. The eval harness runs its tasks as chat conversations titled "[eval] ..." with
        # ids conv-NNNN: no thread-id prefix names them (2026-10-24: 46 of the 48 sessions of a live snapshot were eval
        # runs). So the chat-store TITLE decides, on the wider candidate set, BEFORE the cut to `threads`. Everything below
        # (events, trajectories, episodes, recalls) reads `thread_ids` only: a dropped thread leaves no trace in it.
        exits: dict[str, Any] = {}
        titles: dict[str, str] = {}
        if "caducean_session_exits" in have and thread_ids:
            # PLAN  … FROM caducean_session_exits WHERE session_id IN (…) LIMIT 2000
            #       -> SEARCH caducean_session_exits USING INDEX idx_se_session (session_id=?)
            for part in _chunks(thread_ids):
                exits.update({r[0]: r for r in con.execute(
                    f"SELECT session_id, natural_exit, drift, conversation_id FROM caducean_session_exits "
                    f"WHERE session_id IN ({_marks(len(part))}) LIMIT 2000", part)})
        with _optional_chat_store(chat_path) as cdb:
            if cdb is not None:
                ids = list(thread_ids) + [e[3] for e in exits.values() if e[3]]
                # PLAN  … FROM conversations WHERE id IN (…) LIMIT 4000
                #       -> SEARCH conversations USING INDEX sqlite_autoindex_conversations_1 (id=?)
                for part in _chunks(ids):
                    for r in cdb.execute(f"SELECT id, title FROM conversations WHERE id IN ({_marks(len(part))}) LIMIT 4000", part):
                        if r[1]:
                            titles[r[0]] = r[1]

        def title_of(t: str) -> Optional[str]:
            x = exits.get(t)
            return titles.get(t) or (titles.get(x[3]) if x and x[3] else None)

        if not include_eval:
            thread_ids = [t for t in thread_ids if not _is_eval_thread(t, title_of(t))][:threads]
        lap("session_titles")

        # ③ landmarks that are still live (absorbed ones were merged into a survivor)
        # PLAN  SELECT <cols> FROM mycelium_landmarks WHERE COALESCE(absorbed,0)=0 ORDER BY created_at DESC LIMIT 400
        #       -> SCAN mycelium_landmarks + TEMP B-TREE FOR ORDER BY (3.3k rows, small table)
        lm_want = ("landmark_id", "label", "task_class", "micro_abstract_text", "tier", "is_permanent", "evidence",
                   "activation_count", "contradictions", "last_activated", "last_verified", "created_at", "conversation_ref",
                   "traversal_sequence", "cumulative_score")
        lm_rows = con.execute(f"SELECT {pick_cols(lm_cols, lm_want)} FROM mycelium_landmarks {live_sql} "
                              f"ORDER BY created_at DESC LIMIT ?", (SNAPSHOT_LANDMARKS,)).fetchall() if lm_cols else []
        lm_ids = [r["landmark_id"] for r in lm_rows]
        lm_index = {lid: i for i, lid in enumerate(lm_ids)}
        lm_fams: dict[str, dict[str, int]] = {}
        out_events = []
        for t in thread_ids:
            for r in by_thread[t][:SNAPSHOT_EVENTS_PER_THREAD]:
                links, payload = jload(r["links"], {}), jload(r["payload"], {})
                # LANDMARK_* events name their landmark in the payload; RECALL_* events do not name one
                lid = ((links.get("landmark_id") or links.get("landmark")) if isinstance(links, dict) else None) or \
                      (payload.get("landmark") if isinstance(payload, dict) else None)
                if lid in lm_index:
                    fam = lm_fams.setdefault(lid, {})
                    fam[r["family"]] = fam.get(r["family"], 0) + 1
                out_events.append({"id": r["event_id"], "ts": r["ts"], "family": r["family"], "label": r["label"],
                                   "valence": r["valence"], "actor": r["actor"], "evidence": r["evidence"],
                                   "episode": r["episode_id"], "session": t, "domain": r["topic_domain"] or "general",
                                   "landmark": lid if lid in lm_index else None})
        # the steps of a claim: the nodes its traversal walked, in order, as {space, label}. ONE batched read of the
        # nodes of all claims together; an id the store no longer holds is skipped.
        # PLAN  SELECT node_id, space_id, label FROM mycelium_nodes WHERE node_id IN (…)
        #       -> SEARCH mycelium_nodes USING INDEX sqlite_autoindex_mycelium_nodes_1 (node_id=?)  (the primary key)
        claim_nodes = {r["landmark_id"]: [x for x in jload(r["traversal_sequence"], []) if isinstance(x, str)][:SNAPSHOT_CLAIM_STEPS]
                       for r in lm_rows}
        node_of: dict[str, tuple] = {}
        if "mycelium_nodes" in have:
            for part in _chunks(sorted({x for seq in claim_nodes.values() for x in seq})):
                node_of.update({r[0]: (r[1], r[2]) for r in con.execute(
                    f"SELECT node_id, space_id, label FROM mycelium_nodes WHERE node_id IN ({_marks(len(part))})", part)})
        # decay (Kyudo): the same law and active-day clock the search ranks with; computed, never written back.
        # PLAN  SELECT DISTINCT substr(timestamp,1,10) FROM episodes WHERE timestamp >= ? -> COVERING INDEX idx_ep_timestamp
        law = _search_law() if lm_rows else None
        clock = law["clock"](con, 0.0) if law else None
        landmarks = []
        for r in lm_rows:
            ev: list[dict] = []
            kinds: dict[str, int] = {}
            full = [e for e in jload(r["evidence"], []) if isinstance(e, dict)]
            touch = max([ts_of(r[c]) or 0.0 for c in ("created_at", "last_activated", "last_verified")] +
                        [ts_of(e.get("at")) or 0.0 for e in full])
            _, fading = _claim_alive(law, r["cumulative_score"] or 0.0, bool(r["is_permanent"]),
                                     clock.days_since(touch) if touch else 0.0,
                                     (r["activation_count"] or 0) + law["independent"](full))
            for e in full[-400:]:
                k = LM_EVIDENCE.get(str(e.get("kind")), "claim")
                kinds[k] = kinds.get(k, 0) + 1
                if kinds[k] <= 4:  # the page shows counts; keep a few dated entries per kind
                    ev.append({"kind": k, "at": ts_of(e.get("at")), "session": e.get("session")})
            text = r["micro_abstract_text"] or (r["label"] or "").replace("_", " ")
            ranked = sorted(lm_fams.get(r["landmark_id"], {}).items(), key=lambda kv: -kv[1])[:3]   # stable: ties keep event order
            fams = [FAMILIES.index(f) for f, _ in ranked if f in FAMILIES] or [3, 6]
            landmarks.append({"id": r["landmark_id"], "claim": text, "cls": r["task_class"] or "other",
                              "tier": r["tier"] or "candidate", "permanent": bool(r["is_permanent"]), "evidence": ev,
                              "evidence_counts": dict(kinds), "activations": r["activation_count"] or 0,
                              "contradictions": r["contradictions"] or 0, "fading": fading,
                              "last_activated": ts_of(r["last_activated"]), "last_verified": ts_of(r["last_verified"]),
                              "born": ts_of(r["created_at"]), "session": r["conversation_ref"], "fams": fams,
                              "steps": [{"space": node_of[x][0], "label": node_of[x][1]}
                                        for x in claim_nodes[r["landmark_id"]] if x in node_of],
                              "domain": "general"})  # landmarks carry no domain column yet
        if not any(r["micro_abstract_text"] for r in lm_rows):
            warnings.append("no live landmark has micro_abstract_text")
        lap("landmarks")
        # PLAN  SELECT … FROM mycelium_landmark_edges WHERE from_landmark_id IN (…) AND to_landmark_id IN (…) LIMIT 3000
        #       -> SEARCH mycelium_landmark_edges USING INDEX idx_landmark_edges_from (from_landmark_id=?) (466 rows, small)
        edges = []
        if lm_ids and "mycelium_landmark_edges" in have:
            ph = _marks(len(lm_ids))
            edges = [{"id": r[6], "a": lm_index[r[0]], "b": lm_index[r[1]], "score": r[2], "traversals": r[3], "hits": r[4],
                      "misses": r[5], "last": ts_of(r[7])}
                     for r in con.execute(
                         f"SELECT from_landmark_id, to_landmark_id, score, traversal_count, hit_count, miss_count, edge_id, "
                         f"last_traversed FROM mycelium_landmark_edges "
                         f"WHERE from_landmark_id IN ({ph}) AND to_landmark_id IN ({ph}) LIMIT ?",
                         lm_ids + lm_ids + [SNAPSHOT_EDGES])]

        # Kyudo trust channel of a landmark: the highest channel that ever observed it, read from the episode index
        # (nodes.source_channel is the same value for a coordinate node). NULL on every row = legacy internal; the page
        # then draws the plain membrane.
        ei_cols = table_cols(con, "mycelium_episode_index")
        lap("landmark_edges")
        available["landmark_channel"] = "source_channel" in ei_cols and "landmark_id" in ei_cols
        if available["landmark_channel"] and lm_ids:
            chan = _channels(con, lm_ids)   # PLAN  SEARCH mycelium_episode_index USING INDEX idx_epindex_landmark
            for lm in landmarks:
                lm["channel"] = chan.get(lm["id"])

        lap("landmark_channels")
        # sectors: territories read from the registry when the tables exist (a newer build creates them); the page falls
        # back to the topic-domain territories otherwise. Roots are big, children nested.
        sectors: list[dict] = []
        sec_cols = table_cols(con, "mycelium_sectors")
        ls_cols = table_cols(con, "mycelium_landmark_sectors")
        available["sectors"] = bool(sec_cols)
        available["landmark_sectors"] = bool(ls_cols)
        if "sector_key" in sec_cols:
            # the live table names its last change updated_at (last_activity was the exporter's guess): either one
            want = ("sector_key", "parent_key", "label", "status", "members", "outside_evidence", "last_activity", "updated_at")
            # PLAN  … FROM mycelium_sectors WHERE COALESCE(status,'proven') != 'dissolved' LIMIT 200 -> SCAN (19 rows)
            sectors = [{"key": r["sector_key"], "parent": r["parent_key"] or None,
                        "label": clip(r["label"], 60) or r["sector_key"].rsplit("/", 1)[-1],
                        "status": r["status"] or "proven", "members": r["members"] or 0,
                        "evidence": r["outside_evidence"] or 0, "last": ts_of(r["last_activity"] or r["updated_at"])}
                       for r in con.execute(f"SELECT {pick_cols(sec_cols, want)} FROM mycelium_sectors "
                                            f"WHERE COALESCE(status, 'proven') != 'dissolved' LIMIT 200")]
        if sectors and {"landmark_id", "sector_key"} <= ls_cols and lm_ids:
            best = _best_sector(con, lm_ids)   # PLAN  SEARCH mycelium_landmark_sectors USING COVERING INDEX (landmark_id=?)
            parent = {s["key"]: s["parent"] for s in sectors}
            for lm in landmarks:
                if lm["id"] in best:
                    key = best[lm["id"]]
                    root, hops = key, 0
                    while parent.get(root) and hops < 6:
                        root, hops = parent[root], hops + 1
                    lm["sector"], lm["domain"] = key, root

        lap("sectors")
        # ④ sessions: one per thread, shaped by its Caducean trajectory
        tph = _marks(len(thread_ids))
        traj: dict[str, list] = {}
        if "caducean_trajectories" in have and thread_ids:
            # PLAN  … FROM caducean_trajectories WHERE session_id IN (…) ORDER BY session_id, step_num LIMIT 6000
            #       -> SEARCH caducean_trajectories USING INDEX idx_ct_session (session_id=?) + TEMP B-TREE FOR ORDER BY
            for r in con.execute(f"SELECT session_id, x, y, xi, u FROM caducean_trajectories WHERE session_id IN ({tph}) "
                                 f"ORDER BY session_id, step_num LIMIT ?", thread_ids + [SNAPSHOT_TRAJECTORY_ROWS]):
                steps = traj.setdefault(r[0], [])
                if len(steps) < SNAPSHOT_TRAJECTORY_STEPS:
                    steps.append({"x": r[1] or 0.0, "y": r[2] or 0.0, "xi": r[3] or 0.0, "u": r[4] or 0.0})
        lap("trajectories")
        conv_of = {t: (exits[t][3] if t in exits and exits[t][3] else t) for t in thread_ids}
        messages: dict[str, list] = {}
        children: dict[str, list] = {}
        thread_of: dict[str, str] = {}
        tags_of: dict[str, list] = {}   # a strand's tags (conversations.tags): the corridor rail shows them (UX-PLAN 4.4)
        helpers: dict[str, dict] = {}   # a helper strand: the strand it reports to and the moments it reported (UX-PLAN 4.4)
        with _optional_chat_store(chat_path) as cdb:
            if cdb is not None:
                has_rt = "reports_to" in table_cols(cdb, "conversations")
                # the conversation strands of the tunnel: its messages (a short preview, never the whole text) and the
                # strands forked from it (parent_id)
                for t in thread_ids:
                    cid = conv_of[t]
                    # PLAN  … FROM messages WHERE conversation_id = ? ORDER BY timestamp LIMIT 80
                    #       -> SEARCH messages USING INDEX idx_messages_conv (conversation_id=?) + TEMP B-TREE
                    for r in cdb.execute("SELECT role, timestamp, substr(text, 1, ?), length(text), source FROM messages "
                                         "WHERE conversation_id = ? ORDER BY timestamp LIMIT ?",
                                         (PREVIEW_MESSAGE, cid, MESSAGES_CAP)):
                        src = r[4] or ""
                        messages.setdefault(t, []).append({"role": "user" if r[0] == "user" else "iris", "ts": ts_of(r[1]),
                                                           "text": r[2], "len": r[3] or 0,
                                                           "report": src[len(REPORT_SOURCE):] if src.startswith(REPORT_SOURCE) else None})
                    # a helper: the strand it reports to, and every report it posted there (conversation_store.report_back)
                    # PLAN  … FROM conversations WHERE id = ? -> SEARCH conversations USING INDEX sqlite_autoindex_conversations_1
                    # PLAN  … FROM messages WHERE conversation_id = ? AND source = ? -> SEARCH messages USING INDEX idx_messages_conv
                    row = cdb.execute("SELECT reports_to, parent_id, tags FROM conversations WHERE id = ?", (cid,)).fetchone()                         if has_rt else None
                    tags_of[t] = [x for x in jload(row[2], []) if isinstance(x, str)][:8] if row and row[2] else []
                    if row and row[1]:
                        thread_of[t] = row[1]   # the thread (root conversation) a strand belongs to (UX-PLAN 4.3 braids)
                    if row and row[0]:
                        helpers[t] = {"reports_to": row[0], "reports": [ts_of(x[0]) for x in cdb.execute(
                            "SELECT timestamp FROM messages WHERE conversation_id = ? AND source = ? ORDER BY timestamp",
                            (row[0], REPORT_SOURCE + cid))]}
                    # PLAN  … FROM conversations WHERE parent_id = ? LIMIT 6 -> SEARCH … USING INDEX idx_conversations_parent
                    for r in cdb.execute("SELECT id, title, created_at, updated_at FROM conversations WHERE parent_id = ? "
                                         "LIMIT 6", (cid,)):
                        children.setdefault(t, []).append({"id": r[0], "title": r[1], "started": ts_of(r[2]),
                                                           "ended": ts_of(r[3])})
            else:
                warnings.append("data/conversations.db not found: session titles fall back to thread ids")
        # a strand chat deleted is a GHOST: its tombstone (STRAND_DELETED, written by conversation_store.delete) keeps
        # its name, so the timeline still says what it was (MEMORY-SURFACE-BUILD section 7, phase 3)
        # PLAN  … FROM memory_events WHERE family = 'memory' AND label = 'STRAND_DELETED' AND thread_id IN (…) LIMIT ?
        #       -> SEARCH memory_events USING INDEX idx_memory_events_label (family=? AND label=?)
        ghosts: dict[str, str] = {}
        if thread_ids and has_index_on(con, "memory_events", "family"):
            for part in _chunks([t for t in thread_ids if not title_of(t)]):
                for r in con.execute(f"SELECT thread_id, payload FROM memory_events WHERE family = 'memory' AND "
                                     f"label = 'STRAND_DELETED' AND thread_id IN ({_marks(len(part))}) LIMIT 2000", part):
                    pl = jload(r["payload"], {})
                    ghosts[r["thread_id"]] = (pl.get("title") if isinstance(pl, dict) else None) or ""
        lap("chat_store")
        sessions = []
        now = time.time()
        for t in thread_ids:
            rows = by_thread[t]
            x = exits.get(t)
            chat_title = title_of(t)
            title = chat_title or ghosts.get(t) or pretty_thread(t)
            started, ended = rows[-1]["ts"], rows[0]["ts"]
            live = now - ended < 600
            sessions.append({"id": t, "objective": title, "started": started, "ended": None if live else ended,
                             "exit": "live" if live else ("drift" if x and x[2] and not x[1] else "natural"),
                             "traj": traj.get(t, []), "eval": _is_eval_thread(t, chat_title), "episodes": [],
                             "messages": [m for m in messages.get(t, []) if m["ts"]], "strands": children.get(t, []),
                             "thread": thread_of.get(t, conv_of.get(t, t)), "tags": tags_of.get(t, []), "reports_to": helpers.get(t, {}).get("reports_to"), "reports": helpers.get(t, {}).get("reports", []),
                             "ghost": t in ghosts})

        lap("sessions")
        # ⑤ episodes (task runs)
        episodes = []
        sess_ids = set(thread_ids)
        if "episodes" in have:
            # PLAN  … FROM episodes ORDER BY timestamp DESC LIMIT 300 -> SCAN episodes USING INDEX idx_ep_timestamp
            for r in con.execute("SELECT id, session_id, task_summary, outcome_type, outcome_score, failure_reason, "
                                 "user_corrected, user_confirmed, duration_ms, tool_sequence, timestamp FROM episodes "
                                 "ORDER BY timestamp DESC LIMIT ?", (SNAPSHOT_EPISODES,)):
                tools = [s.get("tool") for s in jload(r["tool_sequence"], []) if isinstance(s, dict) and s.get("tool")][:12]
                episodes.append({"id": r["id"], "session": r["session_id"], "summary": (r["task_summary"] or "")[:160],
                                 "outcome": r["outcome_type"] or "partial", "score": r["outcome_score"] or 0.0,
                                 "failure_reason": r["failure_reason"], "corrected": bool(r["user_corrected"]),
                                 "confirmed": bool(r["user_confirmed"]), "duration": (r["duration_ms"] or 0) / 1000.0,
                                 "tools": tools, "ts": ts_of(r["timestamp"])})
        for s in sessions:
            s["episodes"] = [e["id"] for e in episodes if e["session"] == s["id"]]
        episodes = [e for e in episodes if e["session"] in sess_ids]

        lap("episodes")
        # ⑥ things IRIS made (names and kinds only; no content, no blobs)
        artifacts = []
        if "document_data" in have:
            # PLAN  … FROM document_data ORDER BY created_at DESC LIMIT 80 -> SCAN document_data USING INDEX idx_document_data_created
            for i, r in enumerate(con.execute(
                    "SELECT document_id, conversation_id, fmt, kind, title, summary, created_at, capture_path "
                    "FROM document_data ORDER BY created_at DESC LIMIT ?", (SNAPSHOT_ARTIFACTS,))):
                kind = "screen" if r["capture_path"] else DOC_KIND.get(r["kind"] or "", DOC_KIND.get(r["fmt"] or "", "doc"))
                name = r["title"] or (r["summary"] or "")[:48] or f"{r['fmt'] or 'document'} · {str(r['document_id'])[:8]}"
                # layers: format comes from kind; the folder is where it was captured, else what it is
                folder = (Path(r["capture_path"]).parent.name if r["capture_path"] else None) or \
                    DOC_FOLDER.get(r["fmt"] or "", r["fmt"] or "unsorted")
                artifacts.append({"id": r["document_id"], "kind": kind, "name": name, "folder": folder,
                                  "session": r["conversation_id"], "ts": ts_of(r["created_at"]), "weight": 1.0, "seed": i + 1})

        lap("artifacts")
        # ⑦ pins (MEMORY-INTERFACE Part II 13.3): explicit memory, held not earned. 0 rows today: the page then shows
        # none. "held in context" has no stored flag yet; the 'held' / 'context' tag stands in.
        pins: list[dict] = []
        pin_cols = table_cols(con, "mycelium_pins")
        available["pins"] = bool(pin_cols)
        if pin_cols:
            want = ("pin_id", "title", "pin_type", "tags", "file_refs", "image_refs", "url_refs", "project_id",
                    "created_at", "is_permanent")
            # PLAN  … FROM mycelium_pins ORDER BY created_at DESC LIMIT 200 -> SCAN mycelium_pins + TEMP B-TREE
            #       (an explicit-memory table: 0 rows today, tens by design)
            prow = con.execute(f"SELECT {pick_cols(pin_cols, want)} FROM mycelium_pins ORDER BY created_at DESC LIMIT ?",
                               (SNAPSHOT_PINS,)).fetchall()
            pids = [r["pin_id"] for r in prow]
            links_of: dict[str, list] = {}
            if pids and "mycelium_pin_links" in have:
                # mycelium_pin_links (21k rows) has no index: the lookup would SCAN it, so it runs only when the
                # store indexes both ends (has_index_on); otherwise pin links count the refs of the pin row only.
                if has_index_on(con, "mycelium_pin_links", "source_id") and has_index_on(con, "mycelium_pin_links", "target_id"):
                    pph = _marks(len(pids))
                    for r in con.execute(
                            f"SELECT source_type, source_id, target_type, target_id, relationship FROM mycelium_pin_links "
                            f"WHERE (source_type = 'pin' AND source_id IN ({pph})) OR (target_type = 'pin' AND target_id IN ({pph})) "
                            f"LIMIT ?", pids + pids + [SNAPSHOT_PIN_LINKS]):
                        mine, other = (r[1], (r[2], r[3])) if r[0] == "pin" else (r[3], (r[0], r[1]))
                        links_of.setdefault(mine, []).append({"t": other[0], "id": other[1], "rel": r[4]})
                else:
                    warnings.append("pin links not read: mycelium_pin_links is not indexed")
            known = set(DOM_KEYS) | {s["key"] for s in sectors}
            for r in prow:
                tags = [str(t) for t in jload(r["tags"], []) if isinstance(t, (str, int))][:8]
                refs = links_of.get(r["pin_id"], [])
                nfile, nimg, nurl = (len(jload(r[k], [])) for k in ("file_refs", "image_refs", "url_refs"))
                dom = next((t for t in tags if t in known), None) or (r["project_id"] if r["project_id"] in known else None)
                pins.append({"id": r["pin_id"], "title": clip(r["title"], 80), "type": r["pin_type"] or "note",
                             "created": ts_of(r["created_at"]), "permanent": bool(r["is_permanent"]),
                             "held": bool({"held", "context"} & set(tags)), "links": len(refs) + nfile + nimg + nurl,
                             "refs": refs[:12], "tags": tags[:6], "domain": dom})

        lap("pins")
        # ⑧ coordinate spaces (registry) and the nodes in them: layers, with trust channel and confidence
        spaces: list[dict] = []
        nodes: list[dict] = []
        node_edges: list[dict] = []
        sp_cols = table_cols(con, "mycelium_spaces")
        available["spaces"] = bool(sp_cols)
        if sp_cols:
            want = ("space_id", "description", "active", "write_lock", "render_order", "position")
            # PLAN  … FROM mycelium_spaces LIMIT 40 -> SCAN mycelium_spaces (a registry)
            spaces = [{"id": r["space_id"], "description": clip(r["description"], 120),
                       "active": bool(r["active"] if r["active"] is not None else 1), "write_lock": r["write_lock"],
                       "render_order": r["render_order"], "position": r["position"]}
                      for r in con.execute(f"SELECT {pick_cols(sp_cols, want)} FROM mycelium_spaces LIMIT 40")]
        nd_cols = table_cols(con, "mycelium_nodes")
        available["node_channel"] = "source_channel" in nd_cols
        if nd_cols:
            want = ("node_id", "space_id", "label", "confidence", "source_channel", "created_at", "updated_at", "access_count")
            # PLAN  … FROM mycelium_nodes ORDER BY updated_at DESC LIMIT 600 -> SCAN mycelium_nodes + TEMP B-TREE (139 rows)
            nrows = con.execute(f"SELECT {pick_cols(nd_cols, want)} FROM mycelium_nodes ORDER BY updated_at DESC LIMIT ?",
                                (SNAPSHOT_NODES,)).fetchall()
            nidx = {r["node_id"]: i for i, r in enumerate(nrows)}
            nodes = [{"id": r["node_id"], "space": r["space_id"], "label": clip(r["label"], 48),
                      "conf": r["confidence"] if r["confidence"] is not None else 0.5, "chan": r["source_channel"],
                      "born": ts_of(r["created_at"]), "used": r["access_count"] or 0} for r in nrows]
            ne_cols = table_cols(con, "mycelium_edges")
            if ne_cols and nidx:
                want = ("from_node_id", "to_node_id", "score", "traversal_count", "observation_count", "last_traversed")
                # PLAN  … FROM mycelium_edges LIMIT 4000 -> SCAN mycelium_edges (241 rows; bounded by the LIMIT)
                for r in con.execute(f"SELECT {pick_cols(ne_cols, want)} FROM mycelium_edges LIMIT ?", (SNAPSHOT_NODE_EDGES,)):
                    if r["from_node_id"] in nidx and r["to_node_id"] in nidx:
                        node_edges.append({"a": nidx[r["from_node_id"]], "b": nidx[r["to_node_id"]], "score": r["score"] or 0.0,
                                           "traversals": r["traversal_count"] or 0, "observations": r["observation_count"] or 0,
                                           "last": ts_of(r["last_traversed"])})

        lap("nodes")
        # ⑨ immune response (Kyudo): the durable quorum log. A live row (shadow=0) is a signal that counted; shadow=1 rows
        # are measured only; quorum_reorganization_reset is the region relaxing. The landmark a signal names (activation
        # anomaly) or the session it came from tells the page which territory it touched.
        quorum: list[dict] = []
        qc = table_cols(con, "mycelium_quorum_log")
        available["quorum"] = bool(qc)
        if qc:
            want = ("ts", "session_id", "signal_type", "weight", "threat_after", "shadow", "detail")
            # PLAN  … FROM mycelium_quorum_log ORDER BY ts DESC LIMIT 80 -> SCAN mycelium_quorum_log USING INDEX idx_quorum_log_ts
            for r in con.execute(f"SELECT {pick_cols(qc, want)} FROM mycelium_quorum_log ORDER BY ts DESC LIMIT ?",
                                 (SNAPSHOT_QUORUM,)):
                m = re.search(r"landmark=(\S+)", r["detail"] or "")
                quorum.append({"ts": r["ts"], "session": r["session_id"] or None, "signal": r["signal_type"],
                               "weight": r["weight"] or 0.0, "threat": r["threat_after"], "shadow": bool(r["shadow"]),
                               "landmark": m.group(1) if m else None})
            quorum.reverse()

        lap("quorum")
        # ghosts (UX-PLAN 7.5): claims the integrity pass dissolved in the last GHOST_DAYS, newest first, with the reason
        # PLAN  SELECT ts, payload FROM memory_events WHERE family='memory' AND label='LANDMARK_DISSOLVED' AND ts > ? ORDER BY ts DESC
        #       -> SEARCH memory_events USING INDEX idx_memory_events_label_ts (family=? AND label=? AND ts>?)
        ghosts: list[dict] = []
        if "memory_events" in have and lm_cols:
            gone: dict[str, tuple] = {}
            for ts, payload in con.execute("SELECT ts, payload FROM memory_events WHERE family = 'memory' "
                                           "AND label = 'LANDMARK_DISSOLVED' AND ts > ? ORDER BY ts DESC LIMIT ?",
                                           (time.time() - GHOST_DAYS * 86400, SNAPSHOT_GHOSTS)):
                p = jload(payload, {})
                lid = p.get("landmark") if isinstance(p, dict) else None
                if isinstance(lid, str) and lid not in gone:
                    gone[lid] = (ts, str(p.get("reason") or ""))
            if gone:
                # PLAN  SELECT … FROM mycelium_landmarks WHERE landmark_id IN (…) -> SEARCH USING INDEX sqlite_autoindex_…_1
                g_rows = {r["landmark_id"]: r for r in con.execute(
                    f"SELECT {pick_cols(lm_cols, ('landmark_id', 'label', 'micro_abstract_text', 'conversation_ref', 'created_at', 'last_activated', 'last_verified'))} "
                    f"FROM mycelium_landmarks WHERE landmark_id IN ({_marks(len(gone))})", list(gone))}
                for lid, (ts, reason) in gone.items():
                    r = g_rows.get(lid)
                    if r is None:
                        continue
                    touch = max(ts_of(r[c]) or 0.0 for c in ("created_at", "last_activated", "last_verified"))
                    idle = int(round(clock.days_since(touch))) if clock is not None and touch else None
                    ghosts.append({"id": lid, "claim": r["micro_abstract_text"] or (r["label"] or "").replace("_", " "),
                                   "session": r["conversation_ref"], "dissolved": ts, "reason": reason,
                                   "fate": _dissolved_fate(reason, idle), "domain": "general"})
        lap("ghosts")
        # ⑩ recalls: what the memory gave the agent on each step of a turn (RECALL_DELIVERED, typed by
        # agent_kernel._der_recall_delivered) and whether it helped (RECALL_HELPED / RECALL_MISLED, same recall_trace_id).
        # refs are DER chain ids: resolved to the prior step they name (its thread, what it did, its tool, its result) - a
        # short insight only, never the content.
        traces: dict[str, dict] = {}
        if "memory_events" in have:
            rec_where = "" if include_eval else "AND thread_id NOT LIKE 'eval-%'"
            # 2026-10-26: this read took EVERY recall row (12.4k) and sorted it to keep 60 turns - 156 s cold on the hard
            # disk after a restart. Now the newest deliveries stream in time order and the read stops once the
            # SNAPSHOT_RECALL_TURNS newest turns are complete; the outcomes are read for those turns only.
            # PLAN  … WHERE family = 'memory' AND label IN ('RECALL_DELIVERED') [AND …] ORDER BY ts DESC LIMIT ?
            #       -> SEARCH memory_events USING INDEX idx_memory_events_label_ts (family=? AND label=?) - no temp sort
            #       (a one-value IN plans as equality)
            seen_turns: set = set()
            for r in con.execute("SELECT ts, label, episode_id, step_index, thread_id, links, payload FROM memory_events "
                                 f"WHERE family = 'memory' AND label IN ('RECALL_DELIVERED') {rec_where} "
                                 "ORDER BY ts DESC LIMIT ?", (SNAPSHOT_RECALL_ROWS,)):
                ep = r["episode_id"]
                if ep and ep not in seen_turns:
                    if len(seen_turns) >= SNAPSHOT_RECALL_TURNS:
                        break
                    seen_turns.add(ep)
                tid = (jload(r["links"], {}) or {}).get("recall_trace_id")
                if not tid:
                    continue
                p = jload(r["payload"], {}) or {}
                traces.setdefault(tid, {"outcome": None}).update(
                    turn=ep, session=r["thread_id"], step=r["step_index"], ts=r["ts"],
                    source=p.get("source") or "neighbors", refs=[x for x in (p.get("refs") or []) if x][:5])
            # An outcome row carries its delivery's turn (checked live: 1,473 of 1,473 traces).
            # PLAN  … WHERE episode_id IN (…) AND family = 'memory' AND label IN (…)
            #       -> SEARCH memory_events USING INDEX idx_memory_events_episode (episode_id=?)
            turns = sorted(t for t in seen_turns if t)
            for i in range(0, len(turns), 500):
                part = turns[i:i + 500]
                for r in con.execute(f"SELECT label, links FROM memory_events WHERE episode_id IN ({_marks(len(part))}) "
                                     f"AND family = 'memory' AND label IN ({_marks(len(RECALL_LABELS) - 1)})",
                                     part + list(RECALL_LABELS[1:])):
                    tid = (jload(r["links"], {}) or {}).get("recall_trace_id")
                    if tid in traces:
                        traces[tid]["outcome"] = "helped" if r["label"] == "RECALL_HELPED" else "misled"
        by_turn: dict[str, list] = {}
        for t in traces.values():
            if t.get("turn"):
                by_turn.setdefault(t["turn"], []).append(t)
        turn_ids = sorted(by_turn, key=lambda k: max(x["ts"] for x in by_turn[k]), reverse=True)[:SNAPSHOT_RECALL_TURNS]
        lap("recall_events")
        chain_ids = sorted({c for k in turn_ids for t in by_turn[k] for c in t["refs"]})
        chain: dict[str, dict] = {}
        if chain_ids and has_index_on(con, "memory_chain", "chain_id"):
            # PLAN  … FROM memory_chain WHERE chain_id IN (…) GROUP BY chain_id LIMIT 400
            #       -> SEARCH memory_chain USING INDEX <the chain_id index> (chain_id=?)
            for part in _chunks(chain_ids):
                for r in con.execute(CHAIN_REFS_SQL.format(marks=_marks(len(part))), part + [len(part)]):
                    chain[r[0]] = {"session": r[1], "did": (r[2] or "")[:PREVIEW_INSIGHT], "result": r[3] or None,
                                   "tool": (r[4] or "").split(":")[0] or None, "ts": ts_of(r[5]), "kind": r[6] or "step"}
        elif chain_ids:
            warnings.append("recall refs not resolved: memory_chain(chain_id) is not indexed")
        recalls = []
        for k in turn_ids:
            ts_ = sorted(by_turn[k], key=lambda x: x["ts"])
            recalls.append({"turn": k, "session": ts_[0]["session"], "ts": ts_[0]["ts"],
                            "steps": [{"step": t["step"], "ts": t["ts"], "source": t["source"], "outcome": t["outcome"],
                                       "refs": [chain.get(c, {"session": None, "did": "", "result": None, "tool": None,
                                                              "ts": None, "kind": "step"}) for c in t["refs"]]}
                                      for t in ts_]})
        counts["recall_turns"] = len(by_turn)
        lap("recalls")

    oracle = _snap_oracle(warnings)
    lap("oracle")
    logger.info("[memory_snapshot] ref=%s total_ms=%d threads=%d events=%d eval=%s parts_ms=%s", ref,
                (time.perf_counter() - t_start) * 1000, threads, events, include_eval,
                " ".join(f"{k}={v * 1000:.0f}" for k, v in parts.items()))
    return {"meta": {"source": "data/memory.db (read-only snapshot)", "generated": time.time(), "counts": counts,
                     "eval_share": eval_share, "warnings": warnings, "available": available,
                     "last_integrity_pass": integrity},
            "famCounts": fam_counts, "domCounts": dom_counts, "sessions": sessions, "events": out_events,
            "landmarks": landmarks, "edges": edges, "episodes": episodes, "artifacts": artifacts,
            "oracle": oracle, "mind": [], "sectors": sectors, "pins": pins, "spaces": spaces,
            "nodes": nodes, "nodeEdges": node_edges, "quorum": quorum, "recalls": recalls, "ghosts": ghosts}









# ── search: GET /api/memory/search ───────────────────────────────────────────────────────────────
# SURFACE-BUILD section 3. Not a web search: the answer to "what does the memory hold about this, and how
# much does it hold it". TEXT ONLY. It reads, it never writes: no activation, no RECALL event, no row (a search is
# not a recall - contract-tested by the store's logical digest). One bounded statement per kind on a read-only
# connection; the match is done in Python (accent-insensitive, which SQL LIKE cannot do), the rank by the memory's law.
#
# BOUNDS. The small tables (claims, nodes, pins, artifacts, conversations, tombstones) are read whole under a cap.
# The big ones are read as a WINDOW: the newest N rows by the ts / created_at index (memory_chain 42k, memory_events 42k).
# The response says so per kind (searched[kind]). No index and no FTS table is added: if the p95 budget fails, STOP.
SEARCH_KINDS = ("claim", "strand", "pin", "turn", "artifact", "node", "step", "moment")   # also the display order
SEARCH_LIMIT_DEFAULT = 40
SEARCH_LIMIT_MAX = 100
SEARCH_PER_KIND = 8              # results of one kind shown before "more" (kinds=<one kind> returns up to `limit`)
SEARCH_QUERY_MAX = 300           # characters of q
SEARCH_TERMS_MAX = 8             # words + phrases; the rest are reported in parse.ignored
SEARCH_WINDOW_STEPS = 6000       # newest rows of memory_chain read per query
SEARCH_WINDOW_MOMENTS = 6000     # newest rows of memory_events read per query
SEARCH_WINDOW_TURNS = 5000       # newest episodes read per query (464 today: read whole)
SEARCH_WHOLE_CAP = 20000         # rows of a small table read per query (claims 3.3k and growing: Kyudo keeps absorbed rows)
SEARCH_TOMBSTONES = 2000
SEARCH_ROW_TEXT = 400            # characters of insight / result read per step
SEARCH_TITLE_MAX = 140
SEARCH_SNIPPET_MAX = 160

# kind weight: the memory's own truths first, the raw traffic last
KIND_WEIGHT = {"claim": 1.0, "pin": 0.95, "strand": 0.85, "turn": 0.7, "artifact": 0.7, "node": 0.5, "step": 0.45, "moment": 0.4}
KIND_WORD = {"claim": "a claim", "strand": "a conversation", "pin": "a pin", "turn": "a task", "artifact": "something IRIS made",
             "node": "a point on the map", "step": "a step IRIS took", "moment": "a moment"}
# strength = alive x (0.4 + 0.6 x proven) x (1 + 0.25 x used) x trust x mine
ALIVE_FLOOR = 0.05
PROVEN_BASE, PROVEN_SPAN = 0.4, 0.6
USED_WEIGHT, USED_SATURATION = 0.25, 50      # used = log(1 + n) / log(1 + 50), at most 1
MINE_BOOST = 1.5                              # your word: user evidence, a pin, a pinned conversation
NEUTRAL_PROVEN = 0.5                          # a kind with no evidence of its own (pin, artifact, strand, node, step)
CANDIDATE_FACTOR = 0.8                        # a learning claim's evidence counts 0.8 of a proven claim's
CLEANED_FACTOR = 0.1                          # the rank shown for a cleaned claim; the sort also puts it after every live one
GHOST_STRENGTH = 0.5
FADING_BELOW = 0.85                           # a claim is "fading" when its decayed score is under 0.85 of the stored one

# the evidence ladder (index.html EVID / EVID_WORD): user > recurrence/corroboration > test/completion > verifier > claim > none
EVIDENCE_LADDER = {"user": 1.0, "recurrence": 0.86, "corroboration": 0.86, "test": 0.72, "completion": 0.72,
                   "verifier": 0.45, "claim": 0.28, "none": 0.12}
EVIDENCE_WORD = {"user": "you confirmed it", "test": "a test passed", "completion": "the task finished",
                 "recurrence": "it held up again", "corroboration": "an independent source agreed",
                 "verifier": "the reviewer checked it", "claim": "IRIS reported it", "none": "unconfirmed"}
# landmark evidence is written as 'user_confirm' (landmark.OUTSIDE_EVIDENCE); the exporter's LM_EVIDENCE table lacks it
SEARCH_EVIDENCE = {**LM_EVIDENCE, "user_confirm": "user"}
# from:<word> -> the closed evidence alphabet
FROM_WORDS = {"you": ("user",), "test": ("test",), "finished": ("completion",), "held-up": ("recurrence", "corroboration"),
              "reviewer": ("verifier",), "iris": ("claim",)}
# the plain words of the surface (index.html / lib/memory/scene/engine.ts READ, FAM, CLUSTER_WORD, SPACE_WORD, DOM_WORD)
FAMILY_WORD = {"intent": "goals", "control": "plans", "problem": "problems", "knowledge": "knowledge", "feedback": "your feedback",
               "delivery": "deliveries", "memory": "remembering", "safety": "safety", "environment": "the world"}
EVENT_READ = {
    "GOAL_SET": "you set a goal", "GOAL_REFINED": "the goal got sharper", "CLARIFY_ASKED": "IRIS asked what you meant",
    "CLARIFY_ANSWERED": "you clarified", "PREFERENCE_STATED": "you said what you prefer", "GOAL_ABANDONED": "a goal was dropped",
    "PLAN_MADE": "made a plan", "REPLAN": "changed the plan", "PIVOT": "changed direction",
    "SPLIT": "split the work into parallel paths", "DELEGATED": "handed work to a helper", "ESCALATED": "asked for help",
    "HALTED": "stopped on purpose", "BUDGET_HIT": "ran out of budget", "OBSTACLE": "hit an obstacle", "BUG": "found a bug",
    "ATTEMPT": "tried a fix", "DEAD_END": "reached a dead end", "RESOLUTION": "found a way through", "FIX": "wrote a fix",
    "VERIFIED_RESOLUTION": "the way through held", "VERIFIED_FIX": "the fix passed its test", "OBSERVED": "noticed something",
    "CLAIM_CORROBORATED": "a second source agreed", "CLAIM_UPDATED": "updated a belief",
    "CLAIM_CONTRADICTED": "a belief was contradicted", "SOURCE_UNRELIABLE": "a source proved unreliable",
    "BELIEF_STALE": "a belief went stale", "CONFIRMATION": "you confirmed", "CORRECTION": "you corrected IRIS",
    "APPROVAL": "you approved", "DENIAL": "you said no", "NO_RESPONSE": "no reply came", "ANSWER_GIVEN": "answered you",
    "ARTIFACT_PRODUCED": "made something", "NARRATED": "spoke an update", "CARD_SHOWN": "showed you a card",
    "RECALL_DELIVERED": "remembered something", "RECALL_USED": "used what it remembered",
    "RECALL_HELPED": "remembering this helped", "RECALL_MISLED": "remembering this misled",
    "RECALL_MISSED": "forgot something it knew", "APERTURE_DROPPED": "let a memory leave its mind",
    "OFFLOADED": "set a thought aside", "RESTRETCHED": "brought a thought back",
    "PREMATURE_EVICTION": "let a thought go too early", "LESSON": "learned a lesson",
    "LANDMARK_PROMOTED": "IRIS is now sure about this", "LANDMARK_STALE": "a certainty went stale",
    "LANDMARK_DEMOTED": "a certainty was withdrawn", "CHAIN_CREATED": "learned a way of working",
    "CHAIN_VARIANT": "found a variation that works", "UNSAFE_REFUSED": "refused something unsafe",
    "ESCALATED_UNSURE": "checked with you when unsure", "INJECTION_SUSPECTED": "spotted a manipulation attempt",
    "PERMISSION_DENIED": "was not allowed", "DEPENDENCY_CHANGED": "a dependency changed",
    "RESOURCE_LIMIT": "hit a limit of this machine", "WORLD_CHANGED": "the world changed",
    # labels the live store carries that the mockup table does not name (the same plain register)
    "LANDMARK_DISSOLVED": "a claim was cleaned away", "LANDMARK_MERGED": "two claims became one",
    "MEMORY_PRUNED": "cleaned out what no longer earned its place", "SECTOR_BORN": "a new territory appeared",
    "SECTOR_MERGED": "two territories became one", "SECTOR_PROVEN": "a territory was proven",
    "STRAND_DELETED": "you deleted a conversation", "STRAND_RENAMED": "you renamed a conversation",
}
CLUSTER_WORD = {"preference": "your preferences", "implement": "building", "research": "research", "debug": "fixing things",
                "voice": "voice", "environment": "this machine", "workflow": "ways of working"}
SPACE_WORD = {"conduct": "how you like to work", "domain": "what you work on", "style": "how you like to be spoken to",
              "chrono": "when you work", "context": "what goes on around the work", "capability": "what IRIS can do",
              "toolpath": "which tools worked"}
OUTCOME_WORD = {"success": "it finished", "partial": "it was partly done", "failure": "it failed", "miss": "it missed",
                "cancelled": "it was cancelled"}

_BARE_FACETS = {"proven": ("claim",), "learning": ("claim",), "cleaned": ("claim",), "contradicted": ("claim", "moment"),
                "pinned": ("pin",), "failed": ("step", "moment", "turn"), "helped": ("moment",),
                "outside": ("claim", "step", "moment", "turn", "artifact"), "eval": None}
_KEYED_FACETS = {"kind": None, "in": ("claim", "step", "moment", "turn", "artifact", "strand"),
                 "territory": ("claim", "step", "moment"), "from": ("claim", "moment"), "before": None, "after": None}
_LAST_SPAN_DAYS = {"day": 1, "week": 7, "month": 30}
_TOKEN_RE = re.compile(r'(?:(?P<key>[A-Za-z-]+):)?"(?P<phrase>[^"]*)"|(?P<word>\S+)')
_WORD_RE = re.compile(r"[^\W_]+")


def _squash(v: Any) -> str:
    return " ".join(str(v).split()) if v else ""


# a word joined in camelCase is words: "ImportError" -> "Import Error", "HTTPServer" -> "HTTP Server"
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z][a-z])|(?<=[A-Z])(?=[A-Z][a-z])")   # a capital that starts a lowercase run


def _fold(s: str) -> str:
    """Case- and accent-insensitive form; '_' reads as a space (labels, tool names), and so does a camelCase join
    (2026-10-25: "import error" found no claim saying "ImportError" - "error" never started a word). Keeps the length
    for ASCII except one space per camelCase join; _orig_pos maps a position back."""
    if not s.isascii():
        s = "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))
    return _CAMEL_RE.sub(" ", s).lower().replace("_", " ")


def _orig_pos(orig: str, pos: int) -> int:
    """A position in _fold(orig) as a position in orig (the camelCase joins _fold opened up are taken out)."""
    k = 0
    for m in _CAMEL_RE.finditer(orig):
        if m.start() + k >= pos:
            break
        k += 1
    return pos - k


def _utc_midnight(date_text: str) -> Optional[float]:
    try:
        return datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _facet(name: str, value: Optional[str], kinds: Optional[tuple], **extra: Any) -> dict:
    return {"facet": name, "value": value, "text": f"{name}:{value}" if value is not None else name,
            "kinds": list(kinds) if kinds else None, **extra}


def parse_query(q: str, now: Optional[float] = None) -> dict:
    """The query language, parsed server-side so the surface can show the chips.
      words (AND, word-PREFIX), "quoted phrases" (exact), and facets: proven learning contradicted pinned cleaned failed
      helped outside eval | kind:<kind> in:<thread words> territory:<topic> from:<you|test|finished|held-up|reviewer|iris>
      before:<YYYY-MM-DD> after:<YYYY-MM-DD> | last day / last week / last month.
    A facet word the parser does not know (kind:nothing, from:nobody, before:soon) is a plain word. A facet word inside
    quotes is a plain phrase. Returns {q, words, phrases, facets, ignored}; each facet names the kinds it can match."""
    now = time.time() if now is None else now
    toks = [(m.group("key"), m.group("phrase"), m.group("word")) for m in _TOKEN_RE.finditer(q)]
    words: list[str] = []
    phrases: list[str] = []
    facets: list[dict] = []
    i = 0
    while i < len(toks):
        key, phrase, word = toks[i]
        i += 1
        if phrase is not None:
            if key and key.lower() in ("in", "territory") and _fold(phrase).strip():
                facets.append(_facet(key.lower(), _squash(phrase), _KEYED_FACETS[key.lower()]))
                continue
            if key:
                words += _WORD_RE.findall(_fold(key))
            p = " ".join(_WORD_RE.findall(_fold(phrase)))
            if p:
                phrases.append(p)
            continue
        low = word.lower().strip('"')
        if low in _BARE_FACETS:
            facets.append(_facet(low, None, _BARE_FACETS[low]))
            continue
        if low == "last" and i < len(toks) and toks[i][2] and toks[i][2].lower() in _LAST_SPAN_DAYS:
            span = toks[i][2].lower()
            i += 1
            facets.append({**_facet("last", span, None, at=now - _LAST_SPAN_DAYS[span] * 86400.0), "text": f"last {span}"})
            continue
        if ":" in low:
            name, _, val = low.partition(":")
            val = val.strip('"')
            if name == "kind" and val in SEARCH_KINDS:
                facets.append(_facet("kind", val, (val,)))
                continue
            if name == "from" and val.replace("_", "-") in FROM_WORDS:
                facets.append(_facet("from", val.replace("_", "-"), _KEYED_FACETS["from"]))
                continue
            if name in ("before", "after") and _utc_midnight(val) is not None:
                # after:D = from D's first second on; before:D = before D begins (UTC days, like the active-day clock)
                facets.append(_facet(name, val, None, at=_utc_midnight(val)))
                continue
            if name in ("in", "territory") and _fold(val).strip():
                facets.append(_facet(name, val, _KEYED_FACETS[name]))
                continue
        words += _WORD_RE.findall(_fold(word))
    seen: set[str] = set()
    words = [w for w in words if not (w in seen or seen.add(w))]
    terms = [("word", w) for w in words] + [("phrase", p) for p in phrases]
    ignored = [t[1] for t in terms[SEARCH_TERMS_MAX:]]
    words = [t[1] for t in terms[:SEARCH_TERMS_MAX] if t[0] == "word"]
    phrases = [t[1] for t in terms[:SEARCH_TERMS_MAX] if t[0] == "phrase"]
    return {"q": q, "words": words, "phrases": phrases, "facets": facets, "ignored": ignored}


@dataclass
class _Plan:
    terms: list                     # (needle, compiled regex, is_phrase)
    kinds: tuple                    # the kinds searched, in display order
    flags: set                      # bare facets present
    evidence: Optional[set]         # from: -> the closed evidence alphabet
    in_terms: list                  # one term list per in: facet
    territory: list                 # folded topics
    after: Optional[float] = None
    before: Optional[float] = None
    empty_reason: Optional[str] = None


def _term_rx(word: str) -> re.Pattern:
    return re.compile(r"(?<![^\W_])" + re.escape(word) + r"([^\W_]*)")


def _terms_of(words: list[str], phrases: list[str]) -> list[tuple]:
    out = [(w, _term_rx(w), False) for w in words]
    for p in phrases:
        parts = p.split()
        out.append((parts[0], re.compile(r"(?<![^\W_])" + r"\s+".join(re.escape(x) for x in parts)), True))
    return out


def _plan_of(parsed: dict, kinds: Optional[list[str]]) -> _Plan:
    allowed = set(kinds) if kinds else set(SEARCH_KINDS)
    picked = {f["value"] for f in parsed["facets"] if f["facet"] == "kind"}
    if picked:
        allowed &= picked
    for f in parsed["facets"]:
        if f["kinds"] and f["facet"] != "kind":
            allowed &= set(f["kinds"])
    plan = _Plan(terms=_terms_of(parsed["words"], parsed["phrases"]), kinds=tuple(k for k in SEARCH_KINDS if k in allowed),
                 flags={f["facet"] for f in parsed["facets"] if f["value"] is None}, evidence=None, in_terms=[], territory=[])
    for f in parsed["facets"]:
        if f["facet"] == "from":
            plan.evidence = (plan.evidence or set()) | set(FROM_WORDS[f["value"]])
        elif f["facet"] == "in":
            plan.in_terms.append(_terms_of(_WORD_RE.findall(_fold(f["value"])), []))
        elif f["facet"] == "territory":
            plan.territory.append(_fold(f["value"]).strip())
        elif f["facet"] in ("after", "last"):
            plan.after = max(plan.after or f["at"], f["at"])
        elif f["facet"] == "before":
            plan.before = min(plan.before or f["at"], f["at"])
    if not plan.kinds:
        plan.empty_reason = "no kind of memory can satisfy these filters together"
    return plan



@lru_cache(maxsize=16384)
def _squash_fold(text: str) -> tuple[str, str]:
    o = _squash(text)
    return o, _fold(o)


def _F(weight: float, text: Any) -> Optional[tuple]:
    """One searchable field, squashed and folded ONCE (when the corpus is prepared, not per keystroke; the many repeated
    claim and event texts share one folding)."""
    if not text:
        return None
    o, f = _squash_fold(text if isinstance(text, str) else str(text))
    return (weight, o, f) if o else None


def _score(terms: list[tuple], fields: list[tuple]) -> Optional[tuple[float, str, int]]:
    """AND over the terms. fields = prepared [(weight, text, folded text)], heaviest first. A term scores the weight of the
    best field it matches (x1.0 for a whole word or a phrase, x0.85 for a word prefix); the match is the mean over the
    terms. Returns (match 0..1, the text of the first match, its position) or None. No terms = 1.0 (a facet-only query)."""
    if not terms:
        return 1.0, (fields[0][1] if fields else ""), 0
    total = 0.0
    first: Optional[tuple[str, int]] = None
    if fields and any(t[0] not in fields[0][3] for t in terms):
        return None
    for needle, rx, phrase in terms:
        best, where = 0.0, None
        for w, orig, fol, _blob in fields:
            if w <= best or needle not in fol:
                continue
            m = rx.search(fol)
            if m is None:
                continue
            s = w * (1.0 if phrase or not m.group(1) else 0.85)
            if s > best:
                best, where = s, (orig, _orig_pos(orig, m.start()))
        if best == 0.0:
            return None
        total += best
        first = first or where
    return total / len(terms), first[0], first[1]


def _excerpt(text: str, pos: int, n: int = SEARCH_SNIPPET_MAX) -> str:
    """At most n characters of the text, around position pos."""
    if len(text) <= n:
        return text
    start = max(0, min(pos - 40, len(text) - n))
    body = n - (3 if start else 0)
    trail = start + body < len(text)
    if trail:
        body -= 3
    return ("..." if start else "") + text[start:start + body] + ("..." if trail else "")


def _title_of(text: str) -> str:
    t = _squash(text)
    return t if len(t) <= SEARCH_TITLE_MAX else t[:SEARCH_TITLE_MAX - 3] + "..."


def _payload_text(raw: Any) -> str:
    """The string values of an event payload (never its keys), as one text."""
    try:
        d = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    out: list[str] = []

    def walk(v: Any, depth: int) -> None:
        if isinstance(v, str):
            out.append(v[:200])
        elif depth < 3 and isinstance(v, dict):
            for x in v.values():
                walk(x, depth + 1)
        elif depth < 3 and isinstance(v, list):
            for x in v[:20]:
                walk(x, depth + 1)

    walk(d, 0)
    return " ".join(out)[:600]


def _plain_event(family: Optional[str], label: Optional[str]) -> str:
    return EVENT_READ.get(label or "") or f"{FAMILY_WORD.get(family or '', 'other')} · {(label or '').lower().replace('_', ' ')}"


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"



# -- the prepared corpus: read once, folded once, kept SEARCH_CORPUS_TTL_S ------------------------------
# A keystroke is a new query; the TEXT it searches does not change between keystrokes. Each kind's rows are read (bounded),
# folded and kept for a few seconds, so the second keystroke matches in memory (measured: the first read of the parts costs
# 0.3 s warm, a cached query 10-40 ms). The cache holds the store's rows only - it is not a recall, it never writes.
# Bounded (SEARCH_CORPUS_MAX parts, each itself bounded by the caps above); one lock, so a part is read by one thread at a time
# (single-flight: a second keystroke waits for the first read instead of repeating it). TTL 0 = always read (tests).
SEARCH_CORPUS_TTL_S = 60.0       # the snapshot's TTL; a search is at most this stale (the answer says so: fresh_within_s)
SEARCH_CORPUS_MAX = 16
_corpus_lock = threading.Lock()
_corpus: dict[tuple, tuple[float, Any]] = {}


def _cached(path: Any, part: tuple, build: Any) -> Any:
    key = (str(path), part)
    with _corpus_lock:
        hit = _corpus.get(key)
        if hit is not None and time.monotonic() - hit[0] < SEARCH_CORPUS_TTL_S:
            return hit[1]
        val = build()   # raises: nothing is cached
        _corpus[key] = (time.monotonic(), val)
        while len(_corpus) > SEARCH_CORPUS_MAX:
            _corpus.pop(min(_corpus, key=lambda k: _corpus[k][0]))
        return val


def _fields(*fs: Optional[tuple]) -> list[tuple]:
    """A row's prepared fields. Each carries one blob of all the row's folded text: a term absent from the blob rejects the
    row with one substring test (most rows of a 15,000-row corpus)."""
    fs = [f for f in fs if f]
    blob = " | ".join(f[2] for f in fs)
    return [(w, o, f, blob) for w, o, f in fs]


def _gone(why: str) -> dict:
    return {"rows": [], "info": {"available": False, "why": why}}


def _load_chat(con: sqlite3.Connection, cdb: Optional[sqlite3.Connection]) -> dict:
    """Conversation titles and tags (chat store) + the memory's tombstones for the titles chat erased (section 4 case 1)."""
    chat: dict[str, dict] = {}
    if cdb is not None and "id" in table_cols(cdb, "conversations"):
        cols = table_cols(cdb, "conversations")
        want = ("id", "title", "parent_id", "tags", "pinned", "created_at", "updated_at")
        # PLAN  SELECT id, title, parent_id, tags, pinned, created_at, updated_at FROM conversations LIMIT 20000
        #       -> SCAN conversations (5.8k rows, a small table read whole; 55 ms warm)
        for r in cdb.execute(f"SELECT {pick_cols(cols, want)} FROM conversations LIMIT ?", (SEARCH_WHOLE_CAP,)):
            chat[r["id"]] = {"title": r["title"] or "", "parent": r["parent_id"], "tags": r["tags"], "pinned": bool(r["pinned"]),
                             "updated": ts_of(r["updated_at"]) or ts_of(r["created_at"])}
    renamed: dict[str, list[str]] = {}
    deleted: dict[str, dict] = {}
    if has_index_on(con, "memory_events", "family"):
        # PLAN  SELECT ts, label, thread_id, payload FROM memory_events WHERE family = 'memory' AND label IN (?, ?)
        #       ORDER BY ts DESC LIMIT 2000
        #       -> SEARCH memory_events USING INDEX idx_memory_events_label (family=? AND label=?) + TEMP B-TREE FOR ORDER BY
        for r in con.execute("SELECT ts, label, thread_id, payload FROM memory_events WHERE family = 'memory' AND label IN "
                             "('STRAND_DELETED', 'STRAND_RENAMED') ORDER BY ts DESC LIMIT ?", (SEARCH_TOMBSTONES,)):
            tid, pl = r["thread_id"], jload(r["payload"], {})
            if not tid or not isinstance(pl, dict):
                continue
            if r["label"] == "STRAND_DELETED":
                deleted.setdefault(tid, {"title": _squash(pl.get("title")), "at": ts_of(pl.get("at")) or r["ts"], "tags": pl.get("tags")})
            elif pl.get("old_title"):
                renamed.setdefault(tid, []).append(_squash(pl["old_title"]))
    titles = {tid: c["title"] for tid, c in chat.items()}
    strands: list[dict] = []
    for tid, c in chat.items():
        old = renamed.get(tid, [])
        tags = " ".join(str(t) for t in jload(c["tags"], []) if isinstance(t, (str, int)))
        strands.append({"kind": "strand", "id": tid, "title": c["title"] or pretty_thread(tid), "ts": c["updated"], "touch": c["updated"],
                        "F": _fields(_F(1.0, c["title"]), _F(0.8, " ".join(old)), _F(0.6, tags)), "ghost": False,
                        "mine": c["pinned"], "root": c["parent"] is None, "parent": c["parent"], "old": old})
    for tid, d in deleted.items():
        if tid in chat:
            continue
        titles[tid] = d["title"]
        old = renamed.get(tid, [])
        tags = " ".join(str(t) for t in (d["tags"] if isinstance(d["tags"], list) else []) if isinstance(t, (str, int)))
        strands.append({"kind": "strand", "id": tid, "title": d["title"] or pretty_thread(tid), "ts": d["at"], "touch": d["at"],
                        "F": _fields(_F(1.0, d["title"]), _F(0.8, " ".join(old)), _F(0.6, tags)), "ghost": True,
                        "mine": False, "root": None, "parent": None, "old": old})
    return {"rows": strands, "chat": chat, "titles": titles, "renamed": renamed,
            "info": {"read": len(chat), "complete": len(chat) < SEARCH_WHOLE_CAP, "ghosts": len(deleted)}}


def _load_claims(con: sqlite3.Connection, law: dict) -> dict:
    cols = table_cols(con, "mycelium_landmarks")
    if "landmark_id" not in cols:
        return _gone("there is no claims table")
    want = ("landmark_id", "label", "task_class", "micro_abstract_text", "tier", "is_permanent", "evidence", "activation_count",
            "contradictions", "last_activated", "last_verified", "created_at", "conversation_ref", "absorbed", "falsify_if",
            "cumulative_score")
    # a cleaned claim's evidence (a big JSON, 11 MB over the table) is not read: it ranks last and says how it was cleaned
    sel = ", ".join("CASE WHEN absorbed = 1 THEN NULL ELSE evidence END AS evidence" if c == "evidence" and {"absorbed", "evidence"} <= cols
                    else (c if c in cols else f"NULL AS {c}") for c in want)
    # PLAN  SELECT <cols> FROM mycelium_landmarks LIMIT 20000
    #       -> SCAN mycelium_landmarks (4k rows - 72 live, the rest cleaned; a small table, read whole; 40 ms warm)
    rows = con.execute(f"SELECT {sel} FROM mycelium_landmarks LIMIT ?", (SEARCH_WHOLE_CAP,)).fetchall()
    sectors = _sectors(con)
    parent = {x["key"]: x["parent"] for x in sectors}
    slabel = {x["key"]: _fold(x["label"] or "") for x in sectors}
    best_sector = _best_sector(con)
    out: list[dict] = []
    for r in rows:
        absorbed, tier = bool(r["absorbed"]), r["tier"] or "candidate"
        label = (r["label"] or "").replace("_", " ")
        text = r["micro_abstract_text"] or label
        cls = r["task_class"] or ""
        ev = [e for e in jload(r["evidence"], []) if isinstance(e, dict)]
        kinds = {SEARCH_EVIDENCE.get(str(e.get("kind")), "claim") for e in ev}
        touch = max([r["created_at"] or 0.0, r["last_activated"] or 0.0, r["last_verified"] or 0.0] + [ts_of(e.get("at")) or 0.0 for e in ev])
        key = best_sector.get(r["landmark_id"])
        out.append({"kind": "claim", "id": r["landmark_id"], "title": text, "ts": r["created_at"], "touch": touch,
                    "F": _fields(_F(1.0, text), _F(0.9, label), _F(0.6, cls), _F(0.6, CLUSTER_WORD.get(cls, ""))),
                    "absorbed": absorbed, "tier": tier, "score": r["cumulative_score"] or 0.0, "permanent": bool(r["is_permanent"]),
                    "acts": r["activation_count"] or 0, "n": (r["activation_count"] or 0) + law["independent"](ev),
                    "contradictions": r["contradictions"] or 0, "kinds": kinds,
                    "best": max(kinds, key=lambda k: EVIDENCE_LADDER.get(k, 0.0)) if kinds else "none", "mine": "user" in kinds,
                    "falsify": r["falsify_if"], "thread": r["conversation_ref"],
                    "places": [x for x in (_fold(_root_of(key, parent)) if key else "general", _fold(key or "general"),
                                           slabel.get(key or "", "")) if x], "channel": None})
    # Kyudo trust channel of the live claims (a cleaned claim ranks last whatever its trust). PLAN  SEARCH mycelium_episode_index
    # USING INDEX idx_epindex_landmark (landmark_id=?), 72 seeks
    chan = _channels(con, [c["id"] for c in out if not c["absorbed"]])
    for c in out:
        c["channel"] = chan.get(c["id"])
    return {"rows": out, "by_id": {c["id"]: c for c in out}, "info": {"read": len(rows), "complete": len(rows) < SEARCH_WHOLE_CAP}}


def _load_merges(con: sqlite3.Connection) -> dict:
    """absorbed claim id -> the survivor it was merged into (the newest merge of an absorbed id wins)."""
    if not table_cols(con, "mycelium_landmark_merges"):
        return {}
    # PLAN  SELECT absorbed_id, survivor_id FROM mycelium_landmark_merges ORDER BY created_at LIMIT 20000
    #       -> SCAN mycelium_landmark_merges + TEMP B-TREE FOR ORDER BY (3k rows, small; the table is indexed on survivor_id only)
    return {a: s for a, s in con.execute("SELECT absorbed_id, survivor_id FROM mycelium_landmark_merges ORDER BY created_at LIMIT ?",
                                         (SEARCH_WHOLE_CAP,))}


def _load_pins(con: sqlite3.Connection) -> dict:
    out: list[dict] = []
    seen: set[str] = set()
    found = False
    # PLAN  SELECT pin_id, title, pin_type, tags, created_at, substr(content, 1, 1000) FROM <pins | mycelium_pins> LIMIT 20000
    #       -> SCAN pins / mycelium_pins (an explicit-memory table: 4 rows today, tens by design; read whole)
    for table in ("pins", "mycelium_pins"):
        cols = table_cols(con, table)
        if "pin_id" not in cols:
            continue
        found = True
        sel = pick_cols(cols, ("pin_id", "title", "pin_type", "tags", "created_at")) + \
            (", substr(content, 1, 1000) AS content" if "content" in cols else ", NULL AS content")
        for r in con.execute(f"SELECT {sel} FROM {table} LIMIT ?", (SEARCH_WHOLE_CAP,)):
            if r["pin_id"] in seen:
                continue
            seen.add(r["pin_id"])
            tags = " ".join(str(t) for t in jload(r["tags"], []) if isinstance(t, (str, int)))
            # the pin store's own weights: title 50, content 30, tags 20 (pin_store.DEFAULT_SEARCH_WEIGHTS)
            out.append({"kind": "pin", "id": r["pin_id"], "title": r["title"] or "pin", "ts": r["created_at"], "touch": None,
                        "F": _fields(_F(1.0, r["title"]), _F(0.6, r["content"]), _F(0.4, tags)), "mine": True,
                        "kindword": r["pin_type"] or "note"})
    return {"rows": out, "info": {"read": len(out), "complete": True}} if found else _gone("there is no pins table")


def _load_turns(con: sqlite3.Connection) -> dict:
    if "task_summary" not in table_cols(con, "episodes"):
        return _gone("there is no episodes table")
    # PLAN  SELECT id, session_id, task_summary, failure_reason, outcome_type, user_confirmed, user_corrected, timestamp
    #       FROM episodes ORDER BY timestamp DESC LIMIT 5000
    #       -> SCAN episodes USING INDEX idx_ep_timestamp (stops at the LIMIT; 464 rows today)
    rows = con.execute("SELECT id, session_id, task_summary, failure_reason, outcome_type, user_confirmed, user_corrected, timestamp "
                       "FROM episodes ORDER BY timestamp DESC LIMIT ?", (SEARCH_WINDOW_TURNS,)).fetchall()
    out = []
    for r in rows:
        ts, outcome = ts_of(r["timestamp"]), r["outcome_type"] or "partial"
        out.append({"kind": "turn", "id": f"{r['session_id']}:{r['id']}", "title": r["task_summary"] or "a task", "ts": ts, "touch": ts,
                    "F": _fields(_F(1.0, r["task_summary"]), _F(0.8, r["failure_reason"])), "thread": r["session_id"],
                    "episode": r["id"], "outcome": outcome, "reason": r["failure_reason"], "confirmed": bool(r["user_confirmed"]),
                    "failed": outcome in ("failure", "miss") or bool(r["failure_reason"]),
                    "mine": bool(r["user_confirmed"] or r["user_corrected"])})
    return {"rows": out, "info": {"read": len(rows), "window": SEARCH_WINDOW_TURNS, "complete": len(rows) < SEARCH_WINDOW_TURNS}}


def _load_artifacts(con: sqlite3.Connection) -> dict:
    cols = table_cols(con, "document_data")
    if "document_id" not in cols:
        return _gone("there is no documents table")
    want = ("document_id", "conversation_id", "fmt", "kind", "title", "summary", "created_at", "capture_path")
    # PLAN  SELECT document_id, conversation_id, fmt, kind, title, summary, created_at, capture_path FROM document_data
    #       ORDER BY created_at DESC LIMIT 20000
    #       -> SCAN document_data USING INDEX idx_document_data_created (454 rows; the content blob is not selected)
    rows = con.execute(f"SELECT {pick_cols(cols, want)} FROM document_data ORDER BY created_at DESC LIMIT ?", (SEARCH_WHOLE_CAP,)).fetchall()
    out = []
    for r in rows:
        name = r["title"] or (r["summary"] or "")[:48] or f"{r['fmt'] or 'document'} · {str(r['document_id'])[:8]}"
        folder = (Path(r["capture_path"]).parent.name if r["capture_path"] else None) or DOC_FOLDER.get(r["fmt"] or "", r["fmt"] or "unsorted")
        kind = "screen" if r["capture_path"] else DOC_KIND.get(r["kind"] or "", DOC_KIND.get(r["fmt"] or "", "doc"))
        out.append({"kind": "artifact", "id": r["document_id"], "title": name, "ts": r["created_at"], "touch": r["created_at"],
                    "F": _fields(_F(1.0, name), _F(0.6, r["fmt"]), _F(0.6, folder), _F(0.5, kind)), "thread": r["conversation_id"],
                    "folder": folder, "mine": False})
    return {"rows": out, "info": {"read": len(rows), "complete": len(rows) < SEARCH_WHOLE_CAP}}


def _load_nodes(con: sqlite3.Connection) -> dict:
    cols = table_cols(con, "mycelium_nodes")
    if "node_id" not in cols:
        return _gone("there is no nodes table")
    want = ("node_id", "space_id", "label", "confidence", "updated_at", "access_count", "last_accessed", "last_decayed_at", "source_channel")
    # PLAN  SELECT <cols> FROM mycelium_nodes LIMIT 20000 -> SCAN mycelium_nodes (140 rows, small; read whole)
    rows = con.execute(f"SELECT {pick_cols(cols, want)} FROM mycelium_nodes LIMIT ?", (SEARCH_WHOLE_CAP,)).fetchall()
    out = []
    for r in rows:
        label, space = (r["label"] or "").replace("_", " "), r["space_id"] or ""
        touch = max(r["updated_at"] or 0.0, r["last_accessed"] or 0.0, r["last_decayed_at"] or 0.0)
        out.append({"kind": "node", "id": r["node_id"], "title": label or r["node_id"], "ts": r["updated_at"], "touch": touch or None,
                    "F": _fields(_F(1.0, label), _F(0.5, SPACE_WORD.get(space, "")), _F(0.5, space)), "space": space,
                    "conf": r["confidence"] if r["confidence"] is not None else 0.5, "acts": r["access_count"] or 0,
                    "channel": r["source_channel"], "mine": False})
    return {"rows": out, "info": {"read": len(rows), "complete": len(rows) < SEARCH_WHOLE_CAP}}


# the newest-N windows of the two big tables. The ORDER BY runs on the ts / created_at index; the row is joined by rowid and
# its text is NOT read for a row that is no step (no mediator: an echo of an event) or an evaluation row when those are hidden.
_STEPS_WINDOW_SQL = (
    "SELECT c.rowid AS rid, c.thread_id, c.created_at, c.chain_id, c.topic_domain, c.mediator, "
    "CASE WHEN c.mediator IS NULL OR (? AND c.thread_id >= 'eval-' AND c.thread_id < 'eval.') THEN NULL "
    f"ELSE substr(c.insight, 1, {SEARCH_ROW_TEXT}) END AS insight, "
    "CASE WHEN c.mediator IS NULL OR (? AND c.thread_id >= 'eval-' AND c.thread_id < 'eval.') THEN NULL "
    f"ELSE substr(c.result, 1, {SEARCH_ROW_TEXT}) END AS result "
    "FROM (SELECT rowid AS rid FROM memory_chain WHERE created_at >= ? AND created_at < ? ORDER BY created_at DESC LIMIT ?) w "
    "JOIN memory_chain c ON c.rowid = w.rid")
_MOMENTS_WINDOW_SQL = (
    "SELECT e.event_id, e.ts, e.thread_id, e.episode_id, e.family, e.label, e.valence, e.actor, e.evidence, e.topic_domain, "
    "CASE WHEN ? AND e.thread_id >= 'eval-' AND e.thread_id < 'eval.' THEN NULL ELSE e.payload END AS payload "
    "FROM (SELECT rowid AS rid FROM memory_events WHERE ts >= ? AND ts < ? ORDER BY ts DESC LIMIT ?) w "
    "JOIN memory_events e ON e.rowid = w.rid")


def _load_steps(con: sqlite3.Connection, hide: int, lo: float, hi: float) -> dict:
    if not has_index_on(con, "memory_chain", "created_at"):
        return _gone("memory_chain(created_at) is not indexed: the newest-rows window cannot run")
    # PLAN  SELECT … FROM (SELECT rowid AS rid FROM memory_chain WHERE created_at >= ? AND created_at < ?
    #         ORDER BY created_at DESC LIMIT 6000) w JOIN memory_chain c ON c.rowid = w.rid
    #       -> SEARCH memory_chain USING COVERING INDEX idx_memory_chain_created (created_at>? AND created_at<?),
    #          then SEARCH c USING INTEGER PRIMARY KEY (rowid=?). At most 6000 index entries and 6000 row reads (9 ms warm).
    rows = con.execute(_STEPS_WINDOW_SQL, (hide, hide, lo, hi, SEARCH_WINDOW_STEPS)).fetchall()
    out, steps, hidden, oldest = [], 0, 0, None
    for r in rows:
        oldest = r["created_at"] if oldest is None or r["created_at"] < oldest else oldest
        if r["mediator"] is None:
            continue
        steps += 1
        if hide and (r["thread_id"] or "").startswith(EVAL_THREAD_PREFIX):
            hidden += 1
            continue
        tool = r["mediator"].split(":")[0]
        res = r["result"] or ""
        out.append({"kind": "step", "id": r["chain_id"] or f"{r['thread_id']}#{r['rid']}", "title": r["insight"] or f"used {tool}",
                    "ts": r["created_at"], "touch": r["created_at"], "thread": r["thread_id"], "chain": r["chain_id"], "tool": tool,
                    "result": r["result"], "topic": r["topic_domain"] or "general", "mine": False, "failed": res == "failure",
                    "F": _fields(_F(1.0, r["insight"]), _F(0.7, tool), _F(0.5, res if res != "success" else ""))})
    return {"rows": out, "info": {"read": len(rows), "steps": steps, "window": SEARCH_WINDOW_STEPS, "since": oldest,
                                  "complete": len(rows) < SEARCH_WINDOW_STEPS, "hidden": hidden}}


def _load_moments(con: sqlite3.Connection, hide: int, lo: float, hi: float) -> dict:
    if not has_index_on(con, "memory_events", "ts"):
        return _gone("memory_events(ts) is not indexed: the newest-rows window cannot run")
    # PLAN  SELECT … FROM (SELECT rowid AS rid FROM memory_events WHERE ts >= ? AND ts < ? ORDER BY ts DESC LIMIT 6000) w
    #         JOIN memory_events e ON e.rowid = w.rid
    #       -> SEARCH memory_events USING COVERING INDEX idx_memory_events_ts (ts>? AND ts<?), then SEARCH e USING INTEGER
    #          PRIMARY KEY (rowid=?). At most 6000 index entries and 6000 row reads (payloads average 80 characters; 30-70 ms warm).
    rows = con.execute(_MOMENTS_WINDOW_SQL, (hide, lo, hi, SEARCH_WINDOW_MOMENTS)).fetchall()
    out, hidden, oldest = [], 0, None
    for r in rows:
        ts, tid, label = r["ts"], r["thread_id"], r["label"]
        oldest = ts if oldest is None or ts < oldest else oldest
        if hide and (tid or "").startswith(EVAL_THREAD_PREFIX):
            hidden += 1
            continue
        ep = r["episode_id"]
        plain = _plain_event(r["family"], label)
        out.append({"kind": "moment", "id": r["event_id"], "title": plain, "ts": ts, "touch": ts, "thread": tid, "family": r["family"],
                    "label": label, "evidence": r["evidence"], "valence": r["valence"], "topic": r["topic_domain"] or "general",
                    "mine": r["evidence"] == "user" or r["actor"] == "user", "failed": r["valence"] == "sets_back",
                    "turn": (f"{tid}:{ep[len(tid) + 1:] if ep.startswith(tid + ':') else ep}" if tid and ep else None),
                    "F": _fields(_F(1.0, plain), _F(0.8, label), _F(0.6, FAMILY_WORD.get(r["family"] or "", "")),
                                 _F(0.5, _payload_text(r["payload"])))})
    return {"rows": out, "info": {"read": len(rows), "window": SEARCH_WINDOW_MOMENTS, "since": oldest,
                                  "complete": len(rows) < SEARCH_WINDOW_MOMENTS, "hidden": hidden}}


class _Search:
    """One search call: the plan, the matched candidates. The prepared rows it reads are shared (cached) and never changed:
    a candidate is a copy of its row."""

    def __init__(self, plan: _Plan, now: float, law: dict, chat: dict) -> None:
        self.p, self.now, self.law = plan, now, law
        self.chat, self.titles, self.renamed = chat["chat"], chat["titles"], chat["renamed"]
        self.n0 = plan.terms[0][0] if plan.terms else None   # the first needle: one substring test rejects most rows before _score
        self.cands: list[dict] = []
        self.totals: dict[str, int] = {k: 0 for k in plan.kinds}
        self._tmemo: dict[str, int] = {}
        self._hidden = 0                                 # evaluation rows skipped by the current reader

    # -- shared filters ---------------------------------------------------------------------------
    def time_ok(self, ts: Optional[float]) -> bool:
        p = self.p
        if p.after is None and p.before is None:
            return True
        if ts is None:
            return False
        return (p.after is None or ts >= p.after) and (p.before is None or ts < p.before)

    def thread_ok(self, tid: Optional[str]) -> bool:
        """Evaluation threads are hidden unless the eval facet is on (counted in _hidden); outside / in: narrow the rest."""
        p = self.p
        if tid is None:
            return not p.in_terms      # no thread: outside the chat, and no thread name to match
        code = self._tmemo.get(tid)
        if code is None:
            title = self.titles.get(tid)
            if _is_eval_thread(tid, title) and "eval" not in p.flags:
                code = 0
            elif "outside" in p.flags and tid in self.chat:
                code = -1
            else:
                code = 1
                if p.in_terms:
                    text = _fold(" ".join(str(n) for n in (title, tid, *self.renamed.get(tid, [])) if n))
                    code = 1 if all(all(t[1].search(text) for t in terms) for terms in p.in_terms) else -1
            self._tmemo[tid] = code
        if code == 0:
            self._hidden += 1
        return code == 1

    def add(self, row: dict, m: tuple) -> None:
        self.totals[row["kind"]] += 1
        self.cands.append({**row, "match": m[0], "snip": m[1], "pos": m[2]})

    def places_ok(self, places: list[str]) -> bool:
        return all(any(n.startswith(t) for n in places) for t in self.p.territory)

    # -- matchers: one per kind, over the prepared rows -------------------------------------------------
    def match_claims(self, rows: list[dict]) -> None:
        p, n0 = self.p, self.n0
        for r in rows:
            if n0 is not None and (not r["F"] or n0 not in r["F"][0][3]):
                continue
            if "proven" in p.flags and (r["absorbed"] or r["tier"] != "landmark"):
                continue
            if "learning" in p.flags and (r["absorbed"] or r["tier"] != "candidate"):
                continue
            if "cleaned" in p.flags and not r["absorbed"]:
                continue
            if "contradicted" in p.flags and not r["contradictions"] > 0:
                continue
            if p.evidence is not None and not (r["kinds"] & p.evidence):
                continue    # a cleaned claim's evidence is not read: from: cannot vouch for it
            if p.territory and not self.places_ok(r["places"]):
                continue
            m = _score(p.terms, r["F"])     # the text first: it rejects almost every row; the thread / time filters see the rest
            if m is not None and self.time_ok(r["ts"]) and self.thread_ok(r["thread"]):
                self.add(r, m)

    def match_strands(self, rows: list[dict]) -> None:
        p, n0 = self.p, self.n0
        for r in rows:
            if n0 is not None and (not r["F"] or n0 not in r["F"][0][3]):
                continue
            m = _score(p.terms, r["F"])
            if m is None or not self.time_ok(r["ts"]) or not self.thread_ok(r["id"]):
                continue
            # found by a name it no longer has: say which
            was = None
            if p.terms and r["old"] and _score(p.terms, r["F"][:1]) is None:
                was = next((o for o in r["old"] if _score(p.terms, _fields(_F(1.0, o)))), None)
            self.add({**r, "was": was}, m)

    def match_plain(self, rows: list[dict], thread_key: Optional[str] = None) -> None:
        """pins, tasks, artifacts, nodes, steps, moments: a time filter, a thread filter, the facets each carries."""
        p, n0 = self.p, self.n0
        for r in rows:
            if n0 is not None and (not r["F"] or n0 not in r["F"][0][3]):
                continue
            if "failed" in p.flags and r["kind"] in ("step", "moment", "turn") and not r["failed"]:
                continue
            if r["kind"] == "moment":
                if "contradicted" in p.flags and r["label"] != "CLAIM_CONTRADICTED":
                    continue
                if "helped" in p.flags and r["label"] != "RECALL_HELPED":
                    continue
                if p.evidence is not None and r["evidence"] not in p.evidence:
                    continue
            if p.territory and r["kind"] in ("step", "moment") and not self.places_ok([_fold(r["topic"])]):
                continue
            m = _score(p.terms, r["F"])
            if m is not None and self.time_ok(r["ts"]) and (not thread_key or self.thread_ok(r[thread_key])):
                self.add(r, m)

    # -- rank: match x kind x strength ------------------------------------------------------------
    def strengthen(self, c: dict, clock: Any) -> None:
        """c['alive'], c['proven'], c['strength'], c['rank'] from the memory's own numbers. Computed here, never written back."""
        law, kind = self.law, c["kind"]
        days = clock.days_since(c["touch"]) if clock is not None and c.get("touch") else 0.0
        c["days"] = days
        if kind == "claim":
            alive, c["fading"] = _claim_alive(law, c["score"], c["permanent"], days, c["n"])
            ev = EVIDENCE_LADDER.get(c["best"], EVIDENCE_LADDER["none"])
            proven = ev if c["tier"] == "landmark" else ev * CANDIDATE_FACTOR
        elif kind == "node":
            alive = law["node_after"](c["conf"], law["node_rate"], law["channel_mult"](c["channel"]), days)
            proven = NEUTRAL_PROVEN
        elif kind == "pin":
            alive, proven = 1.0, NEUTRAL_PROVEN              # explicit memory: held, not earned - it does not decay
        else:
            alive = math.exp(-law["rate"] * days)            # no strength of its own: freshness under the claims' rate
            if kind == "moment":
                proven = EVIDENCE_LADDER.get(c["evidence"] or "none", EVIDENCE_LADDER["none"])
            elif kind == "turn":
                proven = EVIDENCE_LADDER["user"] if c["confirmed"] else (EVIDENCE_LADDER["completion"] if c["outcome"] == "success"
                                                                          else EVIDENCE_LADDER["none"])
            else:
                proven = NEUTRAL_PROVEN
        if c.get("ghost"):
            alive = GHOST_STRENGTH
        c["alive"], c["proven"] = max(ALIVE_FLOOR, min(1.0, alive)), proven
        self.rerank(c)

    def rerank(self, c: dict) -> None:
        used = min(1.0, math.log1p(c.get("acts", 0)) / math.log1p(USED_SATURATION))
        trust = 1.0
        if c.get("channel") is not None:
            trust = 0.5 + 0.5 / self.law["channel_mult"](c["channel"])      # untrusted 0.6 ... system 1.0
        mine = MINE_BOOST if c.get("mine") else 1.0
        c["strength"] = c["alive"] * (PROVEN_BASE + PROVEN_SPAN * c["proven"]) * (1.0 + USED_WEIGHT * used) * trust * mine
        c["rank"] = c["match"] * KIND_WEIGHT[c["kind"]] * c["strength"] * (CLEANED_FACTOR if c.get("absorbed") else 1.0)


def _claim_alive(law: dict, score: float, permanent: bool, days: float, n: int) -> tuple[float, bool]:
    """A claim's decayed score after `days` active idle days, and whether it is fading (under FADING_BELOW of its score)."""
    alive = score if permanent else law["credibility"](score, law["rate"], days, n)
    return alive, not permanent and score > 0 and alive < FADING_BELOW * score


def _search_law() -> dict:
    """The growth / decay law the memory itself runs (decay.py, landmark.py), imported when a search runs."""
    from backend.memory.mycelium import decay  # noqa: PLC0415 - lazy: the mycelium package is heavy
    from backend.memory.mycelium.landmark import _DECAY_NON_PERMANENT, _independent  # noqa: PLC0415
    return {"credibility": decay.landmark_credibility, "rate": _DECAY_NON_PERMANENT, "independent": _independent,
            "node_after": decay.node_confidence_after, "node_rate": decay.NODE_DECAY_RATE_DEFAULT,
            "channel_mult": decay.channel_multiplier, "clock": decay.ActivityClock}


def _cleaned_fates(cleaned: list[dict], merges: dict[str, str], by_id: dict[str, dict], clock: Any) -> None:
    """For each cleaned claim in the answer: the survivor it was merged into (the merge log, followed to its end), or the reason
    Kyudo wrote. Sets c['survivor'] = {id, title, live} and c['fate'] (the plain words). Reads the prepared corpus only."""
    final: dict[str, str] = {}
    for c in cleaned:
        cur, hops = c["id"], 0
        while cur in merges and hops < MERGE_HOPS:
            cur, hops = merges[cur], hops + 1
        if hops:
            final[c["id"]] = cur
    titles = {sid: (by_id[sid]["title"], by_id[sid]["absorbed"]) for sid in set(final.values()) if sid in by_id}
    for c in cleaned:
        sid = final.get(c["id"])
        c["survivor"] = None
        if sid and sid in titles:
            c["survivor"] = {"id": sid, "title": _title_of(titles[sid][0]), "live": not titles[sid][1]}
            c["fate"] = "merged into " + _title_of(titles[sid][0])[:60] + ("" if not titles[sid][1] else " (since cleaned too)")
            continue
        reason = (c.get("falsify") or "").replace("dissolved:", "").strip()
        idle = int(round(clock.days_since(c["touch"]))) if clock is not None and c.get("touch") else None
        c["fate"] = _dissolved_fate(reason, idle)


def _dissolved_fate(reason: str, idle: Optional[int]) -> str:
    """The reason Kyudo wrote for dissolving a claim, in plain words."""
    if reason == "no_credibility":
        return "no use and no evidence" + (f" - last touched {_plural(idle, 'active day', 'active days')} ago" if idle is not None else "")
    if reason == "dangling_cluster":
        return "its places on the map were gone"
    if reason == "hub_cluster":
        return "too many different claims shared its place"
    return "cleaned by the integrity pass"


def _why(c: dict) -> str:
    """ONE plain line: where it ranks and why."""
    kind = c["kind"]
    if kind == "claim":
        if c["absorbed"]:
            return "cleaned - " + c.get("fate", "cleaned by the integrity pass")
        parts = ["proven" if c["tier"] == "landmark" else ("learning" if c["tier"] == "candidate" else c["tier"])]
        if c["acts"]:
            parts.append("used " + _plural(c["acts"], "time", "times"))
        if c.get("fading"):
            parts.append(f"fading - not used or confirmed for {_plural(int(round(c['days'])), 'active day', 'active days')}")
        if c["contradictions"]:
            parts.append("contradicted " + _plural(c["contradictions"], "time", "times"))
        parts.append(EVIDENCE_WORD.get(c["best"], EVIDENCE_WORD["none"]))
        if c.get("channel") == 0:
            parts.append("from a source it does not trust")
        return " · ".join(parts)
    if kind == "moment":
        parts = [FAMILY_WORD.get(c["family"] or "", "a moment")]
        if c["evidence"] and c["evidence"] != "none":
            parts.append(EVIDENCE_WORD.get(c["evidence"], c["evidence"]))
        if c["valence"] == "sets_back":
            parts.append("it set things back")
        return " · ".join(parts)
    if kind == "step":
        return " · ".join([KIND_WORD["step"], "used " + c["tool"].replace("_", " "),
                           {"success": "it worked", "failure": "it failed"}.get(c["result"] or "", "no verdict")])
    if kind == "turn":
        parts = [KIND_WORD["turn"], OUTCOME_WORD.get(c["outcome"], c["outcome"])]
        if c["confirmed"]:
            parts.append(EVIDENCE_WORD["user"])
        if c["reason"]:
            parts.append("why: " + _squash(c["reason"])[:60])
        return " · ".join(parts)
    if kind == "pin":
        return f"a pin you keep ({c['kindword']}) · held, it does not fade"
    if kind == "artifact":
        return f"{KIND_WORD['artifact']} · in {c['folder']}"
    if kind == "node":
        parts = [KIND_WORD["node"], SPACE_WORD.get(c["space"], c["space"]), f"sure {int(round(c['conf'] * 100))}%"]
        if c["acts"]:
            parts.insert(2, "used " + _plural(c["acts"], "time", "times"))
        return " · ".join(parts)
    if c["ghost"]:
        return "deleted in chat - the memory kept its name"
    if c["was"]:
        return f"{'a thread' if c['root'] else 'a strand'} you renamed - it was called \"{_title_of(c['was'])[:60]}\""
    return "a thread" if c["root"] else "a strand of a thread"


def _ref(c: dict) -> dict:
    kind = c["kind"]
    if kind == "claim":
        sv = c.get("survivor")
        return {"claim": c["id"], "cleaned": c["absorbed"], "survivor": sv["id"] if sv else None, "thread": c["thread"]}
    if kind == "strand":
        return {"strand": c["id"], "ghost": c["ghost"], "parent": c["parent"]}
    if kind == "step":
        return {"thread": c["thread"], "strand": c["thread"], "chain": c["chain"]}
    if kind == "moment":
        return {"thread": c["thread"], "strand": c["thread"], "event": c["id"], "turn": c["turn"]}
    if kind == "turn":
        return {"turn": c["id"], "thread": c["thread"], "strand": c["thread"], "episode": c["episode"]}
    if kind == "artifact":
        return {"artifact": c["id"], "thread": c["thread"], "strand": c["thread"]}
    if kind == "node":
        return {"node": c["id"], "space": c["space"]}
    return {"pin": c["id"]}


def _sort_key(c: dict) -> tuple:
    """A cleaned claim sorts after every live result, whatever its rank."""
    return (not c.get("absorbed"), c["rank"], c["ts"] or 0.0)


def _window_note(kind: str, word: str, info: dict) -> Optional[str]:
    if info.get("available") is False:
        return f"{word} were not searched: {info.get('why', 'the table is missing')}"
    if "window" not in info:
        return None
    n = f"{info['read']:,}"
    extra = f" ({info['steps']:,} of them steps)" if kind == "step" else ""
    span = f", back to {time.strftime('%Y-%m-%d', time.gmtime(info['since']))}" if info.get("since") else ""
    head = f"searched all {n} {word}{extra}" if info["complete"] else f"searched the newest {n} {word}{extra}{span}"
    if info.get("hidden_eval"):
        head += f"; {info['hidden_eval']:,} from evaluation runs hidden (add 'eval' to include them)"
    return head



def search(q: str, kinds: Optional[str] = None, limit: int = SEARCH_LIMIT_DEFAULT, *, now: Optional[float] = None,
           db: Optional[Path | str] = None, conv_db: Optional[Path | str] = None) -> dict:
    """GET /api/memory/search. Text only, built for memory.db: what the memory holds about this, and how much it holds it.
    rank = match x kind weight x strength; strength = alive x (0.4 + 0.6 x proven) x (1 + 0.25 x used) x trust x mine
    (see the constants above). A cleaned claim sorts after every live result and carries its fate. Read-only; not a recall.
    `kinds` = comma-separated kinds; with exactly one kind in play, up to `limit` of it are returned, else SEARCH_PER_KIND
    per kind (totals say how many more there are). `db` / `conv_db` name other stores (tests, measurements)."""
    t0 = time.perf_counter()
    q = str(q or "")
    if len(q) > SEARCH_QUERY_MAX:
        raise BadRequest(f"q is longer than {SEARCH_QUERY_MAX} characters")
    limit = max(1, min(int(limit), SEARCH_LIMIT_MAX))
    want: Optional[list[str]] = None
    if kinds:
        want = [k.strip().lower() for k in kinds.split(",") if k.strip()]
        bad = [k for k in want if k not in SEARCH_KINDS]
        if bad:
            raise BadRequest(f"kinds must be among {list(SEARCH_KINDS)}; got {bad}")
    now = time.time() if now is None else now
    parsed = parse_query(q, now)
    plan = _plan_of(parsed, want)
    out: dict[str, Any] = {"q": q, "parse": parsed, "kinds": list(plan.kinds), "limit": limit, "per_kind": SEARCH_PER_KIND,
                           "results": [], "totals": {}, "shown": {}, "searched": {}, "notes": [], "generated": now,
                           "fresh_within_s": SEARCH_CORPUS_TTL_S}
    if not (parsed["words"] or parsed["phrases"] or parsed["facets"]) or plan.empty_reason:
        out["notes"].append(plan.empty_reason or "type a word, a phrase or a filter")
        out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return out
    law = _search_law()
    ref = uuid.uuid4().hex[:8]
    dbp = db or memory_db_path()
    cpath = conv_db or (Path(db).with_name("conversations.db") if db else None)
    searched: dict[str, dict] = {}
    with ExitStack() as stack:
        # Connections open only when a part must be read: a search answered from the prepared corpus opens none (an open
        # costs 5-50 ms on the hard disk). A missing store raises StoreUnavailable at the first part that has to be read.
        opened: dict[str, Any] = {}

        def con() -> sqlite3.Connection:
            if "mem" not in opened:
                opened["mem"] = stack.enter_context(read_only(dbp))
            return opened["mem"]

        def cdb() -> Optional[sqlite3.Connection]:
            if "chat" not in opened:
                opened["chat"] = stack.enter_context(_optional_chat_store(cpath))
            return opened["chat"]

        try:
            chat = _cached(dbp, ("chat", str(cpath or conversations_db_path())), lambda: _load_chat(con(), cdb()))
        except sqlite3.Error as exc:   # titles are the one shared input: without them the thread filters read nothing
            logger.warning("[memory_search] ref=%s chat store failed: %s: %s", ref, type(exc).__name__, exc)
            chat = {"rows": [], "chat": {}, "titles": {}, "renamed": {}, "info": {"available": False, "why": "the chat store is resting"}}
        s = _Search(plan, now, law, chat)
        # The step / moment windows are the newest rows, so an "after" / "last week" bound needs no SQL bound (the newest rows are
        # the ones after it; the matcher filters). Only a "before" reaches back: its bound is rounded up to the hour, to be cached.
        lo = 0.0
        hi = math.ceil(plan.before / 3600.0) * 3600.0 if plan.before is not None else 1e18
        hide = 0 if "eval" in plan.flags else 1
        parts = {
            "claim": lambda: (_cached(dbp, ("claims",), lambda: _load_claims(con(), law)), s.match_claims),
            "strand": lambda: (chat, s.match_strands),
            "pin": lambda: (_cached(dbp, ("pins",), lambda: _load_pins(con())), s.match_plain),
            "turn": lambda: (_cached(dbp, ("turns",), lambda: _load_turns(con())), lambda rows: s.match_plain(rows, "thread")),
            "artifact": lambda: (_cached(dbp, ("artifacts",), lambda: _load_artifacts(con())), lambda rows: s.match_plain(rows, "thread")),
            "node": lambda: (_cached(dbp, ("nodes",), lambda: _load_nodes(con())), s.match_plain),
            "step": lambda: (_cached(dbp, ("steps", hide, lo, hi), lambda: _load_steps(con(), hide, lo, hi)),
                             lambda rows: s.match_plain(rows, "thread")),
            "moment": lambda: (_cached(dbp, ("moments", hide, lo, hi), lambda: _load_moments(con(), hide, lo, hi)),
                               lambda rows: s.match_plain(rows, "thread")),
        }
        for kind in plan.kinds:
            try:
                part, match = parts[kind]()
                s._hidden = 0
                match(part["rows"])
                info = dict(part["info"])
                if info.get("available") is not False:
                    info["hidden_eval"] = info.get("hidden", 0) + s._hidden
                searched[kind] = info
            except sqlite3.Error as exc:   # one kind failing leaves the others answering, and says so
                logger.warning("[memory_search] ref=%s kind=%s failed: %s: %s", ref, kind, type(exc).__name__, exc)
                searched[kind] = {"available": False, "why": "the memory is resting"}
        clock = _cached(dbp, ("clock",), lambda: law["clock"](con(), 0.0, now)) if s.cands else None
        for c in s.cands:
            s.strengthen(c, clock)
        single = len(plan.kinds) == 1
        cap = limit if single else SEARCH_PER_KIND
        by_kind: dict[str, list[dict]] = {}
        for c in s.cands:
            by_kind.setdefault(c["kind"], []).append(c)
        chosen: list[dict] = []
        for kind in plan.kinds:
            chosen += heapq.nlargest(cap, by_kind.get(kind, []), key=_sort_key)
        chosen = heapq.nlargest(limit, chosen, key=_sort_key)
        cleaned = [c for c in chosen if c["kind"] == "claim" and c["absorbed"]]
        if cleaned:
            merges = _cached(dbp, ("merges",), lambda: _load_merges(con()))
            claims = _cached(dbp, ("claims",), lambda: _load_claims(con(), law))
            _cleaned_fates(cleaned, merges, claims["by_id"], clock)
    out["results"] = [{"kind": c["kind"], "id": c["id"], "title": _title_of(c["title"]), "snippet": _excerpt(c["snip"], c["pos"]),
                       "why": _why(c), "rank": round(c["rank"], 4), "ts": c["ts"], "ref": _ref(c)} for c in chosen]
    out["shown"] = {k: sum(1 for r in out["results"] if r["kind"] == k) for k in plan.kinds}
    out["totals"] = s.totals
    out["searched"] = searched
    words = {"step": "rows of the step log", "moment": "moments", "turn": "tasks"}
    out["notes"] = [n for k in plan.kinds if (n := _window_note(k, words.get(k, k + "s"), searched.get(k, {})))]
    out["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out

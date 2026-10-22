"""Every SQL statement of the Memory surface, in one place (MEMORY-SURFACE-BUILD.md section 6/7, phase 0).

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

NOT DERIVABLE (said once, here): which TURN received a claim. RECALL_* events name chain ids, not landmark
ids (export_snapshot.py says the same). What is derivable is the episodes that observed the claim
(mycelium_episode_index.landmark_id, indexed): claim detail returns them as observed_in.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from contextlib import contextmanager
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
EDGES_CAP = 50
MERGE_HOPS = 8
OUTSIDE_RECENT_STEPS = 3000
EVAL_SAMPLE_STEPS = 2000
PREVIEW_MESSAGE = 120
PREVIEW_INSIGHT = 140
PREVIEW_CLAIM = 280
EVAL_TITLE_PREFIX = "[eval]"          # conversations the eval harness creates
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
    return tid.startswith(EVAL_THREAD_PREFIX) or bool(title and title.startswith(EVAL_TITLE_PREFIX))


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
                roots, ev_roots = cdb.execute("SELECT COUNT(*), COALESCE(SUM(title LIKE ? || '%'), 0) FROM conversations "
                                              "WHERE parent_id IS NULL", (EVAL_TITLE_PREFIX,)).fetchone()
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

        # last integrity pass: the newest Kyudo cleaning event (rare labels, a handful of rows each)
        # PLAN  SELECT MAX(ts), COUNT(*) FROM memory_events WHERE family='memory' AND label=?
        #       -> SEARCH memory_events USING INDEX idx_memory_events_label (family=? AND label=?)
        last: Optional[dict] = None
        if "memory_events" in have:
            for lab in INTEGRITY_LABELS:
                ts, n = con.execute("SELECT MAX(ts), COUNT(*) FROM memory_events WHERE family = 'memory' AND label = ?",
                                    (lab,)).fetchone()
                if ts is not None and (last is None or ts > last["ts"]):
                    last = {"ts": ts, "label": lab, "total_of_label": n}
        out["last_integrity_pass"] = last
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
            total, hidden_eval = cdb.execute("SELECT COUNT(*), COALESCE(SUM(title LIKE ? || '%'), 0) FROM conversations "
                                             "WHERE parent_id IS NULL", (EVAL_TITLE_PREFIX,)).fetchone()
            # PLAN  SELECT id FROM conversations -> SCAN conversations USING COVERING INDEX sqlite_autoindex_conversations_1 (4.3k)
            conv_ids = {r[0] for r in cdb.execute("SELECT id FROM conversations")}
            flt = "" if include_eval else "AND title NOT LIKE ? || '%' "
            # PLAN  SELECT … FROM conversations WHERE parent_id IS NULL [AND title NOT LIKE ?] ORDER BY updated_at DESC LIMIT ?
            #       -> SEARCH conversations USING INDEX idx_conversations_parent (parent_id=?) + TEMP B-TREE FOR ORDER BY
            #          (4.3k rows, small; conversations has no updated_at index - chat's own thread list reads the same way)
            rows = cdb.execute("SELECT id, title, created_at, updated_at, pinned, tags, project_id FROM conversations "
                               f"WHERE parent_id IS NULL {flt}ORDER BY updated_at DESC LIMIT ?",
                               ((limit,) if include_eval else (EVAL_TITLE_PREFIX, limit))).fetchall()
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
SNAPSHOT_LANDMARKS = 400
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
    events (at most 400 each), 400 live landmarks, 300 episodes, 80 artifacts, 600 nodes, ... include_eval=False
    drops eval-* threads. `db` / `conv_db` name another store (the exporter's --db; a git worktree has no data/).
    Optional tables a newer build adds read as "none" (meta.available says which were found).

    Every statement is LIMIT-bounded or a small-table read; the ones that would SCAN a big table when memory_events
    (thread_id) / memory_chain(chain_id) are not indexed are gated on has_index_on and say so in meta.warnings."""
    threads = max(1, min(int(threads), SNAPSHOT_THREADS_MAX))
    events = max(1, min(int(events), SNAPSHOT_EVENTS_MAX))
    warnings: list[str] = []
    available: dict[str, bool] = {}
    with read_only(db or memory_db_path()) as con:
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
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
        ev_cols = table_cols(con, "memory_events")
        ev_thread_idx = "memory_events" in have and has_index_on(con, "memory_events", "thread_id")

        # PLAN  SELECT family, COUNT(*) FROM memory_events GROUP BY family
        #       -> SCAN memory_events USING COVERING INDEX idx_memory_events_label (family, label) (42k entries)
        fam_counts = {r[0]: r[1] for r in con.execute("SELECT family, COUNT(*) FROM memory_events GROUP BY family")} \
            if "memory_events" in have else {}
        # territories of the lattice: topic domains. memory_chain is the only table that carries them in volume
        # (2026-10-18: memory_events ~90% NULL); NULL counts as "general"
        dom_counts: dict[str, int] = {}
        for tbl in ("memory_chain", "memory_events"):
            if tbl in have and "topic_domain" in table_cols(con, tbl):
                # PLAN  SELECT COALESCE(topic_domain,'general'), COUNT(*) FROM <tbl> GROUP BY 1
                #       -> SCAN <tbl> + TEMP B-TREE FOR GROUP BY: the one whole-table read of the snapshot (no index on
                #          topic_domain). It reads one value per row; the cost is measured in the report.
                for r in con.execute(f"SELECT COALESCE(topic_domain, 'general'), COUNT(*) FROM {tbl} GROUP BY 1"):
                    dom_counts[r[0]] = dom_counts.get(r[0], 0) + r[1]
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

        # ② events (newest first, bounded) and the threads they belong to
        # PLAN  SELECT <cols> FROM memory_events [WHERE thread_id NOT LIKE 'eval-%'] ORDER BY ts DESC LIMIT ?
        #       -> SCAN memory_events USING INDEX idx_memory_events_ts (ts order; stops at the LIMIT)
        where = "" if include_eval else "WHERE thread_id NOT LIKE 'eval-%'"
        ev_want = ("event_id", "ts", "family", "label", "valence", "actor", "evidence", "episode_id", "thread_id", "links",
                   "payload", "topic_domain")
        ev_rows = con.execute(f"SELECT {pick_cols(ev_cols, ev_want)} FROM memory_events {where} ORDER BY ts DESC LIMIT ?",
                              (events,)).fetchall() if "memory_events" in have else []
        by_thread: dict[str, list] = {}
        for r in ev_rows:
            if r["thread_id"]:
                by_thread.setdefault(r["thread_id"], []).append(r)
        thread_ids = sorted(by_thread, key=lambda t: by_thread[t][0]["ts"], reverse=True)[:threads]
        if ev_thread_idx:
            # PLAN  SELECT COUNT(*) FROM (SELECT DISTINCT thread_id FROM memory_events)
            #       -> SCAN memory_events USING COVERING INDEX <the thread_id index> (42k entries)
            counts["sessions"] = con.execute("SELECT COUNT(DISTINCT thread_id) FROM memory_events").fetchone()[0]
        else:
            counts["sessions"] = len(by_thread)
            warnings.append("sessions counts the threads of the newest events: memory_events(thread_id) is not indexed")

        # ③ landmarks that are still live (absorbed ones were merged into a survivor)
        # PLAN  SELECT <cols> FROM mycelium_landmarks WHERE COALESCE(absorbed,0)=0 ORDER BY created_at DESC LIMIT 400
        #       -> SCAN mycelium_landmarks + TEMP B-TREE FOR ORDER BY (3.3k rows, small table)
        lm_want = ("landmark_id", "label", "task_class", "micro_abstract_text", "tier", "is_permanent", "evidence",
                   "activation_count", "contradictions", "last_activated", "last_verified", "created_at", "conversation_ref")
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
        landmarks = []
        for r in lm_rows:
            ev: list[dict] = []
            kinds: dict[str, int] = {}
            for e in jload(r["evidence"], [])[-400:]:
                if not isinstance(e, dict):
                    continue
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
                              "contradictions": r["contradictions"] or 0,
                              "last_activated": ts_of(r["last_activated"]), "last_verified": ts_of(r["last_verified"]),
                              "born": ts_of(r["created_at"]), "session": r["conversation_ref"], "fams": fams,
                              "domain": "general"})  # landmarks carry no domain column yet
        if not any(r["micro_abstract_text"] for r in lm_rows):
            warnings.append("no live landmark has micro_abstract_text")
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
        available["landmark_channel"] = "source_channel" in ei_cols and "landmark_id" in ei_cols
        if available["landmark_channel"] and lm_ids:
            chan = _channels(con, lm_ids)   # PLAN  SEARCH mycelium_episode_index USING INDEX idx_epindex_landmark
            for lm in landmarks:
                lm["channel"] = chan.get(lm["id"])

        # sectors: territories read from the registry when the tables exist (a newer build creates them); the page falls
        # back to the topic-domain territories otherwise. Roots are big, children nested.
        sectors: list[dict] = []
        sec_cols = table_cols(con, "mycelium_sectors")
        ls_cols = table_cols(con, "mycelium_landmark_sectors")
        available["sectors"] = bool(sec_cols)
        available["landmark_sectors"] = bool(ls_cols)
        if "sector_key" in sec_cols:
            want = ("sector_key", "parent_key", "label", "status", "members", "outside_evidence", "last_activity")
            # PLAN  … FROM mycelium_sectors WHERE COALESCE(status,'proven') != 'dissolved' LIMIT 200 -> SCAN (19 rows)
            sectors = [{"key": r["sector_key"], "parent": r["parent_key"] or None, "label": clip(r["label"], 60),
                        "status": r["status"] or "proven", "members": r["members"] or 0,
                        "evidence": r["outside_evidence"] or 0, "last": ts_of(r["last_activity"])}
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
        exits: dict[str, Any] = {}
        if "caducean_session_exits" in have and thread_ids:
            # PLAN  … FROM caducean_session_exits WHERE session_id IN (…) LIMIT 2000
            #       -> SEARCH caducean_session_exits USING INDEX idx_se_session (session_id=?)
            exits = {r[0]: r for r in con.execute(f"SELECT session_id, natural_exit, drift, conversation_id "
                                                  f"FROM caducean_session_exits WHERE session_id IN ({tph}) LIMIT 2000",
                                                  thread_ids)}
        titles: dict[str, str] = {}
        conv_of = {t: (exits[t][3] if t in exits and exits[t][3] else t) for t in thread_ids}
        messages: dict[str, list] = {}
        children: dict[str, list] = {}
        with _optional_chat_store(conv_db if conv_db else (Path(db).with_name("conversations.db") if db else None)) as cdb:
            if cdb is not None:
                ids = list(thread_ids) + [e[3] for e in exits.values() if e[3]]
                # PLAN  … FROM conversations WHERE id IN (…) LIMIT 4000
                #       -> SEARCH conversations USING INDEX sqlite_autoindex_conversations_1 (id=?)
                for r in cdb.execute(f"SELECT id, title FROM conversations WHERE id IN ({_marks(len(ids))}) LIMIT 4000", ids):
                    if r[1]:
                        titles[r[0]] = r[1]
                # the conversation strands of the tunnel: its messages (a short preview, never the whole text) and the
                # strands forked from it (parent_id)
                for t in thread_ids:
                    cid = conv_of[t]
                    # PLAN  … FROM messages WHERE conversation_id = ? ORDER BY timestamp LIMIT 80
                    #       -> SEARCH messages USING INDEX idx_messages_conv (conversation_id=?) + TEMP B-TREE
                    for r in cdb.execute("SELECT role, timestamp, substr(text, 1, ?), length(text) FROM messages "
                                         "WHERE conversation_id = ? ORDER BY timestamp LIMIT ?",
                                         (PREVIEW_MESSAGE, cid, MESSAGES_CAP)):
                        messages.setdefault(t, []).append({"role": "user" if r[0] == "user" else "iris", "ts": ts_of(r[1]),
                                                           "text": r[2], "len": r[3] or 0})
                    # PLAN  … FROM conversations WHERE parent_id = ? LIMIT 6 -> SEARCH … USING INDEX idx_conversations_parent
                    for r in cdb.execute("SELECT id, title, created_at, updated_at FROM conversations WHERE parent_id = ? "
                                         "LIMIT 6", (cid,)):
                        children.setdefault(t, []).append({"id": r[0], "title": r[1], "started": ts_of(r[2]),
                                                           "ended": ts_of(r[3])})
            else:
                warnings.append("data/conversations.db not found: session titles fall back to thread ids")
        sessions = []
        now = time.time()
        for t in thread_ids:
            rows = by_thread[t]
            x = exits.get(t)
            title = titles.get(t) or (titles.get(x[3]) if x and x[3] else None) or pretty_thread(t)
            started, ended = rows[-1]["ts"], rows[0]["ts"]
            live = now - ended < 600
            sessions.append({"id": t, "objective": title, "started": started, "ended": None if live else ended,
                             "exit": "live" if live else ("drift" if x and x[2] and not x[1] else "natural"),
                             "traj": traj.get(t, []), "eval": t.startswith(EVAL_THREAD_PREFIX), "episodes": [],
                             "messages": [m for m in messages.get(t, []) if m["ts"]], "strands": children.get(t, [])})

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

        # ⑦ pins (MEMORY-FOUNDATION-ANALYSIS 13.3): explicit memory, held not earned. 0 rows today: the page then shows
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

        # ⑩ recalls: what the memory gave the agent on each step of a turn (RECALL_DELIVERED, typed by
        # agent_kernel._der_recall_delivered) and whether it helped (RECALL_HELPED / RECALL_MISLED, same recall_trace_id).
        # refs are DER chain ids: resolved to the prior step they name (its thread, what it did, its tool, its result) - a
        # short insight only, never the content.
        traces: dict[str, dict] = {}
        if "memory_events" in have:
            rec_where = "" if include_eval else "AND thread_id NOT LIKE 'eval-%'"
            # PLAN  … FROM memory_events WHERE family = 'memory' AND label IN (…) [AND …] ORDER BY ts DESC LIMIT 8000
            #       -> SEARCH memory_events USING INDEX idx_memory_events_label (family=? AND label=?) + TEMP B-TREE FOR
            #          ORDER BY. The RECALL_* labels all live in family 'memory' (closed alphabet, EVENT_TAXONOMY); naming
            #          it lets the label index answer, where label alone would SCAN the table in ts order.
            for r in con.execute("SELECT ts, label, episode_id, step_index, thread_id, links, payload FROM memory_events "
                                 f"WHERE family = 'memory' AND label IN ({_marks(len(RECALL_LABELS))}) {rec_where} "
                                 "ORDER BY ts DESC LIMIT ?", RECALL_LABELS + (SNAPSHOT_RECALL_ROWS,)):
                tid = (jload(r["links"], {}) or {}).get("recall_trace_id")
                if not tid:
                    continue
                t = traces.setdefault(tid, {"outcome": None})
                if r["label"] == "RECALL_DELIVERED":
                    p = jload(r["payload"], {}) or {}
                    t.update(turn=r["episode_id"], session=r["thread_id"], step=r["step_index"], ts=r["ts"],
                             source=p.get("source") or "neighbors", refs=[x for x in (p.get("refs") or []) if x][:5])
                else:
                    t["outcome"] = "helped" if r["label"] == "RECALL_HELPED" else "misled"
        by_turn: dict[str, list] = {}
        for t in traces.values():
            if t.get("turn"):
                by_turn.setdefault(t["turn"], []).append(t)
        turn_ids = sorted(by_turn, key=lambda k: max(x["ts"] for x in by_turn[k]), reverse=True)[:SNAPSHOT_RECALL_TURNS]
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

    oracle = _snap_oracle(warnings)
    return {"meta": {"source": "data/memory.db (read-only snapshot)", "generated": time.time(), "counts": counts,
                     "eval_share": eval_share, "warnings": warnings, "available": available},
            "famCounts": fam_counts, "domCounts": dom_counts, "sessions": sessions, "events": out_events,
            "landmarks": landmarks, "edges": edges, "episodes": episodes, "artifacts": artifacts,
            "oracle": oracle, "mind": [], "sectors": sectors, "pins": pins, "spaces": spaces,
            "nodes": nodes, "nodeEdges": node_edges, "quorum": quorum, "recalls": recalls}

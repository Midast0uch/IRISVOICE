"""Export a bounded, read-only snapshot of IRIS app memory for the Memory Cortex mockup.

    python docs/Design/Memory-Cortex/export_snapshot.py            # all recent threads
    python docs/Design/Memory-Cortex/export_snapshot.py --no-eval  # skip eval-* threads
    python docs/Design/Memory-Cortex/export_snapshot.py --db C:/dev/IRISVOICE/data/memory.db  # explicit store

Writes docs/Design/Memory-Cortex/memory-snapshot.js (window.IRIS_MEMORY = {...}); open
index.html?real to view it. The snapshot holds personal memory: it is git-ignored and must not
be published or committed.

Optional tables a newer build adds (sectors, pins, the quorum log) and optional columns an older
store lacks (source_channel, render_order, write_lock) are detected with PRAGMA table_info; a missing
one is read as "none", never an error. meta.available lists what was found.

Rules (MEMORY-DASHBOARD-DESIGN.md section 3): read-only URI connections, LIMIT on every row
query, no blobs or embeddings, references only. Every value is mapped into the dashboard's
plain vocabulary here so the page never sees column names.
"""
from __future__ import annotations

import argparse
import calendar
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from _app_store import app_store_path  # noqa: E402  (the one store resolver for scripts)

OUT = Path(__file__).with_name("memory-snapshot.js")
CONV_DB = ROOT / "data" / "conversations.db"
BAR = ROOT / "benchmarks" / "consumer_bar_record.json"

# landmark evidence is written with its own words; map them onto the closed alphabet
LM_EVIDENCE = {"task_complete": "completion", "test_pass": "test", "recurrence": "recurrence",
               "user": "user", "corroboration": "corroboration", "verifier": "verifier",
               "claim": "claim", "completion": "completion", "test": "test"}
# the topic-domain registry (memory_chain.topic_domain values): a pin may name one in its tags
DOM_KEYS = ["general", "web", "science", "data", "finance", "ai", "design", "mobile", "systems", "devops", "security", "hardware"]
FAMILIES = ["intent", "control", "problem", "knowledge", "feedback", "delivery", "memory", "safety", "environment"]
DOC_KIND = {"image": "image", "research": "web", "json": "doc", "markdown": "doc", "code": "code", "document": "doc",
            "video": "video", "audio": "audio"}
DOC_FOLDER = {"research": "research records", "json": "structured data", "markdown": "notes", "image": "images"}


def ro(path: Path | str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def ts_of(v) -> float | None:
    """Tables mix epoch floats and 'YYYY-MM-DD HH:MM:SS' (UTC) strings; return epoch seconds."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return float(calendar.timegm(time.strptime(str(v)[:26].rstrip("Z"), fmt)))
        except ValueError:
            continue
    return None


def jload(s, default):
    try:
        return json.loads(s) if s else default
    except (TypeError, ValueError):
        return default


def table_cols(con: sqlite3.Connection, name: str) -> set[str]:
    """Column names of a table, empty when the table does not exist (tables a newer build adds:
    sectors, pins, the quorum log; columns an older store lacks: source_channel, render_order)."""
    return {r[1] for r in con.execute(f"PRAGMA table_info({name})")}


def pick_cols(have: set[str], want: tuple[str, ...]) -> str:
    """SELECT list of the wanted columns; one the store lacks is read as NULL."""
    return ", ".join(c if c in have else f"NULL AS {c}" for c in want)


def clip(v, n: int = 80):
    return None if v is None else str(v)[:n]


def pretty_thread(tid: str) -> str:
    if tid.startswith("eval-"):
        core = tid[5:].rsplit("-", 1)[0]
        return "test run · " + core.replace("_", " ")
    return tid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-eval", action="store_true", help="leave out eval-* threads")
    ap.add_argument("--threads", type=int, default=48)
    ap.add_argument("--db", help="read this store instead of the configured one (a git worktree has no data/)")
    ap.add_argument("--events", type=int, default=6000)
    args = ap.parse_args()
    warnings: list[str] = []
    store = args.db or app_store_path()
    conv_db = Path(args.db).with_name("conversations.db") if args.db else CONV_DB
    con = ro(store)
    try:
        q = lambda sql, p=(): con.execute(sql, p).fetchall()  # noqa: E731
        counts = {
            "events": q("SELECT COUNT(*) FROM memory_events")[0][0],
            "chain": q("SELECT COUNT(*) FROM memory_chain")[0][0],
            "landmarks": q("SELECT COUNT(*) FROM mycelium_landmarks WHERE COALESCE(absorbed,0)=0")[0][0],
            "landmarks_absorbed": q("SELECT COUNT(*) FROM mycelium_landmarks WHERE absorbed=1")[0][0],
            "edges": q("SELECT COUNT(*) FROM mycelium_landmark_edges")[0][0],
            "merges": q("SELECT COUNT(*) FROM mycelium_landmark_merges")[0][0],
            "episodes": q("SELECT COUNT(*) FROM episodes")[0][0],
            "fragments": q("SELECT COUNT(*) FROM context_chunks")[0][0],
            "artifacts": q("SELECT COUNT(*) FROM document_data")[0][0],
        }
        fam_counts = {r[0]: r[1] for r in q("SELECT family, COUNT(*) FROM memory_events GROUP BY family")}
        # territories of the lattice: topic domains. memory_chain is the only table that carries them
        # in volume (2026-10-18: memory_events ~90% NULL); NULL counts as "general"
        dom_counts: Counter = Counter()
        for tbl in ("memory_chain", "memory_events"):
            for r in q(f"SELECT COALESCE(topic_domain, 'general'), COUNT(*) FROM {tbl} GROUP BY 1"):
                dom_counts[r[0]] += r[1]
        eval_share = q("SELECT SUM(thread_id LIKE 'eval-%'), COUNT(*) FROM memory_events")[0]

        # ── events (newest first, bounded) and the threads they belong to
        where = "WHERE thread_id NOT LIKE 'eval-%'" if args.no_eval else ""
        ev_rows = q(f"SELECT event_id, ts, family, label, valence, actor, evidence, episode_id, thread_id, links, payload, topic_domain "
                    f"FROM memory_events {where} ORDER BY ts DESC LIMIT ?", (args.events,))
        by_thread: dict[str, list] = defaultdict(list)
        for r in ev_rows:
            if r["thread_id"]:
                by_thread[r["thread_id"]].append(r)
        threads = sorted(by_thread, key=lambda t: by_thread[t][0]["ts"], reverse=True)[: args.threads]
        counts["sessions"] = q("SELECT COUNT(DISTINCT thread_id) FROM memory_events")[0][0]

        # ── landmarks that are still live (absorbed ones were merged into a survivor)
        lm_rows = q("SELECT landmark_id, label, task_class, micro_abstract_text, tier, is_permanent, evidence, "
                    "activation_count, contradictions, last_activated, last_verified, created_at, conversation_ref "
                    "FROM mycelium_landmarks WHERE COALESCE(absorbed,0)=0 ORDER BY created_at DESC LIMIT 400")
        lm_ids = [r["landmark_id"] for r in lm_rows]
        lm_index = {lid: i for i, lid in enumerate(lm_ids)}
        lm_fams: dict[str, Counter] = defaultdict(Counter)
        events = []
        for t in threads:
            for r in by_thread[t][:400]:
                links, payload = jload(r["links"], {}), jload(r["payload"], {})
                # LANDMARK_* events name their landmark in the payload; RECALL_* events do not name one
                lid = ((links.get("landmark_id") or links.get("landmark")) if isinstance(links, dict) else None) or \
                      (payload.get("landmark") if isinstance(payload, dict) else None)
                if lid in lm_index:
                    lm_fams[lid][r["family"]] += 1
                events.append({"id": r["event_id"], "ts": r["ts"], "family": r["family"], "label": r["label"],
                               "valence": r["valence"], "actor": r["actor"], "evidence": r["evidence"],
                               "episode": r["episode_id"], "session": t, "domain": r["topic_domain"] or "general",
                               "landmark": lid if lid in lm_index else None})
        landmarks = []
        for r in lm_rows:
            ev = []
            kinds = Counter()
            for e in jload(r["evidence"], [])[-400:]:
                k = LM_EVIDENCE.get(str(e.get("kind")), "claim")
                kinds[k] += 1
                if kinds[k] <= 4:  # the page shows counts; keep a few dated entries per kind
                    ev.append({"kind": k, "at": ts_of(e.get("at")), "session": e.get("session")})
            text = r["micro_abstract_text"] or (r["label"] or "").replace("_", " ")
            fams = [FAMILIES.index(f) for f, _ in lm_fams[r["landmark_id"]].most_common(3) if f in FAMILIES] or [3, 6]
            landmarks.append({"id": r["landmark_id"], "claim": text, "cls": r["task_class"] or "other",
                              "tier": r["tier"] or "candidate", "permanent": bool(r["is_permanent"]), "evidence": ev,
                              "evidence_counts": dict(kinds), "activations": r["activation_count"] or 0,
                              "contradictions": r["contradictions"] or 0,
                              "last_activated": ts_of(r["last_activated"]), "last_verified": ts_of(r["last_verified"]),
                              "born": ts_of(r["created_at"]), "session": r["conversation_ref"], "fams": fams,
                              "domain": "general"})  # landmarks carry no domain column yet
        if not any(r["micro_abstract_text"] for r in lm_rows):
            warnings.append("no live landmark has micro_abstract_text")
        ph = ",".join("?" * len(lm_ids)) or "''"
        edges = [{"id": r[6], "a": lm_index[r[0]], "b": lm_index[r[1]], "score": r[2], "traversals": r[3], "hits": r[4],
                  "misses": r[5], "last": ts_of(r[7])}
                 for r in q(f"SELECT from_landmark_id, to_landmark_id, score, traversal_count, hit_count, miss_count, "
                            f"edge_id, last_traversed "
                            f"FROM mycelium_landmark_edges WHERE from_landmark_id IN ({ph}) AND to_landmark_id IN ({ph}) "
                            f"LIMIT 3000", lm_ids + lm_ids)]

        # ── Kyudo trust channel of a landmark: the highest channel that ever observed it, read from the
        # episode index (nodes.source_channel is the same value for a coordinate node). NULL on every row
        # = legacy internal; the page then draws the plain membrane.
        available: dict[str, bool] = {}
        ei_cols = table_cols(con, "mycelium_episode_index")
        available["landmark_channel"] = "source_channel" in ei_cols and "landmark_id" in ei_cols
        if available["landmark_channel"] and lm_ids:
            chan = {r[0]: r[1] for r in q(f"SELECT landmark_id, MAX(source_channel) FROM mycelium_episode_index "
                                          f"WHERE landmark_id IN ({ph}) AND source_channel IS NOT NULL GROUP BY landmark_id",
                                          lm_ids)}
            for lm in landmarks:
                lm["channel"] = chan.get(lm["id"])

        # ── sectors: territories read from the registry when the tables exist (a newer build creates them);
        # the page falls back to the topic-domain territories otherwise. Roots are big, children nested.
        sectors: list[dict] = []
        sec_cols = table_cols(con, "mycelium_sectors")
        ls_cols = table_cols(con, "mycelium_landmark_sectors")
        available["sectors"] = bool(sec_cols)
        available["landmark_sectors"] = bool(ls_cols)
        if sec_cols and "sector_key" in sec_cols:
            want = ("sector_key", "parent_key", "label", "status", "members", "outside_evidence", "last_activity")
            sectors = [{"key": r["sector_key"], "parent": r["parent_key"] or None, "label": clip(r["label"], 60),
                        "status": r["status"] or "proven", "members": r["members"] or 0,
                        "evidence": r["outside_evidence"] or 0, "last": ts_of(r["last_activity"])}
                       for r in q(f"SELECT {pick_cols(sec_cols, want)} FROM mycelium_sectors "
                                  f"WHERE COALESCE(status, 'proven') != 'dissolved' LIMIT 200")]
        if sectors and {"landmark_id", "sector_key"} <= ls_cols and lm_ids:
            best: dict[str, tuple[float, str]] = {}
            for r in q(f"SELECT landmark_id, sector_key, {'weight' if 'weight' in ls_cols else '1.0'} "
                       f"FROM mycelium_landmark_sectors WHERE landmark_id IN ({ph}) LIMIT 5000", lm_ids):
                if r[0] not in best or (r[2] or 0) > best[r[0]][0]:
                    best[r[0]] = (r[2] or 0, r[1])
            parent = {s["key"]: s["parent"] for s in sectors}
            for lm in landmarks:
                if lm["id"] in best:
                    key = best[lm["id"]][1]
                    root, hops = key, 0
                    while parent.get(root) and hops < 6:
                        root, hops = parent[root], hops + 1
                    lm["sector"], lm["domain"] = key, root

        # ── sessions: one per thread, shaped by its Caducean trajectory
        tph = ",".join("?" * len(threads)) or "''"
        traj = defaultdict(list)
        for r in q(f"SELECT session_id, x, y, xi, u FROM caducean_trajectories WHERE session_id IN ({tph}) "
                   f"ORDER BY session_id, step_num LIMIT 6000", threads):
            if len(traj[r[0]]) < 80:
                traj[r[0]].append({"x": r[1] or 0.0, "y": r[2] or 0.0, "xi": r[3] or 0.0, "u": r[4] or 0.0})
        exits = {r[0]: r for r in q(f"SELECT session_id, natural_exit, drift, conversation_id FROM caducean_session_exits "
                                     f"WHERE session_id IN ({tph}) LIMIT 2000", threads)}
        titles: dict[str, str] = {}
        conv_of = {t: (exits[t][3] if t in exits and exits[t][3] else t) for t in threads}
        messages: dict[str, list] = defaultdict(list)
        children: dict[str, list] = defaultdict(list)
        if conv_db.exists():
            cdb = ro(conv_db)
            try:
                ids = list(threads) + [e[3] for e in exits.values() if e[3]]
                iph = ",".join("?" * len(ids)) or "''"
                for r in cdb.execute(f"SELECT id, title FROM conversations WHERE id IN ({iph}) LIMIT 4000", ids):
                    if r[1]:
                        titles[r[0]] = r[1]
                # the conversation strands of the tunnel: its messages (a short preview, never the
                # whole text) and the strands forked from it (parent_id)
                for t in threads:
                    cid = conv_of[t]
                    for r in cdb.execute("SELECT role, timestamp, substr(text, 1, 120), length(text) FROM messages "
                                         "WHERE conversation_id = ? ORDER BY timestamp LIMIT 80", (cid,)):
                        messages[t].append({"role": "user" if r[0] == "user" else "iris", "ts": ts_of(r[1]),
                                            "text": r[2], "len": r[3] or 0})
                    for r in cdb.execute("SELECT id, title, created_at, updated_at FROM conversations WHERE parent_id = ? "
                                         "LIMIT 6", (cid,)):
                        children[t].append({"id": r[0], "title": r[1], "started": ts_of(r[2]), "ended": ts_of(r[3])})
            finally:
                cdb.close()
        else:
            warnings.append("data/conversations.db not found: session titles fall back to thread ids")
        sessions = []
        now = time.time()
        for t in threads:
            rows = by_thread[t]
            x = exits.get(t)
            title = titles.get(t) or (titles.get(x[3]) if x and x[3] else None) or pretty_thread(t)
            started, ended = rows[-1]["ts"], rows[0]["ts"]
            live = now - ended < 600
            sessions.append({"id": t, "objective": title, "started": started, "ended": None if live else ended,
                             "exit": "live" if live else ("drift" if x and x[2] and not x[1] else "natural"),
                             "traj": traj.get(t, []), "eval": t.startswith("eval-"), "episodes": [],
                             "messages": [m for m in messages.get(t, []) if m["ts"]], "strands": children.get(t, [])})

        # ── episodes (task runs)
        episodes = []
        sess_ids = set(threads)
        for r in q("SELECT id, session_id, task_summary, outcome_type, outcome_score, failure_reason, user_corrected, "
                   "user_confirmed, duration_ms, tool_sequence, timestamp FROM episodes ORDER BY timestamp DESC LIMIT 300"):
            tools = [s.get("tool") for s in jload(r["tool_sequence"], []) if isinstance(s, dict) and s.get("tool")][:12]
            episodes.append({"id": r["id"], "session": r["session_id"], "summary": (r["task_summary"] or "")[:160],
                             "outcome": r["outcome_type"] or "partial", "score": r["outcome_score"] or 0.0,
                             "failure_reason": r["failure_reason"], "corrected": bool(r["user_corrected"]),
                             "confirmed": bool(r["user_confirmed"]), "duration": (r["duration_ms"] or 0) / 1000.0,
                             "tools": tools, "ts": ts_of(r["timestamp"])})
        for s in sessions:
            s["episodes"] = [e["id"] for e in episodes if e["session"] == s["id"]]
        episodes = [e for e in episodes if e["session"] in sess_ids]

        # ── things IRIS made (names and kinds only; no content, no blobs)
        artifacts = []
        for i, r in enumerate(q("SELECT document_id, conversation_id, fmt, kind, title, summary, created_at, capture_path "
                                "FROM document_data ORDER BY created_at DESC LIMIT 80")):
            kind = "screen" if r["capture_path"] else DOC_KIND.get(r["kind"] or "", DOC_KIND.get(r["fmt"] or "", "doc"))
            name = r["title"] or (r["summary"] or "")[:48] or f"{r['fmt'] or 'document'} · {str(r['document_id'])[:8]}"
            # layers: format comes from kind; the folder is where it was captured, else what it is
            folder = (Path(r["capture_path"]).parent.name if r["capture_path"] else None) or DOC_FOLDER.get(r["fmt"] or "", r["fmt"] or "unsorted")
            artifacts.append({"id": r["document_id"], "kind": kind, "name": name, "folder": folder, "session": r["conversation_id"],
                              "ts": ts_of(r["created_at"]), "weight": 1.0, "seed": i + 1})

        # ── pins (MEMORY-FOUNDATION-ANALYSIS 13.3): explicit memory, held not earned. 0 rows today: the page
        # then shows none. "held in context" has no stored flag yet; the 'held' / 'context' tag stands in.
        pins: list[dict] = []
        pin_cols = table_cols(con, "mycelium_pins")
        available["pins"] = bool(pin_cols)
        if pin_cols:
            want = ("pin_id", "title", "pin_type", "tags", "file_refs", "image_refs", "url_refs", "project_id",
                    "created_at", "is_permanent")
            prow = q(f"SELECT {pick_cols(pin_cols, want)} FROM mycelium_pins ORDER BY created_at DESC LIMIT 200")
            pids = [r["pin_id"] for r in prow]
            links_of: dict[str, list] = defaultdict(list)
            if pids and table_cols(con, "mycelium_pin_links"):
                pph = ",".join("?" * len(pids))
                for r in q(f"SELECT source_type, source_id, target_type, target_id, relationship FROM mycelium_pin_links "
                           f"WHERE (source_type = 'pin' AND source_id IN ({pph})) OR (target_type = 'pin' AND target_id IN ({pph})) "
                           f"LIMIT 4000", pids + pids):
                    mine, other = (r[1], (r[2], r[3])) if r[0] == "pin" else (r[3], (r[0], r[1]))
                    links_of[mine].append({"t": other[0], "id": other[1], "rel": r[4]})
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

        # ── coordinate spaces (registry) and the nodes in them: layers, with trust channel and confidence
        spaces: list[dict] = []
        nodes: list[dict] = []
        node_edges: list[dict] = []
        sp_cols = table_cols(con, "mycelium_spaces")
        available["spaces"] = bool(sp_cols)
        if sp_cols:
            want = ("space_id", "description", "active", "write_lock", "render_order", "position")
            spaces = [{"id": r["space_id"], "description": clip(r["description"], 120), "active": bool(r["active"] if r["active"] is not None else 1),
                       "write_lock": r["write_lock"], "render_order": r["render_order"], "position": r["position"]}
                      for r in q(f"SELECT {pick_cols(sp_cols, want)} FROM mycelium_spaces LIMIT 40")]
        nd_cols = table_cols(con, "mycelium_nodes")
        available["node_channel"] = "source_channel" in nd_cols
        if nd_cols:
            want = ("node_id", "space_id", "label", "confidence", "source_channel", "created_at", "updated_at", "access_count")
            nrows = q(f"SELECT {pick_cols(nd_cols, want)} FROM mycelium_nodes ORDER BY updated_at DESC LIMIT 600")
            nidx = {r["node_id"]: i for i, r in enumerate(nrows)}
            nodes = [{"id": r["node_id"], "space": r["space_id"], "label": clip(r["label"], 48),
                      "conf": r["confidence"] if r["confidence"] is not None else 0.5, "chan": r["source_channel"],
                      "born": ts_of(r["created_at"]), "used": r["access_count"] or 0} for r in nrows]
            ne_cols = table_cols(con, "mycelium_edges")
            if ne_cols and nidx:
                want = ("from_node_id", "to_node_id", "score", "traversal_count", "observation_count", "last_traversed")
                for r in q(f"SELECT {pick_cols(ne_cols, want)} FROM mycelium_edges LIMIT 4000"):
                    if r["from_node_id"] in nidx and r["to_node_id"] in nidx:
                        node_edges.append({"a": nidx[r["from_node_id"]], "b": nidx[r["to_node_id"]], "score": r["score"] or 0.0,
                                           "traversals": r["traversal_count"] or 0, "observations": r["observation_count"] or 0,
                                           "last": ts_of(r["last_traversed"])})

        # ── immune response (Kyudo): the durable quorum log. A live row (shadow=0) is a signal that counted;
        # shadow=1 rows are measured only; quorum_reorganization_reset is the region relaxing. The landmark a
        # signal names (activation anomaly) or the session it came from tells the page which territory it touched.
        quorum: list[dict] = []
        qc = table_cols(con, "mycelium_quorum_log")
        available["quorum"] = bool(qc)
        if qc:
            want = ("ts", "session_id", "signal_type", "weight", "threat_after", "shadow", "detail")
            for r in q(f"SELECT {pick_cols(qc, want)} FROM mycelium_quorum_log ORDER BY ts DESC LIMIT 80"):
                m = re.search(r"landmark=(\S+)", r["detail"] or "")
                quorum.append({"ts": r["ts"], "session": r["session_id"] or None, "signal": r["signal_type"],
                               "weight": r["weight"] or 0.0, "threat": r["threat_after"], "shadow": bool(r["shadow"]),
                               "landmark": m.group(1) if m else None})
            quorum.reverse()
    finally:
        con.close()

    oracle = []
    try:
        for cid, v in json.loads(BAR.read_text(encoding="utf-8")).items():
            oracle.append({"consumer": cid, "state": v.get("status", "shadow"), "rows": v.get("rows") or 0,
                           "auroc": v.get("auroc") or 0.5, "ece": v.get("ece"), "precision": v.get("precision") or 0.0})
    except (OSError, ValueError) as exc:
        warnings.append(f"consumer bar record unreadable: {exc}")

    snap = {"meta": {"source": "data/memory.db (read-only snapshot)", "generated": time.time(), "counts": counts,
                     "eval_share": [eval_share[0] or 0, eval_share[1] or 0], "warnings": warnings, "available": available},
            "famCounts": fam_counts, "domCounts": dict(dom_counts), "sessions": sessions, "events": events, "landmarks": landmarks, "edges": edges,
            "episodes": episodes, "artifacts": artifacts, "oracle": oracle, "mind": [],
            "sectors": sectors, "pins": pins, "spaces": spaces, "nodes": nodes, "nodeEdges": node_edges, "quorum": quorum}
    OUT.write_text("window.IRIS_MEMORY = " + json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    print(f"[export_snapshot] wrote {OUT.name}: {len(sessions)} sessions, {len(events)} events, "
          f"{len(landmarks)} live landmarks, {len(edges)} edges, {len(episodes)} episodes, {len(artifacts)} artifacts, "
          f"{len(oracle)} decision points; {len(pins)} pins, {len(nodes)} nodes, {len(node_edges)} node edges, "
          f"{len(spaces)} spaces, {len(sectors)} sectors, {len(quorum)} quorum rows; "
          f"tables={available}; warnings={warnings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

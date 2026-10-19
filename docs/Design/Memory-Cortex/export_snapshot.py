"""Export a bounded, read-only snapshot of IRIS app memory for the Memory Cortex mockup.

    python docs/Design/Memory-Cortex/export_snapshot.py            # all recent threads
    python docs/Design/Memory-Cortex/export_snapshot.py --no-eval  # skip eval-* threads

Writes docs/Design/Memory-Cortex/memory-snapshot.js (window.IRIS_MEMORY = {...}); open
index.html?real to view it. The snapshot holds personal memory: it is git-ignored and must not
be published or committed.

Rules (MEMORY-DASHBOARD-DESIGN.md section 3): read-only URI connections, LIMIT on every row
query, no blobs or embeddings, references only. Every value is mapped into the dashboard's
plain vocabulary here so the page never sees column names.
"""
from __future__ import annotations

import argparse
import calendar
import json
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


def pretty_thread(tid: str) -> str:
    if tid.startswith("eval-"):
        core = tid[5:].rsplit("-", 1)[0]
        return "test run · " + core.replace("_", " ")
    return tid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-eval", action="store_true", help="leave out eval-* threads")
    ap.add_argument("--threads", type=int, default=48)
    ap.add_argument("--events", type=int, default=6000)
    args = ap.parse_args()
    warnings: list[str] = []
    store = app_store_path()
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
        edges = [{"a": lm_index[r[0]], "b": lm_index[r[1]], "score": r[2], "traversals": r[3], "hits": r[4], "misses": r[5]}
                 for r in q(f"SELECT from_landmark_id, to_landmark_id, score, traversal_count, hit_count, miss_count "
                            f"FROM mycelium_landmark_edges WHERE from_landmark_id IN ({ph}) AND to_landmark_id IN ({ph}) "
                            f"LIMIT 3000", lm_ids + lm_ids)]

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
        if CONV_DB.exists():
            cdb = ro(CONV_DB)
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
                     "eval_share": [eval_share[0] or 0, eval_share[1] or 0], "warnings": warnings},
            "famCounts": fam_counts, "domCounts": dict(dom_counts), "sessions": sessions, "events": events, "landmarks": landmarks, "edges": edges,
            "episodes": episodes, "artifacts": artifacts, "oracle": oracle, "mind": []}
    OUT.write_text("window.IRIS_MEMORY = " + json.dumps(snap, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    print(f"[export_snapshot] wrote {OUT.name}: {len(sessions)} sessions, {len(events)} events, "
          f"{len(landmarks)} live landmarks, {len(edges)} edges, {len(episodes)} episodes, {len(artifacts)} artifacts, "
          f"{len(oracle)} decision points; warnings={warnings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

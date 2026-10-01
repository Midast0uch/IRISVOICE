#!/usr/bin/env python3
"""Replay recorded DER sessions through the REAL Caducean engine under an action rule.

CLAUDE.md "REPLAY BEFORE YOU SWITCH": a physics change runs offline over recorded
traces, and its VALUES are read as distributions, before it goes live. The K4 change
(adbf69f8) passed a replay built on recorded TOOL NAMES and failed live, because a
coding step is a NODE with no single tool (every step read COMPRESS). This replay
takes each step's inner tool calls from the ledger (system_events tool_execution rows
between the step's trajectory timestamps), so node steps are classified by what they
actually did.

Rules compared (the step's action and balance fed to ffi_caducean_update):
  current    - live today: 1 for run_command/git_commit/git_push, 2 on failure, else
               0; balance = clamp(SQL EML) = 3.0 (the measured constant).
  k4         - adbf69f8: no tool -> COMPRESS; v2 state EML / 2.3418.
  node_calls - redo: a node step COMPRESSES when one of its calls consolidated
               (wrote, edited, ran, committed), EXPANDS when it only gathered;
               failure expands; v2 state EML / 2.3418.

The engine runs against a TEMPORARY empty store (never the live one). Read-only on
the live store. Simplification, stated: the live loop also applies parameter
homeostasis and the trajectory controller between steps; this replay does not.

Usage: python scripts/replay_sigma.py [--since "2026-10-01"] [--like "eval-c%"]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sqlite3
import statistics
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "scripts"))

CONSOLIDATING = frozenset({
    "write_file", "edit_file", "create_directory", "run_command", "git_commit",
    "git_push", "render_document", "create_artifact", "save_memory",
})
GATHER = frozenset({
    "crawler_query", "search", "web_search", "read_file", "list_directory",
    "get_rendered_documents", "get_system_info", "glob_files", "grep_files",
    "recall_memory", "recall_research", "vision_analyze_screen", "take_screenshot",
    "read_shell_output", "open_url", "list_conversations", "git_log", "git_status",
    "git_diff", "browser_open", "browser_observe", "browser_explore",
})


def action_node_calls(tool, success, calls) -> int:
    """THE live rule (backend/agent/physics_action.py) - one copy, imported."""
    from backend.agent.physics_action import step_action

    return step_action(tool, success, calls)


def action_k4(tool, success, calls) -> int:
    if not success:
        return 0
    return 0 if (tool or "none") in GATHER else 1


def action_current(tool, success, calls) -> int:
    if tool in ("run_command", "git_commit", "git_push"):
        return 1
    return 2 if not success else 0


def _epoch(created_at: str) -> float:
    return dt.datetime.strptime(created_at[:19], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=dt.timezone.utc).timestamp()


def load_sessions(like: str, since: str):
    from _app_store import app_store_path

    c = sqlite3.connect(f"file:{app_store_path()}?mode=ro", uri=True)
    since_ts = dt.datetime.fromisoformat(since).timestamp()
    sids = [r[0] for r in c.execute(
        "SELECT DISTINCT session_id FROM caducean_trajectories "
        "WHERE session_id LIKE ? AND ts >= ?", (like, since_ts))]
    sessions = {}
    for sid in sids:
        steps = c.execute(
            "SELECT step_num, ts, outcome FROM caducean_trajectories "
            "WHERE session_id=? ORDER BY ts", (sid,)).fetchall()
        events = []
        for ca, out, p in c.execute(
                "SELECT created_at, outcome, interaction_payload FROM system_events "
                "WHERE session_id=? AND event_type='tool_execution' ORDER BY created_at",
                (sid,)):
            try:
                tool = json.loads(p or "{}").get("tool")
            except ValueError:
                continue
            if not tool or tool == "no_tool" or out == "shadow":
                continue
            events.append((_epoch(ca), tool, out in ("success", "reason")))
        rows, prev = [], 0.0
        for num, ts, outcome in steps:
            calls = [(t, ok) for (e, t, ok) in events if prev < e <= ts + 1.0]
            ok = str(outcome or "").upper() not in ("FAILED", "FAIL", "FAILURE", "ERROR")
            rows.append((calls, ok))
            prev = ts + 1.0
        sessions[sid] = rows
    c.close()
    return sessions


def replay(sessions, rule, use_v2_eml: bool, tag: str):
    from backend.gateway import iris_ffi as ffi

    acts, recs, xis, dxi, final_rec, balances = [], [], set(), [], [], []
    for sid, rows in sessions.items():
        rid = f"replay-{tag}-{sid}"
        ffi.ffi_caducean_init_session(rid, 1, 1)
        last_xi = 0.0
        for calls, ok in rows:
            a = rule(None, ok, calls)
            if use_v2_eml:
                score, _x, _y = ffi.ffi_caducean_calculate_eml(rid)
                bal = max(0.1, min(3.0, score / 2.3418))
            else:
                bal = 3.0
            ffi.ffi_caducean_update(rid, a, bal)
            rec = ffi.ffi_caducean_recommend(rid)
            st = ffi.ffi_caducean_get_state(rid) or {}
            xi = float(st.get("xi", 0.0))
            acts.append(a); recs.append(rec); balances.append(bal)
            xis.add(round(xi, 4)); dxi.append(round((xi - last_xi) % 6.2832, 3))
            last_xi = xi
        if rows:
            final_rec.append(rec)
    n = len(acts)
    return {
        "steps": n,
        "action_mix": dict(collections.Counter(acts)),
        "rec_mix": dict(collections.Counter(recs)),
        "final_step_rec_mix": dict(collections.Counter(final_rec)),
        "distinct_xi": len(xis),
        "distinct_xi_step": len(set(dxi)),
        "balance_at_clamp_share": round(sum(1 for b in balances if b >= 3.0) / max(1, n), 3),
        "balance_p50": round(statistics.median(balances), 3) if balances else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-10-01")
    ap.add_argument("--like", default="eval-c%")
    args = ap.parse_args()
    sessions = load_sessions(args.like, args.since)
    with_calls = sum(1 for r in sessions.values() for calls, _ in r if calls)
    total = sum(len(r) for r in sessions.values())
    print(f"sessions={len(sessions)} steps={total} steps_with_inner_calls={with_calls}")

    from backend.gateway import iris_ffi as ffi

    tmp = Path(tempfile.mkdtemp(prefix="replay_sigma_")) / "replay.db"
    ffi.ffi_init_engine(str(tmp), "00" * 32)  # temp store only
    out = {}
    for tag, rule, v2 in (("current", action_current, False),
                          ("k4", action_k4, True),
                          ("node_calls", action_node_calls, True)):
        out[tag] = replay(sessions, rule, v2, tag)
        print(tag, json.dumps(out[tag]))
    ffi.ffi_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

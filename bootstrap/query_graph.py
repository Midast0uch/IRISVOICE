#!/usr/bin/env python3
"""
query_graph.py — Navigate the coordinate knowledge graph.

This is not a log viewer. It is a navigation instrument.

The coordinate graph is the semantic memory of the codebase — it encodes
what is currently true about each file, not just what happened to it.
Read it before touching anything. Let the pheromone trails guide you.

  SEMANTIC layer (what IS true — compressed, precise, always current):
    --file    Show topology primitive, trajectory, confidence, and routes
    --routes  Show globally strongest pheromone paths
    --summary Graph statistics + crystallization status

  EPISODIC layer (what HAPPENED — grows every session, decays over time):
    --recent    Last N events across all agents
    --agent X   Trail for a specific agent
    --landmark  Events linked to a landmark

  ANALYSIS:
    --failures  High-signal failures (score >= 0.5) — future success candidates

Usage:
  python bootstrap/query_graph.py --file backend/agent/agent_kernel.py
  python bootstrap/query_graph.py --routes
  python bootstrap/query_graph.py --recent
  python bootstrap/query_graph.py --failures
  python bootstrap/query_graph.py --agent claude_main
  python bootstrap/query_graph.py --summary
"""

import sys
import os
import argparse
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coordinates import (
    CoordinateStore, CHART_ACTIVATION_THRESHOLD,
    HIGH_POTENTIAL_FAILURE_THRESHOLD, EDGE_WEIGHT_MAX,
)


def fmt_time(ts):
    if not ts:
        return "never"
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def fmt_score(score) -> str:
    """Visual indicator of event signal quality."""
    if score is None:
        return "   "
    s = float(score)
    if s >= 0.80:
        return f"[{s:.2f}]"
    if s >= 0.50:
        return f"[{s:.2f}]"  # high-potential failure if outcome=fail
    return f"[{s:.2f}]"


def fmt_event(e):
    outcome = f" [{e['outcome']}]" if e.get("outcome") else ""
    file_part = f" {e['file_path']}" if e.get("file_path") else ""
    score_part = f" score:{e['score']:.2f}" if e.get("score") is not None else ""
    return (
        f"  {fmt_time(e['created_at'])} | {e['event_type']}{outcome}{score_part} "
        f"| {e['agent_id']}{file_part}\n"
        f"    {e['description'][:100]}"
    )


def z_symbol(z) -> str:
    """Direction of travel indicator."""
    if z is None:
        return "→"
    z = float(z)
    if z >= 0.08:
        return "↑"   # ACQUIRING — converging toward mastery
    if z <= -0.06:
        return "↓"   # EVOLVING — diverging, being replaced
    return "→"       # stable — CORE or ORBIT


def primitive_color(primitive: str) -> str:
    """Short label for each primitive."""
    return {
        "CORE":        "CORE       ",
        "ACQUISITION": "ACQUIRING  ",
        "EXPLORATION": "EXPLORING  ",
        "EVOLUTION":   "EVOLVING   ",
        "ORBIT":       "ORBIT      ",
        "UNKNOWN":     "UNKNOWN    ",
    }.get(primitive, f"{primitive:<11}")


def main():
    parser = argparse.ArgumentParser(
        description="Navigate the IRIS coordinate knowledge graph"
    )
    parser.add_argument("--file", default=None,
                        help="Show topology + history for a specific file")
    parser.add_argument("--routes", action="store_true",
                        help="Show globally strongest pheromone paths")
    parser.add_argument("--recent", action="store_true",
                        help="Show N most recent events (episodic layer)")
    parser.add_argument("--failures", action="store_true",
                        help=f"Show high-signal failures (score >= {HIGH_POTENTIAL_FAILURE_THRESHOLD})")
    parser.add_argument("--agent", default=None,
                        help="Show trail for a specific agent")
    parser.add_argument("--landmark", default=None,
                        help="Show events linked to a landmark")
    parser.add_argument("--summary", action="store_true",
                        help="Graph summary + crystallization status")
    parser.add_argument("--limit", type=int, default=10,
                        help="Max results to show")
    args = parser.parse_args()

    store = CoordinateStore()

    # ── SEMANTIC HEADER — always shown first ──────────────────────────────────
    try:
        header = store.get_semantic_header()
        print(header)
        print()
    except Exception:
        pass

    # ── FILE — semantic + episodic for one file ───────────────────────────────
    if args.file:
        print(f"=== {args.file} ===")

        node = store.get_file_node(args.file)
        if node:
            primitive = store.classify_topology_primitive(args.file)
            z = node.get("z_trajectory") or 0.0
            conf = node.get("confidence") or 0.0
            act = node.get("activation_count") or 0
            edit_count = node.get("edit_count") or 0

            # Topology position (semantic layer)
            print(f"Topology:  {primitive_color(primitive)} "
                  f"{z_symbol(z)} z:{z:+.3f}  conf:{conf:.2f}  "
                  f"activations:{act}/{CHART_ACTIVATION_THRESHOLD}")
            if act >= CHART_ACTIVATION_THRESHOLD:
                print("           [*] CRYSTALLIZATION CANDIDATE — this node is permanent-ready")
            print(f"Language:  {node.get('language', '?')} | "
                  f"Edits: {edit_count} | "
                  f"Last agent: {node.get('last_agent', '?')} | "
                  f"Last edited: {fmt_time(node.get('last_edited'))}")
            if node.get("purpose"):
                print(f"Purpose:   {node['purpose']}")
            if node.get("owning_landmark"):
                print(f"Landmark:  {node['owning_landmark']}")
        else:
            print("(no file node yet — not tracked)")

        # Pheromone routes from this file
        print()
        print("Pheromone routes (strongest connected paths):")
        routes = store.get_pheromone_routes(from_file=args.file, limit=5)
        if routes:
            for r in routes:
                src = r.get("source_path") or r.get("source_id", "?")
                tgt = r.get("target_path") or r.get("target_id", "?")
                w = r.get("weight", 1.0)
                rel = r.get("relationship", "→")
                n = r.get("compound_count", 0)
                print(f"  [{w:.1f}x/{n}runs] {src} --{rel}--> {tgt}")
        else:
            print("  (no edges recorded yet)")

        # Related tests
        print()
        print("Test coverage:")
        tests = store.get_related_tests(args.file)
        if tests:
            for t in tests:
                pct = f"{t['pass_count']}/{t['total_runs']}" if t["total_runs"] else "0/0"
                print(f"  {t['test_file']} — {pct} pass | "
                      f"last: {t.get('last_outcome','?')} @ {fmt_time(t.get('last_run'))}")
        else:
            print("  (none recorded)")

        # Episodic history (secondary)
        print()
        print(f"Event history (last {args.limit}):")
        events = store.get_file_history(args.file, limit=args.limit)
        if events:
            for e in events:
                print(fmt_event(e))
        else:
            print("  (none recorded)")
        return

    # ── ROUTES — globally strongest pheromone paths ───────────────────────────
    if args.routes:
        print("=== PHEROMONE ROUTES (strongest reinforced paths) ===")
        print("These trails were built by repeated successful test runs.")
        print("Higher weight = more reinforcement. Follow these first.\n")
        routes = store.get_pheromone_routes(limit=args.limit)
        if routes:
            for r in routes:
                src = r.get("source_path") or r.get("source_id", "?")
                tgt = r.get("target_path") or r.get("target_id", "?")
                w = r.get("weight", 1.0)
                rel = r.get("relationship", "→")
                n = r.get("compound_count", 0)
                bar = "#" * int(w * 4)
                print(f"  {bar:<20} [{w:.2f}x / {n} runs]")
                print(f"  {src}")
                print(f"    --{rel}-->")
                print(f"  {tgt}\n")
        else:
            print("(no edges recorded yet)")
        return

    # ── FAILURES — high-signal failures ──────────────────────────────────────
    if args.failures:
        print(f"=== HIGH-SIGNAL FAILURES (score >= {HIGH_POTENTIAL_FAILURE_THRESHOLD}) ===")
        print("These are NOT noise. They are informative failures — future success candidates.")
        print("The pheromone trail did not strengthen on these passes, but the signal is high.")
        print("Read them before approaching the same area.\n")
        failures = store.get_high_potential_failures(limit=args.limit)
        if failures:
            for e in failures:
                score = e.get("score", 0)
                fp = e.get("file_path", "")
                ts = fmt_time(e.get("created_at"))
                print(f"  [{score:.2f}] {ts} | {e['agent_id']}")
                print(f"    {e['description'][:100]}")
                if fp:
                    print(f"    file: {fp}")
                print()
        else:
            print(f"(no failures scored >= {HIGH_POTENTIAL_FAILURE_THRESHOLD} yet)")
        return

    # ── SUMMARY — graph statistics + crystallization ──────────────────────────
    if args.summary:
        s = store.get_graph_summary()
        print("=== COORDINATE GRAPH SUMMARY ===")
        print(f"Events:               {s['total_events']}")
        print(f"File nodes:           {s['file_nodes']}")
        print(f"Test nodes:           {s['test_nodes']}")
        print(f"Graph edges:          {s['graph_edges']}")
        print(f"Near crystallization: {s.get('near_crystallization', 0)} "
              f"(activation >= {CHART_ACTIVATION_THRESHOLD})")
        print(f"High-signal failures: {s.get('high_potential_failures', 0)}")

        if s.get('hottest_files'):
            print("\nMost-activated files (topology candidates):")
            for fn in s['hottest_files']:
                primitive = store.classify_topology_primitive(fn['file_path'])
                conf = fn.get('confidence') or 0.0
                act = fn.get('activation_count') or 0
                print(f"  {primitive_color(primitive)} [{conf:.2f}] "
                      f"act:{act:<3} edits:{fn['edit_count']:<3}  {fn['file_path']}")

        # Crystallization candidates
        candidates = store.get_crystallization_candidates()
        if candidates:
            print(f"\nCRYSTALLIZATION CANDIDATES (activation >= {CHART_ACTIVATION_THRESHOLD}):")
            print("  These files have been reinforced enough to become permanent landmarks.")
            for fn in candidates:
                primitive = store.classify_topology_primitive(fn['file_path'])
                print(f"  {primitive_color(primitive)} [{fn['confidence']:.2f}] "
                      f"act:{fn['activation_count']}  {fn['file_path']}")
        return

    # ── RECENT — episodic layer ───────────────────────────────────────────────
    if args.recent:
        print("=== RECENT CODE EVENTS (episodic layer) ===")
        events = store.get_recent_events(limit=args.limit)
        if events:
            for e in events:
                print(fmt_event(e))
        else:
            print("(no events recorded yet)")
        return

    # ── AGENT — agent trail ───────────────────────────────────────────────────
    if args.agent:
        print(f"=== AGENT TRAIL: {args.agent} ===")
        events = store.get_agent_trail(args.agent, limit=args.limit)
        if events:
            for e in events:
                print(fmt_event(e))
        else:
            print(f"(no events recorded for agent '{args.agent}')")
        return

    # ── LANDMARK — events linked to a landmark ────────────────────────────────
    if args.landmark:
        print(f"=== EVENTS FOR LANDMARK: {args.landmark} ===")
        with store._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM code_events WHERE landmark_id LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (f"%{args.landmark}%", args.limit)
            ).fetchall()
        if rows:
            for e in rows:
                print(fmt_event(dict(e)))
        else:
            print("(no events linked to this landmark)")
        return

    # ── DEFAULT — semantic summary + strongest routes ─────────────────────────
    s = store.get_graph_summary()
    print(f"Graph: {s['total_events']} events | {s['file_nodes']} files | "
          f"{s['test_nodes']} tests | {s.get('near_crystallization', 0)} near-crystallization")
    print()
    routes = store.get_pheromone_routes(limit=4)
    if routes:
        print("Strongest paths:")
        for r in routes:
            src = r.get("source_path") or r.get("source_id", "?")
            tgt = r.get("target_path") or r.get("target_id", "?")
            w = r.get("weight", 1.0)
            print(f"  [{w:.1f}x] {src} -> {tgt}")
    print()
    print("Use --file <path>, --routes, --failures, --summary, or --recent for details.")


if __name__ == "__main__":
    main()

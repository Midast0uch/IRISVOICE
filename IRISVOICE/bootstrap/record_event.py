#!/usr/bin/env python3
"""
record_event.py — Record a code action into the coordinate graph.

Any agent building in this codebase calls this after:
  - Editing or creating a file
  - Running tests
  - Making a notable decision (use --type note)

Usage:
  python bootstrap/record_event.py --type file_edit --file backend/agent/agent_kernel.py --desc "Added _sanitize_task"
  python bootstrap/record_event.py --type file_create --file backend/channels/telegram_notifier.py --desc "TelegramNotifier class"
  python bootstrap/record_event.py --type test_run --file backend/tests/test_der_loop.py --result pass --covers backend/agent/der_loop.py
  python bootstrap/record_event.py --type note --desc "Chose WAL mode for concurrent SQLite access"
  python bootstrap/record_event.py --type git_commit --desc "feat: DER loop foundation"

  # Override the computed score — a failure that taught you something important:
  python bootstrap/record_event.py --type test_run --file backend/tests/test_x.py --result fail --score 0.70 --desc "ImportError revealed circular dependency in agent_kernel"

Options:
  --type      Event type: file_edit | file_create | test_run | git_commit | note
  --file      File path (relative to IRISVOICE/)
  --desc      Description of what changed and why
  --result    For test_run: pass | fail
  --covers    For test_run: comma-separated implementation files the test covers
  --agent     Agent ID (default: reads from claimed work or uses 'unknown')
  --landmark  Landmark ID to link this event to
  --score     Override computed signal score 0.0-1.0. Use when a failure carries
              more signal than the heuristic assigns — e.g. a fail that revealed
              a fundamental issue scores 0.70, making it a future-success candidate.
"""

import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from coordinates import CoordinateStore, COORDINATES_DB


def get_current_agent():
    """Try to find the currently claimed agent ID from work_items."""
    try:
        store = CoordinateStore()
        with store._conn() as conn:
            row = conn.execute(
                "SELECT claimed_by FROM work_items WHERE status='claimed' "
                "ORDER BY claimed_at DESC LIMIT 1"
            ).fetchone()
            if row and row["claimed_by"]:
                return row["claimed_by"]
    except Exception:
        pass
    return "unknown"


def get_current_gate():
    """Return the current active gate number."""
    try:
        store = CoordinateStore()
        with store._conn() as conn:
            row = conn.execute(
                "SELECT MIN(gate) as g FROM work_items WHERE status != 'complete'"
            ).fetchone()
            if row and row["g"]:
                return row["g"]
    except Exception:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Record a code event in the coordinate graph")
    parser.add_argument("--type", required=True,
                        choices=["file_edit", "file_create", "test_run", "git_commit", "note"],
                        help="Event type")
    parser.add_argument("--file", default=None, help="File path affected")
    parser.add_argument("--desc", required=True, help="Description of what changed and why")
    parser.add_argument("--result", default=None, choices=["pass", "fail"],
                        help="Test result (for test_run events)")
    parser.add_argument("--covers", default=None,
                        help="Comma-separated files the test covers (for test_run)")
    parser.add_argument("--agent", default=None, help="Agent ID")
    parser.add_argument("--landmark", default=None, help="Landmark ID to link")
    parser.add_argument("--purpose", default=None, help="Purpose of the file (for file_create)")
    parser.add_argument("--score", default=None, type=float,
                        help="Override computed signal score 0.0-1.0")
    args = parser.parse_args()

    # Validate score range if provided
    explicit_score = None
    if args.score is not None:
        explicit_score = max(0.0, min(1.0, args.score))

    agent_id = args.agent or get_current_agent()
    gate = get_current_gate()
    store = CoordinateStore()

    if args.type == "test_run":
        covers = [f.strip() for f in args.covers.split(",")] if args.covers else []
        outcome = args.result or "pass"
        test_id = store.record_test_run(
            agent_id=agent_id,
            test_file=args.file or "unknown_test",
            outcome=outcome,
            covers_files=covers,
            landmark_id=args.landmark,
            output_summary=args.desc,
        )
        # Apply explicit score override after the fact if provided
        if explicit_score is not None:
            with store._conn() as conn:
                conn.execute(
                    "UPDATE code_events SET score = ? "
                    "WHERE event_id = ("
                    "  SELECT event_id FROM code_events "
                    "  WHERE agent_id = ? AND event_type = 'test_run' AND file_path = ? "
                    "  ORDER BY created_at DESC LIMIT 1"
                    ")",
                    (explicit_score, agent_id, args.file or "unknown_test")
                )
        # Compute what score was used for display
        display_score = explicit_score if explicit_score is not None else (
            0.85 if outcome == "pass" else 0.20
        )
        print(f"TEST RECORDED: {test_id}")
        print(f"  file:    {args.file}")
        print(f"  outcome: {outcome}")
        print(f"  score:   {display_score:.2f}" +
              (" (explicit override)" if explicit_score is not None else " (computed)"))
        if covers:
            print(f"  covers:  {', '.join(covers)}")
        if outcome == "fail" and display_score >= 0.5:
            print(f"  [!] High-signal failure — this will appear in --failures as a future-success candidate")
    else:
        # Register file node for creates
        if args.type == "file_create" and args.file:
            store.upsert_file_node(
                file_path=args.file,
                purpose=args.purpose or args.desc,
                agent_id=agent_id,
                owning_landmark=args.landmark,
            )

        event_id = store.record_code_event(
            agent_id=agent_id,
            event_type=args.type,
            description=args.desc,
            file_path=args.file,
            outcome=args.result,
            score=explicit_score,
            landmark_id=args.landmark,
            gate=gate,
        )
        # Get the score that was stored
        try:
            with store._conn() as conn:
                row = conn.execute(
                    "SELECT score FROM code_events WHERE event_id = ?", (event_id,)
                ).fetchone()
            display_score = row["score"] if row else None
        except Exception:
            display_score = explicit_score

        print(f"EVENT RECORDED: {event_id}")
        print(f"  type:  {args.type}")
        if args.file:
            print(f"  file:  {args.file}")
        print(f"  desc:  {args.desc[:80]}")
        print(f"  agent: {agent_id}")
        if display_score is not None:
            override = " (explicit override)" if explicit_score is not None else " (computed)"
            print(f"  score: {display_score:.2f}{override}")
        # Show topology update if file was tracked
        if args.file:
            try:
                node = store.get_file_node(args.file)
                if node:
                    primitive = store.classify_topology_primitive(args.file)
                    z = node.get("z_trajectory") or 0.0
                    conf = node.get("confidence") or 0.0
                    act = node.get("activation_count") or 0
                    z_sym = "↑" if z >= 0.08 else ("↓" if z <= -0.06 else "→")
                    print(f"  node:  {primitive} {z_sym} conf:{conf:.2f} act:{act}")
            except Exception:
                pass


if __name__ == "__main__":
    main()

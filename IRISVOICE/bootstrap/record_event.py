#!/usr/bin/env python3
"""
record_event.py — Record a code action into the coordinate graph.

Any agent building in this codebase calls this after:
  - Editing or creating a file
  - Running tests
  - Making a notable decision (use --type note)
  - Adding wiki knowledge (use --type wiki_entry)
  - Referencing an image or diagram (use --type image_ref)
  - Registering a new project (use --type project_ref)

Usage:
  python bootstrap/record_event.py --type file_edit --file backend/agent/agent_kernel.py --desc "Added _sanitize_task"
  python bootstrap/record_event.py --type file_create --file backend/channels/telegram_notifier.py --desc "TelegramNotifier class"
  python bootstrap/record_event.py --type test_run --file backend/tests/test_der_loop.py --result pass --covers backend/agent/der_loop.py
  python bootstrap/record_event.py --type note --desc "Chose WAL mode for concurrent SQLite access"
  python bootstrap/record_event.py --type git_commit --desc "feat: DER loop foundation"
  python bootstrap/record_event.py --type pin --title "TTS Pipeline Design" --content "F5-TTS is primary..." --tags tts voice
  python bootstrap/record_event.py --type pin --pin-type image --title "Architecture Diagram" --image-refs docs/arch.png --file-refs backend/agent/agent_kernel.py
  python bootstrap/record_event.py --type project_ref --project-name "my-other-project" --project-path /path/to/project

  # Override the computed score — a failure that taught you something important:
  python bootstrap/record_event.py --type test_run --file backend/tests/test_x.py --result fail --score 0.70 --desc "ImportError revealed circular dependency in agent_kernel"

Options:
  --type         Event type: file_edit | file_create | test_run | git_commit | note
                             | pin | project_ref
                 pin covers all PiN types — use --pin-type to specify: note|file|folder|image|doc|url|decision|fragment
  --file         File path (relative to IRISVOICE/)
  --desc         Description of what changed and why
  --result       For test_run: pass | fail
  --covers       For test_run: comma-separated implementation files the test covers
  --agent        Agent ID (default: reads from claimed work or uses 'unknown')
  --landmark     Landmark ID to link this event to
  --score        Override computed signal score 0.0-1.0
  --title        Title for wiki_entry or image_ref
  --content      Markdown body for wiki_entry
  --tags         Space-separated tags for wiki_entry / image_ref
  --image-refs   Space-separated image paths/URLs for wiki_entry / image_ref
  --file-refs    Space-separated file paths for wiki_entry / image_ref
  --permanent    Mark wiki entry as permanent (survives merges and decay)
  --project-name Name for project_ref registration
  --project-path Path for project_ref registration
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
                        choices=["file_edit", "file_create", "test_run", "git_commit", "note",
                                 "pin", "project_ref"],
                        help="Event type")
    parser.add_argument("--file", default=None, help="File path affected")
    parser.add_argument("--desc", default=None, help="Description of what changed and why")
    parser.add_argument("--result", default=None, choices=["pass", "fail"],
                        help="Test result (for test_run events)")
    parser.add_argument("--covers", default=None,
                        help="Comma-separated files the test covers (for test_run)")
    parser.add_argument("--agent", default=None, help="Agent ID")
    parser.add_argument("--landmark", default=None, help="Landmark ID to link")
    parser.add_argument("--purpose", default=None, help="Purpose of the file (for file_create)")
    parser.add_argument("--score", default=None, type=float,
                        help="Override computed signal score 0.0-1.0")
    # Wiki / federation fields
    parser.add_argument("--title", default=None,
                        help="Title for wiki_entry or image_ref")
    parser.add_argument("--content", default=None,
                        help="Markdown body for wiki_entry")
    parser.add_argument("--tags", nargs="+", default=None,
                        help="Tags for wiki_entry or image_ref")
    parser.add_argument("--image-refs", nargs="+", default=None,
                        help="Image paths/URLs for pin type=image")
    parser.add_argument("--file-refs", nargs="+", default=None,
                        help="File paths referenced by this PiN")
    parser.add_argument("--url-refs", nargs="+", default=None,
                        help="External URLs referenced by this PiN")
    parser.add_argument("--pin-type", default=None,
                        choices=["note", "file", "folder", "image", "doc", "url", "decision", "fragment"],
                        help="PiN sub-type (for --type pin)")
    parser.add_argument("--permanent", action="store_true",
                        help="Mark PiN as permanent (survives decay)")
    parser.add_argument("--project-name", default=None,
                        help="Project name for project_ref")
    parser.add_argument("--project-path", default=None,
                        help="Project path for project_ref")
    args = parser.parse_args()

    # --desc is optional for pin / project_ref (title takes precedence)
    if args.type not in ("pin", "project_ref") and not args.desc:
        parser.error("--desc is required for this event type")

    # Validate score range if provided
    explicit_score = None
    if args.score is not None:
        explicit_score = max(0.0, min(1.0, args.score))

    agent_id = args.agent or get_current_agent()
    gate = get_current_gate()
    store = CoordinateStore()

    # ── PiN (Primordial Information Node) ────────────────────────────────
    if args.type == "pin":
        title = args.title or args.desc or "Untitled"
        pin_type = args.pin_type or "note"
        pin_id = store.add_pin(
            title=title,
            pin_type=pin_type,
            content=args.content or "",
            tags=args.tags or [],
            file_refs=args.file_refs or ([args.file] if args.file else []),
            image_refs=args.image_refs or [],
            url_refs=args.url_refs or [],
            is_permanent=args.permanent,
        )
        print(f"PiN RECORDED: {pin_id}  [{pin_type}]")
        print(f"  title: {title}")
        if args.tags:
            print(f"  tags:  {', '.join(args.tags)}")
        if args.image_refs:
            print(f"  images: {', '.join(args.image_refs)}")
        if args.file_refs:
            print(f"  files: {', '.join(args.file_refs)}")
        if args.permanent:
            print("  ★ PERMANENT")
        # Mirror into code_event stream so the graph reflects this
        store.record_code_event(
            agent_id=agent_id,
            event_type="note",
            description=f"pin[{pin_type}]: {title}",
            file_path=args.file,
            gate=gate,
        )
        return

    if args.type == "project_ref":
        if not args.project_name:
            print("ERROR: --project-name is required for project_ref")
            sys.exit(1)
        project_id = store.ensure_project(
            name=args.project_name,
            path=args.project_path or "",
            description=args.desc or "",
        )
        print(f"PROJECT REGISTERED: {project_id}")
        print(f"  name: {args.project_name}")
        if args.project_path:
            print(f"  path: {args.project_path}")
        return

    # ── Standard event types ─────────────────────────────────────────────
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

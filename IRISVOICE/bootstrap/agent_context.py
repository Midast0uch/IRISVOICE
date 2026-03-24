"""
IRIS Bootstrap — Agent Context
File: IRISVOICE/bootstrap/agent_context.py

Single command any agent (main or sub-agent) runs at startup.
Returns: current gate, available work, what other agents are doing,
         gradient warnings relevant to the claimed step, and the
         exact spec and test command to use.

Designed for Claude Code sub-agents — each sub-agent runs this,
claims a work item atomically, gets everything it needs to start.

Usage:
    python bootstrap/agent_context.py                     # show context, no claim
    python bootstrap/agent_context.py --claim agent_001   # claim next item
    python bootstrap/agent_context.py --complete item_id agent_001 success --landmark "name:desc:file:cmd"
    python bootstrap/agent_context.py --complete item_id agent_001 failure --warning "space:what:how"
    python bootstrap/agent_context.py --heartbeat agent_001
    python bootstrap/agent_context.py --poll                          # check signals dir
"""

import sys
import os
import json
import time
import glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bootstrap.coordinates import CoordinateStore, COORDINATES_DB, SIGNALS_DIR


def show_context(store: CoordinateStore):
    """Full context for any agent starting a session."""
    session_count = store.get_session_count()
    permanent     = store.get_landmarks(permanent_only=True)
    warnings      = store.get_active_warnings(session_count)
    contracts     = store.get_active_contracts()
    available     = store.get_available_work()
    claimed       = store.get_claimed_work()

    print("=" * 65)
    print("IRIS AGENT CONTEXT")
    print("=" * 65)
    print(f"Sessions: {session_count}  |  "
          f"Permanent landmarks: {len(permanent)}  |  "
          f"Available work: {len(available)}  |  "
          f"In progress: {len(claimed)}")
    print()

    # Current gate
    from bootstrap.session_start import get_current_gate
    gate_num, gate_desc = get_current_gate(store)
    print(f"CURRENT GATE: {gate_desc}")
    print()

    # What's in progress by other agents
    if claimed:
        print("IN PROGRESS (do not duplicate these):")
        for item in claimed:
            age = int((time.time() - (item["claimed_at"] or time.time())) / 60)
            print(f"  [~] step {item['step']}: {item['description'][:55]}")
            print(f"      claimed {age}m ago by {(item['claimed_by'] or '?')[:16]}")
        print()

    # Available to claim
    if available:
        print("AVAILABLE TO CLAIM:")
        for item in available[:5]:  # show first 5
            print(f"  [ ] [Step {item['step']}] {item['description'][:60]}")
        if len(available) > 5:
            print(f"  ... and {len(available)-5} more")
        print()

    # Critical warnings
    if warnings:
        print("GRADIENT WARNINGS (read before starting):")
        for w in warnings[-4:]:
            print(f"  [{w['space']}] {w['description'][:65]}")
            if w["correction"]:
                print(f"    → worked: {w['correction'][:55]}")
        print()

    # Contracts
    if contracts:
        print("ACTIVE CONTRACTS:")
        for c in contracts[:3]:
            print(f"  [{c['confidence']:.2f}] {c['rule'][:70]}")
        print()

    print("To claim next work item:")
    print("  python bootstrap/agent_context.py --claim YOUR_AGENT_ID")
    print("=" * 65)


def claim_work(store: CoordinateStore, agent_id: str):
    """Claim next available work item and print full instructions."""
    item = store.claim_next_work_item(agent_id)

    if not item:
        print(f"NO WORK AVAILABLE for {agent_id}")
        print("All items are either claimed, complete, or gates are locked.")
        available = store.get_available_work()
        if not available:
            print("All Gate 1 items complete — check GOALS.md for Gate 2 items.")
        return

    session_count = store.get_session_count()
    warnings = store.get_active_warnings(session_count)

    print("=" * 65)
    print(f"WORK CLAIMED: {agent_id}")
    print("=" * 65)
    print(f"Item:        {item['item_id']}")
    print(f"Step:        {item['step']}")
    print(f"Gate:        {item['gate']}")
    print()
    print(f"TASK: {item['description']}")
    print()
    print(f"SPEC TO READ: {item['spec_file']}")
    print(f"TEST COMMAND: {item['test_command']}")
    print()
    print("WORKFLOW:")
    print("  1. Read the spec file completely before writing any code")
    print("  2. Read the existing files you will modify before touching them")
    print("  3. Implement following the spec")
    print(f"  4. Run: {item['test_command']}")
    print("  5. If PASS — complete with success:")
    print(f"     python bootstrap/agent_context.py --complete {item['item_id']} {agent_id} success \\")
    print(f"       --landmark \"name:description:file:test_command\"")
    print("  6. If FAIL — fix code and retry. After 2 failures, complete with failure:")
    print(f"     python bootstrap/agent_context.py --complete {item['item_id']} {agent_id} failure \\")
    print(f"       --warning \"space:what failed:approach tried:what worked\"")
    print()

    # Relevant warnings for this step
    relevant = [w for w in warnings if
                item['description'].lower()[:15] in w['description'].lower()
                or w['space'] in ['domain', 'toolpath']]
    if relevant:
        print("WARNINGS RELEVANT TO THIS STEP:")
        for w in relevant[-3:]:
            print(f"  [{w['space']}] {w['description'][:65]}")
            if w["correction"]:
                print(f"    → use: {w['correction'][:55]}")
        print()

    print("HEARTBEAT (run every 60s for long tasks):")
    print(f"  python bootstrap/agent_context.py --heartbeat {agent_id}")
    print()
    print("CRITICAL RULES:")
    print("  - Run the spec's test. Never write tests to match your code.")
    print("  - Never mark complete without a passing test.")
    print("  - Never modify existing tests to make them pass.")
    print("=" * 65)


def complete_work(store: CoordinateStore, item_id: str, agent_id: str,
                  result: str, landmark_str: str = "", warning_str: str = ""):
    """Complete a work item, record landmark or warning, emit signal."""
    session_count = store.get_session_count() + 1

    # Record landmark if provided and result is success
    landmark_name = ""
    if result == "success" and landmark_str:
        parts = landmark_str.split(":", 3)
        if len(parts) == 4:
            name, description, feature_path, test_command = parts
            lm_id = store.add_landmark(
                name.strip(), description.strip(),
                feature_path.strip(), test_command.strip(),
                session_count
            )
            became_permanent = store.verify_landmark(lm_id)
            landmark_name = name.strip()
            status = "PERMANENT" if became_permanent else "DEVELOPING"
            print(f"LANDMARK {status}: {name.strip()}")

    # Record warning if provided
    warning_desc = ""
    if warning_str:
        parts = warning_str.split(":", 3)
        if len(parts) >= 3:
            space       = parts[0].strip()
            description = parts[1].strip()
            approach    = parts[2].strip()
            correction  = parts[3].strip() if len(parts) > 3 else None
            store.add_gradient_warning(
                space, description, approach, session_count, correction
            )
            warning_desc = description
            print(f"WARNING RECORDED: [{space}] {description[:60]}")

    # Complete the work item
    success = store.complete_work_item(
        item_id=item_id,
        agent_id=agent_id,
        result=result,
        landmark_name=landmark_name,
        warning_description=warning_desc
    )

    # Auto-link recent events from this agent to the landmark
    if success and landmark_name:
        lm_id = f"lm_{landmark_name.split(':')[0].lower().replace(' ','_')[:20]}"
        linked = store.link_events_to_landmark(agent_id, lm_id)
        if linked:
            print(f"Linked {linked} code event(s) to landmark {lm_id}")

    if success:
        print(f"COMPLETE: {item_id} → {result.upper()}")
        print(f"Signal written to: bootstrap/signals/")
        print()
        # Show what's next
        next_available = store.get_available_work()
        if next_available:
            next_item = next_available[0]
            print(f"NEXT AVAILABLE: [{next_item['gate']}.{next_item['step']}] "
                  f"{next_item['description'][:55]}")
            print(f"  python bootstrap/agent_context.py --claim {agent_id}")
        else:
            print("No more available items. All work is claimed or complete.")
    else:
        print(f"FAILED to complete {item_id} — check database")


def poll_signals():
    """
    Poll signals directory for completion events.
    Used by orchestrator to know when sub-agents finish.
    Prints each signal and moves it to signals/processed/.
    """
    processed_dir = os.path.join(SIGNALS_DIR, "processed")
    os.makedirs(processed_dir, exist_ok=True)

    signals = glob.glob(os.path.join(SIGNALS_DIR, "complete_*.json"))

    if not signals:
        print("No completion signals pending.")
        return

    print(f"COMPLETION SIGNALS ({len(signals)}):")
    for sig_path in signals:
        try:
            with open(sig_path) as f:
                signal = json.load(f)
            print(f"  [{signal['result'].upper()}] {signal['item_id']}")
            print(f"    Agent: {signal['agent_id']}")
            if signal.get('landmark_name'):
                print(f"    Landmark: {signal['landmark_name']}")
            if signal.get('warning'):
                print(f"    Warning: {signal['warning'][:50]}")
            completed = time.time() - signal.get('completed_at', time.time())
            print(f"    Completed: {int(completed)}s ago")

            # Move to processed
            dest = os.path.join(processed_dir, os.path.basename(sig_path))
            os.rename(sig_path, dest)
        except Exception as e:
            print(f"  Error reading {sig_path}: {e}")


def main():
    if not os.path.exists(COORDINATES_DB):
        print("No coordinate database found.")
        print("Run: python bootstrap/coordinates.py --test")
        sys.exit(1)

    store = CoordinateStore(COORDINATES_DB)
    args  = sys.argv[1:]

    if not args:
        show_context(store)
        return

    if args[0] == "--claim" and len(args) >= 2:
        claim_work(store, args[1])
        return

    if args[0] == "--complete" and len(args) >= 4:
        item_id   = args[1]
        agent_id  = args[2]
        result    = args[3]  # "success" or "failure"
        landmark  = ""
        warning   = ""
        # Parse --landmark and --warning flags
        i = 4
        while i < len(args):
            if args[i] == "--landmark" and i+1 < len(args):
                landmark = args[i+1]; i += 2
            elif args[i] == "--warning" and i+1 < len(args):
                warning = args[i+1]; i += 2
            else:
                i += 1
        complete_work(store, item_id, agent_id, result, landmark, warning)
        return

    if args[0] == "--heartbeat" and len(args) >= 2:
        store.heartbeat(args[1])
        print(f"Heartbeat updated for {args[1]}")
        return

    if args[0] == "--poll":
        poll_signals()
        return

    if args[0] == "--work":
        available = store.get_available_work()
        claimed   = store.get_claimed_work()
        print(f"Available ({len(available)}):")
        for item in available:
            print(f"  [{item['gate']}.{item['step']}] {item['description'][:65]}")
        if claimed:
            print(f"In progress ({len(claimed)}):")
            for item in claimed:
                print(f"  [~] {item['step']} → {(item['claimed_by'] or '?')[:16]}")
        return

    print(__doc__)


if __name__ == "__main__":
    main()

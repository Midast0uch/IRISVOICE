"""
IRIS Bootstrap — Mid-Session Snapshot
File: IRISVOICE/bootstrap/mid_session_snapshot.py

Run this when the context window is at ~50-55k tokens.
Saves the current session's key signals to the database BEFORE condensing.
After running this, tell Roo Code to condense the context.
After condensing, run session_start.py --compact to restore state.

The loop:
    work... work... work... (~50k tokens)
    → python bootstrap/mid_session_snapshot.py --progress "what I just did"
    → [condense context in Roo Code]
    → python bootstrap/session_start.py --compact
    → keep firing

Usage:
    python bootstrap/mid_session_snapshot.py
    python bootstrap/mid_session_snapshot.py --progress "built der_loop foundation, tests passing"
    python bootstrap/mid_session_snapshot.py --verify "landmark_name:test_command"
    python bootstrap/mid_session_snapshot.py --warn "space:what failed:approach"
"""

import sys
import os
import json
import time
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bootstrap.coordinates import CoordinateStore, COORDINATES_DB


def run_test(command: str) -> tuple[bool, str]:
    """Run a verification command. Returns (passed, output)."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True,
            timeout=60,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as e:
        return False, str(e)


def mid_session_snapshot(
    store: CoordinateStore,
    progress: str = "",
    verify_landmarks: list = None,
    add_warnings: list = None,
    add_contracts: list = None
):
    """
    Save mid-session progress to database.
    Prints a compact summary the agent can read after condensing.
    """
    session_count  = store.get_session_count()
    snapshot_time  = time.time()

    print()
    print("=" * 65)
    print("MID-SESSION SNAPSHOT")
    print("=" * 65)
    print(f"Session: {session_count + 1} (in progress)")
    print(f"Time: {time.strftime('%H:%M:%S')}")
    print()

    new_landmarks = []
    failed_verifications = []

    # Verify any landmarks claimed during this context window
    if verify_landmarks:
        print("VERIFYING LANDMARKS:")
        for item in verify_landmarks:
            parts = item.split(":", 3)
            if len(parts) < 4:
                print(f"  SKIP (bad format): {item}")
                continue

            name, description, feature_path, test_command = parts
            name = name.strip()
            test_command = test_command.strip()

            print(f"  Testing: {name}")
            print(f"    Command: {test_command}")

            passed, output = run_test(test_command)

            if passed:
                # Add or update landmark
                lm_id = store.add_landmark(
                    name=name,
                    description=description.strip(),
                    feature_path=feature_path.strip(),
                    test_command=test_command,
                    session_number=session_count + 1
                )
                became_permanent = store.verify_landmark(lm_id)
                new_landmarks.append(name)

                status = "PERMANENT" if became_permanent else "DEVELOPING"
                print(f"    PASS → {status}")
            else:
                failed_verifications.append(name)
                print(f"    FAIL → not recorded as landmark")
                print(f"    Output: {output[:150]}")

                # Auto-record gradient warning for failed verification
                store.add_gradient_warning(
                    space="toolpath",
                    description=f"Verification failed for {name}",
                    approach=f"ran: {test_command}",
                    session_number=session_count + 1
                )

    # Record any gradient warnings from this context window
    warning_ids = []
    if add_warnings:
        print()
        print("RECORDING WARNINGS:")
        for w_str in add_warnings:
            parts = w_str.split(":", 3)
            if len(parts) >= 3:
                space       = parts[0].strip()
                description = parts[1].strip()
                approach    = parts[2].strip()
                correction  = parts[3].strip() if len(parts) > 3 else None

                w_id = store.add_gradient_warning(
                    space=space,
                    description=description,
                    approach=approach,
                    session_number=session_count + 1,
                    correction=correction
                )
                warning_ids.append(w_id)
                print(f"  [{space}] {description[:60]}")

    # Record any behavioral contracts from this context window
    if add_contracts:
        print()
        print("RECORDING CONTRACTS:")
        for rule in add_contracts:
            store.add_contract_evidence(rule.strip())
            print(f"  {rule[:70]}")

    # Save progress note to database
    if progress:
        try:
            with store._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO coordinate_path "
                    "(space, coordinates, confidence, last_updated) "
                    "VALUES ('snapshot_note', ?, ?, ?)",
                    (
                        json.dumps({"progress": progress, "time": snapshot_time}),
                        0.5,
                        snapshot_time
                    )
                )
        except Exception:
            pass

    # Print summary
    print()
    print("SNAPSHOT SUMMARY:")
    if new_landmarks:
        print(f"  New landmarks recorded: {', '.join(new_landmarks)}")
    if failed_verifications:
        print(f"  Failed verifications: {', '.join(failed_verifications)}")
    if warning_ids:
        print(f"  Gradient warnings recorded: {len(warning_ids)}")
    if progress:
        print(f"  Progress note: {progress[:80]}")

    # Print compact state for post-condense context
    print()
    print("-" * 65)
    print("COMPACT STATE (will be restored after condense):")
    print("-" * 65)

    permanent = store.get_landmarks(permanent_only=True)
    all_warnings = store.get_active_warnings(session_count + 1)
    contracts = store.get_active_contracts()

    from bootstrap.session_start import get_current_gate
    gate_num, gate_desc = get_current_gate(store)

    print(f"Gate: {gate_desc}")
    print(f"Permanent landmarks: {len(permanent)}")
    if permanent:
        for lm in permanent[-5:]:
            print(f"  [+] {lm['name']}: {lm['description'][:55]}")
    if all_warnings:
        print("Recent warnings:")
        for w in all_warnings[-3:]:
            print(f"  [{w['space']}] {w['description'][:60]}")
    if contracts:
        print("Active contracts:")
        for c in contracts[:2]:
            print(f"  {c['rule'][:65]}")

    print("-" * 65)
    print()
    print("NEXT STEPS:")
    print("  1. Condense the context in Roo Code now")
    print("  2. After condensing, run:")
    print("     python bootstrap/session_start.py --compact")
    print("  3. Continue from your current gate")
    print("=" * 65)
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="IRIS Bootstrap Mid-Session Snapshot"
    )
    parser.add_argument(
        "--progress", type=str, default="",
        help="Brief description of progress this context window"
    )
    parser.add_argument(
        "--verify", action="append",
        help="name:description:file_path:test_command — verify and record landmark"
    )
    parser.add_argument(
        "--warn", action="append",
        help="space:description:approach[:correction] — record gradient warning"
    )
    parser.add_argument(
        "--contract", action="append",
        help="Behavioral rule to record"
    )

    args = parser.parse_args()

    db_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "coordinates.db"
    )

    if not os.path.exists(db_path):
        print("No coordinate database found.")
        print("Run: python bootstrap/coordinates.py --test")
        print("to initialize the database first.")
        sys.exit(1)

    store = CoordinateStore(db_path)

    mid_session_snapshot(
        store=store,
        progress=args.progress,
        verify_landmarks=args.verify or [],
        add_warnings=args.warn or [],
        add_contracts=args.contract or []
    )
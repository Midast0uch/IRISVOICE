"""
IRIS Bootstrap Session Update Script
File: IRISVOICE/bootstrap/update_coordinates.py

Run this at the END of every session to:
1. Record what was completed
2. Update the coordinate store
3. Generate the new COORDINATE STATE block
4. Print it so you can paste it into the LM Studio system prompt

Usage (run from IRISVOICE/ directory):
    python bootstrap/update_coordinates.py

The script will ask what was completed this session and handle the rest.
The agent can also call this non-interactively with arguments.

Non-interactive usage:
    python bootstrap/update_coordinates.py \
        --session 1 \
        --tasks "built coordinate store,ran self-test" \
        --landmark "coordinate_store:Built the coordinate store:bootstrap/coordinates.py:python bootstrap/coordinates.py --test" \
        --warning "toolpath:Import failed for sqlite3:direct import:use sqlite3 from stdlib"
"""

import sys
import os
import json
import subprocess
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from bootstrap.coordinates import CoordinateStore, COORDINATES_DB


def run_test(test_command: str) -> tuple[bool, str]:
    """Run a test command and return (passed, output)."""
    try:
        result = subprocess.run(
            test_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=os.path.dirname(os.path.dirname(__file__))  # IRISVOICE/
        )
        passed = result.returncode == 0
        output = result.stdout + result.stderr
        return passed, output
    except subprocess.TimeoutExpired:
        return False, "Test timed out after 60 seconds"
    except Exception as e:
        return False, str(e)


def interactive_update(store: CoordinateStore):
    """Interactive session update — prompts for what was done."""
    print("\n" + "=" * 60)
    print("IRIS BOOTSTRAP SESSION UPDATE")
    print("=" * 60)

    session_number = store.get_session_count() + 1
    print(f"\nRecording Session {session_number}")
    print(f"Database: {COORDINATES_DB}\n")

    # Tasks completed
    print("What tasks were completed this session?")
    print("(Enter one per line, blank line when done)")
    tasks = []
    while True:
        task = input(f"  Task {len(tasks)+1}: ").strip()
        if not task:
            break
        tasks.append(task)

    if not tasks:
        print("No tasks recorded. Exiting.")
        return

    # Landmarks
    landmarks_added = []
    print("\nDid any features pass their tests? (y/n)")
    if input("  → ").lower().startswith("y"):
        print("\nFor each passing feature:")
        while True:
            print(f"\n  Landmark {len(landmarks_added)+1}:")
            name = input("    Name (short, no spaces): ").strip()
            if not name:
                break
            description = input("    Description: ").strip()
            feature_path = input("    File path (e.g. backend/agent/der_loop.py): ").strip()
            test_command = input("    Test command: ").strip()

            # Run the test to verify
            print(f"\n    Running: {test_command}")
            passed, output = run_test(test_command)

            if passed:
                print("    ✓ TEST PASSED")
                lm_id = store.add_landmark(
                    name=name,
                    description=description,
                    feature_path=feature_path,
                    test_command=test_command,
                    session_number=session_number
                )
                # Each time a test passes, verify the landmark
                became_permanent = store.verify_landmark(lm_id)
                landmarks_added.append(lm_id)
                if became_permanent:
                    print(f"    ★ LANDMARK PERMANENT: {name}")
                else:
                    lm = [l for l in store.get_landmarks()
                          if l["landmark_id"] == lm_id][0]
                    print(
                        f"    ~ LANDMARK DEVELOPING: {name} "
                        f"({lm['pass_count']}/3 passes)"
                    )
            else:
                print(f"    ✗ TEST FAILED")
                print(f"    Output: {output[:200]}")
                print("    Not recording as landmark — feature needs more work")

            more = input("\n  Another landmark? (y/n): ")
            if not more.lower().startswith("y"):
                break

    # Gradient warnings
    warnings_added = []
    print("\nDid anything fail that future sessions should know about? (y/n)")
    if input("  → ").lower().startswith("y"):
        print("\nFor each failure:")
        while True:
            print(f"\n  Warning {len(warnings_added)+1}:")
            space = input("    Space (domain/conduct/context/capability/toolpath): ").strip()
            description = input("    What failed: ").strip()
            approach = input("    What approach was tried: ").strip()
            correction = input("    What worked instead (leave blank if unknown): ").strip()

            if description and approach:
                w_id = store.add_gradient_warning(
                    space=space or "toolpath",
                    description=description,
                    approach=approach,
                    session_number=session_number,
                    correction=correction or None
                )
                warnings_added.append(w_id)
                print(f"    Warning recorded: {w_id}")

            more = input("\n  Another warning? (y/n): ")
            if not more.lower().startswith("y"):
                break

    # Contracts
    print("\nDid you correct yourself in a way that became a rule? (y/n)")
    if input("  → ").lower().startswith("y"):
        print("Enter the rule (e.g. 'Always run pytest before marking done'):")
        rule = input("  Rule: ").strip()
        if rule:
            store.add_contract_evidence(rule)
            print(f"  Contract evidence recorded for: {rule}")

    # Record the session
    store.record_session(
        session_number=session_number,
        objective="Build IRIS until fully autonomous — own interface, own backend, self-improving.",
        tasks_completed=tasks,
        landmarks_added=landmarks_added,
        warnings_added=warnings_added
    )

    # Generate and print the new state
    print("\n" + "=" * 60)
    print("SESSION RECORDED SUCCESSFULLY")
    print("=" * 60)
    print(f"\nSession {session_number} complete.")
    print(f"Landmarks this session: {len(landmarks_added)}")
    print(f"Warnings this session: {len(warnings_added)}")
    print(f"Total permanent landmarks: "
          f"{len(store.get_landmarks(permanent_only=True))}")

    print("\n" + "=" * 60)
    print("COPY THE FOLLOWING INTO YOUR LM STUDIO SYSTEM PROMPT")
    print("Replace the existing COORDINATE STATE section")
    print("=" * 60)
    print()
    print(store.generate_system_prompt_state())
    print()
    print("=" * 60)
    print("Done. Paste the above into LM Studio before your next session.")
    print("=" * 60)


def non_interactive_update(store: CoordinateStore, args):
    """Non-interactive update — agent calls this from terminal."""
    session_number = store.get_session_count() + 1

    # Parse tasks
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]

    # Parse and process landmarks
    landmarks_added = []
    if args.landmark:
        for lm_str in args.landmark:
            parts = lm_str.split(":", 3)
            if len(parts) == 4:
                name, description, feature_path, test_command = parts

                # Run test
                passed, output = run_test(test_command)
                if passed:
                    lm_id = store.add_landmark(
                        name=name.strip(),
                        description=description.strip(),
                        feature_path=feature_path.strip(),
                        test_command=test_command.strip(),
                        session_number=session_number
                    )
                    became_permanent = store.verify_landmark(lm_id)
                    landmarks_added.append(lm_id)
                    status = "PERMANENT" if became_permanent else "DEVELOPING"
                    print(f"LANDMARK {status}: {name}")
                else:
                    print(f"LANDMARK FAILED TEST: {name}")
                    print(f"  Output: {output[:200]}")

    # Parse and process warnings
    warnings_added = []
    if args.warning:
        for w_str in args.warning:
            parts = w_str.split(":", 3)
            if len(parts) >= 3:
                space = parts[0].strip()
                description = parts[1].strip()
                approach = parts[2].strip()
                correction = parts[3].strip() if len(parts) > 3 else None
                w_id = store.add_gradient_warning(
                    space=space,
                    description=description,
                    approach=approach,
                    session_number=session_number,
                    correction=correction
                )
                warnings_added.append(w_id)
                print(f"WARNING RECORDED: {w_id}")

    # Process contracts
    if args.contract:
        for rule in args.contract:
            store.add_contract_evidence(rule.strip())
            print(f"CONTRACT EVIDENCE: {rule.strip()[:60]}")

    # Record session
    store.record_session(
        session_number=session_number,
        objective="Build IRIS until fully autonomous — own interface, own backend, self-improving.",
        tasks_completed=tasks,
        landmarks_added=landmarks_added,
        warnings_added=warnings_added
    )

    # Output the new state
    print("\n--- COORDINATE STATE UPDATE ---")
    print(store.generate_system_prompt_state())
    print("--- END COORDINATE STATE ---")
    print(f"\nSession {session_number} recorded.")


def main():
    parser = argparse.ArgumentParser(
        description="IRIS Bootstrap Session Update"
    )
    parser.add_argument(
        "--session", type=int,
        help="Session number (auto-detected if not provided)"
    )
    parser.add_argument(
        "--tasks", type=str,
        help="Comma-separated list of tasks completed"
    )
    parser.add_argument(
        "--landmark", action="append",
        help="name:description:file_path:test_command (repeatable)"
    )
    parser.add_argument(
        "--warning", action="append",
        help="space:description:approach[:correction] (repeatable)"
    )
    parser.add_argument(
        "--contract", action="append",
        help="Rule that emerged from corrections (repeatable)"
    )
    parser.add_argument(
        "--state", action="store_true",
        help="Just print current coordinate state and exit"
    )
    parser.add_argument(
        "--auto", action="store_true",
        help="Non-interactive mode — use with --tasks, --landmark, --warning. "
             "Prints compact state at end. No prompts. No human needed."
    )

    args = parser.parse_args()
    store = CoordinateStore()

    if args.state:
        print(store.generate_system_prompt_state())
        return

    # --auto flag: fully non-interactive, prints compact output
    # Agent uses this at end of every session
    if args.auto or args.tasks:
        non_interactive_update(store, args)

        # After non-interactive update, also print the compact start state
        # so the agent can verify what was saved
        print()
        print("--- VERIFY: run this to confirm state was saved ---")
        print("python bootstrap/session_start.py --compact")
        print("--------------------------------------------------")
        return

    # Interactive mode — only when human is present
    interactive_update(store)


if __name__ == "__main__":
    main()
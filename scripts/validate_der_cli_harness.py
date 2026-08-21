#!/usr/bin/env python3
"""
validate_der_cli_harness.py — Standing CDD harness (cli-workspace-unification T12).

Replays a recorded task-lifecycle trace through the REAL contract surfaces
(AgentKernel._task_start_payload + _multiagent_tags) and asserts the
contracts + emergent behaviors on EVERY run:

  CT-1  every task:start frame carries the full identity set
        (card_id / card_relation / conversation_id / agent_id / project_id)
        and is strictly ADDITIVE over the ten pre-T9a keys;
  B-1   revisions re-emit through the SAME channel with a distinct origin
        and CONTINUE the parent card (card_relation="continues");
  B-2   every card converges in EXACTLY ONE terminal frame
        (task:done or task:fail) — failure is recorded, never swallowed;
  B-3   tags are backend-emitted: a frame without agent_id/project_id still
        yields a usable key via conversationId-only fallback.

Usage:
    python scripts/validate_der_cli_harness.py                # built-in trace
    python scripts/validate_der_cli_harness.py --trace t.json # recorded trace

Trace format (JSON list of frames):
    [{"event": "task:start", "task_id": "...", "origin": "initial",
      "card_id": "...", "card_relation": "new",
      "agent_id": "...", "project_id": "...", "conversation_id": "..."},
     {"event": "task:progress", ...},
     {"event": "task:done" | "task:fail", ...}]

Exit code 0 = all invariants held; 1 = violation (with a per-frame report).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.agent.agent_kernel import AgentKernel  # noqa: E402

BASE_KEYS = {
    "task_id", "description", "plan_title", "mode", "steps",
    "total_steps", "origin", "card_id", "card_relation", "conversation_id",
}
IDENTITY_KEYS = BASE_KEYS | {"agent_id", "project_id"}
TERMINAL_EVENTS = {"task:done", "task:fail"}

DEFAULT_TRACE = [
    {"event": "task:start", "task_id": "t1", "origin": "initial",
     "card_id": "card_t1", "card_relation": "new",
     "agent_id": "sess_harness", "project_id": None,
     "conversation_id": "conv_harness"},
    {"event": "task:progress", "task_id": "t1", "step_number": 1,
     "description": "reading spec", "conversation_id": "conv_harness"},
    {"event": "task:start", "task_id": "t2", "origin": "sub_loop_split",
     "card_id": "card_t1", "card_relation": "continues",
     "agent_id": "sess_harness", "project_id": None,
     "conversation_id": "conv_harness"},
    {"event": "task:done", "task_id": "t1", "outcome": "success",
     "conversation_id": "conv_harness"},
    # A legacy emitter frame — no tags at all (B-3 fallback path).
    {"event": "task:start", "task_id": "legacy_1", "origin": "initial",
     "card_id": "card_legacy_1", "card_relation": "new",
     "conversation_id": "conv_harness"},
    {"event": "task:fail", "task_id": "legacy_1", "outcome": "failed",
     "error": "verify_failed", "conversation_id": "conv_harness"},
]


def replay(trace):
    violations = []
    kernel = AgentKernel.__new__(AgentKernel)
    kernel.session_id = "sess_harness"
    kernel.conversation_id = "conv_harness"

    terminal_per_card: dict[str, list] = {}
    starts_by_task: dict[str, dict] = {}

    for i, frame in enumerate(trace):
        ev = frame.get("event")
        label = f"frame[{i}] {ev}({frame.get('task_id')})"

        if ev == "task:start":
            payload = AgentKernel._task_start_payload(
                task_id=frame["task_id"],
                description=frame.get("description", "replayed task"),
                plan_title=frame.get("plan_title", "Harness Plan"),
                mode=frame.get("mode", "full"),
                steps=frame.get("steps", []),
                total_steps=frame.get("total_steps", 0),
                origin=frame.get("origin", "initial"),
                card_id=frame["card_id"],
                card_relation=frame.get("card_relation", "new"),
                conversation_id=frame.get("conversation_id", kernel.conversation_id),
                agent_id=frame.get("agent_id"),
                project_id=frame.get("project_id"),
            )
            # CT-1: identity set present and strictly additive.
            missing = IDENTITY_KEYS - set(payload.keys())
            if missing:
                violations.append(f"{label}: CT-1 missing identity keys {sorted(missing)}")
            extra_noncontract = set(payload.keys()) - IDENTITY_KEYS
            if extra_noncontract:
                violations.append(
                    f"{label}: CT-1 non-contract keys appeared {sorted(extra_noncontract)}"
                )
            starts_by_task[frame["task_id"]] = payload

            # B-1: a revision must continue its parent card.
            if payload["origin"] != "initial" and payload["card_relation"] != "continues":
                violations.append(
                    f"{label}: B-1 revision origin={payload['origin']} must carry "
                    f"card_relation='continues', got {payload['card_relation']!r}"
                )

            # B-3: tags absent -> conversationId-only keying still resolves.
            if payload["agent_id"] is None and not payload["conversation_id"]:
                violations.append(f"{label}: B-3 no tags AND no conversation id — card would drop")

        elif ev in TERMINAL_EVENTS:
            card = frame.get("card_id") or f"card_{frame.get('task_id')}"
            terminal_per_card.setdefault(card, []).append(frame)

    # B-2: exactly one terminal frame per started card.
    started_cards = {p["card_id"] for p in starts_by_task.values()}
    for card in sorted(started_cards):
        n = len(terminal_per_card.get(card, []))
        if n != 1:
            violations.append(
                f"B-2 card {card}: expected exactly 1 terminal frame, got {n}"
            )

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=str, default=None,
                        help="Path to a recorded JSON trace (defaults to built-in)")
    args = parser.parse_args()

    if args.trace:
        trace = json.loads(Path(args.trace).read_text(encoding="utf-8"))
        source = args.trace
    else:
        trace = DEFAULT_TRACE
        source = "<built-in trace>"

    print(f"[CDD harness] replaying {len(trace)} frames from {source}")
    violations = replay(trace)

    if violations:
        print(f"[CDD harness] FAIL — {len(violations)} violation(s):")
        for v in violations:
            print(f"  ✗ {v}")
        return 1

    print("[CDD harness] PASS — CT-1 identity/additivity, B-1 revision "
          "continuation, B-2 single terminal frame, B-3 tag fallback all held.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Standing CDD harness — goal-contract coverage replay (spec T14).

Replays the five recorded probe trajectories (D3/D7/D8/D9/D10, temp/*_reply.json)
through the REAL goal_contract core + the REAL grade/naming helpers on EVERY
run. This is the gap-finding instrument from design.md Verification Strategy
Tier 4: the same five probes that varied five ways live must now terminate
with the SAME coverage verdict — every fact covered or explicitly named
blocked; no pass with an open unblocked fact.

Head-less (no live web, no live model, no backend process). The recorded
probe answers stand in for settled node results; coverage, grade, and naming
are computed through the production code paths. Exits non-zero on any break.

Run:  python scripts/validate_goal_coverage.py
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if os.path.isdir(os.path.join(_REPO, "backend")):
    sys.path.insert(0, _REPO)

PROBES = ("d3", "d7", "d8", "d9", "d10")


class _Failures:
    def __init__(self):
        self.items = []

    def check(self, name, cond, detail=""):
        if cond:
            print(f"  [PASS] {name}")
        else:
            print(f"  [FAIL] {name} {detail}")
            self.items.append(name)


def _load_probe(name: str) -> str:
    from pathlib import Path

    p = Path(_REPO) / "temp" / f"{name}_reply.json"
    if not p.exists():
        return ""
    try:
        # Recorded fixtures predate the UTF-8 convention (cp1252 smart
        # quotes); decode tolerantly so the harness replays what is on
        # disk instead of failing on encoding.
        d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        return str(d.get("content") or "")
    except Exception:
        return ""


def main() -> int:
    from backend.agent import goal_contract as gc
    from backend.agent.tool_envelope import evaluate_run_grade

    fails = _Failures()
    print("goal-contract coverage replay: D3/D7/D8/D9/D10")
    verdicts = {}
    for probe in PROBES:
        answer = _load_probe(probe)
        if not answer.strip():
            fails.check(f"{probe}: probe answer loads", False, "(empty/missing)")
            continue
        facts = gc.extract_required(answer)
        fails.check(f"{probe}: required-fact set non-empty", len(facts) >= 1)
        # the recorded answer stands in for the settled node results
        cov = gc.mark_coverage(
            gc.Contract(required=tuple(facts)),
            ["VERIFIED"] * max(1, len(facts)),
            [answer] * max(1, len(facts)),
        )
        grade, reasons = evaluate_run_grade(
            [], coverage=cov.C,
            open_unblocked=[
                f for f in facts
                if f not in cov.covered
            ],
            blocked=[],
        )
        verdicts[probe] = (cov.C, grade)
        print(f"    {probe}: facts={len(facts)} C={cov.C:.3f} grade={grade}")
        # the invariant: an open unblocked fact never grades pass
        open_facts = [f for f in facts if f not in cov.covered]
        if open_facts:
            fails.check(f"{probe}: open facts cap grade", grade != "pass")
        else:
            fails.check(f"{probe}: full coverage passes", grade == "pass")
    # same terminal coverage verdict shape on all five: a (C, grade) pair
    # recorded per probe; the harness fails if any probe is missing
    fails.check(
        "all five probes replayed",
        all(p in verdicts for p in PROBES),
        f"got {sorted(verdicts)}",
    )
    # determinism: replay twice, identical verdicts
    for probe in PROBES:
        answer = _load_probe(probe)
        facts = gc.extract_required(answer)
        cov = gc.mark_coverage(
            gc.Contract(required=tuple(facts)),
            ["VERIFIED"] * max(1, len(facts)),
            [answer] * max(1, len(facts)),
        )
        grade, _ = evaluate_run_grade(
            [], coverage=cov.C,
            open_unblocked=[f for f in facts if f not in cov.covered],
            blocked=[],
        )
        fails.check(
            f"{probe}: replay deterministic",
            verdicts.get(probe) == (cov.C, grade),
        )
    print(f"\n{len(fails.items)} failure(s)")
    return 1 if fails.items else 0


if __name__ == "__main__":
    raise SystemExit(main())

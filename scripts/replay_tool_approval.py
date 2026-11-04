"""The tool_approval replay: the frames come from the LOG, the rows from the DB.

MEASURED 2026-11-04: the tool_approval's live cohort measures oof AUROC
0.5202 on the active engine (d1-2b), while its v5 wording measured 0.7429
on the OLD engine (d1-3B, 2026-10-17) - the model swap changed the
question's behaviour. The rows carry no frame, but the shadow logs one
DEBUG line per decision ("[tool_approval] frame: {...}") and the row's
input_key is a hash of that frame, so the log joins to the rows.

Usage: python scripts/replay_tool_approval.py [--limit N] [--variants ...]
"""

import argparse
import ast
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from _app_store import app_store_path  # noqa: E402
from backend.memory.db import open_store_read_only  # noqa: E402


def log_frames(log_path: pathlib.Path):
    """The frames the shadow logged, keyed by the row's input_key."""
    from backend.agent.surface_shadow import input_key as _ik

    out = {}
    if not log_path.exists():
        return out
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "[tool_approval] frame:" not in line:
            continue
        try:
            d = json.loads(line)
            msg = str(d.get("message", ""))
        except Exception:
            continue
        raw = msg.split("[tool_approval] frame:", 1)[1].strip()
        try:
            frame = ast.literal_eval(raw)
        except Exception:
            continue
        if not isinstance(frame, dict):
            continue
        out[_ik("tool_approval", str(frame.get("goal", "")), frame)] = frame
    return out


def rows_by_key():
    c = open_store_read_only(app_store_path())
    out = {}
    for (p,) in c.execute(
        "SELECT interaction_payload FROM system_events WHERE event_type='tool_execution'"
    ):
        try:
            d = json.loads(p or "{}").get("decision")
        except Exception:
            continue
        if not isinstance(d, dict) or d.get("consumer_id") != "tool_approval":
            continue
        out[d.get("input_key")] = d
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="logs/iris.log")
    ap.add_argument("--limit", type=int, default=300)
    ap.add_argument("--check", action="store_true",
                    help="ask each frame twice (the determinism check)")
    ap.add_argument("--no-instruction", action="store_true",
                    help="ask with no explicit instruction, like the live call site")
    ap.add_argument("--true-label", default="", help="the noul's true line")
    ap.add_argument("--false-label", default="", help="the noul's false line")
    ap.add_argument("--old-criteria", action="store_true",
                    help="ask the v1-v3 question the live backend still runs")
    ap.add_argument("--engine", default="d1-2b-q4_k_m+systemone")
    ap.add_argument("--stamps", default="tool_approval/v6")
    args = ap.parse_args()

    frames = log_frames(pathlib.Path(args.log))
    rows = rows_by_key()
    stamps = set(s.strip() for s in args.stamps.split(",") if s.strip())
    joined = []
    for key, frame in frames.items():
        row = rows.get(key)
        if not row:
            continue
        if stamps and row.get("criteria_version") not in stamps:
            continue
        if args.engine and row.get("engine") != args.engine:
            continue
        joined.append((frame, row))
    print(f"frames in the log: {len(frames)} | joined rows: {len(joined)}")
    if not joined:
        return 1

    from backend.agent.decision_engine import get_decision_engine
    from backend.agent.tool_approval_shadow import (
        TOOL_APPROVAL_CONSUMER,
        TOOL_APPROVAL_INSTRUCTION,
        _FALSE_LABEL,
        _TRUE_LABEL,
    )

    # The LIVE call site is the engine's NOUL (not decide): the noul builds
    # the state and asks the true/false question. The replay must use the
    # same call, or it asks another question.
    backend = get_decision_engine()
    if args.old_criteria:
        # The A/B: the criteria the live backend still runs (the v1-v3
        # question), registered so the noul asks THAT question.
        from backend.agent.decision_engine import register_declared

        register_declared(
            TOOL_APPROVAL_CONSUMER, TOOL_APPROVAL_INSTRUCTION,
            ("yes", "no"),
            criteria={
                "true": "This tool is the RIGHT NEXT TOOL for the goal, given the last result",
                "false": "This tool is NOT the right next tool for the goal",
            },
        )
    true_label = args.true_label or _TRUE_LABEL
    false_label = args.false_label or _FALSE_LABEL
    pairs = []
    same = 0
    for frame, row in joined[: args.limit]:
        noul = backend.noul(TOOL_APPROVAL_CONSUMER, TOOL_APPROVAL_INSTRUCTION,
                            frame, true_label=true_label,
                            false_label=false_label)
        if noul is None:
            continue
        ds = noul
        if args.check:
            again = backend.noul(TOOL_APPROVAL_CONSUMER, TOOL_APPROVAL_INSTRUCTION,
                                 frame, true_label=true_label,
                                 false_label=false_label)
            if again is not None and bool(again.true(0.5)) == bool(ds.true(0.5)) \
                    and abs(float(again.probability) - float(ds.probability)) < 1e-9:
                same += 1
        if ds is None:
            continue
        ol = row.get("outside_label")
        pick = bool(ds.true(0.5))
        if ol is None:
            ok = pick == bool(row.get("brain_bool"))
        else:
            ok = pick == bool(ol)
        pairs.append((float(ds.probability), ok, pick, row.get("chosen")))
    pos = [c for c, ok, _, _ in pairs if ok]
    neg = [c for c, ok, _, _ in pairs if not ok]
    print(f"n={len(pairs)} correct={len(pos)} wrong={len(neg)}")
    if pos and neg:
        wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
        print(f"auroc={wins / (len(pos) * len(neg)):.4f}")
    agree = sum(1 for _, _, a, b in pairs if bool(a) == bool(b))
    print(f"agreement with the recorded pick: {agree}/{len(pairs)}")
    if args.check:
        print(f"deterministic (the same answer twice): {same}/{len(pairs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

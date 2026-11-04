"""The surface consumers' replay: the frames come from the LOG, the rows from the DB.

MEASURED 2026-11-04: the surface consumers (done, depth_met,
escalate_incomplete, needs_action, web_intent) score a NOUL through
surface_shadow.score_surface_bool, and their rows carry no frame. The
shadow logs one DEBUG line per decision, and the row's input_key is a hash
of (consumer, statement, frame), so the log joins to the rows.

Usage: python scripts/replay_surface.py --consumer done [--limit N]
"""

import argparse
import ast
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _app_store import app_store_path  # noqa: E402
from backend.memory.db import open_store_read_only  # noqa: E402


def log_frames(consumer: str):
    """The frames the shadow logged, newest last."""
    out = {}
    path = pathlib.Path("logs/iris.log")
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            msg = str(json.loads(line).get("message", ""))
        except Exception:
            continue
        if consumer == "tool_approval":
            if "[tool_approval] frame: " not in msg:
                continue
            raw = msg.split("[tool_approval] frame: ", 1)[1]
        elif "[Reviewer] shadow frame step=" in msg:
            if consumer != "done":
                continue
            raw = msg.split("[Reviewer] shadow frame step=", 1)[1]
            raw = raw.split(": ", 1)[1]
        else:
            continue
        try:
            frame = ast.literal_eval(raw)
        except Exception:
            continue
        if isinstance(frame, str):
            frame = {"goal": frame}
        if not isinstance(frame, dict):
            continue
        out[str(frame.get("goal", ""))] = frame
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consumer", default="done")
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()

    from backend.agent.surface_shadow import (
        SURFACE_CONSUMERS,
        _FALSE_LABEL,
        _TRUE_LABEL,
        input_key,
        register_surface_consumers,
    )

    consumer = args.consumer
    statement = SURFACE_CONSUMERS.get(consumer)
    if statement is None:
        print(f"no statement for {consumer}")
        return 1
    register_surface_consumers()

    frames = log_frames(consumer)
    print(f"frames in the log: {len(frames)}")

    c = open_store_read_only(app_store_path())
    rows = {}
    for payload, in c.execute(
            "SELECT interaction_payload FROM system_events "
            "WHERE event_type='tool_execution'"):
        try:
            d = json.loads(payload or "{}").get("decision")
        except Exception:
            continue
        if not isinstance(d, dict) or d.get("consumer_id") != consumer:
            continue
        rows[d.get("input_key")] = d
    print(f"rows: {len(rows)}")

    joined = []
    for goal, frame in frames.items():
        key = input_key(consumer, statement, frame)
        row = rows.get(key)
        if row is not None:
            joined.append((frame, row))
    print(f"joined rows: {len(joined)}")
    if not joined:
        return 1

    from backend.agent.decision_engine import get_decision_engine

    engine = get_decision_engine()
    pairs = []
    for frame, row in joined[: args.limit]:
        noul = engine.noul(consumer, statement, frame,
                            true_label=_TRUE_LABEL, false_label=_FALSE_LABEL)
        if noul is None:
            continue
        pick = bool(noul.true(0.5))
        ol = row.get("outside_label")
        if ol is None:
            ok = pick == bool(row.get("brain_bool"))
        else:
            ok = pick == bool(ol)
        pairs.append((float(noul.probability), ok, pick, row.get("chosen")))
    if not pairs:
        print("no scores")
        return 1

    pos = [c for c, ok, _, _ in pairs if ok]
    neg = [c for c, ok, _, _ in pairs if not ok]
    auroc = 0.5
    if pos and neg:
        wins = sum((1.0 if p > n else 0.5 if p == n else 0.0) for p in pos for n in neg)
        auroc = wins / (len(pos) * len(neg))
    print(f"n={len(pairs)} correct={len(pos)} wrong={len(neg)}")
    print(f"auroc={auroc:.4f}")
    agree = sum(1 for _, _, pick, rec in pairs if pick == bool(rec))
    print(f"agreement with the recorded pick: {agree}/{len(pairs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

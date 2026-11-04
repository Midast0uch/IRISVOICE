"""The confidence distribution per consumer ON THE ACTIVE ENGINE.

MEASURED 2026-11-04: the quality-blocked consumers all sit at chance
(depth_met 0.5055, done 0.5591, escalate_incomplete 0.4616, review_verdict
0.4533, tool_approval 0.5202). The doc (oracle.md 7.2b) says a DEMOTED
consumer's cohort is structurally at confidence >= 0.9, because a sampled
pick binds only at raw confidence >= IRIS_ORACLE_FORCE_MIN. If that holds,
the AUROC clause cannot be met while the consumer is demoted - the range
only forms under enforcement.

This measures the range on the ACTIVE engine only (the report filters by
config.engine_id; this script did not, so it mixed the two engines).

Usage: python scripts/confidence_range.py [--engine ID]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for p in (str(_REPO), str(_REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _app_store import app_store_path  # noqa: E402
from backend.memory.db import open_store_read_only  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="")
    ap.add_argument("--min", type=float, default=0.0)
    args = ap.parse_args()

    conn = open_store_read_only(app_store_path())
    per = collections.defaultdict(list)
    for (payload,) in conn.execute(
        "SELECT interaction_payload FROM system_events WHERE event_type='tool_execution'"
    ):
        try:
            d = json.loads(payload or "{}").get("decision")
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        cid = d.get("consumer_id")
        conf = d.get("confidence")
        if cid is None or conf is None:
            continue
        if args.engine and str(d.get("engine") or "") != args.engine:
            continue
        ref = d.get("brain_bool")
        if ref is None:
            ref = d.get("brain_choice")
        ok = None
        if isinstance(ref, bool):
            ok = ref == d.get("chosen")
        elif isinstance(ref, str) and isinstance(d.get("chosen"), str):
            ok = ref == d.get("chosen")
        per[cid].append((float(conf), ok))

    for cid in sorted(per):
        vals = per[cid]
        confs = [c for c, _ in vals]
        labelled = [(c, ok) for c, ok in vals if ok is not None]
        good = [c for c, ok in labelled if ok]
        bad = [c for c, ok in labelled if not ok]
        above = sum(1 for c in confs if c >= args.min)
        print(
            "%-20s n=%-6d uniq=%-5d min=%.3f p50=%.3f max=%.3f  "
            "mean_ok=%.3f mean_bad=%.3f  labelled=%d"
            % (
                cid,
                len(confs),
                len(set(confs)),
                min(confs),
                sorted(confs)[len(confs) // 2],
                max(confs),
                (sum(good) / len(good)) if good else 0.0,
                (sum(bad) / len(bad)) if bad else 0.0,
                len(labelled),
            )
        )
        if above:
            print("      rows at/above %.2f: %d" % (args.min, above))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

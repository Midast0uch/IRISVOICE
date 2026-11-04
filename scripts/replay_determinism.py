"""Is the d1 server's answer deterministic? (the replay's foundation)

MEASURED 2026-11-04: the replay of the recorded review_verdict states gives
oof_auroc 0.8009 on a 600-row spread sample, while the SAME rows' recorded
confidences give 0.4075 and the whole cohort 0.3997. The picks matched
40/40 but the confidences matched only 1/40 exactly, so the server may
sample. If it samples, every replay number is a noisy estimate and the
tool_choice conclusion (0.632 -> 0.7986) needs re-checking.

This asks the SAME recorded state twice and compares.

Usage:
    python scripts/replay_determinism.py --consumer review_verdict --n 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
for p in (str(_REPO), str(_REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.agent.decision_backend_d1 import D1Backend  # noqa: E402
from backend.agent.decision_engine import (  # noqa: E402
    CONSUMER_DECLARATIONS,
    OracleState,
    oracle_job,
)
from replay_consumer import load_rows  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--consumer", default="review_verdict")
    ap.add_argument("--engine", default="")
    ap.add_argument("--stamps", default="")
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()
    stamps = set(s.strip() for s in args.stamps.split(",") if s.strip()) or None
    rows = load_rows(args.consumer, args.n, stamps, args.engine)
    decl = CONSUMER_DECLARATIONS.get(args.consumer)
    texts = dict(decl.criteria) if decl else {}
    job = oracle_job(args.consumer)
    backend = D1Backend()
    same_pick = same_conf = 0
    for r in rows:
        st = OracleState(job=job.name, fields=tuple(job.fields), text=r["state"],
                         budget_ids=job.budget_ids,
                         option_criteria=tuple((n, texts.get(n, n)) for n in r["menu"]))
        a = backend.decide(args.consumer, r["menu"], st)
        b = backend.decide(args.consumer, r["menu"], st)
        if a is None or b is None:
            continue
        if a.chosen == b.chosen:
            same_pick += 1
        if abs(float(a.confidence) - float(b.confidence)) < 1e-9:
            same_conf += 1
        print("  %-8s a=%.6f b=%.6f pick %s/%s" % (
            a.chosen, float(a.confidence), float(b.confidence), a.chosen, b.chosen))
    print("same pick %d/%d, same confidence %d/%d"
          % (same_pick, len(rows), same_conf, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

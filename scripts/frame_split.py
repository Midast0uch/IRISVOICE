"""Split a consumer's cohort by the FRAME shape (the state's signature).

MEASURED 2026-11-04: the replay of the recorded review_verdict states with
the LIVE instruction gives AUROC 0.8448, and the live confidence matches the
replay row by row, yet the report's scoped cohort measures 0.4533. The
cohort must hold rows from TWO frames under one stamp (a frame change needs
its own criteria_version, oracle.md 6.1 rule 3).
"""
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


def auroc(pairs):
    pos = [c for c, ok in pairs if ok]
    neg = [c for c, ok in pairs if not ok]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--consumer", required=True)
    ap.add_argument("--engine", default="")
    ap.add_argument("--stamps", default="")
    a = ap.parse_args()
    stamps = {s.strip() for s in a.stamps.split(",") if s.strip()}
    c = open_store_read_only(app_store_path())
    groups = collections.defaultdict(list)
    for (p,) in c.execute(
        "SELECT interaction_payload FROM system_events WHERE event_type='tool_execution'"
    ):
        try:
            d = json.loads(p or "{}").get("decision")
        except Exception:
            continue
        if not isinstance(d, dict) or d.get("consumer_id") != a.consumer:
            continue
        if a.engine and d.get("engine") != a.engine:
            continue
        if stamps and d.get("criteria_version") not in stamps:
            continue
        conf = d.get("confidence")
        ref = d.get("brain_choice")
        chosen = d.get("chosen")
        if conf is None or ref is None or chosen is None:
            continue
        state = d.get("state") or ""
        sig = state[:40].replace("\n", " ")
        groups[sig].append((float(conf), chosen == ref))
    for sig, pairs in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:8]:
        a_ = auroc(pairs)
        ok = sum(1 for _, o in pairs if o)
        print(f"n={len(pairs):5d} ok={ok:5d} auroc={a_ if a_ is None else round(a_, 4)}  {sig!r}")


if __name__ == "__main__":
    raise SystemExit(main())

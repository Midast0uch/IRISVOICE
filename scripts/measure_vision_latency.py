#!/usr/bin/env python3
"""Live measurement gate for REQ-8 vision latency targets (T13).

REQ-8 AC4: the per-stage instrumentation (T4) must be consumable by a LIVE
measurement script so targets are validated against the running system. This
script parses the structured ``[vision-timing]`` lines the vision path emits
(stage=... duration_ms=...) — from a live log tail OR a captured log file — and
reports per-stage p50/p95/max plus the cold/warm acquire split (REQ-18 AC1).

Targets are NOT asserted here: Decision 13 keeps every latency NUMBER
UNVERIFIED until the step-10 baseline. This script PRODUCES that baseline.

Usage:
    python scripts/measure_vision_latency.py --log backend/logs/irisvoice.log
    python scripts/measure_vision_latency.py --log-tail 2000
    python scripts/measure_vision_latency.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: [vision-timing] run_id=... stage=inference duration_ms=42 count=3 ...
_TIMING_RE = re.compile(
    r"\[vision-timing\]\s+run_id=(?P<run>\S+)\s+stage=(?P<stage>\S+)\s+"
    r"duration_ms=(?P<ms>-?\d+)(?P<rest>.*)"
)
_KV_RE = re.compile(r"(\w+)=([^\s]+)")

_DEFAULT_LOG = Path(__file__).resolve().parents[1] / "backend" / "logs" / "irisvoice.log"


def parse_timings(text: str) -> dict:
    """Parse [vision-timing] lines into {stage: [ms,...]} + cold/warm counts."""
    by_stage: dict = defaultdict(list)
    cold = 0
    warm = 0
    for line in text.splitlines():
        m = _TIMING_RE.search(line)
        if not m:
            continue
        stage = m.group("stage")
        try:
            ms = int(m.group("ms"))
        except (TypeError, ValueError):
            continue
        by_stage[stage].append(ms)
        rest = m.group("rest") or ""
        kv = dict(_KV_RE.findall(rest))
        if stage in ("browser_acquire", "browser_acquire_class"):
            if kv.get("cold") == "True":
                cold += 1
            elif kv.get("warm") == "True":
                warm += 1
    return {"stages": dict(by_stage), "cold": cold, "warm": warm}


def summarize(samples: list) -> dict:
    if not samples:
        return {"n": 0}
    return {
        "n": len(samples),
        "p50": int(statistics.median(samples)),
        "p95": int(_pct(samples, 95)),
        "max": int(max(samples)),
        "mean": int(statistics.mean(samples)),
    }


def _pct(samples: list, pct: float) -> float:
    if not samples:
        return 0.0
    ordered = sorted(samples)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * len(ordered) + 0.5)) - 1))
    return ordered[k]


def main() -> int:
    parser = argparse.ArgumentParser(description="Vision latency measurement (T13)")
    parser.add_argument("--log", default=str(_DEFAULT_LOG), help="log file to read")
    parser.add_argument("--log-tail", type=int, default=0,
                        help="read only the last N lines of the log")
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    args = parser.parse_args()

    path = Path(args.log)
    if not path.is_file():
        print(f"log not found: {path}", file=sys.stderr)
        print("(the vision path has not run yet — start a run, then re-measure)",
              file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    if args.log_tail:
        text = "\n".join(text.splitlines()[-args.log_tail:])

    parsed = parse_timings(text)
    report = {
        "source": str(path),
        "targets": "UNVERIFIED until this baseline (Decision 13)",
        "cold_acquires": parsed["cold"],
        "warm_acquires": parsed["warm"],
        "stages": {s: summarize(v) for s, v in parsed["stages"].items()},
    }
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"source: {path}")
        print(f"cold acquires: {parsed['cold']}  warm acquires: {parsed['warm']}")
        print(f"{'stage':<24}{'n':>6}{'p50':>8}{'p95':>8}{'max':>8}")
        for stage, s in sorted(report["stages"].items()):
            if s.get("n"):
                print(f"{stage:<24}{s['n']:>6}{s['p50']:>8}{s['p95']:>8}{s['max']:>8}")
        print("\nNOTE: targets are set AFTER this baseline (REQ-8 AC4 / Decision 13).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

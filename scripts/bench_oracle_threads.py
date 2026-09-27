#!/usr/bin/env python3
"""Measure Oracle's ORT intra-op thread count on THIS box (REQ-30 AC30.1, T38).

WHY THIS EXISTS. The optimum is host-specific, and a comment in the source is not
a measurement. `decision_backend_onnx.py` records a measured optimum from an
earlier session (intra=4 → p50 181 ms; intra=8 → 277 ms / p95 419 ms on an
8-logical-core host). This script re-derives it here, on the machine that is
about to run it, so the shipped value is a decision with fresh evidence behind
it rather than a number inherited from another box.

The maths does not change with the thread count — an ORT intra-op pool splits the
same work differently — so a thread change CANNOT invalidate the calibrated
threshold. That is why this is a safe lever (unlike a model or menu-width change).

Usage:
    python scripts/bench_oracle_threads.py                 # 1,2,4,6,8 x 25 runs
    python scripts/bench_oracle_threads.py --threads 4 --runs 40
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# The shipped menu shape: cap 6 plus the two control labels, which is what the
# threshold curve was derived at (Decision C / AC25.7).
_MENU = [
    "read_file", "write_file", "list_directory", "recall_memory",
    "vision_analyze_screen", "crawl_query",
]
_FRAME = {"goal": "read the release notes and tell me what changed"}


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    i = min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))
    return xs[i]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=25, help="decisions per setting")
    ap.add_argument("--threads", default="1,2,4,6,8",
                    help="comma-separated intra-op thread counts")
    ap.add_argument("--warmup", type=int, default=3)
    args = ap.parse_args()

    from backend.agent.decision_backend_onnx import GlinerOnnx, resolve_model_dir

    model_dir = resolve_model_dir(None)
    print(f"model dir: {model_dir}")
    counts = [int(x) for x in args.threads.split(",") if x.strip()]

    results: dict[str, dict] = {}
    for n in counts:
        backend = GlinerOnnx(model_dir=model_dir, threads=n)
        if not backend.load():
            print(f"intra={n}: MODEL DID NOT LOAD — skipping")
            continue
        opts = backend.session_options or {}
        effective = opts.get("intra_op_num_threads")
        for _ in range(args.warmup):
            backend.decide("tool_choice", _MENU, _FRAME)
        lat: list[float] = []
        for _ in range(args.runs):
            t0 = time.perf_counter()
            ds = backend.decide("tool_choice", _MENU, _FRAME)
            lat.append((time.perf_counter() - t0) * 1000.0)
            if ds is None:
                print(f"intra={n}: a decision returned None — result unusable")
                break
        p50, p95 = _pct(lat, 0.50), _pct(lat, 0.95)
        results[str(n)] = {
            "requested": n, "effective": effective,
            "p50_ms": round(p50, 1), "p95_ms": round(p95, 1),
            "mean_ms": round(statistics.fmean(lat), 1) if lat else None,
            "min_ms": round(min(lat), 1) if lat else None,
            "runs": len(lat), "session_options": opts,
        }
        print(f"intra={n} (effective {effective}): p50 {p50:.1f} ms  "
              f"p95 {p95:.1f} ms  n={len(lat)}")
        backend.shutdown()

    if results:
        best = min(results.items(), key=lambda kv: kv[1]["p50_ms"])
        print(f"\nBEST p50: intra={best[0]} at {best[1]['p50_ms']} ms")
        print("MEASURED:", json.dumps(results, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

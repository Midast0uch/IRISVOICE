#!/usr/bin/env python3
"""ORT session options for the Oracle on THIS box: thread affinity and spinning.

Question (owner, 2026-10-01): ORT_ENABLE_ALL and the thread counts are already
set and measured (oracle.md S8.1); can thread AFFINITY or the SPIN setting make
a decision faster without changing its answer?

Each variant builds its own InferenceSession on the deployed model, keeps
intra_op = 4 (the calibrated, measured optimum - the numerics depend on the
count, never on affinity or spinning), and runs the shipped tool_choice menu:
  ALONE   - one decision at a time;
  OVERLAP - two threads deciding at once on the one session (the phase domain).
Every distribution is compared BITWISE with the baseline's. Writes
benchmarks/oracle_ort_options.json. Keep the machine quiet while it runs.
"""
from __future__ import annotations

import json
import statistics
import sys
import threading
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

_MENU = ["read_file", "edit_file", "grep_files", "run_command", "DELEGATE", "NONE"]
_GOAL = "read the release notes and tell me what changed in the parser module"

# i7-7700: 4 cores / 8 logical; logical pairs (1,2) (3,4) (5,6) (7,8) share a
# core (ORT affinity ids are 1-based logical processors). intra_op=4 means the
# caller thread + 3 pool threads; an affinity string lists the 3 pool threads.
VARIANTS = {
    "baseline (shipped)": {},
    "spin off": {"session.intra_op.allow_spinning": "0"},
    "affinity: one thread per physical core": {
        "session.intra_op_thread_affinities": "3;5;7"},
    "affinity + spin off": {"session.intra_op_thread_affinities": "3;5;7",
                            "session.intra_op.allow_spinning": "0"},
}


def _pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


def main() -> int:
    import onnxruntime as ort

    from backend.agent.decision_backend_onnx import GlinerOnnx, build_task, resolve_model_dir

    be = GlinerOnnx(model_dir=resolve_model_dir(None))
    assert be.load(), "model did not load"
    runner = be._runner
    model_path = runner.session._model_path
    be.decide("tool_choice", _MENU, {"goal": _GOAL})  # registers criteria
    task = build_task("tool_choice", _MENU)

    def one():
        return tuple(round(v, 12) for v in runner.logits(_GOAL, [task])[task.name].values())

    out, reference = {}, None
    for name, entries in VARIANTS.items():
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        opts.inter_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        for k, v in entries.items():
            opts.add_session_config_entry(k, v)
        runner.session = ort.InferenceSession(model_path, opts, providers=["CPUExecutionProvider"])
        for _ in range(5):
            one()
        alone, dists = [], set()
        for _ in range(40):
            t = time.perf_counter()
            dists.add(one())
            alone.append((time.perf_counter() - t) * 1000)
        lat, lock = [], threading.Lock()
        barrier = threading.Barrier(2)

        def worker():
            barrier.wait()
            for _ in range(20):
                t = time.perf_counter()
                d = one()
                with lock:
                    lat.append((time.perf_counter() - t) * 1000)
                    dists.add(d)

        t0 = time.perf_counter()
        ths = [threading.Thread(target=worker) for _ in range(2)]
        for th in ths:
            th.start()
        for th in ths:
            th.join()
        wall = time.perf_counter() - t0
        if reference is None:
            reference = next(iter(dists))
        out[name] = {
            "alone_p50_ms": round(statistics.median(alone), 1),
            "alone_p95_ms": round(_pct(alone, 0.95), 1),
            "overlap_p50_ms": round(statistics.median(lat), 1),
            "overlap_p95_ms": round(_pct(lat, 0.95), 1),
            "overlap_decisions_per_s": round(40 / wall, 2),
            "identical_to_baseline": dists == {reference},
        }
        print(f"{name:42s} alone p50 {out[name]['alone_p50_ms']:6.1f} p95 {out[name]['alone_p95_ms']:6.1f} | "
              f"overlap p50 {out[name]['overlap_p50_ms']:6.1f} p95 {out[name]['overlap_p95_ms']:6.1f} "
              f"{out[name]['overlap_decisions_per_s']:5.2f}/s | identical {out[name]['identical_to_baseline']}")
    (_REPO / "benchmarks" / "oracle_ort_options.json").write_text(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
